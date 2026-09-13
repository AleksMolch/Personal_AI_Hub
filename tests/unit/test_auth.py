"""Тесты паролей и JWT.

Проверяют хэширование Argon2id и подпись/проверку токенов.
"""
from __future__ import annotations

import uuid

import jwt as pyjwt
import pytest

from personal_hub.security.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_and_verify() -> None:
    hashed = hash_password("supersecret")
    assert hashed != "supersecret"
    assert verify_password("supersecret", hashed)
    assert not verify_password("wrongpassword", hashed)


def test_jwt_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    assert decode_access_token(token) == user_id


def test_jwt_invalid_token() -> None:
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_access_token("not-a-valid-token")


def test_jwt_tampered_token() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_access_token(tampered)
