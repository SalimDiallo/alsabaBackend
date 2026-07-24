"""
Tests de l'authentification par téléphone / OTP (PhoneAuthView, VerifyOTPView,
ResendOTPView). Le service externe Didit est mocké : on teste la logique de la
plateforme (sessions, rate-limiting, création d'utilisateur, blocage des numéros
frauduleux, émission des tokens JWT).
"""
import phonenumbers
from phonenumbers import PhoneNumberFormat
import pytest
from rest_framework.test import APIClient

from Accounts.models import User
from Accounts.Services.OTP_services import didit_service


PHONE_URL = "/api/accounts/auth/phone/"
VERIFY_URL = "/api/accounts/auth/verify/"
RESEND_URL = "/api/accounts/auth/resend/"


def _valid_e164(region="FR"):
    return phonenumbers.format_number(
        phonenumbers.example_number(region), PhoneNumberFormat.E164
    )


# --- Faux comportements Didit -------------------------------------------------
def _send_ok(*args, **kwargs):
    return {"success": True, "request_id": "req_123", "status": "Success", "message": "sent"}


def _send_fail(*args, **kwargs):
    return {"success": False, "reason": "Blocked", "message": "Numéro bloqué"}


def _verify_ok(*args, **kwargs):
    return {
        "success": True, "verified": True, "status": "Approved", "message": "ok",
        "phone_details": {
            "status": "Approved", "carrier": "Orange",
            "is_disposable": False, "is_virtual": False,
            "country_code": "FR", "verification_method": "sms",
        },
    }


def _verify_bad_code(*args, **kwargs):
    return {"success": True, "verified": False, "status": "Declined",
            "message": "bad", "phone_details": {}}


def _verify_disposable(*args, **kwargs):
    return {
        "success": True, "verified": True, "status": "Approved",
        "phone_details": {"is_disposable": True, "is_virtual": False},
    }


@pytest.fixture
def api():
    return APIClient()


# --- PhoneAuthView ------------------------------------------------------------
@pytest.mark.django_db
def test_phone_auth_new_number_returns_register_session(api, monkeypatch):
    monkeypatch.setattr(didit_service, "send_verification_code", _send_ok)
    phone = _valid_e164("FR")

    res = api.post(PHONE_URL, {"phone_number": phone}, format="json")

    assert res.status_code == 200
    assert res.data["action"] == "register"
    assert res.data["session_key"]
    assert res.data["user_exists"] is False


@pytest.mark.django_db
def test_phone_auth_existing_user_returns_login(api, monkeypatch):
    monkeypatch.setattr(didit_service, "send_verification_code", _send_ok)
    phone = _valid_e164("FR")
    User.objects.create_user(phone_number=phone)

    res = api.post(PHONE_URL, {"phone_number": phone}, format="json")

    assert res.status_code == 200
    assert res.data["action"] == "login"
    assert res.data["user_exists"] is True


@pytest.mark.django_db
def test_phone_auth_rate_limited_after_three_requests(api, monkeypatch):
    monkeypatch.setattr(didit_service, "send_verification_code", _send_ok)
    phone = _valid_e164("FR")

    for _ in range(3):
        ok = api.post(PHONE_URL, {"phone_number": phone}, format="json")
        assert ok.status_code == 200

    limited = api.post(PHONE_URL, {"phone_number": phone}, format="json")
    assert limited.status_code == 429
    assert limited.data["code"] == "rate_limited"


@pytest.mark.django_db
def test_phone_auth_inactive_account_forbidden(api, monkeypatch):
    """L9 : un compte désactivé (is_active=False) est bloqué (403), pas traité comme neuf."""
    monkeypatch.setattr(didit_service, "send_verification_code", _send_ok)
    phone = _valid_e164("FR")
    user = User.objects.create_user(phone_number=phone)
    user.is_active = False
    user.save()

    res = api.post(PHONE_URL, {"phone_number": phone}, format="json")

    assert res.status_code == 403
    assert res.data["code"] == "account_disabled"


@pytest.mark.django_db
def test_phone_auth_didit_failure_returns_400(api, monkeypatch):
    monkeypatch.setattr(didit_service, "send_verification_code", _send_fail)
    phone = _valid_e164("FR")

    res = api.post(PHONE_URL, {"phone_number": phone}, format="json")

    assert res.status_code == 400


@pytest.mark.django_db
def test_phone_auth_invalid_number_returns_400(api, monkeypatch):
    monkeypatch.setattr(didit_service, "send_verification_code", _send_ok)
    res = api.post(PHONE_URL, {"phone_number": "+33000"}, format="json")
    assert res.status_code == 400


# --- VerifyOTPView ------------------------------------------------------------
def _start_session(api, phone):
    """Appelle l'endpoint phone pour obtenir un session_key réel."""
    res = api.post(PHONE_URL, {"phone_number": phone}, format="json")
    return res.data["session_key"]


@pytest.mark.django_db
def test_verify_register_creates_user_and_returns_tokens(api, monkeypatch):
    monkeypatch.setattr(didit_service, "send_verification_code", _send_ok)
    monkeypatch.setattr(didit_service, "verify_code", _verify_ok)
    phone = _valid_e164("FR")
    session_key = _start_session(api, phone)

    assert not User.objects.filter(full_phone_number=phone).exists()

    res = api.post(VERIFY_URL, {
        "phone_number": phone, "code": "123456", "session_key": session_key,
    }, format="json")

    assert res.status_code == 200
    assert res.data["auth"]["access_token"]
    assert res.data["auth"]["refresh_token"]
    user = User.objects.get(full_phone_number=phone)
    assert user.phone_verified is True


@pytest.mark.django_db
def test_verify_invalid_code_returns_400(api, monkeypatch):
    monkeypatch.setattr(didit_service, "send_verification_code", _send_ok)
    monkeypatch.setattr(didit_service, "verify_code", _verify_bad_code)
    phone = _valid_e164("FR")
    session_key = _start_session(api, phone)

    res = api.post(VERIFY_URL, {
        "phone_number": phone, "code": "000000", "session_key": session_key,
    }, format="json")

    assert res.status_code == 400
    assert res.data["code"] == "invalid_otp"


@pytest.mark.django_db
def test_verify_blocks_disposable_number(api, monkeypatch):
    monkeypatch.setattr(didit_service, "send_verification_code", _send_ok)
    monkeypatch.setattr(didit_service, "verify_code", _verify_disposable)
    phone = _valid_e164("FR")
    session_key = _start_session(api, phone)

    res = api.post(VERIFY_URL, {
        "phone_number": phone, "code": "123456", "session_key": session_key,
    }, format="json")

    assert res.status_code == 403
    assert res.data["code"] == "fraudulent_phone"
    # L'utilisateur ne doit PAS avoir été créé
    assert not User.objects.filter(full_phone_number=phone).exists()


@pytest.mark.django_db
def test_verify_session_phone_mismatch(api, monkeypatch):
    monkeypatch.setattr(didit_service, "send_verification_code", _send_ok)
    monkeypatch.setattr(didit_service, "verify_code", _verify_ok)
    phone = _valid_e164("FR")
    other = _valid_e164("DE")
    session_key = _start_session(api, phone)

    # On tente de vérifier avec un autre numéro que celui de la session
    res = api.post(VERIFY_URL, {
        "phone_number": other, "code": "123456", "session_key": session_key,
    }, format="json")

    assert res.status_code == 400


# --- ResendOTPView ------------------------------------------------------------
@pytest.mark.django_db
def test_resend_sends_new_code(api, monkeypatch):
    monkeypatch.setattr(didit_service, "send_verification_code", _send_ok)
    phone = _valid_e164("FR")
    session_key = _start_session(api, phone)

    res = api.post(RESEND_URL, {"session_key": session_key}, format="json")

    assert res.status_code == 200
    assert res.data["success"] is True
    assert res.data["request_id"]


@pytest.mark.django_db
def test_resend_invalid_session_returns_400(api, monkeypatch):
    monkeypatch.setattr(didit_service, "send_verification_code", _send_ok)
    res = api.post(RESEND_URL, {"session_key": "does_not_exist"}, format="json")
    assert res.status_code == 400
