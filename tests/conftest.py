"""Общие фикстуры тестов.

Предоставляет локальный mock HTTP-сервер для contract-тестов провайдеров
без внешних сетевых вызовов.
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest


class _Handler(BaseHTTPRequestHandler):
    """Обработчик mock-провайдера: GET /path возвращает заданную спецификацию."""

    def do_GET(self) -> None:  # noqa: N802
        spec = getattr(self.server, "spec", {}).get(self.path)
        if spec is None:
            self.send_response(404)
            self.end_headers()
            return
        status, body = spec
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args: Any) -> None:  # noqa: D102
        pass


@pytest.fixture
def mock_provider() -> ThreadingHTTPServer:
    """Запускает mock HTTP-сервер на ephemeral-порту.

    Спецификация ответов задаётся через `server.spec = {"/path": (status, body)}`.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.spec = {}  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=1)
