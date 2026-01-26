"""
Service pour gérer les méthodes de paiement sauvegardées
"""
import structlog
from django.db import transaction as db_transaction
from django.utils import timezone
from ..models import PaymentMethod
from django.conf import settings

logger = structlog.get_logger(__name__)


class PaymentMethodService:
    """
    Service de gestion des méthodes de paiement sauvegardées
    """
    
    @staticmethod
    def create_card_payment_method(user, label, card_number, card_expiry_month,
                                   card_expiry_year, card_cvv, is_default=False):
        """
        Crée une méthode de paiement carte sauvegardée
        
        Args:
            user: Instance User
            label: Nom donné par l'utilisateur
            card_number: Numéro de carte complet
            card_expiry_month: Mois d'expiration
            card_expiry_year: Année d'expiration
            card_cvv: CVV (ne sera pas stocké)
            is_default: Définir comme méthode par défaut
            
        Returns:
            PaymentMethod: La méthode créée
        """
        # Nettoyer le numéro de carte
        card_number_clean = card_number.replace(' ', '').replace('-', '')
        card_last_four = card_number_clean[-4:]
        
        # Détecter la marque de la carte (simplifié)
        card_brand = PaymentMethodService._detect_card_brand(card_number_clean)
        
        with db_transaction.atomic():
            # Si c'est la méthode par défaut, désactiver les autres
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
        Crée une méthode de paiement compte bancaire sauvegardée
        
        Args:
            user: Instance User
            label: Nom donné par l'utilisateur
            account_number: Numéro de compte
            bank_code: Code de la banque
            account_name: Nom du titulaire
            bank_name: Nom de la banque (optionnel)
            bank_country: Code pays (optionnel)
            is_default: Définir comme méthode par défaut
            
        Returns:
            PaymentMethod: La méthode créée
        """
        # Nettoyer le numéro de compte
        account_number_clean = account_number.replace(' ', '').replace('-', '')
        account_number_last_four = account_number_clean[-4:] if len(account_number_clean) >= 4 else account_number_clean
        
        with db_transaction.atomic():
            # Si c'est la méthode par défaut, désactiver les autres
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
                account_number=account_number_clean,  # On stocke le numéro complet mais masqué dans l'affichage
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
        Crée une méthode de paiement Orange Money sauvegardée
        
        Args:
            user: Instance User
            label: Nom donné par l'utilisateur
            orange_money_number: Numéro Orange Money
            is_default: Définir comme méthode par défaut
            
        Returns:
            PaymentMethod: La méthode créée
        """
        # Nettoyer le numéro
        phone_clean = orange_money_number.replace(' ', '').replace('+', '')
        
        with db_transaction.atomic():
            # Si c'est la méthode par défaut, désactiver les autres
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
        Récupère une méthode de paiement pour un utilisateur
        
        Args:
            user: Instance User
            payment_method_id: UUID de la méthode
            method_type: Type de méthode attendu (optionnel, pour validation)
            
        Returns:
            PaymentMethod: La méthode trouvée
            
        Raises:
            PaymentMethod.DoesNotExist: Si la méthode n'existe pas
            ValueError: Si le type ne correspond pas
        """
        try:
            payment_method = PaymentMethod.objects.get(
                id=payment_method_id,
                user=user,
                is_active=True
            )
            
            if method_type and payment_method.method_type != method_type:
                raise ValueError(f"Type de méthode incorrect: attendu {method_type}, obtenu {payment_method.method_type}")
            
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
        Récupère la méthode de paiement par défaut pour un type donné
        
        Args:
            user: Instance User
            method_type: Type de méthode ('card', 'bank_account', 'orange_money')
            
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
        Liste les méthodes de paiement d'un utilisateur
        
        Args:
            user: Instance User
            method_type: Filtrer par type (optionnel)
            active_only: Retourner uniquement les méthodes actives
            
        Returns:
            QuerySet: Les méthodes de paiement
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
        Détecte la marque de la carte à partir du numéro
        
        Args:
            card_number: Numéro de carte (sans espaces)
            
        Returns:
            str: Marque de la carte (Visa, Mastercard, etc.)
        """
        if not card_number or not card_number.isdigit():
            return None
        
        # Visa commence par 4
        if card_number.startswith('4'):
            return 'Visa'
        # Mastercard commence par 5 ou 2
        elif card_number.startswith('5') or (card_number.startswith('2') and len(card_number) == 16):
            return 'Mastercard'
        # American Express commence par 34 ou 37
        elif card_number.startswith('34') or card_number.startswith('37'):
            return 'American Express'
        # Discover commence par 6
        elif card_number.startswith('6'):
            return 'Discover'
        else:
            return 'Unknown'
    
    @staticmethod
    def mask_account_number(account_number):
        """
        Masque un numéro de compte pour l'affichage
        
        Args:
            account_number: Numéro de compte complet
            
        Returns:
            str: Numéro masqué (ex: ****1234)
        """
        if not account_number or len(account_number) < 4:
            return "****"
        return "****" + account_number[-4:]


# Instance globale
payment_method_service = PaymentMethodService()
