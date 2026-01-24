import phonenumbers
import pycountry
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)

def get_currency_code_from_phone(full_phone: str) -> str:
    """
    Reconnaît la devise du pays via le numéro de téléphone.
    - Utilise phonenumbers pour extraire le code pays (ex: 'FR', 'MA').
    - Utilise pycountry pour mapper à la devise (ex: 'EUR', 'MAD').
    - Fallback sur 'EUR' si non trouvé (configurable).
    
    Exemples :
    - "+33612345678" → "EUR"
    - "+212612345678" → "MAD"
    - "+221771234567" → "XOF"
    
    Args:
        full_phone: Numéro E.164 (ex: "+33612345678")
    
    Returns:
        str: Code devise ISO 4217 (ex: "EUR")
    
    Raises:
        ValueError si format invalide.
    """
    try:
        parsed = phonenumbers.parse(full_phone, None)
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError(f"Numéro invalide: {full_phone}")
        
        region_code = phonenumbers.region_code_for_number(parsed)  # ex: 'FR', 'MA'
        if not region_code:
            logger.warning("region_code_not_found", full_phone=full_phone)
            return 'EUR'  # Fallback
        
        country = pycountry.countries.get(alpha_2=region_code)
        if not country:
            logger.warning("country_not_found", region_code=region_code)
            return 'EUR'
        
        # Récupère la devise principale
        currency = pycountry.currencies.get(numeric=country.numeric)
        if currency:
            return currency.alpha_3  # ex: 'EUR', 'MAD'
        
        logger.warning("currency_not_found_for_country", region_code=region_code)
        return 'EUR'
    
    except phonenumbers.NumberParseException as e:
        logger.error("phone_parse_error", full_phone=full_phone, error=str(e))
        raise ValueError("Format de numéro invalide.")