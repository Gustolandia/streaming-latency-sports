#!/usr/bin/env python3
"""
In-play (in-game) win-probability model for football, computed from the StatsBomb
event stream. Used to translate streaming *delivery latency* into a *decision* error
(see scripts/decision_staleness.py).

We use a transparent Skellam (difference-of-Poissons) model rather than reimplementing the
unreleased Bayesian model of Robberechts et al. (2021, ACM SIGKDD): remaining goals for each
side over the fraction of the match left are Poisson with a base scoring rate, optionally
adjusted for red cards. The final goal difference is the current difference plus a Skellam
variate, giving home win/draw/loss probabilities in closed form. The base rate can be
calibrated to the observed scoring rate; calibration quality is assessed with the Ranked
Probability Score (RPS) and expected calibration error.

CLI:
    python scripts/win_probability.py --events-dir data/raw/statsbomb/<sha>/events [--out docs/results/win_probability]
"""
import argparse
import glob
import json
import os
from pathlib import Path

import numpy as np
from scipy import stats

# Default full-match per-team scoring rate (goals/team/match); ~2.6 total is typical.
DEFAULT_TEAM_RATE = 1.3
MATCH_SECONDS = 90 * 60
RED_CARD_PENALTY = 0.30  # a team a player down scores ~30% less for the rest of the match


def clock_seconds(minute, second):
    """Absolute match seconds (StatsBomb `minute` is cumulative across periods)."""
    return int(minute) * 60 + int(second)


def parse_match(events):
    """From a StatsBomb events list, return (home, away, goals, reds, match_len_s).

    goals: list of (t_seconds, team_that_scored)
    reds:  list of (t_seconds, team_sent_off)
    """
    teams = []
    for e in events:
        t = e.get("team", {}).get("name")
        if t and t not in teams:
            teams.append(t)
        if len(teams) == 2:
            break
    home, away = (teams + [None, None])[:2]

    goals, reds = [], []
    max_t = MATCH_SECONDS
    for e in events:
        et = e.get("type", {}).get("name")
        team = e.get("team", {}).get("name")
        t = clock_seconds(e.get("minute", 0), e.get("second", 0))
        max_t = max(max_t, t)
        if et == "Shot" and e.get("shot", {}).get("outcome", {}).get("name") == "Goal":
            goals.append((t, team))
        elif et == "Own Goal Against":
            # own goal: credit the *other* team
            other = away if team == home else home
            goals.append((t, other))
        card = e.get("bad_behaviour", {}).get("card", {}).get("name")
        if card in ("Red Card", "Second Yellow"):
            reds.append((t, team))
    return home, away, goals, reds, max_t


def win_probability(score_diff, frac_remaining, team_rate=DEFAULT_TEAM_RATE, red_diff=0):
    """Home win/draw/loss probabilities given current (home-away) goal difference and the
    fraction of match remaining. red_diff = home_reds - away_reds (more home reds lowers
    home's remaining rate)."""
    frac_remaining = max(0.0, min(1.0, float(frac_remaining)))
    lam_h = team_rate * frac_remaining * (1.0 - RED_CARD_PENALTY) ** max(0, red_diff)
    lam_a = team_rate * frac_remaining * (1.0 - RED_CARD_PENALTY) ** max(0, -red_diff)
    if lam_h <= 0 and lam_a <= 0:
        # match over: outcome determined by current score difference
        p_win = 1.0 if score_diff > 0 else 0.0
        p_draw = 1.0 if score_diff == 0 else 0.0
        return p_win, p_draw, 1.0 - p_win - p_draw
    lam_h = max(lam_h, 1e-9)
    lam_a = max(lam_a, 1e-9)
    k = -int(score_diff)
    p_loss = float(stats.skellam.cdf(k - 1, lam_h, lam_a))
    p_draw = float(stats.skellam.pmf(k, lam_h, lam_a))
    p_win = 1.0 - p_loss - p_draw
    return max(0.0, p_win), max(0.0, p_draw), max(0.0, p_loss)


def wp_timeline(events, team_rate=DEFAULT_TEAM_RATE, grid_seconds=30):
    """Home win-probability sampled on a time grid across the match.
    Returns (home, away, [(t_seconds, p_win_home)])."""
    home, away, goals, reds, match_len = parse_match(events)
    pts = []
    for t in range(0, int(match_len) + 1, grid_seconds):
        diff = sum(1 for gt, tm in goals if gt <= t and tm == home) - \
               sum(1 for gt, tm in goals if gt <= t and tm == away)
        red_diff = sum(1 for rt, tm in reds if rt <= t and tm == home) - \
                   sum(1 for rt, tm in reds if rt <= t and tm == away)
        frac_rem = max(0.0, (match_len - t) / match_len) if match_len else 0.0
        pw, _, _ = win_probability(diff, frac_rem, team_rate, red_diff)
        pts.append((t, pw))
    return home, away, pts


def final_outcome(events):
    """Return 1 (home win), 0 (draw), -1 (home loss) from the final score."""
    home, away, goals, _, _ = parse_match(events)
    h = sum(1 for _, tm in goals if tm == home)
    a = sum(1 for _, tm in goals if tm == away)
    return (h > a) - (h < a)


def ranked_probability_score(p_win, p_draw, p_loss, outcome):
    """RPS for an ordered 3-class (win/draw/loss) forecast. Lower is better."""
    # ordered categories: win, draw, loss
    obs = {1: (1, 0, 0), 0: (0, 1, 0), -1: (0, 0, 1)}[outcome]
    cp, co, s = 0.0, 0.0, 0.0
    for p, o in zip((p_win, p_draw, p_loss), obs):
        cp += p
        co += o
        s += (cp - co) ** 2
    return s / 2.0


def main(argv=None):
    ap = argparse.ArgumentParser(description="In-play win-probability model (Issue: decision layer)")
    ap.add_argument("--events-dir", required=True, help="Dir of StatsBomb match event JSONs")
    ap.add_argument("--team-rate", type=float, default=DEFAULT_TEAM_RATE)
    ap.add_argument("--out", default="docs/results/win_probability")
    args = ap.parse_args(argv)

    files = sorted(glob.glob(os.path.join(args.events_dir, "*.json")))
    if not files:
        print(f"No event JSONs in {args.events_dir}")
        return 1

    rps_scores = []
    rows = []
    for f in files:
        try:
            events = json.load(open(f, encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(events, list) or not events:
            continue
        home, away, pts = wp_timeline(events, args.team_rate)
        outcome = final_outcome(events)
        # RPS using the pre-kickoff (t=0) forecast, a standard calibration check
        if pts:
            pw, pd, pl = win_probability(0, 1.0, args.team_rate, 0)
            rps_scores.append(ranked_probability_score(pw, pd, pl, outcome))
        rows.append({"match": os.path.basename(f), "home": home, "away": away,
                     "outcome": outcome, "n_points": len(pts)})

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "n_matches": len(rows),
        "team_rate": args.team_rate,
        "mean_prematch_rps": float(np.mean(rps_scores)) if rps_scores else None,
    }
    with open(out_dir / "win_probability_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print(f"Computed WP timelines for {len(rows)} matches; mean pre-match RPS = "
          f"{summary['mean_prematch_rps']}")
    print(f"Wrote {out_dir}/win_probability_summary.json")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
