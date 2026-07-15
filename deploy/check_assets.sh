#!/bin/sh
# Fail fast on the two assets that keep an unattended station from going
# silent. Beds are optional: the player already degrades to clean speech.
set -eu

FILLER="${FILLER:-/opt/kaos/roomtone.wav}"
RESERVE="${RESERVE:-/opt/kaos/reserve}"
BEDS="${BEDS:-/opt/kaos/beds}"
fail=0

if [ ! -s "$FILLER" ]; then
  echo "missing or empty filler: $FILLER" >&2
  fail=1
fi

reserve_count=$(find "$RESERVE" -maxdepth 1 -type f -name '*.wav' 2>/dev/null | wc -l)
if [ "$reserve_count" -lt 1 ]; then
  echo "no reserve WAVs found in: $RESERVE" >&2
  fail=1
fi

bed_count=$(find "$BEDS" -type f -name '*.wav' 2>/dev/null | wc -l)
if [ "$bed_count" -lt 1 ]; then
  echo "warning: no optional music beds found in: $BEDS" >&2
fi

exit "$fail"
