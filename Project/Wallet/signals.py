"""
Signals pour l'application wallet
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

from Accounts.models import User  # Adaptez ce chemin selon votre structure
import structlog

logger = structlog.get_logger(__name__)


@receiver(post_save, sender=User)
def create_wallet_on_phone_verification(sender, instance, **kwargs):
    """
    Crée automatiquement un wallet quand un utilisateur vérifie son téléphone
    
    S'active quand :
    1. Un nouvel utilisateur est créé avec phone_verified=True (register OTP réussi)
    2. Un utilisateur existant passe phone_verified de False à True
    """
    # Vérifier si le téléphone vient d'être vérifié
    if instance.phone_verified:
        try:
            from .Services.wallet_service import WalletService
            from .models import Wallet
            
            # Vérifier si le wallet existe déjà
            if not Wallet.objects.filter(user=instance).exists():
                # Créer le wallet
                wallet = WalletService.create_wallet_for_user(instance)
                
                logger.info(
                    "wallet_auto_created_on_phone_verification",
                    user_id=str(instance.id),
                    wallet_id=str(wallet.id),
                    currency=wallet.currency.code
                )
            else:
                logger.debug(
                    "wallet_already_exists",
                    user_id=str(instance.id)
                )
                
        except Exception as e:
            logger.error(
                "wallet_auto_creation_failed",
                user_id=str(instance.id),
                error=str(e),
                exc_info=True
            )