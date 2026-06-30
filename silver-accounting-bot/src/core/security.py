from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class Encryptor:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt_text(self, value: str) -> str:
        token = self._fernet.encrypt(value.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt_text(self, token: str) -> str:
        try:
            value = self._fernet.decrypt(token.encode("utf-8"))
        except InvalidToken:
            raise ValueError("Invalid encrypted token")
        return value.decode("utf-8")

