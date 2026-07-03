"""SunoAPI.org music generation provider.

Uses the third-party SunoAPI.org service to generate music tracks
from text prompts via Suno's V5 model. Each API call produces two
songs; the provider picks the first and saves it locally.

See: https://docs.sunoapi.org
"""

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx

from server.providers.base import MusicProvider
from server.utils.rate_limiter import (
    NonRetryableError,
    RateLimiter,
    retry_with_backoff,
)

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
POLL_TIMEOUT = 300  # 5 minutes max wait (wall clock)
MAX_POLL_FAILURES = 5  # consecutive transient poll failures tolerated


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

        Only the submit call is wrapped in a resubmitting retry — each
        submission is a paid generation, so poll and download failures
        retry against the SAME task instead of resubmitting.

        Args:
            prompt: Text description of the desired music style.
            duration: Target duration in seconds (informational; Suno
                controls actual length).

        Returns:
            A dict with keys: task_id, clip_id, filepath, title,
            duration, metadata.

        Raises:
            RuntimeError: If generation fails after retries.
            NonRetryableError: On auth/credit failures that retrying
                cannot fix.
        """
        # --- Submit (resubmit retry: this is the only paid call) ---
        task_id = await retry_with_backoff(
            self._submit_generation,
            prompt,
            max_retries=2,
            base_delay=30.0,
            max_delay=120.0,
            rate_limiter=self._rate_limiter,
            operation_name="suno_music_submit",
        )

        # --- Poll (retries transient failures internally, same task_id) ---
        song = await self._poll_until_complete(task_id)

        # --- Download (own small retry; a failure here must never resubmit) ---
        return await retry_with_backoff(
            self._download_song,
            song,
            task_id,
            prompt,
            max_retries=2,
            base_delay=5.0,
            max_delay=30.0,
            operation_name="suno_music_download",
        )

    async def _submit_generation(self, prompt: str) -> str:
        """Submit a generation request and return its task ID.

        Args:
            prompt: Style description for the music.

        Returns:
            The Suno task ID string.

        Raises:
            NonRetryableError: On auth failures or insufficient credits.
            RuntimeError: On transient submission failures.
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

        response = await client.post("/api/v1/generate", json=payload)

        if response.status_code == 429:
            # SunoAPI.org uses 429 for insufficient credits — retrying
            # cannot fix an empty balance.
            logger.warning("Suno: insufficient credits")
            raise NonRetryableError("Suno: insufficient credits (429)")

        if response.status_code == 430:
            logger.warning("Suno: rate limited (430)")
            raise RuntimeError("Suno: call frequency too high (430)")

        if response.status_code in (400, 401, 403):
            raise NonRetryableError(
                f"Suno submit rejected: HTTP {response.status_code}"
            )

        response.raise_for_status()
        submit_data = response.json()

        if submit_data.get("code") != 200:
            raise RuntimeError(
                f"Suno submit error: {submit_data.get('msg', 'unknown')}"
            )

        task_id = (submit_data.get("data") or {}).get("taskId", "")
        if not task_id:
            raise RuntimeError("Suno submit response contained no taskId")

        logger.info("Suno task submitted: %s", task_id)
        return task_id

    async def _download_song(
        self, song: dict, task_id: str, prompt: str
    ) -> dict:
        """Download a completed song and build the provider result dict.

        Args:
            song: Song dict from the completed poll response.
            task_id: The Suno generation task ID.
            prompt: The original generation prompt.

        Returns:
            A dict with generation result metadata and file path.

        Raises:
            RuntimeError: If no audio URL is present or the download fails.
        """
        audio_url = song.get("audioUrl") or song.get("audio_url")
        if not audio_url:
            raise RuntimeError("Suno returned no audio URL")

        clip_id = uuid.uuid4().hex[:12]
        filepath = self._audio_dir / f"suno_{clip_id}.mp3"

        # The audio URL points at a CDN, not the Suno API — use a bare
        # client so the API Bearer token is never sent to a third party.
        async with self._download_client() as dl_client:
            async with dl_client.stream("GET", audio_url) as dl:
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

    def _download_client(self) -> httpx.AsyncClient:
        """Create a bare HTTP client for downloading generated audio.

        The client carries no Authorization header so the API key is never
        leaked to the CDN host serving the audio file.

        Returns:
            A fresh httpx.AsyncClient intended for single-use download.
        """
        return httpx.AsyncClient(timeout=60.0, follow_redirects=True)

    async def _poll_until_complete(self, task_id: str) -> dict:
        """Poll the Suno API until generation completes or times out.

        Transient poll failures (network errors, 5xx) are retried against
        the same task ID up to ``MAX_POLL_FAILURES`` consecutive times —
        polling must never resubmit the paid generation. The deadline is
        wall-clock so slow responses cannot stretch the cap.

        Args:
            task_id: The generation task ID.

        Returns:
            The first song dict from the completed response.

        Raises:
            RuntimeError: On timeout or generation failure.
            NonRetryableError: If polling is rejected for auth reasons.
        """
        client = self._get_client()
        deadline = time.monotonic() + POLL_TIMEOUT
        consecutive_failures = 0

        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL)

            try:
                resp = await client.get(
                    "/api/v1/generate/record-info",
                    params={"taskId": task_id},
                )
                if resp.status_code in (400, 401, 403):
                    raise NonRetryableError(
                        f"Suno poll rejected: HTTP {resp.status_code}"
                    )
                resp.raise_for_status()
                data = resp.json()
            except NonRetryableError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                consecutive_failures += 1
                if consecutive_failures >= MAX_POLL_FAILURES:
                    raise RuntimeError(
                        f"Suno poll failed {consecutive_failures} consecutive "
                        f"times for task {task_id}"
                    ) from exc
                logger.warning(
                    "Suno poll attempt failed for task %s (%d/%d): %s",
                    task_id,
                    consecutive_failures,
                    MAX_POLL_FAILURES,
                    exc,
                )
                continue

            consecutive_failures = 0

            if data.get("code") != 200:
                raise RuntimeError(
                    f"Suno poll error: {data.get('msg', 'unknown')}"
                )

            # data can be null while the task is pending/unknown
            task_data = data.get("data") or {}
            status = task_data.get("status", "")
            logger.debug("Suno task %s status: %s", task_id, status)

            if status == "SUCCESS":
                suno_data = (task_data.get("response") or {}).get(
                    "sunoData"
                ) or []
                if not suno_data:
                    raise RuntimeError("Suno returned SUCCESS but no songs")
                return suno_data[0]

            if status in _ERROR_STATUSES:
                error_msg = task_data.get("errorMessage", status)
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

    async def aclose(self) -> None:
        """Close the underlying HTTP client and release its pool."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
