"""
Main Flutterwave integration service
Orchestrates specialized services for card and Orange Money
"""
import structlog
import hmac
import hashlib
from django.conf import settings
from typing import Dict, Optional, Any
from .flutterwave.card import flutterwave_card_service
from .flutterwave.orange_money import flutterwave_orange_service
from .flutterwave.base import FlutterwaveBaseService

logger = structlog.get_logger(__name__)


class FlutterwaveService(FlutterwaveBaseService):
    """
    Main Flutterwave integration service
    Uses specialized services for card and Orange Money
    """
    
    def __init__(self):
        super().__init__()
        self.card_service = flutterwave_card_service
        self.orange_service = flutterwave_orange_service
    
    def initiate_deposit(self, amount: float, currency: str = "EUR",
                        payment_method: str = "card",
                        customer_email: Optional[str] = None,
                        customer_phone: Optional[str] = None,
                        customer_name: Optional[str] = None,
                        card_details: Optional[Dict] = None,
                        card_token: Optional[str] = None,
                        **kwargs) -> Dict[str, Any]:
        """
        Initiates a deposit according to the payment method
        
        Args:
            amount: Montant
            currency: Devise
            payment_method: 'card' ou 'orange_money'
            customer_email: Email du client
            customer_phone: Phone
            customer_name: Nom du client
            card_details: Card details (for card)
            card_token: Card token (for tokenized card)
            **kwargs: Arguments supplémentaires
            
        Returns:
            dict: Operation result
        """
        if payment_method == "card":
            if not card_details and not card_token:
                return {
                    "success": False,
                    "error": "Card details or token required for card payment",
                    "code": "card_details_required"
                }
            if not all([customer_email, customer_phone, customer_name]):
                return {
                    "success": False,
                    "error": "Informations client requises",
                    "code": "customer_info_required"
                }
            return self.card_service.initiate_deposit(
                amount, currency, customer_email, customer_phone,
                customer_name, card_details,
                card_token=card_token,
                address=kwargs.get('address'),
                country_code=kwargs.get('country_code', '33'),
                customer_id=kwargs.get('customer_id'),
                redirect_url=kwargs.get('redirect_url')
            )
        elif payment_method == "orange_money":
            if not all([customer_email, customer_phone, customer_name]):
                return {
                    "success": False,
                    "error": "Informations client requises",
                    "code": "customer_info_required"
                }
            return self.orange_service.initiate_deposit(
                amount, currency, customer_email, customer_phone, 
                customer_name, country_code=kwargs.get('country_code'),
                customer_id=kwargs.get('customer_id'),
                redirect_url=kwargs.get('redirect_url')
            )
        else:
            return {
                "success": False,
                "error": f"Unsupported payment method: {payment_method}",
                "code": "unsupported_payment_method"
            }
    
    def initiate_withdrawal(self, amount: float, currency: str = "EUR",
                           payment_method: str = "orange_money",
                           recipient_details: Optional[Dict] = None,
                           **kwargs) -> Dict[str, Any]:
        """
        Initiates a withdrawal according to the payment method
        
        Args:
            amount: Montant
            currency: Devise
            payment_method: 'card' (compte bancaire) ou 'orange_money'
            recipient_details: Recipient details
            **kwargs: Arguments supplémentaires
            
        Returns:
            dict: Operation result
        """
        if payment_method == "card":
            # Withdrawal to bank account
            if not recipient_details:
                return {
                    "success": False,
                    "error": "Recipient details required",
                    "code": "recipient_details_required"
                }
            
            account_number = recipient_details.get("account_number")
            bank_code = recipient_details.get("bank_code")
            account_name = recipient_details.get("account_name")
            recipient_type = recipient_details.get("type", "bank_account")
            
            if not all([account_number, bank_code, account_name]):
                return {
                    "success": False,
                    "error": "Incomplete bank information (account_number, bank_code, account_name required)",
                    "code": "incomplete_bank_details"
                }
            
            try:
                # Create recipient
                recipient_id = self.card_service.create_bank_transfer_recipient(
                    account_number, bank_code, account_name, recipient_type)
                
                # PRECISE TRANSFORMATION TO CENTS
                from decimal import Decimal
                amount_cents = int(Decimal(str(amount)) * 100)
                
                # Initiate transfer
                transfer_result = self.card_service.initiate_bank_transfer(
                    recipient_id, amount_cents, 
                    narration=kwargs.get("narration", "Wallet withdrawal"),
                    currency=currency)
                
                return {
                    "success": True,
                    "reference": transfer_result["data"].get("reference"),
                    "transfer_id": transfer_result["data"]["id"],
                    "status": transfer_result["data"].get("status", "pending")
                }
            except Exception as e:
                logger.error("flutterwave_card_withdrawal_error", error=str(e))
                return {
                    "success": False,
                    "error": str(e),
                    "code": "withdrawal_failed"
                }
                
        elif payment_method == "orange_money":
            if not recipient_details:
                return {
                    "success": False,
                    "error": "Recipient details required (phone, name)",
                    "code": "recipient_details_required"
                }
            
            phone = recipient_details.get("phone")
            name = recipient_details.get("name")
            
            if not all([phone, name]):
                return {
                    "success": False,
                    "error": "Incomplete recipient details (phone, name required)",
                    "code": "incomplete_recipient_details"
                }
            
            return self.orange_service.initiate_withdrawal(
                amount, currency, phone, name,
                country_code=recipient_details.get("country_code")
            )
        else:
            return {
                "success": False,
                "error": f"Unsupported payment method: {payment_method}",
                "code": "unsupported_payment_method"
            }
    
    def verify_transaction(self, transaction_id: str,
                          payment_method: str = "card") -> Dict[str, Any]:
        """
        Verifies the status of a transaction (deposit)
        
        Args:
            transaction_id: ID de la transaction Flutterwave (charge_id)
            payment_method: Méthode de paiement utilisée
            
        Returns:
            dict: Statut de la transaction
        """
        try:
            if payment_method == "card":
                result = self.card_service.verify_charge(transaction_id)
            elif payment_method == "orange_money":
                result = self.orange_service.verify_charge(transaction_id)
            else:
                return {
                    "success": False,
                    "error": f"Unsupported payment method: {payment_method}",
                    "code": "unsupported_payment_method"
                }
            
            charge_data = result.get("data", {})
            status = charge_data.get("status", "unknown")
            
            # Map Flutterwave statuses to our statuses
            status_mapping = {
                "successful": "completed",
                "pending": "pending",
                "failed": "failed",
                "cancelled": "cancelled"
            }
            
            return {
                "success": True,
                "status": status_mapping.get(status, status),
                "flutterwave_status": status,
                "transaction_id": transaction_id,
                "data": charge_data
            }
        except Exception as e:
            logger.error("flutterwave_transaction_verification_error",
                        error=str(e),
                        transaction_id=transaction_id)
            return {
                "success": False,
                "error": str(e),
                "code": "verification_failed"
            }
    
    def verify_transfer(self, transfer_id: str,
                       payment_method: str = "orange_money") -> Dict[str, Any]:
        """
        Verifies the status of a transfer (withdrawal)
        
        Args:
            transfer_id: ID du transfert Flutterwave
            payment_method: Méthode de paiement utilisée
            
        Returns:
            dict: Statut du transfert
        """
        try:
            if payment_method == "card":
                result = self.card_service.verify_transfer(transfer_id)
            elif payment_method == "orange_money":
                result = self.orange_service.verify_transfer(transfer_id)
            else:
                return {
                    "success": False,
                    "error": f"Unsupported payment method: {payment_method}",
                    "code": "unsupported_payment_method"
                }
            
            transfer_data = result.get("data", {})
            status = transfer_data.get("status", "unknown")
            
            # Map Flutterwave statuses to our statuses
            status_mapping = {
                "successful": "completed",
                "pending": "pending",
                "failed": "failed",
                "cancelled": "cancelled"
            }
            
            return {
                "success": True,
                "status": status_mapping.get(status, status),
                "flutterwave_status": status,
                "transfer_id": transfer_id,
                "data": transfer_data
            }
        except Exception as e:
            logger.error("flutterwave_transfer_verification_error",
                        error=str(e),
                        transfer_id=transfer_id)
            return {
                "success": False,
                "error": str(e),
                "code": "verification_failed"
            }
    
    def get_supported_currencies(self) -> list:
        """Returns supported currencies according to configuration"""
        return getattr(settings, 'FLUTTERWAVE_SUPPORTED_CURRENCIES', 
                      ['EUR', 'XOF', 'XAF', 'NGN', 'USD'])
    
    def get_supported_payment_methods(self) -> list:
        """Returns supported payment methods"""
        return ['card', 'orange_money']
    
    @staticmethod
    def verify_webhook_signature(payload: str, signature: str) -> bool:
        """
        Verifies the HMAC signature of a Flutterwave webhook
        
        Args:
            payload: Corps de la requête (string JSON)
            signature: Header 'verif-hash'
        
        Returns:
            bool: True si signature valide
        """
        secret = settings.FLUTTERWAVE_WEBHOOK_SECRET
        if not secret:
            logger.error("flutterwave_webhook_secret_missing")
            return False
        
        try:
            expected_signature = hmac.new(
                secret.encode('utf-8'),
                payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # Use compare_digest to avoid timing attacks
            return hmac.compare_digest(expected_signature, signature)
        except Exception as e:
            logger.error("flutterwave_signature_verification_error", error=str(e))
            return False


# Instance globale du service
flutterwave_service = FlutterwaveService()
