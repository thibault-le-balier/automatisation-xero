#!/usr/bin/env python3
"""Corrige les écritures déjà présentes dans Xero (simulation par défaut).

    python3 fix_existing.py            # montre ce qui serait fait
    python3 fix_existing.py --go       # applique

1. Doublons : une écriture non rapprochée sans ligne Wise en face, alors qu'une écriture rapprochée
   identique (même compte, montant, date, contact proche) existe -> on copie ses pièces jointes sur
   l'écriture rapprochée, puis on supprime le doublon.
2. Recodage du compte fourre-tout 430 sur les écritures en attente (non rapprochées) vers un compte
   précis selon la catégorie Wise de la ligne correspondante.
"""
import argparse
import csv
import json
import urllib.parse
from pathlib import Path

import xero_api as x
from match import xero_date

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
WORK = DATA / "work"
RECODE = {"Travel": ("493", "INPUT"), "Entertainment": ("420", "NONE"), "Office expenses": ("453", "INPUT"),
          "General": ("429", "INPUT"), "Software and web hosting": ("485", "INPUT")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true")
    args = ap.parse_args()
    bts = json.load(open(DATA / "xero" / "bank_transactions.json"))
    rows = list(csv.DictReader(open(WORK / "wise_lines.csv")))
    used = {r["xero_id"] for r in rows if r["xero_id"]}
    by_id = {t["BankTransactionID"]: t for t in bts}

    # 1. Doublons
    for t in bts:
        if t["BankTransactionID"] in used or t["IsReconciled"]:
            continue
        twins = [o for o in bts if o["IsReconciled"] and o["BankAccount"]["Name"] == t["BankAccount"]["Name"]
                 and o["Type"] == t["Type"] and abs(o["Total"] - t["Total"]) < 0.005
                 and abs((xero_date(o["Date"]) - xero_date(t["Date"])).days) <= 3]
        if len(twins) != 1:
            print(f"[doublon ?] {t['BankTransactionID']} {t['Total']} : {len(twins)} jumeau(x), laissé tel quel")
            continue
        twin = twins[0]
        files = x.get(f"BankTransactions/{t['BankTransactionID']}/Attachments")["Attachments"] if t.get("HasAttachments") else []
        print(f"[doublon] {xero_date(t['Date'])} {t['Total']} {(t.get('Contact') or {}).get('Name')} : "
              f"{len(files)} pièce(s) -> {twin['BankTransactionID']} (rapprochée), puis suppression")
        if args.go:
            for a in files:
                data = x.download(f"BankTransactions/{t['BankTransactionID']}/Attachments/{a['AttachmentID']}", a["MimeType"])
                x.upload(f"BankTransactions/{twin['BankTransactionID']}/Attachments/{urllib.parse.quote(a['FileName'])}",
                         data, a["MimeType"])
            x.post(f"BankTransactions/{t['BankTransactionID']}",
                   {"BankTransactions": [{"BankTransactionID": t["BankTransactionID"], "Status": "DELETED"}]})

    # 2. Recodage 430 des écritures en attente
    n = 0
    for r in rows:
        t = by_id.get(r["xero_id"])
        if r["statut"] != "EN_ATTENTE" or not t:
            continue
        if not any(li.get("AccountCode") == "430" for li in t["LineItems"]):
            continue
        acc, tax = RECODE.get(r["category"], ("429", "INPUT"))
        lines = [{**{k: li[k] for k in ("LineItemID", "Description", "Quantity", "UnitAmount") if k in li},
                  "AccountCode": acc if li.get("AccountCode") == "430" else li["AccountCode"],
                  "TaxType": tax if li.get("AccountCode") == "430" else li.get("TaxType")} for li in t["LineItems"]]
        n += 1
        print(f"[recodage] {r['date']} {r['amount']:>7} {r['currency']} {r['counterparty'][:28]:28s} 430 -> {acc} ({r['category']})")
        if args.go:
            x.post(f"BankTransactions/{t['BankTransactionID']}",
                   {"BankTransactions": [{"BankTransactionID": t["BankTransactionID"], "LineItems": lines}]})
    print(f"\n{n} écritures à recoder" + ("" if args.go else " — simulation, relancer avec --go"))


if __name__ == "__main__":
    main()
