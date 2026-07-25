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
]

# A guard that admits only positive samples silently drops the evidence of a violation.
POSITIVE_FILTER = [
    re.compile(r"if\s*\(\s*(\w*[Ll]atency\w*)\s*>\s*0\s*\)"),
    re.compile(r"if\s*\(\s*(\w*[Ll]atency\w*)\s*>=\s*0\s*\)"),
    re.compile(r"if\s+(\w*latency\w*)\s*>\s*0\s*:", re.I),
]

# Evidence that violations are counted rather than dropped -- what we argue should exist.
DISCARD_COUNTER = re.compile(
    r"(negative|invalid|dropped|discard|violation|inverted)\w*\s*(count|counter|\+\+|\.inc)", re.I)


def source_files(repo, exts=(".java", ".py", ".scala", ".go")):
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
            for pat in CROSS_PROCESS:
                if pat.search(line):
                    findings.append({"kind": "cross_process_latency", "file": rel,
                                     "line": i, "evidence": line.strip()})
                    break
            for pat in POSITIVE_FILTER:
                if pat.search(line):
                    findings.append({"kind": "positive_only_filter", "file": rel,
                                     "line": i, "evidence": line.strip()})
                    break
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
    if not cross:
        return ("NOT EXPOSED",
                "no cross-process latency subtraction found; a same-process span cannot "
                "violate causality and needs no check")
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
    for kind in ("cross_process_latency", "positive_only_filter"):
        hits = [f for f in findings if f["kind"] == kind]
        print(f"  {kind}: {len(hits)}")
        for f in hits[:4]:
            print(f"    {f['file']}:{f['line']}  {f['evidence'][:88]}")
    print(f"  counts discarded samples: {counted}")
    print(f"\n== VERDICT: {tag} ==\n  {why}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
