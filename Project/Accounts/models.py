from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
import uuid


class UserManager(BaseUserManager):
    def create_user(self, phone_number, country_code, password=None, **extra_fields):
        if not phone_number:
            raise ValueError('Le numéro de téléphone est obligatoire')
        
        user = self.model(
            phone_number=phone_number,
            country_code=country_code,
            **extra_fields
        )
        
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
            
        user.save(using=self._db)
        return user
    
    def create_superuser(self, phone_number, country_code, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_verified', True)
        
        return self.create_user(phone_number, country_code, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    STATUS_CHOICES = (
        ('unverified', 'Non vérifié'),
        ('pending', 'En attente de vérification'),
        ('verified', 'Vérifié'),
        ('rejected', 'Rejeté'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number = models.CharField(max_length=20, unique=True)
    country_code = models.CharField(max_length=5)
    email = models.EmailField(blank=True, null=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    profile_updated_at = models.DateTimeField(null=True, blank=True)
    # Statut KYC
    kyc_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unverified')
    kyc_submitted_at = models.DateTimeField(null=True, blank=True)
    kyc_verified_at = models.DateTimeField(null=True, blank=True)
    persona_inquiry_id = models.CharField(max_length=100, blank=True, null=True)
    
    # Flags
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    
    # Dates
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = ['country_code']
    
    class Meta:
        db_table = 'users'
        verbose_name = 'Utilisateur'
        verbose_name_plural = 'Utilisateurs'
    
    def __str__(self):
        return f"{self.country_code}{self.phone_number}"
    
    @property
    def full_phone(self):
        return f"{self.country_code}{self.phone_number}"


class KYCDocument(models.Model):
    DOCUMENT_TYPES = (
        ('id_card', "Carte d'identité"),
        ('passport', 'Passeport'),
        ('drivers_license', 'Permis de conduire'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='kyc_documents')
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES)
    front_image = models.ImageField(upload_to='kyc_documents/')
    back_image = models.ImageField(upload_to='kyc_documents/', blank=True, null=True)
    selfie_image = models.ImageField(upload_to='kyc_selfies/', blank=True, null=True)
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    verified = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'kyc_documents'
        verbose_name = 'Document KYC'
        verbose_name_plural = 'Documents KYC'
    
    def __str__(self):
        return f"{self.user} - {self.get_document_type_display()}"
    
    
    
# OTP Model
class OTPCode(models.Model):
    """Modèle pour stocker les codes OTP"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'otp_codes'
        verbose_name = 'Code OTP'
        verbose_name_plural = 'Codes OTP'
    
    def is_valid(self):
        """Vérifier si le code est encore valide"""
        from django.utils import timezone
        return not self.used and self.expires_at > timezone.now()
    
    def mark_used(self):
        """Marquer le code comme utilisé"""
        self.used = True
        self.save()