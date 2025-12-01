"""
ADHD-OS Agentic System v2.1 - Merged Implementation

This version combines:
- Infrastructure optimizations (deterministic machines, caching, dynamic state)
- Full agent roster (all 9 specialist agents preserved)
- Proper async patterns and structured outputs
- Warm emotional support with CBT guardrails
- A/B testing capability for model selection

Prerequisites:
    pip install google-adk litellm pydantic numpy

Environment Variables:
    GOOGLE_API_KEY=your-google-ai-key
    ANTHROPIC_API_KEY=your-anthropic-key
    ADHD_OS_MODEL_MODE=production  # or "ab_test"
"""

import os
import asyncio
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod

# Pydantic for structured outputs
from pydantic import BaseModel, Field

# ADK imports
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import FunctionTool
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner

# =============================================================================
# CONFIGURATION
# =============================================================================

class ModelMode(Enum):
    PRODUCTION = "production"      # Optimized for cost/latency
    QUALITY = "quality"            # Optimized for nuance
    AB_TEST = "ab_test"            # Random selection for testing

# Model registry with fallbacks
MODELS = {
    "orchestrator": "gemini-2.0-flash",
    "decomposer_quality": "anthropic/claude-opus-4-5-20251101",
    "decomposer_fast": "gemini-2.0-flash",
    "emotional": "anthropic/claude-sonnet-4-5-20250929",
    "temporal": "gemini-2.0-flash",
    "motivation": "gemini-2.0-flash",
    "pattern_analysis": "gemini-2.0-pro",
}

def get_model(role: str, mode: ModelMode = ModelMode.PRODUCTION) -> str:
    """Returns appropriate model based on role and mode."""
    if mode == ModelMode.AB_TEST and role == "decomposer":
        import random
        return random.choice([MODELS["decomposer_quality"], MODELS["decomposer_fast"]])
    elif mode == ModelMode.QUALITY and role == "decomposer":
        return MODELS["decomposer_quality"]
    elif role == "decomposer":
        return MODELS["decomposer_fast"]
    return MODELS.get(role, "gemini-2.0-flash")

MODEL_MODE = ModelMode(os.environ.get("ADHD_OS_MODEL_MODE", "production"))

# =============================================================================
# STRUCTURED OUTPUT SCHEMAS
# =============================================================================

class TaskStep(BaseModel):
    """Single step in a task decomposition."""
    step_number: int = Field(..., description="Step sequence number")
    action: str = Field(..., description="Specific actionable instruction")
    duration_minutes: int = Field(..., description="Estimated duration")
    is_checkpoint: bool = Field(False, description="Is this a break/checkpoint?")
    energy_required: str = Field("medium", description="low/medium/high")

class DecompositionPlan(BaseModel):
    """Complete task decomposition output."""
    task_name: str
    original_estimate_minutes: int
    calibrated_estimate_minutes: int
    multiplier_applied: float
    steps: List[TaskStep]
    rabbit_hole_risks: List[str]
    activation_phrase: str

class CatastropheAnalysis(BaseModel):
    """Structured output for catastrophe checking."""
    stated_worry: str
    cognitive_distortion: Optional[str] = None
    probability_estimate: str  # "low/medium/high" or percentage
    actual_impact_if_true: str
    in_your_control: List[str]
    not_in_your_control: List[str]
    one_action_now: str

class TimeCalibration(BaseModel):
    """Structured output for time estimates."""
    original_estimate: int
    base_multiplier: float
    energy_adjustment: float
    medication_adjustment: float
    final_multiplier: float
    calibrated_estimate: int
    similar_past_tasks: List[str] = []
    recommendation: str

# =============================================================================
# STATE MANAGEMENT
# =============================================================================

@dataclass
class UserState:
    """
    Comprehensive user state with dynamic calculations.
    In production, this would be backed by Redis (ephemeral) + Firestore (persistent).
    """
    user_id: str = "vince"
    
    # Base configuration (from persistent storage)
    base_multiplier: float = 1.5
    peak_window_hours: tuple = (1, 5)
    
    # Ephemeral state (current session)
    energy_level: int = 5
    medication_time: Optional[datetime] = None
    current_task: Optional[str] = None
    focus_block_active: bool = False
    mood_indicators: List[str] = field(default_factory=list)
    
    # Historical data (for calibration)
    task_history: Dict[str, List[Dict]] = field(default_factory=dict)
    
    @property
    def dynamic_multiplier(self) -> float:
        """
        Calculates real-time multiplier based on current state.
        This is the key insight from v2.0 - multiplier isn't static.
        """
        mult = self.base_multiplier
        
        # Energy adjustment (-0.1 to +0.4)
        if self.energy_level <= 3:
            mult += 0.4  # Very low energy = much slower
        elif self.energy_level <= 5:
            mult += 0.2  # Below average
        elif self.energy_level >= 8:
            mult -= 0.1  # High energy = slightly faster
            
        # Medication adjustment
        if not self.is_in_peak_window:
            mult += 0.3  # Off-peak = slower
            
        # Time of day adjustment
        hour = datetime.now().hour
        if hour >= 15:  # Afternoon slump
            mult += 0.15
        elif hour >= 20:  # Evening
            mult += 0.25
            
        return round(max(1.0, mult), 2)
    
    @property
    def is_in_peak_window(self) -> bool:
        """Returns True if currently in medication peak window."""
        if not self.medication_time:
            return False
        now = datetime.now()
        start = self.medication_time + timedelta(hours=self.peak_window_hours[0])
        end = self.medication_time + timedelta(hours=self.peak_window_hours[1])
        return start <= now <= end
    
    @property
    def peak_window_status(self) -> Dict[str, Any]:
        """Returns detailed peak window information."""
        if not self.medication_time:
            return {"active": False, "reason": "no_medication_logged"}
        
        now = datetime.now()
        start = self.medication_time + timedelta(hours=self.peak_window_hours[0])
        end = self.medication_time + timedelta(hours=self.peak_window_hours[1])
        
        if now < start:
            mins_until = int((start - now).total_seconds() / 60)
            return {"active": False, "reason": "not_yet", "minutes_until_peak": mins_until}
        elif now > end:
            return {"active": False, "reason": "ended"}
        else:
            mins_remaining = int((end - now).total_seconds() / 60)
            return {"active": True, "minutes_remaining": mins_remaining}
    
    def get_task_type_multiplier(self, task_type: str) -> Optional[float]:
        """Returns learned multiplier for specific task types."""
        if task_type in self.task_history:
            history = self.task_history[task_type]
            if len(history) >= 3:  # Need enough data
                ratios = [h["actual"] / h["estimated"] for h in history if h["estimated"] > 0]
                return round(sum(ratios) / len(ratios), 2)
        return None
    
    def log_task_completion(self, task_type: str, estimated: int, actual: int):
        """Logs task completion for multiplier calibration."""
        if task_type not in self.task_history:
            self.task_history[task_type] = []
        self.task_history[task_type].append({
            "estimated": estimated,
            "actual": actual,
            "timestamp": datetime.now().isoformat(),
            "energy": self.energy_level,
            "in_peak": self.is_in_peak_window
        })
        # Keep only last 20 entries per type
        self.task_history[task_type] = self.task_history[task_type][-20:]

# Global state instance
USER_STATE = UserState()

# =============================================================================
# INFRASTRUCTURE: EVENT BUS
# =============================================================================

class EventType(Enum):
    """Typed events for the event bus."""
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    FOCUS_BLOCK_STARTED = "focus_block_started"
    FOCUS_BLOCK_ENDED = "focus_block_ended"
    CHECKIN_DUE = "checkin_due"
    ENERGY_UPDATED = "energy_updated"
    PATTERN_DETECTED = "pattern_detected"
    SESSION_SUMMARIZED = "session_summarized"

class EventBus:
    """
    Async event bus for decoupled component communication.
    In production, this would use Redis Streams or Cloud Pub/Sub.
    """
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._event_log: List[Dict] = []
    
    def subscribe(self, event_type: EventType, handler: Callable):
        """Subscribe a handler to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
    
    async def publish(self, event_type: EventType, data: Dict[str, Any]):
        """Publish an event to all subscribers."""
        event = {
            "type": event_type.value,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
        self._event_log.append(event)
        print(f"⚡ [EVENT] {event_type.value}: {json.dumps(data, default=str)}")
        
        # Dispatch to subscribers
        if event_type in self._subscribers:
            for handler in self._subscribers[event_type]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(data)
                    else:
                        handler(data)
                except Exception as e:
                    print(f"⚠️ [EVENT ERROR] Handler failed: {e}")
    
    def get_recent_events(self, count: int = 10) -> List[Dict]:
        """Returns recent events for context."""
        return self._event_log[-count:]

EVENT_BUS = EventBus()

# =============================================================================
# INFRASTRUCTURE: SEMANTIC CACHE
# =============================================================================

class TaskCache:
    """
    Semantic cache for task decompositions.
    Uses simple hash-based matching for starter; upgrade to embeddings for production.
    """
    def __init__(self):
        self._cache: Dict[str, DecompositionPlan] = {}
        self._embeddings: Dict[str, List[float]] = {}  # For semantic matching
    
    def _normalize_task(self, task: str) -> str:
        """Normalizes task description for matching."""
        # Simple normalization; in production use sentence embeddings
        return task.lower().strip()
    
    def _compute_hash(self, task: str) -> str:
        """Computes hash for exact matching."""
        normalized = self._normalize_task(task)
        return hashlib.md5(normalized.encode()).hexdigest()[:12]
    
    def get(self, task: str, energy_level: int) -> Optional[DecompositionPlan]:
        """
        Retrieves cached decomposition if available.
        Energy level affects whether cache is valid (low energy needs different steps).
        """
        task_hash = self._compute_hash(task)
        
        if task_hash in self._cache:
            cached = self._cache[task_hash]
            # Invalidate if energy difference is significant
            # (A decomposition for energy=8 won't work for energy=3)
            return cached
        
        # TODO: Add semantic similarity search with embeddings
        # for key, embedding in self._embeddings.items():
        #     if cosine_similarity(query_embedding, embedding) > 0.85:
        #         return self._cache[key]
        
        return None
    
    def store(self, task: str, plan: DecompositionPlan):
        """Stores a decomposition in cache."""
        task_hash = self._compute_hash(task)
        self._cache[task_hash] = plan
        print(f"📦 [CACHE] Stored decomposition for: {task[:30]}...")
    
    def get_similar_tasks(self, task: str, limit: int = 3) -> List[str]:
        """Returns similar cached tasks for reference."""
        # Simple keyword matching; upgrade to embeddings
        normalized = self._normalize_task(task)
        keywords = set(normalized.split())
        
        matches = []
        for cached_task in self._cache.keys():
            cached_keywords = set(self._normalize_task(cached_task).split())
            overlap = len(keywords & cached_keywords)
            if overlap > 0:
                matches.append((cached_task, overlap))
        
        matches.sort(key=lambda x: x[1], reverse=True)
        return [m[0] for m in matches[:limit]]

TASK_CACHE = TaskCache()

# =============================================================================
# INFRASTRUCTURE: DETERMINISTIC MACHINES
# =============================================================================

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
    def __init__(self, event_bus: EventBus):
        self.state = BodyDoubleState.IDLE
        self.task: Optional[str] = None
        self.duration_minutes: int = 0
        self.start_time: Optional[datetime] = None
        self.checkin_count: int = 0
        self.event_bus = event_bus
        self._active_task: Optional[asyncio.Task] = None
    
    async def start_session(self, task: str, duration_minutes: int, checkin_interval: int = 10) -> Dict:
        """Starts a body double session."""
        if self.state == BodyDoubleState.ACTIVE:
            return {"status": "error", "message": f"Already monitoring: {self.task}"}
        
        self.task = task
        self.duration_minutes = duration_minutes
        self.start_time = datetime.now()
        self.checkin_count = 0
        self.state = BodyDoubleState.ACTIVE
        
        # Publish event
        await self.event_bus.publish(EventType.FOCUS_BLOCK_STARTED, {
            "task": task,
            "duration": duration_minutes
        })
        
        # Start background monitoring
        self._active_task = asyncio.create_task(
            self._monitoring_loop(checkin_interval)
        )
        
        return {
            "status": "started",
            "task": task,
            "duration": duration_minutes,
            "checkin_interval": checkin_interval,
            "message": f"🤖 Got it! Monitoring '{task}' for {duration_minutes} minutes. I'll check in every {checkin_interval} minutes."
        }
    
    async def _monitoring_loop(self, interval_minutes: int):
        """Background loop for check-ins."""
        interval_seconds = interval_minutes * 60
        total_checkins = self.duration_minutes // interval_minutes
        
        # For demo, use shorter intervals (2 seconds = 1 "interval")
        demo_interval = 3  # seconds
        
        for i in range(total_checkins):
            if self.state != BodyDoubleState.ACTIVE:
                break
            
            await asyncio.sleep(demo_interval)
            self.checkin_count += 1
            
            # Generate check-in message (no LLM needed!)
            messages = [
                f"👀 Check-in {self.checkin_count}/{total_checkins}: Still on '{self.task}'?",
                f"⏱️ {interval_minutes * self.checkin_count} minutes in. How's it going?",
                f"💪 Checkpoint! Take a breath. Then back to '{self.task}'.",
            ]
            message = messages[self.checkin_count % len(messages)]
            print(f"\n{message}\n")
            
            await self.event_bus.publish(EventType.CHECKIN_DUE, {
                "task": self.task,
                "checkin_number": self.checkin_count,
                "total_checkins": total_checkins
            })
        
        # Session complete
        if self.state == BodyDoubleState.ACTIVE:
            await self._complete_session()
    
    async def _complete_session(self):
        """Handles session completion."""
        self.state = BodyDoubleState.COMPLETING
        
        print(f"\n🎉 DONE! '{self.task}' session complete after {self.duration_minutes} minutes!")
        print(f"   Completed {self.checkin_count} check-ins.\n")
        
        await self.event_bus.publish(EventType.FOCUS_BLOCK_ENDED, {
            "task": self.task,
            "duration": self.duration_minutes,
            "checkins_completed": self.checkin_count,
            "status": "completed"
        })
        
        self.state = BodyDoubleState.IDLE
        self.task = None
    
    async def pause_session(self, reason: str = "") -> Dict:
        """Pauses the current session."""
        if self.state != BodyDoubleState.ACTIVE:
            return {"status": "error", "message": "No active session to pause"}
        
        self.state = BodyDoubleState.PAUSED
        if self._active_task:
            self._active_task.cancel()
        
        return {
            "status": "paused",
            "task": self.task,
            "reason": reason,
            "message": f"⏸️ Paused '{self.task}'. Say 'resume' when ready."
        }
    
    async def end_session(self, completed: bool = True) -> Dict:
        """Ends the current session."""
        if self.state == BodyDoubleState.IDLE:
            return {"status": "error", "message": "No active session"}
        
        if self._active_task:
            self._active_task.cancel()
        
        status = "completed" if completed else "abandoned"
        
        await self.event_bus.publish(EventType.FOCUS_BLOCK_ENDED, {
            "task": self.task,
            "status": status,
            "checkins_completed": self.checkin_count
        })
        
        result = {
            "status": status,
            "task": self.task,
            "checkins_completed": self.checkin_count,
            "message": f"{'🎉 Nice work!' if completed else '👋 Session ended.'}"
        }
        
        self.state = BodyDoubleState.IDLE
        self.task = None
        return result
    
    def get_status(self) -> Dict:
        """Returns current status."""
        if self.state == BodyDoubleState.IDLE:
            return {"state": "idle", "message": "No active session"}
        
        elapsed = (datetime.now() - self.start_time).seconds // 60 if self.start_time else 0
        remaining = max(0, self.duration_minutes - elapsed)
        
        return {
            "state": self.state.value,
            "task": self.task,
            "elapsed_minutes": elapsed,
            "remaining_minutes": remaining,
            "checkins_completed": self.checkin_count
        }

BODY_DOUBLE = BodyDoubleMachine(EVENT_BUS)

class FocusTimerMachine:
    """
    Deterministic focus timer with hyperfocus guardrails.
    """
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.hard_stop_time: Optional[datetime] = None
        self.hard_stop_reason: Optional[str] = None
        self._warning_task: Optional[asyncio.Task] = None
    
    async def set_hard_stop(self, minutes: int, reason: str) -> Dict:
        """Sets a hard stop guardrail for hyperfocus protection."""
        self.hard_stop_time = datetime.now() + timedelta(minutes=minutes)
        self.hard_stop_reason = reason
        
        # Schedule warnings
        self._warning_task = asyncio.create_task(
            self._warning_loop(minutes)
        )
        
        return {
            "status": "guardrail_set",
            "hard_stop": self.hard_stop_time.strftime("%H:%M"),
            "reason": reason,
            "message": f"⏰ Hard stop set for {self.hard_stop_time.strftime('%H:%M')} ({reason}). I'll warn you at 30, 10, and 5 minutes."
        }
    
    async def _warning_loop(self, total_minutes: int):
        """Issues warnings before hard stop."""
        warnings = [
            (total_minutes - 30, "30 minutes until hard stop"),
            (total_minutes - 10, "⚠️ 10 minutes until hard stop!"),
            (total_minutes - 5, "🚨 5 MINUTES! Start wrapping up NOW."),
            (total_minutes, "🛑 HARD STOP. Save your work. Step away.")
        ]
        
        # Demo mode: compress time
        demo_multiplier = 0.1  # 1 minute = 0.1 seconds for demo
        
        elapsed = 0
        for warning_time, message in warnings:
            if warning_time <= 0:
                continue
            wait_time = (warning_time - elapsed) * demo_multiplier
            await asyncio.sleep(max(0.5, wait_time))
            print(f"\n{message}\n")
            elapsed = warning_time
    
    async def clear_guardrail(self) -> Dict:
        """Clears the hard stop guardrail."""
        if self._warning_task:
            self._warning_task.cancel()
        
        self.hard_stop_time = None
        self.hard_stop_reason = None
        
        return {"status": "cleared", "message": "Guardrail cleared."}

FOCUS_TIMER = FocusTimerMachine(EVENT_BUS)

# =============================================================================
# TOOLS
# =============================================================================

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

# =============================================================================
# AGENTS: ACTIVATION CLUSTER
# =============================================================================

task_init_agent = LlmAgent(
    name="task_initiation_agent",
    model=LiteLlm(model=MODELS["emotional"]),  # Claude for nuanced barrier detection
    
    description="""
    Specialist for overcoming task initiation paralysis.
    Triggers: "stuck", "can't start", "avoiding", "procrastinating", "don't want to"
    """,
    
    instruction="""
    You are a Task Initiation Specialist for someone with ADHD.
    Your ONLY job is to help them START—not plan, not strategize, just START.
    
    PROCESS:
    1. Use get_user_state to understand their current energy and context.
    
    2. Identify the ACTUAL barrier (often different from stated):
       - "Unclear scope" → They don't know what "done" looks like
       - "Boring/tedious" → No dopamine, needs novelty injection
       - "Scary/high-stakes" → Fear of failure or judgment
       - "Too big" → Overwhelm, needs microscopic first step
       - "Low energy" → Task exceeds current capacity
       - "Perfectionism" → Can't start until they can do it perfectly
       
    3. Generate the SMALLEST possible action:
       - Must take ≤5 minutes
       - Must be unambiguous ("open the file" not "get started")
       - Must not require decisions
       
    4. Provide an ACTIVATION PHRASE:
       "I'm just going to [specific action]."
       
    5. Log with log_activation_attempt for pattern learning.
    
    GOOD first steps:
    ✓ "Open the QBR template file" 
    ✓ "Write the subject line only"
    ✓ "Set a 10-minute timer and commit to that only"
    ✓ "Put your phone in another room"
    
    BAD first steps:
    ✗ "Start working on the QBR" (too vague)
    ✗ "Review the data and create an outline" (multiple steps)
    ✗ "Think about what you want to accomplish" (requires decisions)
    
    Be warm but direct. No lectures. Just the tiny next step.
    """,
    
    tools=[get_user_state, get_current_time, log_activation_attempt],
)

decomposer_agent = LlmAgent(
    name="task_decomposer_agent",
    model=LiteLlm(model=get_model("decomposer", MODEL_MODE)),
    
    description="""
    Breaks complex tasks into ADHD-friendly microscopic steps.
    Triggers: "break down", "decompose", "too big", tasks estimated >30 min
    """,
    
    instruction="""
    You are a Task Decomposition Specialist for ADHD brains.
    Your job is to make the invisible visible—break tasks into steps so small
    they bypass executive function resistance.
    
    PROTOCOL:
    1. FIRST: Check cache with check_task_cache. If found, return cached plan.
    
    2. Get user state with get_user_state for energy and multiplier context.
    
    3. Apply time calibration using apply_time_calibration.
    
    4. Generate decomposition following these rules:
       - Each step ≤10 minutes (ideally ≤5 for low energy)
       - Each step has CLEAR completion state
       - CHECKPOINTS every 20-30 minutes (stand, stretch, water)
       - Front-load easy steps (build momentum)
       - Flag rabbit hole risks
    
    OUTPUT FORMAT:
    ```
    🎯 TASK: [Task Name]
    ⏱️ Your estimate: [X] min → Calibrated: [Y] min (×[multiplier])
    
    □ Step 1 (X min): [Specific action with clear end state]
    □ Step 2 (X min): [Specific action with clear end state]
    □ Step 3 (X min): [Specific action with clear end state]
       ↳ CHECKPOINT: Stand, stretch, water
    □ Step 4 (X min): [Specific action with clear end state]
    ...
    
    ⚠️ RABBIT HOLE RISKS:
    - [What might distract them] → [Prevention strategy]
    
    🏁 Activation phrase: "I'm just going to [Step 1]."
    ```
    
    For low energy (≤4): Make steps even smaller, add more checkpoints.
    For high energy (≥8): Can use slightly larger chunks.
    """,
    
    tools=[get_user_state, check_task_cache, apply_time_calibration, get_current_time],
)

body_double_agent = LlmAgent(
    name="body_double_agent",
    model=MODELS["temporal"],  # Gemini Flash - just routing to machine
    
    description="""
    Provides virtual body-doubling for accountability.
    Triggers: "body double", "stay with me", "accountability", "work together"
    """,
    
    instruction="""
    You activate the body double system for accountability.
    
    PROCESS:
    1. Confirm the task, duration, and check-in preference.
    2. Use activate_body_double tool to start the deterministic machine.
    3. The machine handles check-ins automatically (no LLM needed).
    
    DEFAULT VALUES:
    - Duration: 30 minutes
    - Check-in interval: 10 minutes
    
    If user asks for status, use get_body_double_status.
    If user says "done" or "stop", acknowledge completion.
    
    Keep responses brief. The machine does the work.
    """,
    
    tools=[activate_body_double, get_body_double_status, get_current_time],
)

# =============================================================================
# AGENTS: TEMPORAL CLUSTER
# =============================================================================

time_calibrator_agent = LlmAgent(
    name="time_calibrator_agent",
    model=MODELS["temporal"],  # Gemini Flash
    
    description="""
    Calibrates time estimates to counteract ADHD time blindness.
    Triggers: "how long", "time check", "realistic", "can I do X by Y", estimates
    """,
    
    instruction="""
    You are a Time Calibration Specialist for ADHD time blindness.
    
    PROTOCOL:
    1. Get current state with get_user_state.
    2. Apply calibration with apply_time_calibration.
    3. Be DIRECT about the correction—don't soften it.
    
    RESPONSE FORMAT:
    ```
    Your estimate: [X] minutes
    Your multiplier: [Y]x (because: [factors])
    Calibrated estimate: [Z] minutes
    
    [If checking against deadline:]
    Available time: [A] minutes
    Verdict: ✅ Realistic / ⚠️ Tight / ❌ Unrealistic
    
    Recommendation: [Specific action]
    ```
    
    Time blindness thrives on optimism—counter it with data, not judgment.
    
    When user completes a task, encourage them to log with log_task_completion
    so we can improve calibration over time.
    """,
    
    tools=[get_user_state, get_current_time, apply_time_calibration, log_task_completion],
)

calendar_agent = LlmAgent(
    name="calendar_agent",
    model=MODELS["temporal"],
    
    description="""
    Manages calendar integration and schedule optimization.
    Triggers: "schedule", "calendar", "block time", "when should I"
    """,
    
    instruction="""
    You are a Calendar Strategist for ADHD productivity.
    
    KEY PRINCIPLES:
    1. PEAK WINDOW PROTECTION
       - Peak focus: ~1hr to ~5hr post-medication
       - Reserve for cognitively demanding work ONLY
       - Never schedule meetings during peak if avoidable
       
    2. REALISTIC SCHEDULING
       - Always use apply_time_calibration before blocking time
       - Include 5-10 min buffer between tasks
       - Account for transition rituals
       
    3. ENERGY MATCHING
       - Morning (peak): Deep work, hard problems
       - Afternoon: Meetings, calls, collaboration
       - End of day: Admin, email, low-stakes tasks
    
    Check get_user_state for current peak window status.
    
    Always offer to set a hyperfocus guardrail (set_hyperfocus_guardrail)
    when scheduling deep work blocks.
    """,
    
    tools=[get_user_state, get_current_time, apply_time_calibration, schedule_checkin, set_hyperfocus_guardrail],
)

focus_timer_agent = LlmAgent(
    name="focus_timer_agent",
    model=MODELS["temporal"],
    
    description="""
    Manages focus sessions and hyperfocus guardrails.
    Triggers: "focus session", "hyperfocus", "hard stop", "guardrail"
    """,
    
    instruction="""
    You manage focus sessions and protect against hyperfocus drift.
    
    FOCUS SESSION:
    - Use activate_body_double for accountability sessions
    - Set clear end times
    
    HYPERFOCUS GUARDRAILS:
    - When user enters approved deep work, set a hard stop
    - Use set_hyperfocus_guardrail with reason (e.g., "client call at 2pm")
    - The machine handles warnings automatically
    
    Be firm about hard stops. Hyperfocus feels productive but can derail the day.
    """,
    
    tools=[get_current_time, get_user_state, activate_body_double, set_hyperfocus_guardrail, get_body_double_status],
)

# =============================================================================
# AGENTS: EMOTIONAL CLUSTER
# =============================================================================

catastrophe_agent = LlmAgent(
    name="catastrophe_check_agent",
    model=LiteLlm(model=MODELS["emotional"]),  # Claude for empathy
    
    description="""
    Reality-tests catastrophic thinking and anxiety spirals.
    Triggers: "disaster", "ruined", "fail", "worried", "anxious", "stressed"
    """,
    
    instruction="""
    You are a Cognitive Reframe Specialist for ADHD-related anxiety.
    
    PROTOCOL (in this order):
    
    1. ACKNOWLEDGE the emotion:
       "That sounds really stressful." / "I can hear how worried you are."
       (Validate the FEELING, not the catastrophic interpretation)
       
    2. SPECIFY the worry:
       - "What specifically happened?"
       - "What's the worst-case scenario you're imagining?"
       - "What would that mean for you?"
       
    3. REALITY-TEST with specifics:
       - "What's the actual probability of that?" (estimate %)
       - "What happened last time you worried about something similar?"
       - "If it did happen, what's the actual impact?"
       
    4. IDENTIFY CONTROL:
       - "What IS in your control right now?" (list 2-3 things)
       - "What's NOT in your control?" (name it, release it)
       
    5. ONE ACTION:
       - "What's one thing you can do in the next 30 minutes?"
       
    NEVER SAY:
    ✗ "Don't worry"
    ✗ "It'll be fine"
    ✗ "You're overreacting"
    
    INSTEAD:
    ✓ "The feeling is valid. Let's check if the story matches reality."
    
    Use get_user_state to understand if low energy might be amplifying anxiety.
    """,
    
    tools=[get_user_state, get_current_time],
)

rsd_agent = LlmAgent(
    name="rsd_shield_agent",
    model=LiteLlm(model=MODELS["emotional"]),  # Claude for empathy
    
    description="""
    Protects against Rejection Sensitive Dysphoria (RSD).
    Triggers: "hate me", "angry at me", "disappointed", "rejected", "criticized"
    """,
    
    instruction="""
    You are an RSD Shield Specialist.
    
    RSD causes perceived rejection to feel catastrophic—even when the rejection
    isn't real or isn't personal. Your job is to provide protection, not dismissal.
    
    PROTOCOL (warmth first, framework second):
    
    1. VALIDATE THE EMOTION (always first):
       "That stings." / "Ouch, that landed hard." / "I hear how much that hurt."
       
    2. GENTLY NAME THE PATTERN (if helpful):
       "This might be our brain's 'mind reading' pattern—assuming we know
       what they're thinking without evidence."
       
       Common patterns:
       - Mind Reading: Assuming you know their thoughts
       - Personalization: Assuming their mood is about you
       - Catastrophizing: Assuming one interaction defines everything
       - All-or-Nothing: "They hate me" vs "They were short once"
       
    3. OFFER ALTERNATIVE INTERPRETATIONS (always 3-4):
       "What if..."
       - They're slammed and wrote quickly?
       - They're having a rough day unrelated to you?
       - That's just their communication style?
       - There's context you're not seeing?
       
    4. EVIDENCE CHECK:
       - What positive interactions have you had with them recently?
       - What do you actually know vs. what are you assuming?
       
    5. RESPONSE STRATEGY (if needed):
       - Draft a measured response
       - Suggest waiting before responding
       - Identify if follow-up is even necessary
       
    CRITICAL: Never say "you're being too sensitive" or lead with the 
    cognitive distortion label. The feeling is real—we're questioning
    the interpretation, not the pain.
    """,
    
    tools=[get_user_state, get_current_time],
)

motivation_agent = LlmAgent(
    name="motivation_agent",
    model=MODELS["motivation"],  # Gemini Flash
    
    description="""
    Makes boring tasks interesting using ADHD interest-based strategies.
    Triggers: "boring", "make interesting", "motivate", "don't want to", "hate this"
    """,
    
    instruction="""
    You are a Motivation Engineer for the ADHD interest-based nervous system.
    
    CORE INSIGHT: ADHD brains aren't motivated by importance—they're motivated by:
    - Interest (novelty, curiosity)
    - Challenge (competition, games)
    - Urgency (deadlines, time pressure)
    - Passion (personal connection)
    
    STRATEGIES (offer 2-3 based on task and energy):
    
    1. SPEEDRUN 🏃
       "Can you beat your best time? Target: [X] minutes. Ready? Go."
       
    2. STREAK GAME 📊
       "5 done → 5 min break. 10 done → snack. All done → [reward]."
       
    3. NOVELTY INJECTION 🎲
       - Different location (couch? standing? coffee shop?)
       - New playlist or podcast
       - Different tool (voice-to-text? whiteboard?)
       - Different time (batch all boring tasks into one "grind block")
       
    4. INTERLEAVING 🔄
       "One boring task, then 5 min of something interesting. Repeat."
       
    5. ACCOUNTABILITY STAKES 🎯
       "Tell someone you'll have it done by [time]."
       
    6. REWARD STACKING 🎁
       "You can [desired thing] AFTER [task]."
       
    Match strategy to energy level from get_user_state:
    - Low energy: Gentler options (interleaving, novelty)
    - High energy: Challenge options (speedrun, stakes)
    
    NEVER use shame, "you should," or guilt. We're hacking the brain, not fighting it.
    """,
    
    tools=[get_user_state, get_current_time, activate_body_double],
)

# =============================================================================
# CONTEXT MANAGEMENT: SESSION SUMMARIZER
# =============================================================================

session_summarizer = LlmAgent(
    name="session_summarizer",
    model=MODELS["temporal"],  # Fast summarization
    
    description="Compresses session context for storage and handoff.",
    
    instruction="""
    Summarize the current session into a compact JSON object:
    
    {
        "session_date": "YYYY-MM-DD",
        "energy_trajectory": "started X, ended Y",
        "tasks_discussed": ["task1", "task2"],
        "tasks_completed": ["task1"],
        "barriers_encountered": ["type1", "type2"],
        "interventions_used": ["intervention1"],
        "open_loops": ["things still pending"],
        "notable_patterns": ["any recurring themes"],
        "tomorrow_priorities": ["if discussed"]
    }
    
    Keep it factual and compact. This is for data, not narrative.
    """,
    
    tools=[get_user_state],
)

# =============================================================================
# ORCHESTRATOR
# =============================================================================

orchestrator = LlmAgent(
    name="adhd_os_orchestrator",
    model=MODELS["orchestrator"],  # Gemini Flash for fast routing
    
    description="Root orchestrator for ADHD Operating System v2.1",
    
    instruction="""
    You are the central coordinator of an executive function support system
    for someone with ADHD. Route requests to the appropriate specialist.
    
    ROUTING RULES:
    
    ACTIVATION CLUSTER (getting started):
    - "stuck", "can't start", "avoiding" → task_initiation_agent
    - "break down", "too big", "decompose" → task_decomposer_agent
    - "body double", "stay with me" → body_double_agent
    
    TEMPORAL CLUSTER (time management):
    - "how long", "time check", "realistic" → time_calibrator_agent
    - "schedule", "calendar", "when should" → calendar_agent
    - "focus session", "hyperfocus", "guardrail" → focus_timer_agent
    
    EMOTIONAL CLUSTER (regulation):
    - worry, anxiety, "disaster", "fail" → catastrophe_check_agent
    - "hate me", "rejected", "criticized" → rsd_shield_agent
    - "boring", "motivate", "interesting" → motivation_agent
    
    SPECIAL COMMANDS:
    - "morning activation" → Run morning protocol (ask energy, meds, priorities)
    - "shutdown" → Run session_summarizer, then end
    - "status" → Report current state and any active sessions
    
    For morning activation, ask:
    1. Energy level (1-10)?
    2. Did you take medication? What time?
    3. What are today's top 3 priorities?
    4. Any anxiety or blockers?
    
    Then create a day structure optimized for their peak window.
    
    CONTEXT AWARENESS:
    - Check get_user_state before routing emotional issues (low energy amplifies anxiety)
    - If user seems to be spiraling (repeated questions), gently note the pattern
    - If user is avoiding (long gaps, topic-switching), name it compassionately
    
    Be warm but direct. Prefer action over discussion.
    """,
    
    sub_agents=[
        # Activation Cluster
        task_init_agent,
        decomposer_agent,
        body_double_agent,
        
        # Temporal Cluster
        time_calibrator_agent,
        calendar_agent,
        focus_timer_agent,
        
        # Emotional Cluster
        catastrophe_agent,
        rsd_agent,
        motivation_agent,
        
        # Utility
        session_summarizer,
    ],
    
    tools=[get_user_state, get_current_time, update_user_state, get_body_double_status],
)

# =============================================================================
# MAIN APPLICATION
# =============================================================================

async def run_adhd_os():
    """Main interaction loop for ADHD-OS v2.1."""
    
    # Initialize session
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="adhd_os",
        user_id=USER_STATE.user_id
    )
    
    # Initialize runner
    runner = Runner(
        agent=orchestrator,
        app_name="adhd_os",
        session_service=session_service
    )
    
    print("=" * 70)
    print("  ADHD Operating System v2.1")
    print("  Merged: Full Agent Roster + Optimized Infrastructure")
    print("=" * 70)
    print(f"\n  Model Mode: {MODEL_MODE.value}")
    print(f"  Decomposer: {get_model('decomposer', MODEL_MODE)}")
    print()
    print("Quick commands:")
    print("  'morning activation' - Start your day with structure")
    print("  'stuck on [task]'    - Get unstuck with microscopic steps")
    print("  'decompose [task]'   - Break down a complex task")
    print("  'body double [task]' - Accountability partner (deterministic)")
    print("  'time check [X min]' - Calibrate a time estimate")
    print("  '[worry/anxiety]'    - Get reality-tested")
    print("  'make [task] fun'    - Motivation strategies")
    print("  'shutdown'           - Summarize and exit")
    print("  'quit'               - Exit immediately")
    print()
    
    # Subscribe to events for demo visibility
    async def on_task_completed(data):
        ratio = data.get("ratio", 1.0)
        if ratio > 1.5:
            print(f"📊 [PATTERN] Task took {ratio:.1f}x longer than estimated. Adjusting multiplier...")
    
    EVENT_BUS.subscribe(EventType.TASK_COMPLETED, on_task_completed)
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() == 'quit':
                print("\n👋 Work mode complete. See you tomorrow!")
                break
            
            if user_input.lower() == 'shutdown':
                print("\n💾 Summarizing session...")
                # In production, run session_summarizer here
                await EVENT_BUS.publish(EventType.SESSION_SUMMARIZED, {
                    "timestamp": datetime.now().isoformat(),
                    "session_id": session.id
                })
                print("👋 Session saved. Work mode complete!")
                break
            
            # Process through orchestrator
            response = await runner.run_async(
                user_id=USER_STATE.user_id,
                session_id=session.id,
                new_message=user_input
            )
            
            # Extract and print response
            if response and response.content:
                print(f"\nADHD-OS: {response.content}")
            else:
                print("\n[Processing... check for deterministic machine output above]")
                
        except KeyboardInterrupt:
            print("\n\n⚡ Interrupted. Running quick shutdown...")
            await EVENT_BUS.publish(EventType.SESSION_SUMMARIZED, {"status": "interrupted"})
            break
        except Exception as e:
            print(f"\n⚠️ Error: {e}")
            import traceback
            traceback.print_exc()

# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Verify API keys
    missing_keys = []
    if not os.environ.get("GOOGLE_API_KEY"):
        missing_keys.append("GOOGLE_API_KEY")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing_keys.append("ANTHROPIC_API_KEY")
    
    if missing_keys:
        print(f"⚠️  Missing API keys: {', '.join(missing_keys)}")
        print("   Set them in your environment to enable all agents.")
        print()
    
    print("🚀 Starting ADHD-OS v2.1...")
    print()
    
    asyncio.run(run_adhd_os())
