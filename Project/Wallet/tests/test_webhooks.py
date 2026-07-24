"""
Tests du traitement des webhooks Flutterwave (chemin critique : crédit des dépôts
et confirmation/annulation des retraits), avec un focus sur l'idempotence et
l'absence de double crédit / double débit.

Couvre :
  - dépôt réussi -> crédite le wallet une seule fois, stocke flutterwave_event_id
  - idempotence : même event_id livré 2x -> 1 seul crédit
  - webhook dupliqué (event_id différent, tx déjà complétée) -> pas de double crédit
  - dépôt échoué -> transaction 'failed', aucun crédit
  - retrait réussi -> pas de double débit (déjà débité à l'initiation)
  - retrait échoué -> remboursement du solde
  - double webhook d'échec de retrait -> remboursement une seule fois
  - vérification de signature (secret en clair, façon Flutterwave v3)
"""
import pytest

from Wallet.models import Transaction
from Wallet.Services.wallet_service import WalletService


# --- Helpers ------------------------------------------------------------------
def _deposit_tx(wallet, ref, amount=100, fee=0, status="pending"):
    return Transaction.objects.create(
        wallet=wallet,
        transaction_type="deposit",
        payment_method="card",
        currency=wallet.currency,
        amount_cents=int(amount * 100),
        fee_cents=int(fee * 100),
        status=status,
        flutterwave_reference=ref,
    )


def _withdrawal_tx(wallet, ref, amount=100, fee=0):
    # Un retrait est débité dès l'initiation -> balance_adjusted=True
    return Transaction.objects.create(
        wallet=wallet,
        transaction_type="withdrawal",
        payment_method="card",
        currency=wallet.currency,
        amount_cents=int(amount * 100),
        fee_cents=int(fee * 100),
        status="processing",
        flutterwave_reference=ref,
        balance_adjusted=True,
    )


def _charge_completed(tx_ref, status, event_id):
    return {
        "event": "charge.completed",
        "id": event_id,
        "data": {"tx_ref": tx_ref, "status": status, "id": "flw_charge_1"},
    }


def _transfer_completed(reference, status, event_id):
    return {
        "event": "transfer.completed",
        "id": event_id,
        "data": {"reference": reference, "status": status},
    }


# --- Dépôts -------------------------------------------------------------------
@pytest.mark.django_db
def test_deposit_webhook_credits_wallet_once(make_user):
    _, w = make_user("FR", balance=0)
    tx = _deposit_tx(w, "TXREF1", amount=100)

    res = WalletService.process_webhook(_charge_completed("TXREF1", "successful", "evt_1"))

    assert res["success"] is True
    w.refresh_from_db(); tx.refresh_from_db()
    assert w.balance_cents == 100 * 100
    assert tx.status == "completed"
    assert tx.balance_adjusted is True
    assert tx.flutterwave_event_id == "evt_1"


@pytest.mark.django_db
def test_deposit_webhook_idempotent_same_event_id(make_user):
    _, w = make_user("FR", balance=0)
    _deposit_tx(w, "TXREF2", amount=100)
    payload = _charge_completed("TXREF2", "successful", "evt_same")

    WalletService.process_webhook(payload)
    WalletService.process_webhook(payload)  # rejeu exact

    w.refresh_from_db()
    assert w.balance_cents == 100 * 100  # crédité une seule fois


@pytest.mark.django_db
def test_deposit_webhook_duplicate_new_event_id_no_double_credit(make_user):
    _, w = make_user("FR", balance=0)
    _deposit_tx(w, "TXREF3", amount=100)

    WalletService.process_webhook(_charge_completed("TXREF3", "successful", "evt_a"))
    # Même transaction, event_id différent : le garde balance_adjusted/mark_completed
    # doit empêcher un second crédit.
    WalletService.process_webhook(_charge_completed("TXREF3", "successful", "evt_b"))

    w.refresh_from_db()
    assert w.balance_cents == 100 * 100


@pytest.mark.django_db
def test_deposit_webhook_failed_status_no_credit(make_user):
    _, w = make_user("FR", balance=0)
    tx = _deposit_tx(w, "TXREF4", amount=100)

    WalletService.process_webhook(_charge_completed("TXREF4", "failed", "evt_fail"))

    w.refresh_from_db(); tx.refresh_from_db()
    assert w.balance_cents == 0
    assert tx.status == "failed"


# --- Retraits -----------------------------------------------------------------
@pytest.mark.django_db
def test_withdrawal_webhook_success_no_double_debit(make_user):
    # Solde déjà réduit à l'initiation (avait 150, débité 100 -> 50)
    _, w = make_user("FR", balance=50)
    tx = _withdrawal_tx(w, "WD1", amount=100)

    WalletService.process_webhook(_transfer_completed("WD1", "successful", "evt_w1"))

    w.refresh_from_db(); tx.refresh_from_db()
    assert w.balance_cents == 50 * 100  # inchangé : pas de double débit
    assert tx.status == "completed"


@pytest.mark.django_db
def test_withdrawal_webhook_failure_refunds_balance(make_user):
    _, w = make_user("FR", balance=50)  # avait 150, débité 100
    tx = _withdrawal_tx(w, "WD2", amount=100)

    WalletService.process_webhook(_transfer_completed("WD2", "failed", "evt_w2"))

    w.refresh_from_db(); tx.refresh_from_db()
    assert w.balance_cents == 150 * 100  # remboursé
    assert tx.status == "failed"
    assert tx.balance_adjusted is False


@pytest.mark.django_db
def test_withdrawal_double_failure_refunds_once(make_user):
    _, w = make_user("FR", balance=50)
    _withdrawal_tx(w, "WD3", amount=100)
    payload = _transfer_completed("WD3", "failed", "evt_w3")

    WalletService.process_webhook(payload)
    WalletService.process_webhook(payload)  # rejeu de l'échec

    w.refresh_from_db()
    assert w.balance_cents == 150 * 100  # remboursé UNE seule fois


# --- Signature ----------------------------------------------------------------
@pytest.mark.django_db
def test_webhook_signature_uses_plain_secret(settings):
    """Flutterwave v3 : le header 'verif-hash' est le secret en clair."""
    from Wallet.Services.flutterwave.base import FlutterwaveBaseService
    settings.FLUTTERWAVE_WEBHOOK_SECRET = "my_super_secret"
    svc = FlutterwaveBaseService()

    assert svc.verify_webhook_signature(b"{}", "my_super_secret") is True
    assert svc.verify_webhook_signature(b"{}", "mauvais_secret") is False
    assert svc.verify_webhook_signature(b"{}", "") is False
