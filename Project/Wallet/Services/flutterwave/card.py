"""
Service Flutterwave pour les paiements par carte
Basé sur l'API Flutterwave avec OAuth2 et encryption AES
"""
import uuid
import structlog
from django.conf import settings
from typing import Dict, Optional, Any
from Wallet.utils.encryption import EncryptionUtils
from .base import FlutterwaveBaseService

logger = structlog.get_logger(__name__)


class FlutterwaveCardService(FlutterwaveBaseService):
    """
    Service Flutterwave pour les paiements par carte
    Gère les dépôts (charges) et retraits (transfers vers compte bancaire)
    """
    
    def __init__(self):
        super().__init__()
        # Devise par défaut selon l'environnement
        self.currency = getattr(settings, 'FLUTTERWAVE_CURRENCY', 'EUR')
        
        if not all([self.client_id, self.client_secret, self.encryption_key]):
            raise ValueError("Configuration Flutterwave incomplète pour les cartes")
    
    def create_customer(self, email: str, first_name: str, last_name: str, 
                       phone: str, country_code: str = "33", 
                       address: Optional[Dict] = None) -> str:
        """
        Crée un customer Flutterwave
        
        Args:
            email: Email du client
            first_name: Prénom
            last_name: Nom
            phone: Numéro de téléphone (sans indicatif)
            country_code: Code pays (ex: "33" pour France)
            address: Adresse complète (optionnel)
            
        Returns:
            str: ID du customer créé
        """
        token = self.get_access_token()
        endpoint = "/customers"
        
        # Adresse par défaut si non fournie
        if not address:
            address = {
                "city": "Unknown",
                "country": country_code[-2:] if len(country_code) > 2 else "FR",
                "line1": "Address not provided",
                "postal_code": "00000",
                "state": "Unknown"
            }
        
        json_data = {
            "address": address,
            "name": {"first": first_name, "last": last_name},
            "phone": {"country_code": country_code, "number": phone},
            "email": email
        }
        
        headers = {
            "X-Idempotency-Key": str(uuid.uuid4())
        }
        
        try:
            response = self._make_request("POST", endpoint, token=token, 
                                         json_data=json_data, headers=headers)
            customer_id = response["data"]["id"]
            logger.info("flutterwave_customer_created", 
                       customer_id=customer_id,
                       email=email)
            return customer_id
        except Exception as e:
            logger.error("flutterwave_customer_creation_failed",
                        error=str(e),
                        email=email)
            raise
    
    def create_card_payment_method(self, card_number: str, exp_month: str, 
                                  exp_year: str, cvv: str) -> str:
        """
        Crée une méthode de paiement carte avec encryption
        
        Args:
            card_number: Numéro de carte
            exp_month: Mois d'expiration (format "MM")
            exp_year: Année d'expiration (format "YY")
            cvv: Code CVV
            
        Returns:
            str: ID de la méthode de paiement
        """
        token = self.get_access_token()
        endpoint = "/payment-methods"
        
        # Encryption AES-256-GCM
        nonce_bytes = EncryptionUtils.generate_nonce()
        enc_number, nonce_b64 = EncryptionUtils.encrypt_aes(
            card_number, self.encryption_key, nonce_bytes)
        enc_month, _ = EncryptionUtils.encrypt_aes(
            exp_month, self.encryption_key, nonce_bytes)
        enc_year, _ = EncryptionUtils.encrypt_aes(
            exp_year, self.encryption_key, nonce_bytes)
        enc_cvv, _ = EncryptionUtils.encrypt_aes(
            cvv, self.encryption_key, nonce_bytes)
        
        json_data = {
            "type": "card",
            "card": {
                "encrypted_card_number": enc_number,
                "encrypted_expiry_month": enc_month,
                "encrypted_expiry_year": enc_year,
                "encrypted_cvv": enc_cvv,
                "nonce": nonce_b64
            }
        }
        
        headers = {
            "X-Idempotency-Key": str(uuid.uuid4())
        }
        
        try:
            response = self._make_request("POST", endpoint, token=token,
                                         json_data=json_data, headers=headers)
            pm_id = response["data"]["id"]
            logger.info("flutterwave_payment_method_created", pm_id=pm_id)
            return pm_id
        except Exception as e:
            logger.error("flutterwave_payment_method_creation_failed", error=str(e))
            raise
    
    def charge_card(self, customer_id: str, payment_method_id: str, 
                   amount: int, reference: Optional[str] = None,
                   currency: Optional[str] = None,
                   meta: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Effectue un paiement par carte (charge)
        
        Args:
            customer_id: ID du customer
            payment_method_id: ID de la méthode de paiement
            amount: Montant en centimes
            reference: Référence unique (générée si None)
            currency: Devise (utilise self.currency si None)
            meta: Métadonnées additionnelles
            
        Returns:
            dict: Réponse de l'API avec les détails du charge
        """
        if reference is None:
            reference = str(uuid.uuid4())
        
        token = self.get_access_token()
        endpoint = "/charges"
        
        json_data = {
            "reference": reference,
            "currency": currency or self.currency,
            "customer_id": customer_id,
            "payment_method_id": payment_method_id,
            "redirect_url": self.redirect_url,
            "amount": amount,
            "meta": meta or {"source": "wallet_deposit"}
        }
        
        headers = {
            "X-Idempotency-Key": str(uuid.uuid4())
        }
        
        # Ajouter X-Scenario-Key pour sandbox uniquement
        if self.environment == 'sandbox':
            headers["X-Scenario-Key"] = "scenario:auth_3ds&issuer:approved"
        
        try:
            response = self._make_request("POST", endpoint, token=token,
                                         json_data=json_data, headers=headers)
            logger.info("flutterwave_charge_initiated",
                       charge_id=response["data"]["id"],
                       amount=amount,
                       reference=reference)
            return response
        except Exception as e:
            logger.error("flutterwave_charge_failed", error=str(e), reference=reference)
            raise
    
    def authorize_with_pin(self, charge_id: str, pin: str = "12345") -> Dict[str, Any]:
        """
        Autorise un charge avec PIN si requis
        
        Args:
            charge_id: ID du charge
            pin: PIN de la carte (défaut pour sandbox)
            
        Returns:
            dict: Réponse de l'API
        """
        token = self.get_access_token()
        endpoint = f"/charges/{charge_id}"
        
        # Encryption du PIN
        nonce_bytes = EncryptionUtils.generate_nonce()
        enc_pin, pin_nonce_b64 = EncryptionUtils.encrypt_aes(
            pin, self.encryption_key, nonce_bytes)
        
        json_data = {
            "authorization": {
                "type": "pin",
                "pin": {
                    "nonce": pin_nonce_b64,
                    "encrypted_pin": enc_pin
                }
            }
        }
        
        headers = {}
        if self.environment == 'sandbox':
            headers["X-Scenario-Key"] = "scenario:auth_3ds&issuer:approved"
        
        try:
            response = self._make_request("PUT", endpoint, token=token,
                                         json_data=json_data, headers=headers)
            logger.info("flutterwave_pin_authorization_success", charge_id=charge_id)
            return response
        except Exception as e:
            logger.error("flutterwave_pin_authorization_failed",
                        error=str(e),
                        charge_id=charge_id)
            raise
    
    def verify_charge(self, charge_id: str) -> Dict[str, Any]:
        """
        Vérifie le statut d'un charge
        
        Args:
            charge_id: ID du charge
            
        Returns:
            dict: Détails du charge avec statut
        """
        token = self.get_access_token()
        endpoint = f"/charges/{charge_id}"
        
        try:
            response = self._make_request("GET", endpoint, token=token)
            return response
        except Exception as e:
            logger.error("flutterwave_charge_verification_failed",
                        error=str(e),
                        charge_id=charge_id)
            raise
    
    def create_bank_transfer_recipient(self, account_number: str, bank_code: str,
                                      account_name: Optional[str] = None,
                                      type_: str = "bank_account") -> str:
        """
        Crée un recipient pour transfert bancaire (retrait)
        
        Args:
            account_number: Numéro de compte bancaire
            bank_code: Code de la banque
            account_name: Nom du titulaire du compte
            type_: Type de recipient (bank_account, bank_ngn, bank_ma, etc.)
            
        Returns:
            str: ID du recipient
        """
        token = self.get_access_token()
        endpoint = "/transfers/recipients"
        
        json_data = {
            "type": type_,
            "bank": {
                "account_number": account_number,
                "code": bank_code
            }
        }
        
        if account_name:
            # Séparer le nom en first/last si possible
            name_parts = account_name.split(maxsplit=1)
            json_data["name"] = {
                "first": name_parts[0] if name_parts else account_name,
                "last": name_parts[1] if len(name_parts) > 1 else ""
            }
        
        headers = {
            "X-Idempotency-Key": str(uuid.uuid4())
        }
        
        try:
            response = self._make_request("POST", endpoint, token=token,
                                         json_data=json_data, headers=headers)
            recipient_id = response["data"]["id"]
            logger.info("flutterwave_bank_recipient_created",
                       recipient_id=recipient_id,
                       account_number=account_number[:4] + "****")
            return recipient_id
        except Exception as e:
            logger.error("flutterwave_bank_recipient_creation_failed", error=str(e))
            raise
    
    def initiate_bank_transfer(self, recipient_id: str, amount: int,
                               narration: str = "Wallet withdrawal",
                               currency: Optional[str] = None) -> Dict[str, Any]:
        """
        Initie un transfert bancaire (retrait depuis votre compte)
        
        Args:
            recipient_id: ID du recipient
            amount: Montant en centimes
            narration: Description du transfert
            currency: Devise (utilise self.currency si None)
            
        Returns:
            dict: Réponse de l'API avec les détails du transfert
        """
        token = self.get_access_token()
        endpoint = "/transfers"
        
        json_data = {
            "action": "instant",
            "reference": str(uuid.uuid4()),
            "narration": narration,
            "payment_instruction": {
                "source_currency": currency or self.currency,
                "destination_currency": currency or self.currency,
                "amount": {
                    "applies_to": "destination_currency",
                    "value": amount
                },
                "recipient_id": recipient_id
            }
        }
        
        headers = {
            "X-Idempotency-Key": str(uuid.uuid4())
        }
        
        if self.environment == 'sandbox':
            headers["X-Scenario-Key"] = "scenario:successful"
        
        try:
            response = self._make_request("POST", endpoint, token=token,
                                         json_data=json_data, headers=headers)
            logger.info("flutterwave_bank_transfer_initiated",
                       transfer_id=response["data"]["id"],
                       amount=amount,
                       recipient_id=recipient_id)
            return response
        except Exception as e:
            logger.error("flutterwave_bank_transfer_failed", error=str(e))
            raise
    
    def verify_transfer(self, transfer_id: str) -> Dict[str, Any]:
        """
        Vérifie le statut d'un transfert
        
        Args:
            transfer_id: ID du transfert
            
        Returns:
            dict: Détails du transfert avec statut
        """
        token = self.get_access_token()
        endpoint = f"/transfers/{transfer_id}"
        
        try:
            response = self._make_request("GET", endpoint, token=token)
            return response
        except Exception as e:
            logger.error("flutterwave_transfer_verification_failed",
                        error=str(e),
                        transfer_id=transfer_id)
            raise
    
    def initiate_deposit(self, amount: float, currency: str,
                        customer_email: str, customer_phone: str,
                        customer_name: str, card_details: Dict[str, str],
                        address: Optional[Dict] = None,
                        country_code: str = "33") -> Dict[str, Any]:
        """
        Initie un dépôt complet par carte (flux complet)
        
        Args:
            amount: Montant
            currency: Devise
            customer_email: Email du client
            customer_phone: Téléphone du client
            customer_name: Nom complet du client
            card_details: Détails de la carte (number, exp_month, exp_year, cvv)
            country_code: Code pays
            
        Returns:
            dict: Résultat avec reference, charge_id, status, payment_link
        """
        try:
            # 1. Obtenir token
            token = self.get_access_token()
            
            # 2. Créer customer
            name_parts = customer_name.split(maxsplit=1)
            first_name = name_parts[0] if name_parts else customer_name
            last_name = name_parts[1] if len(name_parts) > 1 else ""
            customer_id = self.create_customer(
                customer_email, first_name, last_name, customer_phone, 
                country_code, address=address)
            
            # 3. Créer payment method
            pm_id = self.create_card_payment_method(
                card_details['number'],
                card_details['exp_month'],
                card_details['exp_year'],
                card_details['cvv']
            )
            
            # 4. Créer charge
            charge = self.charge_card(
                customer_id, pm_id, int(amount * 100),
                currency=currency
            )
            
            charge_data = charge["data"]
            charge_id = charge_data["id"]
            
            # 5. Vérifier si PIN requis
            if "next_action" in charge_data:
                next_action = charge_data["next_action"]
                if next_action.get("type") == "authorize":
                    logger.info("pin_authorization_required", charge_id=charge_id)
                    # Pour sandbox, on autorise automatiquement
                    if self.environment == 'sandbox':
                        self.authorize_with_pin(charge_id)
                    # En production, l'utilisateur devra autoriser via 3DS
            
            return {
                "success": True,
                "reference": charge_data["reference"],
                "charge_id": charge_id,
                "status": charge_data.get("status", "pending"),
                "payment_link": charge_data.get("authorization", {}).get("redirect_url"),
                "next_action": charge_data.get("next_action")
            }
        except Exception as e:
            logger.error("flutterwave_card_deposit_error", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "code": "deposit_failed"
            }


# Instance globale
flutterwave_card_service = FlutterwaveCardService()
