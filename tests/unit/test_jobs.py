"""Тесты state machine задач.

Проверяют разрешённые и запрещённые переходы статусов Job.
"""
from __future__ import annotations

import pytest

from personal_hub.jobs import (
    InvalidJobTransitionError,
    JobStatus,
    assert_transition,
    can_transition,
)


def test_allowed_transitions() -> None:
    assert can_transition(JobStatus.QUEUED, JobStatus.RUNNING)
    assert can_transition(JobStatus.QUEUED, JobStatus.CANCELLED)
    assert can_transition(JobStatus.RUNNING, JobStatus.COMPLETED)
    assert can_transition(JobStatus.RUNNING, JobStatus.FAILED)
    assert can_transition(JobStatus.RUNNING, JobStatus.CANCELLED)
    assert can_transition(JobStatus.FAILED, JobStatus.QUEUED)
    assert can_transition(JobStatus.FAILED, JobStatus.RETRYABLE)
    assert can_transition(JobStatus.RETRYABLE, JobStatus.QUEUED)


def test_forbidden_transitions() -> None:
    assert not can_transition(JobStatus.COMPLETED, JobStatus.RUNNING)
    assert not can_transition(JobStatus.QUEUED, JobStatus.COMPLETED)
    assert not can_transition(JobStatus.FAILED, JobStatus.COMPLETED)
    assert not can_transition(JobStatus.CANCELLED, JobStatus.RUNNING)
    assert not can_transition(JobStatus.RUNNING, JobStatus.QUEUED)


def test_assert_transition_raises() -> None:
    with pytest.raises(InvalidJobTransitionError):
        assert_transition(JobStatus.COMPLETED, JobStatus.RUNNING)
