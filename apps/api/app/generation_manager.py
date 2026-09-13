"""Внутрипроцессный менеджер генераций (event bus для SSE).

Хранит буфер событий и флаг отмены для потоковых генераций. Однопроцессный
MVP: состояние теряется при рестарте, но сами сообщения — в PostgreSQL.
На Этапе 2 этот механизм будет переиспользован для video jobs.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field


@dataclass
class GenerationState:
    """Состояние одной генерации: буфер событий + флаги завершения/отмены."""

    generation_id: uuid.UUID
    events: list[dict] = field(default_factory=list)
    finished: bool = False
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    condition: asyncio.Condition = field(init=False)

    def __post_init__(self) -> None:
        self.condition = asyncio.Condition()


class GenerationManager:
    """Реестр активных генераций."""

    def __init__(self) -> None:
        self._states: dict[uuid.UUID, GenerationState] = {}

    def create(self, generation_id: uuid.UUID) -> GenerationState:
        state = GenerationState(generation_id)
        self._states[generation_id] = state
        return state

    def get(self, generation_id: uuid.UUID) -> GenerationState | None:
        return self._states.get(generation_id)

    async def publish(self, state: GenerationState, event: dict) -> None:
        async with state.condition:
            state.events.append(event)
            state.condition.notify_all()

    async def finish(self, state: GenerationState) -> None:
        async with state.condition:
            state.finished = True
            state.condition.notify_all()

    def request_cancel(self, generation_id: uuid.UUID) -> bool:
        state = self._states.get(generation_id)
        if state is None or state.finished:
            return False
        state.cancel_event.set()
        return True

    def cleanup(self, generation_id: uuid.UUID) -> None:
        self._states.pop(generation_id, None)


generation_manager = GenerationManager()
