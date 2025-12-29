# apps/auth/Serializers/OTP_serializers.py
# (ou Accounts/serializers.py selon ton organisation)

from rest_framework import serializers
from ..models import KYCDocument

class KYCVerifySerializer(serializers.Serializer):
    """
    Serializer pour l'endpoint POST /api/kyc/verify/
    Gère l'upload et la vérification KYC via Didit Standalone API
    """
    document_type = serializers.ChoiceField(
        choices=KYCDocument.DOCUMENT_TYPES,
        help_text="Type de document : id_card, passport, drivers_license"
    )

    front_image = serializers.ImageField(
        max_length=None,
        use_url=False,
        required=True,
        help_text="Photo du recto du document (obligatoire, format JPG/PNG ≤ 5MB)"
    )

    back_image = serializers.ImageField(
        max_length=None,
        use_url=False,
        required=False,
        allow_null=True,
        help_text="Photo du verso du document (optionnel pour certains documents)"
    )

    perform_document_liveness = serializers.BooleanField(
        default=True,
        help_text="Active la détection de copies d'écran et manipulation du portrait (fortement recommandé)"
    )

    min_age = serializers.IntegerField(
        min_value=16,
        max_value=120,
        required=False,
        allow_null=True,
        help_text="Âge minimum requis pour accepter le document (ex: 18 pour services 18+)"
    )

    external_id = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        help_text="ID externe pour tracking Didit (par défaut : user.id)"
    )

    expiration_action = serializers.ChoiceField(
        choices=["NO_ACTION", "DECLINE"],
        default="DECLINE",
        help_text="Action si document expiré"
    )
    
    mrz_failure_action = serializers.ChoiceField(
        choices=["NO_ACTION", "DECLINE"],
        default="DECLINE"
    )
    
    viz_consistency_action = serializers.ChoiceField(
        choices=["NO_ACTION", "DECLINE"],
        default="DECLINE"
    )

    def validate_front_image(self, value):
        if not value:
            raise serializers.ValidationError("Le recto du document est obligatoire.")
        
        # Taille max 5MB (conforme à Didit)
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("L'image du recto ne doit pas dépasser 5MB.")
        
        return value

    def validate_back_image(self, value):
        if value:
            if value.size > 5 * 1024 * 1024:
                raise serializers.ValidationError("L'image du verso ne doit pas dépasser 5MB.")
        return value

    def validate(self, data):
        """
        Validation croisée supplémentaire
        """
        document_type = data.get('document_type')

        # Exemple : certains documents nécessitent le verso
        if document_type in ['id_card', 'drivers_license']:
            if not data.get('back_image'):
                raise serializers.ValidationError({
                    "back_image": "Le verso est requis pour ce type de document."
                })

        return data