import base64
from datetime import datetime
from django.utils import timezone
from django.core.files.base import ContentFile
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
import structlog

from ..utils import auth_utils
from ..models import User, KYCDocument
from ..Serializers.KYC_serializers import KYCVerifySerializer
from ..Services.KYC_services import kyc_service
from ..Services.kyc_security_service import kyc_security_service


logger = structlog.get_logger(__name__)


class KYCVerifyView(APIView):
    """
    POST /api/kyc/verify/
    Soumission d'un document d'identité pour vérification via Didit Standalone API
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Soumettre un document KYC + Selfie",
        description=(
            "Envoie un document d'identité (recto/verso) et optionnellement un selfie pour vérification Didit v3. "
            "Le verso est désormais optionnel pour les passeports. Si un selfie est fourni, un Face Match v3 est effectué."
        ),
        request=KYCVerifySerializer,
        tags=['Profil & KYC'],
        responses={
            200: inline_serializer(
                name='KYCApprovalResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'message': serializers.CharField(),
                    'kyc_status': serializers.CharField(),
                    'vendor_data': serializers.CharField(),
                    'request_id': serializers.CharField(),
                    'extracted_data': serializers.JSONField(),
                    'metadata': serializers.JSONField()
                }
            ),
            202: {"description": "Document reçu, en attente de vérification manuelle"},
            400: inline_serializer(
                name='KYCRejectionResponse',
                fields={
                    'success': serializers.BooleanField(),
                    'message': serializers.CharField(),
                    'didit_status': serializers.CharField(),
                    'decline_reason': serializers.CharField(),
                    'vendor_data': serializers.CharField(),
                    'request_id': serializers.CharField(),
                    'retry_allowed': serializers.BooleanField(),
                    'retry_count': serializers.IntegerField(),
                    'remaining_attempts': serializers.IntegerField(),
                    'suggestions': serializers.ListField(child=serializers.CharField()),
                    'next_step': serializers.CharField()
                }
            ),
            403: {"description": "Numéro de téléphone non vérifié"},
            429: {"description": "Trop de tentatives"},
            502: inline_serializer(
                name='KYCTechnicalError',
                fields={
                    'success': serializers.BooleanField(),
                    'error': serializers.CharField(),
                    'code': serializers.CharField(),
                    'vendor_data': serializers.CharField(),
                    'retry_count': serializers.IntegerField(),
                    'remaining_attempts': serializers.IntegerField(),
                    'next_step': serializers.CharField()
                }
            )
        }
    )
    def post(self, request):
        serializer = KYCVerifySerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                "kyc_validation_failed",
                user_id=str(request.user.id),
                errors=serializer.errors
            )
            return Response(
                {"error": "Données invalides", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user

        if not user.phone_verified:
            return Response({
                "success": False,
                "error": "Vous devez d'abord vérifier votre numéro de téléphone",
                "code": "phone_not_verified",
                "next_step": "verify_phone"
            }, status=status.HTTP_403_FORBIDDEN)

        if user.kyc_status == 'verified':
            return Response({
                "success": True,
                "message": "Votre identité est déjà vérifiée.",
                "kyc_status": "verified"
            }, status=status.HTTP_200_OK)

        # Rate limiting global par IP : 10 tentatives par heure
        client_ip = auth_utils.get_client_ip(request)
        global_limit_key = f"kyc_global_{client_ip}"
        if auth_utils.is_rate_limited(global_limit_key, limit=10, window_seconds=3600):
            return Response({
                "error": "Trop de tentatives KYC depuis cette adresse IP (limite : 10 par heure)",
                "code": "kyc_global_rate_limited",
                "retry_after": 3600
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Rate limiting : 3 tentatives par heure
        kyc_limit_key = f"kyc_attempts_{user.id}"
        if auth_utils.is_rate_limited(kyc_limit_key, limit=3, window_seconds=3600):
            return Response({
                "error": "Trop de tentatives KYC récentes (limite : 3 par heure)",
                "code": "kyc_rate_limited",
                "retry_after": 3600
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        validated_data = serializer.validated_data
        document_type = validated_data['document_type']
        front_image = validated_data['front_image']
        back_image = validated_data.get('back_image')
        selfie_image = validated_data.get('selfie_image')
        vendor_data = validated_data.get('vendor_data') or f"auto_{user.id}_{timezone.now().strftime('%Y%m%d%H%M%S')}"

        # Création de l'enregistrement local
        try:
            kyc_doc = KYCDocument.objects.create(
                user=user,
                document_type=document_type,
                vendor_data=vendor_data,
                verification_status='pending',
                created_at=timezone.now(),
            )
            filename_prefix = f"kyc_{user.id}_{vendor_data}"
            kyc_doc.front_image.save(f"{filename_prefix}_front.jpg", front_image)
            if back_image:
                kyc_doc.back_image.save(f"{filename_prefix}_back.jpg", back_image)
            if selfie_image:
                kyc_doc.selfie_image.save(f"{filename_prefix}_selfie.jpg", selfie_image)
            # --- AUDIT TRAIL ---
            kyc_doc.accessed_at = timezone.now()
            kyc_doc.accessed_by = str(user.id)
            kyc_doc.save()
            
        except Exception as e:
            logger.error("kyc_document_creation_error", user_id=str(user.id), error=str(e))
            return Response({
                "success": False,
                "error": "Erreur lors de l'enregistrement du document",
                "code": "document_save_error"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Appel à Didit avec les paramètres EXACTS
        try:
            result = kyc_service.verify_id_document(
                front_image=front_image,
                back_image=back_image,
                perform_document_liveness=validated_data.get('perform_document_liveness', False),
                minimum_age=validated_data.get('minimum_age'),  # ← Nom correct Didit
                expiration_date_not_detected_action=validated_data.get('expiration_date_not_detected_action', 'DECLINE'),
                invalid_mrz_action=validated_data.get('invalid_mrz_action', 'DECLINE'),
                inconsistent_data_action=validated_data.get('inconsistent_data_action', 'DECLINE'),
                preferred_characters=validated_data.get('preferred_characters', 'latin'),
                save_api_request=validated_data.get('save_api_request', True),
                vendor_data=vendor_data,
            )

        except Exception as e:
            logger.error("kyc_service_exception", user_id=str(user.id), error=str(e))
            
            kyc_doc.verification_status = 'failed'
            kyc_doc.verification_note = f"Exception lors appel Didit : {str(e)}"
            kyc_doc.save()
            
            user.kyc_retry_count += 1
            user.kyc_last_attempt = timezone.now()
            user.save()
            
            return Response({
                "success": False,
                "error": "Erreur lors de l'appel au service de vérification",
                "code": "service_exception",
                "vendor_data": vendor_data,
                "retry_count": user.kyc_retry_count,
                "remaining_attempts": max(0, 3 - user.kyc_retry_count),
                "next_step": "retry_kyc" if user.kyc_retry_count < 3 else "contact_support"
            }, status=status.HTTP_502_BAD_GATEWAY)

        # Traitement du résultat
        if not result["success"]:
            return self._handle_kyc_failure(user, kyc_doc, result, vendor_data)

        status_didit = result["status"]
        id_verification = result["id_verification"]

        # Sauvegarde des métadonnées Didit
        kyc_doc.didit_request_id = result.get("request_id")
        kyc_doc.raw_id_verification = id_verification
        kyc_doc.save()

        if status_didit == "Approved":
            # Si un selfie a été fourni, on lance le Face Match v3
            if selfie_image:
                logger.info("kyc_face_match_v3_starting", user_id=str(user.id), vendor_data=vendor_data)
                
                # Récupération de l'image de visage extraite (portrait_image) par Didit ID Verification v3
                # Si non disponible, on fallback sur le front_image original
                portrait_b64 = id_verification.get("portrait_image")
                
                ref_image_to_use = front_image
                if portrait_b64:
                    try:
                        format, imgstr = portrait_b64.split(';base64,') if ';base64,' in portrait_b64 else (None, portrait_b64)
                        ext = format.split('/')[-1] if format else 'jpg'
                        ref_image_to_use = ContentFile(base64.b64decode(imgstr), name=f"portrait_extracted.{ext}")
                    except Exception as e:
                        logger.warning("kyc_portrait_extraction_failed", error=str(e))
                        # On continue avec front_image

                match_result = kyc_service.match_face(
                    selfie_image=selfie_image,
                    ref_image=ref_image_to_use,
                    vendor_data=vendor_data
                )
                
                if not match_result["success"] or match_result["status"] != "Approved":
                    # Échec du Face Match -> Rejet du KYC même si le document était OK
                    reason = match_result.get("status") or match_result.get("message", "Échec Face Match")
                    logger.warning("kyc_face_match_failed", user_id=str(user.id), reason=reason)
                    
                    result["status"] = "FaceMatchFailed"
                    id_verification["decline_reason"] = f"La photo ne correspond pas au document ({reason})"
                    return self._handle_kyc_rejection(user, kyc_doc, result, id_verification, vendor_data)

                logger.info("kyc_face_match_approved", user_id=str(user.id), score=match_result.get("score"))
                kyc_doc.verification_note += f" | Face Match OK (Score: {match_result.get('score')})"
                kyc_doc.save()

            return self._handle_kyc_approval(user, kyc_doc, result, id_verification, vendor_data)
        elif status_didit == "Pending":
            return self._handle_kyc_pending(user, kyc_doc, result, id_verification, vendor_data)
        else:
            return self._handle_kyc_rejection(user, kyc_doc, result, id_verification, vendor_data)

    # -------------------------------------------------------------------
    # Les méthodes suivantes restent INCHANGÉES (elles sont déjà correctes)
    # -------------------------------------------------------------------

    def _handle_kyc_failure(self, user, kyc_doc, result, vendor_data):
        kyc_doc.verification_status = 'failed'
        kyc_doc.verification_note = result.get("message", "Échec technique")
        kyc_doc.didit_request_id = result.get("request_id")
        kyc_doc.save()

        user.kyc_retry_count += 1
        user.kyc_last_attempt = timezone.now()
        user.save()

        logger.warning(
            "kyc_technical_failure",
            user_id=str(user.id),
            vendor_data=vendor_data,
            error=result.get("message")
        )

        return Response({
            "success": False,
            "error": "Échec de la vérification technique",
            "message": result.get("message", "Erreur inconnue"),
            "vendor_data": vendor_data,
            "retry_count": user.kyc_retry_count,
            "remaining_attempts": max(0, 3 - user.kyc_retry_count),
            "next_step": "retry_kyc" if user.kyc_retry_count < 3 else "contact_support"
        }, status=status.HTTP_502_BAD_GATEWAY)

    def _handle_kyc_approval(self, user, kyc_doc, result, id_verification, vendor_data):
        user.kyc_status = 'verified'
        user.kyc_verified_at = timezone.now()
        user.kyc_request_id = result["request_id"]
        user.kyc_vendor_data = vendor_data
        user.kyc_retry_count = 0
        
        self._enrich_user_from_kyc(user, id_verification, kyc_doc.document_type)
        user.save()

        kyc_doc.verification_status = 'approved'
        kyc_doc.verified_at = timezone.now()
        kyc_doc.verification_note = f"Approved by Didit - Vendor: {vendor_data}"
        kyc_doc.save()

        logger.info(
            "kyc_approved",
            user_id=str(user.id),
            vendor_data=vendor_data,
            request_id=result["request_id"],
            document_type=id_verification.get("document_type")
        )

        return Response({
            "success": True,
            "message": "Félicitations ! Votre identité a été vérifiée avec succès.",
            "kyc_status": "verified",
            "vendor_data": vendor_data,
            "request_id": result["request_id"],
            "extracted_data": self._format_extracted_data(user),
            "metadata": {
                "verified_at": user.kyc_verified_at.isoformat() if user.kyc_verified_at else None,
                "document_type": user.kyc_document_type,
                "vendor_data": vendor_data
            }
        }, status=status.HTTP_200_OK)

    def _handle_kyc_pending(self, user, kyc_doc, result, id_verification, vendor_data):
        user.kyc_status = 'pending'
        user.kyc_vendor_data = vendor_data
        user.kyc_request_id = result.get("request_id")
        user.save()

        kyc_doc.verification_status = 'pending'
        kyc_doc.save()

        logger.info(
            "kyc_pending",
            user_id=str(user.id),
            vendor_data=vendor_data,
            request_id=result.get("request_id")
        )

        return Response({
            "success": True,
            "message": "Votre document est en cours de revue manuelle. Nous vous informerons dès que possible.",
            "kyc_status": "pending",
            "vendor_data": vendor_data,
            "request_id": result.get("request_id"),
        }, status=status.HTTP_202_ACCEPTED)

    def _handle_kyc_rejection(self, user, kyc_doc, result, id_verification, vendor_data):
        user.kyc_status = 'rejected'
        user.kyc_retry_count += 1
        user.kyc_last_attempt = timezone.now()
        user.kyc_vendor_data = vendor_data
        user.save()

        kyc_doc.verification_status = 'rejected'
        kyc_doc.verification_note = (
            f"Didit: {result['status']} - "
            f"{id_verification.get('decline_reason', 'No reason')} - "
            f"Vendor: {vendor_data}"
        )
        kyc_doc.save()

        logger.warning(
            "kyc_declined",
            user_id=str(user.id),
            vendor_data=vendor_data,
            didit_status=result['status'],
            decline_reason=id_verification.get('decline_reason'),
            retry_count=user.kyc_retry_count
        )

        return Response({
            "success": False,
            "message": "Votre document n'a pas pu être vérifié.",
            "didit_status": result['status'],
            "decline_reason": id_verification.get("decline_reason", "Raison non spécifiée"),
            "vendor_data": vendor_data,
            "request_id": result.get("request_id"),
            "retry_allowed": user.kyc_retry_count < 3,
            "retry_count": user.kyc_retry_count,
            "remaining_attempts": max(0, 3 - user.kyc_retry_count),
            "suggestions": self._get_rejection_suggestions(id_verification),
            "next_step": "retry_kyc" if user.kyc_retry_count < 3 else "contact_support"
        }, status=status.HTTP_400_BAD_REQUEST)

    def _enrich_user_from_kyc(self, user, id_verification, document_type):
        user.first_name = id_verification.get("first_name", user.first_name)
        user.last_name = id_verification.get("last_name", user.last_name)
        user.kyc_document_type = id_verification.get("document_type", document_type)
        user.kyc_document_number = id_verification.get("document_number", "")[:50]
        
        dob_str = id_verification.get("date_of_birth")
        if dob_str:
            try:
                user.kyc_date_of_birth = datetime.strptime(dob_str, "%Y-%m-%d").date()
            except ValueError:
                pass
        
        issue_str = id_verification.get("date_of_issue")
        if issue_str:
            try:
                user.kyc_date_of_issue = datetime.strptime(issue_str, "%Y-%m-%d").date()
            except ValueError:
                pass

        user.kyc_expiration_date = id_verification.get("expiration_date")
        user.kyc_gender = id_verification.get("gender", "")[:20]
        user.kyc_nationality = id_verification.get("nationality", "")[:100]
        user.kyc_place_of_birth = id_verification.get("place_of_birth", "")[:200]
        user.kyc_address = id_verification.get("formatted_address") or id_verification.get("address", "")[:500]
        
        # Tentative d'extraction des champs d'adresse structurés
        # Didit peut renvoyer ces champs dans address_details ou directement
        user.city = id_verification.get("city") or id_verification.get("locality") or user.city
        user.postal_code = id_verification.get("postal_code") or id_verification.get("zip_code") or user.postal_code
        user.state = id_verification.get("state") or id_verification.get("region") or id_verification.get("subdivision") or user.state

        # Fallback simple: si l'adresse est une chaîne et que les champs sont vides
        if not user.city and user.kyc_address and ',' in user.kyc_address:
            parts = [p.strip() for p in user.kyc_address.split(',')]
            if len(parts) >= 2:
                user.city = parts[-2]  # Souvent [Adresse, Ville, Pays]

        user.kyc_issuing_country = id_verification.get("issuing_state_name") or id_verification.get("issuing_state", "")[:100]
        user.kyc_personal_number = id_verification.get("personal_number", "")[:100]
        user.kyc_full_name = id_verification.get("full_name", "")[:200]
        user.kyc_marital_status = id_verification.get("marital_status", "")[:50]

    def _format_extracted_data(self, user):
        return {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": user.kyc_full_name,
            "date_of_birth": user.kyc_date_of_birth.isoformat() if user.kyc_date_of_birth else None,
            "date_of_issue": user.kyc_date_of_issue.isoformat() if user.kyc_date_of_issue else None,
            "document_number": user.kyc_document_number,
            "nationality": user.kyc_nationality,
            "issuing_country": user.kyc_issuing_country,
            "document_type": user.kyc_document_type,
            "gender": user.kyc_gender,
            "marital_status": user.kyc_marital_status,
        }

    def _get_rejection_suggestions(self, id_verification):
        decline_reason = (id_verification.get("decline_reason") or "").lower()
        suggestions = []
        
        if "blurry" in decline_reason or "unclear" in decline_reason:
            suggestions.append("Prenez une photo nette et bien éclairée")
        if "expired" in decline_reason:
            suggestions.append("Utilisez un document non expiré")
        if "damaged" in decline_reason:
            suggestions.append("Le document ne doit pas être endommagé")
        if "mismatch" in decline_reason or "inconsistent" in decline_reason:
            suggestions.append("Vérifiez la cohérence des informations")
        if "cut off" in decline_reason or "cropped" in decline_reason:
            suggestions.append("Photographiez l'intégralité du document")
        
        if not suggestions:
            suggestions.append("Vérifiez que le document est valide et lisible")
        
        return suggestions