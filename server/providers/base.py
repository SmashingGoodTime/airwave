"""Abstract base classes for all provider interfaces."""

from abc import ABC, abstractmethod


class Provider(ABC):
    """Common base for all provider types.

    Provides resource-lifecycle hooks shared by every capability so the
    registry can release provider resources (HTTP connection pools, sockets)
    when providers are replaced or discarded.
    """

    async def aclose(self) -> None:
        """Release any resources held by the provider.

        Called by the registry when a provider instance is being discarded
        (reinitialization, throwaway health-check providers). The default
        implementation is a no-op; providers holding HTTP clients or other
        connections should override it.
        """
        return None


class MusicProvider(Provider):
    """Abstract base class for music generation providers."""

    @abstractmethod
    async def generate(self, prompt: str, duration: int = 180) -> dict:
        """Generate a music track from a text prompt.

        Args:
            prompt: Text description of the desired music style.
            duration: Target duration in seconds.

        Returns:
            A dict containing generation result with at minimum a task ID
            or file path.
        """
        ...

    @abstractmethod
    async def check_status(self) -> bool:
        """Check whether the music provider is available and authenticated.

        Returns:
            True if the provider is operational, False otherwise.
        """
        ...


class ScriptWriterProvider(Provider):
    """Abstract base class for DJ script generation providers."""

    @abstractmethod
    async def write_break(self, context: dict) -> dict:
        """Generate a DJ break script given playback context.

        Args:
            context: Dictionary with recent tracks, time, announcements, etc.

        Returns:
            A dict containing the generated script text and metadata.
        """
        ...

    async def rewrite_prompt(self, prompt: str, instruction: str) -> str:
        """Rewrite a text prompt according to an instruction.

        Used to add creative variation to music style prompts before
        generation. The default implementation returns the prompt unchanged;
        providers with LLM access should override this.

        Args:
            prompt: The original prompt text.
            instruction: How to rewrite (e.g. "vary instruments and tempo").

        Returns:
            The rewritten prompt string.
        """
        return prompt

    @abstractmethod
    async def check_status(self) -> bool:
        """Check whether the scriptwriter provider is available.

        Returns:
            True if the provider is operational, False otherwise.
        """
        ...


class VoiceProvider(Provider):
    """Abstract base class for text-to-speech voice providers."""

    @abstractmethod
    async def render(self, text: str, voice_config: dict) -> str:
        """Render text to speech audio.

        Args:
            text: The script text to synthesize.
            voice_config: Voice settings including voice ID and parameters.

        Returns:
            File path to the rendered audio file.
        """
        ...

    @abstractmethod
    async def list_voices(self) -> list:
        """List available voices from the provider.

        Returns:
            A list of dicts describing available voices.
        """
        ...

    @abstractmethod
    async def check_status(self) -> bool:
        """Check whether the voice provider is available.

        Returns:
            True if the provider is operational, False otherwise.
        """
        ...


# NOTE: TelephonyProvider / ConversationAIProvider (live listener
# call-ins) were removed as unbuilt scaffolding. The Liquidsoap harbor
# input in station.liq remains the integration point should a call-in
# feature land; a new capability would subclass Provider and register
# a ProviderDefinition like the existing three.
