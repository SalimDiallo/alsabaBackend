from django.db.models.signals import post_save
from django.db import transaction as db_transaction
from django.dispatch import receiver
from Offer.models import Offer, Dispute
from .services import UserPreferenceService
import structlog

logger = structlog.get_logger(__name__)


@receiver(post_save, sender=Offer)
def handle_offer_events(sender, instance, created, **kwargs):
    offer = instance

    # 1. Nouvelle offre OPEN -> matching push (asynchrone, après commit)
    if created and offer.status == "OPEN":
        offer_id = str(offer.id)

        def _enqueue():
            try:
                from .tasks import match_new_offer_task
                match_new_offer_task.delay(offer_id)
            except Exception as e:
                logger.error("matching_enqueue_failure", offer_id=offer_id, error=str(e))

        # on_commit : garantit que l'offre est visible par le worker (prod) et
        # évite de matcher une offre qui pourrait être rollback.
        db_transaction.on_commit(_enqueue)

    # 2. Offre terminée -> apprentissage des préférences (synchrone, léger)
    if not created and offer.status == "COMPLETED":
        try:
            UserPreferenceService.update_preferences_from_offer(offer.user, offer)
            if offer.accepted_by:
                UserPreferenceService.update_preferences_from_offer(offer.accepted_by, offer)
        except Exception as e:
            logger.error("preference_update_failure", offer_id=str(offer.id), error=str(e))


@receiver(post_save, sender=Dispute)
def handle_dispute_created(sender, instance, created, **kwargs):
    """Impacte la réputation des parties impliquées dans un litige."""
    if not created:
        return
    try:
        offer = instance.offer
        UserPreferenceService.register_dispute(offer.user)
        if offer.accepted_by:
            UserPreferenceService.register_dispute(offer.accepted_by)
    except Exception as e:
        logger.error("dispute_reputation_update_failure", dispute_id=str(instance.id), error=str(e))
