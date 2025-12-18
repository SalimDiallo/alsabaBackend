from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'Accounts'


# from django.apps import AppConfig


# class AccountsConfig(AppConfig):
#     default_auto_field = 'django.db.models.BigAutoField'
#     name = 'accounts'
    
#     def ready(self):
#         """Code à exécuter quand l'app est prête"""
#         import accounts.signals  # Pour les signaux si besoin