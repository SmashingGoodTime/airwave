"""Tests for the Liquidsoap playout interface.

Verifies the exact telnet command strings sent (annotate: URI format),
error-reply detection (no method may report success on an unknown-command
reply). Telnet I/O is replaced by
a fake _send_command that records commands and returns canned replies.
"""

from pathlib import Path

import pytest

from server.engine.playout import PlayoutInterface

UNKNOWN_COMMAND = 'ERROR: unknown command, type "help" to get a list of commands.'


class FakeTelnet:
    """Fake for PlayoutInterface._send_command.

    Records every command sent and replies from a prefix -> reply map,
    falling back to a default reply.
    """

    def __init__(self, replies: dict[str, str | None] | None = None, default: str | None = "10") -> None:
        self.commands: list[str] = []
        self.replies = replies or {}
        self.default = default

    async def __call__(self, command: str) -> str | None:
        self.commands.append(command)
        for prefix, reply in self.replies.items():
            if command.startswith(prefix):
                return reply
        return self.default


def make_playout(
    monkeypatch: pytest.MonkeyPatch,
    replies: dict[str, str | None] | None = None,
    default: str | None = "10",
) -> tuple[PlayoutInterface, FakeTelnet]:
    """Build a PlayoutInterface with _send_command replaced by a fake."""
    playout = PlayoutInterface(host="localhost", port=1234)
    fake = FakeTelnet(replies=replies, default=default)
    monkeypatch.setattr(playout, "_send_command", fake)
    return playout, fake


def local_audio_path(*parts: str) -> str:
    """An absolute local path containing an /audio/ segment."""
    return str(Path.cwd() / "audio" / Path(*parts))


# ---------------------------------------------------------------------------
# queue_track / queue_break command strings
# ---------------------------------------------------------------------------


async def test_queue_track_without_metadata_sends_plain_uri(monkeypatch):
    playout, fake = make_playout(monkeypatch)

    assert await playout.queue_track(local_audio_path("tracks", "song.wav")) is True
    assert fake.commands == ["queue.push /audio/tracks/song.wav"]


async def test_queue_track_with_metadata_builds_annotate_uri(monkeypatch):
    playout, fake = make_playout(monkeypatch)

    ok = await playout.queue_track(
        local_audio_path("tracks", "song.wav"),
        title='My "Song", Live',
        artist="AI DJ",
    )

    assert ok is True
    assert fake.commands == [
        "queue.push annotate:"
        'title="My \\"Song\\", Live",artist="AI DJ"'
        ":/audio/tracks/song.wav"
    ]


async def test_queue_track_title_only(monkeypatch):
    playout, fake = make_playout(monkeypatch)

    assert await playout.queue_track(local_audio_path("tracks", "a.wav"), title="Solo") is True
    assert fake.commands == ['queue.push annotate:title="Solo":/audio/tracks/a.wav']


async def test_queue_break_keeps_cross_duration_annotation(monkeypatch):
    playout, fake = make_playout(monkeypatch)

    ok = await playout.queue_break(
        local_audio_path("breaks", "break.wav"), title="DJ Break"
    )

    assert ok is True
    assert fake.commands == [
        "queue.push annotate:"
        'liq_cross_duration="0",type="dj_break",title="DJ Break"'
        ":/audio/breaks/break.wav"
    ]


async def test_queue_break_without_title(monkeypatch):
    playout, fake = make_playout(monkeypatch)

    assert await playout.queue_break(local_audio_path("breaks", "b.wav")) is True
    assert fake.commands == [
        'queue.push annotate:liq_cross_duration="0",type="dj_break"'
        ":/audio/breaks/b.wav"
    ]


# ---------------------------------------------------------------------------
# Error-reply detection: nothing succeeds on an unknown-command reply
# ---------------------------------------------------------------------------


async def test_queue_track_returns_false_on_error_reply(monkeypatch):
    playout, _ = make_playout(monkeypatch, default=UNKNOWN_COMMAND)

    assert await playout.queue_track(local_audio_path("tracks", "song.wav")) is False


async def test_queue_track_returns_false_on_connection_failure(monkeypatch):
    playout, _ = make_playout(monkeypatch, default=None)

    assert await playout.queue_track(local_audio_path("tracks", "song.wav")) is False


async def test_skip_returns_false_when_all_commands_unknown(monkeypatch):
    playout, fake = make_playout(monkeypatch, default=UNKNOWN_COMMAND)

    assert await playout.skip() is False
    assert fake.commands == ["radio_out.skip", "queue.skip"]


async def test_skip_prefers_output_command(monkeypatch):
    playout, fake = make_playout(monkeypatch, replies={"radio_out.skip": "Done"})

    assert await playout.skip() is True
    assert fake.commands == ["radio_out.skip"]


async def test_skip_falls_back_to_queue_skip(monkeypatch):
    playout, fake = make_playout(
        monkeypatch,
        replies={"radio_out.skip": UNKNOWN_COMMAND, "queue.skip": "Done"},
    )

    assert await playout.skip() is True
    assert fake.commands == ["radio_out.skip", "queue.skip"]


async def test_start_recording_returns_false_on_error_reply(monkeypatch):
    playout, fake = make_playout(monkeypatch, default=UNKNOWN_COMMAND)

    assert await playout.start_recording() is False
    assert fake.commands == ["recorder.set true"]


async def test_recording_commands_succeed_on_clean_reply(monkeypatch):
    playout, fake = make_playout(
        monkeypatch,
        replies={
            "recorder.set true": "OK recorder_enabled=true",
            "recorder.set false": "OK recorder_enabled=false",
        },
    )

    assert await playout.start_recording() is True
    assert await playout.stop_recording() is True
    assert fake.commands == ["recorder.set true", "recorder.set false"]


async def test_is_recording_parses_status(monkeypatch):
    playout, _ = make_playout(monkeypatch, replies={"recorder.status": "on"})
    assert await playout.is_recording() is True

    playout, _ = make_playout(monkeypatch, replies={"recorder.status": "off"})
    assert await playout.is_recording() is False

    playout, _ = make_playout(monkeypatch, replies={"recorder.status": UNKNOWN_COMMAND})
    assert await playout.is_recording() is False


async def test_get_queue_length_zero_on_error_reply(monkeypatch):
    playout, _ = make_playout(monkeypatch, default=UNKNOWN_COMMAND)
    assert await playout.get_queue_length() == 0

    playout, _ = make_playout(monkeypatch, default="12 13 14")
    assert await playout.get_queue_length() == 3


# ---------------------------------------------------------------------------
# Status / metadata retrieval
# ---------------------------------------------------------------------------


async def test_get_status_parses_remaining_and_metadata(monkeypatch):
    metadata_reply = (
        "--- 1 ---\n"
        'title="Old Song"\n'
        "--- 2 ---\n"
        'title="New Song"\n'
        'artist="AI DJ"'
    )
    playout, fake = make_playout(
        monkeypatch,
        replies={
            "version": "Liquidsoap 2.2.5",
            "radio_out.remaining": "123.45",
            "radio_out.metadata": metadata_reply,
        },
    )

    status = await playout.get_status()

    assert status["remaining"] == pytest.approx(123.45)
    assert status["metadata"] == {"title": "New Song", "artist": "AI DJ"}
    assert status["current_title"] == "New Song"
    assert "radio_out.remaining" in fake.commands
    assert "radio_out.metadata" in fake.commands


async def test_get_status_handles_undef_remaining_and_errors(monkeypatch):
    playout, _ = make_playout(
        monkeypatch,
        replies={
            "version": "Liquidsoap 2.2.5",
            "radio_out.remaining": "(undef)",
            "radio_out.metadata": UNKNOWN_COMMAND,
        },
    )

    status = await playout.get_status()

    assert status["remaining"] is None
    assert status["metadata"] == {}
    assert status["current_title"] is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_is_error_reply_detection():
    assert PlayoutInterface._is_error_reply(None) is True
    assert PlayoutInterface._is_error_reply(UNKNOWN_COMMAND) is True
    assert PlayoutInterface._is_error_reply("ERROR usage: caller.set true|false") is True
    assert PlayoutInterface._is_error_reply("") is False
    assert PlayoutInterface._is_error_reply("Done") is False
    # ERROR inside a metadata value must not be flagged
    assert PlayoutInterface._is_error_reply('title="ERROR in my heart"') is False


def test_escape_annotation():
    assert PlayoutInterface._escape_annotation('a "b" \\ c') == 'a \\"b\\" \\\\ c'
    # Commas stay literal: annotate values are always double-quoted.
    assert PlayoutInterface._escape_annotation("x, y") == "x, y"
