from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
import structlog

from .Services.wallet_service import wallet_service

logger = structlog.get_logger(__name__)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_wallet_for_new_user(sender, instance, created, **kwargs):
    """
    Crée automatiquement un wallet pour chaque nouvel utilisateur
    """
    if created:
        try:
            wallet = wallet_service.create_wallet_for_user(instance)
            logger.info(
                "auto_wallet_created",
                user_id=str(instance.id),
                wallet_id=str(wallet.id)
            )
        except Exception as e:
            logger.error(
                "auto_wallet_creation_failed",
                user_id=str(instance.id),
                error=str(e)
            )