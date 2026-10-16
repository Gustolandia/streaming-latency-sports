#!/usr/bin/env python3
"""
make_deletion_histogram.py
Draw what the instrument deletes, next to what it then reports.

Origin. D. Gregg (2026-08-26, then a co-author, withdrawn 2026-09-08) pointed at the OpenMessaging Benchmark's own
published latency distribution and said: plot that on our data and a whole population sits left
of zero; then plot it again as the software leaves it once that population is discarded, and the
two graphs do not look alike. He asked, in the same message, for the impact of the *various*
strategies for handling such samples. This figure is that, in three panels.

Every number here is emitted by `span_histogram.py` from the archived corpus (since 7 Oct 2026
5,863 runs and 708,505 joined events, the late messages of stale_backlog.py left out) and read
from the committed CSV and JSON, so the figure builds without the 800 MB archive.

What the three panels say, in order:

  (a) At nanosecond resolution the acknowledgment-referenced span really does go below zero,
      62,264 times in 708,505. The publish-timed span, on the same events and the same clock,
      never does. That contrast is the control: the negatives are a property of which stamp is
      used as the origin, not of the delivery being timed.

  (b) A millisecond instrument does not see panel (a). It differences two truncated stamps, so a
      sub-millisecond interval lands on 0 or on 1 depending only on where the tick boundaries
      fall -- the bimodal 0/1 split is that arithmetic, visible raw. The benchmark then admits a
      sample only when the difference is strictly positive, which deletes everything at or below
      zero: 338,242 of 708,505, or 47.7 per cent, none of it counted in what is reported.

  (c) Five dispositions, all found in shipping software and all audited in the manuscript,
      applied to the same measured population. Two of them (discard, NaN) shrink the sample the
      statistic is computed from and report no count of what left. Two (zero, unit) keep the
      sample count intact by reporting a value that was never measured. One keeps the data.

CLI:
    python scripts/make_deletion_histogram.py                    # paper width, PDF + PNG
    python scripts/make_deletion_histogram.py --talk             # slide width, PNG
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import figure_legibility
import figure_style

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

HIST_CSV = os.path.join("docs", "results", "span_histogram.csv")
STATS_JSON = os.path.join("docs", "results", "span_histogram_stats.json")
#: The per-group histograms of S, which sum to HIST_CSV's pooled one bin for bin; Fig. 2 splits
#: S by broker from them (15 Oct 2026).
BY_CONDITION_JSON = os.path.join("docs", "results", "span_by_condition.json")
OUT_DIR = os.path.join("docs", "results", "figures")

#: 15 Oct 2026, Fig. 2: each broker in the colour the paper's Fig. 3 gives it, and the two
#: priorities in a second pair that no broker colour is confused with (the palette passes the
#: all-pairs colour-vision checks as a set of four).
BROKERS = (("kafka", "Kafka", "#1f77b4"), ("redis", "Redis", "#d62728"))
PRIORITIES = (("normal", "normal priority", "#7b3294", "o"),
              ("real-time", "real-time priority", "#1b9e77", "s"))
POOLED = "#cfcfcf"
INK = "#222222"
#: The linear inset's half-width around zero, in microseconds (referee A, Fig. 2).
INSET_US = 500
#: Panel (a)'s count axis runs to here, two and a half decades over the tallest bin, so that the
#: two-row legend stands above every bin (15 Oct 2026).
PANEL_A_TOP = 3e7
#: Panel (b)'s rate axis, from just below zero, so that a rate of zero is not cut by the frame, to
#: just over the highest run's rate (0.55, Kafka at 95% load).
PANEL_B_YLIM = (-0.03, 0.60)
#: A label whose maths carries subscripts, set so that they print at 6.5 pt (figure_style).
MATH_PT = figure_style.MATH_PT
#: Fig. 2's canvas, saved whole: exactly the column's 3.5 in, so that the page prints it at its
#: own size, neither enlarged nor shrunk (15 Oct 2026; see build_s_distribution).
S_DISTRIBUTION_IN = (3.5, 3.40)

KAFKA, REDIS = "#1f77b4", "#ff7f0e"
GREY = "#555555"
CUT = "#b22222"          # the colour the paper already uses for the failing interval
KEPT = "#4c78a8"

#: Display window for panel (a). The corpus reaches -99.8 ms and +424 s; the window holds the
#: negative population entire (p0.1 is -4.4 ms) and the body of the positive one, and the count
#: falling outside is printed on the panel rather than dropped, because that is the whole point.
VIEW_LO_US = -5000
VIEW_HI_US = 5000

#: Panel (b) shows the millisecond grid over the range that carries the mass.
MS_LO, MS_HI = -6, 8

#: Short labels. The long forms ("discard (OMB, emqtt)") ran into their neighbours at paper
#: width; the software each rule comes from is named in the caption, which has room for it.
STRATEGIES = (
    ("keep", "keep\n(ours)", False),
    ("discard", "discard\n(OMB)", True),
    ("nan", "NaN\n(KIP-489)", True),
    ("zero", "zero\n(fio)", False),
    ("unit", "max(d,1)\n(btt)", False),
)


def read_hist(path=None):
    path = HIST_CSV if path is None else path
    """Bin rows from the committed CSV as {span: [(lo_us, hi_us, count)]}, plus the overflows."""
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    header = rows[0][2:]
    series = {name: [] for name in header}
    extra = {name: {"under": 0, "over": 0} for name in header}
    for row in rows[1:]:
        if row[0] == "UNDERFLOW":
            for i, name in enumerate(header):
                extra[name]["under"] = int(row[2 + i])
            continue
        if row[0] == "OVERFLOW":
            for i, name in enumerate(header):
                extra[name]["over"] = int(row[2 + i])
            continue
        lo, hi = int(row[0]), int(row[1])
        for i, name in enumerate(header):
            series[name].append((lo, hi, int(row[2 + i])))
    return series, extra


def outside_window(series, extra, name="ack", lo_us=VIEW_LO_US, hi_us=VIEW_HI_US):
    """What the drawn window leaves out of one span: (below, above), overflows included.

    6 Oct 2026: the paper's Fig. 2 counted only the overflow past the histogram's own range,
    +100 ms, under the words "above the window", and the window ends at 5 ms. The values
    between 5 and 100 ms, and every value below -5 ms, were neither drawn nor counted. The
    bins are aligned to the window's edges, so a bin is wholly inside or wholly outside.
    """
    below = extra[name]["under"] + sum(c for lo, _hi, c in series[name] if lo < lo_us)
    above = extra[name]["over"] + sum(c for lo, _hi, c in series[name] if lo >= hi_us)
    return below, above


def below_zero(series, extra, name="ack"):
    """(values below zero, all values) of one span, from the histogram the figure draws.

    7 Oct 2026: panel (a) printed "62,264 below zero (8.43% of 738,730)" as typed text, and
    leaving out the late messages moved the total under it. The bins are aligned to zero, so a
    bin is wholly below it or wholly at or above it.
    """
    counts = [c for _lo, _hi, c in series[name]]
    below = extra[name]["under"] + sum(c for lo, _hi, c in series[name] if lo < 0)
    return below, extra[name]["under"] + sum(counts) + extra[name]["over"]


def read_stats(path=None):
    path = STATS_JSON if path is None else path
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _thousands(value, _pos):
    if value >= 1000:
        return "%dk" % (value / 1000)
    return "%d" % value


def plot_measured(ax, series, extra):
    """(a) the two spans as measured, nanosecond resolution."""
    ack = [(lo, c) for lo, hi, c in series["ack"] if VIEW_LO_US <= lo < VIEW_HI_US]
    send = [(lo, c) for lo, hi, c in series["send"] if VIEW_LO_US <= lo < VIEW_HI_US]

    width = 50
    neg = [(lo, c) for lo, c in ack if lo < 0]
    pos = [(lo, c) for lo, c in ack if lo >= 0]
    ax.bar([lo for lo, _ in pos], [c for _, c in pos], width=width, align="edge",
           color=KEPT, linewidth=0)
    ax.bar([lo for lo, _ in neg], [c for _, c in neg], width=width, align="edge",
           color=CUT, linewidth=0)
    ax.step([lo for lo, _ in send], [c for _, c in send], where="post",
            color=REDIS, linewidth=1.0)

    ax.axvline(0, color=GREY, linewidth=0.8, linestyle=(0, (3, 2)))
    ax.set_xlim(VIEW_LO_US, VIEW_HI_US)
    # Log counts. On a linear axis the spike just above zero is 88k tall and the negative
    # population -- the entire subject of the panel -- is a smear one pixel high. The point of
    # the figure is that the deleted population is THERE, so the axis has to be able to show a
    # bin of 40 next to a bin of 88,000.
    ax.set_yscale("log")
    ax.set_ylim(1, None)
    # The micro sign, as Fig. 3's axis has it. This said "(us)".
    ax.set_xlabel("measured span (µs)")
    ax.set_ylabel("events (log)")
    # The window caveat rides in the title. Below the axis it sat on the x-label; inside the
    # panel it sat on the bars, in grey on dark red. A title has room and nothing to collide
    # with, and the caveat is about the panel as a whole rather than about any point in it.
    above = extra["ack"]["over"]
    # Short form: the long sentence fitted the two-row paper layout, where panel (a) spans the
    # full width, and ran into panel (b)'s title in the three-across slide layout.
    ax.set_title("(a) As measured, one clock, nanosecond timestamps  (+%s above window)"
                 % "{:,}".format(above), fontsize=8, loc="left")

    negative, total = below_zero(series, extra)
    ax.text(0.03, 0.95, "{:,} below zero\n({:.2f}% of {:,})".format(
                negative, 100.0 * negative / total, total),
            transform=ax.transAxes, fontsize=7, color=CUT, va="top", ha="left")
    ax.text(0.97, 0.95, "publish-timed span\non the same events:\nnever below zero",
            transform=ax.transAxes, fontsize=7, color=REDIS, va="top", ha="right")


def plot_grid(ax, stats):
    """(b) the same events as a millisecond timestamp holds them, and the condition's cut."""
    table = stats["spans"]["ack"]["ms_table"]
    xs = list(range(MS_LO, MS_HI + 1))
    ys = [table.get(str(x), 0) for x in xs]
    colours = [CUT if x <= 0 else KEPT for x in xs]
    ax.bar(xs, ys, width=0.82, color=colours, linewidth=0)

    ax.set_xlim(MS_LO - 0.6, MS_HI + 0.6)
    # A tick at every integer, because each one locates a bar, but a label on every second
    # one: at this width the negative half printed as `-6-5-4-3-2-1`, with the minus signs
    # closing every gap a reader could have read the numbers apart by. Zero stays labelled,
    # which is the boundary the panel is about.
    ax.set_xticks(xs, minor=True)
    ax.set_xticks([x for x in xs if x % 2 == 0])
    ax.set_xlabel("millisecond-differenced span (ms)")
    ax.set_ylabel("events")
    ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
    ax.set_title("(b) As a millisecond timestamp holds it", fontsize=8, loc="left")

    # A shaded span behind the bars, rather than an arrow between them: the deleted region is
    # contiguous and reaches the axis edge, so a two-headed arrow had nowhere to sit and its
    # label landed on the bars it was pointing at.
    ax.axvspan(MS_LO - 0.6, 0.5, color=CUT, alpha=0.07, linewidth=0, zorder=0)

    rule = stats["spans"]["ack"]["ms_rule"]
    # Left, over the shaded region it describes. Anchored right it ran across the 0 ms and
    # 1 ms bars, which are the two tallest things in the panel.
    # Narrow enough to stay inside the shaded band: the wide form reached the 0 ms and 1 ms
    # bars, which carry 600k of the 738k events between them.
    ax.text(0.03, 0.95,
            "admits only > 0:\ndeletes %.1f%%\n(%s events)"
            % (100.0 * (1 - rule["retention"]), "{:,}".format(rule["dropped"])),
            transform=ax.transAxes, fontsize=7, color=CUT, ha="left", va="top")
    ax.text((MS_LO - 0.6 + 0.5) / 2.0, max(ys) * 0.55, "deleted",
            fontsize=8, color=CUT, ha="center", va="center")


def plot_strategies(ax, stats):
    """(c) what share of the samples taken reaches the reported statistic, per disposition."""
    ns = stats["spans"]["ack"]["counts"]
    ms = stats["spans"]["ack"]["ms_rule"]
    total = ns["total"]

    ns_share = {
        "keep": 1.0,
        "discard": ns["retained_discard"] / total,
        "nan": ns["retained_nan"] / total,
        "zero": 1.0,
        "unit": 1.0,
    }
    ms_share = {
        "keep": 1.0,
        "discard": ms["retention"],
        "nan": ms["retention"],
        "zero": 1.0,
        "unit": 1.0,
    }

    xs = range(len(STRATEGIES))
    w = 0.38
    for i, (key, _label, _drops) in enumerate(STRATEGIES):
        ax.bar(i - w / 2, 100 * ns_share[key], width=w, color=KEPT, linewidth=0)
        ax.bar(i + w / 2, 100 * ms_share[key], width=w, color=GREY, linewidth=0)

    # The two that keep the count by inventing a value are marked, because "100%" for them
    # means something different from "100%" for keep, and a bar chart alone would say they agree.
    for i, (key, _label, _drops) in enumerate(STRATEGIES):
        if key in ("zero", "unit"):
            ax.text(i, 103, "value not\nmeasured", fontsize=6, color=CUT,
                    ha="center", va="bottom", linespacing=0.9)

    ax.set_xticks(list(xs))
    ax.set_xticklabels([label for _k, label, _d in STRATEGIES], fontsize=7, linespacing=0.9)
    ax.set_ylim(0, 128)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("% of samples taken\nreaching the statistic")
    ax.set_title("(c) Five dispositions, one population", fontsize=8, loc="left")
    ax.legend(handles=[
        plt.Rectangle((0, 0), 1, 1, color=KEPT),
        plt.Rectangle((0, 0), 1, 1, color=GREY),
    ], labels=["nanosecond timestamps", "millisecond timestamps"], fontsize=6,
        loc="lower left", frameon=False, ncol=1)


def read_broker_hist(path=None):
    """S per broker on the pooled histogram's own 50 us bins, from the per-group histograms.

    Returns ({broker: [(lo_us, hi_us, count)]}, {broker: {"under": n, "over": n}}). The groups
    of span_by_condition.json partition the messages HIST_CSV pools, so the two brokers' bins
    sum to the pooled bins exactly; a test holds them to it.
    """
    path = BY_CONDITION_JSON if path is None else path
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    lo0, width = data["bin_lo_us"], data["bin_width_us"]
    bins, extra = {}, {}
    for cond, q in data["conditions"].items():
        broker = cond.split("_")[0]
        acc = bins.setdefault(broker, {})
        for k, v in q["S"]["bins"].items():
            acc[int(k)] = acc.get(int(k), 0) + v
        e = extra.setdefault(broker, {"under": 0, "over": 0})
        e["under"] += q["S"]["under"]
        e["over"] += q["S"]["over"]
    series = {b: [(lo0 + k * width, lo0 + (k + 1) * width, c) for k, c in sorted(acc.items())]
              for b, acc in bins.items()}
    return series, extra


def _steps(rows, lo_us, hi_us):
    """Edges and counts of the bins inside [lo_us, hi_us), empty bins filled with zero, for a
    step outline that drops to zero where a broker has no messages rather than bridging."""
    have = {lo: c for lo, _hi, c in rows}
    width = rows[0][1] - rows[0][0]
    edges = list(range(int(lo_us), int(hi_us) + width, width))
    counts = [have.get(e, 0) for e in edges[:-1]]
    return edges, counts


def plot_brokers(ax, series, extra, brokers, inset=True):
    """(a) S on one clock, both brokers pooled in grey, each broker's outline over it.

    15 Oct 2026, both referees (Fig. 2): the pooled bars mixed two distributions, Redis's tallest
    bin at 50--100 us and Kafka's mode near half a millisecond, so a reader could not see that
    Redis's margin is about a fifth of Kafka's (0.10 against 0.52 ms at idle, in
    docs/results/model/broker_margins.csv). Each broker is drawn as an outline on the same 50 us
    bins. The axis says what a bar counts, and a linear inset shows the bins within half a
    millisecond of zero, where the log axis makes a tail of hundreds look like the body.
    """
    pooled = [(lo, c) for lo, _hi, c in series["ack"] if VIEW_LO_US <= lo < VIEW_HI_US]
    ax.bar([lo for lo, _ in pooled], [c for _, c in pooled], width=50, align="edge",
           color=POOLED, linewidth=0, label="both brokers", zorder=1)
    for key, name, colour in BROKERS:
        edges, counts = _steps(brokers[key], VIEW_LO_US, VIEW_HI_US)
        ax.stairs(counts, edges, color=colour, linewidth=0.9, label=name, zorder=3)
    send = [(lo, c) for lo, _hi, c in series["send"] if VIEW_LO_US <= lo < VIEW_HI_US]
    # "$D$" alone: the caption says it never falls below zero, and the long label made the
    # legend tall enough to cover every peak (15 Oct 2026, below).
    ax.step([lo for lo, _ in send], [c for _, c in send], where="post", color=INK,
            linewidth=0.8, linestyle=(0, (2.5, 1.5)), label="$D$", zorder=2)
    ax.axvline(0, color="#777777", linewidth=0.8, linestyle=(0, (3, 2)), zorder=2)
    ax.set_xlim(VIEW_LO_US, VIEW_HI_US)
    ax.set_yscale("log")
    ax.set_ylim(1, PANEL_A_TOP)
    # 8 pt, as the paper's other figures and its captions are; the label carrying subscripts at
    # MATH_PT, so that its subscripts print at 6.5 pt rather than 5.6 (15 Oct 2026, an internal
    # review of the printed figures).
    ax.set_xlabel("$S = t_{\\mathrm{recv}} - t_{\\mathrm{ack}}$ (µs)", fontsize=MATH_PT)
    ax.set_ylabel("messages per 50 µs bin\n(log scale)", fontsize=8)
    ax.tick_params(labelsize=8)
    # The counts written out, "10k" as the inset's "50k" is: as 10^n the exponent printed at
    # 5.6 pt once the ticks were set at 8 pt.
    ax.yaxis.set_major_formatter(FuncFormatter(figure_style.plain_log_label))
    negative, total = below_zero(series, extra)
    # 15 Oct 2026: one line, for the page budget; the caption gives the counts outside the
    # window (outside_window, through the ledger).
    ax.set_title("(a) {:,} below zero, {:.2f}% of {:,}".format(
        negative, 100.0 * negative / total, total), fontsize=8, loc="left")
    # 15 Oct 2026, two internal reviews: one column of four long entries hid everything above
    # about 10^4 between -0.3 and +4.9 ms, both brokers' peaks and D's among them, and cut each
    # outline flat at its edge. Two columns of short entries stand above every bin, which
    # figure_collisions.data_under_legends now holds the figure to.
    handles, labels = ax.get_legend_handles_labels()
    by = dict(zip(labels, handles))
    order = ["Kafka", "Redis", "$D$", "both brokers"]
    ax.legend([by[k] for k in order], order, ncol=2, fontsize=8, loc="upper right",
              frameon=True, framealpha=1.0, edgecolor="none", handlelength=1.0,
              handletextpad=0.4, columnspacing=1.0, borderaxespad=0.3, labelspacing=0.3)
    if inset:
        _linear_inset(ax, series, brokers)


def _linear_inset(ax, series, brokers):
    """The bins within INSET_US of zero on a linear count axis, in the upper left of (a)."""
    # Placed over the quiet bins far below zero, and high enough that its tick labels clear the
    # outlines' bump near -0.5 ms; its count axis on the right, away from the main axis's own.
    # 15 Oct 2026: narrower and further left since the panel was shortened to 3.6 in, where the
    # count label on its right ran under the legend's frame.
    sub = ax.inset_axes([0.08, 0.585, 0.26, 0.355])
    sub.yaxis.tick_right()
    pooled = [(lo, c) for lo, _hi, c in series["ack"] if -INSET_US <= lo < INSET_US]
    sub.bar([lo for lo, _ in pooled], [c for _, c in pooled], width=50, align="edge",
            color=POOLED, linewidth=0)
    for key, _name, colour in BROKERS:
        edges, counts = _steps(brokers[key], -INSET_US, INSET_US)
        sub.stairs(counts, edges, color=colour, linewidth=0.9)
    sub.axvline(0, color="#777777", linewidth=0.8, linestyle=(0, (3, 2)))
    sub.set_xlim(-INSET_US, INSET_US)
    sub.set_ylim(0, 1.12 * max(c for _, c in pooled))
    sub.set_xticks([-INSET_US, 0, INSET_US])
    sub.yaxis.set_major_formatter(FuncFormatter(_thousands))
    # One labelled count, away from the corner: a "0" there sat on the x axis's "-500".
    sub.set_yticks([50000])
    sub.tick_params(labelsize=8, length=2, pad=1)
    # Inside, over the quiet bins left of zero, where no outline reaches.
    sub.text(0.05, 0.93, "linear", transform=sub.transAxes, fontsize=8, color=INK,
             ha="left", va="top")
    return sub


def plot_rate_by_load(axes, runs):
    """(b) Each run's negative-span rate against the client machine's utilization.

    15 Oct 2026, referee B (Fig. 2): the pooled share mixes brokers and loads, and one look at
    the per-run rate against utilization, by broker and priority, shows the rate rising with
    load at normal priority and staying low at real-time priority. The runs are E-A3's load
    ladder and the eight matched pairs of E-A5, E-A5b and E-A7, 25 runs a configuration on each
    broker (manipulation_runs.rate_by_load). Runs of one configuration share its utilization,
    so each is set a little to the side, by a fixed offset that depends on its order alone.
    """
    for ax, (key, name, _colour) in zip(axes, BROKERS):
        mine = [r for r in runs if r["backend"] == key]
        for prio, label, colour, marker in PRIORITIES:
            pts = sorted((r for r in mine if r["priority"] == prio),
                         key=lambda r: (r["campaign"], r["cell"], r["run"]))
            xs, ys, seen = [], [], {}
            for r in pts:
                cell = (r["campaign"], r["cell"])
                i = seen.get(cell, 0)
                seen[cell] = i + 1
                xs.append(100.0 * r["rho"] + ((i % 7) - 3) * 0.55)
                ys.append(r["rate"])
            ax.scatter(xs, ys, s=7, marker=marker, color=colour, alpha=0.55, linewidths=0,
                       label=label, zorder=3)
        ax.set_xlim(-6, 106)
        ax.set_ylim(*PANEL_B_YLIM)
        ax.set_xticks([0, 50, 100])
        ax.set_title(name, fontsize=8, loc="left")
        ax.set_xlabel("client utilization (%)", fontsize=8)
        ax.tick_params(labelsize=8)
        ax.grid(alpha=0.25, lw=0.5)
    axes[0].set_ylabel("per-run rate of\n$S$ below zero", fontsize=8)
    axes[1].tick_params(labelleft=False)
    handles = [plt.Line2D([], [], marker=m, linestyle="none", color=c, markersize=4)
               for _p, _l, c, m in PRIORITIES]
    # 15 Oct 2026, three internal reviews: in the Redis panel the legend hid its highest run
    # (0.42 at 88%). In the Kafka panel's upper left no run reaches it: every run below 55%
    # utilization stays under 0.1.
    axes[0].legend(handles, [label for _p, label, _c, _m in PRIORITIES], fontsize=8,
                   loc="upper left", frameon=True, framealpha=1.0, edgecolor="none",
                   handletextpad=0.2, borderaxespad=0.2, labelspacing=0.25,
                   borderpad=0.3, handlelength=1.0)


def build_two_ways(out_dir=OUT_DIR):
    """Panels (a) and (b) alone, side by side: the paper's first figure since v5.

    An outside editor's reading (28 Sep) asked for one exhibit on page 1 that shows both
    failures on one population, and pointed at this figure's first two panels: the red bars
    below zero are the first failure and the shaded cut is the second. Panel (c), the five
    dispositions, stays in the supplement's three-panel version. The titles are shorter here
    because each panel has half the width.
    """
    figure_style.apply()
    series, extra = read_hist()
    stats = read_stats()
    fig = plt.figure(figsize=(7.16, 2.15))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.3, 1.0], wspace=0.28)
    left = fig.add_subplot(gs[0, 0])
    right = fig.add_subplot(gs[0, 1])
    plot_measured(left, series, extra)
    plot_grid(right, stats)
    # Headroom above the data for the notes each panel carries: at half the width they would
    # otherwise sit on the orange curve in (a) and on the 0 ms bar in (b).
    left.set_ylim(1, 3e6)
    right.set_ylim(0, 1.65 * max(p.get_height() for p in right.patches))
    left.set_title("(a) Nanosecond timestamps, one clock", fontsize=8, loc="left")
    right.set_title("(b) The same spans, millisecond timestamps", fontsize=8, loc="left")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    # The stem is written out whole: the compliance gate finds a figure's generator by its
    # quoted name, and a name assembled from parts is a figure no script visibly builds.
    stem = "two_ways"
    made = []
    for ext in ("pdf", "png"):
        path = os.path.join(out_dir, "%s.%s" % (stem, ext))
        fig.savefig(path, bbox_inches="tight", pad_inches=0.02,
                    dpi=200 if ext == "png" else None)
        made.append(path)
    plt.close(fig)
    return made


def build_s_distribution(out_dir=OUT_DIR, runs=None):
    """Panel (a) alone, at column width: the distribution of S, the paper's Fig. 2 since 5 Oct 2026.

    The paper opens its results on the distribution of S = t_recv - t_ack, which would be zero in
    the ideal case, so its figure shows that distribution and the end-to-end latency of the same
    messages, and nothing else. The millisecond panel stays in the three-panel version.
    """
    # 15 Oct 2026, both referees: (a) each broker's outline over the pooled bars, the axis
    # naming what a bar counts, and a linear inset around zero; (b) each run's rate against the
    # client machine's utilization, by broker and priority. A panel, not a figure: the paper's
    # count of figures does not change. Drawn at the column width it prints at, and held to all
    # three figure gates before it is written, as make_result_figures._save holds its figures.
    import figure_collisions
    import figure_vocabulary
    import manipulation_runs
    figure_style.apply()
    series, extra = read_hist()
    brokers, _broker_extra = read_broker_hist()
    # Saved whole, not cropped (15 Oct 2026): the file is the canvas, exactly the column's
    # 3.5 in, so the page prints it at its own size and its type at the size it is set in. A
    # tight crop made the file as wide as its ink, 3.61 in once (the page shrank the 8 pt type to
    # 7.8 pt) and 3.47 in later (the page enlarged the figure and it printed 5 pt taller), and
    # the gates, which measure the canvas, saw neither. The margins hold every label inside the
    # canvas, and figure_collisions checks that none is cut by its edge.
    fig = plt.figure(figsize=S_DISTRIBUTION_IN)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.45, 1.0], hspace=0.58, wspace=0.08,
                          left=0.185, right=0.985, top=0.948, bottom=0.11)
    top = fig.add_subplot(gs[0, :])
    plot_brokers(top, series, extra, brokers)
    left = fig.add_subplot(gs[1, 0])
    right = fig.add_subplot(gs[1, 1], sharey=left)
    plot_rate_by_load((left, right),
                      manipulation_runs.rate_by_load() if runs is None else runs)
    left.set_title("(b) Kafka", fontsize=8, loc="left")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    # The stem is written out whole, as for two_ways, so the compliance gate can find it.
    stem = "s_distribution"
    figure_collisions.check(fig, stem, whole_canvas=True)
    figure_legibility.check(fig, stem)
    figure_vocabulary.check(fig, stem)
    made = []
    for ext in ("pdf", "png"):
        path = os.path.join(out_dir, "%s.%s" % (stem, ext))
        figure_style.save_whole(fig, path, dpi=200 if ext == "png" else None)
        made.append(path)
    plt.close(fig)
    return made


def build(out_dir=OUT_DIR, talk=False):
    figure_style.apply()
    series, extra = read_hist()
    stats = read_stats()

    if talk:
        # A slide is wide and is read from three metres away. Three panels in a row is right.
        fig, axes = plt.subplots(1, 3, figsize=(12.0, 3.6))
        top, left, right = axes
    else:
        # Double-column width is 7.16in, and three panels across it gives each about two
        # inches -- at which point panel (b)'s fifteen tick labels and panel (c)'s five
        # two-line labels overlap each other and the annotations land on the bars. This is
        # the Figure 5 failure again: label rows need a fixed width whatever the panel gets.
        # So the distribution, which needs the width, takes the whole top row, and the two
        # categorical panels share the bottom.
        fig = plt.figure(figsize=(7.16, 4.6))
        gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.0], hspace=0.55, wspace=0.30)
        top = fig.add_subplot(gs[0, :])
        left = fig.add_subplot(gs[1, 0])
        right = fig.add_subplot(gs[1, 1])

    plot_measured(top, series, extra)
    plot_grid(left, stats)
    plot_strategies(right, stats)
    if talk:
        fig.tight_layout()

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    stem = "deletion_histogram_talk" if talk else "deletion_histogram"
    made = []
    for ext in (("png",) if talk else ("pdf", "png")):
        path = os.path.join(out_dir, "%s.%s" % (stem, ext))
        fig.savefig(path, bbox_inches="tight", pad_inches=0.02,
                    dpi=200 if ext == "png" else None)
        made.append(path)
    plt.close(fig)
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description="Draw the deletion histogram")
    ap.add_argument("--talk", action="store_true", help="slide proportions, PNG only")
    ap.add_argument("--two", action="store_true",
                    help="panels (a) and (b) only, side by side (two_ways)")
    ap.add_argument("--s-distribution", action="store_true",
                    help="panel (a) alone at column width, as the paper's Fig. 2 (s_distribution)")
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args(argv)
    if args.s_distribution:
        made = build_s_distribution(args.out_dir)
    elif args.two:
        made = build_two_ways(args.out_dir)
    else:
        made = build(args.out_dir, talk=args.talk)
    for path in made:
        print("wrote %s" % path)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
