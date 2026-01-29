from django.apps import AppConfig


class WalletConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Wallet'
    verbose_name = 'Portefeuille Électronique'

    def ready(self):
        # Import des signaux pour créer automatiquement les wallets
        import Wallet.signals
