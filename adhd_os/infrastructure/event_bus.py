import asyncio
import inspect
import json
import logging
from collections import deque
from datetime import datetime
from typing import Dict, List, Any, Callable
from enum import Enum

logger = logging.getLogger(__name__)

class EventType(Enum):
    """Typed events for the event bus."""
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    FOCUS_BLOCK_STARTED = "focus_block_started"
    FOCUS_BLOCK_ENDED = "focus_block_ended"
    FOCUS_WARNING = "focus_warning"
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
        self._event_log: deque = deque(maxlen=1000)
    
    def subscribe(self, event_type: EventType, handler: Callable):
        """Subscribe a handler to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable):
        """Removes a handler from an event type if present."""
        handlers = self._subscribers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
        if not handlers and event_type in self._subscribers:
            self._subscribers.pop(event_type, None)
    
    async def publish(self, event_type: EventType, data: Dict[str, Any]):
        """Publish an event to all subscribers and persist to DB."""
        event = {
            "type": event_type.value,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
        self._event_log.append(event)
        logger.debug("[EVENT] %s: %s", event_type.value, json.dumps(data, default=str))

        # Persist to DB for cross-session pattern analysis
        try:
            from adhd_os.infrastructure.database import DB
            DB.persist_bus_event(event_type.value, json.dumps(data, default=str))
        except Exception:
            pass  # best-effort; don't break the event pipeline

        # Dispatch to subscribers
        if event_type in self._subscribers:
            for handler in list(self._subscribers[event_type]):
                try:
                    if inspect.iscoroutinefunction(handler):
                        await handler(data)
                    else:
                        handler(data)
                except Exception as e:
                    logger.error("[EVENT] Handler failed for %s: %s", event_type.value, e)
    
    def get_recent_events(self, count: int = 10) -> List[Dict]:
        """Returns recent events for context."""
        return list(self._event_log)[-count:]

EVENT_BUS = EventBus()
