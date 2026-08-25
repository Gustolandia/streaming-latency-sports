#!/usr/bin/env python3
"""
make_paper_figures.py
The figures the manuscript needs beyond the E1 comparison (see make_e1_figure.py).

  1. pipeline_schematic  -- where the four timestamps are taken, and which interval each
     metric spans. This is the figure that makes the clock-integrity argument legible: it
     shows that transport subtracts a timestamp taken in the producer process from one taken
     in the consumer process, which is exactly why it can come out negative.
  2. workload_profile    -- arrival rate and burstiness across 3,315 StatsBomb matches.
  3. kickoff_concurrency -- how many matches are actually in play at once, which is where the
     benchmark's concurrency levels come from instead of being chosen by hand.
  4. integrity_audit     -- the distribution of timestamp-inversion rates per run. Bimodal,
     which is what makes the 1% condemnation threshold insensitive to its exact value.
  5. network_delay       -- the condition that reverses the ordering between the backends.

CLI:
    python scripts/make_paper_figures.py --out docs/results/figures
"""
import argparse
import csv
from pathlib import Path

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib
matplotlib.use("Agg")
import figure_style  # noqa: E402
import figure_collisions  # noqa: E402
import figure_legibility  # noqa: E402
import figure_vocabulary  # noqa: E402
figure_style.apply()  # Type 42, IEEE-listed family; see scripts/figure_style.py
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

KAFKA, REDIS = "#1f77b4", "#ff7f0e"
GREY = "#555555"

# Injected one-way delay (ms) -> median TTI (ms), from docs/results/cloud/net_d*/.
# The 0 ms condition is condemned by the integrity gate in both backends and is excluded
# here rather than plotted as if it were a measurement.
NETEM = {
    "delay_ms": [5, 20, 50],
    "kafka_tti": [12.371339, 77.766731, 336.610643],
    "redis_tti": [4650.816265, 31401.20169, 103142.90199],
}
# The same intervention at N=1 real time, from docs/results/e5/.
ACK_BATCHED_TTI_MS = 103.0
ACK_UNBATCHED_TTI_MS = 4138.0


# --------------------------------------------------------------------------- schematic

NL = chr(10)  # a newline that survives every editing route into this file

def plot_pipeline(ax):
    """Draw the replay pipeline, its four timestamps, and the intervals they define."""
    boxes = [(0.2, "Producer\n(replay)"), (3.8, "Broker\n(Kafka/Redis)"), (7.4, "Consumer")]
    for x, label in boxes:
        ax.add_patch(plt.Rectangle((x, 1.6), 2.4, 0.9, facecolor="white",
                                   edgecolor=GREY, linewidth=1.4))
        ax.text(x + 1.2, 2.05, label, ha="center", va="center", fontsize=8.5)
    for x0, x1 in ((2.65, 3.8), (6.25, 7.4)):
        ax.annotate("", xy=(x1, 2.05), xytext=(x0, 2.05),
                    arrowprops=dict(arrowstyle="->", color=GREY, linewidth=1.2))

    stamps = [(0.6, r"$t_{\rm sched}$", "planned"), (2.4, r"$t_{\rm send}$", "producer"),
              (4.4, r"$t_{\rm ack}$", "producer"), (7.6, r"$t_{\rm recv}$", "consumer")]
    for x, sym, proc in stamps:
        ax.plot([x, x], [1.35, 1.6], color=GREY, linewidth=1.0)
        ax.text(x, 1.20, sym, ha="center", va="top", fontsize=9)
        ax.text(x, 0.98, proc, ha="center", va="top", fontsize=8, color=GREY, style="italic")

    spans = [(0.6, 2.4, 0.42, "scheduling lag"), (4.4, 7.6, 0.42, "broker transport"),
             (0.6, 7.6, 0.05, "end-to-end TTI")]
    for x0, x1, y, label in spans:
        ax.annotate("", xy=(x1, y), xytext=(x0, y),
                    arrowprops=dict(arrowstyle="<->", color="black", linewidth=1.0))
        ax.text((x0 + x1) / 2, y + 0.06, label, ha="center", fontsize=8)

    # Not "two processes' clocks". The producer and the consumer are two processes on one host
    # reading one clock, and Section V exists to show the span inverts anyway; an annotation
    # naming clocks plants the rival hypothesis in the reader at the first figure, and
    # contradicts this figure's own caption, which says "when either process is delayed".
    # No mathtext here. A double arrow has no Arial glyph, falls back to Computer Modern and
    # extracts as ")", which corrupts this sentence for every reader of the text layer.
    ax.text(5.0, 3.20, "broker transport subtracts stamps written by two threads, "
                       "so it can come out negative on one clock",
            ha="center", va="top", fontsize=8, color="#b22222")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3.3)
    ax.axis("off")


# --------------------------------------------------------------------------- workload
def plot_workload(axes, profiles):
    """Per-match arrival rate and burstiness across the corpus."""
    mean_ax, burst_ax = axes
    mean_ax.hist(profiles["mean_rate_evs"], bins=40, color=GREY, alpha=0.75)
    mean_ax.axvline(profiles["mean_rate_evs"].median(), color="#b22222", linewidth=1.6,
                    label=f"median {profiles['mean_rate_evs'].median():.3f} ev/s")
    mean_ax.set_xlabel("Mean arrival rate (events/s)")
    mean_ax.set_ylabel("Matches")
    mean_ax.set_title("(a) Football event feeds are sparse")
    mean_ax.legend(fontsize="small", framealpha=1.0)

    burst_ax.hist(profiles["burstiness"], bins=40, color=GREY, alpha=0.75)
    burst_ax.axvline(profiles["burstiness"].median(), color="#b22222", linewidth=1.6,
                     label=f"median {profiles['burstiness'].median():.2f}$\\times$")
    burst_ax.set_xlabel("Peak / mean arrival rate (10 s window)")
    burst_ax.set_ylabel("Matches")
    burst_ax.set_title("(b) ...and burstier than their mean suggests")
    burst_ax.legend(fontsize="small", framealpha=1.0)


# --------------------------------------------------------------------------- concurrency
def plot_concurrency(axes, slots, timeline):
    """How many matches kick off together, and how many are in play at once."""
    slot_ax, play_ax = axes
    counts = slots["n_matches"].value_counts().sort_index()
    slot_ax.bar(counts.index, counts.values, color=GREY, alpha=0.8)
    slot_ax.set_yscale("log")
    slot_ax.set_xlabel("Matches sharing a kick-off time")
    slot_ax.set_ylabel("Kick-off slots (log)")
    slot_ax.set_title(f"(a) {len(slots):,} kick-off slots; largest carries "
                      f"{int(slots['n_matches'].max())}")

    occupancy = timeline["in_play"]
    play_ax.hist(occupancy[occupancy > 0], bins=range(1, int(occupancy.max()) + 2),
                 color=GREY, alpha=0.8)
    play_ax.set_yscale("log")
    play_ax.set_xlabel("Matches simultaneously in play")
    play_ax.set_ylabel("Timeline points (log)")
    play_ax.set_title(f"(b) Peak simultaneous occupancy: {int(occupancy.max())}")
    for ax, level in ((play_ax, 12),):
        ax.axvline(level, color="#b22222", linestyle="--", linewidth=1.4,
                   label="benchmarked up to $N$=12")
        ax.legend(fontsize="small", framealpha=1.0)


# --------------------------------------------------------------------------- audit
DEFAULT_BASE_SLICE_MS = 3.0


def _base_slice_ms():
    """The EEVDF base slice, derived; the literal is a fallback for a stripped checkout.

    The fallback equals what the derivation returns for the committed testbed, so a reader
    without the kernel config artefact gets the published figure rather than a different one.
    """
    try:
        import kernel_constants
        return float(kernel_constants.constants()["base_slice_ms"])
    except (ImportError, OSError, KeyError, ValueError):
        return DEFAULT_BASE_SLICE_MS


def plot_model(axes):
    """The measurement-failure model, drawn rather than only stated.

    (a) why inversion happens: measured transport is the true value displaced by the asymmetry
        in stamping delay, so it goes negative whenever that asymmetry exceeds the true value.
    (b) why the check bites hardest on small effects (H1): the same Delta distribution overlaps
        a small T_true almost entirely and a large one hardly at all.
    """
    mech_ax, h1_ax = axes

    # --- (a) the mechanism, as a timeline
    #
    # A reader (Kunkel, v3 correspondence, item A1) could not place the acknowledgement in
    # the producer's own sequence because the panel showed only the ack and the receive,
    # while Eq. (1) is written in t_sched and t_send. Both now sit on the producer timeline
    # to the left of the acknowledgement, with the scheduling-lag bracket that ties them to
    # Eq. (1). The start-at-ack framing of the inversion itself is unchanged: the failure
    # is between the two clock reads, and that is what the red bracket still marks.
    mech_ax.set_xlim(0, 10.4)
    mech_ax.set_ylim(0, 3.2)
    mech_ax.axis("off")
    # "thread", not "producer" and "consumer": a co-author read the panel as two processes
    # and asked which thread actually takes each reading. Two do, one per lane, and the whole
    # mechanism is that they wait for a core independently of each other.
    for y, label, colour in ((2.3, "producer" + NL + "thread", KAFKA),
                             (0.9, "consumer" + NL + "thread", REDIS)):
        mech_ax.annotate("", xy=(9.9, y), xytext=(1.4, y),
                         arrowprops=dict(arrowstyle="->", color=GREY, linewidth=1.2))
        mech_ax.text(0.15, y, label, fontsize=8, color=colour, ha="left", va="center",
                     linespacing=0.95)

    # the producer's own two stamps, taken before the acknowledgement exists
    for x, sym in ((1.9, r"$t_{sched}$"), (2.7, r"$t_{send}$")):
        mech_ax.plot([x], [2.3], marker="o", markersize=5, color=KAFKA,
                     markerfacecolor="white", markeredgewidth=1.2)
        mech_ax.text(x, 2.62, sym, fontsize=8, ha="center", color=KAFKA)
    mech_ax.annotate("", xy=(2.7, 2.3), xytext=(1.9, 2.3),
                     arrowprops=dict(arrowstyle="<->", color=GREY, linewidth=0.9))
    mech_ax.text(2.3, 2.02, "scheduling\nlag", fontsize=8, color=GREY, ha="center",
                 va="top", linespacing=0.9)

    # The broker's append, and the two branches descending from it.
    #
    # Without this the panel is a left-to-right sequence of four events on two lines, which
    # invites precisely the reading Section III-C exists to refute: that the acknowledgement
    # causally precedes the record's arrival. It does not. Both descend from the append and
    # neither precedes the other, which is why their difference may be negative with no
    # physical impossibility. A figure for that section has to show the fork.
    mech_ax.plot([2.95], [1.6], marker="D", markersize=5.5, color=GREY)
    # One line, in the band between "scheduling lag" above and the consumer timeline below.
    # Two lines do not fit there at this panel height: anchored high the label runs into the
    # one above it, anchored low its second line lands on the timeline.
    mech_ax.text(2.15, 1.30, "broker append", fontsize=8, color=GREY, ha="center",
                 va="top")
    for tip_x, tip_y in ((3.62, 2.24), (4.62, 0.96)):
        mech_ax.annotate("", xy=(tip_x, tip_y), xytext=(3.05, 1.6),
                         arrowprops=dict(arrowstyle="->", color=GREY, linewidth=0.9,
                                         linestyle=(0, (3, 2))))

    # physical events (true), and the later moments the software actually reads the clock
    mech_ax.plot([3.7], [2.3], marker="|", markersize=14, color=KAFKA)
    mech_ax.text(3.7, 2.62, "ack arrives", fontsize=8, ha="center")
    mech_ax.plot([5.9], [2.3], marker="o", markersize=6, color=KAFKA)
    mech_ax.text(5.9, 2.62, r"clock read $\rightarrow t_{ack}$", fontsize=8, ha="center")
    mech_ax.annotate("", xy=(5.9, 2.3), xytext=(3.7, 2.3),
                     arrowprops=dict(arrowstyle="<->", color="#b22222", linewidth=1.2))
    mech_ax.text(4.8, 2.02, r"$\delta_{ack}$", fontsize=8, color="#b22222", ha="center")

    mech_ax.plot([4.7], [0.9], marker="|", markersize=14, color=REDIS)
    mech_ax.text(4.6, 0.42, "message received", fontsize=8, ha="right")
    mech_ax.plot([5.3], [0.9], marker="o", markersize=6, color=REDIS)
    mech_ax.text(5.9, 0.42, r"clock read $\rightarrow t_{recv}$", fontsize=8, ha="center")
    mech_ax.annotate("", xy=(5.3, 0.9), xytext=(4.7, 0.9),
                     arrowprops=dict(arrowstyle="<->", color="#b22222", linewidth=1.2))
    # Clear of the arrow it names: the panel is shorter than it was drawn for, and 0.12
    # above the timeline is no longer 0.12 on the page.
    mech_ax.text(5.0, 1.16, r"$\delta_{recv}$", fontsize=8, color="#b22222", ha="center")

    mech_ax.text(6.3, 1.55,
                 r"$T_{meas}=t_{recv}-t_{ack}<0$" "\n"
                 r"even though $T_{true}>0$",
                 fontsize=8, color="#b22222", ha="left", va="center")

    # --- (b) why small effects are fragile
    #
    # This panel has now been wrong twice, in opposite directions, and both errors were the
    # same error: drawing a shape the data had not been asked about.
    #
    #   v1 drew Delta as a single Gaussian -- a finite mean and a thin tail, which makes
    #      inversions look like a mild consequence of a wide distribution.
    #   v2 replaced it with a monotone heavy tail and titled it "P(inv) ~ T^-0.34".
    #
    # Estimated properly on the traced histogram (scripts/tail_index_traced.py) the stall
    # distribution is neither. It is multi-modal, and the mode that matters sits at the
    # EEVDF base slice -- 0.75 ms * (1 + ilog2(8)) = 3 ms on these instances -- carrying
    # about a tenth of all wakeups, with a LIGHT tail (alpha ~ 2) beyond it. So Delta, which
    # is the difference of two stamping delays, has a narrow core when the callback thread
    # is running and a lobe near -3 ms when it is not. That is Equation 6 made visible:
    # p(rho) sets the lobe's weight, S(T_true) decides how much of it lies beyond -T_true.
    #
    # The shape below is schematic -- two components with the measured mode's location, not
    # a fit -- and the caption says so. What it must get right, and now does, is that
    # raising T_true past the lobe removes most of the inversion risk rather than "barely
    # thinning" it, which is the direction the payload sweep measures.
    # The lobe's position is the one number in this panel that is not free: it is the
    # scheduler's base slice, and it is derived in kernel_constants.py from the published
    # kernel config and the campaign's own CPU count. Taking it from there rather than
    # typing it means the figure, the caption macro and Section V-G cannot drift apart --
    # the same rule the rest of the manuscript's numbers already live under.
    slice_ms = _base_slice_ms()
    x = np.linspace(-6, 6, 1200)
    core = 0.70 * np.exp(-0.5 * (x / 0.22) ** 2)            # RUNNING: narrow jitter core
    lobe = 0.30 * np.exp(-0.5 * ((x + slice_ms) / 0.60) ** 2)  # PREEMPTED: at the slice
    # A flat-ish background so the density stays on the axis across the whole range: both
    # threads can stall, so there is mass on the positive side too, and a curve that falls
    # off the bottom of the plot would claim otherwise.
    delta = core + lobe + 2.0e-3 * (1.0 + np.abs(x) / 1.0) ** (-1.4)
    h1_ax.semilogy(x, delta, color=GREY, linewidth=1.8)
    h1_ax.fill_between(x, 1e-4, delta, where=(x < -0.5), color="#b22222", alpha=0.28)
    h1_ax.fill_between(x, 1e-4, delta, where=(x < -4.0), color=REDIS, alpha=0.55)
    h1_ax.axvline(-0.5, color=KAFKA, linewidth=1.6, linestyle="--")
    h1_ax.axvline(-4.0, color=REDIS, linewidth=1.6, linestyle="--")
    # Headroom above the hump. The wide format left no gap between the curve and the
    # frame for the label that names it, and this axis has suppressed ticks, so the
    # extra decade is free.
    h1_ax.set_ylim(1e-4, 60.0)
    h1_ax.set_xlim(-6, 6)
    h1_ax.text(-5.85, 22.0, r"large $T_{true}$:" "\npast the lobe,\nlittle left",
               fontsize=8, color=REDIS, linespacing=1.05, va="top")
    h1_ax.text(1.15, 0.60, r"small $T_{true}$:" "\nthe whole lobe\ninverts it",
               fontsize=8, color=KAFKA, linespacing=1.05, va="top")
    # relpos pins the arrow to the edge of the label it belongs to. Left at its default it
    # starts from the centre of the text, and the leader shows through the gaps in the words.
    h1_ax.annotate("core\n(thread running)", xy=(0.30, 1.4), xytext=(3.6, 1.4),
                   fontsize=8, color=GREY, ha="left", va="center",
                   arrowprops=dict(arrowstyle="->", color=GREY, lw=0.8, relpos=(0.0, 0.5)))
    # Labelled where the lobe is rather than from across the panel. The wide format halved the
    # vertical room, and a leader drawn the width of the axes crossed the other annotation on
    # its way; the space directly above the hump is empty and a short one crosses nothing.
    h1_ax.annotate("preempted lobe\nat the scheduler slice", xy=(-slice_ms, 0.52),
                   xytext=(-2.9, 12.0), fontsize=8, color=GREY, ha="center", va="center",
                   arrowprops=dict(arrowstyle="->", color=GREY, lw=0.8, relpos=(0.5, 0.0)))
    h1_ax.set_xlabel(r"stamping asymmetry $\Delta$ (ms)")
    h1_ax.set_ylabel("density (log)")
    h1_ax.set_yticks([])
    h1_ax.set_title(r"(b) which intervals invert is decided by the preempted lobe",
                    fontsize=9)
    mech_ax.set_title("(a) how a positive latency is measured as negative", fontsize=9)


SENSITIVITY_THRESHOLDS = (0.0, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20)


# --- the geometry behind the deletion law -------------------------------------------------

#: One tick of the millisecond grid, and a delivery shorter than it. The pair is the paper's
#: own: both incommensurate arms sit near 50% retention at tau = 1 ms, so a T_true of a few
#: tenths of a millisecond is the regime the failure lives in. The value must fall *between*
#: two grid values for q = 4, so that the figure shows the bracketing the text describes,
#: which a value sitting exactly on a grid point would hide.
#:
#: 0.35 rather than 0.4 or 0.3, and the reason is the ledger sweep rather than the physics:
#: both of those are publish-latency values the ledger emits, and a literal in the caption
#: that happens to equal an emitted quantity is exactly what that gate exists to refuse. The
#: main text takes no exemptions, so the illustration moved instead. 0.35 gives 7/20 = 35% for
#: uniform phases against 1/4 = 25% on the grid, and three of four phases still measure zero.
TAU_MS = 1.0
T_TRUE_MS = 0.35

#: A commensurate send interval in lowest terms. Delta/tau = 5/4 gives q = 4, so the producer
#: visits four phases and retention can only be one of 0, 1/4, 2/4, 3/4, 1.
GRID_Q = 4


def plot_quantum_geometry(axes, tau=TAU_MS, t_true=T_TRUE_MS, q=GRID_Q):
    r"""Why a span is deleted, and why the survivors are not a sample.

    Figure 3 shows that the arms sit closer to the grid than chance allows, and Figure 2 shows
    retention collapsing across the corpus. Both are evidence *that* the deletion law holds.
    Neither draws the mechanism, which is a statement about where a send instant falls inside
    one tick, and which is carried in the text by two equations.

    Panel (a) is Equation (retention). Four deliveries of identical true duration begin at
    four phases of the same tick. Three finish inside it, so both stamps round to the same
    value, the difference is exactly zero, and the guard removes them. The fourth crosses the
    boundary and is recorded -- as one whole tick, which is why the corpus reports 1.0 and 2.0
    ms and nothing between.

    Panel (b) is Equation (quant). The crossing region is the last `t_true` of the tick, so a
    producer with uniform phases retains `t_true / tau`. A commensurate producer does not have
    uniform phases: it visits `q` of them and retains a count out of `q`. Same delivery, same
    clock, a different answer, decided by the send schedule -- which is the argument for
    dithering it.
    """
    top, bot = axes
    keep, drop = "#1f77b4", "#c44e52"
    phases = [i * tau / q for i in range(q)]
    crossing = tau - t_true                     # a delivery from here on reaches the next tick

    # --- (a) one tick, four phases ---------------------------------------------------------
    span = 1.45 * tau
    # Drawn with an explicit top rather than axvline: a full-height rule runs through the
    # labels that name it, which is what the collision gate said the first time this was
    # rendered. The rule stops below the text and the text sits clear of it.
    for x in (0.0, tau):
        top.plot([x, x], [0.42, q + 0.34], color=GREY, lw=0.9, ls=(0, (3, 2)), zorder=1)
    top.text(0.0, q + 0.52, "tick", fontsize=8, color=GREY, ha="center", va="bottom")
    top.text(tau, q + 0.52, "next tick", fontsize=8, color=GREY, ha="center", va="bottom")

    for i, phi in enumerate(phases):
        y = q - i
        crosses = phi + t_true >= tau
        colour = keep if crosses else drop
        top.plot([phi, phi + t_true], [y, y], color=colour, lw=2.6,
                 solid_capstyle="butt", zorder=3)
        top.plot([phi], [y], marker="|", color=colour, ms=7, mew=1.4, zorder=4)
        top.text(-0.05 * tau, y, r"$\varphi=%.2f$" % phi, fontsize=8, ha="right", va="center")
        top.text(1.52 * tau, y, "1 ms" if crosses else "0 ms", fontsize=8, color=colour,
                 ha="right", va="center")
        top.text(1.56 * tau, y, "kept" if crosses else "deleted", fontsize=8, color=colour,
                 ha="left", va="center")
    top.set_xlim(-0.42 * tau, 2.16 * tau)
    top.set_ylim(0.55, q + 1.25)
    for side in ("top", "right", "left", "bottom"):
        top.spines[side].set_visible(False)
    top.set_xticks([])
    top.set_yticks([])
    # The duration belongs in the title, not in the panel: as an annotation it had to sit
    # between the two tick rules, where it was legible on screen and cramped in print. No
    # `~` in a mathtext string -- matplotlib is not LaTeX and prints the tilde.
    top.set_title("(a) one delivery of $T_{\\mathrm{true}} = %.2f$ ms, at four phases"
                  % t_true, fontsize=8, loc="left")

    # --- (b) which phases exist ------------------------------------------------------------
    #
    # No bracket over the crossing region. It was drawn with its own label above the rows, and
    # once the panel was compressed to hold the paper at twelve pages it took most of the
    # vertical budget: the two rows had to sit close enough that the mathtext ascenders of the
    # lower label came within a point or two of the dots above. The collision gate did not
    # fire; at print size it was plain. The shaded band and the $\tau - T_{true}$ tick say the
    # same thing, and the caption names it in a clause, so the space goes to the rows.
    uniform = [(i + 0.5) * tau / 20 for i in range(20)]   # 8/20 = T_true/tau exactly
    # Short enough to end left of the crossing band. The long form -- "incommensurate: every
    # phase occurs" -- reached under the bracket above it, and once the figure was compressed
    # to fit the page the bracket rule cut through it: under the collision gate's threshold,
    # plain to the eye. What the two rows mean is in the caption, which has room for it.
    rows = ((2.35, uniform, "incommensurate", GREY),
            (1.00, phases, "commensurate $\\Delta/\\tau = %d/%d$" % (q + 1, q), "#2a7f62"))
    for y, pts, label, colour in rows:
        # Banded per row rather than as a full-height axvspan. The full-height version put
        # translucent ink behind both row labels, and the collision gate counted it -- which
        # is the correct call: a label over a tint is a label read twice in print.
        bot.add_patch(plt.Rectangle((crossing, y - 0.24), tau - crossing, 0.48,
                                    facecolor=keep, alpha=0.14, lw=0, zorder=0))
        bot.plot([0, tau], [y, y], color=GREY, lw=0.7, zorder=1)
        kept_n = sum(1 for p in pts if p >= crossing)
        for p in pts:
            bot.plot([p], [y], marker="o", ms=4.2, zorder=3,
                     color=keep if p >= crossing else drop)
        # Clear of the markers: at 0.2 the descenders sat on the dots.
        bot.text(0, y + 0.34, label, fontsize=8, color=colour, ha="left", va="bottom")
        bot.text(1.06 * tau, y, "%d/%d = %d%%" % (kept_n, len(pts), round(100 * kept_n / len(pts))),
                 fontsize=8, ha="left", va="center",
                 color=keep if kept_n else drop)
    bot.set_xlim(-0.03 * tau, 1.58 * tau)
    bot.set_ylim(0.42, 3.18)
    bot.set_xticks([0, crossing, tau])
    bot.set_xticklabels(["0", r"$\tau-T_{\mathrm{true}}$", r"$\tau$"], fontsize=8)
    bot.set_yticks([])
    for side in ("top", "right", "left"):
        bot.spines[side].set_visible(False)
    bot.spines["bottom"].set_bounds(0, tau)   # the phase axis ends at the tick
    bot.tick_params(axis="x", labelsize=8, length=3)
    bot.set_xlabel("phase of the send instant within one tick", fontsize=8)
    bot.set_title("(b) the send schedule decides how many survive", fontsize=8, loc="left")


def condemned_at(by_run, threshold):
    """Number of runs the gate condemns at a given negative-span threshold.

    Mirrors the rule in clock_integrity.py: condemn if the worst component's inversion rate
    exceeds the threshold, or if any component median is negative.
    """
    worst = by_run["max_neg_fraction"].astype(float)
    medians = by_run[["median_transport_ms", "median_schedlag_ms",
                      "median_output_ms"]].astype(float)
    return int(((worst > threshold) | (medians < 0).any(axis=1)).sum())


def plot_integrity(axes, by_run, threshold=0.01):
    """Per-run negative-span rates, and how the condemnation count depends on the threshold.

    The distribution is *not* cleanly bimodal, so the threshold is a real choice rather than
    an obvious one. Panel (b) reports the sensitivity instead of asserting robustness.
    """
    hist_ax, sens_ax = axes
    worst = by_run["max_neg_fraction"].astype(float)
    clean = int((worst <= 0).sum())
    nonzero = worst[worst > 0]

    bins = np.logspace(np.log10(max(nonzero.min(), 1e-6)), np.log10(nonzero.max()), 40)
    hist_ax.hist(nonzero, bins=bins, color=GREY, alpha=0.8)
    hist_ax.set_xscale("log")
    hist_ax.axvline(threshold, color="#b22222", linewidth=1.8,
                    label=f"threshold ({threshold:.0%})")
    hist_ax.set_xlabel("Worst-component negative-span rate per run (log)")
    hist_ax.set_ylabel("Runs")
    hist_ax.set_title(f"(a) {clean:,} of {len(by_run):,} runs clean", fontsize=10)
    hist_ax.legend(fontsize="small", loc="upper left", framealpha=1.0)

    counts = [condemned_at(by_run, t) for t in SENSITIVITY_THRESHOLDS]
    pct = [100 * c / len(by_run) for c in counts]
    sens_ax.plot([100 * t for t in SENSITIVITY_THRESHOLDS], pct,
                 marker="o", color=GREY, linewidth=2)
    chosen = 100 * condemned_at(by_run, threshold) / len(by_run)
    sens_ax.scatter([100 * threshold], [chosen], s=110, color="#b22222", zorder=5,
                    label=f"chosen: {chosen:.0f}% condemned")
    sens_ax.set_xscale("symlog", linthresh=0.1)
    sens_ax.set_xlabel("Condemnation threshold (% of events inverted)")
    sens_ax.set_ylabel("Runs condemned (%)")
    # Padded rather than clamped: a campaign that condemns nothing, or everything,
    # puts its marker centred on a spine, where the frame cuts it in half and it
    # reads as a rendering fault. The ticks still run 0 to 100.
    sens_ax.set_ylim(-4, 104)
    sens_ax.set_title("(b) The threshold is a real choice", fontsize=10)
    sens_ax.grid(True, alpha=0.3)
    sens_ax.legend(fontsize="small", loc="upper right", framealpha=1.0)


# --------------------------------------------------------------------------- network
def plot_network(ax):
    """Injected delay against delivered latency, with the acknowledgement fix marked."""
    ax.plot(NETEM["delay_ms"], NETEM["kafka_tti"], marker="o", color=KAFKA,
            linewidth=2, markersize=7, label="Kafka")
    ax.plot(NETEM["delay_ms"], NETEM["redis_tti"], marker="s", color=REDIS,
            linewidth=2, markersize=7, label="Redis (ack per message)")
    ax.plot(NETEM["delay_ms"], NETEM["delay_ms"], color=GREY, linestyle=":", linewidth=1.4,
            label="injected delay (reference)")
    ax.scatter([20], [ACK_BATCHED_TTI_MS], marker="*", s=220, color=REDIS,
               edgecolor="black", zorder=5, label="Redis (ack batched, $N$=1)")
    ax.annotate(f"batching acks:\n{ACK_UNBATCHED_TTI_MS/ACK_BATCHED_TTI_MS:.0f}$\\times$ faster",
                # Above the injected-delay reference rather than below it. At the old
                # anchor the dotted line ran through both lines of this label, which the ink
                # check could not see -- a dotted rule deposits little ink in a label's core
                # -- and which reference_lines_through_text now measures.
                xy=(20, ACK_BATCHED_TTI_MS), xytext=(24, 600.0), fontsize=8,
                # On its own white patch, the device the result figures already use where a
                # label and a rule must share space. This plot has three long series and a
                # dotted reference across five decades; there is no anchor that clears all of
                # them, and an opaque patch interrupts whichever one passes behind.
                bbox=dict(facecolor="white", edgecolor="none", pad=1.0),
                arrowprops=dict(arrowstyle="->", color="black", linewidth=1.0,
                                relpos=(0.0, 0.5)))
    ax.set_yscale("log")
    ax.set_xlabel("Injected one-way delay (ms)")
    ax.set_ylabel("End-to-end TTI, p50 (ms, log)")
    ax.set_title("A network hop reverses the ordering")
    ax.grid(True, which="both", alpha=0.3)
    # framealpha=1. The default is 0.8, and the Kafka series passes under this legend: at
    # 0.8 the line is visible through the frame and crosses a legend entry, which is a strike
    # whatever the drawing order says. An opaque frame is what makes the exemption in
    # figure_collisions.reference_lines_through_text honest.
    ax.legend(fontsize="small", loc="center left", framealpha=1.0).set_zorder(6)


# --------------------------------------------------------------------------- driver
def _save(fig, out_dir, stem, check_layout=True):
    out_dir.mkdir(parents=True, exist_ok=True)
    if check_layout:
        # Skipped only for a deliberately rescaled build: --font-scale draws the figures at a
        # size they were not laid out for, and the gates describe the shipped layout. Running
        # them on a rescaled render would report collisions nobody is going to ship.
        figure_collisions.check(fig, stem)
        figure_legibility.check(fig, stem)
        figure_vocabulary.check(fig, stem)
    written = []
    for ext in ("png", "pdf"):
        path = out_dir / f"{stem}.{ext}"
        fig.savefig(path, dpi=200, bbox_inches="tight")
        written.append(path)
    plt.close(fig)
    return written


def _read(path):
    p = Path(path)
    return pd.read_csv(p) if p.exists() else None


def main(argv=None):
    figure_style.apply()   # in force when the artists are made, not merely at import
    ap = argparse.ArgumentParser(description="Manuscript figures other than E1")
    ap.add_argument("--profiles-csv", default="docs/results/football/feed/match_profiles.csv")
    ap.add_argument("--slots-csv", default="docs/results/football/concurrency/kickoff_slots.csv")
    ap.add_argument("--timeline-csv",
                    default="docs/results/football/concurrency/in_play_timeline.csv")
    ap.add_argument("--integrity-csv",
                    default="docs/results/integrity_windows/clock_integrity_by_run.csv")
    ap.add_argument("--out", default="docs/results/figures")
    ap.add_argument("--only", default=None,
                    help="render a single figure by stem, for testing")
    ap.add_argument("--font-scale", type=float, default=1.0,
                    help="multiply every matplotlib font size; used to regenerate "
                         "figures for reduced print widths (TPDS round 2, minor 3)")
    args = ap.parse_args(argv)
    scaled = {}
    if args.font_scale != 1.0:
        for key in ("font.size", "axes.titlesize", "axes.labelsize",
                    "xtick.labelsize", "ytick.labelsize", "legend.fontsize"):
            base = plt.rcParams[key]
            if isinstance(base, str):      # named sizes like 'medium' resolve via font.size
                continue
            scaled[key] = base
            plt.rcParams[key] = base * args.font_scale
        plt.rcParams["font.size"] = float(plt.rcParams["font.size"])
    out = Path(args.out)

    written, missing = [], []

    layout_is_shipped = args.font_scale == 1.0

    def render(stem, needs, draw):
        """Render one figure if its inputs are present; record it as missing otherwise."""
        if args.only and args.only != stem:
            return
        if any(d is None for d in needs):
            missing.append(stem)
            return
        written.extend(draw())

    def _pipeline():
        # Authored at the supplement one-column width, which is where this figure now
        # lives; the main text carries the fuller version in Figure 2(a).
        fig, ax = plt.subplots(figsize=(6.50, 2.20))
        plot_pipeline(ax)
        return _save(fig, out, "pipeline_schematic", check_layout=layout_is_shipped)

    def _model():
        fig, axes = plt.subplots(2, 1, figsize=(7.16, 3.15))
        plot_model(axes)
        fig.tight_layout()
        return _save(fig, out, "measurement_model", check_layout=layout_is_shipped)

    def _quantum():
        # Single column, like the other two Mode B figures it sits beside.
        fig, axes = plt.subplots(2, 1, figsize=(3.50, 1.94),
                                 gridspec_kw={"height_ratios": [1.12, 1.0]})
        plot_quantum_geometry(axes)
        fig.tight_layout(h_pad=0.35)
        return _save(fig, out, "quantum_geometry", check_layout=layout_is_shipped)

    def _workload():
        fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
        plot_workload(axes, profiles)
        fig.tight_layout()
        return _save(fig, out, "workload_profile", check_layout=layout_is_shipped)

    def _concurrency():
        fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
        plot_concurrency(axes, slots, timeline)
        fig.tight_layout()
        return _save(fig, out, "kickoff_concurrency", check_layout=layout_is_shipped)

    def _integrity():
        fig, axes = plt.subplots(2, 1, figsize=(5.5, 4.8))
        plot_integrity(axes, integrity)
        fig.tight_layout()
        return _save(fig, out, "integrity_audit", check_layout=layout_is_shipped)

    def _network():
        fig, ax = plt.subplots(figsize=(6.5, 4.2))
        plot_network(ax)
        fig.tight_layout()
        return _save(fig, out, "network_delay", check_layout=layout_is_shipped)

    profiles = _read(args.profiles_csv)
    slots = _read(args.slots_csv)
    timeline = _read(args.timeline_csv)
    integrity = _read(args.integrity_csv)

    render("pipeline_schematic", [], _pipeline)
    render("measurement_model", [], _model)
    render("quantum_geometry", [], _quantum)
    render("workload_profile", [profiles], _workload)
    render("kickoff_concurrency", [slots, timeline], _concurrency)
    render("integrity_audit", [integrity], _integrity)
    render("network_delay", [], _network)

    for path in written:
        print(f"wrote {path}")
    for stem in missing:
        print(f"skipped {stem}: input missing")
    # --font-scale is for this call. Left set, it silently rescales every figure built later
    # in the same process, which is what happens when a test exercises it and a later test
    # builds a figure.
    for key, base in scaled.items():
        plt.rcParams[key] = base
    return 1 if missing else 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
