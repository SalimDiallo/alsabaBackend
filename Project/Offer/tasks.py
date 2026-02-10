from celery import shared_task
from django.utils import timezone
from .models import Offer
from .services import SecureEscrowService
import structlog

logger = structlog.get_logger(__name__)

@shared_task
def check_expired_offers():
    """
    Periodic task to manage expired offers.
    1. OPEN offers -> EXPIRED
    2. LOCKED & Expired offers -> CANCELLED (Rollback)
    """
    now = timezone.now()
    
    # 1. Management of expired OPEN offers
    # They can be closed directly without going through the complex service because no funds are blocked
    expired_open_offers = Offer.objects.filter(
        status='OPEN', 
        expires_at__lt=now
    )
    count_open = expired_open_offers.count()
    if count_open > 0:
        expired_open_offers.update(status='EXPIRED')
        logger.info("expired_offers_cleaned", count=count_open, type="OPEN")

    # 2. Management of expired LOCKED (Blocked funds) offers
    # For these, the service MUST be used to release the funds (Rollback)
    expired_locked_offers = Offer.objects.filter(
        status__in=['LOCKED', 'ACCEPTED'],
        expires_at__lt=now
    )
    
    for offer in expired_locked_offers:
        logger.info("process_expired_locked_offer", offer_id=str(offer.id))
        try:
           SecureEscrowService.cancel_transaction(
               offer.id, 
               reason="Auto-expiration: Finalization delay exceeded"
            )
        except Exception as e:
            logger.exception("failed_to_expire_offer", offer_id=str(offer.id))

    return f"Cleaned {count_open} OPEN offers, Processed {expired_locked_offers.count()} LOCKED offers."
