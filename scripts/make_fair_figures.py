#!/usr/bin/env python3
"""
make_fair_figures.py
Publication figures for the fair-corpus results:

  1. Broker transport latency vs. concurrency N (single host) -- Kafka flat, single-node Redis
     grows ~linearly. Source: analyze_realtime_concurrency.py summary CSV (single config).
  2. Decision-staleness vs. concurrency N (full-match) -- negligible at N=1, Redis diverges.
     Source: decision_staleness.py by-backend-config-N CSV.

Both use a log y-axis (values span several orders of magnitude). Saves PNG + PDF.

CLI:
    python scripts/make_fair_figures.py \
        --latency-csv docs/results/realtime_concurrency/realtime_concurrency_summary.csv \
        --staleness-csv docs/results/decision_staleness_fullmatch/decision_staleness_by_backend_config_n.csv \
        --out docs/results/figures
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

COLORS = {"kafka": "#1f77b4", "redis": "#ff7f0e"}
MARKERS = {"kafka": "o", "redis": "s"}


def plot_vs_n(ax, df, n_col, value_col, title, ylabel):
    """Line plot of value_col vs n_col, one series per backend, log-y."""
    for backend in ("kafka", "redis"):
        sub = df[df["backend"] == backend].sort_values(n_col)
        if sub.empty:
            continue
        ax.plot(sub[n_col], sub[value_col], marker=MARKERS[backend],
                color=COLORS[backend], linewidth=2, markersize=7, label=backend.capitalize())
    ax.set_yscale("log")
    ax.set_xlabel("Concurrent matches (N)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()


def _save(fig, out_dir, stem):
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(out_dir / f"{stem}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)


def make_latency_figure(latency_csv, out_dir, config="single"):
    df = pd.read_csv(latency_csv)
    if "config" in df.columns:
        df = df[df["config"] == config]
    if df.empty:
        return False
    fig, ax = plt.subplots(figsize=(6, 4))
    plot_vs_n(ax, df, "n", "transport_p50",
              "Broker transport latency vs. concurrency (single host)",
              "Transport p50 (ms, log)")
    _save(fig, out_dir, "latency_vs_concurrency")
    return True


def make_staleness_figure(staleness_csv, out_dir):
    df = pd.read_csv(staleness_csv)
    n_col = "n_concurrency" if "n_concurrency" in df.columns else "n"
    if "config" in df.columns:
        df = df[df["config"] == "single"]
    if df.empty:
        return False
    fig, ax = plt.subplots(figsize=(6, 4))
    plot_vs_n(ax, df, n_col, "decision_staleness_prob_s",
              "Decision-staleness vs. concurrency (full match)",
              "Decision-staleness (prob-s, log)")
    _save(fig, out_dir, "decision_staleness_vs_concurrency")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fair-corpus publication figures")
    ap.add_argument("--latency-csv",
                    default="docs/results/realtime_concurrency/realtime_concurrency_summary.csv")
    ap.add_argument("--staleness-csv",
                    default="docs/results/decision_staleness_fullmatch/decision_staleness_by_backend_config_n.csv")
    ap.add_argument("--out", default="docs/results/figures")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    made = []
    if Path(args.latency_csv).exists() and make_latency_figure(args.latency_csv, out_dir):
        made.append("latency_vs_concurrency")
    if Path(args.staleness_csv).exists() and make_staleness_figure(args.staleness_csv, out_dir):
        made.append("decision_staleness_vs_concurrency")

    if not made:
        print("No figures produced (inputs missing or empty).")
        return 1
    print(f"Wrote {len(made)} figures to {out_dir}/: {', '.join(made)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
