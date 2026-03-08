import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_event(role, text):
    return SimpleNamespace(
        content=SimpleNamespace(
            role=role,
            parts=[SimpleNamespace(text=text)],
        )
    )


class FakeRunner:
    def __init__(self, **_kwargs):
        self.calls = []

    def run_async(self, *, new_message, **kwargs):
        self.calls.append({"text": new_message.parts[0].text, **kwargs})

        async def _events():
            yield make_event("assistant", f"Echo: {new_message.parts[0].text}")

        return _events()


class DelayedRunner(FakeRunner):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.active = 0
        self.max_active = 0

    def run_async(self, *, new_message, **kwargs):
        self.calls.append({"text": new_message.parts[0].text, **kwargs})

        async def _events():
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.05)
                yield make_event("assistant", f"Echo: {new_message.parts[0].text}")
            finally:
                self.active -= 1

        return _events()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp.close()

        from adhd_os.infrastructure.database import DatabaseManager
        from adhd_os.infrastructure.event_bus import EventBus
        from adhd_os.infrastructure.machines import BodyDoubleMachine, FocusTimerMachine
        from adhd_os.infrastructure.persistence import SqliteSessionService
        from adhd_os.runtime import ADHDOSRuntime
        from adhd_os.state import UserState

        self.db = DatabaseManager(db_path=self.temp.name)
        self.db_patcher = patch("adhd_os.infrastructure.database.DB", self.db)
        self.db_patcher.start()

        self.event_bus = EventBus(db=self.db)
        self.user_state = UserState(user_id="test-user")
        self.session_service = SqliteSessionService(db=self.db)
        self.body_double = BodyDoubleMachine(self.event_bus, db=self.db)
        self.focus_timer = FocusTimerMachine(self.event_bus, db=self.db)
        self.runtime = ADHDOSRuntime(
            app_name="test_app",
            user_state=self.user_state,
            db=self.db,
            event_bus=self.event_bus,
            body_double=self.body_double,
            focus_timer=self.focus_timer,
            agent=None,
            runner_factory=FakeRunner,
            session_service=self.session_service,
        )

    def tearDown(self):
        if self.body_double._active_task:
            self.body_double._active_task.cancel()
        if self.focus_timer._warning_task:
            self.focus_timer._warning_task.cancel()
        self.db_patcher.stop()
        os.unlink(self.temp.name)

    async def test_bootstrap_resumes_recent_session(self):
        session = await self.session_service.create_session(
            app_name="test_app",
            user_id="test-user",
        )
        self.db.store_conversation_message(session.id, "assistant", "chat", "Existing transcript")

        payload = await self.runtime.bootstrap()

        self.assertEqual(payload["active_session"]["id"], session.id)
        self.assertEqual(payload["messages"][0]["text"], "Existing transcript")

    async def test_bootstrap_creates_new_session_when_latest_is_stale(self):
        stale = await self.session_service.create_session(
            app_name="test_app",
            user_id="test-user",
        )
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
                ("2025-01-01T00:00:00", stale.id),
            )

        payload = await self.runtime.bootstrap()

        self.assertNotEqual(payload["active_session"]["id"], stale.id)

    async def test_crisis_messages_bypass_runner_and_persist_safety_message(self):
        session = await self.session_service.create_session(
            app_name="test_app",
            user_id="test-user",
        )

        result = await self.runtime.chat_turn("I want to die", session.id)

        self.assertEqual(len(self.runtime.runner.calls), 0)
        self.assertEqual(result["messages"][-1]["kind"], "safety")
        self.assertIn("988", result["messages"][-1]["text"])

    async def test_backfill_projects_raw_events_into_conversation_messages(self):
        session = await self.session_service.create_session(
            app_name="test_app",
            user_id="test-user",
        )
        payload = json.dumps(
            {
                "content": {
                    "role": "assistant",
                    "parts": [{"text": "Backfilled reply"}],
                }
            }
        )
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO events (session_id, type, data_json, timestamp) VALUES (?, ?, ?, ?)",
                (session.id, "adk_event", payload, "2026-03-08T12:00:00"),
            )

        await self.runtime.ensure_transcript_backfill(session.id)

        messages = self.db.get_conversation_messages(session.id)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["text"], "Backfilled reply")

    async def test_update_user_state_persists_immediately(self):
        snapshot = await self.runtime.update_user_state_data(
            energy_level=8,
            current_task="Quarterly report",
            medication_time="2026-03-08T09:30:00",
        )

        self.assertEqual(snapshot["energy_level"], 8)
        self.assertEqual(self.db.get_state("energy_level"), 8)
        self.assertEqual(self.db.get_state("current_task"), "Quarterly report")

    async def test_startup_restores_machine_state(self):
        now = datetime.now()
        self.db.save_machine_state(
            "body_double",
            {
                "state": "active",
                "task": "Draft launch email",
                "duration_minutes": 30,
                "checkin_interval": 10,
                "start_time": (now - timedelta(minutes=5)).isoformat(),
                "end_time": (now + timedelta(minutes=25)).isoformat(),
                "checkin_count": 0,
                "paused_remaining_seconds": None,
            },
        )
        self.db.save_machine_state(
            "focus_timer",
            {
                "hard_stop_time": (now + timedelta(minutes=40)).isoformat(),
                "hard_stop_reason": "School pickup",
            },
        )

        await self.runtime.startup()

        body_status = self.runtime.get_body_double_status()
        guardrail_status = self.runtime.get_focus_guardrail_status()

        self.assertEqual(body_status["state"], "active")
        self.assertEqual(body_status["task"], "Draft launch email")
        self.assertEqual(guardrail_status["state"], "active")
        self.assertEqual(guardrail_status["reason"], "School pickup")

    async def test_session_lock_serializes_concurrent_turns(self):
        from adhd_os.runtime import ADHDOSRuntime

        delayed_runtime = ADHDOSRuntime(
            app_name="test_app",
            user_state=self.user_state,
            db=self.db,
            event_bus=self.event_bus,
            body_double=self.body_double,
            focus_timer=self.focus_timer,
            agent=None,
            runner_factory=DelayedRunner,
            session_service=self.session_service,
        )
        session = await self.session_service.create_session(
            app_name="test_app",
            user_id="test-user",
        )

        await asyncio.gather(
            delayed_runtime.chat_turn("first", session.id),
            delayed_runtime.chat_turn("second", session.id),
        )

        self.assertEqual(delayed_runtime.runner.max_active, 1)
        self.assertEqual(len(self.db.get_conversation_messages(session.id)), 4)


if __name__ == "__main__":
    unittest.main()
