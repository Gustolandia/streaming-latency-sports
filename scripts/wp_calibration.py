#!/usr/bin/env python3
"""
wp_calibration.py
Validate the in-play win-probability proxy (scripts/win_probability.py) by its *calibration*:
across every game state sampled from the StatsBomb matches, does a predicted home-win
probability of p actually correspond to a home win about p of the time?

We collect (predicted P(home win), did-home-win) pairs at a time grid over each match, bin the
predictions, and report a reliability diagram plus the Expected Calibration Error (ECE),
    ECE = sum_b (n_b / N) * | mean_pred_b - obs_freq_b |.
A reviewer can then see the proxy is sound rather than taking a single RPS number on faith.
The model has one global parameter (team scoring rate), so this is a whole-corpus check.

CLI:
    python scripts/wp_calibration.py --events-dir data/raw/statsbomb/<sha>/events \
        --out docs/results/win_probability
"""
import argparse
import glob
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import win_probability as wp


def collect_calibration_pairs(events_dir, team_rate=wp.DEFAULT_TEAM_RATE, grid_seconds=60):
    """Return list of (p_win_home, home_won) over a time grid across every match JSON."""
    pairs = []
    for f in sorted(glob.glob(os.path.join(events_dir, "*.json"))):
        try:
            events = json.load(open(f, encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not (isinstance(events, list) and events):
            continue
        _, _, pts = wp.wp_timeline(events, team_rate, grid_seconds)
        if not pts:  # pragma: no cover - wp_timeline always yields >=1 grid point
            continue
        home_won = 1 if wp.final_outcome(events) == 1 else 0
        for _t, p_win in pts:
            pairs.append((float(p_win), home_won))
    return pairs


def reliability_bins(pairs, n_bins=10):
    """Bin predictions into [0,1] deciles; return a DataFrame with per-bin mean prediction,
    observed frequency and count (empty bins dropped)."""
    if not pairs:
        return pd.DataFrame(columns=["bin_lo", "bin_hi", "pred_mean", "obs_freq", "count"])
    preds = np.array([p for p, _ in pairs])
    outs = np.array([o for _, o in pairs])
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    rows = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (preds >= lo) & (preds < hi) if i < n_bins - 1 else (preds >= lo) & (preds <= hi)
        if mask.sum() == 0:
            continue
        rows.append({"bin_lo": lo, "bin_hi": hi, "pred_mean": float(preds[mask].mean()),
                     "obs_freq": float(outs[mask].mean()), "count": int(mask.sum())})
    return pd.DataFrame(rows)


def expected_calibration_error(bins_df, total):
    """Weighted mean absolute gap between predicted and observed."""
    if bins_df.empty or total == 0:
        return float("nan")
    return float((bins_df["count"] / total * (bins_df["pred_mean"] - bins_df["obs_freq"]).abs()).sum())


def _plot(bins_df, ece, out_dir):
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color="gray", label="perfect")
    ax.plot(bins_df["pred_mean"], bins_df["obs_freq"], "o-", color="#1f77b4", label="WP proxy")
    ax.set_xlabel("Predicted P(home win)")
    ax.set_ylabel("Observed home-win frequency")
    ax.set_title(f"In-play WP calibration (ECE = {ece:.3f})")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.3)
    ax.legend()
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(out_dir / f"wp_calibration.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Win-probability calibration (reliability + ECE)")
    ap.add_argument("--events-dir", required=True)
    ap.add_argument("--grid-seconds", type=int, default=60)
    ap.add_argument("--n-bins", type=int, default=10)
    ap.add_argument("--out", default="docs/results/win_probability")
    args = ap.parse_args(argv)

    pairs = collect_calibration_pairs(args.events_dir, grid_seconds=args.grid_seconds)
    if not pairs:
        print(f"No calibration pairs from {args.events_dir}")
        return 1
    bins_df = reliability_bins(pairs, args.n_bins)
    ece = expected_calibration_error(bins_df, len(pairs))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    bins_df.to_csv(out_dir / "wp_calibration_bins.csv", index=False)
    (out_dir / "wp_calibration.json").write_text(
        json.dumps({"n_states": len(pairs), "n_bins_used": int(len(bins_df)), "ece": ece}, indent=2),
        encoding="utf-8")
    _plot(bins_df, ece, out_dir)
    print(f"Calibration over {len(pairs)} game states; ECE = {ece:.4f}")
    print(bins_df.to_string(index=False))
    print(f"Wrote results to {out_dir}/")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
