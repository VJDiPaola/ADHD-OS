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
        self.original_env = {
            "GOOGLE_API_KEY": os.environ.get("GOOGLE_API_KEY"),
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY"),
            "ADHD_OS_MODEL_MODE": os.environ.get("ADHD_OS_MODEL_MODE"),
        }

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
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
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

    async def test_update_provider_settings_persists_locally(self):
        from adhd_os.infrastructure import credentials as creds_mod

        stored = {}

        def fake_store(key, value, *, db=None):
            stored[key] = value

        def fake_load(key, *, db=None):
            return stored.get(key)

        def fake_delete(key, *, db=None):
            stored.pop(key, None)

        with patch.object(creds_mod, "store_credential", side_effect=fake_store), \
             patch.object(creds_mod, "load_credential", side_effect=fake_load), \
             patch.object(creds_mod, "delete_credential", side_effect=fake_delete), \
             patch("adhd_os.runtime.store_credential", side_effect=fake_store), \
             patch("adhd_os.runtime.load_credential", side_effect=fake_load), \
             patch("adhd_os.runtime.delete_credential", side_effect=fake_delete):
            status = await self.runtime.update_provider_settings(
                google_api_key="google-test-key",
                anthropic_api_key="anthropic-test-key",
                model_mode="quality",
            )

        self.assertTrue(status["google_api_key_present"])
        self.assertTrue(status["anthropic_api_key_present"])
        self.assertEqual(status["model_mode"], "quality")
        self.assertEqual(stored.get("google_api_key"), "google-test-key")
        self.assertEqual(stored.get("anthropic_api_key"), "anthropic-test-key")
        self.assertEqual(self.db.get_app_setting("model_mode"), "quality")

    async def test_create_task_item_sets_current_task_when_doing(self):
        result = await self.runtime.create_task_item(
            title="Quarterly report",
            status="doing",
            session_id="session-1",
        )

        self.assertEqual(result["task"]["status"], "doing")
        self.assertEqual(result["user_state"]["current_task"], "Quarterly report")
        self.assertEqual(self.db.get_state("current_task"), "Quarterly report")

    async def test_moving_task_out_of_doing_clears_current_task(self):
        created = await self.runtime.create_task_item(
            title="Quarterly report",
            status="doing",
            session_id="session-1",
        )

        result = await self.runtime.update_task_item(created["task"]["id"], status="today")

        self.assertEqual(result["task"]["status"], "today")
        self.assertIsNone(result["user_state"]["current_task"])
        self.assertIsNone(self.db.get_state("current_task"))

    async def test_decompose_task_to_checklist_creates_task_with_steps(self):
        result = await self.runtime.decompose_task_to_checklist(
            task="Draft launch email",
            estimated_minutes=30,
            status="today",
            session_id="session-1",
        )

        self.assertEqual(result["task"]["title"], "Draft launch email")
        self.assertEqual(result["task"]["status"], "today")
        self.assertGreater(len(result["task"]["steps"]), 0)
        self.assertEqual(result["tasks"][0]["id"], result["task"]["id"])
        self.assertIn("stats", result)

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

    async def test_resume_body_double_reactivates_paused_session(self):
        await self.runtime.start_body_double(
            task="Draft launch email",
            duration_minutes=15,
            checkin_interval=5,
        )
        paused_status = await self.runtime.pause_body_double("Coffee refill")
        resumed_status = await self.runtime.resume_body_double()

        self.assertEqual(paused_status["state"], "paused")
        self.assertEqual(resumed_status["state"], "active")
        self.assertEqual(resumed_status["task"], "Draft launch email")

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
