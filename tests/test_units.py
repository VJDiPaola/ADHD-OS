"""
Unit tests for deterministic components that don't require LLM calls.
Covers: database, event_bus, machines, state, and crisis keyword detection.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
class TestDatabaseManager(unittest.TestCase):
    """Tests for infrastructure/database.py"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        from adhd_os.infrastructure.database import DatabaseManager
        self.db = DatabaseManager(db_path=self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    # -- state ---
    def test_save_and_get_state(self):
        self.db.save_state("energy", 7)
        self.assertEqual(self.db.get_state("energy"), 7)

    def test_get_state_default(self):
        self.assertIsNone(self.db.get_state("missing"))
        self.assertEqual(self.db.get_state("missing", 42), 42)

    # -- task cache ---
    def test_cache_and_retrieve_plan(self):
        plan = {"steps": ["a", "b"]}
        import json
        self.db.cache_plan("h1", "write tests", json.dumps(plan), 5)
        result = self.db.get_cached_plan("h1")
        self.assertEqual(result, plan)

    def test_get_cached_plan_miss(self):
        self.assertIsNone(self.db.get_cached_plan("nonexistent"))

    # -- get_similar_tasks ---
    def test_get_similar_tasks_with_keywords(self):
        import json
        self.db.cache_plan("h1", "write unit tests", json.dumps({}), 5)
        self.db.cache_plan("h2", "deploy to production", json.dumps({}), 5)
        self.db.cache_plan("h3", "write integration tests", json.dumps({}), 5)

        results = self.db.get_similar_tasks(["write"])
        self.assertEqual(len(results), 2)
        self.assertIn("write unit tests", results)

    def test_get_similar_tasks_with_limit(self):
        import json
        for i in range(10):
            self.db.cache_plan(f"h{i}", f"task {i}", json.dumps({}), 5)
        results = self.db.get_similar_tasks([], limit=3)
        self.assertEqual(len(results), 3)

    # -- task history ---
    def test_log_and_get_task_history(self):
        self.db.log_task_completion("coding", 30, 45, 6, True)
        self.db.log_task_completion("coding", 20, 25, 7, False)
        history = self.db.get_recent_history(limit=10)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["type"], "coding")

    def test_get_task_multiplier_insufficient_data(self):
        self.db.log_task_completion("rare", 10, 20, 5, True)
        self.assertIsNone(self.db.get_task_multiplier("rare"))

    def test_get_task_multiplier_with_data(self):
        for _ in range(5):
            self.db.log_task_completion("coding", 10, 20, 5, True)
        mult = self.db.get_task_multiplier("coding")
        self.assertIsNotNone(mult)
        self.assertAlmostEqual(mult, 2.0)

    # -- public connection ---
    def test_get_connection(self):
        conn = self.db.get_connection()
        self.assertIsNotNone(conn)
        conn.close()


# ---------------------------------------------------------------------------
# Event Bus
# ---------------------------------------------------------------------------
class TestEventBus(unittest.TestCase):
    """Tests for infrastructure/event_bus.py"""

    def setUp(self):
        from adhd_os.infrastructure.event_bus import EventBus
        self.bus = EventBus()

    def test_subscribe_and_publish(self):
        from adhd_os.infrastructure.event_bus import EventType
        received = []

        async def handler(data):
            received.append(data)

        self.bus.subscribe(EventType.TASK_COMPLETED, handler)
        asyncio.run(self.bus.publish(EventType.TASK_COMPLETED, {"task": "test"}))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["task"], "test")

    def test_sync_handler(self):
        from adhd_os.infrastructure.event_bus import EventType
        received = []

        def handler(data):
            received.append(data)

        self.bus.subscribe(EventType.ENERGY_UPDATED, handler)
        asyncio.run(self.bus.publish(EventType.ENERGY_UPDATED, {"level": 8}))
        self.assertEqual(len(received), 1)

    def test_event_log(self):
        from adhd_os.infrastructure.event_bus import EventType
        asyncio.run(self.bus.publish(EventType.TASK_STARTED, {"a": 1}))
        asyncio.run(self.bus.publish(EventType.TASK_COMPLETED, {"b": 2}))
        events = self.bus.get_recent_events(5)
        self.assertEqual(len(events), 2)

    def test_handler_exception_does_not_propagate(self):
        from adhd_os.infrastructure.event_bus import EventType

        def bad_handler(data):
            raise ValueError("boom")

        self.bus.subscribe(EventType.ENERGY_UPDATED, bad_handler)
        # Should not raise
        asyncio.run(self.bus.publish(EventType.ENERGY_UPDATED, {"level": 1}))


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class TestUserState(unittest.TestCase):
    """Tests for state.py"""

    def setUp(self):
        from adhd_os.state import UserState
        self.state = UserState()

    def test_default_values(self):
        self.assertEqual(self.state.energy_level, 5)
        self.assertEqual(self.state.base_multiplier, 1.5)

    def test_dynamic_multiplier_low_energy(self):
        self.state.energy_level = 2
        mult = self.state.dynamic_multiplier
        self.assertGreater(mult, self.state.base_multiplier)

    def test_dynamic_multiplier_high_energy(self):
        self.state.energy_level = 9
        self.state.medication_time = datetime.now() - timedelta(hours=2)
        mult = self.state.dynamic_multiplier
        # Should be lower due to high energy + peak window
        self.assertLessEqual(mult, self.state.base_multiplier + 0.5)

    def test_peak_window_no_medication(self):
        self.assertFalse(self.state.is_in_peak_window)
        status = self.state.peak_window_status
        self.assertFalse(status["active"])
        self.assertEqual(status["reason"], "no_medication_logged")

    def test_peak_window_active(self):
        self.state.medication_time = datetime.now() - timedelta(hours=2)
        self.assertTrue(self.state.is_in_peak_window)
        status = self.state.peak_window_status
        self.assertTrue(status["active"])

    def test_peak_window_ended(self):
        self.state.medication_time = datetime.now() - timedelta(hours=10)
        self.assertFalse(self.state.is_in_peak_window)
        status = self.state.peak_window_status
        self.assertEqual(status["reason"], "ended")

    def test_save_and_load_from_db(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            from adhd_os.infrastructure.database import DatabaseManager
            db = DatabaseManager(db_path=tmp.name)
            with patch("adhd_os.infrastructure.database.DB", db):
                self.state.energy_level = 8
                self.state.base_multiplier = 2.0
                self.state.current_task = "test task"
                self.state.save_to_db()

                from adhd_os.state import UserState
                new_state = UserState()
                new_state.load_from_db()
                self.assertEqual(new_state.energy_level, 8)
                self.assertEqual(new_state.base_multiplier, 2.0)
                self.assertEqual(new_state.current_task, "test task")
        finally:
            os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Machines (BodyDouble + FocusTimer)
# ---------------------------------------------------------------------------
class TestBodyDoubleMachine(unittest.TestCase):
    """Tests for infrastructure/machines.py — BodyDoubleMachine"""

    def setUp(self):
        from adhd_os.infrastructure.event_bus import EventBus
        from adhd_os.infrastructure.machines import BodyDoubleMachine
        self.bus = EventBus()
        self.machine = BodyDoubleMachine(self.bus)

    def test_initial_state_idle(self):
        from adhd_os.infrastructure.machines import BodyDoubleState
        self.assertEqual(self.machine.state, BodyDoubleState.IDLE)

    def test_get_status_idle(self):
        status = self.machine.get_status()
        self.assertEqual(status["state"], "idle")

    def test_start_session(self):
        result = asyncio.run(self.machine.start_session("write code", 25, 5))
        self.assertEqual(result["status"], "started")
        self.assertEqual(result["task"], "write code")

        from adhd_os.infrastructure.machines import BodyDoubleState
        self.assertEqual(self.machine.state, BodyDoubleState.ACTIVE)

        # Cancel background task to avoid dangling coroutine
        if self.machine._active_task:
            self.machine._active_task.cancel()

    def test_double_start_rejected(self):
        async def run():
            await self.machine.start_session("task1", 25)
            result = await self.machine.start_session("task2", 25)
            return result
        result = asyncio.run(run())
        self.assertEqual(result["status"], "error")
        if self.machine._active_task:
            self.machine._active_task.cancel()

    def test_end_session(self):
        async def run():
            await self.machine.start_session("task", 10)
            if self.machine._active_task:
                self.machine._active_task.cancel()
            return await self.machine.end_session(completed=True)
        result = asyncio.run(run())
        self.assertEqual(result["status"], "completed")

    def test_pause_session(self):
        async def run():
            await self.machine.start_session("task", 10)
            if self.machine._active_task:
                self.machine._active_task.cancel()
            return await self.machine.pause_session("break")
        result = asyncio.run(run())
        self.assertEqual(result["status"], "paused")

    def test_end_idle_session(self):
        result = asyncio.run(self.machine.end_session())
        self.assertEqual(result["status"], "error")

    def test_pause_idle_session(self):
        result = asyncio.run(self.machine.pause_session())
        self.assertEqual(result["status"], "error")


class TestFocusTimerMachine(unittest.TestCase):
    """Tests for infrastructure/machines.py — FocusTimerMachine"""

    def setUp(self):
        from adhd_os.infrastructure.event_bus import EventBus
        from adhd_os.infrastructure.machines import FocusTimerMachine
        self.bus = EventBus()
        self.timer = FocusTimerMachine(self.bus)

    def test_set_hard_stop(self):
        result = asyncio.run(self.timer.set_hard_stop(60, "dinner"))
        self.assertEqual(result["status"], "guardrail_set")
        self.assertIsNotNone(self.timer.hard_stop_time)
        if self.timer._warning_task:
            self.timer._warning_task.cancel()

    def test_clear_guardrail(self):
        async def run():
            await self.timer.set_hard_stop(30, "meeting")
            if self.timer._warning_task:
                self.timer._warning_task.cancel()
            return await self.timer.clear_guardrail()
        result = asyncio.run(run())
        self.assertEqual(result["status"], "cleared")
        self.assertIsNone(self.timer.hard_stop_time)


# ---------------------------------------------------------------------------
# Crisis Keywords (from main.py)
# ---------------------------------------------------------------------------
class TestCrisisKeywords(unittest.TestCase):
    """Tests that crisis keyword detection works correctly."""

    CRISIS_KEYWORDS = ["suicide", "kill myself", "want to die", "end it all", "self harm"]

    def _triggers_crisis(self, text: str) -> bool:
        return any(k in text.lower() for k in self.CRISIS_KEYWORDS)

    def test_positive_matches(self):
        self.assertTrue(self._triggers_crisis("I want to kill myself"))
        self.assertTrue(self._triggers_crisis("thinking about suicide"))
        self.assertTrue(self._triggers_crisis("I want to die"))
        self.assertTrue(self._triggers_crisis("just end it all"))
        self.assertTrue(self._triggers_crisis("self harm thoughts"))

    def test_negative_matches(self):
        self.assertFalse(self._triggers_crisis("I'm stuck on my homework"))
        self.assertFalse(self._triggers_crisis("This task is killing me"))
        self.assertFalse(self._triggers_crisis("I need help with time management"))
        self.assertFalse(self._triggers_crisis(""))


if __name__ == "__main__":
    unittest.main()
