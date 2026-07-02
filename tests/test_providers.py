"""Tests for provider base classes, registry, and mock implementations."""

import pytest
import pytest_asyncio

from server.providers.base import MusicProvider, ScriptWriterProvider, VoiceProvider
from server.providers.scriptwriter.google import GeminiScriptWriterProvider
from server.providers.registry import ProviderDefinition, ProviderRegistry

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

        assert result == {
            "provider": "candidate_music",
            "healthy": False,
            "status": "error",
            "error": "candidate exploded",
        }


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
