# GitHub (registered source 4), NON-default branches of repositories in the
# OMB fork networks (branch_scan parts 1 and 2). One report per repository +
# branch; one row per result file (JSON) or per printed table row (markdown).
# Every quoted JSON field is asserted against the saved file.

import json
import os
import re
import subprocess

R = "2026-09-28"
HERE = os.path.dirname(os.path.abspath(__file__))
BS = os.path.join(HERE, "gh", "branch_scan")
CACHE = os.path.join(HERE, "gh", "branch_dates.json")
FIELDS = ["50pct", "75pct", "95pct", "99pct", "999pct", "9999pct", "Max", "Avg"]

_dates = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}


def dir_date(repo, branch, path):
    d = os.path.dirname(path) or "."
    key = "%s|%s|%s" % (repo, branch, d)
    if key not in _dates:
        q = "repos/%s/commits?sha=%s&per_page=1" % (repo, branch) + ("" if d == "." else "&path=%s" % d)
        p = subprocess.run(["gh", "api", q, "--jq", ".[0].commit.committer.date + \" \" + .[0].sha[0:7]"],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        _dates[key] = p.stdout.strip() if p.returncode == 0 else ""
        json.dump(_dates, open(CACHE, "w", encoding="utf-8"), indent=0)
    return _dates[key]


def frag(raw, key):
    m = re.search(r'"aggregatedEndToEndLatency%s"\s*:\s*(-?[0-9][0-9.eE+-]*)' % key, raw)
    return (m.group(0), m.group(1)) if m else ("", "")


def load_hits():
    out = []
    for part in ("hits_part1.tsv", "hits_part2.tsv"):
        p = os.path.join(BS, part)
        if os.path.exists(p):
            for line in open(p, encoding="utf-8").read().splitlines()[1:]:
                f = line.split("\t")
                if len(f) >= 4:
                    out.append(f[:5])
    return out


REPORTS = []
_by = {}
_text = []
for repo, branch, path, kind, *rest in load_hits():
    if kind == "json":
        _by.setdefault((repo, branch), []).append(path)
    elif kind == "text":
        _text.append((repo, branch, path, rest[0] if rest else ""))

for (repo, branch), paths in sorted(_by.items()):
    confs = []
    for path in sorted(paths):
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", repo + "__" + branch + "__" + path)[:220]
        raw = open(os.path.join(BS, "files", safe), encoding="utf-8").read()
        try:
            j = json.loads(raw)
        except Exception:  # noqa: BLE001
            j = {}
        f = {k: frag(raw, k) for k in FIELDS}
        if not f["50pct"][0]:
            continue  # per-window arrays only, no aggregated percentile printed
        assert f["50pct"][0] in raw and (not f["99pct"][0] or f["99pct"][0] in raw)
        win = j.get("endToEndLatency50pct") if isinstance(j, dict) else None
        wmed = sorted(x for x in win if isinstance(x, (int, float)))[len(win) // 2] if isinstance(win, list) and win else None
        micro = bool(wmed and float(f["50pct"][1]) / wmed > 200)
        p50, p99 = f["50pct"][1], f["99pct"][1]
        flags = []
        if p50 in ("1.0", "1", "1.00"):
            flags.append("PRIMARY: printed aggregatedEndToEndLatency50pct exactly 1.0")
        if micro:
            flags.append("aggregated end-to-end fields are in MICROSECONDS in this file (pre-August-2019 OMB bug fixed by PR #150; per-window endToEndLatency50pct median %s ms); printed value kept as printed" % wmed)
            if p50 in ("1000.0", "1000"):
                flags.append("PRIMARY (unit-corrected): 1000 microseconds = 1 ms")
        if p50 in ("0.0", "0"):
            flags.append("median printed as 0.0 (empty or all-zero end-to-end histogram)")
        dd = dir_date(repo, branch, path).split(" ")
        other = "; ".join("%s %s" % (lab, f[k][1]) for lab, k in (("p75", "75pct"), ("p95", "95pct"), ("p99.9", "999pct"), ("p99.99", "9999pct"), ("max", "Max"), ("avg", "Avg")) if f[k][1])
        confs.append(dict(
            broker=(j.get("driver") if isinstance(j, dict) else "") or "(not named in file)",
            configuration="%s | file %s" % ((j.get("workload") if isinstance(j, dict) else "") or "(workload not named)", path),
            e2e_p50_ms=p50, e2e_p99_ms=p99, other=other,
            quote=f["50pct"][0] + (" | " + f["99pct"][0] if f["99pct"][0] else ""),
            date=dd[0][:10] if dd and dd[0] else "",
            notes="; ".join(flags + ["file https://github.com/%s/blob/%s/%s (latest commit touching its directory on this branch: %s)" % (repo, branch, path, " ".join(dd))])))
    if not confs:
        continue
    dates = sorted(c["date"] for c in confs if c["date"])
    REPORTS.append(dict(
        id="ghbr_" + re.sub(r"[^a-z0-9]+", "_", (repo + "_" + branch).lower()),
        source="4 GitHub: %s, non-default branch '%s', committed OMB result JSON" % (repo, branch),
        url="https://github.com/%s/tree/%s" % (repo, branch),
        date=dates[0] if dates and dates[0] == dates[-1] else ("%s..%s" % (dates[0], dates[-1]) if dates else ""),
        retrieved=R, tool="OMB (%s)" % repo, src=None, src_kind="json", included="yes",
        notes="Raw OMB result files on a non-default branch (no prose; unforeseen case, see summary).",
        configs=confs))

# dao-jun/benchmark, branch dev/asp_perf: doc/performance_test.md tables
_dj = [t for t in _text if t[0] == "dao-jun/benchmark"]
if _dj:
    repo, branch, path, _ = _dj[0]
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", repo + "__" + branch + "__" + path)[:220]
    md = open(os.path.join(BS, "files", safe), encoding="utf-8").read()
    rate = parts = size = ""
    confs = []
    for line in md.splitlines():
        h = re.match(r"^#{3,5}\s*(.*)$", line)
        if h:
            t = h.group(1).strip()
            if t.lower().startswith("publish rate"):
                rate = t
            elif t.lower().startswith("topic partitions"):
                parts = t
            elif t.lower().startswith("payload size"):
                size = t
            continue
        if line.startswith("|") and not line.startswith("|--") and "AVG Publish Latency" not in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 13 and cells[0]:
                name = cells[0]
                allna = all(c.upper() == "N/A" for c in cells[7:12])
                confs.append(dict(broker=name, configuration="%s; %s; %s" % (rate, parts, size),
                                  included="no" if allna else "yes",
                                  reason="configuration printed without end-to-end values ('N/A')" if allna else "",
                                  e2e_p99_ms=cells[9], other="P95 %s; P999 %s; max %s; avg %s" % (cells[8], cells[10], cells[11], cells[7]),
                                  quote=line.strip(),
                                  notes="PRINTED E2E P99 OF EXACTLY 1.0 (median not printed)" if cells[9] in ("1.0", "1") else ""))
    dd = dir_date(repo, branch, path).split(" ")
    REPORTS.append(dict(
        id="ghbr_daojun_perfdoc", source="4 GitHub: dao-jun/benchmark (fork via ascentstream/benchmark), branch 'dev/asp_perf', repository text",
        url="https://github.com/dao-jun/benchmark/blob/dev/asp_perf/doc/performance_test.md", date=dd[0][:10] if dd and dd[0] else "", retrieved=R,
        tool="OMB (fork)", src=os.path.relpath(os.path.join(BS, "files", safe), HERE), included="yes",
        notes="Chinese test plan with results tables for Pulsar, KoP (Kafka-on-Pulsar) and Kafka; end-to-end columns are AVG, P95, P99, P999, Max (no median).",
        configs=confs))

_TEXT_REASON = {
    "laserdata/openmessaging-benchmark": "driver README describing how end-to-end latency is computed; no results",
    "s2-streamstore/ombench": "driver README describing timestamps; no results",
    "Denovo1998/benchmark": "design document (Chinese) listing planned metrics; no values",
    "ankitk-me/openmessaging-benchmark": "README describing chart generation; no results",
    "kevinhan88/openmessaging-benchmark": "analysis notebooks without saved outputs; no values printed",
    "oleiman/openmessaging-benchmark": "CLAUDE.md describing the code (HdrHistogram recording); no results",
    "Vanlightly/openmessaging-benchmark-custom": "chart README (axis ranges); no results",
}
_seen = set()
for repo, branch, path, detail in _text:
    if repo == "dao-jun/benchmark" or (repo, branch) in _seen:
        continue
    _seen.add((repo, branch))
    REPORTS.append(dict(
        id="ghbr_text_" + re.sub(r"[^a-z0-9]+", "_", (repo + "_" + branch).lower()),
        source="4 GitHub: %s, non-default branch '%s', repository text" % (repo, branch),
        url="https://github.com/%s/blob/%s/%s" % (repo, branch, path), date="(repository)", retrieved=R,
        tool="OMB fork", src="", included="no", reason=_TEXT_REASON.get(repo, "no end-to-end result values printed"),
        configs=[dict(configuration="-")]))
