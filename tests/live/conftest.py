"""Инфраструктура live-тестов реального провайдера.

Назначение: сертифицировать боевой OpenAI-compatible провайдер на крошечных
запросах — health/каталог моделей, непотоковый чат с usage, streaming и
эмбеддинги. Live-тесты по умолчанию выключены и запускаются только вручную:

    RUN_LIVE_TESTS=1 LIVE_TEST_BUDGET=0.05 make test-live

Гарантии: без `RUN_LIVE_TESTS=1` все тесты каталога пропускаются; без
`LIVE_TEST_BUDGET` запуск падает с понятной ошибкой (запуск платных API без
согласованного бюджета запрещён); число платных вызовов ограничено, ключ и
секреты берутся только из окружения и никогда не логируются.

Зависимости: `personal_hub.providers` (адаптер и реестр), pytest.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import pytest
from personal_hub.costs import parse_usage
from personal_hub.providers.base import ProviderConnection, RemotePricing
from personal_hub.providers.openai_compatible import OpenAICompatibleAdapter
from personal_hub.providers.presets import PRESETS, get_preset
from personal_hub.providers.registry import get_adapter


def pytest_collection_modifyitems(config, items) -> None:
    """Пропускает live-тесты, если RUN_LIVE_TESTS != 1."""
    if os.getenv("RUN_LIVE_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="live-тесты выключены (RUN_LIVE_TESTS!=1)")
    for item in items:
        item.add_marker(skip)


class LiveBudgetExceededError(Exception):
    """Бюджет live-сессии исчерпан: следующий платный вызов запрещён."""


# Консервативная оценка стоимости вызова, если провайдер не отдал цену:
# позволяет соблюсти бюджет даже без прайса (значение заведомо с запасом
# относительно крошечных live-запросов).
_UNPRICED_CALL_RESERVE = Decimal("0.01")


@dataclass
class LiveBudget:
    """Жёсткий бюджет live-сессии: лимит USD и максимум платных вызовов."""

    limit: Decimal
    max_calls: int = 8
    spent: Decimal = Decimal("0")
    calls: int = 0

    def ensure_available(self) -> None:
        """Проверяет бюджет ДО платного вызова (иначе LiveBudgetExceededError)."""
        if self.calls >= self.max_calls:
            raise LiveBudgetExceededError(
                f"лимит платных вызовов исчерпан ({self.max_calls})"
            )
        if self.spent >= self.limit:
            raise LiveBudgetExceededError(
                f"бюджет исчерпан: потрачено {self.spent} из {self.limit} USD"
            )

    def charge(self, cost: Decimal | None) -> None:
        """Учитывает платный вызов; без цены резервирует консервативную оценку."""
        self.calls += 1
        self.spent += cost if cost is not None else _UNPRICED_CALL_RESERVE
        if self.spent > self.limit:
            raise LiveBudgetExceededError(
                f"бюджет превышен: потрачено {self.spent} из {self.limit} USD"
            )


@dataclass
class LiveProvider:
    """Настроенный провайдер live-сессии с прайсом моделей."""

    connection: ProviderConnection
    adapter: OpenAICompatibleAdapter
    chat_model: str
    embedding_model: str | None
    pricing_by_model: dict[str, RemotePricing]

    def cost(self, model: str, usage: dict | None) -> Decimal | None:
        """Считает стоимость вызова по фактическому usage и прайсу (или None)."""
        pricing = self.pricing_by_model.get(model)
        if pricing is None or not usage:
            return None
        units = parse_usage(usage)
        input_tokens = Decimal(units.get("input_tokens", 0))
        output_tokens = Decimal(units.get("output_tokens", 0))
        million = Decimal("1000000")
        return (
            input_tokens * pricing.input_per_million
            + output_tokens * pricing.output_per_million
        ) / million


@pytest.fixture(scope="session")
def live_budget() -> LiveBudget:
    """Согласованный бюджет live-сессии (USD) из LIVE_TEST_BUDGET."""
    raw = os.getenv("LIVE_TEST_BUDGET", "").strip()
    if not raw:
        pytest.fail(
            "LIVE_TEST_BUDGET не задан. Укажите бюджет в USD, "
            "например: LIVE_TEST_BUDGET=0.05 make test-live"
        )
    try:
        limit = Decimal(raw)
    except InvalidOperation:
        pytest.fail("LIVE_TEST_BUDGET должен быть числом в USD (например, 0.05)")
    if limit <= 0:
        pytest.fail("LIVE_TEST_BUDGET должен быть больше нуля")
    return LiveBudget(limit=limit)


@pytest.fixture
async def live_provider(live_budget: LiveBudget) -> LiveProvider:
    """Создаёт соединение, адаптер и подтягивает прайс моделей провайдера."""
    api_key = os.getenv("LIVE_PROVIDER_API_KEY", "").strip()
    if not api_key:
        pytest.fail(
            "LIVE_PROVIDER_API_KEY не задан: ключ берётся только из "
            "окружения/.env и никогда не логируется"
        )
    provider_type = os.getenv("LIVE_PROVIDER_TYPE", "openrouter").strip() or "openrouter"
    base_url = os.getenv("LIVE_PROVIDER_BASE_URL", "").strip()
    preset = get_preset(provider_type) or PRESETS.get(provider_type)
    if not base_url:
        base_url = preset.base_url if preset is not None else ""
    if not base_url:
        pytest.fail(
            "LIVE_PROVIDER_BASE_URL не задан, и у типа провайдера нет пресета"
        )
    chat_model = os.getenv("LIVE_CHAT_MODEL", "").strip()
    if not chat_model:
        pytest.fail("LIVE_CHAT_MODEL не задан: укажите дешёвую модель провайдера")
    embedding_model = os.getenv("LIVE_EMBEDDING_MODEL", "").strip() or None

    connection = ProviderConnection(
        provider_type=provider_type, base_url=base_url, api_key=api_key
    )
    adapter = get_adapter(provider_type)  # ValueError на неизвестный тип
    models = await adapter.list_models(connection)
    pricing_by_model = {
        m.external_id: m.pricing for m in models if m.pricing is not None
    }
    return LiveProvider(
        connection=connection,
        adapter=adapter,
        chat_model=chat_model,
        embedding_model=embedding_model,
        pricing_by_model=pricing_by_model,
    )
