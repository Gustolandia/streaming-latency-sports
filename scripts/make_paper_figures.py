#!/usr/bin/env python3
"""
make_paper_figures.py
The figures the manuscript needs beyond the E1 comparison (see make_e1_figure.py).

  1. pipeline_schematic  -- where the five timestamps are taken, and which interval each
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
# Fig. 1 since 4 Oct 2026: the red of the paper's two failures, and the green of D, the
# end-to-end latency, kept apart from A's producer blue so the two brackets read as two.
# 15 Oct 2026, an internal review of the printed figures: the green was #2e7d32, which a
# deuteranope cannot tell from the waits' red (colour difference 4.9 against 62 for normal
# vision), so in Fig. 5 the I/O thread's wait read as one more latency. This blue-green keeps a
# difference of 20 or more under both red-green deficiencies and 4.5:1 contrast as text.
FAILURE_RED = "#b22222"
END_TO_END = "#00876c"
# 15 Oct 2026: the kernel's two timestamps and the latency between them, W, in a colour no
# client thread or span already wears.
KERNEL = "#6a3d9a"
# The consumer's orange is for lines and markers. As text it had 2.5:1 contrast on white, and
# Fig. 5's "recv" was the faintest type in the paper; its words and symbols are set in this
# darker orange, 4.9:1 (15 Oct 2026, the same review).
CONSUMER_INK = "#b35806"
# Labels whose maths carries subscripts, so that the subscripts print at 6.5 pt (figure_style).
MATH_PT = figure_style.MATH_PT

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

def _glyph_app(ax, x, y, motif):
    """A small application icon: a terminal window with a motif inside.

    `motif` is "lines" for the producer (it emits records) and "bars" for the consumer (it
    reads and aggregates them). Drawn with patches only, so it survives the text-layer and
    collision checks that read the figure, and it needs no image file.
    """
    ax.add_patch(plt.Rectangle((x, y), 0.46, 0.40, facecolor="white", edgecolor=GREY,
                               linewidth=1.0))
    ax.plot([x, x + 0.46], [y + 0.32, y + 0.32], color=GREY, linewidth=0.8)   # title bar
    ax.plot([x + 0.13, x + 0.33], [y - 0.06, y - 0.06], color=GREY, linewidth=1.0)  # stand
    ax.plot([x + 0.23, x + 0.23], [y - 0.06, y], color=GREY, linewidth=1.0)
    if motif == "lines":
        for k, w in enumerate((0.26, 0.18, 0.22)):
            yy = y + 0.24 - 0.07 * k
            ax.plot([x + 0.07, x + 0.07 + w], [yy, yy], color=GREY, linewidth=1.0)
    else:
        for k, h in enumerate((0.10, 0.18, 0.14)):
            ax.add_patch(plt.Rectangle((x + 0.09 + 0.10 * k, y + 0.05), 0.06, h,
                                       facecolor=GREY, edgecolor="none"))


def _glyph_queue(ax, x, y):
    """A small message-queue icon: a channel holding a row of records.

    No arrow out of it: the first draft had one and its head ran into the broker's label,
    which the layout gate caught (1.6% of the text core under ink).
    """
    ax.add_patch(plt.Rectangle((x, y), 0.50, 0.30, facecolor="white", edgecolor=GREY,
                               linewidth=1.0, joinstyle="round"))
    for k in range(3):
        ax.add_patch(plt.Rectangle((x + 0.06 + 0.14 * k, y + 0.07), 0.09, 0.16,
                                   facecolor=GREY, edgecolor="none"))


def plot_pipeline(ax):
    """Draw the replay pipeline, its five timestamps, and the spans they define."""
    # Each stage carries the icon a reader of message-broker diagrams expects -- an
    # application window for the producer and the consumer, a queue of records for the
    # broker -- beside its name (a co-author's suggestion, 2026-09-08). The icons sit in the
    # left third of each box and the name in the right two thirds.
    boxes = [(0.2, "Producer\n(replay)"), (3.8, "Broker\n(Kafka/Redis)"), (7.4, "Consumer")]
    for x, label in boxes:
        ax.add_patch(plt.Rectangle((x, 1.6), 2.4, 0.9, facecolor="white",
                                   edgecolor=GREY, linewidth=1.4))
        ax.text(x + 1.52, 2.05, label, ha="center", va="center", fontsize=8.5)
    _glyph_app(ax, 0.40, 1.88, "lines")
    _glyph_queue(ax, 3.92, 1.90)
    _glyph_app(ax, 7.60, 1.88, "bars")
    for x0, x1 in ((2.65, 3.8), (6.25, 7.4)):
        ax.annotate("", xy=(x1, 2.05), xytext=(x0, 2.05),
                    arrowprops=dict(arrowstyle="->", color=GREY, linewidth=1.2))

    # t_out since 29 Sep: every end-to-end latency the paper reports is computed to it
    # (compute_tti.py), and the paper's definition of it now says so; drawn to t_recv, the long arrow was the
    # picture of a quantity nobody measured. It carries no process label: it is the consumer's.
    stamps = [(0.6, r"$t_{\rm sched}$", "planned"), (2.4, r"$t_{\rm pub}$", "producer"),
              (4.4, r"$t_{\rm ack}$", "producer"), (7.6, r"$t_{\rm recv}$", "consumer"),
              (9.4, r"$t_{\rm out}$", "")]
    for x, sym, proc in stamps:
        ax.plot([x, x], [1.47, 1.6], color=GREY, linewidth=1.0)
        ax.text(x, 1.42, sym, ha="center", va="top", fontsize=9)
        # The stamp block moves UP rather than the span label moving down. Below it sit
        # three span arrows that cannot be rearranged without crossing each other, and the
        # empty band is above: the boxes start at 1.6. The symbol went up again, to 1.42, and
        # the tick marks were shortened to make the room. Under Arial's maths metrics a
        # subscripted symbol is 0.35 units tall, so at 1.30 its subscript sat on the process
        # name below (19-24% of the smaller label); Liberation Sans's shallower subscript, the
        # CI font, had hidden that.
        ax.text(x, 1.02, proc, ha="center", va="top", fontsize=8, color=GREY,
                style="italic")

    # "transport proxy", not "broker transport". The span from t_ack to t_recv subtracts a
    # producer-side observation of the broker's append from the consumer's receipt; the two
    # are unordered branches of one cause, so the difference is a proxy for delivery and can
    # be negative without anything impossible happening. Labelling it "broker transport" on
    # the first figure plants the causal-chain reading the paper then spends a section
    # retracting -- a co-author's finding, and the paper's own Section III-A.
    # "publish delay", the paper's name for t_pub - t_sched since 3 Oct 2026 and the
    # OpenMessaging Benchmark's (publishDelayLatency); before it, "send lag", and before that
    # "scheduling lag", which collided with the scheduling delay of the timestamping threads.
    # Likewise "publish latency" for A, "event-time latency" for the long arrow (Karimov et
    # al.'s name; "end-to-end latency" is D's now) and "processing" for the consumer's span.
    # The fourth field is where the label sits, which is the span's midpoint except for the
    # TTI. Centred, "end-to-end TTI" runs to x = 5.0 and its top meets the transport proxy's
    # left arrowhead at x = 4.4: on the printed page the arrowhead sat on the first T. The
    # collision gate scored it clean because the strike is a fraction of a percent of a
    # fourteen-character label -- see `_worst_window` in figure_collisions.py, added with
    # this fix. Moving the label left of 4.4 clears the arrowhead and still reads as naming
    # the long arrow beneath it, which is the only arrow it touches.
    # The acknowledgment lag is the middle term of the TTI decomposition and the subject of
    # the sign identity (S < 0 exactly when A > D), and until round 59 it was the one span of
    # the three the figure did not draw: a reader checking TTI = send lag + A + S against the
    # picture found two addends and the sum. It
    # goes in the gap the other two leave, from t_send to t_ack on the row they share. The
    # label is the widest of the three on the narrowest arrow -- 2.0 units against send
    # lag's 1.8 -- which is the shape of the collision item 1 of docs/infrastructure.md
    # records, so figure_collisions.py is what clears it rather than the eye.
    spans = [(0.6, 2.4, 0.46, 1.5, "publish delay"),
             (2.4, 4.4, 0.46, 3.4, "publish latency"),
             (4.4, 7.6, 0.46, 6.0, "transport proxy"),
             (7.6, 9.4, 0.46, 8.5, "processing"),
             (0.6, 9.4, 0.05, 3.1, "event-time latency")]
    for x0, x1, y, label_x, label in spans:
        ax.annotate("", xy=(x1, y), xytext=(x0, y),
                    arrowprops=dict(arrowstyle="<->", color="black", linewidth=1.0))
        # 0.16, not 0.06. "scheduling lag" was wider than the 1.8-unit arrow it names, so the
        # text overhangs both arrowheads and the arrow ruled straight through it. The gap was
        # tuned when this figure was 2.20 in tall; round 40 cut it to 1.58 in to save a page,
        # which turned 0.06 data units into about two and a half points -- less than a line.
        # A collision the checker scored as clean because the overlap is with a rule rather
        # than with other text, and one a reader sees immediately.
        ax.text(label_x, y + 0.16, label, ha="center", fontsize=8)

    # Not "two processes' clocks". The producer and the consumer are two processes on one host
    # reading one clock, and Section V exists to show the span inverts anyway; an annotation
    # naming clocks plants the rival hypothesis in the reader at the first figure, and
    # contradicts this figure's own caption, which says "when either process is delayed".
    # No mathtext here. A double arrow has no Arial glyph, falls back to Computer Modern and
    # extracts as ")", which corrupts this sentence for every reader of the text layer.
    # The red headline that used to sit here said what the caption says, in a figure that
    # is now Fig. 1 of the paper and is read with its caption. Removing it took a fifth of
    # the height off a full-width float, which buys more than the sentence did.
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 2.80)
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
                     label=f"median {profiles['burstiness'].median():.2f}×")
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


DEFAULT_TICK_MS = 1.0


def _tick_ms():
    """The scheduler tick, read as the base slice is; the literal is the same fallback."""
    try:
        import kernel_constants
        return float(kernel_constants.constants()["tick_ms"])
    except (ImportError, OSError, KeyError, ValueError):
        return DEFAULT_TICK_MS


def rest_of_a_slice_density(wait, s, h):
    """The density of R + U, R uniform on [0, s] and U on [0, h], at `wait` (ms): what a thread
    woken while another holds the CPU waits, the rest of that one's slice and then up to a
    tick (Supplement S16.10). A trapezoid: rising across the shorter of the two, level between,
    falling to zero at s + h."""
    low, high = min(s, h), max(s, h)
    if wait <= 0 or wait >= s + h:
        return 0.0
    if wait < low:
        return wait / (s * h)
    if wait <= high:
        return 1.0 / high
    return (s + h - wait) / (s * h)


def plot_model(axes):
    """The measurement-failure model, drawn rather than only stated.

    (a) why inversion happens: measured transport is the true value displaced by the asymmetry
        in stamping delay, so it goes negative whenever that asymmetry exceeds the true value.
    (b) why the check bites hardest on small effects (H1): the same Delta distribution overlaps
        a small T_true almost entirely and a large one hardly at all.
    """
    mech_ax, h1_ax = axes
    plot_mechanism(mech_ax)
    plot_delta(h1_ax)


def plot_system(ax):
    """Panel (a) of Fig. 1: where everything runs, the two legs, and where each clock is read.

    4 Oct 2026, the author: the introduction needs a diagram that makes the system clear to an
    engineer or scientist from outside the field -- which machine runs the broker and which the
    other two, what the broker does, what one leg and two legs are -- "where all fundamental
    quantities are very clear". Panel (b) below says when each timestamp is read; this panel
    says where. A covers leg 1 out and back, D covers leg 1 and then leg 2, and the two red
    labels mark the late reading of t_ack and, outside the consumer's box, a tool that reports D
    in steps of tau and drops every value at or below zero.
    """
    ax.set_xlim(0, 10.4)
    # Stacked labels are spaced for CI's matplotlib 3.9, which sets an 8 pt label with maths in
    # a box about 10-11 pt tall, against 8-8.7 pt on the author's machine: at 0.25 apart (9.7 pt)
    # it reported two lines of the producer's box printed over each other (4 Oct 2026). The
    # lines in a box are now 0.33 apart (12.8 pt), a title and its first line 0.30 (11.6 pt),
    # the network column's two labels 0.27 (10.5 pt). The boxes are 0.98 tall to hold that,
    # and the panel starts at -0.06 to hold the boxes. 15 Oct 2026: from (-0.10, 2.80) to the
    # machines' frames, a hair outside each so that neither stroke is cut, for the page budget.
    ax.set_ylim(*SYSTEM_YLIM)
    ax.axis("off")

    # The two machines, and the network between them. "Client machine", not "Client machine
    # (the driver)": the text never defines the driver, and uses the word for network and
    # benchmark drivers (15 Oct 2026, an internal review).
    for x0, x1, label in ((0.05, 4.05, "Client machine"),
                          (6.55, 10.35, "Broker machine")):
        ax.add_patch(plt.Rectangle((x0, -0.04), x1 - x0, 2.74, fill=False, edgecolor=GREY,
                                   linewidth=1.0))
        ax.text(x0 + 0.12, 2.54, label, fontsize=8, fontweight="bold", color=GREY,
                ha="left", va="center")
    ax.text(5.30, 2.54, "network", fontsize=8, color=GREY, style="italic", ha="center",
            va="center")

    # The two client processes, which read one clock: the fact that keeps clock
    # synchronization out of every result in the paper. The producer's box is 3.35 wide so that
    # its I/O thread's line clears the red label of the late reading.
    procs = ((1.38, 2.36, "Producer process", KAFKA, KAFKA,
              (r"app thread: $t_{\mathrm{sched}}$, $t_{\mathrm{pub}}$",
               r"I/O thread: $t_{\mathrm{ack}}$")),
             (0.35, 1.00, "Consumer process", REDIS, CONSUMER_INK,
              (r"app thread: $t_{\mathrm{recv}}$, $t_{\mathrm{out}}$",)))
    for y0, y1, title, colour, ink, lines in procs:
        ax.add_patch(plt.Rectangle((0.20, y0), 3.35, y1 - y0, fill=False, edgecolor=colour,
                                   linewidth=1.1))
        ax.text(0.32, y1 - 0.15, title, fontsize=8, fontweight="bold", color=ink,
                ha="left", va="center")
        # Each line names its thread's timestamps, set at MATH_PT so that the subscripts print
        # at 6.5 pt; the 12.8 pt pitch still leaves 2.7 pt between the boxes (15 Oct 2026).
        for k, line in enumerate(lines):
            ax.text(0.32, y1 - 0.45 - 0.33 * k, line, fontsize=MATH_PT, ha="left",
                    va="center")
    # The late read of t_ack, by the producer's own I/O thread.
    ax.text(3.45, 2.36 - 0.78, "read late", fontsize=8, fontweight="bold", color=FAILURE_RED,
            ha="right", va="center")
    # 15 Oct 2026, a referee: inside the consumer's box, "drops <= 0" and "reports D in steps of
    # tau" read as properties of our own consumer, which keeps every value at microsecond
    # resolution. They are what a tool of Section V does, so they sit outside the box, under the
    # tool's own name, as the caption says. The box lost its second line and its lower third.
    ax.text(0.32, 0.15, r"a tool that reports $D$ in steps of $\tau$ and drops $\leq 0$",
            fontsize=8, color=FAILURE_RED, ha="left", va="center")
    ax.text(1.875, 1.19, "both processes read one clock", fontsize=8, color=GREY,
            ha="center", va="center")

    # The broker and its three jobs, each beside the arrow that carries it out.
    ax.add_patch(plt.Rectangle((6.75, 0.16), 3.45, 2.18, fill=False, edgecolor=GREY,
                               linewidth=1.1))
    ax.text(6.87, 2.18, "Broker (Kafka or Redis)", fontsize=8, fontweight="bold",
            ha="left", va="center")
    for y, line in ((1.90, "1  writes the message to its log"),
                    (1.52, "2  acknowledges it to the producer"),
                    (0.50, "3  delivers it to the consumer")):
        ax.text(6.87, y, line, fontsize=8, ha="left", va="center")
    # The order drawn is Kafka's. Redis writes the delivery to a waiting consumer first, and
    # in 16 of its 24 runs of freeze 41 the delivery came first (Sections II and IV-A; 15 Oct
    # 2026, an internal review), so the note sits in the gap between its two jobs.
    ax.text(6.87, 1.01, "(Redis: often 3 before 2)", fontsize=8, color=GREY, ha="left",
            va="center")

    # The legs. Leg 1 carries the message out and the acknowledgment back; leg 2 carries the
    # message on to the consumer.
    ax.annotate("", xy=(6.75, 1.90), xytext=(3.55, 1.90),
                arrowprops=dict(arrowstyle="->", color="black", linewidth=1.3))
    ax.text(5.30, 1.98, "leg 1: publish", fontsize=8, ha="center", va="bottom")
    ax.annotate("", xy=(3.55, 1.52), xytext=(6.75, 1.52),
                arrowprops=dict(arrowstyle="->", color="black", linewidth=1.0,
                                linestyle=(0, (4, 2))))
    ax.text(5.30, 1.60, "acknowledgment", fontsize=8, ha="center", va="bottom")
    ax.annotate("", xy=(3.55, 0.50), xytext=(6.75, 0.50),
                arrowprops=dict(arrowstyle="->", color="black", linewidth=1.3))
    ax.text(5.30, 0.58, "leg 2: deliver", fontsize=8, ha="center", va="bottom")

    # What the two latencies cover, said between the legs.
    ax.text(5.30, 1.25, r"$A$: leg 1, out and back", fontsize=8, color=KAFKA, ha="center",
            va="center")
    ax.text(5.30, 0.98, r"$D$: leg 1, then leg 2", fontsize=8, color=END_TO_END,
            ha="center", va="center")


def plot_mechanism(mech_ax):
    """Panel (b) of Fig. 1: the timestamps, the four threads, and the inversion."""

    # --- (a) the mechanism, as a timeline
    #
    # A reader (Kunkel, v3 correspondence, item A1) could not place the acknowledgement in
    # the producer's own sequence because the panel showed only the ack and the receive,
    # while Eq. (1) is written in t_sched and t_send. Both now sit on the producer timeline
    # to the left of the acknowledgement, with the scheduling-lag bracket that ties them to
    # Eq. (1). The start-at-ack framing of the inversion itself is unchanged: the failure
    # is between the two clock reads, and that is what the red bracket still marks.
    # The architecture first, then the failure it permits.
    #
    # v3. This panel used to have ONE lane called "producer thread", which asserts that a
    # single thread takes both t_send and t_ack. Our own pre-registration
    # (docs/preregistration_depth.md) says otherwise, and says it in a table:
    #
    #   redis_producer.py   t_ack after a blocking XADD returns   the calling thread
    #   kafka_producer.py   t_ack in the delivery callback        the client's I/O thread
    #
    # E-C3 is pre-registered to MOVE that stamp (--ack-stamp inline), so the split is the
    # manipulated variable of one of the paper's own experiments. Drawing one lane erased it.
    # Two lanes now, the drawn path is named as the Kafka one, and Redis's contrasting stamp
    # is marked on the thread that actually takes it.
    mech_ax.set_xlim(0, 10.4)
    # Down to -0.75 since 4 Oct 2026, for the D, A and E brackets under the consumer lane, whose
    # labels stack 0.50 apart: 11.7 pt, against the 10.1 pt box CI's matplotlib 3.9 gives each.
    # Up to 4.98 since 15 Oct 2026, from 5.25: the process box's label moved to the panel's
    # title row (below), which freed the row above the box (an internal review of the printed
    # figures, "Shortening Fig. 1").
    mech_ax.set_ylim(*MECH_YLIM)
    mech_ax.axis("off")

    # The producer's two lanes 0.88 and 0.90 apart, not 1.00 and 1.05 (15 Oct 2026, for the page
    # budget): the labels between them keep 4 pt to the lanes, and the two-line lane names 3.8 pt
    # to each other, so that they still read as two names.
    y_app, y_io, y_brk, y_con = Y_APP, Y_IO, 2.25, 1.15
    for y, label, colour in ((y_app, "producer app" + NL + "thread", KAFKA),
                             (y_io, "client I/O" + NL + "thread", KAFKA),
                             (y_brk, "broker", GREY),
                             (y_con, "consumer app" + NL + "thread", CONSUMER_INK)):
        mech_ax.annotate("", xy=(9.9, y), xytext=(2.45, y),
                         arrowprops=dict(arrowstyle="->", color=GREY, linewidth=1.2))
        mech_ax.text(0.05, y, label, fontsize=8, color=colour, ha="left", va="center",
                     linespacing=0.95)

    # The process boundary, and with it the clock. "On one clock by construction" is what
    # excludes skew in III-C, and a reader had to take it from prose; here it is drawn. Both
    # producer threads are in one process, so the two stamps cannot disagree about the epoch.
    # The lower edge sits 0.75 under the I/O lane, clear of the delta-ack label under it, as it
    # did before 15 Oct 2026 (2.55 under 3.30). At 0.55 under it it ran through that label's subscript
    # under matplotlib 3.9.4 in all three fonts the gate was run with (5-6% of the label's core);
    # CI's matplotlib 3.10 happened not to flag it. The top edge sits 0.63 over the producer's
    # lane, over the MATH_PT symbols above it.
    box_lo, box_hi = y_io - 0.75, y_app + 0.63
    mech_ax.add_patch(plt.Rectangle((2.38, box_lo), 7.62, box_hi - box_lo, fill=False, zorder=0,
                                    edgecolor=KAFKA, linewidth=0.7, linestyle=(0, (4, 2))))
    # Its label on the panel's title row, right of the panel's own title, above the box's
    # right-hand corner: one row less than inside the panel. It says that the consumer reads the
    # same clock, since "one producer process, one clock" could be taken to give the producer a
    # clock of its own, in a paper whose finding needs one clock (15 Oct 2026, an internal
    # review).
    mech_ax.set_title("producer process; the consumer reads the same clock", loc="right",
                      fontsize=8, color=KAFKA, pad=TITLE_PAD)

    # the producer's own two stamps, taken on the app thread before the acknowledgment exists
    for x, sym in ((2.95, r"$t_{\mathrm{sched}}$"), (3.65, r"$t_{\mathrm{pub}}$")):
        mech_ax.plot([x], [y_app], marker="o", markersize=5, color=KAFKA,
                     markerfacecolor="white", markeredgewidth=1.2)
        # 0.24 above the lane, midway between the marker and the box's top edge. At 0.28 that
        # edge crossed the top of both symbols under Arial's taller maths boxes.
        mech_ax.text(x, y_app + 0.24, sym, fontsize=MATH_PT, ha="center", color=KAFKA)
    mech_ax.annotate("", xy=(3.65, y_app), xytext=(2.95, y_app),
                     arrowprops=dict(arrowstyle="<->", color=GREY, linewidth=0.9))
    # Backed in white: the guide that carries t_sched down to the E bracket runs behind it.
    mech_ax.text(3.55, y_app - 0.20, "publish delay", fontsize=8, color=GREY, ha="right",
                 va="top", zorder=3,
                 bbox=dict(facecolor="white", edgecolor="none", pad=0.6))

    # The broker's append, and the two branches descending from it.
    #
    # Without this the panel is a left-to-right sequence of events on parallel lines, which
    # invites precisely the reading Section III-C exists to refute: that the acknowledgment
    # causally precedes the record's arrival. It does not. Both descend from the append and
    # neither precedes the other, which is why their difference may be negative with no
    # physical impossibility.
    mech_ax.plot([4.15], [y_brk], marker="D", markersize=5.5, color=GREY)
    mech_ax.text(4.15, y_brk - 0.22, "append", fontsize=8, color=GREY, ha="center", va="top")
    mech_ax.annotate("", xy=(4.05, y_brk + 0.12), xytext=(3.70, y_app - 0.12),
                     arrowprops=dict(arrowstyle="->", color=GREY, linewidth=0.9,
                                     linestyle=(0, (3, 2))))
    for tip_x, tip_y in ((4.85, y_io - 0.12), (5.75, y_con + 0.12)):
        mech_ax.annotate("", xy=(tip_x, tip_y), xytext=(4.28, y_brk),
                         arrowprops=dict(arrowstyle="->", color=GREY, linewidth=0.9,
                                         linestyle=(0, (3, 2))))

    # physical events (true), and the later moments the software actually reads the clock.
    # 15 Oct 2026: each arrival carries the kernel's receive timestamp, which no thread's wait
    # delays: t_rx,ack for the acknowledgment and t_rx for the record (Section VI, Fig. 5).
    mech_ax.plot([4.95], [y_io], marker="|", markersize=13, color=KAFKA)
    mech_ax.text(4.95, y_io + 0.30, r"ack arrives, $t_{\mathrm{rx,ack}}$", fontsize=MATH_PT,
                 ha="center")
    mech_ax.plot([7.10], [y_io], marker="o", markersize=6, color=KAFKA)
    mech_ax.text(7.10, y_io + 0.30, r"clock read $\rightarrow t_{\mathrm{ack}}$",
                 fontsize=MATH_PT, ha="center")
    mech_ax.annotate("", xy=(7.10, y_io), xytext=(4.95, y_io),
                     arrowprops=dict(arrowstyle="<->", color="#b22222", linewidth=1.2))
    # The thread's delay, which holds any wait for a core, as Section IV-A says: on Kafka its
    # median is 163-180 us of the client's own processing, the wait only in its tail (freeze
    # 41). "waiting for a core" said the delay was all wait (15 Oct 2026, an internal review).
    mech_ax.text(6.02, y_io - 0.20, r"$\delta_{\mathrm{ack}}$: the thread's delay",
                 fontsize=MATH_PT, color="#b22222", ha="center", va="top")

    mech_ax.plot([5.85], [y_con], marker="|", markersize=13, color=REDIS)
    # "message", the paper's word: it calls no message a record (15 Oct 2026).
    # 0.15 below the lane, not 0.22, as "clock read" beside it (16 Oct 2026): CI's matplotlib 3.9
    # sets this maths box about 2.4 pt taller, downward from the top it is anchored by, and at
    # 0.22 the D bracket's line ran through 4.2% of its core.
    mech_ax.text(5.75, y_con - 0.15, r"message arrives, $t_{\mathrm{rx}}$", fontsize=MATH_PT,
                 ha="right", va="top")

    # The margin m, from the acknowledgment's arrival to the record's (15 Oct 2026, both
    # referees): the waiting-probability law conditions on it, and the figure is where the
    # vocabulary is defined.
    # Drawn between the broker's lane and the record's dashed branch, which at y = 1.95 lies left
    # of the acknowledgment's guide, so the bracket crosses nothing; the label sits in a white
    # break of its own bracket, the only place between the lane and the branch with room for it.
    y_m = 1.95
    for x, y0 in ((4.95, y_io - 0.28), (5.85, y_con + 0.28)):
        mech_ax.plot([x, x], [y0, y_m], color=GREY, linewidth=0.7, linestyle=(0, (1, 2)),
                     zorder=0)
    mech_ax.annotate("", xy=(5.85, y_m), xytext=(4.95, y_m),
                     arrowprops=dict(arrowstyle="<->", color="black", linewidth=0.9,
                                     shrinkA=0, shrinkB=0))
    mech_ax.text(5.40, y_m, "$m$", fontsize=8, ha="center", va="center", zorder=3,
                 bbox=dict(facecolor="white", edgecolor="none", pad=0.6))
    mech_ax.plot([6.45], [y_con], marker="o", markersize=6, color=REDIS)
    # 0.15 below the lane, not 0.22: under Arial's taller maths box the label sat on the note
    # beneath it (17% of the label). It still clears the orange marker above.
    # Right of its own marker since 4 Oct 2026: the guide that carries t_recv down to the D
    # bracket runs through x = 6.45, which is where this label used to be centred.
    mech_ax.text(6.60, y_con - 0.15, r"clock read $\rightarrow t_{\mathrm{recv}}$",
                 fontsize=MATH_PT, ha="left", va="top")
    mech_ax.annotate("", xy=(6.45, y_con), xytext=(5.85, y_con),
                     arrowprops=dict(arrowstyle="<->", color="#b22222", linewidth=1.2))
    mech_ax.text(6.15, y_con + 0.24, r"$\delta_{\mathrm{recv}}$", fontsize=MATH_PT,
                 color="#b22222", ha="center")

    # The inversion itself, drawn as the backwards span it is.
    #
    # The arrow alone floated: it sat between two lanes joining nothing visible, so the
    # reader had to be told which two stamps it spans. The guides drop from the two clock
    # reads, which is what makes "later stamp, earlier value" a thing you can see rather
    # than a thing you parse.
    mech_ax.plot([7.10, 7.10], [Y_S_ARROW, y_io], color=KAFKA, linewidth=0.8,
                 linestyle=(0, (2, 2)), zorder=0)
    mech_ax.plot([6.45, 6.45], [y_con, Y_S_ARROW], color=REDIS, linewidth=0.8,
                 linestyle=(0, (2, 2)), zorder=0)
    mech_ax.annotate("", xy=(6.45, Y_S_ARROW), xytext=(7.10, Y_S_ARROW),
                     arrowprops=dict(arrowstyle="->", color="#b22222", linewidth=1.3))
    # Labelled in the paper's own model (Section II): S is the acknowledgment-referenced
    # span and D the delivery time, so the inversion reads S < 0 although D > 0 -- not a
    # T_meas/T_true pair the text never defines (co-author comment 16, 2026-09-08). "The
    # delivery time", not "the delivery": the manuscript never uses the bare word for D (1 Oct).
    # Two lines in two sizes since 15 Oct 2026: the definition, whose subscripts are what the
    # reader compares, at MATH_PT, and the sentence under it at 8 pt; set as one label at
    # MATH_PT the second line ran past the panel's right edge.
    mech_ax.text(7.30, Y_S_ARROW + 0.235, r"$S=t_{\mathrm{recv}}-t_{\mathrm{ack}}<0$",
                 fontsize=MATH_PT, color="#b22222", ha="left", va="center")
    mech_ax.text(7.30, Y_S_ARROW - 0.205, r"although the end-to-end latency $D>0$", fontsize=8,
                 color="#b22222", ha="left", va="center")

    # The consumer's last stamp, once it has handled the message. Backed in white: the guide
    # that carries t_out down to the E bracket runs behind its label.
    x_out = 9.45
    # Above the label's backing, which otherwise covers the marker's lower half. 0.18 below the
    # lane, not 0.15: at 0.15 the backing touched the marker (15 Oct 2026, an internal review).
    mech_ax.plot([x_out], [y_con], marker="o", markersize=6, color=REDIS, zorder=4)
    mech_ax.text(x_out, y_con - 0.18, r"handled $\rightarrow t_{\mathrm{out}}$",
                 fontsize=MATH_PT, ha="center", va="top", zorder=3,
                 bbox=dict(facecolor="white", edgecolor="none", pad=0.6))

    # A and D, the two latencies the inversion compares, drawn from the same t_pub (4 Oct
    # 2026). Stacked, the reader sees A run past D, which is the sign identity: S < 0 exactly
    # when A > D. Below them E, from t_sched to t_out, which the eye can read as the publish
    # delay, then D, then the processing-time latency that continues D's row: every quantity
    # of Section II-B is drawn (4 Oct 2026, the author: "the diagram for the whole system where
    # all fundamental quantities are very clear"). The labels sit left of the brackets, clear
    # of the guide that carries t_sched down. 0.04 lower since 15 Oct 2026, under the consumer's
    # MATH_PT labels.
    y_d, y_a, y_e = 0.48, -0.02, -0.52
    for x, y0, y1 in ((2.95, y_app - 0.12, y_e), (3.65, y_app - 0.12, y_a - 0.04),
                      (6.45, y_con, y_d), (x_out, y_con, y_e)):
        mech_ax.plot([x, x], [y0, y1], color=GREY, linewidth=0.7, linestyle=(0, (1, 2)),
                     zorder=0)
    for y, x0, x1, colour, label in (
            (y_d, 3.65, 6.45, END_TO_END, r"$D$: end-to-end latency"),
            (y_a, 3.65, 7.10, KAFKA, r"$A$: publish latency"),
            (y_e, 2.95, x_out, "black", r"$E$: event-time latency")):
        mech_ax.annotate("", xy=(x1, y), xytext=(x0, y),
                         arrowprops=dict(arrowstyle="<->", color=colour, linewidth=1.1))
        mech_ax.text(2.85, y, label, fontsize=8, color=colour, ha="right", va="center")
    mech_ax.annotate("", xy=(x_out, y_d), xytext=(6.45, y_d),
                     arrowprops=dict(arrowstyle="<->", color=GREY, linewidth=1.1))
    mech_ax.text(8.30, y_d - 0.08, "processing-time latency", fontsize=8, color=GREY,
                 ha="center", va="top")

    # The other broker's path, named rather than implied -- and named CAREFULLY.
    #
    # S43.3 is titled "the second thread is not the mechanism" and means it: the harness was
    # built expecting the hand-off to be the cause and the corpus refused. Redis, which
    # stamps inline on the calling thread and never has a second thread, inverts on a LARGER
    # share of runs than Kafka does. A thread returning from a blocking read must also be
    # made runnable and scheduled before it can call the clock, and that wait is charged to
    # the measurement exactly as a callback dispatch would be.
    #
    # So this note may not say "and E-C3 moves the stamp there too", which invites the
    # reading that moving it fixes the sign. It does not. The hand-off is an increment on
    # top of the wakeup, worth tens of microseconds of median, not the thing itself.
    # v5 (28 Sep): the note that used to sit here -- "Kafka path drawn. Redis timestamps t_ack
    # on the app thread and inverts anyway" -- moved to the caption, which says it in one
    # clause. An outside editor's reading found the drawing too busy to read at a glance, and
    # the note was the one element carrying no part of the mechanism itself.


#: Fig. 1(a)'s vertical extent, in its own units (15 Oct 2026; see plot_system).
SYSTEM_YLIM = (-0.06, 2.72)
#: Fig. 1(b)'s producer lanes and vertical extent, in its own units (15 Oct 2026; see
#: plot_mechanism): the extent ends just over the process box's top edge, 0.63 over Y_APP.
Y_APP, Y_IO = 4.03, 3.15
MECH_YLIM = (-0.72, Y_APP + 0.68)
#: The height of the inversion's arrow in Fig. 1(b), between the broker's lane and the
#: consumer's, with its two-line label centred on it.
Y_S_ARROW = 1.74
#: The gap between a panel and its title, in points: 3, from matplotlib's 6, in Fig. 1, whose
#: titles sit over axis-free panels with nothing to clear (15 Oct 2026).
TITLE_PAD = 3.0
#: Fig. 1's layout, in points (15 Oct 2026; see _model). Each panel keeps the scale it had,
#: 38.8 pt a unit in (a) and 23.5 in (b), so that every gap between its labels is as it was; the
#: title rows hold an 8 pt title over a 3 pt pad; the canvas is their sum, at the text width.
MODEL_PT_PER_UNIT = (38.8, 23.5)
MODEL_TOP_PT, MODEL_GAP_PT, MODEL_BOTTOM_PT = 12.7, 12.2, 1.0
MODEL_PANELS_PT = ((SYSTEM_YLIM[1] - SYSTEM_YLIM[0]) * MODEL_PT_PER_UNIT[0],
                   (MECH_YLIM[1] - MECH_YLIM[0]) * MODEL_PT_PER_UNIT[1])
MODEL_FIG_IN = (figure_legibility.TEXT_WIDTH_IN,
                (MODEL_TOP_PT + MODEL_GAP_PT + MODEL_BOTTOM_PT + sum(MODEL_PANELS_PT)) / 72.0)

#: Fig. 5's canvas, in inches, and the panel is laid out in inches too, so that a gap in the code
#: is a gap on the page. The column's 3.5 in exactly, saved whole, so that the page prints it at
#: its own size (15 Oct 2026; see _kernel).
KERNEL_FIG_IN = (3.5, 1.90)


def plot_kernel_fix(ax):
    """Section VI's figure: where the kernel timestamps a message, and where the waits fall.

    15 Oct 2026, the author: the general solution must be clearly explained for the industry.
    Redrawn the same day on Fig. 1(b)'s four lanes, at a referee's request: one lane for "client
    threads" made the producer's threads and the consumer's look like one, only the consumer's
    wait was drawn although H_out holds the producer's too (on Kafka, the background thread that
    writes the message to the network), and the acknowledgment was missing, so the drawing did
    not reach the paper's finding about S. Now the producer's I/O thread waits for a core before
    the kernel timestamps the message as it leaves, t_tx; the acknowledgment and the record each
    arrive with the kernel's receive timestamp, t_rx,ack and t_rx, before a thread waits and
    reads the clock; and the consumer's fetch request reaches the broker before the message
    does. Under the lanes, D over its three parts, so the eye finds both waits outside W.
    """
    width, height = KERNEL_FIG_IN
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")

    # 15 Oct 2026: the symbols set at MATH_PT, so that their subscripts print at 6.5 pt, and
    # every lane 0.02 in higher on a canvas 0.04 in taller, so that the labels at the top and the
    # bottom keep the 2.5 pt CI's matplotlib 3.9 needs for its taller maths boxes. The canvas is
    # still shorter than the file it replaces, which the page enlarged.
    y_app, y_io, y_brk, y_con = 1.66, 1.35, 0.98, 0.61
    x_lane, x_end = 0.74, 3.42
    for y, label, colour in ((y_app, "producer app" + NL + "thread", KAFKA),
                             (y_io, "client I/O" + NL + "thread", KAFKA),
                             (y_brk, "broker", GREY),
                             (y_con, "consumer app" + NL + "thread", CONSUMER_INK)):
        ax.annotate("", xy=(x_end, y), xytext=(x_lane, y),
                    arrowprops=dict(arrowstyle="->", color=GREY, linewidth=1.0))
        ax.text(0.03, y, label, fontsize=8, color=colour, ha="left", va="center",
                linespacing=0.95)

    x_pub, x_hand, x_tx, x_append = 0.86, 0.92, 1.44, 1.66
    x_rxack, x_ack, x_rx, x_recv = 2.10, 2.48, 2.68, 3.14
    x_req, x_req_in = 0.98, 1.20
    dashed = dict(color=GREY, linewidth=0.9, linestyle=(0, (3, 2)))

    # The producer's publish call, and the hand-off to the I/O thread that writes the message.
    ax.plot([x_pub], [y_app], marker="o", markersize=5, color=KAFKA)
    ax.text(x_pub, y_app + 0.06, r"$t_{\mathrm{pub}}$", fontsize=MATH_PT, color=KAFKA,
            ha="center", va="bottom")
    ax.annotate("", xy=(x_hand, y_io + 0.03), xytext=(x_pub + 0.01, y_app - 0.04),
                arrowprops=dict(arrowstyle="->", **dashed))
    # The kernel's three timestamps, the message leaving and the acknowledgment and the record
    # arriving, none of which waits for a thread.
    for x, y in ((x_tx, y_io), (x_rxack, y_io), (x_rx, y_con)):
        ax.plot([x], [y], marker="|", markersize=10, color=KERNEL, markeredgewidth=1.4)
    for x, sym in ((x_tx, r"$t_{\mathrm{tx}}$"), (x_rxack, r"$t_{\mathrm{rx,ack}}$")):
        ax.text(x, y_io + 0.07, sym, fontsize=MATH_PT, color=KERNEL, ha="center", va="bottom")
    ax.text(x_rx + 0.04, y_con - 0.06, r"$t_{\mathrm{rx}}$", fontsize=MATH_PT, color=KERNEL,
            ha="left", va="top")
    # The message's path: out to the broker's append, and back as the acknowledgment and as the
    # record, which the broker sends in answer to the consumer's fetch request.
    ax.annotate("", xy=(x_append - 0.04, y_brk + 0.03), xytext=(x_tx + 0.02, y_io - 0.05),
                arrowprops=dict(arrowstyle="->", **dashed))
    ax.plot([x_append], [y_brk], marker="D", markersize=4.5, color=GREY)
    ax.annotate("", xy=(x_rxack - 0.02, y_io - 0.05), xytext=(x_append + 0.04, y_brk + 0.03),
                arrowprops=dict(arrowstyle="->", **dashed))
    ax.annotate("", xy=(x_rx - 0.02, y_con + 0.05), xytext=(x_append + 0.04, y_brk - 0.03),
                arrowprops=dict(arrowstyle="->", **dashed))
    ax.annotate("", xy=(x_req_in, y_brk), xytext=(x_req, y_con),
                arrowprops=dict(arrowstyle="->", color=REDIS, linewidth=0.9,
                                linestyle=(0, (3, 2)), shrinkA=0, shrinkB=0))
    ax.text((x_req + x_req_in) / 2 + 0.05, (y_con + y_brk) / 2, "fetch", fontsize=8,
            color=CONSUMER_INK, ha="left", va="center")

    # The threads' delays, which hold any wait for a core, and the clock reads they delay. Each
    # is named, the I/O thread's delay before it writes the message too: unnamed, and in the red
    # of the latencies' brackets' shape, it read as one more latency (15 Oct 2026, an internal
    # review of the printed figures).
    for x0, x1, y in ((x_hand, x_tx, y_io), (x_rxack, x_ack, y_io), (x_rx, x_recv, y_con)):
        ax.annotate("", xy=(x1, y), xytext=(x0, y),
                    arrowprops=dict(arrowstyle="<->", color=FAILURE_RED, linewidth=1.1,
                                    shrinkA=0, shrinkB=0))
    ax.text((x_hand + x_tx) / 2, y_io - 0.07, r"$\delta_{\mathrm{tx}}$", fontsize=MATH_PT,
            color=FAILURE_RED, ha="center", va="top")
    ax.text((x_rxack + x_ack) / 2, y_io - 0.07, r"$\delta_{\mathrm{ack}}$", fontsize=MATH_PT,
            color=FAILURE_RED, ha="center", va="top")
    ax.text((x_rx + x_recv) / 2, y_con + 0.07, r"$\delta_{\mathrm{recv}}$", fontsize=MATH_PT,
            color=FAILURE_RED, ha="center", va="bottom")
    for x, y, colour in ((x_ack, y_io, KAFKA), (x_recv, y_con, REDIS)):
        ax.plot([x], [y], marker="o", markersize=5, color=colour, zorder=4)
    ax.text(x_ack, y_io + 0.07, r"$t_{\mathrm{ack}}$", fontsize=MATH_PT, color=KAFKA,
            ha="center", va="bottom")
    ax.text(x_recv + 0.04, y_con - 0.06, r"$t_{\mathrm{recv}}$", fontsize=MATH_PT,
            color=CONSUMER_INK, ha="left", va="top")
    # What the purple ticks and the red arrows are, said once, level with t_pub's label so that
    # the key costs no height. "a thread's delay", which holds any wait for a core, as Section
    # IV-A says; "waits for a core" said the delay was all wait (15 Oct 2026, an internal review).
    y_key = y_app + 0.12
    ax.plot([1.40], [y_key], marker="|", markersize=10, color=KERNEL, markeredgewidth=1.4)
    ax.text(1.45, y_key, "kernel timestamp", fontsize=8, color=KERNEL, ha="left", va="center")
    ax.annotate("", xy=(2.62, y_key), xytext=(2.42, y_key),
                arrowprops=dict(arrowstyle="<->", color=FAILURE_RED, linewidth=1.1,
                                shrinkA=0, shrinkB=0))
    ax.text(2.66, y_key, "a thread's delay", fontsize=8, color=FAILURE_RED, ha="left",
            va="center")

    # The kernel-timed order, from the acknowledgment's arrival to the record's: no thread's
    # wait is in it, and S = S_k + delta_recv - delta_ack. 0.11 under the broker's lane, not
    # 0.09, for the label's MATH_PT box (15 Oct 2026).
    y_s = y_brk - 0.11
    for x, y0 in ((x_rxack, y_io - 0.07), (x_rx, y_con + 0.07)):
        ax.plot([x, x], [y0, y_s], color=KERNEL, linewidth=0.7, linestyle=(0, (1, 2)), zorder=0)
    ax.annotate("", xy=(x_rx, y_s), xytext=(x_rxack, y_s),
                arrowprops=dict(arrowstyle="<->", color=KERNEL, linewidth=0.9, shrinkA=0,
                                shrinkB=0))
    ax.text((x_rxack + x_rx) / 2, y_s, "$S_k$", fontsize=MATH_PT, color=KERNEL, ha="center",
            va="center", zorder=3, bbox=dict(facecolor="white", edgecolor="none", pad=0.6))

    # Guides down to the brackets: D from the threads' readings, its parts from the kernel's
    # timestamps too. D's label sits between W's two guides, clear of both. The labels under
    # the brackets hang 0.04 below them, not 0.035: at 0.035 W's arrowheads touched its label
    # (15 Oct 2026, an internal review of the printed figures).
    y_d, y_h = y_con - 0.225, y_con - 0.395
    for x, y0 in ((x_pub, y_app - 0.07), (x_tx, y_io - 0.07), (x_rx, y_con - 0.07),
                  (x_recv, y_con - 0.07)):
        ax.plot([x, x], [y0, y_h], color=GREY, linewidth=0.7, linestyle=(0, (1, 2)), zorder=0)
    ax.annotate("", xy=(x_recv, y_d), xytext=(x_pub, y_d),
                arrowprops=dict(arrowstyle="<->", color=END_TO_END, linewidth=1.1, shrinkA=0,
                                shrinkB=0))
    ax.text((x_tx + x_rx) / 2, y_d + 0.035, r"$D$: end-to-end latency", fontsize=8,
            color=END_TO_END, ha="center", va="bottom")
    for x0, x1, label, colour, size in (
            (x_pub, x_tx, r"$H_{\mathrm{out}}$", GREY, MATH_PT),
            (x_tx, x_rx, r"$W$: kernel-timed latency", KERNEL, 8),
            (x_rx, x_recv, r"$H_{\mathrm{in}}$", GREY, MATH_PT)):
        ax.annotate("", xy=(x1, y_h), xytext=(x0, y_h),
                    arrowprops=dict(arrowstyle="<->", color=colour, linewidth=1.1, shrinkA=0,
                                    shrinkB=0))
        ax.text((x0 + x1) / 2, y_h - 0.04, label, fontsize=size, color=colour, ha="center",
                va="top")


def plot_delta(h1_ax):
    """The stamping-asymmetry density, schematic. Supplement only: it is a drawing,
    and the measured version of this object is the traced stall spectrum in the main text.
    """
    # why small effects are fragile
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
    # is running and a lobe near -3 ms when it is not. That is the two-state model made visible:
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
    #
    # v5 (28 September 2026): the lobe AT the slice was wrong for the thread that matters, and
    # a measurement says so. A9 timed the wait of the thread that timestamps each
    # acknowledgment: it waits out the REST of another task's slice, spread from nothing to
    # the slice and ending a tick past it (Supplement S16.10). A lobe at the slice is what a
    # thread PREEMPTED meets, and it is what the pre-registered law's plateau assumed; the
    # campaign found no plateau. So the second state is now that wait's own shape, a shelf,
    # with the slice and the tick the kernel sets and nothing else chosen.
    slice_ms, tick_ms = _base_slice_ms(), _tick_ms()
    x = np.linspace(-6, 6, 1200)
    core = 0.70 * np.exp(-0.5 * (x / 0.22) ** 2)            # RUNNING: narrow jitter core
    shelf = 0.30 * np.array([rest_of_a_slice_density(-v, slice_ms, tick_ms) for v in x])
    # A flat-ish background so the density stays on the axis across the whole range: both
    # threads can stall, so there is mass on the positive side too, and a curve that falls
    # off the bottom of the plot would claim otherwise.
    delta = core + shelf + 2.0e-3 * (1.0 + np.abs(x) / 1.0) ** (-1.4)
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
    h1_ax.text(-5.85, 22.0, r"large $T_{\mathrm{true}}$:" "\npast the shelf,\nlittle left",
               fontsize=8, color=REDIS, linespacing=1.05, va="top")
    h1_ax.text(1.15, 0.60, r"small $T_{\mathrm{true}}$:" "\nnearly the whole\nshelf inverts it",
               fontsize=8, color=KAFKA, linespacing=1.05, va="top")
    # relpos pins the arrow to the edge of the label it belongs to. Left at its default it
    # starts from the centre of the text, and the leader shows through the gaps in the words.
    h1_ax.annotate("core\n(thread running)", xy=(0.30, 1.4), xytext=(3.6, 1.4),
                   fontsize=8, color=GREY, ha="left", va="center",
                   arrowprops=dict(arrowstyle="->", color=GREY, lw=0.8, relpos=(0.0, 0.5)))
    # Labelled where the lobe is rather than from across the panel. The wide format halved the
    # vertical room, and a leader drawn the width of the axes crossed the other annotation on
    # its way; the space directly above the hump is empty and a short one crosses nothing.
    h1_ax.annotate("kept waiting:\nthe rest of a slice",
                   xy=(-slice_ms / 2.0, 0.30 / slice_ms), xytext=(-2.9, 12.0), fontsize=8,
                   color=GREY, ha="center", va="center",
                   arrowprops=dict(arrowstyle="->", color=GREY, lw=0.8, relpos=(0.5, 0.0)))
    h1_ax.set_xlabel(r"timestamping asymmetry $\Delta$ (ms)")
    h1_ax.set_ylabel("density (log)")
    h1_ax.set_yticks([])


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
    plot_phases(top, tau, t_true, q)
    _plot_schedule(bot, tau, t_true, q)


KEEP_BLUE, DROP_RED = "#1f77b4", "#c44e52"


def plot_phases(top, tau=TAU_MS, t_true=T_TRUE_MS, q=GRID_Q):
    """Panel (a) of the quantum geometry: one delivery at four phases of one tick. Since v5
    (28 Sep) the paper's Fig. 5 draws this panel beside the deletion scatter, so it is its own
    function; the supplement's two-panel figure calls it unchanged."""
    keep, drop = KEEP_BLUE, DROP_RED
    phases = [i * tau / q for i in range(q)]

    # --- (a) one tick, four phases ---------------------------------------------------------
    # Drawn with an explicit top rather than axvline: a full-height rule runs through the
    # labels that name it, which is what the collision gate said the first time this was
    # rendered. The rule stops below the text and the text sits clear of it.
    for x in (0.0, tau):
        top.plot([x, x], [0.42, q + 0.34], color=GREY, lw=0.9, ls=(0, (3, 2)), zorder=1)
    # Boundaries of the timestamp's millisecond step, not "ticks": the manuscript keeps "tick"
    # for the scheduler's (1 Oct), and these rules are where the clock's reading changes.
    top.text(0.0, q + 0.52, "ms boundary", fontsize=8, color=GREY, ha="center", va="bottom")
    top.text(tau, q + 0.52, "next boundary", fontsize=8, color=GREY, ha="center", va="bottom")

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
    # 4 Oct 2026: without "T_true =", which ran this title into panel (b)'s on the page.
    top.set_title("(a) One end-to-end latency of %.2f ms, at four phases"
                  % t_true, fontsize=8, loc="left")


def _plot_schedule(bot, tau, t_true, q):
    """Panel (b) of the quantum geometry: which phases a publish schedule visits."""
    keep, drop = KEEP_BLUE, DROP_RED
    phases = [i * tau / q for i in range(q)]
    crossing = tau - t_true                     # a delivery from here on reaches the next tick

    # --- (b) which phases exist ------------------------------------------------------------
    #
    # No bracket over the crossing region. It was drawn with its own label above the rows, and
    # once the panel was compressed to hold the paper at twelve pages it took most of the
    # vertical budget: the two rows had to sit close enough that the mathtext ascenders of the
    # lower label came within a point or two of the dots above. The collision gate did not
    # fire; at print size it was plain. The shaded band and the $\tau - T_{\mathrm{true}}$ tick say the
    # same thing, and the caption names it in a clause, so the space goes to the rows.
    # Off-lattice, and that is the whole point. The first version drew this row as twenty
    # *evenly spaced* phases, which is not an incommensurate producer at all -- it is a
    # commensurate one with q = 20, the very thing the row below is contrasted against. The
    # paper reserves the word carefully ("889 msg/s sits 0.00014 from 9/8 and behaves as fully
    # continuous"), and the figure was quietly borrowing it.
    #
    # A golden-ratio rotation is the standard way to get phases that fill the interval without
    # ever repeating, and it keeps the arithmetic the panel exists to show: 7 of the 20 land in
    # the crossing region, so the printed share is exactly T_true/tau. Checked, not assumed --
    # an offset of 0.5 gives 6/20 and would make the panel illustrate the wrong number.
    phi = (5 ** 0.5 - 1) / 2
    uniform = [((i * phi) % 1.0) * tau for i in range(20)]   # 7/20 = T_true/tau exactly
    # Short enough to end left of the crossing band. The long form -- "incommensurate: every
    # phase occurs" -- reached under the bracket above it, and once the figure was compressed
    # to fit the page the bracket rule cut through it: under the collision gate's threshold,
    # plain to the eye. What the two rows mean is in the caption, which has room for it.
    # The last field is each label's lift above its own row. The commensurate label's maths box
    # is the taller of the two, and at 0.34 its top met the incommensurate dots above it (1.9%
    # of its core under Arial, 2.0% under DejaVu Sans); at 0.30 it clears them and its own row.
    rows = ((2.35, uniform, "incommensurate", GREY, 0.34),
            (1.00, phases, "commensurate $\\Delta/\\tau = %d/%d$" % (q + 1, q), "#2a7f62", 0.30))
    for y, pts, label, colour, lift in rows:
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
        bot.text(0, y + lift, label, fontsize=8, color=colour, ha="left", va="bottom")
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
    bot.set_xlabel("phase of the publish instant within one millisecond", fontsize=8)
    bot.set_title("(b) The publish schedule decides how many survive", fontsize=8, loc="left")


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
    # Not "clean": the manuscript uses clean for a run that passes the audit, and 520 of
    # these do. This count is the stricter thing -- runs with no negative span at all -- and
    # printing it as "clean" beside panel (b)'s 62% condemned invited the reader to subtract
    # and find a contradiction that is not there. Round 54's image review.
    hist_ax.set_title(f"(a) {clean:,} of {len(by_run):,} runs with no negative span",
                      fontsize=10)
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
    ax.annotate(f"batching acks:\n{ACK_UNBATCHED_TTI_MS/ACK_BATCHED_TTI_MS:.0f}× faster",
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
def _save(fig, out_dir, stem, check_layout=True, pad_inches=None, whole=False):
    """Gate a figure and write it as PNG and PDF.

    `whole` writes the canvas uncropped, for a figure drawn at exactly the width the page prints
    it at, so that the file is that width and the page neither enlarges nor shrinks it; the
    collision gate then also checks that no label is cut by the canvas edge (15 Oct 2026).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if check_layout:
        # Skipped only for a deliberately rescaled build: --font-scale draws the figures at a
        # size they were not laid out for, and the gates describe the shipped layout. Running
        # them on a rescaled render would report collisions nobody is going to ship.
        figure_collisions.check(fig, stem, whole_canvas=whole)
        figure_legibility.check(fig, stem)
        figure_vocabulary.check(fig, stem)
    # The crop's margin. The default is a tenth of an inch on each side, and a figure drawn
    # edge to edge at the width it prints at then comes out 0.2 in wider than that width and is
    # shrunk on inclusion (15 Oct 2026: Fig. 1's file was 7.29 in for a 7.16 in page, so its
    # 8 pt type printed at 7.9 pt, which the legibility gate, reading the canvas, cannot see).
    crop = {} if pad_inches is None else {"pad_inches": pad_inches}
    written = []
    for ext in ("png", "pdf"):
        path = out_dir / f"{stem}.{ext}"
        if whole:
            figure_style.save_whole(fig, path, dpi=200)
        else:
            fig.savefig(path, dpi=200, bbox_inches="tight", **crop)
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
        # Authored at the supplement's one-column width, not the paper's: this figure is
        # included at both, and a figure authored wide is scaled DOWN in the supplement,
        # which is the direction that pushes 8 pt type under the legibility floor.
        fig, ax = plt.subplots(figsize=(6.50, 1.86))
        plot_pipeline(ax)
        return _save(fig, out, "pipeline_schematic", check_layout=layout_is_shipped)

    def _model():
        # Two panels since 4 Oct 2026: where everything runs above, when each timestamp is
        # read below. Margins set by hand: tight_layout refuses a gridspec of axis-free
        # panels with a warning and lays them out no better.
        # 3.89 in tall since E's row was added and the stacked labels were spaced for CI's
        # matplotlib 3.9 (4 Oct 2026); the ratios keep both panels' scales as they were.
        # 15 Oct 2026: at the text width exactly and saved whole, so that the page prints it at
        # its own size (cropped, the file was 7.13 in and the page enlarged it 0.5%). Shorter by
        # the row the process box's label had, now on panel (b)'s title row, and by half of
        # each title's pad; panel (a)'s scale and panel (b)'s are as they were.
        fig = plt.figure(figsize=MODEL_FIG_IN)
        height_pt = 72.0 * MODEL_FIG_IN[1]
        gs = fig.add_gridspec(2, 1, height_ratios=list(MODEL_PANELS_PT),
                              hspace=MODEL_GAP_PT / (sum(MODEL_PANELS_PT) / 2.0), left=0.005,
                              right=0.995, top=1.0 - MODEL_TOP_PT / height_pt,
                              bottom=MODEL_BOTTOM_PT / height_pt)
        ax_sys, ax_time = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
        plot_system(ax_sys)
        plot_mechanism(ax_time)
        ax_sys.set_title("(a) Where everything runs", fontsize=8, loc="left", pad=TITLE_PAD)
        ax_time.set_title("(b) When each timestamp is read", fontsize=8, loc="left",
                          pad=TITLE_PAD)
        return _save(fig, out, "measurement_model", check_layout=layout_is_shipped,
                     whole=True)

    def _kernel():
        # The column's 3.5 in exactly, saved whole, so that the page prints it at its own size
        # (15 Oct 2026; cropped close it was 3.48 in, and the page enlarged it). The axis-free
        # panel is laid out by hand, in inches, and fills the canvas.
        fig, ax = plt.subplots(figsize=KERNEL_FIG_IN)
        plot_kernel_fix(ax)
        fig.subplots_adjust(left=0.0, right=1.0, top=1.0, bottom=0.0)
        return _save(fig, out, "kernel_timestamps", check_layout=layout_is_shipped,
                     whole=True)

    def _delta():
        # Drawn at the width the supplement includes it at. Drawn wider, every label is
        # scaled down on inclusion and 8 pt type lands at 7.3 pt, below the floor.
        fig, ax = plt.subplots(figsize=(6.50, 1.95))
        plot_delta(ax)
        fig.tight_layout()
        return _save(fig, out, "delta_schematic", check_layout=layout_is_shipped)

    def _quantum():
        # Single column, like the other two Mode B figures it sits beside. 2.12 in tall rather
        # than 1.94, all of the difference given to panel (a): its four phase rows were closer
        # together than an 8 pt label is tall, and under matplotlib 3.9.4 each label's box
        # covered a third of the next one's (31-33%), where 3.10 measured the boxes shorter and
        # passed. The ratio keeps panel (b) at the 0.39 in it had.
        fig, axes = plt.subplots(2, 1, figsize=(3.50, 2.12),
                                 gridspec_kw={"height_ratios": [1.578, 1.0]})
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
    render("kernel_timestamps", [], _kernel)
    render("delta_schematic", [], _delta)
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
