#!/usr/bin/env python3
"""Exporte les justificatifs manquants en deux listes lisibles dans Excel (une pour Hugo, une pour Thibault).

    python3 export_missing.py   ->  factures_manquantes_hugo.csv, factures_manquantes_thibault.csv
"""
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "data" / "work"

# (motif sur le fournisseur, où trouver le justificatif)
WHERE = [
    (r"le balier thibault", "O1 Accounting (Cindy) : bulletin de paie du mois, édité dans BrightPay"),
    (r"revenue", "O1 Accounting / ROS : avis de paiement PAYE-EMP du mois"),
    (r"sncf", "SNCF Connect : Mon compte > Mes voyages > justificatif, ou e-mail de confirmation"),
    (r"idf mobilit|navigo", "Appli Île-de-France Mobilités : Mon compte > Mes achats > justificatif d'achat"),
    (r"notion", "Notion : Settings > Billing > Invoices"),
    (r"figma", "Figma : Settings > Billing > Invoices"),
    (r"vercel", "Vercel : Settings > Billing > Invoices"),
    (r"1password", "1Password : Billing > Invoices"),
    (r"claude|anthropic", "claude.ai : Settings > Billing > Invoices"),
    (r"cursor", "cursor.com : Settings > Billing > Invoices"),
    (r"openai|chatgpt", "chatgpt.com (compte thibault@smartketing-digital) : Paramètres > Compte > Factures"),
    (r"x\.com|x paid|^xai$", "X : Paramètres > Premium > Gérer l'abonnement > Historique des paiements"),
    (r"swype", "Espace client Swype : Factures"),
    (r"^google$", "Google Workspace : admin.google.com > Facturation > Documents et paiements"),
    (r"google ads", "Google Ads : Facturation > Documents"),
    (r"google cloud", "Google Cloud : console.cloud.google.com > Facturation > Documents"),
    (r"facebook|meta", "Meta Business Suite : Facturation > Activité de paiement > télécharger le reçu"),
    (r"airbnb", "Airbnb : Voyages > détails de la réservation > Reçu"),
    (r"make", "make.com : Organisation > Abonnement > Paiements"),
    (r"supabase", "Supabase : Dashboard > Organisation > Billing > Invoices"),
    (r"^xero$", "Xero : Paramètres > Abonnement et facturation > Historique de facturation"),
    (r"rapid|nokia", "RapidAPI / Nokia API Hub : Billing > Invoices"),
    (r"ux pilot", "UX Pilot : Account > Billing"),
    (r"parkingpay", "Appli Parkingpay : Historique > reçu"),
    (r"bipandgo", "Espace client Bip&Go : Factures"),
    (r"aprr|vinci|autoroute", "Ticket papier, ou relevé télépéage"),
    (r"totalenergies|tamoil|shell|eni", "Ticket papier de la station"),
    (r"apple distribution", "App Store Connect : Paiements et rapports financiers"),
    (r"saily|o2switch|fiverr|printoclock|dribbble", "Espace client du fournisseur : Factures"),
]
PAPER = r"restaurant|pub|auberge|brocoiserie|montagnard|cochon|yokocho|s[uü]rpriz|santa lyna|rehab|express de lyon"


def where(vendor):
    v = vendor.lower()
    if re.search(PAPER, v):
        return "Ticket papier (photo)"
    return next((txt for rx, txt in WHERE if re.search(rx, v)), "Espace client du fournisseur ou e-mail de reçu")


def fr(x):
    return f"{float(x):,.2f}".replace(",", " ").replace(".", ",")


def main():
    lines = {r["wise_id"]: r for r in csv.DictReader(open(WORK / "wise_lines.csv")) if r["line"] == "main"}
    missing = [c for c in csv.DictReader(open(WORK / "couverture.csv")) if c["etat"] == "manquant"]
    cols = ["Date", "Fournisseur", "Montant débité", "Devise", "Montant facturé (devise d'origine)",
            "Compte Wise", "Référence Wise", "Où trouver la facture", "Identifiant (ne pas modifier)"]
    o1 = lambda c: bool(re.search(r"le balier thibault|charon hugo|revenue", c["contrepartie"].lower()))  # pièces d'O1
    hugo = lambda c: "Hugo" in c["carte_de"] and not o1(c)
    for who, test in (("hugo", hugo), ("thibault", lambda c: not hugo(c))):
        rows = []
        for c in sorted(filter(test, missing), key=lambda c: (c["contrepartie"].lower(), c["date"])):
            w = lines[c["wise_id"]]
            orig = f"{fr(w['orig_amount'])} {w['orig_currency']}" if w["orig_currency"] and w["orig_currency"] != w["currency"] else ""
            d = c["date"]
            rows.append([f"{d[8:10]}/{d[5:7]}/{d[:4]}", c["contrepartie"], fr(c["montant"]), c["devise"], orig,
                         c["compte"].replace("Compte ", ""), w["reference"], where(c["contrepartie"]), c["wise_id"]])
        out = ROOT / f"factures_manquantes_{who}.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as fh:  # BOM : accents corrects dans Excel
            wr = csv.writer(fh, delimiter=";")
            wr.writerow(cols)
            wr.writerows(rows)
        total = {}
        for r in rows:
            total[r[3]] = total.get(r[3], 0) + float(r[2].replace(" ", "").replace(",", "."))
        print(f"{out.name} : {len(rows)} lignes ({', '.join(f'{fr(v)} {k}' for k, v in total.items())})")


if __name__ == "__main__":
    main()
