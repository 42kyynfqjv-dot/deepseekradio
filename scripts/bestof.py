"""Nightly best-of: pick yesterday's five funniest exchanges for the website.

Runs from a systemd timer at 05:20. Input is HARD-CAPPED (~40k chars of
transcript) so the daily cost stays ~$0.02. Output: data/bestof.json,
rendered client-side by bestof.html.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.openrouter import chat  # noqa: E402

OUT = Path("/var/www/bestairadio/data/bestof.json")
CAP = 40_000  # chars of transcript, hard cost ceiling


def _transcript() -> str:
    y = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    raw = subprocess.run(
        ["journalctl", "-u", "frequency", "--since", f"{y} 00:00",
         "--until", f"{y} 23:59", "--no-pager", "-o", "short"],
        capture_output=True, text=True, timeout=120).stdout
    lines = []
    for ln in raw.splitlines():
        m = re.search(r"python\[\d+\]:   (\[[^\]]+\] .+)", ln)
        if m:
            lines.append(m.group(1))
    txt = "\n".join(lines)
    if len(txt) <= CAP:
        return txt
    # spread the sample across the whole day, not just the morning
    step = len(txt) // 8
    return "\n[...]\n".join(txt[i:i + CAP // 8] for i in range(0, len(txt), step))[:CAP]


def main() -> int:
    txt = _transcript()
    if len(txt) < 500:
        print("not enough transcript; skipping")
        return 0
    models = {"id": "deepseek/deepseek-v4-flash", "temperature": 0.4,
              "max_tokens": 1800, "price_in": 0.09, "price_out": 0.18}
    raw = chat(models, [
        {"role": "system", "content":
         "You curate highlights for The Frequency, a 24/7 AI comedy radio "
         "station. From the day's transcript, pick the FIVE funniest "
         "self-contained exchanges (4-8 lines each). Keep speaker labels. "
         "Prefer variety across shows. Return STRICT JSON: "
         '{"highlights": [{"title": "<wry 4-8 word title>", '
         '"lines": ["Speaker: text", ...]}]}'},
        {"role": "user", "content": txt}])
    t = raw.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1].lstrip("json").strip()
    highlights = json.loads(t).get("highlights", [])[:5]
    y = (datetime.now() - timedelta(days=1)).strftime("%A, %B %d")
    prev = []
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text()).get("days", [])
        except Exception:
            pass
    days = ([{"date": y, "highlights": highlights}] + prev)[:7]
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps({"days": days}))
    tmp.replace(OUT)
    print(f"wrote {len(highlights)} highlights for {y}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
