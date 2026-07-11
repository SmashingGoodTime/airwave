"""Talk show engine for generating and managing talk show segments.

Handles topic selection, script generation (monologue and multi-voice),
audio rendering with multiple voices, and segment buffering.
"""

import json
import logging
import os
import random
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.config import settings
from server.engine.audio_pipeline import AudioPipeline
from server.engine.dj_brain import get_effective_dj_config
from server.engine.generation_jobs import (
    fail_generation_job,
    finish_generation_job,
    start_generation_job,
)
from server.engine.timeline_mirror import mirror_talk_segment_ready
from server.events.emitter import event_bus
from server.models.show import Show
from server.models.station import Station, get_station
from server.models.talk_segment import TalkSegment
from server.models.talk_show_config import TalkShowConfig
from server.models.talk_topic import TalkTopic
from server.providers.registry import ProviderRegistry
from server.utils.audio import concat_audio_files_variable
from server.utils.timeutils import resolve_timezone
from server.utils.voice import parse_voice_settings

logger = logging.getLogger(__name__)


class TalkShowEngine:
    """Generates talk show segments including monologues and multi-voice conversations.

    Manages topic selection with weighted/sequential/random rotation,
    script generation via ScriptWriterProvider, multi-voice audio rendering
    via VoiceProvider, and segment buffering for continuous playout.
    """

    def __init__(self, audio_dir: str | None = None) -> None:
        self._pipeline = AudioPipeline()
        self._audio_dir = audio_dir or settings.AUDIO_DIR
        self._talks_dir = os.path.join(self._audio_dir, "talks")
        self._generating = False
        self._last_topic_id: int | None = None

    async def check_and_fill(
        self, session: AsyncSession, show: Show
    ) -> None:
        """Fill the talk segment buffer up to the configured target.

        Generates segments back-to-back until the buffer is full or a
        generation fails, so the buffer catches up after a drain instead
        of adding at most one segment per scheduler tick.

        Args:
            session: Async database session.
            show: The active talk show.
        """
        if self._generating:
            logger.debug("Talk segment generation already in progress")
            return

        if show.talk_config_id is None:
            logger.warning("Show %s has no talk config, cannot generate segments", show.name)
            return

        target = settings.TALK_BUFFER_TARGET
        while True:
            # Count ready segments
            result = await session.execute(
                select(func.count(TalkSegment.id)).where(
                    TalkSegment.status == "ready",
                    TalkSegment.show_id == show.id,
                )
            )
            ready_count = result.scalar() or 0

            logger.debug(
                "Talk buffer: %d/%d segments for show '%s'",
                ready_count,
                target,
                show.name,
            )

            if ready_count >= target:
                return

            segment = await self.generate_segment(session, show)
            if segment is None:
                # Generation failed — let the next scheduler tick retry
                # rather than hammering the providers in a tight loop.
                return

    async def generate_segment(
        self,
        session: AsyncSession,
        show: Show,
        config: TalkShowConfig | None = None,
        topic_id: int | None = None,
        preview: bool = False,
    ) -> TalkSegment | None:
        """Generate a single talk show segment.

        Selects a topic, generates a script, renders audio (with multi-voice
        stitching for conversations), and saves the result.

        Args:
            session: Async database session.
            show: The active show.
            config: Optional pre-loaded talk show config.
            topic_id: Optional specific topic to use, primarily for previews.
            preview: If True, generate for preview only — do not increment
                topic play counts, deactivate topics, mirror into the
                program timeline, or affect topic rotation.

        Returns:
            The created TalkSegment, or None if generation failed.
        """
        registry = ProviderRegistry.get_instance()
        scriptwriter = registry.get_scriptwriter_provider()

        if scriptwriter is None:
            logger.warning("No scriptwriter provider — cannot generate talk segments")
            return None

        self._generating = True
        job = None
        segment: TalkSegment | None = None
        try:
            # Load talk config
            if config is None:
                result = await session.execute(
                    select(TalkShowConfig).where(
                        TalkShowConfig.id == show.talk_config_id
                    )
                )
                config = result.scalar_one_or_none()

            if config is None:
                logger.warning("Talk config not found for show '%s'", show.name)
                return None

            # Select a topic
            topic = await self._select_topic(session, config, topic_id=topic_id)
            if topic is None:
                logger.warning("No active topics for talk config '%s'", config.name)
                return None

            # Build context for script generation
            context = await self._build_context(session, show, config, topic)

            # Generate script
            logger.info(
                "Generating %s segment: '%s'",
                topic.topic_type,
                topic.title,
            )
            job = await start_generation_job(
                session,
                job_type="generate_talk_segment",
                capability="write_talk_segment",
                provider=type(scriptwriter).__name__,
                input_data={
                    "show_id": show.id,
                    "talk_config_id": config.id,
                    "topic_id": topic.id,
                    "segment_type": topic.topic_type,
                    "topic": topic.title,
                },
            )
            await session.commit()

            script_result = await scriptwriter.write_talk_segment(context)
            script_text = script_result.get("script_text", "")

            if not script_text:
                logger.warning("Scriptwriter returned empty talk segment")
                await fail_generation_job(
                    session, job, "Scriptwriter returned empty talk segment"
                )
                await session.commit()
                return None

            # Create segment record
            segment = TalkSegment(
                show_id=show.id,
                talk_config_id=config.id,
                topic_id=topic.id,
                segment_type=topic.topic_type,
                script_text=script_text,
                speakers=json.dumps(script_result.get("speakers", [])),
                context=json.dumps(context, default=str),
                status="generating",
            )
            session.add(segment)
            await session.commit()
            await session.refresh(segment)

            # Render audio
            os.makedirs(self._talks_dir, exist_ok=True)

            host_name = context["speakers"][0]["name"] if context["speakers"] else "Host"
            if topic.topic_type == "monologue":
                audio_path = await self._render_monologue(script_text, config)
            else:
                audio_path = await self._render_conversation(
                    script_text, config, host_name
                )

            if audio_path:
                # The rendered (stitched) TTS audio is an intermediate
                # file — delete it once processed.
                processed = await self._pipeline.process(
                    audio_path, voice=True, delete_source=True
                )
                # Sanity check: a rendered segment far shorter than the
                # script implies means part of the audio was lost (e.g. a
                # bad stitch). Airing a stub is worse than failing.
                duration = processed["duration"] or 0.0
                expected = float(script_result.get("estimated_duration") or 0.0)
                if duration < 3.0 or (expected >= 20.0 and duration < expected * 0.25):
                    raise RuntimeError(
                        f"Rendered talk segment is suspiciously short "
                        f"({duration:.1f}s vs ~{expected:.0f}s expected from "
                        f"the script) — discarding instead of airing a stub"
                    )
                segment.audio_filepath = processed["processed_path"]
                segment.duration = processed["duration"]
                segment.loudness_lufs = processed.get("loudness_lufs")
                segment.status = "ready"
            else:
                # No voice provider — estimate duration from word count
                word_count = len(script_text.split())
                segment.duration = (word_count / 150) * 60
                segment.status = "ready"
                logger.warning("No voice provider — talk segment has no audio")

            # Previews never enter the program timeline
            output_asset_id = None
            if not preview:
                timeline_item = await mirror_talk_segment_ready(session, segment)
                output_asset_id = timeline_item.audio_asset_id
            await finish_generation_job(
                session,
                job,
                output_data={
                    "segment_id": segment.id,
                    "topic": topic.title,
                    "segment_type": segment.segment_type,
                    "duration": segment.duration,
                    "preview": preview,
                },
                output_asset_id=output_asset_id,
            )
            await session.commit()

            if not preview:
                # Update topic play count
                topic.play_count += 1
                if topic.max_plays and topic.play_count >= topic.max_plays:
                    topic.active = False
                    logger.info(
                        "Topic '%s' reached max plays, deactivated", topic.title
                    )
                await session.commit()

                self._last_topic_id = topic.id

            event_bus.emit("talk_segment.generated", {
                "segment_id": segment.id,
                "topic": topic.title,
                "type": topic.topic_type,
                "duration": segment.duration,
                "show": show.name,
            })
            logger.info(
                "Talk segment generated: id=%d, topic='%s', duration=%.1fs",
                segment.id,
                topic.title,
                segment.duration or 0,
            )
            return segment

        except Exception as exc:
            logger.error("Talk segment generation failed: %s", exc)
            # The original exception may have poisoned the session
            # (e.g. a failed flush) — roll back before writing failure state.
            try:
                await session.rollback()
            except Exception:
                pass
            try:
                if segment is not None and segment.id is not None:
                    segment.status = "failed"
                if job is not None:
                    await fail_generation_job(session, job, exc)
                await session.commit()
            except Exception:
                logger.warning("Could not update talk segment/job status to failed")
            event_bus.emit("provider.error", {
                "provider": "scriptwriter",
                "error": str(exc),
                "context": "talk_segment",
            })
            return None
        finally:
            self._generating = False

    async def get_next_segment(
        self, session: AsyncSession, show_id: int
    ) -> TalkSegment | None:
        """Get the next ready talk segment for playout.

        Args:
            session: Async database session.
            show_id: The active show ID.

        Returns:
            The oldest ready TalkSegment, or None.
        """
        result = await session.execute(
            select(TalkSegment)
            .where(
                TalkSegment.status == "ready",
                TalkSegment.show_id == show_id,
            )
            .order_by(TalkSegment.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _select_topic(
        self,
        session: AsyncSession,
        config: TalkShowConfig,
        topic_id: int | None = None,
    ) -> TalkTopic | None:
        """Select a topic based on rotation strategy and weights.

        Avoids repeating the same topic back-to-back when possible.

        Args:
            session: Async database session.
            config: The talk show configuration.
            topic_id: Optional specific topic ID to select.

        Returns:
            A TalkTopic, or None if no active topics exist.
        """
        if topic_id is not None:
            result = await session.execute(
                select(TalkTopic).where(
                    TalkTopic.id == topic_id,
                    TalkTopic.talk_config_id == config.id,
                )
            )
            return result.scalar_one_or_none()

        result = await session.execute(
            select(TalkTopic).where(
                TalkTopic.talk_config_id == config.id,
                TalkTopic.active.is_(True),
            )
        )
        topics = list(result.scalars().all())

        if not topics:
            return None

        # Filter out max-plays-reached topics
        eligible = [
            t for t in topics
            if t.max_plays is None or t.play_count < t.max_plays
        ]
        if not eligible:
            eligible = topics  # Fall back if all exhausted

        # Avoid back-to-back
        if self._last_topic_id and len(eligible) > 1:
            eligible = [t for t in eligible if t.id != self._last_topic_id] or eligible

        rotation = config.topic_rotation

        if rotation == "sequential":
            # Pick the least-played topic
            eligible.sort(key=lambda t: t.play_count)
            return eligible[0]
        elif rotation == "random":
            return random.choice(eligible)
        else:  # "weighted"
            weights = [t.weight for t in eligible]
            total = sum(weights)
            if total == 0:
                return random.choice(eligible)
            return random.choices(eligible, weights=weights, k=1)[0]

    async def _build_context(
        self,
        session: AsyncSession,
        show: Show,
        config: TalkShowConfig,
        topic: TalkTopic,
    ) -> dict:
        """Assemble context for talk segment script generation.

        Args:
            session: Async database session.
            show: The active show.
            config: Talk show configuration.
            topic: The selected topic.

        Returns:
            Context dict for the scriptwriter.
        """
        # Get station config for timezone
        station = await get_station(session)

        # The host speaks under the show's DJ persona name (falling back
        # to "Host"). The same name keys the voice map at render time, so
        # scripted lines route to the host voice by exact match.
        dj_config = await get_effective_dj_config(session, show_id=show.id)
        host_name = (
            dj_config.dj_name if dj_config and dj_config.dj_name else "Host"
        )

        # Build speakers list
        speakers = []
        if config.host_voice_id:
            host_settings = parse_voice_settings(config.host_voice_settings)
            speakers.append({
                "name": host_name,
                "voice_id": config.host_voice_id,
                "voice_settings": host_settings,
                "personality_prompt": config.host_personality_prompt or "",
            })

        if config.cohost_voices:
            try:
                cohosts = json.loads(config.cohost_voices)
                speakers.extend(cohosts)
            except (json.JSONDecodeError, TypeError):
                pass

        # If no speakers configured, use defaults
        if not speakers:
            speakers = [{"name": host_name, "voice_id": "", "personality_prompt": ""}]

        # Get recent segment summaries for continuity
        result = await session.execute(
            select(TalkSegment)
            .where(
                TalkSegment.show_id == show.id,
                TalkSegment.status.in_(["played", "playing", "ready"]),
            )
            .order_by(TalkSegment.created_at.desc())
            .limit(3)
        )
        previous_segments = []
        for seg in result.scalars().all():
            if seg.topic_id:
                topic_result = await session.execute(
                    select(TalkTopic.title).where(TalkTopic.id == seg.topic_id)
                )
                title = topic_result.scalar_one_or_none() or "Unknown topic"
            else:
                title = "Unknown topic"

            # Extract a brief content summary from the script for continuity
            summary = self._extract_summary(seg.script_text, seg.segment_type)
            previous_segments.append({
                "title": title,
                "type": seg.segment_type,
                "summary": summary,
            })

        # Calculate target duration
        target_duration = random.randint(
            config.segment_min_duration, config.segment_max_duration
        )

        now = datetime.now(timezone.utc)
        station_tz_str = station.timezone if station else "UTC"
        station_tz = resolve_timezone(station_tz_str)
        local_now = now.astimezone(station_tz)

        return {
            "topic": {
                "title": topic.title,
                "prompt": topic.prompt,
                "notes": topic.notes or "",
            },
            "segment_type": topic.topic_type,
            "speakers": speakers,
            "show_name": show.name,
            "host_personality": config.host_personality_prompt or "",
            "intro_style": config.intro_style or "",
            "outro_style": config.outro_style or "",
            "conversation_style": config.conversation_style or "",
            "previous_segments": previous_segments,
            "target_duration": target_duration,
            "current_time": local_now.strftime("%I:%M %p"),
            "station_timezone": station_tz_str,
        }

    async def _render_monologue(
        self, script_text: str, config: TalkShowConfig
    ) -> str | None:
        """Render a monologue script to audio using the host voice.

        Args:
            script_text: The monologue text.
            config: Talk show configuration with voice settings.

        Returns:
            Path to the rendered audio file, or None.
        """
        registry = ProviderRegistry.get_instance()
        voice = registry.get_voice_provider()

        if voice is None:
            return None

        voice_config = parse_voice_settings(
            config.host_voice_settings, config.host_voice_id or ""
        )
        audio_path = await voice.render(script_text, voice_config)
        return audio_path

    async def _render_conversation(
        self, script_text: str, config: TalkShowConfig, host_name: str = "Host"
    ) -> str | None:
        """Render a multi-voice conversation script to audio.

        Parses the structured JSON script, renders each speaker's lines
        with their configured voice, then stitches them together with
        variable pacing based on each line's pace cue.

        Args:
            script_text: JSON string of conversation lines.
            config: Talk show configuration with voice settings.
            host_name: Speaker name the script uses for the host.

        Returns:
            Path to the stitched audio file, or None.

        Raises:
            AudioProcessingError: If too many lines fail to render or the
                stitch fails — a partial conversation must not go to air.
        """
        registry = ProviderRegistry.get_instance()
        voice = registry.get_voice_provider()

        if voice is None:
            return None

        # Parse conversation lines
        try:
            lines = json.loads(script_text)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Cannot parse conversation script as JSON, falling back to monologue render")
            return await self._render_monologue(script_text, config)

        if not isinstance(lines, list) or not lines:
            logger.warning("Conversation script is empty or invalid")
            return await self._render_monologue(script_text, config)

        # Build voice config map: speaker name -> voice config
        voice_configs = self._build_voice_config_map(config, host_name)
        host_voice = voice_configs.get(host_name, {"voice_id": ""})

        # Pace-to-gap mapping (seconds of silence before this line)
        pace_gaps = {
            "quick": 0.1,
            "normal": 0.4,
            "slow": 0.8,
        }
        # Default gap from config, used as fallback
        default_gap = config.segment_gap / 10.0 if config.segment_gap else 0.4
        default_gap = min(default_gap, 1.0)

        # Render each line and track per-line gaps
        audio_files: list[str] = []
        line_gaps: list[float] = []
        failed_lines = 0
        segment_id = uuid.uuid4().hex[:8]
        stitched: str | None = None

        try:
            for i, line in enumerate(lines):
                if not isinstance(line, dict):
                    continue
                speaker = line.get("speaker", "Unknown")
                text = line.get("text", "")
                if not text.strip():
                    continue

                vc = voice_configs.get(speaker, host_voice)

                try:
                    line_path = await voice.render(text, vc)
                    audio_files.append(line_path)

                    # Determine gap before this line (first line gets no leading gap)
                    if not line_gaps:
                        line_gaps.append(0.0)
                    else:
                        pace = line.get("pace", "normal")
                        line_gaps.append(pace_gaps.get(pace, default_gap))
                except Exception as exc:
                    failed_lines += 1
                    logger.warning(
                        "Failed to render line %d (speaker: %s): %s", i, speaker, exc
                    )
                    continue

            if not audio_files:
                logger.warning("No audio files generated for conversation")
                return None

            # A conversation missing a chunk of its lines is broken on
            # air (replies to lines nobody hears) — fail it instead.
            if failed_lines > len(lines) * 0.2:
                raise RuntimeError(
                    f"{failed_lines}/{len(lines)} conversation lines failed "
                    f"to render — discarding segment"
                )

            os.makedirs(self._talks_dir, exist_ok=True)
            output_path = os.path.join(
                self._talks_dir, f"conversation_{segment_id}.wav"
            )

            # Stitch with per-line gaps; raises on failure.
            stitched = await concat_audio_files_variable(
                audio_files, line_gaps, output_path
            )
            return stitched
        finally:
            # Per-line renders are intermediates — remove them on success
            # AND failure so aborted generations don't litter the breaks
            # directory. A single-line "conversation" is returned as-is,
            # so never delete the file that was handed back.
            for line_path in audio_files:
                if line_path != stitched:
                    try:
                        os.remove(line_path)
                    except OSError:
                        pass

    @staticmethod
    def _extract_summary(script_text: str | None, segment_type: str) -> str:
        """Extract a brief content summary from a segment script.

        For monologues, takes the first ~30 words. For conversations, extracts
        the key points from the first few exchanges.

        Args:
            script_text: The script text (plain text or JSON).
            segment_type: The segment type.

        Returns:
            A brief summary string.
        """
        if not script_text:
            return ""

        if segment_type != "monologue":
            try:
                lines = json.loads(script_text)
                if isinstance(lines, list) and lines:
                    # Take the first 2-3 meaningful lines
                    snippets = []
                    word_count = 0
                    for line in lines[:5]:
                        if not isinstance(line, dict):
                            continue
                        text = line.get("text", "")
                        if len(text.split()) < 3:
                            continue
                        snippets.append(text)
                        word_count += len(text.split())
                        if word_count > 40:
                            break
                    return " ".join(snippets)[:200]
            except (json.JSONDecodeError, TypeError):
                pass

        # For monologues or fallback: first ~40 words
        words = script_text.split()
        return " ".join(words[:40]) + ("..." if len(words) > 40 else "")

    def _build_voice_config_map(
        self, config: TalkShowConfig, host_name: str = "Host"
    ) -> dict[str, dict]:
        """Build a mapping of speaker names to voice configurations.

        Args:
            config: Talk show configuration.
            host_name: Speaker name the script uses for the host — the
                host voice is keyed under this name (and "Host") so
                script lines resolve to it by exact match.

        Returns:
            Dict mapping speaker name to voice config dict.
        """
        voice_map: dict[str, dict] = {}

        # Host voice
        host_config = parse_voice_settings(
            config.host_voice_settings, config.host_voice_id or ""
        )
        voice_map["Host"] = host_config
        voice_map[host_name] = host_config

        # Co-host voices
        if config.cohost_voices:
            try:
                cohosts = json.loads(config.cohost_voices)
                for cohost in cohosts:
                    name = cohost.get("name", "")
                    if name:
                        vc: dict = {"voice_id": cohost.get("voice_id", "")}
                        if cohost.get("voice_settings"):
                            vc.update(cohost["voice_settings"])
                        voice_map[name] = vc
            except (json.JSONDecodeError, TypeError):
                pass

        return voice_map
