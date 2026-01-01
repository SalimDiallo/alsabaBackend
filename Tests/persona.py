import os
import json
import hmac
import hashlib
import requests
from datetime import datetime
from flask import Flask, request, jsonify

class PersonaKYC:
    def __init__(self, environment="sandbox"):
        """
        Initialiser le client Persona
        
        Args:
            environment: 'sandbox' ou 'production'
        """
        self.environment = environment
        
        if environment == "sandbox":
            self.base_url = "https://sandbox.withpersona.com/api/v1"
            self.api_key = os.getenv("PERSONA_SANDBOX_API_KEY")
        else:
            self.base_url = "https://withpersona.com/api/v1"
            self.api_key = os.getenv("PERSONA_API_KEY")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Persona-Version": "2023-01-05"
        }
        
        if not self.api_key:
            raise ValueError("API key not found. Set PERSONA_SANDBOX_API_KEY environment variable.")
    
    def create_inquiry(self, user_data, template_id=None):
        """
        Créer une nouvelle vérification KYC
        
        Args:
            user_data: dict avec les données utilisateur
            template_id: ID du template Persona (optionnel)
        
        Returns:
            dict avec les détails de l'inquiry
        """
        # Si aucun template_id n'est fourni, utiliser un template sandbox par défaut
        if not template_id:
            # Template ID sandbox (à remplacer par le vôtre)
            template_id = os.getenv("PERSONA_TEMPLATE_ID", "itmpl_xxxxxxxxxxxx")
        
        payload = {
            "data": {
                "type": "inquiry",
                "attributes": {
                    "template-id": template_id,
                    "reference-id": user_data.get("reference_id", f"user_{datetime.now().timestamp()}"),
                    "fields": {
                        "name-first": user_data.get("first_name", ""),
                        "name-last": user_data.get("last_name", ""),
                        "birthdate": user_data.get("birthdate", ""),
                        "email-address": user_data.get("email", ""),
                        "phone-number": user_data.get("phone", ""),
                        "address-street-1": user_data.get("address", ""),
                        "address-city": user_data.get("city", ""),
                        "address-postal-code": user_data.get("postal_code", ""),
                        "address-country-code": user_data.get("country", "FR")
                    }
                }
            }
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/inquiries",
                headers=self.headers,
                json=payload
            )
            
            response.raise_for_status()
            data = response.json()
            
            inquiry_id = data["data"]["id"]
            verification_url = data["data"]["attributes"]["verification-url"]
            status = data["data"]["attributes"]["status"]
            
            print(f"✅ Inquiry créée: {inquiry_id}")
            print(f"🔗 URL de vérification: {verification_url}")
            
            return {
                "success": True,
                "inquiry_id": inquiry_id,
                "verification_url": verification_url,
                "status": status,
                "full_response": data
            }
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur API Persona: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"Response: {e.response.text}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_inquiry(self, inquiry_id):
        """
        Récupérer les détails d'une inquiry
        
        Args:
            inquiry_id: ID de l'inquiry
        
        Returns:
            dict avec les détails
        """
        try:
            response = requests.get(
                f"{self.base_url}/inquiries/{inquiry_id}",
                headers=self.headers
            )
            
            response.raise_for_status()
            data = response.json()
            
            return {
                "success": True,
                "data": data["data"]
            }
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def list_inquiries(self, limit=10):
        """
        Lister les inquiries
        
        Args:
            limit: nombre maximum d'inquiries à récupérer
        
        Returns:
            liste des inquiries
        """
        try:
            params = {"page[size]": limit}
            response = requests.get(
                f"{self.base_url}/inquiries",
                headers=self.headers,
                params=params
            )
            
            response.raise_for_status()
            data = response.json()
            
            return {
                "success": True,
                "inquiries": data["data"]
            }
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def verify_webhook_signature(self, payload, signature, secret):
        """
        Vérifier la signature d'un webhook
        
        Args:
            payload: corps de la requête (bytes)
            signature: signature du header
            secret: clé secrète des webhooks
        
        Returns:
            bool: True si la signature est valide
        """
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)

# Application Flask pour les webhooks
app = Flask(__name__)

# Initialiser Persona (sandbox par défaut)
persona = PersonaKYC(environment="sandbox")

@app.route('/')
def home():
    return """
    <h1>Persona KYC Integration</h1>
    <p>Endpoints disponibles:</p>
    <ul>
        <li>POST /create-verification - Créer une vérification</li>
        <li>GET /inquiry/<id> - Vérifier le statut</li>
        <li>POST /webhook/persona - Webhook Persona</li>
    </ul>
    """

@app.route('/create-verification', methods=['POST'])
def create_verification():
    """Endpoint pour créer une vérification KYC"""
    try:
        data = request.json or request.form
        
        # Données minimales requises
        user_data = {
            "reference_id": data.get("reference_id"),
            "first_name": data.get("first_name"),
            "last_name": data.get("last_name"),
            "email": data.get("email"),
            "phone": data.get("phone"),
            "birthdate": data.get("birthdate"),
            "address": data.get("address", ""),
            "city": data.get("city", ""),
            "postal_code": data.get("postal_code", ""),
            "country": data.get("country", "FR")
        }
        
        result = persona.create_inquiry(user_data)
        
        if result["success"]:
            return jsonify({
                "message": "Vérification créée avec succès",
                "verification_url": result["verification_url"],
                "inquiry_id": result["inquiry_id"]
            }), 201
        else:
            return jsonify({"error": result["error"]}), 400
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/inquiry/<inquiry_id>', methods=['GET'])
def get_inquiry_status(inquiry_id):
    """Vérifier le statut d'une inquiry"""
    result = persona.get_inquiry(inquiry_id)
    
    if result["success"]:
        inquiry_data = result["data"]
        status = inquiry_data["attributes"]["status"]
        
        return jsonify({
            "inquiry_id": inquiry_id,
            "status": status,
            "created_at": inquiry_data["attributes"]["created-at"],
            "completed_at": inquiry_data["attributes"].get("completed-at"),
            "fields": inquiry_data["attributes"].get("fields", {})
        })
    else:
        return jsonify({"error": result["error"]}), 404

@app.route('/webhook/persona', methods=['POST'])
def persona_webhook():
    """Endpoint pour recevoir les webhooks de Persona"""
    webhook_secret = os.getenv("PERSONA_WEBHOOK_SECRET")
    
    if not webhook_secret:
        return jsonify({"error": "Webhook secret not configured"}), 500
    
    # Récupérer la signature
    signature = request.headers.get("Persona-Signature")
    if not signature:
        return jsonify({"error": "Missing signature"}), 401
    
    # Vérifier la signature
    payload = request.get_data()
    if not persona.verify_webhook_signature(payload, signature, webhook_secret):
        return jsonify({"error": "Invalid signature"}), 401
    
    # Traiter le webhook
    webhook_data = request.json
    
    # Log l'événement
    event_type = webhook_data.get("data", {}).get("attributes", {}).get("name")
    inquiry_id = webhook_data.get("data", {}).get("relationships", {}).get("inquiry", {}).get("data", {}).get("id")
    
    print(f"📩 Webhook reçu: {event_type} pour inquiry {inquiry_id}")
    
    # Ici, vous pouvez:
    # 1. Mettre à jour votre base de données
    # 2. Envoyer un email de confirmation
    # 3. Notifier votre système
    
    return jsonify({"status": "webhook received"}), 200

# Script de test
def test_sandbox_flow():
    """Tester le flux complet en sandbox"""
    print("🧪 Test du flux Persona KYC Sandbox")
    
    # Données de test
    test_user = {
        "reference_id": f"test_user_{datetime.now().timestamp()}",
        "first_name": "Jean",
        "last_name": "Dupont",
        "birthdate": "1985-05-15",
        "email": "test@example.com",
        "phone": "+33612345678",
        "address": "123 Rue de Paris",
        "city": "Paris",
        "postal_code": "75001",
        "country": "FR"
    }
    
    # 1. Créer une inquiry
    print("1. Création de l'inquiry...")
    result = persona.create_inquiry(test_user)
    
    if result["success"]:
        inquiry_id = result["inquiry_id"]
        
        # 2. Afficher l'URL de vérification
        print(f"\n2. Demandez à l'utilisateur de visiter:")
        print(f"   {result['verification_url']}")
        
        # 3. Vérifier le statut (simulation)
        print("\n3. Vérification du statut...")
        status_result = persona.get_inquiry(inquiry_id)
        
        if status_result["success"]:
            print(f"   Statut: {status_result['data']['attributes']['status']}")
        
        # 4. Lister les inquiries
        print("\n4. Liste des dernières inquiries:")
        list_result = persona.list_inquiries(limit=5)
        
        if list_result["success"]:
            for inquiry in list_result["inquiries"]:
                print(f"   - {inquiry['id']}: {inquiry['attributes']['status']}")
    
    return result

if __name__ == "__main__":
    # Charger les variables d'environnement
    from dotenv import load_dotenv
    load_dotenv()
    
    # Vérifier la configuration
    api_key = os.getenv("PERSONA_SANDBOX_API_KEY")
    
    if not api_key or api_key == "your_sandbox_api_key_here":
        print("⚠️  ATTENTION: Configurez vos clés API dans le fichier .env")
        print("1. Créez un compte sur https://dashboard.withpersona.com")
        print("2. Accédez à Sandbox > API Keys")
        print("3. Créez une nouvelle clé API")
        print("4. Copiez-la dans votre fichier .env:")
        print("   PERSONA_SANDBOX_API_KEY=persona_sandbox_xxxxxx")
    else:
        # Lancer le test
        test_sandbox_flow()
        
        # Démarrer le serveur web pour les webhooks
        print("\n🌐 Serveur web démarré sur http://localhost:5000")
        print("   Utilisez ngrok pour exposer localhost aux webhooks Persona")
        app.run(host="0.0.0.0", port=5000, debug=True)