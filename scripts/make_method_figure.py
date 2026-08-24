#!/usr/bin/env python3
"""
make_method_figure.py
Method figure: the experiment map. Which campaign manipulates what, holds what fixed, and which
claim it is the evidence for.

The paper's campaigns accumulated over three months in response to defects, so their logic is not
obvious from their names. This figure states it in one place: the manipulated variable, the
controlled variable, and the hypothesis or claim each campaign settles. A reader should be able
to check that every claim in Section 7 has an experiment behind it, and that no experiment is
doing double duty as both the source of a hypothesis and its test.

CLI:
    python scripts/make_method_figure.py --out docs/results/figures
"""
import argparse
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

# (campaign, manipulated, held fixed, settles) -- the row content of the map.
ROWS = [
    ("E1\nconcurrency", "feeds $N$:\n1, 9, 10, 12", "rate, host,\nplan set",
     "the original question:\ndoes broker choice matter?"),
    ("E-B\ndelay sweep", "injected delay\n0-50 ms", "load, feeds",
     "H1 effect size\n(direction only; confounded)"),
    ("E-A / E-A3\nload sweep", "background load\n0-12", "rate, feeds,\nplan",
     "H2 utilisation, H10 mixture,\n$F_\\Delta$ recovery"),
    ("E-A2\nprocess count", "processes at\nfixed rate", "aggregate\nevent rate",
     "H4 oversubscription"),
    ("E-C3 / E-C4\nstamping", "ack stamp:\ncallback vs inline", "load, in-flight,\nbackend",
     "H3 asymmetry\n(replicated)"),
    ("window\nsweep", "observation window\n60-600 s", "rate, host,\nmatch",
     "start-up cost vs\nper-event constant"),
    ("transport\n(x2)", "feeds, powered", "verified\nreal-time rate",
     "broker transport,\nequivalence + shift"),
    # The campaigns that decided the mechanism. Added after an audit found the closing note's
    # claim -- that every claim in Section 7 traces to a row -- had quietly become false: five
    # campaigns were carrying results in the text with no row here at all.
    ("E-A5/A5b/A7\nstamping priority", "SCHED_FIFO on\nthe stamping threads",
     "utilisation,\nto 0.003", "scheduling, not utilisation\n(8 pairs, 7-80x)"),
    ("E-A6 / E-A6b\nload geometry", "cores free vs\nall duty-cycled", "achieved\nutilisation",
     "utilisation is not the variable\n(2.07x, 2.05x, at rho 0.7531)"),
    ("E-A9\nrun-queue trace", "nothing:\nobservation only", "load,\npriority arm",
     "P(stall > $T_\\mathrm{true}$) predicts\nthe rate, unfitted"),
    ("E-A10\ntransport sweep", "payload size;\n$T_\\mathrm{true}$ 77x", "load, hosts,\ncode path",
     "other side of the inequality;\ntail index 0.34"),
    ("E-A8\nco-location", "broker on\nthe driver", "utilisation,\nto 0.002",
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
            "Every claim in Section 7 traces to one row. No row both generates and tests\n"
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
