# Dans ton fichier views.py (ajoute ou remplace la vue KYC)

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
import structlog

from ..models import User, KYCDocument
from ..Serializers.KYC_serializers import KYCVerifySerializer  # À créer ou mettre à jour
from ..Services.KYC_services import kyc_service

logger = structlog.get_logger(__name__)


class KYCVerifyView(APIView):
    """
    POST /api/kyc/verify/
    
    Endpoint unique pour la vérification KYC via Didit ID Verification Standalone API.
    - Authentification requise (token bearer)
    - Upload recto + verso (verso optionnel)
    - Traitement synchrone : réponse immédiate avec résultat Didit
    - Mise à jour automatique du profil utilisateur si Approved
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = KYCVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "Données invalides", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user

        # Vérifications de sécurité
        if user.kyc_status == 'verified':
            return Response({
                "success": True,
                "message": "Votre identité est déjà vérifiée.",
                "kyc_status": "verified"
            }, status=status.HTTP_200_OK)

        if user.kyc_retry_count >= 3:
            return Response({
                "error": "Vous avez atteint la limite de 3 tentatives KYC.",
                "code": "max_retries_reached"
            }, status=status.HTTP_403_FORBIDDEN)

        document_type = serializer.validated_data['document_type']
        front_image = serializer.validated_data['front_image']
        back_image = serializer.validated_data.get('back_image')

        # Création de l'enregistrement local KYCDocument (traçabilité)
        kyc_doc = KYCDocument.objects.create(
            user=user,
            document_type=document_type,
            front_image=front_image,
            back_image=back_image,
            verification_status='pending',
            created_at=timezone.now()
        )

        # Sauvegarde des fichiers avec noms uniques
        kyc_doc.front_image.save(f"kyc_{user.id}_{kyc_doc.id}_front.jpg", front_image)
        if back_image:
            kyc_doc.back_image.save(f"kyc_{user.id}_{kyc_doc.id}_back.jpg", back_image)
        kyc_doc.save()

        # Appel au service Didit
        result = kyc_service.verify_id_document(
            front_image=kyc_doc.front_image.open('rb'),  # File-like object
            back_image=kyc_doc.back_image.open('rb') if kyc_doc.back_image else None,
            perform_document_liveness=serializer.validated_data.get('perform_document_liveness', True),
            min_age=serializer.validated_data.get('min_age'),
            external_id=str(user.id),
        )

        # Gestion de l'échec technique
        if not result["success"]:
            kyc_doc.verification_status = 'rejected'
            kyc_doc.verification_note = result.get("message", "Erreur technique Didit")
            kyc_doc.save()

            user.kyc_retry_count += 1
            user.save()

            logger.warning(
                "kyc_technical_failure",
                user_id=str(user.id),
                error=result.get("message")
            )

            return Response({
                "success": False,
                "error": "Échec de la vérification technique",
                "message": result.get("message"),
                "retry_count": user.kyc_retry_count
            }, status=status.HTTP_502_BAD_GATEWAY)

        # Succès technique → analyse du résultat Didit
        status_didit = result["status"]  # "Approved" ou "Declined"
        id_verification = result["id_verification"]

        if status_didit == "Approved":
            # === KYC ACCEPTÉ ===
            user.kyc_status = 'verified'
            user.kyc_verified_at = timezone.now()
            user.kyc_request_id = result["request_id"]

            # Enrichissement du profil avec données extraites
            user.first_name = id_verification.get("first_name", user.first_name)
            user.last_name = id_verification.get("last_name", user.last_name)
            user.kyc_document_type = id_verification.get("document_type", document_type)
            user.kyc_document_number = id_verification.get("document_number", "")
            user.kyc_date_of_birth = id_verification.get("date_of_birth")  # format "YYYY-MM-DD"
            user.kyc_expiration_date = id_verification.get("expiration_date")
            user.kyc_gender = id_verification.get("gender", "")
            user.kyc_nationality = id_verification.get("nationality", "")
            user.kyc_place_of_birth = id_verification.get("place_of_birth", "")
            user.kyc_address = id_verification.get("formatted_address", "")
            user.kyc_retry_count = 0  # Reset retries
            user.save()

            # Mise à jour document
            kyc_doc.verification_status = 'approved'
            kyc_doc.verified_at = timezone.now()
            kyc_doc.verification_note = "Approved by Didit"
            kyc_doc.save()

            logger.info("kyc_approved", user_id=str(user.id), request_id=result["request_id"])

            return Response({
                "success": True,
                "message": "Félicitations ! Votre identité a été vérifiée avec succès.",
                "kyc_status": "verified",
                "extracted_data": {
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "date_of_birth": user.kyc_date_of_birth,
                    "document_number": user.kyc_document_number,
                    "nationality": user.kyc_nationality
                }
            }, status=status.HTTP_200_OK)

        else:
            # === KYC REFUSÉ ===
            user.kyc_status = 'rejected'
            user.kyc_retry_count += 1
            user.save()

            kyc_doc.verification_status = 'rejected'
            kyc_doc.verification_note = f"Didit status: {status_didit} - {id_verification.get('decline_reason', '')}"
            kyc_doc.save()

            logger.warning(
                "kyc_declined",
                user_id=str(user.id),
                didit_status=status_didit,
                decline_reason=id_verification.get("decline_reason"),
                retry_count=user.kyc_retry_count
            )

            return Response({
                "success": False,
                "message": "Votre document n'a pas pu être vérifié.",
                "didit_status": status_didit,
                "decline_reason": id_verification.get("decline_reason"),
                "retry_allowed": user.kyc_retry_count < 3,
                "retry_count": user.kyc_retry_count
            }, status=status.HTTP_400_BAD_REQUEST)