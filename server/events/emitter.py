"""Simple event bus for decoupled communication between components.

Supports both sync and async handlers, plus WebSocket broadcast.

WebSocket delivery is serialized per client: each connection gets a bounded
queue drained by a single sender task, so concurrent emits never interleave
frames on the same socket. When a queue overflows, the oldest message is
dropped and counted.
"""

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Maximum messages buffered per WebSocket client before dropping the oldest.
WS_QUEUE_MAXSIZE = 100


class _WSClient:
    """Per-connection send state: a bounded queue and its sender task."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=WS_QUEUE_MAXSIZE)
        self.sender: asyncio.Task[None] | None = None
        self.dropped: int = 0


class EventBus:
    """A publish-subscribe event bus with WebSocket broadcast support.

    Components can register handlers for named events and emit events
    to notify all registered handlers. Connected WebSocket clients
    receive all events in real time.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = {}
        self._ws_clients: dict[WebSocket, _WSClient] = {}
        # Strong references to fire-and-forget tasks so the event loop
        # cannot garbage-collect them mid-flight.
        self._tasks: set[asyncio.Task[Any]] = set()

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
                    self._spawn_handler_task(event, result)
            except Exception:
                logger.exception("Error in handler for event '%s'", event)

        # Broadcast to WebSocket clients
        self._broadcast_ws(event, data)

    def _spawn_handler_task(
        self, event: str, coro: Coroutine[Any, Any, Any]
    ) -> None:
        """Schedule an async handler, keeping a strong reference to the task.

        Without a running event loop the coroutine is dropped with a warning:
        running it via ``asyncio.run`` would execute on a foreign loop, which
        is unsafe for anything holding loop-bound resources.

        Args:
            event: The event name (for error logging).
            coro: The handler coroutine to schedule.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "No running event loop; dropping async handler for event '%s'",
                event,
            )
            coro.close()
            return

        task = loop.create_task(coro)
        self._tasks.add(task)

        def _done(t: asyncio.Task[Any], event: str = event) -> None:
            self._tasks.discard(t)
            self._log_async_handler_error(event, t)

        task.add_done_callback(_done)

    def _broadcast_ws(self, event: str, data: dict[str, Any]) -> None:
        """Queue an event message for all connected WebSocket clients.

        Args:
            event: The event name.
            data: The event data payload.
        """
        if not self._ws_clients:
            return

        message = json.dumps({"type": event, "data": data}, default=str)
        for client in list(self._ws_clients.values()):
            self._enqueue(client, message)

    def send_ws(self, ws: WebSocket, message: str) -> bool:
        """Queue a message for a single connected client.

        All writes to a socket must go through this per-client queue so they
        never interleave with broadcast sends.

        Args:
            ws: A WebSocket previously registered via :meth:`connect_ws`.
            message: The JSON message string to send.

        Returns:
            True if the message was queued, False if the client is unknown.
        """
        client = self._ws_clients.get(ws)
        if client is None:
            return False
        self._enqueue(client, message)
        return True

    def _enqueue(self, client: _WSClient, message: str) -> None:
        """Put a message on a client queue, dropping the oldest on overflow.

        Args:
            client: The per-connection send state.
            message: The JSON message string.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "No running event loop; dropping WebSocket message"
            )
            return

        self._ensure_sender(client)
        try:
            client.queue.put_nowait(message)
        except asyncio.QueueFull:
            try:
                client.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            client.dropped += 1
            logger.warning(
                "WebSocket send queue full; dropped oldest message "
                "(total dropped: %d)",
                client.dropped,
            )
            try:
                client.queue.put_nowait(message)
            except asyncio.QueueFull:
                client.dropped += 1

    def _ensure_sender(self, client: _WSClient) -> None:
        """Start the client's sender task if it is not already running.

        Created lazily (rather than in :meth:`connect_ws`) so clients can be
        registered from contexts without a running event loop.

        Args:
            client: The per-connection send state.
        """
        if client.sender is not None and not client.sender.done():
            return
        client.sender = asyncio.get_running_loop().create_task(
            self._sender_loop(client)
        )
        self._tasks.add(client.sender)
        client.sender.add_done_callback(self._tasks.discard)

    async def _sender_loop(self, client: _WSClient) -> None:
        """Drain a client's queue, sending messages one at a time.

        Args:
            client: The per-connection send state.
        """
        while True:
            message = await client.queue.get()
            try:
                await client.ws.send_text(message)
            except Exception:
                self.disconnect_ws(client.ws)
                return

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
        self._ws_clients[ws] = _WSClient(ws)
        logger.info("WebSocket client connected (total: %d)", len(self._ws_clients))

    def disconnect_ws(self, ws: WebSocket) -> None:
        """Remove a WebSocket client and cancel its sender task.

        Args:
            ws: The WebSocket connection to remove.
        """
        client = self._ws_clients.pop(ws, None)
        if client is not None and client.sender is not None:
            client.sender.cancel()
        logger.info(
            "WebSocket client disconnected (total: %d)", len(self._ws_clients)
        )


event_bus = EventBus()
