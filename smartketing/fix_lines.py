#!/usr/bin/env python3
"""Dernières lignes du relevé sans écriture en face (vues dans l'écran Reconcile le 04/11/2026).

Trois cas, sans effet sur la charge nette :
  - pré-autorisation (carburant, parking) : débit du montant bloqué puis crédit du remboursement ;
    la dépense nette existante passe au montant bloqué + une recette du remboursement ;
  - paiement carte annulé ou remboursé (absent de l'export Wise) : une dépense + une recette du même montant ;
  - frais Wise oubliés (appariés à tort à un paiement Railway du même montant).

    python3 -m smartketing.fix_lines         # simulation
    python3 -m smartketing.fix_lines --go    # applique (sans doublon : chaque écriture a sa référence AUTO26 ... )
"""
import json
import sys

from smartketing import split_preauth
from smartketing import xero_api as x

from smartketing import DATA

SPLITS = [  # (id Wise de la dépense nette, montant bloqué, date du remboursement)
    ("CARD_TRANSACTION-3567799019", 150.00, "2026-03-17"),  # Tamoil Lutry, CHF : -150,00 / +93,35
    ("CARD_TRANSACTION-3574900565", 150.00, "2026-03-19"),  # TotalEnergies, EUR : -150,00 / +92,51
    ("CARD_TRANSACTION-3961360954", 1.05, "2026-06-23"),    # Parkingpay, CHF : -1,05 / +0,50
]
CREATES = [  # (compte bancaire, type, date, montant, contact, compte, TVA, libellé, référence)
    ("Compte EURO", "SPEND", "2026-06-14", 395.39, "AIRBNB", "494", "NONE",
     "Airbnb – paiement annulé (CARD-3923074506)", "AUTO26 CARD-3923074506 DEBIT"),
    ("Compte EURO", "RECEIVE", "2026-06-14", 395.39, "AIRBNB", "494", "NONE",
     "Airbnb – annulation du paiement (CARD-3923074506)", "AUTO26 CARD-3923074506 CREDIT"),
    ("Compte EURO", "SPEND", "2026-02-24", 10.00, "GOOGLE ADVERTISING", "400", "INPUT",
     "Google Ads – paiement annulé (CARD-3490326539)", "AUTO26 CARD-3490326539 DEBIT"),
    ("Compte EURO", "RECEIVE", "2026-02-24", 10.00, "GOOGLE ADVERTISING", "400", "INPUT",
     "Google Ads – annulation du paiement (CARD-3490326539)", "AUTO26 CARD-3490326539 CREDIT"),
    ("Compte EURO", "SPEND", "2026-06-26", 54.60, "APRR", "449", "INPUT",
     "Péage APRR (CARD-3975302396)", "AUTO26 CARD-3975302396 DEBIT"),
    ("Compte EURO", "RECEIVE", "2026-06-29", 54.60, "APRR", "449", "INPUT",
     "APRR – remboursement du péage CARD-3955077875", "AUTO26 CARD-3955077875 CREDIT"),
    ("Compte CHF", "SPEND", "2026-04-14", 0.79, "WISE", "404", "NONE",
     "Frais Wise – TRANSFER-2075977376 (VINC-0088)", "AUTO26 TRANSFER-2075977376 FEE"),
    ("Compte CHF", "RECEIVE", "2026-04-16", 0.79, "RAILWAY", "485", "INPUT",
     "Railway – remboursement de l'autorisation carte 1 USD (CARD-3678323933)", "AUTO26 CARD-3678323933 CREDIT"),
]


def main():
    go = "--go" in sys.argv
    accounts = json.load(open(DATA / "xero" / "accounts.json"))
    banks = {a["Name"]: (a["AccountID"], a.get("CurrencyCode")) for a in accounts if a["Type"] == "BANK"}
    contacts = {c["Name"]: c["ContactID"] for c in json.load(open(DATA / "xero" / "contacts.json"))
                if c.get("ContactStatus") == "ACTIVE"}

    print("== Pré-autorisations ==")
    for wise_id, hold, date in SPLITS:
        sys.argv = ["split_preauth.py", wise_id, str(hold), date] + (["--go"] if go else [])
        try:
            split_preauth.main()
        except SystemExit as e:
            print("  ", e)

    print("\n== Écritures à créer ==")
    todo = []
    for bank, typ, date, amount, contact, acc, tax, desc, ref in CREATES:
        exists = [t for t in x.get("BankTransactions", where=f'Reference=="{ref}"')["BankTransactions"]
                  if t["Status"] != "DELETED"]
        print(f"  {date} {bank:11s} {typ:7s} {amount:>8.2f} {acc:4s} {contact:20s} {desc}"
              + ("  — déjà présente" if exists else ""))
        if not exists:
            bank_id, ccy = banks[bank]
            todo.append({"Type": typ, "Contact": {"ContactID": contacts[contact]} if contact in contacts else {"Name": contact},
                         "BankAccount": {"AccountID": bank_id}, "Date": date, "Reference": ref, "CurrencyCode": ccy,
                         "LineAmountTypes": "Inclusive",
                         "LineItems": [{"Description": desc, "Quantity": 1, "UnitAmount": amount,
                                        "AccountCode": acc, "TaxType": tax}]})
    if not go:
        print("\nSimulation uniquement. Relancer avec --go.")
        return
    if todo:
        res = x.put("BankTransactions", {"BankTransactions": todo}, summarizeErrors="false")
        for t in res["BankTransactions"]:
            ok = not t.get("ValidationErrors")
            print(("  créé " if ok else "  ERREUR ") + t.get("Reference", ""), t.get("ValidationErrors") or "")
            with open(DATA / "work" / "push_log.jsonl", "a") as fh:
                fh.write(json.dumps({"action": "create" if ok else "create_error", "id": t.get("BankTransactionID"),
                                     "ref": t.get("Reference"), "total": t.get("Total")}) + "\n")
    print("Fait.")


if __name__ == "__main__":
    main()
