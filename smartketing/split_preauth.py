#!/usr/bin/env python3
"""Pré-autorisations carburant : le relevé montre un débit (montant bloqué) puis un crédit (remboursement).

L'export Wise ne donne que le net ; Xero a donc une seule dépense nette qu'il ne peut rapprocher d'aucune ligne.
On la transforme en deux écritures qui collent au relevé, sans changer la charge nette :
  - la dépense existante passe au montant bloqué (même compte, contact, pièce jointe) ;
  - une recette du montant remboursé est créée sur le même compte de charge.

    python3 -m smartketing.split_preauth <wise_id> <montant_bloque> [date_remboursement AAAA-MM-JJ]          # simulation
    python3 -m smartketing.split_preauth <wise_id> <montant_bloque> [date_remboursement AAAA-MM-JJ] --go     # applique
"""
import csv
import json
import sys

from smartketing import xero_api as x

from smartketing import DATA
WORK = DATA / "work"
TAG = "AUTO26"


def main():
    args = [a for a in sys.argv[1:] if a != "--go"]
    go = "--go" in sys.argv
    if len(args) < 2:
        sys.exit(__doc__)
    wise_id, hold = args[0], round(float(args[1].replace(",", ".")), 2)
    release_date = args[2] if len(args) > 2 else None

    row = next((r for r in csv.DictReader(open(WORK / "wise_lines.csv"))
                if r["wise_id"] == wise_id and r["line"] == "main"), None)
    if not row or not row["xero_id"]:
        sys.exit(f"{wise_id} : aucune écriture Xero associée (relancer xero_snapshot.py puis match.py)")
    t = x.get(f"BankTransactions/{row['xero_id']}")["BankTransactions"][0]
    net = round(t["Total"], 2)
    if t["IsReconciled"] or t["Type"] != "SPEND" or len(t["LineItems"]) != 1:
        sys.exit(f"{wise_id} : écriture déjà rapprochée ou non standard, on n'y touche pas")
    release = round(hold - net, 2)
    if release <= 0:
        sys.exit(f"montant bloqué {hold} ≤ net {net} : rien à scinder")
    li = t["LineItems"][0]
    ref = f"{TAG} {wise_id} PREAUTH"
    exists = x.get("BankTransactions", where=f'Reference=="{ref}"')["BankTransactions"]
    exists = [e for e in exists if e["Status"] != "DELETED"]

    print(f"{t['BankAccount']['Name']} {(t.get('Contact') or {}).get('Name')} — net {net} {t['CurrencyCode']}")
    print(f"  1. dépense existante : {net} -> {hold} (compte {li.get('AccountCode')}, pièce jointe conservée)")
    print(f"  2. recette créée     : {release} « Remboursement pré-autorisation » (compte {li.get('AccountCode')})"
          + (" — déjà présente, ignorée" if exists else ""))
    if not go:
        print("Simulation uniquement. Relancer avec --go.")
        return

    desc = li.get("Description") or (t.get("Contact") or {}).get("Name", "")
    x.post(f"BankTransactions/{t['BankTransactionID']}", {"BankTransactions": [{
        "BankTransactionID": t["BankTransactionID"],
        "LineItems": [{"LineItemID": li["LineItemID"], "Description": f"{desc} – pré-autorisation carte (net {net})",
                       "Quantity": 1, "UnitAmount": hold, "AccountCode": li["AccountCode"], "TaxType": li.get("TaxType")}],
    }]})
    if not exists:
        date = release_date or t["DateString"][:10]
        res = x.put("BankTransactions", {"BankTransactions": [{
            "Type": "RECEIVE", "Contact": {"ContactID": t["Contact"]["ContactID"]},
            "BankAccount": {"AccountID": t["BankAccount"]["AccountID"]}, "Date": date, "Reference": ref,
            "CurrencyCode": t["CurrencyCode"], "LineAmountTypes": t.get("LineAmountTypes", "Inclusive"),
            "LineItems": [{"Description": f"Remboursement pré-autorisation carte – {desc}", "Quantity": 1,
                           "UnitAmount": release, "AccountCode": li["AccountCode"], "TaxType": li.get("TaxType")}],
        }]})
        new = res["BankTransactions"][0]
        with open(WORK / "push_log.jsonl", "a") as fh:
            fh.write(json.dumps({"action": "preauth_split", "wise_id": wise_id, "id": t["BankTransactionID"],
                                 "hold": hold, "release_id": new["BankTransactionID"], "release": release}) + "\n")
    print("Fait : les deux lignes du relevé ont maintenant chacune leur écriture.")


if __name__ == "__main__":
    main()
