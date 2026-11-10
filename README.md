# Justificatifs comptables 2026

Rapprochement des opérations bancaires de deux sociétés avec leurs factures et tickets.

| Dossier | Société | Banque | Où vont les pièces |
|---|---|---|---|
| `smartketing/` | SMARTKETING LIMITED (Irlande) | Wise, comptes CHF et EURO | Xero |
| `bumpslab/` | BUMPSLAB SARL (France) | Qonto, compte principal | Qonto |
| `commun/` | Code partagé : `.env`, lecture des montants et des dates, contrôle des fichiers | | |

Les scripts se lancent depuis la racine, en module :

```
python3 -m smartketing.report           # couverture Wise / Xero -> factures_manquantes_smartketing.csv (via export_missing)
python3 -m smartketing.export_missing
python3 -m bumpslab.qonto_snapshot      # photographie Qonto (lecture seule)
python3 -m bumpslab.report              # couverture Qonto -> factures_manquantes_bumpslab.csv
```

## Données

Rien n'est versionné (voir `.gitignore`) :

- `data/smartketing/` : `wise/` (exports « transaction history »), `xero/` (photos de Xero), `work/` (calculs et journaux), `invoices/` (pièces).
- `data/bumpslab/` : `qonto/` (photos de Qonto), `work/`, `invoices/`.
- `.env` : `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `WISE_API_KEY` et `QONTO_API_KEY`. Pour Qonto, la clé secrète seule ; l'identifiant de l'organisation est dans `bumpslab/__init__.py`.

## Règles

- Ne pas envoyer de justificatif par l'appli Wise : il crée une dépense en double dans Xero.
- Sous 1 € ou 1 CHF, le relevé bancaire suffit : pas de facture.
- Les photos de tickets prises dans l'appli Wise arrivent dans Xero sous le nom `img_….png`. Avant de joindre une photo de ticket, vérifier qu'elle n'y est pas déjà.
