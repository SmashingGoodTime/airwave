# AI Radio DJ

An AI-powered radio station that runs itself. It creates original music, writes DJ scripts, speaks them in a realistic voice, and streams everything live — all from one command.

(**Listener Call-in** — real callers talking to your AI host on air — is on the roadmap; see [Listener Call-in](#7-listener-call-in-roadmap).)

No music library needed. No recording equipment. No experience required.

---

## Table of Contents

1. [What Is This?](#1-what-is-this)
2. [How It Works](#2-how-it-works)
3. [What You'll Need](#3-what-youll-need)
4. [Getting Started](#4-getting-started)
5. [The Setup Wizard](#5-the-setup-wizard)
6. [Using Your Station](#6-using-your-station)
7. [Listener Call-in (Roadmap)](#7-listener-call-in-roadmap)
8. [Development Setup](#8-development-setup)
9. [Project Structure](#9-project-structure)
10. [API Reference](#10-api-reference)
11. [Tech Stack](#11-tech-stack)
12. [Security](#12-security)
14. [Further Reading](#14-further-reading)
15. [License](#15-license)

---

## 1. What Is This?

AI Radio DJ is a complete, self-running radio station powered by artificial intelligence. Once you set it up, it:

- **Creates original music** from text descriptions you provide (e.g., "relaxing lo-fi hip hop with piano")
- **Writes DJ scripts** — natural, conversational breaks between songs
- **Speaks the scripts** in a realistic AI-generated voice
- **Streams everything live** as a continuous broadcast anyone can listen to
- **Manages itself** — generates new music when the queue gets low, rotates styles, handles errors

You control the station through a web dashboard where you can change the music style, update your DJ's personality, add announcements, and monitor everything in real time.

---

## 2. How It Works

```
  You configure styles          AI generates music         Listeners tune in
  and DJ personality     -->    and DJ breaks         -->  to the live stream
       (Web UI)              (runs automatically)           (any device)
```

Behind the scenes:

```
+------------------------------------------------------+
|                   Web Dashboard                       |
|              (your control panel)                     |
+------------------------------------------------------+
|                  FastAPI Backend                       |
|                                                       |
|  Scheduler  -->  Music Buffer  -->  Playout Queue     |
|      |                |                   |           |
|  DJ Brain   -->  Script + Voice           |           |
|      |                                    v           |
|      +---------------------------->  Liquidsoap       |
|                                           |           |
|                                       Icecast         |
|                                           |           |
|                                     Live Stream       |
+------------------------------------------------------+
```

**The AI services:**

| Service | What It Does | Default Provider |
|---------|-------------|-----------------|
| Music Generation | Creates original songs from your style descriptions | [Suno](https://suno.com) |
| Script Writing | Writes the DJ scripts between songs | [Google Gemini](https://aistudio.google.com) |
| DJ Voice | Speaks the DJ scripts in a realistic voice | [Fish Audio](https://fish.audio) |

---

## 3. What You'll Need

### Required

- **Docker and Docker Compose** — This packages everything so you don't have to install a dozen things separately. [Get Docker here](https://docs.docker.com/get-docker/).

### Recommended (for full functionality)

- **A Suno account** — For music generation. [Sign up at suno.com](https://suno.com)
- **A Google AI Studio account** — For DJ script writing. [Sign up at aistudio.google.com](https://aistudio.google.com)
- **A Fish Audio account** — For the DJ's voice. [Sign up at fish.audio](https://fish.audio)

Each service has a free tier you can start with. You'll need an **API key** from each one — the setup wizard will show you exactly where to find them.

> **Don't have API keys yet?** That's fine. You can start the station without them and add keys later through the settings page. The station just won't generate content until at least the music key is added.

---

## 4. Getting Started

### Step 1: Download the project

```bash
git clone https://github.com/SmashingGoodTime/ai-radio-dj.git
cd ai-radio-dj
```

### Step 2: Create your environment file

```bash
cp .env.example .env
```

This step is **required** — Docker Compose mounts `.env` into the app container so API keys entered through the setup wizard are saved back to it. You can edit `.env` to add API keys now, or enter them through the setup wizard instead.

While you're here, change the `ICECAST_SOURCE_PASSWORD`, `ICECAST_ADMIN_PASSWORD`, and `HARBOR_SOURCE_PASSWORD` values from their `hackme` defaults (see [Security](#13-security)).

### Step 3: Create the data directory

The station stores its database in a `data/` folder on your machine, so your settings survive container upgrades:

```bash
mkdir -p data
```

Emergency audio is already handled — `audio/fallback/` ships with one track that plays if music generation is ever slow or unavailable, so the station will not go silent on a fresh install. To use your own material instead, drop any MP3 or WAV files into that folder; see [audio/fallback/README.md](audio/fallback/README.md).

### Step 4: Start your station

```bash
docker-compose up
```

This starts three services:

| Service | What It Does | URL |
|---------|-------------|-----|
| **App** | Web dashboard + API | http://localhost:8000 |
| **Liquidsoap** | Audio mixing and playout | (internal) |
| **Icecast** | Live stream server | http://localhost:8080/stream |

Wait for the log message: `AI Radio DJ backend ready`

### Step 5: Open the setup wizard

Go to **http://localhost:8000** in your browser. The setup wizard will walk you through everything.

---

## 5. The Setup Wizard

The first time you open your station, a step-by-step wizard guides you through configuration. Here's what each step does:

### Step 1: Station Identity

Give your station a name (e.g., "Sunset Radio", "The Chill Zone") and pick your timezone. The timezone is used for scheduling — so you can play different music at different times of day.

### Step 2: AI Services

Connect the three AI services that power your station. For each one, you'll paste an API key — a long string of characters that acts like a password. The wizard has links to each service's website where you can create an account and find your key.

All three services are optional. You can skip any of them and add keys later.

### Step 3: DJ Persona

Name your DJ and describe their personality. Are they laid-back and chill? Energetic and funny? The personality description shapes how your DJ talks between songs. There's an example you can use as a starting point.

You'll also pick a content policy:
- **Instrumental Only** — Music without singing
- **Clean Vocals** — Songs with singing, but nothing explicit
- **No Restrictions** — Anything goes

### Step 4: Music Styles

Tell the AI what kind of music to create. Each "style" is a text description like "relaxing lo-fi hip hop with mellow piano and soft drums." The wizard has preset styles you can add with one click, or write your own.

Your station will randomly pick from these styles when generating new music.

### Step 5: Review & Launch

Review everything and hit **Start Broadcasting**. Your station begins generating music immediately.

---

## 6. Using Your Station

### The Dashboard

Once your station is running, the dashboard shows you everything at a glance:

- **Now Playing** — The current track with a progress bar
- **Music Queue** — How many songs are ready to play (green = healthy, red = running low)
- **AI Services** — Whether each service is connected and working
- **Listen Live** — An embedded player so you can hear your station
- **Recent Plays** — A scrolling log of everything that's played

The dashboard updates in real time — you don't need to refresh.

### Managing Music Styles

Go to the **Styles** page to add, edit, or remove music styles. You can:

- Add new styles anytime — they take effect immediately
- Set **weights** so some styles play more often than others
- Set **schedules** so certain styles only play at specific times (e.g., jazz at night)
- Toggle styles on/off without deleting them

### DJ Configuration

The **DJ Config** page lets you change:

- Your station name and DJ name
- The DJ's personality (how they talk)
- Their voice
- How often they talk between songs
- Content policy for generated music

### Announcements

The **Announcements** page lets you add messages your DJ will mention during breaks — like upcoming events, shout-outs, or promotions. You can set:

- **Priority** — How urgently the announcement should be mentioned
- **Max plays** — Stop mentioning it after a certain number of times
- **Expiration** — Automatically stop after a date

### Show Schedule

The **Shows** page lets you create scheduled program blocks. Each block sets how long it runs, which music styles it draws from, and which DJ persona hosts it. Blocks play in queue order and loop.

When no show is scheduled, the station runs with the station-default styles and DJ.

### Play Log

The **Play Log** page shows a complete history of everything your station has played. You can filter by date and export the log as a CSV file.

### Stopping Your Station

```bash
docker-compose down
```

Everything that matters lives on your machine, outside the containers:

- **`data/`** — the station database (settings, styles, play history)
- **`.env`** — API keys, including any entered through the setup wizard
- **`audio/`** — generated music, DJ breaks, and recordings

Next time you run `docker-compose up`, everything picks up where it left off — even after upgrading or rebuilding the containers.

---

## 7. Listener Call-in (Roadmap)

> **Not yet implemented.** Listener call-in is a planned feature — it is **not** in the current codebase. There is no Calls page, no `/api/calls/*` endpoints, and no Twilio or OpenAI integration yet.

The plan: let real listeners call a phone number (via Twilio) and talk to an AI host (via a realtime conversation API), either live on air or pre-recorded, screened, and played back later. Some groundwork already exists — the Liquidsoap config includes a harbor input reserved for live caller audio — but the call manager, telephony provider, and conversation AI are not built.

---

## 8. Development Setup

If you want to modify the code or run without Docker:

### Backend (Python)

```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
python -m server.main
```

The API starts at http://localhost:8000.

To also run the test suite, install `requirements-dev.txt` instead — it adds the test tooling on top of the runtime dependencies. See [CONTRIBUTING.md](CONTRIBUTING.md).

### Frontend (React)

```bash
cd frontend
npm install
npm run dev
```

The dev server starts at http://localhost:3000 with hot reload. API calls are proxied to port 8000.

### Build for Production

```bash
cd frontend
npm run build
```

The built files go to `frontend/dist/` and are served by FastAPI automatically.

---

## 9. Project Structure

```
ai-radio-dj/
├── server/                      # Python backend
│   ├── main.py                  # App entry point
│   ├── config.py                # Settings from .env
│   ├── database.py              # SQLite database
│   ├── models/                  # Data models (Track, Style, Show, etc.)
│   ├── routers/                 # API endpoints
│   │   ├── shows.py             #   Show schedule management
│   │   └── ...                  #   Styles, DJ, dashboard, etc.
│   ├── providers/               # AI service integrations
│   │   ├── music/suno.py        #   Music generation
│   │   ├── scriptwriter/google.py  # DJ break scripts
│   │   └── voice/fish.py        #   Text-to-speech
│   ├── engine/                  # Core station logic
│   │   ├── scheduler.py         #   Show-aware master orchestrator
│   │   ├── music_buffer.py      #   Track queue manager
│   │   ├── dj_brain.py          #   DJ break timing & context
│   │   └── playout.py           #   Liquidsoap interface
│   ├── events/                  # Real-time event system
│   └── utils/                   # Audio processing, rate limiting
├── frontend/src/                # React web dashboard
│   ├── pages/
│   │   ├── Shows.jsx            #   Show schedule management
│   │   └── ...                  #   Dashboard, Styles, DJ, etc.
├── liquidsoap/station.liq       # Audio playout config
├── icecast/icecast.xml          # Stream server config
├── data/                        # Station database (created on first run)
├── audio/                       # All audio files
│   ├── tracks/                  #   Generated music
│   ├── breaks/                  #   DJ break audio
│   ├── fallback/                #   Emergency audio
│   └── archive/                 #   Played tracks
└── docs/                        # Documentation
```

---

## 10. API Reference

All endpoints are under `/api/`. The web dashboard uses these same endpoints.

| Method | Endpoint | Description |
|--------|----------|-------------|
| **Setup** | | |
| GET | `/api/setup/status` | Check if first-run setup is complete |
| POST | `/api/setup/complete` | Save initial station configuration |
| **Music Styles** | | |
| GET | `/api/styles` | List all music styles |
| POST | `/api/styles` | Create a new style |
| PUT | `/api/styles/{id}` | Update a style |
| DELETE | `/api/styles/{id}` | Delete a style |
| POST | `/api/styles/{id}/toggle` | Enable or disable a style |
| **Announcements** | | |
| GET | `/api/announcements` | List all announcements |
| POST | `/api/announcements` | Create an announcement |
| PUT | `/api/announcements/{id}` | Update an announcement |
| DELETE | `/api/announcements/{id}` | Delete an announcement |
| **DJ Configuration** | | |
| GET | `/api/dj/config` | Get current DJ settings |
| PUT | `/api/dj/config` | Update DJ settings |
| POST | `/api/dj/preview` | Generate a test DJ break |
| GET | `/api/dj/voices` | List available AI voices |
| **Shows** | | |
| GET | `/api/shows` | List all scheduled shows |
| POST | `/api/shows` | Create a show |
| PUT | `/api/shows/{id}` | Update a show |
| DELETE | `/api/shows/{id}` | Delete a show |
| POST | `/api/shows/{id}/toggle` | Enable or disable a show |
| GET | `/api/shows/active` | Get the currently active show |
| **Dashboard** | | |
| GET | `/api/dashboard/status` | Current station status (includes active show) |
| GET | `/api/dashboard/health` | AI service health check |
| GET | `/api/dashboard/recent` | Recently played items |
| WS | `/api/dashboard/ws` | Real-time status updates |
| **Play Log** | | |
| GET | `/api/playlog` | Play history (paginated) |
| GET | `/api/playlog/export` | Download history as CSV |
| **Stream** | | |
| GET | `/api/stream/url` | Get the live stream URL |

---

## 11. Tech Stack

| What | Technology |
|------|-----------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy, SQLite |
| Frontend | React 18, Vite |
| Music AI | Suno API |
| Script AI | Google Gemini API |
| Voice AI | Fish Audio API |
| Audio Processing | FFmpeg |
| Audio Playout | Liquidsoap 2.2 |
| Live Streaming | Icecast 2.4 |
| Packaging | Docker, Docker Compose |

---

## 12. Security

A few things to know before running the station anywhere other than your own machine:

- **The control API is unauthenticated.** Anyone who can reach port 8000 can reconfigure your station, read your play history, and trigger paid AI generations. On a shared or public network, bind the port to localhost (change the compose mapping to `"127.0.0.1:8000:8000"`) or put a firewall / reverse proxy with authentication in front of it.
- **Change the default passwords.** Set real values for `ICECAST_SOURCE_PASSWORD`, `ICECAST_ADMIN_PASSWORD`, and `HARBOR_SOURCE_PASSWORD` in `.env` — the `hackme` defaults are placeholders. Anyone with the source password can hijack your stream.
- **Only the stream needs to be public.** Port 8080 (Icecast) is the only thing listeners need. Liquidsoap's telnet and harbor ports are intentionally not published outside the Docker network.
- **`.env` holds your API keys.** It is ignored by git — keep it that way, and don't paste it into bug reports.

---

## 14. Further Reading

- **[Getting Started Guide](docs/quickstart.md)** — Detailed walkthrough from zero to a running station
- **[Configuration Reference](docs/configuration.md)** — Every setting explained
- **[Architecture Direction](docs/architecture.md)** — How the station is moving toward timeline-based broadcast automation
- **[Adding Providers](docs/adding-providers.md)** — How to add new AI services (for developers)
- **[Contributing](CONTRIBUTING.md)** — How to contribute to the project

---

## 15. License

MIT — Use it however you like.
