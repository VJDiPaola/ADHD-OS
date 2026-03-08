import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adhd_os.dashboard import backend
from adhd_os.infrastructure.event_bus import EventType


class DashboardApiTests(unittest.TestCase):
    def test_bootstrap_endpoint_returns_runtime_payload(self):
        payload = {
            "active_session": {"id": "session-1"},
            "messages": [],
            "stats": {"current_energy": 5, "tasks_completed_today": 0, "current_multiplier": 1.5},
            "user_state": {"energy_level": 5},
            "body_double": {"state": "idle"},
            "focus_guardrail": {"state": "idle"},
            "tasks": [],
            "recent_sessions": [],
            "provider_status": {"ready": False},
            "recent_activity": [],
        }

        with patch.object(backend.RUNTIME, "startup", AsyncMock()), \
             patch.object(backend.RUNTIME, "bootstrap", AsyncMock(return_value=payload)):
            with TestClient(backend.app) as client:
                response = client.get("/api/bootstrap")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["active_session"]["id"], "session-1")

    def test_chat_turn_endpoint_passes_request_through(self):
        payload = {
            "session_id": "session-1",
            "messages": [],
            "tasks": [],
            "user_state": {"energy_level": 5},
            "body_double": {"state": "idle"},
            "focus_guardrail": {"state": "idle"},
        }

        with patch.object(backend.RUNTIME, "startup", AsyncMock()), \
             patch.object(backend.RUNTIME, "chat_turn", AsyncMock(return_value=payload)) as mock_turn:
            with TestClient(backend.app) as client:
                response = client.post("/api/chat/turn", json={"session_id": "session-1", "text": "Help me start"})

        self.assertEqual(response.status_code, 200)
        mock_turn.assert_awaited_once_with("Help me start", session_id="session-1")

    def test_provider_settings_endpoint_persists_runtime_settings(self):
        payload = {
            "google_api_key_present": True,
            "anthropic_api_key_present": True,
            "ready": True,
            "model_mode": "quality",
            "effective_model_mode": "production",
            "model_mode_restart_required": True,
        }

        with patch.object(backend.RUNTIME, "startup", AsyncMock()), \
             patch.object(backend.RUNTIME, "update_provider_settings", AsyncMock(return_value=payload)) as mock_update:
            with TestClient(backend.app) as client:
                response = client.patch(
                    "/api/settings/providers",
                    json={
                        "google_api_key": "google-test-key",
                        "anthropic_api_key": "anthropic-test-key",
                        "model_mode": "quality",
                    },
                )

        self.assertEqual(response.status_code, 200)
        mock_update.assert_awaited_once_with(
            google_api_key="google-test-key",
            anthropic_api_key="anthropic-test-key",
            model_mode="quality",
            clear_google_api_key=False,
            clear_anthropic_api_key=False,
        )

    def test_machine_endpoints_delegate_to_runtime(self):
        with patch.object(backend.RUNTIME, "startup", AsyncMock()), \
             patch.object(backend.RUNTIME, "start_body_double", AsyncMock(return_value={"state": "active"})) as mock_start, \
             patch.object(backend.RUNTIME, "resume_body_double", AsyncMock(return_value={"state": "active"})) as mock_resume, \
             patch.object(backend.RUNTIME, "set_focus_guardrail", AsyncMock(return_value={"state": "active"})) as mock_guardrail:
            with TestClient(backend.app) as client:
                start_response = client.post(
                    "/api/body-double/start",
                    json={"task": "Deep work", "duration_minutes": 30, "checkin_interval": 10},
                )
                resume_response = client.post("/api/body-double/resume")
                guardrail_response = client.post(
                    "/api/focus-guardrail",
                    json={"minutes": 45, "reason": "School pickup"},
                )

        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(resume_response.status_code, 200)
        self.assertEqual(guardrail_response.status_code, 200)
        mock_start.assert_awaited_once_with(task="Deep work", duration_minutes=30, checkin_interval=10)
        mock_resume.assert_awaited_once_with()
        mock_guardrail.assert_awaited_once_with(minutes=45, reason="School pickup")

    def test_task_endpoints_delegate_to_runtime(self):
        create_payload = {
            "task": {"id": 1, "title": "Pay rent", "status": "inbox", "steps": []},
            "tasks": [{"id": 1, "title": "Pay rent", "status": "inbox", "steps": []}],
            "stats": {"current_energy": 5, "tasks_completed_today": 0, "current_multiplier": 1.5},
            "user_state": {"energy_level": 5, "current_task": None},
        }
        update_payload = {
            "task": {"id": 1, "title": "Pay rent", "status": "doing", "steps": []},
            "tasks": [{"id": 1, "title": "Pay rent", "status": "doing", "steps": []}],
            "stats": {"current_energy": 5, "tasks_completed_today": 0, "current_multiplier": 1.5},
            "user_state": {"energy_level": 5, "current_task": "Pay rent"},
        }
        step_payload = {
            "task": {
                "id": 1,
                "title": "Pay rent",
                "status": "doing",
                "steps": [{"id": 9, "step_number": 1, "text": "Open bank app", "completed": True}],
            },
            "tasks": [{
                "id": 1,
                "title": "Pay rent",
                "status": "doing",
                "steps": [{"id": 9, "step_number": 1, "text": "Open bank app", "completed": True}],
            }],
            "stats": {"current_energy": 5, "tasks_completed_today": 0, "current_multiplier": 1.5},
            "user_state": {"energy_level": 5, "current_task": "Pay rent"},
        }
        decompose_payload = {
            "task": {
                "id": 2,
                "title": "Draft launch email",
                "status": "today",
                "steps": [{"id": 10, "step_number": 1, "text": "Open email draft", "completed": False}],
            },
            "tasks": [{"id": 2, "title": "Draft launch email", "status": "today", "steps": []}],
            "stats": {"current_energy": 5, "tasks_completed_today": 0, "current_multiplier": 1.5},
            "user_state": {"energy_level": 5, "current_task": None},
            "plan": {"task_name": "Draft launch email"},
            "used_cache": False,
        }

        with patch.object(backend.RUNTIME, "startup", AsyncMock()), \
             patch.object(backend.RUNTIME, "create_task_item", AsyncMock(return_value=create_payload)) as mock_create, \
             patch.object(backend.RUNTIME, "update_task_item", AsyncMock(return_value=update_payload)) as mock_update, \
             patch.object(backend.RUNTIME, "update_task_step_item", AsyncMock(return_value=step_payload)) as mock_step, \
             patch.object(backend.RUNTIME, "decompose_task_to_checklist", AsyncMock(return_value=decompose_payload)) as mock_decompose:
            with TestClient(backend.app) as client:
                create_response = client.post(
                    "/api/tasks",
                    json={"title": "Pay rent", "status": "inbox", "session_id": "session-1"},
                )
                update_response = client.patch(
                    "/api/tasks/1",
                    json={"status": "doing"},
                )
                step_response = client.patch(
                    "/api/tasks/1/steps/9",
                    json={"completed": True},
                )
                decompose_response = client.post(
                    "/api/tasks/decompose",
                    json={
                        "task": "Draft launch email",
                        "estimated_minutes": 45,
                        "status": "today",
                        "session_id": "session-1",
                    },
                )

        self.assertEqual(create_response.status_code, 200)
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(step_response.status_code, 200)
        self.assertEqual(decompose_response.status_code, 200)
        mock_create.assert_awaited_once_with(
            title="Pay rent",
            description=None,
            status="inbox",
            session_id="session-1",
            estimated_minutes=None,
        )
        mock_update.assert_awaited_once_with(
            1,
            title=None,
            description=None,
            status="doing",
        )
        mock_step.assert_awaited_once_with(1, 9, completed=True)
        mock_decompose.assert_awaited_once_with(
            task="Draft launch email",
            estimated_minutes=45,
            status="today",
            session_id="session-1",
        )

    def test_shutdown_endpoint_returns_runtime_messages(self):
        payload = {
            "session_id": "session-1",
            "messages": [{"id": 7, "role": "system", "kind": "system", "text": "Session saved."}],
            "tasks": [],
            "user_state": {"energy_level": 4},
            "body_double": {"state": "idle"},
            "focus_guardrail": {"state": "idle"},
        }

        with patch.object(backend.RUNTIME, "startup", AsyncMock()), \
             patch.object(backend.RUNTIME, "shutdown_session", AsyncMock(return_value=payload)):
            with TestClient(backend.app) as client:
                response = client.post("/api/sessions/session-1/shutdown")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["messages"][0]["text"], "Session saved.")

    def test_live_endpoint_streams_event_bus_updates(self):
        async def collect_chunk():
            stream = backend.live_event_stream(keepalive_seconds=60)
            next_chunk = asyncio.create_task(anext(stream))
            await asyncio.sleep(0)
            await backend.EVENT_BUS.publish(
                EventType.CHECKIN_DUE,
                {"task": "Deep work", "checkin_number": 1, "total_checkins": 3},
            )
            try:
                return await asyncio.wait_for(next_chunk, timeout=1)
            finally:
                await stream.aclose()

        chunk = asyncio.run(collect_chunk())

        self.assertIn("event: checkin_due", chunk)
        self.assertIn('"task": "Deep work"', chunk)


if __name__ == "__main__":
    unittest.main()
