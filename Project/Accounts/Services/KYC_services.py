import requests
import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)

class DiditKYCService:
    BASE_URL = "https://verification.didit.me/v3/id-verification/"

    def __init__(self):
        if not settings.DIDIT_API_KEY:
            raise ValueError("DIDIT_API_KEY manquante")
        self.api_key = settings.DIDIT_API_KEY
        self.timeout = 60

    def verify_id_document(
        self,
        front_image,
        back_image=None,
        perform_document_liveness=False,
        minimum_age=None,
        expiration_date_not_detected_action="DECLINE",
        invalid_mrz_action="DECLINE",
        inconsistent_data_action="DECLINE",
        preferred_characters="latin",
        save_api_request=True,
        vendor_data=None,
    ):
        # Validation locale simplifiée (sans magic)
        front_valid, front_msg = self.validate_image_before_upload(front_image)
        if not front_valid:
            return {"success": False, "message": f"Recto invalide: {front_msg}", "code": "invalid_front_image"}

        if back_image:
            back_valid, back_msg = self.validate_image_before_upload(back_image)
            if not back_valid:
                return {"success": False, "message": f"Verso invalide: {back_msg}", "code": "invalid_back_image"}

        # Préparation multipart
        files = []
        front_mime = getattr(front_image, 'content_type', 'image/jpeg')
        front_name = getattr(front_image, 'name', 'front.jpg')
        front_file = self._prepare_file(front_image)
        files.append(('front_image', (front_name, front_file, front_mime)))

        if back_image:
            back_mime = getattr(back_image, 'content_type', 'image/jpeg')
            back_name = getattr(back_image, 'name', 'back.jpg')
            back_file = self._prepare_file(back_image)
            files.append(('back_image', (back_name, back_file, back_mime)))

        # Paramètres exacts Didit
        data = {
            'perform_document_liveness': str(perform_document_liveness).lower(),
            'expiration_date_not_detected_action': expiration_date_not_detected_action,
            'invalid_mrz_action': invalid_mrz_action,
            'inconsistent_data_action': inconsistent_data_action,
            'preferred_characters': preferred_characters,
            'save_api_request': str(save_api_request).lower(),
        }

        if minimum_age is not None:
            data['minimum_age'] = str(minimum_age)

        if vendor_data:
            data['vendor_data'] = str(vendor_data)[:100]

        logger.info("didit_request", vendor_data=vendor_data[:50] if vendor_data else None)

        try:
            response = requests.post(
                self.BASE_URL,
                files=files,
                data=data,
                headers={
                    "accept": "application/json",
                    "X-Api-Key": self.api_key,
                },
                timeout=self.timeout
            )

            if response.status_code == 200:
                res = response.json()
                return {
                    "success": True,
                    "request_id": res.get("request_id"),
                    "status": res.get("id_verification", {}).get("status", "Unknown"),
                    "id_verification": res.get("id_verification", {}),
                    "raw": res
                }

            else:
                error_msg = response.text or "Erreur Didit inconnue"
                logger.warning("didit_http_error", status_code=response.status_code, error=error_msg[:200])
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "message": error_msg,
                }

        except requests.exceptions.Timeout:
            logger.error("didit_timeout")
            return {"success": False, "message": "Timeout du service Didit", "code": "timeout"}

        except requests.exceptions.RequestException as e:
            logger.error("didit_network_error", error=str(e))
            return {"success": False, "message": "Erreur réseau avec Didit", "code": "network_error"}

        except Exception as e:
            logger.error("didit_unexpected_error", error=str(e))
            return {"success": False, "message": f"Erreur technique : {str(e)}", "code": "exception"}

    def validate_image_before_upload(self, image):
        """
        Validation simple sans magic : taille + présence
        """
        if not image:
            return False, "Image absente"

        if hasattr(image, 'size'):
            if image.size == 0:
                return False, "Le fichier est vide (0 octet)"
            if image.size > 5 * 1024 * 1024:
                return False, "Taille > 5MB"

        # Optionnel : vérifier content_type indiqué par le client
        if hasattr(image, 'content_type'):
            allowed_content_types = {
                'image/jpeg', 'image/jpg', 'image/png',
                'image/webp', 'image/tiff', 'application/pdf'
            }
            if image.content_type not in allowed_content_types:
                return False, f"Type indiqué non supporté : {image.content_type}"

        return True, "OK"

    def _prepare_file(self, f):
        """
        Prépare le fichier et remet le curseur à 0
        """
        if hasattr(f, 'seek'):
            f.seek(0)
        return f.file if hasattr(f, 'file') else f

kyc_service = DiditKYCService()