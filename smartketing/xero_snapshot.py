#!/usr/bin/env python3
"""Photographie Xero (lecture seule) : écrit data/smartketing/xero/*.json pour l'analyse et l'anti-doublon."""
import json
from smartketing import DATA
from smartketing import xero_api as x

OUT = DATA / "xero"
SINCE = "DateTime(2026,1,1)"
BILLS_SINCE = "DateTime(2025,7,1)"  # bills 2025 payées en 2026


def dump(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"{name:20s} {len(data) if isinstance(data, list) else 1:>5}")


def main():
    dump("organisation", x.get("Organisation")["Organisations"][0])
    dump("accounts", x.get("Accounts")["Accounts"])
    dump("tax_rates", x.get("TaxRates")["TaxRates"])
    dump("currencies", x.get("Currencies")["Currencies"])
    dump("contacts", x.get_all("Contacts", "Contacts", includeArchived="true"))
    # Tri par date : l'ordre par défaut bouge quand une écriture est rapprochée pendant la lecture.
    dump("bank_transactions", x.get_all("BankTransactions", "BankTransactions", where=f"Date>={SINCE}",
                                        order="Date ASC"))
    dump("bank_transfers", x.get("BankTransfers", where=f"Date>={SINCE}")["BankTransfers"])
    dump("invoices", x.get_all("Invoices", "Invoices", where=f"Date>={BILLS_SINCE}"))
    dump("payments", x.get_all("Payments", "Payments", where=f"Date>={SINCE}"))
    for name in ("CreditNotes", "Prepayments", "Overpayments"):
        try:
            dump(name.lower(), x.get_all(name, name, where=f"Date>={SINCE}"))
        except RuntimeError as e:
            print(f"{name:20s} non lu ({str(e)[:80]})")


if __name__ == "__main__":
    main()
