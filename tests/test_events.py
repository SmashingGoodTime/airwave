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

    def test_async_handler_runs_without_running_loop(self):
        bus = EventBus()
        received = []

        async def async_handler(event, data):
            received.append((event, data))

        bus.on("async.event", async_handler)
        bus.emit("async.event", {"key": "value"})

        assert received == [("async.event", {"key": "value"})]

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

    def test_ws_broadcast_runs_without_running_loop(self):
        bus = EventBus()

        class FakeWS:
            def __init__(self):
                self.messages = []

            async def send_text(self, message):
                self.messages.append(message)

        ws = FakeWS()
        bus.connect_ws(ws)
        bus.emit("ws.event", {"key": "value"})

        assert [json.loads(message) for message in ws.messages] == [
            {"type": "ws.event", "data": {"key": "value"}}
        ]

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
