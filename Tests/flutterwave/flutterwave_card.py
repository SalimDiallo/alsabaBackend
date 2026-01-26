import requests
import json
import uuid
import base64
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from config import BASE_URL_SANDBOX, AUTH_URL, CLIENT_ID, CLIENT_SECRET, ENCRYPTION_KEY, CURRENCY, REDIRECT_URL
# ==================== CONFIG ====================
CONFIG = {
    "CLIENT_ID": CLIENT_ID,
    "CLIENT_SECRET": CLIENT_SECRET,
    "ENCRYPTION_KEY": ENCRYPTION_KEY,  # Base64
    "BASE_URL": BASE_URL_SANDBOX,
    "AUTH_URL": AUTH_URL,
    "CURRENCY": CURRENCY,  # ou "NGN" pour tests doc
    "REDIRECT_URL": REDIRECT_URL,  # Pour 3DS
}

# ==================== MODULE 0: Access Token ====================
def get_access_token():
    payload = {
        "client_id": CONFIG["CLIENT_ID"],
        "client_secret": CONFIG["CLIENT_SECRET"],
        "grant_type": "client_credentials"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(CONFIG["AUTH_URL"], data=payload, headers=headers)
    if resp.status_code == 200:
        return resp.json()["access_token"]
    raise Exception(f"Token error: {resp.text}")

# ==================== MODULE 1: Encryption AES-256-GCM ====================
def encrypt_aes(plaintext: str, encryption_key: str, nonce: bytes = None) -> tuple[str, str]:
    """Retourne (encrypted_base64, nonce_base64) - nonce 12 bytes obligatoire"""
    if nonce is None:
        nonce = get_random_bytes(12)
    if len(nonce) != 12:
        raise ValueError("Nonce must be exactly 12 bytes")
    
    key_bytes = base64.b64decode(encryption_key)
    cipher = AES.new(key_bytes, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode('utf-8'))
    full_enc = ciphertext + tag
    return base64.b64encode(full_enc).decode('utf-8'), base64.b64encode(nonce).decode('utf-8')

# ==================== MODULE 2: Create Customer ====================
def create_customer(token: str, email: str, first_name: str, last_name: str, phone: str, country_code: str = "212"):
    url = f"{CONFIG['BASE_URL']}/customers"
    trace_id = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Trace-Id": trace_id
    }
    payload = {
        "address": {
            "city": "Casablanca",
            "country": "MA",
            "line1": "Rue Mohammed V",
            "postal_code": "20250",
            "state": "Casablanca-Settat"
        },
        "name": {"first": first_name, "last": last_name},
        "phone": {"country_code": country_code, "number": phone},
        "email": email
    }
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code in (200, 201):
        return resp.json()["data"]["id"]
    raise Exception(f"Customer error: {resp.text}")

# ==================== MODULE 3: Create Payment Method (Card) ====================
def create_card_payment_method(token: str, card_number: str, exp_month: str, exp_year: str, cvv: str):
    url = f"{CONFIG['BASE_URL']}/payment-methods"
    trace_id = str(uuid.uuid4())
    idempotency = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Trace-Id": trace_id,
        "X-Idempotency-Key": idempotency
    }
    
    nonce_bytes = get_random_bytes(12)
    enc_number, nonce_b64 = encrypt_aes(card_number, CONFIG["ENCRYPTION_KEY"], nonce_bytes)
    enc_month, _ = encrypt_aes(exp_month, CONFIG["ENCRYPTION_KEY"], nonce_bytes)
    enc_year, _ = encrypt_aes(exp_year, CONFIG["ENCRYPTION_KEY"], nonce_bytes)
    enc_cvv, _ = encrypt_aes(cvv, CONFIG["ENCRYPTION_KEY"], nonce_bytes)
    
    payload = {
        "type": "card",
        "card": {
            "encrypted_card_number": enc_number,
            "encrypted_expiry_month": enc_month,
            "encrypted_expiry_year": enc_year,
            "encrypted_cvv": enc_cvv,
            "nonce": nonce_b64
        }
    }
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code in (200, 201):
        return resp.json()["data"]["id"]
    raise Exception(f"Payment method error: {resp.text}")

# ==================== MODULE 4: Charge Card ====================
def charge_card(token: str, customer_id: str, payment_method_id: str, amount: int, reference: str = None):
    if reference is None:
        reference = str(uuid.uuid4())
    url = f"{CONFIG['BASE_URL']}/charges"
    trace_id = str(uuid.uuid4())
    idempotency = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Trace-Id": trace_id,
        "X-Idempotency-Key": idempotency,
        "X-Scenario-Key": "scenario:auth_3ds&issuer:approved"  # Sandbox simule 3DS/PIN
    }
    payload = {
        "reference": reference,
        "currency": CONFIG["CURRENCY"],
        "customer_id": customer_id,
        "payment_method_id": payment_method_id,
        "redirect_url": CONFIG["REDIRECT_URL"],
        "amount": amount,  # ex. 5000 = 50.00
        "meta": {"test": "python"}
    }
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code in (200, 201):
        data = resp.json()
        if "next_action" in data.get("data", {}):
            print("Next action:", data["data"]["next_action"])
        return data
    raise Exception(f"Charge error: {resp.text}")

# ==================== MODULE 5: Authorize with PIN (si requis) ====================
def authorize_with_pin(token: str, charge_id: str, pin: str = "12345"):
    url = f"{CONFIG['BASE_URL']}/charges/{charge_id}"
    trace_id = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Trace-Id": trace_id,
        "X-Scenario-Key": "scenario:auth_3ds&issuer:approved"
    }
    nonce_bytes = get_random_bytes(12)
    enc_pin, pin_nonce_b64 = encrypt_aes(pin, CONFIG["ENCRYPTION_KEY"], nonce_bytes)
    payload = {
        "authorization": {
            "type": "pin",
            "pin": {
                "nonce": pin_nonce_b64,
                "encrypted_pin": enc_pin
            }
        }
    }
    resp = requests.put(url, json=payload, headers=headers)
    if resp.status_code == 200:
        return resp.json()
    raise Exception(f"PIN auth error: {resp.text}")

# ==================== MODULE 6: Create Transfer Recipient ====================
def create_transfer_recipient(token: str, account_number: str, bank_code: str, type_: str = "bank_ma"):
    url = f"{CONFIG['BASE_URL']}/transfers/recipients"
    trace_id = str(uuid.uuid4())
    idempotency = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Trace-Id": trace_id,
        "X-Idempotency-Key": idempotency
    }
    payload = {
        "type": type_,  # ex. "bank_ngn" ou "bank_ma" selon pays
        "bank": {
            "account_number": account_number,
            "code": bank_code
        }
    }
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code in (200, 201):
        return resp.json()["data"]["id"]
    raise Exception(f"Recipient error: {resp.text}")

# ==================== MODULE 7: Initiate Transfer ====================
def initiate_transfer(token: str, recipient_id: str, amount: int, narration: str = "Test transfer"):
    url = f"{CONFIG['BASE_URL']}/transfers"
    trace_id = str(uuid.uuid4())
    idempotency = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Trace-Id": trace_id,
        "X-Idempotency-Key": idempotency,
        "X-Scenario-Key": "scenario:successful"  # Sandbox succès
    }
    payload = {
        "action": "instant",
        "reference": str(uuid.uuid4()),
        "narration": narration,
        "payment_instruction": {
            "source_currency": CONFIG["CURRENCY"],
            "destination_currency": CONFIG["CURRENCY"],
            "amount": {"applies_to": "destination_currency", "value": amount},
            "recipient_id": recipient_id
        }
    }
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code in (200, 201):
        return resp.json()
    raise Exception(f"Transfer error: {resp.text}")

# ==================== MODULE 8: Webhook Handler (exemple simple) ====================
def handle_webhook(raw_body: bytes, signature: str, encryption_key: str):
    """Vérifie signature webhook (simplifié - adapte à ton serveur)"""
    # Utilise hmac sha256 comme dans doc Flutterwave
    import hmac, hashlib
    computed = hmac.new(encryption_key.encode(), raw_body, hashlib.sha256).hexdigest()
    return computed == signature  # Ou base64 selon version

# ==================== FLUX COMPLET TEST (main) ====================
if __name__ == "__main__":
    try:
        token = get_access_token()
        print("Token OK")

        # Flux Carte
        cust_id = create_customer(token, "test@example.com", "Komlan", "Matthania", "612345678")
        print("Customer:", cust_id)

        pm_id = create_card_payment_method(token, "5531886652122950", "09", "32", "564")
        print("Payment Method:", pm_id)

        charge = charge_card(token, cust_id, pm_id, 5000)
        print("Charge:", charge)

        if "data" in charge and "next_action" in charge["data"] and charge["data"]["next_action"]["type"] == "authorize":
            charge_id = charge["data"]["id"]
            auth = authorize_with_pin(token, charge_id)
            print("PIN Auth:", auth)

        # Flux Transfer (après avoir du solde)
        recip_id = create_transfer_recipient(token, "1234567890", "BANK_CODE")
        print("Recipient:", recip_id)
        transfer = initiate_transfer(token, recip_id, 5000)
        print("Transfer:", transfer)

    except Exception as e:
        print("Erreur:", e)