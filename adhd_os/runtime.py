import asyncio
import inspect
import json
import os
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from google.adk.runners import Runner
from google.genai import types

from adhd_os.agents.orchestrator import orchestrator
from adhd_os.config import MODEL_MODE
from adhd_os.infrastructure.database import DB
from adhd_os.infrastructure.event_bus import EVENT_BUS, EventType
from adhd_os.infrastructure.machines import BODY_DOUBLE, FOCUS_TIMER
from adhd_os.infrastructure.persistence import SqliteSessionService
from adhd_os.state import USER_STATE
from adhd_os.tools.common import capture_event_loop


def _as_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).isoformat()
    text = str(value)
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        return text


class ADHDOSRuntime:
    APP_NAME = "adhd_os"
    CRISIS_KEYWORDS = [
        "suicide",
        "kill myself",
        "want to die",
        "end it all",
        "self harm",
    ]
    CRISIS_MESSAGE = (
        "It sounds like you're in a lot of pain. I'm an AI, but there are people who can help right now.\n"
        "Please reach out to:\n"
        "- 988 Suicide & Crisis Lifeline (Call/Text 988)\n"
        "- Crisis Text Line: Text HOME to 741741\n"
        "- Emergency Services: 911"
    )
    RESUME_WINDOW_SECONDS = 43200

    def __init__(
        self,
        *,
        app_name: str = APP_NAME,
        user_state=USER_STATE,
        db=DB,
        event_bus=EVENT_BUS,
        body_double=BODY_DOUBLE,
        focus_timer=FOCUS_TIMER,
        agent=orchestrator,
        runner_factory: Callable[..., Runner] = Runner,
        session_service: Optional[SqliteSessionService] = None,
    ):
        self.app_name = app_name
        self.user_state = user_state
        self.db = db
        self.event_bus = event_bus
        self.body_double = body_double
        self.focus_timer = focus_timer
        self.agent = agent
        self.runner_factory = runner_factory
        self._session_service = session_service
        self._runner: Optional[Runner] = None
        self._startup_lock = asyncio.Lock()
        self._session_locks: Dict[str, asyncio.Lock] = {}
        self._started = False

    @property
    def session_service(self) -> SqliteSessionService:
        if self._session_service is None:
            self._session_service = SqliteSessionService(db=self.db)
        return self._session_service

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            self._runner = self.runner_factory(
                agent=self.agent,
                app_name=self.app_name,
                session_service=self.session_service,
            )
        return self._runner

    async def startup(self):
        if self._started:
            return

        async with self._startup_lock:
            if self._started:
                return
            capture_event_loop()
            self.user_state.load_from_db()
            _ = self.runner
            await self.body_double.restore_state()
            await self.focus_timer.restore_state()
            self._started = True

    async def health_check(self):
        await self.startup()
        with self.db.get_connection() as conn:
            conn.execute("SELECT 1")

    async def bootstrap(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        session = await self.ensure_session(session_id)
        return {
            "active_session": self._serialize_session(session),
            "messages": self.db.get_conversation_messages(session.id),
            "stats": self.get_stats_snapshot(),
            "user_state": self.get_user_state_snapshot(),
            "body_double": self.get_body_double_status(),
            "focus_guardrail": self.get_focus_guardrail_status(),
            "recent_sessions": self.db.get_recent_sessions(),
            "provider_status": self.get_provider_status(),
            "recent_activity": self.get_recent_activity(),
        }

    async def ensure_session(self, session_id: Optional[str] = None):
        await self.startup()
        if session_id:
            session = await self.session_service.get_session(
                app_name=self.app_name,
                user_id=self.user_state.user_id,
                session_id=session_id,
            )
            if not session:
                raise ValueError(f"Unknown session: {session_id}")
        else:
            session = await self._get_or_create_active_session()

        await self.ensure_transcript_backfill(session.id)
        return session

    async def ensure_transcript_backfill(self, session_id: str):
        if self.db.conversation_message_count(session_id) > 0:
            return

        normalized: List[Dict[str, Any]] = []
        for event in self.db.get_session_event_payloads(session_id):
            text, role = self._project_event_to_message(event)
            if not text or not role:
                continue
            normalized.append(
                {
                    "session_id": session_id,
                    "role": role,
                    "kind": "chat",
                    "text": text,
                    "created_at": _as_iso(event["timestamp"]) or datetime.now().isoformat(),
                }
            )

        if normalized:
            self.db.store_conversation_messages(normalized)

    async def chat_turn(self, text: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        clean_text = (text or "").strip()
        if not clean_text:
            raise ValueError("Chat turn text cannot be empty.")

        session = await self.ensure_session(session_id)
        lock = self._get_session_lock(session.id)

        async with lock:
            user_message = self.db.store_conversation_message(
                session_id=session.id,
                role="user",
                kind="chat",
                text=clean_text,
            )

            if self._is_crisis_message(clean_text):
                safety_message = self.db.store_conversation_message(
                    session_id=session.id,
                    role="assistant",
                    kind="safety",
                    text=self.CRISIS_MESSAGE,
                )
                return self._turn_response(
                    session.id,
                    [user_message, safety_message],
                )

            assistant_texts: List[str] = []
            async for event in self._iter_runner_events(session.id, clean_text):
                text_parts = self._extract_assistant_texts(event)
                for part in text_parts:
                    if not assistant_texts or assistant_texts[-1] != part:
                        assistant_texts.append(part)

            stored_messages = [user_message]
            assistant_text = "\n\n".join(assistant_texts).strip()
            if assistant_text:
                stored_messages.append(
                    self.db.store_conversation_message(
                        session_id=session.id,
                        role="assistant",
                        kind="chat",
                        text=assistant_text,
                    )
                )

            return self._turn_response(session.id, stored_messages)

    async def shutdown_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        session = await self.ensure_session(session_id)
        lock = self._get_session_lock(session.id)

        async with lock:
            user_message = self.db.store_conversation_message(
                session_id=session.id,
                role="user",
                kind="system",
                text="shutdown",
            )

            assistant_texts: List[str] = []
            async for event in self._iter_runner_events(session.id, "shutdown"):
                text_parts = self._extract_assistant_texts(event)
                for part in text_parts:
                    if not assistant_texts or assistant_texts[-1] != part:
                        assistant_texts.append(part)

            self.user_state.save_to_db()
            await self.event_bus.publish(
                EventType.SESSION_SUMMARIZED,
                {
                    "timestamp": datetime.now().isoformat(),
                    "session_id": session.id,
                },
            )

            stored_messages = [user_message]
            assistant_text = "\n\n".join(assistant_texts).strip()
            if assistant_text:
                stored_messages.append(
                    self.db.store_conversation_message(
                        session_id=session.id,
                        role="assistant",
                        kind="chat",
                        text=assistant_text,
                    )
                )

            stored_messages.append(
                self.db.store_conversation_message(
                    session_id=session.id,
                    role="system",
                    kind="system",
                    text="Session saved. Work mode complete!",
                )
            )
            return self._turn_response(session.id, stored_messages)

    async def update_user_state_data(
        self,
        *,
        energy_level: Optional[int] = None,
        medication_time: Optional[str] = None,
        current_task: Optional[str] = None,
        mood_indicator: Optional[str] = None,
    ) -> Dict[str, Any]:
        await self.startup()
        changes = []

        if energy_level is not None:
            level = max(1, min(10, int(energy_level)))
            self.user_state.energy_level = level
            changes.append("energy_level")
            await self.event_bus.publish(EventType.ENERGY_UPDATED, {"level": level})

        if medication_time is not None:
            if medication_time == "":
                self.user_state.medication_time = None
            else:
                self.user_state.medication_time = datetime.fromisoformat(medication_time)
            changes.append("medication_time")

        if current_task is not None:
            self.user_state.current_task = current_task or None
            changes.append("current_task")

        if mood_indicator:
            self.user_state.mood_indicators.append(mood_indicator)
            changes.append("mood_indicator")

        if changes:
            self.user_state.save_to_db()

        return self.get_user_state_snapshot()

    async def start_body_double(
        self,
        *,
        task: str,
        duration_minutes: int,
        checkin_interval: int = 10,
    ) -> Dict[str, Any]:
        await self.startup()
        self.user_state.current_task = task
        self.user_state.save_to_db()
        await self.body_double.start_session(task, duration_minutes, checkin_interval)
        return self.get_body_double_status()

    async def pause_body_double(self, reason: str = "") -> Dict[str, Any]:
        await self.startup()
        await self.body_double.pause_session(reason)
        return self.get_body_double_status()

    async def resume_body_double(self) -> Dict[str, Any]:
        await self.startup()
        await self.body_double.resume_session()
        return self.get_body_double_status()

    async def end_body_double(self, completed: bool = True) -> Dict[str, Any]:
        await self.startup()
        await self.body_double.end_session(completed)
        return self.get_body_double_status()

    async def set_focus_guardrail(self, *, minutes: int, reason: str) -> Dict[str, Any]:
        await self.startup()
        await self.focus_timer.set_hard_stop(minutes, reason)
        return self.get_focus_guardrail_status()

    async def clear_focus_guardrail(self) -> Dict[str, Any]:
        await self.startup()
        await self.focus_timer.clear_guardrail()
        return self.get_focus_guardrail_status()

    def get_stats_snapshot(self) -> Dict[str, Any]:
        return {
            "current_energy": int(self.user_state.energy_level),
            "tasks_completed_today": self.db.get_tasks_completed_today(),
            "current_multiplier": float(self.user_state.dynamic_multiplier),
        }

    def get_task_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.db.get_task_history_items(limit)

    def get_user_state_snapshot(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_state.user_id,
            "energy_level": self.user_state.energy_level,
            "dynamic_multiplier": self.user_state.dynamic_multiplier,
            "base_multiplier": self.user_state.base_multiplier,
            "peak_window": self.user_state.peak_window_status,
            "current_task": self.user_state.current_task,
            "focus_block_active": self.user_state.focus_block_active,
            "mood_indicators": self.user_state.mood_indicators[-5:],
            "medication_time": _as_iso(self.user_state.medication_time),
            "time": datetime.now().strftime("%H:%M"),
        }

    def get_body_double_status(self) -> Dict[str, Any]:
        return self.body_double.get_status()

    def get_focus_guardrail_status(self) -> Dict[str, Any]:
        return self.focus_timer.get_status()

    def get_provider_status(self) -> Dict[str, Any]:
        google_present = bool(os.environ.get("GOOGLE_API_KEY"))
        anthropic_present = bool(os.environ.get("ANTHROPIC_API_KEY"))
        return {
            "google_api_key_present": google_present,
            "anthropic_api_key_present": anthropic_present,
            "ready": google_present and anthropic_present,
            "model_mode": MODEL_MODE.value,
        }

    def get_recent_activity(self, limit: int = 10) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        for row in self.db.get_recent_bus_events(limit):
            try:
                data = json.loads(row["data_json"]) if row["data_json"] else {}
            except json.JSONDecodeError:
                data = {"raw": row["data_json"]}
            events.append(
                {
                    "id": row["id"],
                    "event_type": self._public_event_name(row["event_type"]),
                    "timestamp": _as_iso(row["timestamp"]),
                    "data": data,
                }
            )
        return list(reversed(events))

    async def _get_or_create_active_session(self):
        recent = await self.session_service.list_sessions(
            app_name=self.app_name,
            user_id=self.user_state.user_id,
        )
        if recent.sessions:
            latest = recent.sessions[0]
            last_update = latest.last_update_time or 0
            if datetime.now().timestamp() - float(last_update) < self.RESUME_WINDOW_SECONDS:
                session = await self.session_service.get_session(
                    app_name=self.app_name,
                    user_id=self.user_state.user_id,
                    session_id=latest.id,
                )
                if session:
                    return session

        return await self.session_service.create_session(
            app_name=self.app_name,
            user_id=self.user_state.user_id,
        )

    async def _iter_runner_events(self, session_id: str, text: str) -> AsyncIterator[Any]:
        result = self.runner.run_async(
            user_id=self.user_state.user_id,
            session_id=session_id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=text)],
            ),
        )

        if inspect.isawaitable(result) and not hasattr(result, "__aiter__"):
            result = await result

        if hasattr(result, "__aiter__"):
            async for event in result:
                yield event
            return

        if result is None:
            return

        for event in result:
            yield event

    def _extract_assistant_texts(self, event: Any) -> List[str]:
        content = getattr(event, "content", None)
        if not content:
            return []

        role = getattr(content, "role", None)
        if role == "user":
            return []

        parts = getattr(content, "parts", None) or []
        texts = []
        for part in parts:
            text = getattr(part, "text", None)
            if text and text.strip():
                texts.append(text.strip())
        return texts

    def _project_event_to_message(self, event: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        raw_json = event.get("data_json")
        if not raw_json:
            return None, None

        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            return None, None

        content = payload.get("content") or {}
        role = content.get("role")
        parts = content.get("parts") or []
        texts = [part.get("text", "").strip() for part in parts if part.get("text")]
        text = "\n\n".join(fragment for fragment in texts if fragment).strip()
        if not text:
            return None, None
        normalized_role = "user" if role == "user" else "assistant"
        return text, normalized_role

    def _serialize_session(self, session) -> Dict[str, Any]:
        return {
            "id": session.id,
            "user_id": session.user_id,
            "app_name": session.app_name,
            "last_active": _as_iso(session.last_update_time),
        }

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    def _is_crisis_message(self, text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in self.CRISIS_KEYWORDS)

    def _turn_response(self, session_id: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "session_id": session_id,
            "messages": messages,
            "user_state": self.get_user_state_snapshot(),
            "body_double": self.get_body_double_status(),
            "focus_guardrail": self.get_focus_guardrail_status(),
        }

    def _public_event_name(self, event_type: str) -> str:
        mapping = {
            EventType.CHECKIN_DUE.value: "checkin_due",
            EventType.FOCUS_WARNING.value: "focus_warning",
            EventType.TASK_COMPLETED.value: "task_completed",
            EventType.ENERGY_UPDATED.value: "energy_updated",
            EventType.FOCUS_BLOCK_STARTED.value: "system_notice",
            EventType.FOCUS_BLOCK_ENDED.value: "system_notice",
            EventType.SESSION_SUMMARIZED.value: "system_notice",
            EventType.SYSTEM_NOTICE.value: "system_notice",
        }
        return mapping.get(event_type, "system_notice")


RUNTIME = ADHDOSRuntime()
