"""Helpers for working with provider voice configuration blobs."""

import json


def parse_voice_settings(raw: str | None, voice_id: str | None = None) -> dict:
    """Parse a voice-settings JSON blob into a voice config dict.

    Voice settings are stored as free-form JSON text on config rows;
    malformed or empty blobs degrade to an empty dict rather than
    failing. When *voice_id* is given it is stamped onto the result
    (overriding any voice_id inside the blob).

    Args:
        raw: JSON text of provider-specific voice settings, or None.
        voice_id: Optional voice identifier to include in the config.

    Returns:
        A dict ready to pass to ``VoiceProvider.render``.
    """
    settings: dict = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                settings = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    if voice_id is not None:
        settings["voice_id"] = voice_id
    return settings
