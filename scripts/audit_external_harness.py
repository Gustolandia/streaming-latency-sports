#!/usr/bin/env python3
"""
audit_external_harness.py
Apply this paper's consistency argument to a benchmark harness we did not write.

A referee's decisive objection to an earlier draft was that our evidence came entirely from our
own broken corpus: we had shown that *we* made a mistake, not that the field is exposed to it.
This script answers that by auditing a third-party harness's SOURCE for the two properties that
decide whether the failure can occur and whether anyone would notice:

  1. Does it compute a latency as a difference of timestamps taken in different processes (or on
     different hosts)? If so it can violate causality, exactly as ours did.
  2. What does it do with a non-positive sample? Discarding one silently is worse than recording
     it, because the resulting distribution is conditioned on being positive and the reader
     cannot see the retention rate. Our paper argues the rate should be published the way a
     survey publishes its response rate.

The audit is deliberately source-level and evidence-first: every finding carries the file, the
line number and the line itself, so a reader can check it against the upstream commit rather
than take our word for it. It does not require running the harness, which is the point -- a
design property visible in the source is not contingent on our being able to reproduce someone
else's deployment.

CLI:
    python scripts/audit_external_harness.py --repo ~/omb --name "OpenMessaging Benchmark" \
        --out docs/results/external
"""
import argparse
import csv
import os
import re
import subprocess
from pathlib import Path

# A cross-process latency is a subtraction where one side is a local clock read and the other
# arrives with the message. These patterns catch the common Java/Python spellings.
CROSS_PROCESS = [
    re.compile(r"(now|receiveTime|recvTime)\s*-\s*(publish|send|produce|create)\w*", re.I),
    re.compile(r"currentTimeMillis\(\)\s*-\s*\w*(timestamp|time)", re.I),
    re.compile(r"nanoTime\(\)\s*-\s*\w*(timestamp|time)", re.I),
    re.compile(r"time\.time\(\)\s*-\s*\w*(timestamp|publish)", re.I),
    # Erlang/Elixir: `os:system_time(millisecond) - TS`, a wall-clock read minus a stamp that
    # arrived with the message. The unit is an argument here rather than part of the method
    # name, which is why the JVM patterns above cannot see it.
    re.compile(r"system_time\s*\(\s*\w*\s*\)\s*-\s*\w+", re.I),
    # Pulsar: `System.currentTimeMillis() - msg.publishTime().toEpochMilli()` -- the stamp
    # arrives as a method chain on the message rather than as a field, which the second
    # pattern's `\w*` cannot cross. Added in round 6 with the harness itself.
    re.compile(r"currentTimeMillis\(\)\s*-\s*\w+\.(publish|send|create)\w*\(", re.I),
    # Go: `time.Now().UnixNano() - sendTime`, where sendTime was decoded from the payload.
    # NATS spells the cross-process subtraction inline with no intervening field access.
    re.compile(r"Now\(\)\.Unix(Nano|Milli)\(\)\s*-\s*\w*(send|pub|start)\w*", re.I),
    # C: librdkafka's `ts = wall_clock() - remote_ts;`, the consumer's own clock call minus the
    # stamp that arrived in the payload. `remote` is how that tool names the arriving stamp; its
    # producer's `wall_clock() - source_ts` subtracts a stamp it took itself, in one process,
    # and must not match. Added on 11 Oct 2026 with the tool.
    re.compile(r"\b\w*clock\(\)\s*-\s*\w*remote\w*"),
    # PerfKit Benchmarker's messaging benchmark subtracts a publisher process's time.time_ns() from
    # a receiver process's, by name: `receive_timestamp - published_timestamp`. Added 11 Oct 2026.
    re.compile(r"\breceive\w*\s*-\s*publish\w*"),
    # Clojure, prefix and parenthesised: the Yahoo Streaming Benchmark's
    # `(- (Long/parseLong time_updated) (Long/parseLong window-time))`, a processor's wall clock
    # minus a time that came from the generator's. Added 11 Oct 2026.
    re.compile(r"\(-\s+\(\S+\s+[\w-]*time[\w-]*\)\s+\(\S+\s+[\w-]*time[\w-]*\)\)"),
    # The subtraction can also be behind an abstraction, which is the harder case to see and
    # the reason this list is patterns rather than a grep for a minus sign. RabbitMQ
    # PerfTest's `timestampProvider.getDifference(now, messageTimestamp)` is a cross-process
    # span with no operator in the line at all; what marks it is that one argument is the
    # local clock and the other arrived with the message.
    re.compile(r"get(Difference|Elapsed)\s*\(\s*\w*now\w*\s*,\s*\w*(message|publish|send)\w*",
               re.I),
    # Go, with the clock read held in a variable and the stamp a field of the decoded message:
    # Redpanda kgo-repeater's `e2e_latency := now.UnixMicro() - message.SentAt`. Added 11 Oct 2026
    # with the second October reading (data/tools_audit/batch_11.json), as are those below.
    re.compile(r"\bnow\.Unix(Micro|Milli|Nano)\(\)\s*-\s*\w+\.\w*(sent|send|pub)\w*", re.I),
    # Java, the stamp read off the message by a getter: RocketMQ's benchmark consumer,
    # `long born2ConsumerRT = now - msg.getBornTimestamp();`, the producer's clock in the born
    # timestamp and the broker's in the store timestamp.
    re.compile(r"\bnow\s*-\s*\w+\.get(Born|Store|Send|Publish)\w*Timestamp\s*\(", re.I),
    # Artemis's `artemis perf`: `final long elapsedUs = receivedOn - start;`, where `start` was
    # read from the message's `time` property, which the producer set.
    re.compile(r"\breceived?On\s*-\s*start\b"),
    # Python with numpy, column by column: Quiver's
    # `latencies = transfers["receive_time"] - transfers["send_time"]`.
    re.compile(r"\[\s*\"receive_time\"\s*\]\s*-\s*\w+\[\s*\"send_time\"\s*\]"),
]

# Two guards, not one, and the difference is the difference between this paper's two failure
# modes. Round 69.
#
# `> 0` admits only STRICTLY positive samples, so on a path shorter than the timestamp
# quantum it deletes every sample that computes to exactly zero -- which is most of them.
# That is the deletion failure.
#
# `>= 0` admits zero. It deletes only genuinely inverted samples, and the computes-to-zero
# population survives into the output where an operator can see it pile up on the quantum.
# That is the other failure, and it is the one the sign channel is for: "negative means the
# reference timestamp failed, computes-to-zero means the resolution failed, and one unsigned
# total conflates them."
#
# Both were in one list under a comment that said "admits only positive samples", and the
# registry called Apache Pulsar's `if (latencyMillis >= 0)` a positivity guard on that basis.
# It is a non-negativity guard. The mislabel came in with round 6, which introduced Pulsar
# while correctly fixing a different misreading, and it survived because nothing separated
# the operators. A classifier for a paper about the difference between a measured zero and an
# uncounted absence has to be able to tell `>` from `>=`.
POSITIVE_FILTER = [
    re.compile(r"if\s*\(\s*(\w*[Ll]atency\w*)\s*>\s*0\s*\)"),
    re.compile(r"if\s+(\w*latency\w*)\s*>\s*0\s*:", re.I),
    # Erlang spells the same guard without an `if`, as a short-circuit before the record call:
    # `E2ELatency > 0 andalso record(...)`. Added when auditing beyond the JVM found the
    # identical shape in a language whose syntax the original patterns could not see.
    re.compile(r"\b(\w*[Ll]atency\w*)\s*>\s*0\s+andalso\b"),
    # C, with an upper bound on the same value: librdkafka's
    # `if (ts > 0 && ts < (1000000 * 60 * 5)) {` keeps a latency only above zero and under five
    # minutes. The strict `> 0` on the value about to be recorded is the filter; the bound drops
    # stale stamps. The same name on both sides of the `&&` is what makes it a range on one
    # value rather than two unrelated tests. Added on 11 Oct 2026 with the tool.
    re.compile(r"if\s*\(\s*(\w+)\s*>\s*0\s*&&\s*\1\s*<"),
    # An array of latencies read element by element: BookKeeper's benchmark,
    # `if (bench.latencies[i] > 0) {`, where 0 also marks an add that never completed, so a
    # latency of zero is dropped with the failures. Added 11 Oct 2026 (batch 11).
    re.compile(r"if\s*\(\s*[\w.]*latenc\w*\s*\[\s*\w+\s*\]\s*>\s*0\s*\)"),
]

#: The weaker guard: drops inversions, keeps the quantum's zeros.
NONNEGATIVE_FILTER = [
    re.compile(r"if\s*\(\s*(\w*[Ll]atency\w*)\s*>=\s*0\s*\)"),
    re.compile(r"if\s+(\w*latency\w*)\s*>=\s*0\s*:", re.I),
    re.compile(r"\b(\w*[Ll]atency\w*)\s*>=\s*0\s+andalso\b"),
    # A list kept only where the value reaches what is then subtracted from it, so nothing below
    # zero survives and a zero does: the Yahoo Streaming Benchmark's analysis notebook,
    # `[x - window_size_ms for x in update_times if x >= window_size_ms]`. Added 11 Oct 2026.
    re.compile(r"\[\s*(\w+)\s*-\s*(\w+)\s+for\s+\1\s+in\s+\w+\s+if\s+\1\s*>=\s*\2\s*\]"),
    # A parser that cannot read a minus sign drops a negative duration as surely as a test does:
    # the log reader Strimzi Canary ships matches `duration=([0-9]+)`. A zero still parses.
    # Added 11 Oct 2026.
    re.compile(r"(duration|latency)\w*=\(\[0-9\]\+\)", re.I),
]

# A positivity guard only deletes a sample if what it guards is the *sample*. Round 6 caught us
# on exactly this: emqtt-bench's `E2ELatency > 0 andalso inc_counter(...)` gates a Prometheus
# counter, and the very next line observes the histogram unconditionally, so nothing is dropped
# at all. The pattern above saw the guard and could not see its consequent, and we reported a
# tool as deleting samples when it keeps every one of them.
#
# The distinction is mechanical, so it belongs here rather than in a reviewer's eye: if the
# guarded action increments a counter, the guard is bookkeeping, not disposal.
COUNTER_CONSEQUENT = re.compile(
    r"(andalso|\)\s*\{?)\s*\w*(inc|add|bump)[_\w]*counter\w*\s*\(", re.I)

# A fourth response, weaker to spot than the other three because the deletion is not in the
# harness at all. The recording library refuses the value and says so in a return code; the
# caller ignores it. wrk2 is the specimen: it tests for the negative, prints a panic block
# asserting it can never happen, and then calls `hdr_record_value` anyway, where
# HdrHistogram_c's `if (value < 0 ...) return false;` drops it with nothing counted anywhere.
# Neither file is wrong on its own, which is why this needs its own class.
# The signature is a range check against a bound the object carries: the value is rejected both
# for being negative and for exceeding what this histogram was configured to hold, which is what
# a library does and an application does not. Requiring the second disjunct to be a member
# access is what separates this from fio's `if (sec < 0 || (sec == 0 && nsec < 0))`, which is a
# sign test on two time fields and belongs to SUPPRESSION. A first draft without that
# requirement classified fio as both, which is how this comment came to be written.
#
# Round 7 corrected which file this class points at for wrk2. Upstream HdrHistogram_c refuses
# the *value* (`if (value < 0 || h->highest_trackable_value < value)`); wrk2 does not build
# against upstream -- it vendors its own hdr_histogram.c, which refuses the *derived index*
# (`if (counts_index < 0 || h->counts_len <= counts_index) return false;`, lines 219 and 234),
# and whose index computation carries assert()s that are live in the shipped build (-O2, no
# -DNDEBUG). Both spellings are the same disposal -- a bool the caller never checks -- so both
# match here; the build-dependent abort is recorded in the registry note, not inferred by a
# pattern.
LIBRARY_REFUSAL = [
    # `if (value < 0 || h->highest_trackable_value < value)` -- refuse the value...
    # `if (counts_index < 0 || h->counts_len <= counts_index)` -- ...or the index it maps to.
    re.compile(r"if\s*\(\s*(\w+)\s*<\s*0\s*\|\|\s*[\w>.\[\]-]+(->|\.)\w+\s*<=?\s*\1\b"),
    # `if uint(idx) >= uint(len(h.counts)) {` -- the Go library's one unsigned comparison, in
    # which a negative index wraps to a huge one and is refused with the out-of-range values.
    # hdrhistogram-go maps a negative latency to such an index; the NATS CLI records into it
    # and ignores the error, so its percentile table leaves the negative out. Our first
    # reading of the NATS CLI stopped at the append into its slice and missed this; the
    # documentation audit (T5) read the histogram, and the finding reached this list on
    # 2 Oct 2026.
    re.compile(r"if\s+uint\(\s*\w+\s*\)\s*>=\s*uint\(\s*len\("),
    # A recorder that throws on a negative: Kafka Trogdor's own histogram,
    # `throw new RuntimeException("invalid negative value.");`. ProduceBench catches it inside the
    # send callback and only logs it, so the sample is lost. Added 11 Oct 2026.
    re.compile(r"throw\s+new\s+\w*Exception\s*\(\s*\"[^\"]*negative", re.I),
    # An array indexed by the latency itself: the Pravega benchmark's `latencies[latency]++;`.
    # The JVM refuses a negative index with an exception that ends the thread keeping the
    # statistics, so every later value is lost too, and nothing says why until shutdown. The
    # store is the tool's own array rather than a library's, and the response is the same: the
    # place the value is recorded refuses it and the tool never checks. Added 11 Oct 2026.
    re.compile(r"\b\w*latencies\s*\[\s*\w*latency\w*\s*\]\s*\+\+"),
]

# A third response, and the one that hides the failure most completely: detect the inversion and
# substitute a value for it. Nothing is filtered, so a retention rate computed from the output
# would read 100%; the sample survives into the distribution carrying a number that was never
# measured. This class exists because auditing beyond our own corpus turned it up repeatedly --
# fio substitutes zero, btt substitutes one nanosecond, KIP-489 substitutes NaN, .NET clamped to
# zero -- always as a repair applied to a symptom, never with the cause named. A filter at least
# leaves a hole a careful reader can find; a substitution leaves nothing at all.
SUPPRESSION = [
    # `return (from < to) ? (to - from) : 1;` -- a constant stands in for the inverted span.
    re.compile(r"\?\s*\(?\s*\w+\s*-\s*\w+\s*\)?\s*:\s*[-\d.]+\s*;"),
    # `if (sec < 0 || (sec == 0 && nsec < 0))` -- a sign test guarding a substitution.
    re.compile(r"if\s*\(.*\b\w*(sec|nsec|usec|msec|delta|elapsed|latency)\w*\s*<\s*0\b.*\)", re.I),
    # `Math.max(0, now - publishTimestamp)` -- clamped at the floor, silently.
    re.compile(r"(Math\.)?max\s*\(\s*0[LlFfDd]?\s*,\s*[^)]*-\s*\w*(time|stamp|latency)\w*", re.I),
    # The same floor with the latency first and something else subtracted from it: Kafka
    # Trogdor's `Long.max(0L, (latency - histogramMinMs) / histogramStepMs)`. Added 11 Oct 2026.
    re.compile(r"max\s*\(\s*0[LlFfDd]?\s*,\s*\(?\s*\w*(time|stamp|latency)\w*\s*-", re.I),
    # A value below a recorder's floor pinned to it: kafka-clients' Percentiles,
    # `boundedValue = min;`, which Xinfra Monitor records into. A tracker of the minimum assigns
    # the other way round, `min = value`, and does not match. Added 11 Oct 2026.
    re.compile(r"\b\w*[Vv]alue\w*\s*=\s*min\s*;"),
    # `latency = Double.NaN;` -- replaced by a non-number.
    re.compile(r"\w*latency\w*\s*=\s*[\w.]*NaN\b", re.I),
    # `return Math.abs(ts1 - ts2);` -- the sign thrown away, so a negative span enters the
    # distribution as a positive one of the same size. RabbitMQ PerfTest's getDifference does
    # this. Our first reading of PerfTest stopped at the call site in Consumer.java, saw the
    # difference handed on with no sign test, and filed the tool as one that passes negatives
    # on; the documentation audit (T5) read the method itself and recorded the prediction as
    # failed, and that finding did not reach this classifier until 2 Oct 2026.
    re.compile(r"\b(Math\.)?abs\s*\(\s*\w+\s*-\s*\w+\s*\)"),
    # A bucket index floored at the first bucket: the Google Cloud Pub/Sub load test framework's
    # Java client, `int bucket = Math.max((int) Math.floor(raw_bucket), 0);`, where `raw_bucket`
    # is the latency's logarithm, so a zero (minus infinity) and a negative (not a number) both
    # land in the bucket of the fastest messages. Added 11 Oct 2026 (batch 11).
    re.compile(r"max\s*\(\s*\(int\)\s*(Math\.)?floor\s*\(\s*\w*bucket\w*\s*\)\s*,\s*0\s*\)"),
    # Times held unsigned, so a negative difference wraps to 2^64 less its size: Quiver's
    # `dtype = [("send_time", _numpy.uint64), ("receive_time", _numpy.uint64)]`, from which a
    # value below zero enters its average and its top percentiles as some 1.8e19 ms.
    re.compile(r"\"\w*(send|receive)_time\"\s*,\s*[\w.]*uint64\b"),
]

# Evidence that violations are counted rather than dropped -- what we argue should exist. The
# `sample` alternative and the underscore are here because the one production tool we found that
# does this properly names its metric `scheduler_discarded_samples`: the noun it counts is the
# sample, not the discard. A rule that could not recognise the best existing implementation of
# the practice it recommends would be a poor rule.
DISCARD_COUNTER = re.compile(
    r"(negative|invalid|dropped|discard|violation|inverted)\w*[\s_]*"
    r"(count|counter|sample|\+\+|\+=|\.inc)", re.I)
# `+=` since 11 Oct 2026: SBK counts each value below zero it keeps out of its figures,
# `this.invalidLatencyRecords += events;`, and prints the count in every report.

# The value is RETAINED at a coarser resolution than the clock that produced it.
#
# This class exists because the audit of round 56 found the failure without the guard. Mode B
# was framed as deletion -- a positivity filter dropping a quantized difference -- and that
# framing could not see Apache Kafka's own bundled `EndToEndLatency`, which takes a monotonic
# nanosecond clock, prints every sample at full precision, and then stores the percentile
# array with `elapsed / 1000 / 1000` in Java integer arithmetic. Nothing is filtered and
# nothing is dropped; on a sub-millisecond path every percentile it reports is nevertheless
# zero. Deletion is one way a quantum destroys a measurement, not the only one, and a registry
# whose only categories are ways a sample can *vanish* is blind to the one where it stays and
# reads zero.
#
# The signature is a division or cast that discards a fraction of the unit the value was
# measured in: integer division by a thousand or a million, a cast to int on a nanosecond or
# microsecond quantity, or a widening conversion applied to an already-quantized difference --
# which is the OpenMessaging line, `MILLISECONDS.toMicros(now - publishTimestamp)`, where the
# microseconds are decoration on a millisecond subtraction.
QUANTIZED_RETENTION = [
    re.compile(r"=\s*\w*(elapsed|latency|duration|delta|diff)\w*\s*/\s*1000\s*/\s*1000\b", re.I),
    re.compile(r"=\s*\(\s*int\s*\)\s*\(\s*\w*(now|end)\w*\s*-\s*\w*(start|begin)\w*\s*\)", re.I),
    re.compile(r"(MILLISECONDS|SECONDS)\.to(Micros|Nanos)\s*\(\s*\w+\s*-\s*\w+", re.I),
    # Python's floor division of nanoseconds to milliseconds, PerfKit Benchmarker's
    # `return ns // 1_000_000`: the fraction goes, and a negative is floored away from zero.
    # Added 11 Oct 2026.
    re.compile(r"\b\w+\s*//\s*1_?000_?000\b"),
    # Go's integer division of a Duration by a unit: Sarama's
    # `requestLatencyInMs := int64(requestLatency / time.Millisecond)`, so every request under a
    # millisecond is recorded as 0. Added 11 Oct 2026 (batch 11).
    re.compile(r"\(\s*\w*(latency|elapsed|duration)\w*\s*/\s*time\.Millisecond\s*\)", re.I),
]

# The order matters only for reporting; a line may belong to more than one class.
CLASSES = (
    ("cross_process_latency", CROSS_PROCESS),
    ("positive_only_filter", POSITIVE_FILTER),
    ("nonnegative_filter", NONNEGATIVE_FILTER),
    ("silent_suppression", SUPPRESSION),
    ("library_refusal", LIBRARY_REFUSAL),
    ("quantized_retention", QUANTIZED_RETENTION),
)

# The ways a sample can vanish. `cross_process_latency` is not one of them -- it marks where
# the span is computed, not what happens to it.
#
# `nonnegative_filter` joins the disposals and does not change the count of harnesses that
# dispose, because a tool guarding with `>= 0` still drops its inversions and still counts
# nothing. What changes is what may be said about it: it is a different threshold with a
# different consequence, not the same design under another name.
DISPOSAL_KINDS = ("positive_only_filter", "nonnegative_filter", "silent_suppression",
                  "library_refusal")

#: Kind -> what actually happens to the sample. Two kinds, one response: a filter is a filter
#: whichever way its comparison leans, and Section VII enumerates three responses because
#: there are three -- drop it, replace it, let the library refuse it. Splitting the threshold
#: in round 69 must not turn "three classes" into "four" in the prose, because the reader is
#: being told what becomes of the value and nothing about that changed. The threshold decides
#: WHICH samples are dropped, which is a separate fact and is now in the table.
DISPOSAL_RESPONSES = {
    "positive_only_filter": "filter",
    "nonnegative_filter": "filter",
    "silent_suppression": "substitute",
    "library_refusal": "refuse",
}


def guards_a_tally(line):
    """A sign guard whose consequent is a counter increment.

    classify() withdraws the filter label from such a line, rightly for the sample: it is not
    deleted, and in emqtt-bench every one still reaches the histogram (round 6). What the guard
    does delete is the value from the tally it guards, and that tally can be the one a tool
    prints its figure from -- emqtt-bench's printed average divides that guarded sum by every
    message, so a value at or below zero enters the average as zero. Said separately, so that
    a tool can be counted as cutting the value from what it reports without being called one
    that deletes the sample (11 Oct 2026).
    """
    return (any(p.search(line) for p in POSITIVE_FILTER + NONNEGATIVE_FILTER)
            and bool(COUNTER_CONSEQUENT.search(line)))


def classify(line):
    """Every class a single source line belongs to.

    Split out of scan() so that a committed evidence line can be re-classified later by exactly
    the code that classified it in the first place. A registry of findings that merely *asserts*
    its labels is worth no more than the prose it replaces; one whose labels are recomputed from
    the evidence line on every test run can be checked by a reader who has neither the checkouts
    nor our word for it.

    A positivity guard is withdrawn when its consequent is a counter increment: guarding a
    counter is bookkeeping, and calling it disposal is the error round 6 found in our reading of
    emqtt-bench.
    """
    kinds = [name for name, pats in CLASSES if any(p.search(line) for p in pats)]
    for guard in ("positive_only_filter", "nonnegative_filter"):
        if guard in kinds and COUNTER_CONSEQUENT.search(line):
            kinds.remove(guard)
    return kinds


def source_files(repo, exts=(".java", ".py", ".scala", ".go", ".c", ".h", ".cc", ".cpp",
                             ".erl", ".cs", ".rs", ".js", ".ts")):
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in {".git", "target", "build", "node_modules"}]
        for f in files:
            if f.endswith(exts):
                yield os.path.join(root, f)


def scan(repo):
    """Every cross-process subtraction and every positive-only filter, with evidence."""
    findings = []
    for path in source_files(repo):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        rel = os.path.relpath(path, repo)
        for i, line in enumerate(lines, start=1):
            for kind in classify(line):
                findings.append({"kind": kind, "file": rel,
                                 "line": i, "evidence": line.strip()})
    return findings


def has_discard_counter(repo):
    for path in source_files(repo):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                if DISCARD_COUNTER.search(fh.read()):
                    return True
        except OSError:
            continue
    return False


def provenance(repo):
    def git(*args):
        try:
            return subprocess.run(["git", "-C", repo, *args], capture_output=True,
                                  text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return {"commit": git("rev-parse", "HEAD"),
            "date": git("log", "-1", "--format=%ci"),
            "upstream": git("remote", "get-url", "origin")}


def verdict(findings, counted):
    """Exposed? And if exposed, would anyone be able to tell?"""
    cross = [f for f in findings if f["kind"] == "cross_process_latency"]
    filt = [f for f in findings if f["kind"] == "positive_only_filter"]
    supp = [f for f in findings if f["kind"] == "silent_suppression"]
    if not cross:
        return ("NOT EXPOSED",
                "no cross-process latency subtraction found; a same-process span cannot "
                "violate causality and needs no check")
    if supp and not counted:
        return ("EXPOSED, AND REPAIRED",
                f"{len(cross)} cross-process subtraction(s) and {len(supp)} substitution(s) "
                f"that replace an inverted span with a constant, with no counter: this is worse "
                f"than filtering, because nothing is missing from the output. Retention computed "
                f"downstream reads 100% and the substituted value enters the distribution as "
                f"though it had been measured")
    if filt and not counted:
        return ("EXPOSED, AND SILENT",
                f"{len(cross)} cross-process subtraction(s) and {len(filt)} positive-only "
                f"filter(s), with no counter for the discarded samples: a violation is dropped "
                f"before it reaches the output, so the reported distribution is conditioned on "
                f"being positive and the retention rate is invisible")
    if filt and counted:
        return ("EXPOSED, BUT COUNTED",
                "non-positive samples are filtered, but the harness counts them, so a reader "
                "can see the retention rate")
    return ("EXPOSED, NOT FILTERED",
            f"{len(cross)} cross-process subtraction(s) and no positive-only filter: violations "
            f"would reach the output where they are at least visible")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit a third-party harness for the failure mode")
    ap.add_argument("--repo", required=True, help="path to a checked-out harness")
    ap.add_argument("--name", default=None, help="human name for the harness")
    ap.add_argument("--out", default="docs/results/external")
    args = ap.parse_args(argv)

    repo = os.path.expanduser(args.repo)
    if not os.path.isdir(repo):
        print(f"missing repository: {repo}")
        return 1
    name = args.name or os.path.basename(repo.rstrip("/"))

    findings = scan(repo)
    counted = has_discard_counter(repo)
    tag, why = verdict(findings, counted)
    prov = provenance(repo)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "harness_audit.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["harness", "kind", "file", "line", "evidence"])
        w.writeheader()
        for f in findings:
            w.writerow({"harness": name, **f})

    print(f"== {name} ==")
    if prov.get("commit"):
        print(f"  upstream {prov['upstream']}")
        print(f"  commit   {prov['commit']}  ({prov['date']})")
    for kind, _ in CLASSES:
        hits = [f for f in findings if f["kind"] == kind]
        print(f"  {kind}: {len(hits)}")
        for f in hits[:4]:
            print(f"    {f['file']}:{f['line']}  {f['evidence'][:88]}")
    print(f"  counts discarded samples: {counted}")
    print(f"\n== VERDICT: {tag} ==\n  {why}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
