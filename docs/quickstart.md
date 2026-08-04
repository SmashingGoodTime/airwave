# Getting Started Guide

A detailed walkthrough to get your AI radio station up and running. If you just want the short version, see the [Quick Start section in the README](../README.md#4-getting-started).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Installation](#2-installation)
3. [Getting Your API Keys](#3-getting-your-api-keys)
4. [Configuration](#4-configuration)
5. [Starting Your Station](#5-starting-your-station)
6. [The Setup Wizard](#6-the-setup-wizard)
7. [Listening to Your Station](#7-listening-to-your-station)
8. [How Your Station Runs Itself](#8-how-your-station-runs-itself)
9. [Monitoring with the Dashboard](#9-monitoring-with-the-dashboard)
10. [Setting Up Talk Shows](#10-setting-up-talk-shows)
11. [Listener Call-in (Roadmap)](#11-listener-call-in-roadmap)
12. [Stopping and Restarting](#12-stopping-and-restarting)
13. [Troubleshooting](#13-troubleshooting)
14. [Next Steps](#14-next-steps)

---

## 1. Prerequisites

### Docker (required)

Docker packages your station into containers so you don't need to install Python, Node.js, FFmpeg, Liquidsoap, or Icecast separately. Everything is included.

**Install Docker:**
- **Windows**: [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/)
- **Mac**: [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/)
- **Linux**: [Docker Engine for Linux](https://docs.docker.com/engine/install/)

After installing, verify it works:

```bash
docker --version
docker-compose --version
```

### API Keys (recommended)

Your station uses three AI services. Each one needs an API key — a long string of characters that lets the app connect to the service. You can get all three for free, and you can add them later if you want to start exploring first.

---

## 2. Installation

### Download the project

```bash
git clone https://github.com/SmashingGoodTime/ai-radio-dj.git
cd ai-radio-dj
```

### Create the environment file

```bash
cp .env.example .env
```

This creates a file called `.env` where your API keys and settings will live. This step is **required** — Docker Compose mounts the file into the app container so keys entered through the setup wizard are saved back to it. You can edit it now or enter keys through the web interface later.

### Create the data directory

```bash
mkdir -p data
```

The station's database lives here on your machine, so your settings and play history survive container upgrades.

### Emergency fallback audio

If AI music generation is ever slow or unavailable, the station plays fallback audio instead of going silent. One track ships in `audio/fallback/`, so this already works on a fresh install — there is nothing to do here.

To use your own material, copy any MP3 or WAV files into `audio/fallback/`. Royalty-free ambient or background music works well, and even a 30-second loop is fine — it's only a safety net. See [audio/fallback/README.md](../audio/fallback/README.md) for details.

---

## 3. Getting Your API Keys

An API key is like a password that lets your station connect to an AI service. Here's how to get each one:

### Suno (Music Generation)

Suno creates the original music for your station.

1. Go to [suno.com](https://suno.com) and create an account
2. Navigate to your account settings or API section
3. Generate an API key
4. Copy the key — it looks something like `sk-suno-abc123def456...`

### Google Gemini (DJ Script Writing)

Google Gemini writes what your DJ says between songs and generates talk show segments.

1. Go to [aistudio.google.com](https://aistudio.google.com) and create an account
2. Open **Get API key**
3. Create or select a project
4. Copy the generated API key

### Fish Audio (DJ Voice)

Fish Audio converts your DJ's scripts into spoken audio with a realistic voice.

1. Go to [fish.audio](https://fish.audio) and create an account
2. Open your account or developer settings
3. Create and copy an API key

### Adding your keys

You have two options:

**Option A: Edit the `.env` file**

Open `.env` in any text editor and paste your keys:

```env
SUNO_API_KEY=your_suno_key_here
GOOGLE_API_KEY=your_google_ai_key_here
FISH_AUDIO_API_KEY=your_fish_audio_key_here
```

**Option B: Enter them in the setup wizard**

Just start the station and paste your keys into the web interface. This is usually easier for first-time setup.

---

## 4. Configuration

The `.env` file has a few settings you might want to change. Most people can leave everything at the defaults.

```env
# Server
HOST=0.0.0.0
PORT=8000

# Stream passwords
ICECAST_SOURCE_PASSWORD=hackme
ICECAST_ADMIN_PASSWORD=hackme
HARBOR_SOURCE_PASSWORD=hackme
```

> **Important:** If anyone outside your local network will access your station, change all passwords from `hackme` to something secure. Also note that the control API on port 8000 has no authentication — see the [Security section in the README](../README.md#13-security).

For a complete list of every setting, see the [Configuration Reference](configuration.md).

---

## 5. Starting Your Station

```bash
docker-compose up
```

You'll see logs from three services starting up:

```
app-1         | AI Radio DJ backend ready
liquidsoap-1  | Ready!
icecast-1     | Listening on port 8080
```

The first startup takes a few minutes as Docker downloads the required images. Future startups are much faster.

> **Tip:** Add `-d` to run in the background: `docker-compose up -d`. View logs anytime with `docker-compose logs -f`.

---

## 6. The Setup Wizard

Open your browser to **http://localhost:8000**.

The first time you visit, the setup wizard guides you through five steps:

### Step 1: Station Identity

- **Station Name**: What listeners see (e.g., "Sunset Radio", "KAIX FM")
- **Timezone**: Used for scheduling music by time of day

### Step 2: AI Services

Paste your API keys here, or skip to add them later. The wizard explains what each service does and has links to sign up. A green checkmark appears next to each key you enter.

### Step 3: DJ Persona

- **DJ Name**: What your DJ calls themselves on air
- **Personality**: A text description of how your DJ talks. Be specific — "laid-back and friendly with a dry sense of humor" gives better results than just "cool."
- **Content Policy**: Choose whether music has vocals, and if so, whether to keep it clean

### Step 4: Music Styles

Add the types of music you want your station to play. You can:
- Click preset buttons to instantly add common styles (Lo-fi Chill, Classic Rock, Jazz Lounge, etc.)
- Write your own custom descriptions
- Add as many styles as you want

**Tips for writing good style descriptions:**
- Be specific: "relaxing lo-fi hip hop with mellow piano, vinyl crackle, and soft drums" works better than "chill music"
- Mention instruments, mood, tempo, and era
- The more detail you give, the more unique the results

### Step 5: Review & Launch

Check everything looks right and click **Start Broadcasting**. Your station immediately begins generating its first batch of music.

---

## 7. Listening to Your Station

Once music starts generating, you can listen in several ways:

### In the dashboard

The dashboard at http://localhost:8000 has a built-in audio player under "Listen Live."

### Direct stream URL

Point any media player at:

```
http://localhost:8080/stream
```

This works in VLC, iTunes, web browsers, or any app that plays internet radio.

### Share with others

If your computer is accessible on your network, others can listen using your computer's IP address instead of `localhost` (e.g., `http://192.168.1.100:8080/stream`).

---

## 8. How Your Station Runs Itself

Once you finish setup, the station operates autonomously. Here's what happens behind the scenes:

### Music Generation Loop (every 30 seconds)

1. The **buffer manager** checks how many tracks are ready to play
2. If the queue is below the target (default: 5 tracks), it picks a music style
3. Style selection considers: weights (higher = more likely), time-of-day schedule, and recent history (avoids repeating the same style)
4. The style description is sent to **Suno**, which generates a full song
5. The song is **normalized** to consistent volume (-14 LUFS) and converted to a standard format
6. The track enters the **ready queue**

### DJ Break Loop

1. The system counts songs played since the last DJ break
2. When it's time for a break (default: every 3 songs, with some randomness):
   - The **DJ Brain** gathers context: recent track titles, active announcements, current time, station identity
   - **Gemini** writes a natural script based on the context and DJ personality
   - **Fish Audio** converts the script to spoken audio
   - The audio is normalized and queued between songs

### Playout Loop (every 5 seconds)

1. Checks if **Liquidsoap** needs a new track
2. Queues the next ready track or DJ break
3. Updates the stream metadata (what's playing now)
4. If no tracks are available, activates **fallback audio** to prevent silence

### Cleanup Loop (every hour)

1. Archives played tracks to `audio/archive/`
2. Deletes archived files older than the retention period (default: 30 days)
3. Checks available disk space and warns if running low

---

## 9. Monitoring with the Dashboard

The dashboard at http://localhost:8000 updates in real time:

| Section | What It Shows |
|---------|--------------|
| **Active Show** | The current show name and type (shown when a show is scheduled) |
| **Now Playing** | Current track with title, style, and progress bar |
| **Music Queue** | How many songs are ready. Green = healthy, yellow = getting low, red = critically low |
| **Talk Segment Buffer** | How many talk segments are ready (shown during talk/hybrid shows) |
| **AI Services** | Connection status for each AI service (music, scripts, voice, telephony, conversation AI) |
| **Listen Live** | Embedded audio player for your stream |
| **Recent Plays** | Scrolling history of tracks, DJ breaks, and talk segments |

If you see the Music Queue dropping to zero, it means music generation can't keep up. Check the AI Services panel — if the music service shows "Error" or "Needs API key", that's the issue.

---

## 10. Setting Up Talk Shows

Once your basic station is running, you can add talk shows:

### Step 1: Create a Talk Show Config

Go to the **Talk Shows** page and click "Add Config". Set up:
- A name for the config
- Host voice ID (from your voice provider)
- Host personality prompt — describe how the host speaks
- Optionally add co-host voices for multi-speaker segments

### Step 2: Add Topics

With your config selected, click "Add Topic" and provide:
- **Title** — What the topic is about
- **Prompt** — Detailed instructions for the AI (the more detail, the better)
- **Type** — Monologue, conversation, debate, or interview
- **Weight** — How often this topic should come up

### Step 3: Schedule the Show

Go to the **Shows** page and create a new show:
- Set the type to "Talk"
- Choose your time window and days
- Link it to your talk show config
- Set priority (higher = takes precedence over overlapping shows)

The station will automatically switch to talk mode during the scheduled time.

---

## 11. Listener Call-in (Roadmap)

> **Not yet implemented.** Listener call-in — real people calling a phone number and talking to your AI host — is a planned feature. There is no Calls page or telephony integration in the current release. Talk shows (above) are the way to put AI voices on air today.

---

## 12. Stopping and Restarting

### Stop your station

```bash
docker-compose down
```

Everything is saved on your machine, outside the containers: the database in `data/`, API keys in `.env`, and audio in `audio/`.

### Restart your station

```bash
docker-compose up
```

Everything picks up where it left off. Previously generated tracks are still in the queue.

### View logs

```bash
docker-compose logs -f        # All services
docker-compose logs -f app    # Just the main app
```

---

## 13. Troubleshooting

### "No music is playing"

1. Check the **Music Queue** on the dashboard — is it at 0?
2. Check **AI Services** — is Music Generation showing "Connected"?
3. Verify your Suno API key is correct
4. Check the logs: `docker-compose logs app | tail -50`
5. Music generation takes 1-3 minutes per track. A brand new station needs a few minutes to build up its queue.

### "The DJ isn't talking"

1. Check if both **DJ Script Writer** and **DJ Voice** show "Connected" in AI Services
2. Verify your Google AI Studio and Fish Audio API keys
3. The DJ only talks after a certain number of songs (default: every 3). Wait for a few tracks.

### "I hear the same fallback audio on repeat"

This means the music queue is empty and no new tracks are being generated. Most likely cause: missing or invalid Suno API key. Check `docker-compose logs app` for error messages.

### "The stream URL doesn't work"

1. Make sure Icecast is running: `docker-compose logs icecast`
2. Try opening http://localhost:8080/stream directly in your browser
3. Check that Liquidsoap can reach Icecast: `docker-compose logs liquidsoap`

### "I'm getting rate limited / high API costs"

- Increase the buffer target in station settings (fewer, larger generation batches)
- Use the "Instrumental Only" content policy (sometimes cheaper)
- Increase the break frequency (fewer DJ breaks = fewer TTS API calls)
- All providers have built-in rate limiting, but if you're on a free tier, generation may be slow

### "The dashboard says 'Polling' instead of 'Live'"

This is normal — it means the WebSocket connection couldn't be established, so the dashboard falls back to polling every 15 seconds. Everything still works, just with a slight delay. This often happens behind reverse proxies that don't forward WebSocket connections.

---

### "Talk shows aren't generating segments"

1. Check that you have a **talk show config** with at least one **topic** added
2. Check that a **show** with type "Talk" is scheduled for the current time and day
3. Verify the **Google API key** is set - the script writer generates talk content
4. Verify the **Fish Audio API key** is set - voices render the scripts
5. Check the logs: `docker-compose logs app | grep talk`

---

## 14. Next Steps

Now that your station is running:

- **[Configuration Reference](configuration.md)** — Fine-tune every setting: buffer sizes, retention periods, audio quality, rate limits, and more
- **[Adding Providers](adding-providers.md)** — For developers: how to add new AI services or build custom integrations
- **[Contributing](../CONTRIBUTING.md)** — Help improve AI Radio DJ
