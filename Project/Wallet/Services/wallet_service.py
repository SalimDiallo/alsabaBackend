"""
Service principal de gestion des wallets
Contient la logique métier pour les opérations de wallet
"""
import uuid
from decimal import Decimal
from typing import Dict, Any, Optional, List, Tuple
import structlog

from django.db import transaction as db_transaction
from django.utils import timezone

from ..models import Wallet, Transaction, Currency
from ..Utils.currency_utils import (
    get_currency_by_country_code,
    get_currency_info,
    get_currency_name,
    get_currency_symbol,
    format_amount,
)
from ..exceptions import (
    WalletError,
    WalletNotFoundError,
    WalletInactiveError,
    InsufficientFundsError,
    InvalidAmountError,
    AmountTooSmallError,
    AmountTooLargeError,
    TransactionError,
    KYCRequiredError,
)

logger = structlog.get_logger(__name__)


class WalletService:
    """
    Service pour gérer toutes les opérations sur les wallets
    Thread-safe avec transactions atomiques
    """
    
    # ============================================================================
    # CRÉATION ET RÉCUPÉRATION DE WALLETS
    # ============================================================================
    
    @staticmethod
    def create_wallet_for_user(user) -> Wallet:
        """
        Crée un wallet pour un utilisateur après validation OTP
        
        Args:
            user: Instance du modèle User
        
        Returns:
            Wallet créé
        
        Raises:
            WalletError: Si la création échoue
        """
        logger.info(
            "create_wallet_for_user_started",
            user_id=str(user.id),
            country_code=user.country_code,
            phone_verified=user.phone_verified
        )
        
        # Vérifier que le téléphone est vérifié
        if not user.phone_verified:
            raise WalletError(
                message="Le téléphone doit être vérifié pour créer un wallet",
                code="phone_not_verified"
            )
        
        # Vérifier si un wallet existe déjà
        existing_wallet = Wallet.objects.filter(user=user, is_active=True).first()
        if existing_wallet:
            logger.warning(
                "wallet_already_exists",
                user_id=str(user.id),
                wallet_id=str(existing_wallet.id)
            )
            return existing_wallet
        
        try:
            # Déterminer la devise basée sur le pays
            currency_code = get_currency_by_country_code(user.country_code)
            
            # Récupérer ou créer la devise
            currency, created = WalletService._get_or_create_currency(currency_code)
            
            # Créer le wallet
            wallet = Wallet.objects.create(
                user=user,
                currency=currency,
                balance=Decimal('0'),
                available_balance=Decimal('0'),
                is_active=True,
                last_activity=timezone.now()
            )
            
            logger.info(
                "wallet_created_successfully",
                user_id=str(user.id),
                wallet_id=str(wallet.id),
                currency_code=currency_code,
                currency_created=created
            )
            
            return wallet
            
        except Exception as e:
            logger.error(
                "wallet_creation_failed",
                user_id=str(user.id),
                error=str(e),
                exc_info=True
            )
            raise WalletError(
                message=f"Erreur lors de la création du wallet: {str(e)}",
                code="wallet_creation_failed"
            )
    
    @staticmethod
    def get_user_wallet(user) -> Optional[Wallet]:
        """
        Récupère le wallet actif d'un utilisateur
        
        Args:
            user: Instance du modèle User
        
        Returns:
            Wallet ou None si non trouvé
        """
        try:
            return Wallet.objects.get(user=user, is_active=True)
        except Wallet.DoesNotExist:
            logger.debug("wallet_not_found", user_id=str(user.id))
            return None
        except Wallet.MultipleObjectsReturned:
            # Cas anormal: plusieurs wallets actifs
            logger.error(
                "multiple_active_wallets",
                user_id=str(user.id)
            )
            # Retourner le premier par sécurité
            return Wallet.objects.filter(user=user, is_active=True).first()
    
    @staticmethod
    def get_wallet_by_id(wallet_id: uuid.UUID, user=None) -> Wallet:
        """
        Récupère un wallet par son ID avec vérification de propriété
        
        Args:
            wallet_id: ID du wallet
            user: Utilisateur propriétaire (optionnel pour vérification)
        
        Returns:
            Wallet
        
        Raises:
            WalletNotFoundError: Si le wallet n'existe pas
            WalletInactiveError: Si le wallet est inactif
        """
        try:
            wallet = Wallet.objects.get(id=wallet_id)
            
            # Vérifier que le wallet est actif
            if not wallet.is_active:
                raise WalletInactiveError(wallet_id=str(wallet_id))
            
            # Vérifier la propriété si user fourni
            if user and wallet.user != user:
                logger.warning(
                    "wallet_access_denied",
                    user_id=str(user.id),
                    wallet_id=str(wallet_id),
                    wallet_owner_id=str(wallet.user.id)
                )
                raise WalletNotFoundError(wallet_id=str(wallet_id))
            
            return wallet
            
        except Wallet.DoesNotExist:
            raise WalletNotFoundError(wallet_id=str(wallet_id))
    
    # ============================================================================
    # OPÉRATIONS SUR LES SOLDES (CORRIGÉ - SANS F())
    # ============================================================================
    
    @staticmethod
    @db_transaction.atomic
    def credit_wallet(
        wallet: Wallet,
        amount: Decimal,
        transaction_type: str = 'DEPOSIT',
        reference: Optional[str] = None,
        description: str = '',
        payment_method: str = '',
        fee: Decimal = Decimal('0'),
        external_reference: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Transaction:
        """
        Crédite un wallet de manière atomique (CORRIGÉ)
        
        Args:
            wallet: Wallet à créditer
            amount: Montant à créditer
            transaction_type: Type de transaction
            reference: Référence interne
            description: Description
            payment_method: Méthode de paiement
            fee: Frais associés
            external_reference: Référence externe
            metadata: Métadonnées supplémentaires
        
        Returns:
            Transaction créée
        
        Raises:
            WalletInactiveError: Si le wallet est inactif
            InvalidAmountError: Si le montant est invalide
        """
        # Validation
        if not wallet.is_active:
            raise WalletInactiveError(wallet_id=str(wallet.id))
        
        if amount <= 0:
            raise InvalidAmountError(
                amount=amount,
                reason="Le montant doit être positif"
            )
        
        # Calculer le montant net
        net_amount = amount - fee
        
        if net_amount <= 0:
            raise InvalidAmountError(
                amount=amount,
                reason="Le montant net après frais doit être positif"
            )
        
        # Générer une référence si non fournie
        if not reference:
            reference = f"CREDIT_{uuid.uuid4().hex[:8].upper()}"
        
        try:
            # Créer la transaction
            transaction = Transaction.objects.create(
                wallet=wallet,
                transaction_type=transaction_type,
                amount=amount,
                fee=fee,
                net_amount=net_amount,
                reference=reference,
                external_reference=external_reference,
                description=description,
                payment_method=payment_method,
                status='COMPLETED',
                completed_at=timezone.now(),
                metadata=metadata or {}
            )
            
            # CORRECTION : Récupérer le wallet avec verrou pour thread-safety
            wallet_to_update = Wallet.objects.select_for_update().get(id=wallet.id)
            
            # Calculer les nouveaux soldes
            new_balance = wallet_to_update.balance + net_amount
            new_available_balance = wallet_to_update.available_balance + net_amount
            
            # Mettre à jour le wallet
            wallet_to_update.balance = new_balance
            wallet_to_update.available_balance = new_available_balance
            wallet_to_update.last_activity = timezone.now()
            wallet_to_update.updated_at = timezone.now()
            wallet_to_update.save()
            
            # Rafraîchir l'instance originale
            wallet.refresh_from_db()
            
            logger.info(
                "wallet_credited",
                wallet_id=str(wallet.id),
                user_id=str(wallet.user.id),
                amount=float(amount),
                fee=float(fee),
                net_amount=float(net_amount),
                currency=wallet.currency.code,
                transaction_id=str(transaction.id),
                transaction_type=transaction_type,
                payment_method=payment_method,
                new_balance=float(wallet.balance)
            )
            
            return transaction
            
        except Exception as e:
            logger.error(
                "wallet_credit_failed",
                wallet_id=str(wallet.id),
                amount=float(amount),
                error=str(e),
                exc_info=True
            )
            raise TransactionError(
                message=f"Erreur lors du crédit du wallet: {str(e)}",
                code="credit_failed"
            )
    
    @staticmethod
    @db_transaction.atomic
    def debit_wallet(
        wallet: Wallet,
        amount: Decimal,
        transaction_type: str = 'WITHDRAWAL',
        reference: Optional[str] = None,
        description: str = '',
        payment_method: str = '',
        fee: Decimal = Decimal('0'),
        external_reference: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        check_kyc: bool = True
    ) -> Transaction:
        """
        Débite un wallet de manière atomique (CORRIGÉ)
        
        Args:
            wallet: Wallet à débiter
            amount: Montant à débiter
            transaction_type: Type de transaction
            reference: Référence interne
            description: Description
            payment_method: Méthode de paiement
            fee: Frais associés
            external_reference: Référence externe
            metadata: Métadonnées supplémentaires
            check_kyc: Vérifier si KYC est requis
        
        Returns:
            Transaction créée
        
        Raises:
            WalletInactiveError: Si le wallet est inactif
            InvalidAmountError: Si le montant est invalide
            InsufficientFundsError: Si fonds insuffisants
            KYCRequiredError: Si KYC requis
        """
        # Validation
        if not wallet.is_active:
            raise WalletInactiveError(wallet_id=str(wallet.id))
        
        if amount <= 0:
            raise InvalidAmountError(
                amount=amount,
                reason="Le montant doit être positif"
            )
        
        # Vérifier KYC si demandé
        if check_kyc and wallet.user.kyc_status != 'verified':
            raise KYCRequiredError(
                operation=f"{transaction_type.lower()} de {amount} {wallet.currency.code}"
            )
        
        # Calculer le montant total à débiter
        total_debit = amount + fee
        
        # Vérifier les fonds disponibles (avec verrou pour thread-safety)
        with db_transaction.atomic():
            wallet_for_check = Wallet.objects.select_for_update().get(id=wallet.id)
            
            if wallet_for_check.available_balance < total_debit:
                raise InsufficientFundsError(
                    available=wallet_for_check.available_balance,
                    required=total_debit,
                    currency=wallet.currency.code
                )
        
        # Générer une référence si non fournie
        if not reference:
            reference = f"DEBIT_{uuid.uuid4().hex[:8].upper()}"
        
        try:
            # Créer la transaction
            transaction = Transaction.objects.create(
                wallet=wallet,
                transaction_type=transaction_type,
                amount=amount,
                fee=fee,
                net_amount=total_debit,  # Montant total débité
                reference=reference,
                external_reference=external_reference,
                description=description,
                payment_method=payment_method,
                status='COMPLETED',
                completed_at=timezone.now(),
                metadata=metadata or {}
            )
            
            # CORRECTION : Récupérer le wallet avec verrou
            wallet_to_update = Wallet.objects.select_for_update().get(id=wallet.id)
            
            # Calculer les nouveaux soldes
            new_balance = wallet_to_update.balance - total_debit
            new_available_balance = wallet_to_update.available_balance - total_debit
            
            # Mettre à jour le wallet
            wallet_to_update.balance = new_balance
            wallet_to_update.available_balance = new_available_balance
            wallet_to_update.last_activity = timezone.now()
            wallet_to_update.updated_at = timezone.now()
            wallet_to_update.save()
            
            # Rafraîchir l'instance originale
            wallet.refresh_from_db()
            
            logger.info(
                "wallet_debited",
                wallet_id=str(wallet.id),
                user_id=str(wallet.user.id),
                amount=float(amount),
                fee=float(fee),
                total_debit=float(total_debit),
                currency=wallet.currency.code,
                transaction_id=str(transaction.id),
                transaction_type=transaction_type,
                payment_method=payment_method,
                new_balance=float(wallet.balance)
            )
            
            return transaction
            
        except Exception as e:
            logger.error(
                "wallet_debit_failed",
                wallet_id=str(wallet.id),
                amount=float(amount),
                error=str(e),
                exc_info=True
            )
            raise TransactionError(
                message=f"Erreur lors du débit du wallet: {str(e)}",
                code="debit_failed"
            )
    
    @staticmethod
    @db_transaction.atomic
    def lock_funds(
        wallet: Wallet,
        amount: Decimal,
        reference: str,
        description: str = '',
        metadata: Optional[Dict[str, Any]] = None
    ) -> Transaction:
        """
        Bloque des fonds dans un wallet (pour réservations, etc.)
        
        Args:
            wallet: Wallet
            amount: Montant à bloquer
            reference: Référence du blocage
            description: Description
            metadata: Métadonnées
        
        Returns:
            Transaction de blocage
        """
        if not wallet.is_active:
            raise WalletInactiveError(wallet_id=str(wallet.id))
        
        if amount <= 0:
            raise InvalidAmountError(amount=amount)
        
        # Vérifier les fonds avec verrou
        wallet_to_check = Wallet.objects.select_for_update().get(id=wallet.id)
        
        if wallet_to_check.available_balance < amount:
            raise InsufficientFundsError(
                available=wallet_to_check.available_balance,
                required=amount,
                currency=wallet.currency.code
            )
        
        # Créer une transaction de blocage
        transaction = Transaction.objects.create(
            wallet=wallet,
            transaction_type='FEE',  # Type spécial pour blocage
            amount=Decimal('0'),  # Pas de mouvement réel
            fee=Decimal('0'),
            net_amount=Decimal('0'),
            reference=reference,
            description=description,
            status='COMPLETED',
            completed_at=timezone.now(),
            metadata={
                'lock_type': 'FUNDS_LOCK',
                'locked_amount': float(amount),
                **(metadata or {})
            }
        )
        
        logger.info(
            "funds_locked",
            wallet_id=str(wallet.id),
            amount=float(amount),
            reference=reference,
            transaction_id=str(transaction.id)
        )
        
        return transaction
    
    # ============================================================================
    # GESTION DES DÉPÔTS ET RETRAITS
    # ============================================================================
    
    @staticmethod
    def process_deposit(
        user,
        amount: Decimal,
        payment_method: str,
        provider_response: Dict[str, Any],
        description: str = ''
    ) -> Transaction:
        """
        Traite un dépôt après confirmation du provider
        
        Args:
            user: Utilisateur
            amount: Montant du dépôt
            payment_method: Méthode de paiement
            provider_response: Réponse du provider
            description: Description
        
        Returns:
            Transaction de dépôt
        """
        logger.info(
            "process_deposit_started",
            user_id=str(user.id),
            amount=float(amount),
            payment_method=payment_method
        )
        
        # Vérifier KYC selon le montant
        if amount > Decimal('1000') and user.kyc_status != 'verified':
            raise KYCRequiredError(
                operation=f"dépôt de {amount} (limite: 1000)"
            )
        
        # Récupérer le wallet
        wallet = WalletService.get_user_wallet(user)
        if not wallet:
            wallet = WalletService.create_wallet_for_user(user)
        
        # Extraire les données du provider
        external_reference = provider_response.get('transaction_id')
        fee = Decimal(str(provider_response.get('fee', 0)))
        
        # Créer la transaction
        transaction = WalletService.credit_wallet(
            wallet=wallet,
            amount=amount,
            transaction_type='DEPOSIT',
            reference=f"DEP_{uuid.uuid4().hex[:8].upper()}",
            description=f"{description} | Via {payment_method}",
            payment_method=payment_method,
            fee=fee,
            external_reference=external_reference,
            metadata={
                'provider': payment_method,
                'provider_response': provider_response,
                'processed_at': timezone.now().isoformat(),
                'user_ip': provider_response.get('metadata', {}).get('user_ip')
            }
        )
        
        logger.info(
            "deposit_processed_successfully",
            user_id=str(user.id),
            transaction_id=str(transaction.id),
            amount=float(amount),
            new_balance=float(wallet.balance)
        )
        
        return transaction
    
    @staticmethod
    def process_withdrawal(
        user,
        amount: Decimal,
        payment_method: str,
        provider_response: Dict[str, Any],
        description: str = ''
    ) -> Transaction:
        """
        Traite un retrait après confirmation du provider
        
        Args:
            user: Utilisateur
            amount: Montant du retrait
            payment_method: Méthode de paiement
            provider_response: Réponse du provider
            description: Description
        
        Returns:
            Transaction de retrait
        """
        logger.info(
            "process_withdrawal_started",
            user_id=str(user.id),
            amount=float(amount),
            payment_method=payment_method
        )
        
        # Vérifier KYC (obligatoire pour les retraits)
        if user.kyc_status != 'verified':
            raise KYCRequiredError(operation="retrait")
        
        # Récupérer le wallet
        wallet = WalletService.get_user_wallet(user)
        if not wallet:
            raise WalletNotFoundError(user_id=str(user.id))
        
        # Extraire les données du provider
        external_reference = provider_response.get('transaction_id')
        fee = Decimal(str(provider_response.get('fee', 0)))
        
        # Créer la transaction
        transaction = WalletService.debit_wallet(
            wallet=wallet,
            amount=amount,
            transaction_type='WITHDRAWAL',
            reference=f"WTH_{uuid.uuid4().hex[:8].upper()}",
            description=f"{description} | Via {payment_method}",
            payment_method=payment_method,
            fee=fee,
            external_reference=external_reference,
            metadata={
                'provider': payment_method,
                'provider_response': provider_response,
                'processed_at': timezone.now().isoformat(),
                'user_ip': provider_response.get('metadata', {}).get('user_ip')
            },
            check_kyc=False  # Déjà vérifié
        )
        
        logger.info(
            "withdrawal_processed_successfully",
            user_id=str(user.id),
            transaction_id=str(transaction.id),
            amount=float(amount),
            new_balance=float(wallet.balance)
        )
        
        return transaction
    
    # ============================================================================
    # HISTORIQUE ET RAPPORTS
    # ============================================================================
    
    @staticmethod
    def get_transaction_history(
        wallet: Wallet,
        limit: int = 50,
        offset: int = 0,
        transaction_type: Optional[str] = None,
        start_date: Optional[timezone.datetime] = None,
        end_date: Optional[timezone.datetime] = None
    ) -> Dict[str, Any]:
        """
        Récupère l'historique des transactions d'un wallet
        
        Args:
            wallet: Wallet
            limit: Nombre maximum de transactions
            offset: Décalage pour la pagination
            transaction_type: Filtrer par type
            start_date: Date de début
            end_date: Date de fin
        
        Returns:
            Dict avec transactions et infos de pagination
        """
        # Construire le queryset de base
        queryset = wallet.transactions.all()
        
        # Appliquer les filtres
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)
        
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        
        # Ordonner par date décroissante
        queryset = queryset.order_by('-created_at')
        
        # Pagination
        total = queryset.count()
        transactions = queryset[offset:offset + limit]
        
        return {
            'transactions': transactions,
            'pagination': {
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + limit) < total,
            },
            'summary': WalletService._get_transactions_summary(transactions)
        }
    
    @staticmethod
    def get_wallet_summary(wallet: Wallet) -> Dict[str, Any]:
        """
        Récupère un résumé complet du wallet
        
        Args:
            wallet: Wallet
        
        Returns:
            Dict avec le résumé
        """
        # Statistiques des transactions
        transactions = wallet.transactions.all()
        
        total_deposits = transactions.filter(
            transaction_type='DEPOSIT', 
            status='COMPLETED'
        ).count()
        
        total_withdrawals = transactions.filter(
            transaction_type='WITHDRAWAL',
            status='COMPLETED'
        ).count()
        
        # Montants totaux
        deposit_amount = sum(
            t.net_amount for t in transactions.filter(
                transaction_type='DEPOSIT',
                status='COMPLETED'
            )
        )
        
        withdrawal_amount = sum(
            t.net_amount for t in transactions.filter(
                transaction_type='WITHDRAWAL',
                status='COMPLETED'
            )
        )
        
        # Dernières activités
        recent_transactions = transactions.order_by('-created_at')[:5]
        
        return {
            'wallet_id': str(wallet.id),
            'currency': wallet.currency.code,
            'balance': float(wallet.balance),
            'formatted_balance': format_amount(wallet.balance, wallet.currency.code),
            'available_balance': float(wallet.available_balance),
            'formatted_available_balance': format_amount(wallet.available_balance, wallet.currency.code),
            'is_active': wallet.is_active,
            'created_at': wallet.created_at.isoformat(),
            'last_activity': wallet.last_activity.isoformat() if wallet.last_activity else None,
            'statistics': {
                'total_transactions': transactions.count(),
                'total_deposits': total_deposits,
                'total_withdrawals': total_withdrawals,
                'total_deposit_amount': float(deposit_amount),
                'total_withdrawal_amount': float(withdrawal_amount),
            },
            'recent_transactions': [
                {
                    'id': str(t.id),
                    'type': t.transaction_type,
                    'amount': float(t.amount),
                    'status': t.status,
                    'created_at': t.created_at.isoformat(),
                }
                for t in recent_transactions
            ],
            'user_info': {
                'user_id': str(wallet.user.id),
                'kyc_status': wallet.user.kyc_status,
                'phone_verified': wallet.user.phone_verified,
            }
        }
    
    # ============================================================================
    # UTILITAIRES PRIVÉS
    # ============================================================================
    
    @staticmethod
    def _get_or_create_currency(currency_code: str) -> Tuple[Currency, bool]:
        """
        Récupère ou crée une devise
        
        Args:
            currency_code: Code devise
        
        Returns:
            Tuple (Currency, created)
        """
        try:
            currency = Currency.objects.get(code=currency_code)
            return currency, False
        except Currency.DoesNotExist:
            # Créer la devise avec les infos de currency_utils
            try:
                currency_info = get_currency_info(currency_code)
                
                currency = Currency.objects.create(
                    code=currency_code,
                    name=currency_info.get('name', currency_code),
                    symbol=currency_info.get('symbol', currency_code),
                    decimal_places=currency_info.get('decimal_places', 2),
                    is_active=True
                )
                
                logger.info("currency_created", currency_code=currency_code)
                return currency, True
                
            except ValueError:
                # Devise inconnue, créer avec des valeurs par défaut
                currency = Currency.objects.create(
                    code=currency_code,
                    name=currency_code,
                    symbol=currency_code,
                    decimal_places=2,
                    is_active=True
                )
                
                logger.warning(
                    "unknown_currency_created",
                    currency_code=currency_code
                )
                return currency, True
    
    @staticmethod
    def _get_transactions_summary(transactions) -> Dict[str, Any]:
        """
        Calcule un résumé pour un ensemble de transactions
        """
        if not transactions:
            return {}
        
        total_amount = sum(t.amount for t in transactions)
        total_fees = sum(t.fee for t in transactions)
        
        deposits = [t for t in transactions if t.transaction_type == 'DEPOSIT']
        withdrawals = [t for t in transactions if t.transaction_type == 'WITHDRAWAL']
        
        return {
            'count': len(transactions),
            'total_amount': float(total_amount),
            'total_fees': float(total_fees),
            'deposit_count': len(deposits),
            'withdrawal_count': len(withdrawals),
            'deposit_amount': float(sum(t.amount for t in deposits)),
            'withdrawal_amount': float(sum(t.amount for t in withdrawals)),
        }
    
    @staticmethod
    def validate_wallet_operation(
        wallet: Wallet,
        amount: Decimal,
        operation: str,
        check_kyc: bool = True
    ) -> Dict[str, Any]:
        """
        Valide une opération sur un wallet sans l'exécuter
        
        Args:
            wallet: Wallet
            amount: Montant
            operation: 'deposit' ou 'withdrawal'
            check_kyc: Vérifier KYC
        
        Returns:
            Dict avec les résultats de validation
        """
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'fee': 0,
            'net_amount': float(amount),
            'can_proceed': True
        }
        
        try:
            # Vérifier wallet actif
            if not wallet.is_active:
                validation_result['valid'] = False
                validation_result['errors'].append('Wallet inactif')
                validation_result['can_proceed'] = False
            
            # Vérifier montant positif
            if amount <= 0:
                validation_result['valid'] = False
                validation_result['errors'].append('Montant doit être positif')
                validation_result['can_proceed'] = False
            
            # Vérifier KYC pour les retraits
            if operation == 'withdrawal' and check_kyc:
                if wallet.user.kyc_status != 'verified':
                    validation_result['valid'] = False
                    validation_result['errors'].append('KYC requis pour les retraits')
                    validation_result['can_proceed'] = False
                    validation_result['next_step'] = 'complete_kyc'
            
            # Vérifier les fonds pour les retraits
            if operation == 'withdrawal':
                # Ici vous pourriez calculer les frais dynamiquement
                estimated_fee = amount * Decimal('0.02')  # 2% estimé
                total_required = amount + estimated_fee
                
                if wallet.available_balance < total_required:
                    validation_result['valid'] = False
                    validation_result['errors'].append('Fonds insuffisants')
                    validation_result['can_proceed'] = False
                    validation_result['available'] = float(wallet.available_balance)
                    validation_result['required'] = float(total_required)
                
                validation_result['fee'] = float(estimated_fee)
                validation_result['net_amount'] = float(amount - estimated_fee)
            
            # Vérifier les limites pour les dépôts
            if operation == 'deposit' and amount > Decimal('10000'):
                validation_result['warnings'].append(
                    'Dépôt supérieur à 10,000. KYC peut être requis.'
                )
        
        except Exception as e:
            validation_result['valid'] = False
            validation_result['errors'].append(f'Erreur de validation: {str(e)}')
            validation_result['can_proceed'] = False
        
        return validation_result