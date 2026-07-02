"""SunoAPI.org music generation provider.

Uses the third-party SunoAPI.org service to generate music tracks
from text prompts via Suno's V5 model. Each API call produces two
songs; the provider picks the first and saves it locally.

See: https://docs.sunoapi.org
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional

import httpx

from server.providers.base import MusicProvider
from server.utils.rate_limiter import RateLimiter, retry_with_backoff

logger = logging.getLogger(__name__)

SUNO_API_BASE = "https://api.sunoapi.org"
DEFAULT_MODEL = "V5_5"

# Statuses that mean the task is still in progress
_PENDING_STATUSES = {"PENDING", "TEXT_SUCCESS", "FIRST_SUCCESS"}
# Statuses that mean the task failed
_ERROR_STATUSES = {
    "CREATE_TASK_FAILED",
    "GENERATE_AUDIO_FAILED",
    "CALLBACK_EXCEPTION",
    "SENSITIVE_WORD_ERROR",
}

POLL_INTERVAL = 15  # seconds between status polls
POLL_TIMEOUT = 300  # 5 minutes max wait


class SunoMusicProvider(MusicProvider):
    """Music generation provider using the SunoAPI.org service.

    Sends a text prompt to Suno's music generation API, polls for
    completion, downloads the resulting audio, and saves it locally.

    Args:
        api_key: SunoAPI.org API key (Bearer token).
        audio_dir: Directory to save generated audio files.
        model: Suno model version to use.
    """

    def __init__(
        self,
        api_key: str,
        audio_dir: str = "./audio",
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._api_key = api_key
        self._audio_dir = Path(audio_dir) / "tracks"
        self._audio_dir.mkdir(parents=True, exist_ok=True)
        self._model = model
        self._client: Optional[httpx.AsyncClient] = None
        self._rate_limiter = RateLimiter(
            calls_per_minute=2,
            min_interval=30.0,
            name="suno_music",
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.

        Returns:
            An httpx.AsyncClient configured for the Suno API.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=SUNO_API_BASE,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=60.0,
            )
        return self._client

    async def generate(self, prompt: str, duration: int = 180) -> dict:
        """Generate a music track from a text prompt via Suno.

        Submits a generation request, polls until complete, downloads
        the audio file, and returns metadata matching the provider contract.

        Args:
            prompt: Text description of the desired music style.
            duration: Target duration in seconds (informational; Suno
                controls actual length).

        Returns:
            A dict with keys: task_id, clip_id, filepath, title,
            duration, metadata.

        Raises:
            RuntimeError: If generation fails after retries.
        """
        return await retry_with_backoff(
            self._generate_impl,
            prompt,
            duration,
            max_retries=2,
            base_delay=30.0,
            max_delay=120.0,
            rate_limiter=self._rate_limiter,
            operation_name="suno_music_generate",
        )

    async def _generate_impl(self, prompt: str, duration: int) -> dict:
        """Internal implementation: submit, poll, download.

        Args:
            prompt: Style description for the music.
            duration: Target length in seconds.

        Returns:
            A dict with generation result metadata and file path.
        """
        client = self._get_client()

        # Determine if instrumental from prompt hint
        # The music_buffer appends content policy suffix like
        # "Instrumental only, no vocals." to the prompt.
        instrumental = "instrumental" in prompt.lower()

        payload = {
            "prompt": prompt[:500],
            "customMode": False,
            "instrumental": instrumental,
            "model": self._model,
            "callBackUrl": "https://localhost/callback",
        }

        logger.info(
            "Submitting Suno generation: model=%s, prompt=%s",
            self._model,
            prompt[:80],
        )

        # --- Submit ---
        response = await client.post("/api/v1/generate", json=payload)

        if response.status_code == 429:
            logger.warning("Suno: insufficient credits")
            self._rate_limiter.record_error()
            raise RuntimeError("Suno: insufficient credits (429)")

        if response.status_code == 430:
            logger.warning("Suno: rate limited (430)")
            self._rate_limiter.record_error()
            raise RuntimeError("Suno: call frequency too high (430)")

        response.raise_for_status()
        submit_data = response.json()

        if submit_data.get("code") != 200:
            raise RuntimeError(
                f"Suno submit error: {submit_data.get('msg', 'unknown')}"
            )

        task_id = submit_data["data"]["taskId"]
        logger.info("Suno task submitted: %s", task_id)

        # --- Poll ---
        song = await self._poll_until_complete(client, task_id)

        # --- Download ---
        audio_url = song.get("audioUrl") or song.get("audio_url")
        if not audio_url:
            raise RuntimeError("Suno returned no audio URL")

        clip_id = uuid.uuid4().hex[:12]
        filepath = self._audio_dir / f"suno_{clip_id}.mp3"

        async with client.stream("GET", audio_url) as dl:
            dl.raise_for_status()
            with open(filepath, "wb") as f:
                async for chunk in dl.aiter_bytes(8192):
                    f.write(chunk)

        size_mb = filepath.stat().st_size / 1e6
        title = song.get("title", prompt[:60].strip())
        song_duration = song.get("duration", 0)

        logger.info(
            "Suno track saved: %s (%.2f MB, %.1fs)",
            filepath,
            size_mb,
            song_duration,
        )

        # Extract lyrics if available from the Suno response
        lyrics = song.get("lyric") or song.get("lyrics") or ""

        return {
            "task_id": task_id,
            "clip_id": clip_id,
            "filepath": str(filepath),
            "title": title,
            "duration": song_duration,
            "lyrics": lyrics,
            "metadata": {
                "provider": "suno",
                "clip_id": clip_id,
                "suno_id": song.get("id", ""),
                "prompt": prompt,
                "model": self._model,
                "tags": song.get("tags", ""),
            },
        }

    async def _poll_until_complete(
        self, client: httpx.AsyncClient, task_id: str
    ) -> dict:
        """Poll the Suno API until generation completes or times out.

        Args:
            client: HTTP client to use.
            task_id: The generation task ID.

        Returns:
            The first song dict from the completed response.

        Raises:
            RuntimeError: On timeout or generation failure.
        """
        elapsed = 0.0

        while elapsed < POLL_TIMEOUT:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

            resp = await client.get(
                "/api/v1/generate/record-info",
                params={"taskId": task_id},
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 200:
                raise RuntimeError(
                    f"Suno poll error: {data.get('msg', 'unknown')}"
                )

            status = data["data"].get("status", "")
            logger.debug("Suno task %s status: %s", task_id, status)

            if status == "SUCCESS":
                songs = (
                    data["data"]
                    .get("response", {})
                    .get("taskId", data["data"].get("response", {}))
                )
                # Navigate to the sunoData array
                suno_data = (
                    data["data"]
                    .get("response", {})
                    .get("sunoData", [])
                )
                if not suno_data:
                    raise RuntimeError("Suno returned SUCCESS but no songs")
                return suno_data[0]

            if status in _ERROR_STATUSES:
                error_msg = data["data"].get("errorMessage", status)
                raise RuntimeError(f"Suno generation failed: {error_msg}")

            if status not in _PENDING_STATUSES:
                logger.warning("Suno unknown status: %s", status)

        raise RuntimeError(
            f"Suno generation timed out after {POLL_TIMEOUT}s "
            f"for task {task_id}"
        )

    async def check_status(self) -> bool:
        """Check whether the Suno API is reachable and has credits.

        Calls the credit endpoint. Respects the circuit breaker.

        Returns:
            True if the provider is operational and has credits.
        """
        if self._rate_limiter.is_backing_off:
            logger.debug(
                "Suno health check skipped — %s",
                "circuit OPEN" if self._rate_limiter.circuit_open
                else "rate limiter backing off",
            )
            return False

        try:
            client = self._get_client()
            response = await client.get("/api/v1/generate/credit")
            if response.status_code == 200:
                data = response.json()
                credits = data.get("data", 0)
                if credits > 0:
                    self._rate_limiter.record_success()
                    return True
                logger.warning("Suno health check: 0 credits remaining")
                return False
            logger.warning(
                "Suno health check returned %d", response.status_code
            )
            self._rate_limiter.record_error()
            return False
        except Exception as exc:
            logger.warning("Suno health check failed: %s", exc)
            self._rate_limiter.record_error()
            return False
