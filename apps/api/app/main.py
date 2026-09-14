"""Создание FastAPI-приложения и его жизненный цикл.

Настраивает structured logging, CORS, middleware request-id, обработчики ошибок
и подключает роутеры. При старте в production валидирует master key.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from personal_hub.budget import BudgetExceededError
from personal_hub.config import get_settings
from personal_hub.logging_setup import configure_logging, request_id_var
from personal_hub.models import User
from personal_hub.providers.errors import ProviderError
from personal_hub.security.auth import hash_password
from sqlalchemy import func, select
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.assets import router as assets_router
from app.api.auth import router as auth_router
from app.api.budgets import router as budgets_router
from app.api.conversations import router as conversations_router
from app.api.generations import router as generations_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.models import router as models_router
from app.api.prices import router as prices_router
from app.api.providers import router as providers_router
from app.api.usage import router as usage_router
from app.billing import CurrencyConversionError
from app.chat_worker import mark_interrupted_generations

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


def _error_payload(
    code: str, message: str, retryable: bool = False, details: dict | None = None
) -> dict:
    """Стабильный формат тела ошибки (см. ARCHITECTURE)."""
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id_var.get(),
            "retryable": retryable,
            "details": details or {},
        }
    }


def _error_body(
    code: str, message: str, retryable: bool = False, details: dict | None = None
) -> JSONResponse:
    """JSONResponse со стабильным форматом ошибки и статусом по коду."""
    return JSONResponse(
        status_code=_code_to_status(code),
        content=_error_payload(code, message, retryable, details),
    )


def _code_to_status(code: str) -> int:
    if code in {"PROVIDER_UNAUTHORIZED"}:
        return 401
    if code in {"PROVIDER_INSUFFICIENT_BALANCE"}:
        return 402
    if code in {"PROVIDER_FORBIDDEN"}:
        return 403
    if code in {"MODEL_NOT_FOUND"}:
        return 404
    if code in {"PROVIDER_RATE_LIMITED"}:
        return 429
    return 502


async def _bootstrap_admin_from_env() -> None:
    """Создаёт администратора из env (ADMIN_USERNAME/ADMIN_PASSWORD) при пустой БД.

    Нужен для автоматизированной установки и CI; пароль не логируется.
    """
    settings = get_settings()
    username = getattr(settings, "admin_username", "") or ""
    password = getattr(settings, "admin_password", "") or ""
    if not username or not password:
        return
    from personal_hub.db.engine import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        if count != 0:
            return
        session.add(
            User(username=username, password_hash=hash_password(password), is_admin=True)
        )
        await session.commit()
        logger.info("bootstrap_admin_env", extra={"extra_fields": {"username": username}})


def create_app() -> FastAPI:
    """Создаёт и конфигурирует экземпляр FastAPI."""
    settings = get_settings()
    configure_logging(settings.log_level, service="api")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.validate_master_key()
        await _bootstrap_admin_from_env()
        await mark_interrupted_generations()
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

    @app.exception_handler(ProviderError)
    async def _provider_error(_: Request, exc: ProviderError) -> JSONResponse:
        return _error_body(exc.code, exc.message, exc.retryable)

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
        retryable = exc.status_code in {429} or exc.status_code >= 500
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(f"HTTP_{exc.status_code}", str(exc.detail), retryable),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_payload("VALIDATION_ERROR", "Некорректные данные запроса.", False),
        )

    @app.exception_handler(BudgetExceededError)
    async def _budget_error(_: Request, exc: BudgetExceededError) -> JSONResponse:
        return JSONResponse(
            status_code=402,
            content=_error_payload(exc.code, str(exc), False, {"period": exc.period}),
        )

    @app.exception_handler(CurrencyConversionError)
    async def _fx_error(_: Request, exc: CurrencyConversionError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=_error_payload(exc.code, str(exc), False),
        )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(providers_router)
    app.include_router(models_router)
    app.include_router(conversations_router)
    app.include_router(generations_router)
    app.include_router(usage_router)
    app.include_router(budgets_router)
    app.include_router(prices_router)
    app.include_router(assets_router)
    app.include_router(jobs_router)

    return app


app = create_app()
