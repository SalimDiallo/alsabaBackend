import requests
from django.conf import settings
from django.core.cache import cache
import structlog

logger = structlog.get_logger(__name__)

class ExchangeRateService:
    """
    Service for retrieving real-time exchange rates.
    Uses Redis to cache rates to limit API calls.
    """
    
    CACHE_KEY_PREFIX = "exchange_rates_"
    CACHE_TIMEOUT = 3600  # Caching for 1 hour (3600s)

    @classmethod
    def get_rates(cls, base_currency="MAD"):
        """
        Retrieves exchange rates for a given base currency.
        """
        cache_key = f"{cls.CACHE_KEY_PREFIX}{base_currency}"
        rates = cache.get(cache_key)

        if rates:
            logger.debug("exchange_rates_cache_hit", base=base_currency)
            return rates

        logger.info("exchange_rates_cache_miss", base=base_currency)
        return cls.fetch_and_cache_rates(base_currency)

    @classmethod
    def fetch_and_cache_rates(cls, base_currency="MAD"):
        """
        Calls the external API and stores the result in the cache.
        """
        api_key = getattr(settings, 'EXCHANGERATE_API_KEY', None)
        base_url = getattr(settings, 'EXCHANGERATE_BASE_URL', "https://v6.exchangerate-api.com/v6/")

        if not api_key:
            logger.warning("exchangerate_api_key_missing")
            return None

        url = f"{base_url}{api_key}/latest/{base_currency}"

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("result") == "success":
                rates = data.get("conversion_rates")
                # Caching
                cache_key = f"{cls.CACHE_KEY_PREFIX}{base_currency}"
                cache.set(cache_key, rates, cls.CACHE_TIMEOUT)
                logger.info("exchange_rates_updated", base=base_currency, count=len(rates))
                return rates
            else:
                logger.error("exchangerate_api_error", error=data.get("error-type"))
                return None

        except requests.RequestException as e:
            logger.error("exchangerate_request_failed", error=str(e))
            return None

    @classmethod
    def convert(cls, amount, from_currency, to_currency):
        """
        Converts an amount from one currency to another.
        """
        if from_currency == to_currency:
            return amount

        rates = cls.get_rates(from_currency)
        if rates and to_currency in rates:
            rate = rates[to_currency]
            return amount * rate
        
        return None

    @classmethod
    def get_rate(cls, from_currency, to_currency):
        """
        Retrieves the specific rate between two currencies.
        """
        rates = cls.get_rates(from_currency)
        if rates:
            return rates.get(to_currency)
        return None
