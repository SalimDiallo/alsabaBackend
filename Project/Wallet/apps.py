
import structlog
from django.apps import AppConfig
logger = structlog.get_logger(__name__)


class WalletConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Wallet'
    
    def ready(self):
        """
        Code exécuté quand l'application est prête
        """
        # Importer et enregistrer les providers de paiement
        self._register_payment_providers()
        
        # Initialiser les devises si nécessaire
        self._initialize_currencies()
        
        logger.info("wallet_app_ready")
    
    def _register_payment_providers(self):
        """
        Enregistre les providers de paiement
        """
        try:
            from .Services.PayementProviders.base import PaymentProviderFactory
            from .Services.PayementProviders.orange_money import OrangeMoneyProvider
            from .Services.PayementProviders.card import CardProvider
            
            # Enregistrer les providers
            PaymentProviderFactory.register_provider('ORANGE_MONEY', OrangeMoneyProvider)
            PaymentProviderFactory.register_provider('CARD', CardProvider)
            
            logger.info(
                "payment_providers_registered",
                providers=['ORANGE_MONEY', 'CARD']
            )
            
        except Exception as e:
            logger.error(
                "payment_providers_registration_failed",
                error=str(e),
                exc_info=True
            )
    
    def _initialize_currencies(self):
        """
        Initialise les devises dans la base de données
        """
        try:
            from .Utils.currency_utils import initialize_currencies
            
            # Cette fonction peut être appelée dans une migration à la place
            # initialize_currencies()
            
            logger.debug("currencies_initialization_ready")
            
        except Exception as e:
            logger.error(
                "currencies_initialization_failed",
                error=str(e)
            )