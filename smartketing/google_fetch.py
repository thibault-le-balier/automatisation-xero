#!/usr/bin/env python3
"""Télécharge les justificatifs trouvés dans Gmail et Drive (lecture seule).

    python3 google_fetch.py        # 1re fois : ouvre le navigateur (Gmail + Drive en lecture seule)

Entrée : data/work/found/*.json (résultats vérifiés de la recherche)
Sortie : data/invoices/<wise_id>/<fichier> et data/work/docs_google.json
Prérequis dans .env : GOOGLE_CLIENT_ID et GOOGLE_CLIENT_SECRET (client OAuth « Application de bureau »).
"""
import base64
import hashlib
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from xero_auth import load_env

ROOT = Path(__file__).resolve().parent
TOKENS = ROOT / ".google_tokens.json"
WORK = ROOT / "data" / "work"
INVOICES = ROOT / "data" / "invoices"
PORT = 8766
REDIRECT_URI = f"http://127.0.0.1:{PORT}/"
SCOPES = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/drive.readonly"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE = "https://www.googleapis.com/drive/v3"


def http(method, url, headers=None, data=None, raw=False):
    for attempt in range(5):
        req = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                return body if raw else json.loads(body or b"null")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"HTTP {e.code} {url}: {e.read().decode(errors='replace')[:500]}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def token_request(env, **form):
    form.update(client_id=env["GOOGLE_CLIENT_ID"], client_secret=env["GOOGLE_CLIENT_SECRET"])
    tok = http("POST", "https://oauth2.googleapis.com/token",
               {"Content-Type": "application/x-www-form-urlencoded"}, urllib.parse.urlencode(form).encode())
    tok["expires_at"] = time.time() + tok["expires_in"] - 60
    return tok


def authorize(env):
    state, verifier = secrets.token_urlsafe(16), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": env["GOOGLE_CLIENT_ID"], "redirect_uri": REDIRECT_URI, "response_type": "code",
        "scope": SCOPES, "state": state, "access_type": "offline", "prompt": "consent",
        "code_challenge": challenge, "code_challenge_method": "S256"})
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "state" not in q:
                self.send_response(404)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("Accès Google OK, tu peux fermer cet onglet.".encode())

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", PORT), Callback)
    print(f"Autorise l'accès Google (lecture seule) :\n{url}\n")
    webbrowser.open(url)
    while not result:
        server.handle_request()
    server.server_close()
    if result.get("state") != state or "code" not in result:
        sys.exit(f"Autorisation refusée : {result}")
    return token_request(env, grant_type="authorization_code", code=result["code"],
                         redirect_uri=REDIRECT_URI, code_verifier=verifier)


def access_token(env):
    if not TOKENS.exists():
        tok = authorize(env)
    else:
        tok = json.loads(TOKENS.read_text())
        if time.time() < tok["expires_at"]:
            return tok["access_token"]
        fresh = token_request(env, grant_type="refresh_token", refresh_token=tok["refresh_token"])
        fresh.setdefault("refresh_token", tok["refresh_token"])
        tok = fresh
    TOKENS.write_text(json.dumps(tok, indent=1))
    TOKENS.chmod(0o600)
    return tok["access_token"]


def b64(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def safe(name):
    return re.sub(r"[^\w.\- #]", "_", name).strip() or "piece"


def walk(part):
    yield part
    for p in part.get("parts", []) or []:
        yield from walk(p)


def gmail_attachment(auth, msg_id, filename):
    msg = http("GET", f"{GMAIL}/messages/{msg_id}?format=full", auth)
    parts = [p for p in walk(msg["payload"]) if p.get("filename")]
    for p in parts:
        if p["filename"] == filename or p["filename"].strip().lower() == filename.strip().lower():
            body = p["body"]
            data = body.get("data") or http("GET", f"{GMAIL}/messages/{msg_id}/attachments/{body['attachmentId']}", auth)["data"]
            return p["filename"], b64(data), p.get("mimeType", "application/octet-stream")
    raise LookupError(f"pièce « {filename} » absente du message {msg_id} (présentes : {[p['filename'] for p in parts]})")


def gmail_eml(auth, msg_id):
    raw = http("GET", f"{GMAIL}/messages/{msg_id}?format=raw", auth)["raw"]
    return f"email_{msg_id}.eml", b64(raw), "message/rfc822"


def drive_file(auth, file_id):
    meta = http("GET", f"{DRIVE}/files/{file_id}?fields=name,mimeType&supportsAllDrives=true", auth)
    if meta["mimeType"].startswith("application/vnd.google-apps"):
        data = http("GET", f"{DRIVE}/files/{file_id}/export?mimeType=application/pdf", auth, raw=True)
        return meta["name"] + ".pdf", data, "application/pdf"
    data = http("GET", f"{DRIVE}/files/{file_id}?alt=media&supportsAllDrives=true", auth, raw=True)
    return meta["name"], data, meta["mimeType"]


def main():
    env = load_env()
    missing = [k for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET") if not env.get(k)]
    if missing:
        sys.exit(f"À remplir dans .env : {', '.join(missing)}")
    auth = {"Authorization": f"Bearer {access_token(env)}"}
    lines = [l for f in sorted((WORK / "found").glob("*.json")) for l in json.load(open(f))]
    docs, errors = [], []
    for l in lines:
        if not l.get("found"):
            continue
        try:
            if l["source"] == "gmail_attachment":
                name, data, mime = gmail_attachment(auth, l["gmail_message_id"], l["attachment_filename"])
            elif l["source"] == "gmail_body":
                name, data, mime = gmail_eml(auth, l["gmail_message_id"])
            elif l["source"] == "drive":
                name, data, mime = drive_file(auth, l["drive_file_id"])
            else:
                continue
        except (LookupError, RuntimeError, KeyError) as e:
            errors.append((l["wise_id"], str(e)[:200]))
            continue
        dest = INVOICES / l["wise_id"] / safe(name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        docs.append({"wise_id": l["wise_id"], "source": l["source"], "file": str(dest.relative_to(ROOT)),
                     "mime": mime, "match": l.get("match"), "doc_number": l.get("doc_number")})
        print(f"{l['wise_id']:34s} {len(data):>8} o  {name}")
    (WORK / "docs_google.json").write_text(json.dumps(docs, indent=1, ensure_ascii=False))
    print(f"\n{len(docs)} justificatifs téléchargés, {len(errors)} erreurs")
    for e in errors:
        print("  ERREUR", *e)


if __name__ == "__main__":
    main()
