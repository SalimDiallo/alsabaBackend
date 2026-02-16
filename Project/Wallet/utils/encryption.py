import base64
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
import secrets
import string
import structlog

logger = structlog.get_logger(__name__)


class EncryptionUtils:
    """
    Utilitaires d'encryption pour Flutterwave
    Uses AES-256-GCM to encrypt sensitive data
    """

    @staticmethod
    def encrypt_aes(plaintext: str, encryption_key: str, nonce: bytes = None) -> tuple[str, str]:
        """
        Chiffre un texte en clair avec AES-256-GCM

        Args:
            plaintext: Text to encrypt
            encryption_key: Encryption key in base64
            nonce: 12-byte nonce (automatically generated if None)

        Returns:
            tuple: (encrypted_base64, nonce_base64)
        """
        if nonce is None:
            nonce = get_random_bytes(12)
        if len(nonce) != 12:
            raise ValueError("Nonce must be exactly 12 bytes")

        try:
            key_bytes = base64.b64decode(encryption_key)
            cipher = AES.new(key_bytes, AES.MODE_GCM, nonce=nonce)
            ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode('utf-8'))
            full_enc = ciphertext + tag
            
            # Formattage du nonce pour Flutterwave (doit être exactement 12 chars)
            # If the nonce is already a 12-character alphanumeric string (ASCII), keep it as is
            try:
                nonce_str = nonce.decode('ascii')
                if len(nonce_str) == 12:
                    return base64.b64encode(full_enc).decode('utf-8'), nonce_str
            except (UnicodeDecodeError, AttributeError):
                pass
                
            return base64.b64encode(full_enc).decode('utf-8'), base64.b64encode(nonce).decode('utf-8')
        except Exception as e:
            logger.error("encryption_error", error=str(e))
            raise

    @staticmethod
    def generate_nonce() -> bytes:
        """
        Generates a 12-byte nonce for AES-GCM.
        For Flutterwave, we generate a 12-character alphanumeric string
        because they validate the JSON field length at 12.
        """
        alphabet = string.ascii_letters + string.digits
        nonce_str = ''.join(secrets.choice(alphabet) for _ in range(12))
        return nonce_str.encode('ascii')

    @staticmethod
    def encrypt_flutterwave_v3(payload_json: str, encryption_key: str) -> str:
        """
        Chiffre le payload complet pour Flutterwave V3 direct charge (AES-128-ECB).
        
        Args:
            payload_json: JSON string du payload
            encryption_key: Encryption key (FLUTTERWAVE_ENCRYPTION_KEY)
            
        Returns:
            str: Base64 encrypted payload
        """
        from Crypto.Util.Padding import pad
        import json
        
        try:
            # 1. Data preparation (PKCS7 padding required for ECB)
            raw_data = payload_json.encode('utf-8')
            padded_data = pad(raw_data, AES.block_size)
            
            # 2. Encryption key
            key_bytes = encryption_key.encode('utf-8')
            
            # 3. Encryption AES-128-ECB
            cipher = AES.new(key_bytes, AES.MODE_ECB)
            ciphertext = cipher.encrypt(padded_data)
            
            # 4. Encodage Base64
            return base64.b64encode(ciphertext).decode('utf-8')
        except Exception as e:
            logger.error("flutterwave_v3_encryption_error", error=str(e))
            raise