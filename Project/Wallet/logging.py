"""
Configuration du logging structuré pour wallet
"""
import structlog

# Créer un logger structlog pour tout le module wallet
wallet_logger = structlog.get_logger("wallet")

# Fonctions helpers pour des logs spécifiques
def log_wallet_creation(user_id, wallet_id, currency):
    """Log la création d'un wallet"""
    wallet_logger.info(
        "wallet_created",
        user_id=user_id,
        wallet_id=wallet_id,
        currency=currency,
        event_type="wallet_creation"
    )

def log_transaction(transaction_id, wallet_id, amount, transaction_type, status):
    """Log une transaction"""
    wallet_logger.info(
        "transaction_processed",
        transaction_id=transaction_id,
        wallet_id=wallet_id,
        amount=float(amount),
        transaction_type=transaction_type,
        status=status,
        event_type="transaction"
    )

def log_deposit_initiated(user_id, amount, payment_method):
    """Log l'initiation d'un dépôt"""
    wallet_logger.info(
        "deposit_initiated",
        user_id=user_id,
        amount=float(amount),
        payment_method=payment_method,
        event_type="deposit_initiation"
    )

def log_withdrawal_initiated(user_id, amount, payment_method):
    """Log l'initiation d'un retrait"""
    wallet_logger.info(
        "withdrawal_initiated",
        user_id=user_id,
        amount=float(amount),
        payment_method=payment_method,
        event_type="withdrawal_initiation"
    )

def log_error(event, error, **kwargs):
    """Log une erreur"""
    wallet_logger.error(
        event,
        error=str(error),
        **kwargs,
        event_type="error"
    )

def log_warning(event, **kwargs):
    """Log un warning"""
    wallet_logger.warning(
        event,
        **kwargs,
        event_type="warning"
    )

def log_debug(event, **kwargs):
    """Log debug"""
    wallet_logger.debug(
        event,
        **kwargs,
        event_type="debug"
    )