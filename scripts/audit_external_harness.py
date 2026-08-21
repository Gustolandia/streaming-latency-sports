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
]

# A guard that admits only positive samples silently drops the evidence of a violation.
POSITIVE_FILTER = [
    re.compile(r"if\s*\(\s*(\w*[Ll]atency\w*)\s*>\s*0\s*\)"),
    re.compile(r"if\s*\(\s*(\w*[Ll]atency\w*)\s*>=\s*0\s*\)"),
    re.compile(r"if\s+(\w*latency\w*)\s*>\s*0\s*:", re.I),
    # Erlang spells the same guard without an `if`, as a short-circuit before the record call:
    # `E2ELatency > 0 andalso record(...)`. Added when auditing beyond the JVM found the
    # identical shape in a language whose syntax the original patterns could not see.
    re.compile(r"\b(\w*[Ll]atency\w*)\s*>\s*0\s+andalso\b"),
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
LIBRARY_REFUSAL = [
    # `if (value < 0 || h->highest_trackable_value < value)` -- refuse, and return the refusal.
    re.compile(r"if\s*\(\s*(\w+)\s*<\s*0\s*\|\|\s*[\w>.\[\]-]+(->|\.)\w+\s*<\s*\1\b"),
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
    # `latency = Double.NaN;` -- replaced by a non-number.
    re.compile(r"\w*latency\w*\s*=\s*[\w.]*NaN\b", re.I),
]

# Evidence that violations are counted rather than dropped -- what we argue should exist. The
# `sample` alternative and the underscore are here because the one production tool we found that
# does this properly names its metric `scheduler_discarded_samples`: the noun it counts is the
# sample, not the discard. A rule that could not recognise the best existing implementation of
# the practice it recommends would be a poor rule.
DISCARD_COUNTER = re.compile(
    r"(negative|invalid|dropped|discard|violation|inverted)\w*[\s_]*"
    r"(count|counter|sample|\+\+|\.inc)", re.I)

# The order matters only for reporting; a line may belong to more than one class.
CLASSES = (
    ("cross_process_latency", CROSS_PROCESS),
    ("positive_only_filter", POSITIVE_FILTER),
    ("silent_suppression", SUPPRESSION),
    ("library_refusal", LIBRARY_REFUSAL),
)

# The three ways a sample can vanish. `cross_process_latency` is not one of them -- it marks
# where the span is computed, not what happens to it.
DISPOSAL_KINDS = ("positive_only_filter", "silent_suppression", "library_refusal")


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
    if "positive_only_filter" in kinds and COUNTER_CONSEQUENT.search(line):
        kinds.remove("positive_only_filter")
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


if __name__ == "__main__":
    raise SystemExit(main())
