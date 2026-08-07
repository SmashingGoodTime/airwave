"""Master scheduler coordinating music generation, DJ breaks, and playout.

The main orchestration loop that ties together buffer management, DJ brain,
playout interface, disk cleanup, and dead air protection. Show-aware: the
active show block scopes style selection and the DJ persona.
"""

import asyncio
import json
import logging
import random
import shutil
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.config import settings
from server.database import get_session_factory
from server.engine.audio_pipeline import AudioPipeline
from server.engine.dj_brain import DJBrain
from server.engine.music_buffer import MusicBufferManager
from server.engine.playout import PlayoutInterface
from server.engine.timeline_state import (
    mark_source_failed,
    mark_source_played,
    mark_source_playing,
)
from server.events.emitter import event_bus
from server.engine.dj_brain import get_effective_dj_config
from server.models.dj_break import DJBreak
from server.models.dj_config import DJConfig
from server.models.generation_job import GenerationJob
from server.models.playlog import PlayLog
from server.models.show import Show
from server.models.station import Station, get_station
from server.models.track import Track
from server.utils.timeutils import to_utc_iso, utcnow_naive

logger = logging.getLogger(__name__)

# How often each loop runs (seconds)
BUFFER_CHECK_INTERVAL = 30
PLAYOUT_CHECK_INTERVAL = 5
CLEANUP_INTERVAL = 3600  # 1 hour
HEALTH_CHECK_INTERVAL = 300  # 5 minutes
SHOW_CHECK_INTERVAL = 30  # Check for show transitions

# Rows stuck in a transient generation state longer than this are reaped
STUCK_GENERATION_MAX_AGE = timedelta(hours=2)

# Failed track rows older than this are deleted (the generation_jobs table
# keeps the failure history); finished jobs older than JOB_RETENTION go too.
FAILED_TRACK_RETENTION = timedelta(days=1)
JOB_RETENTION = timedelta(days=7)


class MasterScheduler:
    """Orchestrates the timing of music generation, DJ breaks, and playout.

    Runs as async background tasks on app startup. Show-aware: the active
    show block scopes which styles the buffer draws from and which DJ
    persona speaks. When no show is scheduled the station keeps playing
    with the station-default configuration.
    """

    def __init__(self) -> None:
        self._buffer_manager = MusicBufferManager()
        self._dj_brain = DJBrain()
        self._playout = PlayoutInterface(
            host=settings.LIQUIDSOAP_HOST,
            port=settings.LIQUIDSOAP_PORT,
        )
        self._running = False
        self._streaming = False
        self._tasks: list[asyncio.Task] = []
        self._fallback_dir = Path(settings.AUDIO_DIR) / "fallback"
        self._consecutive_playout_errors = 0
        self._consecutive_buffer_errors = 0
        self._current_show_id: int | None = None
        self._force_show_reload = False
        # Pre-generated DJ break ready for immediate queueing
        self._pending_break: DJBreak | None = None
        self._pending_break_task: asyncio.Task | None = None
        # True while a startup/show-transition intro is being generated —
        # the playout loop must not queue anything ahead of the intro.
        self._intro_pending = False
        # Single writer for show transitions (see _show_transition_step)
        self._show_lock = asyncio.Lock()
        # Air-time reconciliation (see _reconcile_now_playing): the file path
        # Liquidsoap last reported on air, and the PlayLog row opened for it
        # (so its ended_at can be set when the next item takes over). These
        # make now-playing/playlog reflect what is ACTUALLY airing rather than
        # what was last pushed to the queue a track ahead.
        self._on_air_path: str | None = None
        self._on_air_playlog_id: int | None = None
        # True while the queue is being fed from fallback audio. Used to
        # edge-trigger buffer.critical instead of emitting on every tick.
        self._dead_air_active = False

    async def start(self) -> None:
        """Start all scheduler loops as background tasks."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        logger.info("Starting master scheduler...")

        # Ensure audio directories exist
        for subdir in [
            "tracks", "breaks", "fallback", "fallback/normalized", "archive",
            "calls", "calls/raw", "calls/processed",
            "recordings",
        ]:
            (Path(settings.AUDIO_DIR) / subdir).mkdir(
                parents=True, exist_ok=True
            )

        # NOTE: No auto-start of streaming — user must click Start in the UI.
        # _queue_startup_intro() is called from start_streaming() instead.

        self._tasks = [
            # One-shot startup tasks (must not block scheduler start)
            asyncio.create_task(
                self._restore_recording_state(),
                name="restore_recording_state",
            ),
            asyncio.create_task(
                self._normalize_fallback_files(),
                name="normalize_fallback",
            ),
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

    async def start_streaming(self) -> None:
        """Start streaming. Resolves the active show block on startup."""
        if self._streaming:
            logger.warning("Streaming already active")
            return

        # Resolve the active show block
        factory = get_session_factory()
        async with factory() as session:
            active_show = await self._get_active_show(session)

        self._current_show_id = active_show.id if active_show else None
        # Block the playout loop from queueing anything until the startup
        # intro is queued (or intro generation fails/is skipped). Set
        # BEFORE _streaming so no playout tick can slip in between.
        self._intro_pending = True
        self._streaming = True
        logger.info(
            "Streaming started (show=%s)",
            active_show.name if active_show else "(none)",
        )

        try:
            # Wait for Liquidsoap telnet to be ready before queueing anything
            ready = await self._playout.wait_until_ready(
                timeout=30.0, interval=1.0
            )
            if not ready:
                logger.warning(
                    "Liquidsoap not ready after timeout — will retry queueing "
                    "in the next scheduler tick"
                )

            # Generate and queue a startup intro
            await self._queue_startup_intro()
        finally:
            self._intro_pending = False

        event_bus.emit("stream.started", {"show_id": self._current_show_id})

    async def stop_streaming(self) -> None:
        """Stop streaming. The scheduler keeps running but stops generating and playing content."""
        if not self._streaming:
            logger.warning("Streaming not active")
            return

        self._streaming = False
        show_id = self._current_show_id
        self._current_show_id = None

        # Drop any pre-generated break: its context (recent tracks, time of
        # day) would be stale by the time streaming restarts.
        if self._pending_break_task is not None:
            self._pending_break_task.cancel()
            self._pending_break_task = None
        self._pending_break = None

        # Close the open playlog row and clear reconciler state — with the
        # playout loop stopped, nothing else would ever stamp its ended_at.
        if self._on_air_playlog_id is not None:
            try:
                factory = get_session_factory()
                async with factory() as session:
                    playlog = await session.get(PlayLog, self._on_air_playlog_id)
                    if playlog is not None and playlog.ended_at is None:
                        playlog.ended_at = utcnow_naive()
                        await session.commit()
            except Exception as exc:
                logger.warning("Could not close on-air playlog on stop: %s", exc)
        self._on_air_playlog_id = None
        self._on_air_path = None
        self._dead_air_active = False

        logger.info("Streaming stopped")

        event_bus.emit("stream.stopped", {"show_id": show_id})

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
        """Sync the Liquidsoap recorder with the configured recording state.

        Starts the recorder when recording is enabled in config, and stops
        it when disabled (so a Liquidsoap restart with stale state is
        brought back in line). Waits for Liquidsoap to accept commands
        first — this runs as a background task so it never blocks startup.
        """
        try:
            factory = get_session_factory()
            async with factory() as session:
                station = await get_station(session)
            if station is None:
                return

            ready = await self._playout.wait_until_ready(
                timeout=30.0, interval=1.0
            )
            if not ready:
                logger.warning(
                    "Liquidsoap not ready — could not sync recording state"
                )
                return

            if station.recording_enabled:
                started = await self._playout.start_recording()
                if started:
                    logger.info("Recording auto-started (was enabled in config)")
                else:
                    logger.warning("Failed to auto-start recording")
            else:
                await self._playout.stop_recording()
                logger.info("Recorder confirmed stopped (disabled in config)")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Could not restore recording state: %s", exc)

    async def _normalize_fallback_files(self) -> None:
        """Normalize fallback audio into a cache directory (best-effort).

        Fallback files are user-supplied and may not meet the station's
        loudness/format standards. This one-shot startup task processes
        them into ``fallback/normalized/`` so dead-air playback uses
        broadcast-ready audio. Files that fail to process are skipped;
        startup is never blocked on this.
        """
        try:
            if not self._fallback_dir.exists():
                return
            normalized_dir = self._fallback_dir / "normalized"
            normalized_dir.mkdir(parents=True, exist_ok=True)

            pipeline = AudioPipeline()
            fallback_files = list(self._fallback_dir.glob("*.mp3")) + list(
                self._fallback_dir.glob("*.wav")
            )
            for source in fallback_files:
                target = normalized_dir / f"{source.stem}.wav"
                if target.exists():
                    continue
                try:
                    processed = await pipeline.process(str(source))
                    await asyncio.to_thread(
                        shutil.move, processed["processed_path"], str(target)
                    )
                    logger.info(
                        "Normalized fallback file: %s -> %s",
                        source.name,
                        target,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Could not normalize fallback file %s: %s",
                        source.name,
                        exc,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Fallback normalization task failed: %s", exc)

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
                    intro_title = (
                        f"Show Intro — {active_show.name}"
                        if active_show
                        else "Show Intro"
                    )
                    queued = await self._playout.queue_break(
                        dj_break.audio_filepath, title=intro_title
                    )
                    if queued:
                        self._dj_brain.reset_break_counter()
                        dj_break.status = "queued"
                        await session.commit()
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
        """Check buffer depth and generate tracks for the active show.

        Tracks are prefilled even while idle (not streaming) so music is
        ready the moment streaming starts.

        Args:
            session: Async database session.
        """
        # Determine active show for style/DJ filtering
        active_show = await self._get_active_show(session)
        show_id = active_show.id if active_show else None

        await self._buffer_manager.check_and_fill(session, show_id=show_id)

    async def _playout_step(self, session: AsyncSession) -> None:
        """Monitor playout state and queue the next item.

        Args:
            session: Async database session.
        """
        if not self._streaming:
            return

        # Reconcile now-playing/playlog against what is ACTUALLY on air on
        # every tick while streaming (independent of queueing decisions).
        await self._reconcile_now_playing(session)

        if self._intro_pending:
            # While an intro is being generated/queued, nothing may be
            # queued ahead of it.
            return

        await self._manage_playout(session)

    async def _show_transition_step(self, session: AsyncSession) -> None:
        """Detect show transitions, persist them, and emit events.

        This is the ONLY place that writes show-transition state
        (``station.current_show_id`` / ``current_show_started_at``) and
        emits ``show.ended``/``show.started`` — other callers of
        :meth:`_get_active_show` are read-only, so each boundary produces
        exactly one pair of events.

        Args:
            session: Async database session.
        """
        if not self._streaming:
            return

        async with self._show_lock:
            await self._show_transition_locked(session)

    async def _show_transition_locked(self, session: AsyncSession) -> None:
        """Perform the show transition while holding the show lock.

        Args:
            session: Async database session.
        """
        active_show = await self._get_active_show(session)
        await self._persist_show_transition(session, active_show)
        new_show_id = active_show.id if active_show else None

        if new_show_id != self._current_show_id:
            # Show transition detected
            if self._current_show_id is not None:
                event_bus.emit("show.ended", {"show_id": self._current_show_id})
                logger.info("Show ended: id=%s", self._current_show_id)

            if new_show_id is not None:
                event_bus.emit("show.started", {
                    "show_id": active_show.id,
                    "show_name": active_show.name,
                })

                logger.info("Show started: '%s'", active_show.name)

                # Generate and queue a DJ intro for the new show. The
                # playout loop is held off so no track can jump ahead of
                # the transition intro.
                self._intro_pending = True
                try:
                    intro = await self._dj_brain.generate_show_intro(
                        session, show=active_show, show_id=active_show.id
                    )
                    if intro and intro.audio_filepath:
                        queued = await self._playout.queue_break(
                            intro.audio_filepath,
                            title=f"Show Intro — {active_show.name}",
                        )
                        if queued:
                            self._dj_brain.reset_break_counter()
                            intro.status = "queued"
                            await session.commit()
                            logger.info(
                                "Show intro queued for '%s'", active_show.name
                            )
                except Exception as exc:
                    logger.warning(
                        "Failed to generate show intro for '%s': %s",
                        active_show.name,
                        exc,
                    )
                finally:
                    self._intro_pending = False

            self._current_show_id = new_show_id

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
                dj_break = await self._use_or_generate_break(session, show_id)
                if dj_break and dj_break.audio_filepath:
                    break_title = (
                        f"{dj_config.dj_name} — DJ Break"
                        if dj_config and dj_config.dj_name
                        else "DJ Break"
                    )
                    queued = await self._playout.queue_break(
                        dj_break.audio_filepath, title=break_title
                    )
                    if queued:
                        # The break counter resets ONLY here, after the break
                        # has actually been pushed to playout. Status/playlog/
                        # events are handled at air time by the reconciler.
                        self._dj_brain.reset_break_counter()
                        dj_break.status = "queued"
                        await session.commit()
                        return
                    # Queue push failed — keep the break for the next tick
                    # instead of silently dropping it.
                    logger.warning(
                        "Failed to queue DJ break %d — retrying next tick",
                        dj_break.id,
                    )
                    self._pending_break = dj_break
            except Exception as exc:
                logger.error("DJ break generation/queueing failed: %s", exc)
                # Don't let break failure prevent track queueing

        elif self._dj_brain.should_prepare_break(break_freq, break_var):
            # One track before break time — start pre-generating in the
            # background so the break is ready instantly when needed.
            self._start_break_pregeneration(show_id)

        # Queue the next track
        await self._queue_next_track(session)

    async def _use_or_generate_break(
        self,
        session: AsyncSession,
        show_id: int | None,
    ) -> DJBreak | None:
        """Use a pre-generated break if available, otherwise generate one now.

        Args:
            session: Async database session.
            show_id: Active show ID.

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
            return dj_break

        # Fallback: generate synchronously (old behavior)
        logger.info("No pre-generated break ready, generating synchronously")
        return await self._dj_brain.generate_break(session, show_id=show_id)

    def _start_break_pregeneration(self, show_id: int | None) -> None:
        """Kick off background break generation one track early.

        Args:
            show_id: Active show ID.
        """
        if self._pending_break_task is not None:
            return  # already running

        async def _generate() -> DJBreak | None:
            factory = get_session_factory()
            async with factory() as bg_session:
                return await self._dj_brain.generate_break(
                    bg_session, show_id=show_id
                )

        self._pending_break_task = asyncio.create_task(
            _generate(), name="break_pregen",
        )
        logger.info("Started pre-generating DJ break in background")

    async def _get_active_show(self, session: AsyncSession) -> Show | None:
        """Find the currently active show based on broadcast mode and timers.

        Read-only: never writes station state or emits events, so it is
        safe to call concurrently from the buffer/playout loops. In
        scheduled mode, when the current show's timer has lapsed this
        computes the *next* show in the queue without persisting the
        rotation — only :meth:`_show_transition_step` (the single writer)
        commits transitions. A pending force-reload instead re-reads the
        persisted show selection as-is (restarting its timer) rather than
        advancing the rotation.

        Args:
            session: Async database session.

        Returns:
            The active Show, or None.
        """
        # Get Station config
        station = await get_station(session)
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

        if current_show and self._force_show_reload:
            # A forced reload re-reads the persisted selection (e.g.
            # /streaming/switch just wrote the requested show) and restarts
            # its timer via _persist_show_transition. It must NOT advance
            # the rotation — that would land one show past the one the
            # operator explicitly picked.
            return current_show

        if current_show and not self._show_timer_expired(station, current_show):
            return current_show

        # A transition is due — compute (do not persist) the next show
        result = await session.execute(
            select(Show)
            .where(Show.active.is_(True))
            .order_by(Show.queue_order.asc(), Show.id.asc())
        )
        active_shows = list(result.scalars().all())

        if not active_shows:
            return None

        next_show = active_shows[0]
        if current_show:
            try:
                current_idx = [s.id for s in active_shows].index(current_show.id)
                next_idx = (current_idx + 1) % len(active_shows)
                next_show = active_shows[next_idx]
            except ValueError:
                pass

        return next_show

    @staticmethod
    def _show_timer_expired(station: Station, current_show: Show) -> bool:
        """Check whether the scheduled show's playtime window has lapsed.

        Args:
            station: The station row holding the show timer.
            current_show: The currently scheduled show.

        Returns:
            True if the show has run past its duration (or has no start
            timestamp at all).
        """
        started_at = station.current_show_started_at
        if not started_at:
            return True
        # SQLite round-trips naive UTC; same-session objects may be aware
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        return elapsed >= current_show.duration_minutes * 60

    async def _persist_show_transition(
        self, session: AsyncSession, active_show: Show | None
    ) -> None:
        """Persist a scheduled-mode show rotation (single writer).

        Called only from :meth:`_show_transition_step` while holding the
        show lock. Updates ``station.current_show_id`` and restarts the
        show timer when a transition is due.

        Args:
            session: Async database session.
            active_show: The show computed by :meth:`_get_active_show`.
        """
        station = await get_station(session)
        if not station or station.broadcast_mode != "scheduled":
            self._force_show_reload = False
            return

        new_id = active_show.id if active_show else None
        restamp = False
        if station.current_show_id != new_id or self._force_show_reload:
            restamp = True
        elif active_show is not None:
            # Same show rotating onto itself (single-show queue) — restart
            # the timer once it lapses.
            restamp = self._show_timer_expired(station, active_show)

        if restamp:
            station.current_show_id = new_id
            station.current_show_started_at = (
                utcnow_naive() if new_id is not None else None
            )
            await session.commit()
            logger.info(
                "Scheduler transitioned to scheduled show: %s",
                active_show.name if active_show else "(none)",
            )
        self._force_show_reload = False

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
            await self._handle_dead_air(session)
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

        # Resolve stream metadata (show-aware) before queueing — metadata
        # is annotated into the Liquidsoap request at queue time.
        active_show = await self._get_active_show(session)
        cfg = await get_effective_dj_config(
            session, show_id=active_show.id if active_show else None
        )
        queued = await self._playout.queue_track(
            track.filepath,
            title=track.title or "Unknown Track",
            artist=cfg.station_name if cfg else "AI Radio",
        )
        if queued:
            # Mark the track as queued (not playing): the air-time reconciler
            # flips it to "playing", writes the playlog, and emits
            # track.started when Liquidsoap actually starts it. track_played()
            # advances the break-pacing counter at queue time so breaks are
            # still spaced by queue order.
            track.status = "queued"
            track.queued_at = utcnow_naive()
            await session.commit()
            self._dj_brain.track_played()
            self._dead_air_active = False

    def _pick_fallback_file(self) -> Path | None:
        """Choose a fallback file, preferring the normalized cache.

        Files are keyed by stem so a normalized copy (built by
        :meth:`_normalize_fallback_files` into ``fallback/normalized/``)
        replaces its raw original, while raw files not yet normalized
        (e.g. dropped in after startup) remain eligible.

        Returns:
            A fallback audio file path, or None if none exist.
        """
        candidates: dict[str, Path] = {}
        for pattern in ("*.mp3", "*.wav"):
            for raw in self._fallback_dir.glob(pattern):
                candidates[raw.stem] = raw
        normalized_dir = self._fallback_dir / "normalized"
        if normalized_dir.exists():
            for pattern in ("*.mp3", "*.wav"):
                for norm in normalized_dir.glob(pattern):
                    candidates[norm.stem] = norm
        if not candidates:
            return None
        return random.choice(list(candidates.values()))

    async def _handle_dead_air(self, session: AsyncSession) -> None:
        """Activate fallback audio when no tracks are available.

        Args:
            session: Async database session (retained for signature stability;
                fallback airtime is logged by the reconciler).
        """
        # Edge-trigger: emit once when dead air starts, not on every 5s tick.
        # The flag is cleared when a real track is queued again.
        if not self._dead_air_active:
            self._dead_air_active = True
            event_bus.emit("buffer.critical", {"ready": 0, "target": 0})

        if not self._fallback_dir.exists():
            logger.error(
                "DEAD AIR: No fallback directory at %s", self._fallback_dir
            )
            return

        fallback = self._pick_fallback_file()

        if fallback is None:
            logger.error("DEAD AIR: No fallback audio files found")
            return
        logger.warning(
            "Dead air protection: queueing fallback %s", fallback.name
        )
        # Fallback airtime is logged for compliance by the reconciler when the
        # file actually reaches air (it recognises /audio/fallback/ paths),
        # which also covers Liquidsoap's own fallback playlist.
        await self._playout.queue_track(
            str(fallback), title=fallback.stem, artist="AI Radio (fallback)"
        )

    async def _map_on_air_path(
        self, session: AsyncSession, path: str
    ) -> tuple[str, object | None]:
        """Map an on-air file path to its source row.

        Matches on the (unique) file basename so a relative DB path resolves
        against the absolute container path Liquidsoap reports.

        Args:
            session: Async database session.
            path: The on-air file path from Liquidsoap.

        Returns:
            (kind, row) where kind is 'track', 'dj_break', 'fallback', or
            'unknown'; row is the ORM object or None.
        """
        suffix = f"%{Path(path).name}"

        track = (
            await session.execute(
                select(Track).where(Track.filepath.like(suffix))
            )
        ).scalars().first()
        if track is not None:
            return ("track", track)

        dj_break = (
            await session.execute(
                select(DJBreak).where(DJBreak.audio_filepath.like(suffix))
            )
        ).scalars().first()
        if dj_break is not None:
            return ("dj_break", dj_break)

        if Path(path).parent.name == "fallback" or "/fallback/" in path:
            return ("fallback", None)
        return ("unknown", None)

    async def _reconcile_now_playing(self, session: AsyncSession) -> None:
        """Align now-playing/playlog state with what is ACTUALLY on air.

        Polls Liquidsoap for the file currently airing (captured pre-crossfade
        in station.liq). On a change, the previously-airing item is closed
        (marked played, playlog ``ended_at`` stamped) and the newly-airing
        item is opened (marked playing, playlog written with an accurate
        ``started_at``, ``*.started`` emitted). This decouples air-time state
        from queue time, which runs a track ahead.

        Args:
            session: Async database session.
        """
        current = await self._playout.get_now_playing_file()
        if current is None or current == self._on_air_path:
            return

        now = utcnow_naive()
        previous = self._on_air_path
        self._on_air_path = current

        if previous is not None:
            await self._close_on_air(session, previous, now)
        await self._open_on_air(session, current, now)
        await session.commit()

    async def _open_on_air(
        self, session: AsyncSession, path: str, now: datetime
    ) -> None:
        """Mark the newly-airing item playing and log its air-time start."""
        kind, row = await self._map_on_air_path(session, path)
        self._on_air_playlog_id = None

        if kind == "fallback":
            log = await self._log_play(
                session, "fallback", 0, None, {"filename": Path(path).name}
            )
            self._on_air_playlog_id = log.id
            return

        if row is None or getattr(row, "status", None) == "playing":
            # Unknown file, or already opened (e.g. after an app restart) —
            # don't double-log or re-emit.
            return

        row.status = "playing"
        row.played_at = now
        row_id = row.id

        if kind == "track":
            await self._record_timeline_update(
                lambda ts: mark_source_playing(ts, "tracks", row_id)
            )
            log = await self._log_play(
                session, "track", row.id, row.duration,
                {"title": row.title, "style_prompt": row.style_prompt},
            )
            self._on_air_playlog_id = log.id
            event_bus.emit(
                "track.started",
                {
                    "track_id": row.id,
                    "title": row.title,
                    "duration": row.duration,
                    "style": row.style_prompt,
                    "lyrics": row.lyrics or "",
                    "started_at": to_utc_iso(now),
                },
            )
        elif kind == "dj_break":
            await self._record_timeline_update(
                lambda ts: mark_source_playing(ts, "dj_breaks", row_id)
            )
            log = await self._log_play(
                session, "dj_break", row.id, row.duration, None
            )
            self._on_air_playlog_id = log.id
            if row.context:
                await self._update_announcement_plays(session, row.context)
            event_bus.emit(
                "break.started",
                {
                    "break_id": row.id,
                    "script_text": row.script_text or "",
                    "duration": row.duration or 0,
                },
            )

    async def _close_on_air(
        self, session: AsyncSession, path: str, now: datetime
    ) -> None:
        """Mark the item that just left air as played and stamp ended_at."""
        if self._on_air_playlog_id is not None:
            playlog = await session.get(PlayLog, self._on_air_playlog_id)
            if playlog is not None and playlog.ended_at is None:
                playlog.ended_at = now
            self._on_air_playlog_id = None

        kind, row = await self._map_on_air_path(session, path)
        if row is None or getattr(row, "status", None) != "playing":
            return

        row.status = "played"
        row_id = row.id
        if kind == "track":
            await self._record_timeline_update(
                lambda ts: mark_source_played(ts, "tracks", row_id)
            )
            event_bus.emit(
                "track.ended", {"track_id": row.id, "title": row.title}
            )
        elif kind == "dj_break":
            await self._record_timeline_update(
                lambda ts: mark_source_played(ts, "dj_breaks", row_id)
            )
            event_bus.emit("break.ended", {"break_id": row.id})

    async def _log_play(
        self,
        session: AsyncSession,
        item_type: str,
        item_id: int,
        duration: float | None,
        metadata: dict | None = None,
    ) -> PlayLog:
        """Record a played item in the play log.

        ``started_at`` defaults to now, so callers should invoke this when the
        item actually goes on air (see :meth:`_reconcile_now_playing`).

        Args:
            session: Async database session.
            item_type: 'track', 'dj_break', or 'fallback'.
            item_id: ID of the played item (0 for fallback).
            duration: Nominal duration in seconds.
            metadata: Optional metadata dict.

        Returns:
            The created PlayLog row (flushed so ``id`` is populated).
        """
        log = PlayLog(
            item_type=item_type,
            item_id=item_id,
            duration=duration,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
        session.add(log)
        await session.flush()
        return log

    async def _run_cleanup(self, session: AsyncSession) -> None:
        """Archive played tracks and purge old files past retention.

        Args:
            session: Async database session.
        """
        # Get retention config
        station = await get_station(session)
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

        # Reset tracks stuck in "queued" back to "ready": the app pushed them
        # to Liquidsoap but they never reached air — e.g. the Liquidsoap
        # container restarted and dropped its request queue. Keyed on
        # queued_at (stamped at push time), NOT created_at: prefilled tracks
        # can be arbitrarily old when queued, and 30 minutes since the push
        # is well beyond any real track length. A NULL queued_at
        # (pre-upgrade row) is treated as orphaned.
        queued_cutoff = utcnow_naive() - timedelta(minutes=30)
        result = await session.execute(
            select(Track).where(Track.status == "queued")
        )
        requeued = 0
        for track in result.scalars().all():
            queued_at = track.queued_at
            if queued_at is not None and queued_at.tzinfo is not None:
                queued_at = queued_at.replace(tzinfo=None)
            if queued_at is None or queued_at < queued_cutoff:
                track.status = "ready"
                track.queued_at = None
                requeued += 1
        if requeued:
            logger.info(
                "Reset %d orphaned 'queued' tracks back to 'ready'", requeued
            )

        # Clean up failed tracks: delete their audio files, and drop rows
        # past retention (generation_jobs keeps the failure history).
        failed_cutoff = utcnow_naive() - FAILED_TRACK_RETENTION
        result = await session.execute(
            select(Track).where(Track.status == "failed")
        )
        removed_failed = 0
        for track in result.scalars().all():
            if track.filepath and Path(track.filepath).exists():
                try:
                    Path(track.filepath).unlink()
                except OSError:
                    # File is stuck; keep the row so deletion retries next run.
                    continue
            created = track.created_at
            if created is not None and created.tzinfo is not None:
                created = created.replace(tzinfo=None)
            if created is None or created < failed_cutoff:
                await session.delete(track)
                removed_failed += 1
        if removed_failed:
            logger.info(
                "Deleted %d failed track rows past retention", removed_failed
            )

        await session.commit()

        # Reap rows stuck mid-generation (e.g. a crash or provider hang left
        # them in a transient state with no worker to finish them).
        await self._reap_stuck_generations(session)

        # Prune finished generation jobs past retention.
        await self._prune_finished_jobs(session)

        # Remove audio files no DB row references (failed generations)
        await self._cleanup_orphan_audio(session)

        # Clean up old recordings past retention
        await self._cleanup_recordings(session)

    async def _reap_stuck_generations(self, session: AsyncSession) -> None:
        """Fail rows stuck in a transient generation state past the max age.

        Without this, a process crash or provider hang mid-generation leaves
        tracks/breaks in ``generating`` (and jobs in ``running``) forever —
        they never become ``ready`` and the dashboard shows phantom
        in-flight work. Anything older than :data:`STUCK_GENERATION_MAX_AGE`
        is marked ``failed``.

        Args:
            session: Async database session.
        """
        cutoff = utcnow_naive() - STUCK_GENERATION_MAX_AGE
        reaped = 0

        # (model, timestamp column) for the transient content states.
        for model in (Track, DJBreak):
            result = await session.execute(
                select(model).where(
                    model.status == "generating",
                    model.created_at < cutoff,
                )
            )
            for row in result.scalars().all():
                row.status = "failed"
                reaped += 1

        # Generation jobs use their own running state / attempt bookkeeping.
        job_result = await session.execute(
            select(GenerationJob).where(
                GenerationJob.status == "running",
                GenerationJob.created_at < cutoff,
            )
        )
        for job in job_result.scalars().all():
            job.status = "failed"
            job.error_message = (
                job.error_message
                or "Reaped: stuck in 'running' past the max generation age."
            )
            job.finished_at = utcnow_naive()
            reaped += 1

        if reaped:
            logger.warning(
                "Reaped %d rows stuck mid-generation past %s",
                reaped,
                STUCK_GENERATION_MAX_AGE,
            )
            await session.commit()

    async def _prune_finished_jobs(self, session: AsyncSession) -> None:
        """Delete finished generation jobs older than :data:`JOB_RETENTION`.

        Diagnostics only need recent history; without pruning, the jobs
        table (and the dashboard's failed-job count) grows forever.

        Args:
            session: Async database session.
        """
        cutoff = utcnow_naive() - JOB_RETENTION
        result = await session.execute(
            delete(GenerationJob).where(
                GenerationJob.status.in_(("succeeded", "failed")),
                GenerationJob.created_at < cutoff,
            )
        )
        if result.rowcount:
            await session.commit()
            logger.info(
                "Pruned %d finished generation jobs older than %s",
                result.rowcount,
                JOB_RETENTION,
            )

    async def _cleanup_orphan_audio(self, session: AsyncSession) -> None:
        """Delete stale audio files in breaks/ that no row references.

        Failed or interrupted generations can abandon intermediates (TTS
        renders, stubs of failed breaks). Anything older than a day that is
        not the audio file of a DJBreak row is deleted.

        Args:
            session: Async database session.
        """
        referenced: set[str] = set()
        result = await session.execute(
            select(DJBreak.audio_filepath).where(
                DJBreak.audio_filepath.isnot(None)
            )
        )
        for (filepath,) in result.all():
            referenced.add(Path(filepath).name)

        cutoff = datetime.now(timezone.utc).timestamp() - 86400
        purged = 0
        directory = Path(settings.AUDIO_DIR) / "breaks"
        if directory.exists():
            for f in directory.iterdir():
                if not f.is_file() or f.suffix.lower() not in (".wav", ".mp3"):
                    continue
                if f.name in referenced:
                    continue
                try:
                    if f.stat().st_mtime >= cutoff:
                        continue
                    f.unlink()
                    purged += 1
                except OSError:
                    continue

        if purged:
            logger.info("Purged %d orphaned audio files from breaks/", purged)

    async def _cleanup_recordings(self, session: AsyncSession) -> None:
        """Delete recording files older than the configured retention period.

        Args:
            session: Async database session.
        """
        station = await get_station(session)
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
