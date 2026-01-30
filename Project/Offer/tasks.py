from celery import shared_task
from django.utils import timezone
from .models import Offer
from .services import SecureEscrowService
import structlog

logger = structlog.get_logger(__name__)

@shared_task
def check_expired_offers():
    """
    Tâche périodique pour gérer les offres expirées.
    1. Offers OPEN -> EXPIRED
    2. Offers LOCKED & Expired -> CANCELLED (Rollback)
    """
    now = timezone.now()
    
    # 1. Gestion des offres OPEN expirées
    # On peut les fermer directement sans passer par le service complexe car pas de fonds bloqués
    expired_open_offers = Offer.objects.filter(
        status='OPEN', 
        expires_at__lt=now
    )
    count_open = expired_open_offers.count()
    if count_open > 0:
        expired_open_offers.update(status='EXPIRED')
        logger.info("expired_offers_cleaned", count=count_open, type="OPEN")

    # 2. Gestion des offres LOCKED (Fonds bloqués) expirées
    # Pour celles-ci, IL FAUT utiliser le service pour libérer les fonds (Rollback)
    expired_locked_offers = Offer.objects.filter(
        status__in=['LOCKED', 'ACCEPTED'],
        expires_at__lt=now
    )
    
    for offer in expired_locked_offers:
        logger.info("process_expired_locked_offer", offer_id=str(offer.id))
        try:
           SecureEscrowService.cancel_transaction(
               offer.id, 
               reason="Auto-expiration: Délai de finalisation dépassé"
            )
        except Exception as e:
            logger.exception("failed_to_expire_offer", offer_id=str(offer.id))

    return f"Cleaned {count_open} OPEN offers, Processed {expired_locked_offers.count()} LOCKED offers."
