from django.apps import AppConfig


class WalletConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Wallet'
    verbose_name = 'Electronic Wallet'

    def ready(self):
        # Import signals to automatically create wallets
        pass
