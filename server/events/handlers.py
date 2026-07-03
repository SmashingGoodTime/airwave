"""Default event handlers for the radio application.

Registers handlers for logging, recovery tracking, and extensibility.
"""

import logging
from typing import Any

from server.events.emitter import EventBus

logger = logging.getLogger(__name__)

# Track provider error/recovery state for dashboard
_provider_state: dict[str, str] = {
    "music": "unknown",
    "scriptwriter": "unknown",
    "voice": "unknown",
}


def _log_event(event: str, data: dict[str, Any]) -> None:
    """Log any emitted event at appropriate level.

    Args:
        event: The event name.
        data: The event data payload.
    """
    if "error" in event or "critical" in event or "failed" in event:
        logger.warning("Event: %s | %s", event, data)
    elif "warning" in event or "low" in event:
        logger.warning("Event: %s | %s", event, data)
    else:
        logger.info("Event: %s | %s", event, data)


def _on_track_generated(event: str, data: dict[str, Any]) -> None:
    """Handle track.generated events.

    Args:
        event: The event name.
        data: Event data with track_id, title, style, duration.
    """
    logger.info(
        "Track generated: id=%s title='%s' style='%s' duration=%.0fs",
        data.get("track_id"),
        data.get("title", "?"),
        data.get("style", "?"),
        data.get("duration") or 0,
    )


def _on_track_started(event: str, data: dict[str, Any]) -> None:
    """Handle track.started events.

    Args:
        event: The event name.
        data: Event data with track_id and title.
    """
    logger.info(
        "Now playing: '%s' (id=%s)",
        data.get("title", "Unknown"),
        data.get("track_id"),
    )


def _on_buffer_warning(event: str, data: dict[str, Any]) -> None:
    """Handle buffer.low and buffer.critical events.

    Args:
        event: The event name.
        data: Event data with ready count and target.
    """
    ready = data.get("ready", 0)
    target = data.get("target", 5)

    if event == "buffer.critical":
        logger.critical(
            "BUFFER CRITICAL: %d/%d tracks ready — dead air imminent!",
            ready,
            target,
        )
    else:
        logger.warning(
            "Buffer low: %d/%d tracks ready", ready, target
        )


def _on_provider_error(event: str, data: dict[str, Any]) -> None:
    """Handle provider.error events and track state.

    Args:
        event: The event name.
        data: Event data with provider name and error.
    """
    provider = data.get("provider", "unknown")
    error = data.get("error", "unknown error")
    _provider_state[provider] = "error"
    logger.error(
        "Provider error [%s]: %s", provider, error
    )


def _on_provider_recovered(event: str, data: dict[str, Any]) -> None:
    """Handle provider.recovered events.

    Args:
        event: The event name.
        data: Event data with provider name.
    """
    provider = data.get("provider", "unknown")
    _provider_state[provider] = "ok"
    logger.info("Provider recovered: %s", provider)


def _on_break_generated(event: str, data: dict[str, Any]) -> None:
    """Handle break.generated events.

    Args:
        event: The event name.
        data: Event data with break_id and duration.
    """
    logger.info(
        "DJ break generated: id=%s duration=%.1fs has_audio=%s",
        data.get("break_id"),
        data.get("duration") or 0,
        data.get("has_audio", False),
    )


def _on_disk_warning(event: str, data: dict[str, Any]) -> None:
    """Handle disk space warnings.

    Args:
        event: The event name.
        data: Event data with free_gb and usage_pct.
    """
    free_gb = data.get("free_gb", 0)
    usage_pct = data.get("usage_pct", 0)

    if "critical" in event:
        logger.critical(
            "DISK SPACE CRITICAL: %.2f GB free (%.1f%% used)",
            free_gb,
            usage_pct,
        )
    else:
        logger.warning(
            "Disk space warning: %.2f GB free (%.1f%% used)",
            free_gb,
            usage_pct,
        )


def get_provider_state() -> dict[str, str]:
    """Get the current provider error/recovery state.

    Returns:
        Dict mapping provider names to their current state.
    """
    return dict(_provider_state)


def _on_show_transition(event: str, data: dict[str, Any]) -> None:
    """Handle show.started and show.ended events.

    Args:
        event: The event name.
        data: Event data with show details.
    """
    if event == "show.started":
        logger.info(
            "Show started: '%s' (type=%s, id=%s)",
            data.get("show_name", "?"),
            data.get("show_type", "?"),
            data.get("show_id"),
        )
    else:
        logger.info(
            "Show ended: id=%s type=%s",
            data.get("show_id"),
            data.get("show_type", "?"),
        )


def _on_talk_segment(event: str, data: dict[str, Any]) -> None:
    """Handle talk_segment events.

    Args:
        event: The event name.
        data: Event data with segment details.
    """
    if "generated" in event:
        logger.info(
            "Talk segment generated: topic='%s' type=%s duration=%.1fs",
            data.get("topic", "?"),
            data.get("type", "?"),
            data.get("duration") or 0,
        )
    else:
        logger.info("Event: %s | %s", event, data)


def _on_call_event(event: str, data: dict[str, Any]) -> None:
    """Handle call-related events.

    Args:
        event: The event name.
        data: Event data with call details.
    """
    action = event.split(".")[-1] if "." in event else event
    session_id = data.get("session_id", "?")

    if event == "call.moderation_flag":
        logger.warning(
            "Call moderation flag: session=%s flags=%s",
            session_id,
            data.get("flags", "?"),
        )
    else:
        logger.info(
            "Call %s: session=%s %s",
            action,
            session_id,
            (
                f"duration={data['duration']:.1f}s"
                if data.get("duration") is not None
                else ""
            ),
        )


def setup_default_handlers(bus: EventBus) -> None:
    """Register all default handlers on the event bus.

    Args:
        bus: The EventBus instance to register handlers on.
    """
    # General logging
    bus.on("track.started", _on_track_started)
    bus.on("track.ended", _log_event)

    # Track-specific (also covers general logging for track.generated)
    bus.on("track.generated", _on_track_generated)

    # Buffer alerts
    bus.on("buffer.low", _on_buffer_warning)
    bus.on("buffer.critical", _on_buffer_warning)

    # DJ breaks
    bus.on("break.generated", _on_break_generated)
    bus.on("break.started", _log_event)
    bus.on("break.ended", _log_event)

    # Provider health
    bus.on("provider.error", _on_provider_error)
    bus.on("provider.recovered", _on_provider_recovered)

    # System
    bus.on("system.disk_warning", _on_disk_warning)
    bus.on("system.disk_critical", _on_disk_warning)

    # Shows
    bus.on("show.started", _on_show_transition)
    bus.on("show.ended", _on_show_transition)

    # Talk segments
    bus.on("talk_segment.generated", _on_talk_segment)
    bus.on("talk_segment.started", _on_talk_segment)
    bus.on("talk_segment.ended", _on_talk_segment)

    # Calls
    bus.on("call.incoming", _on_call_event)
    bus.on("call.connected", _on_call_event)
    bus.on("call.screening", _on_call_event)
    bus.on("call.on_air", _on_call_event)
    bus.on("call.ended", _on_call_event)
    bus.on("call.queued", _on_call_event)
    bus.on("call.moderation_flag", _on_call_event)

    logger.info("Default event handlers registered")
