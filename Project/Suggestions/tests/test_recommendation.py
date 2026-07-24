"""
Tests du moteur de recommandation d'offres (RecommendationEngine, feed, matching,
apprentissage). On mocke les taux marché (ExchangeRateService) pour être déterministe.

Rappels métier :
- Le preneur verrouille currency_buy -> son wallet doit être en currency_buy (feasible).
- Corridor du preneur = "currency_buy>currency_sell" (réciproque de l'offre).
- Taux vu par le preneur = amount_sell / amount_buy (currency_sell par currency_buy).
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from Offer.models import Offer
from Suggestions.models import UserPreference
from Suggestions.recommendation_engine import RecommendationEngine
from Suggestions.services import UserPreferenceService, MatchingEngine


def make_offer(creator, sell="XOF", buy="EUR", amount_sell=500, amount_buy=100, ttl_h=24):
    return Offer.objects.create(
        user=creator,
        amount_sell_cents=int(amount_sell * 100), currency_sell=sell,
        amount_buy_cents=int(amount_buy * 100), currency_buy=buy,
        rate=Decimal(str(amount_buy)) / Decimal(str(amount_sell)),
        status="OPEN",
        expires_at=timezone.now() + timedelta(hours=ttl_h),
    )


def _mock_market_rate(monkeypatch, value):
    from Offer.exchange_service import ExchangeRateService
    monkeypatch.setattr(ExchangeRateService, "get_rate", staticmethod(lambda a, b: value))


@pytest.fixture
def api():
    return APIClient()


# --- Filtre dur : compatibilité devise ---------------------------------------
@pytest.mark.django_db
def test_currency_incompatible_is_infeasible(make_user):
    taker, _ = make_user("FR", balance=1000)      # wallet EUR
    creator, _ = make_user("SN", balance=0)
    # currency_buy = XOF -> un wallet EUR ne peut pas prendre cette offre
    offer = make_offer(creator, sell="EUR", buy="XOF", amount_sell=100, amount_buy=500)
    ctx = RecommendationEngine.build_user_context(taker)
    so = RecommendationEngine.score_offer(ctx, offer, market_rate=1.0)
    assert so.feasible is False
    assert so.score == 0


# --- Faisabilité financière ---------------------------------------------------
@pytest.mark.django_db
def test_insufficient_balance_flagged_unaffordable(make_user):
    poor, _ = make_user("FR", balance=50)          # 50 EUR dispo
    creator, _ = make_user("SN", balance=0)
    offer = make_offer(creator, sell="XOF", buy="EUR", amount_sell=500, amount_buy=100)  # exige 100 EUR
    ctx = RecommendationEngine.build_user_context(poor)
    so = RecommendationEngine.score_offer(ctx, offer, market_rate=5.0)
    assert so.feasible is True
    assert so.affordable is False


# --- Compétitivité du taux ----------------------------------------------------
@pytest.mark.django_db
def test_rate_competitiveness_prefers_above_market(make_user):
    taker, _ = make_user("FR", balance=1000)
    creator, _ = make_user("SN", balance=0)
    # taker_rate = amount_sell/amount_buy (XOF par EUR)
    good = make_offer(creator, sell="XOF", buy="EUR", amount_sell=700, amount_buy=1)  # 700 XOF/EUR
    bad = make_offer(creator, sell="XOF", buy="EUR", amount_sell=600, amount_buy=1)   # 600 XOF/EUR
    ctx = RecommendationEngine.build_user_context(taker)
    sg = RecommendationEngine.score_offer(ctx, good, market_rate=655.0)
    sb = RecommendationEngine.score_offer(ctx, bad, market_rate=655.0)
    assert sg.breakdown["rate_competitiveness"] > sb.breakdown["rate_competitiveness"]
    assert sg.score > sb.score


# --- Affinité corridor --------------------------------------------------------
@pytest.mark.django_db
def test_corridor_history_boosts_score(make_user):
    familiar, _ = make_user("FR", balance=1000)
    UserPreference.objects.create(
        user=familiar,
        corridor_stats={"EUR>XOF": {"count": 5, "volume_cents": 500000,
                                    "last_at": timezone.now().isoformat()}},
    )
    fresh, _ = make_user("DE", balance=1000)        # EUR aussi, sans historique
    creator, _ = make_user("SN", balance=0)
    offer = make_offer(creator, sell="XOF", buy="EUR", amount_sell=500, amount_buy=100)

    s_fam = RecommendationEngine.score_offer(
        RecommendationEngine.build_user_context(familiar), offer, market_rate=655.0)
    s_new = RecommendationEngine.score_offer(
        RecommendationEngine.build_user_context(fresh), offer, market_rate=655.0)

    assert s_fam.breakdown["corridor_affinity"] >= 0.5
    assert s_fam.breakdown["corridor_affinity"] > s_new.breakdown["corridor_affinity"]


# --- Apprentissage ------------------------------------------------------------
@pytest.mark.django_db
def test_learning_updates_corridor_stats(make_user):
    a1, _ = make_user("SN", balance=0)
    a2, _ = make_user("FR", balance=0)
    offer = make_offer(a1, sell="XOF", buy="EUR", amount_sell=500, amount_buy=100)
    offer.accepted_by = a2
    offer.save()

    UserPreferenceService.update_preferences_from_offer(a1, offer)
    UserPreferenceService.update_preferences_from_offer(a2, offer)

    p1 = UserPreference.objects.get(user=a1)
    p2 = UserPreference.objects.get(user=a2)
    assert "XOF>EUR" in p1.corridor_stats        # A1 vend XOF, achète EUR
    assert "EUR>XOF" in p2.corridor_stats         # A2 vend EUR, achète XOF
    assert p1.corridor_stats["XOF>EUR"]["count"] == 1
    assert p1.completed_offers_count == 1


# --- Feed temps réel ----------------------------------------------------------
@pytest.mark.django_db
def test_feed_returns_only_feasible_ranked_offers(api, make_user, monkeypatch):
    _mock_market_rate(monkeypatch, 655.0)
    taker, _ = make_user("FR", balance=1000)       # wallet EUR
    other, _ = make_user("SN", balance=0)

    feasible = make_offer(other, sell="XOF", buy="EUR", amount_sell=500, amount_buy=100)
    make_offer(other, sell="EUR", buy="XOF", amount_sell=100, amount_buy=500)  # currency_buy=XOF -> exclu
    make_offer(taker, sell="XOF", buy="EUR", amount_sell=300, amount_buy=60)   # la sienne -> exclue

    api.force_authenticate(taker)
    res = api.get("/api/suggestions/feed/")

    assert res.status_code == 200
    assert res.data["count"] == 1
    result = res.data["results"][0]
    assert result["id"] == str(feasible.id)
    assert "recommendation" in result
    assert 0 <= result["recommendation"]["score"] <= 100
    assert "breakdown" in result["recommendation"]


# --- Push matching ------------------------------------------------------------
@pytest.mark.django_db
def test_process_new_offer_notifies_relevant_taker(make_user, monkeypatch):
    _mock_market_rate(monkeypatch, 4.0)            # taker_rate=5.0 -> avantageux
    creator, _ = make_user("SN", balance=0)
    taker, _ = make_user("FR", balance=1000)       # EUR, peut prendre
    UserPreference.objects.create(
        user=taker,
        corridor_stats={"EUR>XOF": {"count": 5, "volume_cents": 500000,
                                    "last_at": timezone.now().isoformat()}},
        completed_offers_count=5,
    )
    offer = make_offer(creator, sell="XOF", buy="EUR", amount_sell=500, amount_buy=100)

    notified = MatchingEngine.process_new_offer(offer)
    assert notified >= 1


@pytest.mark.django_db
def test_process_new_offer_skips_incompatible_currency(make_user, monkeypatch):
    _mock_market_rate(monkeypatch, 4.0)
    creator, _ = make_user("SN", balance=0)
    # Un utilisateur XOF ne peut pas prendre une offre currency_buy=EUR
    make_user("CI", balance=1000)                  # wallet XOF
    offer = make_offer(creator, sell="XOF", buy="EUR", amount_sell=500, amount_buy=100)

    notified = MatchingEngine.process_new_offer(offer)
    assert notified == 0
