#!/usr/bin/env python3
"""Rapport de couverture des justificatifs 2026 et listes de pièces manquantes.

Sorties : data/work/couverture.csv (une ligne par opération Wise) et data/work/manquants_<qui>.csv
"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "data" / "work"


def load(path, default):
    return json.load(open(path)) if path.exists() else default


def main():
    rows = [r for r in csv.DictReader(open(WORK / "wise_lines.csv")) if r["line"] == "main"]
    found = {l["wise_id"]: l for f in sorted((WORK / "found").glob("*.json")) for l in load(f, [])}
    drafts = {d["wise_id"] for d in load(WORK / "docs_drafts.json", []) + load(WORK / "docs_wise.json", [])}
    mcp = WORK / "docs_mcp.jsonl"
    downloaded = drafts | ({json.loads(l)["wise_id"] for l in open(mcp)} if mcp.exists() else set())
    bundled = {x["wise_id"] for f in (WORK / "bundles").glob("*.json") for x in load(f, [])}

    # Paiements remboursés : un débit et un remboursement du même montant chez le même marchand (net nul).
    refunded = set()
    for r in rows:
        if r["type"] == "RECEIVE" and r["status_wise"] == "REFUNDED":
            twin = next((o for o in rows if o["type"] == "SPEND" and o["wise_id"] not in refunded
                         and o["account"] == r["account"] and o["amount"] == r["amount"]
                         and o["counterparty"][:5].lower() == r["counterparty"][:5].lower()), None)
            if twin:
                refunded |= {r["wise_id"], twin["wise_id"]}

    out = []
    for r in rows:
        f = found.get(r["wise_id"], {})
        if r["xero_has_attachment"] == "True":
            etat, detail = "déjà joint dans Xero", ""
        elif r["kind"] == "BALANCE_CASHBACK":
            etat, detail = "sans facture (relevé Wise)", "cashback Wise"
        elif r["wise_id"] in refunded:
            etat, detail = "sans facture (relevé Wise)", "paiement remboursé, net nul"
        elif r["wise_id"] in drafts:
            etat, detail = "trouvé", "brouillon Xero / export Wise"
        elif f.get("found") and r["wise_id"] in downloaded:
            etat, detail = "trouvé", f"{f['source']} ({f.get('match')})"
        elif f.get("found"):
            etat, detail = "manquant", "trouvé mais non téléchargeable par le connecteur : " + (f.get("note") or "")[:200]
        elif r["wise_id"] in bundled and r["wise_id"] not in found:
            etat, detail = "recherche en cours", ""
        else:
            etat, detail = "manquant", (f.get("note") or "")[:300]
        out.append({"date": r["date"], "compte": r["account"], "montant": r["amount"], "devise": r["currency"],
                    "contrepartie": r["counterparty"], "carte_de": r["created_by"], "statut_xero": r["statut"],
                    "etat": etat, "detail": detail, "facture_a": f.get("billed_to", ""), "wise_id": r["wise_id"]})

    with open(WORK / "couverture.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    by_state = Counter(o["etat"] for o in out)
    print(f"{len(out)} opérations Wise 2026 :")
    for k, v in by_state.most_common():
        eur = sum(float(o["montant"]) for o in out if o["etat"] == k)
        print(f"  {k:28s} {v:4d}   ({eur:,.2f} en devise du compte)")
    ok = sum(by_state[k] for k in ("déjà joint dans Xero", "trouvé", "sans facture (relevé Wise)"))
    print(f"  => justifiées : {ok}/{len(out)} ({100 * ok / len(out):.0f} %)")

    missing = defaultdict(list)
    for o in out:
        if o["etat"] == "manquant":
            who = "hugo" if "Hugo" in o["carte_de"] else "thibault"
            missing[who].append(o)
    for who, items in missing.items():
        with open(WORK / f"manquants_{who}.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["date", "contrepartie", "montant", "devise", "compte", "detail", "wise_id"])
            w.writeheader()
            for o in sorted(items, key=lambda o: (o["contrepartie"], o["date"])):
                w.writerow({k: o[k] for k in w.fieldnames})
        print(f"  manquants carte {who} : {len(items)}  -> data/work/manquants_{who}.csv")
    other = Counter(o["facture_a"][:30] for o in out if o["facture_a"] and "SMARTKETING" not in o["facture_a"].upper())
    if other:
        print("  factures NON adressées à Smartketing :", dict(other))


if __name__ == "__main__":
    main()
