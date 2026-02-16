import requests
import uuid
import json
import hmac
import hashlib
import base64
from config import BASE_URL_SANDBOX, AUTH_URL, CLIENT_ID, CLIENT_SECRET, ENCRYPTION_KEY, CURRENCY, REDIRECT_URL
# ==================== CONFIG ====================
CONFIG = {
    "CLIENT_ID": CLIENT_ID,
    "CLIENT_SECRET": CLIENT_SECRET,
    "ENCRYPTION_KEY": ENCRYPTION_KEY,  # pour webhook signature
    "BASE_URL": BASE_URL_SANDBOX,
    "AUTH_URL": AUTH_URL,
    "CURRENCY": CURRENCY,          # ex. XOF pour Sénégal/Côte d'Ivoire (Orange Money)
    "COUNTRY_CODE": "221",      # 221 = Sénégal pour Orange Money
    "NETWORK": "ORANGE",        # ou "orangemoney" selon doc
    "REDIRECT_URL": REDIRECT_URL,  # pour test redirect
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

# ==================== MODULE 1: Create Customer ====================
def create_customer(token: str, email: str, first_name: str, last_name: str, phone: str):
    url = f"{CONFIG['BASE_URL']}/customers"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Trace-Id": str(uuid.uuid4()),
        "X-Idempotency-Key": str(uuid.uuid4())
    }
    payload = {
        "name": {"first": first_name, "last": last_name},
        "phone": {"country_code": CONFIG["COUNTRY_CODE"], "number": phone},
        "email": email
    }
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code in (200, 201):
        return resp.json()["data"]["id"]
    raise Exception(f"Customer error: {resp.text}")

# ==================== MODULE 2: Create Mobile Money Payment Method ====================
def create_mobile_money_payment_method(token: str, phone: str):
    url = f"{CONFIG['BASE_URL']}/payment-methods"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Trace-Id": str(uuid.uuid4()),
        "X-Idempotency-Key": str(uuid.uuid4())
    }
    payload = {
        "type": "mobile_money",
        "mobile_money": {
            "country_code": CONFIG["COUNTRY_CODE"],
            "network": CONFIG["NETWORK"],
            "phone_number": phone
        }
    }
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code in (200, 201):
        return resp.json()["data"]["id"]
    raise Exception(f"Payment method error: {resp.text}")

# ==================== MODULE 3: Charge Mobile Money (Encaissement) ====================
def charge_mobile_money(token: str, customer_id: str, payment_method_id: str, amount: int, reference: str = None):
    if reference is None:
        reference = str(uuid.uuid4())
    
    url = f"{CONFIG['BASE_URL']}/charges"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Trace-Id": str(uuid.uuid4()),
        "X-Idempotency-Key": str(uuid.uuid4()),
        "X-Scenario-Key": "scenario:successful"  # Sandbox succès
    }
    payload = {
        "reference": reference,
        "currency": CONFIG["CURRENCY"],
        "customer_id": customer_id,
        "payment_method_id": payment_method_id,
        "amount": amount,
        "redirect_url": CONFIG["REDIRECT_URL"]
    }
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code in (200, 201):
        data = resp.json()
        print("Charge lancé :", json.dumps(data, indent=2))
        if "next_action" in data.get("data", {}):
            action = data["data"]["next_action"]
            print("Action requise :", action)
        return data["data"]["id"]  # Retourne charge_id pour vérif
    raise Exception(f"Charge error: {resp.text}")

# ==================== MODULE 4: Create Mobile Money Recipient (pour Décaissement) ====================
def create_mobile_money_recipient(token: str, phone: str, first_name: str, last_name: str):
    url = f"{CONFIG['BASE_URL']}/transfers/recipients"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Trace-Id": str(uuid.uuid4()),
        "X-Idempotency-Key": str(uuid.uuid4())
    }
    payload = {
        "type": "mobile_money",
        "mobile_money": {
            "country": CONFIG["COUNTRY_CODE"][-2:],  # ex. "221" → "SN" pour Sénégal
            "network": CONFIG["NETWORK"],
            "msisdn": CONFIG["COUNTRY_CODE"] + phone  # format international
        },
        "name": {"first": first_name, "last": last_name}
    }
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code in (200, 201):
        return resp.json()["data"]["id"]
    raise Exception(f"Recipient error: {resp.text}")

# ==================== MODULE 5: Initiate Mobile Money Transfer (Décaissement) ====================
def initiate_mobile_money_transfer(token: str, recipient_id: str, amount: int, narration: str = "Test payout"):
    url = f"{CONFIG['BASE_URL']}/transfers"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Trace-Id": str(uuid.uuid4()),
        "X-Idempotency-Key": str(uuid.uuid4()),
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
        data = resp.json()
        print("Transfer lancé :", json.dumps(data, indent=2))
        return data["data"]["id"]  # transfer_id
    raise Exception(f"Transfer error: {resp.text}")

# ==================== MODULE 6: Webhook Handler (pour confirmations encaissement/décaissement) ====================
def handle_webhook(raw_body: bytes, signature: str):
    """Vérifie signature webhook"""
    key = CONFIG["ENCRYPTION_KEY"].encode('utf-8')
    computed = hmac.new(key, raw_body, hashlib.sha256).digest()
    computed_b64 = base64.b64encode(computed).decode('utf-8')
    return hmac.compare_digest(computed_b64, signature)

# ==================== FLUX COMPLET TEST ====================
if __name__ == "__main__":
    try:
        token = get_access_token()
        print("Token OK")

        # ENCAISSEMENT (RECEVOIR ARGENT VIA MOBILE MONEY)
        cust_id = create_customer(token, "test.om@example.com", "Komlan", "Matthania", "781234567")
        print("Customer ID:", cust_id)

        pm_id = create_mobile_money_payment_method(token, "781234567")
        print("Payment Method ID:", pm_id)

        charge_id = charge_mobile_money(token, cust_id, pm_id, 5000)
        print("Charge ID:", charge_id)

        # DÉCAISSEMENT (ENVOYER ARGENT VERS MOBILE MONEY)
        recip_id = create_mobile_money_recipient(token, "781234567", "Komlan", "Matthania")
        print("Recipient ID:", recip_id)

        transfer_id = initiate_mobile_money_transfer(token, recip_id, 2500)  # ex. envoyer 25% des 5000 reçus
        print("Transfer ID:", transfer_id)

    except Exception as e:
        print("Erreur:", e)