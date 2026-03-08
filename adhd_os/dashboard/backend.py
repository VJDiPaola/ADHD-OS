import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from adhd_os.infrastructure.event_bus import EVENT_BUS, EventType
from adhd_os.runtime import RUNTIME


@asynccontextmanager
async def lifespan(_: FastAPI):
    await RUNTIME.startup()
    yield


app = FastAPI(title="ADHD-OS Dashboard API", lifespan=lifespan)

_cors_origins_raw = os.environ.get("ADHD_OS_CORS_ORIGINS", "http://localhost:5173")
CORS_ORIGINS = [origin.strip() for origin in _cors_origins_raw.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatTurnRequest(BaseModel):
    session_id: Optional[str] = None
    text: str = Field(..., min_length=1)


class UserStatePatchRequest(BaseModel):
    energy_level: Optional[int] = None
    medication_time: Optional[str] = None
    current_task: Optional[str] = None
    mood_indicator: Optional[str] = None


class BodyDoubleStartRequest(BaseModel):
    task: str = Field(..., min_length=1)
    duration_minutes: int = Field(..., ge=5, le=480)
    checkin_interval: int = Field(10, ge=1, le=480)


class BodyDoublePauseRequest(BaseModel):
    reason: str = ""


class BodyDoubleEndRequest(BaseModel):
    completed: bool = True


class FocusGuardrailRequest(BaseModel):
    minutes: int = Field(..., ge=5, le=480)
    reason: str = Field(..., min_length=1)


LIVE_EVENT_TYPES = [
    EventType.CHECKIN_DUE,
    EventType.FOCUS_WARNING,
    EventType.TASK_COMPLETED,
    EventType.ENERGY_UPDATED,
    EventType.FOCUS_BLOCK_STARTED,
    EventType.FOCUS_BLOCK_ENDED,
    EventType.SESSION_SUMMARIZED,
    EventType.SYSTEM_NOTICE,
]


def _public_event_payload(event_type: EventType, data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "event_type": RUNTIME._public_event_name(event_type.value),
        "timestamp": datetime.now().isoformat(),
        "data": data,
    }


async def live_event_stream(
    *,
    event_bus=EVENT_BUS,
    keepalive_seconds: int = 15,
):
    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    subscribed = {}

    def make_handler(event_type: EventType):
        def _handler(data: Dict[str, Any]):
            loop.call_soon_threadsafe(
                queue.put_nowait,
                _public_event_payload(event_type, data),
            )

        return _handler

    for event_type in LIVE_EVENT_TYPES:
        handler = make_handler(event_type)
        subscribed[event_type] = handler
        event_bus.subscribe(event_type, handler)

    try:
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=keepalive_seconds)
                yield (
                    f"event: {payload['event_type']}\n"
                    f"data: {json.dumps(payload)}\n\n"
                )
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        for event_type, handler in subscribed.items():
            event_bus.unsubscribe(event_type, handler)


@app.get("/api/bootstrap")
async def get_bootstrap(session_id: Optional[str] = Query(default=None)):
    try:
        return await RUNTIME.bootstrap(session_id=session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/chat/turn")
async def post_chat_turn(request: ChatTurnRequest):
    try:
        return await RUNTIME.chat_turn(request.text, session_id=request.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/user-state")
async def patch_user_state(request: UserStatePatchRequest):
    try:
        return await RUNTIME.update_user_state_data(
            energy_level=request.energy_level,
            medication_time=request.medication_time,
            current_task=request.current_task,
            mood_indicator=request.mood_indicator,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/shutdown")
async def post_shutdown(session_id: str):
    try:
        return await RUNTIME.shutdown_session(session_id=session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/stats")
async def get_stats():
    await RUNTIME.startup()
    return RUNTIME.get_stats_snapshot()


@app.get("/api/history")
async def get_history(limit: int = Query(default=50, ge=1, le=200)):
    await RUNTIME.startup()
    return RUNTIME.get_task_history(limit=limit)


@app.get("/api/sessions")
async def get_sessions():
    await RUNTIME.startup()
    return RUNTIME.db.get_recent_sessions()


@app.get("/api/body-double/status")
async def get_body_double_status():
    await RUNTIME.startup()
    return RUNTIME.get_body_double_status()


@app.post("/api/body-double/start")
async def post_body_double_start(request: BodyDoubleStartRequest):
    return await RUNTIME.start_body_double(
        task=request.task,
        duration_minutes=request.duration_minutes,
        checkin_interval=request.checkin_interval,
    )


@app.post("/api/body-double/pause")
async def post_body_double_pause(request: BodyDoublePauseRequest):
    return await RUNTIME.pause_body_double(reason=request.reason)


@app.post("/api/body-double/end")
async def post_body_double_end(request: BodyDoubleEndRequest):
    return await RUNTIME.end_body_double(completed=request.completed)


@app.get("/api/focus-guardrail/status")
async def get_focus_guardrail_status():
    await RUNTIME.startup()
    return RUNTIME.get_focus_guardrail_status()


@app.post("/api/focus-guardrail")
async def post_focus_guardrail(request: FocusGuardrailRequest):
    return await RUNTIME.set_focus_guardrail(minutes=request.minutes, reason=request.reason)


@app.delete("/api/focus-guardrail")
async def delete_focus_guardrail():
    return await RUNTIME.clear_focus_guardrail()


@app.get("/api/live")
async def get_live_events():
    await RUNTIME.startup()
    return StreamingResponse(
        live_event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/health")
async def health_check():
    try:
        await RUNTIME.health_check()
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
