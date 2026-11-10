#!/usr/bin/env python3
"""Photographie Qonto (lecture seule) : écrit data/bumpslab/qonto/*.json.

    python3 -m bumpslab.qonto_snapshot
"""
import json

from bumpslab import DATA
from bumpslab import qonto_api as q

OUT = DATA / "qonto"


def dump(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"{name:20s} {len(data) if isinstance(data, list) else 1:>5}")


def main():
    org = q.get("organization")["organization"]
    dump("organisation", {k: v for k, v in org.items() if k != "bank_accounts"})
    accounts = org["bank_accounts"]
    dump("bank_accounts", accounts)
    tx = []
    for a in accounts:
        for status in ("completed", "pending", "declined", "reversed"):
            tx += q.get_all("transactions", "transactions", bank_account_id=a["id"], **{"status[]": status},
                            **{"includes[]": ["attachments", "labels", "vat_details"]})
    dump("transactions", tx)
    dump("memberships", q.get_all("memberships", "memberships"))


if __name__ == "__main__":
    main()
