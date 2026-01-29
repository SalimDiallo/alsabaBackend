"""
Service Flutterwave pour Orange Money
Gère les dépôts (charges) et retraits (transfers) via mobile money
"""
import uuid
import structlog
from django.conf import settings
from typing import Dict, Optional, Any

from .base import FlutterwaveBaseService

logger = structlog.get_logger(__name__)


class FlutterwaveOrangeMoneyService(FlutterwaveBaseService):
    """
    Service Flutterwave pour Orange Money
    Gère les dépôts et retraits via mobile money
    """
    
    def __init__(self):
        super().__init__()
        # Configuration Orange Money
        self.currency = getattr(settings, 'FLUTTERWAVE_CURRENCY', 'XOF')
        self.country_code = getattr(settings, 'FLUTTERWAVE_COUNTRY_CODE', '221')  # Sénégal par défaut
        self.network = getattr(settings, 'FLUTTERWAVE_NETWORK', 'ORANGE')
        
        if not all([self.client_id, self.client_secret]):
            raise ValueError("Configuration Flutterwave incomplète pour Orange Money")
    
    def create_customer(self, email: str, first_name: str, last_name: str, 
                       phone: str, country_code: Optional[str] = None) -> str:
        """
        Crée un customer Flutterwave pour Orange Money
        
        Args:
            email: Email du client
            first_name: Prénom
            last_name: Nom
            phone: Numéro de téléphone (sans indicatif)
            country_code: Code pays (optionnel)
            
        Returns:
            str: ID du customer créé
        """
        token = self.get_access_token()
        endpoint = "/customers"
        
        json_data = {
            "name": {"first": first_name, "last": last_name},
            "phone": {"country_code": country_code or self.country_code, "number": phone},
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
            # Gestion du conflit si le customer existe déjà (Erreur 409)
            if "10409" in str(e) or "already exists" in str(e).lower():
                logger.info("flutterwave_customer_conflict_detected", email=email)
                return self.get_customer_id_by_email(email)
                
            logger.error("flutterwave_customer_creation_failed",
                        error=str(e),
                        email=email)
            raise
    
    def create_mobile_money_payment_method(self, phone: str) -> str:
        """
        Crée une méthode de paiement mobile money
        
        Args:
            phone: Numéro de téléphone Orange Money (sans indicatif)
            
        Returns:
            str: ID de la méthode de paiement
        """
        token = self.get_access_token()
        endpoint = "/payment-methods"
        
        json_data = {
            "type": "mobile_money",
            "mobile_money": {
                "country_code": self.country_code,
                "network": self.network,
                "phone_number": phone
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
    
    def charge_mobile_money(self, customer_id: str, payment_method_id: str,
                           amount: int, reference: Optional[str] = None, **kwargs) -> str:
        """
        Effectue un encaissement via Orange Money (dépôt)
        
        Args:
            customer_id: ID du customer
            payment_method_id: ID de la méthode de paiement
            amount: Montant en centimes
            reference: Référence unique (générée si None)
            
        Returns:
            str: ID du charge créé
        """
        if reference is None:
            reference = str(uuid.uuid4())
        
        token = self.get_access_token()
        endpoint = "/charges"
        
        # Validation stricte du redirect_url selon V3
        raw_redirect = kwargs.get('redirect_url') or self.redirect_url or "https://google.com"
        clean_redirect = str(raw_redirect).strip().strip('"').strip("'")
        
        is_valid, error_msg = self.validate_redirect_url(clean_redirect)
        if not is_valid:
            logger.error("invalid_redirect_url", url=clean_redirect, reason=error_msg)
            clean_redirect = "https://google.com"
            logger.warning("using_fallback_redirect_url", url=clean_redirect)

        json_data = {
            "reference": reference,
            "currency": self.currency,
            "customer_id": customer_id,
            "payment_method_id": payment_method_id,
            "amount": float(amount),  # TOUJOURS float, jamais centimes
            "redirect_url": clean_redirect
        }
        
        headers = {
            "X-Idempotency-Key": str(uuid.uuid4())
        }
        
        if self.environment == 'sandbox':
            headers["X-Scenario-Key"] = kwargs.get('scenario', 'scenario:successful')
        
        try:
            response = self._make_request("POST", endpoint, token=token,
                                         json_data=json_data, headers=headers)
            charge_id = response["data"]["id"]
            logger.info("flutterwave_charge_initiated",
                       charge_id=charge_id,
                       amount=amount,
                       reference=reference)
            return charge_id
        except Exception as e:
            logger.error("flutterwave_charge_failed", error=str(e), reference=reference)
            raise
    
    def verify_charge(self, charge_id: str) -> Dict[str, Any]:
        """
        Vérifie le statut d'un charge Orange Money
        
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
    
    def create_mobile_money_recipient(self, phone: str, first_name: str,
                                     last_name: str, country_code: Optional[str] = None) -> str:
        """
        Crée un recipient pour transfert Orange Money (retrait)
        
        Args:
            phone: Numéro Orange Money (sans indicatif)
            first_name: Prénom du destinataire
            last_name: Nom du destinataire
            country_code: Code pays (ex: 33, 221)
            
        Returns:
            str: ID du recipient
        """
        token = self.get_access_token()
        endpoint = "/transfers/recipients"
        
        # Formatage du code pays
        c_code = country_code or self.country_code
        c_code = str(c_code).replace('+', '')
        
        # Format international du numéro
        msisdn = c_code + phone
        
        json_data = {
            "type": "mobile_money",
            "mobile_money": {
                "country": c_code[-2:] if len(c_code) > 2 else "SN", # Déduction simplifiée
                "network": self.network,
                "msisdn": msisdn
            },
            "name": {"first": first_name, "last": last_name}
        }
        
        headers = {
            "X-Idempotency-Key": str(uuid.uuid4())
        }
        
        try:
            response = self._make_request("POST", endpoint, token=token,
                                         json_data=json_data, headers=headers)
            recipient_id = response["data"]["id"]
            logger.info("flutterwave_recipient_created",
                       recipient_id=recipient_id,
                       phone=phone[:3] + "****")
            return recipient_id
        except Exception as e:
            logger.error("flutterwave_recipient_creation_failed", error=str(e))
            raise
    
    def initiate_mobile_money_transfer(self, recipient_id: str, amount: int,
                                      narration: str = "Wallet withdrawal") -> str:
        """
        Initie un transfert Orange Money (retrait depuis votre compte)
        
        Args:
            recipient_id: ID du recipient
            amount: Montant en centimes
            narration: Description du transfert
            
        Returns:
            str: ID du transfert créé
        """
        token = self.get_access_token()
        endpoint = "/transfers"
        
        json_data = {
            "action": "instant",
            "reference": str(uuid.uuid4()),
            "narration": narration,
            "payment_instruction": {
                "source_currency": self.currency,
                "destination_currency": self.currency,
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
            transfer_id = response["data"]["id"]
            logger.info("flutterwave_transfer_initiated",
                       transfer_id=transfer_id,
                       amount=amount,
                       recipient_id=recipient_id)
            return transfer_id
        except Exception as e:
            logger.error("flutterwave_transfer_failed", error=str(e))
            raise
    
    def verify_transfer(self, transfer_id: str) -> Dict[str, Any]:
        """
        Vérifie le statut d'un transfert Orange Money
        
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
                       customer_name: str, country_code: Optional[str] = None,
                       customer_id: Optional[str] = None,
                       **kwargs) -> Dict[str, Any]:
        """
        Initie un dépôt complet via Orange Money (flux complet)
        
        Args:
            amount: Montant
            currency: Devise
            customer_email: Email du client
            customer_phone: Téléphone Orange Money (sans indicatif)
            customer_name: Nom complet du client
            country_code: Code pays (optionnel)
            customer_id: ID Flutterwave du client (si déjà connu)
            
        Returns:
            dict: Résultat avec reference, charge_id, status
        """
        try:
            token = self.get_access_token()
            
            # 2. Obtenir ou créer customer
            if not customer_id:
                name_parts = customer_name.split(maxsplit=1)
                first_name = name_parts[0] if name_parts else customer_name
                last_name = name_parts[1] if len(name_parts) > 1 else ""
                customer_id = self.create_customer(
                    customer_email, first_name, last_name, customer_phone, country_code=country_code)
            
            # Créer payment method
            pm_id = self.create_mobile_money_payment_method(customer_phone)
            
            # Créer charge
            charge_id = self.charge_mobile_money(
                customer_id, pm_id, int(amount * 100),
                redirect_url=kwargs.get('redirect_url')
            )
            
            return {
                "success": True,
                "reference": f"charge_{charge_id}",
                "charge_id": charge_id,
                "customer_id": customer_id,
                "status": "pending"  # À vérifier via webhook
            }
        except Exception as e:
            logger.error("flutterwave_orange_deposit_error", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "code": "deposit_failed"
            }
    
    def initiate_withdrawal(self, amount: float, currency: str,
                           recipient_phone: str, recipient_name: str,
                           country_code: Optional[str] = None) -> Dict[str, Any]:
        """
        Initie un retrait complet vers Orange Money (flux complet)
        
        Args:
            amount: Montant
            currency: Devise
            recipient_phone: Numéro Orange Money du destinataire (sans indicatif)
            recipient_name: Nom complet du destinataire
            country_code: Code pays (ex: 33, 221)
            
        Returns:
            dict: Résultat avec reference, transfer_id, status
        """
        try:
            token = self.get_access_token()
            
            # Créer recipient
            name_parts = recipient_name.split(maxsplit=1)
            first_name = name_parts[0] if name_parts else recipient_name
            last_name = name_parts[1] if len(name_parts) > 1 else ""
            recipient_id = self.create_mobile_money_recipient(
                recipient_phone, first_name, last_name, country_code=country_code)
            
            # Initier transfert
            transfer_id = self.initiate_mobile_money_transfer(
                recipient_id, int(amount * 100))
            
            return {
                "success": True,
                "reference": f"transfer_{transfer_id}",
                "transfer_id": transfer_id,
                "status": "pending"
            }
        except Exception as e:
            logger.error("flutterwave_orange_withdrawal_error", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "code": "withdrawal_failed"
            }


# Instance globale
flutterwave_orange_service = FlutterwaveOrangeMoneyService()
