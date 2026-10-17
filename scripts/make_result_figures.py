#!/usr/bin/env python3
"""
make_result_figures.py
The result figures, drawn from the committed artefacts rather than described in prose.

Why these, and why now. Three readers in a row have said the manuscript is hard to follow, and
measuring it against the journal's own published corpus turned the complaint into a number: the
median regular paper in that corpus carries thirteen figures and this one carried two. The
results that were hardest to follow were the ones that existed only as prose and a table of
numbers, and each of them is a picture:

  deletion  -- the headline. Retention swings across two and a half orders of magnitude while
               the median the benchmark prints does not move at all. Said in a sentence it
               sounds like a paradox; drawn, it is obvious, because the printed median is a
               property of the grid and the retention is a property of the phase.

  spectrum  -- the traced stall distribution, which is trimodal, with the last of the three
               modes sitting on the scheduler's base slice. (The last of the three, and the
               smallest: it holds 10.5% of wakeups against the jitter core's 20.0%. Round 30
               corrected that adjective in the manuscript and this docstring kept the wrong one
               two rounds longer, which is why the ordinal gate reads scripts too.) The
               mechanism argument in Section V rests entirely on where that mode is, and
               asking a reader to hold a log2 histogram in their head from a list of bucket
               counts is asking too much.

  grid      -- membership against a continuum null, beside the table that carries the same
               numbers. A table of twelve p-values answers "is each arm significant"; the
               figure answers "does the whole set lie on the grid", which is the actual claim.

  mechanism -- the four matched pairs as a forest of Wilson intervals. Table III gives the
               numbers, and the numbers are the evidence; what the table cannot show at a
               glance is that no pair overlaps, which is the causal claim itself.

  ttrue     -- inversion rate against the interval being measured. The negative-span
               probability as a function of T_true, as an
               experiment: lengthening the true transport lowers the rate, where an account
               driven by load alone predicts no change. It had no figure at all.

Every number drawn here comes from the same artefacts and the same estimators the ledger uses,
so a figure cannot drift from the text: `stat_intervals` for the intervals, `tail_index_traced`
for the histogram parse, and the committed CSVs for everything else. Nothing is recomputed by
eye and nothing is smoothed.

CLI:
    python scripts/make_result_figures.py --out docs/results/figures
"""
import argparse
import os
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import figure_style  # noqa: E402
import figure_collisions  # noqa: E402
import figure_legibility  # noqa: E402
import figure_vocabulary  # noqa: E402
figure_style.apply()  # Type 42, IEEE-listed family; see scripts/figure_style.py
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
                pts.append((float(r["retention_pct"]), float(r["omb_p50_ms"]),
                            _payload_label(r.get("cell", ""))))
            except (KeyError, ValueError):
                continue
    if not pts:
        raise ValueError("no usable retention rows in %s" % path)
    return pts


def incommensurate_points(path=RETENTION_CSV):
    """(retention %, printed median ms) of every captured setting at an incommensurate rate.

    15 Oct 2026, referee B (Fig. 4): the retention law's test rests on the configurations whose
    publish interval bears no ratio of small whole numbers to the clock's step, the arms
    `stat_intervals.spread_cells` returns with `commensurate` false. A cell of the retention
    file is one of them when its campaign paced the producer at one of those rates, which its
    name gives ("r457_rep2"). Of the seven rates, the benchmark's own summary was captured at
    two, so their cells are the ones panel (b) can mark.
    """
    import csv
    loose = {c["rate_hz"] for c in stat_intervals.spread_cells() if not c["commensurate"]}
    pts = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            m = re.match(r"^r(\d+)_rep\d+$", r.get("cell", ""))
            if m and int(m.group(1)) in loose:
                pts.append((float(r["retention_pct"]), float(r["omb_p50_ms"]),
                            int(m.group(1))))
    return pts


def _payload_label(cell):
    """The payload a cell name encodes, as a printable size, or "" if it encodes none.

    Only the resolution sweep names its payload, and only those cells escape the quantum, so
    this is exactly the set the figure needs to label.
    """
    m = re.match(r"^s(\d+)_", cell or "")
    if not m:
        return ""
    b = int(m.group(1))
    return "%d KB" % (b // 1024) if b >= 1024 else "%d B" % b


# The largest printed median that still reads as a grid value. The quantum itself is 1 ms
# (Section V-B); 2 ms is the next vertex, so a cell printing 1.0 or 2.0 is reporting AT the
# grid and one printing 250 ms is not. Round 56 renamed it: called QUANTUM_MS it asserted
# that the quantum was two milliseconds, which is the one thing it is not.
AT_GRID_MAX_MS = 2.0

# How far the grid figure's null bars sit left of the arms they belong to, as a fraction of
# the axis. Wide enough to clear a 5 pt marker and the dashed diagonal at column width,
# narrow enough that the bar is unambiguously the one beside it.
DODGE_FRACTION = 0.022

# Two markers closer than this on a log axis, as a ratio, are one marker to the eye.
COINCIDENT_RATIO = 1.06
# And this is how far apart they have to go to stop being one. A marker in the deletion
# figure is about 4.8 pt across and a decade of that axis is about 46 pt wide, so a tenth of
# a decade is one marker's width.
#
# One marker's width was the first answer and it was the wrong one: separating two centres by
# exactly one diameter leaves the two circles touching, and round 45 found them on the printed
# page rendering as a single figure-of-eight -- the same undercount the spreading was written
# to prevent, one step further along. Two diameters of centre separation is what makes two
# markers read as two. That is 0.21 of a decade, or 3.7% of this axis, still small enough that
# no reading of position changes; the label of a payload whose markers were set apart says so
# (since 15 Oct 2026; the caption was said to and did not).
SEPARATION_RATIO = 1.62


def spread_coincident(xs, ys, ratio=COINCIDENT_RATIO, separation=SEPARATION_RATIO):
    """Nudge markers apart that would otherwise render as one, on a log x axis.

    The legend of the deletion figure counts the cells it draws. Two of them -- the 256 KB
    replicates, printing 42,393 and 42,973 ms -- sit 1.4% apart across five decades, so the
    figure announced four points and drew three. In a paper whose argument is that an
    instrument should show what it discarded, a picture that quietly loses one of its own
    four markers is not a rendering detail.

    Points are grouped by shared y and near-equal x, and each group is spread symmetrically
    about its own geometric centre. Symmetric, so the group's centre of mass does not move
    and no reading of position is altered beyond the separation itself; multiplicative,
    because the axis is logarithmic. Returns new x values and leaves y untouched.
    """
    out = list(xs)
    order = sorted(range(len(out)), key=lambda i: (ys[i], out[i]))
    group = []

    def flush(g):
        if len(g) < 2:
            return
        # Enough separation to read as distinct, centred so nothing shifts on average.
        for rank, idx in enumerate(g):
            step = rank - (len(g) - 1) / 2.0
            out[idx] = out[idx] * (separation ** step)

    for i in order:
        if group and ys[i] == ys[group[-1]] and out[i] <= out[group[-1]] * ratio:
            group.append(i)
            continue
        flush(group)
        group = [i]
    flush(group)
    return out


def plot_deletion(ax, pts, quantum_ms=AT_GRID_MAX_MS, marked=()):
    """Retention against the median the benchmark printed, every committed cell.

    `marked` (15 Oct 2026) holds the cells at an incommensurate rate, ringed on top of their
    own markers and counted in the legend, because the retention law's test rests on them: an
    incommensurate rate spreads the publish instants evenly over the clock's step, as the law
    assumes.

    Every cell is drawn, including the four where the payload is large enough that the
    quantum stops binding. Dropping them would be the same move the paper is about. They
    also carry the argument: away from the grid the benchmark behaves, and the failure is
    confined to the region where the interval it is asked to measure is smaller than the
    instrument it measures with.
    """
    from matplotlib.ticker import FuncFormatter
    ret = np.array([p[0] for p in pts])
    med = np.array([p[1] for p in pts])
    tags = [p[2] if len(p) > 2 else "" for p in pts]
    at_grid = med <= quantum_ms

    # The above-grid markers are counted in their own legend entry, so each one has to be
    # visible.
    above_x = spread_coincident(list(med[~at_grid]), list(ret[~at_grid]))

    # Round 79 (W3). The at-grid stripe used to be left alone as "read as a range", and the
    # legend still counted it: 71 cells, 67 of them in one column of 4-point markers, where 57
    # of the 66 neighbouring pairs sit closer than a marker. A reader could count about two
    # dozen. The caption's count could not be checked from the picture, which is the defect
    # B15 exists to prevent. The markers go translucent, so overlap shows as depth, and each
    # grid column prints its own count from the data (below), totalling the legend's.
    # v5 (28 Sep): the legend says what the grid values are, so "67" and "4" above the two
    # columns decode without the caption -- an outside editor's reading could not tell what they
    # counted. Derived per grid value, like the ticks and the counts.
    # The per-value counts moved onto the plot itself (below), where the editor asked for them;
    # the legend keeps the marker's meaning and the total.
    grid_label = "%s ms (%d)" % (" or ".join("%g" % g for g in sorted(set(med[at_grid].tolist()))),
                                 int(at_grid.sum()))
    ax.scatter(med[at_grid], ret[at_grid], s=16, color=KEPT, edgecolors="none", alpha=0.45,
               zorder=3, label="printed %s" % grid_label)
    ax.scatter(above_x, ret[~at_grid], s=18, facecolors="none", edgecolors=GREY,
               linewidths=0.9, zorder=3, label="printed above %g ms, by payload (%d)" % (quantum_ms, (~at_grid).sum()))
    if marked:
        # Drawn over the column they sit in, as diamonds that do not hide its markers. 15 Oct
        # 2026, three internal reviews: the long label ("8 settings at incommensurate rates, 383
        # and 457 msg/s") made the legend so wide that its markers fell on the 1 ms column, one
        # over the lowest retention, each reading as a datum. The entry counts what it marks,
        # as the other two do, and the caption names the two rates of Section V-C's seven.
        ax.scatter([p[1] for p in marked], [p[0] for p in marked], s=30, marker="D",
                   facecolors="none", edgecolors="#222222", linewidths=0.9, zorder=4,
                   label="incommensurate rate (%d)" % len(marked))
    ax.set_xscale("log")
    ax.set_yscale("log")
    # "log" in the labels, and the ticks written out: as 10^n their exponents printed at 5.75 pt
    # (15 Oct 2026, an internal review of the printed figures).
    ax.set_xlabel("median latency the benchmark printed (ms, log)", fontsize=8)
    ax.set_ylabel("samples retained (%, log)", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.yaxis.set_major_formatter(FuncFormatter(figure_style.plain_log_label))
    ax.grid(alpha=0.25, lw=0.5)
    ax.axhline(100, color=GREY, lw=0.6, ls=":", zorder=0)

    # Round 76. The caption says the at-grid cells print "1.0 or 2.0 ms", and until now the
    # picture could not be used to check it: those two values are 0.3 of a decade apart on an
    # axis spanning five, and a log axis labels decades only, so the two columns read as one
    # stripe and the reader had to take the sentence on trust. That is the wrong way round in
    # this paper of all papers. The grid vertices get their own labelled ticks.
    #
    # Derived from the data rather than written as [1, 2]: if a future campaign prints a
    # third grid value the axis grows a third tick instead of the figure quietly asserting
    # there were two.
    grid_values = sorted(set(med[at_grid].tolist()))
    ax.set_xticks(grid_values, minor=True)
    ax.set_xticklabels(["%g" % v for v in grid_values], minor=True)
    # Round 77 (W3). matplotlib drops a minor tick that coincides with a major one, so the
    # grid value 1 kept its decade label "10^0" while 2 read "2": the caption's two values in
    # two notations. Since 15 Oct 2026 every decade is written out as the grid values are, "1",
    # "10", "1k", so the two notations cannot return.
    ax.xaxis.set_major_formatter(FuncFormatter(figure_style.plain_log_label))
    # 8 pt, not the 7 that would fit more comfortably: `figure_legibility` holds every figure
    # to the journal's floor and caught the smaller size on the first build. A tick a reader
    # cannot read is not a repair for a claim a reader cannot check. The minor tick's length and
    # pad add up to the major's 3.5 and 3.5, so that "2" sits on the line the decades' labels
    # sit on: with a pad of 1.5 it floated 4 pt above them (15 Oct 2026).
    ax.tick_params(axis="x", which="minor", labelsize=8, length=2.5, pad=4.5)

    # Each grid column's count, just above its topmost marker, from the same data the legend
    # totals. Derived per grid value, like the ticks, so a third value would get a third count.
    # v5 (28 Sep): the count says what it counts, "67 printed 1.0 ms", because an outside
    # editor could not decode a bare "67" without the caption. Set off to the right of its
    # column so the two labels cannot sit on each other.
    for g in grid_values:
        column = ret[at_grid][med[at_grid] == g]
        ax.text(g * 1.1, column.max() * 1.22, "%d printed %.1f ms" % (len(column), g),
                fontsize=8, color=KEPT, ha="left", va="bottom")

    lo, hi = ret[at_grid].min(), ret[at_grid].max()
    xs = med[at_grid].min()
    ax.annotate("", xy=(xs * 0.62, lo), xytext=(xs * 0.62, hi),
                arrowprops=dict(arrowstyle="<->", color=DELETED, lw=1.0))
    ax.text(xs * 0.55, (lo * hi) ** 0.5, "%.0f×" % (hi / lo), fontsize=8,
            color=DELETED, va="center", ha="right", rotation=90)
    ax.set_xlim(xs * 0.30, med.max() * 3)
    ax.set_ylim(lo * 0.45, 260)

    # Name the cells that escape. They are the mechanism stated in one word: the quantum stops
    # binding once the interval is larger than it, and the payload is what made it larger. One
    # label per distinct payload, at the leftmost of its replicates, so replicates at the same
    # size do not print the same word twice.
    # 15 Oct 2026, an internal review: replicates spread apart by `spread_coincident` were said
    # to be disclosed by the caption, which did not; the label says it now, with their count.
    # Under its group, right-aligned under the last marker, so that the longer label stays clear
    # of the frame at the right of the axis.
    above_tags = [tg for tg, g in zip(tags, at_grid) if not g]
    moved = {tg for x0, x1, tg in zip(med[~at_grid], above_x, above_tags) if x1 != x0}
    last = dict((tg, x) for x, tg in sorted(zip(above_x, above_tags)))
    seen = set()
    for x, y, tag in sorted(zip(above_x, ret[~at_grid], above_tags)):
        if not tag or tag in seen:
            continue
        seen.add(tag)
        if tag in moved:
            ax.annotate("%s\n(×%d, set apart)" % (tag, above_tags.count(tag)),
                        xy=(last[tag], y), xytext=(6, -9), textcoords="offset points",
                        fontsize=8, color=GREY, ha="right", va="top", linespacing=1.1)
        else:
            ax.annotate(tag, xy=(x, y), xytext=(0, -9), textcoords="offset points",
                        fontsize=8, color=GREY, ha="center", va="top")

    leg = ax.legend(fontsize=8, frameon=False, loc="lower right", handletextpad=0.4)
    # The legend's marker is the category, not a depth of overlap: drawn opaque.
    for handle in getattr(leg, "legend_handles", None) or getattr(leg, "legendHandles", []):
        handle.set_alpha(1.0)


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
    ax.set_xticklabels([_us_label(v) for v in los], fontsize=8, rotation=90)
    ax.set_xlabel("scheduling delay (µs, log2 buckets)", fontsize=8)
    ax.set_ylabel("share of wakeups (%)", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(axis="y", alpha=0.25, lw=0.5)

    for lo, _, frac, rise in tit.modes(bins):
        i = los.index(lo)
        ax.annotate("%.1f%%" % (100 * frac), xy=(i, share[i]), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=8, color=ACCENT)
        if slice_ms is not None and lo == _slice_bucket(los, slice_ms):
            # Anchored to the right of the bar and above it: to its left is the 128 us hump,
            # and a label placed there runs into the axis.
            # Two short lines rather than one long one. Right-aligned at the frame, the
            # previous wording reached back to x = 7.5 in bucket units while the 1 ms
            # rule stands at 9.47, so the rule ran through its second line -- invisible
            # for as long as the reference-line check measured an axvline through the
            # wrong transform. Every fact is kept; the widest line is now narrow enough.
            # "the one below", not "its neighbor": the mode has two neighbours and they give
            # different answers -- 4.5x the bucket below it and 5.0x the one above. The body
            # says "its lower neighbor", and a figure that says only "its neighbor" sends a
            # reader checking the histogram by eye to the wrong bar.
            # "%.1f": the derived slice is 2.8 ms, which "%.0f" printed as 3 ms, the slice the
            # registered campaign set by hand and Fig. 3 draws (15 Oct 2026, an internal review).
            ax.annotate("base slice: %.1f ms\n%.1f× the one below"
                        % (slice_ms, rise),
                        xy=(i + 0.62, share[i] * 0.72),
                        xytext=(len(los) - 0.5, max(share) * 1.30),
                        fontsize=8, color=DELETED, ha="right", va="top",
                        # Bowed away from the bar rather than towards it: the original arc
                        # passed through the "%.1f%%" label sitting above the same bar.
                        arrowprops=dict(arrowstyle="->", color=DELETED, lw=0.8,
                                        relpos=(0.5, 0.0),
                                        connectionstyle="arc3,rad=-0.28"))
    # The tick, beside the slice. The paper argues both matter and this is why the mode is a
    # band rather than a spike: a thread descheduled at the wrong instant reads its clock a
    # slice late, and the tick is the grain that clock reports in.
    x_tick = _bucket_position(los, 1000.0)
    if x_tick is not None:
        # Drawn to just above the tallest bar rather than to the top of the frame. A
        # full-height rule runs through the second line of the slice callout, which the
        # reference-line check could not see while it measured an axvline with the wrong
        # transform, and which is visible at print size once it can. The rule marks a
        # position on the x-axis; it has no business in the callout's airspace.
        ax.plot([x_tick, x_tick], [0, max(share) * 1.02],
                color=GREY, lw=0.8, ls=(0, (3, 2)), zorder=0)
        # At the foot of its own rule. The top right of this axis belongs to the slice
        # callout, and a label placed up there shares half its area -- which is how the
        # collision gate found the first attempt. rotation_mode="anchor" is not decoration:
        # under the default mode the box is aligned and then swung about the anchor, which
        # put the leading "1" below the axis, where the frame clipped it off.
        # Standing on whichever of the two bars it straddles is taller, rather than at y=0:
        # the label is about half a bucket wide once rotated, so from the axis it grows up
        # through the 1K bar and the collision gate says so.
        near = [share[j] for j in (int(x_tick), int(x_tick) + 1) if 0 <= j < len(share)]
        ax.annotate("1 ms tick", xy=(x_tick, max(near or [0.0])), xytext=(3, 3),
                    textcoords="offset points", fontsize=8, color=GREY, ha="left",
                    va="bottom", rotation=90, rotation_mode="anchor",
                    # The y-grid runs the full width, so a vertical label crosses two of the
                    # rules whatever height it stands at. Same white patch the forest's
                    # factor column uses, for the same reason.
                    bbox=dict(facecolor="white", edgecolor="none", pad=0.8))

    ax.set_ylim(0, max(share) * 1.42)
    ax.set_xlim(-0.8, len(los) - 0.2)


def _us_label(us):
    if us >= 1024:
        return "%gK" % (us / 1024)
    return "%g" % us


def _bucket_position(los, us):
    """Where a value falls on the categorical axis, in bar units, inside its own bucket.

    A log2 bucket starting at `lo` covers [lo, 2*lo), and the bar for it is centred on its
    index. A value is therefore at index - 0.5 + log2(us/lo): 1 ms lands at the top edge of
    the 512 us bucket, not at its centre, and drawing it at the centre says 1 ms = 512 us.
    """
    lo = _slice_bucket(los, us / 1000.0)
    if lo is None:
        return None
    return los.index(lo) - 0.5 + float(np.log2(us / lo))


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
    # Three classes, not two. "Powered" is not the distinction the claim turns on: one
    # powered arm does not reject after correction, and drawing it like the nine that do
    # shows ten successes where the text claims nine.
    klass = []
    for r in rows:
        if not r["powered"]:
            klass.append("coincident")
        elif str(r.get("verdict", "")).startswith("grid"):
            klass.append("grid")
        else:
            klass.append("unresolved")

    bands = [(r.get("d_null_lo"), r.get("d_null_hi")) for r in rows]
    lim = max(xs + ys + [h for _, h in bands if h]) * 1.12
    ax.plot([0, lim], [0, lim], color=GREY, lw=0.8, ls="--", zorder=1)
    # Below the diagonal is the whole claim: closer to the grid than a continuum would be.
    ax.fill_between([0, lim], [0, 0], [0, lim], color=KEPT, alpha=0.06, zorder=0)

    # Each arm's own null. Without it the figure asked the eye to judge distance from a line
    # with nothing to say how far an arm can fall by chance; the p-values that answered that
    # were printed only in a supplement table. The test is one-sided towards the grid, so an
    # arm whose marker falls BELOW its own bar is an arm that rejects the null this bar
    # draws, and the picture carries that much of the test rather than illustrating it.
    #
    # It carries no more than that, and round 49 is why the sentence now says so. The bars
    # are the UNCORRECTED null; every verdict in the legend is Holm-corrected across the
    # family, and correction is not a geometric property. For nine arms the two agree. The
    # tenth sits 0.0033 below its bar -- rejecting raw at 0.044 -- and does not survive
    # correction at 0.131, so the picture and the legend disagree about it and only the
    # caption can reconcile them. This comment said "clears its own bar", without a
    # direction, for four rounds after round 45 corrected exactly that wording in the
    # caption it describes.
    #
    # Dodged a little left of the arm's own x, the way any error bar is dodged off the point
    # it belongs to. Drawn on the arm's x, each bar is centred on the diagonal -- the diagonal
    # IS the null's centre -- so the diagonal cuts every bar near its middle, and in the
    # right-hand fifth, where five of the twelve arms sit within 0.05 of each other, bars,
    # diagonal and neighbours interleaved into one smudge at column width. The dodge does not
    # stop the diagonal crossing a wide bar, and cannot without a displacement large enough to
    # misreport position; what it does is take the bars off the arms' own abscissae so the
    # reference reads as separate from the thing being judged. The marker keeps its measured
    # x, and the caption says the bar is offset.
    #
    # The offset is absolute, so it is 2.6% of the crowded arms' abscissae and 62% of the
    # leftmost one's. Round 45 rendered the printed page and found the 400 msg/s bar pushed
    # onto the left spine, nearer the origin than its own marker: the arms that need the
    # dodge are the ones where it is proportionally invisible, and the arms where it is
    # proportionally huge are the two with nothing beside them to crowd. So it is mirrored
    # for any arm within one dodge of the axis, which puts the bar in white space on the
    # other side without changing its length, its height, or what it means.
    dodge = DODGE_FRACTION * lim
    for x, (blo, bhi), k in zip(xs, bands, klass):
        if blo is None or bhi is None:
            continue
        # No band where no test has power. The two coincident configurations sit above the
        # diagonal, and a null bar beside them reads as a test they failed; the caption has
        # to say "the sign carries nothing there" to undo it. Round 55: drawing the bar only
        # where a rejection is possible says the same thing without the correction.
        if k == "coincident":
            continue
        at = x + dodge if x < 2 * dodge else x - dodge
        ax.plot([at, at], [blo, bhi], color=GREY, lw=1.1, alpha=0.55,
                zorder=1, solid_capstyle="butt")
    # The annotation that used to point at the diagonal -- "a continuum would land on this
    # line" -- is gone, and the bars are why. The diagonal is the null's centre; the bars are
    # the null. Once both are drawn, a label naming the weaker of the two costs a legend row
    # it now collides with and tells the reader less than the thing beside it. The caption
    # names the diagonal instead.
    # "lattice", not "grid": the supplement keeps "grid" for the instants a timestamp changes
    # value and names the retentions 0, 1/q, ..., 1 a configuration can reach its q-lattice.
    ax.text(lim * 0.72, lim * 0.11, "closer to the lattice", fontsize=8,
            color=KEPT, ha="center", style="italic")

    # ls="none" on every entry. The arms are a scatter; nothing joins them. Only the filled
    # style showed a line in the legend, because color="none" on the open styles suppressed
    # their proxy lines too and hid the inconsistency.
    STYLE = {
        "grid":       dict(marker="o", ms=5.0, color=KEPT, mec=KEPT, mew=0.9, ls="none"),
        "unresolved": dict(marker="o", ms=5.0, color="none", mec=KEPT, mew=1.4, ls="none"),
        "coincident": dict(marker="s", ms=4.2, color="none", mec=GREY, mew=0.9, ls="none"),
    }
    for x, y, k in zip(xs, ys, klass):
        ax.plot(x, y, zorder=3, **STYLE[k])
    # A point at zero is drawn centred on the spine and clipped to half a marker, which
    # reads as a rendering fault rather than as data.
    ax.set_xlim(-lim * 0.02, lim)
    ax.set_ylim(-lim * 0.02, lim)
    ax.set_xlabel("distance expected from a continuum", fontsize=8)
    ax.set_ylabel("distance observed", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(alpha=0.25, lw=0.5)

    # Short labels: three entries at 8 pt in a 3.5-inch column leave no room for prose, and
    # the caption carries the full reading anyway.
    for key, text in (("grid", "rejects the null"),
                      ("unresolved", "unresolved"),
                      ("coincident", "no power")):
        n = klass.count(key)
        if n:
            ax.plot([], [], label="%s (%d)" % (text, n), **STYLE[key])
    if any(lo is not None for lo, _ in bands):
        ax.plot([], [], color=GREY, lw=1.1, alpha=0.55, label="the null's central 90%")
    ax.legend(fontsize=8, frameon=False, loc="upper left")


def grid_rows():
    """The grid arms, from the same helper the ledger and the table use."""
    out = []
    for c in stat_intervals.grid_cells():
        out.append({"rate_hz": c["rate_hz"], "q": c["q"], "powered": c["powered"],
                    "d_obs": c["d_observed"], "d_null": c["d_null"],
                    "d_null_lo": c["d_null_lo"], "d_null_hi": c["d_null_hi"],
                    "verdict": c["verdict"]})
    return out



# --- the priority ladder ------------------------------------------------------------------

def plot_priority_ladder(ax, rows):
    """Eight matched pairs against load: both arms, and the collapse between them.

    A forest plot rather than a factor-against-load scatter, because the factor alone hides
    which arm moved. Reading down the rows, the real-time arm barely moves while the normal-priority
    arm climbs with load, and the gap between them -- the factor -- widens from sevenfold to
    eightyfold. That is the pattern the range in the main text summarises.
    """
    import stat_intervals

    rows = sorted(rows, key=lambda r: (r["rho"], r["campaign"]))
    positions = list(range(len(rows)))[::-1]
    for pos, r in zip(positions, rows):
        # The forest of Fig. S8 plots these same pairs and gives ACCENT to the arm
        # the manipulation predicts will invert less, KEPT to the other. This panel
        # used to give KEPT to `real-time`, so one blue meant two opposite arms in
        # one document. DELETED never meant anything here -- it is the deleted-sample
        # red of Fig. S12 -- so the ladder takes the forest's key rather than the
        # reverse. Round 59's image review, reading the figures against each other.
        for rate, n, colour, marker in ((r["rate_base"], r["n_base"], KEPT, "o"),
                                        (r["rate_rt"], r["n_rt"], ACCENT, "s")):
            lo, hi = stat_intervals.wilson(int(round(rate * n)), n)
            ax.plot([lo, hi], [pos, pos], color=colour, lw=1.4, solid_capstyle="butt")
            ax.plot([rate], [pos], marker, ms=4.0, color=colour, mec="none")
        # A literal sign, not $\times$: mathtext sets \times as a binary operator and
        # pads it, so this column read "39 x" against Fig. S8's "39x" for the one
        # number. Round 59's image review, comparing the figures with each other.
        ax.text(1.35, pos, "%.0f×" % r["factor"], transform=ax.get_yaxis_transform(),
                va="center", ha="right", fontsize=8, color=GREY)

    ax.set_yticks(positions)
    ax.set_yticklabels(["%s%%  %s" % (r["level"].lstrip("l"), r["campaign"]) for r in rows],
                       fontsize=8)
    ax.set_xscale("log")
    ax.set_xlabel("negative-span rate (Wilson 95% interval, log)", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(axis="x", alpha=0.25, lw=0.5)
    # Wide enough for the lowest Wilson bound in the set: the 60% real-time arm has five
    # events in 2,985 and its interval runs below 1e-3, where a tighter limit clips it.
    ax.set_xlim(4e-4, 0.60)
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.plot([], [], "o", color=KEPT, mec="none", ms=4.0, ls="none", label="normal")
    ax.plot([], [], "s", color=ACCENT, mec="none", ms=4.0, ls="none", label="real-time")
    # Upper right: the bottom row is the 95% arm, whose normal-priority interval runs to the right
    # edge, and a legend there sits on it.
    ax.legend(fontsize=8, frameon=False, loc="upper right")


MECH_INTERVALS = RESULTS / "model" / "manipulation_intervals.csv"


def priority_forest_rows(path=MECH_INTERVALS):
    """{broker: [pair, ...]} for the forest of the real-time factor, ordered by load and then
    campaign, each pair {"campaign", "level", "rho", "factor", "lo", "hi"} with the run-level
    95% interval of the committed intervals file; an unbounded upper end is math.inf."""
    import csv
    import math
    import priority_pairs
    rho = {(p["campaign"], p["level"]): p["rho"] for p in priority_pairs.usable()}
    out = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["result"] != "priority":
                continue
            out.setdefault(r["backend"], []).append({
                "campaign": r["campaign"], "level": r["level"],
                "rho": rho[(r["campaign"], r["level"])], "factor": float(r["factor"]),
                "lo": float(r["factor_lo"]),
                "hi": math.inf if r["factor_hi"] == "inf" else float(r["factor_hi"])})
    for pairs in out.values():
        pairs.sort(key=lambda p: (p["rho"], p["campaign"]))
    return out


#: The factor axis of the forest: wide enough for every bounded interval, with room at the
#: right edge for the arrows of the unbounded ones.
FOREST_XLIM = (1.0, 2000.0)


def plot_priority_forest(axes, rows):
    """Every matched pair's real-time factor with its run-level interval, one panel a broker.

    15 Oct 2026, both referees (A on the priority pairs' intervals, B on Table II): the range of
    point factors hides how wide each interval is and that five of Kafka's eight have no upper
    end. A forest shows each pair, and the dashed line marks the smallest lower bound, the floor
    every pair's interval clears. An interval with no upper end runs to the panel's edge as an
    arrow.
    """
    from matplotlib.ticker import FuncFormatter
    for ax, (key, name, colour) in zip(axes, BROKER_COLOURS):
        pairs = rows[key]
        ys = list(range(len(pairs)))[::-1]
        for y, p in zip(ys, pairs):
            hi = p["hi"] if p["hi"] != float("inf") else FOREST_XLIM[1]
            ax.plot([p["lo"], hi], [y, y], color=colour, lw=1.4, solid_capstyle="butt")
            if p["hi"] == float("inf"):
                ax.annotate("", xy=(FOREST_XLIM[1], y), xytext=(FOREST_XLIM[1] / 2.2, y),
                            arrowprops=dict(arrowstyle="->", color=colour, lw=1.2))
            ax.plot([p["factor"]], [y], "o", ms=4.5, color=colour, mec="none")
        floor = min(p["lo"] for p in pairs)
        ax.axvline(floor, color=GREY, lw=0.8, ls=(0, (3, 2)), zorder=0)
        # Above the top row, beside the line rather than across it; literal signs, as the
        # ladder figure prints its factors, since mathtext pads a \times. The bound is rounded
        # down, as the ledger rounds it, so the label never claims more than every pair shows.
        import emit_paper_numbers
        ax.text(floor * 1.12, len(pairs) + 0.05,
                "every pair ≥ %s×" % emit_paper_numbers.floor_to_tenth(floor),
                fontsize=8, color=GREY, ha="left", va="center")
        ax.set_xscale("log")
        ax.set_xlim(*FOREST_XLIM)
        ax.set_ylim(-0.7, len(pairs) + 0.9)
        ax.set_yticks(ys)
        ax.set_yticklabels(["%s%%  %s" % (p["level"].lstrip("l"), p["campaign"]) for p in pairs],
                           fontsize=8)
        # "log" in the label and the factors written out, "1k" for 10^3: as 10^n the exponents
        # printed at 5.8 pt (15 Oct 2026, an internal review of the printed figures).
        ax.set_xlabel("normal-priority rate over real-time rate (log)", fontsize=8)
        ax.xaxis.set_major_formatter(FuncFormatter(figure_style.plain_log_label))
        ax.set_title(name, fontsize=8, loc="left")
        ax.tick_params(labelsize=8)
        ax.grid(axis="x", alpha=0.25, lw=0.5)
    # Written out, so the typography gate can read each panel's opening word; BROKER_COLOURS
    # holds Kafka first and Redis second.
    axes[0].set_title("(a) Kafka", fontsize=8, loc="left")
    axes[1].set_title("(b) Redis", fontsize=8, loc="left")
    axes[1].tick_params(labelleft=False)


#: The supplement's one-column text block, which a figure it includes at \columnwidth fills;
#: the legibility gate holds a figure no document includes yet to it (15 Oct 2026).
SUPPLEMENT_WIDTH_IN = figure_legibility.ONECOLUMN_WIDTH_IN

SO_FIX_RUNS = RESULTS / "so_fix" / "f2_runs.csv"

#: The three setups the fix's figure draws, in reading order: what load does to each latency at
#: normal priority, and what real-time priority does under that load.
FIX_SETUPS = (("idle", 0, False), ("load", 88, False), ("load,\nreal-time", 88, True))

#: What each latency is in the fix's figure: timed by the clients' threads, as benchmarks time
#: it, or between the kernel's timestamps read on the clients' own sockets (freeze 40).
FIX_SERIES = (("D_p99", "end-to-end latency $D$", DELETED),
              ("Wso_p99", "kernel-timed latency $W$", KEPT))


def fix_benefit_rows(path=SO_FIX_RUNS):
    """{broker: [(setup label, D's 99th percentile, the kernel-timed latency's), ...]} in
    milliseconds, one entry per FIX_SETUPS, each a setup's median over its runs of each run's
    99th percentile, as Supplement S3.10's table gives them (scripts/full_fix.setup_value)."""
    import csv
    import full_fix
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {b: [(label,) + tuple(full_fix.setup_value(rows, b, load, rt, field) / 1000.0
                                 for field, _, _ in FIX_SERIES)
                for label, load, rt in FIX_SETUPS]
            for b in full_fix.BACKENDS}


def plot_fix_benefit(axes, rows):
    """What the fix buys, one panel a broker (17 Oct 2026, the author's twelfth point: show with
    a graph how things improve). Under load at normal priority the tail of D, timed by the
    clients' threads as a benchmark times it, grows several-fold and real-time priority takes it
    back; timed between the kernel's timestamps the same messages' tail holds level throughout.
    Bars, side by side per setup, on one linear scale shared by both panels."""
    width = 0.38
    top = max(v for setups in rows.values() for s in setups for v in s[1:])
    for ax, (key, name, _) in zip(axes, BROKER_COLOURS):
        setups = rows[key]
        xs = np.arange(len(setups))
        for i, (_, label, colour) in enumerate(FIX_SERIES):
            ax.bar(xs + (i - 0.5) * width, [s[1 + i] for s in setups], width, color=colour,
                   label=label, edgecolor="none")
        ax.set_xticks(xs)
        ax.set_xticklabels([s[0] for s in setups], fontsize=8)
        # Headroom for the legend, and for the 2.4 pt taller text boxes CI's matplotlib sets.
        ax.set_ylim(0, top * 1.2)
        ax.tick_params(labelsize=8)
        ax.grid(axis="y", alpha=0.25, lw=0.5)
        ax.set_axisbelow(True)
    # Written out, so the typography gate can read each panel's opening word; BROKER_COLOURS
    # holds Kafka first and Redis second.
    axes[0].set_title("(a) Kafka", fontsize=8, loc="left")
    axes[1].set_title("(b) Redis", fontsize=8, loc="left")
    # On two lines: on one it overran the 1.9 in canvas.
    axes[0].set_ylabel("99th percentile\n(ms)", fontsize=8)
    axes[1].tick_params(labelleft=False)
    # One legend, in the upper half of (b), which Redis's bars leave empty; in (a) it sat on
    # Kafka's tall bar under load.
    axes[1].legend(fontsize=8, frameon=False, loc="upper right", handlelength=1.0,
                   handletextpad=0.4, borderaxespad=0.2)


#: The paper's column, which the fix's figure fills when Section VI includes it.
FIX_BENEFIT_IN = (figure_legibility.COLUMN_WIDTH_IN, 1.9)


def build_fix_benefit(out_dir):
    """Section VI's figure of what the kernel-timed fix buys, drawn at the column width the paper
    prints it at, from freeze 40's committed run table."""
    figure_style.apply()   # in force when the artists are made, not merely at import
    width = figure_legibility.print_widths().get("fix_benefit", FIX_BENEFIT_IN[0])
    fig, axes = plt.subplots(1, 2, figsize=(width, FIX_BENEFIT_IN[1]), sharey=True)
    plot_fix_benefit(axes, fix_benefit_rows())
    # A sliver kept on the left: tight_layout counted the two-line axis label short by 5 px.
    fig.tight_layout(w_pad=0.6, pad=0.3, rect=(0.025, 0, 1, 1))
    return _save(fig, out_dir, "fix_benefit", intended_in=FIX_BENEFIT_IN[0], whole=True)


def build_priority_forest(out_dir):
    """Supplement S3.1's forest of the eight matched pairs on both brokers (15 Oct 2026).

    Drawn at the width the supplement prints it at, a fraction of its one-column width (the
    whole text block when no document includes it yet), so that its 8 pt type prints at 8 pt:
    drawn at the whole block and included at 0.9 of it, it printed at 7.2 pt (15 Oct 2026).
    """
    figure_style.apply()   # in force when the artists are made, not merely at import
    width = figure_legibility.print_widths().get("priority_forest", SUPPLEMENT_WIDTH_IN)
    # Saved whole at that width, 2.29 in tall: the page prints it as drawn, no taller than the
    # cropped and enlarged 2.5 in canvas printed before (165.5 pt).
    fig, axes = plt.subplots(1, 2, figsize=(width, 2.29), sharey=True)
    plot_priority_forest(axes, priority_forest_rows())
    fig.tight_layout(w_pad=1.2, pad=0.3)
    return _save(fig, out_dir, "priority_forest", intended_in=SUPPLEMENT_WIDTH_IN, whole=True)


def build_priority_ladder(out_dir):
    figure_style.apply()   # in force when the artists are made, not merely at import
    import priority_pairs
    fig, ax = plt.subplots(figsize=(6.50, 3.10))
    plot_priority_ladder(ax, priority_pairs.usable())
    fig.tight_layout()
    return _save(fig, out_dir, "priority_ladder")


# --- driver -----------------------------------------------------------------------------

def _save(fig, out_dir, stem, intended_in=None, whole=False):
    """Gate a figure and write it. `intended_in` is the width a figure no document includes
    yet will print at (15 Oct 2026): the legibility gate measures a figure only at the width a
    document gives it, so a new figure would otherwise pass unmeasured until the text took it
    up, which is how a 7 pt legend once reached the paper.

    `whole` writes the canvas uncropped, for a figure drawn at exactly the width the page
    prints it at: the file is that width, so the page neither enlarges nor shrinks it, and
    the collision gate checks that no label is cut by the canvas edge (15 Oct 2026)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ("%s.pdf" % stem)
    figure_collisions.check(fig, stem, whole_canvas=whole)
    widths = figure_legibility.print_widths()
    if intended_in is not None and stem not in widths:
        widths[stem] = intended_in
    figure_legibility.check(fig, stem, widths)
    figure_vocabulary.check(fig, stem)
    if whole:
        figure_style.save_whole(fig, path)
    else:
        fig.savefig(path, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    return path


def build_deletion_phases(out_dir):
    """The deletion figure: why a sample is deleted, beside what it did.

    An outside editor's reading (28 Sep) found the paper's deletion scatter unable to show the
    mechanism and the supplement's four-phase drawing unable to show the consequence, and asked
    for the two side by side: (a) one delivery at four phases of one tick, three of them
    deleted; (b) every captured setting's retention against the median it printed. Panel (b)
    is the old single-panel scatter, whose own builder was retired with it: a figure built and
    included nowhere is the dangling case the manuscript gates fail on.

    The paper carried it from v5 until 5 Oct 2026, when it moved to the journal supplement
    (S4.1), whose one-column text block is 6.5 in. Drawn at the paper's 7.16 in it printed its
    8 pt labels there at 7.3 pt, under the legibility floor. 6 Oct 2026: back in the paper, as
    Section V-C's figure across both columns, so it is drawn at the paper's 7.16 in again and
    printed in no other document.
    """
    import make_paper_figures
    figure_style.apply()
    # The margins are explicit because the panels have to use the whole width: at the
    # default ones the two panel titles ran together with under 2 pt between them. The bottom
    # margin keeps panel (b)'s x label on the canvas, where the collision gate can read it;
    # at 7.16 in by 2.10 in it hung below the edge and was never checked. No tight_layout:
    # a gridspec with its own spacing is one it leaves alone, with a warning, so the call
    # changed nothing.
    # 15 Oct 2026: saved whole at exactly the text width. Cropped to its ink the file was 6.975
    # in, and the page enlarged it 2.75%, which printed it 4.1 pt taller in both columns.
    fig = plt.figure(figsize=DELETION_PHASES_IN)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.15], wspace=0.22,
                          left=0.004, right=0.992, bottom=0.215, top=0.91)
    left = fig.add_subplot(gs[0, 0])
    right = fig.add_subplot(gs[0, 1])
    make_paper_figures.plot_phases(left)
    plot_deletion(right, retention_points(), marked=incommensurate_points())
    right.set_title("(b) What the benchmark printed, and what it kept", fontsize=8, loc="left")
    return _save(fig, out_dir, "deletion_phases", whole=True)


#: Fig. 4's canvas: the paper's text width exactly, and saved whole (15 Oct 2026).
DELETION_PHASES_IN = (figure_legibility.TEXT_WIDTH_IN, 2.04)


# --- the exposure curve -------------------------------------------------------------------

def plot_exposure(ax, lags):
    """Relative error of the acknowledgment-referenced proxy against the delivery measured.

    The supplement already carries this as a table of nine rows, and round 54 asked for the
    picture, on the grounds that this is the one quantity a reader will want to locate their
    own path on. A table answers "what is the error at 10 ms"; the curve answers "where does
    my path sit", which is the question a practitioner actually has.

    Both the curve and the table read `_exposure_lags()` in `emit_paper_numbers`, so the
    figure cannot drift from the table beside it -- the failure this project gates against
    everywhere else, and the reason the arithmetic is not repeated here.

    The band is the tenth to ninetieth percentile of the measured publish latency across
    conditions. Drawing only the median would repeat, one level up, the mistake Section VI-E
    reports: a central summary offered as guidance for a distribution that is not central.
    """
    typical, _hi, _lo, p10, p90 = lags
    t_ms = np.logspace(np.log10(0.1), np.log10(200.0), 400)

    def err(lag_us):
        return 100.0 * lag_us / (t_ms * 1000.0)

    # An en dash, not two hyphens. "p10--p90" is the LaTeX idiom, and matplotlib is not
    # LaTeX: it printed the two characters, in the legend of a supplement figure, for every
    # round since the curve was drawn.
    ax.fill_between(t_ms, err(p10), err(p90), color=DELETED, alpha=0.16, linewidth=0,
                    label="p10\u2013p90 across conditions")
    ax.plot(t_ms, err(typical), color=DELETED, lw=1.4, label="median publish latency")

    # 100% is the line the paper's headline turns on: below it the correction is smaller
    # than the quantity corrected, above it the correction is larger.
    # The label sits on the right, where the curve has already fallen away: the first draft
    # put it over the crossover and the collision gate refused the figure.
    ax.axhline(100, color=GREY, lw=0.8, ls="--", zorder=1)
    # The crossover is a range, and this is the one panel that may not quote it by its middle.
    # The band crosses the 100% line wherever the lag equals the delivery, so its own p10 and
    # p90 bracket the crossing: lag/1000 ms at each end. Round 57 found the caption naming
    # only the median crossing in a figure whose stated purpose is that "a reader can bracket
    # their own path rather than take the middle" -- the criticism round 51 made of this same
    # curve and round 55 made of the recovery remedy, surviving in the caption.
    # Median to p90, which is the interval the main text and this caption both quote. Drawing
    # the band's full p10-p90 crossing instead would put a fourth number in the reader's way
    # and would not be the range either sentence names.
    crossover, hi_cross = typical / 1000.0, p90 / 1000.0
    ax.plot([crossover, hi_cross], [100, 100], color=DELETED, lw=3.0, alpha=0.30,
            solid_capstyle="butt", zorder=3)
    ax.plot([crossover], [100], marker="o", ms=4.5, color=DELETED, zorder=4)
    # The manuscript's names (3 Oct, A10): A is the publish latency and D the end-to-end latency, and
    # bare "delivery" is never a duration. "displacement = delivery" used both retired names.
    ax.text(150, 125, "publish latency = end-to-end latency", fontsize=8, color=GREY,
            ha="right", va="bottom")

    # Where published broker medians sit, which is the whole reason the curve matters.
    ax.axvspan(0.1, 1.0, color=GREY, alpha=0.10, zorder=0)
    ax.text(0.135, 2.2, "sub-millisecond\nbroker medians", fontsize=8, color=GREY,
            ha="left", va="bottom", linespacing=1.15)

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("end-to-end latency measured (ms)", fontsize=8)
    ax.set_ylabel("relative error of the proxy (%)", fontsize=8)
    ax.set_xlim(0.1, 200)
    ax.set_ylim(0.2, 4000)
    ax.tick_params(labelsize=8)
    ax.grid(alpha=0.25, lw=0.5)
    ax.legend(fontsize=8, frameon=False, loc="upper right", handletextpad=0.5)


def build_exposure(out_dir):
    figure_style.apply()   # in force when the artists are made, not merely at import
    import emit_paper_numbers
    lags = emit_paper_numbers._exposure_lags()
    if lags is None:                      # pragma: no cover - the corpus ships with the repo
        raise SystemExit("span_symmetry.csv is missing; the exposure curve has no source")
    # Drawn at the supplement's one-column width, like `priority_ladder` and the other
    # figures that live there: a figure is drawn at the width it prints at, never scaled on
    # inclusion, because scaling shrinks its type by the same factor.
    fig, ax = plt.subplots(figsize=(6.50, 2.60))
    plot_exposure(ax, lags)
    fig.tight_layout()
    return _save(fig, out_dir, "exposure_curve")


# --- what the remedies buy (Fig. 4 since 4 Oct 2026) -------------------------------------

SPAN_CSV = RESULTS / "span_symmetry.csv"


def repair_rows(path=SPAN_CSV):
    """Per group: (median D in ms, the proxy's error and the repaired error, in % of D, broker).

    The proxy is the latency timed from the acknowledgment, S; the repair adds the publish
    latency back, S + A, as Section VI-B does. Both errors are against the condition's own
    median D, which is how `stat_intervals.recovery_populations` and the ledger count them.
    15 Oct 2026: the repair is the median of S plus the median of A, at native resolution, as
    the CSV now holds it; and each row names its broker, which the figure marks.
    """
    import csv
    out = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            d = float(r["median_D_us"])
            if not d:
                continue
            out.append((d / 1000.0, 100.0 * (d - float(r["median_S_us"])) / d,
                        100.0 * abs(float(r["recovery_err_us"])) / d,
                        r["condition"].split("_")[0]))
    if not out:
        raise ValueError("no conditions in %s" % path)
    return sorted(out)


#: The brokers as the paper's Fig. 3 colours them, for the figures that mark them (15 Oct 2026).
BROKER_COLOURS = (("kafka", "Kafka", "#1f77b4"), ("redis", "Redis", "#d62728"))
#: The model curve's ink, neutral so that no broker's colour reads as the curve's.
CURVE = "#4d4d4d"


def padding_points(path=None):
    """[(campaign, broker, [(median D in ms, 100 A/D)])], one trajectory per campaign and broker,
    from the padding campaign's committed medians (manipulation_runs.padding_spans)."""
    import manipulation_runs
    rows = manipulation_runs.read_padding(path or manipulation_runs.PADDING_CSV)
    out = {}
    for r in rows:
        out.setdefault((r["campaign"], r["backend"]), []).append(
            (int(r["pad_bytes"]), r["median_d_ms"], 100.0 * r["median_a_ms"] / r["median_d_ms"]))
    return [(c, b, [(d, e) for _p, d, e in sorted(pts)]) for (c, b), pts in sorted(out.items())]


def plot_repair(ax, rows, lags, padding=None):
    """Panel (a) of Fig. 4: the proxy's error on every condition, and the error once repaired.

    4 Oct 2026, the author: "show how things could be improved". The curve says how large the
    proxy's error is for a path of a given length; the points are the measured conditions,
    timed from the acknowledgment and then with the publish latency added back, on the same
    axes. The curve and its band are the ones `plot_exposure` draws, from `_exposure_lags()`.
    """
    typical, _hi, _lo, p10, p90 = lags
    t_ms = np.logspace(np.log10(0.1), np.log10(200.0), 400)
    # 15 Oct 2026: the curve and its band in neutral ink, since colour now marks the broker.
    ax.fill_between(t_ms, 100.0 * p10 / (t_ms * 1000.0), 100.0 * p90 / (t_ms * 1000.0),
                    color=CURVE, alpha=0.18, linewidth=0)
    # 6 Oct 2026: the curve is one path at the median publish latency; across conditions the
    # publish latency grows with the end-to-end latency, so the crosses sit above it, and the
    # label says which it is.
    ax.plot(t_ms, 100.0 * typical / (t_ms * 1000.0), color=CURVE, lw=1.2,
            label="$A/D$ at a fixed $A$")
    ax.axhline(100, color=GREY, lw=0.8, ls="--", zorder=1)
    # Lighter than the band since 15 Oct 2026, when the band turned grey with the curve.
    ax.axvspan(0.1, 1.0, color=GREY, alpha=0.06, zorder=0)
    ax.text(0.12, 60, "below 1 ms", fontsize=8, color=GREY, ha="left", va="center")
    # 15 Oct 2026, referee B (Fig. 6): pooled, the dots said the repair works everywhere.
    # Kafka's groups sit near 2--3 ms and repair to within about a per cent; Redis's sit near
    # 1 ms and repair to within a few tens. Each broker in the colour Fig. 3 gives it, the
    # marker saying what was timed.
    for key, _name, colour in BROKER_COLOURS:
        mine = [r for r in rows if r[3] == key]
        xs = [r[0] for r in mine]
        ax.scatter(xs, [r[1] for r in mine], s=11, marker="x", color=colour, linewidths=0.8,
                   zorder=3)
        ax.scatter(xs, [r[2] for r in mine], s=10, color=colour, edgecolors="none", zorder=3)
    # 15 Oct 2026, referee A (m25): the padding campaign, E-A10 and its repeat, A/D at each
    # padding level, joined in order of padding. Load is held there, and the referee expected
    # the publish latency to hold too; on Kafka it grows with the payload almost as fast as
    # the end-to-end latency, so its points stay high where the curve falls.
    for _campaign, key, pts in padding or ():
        colour = dict((k, c) for k, _n, c in BROKER_COLOURS)[key]
        ax.plot([d for d, _e in pts], [e for _d, e in pts], color=colour, lw=0.6, alpha=0.6,
                zorder=2)
        ax.scatter([d for d, _e in pts], [e for _d, e in pts], s=13, marker="D",
                   facecolors="white", edgecolors=colour, linewidths=0.8, zorder=4)
    ax.set_xscale("log")
    ax.set_xlim(0.1, 300)
    ax.set_ylim(-4, 125)
    ax.set_xlabel("end-to-end latency (ms)", fontsize=8)
    ax.set_ylabel("error (% of the end-to-end latency)", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(alpha=0.25, lw=0.5)
    # Above the axes, where neither the band nor the points can run into it. What a marker
    # means in neutral ink, and which broker a colour is.
    handles = [plt.Line2D([], [], color=CURVE, lw=1.2),
               plt.Line2D([], [], marker="x", ls="none", color=GREY, markersize=4,
                          markeredgewidth=0.9),
               plt.Line2D([], [], marker="o", ls="none", color=GREY, markersize=3.5),
               plt.Line2D([], [], marker="D", ls="none", markerfacecolor="white",
                          markeredgecolor=GREY, markersize=3.5),
               plt.Rectangle((0, 0), 1, 1, color=BROKER_COLOURS[0][2]),
               plt.Rectangle((0, 0), 1, 1, color=BROKER_COLOURS[1][2])]
    labels = ["$A/D$ at a fixed $A$", "timed from the acknowledgment", "with $A$ added back",
              "padding, $A/D$", BROKER_COLOURS[0][1], BROKER_COLOURS[1][1]]
    ax.legend(handles, labels, fontsize=8, frameon=False, loc="lower center",
              bbox_to_anchor=(0.5, 1.0), ncol=2, handletextpad=0.5, columnspacing=1.2,
              borderaxespad=0.5, handlelength=1.4)


def plot_priority_pairs(ax, rows):
    """Panel (b) of Fig. 4: every matched pair, at normal and at real-time priority.

    The supplement's ladder reads one pair per row with its campaign; this panel is for the
    reader who wants the effect at a glance: each pair is a vertical drop at its own load, red
    at normal priority, blue at real-time priority. Pairs measured at the same load are set a
    little apart so that none hides another.
    """
    from matplotlib.ticker import FuncFormatter
    groups = {}
    for r in sorted(rows, key=lambda r: (r["rho"], r["campaign"])):
        groups.setdefault(round(r["rho"], 2), []).append(r)
    for level, members in groups.items():
        for i, r in enumerate(members):
            x = 100.0 * level + (i - (len(members) - 1) / 2.0) * 1.6
            ax.plot([x, x], [r["rate_rt"], r["rate_base"]], color=GREY, lw=0.8, zorder=1)
            ax.plot([x], [r["rate_base"]], "o", ms=4.5, color=DELETED, mec="none", zorder=3)
            ax.plot([x], [r["rate_rt"]], "s", ms=4.0, color=KEPT, mec="none", zorder=3)
    ax.set_yscale("log")
    ax.set_ylim(8e-4, 0.9)
    ax.set_xlim(55, 100)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _pos: "%g" % v))
    ax.text(57, 0.42, "normal priority", fontsize=8, color=DELETED, ha="left", va="center")
    ax.text(99, 0.00105, "real-time priority", fontsize=8, color=KEPT, ha="right",
            va="center")
    ax.set_xlabel("host utilization (%)", fontsize=8)
    ax.set_ylabel("negative-span rate", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(alpha=0.25, lw=0.5)


def build_remedies(out_dir):
    """Fig. 4 since 4 Oct 2026: what the paper's remedies buy, measured.

    The author asked for graphs that show the formulas' benefits and how things improve. (a)
    is the identity S = D - A at work: every condition's error timed from the acknowledgment,
    on the exposure curve it follows, and the error once the publish latency is added back.
    (b) is the occupancy law at work: real-time priority lowers the occupancy and the rate
    falls, in every
    matched pair. The column-width exposure curve that was the paper's Fig. 5 is panel (a)'s
    curve, and its own builder went with it.
    """
    # 6 Oct 2026: panel (b), the priority pairs, left for the paper's mechanism table, which
    # gives both brokers with intervals that resample whole runs. The figure is the repair panel
    # alone, at column width; plot_priority_pairs stays for the postmortem's figure.
    figure_style.apply()
    import emit_paper_numbers
    lags = emit_paper_numbers._exposure_lags()
    if lags is None:                      # pragma: no cover - the corpus ships with the repo
        raise SystemExit("span_symmetry.csv is missing; the repair panel has no source")
    fig, a = plt.subplots(figsize=(3.5, 2.5))
    plot_repair(a, repair_rows(), lags, padding_points())
    fig.tight_layout()
    return _save(fig, out_dir, "remedies")


def build_spectrum(out_dir, slice_ms=None):
    figure_style.apply()   # in force when the artists are made, not merely at import
    if slice_ms is None:
        try:
            import kernel_constants
            slice_ms = kernel_constants.constants()["base_slice_ms"]
        except (ImportError, OSError, KeyError, ValueError):
            slice_ms = None
    bins, _ = stall_histogram()
    fig, ax = plt.subplots(figsize=(3.50, 2.10))
    plot_spectrum(ax, bins, slice_ms)
    fig.tight_layout()
    return _save(fig, out_dir, "stall_spectrum")


def build_grid(out_dir):
    figure_style.apply()   # in force when the artists are made, not merely at import
    fig, ax = plt.subplots(figsize=(3.50, 2.45))
    plot_grid(ax, grid_rows())
    fig.tight_layout()
    return _save(fig, out_dir, "grid_membership")


# --- the mechanism, by manipulation --------------------------------------------------------

def mechanism_arms():
    """The four matched pairs behind Table~III, each as (label, arm, k, n).

    Priority and geometry come from the same helpers the ledger uses, so the figure and the
    table cannot disagree: they are two renderings of one computation.
    """
    arms = []
    for level, kb, nb, kr, nr in stat_intervals.priority_cells():
        pretty = {"l75": "Priority, 75%", "l88": "Priority, 88%"}.get(level, level)
        arms.append((pretty, "normal", kb, nb))
        arms.append((pretty, "real-time", kr, nr))
    for phase, pretty in (("ea6", "Geometry, original"), ("ea6b", "Geometry, replication")):
        try:
            cells = stat_intervals.geometry_cells(phase)
        except (OSError, KeyError, ValueError):
            continue
        for cond, k, n in cells:
            arms.append((pretty, "concentrated" if "conc" in cond else "spread", k, n))
    return arms


def backend_arms(path=None):
    """(label, "observed", negatives, events) for each broker, from the span recount.

    These are not manipulations and must not be drawn as though they were. They answer the
    other question a reader has about the mechanism -- whether it is a property of one
    client -- and they answer it by holding the clock, the host and the span fixed and
    changing the broker. Same artefact as Table~II, so figure and table cannot disagree.
    """
    import recount_spans
    path = path or (RESULTS / "span_recount.csv")
    if not Path(path).exists():
        return []
    pretty = {"kafka": "Kafka", "redis": "Redis"}
    out = []
    for backend, agg in recount_spans.by_backend(recount_spans.read_csv(str(path))).items():
        if not agg["events"]:
            continue
        out.append((pretty.get(backend, backend), "observed", agg["neg_ack"], agg["events"]))
    return out


def plot_mechanism(ax, arms, observed=()):
    """A forest of Wilson intervals: the manipulations, and whether they overlap.

    The table gives the numbers. What the table cannot show at a glance is that the two arms
    of every pair are disjoint, which is the whole causal claim: move occupancy at fixed
    utilization and the rate moves with it.

    Below a rule, and only if supplied, the same axis carries the two brokers. Their intervals
    are tight and mutually overlapping, so the one glance that shows every manipulated pair
    separating also shows the broker making no difference. They are drawn in the neutral grey
    reserved for "not a manipulated arm".
    """
    rows = list(arms) + list(observed)
    labels, y = [], []
    for i, (group, arm, k, n) in enumerate(rows):
        rate = k / n
        lo, hi = stat_intervals.wilson(k, n)
        pos = len(rows) - i
        if arm == "observed":
            colour = GREY
        else:
            colour = ACCENT if arm in ("real-time", "concentrated") else KEPT
        ax.plot([lo, hi], [pos, pos], color=colour, lw=1.6, solid_capstyle="butt")
        ax.plot([rate], [pos], "o", ms=4.2, color=colour, mec="none")
        labels.append("%s, %s" % (group, arm))
        y.append(pos)

    # The factor, once per manipulated pair, at the right margin. The forest shows that the
    # two arms of every pair separate; the factor is what a reader carries away, and until now
    # it lived only in Table II. Rendered as max/min so it reads the same way for a
    # manipulation that lowers the rate and one that raises it.
    factors = []
    for i in range(0, len(arms) - 1, 2):
        r1 = arms[i][2] / arms[i][3]
        r2 = arms[i + 1][2] / arms[i + 1][3]
        if min(r1, r2) > 0:
            top = len(rows) - i
            factors.append(((top + (top - 1)) / 2.0, max(r1, r2) / min(r1, r2)))

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("negative-span rate (Wilson 95% interval)", fontsize=8)
    ax.tick_params(axis="x", labelsize=8)
    ax.grid(axis="x", alpha=0.25, lw=0.5)
    _hi = max(stat_intervals.wilson(k, n)[1] for _, _, k, n in rows) * 1.10
    # The real-time arms sit at essentially zero, where the frame would cut the marker. The
    # right margin carries the factor column, so the axis is widened to make room for it
    # rather than printing it over the intervals.
    _right = _hi * 1.26
    ax.set_xlim(-_hi * 0.015, _right)
    for pos, factor in factors:
        # On a white patch: the x-grid runs the full height of the axis, so without one the
        # gridline is drawn straight through the digits and the collision gate says so.
        # A hair inside the limit. Anchored on it, the patch below extends a point or so
        # past the spine and paints it out, and the frame prints with gaps beside each
        # factor; `label_patches_over_spines` measures that now.
        ax.text(_right * 0.994, pos,
                "%.0f×" % factor if factor >= 10 else "%.2f×" % factor,
                fontsize=8, color=GREY, ha="right", va="center",
                bbox=dict(facecolor="white", edgecolor="none", pad=0.8))
    for i in range(0, len(arms), 2):
        ax.axhspan(len(rows) - i - 1.5, len(rows) - i + 0.5, color=GREY, alpha=0.05, zorder=0)
    if observed:
        # The rule is the point: everything above it was moved on purpose, everything below
        # it was only observed. Without it the brokers read as a fifth matched pair.
        ax.axhline(len(observed) + 0.5, color=GREY, lw=0.7, ls=(0, (4, 2)), zorder=1)
        # Left of the factor column, which now occupies the right margin.
        _label_x = _hi * 1.02
        ax.text(_label_x, len(observed) + 0.62, "manipulated", fontsize=8,
                color=GREY, ha="right", va="bottom")
        ax.text(_label_x, len(observed) + 0.38, "observed", fontsize=8,
                color=GREY, ha="right", va="top")
    ax.set_ylim(0.4, len(rows) + 0.6)


# --- the interval being measured decides the rate -------------------------------------------

TTRUE_CSV = RESULTS / "model" / "ttrue_sweep.csv"


def ttrue_points(path=TTRUE_CSV):
    """(transport ms, negative-span rate, ci_lo, ci_hi) over the payload sweep."""
    import csv
    pts = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            pts.append((float(r["transport_ms"]), float(r["inversion"]),
                        float(r["ci_lo"]), float(r["ci_hi"])))
    if not pts:
        raise ValueError("no rows in %s" % path)
    return sorted(pts)


def plot_ttrue(ax, pts):
    """Negative-span rate against the interval being measured, over the payload sweep.

    This is the negative-span probability as a function of T_true, run as an
    experiment: the same stall distribution overlaps a short
    interval almost entirely and a long one hardly at all, so lengthening the true transport
    *lowers* the rate. It is the manipulation that rules out load as the sole explanation,
    and it had no figure.
    """
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    lo = [p[1] - p[2] for p in pts]
    hi = [p[3] - p[1] for p in pts]
    ax.errorbar(xs, ys, yerr=[lo, hi], fmt="o", ms=4.5, color=KEPT,
                ecolor=KEPT, elinewidth=1.1, capsize=2.2)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("true transport (ms)", fontsize=8)
    ax.set_ylabel("negative-span rate", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(alpha=0.25, lw=0.5)

    slope, _, _r2, lo_slope, hi_slope = stat_intervals.payload_fit()
    # The ratio drawn here is the span in *transport*, not in payload: payload starts at zero
    # bytes and so has no ratio. The manuscript states it the same way.
    # The interval rather than R-squared: on four points R-squared is the flattering
    # statistic and the interval on the exponent is the one that says what was learned.
    # One word and one sign for one quantity. Section V-D called this "an effective exponent
    # of 0.339" while this annotation drew "slope -0.34" from the same fit, on the facing
    # page. Both now say slope and both carry the sign, and the ledger emits it so they
    # cannot drift apart again.
    #
    # And the span beside it, finally. This line read `round(xs[-1] / xs[0])` for eight
    # rounds after the slope was fixed --- a sixth reading of a CSV that seventeen sentences
    # across the two documents were also reading by hand. It comes from `payload_span()` now,
    # which is the function the emitter uses, so the figure and `\payloadTransportFactorRound`
    # cannot disagree. `tests/unit/test_figure_ledger_agreement.py` asserts they do not.
    span = stat_intervals.payload_span()
    ax.annotate("slope %.2f (%.2f to %.2f)\nover a %d× span in transport"
                % (slope, lo_slope, hi_slope, round(span["transport_factor"])),
                # Left of where it was: adding the interval lengthened the first line enough
                # to put the second line's last glyph on the right spine.
                #
                # No arrow. It used to point at the second payload level, and at print size
                # the text box sat close enough to that marker that the tail vanished and
                # only the head was drawn -- an arrowhead resting on a data point, which
                # reads as a label for that point. The annotation is about the slope through
                # all four, so it should point at none of them. Neither gate can see this:
                # an arrowhead is ink, not text, and it was not covering any.
                xy=(0.24, 0.82), xycoords="axes fraction",
                fontsize=8, color=GREY)
    ax.set_xlim(xs[0] * 0.55, xs[-1] * 1.9)


def build_mechanism(out_dir):
    figure_style.apply()   # in force when the artists are made, not merely at import
    # Full width, and not for grandeur. Ten rows of categorical labels take about an inch
    # and a half whatever the panel is, so in a 3.50 in column the intervals were drawn in
    # the 1.7 in left over and a co-author could not read them on a 37-inch monitor. The
    # legibility gate passed it: the type is 8 pt either way. Width is the fix, and the
    # height follows the row count at 17.6 pt of pitch for 8 pt type, which is what the
    # column version already had -- height was never the complaint, the data panel was.
    # 6.50 in, not 7.16: round 57 moved this figure to the supplement, whose column is
    # narrower than the main text's. A figure authored wide is scaled DOWN on inclusion,
    # and that is the direction that pushes 8 pt type under the legibility floor.
    fig, ax = plt.subplots(figsize=(6.50, 2.22))
    plot_mechanism(ax, mechanism_arms(), backend_arms())
    fig.tight_layout()
    return _save(fig, out_dir, "mechanism_forest")


def build_ttrue(out_dir):
    figure_style.apply()   # in force when the artists are made, not merely at import
    fig, ax = plt.subplots(figsize=(3.50, 2.05))
    plot_ttrue(ax, ttrue_points())
    fig.tight_layout()
    return _save(fig, out_dir, "ttrue_law")



# --- the payload flip ------------------------------------------------------------------------

# The arms of the pre-registered payload manipulation, and where each one's replicates live.
# 200 B is the baseline at the same rate: two campaigns ran it, and both belong to the arm --
# dropping either would narrow the spread by selection rather than by measurement.
#: 15 Oct 2026, two internal reviews: the arms were grey, red and blue, the red and blue the
#: paper and the supplement give the two brokers, and every arm ran on one broker. They are told
#: apart now by a grey that darkens with the payload and by marker shape, which no other
#: figure gives a meaning, and their names stand beside them in both panels.
PAYLOAD_ARMS = (
    ("200 B", (("rate_q", 300), ("ultimate", 300)), "#8c8c8c"),
    ("32 KB", (("ultimate_pay300", 32768),), "#4d4d4d"),
    ("64 KB", (("ultimate_pay300", 65536),), "#111111"),
)
PAYLOAD_MARKERS = {"200 B": "o", "32 KB": "s", "64 KB": "^"}
PAYLOAD_Q = 3  # 300 msg/s against a 1 ms tick is 10/3 in lowest terms


def payload_arms(path=None):
    """Retention percentages per payload arm, from the committed campaign ledger.

    Selection matches the audit everywhere else, and it lives in `stat_intervals` now: both
    documents quote this arm's spread and its pin in prose, and round 60 found all four of
    those numbers typed by hand. The figure keeps the colours, which are a drawing decision;
    the numbers come from the one function that reads the ledger.
    """
    import stat_intervals
    colours = {label: colour for label, _keys, colour in PAYLOAD_ARMS}
    return [(label, vals, colours[label])
            for label, vals in stat_intervals.payload_flip_replicates(path)]


def payload_positions(arms=None, q=PAYLOAD_Q):
    """(label, frac(q*theta), spread, colour) per arm.

    theta is the arm's mean retention as a fraction, which by the retention identity estimates
    T_true/tau. frac(q*theta) is then the replicates' position inside their grid cell, and
    The spread rule says it should be near 100/q at mid-cell and near zero on a vertex.
    """
    arms = payload_arms() if arms is None else arms
    out = []
    for label, vals, colour in arms:
        theta = (sum(vals) / len(vals)) / 100.0
        # The replicates' own offsets above the arm minimum travel with the spread. The
        # spread is a range, so it is fixed by two replicates and says nothing about the
        # other n-2; a threshold crossing shown as a bare point invites the reader to treat
        # it as a summary of the arm when it is a summary of its two extremes. Carrying the
        # offsets lets the panel draw what the statistic is made of. A bootstrap would have
        # been the reflex and is the wrong instrument here: resampling can never exceed the
        # observed range, so every interval is one-sided by construction and the arms that
        # sit furthest above the boundary would be drawn as the least certain.
        base = min(vals)
        out.append((label, (q * theta) % 1.0, max(vals) - base, colour,
                    [v - base for v in vals]))
    return out


def swarm_offsets(vals, tol, step=0.055):
    """Horizontal offsets that separate near-equal values without implying an order.

    The first version of this panel laid each arm's replicates out at even spacing in the
    order they arrived, and they arrive sorted. Every arm therefore rendered as a staircase
    climbing left to right along an axis that carries no variable, and a reader could leave
    the figure believing retention rises with replicate number. Nothing in the caption
    claimed that; the picture did.

    A swarm says only what is true. Replicates far apart in retention sit on the arm's own
    centre line; replicates within `tol` of each other are spread symmetrically about it, so
    the offset encodes local crowding and nothing else, and the group's centre does not move.
    """
    out = [0.0] * len(vals)
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    group = []

    def flush(g):
        for rank, idx in enumerate(g):
            out[idx] = (rank - (len(g) - 1) / 2.0) * step

    for i in order:
        if group and abs(vals[i] - vals[group[0]]) <= tol:
            group.append(i)
            continue
        flush(group)
        group = [i]
    flush(group)
    return out


def plot_payload_grid(ax, arms, q=PAYLOAD_Q):
    """Panel (a): every replicate against the q-grid it is supposed to land on."""
    every = [v for _, vals, _ in arms for v in vals]
    # A marker is about this tall in data units at this panel's size, so values closer than
    # it would overprint and are the ones worth separating.
    tol = 0.04 * (max(every) - min(every)) if len(every) > 1 else 0.0
    for x, (label, vals, colour) in enumerate(arms):
        swarm = [x + d for d in swarm_offsets(vals, tol)]
        ax.scatter(swarm, vals, s=15, color=colour, edgecolors="none", zorder=3,
                   marker=PAYLOAD_MARKERS.get(label, "o"))
    # The label sits inside the axes, so the rule has to stop short of it: an axhline spans
    # the full width and printed each grid line straight through its own "k/q".
    left, label_x = -0.5, len(arms) - 0.55
    for k in range(1, q + 1):
        y = 100.0 * k / q
        ax.plot([left, label_x - 0.06], [y, y], color=GREY, lw=0.6, ls=":",
                zorder=0, alpha=0.7, clip_on=False)
        ax.annotate("%d/%d" % (k, q), xy=(label_x, y), fontsize=8,
                    color=GREY, va="center", ha="left")
    ax.set_xticks(range(len(arms)))
    ax.set_xticklabels([a[0] for a in arms], fontsize=8)
    ax.set_xlim(-0.5, len(arms) - 0.35)
    # Headroom above the full-retention line, which is where its own label sits: without it
    # the axes stop at 100 and the top frame runs through the capitals of "q/q". Retention
    # cannot exceed 100, so the space is empty by construction.
    ax.set_ylim(25, 108)
    ax.set_ylabel("retention (%)", fontsize=8)
    # "lattice", the supplement's word for the retentions 0, 1/q, ..., 1 a configuration can
    # reach, as its caption says; it keeps "grid" for the instants a timestamp changes value.
    ax.set_title("(a) Replicates against the $q=%d$ lattice" % q, fontsize=8)
    ax.tick_params(labelsize=8)


def plot_payload_flip(ax, pos, q=PAYLOAD_Q):
    """Panel (b): the spread against cell position, and the boundary it crosses twice."""
    half = 100.0 / (2 * q)
    ax.axhline(half, color=GREY, lw=0.8, ls="--", zorder=0)
    # Hard left. The label used to start at 0.30 and ran right, which was clear while the
    # arms were three bare markers and stopped being clear the moment each arm grew a stick:
    # the 200 B stick rises through the boundary at frac 0.40 and printed itself across the
    # last word.
    ax.annotate("half step width", xy=(0.0, half), xytext=(0, 3),
                textcoords="offset points", fontsize=8, color=GREY, va="bottom", ha="left")
    # 1.30, not 1.22: at 1.22 the label over the highest arm, 200 B, crossed the top spine (15 Oct
    # 2026, an internal review of the printed figures).
    top = max(s for _, _, s, _, _ in pos) * 1.30
    # A label set four points above its marker occupies roughly this much of the data range.
    # Any marker sitting that close beneath the boundary would have the rule printed through
    # its label, so the label hangs below the marker instead.
    clearance = 0.11 * top
    for label, frac, spread, colour, offsets in pos:
        # The statistic, and the replicates it is made of. The stick runs the full spread and
        # each tick is one replicate's distance above the arm minimum, so a reader can see
        # whether an arm clears the boundary because it is broad or because two of its
        # replicates are strays -- which is the difference between the 32 KB arm, three of
        # whose replicates sit within 0.06 of each other, and the 64 KB arm, which is broad.
        ax.plot([frac, frac], [0, spread], color=colour, lw=0.9, alpha=0.45, zorder=2,
                solid_capstyle="butt")
        for off in offsets:
            ax.plot([frac - 0.012, frac + 0.012], [off, off], color=colour, lw=0.9,
                    alpha=0.8, zorder=2, solid_capstyle="butt")
        ax.scatter([frac], [spread], s=22, color=colour, edgecolors="none", zorder=3,
                   marker=PAYLOAD_MARKERS.get(label, "o"))
        # A point in the right-hand third would carry its label off the axis, so the label
        # turns around and sits to its left instead.
        right = frac > 0.55
        collides = 0 <= (half - spread) < clearance
        ax.annotate(label, xy=(frac, spread),
                    xytext=(-5 if right else 5, -5 if collides else 4),
                    textcoords="offset points", fontsize=8, color="#222222",
                    ha="right" if right else "left",
                    va="top" if collides else "baseline")
    ax.set_xlim(-0.03, 0.75)
    ax.set_ylim(0, top)
    ax.set_xlabel(r"frac($q\theta$)", fontsize=8)
    # Percentage points of retention, written out: "(pts)" could be read as type or data points.
    ax.set_ylabel("replicate spread\n(percentage points)", fontsize=8)
    ax.set_title("(b) The flat/full flip", fontsize=8)
    ax.tick_params(labelsize=8)


def build_payload(out_dir):
    """Stacked and one column wide, not side by side across two.

    Drawn across the full text width this was 7.16 by 1.53 inches: two sparse panels with a
    great deal of white between them, costing twice its own height in column inches because a
    `figure*` occupies both columns. Stacked at column width it carries the same two panels in
    two thirds of the space, and a single-column float can also settle anywhere on the page
    rather than only at the top of one. The panels are unchanged.
    """
    figure_style.apply()   # in force when the artists are made, not merely at import
    arms = payload_arms()
    # 2.855 in, from 2.86, since the spread's axis label took a second line (15 Oct 2026): the
    # crop came out a hair narrower, and the page would have printed the figure 0.2 pt taller.
    fig, axes = plt.subplots(2, 1, figsize=(3.50, 2.855))
    plot_payload_grid(axes[0], arms)
    plot_payload_flip(axes[1], payload_positions(arms))
    fig.tight_layout(h_pad=1.0)
    return _save(fig, out_dir, "payload_flip")


# --- the recovery populations (the postmortem's S16.9) -------------------------------------

def plot_recovery(axes, pops, cells):
    """The recovery's error on the groups the check accepts and those it rejects, as
    empirical distribution functions: (a) pooled, (b) on Kafka, (c) on Redis.

    Round 77 drew the two pooled populations, beside a strip of every group, for S16.9's
    argument about their shape around a pile of exact recoveries. 15 Oct 2026, S16.9
    rewritten: at native resolution that pile is gone, and the pooled verdicts part because
    they mix the brokers unevenly. So (a) draws the pooled verdicts, which part, and (b) and (c)
    each broker's, which interleave. Every group is a mark on its curve, and the axis is
    logarithmic, because Kafka's errors lie an order of magnitude below Redis's and a linear
    axis stacked all of Kafka's groups on its first tick. One axis for all three panels, so
    that the brokers' errors sit where they sit against each other.
    """
    # The rejected population in grey, not DELETED red (round 78, W3). Red means "deleted" in
    # Figure 4 and in the deletion histogram, and S16.9's whole point is that these groups were
    # kept and measured: a reader carrying Figure 4's legend here would read them as discarded.
    # Grey is what the paper already draws for what is printed and kept.
    from matplotlib.ticker import FuncFormatter
    series = (("Pass", "check accepts", KEPT), ("Fail", "check rejects", GREY))
    panels = ((axes[0], pops, ""), (axes[1], cells, "Kafka"), (axes[2], cells, "Redis"))
    every = [v for p in pops.values() for v in p]
    for ax, source, broker in panels:
        for key, label, colour in series:
            v = sorted(source[broker + key])
            xs = sorted(set(v))
            fs = [sum(1 for t in v if t <= x) / len(v) for x in xs]
            ax.step([xs[0]] + xs, [0.0] + fs, where="post", color=colour, lw=1.2, label=label)
            ax.plot(xs, fs, "o", color=colour, mec="none", ms=3.0, ls="none")
        ax.set_xscale("log")
        ax.set_xlim(min(every) / 2.0, max(every) * 2.0)
        ax.xaxis.set_major_formatter(FuncFormatter(figure_style.plain_log_label))
        ax.set_ylim(0.0, 1.03)
        ax.tick_params(labelsize=8)
        ax.grid(alpha=0.25, lw=0.5)
    # One legend, in the corner of (a) that both pooled curves leave empty: low errors are
    # Kafka's, and fewer than three quarters of either verdict's groups lie there. Each panel's
    # counts are the caption's, from the ledger; in a legend of every panel, Kafka's sat on
    # its own curves.
    axes[0].legend(fontsize=8, frameon=False, loc="upper left", handletextpad=0.4,
                   borderaxespad=0.3)
    axes[0].set_ylabel("share of groups", fontsize=8)
    # One label for the three axes they share, under the middle one; "log" in it, and the
    # ticks written out, as the paper's other logarithmic axes have them (15 Oct 2026).
    axes[1].set_xlabel("recovery error (% of median end-to-end latency, log)", fontsize=8)
    # Titled as the caption names the panels, and on a capital: `test_figure_typography` holds
    # every panel title in the submission to that, and reads the titles written out here.
    axes[0].set_title("(a) Both brokers", fontsize=8, loc="left")
    axes[1].set_title("(b) Kafka", fontsize=8, loc="left")
    axes[2].set_title("(c) Redis", fontsize=8, loc="left")


def build_recovery(out_dir):
    figure_style.apply()   # in force when the artists are made, not merely at import
    import stat_intervals
    fig, axes = plt.subplots(1, 3, figsize=(6.5, 2.35), sharey=True)
    # The populations the ledger's macros are made from, through the one loader both read
    # (round 77): pooled by verdict, and each broker's two verdicts (15 Oct 2026).
    plot_recovery(axes, stat_intervals.recovery_populations(),
                  stat_intervals.recovery_populations(split="both"))
    fig.tight_layout()
    return _save(fig, out_dir, "recovery_populations")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the result figures")
    ap.add_argument("--out", default=os.path.join("docs", "results", "figures"))
    ap.add_argument("--only",
                    choices=("deletion_phases", "spectrum", "grid", "mechanism", "ttrue",
                             "payload", "exposure", "recovery", "priority", "remedies",
                             "priority_forest", "fix_benefit"),
                    default=None)
    args = ap.parse_args(argv)

    builders = {"deletion_phases": build_deletion_phases,
                "spectrum": build_spectrum, "grid": build_grid,
                "mechanism": build_mechanism, "ttrue": build_ttrue,
                "payload": build_payload, "exposure": build_exposure,
                "priority": build_priority_ladder, "recovery": build_recovery,
                "remedies": build_remedies, "priority_forest": build_priority_forest,
                "fix_benefit": build_fix_benefit}
    todo = [args.only] if args.only else list(builders)
    for name in todo:
        path = builders[name](args.out)
        print("wrote %s" % path)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
