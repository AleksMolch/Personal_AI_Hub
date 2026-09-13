"""SSE-поток событий генерации и отмена.

GET /generations/{id}/events возвращает поток Server-Sent Events: сначала
буферизованные события, затем live-события до завершения. POST /cancel
останавливает генерацию.
"""
from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.deps import get_current_user, get_current_user_sse
from app.generation_manager import GenerationState, generation_manager

router = APIRouter(prefix="/api/v1/generations", tags=["generations"])

HEARTBEAT_SECONDS = 15.0


def _format_sse(event: dict) -> str:
    """Форматирует событие в SSE: строки `event:` и `data:`."""
    name = event.get("event", "message")
    return f"event: {name}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _event_stream(state: GenerationState):
    """Генератор событий: replay буфера, затем live до завершения."""
    index = 0
    while True:
        async with state.condition:
            if index < len(state.events):
                event = state.events[index]
                index += 1
                yield _format_sse(event)
                continue
            if state.finished:
                break
            try:
                await asyncio.wait_for(state.condition.wait(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                yield ": heartbeat\n\n"


@router.get("/{generation_id}/events")
async def generation_events(
    generation_id: uuid.UUID,
    _=Depends(get_current_user_sse),
) -> StreamingResponse:
    state = generation_manager.get(generation_id)
    if state is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Генерация не найдена.")
    return StreamingResponse(
        _event_stream(state),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/{generation_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_generation(
    generation_id: uuid.UUID, _=Depends(get_current_user)
) -> dict:
    cancelled = generation_manager.request_cancel(generation_id)
    if not cancelled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Генерация не найдена или завершена.")
    return {"status": "cancelling"}
