# from django.db.models.signals import post_save
# from django.dispatch import receiver
# import structlog

# from .models import User
# from Wallet.models import Wallet

# logger = structlog.get_logger(__name__)

# @receiver(post_save, sender=User)
# def auto_create_wallet_on_verify(sender, instance, **kwargs):
#     """
#     Crée le wallet automatiquement quand phone_verified passe à True.
#     """
#     if instance.phone_verified and not hasattr(instance, 'wallet'):
#         try:
#             Wallet.create_for_user(instance)
#         except Exception as e:
#             logger.error("auto_wallet_creation_failed", user_id=str(instance.id), error=str(e))