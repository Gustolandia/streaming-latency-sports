#!/usr/bin/env python3
"""
general_method_power.py -- the rounds rule for freeze 44's blocks (docs/results/general_method/
DESIGN47.md, D47-11): how often the registered judge confirms each prediction in made-up blocks
drawn about pilot round a's runs, by the rule of version 45 (scripts/under_load_power.py).

The input is the pilot's run table, `general_method.py read --pilot`, which holds only the runs
that passed the integrity rule. A setup's pilot values are the means over its passing runs.

A made-up block has `rounds` runs of every setup the table holds. Each run is the setup's pilot
row with its readings drawn again, as version 45 drew its runs, from the lognormal with the pilot's
value as its mean and the pilot's own spread where the setup ran more than once, at least version
45's least spread:
  - each load state's tail means, IDLE_CV in the off-blocks and LOAD_CV in the on-blocks, each
    state drawn on its own, and their ratios and rises worked out again from the draws;
  - each share's complement, the part that missed, at LOAD_CV, so that no share passes 1;
  - the card's lag and the differences of the reads, at LOAD_CV;
  - the counts of misses and of false calls, and the checks of B, as the pilot read them.
The registered judge (scripts/general_method.py) then judges the made-up block as it will judge
the real one, and a prediction's power is the share of made-up blocks it confirms.

Drawn on their own, the two states of one run are given the spread of two whole runs, though they
share the run's connections and its path; that overstates a ratio within a run, and the
equivalence clauses (M3-a, KC-d, and A's parts) pay most for it. So beside the rule, never as its
input, `--spread pilot` draws each run's on/off ratios with the spread the pilot's own repeated
runs show, at least PILOT_CV_FLOOR, and the off-block tail at IDLE_CV, the on-block tail following.

The rule (version 45's, D47-11): the rounds are the least number from four up to twelve at which
every prediction whose pilot effect clears its margin is confirmed in at least POWER of the made-up
blocks. A prediction whose pilot effect does not clear its margin rests on the floor of four with
its power stated; one that no number up to twelve brings to POWER cannot be brought to the bar by
more rounds either, and is reported at the rounds the others need.

CLI:
    python scripts/general_method_power.py --pilot-table CSV [--pilot-table CSV ...]
        [--rounds 4] [--most 12] [--blocks 2000] [--seed 20261104] [--spread rule|pilot]
        [--out JSON]
"""
import argparse
import json
import math
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import general_method as gm  # noqa: E402
import under_load_power as ulp  # noqa: E402

#: Version 45's least spreads and bar.
IDLE_CV, LOAD_CV, POWER = ulp.IDLE_CV, ulp.LOAD_CV, ulp.POWER

#: The least spread `--spread pilot` gives a ratio within a run.
PILOT_CV_FLOOR = 0.02

#: The predictions the judge gives a verdict, as gm.judge names them; S and the described setups
#: have none.
PREDICTIONS = ("M1-a", "M1-b", "M1-c", "M2-a", "M2-b", "M2-c", "M3-a", "M3-b", "V-a", "N-a",
               "P-a", "KC-a", "KC-b", "KC-c", "KC-d", "KC-h", "C-a", "A")

#: The tail means each state carries: every TAILED quantity over all messages and over those that
#: found a request waiting, and the own-tail means.
TAILS = tuple("%s%s" % (prefix, q) for prefix in ("", "waiting_") for q in gm.TAILED) + (
    "D_own", "Tc_req")

#: Readings drawn at LOAD_CV with their sign kept.
SIGNED = ("q_p99", "m1_tail_diff", "m1_tail_diff_on")

#: The judge's verdict that counts as confirmed.
CONFIRMED = "confirmed"


def _number(value):
    """A float, or None for a missing or empty value."""
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_share(name):
    """A reading that is a share of messages or of time: never below 0 or above 1."""
    return name.endswith("_share") or "_share_" in name


def setup_name(setup):
    """The judged setup's name for a pilot's one: the id without "-pilot"."""
    return setup[:-len("-pilot")] if setup.endswith("-pilot") else setup


def pilot_setups(rows):
    """{setup: [rows]} of the pilot's runs, by the judged setup's name, in order."""
    out = {}
    for r in rows:
        if r.get("pilot") in (True, "True"):
            out.setdefault(setup_name(r["setup"]), []).append(r)
    return dict(sorted(out.items()))


def spread(values):
    """The coefficient of variation of `values`, None for fewer than two or a zero mean."""
    known = [v for v in values if v is not None]
    if len(known) < 2:
        return None
    m = statistics.fmean(known)
    return None if m == 0 else statistics.pstdev(known) / abs(m)


def profile(runs):
    """One setup's pilot: its first row's settings, each numeric reading the mean over its runs,
    and each reading's spread over them (None from one run)."""
    base = dict(runs[0])
    cv = {}
    for name in runs[0]:
        values = [_number(r.get(name)) for r in runs]
        if all(v is None for v in values) or isinstance(runs[0][name], bool):
            continue
        known = [v for v in values if v is not None]
        if name not in ("rate", "depth", "depth_asked", "prefetch", "ack_batch", "load_pct"):
            base[name] = statistics.fmean(known)
        cv[name] = spread(known)
    return base, cv


def ratio_spreads(profiles):
    """{tail: the median over the setups that ran more than once of its on/off ratio's spread}, for
    the setups that ran once."""
    found = {}
    for _, (_, cv) in profiles.items():
        for tail in TAILS:
            value = cv.get(tail + "_ratio")
            if value is not None:
                found.setdefault(tail, []).append(value)
    return {tail: statistics.median(v) for tail, v in found.items()}


def draw(rng, mean, cv):
    """One run's value from the lognormal with this mean and coefficient of variation; a value of
    0 stays 0 and a negative one keeps its sign."""
    if mean == 0:
        return 0.0
    return math.copysign(ulp.draw(rng, abs(mean), cv), mean)


def made_up_run(rng, base, cv, index, mode="rule", ratio_cv=None, scale=1.0):
    """One made-up run of a setup from its pilot profile: (`base`, `cv`) as profile() gives them.
    `scale` multiplies each state's on-block excess over its off-block, to ask how the rule fares
    with a smaller effect than the pilot's."""
    run = dict(base, pilot=False, setup=setup_name(base["setup"]),
               run="%s_m%d" % (setup_name(base["setup"]), index))
    for tail in TAILS:
        on, off = (_number(base.get("%s_tail_%s" % (tail, s))) for s in ("on", "off"))
        if on is None or off is None:
            continue
        on = off + scale * (on - off)
        if mode == "pilot":
            low = draw(rng, off, max(cv.get(tail + "_tail_off") or 0.0, IDLE_CV))
            r_cv = cv.get(tail + "_ratio")
            if r_cv is None:
                r_cv = (ratio_cv or {}).get(tail, PILOT_CV_FLOOR)
            high = low * draw(rng, on / off, max(r_cv, PILOT_CV_FLOOR)) if off else on
        else:
            low = draw(rng, off, max(cv.get(tail + "_tail_off") or 0.0, IDLE_CV))
            high = draw(rng, on, max(cv.get(tail + "_tail_on") or 0.0, LOAD_CV))
        run["%s_tail_off" % tail], run["%s_tail_on" % tail] = low, high
        run[tail + "_ratio"] = gm._ratio(high, low)
        run[tail + "_rise"] = high - low
    w = (run.get("W_tail_on"), run.get("W_tail_off"), run.get("E2_tail_on"),
         run.get("E2_tail_off"))
    if "e2_share" in base and None not in w:
        run["e2_share"] = None if w[0] <= w[1] else 1.0 - (w[2] - w[3]) / (w[0] - w[1])
    for name, value in base.items():
        number = _number(value)
        if number is None or name == "e2_share" or isinstance(value, bool):
            continue
        if is_share(name):
            if number >= 0.5:
                run[name] = min(1.0, max(0.0, 1.0 - draw(rng, 1.0 - number, LOAD_CV)))
            else:
                run[name] = min(1.0, max(0.0, draw(rng, number, LOAD_CV)))
        elif name in SIGNED:
            run[name] = draw(rng, number, LOAD_CV)
    return run


def made_up_block(rng, profiles, rounds, mode="rule", scale=1.0):
    ratio_cv = ratio_spreads(profiles) if mode == "pilot" else None
    rows = []
    for _, (base, cv) in profiles.items():
        for i in range(rounds):
            rows.append(made_up_run(rng, base, cv, i, mode, ratio_cv, scale))
    return rows


def verdicts(rows):
    """{prediction: its verdict} from the registered judge; no interval is drawn, since none
    decides a verdict."""
    out = gm.judge(rows, draws=0)
    return dict((p, out[p]["verdict"]) for p in PREDICTIONS)


def clears(profiles):
    """{prediction: whether the judge confirms it on the pilot's own values}: each setup's pilot
    profile, twice and undrawn, so that every clause sees its margin at the pilot's means."""
    rows = []
    for _, (base, _) in profiles.items():
        for i in range(2):
            rows.append(dict(base, pilot=False, setup=setup_name(base["setup"]),
                             run="%s_p%d" % (setup_name(base["setup"]), i)))
    return dict((p, v == CONFIRMED) for p, v in verdicts(rows).items())


def power(profiles, rounds, blocks, seed, mode="rule", scale=1.0):
    """{prediction: share of `blocks` made-up blocks the judge confirms it in}."""
    rng = random.Random(seed)
    counts = dict.fromkeys(PREDICTIONS, 0)
    for _ in range(blocks):
        for p, v in verdicts(made_up_block(rng, profiles, rounds, mode, scale)).items():
            counts[p] += v == CONFIRMED
    return dict((p, counts[p] / float(blocks)) for p in PREDICTIONS)


def rounds_needed(profiles, blocks, seed, start=4, most=12, mode="rule"):
    """The rule: (rounds, {prediction: power} there, the predictions that clear their margin, those
    of them no number up to `most` brings to POWER). The rounds are the least from `start` at which
    every prediction that clears its margin and can be brought to the bar reaches it; `start`
    where none can."""
    clear = clears(profiles)
    wanted = [p for p in PREDICTIONS if clear[p]]
    at = {start: power(profiles, start, blocks, seed, mode)}
    if all(at[start][p] >= POWER for p in wanted):
        return start, at[start], wanted, []
    at[most] = power(profiles, most, blocks, seed, mode)
    unreachable = [p for p in wanted if at[most][p] < POWER]
    reachable = [p for p in wanted if p not in unreachable]
    rounds = start
    while not all(at[rounds][p] >= POWER for p in reachable):
        rounds += 1
        if rounds not in at:
            at[rounds] = power(profiles, rounds, blocks, seed, mode)
    return rounds, at[rounds], wanted, unreachable


def read_tables(paths):
    rows = []
    for path in paths:
        rows.extend(gm.read_table(path))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pilot-table", action="append", required=True)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--most", type=int, default=12)
    ap.add_argument("--blocks", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261104)
    ap.add_argument("--spread", choices=("rule", "pilot"), default="rule")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    profiles = dict((s, profile(r)) for s, r in pilot_setups(read_tables(args.pilot_table))
                    .items())
    if not profiles:
        print("ERROR: the tables hold no pilot run", file=sys.stderr)
        return 1
    print("setups: %d, from %d pilot runs" % (len(profiles), sum(
        len(r) for r in pilot_setups(read_tables(args.pilot_table)).values())))
    clear = clears(profiles)
    print("clears its margin at the pilot's means: %s" % ", ".join(
        "%s %s" % (p, "yes" if clear[p] else "no") for p in PREDICTIONS))
    rounds, at, wanted, unreachable = rounds_needed(profiles, args.blocks, args.seed,
                                                    args.rounds, args.most, args.spread)
    halved = power(profiles, rounds, args.blocks, args.seed, args.spread, 0.5)
    print("the rule asks %d rounds (%s spread): %s" % (rounds, args.spread, "  ".join(
        "%s %.3f" % (p, at[p]) for p in PREDICTIONS)))
    if unreachable:
        print("no number of rounds up to %d brings %s to %.2f" % (
            args.most, ", ".join(unreachable), POWER))
    print("with the load's excess halved: %s" % "  ".join(
        "%s %.3f" % (p, halved[p]) for p in PREDICTIONS))
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"rounds": rounds, "spread": args.spread, "blocks": args.blocks,
                       "seed": args.seed, "power": at, "power_excess_halved": halved,
                       "clears": clear, "wanted": wanted, "unreachable": unreachable,
                       "most": args.most, "bar": POWER, "idle_cv": IDLE_CV, "load_cv": LOAD_CV},
                      fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("OK -> %s" % args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
