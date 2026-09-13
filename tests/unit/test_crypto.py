"""Тесты шифрования секретов и маскирования.

Проверяют, что ключ провайдера не хранится открыто и что маска не раскрывает
секрет.
"""
from __future__ import annotations

from personal_hub.security.crypto import get_cipher, mask_secret


def test_encrypt_decrypt_roundtrip() -> None:
    cipher = get_cipher()
    secret = "sk-test-1234567890"
    token = cipher.encrypt(secret)
    assert token != secret
    assert secret not in token
    assert cipher.decrypt(token) == secret


def test_encrypt_is_nondeterministic() -> None:
    cipher = get_cipher()
    secret = "sk-test-1234567890"
    # Fernet использует случайный IV: два шифрования не совпадают.
    assert cipher.encrypt(secret) != cipher.encrypt(secret)


def test_mask_secret_hides_most() -> None:
    assert mask_secret("sk-1234abcd") == "•••••••abcd"


def test_mask_secret_short() -> None:
    assert mask_secret("ab") == "**"
