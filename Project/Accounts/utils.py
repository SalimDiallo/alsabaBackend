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
    Centralized utility class to avoid code duplication.
    All methods are static for easy usage.
    """
    
    @staticmethod
    def mask_phone(phone_number):
        """
        Partially masks a phone number for data protection.
        Example: +33612345678 → +33612****78
        """
        if not phone_number or not isinstance(phone_number, str):
            return "****"
        
        if len(phone_number) > 6:
            # Keep the first 6 and last 2 characters
            return phone_number[:6] + "****" + phone_number[-2:]
        
        return "****"
    
    @staticmethod
    def get_client_ip(request):
        """
        ✅ SECURE: Retrieves the real client IP address by handling proxies.
        Validates X-Forwarded-For and falls back to REMOTE_ADDR if invalid.
        Priority: X-Forwarded-For (last valid IP) > REMOTE_ADDR
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            # Take the LAST IP because it's the real client (the first is the trusted proxy)
            ips = [ip.strip() for ip in x_forwarded_for.split(',')]
            
            # Validate that it's a correct IP
            for ip in reversed(ips):  # Check from last to first
                if AuthUtils.is_valid_ip(ip):
                    return ip
            
            logger.warning("invalid_x_forwarded_for", value=x_forwarded_for[:50])
        
        # Fallback to REMOTE_ADDR
        remote_addr = request.META.get('REMOTE_ADDR', '')
        if AuthUtils.is_valid_ip(remote_addr):
            return remote_addr
        
        logger.warning("invalid_remote_addr", value=remote_addr[:50])
        return ''  # Invalid IP
    
    @staticmethod
    def extract_request_metadata(request):
        """
        Extracts and cleans request metadata for logs and security.
        Limits field size to avoid storage issues.
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
        """✅ Validates an IPv4 or IPv6 address."""
        if not ip:
            return False
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False
    
    @staticmethod
    def validate_e164_format(phone_number):
        """Validates the E.164 format of a phone number."""
        if not phone_number or not isinstance(phone_number, str):
            return False
        return re.match(r'^\+\d{10,15}$', phone_number) is not None
    
    @staticmethod
    def generate_session_key(prefix="auth"):
        """Generates a secure and unique session key."""
        return f"{prefix}_{uuid.uuid4().hex[:16]}"
    
    @staticmethod
    def create_auth_session(session_key, full_phone_number, **session_data):
        """
        Creates a standardized authentication session.
        
        Args:
            session_key: The generated session key
            full_phone_number: Number in E.164 format
            **session_data: Additional data to store
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
        
        # Merge with specific data
        session_data_combined = {**default_session_data, **session_data}
        
        # Storage in cache
        cache.set(session_key, session_data_combined, timeout=300)
        
        logger.debug(
            "session_created",
            session_key=session_key[:8] + "...",
            phone_number=AuthUtils.mask_phone(full_phone_number),
            expires_in="5min"
        )
        
        return session_key  # Optional
    
    @staticmethod
    def update_session_attempt(session_key, increment=True):
        """Updates the attempt counter of a session."""
        session_data = cache.get(session_key)
        if session_data:
            if increment:
                session_data['attempts'] = session_data.get('attempts', 0) + 1
            session_data['last_attempt'] = timezone.now().isoformat()
            # Use get_session_ttl for LocMemCache compatibility
            ttl = AuthUtils.get_session_ttl(session_key, session_data)
            cache.set(session_key, session_data, timeout=ttl or 300)
        return session_data
    
    @staticmethod
    def is_rate_limited(identifier, limit=5, window_seconds=600):
        """
        Vérifie si un identifiant (phone ou IP) est rate limited.
        ATTENTION: Cette méthode incrémente le compteur à chaque appel.
        Utilisez check_rate_limit si vous voulez seulement vérifier.
        """
        cache_key = f"rate_limit_{identifier}"
        attempts = cache.get(cache_key, [])
        
        now = timezone.now()
        # Keep only recent attempts
        recent_attempts = [
            t for t in attempts 
            if (now - t).total_seconds() < window_seconds
        ]
        
        if len(recent_attempts) >= limit:
            return True
        
        # Add current attempt
        recent_attempts.append(now)
        cache.set(cache_key, recent_attempts, timeout=window_seconds)
        
        return False
    
    @staticmethod
    def check_rate_limit(identifier, limit=5, window_seconds=600):
        """
        Vérifie si un identifiant est rate limited SANS incrémenter le compteur.
        Utile pour vérifier avant d'autoriser une action.
        """
        cache_key = f"rate_limit_{identifier}"
        attempts = cache.get(cache_key, [])
        
        now = timezone.now()
        # Garder seulement les tentatives récentes
        recent_attempts = [
            t for t in attempts 
            if (now - t).total_seconds() < window_seconds
        ]
        
        return len(recent_attempts) >= limit
    
    @staticmethod
    def increment_rate_limit(identifier, window_seconds=600):
        """
        Incrémente le compteur de rate limiting pour un identifiant.
        Appeler cette méthode seulement après que l'action a été effectuée.
        """
        cache_key = f"rate_limit_{identifier}"
        attempts = cache.get(cache_key, [])
        
        now = timezone.now()
        # Garder seulement les tentatives récentes
        recent_attempts = [
            t for t in attempts 
            if (now - t).total_seconds() < window_seconds
        ]
        
        recent_attempts.append(now)
        cache.set(cache_key, recent_attempts, timeout=window_seconds)
    
    @staticmethod
    def get_rate_limit_remaining(identifier, limit=5, window_seconds=600):
        """
        Retourne le nombre de tentatives restantes pour un identifiant.
        Utile pour informer l'utilisateur.
        """
        cache_key = f"rate_limit_{identifier}"
        attempts = cache.get(cache_key, [])
        
        now = timezone.now()
        recent_attempts = [
            t for t in attempts 
            if (now - t).total_seconds() < window_seconds
        ]
        
        return max(0, limit - len(recent_attempts))
    
    @staticmethod
    def clear_rate_limit(identifier):
        """
        Efface le compteur de rate limiting pour un identifiant.
        Utile pour les tests ou après une vérification réussie.
        """
        cache_key = f"rate_limit_{identifier}"
        cache.delete(cache_key)
        logger.info("rate_limit_cleared", identifier=identifier[:20] if identifier else "")
    
    # Méthodes privées auxiliaires
    @staticmethod
    def _is_ip_in_subnets(ip, subnets):
        """Checks if an IP belongs to a list of subnets."""
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
        """Detects the platform from headers or user agent."""
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

    # In utils.py - add this method to the AuthUtils class
    @staticmethod
    def get_session_ttl(session_key, session_data=None):
        """
        Returns the remaining time for a session in seconds.
        Compatible with LocMemCache and other backends.
        
        Args:
            session_key: Session key
            session_data: Session data (optional, avoids a cache.get())
            
        Returns:
            int: Remaining seconds before expiration
        """
        # Try standard method first (for Redis)
        try:
            ttl = cache.ttl(session_key)
            if ttl is not None:
                return max(0, ttl)
        except AttributeError:
            # cache.ttl() does not exist (LocMemCache)
            pass
        
        # Fallback: calculation from expires_at
        if session_data is None:
            session_data = cache.get(session_key)
        
        if not session_data or 'expires_at' not in session_data:
            return 0
        
        expires_at_str = session_data['expires_at']
        
        try:
            from django.utils import timezone
            from datetime import datetime
            
            # Clean ISO string
            if 'Z' in expires_at_str:
                expires_at_str = expires_at_str.replace('Z', '+00:00')
            
            expires_at = datetime.fromisoformat(expires_at_str)
            
            # Ensure it is timezone aware
            if timezone.is_naive(expires_at):
                expires_at = timezone.make_aware(expires_at)
            
            now = timezone.now()
            time_remaining = (expires_at - now).total_seconds()
            
            return max(0, int(time_remaining))
        except (ValueError, TypeError, AttributeError):
            return 0
# Global instance for easy import
auth_utils = AuthUtils()