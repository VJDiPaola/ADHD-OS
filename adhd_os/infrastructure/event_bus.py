import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any, Callable
from enum import Enum

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
        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable):
        """Remove a handler from an event type."""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(handler)
            except ValueError:
                pass

    def unsubscribe_all(self, event_type: EventType):
        """Remove all handlers for an event type."""
        self._subscribers.pop(event_type, None)

    async def publish(self, event_type: EventType, data: Dict[str, Any]):
        """Publish an event to all subscribers."""
        event = {
            "type": event_type.value,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
        self._event_log.append(event)
        print(f"⚡ [EVENT] {event_type.value}: {json.dumps(data, default=str)}")

        # Dispatch to subscribers (iterate over a copy to allow modification during dispatch)
        if event_type in self._subscribers:
            for handler in list(self._subscribers[event_type]):
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
