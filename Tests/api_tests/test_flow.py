import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000/api/accounts"
TEST_PHONE = "0684499227"  # Votre numéro
COUNTRY_CODE = "+212"

def print_step(msg):
    print(f"\n\033[94m>>> {msg}\033[0m")

def print_success(msg):
    print(f"\033[92m✓ {msg}\033[0m")

def print_error(msg):
    print(f"\033[91m✗ {msg}\033[0m")

def request_otp():
    print_step("1. Demande d'envoi OTP")
    url = f"{BASE_URL}/auth/phone/"
    payload = {
        "phone_number": TEST_PHONE,
        "country_code": COUNTRY_CODE
    }
    
    try:
        response = requests.post(url, json=payload)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print_success("OTP envoyé avec succès !")
            print(f"Session Key: {data.get('session_key')}")
            return data.get('session_key'), data.get('phone_number') # Return full phone e164
        else:
            print_error(f"Erreur: {response.text}")
            return None, None
    except Exception as e:
        print_error(f"Exception: {e}")
        return None, None

def verify_otp(session_key, phone_number):
    print_step("2. Vérification OTP")
    otp_code = input(">> Entrez le code reçus par SMS : ")
    
    url = f"{BASE_URL}/auth/verify/"
    payload = {
        "phone_number": phone_number,
        "code": otp_code,
        "session_key": session_key
    }
    
    try:
        response = requests.post(url, json=payload)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print_success("Vérification réussie !")
            token = data.get('auth', {}).get('access_token')
            print(f"Token Access: {token[:20]}...")
            return token
        else:
            print_error(f"Erreur: {response.text}")
            return None
    except Exception as e:
        print_error(f"Exception: {e}")
        return None

if __name__ == "__main__":
    print("=== DÉBUT DU TEST ===")
    session_key, full_phone = request_otp()
    
    if session_key and full_phone:
        verify_otp(session_key, full_phone)
    print("\n=== FIN DU TEST ===")
