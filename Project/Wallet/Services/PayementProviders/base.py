"""
Interface de base pour tous les providers de paiement
Design Pattern: Strategy
"""
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, Any, Optional
import logging

import structlog

logger = structlog.get_logger(__name__)


class PaymentProvider(ABC):
    """
    Interface abstraite pour un provider de paiement
    Tous les providers (Orange Money, Carte, etc.) doivent implémenter cette interface
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Nom du provider (ex: 'ORANGE_MONEY', 'CARD')"""
        pass
    
    @property
    @abstractmethod
    def display_name(self) -> str:
        """Nom d'affichage (ex: 'Orange Money', 'Carte bancaire')"""
        pass
    
    @property
    @abstractmethod
    def supported_currencies(self) -> list:
        """Liste des devises supportées (ex: ['XOF', 'EUR'])"""
        pass
    
    @property
    @abstractmethod
    def min_amount(self) -> Dict[str, Decimal]:
        """Montant minimum par devise"""
        pass
    
    @property
    @abstractmethod
    def max_amount(self) -> Dict[str, Decimal]:
        """Montant maximum par devise"""
        pass
    
    @property
    @abstractmethod
    def deposit_fee_rate(self) -> Dict[str, Decimal]:
        """Taux de frais pour les dépôts par devise"""
        pass
    
    @property
    @abstractmethod
    def withdrawal_fee_rate(self) -> Dict[str, Decimal]:
        """Taux de frais pour les retraits par devise"""
        pass
    
    @abstractmethod
    def initiate_deposit(
        self,
        amount: Decimal,
        currency: str,
        user_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Initie un dépôt
        
        Args:
            amount: Montant du dépôt
            currency: Devise (ex: 'XOF', 'EUR')
            user_data: Informations utilisateur
            metadata: Métadonnées supplémentaires
        
        Returns:
            Dict avec les informations du dépôt initié
        """
        pass
    
    @abstractmethod
    def initiate_withdrawal(
        self,
        amount: Decimal,
        currency: str,
        user_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Initie un retrait
        
        Args:
            amount: Montant du retrait
            currency: Devise
            user_data: Informations utilisateur
            metadata: Métadonnées supplémentaires
        
        Returns:
            Dict avec les informations du retrait initié
        """
        pass
    
    @abstractmethod
    def check_status(
        self,
        transaction_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Vérifie le statut d'une transaction
        
        Args:
            transaction_id: ID de la transaction externe
            metadata: Métadonnées supplémentaires
        
        Returns:
            Dict avec le statut de la transaction
        """
        pass
    
    def validate_amount(self, amount: Decimal, currency: str, operation: str) -> None:
        """
        Valide le montant pour une opération
        
        Args:
            amount: Montant à valider
            currency: Devise
            operation: 'deposit' ou 'withdrawal'
        
        Raises:
            ValueError: Si le montant est invalide
        """
        from ...exceptions import InvalidAmountError, AmountTooSmallError, AmountTooLargeError
        
        if amount <= 0:
            raise InvalidAmountError(
                amount=amount,
                reason="Le montant doit être positif"
            )
        
        # Vérifier les limites par devise
        min_amount = self.min_amount.get(currency)
        max_amount = self.max_amount.get(currency)
        
        if min_amount and amount < min_amount:
            raise AmountTooSmallError(
                amount=amount,
                min_amount=min_amount,
                currency=currency
            )
        
        if max_amount and amount > max_amount:
            raise AmountTooLargeError(
                amount=amount,
                max_amount=max_amount,
                currency=currency
            )
    
    def validate_currency(self, currency: str) -> None:
        """
        Valide que la devise est supportée
        
        Args:
            currency: Code devise à valider
        
        Raises:
            ValueError: Si la devise n'est pas supportée
        """
        from ...exceptions import CurrencyNotSupportedError
        
        if currency not in self.supported_currencies:
            raise CurrencyNotSupportedError(currency)
    
    def calculate_fee(self, amount: Decimal, currency: str, operation: str) -> Decimal:
        """
        Calcule les frais pour une opération
        
        Args:
            amount: Montant de base
            currency: Devise
            operation: 'deposit' ou 'withdrawal'
        
        Returns:
            Montant des frais
        """
        if operation == 'deposit':
            fee_rate = self.deposit_fee_rate.get(currency, Decimal('0'))
        elif operation == 'withdrawal':
            fee_rate = self.withdrawal_fee_rate.get(currency, Decimal('0'))
        else:
            fee_rate = Decimal('0')
        
        fee = amount * fee_rate
        
        # Arrondir à 2 décimales
        return fee.quantize(Decimal('0.01'))
    
    def get_net_amount(self, amount: Decimal, currency: str, operation: str) -> Decimal:
        """
        Calcule le montant net (après frais)
        
        Args:
            amount: Montant de base
            currency: Devise
            operation: 'deposit' ou 'withdrawal'
        
        Returns:
            Montant net
        """
        fee = self.calculate_fee(amount, currency, operation)
        
        if operation == 'deposit':
            # Pour un dépôt: utilisateur paye les frais
            return amount
        elif operation == 'withdrawal':
            # Pour un retrait: frais déduits du montant
            return amount - fee
        else:
            return amount


class PaymentProviderFactory:
    """
    Factory pour créer des instances de providers de paiement
    Design Pattern: Factory
    """
    
    _providers = {}
    
    @classmethod
    def register_provider(cls, name: str, provider_class):
        """
        Enregistre un provider
        
        Args:
            name: Nom du provider (ex: 'ORANGE_MONEY')
            provider_class: Classe du provider
        """
        cls._providers[name.upper()] = provider_class
    
    @classmethod
    def get_provider(cls, name: str) -> PaymentProvider:
        """
        Récupère une instance d'un provider
        
        Args:
            name: Nom du provider
        
        Returns:
            Instance du provider
        
        Raises:
            KeyError: Si le provider n'est pas enregistré
        """
        from ...exceptions import PaymentMethodNotSupportedError
        
        provider_class = cls._providers.get(name.upper())
        
        if not provider_class:
            raise PaymentMethodNotSupportedError(name)
        
        return provider_class()
    
    @classmethod
    def get_available_providers(cls) -> list:
        """
        Retourne la liste des providers disponibles
        
        Returns:
            Liste des noms de providers
        """
        return list(cls._providers.keys())
    
    @classmethod
    def get_provider_info(cls, name: str) -> Dict[str, Any]:
        """
        Récupère les informations d'un provider
        
        Args:
            name: Nom du provider
        
        Returns:
            Dict avec les informations du provider
        """
        try:
            provider = cls.get_provider(name)
            return {
                'name': provider.name,
                'display_name': provider.display_name,
                'supported_currencies': provider.supported_currencies,
                'min_amount': {k: float(v) for k, v in provider.min_amount.items()},
                'max_amount': {k: float(v) for k, v in provider.max_amount.items()},
                'deposit_fee_rate': {k: float(v) for k, v in provider.deposit_fee_rate.items()},
                'withdrawal_fee_rate': {k: float(v) for k, v in provider.withdrawal_fee_rate.items()},
            }
        except Exception as e:
            logger.error(f"Error getting provider info for {name}: {e}")
            return {}
    
    @classmethod
    def get_all_providers_info(cls) -> Dict[str, Dict[str, Any]]:
        """
        Récupère les informations de tous les providers
        
        Returns:
            Dict avec les informations de tous les providers
        """
        providers_info = {}
        
        for name in cls._providers.keys():
            providers_info[name] = cls.get_provider_info(name)
        
        return providers_info