"""Abstract base classes for all provider interfaces."""

from abc import ABC, abstractmethod
from typing import Any


class MusicProvider(ABC):
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


class ScriptWriterProvider(ABC):
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

    async def write_talk_segment(self, context: dict) -> dict:
        """Generate a talk show segment script (monologue or conversation).

        For monologues, returns plain text in script_text.
        For conversations, returns structured JSON in script_text:
        [{"speaker": "name", "text": "line"}, ...]

        Args:
            context: Dictionary containing:
                - topic: The topic title and prompt
                - segment_type: "monologue", "conversation", "debate", or "interview"
                - speakers: List of speaker configs with name and personality
                - show_name: The show's name
                - host_personality: Host personality prompt
                - previous_segments: Summaries of recent segments for continuity
                - target_duration: Target segment length in seconds
                - current_time: Station local time

        Returns:
            A dict with script_text, speakers list, estimated_duration, and metadata.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support talk segment generation"
        )

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


class VoiceProvider(ABC):
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


class TelephonyProvider(ABC):
    """Abstract base class for telephony providers handling listener call-ins."""

    @abstractmethod
    async def provision_number(self, area_code: str = "") -> dict:
        """Provision a phone number for incoming calls.

        Args:
            area_code: Preferred area code for the number.

        Returns:
            A dict with number and provider-specific ID.
        """
        ...

    @abstractmethod
    async def list_numbers(self) -> list[dict]:
        """List provisioned phone numbers.

        Returns:
            A list of dicts describing active numbers.
        """
        ...

    @abstractmethod
    async def accept_call(self, call_sid: str, webhook_url: str) -> dict:
        """Accept an incoming call and connect it.

        Args:
            call_sid: Provider-specific call session identifier.
            webhook_url: URL for the provider to send audio/events to.

        Returns:
            A dict with connection status and metadata.
        """
        ...

    @abstractmethod
    async def bridge_to_stream(self, call_sid: str, stream_url: str) -> bool:
        """Bridge call audio to a WebSocket stream for live broadcast.

        Args:
            call_sid: Provider-specific call session identifier.
            stream_url: WebSocket URL to stream audio to.

        Returns:
            True if the bridge was established successfully.
        """
        ...

    @abstractmethod
    async def record_call(self, call_sid: str) -> dict:
        """Start recording a call.

        Args:
            call_sid: Provider-specific call session identifier.

        Returns:
            A dict with recording ID and status.
        """
        ...

    @abstractmethod
    async def end_call(self, call_sid: str) -> bool:
        """Hang up an active call.

        Args:
            call_sid: Provider-specific call session identifier.

        Returns:
            True if the call was ended successfully.
        """
        ...

    @abstractmethod
    async def get_recording(self, recording_sid: str, output_dir: str) -> str:
        """Download a call recording to a local file.

        Args:
            recording_sid: Provider-specific recording identifier.
            output_dir: Directory to save the recording to.

        Returns:
            File path to the downloaded recording.
        """
        ...

    @abstractmethod
    async def check_status(self) -> bool:
        """Check whether the telephony provider is available.

        Returns:
            True if the provider is operational, False otherwise.
        """
        ...


class ConversationAIProvider(ABC):
    """Abstract base class for real-time voice AI conversation providers.

    Used for live caller interactions where the AI responds to callers
    in real time with voice.
    """

    @abstractmethod
    async def start_session(
        self, system_prompt: str, voice_config: dict
    ) -> str:
        """Start a real-time conversation session.

        Args:
            system_prompt: Instructions for the AI persona.
            voice_config: Voice settings for the AI's speech.

        Returns:
            A session ID string for managing the session.
        """
        ...

    @abstractmethod
    async def connect_audio_stream(
        self, session_id: str, audio_stream: Any
    ) -> None:
        """Connect a bidirectional audio stream to the conversation session.

        Args:
            session_id: The active session identifier.
            audio_stream: Bidirectional audio stream (e.g., WebSocket).
        """
        ...

    @abstractmethod
    async def end_session(self, session_id: str) -> dict:
        """End a conversation session and retrieve results.

        Args:
            session_id: The active session identifier.

        Returns:
            A dict with transcript, duration, and recording_path.
        """
        ...

    @abstractmethod
    async def check_status(self) -> bool:
        """Check whether the conversation AI provider is available.

        Returns:
            True if the provider is operational, False otherwise.
        """
        ...
