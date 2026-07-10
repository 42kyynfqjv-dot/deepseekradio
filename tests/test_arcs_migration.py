"""scripts/migrate_arcs.py fixtures (Row F, docs/designs/arcs-census-final.md):
bootstraps data/arcs/{arcs,civilians}.json from a synthetic lore_state,
gate stays OFF the whole time (never creates ENABLED, never writes
lore_state.json/station_state.json), a clean migration's canon-diff-arcs.txt
comes out EMPTY, and a second run is additive/preserving (idempotent).

Runs entirely in a temp dir (paths are injected into migrate(), the same
temp-dir discipline tests/test_season_live.py uses via monkeypatched module
globals -- here the script takes the paths as real parameters instead).

Run directly (no pytest needed):  python3 tests/test_arcs_migration.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import migrate_arcs as mig  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


# --------------------------------------------------------------- fixtures

def synthetic_lore():
    """A synthetic legacy `lore_state` shaped exactly like
    arcs.py's `_legacy_daily_tick` output: arcs-as-a-list, each with
    title/premise/day/max_days/latest/status."""
    return {
        "arcs": [
            {"title": "The Pharmacy-Lot Goose", "premise": "a goose has claimed "
             "the pharmacy parking lot", "day": 1, "max_days": 5,
             "latest": "the goose has accepted a folding chair",
             "status": "active"},
            {"title": "The Pothole Commissioner Election",
             "premise": "a write-in campaign for Pothole Commissioner "
             "gains steam ahead of the council vote", "day": 4, "max_days": 5,
             "latest": "yard signs have appeared on Elm", "status": "active"},
            {"title": "The Thermostat War", "premise": "an office thermostat "
             "dispute finally ends", "day": 5, "max_days": 5,
             "latest": "a truce was declared", "status": "done"},
            {"title": "", "premise": "titleless, must be skipped", "day": 1,
             "max_days": 3, "latest": "", "status": "active"},
        ],
        "recent_premises": ["a goose in a parking lot", "a roundabout fern"],
        "running_jokes": ["the roundabout is always two weeks out"],
    }


def synthetic_station():
    return {"callers_today": ["Maureen", "Ruth", "", "  ", "Al"]}


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj))


def run_migration(tmp: Path, lore=None, station=None, today="2026-07-11"):
    root = tmp / "arcs"
    lore_p = tmp / "lore_state.json"
    station_p = tmp / "station_state.json"
    if lore is not None:
        write_json(lore_p, lore)
    if station is not None:
        write_json(station_p, station)
    res = mig.migrate(root=root, lore_path=lore_p, station_path=station_p,
                       today=today)
    return res, root, lore_p, station_p


def main():
    tmp = Path(tempfile.mkdtemp())
    try:
        # ============================================================
        # 1. Basic migration off a synthetic lore_state
        # ============================================================
        res, root, lore_p, station_p = run_migration(
            tmp, synthetic_lore(), synthetic_station())

        check("ok (clean canon-diff)", res["ok"], res["canon_diff"])
        check("2 arcs lifted (titleless + done skipped)",
              res["arcs_lifted"] == 2, res["arcs_lifted"])
        check("1 done arc skipped", res["done_arcs_skipped"] == 1)
        check("0 already-present on first run", res["arcs_already_present"] == 0)
        check("gate not present", res["gate_present"] is False)
        check("ENABLED never created", not (root / "ENABLED").exists())
        check("canon-diff empty list", res["canon_diff"] == [])

        diff_path = root / "canon-diff-arcs.txt"
        check("canon-diff-arcs.txt written", diff_path.exists())
        check("canon-diff-arcs.txt EMPTY", diff_path.read_text() == "")

        check("arcs.json written", (root / "arcs.json").exists())
        check("civilians.json written", (root / "civilians.json").exists())

        arcs_on_disk = json.loads((root / "arcs.json").read_text())
        check("arcs.json schema", arcs_on_disk.get("schema") == 1)
        check("arcs.json has seq (arcs.py parity)", "seq" in arcs_on_disk)
        check("2 arcs present", len(arcs_on_disk["arcs"]) == 2)

        goose = next(a for a in arcs_on_disk["arcs"].values()
                     if a["title"] == "The Pharmacy-Lot Goose")
        election = next(a for a in arcs_on_disk["arcs"].values()
                         if "Pothole Commissioner" in a["title"])

        # ---- schema compatibility with the shipped src/arcs.py state
        # machine (component B) -- every field daily_tick/gate_payoff/
        # next_beat touch via direct subscript must be present.
        required = {"id", "title", "premise", "setting", "register", "stage",
                    "stage_idx", "opened", "payoff_on", "cast", "status",
                    "force_payoff", "graduated", "facts", "beats", "latest"}
        check("goose has every field src/arcs.py's state machine reads",
              required <= set(goose.keys()), sorted(set(goose) ^ required))
        check("payoff_on present (not the stale payoff_date label)",
              "payoff_on" in goose and "payoff_date" not in goose)
        check("id field matches the outer dict key",
              goose["id"] in arcs_on_disk["arcs"]
              and arcs_on_disk["arcs"][goose["id"]] is goose)
        check("force_payoff starts false", goose["force_payoff"] is False)
        check("graduated starts false", goose["graduated"] is False)
        check("status active", goose["status"] == "active")

        # ---- no invented aired facts/beats -----------------------------
        check("facts[] empty (no invented aired canon)", goose["facts"] == [])
        check("exactly one beat (the forward PAYOFF)", len(goose["beats"]) == 1)
        beat = goose["beats"][0]
        check("beat is a PAYOFF beat", beat["stage"] == "PAYOFF")
        check("beat status pending (never pre-aired)", beat["status"] == "pending")
        check("beat aired_date is None", beat["aired_date"] is None)
        check("beat carries a due date == payoff_on",
              beat["due"] == goose["payoff_on"])
        check("beat carries both directive and fact text",
              beat["directive"] and beat["fact"])
        check("payoff_on is strictly in the future of today",
              goose["payoff_on"] > "2026-07-11")
        check("opened == today (no fabricated past open date)",
              goose["opened"] == "2026-07-11")

        # ---- register narrowing (never invents conspiracy/dreamcourt/sports)
        check("mundane premise stays mundane", goose["register"] == "mundane")
        check("civic-worded premise (council/election) narrows to civic",
              election["register"] == "civic")

        # ---- stage/stage_idx derivation, never PAYOFF/LORE for an active arc
        check("day1/max5 -> SEEDED", goose["stage"] == "SEEDED"
              and goose["stage_idx"] == 0)
        check("day4/max5 -> mid-ladder stage (never PAYOFF/LORE pre-lift)",
              election["stage"] in ("RISING", "COMPLICATION", "CRISIS"))
        check("stage never PAYOFF/LORE for a lifted active arc",
              all(a["stage"] not in ("PAYOFF", "LORE")
                  for a in arcs_on_disk["arcs"].values()))

        # ---- latest weave-in line preserved verbatim ---------------------
        check("latest preserved verbatim",
              goose["latest"] == "the goose has accepted a folding chair")

        # ---- census sidecar ------------------------------------------------
        civ_on_disk = json.loads((root / "civilians.json").read_text())
        check("civilians.json schema", civ_on_disk.get("schema") == 1)
        check("residents born empty (no resurrected past callers)",
              civ_on_disk["residents"] == {})
        check("blank/whitespace caller names filtered",
              "" not in civ_on_disk["used_names"]
              and "  " not in civ_on_disk["used_names"])
        check("real caller names reserved",
              {"Maureen", "Ruth", "Al"} <= set(civ_on_disk["used_names"]))
        check("names_reserved count matches non-blank callers_today",
              res["names_reserved"] == 3, res["names_reserved"])

        # ---- recent_settings carried forward (variety memory, not canon) --
        check("recent_premises carried into recent_settings",
              "a goose in a parking lot" in arcs_on_disk["recent_settings"]
              and "a roundabout fern" in arcs_on_disk["recent_settings"])

        # ---- running jokes untouched, arc->joke is one-way -----------------
        check("running_jokes_left_in_lore reported, lore itself untouched",
              res["running_jokes_left_in_lore"] == 1)

        # ---- read-only guarantee: lore_state.json / station_state.json
        # byte-identical after the run (this script NEVER writes them) ------
        lore_bytes_before = json.dumps(synthetic_lore()).encode()
        # (re-derive expected bytes by reloading straight off disk instead,
        # since dict key order in json.dumps isn't guaranteed identical)
        lore_after = json.loads(lore_p.read_text())
        station_after = json.loads(station_p.read_text())
        check("lore_state.json content unchanged", lore_after == synthetic_lore())
        check("station_state.json content unchanged",
              station_after == synthetic_station())

        # ============================================================
        # 2. Idempotent double-run: additive + preserving
        # ============================================================
        snapshot = json.loads((root / "arcs.json").read_text())
        civ_snapshot = json.loads((root / "civilians.json").read_text())

        res2, root2, lore_p2, station_p2 = run_migration(
            tmp, synthetic_lore(), synthetic_station())
        check("second run same root", root2 == root)
        check("second run: 0 newly lifted", res2["arcs_lifted"] == 0,
              res2["arcs_lifted"])
        check("second run: 2 already present", res2["arcs_already_present"] == 2)
        check("second run: still 1 done skipped", res2["done_arcs_skipped"] == 1)
        check("second run: canon-diff still empty", res2["canon_diff"] == [])
        check("second run: ENABLED still absent", not (root / "ENABLED").exists())

        arcs_after2 = json.loads((root / "arcs.json").read_text())
        check("idempotent: arc records byte-for-byte unchanged (dates and all)",
              arcs_after2["arcs"] == snapshot["arcs"], "arcs drifted on re-run")
        check("idempotent: no duplicate arcs minted",
              len(arcs_after2["arcs"]) == len(snapshot["arcs"]))

        civ_after2 = json.loads((root / "civilians.json").read_text())
        check("idempotent: used_names not duplicated on identical callers_today",
              civ_after2["used_names"] == civ_snapshot["used_names"])
        check("idempotent: residents still untouched",
              civ_after2["residents"] == {})

        check("canon-diff-arcs.txt still empty after 2nd run",
              diff_path.read_text() == "")

        # A THIRD run with one brand-new caller name must be additive-only:
        # existing residents/arcs untouched, new name unioned in.
        station3 = {"callers_today": ["Maureen", "Priya"]}
        res3, *_ = run_migration(tmp, synthetic_lore(), station3)
        civ_after3 = json.loads((root / "civilians.json").read_text())
        check("3rd run adds the new name", "Priya" in civ_after3["used_names"])
        check("3rd run preserves prior names", "Al" in civ_after3["used_names"])
        check("3rd run: no dup arcs (still 2)", len(
            json.loads((root / "arcs.json").read_text())["arcs"]) == 2)

        # ============================================================
        # 3. Gate-off byte-identity + read-only discipline, isolated run
        # ============================================================
        tmp2 = Path(tempfile.mkdtemp())
        try:
            lore2 = synthetic_lore()
            station2 = synthetic_station()
            lore_p2 = tmp2 / "lore_state.json"
            station_p2 = tmp2 / "station_state.json"
            write_json(lore_p2, lore2)
            write_json(station_p2, station2)
            lore_raw_before = lore_p2.read_bytes()
            station_raw_before = station_p2.read_bytes()

            root2 = tmp2 / "arcs"
            r = mig.migrate(root=root2, lore_path=lore_p2,
                            station_path=station_p2, today="2026-07-11")

            check("gate-off: ENABLED not created", not (root2 / "ENABLED").exists())
            check("gate-off: result reports gate_present False",
                  r["gate_present"] is False)
            check("gate-off: lore_state.json byte-identical",
                  lore_p2.read_bytes() == lore_raw_before)
            check("gate-off: station_state.json byte-identical",
                  station_p2.read_bytes() == station_raw_before)

            # re-run again -- gate still never arms, sidecars still not
            # byte-identical is FINE (dict key order can shuffle) but the
            # *content* must be idempotent and the gate files absent
            r2 = mig.migrate(root=root2, lore_path=lore_p2,
                             station_path=station_p2, today="2026-07-11")
            check("gate-off after 2nd run: ENABLED still absent",
                  not (root2 / "ENABLED").exists())
            check("gate-off after 2nd run: lore/station still untouched",
                  lore_p2.read_bytes() == lore_raw_before
                  and station_p2.read_bytes() == station_raw_before)
            check("gate-off: VERIFIED never created either",
                  not (root2 / "VERIFIED").exists())
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

        # ============================================================
        # 4. Empty / missing-input edge cases
        # ============================================================
        tmp3 = Path(tempfile.mkdtemp())
        try:
            root3 = tmp3 / "arcs"
            res4 = mig.migrate(root=root3, lore_path=tmp3 / "no-lore.json",
                               station_path=tmp3 / "no-station.json",
                               today="2026-07-11")
            check("missing lore/station files -> no crash, ok",
                  res4["ok"] is True)
            check("missing lore -> 0 arcs lifted", res4["arcs_lifted"] == 0)
            check("missing station -> 0 names reserved",
                  res4["names_reserved"] == 0)
            check("missing-input canon-diff still empty",
                  res4["canon_diff"] == [])
            check("missing-input: arcs.json still written w/ empty arcs",
                  json.loads((root3 / "arcs.json").read_text())["arcs"] == {})
        finally:
            shutil.rmtree(tmp3, ignore_errors=True)

        # ============================================================
        # 5. compute_canon_diff is honest, not hardcoded empty (defense in
        # depth: if a future edit ever stamped something aired, it must show)
        # ============================================================
        dirty_arcs = {"schema": 1, "seq": 0, "arcs": {
            "arc-x": {"title": "X", "facts": [
                {"fid": "f1", "kind": "outcome", "key": "k", "value": "v",
                 "aired": "2026-07-11"}],
                "beats": [{"bid": "b1", "stage": "PAYOFF", "status": "aired",
                          "aired_date": "2026-07-11"}]}}}
        dirty_civ = {"residents": {"cv-1": {
            "facts": [{"fid": "f1", "kind": "place", "key": "home",
                      "value": "somewhere", "aired": "2026-07-11"}],
            "appearances": [{"date": "2026-07-11", "aired": True}]}}}
        diffs = mig.compute_canon_diff(dirty_arcs, dirty_civ)
        check("dirty fixture: fact-aired flagged",
              any("fact" in d and "arc-x" in d for d in diffs))
        check("dirty fixture: beat-aired flagged",
              any("beat" in d and "arc-x" in d for d in diffs))
        check("dirty fixture: civilian fact-aired flagged",
              any("civilian" in d and "cv-1" in d for d in diffs))
        check("dirty fixture: civilian appearance-aired flagged",
              any("appearance" in d for d in diffs))

        # a lifted arc with NO payoff beat at all must be flagged (structure
        # sanity: payoff must be guaranteed)
        no_payoff = {"schema": 1, "arcs": {"arc-y": {
            "title": "Y", "facts": [],
            "beats": [{"bid": "b1", "stage": "SEEDED", "status": "pending",
                      "aired_date": None}]}}}
        diffs2 = mig.compute_canon_diff(no_payoff, {"residents": {}})
        check("missing-PAYOFF-beat structural check fires",
              any("no PAYOFF beat scheduled" in d for d in diffs2))

        # a clean arc really does produce an empty diff (sanity check the
        # negative doesn't false-positive)
        clean = {"schema": 1, "arcs": {"arc-z": goose}}
        diffs3 = mig.compute_canon_diff(clean, {"residents": {}})
        check("clean lifted arc -> empty canon-diff", diffs3 == [])

        # ============================================================
        # 6. Title-slug collision -> unique ids, never overwritten
        # ============================================================
        collide_lore = {"arcs": [
            {"title": "The Roundabout Fern Returns Yet Again",
             "premise": "a fern", "day": 1, "max_days": 4,
             "latest": "still there", "status": "active"},
            {"title": "The Roundabout Fern Returns Yet Somehow",
             "premise": "a different fern", "day": 1, "max_days": 4,
             "latest": "also still there", "status": "active"},
        ]}
        tmp4 = Path(tempfile.mkdtemp())
        try:
            root4 = tmp4 / "arcs"
            res5, *_ = run_migration(tmp4, collide_lore, {})
            arcs5 = json.loads((root4 / "arcs.json").read_text())["arcs"]
            check("slug-colliding titles both lifted", len(arcs5) == 2,
                  list(arcs5))
            check("slug-colliding ids are distinct",
                  len({a["id"] for a in arcs5.values()}) == 2)
            check("both titles preserved distinctly",
                  {a["title"] for a in arcs5.values()}
                  == {"The Roundabout Fern Returns Yet Again",
                      "The Roundabout Fern Returns Yet Somehow"})
        finally:
            shutil.rmtree(tmp4, ignore_errors=True)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
