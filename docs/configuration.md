# Configuration Reference

Every setting in AI Radio DJ, explained. Most settings have sensible defaults and don't need to be changed.

---

## Table of Contents

1. [Where Settings Live](#1-where-settings-live)
2. [Environment Variables (.env)](#2-environment-variables-env)
3. [Station Settings (Web UI)](#3-station-settings-web-ui)
4. [DJ Configuration (Web UI)](#4-dj-configuration-web-ui)
5. [Music Styles (Web UI)](#5-music-styles-web-ui)
6. [Announcements (Web UI)](#6-announcements-web-ui)
7. [Show Schedule (Web UI)](#7-show-schedule-web-ui)
8. [Call-in Configuration (Roadmap)](#8-call-in-configuration-roadmap)
9. [Audio Standards](#9-audio-standards)
10. [Rate Limits](#10-rate-limits)
11. [Background Loops](#11-background-loops)
12. [Docker & Infrastructure](#12-docker--infrastructure)

---

## 1. Where Settings Live

AI Radio DJ has two types of settings:

| Type | Where | How to Change |
|------|-------|--------------|
| **Secrets & infrastructure** | `.env` file | Edit the file, restart the app |
| **Station behavior** | SQLite database | Change through the web UI (takes effect immediately) |

The `.env` file holds things like API keys and server ports — stuff you typically set once. Everything else (station name, DJ personality, music styles, break frequency) lives in the database and is managed through the web dashboard.

---

## 2. Environment Variables (.env)

These are set in the `.env` file at the project root. Changes require restarting the app.

### Server

| Variable | Default | What It Does |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Network address the server listens on. `0.0.0.0` means all interfaces. |
| `PORT` | `8000` | Port for the web dashboard and API. |
| `LOG_LEVEL` | `INFO` | How verbose the logs are. Options: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Use `DEBUG` for troubleshooting. |
| `DATABASE_URL` | `sqlite+aiosqlite:///./radio.db` | Path to the SQLite database. Under docker-compose this is overridden to `sqlite+aiosqlite:////data/radio.db` so the database persists in the host `./data` directory. |
| `AUDIO_DIR` | `./audio` | Root directory for all audio files (tracks, breaks, fallback, archive). |

### API Keys

| Variable | Default | What It Does |
|----------|---------|-------------|
| `SUNO_API_KEY` | *(empty)* | Key for Suno music generation. Without this, no music is created. |
| `GOOGLE_API_KEY` | *(empty)* | Key for Google Gemini script writing. Without this, no DJ scripts are written. |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Gemini model used for script writing. |
| `FISH_AUDIO_API_KEY` | *(empty)* | Key for Fish Audio voice rendering. Without this, DJ scripts aren't spoken aloud. |

All keys are optional. The station starts without them but won't generate content until they're provided. You can enter keys through the setup wizard instead of editing `.env`.

### Liquidsoap Connection

| Variable | Default | What It Does |
|----------|---------|-------------|
| `LIQUIDSOAP_HOST` | `liquidsoap` | Hostname of the Liquidsoap service. Use `localhost` for local development. |
| `LIQUIDSOAP_PORT` | `1234` | Port for Liquidsoap's control interface. |
| `LIQUIDSOAP_HARBOR_PORT` | `8005` | Port for live caller audio input (harbor). Only reachable inside the Docker network. |
| `HARBOR_SOURCE_PASSWORD` | `hackme` | Password a source must present to connect to the harbor input. |

In Docker, the defaults connect to the `liquidsoap` container automatically.

### Icecast (Stream Server)

| Variable | Default | What It Does |
|----------|---------|-------------|
| `ICECAST_URL` | `http://localhost:8080/stream` | Public URL for the live stream. Shown in the dashboard player. |
| `ICECAST_SOURCE_PASSWORD` | `hackme` | Password Liquidsoap uses to connect to Icecast. Injected into the Icecast container at startup. |
| `ICECAST_ADMIN_PASSWORD` | `hackme` | Password for the Icecast admin panel. Injected into the Icecast container at startup. |

> **Security note:** Change all `hackme` passwords before exposing your station to the internet.

### CORS

| Variable | Default | What It Does |
|----------|---------|-------------|
| `CORS_ALLOW_ORIGINS` | localhost origins for ports 8000 and 3000 | Comma-separated list of origins allowed to call the API from a browser. |

---

## 3. Station Settings (Web UI)

These are configured during setup and can be changed in the dashboard.

| Setting | Default | What It Does |
|---------|---------|-------------|
| **Timezone** | `UTC` | Your local timezone (e.g., `America/New_York`). Used for style scheduling and the DJ mentioning the time. |
| **Stream URL** | *(from .env)* | The Icecast stream URL shown in the dashboard player. |
| **Disk Retention Days** | `30` | How many days played tracks are kept in the archive before being deleted. |
| **Buffer Target** | `5` | How many tracks the station tries to keep ready at all times. Higher = more resilient but uses more disk space and API calls. |
| **Buffer Warning Threshold** | `2` | Dashboard shows a warning when ready tracks drop below this number. |

---

## 4. DJ Configuration (Web UI)

Editable on the **DJ Config** page. Changes take effect on the next DJ break.

| Setting | Default | What It Does |
|---------|---------|-------------|
| **Station Name** | *(from setup)* | Your station's name, used in the stream metadata and by the DJ. |
| **DJ Name** | *(from setup)* | The name your DJ uses on air. |
| **Personality Prompt** | *(from setup)* | A text description telling the AI how your DJ should talk. The more detail, the more unique. |
| **Voice Provider** | `fish_audio` | Which voice service renders DJ scripts to audio. |
| **Voice ID** | *(from setup)* | Which specific voice to use from the selected provider. |
| **Voice Settings** | `{}` | Advanced: JSON settings like `{"stability": 0.5, "similarity_boost": 0.75}`. |
| **Break Frequency** | `3` | How many songs play between DJ breaks. Lower = more DJ talking. |
| **Break Frequency Variance** | `1` | Adds randomness so breaks don't happen at exact intervals. A variance of 1 means breaks happen every 2-4 songs instead of exactly every 3. |
| **Mention Time** | `true` | Whether the DJ mentions what time it is during breaks. Gives a "live radio" feel. |
| **Content Policy** | `clean_vocals` | Controls what kind of lyrics appear in generated music. See below. |
| **Max Break Duration** | `60` | Maximum length of a DJ break in seconds. |

Validation: break frequency must be 1-20, variance 0-20, content policy must be `instrumental_only`, `clean_vocals`, or `no_restrictions`, and max break duration must be 1-600 seconds.

### Content Policy Options

The content policy adds text to every music generation prompt to control lyrical content:

| Policy | What It Does | Text Added to Prompts |
|--------|-------------|----------------------|
| **Instrumental Only** | No singing or lyrics at all | "Instrumental only, no vocals." |
| **Clean Vocals** | Singing allowed, but nothing explicit | "Clean vocals only, no explicit content." |
| **No Restrictions** | No filtering | *(nothing added)* |

You can override the automatic text with a custom policy suffix in the advanced section of the DJ Config page.

---

## 5. Music Styles (Web UI)

Managed on the **Styles** page. Each style has:

| Field | What It Does |
|-------|-------------|
| **Name** | A label for you (e.g., "Late Night Ambient"). Not sent to the AI. |
| **Prompt** | The text description sent to the music AI (e.g., "ethereal ambient with lush pads and gentle drones"). |
| **Weight** | How often this style is chosen relative to others. Weight 2 plays twice as often as weight 1. Default: 1. |
| **Tags** | Comma-separated labels (e.g., "chill, ambient, focus"). The DJ can reference these when talking about the music. |
| **Schedule Start / End** | Optional time window. If set, this style only plays during these hours (in your station's timezone). |
| **Active** | Toggle to enable/disable without deleting. |

Validation: name and prompt cannot be blank, and weight must be greater than 0.

### How style selection works

When your station needs a new track:

1. Filters to only **active** styles
2. Filters by **time-of-day schedule** (if set)
3. Excludes the **most recently used style** (no back-to-back repeats)
4. Picks randomly, weighted by the **weight** field

---

## 6. Announcements (Web UI)

Managed on the **Announcements** page. Announcements are messages your DJ works into their breaks naturally.

| Field | What It Does |
|-------|-------------|
| **Text** | The announcement content. Your DJ will paraphrase this naturally — it won't be read verbatim. |
| **Priority** | How urgently it should be mentioned: `low`, `normal`, `high`, or `urgent`. Higher priority = mentioned sooner and more often. |
| **Active** | Toggle to enable/disable. |
| **Expires At** | Optional date/time. The announcement automatically stops after this. |
| **Max Plays** | Optional limit. The announcement stops after being included in this many DJ breaks. |
| **Play Count** | How many times it's been used so far (read-only). |

Validation: text cannot be blank, priority must be `low`, `normal`, `high`, or `urgent`, and max plays must be at least 1 when set.

---

## 7. Show Schedule (Web UI)

Managed on the **Shows** page. Shows define scheduled programming blocks.

| Field | What It Does |
|-------|-------------|
| **Name** | A label for the block (e.g., "Morning Drive", "Late Night Jazz"). |
| **Play Duration** | How many minutes the block runs before the next one takes over. |
| **Order** | Position in the loop. Blocks play in this order and repeat. |
| **Music Styles** | Which styles this block draws from. Leave empty to use all active styles. |
| **DJ Personality Config** | Optionally override the station-default DJ persona for this block. |
| **Active** | Toggle to enable/disable without deleting. |

Validation: duration must be 1-1440 minutes; queue order cannot be negative.

When no blocks are scheduled, the station runs with the station-default styles and DJ. You don't need to create any blocks if you just want music.

---

## 8. Call-in Configuration (Roadmap)

> **Not yet implemented.** Listener call-in (Twilio telephony, a Calls page, and a real-time conversation AI) is a planned feature and has no settings in the current release.

---

## 9. Audio Standards

All audio is processed through the audio pipeline before entering any queue. This ensures consistent quality across AI-generated tracks, DJ breaks, and fallback audio.

| Property | Value | Why |
|----------|-------|-----|
| **Sample Rate** | 48,000 Hz | Broadcast standard quality |
| **Bit Depth** | 16-bit | Standard for streaming |
| **Channels** | Stereo | Two-channel audio |
| **Internal Format** | WAV | Lossless for processing |
| **Loudness Target** | -14 LUFS (EBU R128) | Consistent volume between tracks |
| **Normalization** | Two-pass FFmpeg `loudnorm` | Accurate loudness measurement and correction |
| **Silence Trimming** | Below -50 dB, 0.5s padding | Removes dead air at track starts/ends |
| **Stream Format** | MP3 192 kbps | Efficient for internet streaming |

You don't need to configure any of this — it's applied automatically to everything.

---

## 10. Rate Limits

Each AI provider has built-in rate limiting to avoid being throttled or banned:

| Provider | Max Calls/Min | Min Time Between Calls | Retries | Max Backoff |
|----------|:------------:|:---------------------:|:-------:|:----------:|
| **Suno** (Music) | 5 | 15 seconds | 2 | 2 minutes |
| **Gemini** (Scripts) | 15 | 4 seconds | 2 | 30 seconds |
| **Fish Audio** (Voice) | 10 | 2 seconds | 2 | 1 minute |

When a provider returns a rate limit error (HTTP 429), the backoff period increases exponentially with randomized jitter. After a successful call, the backoff resets to normal.

You don't need to configure rate limits — they're built into each provider.

---

## 11. Background Loops

The station runs several background tasks that check on things periodically:

| Loop | Runs Every | What It Does |
|------|:----------:|-------------|
| **Buffer Check** | 30 seconds | Checks if the music queue is below target and triggers generation |
| **Playout Check** | 5 seconds | Queues the next track in Liquidsoap, triggers DJ breaks at the right time |
| **Show Transition** | 30 seconds | Detects block changes (start/end), emits events, queues the block intro |
| **Cleanup** | 1 hour | Archives played tracks, deletes old files, checks disk space |

Each loop has independent error recovery. If one fails, it backs off gradually (up to 10x the normal interval) to avoid hammering broken services, while the other loops continue normally.

---

## 12. Docker & Infrastructure

### Audio Directories

| Path | What's Stored | Managed By |
|------|--------------|-----------|
| `audio/tracks/` | AI-generated music waiting to play | Buffer manager |
| `audio/breaks/` | DJ break audio files | DJ brain |
| `audio/fallback/` | Emergency audio (you must add at least 1 file) | You |
| `audio/archive/` | Played tracks (auto-cleaned per retention policy) | Cleanup loop |

### Icecast Settings

The Icecast config is at `icecast/icecast.xml`:

| Setting | Default | What It Does |
|---------|---------|-------------|
| **Max Clients** | 100 | Maximum simultaneous listeners |
| **Max Sources** | 2 | Maximum audio sources (Liquidsoap connections) |
| **Mount Point** | `/stream` | URL path for the stream |
| **Burst on Connect** | Enabled | Sends buffered audio immediately when a listener connects (reduces initial wait) |
| **CORS** | Allow all origins (`*`) | Lets the dashboard's embedded player access the stream |

### Liquidsoap Settings

The Liquidsoap config is at `liquidsoap/station.liq`:

| Setting | Value | What It Does |
|---------|-------|-------------|
| **Telnet Port** | 1234 | Control interface for the app to queue tracks |
| **Queue Source** | `request.queue` | The app pushes tracks through this |
| **Harbor Input** | Port 8005 | Live caller audio input (reserved for the call-in roadmap feature) — highest priority source in the chain. Not published outside the Docker network. |
| **Fallback** | `/audio/fallback/` | Directory scanned for emergency audio |
| **Crossfade** | 3 seconds | Smooth transitions between tracks |
| **Output** | MP3 192 kbps | Stream format sent to Icecast |
| **Error Recovery** | 3 second retry | Automatically reconnects to Icecast on failure |

The source priority chain is: **live caller input** > **queued tracks/segments** > **fallback audio** > **silence**. When a caller goes live on air, their audio takes over the stream automatically.
