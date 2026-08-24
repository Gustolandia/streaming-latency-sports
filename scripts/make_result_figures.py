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

  spectrum  -- the traced stall distribution, which is trimodal, with the largest of the three
               modes sitting on the scheduler's base slice. The mechanism argument in Section V
               rests entirely on where that mode is, and asking a reader to hold a log2
               histogram in their head from a list of bucket counts is asking too much.

  grid      -- membership against a continuum null, beside the table that carries the same
               numbers. A table of twelve p-values answers "is each arm significant"; the
               figure answers "does the whole set lie on the grid", which is the actual claim.

  mechanism -- the four matched pairs as a forest of Wilson intervals. Table III gives the
               numbers, and the numbers are the evidence; what the table cannot show at a
               glance is that no pair overlaps, which is the causal claim itself.

  ttrue     -- inversion rate against the interval being measured. Equation 2 as an
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
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import figure_style  # noqa: E402
import figure_collisions  # noqa: E402
import figure_legibility  # noqa: E402
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
            ax.annotate("scheduler base slice:\n%.0f ms, %.1f× the bucket below"
                        % (slice_ms, rise),
                        xy=(i + 0.62, share[i] * 0.72),
                        xytext=(len(los) - 0.5, max(share) * 1.30),
                        fontsize=8, color=DELETED, ha="right", va="top",
                        # Bowed away from the bar rather than towards it: the original arc
                        # passed through the "%.1f%%" label sitting above the same bar.
                        arrowprops=dict(arrowstyle="->", color=DELETED, lw=0.8,
                                        relpos=(0.5, 0.0),
                                        connectionstyle="arc3,rad=-0.28"))
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

    lim = max(xs + ys) * 1.12
    ax.plot([0, lim], [0, lim], color=GREY, lw=0.8, ls="--", zorder=1)
    # Below the diagonal is the whole claim: closer to the grid than a continuum would be.
    ax.fill_between([0, lim], [0, 0], [0, lim], color=KEPT, alpha=0.06, zorder=0)
    # Below the legend and left of the diagonal. At the previous anchor the diagonal passed
    # through the last glyph of "line" -- a strike on the terminal letter, which the collision
    # gate's horizontal inset does not reach and which the eye sees immediately.
    ax.annotate("a continuum would\nland on this line", xy=(lim * 0.42, lim * 0.42),
                xytext=(lim * 0.155, lim * 0.26), fontsize=8, color=GREY, ha="center",
                arrowprops=dict(arrowstyle="->", color=GREY, lw=0.7))
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
    ax.legend(fontsize=8, frameon=False, loc="upper left")


def grid_rows():
    """The grid arms, from the same helper the ledger and the table use."""
    out = []
    for c in stat_intervals.grid_cells():
        out.append({"rate_hz": c["rate_hz"], "q": c["q"], "powered": c["powered"],
                    "d_obs": c["d_observed"], "d_null": c["d_null"],
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
    ax.set_xlabel("inversion rate (Wilson 95% interval, log)", fontsize=8)
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

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("inversion rate (Wilson 95% interval)", fontsize=8)
    ax.tick_params(axis="x", labelsize=8)
    ax.grid(axis="x", alpha=0.25, lw=0.5)
    _hi = max(stat_intervals.wilson(k, n)[1] for _, _, k, n in rows) * 1.10
    # The real-time arms sit at essentially zero, where the frame would cut the marker.
    ax.set_xlim(-_hi * 0.015, _hi)
    for i in range(0, len(arms), 2):
        ax.axhspan(len(rows) - i - 1.5, len(rows) - i + 0.5, color=GREY, alpha=0.05, zorder=0)
    if observed:
        # The rule is the point: everything above it was moved on purpose, everything below
        # it was only observed. Without it the brokers read as a fifth matched pair.
        ax.axhline(len(observed) + 0.5, color=GREY, lw=0.7, ls=(0, (4, 2)), zorder=1)
        ax.text(ax.get_xlim()[1], len(observed) + 0.62, "manipulated", fontsize=8,
                color=GREY, ha="right", va="bottom")
        ax.text(ax.get_xlim()[1], len(observed) + 0.38, "observed", fontsize=8,
                color=GREY, ha="right", va="top")
    ax.set_ylim(0.4, len(rows) + 0.6)


# --- the interval being measured decides the rate -------------------------------------------

TTRUE_CSV = RESULTS / "model" / "ttrue_sweep.csv"


def ttrue_points(path=TTRUE_CSV):
    """(transport ms, inversion rate, ci_lo, ci_hi) over the payload sweep."""
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
    """Inversion rate against the interval being measured, over a 77x payload span.

    This is Equation 2 as an experiment: the same stall distribution overlaps a short
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
    ax.set_ylabel("inversion rate", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(alpha=0.25, lw=0.5)

    slope, _, _r2, lo_slope, hi_slope = stat_intervals.payload_fit()
    # The ratio drawn here is the span in *transport*, not in payload: payload starts at zero
    # bytes and so has no ratio. The manuscript states it the same way.
    # The interval rather than R-squared: on four points R-squared is the flattering
    # statistic and the interval on the exponent is the one that says what was learned.
    ax.annotate("slope %.2f (%.2f to %.2f)\nover a %d× span in transport"
                % (slope, lo_slope, hi_slope, round(xs[-1] / xs[0])),
                # Left of where it was: adding the interval lengthened the first line enough
                # to put the second line's last glyph on the right spine.
                xy=(xs[1], ys[1]), xytext=(0.24, 0.82), textcoords="axes fraction",
                fontsize=8, color=GREY,
                arrowprops=dict(arrowstyle="->", color=GREY, lw=0.7))
    ax.set_xlim(xs[0] * 0.55, xs[-1] * 1.9)


def build_mechanism(out_dir):
    figure_style.apply()   # in force when the artists are made, not merely at import
    # Two extra rows and a rule. The panel grows by less than the row count: the arms were
    # set with room to spare and the column budget has none.
    fig, ax = plt.subplots(figsize=(3.50, 2.30))
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

    theta is the arm's mean retention as a fraction, which by Equation 4 estimates
    T_true/tau. frac(q*theta) is then the replicates' position inside their grid cell, and
    Equation 5 says the spread should be near 100/q at mid-cell and near zero on a vertex.
    """
    arms = payload_arms() if arms is None else arms
    out = []
    for label, vals, colour in arms:
        theta = (sum(vals) / len(vals)) / 100.0
        out.append((label, (q * theta) % 1.0, max(vals) - min(vals), colour))
    return out


def plot_payload_grid(ax, arms, q=PAYLOAD_Q):
    """Panel (a): every replicate against the q-grid it is supposed to land on."""
    for x, (label, vals, colour) in enumerate(arms):
        jitter = [x + (i - (len(vals) - 1) / 2.0) * 0.055 for i in range(len(vals))]
        ax.scatter(jitter, vals, s=15, color=colour, edgecolors="none", zorder=3)
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
    ax.annotate("half cell width", xy=(0.30, half), xytext=(0, 3),
                textcoords="offset points", fontsize=8, color=GREY, va="bottom")
    top = max(s for _, _, s, _ in pos) * 1.22
    # A label set four points above its marker occupies roughly this much of the data range.
    # Any marker sitting that close beneath the boundary would have the rule printed through
    # its label, so the label hangs below the marker instead.
    clearance = 0.11 * top
    for label, frac, spread, colour in pos:
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
    figure_style.apply()   # in force when the artists are made, not merely at import
    arms = payload_arms()
    fig, axes = plt.subplots(1, 2, figsize=(7.16, 1.75))
    plot_payload_grid(axes[0], arms)
    plot_payload_flip(axes[1], payload_positions(arms))
    fig.tight_layout(w_pad=2.2)
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
