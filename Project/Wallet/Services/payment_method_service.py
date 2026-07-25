"""
Service to manage saved payment methods
"""
import structlog
from django.db import transaction as db_transaction
from ..models import PaymentMethod

logger = structlog.get_logger(__name__)


class PaymentMethodService:
    """
    Service for managing saved payment methods
    """
    
    @staticmethod
    def create_card_payment_method(user, label, card_number, card_expiry_month,
                                   card_expiry_year, card_cvv, is_default=False):
        """
        Creates a saved card payment method
        
        Args:
            user: Instance User
            label: Name given by the user
            card_number: Full card number
            card_expiry_month: Mois d'expiration
            card_expiry_year: Année d'expiration
            card_cvv: CVV (will not be stored)
            is_default: Set as default method
            
        Returns:
            PaymentMethod: The created method
        """
        # Clean card number
        card_number_clean = card_number.replace(' ', '').replace('-', '')
        card_last_four = card_number_clean[-4:]
        
        # Detect card brand (simplified)
        card_brand = PaymentMethodService._detect_card_brand(card_number_clean)
        
        with db_transaction.atomic():
            # If it's the default method, deactivate others
            if is_default:
                PaymentMethod.objects.filter(
                    user=user,
                    method_type='card',
                    is_default=True
                ).update(is_default=False)
            
            payment_method = PaymentMethod.objects.create(
                user=user,
                method_type='card',
                label=label,
                card_last_four=card_last_four,
                card_brand=card_brand,
                card_expiry_month=card_expiry_month,
                card_expiry_year=card_expiry_year,
                is_default=is_default
            )
            
            logger.info(
                "payment_method_created",
                user_id=str(user.id),
                method_id=str(payment_method.id),
                method_type='card',
                label=label
            )
            
            return payment_method
    
    @staticmethod
    def create_bank_account_payment_method(user, label, account_number, bank_code,
                                          account_name, bank_name=None, bank_country=None,
                                          is_default=False):
        """
        Creates a saved bank account payment method
        
        Args:
            user: Instance User
            label: Name given by the user
            account_number: Account number
            bank_code: Code de la banque
            account_name: Account owner name
            bank_name: Name of the bank (optionnel)
            bank_country: Code pays (optionnel)
            is_default: Set as default method
            
        Returns:
            PaymentMethod: The created method
        """
        # Clean account number
        account_number_clean = account_number.replace(' ', '').replace('-', '')
        account_number_last_four = account_number_clean[-4:] if len(account_number_clean) >= 4 else account_number_clean
        
        with db_transaction.atomic():
            # If it's the default method, deactivate others
            if is_default:
                PaymentMethod.objects.filter(
                    user=user,
                    method_type='bank_account',
                    is_default=True
                ).update(is_default=False)
            
            payment_method = PaymentMethod.objects.create(
                user=user,
                method_type='bank_account',
                label=label,
                account_number=account_number_clean,  # We store the full number but masked in display
                account_number_last_four=account_number_last_four,
                bank_code=bank_code,
                bank_name=bank_name,
                account_name=account_name,
                bank_country=bank_country,
                is_default=is_default
            )
            
            logger.info(
                "payment_method_created",
                user_id=str(user.id),
                method_id=str(payment_method.id),
                method_type='bank_account',
                label=label
            )
            
            return payment_method
    
    @staticmethod
    def create_orange_money_payment_method(user, label, orange_money_number, is_default=False):
        """
        Creates a saved Orange Money payment method
        
        Args:
            user: Instance User
            label: Name given by the user
            orange_money_number: Orange Money number
            is_default: Set as default method
            
        Returns:
            PaymentMethod: The created method
        """
        # Clean the number
        phone_clean = orange_money_number.replace(' ', '').replace('+', '')
        
        with db_transaction.atomic():
            # If it's the default method, deactivate others
            if is_default:
                PaymentMethod.objects.filter(
                    user=user,
                    method_type='orange_money',
                    is_default=True
                ).update(is_default=False)
            
            payment_method = PaymentMethod.objects.create(
                user=user,
                method_type='orange_money',
                label=label,
                orange_money_number=phone_clean,
                is_default=is_default
            )
            
            logger.info(
                "payment_method_created",
                user_id=str(user.id),
                method_id=str(payment_method.id),
                method_type='orange_money',
                label=label
            )
            
            return payment_method
    
    @staticmethod
    def get_payment_method(user, payment_method_id, method_type=None):
        """
        Retrieves a payment method for a user
        
        Args:
            user: Instance User
            payment_method_id: Method UUID
            method_type: Expected method type (optional, for validation)
            
        Returns:
            PaymentMethod: The found method
            
        Raises:
            PaymentMethod.DoesNotExist: If the method does not exist
            ValueError: Si le type ne correspond pas
        """
        try:
            payment_method = PaymentMethod.objects.get(
                id=payment_method_id,
                user=user,
                is_active=True
            )
            
            if method_type and payment_method.method_type != method_type:
                raise ValueError(f"Incorrect method type: expected {method_type}, got {payment_method.method_type}")
            
            return payment_method
        except PaymentMethod.DoesNotExist:
            logger.warning(
                "payment_method_not_found",
                user_id=str(user.id),
                payment_method_id=str(payment_method_id)
            )
            raise
    
    @staticmethod
    def get_default_payment_method(user, method_type):
        """
        Retrieves the default payment method for a given type
        
        Args:
            user: Instance User
            method_type: Method type ('card', 'bank_account', 'orange_money')
            
        Returns:
            PaymentMethod ou None
        """
        try:
            return PaymentMethod.objects.get(
                user=user,
                method_type=method_type,
                is_default=True,
                is_active=True
            )
        except PaymentMethod.DoesNotExist:
            return None
    
    @staticmethod
    def list_payment_methods(user, method_type=None, active_only=True):
        """
        Lists a user's payment methods
        
        Args:
            user: Instance User
            method_type: Filtrer par type (optionnel)
            active_only: Return only active methods
            
        Returns:
            QuerySet: The payment methods
        """
        queryset = PaymentMethod.objects.filter(user=user)
        
        if method_type:
            queryset = queryset.filter(method_type=method_type)
        
        if active_only:
            queryset = queryset.filter(is_active=True)
        
        return queryset.order_by('-is_default', '-last_used_at', '-created_at')
    
    @staticmethod
    def _detect_card_brand(card_number):
        """
        Detects the card brand from the number
        
        Args:
            card_number: Card number (no spaces)
            
        Returns:
            str: Card brand (Visa, Mastercard, etc.)
        """
        if not card_number or not card_number.isdigit():
            return None
        
        # Visa starts with 4
        if card_number.startswith('4'):
            return 'Visa'
        # Mastercard starts with 5 or 2
        elif card_number.startswith('5') or (card_number.startswith('2') and len(card_number) == 16):
            return 'Mastercard'
        # American Express starts with 34 or 37
        elif card_number.startswith('34') or card_number.startswith('37'):
            return 'American Express'
        # Discover starts with 6
        elif card_number.startswith('6'):
            return 'Discover'
        else:
            return 'Unknown'
    
    @staticmethod
    def mask_account_number(account_number):
        """
        Masks an account number for display
        
        Args:
            account_number: Full account number
            
        Returns:
            str: Masked number (e.g., ****1234)
        """
        if not account_number or len(account_number) < 4:
            return "****"
        return "****" + account_number[-4:]


# Instance globale
payment_method_service = PaymentMethodService()
