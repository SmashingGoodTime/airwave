# AI Radio DJ

An AI-powered radio station that runs itself. It creates original music, writes DJ scripts, speaks them in a realistic voice, and streams everything live — all from one command.

Now with **Talk Show Mode** for all-talk AI broadcasts and **Listener Call-in** so real callers can talk to your AI host on air.

No music library needed. No recording equipment. No experience required.

---

## Table of Contents

1. [What Is This?](#1-what-is-this)
2. [How It Works](#2-how-it-works)
3. [What You'll Need](#3-what-youll-need)
4. [Getting Started](#4-getting-started)
5. [The Setup Wizard](#5-the-setup-wizard)
6. [Using Your Station](#6-using-your-station)
7. [Talk Shows](#7-talk-shows)
8. [Listener Call-in](#8-listener-call-in)
9. [Development Setup](#9-development-setup)
10. [Project Structure](#10-project-structure)
11. [API Reference](#11-api-reference)
12. [Tech Stack](#12-tech-stack)
13. [Further Reading](#13-further-reading)
14. [License](#14-license)

---

## 1. What Is This?

AI Radio DJ is a complete, self-running radio station powered by artificial intelligence. Once you set it up, it:

- **Creates original music** from text descriptions you provide (e.g., "relaxing lo-fi hip hop with piano")
- **Writes DJ scripts** — natural, conversational breaks between songs
- **Speaks the scripts** in a realistic AI-generated voice
- **Runs talk shows** — AI-hosted monologues, multi-voice conversations, debates, and interviews on topics you define
- **Takes live calls** — listeners call a real phone number and talk to an AI host, either live on air or pre-recorded and screened
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
|      |                                    |           |
|  Talk Engine --> Talk Segments             |           |
|      |                                    v           |
|  Call Manager --> Live/Recorded       Liquidsoap      |
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
| Script Writing | Writes DJ scripts and talk show segments | [Google Gemini](https://aistudio.google.com) |
| DJ Voice | Speaks the DJ scripts in a realistic voice | [Fish Audio](https://fish.audio) |
| Telephony | Handles incoming listener calls | [Twilio](https://twilio.com) *(optional)* |
| Conversation AI | Real-time voice conversation with callers | [OpenAI Realtime](https://openai.com) *(optional)* |

---

## 3. What You'll Need

### Required

- **Docker and Docker Compose** — This packages everything so you don't have to install a dozen things separately. [Get Docker here](https://docs.docker.com/get-docker/).

### Recommended (for full functionality)

- **A Suno account** — For music generation. [Sign up at suno.com](https://suno.com)
- **A Google AI Studio account** — For DJ script writing and talk shows. [Sign up at aistudio.google.com](https://aistudio.google.com)
- **A Fish Audio account** — For the DJ's voice. [Sign up at fish.audio](https://fish.audio)

Each service has a free tier you can start with. You'll need an **API key** from each one — the setup wizard will show you exactly where to find them.

### Optional (for call-in features)

- **A Twilio account** — For a real phone number that listeners can call. [Sign up at twilio.com](https://twilio.com)
- **An OpenAI account** — For the real-time conversation AI that talks to callers. [Sign up at openai.com](https://platform.openai.com)

> **Don't have API keys yet?** That's fine. You can start the station without them and add keys later through the settings page. The station just won't generate content until at least the music key is added. Talk shows work without Twilio — call-in is an optional add-on.

---

## 4. Getting Started

### Step 1: Download the project

```bash
git clone https://github.com/your-org/ai-radio-dj.git
cd ai-radio-dj
```

### Step 2: Create your environment file

```bash
cp .env.example .env
```

You can edit `.env` to add API keys now, or skip this and enter them through the setup wizard instead.

### Step 3: Add emergency audio

Your station needs at least one audio file to play if the AI music generation is slow or unavailable. Place any MP3 or WAV file in the fallback folder:

```bash
mkdir -p audio/fallback
# Copy any music file here — royalty-free background music works well
```

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

The **Shows** page lets you create scheduled show blocks. Each show has a type, time window, and days of the week:

- **Music** — Standard music programming (the default behavior)
- **Talk** — All-talk AI show with no music
- **Hybrid** — Alternates between music and talk segments

When no show is scheduled, the station runs in its default music mode. Shows with higher priority take precedence when time slots overlap.

### Play Log

The **Play Log** page shows a complete history of everything your station has played. You can filter by date and export the log as a CSV file.

### Stopping Your Station

```bash
docker-compose down
```

Your settings and audio files are saved. Next time you run `docker-compose up`, everything picks up where it left off.

---

## 7. Talk Shows

Talk shows let your station run all-talk AI programming — no music, just voices discussing topics you define.

### Setting Up a Talk Show

1. Go to the **Talk Shows** page and create a talk show config
2. Set up the host voice and personality (the main speaker)
3. Optionally add co-host voices for multi-voice conversations
4. Add topics — each topic has a prompt, type, and weight

### Topic Types

| Type | What It Sounds Like |
|------|-------------------|
| **Monologue** | A single host speaking on the topic |
| **Conversation** | Two or more voices discussing naturally |
| **Debate** | Opposing viewpoints on a subject |
| **Interview** | Host asks questions, guest responds |

### How It Works

The talk show engine selects topics based on weights (like music style selection), generates scripts via the script writer, renders each speaker's lines with the appropriate voice, and stitches the audio together. Segments are buffered ahead of time so there's no gap.

### Scheduling Talk Shows

Go to the **Shows** page and create a show with type "Talk". Link it to your talk show config, set the time window and days, and the scheduler handles the rest. When the show's time arrives, the station switches from music to talk automatically.

---

## 8. Listener Call-in

Let real listeners call your station and talk to an AI host. Requires a Twilio account.

### Two Modes

- **Live** — The caller's audio goes directly to the broadcast stream in real time
- **Pre-recorded** — The caller's conversation with the AI is recorded, screened by the operator, and played back later

### Setting Up Call-in

1. Add your Twilio credentials to `.env` (or enter them in settings):
   ```env
   TWILIO_ACCOUNT_SID=your_sid
   TWILIO_AUTH_TOKEN=your_token
   TWILIO_PHONE_NUMBER=+1234567890
   CALL_WEBHOOK_BASE_URL=https://your-public-url.com
   OPENAI_API_KEY=your_key
   ```
2. Go to the **Calls** page and configure call settings (max duration, moderation level, screening prompt)
3. Share the phone number with your listeners

### Call Flow

1. Listener calls the Twilio number
2. The AI screens the caller using the screening prompt you configured
3. The call appears in the **Calls** dashboard
4. For live mode: you approve and the caller goes on air immediately
5. For pre-recorded mode: the conversation is recorded, processed, and queued as a talk segment

### Content Moderation

- The AI host has guardrails in its system prompt
- You set a moderation level: `strict`, `moderate`, or `relaxed`
- Pre-recorded calls can be reviewed before airing
- Phone numbers are stored as SHA-256 hashes for privacy

### Without Twilio

Talk shows work without any telephony setup. Call-in is purely optional — if Twilio credentials aren't configured, the Calls page simply shows that telephony isn't set up.

---

## 9. Development Setup

If you want to modify the code or run without Docker:

### Backend (Python)

```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
python -m server.main
```

The API starts at http://localhost:8000.

### Frontend (React)

```bash
cd frontend
npm install
npm run dev
```

The dev server starts at http://localhost:5173 with hot reload. API calls are proxied to port 8000.

### Build for Production

```bash
cd frontend
npm run build
```

The built files go to `frontend/dist/` and are served by FastAPI automatically.

---

## 10. Project Structure

```
ai-radio-dj/
├── server/                      # Python backend
│   ├── main.py                  # App entry point
│   ├── config.py                # Settings from .env
│   ├── database.py              # SQLite database
│   ├── models/                  # Data models (Track, Style, Show, etc.)
│   ├── routers/                 # API endpoints
│   │   ├── shows.py             #   Show schedule management
│   │   ├── talk_shows.py        #   Talk config & topics
│   │   ├── calls.py             #   Call-in management & webhooks
│   │   └── ...                  #   Styles, DJ, dashboard, etc.
│   ├── providers/               # AI service integrations
│   │   ├── music/suno.py        #   Music generation
│   │   ├── scriptwriter/google.py  # DJ scripts + talk segments
│   │   ├── voice/fish.py        #   Text-to-speech
│   │   ├── telephony/twilio.py  #   Phone call handling
│   │   └── conversation/openai_realtime.py  # Real-time caller AI
│   ├── engine/                  # Core station logic
│   │   ├── scheduler.py         #   Show-aware master orchestrator
│   │   ├── music_buffer.py      #   Track queue manager
│   │   ├── dj_brain.py          #   DJ break timing & context
│   │   ├── talk_show.py         #   Talk segment generation engine
│   │   ├── call_manager.py      #   Incoming call lifecycle
│   │   └── playout.py           #   Liquidsoap interface
│   ├── events/                  # Real-time event system
│   └── utils/                   # Audio processing, rate limiting
├── frontend/src/                # React web dashboard
│   ├── pages/
│   │   ├── Shows.jsx            #   Show schedule management
│   │   ├── TalkShowConfig.jsx   #   Talk host/topic config
│   │   ├── CallDashboard.jsx    #   Live call management
│   │   └── ...                  #   Dashboard, Styles, DJ, etc.
├── liquidsoap/station.liq       # Audio playout config (with harbor input)
├── icecast/icecast.xml          # Stream server config
├── audio/                       # All audio files
│   ├── tracks/                  #   Generated music
│   ├── breaks/                  #   DJ break audio
│   ├── talks/                   #   Talk show segments
│   ├── calls/                   #   Call recordings (raw + processed)
│   ├── fallback/                #   Emergency audio
│   └── archive/                 #   Played tracks
└── docs/                        # Documentation
```

---

## 11. API Reference

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
| **Talk Shows** | | |
| GET | `/api/talk/configs` | List talk show configurations |
| POST | `/api/talk/configs` | Create a talk show config |
| PUT | `/api/talk/configs/{id}` | Update a talk show config |
| DELETE | `/api/talk/configs/{id}` | Delete a talk show config |
| GET | `/api/talk/configs/{id}/topics` | List topics for a config |
| POST | `/api/talk/topics` | Create a topic |
| PUT | `/api/talk/topics/{id}` | Update a topic |
| DELETE | `/api/talk/topics/{id}` | Delete a topic |
| GET | `/api/talk/segments` | List generated talk segments |
| POST | `/api/talk/preview` | Generate a preview talk segment |
| **Calls** | | |
| GET | `/api/calls/config` | Get call-in configuration |
| PUT | `/api/calls/config` | Update call-in configuration |
| GET | `/api/calls/active` | List active calls |
| POST | `/api/calls/{id}/approve` | Approve a screened call |
| POST | `/api/calls/{id}/reject` | Reject a call |
| POST | `/api/calls/{id}/end` | End an active call |
| GET | `/api/calls/history` | Call history |
| GET | `/api/calls/status` | Telephony provider status |
| POST | `/api/calls/webhook` | Twilio incoming call webhook |
| POST | `/api/calls/status-callback` | Twilio status callback |
| **Dashboard** | | |
| GET | `/api/dashboard/status` | Current station status (includes active show, call count) |
| GET | `/api/dashboard/health` | AI service health check (includes telephony, conversation AI) |
| GET | `/api/dashboard/recent` | Recently played items |
| WS | `/api/dashboard/ws` | Real-time status updates |
| **Play Log** | | |
| GET | `/api/playlog` | Play history (paginated) |
| GET | `/api/playlog/export` | Download history as CSV |
| **Stream** | | |
| GET | `/api/stream/url` | Get the live stream URL |

---

## 12. Tech Stack

| What | Technology |
|------|-----------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy, SQLite |
| Frontend | React 18, Vite |
| Music AI | Suno API |
| Script AI | Google Gemini API |
| Voice AI | Fish Audio API |
| Telephony | Twilio *(optional)* |
| Conversation AI | OpenAI Realtime API *(optional)* |
| Audio Processing | FFmpeg |
| Audio Playout | Liquidsoap 2.2 |
| Live Streaming | Icecast 2.4 |
| Packaging | Docker, Docker Compose |

---

## 13. Further Reading

- **[Getting Started Guide](docs/quickstart.md)** — Detailed walkthrough from zero to a running station
- **[Configuration Reference](docs/configuration.md)** — Every setting explained
- **[Architecture Direction](docs/architecture.md)** — How the station is moving toward timeline-based broadcast automation
- **[Adding Providers](docs/adding-providers.md)** — How to add new AI services (for developers)
- **[Contributing](CONTRIBUTING.md)** — How to contribute to the project

---

## 14. License

MIT — Use it however you like.
