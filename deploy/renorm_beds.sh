#!/usr/bin/env bash
# One-time (idempotent) bed renormalization: every bed in /opt/kaos/beds is
# brought to -30 LUFS / -6 dBTP, 24k mono — the reference level player.sh's
# duck assumes. Originals are kept in beds/orig/ the first time through.
# (The first generation pass left night beds at -38.7 dB mean; after the
# 10:1 duck they mixed at -64.7 dB — playing, and humanly inaudible.)
set -eu
BEDS="${BEDS:-/opt/kaos/beds}"
mkdir -p "$BEDS/orig"
for f in "$BEDS"/*.wav; do
  base=$(basename "$f")
  [ -f "$BEDS/orig/$base" ] && continue   # already normalized once
  cp "$f" "$BEDS/orig/$base"
  tmp="$f.norm.tmp.wav"
  if ffmpeg -y -v error -i "$BEDS/orig/$base" \
        -af loudnorm=I=-30:LRA=7:TP=-6 -ar 24000 -ac 1 "$tmp"; then
    mv "$tmp" "$f"
    echo "normalized: $base"
  else
    rm -f "$tmp"
    echo "!! failed, left untouched: $base" >&2
  fi
done
