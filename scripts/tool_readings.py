#!/usr/bin/env python3
"""
tool_readings.py -- what each benchmarking tool says it measured, read from its own output.

T1 to T4 run ten tools against the same traffic our own program records, and then compare what
each one reports with what was really there. That comparison needs every tool's answer in one
shape, and it needs the answer the tool actually gave rather than a tidied version of it: the
whole point of the block is that tools round, drop, clamp and replace, and a reader that quietly
normalised those away would destroy the finding it exists to make.

So each reading keeps three things beside the numbers:

  reported_ms     the figures exactly as the tool printed them, converted to milliseconds only
  step_ms         the smallest step the tool's own printing can express -- one digit after the
                  point is a step of 0.1 ms, and a tool cannot report a difference below it
  kept            how many samples the tool says it counted, where it says so, so a tool that
                  silently drops the negatives can be caught by its own arithmetic

The audit (T5) read these tools' source and predicted how each behaves. These parsers read what
they print. Where the two disagree, the prediction is reported as failed, not corrected.

    python3 scripts/tool_readings.py read --tool vegeta --file report.txt
"""
import argparse
import json
import os
import re
import sys

#: How many milliseconds one of the tool's units is.
UNITS_MS = {"ns": 1e-6, "us": 1e-3, "µs": 1e-3, "μs": 1e-3, "ms": 1.0, "s": 1000.0, "m": 60000.0}


def step_of(text):
    """The smallest step a printed number can express, from its digits.

    "1.23" steps in 0.01 of whatever unit it carries; "1" steps in 1. A tool printing whole
    milliseconds cannot report a difference below a millisecond, however fine its clock, and that
    ceiling belongs with its answer.
    """
    if text is None:
        return None
    match = re.search(r"\d+(?:\.(\d+))?", str(text))
    if not match:
        return None
    return 10.0 ** (-len(match.group(1))) if match.group(1) else 1.0


def as_ms(number, unit):
    """A number the tool printed, in milliseconds, or None where the unit is not one we know."""
    if number is None or unit is None:
        return None
    scale = UNITS_MS.get(unit.strip())
    return None if scale is None else float(number) * scale


def _find(text, pattern, group=1):
    match = re.search(pattern, text or "", re.M | re.I)
    return match.group(group) if match else None


def _reading(tool, **rest):
    base = {"tool": tool, "reported_ms": {}, "step_ms": None, "kept": None, "unit": None}
    base.update(rest)
    return base


def read_vegeta(text):
    """Vegeta's text report. The audit rated it high: nanoseconds that survive the subtraction.

    Its latencies line carries several named figures with their own units, e.g.
        Latencies  [min, mean, 50, 90, 95, 99, max]  1.2ms, 3.4ms, 2.9ms, ...
    """
    line = _find(text, r"^Latencies\s+\[([^\]]+)\]\s+(.+)$", 2)
    names = _find(text, r"^Latencies\s+\[([^\]]+)\]", 1)
    if not line or not names:
        return _reading("vegeta")
    wanted = {"mean": "avg", "50": "p50", "99": "p99", "min": "min", "max": "max"}
    got, steps = {}, []
    for name, value in zip([n.strip() for n in names.split(",")],
                           [v.strip() for v in line.split(",")]):
        where = wanted.get(name)
        pair = re.match(r"([\d.]+)\s*([a-zµμ]+)", value)
        if not where or not pair:
            continue
        got[where] = as_ms(float(pair.group(1)), pair.group(2))
        steps.append(as_ms(step_of(pair.group(1)), pair.group(2)))
    requests = _find(text, r"^Requests\s+\[total.*?\]\s+(\d+)")
    return _reading("vegeta", reported_ms=got, kept=int(requests) if requests else None,
                    step_ms=max([s for s in steps if s is not None], default=None))


def read_hey(text):
    """hey prints seconds with four decimals, so its step is 0.1 ms whatever its clock does.

    That is the audit's prediction for it, and the one place this reader could hide the finding
    by rounding differently, so the step is taken from the digits it actually printed.
    """
    got, steps = {}, []
    for key, pattern in (("avg", r"^\s*Average:\s*([\d.]+) secs"),
                         ("min", r"^\s*Fastest:\s*([\d.]+) secs"),
                         ("max", r"^\s*Slowest:\s*([\d.]+) secs")):
        raw = _find(text, pattern)
        if raw is not None:
            got[key] = as_ms(float(raw), "s")
            steps.append(as_ms(step_of(raw), "s"))
    for share, key in (("50", "p50"), ("99", "p99")):
        raw = _find(text, r"^\s*%s%%%% in ([\d.]+) secs" % share) or \
            _find(text, r"^\s*%s%% in ([\d.]+) secs" % share)
        if raw is not None:
            got[key] = as_ms(float(raw), "s")
            steps.append(as_ms(step_of(raw), "s"))
    total = _find(text, r"^\s*Total:\s*[\d.]+ secs.*?\n.*?requests\s*:\s*(\d+)") or \
        _find(text, r"responses\s*:\s*(\d+)")
    return _reading("hey", reported_ms=got, kept=int(total) if total else None,
                    step_ms=max([s for s in steps if s is not None], default=None))


def read_valkey_benchmark(text):
    """valkey-benchmark's percentile table, in milliseconds with three decimals.

    The audit predicted its reported minimum reads 0.000 ms for any reply faster than 8 us, which
    is a floor its own printing puts there; the step recorded here is what makes that checkable.
    """
    got, steps = {}, []
    for key, pattern in (("avg", r"^\s*avg[^0-9]*([\d.]+)"),
                         ("min", r"^\s*min[^0-9]*([\d.]+)"),
                         ("p50", r"^\s*p50[^0-9]*([\d.]+)"),
                         ("p99", r"^\s*p99[^0-9]*([\d.]+)"),
                         ("max", r"^\s*max[^0-9]*([\d.]+)")):
        raw = _find(text, pattern)
        if raw is not None:
            got[key] = as_ms(float(raw), "ms")
            steps.append(as_ms(step_of(raw), "ms"))
    requests = _find(text, r"([\d]+) requests completed")
    return _reading("valkey-benchmark", reported_ms=got,
                    kept=int(requests) if requests else None,
                    step_ms=max([s for s in steps if s is not None], default=None))


def read_memtier(text):
    """memtier_benchmark's totals row: ops/sec, hits, misses, then latency figures in ms."""
    got, steps = {}, []
    for key, pattern in (("avg", r"^Totals\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)"),
                         ("p50", r"^Totals\s+(?:[\d.]+\s+){4}([\d.]+)"),
                         ("p99", r"^Totals\s+(?:[\d.]+\s+){5}([\d.]+)")):
        raw = _find(text, pattern)
        if raw is not None:
            got[key] = as_ms(float(raw), "ms")
            steps.append(as_ms(step_of(raw), "ms"))
    return _reading("memtier_benchmark", reported_ms=got,
                    step_ms=max([s for s in steps if s is not None], default=None))


def read_kafka_end_to_end(text):
    """Kafka's EndToEndLatency prints whole milliseconds for the percentiles.

    The audit found it truncates nanoseconds to milliseconds: an average that is exact and
    percentiles that are not. Both are kept as printed.
    """
    got, steps = {}, []
    avg = _find(text, r"Avg latency:\s*([\d.]+)\s*ms")
    if avg is not None:
        got["avg"] = as_ms(float(avg), "ms")
        steps.append(as_ms(step_of(avg), "ms"))
    for share, key in (("50", "p50"), ("99", "p99")):
        raw = _find(text, r"Percentiles?:.*?%sth\s*=\s*(\d+)" % share) or \
            _find(text, r"^\s*%sth\s*=\s*(\d+)" % share)
        if raw is not None:
            got[key] = as_ms(float(raw), "ms")
            steps.append(as_ms(step_of(raw), "ms"))
    return _reading("kafka-end-to-end", reported_ms=got,
                    step_ms=max([s for s in steps if s is not None], default=None))


def read_rdkafka_performance(text):
    """librdkafka's rdkafka_performance, which prints its latency in microseconds."""
    got, steps = {}, []
    for key, pattern in (("avg", r"latency\s+curr/avg/lo/hi[^0-9]*[\d.]+/([\d.]+)"),
                         ("min", r"latency\s+curr/avg/lo/hi[^0-9]*[\d.]+/[\d.]+/([\d.]+)"),
                         ("max", r"latency\s+curr/avg/lo/hi[^0-9]*(?:[\d.]+/){3}([\d.]+)")):
        raw = _find(text, pattern)
        if raw is not None:
            got[key] = as_ms(float(raw), "us")
            steps.append(as_ms(step_of(raw), "us"))
    return _reading("rdkafka_performance", reported_ms=got, unit="us",
                    step_ms=max([s for s in steps if s is not None], default=None))


def read_k6(text):
    """k6's summary. The audit found it strips the monotonic part of Go's clock."""
    got, steps = {}, []
    line = _find(text, r"^\s*(?:iteration_duration|http_req_duration).*$", 0)
    for key, name in (("avg", "avg"), ("min", "min"), ("p50", "med"), ("p99", "p\\(99\\)"),
                      ("max", "max")):
        raw = _find(line or "", r"%s=([\d.]+)(ms|s|µs|us)" % name, 1)
        unit = _find(line or "", r"%s=[\d.]+(ms|s|µs|us)" % name, 1)
        if raw is not None:
            got[key] = as_ms(float(raw), unit)
            steps.append(as_ms(step_of(raw), unit))
    return _reading("k6", reported_ms=got,
                    step_ms=max([s for s in steps if s is not None], default=None))


#: Every tool this reads, by the name a campaign calls it.
READERS = {
    "vegeta": read_vegeta,
    "hey": read_hey,
    "valkey-benchmark": read_valkey_benchmark,
    "memtier_benchmark": read_memtier,
    "kafka-end-to-end": read_kafka_end_to_end,
    "rdkafka_performance": read_rdkafka_performance,
    "k6": read_k6,
}


def read_tool(tool, text):
    """One tool's output, as a reading. An unknown tool is refused rather than guessed at."""
    if tool not in READERS:
        raise ValueError("no reader for %s; the tools read here are %s"
                         % (tool, ", ".join(sorted(READERS))))
    return READERS[tool](text)


def below_its_step(reading, true_ms, other_ms):
    """Whether a difference the reference measured is one this tool could not have reported.

    T1 adds steps of 0.1 ms and asks whether each tool sees them. A tool printing whole
    milliseconds cannot, however good its clock, and that is a property of the tool rather than a
    failure of the run -- so it is reported as out of the tool's reach, not as a miss.
    """
    step = reading.get("step_ms")
    if step is None or true_ms is None or other_ms is None:
        return None
    return abs(true_ms - other_ms) < step


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="What a tool says it measured, from its own output")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("read")
    p.add_argument("--tool", required=True, choices=sorted(READERS))
    p.add_argument("--file", required=True)
    p.add_argument("--out", default="")
    args = ap.parse_args(argv)
    with open(args.file, encoding="utf-8", errors="replace") as fh:
        reading = read_tool(args.tool, fh.read())
    text = json.dumps(reading, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text, file=out)
    return 0 if reading["reported_ms"] else 1


if __name__ == "__main__":  # pragma: no cover - the dispatch is exercised through main()
    sys.exit(main())
