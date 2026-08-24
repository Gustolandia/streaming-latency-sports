#!/usr/bin/env python3
"""
make_window_figure.py
Publication figure for the observation-window sweep: the evidence that the ~103 ms producer
offset is a per-run start-up cost rather than a per-event constant.

The figure exists because the distinction is invisible in any percentile. A median only shows
the cost when the run is short enough for it to dominate, which is exactly how the original
result went wrong. What separates the two explanations is a COUNT, and a count is best shown
against the thing it fails to track.

Two panels:

  (a) Events per run and events waking more than 50 ms late, against the observation window.
      The first grows 8.9x; the second does not move. A per-event constant would put the two
      series on parallel paths.
  (b) The share of events paying the cost, which is the same fact stated as a proportion, with
      the 1/N curve a per-run cost predicts. This is the panel that shows why a seven-event run
      reports 103 ms and a five-hundred-event run reports 1.6 ms from the same measurement.

Source: docs/results/window/window_sweep.csv (one row per window, written by analyze_window.py).

CLI:
    python scripts/make_window_figure.py \
        --sweep-csv docs/results/window/window_sweep.csv \
        --out docs/results/figures
"""
import argparse
from pathlib import Path

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib
matplotlib.use("Agg")
import figure_style  # noqa: E402
figure_style.apply()  # Type 42, IEEE-listed family; see scripts/figure_style.py
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker  # noqa: E402
import pandas as pd  # noqa: E402

EMITTED = "#1f77b4"
AFFECTED = "#d62728"


def load(path):
    """Rows ordered by window, with the columns the panels need.

    Raises rather than plotting a partial sweep: a figure whose whole point is that one series
    stays flat while another grows is misleading if a window is missing.
    """
    df = pd.read_csv(path).sort_values("window_s").reset_index(drop=True)
    missing = [c for c in ("window_s", "trace_events", "slow_wake", "schedlag_p50",
                           "schedlag_max") if c not in df.columns]
    if missing:
        raise ValueError(f"{path} lacks {missing}; re-run analyze_window.py")
    if len(df) < 2:
        raise ValueError(f"{path} has {len(df)} window(s); the figure needs at least two")
    if df["slow_wake"].isna().any():
        raise ValueError(f"{path} has an untraced window; the count panel would be blank")
    return df


def plot_counts(ax, df):
    """Panel (a): the growing series and the flat one, on one axis."""
    ax.plot(df["window_s"], df["trace_events"], marker="o", color=EMITTED,
            linewidth=2, markersize=7, label="Events emitted per run")
    ax.plot(df["window_s"], df["slow_wake"], marker="s", color=AFFECTED,
            linewidth=2, markersize=7, label="Events waking $>$50 ms late")
    ax.set_xscale("log")
    # A log axis keeps labelling its minor decades, which prints "2 x 10^2" straight through
    # the "180" set below. Keep the ticks, drop their labels.
    ax.xaxis.set_minor_formatter(mticker.NullFormatter())
    ax.set_yscale("log")
    ax.set_xticks(df["window_s"])
    ax.set_xticklabels([f"{int(w)}" for w in df["window_s"]])
    ax.set_xlabel("Observation window (s)")
    ax.set_ylabel("Events per run")
    ax.set_title("(a) One series grows, the other does not")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="center left")

    grew = df["trace_events"].iloc[-1] / df["trace_events"].iloc[0]
    ax.annotate(f"${grew:.1f}\\times$", xy=(df["window_s"].iloc[-1], df["trace_events"].iloc[-1]),
                xytext=(-34, -16), textcoords="offset points", color=EMITTED, fontweight="bold")
    ax.annotate("fixed", xy=(df["window_s"].iloc[-1], df["slow_wake"].iloc[-1]),
                xytext=(-32, 10), textcoords="offset points", color=AFFECTED, fontweight="bold")


def plot_share(ax, df):
    """Panel (b): the same fact as a proportion, against what a per-run cost predicts."""
    share = 100.0 * df["slow_wake"] / df["trace_events"]
    ax.plot(df["window_s"], share, marker="s", color=AFFECTED, linewidth=2, markersize=7,
            label="Measured share")
    # A cost paid once per run dilutes as 1/events, anchored at the narrowest window.
    predicted = share.iloc[0] * df["trace_events"].iloc[0] / df["trace_events"]
    # No mathtext. A proportional-to sign has no Arial glyph, falls back to Computer Modern
    # and extracts as "(", which corrupts the legend for every reader of the text layer.
    ax.plot(df["window_s"], predicted, linestyle="--", color="#555555", linewidth=1.5,
            label="Paid once per run, diluting as 1/events")
    ax.set_xscale("log")
    # A log axis keeps labelling its minor decades, which prints "2 x 10^2" straight through
    # the "180" set below. Keep the ticks, drop their labels.
    ax.xaxis.set_minor_formatter(mticker.NullFormatter())
    ax.set_xticks(df["window_s"])
    ax.set_xticklabels([f"{int(w)}" for w in df["window_s"]])
    ax.set_xlabel("Observation window (s)")
    # Plain "%": matplotlib renders without usetex, so a LaTeX-escaped percent would print
    # the backslash literally on the axis.
    ax.set_ylabel("Share of events paying the cost (%)")
    ax.set_title("(b) Dilution, not absence")
    ax.grid(True, alpha=0.3)
    ax.legend()
    for w, s in zip(df["window_s"], share):
        ax.annotate(f"{s:.1f}%", xy=(w, s), xytext=(0, 8), textcoords="offset points",
                    ha="center", fontsize=8)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Window-sweep figure: start-up cost, not constant")
    ap.add_argument("--sweep-csv", default="docs/results/window/window_sweep.csv")
    ap.add_argument("--out", default="docs/results/figures")
    args = ap.parse_args(argv)

    df = load(args.sweep_csv)
    plt.rcParams.update({"font.size": 10, "text.usetex": False})
    fig, axes = plt.subplots(2, 1, figsize=(5.5, 4.8))
    plot_counts(axes[0], df)
    plot_share(axes[1], df)
    fig.tight_layout()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(out / f"window_sweep.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"OK wrote {out}/window_sweep.pdf and .png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
