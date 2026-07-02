"""Audio processing pipeline for normalization and format conversion.

All audio entering the system passes through this pipeline to ensure
consistent format, loudness, and quality.
"""

import logging
from pathlib import Path

from server.utils.audio import (
    apply_radio_voice_effects,
    convert_to_wav,
    get_duration,
    get_loudness,
    normalize_loudness,
    trim_silence,
)

logger = logging.getLogger(__name__)


class AudioPipeline:
    """Handles audio normalization and format conversion via FFmpeg.

    Ensures all audio meets the station's format standards:
    - 48kHz, 16-bit, stereo WAV
    - Loudness normalized to -14 LUFS (EBU R128)
    - Excessive silence trimmed from start/end
    """

    def __init__(self, target_lufs: float = -14.0) -> None:
        self._target_lufs = target_lufs

    async def process(self, filepath: str, voice: bool = False) -> dict:
        """Run the full audio processing pipeline on a file.

        Steps:
        1. Convert to 48kHz stereo WAV
        2. Trim excessive silence
        3. Apply radio voice effects (voice audio only — DJ breaks)
        4. Normalize loudness to target LUFS (two-pass)
        5. Measure final loudness and duration

        Args:
            filepath: Path to the input audio file.
            voice: If True, apply radio DJ voice effects (compression, EQ).
                Use for DJ break TTS audio, not for music tracks.

        Returns:
            A dict with processed_path, duration, and loudness_lufs.
        """
        logger.info("Processing audio: %s (voice=%s)", filepath, voice)
        p = Path(filepath)

        # Step 1: Convert to WAV
        wav_path = str(p.with_suffix(".wav"))
        wav_path = await convert_to_wav(filepath, wav_path)
        logger.debug("Converted to WAV: %s", wav_path)

        # Step 2: Trim silence (gentler for voice to avoid clipping speech)
        trimmed_path = await trim_silence(wav_path, voice=voice)
        logger.debug("Trimmed silence: %s", trimmed_path)

        # Step 3: Radio voice effects (DJ breaks only)
        if voice:
            effects_path = await apply_radio_voice_effects(trimmed_path)
            logger.debug("Applied radio voice effects: %s", effects_path)
        else:
            effects_path = trimmed_path

        # Step 4: Normalize loudness
        norm_path = await normalize_loudness(
            effects_path, target_lufs=self._target_lufs
        )
        logger.debug("Normalized loudness: %s", norm_path)

        # Step 4: Measure results
        duration = await get_duration(norm_path)
        loudness = await get_loudness(norm_path)

        # Clean up intermediate files (keep only the final output)
        final_path = str(p.with_stem(p.stem + "_processed").with_suffix(".wav"))
        final = Path(norm_path)
        if final.exists() and str(final) != final_path:
            final.rename(final_path)
        elif not final.exists():
            final_path = norm_path

        # Remove intermediates
        for tmp in [wav_path, trimmed_path, effects_path, norm_path]:
            tmp_p = Path(tmp)
            if tmp_p.exists() and str(tmp_p) != final_path and str(tmp_p) != filepath:
                try:
                    tmp_p.unlink()
                except OSError:
                    pass

        logger.info(
            "Audio processed: %s -> %s (%.1fs, %.1f LUFS)",
            filepath, final_path, duration, loudness,
        )

        return {
            "processed_path": final_path,
            "duration": duration,
            "loudness_lufs": loudness,
        }

    async def normalize(self, filepath: str, target_lufs: float | None = None) -> str:
        """Normalize audio loudness to the target LUFS level.

        Args:
            filepath: Path to the input audio file.
            target_lufs: Target loudness in LUFS. Uses pipeline default if None.

        Returns:
            Path to the normalized output file.
        """
        target = target_lufs if target_lufs is not None else self._target_lufs
        return await normalize_loudness(filepath, target_lufs=target)

    async def convert_format(self, filepath: str, output_format: str = "wav") -> str:
        """Convert an audio file to the specified format.

        Args:
            filepath: Path to the input audio file.
            output_format: Target audio format ('wav' or 'mp3').

        Returns:
            Path to the converted output file.
        """
        if output_format == "wav":
            return await convert_to_wav(filepath)
        elif output_format == "mp3":
            from server.utils.audio import convert_to_mp3
            return await convert_to_mp3(filepath)
        else:
            logger.warning("Unsupported format '%s', returning original", output_format)
            return filepath
