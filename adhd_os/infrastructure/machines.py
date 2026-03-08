import asyncio
import os
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional

from adhd_os.infrastructure import database as database_module
from adhd_os.infrastructure.event_bus import EVENT_BUS, EventBus, EventType

DEMO_MODE = os.environ.get("ADHD_OS_DEMO_MODE", "").lower() in ("1", "true", "yes")

BODY_DOUBLE_STATE_KEY = "body_double"
FOCUS_TIMER_STATE_KEY = "focus_timer"


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _minutes_from_seconds(seconds: float) -> int:
    remaining_seconds = max(0, int(seconds))
    return int((remaining_seconds + 59) // 60)


class BodyDoubleState(Enum):
    """States for the body double state machine."""

    IDLE = "idle"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETING = "completing"


class BodyDoubleMachine:
    """
    Deterministic state machine for accountability.
    No LLM calls - just predictable, low-latency check-ins.
    """

    def __init__(self, event_bus: EventBus, db=None):
        self.event_bus = event_bus
        self.db = db or database_module.DB
        self.state = BodyDoubleState.IDLE
        self.task: Optional[str] = None
        self.duration_minutes: int = 0
        self.checkin_interval: int = 10
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.checkin_count: int = 0
        self.paused_remaining_seconds: Optional[int] = None
        self._active_task: Optional[asyncio.Task] = None

    async def start_session(self, task: str, duration_minutes: int, checkin_interval: int = 10) -> Dict[str, Any]:
        """Starts a body double session."""
        if self.state != BodyDoubleState.IDLE:
            active_task = self.task or "current session"
            return {"status": "error", "message": f"Already monitoring: {active_task}"}

        duration_minutes = max(5, min(480, int(duration_minutes)))
        checkin_interval = max(1, min(duration_minutes, int(checkin_interval)))
        now = datetime.now()

        self.task = task
        self.duration_minutes = duration_minutes
        self.checkin_interval = checkin_interval
        self.start_time = now
        self.end_time = now + timedelta(minutes=duration_minutes)
        self.checkin_count = 0
        self.paused_remaining_seconds = None
        self.state = BodyDoubleState.ACTIVE
        self._persist_snapshot()

        await self.event_bus.publish(
            EventType.FOCUS_BLOCK_STARTED,
            {
                "task": task,
                "duration": duration_minutes,
                "checkin_interval": checkin_interval,
                "message": f"Body-double started for '{task}'.",
            },
        )

        self._active_task = asyncio.create_task(self._monitoring_loop())

        return {
            "status": "started",
            "task": task,
            "duration": duration_minutes,
            "checkin_interval": checkin_interval,
            "message": f"Got it. Monitoring '{task}' for {duration_minutes} minutes.",
        }

    async def restore_state(self):
        """Restores persisted machine state after process restart."""
        snapshot = self.db.get_machine_state(BODY_DOUBLE_STATE_KEY)
        if not snapshot:
            return

        try:
            state = BodyDoubleState(snapshot.get("state", BodyDoubleState.IDLE.value))
            start_time = _parse_datetime(snapshot.get("start_time"))
            end_time = _parse_datetime(snapshot.get("end_time"))
            paused_remaining_seconds = snapshot.get("paused_remaining_seconds")
            if paused_remaining_seconds is not None:
                paused_remaining_seconds = int(paused_remaining_seconds)
        except (TypeError, ValueError):
            self._reset_state(clear_snapshot=True)
            return

        self.task = snapshot.get("task")
        self.duration_minutes = int(snapshot.get("duration_minutes") or 0)
        self.checkin_interval = max(1, int(snapshot.get("checkin_interval") or 10))
        self.start_time = start_time
        self.end_time = end_time or (
            start_time + timedelta(minutes=self.duration_minutes) if start_time and self.duration_minutes else None
        )
        self.checkin_count = max(0, int(snapshot.get("checkin_count") or 0))
        self.paused_remaining_seconds = paused_remaining_seconds

        if state == BodyDoubleState.PAUSED and self.task:
            self.state = BodyDoubleState.PAUSED
            self._persist_snapshot()
            await self.event_bus.publish(
                EventType.SYSTEM_NOTICE,
                {
                    "task": self.task,
                    "state": self.state.value,
                    "message": f"Restored paused body-double session for '{self.task}'.",
                },
            )
            return

        if state != BodyDoubleState.ACTIVE or not self.task or not self.start_time or not self.end_time:
            self._reset_state(clear_snapshot=True)
            return

        if self.end_time <= datetime.now():
            self._reset_state(clear_snapshot=True)
            return

        self.state = BodyDoubleState.ACTIVE
        total_checkins = self._total_checkins()
        elapsed_seconds = max(0, (datetime.now() - self.start_time).total_seconds())
        expected_checkins = min(total_checkins, int(elapsed_seconds // (self.checkin_interval * 60)))
        self.checkin_count = max(self.checkin_count, expected_checkins)
        self._persist_snapshot()
        self._active_task = asyncio.create_task(self._monitoring_loop())

        await self.event_bus.publish(
            EventType.SYSTEM_NOTICE,
            {
                "task": self.task,
                "state": self.state.value,
                "message": f"Restored body-double session for '{self.task}'.",
            },
        )

    async def _monitoring_loop(self):
        """Background loop for check-ins."""
        current_task = asyncio.current_task()
        try:
            while self.state == BodyDoubleState.ACTIVE and self.start_time and self.end_time:
                next_checkin_time = self._next_checkin_time()
                target_time = self.end_time
                emit_checkin = False

                if next_checkin_time and next_checkin_time < self.end_time:
                    target_time = next_checkin_time
                    emit_checkin = True

                wait_seconds = max(0.0, (target_time - datetime.now()).total_seconds())
                if wait_seconds > 0:
                    await asyncio.sleep(self._sleep_seconds(wait_seconds))

                if self.state != BodyDoubleState.ACTIVE:
                    break

                if emit_checkin and self.task:
                    self.checkin_count += 1
                    self._persist_snapshot()
                    await self.event_bus.publish(
                        EventType.CHECKIN_DUE,
                        {
                            "task": self.task,
                            "checkin_number": self.checkin_count,
                            "total_checkins": self._total_checkins(),
                            "message": self._checkin_message(),
                        },
                    )
                    continue

                break

            if self.state == BodyDoubleState.ACTIVE:
                await self._complete_session()
        except asyncio.CancelledError:
            raise
        finally:
            if self._active_task is current_task:
                self._active_task = None

    async def _complete_session(self):
        """Handles session completion."""
        if not self.task:
            self._reset_state(clear_snapshot=True)
            return

        self.state = BodyDoubleState.COMPLETING
        task = self.task
        duration = self.duration_minutes
        checkins = self.checkin_count

        await self.event_bus.publish(
            EventType.FOCUS_BLOCK_ENDED,
            {
                "task": task,
                "duration": duration,
                "checkins_completed": checkins,
                "status": "completed",
                "message": f"Body-double complete for '{task}'.",
            },
        )

        self._reset_state(clear_snapshot=True)

    async def pause_session(self, reason: str = "") -> Dict[str, Any]:
        """Pauses the current session."""
        if self.state != BodyDoubleState.ACTIVE:
            return {"status": "error", "message": "No active session to pause"}

        self._cancel_active_task()
        self.state = BodyDoubleState.PAUSED
        self.paused_remaining_seconds = max(
            0,
            int((self.end_time - datetime.now()).total_seconds()) if self.end_time else 0,
        )
        self._persist_snapshot()

        await self.event_bus.publish(
            EventType.SYSTEM_NOTICE,
            {
                "task": self.task,
                "reason": reason,
                "state": self.state.value,
                "message": f"Paused body-double session for '{self.task}'.",
            },
        )

        return {
            "status": "paused",
            "task": self.task,
            "reason": reason,
            "message": f"Paused '{self.task}'.",
        }

    async def end_session(self, completed: bool = True) -> Dict[str, Any]:
        """Ends the current session."""
        if self.state == BodyDoubleState.IDLE:
            return {"status": "error", "message": "No active session"}

        self._cancel_active_task()
        task = self.task
        checkins = self.checkin_count
        status = "completed" if completed else "abandoned"

        await self.event_bus.publish(
            EventType.FOCUS_BLOCK_ENDED,
            {
                "task": task,
                "status": status,
                "checkins_completed": checkins,
                "message": f"Body-double session {status} for '{task}'.",
            },
        )

        result = {
            "status": status,
            "task": task,
            "checkins_completed": checkins,
            "message": "Nice work!" if completed else "Session ended.",
        }

        self._reset_state(clear_snapshot=True)
        return result

    def get_status(self) -> Dict[str, Any]:
        """Returns current status."""
        if self.state == BodyDoubleState.IDLE:
            return {"state": "idle", "message": "No active session"}

        remaining_seconds = 0
        if self.state == BodyDoubleState.PAUSED:
            remaining_seconds = float(self.paused_remaining_seconds or 0)
        elif self.end_time:
            remaining_seconds = max(0.0, (self.end_time - datetime.now()).total_seconds())

        if self.start_time and self.state == BodyDoubleState.PAUSED:
            total_seconds = max(0, self.duration_minutes * 60)
            elapsed_seconds = max(0, total_seconds - int(self.paused_remaining_seconds or 0))
        elif self.start_time:
            elapsed_seconds = max(0, int((datetime.now() - self.start_time).total_seconds()))
        else:
            elapsed_seconds = 0

        return {
            "state": self.state.value,
            "task": self.task,
            "duration_minutes": self.duration_minutes,
            "checkin_interval": self.checkin_interval,
            "elapsed_minutes": int(elapsed_seconds // 60),
            "remaining_minutes": _minutes_from_seconds(remaining_seconds),
            "checkins_completed": self.checkin_count,
        }

    def _checkin_message(self) -> str:
        total_checkins = max(1, self._total_checkins())
        messages = [
            f"Check-in {self.checkin_count}/{total_checkins}: still on '{self.task}'?",
            f"{self.checkin_interval * self.checkin_count} minutes in. How's '{self.task}' going?",
            f"Checkpoint reached. Take a breath, then back to '{self.task}'.",
        ]
        return messages[(self.checkin_count - 1) % len(messages)]

    def _cancel_active_task(self):
        if self._active_task:
            self._active_task.cancel()
            self._active_task = None

    def _next_checkin_time(self) -> Optional[datetime]:
        if not self.start_time or self.checkin_interval <= 0:
            return None
        next_checkin_number = self.checkin_count + 1
        if next_checkin_number > self._total_checkins():
            return None
        return self.start_time + timedelta(minutes=self.checkin_interval * next_checkin_number)

    def _persist_snapshot(self):
        if self.state == BodyDoubleState.IDLE:
            self.db.clear_machine_state(BODY_DOUBLE_STATE_KEY)
            return

        self.db.save_machine_state(
            BODY_DOUBLE_STATE_KEY,
            {
                "state": self.state.value,
                "task": self.task,
                "duration_minutes": self.duration_minutes,
                "checkin_interval": self.checkin_interval,
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "end_time": self.end_time.isoformat() if self.end_time else None,
                "checkin_count": self.checkin_count,
                "paused_remaining_seconds": self.paused_remaining_seconds,
            },
        )

    def _reset_state(self, *, clear_snapshot: bool):
        self.state = BodyDoubleState.IDLE
        self.task = None
        self.duration_minutes = 0
        self.checkin_interval = 10
        self.start_time = None
        self.end_time = None
        self.checkin_count = 0
        self.paused_remaining_seconds = None
        if clear_snapshot:
            self.db.clear_machine_state(BODY_DOUBLE_STATE_KEY)

    def _sleep_seconds(self, real_seconds: float) -> float:
        if not DEMO_MODE:
            return real_seconds
        return max(0.5, real_seconds / 200)

    def _total_checkins(self) -> int:
        if self.duration_minutes <= 0 or self.checkin_interval <= 0:
            return 0
        return max(0, (self.duration_minutes - 1) // self.checkin_interval)


class FocusTimerMachine:
    """Deterministic focus timer with hyperfocus guardrails."""

    def __init__(self, event_bus: EventBus, db=None):
        self.event_bus = event_bus
        self.db = db or database_module.DB
        self.hard_stop_time: Optional[datetime] = None
        self.hard_stop_reason: Optional[str] = None
        self._warning_task: Optional[asyncio.Task] = None

    async def set_hard_stop(self, minutes: int, reason: str) -> Dict[str, Any]:
        """Sets a hard stop guardrail for hyperfocus protection."""
        minutes = max(5, min(480, int(minutes)))
        self._cancel_warning_task()

        self.hard_stop_time = datetime.now() + timedelta(minutes=minutes)
        self.hard_stop_reason = reason
        self._persist_snapshot()
        self._warning_task = asyncio.create_task(self._warning_loop())

        await self.event_bus.publish(
            EventType.SYSTEM_NOTICE,
            {
                "reason": reason,
                "hard_stop_time": self.hard_stop_time.isoformat(),
                "message": f"Hard stop set for {self.hard_stop_time.strftime('%H:%M')} ({reason}).",
            },
        )

        return {
            "status": "guardrail_set",
            "hard_stop": self.hard_stop_time.strftime("%H:%M"),
            "reason": reason,
            "message": f"Hard stop set for {self.hard_stop_time.strftime('%H:%M')} ({reason}).",
        }

    async def restore_state(self):
        """Restores a persisted hard stop after process restart."""
        snapshot = self.db.get_machine_state(FOCUS_TIMER_STATE_KEY)
        if not snapshot:
            return

        try:
            hard_stop_time = _parse_datetime(snapshot.get("hard_stop_time"))
        except (TypeError, ValueError):
            self._reset_state(clear_snapshot=True)
            return

        if not hard_stop_time or hard_stop_time <= datetime.now():
            self._reset_state(clear_snapshot=True)
            return

        self.hard_stop_time = hard_stop_time
        self.hard_stop_reason = snapshot.get("hard_stop_reason")
        self._persist_snapshot()
        self._warning_task = asyncio.create_task(self._warning_loop())

        await self.event_bus.publish(
            EventType.SYSTEM_NOTICE,
            {
                "reason": self.hard_stop_reason,
                "hard_stop_time": self.hard_stop_time.isoformat(),
                "message": f"Restored hard stop for {self.hard_stop_time.strftime('%H:%M')} ({self.hard_stop_reason}).",
            },
        )

    async def _warning_loop(self):
        """Issues warnings before hard stop."""
        current_task = asyncio.current_task()
        warnings = [
            (30, "30 minutes until hard stop."),
            (10, "10 minutes until hard stop."),
            (5, "5 minutes until hard stop. Start wrapping up now."),
            (0, "Hard stop reached. Save your work and step away."),
        ]

        try:
            for minutes_until_stop, message in warnings:
                if not self.hard_stop_time:
                    return

                target_time = self.hard_stop_time - timedelta(minutes=minutes_until_stop)
                wait_seconds = max(0.0, (target_time - datetime.now()).total_seconds())
                if wait_seconds <= 0:
                    continue

                await asyncio.sleep(self._sleep_seconds(wait_seconds))

                if not self.hard_stop_time:
                    return

                await self.event_bus.publish(
                    EventType.FOCUS_WARNING,
                    {
                        "message": message,
                        "minutes_until_stop": minutes_until_stop,
                        "hard_stop_time": self.hard_stop_time.isoformat(),
                        "reason": self.hard_stop_reason,
                    },
                )

            self._reset_state(clear_snapshot=True)
        except asyncio.CancelledError:
            raise
        finally:
            if self._warning_task is current_task:
                self._warning_task = None

    async def clear_guardrail(self) -> Dict[str, Any]:
        """Clears the hard stop guardrail."""
        self._cancel_warning_task()
        self._reset_state(clear_snapshot=True)

        await self.event_bus.publish(
            EventType.SYSTEM_NOTICE,
            {
                "message": "Guardrail cleared.",
            },
        )

        return {"status": "cleared", "message": "Guardrail cleared."}

    def get_status(self) -> Dict[str, Any]:
        """Returns the current guardrail status."""
        if not self.hard_stop_time:
            return {"state": "idle", "message": "No active hard stop"}

        remaining_seconds = max(0.0, (self.hard_stop_time - datetime.now()).total_seconds())
        return {
            "state": "active",
            "hard_stop_time": self.hard_stop_time.isoformat(),
            "reason": self.hard_stop_reason,
            "remaining_minutes": _minutes_from_seconds(remaining_seconds),
        }

    def _cancel_warning_task(self):
        if self._warning_task:
            self._warning_task.cancel()
            self._warning_task = None

    def _persist_snapshot(self):
        if not self.hard_stop_time:
            self.db.clear_machine_state(FOCUS_TIMER_STATE_KEY)
            return

        self.db.save_machine_state(
            FOCUS_TIMER_STATE_KEY,
            {
                "hard_stop_time": self.hard_stop_time.isoformat(),
                "hard_stop_reason": self.hard_stop_reason,
            },
        )

    def _reset_state(self, *, clear_snapshot: bool):
        self.hard_stop_time = None
        self.hard_stop_reason = None
        if clear_snapshot:
            self.db.clear_machine_state(FOCUS_TIMER_STATE_KEY)

    def _sleep_seconds(self, real_seconds: float) -> float:
        if not DEMO_MODE:
            return real_seconds
        return max(0.5, real_seconds / 600)


BODY_DOUBLE = BodyDoubleMachine(EVENT_BUS)
FOCUS_TIMER = FocusTimerMachine(EVENT_BUS)
