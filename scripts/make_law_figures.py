#!/usr/bin/env python3
"""
make_law_figures.py
Supplement figures for the pre-registered law campaign (Part V): every run of every block, at the
delivery it had and the negative rate it measured, with every aberrant run marked and the reason it is
marked in the legend.

A pre-registered campaign is judged on the runs its rules count, and a reader should be able to
see the others too: where they sat, and why each was set apart or kept with a warning beside it.
So nothing is dropped from these panels. A run the integrity rule did not count is drawn as a
cross in its own colour; a run of a false start as a plus; and a counted run that carries a
warning -- a pause held a message, the stopping rule would have stopped on it, its conditions sat far
from its fellows', or its recording disturbed it -- is ringed, one shape per reason. The marks
are read by law_runs.py from the repository's own files, never by eye.

Figures (stems):
  law_slice     L1 on the first x86 pair and L4 on the Arm pair: the slice, both backends
  law_tick      L2 (the tick), L5 (the core count) and L7 (real-time priority)
  law_load      L3 (load), five campaigns, and L8 (the client's language), two pairs
  law_a9        L9, three pairs, both backends, 75 and 88% load
  law_slice_halfway  (15 Oct 2026) L1 and L4 again, as the judges read them: where each slice's
                fall is halfway down, free and fitted, against the band [s, s + h]; recomputed
                from the registry with the judge's own function and checked against the judged
                records under docs/results/law/judged-27-sep/all

Panel titles use the supplement's L-labels. The registry, the judged records and the plan name
the same blocks A1 to A9, which is what each panel's `block` matches on.

CLI:
    python scripts/make_law_figures.py --out docs/results/figures
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
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

import law_predictions  # noqa: E402
import law_runs  # noqa: E402
import run_integrity  # noqa: E402

#: The pairs as the figures name them. "Arm64" rather than the processor family's bare name: the
#: figure vocabulary gate bans the word the manuscript retired for a configuration.
PAIR_LABELS = {"matched": "first x86", "matched-b": "second x86", "arm": "Arm64"}
PALETTE = ("#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02", "#a6761d")

#: How each counted run's warning is ringed: marker, size, edge colour.
RINGS = {"paused": ("o", 90, "#d62728"), "flagged": ("D", 80, "#000000"),
         "far": ("s", 80, "#ff7f0e"), "traced": ("o", 45, "#7f7f7f")}
#: In the manuscript's names (3 Oct, writing standard A10, the industry's): the plan's "got-it"
#: is the publish latency, a duration is the end-to-end latency, never the bare "delivery", and
#: the plan's brake is the stopping rule. The square's entry is set on two
#: lines, broken where the saved file stays the width it was. The legend overhangs the 6.5 in
#: canvas and the tight crop keeps what overhangs, so the legend's width is the file's: on one
#: line the file grew from 7.16 to 8.17 in and printed in the supplement's 7.16 in column at
#: 88% of its authored type; broken after "lag" it shrank to 6.69 in and the 8.6 in figures
#: printed 43 pt taller, more than law_tick's float page has room for. Neither gate can see
#: either, since both measure the canvas. Broken here the file is 7.23 in, as near the old
#: width as a break gets.
RING_LABELS = {"paused": "ringed red: a pause held a message over 150 ms",
               "flagged": "diamond: the stopping rule would have stopped it",
               "far": "square: end-to-end latency, publish latency or held delay\nfar from its "
                      "fellows'",
               "traced": "ringed gray: L9's traced half"}


def variable(run, by):
    """The value a panel colours a run by."""
    if by == "client":
        return "%s%s" % (run["language"].capitalize(), ", real-time" if run["priority"] else "")
    if by == "priority":
        return "real-time" if run["priority"] else "normal"
    value = run[{"slice": "slice_ms", "tick": "tick_ms", "load": "load_pct",
                 "cpus": "cpus"}[by]]
    return value


def value_label(value, by):
    if by in ("client", "priority"):
        return value
    unit = {"slice": " ms slice", "tick": " ms tick", "load": "% load", "cpus": " CPUs"}[by]
    return "%g%s" % (value, unit)


def colours(values):
    """{value: colour}, in sorted order, from one fixed palette."""
    ordered = sorted(set(values), key=lambda v: (str(type(v)), v))
    return dict((v, PALETTE[i % len(PALETTE)]) for i, v in enumerate(ordered))


def select(runs, spec):
    """The runs a panel draws: its block, pair and backend, and a campaign filter if it has one;
    only runs that measured a trip and a rate can be drawn."""
    return [r for r in runs if r["block"] == spec["block"] and r["pair"] == spec["pair"]
            and r["backend"] == spec["backend"]
            and (not spec.get("folders") or r["folder"] in spec["folders"])
            and r["trip_median_ms"] is not None and r["rate"] is not None]


def panel(ax, runs, spec, palette=None):
    """One block's runs on one pair and backend, colored by what the block moves, every
    aberrant run marked; returns {mark: n} of what was drawn. A figure passes one palette for
    all its panels, so that a value has one colour throughout it."""
    mine = select(runs, spec)
    by = spec["by"]
    palette = palette or colours(variable(r, by) for r in mine)
    palette = dict((v, c) for v, c in palette.items() if any(variable(r, by) == v for r in mine))
    drawn = dict.fromkeys(law_runs.MARK_KEYS, 0)
    drawn["runs"] = len(mine)
    for value, colour in palette.items():
        some = [r for r in mine if variable(r, by) == value]
        kept = [r for r in some if not set(r["marks"]) & set(law_runs.OUT_MARKS)]
        ax.scatter([r["trip_median_ms"] for r in kept], [r["rate"] for r in kept], s=12,
                   color=colour, alpha=0.75, linewidths=0, zorder=2,
                   label=value_label(value, by))
        for mark, symbol in (("false start", "+"), ("repeated", "x"), ("stopped", "x")):
            out = [r for r in some if mark in r["marks"]
                   and not (mark != "false start" and "false start" in r["marks"])]
            if out:
                ax.scatter([r["trip_median_ms"] for r in out], [r["rate"] for r in out],
                           marker=symbol, s=36, color=colour, linewidths=1.2, zorder=4)
    for run in mine:
        for mark in run["marks"]:
            drawn[mark] += 1
            if mark in RINGS:
                symbol, size, edge = RINGS[mark]
                ax.scatter([run["trip_median_ms"]], [run["rate"]], marker=symbol, s=size,
                           facecolors="none", edgecolors=edge, linewidths=0.9, zorder=3)
    ax.set_title(spec["title"], fontsize=9)
    ax.set_xlabel("End-to-end latency, the run's median (ms)", fontsize=8)
    ax.set_ylabel("Negative rate", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(True, alpha=0.3)
    # A panel whose runs reach the legend's corner gets headroom over them (15 Oct 2026, when
    # figure_collisions.data_under_legends found two of L8's Arm64 runs under its legend).
    if spec.get("ylim_top"):
        ax.set_ylim(top=spec["ylim_top"])
    ax.legend(loc="upper right", fontsize=8, framealpha=1.0, handletextpad=0.2,
              borderaxespad=0.3, markerscale=1.5)
    return drawn


#: The panels' floor, in inches: room for a three-line mark legend, as it always was.
LEGEND_RESERVE_IN = 0.07 * 8.6
#: What that floor leaves between a three-line legend's top and the panels above it.
LEGEND_CLEARANCE_IN = 2.4 / 72


def mark_legend(fig, rings, y=0.0):
    """The marks, once for the figure, below its panels; returns the legend."""
    handles = [Line2D([], [], marker="x", linestyle="none", color="#333333",
                      label="cross: not counted (a condition did not take, or the stopping rule stopped it)"),
               Line2D([], [], marker="+", linestyle="none", color="#333333",
                      label="plus: a run of a false start")]
    for mark in rings:
        symbol, _, edge = RINGS[mark]
        handles.append(Line2D([], [], marker=symbol, linestyle="none", markerfacecolor="none",
                              markeredgecolor=edge, label=RING_LABELS[mark]))
    return fig.legend(handles=handles, loc="lower center", ncol=2, fontsize=8, frameon=False,
                      bbox_to_anchor=(0.5, y))


FIGURES = {
    "law_slice": {"rows": 2, "cols": 2, "height": 6.4, "rings": ("paused", "flagged", "far"),
                  "panels": [
                      {"block": "A1", "pair": "matched", "backend": "kafka", "by": "slice",
                       "title": "(a) L1, first x86, Kafka"},
                      {"block": "A1", "pair": "matched", "backend": "redis", "by": "slice",
                       "title": "(b) L1, first x86, Redis"},
                      {"block": "A4", "pair": "arm", "backend": "kafka", "by": "slice",
                       "title": "(c) L4, Arm64, Kafka"},
                      {"block": "A4", "pair": "arm", "backend": "redis", "by": "slice",
                       "title": "(d) L4, Arm64, Redis"}]},
    "law_tick": {"rows": 4, "cols": 2, "height": 8.6, "rings": ("paused", "flagged", "far"),
                 "panels": [
                     {"block": "A2", "pair": "matched", "backend": "kafka", "by": "tick",
                      "title": "(a) L2, first x86, Kafka"},
                     {"block": "A2", "pair": "matched-b", "backend": "redis", "by": "tick",
                      "title": "(b) L2, second x86, Redis"},
                     {"block": "A2", "pair": "matched-b", "backend": "kafka", "by": "tick",
                      "title": "(c) L2, second x86, Kafka, a replicate"},
                     {"block": "A5", "pair": "matched-b", "backend": "kafka", "by": "cpus",
                      "title": "(d) L5, second x86, Kafka"},
                     {"block": "A5", "pair": "matched-b", "backend": "redis", "by": "cpus",
                      "title": "(e) L5, second x86, Redis"},
                     {"block": "A7", "pair": "matched", "backend": "kafka", "by": "priority",
                      "title": "(f) L7, first x86, Kafka"},
                     {"block": "A7", "pair": "matched", "backend": "redis", "by": "priority",
                      "title": "(g) L7, first x86, Redis"}]},
    "law_load": {"rows": 4, "cols": 2, "height": 8.6, "rings": ("paused", "flagged", "far"),
                 "panels": [
                     {"block": "A3", "pair": "matched", "backend": "kafka", "by": "load",
                      "folders": ("a3_20260919T171733Z",),
                      "title": "(a) L3, first x86, Kafka, 19 Sep"},
                     {"block": "A3", "pair": "matched", "backend": "kafka", "by": "load",
                      "folders": ("a3_20260921T030021Z", "a3_20260921T032730Z"),
                      "title": "(b) L3, first x86, Kafka, 21 Sep"},
                     {"block": "A3", "pair": "matched-b", "backend": "kafka", "by": "load",
                      "folders": ("a3_20260926T033945Z",),
                      "title": "(c) L3, second x86, Kafka, 26 Sep"},
                     {"block": "A3", "pair": "matched-b", "backend": "kafka", "by": "load",
                      "folders": ("a3_20260926T185701Z",),
                      "title": "(d) L3, second x86, Kafka, its retry"},
                     {"block": "A3", "pair": "arm", "backend": "kafka", "by": "load",
                      "title": "(e) L3, Arm64, Kafka"},
                     {"block": "A8", "pair": "matched", "backend": "kafka", "by": "client",
                      "title": "(f) L8, first x86, Kafka"},
                     {"block": "A8", "pair": "arm", "backend": "kafka", "by": "client",
                      "title": "(g) L8, Arm64, Kafka", "ylim_top": 0.25}]},
    "law_a9": {"rows": 3, "cols": 2, "height": 8.6,
               "rings": ("paused", "flagged", "far", "traced"),
               "panels": [
                   {"block": "A9", "pair": pair, "backend": backend, "by": "load",
                    "title": "(%s) L9, %s, %s" % (letter, PAIR_LABELS[pair], backend.capitalize())}
                   for letter, (pair, backend) in zip("abcdef", [
                       ("matched", "kafka"), ("matched", "redis"), ("matched-b", "kafka"),
                       ("matched-b", "redis"), ("arm", "kafka"), ("arm", "redis")])]},
}


def figure(runs, stem, spec):
    """(fig, [{mark: n} per panel]) for one figure of FIGURES."""
    fig, axes = plt.subplots(spec["rows"], spec["cols"], figsize=(6.5, spec["height"]))
    flat = list(axes.flat)
    values = {}
    for p in spec["panels"]:
        values.setdefault(p["by"], set()).update(variable(r, p["by"]) for r in select(runs, p))
    palettes = dict((by, colours(some)) for by, some in values.items())
    drawn = [panel(ax, runs, p, palettes[p["by"]]) for ax, p in zip(flat, spec["panels"])]
    for ax in flat[len(spec["panels"]):]:
        ax.set_visible(False)
    # The panels stand on the legend, however tall it is. The floor was fixed, and fitted three
    # lines; L9's six marks with the square's entry on two lines make four, and the bottom
    # panels' axis labels came down to 3 pt above the legend, which read as a row of it.
    legend = mark_legend(fig, spec["rings"])
    top = legend.get_window_extent(fig.canvas.get_renderer()).y1 / fig.dpi
    floor = max(LEGEND_RESERVE_IN, top + LEGEND_CLEARANCE_IN)
    fig.tight_layout(rect=(0, floor / spec["height"], 1, 1))
    return fig, drawn


#: The journal supplement's Fig. S3 since 15 Oct 2026: for each pair and broker, where each slice's
#: fall is halfway down against the slice, beside the band [s, s + h] the law put it in. Both
#: referees found that the runs panels of `law_slice` hid what the slice does, as the slices'
#: colors overlap; one asked for this form. `law_slice` stays as it was, every run drawn and
#: marked, for Part V of the postmortem, which includes it and says so.
HALFWAY_STEM = "law_slice_halfway"
HALFWAY_PANELS = ({"block": "A1", "pair": "matched", "judged": "p1_a1",
                   "title": "(a) L1, first x86"},
                  {"block": "A4", "pair": "arm", "judged": "p9_a4", "title": "(b) L4, Arm64"})
#: The judged records the halfway points are checked against, and the campaigns they read.
JUDGED_DIR = os.path.join("docs", "results", "law", "judged-27-sep", "all")
QUALITY_CSV = os.path.join("docs", "results", "law", "judged-27-sep", "quality_by_campaign.csv")
#: The band's width, h: one tick, the 1 ms the judges were given and that the runs read back.
TICK_MS = 1.0
#: One colour and one marker a broker, filled for the free reading and open for the fitted one.
#: Redis in the red the paper and the rest of the supplement give it, not the orange it had here
#: (15 Oct 2026, two internal reviews); this figure draws none of the runs figures' red rings.
BROKERS = {"kafka": ("Kafka", "#1f77b4", "o"), "redis": ("Redis", "#d62728", "s")}


def judged_campaigns(path=QUALITY_CSV):
    """{(pair, campaign)} the judging read."""
    with open(path, newline="", encoding="utf-8") as fh:
        return set((row["pair"], row["campaign"]) for row in csv.DictReader(fh))


def curve_runs(runs, block, pair, backend, campaigns):
    """One block's runs on one pair and broker as the judges read them: counted runs of the
    judged campaigns, each with the campaign it belongs to, the trip it had and its rate."""
    return [{"trip_ms": r["trip_median_ms"], "negative_rate": r["rate"], "point": r["point"],
             "slice_ms": r["slice_ms"], "campaign": r["folder"], "backend": backend}
            for r in runs
            if r["block"] == block and r["pair"] == pair and r["backend"] == backend
            and r["verdict"] == run_integrity.COUNT and (pair, r["folder"]) in campaigns
            and r["trip_median_ms"] is not None and r["rate"] is not None]


def halfway_readings(runs, spec, judged_dir=JUDGED_DIR, campaigns=None):
    """{backend: {summary: {"halfway": {slice: ms}, "in_reach": [slices], "slope": (value, low,
    high)}}} for one panel, read the way the frozen judge reads it.

    The judged record gives the halfway points only at the slices in reach, but its slope is
    taken through every slice that has one: on the Arm pair, Kafka's 1.5 ms slice is out of
    reach and still in the slope. So the points are recomputed from the run registry with the
    judge's own function, and the figure refuses to draw unless they are the judged ones and
    give the judged slope.
    """
    campaigns = judged_campaigns() if campaigns is None else campaigns
    with open(os.path.join(judged_dir, spec["judged"] + ".json"), encoding="utf-8") as fh:
        judged = json.load(fh)["by_part"]
    found = {}
    for backend, part in sorted(judged.items()):
        mine = curve_runs(runs, spec["block"], spec["pair"], backend, campaigns)
        found[backend] = {}
        for summary, said in sorted(part["by_summary"].items()):
            halfway = law_predictions.through_the_anchor(mine, part["anchor_ms"], summary)
            judged_points = dict((float(s), ms) for s, ms in said["halfway_ms"].items())
            for s, ms in sorted(judged_points.items()):
                if ms is not None and abs(halfway.get(s, float("inf")) - ms) > 1e-9:
                    raise ValueError("%s, %s, %s: the halfway point at %g ms is not the judged one"
                                     % (spec["judged"], backend, summary, s))
            in_reach = sorted(judged_points)
            slope = law_predictions.straight_line(sorted(halfway),
                                                  [halfway[s] for s in sorted(halfway)])[0]
            if abs(slope - said["value"]) > 1e-9:
                raise ValueError("%s, %s, %s: the slope through the halfway points is %.4f, not "
                                 "the judged %.4f" % (spec["judged"], backend, summary, slope,
                                                      said["value"]))
            found[backend][summary] = {"halfway": halfway, "in_reach": in_reach,
                                       "slope": (said["value"],) + tuple(said["interval"])}
    return found


#: The slices both panels show, in ms, so that the two pairs are read on one scale. The halfway
#: axis runs 0.8 ms higher, to hold the band at the longest slice run, 6 ms.
HALFWAY_SLICES_MS = (1.0, 6.4)
#: The grey of a slice out of reach: no test of the band there, but in the judged slope.
OUT_OF_REACH = "#9a9a9a"


def _mark(colour, marker, summary, label):
    """A legend's sample of one broker's reading: filled and solid for the free reading, open
    and dashed for the fitted one."""
    return Line2D([], [], color=colour, marker=marker, markersize=5, markeredgecolor=colour,
                  markerfacecolor=colour if summary == "free" else "white", linewidth=0.9,
                  linestyle="-" if summary == "free" else (0, (3, 2)), label=label)


def plot_halfways(ax, readings, title, tick_ms=TICK_MS):
    """One pair: each broker's halfway points against the slice, over the band [s, s + h].

    Free readings filled and fitted ones open, each with the straight line the judge took its
    slope from, and a slice out of reach in grey. The legend gives each line's judged slope,
    where no point falls, above the band at the shortest slices.
    """
    lo, hi = HALFWAY_SLICES_MS
    ax.fill_between([lo, hi], [lo, hi], [lo + tick_ms, hi + tick_ms], color="#e6e6e6",
                    linewidth=0, zorder=0)
    ax.plot([lo, hi], [lo, hi], color="#666666", linewidth=0.9, zorder=1)
    handles = []
    for backend, summaries in sorted(readings.items()):
        name, colour, marker = BROKERS.get(backend, (backend.capitalize(), "#7f7f7f", "^"))
        for summary in ("free", "fitted"):
            got = summaries[summary]
            xs = sorted(got["halfway"])
            for edge, slices in ((colour, [s for s in xs if s in got["in_reach"]]),
                                 (OUT_OF_REACH, [s for s in xs if s not in got["in_reach"]])):
                ax.plot(slices, [got["halfway"][s] for s in slices], linestyle="none",
                        marker=marker, markersize=5, markeredgecolor=edge,
                        markerfacecolor=edge if summary == "free" else "white",
                        markeredgewidth=1.0, zorder=4 if edge == colour else 3)
            slope, intercept = law_predictions.straight_line(xs, [got["halfway"][s] for s in xs])
            ax.plot([xs[0], xs[-1]], [intercept + slope * xs[0], intercept + slope * xs[-1]],
                    color=colour, linewidth=0.9,
                    linestyle="-" if summary == "free" else (0, (3, 2)), zorder=2)
            handles.append(_mark(colour, marker, summary, "%s, %s %.3f"
                                 % (name, summary, got["slope"][0])))
    ax.legend(handles=handles, title="slope against $s$", loc="upper left", fontsize=8,
              title_fontsize=8, framealpha=1.0, borderaxespad=0.4, handletextpad=0.5)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi + 0.8)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=9)
    ax.set_xlabel("Slice $s$ (ms)", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(True, alpha=0.3)


def halfway_legend(fig):
    """What the grey marks and the band are, once for the figure, below its panels."""
    handles = [Line2D([], [], color=OUT_OF_REACH, marker="o", markersize=5, linestyle="none",
                      label="a slice out of reach: not tested against the band, but in the "
                            "slope"),
               Patch(facecolor="#e6e6e6", edgecolor="#666666", linewidth=0.6,
                     label="$[s, s + h]$, the slice to a tick past it")]
    return fig.legend(handles=handles, loc="lower center", ncol=2, fontsize=8, frameon=False,
                      bbox_to_anchor=(0.5, 0.0), columnspacing=1.5)


#: Fig. S3's canvas: the supplement's width, and tall enough for the two square-scaled panels.
HALFWAY_FIG_IN = (6.5, 3.9)
#: Room between the shared legend and the slice axes' labels, twice the other figures': a label
#: box sits 2.3 pt taller under CI's older matplotlib, and the two met there by 0.7 pt.
HALFWAY_CLEARANCE_IN = 2 * LEGEND_CLEARANCE_IN


def halfway_figure(runs, judged_dir=JUDGED_DIR, quality_csv=QUALITY_CSV):
    """(fig, {panel title: readings}) for Fig. S3: one panel a pair, the halfway axis shared."""
    campaigns = judged_campaigns(quality_csv)
    width, height = HALFWAY_FIG_IN
    fig, axes = plt.subplots(1, 2, figsize=(width, height), sharey=True)
    found = {}
    for ax, spec in zip(axes, HALFWAY_PANELS):
        found[spec["title"]] = halfway_readings(runs, spec, judged_dir, campaigns)
        plot_halfways(ax, found[spec["title"]], spec["title"])
    axes[0].set_ylabel("Halfway point of the rate's fall (ms)", fontsize=8)
    legend = halfway_legend(fig)
    top = legend.get_window_extent(fig.canvas.get_renderer()).y1 / fig.dpi
    fig.tight_layout(rect=(0, (top + HALFWAY_CLEARANCE_IN) / height, 1, 1), w_pad=1.0)
    return fig, found


#: Figures drawn by a function of the runs rather than from a spec of FIGURES, so that Part V's
#: rule -- every run drawn in a panel of FIGURES -- reads FIGURES alone.
EXTRA = {HALFWAY_STEM: halfway_figure}


def main(argv=None):
    figure_style.apply()   # in force when the artists are made, not merely at import
    ap = argparse.ArgumentParser(description="The law campaign's runs, every aberration marked")
    ap.add_argument("--out", default="docs/results/figures")
    ap.add_argument("--only", default=None, help="one stem of FIGURES or of EXTRA")
    args = ap.parse_args(argv)
    runs = law_runs.load()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    todo = [(stem, figure, (runs, stem, spec)) for stem, spec in FIGURES.items()]
    todo += [(stem, build, (runs,)) for stem, build in EXTRA.items()]
    for stem, build, given in todo:
        if args.only and args.only != stem:
            continue
        fig, _ = build(*given)
        for ext in ("pdf", "png"):
            figure_collisions.check(fig, stem)
            figure_legibility.check(fig, stem)
            fig.savefig(out / ("%s.%s" % (stem, ext)), dpi=200, bbox_inches="tight")
        plt.close(fig)
        print("OK wrote %s/%s.pdf and .png" % (out, stem))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
