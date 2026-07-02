"""Simple event bus for decoupled communication between components.

Supports both sync and async handlers, plus WebSocket broadcast.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class EventBus:
    """A publish-subscribe event bus with WebSocket broadcast support.

    Components can register handlers for named events and emit events
    to notify all registered handlers. Connected WebSocket clients
    receive all events in real time.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = {}
        self._ws_clients: list[WebSocket] = []

    def on(self, event: str, handler: Callable) -> None:
        """Register a handler for the given event name.

        Args:
            event: The event name to listen for.
            handler: A callable invoked when the event is emitted.
        """
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(handler)

    def emit(self, event: str, data: dict[str, Any] | None = None) -> None:
        """Emit an event, calling all registered handlers and broadcasting to WS.

        Args:
            event: The event name to emit.
            data: A dictionary of event data passed to each handler.
        """
        if data is None:
            data = {}

        handlers = self._handlers.get(event, [])
        for handler in handlers:
            try:
                result = handler(event, data)
                if asyncio.iscoroutine(result):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        asyncio.run(result)
                    else:
                        task = loop.create_task(result)
                        task.add_done_callback(
                            lambda task, event=event: self._log_async_handler_error(
                                event, task
                            )
                        )
            except Exception:
                logger.exception("Error in handler for event '%s'", event)

        # Broadcast to WebSocket clients
        self._broadcast_ws(event, data)

    def _broadcast_ws(self, event: str, data: dict[str, Any]) -> None:
        """Send event to all connected WebSocket clients.

        Args:
            event: The event name.
            data: The event data payload.
        """
        if not self._ws_clients:
            return

        message = json.dumps({"type": event, "data": data}, default=str)

        for ws in list(self._ws_clients):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(self._safe_ws_send(ws, message))
            else:
                loop.create_task(self._safe_ws_send(ws, message))

    async def _safe_ws_send(self, ws: WebSocket, message: str) -> None:
        """Send a message to a WebSocket, removing on failure.

        Args:
            ws: The WebSocket connection.
            message: The JSON message string.
        """
        try:
            await ws.send_text(message)
        except Exception:
            if ws in self._ws_clients:
                self._ws_clients.remove(ws)

    @staticmethod
    def _log_async_handler_error(event: str, task: asyncio.Task[Any]) -> None:
        """Log exceptions from scheduled async event handlers."""
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error in async handler for event '%s'", event)

    def connect_ws(self, ws: WebSocket) -> None:
        """Register a WebSocket client for event broadcasts.

        Args:
            ws: The WebSocket connection to add.
        """
        self._ws_clients.append(ws)
        logger.info("WebSocket client connected (total: %d)", len(self._ws_clients))

    def disconnect_ws(self, ws: WebSocket) -> None:
        """Remove a WebSocket client from broadcasts.

        Args:
            ws: The WebSocket connection to remove.
        """
        if ws in self._ws_clients:
            self._ws_clients.remove(ws)
        logger.info(
            "WebSocket client disconnected (total: %d)", len(self._ws_clients)
        )


event_bus = EventBus()
