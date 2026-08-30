#!/usr/bin/env python3
"""
make_axis_comparison.py
The benchmark's own published chart, and ours on the same axes.

Origin. D. Gregg sent the reference OpenMessaging Benchmark write-up and its end-to-end latency
chart, and asked what our data would look like drawn the same way. This is that, side by side,
with the axes held identical between the two panels so the only thing that differs is the data.

Both panels: x is percentile (0 to 100, linear), y is latency in milliseconds on a symmetric-log
scale so that one axis can hold a value of -99 ms and a value of +692 ms and still show the
region around zero, which is where the whole argument lives.

The two things the figure is for:

    Their distribution stops dead at 1 ms. That floor is the quantum, not the network. The
    benchmark differences two millisecond-resolution stamps and admits the sample only when the
    difference is strictly positive, so everything faster than one tick computes to zero and is
    deleted. A distribution built that way cannot begin anywhere except at one tick, and theirs
    does not.

    Ours, measured on the same kind of path with a finer clock, crosses zero at the 8.43rd
    percentile and keeps going down to -99.8 ms. That population is not noise and it is not
    clock skew; it is the same population their guard removes, which is why their chart has a
    floor and ours does not.

Why their own chart cannot show any of this, which `plot_omb_native` draws separately. Their
published axes are chosen for the tail: x is a tail scale whose ticks are 90, 99, 99.9, 99.99
and 99.999 per cent -- each step a tenfold cut in the fraction remaining -- against a linear
0-700 ms y-axis. Two consequences. Everything below the 90th percentile, nine tenths of the
distribution, is compressed into a narrow strip at the left. And a 1 ms floor on a 0-700 ms
axis sits on the frame. The deletion happens at the bottom-left of a picture drawn to show the
top-right; it is not hidden, it is simply out of scale.

CLI:
    python scripts/make_axis_comparison.py              # paper width
    python scripts/make_axis_comparison.py --talk       # slide width
"""
import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import figure_style
import omb_published_quantiles

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HIST_CSV = os.path.join("docs", "results", "span_histogram.csv")
OMB_CSV = os.path.join("docs", "results", "omb_published_quantiles.csv")
OUT_DIR = os.path.join("docs", "results", "figures")

OMBC = "#7a7a7a"
OURS = "#A81F1F"
OURS2 = "#B4670A"
GREY = "#555555"
CUT = "#A81F1F"
GOOD = "#1F7A4D"

def our_quantiles(path=None, span="ack"):
    """Percentile -> latency in ms, from the committed bin counts.

    The percentile paired with a bin edge is the share of events lying strictly BELOW that
    edge. Getting this wrong by one bin is not cosmetic: pairing a bin's lower edge with the
    cumulative count *after* that bin puts the zero crossing at the 11.27th percentile, when
    the share of events actually below zero is 8.43% -- the number the paper quotes. The figure
    would then contradict the manuscript on the manuscript's own headline quantity.

    Bins are 50 us wide, so a quantile is read to that resolution and no finer. Ample here:
    the claims are about which side of zero a percentile falls on.

    `path=None` resolves to the module constant at call time, so a test can repoint the
    constant; a default bound at def time silently reads the committed corpus instead.
    """
    path = HIST_CSV if path is None else path
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    header = rows[0][2:]
    col = header.index(span)
    bins, under, over = [], 0, 0
    for row in rows[1:]:
        if row[0] == "UNDERFLOW":
            under = int(row[2 + col]); continue
        if row[0] == "OVERFLOW":
            over = int(row[2 + col]); continue
        bins.append((int(row[0]), int(row[2 + col])))
    total = under + over + sum(c for _lo, c in bins)

    pts, below = [], under
    for lo, count in bins:
        if count:
            pts.append((100.0 * below / total, lo / 1000.0))   # share strictly below; us -> ms
        below += count
    return pts, total, over, total


def _plot_series(ax, pts, colour, label, lw=1.8, z=3):
    ax.plot([p for p, _ in pts], [v for _, v in pts], color=colour, linewidth=lw,
            label=label, zorder=z, solid_capstyle="round")


def _frame(ax, title):
    ax.set_yscale("symlog", linthresh=1.0, linscale=0.9)
    ax.set_ylim(-200, 1000)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_yticks([-100, -10, -1, 0, 1, 10, 100, 1000])
    ax.set_yticklabels(["-100", "-10", "-1", "0", "1", "10", "100", "1000"])
    ax.axhline(0, color=GREY, linewidth=1.0, linestyle=(0, (3, 2)), zorder=1)
    ax.set_xlabel("Percentile")
    ax.set_ylabel("Latency (ms)")
    ax.set_title(title, fontsize=8.5, loc="left")


def plot_omb(ax, pts):
    """(a) their series, redrawn on the axes this figure uses for both panels.

    Titled honestly. This is their DATA, not their CHART: the published chart uses a
    tail-focused percentile axis (ticks at 90, 99, 99.9, 99.99, 99.999 -- each step a tenfold
    cut in the fraction remaining) against a linear 0-700 ms scale. On those axes a 1 ms floor
    is one pixel off the bottom and the lower nine tenths of the distribution are compressed
    into a sliver at the left, which is why the deletion cannot be seen on their own figure.
    Their chart is reproduced faithfully, on its own axes, by `plot_omb_native` below.
    """
    _frame(ax, "(a) OpenMessaging Benchmark's published data (kafka-local)")
    # Everything below one tick is empty by construction, not by measurement.
    ax.axhspan(-200, 1.0, color=CUT, alpha=0.07, linewidth=0, zorder=0)
    _plot_series(ax, pts, OMBC, "published series")

    floor = min(v for _p, v in pts)
    p_at_floor = min(p for p, v in pts if v == floor)
    ax.plot([p_at_floor], [floor], marker="o", markersize=5, color=OMBC, zorder=4)
    # Below the zero rule, not across it: anchored near y=0 the second line was struck through
    # by the dashed zero guide, which is the one line on this panel that must stay readable.
    ax.annotate("floor = 1 ms = one clock tick\nnothing below it exists",
                xy=(p_at_floor, floor), xytext=(22, -0.55),
                fontsize=7, color=CUT, va="top",
                arrowprops=dict(arrowstyle="->", color=CUT, linewidth=0.9))
    ax.text(0.97, 0.05, "tail reaches 692 ms", transform=ax.transAxes,
            fontsize=7, color=GREY, ha="right")


def plot_omb_native(ax, pts):
    """Their chart, reproduced on ITS OWN axes, annotated.

    x is the tail scale the original uses: position = -log10(1 - p/100), so 90, 99, 99.9,
    99.99 and 99.999 fall at 1, 2, 3, 4, 5 and sit evenly spaced. y is linear milliseconds.
    Drawn so the axes can be explained from the picture rather than described.
    """
    import math

    def tx(p):
        return -math.log10(max(1e-9, 1.0 - p / 100.0))

    ax.plot([tx(p) for p, _v in pts], [v for _p, v in pts], color="#E4572E", linewidth=1.6)
    ax.set_xlim(tx(4.0), tx(99.9995))
    ax.set_ylim(0, 720)
    ticks = [90.0, 99.0, 99.9, 99.99, 99.999]
    ax.set_xticks([tx(t) for t in ticks])
    ax.set_xticklabels(["90.0 %", "99.0 %", "99.9 %", "99.99 %", "99.999 %"])
    ax.set_yticks([0, 100, 200, 300, 400, 500, 600, 700])
    ax.grid(True, which="major", color=GREY, linewidth=0.6, linestyle=(0, (4, 4)), alpha=0.55)
    ax.set_axisbelow(True)
    ax.set_xlabel("Percentile")
    ax.set_ylabel("Latency (ms)")
    ax.set_title("The published chart, reproduced on its own axes", fontsize=8.5, loc="left", pad=20)

    # Labels sit on what they describe. The first attempt used leader arrows from the top of
    # the panel down to the baseline, and three long diagonals crossed both the curve and each
    # other -- unreadable, and they drew the eye away from the data.
    ax.axvspan(tx(4.0), tx(90.0), color=CUT, alpha=0.06, linewidth=0, zorder=0)
    ax.text(tx(55), 660, "everything below the 90th percentile\n"
                         "-- nine tenths of the data --\nis this strip",
            fontsize=7.5, color=CUT, ha="center", va="top", linespacing=1.15,
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.88, pad=2.5))

    # The floor, marked where it actually is rather than pointed at from a distance.
    ax.axhline(1.0, color=CUT, linewidth=1.0, zorder=2)
    ax.text(tx(99.99), 14, "the 1 ms floor is this line -- on a 0-700 ms axis "
                           "it is indistinguishable from zero",
            fontsize=7.5, color=CUT, ha="right", va="bottom",
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.88, pad=2.5))

    ax.text(0.0, 1.012, "x is a tail scale: each tick cuts the remaining fraction tenfold. "
                        "y is linear milliseconds.",
            transform=ax.transAxes, fontsize=7.5, color=GREY, va="bottom")
    ax.text(0.985, 0.62, "the jump at ~99.97%\nis a real tail event",
            transform=ax.transAxes, fontsize=7, color=GREY, ha="right")


def plot_ours(ax, ack, send, above_pct):
    """(b) our corpus, identical axes."""
    _frame(ax, "(b) Our corpus, identical axes")
    ax.axhspan(-200, 0.0, color=CUT, alpha=0.07, linewidth=0, zorder=0)
    _plot_series(ax, ack, OURS, "ack-referenced span")
    _plot_series(ax, send, OURS2, "send-referenced span", lw=1.4, z=2)

    crossing = None
    for p, v in ack:
        if v >= 0:
            crossing = p
            break
    if crossing is not None:
        ax.plot([crossing], [0], marker="o", markersize=5, color=OURS, zorder=4)
        ax.annotate("crosses zero at the\n%.2fth percentile" % crossing,
                    xy=(crossing, 0), xytext=(34, -26),
                    fontsize=7, color=CUT,
                    arrowprops=dict(arrowstyle="->", color=CUT, linewidth=0.9))
    ax.text(0.03, 0.06, "no floor: the population\ntheir guard deletes is here",
            transform=ax.transAxes, fontsize=7, color=CUT, va="bottom")
    # The curve stops short of 100 because the top slice sits above the binning window. Saying
    # so is the same discipline the paper asks of everyone else.
    ax.text(0.97, 0.05, "top %.1f%% lies above +100 ms,\nbeyond the binning window" % above_pct,
            transform=ax.transAxes, fontsize=6.5, color=GREY, ha="right")
    ax.legend(fontsize=6.5, loc="upper left", frameon=False)


def build(out_dir=OUT_DIR, talk=False):
    figure_style.apply()
    omb = omb_published_quantiles.read_csv(OMB_CSV)
    ack, total, over, _t = our_quantiles(span="ack")
    send, _t2, _o2, _t3 = our_quantiles(span="send")
    above_pct = 100.0 * over / total if total else 0.0

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    made = []

    def _save(fig, stem):
        for ext in (("png",) if talk else ("pdf", "png")):
            path = os.path.join(out_dir, "%s.%s" % (stem, ext))
            fig.savefig(path, bbox_inches="tight", pad_inches=0.03,
                        dpi=200 if ext == "png" else None)
            made.append(path)
        plt.close(fig)

    # 1. their chart on its own axes, so the axes can be explained from the picture
    fig1, ax1 = plt.subplots(figsize=(9.0, 4.6) if talk else (5.4, 3.0))
    plot_omb_native(ax1, omb)
    fig1.tight_layout()
    _save(fig1, "omb_axes_explained_talk" if talk else "omb_axes_explained")

    # 2. both series on one shared pair of axes
    size = (12.0, 4.4) if talk else (7.16, 3.0)
    fig2, axes = plt.subplots(1, 2, figsize=size)
    plot_omb(axes[0], omb)
    plot_ours(axes[1], ack, send, above_pct)
    fig2.tight_layout()
    _save(fig2, "axis_comparison_talk" if talk else "axis_comparison")
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description="Their published chart and ours, same axes")
    ap.add_argument("--talk", action="store_true")
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args(argv)
    for p in build(args.out_dir, talk=args.talk):
        print("wrote %s" % p)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
