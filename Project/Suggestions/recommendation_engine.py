"""
Moteur de recommandation d'offres P2P — scoring explicable et configurable.

Principe
--------
Pour un utilisateur (le *preneur* potentiel) et une offre, on calcule un score
[0..100] à partir de sous-scores normalisés [0..1] pondérés, PLUS un facteur de
faisabilité. Chaque score est accompagné de "raisons" lisibles (explicabilité).

Contexte métier (modèle escrow, wallet mono-devise)
---------------------------------------------------
- Pour *accepter* une offre, le preneur verrouille `amount_buy` en `currency_buy`.
  Il doit donc détenir un wallet en `currency_buy` (compatibilité devise = filtre
  DUR) et disposer d'un solde suffisant (faisabilité).
- Le corridor du preneur est le réciproque de l'offre : il vend `currency_buy`
  et achète `currency_sell`, soit la clé "currency_buy>currency_sell".
- Taux vu par le preneur : il donne `amount_buy` (currency_buy) pour faire
  livrer `amount_sell` (currency_sell) -> taux = amount_sell / amount_buy
  (unités de currency_sell par unité de currency_buy). Plus c'est élevé vs le
  marché, meilleure est l'affaire.

Sous-scores
-----------
- corridor_affinity   : fréquence/volume historiques du preneur sur ce corridor
- rate_competitiveness: avantage du taux de l'offre vs marché (côté preneur)
- amount_fit          : proximité du montant vs habitude du preneur
- reputation          : KYC + historique de complétion - litiges du créateur
- freshness           : récence de l'offre et distance à l'expiration

Facteurs (multiplicateurs, hors somme pondérée)
- currency_compatible : 0/1 (filtre dur)
- affordability       : 1.0 si solde suffisant, sinon pénalité
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

import structlog

logger = structlog.get_logger(__name__)


# Poids par défaut (surchargeable via settings.RECOMMENDATION_WEIGHTS)
DEFAULT_WEIGHTS = {
    "corridor_affinity": 0.30,
    "rate_competitiveness": 0.30,
    "amount_fit": 0.15,
    "reputation": 0.15,
    "freshness": 0.10,
}

# Pénalité appliquée quand le preneur a la bonne devise mais un solde insuffisant.
UNAFFORDABLE_FACTOR = 0.35

# Score en dessous duquel on ne notifie pas (push).
DEFAULT_NOTIFY_THRESHOLD = 62


def _weights() -> Dict[str, float]:
    w = dict(DEFAULT_WEIGHTS)
    w.update(getattr(settings, "RECOMMENDATION_WEIGHTS", {}) or {})
    return w


@dataclass
class ScoredOffer:
    offer: object
    score: int                      # 0..100
    breakdown: Dict[str, float]     # sous-scores [0..1]
    reasons: List[str] = field(default_factory=list)
    feasible: bool = True           # devise compatible
    affordable: bool = True         # solde suffisant

    def to_dict(self):
        return {
            "score": self.score,
            "feasible": self.feasible,
            "affordable": self.affordable,
            "breakdown": {k: round(v, 3) for k, v in self.breakdown.items()},
            "reasons": self.reasons,
        }


@dataclass
class UserContext:
    """Contexte du preneur, calculé une seule fois pour classer plusieurs offres."""
    user: object
    wallet_currency: Optional[str]
    available_cents: int
    preference: object  # UserPreference | None

    @property
    def avg_amount_cents(self) -> int:
        return getattr(self.preference, "avg_transaction_amount_cents", 0) or 0


class RecommendationEngine:
    # ---------------------------------------------------------------- Contexte
    @staticmethod
    def build_user_context(user) -> UserContext:
        from Wallet.models import Wallet
        from Offer.models import EscrowLock
        from .models import UserPreference

        wallet = Wallet.objects.filter(user=user).first()
        wallet_currency = wallet.currency if wallet else None

        available = 0
        if wallet:
            locked = EscrowLock.objects.filter(user=user, status="LOCKED").aggregate(
                s=Sum("amount_cents")
            )["s"] or 0
            available = max(0, wallet.balance_cents - locked)

        pref = UserPreference.objects.filter(user=user).first()
        return UserContext(user=user, wallet_currency=wallet_currency,
                           available_cents=available, preference=pref)

    @staticmethod
    def build_contexts_for_wallets(wallets) -> Dict[object, "UserContext"]:
        """
        Construit les contextes de plusieurs preneurs potentiels en 2 requêtes
        (locks + préférences), pour le matching push performant.
        `wallets` : itérable de Wallet avec .user chargé (select_related).
        Retourne { user_id: UserContext }.
        """
        from Offer.models import EscrowLock
        from .models import UserPreference

        wallets = list(wallets)
        user_ids = [w.user_id for w in wallets]

        locks = {
            row["user_id"]: row["s"]
            for row in EscrowLock.objects.filter(user_id__in=user_ids, status="LOCKED")
            .values("user_id").annotate(s=Sum("amount_cents"))
        }
        prefs = {p.user_id: p for p in UserPreference.objects.filter(user_id__in=user_ids)}

        contexts = {}
        for w in wallets:
            available = max(0, w.balance_cents - (locks.get(w.user_id) or 0))
            contexts[w.user_id] = UserContext(
                user=w.user, wallet_currency=w.currency,
                available_cents=available, preference=prefs.get(w.user_id),
            )
        return contexts

    # ------------------------------------------------------------------ Scoring
    @staticmethod
    def score_offer(ctx: UserContext, offer, *, market_rate: Optional[float] = None,
                    creator_pref=None) -> ScoredOffer:
        """
        Note une offre pour le preneur `ctx`. `market_rate` et `creator_pref`
        peuvent être fournis (cache) pour éviter des requêtes répétées.
        """
        reasons: List[str] = []
        w = _weights()

        # --- Filtre DUR : compatibilité devise ---
        # Le preneur verrouille currency_buy -> son wallet doit être en currency_buy.
        feasible = bool(ctx.wallet_currency) and ctx.wallet_currency == offer.currency_buy
        if not feasible:
            return ScoredOffer(
                offer=offer, score=0, breakdown={}, feasible=False, affordable=False,
                reasons=[f"Nécessite un wallet en {offer.currency_buy}"],
            )

        # --- Faisabilité : solde suffisant pour verrouiller amount_buy ---
        affordable = ctx.available_cents >= offer.amount_buy_cents
        if affordable:
            reasons.append("Solde suffisant pour accepter")
        else:
            reasons.append("Solde insuffisant — approvisionnez votre wallet")

        # --- Sous-scores [0..1] ---
        s_corridor = RecommendationEngine._score_corridor(ctx, offer, reasons)
        s_rate = RecommendationEngine._score_rate(offer, market_rate, reasons)
        s_amount = RecommendationEngine._score_amount(ctx, offer, reasons)
        s_reputation = RecommendationEngine._score_reputation(offer, creator_pref, reasons)
        s_fresh = RecommendationEngine._score_freshness(offer, reasons)

        breakdown = {
            "corridor_affinity": s_corridor,
            "rate_competitiveness": s_rate,
            "amount_fit": s_amount,
            "reputation": s_reputation,
            "freshness": s_fresh,
        }

        weighted = sum(breakdown[k] * w.get(k, 0) for k in breakdown)
        total_w = sum(w.get(k, 0) for k in breakdown) or 1.0
        base = weighted / total_w  # [0..1]

        # Facteur de faisabilité financière
        factor = 1.0 if affordable else UNAFFORDABLE_FACTOR
        score = int(round(base * factor * 100))
        score = max(0, min(100, score))

        return ScoredOffer(
            offer=offer, score=score, breakdown=breakdown, reasons=reasons,
            feasible=True, affordable=affordable,
        )

    # ------------------------------------------------------- Sous-scores privés
    @staticmethod
    def _score_corridor(ctx: UserContext, offer, reasons) -> float:
        """Affinité au corridor réciproque (le preneur vend currency_buy, achète currency_sell)."""
        if not ctx.preference:
            return 0.35  # cold start : neutre-bas
        count, volume, _ = ctx.preference.corridor_affinity(offer.currency_buy, offer.currency_sell)
        if count <= 0:
            # Corridor jamais tradé : petit crédit si l'utilisateur a de l'historique ailleurs
            return 0.30
        # Saturation logarithmique : 1 trade -> ~0.5, 5 -> ~0.8, 10+ -> ~1.0
        affinity = min(1.0, math.log1p(count) / math.log1p(10))
        reasons.append(f"Corridor habituel {offer.currency_buy}→{offer.currency_sell} ({count} échanges)")
        return round(0.5 + 0.5 * affinity, 4)  # plancher 0.5 dès qu'il y a de l'historique

    @staticmethod
    def _score_rate(offer, market_rate: Optional[float], reasons) -> float:
        """
        Compétitivité du taux côté preneur.
        taker_rate = amount_sell / amount_buy (currency_sell par currency_buy).
        market_rate = ExchangeRateService.get_rate(currency_buy, currency_sell).
        """
        if not offer.amount_buy_cents:
            return 0.5
        taker_rate = offer.amount_sell_cents / offer.amount_buy_cents
        if not market_rate or market_rate <= 0:
            return 0.5  # marché indisponible -> neutre
        advantage = taker_rate / market_rate  # >1 : meilleur que le marché
        # Mapping sigmoïde centré sur 1.0 (marché), pente douce.
        score = 1.0 / (1.0 + math.exp(-8.0 * (advantage - 1.0)))
        if advantage >= 1.02:
            reasons.append(f"Taux avantageux (+{round((advantage - 1) * 100, 1)}% vs marché)")
        elif advantage <= 0.98:
            reasons.append(f"Taux sous le marché ({round((advantage - 1) * 100, 1)}%)")
        return round(score, 4)

    @staticmethod
    def _score_amount(ctx: UserContext, offer, reasons) -> float:
        """Proximité entre le montant à engager (amount_buy) et l'habitude du preneur."""
        avg = ctx.avg_amount_cents
        target = offer.amount_buy_cents
        if avg <= 0:
            return 0.5  # pas d'habitude connue
        ratio = min(avg, target) / max(avg, target)
        if ratio > 0.8:
            reasons.append("Montant proche de vos habitudes")
        return round(ratio, 4)

    @staticmethod
    def _score_reputation(offer, creator_pref, reasons) -> float:
        """Réputation du créateur : KYC vérifié + complétions - litiges."""
        score = 0.0
        creator = offer.user
        if getattr(creator, "kyc_status", None) == "verified":
            score += 0.5
            reasons.append("Contrepartie vérifiée (KYC)")
        else:
            reasons.append("Contrepartie non vérifiée")

        completed = getattr(creator_pref, "completed_offers_count", 0) or 0
        disputes = getattr(creator_pref, "disputes_count", 0) or 0
        # Complétions -> jusqu'à +0.5 (saturation à ~10)
        score += 0.5 * min(1.0, math.log1p(completed) / math.log1p(10))
        # Litiges -> pénalité douce
        score -= 0.15 * min(1.0, disputes / 3.0)
        if completed >= 3:
            reasons.append(f"{completed} échanges réussis")
        return round(max(0.0, min(1.0, score)), 4)

    @staticmethod
    def _score_freshness(offer, reasons) -> float:
        """Récence de création + distance à l'expiration (décroissance douce)."""
        now = timezone.now()
        # Récence : demi-vie ~12h
        age_h = max(0.0, (now - offer.created_at).total_seconds() / 3600.0)
        recency = math.exp(-age_h / 12.0)
        # Distance à l'expiration : pénalise si proche de l'expiration (<2h)
        ttl_h = max(0.0, (offer.expires_at - now).total_seconds() / 3600.0)
        expiry_factor = min(1.0, ttl_h / 2.0)
        score = 0.6 * recency + 0.4 * expiry_factor
        if age_h < 2:
            reasons.append("Offre récente")
        return round(max(0.0, min(1.0, score)), 4)

    # -------------------------------------------------------------- Classement
    @staticmethod
    def rank_offers_for_user(user, offers, limit: int = 20,
                             include_unaffordable: bool = True) -> List[ScoredOffer]:
        """
        Classe une liste d'offres pour un utilisateur (flux "Pour Vous").
        Précalcule le contexte, met en cache les taux marché et les profils créateurs.
        """
        from Offer.exchange_service import ExchangeRateService
        from .models import UserPreference

        ctx = RecommendationEngine.build_user_context(user)
        if not ctx.wallet_currency:
            return []

        offers = list(offers)

        # Cache des profils créateurs (réputation) en une requête
        creator_ids = {o.user_id for o in offers}
        prefs_by_user = {
            p.user_id: p for p in UserPreference.objects.filter(user_id__in=creator_ids)
        }

        # Cache des taux marché par paire (buy -> sell)
        rate_cache: Dict[tuple, Optional[float]] = {}

        scored: List[ScoredOffer] = []
        for offer in offers:
            pair = (offer.currency_buy, offer.currency_sell)
            if pair not in rate_cache:
                rate_cache[pair] = ExchangeRateService.get_rate(offer.currency_buy, offer.currency_sell)
            so = RecommendationEngine.score_offer(
                ctx, offer,
                market_rate=rate_cache[pair],
                creator_pref=prefs_by_user.get(offer.user_id),
            )
            if not so.feasible:
                continue
            if not include_unaffordable and not so.affordable:
                continue
            scored.append(so)

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:limit]
