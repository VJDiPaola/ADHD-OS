import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List

from google.adk.tools import FunctionTool

from adhd_os.state import USER_STATE
from adhd_os.infrastructure.event_bus import EVENT_BUS, EventType
from adhd_os.infrastructure.cache import TASK_CACHE
from adhd_os.infrastructure.machines import BODY_DOUBLE, FOCUS_TIMER

@FunctionTool
def get_current_time() -> Dict:
    """Returns current time and temporal context."""
    now = datetime.now()
    return {
        "time": now.strftime("%H:%M"),
        "day": now.strftime("%A"),
        "date": now.strftime("%Y-%m-%d"),
        "period": "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    }

@FunctionTool
def get_user_state() -> Dict:
    """Returns comprehensive user state for agent context."""
    return {
        "user_id": USER_STATE.user_id,
        "energy_level": USER_STATE.energy_level,
        "dynamic_multiplier": USER_STATE.dynamic_multiplier,
        "base_multiplier": USER_STATE.base_multiplier,
        "peak_window": USER_STATE.peak_window_status,
        "current_task": USER_STATE.current_task,
        "focus_block_active": USER_STATE.focus_block_active,
        "mood_indicators": USER_STATE.mood_indicators[-5:],  # Last 5
        "time": datetime.now().strftime("%H:%M")
    }

@FunctionTool
def update_user_state(
    energy_level: Optional[int] = None,
    medication_taken: bool = False,
    current_task: Optional[str] = None,
    mood_indicator: Optional[str] = None
) -> Dict:
    """Updates user state. Energy 1-10."""
    changes = []
    
    if energy_level is not None:
        USER_STATE.energy_level = max(1, min(10, energy_level))
        changes.append(f"energy={energy_level}")
        asyncio.create_task(EVENT_BUS.publish(EventType.ENERGY_UPDATED, {"level": energy_level}))
    
    if medication_taken:
        USER_STATE.medication_time = datetime.now()
        changes.append("medication_logged")
    
    if current_task is not None:
        USER_STATE.current_task = current_task
        changes.append(f"task={current_task[:20]}")
    
    if mood_indicator:
        USER_STATE.mood_indicators.append(mood_indicator)
        changes.append(f"mood={mood_indicator}")
    
    return {
        "status": "updated",
        "changes": changes,
        "new_state": get_user_state.func()
    }

@FunctionTool
def apply_time_calibration(estimated_minutes: int, task_type: Optional[str] = None) -> Dict:
    """
    Applies comprehensive time calibration.
    Uses dynamic multiplier and task-type-specific history when available.
    """
    # Check for task-specific multiplier
    specific_mult = USER_STATE.get_task_type_multiplier(task_type) if task_type else None
    
    # Use specific or dynamic
    multiplier = specific_mult or USER_STATE.dynamic_multiplier
    calibrated = int(estimated_minutes * multiplier)
    
    # Build explanation
    factors = []
    if USER_STATE.energy_level <= 5:
        factors.append(f"low energy ({USER_STATE.energy_level}/10)")
    if not USER_STATE.is_in_peak_window:
        factors.append("outside peak focus window")
    if specific_mult:
        factors.append(f"historical data for '{task_type}'")
    
    return {
        "original_estimate": estimated_minutes,
        "multiplier_used": multiplier,
        "multiplier_source": "task_history" if specific_mult else "dynamic",
        "calibrated_estimate": calibrated,
        "factors": factors,
        "recommendation": f"Block {calibrated} minutes, not {estimated_minutes}."
    }

@FunctionTool
def check_task_cache(task_description: str) -> Dict:
    """Checks semantic cache for existing decomposition."""
    cached = TASK_CACHE.get(task_description, USER_STATE.energy_level)
    
    if cached:
        return {
            "found": True,
            "cached_plan": cached.model_dump(),
            "message": "Found cached decomposition!"
        }
    
    similar = TASK_CACHE.get_similar_tasks(task_description)
    return {
        "found": False,
        "similar_tasks": similar,
        "message": "No cache hit. Similar tasks listed if any."
    }

@FunctionTool
def store_task_decomposition(task_description: str, plan_json: Dict) -> Dict:
    """Stores a decomposition plan in the semantic cache."""
    from adhd_os.models.schemas import DecompositionPlan
    try:
        # Validate plan structure
        plan = DecompositionPlan(**plan_json)
        TASK_CACHE.store_with_energy(task_description, plan, USER_STATE.energy_level)
        return {"stored": True, "message": "Plan cached successfully."}
    except Exception as e:
        return {"stored": False, "error": str(e)}

@FunctionTool
def log_task_completion(task_type: str, estimated_minutes: int, actual_minutes: int) -> Dict:
    """Logs task completion for calibration learning."""
    USER_STATE.log_task_completion(task_type, estimated_minutes, actual_minutes)
    
    ratio = actual_minutes / estimated_minutes if estimated_minutes > 0 else 1.0
    
    asyncio.create_task(EVENT_BUS.publish(EventType.TASK_COMPLETED, {
        "task_type": task_type,
        "estimated": estimated_minutes,
        "actual": actual_minutes,
        "ratio": ratio
    }))
    
    return {
        "logged": True,
        "ratio": round(ratio, 2),
        "feedback": "Great data point!" if 0.8 <= ratio <= 1.2 else "Estimate was off - I'll adjust."
    }

@FunctionTool
def log_activation_attempt(task: str, barrier_type: str, intervention: str) -> Dict:
    """Logs task initiation attempts for pattern learning."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "task": task,
        "barrier": barrier_type,
        "intervention": intervention,
        "energy": USER_STATE.energy_level,
        "in_peak": USER_STATE.is_in_peak_window
    }
    
    asyncio.create_task(EVENT_BUS.publish(EventType.TASK_STARTED, entry))
    
    return {"logged": True, "entry": entry}

@FunctionTool
def activate_body_double(task: str, duration_minutes: int, checkin_interval: int = 10) -> Dict:
    """Activates deterministic body double machine."""
    # Run synchronously but fire off async task
    loop = asyncio.get_event_loop()
    result = loop.create_task(BODY_DOUBLE.start_session(task, duration_minutes, checkin_interval))
    return {"status": "activating", "message": f"Starting body double for '{task}'..."}

@FunctionTool
def get_body_double_status() -> Dict:
    """Returns current body double session status."""
    return BODY_DOUBLE.get_status()

@FunctionTool
def set_hyperfocus_guardrail(minutes: int, reason: str) -> Dict:
    """Sets hard stop for hyperfocus protection."""
    loop = asyncio.get_event_loop()
    loop.create_task(FOCUS_TIMER.set_hard_stop(minutes, reason))
    return {"status": "setting", "message": f"Setting {minutes} minute guardrail..."}

@FunctionTool
def schedule_checkin(minutes_from_now: int, message: str) -> Dict:
    """Schedules a future reminder/check-in."""
    checkin_time = datetime.now() + timedelta(minutes=minutes_from_now)
    # In production, use Cloud Tasks or similar
    return {
        "scheduled": True,
        "time": checkin_time.strftime("%H:%M"),
        "message": message
    }

@FunctionTool
def get_recent_history(limit: int = 50) -> List[Dict]:
    """Retrieves recent task history for pattern analysis."""
    from adhd_os.infrastructure.database import DB
    with DB._get_conn() as conn:
        cursor = conn.execute(
            """
            SELECT task_type, estimated_minutes, actual_minutes, energy_level, in_peak_window, timestamp 
            FROM task_history 
            ORDER BY timestamp DESC LIMIT ?
            """,
            (limit,)
        )
        rows = cursor.fetchall()
        return [
            {
                "type": r[0],
                "est": r[1],
                "act": r[2],
                "energy": r[3],
                "peak": bool(r[4]),
                "date": r[5][:10]
            }
            for r in rows
        ]

@FunctionTool
def safe_list_dir(path: str = ".") -> List[str]:
    """Lists files in the project directory (read-only)."""
    from pathlib import Path
    base_path = Path.cwd().resolve()
    target_path = (base_path / path).resolve()
    
    if not target_path.is_relative_to(base_path):
        return ["Error: Access denied. Stay within project root."]
    
    try:
        return os.listdir(target_path)
    except Exception as e:
        return [f"Error: {str(e)}"]

@FunctionTool
def safe_read_file(path: str) -> str:
    """Reads a file from the project directory (read-only)."""
    from pathlib import Path
    base_path = Path.cwd().resolve()
    target_path = (base_path / path).resolve()
    
    if not target_path.is_relative_to(base_path):
        return "Error: Access denied. Stay within project root."
    
    try:
        with open(target_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error: {str(e)}"
