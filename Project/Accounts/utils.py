import os
import phonenumbers
from phonenumbers.phonenumberutil import NumberParseException
import secrets
from django.utils import timezone
from datetime import timedelta
from .models import OTPCode, User
from twilio.rest import Client


def validate_phone_number(phone_number, country_code='+33'):
    """
    Valide un numéro de téléphone avec un code pays
    
    Args:
        phone_number (str): Numéro de téléphone
        country_code (str): Code pays (ex: +33)
    
    Returns:
        tuple: (is_valid, formatted_number, error_message)
    """
    try:
        # Nettoyer le numéro
        cleaned_number = ''.join(filter(str.isdigit, str(phone_number)))
        
        # Parser avec phonenumbers
        parsed = phonenumbers.parse(f"{country_code}{cleaned_number}")
        
        if not phonenumbers.is_valid_number(parsed):
            return False, None, "Numéro de téléphone invalide"
        
        # Formater le numéro
        formatted = phonenumbers.format_number(
            parsed, 
            phonenumbers.PhoneNumberFormat.E164
        )
        
        return True, formatted, None
        
    except NumberParseException:
        return False, None, "Format de numéro invalide"
    except Exception as e:
        return False, None, f"Erreur de validation: {str(e)}"


def extract_country_code_and_number(full_number):
    """
    Extrait le code pays et le numéro d'un numéro complet
    
    Args:
        full_number (str): Numéro complet (ex: +33612345678)
    
    Returns:
        tuple: (country_code, phone_number) ou (None, None) si invalide
    """
    try:
        parsed = phonenumbers.parse(full_number)
        country_code = f"+{parsed.country_code}"
        
        # Extraire le numéro national
        national_number = str(parsed.national_number)
        
        return country_code, national_number
        
    except Exception:
        return None, None


def normalize_phone_input(phone_input, default_country='+33'):
    """
    Normalise une entrée téléphone qui peut être:
    - Numéro seul (0612345678)
    - Numéro avec code (33612345678)
    - Numéro complet (+33612345678)
    
    Returns:
        tuple: (country_code, phone_number)
    """
    # Si le numéro commence par +, on le parse
    if phone_input.startswith('+'):
        return extract_country_code_and_number(phone_input)
    
    # Si le numéro commence par 0 (France), on ajoute +33
    elif phone_input.startswith('0'):
        phone_number = phone_input[1:]  # Enlever le 0
        return default_country, phone_number
    
    # Si le numéro commence par 33 (sans +)
    elif phone_input.startswith('33'):
        phone_number = phone_input[2:]  # Enlever 33
        return '+33', phone_number
    
    # Sinon, on utilise le code par défaut
    else:
        return default_country, phone_input
    
    
# OTP Utilities
def generate_secure_otp():
    """
    Génère un OTP sécurisé de 6 chiffres
    Utilise secrets pour la sécurité cryptographique
    """
    # Génère un nombre entre 0 et 999999
    otp_number = secrets.randbelow(1_000_000)
    
    # Format sur 6 chiffres avec zéros devant si besoin
    return f"{otp_number:06d}"


def generate_unique_otp(user, max_attempts=10):
    """
    Génère un OTP unique pour cet utilisateur
    Vérifie qu'il n'existe pas déjà (non expiré)
    """
    for attempt in range(max_attempts):
        otp_code = generate_secure_otp()
        
        # Vérifier si ce code existe déjà (non expiré et non utilisé)
        exists = OTPCode.objects.filter(
            user=user,
            code=otp_code,
            used=False,
            expires_at__gt=timezone.now()
        ).exists()
        
        if not exists:
            return otp_code
    
    # Si trop de collisions (très rare), retourne un OTP simple
    return generate_secure_otp()


def create_otp_for_user(user, expires_in_minutes=10):
    """
    Crée et enregistre un OTP pour un utilisateur
    Retourne le code OTP
    """
    # Générer un OTP unique
    otp_code = generate_unique_otp(user)
    
    # Calculer la date d'expiration
    expires_at = timezone.now() + timedelta(minutes=expires_in_minutes)
    
    # Créer l'objet OTP en base
    OTPCode.objects.create(
        user=user,
        code=otp_code,
        expires_at=expires_at
    )
    
    return otp_code


def validate_otp(phone_number, otp_code):
    """
    Valide un code OTP pour un numéro de téléphone
    Retourne (success, message, user) ou (success, message, None)
    """
    
    # Chercher l'utilisateur
    try:
        user = User.objects.get(phone_number=phone_number)
    except User.DoesNotExist:
        return False, "Numéro de téléphone non trouvé", None
    
    # Chercher l'OTP valide le plus récent
    try:
        otp_obj = OTPCode.objects.filter(
            user=user,
            code=otp_code,
            used=False
        ).latest('created_at')
        
        # Vérifier si l'OTP est encore valide
        if otp_obj.expires_at < timezone.now():
            return False, "Code OTP expiré", None
        
        # Marquer comme utilisé
        otp_obj.used = True
        otp_obj.save()
        
        return True, "Code OTP valide", user
        
    except OTPCode.DoesNotExist:
        return False, "Code OTP invalide", None


def cleanup_expired_otps():
    """
    Nettoie les OTP expirés (peut être appelé par une tâche cron)
    """
    expired_count = OTPCode.objects.filter(
        expires_at__lt=timezone.now()
    ).delete()[0]
    
    return expired_count


def get_active_otps_count(user=None):
    """
    Retourne le nombre d'OTP actifs (non expirés, non utilisés)
    Optionnellement pour un utilisateur spécifique
    """
    queryset = OTPCode.objects.filter(
        used=False,
        expires_at__gt=timezone.now()
    )
    
    if user:
        queryset = queryset.filter(user=user)
    
    return queryset.count()

ACCOUNT_SID = os.getenv('ACCOUNT_SID')
AUTH_TOKEN = os.getenv('AUTH_TOKEN')
# Fonction pour simulation SMS (développement)
def simulate_sms_send(phone_number, otp_code, provider="TwiliSandbox"):
    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    """
    Simule l'envoi d'un SMS (à remplacer par vrai service en production)
    
    Args:
        phone_number: Numéro de téléphone
        otp_code: Code OTP
        provider: Nom du fournisseur simulé
    
    Returns:
        dict: Informations sur l'envoi simulé
    """
    message = client.messages.create(
    from_='whatsapp:+14155238886',  # Numéro sandbox par défaut
    body='Bonjour depuis le sandbox WhatsApp de Twilio ! 🚀',
    to=f'whatsapp:{phone_number}'      # Ton numéro WhatsApp (avec indicatif)
)
    
    return {
        "success": True,
        "provider": provider,
        "phone_number": phone_number,
        "timestamp": timezone.now().isoformat(),
    }