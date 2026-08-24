#!/usr/bin/env python3
"""
make_synthetic_plan.py
Generate a replay plan with a controlled arrival process, matching the football feed's mean rate
but not its burst structure.

Why this exists. The paper's sharpest methodological claim is that the difference between the
two brokers appears at the real workload's sparse arrival rate and vanishes under accelerated
replay -- so a benchmark driven by a dense synthetic publisher measures the regime in which the
difference is absent. That claim currently rests on one workload, which is a external-validity
threat we state in the paper.

This closes half of it. By generating plans that hold the *mean rate* fixed while varying the
arrival process (constant-rate, Poisson, or bursty), we can ask whether the effect follows the
rate or follows football specifically. If a constant-rate synthetic feed at 0.415 events/second
reproduces the effect, the finding is about sparsity and generalises. If only the bursty feed
does, it is about the idle-then-burst duty cycle, which is a narrower but still transferable
claim.

Output schema matches make_replay_plan.py exactly, so the plans are drop-in for the existing
orchestrator.

CLI:
    python scripts/make_synthetic_plan.py --arrival constant --rate 0.415 \
        --duration 600 --out data/synthetic/constant/replay_plan.csv
"""
import argparse
import csv
from pathlib import Path

import numpy as np

ARRIVALS = ("constant", "poisson", "bursty")


def constant_offsets(rate, duration, rng):  # noqa: ARG001 - rng unused, kept for a uniform signature
    """Perfectly regular arrivals: the implicit model of a fixed-rate publisher."""
    n = max(1, int(rate * duration))
    return np.arange(n, dtype=float) / rate


def poisson_offsets(rate, duration, rng):
    """Exponential inter-arrival times: the standard stochastic assumption."""
    offsets, t = [], 0.0
    while True:
        t += rng.exponential(1.0 / rate)
        if t >= duration:
            break
        offsets.append(t)
    return np.asarray(offsets if offsets else [0.0])


def bursty_offsets(rate, duration, rng, burst_size=8, quiet_factor=6.0):
    """Idle periods punctuated by tight bursts, echoing the football duty cycle.

    The mean rate is held to `rate`; what changes is that arrivals clump. This is the arm that
    distinguishes "the effect follows sparsity" from "the effect follows the idle-then-burst
    pattern", which the paper currently cannot separate.
    """
    offsets, t = [], 0.0
    burst_gap = 1.0 / (rate * quiet_factor)
    while t < duration:
        for _ in range(burst_size):
            if t >= duration:
                break
            offsets.append(t)
            t += burst_gap
        # Quiet period sized so the long-run mean rate comes out at `rate`.
        t += burst_size / rate - burst_size * burst_gap
    return np.asarray(offsets if offsets else [0.0])


GENERATORS = {"constant": constant_offsets, "poisson": poisson_offsets, "bursty": bursty_offsets}


def build_plan(arrival, rate, duration, seed=12345, match_id=900000):
    """Return plan rows in make_replay_plan.py's schema."""
    if arrival not in GENERATORS:
        raise ValueError(f"unknown arrival process {arrival!r}; expected one of {ARRIVALS}")
    if rate <= 0 or duration <= 0:
        raise ValueError("rate and duration must be positive")

    rng = np.random.default_rng(seed)
    offsets = GENERATORS[arrival](rate, duration, rng)
    return [
        {
            "row_idx": i,
            "event_id": f"{arrival}-{i:06d}",
            "match_id": match_id,
            "t_sim_seconds": int(off),
            "t_emit_offset_s": round(float(off), 6),
        }
        for i, off in enumerate(offsets)
    ]


def write_plan(rows, out_path):
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["row_idx", "event_id", "match_id",
                                           "t_sim_seconds", "t_emit_offset_s"])
        w.writeheader()
        w.writerows(rows)
    return out


def achieved_rate(rows, duration):
    """The realised mean rate, so the manipulation can be verified rather than assumed."""
    return len(rows) / duration if duration else float("nan")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Synthetic replay plan with a controlled arrival process")
    ap.add_argument("--arrival", choices=ARRIVALS, default="constant")
    ap.add_argument("--rate", type=float, default=0.415,
                    help="mean events/second (default: the football feed's measured rate)")
    ap.add_argument("--duration", type=float, default=600.0, help="seconds of plan")
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    rows = build_plan(args.arrival, args.rate, args.duration, args.seed)
    out = write_plan(rows, args.out)
    print(f"{args.arrival}: {len(rows)} events over {args.duration:g}s "
          f"(achieved {achieved_rate(rows, args.duration):.3f} ev/s, "
          f"requested {args.rate:.3f}) -> {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
