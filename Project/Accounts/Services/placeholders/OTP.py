# apps/auth/Services/OTP_services.py
import random
import uuid
import time
import structlog
from datetime import datetime
from django.conf import settings
from ...utils import auth_utils
from django.utils import timezone
import requests
logger = structlog.get_logger(__name__)


class DiditVerificationService:
    """
    Service d'intégration avec Didit V2 - Version adaptée sans resend
    Documentation : https://docs.didit.me
    Note: Didit ne propose pas d'endpoint resend, on doit renvoyer un nouveau code
    """
    BASE_URL = "https://verification.didit.me/v2"
    SEND_CODE_URL = f"{BASE_URL}/phone/send"
    VERIFY_CODE_URL = f"{BASE_URL}/phone/check"
    
    def __init__(self):
        if not settings.DIDIT_API_KEY:
            raise ValueError("DIDIT_API_KEY n'est pas configurée dans settings")
        
        self.api_key = settings.DIDIT_API_KEY
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-api-key": self.api_key,
        }
        self.timeout = 15
        
        # Mode placeholder (peut être configuré dans les settings)
        self.use_placeholder = getattr(settings, 'DIDIT_USE_PLACEHOLDER', True)
        
        # Stockage local pour les codes (en mode placeholder)
        self._verification_store = {}
        
        # Formats de numéros test pour les différents scénarios
        self._test_numbers = {
            'success': ['+33612345678', '+33798765432', '+33611223344'],
            'blocked': ['+33699999999', '+33788888888'],
            'invalid': ['+33600000000', 'invalid_number'],
            'undeliverable': ['+33611111111'],
            'timeout': ['+33622222222']
        }

    def send_verification_code(self, phone_number, request_meta=None, vendor_data=None):
        """
        Envoie un code OTP via Didit (ou placeholder).
        
        Args:
            phone_number: Format E.164 (ex: +33612345678)
            request_meta: Métadonnées de la requête
            vendor_data: Identifiant interne pour corrélation
        
        Returns:
            dict: Résultat de l'envoi avec request_id
        """
        # Validation du format E.164
        if not auth_utils.validate_e164_format(phone_number):
            logger.error("invalid_e164_format", phone_number=auth_utils.mask_phone(phone_number))
            return self._error_response(
                "InvalidFormat", 
                "invalid_phone_format", 
                "Format de numéro invalide"
            )
        
        # Si le placeholder est activé, simuler l'envoi
        if self.use_placeholder:
            return self._simulate_send_code(phone_number, request_meta, vendor_data)
        
        # Sinon, utiliser l'implémentation réelle
        return self._real_send_code(phone_number, request_meta, vendor_data)

    def verify_code(self, phone_number, code, request_id=None):
        """
        Vérifie un code OTP avec Didit (ou placeholder).
        
        Args:
            phone_number: Format E.164
            code: Code OTP (6 chiffres)
            request_id: Optionnel - ID de la requête Didit pour tracking
        
        Returns:
            dict: Résultat de la vérification avec détails
        """
        # Validation des entrées
        if not auth_utils.validate_e164_format(phone_number):
            return {
                "success": False,
                "verified": False,
                "message": "Format de numéro invalide",
                "code": "invalid_phone_format"
            }
        
        if not code or not code.isdigit() or len(code) != 6:
            return {
                "success": False,
                "verified": False,
                "message": "Code OTP invalide (6 chiffres requis)",
                "code": "invalid_otp_format"
            }

        # Si le placeholder est activé, simuler la vérification
        if self.use_placeholder:
            return self._simulate_verify_code(phone_number, code, request_id)
        
        # Sinon, utiliser l'implémentation réelle
        return self._real_verify_code(phone_number, code, request_id)

    # ==================== SIMULATION MODE ====================

    def _simulate_send_code(self, phone_number, request_meta=None, vendor_data=None):
        """Simule l'envoi d'un code OTP."""
        # Simuler un délai réseau
        time.sleep(random.uniform(0.5, 1.5))
        
        # Générer un request_id
        request_id = f"didit_sim_{uuid.uuid4().hex[:16]}"
        
        # Déterminer le scénario basé sur le numéro de téléphone
        scenario = self._determine_send_scenario(phone_number)
        
        logger.info(
            "didit_placeholder_send_attempt",
            phone_number=auth_utils.mask_phone(phone_number),
            scenario=scenario,
            request_id=request_id
        )
        
        # Traiter selon le scénario
        if scenario == 'blocked':
            return self._simulate_blocked_response(phone_number, request_id)
        elif scenario == 'invalid':
            return self._simulate_invalid_response(phone_number, request_id)
        elif scenario == 'undeliverable':
            return self._simulate_undeliverable_response(phone_number, request_id)
        elif scenario == 'timeout':
            return self._simulate_timeout_response()
        else:
            # Cas normal - générer et stocker un code
            otp_code = self._generate_otp_code()
            expires_at = time.time() + 300  # 5 minutes
            
            self._verification_store[phone_number] = {
                'code': otp_code,
                'expires_at': expires_at,
                'request_id': request_id,
                'attempts': 0,
                'vendor_data': vendor_data
            }
            
            # Pour les numéros spécifiques, forcer le code à 123456 pour les tests
            if phone_number in ['+33612345678', '+336000000']:
                otp_code = '123456'
                self._verification_store[phone_number]['code'] = otp_code
            
            logger.info(
                "didit_placeholder_code_generated",
                phone_number=auth_utils.mask_phone(phone_number),
                code=otp_code,
                request_id=request_id
            )
            
            return {
                "success": True,
                "request_id": request_id,
                "status": "Success",
                "message": "Code de vérification envoyé par SMS (simulé)"
            }

    def _simulate_verify_code(self, phone_number, code, request_id=None):
        """Simule la vérification d'un code OTP."""
        # Simuler un délai
        time.sleep(random.uniform(0.3, 0.8))
        
        # Vérifier si le numéro existe dans le store
        if phone_number not in self._verification_store:
            logger.warning(
                "didit_placeholder_no_code_found",
                phone_number=auth_utils.mask_phone(phone_number)
            )
            return {
                "success": False,
                "verified": False,
                "message": "Aucun code trouvé pour ce numéro",
                "code": "no_pending_verification"
            }
        
        stored_data = self._verification_store[phone_number]
        
        # Vérifier l'expiration
        if time.time() > stored_data['expires_at']:
            del self._verification_store[phone_number]
            return {
                "success": False,
                "verified": False,
                "message": "Le code a expiré",
                "code": "code_expired"
            }
        
        # Incrémenter les tentatives
        stored_data['attempts'] += 1
        
        # Vérifier le code
        if code == stored_data['code']:
            # Code correct
            phone_details = self._generate_phone_details(phone_number)
            
            # Nettoyer le store
            del self._verification_store[phone_number]
            
            logger.info(
                "didit_placeholder_verification_success",
                phone_number=auth_utils.mask_phone(phone_number),
                request_id=request_id
            )
            
            return {
                "success": True,
                "verified": True,
                "status": "Approved",
                "message": "Vérification réussie (simulée)",
                "phone_details": phone_details
            }
        else:
            # Code incorrect
            if stored_data['attempts'] >= 3:
                del self._verification_store[phone_number]
                return {
                    "success": False,
                    "verified": False,
                    "message": "Trop de tentatives échouées",
                    "code": "max_attempts_exceeded"
                }
            
            logger.warning(
                "didit_placeholder_wrong_code",
                phone_number=auth_utils.mask_phone(phone_number),
                attempts=stored_data['attempts']
            )
            
            return {
                "success": False,
                "verified": False,
                "message": "Code incorrect",
                "code": "wrong_code",
                "attempts_remaining": 3 - stored_data['attempts']
            }

    # ==================== REAL MODE ====================

    def _real_send_code(self, phone_number, request_meta=None, vendor_data=None):
        """Implémentation réelle de l'envoi de code (votre code original)."""
        payload = {
            "phone_number": phone_number,
            "options": {
                "code_size": 6,
                "locale": "fr-FR",
                "preferred_channel": "sms"
            }
        }

        # Ajout des signaux anti-fraude
        if request_meta:
            signals = self._extract_signals(request_meta)
            if self._are_signals_valid(signals):
                payload["signals"] = signals
            else:
                logger.warning(
                    "didit_signals_incomplete",
                    phone_number=auth_utils.mask_phone(phone_number),
                    missing_fields=self._get_missing_signal_fields(signals)
                )

        if vendor_data:
            payload["vendor_data"] = str(vendor_data)[:100]

        logger.info(
            "didit_send_code_attempt",
            phone_number=auth_utils.mask_phone(phone_number),
            has_signals="signals" in payload,
            vendor_data=vendor_data[:20] if vendor_data else None
        )

        try:
            response = requests.post(
                self.SEND_CODE_URL,
                json=payload,
                headers=self.headers,
                timeout=self.timeout
            )
            
            logger.debug(
                "didit_send_code_http",
                status_code=response.status_code,
                phone_number=auth_utils.mask_phone(phone_number)
            )
            
            response_data = response.json() if response.content else {}

            if response.status_code == 200:
                return self._handle_success_send(response_data)
            else:
                return self._handle_error_send(response.status_code, response_data)

        except requests.exceptions.Timeout:
            logger.error("didit_send_timeout", phone_number=auth_utils.mask_phone(phone_number))
            return self._error_response(
                "Timeout", 
                "request_timeout", 
                "Le service est temporairement indisponible"
            )
        except requests.exceptions.RequestException as e:
            logger.error("didit_send_network_error", error=str(e))
            return self._error_response(
                "NetworkError", 
                "service_unavailable", 
                "Service temporairement indisponible"
            )
        except ValueError as e:
            logger.error("didit_send_json_error", error=str(e))
            return self._error_response(
                "ParseError", 
                "invalid_response", 
                "Réponse invalide du service"
            )

    def _real_verify_code(self, phone_number, code, request_id=None):
        """Implémentation réelle de la vérification de code (votre code original)."""
        payload = {
            "phone_number": phone_number,
            "code": code,
        }

        logger.info(
            "didit_verify_attempt",
            phone_number=auth_utils.mask_phone(phone_number),
            request_id=request_id[:20] if request_id else None,
            code_length=len(code)
        )

        try:
            response = requests.post(
                self.VERIFY_CODE_URL,
                json=payload,
                headers=self.headers,
                timeout=10
            )
            
            logger.debug(
                "didit_verify_http",
                status_code=response.status_code,
                phone_number=auth_utils.mask_phone(phone_number)
            )
            
            response_data = response.json() if response.content else {}

            if response.status_code != 200:
                return self._handle_verification_error(response.status_code, response_data)

            phone_details = response_data.get("phone", {})
            status = phone_details.get("status", "Unknown")
            verified = (status == "Approved")

            return {
                "success": True,
                "verified": verified,
                "status": status,
                "message": response_data.get("message", "Vérification effectuée"),
                "phone_details": self._extract_phone_details(phone_details)
            }

        except requests.exceptions.Timeout:
            logger.error("didit_verify_timeout", phone_number=auth_utils.mask_phone(phone_number))
            return {"success": False, "verified": False, "message": "Timeout de vérification"}
        except requests.exceptions.RequestException as e:
            logger.error("didit_verify_network_error", error=str(e))
            return {"success": False, "verified": False, "message": "Erreur réseau"}
        except ValueError as e:
            logger.error("didit_verify_json_error", error=str(e))
            return {"success": False, "verified": False, "message": "Réponse invalide"}

    # ==================== UTILITY METHODS ====================

    def _determine_send_scenario(self, phone_number):
        """Détermine le scénario de test basé sur le numéro."""
        for scenario, numbers in self._test_numbers.items():
            if phone_number in numbers:
                return scenario
        
        # Par défaut, retourner un scénario aléatoire avec probabilités
        rand = random.random()
        if rand < 0.70:  # 70% de succès
            return 'success'
        elif rand < 0.75:  # 5% bloqué
            return 'blocked'
        elif rand < 0.80:  # 5% invalide
            return 'invalid'
        elif rand < 0.85:  # 5% non délivrable
            return 'undeliverable'
        elif rand < 0.90:  # 5% timeout
            return 'timeout'
        else:  # 10% succès
            return 'success'

    def _generate_otp_code(self):
        """Génère un code OTP aléatoire."""
        return ''.join([str(random.randint(0, 9)) for _ in range(6)])

    def _generate_phone_details(self, phone_number):
        """Génère des détails de téléphone réalistes."""
        carriers = ['Orange', 'SFR', 'Bouygues', 'Free', 'O2', 'Vodafone', 'T-Mobile']
        countries = {
            '+33': {'code': 'FR', 'name': 'France'},
            '+44': {'code': 'GB', 'name': 'United Kingdom'},
            '+49': {'code': 'DE', 'name': 'Germany'},
            '+34': {'code': 'ES', 'name': 'Spain'},
            '+39': {'code': 'IT', 'name': 'Italy'},
        }
        
        prefix = phone_number[:3]
        country_info = countries.get(prefix, {'code': 'FR', 'name': 'France'})
        
        return {
            "status": "Approved",
            "phone_number_prefix": prefix,
            "full_number": phone_number,
            "country_code": country_info['code'],
            "country_name": country_info['name'],
            "carrier": random.choice(carriers),
            "is_disposable": random.random() < 0.05,  # 5% de chances
            "is_virtual": random.random() < 0.1,  # 10% de chances
            "verification_method": "sms",
            "warnings": [] if random.random() < 0.9 else ["number_flagged_for_review"],
            "recommendation": "Accept" if random.random() < 0.95 else "Review",
            "risk_score": random.randint(0, 30),
        }

    def _simulate_blocked_response(self, phone_number, request_id):
        """Simule une réponse bloquée."""
        return {
            "success": False,
            "request_id": request_id,
            "status": "Blocked",
            "reason": "TooManyAttempts",
            "message": "Ce numéro est temporairement bloqué (simulé)"
        }

    def _simulate_invalid_response(self, phone_number, request_id):
        """Simule une réponse de numéro invalide."""
        return {
            "success": False,
            "request_id": request_id,
            "status": "Invalid",
            "reason": "InvalidNumber",
            "message": "Numéro de téléphone invalide (simulé)"
        }

    def _simulate_undeliverable_response(self, phone_number, request_id):
        """Simule une réponse non délivrable."""
        return {
            "success": False,
            "request_id": request_id,
            "status": "Undeliverable",
            "reason": "CarrierFailure",
            "message": "Impossible d'envoyer le SMS à ce numéro (simulé)"
        }

    def _simulate_timeout_response(self):
        """Simule un timeout."""
        return {
            "success": False,
            "status": "Timeout",
            "reason": "request_timeout",
            "message": "Le service est temporairement indisponible (simulé)"
        }

    # Les méthodes suivantes sont les mêmes que dans votre code original
    # Je les conserve pour éviter les erreurs de référence

    def _handle_success_send(self, data):
        """Traite une réponse réussie d'envoi de code."""
        status = data.get("status")
        request_id = data.get("request_id")
        
        if status == "Success":
            return {
                "success": True,
                "request_id": request_id,
                "status": status,
                "message": "Code de vérification envoyé par SMS"
            }
        else:
            reason = data.get("reason", "unknown")
            return {
                "success": False,
                "request_id": request_id,
                "status": status,
                "reason": reason,
                "message": self._friendly_message(status, reason)
            }

    def _handle_error_send(self, status_code, data):
        """Traite les erreurs HTTP lors de l'envoi."""
        error_messages = {
            400: ("BadRequest", "invalid_request", "Requête invalide vers Didit"),
            401: ("Unauthorized", "invalid_key", "Clé API Didit invalide"),
            403: ("Forbidden", "permission_denied", "Accès refusé à l'API Didit"),
            429: ("RateLimited", "rate_limited", "Trop de requêtes vers Didit"),
            500: ("ServerError", "didit_server_error", "Erreur interne chez Didit"),
            502: ("BadGateway", "bad_gateway", "Problème de connexion à Didit"),
            503: ("ServiceUnavailable", "service_unavailable", "Didit temporairement indisponible"),
        }
        
        if status_code in error_messages:
            status, reason, default_message = error_messages[status_code]
            message = data.get("detail") or data.get("message") or default_message
            return self._error_response(status, reason, message)
        else:
            message = data.get("detail") or data.get("message") or f"Erreur Didit ({status_code})"
            return self._error_response("HttpError", "http_error", message)

    def _handle_verification_error(self, status_code, data):
        """Traite les erreurs HTTP lors de la vérification."""
        if status_code == 400:
            return {
                "success": False,
                "verified": False,
                "message": data.get("detail", "Requête de vérification invalide"),
                "code": "verification_failed"
            }
        elif status_code == 429:
            return {
                "success": False,
                "verified": False,
                "message": "Trop de tentatives de vérification",
                "code": "verification_rate_limited",
                "retry_after": 60
            }
        else:
            return {
                "success": False,
                "verified": False,
                "message": f"Erreur lors de la vérification ({status_code})",
                "code": "verification_error"
            }

    def _error_response(self, status, reason, message):
        """Format standard pour les réponses d'erreur."""
        return {
            "success": False,
            "status": status,
            "reason": reason,
            "message": message
        }

    def _extract_signals(self, request_meta):
        """
        Extrait les signaux anti-fraude des métadonnées de requête.
        Format attendu par Didit: https://docs.didit.me/reference/phone-verification-signals
        """
        signals = {}
        
        # Mapping des champs
        mapping = {
            'device_id': 'device_id',
            'app_version': 'app_version',
            'ip': 'client_ip',
            'user_agent': 'user_agent',
        }
        
        for signal_key, meta_key in mapping.items():
            value = request_meta.get(meta_key, '').strip()
            
            # Valeurs par défaut intelligentes
            if not value:
                if signal_key == 'device_id':
                    value = f"web_{uuid.uuid4().hex[:8]}"
                elif signal_key == 'app_version':
                    value = "1.0.0"
                elif signal_key == 'ip':
                    # Ne jamais mettre 0.0.0.0, utiliser l'IP réelle ou 'unknown'
                    value = request_meta.get('client_ip', 'unknown')[:50]
                elif signal_key == 'user_agent':
                    value = "Unknown"
            
            if value:
                signals[signal_key] = value
        
        return signals

    def _are_signals_valid(self, signals):
        """
        Vérifie que les signaux minimums sont présents.
        Didit recommande au moins device_id et app_version.
        """
        required = ['device_id', 'app_version']
        for field in required:
            if field not in signals or not signals[field]:
                return False
        return True

    def _get_missing_signal_fields(self, signals):
        """Retourne la liste des champs de signal manquants."""
        required = ['device_id', 'app_version']
        return [f for f in required if not signals.get(f)]

    def _friendly_message(self, status, reason):
        """Traduit les messages techniques de Didit en messages utilisateur."""
        messages = {
            "Blocked": "Ce numéro est temporairement bloqué",
            "Invalid": "Numéro de téléphone invalide",
            "Undeliverable": "Impossible d'envoyer le SMS à ce numéro",
            "TooManyAttempts": "Trop de tentatives, veuillez réessayer plus tard",
            "CarrierFailure": "Problème avec l'opérateur téléphonique",
            "Unsupported": "Numéro non supporté",
        }
        
        # Essayer d'abord par raison, puis par status
        if reason in messages:
            return messages[reason]
        elif status in messages:
            return messages[status]
        else:
            return f"Échec d'envoi du code ({reason or status})"

    def _extract_phone_details(self, phone_details):
        """
        Extrait et formate les détails du numéro de téléphone.
        """
        return {
            "status": phone_details.get("status"),
            "phone_number_prefix": phone_details.get("phone_number_prefix"),
            "full_number": phone_details.get("full_number"),
            "country_code": phone_details.get("country_code"),
            "country_name": phone_details.get("country_name"),
            "carrier": phone_details.get("carrier"),
            "is_disposable": phone_details.get("is_disposable", False),
            "is_virtual": phone_details.get("is_virtual", False),
            "verification_method": phone_details.get("verification_method"),
            "warnings": phone_details.get("warnings", []),
            "recommendation": phone_details.get("recommendation"),
            "risk_score": phone_details.get("risk_score"),
        }


# Instance singleton
didit_service = DiditVerificationService()