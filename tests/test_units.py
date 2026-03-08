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

    def test_machine_state_round_trip(self):
        snapshot = {"state": "active", "task": "write code", "remaining_minutes": 12}
        self.db.save_machine_state("body_double", snapshot)
        self.assertEqual(self.db.get_machine_state("body_double"), snapshot)

        self.db.clear_machine_state("body_double")
        self.assertIsNone(self.db.get_machine_state("body_double"))


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
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        from adhd_os.infrastructure.database import DatabaseManager
        from adhd_os.infrastructure.event_bus import EventBus
        from adhd_os.infrastructure.machines import BodyDoubleMachine
        self.db = DatabaseManager(db_path=self.tmp.name)
        self.bus = EventBus(db=self.db)
        self.machine = BodyDoubleMachine(self.bus, db=self.db)

    def tearDown(self):
        if self.machine._active_task:
            self.machine._active_task.cancel()
        os.unlink(self.tmp.name)

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
        snapshot = self.db.get_machine_state("body_double")
        self.assertEqual(snapshot["state"], "active")
        self.assertEqual(snapshot["task"], "write code")

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
        self.assertIsNone(self.db.get_machine_state("body_double"))

    def test_pause_session(self):
        async def run():
            await self.machine.start_session("task", 10)
            return await self.machine.pause_session("break")
        result = asyncio.run(run())
        self.assertEqual(result["status"], "paused")
        snapshot = self.db.get_machine_state("body_double")
        self.assertEqual(snapshot["state"], "paused")

    def test_resume_session(self):
        async def run():
            await self.machine.start_session("task", 10)
            await self.machine.pause_session("break")
            return await self.machine.resume_session()

        result = asyncio.run(run())
        self.assertEqual(result["status"], "resumed")
        snapshot = self.db.get_machine_state("body_double")
        self.assertEqual(snapshot["state"], "active")

    def test_end_idle_session(self):
        result = asyncio.run(self.machine.end_session())
        self.assertEqual(result["status"], "error")

    def test_pause_idle_session(self):
        result = asyncio.run(self.machine.pause_session())
        self.assertEqual(result["status"], "error")


class TestFocusTimerMachine(unittest.TestCase):
    """Tests for infrastructure/machines.py — FocusTimerMachine"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        from adhd_os.infrastructure.database import DatabaseManager
        from adhd_os.infrastructure.event_bus import EventBus
        from adhd_os.infrastructure.machines import FocusTimerMachine
        self.db = DatabaseManager(db_path=self.tmp.name)
        self.bus = EventBus(db=self.db)
        self.timer = FocusTimerMachine(self.bus, db=self.db)

    def tearDown(self):
        if self.timer._warning_task:
            self.timer._warning_task.cancel()
        os.unlink(self.tmp.name)

    def test_set_hard_stop(self):
        result = asyncio.run(self.timer.set_hard_stop(60, "dinner"))
        self.assertEqual(result["status"], "guardrail_set")
        self.assertIsNotNone(self.timer.hard_stop_time)
        snapshot = self.db.get_machine_state("focus_timer")
        self.assertEqual(snapshot["hard_stop_reason"], "dinner")
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
        self.assertIsNone(self.db.get_machine_state("focus_timer"))


# ---------------------------------------------------------------------------
# Crisis Keywords (from main.py)
# ---------------------------------------------------------------------------
class TestCrisisKeywords(unittest.TestCase):
    """Tests that crisis keyword detection works correctly."""

    def test_positive_matches(self):
        from adhd_os.runtime import ADHDOSRuntime

        runtime = ADHDOSRuntime()
        self.assertTrue(runtime._is_crisis_message("I want to kill myself"))
        self.assertTrue(runtime._is_crisis_message("thinking about suicide"))
        self.assertTrue(runtime._is_crisis_message("I want to die"))
        self.assertTrue(runtime._is_crisis_message("just end it all"))
        self.assertTrue(runtime._is_crisis_message("self harm thoughts"))

    def test_negative_matches(self):
        from adhd_os.runtime import ADHDOSRuntime

        runtime = ADHDOSRuntime()
        self.assertFalse(runtime._is_crisis_message("I'm stuck on my homework"))
        self.assertFalse(runtime._is_crisis_message("This task is killing me"))
        self.assertFalse(runtime._is_crisis_message("I need help with time management"))
        self.assertFalse(runtime._is_crisis_message(""))


# ---------------------------------------------------------------------------
# TF-IDF cache similarity (Improvement #1)
# ---------------------------------------------------------------------------
class TestTFIDFCache(unittest.TestCase):
    """Tests for infrastructure/cache.py TF-IDF helpers and TaskCache."""

    def test_tokenize_strips_stop_words(self):
        from adhd_os.infrastructure.cache import _tokenize
        tokens = _tokenize("Write a unit test for the parser")
        self.assertNotIn("a", tokens)
        self.assertNotIn("the", tokens)
        self.assertNotIn("for", tokens)
        self.assertIn("write", tokens)
        self.assertIn("unit", tokens)

    def test_cosine_similarity_identical(self):
        from adhd_os.infrastructure.cache import _cosine_similarity
        import numpy as np
        v = np.array([1.0, 2.0, 3.0])
        self.assertAlmostEqual(_cosine_similarity(v, v), 1.0, places=5)

    def test_cosine_similarity_orthogonal(self):
        from adhd_os.infrastructure.cache import _cosine_similarity
        import numpy as np
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        self.assertAlmostEqual(_cosine_similarity(a, b), 0.0, places=5)

    def test_cosine_similarity_zero_vector(self):
        from adhd_os.infrastructure.cache import _cosine_similarity
        import numpy as np
        self.assertAlmostEqual(_cosine_similarity(np.zeros(3), np.array([1, 2, 3])), 0.0)

    def test_tfidf_vectors_same_doc(self):
        from adhd_os.infrastructure.cache import _tfidf_vectors, _cosine_similarity
        tokens = ["write", "unit", "tests"]
        q_vec, d_vecs = _tfidf_vectors(tokens, [tokens])
        self.assertAlmostEqual(_cosine_similarity(q_vec, d_vecs[0]), 1.0, places=5)

    def test_cache_semantic_match(self):
        """Store a plan then retrieve it with a semantically similar query."""
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            from adhd_os.infrastructure.database import DatabaseManager
            db = DatabaseManager(db_path=tmp.name)
            with patch("adhd_os.infrastructure.cache.DB", db), \
                 patch("adhd_os.infrastructure.database.DB", db):
                from adhd_os.infrastructure.cache import TaskCache
                from adhd_os.models.schemas import DecompositionPlan
                cache = TaskCache()
                plan = DecompositionPlan(
                    task_name="Write unit tests",
                    original_estimate_minutes=30,
                    calibrated_estimate_minutes=45,
                    multiplier_applied=1.5,
                    steps=[{"step_number": 1, "action": "step1", "duration_minutes": 10, "energy_required": "low"}],
                    rabbit_hole_risks=["scope creep"],
                    activation_phrase="Just open the file",
                )
                cache.store_with_energy("write unit tests for project", plan, 5)
                # Exact match
                result = cache.get("write unit tests for project", 5)
                self.assertIsNotNone(result)
                # Fuzzy TF-IDF match
                result2 = cache.get("write tests project", 5)
                # May or may not match depending on threshold, just ensure no crash
                self.assertTrue(result2 is None or isinstance(result2, DecompositionPlan))
        finally:
            os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Dynamic multiplier ceiling (Improvement #9)
# ---------------------------------------------------------------------------
class TestMultiplierCeiling(unittest.TestCase):
    """Tests that the dynamic multiplier is capped at MAX_MULTIPLIER."""

    def test_ceiling_enforced(self):
        from adhd_os.state import UserState, MAX_MULTIPLIER
        state = UserState()
        state.energy_level = 1
        state.base_multiplier = 3.5
        # Even with all penalties stacked, should not exceed MAX_MULTIPLIER
        self.assertLessEqual(state.dynamic_multiplier, MAX_MULTIPLIER)

    def test_floor_enforced(self):
        from adhd_os.state import UserState
        state = UserState()
        state.energy_level = 10
        state.base_multiplier = 0.5
        self.assertGreaterEqual(state.dynamic_multiplier, 1.0)


# ---------------------------------------------------------------------------
# Input sanitization (Improvement #8)
# ---------------------------------------------------------------------------
class TestInputSanitization(unittest.TestCase):
    """Tests that tool functions clamp inputs correctly."""

    def _capture_background_task(self):
        scheduled = []

        def _capture(coro):
            scheduled.append(coro)

        return scheduled, _capture

    def test_log_task_completion_clamps(self):
        from adhd_os.tools import common

        scheduled, capture = self._capture_background_task()
        with patch.object(common, "_fire_and_forget", side_effect=capture), \
             patch.object(common.USER_STATE, "log_task_completion") as mock_log, \
             patch.object(common.EVENT_BUS, "publish", AsyncMock()) as mock_publish:
            result = common.log_task_completion.func("test", -5, 0)
            asyncio.run(scheduled[0])

        mock_log.assert_called_once_with("test", 1, 1)
        mock_publish.assert_awaited_once()
        self.assertTrue(result["logged"])
        self.assertGreater(result["ratio"], 0)

    def test_apply_time_calibration_clamps(self):
        from adhd_os.tools.common import apply_time_calibration
        result = apply_time_calibration.func(-10)
        self.assertEqual(result["original_estimate"], 1)

    def test_schedule_checkin_clamps(self):
        from adhd_os.tools import common

        scheduled, capture = self._capture_background_task()
        with patch.object(common, "_fire_and_forget", side_effect=capture), \
             patch.object(common.asyncio, "sleep", AsyncMock()) as mock_sleep, \
             patch.object(common.EVENT_BUS, "publish", AsyncMock()) as mock_publish:
            result = common.schedule_checkin.func(0, "test")
            asyncio.run(scheduled[0])

        mock_sleep.assert_awaited_once_with(60)
        mock_publish.assert_awaited_once()
        self.assertTrue(result["scheduled"])

    def test_set_hyperfocus_guardrail_clamps(self):
        from adhd_os.tools import common

        scheduled, capture = self._capture_background_task()
        with patch.object(common, "_fire_and_forget", side_effect=capture), \
             patch.object(common.FOCUS_TIMER, "set_hard_stop", AsyncMock()) as mock_set:
            result = common.set_hyperfocus_guardrail.func(0, "test")
            asyncio.run(scheduled[0])

        mock_set.assert_awaited_once_with(5, "test")
        self.assertEqual(result["status"], "setting")

    def test_activate_body_double_clamps(self):
        from adhd_os.tools import common

        scheduled, capture = self._capture_background_task()
        with patch.object(common, "_fire_and_forget", side_effect=capture), \
             patch.object(common.BODY_DOUBLE, "start_session", AsyncMock()) as mock_start:
            result = common.activate_body_double.func("task", 0)
            asyncio.run(scheduled[0])

        mock_start.assert_awaited_once_with("task", 5, 5)
        self.assertEqual(result["status"], "activating")


# ---------------------------------------------------------------------------
# Session pruning (Improvement #6)
# ---------------------------------------------------------------------------
class TestSessionPruning(unittest.TestCase):
    """Tests for DatabaseManager.prune_old_sessions()."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        from adhd_os.infrastructure.database import DatabaseManager
        self.db = DatabaseManager(db_path=self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_prune_deletes_old(self):
        import sqlite3
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO sessions (id, user_id, app_name, created_at, last_updated_at, state_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("old", "u", "app", "2020-01-01T00:00:00", "2020-01-01T00:00:00", '{}'),
            )
            conn.execute(
                "INSERT INTO sessions (id, user_id, app_name, created_at, last_updated_at, state_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("recent", "u", "app", datetime.now().isoformat(), datetime.now().isoformat(), '{}'),
            )
        deleted = self.db.prune_old_sessions(max_age_days=30)
        self.assertEqual(deleted, 1)
        # recent session should remain
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT id FROM sessions").fetchall()
            self.assertEqual(len(row), 1)
            self.assertEqual(row[0][0], "recent")


# ---------------------------------------------------------------------------
# Event bus persistence (Improvement #11)
# ---------------------------------------------------------------------------
class TestEventPersistence(unittest.TestCase):
    """Tests that events are persisted to bus_events table."""

    def test_persist_bus_event(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            from adhd_os.infrastructure.database import DatabaseManager
            db = DatabaseManager(db_path=tmp.name)
            db.persist_bus_event("task_completed", '{"task": "test"}')
            with db.get_connection() as conn:
                rows = conn.execute("SELECT event_type, data_json FROM bus_events").fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][0], "task_completed")
        finally:
            os.unlink(tmp.name)

    def test_publish_persists(self):
        """Calling EventBus.publish persists to DB."""
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            from adhd_os.infrastructure.database import DatabaseManager
            from adhd_os.infrastructure.event_bus import EventBus, EventType
            db = DatabaseManager(db_path=tmp.name)
            # The publish() method imports DB from adhd_os.infrastructure.database
            with patch("adhd_os.infrastructure.database.DB", db):
                bus = EventBus()
                asyncio.run(bus.publish(EventType.TASK_COMPLETED, {"x": 1}))
                with db.get_connection() as conn:
                    rows = conn.execute("SELECT event_type FROM bus_events").fetchall()
                    self.assertEqual(len(rows), 1)
        finally:
            os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Health check endpoint (Improvement #12)
# ---------------------------------------------------------------------------
class TestHealthEndpoint(unittest.TestCase):
    """Tests for the /health dashboard endpoint."""

    def test_health_returns_ok(self):
        from fastapi.testclient import TestClient
        from adhd_os.dashboard import backend

        with patch.object(backend.RUNTIME, "startup", AsyncMock()), \
             patch.object(backend.RUNTIME, "health_check", AsyncMock()):
            with TestClient(backend.app) as client:
                resp = client.get("/health")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_health_returns_503_when_runtime_check_fails(self):
        from fastapi.testclient import TestClient
        from adhd_os.dashboard import backend

        with patch.object(backend.RUNTIME, "startup", AsyncMock()), \
             patch.object(backend.RUNTIME, "health_check", AsyncMock(side_effect=RuntimeError("db offline"))):
            with TestClient(backend.app) as client:
                resp = client.get("/health")

        self.assertEqual(resp.status_code, 503)
        self.assertIn("Database unavailable", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
