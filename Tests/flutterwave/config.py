"""
Configuration des scripts manuels Flutterwave.

Les identifiants sont lus depuis l'environnement : ce fichier est versionne,
il ne doit JAMAIS contenir de cles en clair.

    export FLUTTERWAVE_SANDBOX_CLIENT_ID=...
    export FLUTTERWAVE_SANDBOX_CLIENT_SECRET=...
    export FLUTTERWAVE_SANDBOX_ENCRYPTION_KEY=...
"""
import os

CLIENT_ID = os.getenv("FLUTTERWAVE_SANDBOX_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("FLUTTERWAVE_SANDBOX_CLIENT_SECRET", "")
ENCRYPTION_KEY = os.getenv("FLUTTERWAVE_SANDBOX_ENCRYPTION_KEY", "")

BASE_URL_SANDBOX = "https://developersandbox-api.flutterwave.com"
AUTH_URL = "https://idp.flutterwave.com/realms/flutterwave/protocol/openid-connect/token"

CURRENCY = os.getenv("FLUTTERWAVE_CURRENCY", "MAD")  # ou "NGN" pour tests doc
REDIRECT_URL = os.getenv("FLUTTERWAVE_REDIRECT_URL", "https://example.com/retour")

if not CLIENT_ID:
    raise SystemExit(
        "Identifiants Flutterwave absents. Exporte FLUTTERWAVE_SANDBOX_CLIENT_ID, "
        "_CLIENT_SECRET et _ENCRYPTION_KEY avant de lancer ces scripts."
    )
