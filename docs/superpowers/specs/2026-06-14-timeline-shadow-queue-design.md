# Timeline Shadow Queue Design

## Purpose

Move the station toward timeline-driven broadcast automation without making
`ProgramItem` authoritative yet. The first slice records scheduler playout
decisions into the timeline lifecycle while keeping existing track, DJ break,
talk segment, fallback, and Liquidsoap behavior intact.

This gives operators and developers a trustworthy shadow timeline before any
scheduler decision depends on it.

## Current State

Generated music tracks, DJ breaks, and talk segments are mirrored into
`AudioAsset` and `ProgramItem` rows when they become ready. The dashboard can
display recent timeline items and timeline health diagnostics. Generation work
is also recorded in `GenerationJob` rows.

The legacy scheduler still chooses what plays next from `Track`, `DJBreak`, and
`TalkSegment` rows. Those legacy records remain the source of truth for playout
in this design.

## Scope

This slice adds a conservative timeline lifecycle recorder beside the existing
scheduler.

In scope:

- Add timeline lifecycle helpers for existing `ProgramItem` rows.
- Mark mirrored items as `queued` and `playing` when the scheduler queues their
  source record to Liquidsoap.
- Mark mirrored items as `played` when the scheduler closes the previous source
  record as played.
- Mark mirrored items as `failed` when the corresponding source record cannot
  be queued because its audio file is missing or queueing fails.
- Keep timeline update failures from interrupting broadcast playout.
- Cover music, DJ break, talk segment, and missing-audio paths with tests.

Out of scope:

- Replacing style selection, break timing, talk segment selection, or fallback
  selection with timeline queries.
- Creating fallback `ProgramItem` rows.
- Rewriting Liquidsoap queue logic.
- Changing the dashboard UI beyond any small diagnostic field needed by tests.
- Migrating existing historical rows.

## Architecture

Create a focused module, `server/engine/timeline_state.py`, responsible only for
finding and updating existing `ProgramItem` rows by source identity.

The scheduler continues to decide what should play. After each legacy decision,
it asks the timeline state module to record what happened. The dependency points
one way: scheduler code may call timeline state helpers, but timeline state
helpers must not import scheduler, providers, playout, or selection logic.

The helper API should be small and source-oriented:

- Find item by `source_table` and `source_id`.
- Mark an item as `queued` with `queued_at`.
- Mark an item as `playing` with `queued_at` and `started_at`.
- Mark an item as `played` with `ended_at`.
- Mark an item as `failed` with `ended_at`.

Missing timeline rows are valid. Older rows, manually created content, and
partial data may not have a mirror yet. In those cases helpers return `None` and
the scheduler continues.

## Lifecycle Rules

The initial shadow lifecycle is:

`ready -> queued -> playing -> played`

Failure lifecycle:

`ready -> failed`

For this slice, queueing and starting happen in the same scheduler action for
most item types because the current scheduler marks legacy rows as `playing`
immediately after handing them to Liquidsoap. The helper may set both
`queued_at` and `started_at` in the same call.

Lifecycle updates should be idempotent:

- Repeating a mark-as-playing call on a `ready`, `queued`, or `playing` item
  keeps one row and updates missing timestamps only.
- Repeating a mark-as-played call on a `played` item keeps it played.
- A `played` item must not be moved back to `playing`.
- Missing timeline rows must not create new timeline rows in lifecycle helpers.
  Creation remains the job of the existing mirror helpers.

## Data Flow

Music:

1. Music generation mirrors a ready `Track` to a ready `ProgramItem`.
2. `_queue_next_track()` selects a ready `Track` using existing logic.
3. If the track file exists and Liquidsoap accepts it, the legacy `Track` becomes
   `playing`.
4. The matching `ProgramItem(source_table="tracks", source_id=track.id)` becomes
   `playing`.
5. When the scheduler closes a previous playing track, the matching timeline
   item becomes `played`.

DJ breaks:

1. DJ break generation mirrors a ready `DJBreak` to a ready `ProgramItem`.
2. Existing scheduler logic queues the DJ break when break timing says it is
   due.
3. The matching `ProgramItem(source_table="dj_breaks", source_id=dj_break.id)`
   becomes `playing` when the break is handed to Liquidsoap.
4. When a previous DJ break is closed as played, the matching timeline item
   becomes `played`.

Talk segments:

1. Talk segment generation mirrors a ready `TalkSegment` to a ready
   `ProgramItem`.
2. `_manage_talk_playout()` and hybrid playout paths select a ready segment
   using existing logic.
3. The matching `ProgramItem(source_table="talk_segments", source_id=segment.id)`
   becomes `playing` when queued.
4. When a previous talk segment is closed as played, the matching timeline item
   becomes `played`.

Missing or rejected audio:

1. Existing scheduler logic marks the source record as `failed`.
2. The matching timeline item becomes `failed`.
3. Broadcast fallback behavior remains unchanged.

## Error Handling

Timeline recording is diagnostic and must not cause dead air.

Scheduler integration should wrap timeline helper calls so that exceptions are
logged as warnings and playout continues. This wrapper can live in the scheduler
or in a small timeline-state helper, but the behavior must be explicit in tests
or existing scheduler reliability tests must continue to prove playout proceeds.

The helper should not raise for missing rows. It should return `None`.

Unexpected database errors may still raise inside the helper, but scheduler call
sites must catch those errors around non-critical timeline updates.

## Testing Strategy

Unit tests for `server/engine/timeline_state.py`:

- Marking a ready timeline item as playing sets `status`, `queued_at`, and
  `started_at`.
- Marking a playing timeline item as played sets `status` and `ended_at`.
- Marking a ready timeline item as failed sets `status` and `ended_at`.
- Missing source rows return `None`.
- A played timeline item is not moved back to playing.

Scheduler reliability tests:

- Queueing a music track marks the matching timeline item as playing.
- Closing a previous playing track marks its timeline item as played.
- Missing music audio marks the matching timeline item as failed.
- Queueing a talk segment marks the matching timeline item as playing.
- Closing a previous talk segment marks its timeline item as played.
- DJ break queueing, where covered by existing scheduler tests, marks its
  timeline item as playing.

Regression tests:

- Existing scheduler tests for fallback, hybrid alternation, playlog writing,
  metadata updates, and provider failure recovery continue to pass.

## Success Criteria

- Existing playout behavior is unchanged.
- `ProgramItem` lifecycle state matches source records for newly queued music,
  DJ breaks, and talk segments.
- Timeline failures do not prevent queueing.
- Missing preexisting timeline rows are tolerated.
- Tests describe the new lifecycle contract before implementation.

## Next Slice After This

Once shadow lifecycle data is reliable, the next design can introduce a read-only
timeline candidate selector that compares "what the scheduler would play" with
"what the timeline would play." Only after those match should `ProgramItem`
become the scheduler source of truth.
