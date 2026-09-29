# GitHub (registered source 4): OMB result JSON files committed to the default
# branch of forks (GitHub forks and detached copies of the OMB code).
# One row per result file. The report is the repository (report_url); the file
# is named in `configuration`. Every quoted field is checked against the file.

import csv
import os
import re

R = "2026-09-28"
HERE = os.path.dirname(os.path.abspath(__file__))
FIELDS = ["50pct", "75pct", "95pct", "99pct", "999pct", "9999pct", "Max", "Avg"]
BRANCH = {"snxmlx/openmessaging-benchmark": "master", "Camjo-AB/degree-benchmark": "main",
          "confluentinc/openmessaging-benchmark": "master", "KaimingWan/openmessaging-benchmark": "main",
          "duyvu1109/omb": "main", "seolzero/benchmark-for-DT": "main"}
KIND = {"snxmlx/openmessaging-benchmark": "GitHub fork of openmessaging/benchmark",
        "Camjo-AB/degree-benchmark": "detached copy of the OMB code ('Degree project benchmarking Kafka and RabbitMQ on kubernetes')",
        "confluentinc/openmessaging-benchmark": "Confluent's detached fork; these are the files cited by the Confluent 2020 blog post",
        "KaimingWan/openmessaging-benchmark": "fork in the AutoMQ/openmessaging-benchmark network",
        "duyvu1109/omb": "detached copy of the OMB code",
        "seolzero/benchmark-for-DT": "detached copy of the OMB code with a custom driver"}


def frag(raw, key):
    m = re.search(r'"aggregatedEndToEndLatency%s"\s*:\s*(-?[0-9][0-9.eE+-]*)' % key, raw)
    return (m.group(0), m.group(1)) if m else ("", "")


REPORTS = []
_by = {}
for r in csv.DictReader(open(os.path.join(HERE, "gh", "results_parsed.tsv"), encoding="utf-8"), delimiter="\t"):
    _by.setdefault(r["repo"], []).append(r)

for repo, rows in _by.items():
    confs = []
    for r in sorted(rows, key=lambda x: x["path"]):
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", repo + "__" + r["path"])[:200]
        raw = open(os.path.join(HERE, "gh", "fork_scan", "files", safe), encoding="utf-8").read()
        f = {k: frag(raw, k) for k in FIELDS}
        for k in ("50pct", "99pct"):
            assert f[k][0] and f[k][0] in raw, (repo, r["path"], k)
        p50, p99 = f["50pct"][1], f["99pct"][1]
        other = "; ".join("%s %s" % (lab, f[k][1]) for lab, k in
                          (("p75", "75pct"), ("p95", "95pct"), ("p99.9", "999pct"), ("p99.99", "9999pct"), ("max", "Max"), ("avg", "Avg")) if f[k][1])
        is1 = p50 in ("1.0", "1", "1.00")
        flags = []
        if is1:
            flags.append("PRIMARY: printed aggregatedEndToEndLatency50pct exactly 1.0")
            if p99 in ("1.0", "1", "1.00"):
                flags.append("STRONG: p99 also 1.0")
        added = r["added"].split(" ")
        confs.append(dict(
            broker=r["driver"] or "(not named in file)",
            configuration="%s | file %s" % (r["workload"] or "(workload not named in file)", r["path"]),
            e2e_p50_ms=p50, e2e_p99_ms=p99, other=other,
            quote=f["50pct"][0] + " | " + f["99pct"][0],
            date=added[0][:10] if added and added[0] else "",
            notes="; ".join(flags + ["file https://github.com/%s/blob/%s/%s (added in commit %s)" % (repo, BRANCH[repo], r["path"], added[1] if len(added) > 1 else "?")])))
    dates = sorted(c["date"] for c in confs if c["date"])
    REPORTS.append(dict(
        id="ghjson_" + re.sub(r"[^a-z0-9]+", "_", repo.lower()),
        source="4 GitHub: %s (%s), committed OMB result JSON" % (repo, KIND[repo]),
        url="https://github.com/%s" % repo,
        date=dates[0] if dates and dates[0] == dates[-1] else ("%s..%s" % (dates[0], dates[-1]) if dates else ""),
        retrieved=R, tool="OMB (%s)" % repo, src=None, src_kind="json", included="yes",
        notes="Raw OMB result files with no prose (unforeseen case): inclusion criterion (a) read as met by the files' location in a named OMB fork/copy; values copied as printed in the JSON (aggregated fields).",
        configs=confs))
