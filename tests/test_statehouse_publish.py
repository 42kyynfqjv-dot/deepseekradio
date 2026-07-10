"""Statehouse publish.py + the Dome Desk news-bulletin wiring: the air-gated
`.../statehouse.json` export (mirror §7, scoped per `publish.py`'s own
docstring) and the code-built wire line `orchestrator._news_bulletin`
appends once the gate arms.

Gate-off must be byte-identical (no file created; an existing file survives
untouched). Gate-on must publish exactly the standings-equivalent fields
(never a `gavel_recap` narrative leak) and the Dome Desk line must round-trip
through `civicguard` with zero replacements — proof the code-built copy is
guard-safe by construction, mirroring the Sports Desk pattern.

Repo style, temp-dir monkeypatched (mirrors tests/test_statehouse_engine.py's
`_tmp_env()`). Per this task's own instruction, the Dome Desk block is
exercised by driving `sheets`/`publish`/`civicguard` directly rather than the
full LLM/TTS orchestrator pipeline.

Run directly (no pytest needed): python3 tests/test_statehouse_publish.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.statehouse import calendar as cal_mod        # noqa: E402
from src.statehouse import civicguard as cg            # noqa: E402
from src.statehouse import engine                        # noqa: E402
from src.statehouse import members                        # noqa: E402
from src.statehouse import publish                         # noqa: E402
from src.statehouse import sheets                            # noqa: E402

PASS = FAIL = 0
GA = 1
DATE = "2026-07-10"   # Friday — never Wed/Sat (final.md delta 5)
ELECTION_DATE = "2026-11-03"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def _tmp_env():
    """A fresh temp dir with engine.SIDE/_CIV_PATH pointed at it — the same
    monkeypatch `publish.py` transparently inherits, since it only ever
    calls `engine.*` (never caches SIDE/_CIV_PATH locally)."""
    tmp = Path(tempfile.mkdtemp())
    root = tmp / "statehouse"
    civ_path = tmp / "civics.json"
    engine.SIDE = root
    engine._CIV_PATH = civ_path
    return tmp, root, civ_path


def _arm_gate(root):
    """Real calendar + members sidecars (the immutable core VERIFIED hashes
    over), armed directly via `engine.arm` — this unit test doesn't need the
    full bootstrap/verify-script ceremony `test_statehouse_engine.py` covers
    end-to-end; it only needs a gate that reads True."""
    cal = cal_mod.build_calendar(GA, cal_mod.GA1_CONVENED)
    engine.save_side(f"calendar-ga{GA}.json", cal, root)
    mem = members.mint_assembly(GA)
    engine.save_side(f"members-ga{GA}.json", mem, root)
    engine.arm(GA, root)
    (root / "ENABLED").touch()


# --------------------------------------------------------------- fixtures

def _make_civ():
    return {
        "ga": GA, "session": "regular-extended", "sim_through": DATE,
        "phase": "session",
        "seats": {"house": {"prov": 14, "round": 9, "vang": 11, "barb": 7,
                             "grudge": 6, "goose": 4},
                  "senate": {"prov": 3, "vang": 2, "round": 2, "barb": 1,
                             "grudge": 1}},
        "approval": {"gov": 46.2, "streak": 3, "series": {DATE: 46.2}},
        "tracked": {"kind": "bill", "id": "HB-7", "since": "2026-07-01",
                    "beat": "committee", "resolved": None},
        "quorum_fails": ["2026-02-11"],
        "aired": {"HB-7:reported": 1789200000.0},
        "last_line": "HB-7 cleared Roads, 6 votes to 3",
        "rolled_pending": False,
    }


HB7_TITLE = "An Act Relating to the Numbering of Potholes Prior to Repair"


def _make_dk():
    return {
        "schema": 1, "ga": GA, "next_no": {"H": 41, "S": 12},
        "bills": {
            "HB-7": {
                "title": HB7_TITLE,
                "sponsor": "H-03", "committee": "roads", "stage": "REPORTED",
                "intro": "2026-07-01", "marquee": 0.91,
                "history": [["2026-07-01", "INTRODUCED"],
                            ["2026-07-06", "HEARING", "roads"],
                            [DATE, "REPORTED", "roads", [6, 3]]],
                "deficiency": None,
            },
        },
    }


MEMBERS_FIXTURE = {
    "schema": 1, "ga": GA,
    "members": {"H-03": {"name": "Doreen Vachon", "chamber": "house",
                          "district": 3, "party": "round"}},
    "officials": {"governor": {"name": "Marty Bouchard", "canon": True}},
}


# ================================================================ gate-off

def test_gate_off_publish_and_dome_desk():
    tmp, root, civ_path = _tmp_env()
    try:
        engine.save_civics(_make_civ(), civ_path)
        engine.save_side(f"docket-ga{GA}.json", _make_dk(), root)
        # no ENABLED/VERIFIED written -> gate stays off despite live sidecars
        check("gate off with sidecars present but unverified",
              engine.statehouse_on(GA) is False)

        out = tmp / "statehouse.json"
        publish.export(str(out))
        check("gate-off export creates nothing", not out.exists())

        # byte-identical fallback (mirror §9.7): a stale file from a prior,
        # now-reverted publish must survive a gate-off export untouched
        stale = b'{"stale": true, "left": "alone"}'
        out.write_bytes(stale)
        publish.export(str(out))
        check("gate-off export leaves an existing file byte-identical",
              out.read_bytes() == stale)

        # the Dome Desk block's own guard (orchestrator._news_bulletin)
        civ = engine.load_civics(civ_path)
        check("dome desk gate closed -- _news_bulletin's guard would skip it",
              engine.statehouse_on(civ.get("ga", 1)) is False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================= gate-on shape

def test_gate_on_export_shape_and_no_narrative_leak():
    tmp, root, civ_path = _tmp_env()
    try:
        _arm_gate(root)
        civ, dk = _make_civ(), _make_dk()
        engine.save_civics(civ, civ_path)
        engine.save_side(f"docket-ga{GA}.json", dk, root)
        check("gate on", engine.statehouse_on(GA) is True)

        out = tmp / "statehouse.json"
        publish.export(str(out))
        check("gate-on export writes a file", out.exists())
        d = json.loads(out.read_text())

        check("ga published", d.get("ga") == GA)
        check("phase published", d.get("phase") == "session")
        check("approval gov+streak published (standings-equivalent)",
              d.get("approval") == {"gov": 46.2, "streak": 3})
        check("tracked bill id/title/public-record-stage published",
              d.get("tracked") == {"id": "HB-7", "title": HB7_TITLE,
                                    "stage": "reported out of committee"})
        check("quorum-fails COUNT published (not the raw date ledger)",
              d.get("quorum_fails") == 1)
        el = d.get("election", {})
        check("election countdown to 2026-11-03 published",
              el.get("date") == ELECTION_DATE and
              isinstance(el.get("days_to"), int) and el["days_to"] > 0)

        # NEVER a gavel_recap narrative leak: no docket history, no stored
        # tally, no decisive-event / aired-ledger content anywhere published
        blob = json.dumps(d)
        check("no raw docket history leaked",
              "INTRODUCED" not in blob and "HEARING" not in blob)
        check("no stored tally leaked",
              "[6, 3]" not in blob and "6-3" not in blob and "votes to" not in blob)
        check("no gavel_recap/aired-ledger keys leaked",
              "recap" not in d and "events" not in d and "aired" not in d
              and "history" not in blob)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ==================================================== dome desk + civicguard

def test_dome_desk_line_and_civicguard_roundtrip():
    tmp, root, civ_path = _tmp_env()
    try:
        _arm_gate(root)
        civ, dk = _make_civ(), _make_dk()
        engine.save_civics(civ, civ_path)
        engine.save_side(f"docket-ga{GA}.json", dk, root)

        # the exact guard orchestrator._news_bulletin's Dome Desk block uses
        loaded_civ = engine.load_civics(civ_path)
        ga = loaded_civ.get("ga", 1)
        check("gate on for the dome desk block", engine.statehouse_on(ga) is True)
        loaded_dk = engine.load_side(f"docket-ga{ga}.json", root)
        sim_date = loaded_civ.get("sim_through")

        desk = sheets.dome_desk(loaded_civ, loaded_dk, sim_date)
        check("dome_desk produced today's wire copy",
              desk.startswith("At the Dome today:"))
        line_text = "From the Half-Dome. " + desk
        check("dome desk line carries the Half-Dome prefix",
              line_text.startswith("From the Half-Dome. At the Dome today:"))

        # civicguard round-trip: zero replacements. This is the proof that
        # code-built wire copy is guard-safe by construction (no runtime
        # guard call needed in the orchestrator, exactly like the Sports
        # Desk's scores_desk line above it).
        state = {"civ": loaded_civ, "dk": loaded_dk, "members": MEMBERS_FIXTURE,
                 "date": sim_date}
        facts = cg.build_civic_facts(state, {"mode": "dome_desk"})
        out = cg.enforce_civic([{"text": line_text}], facts)
        check("civicguard round-trip: zero replacements on the dome line",
              out[0]["text"] == line_text and "_enforced" not in out[0],
              out[0])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ================================================================ run

for _name, _fn in sorted(list(globals().items())):
    if _name.startswith("test_") and callable(_fn):
        _fn()

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
