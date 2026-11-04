#!/usr/bin/env python3
"""Connexion OAuth2 à Xero pour SMARTKETING LIMITED. Ce script ne fait que lire.

    python3 xero_auth.py          # ouvre le navigateur, enregistre les jetons, teste la connexion
    python3 xero_auth.py --test   # réutilise les jetons enregistrés (rafraîchis si besoin)

Les autres scripts réutilisent get_access_token() pour appeler l'API.
"""
import base64
import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOKENS = ROOT / ".xero_tokens.json"
PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/callback"
ORG_NAME = "SMARTKETING LIMITED"
# Les apps créées après le 2 mars 2026 doivent utiliser les scopes « granulaires ».
SCOPES = " ".join([
    "offline_access",               # jeton de rafraîchissement (60 jours)
    "accounting.settings.read",     # plan comptable, comptes bancaires, taux de TVA
    "accounting.contacts",          # fournisseurs
    "accounting.banktransactions",  # dépenses / recettes / virements internes
    "accounting.attachments",       # factures jointes
    "accounting.invoices.read",     # bills déjà saisies (anti-doublon)
    "accounting.payments.read",
])
AUTHORIZE_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"
API = "https://api.xero.com"


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("\"'")
    return env


def http(method, url, headers=None, data=None):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        sys.exit(f"Erreur HTTP {e.code} sur {url} :\n{e.read().decode(errors='replace')[:800]}")


def token_request(env, **form):
    creds = f"{env['XERO_CLIENT_ID']}:{env['XERO_CLIENT_SECRET']}".encode()
    tokens = http(
        "POST", TOKEN_URL,
        {"Authorization": "Basic " + base64.b64encode(creds).decode(),
         "Content-Type": "application/x-www-form-urlencoded"},
        urllib.parse.urlencode(form).encode(),
    )
    tokens["expires_at"] = time.time() + tokens["expires_in"] - 60
    return tokens


def save(tokens):
    TOKENS.write_text(json.dumps(tokens, indent=2))
    TOKENS.chmod(0o600)


def get_access_token(env=None):
    """Renvoie (access_token, tenant_id), rafraîchis si besoin."""
    env = env or load_env()
    tokens = json.loads(TOKENS.read_text())
    if time.time() >= tokens["expires_at"]:
        fresh = token_request(env, grant_type="refresh_token", refresh_token=tokens["refresh_token"])
        fresh["tenant_id"], fresh["tenant_name"] = tokens["tenant_id"], tokens["tenant_name"]
        tokens = fresh
        save(tokens)  # le refresh token change à chaque rafraîchissement
    return tokens["access_token"], tokens["tenant_id"]


def authorize(env):
    state = secrets.token_urlsafe(16)
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": env["XERO_CLIENT_ID"],
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    })
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()})
            ok = "code" in result and result.get("state") == state
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Connexion Xero OK, tu peux fermer cet onglet." if ok else f"Échec : {result}"
            self.wfile.write(msg.encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", PORT), Callback)
    print(f"Autorise l'accès dans le navigateur (sinon ouvre ce lien) :\n{url}\n")
    webbrowser.open(url)
    while not result:
        server.handle_request()
    server.server_close()
    if result.get("state") != state or "code" not in result:
        sys.exit(f"Autorisation refusée ou invalide : {result}")
    return token_request(env, grant_type="authorization_code",
                         code=result["code"], redirect_uri=REDIRECT_URI)


def pick_tenant(access_token):
    connections = http("GET", f"{API}/connections", {"Authorization": f"Bearer {access_token}"})
    for c in connections:
        if c.get("tenantName", "").upper() == ORG_NAME:
            return c["tenantId"], c["tenantName"]
    sys.exit(f"{ORG_NAME} introuvable parmi : {[c.get('tenantName') for c in connections]}")


def test(env):
    access, tenant = get_access_token(env)
    headers = {"Authorization": f"Bearer {access}", "xero-tenant-id": tenant,
               "Accept": "application/json"}
    org = http("GET", f"{API}/api.xro/2.0/Organisation", headers)["Organisations"][0]
    print(f"OK : {org['Name']} ({org['CountryCode']}, devise de base {org['BaseCurrency']})")
    where = urllib.parse.quote('Type=="BANK"')
    for a in http("GET", f"{API}/api.xro/2.0/Accounts?where={where}", headers)["Accounts"]:
        print(f"  compte bancaire : {a['Name']} [{a.get('CurrencyCode')}] {a['Status']} id={a['AccountID']}")


if __name__ == "__main__":
    env = load_env()
    missing = [k for k in ("XERO_CLIENT_ID", "XERO_CLIENT_SECRET") if not env.get(k)]
    if missing:
        sys.exit(f"À remplir dans .env : {', '.join(missing)}")
    if "--test" not in sys.argv or not TOKENS.exists():
        tokens = authorize(env)
        tokens["tenant_id"], tokens["tenant_name"] = pick_tenant(tokens["access_token"])
        save(tokens)
    test(env)
