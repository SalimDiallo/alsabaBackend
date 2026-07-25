"""
Tests du parcours Escrow P2P (SecureEscrowService).

Scénario de référence :
    A1 (XOF) vend 500 XOF, veut 100 EUR
    A2 (EUR) accepte, désigne B1 (XOF) comme bénéficiaire
    A1 valide, désigne B2 (EUR) comme bénéficiaire
    confirm -> A1 débité 500 XOF / B1 crédité 500 XOF
               A2 débité 100 EUR / B2 crédité 100 EUR

Ces tests couvrent notamment les correctifs :
  - L1 : accept_offer / validate_offer (select_for_update dans une transaction)
  - L3 : review_dispute libère les EscrowLock sans créer de monnaie fantôme
"""
import pytest
from django.core.exceptions import ValidationError

from Offer.services import SecureEscrowService
from Offer.models import EscrowLock


# Montants exprimés en unités ; en cents = *100
SELL_XOF = 500
BUY_EUR = 100


def _prepare_locked_offer(make_user):
    """Crée 4 users + une offre menée jusqu'au statut LOCKED (locks posés)."""
    a1, w_a1 = make_user("SN", balance=1000)   # vendeur XOF
    b1, w_b1 = make_user("CI", balance=0)      # bénéficiaire XOF (reçoit currency_sell)
    a2, w_a2 = make_user("FR", balance=1000)   # acheteur EUR
    b2, w_b2 = make_user("DE", balance=0)      # bénéficiaire EUR (reçoit currency_buy)

    offer = SecureEscrowService.create_offer(
        user=a1,
        amount_sell=SELL_XOF, currency_sell="XOF",
        amount_buy=BUY_EUR, currency_buy="EUR",
        beneficiary_data={}, expiry_hours=24,
    )
    SecureEscrowService.accept_offer(
        user_accepter=a2, offer_id=offer.id,
        beneficiary_data={"phone": b1.full_phone_number},
    )
    SecureEscrowService.validate_offer(
        user_validator=a1, offer_id=offer.id,
        beneficiary_data={"phone": b2.full_phone_number},
    )
    offer.refresh_from_db()
    return {
        "offer": offer,
        "a1": (a1, w_a1), "b1": (b1, w_b1),
        "a2": (a2, w_a2), "b2": (b2, w_b2),
    }


@pytest.mark.django_db
def test_full_escrow_swap_moves_funds_correctly(make_user):
    """L1 + parcours nominal : accept/validate/confirm déplacent bien les fonds."""
    ctx = _prepare_locked_offer(make_user)
    offer = ctx["offer"]
    assert offer.status == "LOCKED"
    assert EscrowLock.objects.filter(offer=offer, status="LOCKED").count() == 2

    SecureEscrowService.confirm_transaction(offer.id)

    offer.refresh_from_db()
    assert offer.status == "COMPLETED"

    w_a1 = ctx["a1"][1]; w_b1 = ctx["b1"][1]
    w_a2 = ctx["a2"][1]; w_b2 = ctx["b2"][1]
    for w in (w_a1, w_b1, w_a2, w_b2):
        w.refresh_from_db()

    assert w_a1.balance_cents == (1000 - SELL_XOF) * 100   # 1000 - 500 XOF
    assert w_b1.balance_cents == SELL_XOF * 100            # +500 XOF
    assert w_a2.balance_cents == (1000 - BUY_EUR) * 100    # 1000 - 100 EUR
    assert w_b2.balance_cents == BUY_EUR * 100             # +100 EUR

    # Locks tous libérés
    assert not EscrowLock.objects.filter(offer=offer, status="LOCKED").exists()


@pytest.mark.django_db
def test_create_offer_requires_kyc(make_user):
    a1, _ = make_user("SN", balance=1000, kyc="unverified")
    with pytest.raises(ValidationError):
        SecureEscrowService.create_offer(
            user=a1, amount_sell=100, currency_sell="XOF",
            amount_buy=20, currency_buy="EUR",
        )


@pytest.mark.django_db
def test_create_offer_rejects_insufficient_available_balance(make_user):
    """Double-spend / solde insuffisant : impossible de créer au-delà du disponible."""
    a1, _ = make_user("SN", balance=100)  # 100 XOF seulement
    with pytest.raises(ValidationError):
        SecureEscrowService.create_offer(
            user=a1, amount_sell=200, currency_sell="XOF",  # > solde
            amount_buy=50, currency_buy="EUR",
        )


@pytest.mark.django_db
def test_cannot_accept_own_offer(make_user):
    a1, _ = make_user("SN", balance=1000)
    b1, _ = make_user("CI", balance=0)
    offer = SecureEscrowService.create_offer(
        user=a1, amount_sell=SELL_XOF, currency_sell="XOF",
        amount_buy=BUY_EUR, currency_buy="EUR",
    )
    with pytest.raises(ValidationError):
        SecureEscrowService.accept_offer(
            user_accepter=a1, offer_id=offer.id,
            beneficiary_data={"phone": b1.full_phone_number},
        )


@pytest.mark.django_db
def test_review_dispute_releases_locks_without_creating_money(make_user):
    """
    L3 (régression) : la résolution d'un litige doit libérer les EscrowLock
    (fonds virtuels rendus disponibles) SANS ajouter de solde fantôme.
    """
    ctx = _prepare_locked_offer(make_user)
    offer = ctx["offer"]
    admin, _ = make_user("IT", balance=0, is_staff=True)

    dispute = SecureEscrowService.initiate_dispute(
        offer_id=offer.id, user_initiator=ctx["a1"][0], reason="Non-réception",
    )
    SecureEscrowService.review_dispute(
        dispute_id=dispute.id, reviewer=admin, resolution="refund_a1",
        notes="Test",
    )

    offer.refresh_from_db()
    assert offer.status == "CANCELLED"

    # Aucun lock ne reste actif (sinon fonds bloqués à vie)
    assert not EscrowLock.objects.filter(offer=offer, status="LOCKED").exists()

    # Soldes INCHANGÉS : les locks étaient virtuels, aucune monnaie créée/détruite
    w_a1 = ctx["a1"][1]; w_b1 = ctx["b1"][1]
    w_a2 = ctx["a2"][1]; w_b2 = ctx["b2"][1]
    for w in (w_a1, w_b1, w_a2, w_b2):
        w.refresh_from_db()
    assert w_a1.balance_cents == 1000 * 100
    assert w_a2.balance_cents == 1000 * 100
    assert w_b1.balance_cents == 0
    assert w_b2.balance_cents == 0


@pytest.mark.django_db
def test_initiate_dispute_freezes_swap(make_user):
    """
    L5 : ouvrir un litige (modèle Dispute) doit geler l'offre (statut DISPUTE)
    et empêcher la confirmation du swap tant qu'il n'est pas résolu.
    """
    ctx = _prepare_locked_offer(make_user)
    offer = ctx["offer"]

    SecureEscrowService.initiate_dispute(
        offer_id=offer.id, user_initiator=ctx["a1"][0], reason="Litige",
    )

    offer.refresh_from_db()
    assert offer.status == "DISPUTE"

    # Le swap ne peut plus être confirmé pendant le litige
    with pytest.raises(ValidationError):
        SecureEscrowService.confirm_transaction(offer.id)


@pytest.mark.django_db
def test_non_admin_cannot_review_dispute(make_user):
    ctx = _prepare_locked_offer(make_user)
    offer = ctx["offer"]
    dispute = SecureEscrowService.initiate_dispute(
        offer_id=offer.id, user_initiator=ctx["a1"][0], reason="x",
    )
    with pytest.raises(ValidationError):
        SecureEscrowService.review_dispute(
            dispute_id=dispute.id, reviewer=ctx["a2"][0],  # non-staff
            resolution="refund_a1",
        )
