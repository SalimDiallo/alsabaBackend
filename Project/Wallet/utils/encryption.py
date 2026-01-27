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
    Utilise AES-256-GCM pour chiffrer les données sensibles
    """

    @staticmethod
    def encrypt_aes(plaintext: str, encryption_key: str, nonce: bytes = None) -> tuple[str, str]:
        """
        Chiffre un texte en clair avec AES-256-GCM

        Args:
            plaintext: Texte à chiffrer
            encryption_key: Clé d'encryption en base64
            nonce: Nonce de 12 bytes (généré automatiquement si None)

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
            # Si le nonce est déjà un string alpha-numérique de 12 (ASCII), on le garde tel quel
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
        Génère un nonce de 12 bytes pour AES-GCM.
        Pour Flutterwave, on génère un string alphanumérique de 12 caractères
        car ils valident la longueur du champ JSON à 12.
        """
        alphabet = string.ascii_letters + string.digits
        nonce_str = ''.join(secrets.choice(alphabet) for _ in range(12))
        return nonce_str.encode('ascii')