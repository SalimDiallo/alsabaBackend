import requests
import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)

class DiditKYCService:
    BASE_URL = "https://verification.didit.me/v3/id-verification/"
    FACE_MATCH_URL = "https://verification.didit.me/v3/face-match"

    def __init__(self):
        if not settings.DIDIT_API_KEY:
            raise ValueError("DIDIT_API_KEY missing")
        self.api_key = settings.DIDIT_API_KEY
        self.timeout = 60

    def verify_id_document(
        self,
        front_image,
        back_image=None,
        perform_document_liveness=True,
        minimum_age=None,
        expiration_date_not_detected_action="DECLINE",
        invalid_mrz_action="DECLINE",
        inconsistent_data_action="DECLINE",
        preferred_characters="latin",
        save_api_request=True,
        vendor_data=None,
    ):
        # Simplified local validation (without magic)
        front_valid, front_msg = self.validate_image_before_upload(front_image)
        if not front_valid:
            return {"success": False, "message": f"Front invalid: {front_msg}", "code": "invalid_front_image"}

        if back_image:
            back_valid, back_msg = self.validate_image_before_upload(back_image)
            if not back_valid:
                return {"success": False, "message": f"Back invalid: {back_msg}", "code": "invalid_back_image"}

        # Multipart preparation
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

        # Exact Didit parameters
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
                
                logger.info("didit_id_verification_success", 
                            status=res.get("id_verification", {}).get("status"),
                            request_id=res.get("request_id"))
                
                print(res)
                return {
                    "success": True,
                    "request_id": res.get("request_id"),
                    "status": res.get("id_verification", {}).get("status", "Unknown"),
                    "id_verification": res.get("id_verification", {}),
                    "raw": res
                }

            else:
                error_msg = response.text or "Unknown Didit error"
                logger.warning("didit_http_error", status_code=response.status_code, error=error_msg[:200])
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "message": error_msg,
                }

        except requests.exceptions.Timeout:
            logger.error("didit_timeout")
            return {"success": False, "message": "Didit service timeout", "code": "timeout"}

        except requests.exceptions.RequestException as e:
            logger.error("didit_network_error", error=str(e))
            return {"success": False, "message": "Network error with Didit", "code": "network_error"}

        except Exception as e:
            logger.error("didit_unexpected_error", error=str(e))
            return {"success": False, "message": f"Technical error: {str(e)}", "code": "exception"}

    def match_face(
        self,
        selfie_image,
        ref_image,
        decline_threshold=50,
        rotate_image=False,
        save_api_request=True,
        vendor_data=None,
    ):
        """
        Compare a photo (selfie) with a reference image (from the ID document).
        Uses Standalone Face Match v3 API.
        """
        # Local validation
        selfie_valid, selfie_msg = self.validate_image_before_upload(selfie_image)
        if not selfie_valid:
            return {"success": False, "message": f"Selfie invalid: {selfie_msg}", "code": "invalid_selfie_image"}

        ref_valid, ref_msg = self.validate_image_before_upload(ref_image)
        if not ref_valid:
            return {"success": False, "message": f"Reference image invalid: {ref_msg}", "code": "invalid_ref_image"}

        # Multipart preparation
        files = []
        
        # The selfie (user_image)
        selfie_mime = getattr(selfie_image, 'content_type', 'image/jpeg')
        selfie_name = getattr(selfie_image, 'name', 'selfie.jpg')
        files.append(('user_image', (selfie_name, self._prepare_file(selfie_image), selfie_mime)))

        # The reference image (ref_image)
        # Note: ref_image can be a File object (if we extract it ourselves)
        # or the document image sent previously.
        ref_mime = getattr(ref_image, 'content_type', 'image/jpeg')
        ref_name = getattr(ref_image, 'name', 'ref.jpg')
        files.append(('ref_image', (ref_name, self._prepare_file(ref_image), ref_mime)))

        # Parameters
        data = {
            'face_match_score_decline_threshold': str(decline_threshold),
            'rotate_image': str(rotate_image).lower(),
            'save_api_request': str(save_api_request).lower(),
        }

        if vendor_data:
            data['vendor_data'] = str(vendor_data)[:100]


        try:
            response = requests.post(
                self.FACE_MATCH_URL,
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
                face_match_data = res.get("face_match", {})
                
                # Correction pour coller à la structure v3 Standalone
                score = face_match_data.get("score") or res.get("score") or face_match_data.get("similarity_percentage")
                status_val = face_match_data.get("status") or res.get("status") or "Unknown"
                
                logger.info("didit_face_match_success", 
                            status=status_val, 
                            score=score,
                            request_id=res.get("request_id"))
                
                return {
                    "success": True,
                    "request_id": res.get("request_id"),
                    "status": status_val,
                    "score": score,
                    "raw": res
                }
            else:
                error_msg = response.text or "Unknown Face Match v3 error"
                logger.warning("didit_face_match_v3_http_error", status_code=response.status_code, error=error_msg[:200])
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "message": error_msg,
                }

        except Exception as e:
            logger.error("didit_face_match_v3_unexpected_error", error=str(e))
            return {"success": False, "message": f"Technical error Face Match v3: {str(e)}", "code": "exception"}

    def validate_image_before_upload(self, image):
        """
        Simple validation without magic: size + presence
        """
        if not image:
            return False, "Image missing"

        if hasattr(image, 'size'):
            if image.size == 0:
                return False, "File is empty (0 bytes)"
            if image.size > 5 * 1024 * 1024:
                return False, "Size > 5MB"

        # Optional: check content_type indicated by client
        if hasattr(image, 'content_type'):
            allowed_content_types = {
                'image/jpeg', 'image/jpg', 'image/png',
                'image/webp', 'image/tiff', 'application/pdf'
            }
            if image.content_type not in allowed_content_types:
                return False, f"Indicated type not supported: {image.content_type}"

        return True, "OK"

    def _prepare_file(self, f):
        """
        Prepares the file and resets the cursor to 0
        """
        if hasattr(f, 'seek'):
            f.seek(0)
        return f.file if hasattr(f, 'file') else f

kyc_service = DiditKYCService()