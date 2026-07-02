"""Helpers for mirroring existing generated content into the program timeline."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.models.audio_asset import AudioAsset
from server.models.dj_break import DJBreak
from server.models.program_item import ProgramItem
from server.models.talk_segment import TalkSegment
from server.models.track import Track


async def mirror_track_ready(session: AsyncSession, track: Track) -> ProgramItem:
    """Mirror a ready track into audio asset and timeline records."""
    return await _mirror_ready_item(
        session=session,
        source_table="tracks",
        source_id=track.id,
        item_type="music_track",
        title=track.title,
        filepath=track.filepath,
        duration=track.duration,
        loudness_lufs=track.loudness_lufs,
        provider=track.provider,
        metadata_json=track.metadata_json,
    )


async def mirror_dj_break_ready(
    session: AsyncSession, dj_break: DJBreak
) -> ProgramItem:
    """Mirror a ready DJ break into audio asset and timeline records."""
    return await _mirror_ready_item(
        session=session,
        source_table="dj_breaks",
        source_id=dj_break.id,
        item_type="dj_break",
        title="DJ Break",
        filepath=dj_break.audio_filepath,
        duration=dj_break.duration,
        loudness_lufs=None,
        provider=None,
        metadata_json=dj_break.context,
    )


async def mirror_talk_segment_ready(
    session: AsyncSession, segment: TalkSegment
) -> ProgramItem:
    """Mirror a ready talk segment into audio asset and timeline records."""
    return await _mirror_ready_item(
        session=session,
        source_table="talk_segments",
        source_id=segment.id,
        item_type="talk_segment",
        title=segment.segment_type,
        filepath=segment.audio_filepath,
        duration=segment.duration,
        loudness_lufs=segment.loudness_lufs,
        provider=None,
        metadata_json=segment.context,
    )


async def _mirror_ready_item(
    *,
    session: AsyncSession,
    source_table: str,
    source_id: int,
    item_type: str,
    title: str | None,
    filepath: str | None,
    duration: float | None,
    loudness_lufs: float | None,
    provider: str | None,
    metadata_json: str | None,
) -> ProgramItem:
    """Create timeline mirror rows unless this source is already mirrored."""
    result = await session.execute(
        select(ProgramItem).where(
            ProgramItem.source_table == source_table,
            ProgramItem.source_id == source_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    asset_id: int | None = None
    if filepath:
        asset = AudioAsset(
            asset_type=item_type,
            normalized_filepath=filepath,
            duration=duration,
            loudness_lufs=loudness_lufs,
            provider=provider,
            status="ready",
            metadata_json=metadata_json,
        )
        session.add(asset)
        await session.flush()
        asset_id = asset.id

    item = ProgramItem(
        item_type=item_type,
        status="ready",
        audio_asset_id=asset_id,
        source_table=source_table,
        source_id=source_id,
        title=title,
        duration=duration,
        metadata_json=metadata_json,
    )
    session.add(item)
    await session.flush()
    return item
