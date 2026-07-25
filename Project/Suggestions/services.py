from django.conf import settings
from django.utils import timezone
from .models import UserPreference
from .recommendation_engine import RecommendationEngine, DEFAULT_NOTIFY_THRESHOLD
import structlog

logger = structlog.get_logger(__name__)


class UserPreferenceService:
    @staticmethod
    def update_preferences_from_offer(user, offer):
        """
        Apprentissage après une transaction réussie (OFFER_COMPLETED).
        Met à jour le profil enrichi : corridor_stats (fréquence/volume par
        corridor), montant moyen, compteur de complétions.

        Corridor DU POINT DE VUE de l'utilisateur ("je vends X, j'achète Y") :
          - créateur A1 : vend currency_sell, achète currency_buy
          - preneur  A2 : vend currency_buy, achète currency_sell
        """
        prefs, _ = UserPreference.objects.get_or_create(user=user)

        if user == offer.user:
            sell, buy = offer.currency_sell, offer.currency_buy
            new_amount = offer.amount_sell_cents
        else:
            sell, buy = offer.currency_buy, offer.currency_sell
            new_amount = offer.amount_buy_cents

        # 1. Devises dominantes (rétro-compat / KNN)
        prefs.preferred_currency_sell = sell
        prefs.preferred_currency_buy = buy

        # 2. Statistiques de corridor (multi-corridors)
        stats = dict(prefs.corridor_stats or {})
        key = f"{sell}>{buy}"
        entry = stats.get(key, {"count": 0, "volume_cents": 0, "last_at": None})
        entry["count"] = entry.get("count", 0) + 1
        entry["volume_cents"] = entry.get("volume_cents", 0) + new_amount
        entry["last_at"] = timezone.now().isoformat()
        stats[key] = entry
        prefs.corridor_stats = stats

        # 3. Montant moyen (moyenne mobile)
        if prefs.total_transactions_count == 0:
            prefs.avg_transaction_amount_cents = new_amount
        else:
            total_history = prefs.avg_transaction_amount_cents * prefs.total_transactions_count
            prefs.avg_transaction_amount_cents = int(
                (total_history + new_amount) / (prefs.total_transactions_count + 1)
            )

        # 4. Compteurs
        prefs.total_transactions_count += 1
        prefs.completed_offers_count += 1
        prefs.save()

        logger.info(
            "preferences_updated",
            user_id=str(user.id), corridor=key,
            corridor_count=entry["count"], new_avg=prefs.avg_transaction_amount_cents,
        )

    @staticmethod
    def register_dispute(user):
        """Incrémente le compteur de litiges (impacte la réputation)."""
        prefs, _ = UserPreference.objects.get_or_create(user=user)
        prefs.disputes_count += 1
        prefs.save(update_fields=["disputes_count"])


class MatchingEngine:
    """
    Push-matching : à la création d'une offre, notifie les preneurs pertinents.
    Utilise le MÊME moteur de scoring que le flux "Pour Vous".
    """

    @staticmethod
    def process_new_offer(offer):
        from Wallet.models import Wallet
        from Offer.exchange_service import ExchangeRateService

        # Preneurs potentiels : wallet en currency_buy (ils peuvent verrouiller),
        # actifs, hors créateur. Filtre de faisabilité DUR côté requête.
        candidate_wallets = list(
            Wallet.objects.filter(currency=offer.currency_buy, is_active=True)
            .exclude(user=offer.user)
            .select_related("user")[: getattr(settings, "RECOMMENDATION_MAX_CANDIDATES", 1000)]
        )
        if not candidate_wallets:
            return 0

        contexts = RecommendationEngine.build_contexts_for_wallets(candidate_wallets)
        market_rate = ExchangeRateService.get_rate(offer.currency_buy, offer.currency_sell)
        creator_pref = UserPreference.objects.filter(user=offer.user).first()
        threshold = getattr(settings, "RECOMMENDATION_NOTIFY_THRESHOLD", DEFAULT_NOTIFY_THRESHOLD)

        notified = 0
        for wallet in candidate_wallets:
            ctx = contexts[wallet.user_id]
            scored = RecommendationEngine.score_offer(
                ctx, offer, market_rate=market_rate, creator_pref=creator_pref
            )
            # On ne notifie que des preneurs qui peuvent RÉELLEMENT accepter (affordable).
            if scored.feasible and scored.affordable and scored.score >= threshold:
                MatchingEngine._create_notification(wallet.user, offer, scored)
                notified += 1

        logger.info("matching_completed", offer_id=str(offer.id),
                    candidates=len(candidate_wallets), notified=notified)
        return notified

    @staticmethod
    def _create_notification(user, offer, scored):
        from Notifications.services import NotificationService

        amount = offer.amount_sell_cents / 100
        title = "🎯 Offre recommandée"
        msg = (f"Une offre de {amount:g} {offer.currency_sell} correspond à votre profil "
               f"({scored.score}% de match).")

        NotificationService.send(
            user=user,
            title=title,
            body=msg,
            notification_type="suggestion",
            data={
                "offer_id": str(offer.id),
                "score": scored.score,
                "breakdown": {k: round(v, 3) for k, v in scored.breakdown.items()},
                "reasons": scored.reasons,
                "screen": "offer_detail",
            },
            channels=["db", "push"],
        )
        logger.info("suggestion_notification_sent",
                    user_id=str(user.id), offer_id=str(offer.id), score=scored.score)
