#!/usr/bin/env python3
"""Indexe un dossier de justificatifs (texte des PDF) et propose des correspondances avec les opérations sans pièce.

    python3 -m smartketing.index_folder "<dossier>"

Sorties :
  data/smartketing/work/folder_index.json      texte extrait de chaque PDF (via pdftotext)
  data/smartketing/work/folder_candidates.csv  pour chaque opération sans justificatif, les documents qui contiennent
                                   son montant (en devise d'origine ou du compte), avec un score
"""
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

from commun import ROOT
from smartketing import DATA
from commun.pieces import amount_variants, dates_in, norm, pdf_text
WORK = DATA / "work"


def main():
    folder = Path(sys.argv[1]).resolve()
    index_path = WORK / "folder_index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    for p in sorted(folder.rglob("*.pdf")):
        key = str(p.relative_to(ROOT))
        if key not in index:
            index[key] = {"text": pdf_text(p)[:20000], "size": p.stat().st_size}
    index_path.write_text(json.dumps(index, ensure_ascii=False))
    empty = sum(1 for v in index.values() if len(v["text"].strip()) < 30)
    print(f"{len(index)} PDF indexés ({empty} sans texte : scans à lire autrement)")

    missing = [c for c in csv.DictReader(open(WORK / "couverture.csv")) if c["etat"] == "manquant"]
    lines = {r["wise_id"]: r for r in csv.DictReader(open(WORK / "wise_lines.csv")) if r["line"] == "main"}
    rows = []
    for c in missing:
        w = lines[c["wise_id"]]
        wdate = date.fromisoformat(w["date"])
        amts = {(float(w["amount"]), w["currency"])}
        if w["orig_amount"]:
            amts.add((float(w["orig_amount"]), w["orig_currency"]))
        vendor = norm(w["counterparty"].split("|")[0])[:6]
        for key, v in index.items():
            text = v["text"]
            hit = [f"{a} {cur}" for a, cur in amts if any(re.search(rf"(?<![\d.,]){re.escape(s)}(?![\d])", text)
                                                       for s in amount_variants(a))]
            if not hit:
                continue
            ds = dates_in(text)
            gap = min((abs((d - wdate).days) for d in ds), default=999)
            vend = bool(vendor) and (vendor in norm(text) or vendor in norm(key))
            score = 2 * vend + (2 if gap <= 3 else 1 if gap <= 35 else 0) + (1 if "2026" in key or "2026" in text else 0)
            rows.append({"wise_id": c["wise_id"], "date": w["date"], "contrepartie": w["counterparty"],
                         "montant": f"{w['amount']} {w['currency']}", "origine": f"{w['orig_amount']} {w['orig_currency']}",
                         "document": key, "montant_trouve": "; ".join(hit), "ecart_jours": gap,
                         "fournisseur_trouve": vend, "score": score})
    rows.sort(key=lambda r: (r["wise_id"], -r["score"]))
    with open(WORK / "folder_candidates.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["wise_id"])
        wr.writeheader()
        wr.writerows(rows)
    strong = {r["wise_id"] for r in rows if r["score"] >= 4}
    print(f"{len(missing)} opérations sans justificatif ; candidats pour {len({r['wise_id'] for r in rows})}, "
          f"dont {len(strong)} avec un bon score (montant + fournisseur + date proche)")


if __name__ == "__main__":
    main()
