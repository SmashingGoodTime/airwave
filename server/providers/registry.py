"""Provider registry managing configured provider implementations."""

from __future__ import annotations

import importlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from server.events.emitter import event_bus
from server.providers.base import (
    MusicProvider,
    ScriptWriterProvider,
    VoiceProvider,
)

logger = logging.getLogger(__name__)

# Cache health results for this many seconds to avoid hammering APIs on
# every dashboard poll / WebSocket snapshot.
HEALTH_CACHE_TTL = 60.0

ProviderInstance = MusicProvider | ScriptWriterProvider | VoiceProvider
ProviderFactory = Callable[["ProviderFactoryContext"], ProviderInstance]


@dataclass(frozen=True)
class ProviderDefinition:
    """Declarative metadata for a concrete provider implementation."""

    key: str
    capability: str
    display_name: str
    module_path: str
    class_name: str
    required_env: tuple[str, ...]
    factory: ProviderFactory

    def is_configured(self, config: object) -> bool:
        """Return True when every required config value is present."""
        return all(bool(getattr(config, env_name, "")) for env_name in self.required_env)

    def create(self, config: object) -> ProviderInstance:
        """Import and instantiate the concrete provider."""
        module = importlib.import_module(self.module_path)
        provider_cls = getattr(module, self.class_name)
        return self.factory_with_class(config, provider_cls)

    def factory_with_class(self, config: object, provider_cls: type) -> ProviderInstance:
        """Instantiate a provider class using this definition's factory."""
        return self.factory(ProviderFactoryContext(config=config, provider_cls=provider_cls))


@dataclass(frozen=True)
class ProviderFactoryContext:
    """Context passed to provider factories."""

    config: object
    provider_cls: type

    @property
    def audio_dir(self) -> str:
        """Return configured audio directory or the default."""
        return getattr(self.config, "AUDIO_DIR", "./audio")

    def value(self, env_name: str) -> str:
        """Return a string config value."""
        return getattr(self.config, env_name, "")


def _api_key_provider(env_name: str, *, include_audio_dir: bool) -> ProviderFactory:
    """Build a factory for providers constructed with an API key."""

    def _factory(ctx: ProviderFactoryContext) -> ProviderInstance:
        kwargs = {"api_key": ctx.value(env_name)}
        if include_audio_dir:
            kwargs["audio_dir"] = ctx.audio_dir
        return ctx.provider_cls(**kwargs)

    return _factory


def sanitize_provider_error(exc: Exception) -> str:
    """Build an error string safe to log and return to browsers.

    Never includes URLs or query strings, which can carry API keys
    (e.g. httpx exception messages embed the full request URL).

    Args:
        exc: The exception to describe.

    Returns:
        Exception class name plus its message when the message is safe,
        otherwise the class name alone.
    """
    message = str(exc)
    if not message or "://" in message or "key=" in message.lower():
        return type(exc).__name__
    return f"{type(exc).__name__}: {message}"


def _suno_factory(ctx: ProviderFactoryContext) -> ProviderInstance:
    """Build a Suno music provider."""
    kwargs = {
        "api_key": ctx.value("SUNO_API_KEY"),
        "audio_dir": ctx.audio_dir,
    }
    model = ctx.value("SUNO_MODEL")
    if model:
        kwargs["model"] = model
    return ctx.provider_cls(**kwargs)


def _gemini_factory(ctx: ProviderFactoryContext) -> ProviderInstance:
    """Build a Gemini scriptwriter provider with a configurable model."""
    kwargs = {"api_key": ctx.value("GOOGLE_API_KEY")}
    model = ctx.value("GEMINI_MODEL")
    if model:
        kwargs["model"] = model
    return ctx.provider_cls(**kwargs)


def _fish_factory(ctx: ProviderFactoryContext) -> ProviderInstance:
    """Build a Fish Audio voice provider with a configurable model."""
    kwargs = {
        "api_key": ctx.value("FISH_AUDIO_API_KEY"),
        "audio_dir": ctx.audio_dir,
    }
    model = ctx.value("FISH_AUDIO_MODEL")
    if model:
        kwargs["model"] = model
    return ctx.provider_cls(**kwargs)


BUILTIN_PROVIDER_DEFINITIONS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        key="suno",
        capability="music",
        display_name="Suno",
        module_path="server.providers.music.suno",
        class_name="SunoMusicProvider",
        required_env=("SUNO_API_KEY",),
        factory=_suno_factory,
    ),
    ProviderDefinition(
        key="google_scriptwriter",
        capability="scriptwriter",
        display_name="Gemini Scriptwriter",
        module_path="server.providers.scriptwriter.google",
        class_name="GeminiScriptWriterProvider",
        required_env=("GOOGLE_API_KEY",),
        factory=_gemini_factory,
    ),
    ProviderDefinition(
        key="fish_audio",
        capability="voice",
        display_name="Fish Audio",
        module_path="server.providers.voice.fish",
        class_name="FishAudioVoiceProvider",
        required_env=("FISH_AUDIO_API_KEY",),
        factory=_fish_factory,
    ),
)

VOICE_PROVIDER_PREFERENCE = ("fish_audio",)
CAPABILITIES = ("music", "scriptwriter", "voice")


class ProviderRegistry:
    """Singleton registry holding references to configured providers.

    Providers are declared as ``ProviderDefinition`` records. The registry
    handles import, construction, fallback priority, active voice selection,
    and health caching without leaking concrete provider classes to engine code.
    """

    _instance: Optional[ProviderRegistry] = None

    def __init__(
        self,
        definitions: tuple[ProviderDefinition, ...] = BUILTIN_PROVIDER_DEFINITIONS,
    ) -> None:
        self._definitions = definitions
        self._music: Optional[MusicProvider] = None
        self._scriptwriter: Optional[ScriptWriterProvider] = None
        self._voice: Optional[VoiceProvider] = None
        self._voice_providers: dict[str, VoiceProvider] = {}
        self._provider_keys: dict[str, str] = {}
        self._provider_names: dict[str, str] = {}
        self._health_cache: dict = {}
        self._health_cache_time: float = 0.0
        # Last observed healthy state per capability, kept across cache
        # clears and reinitialization so an unhealthy -> healthy transition
        # (including "operator fixed the API key") emits provider.recovered.
        self._last_health_state: dict[str, bool] = {}

    @classmethod
    def get_instance(cls) -> ProviderRegistry:
        """Return the singleton ProviderRegistry instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_music_provider(self) -> Optional[MusicProvider]:
        """Return the configured music provider, if any."""
        return self._music

    def get_scriptwriter_provider(self) -> Optional[ScriptWriterProvider]:
        """Return the configured scriptwriter provider, if any."""
        return self._scriptwriter

    def get_voice_provider(self) -> Optional[VoiceProvider]:
        """Return the configured voice provider, if any."""
        return self._voice

    def list_voice_providers(self) -> list[dict]:
        """Return metadata about all available voice providers."""
        active_key = None
        for key, provider in self._voice_providers.items():
            if provider is self._voice:
                active_key = key
                break
        return [
            {
                "key": key,
                "name": self._provider_names.get(key, key),
                "active": key == active_key,
            }
            for key in self._voice_providers
        ]

    def get_voice_provider_by_key(self, key: str) -> Optional[VoiceProvider]:
        """Return a specific voice provider by its registry key."""
        return self._voice_providers.get(key)

    def set_active_voice_provider(self, key: str) -> bool:
        """Switch the active voice provider."""
        provider = self._voice_providers.get(key)
        if provider is None:
            return False
        self._voice = provider
        self._provider_keys["voice"] = key
        self._clear_health_cache()
        return True

    async def initialize(self, config: object) -> None:
        """Read config and instantiate provider implementations.

        Providers degrade gracefully: missing keys simply leave capabilities
        unconfigured, and failed providers are logged without stopping startup.
        """
        logger.info("Initializing provider registry...")
        await self._reset_providers()

        for definition in self._definitions:
            if not definition.is_configured(config):
                continue
            if definition.capability != "voice" and self._has_capability(definition.capability):
                continue

            try:
                provider = definition.create(config)
            except Exception as exc:
                logger.error(
                    "Failed to initialize %s provider %s: %s",
                    definition.capability,
                    definition.display_name,
                    exc,
                )
                continue

            self._register_provider(definition, provider)
            logger.info(
                "%s provider initialized: %s",
                definition.capability.capitalize(),
                definition.display_name,
            )

        self._select_default_voice_provider()
        self._log_configuration_summary()

    async def check_capability_health(self, capability: str, config: object) -> dict:
        """Check one provider capability against a supplied config object.

        This constructs a temporary provider from the matching provider
        definition and does not register it on the singleton. It is used for
        testing candidate credentials before they are saved.
        """
        known_capabilities = {definition.capability for definition in self._definitions}
        known_capabilities.update(CAPABILITIES)
        if capability not in known_capabilities:
            return {
                "provider": capability,
                "healthy": False,
                "status": "unknown_provider",
                "error": f"Unknown provider type: {capability}",
            }

        for definition in self._definitions:
            if definition.capability != capability:
                continue
            if not definition.is_configured(config):
                continue

            provider: Optional[ProviderInstance] = None
            try:
                provider = definition.create(config)
                healthy = await provider.check_status()
            except Exception as exc:
                logger.warning(
                    "Candidate health check failed for %s provider %s: %s",
                    capability,
                    definition.display_name,
                    sanitize_provider_error(exc),
                )
                return {
                    "provider": definition.key,
                    "healthy": False,
                    "status": "error",
                    "error": sanitize_provider_error(exc),
                }
            finally:
                # The throwaway candidate provider is never registered, so
                # close it here or its connection pool leaks.
                if provider is not None:
                    await self._close_provider(provider)

            return {
                "provider": definition.key,
                "healthy": healthy,
                "status": "healthy" if healthy else "unhealthy",
                "error": None if healthy else "Provider reported unhealthy",
            }

        return {
            "provider": None,
            "healthy": False,
            "status": "unconfigured",
            "error": "Provider is not configured",
        }

    async def _reset_providers(self) -> None:
        """Close and clear configured provider instances before reinitialization.

        Old instances are explicitly closed so their HTTP connection pools
        are released instead of leaking when providers are replaced.
        """
        stale = {
            id(provider): provider
            for provider in (
                self._music,
                self._scriptwriter,
                self._voice,
                *self._voice_providers.values(),
            )
            if provider is not None
        }
        for provider in stale.values():
            await self._close_provider(provider)

        self._music = None
        self._scriptwriter = None
        self._voice = None
        self._voice_providers = {}
        self._provider_keys = {}
        self._provider_names = {}
        self._clear_health_cache()

    @staticmethod
    async def _close_provider(provider: object) -> None:
        """Best-effort close of a provider's resources."""
        closer = getattr(provider, "aclose", None)
        if closer is None:
            return
        try:
            await closer()
        except Exception as exc:
            logger.warning(
                "Error closing %s: %s", type(provider).__name__, exc
            )

    def _clear_health_cache(self) -> None:
        """Invalidate cached health results."""
        self._health_cache = {}
        self._health_cache_time = 0.0

    def _has_capability(self, capability: str) -> bool:
        """Return True when a non-voice capability is already configured."""
        return {
            "music": self._music,
            "scriptwriter": self._scriptwriter,
        }.get(capability) is not None

    def _register_provider(
        self,
        definition: ProviderDefinition,
        provider: ProviderInstance,
    ) -> None:
        """Store an initialized provider for its capability."""
        self._provider_names[definition.key] = definition.display_name

        if definition.capability == "music":
            self._music = provider  # type: ignore[assignment]
            self._provider_keys["music"] = definition.key
        elif definition.capability == "scriptwriter":
            self._scriptwriter = provider  # type: ignore[assignment]
            self._provider_keys["scriptwriter"] = definition.key
        elif definition.capability == "voice":
            voice = provider  # type: ignore[assignment]
            self._voice_providers[definition.key] = voice

    def _select_default_voice_provider(self) -> None:
        """Choose the active voice provider by stable preference order."""
        for key in VOICE_PROVIDER_PREFERENCE:
            if self.set_active_voice_provider(key):
                return

        if self._voice_providers:
            key, provider = next(iter(self._voice_providers.items()))
            self._voice = provider
            self._provider_keys["voice"] = key
        else:
            logger.warning("No voice providers configured")

    def _log_configuration_summary(self) -> None:
        """Log how many capabilities were configured."""
        configured = sum(
            1
            for provider in [
                self._music,
                self._scriptwriter,
                self._voice,
            ]
            if provider is not None
        )
        logger.info("Provider registry ready: %d/3 providers configured", configured)

    async def check_all_health(self, force: bool = False) -> dict:
        """Check health status of all configured providers.

        Results are cached for ``HEALTH_CACHE_TTL`` seconds to prevent
        the dashboard's frequent polling from triggering redundant API calls.
        """
        now = time.monotonic()
        if (
            not force
            and self._health_cache
            and (now - self._health_cache_time) < HEALTH_CACHE_TTL
        ):
            return self._health_cache

        results = {}

        for name, provider in [
            ("music", self._music),
            ("scriptwriter", self._scriptwriter),
            ("voice", self._voice),
        ]:
            key = self._provider_keys.get(name)
            if provider is None:
                results[name] = {"status": "unconfigured", "healthy": False}
            else:
                try:
                    healthy = await provider.check_status()
                    status = "healthy" if healthy else "unhealthy"

                    # Surface circuit breaker state so the dashboard can
                    # show operators why a provider is down.
                    limiter = getattr(provider, "_rate_limiter", None) or getattr(
                        provider, "_health_limiter", None
                    )
                    circuit = (
                        getattr(limiter, "circuit_state", "unknown")
                        if limiter
                        else "unknown"
                    )
                    if circuit == "open":
                        status = "circuit_open"

                    results[name] = {
                        "status": status,
                        "healthy": healthy,
                        "provider": key,
                        "circuit": circuit,
                    }
                except Exception as exc:
                    logger.warning(
                        "Health check failed for %s: %s",
                        name,
                        sanitize_provider_error(exc),
                    )
                    results[name] = {
                        "status": "error",
                        "healthy": False,
                        "provider": key,
                        "error": sanitize_provider_error(exc),
                    }

        # Emit recovery events on unhealthy -> healthy transitions so
        # dashboards and custom handlers hear about providers coming back.
        for name, result in results.items():
            healthy = bool(result.get("healthy"))
            if self._last_health_state.get(name) is False and healthy:
                event_bus.emit(
                    "provider.recovered",
                    {"provider": name, "key": result.get("provider")},
                )
            self._last_health_state[name] = healthy

        self._health_cache = results
        self._health_cache_time = now
        return results
