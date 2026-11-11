import base64
import hashlib

from cryptography.fernet import Fernet


def _make_key(secret: str) -> bytes:
    """SECRET_KEY может быть любой строкой: если это не готовый ключ Fernet, выводим ключ из неё."""
    raw = secret.strip().encode()
    try:
        Fernet(raw)
        return raw
    except ValueError:
        return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())


class Crypto:
    def __init__(self, key: str):
        self._f = Fernet(_make_key(key))

    def encrypt(self, text: str) -> str:
        return self._f.encrypt(text.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._f.decrypt(token.encode()).decode()
