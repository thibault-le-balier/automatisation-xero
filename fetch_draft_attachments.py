#!/usr/bin/env python3
"""Télécharge (lecture seule) les pièces jointes des brouillons de factures Xero appariés aux lignes Wise.

Entrée : data/work/drafts_map.json (wise_id -> invoice_id)
Sortie : data/invoices/<wise_id>/<fichier> + data/work/docs_drafts.json
"""
import json
import re
from pathlib import Path

import xero_api as x

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "data" / "work"
INVOICES = ROOT / "data" / "invoices"


def safe(name):
    return re.sub(r"[^\w.\- ]", "_", name).strip() or "piece.pdf"


def main():
    docs = []
    for d in json.load(open(WORK / "drafts_map.json")):
        atts = x.get(f"Invoices/{d['invoice_id']}/Attachments")["Attachments"]
        for a in atts:
            dest = INVOICES / d["wise_id"] / safe(a["FileName"])
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(x.download(f"Invoices/{d['invoice_id']}/Attachments/{a['AttachmentID']}", a["MimeType"]))
            docs.append({"wise_id": d["wise_id"], "source": "xero_draft", "invoice_id": d["invoice_id"],
                         "file": str(dest.relative_to(ROOT)), "mime": a["MimeType"], "contact": d["contact"]})
            print(f"{d['wise_id']:32s} {dest.stat().st_size:>8} o  {a['FileName']}")
    (WORK / "docs_drafts.json").write_text(json.dumps(docs, indent=1, ensure_ascii=False))
    print(f"\n{len(docs)} pièces pour {len({d['wise_id'] for d in docs})} lignes Wise")


if __name__ == "__main__":
    main()
