"""HALFWAY HOT 10 sheets — the broadcast contract for the countdown desk
(design §5/§6, mirrors `src/statehouse/sheets.py`).

Leaf module: pure functions over an already-computed `hot10.py` week-record
(`chart()`/`roll_week()`'s output shape) and the catalog dict. No file IO,
no imports of `hot10.py` or any sibling `src/music/*` module — this module
only needs to agree with their *output shapes*, exactly like
`statehouse/sheets.py`'s own discipline ("F needs B/C/E shapes only"). Code
(`hot10.py`) owns every number; these functions only phrase already
-computed state — nothing here invents a rank, a debut, or a gainer that
wasn't already sitting in the dicts handed to us.

Two registers, two purposes:
  - `countdown_sheet` — the show's own prep sheet: a full #10 -> #1 rundown
    plus deltas, prose the booth reads from. Distinct from `hot10.narrate`'s
    strict "authoritative, do not change any number" prompt block, though
    every figure here is the same code-owned truth (deliberate restatement
    of shared vocabulary rather than a cross-import, same reasoning as
    civicguard/sheets.py's own STAGE_WORDS restatement).
  - `chart_desk_line` — one narratable wire line for OTHER shows' news
    desks (the music-chart analogue of `statehouse.sheets.dome_desk`), so a
    drive-time show can namecheck "the new number one on the Hot 10" without
    running its own chart logic.
"""
from __future__ import annotations


def _title_artist(catalog: dict, tid: str) -> tuple:
    tr = catalog.get("tracks", {}).get(tid, {})
    title = tr.get("title", tid)
    artist = catalog.get("artists", {}).get(tr.get("artist"), {}).get("name", "")
    return title, artist


def _who(catalog: dict, tid: str) -> str:
    title, artist = _title_artist(catalog, tid)
    return f"{title} — {artist}" if artist else title


def countdown_sheet(chart: dict, catalog: dict) -> str:
    """The countdown show's prep sheet: #10 -> #1 (AT40-style, ascending
    reveal order) plus this week's deltas."""
    rows = sorted(chart.get("chart", []), key=lambda r: -r["rank"])  # #10 first
    lines = [f"HALFWAY HOT 10 — WEEK OF {chart.get('week')}"]
    for r in rows:
        who = _who(catalog, r["tid"])
        if r["debut"]:
            tag_word = ("the Hot Shot Debut" if r["tid"] == chart.get("hot_shot")
                        else "a brand new entry")
            move = f"debuts at number {r['rank']}, {tag_word}"
        elif r["last"] == r["rank"]:
            move = f"holds at number {r['rank']}"
        elif r["rank"] < r["last"]:
            move = f"climbs from number {r['last']} to number {r['rank']}"
        else:
            move = f"slides from number {r['last']} down to number {r['rank']}"
        tag = ""
        if r["bullet"]:
            tag += ", with a bullet"
        if r["tid"] == chart.get("gainer"):
            tag += ", this week's Greatest Gainer"
        lines.append(f"#{r['rank']}: {who} — {move}, its {r['weeks']} week "
                     f"on the chart, peak of number {r['peak']}{tag}.")
    if chart.get("droppers"):
        names = "; ".join(_who(catalog, t) for t in chart["droppers"])
        lines.append(f"DROPPED OFF THE CHART: {names}.")
    return "\n".join(lines)


def chart_desk_line(chart: dict, catalog: dict, n: int = 5) -> str:
    """One narratable wire line for other shows' news desks (`dome_desk`'s
    music-chart analogue). Semicolon-joined highlights, capped at `n`."""
    rows = sorted(chart.get("chart", []), key=lambda r: r["rank"])
    items = []
    top = next((r for r in rows if r["rank"] == 1), None)
    if top:
        who = _who(catalog, top["tid"])
        items.append(f"{who} holds number one" if top["last"] == 1
                     else f"{who} is the new number one")
    hs = chart.get("hot_shot")
    if hs:
        items.append(f"{_who(catalog, hs)} is the Hot Shot Debut")
    gainer = chart.get("gainer")
    if gainer:
        items.append(f"{_who(catalog, gainer)} takes the Greatest Gainer")
    for tid in chart.get("droppers", []):
        items.append(f"{_who(catalog, tid)} drops off the chart")
    items = items[:n]
    if not items:
        return f"No Halfway Hot 10 wire for the week of {chart.get('week')}."
    return "On the Halfway Hot 10 this week: " + "; ".join(items) + "."
