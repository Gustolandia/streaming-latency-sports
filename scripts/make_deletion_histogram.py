#!/usr/bin/env python3
"""
make_deletion_histogram.py
Draw what the instrument deletes, next to what it then reports.

Origin. A co-author (D. Gregg, 2026-08-26) pointed at the OpenMessaging Benchmark's own
published latency distribution and said: plot that on our data and a whole population sits left
of zero; then plot it again as the software leaves it once that population is discarded, and the
two graphs do not look alike. He asked, in the same message, for the impact of the *various*
strategies for handling such samples. This figure is that, in three panels.

Every number here is emitted by `span_histogram.py` from the archived corpus (5,913 runs,
738,730 joined events) and read from the committed CSV and JSON, so the figure builds without
the 800 MB archive.

What the three panels say, in order:

  (a) At nanosecond resolution the acknowledgment-referenced span really does go below zero,
      62,264 times in 738,730. The send-referenced span, on the same events and the same clock,
      never does. That contrast is the control: the negatives are a property of which stamp is
      used as the origin, not of the delivery being timed.

  (b) A millisecond instrument does not see panel (a). It differences two truncated stamps, so a
      sub-millisecond interval lands on 0 or on 1 depending only on where the tick boundaries
      fall -- the bimodal 0/1 split is that arithmetic, visible raw. The benchmark then admits a
      sample only when the difference is strictly positive, which deletes everything at or below
      zero: 338,242 of 738,730, or 45.8 per cent, none of it counted in what is reported.

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

import figure_style

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

HIST_CSV = os.path.join("docs", "results", "span_histogram.csv")
STATS_JSON = os.path.join("docs", "results", "span_histogram_stats.json")
OUT_DIR = os.path.join("docs", "results", "figures")

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
    ax.set_xlabel("measured span (us)")
    ax.set_ylabel("events (log)")
    # The window caveat rides in the title. Below the axis it sat on the x-label; inside the
    # panel it sat on the bars, in grey on dark red. A title has room and nothing to collide
    # with, and the caveat is about the panel as a whole rather than about any point in it.
    above = extra["ack"]["over"]
    # Short form: the long sentence fitted the two-row paper layout, where panel (a) spans the
    # full width, and ran into panel (b)'s title in the three-across slide layout.
    ax.set_title("(a) as measured, one clock, nanosecond stamps  (+%s above window)"
                 % "{:,}".format(above), fontsize=8, loc="left")

    ax.text(0.03, 0.95, "62,264 below zero\n(8.43% of 738,730)",
            transform=ax.transAxes, fontsize=7, color=CUT, va="top", ha="left")
    ax.text(0.97, 0.95, "send-referenced span\non the same events:\nnever below zero",
            transform=ax.transAxes, fontsize=7, color=REDIS, va="top", ha="right")


def plot_grid(ax, stats):
    """(b) the same events as a millisecond instrument holds them, and the guard's cut."""
    table = stats["spans"]["ack"]["ms_table"]
    xs = list(range(MS_LO, MS_HI + 1))
    ys = [table.get(str(x), 0) for x in xs]
    colours = [CUT if x <= 0 else KEPT for x in xs]
    ax.bar(xs, ys, width=0.82, color=colours, linewidth=0)

    ax.set_xlim(MS_LO - 0.6, MS_HI + 0.6)
    ax.set_xticks(xs)
    ax.set_xlabel("millisecond-differenced span (ms)")
    ax.set_ylabel("events")
    ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
    ax.set_title("(b) as a millisecond instrument holds it", fontsize=8, loc="left")

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
            "guard admits\nonly > 0:\ndeletes %.1f%%\n(%s events)"
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
    ax.set_title("(c) five dispositions, one population", fontsize=8, loc="left")
    ax.legend(handles=[
        plt.Rectangle((0, 0), 1, 1, color=KEPT),
        plt.Rectangle((0, 0), 1, 1, color=GREY),
    ], labels=["nanosecond stamps", "millisecond stamps"], fontsize=6,
        loc="lower left", frameon=False, ncol=1)


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
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args(argv)
    for path in build(args.out_dir, talk=args.talk):
        print("wrote %s" % path)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
