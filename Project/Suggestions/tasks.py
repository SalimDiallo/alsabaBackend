from celery import shared_task
import structlog

logger = structlog.get_logger(__name__)


@shared_task(name="Suggestions.match_new_offer")
def match_new_offer_task(offer_id):
    """
    Push-matching asynchrone : notifie les preneurs pertinents pour une offre.
    Exécuté hors du cycle requête (ne bloque pas la création d'offre en prod).
    """
    from Offer.models import Offer
    from .services import MatchingEngine

    try:
        offer = Offer.objects.select_related("user").get(id=offer_id)
    except Offer.DoesNotExist:
        logger.warning("match_task_offer_not_found", offer_id=str(offer_id))
        return 0

    if offer.status != "OPEN":
        return 0

    try:
        return MatchingEngine.process_new_offer(offer)
    except Exception as e:
        logger.error("match_task_failed", offer_id=str(offer_id), error=str(e))
        return 0
