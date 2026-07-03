"""Tests for provider base classes, registry, and mock implementations."""

import httpx
import pytest
import pytest_asyncio

from server.providers.base import MusicProvider, ScriptWriterProvider, VoiceProvider
from server.providers.scriptwriter.google import (
    GeminiScriptWriterProvider,
    _clean_for_tts,
)
from server.providers.registry import ProviderDefinition, ProviderRegistry
from server.utils.env import update_env_file
from server.utils.rate_limiter import (
    NonRetryableError,
    RateLimiter,
    retry_with_backoff,
)

from tests.conftest import (
    FailingMusicProvider,
    MockMusicProvider,
    MockScriptWriterProvider,
    MockVoiceProvider,
)


# ---------------------------------------------------------------------------
# Base class contract tests
# ---------------------------------------------------------------------------


class TestMockMusicProvider:
    @pytest.mark.asyncio
    async def test_generate_returns_expected_keys(self, mock_music_provider):
        result = await mock_music_provider.generate("ambient chill", duration=120)
        assert "filepath" in result
        assert "title" in result
        assert "duration" in result
        assert result["duration"] == 120

    @pytest.mark.asyncio
    async def test_generate_includes_prompt_in_title(self, mock_music_provider):
        result = await mock_music_provider.generate("lo-fi jazz")
        assert "lo-fi jazz" in result["title"]

    @pytest.mark.asyncio
    async def test_check_status_healthy(self, mock_music_provider):
        assert await mock_music_provider.check_status() is True

    @pytest.mark.asyncio
    async def test_is_instance_of_base(self, mock_music_provider):
        assert isinstance(mock_music_provider, MusicProvider)


class TestMockScriptWriterProvider:
    @pytest.mark.asyncio
    async def test_write_break_returns_script(self, mock_scriptwriter_provider):
        result = await mock_scriptwriter_provider.write_break({"dj_name": "TestDJ"})
        assert "script_text" in result
        assert "TestDJ" in result["script_text"]

    @pytest.mark.asyncio
    async def test_write_break_default_dj_name(self, mock_scriptwriter_provider):
        result = await mock_scriptwriter_provider.write_break({})
        assert "DJ" in result["script_text"]

    @pytest.mark.asyncio
    async def test_check_status(self, mock_scriptwriter_provider):
        assert await mock_scriptwriter_provider.check_status() is True

    @pytest.mark.asyncio
    async def test_write_talk_segment_not_implemented(self, mock_scriptwriter_provider):
        with pytest.raises(NotImplementedError):
            await mock_scriptwriter_provider.write_talk_segment({})

    @pytest.mark.asyncio
    async def test_is_instance_of_base(self, mock_scriptwriter_provider):
        assert isinstance(mock_scriptwriter_provider, ScriptWriterProvider)


class TestGeminiScriptWriterProvider:
    @pytest.mark.asyncio
    async def test_write_talk_segment_returns_conversation_json(self):
        """Gemini should implement the talk-show contract, not inherit the stub."""

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {
                                "parts": [
                                    {
                                        "text": (
                                            '[{"speaker":"Host","text":"Welcome back.",'
                                            '"pace":"normal"},'
                                            '{"speaker":"Riley","text":"This is the good part.",'
                                            '"pace":"quick"}]'
                                        )
                                    }
                                ]
                            },
                        }
                    ]
                }

        class FakeClient:
            async def post(self, url, json):
                return FakeResponse()

        provider = GeminiScriptWriterProvider(api_key="test-key")
        provider._get_client = lambda: FakeClient()

        result = await provider.write_talk_segment(
            {
                "topic": {"title": "Local arts", "prompt": "Discuss local arts."},
                "segment_type": "conversation",
                "speakers": [
                    {"name": "Host", "personality_prompt": "Curious host"},
                    {"name": "Riley", "personality_prompt": "Dry co-host"},
                ],
                "show_name": "Morning Talk",
                "target_duration": 120,
            }
        )

        assert result["segment_type"] == "conversation"
        assert result["speakers"] == ["Host", "Riley"]
        assert result["estimated_duration"] > 0
        assert result["script_text"].startswith("[")


class TestMockVoiceProvider:
    @pytest.mark.asyncio
    async def test_render_returns_path(self, mock_voice_provider):
        path = await mock_voice_provider.render("Hello world", {"voice_id": "v1"})
        assert isinstance(path, str)
        assert path.endswith(".wav")

    @pytest.mark.asyncio
    async def test_list_voices(self, mock_voice_provider):
        voices = await mock_voice_provider.list_voices()
        assert len(voices) == 2
        assert voices[0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_check_status(self, mock_voice_provider):
        assert await mock_voice_provider.check_status() is True

    @pytest.mark.asyncio
    async def test_is_instance_of_base(self, mock_voice_provider):
        assert isinstance(mock_voice_provider, VoiceProvider)


class TestFailingMusicProvider:
    @pytest.mark.asyncio
    async def test_generate_raises(self, failing_music_provider):
        with pytest.raises(RuntimeError, match="Provider unavailable"):
            await failing_music_provider.generate("anything")

    @pytest.mark.asyncio
    async def test_check_status_unhealthy(self, failing_music_provider):
        assert await failing_music_provider.check_status() is False


# ---------------------------------------------------------------------------
# Provider registry tests
# ---------------------------------------------------------------------------


class CandidateHealthyMusicProvider(MusicProvider):
    """Music provider that records the API key used for health checks."""

    seen_keys: list[str] = []

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.seen_keys.append(api_key)

    async def generate(self, prompt: str, duration: int = 180) -> dict:
        return {}

    async def check_status(self) -> bool:
        return self.api_key == "candidate-key"


class CandidateFailingMusicProvider(MusicProvider):
    """Music provider whose health check raises an exception."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def generate(self, prompt: str, duration: int = 180) -> dict:
        return {}

    async def check_status(self) -> bool:
        raise RuntimeError("candidate exploded")


class ClosableMusicProvider(MusicProvider):
    """Music provider that records whether aclose() was called."""

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key
        self.closed = False

    async def generate(self, prompt: str, duration: int = 180) -> dict:
        return {}

    async def check_status(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.closed = True


class TestProviderRegistry:
    def test_singleton(self):
        # Reset singleton for test isolation
        ProviderRegistry._instance = None
        a = ProviderRegistry.get_instance()
        b = ProviderRegistry.get_instance()
        assert a is b
        ProviderRegistry._instance = None  # cleanup

    def test_empty_registry_returns_none(self):
        registry = ProviderRegistry()
        assert registry.get_music_provider() is None
        assert registry.get_scriptwriter_provider() is None
        assert registry.get_voice_provider() is None
        assert registry.get_telephony_provider() is None
        assert registry.get_conversation_provider() is None

    def test_mock_registry_providers(self, mock_registry):
        assert isinstance(mock_registry.get_music_provider(), MusicProvider)
        assert isinstance(mock_registry.get_scriptwriter_provider(), ScriptWriterProvider)
        assert isinstance(mock_registry.get_voice_provider(), VoiceProvider)

    @pytest.mark.asyncio
    async def test_check_all_health_configured(self, mock_registry):
        health = await mock_registry.check_all_health()
        assert health["music"]["healthy"] is True
        assert health["scriptwriter"]["healthy"] is True
        assert health["voice"]["healthy"] is True
        assert health["music"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_check_all_health_unconfigured(self):
        registry = ProviderRegistry()
        health = await registry.check_all_health()
        assert health["music"]["status"] == "unconfigured"
        assert health["music"]["healthy"] is False

    @pytest.mark.asyncio
    async def test_check_all_health_failing(self):
        registry = ProviderRegistry()
        registry._music = FailingMusicProvider()
        health = await registry.check_all_health()
        assert health["music"]["healthy"] is False
        assert health["music"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_initialize_no_keys(self):
        """Registry should handle missing API keys gracefully."""
        registry = ProviderRegistry()

        class EmptyConfig:
            pass

        await registry.initialize(EmptyConfig())
        assert registry.get_music_provider() is None
        assert registry.get_scriptwriter_provider() is None
        assert registry.get_voice_provider() is None

    @pytest.mark.asyncio
    async def test_initialize_clears_stale_providers_when_keys_removed(self):
        """Reinitializing with no keys should not keep old providers alive."""
        registry = ProviderRegistry()
        registry._music = MockMusicProvider()

        class EmptyConfig:
            pass

        await registry.initialize(EmptyConfig())
        assert registry.get_music_provider() is None

    @pytest.mark.asyncio
    async def test_initialize_closes_stale_provider_instances(self):
        """Reinitializing must aclose() replaced providers, not just drop them."""
        registry = ProviderRegistry()
        stale = ClosableMusicProvider()
        registry._music = stale

        class EmptyConfig:
            pass

        await registry.initialize(EmptyConfig())
        assert stale.closed is True

    @pytest.mark.asyncio
    async def test_check_capability_health_closes_throwaway_provider(self):
        """Candidate providers built for health tests must be closed."""
        created: list[ClosableMusicProvider] = []

        def factory(ctx):
            provider = ClosableMusicProvider(api_key=ctx.value("SUNO_API_KEY"))
            created.append(provider)
            return provider

        definitions = (
            ProviderDefinition(
                key="closable_music",
                capability="music",
                display_name="Closable Music",
                module_path="tests.test_providers",
                class_name="ClosableMusicProvider",
                required_env=("SUNO_API_KEY",),
                factory=factory,
            ),
        )
        registry = ProviderRegistry(definitions=definitions)

        class CandidateConfig:
            SUNO_API_KEY = "candidate-key"

        result = await registry.check_capability_health("music", CandidateConfig())

        assert result["healthy"] is True
        assert len(created) == 1
        assert created[0].closed is True

    @pytest.mark.asyncio
    async def test_music_provider_priority_prefers_first_configured_definition(self):
        """Music selection should use definition order as provider priority."""
        definitions = (
            ProviderDefinition(
                key="suno",
                capability="music",
                display_name="Suno",
                module_path="tests.conftest",
                class_name="MockMusicProvider",
                required_env=("SUNO_API_KEY",),
                factory=lambda ctx: ctx.provider_cls(),
            ),
            ProviderDefinition(
                key="other_music",
                capability="music",
                display_name="Other Music",
                module_path="tests.conftest",
                class_name="MockMusicProvider",
                required_env=("OTHER_API_KEY",),
                factory=lambda ctx: ctx.provider_cls(),
            ),
        )
        registry = ProviderRegistry(definitions=definitions)

        class Config:
            SUNO_API_KEY = "suno-key"
            OTHER_API_KEY = "other-key"

        await registry.initialize(Config())
        assert registry.get_music_provider() is not None
        assert registry._provider_keys["music"] == "suno"

    @pytest.mark.asyncio
    async def test_voice_provider_preference_restores_fish_audio_first(self):
        """When multiple voices are configured, Fish Audio is active by default."""
        definitions = (
            ProviderDefinition(
                key="fish_audio",
                capability="voice",
                display_name="Fish Audio",
                module_path="tests.conftest",
                class_name="MockVoiceProvider",
                required_env=("FISH_AUDIO_API_KEY",),
                factory=lambda ctx: ctx.provider_cls(),
            ),
            ProviderDefinition(
                key="other_voice",
                capability="voice",
                display_name="Other Voice",
                module_path="tests.conftest",
                class_name="MockVoiceProvider",
                required_env=("OTHER_VOICE_API_KEY",),
                factory=lambda ctx: ctx.provider_cls(),
            ),
        )
        registry = ProviderRegistry(definitions=definitions)

        class Config:
            FISH_AUDIO_API_KEY = "fish-key"
            OTHER_VOICE_API_KEY = "other-voice-key"

        await registry.initialize(Config())
        providers = registry.list_voice_providers()
        assert {p["key"] for p in providers} == {"fish_audio", "other_voice"}
        assert [p["key"] for p in providers if p["active"]] == ["fish_audio"]

    @pytest.mark.asyncio
    async def test_failed_provider_initialization_does_not_block_fallback(self):
        """A broken provider definition should log and continue to the next one."""

        def fail_factory(ctx):
            raise RuntimeError("boom")

        definitions = (
            ProviderDefinition(
                key="broken_music",
                capability="music",
                display_name="Broken Music",
                module_path="tests.conftest",
                class_name="MockMusicProvider",
                required_env=("BROKEN_API_KEY",),
                factory=fail_factory,
            ),
            ProviderDefinition(
                key="working_music",
                capability="music",
                display_name="Working Music",
                module_path="tests.conftest",
                class_name="MockMusicProvider",
                required_env=("WORKING_API_KEY",),
                factory=lambda ctx: ctx.provider_cls(),
            ),
        )
        registry = ProviderRegistry(definitions=definitions)

        class Config:
            BROKEN_API_KEY = "broken-key"
            WORKING_API_KEY = "working-key"

        await registry.initialize(Config())
        assert registry.get_music_provider() is not None
        assert registry._provider_keys["music"] == "working_music"

    @pytest.mark.asyncio
    async def test_health_results_are_cached(self):
        """Repeated health checks should use cache unless force=True."""

        class CountingMusicProvider(MusicProvider):
            def __init__(self):
                self.calls = 0

            async def generate(self, prompt: str, duration: int = 180) -> dict:
                return {}

            async def check_status(self) -> bool:
                self.calls += 1
                return True

        provider = CountingMusicProvider()
        registry = ProviderRegistry()
        registry._music = provider

        await registry.check_all_health()
        await registry.check_all_health()
        assert provider.calls == 1

        await registry.check_all_health(force=True)
        assert provider.calls == 2

    @pytest.mark.asyncio
    async def test_check_capability_health_uses_candidate_config_without_registering(self):
        CandidateHealthyMusicProvider.seen_keys.clear()
        definitions = (
            ProviderDefinition(
                key="candidate_music",
                capability="music",
                display_name="Candidate Music",
                module_path="tests.test_providers",
                class_name="CandidateHealthyMusicProvider",
                required_env=("SUNO_API_KEY",),
                factory=lambda ctx: ctx.provider_cls(api_key=ctx.value("SUNO_API_KEY")),
            ),
        )
        registry = ProviderRegistry(definitions=definitions)

        class CandidateConfig:
            SUNO_API_KEY = "candidate-key"

        result = await registry.check_capability_health("music", CandidateConfig())

        assert result == {
            "provider": "candidate_music",
            "healthy": True,
            "status": "healthy",
            "error": None,
        }
        assert CandidateHealthyMusicProvider.seen_keys == ["candidate-key"]
        assert registry.get_music_provider() is None

    @pytest.mark.asyncio
    async def test_check_capability_health_reports_unconfigured_candidate(self):
        definitions = (
            ProviderDefinition(
                key="candidate_music",
                capability="music",
                display_name="Candidate Music",
                module_path="tests.test_providers",
                class_name="CandidateHealthyMusicProvider",
                required_env=("SUNO_API_KEY",),
                factory=lambda ctx: ctx.provider_cls(api_key=ctx.value("SUNO_API_KEY")),
            ),
        )
        registry = ProviderRegistry(definitions=definitions)

        class EmptyConfig:
            SUNO_API_KEY = ""

        result = await registry.check_capability_health("music", EmptyConfig())

        assert result == {
            "provider": None,
            "healthy": False,
            "status": "unconfigured",
            "error": "Provider is not configured",
        }

    @pytest.mark.asyncio
    async def test_check_capability_health_reports_unknown_capability(self):
        registry = ProviderRegistry()

        result = await registry.check_capability_health("weather", object())

        assert result == {
            "provider": "weather",
            "healthy": False,
            "status": "unknown_provider",
            "error": "Unknown provider type: weather",
        }

    @pytest.mark.asyncio
    async def test_check_capability_health_accepts_custom_definition_capability(self):
        CandidateHealthyMusicProvider.seen_keys.clear()
        definitions = (
            ProviderDefinition(
                key="candidate_custom",
                capability="custom_audio",
                display_name="Candidate Custom",
                module_path="tests.test_providers",
                class_name="CandidateHealthyMusicProvider",
                required_env=("CUSTOM_AUDIO_API_KEY",),
                factory=lambda ctx: ctx.provider_cls(
                    api_key=ctx.value("CUSTOM_AUDIO_API_KEY")
                ),
            ),
        )
        registry = ProviderRegistry(definitions=definitions)

        class CandidateConfig:
            CUSTOM_AUDIO_API_KEY = "candidate-key"

        result = await registry.check_capability_health("custom_audio", CandidateConfig())

        assert result == {
            "provider": "candidate_custom",
            "healthy": True,
            "status": "healthy",
            "error": None,
        }
        assert CandidateHealthyMusicProvider.seen_keys == ["candidate-key"]

    @pytest.mark.asyncio
    async def test_check_capability_health_reports_exceptions(self):
        definitions = (
            ProviderDefinition(
                key="candidate_music",
                capability="music",
                display_name="Candidate Music",
                module_path="tests.test_providers",
                class_name="CandidateFailingMusicProvider",
                required_env=("SUNO_API_KEY",),
                factory=lambda ctx: ctx.provider_cls(api_key=ctx.value("SUNO_API_KEY")),
            ),
        )
        registry = ProviderRegistry(definitions=definitions)

        class CandidateConfig:
            SUNO_API_KEY = "candidate-key"

        result = await registry.check_capability_health("music", CandidateConfig())

        # Error strings are sanitized: exception class name + safe message,
        # never raw URLs or keys.
        assert result == {
            "provider": "candidate_music",
            "healthy": False,
            "status": "error",
            "error": "RuntimeError: candidate exploded",
        }


# ---------------------------------------------------------------------------
# Rate limiter / retry semantics
# ---------------------------------------------------------------------------


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_non_retryable_error_short_circuits(self):
        """NonRetryableError must fail immediately with one error record."""
        limiter = RateLimiter(min_interval=0.0, name="test")
        calls = 0

        async def func():
            nonlocal calls
            calls += 1
            raise NonRetryableError("auth failed")

        with pytest.raises(NonRetryableError, match="auth failed"):
            await retry_with_backoff(
                func,
                max_retries=3,
                base_delay=0.0,
                rate_limiter=limiter,
                operation_name="test_op",
            )

        assert calls == 1
        assert limiter.consecutive_errors == 1

    @pytest.mark.asyncio
    async def test_single_error_record_per_failed_attempt(self):
        """retry_with_backoff is the only accounting point — one record per attempt."""

        class SpyLimiter(RateLimiter):
            def __init__(self):
                super().__init__(min_interval=0.0, name="spy")
                self.errors = 0
                self.successes = 0

            async def acquire(self):
                return None

            def record_error(self):
                self.errors += 1

            def record_success(self):
                self.successes += 1

        spy = SpyLimiter()
        calls = 0

        async def func():
            nonlocal calls
            calls += 1
            raise RuntimeError("transient")

        with pytest.raises(RuntimeError, match="transient"):
            await retry_with_backoff(
                func,
                max_retries=2,
                base_delay=0.0,
                rate_limiter=spy,
                operation_name="test_op",
            )

        assert calls == 3
        assert spy.errors == 3
        assert spy.successes == 0

    @pytest.mark.asyncio
    async def test_circuit_open_rejects_without_calling_func(self):
        """An open circuit propagates immediately and never invokes func."""
        limiter = RateLimiter(
            min_interval=0.0, name="test", circuit_threshold=1
        )
        limiter.record_error()  # threshold 1 — opens the circuit
        assert limiter.circuit_open

        calls = 0

        async def func():
            nonlocal calls
            calls += 1
            return "ok"

        with pytest.raises(RuntimeError, match="circuit breaker OPEN"):
            await retry_with_backoff(
                func,
                max_retries=2,
                base_delay=0.0,
                rate_limiter=limiter,
                operation_name="test_op",
            )

        assert calls == 0
        assert limiter.consecutive_errors == 1  # rejection not recorded


class TestCircuitBreakerHalfOpen:
    @pytest.mark.asyncio
    async def test_half_open_admits_single_probe(self):
        """Only one probe may be in flight while the circuit is half-open."""
        limiter = RateLimiter(
            min_interval=0.0,
            name="test",
            circuit_threshold=1,
            circuit_base_cooldown=0.0,
        )
        limiter.record_error()  # opens circuit; cooldown 0 expires instantly
        limiter._backoff_until = 0.0  # skip the error backoff sleep in tests

        await limiter.acquire()  # transitions to half-open, claims the probe

        with pytest.raises(RuntimeError, match="probe already in flight"):
            await limiter.acquire()

        # Probe completes successfully — circuit closes, calls flow again.
        limiter.record_success()
        assert limiter.circuit_state == "closed"
        await limiter.acquire()

    @pytest.mark.asyncio
    async def test_failed_probe_reopens_and_releases_probe_slot(self):
        limiter = RateLimiter(
            min_interval=0.0,
            name="test",
            circuit_threshold=1,
            circuit_base_cooldown=0.0,
        )
        limiter.record_error()
        limiter._backoff_until = 0.0

        await limiter.acquire()  # half-open probe
        limiter.record_error()  # probe failed — circuit re-opens

        assert not limiter._probe_in_flight
        limiter._backoff_until = 0.0
        limiter._circuit_open_until = 0.0
        await limiter.acquire()  # next probe is admitted again


# ---------------------------------------------------------------------------
# .env writing safety
# ---------------------------------------------------------------------------


class TestUpdateEnvFile:
    def test_rejects_newline_injection(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        monkeypatch.setenv("ENV_FILE", str(env_file))

        with pytest.raises(ValueError, match="control characters"):
            update_env_file({"GOOGLE_API_KEY": "abc\nEVIL_VAR=1"})

        assert not env_file.exists()

    def test_rejects_invalid_variable_name(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        monkeypatch.setenv("ENV_FILE", str(env_file))

        with pytest.raises(ValueError, match="Invalid environment variable"):
            update_env_file({"BAD NAME": "value"})

    def test_quotes_values_with_spaces_and_hashes(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        monkeypatch.setenv("ENV_FILE", str(env_file))

        update_env_file({"SUNO_API_KEY": "abc def#ghi"})

        content = env_file.read_text(encoding="utf-8")
        assert 'SUNO_API_KEY="abc def#ghi"' in content

    def test_strips_whitespace_and_updates_in_place(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# comment\nGOOGLE_API_KEY=old\nOTHER=keep\n", encoding="utf-8"
        )
        monkeypatch.setenv("ENV_FILE", str(env_file))

        update_env_file({"GOOGLE_API_KEY": "  newkey  "})

        lines = env_file.read_text(encoding="utf-8").splitlines()
        assert "GOOGLE_API_KEY=newkey" in lines
        assert "OTHER=keep" in lines
        assert lines.count("# comment") == 1


# ---------------------------------------------------------------------------
# Suno provider: paid submissions must never be retried by poll/download
# ---------------------------------------------------------------------------


class TestSunoMusicProvider:
    @pytest.mark.asyncio
    async def test_poll_failure_does_not_resubmit(self, tmp_path, monkeypatch):
        """A transient poll failure retries the SAME task, never resubmits."""
        from server.providers.music import suno as suno_module
        from server.providers.music.suno import SunoMusicProvider

        monkeypatch.setattr(suno_module, "POLL_INTERVAL", 0)

        submits = 0
        polls = 0

        def api_handler(request: httpx.Request) -> httpx.Response:
            nonlocal submits, polls
            if request.url.path == "/api/v1/generate":
                submits += 1
                return httpx.Response(
                    200, json={"code": 200, "data": {"taskId": "task-1"}}
                )
            if request.url.path == "/api/v1/generate/record-info":
                polls += 1
                if polls == 1:
                    return httpx.Response(500)  # transient poll failure
                if polls == 2:
                    # Pending state where "data" is null — must not crash
                    return httpx.Response(200, json={"code": 200, "data": None})
                return httpx.Response(
                    200,
                    json={
                        "code": 200,
                        "data": {
                            "status": "SUCCESS",
                            "response": {
                                "sunoData": [
                                    {
                                        "audioUrl": "https://cdn.example.com/song.mp3",
                                        "title": "Test Song",
                                        "duration": 42,
                                    }
                                ]
                            },
                        },
                    },
                )
            raise AssertionError(f"unexpected request: {request.url}")

        downloads = 0
        seen_download_headers = {}

        def download_handler(request: httpx.Request) -> httpx.Response:
            nonlocal downloads
            downloads += 1
            seen_download_headers.update(dict(request.headers))
            return httpx.Response(200, content=b"audio-bytes")

        provider = SunoMusicProvider(api_key="secret-key", audio_dir=str(tmp_path))
        provider._rate_limiter = RateLimiter(
            calls_per_minute=100, min_interval=0.0, name="suno_test"
        )
        client = provider._get_client()
        client._transport = httpx.MockTransport(api_handler)
        monkeypatch.setattr(
            provider,
            "_download_client",
            lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(download_handler)
            ),
        )

        result = await provider.generate("ambient chill instrumental")

        assert submits == 1, "poll/download failures must not resubmit"
        assert polls == 3
        assert downloads == 1
        assert result["task_id"] == "task-1"
        assert result["title"] == "Test Song"

        # The CDN download must not carry the API Bearer token.
        assert "authorization" not in seen_download_headers

        await provider.aclose()

    @pytest.mark.asyncio
    async def test_insufficient_credits_is_non_retryable(
        self, tmp_path, monkeypatch
    ):
        from server.providers.music.suno import SunoMusicProvider

        submits = 0

        def api_handler(request: httpx.Request) -> httpx.Response:
            nonlocal submits
            submits += 1
            return httpx.Response(429, json={"msg": "insufficient credits"})

        provider = SunoMusicProvider(api_key="secret-key", audio_dir=str(tmp_path))
        provider._rate_limiter = RateLimiter(
            calls_per_minute=100, min_interval=0.0, name="suno_test"
        )
        client = provider._get_client()
        client._transport = httpx.MockTransport(api_handler)

        with pytest.raises(NonRetryableError, match="insufficient credits"):
            await provider.generate("lo-fi jazz")

        assert submits == 1
        assert provider._rate_limiter.consecutive_errors == 1

        await provider.aclose()


# ---------------------------------------------------------------------------
# Gemini provider: the API key must never ride the URL
# ---------------------------------------------------------------------------


class TestGeminiKeyHandling:
    @pytest.mark.asyncio
    async def test_api_key_in_header_never_in_url(self):
        provider = GeminiScriptWriterProvider(api_key="super-secret-key")
        provider._rate_limiter = RateLimiter(
            calls_per_minute=100, min_interval=0.0, name="gemini_test"
        )
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {
                                "parts": [{"text": "Hello there. Great song."}]
                            },
                        }
                    ]
                },
            )

        client = provider._get_client()
        client._transport = httpx.MockTransport(handler)

        result = await provider.write_break({"dj_name": "DJ"})

        assert result["script_text"]
        assert "super-secret-key" not in captured["url"]
        assert "key=" not in captured["url"]
        assert captured["headers"]["x-goog-api-key"] == "super-secret-key"

        await provider.aclose()


class TestCleanForTts:
    def test_complete_final_sentence_is_kept_when_truncated(self):
        """MAX_TOKENS exactly at a sentence boundary must not lose a sentence."""
        text = "First sentence. Second sentence."
        assert _clean_for_tts(text, truncated=True) == text

    def test_incomplete_final_sentence_is_trimmed(self):
        text = "First sentence. Second sen"
        assert _clean_for_tts(text, truncated=True) == "First sentence."


class TestFishAudioVoiceProvider:
    @pytest.mark.asyncio
    async def test_render_invalid_voice_id_fallback(self, tmp_path):
        """Fish Audio should fall back to a default voice immediately if voice_id is invalid."""
        from server.providers.voice.fish import FishAudioVoiceProvider

        class FakeResponse:
            status_code = 200
            content = b"fake-audio-bytes"

            def raise_for_status(self):
                pass

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def post(self, url, json, headers=None):
                self.calls.append((url, dict(json) if json else {}, headers))
                return FakeResponse()

        client = FakeClient()
        provider = FishAudioVoiceProvider(api_key="test-key", audio_dir=str(tmp_path))
        provider._get_client = lambda: client

        # Render with an invalid voice ID (e.g. "Aoede")
        res_path = await provider.render("Hello", {"voice_id": "Aoede"})

        # Verify it fell back to Raddo ID: "100b9bbcdc52442bb9a710a5c9ee1bf8"
        assert len(client.calls) == 1
        url, json_data, headers = client.calls[0]
        assert json_data["reference_id"] == "100b9bbcdc52442bb9a710a5c9ee1bf8"
        assert res_path.endswith(".wav")

    @pytest.mark.asyncio
    async def test_render_not_found_voice_id_retry(self, tmp_path):
        """Fish Audio should retry with a default voice if the API returns 400 Reference not found."""
        from server.providers.voice.fish import FishAudioVoiceProvider

        class FakeResponse400:
            status_code = 400
            text = "Reference not found"

            def raise_for_status(self):
                import httpx
                response = httpx.Response(status_code=400, text="Reference not found")
                raise httpx.HTTPStatusError("400 error", request=None, response=response)

            def json(self):
                return {"message": "Reference not found", "status": 400}

        class FakeResponse200:
            status_code = 200
            content = b"fake-audio-bytes"

            def raise_for_status(self):
                pass

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def post(self, url, json, headers=None):
                self.calls.append((url, dict(json) if json else {}, headers))
                if len(self.calls) == 1:
                    return FakeResponse400()
                return FakeResponse200()

        client = FakeClient()
        provider = FishAudioVoiceProvider(api_key="test-key", audio_dir=str(tmp_path))
        provider._get_client = lambda: client

        # Pass a 32-character hex voice ID that matches the regex, but isn't real
        fake_uuid = "a" * 32
        res_path = await provider.render("Hello", {"voice_id": fake_uuid})

        # Verify it tried the fake voice first, got 400, then retried with Raddo
        assert len(client.calls) == 2

        # First call uses the requested fake voice
        assert client.calls[0][1]["reference_id"] == fake_uuid

        # Second call falls back to Raddo
        assert client.calls[1][1]["reference_id"] == "100b9bbcdc52442bb9a710a5c9ee1bf8"
        assert res_path.endswith(".wav")
