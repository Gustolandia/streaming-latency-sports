#!/usr/bin/env python3
"""
make_result_figures.py
The three result figures, drawn from the committed artefacts rather than described in prose.

Why these three, and why now. Three readers in a row have said the manuscript is hard to
follow, and measuring it against the journal's own published corpus turned the complaint into
a number: the median regular paper in that corpus carries thirteen figures and this one carried
two. The three results that were hardest to follow were the three that existed only as prose
and a table of numbers, and each of them is a picture:

  deletion  -- the headline. Retention swings across two and a half orders of magnitude while
               the median the benchmark prints does not move at all. Said in a sentence it
               sounds like a paradox; drawn, it is obvious, because the printed median is a
               property of the grid and the retention is a property of the phase.

  spectrum  -- the traced stall distribution, which is trimodal, with the largest of the three
               modes sitting on the scheduler's base slice. The mechanism argument in Section V
               rests entirely on where that mode is, and asking a reader to hold a log2
               histogram in their head from a list of bucket counts is asking too much.

  grid      -- membership against a continuum null, replacing the table that carried the same
               numbers. A table of twelve p-values answers "is each arm significant"; the
               figure answers "does the whole set lie on the grid", which is the actual claim.

Every number drawn here comes from the same artefacts and the same estimators the ledger uses,
so a figure cannot drift from the text: `stat_intervals` for the intervals, `tail_index_traced`
for the histogram parse, and the committed CSVs for everything else. Nothing is recomputed by
eye and nothing is smoothed.

CLI:
    python scripts/make_result_figures.py --out docs/results/figures
"""
import argparse
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stat_intervals  # noqa: E402
import tail_index_traced as tit  # noqa: E402

KEPT, DELETED, GREY, ACCENT = "#1f77b4", "#c44e52", "#555555", "#2a7f62"

RESULTS = Path("docs") / "results"
RETENTION_CSV = RESULTS / "external" / "omb_retention.csv"
RUNQLAT = RESULTS / "depth" / "ea9" / "l88_base" / "runqlat.txt"


# --- the deletion -------------------------------------------------------------------------

def retention_points(path=RETENTION_CSV):
    """(retention %, printed median ms) for every committed OMB cell.

    Both columns come from the same result file the benchmark itself wrote, which is the point:
    a reader of that file sees the median and has no way to see the retention.
    """
    import csv
    pts = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                pts.append((float(r["retention_pct"]), float(r["omb_p50_ms"])))
            except (KeyError, ValueError):
                continue
    if not pts:
        raise ValueError("no usable retention rows in %s" % path)
    return pts


QUANTUM_MS = 2.0  # a cell printing at most this is reporting at the grid, not above it


def plot_deletion(ax, pts, quantum_ms=QUANTUM_MS):
    """Retention against the median the benchmark printed, every committed cell.

    Every cell is drawn, including the four where the payload is large enough that the
    quantum stops binding. Dropping them would be the same move the paper is about. They
    also carry the argument: away from the grid the benchmark behaves, and the failure is
    confined to the region where the interval it is asked to measure is smaller than the
    instrument it measures with.
    """
    ret = np.array([p[0] for p in pts])
    med = np.array([p[1] for p in pts])
    at_grid = med <= quantum_ms

    ax.scatter(med[at_grid], ret[at_grid], s=16, color=KEPT, edgecolors="none",
               zorder=3, label="printed at the grid (%d)" % at_grid.sum())
    ax.scatter(med[~at_grid], ret[~at_grid], s=18, facecolors="none", edgecolors=GREY,
               linewidths=0.9, zorder=3, label="printed above it (%d)" % (~at_grid).sum())
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("median the benchmark printed (ms)", fontsize=7.5)
    ax.set_ylabel("samples retained (%)", fontsize=7.5)
    ax.tick_params(labelsize=7)
    ax.grid(alpha=0.25, lw=0.5)
    ax.axhline(100, color=GREY, lw=0.6, ls=":", zorder=0)

    lo, hi = ret[at_grid].min(), ret[at_grid].max()
    xs = med[at_grid].min()
    ax.annotate("", xy=(xs * 0.62, lo), xytext=(xs * 0.62, hi),
                arrowprops=dict(arrowstyle="<->", color=DELETED, lw=1.0))
    ax.text(xs * 0.55, (lo * hi) ** 0.5, "%.0f×" % (hi / lo), fontsize=7.5,
            color=DELETED, va="center", ha="right", rotation=90)
    ax.set_xlim(xs * 0.30, med.max() * 3)
    ax.set_ylim(lo * 0.45, 260)
    ax.legend(fontsize=6.3, frameon=False, loc="lower right", handletextpad=0.4)


# --- the stall spectrum -------------------------------------------------------------------

def stall_histogram(path=RUNQLAT):
    """The committed bpftrace histogram, parsed by the same code the estimators use."""
    with open(path, encoding="utf-8") as fh:
        bins, counters = tit.parse_runqlat(fh.read())
    if not bins:
        raise ValueError("no histogram buckets in %s" % path)
    return bins, counters


def plot_spectrum(ax, bins, slice_ms=None):
    """The log2 histogram, with the three modes marked and the scheduler slice annotated."""
    total = sum(b[2] for b in bins) or 1
    los = [b[0] for b in bins]
    share = [100.0 * b[2] / total for b in bins]
    peaks = {lo for lo, _, _, _ in tit.modes(bins)}

    colors = [ACCENT if lo in peaks else GREY for lo in los]
    ax.bar(range(len(los)), share, color=colors, width=0.82, linewidth=0)
    ax.set_xticks(range(len(los)))
    ax.set_xticklabels([_us_label(v) for v in los], fontsize=6, rotation=90)
    ax.set_xlabel("run-queue stall (µs, log2 buckets)", fontsize=7.5)
    ax.set_ylabel("share of wakeups (%)", fontsize=7.5)
    ax.tick_params(labelsize=7)
    ax.grid(axis="y", alpha=0.25, lw=0.5)

    for lo, _, frac, rise in tit.modes(bins):
        i = los.index(lo)
        ax.annotate("%.1f%%" % (100 * frac), xy=(i, share[i]), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=6.5, color=ACCENT)
        if slice_ms is not None and lo == _slice_bucket(los, slice_ms):
            # Anchored to the right of the bar and above it: to its left is the 128 us hump,
            # and a label placed there runs into the axis.
            ax.annotate("scheduler base slice:\n%.0f ms, %.1f× the bucket below"
                        % (slice_ms, rise),
                        xy=(i + 0.46, share[i] * 0.72),
                        xytext=(len(los) - 0.5, max(share) * 1.30),
                        fontsize=6.4, color=DELETED, ha="right", va="top",
                        arrowprops=dict(arrowstyle="->", color=DELETED, lw=0.8,
                                        connectionstyle="arc3,rad=0.18"))
    ax.set_ylim(0, max(share) * 1.42)
    ax.set_xlim(-0.8, len(los) - 0.2)


def _us_label(us):
    if us >= 1024:
        return "%gK" % (us / 1024)
    return "%g" % us


def _slice_bucket(los, slice_ms):
    """The log2 bucket the base slice falls in: the largest bucket start at or below it."""
    target = slice_ms * 1000.0
    below = [v for v in los if v <= target]
    return max(below) if below else None


# --- grid membership ----------------------------------------------------------------------

def plot_grid(ax, cells):
    """Observed distance to the grid against the distance a continuum would give.

    The table this replaces answered "is each arm significant". The claim is about the set:
    every powered arm sits below the diagonal, which is what "the rates lie on the grid"
    means when you draw it.
    """
    rows = sorted(cells, key=lambda r: r["rate_hz"])
    xs = [r["d_null"] for r in rows]
    ys = [r["d_obs"] for r in rows]
    powered = [r["powered"] for r in rows]

    lim = max(xs + ys) * 1.12
    ax.plot([0, lim], [0, lim], color=GREY, lw=0.8, ls="--", zorder=1)
    # Below the diagonal is the whole claim: closer to the grid than a continuum would be.
    ax.fill_between([0, lim], [0, 0], [0, lim], color=KEPT, alpha=0.06, zorder=0)
    ax.annotate("a continuum would\nland on this line", xy=(lim * 0.40, lim * 0.40),
                xytext=(lim * 0.17, lim * 0.60), fontsize=6.4, color=GREY, ha="center",
                arrowprops=dict(arrowstyle="->", color=GREY, lw=0.7))
    ax.text(lim * 0.72, lim * 0.11, "closer to the grid", fontsize=6.4,
            color=KEPT, ha="center", style="italic")

    for x, y, p in zip(xs, ys, powered):
        ax.plot(x, y, "o" if p else "s", ms=5 if p else 4.2,
                color=KEPT if p else "none", mec=KEPT if p else GREY,
                mew=0.9, zorder=3)
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("distance expected from a continuum", fontsize=7.5)
    ax.set_ylabel("distance observed", fontsize=7.5)
    ax.tick_params(labelsize=7)
    ax.grid(alpha=0.25, lw=0.5)

    n_pow = sum(powered)
    ax.plot([], [], "o", color=KEPT, mec=KEPT, ms=5, label="powered (%d)" % n_pow)
    ax.plot([], [], "s", color="none", mec=GREY, mew=0.9, ms=4.2,
            label="underpowered (%d)" % (len(rows) - n_pow))
    ax.legend(fontsize=6.5, frameon=False, loc="upper left")


def grid_rows():
    """The grid arms, from the same helper the ledger and the table use."""
    out = []
    for c in stat_intervals.grid_cells():
        out.append({"rate_hz": c["rate_hz"], "q": c["q"], "powered": c["powered"],
                    "d_obs": c["d_observed"], "d_null": c["d_null"]})
    return out


# --- driver -----------------------------------------------------------------------------

def _save(fig, out_dir, stem):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ("%s.pdf" % stem)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    return path


def build_deletion(out_dir):
    fig, ax = plt.subplots(figsize=(3.4, 2.5))
    plot_deletion(ax, retention_points())
    fig.tight_layout()
    return _save(fig, out_dir, "deletion")


def build_spectrum(out_dir, slice_ms=None):
    if slice_ms is None:
        try:
            import kernel_constants
            slice_ms = kernel_constants.constants()["base_slice_ms"]
        except (ImportError, OSError, KeyError, ValueError):
            slice_ms = None
    bins, _ = stall_histogram()
    fig, ax = plt.subplots(figsize=(3.4, 2.5))
    plot_spectrum(ax, bins, slice_ms)
    fig.tight_layout()
    return _save(fig, out_dir, "stall_spectrum")


def build_grid(out_dir):
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    plot_grid(ax, grid_rows())
    fig.tight_layout()
    return _save(fig, out_dir, "grid_membership")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the result figures")
    ap.add_argument("--out", default=os.path.join("docs", "results", "figures"))
    ap.add_argument("--only", choices=("deletion", "spectrum", "grid"), default=None)
    args = ap.parse_args(argv)

    builders = {"deletion": build_deletion, "spectrum": build_spectrum, "grid": build_grid}
    todo = [args.only] if args.only else list(builders)
    for name in todo:
        path = builders[name](args.out)
        print("wrote %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
