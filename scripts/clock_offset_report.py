#!/usr/bin/env python3
"""
clock_offset_report.py
How far apart are the hosts' clocks, and does it matter at the resolution being used?

A cross-host end-to-end latency is `t_recv(host B) - t_send(host A)`. It goes negative when the
clocks disagree by more than the true transport time. That is the failure this project reports,
and in a distributed OpenMessaging Benchmark run it is the channel that would produce genuine
causality violations rather than tick collisions.

Whether it can produce them depends on two numbers together, and reporting either alone is
misleading:

  * the offset between the hosts' clocks, which chrony estimates continuously;
  * the resolution of the timestamp being subtracted.

Kafka's `CreateTime` timestamp is millisecond-grained. An offset of 141 microseconds is real, is
larger than nothing, and is *invisible* to a subtraction that cannot resolve below 1000 of them.
A well-synchronised pair of hosts therefore hides the clock channel behind the quantisation, and
a benchmark reporting whole-millisecond percentiles cannot distinguish "the clocks agree" from
"the clocks disagree by less than one tick". This script reports the ratio so that a run showing
no negatives is interpreted as what it is -- evidence about this pair of clocks at this
resolution -- and not as evidence that cross-host subtraction is safe.

Input is `chronyc tracking` output per host, as captured by the campaign.

CLI:
    python scripts/clock_offset_report.py --tracking driver=drv.txt --tracking broker1=b1.txt \\
        --resolution-ms 1.0 --out docs/results/external/clock_offsets.csv
"""
import argparse
import csv
import os
import re

# `chronyc tracking` reports these in seconds; both matter. Last offset is the most recent
# correction, RMS offset the longer-run spread, and a pair can look tight on one and not the other.
LAST_OFFSET_RE = re.compile(r"^Last offset\s*:\s*([+-]?[\d.]+)\s*seconds", re.M)
RMS_OFFSET_RE = re.compile(r"^RMS offset\s*:\s*([\d.]+)\s*seconds", re.M)
STRATUM_RE = re.compile(r"^Stratum\s*:\s*(\d+)", re.M)
# The bound chrony itself puts on its error. This is the honest figure for "how wrong could we be".
ROOT_DISP_RE = re.compile(r"^Root dispersion\s*:\s*([\d.]+)\s*seconds", re.M)
ROOT_DELAY_RE = re.compile(r"^Root delay\s*:\s*([\d.]+)\s*seconds", re.M)


def parse_tracking(text):
    """Pull the offsets out of `chronyc tracking`. Missing fields come back as None."""
    def one(rx):
        m = rx.search(text or "")
        return float(m.group(1)) if m else None

    return {"last_offset_s": one(LAST_OFFSET_RE), "rms_offset_s": one(RMS_OFFSET_RE),
            "stratum": one(STRATUM_RE), "root_dispersion_s": one(ROOT_DISP_RE),
            "root_delay_s": one(ROOT_DELAY_RE)}


def max_error_ms(tracking):
    """chrony's own bound on how far this host can be from true time, in milliseconds.

    The conventional bound is root dispersion plus half the root delay. Using it rather than the
    last offset avoids quoting the most flattering number available.
    """
    disp, delay = tracking.get("root_dispersion_s"), tracking.get("root_delay_s")
    if disp is None and delay is None:
        return None
    return ((disp or 0.0) + (delay or 0.0) / 2.0) * 1000.0


def pair_bound_ms(a, b):
    """Worst-case disagreement between two hosts, in milliseconds.

    Each host is within its own bound of true time, so the pair is within the sum. This is a
    bound, not an estimate: the true offset is usually far smaller, and saying so is the point.
    """
    ea, eb = max_error_ms(a), max_error_ms(b)
    if ea is None or eb is None:
        return None
    return ea + eb


def verdict(bound_ms, resolution_ms):
    """Can a clock disagreement of this size show up at this timestamp resolution?"""
    if bound_ms is None or not resolution_ms:
        return "unknown", "no chrony bound available for one host"
    if bound_ms >= resolution_ms:
        return "VISIBLE", (f"the pair may disagree by up to {bound_ms:.3f} ms, which reaches the "
                           f"{resolution_ms:g} ms timestamp resolution: a negative sample is "
                           f"possible from clock offset alone")
    return "MASKED", (f"the pair may disagree by up to {bound_ms:.3f} ms, below the "
                      f"{resolution_ms:g} ms timestamp resolution: clock offset cannot produce a "
                      f"negative sample here, and a run showing none is not evidence that "
                      f"cross-host subtraction is safe -- only that this pair is tight relative "
                      f"to a coarse clock")


def report(hosts, resolution_ms):
    """hosts: {name: tracking dict}. Returns (rows, overall verdict)."""
    names = sorted(hosts)
    print(f"== host clocks, against a {resolution_ms:g} ms timestamp resolution ==\n")
    print(f"{'host':<12s}{'stratum':>8s}{'last offset':>14s}{'RMS offset':>13s}{'max error':>12s}")
    for n in names:
        t = hosts[n]
        err = max_error_ms(t)
        print(f"{n:<12s}{_fmt(t['stratum'], 0):>8s}"
              f"{_fmt_ms(t['last_offset_s']):>14s}{_fmt_ms(t['rms_offset_s']):>13s}"
              f"{('-' if err is None else f'{err:.3f} ms'):>12s}")

    rows, worst = [], None
    print()
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            bound = pair_bound_ms(hosts[a], hosts[b])
            v, why = verdict(bound, resolution_ms)
            rows.append({"host_a": a, "host_b": b,
                         "bound_ms": "" if bound is None else round(bound, 6),
                         "resolution_ms": resolution_ms, "verdict": v})
            print(f"  {a} <-> {b}: {v}")
            if bound is not None and (worst is None or bound > worst[0]):
                worst = (bound, why)
    if worst:
        print(f"\n== overall ==\n  {worst[1]}")
    return rows


def _fmt(v, nd):
    return "-" if v is None else f"{v:.{nd}f}"


def _fmt_ms(v):
    return "-" if v is None else f"{v * 1000:.4f} ms"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Report host clock offsets against a resolution")
    ap.add_argument("--tracking", action="append", default=[], metavar="NAME=PATH",
                    help="`chronyc tracking` output for a host; repeatable")
    ap.add_argument("--resolution-ms", type=float, default=1.0,
                    help="resolution of the timestamp being subtracted (Kafka CreateTime: 1 ms)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    hosts = {}
    for spec in args.tracking:
        name, sep, path = spec.partition("=")
        if not sep:
            print(f"bad --tracking (want NAME=PATH): {spec}")
            return 1
        if not os.path.exists(path):
            print(f"missing: {path}")
            return 1
        with open(path, encoding="utf-8", errors="replace") as fh:
            hosts[name] = parse_tracking(fh.read())

    if len(hosts) < 2:
        print("need at least two hosts to report an offset between them")
        return 1

    rows = report(hosts, args.resolution_ms)

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["host_a", "host_b", "bound_ms",
                                               "resolution_ms", "verdict"])
            w.writeheader()
            w.writerows(rows)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
