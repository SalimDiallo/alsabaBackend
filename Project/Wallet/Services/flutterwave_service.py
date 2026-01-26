"""
Service principal d'intégration avec Flutterwave
Orchestre les services spécialisés pour carte et Orange Money
"""
import structlog
from django.conf import settings
from typing import Dict, Optional, Any
from .flutterwave.card import flutterwave_card_service
from .flutterwave.orange_money import flutterwave_orange_service
from .flutterwave.base import FlutterwaveBaseService

logger = structlog.get_logger(__name__)


class FlutterwaveService(FlutterwaveBaseService):
    """
    Service principal d'intégration avec Flutterwave
    Utilise les services spécialisés pour carte et Orange Money
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
                        **kwargs) -> Dict[str, Any]:
        """
        Initie un dépôt selon la méthode de paiement
        
        Args:
            amount: Montant
            currency: Devise
            payment_method: 'card' ou 'orange_money'
            customer_email: Email du client
            customer_phone: Téléphone
            customer_name: Nom du client
            card_details: Détails de la carte (pour card)
            **kwargs: Arguments supplémentaires
            
        Returns:
            dict: Résultat de l'opération
        """
        if payment_method == "card":
            if not card_details:
                return {
                    "success": False,
                    "error": "Détails de carte requis pour le paiement par carte",
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
                address=kwargs.get('address'),
                country_code=kwargs.get('country_code', '33')
            )
        elif payment_method == "orange_money":
            if not all([customer_email, customer_phone, customer_name]):
                return {
                    "success": False,
                    "error": "Informations client requises",
                    "code": "customer_info_required"
                }
            return self.orange_service.initiate_deposit(
                amount, currency, customer_email, customer_phone, customer_name
            )
        else:
            return {
                "success": False,
                "error": f"Méthode de paiement non supportée: {payment_method}",
                "code": "unsupported_payment_method"
            }
    
    def initiate_withdrawal(self, amount: float, currency: str = "EUR",
                           payment_method: str = "orange_money",
                           recipient_details: Optional[Dict] = None,
                           **kwargs) -> Dict[str, Any]:
        """
        Initie un retrait selon la méthode de paiement
        
        Args:
            amount: Montant
            currency: Devise
            payment_method: 'card' (compte bancaire) ou 'orange_money'
            recipient_details: Détails du destinataire
            **kwargs: Arguments supplémentaires
            
        Returns:
            dict: Résultat de l'opération
        """
        if payment_method == "card":
            # Retrait vers compte bancaire
            if not recipient_details:
                return {
                    "success": False,
                    "error": "Détails du destinataire requis",
                    "code": "recipient_details_required"
                }
            
            account_number = recipient_details.get("account_number")
            bank_code = recipient_details.get("bank_code")
            account_name = recipient_details.get("account_name")
            recipient_type = recipient_details.get("type", "bank_account")
            
            if not all([account_number, bank_code, account_name]):
                return {
                    "success": False,
                    "error": "Informations bancaires incomplètes (account_number, bank_code, account_name requis)",
                    "code": "incomplete_bank_details"
                }
            
            try:
                # Créer recipient
                recipient_id = self.card_service.create_bank_transfer_recipient(
                    account_number, bank_code, account_name, recipient_type)
                
                # TRANSFORMATION PRÉCISE EN CENTIMES
                from decimal import Decimal
                amount_cents = int(Decimal(str(amount)) * 100)
                
                # Initier transfert
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
                    "error": "Détails du destinataire requis (phone, name)",
                    "code": "recipient_details_required"
                }
            
            phone = recipient_details.get("phone")
            name = recipient_details.get("name")
            
            if not all([phone, name]):
                return {
                    "success": False,
                    "error": "Détails du destinataire incomplets (phone, name requis)",
                    "code": "incomplete_recipient_details"
                }
            
            return self.orange_service.initiate_withdrawal(
                amount, currency, phone, name
            )
        else:
            return {
                "success": False,
                "error": f"Méthode de paiement non supportée: {payment_method}",
                "code": "unsupported_payment_method"
            }
    
    def verify_transaction(self, transaction_id: str,
                          payment_method: str = "card") -> Dict[str, Any]:
        """
        Vérifie le statut d'une transaction (dépôt)
        
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
                    "error": f"Méthode de paiement non supportée: {payment_method}",
                    "code": "unsupported_payment_method"
                }
            
            charge_data = result.get("data", {})
            status = charge_data.get("status", "unknown")
            
            # Mapper les statuts Flutterwave vers nos statuts
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
        Vérifie le statut d'un transfert (retrait)
        
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
                    "error": f"Méthode de paiement non supportée: {payment_method}",
                    "code": "unsupported_payment_method"
                }
            
            transfer_data = result.get("data", {})
            status = transfer_data.get("status", "unknown")
            
            # Mapper les statuts Flutterwave vers nos statuts
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
        """Retourne les devises supportées selon la configuration"""
        return getattr(settings, 'FLUTTERWAVE_SUPPORTED_CURRENCIES', 
                      ['EUR', 'XOF', 'XAF', 'NGN', 'USD'])
    
    def get_supported_payment_methods(self) -> list:
        """Retourne les méthodes de paiement supportées"""
        return ['card', 'orange_money']


# Instance globale du service
flutterwave_service = FlutterwaveService()
