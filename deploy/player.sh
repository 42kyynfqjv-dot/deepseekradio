#!/bin/bash
# The Frequency — streamer. Drains audio_buffer/incoming into one persistent
# Icecast connection through a broadcast processing chain (I1). A single
# long-lived ffmpeg encodes; the feed loop supplies raw PCM from queued WAVs
# (oldest first), inserting a produced spot (ad/weather/traffic, SQLite
# rotation) roughly every 15 minutes, and falling back to the reserve pool +
# room tone when the buffer is empty. Music beds duck under dialogue when a
# bed exists for the show (I4 stage 2); missing beds degrade gracefully.
set -u
BUF="${BUF:-/opt/kaos/app/audio_buffer}"
APP="${APP:-/opt/kaos/app}"
FILLER="${FILLER:-/opt/kaos/roomtone.wav}"
RESERVE="${RESERVE:-/opt/kaos/reserve}"
BEDS="${BEDS:-/opt/kaos/beds}"
MOUNT="${MOUNT:-live}"
SPOT_EVERY="${SPOT_EVERY:-3600}"  # fallback only; breaks are host-announced
: "${ICECAST_PW:?set ICECAST_PW (see /opt/kaos/stream.env)}"

mkdir -p "$BUF/incoming" "$BUF/played"
QUEUE="$BUF/reserve-queue"
LAST_SPOT_FILE="$BUF/.last_spot"
[ -f "$LAST_SPOT_FILE" ] || date +%s > "$LAST_SPOT_FILE"
LAST_SHOW=""

show_of() {
  # 000000123_night-shift-the-quiet-part.wav -> night-shift (etc.)
  local n; n=$(basename "$1"); n=${n#*_}
  case "$n" in
    morning-scramble*) echo morning-scramble ;;
    refined-palate*)   echo refined-palate ;;
    complaints*)       echo complaints ;;
    the-handover*)     echo the-handover ;;
    culture-vulture*)  echo culture-vulture ;;
    night-shift*)      echo night-shift ;;
    static-hour*)      echo static-hour ;;
    dawn-patrol*)      echo dawn-patrol ;;
    *) echo "" ;;      # news/spots/unknown: no transition
  esac
}

bed_for() {
  # music under dialogue only where music belongs: the ambient dawn hour.
  # talk shows air clean — beds under conversation read as noise, not polish.
  case "$(basename "$1")" in
    *dawn-patrol*) ls "$BEDS/night"*.wav 2>/dev/null | shuf -n1 ;;
    *) echo "" ;;
  esac
}

play_file() {
  # decode one file to raw PCM; duck a music bed under dialogue when available
  local f="$1" bed
  bed=$(bed_for "$f")
  if [ -f "$bed" ]; then
    ffmpeg -v quiet -i "$f" -stream_loop -1 -i "$bed" -filter_complex \
      "[1:a]volume=0.3[bq];[bq][0:a]sidechaincompress=threshold=0.015:ratio=10:attack=40:release=900:makeup=1[duck];[0:a][duck]amix=inputs=2:duration=first:normalize=0[out]" \
      -map "[out]" -f s16le -ar 24000 -ac 1 - </dev/null
  else
    ffmpeg -v quiet -i "$f" -f s16le -ar 24000 -ac 1 - </dev/null
  fi
}

play_spot() {
  # least-recently-aired live spot from the SQLite rotation; returns 1 if none
  # guarded: never within 5 minutes of the previous break
  local row wav now last
  now=$(date +%s); last=$(cat "$LAST_SPOT_FILE" 2>/dev/null || echo 0)
  [ $((now - last)) -lt 300 ] && return 1
  row=$(python3 - << "PY"
import sqlite3, time
try:
    con = sqlite3.connect("/opt/kaos/app/station.db")
    r = con.execute("SELECT id, wav FROM spots WHERE retired=0 AND wav != '' "
                    "ORDER BY last_played ASC, plays ASC LIMIT 1").fetchone()
    if r:
        con.execute("UPDATE spots SET plays=plays+1, last_played=? WHERE id=?",
                    (time.time(), r[0]))
        con.commit()
        print(r[1])
except Exception:
    pass
PY
)
  [ -z "$row" ] && return 1
  wav="$APP/$row"; [ -f "$wav" ] || wav="$row"
  [ -f "$wav" ] || return 1
  ffmpeg -v quiet -i "$wav" -f s16le -ar 24000 -ac 1 - </dev/null
  ffmpeg -v quiet -i "$FILLER" -t 1.2 -f s16le -ar 24000 -ac 1 - </dev/null
}

feed() {
  while true; do
    # spot break roughly every SPOT_EVERY seconds of aired content
    now=$(date +%s); last=$(cat "$LAST_SPOT_FILE" 2>/dev/null || echo 0)
    if [ $((now - last)) -ge "$SPOT_EVERY" ]; then
      if play_spot; then date +%s > "$LAST_SPOT_FILE"; fi
    fi
    f=$(ls "$BUF"/incoming/*.wav 2>/dev/null | sort | head -1)
    if [ -z "$f" ]; then
      # brief drought: a short breath of room tone, then AUDIBLE reserve
      # content — long near-silence is dead air, the one unforgivable sin
      for i in $(seq 1 4); do
        ffmpeg -v quiet -i "$FILLER" -t 1.5 -f s16le -ar 24000 -ac 1 - </dev/null
        f=$(ls "$BUF"/incoming/*.wav 2>/dev/null | sort | head -1)
        [ -n "$f" ] && break
      done
    fi
    if [ -n "$f" ]; then
      # host-announced ad break: marker file -> a real break (3 spots), or a
      # station bumper if no spot is ready — a throw must NEVER land on nothing
      case "$(basename "$f")" in *-break*)
        mv "$f" "$BUF/played/"
        if play_spot; then
          date +%s > "$LAST_SPOT_FILE"
          play_spot && true
          play_spot && true
          ffmpeg -v quiet -i "$FILLER" -t 1.0 -f s16le -ar 24000 -ac 1 - </dev/null
        else
          # guard biting or empty pool: back the host's "we'll be right back"
          # with a bumper + breath so it reads as a real break, not a false ending
          bb=$(ls "$RESERVE"/bumper*.wav 2>/dev/null | shuf -n1)
          [ -n "$bb" ] && ffmpeg -v quiet -i "$bb" -f s16le -ar 24000 -ac 1 - </dev/null
          ffmpeg -v quiet -i "$FILLER" -t 1.0 -f s16le -ar 24000 -ac 1 - </dev/null
        fi
        continue
      ;; esac
      # produced handover at show boundaries: bumper + a breath
      sh=$(show_of "$f")
      if [ -n "$sh" ] && [ -n "$LAST_SHOW" ] && [ "$sh" != "$LAST_SHOW" ]; then
        b=$(ls "$RESERVE"/bumper*.wav 2>/dev/null | shuf -n1)
        [ -n "$b" ] && ffmpeg -v quiet -i "$b" -f s16le -ar 24000 -ac 1 - </dev/null
        ffmpeg -v quiet -i "$FILLER" -t 1.5 -f s16le -ar 24000 -ac 1 - </dev/null
      fi
      [ -n "$sh" ] && LAST_SHOW="$sh"
      # publish what's actually airing (show + segment) for the website
      seg=$(basename "$f" .wav | sed "s/^[0-9]*_//; s/-/ /g")
      printf '{"airing":"%s","ts":%s}\n' "$seg" "$(date +%s)" \
        > /var/www/bestairadio/data/now.json.tmp 2>/dev/null \
        && mv /var/www/bestairadio/data/now.json.tmp /var/www/bestairadio/data/now.json 2>/dev/null
      play_file "$f"
      mv "$f" "$BUF/played/"
      # keep only the last 50 played segments
      ls -t "$BUF"/played/*.wav 2>/dev/null | tail -n +51 | xargs -r rm -f
    else
      # buffer empty: no-repeat shuffled rotation through the reserve pool —
      # every piece airs once before anything repeats; atomic consumption
      if [ ! -s "$QUEUE" ]; then
        ls "$RESERVE"/*.wav 2>/dev/null | shuf > "$QUEUE"
      fi
      r=$(head -1 "$QUEUE")
      tail -n +2 "$QUEUE" > "$QUEUE.tmp" && mv "$QUEUE.tmp" "$QUEUE"
      if [ -n "$r" ] && [ -f "$r" ]; then
        ffmpeg -v quiet -i "$r" -f s16le -ar 24000 -ac 1 - </dev/null
        # breathing room (room tone, never digital zero)
        ffmpeg -v quiet -i "$FILLER" -t 2.5 -f s16le -ar 24000 -ac 1 - </dev/null
      else
        ffmpeg -v quiet -i "$FILLER" -f s16le -ar 24000 -ac 1 - </dev/null
      fi
      sleep 1
    fi
  done
}

# broadcast chain (I1): HPF, gentle compression, de-esser, leveler, limiter.
# dynaudnorm+alimiter, NOT loudnorm (loudnorm resamples internally — CPU trap).
CHAIN="highpass=f=75,acompressor=threshold=-21dB:ratio=2.5:attack=15:release=250:knee=6:makeup=5,deesser=i=0.3,dynaudnorm=f=400:g=17:p=0.85,alimiter=limit=0.85:attack=4:release=80:level=false"

# if the encoder ever exits (icecast down, network), exit so systemd restarts
# us cleanly — otherwise the feeder keeps the service alive-but-silent
feed | ffmpeg -v warning -re -f s16le -ar 24000 -ac 1 -i - \
  -af "$CHAIN" \
  -c:a libmp3lame -b:a 96k -content_type audio/mpeg -f mp3 \
  -ice_name "The Frequency" \
  -ice_description "A fully-AI radio station, live around the clock. bestairadio.com" \
  -ice_genre "Comedy / Talk" -ice_url "https://bestairadio.com" \
  "icecast://source:${ICECAST_PW}@127.0.0.1:8000/${MOUNT}" &
wait $!
exit 1
