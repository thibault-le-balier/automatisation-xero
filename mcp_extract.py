#!/usr/bin/env python3
"""Transforme un résultat des connecteurs Gmail / Drive en justificatif dans data/invoices/<wise_id>/.

    python3 mcp_extract.py gmail    <resultat_get_message_RAW.json> <wise_id> <nom_piece | --eml>
    python3 mcp_extract.py gmailraw <fichier_texte_base64url>       <wise_id> <nom_piece | --eml>
    python3 mcp_extract.py drive    <resultat_download_file_content.json> <wise_id>
    python3 mcp_extract.py b64      <fichier_texte_base64>          <wise_id> <nom_fichier>
    python3 mcp_extract.py text     <fichier_texte>                 <wise_id> <nom_de_base>

Les gros résultats des connecteurs sont enregistrés par Claude Code dans un fichier JSON : on le décode ici.
--eml (ou « text ») : le corps de l'e-mail fait foi ; on l'imprime en PDF avec Chrome, sans accès réseau.
Chaque fichier produit est contrôlé (PDF complet, image lisible). Une ligne est ajoutée à data/work/docs_mcp.jsonl.
"""
import base64
import email
import html
import json
import re
import subprocess
import sys
import tempfile
from email import policy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LOG = ROOT / "data" / "work" / "docs_mcp.jsonl"


def safe(name):
    return re.sub(r"[^\w.\- #]", "_", name).strip() or "piece"


def b64decode(text, urlsafe=False):
    text = re.sub(r"\s+", "", text)
    text += "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text) if urlsafe else base64.b64decode(text)


def pdf_streams_problem(data):
    """Décompresse chaque flux FlateDecode (après ASCII85 si présent) : une erreur = fichier abîmé."""
    import zlib
    for m in re.finditer(rb"<<(.{0,400}?)>>\s*stream\r?\n", data, re.S):
        head = m.group(1)
        if b"FlateDecode" not in head:
            continue
        end = data.find(b"endstream", m.end())
        raw = data[m.end():end]
        try:
            if b"ASCII85Decode" in head:
                raw = base64.a85decode(raw.strip().removeprefix(b"<~").removesuffix(b"~>"), adobe=False, ignorechars=b" \t\r\n")
            o = zlib.decompressobj()
            o.decompress(raw)
            if not o.eof:
                return "PDF tronqué (flux incomplet)"
        except (zlib.error, ValueError):
            return "PDF corrompu (flux illisible)"
    return None


def check(path):
    """Renvoie None si le fichier est sain, sinon la raison."""
    data = path.read_bytes()
    if not data:
        return "fichier vide"
    if path.suffix.lower() == ".pdf" or data[:5] == b"%PDF-":
        if data[:5] != b"%PDF-" or b"%%EOF" not in data[-2048:]:
            return "PDF tronqué"
        m = re.findall(rb"startxref\s+(\d+)", data[-2048:])
        if m:
            off = int(m[-1])
            if not (data[off:off + 4] == b"xref" or re.match(rb"\d+\s+\d+\s+obj", data[off:off + 20])):
                return "PDF corrompu (table xref)"
        return pdf_streams_problem(data)
    if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".heic"):
        r = subprocess.run(["sips", "-g", "pixelWidth", str(path)], capture_output=True, text=True)
        return None if "pixelWidth" in r.stdout else "image illisible"
    return None


def to_pdf(page_html, dest):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "mail.html"
        src.write_text(page_html, encoding="utf-8")
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--host-resolver-rules=MAP * ~NOTFOUND", "--blink-settings=imagesEnabled=false",
                        f"--user-data-dir={tmp}/profile", f"--print-to-pdf={dest}", src.as_uri()],
                       capture_output=True, timeout=90)
    return dest if dest.exists() and dest.stat().st_size > 0 else None


def header_block(pairs):
    return ("<div style='font-family:sans-serif;font-size:12px;border-bottom:1px solid #999;"
            "margin-bottom:12px;padding-bottom:6px'>"
            + "".join(f"<div><b>{k} :</b> {html.escape(str(v or ''))}</div>" for k, v in pairs) + "</div>")


def email_to_pdf(msg, dest):
    body = msg.get_body(preferencelist=("html", "plain"))
    if body is None:
        return None
    content = body.get_content()
    if body.get_content_type() == "text/plain":
        content = f"<pre style='white-space:pre-wrap;font-family:sans-serif'>{html.escape(content)}</pre>"
    head = header_block([(k, msg[k]) for k in ("From", "To", "Date", "Subject")])
    return to_pdf(f"<html><head><meta charset='utf-8'></head><body>{head}{content}</body></html>", dest)


def from_mime(data, msg_id, out_dir, wanted):
    msg = email.message_from_bytes(data, policy=policy.default)
    if wanted == "--eml":
        (out_dir / f"email_{msg_id}.eml").write_bytes(data)
        return email_to_pdf(msg, out_dir / f"email_{msg_id}.pdf") or out_dir / f"email_{msg_id}.eml"
    parts = [p for p in msg.iter_attachments() if p.get_filename()]
    pick = [p for p in parts if p.get_filename().strip().lower() == wanted.strip().lower()]
    if not pick:
        pick = [p for p in parts if wanted.strip().lower() in p.get_filename().strip().lower()]
    if not pick:
        raise LookupError(f"pièce « {wanted} » absente ; présentes : {[p.get_filename() for p in parts]}")
    dest = out_dir / safe(pick[0].get_filename())
    dest.write_bytes(pick[0].get_payload(decode=True))
    return dest


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    mode, src, wise_id = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    arg = sys.argv[4] if len(sys.argv) > 4 else ""
    out_dir = ROOT / "data" / "invoices" / wise_id
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        if mode == "gmail":
            d = json.loads(src.read_text())
            dest = from_mime(b64decode(d["raw"], urlsafe=True), d.get("id", "msg"), out_dir, arg or "--eml")
        elif mode == "gmailraw":
            raw = src.read_text()
            try:
                raw = json.loads(raw)["raw"]
            except (ValueError, KeyError, TypeError):
                pass
            dest = from_mime(b64decode(raw, urlsafe=True), src.stem, out_dir, arg or "--eml")
        elif mode == "drive":
            d = json.loads(src.read_text())
            dest = out_dir / safe(d.get("title") or d.get("name") or "fichier_drive")
            dest.write_bytes(b64decode(d["content"]))
        elif mode == "b64":
            dest = out_dir / safe(arg or src.stem)
            dest.write_bytes(b64decode(src.read_text()))
        elif mode == "text":
            text = src.read_text()
            dest = to_pdf("<html><head><meta charset='utf-8'></head><body><pre style='white-space:pre-wrap;"
                          f"font-family:sans-serif'>{html.escape(text)}</pre></body></html>",
                          out_dir / f"{safe(arg or src.stem)}.pdf")
            if dest is None:
                dest = out_dir / f"{safe(arg or src.stem)}.txt"
                dest.write_text(text)
        else:
            sys.exit(f"mode inconnu : {mode}")
    except (LookupError, KeyError, ValueError) as e:
        print(f"ERREUR {wise_id} : {e}")
        sys.exit(1)
    problem = check(dest)
    if problem:
        dest.unlink()
        print(f"ERREUR {wise_id} : {problem}, fichier supprimé")
        sys.exit(1)
    with open(LOG, "a") as fh:
        fh.write(json.dumps({"wise_id": wise_id, "source": f"mcp_{mode}", "file": str(dest.relative_to(ROOT))},
                            ensure_ascii=False) + "\n")
    print(f"OK {dest.relative_to(ROOT)} {dest.stat().st_size} o")


if __name__ == "__main__":
    main()
