"""Fish Audio TTS voice provider with rate limiting and retry.

Uses the Fish Audio API (https://docs.fish.audio) to render DJ scripts
to audio. Supports the s1 and s2-pro models, voice cloning via
reference_id, and WAV output.

See: https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech
"""

import logging
import uuid
from pathlib import Path
from typing import Optional

import httpx

from server.providers.base import VoiceProvider
from server.utils.rate_limiter import RateLimiter, retry_with_backoff

logger = logging.getLogger(__name__)

FISH_API_BASE = "https://api.fish.audio"
DEFAULT_MODEL = "s2-pro"

# Curated radio-style voices from Fish Audio
FISH_VOICES = [
    {
        "voice_id": "100b9bbcdc52442bb9a710a5c9ee1bf8",
        "name": "Raddo",
        "category": "radio",
    },
    {
        "voice_id": "1248b0526f4e40be8789dd1317a4cbfb",
        "name": "Dynamic Radio Host",
        "category": "radio",
        "description": "A dynamic and confident male voice, perfect for high-energy announcements and entertainment.",
    },
    {
        "voice_id": "190fab3282be4b97bf07c272c86814e2",
        "name": "Old Radio",
        "category": "vintage",
        "description": "A high-energy, authoritative tone characteristic of a classic Transatlantic radio announcer.",
    },
    {
        "voice_id": "3bbda400560042f2af147a4609e26646",
        "name": "GTA Radio Girl",
        "category": "radio",
        "description": "Radio girl from GTA V.",
    },
    {
        "voice_id": "46e6284b3eb0482cbc652c19f0fdbce3",
        "name": "Vintage Radio Announcer",
        "category": "vintage",
        "description": "A clear and confident voice perfect for product demonstrations and classic radio broadcasts.",
    },
    {
        "voice_id": "4f8243618f7a4cb8861023cf449fbff1",
        "name": "American Radio Host",
        "category": "radio",
        "description": "A warm and upbeat male voice, exuding enthusiasm and positivity with a smooth, engaging tone.",
    },
    {
        "voice_id": "79fe3bfec92e437dbeb7cd857115409d",
        "name": "After Morning Radio",
        "category": "radio",
        "description": "A professional and authoritative middle-aged male voice with a deep, resonant tone.",
    },
    {
        "voice_id": "cf3bd50df5234f8bbcfaaf83e92361c8",
        "name": "Adam Stone - Late Night Radio",
        "category": "radio",
    },
    {
        "voice_id": "9b75337d041e4afb9369ba0923522465",
        "name": "Horror Radio Voice",
        "category": "specialty",
        "description": "A mature male voice with an authoritative and serious tone, like a formal emergency broadcast narrator.",
    },
    {
        "voice_id": "af84a89658124562a6136d11fd7f6709",
        "name": "Radio Station Voice",
        "category": "radio",
        "description": "Good for radios and voice overs.",
    },
    {
        "voice_id": "c52d77b4262f44529f3889d690f0c899",
        "name": "Radio Shock Jockette/TV Hostess",
        "category": "radio",
        "description": "New York radio DJ with a talk show hostess vibe.",
    },
    {
        "voice_id": "ed028f4f70bc49828acac1cbd2af6b2c",
        "name": "Radio Broadcast Voice",
        "category": "radio",
    },
    {
        "voice_id": "f520b699bd4e41fab9fffe3a3916044a",
        "name": "Radio Voice Male",
        "category": "radio",
        "description": "A warm and sincere middle-aged male voice with a deep, smooth tone and a touch of raspiness.",
    },
]


class FishAudioVoiceProvider(VoiceProvider):
    """Voice synthesis provider using Fish Audio's TTS API.

    Renders DJ break scripts to speech audio using Fish Audio's cloud
    service. Supports hundreds of community voices and custom cloned
    voices via reference_id.

    Args:
        api_key: Fish Audio API key.
        audio_dir: Directory to save rendered audio files.
        model: Fish Audio model name (s1 or s2-pro).
    """

    def __init__(
        self,
        api_key: str,
        audio_dir: str = "./audio",
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._api_key = api_key
        self._audio_dir = Path(audio_dir) / "breaks"
        self._audio_dir.mkdir(parents=True, exist_ok=True)
        self._model = model
        self._client: Optional[httpx.AsyncClient] = None
        self._rate_limiter = RateLimiter(
            calls_per_minute=10, min_interval=2.0, name="fish_audio_tts"
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.

        Returns:
            An httpx.AsyncClient configured for the Fish Audio API.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=FISH_API_BASE,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        return self._client

    async def render(self, text: str, voice_config: dict) -> str:
        """Render text to speech using Fish Audio with retry.

        Args:
            text: The script text to synthesize.
            voice_config: Dict with voice_id (reference_id) and optional
                temperature, top_p, speed settings.

        Returns:
            File path to the rendered WAV audio file.

        Raises:
            RuntimeError: If the TTS request fails after retries.
        """
        return await retry_with_backoff(
            self._render_impl,
            text,
            voice_config,
            max_retries=2,
            base_delay=10.0,
            max_delay=60.0,
            rate_limiter=self._rate_limiter,
            operation_name="fish_audio_tts_render",
        )

    async def _render_impl(self, text: str, voice_config: dict) -> str:
        """Internal render implementation.

        Args:
            text: The script text to synthesize.
            voice_config: Voice settings dict.

        Returns:
            File path to the rendered audio file.
        """
        client = self._get_client()
        voice_id = voice_config.get("voice_id", "")

        # Fish Audio voice / reference IDs are 32-character hexadecimal strings.
        # If the voice_id is not in this format (e.g. "Aoede" or empty), fall back immediately.
        if voice_id and not (len(voice_id) == 32 and all(c in "0123456789abcdefABCDEF" for c in voice_id)):
            default_voice = FISH_VOICES[0]["voice_id"]
            logger.warning(
                "Invalid Fish Audio voice ID %r (must be 32-character hex). "
                "Falling back to default voice %r (Raddo).",
                voice_id,
                default_voice,
            )
            voice_id = default_voice

        payload: dict = {
            "text": text,
            "format": "wav",
            "sample_rate": 44100,
            "latency": "normal",
            "normalize": True,
        }

        if voice_id:
            payload["reference_id"] = voice_id

        # Optional generation parameters
        if "temperature" in voice_config:
            payload["temperature"] = voice_config["temperature"]
        if "top_p" in voice_config:
            payload["top_p"] = voice_config["top_p"]

        # Prosody adjustments
        speed = voice_config.get("speed")
        volume = voice_config.get("volume")
        if speed is not None or volume is not None:
            prosody: dict = {}
            if speed is not None:
                prosody["speed"] = speed
            if volume is not None:
                prosody["volume"] = volume
            payload["prosody"] = prosody

        try:
            logger.info(
                "Rendering TTS via Fish Audio: voice=%s, model=%s, %d chars",
                voice_id or "(default)",
                self._model,
                len(text),
            )

            response = await client.post(
                "/v1/tts",
                json=payload,
                headers={"model": self._model},
            )

            if response.status_code == 429:
                logger.warning("Fish Audio TTS rate limited")
                self._rate_limiter.record_error()
                raise RuntimeError("Fish Audio TTS rate limited")

            if response.status_code == 402:
                logger.error("Fish Audio TTS payment required — check account balance")
                raise RuntimeError("Fish Audio TTS payment required")

            # Check for bad reference voice ID (400 Bad Request)
            if response.status_code == 400:
                try:
                    err_json = response.json()
                    err_msg = err_json.get("message", "")
                except Exception:
                    err_msg = response.text

                if "Reference not found" in err_msg or "reference" in err_msg.lower():
                    default_voice = FISH_VOICES[0]["voice_id"]
                    logger.warning(
                        "Fish Audio voice reference %r was not found. "
                        "Falling back to default voice %r (Raddo) and retrying.",
                        voice_id,
                        default_voice,
                    )
                    payload["reference_id"] = default_voice
                    response = await client.post(
                        "/v1/tts",
                        json=payload,
                        headers={"model": self._model},
                    )

            response.raise_for_status()

            # Response is a streamed audio file
            audio_bytes = response.content
            if not audio_bytes:
                raise RuntimeError("Fish Audio TTS returned empty response")

            file_id = uuid.uuid4().hex[:12]
            filepath = self._audio_dir / f"break_{file_id}.wav"
            filepath.write_bytes(audio_bytes)

            size_mb = filepath.stat().st_size / 1e6
            logger.info(
                "Fish Audio TTS saved: %s (%.2f MB)", filepath, size_mb
            )

            return str(filepath)

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:200]
            if status >= 500:
                raise RuntimeError(
                    f"Fish Audio TTS server error: {status}"
                ) from exc
            logger.error("Fish Audio TTS API error: %s %s", status, body)
            raise RuntimeError(
                f"Fish Audio TTS API error: {status}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Fish Audio TTS request failed: %s", exc)
            raise RuntimeError(
                f"Fish Audio TTS request failed: {exc}"
            ) from exc

    async def list_voices(self) -> list:
        """List available voices from Fish Audio.

        Returns curated radio voices first, then appends popular public
        models from the API (excluding duplicates).

        Returns:
            A list of dicts with voice_id, name, category, description, and sample_url.
        """
        voices = [dict(v) for v in FISH_VOICES]
        curated_map = {v["voice_id"]: v for v in voices}

        try:
            client = self._get_client()
            response = await client.get(
                "/model",
                params={
                    "page_size": 50,
                    "page_number": 1,
                    "sort_by": "score",
                },
            )
            response.raise_for_status()
            data = response.json()

            for item in data.get("items", []):
                item_id = item.get("_id", "")
                samples = item.get("samples", [])
                sample_url = samples[0].get("audio") if samples else None

                if item_id in curated_map:
                    if sample_url:
                        curated_map[item_id]["sample_url"] = sample_url
                elif item_id:
                    voices.append({
                        "voice_id": item_id,
                        "name": item.get("title", "Unknown"),
                        "category": ", ".join(item.get("languages", [])) or "multilingual",
                        "description": item.get("description", ""),
                        "sample_url": sample_url,
                    })
        except Exception as exc:
            logger.warning("Failed to fetch additional Fish Audio voices: %s", exc)

        return voices

    async def check_status(self) -> bool:
        """Check whether Fish Audio is reachable.

        Respects the circuit breaker — returns a cached False immediately
        when the circuit is open.

        Returns:
            True if the provider is operational, False otherwise.
        """
        if self._rate_limiter.is_backing_off:
            logger.debug(
                "Fish Audio health check skipped — %s",
                "circuit OPEN" if self._rate_limiter.circuit_open
                else "rate limiter backing off",
            )
            return False

        try:
            client = self._get_client()
            response = await client.get("/model", params={"page_size": 1})
            if response.status_code == 200:
                self._rate_limiter.record_success()
                return True
            logger.warning(
                "Fish Audio health check returned %d", response.status_code
            )
            self._rate_limiter.record_error()
            return False
        except Exception as exc:
            logger.warning("Fish Audio health check failed: %s", exc)
            self._rate_limiter.record_error()
            return False
