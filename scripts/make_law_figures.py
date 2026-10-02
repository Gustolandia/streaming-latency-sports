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
warning -- a pause held a message, the brake would have stopped on it, its conditions sat far
from its fellows', or its recording disturbed it -- is ringed, one shape per reason. The marks
are read by law_runs.py from the repository's own files, never by eye.

Figures (stems):
  law_slice     L1 on the first x86 pair and L4 on the Arm pair: the slice, both backends
  law_tick      L2 (the tick), L5 (the core count) and L7 (go-first priority)
  law_load      L3 (load), five campaigns, and L8 (the client's language), two pairs
  law_a9        L9, three pairs, both backends, 75 and 88% load

Panel titles use the supplement's L-labels. The registry, the judged records and the plan name
the same blocks A1 to A9, which is what each panel's `block` matches on.

CLI:
    python scripts/make_law_figures.py --out docs/results/figures
"""
import argparse
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

import law_runs  # noqa: E402

#: The pairs as the figures name them. "Arm64" rather than the processor family's bare name: the
#: figure vocabulary gate bans the word the manuscript retired for a configuration.
PAIR_LABELS = {"matched": "first x86", "matched-b": "second x86", "arm": "Arm64"}
PALETTE = ("#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02", "#a6761d")

#: How each counted run's warning is ringed: marker, size, edge colour.
RINGS = {"paused": ("o", 90, "#d62728"), "flagged": ("D", 80, "#000000"),
         "far": ("s", 80, "#ff7f0e"), "traced": ("o", 45, "#7f7f7f")}
#: In the manuscript's names (1 Oct): the plan's "got-it" is the acknowledgment lag, and a
#: duration is the delivery time, never the bare "delivery". The square's entry is set on two
#: lines, broken where the saved file stays the width it was. The legend overhangs the 6.5 in
#: canvas and the tight crop keeps what overhangs, so the legend's width is the file's: on one
#: line the file grew from 7.16 to 8.17 in and printed in the supplement's 7.16 in column at
#: 88% of its authored type; broken after "lag" it shrank to 6.69 in and the 8.6 in figures
#: printed 43 pt taller, more than law_tick's float page has room for. Neither gate can see
#: either, since both measure the canvas. Broken here the file is 7.23 in, as near the old
#: width as a break gets.
RING_LABELS = {"paused": "ringed red: a pause held a message over 150 ms",
               "flagged": "diamond: the lag brake would have stopped it",
               "far": "square: delivery time, acknowledgment lag or held delay\nfar from its "
                      "fellows'",
               "traced": "ringed gray: L9's traced half"}


def variable(run, by):
    """The value a panel colours a run by."""
    if by == "client":
        return "%s%s" % (run["language"].capitalize(), ", go-first" if run["priority"] else "")
    if by == "priority":
        return "go-first" if run["priority"] else "ordinary"
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
    ax.set_xlabel("Delivery time, the run's median (ms)", fontsize=8)
    ax.set_ylabel("Negative rate", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(True, alpha=0.3)
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
                      label="cross: not counted (a condition did not take, or the brake stopped it)"),
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
                      "title": "(g) L8, Arm64, Kafka"}]},
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


def main(argv=None):
    figure_style.apply()   # in force when the artists are made, not merely at import
    ap = argparse.ArgumentParser(description="The law campaign's runs, every aberration marked")
    ap.add_argument("--out", default="docs/results/figures")
    ap.add_argument("--only", default=None, help="one stem of FIGURES")
    args = ap.parse_args(argv)
    runs = law_runs.load()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for stem, spec in FIGURES.items():
        if args.only and args.only != stem:
            continue
        fig, _ = figure(runs, stem, spec)
        for ext in ("pdf", "png"):
            figure_collisions.check(fig, stem)
            figure_legibility.check(fig, stem)
            fig.savefig(out / ("%s.%s" % (stem, ext)), dpi=200, bbox_inches="tight")
        plt.close(fig)
        print("OK wrote %s/%s.pdf and .png" % (out, stem))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
