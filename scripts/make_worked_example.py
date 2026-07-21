#!/usr/bin/env python3
"""
make_worked_example.py
A single concrete goal, to make decision-staleness tangible.

The aggregate decision-staleness numbers answer "how much", but not "what does this actually
look like". This script takes one real goal from the StatsBomb corpus, computes the in-play
win-probability step it causes, and draws what a consumer *believes* while the event is still
in flight under each backend's measured delivery latency. The shaded area between the true and
delivered curves is exactly the decision-staleness contributed by that one event
(TV_shift x latency, Section "Decision-Staleness" of the manuscript).

CLI:
    python scripts/make_worked_example.py --events-dir data/raw/statsbomb/<sha>/events \
        --kafka-latency-ms 102 --redis-latency-ms 1507 --out docs/results/figures
"""
import argparse
import glob
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import win_probability as wp
import decision_staleness as ds


def pick_headline_goal(events_dir, team_rate=wp.DEFAULT_TEAM_RATE):
    """Return the goal with the largest win-probability shift across the corpus.

    Returns dict(match_file, event_id, minute, tv_shift, p_before, p_after, scorer) or None.
    """
    best = None
    for f in sorted(glob.glob(os.path.join(events_dir, "*.json"))):
        try:
            events = json.load(open(f, encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not (isinstance(events, list) and events):
            continue
        home, away, goals, reds, match_len = wp.parse_match(events)
        shifts = ds.goal_decision_shifts(events, team_rate)
        if not shifts:
            continue
        # replay the goal sequence to recover before/after win probabilities per goal
        h = a = 0
        for e in events:
            et = e.get("type", {}).get("name")
            team = e.get("team", {}).get("name")
            eid = e.get("id")
            is_goal = et == "Shot" and e.get("shot", {}).get("outcome", {}).get("name") == "Goal"
            is_og = et == "Own Goal Against"
            if not (is_goal or is_og):
                continue
            t = wp.clock_seconds(e.get("minute", 0), e.get("second", 0))
            frac_rem = max(0.0, (match_len - t) / match_len)
            before = wp.win_probability(h - a, frac_rem, team_rate)
            scorer = team if is_goal else (away if team == home else home)
            if scorer == home:
                h += 1
            else:
                a += 1
            after = wp.win_probability(h - a, frac_rem, team_rate)
            tv = shifts.get(eid)
            if tv is None:
                continue
            if best is None or tv > best["tv_shift"]:
                best = {"match_file": os.path.basename(f), "event_id": eid,
                        "minute": int(e.get("minute", 0)), "tv_shift": float(tv),
                        "p_before": float(before[0]), "p_after": float(after[0]),
                        # the full win/draw/loss forecast: a late equaliser moves mass from
                        # loss to draw, which P(win) alone would not show
                        "dist_before": [float(x) for x in before],
                        "dist_after": [float(x) for x in after],
                        "scorer": scorer, "home": home, "away": away}
    return best


def staleness_cost(tv_shift, latency_ms):
    """Decision-staleness contributed by one event: TV shift x latency, in probability-seconds."""
    return float(tv_shift) * (float(latency_ms) / 1000.0)


def plot_worked_example(goal, latencies_ms, out_dir):
    """Two panels for one goal: what the forecast did, and what staleness it caused.

    (a) the full win/draw/loss forecast before vs. after the event -- for a late equaliser the
        mass moves from loss to draw, which P(win) alone would hide;
    (b) the consumer's forecast error over time per backend. The error is the event's TV shift
        until the event is delivered, then zero, so each rectangle's *area* is precisely the
        decision-staleness that event contributes (TV shift x latency).
    """
    tv = goal["tv_shift"]
    before = goal.get("dist_before", [goal["p_before"], 0.0, 0.0])
    after = goal.get("dist_after", [goal["p_after"], 0.0, 0.0])
    colors = {"kafka": "#1f77b4", "redis": "#ff7f0e"}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.0, 4.2))

    # (a) forecast before vs after
    labels = ["Home win", "Draw", "Home loss"]
    x = range(len(labels))
    ax1.bar([i - 0.2 for i in x], before, width=0.4, label="Before event", color="#999999")
    ax1.bar([i + 0.2 for i in x], after, width=0.4, label="After event", color="#2ca02c")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(labels)
    ax1.set_ylabel("Probability")
    ax1.set_ylim(0, 1)
    ax1.set_title(f"(a) Forecast moves at {goal['minute']}' (TV shift {tv:.2f})")
    ax1.grid(True, axis="y", alpha=0.3)
    ax1.legend(fontsize=8)

    # (b) consumer error over time; area = decision-staleness
    span = max(list(latencies_ms.values()) + [1.0]) / 1000.0
    for backend, lat_ms in sorted(latencies_ms.items(), key=lambda kv: -kv[1]):
        L = lat_ms / 1000.0
        cost = staleness_cost(tv, lat_ms)
        ax2.fill_between([0, L], [tv, tv], step="post", alpha=0.30,
                         color=colors.get(backend, "gray"))
        ax2.plot([0, L, L, span * 1.35], [tv, tv, 0, 0], linewidth=2.0,
                 color=colors.get(backend, "gray"),
                 label=f"{backend.capitalize()}: +{lat_ms:.0f} ms = {cost:.3f} prob-s")
    ax2.set_xlabel("Time since the event occurred (s)")
    ax2.set_ylabel("Consumer forecast error (TV distance)")
    ax2.set_ylim(0, min(1.0, tv * 1.25))
    ax2.set_title("(b) Staleness while the event is in flight\n(area = probability-seconds)")
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc="upper right", fontsize=8)

    fig.tight_layout()
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(out_dir / f"worked_example.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Worked decision-staleness example for one goal")
    ap.add_argument("--events-dir", required=True)
    ap.add_argument("--kafka-latency-ms", type=float, default=102.0,
                    help="measured mean decisive-event latency for Kafka (default: N=5 single)")
    ap.add_argument("--redis-latency-ms", type=float, default=1507.0,
                    help="measured mean decisive-event latency for Redis (default: N=5 single)")
    ap.add_argument("--out", default="docs/results/figures")
    args = ap.parse_args(argv)

    goal = pick_headline_goal(args.events_dir)
    if goal is None:
        print(f"No goals with a win-probability shift found in {args.events_dir}")
        return 1

    latencies = {"kafka": args.kafka_latency_ms, "redis": args.redis_latency_ms}
    goal["staleness_prob_s"] = {b: staleness_cost(goal["tv_shift"], ms)
                                for b, ms in latencies.items()}
    goal["latency_ms"] = latencies

    out_dir = Path(args.out)
    plot_worked_example(goal, latencies, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "worked_example.json").write_text(json.dumps(goal, indent=2), encoding="utf-8")

    print(f"Goal at {goal['minute']}' ({goal['scorer']}) in {goal['match_file']}")
    print(f"  P(home win): {goal['p_before']:.3f} -> {goal['p_after']:.3f}  "
          f"(TV shift {goal['tv_shift']:.3f})")
    for b, ms in latencies.items():
        print(f"  {b}: delivered +{ms:.0f} ms -> {goal['staleness_prob_s'][b]:.4f} probability-seconds stale")
    print(f"Wrote worked example to {out_dir}/")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
