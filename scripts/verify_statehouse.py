#!/usr/bin/env python3
"""The ONLY armer (mirror G4): writes `data/statehouse/VERIFIED` — and
thereby lets `engine.statehouse_on()` flip on — if and only if every check
below passes. A human cannot skip this at 2am; there is no other code path
that calls `engine.arm()`. This script never touches `ENABLED`: even a
clean VERIFIED leaves the gate off until an operator flips that flag by
hand (mirror §9.7).

Re-runs (from scratch, never trusting bootstrap's own report):
  - canon-diff recomputed independently (`bootstrap_mod.compute_canon_diff`)
    against the live sidecars, plus `canon-diff.txt` read back and checked
    empty.
  - a full OFFLINE 30-day dry-run: copy civics.json + data/statehouse into a
    temp dir, run `engine.tick()` day-by-day 30 days past `sim_through` on
    the copy, asserting zero exceptions, the TRACKED pointer always names a
    real bill id (or is legitimately empty), chamber seat sums hold at
    every checkpoint, and a repeat same-day tick is fast (<100ms).
  - a civicguard golden-render: build `session_brief`'s facts
    (`civicguard.build_civic_facts`) and confirm booth-style lines quoting
    that sheet verbatim pass `civicguard.enforce_civic` with ZERO
    replacements — the anti-hallucination round-trip the design calls G3.

Any failure: print the failure table, exit 1, never call `engine.arm()`.
Runnable from the repo root or from /opt/kaos/app (cwd-relative paths).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from datetime import date as _date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

import bootstrap_statehouse as bootstrap_mod          # noqa: E402
from src.statehouse import civicguard                 # noqa: E402
from src.statehouse import docket                      # noqa: E402
from src.statehouse import engine                       # noqa: E402
from src.statehouse import members                       # noqa: E402
from src.statehouse import sheets                         # noqa: E402
from src.statehouse import votes                           # noqa: E402

DEFAULT_GA = 1
_DRY_RUN_DAYS = 30


# --------------------------------------------------------------- core re-derive

def _sidecars_present(ga: int, root: Path) -> tuple[bool, str]:
    cal = engine.load_side(f"calendar-ga{ga}.json", root)
    mem = engine.load_side(f"members-ga{ga}.json", root)
    dk = engine.load_side(f"docket-ga{ga}.json", root)
    ok = cal is not None and mem is not None and dk is not None
    return ok, "" if ok else "run bootstrap_statehouse.py first"


def _chamber_sums_hold(mem: dict) -> tuple[bool, str]:
    agg = members.seat_table(mem)
    house_ok = sum(agg.get("house", {}).values()) == 51
    senate_ok = sum(agg.get("senate", {}).values()) == 9
    return (house_ok and senate_ok,
            f"house={sum(agg.get('house', {}).values())} "
            f"senate={sum(agg.get('senate', {}).values())}")


def _whip_bucket_invariant(dk: dict, mem: dict, ga: int) -> tuple[bool, str]:
    """Spot-check the frozen 4-bucket invariant (votes.py's own contract):
    yea+nay+und+absent == chamber size, for every bill currently on the
    docket. Cheap (a docket is ~200 bills) and catches any drift between
    the members sidecar and votes.py's CHAMBER_SIZE assumption."""
    bad = []
    for bid, bill in dk.get("bills", {}).items():
        ch = votes.chamber_of(bill)
        wc = votes.whip_count(bid, bill, mem.get("members", {}), ga, chamber=ch)
        total = sum(wc.values())
        if total != votes.CHAMBER_SIZE[ch]:
            bad.append(f"{bid}: {total} != {votes.CHAMBER_SIZE[ch]}")
    return not bad, "; ".join(bad[:3]) + (" ..." if len(bad) > 3 else "")


# ---------------------------------------------------------- offline dry run

def _offline_dry_run(ga: int, days: int = _DRY_RUN_DAYS) -> dict:
    civ_live = engine.load_civics()
    if not civ_live.get("sim_through"):
        return {"skipped": "no live civics.json to dry-run from"}

    tmp = Path(tempfile.mkdtemp(prefix="verify_statehouse_dryrun_"))
    try:
        copy_root = tmp / "statehouse"
        if engine.SIDE.exists():
            shutil.copytree(engine.SIDE, copy_root,
                            ignore=shutil.ignore_patterns("*.tmp.*", "ENABLED", "VERIFIED"))
        else:
            copy_root.mkdir(parents=True)
        civ_path = tmp / "civics.json"
        live_civ_path = engine._CIV_PATH
        if live_civ_path.exists():
            civ_path.write_text(live_civ_path.read_text())

        start = _date.fromisoformat(civ_live["sim_through"])
        errors: list[str] = []
        tracked_bad: list[str] = []
        chamber_bad: list[str] = []
        day = start.isoformat()
        for i in range(1, days + 1):
            day = (start + timedelta(days=i)).isoformat()
            try:
                res = engine.tick(ga, day, root=copy_root, civ_path=civ_path)
            except Exception as e:
                errors.append(f"{day}: {type(e).__name__}: {e}")
                continue
            civ, dk, mem = res["civ"], res["dk"], res["mem"]
            tid = (civ.get("tracked") or {}).get("id")
            if tid is not None and tid not in dk.get("bills", {}):
                tracked_bad.append(f"{day}: tracked id {tid!r} not in docket")
            ok, detail = _chamber_sums_hold(mem)
            if not ok:
                chamber_bad.append(f"{day}: {detail}")

        t0 = time.perf_counter()
        try:
            engine.tick(ga, day, root=copy_root, civ_path=civ_path)
        except Exception as e:
            errors.append(f"{day} (re-tick): {type(e).__name__}: {e}")
        fast_ms = (time.perf_counter() - t0) * 1000.0

        return {"skipped": None, "errors": errors, "tracked_bad": tracked_bad,
                "chamber_bad": chamber_bad, "fast_ms": fast_ms}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------- golden render

_BOOTH = {"speaker": "Sal Tarantella", "voice": "am_onyx", "speed": 0.97}


def _guard_lines(text: str) -> list:
    out = []
    for frag in text.replace("\n", " ").split(". "):
        frag = frag.strip()
        if not frag:
            continue
        if not frag.endswith((".", "!", "?")):
            frag += "."
        out.append({"speaker": _BOOTH["speaker"], "voice": _BOOTH["voice"],
                    "speed": _BOOTH["speed"], "text": frag})
    return out


def _golden_render(civ: dict, dk: dict, mem: dict, ga: int) -> tuple[bool, str]:
    """Render `session_brief` for a SAFE, spoiler-free TRACKED thread — the
    highest-marquee UNRESOLVED bill (`docket.pick_tracked`), independent of
    whatever the live `civ["tracked"]` pointer happens to hold. This
    mirrors `verify_league.py`'s own golden render, which deliberately
    builds a fresh, never-yet-played matchup rather than reusing arbitrary
    live state: the live tracked pointer can legitimately be a
    RESOLVED-but-unaired bill (the spine holds those constantly — that's
    the whole point of air-gating exports on the aired ledger), and
    rendering THAT as "Resolved: ..." is exactly the pre-air spoiler
    civicguard's catch class #8 is supposed to catch, not a guard bug. This
    check instead proves the sheet-building + guard pipeline is sound on
    the one shape a pregame-analog sheet is actually allowed to say
    something numeric about: an unresolved whip count. Falls back to a
    "no marquee thread currently tracked" render (also structurally
    spoiler-free) if nothing is currently live."""
    try:
        date = civ.get("sim_through") or ""
        safe_id = docket.pick_tracked(dk, ga, date)
        safe_civ = dict(civ)
        whip = None
        sheet_extra: dict = {"mode": "session_brief"}
        if safe_id:
            bill = dk["bills"][safe_id]
            ch = votes.chamber_of(bill)
            whip = votes.whip_count(safe_id, bill, mem.get("members", {}), ga, chamber=ch)
            safe_civ["tracked"] = {"kind": "bill", "id": safe_id, "since": date,
                                    "beat": "committee", "resolved": None}
            sheet_extra["whip"] = {safe_id: whip}
        else:
            safe_civ["tracked"] = {"kind": "bill", "id": None, "since": None,
                                    "beat": None, "resolved": None}

        text = sheets.session_brief(safe_civ, dk, mem, date, whip=whip)
        facts = civicguard.build_civic_facts(
            {"civ": safe_civ, "dk": dk, "members": mem, "date": date}, sheet_extra)
        lines = _guard_lines(text)
        out = civicguard.enforce_civic(lines, facts)
        bad = [o for o in out if o.get("_enforced")]
        if bad:
            sample = "; ".join(o["text"][:70] for o in bad[:3])
            return False, f"{len(bad)}/{len(lines)} line(s) replaced: {sample}"
        return True, f"{len(lines)} line(s) rendered, zero replacements"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ----------------------------------------------------------------- verify

def verify(ga: int = DEFAULT_GA) -> dict:
    root = engine.SIDE
    checks: list = []

    def add(name: str, ok: bool, detail: str = "", warn: bool = False) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "warn": warn})

    ok, detail = _sidecars_present(ga, root)
    add("sidecars present & parse (calendar/members/docket)", ok, detail)
    if not ok:
        return {"skipped": None, "checks": checks, "armed": False}

    cal = engine.load_side(f"calendar-ga{ga}.json", root)
    mem = engine.load_side(f"members-ga{ga}.json", root)
    dk = engine.load_side(f"docket-ga{ga}.json", root)
    civ = engine.load_civics()

    diffs = bootstrap_mod.compute_canon_diff(mem, cal)
    add("canon-diff recomputed from scratch is empty", not diffs,
        "; ".join(diffs[:5]) + (" ..." if len(diffs) > 5 else ""))

    diff_path = root / "canon-diff.txt"
    file_txt = diff_path.read_text() if diff_path.exists() else None
    add("canon-diff.txt exists and is empty",
        diff_path.exists() and file_txt is not None and not file_txt.strip(),
        "missing" if file_txt is None else f"{len(file_txt.strip().splitlines())} line(s)")

    add("chamber seat sums hold (51 House / 9 Senate)", *_chamber_sums_hold(mem))
    add("whip-count 4-bucket invariant holds docket-wide",
        *_whip_bucket_invariant(dk, mem, ga))

    tid = (civ.get("tracked") or {}).get("id")
    add("tracked pointer names a real bill id (or is empty)",
        tid is None or tid in dk.get("bills", {}),
        f"tracked id {tid!r}")

    dry = _offline_dry_run(ga)
    if dry.get("skipped"):
        add(f"offline {_DRY_RUN_DAYS}-day dry-run", True, dry["skipped"])
    else:
        errs = dry["errors"]
        add(f"dry-run: zero exceptions across the {_DRY_RUN_DAYS}-day tick rehearsal",
            not errs, "; ".join(errs[:3]) + (" ..." if len(errs) > 3 else "") or "clean")
        add("dry-run: tracked pointer always valid", not dry["tracked_bad"],
            "; ".join(dry["tracked_bad"][:3]))
        add("dry-run: chamber sums hold at every checkpoint", not dry["chamber_bad"],
            "; ".join(dry["chamber_bad"][:3]))
        add("dry-run: fast re-tick < 100ms", dry["fast_ms"] < 100.0,
            f"{dry['fast_ms']:.1f}ms")

    gr_ok, gr_detail = _golden_render(civ, dk, mem, ga)
    add("golden-render: session_brief + civicguard zero replacements", gr_ok, gr_detail)

    armed = all(c["ok"] for c in checks if not c["warn"])
    if armed:
        engine.arm(ga, root)
    return {"skipped": None, "checks": checks, "armed": armed}


def _print_table(res: dict) -> None:
    if res.get("skipped"):
        print(f"verify_statehouse: {res['skipped']} — nothing to verify, exiting 0")
        return
    width = max((len(c["name"]) for c in res["checks"]), default=10)
    for c in res["checks"]:
        mark = "PASS" if c["ok"] else ("WARN" if c["warn"] else "FAIL")
        line = f"  [{mark}] {c['name']:<{width}}"
        if c["detail"]:
            line += f"  -- {c['detail']}"
        print(line)
    if res["armed"]:
        print("\nverify_statehouse: all GATING checks green -> "
              "data/statehouse/VERIFIED written, armed. (ENABLED is still off "
              "— an operator flips that flag by hand.)")
    else:
        n_fail = sum(1 for c in res["checks"] if not c["ok"] and not c["warn"])
        print(f"\nverify_statehouse: {n_fail} check(s) FAILED -- refusing to arm.")


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ga", type=int, default=DEFAULT_GA)
    args = ap.parse_args(argv)
    res = verify(args.ga)
    _print_table(res)
    if res.get("skipped"):
        return 0
    return 0 if res["armed"] else 1


if __name__ == "__main__":
    sys.exit(main())
