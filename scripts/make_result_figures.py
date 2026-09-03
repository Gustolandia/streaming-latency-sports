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
               probability as a function of $T_{true}$, as an
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


QUANTUM_MS = 2.0  # a cell printing at most this is reporting at the grid, not above it

# Two markers closer than this on a log axis, as a ratio, are one marker to the eye.
COINCIDENT_RATIO = 1.06
# And this is how far apart they have to go to stop being one. A marker in the deletion
# figure is about 4.8 pt across and a decade of that axis is about 46 pt wide, so a tenth of
# a decade is one marker's width -- which is 2% of the axis and invisible as a displacement.
SEPARATION_RATIO = 1.30


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
    tags = [p[2] if len(p) > 2 else "" for p in pts]
    at_grid = med <= quantum_ms

    # The above-grid markers are counted in their own legend entry, so each one has to be
    # visible; the at-grid stripe is read as a range and is left alone.
    above_x = spread_coincident(list(med[~at_grid]), list(ret[~at_grid]))

    ax.scatter(med[at_grid], ret[at_grid], s=16, color=KEPT, edgecolors="none",
               zorder=3, label="printed at the grid (%d)" % at_grid.sum())
    ax.scatter(above_x, ret[~at_grid], s=18, facecolors="none", edgecolors=GREY,
               linewidths=0.9, zorder=3, label="printed above it (%d)" % (~at_grid).sum())
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("median latency the benchmark printed (ms)", fontsize=8)
    ax.set_ylabel("samples retained (%)", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(alpha=0.25, lw=0.5)
    ax.axhline(100, color=GREY, lw=0.6, ls=":", zorder=0)

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
    seen = set()
    for x, y, tag in sorted(zip(above_x, ret[~at_grid],
                                [tg for tg, g in zip(tags, at_grid) if not g])):
        if not tag or tag in seen:
            continue
        seen.add(tag)
        ax.annotate(tag, xy=(x, y), xytext=(0, -9), textcoords="offset points",
                    fontsize=8, color=GREY, ha="center", va="top")

    ax.legend(fontsize=8, frameon=False, loc="lower right", handletextpad=0.4)


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
    ax.set_xlabel("run-queue stall (µs, log2 buckets)", fontsize=8)
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
            ax.annotate("base slice: %.0f ms\n%.1f× the one below"
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

    # Each arm's own null, drawn where its centre sits on the diagonal. Without it the figure
    # asked the eye to judge distance from a line with nothing to say how far an arm can fall
    # by chance; the p-values that answered that were printed only in a supplement table. An
    # arm whose marker clears its own bar is an arm that rejects, so the picture now carries
    # the test rather than illustrating it.
    for x, (blo, bhi) in zip(xs, bands):
        if blo is None or bhi is None:
            continue
        ax.plot([x, x], [blo, bhi], color=GREY, lw=1.1, alpha=0.55, zorder=1,
                solid_capstyle="butt")
    # The annotation that used to point at the diagonal -- "a continuum would land on this
    # line" -- is gone, and the bars are why. The diagonal is the null's centre; the bars are
    # the null. Once both are drawn, a label naming the weaker of the two costs a legend row
    # it now collides with and tells the reader less than the thing beside it. The caption
    # names the diagonal instead.
    ax.text(lim * 0.72, lim * 0.11, "closer to the grid", fontsize=8,
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
    which arm moved. Reading down the rows, the real-time arm barely moves while the ordinary
    arm climbs with load, and the gap between them -- the factor -- widens from sevenfold to
    eightyfold. That is the pattern the range in the main text summarises.
    """
    import stat_intervals

    rows = sorted(rows, key=lambda r: (r["rho"], r["campaign"]))
    positions = list(range(len(rows)))[::-1]
    for pos, r in zip(positions, rows):
        for rate, n, colour, marker in ((r["rate_base"], r["n_base"], DELETED, "o"),
                                        (r["rate_rt"], r["n_rt"], KEPT, "s")):
            lo, hi = stat_intervals.wilson(int(round(rate * n)), n)
            ax.plot([lo, hi], [pos, pos], color=colour, lw=1.4, solid_capstyle="butt")
            ax.plot([rate], [pos], marker, ms=4.0, color=colour, mec="none")
        ax.text(1.35, pos, "%.0f$\\times$" % r["factor"], transform=ax.get_yaxis_transform(),
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
    ax.plot([], [], "o", color=DELETED, mec="none", ms=4.0, ls="none", label="ordinary")
    ax.plot([], [], "s", color=KEPT, mec="none", ms=4.0, ls="none", label="real-time")
    # Upper right: the bottom row is the 95% arm, whose ordinary interval runs to the right
    # edge, and a legend there sits on it.
    ax.legend(fontsize=8, frameon=False, loc="upper right")


def build_priority_ladder(out_dir):
    figure_style.apply()   # in force when the artists are made, not merely at import
    import priority_pairs
    fig, ax = plt.subplots(figsize=(6.50, 3.10))
    plot_priority_ladder(ax, priority_pairs.usable())
    fig.tight_layout()
    return _save(fig, out_dir, "priority_ladder")


# --- driver -----------------------------------------------------------------------------

def _save(fig, out_dir, stem):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ("%s.pdf" % stem)
    figure_collisions.check(fig, stem)
    figure_legibility.check(fig, stem)
    figure_vocabulary.check(fig, stem)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    return path


def build_deletion(out_dir):
    figure_style.apply()   # in force when the artists are made, not merely at import
    fig, ax = plt.subplots(figsize=(3.50, 2.15))
    plot_deletion(ax, retention_points())
    fig.tight_layout()
    return _save(fig, out_dir, "deletion")


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
        arms.append((pretty, "ordinary", kb, nb))
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
    utilisation and the rate moves with it.

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
PAYLOAD_ARMS = (
    ("200 B", (("rate_q", 300), ("ultimate", 300)), GREY),
    ("32 KB", (("ultimate_pay300", 32768),), DELETED),
    ("64 KB", (("ultimate_pay300", 65536),), KEPT),
)
PAYLOAD_Q = 3  # 300 msg/s against a 1 ms tick is 10/3 in lowest terms


def payload_arms(path=None):
    """Retention percentages per payload arm, from the committed campaign ledger.

    Selection matches the audit everywhere else: valid runs only, and only those whose counts
    came from the shutdown hook, because a run whose totals were reconstructed afterwards cannot
    support a retention rate.
    """
    import csv
    path = path or (RESULTS / "external_campaigns_index.csv")
    rows = list(csv.DictReader(open(path, encoding="utf-8", newline="")))
    out = []
    for label, keys, colour in PAYLOAD_ARMS:
        vals = []
        for campaign, level in keys:
            for r in rows:
                if (r.get("campaign") != campaign or r.get("valid") != "1"
                        or r.get("count_source") != "shutdown_hook"
                        or (r.get("level") or "") != str(level)):
                    continue
                try:
                    kept = int(r.get("kept") or 0)
                    seen = kept + int(r.get("discarded_zero") or 0) \
                        + int(r.get("discarded_negative") or 0)
                except (TypeError, ValueError):
                    continue
                if seen > 0:
                    vals.append(100.0 * kept / seen)
        if not vals:
            raise ValueError("no replicates for payload arm %s" % label)
        out.append((label, sorted(vals), colour))
    return out


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
        ax.scatter(swarm, vals, s=15, color=colour, edgecolors="none", zorder=3)
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
    ax.set_title("(a) replicates against the $q=%d$ grid" % q, fontsize=8)
    ax.tick_params(labelsize=8)


def plot_payload_flip(ax, pos, q=PAYLOAD_Q):
    """Panel (b): the spread against cell position, and the boundary it crosses twice."""
    half = 100.0 / (2 * q)
    ax.axhline(half, color=GREY, lw=0.8, ls="--", zorder=0)
    # Hard left. The label used to start at 0.30 and ran right, which was clear while the
    # arms were three bare markers and stopped being clear the moment each arm grew a stick:
    # the 200 B stick rises through the boundary at frac 0.40 and printed itself across the
    # last word.
    ax.annotate("half cell width", xy=(0.0, half), xytext=(0, 3),
                textcoords="offset points", fontsize=8, color=GREY, va="bottom", ha="left")
    top = max(s for _, _, s, _, _ in pos) * 1.22
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
        ax.scatter([frac], [spread], s=22, color=colour, edgecolors="none", zorder=3)
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
    ax.set_ylabel("replicate spread (pts)", fontsize=8)
    ax.set_title("(b) the flat/full flip", fontsize=8)
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
    fig, axes = plt.subplots(2, 1, figsize=(3.50, 2.86))
    plot_payload_grid(axes[0], arms)
    plot_payload_flip(axes[1], payload_positions(arms))
    fig.tight_layout(h_pad=1.0)
    return _save(fig, out_dir, "payload_flip")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the result figures")
    ap.add_argument("--out", default=os.path.join("docs", "results", "figures"))
    ap.add_argument("--only",
                    choices=("deletion", "spectrum", "grid", "mechanism", "ttrue", "payload"),
                    default=None)
    args = ap.parse_args(argv)

    builders = {"deletion": build_deletion, "spectrum": build_spectrum, "grid": build_grid,
                "mechanism": build_mechanism, "ttrue": build_ttrue,
                "payload": build_payload,
                "priority": build_priority_ladder}
    todo = [args.only] if args.only else list(builders)
    for name in todo:
        path = builders[name](args.out)
        print("wrote %s" % path)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
