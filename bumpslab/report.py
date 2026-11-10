#!/usr/bin/env python3
"""Couverture des justificatifs du compte Qonto de BUMPSLAB, à partir de data/bumpslab/qonto/ (qonto_snapshot).

    python3 -m bumpslab.report

Sorties :
  data/bumpslab/work/couverture.csv    une ligne par opération (justifiée ou non, et pourquoi)
  factures_manquantes_bumpslab.csv     les pièces à fournir, lisible dans Excel (séparateur « ; », UTF-8 avec BOM)
"""
import csv
import json
import re
from collections import Counter
from datetime import date

from bumpslab import DATA
from commun import ROOT

QONTO = DATA / "qonto"
WORK = DATA / "work"

# Opérations sans pièce à fournir (décision de Thibault, 10/11/2026) : URSSAF, impôts (DGFIP, SIE = service des impôts
# des entreprises) et virements à Thibault (remboursements de notes de frais ou rémunération de gérant TNS).
NO_DOC = r"urssaf|dgfip|finances pu|sie paris|le balier thibault"

# (motif sur le libellé, type de pièce, où la trouver) : le premier motif qui correspond l'emporte
HOW = [
    (r"hugo charon", "Justificatif interne",
     "Virement à Hugo : bulletin de paie, note de frais ou décision de distribution, selon la nature du virement."),
    (r"repam", "À télécharger en ligne", "Espace client REPAM : avis d'échéance ou attestation de l'assurance."),
    (r"^qonto$", "À télécharger en ligne", "Qonto > Paramètres > Abonnement > Factures."),
    (r"anthropic", "À télécharger en ligne", "claude.ai > Settings > Billing > Invoices, ou e-mail de reçu d'Anthropic."),
    (r"openai", "À télécharger en ligne", "platform.openai.com > Settings > Billing > Invoices, ou e-mail de reçu d'OpenAI."),
    (r"apollo", "À télécharger en ligne", "Apollo.io > Settings > Plans & Billing > Invoices."),
    (r"figma", "À télécharger en ligne", "Figma > Settings > Billing > Invoices, ou e-mail de reçu."),
    (r"notion", "À télécharger en ligne", "Notion > Settings > Billing > Invoices, ou e-mail de reçu."),
    (r"vercel", "À télécharger en ligne", "Vercel > Settings > Billing > Invoices, ou e-mail de reçu."),
    (r"1password", "À télécharger en ligne", "1Password > Billing > Invoices, ou e-mail de reçu."),
    (r"cohere", "À télécharger en ligne", "dashboard.cohere.com > Billing, ou e-mail de reçu."),
    (r"google workspace", "À télécharger en ligne", "admin.google.com > Facturation > Documents et paiements."),
    (r"swype", "À télécharger en ligne", "Appli Swype : historique des achats ou e-mail de reçu."),
    (r"sncf", "À télécharger en ligne", "SNCF Connect : Mon compte > Mes voyages > justificatif, ou e-mail de confirmation."),
    (r"airbnb", "À télécharger en ligne", "Airbnb : Voyages > détails de la réservation > Reçu."),
    (r"booking", "À télécharger en ligne", "Booking.com : Réservations > Facture, ou facture demandée à l'hôtel."),
    (r"paybyphone", "À télécharger en ligne", "Appli PayByPhone : Historique > reçu de la session de stationnement."),
    (r"h[oô]tel", "Ticket papier", "Facture de l'hôtel (papier ou e-mail)."),
]


def how(label):
    v = label.lower()
    return next(((k, t) for rx, k, t in HOW if re.search(rx, v)), ("À télécharger en ligne", "Espace client du fournisseur, ou e-mail de reçu."))


def fr(x):
    return f"{float(x):,.2f}".replace(",", " ").replace(".", ",")


def main():
    tx = json.load(open(QONTO / "transactions.json"))
    who = {m["id"]: m["first_name"].split()[0] for m in json.load(open(QONTO / "memberships.json"))}
    out = []
    for t in sorted(tx, key=lambda t: t["emitted_at"]):
        if t["status"] in ("declined", "reversed"):
            continue
        amount = float(t["amount"])
        if t.get("attachment_ids"):
            etat, detail = "justificatif joint dans Qonto", ""
        elif amount < 1:  # même règle que Smartketing (décision de Thibault, 09/11/2026)
            etat, detail = "sans justificatif (relevé Qonto)", "montant inférieur à 1 (autorisation de carte ou frais minimes)"
        elif re.search(NO_DOC, t["label"].lower()):  # décision de Thibault (10/11/2026)
            etat = "sans justificatif (relevé Qonto)"
            detail = ("virement à Thibault : remboursement de notes de frais ou rémunération de gérant TNS"
                      if "le balier" in t["label"].lower() else "prélèvement URSSAF ou impôts (DGFIP, SIE) : le relevé suffit")
        elif t["side"] == "credit":
            etat, detail = "manquant", "encaissement : facture de vente, contrat ou justificatif de l'apport"
        else:
            etat, detail = "manquant", ""
        foreign = t.get("local_currency") and t["local_currency"] != t["currency"]
        out.append({"date": t["emitted_at"][:10], "statut_qonto": t["status"], "sens": t["side"],
                    "type": t["operation_type"], "montant": t["amount"], "devise": t["currency"],
                    "montant_origine": f"{t['local_amount']} {t['local_currency']}" if foreign else "",
                    "libelle": t["label"], "carte": t.get("card_last_digits") or "",
                    "porteur": who.get(t.get("initiator_id"), ""), "categorie_qonto": t.get("category") or "",
                    "etat": etat, "detail": detail, "qonto_id": t["id"]})

    WORK.mkdir(parents=True, exist_ok=True)
    with open(WORK / "couverture.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    by_state = Counter(o["etat"] for o in out)
    print(f"{len(out)} opérations Qonto (hors refusées et annulées) :")
    for k, v in by_state.most_common():
        print(f"  {k:34s} {v:4d}   ({sum(float(o['montant']) for o in out if o['etat'] == k):,.2f} EUR)")

    rows = []
    for o in out:
        if o["etat"] != "manquant":
            continue
        kind, where = how(o["libelle"])
        if o["sens"] == "credit":
            kind, where = "Justificatif d'encaissement", o["detail"]
        if o["statut_qonto"] == "pending":
            where += " (opération encore en attente chez Qonto)"
        rows.append({"Qui fournit la pièce": o["porteur"] or "Thibault", "Date du paiement": date.fromisoformat(o["date"]),
                     "Libellé Qonto": o["libelle"], "Montant payé": fr(o["montant"]), "Devise": o["devise"],
                     "Montant facturé (devise d'origine)": o["montant_origine"].replace(".", ","),
                     "Carte": o["carte"], "Type d'opération": o["type"], "Pièce à fournir": kind,
                     "Où la trouver / précisions": where, "Identifiant Qonto (ne pas modifier)": o["qonto_id"]})
    rows.sort(key=lambda r: (r["Qui fournit la pièce"] != "Thibault", r["Date du paiement"]))
    path = ROOT / "factures_manquantes_bumpslab.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:  # BOM : accents corrects dans Excel
        wr = csv.writer(fh, delimiter=";")
        cols = list(rows[0]) if rows else []
        wr.writerow(cols)
        for r in rows:
            wr.writerow([f"{r[k]:%d/%m/%Y}" if k == "Date du paiement" else r[k] for k in cols])
    print(f"  {path.name} : {len(rows)} pièces à fournir")


if __name__ == "__main__":
    main()
