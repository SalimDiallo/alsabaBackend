"""
Utils pour la gestion des devises
Mapping pays -> devise et informations des devises
"""
from decimal import Decimal

import structlog

logger = structlog.get_logger(__name__)

# ============================================================================
# MAPPING CODE PAYS -> DEVISE
# ============================================================================
COUNTRY_CURRENCY_MAPPING = {
    # Europe
    '+33': 'EUR',      # France
    '+32': 'EUR',      # Belgique
    '+41': 'CHF',      # Suisse
    '+44': 'GBP',      # Royaume-Uni
    '+49': 'EUR',      # Allemagne
    '+34': 'EUR',      # Espagne
    '+39': 'EUR',      # Italie
    
    # Afrique de l'Ouest (UEMOA - XOF)
    '+225': 'XOF',     # Côte d'Ivoire
    '+229': 'XOF',     # Bénin
    '+226': 'XOF',     # Burkina Faso
    '+221': 'XOF',     # Sénégal
    '+228': 'XOF',     # Togo
    '+223': 'XOF',     # Mali
    '+227': 'XOF',     # Niger
    '+224': 'GNF',     # Guinée (pas XOF)
    
    # Afrique Centrale (CEMAC - XAF)
    '+237': 'XAF',     # Cameroun
    '+242': 'XAF',     # Congo
    '+243': 'CDF',     # RDC (pas XAF)
    '+236': 'XAF',     # République Centrafricaine
    '+241': 'XAF',     # Gabon
    '+235': 'XAF',     # Tchad
    
    # Amérique
    '+1': 'USD',       # USA/Canada
    '+55': 'BRL',      # Brésil
    
    # Asie
    '+91': 'INR',      # Inde
    '+86': 'CNY',      # Chine
    '+81': 'JPY',      # Japon
}

# Devise par défaut si pays non trouvé
DEFAULT_CURRENCY = 'EUR'

# ============================================================================
# INFORMATIONS DES DEVISES
# ============================================================================
CURRENCY_INFO = {
    'EUR': {
        'name': 'Euro',
        'symbol': '€',
        'decimal_places': 2,
        'is_fiat': True,
        'is_crypto': False,
        'min_amount': Decimal('0.01'),
    },
    'USD': {
        'name': 'Dollar US',
        'symbol': '$',
        'decimal_places': 2,
        'is_fiat': True,
        'is_crypto': False,
        'min_amount': Decimal('0.01'),
    },
    'XOF': {
        'name': 'Franc CFA Ouest Africain',
        'symbol': 'CFA',
        'decimal_places': 0,  # Pas de centimes
        'is_fiat': True,
        'is_crypto': False,
        'min_amount': Decimal('1'),
    },
    'XAF': {
        'name': 'Franc CFA Centrafricain',
        'symbol': 'FCFA',
        'decimal_places': 0,
        'is_fiat': True,
        'is_crypto': False,
        'min_amount': Decimal('1'),
    },
    'GBP': {
        'name': 'Livre Sterling',
        'symbol': '£',
        'decimal_places': 2,
        'is_fiat': True,
        'is_crypto': False,
        'min_amount': Decimal('0.01'),
    },
    'CHF': {
        'name': 'Franc Suisse',
        'symbol': 'CHF',
        'decimal_places': 2,
        'is_fiat': True,
        'is_crypto': False,
        'min_amount': Decimal('0.01'),
    },
    'CDF': {
        'name': 'Franc Congolais',
        'symbol': 'FC',
        'decimal_places': 2,
        'is_fiat': True,
        'is_crypto': False,
        'min_amount': Decimal('1'),
    },
    'GNF': {
        'name': 'Franc Guinéen',
        'symbol': 'FG',
        'decimal_places': 0,
        'is_fiat': True,
        'is_crypto': False,
        'min_amount': Decimal('1'),
    },
}


# ============================================================================
# FONCTIONS PUBLIQUES
# ============================================================================

def get_currency_by_country_code(country_code: str) -> str:
    """
    Détermine la devise basée sur le code pays.
    
    Args:
        country_code: Code pays avec '+' (ex: '+33', '+225')
    
    Returns:
        Code devise (ex: 'EUR', 'XOF')
    
    Raises:
        ValueError: Si country_code est invalide
    """
    if not country_code or not country_code.startswith('+'):
        logger.warning(
            "invalid_country_code_format",
            country_code=country_code,
            default_currency=DEFAULT_CURRENCY
        )
        return DEFAULT_CURRENCY
    
    currency = COUNTRY_CURRENCY_MAPPING.get(country_code, DEFAULT_CURRENCY)
    
    logger.debug(
        "currency_determined",
        country_code=country_code,
        currency=currency
    )
    
    return currency


def get_currency_info(currency_code: str) -> dict:
    """
    Récupère les informations d'une devise.
    
    Args:
        currency_code: Code devise (ex: 'EUR', 'XOF')
    
    Returns:
        Dictionnaire avec les informations de la devise
    
    Raises:
        ValueError: Si la devise n'est pas supportée
    """
    info = CURRENCY_INFO.get(currency_code.upper())
    
    if not info:
        logger.error(
            "unsupported_currency",
            currency_code=currency_code
        )
        raise ValueError(f"Devise non supportée: {currency_code}")
    
    return info.copy()  # Retourne une copie pour éviter la modification


def get_currency_name(currency_code: str) -> str:
    """
    Récupère le nom d'une devise.
    
    Args:
        currency_code: Code devise
    
    Returns:
        Nom de la devise
    """
    try:
        info = get_currency_info(currency_code)
        return info['name']
    except ValueError:
        return currency_code  # Retourne le code si devise inconnue


def get_currency_symbol(currency_code: str) -> str:
    """
    Récupère le symbole d'une devise.
    
    Args:
        currency_code: Code devise
    
    Returns:
        Symbole de la devise
    """
    try:
        info = get_currency_info(currency_code)
        return info['symbol']
    except ValueError:
        return currency_code


def get_currency_decimal_places(currency_code: str) -> int:
    """
    Récupère le nombre de décimales pour une devise.
    
    Args:
        currency_code: Code devise
    
    Returns:
        Nombre de décimales
    """
    try:
        info = get_currency_info(currency_code)
        return info['decimal_places']
    except ValueError:
        return 2  # Valeur par défaut


def format_amount(amount, currency_code: str, include_symbol: bool = True) -> str:
    """
    Formate un montant selon les conventions de la devise.
    
    Args:
        amount: Montant (Decimal, float, int)
        currency_code: Code devise
        include_symbol: Inclure le symbole monétaire
    
    Returns:
        Montant formaté (ex: "1 000,50 €" ou "1 000 CFA")
    """
    from decimal import Decimal
    
    # Convertir en Decimal
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    
    try:
        info = get_currency_info(currency_code)
        decimal_places = info['decimal_places']
        symbol = info['symbol']
        
        # Formater le nombre
        # Format français : 1 000,50
        formatted = f"{amount:,.{decimal_places}f}"
        formatted = formatted.replace(',', ' ').replace('.', ',')
        
        # Retirer les .00 pour les devises sans décimales
        if decimal_places == 0:
            formatted = formatted.replace(',00', '')
        
        # Ajouter le symbole
        if include_symbol:
            # Symboles qui se placent avant (€, $, £)
            if symbol in ['€', '$', '£']:
                return f"{symbol}{formatted}"
            # Symboles qui se placent après
            else:
                return f"{formatted} {symbol}"
        else:
            return formatted
            
    except ValueError:
        # Fallback si devise inconnue
        return f"{amount} {currency_code}"


def is_currency_supported(currency_code: str) -> bool:
    """
    Vérifie si une devise est supportée.
    
    Args:
        currency_code: Code devise
    
    Returns:
        True si la devise est supportée
    """
    return currency_code.upper() in CURRENCY_INFO


def validate_amount_for_currency(amount, currency_code: str) -> bool:
    """
    Valide qu'un montant est valide pour une devise.
    
    Args:
        amount: Montant à valider
        currency_code: Code devise
    
    Returns:
        True si le montant est valide
    """
    from decimal import Decimal, InvalidOperation
    
    try:
        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))
        
        info = get_currency_info(currency_code)
        min_amount = info.get('min_amount', Decimal('0.01'))
        
        # Vérifier que c'est un multiple de l'unité minimale
        if amount < min_amount:
            return False
        
        # Vérifier les décimales
        decimal_places = info['decimal_places']
        # Vérifier qu'il n'y a pas plus de décimales que permis
        if amount.as_tuple().exponent < -decimal_places:
            return False
            
        return True
        
    except (ValueError, InvalidOperation):
        return False


# ============================================================================
# FONCTIONS POUR L'INITIALISATION
# ============================================================================

def initialize_currencies():
    """
    Initialise les devises dans la base de données.
    À exécuter dans une migration ou un script de setup.
    """
    from ..models import Currency
    
    currencies_created = 0
    currencies_updated = 0
    
    for code, info in CURRENCY_INFO.items():
        currency, created = Currency.objects.update_or_create(
            code=code,
            defaults={
                'name': info['name'],
                'symbol': info['symbol'],
                'decimal_places': info['decimal_places'],
                'is_active': True,
            }
        )
        
        if created:
            currencies_created += 1
            logger.info(f"Devise créée: {code}")
        else:
            currencies_updated += 1
            logger.debug(f"Devise mise à jour: {code}")
    
    logger.info(
        "currencies_initialized",
        created=currencies_created,
        updated=currencies_updated,
        total=len(CURRENCY_INFO)
    )
    
    return currencies_created, currencies_updated