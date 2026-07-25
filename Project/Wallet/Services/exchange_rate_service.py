from decimal import Decimal
from django.core.cache import cache
import structlog

logger = structlog.get_logger(__name__)

class ExchangeRateService:
    """
    Service de gestion des taux de change avec Cache.
    """
    CACHE_TIMEOUT = 3600  # 1 heure
    
    @staticmethod
    def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
        """
        Récupère le taux de change avec cache.
        """
        if from_currency == to_currency:
            return Decimal("1.0")

        cache_key = f"exchange_rate:{from_currency}:{to_currency}"
        
        # 1. Vérifier le cache
        cached_rate = cache.get(cache_key)
        if cached_rate:
            return Decimal(str(cached_rate))
            
        # 2. Si pas en cache, récupérer (simulation pour l'instant)
        # Dans le futur: appel API externe (xe.com, fixer.io, etc.)
        rate = ExchangeRateService._fetch_rate_from_provider(from_currency, to_currency)
        
        # 3. Mettre en cache
        cache.set(cache_key, str(rate), timeout=ExchangeRateService.CACHE_TIMEOUT)
        
        return rate

    @staticmethod
    def _fetch_rate_from_provider(from_curr, to_curr) -> Decimal:
        """
        Récupère le taux depuis forex-python ou fallback sur taux fixes.
        """
        from forex_python.converter import CurrencyRates
        from forex_python.converter import RatesNotAvailableError

        # Taux de secours (Hardcoded / Pegged)
        fallback_rates = {
            "EUR_XOF": Decimal("655.957"), # Fixed Peg
            "XOF_EUR": Decimal("1") / Decimal("655.957"),
            "USD_XOF": Decimal("600.0"),
            "XOF_USD": Decimal("1") / Decimal("600.0"),
            "EUR_USD": Decimal("1.08"),
            "USD_EUR": Decimal("0.92"),
        }

        # 1. Essayer forex-python
        try:
            logger.info("fetching_rate_forex_python", from_curr=from_curr, to_curr=to_curr)
            c = CurrencyRates()
            
            # XOF est souvent manquant ou mal géré par les API gratuites, on force le PEG si c'est EUR/XOF
            if (from_curr == 'EUR' and to_curr == 'XOF') or (from_curr == 'XOF' and to_curr == 'EUR'):
                return fallback_rates.get(f"{from_curr}_{to_curr}")

            rate = c.get_rate(from_curr, to_curr)
            return Decimal(str(rate))
            
        except (RatesNotAvailableError, Exception) as e:
            logger.warning("forex_python_failed", error=str(e), pair=f"{from_curr}_{to_curr}")
        
        # 2. Fallback
        logger.info("using_fallback_rate", pair=f"{from_curr}_{to_curr}")
        key = f"{from_curr}_{to_curr}"
        return fallback_rates.get(key, Decimal("1.0"))

    @staticmethod
    def is_rate_reasonable(proposed_rate: Decimal, from_curr: str, to_curr: str, tolerance_percent=0.05) -> bool:
        """
        Vérifie si un taux proposé est raisonnable par rapport au marché.
        """
        market_rate = ExchangeRateService.get_exchange_rate(from_curr, to_curr)
        
        diff = abs(proposed_rate - market_rate)
        limit = market_rate * Decimal(str(tolerance_percent))
        
        return diff <= limit
