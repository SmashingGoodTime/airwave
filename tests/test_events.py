"""Tests for the event bus and default handlers."""

import asyncio
import json
import logging

import pytest

from server.events.emitter import EventBus
from server.events.handlers import (
    _on_provider_error,
    _on_provider_recovered,
    _provider_state,
    get_provider_state,
    setup_default_handlers,
)


class TestEventBus:
    def test_handler_receives_event(self):
        bus = EventBus()
        received = []
        bus.on("test.event", lambda event, data: received.append((event, data)))
        bus.emit("test.event", {"key": "value"})
        assert len(received) == 1
        assert received[0] == ("test.event", {"key": "value"})

    def test_multiple_handlers(self):
        bus = EventBus()
        results = []
        bus.on("x", lambda e, d: results.append("a"))
        bus.on("x", lambda e, d: results.append("b"))
        bus.emit("x")
        assert results == ["a", "b"]

    def test_emit_no_handlers(self):
        bus = EventBus()
        # Should not raise
        bus.emit("nonexistent.event", {"data": 1})

    def test_emit_default_data(self):
        bus = EventBus()
        received = []
        bus.on("e", lambda event, data: received.append(data))
        bus.emit("e")
        assert received == [{}]

    def test_handler_exception_does_not_propagate(self):
        bus = EventBus()

        def bad_handler(event, data):
            raise ValueError("oops")

        received = []
        bus.on("e", bad_handler)
        bus.on("e", lambda e, d: received.append("ok"))
        bus.emit("e")
        # Second handler should still run
        assert received == ["ok"]

    def test_async_handler_without_running_loop_is_dropped(self, caplog):
        """Without a running loop the coroutine is dropped with a warning,
        never run on a foreign loop via asyncio.run."""
        bus = EventBus()
        received = []

        async def async_handler(event, data):
            received.append((event, data))

        bus.on("async.event", async_handler)
        with caplog.at_level(logging.WARNING, logger="server.events.emitter"):
            bus.emit("async.event", {"key": "value"})

        assert received == []
        assert "dropping async handler" in caplog.text

    @pytest.mark.asyncio
    async def test_async_handler_task_is_strongly_referenced(self):
        bus = EventBus()
        release = asyncio.Event()
        received = []

        async def async_handler(event, data):
            await release.wait()
            received.append(event)

        bus.on("async.event", async_handler)
        bus.emit("async.event")

        # The pending task must be held by the bus so GC cannot collect it.
        assert len(bus._tasks) == 1
        release.set()
        await asyncio.gather(*bus._tasks)
        assert received == ["async.event"]
        assert bus._tasks == set()

    @pytest.mark.asyncio
    async def test_async_handler_exception_is_logged(self, caplog):
        bus = EventBus()

        async def bad_handler(event, data):
            raise ValueError("async oops")

        bus.on("async.event", bad_handler)

        with caplog.at_level(logging.ERROR, logger="server.events.emitter"):
            bus.emit("async.event", {"key": "value"})
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        assert "Error in async handler for event 'async.event'" in caplog.text

    def test_ws_client_management(self):
        bus = EventBus()

        class FakeWS:
            pass

        ws = FakeWS()
        bus.connect_ws(ws)
        assert ws in bus._ws_clients
        bus.disconnect_ws(ws)
        assert ws not in bus._ws_clients

    def test_ws_broadcast_without_running_loop_drops_message(self, caplog):
        bus = EventBus()

        class FakeWS:
            def __init__(self):
                self.messages = []

            async def send_text(self, message):
                self.messages.append(message)

        ws = FakeWS()
        bus.connect_ws(ws)
        with caplog.at_level(logging.WARNING, logger="server.events.emitter"):
            bus.emit("ws.event", {"key": "value"})

        assert ws.messages == []
        assert "dropping WebSocket message" in caplog.text

    @pytest.mark.asyncio
    async def test_ws_broadcast_delivers_through_per_client_queue(self):
        bus = EventBus()

        class FakeWS:
            def __init__(self):
                self.messages = []

            async def send_text(self, message):
                self.messages.append(message)

        ws = FakeWS()
        bus.connect_ws(ws)
        bus.emit("ws.event", {"key": "value"})

        # Let the sender task drain the queue.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert [json.loads(message) for message in ws.messages] == [
            {"type": "ws.event", "data": {"key": "value"}}
        ]
        bus.disconnect_ws(ws)

    @pytest.mark.asyncio
    async def test_send_ws_targets_single_client(self):
        bus = EventBus()

        class FakeWS:
            def __init__(self):
                self.messages = []

            async def send_text(self, message):
                self.messages.append(message)

        ws_a = FakeWS()
        ws_b = FakeWS()
        bus.connect_ws(ws_a)
        bus.connect_ws(ws_b)

        assert bus.send_ws(ws_a, '{"type": "snapshot"}') is True
        assert bus.send_ws(FakeWS(), '{"type": "snapshot"}') is False

        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert ws_a.messages == ['{"type": "snapshot"}']
        assert ws_b.messages == []
        bus.disconnect_ws(ws_a)
        bus.disconnect_ws(ws_b)

    @pytest.mark.asyncio
    async def test_ws_queue_overflow_drops_oldest(self):
        from server.events import emitter

        bus = EventBus()

        class StuckWS:
            async def send_text(self, message):
                await asyncio.Event().wait()  # never completes

        ws = StuckWS()
        bus.connect_ws(ws)
        client = bus._ws_clients[ws]

        total = emitter.WS_QUEUE_MAXSIZE + 5
        for i in range(total):
            bus.send_ws(ws, str(i))
        await asyncio.sleep(0)

        assert client.dropped >= 4
        assert client.queue.qsize() <= emitter.WS_QUEUE_MAXSIZE
        bus.disconnect_ws(ws)

    @pytest.mark.asyncio
    async def test_disconnect_cancels_sender_task(self):
        bus = EventBus()

        class FakeWS:
            async def send_text(self, message):
                pass

        ws = FakeWS()
        bus.connect_ws(ws)
        bus.send_ws(ws, "hello")
        client = bus._ws_clients[ws]
        assert client.sender is not None

        bus.disconnect_ws(ws)
        await asyncio.sleep(0)
        assert client.sender.cancelled() or client.sender.done()
        assert ws not in bus._ws_clients

    def test_disconnect_nonexistent_ws(self):
        bus = EventBus()

        class FakeWS:
            pass

        # Should not raise
        bus.disconnect_ws(FakeWS())


class TestDefaultHandlers:
    def test_setup_registers_handlers(self):
        bus = EventBus()
        setup_default_handlers(bus)
        # Spot-check that key events have handlers
        assert len(bus._handlers.get("track.generated", [])) >= 1
        assert len(bus._handlers.get("buffer.low", [])) >= 1
        assert len(bus._handlers.get("provider.error", [])) >= 1

    def test_provider_error_tracking(self):
        _provider_state["music"] = "unknown"
        _on_provider_error("provider.error", {"provider": "music", "error": "timeout"})
        assert get_provider_state()["music"] == "error"

    def test_provider_recovery_tracking(self):
        _provider_state["music"] = "error"
        _on_provider_recovered("provider.recovered", {"provider": "music"})
        assert get_provider_state()["music"] == "ok"
