# apps/auth/Services/OTP_services.py
import time
import uuid
import structlog
from django.conf import settings
from ...utils import auth_utils
import random
from enum import Enum
from datetime import datetime, timedelta

logger = structlog.get_logger(__name__)


class DiditVerificationService:
    """
    Service de simulation OTP Didit - Version simulée complète
    """
    BASE_URL = "https://verification.didit.me/v2"
    SEND_CODE_URL = f"{BASE_URL}/phone/send"
    VERIFY_CODE_URL = f"{BASE_URL}/phone/check"
    
    # Codes OTP générés en mémoire (simulation)
    _OTP_STORE = {}  # {phone: {"code": "123456", "timestamp": ..., "request_id": "...", "attempts": 0}}
    
    # Statistiques de simulation
    _SIMULATION_STATS = {
        "total_send_requests": 0,
        "total_verify_requests": 0,
        "successful_sends": 0,
        "failed_sends": 0,
        "successful_verifications": 0,
        "failed_verifications": 0,
        "rate_limit_hits": 0
    }

    class OTPStatus(Enum):
        PENDING = "pending"
        VERIFIED = "verified"
        EXPIRED = "expired"
        MAX_ATTEMPTS = "max_attempts"
        BLOCKED = "blocked"

    def __init__(self):
        """Initialisation avec clé API simulée"""
        self.simulated_api_key = getattr(settings, 'DIDIT_API_KEY', 'simulated-key-otp-789')
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-api-key": self.simulated_api_key,
        }
        self.timeout = 15
        self.simulation_mode = True
        
        # Configuration de simulation
        self._config = {
            "otp_length": 6,
            "otp_expiry_seconds": 300,  # 5 minutes
            "max_attempts": 3,
            "success_rate": 0.95,  # 95% de succès d'envoi
            "verification_success_rate": 0.85,  # 85% de codes corrects
            "simulated_delivery_time_ms": (1000, 3000),  # 1-3 secondes
            "blocked_numbers": ["+33600000000", "+33700000000"],  # Numéros simulés bloqués
            "virtual_numbers": ["+33612345678", "+33712345678"],  # Numéros virtuels simulés
            "disposable_numbers": ["+33699999999"],  # Numéros jetables simulés
        }

    def send_verification_code(self, phone_number, request_meta=None, vendor_data=None):
        """
        Simulation d'envoi de code OTP via Didit.
        
        Args:
            phone_number: Format E.164 (ex: +33612345678)
            request_meta: Métadonnées de la requête
            vendor_data: Identifiant interne pour corrélation
        
        Returns:
            dict: Résultat de l'envoi avec request_id
        """
        # Mise à jour des statistiques
        self._SIMULATION_STATS["total_send_requests"] += 1
        
        # Validation du format E.164
        if not auth_utils.validate_e164_format(phone_number):
            logger.error("simulation_invalid_e164_format", 
                        phone_number=auth_utils.mask_phone(phone_number))
            return self._error_response(
                "InvalidFormat", 
                "invalid_phone_format", 
                "Format de numéro invalide"
            )
        
        # Vérification des numéros bloqués
        if phone_number in self._config["blocked_numbers"]:
            logger.warning("simulation_blocked_number",
                          phone_number=auth_utils.mask_phone(phone_number))
            return {
                "success": False,
                "status": "Blocked",
                "reason": "Blocked",
                "message": "Ce numéro est temporairement bloqué"
            }
        
        # Simulation d'un taux d'échec aléatoire
        if random.random() > self._config["success_rate"]:
            self._SIMULATION_STATS["failed_sends"] += 1
            failure_reasons = [
                ("Undeliverable", "Impossible d'envoyer le SMS à ce numéro"),
                ("CarrierFailure", "Problème avec l'opérateur téléphonique"),
                ("Invalid", "Numéro de téléphone invalide"),
            ]
            status, reason = random.choice(failure_reasons)
            return self._error_response(status, reason.lower(), reason)
        
        # Génération du code OTP
        otp_code = self._generate_otp_code()
        request_id = f"didit_req_{uuid.uuid4().hex[:16]}"
        
        # Simulation du temps de livraison
        delivery_time = random.randint(*self._config["simulated_delivery_time_ms"])
        time.sleep(delivery_time / 1000.0)
        
        # Stockage en mémoire
        self._OTP_STORE[phone_number] = {
            "code": otp_code,
            "timestamp": datetime.now(),
            "request_id": request_id,
            "attempts": 0,
            "vendor_data": vendor_data,
            "status": self.OTPStatus.PENDING.value
        }
        
        # Log des métadonnées
        if request_meta:
            signals = self._extract_signals(request_meta)
            logger.info("simulation_signals_extracted",
                       phone_number=auth_utils.mask_phone(phone_number),
                       signals_count=len(signals))
        
        logger.info(
            "didit_simulation_send_success",
            phone_number=auth_utils.mask_phone(phone_number),
            request_id=request_id,
            code=otp_code,  # Dans la réalité, NE PAS logger le code!
            delivery_time_ms=delivery_time,
            vendor_data=vendor_data[:20] if vendor_data else None
        )
        
        self._SIMULATION_STATS["successful_sends"] += 1
        
        return {
            "success": True,
            "request_id": request_id,
            "status": "Success",
            "message": "Code de vérification envoyé par SMS",
            "simulation_note": f"Code OTP: {otp_code} (Visible uniquement en mode simulation)",
            "delivery_time_ms": delivery_time
        }

    def verify_code(self, phone_number, code, request_id=None):
        """
        Simulation de vérification de code OTP avec Didit.
        
        Args:
            phone_number: Format E.164
            code: Code OTP (6 chiffres)
            request_id: Optionnel - ID de la requête Didit pour tracking
        
        Returns:
            dict: Résultat de la vérification avec détails
        """
        # Mise à jour des statistiques
        self._SIMULATION_STATS["total_verify_requests"] += 1
        
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
        
        logger.info(
            "didit_simulation_verify_attempt",
            phone_number=auth_utils.mask_phone(phone_number),
            request_id=request_id[:20] if request_id else None,
            code_provided=code
        )
        
        # Vérifier si le code existe pour ce numéro
        if phone_number not in self._OTP_STORE:
            self._SIMULATION_STATS["failed_verifications"] += 1
            return {
                "success": False,
                "verified": False,
                "message": "Aucun code OTP actif pour ce numéro",
                "code": "no_active_otp"
            }
        
        otp_data = self._OTP_STORE[phone_number]
        
        # Vérifier l'expiration
        if self._is_otp_expired(otp_data):
            del self._OTP_STORE[phone_number]
            self._SIMULATION_STATS["failed_verifications"] += 1
            return {
                "success": False,
                "verified": False,
                "message": "Le code OTP a expiré",
                "code": "otp_expired",
                "status": "Expired"
            }
        
        # Vérifier les tentatives maximum
        otp_data["attempts"] += 1
        if otp_data["attempts"] > self._config["max_attempts"]:
            del self._OTP_STORE[phone_number]
            self._SIMULATION_STATS["failed_verifications"] += 1
            return {
                "success": False,
                "verified": False,
                "message": "Trop de tentatives échouées",
                "code": "max_attempts_exceeded",
                "status": "Blocked"
            }
        
        # Simulation du temps de traitement
        processing_time = random.randint(200, 800)  # 200-800ms
        time.sleep(processing_time / 1000.0)
        
        # Génération du résultat
        is_correct = (code == otp_data["code"])
        
        # Simuler un taux d'échec même avec le bon code (ex: problèmes réseau)
        if is_correct and random.random() > self._config["verification_success_rate"]:
            is_correct = False
        
        if is_correct:
            # Vérification réussie
            otp_data["status"] = self.OTPStatus.VERIFIED.value
            self._SIMULATION_STATS["successful_verifications"] += 1
            
            # Générer des détails de téléphone simulés
            phone_details = self._simulate_phone_details(phone_number)
            
            logger.info(
                "didit_simulation_verify_success",
                phone_number=auth_utils.mask_phone(phone_number),
                request_id=request_id,
                processing_time_ms=processing_time
            )
            
            return {
                "success": True,
                "verified": True,
                "status": "Approved",
                "message": "Vérification effectuée avec succès",
                "phone_details": phone_details,
                "processing_time_ms": processing_time,
                "attempts_used": otp_data["attempts"]
            }
        else:
            # Vérification échouée
            remaining_attempts = self._config["max_attempts"] - otp_data["attempts"]
            self._SIMULATION_STATS["failed_verifications"] += 1
            
            logger.warning(
                "didit_simulation_verify_failed",
                phone_number=auth_utils.mask_phone(phone_number),
                remaining_attempts=remaining_attempts,
                expected_code=otp_data["code"]
            )
            
            if remaining_attempts <= 0:
                del self._OTP_STORE[phone_number]
                return {
                    "success": False,
                    "verified": False,
                    "message": "Trop de tentatives échouées. Le code a été bloqué.",
                    "code": "blocked",
                    "status": "Blocked",
                    "retry_after": 300  # 5 minutes
                }
            
            return {
                "success": False,
                "verified": False,
                "message": f"Code incorrect. Il vous reste {remaining_attempts} tentative(s).",
                "code": "incorrect_code",
                "status": "Rejected",
                "remaining_attempts": remaining_attempts
            }

    # === Méthodes utilitaires privées ===

    def _generate_otp_code(self):
        """Génère un code OTP de 6 chiffres."""
        return ''.join(random.choices('0123456789', k=self._config["otp_length"]))

    def _is_otp_expired(self, otp_data):
        """Vérifie si un OTP a expiré."""
        elapsed = datetime.now() - otp_data["timestamp"]
        return elapsed.total_seconds() > self._config["otp_expiry_seconds"]

    def _simulate_phone_details(self, phone_number):
        """
        Simule les détails de téléphone comme le ferait Didit.
        """
        # Déterminer le type de numéro
        is_disposable = phone_number in self._config["disposable_numbers"]
        is_virtual = phone_number in self._config["virtual_numbers"]
        
        # Simuler un score de risque
        risk_factors = []
        if is_disposable:
            risk_factors.append("disposable")
        if is_virtual:
            risk_factors.append("virtual")
        
        risk_score = 0.0
        if risk_factors:
            risk_score = random.uniform(0.6, 0.9)
        else:
            risk_score = random.uniform(0.1, 0.4)
        
        # Simuler un opérateur
        french_carriers = ["Orange", "SFR", "Bouygues Telecom", "Free Mobile"]
        international_carriers = ["Vodafone", "Telefonica", "Deutsche Telekom", "TIM"]
        
        carrier = random.choice(french_carriers if phone_number.startswith("+33") else international_carriers)
        
        return {
            "status": "Approved",
            "phone_number_prefix": phone_number[:4],
            "full_number": phone_number,
            "country_code": phone_number[1:3] if phone_number.startswith("+") else "",
            "country_name": "France" if phone_number.startswith("+33") else "International",
            "carrier": carrier,
            "is_disposable": is_disposable,
            "is_virtual": is_virtual,
            "verification_method": "sms",
            "warnings": ["high_volume_recently"] if random.random() > 0.7 else [],
            "recommendation": "approve" if risk_score < 0.5 else "review",
            "risk_score": round(risk_score, 2),
            "risk_factors": risk_factors,
            "simulated": True
        }

    def _error_response(self, status, reason, message):
        """Format standard pour les réponses d'erreur."""
        return {
            "success": False,
            "status": status,
            "reason": reason,
            "message": message,
            "simulated": True
        }

    def _extract_signals(self, request_meta):
        """
        Extrait les signaux anti-fraude des métadonnées de requête.
        Identique à l'original pour la compatibilité.
        """
        signals = {}
        
        mapping = {
            'device_id': 'device_id',
            'app_version': 'app_version',
            'ip': 'client_ip',
            'user_agent': 'user_agent',
        }
        
        for signal_key, meta_key in mapping.items():
            value = request_meta.get(meta_key, '').strip()
            
            if not value:
                if signal_key == 'device_id':
                    value = f"web_{uuid.uuid4().hex[:8]}"
                elif signal_key == 'app_version':
                    value = "1.0.0"
                elif signal_key == 'ip':
                    value = request_meta.get('client_ip', 'unknown')[:50]
                elif signal_key == 'user_agent':
                    value = "Unknown"
            
            if value:
                signals[signal_key] = value
        
        return signals

    def _are_signals_valid(self, signals):
        """Vérifie que les signaux minimums sont présents."""
        required = ['device_id', 'app_version']
        for field in required:
            if field not in signals or not signals[field]:
                return False
        return True

    def _get_missing_signal_fields(self, signals):
        """Retourne la liste des champs de signal manquants."""
        required = ['device_id', 'app_version']
        return [f for f in required if not signals.get(f)]

    # === Méthodes de gestion de la simulation ===

    def get_simulation_statistics(self):
        """Retourne les statistiques de simulation."""
        stats = self._SIMULATION_STATS.copy()
        
        # Calculer les taux
        if stats["total_send_requests"] > 0:
            stats["send_success_rate"] = round(
                stats["successful_sends"] / stats["total_send_requests"] * 100, 2
            )
        
        if stats["total_verify_requests"] > 0:
            stats["verify_success_rate"] = round(
                stats["successful_verifications"] / stats["total_verify_requests"] * 100, 2
            )
        
        stats["active_otps"] = len(self._OTP_STORE)
        stats["simulation_mode"] = True
        stats["config"] = {
            "otp_expiry_seconds": self._config["otp_expiry_seconds"],
            "max_attempts": self._config["max_attempts"]
        }
        
        return stats

    def get_active_otps(self):
        """Retourne la liste des OTPs actifs (pour le débogage)."""
        result = {}
        for phone, data in self._OTP_STORE.items():
            result[auth_utils.mask_phone(phone)] = {
                "code": data["code"],
                "timestamp": data["timestamp"].isoformat(),
                "attempts": data["attempts"],
                "status": data["status"],
                "expires_in": self._config["otp_expiry_seconds"] - 
                             (datetime.now() - data["timestamp"]).total_seconds()
            }
        return result

    def clear_expired_otps(self):
        """Nettoie les OTPs expirés."""
        expired = []
        now = datetime.now()
        
        for phone, data in list(self._OTP_STORE.items()):
            if self._is_otp_expired(data):
                expired.append(phone)
                del self._OTP_STORE[phone]
        
        logger.info("simulation_cleared_expired_otps", count=len(expired))
        return expired

    def reset_simulation(self):
        """Réinitialise complètement la simulation."""
        self._OTP_STORE.clear()
        self._SIMULATION_STATS = {
            "total_send_requests": 0,
            "total_verify_requests": 0,
            "successful_sends": 0,
            "failed_sends": 0,
            "successful_verifications": 0,
            "failed_verifications": 0,
            "rate_limit_hits": 0
        }
        logger.info("simulation_reset")

    def simulate_rate_limit(self, phone_number):
        """
        Simule un rate limit pour un numéro donné.
        """
        # Simuler un délai avant de pouvoir réessayer
        wait_time = random.randint(60, 300)  # 1-5 minutes
        self._SIMULATION_STATS["rate_limit_hits"] += 1
        
        logger.warning("simulation_rate_limit_triggered",
                      phone_number=auth_utils.mask_phone(phone_number),
                      wait_time_seconds=wait_time)
        
        return {
            "success": False,
            "status": "RateLimited",
            "reason": "rate_limited",
            "message": "Trop de tentatives, veuillez réessayer plus tard",
            "retry_after": wait_time
        }

    def validate_phone_number(self, phone_number):
        """
        Simule la validation d'un numéro de téléphone.
        """
        if not auth_utils.validate_e164_format(phone_number):
            return {"valid": False, "reason": "invalid_format"}
        
        if phone_number in self._config["blocked_numbers"]:
            return {"valid": False, "reason": "blocked"}
        
        if phone_number in self._config["disposable_numbers"]:
            return {"valid": True, "warning": "disposable_number"}
        
        if phone_number in self._config["virtual_numbers"]:
            return {"valid": True, "warning": "virtual_number"}
        
        return {"valid": True, "reason": "valid_number"}


# Instance singleton
didit_service = DiditVerificationService()


# ===== UTILITAIRE DE TEST =====
# def test_otp_simulation():
#     """
#     Fonction de test pour la simulation OTP.
#     """
#     print("=== Test de simulation OTP Didit ===")
    
#     # Test 1: Envoi de code
#     print("\n1. Test d'envoi de code:")
#     result_send = didit_service.send_verification_code(
#         phone_number="+33612345678",
#         request_meta={
#             "device_id": "test_device_123",
#             "app_version": "1.2.3",
#             "client_ip": "192.168.1.100",
#             "user_agent": "TestClient/1.0"
#         },
#         vendor_data="test_user_001"
#     )
    
#     print(f"   Succès: {result_send.get('success')}")
#     print(f"   Request ID: {result_send.get('request_id')}")
#     print(f"   Message: {result_send.get('message')}")
    
#     # Test 2: Vérification correcte
#     print("\n2. Test de vérification (code correct):")
#     otp_code = list(didit_service._OTP_STORE.values())[0]["code"]
#     result_verify = didit_service.verify_code(
#         phone_number="+33612345678",
#         code=otp_code,
#         request_id=result_send.get("request_id")
#     )
    
#     print(f"   Vérifié: {result_verify.get('verified')}")
#     print(f"   Statut: {result_verify.get('status')}")
    
#     # Test 3: Vérification incorrecte
#     print("\n3. Test de vérification (code incorrect):")
#     result_fail = didit_service.verify_code(
#         phone_number="+33612345678",
#         code="999999",
#         request_id=result_send.get("request_id")
#     )
    
#     print(f"   Vérifié: {result_fail.get('verified')}")
#     print(f"   Message: {result_fail.get('message')}")
    
#     # Afficher les statistiques
#     print("\n4. Statistiques de simulation:")
#     stats = didit_service.get_simulation_statistics()
#     for key, value in stats.items():
#         if key not in ["config", "simulation_mode"]:
#             print(f"   {key}: {value}")
    
#     # Afficher les OTPs actifs
#     print("\n5. OTPs actifs:")
#     active = didit_service.get_active_otps()
#     for phone, data in active.items():
#         print(f"   {phone}: {data}")
    
#     return {
#         "send": result_send,
#         "verify_success": result_verify,
#         "verify_fail": result_fail,
#         "stats": stats
#     }


# if __name__ == "__main__":
#     # Exécuter les tests
#     test_results = test_otp_simulation()
#     print("\n=== Test terminé ===")