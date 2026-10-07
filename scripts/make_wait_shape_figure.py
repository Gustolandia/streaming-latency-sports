#!/usr/bin/env python3
"""
make_wait_shape_figure.py
Supplement figure for the shape of the wait behind a late acknowledgment timestamp: the rest of
a slice, not a whole one.

The pre-registered law had the timestamping thread, once kept off a CPU, wait out a whole slice
and then up to a tick, so the negative-span rate would hold level until the delivery passed the
slice. A9 timed the wait for every acknowledgment instead, and the figure sets those waits
against the two shapes the wait could have had. It is a comparison that turns on shape, which
is why it is drawn rather than described.

Two panels:

  (a) The share of acknowledgments still waiting at each wait x, over the share still waiting at
      1 ms, for every pair, backend and load A9 ran: a whole slice keeps every one of them to
      the 3 ms slice; the rest of a slice keeps 60% to 2 ms and 20% to 3 ms. Dividing by the
      share at 1 ms fits nothing: it puts every part on one scale without a free parameter.
  (b) Every python3 thread's waits over a quarter of a millisecond, a density per millisecond in
      each bin, split by what began them. Waits begun by a wake-up keep one density from 1 ms to
      the slice; waits begun by a preemption rise in the band from the slice to a tick past it.
      The thread that timestamps an acknowledgment is woken by the acknowledgment's reply, so
      its wait is of the first kind.

Sources (both written by a9_decompose.py):
    docs/results/law/strange-results-28-sep/ack_waits.csv     S(x) for each part
    docs/results/law/strange-results-28-sep/a9_summary.json   waits in bins, by what began them

CLI:
    python scripts/make_wait_shape_figure.py \
        --waits docs/results/law/strange-results-28-sep/ack_waits.csv \
        --summary docs/results/law/strange-results-28-sep/a9_summary.json \
        --out docs/results/figures
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import figure_style  # noqa: E402
import figure_collisions  # noqa: E402
import figure_legibility  # noqa: E402
figure_style.apply()  # Type 42, IEEE-listed family; see scripts/figure_style.py
import matplotlib.pyplot as plt  # noqa: E402

import a9_decompose  # noqa: E402

STEM = "wait_shape"
#: One colour a machine, one marker a backend.
#: The Arm pair is named for its instruction set: the figure vocabulary gate bans the bare word
#: "arm", which the manuscript retired as a name for a configuration.
PAIRS = {"matched": ("first x86", "#1f77b4"), "matched-b": ("second x86", "#2ca02c"),
         "arm": ("Arm64", "#d62728")}
#: Each machine's marks are set a little to one side of the wait they are read at, so that the
#: three do not hide one another; the caption says so. The waits themselves are 0.25 ms apart.
DODGE_MS = {"arm": -0.06, "matched": 0.0, "matched-b": 0.06}
MARKERS = {"kafka": "o", "redis": "s"}
WOKEN, PREEMPTED = "#1f77b4", "#d62728"
SHAPE_STYLE = {"rest of a slice": ("#333333", "-"), "whole slice": ("#999999", "--")}


def load_waits(path):
    """{(pair, backend, load): [(x, share)]}, every part's shares in order of x.

    Raises where a part lacks the share at 1 ms, which every other share is divided by.
    """
    parts = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (row["pair"], row["backend"], row["load_pct"])
            parts.setdefault(key, []).append((float(row["x_ms"]), float(row["share"])))
    if not parts:
        raise ValueError("%s holds no part; re-run a9_decompose.py" % path)
    for key, points in parts.items():
        points.sort()
        at_one = dict(points).get(1.0)
        if not at_one:
            raise ValueError("%s: part %s has no acknowledgment waiting past 1 ms"
                             % (path, ", ".join(key)))
    return parts


def load_bins(path):
    """{"pair, backend": {"wake": [counts], "preempt": [counts]}} from a9_summary.json."""
    with open(path, encoding="utf-8") as fh:
        found = json.load(fh)["a9"]
    bins = dict((name, {"wake": part.get("wake_bins"), "preempt": part.get("preempt_bins")})
                for name, part in found.items())
    missing = [name for name, part in bins.items() if not part["wake"] or not part["preempt"]]
    if missing:
        raise ValueError("%s lacks the waits in bins for %s; re-run a9_decompose.py"
                         % (path, ", ".join(sorted(missing))))
    return bins


def densities(counts, edges=a9_decompose.BAND_EDGES):
    """The share of the waits in each bin, per ms of the bin's width."""
    total = float(sum(counts))
    return [n / total / (b - a) for n, a, b in zip(counts, edges, edges[1:])]


def plot_survival(ax, parts, s=a9_decompose.A9_SLICE_MS, h=a9_decompose.A9_TICK_MS):
    """Panel (a): every part's shares over its share at 1 ms, and the two shapes."""
    xs = [0.05 * k for k in range(0, 101)]
    for name, (colour, style) in sorted(SHAPE_STYLE.items()):
        shape = a9_decompose.WAIT_SHAPES[name]
        ax.plot(xs, [shape(x, s, h) / shape(1.0, s, h) for x in xs], color=colour,
                linestyle=style, linewidth=1.8, label=name, zorder=1)
    seen = set()
    for (pair, backend, load), points in sorted(parts.items()):
        label_pair, colour = PAIRS.get(pair, (pair, "#7f7f7f"))
        at_one = dict(points)[1.0]
        label = "%s, %s" % (label_pair, backend.capitalize())
        ax.plot([x + DODGE_MS.get(pair, 0.0) for x, _ in points],
                [share / at_one for _, share in points],
                linestyle="none", marker=MARKERS.get(backend, "^"), markersize=4,
                markerfacecolor="white" if load == "75" else colour, markeredgecolor=colour,
                label=None if label in seen else label, zorder=2)
        seen.add(label)
    ax.axvline(s, color="#bbbbbb", linewidth=0.8, zorder=0)
    ax.axvline(s + h, color="#bbbbbb", linewidth=0.8, zorder=0)
    # Room past the last wait read and below zero, so that no marker is cut by the frame.
    ax.set_xlim(0, 5.2)
    ax.set_ylim(-0.06, 1.65)
    ax.set_xlabel("Wait for a CPU, x (ms)")
    ax.set_ylabel("Share waiting past x,\nover the share past 1 ms")
    ax.set_title("(a) Each acknowledgment's wait: the rest of a slice")
    ax.legend(loc="upper right", fontsize=8, ncol=2, framealpha=1.0)
    ax.grid(True, alpha=0.3)


#: The paper's column-width panel (6 Oct 2026): one mark a broker, not a machine, so that its
#: legend holds four entries rather than eight at 3.5 in.
PAPER_STEM = "residual_wait"
BROKER_STYLE = {"kafka": ("Kafka, each part", "#1f77b4", "o"),
                "redis": ("Redis, each part", "#d62728", "s")}


def plot_survival_compact(ax, parts, s=a9_decompose.A9_SLICE_MS, h=a9_decompose.A9_TICK_MS):
    """Panel (a) for the paper: the two shapes, and every part marked by its broker alone."""
    xs = [0.05 * k for k in range(0, 101)]
    for name, (colour, style) in sorted(SHAPE_STYLE.items()):
        shape = a9_decompose.WAIT_SHAPES[name]
        ax.plot(xs, [shape(x, s, h) / shape(1.0, s, h) for x in xs], color=colour,
                linestyle=style, linewidth=1.6, label=name, zorder=1)
    seen = set()
    for (pair, backend, _load), points in sorted(parts.items()):
        label, colour, marker = BROKER_STYLE.get(backend, (backend, "#7f7f7f", "^"))
        at_one = dict(points)[1.0]
        ax.plot([x + DODGE_MS.get(pair, 0.0) for x, _ in points],
                [share / at_one for _, share in points], linestyle="none", marker=marker,
                markersize=3, markerfacecolor="white", markeredgecolor=colour,
                markeredgewidth=0.8, label=None if label in seen else label, zorder=2)
        seen.add(label)
    ax.axvline(s, color="#bbbbbb", linewidth=0.8, zorder=0)
    ax.axvline(s + h, color="#bbbbbb", linewidth=0.8, zorder=0)
    ax.set_xlim(0, 5.2)
    # Room above the data for the legend in two columns, clear of the whole-slice curve, whose
    # turn at the slice is what tells the two shapes apart.
    ax.set_ylim(-0.06, 1.95)
    ax.set_xlabel("Wait for a core, $x$ (ms)")
    ax.set_ylabel("Share still waiting at $x$,\nrelative to 1 ms")
    # 8 pt, IEEE's floor; it was drawn at 7 before the paper included it, when the legibility
    # gate had no width to check it at.
    ax.legend(loc="upper right", fontsize=8, framealpha=1.0, ncol=2, columnspacing=0.8,
              handletextpad=0.4, handlelength=1.6)
    ax.grid(True, alpha=0.3)


def build_paper_panel(waits, out_dir):
    """The residual-wait figure the paper prints in Section IV-C, at column width."""
    figure_style.apply()
    parts = load_waits(waits)
    fig, ax = plt.subplots(figsize=(3.5, 2.4))
    plot_survival_compact(ax, parts)
    fig.tight_layout()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        figure_collisions.check(fig, PAPER_STEM)
        figure_legibility.check(fig, PAPER_STEM)
        fig.savefig(out / ("%s.%s" % (PAPER_STEM, ext)), dpi=200, bbox_inches="tight",
                    pad_inches=0.02)
    plt.close(fig)
    return out / ("%s.pdf" % PAPER_STEM)


def plot_causes(ax, bins, edges=a9_decompose.BAND_EDGES, s=a9_decompose.A9_SLICE_MS,
                h=a9_decompose.A9_TICK_MS):
    """Panel (b): every thread's waits over a quarter of a millisecond, by what began them."""
    ax.axvspan(s, s + h, color="#eeeeee", zorder=0)
    for cause, colour, label in (("wake", WOKEN, "begun by a wake-up"),
                                 ("preempt", PREEMPTED, "begun by a preemption")):
        # Each pair and backend thin, and all of them pooled bold on top.
        for name, part in sorted(bins.items()):
            steps = densities(part[cause], edges)
            ax.step(edges, steps + steps[-1:], where="post", color=colour, linewidth=0.8,
                    alpha=0.35, zorder=2)
        pooled = densities([sum(column) for column in zip(*[part[cause]
                                                            for part in bins.values()])], edges)
        ax.step(edges, pooled + pooled[-1:], where="post", color=colour, linewidth=2.2,
                label=label + ", pooled", zorder=3)
    ax.set_xlim(edges[0], 5)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Wait for a CPU (ms); shaded, the slice to a tick past it")
    ax.set_ylabel("Share of waits a ms")
    ax.set_title("(b) Every thread's waits, by what began them")
    ax.legend(loc="upper right", fontsize=8, framealpha=1.0)
    ax.grid(True, alpha=0.3)


def main(argv=None):
    figure_style.apply()   # in force when the artists are made, not merely at import
    ap = argparse.ArgumentParser(description="The wait behind a late acknowledgment timestamp")
    ap.add_argument("--waits", default="docs/results/law/strange-results-28-sep/ack_waits.csv")
    ap.add_argument("--summary",
                    default="docs/results/law/strange-results-28-sep/a9_summary.json")
    ap.add_argument("--out", default="docs/results/figures")
    args = ap.parse_args(argv)

    parts, bins = load_waits(args.waits), load_bins(args.summary)
    plt.rcParams.update({"font.size": 10, "text.usetex": False})
    # Drawn at the width the supplement includes it at, so that 8 pt type prints at 8 pt.
    fig, axes = plt.subplots(2, 1, figsize=(6.5, 6.2))
    plot_survival(axes[0], parts)
    plot_causes(axes[1], bins)
    fig.tight_layout()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        figure_collisions.check(fig, STEM)
        figure_legibility.check(fig, STEM)
        fig.savefig(out / ("%s.%s" % (STEM, ext)), dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("OK wrote %s/%s.pdf and .png" % (out, STEM))
    print("OK wrote %s" % build_paper_panel(args.waits, args.out))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
