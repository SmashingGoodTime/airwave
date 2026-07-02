# Timeline Reconciliation Dashboard Design

## Objective

Add read-only trust diagnostics that compare the legacy scheduler's next-play decisions with the mirrored `program_items` timeline, then surface that scheduler parity clearly on the dashboard.

## Scope

- Add backend reconciliation diagnostics for music and talk queues.
- Extend the existing `GET /api/dashboard/timeline/health` response instead of adding a new endpoint.
- Show scheduler parity in the existing Dashboard Program Timeline panel.
- Detect duplicate timeline mirrors and source/timeline readiness drift.
- Keep the legacy scheduler authoritative. This phase must not change Liquidsoap queueing, track selection, talk selection, DJ break timing, provider calls, or playout state transitions.

## Non-Goals

- Do not make `ProgramItem` authoritative for playout.
- Do not repair duplicate or orphan timeline rows automatically.
- Do not compare DJ break queue selection yet; DJ break scheduling depends on break timing and generated context, so this phase only includes DJ break integrity counts through source/timeline readiness diagnostics.
- Do not introduce provider-specific imports in engine or router code.

## Backend Behavior

Create a focused helper module, `server/engine/timeline_reconciliation.py`, with one public async function:

```python
async def build_timeline_reconciliation(session: AsyncSession) -> dict:
    """Build read-only diagnostics comparing legacy ready queues to timeline rows."""
```

The helper returns JSON-ready data:

```json
{
  "parity_status": "aligned",
  "summary": {
    "duplicate_source_mirrors": 0,
    "music_candidate_mismatch": 0,
    "talk_candidate_mismatch": 0,
    "legacy_ready_missing_timeline": 0,
    "timeline_ready_source_not_ready": 0
  },
  "comparisons": [
    {
      "queue": "music",
      "show_id": null,
      "aligned": true,
      "legacy_source": {"source_table": "tracks", "source_id": 1, "title": "Song"},
      "timeline_source": {"source_table": "tracks", "source_id": 1, "title": "Song"}
    }
  ],
  "issues": []
}
```

Status rules:

- `aligned`: no reconciliation issues.
- `drifting`: one or more candidate mismatches, but no duplicate source mirrors.
- `needs_attention`: duplicate source mirrors or source/timeline readiness drift exists.

Candidate rules:

- Music legacy candidate: oldest `Track(status="ready")` by `Track.created_at`, then `Track.id`.
- Music timeline candidate: first ready `ProgramItem` for `source_table="tracks"` and `item_type="music_track"` with a ready `Track` source, ordered by `ProgramItem.position`, `ProgramItem.planned_start_at`, `ProgramItem.created_at`, then `ProgramItem.id`.
- Talk legacy candidate: oldest ready `TalkSegment` for each `show_id` by `TalkSegment.created_at`, then `TalkSegment.id`.
- Talk timeline candidate: first ready `ProgramItem` for `source_table="talk_segments"` and `item_type="talk_segment"` joined to a ready `TalkSegment` source for the same `show_id`, ordered by `ProgramItem.position`, `ProgramItem.planned_start_at`, `ProgramItem.created_at`, then `ProgramItem.id`.

Integrity diagnostics:

- `duplicate_source_mirrors`: number of `(source_table, source_id)` groups with more than one `ProgramItem`.
- `legacy_ready_missing_timeline`: ready tracks, DJ breaks, and talk segments with no matching timeline row.
- `timeline_ready_source_not_ready`: ready timeline rows whose source row is missing or not `ready`.

## API Behavior

Extend `GET /api/dashboard/timeline/health`:

- Merge reconciliation summary fields into `summary`.
- Merge reconciliation issues into `issues`, except omit the aggregate
  `legacy_ready_missing_timeline` issue from the top-level list because the
  existing per-type unmirrored issues are more actionable there. Keep the
  aggregate issue in the nested `reconciliation.issues` list.
- Add a nested `reconciliation` object containing `parity_status`, `summary`, `comparisons`, and reconciliation-only `issues`.
- `healthy` remains `true` only when the full issue list is empty.

## Dashboard Behavior

Update `frontend/src/pages/Dashboard.jsx` inside the existing Program Timeline card:

- Show a compact badge labeled `Scheduler parity: Aligned`, `Scheduler parity: Drifting`, or `Scheduler parity: Needs attention`.
- Render reconciliation issue badges alongside existing timeline issue badges.
- When candidate comparisons exist, show a compact line per comparison using source IDs and titles, only in the Program Timeline diagnostics area.
- Keep this as operator diagnostics, not a new page and not a decorative card inside the existing card.

## Tests

Add focused backend tests:

- Helper reports aligned music candidates.
- Helper reports music candidate mismatch.
- Helper reports duplicate source mirrors.
- Helper reports legacy-ready missing timeline rows and timeline-ready source drift.
- Helper reports talk candidate mismatch per show.
- Router response includes reconciliation data and marks health unhealthy when reconciliation issues exist.

Frontend verification:

- `npm run build` in `frontend`.

Backend verification:

- `powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_timeline_reconciliation.py tests\test_routers.py`
- `powershell -ExecutionPolicy Bypass -File scripts\test.ps1`
