"""Доменные типы и state machine задач (Job).

Статусная машина проверяется централизованно: запрещённые переходы вызывают
InvalidJobTransition. На Этапе 1 типы — импорт/OCR/индексация, на Этапе 2 —
видео (зарезервированы).
"""
from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    """Жизненный цикл задачи."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYABLE = "retryable"  # «мёртвая» задача, ожидающая повторного запуска


class JobType(StrEnum):
    """Типы задач. Этап 1: документы; Этап 2: видео (зарезервировано)."""

    DOCUMENT_INGEST = "document_ingest"
    DOCUMENT_DELETE = "document_delete"
    EMBEDDING = "embedding"
    EXPORT = "export"
    VIDEO_GENERATE = "video_generate"
    VIDEO_DOWNLOAD = "video_download"
    VIDEO_PROCESS = "video_process"


class InvalidJobTransitionError(Exception):
    """Запрещённый переход статуса задачи."""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"запрещённый переход задачи: {current} -> {target}")
        self.code = "INVALID_JOB_TRANSITION"


class JobCancelledError(Exception):
    """Задача была отменена (cooperative cancel) во время выполнения."""


# Разрешённые переходы. FAILED -> QUEUED (retry) и RETRYABLE -> QUEUED.
_ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.FAILED: {JobStatus.QUEUED, JobStatus.RETRYABLE},
    JobStatus.RETRYABLE: {JobStatus.QUEUED, JobStatus.CANCELLED},
    JobStatus.COMPLETED: set(),
    JobStatus.CANCELLED: set(),
}


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    """True, если переход разрешён."""
    return target in _ALLOWED_TRANSITIONS.get(current, set())


def assert_transition(current: JobStatus, target: JobStatus) -> None:
    """Проверяет переход; бросает InvalidJobTransitionError при запрете."""
    if not can_transition(current, target):
        raise InvalidJobTransitionError(current.value, target.value)
