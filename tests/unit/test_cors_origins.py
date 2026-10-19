"""Тесты конфигурации CORS.

Регрессия на реальный дефект: приложение открывалось по `http://127.0.0.1:3000`,
но CORS разрешал только `http://localhost:3000`, поэтому браузер блокировал
логин. Это одна и та же локальная машина, и пользователь вправе открыть любой
из адресов.
"""
from __future__ import annotations

from app.main import _cors_origins


def test_localhost_and_loopback_are_interchangeable() -> None:
    """Для localhost-адреса разрешается и loopback-алиас."""
    assert _cors_origins("http://localhost:3000") == [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]


def test_loopback_expands_to_localhost() -> None:
    """Обратное направление тоже поддержано."""
    assert _cors_origins("http://127.0.0.1:3000") == [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]


def test_external_domain_is_not_expanded() -> None:
    """Внешний домен не получает лишних origin: расширение только локальное."""
    assert _cors_origins("https://hub.example.com") == ["https://hub.example.com"]


def test_trailing_slash_is_normalized() -> None:
    """Завершающий слеш не создаёт второй, «почти такой же» origin."""
    assert _cors_origins("http://localhost:3000/") == [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]
