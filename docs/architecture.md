# Architecture Direction

Airwave is being shaped as a broadcast automation system first and an AI
content generator second. The current music buffer, DJ brain, and scheduler
continue to run as they do today, while new shared foundations are added
underneath them.

## Core Model

The long-term architecture centers on three shared concepts:

| Concept | Purpose |
|---|---|
| `AudioAsset` | Immutable metadata for audio that has entered the station, including original path, normalized path, duration, loudness, checksum, provider, and processing status. |
| `ProgramItem` | A single item on the station timeline, such as a music track, DJ break, call clip, live input, or fallback item. |
| `GenerationJob` | A durable unit of provider or processing work, with inputs, provider/capability metadata, attempts, status, output, and errors. |

These records do not replace existing `Track`, `DJBreak`, or `PlayLog`
records yet. They are an additive foundation for moving the scheduler
and playout code toward one shared timeline.

## Why This Shape

Radio reliability is easier to reason about when every playable item follows the
same lifecycle:

`planned -> generating -> ready -> queued -> playing -> played -> archived/failed`

Provider calls are easier to debug when each piece of work is recorded as a job:
what was requested, which provider handled it, how many attempts were made, what
asset came out, and what failed.

Audio processing is easier to harden when every file becomes an asset with the
same normalization and measurement metadata.

## Migration Strategy

1. Keep current behavior stable.
2. Record new generated audio as `AudioAsset` rows.
3. Mirror existing queue decisions into `ProgramItem` rows.
4. Move generation calls behind `GenerationJob` records.
5. Teach the dashboard to read the timeline and job queue.
6. Move scheduler decisions to the timeline once the mirror data is trusted.

This avoids a risky rewrite while steadily moving the system toward the simpler
first-principles model.

## Current Timeline Mirror

Generated music tracks and DJ breaks are now mirrored into the
timeline foundation when they become ready. The legacy records remain the source
used by the current scheduler and routes, while `AudioAsset` and `ProgramItem`
rows provide a parallel timeline that can be validated before the scheduler is
moved onto it.

The dashboard exposes this mirror through `GET /api/dashboard/timeline` and a
read-only Program Timeline panel. This lets operators and developers inspect the
new timeline data without making it responsible for playout yet. Timeline
diagnostics are available through `GET /api/dashboard/timeline/health` and are
shown in the dashboard as issue counts for unmirrored content, timeline items
without assets, missing ready files, and failed generation jobs.
The timeline health endpoint also reports read-only scheduler parity
diagnostics, comparing legacy next-play candidates against timeline candidates
without allowing the timeline to drive playout.

Generation jobs have started moving into the same operator-console model. Music
track and DJ break generation now record `GenerationJob` rows for
provider work, mark them succeeded or failed, link successful jobs to generated
`AudioAsset` rows when audio exists, and expose recent jobs through
`GET /api/dashboard/jobs` plus a read-only Generation Jobs dashboard panel.
The dashboard panels include status/type filters so operators can focus on
problems first and expand to the full history when needed.

The scheduler now also records playout lifecycle changes into the mirrored
timeline. When legacy tracks are queued by the existing scheduler, their
matching `ProgramItem` rows move through `playing`, `played`, or `failed`
states. Queued DJ breaks are marked `playing` after the legacy
queue/log path succeeds. These lifecycle updates are still diagnostic: legacy
scheduler records remain authoritative, and timeline recording failures are
logged without stopping playout.
