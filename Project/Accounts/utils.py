# apps/auth/utils.py
import uuid
import re
import ipaddress
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings
import structlog
from datetime import datetime
from typing import Dict, Any, Optional
logger = structlog.get_logger(__name__)


class AuthUtils:
    """
    Classe utilitaire centralisée pour éviter la duplication de code.
    Toutes les méthodes sont statiques pour une utilisation facile.
    """
    
    @staticmethod
    def mask_phone(phone_number):
        """
        Masque partiellement un numéro de téléphone pour la protection des données.
        Exemple: +33612345678 → +33612****78
        """
        if not phone_number or not isinstance(phone_number, str):
            return "****"
        
        if len(phone_number) > 6:
            # Garde les 6 premiers et 2 derniers caractères
            return phone_number[:6] + "****" + phone_number[-2:]
        
        return "****"
    
    @staticmethod
    def get_client_ip(request):
        """
        Récupère l'adresse IP réelle du client en gérant les proxies.
        Priorité: X-Forwarded-For > REMOTE_ADDR
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            # Prend la première IP non-trusted
            ips = [ip.strip() for ip in x_forwarded_for.split(',')]
            # Filtrage des IPs locales/proxies (configuration optionnelle)
            trusted_proxies = getattr(settings, 'TRUSTED_PROXIES', [])
            for ip in ips:
                if not AuthUtils._is_ip_in_subnets(ip, trusted_proxies):
                    return ip
            # Si toutes sont trusted, retourne la première
            return ips[0] if ips else ''
        
        return request.META.get('REMOTE_ADDR', '')
    
    @staticmethod
    def extract_request_metadata(request):
        """
        Extrait et nettoie les métadonnées de la requête pour logs et sécurité.
        Limite la taille des champs pour éviter les problèmes de stockage.
        """
        client_ip = AuthUtils.get_client_ip(request)
        
        return {
            'client_ip': client_ip,
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:500],
            'device_id': request.META.get('HTTP_X_DEVICE_ID', '').strip(),
            'app_version': request.META.get('HTTP_X_APP_VERSION', '').strip(),
            'accept_language': request.META.get('HTTP_ACCEPT_LANGUAGE', '')[:50],
            'referer': request.META.get('HTTP_REFERER', '')[:200],
            'timestamp': timezone.now().isoformat(),
            'platform': AuthUtils._detect_platform(request)
        }
    
    @staticmethod
    def is_valid_ip(ip):
        """Valide une adresse IPv4 ou IPv6."""
        if not ip:
            return False
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False
    
    @staticmethod
    def validate_e164_format(phone_number):
        """Valide le format E.164 d'un numéro de téléphone."""
        if not phone_number or not isinstance(phone_number, str):
            return False
        return re.match(r'^\+\d{10,15}$', phone_number) is not None
    
    @staticmethod
    def generate_session_key(prefix="auth"):
        """Génère une clé de session sécurisée et unique."""
        return f"{prefix}_{uuid.uuid4().hex[:16]}"
    
    @staticmethod
    def create_auth_session(session_key, full_phone_number, **session_data):
        """
        Crée une session d'authentification standardisée.
        
        Args:
            session_key: La clé de session générée
            full_phone_number: Numéro en format E.164
            **session_data: Données supplémentaires à stocker
        """
        expires_at = timezone.now() + timezone.timedelta(minutes=5)
        
        default_session_data = {
            "full_phone_number": full_phone_number,
            "created_at": timezone.now().isoformat(),
            "expires_at": expires_at.isoformat(),
            "attempts": 0,
            "verified": False,
            "last_attempt": None,
        }
        
        # Fusion avec les données spécifiques
        session_data_combined = {**default_session_data, **session_data}
        
        # Stockage dans le cache
        cache.set(session_key, session_data_combined, timeout=300)
        
        logger.debug(
            "session_created",
            session_key=session_key[:8] + "...",
            phone_number=AuthUtils.mask_phone(full_phone_number),
            expires_in="5min"
        )
        
        return session_key  # Optionnel
    
    @staticmethod
    def update_session_attempt(session_key, increment=True):
        """Met à jour le compteur de tentatives d'une session."""
        session_data = cache.get(session_key)
        if session_data:
            if increment:
                session_data['attempts'] = session_data.get('attempts', 0) + 1
            session_data['last_attempt'] = timezone.now().isoformat()
            cache.set(session_key, session_data, timeout=cache.ttl(session_key) or 300)
        return session_data
    
    @staticmethod
    def is_rate_limited(identifier, limit=5, window_seconds=600):
        """
        Vérifie si un identifiant (phone ou IP) est rate limited.
        """
        cache_key = f"rate_limit_{identifier}"
        attempts = cache.get(cache_key, [])
        
        now = timezone.now()
        # Garder seulement les tentatives récentes
        recent_attempts = [
            t for t in attempts 
            if (now - t).total_seconds() < window_seconds
        ]
        
        if len(recent_attempts) >= limit:
            return True
        
        # Ajouter la tentative actuelle
        recent_attempts.append(now)
        cache.set(cache_key, recent_attempts, timeout=window_seconds)
        
        return False
    
    # Méthodes privées auxiliaires
    @staticmethod
    def _is_ip_in_subnets(ip, subnets):
        """Vérifie si une IP appartient à une liste de sous-réseaux."""
        if not ip or not subnets:
            return False
        
        try:
            ip_obj = ipaddress.ip_address(ip)
            for subnet_str in subnets:
                try:
                    subnet = ipaddress.ip_network(subnet_str, strict=False)
                    if ip_obj in subnet:
                        return True
                except ValueError:
                    continue
        except ValueError:
            pass
        
        return False
    
    @staticmethod
    def _detect_platform(request):
        """Détecte la plateforme depuis les headers ou user agent."""
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        device_id = request.META.get('HTTP_X_DEVICE_ID', '')
        app_version = request.META.get('HTTP_X_APP_VERSION', '')
        
        if app_version or 'mobile' in user_agent or device_id:
            if 'android' in user_agent:
                return 'android'
            elif 'iphone' in user_agent or 'ipad' in user_agent:
                return 'ios'
            return 'mobile'
        
        return 'web'

    # Dans utils.py - ajoute cette méthode à la classe AuthUtils
    @staticmethod
    def get_session_ttl(session_key, session_data=None):
        """
        Retourne le temps restant pour une session en secondes.
        Compatible avec LocMemCache et autres backends.
        
        Args:
            session_key: Clé de la session
            session_data: Données de session (optionnel, évite un cache.get())
            
        Returns:
            int: Secondes restantes avant expiration
        """
        # Essayer d'abord la méthode standard (pour Redis)
        try:
            ttl = cache.ttl(session_key)
            if ttl is not None:
                return max(0, ttl)
        except AttributeError:
            # cache.ttl() n'existe pas (LocMemCache)
            pass
        
        # Fallback: calcul depuis expires_at
        if session_data is None:
            session_data = cache.get(session_key)
        
        if not session_data or 'expires_at' not in session_data:
            return 0
        
        expires_at_str = session_data['expires_at']
        
        try:
            from django.utils import timezone
            from datetime import datetime
            
            # Nettoyer la chaîne ISO
            if 'Z' in expires_at_str:
                expires_at_str = expires_at_str.replace('Z', '+00:00')
            
            expires_at = datetime.fromisoformat(expires_at_str)
            
            # S'assurer que c'est timezone aware
            if timezone.is_naive(expires_at):
                expires_at = timezone.make_aware(expires_at)
            
            now = timezone.now()
            time_remaining = (expires_at - now).total_seconds()
            
            return max(0, int(time_remaining))
        except (ValueError, TypeError, AttributeError):
            return 0
# Instance globale pour import facile
auth_utils = AuthUtils()
#### A supprimer si non plus neccessaire ####
class DiditDataExtractor:
    """
    Extrait et nettoie les données pertinentes de la réponse Didit.
    Principe Single Responsibility.
    """
    
    @staticmethod
    def extract_essential_data(didit_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extrait uniquement les données essentielles de la réponse Didit.
        """
        id_verification = didit_response.get("id_verification", {})
        
        # Données de base
        essential = {
            # Statut et identification
            "status": id_verification.get("status"),
            "document_type": id_verification.get("document_type"),
            "document_number": id_verification.get("document_number"),
            "personal_number": id_verification.get("personal_number"),
            
            # Informations personnelles
            "first_name": id_verification.get("first_name"),
            "last_name": id_verification.get("last_name"),
            "full_name": id_verification.get("full_name"),
            "date_of_birth": id_verification.get("date_of_birth"),
            "age": id_verification.get("age"),
            "gender": id_verification.get("gender"),
            "nationality": id_verification.get("nationality"),
            "place_of_birth": id_verification.get("place_of_birth"),
            "marital_status": id_verification.get("marital_status"),
            
            # Document info
            "issuing_state": id_verification.get("issuing_state"),
            "issuing_state_name": id_verification.get("issuing_state_name"),
            "date_of_issue": id_verification.get("date_of_issue"),
            "expiration_date": id_verification.get("expiration_date"),
            
            # Adresse
            "address": id_verification.get("address"),
            "formatted_address": id_verification.get("formatted_address"),
            
            # Calculs
            "is_expired": DiditDataExtractor._check_if_expired(
                id_verification.get("expiration_date")
            ),
            "days_until_expiry": DiditDataExtractor._calculate_days_until_expiry(
                id_verification.get("expiration_date")
            ),
        }
        
        # Nettoyer les valeurs None
        return {k: v for k, v in essential.items() if v is not None}
    
    @staticmethod
    def extract_warnings(didit_response: Dict[str, Any]) -> list:
        """Extrait les warnings de la réponse."""
        id_verification = didit_response.get("id_verification", {})
        warnings = id_verification.get("warnings", [])
        
        # Formater les warnings
        formatted_warnings = []
        for warning in warnings:
            formatted_warnings.append({
                "risk": warning.get("risk"),
                "short_description": warning.get("short_description"),
                "log_type": warning.get("log_type"),
            })
        
        return formatted_warnings
    
    @staticmethod
    def extract_decline_reason(didit_response: Dict[str, Any]) -> Optional[str]:
        """Extrait la raison du déclin."""
        warnings = DiditDataExtractor.extract_warnings(didit_response)
        
        if warnings:
            # Prendre le premier warning comme raison principale
            first_warning = warnings[0]
            return f"{first_warning.get('risk')}: {first_warning.get('short_description')}"
        
        return None
    
    @staticmethod
    def _check_if_expired(expiration_date_str: Optional[str]) -> bool:
        """Vérifie si le document est expiré."""
        if not expiration_date_str:
            return False
        
        try:
            expiry_date = datetime.strptime(expiration_date_str, "%Y-%m-%d").date()
            return expiry_date < datetime.now().date()
        except (ValueError, TypeError):
            return False
    
    @staticmethod
    def _calculate_days_until_expiry(expiration_date_str: Optional[str]) -> Optional[int]:
        """Calcule les jours avant expiration."""
        if not expiration_date_str:
            return None
        
        try:
            expiry_date = datetime.strptime(expiration_date_str, "%Y-%m-%d").date()
            today = datetime.now().date()
            
            if expiry_date >= today:
                return (expiry_date - today).days
            return 0  # Déjà expiré
        except (ValueError, TypeError):
            return None