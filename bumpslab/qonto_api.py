"""Client minimal pour l'API Qonto (v2) : lecture paginée et envoi de justificatifs.

Authentification par clé : en-tête « Authorization: <identifiant>:<clé secrète> ».
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from bumpslab import QONTO_LOGIN
from commun import load_env

BASE = "https://thirdparty.qonto.com/v2"
_KEY = None


def _auth():
    global _KEY
    if _KEY is None:
        _KEY = load_env()["QONTO_API_KEY"]
    return f"{QONTO_LOGIN}:{_KEY}"


def _request(method, path, params=None, data=None, headers=None):
    url = f"{BASE}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    for attempt in range(6):
        h = {"Authorization": _auth(), "Accept": "application/json", **(headers or {})}
        req = urllib.request.Request(url, method=method, headers=h, data=data)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = int(e.headers.get("Retry-After", 2 ** attempt))
                print(f"  {e.code} sur {path}, nouvel essai dans {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code} {method} {path}: {e.read().decode(errors='replace')[:1000]}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if method != "GET":
                raise  # pas de nouvel essai automatique pour une écriture : risque de doublon
            print(f"  réseau ({e}) sur {path}, nouvel essai dans {2 ** attempt}s", file=sys.stderr)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Abandon après plusieurs essais : {method} {path}")


def get(path, **params):
    return _request("GET", path, params or None)


def get_all(path, key, **params):
    """Parcourt toutes les pages (100 éléments par page)."""
    out, page = [], 1
    while True:
        r = get(path, page=page, per_page=100, **params)
        out.extend(r[key])
        if not r.get("meta", {}).get("next_page"):
            return out
        page += 1


def upload_attachment(transaction_id, filename, raw, content_type):
    """Joint un fichier (PDF, JPEG, PNG) à une transaction."""
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n").encode() + raw + f"\r\n--{boundary}--\r\n".encode()
    return _request("POST", f"transactions/{transaction_id}/attachments", data=body,
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                             "X-Qonto-Idempotency-Key": str(uuid.uuid4())})
