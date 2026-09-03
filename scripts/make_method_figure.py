#!/usr/bin/env python3
"""
make_method_figure.py
Method figure: the experiment map. Which campaign manipulates what, holds what fixed, and which
claim it is the evidence for.

The paper's campaigns accumulated over three months in response to defects, so their logic is not
obvious from their names. This figure states it in one place: the manipulated variable, the
controlled variable, and the hypothesis or claim each campaign settles. A reader should be able
to check that every claim in the discussion has an experiment behind it, and that no experiment is
doing double duty as both the source of a hypothesis and its test.

CLI:
    python scripts/make_method_figure.py --out docs/results/figures
"""
import argparse
import math
from pathlib import Path

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib
matplotlib.use("Agg")
import figure_style  # noqa: E402
figure_style.apply()  # Type 42, IEEE-listed family; see scripts/figure_style.py
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

def _transport_span():
    """How far E-A10 moved the transport, from the campaign rather than from memory.

    This map is drawn into the supplement, so its cells are published numbers. Round 34 found
    the payload sweep's transport ratio typed in twenty places across the two documents, the
    figure scripts and this table; every copy was correct, which is why none of them ever
    failed. The fallback equals what the derivation returns for the committed campaign, so a
    reader without the artefact gets the published figure rather than a different one --- the
    same bargain `_base_slice_ms` makes in `make_paper_figures`.
    """
    try:
        import stat_intervals
        return "%.0f" % round(stat_intervals.payload_span()["transport_factor"])
    except (ImportError, OSError, KeyError, ValueError):
        return "77"


def _priority_range():
    """E-A5's collapse factor across every matched pair, as the map prints it.

    `\\rtFactorLow`--`\\rtFactorHigh` over `\\rtPairs` pairs in the ledger. The map said
    "8 pairs, 7-80x".
    """
    try:
        import priority_pairs
        s = priority_pairs.summary()
        return "%d pairs, %.0f-%.0fx" % (s["pairs"], s["factor_low"], s["factor_high"])
    except (ImportError, OSError, KeyError, ValueError):
        return "8 pairs, 7-80x"


def _geometry_result():
    """E-A6's two factors and the utilization both arms reached.

    `\\GeomOrigFactor`, `\\GeomReplFactor` and the shared rho. The factors are derived the
    same way `emit_paper_numbers` derives them --- `ratio_z` over the two cells --- so the
    cell and the macro cannot disagree about what the ratio is.
    """
    try:
        import stat_intervals
        out = []
        for phase in ("ea6", "ea6b"):
            (_, kc, nc), (_, ks, ns) = stat_intervals.geometry_cells(phase)
            out.append(stat_intervals.ratio_z(ks, ns, kc, nc)[1])
        return "%.2fx, %.2fx, at rho %g" % (out[0], out[1],
                                            stat_intervals.geometry_rho("ea6"))
    except (ImportError, OSError, KeyError, ValueError):
        return "2.07x, 2.05x, at rho 0.7531"


def _priority_rho_match():
    """How closely utilization was held between the priority arms, as a bound.

    The map's "held fixed" column states a bound, not a measurement: utilization was the same
    in both arms *to within* this much. Round 48 emitted the underlying worst gap as
    `\\manipWorst` for S47 and found this cell still typing its own copy of the same quantity
    at a coarser rounding, which is how a figure and a sentence come to print two numbers for
    one fact. The ceiling is taken at three decimals because that is the width the cell has;
    it is a bound, so it rounds up rather than to nearest.
    """
    try:
        import priority_pairs
        worst = max(abs(p["rho"] - p["rho_rt"]) for p in priority_pairs.pairs())
        return "%.3f" % (math.ceil(worst * 1000.0) / 1000.0)
    except (ImportError, OSError, KeyError, ValueError):
        return "0.003"


def _colocation_rho_match():
    """The same bound for E-A8, where the typed copy was not merely coarse but wrong.

    The cell claimed utilization was held "to 0.002" between the remote and co-located arms.
    `docs/results/model/colocation.csv` has them differing by $0.0025$ at idle --- 0.0025
    against 0.005 --- so the bound the map published excluded a value the campaign actually
    recorded. Nothing downstream depends on it, which is precisely why it survived: no result
    is computed from this cell, so no gate that checks results could notice it was false.
    """
    try:
        import csv
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "docs", "results", "model", "colocation.csv")
        with open(path, newline="", encoding="utf-8-sig") as handle:
            gaps = [abs(float(r["rho_remote"]) - float(r["rho_colocated"]))
                    for r in csv.DictReader(handle)]
        return "%.3f" % (math.ceil(max(gaps) * 1000.0) / 1000.0)
    except (OSError, KeyError, TypeError, ValueError):
        return "0.003"


def _tail_index():
    """The payload sweep's effective exponent, two decimals, as the map prints it.

    `\\tailExponent` is emitted at three (0.339); the map has room for two and said 0.34.
    Both are the same fit, and this reads it rather than remembering it.
    """
    try:
        import stat_intervals
        return "%.2f" % -stat_intervals.payload_fit()[0]
    except (ImportError, OSError, KeyError, ValueError):
        return "0.34"


# (campaign, manipulated, held fixed, settles) -- the row content of the map.
ROWS = [
    ("E1\nconcurrency", "feeds $N$:\n1, 9, 10, 12", "rate, host,\nplan set",
     "the original question:\ndoes broker choice matter?"),
    ("E-B\ndelay sweep", "injected delay\n0-50 ms", "load, feeds",
     "H1 effect size\n(direction only; confounded)"),
    ("E-A / E-A3\nload sweep", "background load\n0-12", "rate, feeds,\nplan",
     "H2 utilization, H10 mixture,\n$F_\\Delta$ recovery"),
    ("E-A2\nprocess count", "processes at\nfixed rate", "aggregate\nevent rate",
     "H4 oversubscription"),
    ("E-C3 / E-C4\nstamping", "ack stamp:\ncallback vs inline", "load, in-flight,\nbackend",
     "H3 asymmetry\n(replicated)"),
    ("window\nsweep", "observation window\n60-600 s", "rate, host,\nmatch",
     "start-up cost vs\nper-event constant"),
    ("transport\n(x2)", "feeds, powered", "verified\nreal-time rate",
     "broker transport,\nequivalence + shift"),
    # The campaigns that decided the mechanism. Added after an audit found the closing note's
    # claim -- that every claim in the discussion traces to a row -- had quietly become false: five
    # campaigns were carrying results in the text with no row here at all.
    ("E-A5/A5b/A7\nstamping priority", "SCHED_FIFO on\nthe stamping threads",
     "utilization,\nto %s" % _priority_rho_match(),
     "scheduling, not utilization\n(%s)" % _priority_range()),
    ("E-A6 / E-A6b\nload geometry", "cores free vs\nall duty-cycled", "achieved\nutilization",
     "utilization is not the variable\n(%s)" % _geometry_result()),
    ("E-A9\nrun-queue trace", "nothing:\nobservation only", "load,\npriority arm",
     "P(stall > $T_\\mathrm{true}$) predicts\nthe rate, unfitted"),
    ("E-A10\ntransport sweep", "payload size;\n$T_\\mathrm{true}$ %sx" % _transport_span(),
     "load, hosts,\ncode path",
     "other side of the inequality;\ntail index %s" % _tail_index()),
    ("E-A8\nco-location", "broker on\nthe driver",
     "utilization,\nto %s" % _colocation_rho_match(),
     "nothing: transport did not\nmove, so it is withheld"),
    ("OMB\nexternal", "instrumented\ndiscard counter", "our broker,\nunder load",
     "the exposure is\nnot ours alone"),
]

CAMPAIGN = "#1f77b4"
MANIP = "#d62728"
FIXED = "#7f7f7f"
CLAIM = "#2ca02c"


def draw(ax):
    ax.set_xlim(0, 10)
    # Half a row of headroom above and a full row below, so the closing note clears the last row.
    ax.set_ylim(-0.7, len(ROWS) + 1.4)
    ax.axis("off")

    headers = [(1.0, "Campaign"), (3.5, "Manipulated"), (5.8, "Held fixed"),
               (8.3, "What it settles")]
    for x, label in headers:
        ax.text(x, len(ROWS) + 0.85, label, ha="center", va="center",
                fontsize=11.5, fontweight="bold")
    ax.plot([0.15, 9.85], [len(ROWS) + 0.55] * 2, color="black", lw=1.0)

    for i, (camp, manip, fixed, claim) in enumerate(ROWS):
        y = len(ROWS) - i - 0.5
        # Campaign chip
        ax.add_patch(FancyBboxPatch((0.18, y - 0.36), 1.64, 0.72,
                                    boxstyle="round,pad=0.02,rounding_size=0.08",
                                    facecolor=CAMPAIGN, alpha=0.16,
                                    edgecolor=CAMPAIGN, lw=1.0))
        ax.text(1.0, y, camp, ha="center", va="center", fontsize=10.5, color=CAMPAIGN,
                fontweight="bold")
        ax.text(3.5, y, manip, ha="center", va="center", fontsize=10.5, color=MANIP)
        ax.text(5.8, y, fixed, ha="center", va="center", fontsize=10.5, color=FIXED)
        ax.text(8.3, y, claim, ha="center", va="center", fontsize=10.5, color=CLAIM)
        if i < len(ROWS) - 1:
            ax.plot([0.15, 9.85], [y - 0.5] * 2, color="#dddddd", lw=0.6)

    # Two lines: at the larger point size this note no longer fits the narrower canvas on one.
    ax.text(5.0, -0.42,
            "Every claim in the discussion traces to one row. No row both generates and tests\n"
            "the same hypothesis, and a row that settled nothing says so.",
            ha="center", va="center", fontsize=9.5, style="italic", color="#444444")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Method figure: the experiment map")
    ap.add_argument("--out", default="docs/results/figures")
    args = ap.parse_args(argv)

    plt.rcParams.update({"font.size": 10})
    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    draw(ax)
    fig.tight_layout()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(out / f"experiment_map.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"OK wrote {out}/experiment_map.pdf and .png")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
