"""Шифрование секретов провайдеров мастер-ключом.

Использует Fernet (authenticated encryption из пакета cryptography).
Мастер-ключ никогда не хранится в БД; из него выводится симметричный ключ.
Ключи провайдеров хранятся только в зашифрованном виде.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from personal_hub.config import get_settings


def _derive_key(master_key: str) -> bytes:
    """Выводит 32-байтовый ключ Fernet из мастер-ключа.

    Мастер-ключ может быть hex-строкой или произвольной строкой; для
    стабильности применяем SHA-256, а не парсинг hex.
    """
    return base64.urlsafe_b64encode(hashlib.sha256(master_key.encode()).digest())


class SecretCipher:
    """Шифрует и расшифровывает секреты провайдеров.

    Экземпляр создаётся из настроек; ключ не покидает класс.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._fernet = Fernet(_derive_key(settings.app_master_key))

    def encrypt(self, plaintext: str) -> str:
        """Шифрует секрет; возвращает строку для хранения в БД."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        """Расшифровывает секрет; бросает ValueError при повреждении.

        ValueError используется для нормализации в стабильный код ошибки,
        а не для раскрытия деталей криптографии.
        """
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("невозможно расшифровать секрет") from exc


def mask_secret(secret: str) -> str:
    """Возвращает маску секрета: видны только последние 4 символа."""
    if len(secret) <= 4:
        return "*" * len(secret)
    return "•" * (len(secret) - 4) + secret[-4:]


_cipher: SecretCipher | None = None


def get_cipher() -> SecretCipher:
    """Возвращает singleton SecretCipher на процесс."""
    global _cipher
    if _cipher is None:
        _cipher = SecretCipher()
    return _cipher
