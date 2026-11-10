#!/usr/bin/env python3
"""Exporte les justificatifs manquants (Thibault et Hugo) dans une seule liste lisible dans Excel.

    python3 -m smartketing.export_missing   ->  data/smartketing/factures_manquantes_smartketing.csv

Format : séparateur « ; », UTF-8 avec BOM (accents corrects dans Excel), virgule décimale.
Seulement les justificatifs à fournir, triés par type de pièce, avec la façon de les obtenir
(les opérations pour lesquelles le relevé Wise suffit n'y figurent pas).
"""
import csv
import re
from datetime import date

from smartketing import DATA
WORK = DATA / "work"

O1 = r"le balier thibault|charon hugo|revenue"
PAPER = (r"restaurant|\bpub\b|auberge|brocoiserie|montagnard|cochon|yokocho|s[uü]rpriz|santa lyna|rehab|express de lyon"
         r"|aprr|vinci|autoroute|totalenergies|tamoil|shell|^eni$")
TYPES = ["Bulletin de paie (O1)", "À télécharger en ligne", "Duplicata à demander", "Ticket papier"]

# (motif sur le fournisseur, comment obtenir la pièce) : le premier motif qui correspond l'emporte
HOW = [
    (r"le balier thibault", "Bulletins de décembre 2025 de Thibault et Hugo : pièce jointe de l'e-mail de Cindy (O1) du "
                            "13/01/2026, trop lourde pour être récupérée automatiquement. L'enregistrer en PDF dans le dossier."),
    (r"revenue", "O1 Accounting / ROS : avis de paiement PAYE-EMP du mois."),
    (r"google ads", "Compte Google Ads 388-623-0358 : ce débit (27,49 € + 1,22 €) solde le compte suspendu en février-mars. "
                    "Facture ou relevé de septembre 2026 dans Google Ads > Facturation > Documents."),
    (r"apple distribution", "Encaissement, pas une dépense : revenus App Store versés par Apple. Relevé de paiement "
                            "d'avril 2026 dans App Store Connect > Paiements et rapports financiers."),
    (r"^rapid", "Abonnement RapidAPI à 9,99 USD (factures émises par Nokia of America). Deux abonnements semblent "
                "tourner, le 4 et le 19 du mois. RapidAPI > Billing > Transactions History."),
    (r"nokia", "Abonnement RapidAPI à 9,99 USD (Nokia of America émet les factures RapidAPI). "
               "RapidAPI > Billing > Transactions History."),
    (r"o2switch", "Hébergement bumps.fr : facture de janvier 2026 dans l'espace client o2switch > Factures "
                  "(le Drive n'a que celles d'août et septembre)."),
    (r"saily", "eSIM Saily (groupe Nord), achat de 13,99 USD : Nord Account > Facturation, "
               "ou appli Saily > Profil > Historique des achats."),
    (r"idf mobilit|navigo", "Achat du jour (12,75 € = sans doute 5 tickets à 2,55 €). Appli Île-de-France Mobilités > "
                            "Mon compte > Mes achats > justificatif d'achat."),
    (r"grand somma", "Auberge du Grand-Sommartel, La Sagne (NE). Photo du ticket, ou à défaut demander un duplicata."),
    (r"montagnard", "Les Montagnards, brasserie, rue de Montsalvens 4, 1636 Broc (lesmontagnards.ch). "
                    "Photo du ticket, ou à défaut demander un duplicata."),
    (r"brocoiserie", "La Brocoiserie, boulangerie-café, rue de Montsalvens 3, 1636 Broc (en face des Montagnards). "
                     "Photo du ticket, ou à défaut demander un duplicata."),
    (r"s[uü]rpriz", "Catégorie Wise « Travel » : sans doute un repas en déplacement. Photo du ticket."),
    (r"totalenergies|tamoil|shell", "Photo du ticket de la station."),
    (r"aprr|vinci|autoroute", "Photo du ticket de la borne de péage."),
    (PAPER, "Photo du ticket, ou à défaut demander un duplicata au restaurant."),
    (r"sncf", "SNCF Connect : Mon compte > Mes voyages > justificatif, ou e-mail de confirmation."),
    (r"airbnb", "Airbnb : Voyages > détails de la réservation > Reçu."),
    (r"parkingpay", "Appli ou site Parkingpay : relevé de compte du mois."),
]
def kind(vendor):
    v = vendor.lower()
    if re.search(O1, v):
        return TYPES[0]
    if re.search(r"idf mobilit|navigo", v):
        return TYPES[2]
    if re.search(PAPER, v):
        return TYPES[3]
    return TYPES[1]


def how(vendor):
    v = vendor.lower()
    return next((txt for rx, txt in HOW if re.search(rx, v)), "Espace client du fournisseur, ou e-mail de reçu.")


# Nom lisible du fournisseur (le libellé Wise est souvent tronqué)
NAMES = [
    (r"lesmontagnards", "Les Montagnards (Broc)"), (r"brocoiserie", "La Brocoiserie (Broc)"),
    (r"grand somma", "Auberge du Grand-Sommartel (La Sagne)"), (r"express de lyon", "L'Express de Lyon"),
    (r"cochon volant", "Au Cochon Volant"), (r"idf mobilit|navigo", "Île-de-France Mobilités"),
    (r"apple distribution", "Apple (App Store)"), (r"vinci", "VINCI Autoroutes"), (r"^le balier thibault$", "Salaire Thibault Le Balier"),
]
CATEGORIES = [
    (r"totalenergies|tamoil|shell|^eni$", "Carburant"), (r"aprr|vinci|autoroute|bipandgo", "Péage"),
    (r"parking", "Stationnement"), (r"sncf|idf mobilit|navigo|airbnb|h[oô]tel", "Déplacement"),
    (r"le balier thibault|charon hugo|revenue", "Salaires et charges"), (PAPER, "Repas"),
    (r"google ads|facebook|meta|linkedin", "Publicité"), (r"apple distribution", "Recette App Store"),
]


def pick(table, vendor, default):
    v = vendor.lower()
    return next((val for rx, val in table if re.search(rx, v)), default)


def fr(x):
    return f"{float(x):,.2f}".replace(",", " ").replace(".", ",")


def main():
    lines = {r["wise_id"]: r for r in csv.DictReader(open(WORK / "wise_lines.csv")) if r["line"] == "main"}
    missing = [c for c in csv.DictReader(open(WORK / "couverture.csv")) if c["etat"] == "manquant"]
    rows = []
    for c in missing:
        w, v = lines[c["wise_id"]], c["contrepartie"]
        who = "Hugo" if "Hugo" in c["carte_de"] and not re.search(O1, v.lower()) else "Thibault"  # pièces d'O1 : Thibault
        orig = f"{fr(w['orig_amount'])} {w['orig_currency']}" if w["orig_currency"] and w["orig_currency"] != w["currency"] else ""
        rows.append({"Qui fournit la pièce": who, "Date du paiement": date.fromisoformat(c["date"]),
                     "Fournisseur": pick(NAMES, v, v.strip()), "Libellé sur le relevé Wise": v.strip(),
                     "Montant payé": fr(c["montant"]), "Devise": c["devise"], "Montant facturé (devise d'origine)": orig,
                     "Compte Wise": c["compte"].replace("Compte ", ""), "Catégorie": pick(CATEGORIES, v, "Logiciels et services"),
                     "Pièce à fournir": kind(v), "Où la trouver / précisions": how(v) + (
                         f" Attention : {c['detail']}." if "supprimer dans Xero" in c["detail"] else ""),
                     "Identifiant Wise (ne pas modifier)": c["wise_id"]})
    rows.sort(key=lambda r: (r["Qui fournit la pièce"] != "Thibault", r["Date du paiement"]))
    cols = list(rows[0]) if rows else []
    if not any(r["Montant facturé (devise d'origine)"] for r in rows):  # colonne vide : on l'enlève
        cols = [k for k in cols if k != "Montant facturé (devise d'origine)"]
    out = DATA / "factures_manquantes_smartketing.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:  # BOM : accents corrects dans Excel
        wr = csv.writer(fh, delimiter=";")
        wr.writerow(cols)
        for r in rows:
            wr.writerow([f"{r[k]:%d/%m/%Y}" if k == "Date du paiement" else r[k] for k in cols])
    total = {}
    for r in rows:
        k = (r["Qui fournit la pièce"], r["Devise"])
        total[k] = total.get(k, 0) + float(r["Montant payé"].replace(" ", "").replace(",", "."))
    print(f"{out.name} : {len(rows)} lignes ; " + ", ".join(f"{w} {fr(v)} {d}" for (w, d), v in sorted(total.items())))


if __name__ == "__main__":
    main()
