import asyncio
import inspect
import json
import os
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from google.adk.runners import Runner
from google.genai import types

from adhd_os.agents.orchestrator import orchestrator
from adhd_os.config import MODEL_MODE, ModelMode
from adhd_os.infrastructure.cache import TASK_CACHE
from adhd_os.infrastructure.database import DB
from adhd_os.infrastructure.event_bus import EVENT_BUS, EventType
from adhd_os.infrastructure.machines import BODY_DOUBLE, FOCUS_TIMER
from adhd_os.infrastructure.persistence import SqliteSessionService
from adhd_os.infrastructure.settings import (
    ANTHROPIC_API_KEY_SETTING,
    GOOGLE_API_KEY_SETTING,
    MODEL_MODE_SETTING,
)
from adhd_os.models.schemas import DecompositionPlan, TaskStep
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
    TASK_STATUSES = ("inbox", "today", "doing", "done")
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
            self._load_saved_provider_environment()
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
            "tasks": self.get_task_board(),
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

    async def update_provider_settings(
        self,
        *,
        google_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
        model_mode: Optional[str] = None,
        clear_google_api_key: bool = False,
        clear_anthropic_api_key: bool = False,
    ) -> Dict[str, Any]:
        await self.startup()

        if clear_google_api_key:
            self.db.delete_app_setting(GOOGLE_API_KEY_SETTING)
            os.environ.pop("GOOGLE_API_KEY", None)
        elif google_api_key and google_api_key.strip():
            clean_google_key = google_api_key.strip()
            self.db.save_app_setting(GOOGLE_API_KEY_SETTING, clean_google_key)
            os.environ["GOOGLE_API_KEY"] = clean_google_key

        if clear_anthropic_api_key:
            self.db.delete_app_setting(ANTHROPIC_API_KEY_SETTING)
            os.environ.pop("ANTHROPIC_API_KEY", None)
        elif anthropic_api_key and anthropic_api_key.strip():
            clean_anthropic_key = anthropic_api_key.strip()
            self.db.save_app_setting(ANTHROPIC_API_KEY_SETTING, clean_anthropic_key)
            os.environ["ANTHROPIC_API_KEY"] = clean_anthropic_key

        if model_mode is not None:
            desired_mode = ModelMode(model_mode).value
            self.db.save_app_setting(MODEL_MODE_SETTING, desired_mode)
            os.environ["ADHD_OS_MODEL_MODE"] = desired_mode

        return self.get_provider_status()

    async def create_task_item(
        self,
        *,
        title: str,
        description: Optional[str] = None,
        status: str = "inbox",
        session_id: Optional[str] = None,
        estimated_minutes: Optional[int] = None,
        source: str = "manual",
        activation_phrase: Optional[str] = None,
    ) -> Dict[str, Any]:
        await self.startup()
        normalized_status = self._validate_task_status(status)
        task = self.db.create_task(
            title=title,
            description=description,
            status=normalized_status,
            source=source,
            session_id=session_id,
            estimated_minutes=estimated_minutes,
            activation_phrase=activation_phrase,
        )
        self._sync_current_task_from_status(task)
        return self._task_response(task)

    async def update_task_item(
        self,
        task_id: int,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        await self.startup()
        normalized_status = self._validate_task_status(status) if status is not None else None
        task = self.db.update_task(
            task_id,
            title=title,
            description=description,
            status=normalized_status,
        )
        if not task:
            raise ValueError(f"Unknown task: {task_id}")
        self._sync_current_task_from_status(task)
        return self._task_response(task)

    async def update_task_step_item(self, task_id: int, step_id: int, *, completed: bool) -> Dict[str, Any]:
        await self.startup()
        task = self.db.update_task_step(task_id, step_id, completed=completed)
        if not task:
            raise ValueError(f"Unknown task step: {step_id}")
        self._sync_current_task_from_status(task)
        return self._task_response(task)

    async def decompose_task_to_checklist(
        self,
        *,
        task: str,
        estimated_minutes: int,
        status: str = "today",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        await self.startup()
        normalized_status = self._validate_task_status(status)
        plan, used_cache = self._build_task_plan(task, estimated_minutes)
        created_task = self.db.create_task(
            title=plan.task_name,
            description=self._plan_description(plan),
            status=normalized_status,
            source="decomposition",
            session_id=session_id,
            estimated_minutes=plan.calibrated_estimate_minutes,
            activation_phrase=plan.activation_phrase,
        )
        self.db.create_task_steps(
            created_task["id"],
            [
                {
                    "step_number": step.step_number,
                    "text": step.action,
                    "duration_minutes": step.duration_minutes,
                    "is_checkpoint": step.is_checkpoint,
                }
                for step in plan.steps
            ],
        )
        stored_task = self.db.get_task(created_task["id"])
        self._sync_current_task_from_status(stored_task)
        response = self._task_response(stored_task)
        response.update(
            {
                "plan": plan.model_dump(),
                "used_cache": used_cache,
            }
        )
        return response

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

    def get_task_board(self) -> List[Dict[str, Any]]:
        return self.db.get_tasks()

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
        saved_settings = self.db.get_app_settings(
            [GOOGLE_API_KEY_SETTING, ANTHROPIC_API_KEY_SETTING, MODEL_MODE_SETTING]
        )
        google_present = bool(os.environ.get("GOOGLE_API_KEY") or saved_settings.get(GOOGLE_API_KEY_SETTING))
        anthropic_present = bool(os.environ.get("ANTHROPIC_API_KEY") or saved_settings.get(ANTHROPIC_API_KEY_SETTING))
        saved_model_mode = saved_settings.get(MODEL_MODE_SETTING)

        try:
            configured_model_mode = ModelMode(saved_model_mode).value if saved_model_mode else MODEL_MODE.value
        except ValueError:
            configured_model_mode = MODEL_MODE.value

        return {
            "google_api_key_present": google_present,
            "anthropic_api_key_present": anthropic_present,
            "ready": google_present and anthropic_present,
            "model_mode": configured_model_mode,
            "effective_model_mode": MODEL_MODE.value,
            "model_mode_restart_required": configured_model_mode != MODEL_MODE.value,
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
            "tasks": self.get_task_board(),
            "user_state": self.get_user_state_snapshot(),
            "body_double": self.get_body_double_status(),
            "focus_guardrail": self.get_focus_guardrail_status(),
        }

    def _task_response(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "task": task,
            "tasks": self.get_task_board(),
            "stats": self.get_stats_snapshot(),
            "user_state": self.get_user_state_snapshot(),
        }

    def _load_saved_provider_environment(self):
        google_api_key = self.db.get_app_setting(GOOGLE_API_KEY_SETTING)
        anthropic_api_key = self.db.get_app_setting(ANTHROPIC_API_KEY_SETTING)

        if google_api_key and not os.environ.get("GOOGLE_API_KEY"):
            os.environ["GOOGLE_API_KEY"] = str(google_api_key)

        if anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = str(anthropic_api_key)

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

    def _validate_task_status(self, status: str) -> str:
        clean_status = (status or "").strip().lower()
        if clean_status not in self.TASK_STATUSES:
            raise ValueError(f"Invalid task status: {status}")
        return clean_status

    def _build_task_plan(self, task: str, estimated_minutes: int) -> tuple[DecompositionPlan, bool]:
        clean_task = (task or "").strip()
        if not clean_task:
            raise ValueError("Task cannot be empty.")

        estimate = max(1, int(estimated_minutes))
        cached_plan = TASK_CACHE.get(clean_task, self.user_state.energy_level)
        if cached_plan:
            return cached_plan, True

        calibrated_estimate = max(estimate, int(round(estimate * self.user_state.dynamic_multiplier)))
        step_target = 5 if self.user_state.energy_level <= 4 else 8 if self.user_state.energy_level <= 7 else 10
        plan_steps = self._plan_template_steps(clean_task, calibrated_estimate, step_target)

        plan = DecompositionPlan(
            task_name=clean_task,
            original_estimate_minutes=estimate,
            calibrated_estimate_minutes=calibrated_estimate,
            multiplier_applied=round(float(self.user_state.dynamic_multiplier), 2),
            steps=plan_steps,
            rabbit_hole_risks=self._rabbit_hole_risks(clean_task),
            activation_phrase=f"I'm just going to {plan_steps[0].action.lower()}",
        )
        TASK_CACHE.store_with_energy(clean_task, plan, self.user_state.energy_level)
        return plan, False

    def _plan_template_steps(self, task: str, calibrated_estimate: int, chunk_minutes: int) -> List[TaskStep]:
        steps: List[TaskStep] = []
        templates = self._task_templates(task)
        setup_minutes = min(chunk_minutes, max(3, min(5, calibrated_estimate)))
        wrap_minutes = min(chunk_minutes, 5) if calibrated_estimate > 10 else 0
        focus_minutes = max(0, calibrated_estimate - setup_minutes - wrap_minutes)
        focus_chunks = max(1, int((focus_minutes + chunk_minutes - 1) // chunk_minutes)) if focus_minutes else 0

        step_number = 1
        steps.append(
            TaskStep(
                step_number=step_number,
                action=templates["setup"],
                duration_minutes=setup_minutes,
                energy_required="low",
            )
        )
        step_number += 1

        for chunk_index in range(1, focus_chunks + 1):
            chunk_duration = min(chunk_minutes, max(1, focus_minutes - ((chunk_index - 1) * chunk_minutes)))
            steps.append(
                TaskStep(
                    step_number=step_number,
                    action=templates["focus"].format(index=chunk_index),
                    duration_minutes=chunk_duration,
                    energy_required="medium",
                )
            )
            step_number += 1

            if chunk_index < focus_chunks and chunk_index % 3 == 0:
                steps.append(
                    TaskStep(
                        step_number=step_number,
                        action="Checkpoint: stand up, stretch, get water, then come back.",
                        duration_minutes=3,
                        is_checkpoint=True,
                        energy_required="low",
                    )
                )
                step_number += 1

        if wrap_minutes:
            steps.append(
                TaskStep(
                    step_number=step_number,
                    action=templates["wrap"],
                    duration_minutes=wrap_minutes,
                    energy_required="low",
                )
            )

        return steps

    def _task_templates(self, task: str) -> Dict[str, str]:
        lowered = task.lower()
        if any(keyword in lowered for keyword in ("email", "inbox", "reply", "message")):
            return {
                "setup": f"Open the inbox or thread for {task}. Star the exact message you are handling first.",
                "focus": f"Draft and send the next email chunk for {task} (chunk {{index}}).",
                "wrap": f"Send what is ready for {task}, then archive or flag the next follow-up.",
            }
        if any(keyword in lowered for keyword in ("report", "deck", "slides", "presentation", "proposal")):
            return {
                "setup": f"Open the working file for {task}. Add a rough title and the first section header.",
                "focus": f"Complete one draft section for {task} (chunk {{index}}).",
                "wrap": f"Do a quick review of {task} and leave one note about the next missing section.",
            }
        if any(keyword in lowered for keyword in ("code", "bug", "test", "refactor", "deploy")):
            return {
                "setup": f"Open the code or test related to {task}. Find the first file you need to touch.",
                "focus": f"Finish one small coding chunk for {task} (chunk {{index}}).",
                "wrap": f"Run the quickest sanity check for {task} and leave a note about the next code change.",
            }
        if any(keyword in lowered for keyword in ("clean", "laundry", "organize", "tidy")):
            return {
                "setup": f"Set a timer and clear one visible zone for {task}.",
                "focus": f"Finish one small area for {task} (zone {{index}}).",
                "wrap": f"Put obvious trash away, then stage the next area for {task}.",
            }
        return {
            "setup": f"Open everything you need for {task} and define the first concrete target.",
            "focus": f"Complete one focused work chunk for {task} (chunk {{index}}).",
            "wrap": f"Review what changed in {task} and write down the next visible step.",
        }

    def _rabbit_hole_risks(self, task: str) -> List[str]:
        lowered = task.lower()
        risks = [
            "Research spiral -> stop after one answer and return to the next step.",
            "Tool or layout tweaking -> keep the first workable version and move on.",
        ]
        if any(keyword in lowered for keyword in ("email", "inbox", "message")):
            risks.append("Inbox pinball -> finish the chosen thread before opening new messages.")
        if any(keyword in lowered for keyword in ("code", "bug", "test")):
            risks.append("Refactor drift -> only change what is required for this task.")
        return risks

    def _plan_description(self, plan: DecompositionPlan) -> str:
        return (
            f"Calibrated estimate: {plan.calibrated_estimate_minutes} minutes. "
            f"Activation phrase: {plan.activation_phrase}"
        )

    def _sync_current_task_from_status(self, task: Optional[Dict[str, Any]]):
        if not task:
            return
        if task["status"] == "doing":
            self.user_state.current_task = task["title"]
            self.user_state.save_to_db()
            return
        if self.user_state.current_task == task["title"]:
            self.user_state.current_task = None
            self.user_state.save_to_db()


RUNTIME = ADHDOSRuntime()
