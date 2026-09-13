"""Создание FastAPI-приложения и его жизненный цикл.

Настраивает structured logging, CORS, middleware request-id и подключает
роутеры. При старте в production валидирует master key.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from personal_hub.config import get_settings
from personal_hub.logging_setup import configure_logging, request_id_var
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.health import router as health_router

logger = logging.getLogger("api")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Прокидывает correlation id в логи и возвращает его в заголовке."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)


def create_app() -> FastAPI:
    """Создаёт и конфигурирует экземпляр FastAPI."""
    settings = get_settings()
    configure_logging(settings.log_level, service="api")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.validate_master_key()
        logger.info("api_started", extra={"extra_fields": {"event": "startup"}})
        yield

    app = FastAPI(
        title="Personal AI Hub API",
        version="0.1.0",
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
    )

    # CORS: разрешаем только собственный frontend, не широкий wildcard.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.app_base_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health_router)

    return app


app = create_app()
