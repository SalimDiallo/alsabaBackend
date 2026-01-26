from rest_framework import serializers
from PIL import Image
import io
from django.core.exceptions import ValidationError

def validate_file_size(value):
    max_size = 5 * 1024 * 1024  # 5MB
    if value.size > max_size:
        raise ValidationError("Le fichier ne doit pas dépasser 5MB.")

def validate_file_type(value):
    allowed_types = ['image/jpeg', 'image/png', 'image/webp', 'image/tiff', 'application/pdf']
    if hasattr(value, 'content_type') and value.content_type not in allowed_types:
        raise ValidationError("Type de fichier non autorisé. Utilisez JPEG, PNG, WebP, TIFF ou PDF.")

class KYCVerifySerializer(serializers.Serializer):
    DOCUMENT_TYPE_CHOICES = [
        ('id_card', 'Carte d\'identité'),
        ('passport', 'Passeport'),
        ('drivers_license', 'Permis de conduire'),
        ('residence_permit', 'Titre de séjour'),
    ]

    document_type = serializers.ChoiceField(
        choices=DOCUMENT_TYPE_CHOICES,
        required=True,
        help_text="Type de document d'identité"
    )

    front_image = serializers.FileField(  # ← Changé en FileField car Didit accepte aussi PDF
        required=True,
        help_text="Recto du document (JPEG, PNG, WebP, TIFF, PDF - max 5MB)",
        validators=[validate_file_size, validate_file_type]
    )

    back_image = serializers.FileField(
        required=False,
        allow_null=True,
        help_text="Verso du document (requis pour documents recto-verso - JPEG, PNG, WebP, TIFF, PDF - max 5MB)",
        validators=[validate_file_size, validate_file_type]
    )

    perform_document_liveness = serializers.BooleanField(
        default=False,  # ← Valeur par défaut officielle Didit = false
        help_text="Active la détection de fraude sur le document (photo de photo, copie d'écran, etc.)"
    )

    minimum_age = serializers.IntegerField(  # ← Nom corrigé : minimum_age (pas min_age)
        min_value=1,
        max_value=120,
        required=False,
        allow_null=True,
        help_text="Âge minimum requis (1-120). Utilisateurs plus jeunes seront refusés."
    )

    expiration_date_not_detected_action = serializers.ChoiceField(  # ← Nom exact Didit
        choices=[("NO_ACTION", "Ignorer"), ("DECLINE", "Refuser")],
        default="DECLINE",
        help_text="Action si date d'expiration non détectée"
    )

    invalid_mrz_action = serializers.ChoiceField(  # ← Nom exact Didit
        choices=[("NO_ACTION", "Ignorer"), ("DECLINE", "Refuser")],
        default="DECLINE",
        help_text="Action si échec lecture MRZ"
    )

    inconsistent_data_action = serializers.ChoiceField(  # ← Nom exact Didit
        choices=[("NO_ACTION", "Ignorer"), ("DECLINE", "Refuser")],
        default="DECLINE",
        help_text="Action si incohérence entre VIZ et MRZ"
    )

    preferred_characters = serializers.ChoiceField(  # ← Nom exact Didit
        choices=[("latin", "Latin"), ("non_latin", "Non-latin")],
        default="latin",
        help_text="Jeu de caractères préféré quand plusieurs scripts sont disponibles"
    )

    save_api_request = serializers.BooleanField(  # ← Nom exact Didit
        default=True,
        help_text="Enregistrer cette requête dans la console Didit (Manual Checks)"
    )

    vendor_data = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
        help_text="Identifiant unique vendor/user (UUID, email, etc.) pour tracking"
    )

    # Validation spécifique
    def validate_front_image(self, value):
        return self._validate_image(value, "recto")

    def validate_back_image(self, value):
        if value:
            return self._validate_image(value, "verso")
        return value

    def _validate_image(self, image, side):
        errors = []

        # Taille
        if hasattr(image, 'size') and image.size > 5 * 1024 * 1024:
            errors.append("Taille maximale : 5 Mo")

        # MIME réel - validation simplifiée
        if hasattr(image, 'content_type'):
            allowed = {
                'image/jpeg', 'image/jpg', 'image/png',
                'image/webp', 'image/tiff', 'application/pdf'
            }
            if image.content_type not in allowed:
                errors.append(f"Format non supporté : {image.content_type} (JPEG, PNG, WebP, TIFF, PDF seulement)")

        # PIL (seulement pour images, pas PDF)
        try:
            if 'pdf' not in mime.lower():
                image.seek(0)
                img_data = image.read()
                image.seek(0)

                buf = io.BytesIO(img_data)
                img = Image.open(buf)
                img.verify()
                buf.seek(0)
                img = Image.open(buf)
                img.load()

                if img.width < 800 or img.height < 600:
                    errors.append("Résolution trop faible (min 800×600 recommandé)")
                
                ratio = img.width / img.height
                if not 0.5 <= ratio <= 2.0:
                    errors.append("Proportions incorrectes pour un document")
        except Exception:
            pass  # On tolère les PDF → pas d'erreur si PIL échoue sur PDF

        if errors:
            raise serializers.ValidationError(f"Image {side} invalide : {' ; '.join(errors)}")

        image.seek(0)
        return image

    def validate(self, data):
        dt = data.get('document_type')
        back = data.get('back_image')

        requires_back = {'id_card', 'drivers_license', 'residence_permit'}
        no_back = {'passport'}

        if dt in requires_back and not back:
            raise serializers.ValidationError({
                "back_image": f"Verso obligatoire pour {dict(self.DOCUMENT_TYPE_CHOICES)[dt]}"
            })

        if dt in no_back and back:
            raise serializers.ValidationError({
                "back_image": f"Verso non requis pour {dict(self.DOCUMENT_TYPE_CHOICES)[dt]}"
            })

        return data

    def to_internal_value(self, data):
        data = super().to_internal_value(data)

        if not data.get('vendor_data'):
            from datetime import datetime
            import hashlib, uuid
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            uid = str(uuid.uuid4())[:8]
            h = hashlib.md5(f"{ts}_{uid}".encode()).hexdigest()[:8]
            data['vendor_data'] = f"kyc_{ts}_{h}"

        return data