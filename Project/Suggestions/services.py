from django.db.models import F
from django.shortcuts import get_object_or_404
from .models import UserPreference
from .ml_engine import AdvancedMLEngine
from Offer.models import Offer
from Accounts.models import User
import structlog

logger = structlog.get_logger(__name__)

class UserPreferenceService:
    @staticmethod
    def update_preferences_from_offer(user, offer):
        """
        Met à jour le profil utilisateur après une transaction réussie (OFFER_COMPLETED).
        Apprend des habitudes : Que vend-il ? Qu'achète-t-il ? Combien ?
        """
        prefs, created = UserPreference.objects.get_or_create(user=user)
        
        # Logique d'apprentissage simple (Moyenne mobile pondérée)
        if user == offer.user:
            # Le vendeur (A1) a vendu currency_sell et acheté currency_buy
            prefs.preferred_currency_sell = offer.currency_sell
            prefs.preferred_currency_buy = offer.currency_buy
            new_amount = offer.amount_sell_cents
        else:
            # L'acheteur (A2) a acheté currency_sell et vendu currency_buy
            prefs.preferred_currency_sell = offer.currency_buy
            prefs.preferred_currency_buy = offer.currency_sell
            new_amount = offer.amount_buy_cents

        # 1. Mise à jour Montant Moyen
        if prefs.total_transactions_count == 0:
            prefs.avg_transaction_amount_cents = new_amount
        else:
            # Formule: (AncienneMoyenne * N + Nouveau) / (N + 1)
            total_history = prefs.avg_transaction_amount_cents * prefs.total_transactions_count
            prefs.avg_transaction_amount_cents = int((total_history + new_amount) / (prefs.total_transactions_count + 1))
        
        prefs.total_transactions_count += 1
        prefs.save()
        
        logger.info("preferences_updated", user_id=str(user.id), new_avg=prefs.avg_transaction_amount_cents)

class MatchingEngine:
    @staticmethod
    def process_new_offer(offer):
        """
        Algorithme HYBRIDE : Règles + Machine Learning (KNN).
        """
        # 1. Approche heuristique (Règles strictes)
        target_currency_buy = offer.currency_sell
        target_currency_sell = offer.currency_buy
        
        candidates = UserPreference.objects.filter(
            preferred_currency_buy=target_currency_buy,
            preferred_currency_sell=target_currency_sell
        ).exclude(user=offer.user)
        
        matches = {} # Dict {user_id: score}

        # Scoring par Règles
        for prefs in candidates:
            score = MatchingEngine._calculate_score(offer, prefs)
            matches[prefs.user.id] = score

        # 2. Approche ML (Voisinage Vectoriel)
        # Trouve des connexions non-évidentes (ex: montants très proches même si devise secondaire diffère)
        ml_results = AdvancedMLEngine.find_matching_users(offer)
        
        for user_id, ml_score in ml_results:
            if user_id == offer.user.id:
                continue
                
            # Fusion des scores
            if user_id in matches:
                # Si trouvé par les deux, on booste !
                matches[user_id] = max(matches[user_id], ml_score) + 10 
            else:
                # Si trouvé que par le ML (ex: règle devise trop stricte mais KNN a trouvé similitude)
                matches[user_id] = ml_score

        # 3. Création des notifs
        for user_id, final_score in matches.items():
            final_score = min(final_score, 100) # Cap à 100
            
            if final_score >= 60:
                user = User.objects.get(id=user_id)
                MatchingEngine._create_notification(user, offer, final_score)

    @staticmethod
    def _calculate_score(offer, prefs):
        """
        Calcule un score de 0 à 100.
        """
        score = 0
        
        # Critère 1: Devises (Déjà filtré par la query, donc c'est un match fort)
        score += 50 
        
        # Critère 2: Montant
        user_avg = prefs.avg_transaction_amount_cents
        offer_amt = offer.amount_sell_cents 
        
        if user_avg > 0:
            ratio = min(user_avg, offer_amt) / max(user_avg, offer_amt)
            if ratio > 0.8: # Proche à 20%
                score += 30
            elif ratio > 0.5:
                score += 15
        else:
            # Nouveau user, bénéfice du doute
            score += 10

        # Critère 3: Boost activité
        score += 20 

        return min(score, 100)

    @staticmethod
    def _create_notification(user, offer, score):
        from Notifications.services import NotificationService
        
        title = "🎯 Offre Recommandée !"
        amount = offer.amount_sell_cents / 100
        msg = f"Une offre de {amount} {offer.currency_sell} correspond à vos critères ({score}% match)."
        
        NotificationService.send(
            user=user,
            title=title,
            body=msg,
            notification_type='suggestion',
            data={
                'offer_id': str(offer.id),
                'score': score,
                'screen': 'offer_detail'
            },
            channels=['db', 'push'] # Suggestions are pushed
        )
        logger.info("suggestion_notification_sent", user_id=str(user.id), offer_id=str(offer.id), score=score)
