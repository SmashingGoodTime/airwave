# AI Radio DJ - Liquidsoap Station Configuration
# Liquidsoap v2.2.x

# =====================
# Server / Telnet
# =====================
settings.server.telnet.set(true)
settings.server.telnet.bind_addr.set("0.0.0.0")
settings.server.telnet.port.set(1234)

# =====================
# Logging
# =====================
settings.log.level.set(3)

# =====================
# Request Queue
# =====================
# The app pushes tracks and DJ breaks into this queue via telnet.
# "queue.push <filepath>" adds an item; items play in FIFO order.
queue = request.queue(id="queue")

# =====================
# Fallback Source
# =====================
# Emergency audio that plays when the queue is empty.
# Watches the directory for new files and plays them in random order.
fallback_src = playlist(
  id="fallback",
  mode="random",
  reload_mode="watch",
  "/audio/fallback/"
)

# Silence as last resort
silence_src = blank(id="silence", duration=1.0)

# =====================
# Live Caller Input
# =====================
# Harbor input for live caller audio. The Python app bridges
# Twilio WebSocket audio to this endpoint for live on-air calls.
caller_input = input.harbor(
  id="caller",
  port=8005,
  "/caller",
  buffer=2.0
)

# =====================
# Source Chain
# =====================
# Priority: live caller > queue > fallback playlist > silence
radio = fallback(
  id="radio",
  track_sensitive=false,
  [caller_input, queue, fallback_src, silence_src]
)

# =====================
# Crossfade
# =====================
# Smart crossfade: smooth transitions between music tracks, but NO
# crossfade into or out of DJ breaks so speech is never cut short.
# DJ breaks are tagged with liq_cross_duration="0" by the app.
def smart_crossfade(a, b)
  # If the outgoing or incoming item is a DJ break, do a simple
  # sequential transition (finish a, then start b) with a short
  # fade to avoid pops.
  a_cross = list.assoc(default="3.0", "liq_cross_duration", a.metadata)
  b_cross = list.assoc(default="3.0", "liq_cross_duration", b.metadata)
  if a_cross == "0" or b_cross == "0" then
    sequence([
      fade.out(duration=0.3, a.source),
      fade.in(duration=0.3, b.source)
    ])
  else
    # Normal music-to-music crossfade
    cross.smart(fade_in=1.5, fade_out=2.5, a, b)
  end
end

radio = cross(duration=3.0, smart_crossfade, radio)

# =====================
# Metadata Handling
# =====================
# Log metadata changes for debugging
radio = source.on_metadata(radio, fun(m) -> begin
  title = list.assoc(default="Unknown Title", "title", m)
  artist = list.assoc(default="Unknown Artist", "artist", m)
  log("Now playing: #{artist} - #{title}")
end)

# Track start logging
radio = source.on_track(radio, fun(m) -> begin
  fname = list.assoc(default="unknown", "filename", m)
  log("Track started: #{fname}")
end)

# =====================
# Local Recording Output
# =====================
# Records the final mixed stream to hourly MP3 files.
# Controlled via telnet: recorder.start / recorder.stop
# Files are saved as /audio/recordings/YYYY-MM-DD-HH.mp3
rec_dir = "/audio/recordings/"

# Track the current hour to detect when it changes (hourly file rotation)
last_rec_hour = ref(-1)

def should_reopen()
  current_hour = int_of_float(time() / 3600.0) mod 24
  if current_hour != last_rec_hour() then
    last_rec_hour := current_hour
    true
  else
    false
  end
end

output.file(
  %mp3(bitrate=192),
  id="recorder",
  fallible=true,
  reopen_on_error=fun(_) -> 1.0,
  reopen_when=should_reopen,
  {rec_dir ^ time.string("%Y-%m-%d-%H") ^ ".mp3"},
  radio
)

# =====================
# Icecast Output
# =====================
# Stream to the Icecast server as MP3 at 192kbps.
# The password, host, port, and mount are configured to match
# the Icecast container in docker-compose.
output.icecast(
  %mp3(bitrate=192),
  host="icecast",
  port=8080,
  password="hackme",
  mount="/stream",
  name="AI Radio DJ",
  description="AI-powered radio station",
  genre="Various",
  url="",
  icy_metadata=["artist", "title", "genre"],
  fallible=true,
  on_error=fun(msg) -> begin
    log("Icecast output error: #{msg}")
    3.0
  end,
  radio
)
