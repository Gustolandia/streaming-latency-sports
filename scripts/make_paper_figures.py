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

import matplotlib
matplotlib.use("Agg")
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
def plot_pipeline(ax):
    """Draw the replay pipeline, its four timestamps, and the intervals they define."""
    boxes = [(0.5, "Producer\n(replay)"), (4.0, "Broker\n(Kafka / Redis)"), (7.5, "Consumer")]
    for x, label in boxes:
        ax.add_patch(plt.Rectangle((x, 1.6), 2.0, 0.9, facecolor="white",
                                   edgecolor=GREY, linewidth=1.4))
        ax.text(x + 1.0, 2.05, label, ha="center", va="center", fontsize=9)
    for x0, x1 in ((2.5, 4.0), (6.0, 7.5)):
        ax.annotate("", xy=(x1, 2.05), xytext=(x0, 2.05),
                    arrowprops=dict(arrowstyle="->", color=GREY, linewidth=1.2))

    stamps = [(0.9, r"$t_{\rm sched}$", "planned"), (2.4, r"$t_{\rm send}$", "producer"),
              (4.6, r"$t_{\rm ack}$", "producer"), (7.6, r"$t_{\rm recv}$", "consumer")]
    for x, sym, proc in stamps:
        ax.plot([x, x], [1.35, 1.6], color=GREY, linewidth=1.0)
        ax.text(x, 1.20, sym, ha="center", va="top", fontsize=9)
        ax.text(x, 0.92, proc, ha="center", va="top", fontsize=7, color=GREY, style="italic")

    spans = [(0.9, 2.4, 0.55, "scheduling lag"), (4.6, 7.6, 0.55, "broker transport"),
             (0.9, 7.6, 0.15, "end-to-end TTI")]
    for x0, x1, y, label in spans:
        ax.annotate("", xy=(x1, y), xytext=(x0, y),
                    arrowprops=dict(arrowstyle="<->", color="black", linewidth=1.0))
        ax.text((x0 + x1) / 2, y + 0.07, label, ha="center", fontsize=8)

    ax.text(6.1, 3.15, r"broker transport spans two processes' clocks "
                       r"$\Rightarrow$ it can come out negative",
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
    mean_ax.legend(fontsize="small")

    burst_ax.hist(profiles["burstiness"], bins=40, color=GREY, alpha=0.75)
    burst_ax.axvline(profiles["burstiness"].median(), color="#b22222", linewidth=1.6,
                     label=f"median {profiles['burstiness'].median():.2f}$\\times$")
    burst_ax.set_xlabel("Peak / mean arrival rate (10 s window)")
    burst_ax.set_ylabel("Matches")
    burst_ax.set_title("(b) ...and burstier than their mean suggests")
    burst_ax.legend(fontsize="small")


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
        ax.legend(fontsize="small")


# --------------------------------------------------------------------------- audit
SENSITIVITY_THRESHOLDS = (0.0, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20)


def condemned_at(by_run, threshold):
    """Number of runs the gate condemns at a given inversion threshold.

    Mirrors the rule in clock_integrity.py: condemn if the worst component's inversion rate
    exceeds the threshold, or if any component median is negative.
    """
    worst = by_run["max_neg_fraction"].astype(float)
    medians = by_run[["median_transport_ms", "median_schedlag_ms",
                      "median_output_ms"]].astype(float)
    return int(((worst > threshold) | (medians < 0).any(axis=1)).sum())


def plot_integrity(axes, by_run, threshold=0.01):
    """Per-run inversion rates, and how the condemnation count depends on the threshold.

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
    hist_ax.set_xlabel("Worst-component inversion rate per run (log)")
    hist_ax.set_ylabel("Runs")
    hist_ax.set_title(f"(a) {clean:,} of {len(by_run):,} runs clean", fontsize=10)
    hist_ax.legend(fontsize="small", loc="upper left")

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
    sens_ax.set_ylim(0, 100)
    sens_ax.set_title("(b) The threshold is a real choice", fontsize=10)
    sens_ax.grid(True, alpha=0.3)
    sens_ax.legend(fontsize="small", loc="upper right")


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
                xy=(20, ACK_BATCHED_TTI_MS), xytext=(23, 4.0),
                fontsize=8, arrowprops=dict(arrowstyle="->", color="black", linewidth=1.0))
    ax.set_yscale("log")
    ax.set_xlabel("Injected one-way delay (ms)")
    ax.set_ylabel("End-to-end TTI, p50 (ms, log)")
    ax.set_title("A network hop reverses the ordering")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize="small", loc="center right")


# --------------------------------------------------------------------------- driver
def _save(fig, out_dir, stem):
    out_dir.mkdir(parents=True, exist_ok=True)
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
    args = ap.parse_args(argv)
    out = Path(args.out)

    written, missing = [], []

    def render(stem, needs, draw):
        """Render one figure if its inputs are present; record it as missing otherwise."""
        if args.only and args.only != stem:
            return
        if any(d is None for d in needs):
            missing.append(stem)
            return
        written.extend(draw())

    def _pipeline():
        fig, ax = plt.subplots(figsize=(9, 2.8))
        plot_pipeline(ax)
        return _save(fig, out, "pipeline_schematic")

    def _workload():
        fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
        plot_workload(axes, profiles)
        fig.tight_layout()
        return _save(fig, out, "workload_profile")

    def _concurrency():
        fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
        plot_concurrency(axes, slots, timeline)
        fig.tight_layout()
        return _save(fig, out, "kickoff_concurrency")

    def _integrity():
        fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
        plot_integrity(axes, integrity)
        fig.tight_layout()
        return _save(fig, out, "integrity_audit")

    def _network():
        fig, ax = plt.subplots(figsize=(6.5, 4.2))
        plot_network(ax)
        fig.tight_layout()
        return _save(fig, out, "network_delay")

    profiles = _read(args.profiles_csv)
    slots = _read(args.slots_csv)
    timeline = _read(args.timeline_csv)
    integrity = _read(args.integrity_csv)

    render("pipeline_schematic", [], _pipeline)
    render("workload_profile", [profiles], _workload)
    render("kickoff_concurrency", [slots, timeline], _concurrency)
    render("integrity_audit", [integrity], _integrity)
    render("network_delay", [], _network)

    for path in written:
        print(f"wrote {path}")
    for stem in missing:
        print(f"skipped {stem}: input missing")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
