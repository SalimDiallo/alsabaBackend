"""
Fixtures partagées pour la suite de tests pytest.

Lancement (depuis le dossier Project/, dans le conteneur web qui a accès à la DB) :
    docker exec alsaba_django pytest -v

Prérequis : pip install pytest pytest-django  (voir requirements-dev.txt)
"""
import pytest
import phonenumbers
from phonenumbers import PhoneNumberFormat


# --- Utilitaire : numéro E.164 VALIDE pour une région donnée -------------------
# On passe par example_number() pour garantir la validité (phonenumbers rejette
# les numéros invalides à la création de l'utilisateur). Chaque région donne un
# numéro distinct, ce qui évite les collisions d'unicité.
#
# Correspondance région -> devise (voir Wallet.models.get_currency_from_phone_number) :
#   SN, CI -> XOF   |   FR, DE, IT -> EUR
def e164_for_region(region: str) -> str:
    number = phonenumbers.example_number(region)
    return phonenumbers.format_number(number, PhoneNumberFormat.E164)


@pytest.fixture(autouse=True)
def _mute_notifications(monkeypatch):
    """
    Neutralise l'envoi de notifications (push/email/sms) pendant les tests :
    on veut tester la logique argent, pas les intégrations externes.
    """
    from Notifications.services import NotificationService
    monkeypatch.setattr(NotificationService, "send", lambda *args, **kwargs: None)
    yield


@pytest.fixture(autouse=True)
def _clear_cache():
    """
    Vide le cache Django avant/après chaque test : le rate-limiting et les
    sessions OTP y sont stockés, il ne faut pas de fuite d'état entre tests.
    """
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def make_user(db):
    """
    Fabrique un (User, Wallet) prêt à l'emploi.

    Args:
        region: code région ISO (ex: 'SN', 'FR') -> détermine la devise du wallet
        balance: solde initial en unités (ex: 1000 -> 1000.00), converti en cents
        kyc: statut KYC (par défaut 'verified' pour pouvoir créer/accepter des offres)
        is_staff: True pour un compte admin (résolution de litige)

    Returns:
        tuple(User, Wallet)
    """
    from Accounts.models import User
    from Wallet.models import Wallet

    def _make(region, balance=0, kyc="verified", is_staff=False):
        e164 = e164_for_region(region)
        user = User.objects.create_user(phone_number=e164)
        user.kyc_status = kyc
        user.phone_verified = True
        user.is_staff = is_staff
        user.save()

        # Le wallet est créé automatiquement par signal (devise déduite du numéro).
        wallet, _ = Wallet.objects.get_or_create(user=user)
        if balance:
            wallet.balance_cents = int(balance * 100)
            wallet.save(update_fields=["balance_cents"])
        return user, wallet

    return _make
