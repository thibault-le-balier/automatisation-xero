#!/usr/bin/env python3
"""Exporte les justificatifs manquants en deux listes lisibles dans Excel (une pour Hugo, une pour Thibault).

    python3 export_missing.py   ->  factures_manquantes_hugo.csv, factures_manquantes_thibault.csv

Format : séparateur « ; », UTF-8 avec BOM (accents corrects dans Excel), virgule décimale.
Seulement les justificatifs à fournir, triés par type de pièce, avec la façon de les obtenir
(les opérations pour lesquelles le relevé Wise suffit n'y figurent pas).
"""
import csv
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "data" / "work"

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
    (r"grand somma", "Auberge du Grand-Sommartel, La Sagne (NE). Photo du ticket ; à défaut, demander un duplicata."),
    (r"montagnard", "Les Montagnards, brasserie, rue de Montsalvens 4, 1636 Broc (lesmontagnards.ch). "
                    "Photo du ticket ; à défaut, demander un duplicata."),
    (r"brocoiserie", "La Brocoiserie, boulangerie-café, rue de Montsalvens 3, 1636 Broc (en face des Montagnards). "
                     "Photo du ticket ; à défaut, demander un duplicata."),
    (r"s[uü]rpriz", "Catégorie Wise « Travel » : sans doute un repas en déplacement. Photo du ticket."),
    (r"totalenergies|tamoil|shell", "Photo du ticket de la station."),
    (r"aprr|vinci|autoroute", "Photo du ticket de la borne de péage."),
    (PAPER, "Photo du ticket ; à défaut, demander un duplicata au restaurant."),
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


def fr(x):
    return f"{float(x):,.2f}".replace(",", " ").replace(".", ",")


def main():
    lines = {r["wise_id"]: r for r in csv.DictReader(open(WORK / "wise_lines.csv")) if r["line"] == "main"}
    cov = list(csv.DictReader(open(WORK / "couverture.csv")))
    cols = ["Type de justificatif", "Date", "Fournisseur", "Montant débité", "Devise",
            "Montant facturé (devise d'origine)", "Compte Wise", "Comment l'obtenir", "Identifiant (ne pas modifier)"]
    o1 = lambda c: bool(re.search(O1, c["contrepartie"].lower()))  # pièces d'O1 : toujours chez Thibault
    hugo = lambda c: "Hugo" in c["carte_de"] and not o1(c)
    for who, test in (("hugo", hugo), ("thibault", lambda c: not hugo(c))):
        todo = []
        for c in filter(test, cov):
            w = lines[c["wise_id"]]
            d = date.fromisoformat(c["date"])
            orig = f"{fr(w['orig_amount'])} {w['orig_currency']}" if w["orig_currency"] and w["orig_currency"] != w["currency"] else ""
            row = [d, c["contrepartie"].replace("TransferWise", "Wise"), fr(c["montant"]), c["devise"], orig,
                   c["compte"].replace("Compte ", "")]
            if c["etat"] == "manquant":
                todo.append([kind(c["contrepartie"])] + row + [how(c["contrepartie"]), c["wise_id"]])
        todo.sort(key=lambda r: (TYPES.index(r[0]), r[1]))
        out = ROOT / f"factures_manquantes_{who}.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as fh:  # BOM : accents corrects dans Excel
            wr = csv.writer(fh, delimiter=";")
            wr.writerow(cols)
            wr.writerows([r[0], f"{r[1]:%d/%m/%Y}"] + r[2:] for r in todo)
        (ROOT / f"factures_manquantes_{who}.xlsx").unlink(missing_ok=True)
        total = {}
        for r in todo:
            total[r[4]] = total.get(r[4], 0) + float(r[3].replace(" ", "").replace(",", "."))
        print(f"{out.name} : {len(todo)} lignes ({', '.join(f'{fr(v)} {k}' for k, v in total.items())})")


if __name__ == "__main__":
    main()
