"""
Tests du solde wallet — notamment L6 : available_balance exclut les fonds
bloqués en escrow (le solde brut ne doit pas induire l'utilisateur en erreur).
"""
import pytest

from Offer.services import SecureEscrowService
from Wallet.Serializers.wallet_serializers import WalletSerializer


@pytest.mark.django_db
def test_available_balance_excludes_locked_funds(make_user):
    a1, w_a1 = make_user("SN", balance=1000)   # XOF
    b1, _ = make_user("CI", balance=0)
    a2, _ = make_user("FR", balance=1000)      # EUR

    offer = SecureEscrowService.create_offer(
        user=a1,
        amount_sell=500, currency_sell="XOF",
        amount_buy=100, currency_buy="EUR",
    )
    # accept_offer verrouille 500 XOF chez A1
    SecureEscrowService.accept_offer(
        user_accepter=a2, offer_id=offer.id,
        beneficiary_data={"phone": b1.full_phone_number},
    )

    w_a1.refresh_from_db()
    data = WalletSerializer(w_a1).data

    assert data["balance"] == 1000.0            # solde total inchangé
    assert data["locked_balance"] == 500.0      # 500 XOF bloqués
    assert data["available_balance"] == 500.0   # seulement 500 réellement disponibles


@pytest.mark.django_db
def test_available_equals_balance_when_no_lock(make_user):
    _, wallet = make_user("FR", balance=250)
    data = WalletSerializer(wallet).data
    assert data["balance"] == 250.0
    assert data["locked_balance"] == 0.0
    assert data["available_balance"] == 250.0


@pytest.mark.django_db
def test_subtract_balance_insufficient_raises_validation_error(make_user):
    """L4 : un débit supérieur au solde lève ValidationError (pas d'IntegrityError)."""
    from django.core.exceptions import ValidationError
    _, wallet = make_user("FR", balance=10)
    with pytest.raises(ValidationError):
        wallet.subtract_balance(20)
    wallet.refresh_from_db()
    assert wallet.balance_cents == 10 * 100  # solde intact


@pytest.mark.django_db
def test_subtract_balance_exact_amount_succeeds(make_user):
    _, wallet = make_user("FR", balance=10)
    wallet.subtract_balance(10)
    wallet.refresh_from_db()
    assert wallet.balance_cents == 0
