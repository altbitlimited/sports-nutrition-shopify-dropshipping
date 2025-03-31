from cryptography.fernet import Fernet
import base64
import hashlib
from core.config import ENCRYPTION_SECRET

def _get_cipher():
    # Convert 32-byte hex to base64 key for Fernet
    key = hashlib.sha256(ENCRYPTION_SECRET.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))

def encrypt_token(token: str) -> str:
    return _get_cipher().encrypt(token.encode()).decode()

def decrypt_token(token: str) -> str:
    return _get_cipher().decrypt(token.encode()).decode()
