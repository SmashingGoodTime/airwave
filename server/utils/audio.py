"""Audio utility functions wrapping FFmpeg operations."""

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class AudioProcessingError(RuntimeError):
    """Raised when an FFmpeg processing step fails.

    Callers (the audio pipeline and, transitively, the generation
    engines) must treat this as a hard failure and mark the item
    failed — returning unprocessed audio would put unnormalized
    files on the air.
    """


async def _run_ffmpeg(*args: str) -> tuple[int, str, str]:
    """Run an FFmpeg command asynchronously.

    Args:
        *args: Command-line arguments to pass to ffmpeg.

    Returns:
        A tuple of (return_code, stdout, stderr).
    """
    cmd = ["ffmpeg", "-y", *args]
    logger.debug("Running: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    # errors="replace": ffmpeg output can contain non-UTF-8 bytes on
    # Windows (cp1252 filenames); a decode error here would escape all
    # downstream error handling.
    return (
        proc.returncode,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


async def _run_ffprobe(*args: str) -> tuple[int, str, str]:
    """Run an FFprobe command asynchronously.

    Args:
        *args: Command-line arguments to pass to ffprobe.

    Returns:
        A tuple of (return_code, stdout, stderr).
    """
    cmd = ["ffprobe", *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


async def get_duration(filepath: str) -> float:
    """Get the duration of an audio file in seconds.

    Args:
        filepath: Path to the audio file.

    Returns:
        Duration in seconds, or 0.0 on error.
    """
    rc, stdout, stderr = await _run_ffprobe(
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        filepath,
    )
    if rc != 0:
        logger.warning("ffprobe failed for %s: %s", filepath, stderr[:200])
        return 0.0

    try:
        data = json.loads(stdout)
        return float(data["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Could not parse duration for %s: %s", filepath, exc)
        return 0.0


async def get_loudness(filepath: str) -> float:
    """Measure the integrated loudness of an audio file in LUFS.

    Uses FFmpeg's ebur128 filter for EBU R128 measurement.

    Args:
        filepath: Path to the audio file.

    Returns:
        Integrated loudness in LUFS, or -14.0 as fallback.
    """
    rc, stdout, stderr = await _run_ffmpeg(
        "-i", filepath,
        "-af", "ebur128=framelog=verbose",
        "-f", "null", "-",
    )
    if rc != 0:
        logger.warning("Loudness measurement failed for %s", filepath)
        return -14.0

    # Parse integrated loudness from ebur128 output
    for line in stderr.split("\n"):
        if "I:" in line and "LUFS" in line:
            try:
                # Line format: "    I:         -14.0 LUFS"
                parts = line.strip().split()
                idx = parts.index("LUFS") - 1
                return float(parts[idx])
            except (ValueError, IndexError):
                continue

    logger.warning("Could not parse loudness for %s, using default", filepath)
    return -14.0


async def normalize_loudness(
    filepath: str, target_lufs: float = -14.0, output_path: str | None = None
) -> str:
    """Normalize audio loudness using two-pass EBU R128 loudnorm.

    Args:
        filepath: Path to the input audio file.
        target_lufs: Target integrated loudness in LUFS.
        output_path: Optional output path. If None, replaces the input file.

    Returns:
        Path to the normalized audio file.

    Raises:
        AudioProcessingError: If FFmpeg fails to normalize the file.
    """
    normalized_path, _ = await normalize_loudness_measured(
        filepath, target_lufs=target_lufs, output_path=output_path
    )
    return normalized_path


async def normalize_loudness_measured(
    filepath: str, target_lufs: float = -14.0, output_path: str | None = None
) -> tuple[str, float | None]:
    """Normalize loudness and return the measured output loudness.

    Same as :func:`normalize_loudness`, but also returns the integrated
    output loudness reported by loudnorm's pass-2 summary, letting
    callers skip a separate full-decode ebur128 measurement.

    Args:
        filepath: Path to the input audio file.
        target_lufs: Target integrated loudness in LUFS.
        output_path: Optional output path. If None, replaces the input file.

    Returns:
        A tuple of (normalized_path, output_lufs). ``output_lufs`` is None
        if the summary could not be parsed.

    Raises:
        AudioProcessingError: If FFmpeg fails to normalize the file.
    """
    if output_path is None:
        p = Path(filepath)
        output_path = str(p.with_stem(p.stem + "_norm"))

    # Pass 1: Measure
    rc, stdout, stderr = await _run_ffmpeg(
        "-i", filepath,
        "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    )
    if rc != 0:
        logger.error("Loudnorm pass 1 failed for %s: %s", filepath, stderr[:200])
        raise AudioProcessingError(
            f"Loudnorm pass 1 failed for {filepath}: {stderr[:200]}"
        )

    # Parse measured values from JSON in stderr
    measured = _parse_loudnorm_stats(stderr)
    if measured is None:
        logger.warning("Could not parse loudnorm stats for %s, using single pass", filepath)
        # Fallback to single-pass
        rc, _, stderr2 = await _run_ffmpeg(
            "-i", filepath,
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=summary",
            "-ar", "48000", "-ac", "2",
            output_path,
        )
        if rc != 0:
            logger.error(
                "Single-pass loudnorm failed for %s: %s", filepath, stderr2[:200]
            )
            raise AudioProcessingError(
                f"Single-pass loudnorm failed for {filepath}: {stderr2[:200]}"
            )
        return output_path, _parse_loudnorm_output_i(stderr2)

    # Pass 2: Apply with measured values
    loudnorm_filter = (
        f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"
        f":measured_I={measured['input_i']}"
        f":measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}"
        f":measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}"
        f":linear=true:print_format=summary"
    )

    rc, _, stderr2 = await _run_ffmpeg(
        "-i", filepath,
        "-af", loudnorm_filter,
        "-ar", "48000", "-ac", "2",
        output_path,
    )
    if rc != 0:
        logger.error("Loudnorm pass 2 failed for %s: %s", filepath, stderr2[:200])
        raise AudioProcessingError(
            f"Loudnorm pass 2 failed for {filepath}: {stderr2[:200]}"
        )

    logger.info("Normalized %s -> %s (target: %s LUFS)", filepath, output_path, target_lufs)
    return output_path, _parse_loudnorm_output_i(stderr2)


def _parse_loudnorm_output_i(stderr: str) -> float | None:
    """Extract the output integrated loudness from a loudnorm summary.

    Args:
        stderr: FFmpeg stderr containing ``print_format=summary`` output.

    Returns:
        The ``Output Integrated`` value in LUFS, or None if not found.
    """
    for line in stderr.splitlines():
        stripped = line.strip()
        if stripped.startswith("Output Integrated:"):
            parts = stripped.split()
            try:
                return float(parts[2])
            except (IndexError, ValueError):
                return None
    return None


def _parse_loudnorm_stats(stderr: str) -> dict | None:
    """Extract loudnorm measurement JSON from FFmpeg stderr.

    Args:
        stderr: FFmpeg stderr output containing the loudnorm JSON block.

    Returns:
        A dict of measurement values, or None if parsing failed.
    """
    # Find the JSON block output by loudnorm
    try:
        json_start = stderr.rfind("{")
        json_end = stderr.rfind("}") + 1
        if json_start == -1 or json_end == 0:
            return None
        data = json.loads(stderr[json_start:json_end])
        required = ["input_i", "input_tp", "input_lra", "input_thresh", "target_offset"]
        if all(k in data for k in required):
            return data
        return None
    except (json.JSONDecodeError, ValueError):
        return None


async def convert_to_wav(filepath: str, output_path: str | None = None) -> str:
    """Convert an audio file to 48kHz 16-bit stereo WAV.

    Args:
        filepath: Path to the input audio file.
        output_path: Optional output path. If None, creates alongside input.

    Returns:
        Path to the WAV file.

    Raises:
        AudioProcessingError: If FFmpeg fails to convert the file.
    """
    if output_path is None:
        p = Path(filepath)
        output_path = str(p.with_suffix(".wav"))

    if filepath == output_path:
        tmp = str(Path(filepath).with_stem(Path(filepath).stem + "_tmp"))
        rc, _, stderr = await _run_ffmpeg(
            "-i", filepath,
            "-ar", "48000", "-ac", "2", "-sample_fmt", "s16",
            tmp,
        )
        if rc == 0:
            Path(tmp).replace(Path(output_path))
            return output_path
        logger.error("WAV conversion failed for %s: %s", filepath, stderr[:200])
        raise AudioProcessingError(
            f"WAV conversion failed for {filepath}: {stderr[:200]}"
        )

    rc, _, stderr = await _run_ffmpeg(
        "-i", filepath,
        "-ar", "48000", "-ac", "2", "-sample_fmt", "s16",
        output_path,
    )
    if rc != 0:
        logger.error("WAV conversion failed for %s: %s", filepath, stderr[:200])
        raise AudioProcessingError(
            f"WAV conversion failed for {filepath}: {stderr[:200]}"
        )

    return output_path


async def convert_to_mp3(filepath: str, bitrate: str = "192k") -> str:
    """Convert an audio file to MP3 format.

    Args:
        filepath: Path to the input audio file.
        bitrate: Target MP3 bitrate.

    Returns:
        Path to the output MP3 file.
    """
    p = Path(filepath)
    output_path = str(p.with_suffix(".mp3"))

    if filepath == output_path:
        return filepath

    rc, _, stderr = await _run_ffmpeg(
        "-i", filepath,
        "-codec:a", "libmp3lame", "-b:a", bitrate,
        output_path,
    )
    if rc != 0:
        logger.error("MP3 conversion failed for %s: %s", filepath, stderr[:200])
        return filepath

    return output_path


async def concat_audio_files(
    files: list[str], gap_seconds: float = 0.3, output_path: str = ""
) -> str:
    """Concatenate multiple audio files with silence gaps between them.

    Uses FFmpeg's concat filter to join files sequentially with configurable
    silence gaps. All input files should be in the same format (48kHz stereo WAV).

    Args:
        files: List of file paths to concatenate in order.
        gap_seconds: Seconds of silence to insert between files.
        output_path: Output file path. If empty, auto-generated.

    Returns:
        Path to the concatenated output file.
    """
    if not files:
        raise ValueError("No audio files to concatenate")

    if len(files) == 1:
        return files[0]

    if not output_path:
        p = Path(files[0])
        output_path = str(p.with_stem(p.stem + "_concat"))

    # Build a concat filter with silence gaps
    # We use the anullsrc filter to generate silence between clips
    filter_parts = []
    input_args = []

    for i, f in enumerate(files):
        input_args.extend(["-i", f])

    # Build the filter graph:
    # [0:a]apad=pad_dur=<gap>[a0]; [1:a]apad=pad_dur=<gap>[a1]; ... [aN-1:a][aN]concat=n=N:v=0:a=1
    gap_ms = int(gap_seconds * 1000)
    concat_inputs = []

    for i in range(len(files)):
        label = f"a{i}"
        if i < len(files) - 1 and gap_seconds > 0:
            # Add silence padding after each clip except the last
            filter_parts.append(
                f"[{i}:a]apad=pad_dur={gap_ms}ms[{label}]"
            )
        else:
            filter_parts.append(f"[{i}:a]acopy[{label}]")
        concat_inputs.append(f"[{label}]")

    filter_parts.append(
        f"{''.join(concat_inputs)}concat=n={len(files)}:v=0:a=1[out]"
    )

    filter_graph = ";".join(filter_parts)

    rc, _, stderr = await _run_ffmpeg(
        *input_args,
        "-filter_complex", filter_graph,
        "-map", "[out]",
        "-ar", "48000", "-ac", "2",
        output_path,
    )

    if rc != 0:
        logger.error("Audio concatenation failed: %s", stderr[:300])
        # Fallback: return first file
        return files[0]

    logger.info(
        "Concatenated %d audio files (gap=%.1fs) -> %s",
        len(files), gap_seconds, output_path,
    )
    return output_path


async def concat_audio_files_variable(
    files: list[str], gaps: list[float], output_path: str = ""
) -> str:
    """Concatenate audio files with variable silence gaps between them.

    Each file gets a different gap duration before it, enabling natural
    conversation pacing (quick interruptions vs. thoughtful pauses).

    Args:
        files: List of file paths to concatenate in order.
        gaps: Per-file gap durations in seconds. gaps[0] is ignored (no gap
            before the first file). Must be same length as files.
        output_path: Output file path. If empty, auto-generated.

    Returns:
        Path to the concatenated output file.
    """
    if not files:
        raise ValueError("No audio files to concatenate")

    if len(files) == 1:
        return files[0]

    # Pad gaps list if needed
    while len(gaps) < len(files):
        gaps.append(0.4)

    if not output_path:
        p = Path(files[0])
        output_path = str(p.with_stem(p.stem + "_concat"))

    # Build a filter graph with per-file silence gaps
    input_args = []
    for f in files:
        input_args.extend(["-i", f])

    filter_parts = []
    concat_inputs = []

    for i in range(len(files)):
        label = f"a{i}"
        gap_ms = int(gaps[i] * 1000) if i > 0 else 0

        if gap_ms > 0:
            filter_parts.append(
                f"[{i}:a]adelay={gap_ms}|{gap_ms}[{label}]"
            )
        else:
            filter_parts.append(f"[{i}:a]acopy[{label}]")
        concat_inputs.append(f"[{label}]")

    filter_parts.append(
        f"{''.join(concat_inputs)}concat=n={len(files)}:v=0:a=1[out]"
    )

    filter_graph = ";".join(filter_parts)

    rc, _, stderr = await _run_ffmpeg(
        *input_args,
        "-filter_complex", filter_graph,
        "-map", "[out]",
        "-ar", "48000", "-ac", "2",
        output_path,
    )

    if rc != 0:
        logger.error("Variable-gap concatenation failed: %s", stderr[:300])
        # Fallback to uniform-gap concat
        avg_gap = sum(gaps[1:]) / max(len(gaps) - 1, 1)
        return await concat_audio_files(files, avg_gap, output_path)

    logger.info(
        "Concatenated %d audio files (variable gaps) -> %s",
        len(files), output_path,
    )
    return output_path


async def apply_radio_voice_effects(filepath: str) -> str:
    """Apply radio DJ voice processing effects to a TTS audio file.

    Applies a chain of FFmpeg audio filters to make TTS output sound like
    a professional radio DJ broadcast:
    1. High-pass filter at 80Hz (removes rumble and mic pops)
    2. Warm bass boost around 200Hz
    3. Presence/clarity boost around 3kHz
    4. Compression (tighter dynamic range, punchy broadcast voice)
    5. Subtle brightness lift at 8kHz (air/sparkle)

    Args:
        filepath: Path to the input audio file (should be WAV).

    Returns:
        Path to the processed output file.
    """
    p = Path(filepath)
    output_path = str(p.with_stem(p.stem + "_radio"))

    # Build the filter chain
    filters = ",".join([
        # 1. High-pass: remove low rumble and plosive pops
        "highpass=f=80:poles=2",
        # 2. Warm bass boost at 200Hz
        "equalizer=f=200:t=q:w=1.5:g=2.5",
        # 3. Presence boost at 3kHz for clarity and cut-through
        "equalizer=f=3000:t=q:w=2.0:g=4.0",
        # 4. Brightness/air at 8kHz
        "equalizer=f=8000:t=q:w=1.5:g=2.0",
        # 5. Broadcast compression: fast attack, moderate release, punchy sound
        "acompressor=threshold=-18dB:ratio=4:attack=5:release=50:makeup=3:knee=4",
    ])

    rc, _, stderr = await _run_ffmpeg(
        "-i", filepath,
        "-af", filters,
        "-ar", "48000", "-ac", "2",
        output_path,
    )
    if rc != 0:
        logger.warning("Radio voice effects failed for %s: %s", filepath, stderr[:200])
        return filepath

    logger.info("Applied radio voice effects: %s -> %s", filepath, output_path)
    return output_path


async def trim_silence(
    filepath: str,
    threshold: float = -50.0,
    padding: float = 0.5,
    voice: bool = False,
) -> str:
    """Trim leading and trailing silence from an audio file.

    Args:
        filepath: Path to the input audio file.
        threshold: Silence threshold in dB.
        padding: Seconds of padding to leave at start/end.
        voice: If True, use gentler trimming to avoid clipping speech.

    Returns:
        Path to the trimmed output file.

    Raises:
        AudioProcessingError: If FFmpeg fails to trim the file.
    """
    if voice:
        # Speech trails off gradually — use a higher threshold so only
        # true silence is removed, and keep more padding so the last
        # word is never clipped.
        threshold = -55.0
        padding = 1.5
    p = Path(filepath)
    output_path = str(p.with_stem(p.stem + "_trimmed"))

    # Use silenceremove filter to trim start and end
    filter_str = (
        f"silenceremove=start_periods=1:start_threshold={threshold}dB"
        f":start_silence={padding}"
        f",areverse"
        f",silenceremove=start_periods=1:start_threshold={threshold}dB"
        f":start_silence={padding}"
        f",areverse"
    )

    rc, _, stderr = await _run_ffmpeg(
        "-i", filepath,
        "-af", filter_str,
        output_path,
    )
    if rc != 0:
        logger.error("Silence trimming failed for %s: %s", filepath, stderr[:200])
        raise AudioProcessingError(
            f"Silence trimming failed for {filepath}: {stderr[:200]}"
        )

    return output_path
