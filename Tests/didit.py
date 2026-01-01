#!/usr/bin/env python3
"""
Script de test pour l'API Didit Sandbox
Usage: python test_didit_sandbox.py
"""

import requests
import json
import uuid
from datetime import datetime, timedelta
import sys
import os

class DiditSandboxTester:
    """Classe pour tester l'API Didit Sandbox"""
    
    def __init__(self, api_key, app_id):
        """
        Initialise le client Didit
        
        Args:
            api_key (str): Votre clé API Didit
            app_id (str): Votre App ID Didit
        """
        self.api_key = api_key
        self.app_id = app_id
        self.base_url = "https://api.sandbox.didit.me/v1"  # Sandbox URL
        
        # Headers communs
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-App-ID": self.app_id,
            "Content-Type": "application/json"
        }
        
        # User de test
        self.test_user_id = str(uuid.uuid4())
        
        print("=" * 60)
        print("DIDIT SANDBOX TESTER")
        print("=" * 60)
        print(f"Base URL: {self.base_url}")
        print(f"Test User ID: {self.test_user_id}")
        print(f"Timestamp: {datetime.now().isoformat()}")
        print("=" * 60)
    
    def test_connection(self):
        """Teste la connexion à l'API Didit"""
        print("\n1️⃣  TEST DE CONNEXION...")
        
        url = f"{self.base_url}/health"  # Endpoint santé (à vérifier dans la doc)
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            print(f"   URL: {url}")
            print(f"   Status Code: {response.status_code}")
            
            if response.status_code == 200:
                print("   ✅ Connexion réussie!")
                if response.text:
                    print(f"   Response: {response.text[:100]}...")
                return True
            else:
                print(f"   ❌ Échec: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Exception: {e}")
            return False
    
    def create_verification_session(self, document_type="PASSPORT"):
        """
        Crée une session de vérification
        
        Args:
            document_type (str): Type de document (PASSPORT, NATIONAL_ID, DRIVER_LICENSE)
        
        Returns:
            dict: Résultat de la session
        """
        print(f"\n2️⃣  CRÉATION SESSION VÉRIFICATION ({document_type})...")
        
        # URL d'endpoint - À ADAPTER selon la doc exacte
        url = f"{self.base_url}/verifications"
        
        # Payload de test
        payload = {
            "user_id": self.test_user_id,
            "document_types": [document_type],
            "callback_url": "https://webhook.site/test-didit",  # Webhook test
            "redirect_url": "https://your-frontend.com/kyc/callback",
            "metadata": {
                "test": True,
                "environment": "sandbox",
                "timestamp": datetime.now().isoformat(),
                "user_email": f"test_{self.test_user_id[:8]}@example.com"
            }
        }
        
        print(f"   URL: {url}")
        print(f"   Headers: { {k: '***' if 'auth' in k.lower() else v for k, v in self.headers.items()} }")
        print(f"   Payload: {json.dumps(payload, indent=2)}")
        
        try:
            response = requests.post(
                url, 
                json=payload, 
                headers=self.headers, 
                timeout=15
            )
            
            print(f"\n   Status Code: {response.status_code}")
            
            if response.status_code in [200, 201]:
                data = response.json()
                print("   ✅ Session créée avec succès!")
                print(f"   Session ID: {data.get('id', 'N/A')}")
                print(f"   Verification URL: {data.get('verification_url', 'N/A')[:80]}...")
                
                # Sauvegarder pour les tests suivants
                self.session_id = data.get('id')
                self.verification_url = data.get('verification_url')
                
                return {
                    "success": True,
                    "session_id": self.session_id,
                    "verification_url": self.verification_url,
                    "raw_response": data
                }
            else:
                print(f"   ❌ Échec: {response.status_code}")
                print(f"   Response: {response.text}")
                return {
                    "success": False,
                    "error": response.text,
                    "status_code": response.status_code
                }
                
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def check_session_status(self, session_id=None):
        """
        Vérifie le statut d'une session
        
        Args:
            session_id (str): ID de session (optionnel, utilise le dernier)
        
        Returns:
            dict: Statut de la session
        """
        if not session_id:
            if hasattr(self, 'session_id'):
                session_id = self.session_id
            else:
                print("   ❌ Aucune session ID disponible")
                return None
        
        print(f"\n3️⃣  VÉRIFICATION STATUT SESSION ({session_id})...")
        
        # URL d'endpoint - À ADAPTER
        url = f"{self.base_url}/verifications/{session_id}"
        
        print(f"   URL: {url}")
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            
            print(f"   Status Code: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print("   ✅ Statut récupéré!")
                
                # Affichage formaté
                print(f"\n   📊 DÉTAILS SESSION:")
                print(f"   - ID: {data.get('id')}")
                print(f"   - Status: {data.get('status', 'N/A')}")
                print(f"   - Created: {data.get('created_at', 'N/A')}")
                
                if data.get('verification_result'):
                    result = data['verification_result']
                    print(f"   - Document Type: {result.get('document_type', 'N/A')}")
                    print(f"   - Verified: {result.get('verified', 'N/A')}")
                    print(f"   - Extracted Data: {result.get('extracted_data', {})}")
                
                return data
            else:
                print(f"   ❌ Échec: {response.status_code}")
                print(f"   Response: {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Exception: {e}")
            return None
    
    def simulate_webhook_payload(self):
        """
        Génère un payload de webhook simulé pour tester
        """
        print("\n4️⃣  PAYLOAD WEBHOOK SIMULÉ...")
        
        webhook_payload = {
            "id": f"wh_{uuid.uuid4()}",
            "type": "verification.completed",
            "created_at": datetime.now().isoformat(),
            "data": {
                "object": "verification",
                "id": self.session_id if hasattr(self, 'session_id') else "verif_123",
                "user_id": self.test_user_id,
                "status": "verified",  # ou 'rejected', 'pending'
                "document_type": "PASSPORT",
                "country": "FR",
                "verified_at": datetime.now().isoformat(),
                "verification_result": {
                    "status": "approved",
                    "score": 0.95,
                    "extracted_data": {
                        "first_name": "JEAN",
                        "last_name": "DUPONT",
                        "date_of_birth": "1985-07-15",
                        "document_number": "12AB34567",
                        "nationality": "FRA",
                        "expiry_date": "2030-12-31"
                    },
                    "checks": {
                        "document_authenticity": True,
                        "face_match": True,
                        "liveness": True
                    }
                },
                "metadata": {
                    "test": True,
                    "environment": "sandbox"
                }
            }
        }
        
        print("   📋 Payload JSON pour votre webhook endpoint:")
        print("   " + "=" * 50)
        print(json.dumps(webhook_payload, indent=2, ensure_ascii=False))
        print("   " + "=" * 50)
        
        return webhook_payload
    
    def test_different_document_types(self):
        """
        Teste différents types de documents
        """
        print("\n5️⃣  TEST DIFFÉRENTS TYPES DE DOCUMENTS...")
        
        document_types = ["PASSPORT", "NATIONAL_ID", "DRIVER_LICENSE"]
        
        for doc_type in document_types:
            print(f"\n   📄 Test avec: {doc_type}")
            result = self.create_verification_session(doc_type)
            
            if result and result.get('success'):
                print(f"   ✅ {doc_type} - OK")
                # Vérifier le statut après 2 secondes
                import time
                time.sleep(2)
                self.check_session_status(result['session_id'])
            else:
                print(f"   ❌ {doc_type} - Échec")
    
    def run_full_test(self):
        """
        Exécute tous les tests
        """
        print("\n" + "=" * 60)
        print("EXÉCUTION COMPLÈTE DES TESTS")
        print("=" * 60)
        
        # 1. Test connexion
        if not self.test_connection():
            print("❌ Arrêt des tests: connexion échouée")
            return
        
        # 2. Créer une session
        session_result = self.create_verification_session("PASSPORT")
        
        if not session_result or not session_result.get('success'):
            print("❌ Arrêt des tests: création session échouée")
            return
        
        # 3. Vérifier statut
        print("\n📦 Attente 3 secondes avant vérification statut...")
        import time
        time.sleep(3)
        
        self.check_session_status()
        
        # 4. Générer payload webhook
        self.simulate_webhook_payload()
        
        # 5. Tester autres documents (optionnel)
        print("\nVoulez-vous tester d'autres types de documents? (o/n)")
        response = input("> ").strip().lower()
        if response == 'o':
            self.test_different_document_types()
        
        print("\n" + "=" * 60)
        print("TESTS TERMINÉS")
        print("=" * 60)
        
        # Résumé
        print("\n📈 RÉSUMÉ:")
        print(f"   User Test ID: {self.test_user_id}")
        print(f"   Session ID: {getattr(self, 'session_id', 'N/A')}")
        print(f"   Verification URL: {getattr(self, 'verification_url', 'N/A')[:80]}...")
        
        if hasattr(self, 'verification_url'):
            print(f"\n🌐 Pour tester manuellement:")
            print(f"   1. Ouvrez: {self.verification_url}")
            print(f"   2. Utilisez un document de test Didit")
            print(f"   3. Vérifiez le webhook sur: https://webhook.site")


def main():
    """Fonction principale"""
    
    # Récupérer les credentials depuis les variables d'environnement
    API_KEY = os.getenv("DIDIT_API_KEY")
    APP_ID = os.getenv("DIDIT_APP_ID")
    
    # Ou depuis le fichier .env
    if not API_KEY or not APP_ID:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            API_KEY = os.getenv("DIDIT_API_KEY")
            APP_ID = os.getenv("DIDIT_APP_ID")
        except ImportError:
            pass
    
    # Demander si non trouvé
    if not API_KEY:
        API_KEY = input("Entrez votre DIDIT_API_KEY: ").strip()
    
    if not APP_ID:
        APP_ID = input("Entrez votre DIDIT_APP_ID: ").strip()
    
    if not API_KEY or not APP_ID:
        print("❌ API Key et App ID requis!")
        print("💡 Conseil: Créez un fichier .env avec:")
        print("DIDIT_API_KEY=votre_clé_sandbox")
        print("DIDIT_APP_ID=votre_app_id")
        sys.exit(1)
    
    # Initialiser le testeur
    tester = DiditSandboxTester(API_KEY, APP_ID)
    
    # Menu interactif
    print("\n🔧 MENU DE TEST:")
    print("1. Test complet")
    print("2. Test de connexion seulement")
    print("3. Créer session vérification")
    print("4. Vérifier statut session")
    print("5. Générer payload webhook")
    print("6. Tester tous types documents")
    print("7. Quitter")
    
    choice = input("\nChoisissez une option (1-7): ").strip()
    
    if choice == "1":
        tester.run_full_test()
    elif choice == "2":
        tester.test_connection()
    elif choice == "3":
        doc_type = input("Type de document (PASSPORT/NATIONAL_ID/DRIVER_LICENSE): ").strip().upper()
        tester.create_verification_session(doc_type)
    elif choice == "4":
        session_id = input("Session ID (laisser vide pour dernière): ").strip()
        tester.check_session_status(session_id if session_id else None)
    elif choice == "5":
        tester.simulate_webhook_payload()
    elif choice == "6":
        tester.test_different_document_types()
    elif choice == "7":
        print("Au revoir!")
        sys.exit(0)
    else:
        print("Option invalide")

if __name__ == "__main__":
    main()