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

The paper's Fig. 3 (residual_wait) is panel (a) at column width: since 15 Oct 2026 each part is a
thin line, their median a bold one, and an inset draws the tail past 3 ms on a log axis.

Sources (all written by a9_decompose.py):
    docs/results/law/strange-results-28-sep/ack_waits.csv        S(x) for each part
    docs/results/law/strange-results-28-sep/a9_summary.json      waits in bins, by what began them
    docs/results/law/strange-results-28-sep/ack_wait_shape.json  each part's acknowledgments

Written beside them (15 Oct 2026), for the caption to give through the ledger:
    docs/results/law/strange-results-28-sep/ack_share_past_1ms.json  the share of acknowledgments
        still waiting at 1 ms, the point every part is divided by, per part and per broker

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
import statistics
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
from matplotlib.ticker import FixedFormatter, FixedLocator, NullLocator  # noqa: E402

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


#: The paper's column-width panel (6 Oct 2026; redrawn 15 Oct 2026). One colour a broker, not a
#: machine, so that its legend holds five short entries at 3.5 in.
PAPER_STEM = "residual_wait"
BROKER_STYLE = {"kafka": ("Kafka", "#1f77b4"), "redis": ("Redis", "#d62728")}
#: The median of the parts, bold, with a dot at each wait it is read at, so that it reads as data
#: and is not taken for the solid model curve it follows.
MEDIAN_STYLE = dict(color="black", linewidth=1.2, marker="o", markersize=2.4)
#: The tail inset, in the main panel's own coordinates: right of the legend and above the
#: whole-slice curve's plateau, where no part reaches. The card behind it is wider, so that the
#: main panel's grid does not run through the inset's tick labels.
TAIL_INSET = (3.45, 1.14, 1.67, 0.84)
TAIL_CARD = (3.15, 0.93, 2.01, 1.08)
TAIL_X_MS = (3.0, 5.1)
TAIL_Y = (0.004, 0.6)


def normalised(points):
    """(waits, shares over the share at 1 ms) of one part."""
    at_one = dict(points)[1.0]
    return [x for x, _ in points], [share / at_one for _, share in points]


def median_shares(parts):
    """(waits, the median over the parts of each part's normalised share at that wait)."""
    found = {}
    for points in parts.values():
        for x, y in zip(*normalised(points)):
            found.setdefault(x, []).append(y)
    xs = sorted(found)
    return xs, [statistics.median(found[x]) for x in xs]


def _draw_survival(ax, parts, s, h, log=False):
    """The two shapes, every part thin in its broker's colour, and the parts' median bold.

    Returns {legend label: artist}. On a log axis a shape's zero is left undrawn, so that its
    curve ends where it leaves the axis rather than being joined to the floor.
    """
    drawn = {}
    xs = [0.01 * k for k in range(0, 521)]
    for name, (colour, style) in sorted(SHAPE_STYLE.items()):
        shape = a9_decompose.WAIT_SHAPES[name]
        ys = [shape(x, s, h) / shape(1.0, s, h) for x in xs]
        if log:
            ys = [y if y > 0 else float("nan") for y in ys]
        drawn[name], = ax.plot(xs, ys, color=colour, linestyle=style, linewidth=1.5,
                               zorder=1)
    for (_pair, backend, _load), points in sorted(parts.items()):
        label, colour = BROKER_STYLE.get(backend, (backend.capitalize(), "#7f7f7f"))
        drawn[label], = ax.plot(*normalised(points), color=colour, linewidth=0.6, alpha=0.6,
                                zorder=2)
    drawn["median"], = ax.plot(*median_shares(parts), zorder=3, **MEDIAN_STYLE)
    return drawn


def plot_survival_compact(ax, parts, s=a9_decompose.A9_SLICE_MS, h=a9_decompose.A9_TICK_MS):
    """Panel (a) for the paper: the two shapes, every part as a thin line, and their median.

    15 Oct 2026, both referees: twenty-four marker series smeared into one band, so each of the
    twelve parts is now a thin line in its broker's colour (one referee's form), with the
    parts' median bold over them (the other's), and the spread across parts shows against the
    two shapes. The tail past s + h, which the rest-of-a-slice shape sets at zero and a linear
    axis hides, is drawn again in an inset on a log axis. Returns the inset.
    """
    drawn = _draw_survival(ax, parts, s, h)
    # The slice and a tick past it, stopped under the inset so that neither runs between the
    # inset's tick labels.
    for x in (s, s + h):
        ax.plot([x, x], [-0.06, 1.05], color="#bbbbbb", linewidth=0.8, zorder=0)
    ax.set_xlim(0, 5.2)
    # Room above the data for the legend and the inset, clear of the whole-slice curve, whose
    # turn at the slice is what tells the two shapes apart.
    ax.set_ylim(-0.06, 2.05)
    ax.set_yticks([0.0, 0.5, 1.0, 1.5])
    # 8 pt, as the paper's other figures and its captions are: at the pinned default the ticks
    # and axis labels printed at 10.1 pt beside 8 pt legends (15 Oct 2026, an internal review).
    ax.set_xlabel("Wait for a core, $x$ (ms)", fontsize=8)
    ax.set_ylabel("Share still waiting at $x$,\nrelative to 1 ms", fontsize=8)
    ax.tick_params(labelsize=8)
    # 8 pt, IEEE's floor; it was drawn at 7 before the paper included it, when the legibility
    # gate had no width to check it at.
    order = ["rest of a slice", "whole slice", "median"] + sorted(
        label for label in drawn if label not in SHAPE_STYLE and label != "median")
    # A broker's entry is a sample of its colour, opaque and of a weight the eye can find: drawn
    # as its parts are, 0.6 pt at 60% opacity, it was the faintest line in the legend.
    handles = [drawn[label] if label in SHAPE_STYLE or label == "median"
               else plt.Line2D([], [], color=drawn[label].get_color(), linewidth=1.2)
               for label in order]
    ax.legend(handles, order, loc="upper left", fontsize=8,
              framealpha=1.0, ncol=2, columnspacing=0.8, handletextpad=0.4,
              handlelength=1.6, borderaxespad=0.3, labelspacing=0.3)
    ax.grid(True, alpha=0.3)
    x0, y0, width, height = TAIL_CARD
    ax.add_patch(plt.Rectangle((x0, y0), width, height, facecolor="white", edgecolor="none",
                               zorder=1.6))
    tail = ax.inset_axes(list(TAIL_INSET), transform=ax.transData)
    _draw_survival(tail, parts, s, h, log=True)
    tail.set_yscale("log")
    tail.set_xlim(*TAIL_X_MS)
    tail.set_ylim(*TAIL_Y)
    tail.axvline(s + h, color="#bbbbbb", linewidth=0.8, zorder=0)
    tail.set_xticks([3, 4, 5])
    tail.yaxis.set_major_locator(FixedLocator([0.01, 0.1]))
    tail.yaxis.set_major_formatter(FixedFormatter(["0.01", "0.1"]))
    tail.yaxis.set_minor_locator(NullLocator())
    tail.tick_params(labelsize=8, length=2, pad=1.5)
    tail.grid(True, alpha=0.3)
    return tail


#: The paper panel's canvas: the column's 3.5 in exactly, saved whole (15 Oct 2026).
PAPER_IN = (3.5, 2.0)


def build_paper_panel(waits, out_dir):
    """The residual-wait figure the paper prints in Section IV-C, at column width.

    Drawn at the column's 3.5 in and saved whole, so that the file is the canvas and prints at
    full size, neither enlarged nor shrunk. Cropped to its ink with 0.02 in around it, it came
    out 3.46 in and the page enlarged it 1.2%, which printed it 1.8 pt taller (15 Oct 2026).
    """
    figure_style.apply()
    parts = load_waits(waits)
    fig, ax = plt.subplots(figsize=PAPER_IN)
    plot_survival_compact(ax, parts)
    fig.tight_layout(pad=0.15)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        figure_collisions.check(fig, PAPER_STEM, whole_canvas=True)
        figure_legibility.check(fig, PAPER_STEM)
        figure_style.save_whole(fig, out / ("%s.%s" % (PAPER_STEM, ext)), dpi=200)
    plt.close(fig)
    return out / ("%s.pdf" % PAPER_STEM)


#: The data file of the share of acknowledgments past 1 ms, beside the waits it is read from.
SHARE_FILE = "ack_share_past_1ms.json"
#: Below this many acknowledgments, a part's count past 1 ms is recovered exactly from its share,
#: which ack_waits.csv keeps to six decimals: the rounding moves the count by under a half.
EXACT_BELOW = 1000000


def load_acks(path):
    """{(pair, backend, load): acknowledgments} from ack_wait_shape.json."""
    with open(path, encoding="utf-8") as fh:
        found = json.load(fh)["parts"]
    return dict((tuple(name.split(", ")), part["acks"]) for name, part in found.items())


def _pooled(rows):
    past, acks = sum(r["past"] for r in rows), sum(r["acks"] for r in rows)
    shares = [r["share"] for r in rows]
    return {"parts": len(rows), "acks": acks, "past": past, "share": past / float(acks),
            "share_lo": min(shares), "share_hi": max(shares)}


def share_past(parts, acks, at_ms=1.0):
    """The share of acknowledgments still waiting at `at_ms`, the point Fig. 3 divides by.

    15 Oct 2026, a referee: the caption normalises at 1 ms but never said how much of the
    distribution that is. Per part, the count is recovered from the share and the part's
    acknowledgments; per broker, and per broker and load, the counts are pooled, with the
    range of the parts' shares beside them.
    """
    rows = {}
    for key, points in sorted(parts.items()):
        if key not in acks:
            raise ValueError("no acknowledgment count for part %s" % ", ".join(key))
        if acks[key] >= EXACT_BELOW:
            raise ValueError("part %s has %d acknowledgments, too many to recover its count "
                             "from a share kept to six decimals" % (", ".join(key), acks[key]))
        share = dict(points)[at_ms]
        rows[key] = {"acks": acks[key], "past": int(round(share * acks[key])), "share": share}
    by_broker, by_load = {}, {}
    for (pair, backend, load), row in rows.items():
        by_broker.setdefault(backend, []).append(row)
        by_load.setdefault("%s, %s" % (backend, load), []).append(row)
    return {"at_ms": at_ms,
            "what": "the share of acknowledgments whose thread was still waiting for a core "
                    "at at_ms, the point Fig. 3 divides every part's shares by: per part, "
                    "pooled per broker and per broker and load, with the range over parts",
            "parts": dict((", ".join(key), row) for key, row in rows.items()),
            "by_broker": dict((b, _pooled(r)) for b, r in sorted(by_broker.items())),
            "by_broker_and_load": dict((k, _pooled(r)) for k, r in sorted(by_load.items())),
            "all": _pooled(list(rows.values()))}


def write_share(found, path):
    """Write the share past 1 ms where emit_paper_numbers.py can read it."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(found, indent=1, sort_keys=True) + "\n")
    return path


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
    ap.add_argument("--shape", default=None,
                    help="ack_wait_shape.json, each part's acknowledgments (beside --waits by "
                         "default)")
    ap.add_argument("--share-out", default=None,
                    help="where the share of acknowledgments past 1 ms is written (beside "
                         "--waits by default)")
    args = ap.parse_args(argv)

    parts, bins = load_waits(args.waits), load_bins(args.summary)
    # The share Fig. 3 divides by, beside the waits it is read from (15 Oct 2026), for the
    # caption to give through the ledger.
    beside = os.path.dirname(os.path.abspath(args.waits))
    share = share_past(parts, load_acks(args.shape
                                        or os.path.join(beside, "ack_wait_shape.json")))
    print("OK wrote %s" % write_share(share, args.share_out or os.path.join(beside, SHARE_FILE)))
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
