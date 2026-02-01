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
        # Helper pour nettoyer les variables d'environnement
        def clean_env(val):
            if isinstance(val, str):
                return val.strip().strip('"').strip("'")
            return val

        self.environment = clean_env(getattr(settings, 'FLUTTERWAVE_ENVIRONMENT', 'sandbox'))
        self.timeout = int(getattr(settings, 'FLUTTERWAVE_TIMEOUT', 30))
        self.max_retries = int(getattr(settings, 'FLUTTERWAVE_MAX_RETRIES', 3))
        self.retry_delay = int(getattr(settings, 'FLUTTERWAVE_RETRY_DELAY', 2))
        
        # Configuration V3 Standard
        self.secret_key = clean_env(getattr(settings, 'FLUTTERWAVE_SECRET_KEY', ''))
        self.public_key = clean_env(getattr(settings, 'FLUTTERWAVE_PUBLIC_KEY', ''))
        self.encryption_key = clean_env(getattr(settings, 'FLUTTERWAVE_ENCRYPTION_KEY', ''))
        
        # Base URL: Toujours /v3 pour la version actuelle
        self.base_url = "https://api.flutterwave.com/v3"
        
        # Si on est en sandbox, Flutterwave utilise parfois une URL différente ou simplement des clés de test
        # Version standard V3: api.flutterwave.com/v3
        sandbox_url = clean_env(getattr(settings, 'FLUTTERWAVE_SANDBOX_BASE_URL', ''))
        if self.environment != 'production' and sandbox_url:
            self.base_url = sandbox_url
        
        self.redirect_url = clean_env(getattr(settings, 'FLUTTERWAVE_REDIRECT_URL', 'https://google.com'))
        self.webhook_secret = clean_env(getattr(settings, 'FLUTTERWAVE_WEBHOOK_SECRET', ''))
    
    def validate_redirect_url(self, url: str) -> tuple[bool, str]:
        """
        Valide qu'une URL de redirection est acceptable par Flutterwave V3
        
        Args:
            url: URL à valider
            
        Returns:
            tuple: (is_valid, error_message)
        """
        import re
        
        if not url or not isinstance(url, str):
            return False, "URL vide ou invalide"
        
        # Nettoyage
        url = url.strip().strip('"').strip("'")
        
        # En production, HTTPS obligatoire
        if self.environment == 'production' and not url.startswith('https://'):
            return False, "HTTPS requis en production"
        
        # Pattern de validation (HTTP/HTTPS avec domaine valide)
        pattern = r'^https?://[\w\-\.]+(:\d+)?(/.*)?$'
        if not re.match(pattern, url):
            return False, "Format d'URL invalide"
        
        # Pas de localhost/127.0.0.1 en production
        if self.environment == 'production':
            if 'localhost' in url.lower() or '127.0.0.1' in url:
                return False, "localhost interdit en production"
        
        return True, ""
    
    def get_access_token(self, force_refresh: bool = False) -> str:
        """
        Obtient la clé secrète pour l'authentification V3.
        Note: Garde le nom de méthode pour compatibilité avec le reste du code.
        """
        return self.secret_key
    
    def _extract_error_message(self, response_text: str) -> str:
        """Extrait un message d'erreur lisible d'une réponse Flutterwave."""
        try:
            import json
            data = json.loads(response_text)
            
            # Cas 1: Erreur imbriquée (error.message)
            if isinstance(data, dict):
                error_obj = data.get("error")
                if isinstance(error_obj, dict):
                    return error_obj.get("message") or error_obj.get("type") or response_text
                
                # Cas 2: Message au top level
                return data.get("message") or response_text
            
            return response_text
        except:
            return response_text

    def _make_request(self, method: str, endpoint: str, token: Optional[str] = None, 
                     data: Optional[Dict] = None, json_data: Optional[Dict] = None,
                     headers: Optional[Dict] = None, retry: bool = True) -> Dict[str, Any]:
        """
        Effectue une requête HTTP avec retry automatique
        """
        if token is None:
            token = self.get_access_token()
        
        url = f"{self.base_url}{endpoint}"
        request_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Trace-Id": str(time.time_ns()),
        }
        
        if headers:
            request_headers.update(headers)
        
        last_exception = None
        for attempt in range(self.max_retries if retry else 1):
            try:
                # Log de la requête sortante (sans données sensibles si possible)
                logger.debug("flutterwave_request_start", method=method, endpoint=endpoint, attempt=attempt+1)
                
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
                
                # Succès (200, 201)
                if resp.status_code in (200, 201):
                    return resp.json()
                
                # Erreur client (4xx) - extraction message et log
                if 400 <= resp.status_code < 500:
                    error_msg = self._extract_error_message(resp.text)
                    logger.error("flutterwave_client_error",
                               status_code=resp.status_code,
                               error=error_msg,
                               endpoint=endpoint,
                               raw_response=resp.text if self.environment == 'sandbox' else 'HIDDEN')
                    raise Exception(f"Erreur Flutterwave ({resp.status_code}): {error_msg}")
                
                # Erreur serveur (5xx) - retry
                if resp.status_code >= 500:
                    last_exception = Exception(f"Erreur serveur Flutterwave ({resp.status_code})")
                    logger.warning("flutterwave_server_error",
                                 status_code=resp.status_code,
                                 endpoint=endpoint,
                                 response=resp.text if self.environment == 'sandbox' else 'HIDDEN',
                                 attempt=attempt + 1)
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay * (attempt + 1))
                        continue
                    raise last_exception
                
                raise Exception(f"Erreur inattendue ({resp.status_code})")
                
            except requests.Timeout as e:
                # ... existing logic for timeout ...
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

    def split_customer_name(self, name: str) -> tuple[str, str]:
        """
        Sépare un nom complet en prénom et nom, avec validation pour Flutterwave (min 2 caractères).
        Nettoie également les caractères spéciaux interdits.
        """
        import re
        if not name or not isinstance(name, str):
            return "User", "Customer"
            
        # Nettoyage: Flutterwave accepte lettres, espaces, virgules, points, apostrophes et tirets.
        # On supprime tout le reste (notamment le '+' des numéros de téléphone)
        # On autorise les caractères accentués courants (A-ÿ)
        name = re.sub(r'[^a-zA-ZÀ-ÿ\s,.\'\-]', '', name).strip()
        
        parts = name.split(maxsplit=1)
        
        first = parts[0] if parts else "User"
        last = parts[1] if len(parts) > 1 else "Customer"
        
        # Validation Flutterwave (min 2 chars, max 50)
        if len(first) < 2:
            first = f"{first}." if first else "User"
        if len(last) < 2:
            last = f"{last}." if last else "Customer"
            
        return first[:50], last[:50]

    def get_customer_id_by_email(self, email: str) -> str:
        """
        Récupère l'ID d'un customer Flutterwave par son email
        
        Args:
            email: Email du client
            
        Returns:
            str: ID du customer
        """
        token = self.get_access_token()
        # Endpoint pour lister/rechercher les customers
        endpoint = f"/customers?email={email}"
        
        try:
            response = self._make_request("GET", endpoint, token=token)
            # Flutterwave retourne généralement une liste
            customers = response.get("data", [])
            if isinstance(customers, list) and customers:
                # On prend le premier match
                return customers[0]["id"]
            elif isinstance(customers, dict) and "id" in customers:
                return customers["id"]
                
            raise Exception(f"Aucun customer trouvé pour l'email {email}")
        except Exception as e:
            logger.error("flutterwave_get_customer_id_failed", error=str(e), email=email)
            raise
    
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
