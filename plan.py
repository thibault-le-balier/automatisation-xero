#!/usr/bin/env python3
"""Construit le plan de saisie (data/work/plan.csv) et le plan des pièces jointes (data/work/attach_plan.csv).

Codage, par ordre de priorité :
  1. règles explicites (RULES) : salaires, Revenue, frais Wise, cashback…
  2. ce qui a déjà été fait dans Xero pour la même contrepartie Wise (contact, compte, TVA les plus fréquents)
  3. à défaut, la catégorie Wise (CATEGORY_DEFAULT), et la ligne est marquée « à confirmer »
Le compte fourre-tout 430 n'est jamais repris : il est remplacé par un compte précis selon la catégorie Wise.
"""
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
WORK = DATA / "work"
TAG = "AUTO26"

# (motif sur la contrepartie Wise, contact Xero, compte, TVA, à confirmer ?)
RULES = [
    (r"revenue commissioners", "REVENUE COMMISSIONERS", "825", "NONE", False),
    (r"^charon hugo$", "Hugo Charon", "804", "NONE", False),
    (r"^le balier thibault$", "THIBAULT LE BALIER", "804", "NONE", False),
    (r"o1 accounting", "O1 ACCOUNTING SERVICES PARIS LONDON DUBL", "412", "INPUT", False),
    (r"^sabri dahmani$", "Sabri DAHMANI", "494", "NONE", True),  # facture d'hébergement à Cully
    (r"vincentius|vito arvy|fata hibban|rohmad|aashish|denys fajar|wildan", None, "4121", "INPUT", False),
    (r"^(anthropic|claude|anthropic claude subscription)$", "CLAUDE AI", "485", "INPUT", False),
    (r"^cursor", "CURSOR", "4852", "INPUT", False),
    (r"^supabase$", "SUPABASE", "4855", "INPUT", False),
    (r"^bubble$", "Bubble", "4853", "INPUT", False),
    (r"^google$", "GOOGLE WORKSPACE", "4851", "INPUT", False),
    (r"^google cloud$", "GOOGLE CLOUD", "4851", "INPUT", False),
    (r"^google ads$", "GOOGLE ADVERTISING", "400", "INPUT", False),
    (r"^facebook$", "META ADVERTISING", "400", "INPUT", False),
    (r"^linkedin$", "Linkedin", "400", "INPUT", False),
    (r"^xero$", "XERO", "463", "INPUT", False),
    (r"^swype$", "SWYPE", "489", "INPUT", False),
    (r"^(x\.com - paid features|x paid features|xai)$", "X AI", "485", "INPUT", False),
    (r"^printoclock$", "Printoclock", "461", "INPUT", False),
    (r"^apollo$", "APOLLO", "485", "INPUT", False),
    (r"^docker$", "DOCKER", "485", "INPUT", False),
    (r"^tavily$", "TAVILY", "485", "INPUT", False),
    (r"aprr|vinci autoroutes|bipandgo|parkingpay|apcoa|parking", None, "493", "INPUT", False),
    (r"^apple distribution", "APPLE", "260", "NONE", True),
    (r"^jane", "JANE", "200", "OUTPUT", False),
    (r"^epfl$", "EPFL", "200", "OUTPUT", False),
]
CATEGORY_DEFAULT = {
    "Software and web hosting": ("485", "INPUT"),
    "Marketing": ("400", "INPUT"),
    "Travel": ("493", "INPUT"),
    "Entertainment": ("420", "NONE"),
    "Office expenses": ("453", "INPUT"),
    "Contract services": ("4121", "INPUT"),
    "Tax": ("825", "NONE"),
    "General": ("429", "INPUT"),
    "Rewards": ("270", "NONE"),
    "Money added": ("260", "NONE"),
}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def load_json(path, default):
    return json.load(open(path)) if path.exists() else default


def main():
    rows = list(csv.DictReader(open(WORK / "wise_lines.csv")))
    bts = {t["BankTransactionID"]: t for t in json.load(open(DATA / "xero" / "bank_transactions.json"))}
    contacts = [c["Name"] for c in json.load(open(DATA / "xero" / "contacts.json")) if c.get("ContactStatus") == "ACTIVE"]
    contact_by_norm = {norm(c): c for c in contacts}
    found = {l["wise_id"]: l for f in sorted((WORK / "found").glob("*.json")) for l in load_json(f, [])}
    docs = defaultdict(list)
    for d in load_json(WORK / "docs_drafts.json", []) + load_json(WORK / "docs_google.json", []):
        if d["file"] not in docs[d["wise_id"]]:
            docs[d["wise_id"]].append(d["file"])

    # 2. Historique : contrepartie Wise -> (contact, compte, TVA) le plus fréquent dans Xero
    history = defaultdict(Counter)
    for r in rows:
        t = bts.get(r["xero_id"])
        if r["line"] == "main" and t and t.get("Contact"):
            for li in t["LineItems"]:
                history[r["counterparty"]][(t["Contact"]["Name"], li.get("AccountCode"), li.get("TaxType"))] += 1

    def code(r):
        cp = r["counterparty"]
        if r["line"] == "fee":
            return "WISE", "404", "NONE", False, "règle"
        if r["kind"] == "BALANCE_CASHBACK":
            return "WISE", "270", "NONE", False, "règle"
        for rx, contact, acc, tax, doubt in RULES:
            if re.search(rx, cp.lower()):
                return contact or find_contact(cp), acc, tax, doubt, "règle"
        if history[cp]:
            (contact, acc, tax), _ = history[cp].most_common(1)[0]
            if acc != "430":
                return contact, acc, tax, False, "historique"
            acc, tax = CATEGORY_DEFAULT.get(r["category"], ("429", "INPUT"))
            return contact, acc, tax, False, "historique (430 remplacé)"
        acc, tax = CATEGORY_DEFAULT.get(r["category"], ("429", "INPUT"))
        return find_contact(cp), acc, tax, True, f"catégorie Wise « {r['category']} »"

    def find_contact(cp):
        n = norm(cp)
        if n in contact_by_norm:
            return contact_by_norm[n]
        hits = [c for k, c in contact_by_norm.items() if len(k) > 4 and len(n) > 4 and (k in n or n in k)]
        return hits[0] if len(hits) == 1 else cp.strip()

    plan, attach = [], []
    for r in rows:
        f = found.get(r["wise_id"], {})
        if r["statut"] == "A_CREER":
            contact, acc, tax, doubt, why = code(r)
            if r["line"] == "fee":
                desc = f"Frais Wise – {r['wise_id']}"
            else:
                desc = f.get("nature") or f"{r['counterparty']} – {r['orig_amount']} {r['orig_currency']}".strip(" –")
                if r["status_wise"] == "REFUNDED":
                    desc = f"Remboursement {desc}"
            if r["counterparty"].lower().startswith("revenue") and abs(float(r["amount"]) - 1917.11) > 1:
                doubt, why = True, why + " ; montant hors mensualité PAYE : vérifier impôt et période"
            plan.append({
                "wise_id": r["wise_id"], "line": r["line"], "bank_account": r["account"], "type": r["type"],
                "date": r["date"], "amount": r["amount"], "currency": r["currency"], "contact": contact,
                "account_code": acc, "tax_type": tax, "description": desc[:400],
                "reference": f"{TAG} {r['wise_id']}" + (" FEE" if r["line"] == "fee" else ""),
                "a_confirmer": "OUI" if doubt else "", "source_codage": why,
                "justificatif": " | ".join(docs.get(r["wise_id"], [])) if r["line"] == "main" else "relevé Wise",
            })
        if r["line"] == "main" and docs.get(r["wise_id"]) and r["xero_has_attachment"] != "True":
            for path in docs[r["wise_id"]]:
                attach.append({"wise_id": r["wise_id"], "statut": r["statut"], "xero_id": r["xero_id"], "file": path})

    for name, data in (("plan.csv", plan), ("attach_plan.csv", attach)):
        if data:
            with open(WORK / name, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(data[0].keys()))
                w.writeheader()
                w.writerows(data)
    c = Counter((p["bank_account"], p["type"], p["line"]) for p in plan)
    print("Écritures à créer :", len(plan), dict(c))
    print("  à confirmer :", sum(p["a_confirmer"] == "OUI" for p in plan))
    print("  avec justificatif :", sum(bool(p["justificatif"]) and p["justificatif"] != "relevé Wise" for p in plan if p["line"] == "main"),
          "/", sum(p["line"] == "main" for p in plan))
    print("Comptes :", Counter(p["account_code"] for p in plan).most_common())
    print("Pièces à joindre :", len(attach), Counter(a["statut"] for a in attach))


if __name__ == "__main__":
    main()
