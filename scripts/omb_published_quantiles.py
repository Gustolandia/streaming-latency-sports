#!/usr/bin/env python3
"""
omb_published_quantiles.py
Recover the data behind the OpenMessaging Benchmark's own published latency chart.

Why this exists. A co-author pointed at the reference write-up of the benchmark
(jeqo.dev/blog/benchmarking-apache-kafka/intro-omb) and its end-to-end latency chart, and
asked what our data would look like on the same axes. The chart is a pygal SVG, and pygal
writes every plotted point into a `<desc class="value">` tooltip, so the series can be
recovered exactly rather than traced off the picture by eye.

What the recovered series shows, and why it is worth a figure of its own:

    the smallest latency anywhere in the published distribution is 1 ms.

Not 0.9, not 0.4 -- one whole millisecond, at the 4.5th percentile, with nothing beneath it.
That floor is not a property of the network. It is the quantum: the benchmark differences two
millisecond-resolution stamps and admits the sample only when the result is strictly positive,
so every sample that computed to 0 is deleted and the reported distribution necessarily begins
at one tick. The floor of their own published chart is the deletion, drawn.

Second observation, from the axis rather than the data: the x-axis is a TAIL scale, whose
ticks run 90, 99, 99.9, 99.99 -- each one cutting the remaining fraction tenfold -- so its
first labelled tick is the 90th percentile. Say that precisely rather than "the axis starts
at 90%": the scale is -log10(1 - p/100), not a linear axis with a cropped origin, and the
distinction is exactly the kind this paper is about. The consequence is the same either way.
Even the 4.5% of samples sitting on the 1 ms floor are off the left edge of the canvas, and
the published picture shows the tail of a distribution whose lower nine tenths are not drawn
at all.

CLI:
    python scripts/omb_published_quantiles.py --svg <path to results-e2e-quantiles.svg>
    python scripts/omb_published_quantiles.py --summary
"""
import argparse
import csv
import io
import os
import re

DEFAULT_OUT = os.path.join("docs", "results", "omb_published_quantiles.csv")

#: pygal writes one of these per plotted point: "<percentile> %: <latency ms>".
VALUE_RE = re.compile(r'<desc[^>]*class="[^"]*value[^"]*"[^>]*>([^<]*)</desc>')
PAIR_RE = re.compile(r'^\s*([0-9.]+)\s*%\s*:\s*([0-9.]+)\s*$')


def parse_svg(path):
    """Return [(percentile, latency_ms)] recovered from the chart's tooltips."""
    text = io.open(path, encoding="utf-8", errors="replace").read()
    points = []
    for raw in VALUE_RE.findall(text):
        m = PAIR_RE.match(raw)
        if not m:
            continue
        points.append((float(m.group(1)), float(m.group(2))))
    points.sort()
    return points


def describe(points):
    """The two facts the figure is built on, computed rather than asserted."""
    if not points:
        return {}
    lat = [ms for _p, ms in points]
    floor = min(lat)
    at_floor = [p for p, ms in points if ms == floor]
    return {
        "n_points": len(points),
        "latency_floor_ms": floor,
        "percentile_at_floor": min(at_floor) if at_floor else None,
        "latency_max_ms": max(lat),
        "percentile_min": min(p for p, _ in points),
        "percentile_max": max(p for p, _ in points),
        "below_one_ms": sum(1 for ms in lat if ms < 1.0),
        "below_zero": sum(1 for ms in lat if ms < 0.0),
    }


def write_csv(points, out):
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["percentile", "latency_ms"])
        for p, ms in points:
            w.writerow(["%.8f" % p, "%.3f" % ms])
    return out


def read_csv(path=DEFAULT_OUT):
    with open(path, newline="", encoding="utf-8") as fh:
        return [(float(r["percentile"]), float(r["latency_ms"]))
                for r in csv.DictReader(fh)]


def report(points):
    d = describe(points)
    print("points recovered      %d" % d["n_points"])
    print("percentile range      %.4f%% .. %.5f%%" % (d["percentile_min"], d["percentile_max"]))
    print("latency range         %.3f .. %.3f ms" % (d["latency_floor_ms"], d["latency_max_ms"]))
    print("")
    print("samples below 1 ms    %d" % d["below_one_ms"])
    print("samples below 0 ms    %d" % d["below_zero"])
    print("floor sits at         %.3f ms, reached at the %.2fth percentile"
          % (d["latency_floor_ms"], d["percentile_at_floor"]))
    print("")
    print("The floor is the quantum. Nothing faster than one tick survives the guard,")
    print("so the published distribution cannot begin anywhere else.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Recover the OMB published quantile series")
    ap.add_argument("--svg")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args(argv)

    if args.summary:
        report(read_csv(args.out))
        return 0
    if not args.svg:
        ap.error("give --svg <file> or --summary")
    points = parse_svg(args.svg)
    if not points:
        raise SystemExit("no plotted values found in %s" % args.svg)
    write_csv(points, args.out)
    report(points)
    print("")
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
