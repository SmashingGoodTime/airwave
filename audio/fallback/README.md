# Fallback audio

Emergency audio for dead-air protection. Liquidsoap plays these files in
random order whenever the queue is empty — when music generation is slow,
a provider is down, or the station has just started with an empty buffer.

**Never leave this directory empty.** It is the last line of defence before
silence goes out on the air.

## Adding your own

Drop any `.mp3` or `.wav` file in here. Both the startup normalizer and the
dead-air handler pick up either extension, and Liquidsoap watches the
directory, so no restart is needed to add files.

On startup each file is loudness-normalized into `normalized/` so dead-air
playback matches the rest of the broadcast. That cache is generated at
runtime and is not tracked by git. It is keyed by filename stem, so if you
replace `song.mp3` with a different track of the same name, delete the stale
`normalized/song.wav` to force it to be regenerated.

Longer, loopable, low-key instrumental tracks work best — this audio plays
precisely when something has gone wrong, and may repeat for a while.

## Bundled track

`Bloghouse.mp3` ships with the project so a fresh install has working
dead-air protection out of the box. It is AI-generated. Replace it with your
own material whenever you like — nothing in the station depends on this
specific file.
