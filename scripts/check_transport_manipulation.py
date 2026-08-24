#!/usr/bin/env python3
"""Did the manipulation actually move the true transport? If not, nothing else follows.

This is the manipulation check for the co-location and padding arms. Both experiments claim
that changing the transport changed T_true; if the medians say otherwise, every downstream
comparison is between two arms that differ in label only.

One note on wording, kept because it was a real defect. The tool was written for co-location,
where the second arm was expected to be *faster*, and it printed "shorter" unconditionally.
Pointed at the padding sweep, where the second arm is expected slower, that label inverted the
meaning of a correct number. The direction is now read off the data.

CLI:
    python scripts/check_transport_manipulation.py baseline=20260712_101500 padded=20260712_1130
"""
import argparse
import glob
import json
import statistics as st

BACKENDS = ("kafka", "redis")


def parse_arms(pairs):
    """`name=timestamp` pairs, in the order given -- the first is the reference arm."""
    arms = {}
    for pair in pairs:
        name, _, timestamp = pair.partition("=")
        if not timestamp:
            raise ValueError("expected name=timestamp, got %r" % pair)
        arms[name] = timestamp
    return arms


def transport_percentiles(timestamp, backend, root="runs"):
    """(p50 list, p99 list) over every run of one arm and backend.

    A summary that will not parse is skipped rather than fatal: these directories accumulate
    partial writes from interrupted runs, and one of them must not hide the whole arm.
    """
    p50, p99 = [], []
    pattern = "%s/concurrency_%s_%s_*/tti_summary.json" % (root, timestamp, backend)
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8") as handle:
                summary = json.load(handle)
        except Exception:      # noqa: BLE001 - unreadable is "no data from this run"
            continue
        transport = summary.get("transport_ms") or {}
        if "p50" in transport:
            p50.append(transport["p50"])
        if "p99" in transport:
            p99.append(transport["p99"])
    return p50, p99


def medians(arms, root="runs"):
    """{(arm, backend): (runs, median p50, median p99)} for every arm that produced data."""
    out = {}
    for arm, timestamp in arms.items():
        for backend in BACKENDS:
            p50, p99 = transport_percentiles(timestamp, backend, root)
            if p50:
                out[(arm, backend)] = (len(p50), st.median(p50),
                                       st.median(p99) if p99 else None)
    return out


def describe(backend, reference, other, arm_name):
    """The one-line verdict, with the direction read off the numbers rather than assumed."""
    if other > reference:
        return ("  %s: T_true %.4f -> %.4f ms   (%.2fx LONGER in %s)"
                % (backend, reference, other, other / reference, arm_name))
    return ("  %s: T_true %.4f -> %.4f ms   (%.2fx shorter in %s)"
            % (backend, reference, other, reference / other, arm_name))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pairs", nargs="*", metavar="name=timestamp")
    ap.add_argument("--root", default="runs")
    args = ap.parse_args(argv)

    arms = parse_arms(args.pairs)
    print("%14s %7s %5s %11s %11s" % ("arm", "backend", "runs", "median p50", "median p99"))
    found = medians(arms, args.root)
    for (arm, backend), (runs, m50, m99) in found.items():
        print("%14s %7s %5d %11.4f %11s"
              % (arm, backend, runs, m50, "-" if m99 is None else "%11.4f" % m99))

    print()
    names = list(arms)
    if len(names) < 2:
        print("give at least two arms to compare")
        return 1

    reference, other = names[0], names[1]
    compared = 0
    for backend in BACKENDS:
        a = found.get((reference, backend))
        b = found.get((other, backend))
        if a and b and a[1] and b[1]:
            print(describe(backend, a[1], b[1], other))
            compared += 1
    if not compared:
        print("no backend produced data in both arms")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
