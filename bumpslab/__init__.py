"""BUMPSLAB SARL (France, SIREN 100 095 686) : compte Qonto, justificatifs joints dans Qonto.

Lancer les scripts depuis la racine du dépôt : python3 -m bumpslab.<script>
"""
from commun import ROOT

DATA = ROOT / "data" / "bumpslab"  # qonto/ (photos de Qonto), work/ (calculs), invoices/ (pièces)
QONTO_LOGIN = "bumpslab-3355"      # identifiant de l'organisation ; la clé secrète est QONTO_API_KEY dans .env
