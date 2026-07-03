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
# Secrets (from docker-compose environment)
# =====================
icecast_password = environment.get(default="hackme", "ICECAST_SOURCE_PASSWORD")
# Deliberately NOT "hackme": if the compose env var is absent, the harbor
# must not accept the well-known Liquidsoap default password.
harbor_password = environment.get(default="airadio-caller-secret", "HARBOR_SOURCE_PASSWORD")

# =====================
# Request Queue
# =====================
# The app pushes tracks and DJ breaks into this queue via telnet.
# request.queue(id="queue") registers exactly these server commands:
#   queue.push / queue.queue / queue.skip / queue.flush_and_skip
# Now-playing metadata arrives on each request via annotate: URIs
# (title/artist), added by the app at queue time.
queue = request.queue(id="queue")

# Silent-track protection: if a corrupt or all-silent file reaches the
# queue, skip it after 15s of continuous silence instead of airing dead
# air. Threshold -50dB matches the audio pipeline's silence-trim floor,
# so quiet-but-intentional ambient material is not skipped; DJ speech
# pauses never approach 15s.
queue = blank.skip(id="queue_blank_skip", threshold=-50.0, max_blank=15.0, queue)

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

# Silence as last resort. Default blank duration is -1 (a single endless
# track): a bounded duration would end a "track" every few seconds and
# make cross() churn through transitions while everything is empty.
silence_src = blank(id="silence")

# =====================
# Live Caller Input
# =====================
# Harbor input for live caller audio. The Python app bridges Twilio
# WebSocket audio to this endpoint for live on-air calls.
#
# The input only goes on air when caller_enabled is true. The app toggles
# it with the custom telnet commands below ("caller.set true|false"),
# registered via server.register (harbor inputs register no start/stop
# telnet commands of their own in 2.2.x).
caller_enabled = ref(false)

server.register(
  namespace="caller",
  description="Enable or disable the live caller input.",
  usage="set true|false",
  "set",
  fun (arg) -> begin
    if arg == "true" then
      caller_enabled := true
      "OK caller_enabled=true"
    elsif arg == "false" then
      caller_enabled := false
      "OK caller_enabled=false"
    else
      "ERROR usage: caller.set true|false"
    end
  end
)

server.register(
  namespace="caller",
  description="Show whether the live caller input is enabled.",
  "status",
  fun (_) -> if caller_enabled() then "on" else "off" end
)

caller_input = input.harbor(
  id="caller",
  port=8005,
  user="source",
  password=harbor_password,
  buffer=2.0,
  "/caller"
)

# Gate the caller behind the enabled flag so a connected-but-unapproved
# source can never take over the air.
caller_live = source.available(id="caller_gated", caller_input, {caller_enabled()})

# =====================
# Source Chain
# =====================
# Priority: live caller (when enabled) > queue > fallback playlist > silence
radio = fallback(
  id="radio",
  track_sensitive=false,
  [caller_live, queue, fallback_src, silence_src]
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
# Records the final mixed stream to hourly MP3 files, but only while
# recording is enabled. An output.file registers no start/stop telnet
# commands of its own in 2.2.x, so — like the caller — recording is gated
# by a flag toggled via a custom "recorder.set true|false" command and the
# output is fed a source that is only available when the flag is set.
# Files are saved as /audio/recordings/YYYY-MM-DD-HH.mp3
rec_dir = "/audio/recordings/"

recorder_enabled = ref(false)

server.register(
  namespace="recorder",
  description="Enable or disable local stream recording.",
  usage="set true|false",
  "set",
  fun (arg) -> begin
    if arg == "true" then
      recorder_enabled := true
      "OK recorder_enabled=true"
    elsif arg == "false" then
      recorder_enabled := false
      "OK recorder_enabled=false"
    else
      "ERROR usage: recorder.set true|false"
    end
  end
)

server.register(
  namespace="recorder",
  description="Show whether local recording is enabled.",
  "status",
  fun (_) -> if recorder_enabled() then "on" else "off" end
)

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

# Only carries audio while recording is enabled, so no file is written
# (and no empty file is created) while recording is off.
recorder_source = source.available(
  id="recorder_src", radio, {recorder_enabled()}
)

output.file(
  %mp3(bitrate=192),
  id="recorder",
  fallible=true,
  reopen_on_error=fun(_) -> 1.0,
  reopen_when=should_reopen,
  {rec_dir ^ time.string("%Y-%m-%d-%H") ^ ".mp3"},
  recorder_source
)

# =====================
# Icecast Output
# =====================
# Stream to the Icecast server as MP3 at 192kbps.
# id="radio_out" + register_telnet (default true) expose the output-level
# telnet commands the app relies on: radio_out.skip / radio_out.metadata /
# radio_out.remaining.
output.icecast(
  %mp3(bitrate=192),
  id="radio_out",
  host="icecast",
  port=8080,
  password=icecast_password,
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
