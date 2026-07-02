"""Music buffer manager ensuring adequate ready tracks are available."""

import json
import logging
import random
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.audio_pipeline import AudioPipeline
from server.engine.dj_brain import get_effective_dj_config
from server.engine.generation_jobs import (
    fail_generation_job,
    finish_generation_job,
    start_generation_job,
)
from server.engine.timeline_mirror import mirror_track_ready
from server.events.emitter import event_bus
from server.models.show_style import show_styles
from server.models.station import Station
from server.models.style import Style
from server.models.track import Track
from server.providers.registry import ProviderRegistry
from server.utils.timeutils import resolve_timezone

logger = logging.getLogger(__name__)


class MusicBufferManager:
    """Monitors the track buffer and triggers generation when levels are low.

    Selects style prompts based on weights, time-of-day schedule, and recent
    history. Appends content policy suffix to every prompt. Runs generated
    audio through the processing pipeline before marking it ready.
    """

    def __init__(self) -> None:
        self._pipeline = AudioPipeline()
        self._generating = False

    async def check_and_fill(
        self, session: AsyncSession, show_id: int | None = None
    ) -> None:
        """Check current buffer depth and request new tracks if needed.

        Args:
            session: Async database session.
            show_id: Optional active show ID for show-specific style filtering.
        """
        if self._generating:
            logger.debug("Generation already in progress, skipping")
            return

        # Get station config
        result = await session.execute(select(Station).limit(1))
        station = result.scalar_one_or_none()
        buffer_target = station.buffer_target if station else 3
        buffer_warning = station.buffer_warning_threshold if station else 2

        # Count ready tracks
        result = await session.execute(
            select(func.count(Track.id)).where(Track.status == "ready")
        )
        ready_count = result.scalar() or 0

        logger.debug("Buffer: %d/%d ready tracks", ready_count, buffer_target)

        # Emit buffer warnings
        if ready_count <= 0:
            event_bus.emit("buffer.critical", {"ready": ready_count, "target": buffer_target})
        elif ready_count <= buffer_warning:
            event_bus.emit("buffer.low", {"ready": ready_count, "target": buffer_target})

        # Generate if below target
        if ready_count < buffer_target:
            await self._generate_track(session, show_id=show_id)

    async def get_buffer_depth(self, session: AsyncSession) -> int:
        """Get the current number of ready tracks.

        Args:
            session: Async database session.

        Returns:
            Count of tracks with status 'ready'.
        """
        result = await session.execute(
            select(func.count(Track.id)).where(Track.status == "ready")
        )
        return result.scalar() or 0

    async def _generate_track(
        self, session: AsyncSession, show_id: int | None = None
    ) -> None:
        """Generate a single new track using the music provider.

        Selects a style, builds the prompt with content policy suffix,
        calls the provider, and processes the resulting audio.

        Args:
            session: Async database session.
            show_id: Optional active show ID for show-specific style/config.
        """
        registry = ProviderRegistry.get_instance()
        music_provider = registry.get_music_provider()

        if music_provider is None:
            logger.warning("No music provider configured, cannot generate tracks")
            return

        self._generating = True
        track = None
        job = None
        try:
            # Select a style (show-specific if applicable)
            style = await self._select_style(session, show_id=show_id)
            if style is None:
                logger.warning("No active styles available for generation")
                return

            # Get content policy suffix from effective DJ config
            dj_config = await get_effective_dj_config(session, show_id=show_id)
            content_suffix = ""
            if dj_config and dj_config.content_policy_suffix:
                content_suffix = dj_config.content_policy_suffix
            elif dj_config and dj_config.content_policy == "instrumental_only":
                content_suffix = "Instrumental only, no vocals."
            elif dj_config and dj_config.content_policy == "clean_vocals":
                content_suffix = "Clean vocals only, no explicit content."

            # Vary the style prompt via LLM for creative diversity
            varied_prompt = await self._vary_prompt(style.prompt)

            # Build full prompt
            full_prompt = varied_prompt
            if content_suffix:
                full_prompt = f"{full_prompt}. {content_suffix}"

            logger.info("Generating track: style=%s, prompt=%s", style.name, full_prompt[:80])

            # Create track record
            track = Track(
                style_id=style.id,
                style_prompt=full_prompt,
                content_policy_suffix=content_suffix,
                provider=type(music_provider).__name__,
                status="generating",
            )
            session.add(track)
            await session.commit()
            await session.refresh(track)

            job = await start_generation_job(
                session,
                job_type="generate_track",
                capability="generate_music",
                provider=type(music_provider).__name__,
                input_data={
                    "track_id": track.id,
                    "style_id": style.id,
                    "show_id": show_id,
                    "prompt": full_prompt,
                },
            )
            await session.commit()

            # Call provider
            gen_result = await music_provider.generate(full_prompt)

            # Process audio through pipeline
            filepath = gen_result.get("filepath", "")
            if filepath:
                processed = await self._pipeline.process(filepath)
                track.filepath = processed["processed_path"]
                track.duration = processed["duration"]
                track.loudness_lufs = processed["loudness_lufs"]
            else:
                track.filepath = filepath
                track.duration = gen_result.get("duration", 0)

            track.title = gen_result.get("title", "Untitled")
            track.lyrics = gen_result.get("lyrics", "") or ""
            track.metadata_json = json.dumps(gen_result.get("metadata", {}))
            track.status = "ready"
            timeline_item = await mirror_track_ready(session, track)
            await finish_generation_job(
                session,
                job,
                output_data={
                    "track_id": track.id,
                    "title": track.title,
                    "duration": track.duration,
                },
                output_asset_id=timeline_item.audio_asset_id,
            )

            await session.commit()

            event_bus.emit("track.generated", {
                "track_id": track.id,
                "title": track.title,
                "style": style.name,
                "duration": track.duration,
            })
            logger.info("Track generated: id=%d, title=%s", track.id, track.title)

        except Exception as exc:
            logger.error("Track generation failed: %s", exc)
            # Mark the track as failed so it doesn't stay stuck in "generating"
            if track is not None and track.id is not None:
                try:
                    track.status = "failed"
                    if job is not None:
                        await fail_generation_job(session, job, exc)
                    await session.commit()
                except Exception:
                    logger.warning("Could not update track status to failed")
            event_bus.emit("provider.error", {
                "provider": "music",
                "error": str(exc),
            })
        finally:
            self._generating = False

    _VARY_INSTRUCTION = (
        "You are a music prompt writer. Given a base style description, "
        "create a fresh variation. Keep the same genre and mood but vary "
        "instruments, tempo descriptors, textures, and energy. "
        "Output ONLY the rewritten prompt, nothing else."
    )

    async def _vary_prompt(self, base_prompt: str) -> str:
        """Use the scriptwriter LLM to create a variation of a style prompt.

        Falls back to the original prompt if the provider is unavailable
        or the call fails.

        Args:
            base_prompt: The original style prompt text.

        Returns:
            A varied version of the prompt, or the original on failure.
        """
        registry = ProviderRegistry.get_instance()
        scriptwriter = registry.get_scriptwriter_provider()
        if scriptwriter is None:
            return base_prompt

        try:
            varied = await scriptwriter.rewrite_prompt(
                base_prompt, self._VARY_INSTRUCTION
            )
            return varied or base_prompt
        except Exception as exc:
            logger.warning("Prompt variation failed, using original: %s", exc)
            return base_prompt

    async def _select_style(
        self, session: AsyncSession, show_id: int | None = None
    ) -> Style | None:
        """Select a style prompt based on weights, schedule, and history.

        When *show_id* is provided and the show has linked styles, only
        those styles are eligible. Otherwise all active styles are used.
        Avoids repeating the same style back-to-back when possible.

        Args:
            session: Async database session.
            show_id: Optional active show ID for show-specific filtering.

        Returns:
            A Style instance, or None if no active styles exist.
        """
        # Check if the show has specific styles linked
        show_style_ids: list[int] | None = None
        if show_id is not None:
            result = await session.execute(
                select(show_styles.c.style_id).where(
                    show_styles.c.show_id == show_id
                )
            )
            ids = [row[0] for row in result.all()]
            if ids:
                show_style_ids = ids

        # Get active styles, optionally filtered to show-specific ones
        query = select(Style).where(Style.active.is_(True))
        if show_style_ids is not None:
            query = query.where(Style.id.in_(show_style_ids))

        result = await session.execute(query)
        styles = list(result.scalars().all())

        if not styles:
            return None

        # Filter by time-of-day schedule (in the station's local timezone)
        result = await session.execute(select(Station.timezone).limit(1))
        station_tz_name = result.scalar_one_or_none()
        now = datetime.now(resolve_timezone(station_tz_name))
        current_hour = now.hour
        eligible = []
        for style in styles:
            if style.schedule:
                try:
                    schedule = json.loads(style.schedule)
                    start_h = int(schedule.get("start", "00:00").split(":")[0])
                    end_h = int(schedule.get("end", "23:59").split(":")[0])
                    if start_h <= end_h:
                        if start_h <= current_hour <= end_h:
                            eligible.append(style)
                    else:  # Wraps midnight
                        if current_hour >= start_h or current_hour <= end_h:
                            eligible.append(style)
                except (json.JSONDecodeError, ValueError):
                    eligible.append(style)
            else:
                eligible.append(style)

        if not eligible:
            eligible = styles  # Fall back to all active if schedule filters everything

        # Check last generated style to avoid back-to-back
        result = await session.execute(
            select(Track.style_id)
            .where(Track.style_id.isnot(None))
            .order_by(Track.created_at.desc())
            .limit(1)
        )
        last_style_id = result.scalar_one_or_none()

        # Remove last style if we have alternatives
        if last_style_id and len(eligible) > 1:
            eligible = [s for s in eligible if s.id != last_style_id] or eligible

        # Weighted random selection
        weights = [s.weight for s in eligible]
        total = sum(weights)
        if total == 0:
            return random.choice(eligible)

        return random.choices(eligible, weights=weights, k=1)[0]
