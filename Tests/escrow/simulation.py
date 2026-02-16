import requests
import json
from base64 import b64encode

class EscrowSimpleTester:
    def __init__(self):
        self.base_url = "https://api.escrow-sandbox.com/2017-09-01"
        
    def test_with_your_account(self):
        """Utilise VOS identifiants réels"""
        print("🔐 TEST AVEC VOTRE COMPTE RÉEL")
        print("="*50)
        
        # DEMANDER VOS IDENTIFIANTS
        email = input("Votre email Escrow Sandbox: ").strip()
        password = input("Votre mot de passe: ").strip()
        
        # Tester la connexion d'abord
        if self.test_connection(email, password):
            # Créer une transaction simple
            transaction_id = self.create_simple_transaction(email, password)
            
            if transaction_id:
                print(f"\n🎉 SUCCÈS! Transaction créée: {transaction_id}")
                print(f"🔗 Dashboard: https://sandbox.escrow.com/app/transaction/{transaction_id}")
                print(f"📧 Connectez-vous avec: {email}")
        
    def test_connection(self, email, password):
        """Teste si les identifiants fonctionnent"""
        print(f"\n🔍 Test de connexion pour {email}...")
        
        url = f"{self.base_url}/transaction"
        headers = self.create_headers(email, password)
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                print("✅ Connexion API réussie!")
                return True
            else:
                print(f"❌ Erreur {response.status_code}: {response.text[:100]}")
                return False
        except Exception as e:
            print(f"❌ Exception: {e}")
            return False
    
    def create_headers(self, email, password):
        """Crée les headers d'authentification"""
        auth_string = f"{email}:{password}"
        auth_encoded = b64encode(auth_string.encode()).decode()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_encoded}"
        }
    
    def create_simple_transaction(self, email, password):
        """Crée une transaction TRÈS simple"""
        print(f"\n🔄 Création d'une transaction test...")
        
        url = f"{self.base_url}/transaction"
        headers = self.create_headers(email, password)
        
        # Transaction MINIMALE pour test
        payload = {
            "parties": [
                {
                    "role": "buyer",
                    "customer": email,  # VOUS êtes l'acheteur
                    "agreed": True
                },
                {
                    "role": "seller",
                    "customer": "seller@test.escrow.com",  # Compte test
                    "agreed": False
                }
            ],
            "currency": "usd",
            "description": "Transaction test API",
            "amount": 10.00,  # Petit montant
            "items": [
                {
                    "title": "Service test",
                    "description": "Test d'intégration API",
                    "type": "general_merchandise",
                    "inspection_period": 86400,  # 1 jour
                    "quantity": 1,
                    "schedule": [
                        {
                            "amount": 10.00,
                            "payer_customer": email,
                            "beneficiary_customer": "seller@test.escrow.com"
                        }
                    ]
                }
            ]
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            
            transaction = response.json()
            print(f"✅ Transaction créée!")
            print(f"   ID: {transaction.get('id')}")
            print(f"   Statut: {transaction.get('status', 'N/A')}")
            
            return transaction.get('id')
            
        except requests.exceptions.HTTPError as e:
            print(f"❌ Erreur HTTP {e.response.status_code}:")
            print(f"   Détails: {e.response.text[:200]}")
        except Exception as e:
            print(f"❌ Exception: {e}")
        
        return None

# TEST RAPIDE
def quick_test():
    print("🚀 TEST RAPIDE ESCROW SANDBOX")
    print("="*50)
    print("1. Avez-vous un compte sur https://sandbox.escrow.com ?")
    print("2. Sinon, créez-en un rapidement (gratuit)")
    print("3. Utilisez ces identifiants ci-dessous")
    print("="*50)
    
    tester = EscrowSimpleTester()
    tester.test_with_your_account()

if __name__ == "__main__":
    quick_test()