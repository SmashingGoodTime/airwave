# Airwave — AGENTS.md

## Project Overview

Airwave is an open-source, self-contained automated radio station powered by AI. It generates music, writes and voices DJ breaks, manages announcements, and streams everything as a continuous broadcast — all from a single `docker-compose up` command.

The system is designed so that **any radio station** can run it with minimal setup. A first-run setup wizard walks operators through configuration. No editing config files required to get started.

**License**: MIT

---

## Architecture Principles

### Provider Abstraction (CRITICAL)

The system uses a **plugin architecture** with three provider interfaces. All engine code MUST interact with providers through abstract base classes only. Never import a specific provider (Suno, Gemini, Fish Audio, etc.) directly in engine or router code. Always go through the provider registry.

```
providers/
├── base.py            # Abstract base classes — the contracts
├── registry.py        # Provider discovery and instantiation
├── music/
│   ├── suno.py        # MusicProvider implementation
│   └── ...
├── scriptwriter/
│   ├── google.py      # ScriptWriterProvider implementation
│   └── ...
└── voice/
    ├── fish.py        # VoiceProvider implementation
    └── ...
```

**Three provider interfaces:**

1. **MusicProvider** — `generate(prompt, duration) → TrackResult`
2. **ScriptWriterProvider** — `write_break(context) → BreakScript`
3. **VoiceProvider** — `render(text, voice_config) → Path` and `list_voices() → list`

Each provider must also implement `check_status() → bool` for health monitoring.

New providers are added by:
1. Creating a new file in the appropriate `providers/` subdirectory
2. Subclassing the abstract base
3. Registering it in the provider registry
4. No other code changes required

### Self-Contained / Single Process

- Backend (FastAPI) serves the React frontend as static files
- SQLite only — no external database
- Background workers run as async tasks within the same process
- Docker Compose bundles app + Liquidsoap + Icecast
- Everything the station needs is in one repo

### Graceful Degradation

- The UI MUST load and be fully navigable even if zero providers are configured
- If a provider is down, the system logs warnings and continues with what it has
- Dead air protection: a `fallback/` directory of emergency audio loops if the buffer drains completely
- Buffer low alerts surface in the dashboard well before dead air is possible

### Configuration

- `.env` for secrets (API keys) — never committed, `.env.example` provided
- All other config lives in the database, managed through the UI
- Pydantic Settings for validation and defaults
- Station timezone is configurable and used for all scheduling logic

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy (SQLite), APScheduler |
| Frontend | React (Vite), served as static build by FastAPI |
| Music Generation | SunoAPI.org (default provider) — an unofficial third-party bridge to Suno's models; Suno has no public API |
| DJ Script Writing | Google Gemini API (default provider) |
| TTS / DJ Voice | Fish Audio API (default provider) |
| Audio Processing | FFmpeg, pydub |
| Playout | Liquidsoap |
| Streaming | Icecast |
| Containerization | Docker, Docker Compose |

---

## Project Structure

```
airwave/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── README.md
├── CONTRIBUTING.md
├── AGENTS.md                      # This file — guidance for AI coding agents
├── CLAUDE.md                      # Thin pointer at AGENTS.md, for Claude Code
├── LICENSE
│
├── server/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app, lifespan, static mount
│   ├── config.py                  # Pydantic Settings from env + DB
│   ├── database.py                # SQLAlchemy engine, session, base
│   │
│   ├── models/                    # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── track.py               # Generated tracks + status
│   │   ├── style.py               # Song style prompts + scheduling
│   │   ├── announcement.py        # Announcements with priority/expiry
│   │   ├── dj_break.py            # Generated DJ break scripts + audio
│   │   ├── dj_config.py           # DJ personality, voice, break rules
│   │   ├── playlog.py             # What played and when (exportable)
│   │   └── station.py             # Station identity, timezone, settings
│   │
│   ├── routers/                   # FastAPI route modules
│   │   ├── __init__.py
│   │   ├── styles.py              # CRUD for song style prompts
│   │   ├── announcements.py       # CRUD for announcements
│   │   ├── dj_config.py           # DJ personality and voice settings
│   │   ├── dashboard.py           # Now playing, buffer, health, logs
│   │   ├── setup.py               # First-run wizard endpoints
│   │   └── playlog.py             # Play history, CSV export
│   │
│   ├── providers/                 # Provider abstraction layer
│   │   ├── __init__.py
│   │   ├── base.py                # Abstract base classes
│   │   ├── registry.py            # Provider discovery + instantiation
│   │   ├── music/
│   │   │   ├── __init__.py
│   │   │   └── suno.py
│   │   ├── scriptwriter/
│   │   │   ├── __init__.py
│   │   │   └── google.py
│   │   └── voice/
│   │       ├── __init__.py
│   │       └── fish.py
│   │
│   ├── engine/                    # Core station logic
│   │   ├── __init__.py
│   │   ├── scheduler.py           # Master orchestrator / main loop
│   │   ├── music_buffer.py        # Track generation queue manager
│   │   ├── dj_brain.py            # Break timing, script gen, context
│   │   ├── playout.py             # Liquidsoap interface + metadata
│   │   └── audio_pipeline.py      # Normalization, format conversion
│   │
│   ├── events/                    # Event / webhook system
│   │   ├── __init__.py
│   │   ├── emitter.py             # Event bus
│   │   └── handlers.py            # Built-in handlers (logging, etc.)
│   │
│   └── utils/
│       ├── __init__.py
│       └── audio.py               # FFmpeg wrappers, loudnorm, etc.
│
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── App.jsx
│       ├── api.js                 # API client
│       ├── pages/
│       │   ├── Dashboard.jsx      # Now playing, buffer depth, health
│       │   ├── Styles.jsx         # Song style prompt manager
│       │   ├── DJConfig.jsx       # DJ personality + voice + break rules
│       │   ├── Announcements.jsx  # Announcement board
│       │   ├── PlayLog.jsx        # History + CSV export
│       │   └── Setup.jsx          # First-run wizard
│       └── components/
│           ├── NowPlaying.jsx
│           ├── BufferStatus.jsx
│           ├── HealthIndicators.jsx
│           ├── AudioPlayer.jsx    # Embedded Icecast stream player
│           ├── StyleCard.jsx
│           └── AnnouncementCard.jsx
│
├── liquidsoap/
│   └── station.liq                # Liquidsoap playout config
│
├── audio/                         # Docker volume
│   ├── tracks/                    # Generated music buffer
│   ├── breaks/                    # Rendered DJ break audio
│   ├── fallback/                  # Emergency loop tracks
│   └── archive/                   # Played tracks (retention policy)
│
└── docs/
    ├── quickstart.md
    ├── adding-providers.md
    └── configuration.md
```

---

## Data Models

### Track
- `id`, `uuid`
- `filepath` — path to audio file
- `title` — generated or extracted title
- `style_id` — FK to the style prompt that generated it
- `style_prompt` — the actual prompt sent (snapshot, since styles can be edited)
- `content_policy_suffix` — the content filter text appended to prompt
- `duration` — seconds
- `provider` — which MusicProvider generated it
- `status` — enum: `generating`, `ready`, `playing`, `played`, `archived`, `failed`
- `loudness_lufs` — measured loudness after normalization
- `metadata` — JSON blob for provider-specific data
- `created_at`, `played_at`

### Style
- `id`
- `name` — human label ("Late Night Ambient", "Morning Energy")
- `prompt` — the style/genre prompt text
- `active` — boolean toggle
- `weight` — relative frequency weight for selection
- `schedule` — JSON: optional time-of-day windows (e.g., `{"start": "22:00", "end": "06:00"}`)
- `tags` — comma-separated genre/mood tags (used by DJ brain for commentary)
- `created_at`, `updated_at`

### Announcement
- `id`
- `text` — the announcement content
- `priority` — enum: `low`, `normal`, `high`, `urgent`
- `active` — boolean
- `expires_at` — nullable datetime, auto-deactivates after expiry
- `play_count` — how many times it's been included in a break
- `max_plays` — nullable, auto-deactivates after N plays
- `created_at`

### DJBreak
- `id`
- `script_text` — the generated DJ script
- `audio_filepath` — rendered TTS audio
- `context` — JSON snapshot of what the brain used (tracks, announcements, time)
- `duration` — seconds
- `status` — enum: `generating`, `ready`, `played`, `failed`
- `created_at`, `played_at`

### DJConfig (singleton-ish, one active config)
- `id`
- `station_name` — call sign / station name
- `dj_name` — the DJ persona's name
- `personality_prompt` — system prompt for the DJ persona (tone, catchphrases, vibe)
- `voice_provider` — which VoiceProvider to use
- `voice_id` — provider-specific voice identifier
- `voice_settings` — JSON (stability, similarity_boost, etc.)
- `break_frequency` — how many tracks between breaks (e.g., 3)
- `break_frequency_variance` — randomization range (e.g., ±1)
- `mention_time` — boolean, whether DJ mentions time of day
- `mention_weather` — boolean (future feature)
- `content_policy` — enum: `instrumental_only`, `clean_vocals`, `no_restrictions`
- `content_policy_suffix` — the actual text appended to every music prompt (auto-generated from content_policy or custom)
- `max_break_duration` — seconds, cap on DJ break length
- `updated_at`

### PlayLog
- `id`
- `item_type` — enum: `track`, `dj_break`
- `item_id` — FK to track or break
- `started_at`, `ended_at`
- `duration`
- `metadata` — JSON (title, style, etc. for easy export without joins)

### Station
- `id`
- `timezone` — IANA timezone string
- `stream_url` — Icecast stream URL
- `setup_complete` — boolean, gates the first-run wizard
- `disk_retention_days` — how long to keep archived audio
- `buffer_target` — how many tracks to keep ready (default 5)
- `buffer_warning_threshold` — alert when buffer drops below this (default 2)

---

## Engine Logic

### Master Scheduler (`engine/scheduler.py`)
The main loop that orchestrates everything. Runs as an async background task on app startup.

Responsibilities:
- Monitor buffer depth, trigger music generation when below target
- Count tracks since last break, trigger DJ break generation at the right time
- Interface with Liquidsoap playout (track queue, metadata updates)
- Emit events on state changes
- Run disk cleanup on a schedule (archive old tracks, purge past retention)

### Music Buffer (`engine/music_buffer.py`)
- Checks buffer depth against `station.buffer_target`
- Selects a style prompt based on weights, time-of-day schedule, and recent history (avoid repeating the same style back-to-back)
- Appends the `content_policy_suffix` from DJConfig to the prompt
- Calls the active MusicProvider
- Runs the result through the audio pipeline (normalize loudness to -14 LUFS via `loudnorm`, convert to consistent format: 48kHz stereo WAV)
- Saves to `audio/tracks/` and creates the Track record
- Respects provider rate limits — uses backoff/retry, never burst-requests

### DJ Brain (`engine/dj_brain.py`)
- Tracks how many songs have played since last break
- When it's time for a break, assembles context:
  - Last N track titles, styles, and tags
  - Active announcements (prioritized, respecting max_plays and expiry)
  - Station identity (name, call sign, DJ persona)
  - Current time in station timezone
  - Any special context (time of day greeting, etc.)
- Calls the active ScriptWriterProvider with this context
- Calls the active VoiceProvider to render the script
- Runs the audio through the pipeline (normalize, format)
- Saves to `audio/breaks/` and creates the DJBreak record

**DJ Script Prompt Structure:**
The system prompt to the ScriptWriter should include the DJ personality prompt from config and station identity. The user message should include the structured context (recent tracks, announcements, time). The prompt should instruct natural, conversational delivery — not reading a list. Announcements should be woven in organically. The script should be concise (target the `max_break_duration` from config, roughly 150 words per minute for TTS estimation).

### Audio Pipeline (`engine/audio_pipeline.py`)
All audio entering the system goes through this:
1. Format detection and conversion to 48kHz stereo WAV
2. Loudness normalization to -14 LUFS (EBU R128) via FFmpeg `loudnorm` (two-pass)
3. Loudness measurement stored on the Track/Break record
4. Silence trimming (remove excessive silence at start/end)

### Playout Interface (`engine/playout.py`)
Communicates with Liquidsoap via its telnet or Unix socket interface:
- Queue next track or break
- Skip current item
- Get current playback status
- Update Icecast stream metadata (title, artist) on track change
- Monitor for silence / dead air and trigger fallback

---

## Event System

Simple pub/sub event bus for extensibility:

**Built-in events:**
- `track.generated` — new track ready in buffer
- `track.started` — track began playing
- `track.ended` — track finished playing
- `break.generated` — DJ break audio ready
- `break.started` / `break.ended`
- `buffer.low` — buffer dropped below warning threshold
- `buffer.critical` — buffer at 0, fallback activated
- `provider.error` — a provider call failed
- `provider.recovered` — provider responding again

**Built-in handlers:**
- PlayLog writer (records everything that plays)
- Dashboard WebSocket push (real-time UI updates)
- Console logger

**Extension point:** Users can register custom handlers (webhook URLs, Discord bots, lighting control, now-playing website updates) by adding handler modules. Document this in `docs/adding-providers.md` alongside provider extension.

---

## API Endpoints

### Setup
- `GET /api/setup/status` — is first-run setup complete?
- `POST /api/setup/complete` — save initial config from wizard

### Styles
- `GET /api/styles` — list all styles
- `POST /api/styles` — create style
- `PUT /api/styles/{id}` — update style
- `DELETE /api/styles/{id}` — delete style
- `POST /api/styles/{id}/toggle` — toggle active
- `POST /api/styles/reorder` — update weights/order

### Announcements
- `GET /api/announcements` — list all (filter by active)
- `POST /api/announcements` — create
- `PUT /api/announcements/{id}` — update
- `DELETE /api/announcements/{id}` — delete

### DJ Config
- `GET /api/dj/config` — get current DJ configuration
- `PUT /api/dj/config` — update DJ configuration
- `POST /api/dj/preview` — generate a test DJ break (script + audio) without queueing it
- `GET /api/dj/voices` — list available voices from active VoiceProvider

### Dashboard
- `GET /api/dashboard/status` — now playing, buffer depth, provider health, stream status
- `GET /api/dashboard/recent` — last N played items (tracks + breaks)
- `GET /api/dashboard/health` — provider connectivity status
- `WebSocket /api/dashboard/ws` — real-time updates

### Play Log
- `GET /api/playlog` — paginated play history
- `GET /api/playlog/export` — CSV download

### Stream
- `GET /api/stream/url` — Icecast stream URL for the embedded player

---

## Frontend Pages

### Setup Wizard (`Setup.jsx`)
Only shown on first run. Steps:
1. Station identity (name, call sign, timezone)
2. API keys (Suno, Google, Fish Audio) — stored in DB, encrypted at rest
3. DJ persona (name, personality, voice selection with preview)
4. Content policy (instrumental only / clean / no restrictions)
5. Add first few style prompts
6. Test: generate one track + one DJ break to verify everything works

### Dashboard (`Dashboard.jsx`)
- Now playing card with title, style, elapsed/remaining time
- Buffer depth gauge (visual, color-coded)
- Provider health indicators (green/yellow/red per provider)
- Stream status (listeners count if Icecast exposes it)
- Recent play history (scrolling list)
- Embedded audio player for monitoring the stream

### Styles (`Styles.jsx`)
- Card-based list of style prompts
- Each card shows: name, prompt text, weight, schedule, active toggle
- Add/edit modal with fields for all style properties
- Drag to reorder / adjust weight
- Time-of-day schedule picker (visual timeline)
- Preview button: generate a track with this style (doesn't enter buffer, just for testing)

### DJ Config (`DJConfig.jsx`)
- Station identity section (name, call sign)
- DJ personality textarea (the system prompt)
- Voice selection dropdown (from provider's `list_voices`)
- Voice preview button
- Break frequency slider with variance
- Content policy selector (instrumental_only / clean_vocals / no_restrictions)
- Custom content policy suffix override (advanced, collapsed by default)
- Toggles: mention time, mention weather (future)

### Announcements (`Announcements.jsx`)
- List with priority color coding
- Add/edit with: text, priority dropdown, expiration date picker, max plays
- Active/inactive toggle
- Play count display
- Expired items shown greyed out at bottom

### Play Log (`PlayLog.jsx`)
- Table: timestamp, type (track/break), title/description, duration
- Date range filter
- CSV export button

---

## Coding Standards

- **Type hints everywhere** — all function signatures, return types, variable annotations where non-obvious
- **Docstrings on all public methods and classes** — Google style
- **Async by default** — all provider calls, database operations, and engine methods are async
- **Pydantic models for all API request/response schemas** — separate from SQLAlchemy models
- **Error handling** — providers must catch their own exceptions and return meaningful errors. Never let a provider exception crash the engine.
- **Logging** — use Python's `logging` module with structured context. Log level configurable. Key events: track generated, break generated, provider errors, buffer state changes.
- **No hardcoded values** — everything configurable through DB/UI or environment variables
- **Tests** — pytest, async tests with httpx. Provider tests should use mocks. Engine tests should use a mock provider that returns dummy audio files.

---

## Audio Format Standards

- **Internal format**: 48kHz, 16-bit, stereo WAV
- **Loudness target**: -14 LUFS (EBU R128)
- **Normalization**: two-pass FFmpeg `loudnorm` filter
- **Silence trimming**: strip silence below -50dB from start/end, leave 0.5s padding
- All provider output gets normalized before entering any queue

---

## Docker Configuration

### docker-compose.yml services:

**app** — Python backend + frontend static files
- Builds from Dockerfile
- Mounts `./audio` as volume
- Exposes port 8000 (API + UI)
- Environment from `.env`

**liquidsoap** — Audio playout engine
- Official Liquidsoap image
- Mounts `./audio` (read) and `./liquidsoap/station.liq`
- Communicates with app via telnet socket
- Outputs to Icecast

**icecast** — Stream server
- Official Icecast image
- Exposes port 8080 (stream)
- Config mounted from `./icecast/icecast.xml`

### Volumes:
- `audio` — shared between app and liquidsoap

---

## Build Order

Build in this sequence, getting each layer working before the next:

### Phase 1: Foundation
1. Project scaffolding (directory structure, Docker setup, .env.example)
2. Database models + migrations (SQLAlchemy + Alembic)
3. FastAPI app skeleton with routers returning mock data
4. React app skeleton with routing between pages
5. Static file serving (FastAPI serves built React app)
6. First-run setup wizard (stores config in DB)

### Phase 2: Provider Layer
7. Abstract base classes in `providers/base.py`
8. Provider registry with config-driven instantiation
9. Suno provider implementation
10. Gemini scriptwriter provider implementation
11. Fish Audio voice provider implementation
12. Health check endpoints for each provider

### Phase 3: Engine
13. Audio pipeline (normalization, format conversion)
14. Music buffer manager (style selection, generation, queueing)
15. DJ brain (context assembly, script generation, TTS rendering)
16. Content policy suffix injection into music prompts
17. Master scheduler (ties buffer + brain + playout together)
18. Dead air protection (fallback directory, buffer alerts)

### Phase 4: Playout
19. Liquidsoap config (`station.liq` with track queue, crossfade, fallback, DJ break insertion)
20. Playout interface (telnet commands from Python)
21. Icecast metadata updates on track change
22. Crossfade logic (energy-aware transitions)

### Phase 5: UI Polish
23. Dashboard with real-time WebSocket updates
24. Styles page with full CRUD, scheduling, preview
25. DJ config page with voice preview
26. Announcements board with priority/expiry
27. Play log with CSV export
28. Embedded stream player
29. Buffer and health monitoring visualizations

### Phase 6: Production Hardening
30. Rate limit awareness in all providers (backoff, retry, pacing)
31. Disk space management (archival, cleanup scheduler)
32. Comprehensive error handling and recovery
33. Logging and observability
34. Event system with WebSocket + extensible handlers

### Phase 7: Documentation
35. README with screenshots and quickstart
36. docs/quickstart.md — zero to streaming in 5 minutes
37. docs/adding-providers.md — how to write a new provider
38. docs/configuration.md — all settings explained
39. CONTRIBUTING.md — dev setup, code style, PR process

---

## Key Reminders

- **Never import a specific provider in engine code.** Always use the registry.
- **The UI must work with no providers configured.** Graceful degradation everywhere.
- **Content policy suffix is appended to EVERY music generation prompt.** This is the primary content filtering mechanism.
- **Normalize ALL audio** before it enters any queue. No exceptions.
- **Log everything that plays.** Stations need this for compliance.
- **Dead air is the worst failure mode.** Always have fallback audio.
- **Rate limits are real.** Pace provider calls, never burst.
- **Timezone matters.** All scheduling uses the station's configured timezone.
- **This is open source.** Write clear code, good docs, and helpful error messages. Someone who has never seen the codebase should be able to add a provider in an afternoon.
