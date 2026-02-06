"""Tests for BodyDoubleMachine and FocusTimerMachine state transitions."""

import asyncio
import os
import pytest
from unittest.mock import patch

from adhd_os.infrastructure.event_bus import EventBus, EventType
from adhd_os.infrastructure.machines import (
    BodyDoubleMachine,
    BodyDoubleState,
    FocusTimerMachine,
    DEMO_MODE,
)


@pytest.fixture()
def body_double():
    bus = EventBus()
    return BodyDoubleMachine(bus), bus


@pytest.fixture()
def focus_timer():
    bus = EventBus()
    return FocusTimerMachine(bus), bus


class TestBodyDoubleStateMachine:
    @pytest.mark.asyncio
    async def test_starts_idle(self, body_double):
        bd, _ = body_double
        assert bd.state == BodyDoubleState.IDLE

    @pytest.mark.asyncio
    async def test_start_session_transitions_to_active(self, body_double):
        bd, _ = body_double
        result = await bd.start_session("test task", 30, checkin_interval=10)
        assert bd.state == BodyDoubleState.ACTIVE
        assert result["status"] == "started"
        assert result["task"] == "test task"
        # Cancel background task to avoid sleep
        if bd._active_task:
            bd._active_task.cancel()

    @pytest.mark.asyncio
    async def test_double_start_returns_error(self, body_double):
        bd, _ = body_double
        await bd.start_session("task1", 30)
        result = await bd.start_session("task2", 30)
        assert result["status"] == "error"
        if bd._active_task:
            bd._active_task.cancel()

    @pytest.mark.asyncio
    async def test_pause_from_active(self, body_double):
        bd, _ = body_double
        await bd.start_session("task", 30)
        result = await bd.pause_session("need break")
        assert bd.state == BodyDoubleState.PAUSED
        assert result["status"] == "paused"

    @pytest.mark.asyncio
    async def test_pause_from_idle_returns_error(self, body_double):
        bd, _ = body_double
        result = await bd.pause_session()
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_end_session_completed(self, body_double):
        bd, _ = body_double
        await bd.start_session("task", 30)
        if bd._active_task:
            bd._active_task.cancel()
        result = await bd.end_session(completed=True)
        assert result["status"] == "completed"
        assert bd.state == BodyDoubleState.IDLE

    @pytest.mark.asyncio
    async def test_end_session_abandoned(self, body_double):
        bd, _ = body_double
        await bd.start_session("task", 30)
        if bd._active_task:
            bd._active_task.cancel()
        result = await bd.end_session(completed=False)
        assert result["status"] == "abandoned"

    @pytest.mark.asyncio
    async def test_end_from_idle_returns_error(self, body_double):
        bd, _ = body_double
        result = await bd.end_session()
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_status_idle(self, body_double):
        bd, _ = body_double
        status = bd.get_status()
        assert status["state"] == "idle"

    @pytest.mark.asyncio
    async def test_get_status_active(self, body_double):
        bd, _ = body_double
        await bd.start_session("task", 30)
        status = bd.get_status()
        assert status["state"] == "active"
        assert status["task"] == "task"
        assert "elapsed_minutes" in status
        assert "remaining_minutes" in status
        if bd._active_task:
            bd._active_task.cancel()

    @pytest.mark.asyncio
    async def test_start_publishes_event(self, body_double):
        bd, bus = body_double
        events = []
        bus.subscribe(EventType.FOCUS_BLOCK_STARTED, lambda d: events.append(d))
        await bd.start_session("task", 30)
        assert len(events) == 1
        assert events[0]["task"] == "task"
        if bd._active_task:
            bd._active_task.cancel()


class TestFocusTimerMachine:
    @pytest.mark.asyncio
    async def test_set_hard_stop(self, focus_timer):
        ft, _ = focus_timer
        result = await ft.set_hard_stop(60, "meeting at 2pm")
        assert result["status"] == "guardrail_set"
        assert ft.hard_stop_time is not None
        assert ft.hard_stop_reason == "meeting at 2pm"
        if ft._warning_task:
            ft._warning_task.cancel()

    @pytest.mark.asyncio
    async def test_clear_guardrail(self, focus_timer):
        ft, _ = focus_timer
        await ft.set_hard_stop(60, "meeting")
        if ft._warning_task:
            ft._warning_task.cancel()

        result = await ft.clear_guardrail()
        assert result["status"] == "cleared"
        assert ft.hard_stop_time is None
        assert ft.hard_stop_reason is None


class TestDemoModeFlag:
    def test_demo_mode_reads_env(self):
        """DEMO_MODE should be controlled by ADHD_OS_DEMO_MODE env var."""
        # In test env, this should be False unless explicitly set
        assert DEMO_MODE == (os.environ.get("ADHD_OS_DEMO_MODE", "0") == "1")
