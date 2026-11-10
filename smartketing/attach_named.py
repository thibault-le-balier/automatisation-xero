#!/usr/bin/env python3
"""Joint dans Xero les justificatifs d'un dossier dont le nom de fichier contient l'identifiant Wise
(ex. 2026-01-25_1Password_20.85EUR_CARD_TRANSACTION-3383484493.pdf), puis les range dans <dossier>/archive/.

    python3 attach_named.py "<dossier>"         # simulation : contrôle chaque pièce
    python3 attach_named.py "<dossier>" --go    # joint dans Xero et archive les pièces jointes

Contrôles avant de joindre :
- l'identifiant existe dans le relevé Wise et l'opération est dans Xero ;
- le fichier est intact (PDF complet, image lisible) ;
- pour un PDF, le montant facturé (devise d'origine) et une date à 5 jours près de l'opération figurent dans le texte.
  Sinon la pièce est mise de côté (« à vérifier ») et n'est ni jointe ni archivée.
- les photos sont contrôlées à l'œil avant le --go (le script ne lit pas les images).
Les photos HEIC sont converties en JPEG, 2 400 px de côté au plus (Xero n'accepte pas le HEIC).
On joint si l'opération n'a pas de pièce, ou seulement un e-mail sans montant (email_*.pdf).
"""
import csv
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

import xero_api as x
from datetime import date

from index_folder import amount_variants, dates_in
from mcp_extract import check

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "data" / "work"
ID = re.compile(r"((?:CARD_TRANSACTION|TRANSFER|BALANCE_TRANSACTION|DIRECT_DEBIT_TRANSACTION)-\d+)")
MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def text(p):
    return subprocess.run(["pdftotext", "-layout", "-q", str(p), "-"], capture_output=True, text=True).stdout


def amounts(x):
    """Variantes d'écriture du montant, y compris sans zéro final (« 32.4 euros »)."""
    out = amount_variants(x)
    if f"{x:.2f}".endswith("0"):
        out |= {f"{x:.1f}", f"{x:.1f}".replace(".", ",")}
    return out


def to_jpeg(src, wise_id):
    out_dir = ROOT / "data" / "invoices" / wise_id
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / (src.stem + ".jpg")
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", "-Z", "2400", str(src), "--out", str(dest)],
                   capture_output=True)
    return dest


def main():
    folder = Path(sys.argv[1]).resolve()
    go = "--go" in sys.argv
    archive = folder / "archive"
    lines = {r["wise_id"]: r for r in csv.DictReader(open(WORK / "wise_lines.csv")) if r["line"] == "main"}
    files = sorted(p for p in folder.rglob("*") if p.is_file() and archive not in p.parents and ID.search(p.name))

    todo, held = [], []
    for f in files:
        wid = ID.search(f.name).group(1)
        w = lines.get(wid)
        rel = f.relative_to(folder)
        if not w or not w["xero_id"]:
            held.append((rel, "identifiant absent du relevé Wise ou opération absente de Xero"))
            continue
        upload = to_jpeg(f, wid) if f.suffix.lower() == ".heic" else f
        problem = check(upload)
        if problem:
            held.append((rel, problem))
            continue
        foreign = w["orig_currency"] and w["orig_currency"] != w["currency"]
        billed = float(w["orig_amount"] if foreign else w["amount"])
        ccy = w["orig_currency"] if foreign else w["currency"]
        if upload.suffix.lower() == ".pdf":
            t = text(upload)
            if not any(v in t for v in amounts(billed)):
                held.append((rel, f"montant {billed:.2f} {ccy} introuvable dans le document"))
                continue
            d = date.fromisoformat(w["date"])
            gaps = [abs((x - d).days) for x in dates_in(t)]
            if not gaps or min(gaps) > 5:
                held.append((rel, f"aucune date proche du {d:%d/%m/%Y} dans le document"))
                continue
            proof = f"{billed:.2f} {ccy}, date à {min(gaps)} j"
        else:
            proof = "photo (contrôle visuel)"
        existing = [a["FileName"] for a in x.get(f"BankTransactions/{w['xero_id']}/Attachments")["Attachments"]]
        weak = all(n.startswith("email_") for n in existing)
        state = "déjà joint" if upload.name in existing else ("à joindre" if weak else "a déjà une facture")
        print(f"  {w['date']} {w['counterparty'][:22]:22s} {float(w['amount']):>8,.2f} {w['currency']} "
              f"<- {str(rel)[:62]:62s} [{proof} ; {state}]")
        todo.append((f, upload, w, state))

    for rel, why in held:
        print(f"  À VÉRIFIER {rel} : {why}")
    n_new = sum(s == "à joindre" for *_, s in todo)
    print(f"\n{len(files)} pièces, {n_new} à joindre, {len(todo) - n_new} déjà justifiées, {len(held)} à vérifier")
    if not go:
        print("Simulation uniquement. Relancer avec --go.")
        return

    for f, upload, w, state in todo:
        if state == "à joindre":
            x.upload(f"BankTransactions/{w['xero_id']}/Attachments/{urllib.parse.quote(upload.name)}",
                     upload.read_bytes(), MIME.get(upload.suffix.lower(), "application/octet-stream"))
        dest = archive / f.relative_to(folder)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), dest)
        kept = dest if upload == f else upload  # le JPEG converti reste dans data/invoices
        if state == "à joindre":
            with open(WORK / "push_log.jsonl", "a") as fh:
                fh.write(json.dumps({"action": "attach", "wise_id": w["wise_id"], "id": w["xero_id"],
                                     "file": str(kept.relative_to(ROOT)), "status": "ok"}, ensure_ascii=False) + "\n")
            with open(WORK / "docs_mcp.jsonl", "a") as fh:
                fh.write(json.dumps({"wise_id": w["wise_id"], "source": f"dossier_{folder.name}",
                                     "file": str(kept.relative_to(ROOT))}, ensure_ascii=False) + "\n")
    for d in sorted((p for p in folder.rglob("*") if p.is_dir() and archive not in p.parents and p != archive),
                    key=lambda p: -len(p.parts)):
        if all(p.name == ".DS_Store" for p in d.iterdir()):
            shutil.rmtree(d)  # sous-dossiers vidés par l'archivage
    print(f"{n_new} pièces jointes dans Xero, {len(todo)} pièces archivées dans {archive.relative_to(ROOT)}.")


if __name__ == "__main__":
    main()
