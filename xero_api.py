"""Client minimal pour l'API Accounting de Xero (pagination, limite de débit, envoi de fichiers)."""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from xero_auth import get_access_token

BASE = "https://api.xero.com/api.xro/2.0"


def _request(method, path, params=None, body=None, raw=None, content_type=None, accept=None):
    url = f"{BASE}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        access, tenant = get_access_token()
        headers = {"Authorization": f"Bearer {access}", "xero-tenant-id": tenant,
                   "Accept": accept or "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif raw is not None:
            data = raw
            headers["Content-Type"] = content_type or "application/octet-stream"
        req = urllib.request.Request(url, method=method, headers=headers, data=data)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = resp.read()
                return payload if accept else json.loads(payload or b"null")
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = int(e.headers.get("Retry-After", 2 ** attempt))
                print(f"  {e.code} sur {path}, nouvel essai dans {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            detail = e.read().decode(errors="replace")
            raise RuntimeError(f"HTTP {e.code} {method} {path}: {detail[:2000]}") from None
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
        chunk = get(path, page=page, **params)[key]
        out.extend(chunk)
        if len(chunk) < 100:
            return out
        page += 1


def put(path, body, **params):
    return _request("PUT", path, params or None, body=body)


def post(path, body, **params):
    return _request("POST", path, params or None, body=body)


def upload(path, raw, content_type):
    return _request("PUT", path, raw=raw, content_type=content_type)


def download(path, mime):
    """Renvoie les octets bruts d'une pièce jointe."""
    return _request("GET", path, accept=mime)
