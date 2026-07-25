"""
✅ Encrypted File Storage for PCI-DSS Compliant KYC Document Storage

This module provides an encrypted storage backend that encrypts files at rest
using Fernet symmetric encryption (AES-128-CBC with HMAC).

Files are encrypted before being written to disk and decrypted when read.
This ensures sensitive KYC documents (ID cards, passports, selfies) are never
stored in plaintext.

Usage:
    # In your model:
    from Accounts.encrypted_storage import EncryptedFileStorage
    
    front_image = models.ImageField(
        upload_to='kyc_documents/',
        storage=EncryptedFileStorage()
    )

Security Notes:
    - Encryption key is derived from Django's SECRET_KEY
    - Never expose the SECRET_KEY in logs or error messages
    - Consider key rotation strategy for long-term deployments
"""

import base64
import hashlib
import io
from django.conf import settings
from django.core.files.base import ContentFile, File
from django.core.files.storage import FileSystemStorage
from cryptography.fernet import Fernet, InvalidToken
import structlog

logger = structlog.get_logger(__name__)


def get_fernet_key():
    """
    Derive a Fernet-compatible key from KYC_ENCRYPTION_KEY (ou SECRET_KEY).

    Fernet requires a 32-byte base64-encoded key. We derive this
    using SHA256 to ensure consistent key length.

    /!\\ IMPORTANT — cette cle dechiffre les documents d'identite deja stockes.
    La changer rend TOUS les documents existants definitivement illisibles.

    KYC_ENCRYPTION_KEY existe pour decoupler ce secret de SECRET_KEY : sans lui,
    toute rotation de SECRET_KEY (pratique de securite courante) detruirait
    silencieusement les documents KYC. Si KYC_ENCRYPTION_KEY n'est pas defini on
    retombe sur SECRET_KEY, ce qui preserve le dechiffrement des donnees deja
    ecrites avant l'introduction de cette variable.
    """
    # Use the dedicated KYC key if configured, else fall back to SECRET_KEY
    # (backward compatible with documents encrypted before this split).
    base_secret = getattr(settings, 'KYC_ENCRYPTION_KEY', None) or settings.SECRET_KEY
    secret_key = base_secret.encode('utf-8')

    # SHA256 produces 32 bytes, perfect for Fernet
    key_hash = hashlib.sha256(secret_key).digest()
    
    # Fernet expects base64-encoded key
    return base64.urlsafe_b64encode(key_hash)


class EncryptedFileStorage(FileSystemStorage):
    """
    A Django storage backend that encrypts files at rest using Fernet (AES-128).
    
    All files saved through this storage are automatically encrypted.
    All files opened through this storage are automatically decrypted.
    
    This is transparent to the application - Django's ImageField/FileField
    work normally with this storage.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fernet = None
    
    @property
    def fernet(self):
        """Lazy initialization of Fernet cipher."""
        if self._fernet is None:
            key = get_fernet_key()
            self._fernet = Fernet(key)
        return self._fernet
    
    def _save(self, name, content):
        """
        Encrypt the content before saving to disk.
        
        Args:
            name: The name of the file
            content: A File object containing the data to save
            
        Returns:
            str: The name of the saved file
        """
        try:
            # Read the original content
            if hasattr(content, 'read'):
                original_data = content.read()
                # Reset file pointer for potential re-reading
                if hasattr(content, 'seek'):
                    content.seek(0)
            else:
                original_data = content
            
            # Ensure we have bytes
            if isinstance(original_data, str):
                original_data = original_data.encode('utf-8')
            
            # Encrypt the data
            encrypted_data = self.fernet.encrypt(original_data)
            
            # Create a new ContentFile with encrypted data
            encrypted_content = ContentFile(encrypted_data)
            
            logger.debug(
                "file_encrypted_for_storage",
                filename=name,
                original_size=len(original_data),
                encrypted_size=len(encrypted_data)
            )
            
            # Save using parent's _save method
            return super()._save(name, encrypted_content)
            
        except Exception as e:
            logger.error("file_encryption_failed", filename=name, error=str(e))
            raise
    
    def _open(self, name, mode='rb'):
        """
        Decrypt the file content when opening.
        
        Args:
            name: The name of the file to open
            mode: The file mode (ignored, always reads as bytes for decryption)
            
        Returns:
            File: A File object containing the decrypted data
        """
        try:
            # Open the encrypted file from disk
            encrypted_file = super()._open(name, 'rb')
            encrypted_data = encrypted_file.read()
            encrypted_file.close()
            
            # Decrypt the data
            try:
                decrypted_data = self.fernet.decrypt(encrypted_data)
            except InvalidToken:
                # File might be unencrypted (legacy) - return as-is
                logger.warning(
                    "file_decryption_failed_returning_raw",
                    filename=name,
                    hint="File may be stored without encryption (legacy)"
                )
                return File(io.BytesIO(encrypted_data), name=name)
            
            logger.debug(
                "file_decrypted_from_storage",
                filename=name,
                decrypted_size=len(decrypted_data)
            )
            
            # Return a file-like object with decrypted content
            return File(io.BytesIO(decrypted_data), name=name)
            
        except Exception as e:
            logger.error("file_open_failed", filename=name, error=str(e))
            raise
    
    def size(self, name):
        """
        Return the actual (encrypted) size on disk.
        Note: This returns the encrypted size, not the original file size.
        """
        return super().size(name)
    
    def get_available_name(self, name, max_length=None):
        """Get an available filename, unchanged from parent behavior."""
        return super().get_available_name(name, max_length)


# Singleton instance for use in models
encrypted_kyc_storage = EncryptedFileStorage()
