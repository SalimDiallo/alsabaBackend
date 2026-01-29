import requests
import json
from base64 import b64encode

class EscrowTransactionAdvancer:
    def __init__(self, email, password):
        self.base_url = "https://api.escrow-sandbox.com/2017-09-01"
        self.email = email
        self.password = password
        self.headers = self._create_headers()
    
    def _create_headers(self):
        auth_string = f"{self.email}:{self.password}"
        auth_encoded = b64encode(auth_string.encode()).decode()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_encoded}"
        }
    
    def get_transaction_status(self, transaction_id):
        """Récupère le statut actuel d'une transaction"""
        url = f"{self.base_url}/transaction/{transaction_id}"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur: {e}")
            return None
    
    def seller_accept_transaction(self, transaction_id):
        """
        SIMULE l'acceptation du vendeur
        En réalité, c'est VOUS qui acceptez au nom du vendeur
        puisque vous utilisez vos propres identifiants
        """
        url = f"{self.base_url}/transaction/{transaction_id}/agree"
        
        try:
            response = requests.post(url, headers=self.headers)
            response.raise_for_status()
            
            print("✅ Demande d'acceptation envoyée!")
            return response.json()
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur lors de l'acceptation: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"Détails de l'erreur: {e.response.text}")
            return None
    
    def initiate_payment(self, transaction_id, payment_method="wire"):
        """
        Initie le paiement (étape suivante après acceptation)
        """
        url = f"{self.base_url}/transaction/{transaction_id}/initiate_payment"
        
        payload = {
            "payment_methods": [
                {
                    "payer_customer": self.email,  # Vous êtes le payeur
                    "payment_type": payment_method,
                    "amount": "95000.00"  # Montant de la transaction de test
                }
            ]
        }
        
        try:
            response = requests.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            
            print("✅ Paiement initié!")
            return response.json()
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur lors de l'initiation du paiement: {e}")
            return None
    
    def check_next_actions(self, transaction_id):
        """
        Vérifie quelles actions sont possibles sur la transaction
        """
        transaction = self.get_transaction_status(transaction_id)
        if not transaction:
            return
        
        print("\n" + "="*50)
        print("📋 ANALYSE DE LA TRANSACTION")
        print("="*50)
        
        # Vérifier le statut des parties
        for party in transaction.get('parties', []):
            role = party.get('role')
            agreed = party.get('agreed', False)
            customer = party.get('customer')
            
            print(f"\n👤 {role.upper()}:")
            print(f"   Email: {customer}")
            print(f"   Accepté: {'✅ OUI' if agreed else '❌ NON'}")
        
        # Déterminer les prochaines actions
        print(f"\n🎯 STATUT GLOBAL: {transaction.get('status', 'N/A')}")
        
        if transaction.get('status') == 'awaiting_agreement':
            print("\n⬇️ PROCHAINE ACTION REQUISE:")
            print("   Le VENDEUR doit accepter la transaction")
            print("   (Nous allons simuler cette action via API)")
        
        return transaction
from config import ESCROW_EMAIL, ESCROW_PASSWORD
# UTILISATION
def main():
    print("🔄 AVANCEMENT DE LA TRANSACTION ESCROW")
    print("="*40)
    
    # ⚠️ REMPLACEZ AVEC VOS IDENTIFIANTS
    EMAIL = ESCROW_EMAIL
    PASSWORD = ESCROW_PASSWORD
    
    # ⚠️ REMPLACEZ AVEC VOTRE TRANSACTION ID
    TRANSACTION_ID = "5580062"  # Mettez l'ID de VOTRE transaction
    
    # Initialiser
    advancer = EscrowTransactionAdvancer(EMAIL, PASSWORD)
    
    # 1. Vérifier l'état actuel
    print(f"\n1. Vérification de la transaction {TRANSACTION_ID}...")
    current_status = advancer.get_transaction_status(TRANSACTION_ID)
    
    if current_status:
        print(f"   Statut: {current_status.get('status', 'Non disponible')}")
        print(f"   Description: {current_status.get('description')}")
    
    # 2. Analyser les actions possibles
    print(f"\n2. Analyse des actions requises...")
    transaction_details = advancer.check_next_actions(TRANSACTION_ID)
    
    # 3. Simuler l'acceptation du vendeur
    print(f"\n3. Simulation de l'acceptation du vendeur...")
    response = advancer.seller_accept_transaction(TRANSACTION_ID)
    
    if response:
        # 4. Vérifier le nouveau statut
        print(f"\n4. Vérification du nouveau statut...")
        new_status = advancer.get_transaction_status(TRANSACTION_ID)
        
        if new_status:
            print(f"   Nouveau statut: {new_status.get('status', 'N/A')}")
            
            # 5. Si accepté, initier le paiement
            if new_status.get('status') == 'accepted':
                print(f"\n5. Initiation du paiement...")
                payment_response = advancer.initiate_payment(TRANSACTION_ID)
                
                if payment_response:
                    print(f"\n🎉 Transaction avancée avec succès!")
                    print(f"   Prochaine étape sur le dashboard: Shipping")
            else:
                print(f"\n⚠️ La transaction n'est pas encore 'accepted'")
                print(f"   Statut actuel: {new_status.get('status')}")
    
    # 6. Lien vers le dashboard
    print(f"\n🌐 LIEN DASHBOARD:")
    print(f"   https://sandbox.escrow.com/app/transaction/{TRANSACTION_ID}")
    print(f"\n🔍 Actualisez la page pour voir les changements!")

if __name__ == "__main__":
    main()