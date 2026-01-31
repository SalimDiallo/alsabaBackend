from django.db.models.signals import post_save
from django.dispatch import receiver
from Offer.models import Offer
from .services import MatchingEngine, UserPreferenceService
import structlog

logger = structlog.get_logger(__name__)

@receiver(post_save, sender=Offer)
def handle_offer_events(sender, instance, created, **kwargs):
    offer = instance
    
    if created and offer.status == 'OPEN':
        # 1. Nouvelle Offre -> Matching
        try:
            MatchingEngine.process_new_offer(offer)
        except Exception as e:
            logger.error("matching_engine_failure", offer_id=str(offer.id), error=str(e))

    if not created and offer.status == 'COMPLETED':
        # 2. Offre Terminée -> Apprentissage (User A et B)
        try:
            UserPreferenceService.update_preferences_from_offer(offer.user, offer)
            if offer.accepted_by:
                UserPreferenceService.update_preferences_from_offer(offer.accepted_by, offer)
        except Exception as e:
            logger.error("preference_update_failure", offer_id=str(offer.id), error=str(e))
