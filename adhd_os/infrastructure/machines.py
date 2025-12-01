import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional
from enum import Enum
from adhd_os.infrastructure.event_bus import EventBus, EventType

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

# Initialize global instances here to be imported by tools
# However, machines need EVENT_BUS which is in event_bus.py
# We can initialize them here if we import EVENT_BUS
from adhd_os.infrastructure.event_bus import EVENT_BUS

BODY_DOUBLE = BodyDoubleMachine(EVENT_BUS)
FOCUS_TIMER = FocusTimerMachine(EVENT_BUS)
