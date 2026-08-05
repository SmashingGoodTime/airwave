"""DJ Brain responsible for generating DJ break scripts and audio.

Assembles context from recent tracks, announcements, and station config,
then generates a script and renders it to audio via the configured providers.
"""

import json
import logging
import random
from datetime import datetime, timezone

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from server.engine.audio_pipeline import AudioPipeline
from server.engine.generation_jobs import (
    fail_generation_job,
    finish_generation_job,
    start_generation_job,
)
from server.engine.timeline_mirror import mirror_dj_break_ready
from server.events.emitter import event_bus
from server.models.announcement import Announcement
from server.models.dj_break import DJBreak
from server.models.dj_config import DJConfig
from server.models.playlog import PlayLog
from server.models.show import Show
from server.models.station import Station, get_station
from server.models.style import Style
from server.models.track import Track
from server.providers.registry import ProviderRegistry
from server.utils.timeutils import resolve_timezone, utcnow_naive
from server.utils.voice import parse_voice_settings

logger = logging.getLogger(__name__)


async def get_effective_dj_config(
    session: AsyncSession, show_id: int | None = None
) -> DJConfig | None:
    """Resolve the DJ config for the current context.

    If *show_id* is given and the show has a ``dj_config_id``, that config
    is returned.  Otherwise, falls back to the station default (the row
    with ``is_default=True``), then to any existing config.

    Args:
        session: Async database session.
        show_id: Optional active show ID.

    Returns:
        A DJConfig instance, or None if the table is empty.
    """
    if show_id is not None:
        show_result = await session.execute(
            select(Show).where(Show.id == show_id)
        )
        show = show_result.scalar_one_or_none()
        if show and show.dj_config_id:
            cfg_result = await session.execute(
                select(DJConfig).where(DJConfig.id == show.dj_config_id)
            )
            cfg = cfg_result.scalar_one_or_none()
            if cfg is not None:
                return cfg

    # Fall back to default
    result = await session.execute(
        select(DJConfig).where(DJConfig.is_default.is_(True)).limit(1)
    )
    cfg = result.scalar_one_or_none()
    if cfg is not None:
        return cfg

    # Last resort — any config
    result = await session.execute(select(DJConfig).limit(1))
    return result.scalar_one_or_none()


class DJBrain:
    """Generates contextual DJ break scripts and renders them to audio.

    Tracks how many songs have played since the last break and triggers
    break generation at the configured interval (with variance).
    """

    def __init__(self) -> None:
        self._pipeline = AudioPipeline()
        self._tracks_since_break = 0
        self._next_break_at: int | None = None

    def track_played(self) -> None:
        """Record that a track has finished playing.

        Increments the counter used to determine when the next break should occur.
        """
        self._tracks_since_break += 1

    def should_break(self, break_frequency: int = 3, variance: int = 1) -> bool:
        """Check whether it's time for a DJ break.

        Args:
            break_frequency: Base number of tracks between breaks.
            variance: Random variance range (±).

        Returns:
            True if enough tracks have played to trigger a break.
        """
        if self._next_break_at is None:
            self._next_break_at = break_frequency + random.randint(-variance, variance)
            self._next_break_at = max(1, self._next_break_at)

        return self._tracks_since_break >= self._next_break_at

    def should_prepare_break(self, break_frequency: int = 3, variance: int = 1) -> bool:
        """Check whether a DJ break should start pre-generating.

        Returns True one track before ``should_break`` would fire so the
        break audio is ready the moment it's needed — eliminating the
        5-20 second generation delay that causes stale song references.

        Args:
            break_frequency: Base number of tracks between breaks.
            variance: Random variance range (±).

        Returns:
            True if the next track will trigger a break.
        """
        if self._next_break_at is None:
            self._next_break_at = break_frequency + random.randint(-variance, variance)
            self._next_break_at = max(1, self._next_break_at)

        return self._tracks_since_break >= self._next_break_at - 1

    def reset_break_counter(self) -> None:
        """Reset the track counter after a break has been played."""
        self._tracks_since_break = 0
        self._next_break_at = None

    async def generate_show_intro(
        self, session: AsyncSession, show: object | None = None,
        show_id: int | None = None,
    ) -> DJBreak | None:
        """Generate a DJ intro for when the station or a show starts broadcasting.

        This creates a special break where the DJ introduces the station/show
        before any music plays. Uses the same script + voice pipeline as
        regular breaks but with intro-specific context.

        Args:
            session: Async database session.
            show: Optional Show object if a specific show is starting.
                  If None, generates a general station startup intro.

        Returns:
            The created DJBreak record, or None if generation failed.
        """
        registry = ProviderRegistry.get_instance()
        scriptwriter = registry.get_scriptwriter_provider()

        if scriptwriter is None:
            logger.warning("No scriptwriter provider configured, skipping show intro")
            return None

        dj_break: DJBreak | None = None
        try:
            effective_show_id = show_id or (getattr(show, "id", None) if show else None)
            context = await self._build_context(session, show_id=effective_show_id)

            # Override context with show intro instructions
            context["is_show_intro"] = True
            if show is not None:
                context["show_name"] = getattr(show, "name", "")
                context["intro_instruction"] = (
                    f"You are OPENING the show '{show.name}'. Welcome listeners, "
                    f"introduce the show by name, set the mood, and let them know "
                    f"what they're in for. Be enthusiastic and engaging. "
                    f"Do NOT reference any previous tracks — this is the very start."
                )
            else:
                context["intro_instruction"] = (
                    "You are OPENING the broadcast. Welcome listeners to the station, "
                    "introduce yourself as the DJ, mention the station name, set the vibe, "
                    "and let them know what kind of music is coming up. "
                    "Be warm, enthusiastic, and engaging — this is the very first thing "
                    "listeners will hear. Do NOT reference any previous tracks."
                )
            # Clear recent tracks since none have played yet
            context["recent_tracks"] = []

            logger.info("Generating show intro DJ break...")

            script_result = await scriptwriter.write_break(context)
            script_text = script_result.get("script_text", "")

            if not script_text:
                logger.warning("Scriptwriter returned empty intro script")
                return None

            dj_break = DJBreak(
                script_text=script_text,
                context=json.dumps(context, default=str),
                status="generating",
            )
            session.add(dj_break)
            await session.commit()
            await session.refresh(dj_break)

            voice = registry.get_voice_provider()
            if voice is not None:
                voice_config = await self._get_voice_config(session, show_id=effective_show_id)
                audio_path = await voice.render(script_text, voice_config)
                processed = await self._pipeline.process(
                    audio_path, voice=True, delete_source=True
                )
                dj_break.audio_filepath = processed["processed_path"]
                dj_break.duration = processed["duration"]
            else:
                logger.warning("No voice provider — intro will have script only")
                word_count = len(script_text.split())
                dj_break.duration = (word_count / 150) * 60

            dj_break.status = "ready"
            await mirror_dj_break_ready(session, dj_break)
            await session.commit()

            event_bus.emit("break.generated", {
                "break_id": dj_break.id,
                "duration": dj_break.duration,
                "has_audio": dj_break.audio_filepath is not None,
                "is_show_intro": True,
            })
            logger.info(
                "Show intro generated: id=%d, duration=%.1fs",
                dj_break.id, dj_break.duration or 0,
            )

            return dj_break

        except Exception as exc:
            logger.error("Show intro generation failed: %s", exc)
            # The original exception may have poisoned the session
            # (e.g. a failed flush) — roll back before writing failure state.
            try:
                await session.rollback()
            except Exception:
                pass
            if dj_break is not None and dj_break.id is not None:
                try:
                    dj_break.status = "failed"
                    await session.commit()
                except Exception:
                    logger.warning("Could not mark show intro break as failed")
            event_bus.emit("provider.error", {
                "provider": "scriptwriter",
                "error": str(exc),
            })
            return None

    async def generate_break(
        self, session: AsyncSession, show_id: int | None = None,
        queue_offset: int = 0,
    ) -> DJBreak | None:
        """Generate a new DJ break based on current playback context.

        Gathers context from recent tracks and announcements, generates
        a script via the scriptwriter provider, and renders audio via
        the voice provider.

        Args:
            session: Async database session.
            show_id: Optional active show ID for show-specific config.
            queue_offset: Liquidsoap queue depth — used to skip tracks
                that are marked played/playing in the DB but haven't
                actually been heard by the listener yet.

        Returns:
            The created DJBreak record, or None if generation failed.
        """
        registry = ProviderRegistry.get_instance()
        scriptwriter = registry.get_scriptwriter_provider()

        if scriptwriter is None:
            logger.warning("No scriptwriter provider configured, skipping DJ break")
            return None

        job = None
        dj_break: DJBreak | None = None
        try:
            # Assemble context, offset by queue depth so the DJ
            # references songs the listener has actually heard.
            context = await self._build_context(
                session, show_id=show_id, queue_offset=queue_offset,
            )

            logger.info("Generating DJ break script...")

            job = await start_generation_job(
                session,
                job_type="generate_dj_break",
                capability="write_dj_break",
                provider=type(scriptwriter).__name__,
                input_data={
                    "show_id": show_id,
                    "queue_offset": queue_offset,
                    "station_name": context.get("station_name"),
                    "dj_name": context.get("dj_name"),
                },
            )
            await session.commit()

            # Generate script
            script_result = await scriptwriter.write_break(context)
            script_text = script_result.get("script_text", "")

            if not script_text:
                logger.warning("Scriptwriter returned empty script")
                await fail_generation_job(
                    session, job, "Scriptwriter returned empty script"
                )
                await session.commit()
                return None

            # Create break record
            dj_break = DJBreak(
                script_text=script_text,
                context=json.dumps(context, default=str),
                status="generating",
            )
            session.add(dj_break)
            await session.commit()
            await session.refresh(dj_break)

            # Render audio via voice provider
            voice = registry.get_voice_provider()
            if voice is not None:
                voice_config = await self._get_voice_config(session, show_id=show_id)
                audio_path = await voice.render(script_text, voice_config)

                # Process audio through pipeline
                processed = await self._pipeline.process(
                    audio_path, voice=True, delete_source=True
                )
                dj_break.audio_filepath = processed["processed_path"]
                dj_break.duration = processed["duration"]
            else:
                logger.warning("No voice provider — break will have script only")
                # Estimate duration from word count
                word_count = len(script_text.split())
                dj_break.duration = (word_count / 150) * 60

            dj_break.status = "ready"
            timeline_item = await mirror_dj_break_ready(session, dj_break)
            await finish_generation_job(
                session,
                job,
                output_data={
                    "break_id": dj_break.id,
                    "duration": dj_break.duration,
                    "has_audio": dj_break.audio_filepath is not None,
                },
                output_asset_id=timeline_item.audio_asset_id,
            )
            await session.commit()

            event_bus.emit("break.generated", {
                "break_id": dj_break.id,
                "duration": dj_break.duration,
                "has_audio": dj_break.audio_filepath is not None,
            })
            logger.info(
                "DJ break generated: id=%d, duration=%.1fs",
                dj_break.id, dj_break.duration or 0,
            )

            # NOTE: the break counter is NOT reset here — the scheduler
            # resets it only after the break is successfully queued for
            # playout, so background pre-generation cannot shorten the
            # effective break interval.
            return dj_break

        except Exception as exc:
            logger.error("DJ break generation failed: %s", exc)
            # The original exception may have poisoned the session
            # (e.g. a failed flush) — roll back before writing failure state.
            try:
                await session.rollback()
            except Exception:
                pass
            try:
                if dj_break is not None and dj_break.id is not None:
                    dj_break.status = "failed"
                if job is not None:
                    await fail_generation_job(session, job, exc)
                await session.commit()
            except Exception:
                logger.warning("Could not update DJ break/job status to failed")
            event_bus.emit("provider.error", {
                "provider": "scriptwriter",
                "error": str(exc),
            })
            return None

    async def _build_context(
        self, session: AsyncSession, show_id: int | None = None,
        queue_offset: int = 0,
    ) -> dict:
        """Assemble context for the DJ break script generator.

        Args:
            session: Async database session.
            show_id: Optional active show ID for show-specific DJ config.
            queue_offset: Number of tracks to skip from the most recent
                "played"/"playing" results.  Tracks are marked as
                "playing"/"played" in the DB the moment they are pushed
                to Liquidsoap's queue, which runs ahead of what the
                listener has actually heard.  Passing the current
                Liquidsoap queue depth here corrects for that offset so
                the DJ references songs the listener genuinely just heard.

        Returns:
            A dict with recent_tracks, announcements, station info, and time.
        """
        # Get DJ config (show-specific or default)
        dj_config = await get_effective_dj_config(session, show_id=show_id)

        # Get station config for timezone
        station = await get_station(session)

        # Get recent tracks with their style info.
        # Fetch extra rows equal to queue_offset so we can skip tracks
        # that are still waiting in Liquidsoap's queue (their DB status
        # has been prematurely advanced to "played"/"playing").
        fetch_count = 5 + queue_offset
        result = await session.execute(
            select(Track)
            .where(Track.status.in_(["played", "playing"]))
            .order_by(Track.played_at.desc())
            .limit(fetch_count)
        )
        all_tracks = result.scalars().all()
        tracks = all_tracks[queue_offset:]

        # Batch-fetch linked styles for genre/tag info
        style_ids = [t.style_id for t in tracks if t.style_id is not None]
        styles_by_id = {}
        if style_ids:
            style_result = await session.execute(
                select(Style).where(Style.id.in_(style_ids))
            )
            for s in style_result.scalars().all():
                styles_by_id[s.id] = s

        recent_tracks = []
        for track in tracks:
            style = styles_by_id.get(track.style_id)
            style_name = style.name if style else (track.style_prompt[:50] if track.style_prompt else "")
            tags = style.tags if style and style.tags else ""
            recent_tracks.append({
                "title": track.title or "Unknown",
                "style": style_name,
                "tags": tags,
            })

        # Get active announcements (prioritized)
        now = datetime.now(timezone.utc)
        now_naive = utcnow_naive()  # DB stores naive UTC datetimes

        _priority_order = case(
            (Announcement.priority == "urgent", 0),
            (Announcement.priority == "high", 1),
            (Announcement.priority == "normal", 2),
            (Announcement.priority == "low", 3),
            else_=4,
        )
        result = await session.execute(
            select(Announcement)
            .where(
                Announcement.active.is_(True),
                or_(Announcement.expires_at.is_(None), Announcement.expires_at > now_naive),
                or_(Announcement.max_plays.is_(None), Announcement.play_count < Announcement.max_plays),
            )
            .order_by(_priority_order, Announcement.created_at.desc())
            .limit(3)
        )
        announcements = [
            {"id": ann.id, "text": ann.text, "priority": ann.priority}
            for ann in result.scalars().all()
        ]

        # Convert current time to station's local timezone
        station_tz = resolve_timezone(station.timezone if station else None)
        local_now = now.astimezone(station_tz)

        # Use time-of-day period instead of exact minutes to avoid the
        # break sounding wrong after generation + TTS delay (30s-2min).
        current_time_desc = self._describe_time_of_day(local_now)

        # Build context
        context = {
            "station_name": dj_config.station_name if dj_config else "AI Radio",
            "dj_name": dj_config.dj_name if dj_config else "DJ",
            "personality_prompt": dj_config.personality_prompt if dj_config else "",
            "max_duration": dj_config.max_break_duration if dj_config else 60,
            "mention_time": dj_config.mention_time if dj_config else True,
            "recent_tracks": recent_tracks,
            "announcements": announcements,
            "current_time": current_time_desc,
        }

        return context

    @staticmethod
    def _describe_time_of_day(local_now: datetime) -> str:
        """Convert a datetime to a natural time-of-day description.

        Returns a rounded hour description rather than exact minutes so
        the DJ break still sounds correct after the generation + TTS
        delay (which can be 30 seconds to 2+ minutes).

        Args:
            local_now: The current datetime in the station's local timezone.

        Returns:
            A human-friendly time description, e.g. "Thursday evening, around 7"
            or "Saturday morning, just after 10".
        """
        hour = local_now.hour
        minute = local_now.minute
        day_name = local_now.strftime("%A")

        # Determine period of day
        if 5 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 17:
            period = "afternoon"
        elif 17 <= hour < 21:
            period = "evening"
        else:
            period = "night"

        # Round to a natural description that tolerates a few minutes drift
        display_hour = hour % 12 or 12
        am_pm = "in the morning" if hour < 12 else "in the afternoon" if hour < 17 else "in the evening" if hour < 21 else "at night"
        if minute < 5:
            time_desc = f"around {display_hour} {am_pm}"
        elif minute < 20:
            time_desc = f"just after {display_hour} {am_pm}"
        elif minute < 40:
            time_desc = f"about half past {display_hour} {am_pm}"
        elif minute < 55:
            next_hour = (hour + 1) % 12 or 12
            # If crossing noon/midnight boundary, adjust the am/pm
            next_am_pm = "in the morning" if (hour + 1) % 24 < 12 else "in the afternoon" if (hour + 1) % 24 < 17 else "in the evening" if (hour + 1) % 24 < 21 else "at night"
            time_desc = f"almost {next_hour} {next_am_pm}"
        else:
            next_hour = (hour + 1) % 12 or 12
            next_am_pm = "in the morning" if (hour + 1) % 24 < 12 else "in the afternoon" if (hour + 1) % 24 < 17 else "in the evening" if (hour + 1) % 24 < 21 else "at night"
            time_desc = f"around {next_hour} {next_am_pm}"

        return f"{day_name} {period}, {time_desc}"

    async def _get_voice_config(
        self, session: AsyncSession, show_id: int | None = None
    ) -> dict:
        """Get voice configuration from DJ config.

        Args:
            session: Async database session.
            show_id: Optional active show ID for show-specific DJ config.

        Returns:
            A dict with voice_id and voice settings.
        """
        dj_config = await get_effective_dj_config(session, show_id=show_id)

        if dj_config is None:
            return {"voice_id": "Aoede"}  # Default Gemini TTS voice

        return parse_voice_settings(
            dj_config.voice_settings, dj_config.voice_id or "Aoede"
        )

    async def increment_announcement_plays(
        self, session: AsyncSession, announcement_ids: list[int]
    ) -> None:
        """Increment play_count for announcements included in a break.

        Args:
            session: Async database session.
            announcement_ids: IDs of announcements that were played.
        """
        for ann_id in announcement_ids:
            result = await session.execute(
                select(Announcement).where(Announcement.id == ann_id)
            )
            ann = result.scalar_one_or_none()
            if ann:
                ann.play_count += 1
        await session.commit()
