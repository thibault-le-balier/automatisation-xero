#!/usr/bin/env python3
"""Extrait un justificatif d'un e-mail récupéré par le connecteur Gmail (get_message, format RAW).

    python3 mcp_extract.py <fichier_resultat_mcp> <wise_id> [nom_de_la_piece | --eml]

Le connecteur Gmail enregistre les gros résultats dans un fichier JSON ({..., "raw": "<MIME base64url>"}).
On décode le MIME et on écrit dans data/invoices/<wise_id>/ :
  - la pièce jointe demandée (nom exact, sinon le seul PDF du message) ;
  - ou, avec --eml, l'e-mail complet (.eml), pour les reçus sans PDF dont le corps fait foi.
"""
import base64
import email
import json
import re
import sys
from email import policy
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def safe(name):
    return re.sub(r"[^\w.\- #]", "_", name).strip() or "piece"


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def email_to_pdf(msg, dest):
    """Imprime le corps de l'e-mail en PDF avec Chrome, sans aucun accès réseau. Renvoie None en cas d'échec."""
    import html
    import subprocess
    import tempfile
    body = msg.get_body(preferencelist=("html", "plain"))
    if body is None or not Path(CHROME).exists():
        return None
    content = body.get_content()
    if body.get_content_type() == "text/plain":
        content = f"<pre style='white-space:pre-wrap;font-family:sans-serif'>{html.escape(content)}</pre>"
    head = "".join(f"<div><b>{k} :</b> {html.escape(str(msg[k] or ''))}</div>" for k in ("From", "To", "Date", "Subject"))
    page = f"<html><head><meta charset='utf-8'></head><body><div style='font-family:sans-serif;font-size:12px;border-bottom:1px solid #999;margin-bottom:12px;padding-bottom:6px'>{head}</div>{content}</body></html>"
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "mail.html"
        src.write_text(page, encoding="utf-8")
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--host-resolver-rules=MAP * ~NOTFOUND", "--blink-settings=imagesEnabled=false",
                        f"--user-data-dir={tmp}/profile", f"--print-to-pdf={dest}", src.as_uri()],
                       capture_output=True, timeout=60)
    return dest if dest.exists() and dest.stat().st_size > 0 else None


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, wise_id = Path(sys.argv[1]), sys.argv[2]
    wanted = sys.argv[3] if len(sys.argv) > 3 else None
    d = json.loads(src.read_text())
    raw = d["raw"]
    data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    out_dir = ROOT / "data" / "invoices" / wise_id
    out_dir.mkdir(parents=True, exist_ok=True)

    msg = email.message_from_bytes(data, policy=policy.default)
    if wanted == "--eml":
        dest = out_dir / f"email_{d['id']}.eml"
        dest.write_bytes(data)
        pdf = email_to_pdf(msg, out_dir / f"email_{d['id']}.pdf")
        print(f"OK {(pdf or dest).relative_to(ROOT)} {(pdf or dest).stat().st_size} o")
        return

    parts = [p for p in msg.iter_attachments() if p.get_filename()]
    pick = [p for p in parts if wanted and p.get_filename().strip().lower() == wanted.strip().lower()]
    if not pick and not wanted:
        pick = [p for p in parts if p.get_content_type() == "application/pdf"][:1]
    if not pick:
        sys.exit(f"ERREUR pièce « {wanted} » absente ; présentes : {[p.get_filename() for p in parts]}")
    payload = pick[0].get_payload(decode=True)
    dest = out_dir / safe(pick[0].get_filename())
    dest.write_bytes(payload)
    kind = "PDF" if payload[:5] == b"%PDF-" else pick[0].get_content_type()
    print(f"OK {dest.relative_to(ROOT)} {len(payload)} o {kind}")


if __name__ == "__main__":
    main()
