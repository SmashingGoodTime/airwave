"""Master scheduler coordinating music generation, DJ breaks, talk shows, and playout.

The main orchestration loop that ties together buffer management, DJ brain,
talk show engine, call management, playout interface, disk cleanup, and
dead air protection. Show-aware: delegates to different engines based on
the active show type.
"""

import asyncio
import json
import logging
import random
import shutil
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.config import settings
from server.database import get_session_factory
from server.engine.dj_brain import DJBrain
from server.engine.music_buffer import MusicBufferManager
from server.engine.playout import PlayoutInterface
from server.engine.talk_show import TalkShowEngine
from server.engine.timeline_state import (
    mark_source_failed,
    mark_source_played,
    mark_source_playing,
)
from server.events.emitter import event_bus
from server.engine.dj_brain import get_effective_dj_config
from server.models.dj_break import DJBreak
from server.models.dj_config import DJConfig
from server.models.playlog import PlayLog
from server.models.show import Show
from server.models.station import Station
from server.models.talk_segment import TalkSegment
from server.models.track import Track

logger = logging.getLogger(__name__)

# How often each loop runs (seconds)
BUFFER_CHECK_INTERVAL = 30
PLAYOUT_CHECK_INTERVAL = 5
CLEANUP_INTERVAL = 3600  # 1 hour
HEALTH_CHECK_INTERVAL = 300  # 5 minutes
SHOW_CHECK_INTERVAL = 30  # Check for show transitions


class MasterScheduler:
    """Orchestrates the timing of music generation, DJ breaks, talk shows, and playout.

    Runs as async background tasks on app startup. Show-aware: when a talk
    show is active, delegates to TalkShowEngine instead of MusicBufferManager.
    When no show is scheduled, falls back to default music mode for backward
    compatibility.
    """

    def __init__(self) -> None:
        self._buffer_manager = MusicBufferManager()
        self._dj_brain = DJBrain()
        self._talk_engine = TalkShowEngine(audio_dir=settings.AUDIO_DIR)
        self._playout = PlayoutInterface(
            host=settings.LIQUIDSOAP_HOST,
            port=settings.LIQUIDSOAP_PORT,
        )
        self._running = False
        self._streaming = False
        self._streaming_show_type: str | None = None
        self._tasks: list[asyncio.Task] = []
        self._fallback_dir = Path(settings.AUDIO_DIR) / "fallback"
        self._consecutive_playout_errors = 0
        self._consecutive_buffer_errors = 0
        self._current_show_id: int | None = None
        self._current_show_type: str | None = None
        self._force_show_reload = False
        # Pre-generated DJ break ready for immediate queueing
        self._pending_break: DJBreak | None = None
        self._pending_break_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start all scheduler loops as background tasks."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        logger.info("Starting master scheduler...")

        # Ensure audio directories exist
        for subdir in [
            "tracks", "breaks", "fallback", "archive",
            "talks", "calls", "calls/raw", "calls/processed",
            "recordings",
        ]:
            (Path(settings.AUDIO_DIR) / subdir).mkdir(
                parents=True, exist_ok=True
            )

        # Auto-start recording if enabled in station config
        await self._restore_recording_state()

        # NOTE: No auto-start of streaming — user must click Start in the UI.
        # _queue_startup_intro() is called from start_streaming() instead.

        self._tasks = [
            asyncio.create_task(
                self._safe_loop(
                    self._buffer_loop, "buffer_loop", BUFFER_CHECK_INTERVAL
                ),
                name="buffer_loop",
            ),
            asyncio.create_task(
                self._safe_loop(
                    self._playout_step, "playout_loop", PLAYOUT_CHECK_INTERVAL
                ),
                name="playout_loop",
            ),
            asyncio.create_task(
                self._safe_loop(
                    self._cleanup_step, "cleanup_loop", CLEANUP_INTERVAL
                ),
                name="cleanup_loop",
            ),
            asyncio.create_task(
                self._safe_loop(
                    self._show_transition_step, "show_loop", SHOW_CHECK_INTERVAL
                ),
                name="show_loop",
            ),
        ]

        logger.info(
            "Master scheduler started with %d background tasks",
            len(self._tasks),
        )

    async def stop(self) -> None:
        """Stop all scheduler loops gracefully."""
        self._running = False
        logger.info("Stopping master scheduler...")

        for task in self._tasks:
            task.cancel()

        if self._pending_break_task is not None:
            self._pending_break_task.cancel()
            self._pending_break_task = None
            self._pending_break = None

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

        logger.info("Master scheduler stopped")

    @property
    def is_streaming(self) -> bool:
        """Whether the station is actively streaming."""
        return self._streaming

    @property
    def streaming_show_type(self) -> str | None:
        """The show type selected for the current streaming session."""
        return self._streaming_show_type

    async def start_streaming(self) -> None:
        """Start streaming. Resolves the active show type on startup."""
        if self._streaming:
            logger.warning("Streaming already active")
            return

        # Resolve active show type
        factory = get_session_factory()
        async with factory() as session:
            active_show = await self._get_active_show(session)
            show_type = active_show.show_type if active_show else "music"

        self._streaming_show_type = show_type
        self._current_show_id = active_show.id if active_show else None
        self._current_show_type = active_show.show_type if active_show else None
        self._streaming = True
        logger.info("Streaming started (show_type=%s)", show_type)

        # Wait for Liquidsoap telnet to be ready before queueing anything
        ready = await self._playout.wait_until_ready(timeout=30.0, interval=1.0)
        if not ready:
            logger.warning(
                "Liquidsoap not ready after timeout — will retry queueing "
                "in the next scheduler tick"
            )

        # Generate and queue a startup intro
        await self._queue_startup_intro()

        event_bus.emit("stream.started", {"show_type": show_type})

    async def stop_streaming(self) -> None:
        """Stop streaming. The scheduler keeps running but stops generating and playing content."""
        if not self._streaming:
            logger.warning("Streaming not active")
            return

        self._streaming = False
        show_type = self._streaming_show_type
        self._streaming_show_type = None
        self._current_show_id = None
        self._current_show_type = None
        logger.info("Streaming stopped")

        event_bus.emit("stream.stopped", {"show_type": show_type})

    async def trigger_show_reload(self) -> None:
        """Force the scheduler to re-evaluate the active show block immediately."""
        self._force_show_reload = True
        factory = get_session_factory()
        async with factory() as session:
            await self._show_transition_step(session)

    async def _safe_loop(
        self,
        step_func,
        loop_name: str,
        interval: float,
    ) -> None:
        """Run a step function in a loop with error isolation.

        Each iteration is wrapped in a try/except so that a single
        failure never kills the loop. Consecutive errors increase
        the sleep interval to avoid hammering broken services.

        Args:
            step_func: Async function to run each iteration.
            loop_name: Name for logging.
            interval: Base sleep interval between iterations.
        """
        consecutive_errors = 0
        max_backoff = interval * 10

        while self._running:
            try:
                factory = get_session_factory()
                async with factory() as session:
                    await step_func(session)
                consecutive_errors = 0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                consecutive_errors += 1
                logger.error(
                    "%s error (#%d): %s",
                    loop_name,
                    consecutive_errors,
                    exc,
                    exc_info=consecutive_errors == 1,
                )
                if consecutive_errors >= 10:
                    logger.critical(
                        "%s has failed %d times consecutively",
                        loop_name,
                        consecutive_errors,
                    )

            # Backoff on consecutive errors
            sleep_time = interval
            if consecutive_errors > 0:
                sleep_time = min(
                    interval * (2 ** min(consecutive_errors, 5)),
                    max_backoff,
                )
            await asyncio.sleep(sleep_time)

    async def _restore_recording_state(self) -> None:
        """Start the Liquidsoap recorder if recording was enabled in config."""
        try:
            factory = get_session_factory()
            async with factory() as session:
                result = await session.execute(select(Station).limit(1))
                station = result.scalar_one_or_none()
                if station and station.recording_enabled:
                    started = await self._playout.start_recording()
                    if started:
                        logger.info("Recording auto-started (was enabled in config)")
                    else:
                        logger.warning("Failed to auto-start recording")
        except Exception as exc:
            logger.debug("Could not restore recording state: %s", exc)

    async def _queue_startup_intro(self) -> None:
        """Generate and queue a DJ show intro when the station first starts.

        This ensures listeners hear the DJ introduce the station/show before
        any music plays. If generation fails, the station continues without
        an intro (graceful degradation).
        """
        try:
            factory = get_session_factory()
            async with factory() as session:
                # Check if there's an active show to intro
                active_show = await self._get_active_show(session)

                logger.info("Generating startup show intro...")
                dj_break = await self._dj_brain.generate_show_intro(
                    session, show=active_show
                )

                if dj_break and dj_break.audio_filepath:
                    queued = await self._playout.queue_break(
                        dj_break.audio_filepath
                    )
                    if queued:
                        await self._log_play(
                            session,
                            "dj_break",
                            dj_break.id,
                            dj_break.duration,
                            {"is_show_intro": True},
                        )
                        await self._record_timeline_update(
                            lambda timeline_session: mark_source_playing(
                                timeline_session,
                                "dj_breaks",
                                dj_break.id,
                            )
                        )
                        event_bus.emit(
                            "break.started",
                            {
                                "break_id": dj_break.id,
                                "is_show_intro": True,
                                "script_text": dj_break.script_text or "",
                                "duration": dj_break.duration or 0,
                            },
                        )
                        logger.info("Show intro queued for playout")
                    else:
                        logger.warning(
                            "Failed to queue show intro — Liquidsoap may not "
                            "be ready yet"
                        )
                else:
                    logger.warning(
                        "Show intro generation returned no audio, "
                        "starting without intro"
                    )
        except Exception as exc:
            logger.warning("Could not generate startup intro: %s", exc)

    async def _buffer_loop(self, session: AsyncSession) -> None:
        """Check buffer depth and generate content based on active show type.

        Always keeps the music buffer filled regardless of streaming state,
        so tracks are ready when streaming starts. Talk segments are only
        generated while streaming is active.

        Args:
            session: Async database session.
        """
        # Determine active show for style/DJ filtering
        active_show = await self._get_active_show(session)
        show_id = active_show.id if active_show else None

        # Always fill the music buffer so tracks are ready before streaming
        await self._buffer_manager.check_and_fill(session, show_id=show_id)

        if not self._streaming:
            return
        show_type = (
            active_show.show_type if active_show
            else (self._streaming_show_type or "music")
        )

        # Resolve a talk-capable show for talk/hybrid modes
        talk_show = active_show
        if show_type in ("talk", "hybrid") and not talk_show:
            talk_show = await self._get_talk_show_fallback(session)
            if not talk_show:
                logger.warning(
                    "Streaming in %s mode but no talk show or config found",
                    show_type,
                )

        if show_type == "talk" and talk_show:
            # Talk show mode — generate talk segments instead of music
            await self._talk_engine.check_and_fill(session, talk_show)
        elif show_type == "hybrid" and talk_show:
            # Hybrid mode — talk segments alongside music (already filled above)
            await self._talk_engine.check_and_fill(session, talk_show)

    async def _playout_step(self, session: AsyncSession) -> None:
        """Monitor playout state and queue next items based on show type.

        Args:
            session: Async database session.
        """
        if not self._streaming:
            return

        active_show = await self._get_active_show(session)
        show_type = (
            active_show.show_type if active_show
            else (self._streaming_show_type or "music")
        )

        # Resolve a talk-capable show for talk mode
        talk_show = active_show
        if show_type in ("talk", "hybrid") and not talk_show:
            talk_show = await self._get_talk_show_fallback(session)

        if show_type == "talk" and talk_show:
            await self._manage_talk_playout(session, talk_show)
        elif show_type == "hybrid" and talk_show:
            await self._manage_hybrid_playout(session, talk_show)
        else:
            # Music mode (default) or hybrid — use existing music playout
            await self._manage_playout(session)

    async def _show_transition_step(self, session: AsyncSession) -> None:
        """Detect show transitions and emit events.

        Args:
            session: Async database session.
        """
        if not self._streaming:
            return

        active_show = await self._get_active_show(session)
        new_show_id = active_show.id if active_show else None
        new_show_type = active_show.show_type if active_show else None

        if new_show_id != self._current_show_id:
            # Show transition detected
            if self._current_show_id is not None:
                event_bus.emit("show.ended", {
                    "show_id": self._current_show_id,
                    "show_type": self._current_show_type,
                })
                logger.info(
                    "Show ended: id=%s type=%s",
                    self._current_show_id,
                    self._current_show_type,
                )

                # If transitioning to no show, revert to music mode
                if new_show_id is None and self._streaming_show_type != "music":
                    old_type = self._streaming_show_type
                    self._streaming_show_type = "music"
                    event_bus.emit("stream.mode_changed", {
                        "old_show_type": old_type,
                        "show_type": "music",
                    })

            if new_show_id is not None:
                # Update streaming show type to match the new show
                old_streaming_type = self._streaming_show_type
                self._streaming_show_type = active_show.show_type

                event_bus.emit("show.started", {
                    "show_id": active_show.id,
                    "show_name": active_show.name,
                    "show_type": active_show.show_type,
                })

                # Notify UI of mode change if the show type actually changed
                if old_streaming_type != active_show.show_type:
                    event_bus.emit("stream.mode_changed", {
                        "old_show_type": old_streaming_type,
                        "show_type": active_show.show_type,
                    })

                logger.info(
                    "Show started: '%s' (type=%s)",
                    active_show.name,
                    active_show.show_type,
                )

                # Generate and queue a DJ intro for the new show
                try:
                    intro = await self._dj_brain.generate_show_intro(
                        session, show=active_show, show_id=active_show.id
                    )
                    if intro and intro.audio_filepath:
                        queued = await self._playout.queue_break(
                            intro.audio_filepath
                        )
                        if queued:
                            await self._log_play(
                                session,
                                "dj_break",
                                intro.id,
                                intro.duration,
                                {"is_show_intro": True, "show_id": active_show.id},
                            )
                            await self._record_timeline_update(
                                lambda timeline_session: mark_source_playing(
                                    timeline_session,
                                    "dj_breaks",
                                    intro.id,
                                )
                            )
                            event_bus.emit(
                                "break.started",
                                {
                                    "break_id": intro.id,
                                    "is_show_intro": True,
                                    "script_text": intro.script_text or "",
                                    "duration": intro.duration or 0,
                                },
                            )
                            logger.info(
                                "Show intro queued for '%s'", active_show.name
                            )
                except Exception as exc:
                    logger.warning(
                        "Failed to generate show intro for '%s': %s",
                        active_show.name,
                        exc,
                    )

            self._current_show_id = new_show_id
            self._current_show_type = new_show_type

    async def _cleanup_step(self, session: AsyncSession) -> None:
        """Archive old tracks and clean up disk.

        Args:
            session: Async database session.
        """
        await self._run_cleanup(session)
        await self._check_disk_space()

    async def _manage_playout(self, session: AsyncSession) -> None:
        """Check playout state and queue the next item if needed.

        Handles the logic of alternating between tracks and DJ breaks
        based on the configured break frequency.  Uses pre-generation:
        break audio is prepared one track early so it can be queued
        instantly without a 5-20 second generation delay (which caused
        the DJ to reference songs that were already several tracks old
        by the time the break actually played).

        Args:
            session: Async database session.
        """
        # Check Liquidsoap queue
        queue_length = await self._playout.get_queue_length()

        if queue_length >= 1:
            self._consecutive_playout_errors = 0
            return

        # Get DJ config for break frequency (show-aware)
        active_show = await self._get_active_show(session)
        show_id = active_show.id if active_show else None
        dj_config = await get_effective_dj_config(session, show_id=show_id)
        break_freq = dj_config.break_frequency if dj_config else 3
        break_var = dj_config.break_frequency_variance if dj_config else 1

        # Check if it's time for a DJ break
        if self._dj_brain.should_break(break_freq, break_var):
            try:
                dj_break = await self._use_or_generate_break(
                    session, show_id, queue_length
                )
                if dj_break and dj_break.audio_filepath:
                    queued = await self._playout.queue_break(
                        dj_break.audio_filepath
                    )
                    if queued:
                        await self._log_play(
                            session,
                            "dj_break",
                            dj_break.id,
                            dj_break.duration,
                        )
                        await self._record_timeline_update(
                            lambda timeline_session: mark_source_playing(
                                timeline_session,
                                "dj_breaks",
                                dj_break.id,
                            )
                        )
                        if dj_break.context:
                            await self._update_announcement_plays(
                                session, dj_break.context
                            )
                        event_bus.emit(
                            "break.started",
                            {
                                "break_id": dj_break.id,
                                "script_text": dj_break.script_text or "",
                                "duration": dj_break.duration or 0,
                            },
                        )
                        return
            except Exception as exc:
                logger.error("DJ break generation/queueing failed: %s", exc)
                # Don't let break failure prevent track queueing

        elif self._dj_brain.should_prepare_break(break_freq, break_var):
            # One track before break time — start pre-generating in the
            # background so the break is ready instantly when needed.
            self._start_break_pregeneration(show_id, queue_length)

        # Queue the next track
        await self._queue_next_track(session)

    async def _use_or_generate_break(
        self,
        session: AsyncSession,
        show_id: int | None,
        queue_length: int,
    ) -> DJBreak | None:
        """Use a pre-generated break if available, otherwise generate one now.

        Args:
            session: Async database session.
            show_id: Active show ID.
            queue_length: Current Liquidsoap queue depth (used to offset
                the context query so the DJ references actually-heard songs).

        Returns:
            A ready DJBreak, or None.
        """
        # Try the pre-generated break first
        if self._pending_break_task is not None:
            if self._pending_break_task.done():
                try:
                    self._pending_break = self._pending_break_task.result()
                except Exception as exc:
                    logger.warning("Pre-generated break failed: %s", exc)
                    self._pending_break = None
                self._pending_break_task = None
            else:
                # Still generating — wait for it (bounded) rather than
                # starting a second generation.
                logger.info("Waiting for pre-generated break to finish...")
                try:
                    self._pending_break = await asyncio.wait_for(
                        self._pending_break_task, timeout=30.0,
                    )
                except (asyncio.TimeoutError, Exception) as exc:
                    logger.warning("Pre-generated break timed out/failed: %s", exc)
                    self._pending_break = None
                self._pending_break_task = None

        if self._pending_break is not None:
            dj_break = self._pending_break
            self._pending_break = None
            # Re-attach to current session so we can commit status changes
            dj_break = await session.merge(dj_break)
            logger.info(
                "Using pre-generated break id=%d (no generation delay)",
                dj_break.id,
            )
            self._dj_brain.reset_break_counter()
            return dj_break

        # Fallback: generate synchronously (old behavior, with offset fix)
        logger.info("No pre-generated break ready, generating synchronously")
        return await self._dj_brain.generate_break(
            session, show_id=show_id, queue_offset=queue_length,
        )

    def _start_break_pregeneration(
        self, show_id: int | None, queue_length: int,
    ) -> None:
        """Kick off background break generation one track early.

        Args:
            show_id: Active show ID.
            queue_length: Current Liquidsoap queue depth for context offset.
        """
        if self._pending_break_task is not None:
            return  # already running

        async def _generate() -> DJBreak | None:
            factory = get_session_factory()
            async with factory() as bg_session:
                return await self._dj_brain.generate_break(
                    bg_session,
                    show_id=show_id,
                    queue_offset=queue_length,
                )

        self._pending_break_task = asyncio.create_task(
            _generate(), name="break_pregen",
        )
        logger.info("Started pre-generating DJ break in background")

    async def _get_active_show(self, session: AsyncSession) -> Show | None:
        """Find the currently active show based on broadcast mode and timers.

        If in manual mode, returns the current_show_id config.
        If in scheduled mode, handles transition timers and returns the current queue block.

        Args:
            session: Async database session.

        Returns:
            The active Show, or None.
        """
        # Get Station config
        result = await session.execute(select(Station).limit(1))
        station = result.scalar_one_or_none()
        if not station:
            return None

        if station.broadcast_mode == "manual":
            if station.current_show_id:
                result = await session.execute(
                    select(Show).where(Show.id == station.current_show_id)
                )
                show = result.scalar_one_or_none()
                if show and show.active:
                    return show
            return None

        # Scheduled mode: timer/queue-based schedule
        current_show = None
        if station.current_show_id:
            result = await session.execute(
                select(Show).where(Show.id == station.current_show_id, Show.active.is_(True))
            )
            current_show = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)
        should_transition = False

        if not current_show or not station.current_show_started_at or getattr(self, "_force_show_reload", False):
            should_transition = True
        else:
            elapsed = (now - station.current_show_started_at.replace(tzinfo=timezone.utc)).total_seconds()
            duration_secs = current_show.duration_minutes * 60
            if elapsed >= duration_secs:
                should_transition = True

        if should_transition:
            self._force_show_reload = False
            # Transition to the next active show in the queue
            result = await session.execute(
                select(Show)
                .where(Show.active.is_(True))
                .order_by(Show.queue_order.asc(), Show.id.asc())
            )
            active_shows = list(result.scalars().all())

            if not active_shows:
                station.current_show_id = None
                station.current_show_started_at = None
                await session.commit()
                return None

            # Find next show in queue
            next_show = active_shows[0]
            if current_show:
                try:
                    current_idx = [s.id for s in active_shows].index(current_show.id)
                    next_idx = (current_idx + 1) % len(active_shows)
                    next_show = active_shows[next_idx]
                except ValueError:
                    pass

            station.current_show_id = next_show.id
            station.current_show_started_at = now
            await session.commit()

            # Emit show transition event
            event_bus.emit("show.started", {
                "show_id": next_show.id,
                "show_name": next_show.name,
                "show_type": next_show.show_type,
            })
            logger.info("Scheduler transitioned to scheduled show: %s", next_show.name)
            return next_show

        return current_show

    async def _get_talk_show_fallback(
        self, session: AsyncSession
    ) -> Show | None:
        """Find a talk show to use when no scheduled show matches.

        When the user starts a talk broadcast but no show is currently
        within its scheduled time window, fall back to the first active
        talk show (or any show with a talk_config_id). This prevents the
        talk engine from silently doing nothing.

        Args:
            session: Async database session.

        Returns:
            A talk-capable Show, or None.
        """
        # First try: active talk show ordered by queue_order
        result = await session.execute(
            select(Show)
            .where(
                Show.active.is_(True),
                Show.show_type.in_(["talk", "hybrid"]),
                Show.talk_config_id.isnot(None),
            )
            .order_by(Show.queue_order.asc(), Show.id.asc())
            .limit(1)
        )
        show = result.scalar_one_or_none()
        if show:
            return show

        # Second try: any show with a talk_config_id
        result = await session.execute(
            select(Show)
            .where(Show.talk_config_id.isnot(None))
            .order_by(Show.queue_order.asc(), Show.id.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _manage_talk_playout(
        self, session: AsyncSession, show: Show
    ) -> None:
        """Manage playout during a talk show.

        Queues talk segments instead of music tracks. No DJ breaks needed
        since the show IS the DJ talking.

        Args:
            session: Async database session.
            show: The active talk show.
        """
        queue_length = await self._playout.get_queue_length()

        if queue_length > 1:
            return

        await self._queue_next_talk_segment(
            session, show, fallback_to_dead_air=True
        )

    async def _manage_hybrid_playout(
        self, session: AsyncSession, show: Show
    ) -> None:
        """Manage playout during a hybrid music/talk show.

        Hybrid shows alternate between music and talk when talk segments are
        ready. If no talk segment is ready, music continues so the stream does
        not go silent while generation catches up.

        Args:
            session: Async database session.
            show: The active hybrid show.
        """
        queue_length = await self._playout.get_queue_length()

        if queue_length > 1:
            return

        result = await session.execute(
            select(PlayLog.item_type)
            .order_by(PlayLog.started_at.desc(), PlayLog.id.desc())
            .limit(1)
        )
        last_item_type = result.scalar_one_or_none()

        if last_item_type == "track":
            queued_talk = await self._queue_next_talk_segment(
                session, show, fallback_to_dead_air=False
            )
            if queued_talk:
                return

        await self._manage_playout(session)

    async def _queue_next_talk_segment(
        self,
        session: AsyncSession,
        show: Show,
        fallback_to_dead_air: bool,
    ) -> bool:
        """Queue the next ready talk segment.

        Args:
            session: Async database session.
            show: The active talk-capable show.
            fallback_to_dead_air: Whether to queue fallback audio when no talk
                segment is ready.

        Returns:
            True if a talk segment was queued, False otherwise.
        """
        segment = await self._talk_engine.get_next_segment(session, show.id)

        if segment is None:
            # No segments ready — try fallback
            if fallback_to_dead_air:
                await self._handle_dead_air()
            return False

        if not segment.audio_filepath or not Path(segment.audio_filepath).exists():
            logger.warning(
                "Talk segment %d file missing: %s",
                segment.id,
                segment.audio_filepath,
            )
            segment.status = "failed"
            await session.commit()
            await self._record_timeline_update(
                lambda timeline_session: mark_source_failed(
                    timeline_session,
                    "talk_segments",
                    segment.id,
                )
            )
            return False

        queued = await self._playout.queue_track(segment.audio_filepath)
        if queued:
            prev_result = await session.execute(
                select(TalkSegment).where(TalkSegment.status == "playing")
            )
            previous_segments = list(prev_result.scalars().all())
            for prev_segment in previous_segments:
                prev_segment.status = "played"
                event_bus.emit(
                    "talk_segment.ended",
                    {"segment_id": prev_segment.id},
                )

            segment.status = "playing"
            segment.played_at = datetime.now(timezone.utc)
            await session.commit()

            for prev_segment in previous_segments:
                await self._record_timeline_update(
                    lambda timeline_session, prev_segment_id=prev_segment.id: mark_source_played(
                        timeline_session,
                        "talk_segments",
                        prev_segment_id,
                    )
                )
            await self._record_timeline_update(
                lambda timeline_session: mark_source_playing(
                    timeline_session,
                    "talk_segments",
                    segment.id,
                )
            )

            await self._playout.update_metadata(
                title=f"{show.name} - Talk Segment",
                artist=show.name,
            )

            await self._log_play(
                session,
                "talk_segment",
                segment.id,
                segment.duration,
                {
                    "show": show.name,
                    "type": segment.segment_type,
                },
            )

            event_bus.emit("talk_segment.started", {
                "segment_id": segment.id,
                "show_id": show.id,
                "type": segment.segment_type,
                "duration": segment.duration,
            })
            return True

        return False

    async def _update_announcement_plays(
        self, session: AsyncSession, context_json: str
    ) -> None:
        """Increment play counts for announcements used in a break.

        Args:
            session: Async database session.
            context_json: JSON string of the break context.
        """
        try:
            ctx = json.loads(context_json)
            ann_ids = [
                a["id"]
                for a in ctx.get("announcements", [])
                if "id" in a
            ]
            if ann_ids:
                await self._dj_brain.increment_announcement_plays(
                    session, ann_ids
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    async def _record_timeline_update(
        self,
        operation: Callable[[AsyncSession], Awaitable[object]],
    ) -> None:
        """Record a non-critical timeline update without blocking playout."""
        try:
            factory = get_session_factory()
            async with factory() as timeline_session:
                await operation(timeline_session)
                await timeline_session.commit()
        except Exception as exc:
            logger.warning("Timeline state update failed: %s", exc)

    async def _queue_next_track(self, session: AsyncSession) -> None:
        """Select and queue the next ready track for playout.

        Args:
            session: Async database session.
        """
        result = await session.execute(
            select(Track)
            .where(Track.status == "ready")
            .order_by(Track.created_at.asc())
            .limit(1)
        )
        track = result.scalar_one_or_none()

        if track is None:
            await self._handle_dead_air()
            return

        if not track.filepath or not Path(track.filepath).exists():
            logger.warning(
                "Track %d file missing: %s", track.id, track.filepath
            )
            track.status = "failed"
            await session.commit()
            track_id = track.id
            await self._record_timeline_update(
                lambda timeline_session: mark_source_failed(
                    timeline_session,
                    "tracks",
                    track_id,
                ),
            )
            return

        queued = await self._playout.queue_track(track.filepath)
        if queued:
            # Mark any previously-playing tracks as played
            prev_result = await session.execute(
                select(Track).where(Track.status == "playing")
            )
            previous_tracks = list(prev_result.scalars().all())
            for prev_track in previous_tracks:
                prev_track.status = "played"
                event_bus.emit(
                    "track.ended",
                    {"track_id": prev_track.id, "title": prev_track.title},
                )

            track.status = "playing"
            track.played_at = datetime.now(timezone.utc)
            await session.commit()

            for prev_track in previous_tracks:
                prev_track_id = prev_track.id
                await self._record_timeline_update(
                    lambda timeline_session: mark_source_played(
                        timeline_session,
                        "tracks",
                        prev_track_id,
                    ),
                )
            track_id = track.id
            await self._record_timeline_update(
                lambda timeline_session: mark_source_playing(
                    timeline_session,
                    "tracks",
                    track_id,
                ),
            )

            # Update stream metadata (show-aware)
            active_show = await self._get_active_show(session)
            cfg = await get_effective_dj_config(
                session, show_id=active_show.id if active_show else None
            )
            await self._playout.update_metadata(
                title=track.title or "Unknown Track",
                artist=cfg.station_name if cfg else "AI Radio",
            )

            self._dj_brain.track_played()

            await self._log_play(
                session,
                "track",
                track.id,
                track.duration,
                {
                    "title": track.title,
                    "style_prompt": track.style_prompt,
                },
            )

            event_bus.emit(
                "track.started",
                {
                    "track_id": track.id,
                    "title": track.title,
                    "duration": track.duration,
                    "style": track.style_prompt,
                    "lyrics": track.lyrics or "",
                    "started_at": track.played_at.isoformat()
                    if track.played_at
                    else None,
                },
            )

    async def _handle_dead_air(self) -> None:
        """Activate fallback audio when no tracks are available."""
        event_bus.emit("buffer.critical", {"ready": 0, "target": 0})

        if not self._fallback_dir.exists():
            logger.error(
                "DEAD AIR: No fallback directory at %s", self._fallback_dir
            )
            return

        fallback_files = list(self._fallback_dir.glob("*.mp3")) + list(
            self._fallback_dir.glob("*.wav")
        )

        if not fallback_files:
            logger.error("DEAD AIR: No fallback audio files found")
            return

        fallback = random.choice(fallback_files)
        logger.warning(
            "Dead air protection: queueing fallback %s", fallback.name
        )
        await self._playout.queue_track(str(fallback))

    async def _log_play(
        self,
        session: AsyncSession,
        item_type: str,
        item_id: int,
        duration: float | None,
        metadata: dict | None = None,
    ) -> None:
        """Record a played item in the play log.

        Args:
            session: Async database session.
            item_type: 'track' or 'dj_break'.
            item_id: ID of the played item.
            duration: Duration in seconds.
            metadata: Optional metadata dict.
        """
        log = PlayLog(
            item_type=item_type,
            item_id=item_id,
            duration=duration,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        session.add(log)
        await session.commit()

    async def _run_cleanup(self, session: AsyncSession) -> None:
        """Archive played tracks and purge old files past retention.

        Args:
            session: Async database session.
        """
        # Get retention config
        result = await session.execute(select(Station).limit(1))
        station = result.scalar_one_or_none()
        retention_days = station.disk_retention_days if station else 30

        archive_dir = Path(settings.AUDIO_DIR) / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        # Move played tracks to archive
        result = await session.execute(
            select(Track).where(Track.status == "played")
        )
        archived_count = 0
        for track in result.scalars().all():
            if track.filepath and Path(track.filepath).exists():
                dest = archive_dir / Path(track.filepath).name
                try:
                    shutil.move(track.filepath, str(dest))
                    track.filepath = str(dest)
                    track.status = "archived"
                    archived_count += 1
                except OSError as exc:
                    logger.warning(
                        "Failed to archive track %d: %s", track.id, exc
                    )

        if archived_count:
            logger.info("Archived %d played tracks", archived_count)

        await session.commit()

        # Purge files older than retention
        cutoff = datetime.now(timezone.utc).timestamp() - (
            retention_days * 86400
        )
        purged = 0
        for f in archive_dir.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    purged += 1
                except OSError:
                    pass

        if purged:
            logger.info(
                "Purged %d archived files older than %d days",
                purged,
                retention_days,
            )

        # Mark stale "playing" tracks as "played" (>15 min)
        result = await session.execute(
            select(Track).where(Track.status == "playing")
        )
        now = datetime.now(timezone.utc)
        stale_count = 0
        for track in result.scalars().all():
            if track.played_at:
                # SQLite returns naive UTC datetimes after a round-trip, but
                # same-session objects may still hold aware values.
                played_at = track.played_at
                if played_at.tzinfo is None:
                    played_at = played_at.replace(tzinfo=timezone.utc)
                elapsed = (now - played_at).total_seconds()
                if elapsed > 900:
                    track.status = "played"
                    stale_count += 1

        if stale_count:
            logger.info(
                "Marked %d stale playing tracks as played", stale_count
            )

        # Clean up failed tracks (remove DB records for tracks with no file)
        result = await session.execute(
            select(Track).where(Track.status == "failed")
        )
        for track in result.scalars().all():
            if track.filepath and Path(track.filepath).exists():
                try:
                    Path(track.filepath).unlink()
                except OSError:
                    pass

        await session.commit()

        # Clean up old recordings past retention
        await self._cleanup_recordings(session)

    async def _cleanup_recordings(self, session: AsyncSession) -> None:
        """Delete recording files older than the configured retention period.

        Args:
            session: Async database session.
        """
        result = await session.execute(select(Station).limit(1))
        station = result.scalar_one_or_none()
        retention_days = station.recording_retention_days if station else 7

        recordings_dir = Path(settings.AUDIO_DIR) / "recordings"
        if not recordings_dir.exists():
            return

        cutoff = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
        purged = 0
        for f in recordings_dir.iterdir():
            if f.is_file() and f.suffix in (".mp3", ".wav", ".ogg"):
                if f.stat().st_mtime < cutoff:
                    try:
                        f.unlink()
                        purged += 1
                    except OSError:
                        pass

        if purged:
            logger.info(
                "Purged %d recording files older than %d days",
                purged,
                retention_days,
            )

    async def _check_disk_space(self) -> None:
        """Check available disk space and warn if low."""
        try:
            audio_path = Path(settings.AUDIO_DIR)
            if not audio_path.exists():
                return

            import shutil as sh

            total, used, free = sh.disk_usage(str(audio_path))
            free_gb = free / (1024**3)
            usage_pct = (used / total) * 100

            if free_gb < 1.0:
                logger.critical(
                    "DISK SPACE CRITICAL: %.2f GB free (%.1f%% used)",
                    free_gb,
                    usage_pct,
                )
                event_bus.emit(
                    "system.disk_critical",
                    {"free_gb": free_gb, "usage_pct": usage_pct},
                )
            elif free_gb < 5.0:
                logger.warning(
                    "Disk space low: %.2f GB free (%.1f%% used)",
                    free_gb,
                    usage_pct,
                )
                event_bus.emit(
                    "system.disk_warning",
                    {"free_gb": free_gb, "usage_pct": usage_pct},
                )
            else:
                logger.debug(
                    "Disk space OK: %.2f GB free (%.1f%% used)",
                    free_gb,
                    usage_pct,
                )
        except Exception as exc:
            logger.debug("Disk space check failed: %s", exc)
