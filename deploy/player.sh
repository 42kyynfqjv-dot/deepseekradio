#!/bin/bash
# The Frequency — streamer. Drains audio_buffer/incoming into one persistent
# Icecast connection. A single long-lived ffmpeg encodes; an inner loop feeds it
# raw PCM from queued WAVs (oldest first), or the filler bed when the buffer is
# empty, so listeners never get disconnected between segments.
set -u
BUF="${BUF:-/opt/kaos/app/audio_buffer}"
FILLER="${FILLER:-/opt/kaos/filler.wav}"
RESERVE="${RESERVE:-/opt/kaos/reserve}"
MOUNT="${MOUNT:-live}"
: "${ICECAST_PW:?set ICECAST_PW (see /opt/kaos/stream.env)}"

mkdir -p "$BUF/incoming" "$BUF/played"

feed() {
  while true; do
    f=$(ls "$BUF"/incoming/*.wav 2>/dev/null | sort | head -1)
    if [ -n "$f" ]; then
      ffmpeg -v quiet -i "$f" -f s16le -ar 24000 -ac 1 - </dev/null
      mv "$f" "$BUF/played/"
      # keep only the last 50 played segments
      ls -t "$BUF"/played/*.wav 2>/dev/null | tail -n +51 | xargs -r rm -f
    else
      # buffer empty: no-repeat shuffled rotation through the reserve pool —
      # every piece airs once before anything repeats
      QUEUE="/tmp/frequency-reserve-queue"
      if [ ! -s "$QUEUE" ]; then
        ls "$RESERVE"/*.wav 2>/dev/null | shuf > "$QUEUE"
      fi
      r=$(head -1 "$QUEUE"); sed -i 1d "$QUEUE"
      if [ -n "$r" ] && [ -f "$r" ]; then
        ffmpeg -v quiet -i "$r" -f s16le -ar 24000 -ac 1 - </dev/null
      else
        ffmpeg -v quiet -i "$FILLER" -f s16le -ar 24000 -ac 1 - </dev/null
      fi
      sleep 1
    fi
  done
}

feed | ffmpeg -v warning -re -f s16le -ar 24000 -ac 1 -i - \
  -c:a libmp3lame -b:a 96k -content_type audio/mpeg -f mp3 \
  "icecast://source:${ICECAST_PW}@127.0.0.1:8000/${MOUNT}"
