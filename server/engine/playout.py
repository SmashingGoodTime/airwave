"""Playout interface managing communication with Liquidsoap.

Communicates with Liquidsoap via its telnet interface to queue tracks,
get playback status, skip items, and update stream metadata.
"""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PlayoutInterface:
    """Manages the playout queue and communicates with Liquidsoap via telnet.

    Uses Liquidsoap v2.2.x telnet protocol. The request.queue source is
    named "queue" in station.liq, so commands target "queue.*".

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
        import time

        deadline = time.monotonic() + timeout
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            response = await self._send_command("version")
            if response:
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

    async def _send_command(self, command: str) -> str:
        """Send a command to Liquidsoap via telnet and return the response.

        Opens a new connection per command (Liquidsoap telnet is stateless).
        Reads until the END marker that Liquidsoap sends after each response.

        Args:
            command: The Liquidsoap telnet command to send.

        Returns:
            The response string from Liquidsoap, or empty string on failure.
        """
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=5.0,
            )
            writer.write(f"{command}\r\n".encode())
            await writer.drain()

            # Read response until END marker or timeout
            response_lines = []
            try:
                while True:
                    line = await asyncio.wait_for(reader.readline(), timeout=3.0)
                    if not line:
                        break
                    decoded = line.decode().strip()
                    if decoded == "END":
                        break
                    response_lines.append(decoded)
            except asyncio.TimeoutError:
                pass

            writer.write(b"quit\r\n")
            await writer.drain()
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            self._connected = True
            return "\n".join(response_lines)

        except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as exc:
            self._connected = False
            logger.debug("Liquidsoap connection failed (%s:%d): %s", self._host, self._port, exc)
            return ""

    async def queue_track(self, filepath: str) -> bool:
        """Add a track to the Liquidsoap request queue.

        Uses the "queue.push" command which accepts a URI (file path).
        Converts local paths to container paths since Liquidsoap runs
        in Docker with audio mounted at /audio/.

        Args:
            filepath: Path to the audio file to queue.

        Returns:
            True if the track was successfully queued.
        """
        abs_path = self._to_container_path(filepath)
        response = await self._send_command(f"queue.push {abs_path}")

        if response:
            logger.info("Queued track: %s (rid: %s)", filepath, response.strip()[:20])
            return True
        else:
            logger.warning("Failed to queue track: %s", filepath)
            return False

    async def queue_break(self, filepath: str) -> bool:
        """Add a DJ break audio file to the playout queue.

        Tags the request with liq_cross_duration=0 so Liquidsoap skips
        crossfade for this item, preventing the DJ speech from being
        cut short by an early fade-out into the next track.

        Args:
            filepath: Path to the DJ break audio file.

        Returns:
            True if the break was successfully queued.
        """
        abs_path = self._to_container_path(filepath)
        annotated = f"annotate:liq_cross_duration=\"0\",type=\"dj_break\":{abs_path}"
        response = await self._send_command(f"queue.push {annotated}")

        if response:
            logger.info("Queued DJ break: %s (rid: %s)", filepath, response.strip()[:20])
            return True
        else:
            logger.warning("Failed to queue DJ break: %s", filepath)
            return False

    async def skip(self) -> bool:
        """Skip the currently playing item.

        Returns:
            True if the skip command was acknowledged.
        """
        response = await self._send_command("radio.skip")
        logger.info("Skip requested (response: %s)", response[:50] if response else "none")
        return bool(response) or self._connected

    async def get_status(self) -> dict:
        """Get the current playout status from Liquidsoap.

        Returns:
            A dict with current playback state, remaining time, and metadata.
        """
        if not self._connected:
            await self._send_command("version")

        # Get remaining time on current track
        remaining_raw = await self._send_command("radio.remaining")
        remaining = None
        if remaining_raw:
            try:
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

        Returns:
            A dict of metadata key-value pairs.
        """
        response = await self._send_command("queue.metadata")
        metadata = {}
        if response:
            for line in response.split("\n"):
                if "=" in line:
                    key, _, value = line.partition("=")
                    metadata[key.strip()] = value.strip().strip('"')
        return metadata

    async def update_metadata(self, title: str, artist: str = "AI Radio") -> bool:
        """Update the stream metadata shown to listeners.

        Liquidsoap v2.2 uses the "metadata.update" command on the output.

        Args:
            title: The track or break title.
            artist: The artist name (defaults to station name).

        Returns:
            True if metadata was updated successfully.
        """
        # Escape quotes in metadata values
        safe_title = title.replace('"', '\\"')
        safe_artist = artist.replace('"', '\\"')

        # Insert metadata into the queue source
        response = await self._send_command(
            f'queue.insert 0 annotate:title="{safe_title}",artist="{safe_artist}":empty'
        )
        # The metadata update via annotate may not return a useful response,
        # but the on_metadata handler in station.liq will pick it up
        return self._connected

    async def is_alive(self) -> bool:
        """Check if Liquidsoap is responding to telnet commands.

        Returns:
            True if Liquidsoap responds to the version command.
        """
        response = await self._send_command("version")
        alive = bool(response)
        self._connected = alive
        return alive

    async def get_queue_length(self) -> int:
        """Get the number of items waiting in the Liquidsoap queue.

        Returns:
            Number of queued request IDs, or 0 if unable to determine.
        """
        response = await self._send_command("queue.queue")
        if not response or response.strip() == "":
            return 0
        # Response is space-separated request IDs
        items = response.strip().split()
        return len([item for item in items if item.strip()])

    async def start_live_input(self) -> bool:
        """Enable the harbor input for live caller audio.

        Activates the caller input source in Liquidsoap so that
        audio streamed to the harbor port takes priority.

        Returns:
            True if the command was acknowledged.
        """
        response = await self._send_command("caller.start")
        logger.info("Live input started (response: %s)", response[:50] if response else "none")
        return self._connected

    async def stop_live_input(self) -> bool:
        """Disable the harbor input, reverting to normal queue playout.

        Returns:
            True if the command was acknowledged.
        """
        response = await self._send_command("caller.stop")
        logger.info("Live input stopped (response: %s)", response[:50] if response else "none")
        return self._connected

    async def start_recording(self) -> bool:
        """Start the local stream recording output in Liquidsoap.

        Returns:
            True if the command was acknowledged.
        """
        response = await self._send_command("recorder.start")
        logger.info("Recording started (response: %s)", response[:50] if response else "none")
        return self._connected

    async def stop_recording(self) -> bool:
        """Stop the local stream recording output in Liquidsoap.

        Returns:
            True if the command was acknowledged.
        """
        response = await self._send_command("recorder.stop")
        logger.info("Recording stopped (response: %s)", response[:50] if response else "none")
        return self._connected

    async def is_recording(self) -> bool:
        """Check if the recorder output is currently active.

        Returns:
            True if the recorder is running.
        """
        response = await self._send_command("recorder.status")
        return "on" in response.lower() if response else False

    async def get_secondary_queue_length(self) -> int:
        """Get the number of items in the secondary queue (pending requests).

        Returns:
            Number of secondary queue items.
        """
        response = await self._send_command("queue.secondary_queue")
        if not response or response.strip() == "":
            return 0
        items = response.strip().split()
        return len([item for item in items if item.strip()])
