#!/usr/bin/env python3
"""Indexe un dossier de justificatifs (texte des PDF) et propose des correspondances avec les opérations sans pièce.

    python3 index_folder.py "<dossier>"

Sorties :
  data/work/folder_index.json      texte extrait de chaque PDF (via pdftotext)
  data/work/folder_candidates.csv  pour chaque opération sans justificatif, les documents qui contiennent
                                   son montant (en devise d'origine ou du compte), avec un score
"""
import csv
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "data" / "work"
MONTHS = {m: i + 1 for i, ms in enumerate([
    ("jan", "janv", "january", "janvier"), ("feb", "fév", "fev", "févr", "fevr", "february", "février", "fevrier"),
    ("mar", "march", "mars"), ("apr", "avr", "april", "avril"), ("may", "mai"), ("jun", "june", "juin"),
    ("jul", "july", "juillet", "juil"), ("aug", "august", "août", "aout"), ("sep", "sept", "september", "septembre"),
    ("oct", "october", "octobre"), ("nov", "november", "novembre"), ("dec", "déc", "december", "décembre"),
]) for m in ms}


def pdf_text(path):
    r = subprocess.run(["pdftotext", "-layout", "-q", str(path), "-"], capture_output=True, text=True, timeout=60)
    return r.stdout


def amount_variants(x):
    """Formats possibles d'un montant dans un document : 1234.5 -> 1234.50, 1,234.50, 1 234,50, 1234,50…"""
    v = f"{x:.2f}"
    ent, dec = v.split(".")
    grouped = f"{int(ent):,}"
    out = {v, f"{ent},{dec}", f"{grouped}.{dec}", f"{grouped.replace(',', ' ')},{dec}",
           f"{grouped.replace(',', ' ')}.{dec}", f"{grouped.replace(',', '.')},{dec}",
           f"{grouped.replace(',', chr(8239))},{dec}", f"{grouped.replace(',', chr(160))},{dec}"}
    if dec == "00":
        out |= {ent, grouped}
    return {o for o in out if len(o) >= 3}


def dates_in(text):
    found = set()
    for d, m, y in re.findall(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b", text):
        found.add((int(y), int(m), int(d)))
    for y, m, d in re.findall(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text):
        found.add((int(y), int(m), int(d)))
    for d, mon, y in re.findall(r"\b(\d{1,2})(?:er)?\s+([A-Za-zéûè]{3,9})\.?,?\s+(20\d{2})\b", text):
        if mon.lower() in MONTHS:
            found.add((int(y), MONTHS[mon.lower()], int(d)))
    for y, mon, d in re.findall(r"\b(20\d{2})\s+([A-Za-z]{3,9})\s+(\d{1,2})\b", text):  # « 2026 February 09 »
        if mon.lower() in MONTHS:
            found.add((int(y), MONTHS[mon.lower()], int(d)))
    for mon, d, y in re.findall(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(20\d{2})\b", text):
        if mon.lower() in MONTHS:
            found.add((int(y), MONTHS[mon.lower()], int(d)))
    out = []
    for y, m, d in found:
        try:
            out.append(date(y, m, d))
        except ValueError:
            pass
    return out


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


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
