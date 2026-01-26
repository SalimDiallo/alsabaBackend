from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
import uuid
import phonenumbers
from phonenumbers import PhoneNumberFormat


class UserManager(BaseUserManager):
    def create_user(self, phone_number, country_code="+33", password=None, **extra_fields):
        if not phone_number:
            raise ValueError("Le numéro de téléphone est obligatoire")

        full_phone = f"{country_code}{phone_number}"
        try:
            parsed = phonenumbers.parse(full_phone, None)
            if not phonenumbers.is_valid_number(parsed):
                raise ValueError("Numéro de téléphone invalide")
            
            country_code = f"+{parsed.country_code}"
            national_number = str(parsed.national_number)
            full_phone_e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            raise ValueError("Format de numéro invalide")

        user = self.model(
            country_code=country_code,
            phone_number=national_number,
            full_phone_number=full_phone_e164,
            **extra_fields,
        )

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number, country_code="+33", password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("phone_verified", True)

        return self.create_user(phone_number, country_code, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    KYC_STATUS_CHOICES = (
        ("unverified", "Non vérifié"),
        ("pending", "En attente de vérification"),
        ("verified", "Vérifié"),
        ("rejected", "Rejeté"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    phone_number = models.CharField(max_length=15, db_index=True, null=True, blank=True)
    country_code = models.CharField(max_length=4, db_index=True)
    full_phone_number = models.CharField(max_length=20, unique=True, db_index=True)

    email = models.EmailField(blank=True, null=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    profile_updated_at = models.DateTimeField(null=True, blank=True)

    kyc_status = models.CharField(max_length=20, choices=KYC_STATUS_CHOICES, default="unverified")
    kyc_submitted_at = models.DateTimeField(null=True, blank=True)
    kyc_verified_at = models.DateTimeField(null=True, blank=True)
    kyc_request_id = models.CharField(max_length=100, blank=True, null=True)
    kyc_retry_count = models.IntegerField(default=0)
    kyc_last_attempt = models.DateTimeField(null=True, blank=True)
    kyc_vendor_data = models.CharField(max_length=100, blank=True, null=True)
    kyc_document_type = models.CharField(max_length=20, blank=True, null=True)
    kyc_document_number = models.CharField(max_length=100, blank=True, null=True)
    kyc_date_of_birth = models.DateField(null=True, blank=True)
    kyc_expiration_date = models.DateField(null=True, blank=True)
    kyc_gender = models.CharField(max_length=20, blank=True, null=True)
    kyc_nationality = models.CharField(max_length=100, blank=True, null=True)
    kyc_place_of_birth = models.CharField(max_length=200, blank=True, null=True)
    kyc_address = models.TextField(blank=True, null=True)
    
    # Champs supplémentaires extraits de Didit
    kyc_issuing_country = models.CharField(max_length=100, blank=True, null=True)
    kyc_personal_number = models.CharField(max_length=100, blank=True, null=True)
    kyc_date_of_issue = models.DateField(null=True, blank=True)
    kyc_full_name = models.CharField(max_length=200, blank=True, null=True)
    kyc_marital_status = models.CharField(max_length=50, blank=True, null=True)

    # Autres champs existants
    carrier = models.CharField(max_length=100, blank=True)
    is_disposable = models.BooleanField(default=False)
    is_voip = models.BooleanField(default=False)

    is_staff = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)
    phone_verified_at = models.DateTimeField(null=True, blank=True)

    didit_session_uuid = models.CharField(max_length=100, blank=True, null=True)
    didit_session_expires = models.DateTimeField(null=True, blank=True)

    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_reason = models.CharField(max_length=100, blank=True)
    deleted_phone_number = models.CharField(max_length=20, blank=True, null=True)
    
    objects = UserManager()

    USERNAME_FIELD = "full_phone_number"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        constraints = [
            models.UniqueConstraint(
                fields=["country_code", "phone_number"],
                name="unique_country_code_phone_number"
            )
        ]
        indexes = [
            models.Index(fields=["full_phone_number"]),
            models.Index(fields=["country_code", "phone_number"]),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        from datetime import date
        if self.kyc_date_of_birth:
            today = date.today()
            age = today.year - self.kyc_date_of_birth.year - ((today.month, today.day) < (self.kyc_date_of_birth.month, self.kyc_date_of_birth.day))
            if age < 18:
                raise ValidationError("L'utilisateur doit avoir au moins 18 ans pour la vérification KYC.")

    def __str__(self):
        return self.full_phone_number

    def soft_delete(self, reason="user_requested"):
        self.is_active = False
        self.deleted_at = timezone.now()
        self.deleted_reason = reason
        self.deleted_phone_number = self.full_phone_number
        self.full_phone_number = f"deleted_{self.full_phone_number}"
        self.phone_number = None
        self.save()


class KYCDocument(models.Model):
    DOCUMENT_TYPES = (
        ("id_card", "Carte d'identité"),
        ("passport", "Passeport"),
        ("drivers_license", "Permis de conduire"),
        ("residence_permit", "Titre de séjour"),
    )

    VERIFICATION_STATUS = (
        ("pending", "En attente"),
        ("approved", "Approuvé"),
        ("rejected", "Rejeté"),
        ("review", "En revue manuelle"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="kyc_documents")
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES)
    front_image = models.ImageField(upload_to="kyc_documents/")
    back_image = models.ImageField(upload_to="kyc_documents/", blank=True, null=True)
    selfie_image = models.ImageField(upload_to="kyc_selfies/", blank=True, null=True)

    verification_status = models.CharField(max_length=20, choices=VERIFICATION_STATUS, default="pending")
    verification_note = models.TextField(blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Champs Didit spécifiques
    didit_request_id = models.CharField(max_length=100, blank=True, null=True)
    vendor_data = models.CharField(max_length=100, blank=True, null=True)
    raw_id_verification = models.JSONField(default=dict, blank=True, null=True)

    class Meta:
        db_table = "kyc_documents"
        verbose_name = "Document KYC"
        verbose_name_plural = "Documents KYC"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "document_type"],
                name="unique_user_document_type"
            )
        ]

    def __str__(self):
        return f"{self.user} - {self.get_document_type_display()} ({self.get_verification_status_display()})"