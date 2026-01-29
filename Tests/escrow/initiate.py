import requests
import json
from base64 import b64encode
from config import SELLER_EMAIL
class EscrowSandboxTester:
    def __init__(self, email, password):
        """
        Initialise le client API Escrow Sandbox
        
        Args:
            email: Votre email Escrow.com
            password: Votre mot de passe Escrow.com
        """
        self.base_url = "https://api.escrow-sandbox.com/2017-09-01"
        self.email = email
        self.password = password
        self.headers = self._create_headers()
    
    def _create_headers(self):
        """Crée les en-têtes d'authentification"""
        auth_string = f"{self.email}:{self.password}"
        auth_encoded = b64encode(auth_string.encode()).decode()
        
        return {
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_encoded}"
        }
    
    def create_test_transaction(self):
        """
        Crée une transaction de test comme dans la documentation
        Utilise les emails de test fournis par Escrow
        """
        url = f"{self.base_url}/transaction"
        
        # Payload exact de l'exemple de la documentation
        payload = {
            "parties": [
                {
                    "role": "buyer",
                    "customer": "me"  # Sera remplacé par votre email
                },
                {
                    "role": "seller",
                    "customer": SELLER_EMAIL  # Email de test Escrow
                }
            ],
            "currency": "usd",
            "description": "1962 Fender Stratocaster",
            "items": [
                {
                    "title": "1962 Fender Stratocaster",
                    "description": "Like new condition, includes original hard case.",
                    "type": "general_merchandise",
                    "inspection_period": 259200,  # 3 jours en secondes
                    "quantity": 1,
                    "schedule": [
                        {
                            "amount": 95000.0,
                            "payer_customer": "me",
                            "beneficiary_customer": SELLER_EMAIL
                        }
                    ]
                }
            ]
        }
        
        try:
            response = requests.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            
            transaction_data = response.json()
            print("✅ Transaction créée avec succès!")
            print(f"ID de transaction: {transaction_data['id']}")
            
            # Remplace 'me' par l'email réel dans la réponse
            for party in transaction_data['parties']:
                if party['customer'] == 'me':
                    party['customer'] = self.email
            
            return transaction_data
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur lors de la création: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"Détails: {e.response.text}")
            return None
    
    def get_transaction(self, transaction_id):
        """
        Récupère les détails d'une transaction
        
        Args:
            transaction_id: L'ID de la transaction à récupérer
        """
        url = f"{self.base_url}/transaction/{transaction_id}"
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            transaction_data = response.json()
            print(f"✅ Transaction {transaction_id} récupérée")
            return transaction_data
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur lors de la récupération: {e}")
            return None
    
    def list_transactions(self):
        """Liste toutes vos transactions"""
        url = f"{self.base_url}/transaction"
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            transactions = response.json()
            print(f"✅ {len(transactions)} transactions trouvées")
            return transactions
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur: {e}")
            return None
    
    def print_transaction_summary(self, transaction_data):
        """Affiche un résumé lisible d'une transaction"""
        if not transaction_data:
            print("Aucune donnée de transaction")
            return
        
        print("\n" + "="*50)
        print(f"📋 RÉSUMÉ DE LA TRANSACTION")
        print("="*50)
        print(f"ID: {transaction_data.get('id')}")
        print(f"Description: {transaction_data.get('description')}")
        print(f"Devise: {transaction_data.get('currency').upper()}")
        print(f"Date création: {transaction_data.get('creation_date')}")
        
        print("\n👥 Parties:")
        for party in transaction_data.get('parties', []):
            role = party.get('role', 'N/A')
            customer = party.get('customer', 'N/A')
            agreed = "✓" if party.get('agreed') else "✗"
            print(f"  - {role}: {customer} (Accepté: {agreed})")
        
        print("\n📦 Articles:")
        for item in transaction_data.get('items', []):
            print(f"  - {item.get('title')}")
            print(f"    Quantité: {item.get('quantity')}")
            print(f"    Période inspection: {item.get('inspection_period')} secondes")
            
            # Statut de l'article
            status = item.get('status', {})
            print("    Statut: ", end="")
            for key, value in status.items():
                if value:
                    print(f"{key}, ", end="")
            print()

# Fonction principale pour exécuter les tests
from config import ESCROW_EMAIL, ESCROW_PASSWORD

def main():
    print("🚀 TEST DE L'API ESCROW SANDBOX")
    print("="*40)
    # ⚠️ REMPLACEZ CES VALEURS PAR LES VÔTRES ⚠️
    EMAIL = ESCROW_EMAIL  # Votre email Escrow.com
    PASSWORD = ESCROW_PASSWORD    # Votre mot de passe
    
    # Initialiser le tester
    tester = EscrowSandboxTester(EMAIL, PASSWORD)
    
    # Test 1: Créer une transaction
    print("\n1. Création d'une transaction de test...")
    new_transaction = tester.create_test_transaction()
    
    if new_transaction:
        # Afficher le résumé
        tester.print_transaction_summary(new_transaction)
        
        # Test 2: Récupérer la transaction par ID
        transaction_id = new_transaction['id']
        print(f"\n2. Récupération de la transaction {transaction_id}...")
        retrieved_transaction = tester.get_transaction(transaction_id)
        
        if retrieved_transaction:
            # Test 3: Lister toutes les transactions
            print("\n3. Liste de toutes vos transactions...")
            all_transactions = tester.list_transactions()
            
            if all_transactions:
                print("\n🎉 Tous les tests ont réussi!")
                print("\n📝 Prochaines étapes:")
                print("1. Connectez-vous au sandbox: https://sandbox.escrow.com")
                print("2. Vérifiez votre transaction dans l'interface")
                print("3. Testez d'autres endpoints API")
                print("\n⚠️ Rappel: Ceci est l'environnement SANDBOX")
                print("   Aucune transaction réelle ni argent réel n'est impliqué.")

if __name__ == "__main__":
    main()