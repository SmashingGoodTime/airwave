"""Regression tests for the talk-show audio chain.

Covers the failure mode where a talk "conversation" aired as a single
short TTS clip: lying WAV headers from the streaming TTS provider,
silent concat fallbacks, and stub segments passing validation.
"""

import struct

import pytest

from server.engine.talk_show import TalkShowEngine
from server.models.show import Show
from server.models.talk_show_config import TalkShowConfig
from server.models.talk_topic import TalkTopic
from server.providers.base import ScriptWriterProvider, VoiceProvider
from server.providers.registry import ProviderRegistry
from server.providers.voice.fish import _fix_wav_header


# ---------------------------------------------------------------------------
# _fix_wav_header
# ---------------------------------------------------------------------------


def _streaming_wav_bytes(payload: bytes, extra_chunk: bytes = b"") -> bytes:
    """Build a WAV with ~4GB placeholder sizes, like a streamed TTS reply."""
    fmt = struct.pack("<HHIIHH", 1, 1, 44100, 88200, 2, 16)
    return (
        b"RIFF" + struct.pack("<I", 0xFFFFFF24) + b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + extra_chunk
        + b"data" + struct.pack("<I", 0xFFFFFF00) + payload
    )


def test_fix_wav_header_corrects_placeholder_sizes(tmp_path):
    payload = b"\x00\x01" * 500
    path = tmp_path / "line.wav"
    path.write_bytes(_streaming_wav_bytes(payload))

    _fix_wav_header(path)

    data = path.read_bytes()
    assert struct.unpack("<I", data[4:8])[0] == len(data) - 8
    data_size_offset = data.index(b"data") + 4
    assert (
        struct.unpack("<I", data[data_size_offset:data_size_offset + 4])[0]
        == len(payload)
    )


def test_fix_wav_header_walks_extra_chunks(tmp_path):
    payload = b"\x00\x01" * 100
    extra = b"LIST" + struct.pack("<I", 6) + b"INFOab"
    path = tmp_path / "line.wav"
    path.write_bytes(_streaming_wav_bytes(payload, extra_chunk=extra))

    _fix_wav_header(path)

    data = path.read_bytes()
    data_size_offset = data.index(b"data") + 4
    assert (
        struct.unpack("<I", data[data_size_offset:data_size_offset + 4])[0]
        == len(payload)
    )


def test_fix_wav_header_ignores_non_riff(tmp_path):
    path = tmp_path / "error.wav"
    original = b'{"error": "quota exceeded"}' + b"x" * 40
    path.write_bytes(original)

    _fix_wav_header(path)

    assert path.read_bytes() == original


def test_fix_wav_header_leaves_correct_header_untouched(tmp_path):
    payload = b"\x00\x01" * 100
    fmt = struct.pack("<HHIIHH", 1, 1, 44100, 88200, 2, 16)
    body = (
        b"WAVEfmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", len(payload)) + payload
    )
    correct = b"RIFF" + struct.pack("<I", len(body)) + body
    path = tmp_path / "ok.wav"
    path.write_bytes(correct)

    _fix_wav_header(path)

    assert path.read_bytes() == correct


# ---------------------------------------------------------------------------
# Conversation rendering
# ---------------------------------------------------------------------------


class FileWritingVoiceProvider(VoiceProvider):
    """Writes a real file per render; can fail on selected line indexes."""

    def __init__(self, out_dir, fail_on: set[int] | None = None) -> None:
        self._out_dir = out_dir
        self._fail_on = fail_on or set()
        self.calls = 0

    async def render(self, text: str, voice_config: dict) -> str:
        index = self.calls
        self.calls += 1
        if index in self._fail_on:
            raise RuntimeError("TTS unavailable")
        path = self._out_dir / f"line_{index}.wav"
        path.write_bytes(b"RIFF fake audio")
        return str(path)

    async def list_voices(self) -> list:
        return []

    async def check_status(self) -> bool:
        return True


def _make_registry_with_voice(voice) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry._voice = voice
    ProviderRegistry._instance = registry
    return registry


CONVO_SCRIPT = (
    '[{"speaker": "Host", "text": "Welcome back."},'
    ' {"speaker": "Ray", "text": "Glad to be here."},'
    ' {"speaker": "Host", "text": "Let us dig in."}]'
)


@pytest.mark.asyncio
async def test_render_conversation_stitches_and_cleans_lines(
    tmp_path, monkeypatch
):
    voice = FileWritingVoiceProvider(tmp_path)
    _make_registry_with_voice(voice)
    engine = TalkShowEngine(audio_dir=str(tmp_path))

    async def fake_concat(files, gaps, output_path):
        assert len(files) == 3
        with open(output_path, "wb") as f:
            f.write(b"stitched")
        return output_path

    monkeypatch.setattr(
        "server.engine.talk_show.concat_audio_files_variable", fake_concat
    )

    config = TalkShowConfig(name="Test", segment_gap=5)
    result = await engine._render_conversation(CONVO_SCRIPT, config)

    assert result is not None and "conversation_" in result
    # Per-line renders are intermediates and must be removed after the stitch.
    assert not list(tmp_path.glob("line_*.wav"))


@pytest.mark.asyncio
async def test_render_conversation_rejects_partial_render(tmp_path):
    # 2 of 3 lines fail (> 20% threshold) — the segment must fail rather
    # than air a fragment of the conversation.
    voice = FileWritingVoiceProvider(tmp_path, fail_on={1, 2})
    _make_registry_with_voice(voice)
    engine = TalkShowEngine(audio_dir=str(tmp_path))
    config = TalkShowConfig(name="Test", segment_gap=5)

    with pytest.raises(RuntimeError, match="lines failed"):
        await engine._render_conversation(CONVO_SCRIPT, config)

    # Failed attempts must not leave orphan line renders behind.
    assert not list(tmp_path.glob("line_*.wav"))


@pytest.mark.asyncio
async def test_render_conversation_routes_host_name_to_host_voice(tmp_path, monkeypatch):
    rendered_configs = []

    class RecordingVoice(FileWritingVoiceProvider):
        async def render(self, text: str, voice_config: dict) -> str:
            rendered_configs.append(dict(voice_config))
            return await super().render(text, voice_config)

    voice = RecordingVoice(tmp_path)
    _make_registry_with_voice(voice)
    engine = TalkShowEngine(audio_dir=str(tmp_path))

    async def fake_concat(files, gaps, output_path):
        with open(output_path, "wb") as f:
            f.write(b"stitched")
        return output_path

    monkeypatch.setattr(
        "server.engine.talk_show.concat_audio_files_variable", fake_concat
    )

    config = TalkShowConfig(
        name="Test", segment_gap=5, host_voice_id="a" * 32
    )
    script = '[{"speaker": "Nova", "text": "Hello there, listeners."}]'
    await engine._render_conversation(script, config, host_name="Nova")

    assert rendered_configs[0]["voice_id"] == "a" * 32


# ---------------------------------------------------------------------------
# Stub-segment rejection in generate_segment
# ---------------------------------------------------------------------------


class StubScriptWriter(ScriptWriterProvider):
    """Returns a monologue whose script implies ~2 minutes of speech."""

    async def write_break(self, context: dict) -> dict:
        return {"script_text": "hi"}

    async def write_talk_segment(self, context: dict) -> dict:
        return {
            "script_text": "word " * 300,
            "segment_type": "monologue",
            "speakers": ["Host"],
            "estimated_duration": 120.0,
        }

    async def check_status(self) -> bool:
        return True


async def _seed_talk_show(db_session) -> Show:
    config = TalkShowConfig(name="Talk Config")
    db_session.add(config)
    await db_session.flush()
    topic = TalkTopic(
        talk_config_id=config.id,
        title="Topic",
        prompt="Discuss.",
        topic_type="monologue",
    )
    show = Show(name="Night Talk", show_type="talk", talk_config_id=config.id)
    db_session.add_all([topic, show])
    await db_session.commit()
    return show


@pytest.mark.asyncio
async def test_generate_segment_rejects_stub_audio(
    db_session, tmp_path, monkeypatch
):
    """A rendered file far shorter than the script means audio was lost."""
    registry = ProviderRegistry()
    registry._scriptwriter = StubScriptWriter()
    registry._voice = FileWritingVoiceProvider(tmp_path)
    ProviderRegistry._instance = registry

    engine = TalkShowEngine(audio_dir=str(tmp_path))

    async def fake_process(filepath, voice=False, delete_source=False):
        return {
            "processed_path": str(tmp_path / "stub_processed.wav"),
            "duration": 4.3,  # vs ~120s expected from the script
            "loudness_lufs": -14.0,
        }

    monkeypatch.setattr(engine._pipeline, "process", fake_process)

    show = await _seed_talk_show(db_session)
    segment = await engine.generate_segment(db_session, show)

    assert segment is None


@pytest.mark.asyncio
async def test_generate_segment_accepts_full_length_audio(
    db_session, tmp_path, monkeypatch
):
    registry = ProviderRegistry()
    registry._scriptwriter = StubScriptWriter()
    registry._voice = FileWritingVoiceProvider(tmp_path)
    ProviderRegistry._instance = registry

    engine = TalkShowEngine(audio_dir=str(tmp_path))

    async def fake_process(filepath, voice=False, delete_source=False):
        return {
            "processed_path": str(tmp_path / "full_processed.wav"),
            "duration": 118.0,
            "loudness_lufs": -14.0,
        }

    monkeypatch.setattr(engine._pipeline, "process", fake_process)

    show = await _seed_talk_show(db_session)
    segment = await engine.generate_segment(db_session, show)

    assert segment is not None
    assert segment.status == "ready"
    assert segment.duration == pytest.approx(118.0)
