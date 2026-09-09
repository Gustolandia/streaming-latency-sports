#!/usr/bin/env python3
"""
make_e1_figure.py
Publication figure for E1: end-to-end lag at the concurrency levels football actually
produces, measured on the multi-host testbed at true real-time replay, after clock-integrity
gating.

Two panels, because the headline number and its explanation are different quantities:

  (a) End-to-end TTI (p50) vs concurrency N, one series per backend, log-y. This is the
      quantity a consumer experiences and the one the study set out to compare.
  (b) The same measurement decomposed into producer scheduling lag and broker transport.
      Panel (a)'s ~20x gap lives entirely in the client send path; the brokers themselves
      are separated by well under a millisecond.

Source: docs/results/e1/e1_by_run_gated.csv (one row per surviving run).

CLI:
    python scripts/make_e1_figure.py \
        --by-run-csv docs/results/e1/e1_by_run_gated.csv \
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
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

COLORS = {"kafka": "#1f77b4", "redis": "#ff7f0e"}
MARKERS = {"kafka": "o", "redis": "s"}
LABELS = {"kafka": "Kafka", "redis": "Redis"}


def condition_medians(df):
    """Collapse per-run rows to one median per (backend, N).

    The run-level values are themselves per-run medians, so this is a median of medians:
    it is the estimator the accompanying rank tests operate on, and it is deliberately
    insensitive to the handful of runs carrying a startup outlier.
    """
    if df.empty:
        return df
    return (df.groupby(["backend", "n"], as_index=False)
              [["tti_p50", "schedlag_p50", "transport_p50"]].median()
              .sort_values(["backend", "n"]))


def plot_tti(ax, med):
    """Panel (a): end-to-end TTI against concurrency, one line per backend."""
    for backend in ("kafka", "redis"):
        sub = med[med["backend"] == backend]
        if sub.empty:
            continue
        ax.plot(sub["n"], sub["tti_p50"], marker=MARKERS[backend], color=COLORS[backend],
                linewidth=2, markersize=7, label=LABELS[backend])
    ax.set_yscale("log")
    ax.set_xlabel("Concurrent matches ($N$)")
    ax.set_ylabel("End-to-end TTI, p50 (ms)")
    ax.set_title("(a) End-to-end lag")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(framealpha=1.0)


def plot_decomposition(ax, med):
    """Panel (b): the same runs split into scheduling lag and broker transport.

    Not bars. A bar states its value as a length measured from zero, and a log axis has no
    zero: eight grouped bars ran from whatever the bottom of the axis happened to be, so
    their lengths were log(v) - log(floor) and would all have changed if the limit moved.
    Kafka's send lag drew about eight times the ink of its transport for a ratio near 120.

    What a log axis does measure honestly is a ratio, as a distance --- and the ratio is
    what this panel claims. Each backend gets a segment joining its two components at each
    concurrency, filled marker at the send lag and hollow at the transport, so the gap a
    reader measures is the gap the caption asserts.
    """
    ns = sorted(med["n"].unique())
    offset = 0.16
    for i, backend in enumerate(("kafka", "redis")):
        sub = med[med["backend"] == backend].set_index("n")
        if sub.empty:
            continue
        xs = [j + (i - 0.5) * 2 * offset for j in range(len(ns))]
        lag = [sub["schedlag_p50"].get(n, float("nan")) for n in ns]
        transport = [sub["transport_p50"].get(n, float("nan")) for n in ns]
        for x, a, b in zip(xs, lag, transport):
            ax.plot([x, x], [b, a], color=COLORS[backend], linewidth=1.4,
                    alpha=0.55, zorder=1, solid_capstyle="butt")
        ax.plot(xs, lag, linestyle="none", marker=MARKERS[backend], markersize=6,
                color=COLORS[backend], zorder=2,
                label=f"{LABELS[backend]} send lag")
        ax.plot(xs, transport, linestyle="none", marker=MARKERS[backend], markersize=6,
                markerfacecolor="white", markeredgecolor=COLORS[backend],
                markeredgewidth=1.3, zorder=2,
                label=f"{LABELS[backend]} transport")
    ax.set_yscale("log")
    ax.set_xticks(range(len(ns)))
    ax.set_xticklabels([str(n) for n in ns])
    ax.set_xlabel("Concurrent matches ($N$)")
    ax.set_ylabel("Component, p50 (ms)")
    ax.set_title("(b) Where the lag is")
    ax.grid(True, axis="y", which="both", alpha=0.3)
    ax.legend(fontsize="small", framealpha=1.0)


def _save(fig, out_dir, stem):
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for ext in ("png", "pdf"):
        path = out_dir / f"{stem}.{ext}"
        fig.savefig(path, dpi=200, bbox_inches="tight")
        written.append(path)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description="E1 figure: end-to-end lag and its decomposition")
    ap.add_argument("--by-run-csv", default="docs/results/e1/e1_by_run_gated.csv")
    ap.add_argument("--out", default="docs/results/figures")
    ap.add_argument("--stem", default="e1_end_to_end_lag")
    args = ap.parse_args(argv)

    src = Path(args.by_run_csv)
    if not src.exists():
        print(f"missing input: {src}")
        return 1

    med = condition_medians(pd.read_csv(src))
    if med.empty:
        print("no rows to plot")
        return 1

    fig, axes = plt.subplots(2, 1, figsize=(5.5, 5.0))
    plot_tti(axes[0], med)
    plot_decomposition(axes[1], med)
    fig.tight_layout()
    for path in _save(fig, Path(args.out), args.stem):
        print(f"wrote {path}")
    plt.close(fig)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
