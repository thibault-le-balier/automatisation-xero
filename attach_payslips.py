#!/usr/bin/env python3
"""Joint les bulletins de paie aux virements de salaire et aux paiements PAYE de Revenue.

    python3 attach_payslips.py          # simulation
    python3 attach_payslips.py --go     # joint dans Xero

- Virement de salaire : bulletin du même salarié, même net, payé à 10 jours près.
- Paiement Revenue du mois M+1 : bulletins du mois M (tous les salariés), seulement si la somme
  de leurs retenues (impôt + USC + PRSI) est égale au montant prélevé, à 0,05 € près.
"""
import csv
import json
import re
import subprocess
import sys
import urllib.parse
from datetime import date
from pathlib import Path

import xero_api as x

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "data" / "work"
FOLDERS = [ROOT / "Wise with invoices pdf/thibault manquant/archive/salaires",
           ROOT / "Wise with invoices pdf/01_Comptabilité/Payslips"]
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
          "nov": 11, "dec": 12, "janv": 1, "fev": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7}


def euros(s):
    return float(s.replace("€", "").replace(",", ""))


def parse(pdf):
    t = subprocess.run(["pdftotext", "-layout", "-q", str(pdf), "-"], capture_output=True, text=True).stdout
    name = re.search(r"(Thibault Le Balier|Hugo Pierre Charon)", t)
    net = re.search(r"Net pay\s+(€[\d,]+\.\d{2})", t)
    ded = re.search(r"Total\s+€[\d,]+\.\d{2}\s+Total\s+(€[\d,]+\.\d{2})", t)
    paid = re.search(r"Paid on (\d{2})/(\d{2})/(\d{4})", t)
    period = re.search(r"Month Ending (\d{1,2}) ([A-Za-z]{3})[a-z]* (\d{4})", t)
    if not (name and net and ded):
        return None
    if period:
        y, m = int(period.group(3)), MONTHS[period.group(2).lower()]
    else:  # nom de fichier du type SMARTKETING_LIMITED_Payslip_MARS2026.pdf
        mm = re.search(r"_([A-Z]+)(20\d{2})\.pdf$", pdf.name)
        if not mm or mm.group(1).lower() not in MONTHS:
            return None
        y, m = int(mm.group(2)), MONTHS[mm.group(1).lower()]
    return {"file": pdf, "who": name.group(1), "year": y, "month": m, "net": euros(net.group(1)),
            "deductions": euros(ded.group(1)),
            "paid": date(int(paid.group(3)), int(paid.group(2)), int(paid.group(1))) if paid else None}


def main():
    go = "--go" in sys.argv
    slips = [s for f in FOLDERS for p in sorted(f.rglob("*.pdf")) if (s := parse(p))]
    # un seul bulletin par salarié et par mois (les doublons de dossier sont ignorés)
    uniq = {}
    for s in slips:
        uniq.setdefault((s["who"], s["year"], s["month"]), s)
    slips = list(uniq.values())
    for s in sorted(slips, key=lambda s: (s["who"], s["year"], s["month"])):
        print(f"  bulletin {s['who'][:17]:17s} {s['month']:02d}/{s['year']} net {s['net']:>9,.2f} retenues {s['deductions']:>8,.2f} payé le {s['paid']}")

    lines = [r for r in csv.DictReader(open(WORK / "wise_lines.csv")) if r["line"] == "main" and r["xero_id"]]
    plan = []
    for w in lines:
        cp, d, amt = w["counterparty"].lower(), date.fromisoformat(w["date"]), float(w["amount"])
        if cp == "le balier thibault":
            c = [s for s in slips if s["who"] == "Thibault Le Balier" and abs(s["net"] - amt) < 0.01
                 and s["paid"] and abs((s["paid"] - d).days) <= 10]
            if c:
                plan.append((w, [min(c, key=lambda s: abs((s["paid"] - d).days))], "net = virement"))
        elif "revenue commissioners" in cp and w["counterparty"].startswith("Revenue"):
            pm = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
            c = [s for s in slips if (s["year"], s["month"]) == pm]
            if c and abs(sum(s["deductions"] for s in c) - amt) <= 0.05:
                plan.append((w, c, f"retenues {pm[1]:02d}/{pm[0]} = {sum(s['deductions'] for s in c):,.2f}"))

    todo = []
    print()
    for w, docs, why in plan:
        existing = {a["FileName"] for a in x.get(f"BankTransactions/{w['xero_id']}/Attachments")["Attachments"]}
        new = [s for s in docs if s["file"].name not in existing]
        print(f"  {w['date']} {w['counterparty'][:22]:22s} {float(w['amount']):>9,.2f} € <- "
              f"{', '.join(s['who'].split()[0] + ' ' + f'{s['month']:02d}/{s['year']}' for s in docs)} ({why})"
              + ("" if new else " — déjà joint"))
        todo += [(w, s) for s in new]
    print(f"\n{len(plan)} opérations, {len(todo)} bulletins à joindre")
    if not go:
        print("Simulation uniquement. Relancer avec --go.")
        return
    for w, s in todo:
        x.upload(f"BankTransactions/{w['xero_id']}/Attachments/{urllib.parse.quote(s['file'].name)}",
                 s["file"].read_bytes(), "application/pdf")
        with open(WORK / "push_log.jsonl", "a") as fh:
            fh.write(json.dumps({"action": "attach", "wise_id": w["wise_id"], "id": w["xero_id"],
                                 "file": str(s["file"].relative_to(ROOT)), "status": "ok"}, ensure_ascii=False) + "\n")
        with open(WORK / "docs_mcp.jsonl", "a") as fh:
            fh.write(json.dumps({"wise_id": w["wise_id"], "source": "bulletins_paie",
                                 "file": str(s["file"].relative_to(ROOT))}, ensure_ascii=False) + "\n")
    print(f"{len(todo)} bulletins joints.")


if __name__ == "__main__":
    main()
