"""
Exceptions personnalisées pour le module wallet
Permet une gestion d'erreur granulaire et des messages clairs
"""


class WalletError(Exception):
    """
    Exception de base pour toutes les erreurs liées aux wallets.
    Toutes les autres exceptions héritent de celle-ci.
    """
    
    def __init__(self, message: str, code: str = None, details: dict = None):
        self.message = message
        self.code = code or "wallet_error"
        self.details = details or {}
        super().__init__(self.message)


# ============================================================================
# EXCEPTIONS LIÉES AUX WALLETS
# ============================================================================

class WalletNotFoundError(WalletError):
    """Wallet non trouvé"""
    
    def __init__(self, wallet_id: str = None, user_id: str = None, **kwargs):
        message = "Wallet non trouvé"
        if wallet_id:
            message = f"Wallet {wallet_id} non trouvé"
        elif user_id:
            message = f"Aucun wallet trouvé pour l'utilisateur {user_id}"
        
        super().__init__(message, code="wallet_not_found", details=kwargs)


class WalletInactiveError(WalletError):
    """Wallet inactif"""
    
    def __init__(self, wallet_id: str = None, **kwargs):
        message = "Wallet inactif"
        if wallet_id:
            message = f"Wallet {wallet_id} est inactif"
        
        super().__init__(message, code="wallet_inactive", details=kwargs)


class WalletAlreadyExistsError(WalletError):
    """Wallet existe déjà pour cet utilisateur"""
    
    def __init__(self, user_id: str, currency: str, **kwargs):
        message = f"L'utilisateur {user_id} a déjà un wallet en {currency}"
        
        super().__init__(message, code="wallet_already_exists", details=kwargs)


# ============================================================================
# EXCEPTIONS LIÉES AUX SOLDES ET MONTANTS
# ============================================================================

class InsufficientFundsError(WalletError):
    """Fonds insuffisants"""
    
    def __init__(self, 
                 available: float = None, 
                 required: float = None, 
                 currency: str = None,
                 **kwargs):
        
        message = "Fonds insuffisants"
        if available is not None and required is not None:
            if currency:
                message = f"Fonds insuffisants. Disponible: {available} {currency}, Requiert: {required} {currency}"
            else:
                message = f"Fonds insuffisants. Disponible: {available}, Requiert: {required}"
        
        super().__init__(message, code="insufficient_funds", details=kwargs)


class InvalidAmountError(WalletError):
    """Montant invalide"""
    
    def __init__(self, amount: float = None, reason: str = None, **kwargs):
        message = "Montant invalide"
        if amount is not None:
            message = f"Montant invalide: {amount}"
            if reason:
                message = f"{message} ({reason})"
        
        super().__init__(message, code="invalid_amount", details=kwargs)


class AmountTooSmallError(InvalidAmountError):
    """Montant trop petit"""
    
    def __init__(self, amount: float, min_amount: float, currency: str = None, **kwargs):
        if currency:
            message = f"Montant trop petit: {amount} {currency}. Minimum: {min_amount} {currency}"
        else:
            message = f"Montant trop petit: {amount}. Minimum: {min_amount}"
        
        super().__init__(message, code="amount_too_small", details=kwargs)


class AmountTooLargeError(InvalidAmountError):
    """Montant trop grand"""
    
    def __init__(self, amount: float, max_amount: float, currency: str = None, **kwargs):
        if currency:
            message = f"Montant trop grand: {amount} {currency}. Maximum: {max_amount} {currency}"
        else:
            message = f"Montant trop grand: {amount}. Maximum: {max_amount}"
        
        super().__init__(message, code="amount_too_large", details=kwargs)


# ============================================================================
# EXCEPTIONS LIÉES AUX TRANSACTIONS
# ============================================================================

class TransactionError(WalletError):
    """Erreur générale de transaction"""
    
    def __init__(self, transaction_id: str = None, reason: str = None, **kwargs):
        message = "Erreur de transaction"
        if transaction_id:
            message = f"Erreur de transaction {transaction_id}"
            if reason:
                message = f"{message}: {reason}"
        
        super().__init__(message, code="transaction_error", details=kwargs)


class TransactionNotFoundError(TransactionError):
    """Transaction non trouvée"""
    
    def __init__(self, transaction_id: str = None, **kwargs):
        message = "Transaction non trouvée"
        if transaction_id:
            message = f"Transaction {transaction_id} non trouvée"
        
        super().__init__(message, code="transaction_not_found", details=kwargs)


class TransactionAlreadyProcessedError(TransactionError):
    """Transaction déjà traitée"""
    
    def __init__(self, transaction_id: str, current_status: str, **kwargs):
        message = f"Transaction {transaction_id} déjà traitée (statut: {current_status})"
        
        super().__init__(message, code="transaction_already_processed", details=kwargs)


# ============================================================================
# EXCEPTIONS LIÉES AUX PAIEMENTS
# ============================================================================

class PaymentError(WalletError):
    """Erreur générale de paiement"""
    
    def __init__(self, provider: str = None, reason: str = None, **kwargs):
        message = "Erreur de paiement"
        if provider:
            message = f"Erreur de paiement avec {provider}"
            if reason:
                message = f"{message}: {reason}"
        
        super().__init__(message, code="payment_error", details=kwargs)


class PaymentProviderError(PaymentError):
    """Erreur spécifique au provider de paiement"""
    
    def __init__(self, provider: str, error_code: str = None, **kwargs):
        message = f"Erreur avec le provider {provider}"
        if error_code:
            message = f"{message} (code: {error_code})"
        
        super().__init__(message, code=f"provider_{provider.lower()}_error", details=kwargs)


class PaymentMethodNotSupportedError(PaymentError):
    """Méthode de paiement non supportée"""
    
    def __init__(self, payment_method: str, currency: str = None, **kwargs):
        message = f"Méthode de paiement non supportée: {payment_method}"
        if currency:
            message = f"{message} pour la devise {currency}"
        
        super().__init__(message, code="payment_method_not_supported", details=kwargs)


class PaymentProcessingError(PaymentError):
    """Erreur lors du traitement du paiement"""
    
    def __init__(self, transaction_id: str = None, **kwargs):
        message = "Erreur lors du traitement du paiement"
        if transaction_id:
            message = f"Erreur lors du traitement du paiement {transaction_id}"
        
        super().__init__(message, code="payment_processing_error", details=kwargs)


# ============================================================================
# EXCEPTIONS LIÉES AUX DEVISES
# ============================================================================

class CurrencyError(WalletError):
    """Erreur liée à une devise"""
    
    def __init__(self, currency: str = None, reason: str = None, **kwargs):
        message = "Erreur de devise"
        if currency:
            message = f"Erreur avec la devise {currency}"
            if reason:
                message = f"{message}: {reason}"
        
        super().__init__(message, code="currency_error", details=kwargs)


class CurrencyNotSupportedError(CurrencyError):
    """Devise non supportée"""
    
    def __init__(self, currency: str, **kwargs):
        message = f"Devise non supportée: {currency}"
        
        super().__init__(message, code="currency_not_supported", details=kwargs)


class CurrencyConversionError(CurrencyError):
    """Erreur de conversion de devise"""
    
    def __init__(self, from_currency: str, to_currency: str, **kwargs):
        message = f"Impossible de convertir de {from_currency} vers {to_currency}"
        
        super().__init__(message, code="currency_conversion_error", details=kwargs)


# ============================================================================
# EXCEPTIONS DE VALIDATION
# ============================================================================

class ValidationError(WalletError):
    """Erreur de validation"""
    
    def __init__(self, field: str = None, errors: dict = None, **kwargs):
        message = "Erreur de validation"
        if field:
            message = f"Erreur de validation pour le champ {field}"
        
        super().__init__(message, code="validation_error", details={'errors': errors} if errors else kwargs)


class KYCRequiredError(WalletError):
    """KYC requis pour l'opération"""
    
    def __init__(self, operation: str = None, **kwargs):
        message = "Vérification KYC requise"
        if operation:
            message = f"Vérification KYC requise pour {operation}"
        
        super().__init__(message, code="kyc_required", details=kwargs)


# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================

def handle_wallet_error(error: WalletError) -> dict:
    """
    Formate une exception WalletError pour la réponse API.
    
    Args:
        error: L'exception WalletError
    
    Returns:
        Dictionnaire formaté pour la réponse API
    """
    response = {
        "success": False,
        "error": error.message,
        "code": error.code,
    }
    
    if error.details:
        response["details"] = error.details
    
    return response


def is_wallet_error(error: Exception) -> bool:
    """
    Vérifie si une exception est une WalletError.
    
    Args:
        error: L'exception à vérifier
    
    Returns:
        True si c'est une WalletError
    """
    return isinstance(error, WalletError)