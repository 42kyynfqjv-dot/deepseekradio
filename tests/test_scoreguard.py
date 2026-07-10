"""Scoreguard fixtures: catch every lie, touch no truth, inject what's missing.

Run directly (no pytest needed):  python3 tests/test_scoreguard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.scoreguard import enforce_scoreboard, build_facts

GAME = {
    "home": "Montreal Apologies", "away": "New York Gridlock",
    "home_key": "mtl", "away_key": "nyg", "arena": "Le Centre du Regret",
    "rosters": {
        "home": {"skaters": ["Doug Bouchard", "Erik Larsson", "Petr Novak",
                             "Sam Okafor", "Jean Lefebvre", "Ty Kowalski",
                             "Al Roy", "Ben Girard", "Max Dube"],
                 "goalie": "Rene Tremblay"},
        "away": {"skaters": ["Vic Marino", "Lou Costa", "Dan Ferraro",
                             "Joe Kessler", "Art Quinn", "Hal Bishop",
                             "Gus Weber", "Pat Doyle", "Sid Frank"],
                 "goalie": "Otto Kranz"}},
    "refs": ["Referee Ada Cole", "Referee Bo Iyer"],
}
PBP = {"speaker": "Walt Fontaine", "voice": "am_onyx", "speed": 0.97}


def L(text, speaker="Walt Fontaine"):
    return {"speaker": speaker, "voice": "am_onyx", "speed": 0.97, "text": text}


def goal(scorer, board, clock="08:12", period=2, team="home", assist=None,
         strength="EV"):
    m, s = clock.split(":")
    return {"type": "goal", "team": team, "scorer": scorer, "assist": assist,
            "period": period, "clock": clock, "secs": int(m) * 60 + int(s),
            "strength": strength, "net_empty": False, "board": list(board)}


def facts(events=(), board=(1, 1), pp=False, en=False, prior=(), allow=(),
          period=2, lo="05:00", hi="10:00"):
    chunk = {"board_in": list(board), "events": list(events),
             "pp_span": pp, "en_span": en}
    return build_facts(GAME, list(prior), chunk, mode="live", pbp=PBP,
                       allow_pairs=allow, period=period,
                       clock_lo=lo, clock_hi=hi)


ok = fail = 0


def check(name, cond, note=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print(f"FAIL: {name}  {note}")


def keeps(name, text, f):
    out = enforce_scoreboard([L(text)], f)
    check(name, out and out[0].get("text") == text
          and not out[0].get("_enforced"), f"got {out!r}")


def fixes(name, text, f):
    out = enforce_scoreboard([L(text)], f)
    ln = out[0]
    check(name, ln.get("_enforced") is True and ln["text"] != text,
          f"got {ln!r}")
    return ln


# ---------------------------------------------------- false positives (keep)
keeps("record_triple", "The Apologies come in at 10-4-2 on the season.", facts())
keeps("shots_pair", "Shots are 31-28 Montreal after two.", facts())
keeps("oh_for_three", "They're 0-for-3 on the power play tonight.", facts(pp=True))
keeps("allow_slate", "Regina beat Fargo 5 to 2 earlier tonight.",
      facts(allow=[(5, 2)]))
keeps("allow_past", "They beat the Gridlock 4-2 last Saturday.",
      facts(allow=[(4, 2)]))
keeps("idiom_onetwo", "That's a real one-two punch on the top line.", facts())
keeps("save_goalie", "What a save by Tremblay!", facts())
keeps("rush_2on1", "Odd-man rush, it's a 2-on-1!", facts())
keeps("modality_bet", "I bet we take them 5-1 next week.", facts())
keeps("modality_if", "If we'd buried that chance it's 3-2 us.", facts())
keeps("margin_ok", "Montreal up by two.", facts(board=(3, 1)))
keeps("tie_ok", "We're even at two.", facts(board=(2, 2)))
keeps("clock_ok", "Kowalski at 7:45 of the second, what a move.", facts())
keeps("minute_to_go", "Under a minute to go here.", facts())
keeps("clock_no_collide", "The clock reads 12:34 somewhere in the rafters.",
      facts())
keeps("remaining_ok", "14:30 left in the second, still plenty of time.", facts())
keeps("stops_named_goalie", "Tremblay stops Marino right there.", facts())
keeps("stops_unnamed", "Nothing stops Bouchard tonight.", facts())

f_call = facts(events=[goal("Doug Bouchard", (2, 1))])
out = enforce_scoreboard([L("Bouchard buries it! 2-1!")], f_call)
check("goal_call_kept", len(out) == 1 and not out[0].get("_enforced"),
      f"got {out!r}")

out = enforce_scoreboard([L("He went 4-3 in the dot tonight.")], facts())
check("bare_pair_logged_kept", len(out) == 1 and not out[0].get("_enforced")
      and out[0]["text"].startswith("He went"), f"got {out!r}")

prior2L = [goal("Erik Larsson", (1, 0), "03:00", 1),
           goal("Erik Larsson", (2, 0), "15:00", 1)]
keeps("hat_trick_ok", "A hat trick for Larsson, the building erupts!",
      facts(events=[goal("Erik Larsson", (3, 1), "06:30", 2)], board=(2, 1),
            prior=prior2L))
keeps("second_of_night_ok", "Bouchard scores! His second of the night!",
      facts(events=[goal("Doug Bouchard", (2, 1), "07:10", 2)],
            prior=[goal("Doug Bouchard", (1, 0), "04:00", 1)]))

# pregame: frozen board, allow_pairs still honored, no locator checks
f_pre = build_facts(GAME, [], None, mode="neutral", pbp=PBP,
                    allow_pairs=[(4, 2)], period=None)
keeps("pregame_allow", "Last week they won 4-2, remember.", f_pre)

# intermission: board frozen at the last prior board
priorN = [goal("Doug Bouchard", (1, 0), "05:00", 1),
          goal("Doug Bouchard", (2, 0), "11:00", 2),
          goal("Vic Marino", (2, 1), "15:00", 2, team="away")]
f_mid = build_facts(GAME, priorN, None, mode="neutral", pbp=PBP, period=None)
keeps("neutral_frozen_ok", "It's 2-1 at the break.", f_mid)
fixes("neutral_frozen_bad", "It's 3-1 for the boys.", f_mid)

# postgame: final is the only pair, feats vs full-game tallies, modality free
all_ev = [goal("Erik Larsson", (1, 0), "03:11", 1),
          goal("Vic Marino", (1, 1), "08:40", 1, team="away"),
          goal("Erik Larsson", (2, 1), "12:02", 2),
          goal("Vic Marino", (2, 2), "04:59", 3, team="away"),
          goal("Erik Larsson", (3, 2), "14:20", 3)]
f_post = build_facts(GAME, all_ev, None, mode="postgame", pbp=PBP,
                     final=[3, 2], period=None)
keeps("postgame_final_ok", "They took it 3-2 tonight.", f_post)
keeps("postgame_hat_ok", "Hat trick for Larsson tonight.", f_post)
keeps("postgame_modality", "Next Saturday they'll run them out of the "
      "building, that's my prediction.", f_post)
fixes("postgame_wrong_pair", "Final score 4-2 tonight.", f_post)

# ------------------------------------------------------ true positives (fix)
ln = fixes("pair_unreachable", "It's 4-1 here in the second.", facts())
check("pair_fix_truthful", "Apologies 1" in ln["text"]
      and "Gridlock 1" in ln["text"], f"got {ln['text']!r}")

f2 = facts(events=[goal("Doug Bouchard", (2, 1))])
out = enforce_scoreboard([L("It's 4-1 here in the second.")], f2)
check("pair_fix_two_boards", out[0].get("_enforced")
      and "Apologies 1" in out[0]["text"], f"got {out[0]!r}")
check("pair_fix_then_inject", len(out) == 2 and "Bouchard" in out[1]["text"],
      f"got {out!r}")

out = enforce_scoreboard([L("Bouchard buries it, 2-1!"),
                          L("Big stop at the other end."),
                          L("Still one to one here.")], f_call)
check("stale_board_replaced", len(out) == 3 and out[2].get("_enforced")
      and "Apologies 2" in out[2]["text"] and "Gridlock 1" in out[2]["text"],
      f"got {out!r}")
check("stale_board_others_kept", not out[0].get("_enforced")
      and not out[1].get("_enforced"), f"got {out!r}")

ln = fixes("attribution_flip", "Gridlock lead two to one.", facts(board=(2, 1)))
check("attribution_fix_truthful", "Apologies 2" in ln["text"],
      f"got {ln['text']!r}")
fixes("margin_wrong", "They're up by three.", facts(board=(2, 1)))
ln = fixes("phantom_scorer", "Demchuk scores from the slot!", facts())
check("phantom_scorer_gone", "Demchuk" not in ln["text"], f"got {ln['text']!r}")
fixes("save_to_skater", "Big save by Bouchard!", facts())
fixes("phantom_hat_trick", "HAT TRICK for Larsson!", facts(prior=prior2L))
fixes("phantom_pp", "They're on the power play here.", facts())
fixes("phantom_en", "The net is empty!", facts())
fixes("phantom_injury", "He's helped off, won't return.", facts())
fixes("wrong_period", "Early in the third, still tight.", facts())
fixes("clock_outside", "16:40 of the first and counting.", facts(period=1))
fixes("premature_shootout", "We're headed to a shootout, folks.",
      facts(period=3))
fixes("word_form_pair", "It's three to one out there.", facts())
fixes("endash_pair", "The score is 3–2 right now.", facts())
fixes("remaining_outside", "3:00 left in the second, folks.", facts())

# ---------------------------------------------------------------- injection
f_inj = facts(events=[goal("Sam Okafor", (2, 1), "08:12", 2,
                           assist="Erik Larsson")])
out = enforce_scoreboard([L("What a shift down low."),
                          L("It's 2-1 now and the building knows it.")], f_inj)
check("inject_count", len(out) == 3, f"got {out!r}")
check("inject_positioned", out[1].get("_enforced")
      and "Okafor" in out[1]["text"] and "from Erik Larsson" in out[1]["text"]
      and out[2]["text"].startswith("It's 2-1"), f"got {out!r}")
check("inject_pbp_voice", out[1]["speaker"] == "Walt Fontaine"
      and out[1]["voice"] == "am_onyx", f"got {out[1]!r}")

f_empty = facts(events=[goal("Doug Bouchard", (2, 1), "06:15", 2),
                        goal("Vic Marino", (2, 2), "09:40", 2, team="away")])
out = enforce_scoreboard([], f_empty)
check("inject_parse_failure_beat", len(out) == 2
      and "Bouchard" in out[0]["text"] and "Marino" in out[1]["text"]
      and all(o.get("_enforced") for o in out), f"got {out!r}")

pen = {"type": "penalty", "team": "away", "player": "Pat Doyle",
       "call": "tripping", "period": 2, "clock": "07:05", "secs": 425}
out = enforce_scoreboard([L("The crowd wants a whistle here.")],
                         facts(events=[pen], pp=True))
check("inject_penalty", len(out) == 2 and out[1].get("_enforced")
      and "Doyle" in out[1]["text"] and "tripping" in out[1]["text"],
      f"got {out!r}")

# postgame audit is skipped — the game already aired, nothing to inject
f_post_g = build_facts(GAME, all_ev, None, mode="postgame", pbp=PBP,
                       final=[3, 2], period=None)
out = enforce_scoreboard([L("What a night at the rink.")], f_post_g)
check("postgame_no_audit", len(out) == 1, f"got {out!r}")

# -------------------------------------------------------------- idempotence
r1 = enforce_scoreboard([L("It's 4-1 here in the second."),
                         L("It's 2-1 now and what a game.")], f_inj)
r2 = enforce_scoreboard(r1, f_inj)
check("idempotent_mixed", r1 == r2, f"\n r1={r1!r}\n r2={r2!r}")
check("idempotent_shape", len(r1) == 3 and r1[0].get("_enforced")
      and "Okafor" in r1[1]["text"], f"got {r1!r}")

r1 = enforce_scoreboard([], f_empty)
r2 = enforce_scoreboard(r1, f_empty)
check("idempotent_injected", r1 == r2, f"\n r1={r1!r}\n r2={r2!r}")

# --------------------------------------------------------- build_facts units
prior_t = [goal("Doug Bouchard", (1, 0), "03:00", 1),
           goal("Vic Marino", (1, 1), "09:00", 1, team="away")]
f = facts(events=[goal("Doug Bouchard", (2, 1), "07:00", 2)], prior=prior_t)
check("tally_cross_beat", f["tallies"]["bouchard"] == 2
      and f["tallies"]["marino"] == 1, f"got {f['tallies']!r}")
check("tally_period_scoped", f["period_tallies"][("bouchard", 1)] == 1
      and f["period_tallies"][("bouchard", 2)] == 1,
      f"got {f['period_tallies']!r}")
check("boards_sequence", f["boards"] == [(1, 1), (2, 1)], f"got {f['boards']!r}")
check("goalie_sets", "tremblay" in f["goalies"] and "kranz" in f["goalies"]
      and "bouchard" not in f["goalies"], f"got {f['goalies']!r}")
check("names_include_refs_pbp", "cole" in f["names_ok"]
      and "walt fontaine" in f["names_ok"] and "gridlock" in f["names_ok"],
      "names_ok missing entries")

# --------------------------------------------------- regression: idiom leaks
# board 3-1, no goal this beat -> "2-1" is a hallucinated score no matter the
# idiom that introduces it (the pre-fix guard leaked these three)
fL = facts(board=(3, 1))
fixes("idiom_makes_it", "That makes it 2-1.", fL)
fixes("idiom_thats", "That's 2-1 now.", fL)
fixes("idiom_now", "2-1 now, and the building is up.", fL)
fixes("score_for_team", "It's 4-2 for Montreal.", fL)
# genuine stats with a bare pair survive
keeps("stat_dot", "He went 4-3 in the dot tonight.", fL)
keeps("stat_shots", "Shots are 5-4 New York after the rush.", fL)
keeps("stat_faceoffs", "Faceoffs 8-6 Montreal in the circle.", fL)

# ------------------------------------------ regression: multiword-city tokens
# home Montreal LEADS 3-1; the bare common word "new" must NOT register a
# phantom away hit that flips attribution and clobbers a correct line
keeps("multiword_new_no_attr",
      "New York brings new energy and pushes up the ice.", fL)
keeps("multiword_long_no_attr", "A long change coming up for both benches.", fL)
# the nickname still drives a REAL attribution flip (away can't lead 3-1)
fixes("nickname_attr_flip", "Gridlock lead it here.", fL)

# --- interview anecdotes: implicit feats in PAST context are stories, not claims
keeps("anecdote_hat_trick", "Back in juniors I scored a hat trick on my "
      "birthday, Bouchard says.", facts())
keeps("anecdote_brace_career", "Best brace of his career, years ago in Fargo.",
      facts())
# ...but a TONIGHT hat trick with zero tallies is still a lie and still dies
fixes("phantom_ht_tonight", "A hat trick tonight for Larsson!", facts())
# and explicit of-the-night ordinals check even next to past words
fixes("explicit_ord_checks", "Earlier tonight he potted his third of the "
      "night, Larsson unstoppable.", facts())
# "back in the ..." is play language, not past context — attribution still live
fixes("back_in_the_not_past", "Back in the lineup and the Gridlock lead it "
      "here.", fL)

# --- postgame retrospection: strength talk is description, not a state claim
_PEN_EV = {"type": "penalty", "team": "away", "player": "Otto Kranz",
           "call": "hooking", "period": 2, "clock": "07:00", "secs": 1620}
pf_pen = build_facts(GAME, [goal("Doug Bouchard", (2, 1)), _PEN_EV], None,
                     mode="postgame", pbp=PBP, final=(3, 1))
keeps("postgame_pp_talk", "That power play goal in the second was the "
      "difference tonight.", pf_pen)
pf_clean = build_facts(GAME, [goal("Doug Bouchard", (2, 1))], None,
                       mode="postgame", pbp=PBP, final=(3, 1))
fixes("postgame_pp_invented", "That power play goal in the second was the "
      "difference tonight.", pf_clean)
# "even strength" is a goal type, never a tie claim — 3-1 final is not tied
keeps("even_strength_not_tie", "The Bouchard goal was even strength, and "
      "it's 3-1 final.", pf_pen)

if fail:
    print(f"\n{fail}/{ok + fail} failed")
    sys.exit(1)
print(f"all {ok} checks pass")
