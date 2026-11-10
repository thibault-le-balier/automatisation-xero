#!/usr/bin/env python3
"""Crée dans Xero les écritures du plan (non rapprochées) et joint les justificatifs.

    python3 push.py                     # simulation : valide tout, n'écrit rien
    python3 push.py --go --limit 5      # crée 5 écritures (+ leurs pièces jointes)
    python3 push.py --go                # crée tout le reste
    python3 push.py --go --attach-only  # joint les pièces aux opérations déjà rapprochées
    python3 push.py --go --undo         # supprime les écritures AUTO26 encore non rapprochées

Chaque écriture porte la référence « AUTO26 <id Wise> » : relancer le script ne crée jamais de doublon.
Les écritures sont créées NON rapprochées : Xero les propose ensuite en face de la ligne du relevé (bouton OK).
"""
import argparse
import csv
import json
import mimetypes
import sys
import urllib.parse
from pathlib import Path

import xero_api as x

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
WORK = DATA / "work"
TAG = "AUTO26"
MAX_FILE = 10 * 1024 * 1024
MIME = {".pdf": "application/pdf", ".eml": "message/rfc822", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".html": "text/html", ".txt": "text/plain"}


def existing_auto():
    """Écritures AUTO26 déjà présentes dans Xero : référence -> opération."""
    found = x.get_all("BankTransactions", "BankTransactions",
                      where=f'Reference!=null&&Reference.StartsWith("{TAG} ")')
    return {t["Reference"]: t for t in found if t["Status"] != "DELETED"}


def load_refs():
    accounts = json.load(open(DATA / "xero" / "accounts.json"))
    banks = {a["Name"]: a["AccountID"] for a in accounts if a["Type"] == "BANK"}
    codes = {a["Code"] for a in accounts if a.get("Code") and a["Status"] == "ACTIVE"}
    contacts = {c["Name"]: c["ContactID"] for c in json.load(open(DATA / "xero" / "contacts.json"))
                if c.get("ContactStatus") == "ACTIVE"}
    return banks, codes, contacts


def payload(p, banks, contacts):
    contact = {"ContactID": contacts[p["contact"]]} if p["contact"] in contacts else {"Name": p["contact"]}
    return {
        "Type": p["type"], "Contact": contact, "BankAccount": {"AccountID": banks[p["bank_account"]]},
        "Date": p["date"], "Reference": p["reference"], "CurrencyCode": p["currency"],
        "LineAmountTypes": "Inclusive",
        "LineItems": [{"Description": p["description"], "Quantity": 1, "UnitAmount": float(p["amount"]),
                       "AccountCode": p["account_code"], "TaxType": p["tax_type"]}],
    }


def validate(plan, banks, codes):
    errors = []
    for p in plan:
        if p["bank_account"] not in banks:
            errors.append(f"{p['wise_id']}: compte bancaire inconnu {p['bank_account']}")
        if p["account_code"] not in codes:
            errors.append(f"{p['wise_id']}: compte {p['account_code']} inexistant ou archivé")
        if float(p["amount"]) <= 0:
            errors.append(f"{p['wise_id']}: montant {p['amount']}")
        for f in filter(None, p["justificatif"].split(" | ")):
            if f != "relevé Wise" and not (ROOT / f).exists():
                errors.append(f"{p['wise_id']}: fichier absent {f}")
    return errors


def attach(bt_id, path):
    path = ROOT / path
    data = path.read_bytes()
    if len(data) > MAX_FILE:
        return f"trop gros ({len(data)} o)"
    mime = MIME.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    name = urllib.parse.quote(path.name)
    x.upload(f"BankTransactions/{bt_id}/Attachments/{name}", data, mime)
    return "ok"


def attachments_of(bt_id):
    return {a["FileName"] for a in x.get(f"BankTransactions/{bt_id}/Attachments")["Attachments"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="écrire réellement dans Xero")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--attach-only", action="store_true")
    ap.add_argument("--undo", action="store_true")
    ap.add_argument("--only", default="", help="références Wise séparées par des virgules")
    ap.add_argument("--include-doubtful", action="store_true", help="inclure les lignes « à confirmer »")
    args = ap.parse_args()

    plan = list(csv.DictReader(open(WORK / "plan.csv")))
    banks, codes, contacts = load_refs()
    log_path = WORK / "push_log.jsonl"

    def log(event):
        with open(log_path, "a") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    if args.undo:
        auto = existing_auto()
        todo = [t for t in auto.values() if not t["IsReconciled"]]
        print(f"{len(todo)} écritures AUTO26 non rapprochées à supprimer ({len(auto) - len(todo)} déjà rapprochées, conservées)")
        if args.go:
            for t in todo:
                x.post(f"BankTransactions/{t['BankTransactionID']}",
                       {"BankTransactions": [{"BankTransactionID": t["BankTransactionID"], "Status": "DELETED"}]})
                log({"action": "delete", "id": t["BankTransactionID"], "ref": t["Reference"]})
        return

    if args.attach_only:
        rows = list(csv.DictReader(open(WORK / "attach_plan.csv")))
        rows = [r for r in rows if r["statut"] in ("RAPPROCHE", "EN_ATTENTE") and r["xero_id"]]
        print(f"{len(rows)} pièces à joindre à des opérations existantes")
        if not args.go:
            for r in rows[:10]:
                print("  ", r["wise_id"], "->", r["xero_id"], r["file"])
            return
        done = 0
        for r in rows[: args.limit or None]:
            if Path(r["file"]).name in attachments_of(r["xero_id"]):
                continue
            status = attach(r["xero_id"], r["file"])
            log({"action": "attach", "wise_id": r["wise_id"], "id": r["xero_id"], "file": r["file"], "status": status})
            done += status == "ok"
        print(f"{done} pièces jointes ajoutées")
        return

    errors = validate(plan, banks, codes)
    if errors:
        print("Plan invalide :", *errors, sep="\n  ")
        sys.exit(1)
    auto = existing_auto()
    todo = [p for p in plan if p["reference"] not in auto]
    if args.only:
        wanted = {w.strip() for w in args.only.split(",")}
        todo = [p for p in todo if p["wise_id"] in wanted or p["reference"] in wanted]
    if not args.include_doubtful:
        skipped = [p for p in todo if p["a_confirmer"] == "OUI"]
        todo = [p for p in todo if p["a_confirmer"] != "OUI"]
        if skipped:
            print(f"{len(skipped)} lignes « à confirmer » écartées (--include-doubtful pour les inclure)")
    # Les lignes avec justificatif d'abord, pour que le test porte aussi sur les pièces jointes.
    todo.sort(key=lambda p: (p["justificatif"] in ("", "relevé Wise"), p["date"]))
    if args.limit:
        todo = todo[: args.limit]
    new_contacts = sorted({p["contact"] for p in todo if p["contact"] not in contacts})
    print(f"Plan : {len(plan)} écritures, déjà dans Xero : {len(plan) - len([p for p in plan if p['reference'] not in auto])}, à créer maintenant : {len(todo)}")
    print(f"Nouveaux contacts créés au passage : {len(new_contacts)} {new_contacts}")
    for p in todo[:8]:
        print(f"  {p['date']} {p['bank_account']:11s} {p['type']:7s} {p['amount']:>9} {p['currency']} "
              f"{p['account_code']:5s} {p['contact'][:25]:25s} {p['description'][:45]}")
    if not args.go:
        (WORK / "payloads.json").write_text(json.dumps([payload(p, banks, contacts) for p in todo], indent=1, ensure_ascii=False))
        print("\nSimulation uniquement (rien n'a été écrit). Payloads : data/work/payloads.json. Relancer avec --go.")
        return

    created = 0
    for i in range(0, len(todo), 25):
        batch = todo[i:i + 25]
        res = x.put("BankTransactions", {"BankTransactions": [payload(p, banks, contacts) for p in batch]},
                    summarizeErrors="false")
        for p, t in zip(batch, res["BankTransactions"]):
            if t.get("HasValidationErrors") or t.get("ValidationErrors"):
                print("  ERREUR", p["wise_id"], t.get("ValidationErrors"))
                log({"action": "create_error", "wise_id": p["wise_id"], "errors": t.get("ValidationErrors")})
                continue
            created += 1
            log({"action": "create", "wise_id": p["wise_id"], "id": t["BankTransactionID"], "ref": p["reference"],
                 "total": t["Total"], "currency": t["CurrencyCode"]})
            if abs(t["Total"] - float(p["amount"])) > 0.005:
                print("  ATTENTION total Xero", t["Total"], "≠", p["amount"], p["wise_id"])
            for f in filter(None, p["justificatif"].split(" | ")):
                if f != "relevé Wise":
                    status = attach(t["BankTransactionID"], f)
                    log({"action": "attach", "wise_id": p["wise_id"], "id": t["BankTransactionID"], "file": f, "status": status})
    print(f"{created} écritures créées. Journal : data/work/push_log.jsonl")


if __name__ == "__main__":
    main()
