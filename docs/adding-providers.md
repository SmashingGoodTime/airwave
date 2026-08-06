# Adding Providers

How to add new AI services or custom integrations to Airwave. This guide is for developers who want to swap in a different music API, voice service, or script writer.

---

## Table of Contents

1. [How Providers Work](#1-how-providers-work)
2. [The Three Provider Types](#2-the-three-provider-types)
3. [Step-by-Step: Creating a New Provider](#3-step-by-step-creating-a-new-provider)
4. [Provider Requirements](#4-provider-requirements)
5. [Rate Limiting and Retries](#5-rate-limiting-and-retries)
6. [Health Checks](#6-health-checks)
7. [Adding Event Handlers](#7-adding-event-handlers)
8. [Available Events](#8-available-events)

---

## 1. How Providers Work

Airwave uses a plugin architecture. The engine (scheduler, buffer manager, DJ brain) never talks directly to concrete services such as Suno, Gemini, or Fish Audio. Instead, it talks to abstract interfaces, and a **provider registry** decides which concrete implementation to use based on your configuration.

```
Engine Code  -->  Abstract Interface  -->  Provider Registry  -->  Concrete Provider
                  (MusicProvider)          (picks based on       (SunoProvider,
                                            config/API keys)      OpenAIMusicProvider,
                                                                  etc.)
```

This means you can add a new provider by:

1. Creating one Python file
2. Subclassing the abstract base
3. Registering it in the registry
4. **No other code changes needed**

---

## 2. The Five Provider Types

All provider interfaces are defined in `server/providers/base.py`.

### MusicProvider

Generates music tracks from text descriptions.

```python
class MusicProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, duration: int = 180) -> dict:
        """Generate a music track from a text prompt.

        Args:
            prompt: Style/genre description (e.g., "lo-fi hip hop with piano").
            duration: Target duration in seconds.

        Returns:
            Dict with: filepath, title, duration, metadata
        """
        ...

    @abstractmethod
    async def check_status(self) -> bool:
        """Return True if the provider is operational."""
        ...
```

### ScriptWriterProvider

Writes DJ break scripts from playback context.

```python
class ScriptWriterProvider(ABC):
    @abstractmethod
    async def write_break(self, context: dict) -> dict:
        """Generate a DJ break script.

        Args:
            context: Dict containing recent_tracks, announcements,
                     station_name, dj_name, personality_prompt,
                     current_time, mention_time, max_duration.

        Returns:
            Dict with: script_text, estimated_duration
        """
        ...

    @abstractmethod
    async def check_status(self) -> bool:
        ...
```

### VoiceProvider

Converts text to spoken audio.

```python
class VoiceProvider(ABC):
    @abstractmethod
    async def render(self, text: str, voice_config: dict) -> str:
        """Render text to speech.

        Args:
            text: The script to speak.
            voice_config: Dict with voice_id and optional settings
                          (stability, similarity_boost, etc.)

        Returns:
            File path to the rendered audio file.
        """
        ...

    @abstractmethod
    async def list_voices(self) -> list:
        """Return available voices as a list of dicts.

        Each dict should have: voice_id, name, and optionally
        preview_url, category, description.
        """
        ...

    @abstractmethod
    async def check_status(self) -> bool:
        ...
```

---

## 3. Step-by-Step: Creating a New Provider

This example adds a hypothetical OpenAI music provider. The same pattern works for any provider type.

### Step 1: Create the provider file

Create `server/providers/music/openai_music.py`:

```python
"""OpenAI music generation provider."""

import logging
from pathlib import Path
from server.providers.base import MusicProvider
from server.utils.rate_limiter import RateLimiter, retry_with_backoff

logger = logging.getLogger(__name__)


class OpenAIMusicProvider(MusicProvider):
    """Music generation using OpenAI's API.

    Args:
        api_key: OpenAI API key.
        audio_dir: Root audio directory.
    """

    def __init__(self, api_key: str, audio_dir: str = "./audio") -> None:
        self._api_key = api_key
        self._audio_dir = Path(audio_dir) / "tracks"
        self._audio_dir.mkdir(parents=True, exist_ok=True)
        self._rate_limiter = RateLimiter(
            calls_per_minute=10, min_interval=5.0, name="openai_music"
        )

    async def generate(self, prompt: str, duration: int = 180) -> dict:
        """Generate a track with retry and rate limiting."""
        return await retry_with_backoff(
            self._generate_impl, prompt, duration,
            max_retries=2,
            base_delay=10.0,
            max_delay=60.0,
            rate_limiter=self._rate_limiter,
            operation_name="openai_music_generate",
        )

    async def _generate_impl(self, prompt: str, duration: int) -> dict:
        """Internal generation logic — make the API call here."""
        # 1. Call the OpenAI API
        # 2. Download the resulting audio file
        # 3. Save it to self._audio_dir
        # 4. Return the required dict

        filepath = self._audio_dir / "openai_track_123.mp3"

        return {
            "filepath": str(filepath),
            "title": "Generated Track",
            "duration": duration,
            "metadata": {
                "provider": "openai",
                "prompt": prompt,
            },
        }

    async def check_status(self) -> bool:
        """Quick health check — don't consume API credits."""
        if self._rate_limiter.is_backing_off:
            return False
        try:
            # Make a cheap API call to verify connectivity
            return True
        except Exception:
            return False
```

### Step 2: Register in the provider registry

Edit `server/providers/registry.py` and add a `ProviderDefinition` to
`BUILTIN_PROVIDER_DEFINITIONS`. Do not add provider-specific branches to
engine code or route handlers.

```python
ProviderDefinition(
    key="openai_music",
    capability="music",
    display_name="OpenAI Music",
    module_path="server.providers.music.openai_music",
    class_name="OpenAIMusicProvider",
    required_env=("OPENAI_MUSIC_API_KEY",),
    factory=_api_key_provider("OPENAI_MUSIC_API_KEY", include_audio_dir=True),
),
```

The registry checks definitions in order. For single-provider capabilities
like music, scriptwriter, telephony, and conversation, the first configured
provider that initializes successfully wins. For voice providers, all
configured providers are loaded and the active voice is selected by
`VOICE_PROVIDER_PREFERENCE`.

If your provider constructor is not simply `api_key=...` plus optional
`audio_dir=...`, add a small factory function near the definitions:

```python
def _my_provider_factory(ctx: ProviderFactoryContext) -> ProviderInstance:
    return ctx.provider_cls(
        token=ctx.value("MY_PROVIDER_TOKEN"),
        region=ctx.value("MY_PROVIDER_REGION"),
        output_dir=ctx.audio_dir,
    )
```

Then reference that factory from your `ProviderDefinition`.

### Step 3: Add the config key

Add to `server/config.py`:

```python
OPENAI_MUSIC_API_KEY: str = ""
```

And to `.env.example`:

```env
# OpenAI music generation (alternative to Suno)
OPENAI_MUSIC_API_KEY=
```

### Step 4: Done

That's it. No engine code changes needed. The buffer manager, scheduler, and DJ brain all work through the abstract interface and will automatically use your new provider when its required config is set.

### Step 5: Add tests

Add or update provider registry tests in `tests/test_providers.py` for:

- priority/fallback behavior if your provider competes with an existing one
- graceful failure when the provider constructor raises
- health check behavior using mocks, never real API calls

---

## 4. Provider Requirements

### What `generate()` must return (MusicProvider)

```python
{
    "filepath": "/path/to/audio.mp3",    # Required — path to the audio file
    "title": "Track Title",               # Required — display title
    "duration": 180.0,                    # Required — duration in seconds
    "metadata": {                         # Optional — stored as JSON
        "provider": "your_provider",
        "any_extra": "data"
    }
}
```

### What `write_break()` must return (ScriptWriterProvider)

```python
{
    "script_text": "Hey everyone, ...",   # Required — the DJ script text
    "estimated_duration": 25.0,           # Optional — estimated seconds when spoken
}
```

### What `render()` must return (VoiceProvider)

```python
"/path/to/rendered/audio.mp3"            # A file path string
```

### What `list_voices()` must return (VoiceProvider)

```python
[
    {"voice_id": "abc123", "name": "Rachel", "preview_url": "https://..."},
    {"voice_id": "def456", "name": "Josh"},
]
```

### TelephonyProvider methods

```python
class TelephonyProvider(ABC):
    async def accept_call(self, call_sid: str, webhook_url: str) -> dict: ...
    async def bridge_to_stream(self, call_sid: str, stream_url: str) -> dict: ...
    async def record_call(self, call_sid: str) -> dict: ...
    async def end_call(self, call_sid: str) -> bool: ...
    async def get_recording(self, recording_sid: str) -> bytes: ...
    async def check_status(self) -> bool: ...
```

### ConversationAIProvider methods

```python
class ConversationAIProvider(ABC):
    async def start_session(self, system_prompt: str, voice: str, ...) -> dict: ...
    async def connect_audio_stream(self, session_id: str, audio_stream) -> None: ...
    async def end_session(self, session_id: str) -> dict: ...
    async def check_status(self) -> bool: ...
```

### Audio formats

Generated audio files can be in any format FFmpeg supports (MP3, WAV, OGG, FLAC, AAC, etc.). The audio pipeline automatically:

1. Converts to 48kHz, 16-bit, stereo WAV
2. Trims silence from the start and end
3. Normalizes loudness to -14 LUFS (EBU R128, two-pass)

You don't need to worry about normalization in your provider.

### Error handling rules

Your provider must:

- **Catch all API exceptions** and re-raise as `RuntimeError` with a clear message
- **Never let raw API errors propagate** to the engine
- **Log errors** with enough context to debug (status codes, truncated response bodies)
- **Use the rate limiter** to pace API calls

The engine wraps all provider calls in try/except, so a crash won't take down the station — but clean error messages help operators diagnose issues.

---

## 5. Rate Limiting and Retries

Use the built-in `RateLimiter` and `retry_with_backoff` from `server/utils/rate_limiter.py`:

```python
from server.utils.rate_limiter import RateLimiter, retry_with_backoff

# Create a rate limiter in __init__
self._rate_limiter = RateLimiter(
    calls_per_minute=10,     # Max API calls per minute
    min_interval=5.0,        # Minimum seconds between calls
    name="my_provider"       # Used in log messages
)

# Use retry_with_backoff for the public method
async def generate(self, prompt, duration):
    return await retry_with_backoff(
        self._generate_impl, prompt, duration,
        max_retries=2,          # Retry up to 2 times on failure
        base_delay=10.0,        # Initial delay between retries
        max_delay=60.0,         # Maximum delay (caps exponential growth)
        rate_limiter=self._rate_limiter,
        operation_name="my_provider_generate",
    )
```

If you get an HTTP 429 (rate limited) response, call `self._rate_limiter.record_error()` to trigger exponential backoff.

---

## 6. Health Checks

The `check_status()` method is called periodically by the dashboard. It should:

- Be **fast** (under 5 seconds)
- **Not consume API credits** — use a cheap endpoint like listing voices or checking auth
- Return `False` if the rate limiter is backing off
- **Never raise exceptions** — catch everything and return `False`

```python
async def check_status(self) -> bool:
    if self._rate_limiter.is_backing_off:
        return False
    try:
        # Quick connectivity check
        client = self._get_client()
        response = await client.get("/health")
        return response.status_code == 200
    except Exception:
        return False
```

---

## 7. Adding Event Handlers

Beyond providers, you can extend the station with custom event handlers. Events fire when tracks play, the buffer gets low, providers fail, etc.

### Example: Discord notifications

```python
import httpx

async def notify_discord(event: str, data: dict) -> None:
    """Send now-playing updates to a Discord webhook."""
    webhook_url = "https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE"
    title = data.get("title", "Unknown Track")
    async with httpx.AsyncClient() as client:
        await client.post(webhook_url, json={
            "content": f"Now playing: {title}"
        })
```

Register it in `server/events/handlers.py`:

```python
def setup_default_handlers(bus):
    # ... existing handlers ...
    bus.on("track.started", notify_discord)
```

---

## 8. Available Events

Every event includes a `data` dict with context-specific fields.

| Event | When It Fires | Data Fields |
|-------|--------------|-------------|
| `track.generated` | New track added to the buffer | `track_id`, `title`, `style`, `duration` |
| `track.started` | Track begins playing | `track_id`, `title`, `duration`, `style`, `started_at` |
| `track.ended` | Track finished playing | `track_id` |
| `break.generated` | DJ break audio is ready | `break_id`, `duration`, `has_audio` |
| `break.started` | DJ break begins playing | `break_id` |
| `buffer.low` | Buffer below warning threshold | `ready`, `target` |
| `buffer.critical` | Buffer empty, fallback activated | `ready`, `target` |
| `provider.error` | An AI service call failed | `provider`, `error` |
| `provider.recovered` | AI service responding again | `provider` |
| `system.disk_warning` | Disk space below 5 GB | `free_gb`, `usage_pct` |
| `system.disk_critical` | Disk space below 1 GB | `free_gb`, `usage_pct` |
| `show.started` | A scheduled show has begun | `show_id`, `show_name` |
| `show.ended` | A scheduled show has ended | `show_id` |
| `call.incoming` | A listener is calling in | `session_id`, `mode` |
| `call.screening` | Caller is being screened by AI | `session_id` |
| `call.connected` | Caller connected to AI host | `session_id` |
| `call.on_air` | Caller audio is live on the stream | `session_id` |
| `call.ended` | Call has ended | `session_id`, `duration` |
| `call.queued` | Call added to the queue | `session_id` |
| `call.moderation_flag` | Content moderation triggered | `session_id`, `flags` |
