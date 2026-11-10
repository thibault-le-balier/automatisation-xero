#!/usr/bin/env python3
"""Associe les factures d'un dossier (un sous-dossier par fournisseur) aux opérations Wise et les joint dans Xero.

    python3 -m smartketing.attach_folder "<dossier>"         # simulation : liste les correspondances
    python3 -m smartketing.attach_folder "<dossier>" --go    # joint les factures

Correspondance = même fournisseur + même montant dans la devise de facturation + date à 4 jours près.
On joint si l'opération n'a pas de pièce, ou seulement un e-mail sans montant (email_*.pdf généré par mcp_extract).
"""
import csv
import json
import re
import subprocess
import sys
import urllib.parse
from datetime import date
from pathlib import Path

from smartketing import xero_api as x
from commun.pieces import dates_in

from commun import ROOT
from smartketing import DATA
WORK = DATA / "work"
VENDORS = {"cursor": r"^cursor", "make": r"^make$", "openai": r"openai|chatgpt", "xero": r"^xero$"}
MAX_GAP = 4


def text(p):
    return subprocess.run(["pdftotext", "-layout", "-q", str(p), "-"], capture_output=True, text=True).stdout


def invoices(folder):
    out = []
    for vdir in sorted(p for p in folder.iterdir() if p.is_dir()):
        vendor = vdir.name.lower()
        manifest = vdir / "manifest.csv"
        if manifest.exists():  # Cursor : le manifest donne date, montant, devise et statut
            for m in csv.DictReader(open(manifest)):
                if m["Status"] == "paid":
                    out.append((vendor, date.fromisoformat(m["Date"]), float(m["Amount"]), m["Currency"], vdir / m["File"]))
            continue
        for pdf in sorted(vdir.glob("*.pdf")):
            t = text(pdf)
            issue = re.search(r"(?:Date of issue|Issue date)\s+.*?([A-Z][a-z]{2,8}\.? \d{1,2}, 20\d{2})", t, re.S)
            ds = dates_in(issue.group(1)) if issue else dates_in(t)
            tot = (re.search(r"\n\s*Total\s+(?:USD\$|\$|€|EUR\s*)?([\d,]+\.\d{2})", t)
                   or re.search(r"Amount (?:due|paid)\s+(?:USD\$|\$|€)?([\d,]+\.\d{2})", t))
            if ds and tot:
                ccy = "USD" if ("$" in t or "USD" in t) else "EUR"
                out.append((vendor, min(ds), float(tot.group(1).replace(",", "")), ccy, pdf))
    return out


def main():
    folder = Path(sys.argv[1]).resolve()
    go = "--go" in sys.argv
    lines = [r for r in csv.DictReader(open(WORK / "wise_lines.csv")) if r["line"] == "main" and r["xero_id"]]
    used, plan = set(), []
    for vendor, d, amount, ccy, pdf in invoices(folder):
        rx = VENDORS.get(vendor)
        cands = [w for w in lines if rx and re.search(rx, w["counterparty"].lower()) and w["wise_id"] not in used
                 and w["orig_currency"] == ccy and abs(float(w["orig_amount"] or 0) - amount) < 0.005
                 and abs((date.fromisoformat(w["date"]) - d).days) <= MAX_GAP]
        cands.sort(key=lambda w: abs((date.fromisoformat(w["date"]) - d).days))
        if not cands:
            if d.year == 2026:
                print(f"  sans opération : {pdf.name} ({d} {amount} {ccy})")
            continue
        w = cands[0]
        used.add(w["wise_id"])
        plan.append((w, pdf, d, amount, ccy))

    todo = []
    for w, pdf, d, amount, ccy in plan:
        existing = [a["FileName"] for a in x.get(f"BankTransactions/{w['xero_id']}/Attachments")["Attachments"]]
        weak = all(n.startswith("email_") for n in existing)
        action = "déjà joint" if pdf.name in existing else ("à joindre" if weak else "a déjà une facture")
        print(f"  {w['date']} {w['counterparty'][:22]:22s} {w['amount']:>7} {w['currency']} ({amount} {ccy}) "
              f"<- {pdf.name[:48]:48s} [{action}{' — remplace un e-mail sans montant' if existing and weak and action == 'à joindre' else ''}]")
        if action == "à joindre":
            todo.append((w, pdf))
    print(f"\n{len(plan)} correspondances, {len(todo)} factures à joindre")
    if not go:
        print("Simulation uniquement. Relancer avec --go.")
        return
    for w, pdf in todo:
        x.upload(f"BankTransactions/{w['xero_id']}/Attachments/{urllib.parse.quote(pdf.name)}", pdf.read_bytes(), "application/pdf")
        with open(WORK / "push_log.jsonl", "a") as fh:
            fh.write(json.dumps({"action": "attach", "wise_id": w["wise_id"], "id": w["xero_id"],
                                 "file": str(pdf.relative_to(ROOT)), "status": "ok"}, ensure_ascii=False) + "\n")
        with open(WORK / "docs_mcp.jsonl", "a") as fh:
            fh.write(json.dumps({"wise_id": w["wise_id"], "source": "dossier_thibault_manquant",
                                 "file": str(pdf.relative_to(ROOT))}, ensure_ascii=False) + "\n")
    print(f"{len(todo)} factures jointes.")


if __name__ == "__main__":
    main()
