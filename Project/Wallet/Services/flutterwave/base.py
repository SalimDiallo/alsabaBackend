"""
Service de base Flutterwave avec gestion des environnements et retry logic
"""
import requests
import time
import structlog
from django.conf import settings
from typing import Dict, Optional, Any

logger = structlog.get_logger(__name__)


class FlutterwaveBaseService:
    """
    Service de base pour l'intégration Flutterwave
    Gère l'environnement (sandbox/production), les tokens, et les retries
    """
    
    def __init__(self):
        self.environment = getattr(settings, 'FLUTTERWAVE_ENVIRONMENT', 'sandbox')
        self.timeout = getattr(settings, 'FLUTTERWAVE_TIMEOUT', 30)
        self.max_retries = getattr(settings, 'FLUTTERWAVE_MAX_RETRIES', 3)
        self.retry_delay = getattr(settings, 'FLUTTERWAVE_RETRY_DELAY', 2)
        
        # Configuration selon l'environnement
        if self.environment == 'production':
            self.client_id = getattr(settings, 'FLUTTERWAVE_PRODUCTION_CLIENT_ID', '')
            self.client_secret = getattr(settings, 'FLUTTERWAVE_PRODUCTION_CLIENT_SECRET', '')
            self.encryption_key = getattr(settings, 'FLUTTERWAVE_PRODUCTION_ENCRYPTION_KEY', '')
            self.base_url = getattr(settings, 'FLUTTERWAVE_PRODUCTION_BASE_URL', 'https://api.flutterwave.com')
            self.auth_url = getattr(settings, 'FLUTTERWAVE_PRODUCTION_AUTH_URL', 
                                   'https://idp.flutterwave.com/realms/flutterwave/protocol/openid-connect/token')
        else:  # sandbox
            self.client_id = getattr(settings, 'FLUTTERWAVE_SANDBOX_CLIENT_ID', '')
            self.client_secret = getattr(settings, 'FLUTTERWAVE_SANDBOX_CLIENT_SECRET', '')
            self.encryption_key = getattr(settings, 'FLUTTERWAVE_SANDBOX_ENCRYPTION_KEY', '')
            self.base_url = getattr(settings, 'FLUTTERWAVE_SANDBOX_BASE_URL', 
                                   'https://developersandbox-api.flutterwave.com')
            self.auth_url = getattr(settings, 'FLUTTERWAVE_SANDBOX_AUTH_URL',
                                   'https://idp.flutterwave.com/realms/flutterwave/protocol/openid-connect/token')
        
        self.redirect_url = getattr(settings, 'FLUTTERWAVE_REDIRECT_URL', '')
        self.webhook_secret = getattr(settings, 'FLUTTERWAVE_WEBHOOK_SECRET', '')
        
        # Cache pour le token (éviter de le régénérer à chaque requête)
        self._cached_token = None
        self._token_expires_at = 0
    
    def get_access_token(self, force_refresh: bool = False) -> str:
        """
        Obtient un token d'accès OAuth2 avec cache
        
        Args:
            force_refresh: Force le rafraîchissement même si le token est encore valide
            
        Returns:
            str: Token d'accès
        """
        # Vérifier le cache (token valide pendant ~1h généralement)
        if not force_refresh and self._cached_token and time.time() < self._token_expires_at:
            return self._cached_token
        
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        try:
            resp = requests.post(self.auth_url, data=payload, headers=headers, timeout=self.timeout)
            if resp.status_code == 200:
                token_data = resp.json()
                access_token = token_data["access_token"]
                expires_in = token_data.get("expires_in", 3600)  # Par défaut 1h
                
                # Mettre en cache
                self._cached_token = access_token
                self._token_expires_at = time.time() + expires_in - 60  # -60s pour marge de sécurité
                
                logger.info("flutterwave_token_obtained", environment=self.environment)
                return access_token
            else:
                logger.error("flutterwave_token_error", 
                           status_code=resp.status_code, 
                           response=resp.text,
                           environment=self.environment)
                raise Exception(f"Erreur token: {resp.text}")
        except requests.RequestException as e:
            logger.error("flutterwave_token_request_error", 
                        error=str(e),
                        environment=self.environment)
            raise
    
    def _make_request(self, method: str, endpoint: str, token: Optional[str] = None, 
                     data: Optional[Dict] = None, json_data: Optional[Dict] = None,
                     headers: Optional[Dict] = None, retry: bool = True) -> Dict[str, Any]:
        """
        Effectue une requête HTTP avec retry automatique
        
        Args:
            method: Méthode HTTP (GET, POST, PUT, etc.)
            endpoint: Endpoint relatif (ex: "/charges")
            token: Token d'accès (si None, sera obtenu automatiquement)
            data: Données pour POST form-data
            json_data: Données JSON
            headers: Headers additionnels
            retry: Activer les retries
            
        Returns:
            dict: Réponse JSON
            
        Raises:
            Exception: En cas d'erreur après tous les retries
        """
        if token is None:
            token = self.get_access_token()
        
        url = f"{self.base_url}{endpoint}"
        request_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Trace-Id": str(time.time_ns()),  # Trace ID unique
        }
        
        if headers:
            request_headers.update(headers)
        
        # Retry logic
        last_exception = None
        for attempt in range(self.max_retries if retry else 1):
            try:
                if method.upper() == 'GET':
                    resp = requests.get(url, headers=request_headers, timeout=self.timeout)
                elif method.upper() == 'POST':
                    if data:
                        resp = requests.post(url, data=data, headers=request_headers, timeout=self.timeout)
                    else:
                        resp = requests.post(url, json=json_data, headers=request_headers, timeout=self.timeout)
                elif method.upper() == 'PUT':
                    resp = requests.put(url, json=json_data, headers=request_headers, timeout=self.timeout)
                elif method.upper() == 'PATCH':
                    resp = requests.patch(url, json=json_data, headers=request_headers, timeout=self.timeout)
                else:
                    raise ValueError(f"Méthode HTTP non supportée: {method}")
                
                # Succès
                if resp.status_code in (200, 201):
                    return resp.json()
                
                # Erreur client (4xx) - ne pas retry
                if 400 <= resp.status_code < 500:
                    logger.error("flutterwave_client_error",
                               status_code=resp.status_code,
                               response=resp.text,
                               endpoint=endpoint,
                               attempt=attempt + 1)
                    raise Exception(f"Erreur client Flutterwave ({resp.status_code}): {resp.text}")
                
                # Erreur serveur (5xx) - retry
                if resp.status_code >= 500:
                    last_exception = Exception(f"Erreur serveur Flutterwave ({resp.status_code}): {resp.text}")
                    logger.warning("flutterwave_server_error",
                                 status_code=resp.status_code,
                                 endpoint=endpoint,
                                 attempt=attempt + 1,
                                 will_retry=attempt < self.max_retries - 1)
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay * (attempt + 1))  # Backoff exponentiel
                        continue
                    raise last_exception
                
                # Autre code - ne pas retry
                raise Exception(f"Erreur inattendue ({resp.status_code}): {resp.text}")
                
            except requests.Timeout as e:
                last_exception = e
                logger.warning("flutterwave_timeout",
                             endpoint=endpoint,
                             attempt=attempt + 1,
                             will_retry=attempt < self.max_retries - 1)
                if attempt < self.max_retries - 1 and retry:
                    time.sleep(self.retry_delay * (attempt + 1))
                    continue
                raise
            
            except requests.RequestException as e:
                last_exception = e
                logger.warning("flutterwave_request_error",
                             endpoint=endpoint,
                             error=str(e),
                             attempt=attempt + 1,
                             will_retry=attempt < self.max_retries - 1)
                if attempt < self.max_retries - 1 and retry:
                    time.sleep(self.retry_delay * (attempt + 1))
                    continue
                raise
        
        # Si on arrive ici, tous les retries ont échoué
        raise last_exception or Exception("Erreur inconnue lors de la requête")
    
    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        """
        Vérifie la signature d'un webhook Flutterwave
        
        Args:
            raw_body: Corps brut de la requête webhook
            signature: Signature fournie dans le header
            
        Returns:
            bool: True si la signature est valide
        """
        import hmac
        import hashlib
        import base64
        
        if not self.webhook_secret:
            logger.warning("webhook_secret_not_configured")
            return False
        
        try:
            # 1. Vérification standard Flutterwave (Secret Hash direct)
            if signature == self.webhook_secret:
                return True
                
            # 2. Fallback HMAC (si configuré comme tel)
            key = self.webhook_secret.encode('utf-8')
            computed = hmac.new(key, raw_body, hashlib.sha256).digest()
            computed_b64 = base64.b64encode(computed).decode('utf-8')
            
            # Comparaison sécurisée
            if hmac.compare_digest(computed_b64, signature):
                return True
                
            logger.warning(
                "webhook_signature_invalid",
                provided_signature=signature[:20] + "..." if signature else None
            )
            return False
            
        except Exception as e:
            logger.error("webhook_signature_verification_error", error=str(e))
            return False
