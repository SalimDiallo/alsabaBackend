# apps/auth/Services/kyc_services.py

import requests
import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)


class DiditKYCService:
    """
    Service pour l'API ID Verification Standalone de Didit
    Documentation officielle : https://docs.didit.me/reference/id-verification-standalone-api
    Endpoint unique : POST https://verification.didit.me/v2/id-verification/
    Traitement synchrone, réponse immédiate avec résultats.
    """
    BASE_URL = "https://verification.didit.me/v2/id-verification/"

    def __init__(self):
        if not settings.DIDIT_API_KEY:
            raise ValueError("DIDIT_API_KEY n'est pas configurée dans settings")
        
        self.api_key = settings.DIDIT_API_KEY
        self.headers = {
            "accept": "application/json",
            "x-api-key": self.api_key,
            "content-type": "multipart/form-data"
        }
        self.timeout = 60  # Upload + traitement peuvent prendre du temps

    def verify_id_document(
        self,
        front_image,
        back_image=None,
        perform_document_liveness=True,   # Fortement recommandé
        min_age=None,
        expiration_action="DECLINE",
        mrz_failure_action="DECLINE",
        viz_consistency_action="DECLINE",
        preferred_charset="latin",
        save_request=True,
        external_id=None,
    ):
        """
        Envoie les images du document et récupère le résultat de vérification immédiatement.

        Args:
            front_image: fichier image du recto (obligatoire)
            back_image: fichier image du verso (optionnel)
            perform_document_liveness: détection copie d'écran / manipulation portrait
            min_age: âge minimum requis (ex: 18)
            expiration_action: "DECLINE" ou "NO_ACTION" si document expiré
            mrz_failure_action: "DECLINE" ou "NO_ACTION" si MRZ invalide
            viz_consistency_action: "DECLINE" ou "NO_ACTION" si incohérence VIS/MRZ
            preferred_charset: "latin" ou "non_latin"
            save_request: conserver la requête chez Didit pour support
            external_id: ton ID interne pour tracking (ex: user.id)

        Returns:
            dict avec success, request_id, status (Approved/Declined), données extraites
        """
        # Préparation des fichiers
        files = {
            'file': ('front.jpg', front_image, 'image/jpeg')
        }
        if back_image:
            files['file'] = ('back.jpg', back_image, 'image/jpeg')  # Didit accepte plusieurs 'file'

        # Préparation des paramètres form-data
        data = {
            'perform_document_liveness': str(perform_document_liveness).lower(),
            'expiration_action': expiration_action,
            'mrz_failure_action': mrz_failure_action,
            'viz_consistency_action': viz_consistency_action,
            'preferred_charset': preferred_charset,
            'save_request': str(save_request).lower(),
        }

        if min_age is not None:
            data['min_age'] = str(min_age)

        if external_id:
            data['external_id'] = str(external_id)

        logger.info(
            "didit_kyc_verify_attempt",
            external_id=external_id,
            perform_liveness=perform_document_liveness,
            min_age=min_age,
            has_back_image=back_image is not None
        )

        try:
            response = requests.post(
                self.BASE_URL,
                headers=self.headers,
                files=files,
                data=data,
                timeout=self.timeout
            )

            # Log brut pour debug si besoin
            logger.debug(
                "didit_kyc_raw_response",
                status_code=response.status_code,
                response_text=response.text[:500]
            )

            if response.status_code == 200:
                result = response.json()
                request_id = result.get("request_id")
                id_verification = result.get("id_verification", {})
                status = id_verification.get("status", "Unknown")

                logger.info(
                    "didit_kyc_success",
                    request_id=request_id,
                    status=status,
                    external_id=external_id
                )

                return {
                    "success": True,
                    "request_id": request_id,
                    "status": status,  # Approved / Declined / etc.
                    "id_verification": id_verification,
                    "raw_response": result
                }

            else:
                # Erreur HTTP
                error_msg = response.text or "Erreur inconnue"
                logger.warning(
                    "didit_kyc_http_error",
                    status_code=response.status_code,
                    response=error_msg,
                    external_id=external_id
                )
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "message": f"Erreur Didit ({response.status_code})",
                    "details": error_msg
                }

        except requests.exceptions.Timeout:
            logger.error("didit_kyc_timeout", external_id=external_id)
            return {
                "success": False,
                "message": "Timeout : le service Didit a mis trop de temps à répondre"
            }
        except requests.exceptions.RequestException as e:
            logger.error("didit_kyc_network_error", error=str(e), external_id=external_id)
            return {
                "success": False,
                "message": "Erreur réseau lors de la communication avec Didit"
            }
        except Exception as e:
            logger.error("didit_kyc_unexpected_error", error=str(e))
            return {
                "success": False,
                "message": "Erreur inattendue lors de la vérification KYC"
            }


# Instance singleton à importer partout
kyc_service = DiditKYCService()