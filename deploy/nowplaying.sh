#!/bin/bash
. /opt/kaos/stream.env
# self-heal: if no source is connected, bounce the streamer
if ! curl -s -m 8 http://127.0.0.1:8000/status-json.xsl | grep -q "\"listenurl\""; then
  systemctl restart frequency-stream
  logger -t frequency "self-heal: source was down, restarted streamer"
  sleep 5
fi
SHOW=$(python3 - << "PY"
import yaml
from datetime import datetime, time as dtime
sched = yaml.safe_load(open("/opt/kaos/app/schedule.yaml"))
t = datetime.now().time()
for dp in sched["dayparts"]:
    a, b = (dtime.fromisoformat(x) for x in dp["window"])
    if (a <= b and a <= t < b) or (a > b and (t >= a or t < b)):
        print(dp["show"]); break
PY
)
# only push when the title CHANGES: every updinfo makes icecast inject an ICY
# metadata block mid-stream, and AppleCoreMedia players stall/reload on it
TITLE="The Frequency - ${SHOW}"
LAST_FILE=/run/frequency-nowplaying.last
if [ "$(cat "$LAST_FILE" 2>/dev/null)" != "$TITLE" ]; then
  curl -s -m 8 -u "admin:${ICECAST_ADMIN_PW}" \
    "http://127.0.0.1:8000/admin/metadata?mount=/live&mode=updinfo&song=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$TITLE")" > /dev/null
  printf "%s" "$TITLE" > "$LAST_FILE"
fi
