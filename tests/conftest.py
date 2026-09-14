"""Общие фикстуры тестов.

Предоставляет локальный mock HTTP-сервер для contract-тестов провайдеров.
Спецификация задаётся ключами "GET /path" или "POST /path" (для GET допустим
и просто "/path"). Значение может быть кортежем (status, body[, headers]) или
callable(method, path, body) -> (status, body[, headers]).
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest


class _Handler(BaseHTTPRequestHandler):
    """Обработчик mock-провайдера: возвращает заданную спецификацию ответа."""

    def _respond(self, method: str, body: bytes) -> None:
        spec = getattr(self.server, "spec", {})
        key = f"{method} {self.path}"
        entry = spec.get(key) if key in spec else (spec.get(self.path) if method == "GET" else None)
        if entry is None:
            self.send_response(404)
            self.end_headers()
            return
        if callable(entry):
            entry = entry(method, self.path, body)
        status, resp_body, headers = entry if len(entry) == 3 else (entry[0], entry[1], {})
        self.send_response(status)
        headers.setdefault("Content-Type", "application/json")
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(resp_body.encode())

    def do_GET(self) -> None:  # noqa: N802
        self._respond("GET", b"")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        self._respond("POST", body)

    def log_message(self, *args: Any) -> None:  # noqa: D102
        pass


@pytest.fixture
def mock_provider() -> ThreadingHTTPServer:
    """Запускает mock HTTP-сервер на ephemeral-порту."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.spec = {}  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=1)
