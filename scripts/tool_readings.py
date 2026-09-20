#!/usr/bin/env python3
"""
tool_readings.py -- what each benchmarking tool says it measured, read from its own output.

T1 to T4 run the tools against the same traffic our own program records, and then compare what
each one reports with what was really there. That comparison needs every tool's answer in one
shape, and it needs the answer the tool actually gave rather than a tidied version of it: the
whole point of the block is that tools round, drop, clamp and replace, and a reader that quietly
normalised those away would destroy the finding it exists to make.

So each reading keeps these beside the numbers:

  reported_ms     the figures exactly as the tool printed them, converted to milliseconds only
  steps_ms        the smallest step each figure's own printing can express -- one digit after the
                  point is a step of 0.1 ms, and a tool cannot report a difference below it
  step_ms         the coarsest of those: what the tool cannot report anywhere
  kept            how many samples the tool says it counted, where it says so, so a tool that
                  silently drops the negatives can be caught by its own arithmetic

The step is per figure because two of the predictions turn on exactly that. Kafka's
EndToEndLatency prints "Avg latency: %.4f ms" beside "50th = %d", and ProducerPerformance prints
"%.2f ms avg latency" beside "%d ms 50th": an average that can see a tenth of a millisecond,
sitting next to percentiles that cannot see one at all. One step per tool would report the pair
as uniformly coarse and lose the thing T-P1 and T-P2 predict.

The audit (T5) read these tools' source and predicted how each behaves. These parsers read what
they print. Where the two disagree, the prediction is reported as failed, not corrected.

    python3 scripts/tool_readings.py read --tool vegeta --file report.txt
"""
import argparse
import json
import re
import sys

#: How many milliseconds one of the tool's units is.
UNITS_MS = {"ns": 1e-6, "us": 1e-3, "µs": 1e-3, "μs": 1e-3, "ms": 1.0, "s": 1000.0, "m": 60000.0}

#: The units a Go program prints a duration in, longest first so "ms" is not read as "m".
GO_UNITS = r"(?:ns|µs|μs|us|ms|s)"


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


def _last(text, pattern):
    """The last time a pattern appears, which for a tool that prints as it goes is its total."""
    found = list(re.finditer(pattern, text or "", re.M | re.I))
    return found[-1] if found else None


def _coarsest(steps):
    """The coarsest step among a tool's figures: what it cannot report anywhere."""
    return max([s for s in steps.values() if s is not None], default=None)


def _put(got, steps, key, raw, unit):
    """One figure the tool printed, with the step its own digits put under it."""
    if raw is None:
        return
    got[key] = as_ms(float(raw), unit)
    steps[key] = as_ms(step_of(raw), unit)


def _reading(tool, got=None, steps=None, **rest):
    got, steps = got or {}, steps or {}
    base = {"tool": tool, "reported_ms": got, "steps_ms": steps, "step_ms": _coarsest(steps),
            "kept": None, "unit": None}
    base.update(rest)
    return base


def _by_column(names, fields, wanted):
    """Figures read by the name the tool's own header gives each column, not by counting.

    Two of these tools print their latencies as a table, and both have moved the columns between
    versions: memtier_benchmark gained a p99.9 beside p50 and p99, and valkey-benchmark puts a p95
    between them. A reader that counted fields from the left would report one percentile as
    another depending on which version happened to run, and would say nothing about having done
    it. Reading the header instead means a column that is not there is simply absent.
    """
    got, steps = {}, {}
    for key, accepted in wanted:
        at = next((names.index(n) for n in accepted if n in names), None)
        # A minus sign is part of the number: under T2's offset a minimum can come out below
        # zero, and a reader that only accepted digits would drop exactly the value T2 is for.
        if at is None or at >= len(fields) or not re.fullmatch(r"-?\d+(?:\.\d+)?", fields[at]):
            continue
        _put(got, steps, key, fields[at], "ms")
    return got, steps


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
    got, steps = {}, {}
    for name, value in zip([n.strip() for n in names.split(",")],
                           [v.strip() for v in line.split(",")]):
        where = wanted.get(name)
        pair = re.match(r"([\d.]+)\s*([a-zµμ]+)", value)
        if not where or not pair:
            continue
        _put(got, steps, where, pair.group(1), pair.group(2))
    requests = _find(text, r"^Requests\s+\[total.*?\]\s+(\d+)")
    return _reading("vegeta", got, steps, kept=int(requests) if requests else None)


def read_hey(text):
    """hey prints seconds with four decimals, so its step is 0.1 ms whatever its clock does.

    That is the audit's prediction for it, and the one place this reader could hide the finding
    by rounding differently, so the step is taken from the digits it actually printed.
    """
    got, steps = {}, {}
    for key, pattern in (("avg", r"^\s*Average:\s*([\d.]+) secs"),
                         ("min", r"^\s*Fastest:\s*([\d.]+) secs"),
                         ("max", r"^\s*Slowest:\s*([\d.]+) secs")):
        _put(got, steps, key, _find(text, pattern), "s")
    for share, key in (("50", "p50"), ("99", "p99")):
        _put(got, steps, key, _find(text, r"^\s*%s%% in ([\d.]+) secs" % share), "s")
    # Its count is in the status-code distribution, as "[200]\t1000 responses", one line per
    # code. All of them together are what it kept, so a run that answered 900 of 1000 with a 200
    # and 100 with a 503 is not read as having kept 900.
    counts = re.findall(r"^\s*\[\d+\]\s+(\d+)\s+responses", text or "", re.M)
    return _reading("hey", got, steps, kept=sum(int(c) for c in counts) if counts else None)


#: valkey-benchmark's summary columns, by the name its own header row gives each.
VALKEY_COLUMNS = (("avg", ("avg",)), ("min", ("min",)), ("p50", ("p50",)),
                  ("p99", ("p99",)), ("max", ("max",)))

#: memtier_benchmark's latency columns. Older builds head the average "Latency" alone.
MEMTIER_COLUMNS = (("avg", ("Avg. Latency", "Latency")), ("p50", ("p50 Latency",)),
                   ("p99", ("p99 Latency",)))


def read_valkey_benchmark(text):
    """valkey-benchmark's "latency summary (msec)" block, which is a table and not a list.

        latency summary (msec):
                avg       min       p50       p95       p99       max
              0.271     0.000     0.263     0.407     0.887     2.119

    A row of names, then a row of figures, printed at %9.3f. So its step is 0.001 ms and any
    reply faster than half of that reads as 0.000 -- the floor the audit predicted for this tool,
    and the reason the step is taken from the digits rather than assumed.
    """
    match = re.search(r"^[ \t]*latency summary \(msec\):[ \t]*\n[ \t]*(.+)\n[ \t]*(.+)$",
                      text or "", re.M | re.I)
    got, steps = _by_column(match.group(1).split() if match else [],
                            match.group(2).split() if match else [], VALKEY_COLUMNS)
    requests = _find(text, r"([\d]+) requests completed")
    return _reading("valkey-benchmark", got, steps,
                    kept=int(requests) if requests else None)


def read_memtier(text):
    """memtier_benchmark's totals row, read through the header above it.

    Its columns are Type, Ops/sec, Hits/sec, Misses/sec, then the latencies and KB/sec -- but a
    p99.9 latency arrived beside p50 and p99, so which field holds p99 depends on the build.
    """
    header = _find(text, r"^(Type[ \t]+Ops/sec.*)$", 1)
    totals = _find(text, r"^(Totals[ \t]+.*)$", 1)
    got, steps = _by_column([n.strip() for n in re.split(r"\s{2,}", (header or "").strip())],
                            (totals or "").split(), MEMTIER_COLUMNS)
    return _reading("memtier_benchmark", got, steps)


def read_kafka_end_to_end(text):
    """Kafka's EndToEndLatency prints whole milliseconds for the percentiles.

    The audit found it truncates nanoseconds to milliseconds: an average that is exact and
    percentiles that are not. Both are kept as printed, with their own steps, because that gap
    is the prediction and not an inconvenience.
    """
    got, steps = {}, {}
    _put(got, steps, "avg", _find(text, r"Avg latency:\s*([\d.]+)\s*ms"), "ms")
    for share, key in (("50", "p50"), ("99", "p99")):
        raw = _find(text, r"Percentiles?:.*?%sth\s*=\s*(\d+)" % share) or \
            _find(text, r"^\s*%sth\s*=\s*(\d+)" % share)
        _put(got, steps, key, raw, "ms")
    return _reading("kafka-end-to-end", got, steps)


def read_kafka_producer_perf(text):
    """Kafka's ProducerPerformance, whose total line is

        %d%s records sent, %f records/sec (%.2f MB/sec), %.2f ms avg latency,
        %.2f ms max latency, %d ms 50th, %d ms 95th, %d ms 99th, %d ms 99.9th.

    Two decimals on the average and whole milliseconds on every percentile, which is the audit's
    "low, reads a millisecond clock twice, keeps all" class. It prints a shorter line as it goes;
    the total is the one carrying the percentiles, and the progress line is read only when there
    is no total -- a run that was killed, which is a thing T2 has to be able to report.
    """
    match = _last(text, r"^.*records sent.*50th.*$") or _last(text, r"^.*records sent.*$")
    line = match.group(0) if match else ""
    got, steps = {}, {}
    for key, pattern in (("avg", r"([\d.]+)\s*ms avg latency"),
                         ("max", r"([\d.]+)\s*ms max latency"),
                         ("p50", r"(\d+)\s*ms 50th"),
                         ("p99", r"(\d+)\s*ms 99th")):
        _put(got, steps, key, _find(line, pattern), "ms")
    sent = re.match(r"\s*(\d+)", line)
    return _reading("kafka-producer-perf", got, steps,
                    kept=int(sent.group(1)) if sent else None)


def read_rdkafka_performance(text):
    """librdkafka's rdkafka_performance.

    Its counters are microseconds and it prints milliseconds: the format string in
    examples/rdkafka_performance.c is

        ", latency curr/avg/lo/hi %.2f/%.2f/%.2f/%.2fms"

    with every argument divided by 1000.0f first. Reading those figures as the microseconds the
    tool counts in would report every latency a thousand times too small, and two decimals of a
    millisecond is a step of 0.01 ms -- coarser than a tenth of T1's smallest step, which is the
    thing that matters here. Its -l latency mode needs a matching producer and consumer, and it
    is the consumer that subtracts and prints.

    It prints this line as it goes, and its average, low and high are running totals over the
    whole run, so the last one printed is the one that covers it. The figures may be negative --
    its producer and consumer are separate processes, so T2's offset does reach its subtraction.
    """
    match = _last(text, r"latency\s+curr/avg/lo/hi\s+"
                        r"(-?[\d.]+)/(-?[\d.]+)/(-?[\d.]+)/(-?[\d.]+)\s*ms")
    got, steps = {}, {}
    if match:
        for key, group in (("avg", 2), ("min", 3), ("max", 4)):
            _put(got, steps, key, match.group(group), "ms")
    return _reading("rdkafka_performance", got, steps, unit="ms")


def read_k6(text):
    """k6's summary. The audit found it strips the monotonic part of Go's clock.

    http_req_duration is the request; iteration_duration is the whole loop, which in our script
    includes the sleep that paces it, so it is only read when the request metric is absent and is
    never preferred over it.

    k6's default trend statistics are avg, min, med, max, p(90) and p(95) -- no p(99). The runner
    asks for p(99) with --summary-trend-stats; where it is not there, it is missing from the
    reading rather than replaced by p(95).
    """
    got, steps = {}, {}
    line = _find(text, r"^\s*http_req_duration.*$", 0) or \
        _find(text, r"^\s*iteration_duration.*$", 0) or ""
    for key, name in (("avg", "avg"), ("min", "min"), ("p50", "med"), ("p99", r"p\(99\)"),
                      ("max", "max")):
        pair = re.search(r"%s=([\d.]+)(%s)" % (name, GO_UNITS), line)
        if pair:
            _put(got, steps, key, pair.group(1), pair.group(2))
    return _reading("k6", got, steps)


def read_wrk2(text):
    """wrk2's report: a Thread Stats average, then an HdrHistogram distribution under --latency.

        Thread Stats   Avg      Stdev     99%   +/- Stdev
          Latency     1.23ms    0.45ms   3.21ms   75.00%
        Latency Distribution (HdrHistogram - Recorded Latency)
         50.000%    1.10ms

    It is the audit's only medium-class tool: it corrects for coordinated omission, so its
    figures are the delay a request would have seen and not the one it did.
    """
    got, steps = {}, {}
    pair = re.search(r"^\s*Latency\s+([\d.]+)(%s)\s" % GO_UNITS, text or "", re.M)
    if pair:
        _put(got, steps, "avg", pair.group(1), pair.group(2))
    for share, key in (("50", "p50"), ("99", "p99")):
        pair = re.search(r"^\s*%s\.000%%\s+([\d.]+)(%s)" % (share, GO_UNITS), text or "", re.M)
        if pair:
            _put(got, steps, key, pair.group(1), pair.group(2))
    requests = _find(text, r"([\d]+) requests in")
    return _reading("wrk2", got, steps, kept=int(requests) if requests else None)


def read_rabbitmq_perftest(text):
    """RabbitMQ PerfTest's consumer latency line, in whole microseconds.

        id: test-..., consumer latency min/median/75th/95th/99th 99/975/1320/1900/2799 µs

    The label has sat on either side of the figures across versions, so the five names are what
    the reader anchors on. It prints one of these a second and a summary at the end; the last is
    the summary. The audit rates it high and keeps negatives, which is what T2 asks of it.
    """
    # The gap before the figures must not swallow a minus sign: a negative minimum is the whole
    # point of T2 for this tool, and "[^0-9]*" would eat the sign and report -0.89 ms as 0.89.
    match = _last(text, r"min/median/75th/95th/99th[^0-9-]*"
                        r"(-?\d+)/(-?\d+)/(-?\d+)/(-?\d+)/(-?\d+)\s*(%s)" % GO_UNITS)
    got, steps = {}, {}
    if match:
        unit = match.group(6)
        for key, group in (("min", 1), ("p50", 2), ("p99", 5)):
            _put(got, steps, key, match.group(group), unit)
    return _reading("rabbitmq-perftest", got, steps)


def read_nats_latency(text):
    """The NATS CLI's latency report, printed as Go durations truncated to microseconds.

        Minimum Latency: 271µs
        Median Latency : 312µs
        Maximum Latency: 1.204ms
        99:       887µs

    Go writes a duration in whatever unit keeps it readable, so every figure carries its own, and
    the truncation means the step is a microsecond however many digits happen to be printed.
    """
    got, steps = {}, {}
    for key, pattern in (("min", r"^\s*Minimum Latency\s*:\s*([\d.]+)(%s)"),
                         ("p50", r"^\s*Median Latency\s*:\s*([\d.]+)(%s)"),
                         ("max", r"^\s*Maximum Latency\s*:\s*([\d.]+)(%s)"),
                         ("p99", r"^\s*99:\s+([\d.]+)(%s)")):
        pair = re.search(pattern % GO_UNITS, text or "", re.M)
        if pair:
            _put(got, steps, key, pair.group(1), pair.group(2))
    return _reading("nats-latency", got, steps)


#: Every tool this reads, by the name a campaign calls it.
READERS = {
    "vegeta": read_vegeta,
    "hey": read_hey,
    "k6": read_k6,
    "wrk2": read_wrk2,
    "valkey-benchmark": read_valkey_benchmark,
    "memtier_benchmark": read_memtier,
    "kafka-end-to-end": read_kafka_end_to_end,
    "kafka-producer-perf": read_kafka_producer_perf,
    "rdkafka_performance": read_rdkafka_performance,
    "rabbitmq-perftest": read_rabbitmq_perftest,
    "nats-latency": read_nats_latency,
}


def read_tool(tool, text):
    """One tool's output, as a reading. An unknown tool is refused rather than guessed at."""
    if tool not in READERS:
        raise ValueError("no reader for %s; the tools read here are %s"
                         % (tool, ", ".join(sorted(READERS))))
    return READERS[tool](text)


def below_its_step(reading, true_ms, other_ms, figure=None):
    """Whether a difference the reference measured is one this tool could not have reported.

    T1 adds steps of 0.1 ms and asks whether each tool sees them. A tool printing whole
    milliseconds cannot, however good its clock, and that is a property of the tool rather than a
    failure of the run -- so it is reported as out of the tool's reach, not as a miss.

    Naming a figure asks the question of that figure. Kafka's EndToEndLatency can see a tenth of
    a millisecond in its average and nothing below a whole one in its percentiles, and answering
    for the tool as a whole would report the average as blind along with them.
    """
    steps = reading.get("steps_ms") or {}
    step = steps.get(figure) if figure in steps else reading.get("step_ms")
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
