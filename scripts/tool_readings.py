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
import base64
import json
import os
import re
import struct
import sys
import zlib

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
        #: One percent sign or two. hey's documentation shows "50% in"; what it prints is its own
        #: format string's escape, "50%% in", in every real run of 25 September -- so this read
        #: none of its percentiles from any of them, and T1 fell back to its average.
        _put(got, steps, key, _find(text, r"^\s*%s%%{1,2} in ([\d.]+) secs" % share), "s")
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

    http_req_duration is the request, and it is the only figure read (D25-3). This used to fall
    back to iteration_duration when the request metric was absent -- but k6 prints no request
    metric only when it made no request, so the fallback turned nothing into a number. On
    24 September every k6 run did exactly that: no URL reached it, each iteration failed at once,
    and the 9 microseconds a failure took were read as the latency of a request that never left.
    A run that sent no byte is a run that reported nothing, whatever else it printed.

    k6's default trend statistics are avg, min, med, max, p(90) and p(95) -- no p(99). The runner
    asks for p(99) with --summary-trend-stats; where it is not there, it is missing from the
    reading rather than replaced by p(95).
    """
    got, steps = {}, {}
    sent = _find(text, r"^\s*data_sent\.*:\s*([\d.]+)\s*\w*B\b", 1)
    if sent is not None and float(sent) == 0:
        return _reading("k6", got, steps)
    line = _find(text, r"^\s*http_req_duration.*$", 0) or ""
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
        id: test-..., consumer latency min/median/75th/95th/99th/max 271/507/576/692/809/5112 µs

    The label has sat on either side of the figures across versions, so the names are what the
    reader anchors on. The build this block runs prints a sixth, the maximum, and the five-figure
    pattern then matched the label and the first five numbers and stopped at the slash before the
    sixth -- so every run of it read as nothing at all, with its latencies in the file. Both
    shapes are read now, and the maximum is kept where it is there.

    It prints one of these a second and a summary at the end; the last is the summary. The audit
    rates it high and keeps negatives, which is what T2 asks of it.
    """
    # The gap before the figures must not swallow a minus sign: a negative minimum is the whole
    # point of T2 for this tool, and "[^0-9]*" would eat the sign and report -0.89 ms as 0.89.
    match = _last(text, r"min/median/75th/95th/99th(?:/max)?[^0-9-]*"
                        r"(-?\d+)/(-?\d+)/(-?\d+)/(-?\d+)/(-?\d+)(?:/(-?\d+))?"
                        r"\s*(%s)" % GO_UNITS)
    got, steps = {}, {}
    if match:
        unit = match.group(7)
        for key, group in (("min", 1), ("p50", 2), ("p99", 5), ("max", 6)):
            if match.group(group) is not None:
                _put(got, steps, key, match.group(group), unit)
    return _reading("rabbitmq-perftest", got, steps)


def read_nats_latency(text):
    """The NATS CLI's latency report, printed as Go durations truncated to microseconds.

        16:18:00 Minimum Latency: 107µs
        16:18:00 Median Latency : 254µs
        16:18:00 Maximum Latency: 1.631ms
        16:18:00 99:       887µs

    Go writes a duration in whatever unit keeps it readable, so every figure carries its own, and
    the truncation means the step is a microsecond however many digits happen to be printed.

    The clock at the start of each line is why these are not anchored. Written down from the
    tool's documented report, the patterns began at the start of the line; run against the tool,
    every line arrives with the time on it, nothing matched, and T4 stopped saying the tool had
    printed no latency at all -- with its latencies in the file beside the message.
    """
    got, steps = {}, {}
    for key, pattern in (("min", r"Minimum Latency\s*:\s*([\d.]+)(%s)"),
                         ("p50", r"Median Latency\s*:\s*([\d.]+)(%s)"),
                         ("max", r"Maximum Latency\s*:\s*([\d.]+)(%s)"),
                         ("p99", r"\b99:\s+([\d.]+)(%s)")):
        pair = re.search(pattern % GO_UNITS, text or "", re.M)
        if pair:
            _put(got, steps, key, pair.group(1), pair.group(2))
    return _reading("nats-latency", got, steps)


#: HdrHistogram's two V2 encodings, as its Java implementation writes them (AbstractHistogram).
#: The low nibble of a cookie's last byte carries the word size, so it is masked off.
HDR_COMPRESSED, HDR_PLAIN = 0x1c849304, 0x1c849303


def _zigzag_varints(data):
    """HdrHistogram's counts: ZigZag LEB128, seven bits a byte for eight bytes, then all eight
    bits of a ninth (ZigZagEncoding.getLong). A negative number is a run of empty buckets."""
    at = 0
    while at < len(data):
        value, shift = 0, 0
        while True:
            byte = data[at]
            at += 1
            if shift == 56:
                value |= byte << shift
                break
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        yield (value >> 1) ^ -(value & 1)


def hdr_count(encoded):
    """How many values one compressed histogram, as an HdrHistogram log writes it, holds."""
    raw = base64.b64decode(encoded)
    cookie, length = struct.unpack(">ii", raw[:8])
    if cookie & ~0xF0 != HDR_COMPRESSED:
        raise ValueError("not a compressed HdrHistogram: cookie %#x" % cookie)
    inner = zlib.decompress(raw[8:8 + length])
    cookie, payload = struct.unpack(">ii", inner[:8])
    if cookie & ~0xF0 != HDR_PLAIN:
        raise ValueError("not an HdrHistogram: cookie %#x" % cookie)
    # The header: cookie, payload length, normalising offset, significant digits (four bytes
    # each), the lowest and highest trackable values and the conversion ratio (eight each).
    return sum(v for v in _zigzag_varints(inner[40:40 + payload]) if v > 0)


#: The line the runner writes between pulsar-perf's log and its histogram file.
PULSAR_HISTOGRAM = "# pulsar-perf's histogram file"


def read_pulsar_perf(text):
    """Apache Pulsar's performance consumer, `pulsar-perf consume`, at release 4.2.4.

    It closes with two lines, the second carrying the latencies of the whole run:

        Aggregated throughput stats --- 500 records received --- 16.645 msg/s --- ...
        Aggregated latency stats --- Latency: mean: 4.214 ms - med: 4 - 95pct: 5 - 99pct: 10
            - 99.9pct: 42 - 99.99pct: 42 - 99.999pct: 42 - Max: 42

    The mean has three decimals and every percentile is a whole number of milliseconds, because
    the consumer subtracts the producer's publish stamp from System.currentTimeMillis() and
    records the difference only when it is at or above zero (PerformanceConsumer.java:277-283 at
    v4.2.4). "Records received" counts every message, the ones the histogram refused among them,
    so it is what arrived rather than what was kept.

    What it kept is in the histogram file it writes with --histogram-file, ten seconds a line,
    which the runner writes after the log under a line of its own: the sum of every interval's
    count. It decides one thing more. An empty histogram prints a mean of 0.000 and every
    percentile as 0 -- the audit found it, and a user filed it (apache/pulsar#13250) -- which
    reads exactly like a run whose every latency was zero. Where the file shows the tool kept
    nothing, those zeros are not measurements and the reading has no figures.
    """
    log, marker, histograms = (text or "").partition(PULSAR_HISTOGRAM)
    match = _last(log, r"Aggregated latency stats --- Latency: mean:\s*(-?[\d.]+)\s*ms"
                       r" - med:\s*(-?\d+) - 95pct:\s*(-?\d+) - 99pct:\s*(-?\d+).*?"
                       r"Max:\s*(-?\d+)")
    kept = None
    if marker:
        lines = [line.strip() for line in histograms.splitlines()]
        try:
            kept = sum(hdr_count(line.rsplit(",", 1)[1]) for line in lines
                       if line and not line.startswith(("#", '"')) and "," in line)
        except (ValueError, IndexError, struct.error, zlib.error):
            kept = None
    got, steps = {}, {}
    if match and kept != 0:
        for key, group in (("avg", 1), ("p50", 2), ("p99", 4), ("max", 5)):
            _put(got, steps, key, match.group(group), "ms")
    received = _find(log, r"Aggregated throughput stats --- (\d+) records received")
    return _reading("pulsar-perf", got, steps, kept=kept,
                    received=int(received) if received else None)


#: The line the runner writes between emqtt-bench's console and its /metrics page.
EMQTT_METRICS = "# emqtt-bench's /metrics, read at the end of the run"


def read_emqtt_bench(text):
    """emqtt-bench's subscriber at tag 0.6.3, the publisher stamping each payload (`ts`).

    It reports a latency in two places, and they handle a value at or below zero differently:

      * its console, once a second: `6s publish_latency avg=1ms`. A counter that adds only
        latencies above zero, divided by every message received that second, in whole
        milliseconds (src/emqtt_bench.erl:489-494 and 1431-1434). A value at or below zero is
        counted as zero.
      * its Prometheus histogram, `e2e_latency`, which records every latency, zero and below
        included, and whose sum and count the runner reads off /metrics at the end of the run
        and writes after the console's lines:

            e2e_latency_count 500
            e2e_latency_sum 500

    The average read is the histogram's, its sum over its count: the tool's own record of every
    sample, and the only one of its figures fine enough for T1's staircase (D33-4). Its step is a
    millisecond over the count, because the sum is of whole milliseconds. The console's averages
    are kept beside it, as printed, for what they show of the console's own rule. The tool prints
    no percentile: its histogram's finest bucket holds everything up to a millisecond.
    """
    got, steps = {}, {}
    head, _, metrics = (text or "").partition(EMQTT_METRICS)
    count = _find(metrics, r"^e2e_latency_count\s+(\d+)\s*$")
    total = _find(metrics, r"^e2e_latency_sum\s+(-?\d+(?:\.\d+)?)\s*$")
    if count and total is not None and int(count) > 0:
        got["avg"] = float(total) / int(count)
        steps["avg"] = (step_of(total) or 1.0) / int(count)
    printed = [int(v) for v in re.findall(r"publish_latency avg=(-?\d+)ms", head)]
    received = _last(head, r"recv total=(\d+)")
    return _reading("emqtt-bench", got, steps, kept=int(count) if count else None,
                    console_avg_ms=printed,
                    received=int(received.group(1)) if received else None)


#: The line the runner writes between OMB's log and its result file.
OMB_RESULT = "# the benchmark's result file"


def read_omb(text):
    """The OpenMessaging Benchmark at 5b1fa709, in its distributed mode, with its Kafka driver.

    At this commit its log prints the publish latency as it goes and no end-to-end figure at all;
    the end-to-end ones are in the result file it writes with --output, which the runner writes
    after the log:

        "aggregatedEndToEndLatencyAvg" : 2.53156146179402,
        "aggregatedEndToEndLatency50pct" : 2.0,
        "aggregatedEndToEndLatency99pct" : 5.0,
        "aggregatedEndToEndLatencyMax" : 9.0,
        "aggregatedEndToEndLatencyQuantiles" : {"53.588039867109636" : 2.0, ...}

    Every end-to-end sample is a whole number of milliseconds -- the consumer subtracts two
    System.currentTimeMillis() stamps and converts the difference to microseconds -- so each
    percentile, and the smallest value its quantiles hold, steps in whole milliseconds whatever
    digits the file gives it. Only the average can see less. Nothing in the file counts what the
    filter kept or what it dropped.

    The quantiles list every value the histogram recorded, so an empty list is a histogram that
    recorded none -- what the filter leaves when every difference is at or below zero. The
    histogram then reports a mean, percentiles and a maximum of 0.0, which are not measurements,
    and the reading has no figures.
    """
    got, steps = {}, {}
    _, marker, tail = (text or "").partition(OMB_RESULT)
    start = tail.find("{")
    try:
        #: The first object after the line and nothing past it: what the runner prints after the
        #: file is not part of the file.
        result = json.JSONDecoder().raw_decode(tail[start:])[0] if marker and start >= 0 else {}
    except ValueError:
        result = {}
    quantiles = result.get("aggregatedEndToEndLatencyQuantiles")
    if isinstance(quantiles, dict) and not quantiles:
        return _reading("omb", got, steps, kept=0)
    avg = result.get("aggregatedEndToEndLatencyAvg")
    if isinstance(avg, (int, float)):
        got["avg"] = float(avg)
        steps["avg"] = step_of(repr(float(avg)))
    for key, name in (("p50", "aggregatedEndToEndLatency50pct"),
                      ("p99", "aggregatedEndToEndLatency99pct"),
                      ("max", "aggregatedEndToEndLatencyMax")):
        if isinstance(result.get(name), (int, float)):
            got[key], steps[key] = float(result[name]), 1.0
    values = [v for v in (quantiles if isinstance(quantiles, dict) else {}).values()
              if isinstance(v, (int, float))]
    if values:
        got["min"], steps["min"] = float(min(values)), 1.0
    return _reading("omb", got, steps)


def read_ycsb(text):
    """YCSB's summary for its reads, in microseconds, at 66302f30 with its Redis binding.

        [READ], Operations, 500
        [READ], AverageLatency(us), 667.286
        [READ], MinLatency(us), 599
        [READ], MaxLatency(us), 5551
        [READ], 50thPercentileLatency(us), 655
        [READ], 99thPercentileLatency(us), 792

    It times each read on System.nanoTime() and records it as whole microseconds, so the average
    carries decimals and every other figure steps in a microsecond. The 50th percentile is printed
    because the runner asks for it (hdrhistogram.percentiles), as k6 is asked for its 99th.
    """
    got, steps = {}, {}
    for key, name in (("avg", "AverageLatency"), ("min", "MinLatency"), ("max", "MaxLatency"),
                      ("p50", "50thPercentileLatency"), ("p99", "99thPercentileLatency")):
        _put(got, steps, key, _find(text, r"^\[READ\],\s*%s\(us\),\s*(-?[\d.]+)\s*$" % name), "us")
    operations = _find(text, r"^\[READ\],\s*Operations,\s*(\d+)\s*$")
    return _reading("ycsb", got, steps, kept=int(operations) if operations else None)


def read_nats_bench(text):
    """The NATS CLI's benchmark in its request mode, at cc0a8e32 (the nats-latency build).

        NATS Core NATS service requester stats: 49 msgs/sec ~ 25 KiB/sec ~ min: 1,194.58us ~
            avg: 1,267.59us ~ max: 3,132.66us ~ P50: 1,260.20us ~ P90: 1,290.43us ~
            P99: 1,338.33us ~ P99.9: 3,132.66us

    Microseconds with two decimals and a comma at every thousand (internal/bench/stats.go,
    humanize.CommafWithDigits). The comma is a separator, not a decimal point, and is dropped
    before the figure is read; the step is taken from the decimals.
    """
    line = _last(text, r"^.*stats:.*\bmin:.*$")
    found = line.group(0) if line else ""
    got, steps = {}, {}
    for key, name in (("min", "min"), ("avg", "avg"), ("max", "max"), ("p50", "P50"),
                      ("p99", "P99")):
        pair = re.search(r"\b%s:\s*(-?[\d,]+(?:\.\d+)?)(%s)(?=\s|$)" % (name, GO_UNITS), found)
        if pair:
            _put(got, steps, key, pair.group(1).replace(",", ""), pair.group(2))
    return _reading("nats-bench", got, steps)


#: The lines the runner writes between a tool's console and what it reads off the tool after it.
CANARY_METRICS = "# the canary's /metrics, read at the end of the run"
CANARY_LOG = "# the canary's log"
CANARY_SHIPPED = "# the canary's own log reader on that log"
TROGDOR_CONSUME = "# trogdor's consume task"
TROGDOR_PRODUCE = "# trogdor's produce task"
STREAM_CONSUMER = "# the stream consumer instance"
STREAM_METRICS = "# the stream consumer's /metrics, read once the producer had finished"
YSB_UPDATED = "# the generator's updated.txt"
YSB_SEEN = "# the generator's seen.txt"
#: The Yahoo Streaming Benchmark's window, which its notebook subtracts (Benchmark_combined.ipynb,
#: `window_size_ms = 10000`) and its common component divides event times by (time_divisor).
YSB_WINDOW_MS = 10000

#: A number as Java or Prometheus prints a double: digits, a point, an exponent.
_DOUBLE = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"


def read_xinfra_monitor(text):
    """Xinfra Monitor at release 2.5.16, whose reporter logs each metric it is given once a second
    as `mbean:attribute=value`:

        kmf.services:name=single-cluster-monitor,type=consume-service:records-delay-ms-avg=3.25

    Its latency metrics are a rolling minute (ConsumeService.java:94), so the last line of each is
    the run's last minute, and that is what is read. The average is a mean of whole milliseconds,
    the consume service's System.currentTimeMillis() less the produce service's. The percentiles
    come from one-millisecond buckets whose floor is zero, in the kafka-clients its build pins, so a
    negative enters them as 0 (Percentiles.java at 2.8.2). Before its first record a mean prints as
    NaN and a maximum as -Infinity; neither is a measurement and neither is read. It gives no count
    of what it kept, only of what it consumed, which is kept beside the figures and not as `kept`:
    it is paced by a timer and sends what it sends, not a number it was asked for.

    Under S1 (freeze 34) its console also carries the line kafka-clients writes, at debug level,
    for each value below its percentiles' floor that it pins to the floor (Percentiles.java:119-122
    at 2.8.2):

        [2026-10-11 ...] DEBUG Received value -18.0 which is less than min recordable value 0.0,
        will be pinned to the min value (org.apache.kafka.common.metrics.stats.Percentiles)

    Each such value is kept, as `pinned_below_ms`, beside the figures it never shows in: the only
    count anywhere of what its percentiles hid."""
    got, steps = {}, {}
    pinned = [float(v) for v in re.findall(
        r"Received value (%s) which is less than min recordable value" % _DOUBLE, text or "")]
    for key, metric in (("avg", "records-delay-ms-avg"), ("p99", "records-delay-ms-99th"),
                        ("max", "records-delay-ms-max")):
        match = _last(text, r"consume-service:%s=(%s)\s*$" % (re.escape(metric), _DOUBLE))
        if match:
            _put(got, steps, key, match.group(1), "ms")
    #: Its percentiles are one-millisecond buckets and its maximum a whole millisecond, whatever
    #: digits Java prints them with: in the pilot of 11 October its 99th came out as
    #: 2.998800479808077, the bucket of 3 ms at the width of 5,000 ms over its 5,002 buckets. The
    #: average keeps the step of the digits it prints, as the OpenMessaging Benchmark's does.
    for key in ("p99", "max"):
        if key in steps:
            steps[key] = 1.0
    consumed = _last(text, r"consume-service:records-consumed-total=(%s)\s*$" % _DOUBLE)
    return _reading("xinfra-monitor", got, steps,
                    received=int(float(consumed.group(1))) if consumed else None,
                    pinned_below_ms=pinned)


def read_strimzi_canary(text):
    """Strimzi Canary at f3812fb5, which records its end-to-end latency, in whole milliseconds, in
    two places:

      * a Prometheus histogram, read off /metrics before the canary stopped,

            strimzi_canary_records_consumed_latency_sum{clientid="c",partition="0"} 2861
            strimzi_canary_records_consumed_latency_count{clientid="c",partition="0"} 2950

        whose sum over its count is its average, the only figure its metrics give finer than their
        5 ms buckets;
      * its log at verbosity 1, a line per message,

            consumer.go:276] Message received: value={...}, partition=0, offset=41, duration=3 ms

        from which the median, the 99th percentile, the minimum and the maximum are read, minus
        signs included: the reader it ships cannot read one (tools/canary_latencies.py:19). A
        percentile is the value at n times q in the sorted durations.

    It sends a message per partition per tick, and Go drops a tick that comes while the last is
    still running, so it gives no count of what it was asked to send; the count its histogram
    holds is kept beside the figures, not as `kept`."""
    _, _, rest = (text or "").partition(CANARY_METRICS)
    metrics, _, log = rest.partition(CANARY_LOG)
    log, _, shipped = log.partition(CANARY_SHIPPED)
    got, steps = {}, {}
    total = _find(metrics, r"^strimzi_canary_records_consumed_latency_sum\{[^}]*\}\s+(%s)\s*$"
                  % _DOUBLE)
    count = _find(metrics, r"^strimzi_canary_records_consumed_latency_count\{[^}]*\}\s+(%s)\s*$"
                  % _DOUBLE)
    if total is not None and count is not None and float(count) > 0:
        got["avg"] = float(total) / float(count)
        steps["avg"] = 1.0 / float(count)
    durations = sorted(int(d) for d in re.findall(r"Message received:.*?duration=(-?\d+) ms", log))
    if durations:
        for key, at in (("p50", 0.5), ("p99", 0.99)):
            got[key] = float(durations[min(len(durations) - 1, int(len(durations) * at))])
            steps[key] = 1.0
        got["min"], got["max"] = float(durations[0]), float(durations[-1])
        steps["min"] = steps["max"] = 1.0
    #: The average the canary's own log reader printed for the same log, which skips every
    #: negative duration (freeze 34, S1), kept beside the figures rather than read as one.
    shipped_avg = _find(shipped, r"E2E Latency Average:\s*\n\s*(%s)" % _DOUBLE)
    return _reading("strimzi-canary", got, steps,
                    histogram_count=int(float(count)) if count is not None else None,
                    logged=len(durations), logged_negative=sum(1 for d in durations if d < 0),
                    shipped_reader_avg=float(shipped_avg) if shipped_avg is not None else None)


def read_trogdor(text):
    """Kafka's Trogdor at release 3.7.1: the consume task's status as its coordinator reports it,
    in which the timestamp record processor gives the end-to-end latency,

        "recordProcessorStatus" : { "averageLatencyMs" : 2.41, "p50LatencyMs" : 2,
                                    "p95LatencyMs" : 3, "p99LatencyMs" : 5 }

    ProduceBench's wall clock, written into each record, subtracted from the consuming agent's, a
    negative put at the histogram's floor (TimestampRecordProcessor.java:88-89). The average is a
    float and the percentiles whole milliseconds. ConsumeBench's own figures beside it time the
    wait between batches, not a message, and are not read; nor is the produce task's, the publish
    latency, which is the other span."""
    consume, _, produce = (text or "").partition(TROGDOR_CONSUME)[2].partition(TROGDOR_PRODUCE)
    block = _find(consume, r'"recordProcessorStatus"\s*:\s*\{([^}]*)\}') or ""
    got, steps = {}, {}
    for key, field in (("avg", "averageLatencyMs"), ("p50", "p50LatencyMs"),
                       ("p99", "p99LatencyMs")):
        _put(got, steps, key, _find(block, r'"%s"\s*:\s*(%s)' % (field, _DOUBLE)), "ms")
    received = _find(consume, r'"totalMessagesReceived"\s*:\s*(\d+)')
    return _reading("trogdor", got, steps, received=int(received) if received else None)


def read_stream_perftest(text):
    """RabbitMQ Stream PerfTest at release 1.8.0, which prints a line a second,

        13, published 0 msg/s, confirmed 0 msg/s, consumed 50 msg/s, latency
            median/75th/95th/99th 1/2/2/2 ms, chunk size 1

    each holding the last second's percentiles in whole milliseconds
    (DefaultPrintWriterMetricsFormatter.java:62), and at the end only a 95th of about its last
    second (BaseMetricsFormatter.java:111). Its median and 99th percentile are therefore read from
    its own lines a second: the median of their medians and the median of their 99th percentiles,
    over the seconds in which it consumed anything, the first five of those left out as its
    warm-up, every line's figures kept beside them.

    It runs as two instances (D35-4), and only the consumer's lines hold a latency; the runner
    writes them after a line of its own, and where that line is there, nothing before it is read.

    The consumer's /metrics, read once the producer has finished, give its latency timer's total
    count and sum, cumulative over the run (DefaultPerformanceMetrics.java:95-101):

        rabbitmq_stream_latency_seconds_count 3000.0
        rabbitmq_stream_latency_seconds_sum 4.21
        rabbitmq_stream_consumed_total 3000.0

    The count is how many latencies it kept -- it records one only at or above zero (:318-327) --
    and the sum over it, in seconds of whole milliseconds, its average. A second in which it kept
    none prints 0/0/0/0: in the pilot of 11 October, with its consumer's clock 5 ms behind, every
    second did, while it consumed fifty messages a second. So where the count shows it kept fewer
    than it consumed, a line of four zeros is a second it may have emptied, and is not read as a
    measurement; where it kept nothing, there are no figures at all."""
    _, marked, rest = (text or "").partition(STREAM_CONSUMER)
    consumer, _, metrics = (rest if marked else (text or "")).partition(STREAM_METRICS)
    lines = [(int(sec), int(eaten), int(p50), int(p75), int(p95), int(p99))
             for sec, eaten, p50, p75, p95, p99 in re.findall(
                 r"^\s*(\d+), published .*?consumed (\d+) msg/s, latency median/75th/95th/99th"
                 r" (-?\d+)/(-?\d+)/(-?\d+)/(-?\d+) ms", consumer, re.M)]
    count = _find(metrics, r"^rabbitmq_stream_latency_seconds_count(?:\{[^}]*\})?\s+(%s)\s*$"
                  % _DOUBLE)
    total = _find(metrics, r"^rabbitmq_stream_latency_seconds_sum(?:\{[^}]*\})?\s+(%s)\s*$"
                  % _DOUBLE)
    eaten_total = _find(metrics, r"^rabbitmq_stream_consumed_total(?:\{[^}]*\})?\s+(%s)\s*$"
                        % _DOUBLE)
    kept = int(float(count)) if count is not None else None
    received = int(float(eaten_total)) if eaten_total is not None else None
    got, steps = {}, {}
    if kept and total is not None:
        got["avg"] = float(total) * 1000.0 / kept
        steps["avg"] = 1.0 / kept
    emptied = kept is not None and (kept == 0 or (received is not None and kept < received))
    steady = [line for line in lines if line[1] > 0][5:]
    if emptied:
        steady = [line for line in steady if any(line[2:])]
    if steady and kept != 0:
        medians = sorted(line[2] for line in steady)
        nines = sorted(line[5] for line in steady)
        got["p50"] = float(medians[len(medians) // 2])
        got["p99"] = float(nines[len(nines) // 2])
        steps["p50"] = steps["p99"] = 1.0
    return _reading("stream-perftest", got, steps, kept=kept, received=received,
                    seconds=len(lines),
                    per_second=[[sec, eaten, p50, p99] for sec, eaten, p50, _, _, p99 in lines])


def _linear_percentile(ordered, q):
    """numpy's percentile at its default, linear interpolation between the order statistics, on
    values already sorted: what the benchmark's own notebook calls."""
    at = (len(ordered) - 1) * q / 100.0
    low = int(at)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (at - low)


def read_ysb(text):
    """The Yahoo Streaming Benchmark at d1aaf6bb, read as the analysis it ships reads it.

    Its generator's collection (`lein run -g`, core.clj:130-149) writes, for every campaign window
    it finds in Redis, the window's last update less the window's start, in whole milliseconds, one
    a line, into updated.txt -- the processor's wall clock at its last flush of the window less the
    event time the generator wrote, so the ten-second window is inside every value. Its notebook
    (pynotebooks/Benchmark_combined.ipynb, get_filtered_updated) keeps only the values at or above
    the window and subtracts it, and reports numpy's average and percentiles of what is left:
    a window whose latency after the window comes out below zero is dropped, uncounted.

    The reading is that: the average, median, 99th percentile, minimum and maximum of the kept
    windows, each in whole milliseconds, the count kept against the count written, and the kept
    latencies themselves. Beside them, every written window's value less the window, sign kept:
    at its default load a campaign's window holds about thirty views, its last some three hundred
    milliseconds before the window's end on average, and a flush once a second can write the window
    before it ends -- in the pilot of 11 October 301 of 1,200 windows came out below zero on one
    clock, and its notebook dropped them. T2 takes those signed values as its reference where YSB
    is its own (D36-3), so that its predictions start from what YSB wrote and not from what its
    notebook kept."""
    _, marked, rest = (text or "").partition(YSB_UPDATED)
    updated_text = rest.partition(YSB_SEEN)[0]
    written = [int(v) for v in re.findall(r"^\s*(-?\d+)\s*$", updated_text, re.M)]
    kept = sorted(x - YSB_WINDOW_MS for x in written if x >= YSB_WINDOW_MS)
    got, steps = {}, {}
    if kept:
        got["avg"] = sum(kept) / len(kept)
        steps["avg"] = 1.0 / len(kept)
        got["p50"] = float(_linear_percentile(kept, 50.0))
        got["p99"] = float(_linear_percentile(kept, 99.0))
        got["min"], got["max"] = float(kept[0]), float(kept[-1])
        for key in ("p50", "p99", "min", "max"):
            steps[key] = 1.0
    return _reading("ysb", got, steps, kept=len(kept) if marked else None,
                    received=len(written) if marked else None,
                    below_window=sum(1 for x in written if x < YSB_WINDOW_MS) if marked else None,
                    windows_ms=kept, written_ms=sorted(x - YSB_WINDOW_MS for x in written))


def read_pkb(text):
    """PerfKit Benchmarker's messaging benchmark at e5fd49d7, its end-to-end scenario, which prints
    its metrics as one line of JSON when it ends (latency_runner.py:192-194):

        {"e2e_latency_failure_counter": {"value": 0, ...},
         "e2e_latency_mean": {"value": 24.31, "unit": "milliseconds",
                              "metadata": {"samples": [25, 23, ...]}},
         "e2e_latency_p50": {"value": 24.0, ...}, "e2e_latency_p99": {"value": 41.03, ...}, ...}

    Each sample is the receiver's time.time_ns() less the publisher's, floored to whole
    milliseconds (latency_runner.py:27-28, :97-99), and the mean and the percentiles are numpy's
    over every sample, a value below zero included (runners.py:74-104). Its mean, median and 99th
    percentile are read as printed; its minimum and maximum, which it does not print as figures,
    from the samples it prints beside them; the count it kept is the number of samples, and the
    messages it lost are its failure counter. The samples themselves are kept, which is what T2
    takes as its reference where PerfKit is its own (freeze 34)."""
    found = None
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and "e2e_latency_mean" in parsed:
            found = parsed
            break
    got, steps = {}, {}
    if not found:
        return _reading("pkb", got, steps, samples_ms=[])
    samples = [float(v) for v in found["e2e_latency_mean"].get("metadata", {}).get("samples", [])]
    if samples:
        got["avg"] = float(found["e2e_latency_mean"]["value"])
        steps["avg"] = 1.0 / len(samples)
        for key, metric in (("p50", "e2e_latency_p50"), ("p99", "e2e_latency_p99")):
            if metric in found:
                got[key] = float(found[metric]["value"])
                steps[key] = 1.0
        got["min"], got["max"] = min(samples), max(samples)
        steps["min"] = steps["max"] = 1.0
    failures = int(found.get("e2e_latency_failure_counter", {}).get("value", 0))
    return _reading("pkb", got, steps, kept=len(samples), received=len(samples) + failures,
                    failures=failures, samples_ms=samples)


def read_mqtt_benchmark(text):
    """mqtt-benchmark at f46efba1, run with -format json, which prints one JSON document once its
    clients are done (main.go:180-194):

        {"runs": [{"id": 0, "successes": 60, "failures": 0, "msg_time_min": 0.41,
                   "msg_time_max": 1.9, "msg_time_mean": 0.62, ...}, ...],
         "totals": {"successes": 3000, "failures": 0, "msg_time_min": 0.38,
                    "msg_time_max": 2.4, "msg_time_mean_avg": 0.63, ...}}

    Each client times publish to its acknowledgment in one goroutine, m.Delivered.Sub(m.Sent) on
    Go's monotonic clock, in milliseconds as a float (client.go:110, 120, 57), and it prints no
    percentile. Its minimum and maximum are read from its totals, and its average as the mean of
    every message, from each client's mean weighted by its successes. The count it kept is its
    successes, of the successes and failures it was asked to send."""
    text = text or ""
    found, start = None, text.find("{")
    while start != -1:
        try:
            found, _ = json.JSONDecoder().raw_decode(text[start:])
        except ValueError:
            found = None
        if isinstance(found, dict) and isinstance(found.get("totals"), dict):
            break
        found, start = None, text.find("{", start + 1)
    got, steps = {}, {}
    if not found:
        return _reading("mqtt-benchmark", got, steps)
    totals = found["totals"]
    runs = [r for r in found.get("runs") or [] if r.get("successes")]
    if runs:
        done = sum(int(r["successes"]) for r in runs)
        got["avg"] = sum(float(r["msg_time_mean"]) * int(r["successes"]) for r in runs) / done
        got["min"], got["max"] = float(totals["msg_time_min"]), float(totals["msg_time_max"])
        steps.update(avg=1e-6, min=1e-6, max=1e-6)
    kept = int(totals.get("successes") or 0)
    return _reading("mqtt-benchmark", got, steps, kept=kept,
                    received=kept + int(totals.get("failures") or 0))


#: The line Sarama's tool prints every five seconds and once more as it ends (main.go:440-451).
SARAMA_LINE = (r"(\d+) records sent, .*? (-?\d+(?:\.\d+)?) ms avg latency, (-?\d+(?:\.\d+)?) ms "
               r"stddev, (-?\d+(?:\.\d+)?) ms 50th, (-?\d+(?:\.\d+)?) ms 75th, (-?\d+(?:\.\d+)?) ms "
               r"95th, (-?\d+(?:\.\d+)?) ms 99th, (-?\d+(?:\.\d+)?) ms 99\.9th")


def read_sarama_producer_perf(text):
    """IBM Sarama's kafka-producer-performance at 36f7a14e: the last of its metrics lines, the one it
    prints as it ends. Its latency is Sarama's request-latency-in-ms: every request on every broker
    connection, produce and metadata alike, each time.Since its write on Go's monotonic clock and
    truncated to whole milliseconds before it enters a 1,028-sample reservoir (broker.go:1371,
    1983-1984). Its percentiles interpolate between those whole numbers, so the step any one
    latency can take is a millisecond whatever decimals the line prints. The records it counts are
    messages acknowledged, not latencies: it keeps none per message, so no count of them is read."""
    match = _last(text, SARAMA_LINE)
    got, steps = {}, {}
    if not match:
        return _reading("sarama-producer-perf", got, steps)
    for key, group in (("avg", 2), ("p50", 4), ("p75", 5), ("p95", 6), ("p99", 7), ("p999", 8)):
        got[key] = float(match.group(group))
        steps[key] = 1.0
    return _reading("sarama-producer-perf", got, steps, records=int(match.group(1)),
                    stddev_ms=float(match.group(3)))


#: SBK's total line, in the time unit it was given, ms by default. Its console logger
#: begins it "<time>, Total <prefix>", then its writers and readers, and ends it with what perl's
#: ResultsLogger.appendResultString writes, from the run's seconds on (AbstractSystemLogger
#: printTotal, AbstractRWLogger.appendResultString); "N seconds, X MB, N records" is where that
#: part begins, and nothing before it prints a count straight before "records,".
SBK_TOTAL = (r"\bTotal\b.*?\d+ seconds, +-?[\d.]+ MB, +(\d+) records, .*? (-?\d+(?:\.\d+)?) (\w+) "
             r"avg latency, +(-?\d+) \w+ min latency, +(-?\d+) \w+ max latency; +(\d+) invalid "
             r"latencies; Discarded Latencies: *(\d+) lower, +(\d+) higher;.*?Latency Percentiles: "
             r"(.*)$")
#: Its own names for its time units, which its line prints (its -time option takes the same).
SBK_UNITS = {"ms": "ms", "mcs": "us", "ns": "ns"}
SBK_PERCENTILES = {"50": "p50", "90": "p90", "99": "p99", "99.9": "p999"}


def read_sbk(text):
    """SBK 10.8 at 39af60da, its Kafka driver in Write_Reading, writer and reader in one process: its
    total line. Its reader takes the stamp in the first record of each poll and subtracts it from
    its own clock (KafkaReader.recordReadTime), System.currentTimeMillis() in its default unit.
    LatencyRecorder.record() keeps a value below zero out of its minimum, maximum, mean and
    percentiles and counts it as invalid (LatencyRecorder.java:125-126), and the count is printed.

    Its records are every record its reader polled in the run's time, the invalid ones among them,
    so they are carried as what it received and not held as a count kept against the count sent;
    the invalid count is carried beside them, with the values it discarded as out of range, which
    stay in its mean and extremes and leave its percentiles."""
    match = _last(text, SBK_TOTAL)
    got, steps = {}, {}
    if not match:
        return _reading("sbk", got, steps)
    unit = SBK_UNITS.get(match.group(3))
    if unit:
        _put(got, steps, "avg", match.group(2), unit)
        _put(got, steps, "min", match.group(4), unit)
        _put(got, steps, "max", match.group(5), unit)
        for value, name in re.findall(r"(-?\d+) \w+ ([\d.]+)th", match.group(9)):
            if name in SBK_PERCENTILES:
                got[SBK_PERCENTILES[name]] = as_ms(float(value), unit)
                steps[SBK_PERCENTILES[name]] = as_ms(1.0, unit)
    return _reading("sbk", got, steps, received=int(match.group(1)), invalid=int(match.group(6)),
                    discarded_lower=int(match.group(7)), discarded_higher=int(match.group(8)),
                    unit=unit)


KGO_STATUS = "# kgo-repeater B's /status, read at the end of the run"


def read_kgo_repeater(text):
    """Redpanda's kgo-repeater at 6567f2f5, the repeater B that consumes and never produces: its
    /status, a list with one entry per worker, each with its counts and its latencies' p50, p90 and
    p99 in microseconds (worker.go:18-30, repeater_worker.go WorkerStatus). The end-to-end latency
    is B's time.Now().UnixMicro() less the stamp A wrote with its own wall clock, kept in a
    1,024-sample reservoir with no test of its sign (repeater_worker.go:258-261). It prints no
    minimum, no mean and no count of latencies; the messages its one worker consumed since its
    reset are carried as what it received."""
    status = text.split(KGO_STATUS, 1)[1] if KGO_STATUS in (text or "") else ""
    workers, start = [], status.find("[")
    if start != -1:
        try:
            workers, _ = json.JSONDecoder().raw_decode(status[start:])
        except ValueError:
            workers = []
    workers = [w for w in workers if isinstance(w, dict) and (w.get("consumed") or 0) > 0]
    got, steps = {}, {}
    if len(workers) == 1:
        e2e = (workers[0].get("latency") or {}).get("e2e") or {}
        for key in ("p50", "p90", "p99"):
            if isinstance(e2e.get(key), (int, float)):
                got[key] = float(e2e[key]) / 1000.0
                steps[key] = 1e-3
    return _reading("kgo-repeater", got, steps,
                    received=sum(int(w["consumed"]) for w in workers) or None, workers=len(workers))


ARTEMIS_CONSOLE = "# artemis perf consumer's console"
ARTEMIS_JSON = "# artemis perf consumer's JSON"
ARTEMIS_PRODUCER_JSON = "# artemis perf producer's JSON"


def _artemis_objects(part):
    """The JSON objects Artemis's perf client wrote to a file, in order, skipping what is torn."""
    found, start = [], part.find("{")
    while start != -1:
        try:
            one, end = json.JSONDecoder().raw_decode(part[start:])
        except ValueError:
            start = part.find("{", start + 1)
            continue
        found.append(one)  # a value that begins with "{" decodes to an object
        start = part.find("{", start + end)
    return found


def _artemis_summary(part):
    """The last "summary" object among them, or None."""
    return next((o for o in reversed(_artemis_objects(part)) if o.get("sampleType") == "summary"), None)


def _artemis_sent(part):
    """How many the producer sent: its summary's count, or, where it was stopped before writing one,
    the sum of its one-second intervals' send rates, which approaches the count; and which it was."""
    summary = _artemis_summary(part)
    if summary is not None and summary.get("totalSent") is not None:
        return summary["totalSent"], "summary"
    rates = [o["sent"] for o in _artemis_objects(part)
             if o.get("sampleType") == "interval" and isinstance(o.get("sent"), (int, float))]
    return (int(sum(rates)), "intervals") if rates else (None, None)


def read_artemis_perf(text):
    """Artemis 2.57.0's perf consumer: the summary object its --json file ends with
    (LiveStatistics.appendJsonSummarySampleOnFile), its transfer-time percentiles in microseconds,
    each the consumer's clock less the stamp the producer put in the message's "time" property
    (RecordingMessageListener.java:85-88). A value below zero makes HdrHistogram 2.2.2 throw before
    it counts anything, so the histogram's count is the latencies it kept, against the messages it
    received, which counts every redelivery of a message rolled back after that throw; each throw
    leaves an AMQ132001 warning on the console, which is counted beside them. Its figures are read
    only where its histogram counted something: an empty histogram prints zeros that time nothing.
    The producer's own summary gives how many it sent (freeze 36's pilot: under S1's steps it
    stopped after ten, and said success)."""
    text = text or ""
    producer_part = text.split(ARTEMIS_PRODUCER_JSON, 1)[1] if ARTEMIS_PRODUCER_JSON in text else ""
    json_part = text.split(ARTEMIS_JSON, 1)[1].split(ARTEMIS_PRODUCER_JSON, 1)[0] if ARTEMIS_JSON in text else ""
    console = text.split(ARTEMIS_CONSOLE, 1)[1].split(ARTEMIS_JSON, 1)[0] if ARTEMIS_CONSOLE in text else ""
    summary = _artemis_summary(json_part)
    produced = _artemis_summary(producer_part) or {}
    sent, sent_from = _artemis_sent(producer_part)
    got, steps = {}, {}
    extra = {"producer_sent": sent, "producer_sent_from": sent_from,
             "producer_result": produced.get("result")}
    if summary is None:
        return _reading("artemis-perf", got, steps, refused=console.count("AMQ132001"), **extra)
    transfer = summary.get("totalTransferTime") or {}
    kept = int(transfer.get("count") or 0)
    if kept:
        for key, field in (("avg", "mean"), ("p50", "50"), ("p90", "90"), ("p99", "99"),
                           ("p999", "99.9"), ("max", "max")):
            if field in transfer:
                got[key] = float(transfer[field]) / 1000.0
                steps[key] = 1e-3
    return _reading("artemis-perf", got, steps, kept=kept,
                    received=summary.get("totalReceived"), result=summary.get("result"),
                    refused=console.count("AMQ132001"), **extra)


ROCKETMQ_CONSUMER = (r"Consume TPS: (\d+) \| AVG\(B2C\) RT\(ms\): +(-?[\d.]+|NaN) \| AVG\(S2C\) "
                     r"RT\(ms\): +(-?[\d.]+|NaN) \| MAX\(B2C\) RT\(ms\): (-?\d+) \| MAX\(S2C\) "
                     r"RT\(ms\): (-?\d+) \| Consume Fail: (\d+)")


def read_rocketmq_benchmark(text):
    """RocketMQ 5.5.1's benchmark Consumer: its report every ten seconds (Consumer.java:115). Its
    B2C is the consumer's System.currentTimeMillis() less the message's born time, the producer's
    clock, in whole milliseconds; each is added to a total, so its average keeps a value below zero,
    and its maximum starts at 0 and rises only past it, reset at each report, so it cannot show one.
    Read over the reports in which messages arrived: the average weighted by each report's rate, the
    largest maximum; S2C, against the broker's clock, beside them. The Producer's last count is the
    messages it sent."""
    rows = [m for m in re.finditer(ROCKETMQ_CONSUMER, text or "")
            if int(m.group(1)) > 0 and m.group(2) != "NaN"]
    got, steps = {}, {}
    if rows:
        weight = sum(int(m.group(1)) for m in rows)
        got["avg"] = sum(float(m.group(2)) * int(m.group(1)) for m in rows) / weight
        got["max"] = float(max(int(m.group(4)) for m in rows))
        steps.update(avg=1e-3, max=1.0)
    sent = _last(text, r"\[Complete\] Send Total: (\d+)")
    s2c = [float(m.group(3)) for m in rows]
    return _reading("rocketmq-benchmark", got, steps, reports=len(rows),
                    report_rows=[[int(m.group(1)), float(m.group(2)), int(m.group(4))] for m in rows],
                    sent=int(sent.group(1)) if sent else None,
                    s2c_avg_ms=sum(s2c) / len(s2c) if s2c else None,
                    consume_fail=sum(int(m.group(6)) for m in rows))


BOOKKEEPER_DUMP = "# bookkeeper benchmark's latency dump"


def read_bookkeeper_benchmark(text):
    """BookKeeper 4.18.1's `bin/benchmark writes`: the latencies its dump file holds, one line each,
    "<nanoseconds>\\t<milliseconds>ms", sorted, each System.nanoTime() at completion less the
    nanoTime taken just before asyncAddEntry (BenchThroughputLatency.java:187-188, 239, 429-433). It
    keeps only values above zero (:397-410), which is also how it leaves out a failed add, and its
    log prints the 95th and 99th percentiles of those, in milliseconds (:438-439, :445-451). Its
    median, mean, minimum and maximum are read from the dump; its percentiles as it printed them."""
    text = text or ""
    dump = text.split(BOOKKEEPER_DUMP, 1)[1] if BOOKKEEPER_DUMP in text else ""
    samples = [int(m.group(1)) / 1e6 for m in re.finditer(r"^(-?\d+)\t-?\d+ms$", dump, re.M)]
    got, steps = {}, {}
    if samples:
        ordered = sorted(samples)
        got["p50"] = _linear_percentile(ordered, 50)
        got["avg"] = sum(samples) / len(samples)
        got["min"], got["max"] = ordered[0], ordered[-1]
        steps.update(p50=1e-6, avg=1e-6, min=1e-6, max=1e-6)
    for name in ("95", "99"):
        printed = _last(text, r"%sth percentile latency.*?latency=(-?[\d.]+(?:[eE][+-]?\d+)?)" % name)
        if printed:
            got["p%s" % name] = float(printed.group(1))
            steps["p%s" % name] = 1e-6
    done = _last(text, r"Benchmark complete.*?completions=(\d+)")
    sent = _last(text, r"\bSent\b.*?sent=(\d+)")
    return _reading("bookkeeper-benchmark", got, steps, samples_ms=samples,
                    completions=int(done.group(1)) if done else None,
                    sent=int(sent.group(1)) if sent else None)


QUIVER_RECEIVER = "# quiver receiver's console"
QUIVER_SENDER = "# quiver sender's console"
QUIVER_SUMMARY = "# quiver receiver's summary"
QUIVER_SENT = "# quiver sender's summary"
QUIVER_TRANSFERS = "# quiver receiver's transfers"
_QUIVER_PARTS = (QUIVER_RECEIVER, QUIVER_SENDER, QUIVER_SUMMARY, QUIVER_SENT, QUIVER_TRANSFERS)
#: A figure past 10^18 ms, some thirty million years, is one Quiver's unsigned subtraction wrapped:
#: a value below zero lands at 2^64 less its size, about 1.8 x 10^19 ms. block_v40.py and
#: s1_block.py judge by the same bound.
QUIVER_WRAPPED_MS = 1e18


def _part(text, head, heads):
    """What follows one of a run's headers, up to whichever of the others comes next."""
    if head not in text:
        return ""
    part = text.split(head, 1)[1]
    for other in heads:
        part = part.split(other, 1)[0]
    return part


def read_quiver(text):
    """Quiver's receiving arrow: the summary its wrapper wrote (arrow.py:310-346) -- the average,
    the quartiles (0, 25, 50, 75 and 100 per cent) and the nines (90 to 99.999 per cent), whole
    milliseconds but for the average -- from the transfers its JMS arrow wrote, the sender's
    System.currentTimeMillis() carried in the message beside its own at receipt
    (QuiverArrowJms.java:233, 274), subtracted as unsigned 64-bit integers (arrow.py:264-265, 301),
    so that a value below zero becomes 2^64 less its size. The transfers are read again here with
    their sign, which is what samples_ms and below_zero count, and the figures that wrapped are named.
    The sender's summary gives how many it sent."""
    text = text or ""
    summary = next(iter(_artemis_objects(_part(text, QUIVER_SUMMARY, _QUIVER_PARTS))), None) or {}
    sender = next(iter(_artemis_objects(_part(text, QUIVER_SENT, _QUIVER_PARTS))), None) or {}
    transfers = _part(text, QUIVER_TRANSFERS, _QUIVER_PARTS)
    samples = [int(got) - int(left) for left, got in re.findall(r"^(\d+),(\d+)$", transfers, re.M)]
    results = summary.get("results") or {}
    got, steps = {}, {}
    if results.get("latency_average") is not None:
        got["avg"], steps["avg"] = float(results["latency_average"]), 1e-3
    named = list(zip(("min", "p25", "p50", "p75", "max"), results.get("latency_quartiles") or []))
    named += list(zip(("p90", "p99", "p999", "p9999", "p99999"), results.get("latency_nines") or []))
    for key, value in named:
        got[key], steps[key] = float(value), 1.0
    return _reading("quiver", got, steps, samples_ms=samples,
                    below_zero=sum(1 for v in samples if v < 0) if samples else None,
                    wrapped=sorted(k for k, v in got.items() if v >= QUIVER_WRAPPED_MS),
                    kept=results.get("message_count"), received=results.get("message_count"),
                    sent=(sender.get("results") or {}).get("message_count"))


PRAVEGA_TOTAL = (r"(\d+) records Write/Reading, [\d.]+ records/sec, \d+ bytes record size, [\d.]+ "
                 r"MiB/sec, (-?[\d.]+|NaN) ms avg latency, (-?[\d.]+) ms max latency, (-?\d+) ms "
                 r"50th, (-?\d+) ms 75th, (-?\d+) ms 95th, (-?\d+) ms 99th, (-?\d+) ms 99\.9th, "
                 r"(-?\d+) ms 99\.99th")
PRAVEGA_WINDOW = (r"(\d+) records Write/Reading, +[\d.]+ records/sec, +[\d.]+ MiB/sec, +"
                  r"(-?[\d.]+|NaN) ms avg latency, +(-?[\d.]+) ms max latency$")
#: Java 8 prints the index after a colon; Java 11 and later as "Index <i> out of bounds".
PRAVEGA_THROWN = r"ArrayIndexOutOfBoundsException(?:: (?:Index )?(-?\d+))?"


def read_pravega_benchmark(text):
    """The Pravega benchmark in its End to End mode: its final line (PerfStats.java:351-355) -- the
    records it counted, their average and maximum to a tenth of a millisecond and six percentiles in
    whole milliseconds -- each the reader's System.currentTimeMillis() less the writer's, carried in
    the event (WriterWorker.java:207-208, ReaderWorker.java:135-141), counted into an array indexed by
    the value (PerfStats.java:123-126, 334-337); and its window lines (:233-234). A value below zero
    throws there, in its one statistics task, which then prints neither another window nor its total:
    the exceptions it printed are counted, with the indices they name."""
    text = text or ""
    total = _last(text, PRAVEGA_TOTAL)
    got, steps = {}, {}
    if total and total.group(2) != "NaN":
        got["avg"], got["max"] = float(total.group(2)), float(total.group(3))
        steps.update(avg=0.1, max=0.1)
        for key, at in (("p50", 4), ("p75", 5), ("p95", 6), ("p99", 7), ("p999", 8), ("p9999", 9)):
            got[key], steps[key] = float(total.group(at)), 1.0
    windows = [[int(m.group(1)), None if m.group(2) == "NaN" else float(m.group(2)), float(m.group(3))]
               for m in re.finditer(PRAVEGA_WINDOW, text, re.M)]
    thrown = list(re.finditer(PRAVEGA_THROWN, text))
    return _reading("pravega-benchmark", got, steps, final=total is not None,
                    kept=int(total.group(1)) if total else None, windows=len(windows),
                    window_rows=windows, thrown=len(thrown),
                    thrown_at=sorted({int(m.group(1)) for m in thrown if m.group(1)}))


PUBSUB_CONSOLE = "# pubsub driver's console"
PUBSUB_STATUS = "# pubsub driver's exit status"
PUBSUB_SECONDS = "# pubsub test seconds"
PUBSUB_CSV = "# pubsub output.csv"
PUBSUB_BURN_IN = "# pubsub burn-in seconds"
PUBSUB_ASIDE = "# pubsub attempts set aside"
_PUBSUB_PARTS = (PUBSUB_CONSOLE, PUBSUB_STATUS, PUBSUB_SECONDS, PUBSUB_CSV, PUBSUB_BURN_IN,
                 PUBSUB_ASIDE)
_PUBSUB_CHECK = re.compile(r"Connected to cps-gcloud-\w+-(publisher|subscriber) client\.\s+Got check "
                           r"response:(.*)$")
#: What its controller throws when a percentile's share of the values lies in bucket 0, where 0, 1
#: and every negative value land (LatencyTracker.java:37-52).
PUBSUB_THROWN = "Programming error: negative values appear in buckets."
_PUBSUB_NUMBER = r"[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?"
_PUBSUB_KEYS = {"50": "p50", "90": "p90", "99": "p99", "99.9": "p999"}


def _pubsub_ranges(console):
    """Each client side's printed percentile ranges, {side: {key: [low, high]}}, by the "Results
    for" line before them (Driver.java:243-246)."""
    side, ranges = None, {}
    for line in console.splitlines():
        named = re.search(r"Results for cps-gcloud-\w+-(publisher|subscriber):", line)
        if named:
            side = named.group(1)
            ranges.setdefault(side, {})
            continue
        printed = re.search(r"\b(50|99|99\.9)%%: (%s) - (%s)" % (_PUBSUB_NUMBER, _PUBSUB_NUMBER),
                            line)
        if printed and side:
            ranges[side][_PUBSUB_KEYS[printed.group(1)]] = [float(printed.group(2)),
                                                            float(printed.group(3))]
    return ranges


def _pubsub_table(part):
    """The rows of the output.csv its driver writes (CsvOutput.java:36-38, 83-86, 95-98), by side:
    its rate and each percentile's midpoint."""
    lines = [l.strip() for l in part.splitlines() if l.strip()]
    if not lines:
        return {}
    names = lines[0].split(",")
    found = {}
    for line in lines[1:]:
        row = dict(zip(names, line.split(",")))
        side = (row.get("Messaging Side") or "").lower()
        cells = {}
        for key, column in (("qps", "QPS"), ("p50", "50%ile Latency"), ("p90", "90%ile Latency"),
                            ("p99", "99%ile Latency"), ("p999", "99.9%ile Latency")):
            if re.fullmatch(_PUBSUB_NUMBER, row.get(column) or ""):
                cells[key] = float(row[column])
        found[side] = cells
    return found


def _pubsub_responses(console):
    """Every check response its driver logged from its clients (Client.java:232-236), in order:
    [{"side": ..., "seconds": ..., "counts": [...]}]. Bucket n holds the values in
    [1.5^n, 1.5^(n+1)) ms, and bucket 0 every value at or below 1 ms (MetricsHandler.java:72-73).
    The seconds are the running duration the response reports, its seconds and nanoseconds
    together, below zero where the client's wall clock has not yet reached the start it was given,
    as under S1's steps; a duration the response leaves out is protobuf's zero."""
    found, open_, timing = [], None, False
    for line in console.splitlines():
        checked = _PUBSUB_CHECK.search(line)
        if line.startswith("["):
            open_, timing = None, False
            if not checked:
                continue
            open_ = {"side": checked.group(1), "counts": [], "seconds": 0.0}
            found.append(open_)
            line = checked.group(2)
        if open_ is None:
            continue
        if re.fullmatch(r"\s*running_duration \{\s*", line):
            timing = True
            continue
        value = re.fullmatch(r"\s*bucket_values: (\d+)\s*", line)
        if value and not timing:
            open_["counts"].append(int(value.group(1)))
            continue
        part = re.fullmatch(r"\s*(seconds|nanos): (-?\d+)\s*", line)
        if part and timing:
            open_["seconds"] += int(part.group(2)) / (1.0 if part.group(1) == "seconds" else 1e9)
            continue
        if line.strip() == "}":
            timing = False
    return found


def pubsub_responses(text):
    """The check responses in one run's printed output, as _pubsub_responses reads its console."""
    return _pubsub_responses(_part(text or "", PUBSUB_CONSOLE, _PUBSUB_PARTS))


def _pubsub_buckets(console, burn_in):
    """Each side's buckets, summed over its check responses (_pubsub_responses). Its controller adds
    a response's buckets only where the running duration the response reports is longer than the
    burn-in (Client.java:246-250), so those are counted apart from the burn-in's:
    {"after": {side: [...]}, "burn_in": {side: [...]}}. With no burn-in given, every response counts
    as after it."""
    found = {"after": {}, "burn_in": {}}
    for block in _pubsub_responses(console):
        late = burn_in is None or block["seconds"] > burn_in
        counts = found["after" if late else "burn_in"].setdefault(block["side"], [])
        while len(counts) < len(block["counts"]):
            counts.append(0)
        for i, n in enumerate(block["counts"]):
            counts[i] += n
    return found


def _pubsub_width(midpoint):
    """The width of the bucket whose midpoint its controller printed: bucket 0 is [0, 1), and bucket
    n > 0 is [1.5^(n-1), 1.5^n), whose midpoint is 1.25 times its floor and whose width is half it."""
    return 1.0 if midpoint == 0.5 else 0.4 * midpoint


def read_pubsub_loadtest(text):
    """Google's Cloud Pub/Sub load test framework, run by its driver in local mode: the percentile
    ranges its controller prints for each client side (Driver.java:239-246) and the midpoints it
    writes to output.csv. Its subscriber's latency is its System.currentTimeMillis() less the
    publisher's, carried in the message (CPSSubscriberTask.java:68-70, AbstractPublisher.java:83),
    put into bucket floor(log1.5 ms), floored at 0 (MetricsHandler.java:72-73), so that 0, 1 and
    every value below zero share bucket 0; its publisher's is its own publish to success, in one
    process (AbstractPublisher.java:93-95). Its controller labels bucket n [1.5^(n-1), 1.5^n), one
    bucket below the values in it, and throws PUBSUB_THROWN when a percentile's share lies in bucket
    0, before it writes output.csv or exits with status 0. Read: the subscriber's figures, which are
    what the run reports, its ranges and the publisher's, how many times that exception was printed,
    how many lines mention a value below zero at all, the messages it says went missing, its exit
    status, and the counts its rates give over the test's seconds."""
    text = text or ""
    console = _part(text, PUBSUB_CONSOLE, _PUBSUB_PARTS)
    status = re.search(r"^\s*(-?\d+)\s*$", _part(text, PUBSUB_STATUS, _PUBSUB_PARTS), re.M)
    seconds = re.search(r"^\s*(\d+)\s*$", _part(text, PUBSUB_SECONDS, _PUBSUB_PARTS), re.M)
    table = _pubsub_table(_part(text, PUBSUB_CSV, _PUBSUB_PARTS))
    ranges = _pubsub_ranges(console)
    figures = {}
    for side in ("subscriber", "publisher"):
        got, steps = {}, {}
        for key in ("p50", "p90", "p99", "p999"):
            printed = ranges.get(side, {}).get(key)
            middle = table.get(side, {}).get(key)
            if middle is None and printed:
                middle = (printed[0] + printed[1]) / 2.0
            if middle is None:
                continue
            got[key] = middle
            steps[key] = printed[1] - printed[0] if printed else _pubsub_width(middle)
        figures[side] = (got, steps)
    missing = _last(console, r"Missing (\d+) total messages")
    span = int(seconds.group(1)) if seconds else None
    burn = re.search(r"^\s*(\d+)\s*$", _part(text, PUBSUB_BURN_IN, _PUBSUB_PARTS), re.M)
    aside = re.search(r"^\s*(\d+)\s*$", _part(text, PUBSUB_ASIDE, _PUBSUB_PARTS), re.M)
    buckets = _pubsub_buckets(console, int(burn.group(1)) if burn else None)

    def count(side):
        rate = table.get(side, {}).get("qps")
        return None if rate is None or span is None else int(round(rate * span))

    exit_status = int(status.group(1)) if status else None
    return _reading("pubsub-loadtest", figures["subscriber"][0], figures["subscriber"][1],
                    ranges=ranges, publisher_ms=figures["publisher"][0],
                    thrown=console.count(PUBSUB_THROWN),
                    mentions_negative=len(re.findall(r"^.*negative.*$", console, re.M | re.I)),
                    missing=int(missing.group(1)) if missing else None,
                    exit=exit_status, wrote_csv=bool(table),
                    final=exit_status == 0 and bool(table), kept=count("subscriber"),
                    sent=count("publisher"), buckets=buckets["after"],
                    buckets_burn_in=buckets["burn_in"],
                    set_aside=int(aside.group(1)) if aside else None, unit="ms")


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
    # The five the plan registered and version 15 left unrun (D15-6), run under freeze 30.
    "omb": read_omb,
    "pulsar-perf": read_pulsar_perf,
    "emqtt-bench": read_emqtt_bench,
    "ycsb": read_ycsb,
    "nats-bench": read_nats_bench,
    # Freeze 32's four (D35-1): two Kafka monitors, Kafka's own Trogdor, and RabbitMQ's tool for
    # its streams, each read where its own documentation says it reports.
    "xinfra-monitor": read_xinfra_monitor,
    "strimzi-canary": read_strimzi_canary,
    "trogdor": read_trogdor,
    "stream-perftest": read_stream_perftest,
    # Freeze 33's YSB (D36-4), read as the notebook it ships reads its windows.
    "ysb": read_ysb,
    # Freeze 34's PerfKit messaging benchmark, read from the metrics line it prints.
    "pkb": read_pkb,
    # Freeze 34's S1: Stream PerfTest as one instance, its default, read as its two instances are.
    "stream-perftest-one": lambda text: dict(read_stream_perftest(text), tool="stream-perftest-one"),
    # Freeze 35's four (D38-2), each read where its own source says it reports.
    "mqtt-benchmark": read_mqtt_benchmark,
    "sarama-producer-perf": read_sarama_producer_perf,
    "sbk": read_sbk,
    "kgo-repeater": read_kgo_repeater,
    # Freeze 36's three (D39-2), each read where its own source says it reports.
    "artemis-perf": read_artemis_perf,
    "rocketmq-benchmark": read_rocketmq_benchmark,
    "bookkeeper-benchmark": read_bookkeeper_benchmark,
    # Freeze 37's two (D40-2), each read where its own source says it reports.
    "quiver": read_quiver,
    "pravega-benchmark": read_pravega_benchmark,
    # Freeze 38's one (D41-2), read where its own source says it reports.
    "pubsub-loadtest": read_pubsub_loadtest,
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


def step_seen(staircase):
    """What T1's staircase says this tool can report, from its own answers at each step.

    `staircase` is (added_ms, reading) pairs, one per step, including the zero step. Each step's
    reported average is compared with the tool's average at zero, and a step it moved by less
    than its own printing step is one it could not report.

    The smallest step it *did* report is the tool's step as measured rather than as printed, and
    it is what T2 has to predict through. A tool that cannot report a tenth of a millisecond does
    not meet a negative a tenth of a millisecond below zero either: its clock puts that value at
    zero before its rule for odd values ever runs.
    """
    base = next((r["reported_ms"].get("avg") for added, r in staircase if added == 0.0), None)
    moves, smallest = [], None
    for added, reading in sorted(staircase, key=lambda pair: pair[0]):
        avg, step = reading["reported_ms"].get("avg"), reading.get("step_ms")
        moved = None if (avg is None or base is None) else avg - base
        seen = bool(moved is not None and step is not None and abs(moved) >= step)
        if seen and added > 0.0 and (smallest is None or added < smallest):
            smallest = added
        moves.append({"added_ms": added, "reported_avg_ms": avg, "moved_ms": moved, "seen": seen})
    return {"zero_avg_ms": base, "smallest_reported_ms": smallest, "steps": moves}


#: How many times a tool's measured interval crosses the delayed direction (D25-5). T1 delays the
#: broker's traffic toward the driver, so a round trip meets it once. kafka-end-to-end sends,
#: waits for the broker's acknowledgement, and then fetches the message back: twice.
#: rdkafka_performance's consumer fetches what a producer waiting on acknowledgements sent: twice.
#: The five of freeze 30 each cross it once (D33-5): a reply to a request (ycsb, nats-bench), or
#: a message delivered to the process that subtracts, stamped before it left a producer that
#: waits for nothing (omb, pulsar-perf, emqtt-bench).
CROSSINGS = {"kafka-end-to-end": 2, "rdkafka_performance": 2}


def slope_against_delay(staircase, tool):
    """How far a tool's reading moves per millisecond T1 adds, held to its crossings (D25-5).

    The median where the tool prints one, else the average. A slope under half the number of
    crossings, or over one and a half times it, is a staircase that did not measure the path --
    which is how k6 was found on 24 September: 0.000, because it had made no request at all.
    """
    figure = "p50" if any("p50" in (r.get("reported_ms") or {}) for _, r in staircase) else "avg"
    xy = [(added, (r.get("reported_ms") or {}).get(figure)) for added, r in staircase]
    xy = [(x, y) for x, y in xy if isinstance(y, (int, float))]
    crossings = CROSSINGS.get(tool, 1)
    found = {"figure": figure, "crossings": crossings, "slope": None, "measured_the_path": None}
    if len(xy) < 3 or len(set(x for x, _ in xy)) < 2:
        return found
    mx = sum(x for x, _ in xy) / len(xy)
    my = sum(y for _, y in xy) / len(xy)
    slope = sum((x - mx) * (y - my) for x, y in xy) / sum((x - mx) ** 2 for x, _ in xy)
    found["slope"] = slope
    found["measured_the_path"] = 0.5 * crossings <= slope <= 1.5 * crossings
    return found


def _staircase_from(folder, tool):
    """T1's runs for one tool, as (added_ms, reading) pairs, read off their folder names."""
    found = []
    for name in sorted(os.listdir(folder)):
        match = re.fullmatch(r"t1-%s-(\d+)_?(\d*)ms" % re.escape(tool), name)
        path = os.path.join(folder, name, "reading.json")
        if not match or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            found.append((float("%s.%s" % (match.group(1), match.group(2) or "0")), json.load(fh)))
    return found


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="What a tool says it measured, from its own output")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("read")
    p.add_argument("--tool", required=True, choices=sorted(READERS))
    p.add_argument("--file", required=True)
    p.add_argument("--out", default="")
    s = sub.add_parser("staircase")
    s.add_argument("--tool", required=True, choices=sorted(READERS))
    s.add_argument("--dir", required=True, help="the folder T1's runs were written under")
    s.add_argument("--out", default="")
    args = ap.parse_args(argv)

    if args.command == "staircase":
        steps = _staircase_from(args.dir, args.tool)
        found = step_seen(steps)
        found["slope"] = slope_against_delay(steps, args.tool)
        text = json.dumps(found, indent=2, sort_keys=True)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        print(text, file=out)
        return 0 if found["smallest_reported_ms"] is not None else 1

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
