#!/usr/bin/env python3
"""
wp_baselines.py
Give the win-probability proxy's scores something to be compared against.

The paper reports a ranked probability score of about 0.24 and an expected calibration error of
0.054 with nothing beside them, which makes both uninterpretable: a reader cannot tell whether
0.24 is good, mediocre or worse than guessing. Skill scores are only meaningful relative to a
reference forecast.

Three references, in increasing order of difficulty:

  uniform     - 1/3 each. The zero-information forecast.
  base rate   - the corpus-wide home/draw/away frequencies, ignoring game state entirely.
                Beating this shows the model uses the state at all.
  score-only  - the empirical outcome distribution conditioned on the current goal difference,
                ignoring time remaining and red cards. Beating this shows the Skellam structure
                adds something over a lookup table, which is the claim that actually matters.

Reported as a skill score: 1 - RPS_model / RPS_reference. Positive means better than the
reference, zero means no better, negative means worse.

CLI:
    python scripts/wp_baselines.py --events-dir data/raw/statsbomb/<sha>/events \
        --out docs/results/win_probability
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import win_probability as wp


def rps(p_win, p_draw, p_loss, outcome):
    """Ranked probability score for a three-outcome forecast (lower is better)."""
    return wp.ranked_probability_score(p_win, p_draw, p_loss, outcome)


def base_rates(outcomes):
    """Frequencies of (win, draw, loss); uniform when there is nothing to count.

    Outcomes use win_probability's convention: 1 home win, 0 draw, -1 home loss.
    """
    c = {1: 0, 0: 0, -1: 0}
    for o in outcomes:
        if o in c:
            c[o] += 1
    total = sum(c.values())
    if total == 0:
        return (1 / 3.0, 1 / 3.0, 1 / 3.0)
    return (c[1] / total, c[0] / total, c[-1] / total)


def score_only_table(samples):
    """Empirical outcome distribution per goal difference, from (score_diff, outcome) pairs.

    Deliberately ignores time remaining: this is the lookup table a analyst would build without
    any model, and it is the reference the Skellam proxy has to beat to justify itself.
    """
    table = {}
    buckets = {}
    for diff, outcome in samples:
        buckets.setdefault(int(diff), []).append(outcome)
    for diff, outs in buckets.items():
        table[diff] = base_rates(outs)
    return table


def lookup(table, diff, fallback=(1 / 3.0, 1 / 3.0, 1 / 3.0)):
    """Table lookup with a fallback for goal differences never observed."""
    return table.get(int(diff), fallback)


def skill_score(model_rps, reference_rps):
    """1 - model/reference. Positive is better than the reference."""
    if reference_rps is None or reference_rps <= 0 or np.isnan(reference_rps):
        return float("nan")
    return 1.0 - (model_rps / reference_rps)


def evaluate(samples, team_rate=wp.DEFAULT_TEAM_RATE):
    """Mean RPS for the model and each reference over (diff, frac_remaining, red, outcome)."""
    if not samples:
        return pd.DataFrame()
    outcomes = [s[3] for s in samples]
    br = base_rates(outcomes)
    tbl = score_only_table([(s[0], s[3]) for s in samples])

    rows = {"model": [], "uniform": [], "base_rate": [], "score_only": []}
    for diff, frac, red, outcome in samples:
        pw, pd_, pl = wp.win_probability(diff, frac, team_rate=team_rate, red_diff=red)
        rows["model"].append(rps(pw, pd_, pl, outcome))
        rows["uniform"].append(rps(1 / 3.0, 1 / 3.0, 1 / 3.0, outcome))
        rows["base_rate"].append(rps(br[0], br[1], br[2], outcome))
        s = lookup(tbl, diff)
        rows["score_only"].append(rps(s[0], s[1], s[2], outcome))

    model_mean = float(np.mean(rows["model"]))
    out = []
    for name in ("uniform", "base_rate", "score_only"):
        ref = float(np.mean(rows[name]))
        out.append({"reference": name, "reference_rps": ref, "model_rps": model_mean,
                    "skill_score": skill_score(model_mean, ref),
                    "n_states": len(samples)})
    return pd.DataFrame(out)


def match_states(events, grid_seconds=60):
    """Sampled (goal difference, fraction remaining, red difference) states for one match.

    Rebuilt from parse_match rather than wp_timeline, which returns only the win probability
    and would not expose the game state a score-only baseline needs.
    """
    home, away, goals, reds, match_len = wp.parse_match(events)
    if not match_len:
        return []
    states, t = [], 0.0
    while t <= match_len:
        diff = (sum(1 for gt, tm in goals if gt <= t and tm == home)
                - sum(1 for gt, tm in goals if gt <= t and tm == away))
        red = (sum(1 for rt, tm in reds if rt <= t and tm == home)
               - sum(1 for rt, tm in reds if rt <= t and tm == away))
        states.append((diff, max(0.0, (match_len - t) / match_len), red))
        t += grid_seconds
    return states


def collect_samples(events_dir, grid_seconds=60, limit=0):
    """(goal difference, fraction remaining, red difference, final outcome) per sampled state."""
    import json
    samples = []
    files = sorted(Path(events_dir).glob("*.json"))
    if limit:
        files = files[:limit]
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                events = json.load(f)
        except (OSError, ValueError):
            continue
        if not events:
            continue
        try:
            outcome = wp.final_outcome(events)
            states = match_states(events, grid_seconds)
        except Exception:      # noqa: BLE001 - a malformed match must not stop the sweep
            continue
        for diff, frac, red in states:
            samples.append((diff, frac, red, outcome))
    return samples


def main(argv=None):
    ap = argparse.ArgumentParser(description="Baselines for the win-probability proxy")
    ap.add_argument("--events-dir", required=True)
    ap.add_argument("--grid-seconds", type=int, default=60)
    ap.add_argument("--team-rate", type=float, default=wp.DEFAULT_TEAM_RATE)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="docs/results/win_probability")
    args = ap.parse_args(argv)

    samples = collect_samples(args.events_dir, args.grid_seconds, args.limit)
    if not samples:
        print(f"No usable game states under {args.events_dir}")
        return 1
    df = evaluate(samples, args.team_rate)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "wp_baselines.csv", index=False)

    print(f"== win-probability skill against references ({len(samples)} game states) ==")
    print(df.to_string(index=False))
    print("skill > 0 beats the reference; <= 0 means the model adds nothing over it.")
    print(f"Wrote {out}/wp_baselines.csv")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
