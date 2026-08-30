#!/usr/bin/env python3
"""
make_thread_figure.py
Which threads do the work, which threads read the clock, and why that makes a span go negative.

Origin. D. Gregg, 2026-08-24: "At some point the reader needs to understand what threads are
doing the work of the benchmark, what threads are recording times, and how the two groups of
threads interact. I think the only way to explain this is with some sort of picture showing
producer threads, consumer threads, and time-stamping threads."

He is right that the paper never draws this, and the existing Figure 1(a) does not: it has two
lanes, "producer thread" and "consumer thread", which is the mechanism after the architecture
has been assumed. This draws the architecture. It is deliberately a first version to be argued
with at a whiteboard, not a finished exhibit.

The three questions it has to answer on sight:

  Which threads take the two stamps?  Not one. `t_send` is taken on the application thread
  that calls send(); `t_ack` is taken on the client library's delivery-callback thread. They
  are different threads in the same process, and nothing schedules them together.

  Why is it built that way?  Because every mainstream client sends asynchronously and signals
  completion on a callback thread. A producer that blocked for each acknowledgment could not
  generate load at all. So the asynchrony is not a defect of one benchmark; it is the reason
  the benchmark can exist, and no design that keeps it has a single thread to stamp with.

  Where does the negative come from?  The broker's append precedes both the acknowledgment and
  the delivery. Neither of those precedes the other. If the callback thread waits longer for a
  core than the consumer does, `t_recv - t_ack` is negative with nothing physically impossible
  having happened. The figure shows exactly that case, to scale with the numbers in the corpus:
  raw stamps give send->ack of 3-113 ms against send->recv of 2-5 ms.

CLI:
    python scripts/make_thread_figure.py            # paper width
    python scripts/make_thread_figure.py --talk     # slide width
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import figure_style

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT_DIR = os.path.join("docs", "results", "figures")

PROD = "#1f77b4"
CONS = "#ff7f0e"
GREY = "#555555"
CUT = "#b22222"
BROKER = "#7a7a7a"

#: Lanes, top to bottom: (y, label, colour). The broker sits in the middle because both
#: branches descend from it, which is the fact the whole figure exists to make visible.
LANES = (
    (5.0, "producer app thread\n(calls send)", PROD),
    (4.0, "client I/O thread\n(transmits)", PROD),
    (3.0, "BROKER\n(appends)", BROKER),
    (2.0, "client callback thread\n(reads clock -> t_ack)", PROD),
    (1.0, "consumer app thread\n(reads clock -> t_recv)", CONS),
)

X_LO, X_HI = 0.0, 10.6


def _lane(ax, y, label, colour):
    ax.annotate("", xy=(X_HI - 0.3, y), xytext=(2.55, y),
                arrowprops=dict(arrowstyle="->", color=GREY, linewidth=1.0))
    ax.text(2.42, y, label, fontsize=7, color=colour, ha="right", va="center",
            linespacing=1.0)


def plot_threads(ax):
    ax.set_xlim(X_LO, X_HI)
    ax.set_ylim(0.35, 5.95)
    ax.axis("off")

    for y, label, colour in LANES:
        _lane(ax, y, label, colour)

    # --- the outward path -------------------------------------------------------------
    # send() is called and stamped on the calling thread. This stamp is never late relative
    # to the event it marks, because the thread taking it is the thread doing the thing.
    ax.plot([3.1], [5.0], marker="o", markersize=6, color=PROD,
            markerfacecolor="white", markeredgewidth=1.4)
    ax.text(3.1, 5.34, r"$t_{send}$", fontsize=8, color=PROD, ha="center")
    ax.annotate("", xy=(3.7, 4.0), xytext=(3.2, 4.95),
                arrowprops=dict(arrowstyle="->", color=GREY, linewidth=0.9))
    ax.text(3.05, 4.5, "enqueue", fontsize=6.5, color=GREY, ha="right", va="center")

    ax.annotate("", xy=(4.5, 3.05), xytext=(3.85, 3.9),
                arrowprops=dict(arrowstyle="->", color=GREY, linewidth=0.9))

    # the append: one cause, two branches
    ax.plot([4.7], [3.0], marker="D", markersize=7, color=BROKER)
    ax.text(4.7, 3.32, "append", fontsize=7.5, color=BROKER, ha="center")

    for tip in ((5.9, 2.08), (5.6, 1.08)):
        ax.annotate("", xy=tip, xytext=(4.85, 2.92),
                    arrowprops=dict(arrowstyle="->", color=BROKER, linewidth=1.0,
                                    linestyle=(0, (3, 2))))
    ax.text(4.52, 2.52, "two branches,\nneither before the other", fontsize=6.5,
            color=BROKER, ha="right", va="center", linespacing=1.0)

    # --- the consumer branch: short wait, early stamp ---------------------------------
    ax.plot([5.7], [1.0], marker="|", markersize=13, color=CONS)
    ax.text(5.7, 0.62, "record\narrives", fontsize=6.5, color=GREY, ha="center", va="top",
            linespacing=1.0)
    ax.plot([6.5], [1.0], marker="o", markersize=6, color=CONS)
    ax.text(6.5, 1.30, r"$t_{recv}$", fontsize=8, color=CONS, ha="center")
    ax.annotate("", xy=(6.5, 1.0), xytext=(5.7, 1.0),
                arrowprops=dict(arrowstyle="<->", color=CUT, linewidth=1.3))
    ax.text(6.18, 0.62, r"$\delta_{recv}$", fontsize=7.5, color=CUT, ha="center", va="top")

    # --- the acknowledgment branch: the callback thread waits for a core --------------
    ax.plot([6.0], [2.0], marker="|", markersize=13, color=PROD)
    ax.text(6.0, 2.32, "ack arrives", fontsize=6.5, color=GREY, ha="center")
    ax.plot([9.3], [2.0], marker="o", markersize=6, color=PROD)
    ax.text(9.3, 2.32, r"$t_{ack}$", fontsize=8, color=PROD, ha="center")
    ax.annotate("", xy=(9.3, 2.0), xytext=(6.0, 2.0),
                arrowprops=dict(arrowstyle="<->", color=CUT, linewidth=1.6))
    # Short, and anchored right of t_recv's guide line. The long form ("descheduled, waiting
    # for a core") is wide enough at paper width to reach back across the consumer's stamp
    # label, which sits a third of the figure away.
    ax.text(9.25, 1.68, r"$\delta_{ack}$: waiting for a core",
            fontsize=7.5, color=CUT, ha="right", va="top")

    # --- the consequence --------------------------------------------------------------
    # A vertical guide from each stamp, so the reader can see t_recv sitting to the LEFT of
    # t_ack on the page. That ordering on the page is the whole result.
    for x, colour in ((6.5, CONS), (9.3, PROD)):
        ax.plot([x, x], [0.62, 5.55], color=colour, linewidth=0.7,
                linestyle=(0, (2, 3)), alpha=0.55, zorder=0)

    ax.annotate("", xy=(6.5, 5.62), xytext=(9.3, 5.62),
                arrowprops=dict(arrowstyle="->", color=CUT, linewidth=1.6))
    ax.text(7.9, 5.72, r"$t_{recv} - t_{ack} < 0$", fontsize=8.5, color=CUT, ha="center",
            va="bottom")

    ax.text(0.02, 0.03,
            "The stamp that fails is not the one on the path being timed.",
            transform=ax.transAxes, fontsize=7, color=GREY, ha="left", va="bottom",
            style="italic")


def build(out_dir=OUT_DIR, talk=False):
    figure_style.apply()
    size = (12.0, 4.4) if talk else (7.16, 2.9)
    fig, ax = plt.subplots(figsize=size)
    plot_threads(ax)
    fig.tight_layout()

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    stem = "thread_architecture_talk" if talk else "thread_architecture"
    made = []
    for ext in (("png",) if talk else ("pdf", "png")):
        path = os.path.join(out_dir, "%s.%s" % (stem, ext))
        fig.savefig(path, bbox_inches="tight", pad_inches=0.03,
                    dpi=200 if ext == "png" else None)
        made.append(path)
    plt.close(fig)
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description="Draw the thread architecture behind the two stamps")
    ap.add_argument("--talk", action="store_true")
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args(argv)
    for path in build(args.out_dir, talk=args.talk):
        print("wrote %s" % path)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
