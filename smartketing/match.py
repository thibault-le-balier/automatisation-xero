#!/usr/bin/env python3
"""Apparie chaque mouvement Wise (ligne principale + ligne de frais) avec les opérations Xero 2026.

Entrées : data/wise/*.csv (export « transaction history ») et data/xero/*.json (xero_snapshot.py).
Sortie  : data/work/wise_lines.csv, une ligne par mouvement tel qu'il arrive dans le flux bancaire Xero.

Statuts :
  RAPPROCHE   déjà rapproché dans Xero
  EN_ATTENTE  une écriture Xero non rapprochée existe déjà (un clic « OK » suffit)
  A_CREER     rien dans Xero en face : l'écriture est à créer
"""
import csv
import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "work"
ACCOUNT_BY_CCY = {"CHF": "Compte CHF", "EUR": "Compte EURO"}
DATE_WINDOW = 7  # jours d'écart toléré entre Wise et Xero


def xero_date(s):
    ms = int(re.search(r"-?\d+", s).group())
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).date()


def xero_stamp(t):
    m = re.search(r"\d+", t.get("UpdatedDateUTC") or "")
    return int(m.group()) if m else 0


def money(s):
    return round(float(s), 2) if s not in ("", None) else 0.0


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def wise_lines():
    """Déplie chaque ligne d'export en mouvements « vus par la banque »."""
    lines = []
    for path in sorted((DATA / "wise").glob("*.csv")):
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            wid = r["ID"]
            kind, num = wid.rsplit("-", 1)
            out = r["Direction"] == "OUT"
            ccy = r["Source currency"] if out else r["Target currency"]
            amount = money(r["Source amount (after fees)"] if out else r["Target amount (after fees)"])
            counterparty = r["Target name"] if out else r["Source name"]
            base = {
                "wise_id": wid, "wise_num": num, "kind": kind, "status_wise": r["Status"],
                "date": r["Created on"][:10], "date_fin": (r["Finished on"] or r["Created on"])[:10],
                "account": ACCOUNT_BY_CCY.get(ccy, f"?{ccy}"), "currency": ccy,
                "counterparty": counterparty.strip(), "reference": r["Reference"].strip(),
                "category": r["Category"], "created_by": r["Created by"],
                "orig_amount": r["Target amount (after fees)"] if out else r["Source amount (after fees)"],
                "orig_currency": r["Target currency"] if out else r["Source currency"],
            }
            fee = money(r["Source fee amount"])
            if not out and fee > 0 and (r["Source fee currency"] or ccy) == ccy:
                amount = round(amount + fee, 2)  # reçu : Xero voit le brut, puis les frais à part
            lines.append({**base, "line": "main", "type": "SPEND" if out else "RECEIVE", "amount": amount})
            if fee > 0:
                fee_ccy = r["Source fee currency"] or ccy
                lines.append({**base, "line": "fee", "type": "SPEND", "amount": fee,
                              "account": ACCOUNT_BY_CCY.get(fee_ccy, f"?{fee_ccy}"), "currency": fee_ccy,
                              "counterparty": "WISE", "reference": f"FEE-{kind.split('_')[0]}-{num}"})
    return lines


def main():
    raw = json.load(open(DATA / "xero" / "bank_transactions.json"))
    # Une lecture paginée pendant que quelqu'un rapproche peut renvoyer deux fois la même écriture :
    # on garde la version la plus récente et on ignore les écritures supprimées ou annulées.
    latest = {}
    for t in raw:
        prev = latest.get(t["BankTransactionID"])
        if prev is None or xero_stamp(t) >= xero_stamp(prev):
            latest[t["BankTransactionID"]] = t
    bts = [t for t in latest.values() if t["Status"] not in ("DELETED", "VOIDED")]
    for t in bts:
        t["_date"] = xero_date(t["Date"])
        t["_used"] = False
    lines = wise_lines()

    def candidates(w):
        d = dt.date.fromisoformat(w["date"])
        for t in bts:
            if t["_used"] or t["BankAccount"]["Name"] != w["account"] or t["Type"] != w["type"]:
                continue
            if abs(t["Total"] - w["amount"]) > 0.005:
                continue
            gap = abs((t["_date"] - d).days)
            if gap > DATE_WINDOW:
                continue
            ref_hit = w["wise_num"] in (t.get("Reference") or "")
            if w["line"] == "fee" and (t.get("Reference") or "").startswith("FEE-") and not ref_hit:
                continue  # frais d'une autre opération
            if w["line"] == "fee" and not ref_hit and (t.get("Contact") or {}).get("Name", "").upper() not in ("WISE", "WISE-SERVICE"):
                continue  # des frais Wise ne s'apparient qu'à une écriture Wise (ex. Railway 0,79 ≠ frais 0,79)
            name_hit = norm(w["counterparty"])[:5] and norm(w["counterparty"])[:5] in norm((t.get("Contact") or {}).get("Name"))
            yield (0 if ref_hit else 1, 0 if name_hit else 1, gap), t

    # Les correspondances par référence d'abord, puis par date la plus proche.
    order = sorted(range(len(lines)), key=lambda i: (lines[i]["line"] != "fee", lines[i]["date"]))
    for i in order:
        w = lines[i]
        best = min(candidates(w), default=None, key=lambda c: c[0])
        if best:
            t = best[1]
            t["_used"] = True
            w.update({
                "statut": "RAPPROCHE" if t["IsReconciled"] else "EN_ATTENTE",
                "xero_id": t["BankTransactionID"], "xero_date": t["_date"].isoformat(),
                "xero_contact": (t.get("Contact") or {}).get("Name", ""),
                "xero_account_code": "|".join(l.get("AccountCode") or "" for l in t["LineItems"]),
                "xero_has_attachment": t.get("HasAttachments", False),
            })
        else:
            w.update({"statut": "A_CREER", "xero_id": "", "xero_date": "", "xero_contact": "",
                      "xero_account_code": "", "xero_has_attachment": False})

    # Pré-autorisations scindées (split_preauth.py) : dépense du montant bloqué + recette « ... PREAUTH ».
    for w in lines:
        if w["statut"] != "A_CREER" or w["line"] != "main":
            continue
        rel = next((t for t in bts if not t["_used"] and t["Type"] == "RECEIVE"
                    and (t.get("Reference") or "") == f"AUTO26 {w['wise_id']} PREAUTH"), None)
        if not rel:
            continue
        hold = next((t for t in bts if not t["_used"] and t["Type"] == "SPEND"
                     and t["BankAccount"]["Name"] == w["account"]
                     and abs(t["Total"] - rel["Total"] - w["amount"]) < 0.005
                     and abs((t["_date"] - rel["_date"]).days) <= DATE_WINDOW), None)
        if hold:
            rel["_used"] = hold["_used"] = True
            w.update({"statut": "RAPPROCHE" if hold["IsReconciled"] else "EN_ATTENTE",
                      "xero_id": hold["BankTransactionID"], "xero_date": hold["_date"].isoformat(),
                      "xero_contact": (hold.get("Contact") or {}).get("Name", ""),
                      "xero_account_code": "|".join(l.get("AccountCode") or "" for l in hold["LineItems"]),
                      "xero_has_attachment": hold.get("HasAttachments", False)})

    OUT.mkdir(parents=True, exist_ok=True)
    fields = list(lines[0].keys())
    with open(OUT / "wise_lines.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(sorted(lines, key=lambda w: (w["account"], w["date"], w["wise_id"], w["line"])))

    orphans = [t for t in bts if not t["_used"]]
    with open(OUT / "xero_sans_wise.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["xero_id", "compte", "type", "date", "montant", "contact", "reference", "rapproche", "comptes"])
        for t in orphans:
            wr.writerow([t["BankTransactionID"], t["BankAccount"]["Name"], t["Type"], t["_date"], t["Total"],
                         (t.get("Contact") or {}).get("Name"), t.get("Reference"), t["IsReconciled"],
                         "|".join(l.get("AccountCode") or "" for l in t["LineItems"])])

    # Résumé
    from collections import Counter
    c = Counter((w["account"], w["line"], w["statut"]) for w in lines)
    print("compte        ligne  statut       nb")
    for k in sorted(c):
        print(f"{k[0]:13s} {k[1]:6s} {k[2]:12s} {c[k]}")
    print(f"\nOpérations Xero 2026 sans mouvement Wise en face : {len(orphans)} "
          f"(dont non rapprochées : {sum(not t['IsReconciled'] for t in orphans)})")


if __name__ == "__main__":
    main()
