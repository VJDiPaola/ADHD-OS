"""Tests for EventBus: subscribe, unsubscribe, publish, duplicate prevention."""

import pytest
from adhd_os.infrastructure.event_bus import EventBus, EventType


class TestSubscribe:
    def test_subscribe_adds_handler(self, event_bus):
        handler = lambda d: None
        event_bus.subscribe(EventType.TASK_STARTED, handler)
        assert handler in event_bus._subscribers[EventType.TASK_STARTED]

    def test_duplicate_subscribe_ignored(self, event_bus):
        handler = lambda d: None
        event_bus.subscribe(EventType.TASK_STARTED, handler)
        event_bus.subscribe(EventType.TASK_STARTED, handler)
        assert len(event_bus._subscribers[EventType.TASK_STARTED]) == 1


class TestUnsubscribe:
    def test_unsubscribe_removes_handler(self, event_bus):
        handler = lambda d: None
        event_bus.subscribe(EventType.TASK_STARTED, handler)
        event_bus.unsubscribe(EventType.TASK_STARTED, handler)
        assert handler not in event_bus._subscribers.get(EventType.TASK_STARTED, [])

    def test_unsubscribe_nonexistent_handler_no_error(self, event_bus):
        handler = lambda d: None
        event_bus.unsubscribe(EventType.TASK_STARTED, handler)  # No error

    def test_unsubscribe_all(self, event_bus):
        h1 = lambda d: None
        h2 = lambda d: None
        event_bus.subscribe(EventType.TASK_STARTED, h1)
        event_bus.subscribe(EventType.TASK_STARTED, h2)
        event_bus.unsubscribe_all(EventType.TASK_STARTED)
        assert EventType.TASK_STARTED not in event_bus._subscribers


class TestPublish:
    @pytest.mark.asyncio
    async def test_publish_calls_sync_handler(self, event_bus):
        received = []
        event_bus.subscribe(EventType.TASK_STARTED, lambda d: received.append(d))
        await event_bus.publish(EventType.TASK_STARTED, {"task": "test"})
        assert len(received) == 1
        assert received[0]["task"] == "test"

    @pytest.mark.asyncio
    async def test_publish_calls_async_handler(self, event_bus):
        received = []

        async def handler(data):
            received.append(data)

        event_bus.subscribe(EventType.TASK_COMPLETED, handler)
        await event_bus.publish(EventType.TASK_COMPLETED, {"ratio": 1.5})
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_publish_multiple_handlers(self, event_bus):
        count = {"value": 0}
        event_bus.subscribe(EventType.ENERGY_UPDATED, lambda d: count.update(value=count["value"] + 1))
        event_bus.subscribe(EventType.ENERGY_UPDATED, lambda d: count.update(value=count["value"] + 1))
        await event_bus.publish(EventType.ENERGY_UPDATED, {"level": 5})
        assert count["value"] == 2

    @pytest.mark.asyncio
    async def test_publish_no_subscribers_no_error(self, event_bus):
        await event_bus.publish(EventType.PATTERN_DETECTED, {"data": "test"})

    @pytest.mark.asyncio
    async def test_handler_exception_doesnt_break_others(self, event_bus):
        received = []

        def bad_handler(data):
            raise ValueError("boom")

        event_bus.subscribe(EventType.TASK_STARTED, bad_handler)
        event_bus.subscribe(EventType.TASK_STARTED, lambda d: received.append(d))

        await event_bus.publish(EventType.TASK_STARTED, {"task": "test"})
        # Second handler should still fire despite first failing
        assert len(received) == 1


class TestEventLog:
    @pytest.mark.asyncio
    async def test_events_are_logged(self, event_bus):
        await event_bus.publish(EventType.TASK_STARTED, {"task": "a"})
        await event_bus.publish(EventType.TASK_COMPLETED, {"task": "a"})

        events = event_bus.get_recent_events(10)
        assert len(events) == 2
        assert events[0]["type"] == "task_started"
        assert events[1]["type"] == "task_completed"

    @pytest.mark.asyncio
    async def test_recent_events_limited(self, event_bus):
        for i in range(20):
            await event_bus.publish(EventType.ENERGY_UPDATED, {"level": i})

        events = event_bus.get_recent_events(5)
        assert len(events) == 5
