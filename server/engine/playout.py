"""Playout interface managing communication with Liquidsoap.

Communicates with Liquidsoap via its telnet interface to queue tracks,
get playback status, skip items, and toggle the live caller/recorder.

Command inventory (verified against the Liquidsoap 2.2.5 reference):
- ``request.queue(id="queue")`` registers: ``queue.push``, ``queue.queue``,
  ``queue.skip``, ``queue.flush_and_skip``.
- Outputs created with ``register_telnet=true`` (the default) register
  output-level commands under their id: ``<id>.skip``, ``<id>.metadata``,
  ``<id>.remaining``, ``<id>.start``, ``<id>.stop``, ``<id>.status``.
  station.liq gives the Icecast output ``id="radio_out"`` and the file
  recorder ``id="recorder"``.

Now-playing metadata is passed at queue time via ``annotate:`` URIs and
flows to Icecast through the normal ICY metadata path.
"""

import asyncio
import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Matches the "--- 3 ---" separators in output-level metadata replies.
_METADATA_BLOCK_SEPARATOR = re.compile(r"^--- \d+ ---$")


class PlayoutInterface:
    """Manages the playout queue and communicates with Liquidsoap via telnet.

    Uses Liquidsoap v2.2.x telnet protocol. The request.queue source is
    named "queue" in station.liq, so queue commands target "queue.*";
    output-level commands target "radio_out.*" (the Icecast output id).

    Args:
        host: Liquidsoap telnet host.
        port: Liquidsoap telnet port.
    """

    def __init__(self, host: str = "liquidsoap", port: int = 1234) -> None:
        self._host = host
        self._port = port
        self._connected = False

    async def wait_until_ready(self, timeout: float = 30.0, interval: float = 1.0) -> bool:
        """Wait for Liquidsoap's telnet interface to accept connections.

        Polls with a version command until Liquidsoap responds or timeout
        is reached. Should be called before the first queue operation.

        Args:
            timeout: Maximum seconds to wait.
            interval: Seconds between retries.

        Returns:
            True if Liquidsoap is ready, False if timeout was reached.
        """
        deadline = time.monotonic() + timeout
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            response = await self._send_command("version")
            if response and not self._is_error_reply(response):
                logger.info(
                    "Liquidsoap ready (attempt %d): %s",
                    attempt,
                    response.strip()[:60],
                )
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(interval, remaining))

        logger.warning(
            "Liquidsoap not ready after %.0fs (%d attempts)", timeout, attempt
        )
        return False

    def _to_container_path(self, filepath: str) -> str:
        """Convert a local filepath to the Liquidsoap container path.

        Liquidsoap runs in Docker with the audio directory mounted at /audio/.
        Local paths like ./audio/tracks/foo.wav or D:/proj/audio/tracks/foo.wav
        need to become /audio/tracks/foo.wav inside the container.

        Args:
            filepath: Local path to an audio file.

        Returns:
            The equivalent path inside the Liquidsoap container.
        """
        normalized = str(Path(filepath).resolve()).replace("\\", "/")
        # Find the /audio/ segment and keep everything from there
        marker = "/audio/"
        idx = normalized.find(marker)
        if idx != -1:
            return normalized[idx:]
        # Fallback: if path doesn't contain /audio/, send as-is
        logger.warning("Path does not contain /audio/ segment: %s", filepath)
        return normalized

    @staticmethod
    def _escape_annotation(value: str) -> str:
        """Escape a metadata value for use inside an annotate: URI.

        Values are always emitted inside double quotes, where commas and
        colons are literal; only backslashes and double quotes need escaping.

        Args:
            value: Raw metadata value.

        Returns:
            The escaped value, safe to embed between double quotes.
        """
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _is_error_reply(response: str | None) -> bool:
        """Check whether a Liquidsoap telnet reply signals failure.

        Liquidsoap replies to unknown or failing commands with a line
        starting with "ERROR" (e.g. 'ERROR: unknown command, type "help"
        to get a list of commands.') before the END terminator.

        Args:
            response: The reply from _send_command, or None on
                connection failure.

        Returns:
            True if the reply is missing or contains an error line.
        """
        if response is None:
            return True
        return any(
            line.strip().startswith("ERROR") for line in response.splitlines()
        )

    async def _send_command(self, command: str) -> str | None:
        """Send a command to Liquidsoap via telnet and return the response.

        Opens a new connection per command (Liquidsoap telnet is stateless).
        Reads until the END marker that Liquidsoap sends after each response.
        Every network operation is bounded by a timeout so a hung Liquidsoap
        cannot stall the scheduler, and the socket is always closed.

        Args:
            command: The Liquidsoap telnet command to send.

        Returns:
            The response string from Liquidsoap (may be empty), or None
            if the connection failed or no reply arrived at all.
        """
        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=5.0,
            )
            writer.write(f"{command}\r\n".encode())
            await asyncio.wait_for(writer.drain(), timeout=5.0)

            # Read response until END marker or timeout
            response_lines: list[str] = []
            got_any = False
            try:
                while True:
                    line = await asyncio.wait_for(reader.readline(), timeout=3.0)
                    if not line:
                        break
                    got_any = True
                    decoded = line.decode().strip()
                    if decoded == "END":
                        break
                    response_lines.append(decoded)
            except asyncio.TimeoutError:
                # Keep any partial reply; a totally silent server is a failure.
                if not got_any:
                    raise

            self._connected = True
            return "\n".join(response_lines)

        except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as exc:
            self._connected = False
            logger.debug(
                "Liquidsoap connection failed (%s:%d): %s", self._host, self._port, exc
            )
            return None
        finally:
            if writer is not None:
                try:
                    writer.write(b"quit\r\n")
                except Exception:
                    pass
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
                except Exception:
                    pass

    async def queue_track(
        self, filepath: str, *, title: str | None = None, artist: str | None = None
    ) -> bool:
        """Add a track to the Liquidsoap request queue.

        Uses the "queue.push" command which accepts a URI. When title or
        artist are given they are attached via the annotate: protocol so
        the metadata reaches Icecast through the normal ICY path.

        Args:
            filepath: Path to the audio file to queue.
            title: Optional track title for stream metadata.
            artist: Optional artist name for stream metadata.

        Returns:
            True if the track was successfully queued.
        """
        uri = self._to_container_path(filepath)
        annotations: list[str] = []
        if title is not None:
            annotations.append(f'title="{self._escape_annotation(title)}"')
        if artist is not None:
            annotations.append(f'artist="{self._escape_annotation(artist)}"')
        if annotations:
            uri = f"annotate:{','.join(annotations)}:{uri}"

        response = await self._send_command(f"queue.push {uri}")
        if self._is_error_reply(response):
            logger.warning("Failed to queue track: %s (%s)", filepath, response)
            return False
        logger.info("Queued track: %s (rid: %s)", filepath, response.strip()[:20])
        return True

    async def queue_break(self, filepath: str, *, title: str | None = None) -> bool:
        """Add a DJ break audio file to the playout queue.

        Tags the request with liq_cross_duration=0 so Liquidsoap skips
        crossfade for this item, preventing the DJ speech from being
        cut short by an early fade-out into the next track. An optional
        title is attached for stream metadata.

        Args:
            filepath: Path to the DJ break audio file.
            title: Optional break title for stream metadata.

        Returns:
            True if the break was successfully queued.
        """
        uri = self._to_container_path(filepath)
        annotations = ['liq_cross_duration="0"', 'type="dj_break"']
        if title is not None:
            annotations.append(f'title="{self._escape_annotation(title)}"')
        annotated = f"annotate:{','.join(annotations)}:{uri}"

        response = await self._send_command(f"queue.push {annotated}")
        if self._is_error_reply(response):
            logger.warning("Failed to queue DJ break: %s (%s)", filepath, response)
            return False
        logger.info("Queued DJ break: %s (rid: %s)", filepath, response.strip()[:20])
        return True

    async def skip(self) -> bool:
        """Skip the currently playing item.

        Prefers the output-level "radio_out.skip" (skips whatever is on
        air, including fallback audio); falls back to "queue.skip" if the
        output command is unavailable.

        Returns:
            True if a skip command was acknowledged without error.
        """
        response = await self._send_command("radio_out.skip")
        if not self._is_error_reply(response):
            logger.info("Skip requested via radio_out.skip (response: %s)", response[:50])
            return True

        logger.debug("radio_out.skip failed (%s); trying queue.skip", response)
        response = await self._send_command("queue.skip")
        if not self._is_error_reply(response):
            logger.info("Skip requested via queue.skip (response: %s)", response[:50])
            return True

        logger.warning("Skip failed (response: %s)", response)
        return False

    async def get_status(self) -> dict:
        """Get the current playout status from Liquidsoap.

        Returns:
            A dict with current playback state, remaining time, and metadata.
        """
        if not self._connected:
            await self._send_command("version")

        # Remaining time on the item currently on air (output-level command).
        remaining_raw = await self._send_command("radio_out.remaining")
        remaining: float | None = None
        if remaining_raw and not self._is_error_reply(remaining_raw):
            try:
                # Reply is a float in seconds, or "(undef)" when unknown.
                remaining = float(remaining_raw.strip())
            except ValueError:
                remaining = None

        # Get current metadata
        metadata = await self._get_current_metadata()

        return {
            "status": "playing" if self._connected else "offline",
            "connected": self._connected,
            "remaining": remaining,
            "metadata": metadata,
            "current_title": metadata.get("title"),
        }

    async def _get_current_metadata(self) -> dict:
        """Fetch current track metadata from Liquidsoap.

        Uses the output-level "radio_out.metadata" command, which returns
        the recent metadata history as blocks separated by "--- N ---"
        lines (most recent block last). Only the latest block is returned.

        Returns:
            A dict of metadata key-value pairs (empty on failure).
        """
        response = await self._send_command("radio_out.metadata")
        if not response or self._is_error_reply(response):
            return {}

        blocks: list[dict] = [{}]
        for line in response.split("\n"):
            stripped = line.strip()
            if _METADATA_BLOCK_SEPARATOR.match(stripped):
                blocks.append({})
                continue
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                blocks[-1][key.strip()] = value.strip().strip('"')

        for block in reversed(blocks):
            if block:
                return block
        return {}

    async def get_now_playing_file(self) -> str | None:
        """Return the absolute path of the file currently on air.

        Reads the custom ``nowplaying.file`` telnet command registered in
        station.liq, which reflects the file the ``on_track`` handler last
        saw (captured before the crossfade so the per-request ``filename``
        metadata is preserved). This is what is ACTUALLY airing, as opposed
        to what was last pushed to the queue.

        Returns:
            The on-air file path, or None if unknown/empty or on failure.
        """
        response = await self._send_command("nowplaying.file")
        if not response or self._is_error_reply(response):
            return None
        path = response.strip()
        if not path or path == "unknown":
            return None
        return path

    async def is_alive(self) -> bool:
        """Check if Liquidsoap is responding to telnet commands.

        Returns:
            True if Liquidsoap responds to the version command.
        """
        response = await self._send_command("version")
        alive = bool(response) and not self._is_error_reply(response)
        self._connected = alive
        return alive

    async def get_queue_length(self) -> int:
        """Get the number of items waiting in the Liquidsoap queue.

        Returns:
            Number of queued request IDs, or 0 if unable to determine.
        """
        response = await self._send_command("queue.queue")
        if not response or self._is_error_reply(response):
            return 0
        # Response is space-separated request IDs
        items = response.strip().split()
        return len([item for item in items if item.strip()])

    async def start_recording(self) -> bool:
        """Start the local stream recording output in Liquidsoap.

        Sends the custom "recorder.set true" command registered in
        station.liq, which enables the gated source feeding the file
        output (an output.file registers no start/stop telnet commands).

        Returns:
            True if Liquidsoap confirmed the flag was set.
        """
        response = await self._send_command("recorder.set true")
        ok = (
            not self._is_error_reply(response)
            and response is not None
            and response.strip().startswith("OK")
        )
        if ok:
            logger.info("Recording started (response: %s)", response.strip()[:50])
        else:
            logger.warning("Failed to start recording (response: %s)", response)
        return ok

    async def stop_recording(self) -> bool:
        """Stop the local stream recording output in Liquidsoap.

        Returns:
            True if Liquidsoap confirmed the flag was cleared.
        """
        response = await self._send_command("recorder.set false")
        ok = (
            not self._is_error_reply(response)
            and response is not None
            and response.strip().startswith("OK")
        )
        if ok:
            logger.info("Recording stopped (response: %s)", response.strip()[:50])
        else:
            logger.warning("Failed to stop recording (response: %s)", response)
        return ok

    async def is_recording(self) -> bool:
        """Check if the recorder output is currently active.

        Returns:
            True if the recorder is running ("recorder.status" replies "on").
        """
        response = await self._send_command("recorder.status")
        if not response or self._is_error_reply(response):
            return False
        return response.strip().lower().startswith("on")
