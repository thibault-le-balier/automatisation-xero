"""Code partagé par les deux sociétés (SMARTKETING LIMITED et BUMPSLAB SARL).

ROOT est la racine du dépôt : .env, jetons OAuth et dossiers de dépôt des justificatifs y restent.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    """Lit ROOT/.env (clé=valeur, une par ligne). Le fichier n'est jamais modifié."""
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("\"'")
    return env
