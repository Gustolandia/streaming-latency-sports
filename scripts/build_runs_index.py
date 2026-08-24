#!/usr/bin/env python3
"""
build_runs_index.py
One tracked row per run, so the raw per-event CSVs can be deleted without losing the record.

`runs/` holds 8.4 GB across ~1,700 directories and **not one file of it is tracked**. The
aggregated CSVs under docs/results cover 1,546 run ids between them, scattered over 57 files, and
1,445 runs on disk appear in none of them. So today the honest answer to "what runs produced this
paper" is a directory on one laptop, which is exactly the provenance gap Section 7.4 of the paper
reports having found in its own history.

This writes `reproducibility/runs_index.csv`: for every run directory, what it was, when, what it
measured, and -- the part that cannot be recovered later -- **its clock-integrity verdict,
recomputed from the raw timestamps while they still exist**. The audit that rejects 1,321 of
2,266 runs is computed from those CSVs. Delete them without extracting this first and the paper's
central claim becomes uncheckable.

Each row carries:

  identity     run_id, campaign, backend, config, feeds, speedup, plan
  provenance   git head, and whether meta.json recorded per-file code hashes
  size         events produced, consumed, matched
  measurement  median transport (ms), median TTI (ms) where available
  integrity    negative-transport count and fraction, and the verdict under the >1% rule
               applied to TRANSPORT ONLY. The paper's audit also tests scheduling lag and
               output, so its counts are larger and are not comparable to this column
  usage        whether any tracked aggregate CSV names this run, so an unused run is visibly
               unused rather than silently absent

CLI:
    python scripts/build_runs_index.py                       # full pass, reads every run
    python scripts/build_runs_index.py --fast                # skip the raw-CSV integrity pass
    python scripts/build_runs_index.py --runs runs --out reproducibility/runs_index.csv
"""
import argparse
import csv
import glob
import gzip
import json
import os
import re
import statistics as st
import sys

# The paper's rule, restated here because this file may outlive the analysis scripts.
NEG_FRACTION_LIMIT = 0.01

FIELDS = [
    "run_id", "campaign", "started", "backend", "config", "feeds", "speedup", "plan",
    "host", "git_head", "n_code_files",
    "n_produced", "n_consumed", "n_matched",
    "transport_median_ms", "tti_median_ms",
    "n_negative_transport", "frac_negative_transport", "transport_integrity",
    "used_by",
]

TS = re.compile(r"(\d{8})_(\d{6})")


def campaign_of(run_id):
    """Which family a run belongs to, from its id. Best effort, and honest when it cannot tell."""
    rid = run_id.lower()
    for key, name in (("concurrency", "concurrency"), ("batch9p", "s2sf12-acks"),
                      ("batch9", "s2-batch"), ("s4", "s4-sweep"), ("s3c", "s3-corrected"),
                      ("s3", "s3"), ("test", "test"), ("ack", "ack-probe")):
        if rid.startswith(key):
            return name
    return "unknown"


FEEDS = re.compile(r"_n(\d+)_")
TOPOLOGY = re.compile(r"_(single|cluster)_")


def feeds_of(run_id, meta):
    """Feed count. meta.json has no field for it; the run id and the topic both encode it."""
    for source in (run_id or "", str((meta.get("topic") or ""))):
        m = FEEDS.search(source) or re.search(r"-n(\d+)-", source)
        if m:
            return m.group(1)
    return ""


def topology_of(run_id, meta):
    """single vs cluster. Named in the run id for the S-era runs; inferred otherwise."""
    m = TOPOLOGY.search(run_id or "")
    if m:
        return m.group(1)
    if meta.get("redis"):
        return "redis-single" if str(meta["redis"].get("port", "")) == "16379" else "redis"
    if meta.get("bootstrap"):
        return "kafka-single" if "19092" in str(meta["bootstrap"]) else "kafka"
    return ""


def started_of(run_id, meta):
    m = TS.search(run_id or "")
    if m:
        d, t = m.groups()
        return f"{d[:4]}-{d[4:6]}-{d[6:]}T{t[:2]}:{t[2:4]}:{t[4:]}Z"
    return str(meta.get("started") or meta.get("timestamp") or "")


def _read_meta(run_dir):
    try:
        # utf-8-sig: some meta.json files carry a BOM, and plain utf-8 raises on them --
        # which this function would swallow, silently emptying the row.
        with open(os.path.join(run_dir, "meta.json"), encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _read_tti(run_dir):
    try:
        with open(os.path.join(run_dir, "tti_summary.json"), encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def transport_and_integrity(run_dir):
    """Median transport and the negative-transport count, from the raw per-event CSVs.

    This is the whole reason the script exists: once producer.csv and consumer_events.csv are
    gone, no later pass can recover these numbers. Events that fail to parse are skipped without
    being counted in the denominator -- counting them would bias the fraction downward, which is
    the direction that would make a run look cleaner than it is.
    """
    prod = os.path.join(run_dir, "producer.csv")
    cons = os.path.join(run_dir, "consumer_events.csv")
    if not (os.path.exists(prod) and os.path.exists(cons)):
        return None
    ack = {}
    try:
        with open(prod, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                v = r.get("t_broker_ack_ns")
                if v not in (None, "", "None"):
                    try:
                        ack[r["event_id"]] = int(v)
                    except (ValueError, KeyError):
                        continue
        deltas = []
        neg = 0
        with open(cons, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                a = ack.get(r.get("event_id"))
                rc = r.get("t_consume_ns")
                if a is None or rc in (None, "", "None"):
                    continue
                try:
                    d = int(rc) - a
                except ValueError:
                    continue
                deltas.append(d)
                if d < 0:
                    neg += 1
    except OSError:
        return None
    if not deltas:
        return {"n_matched": 0, "median_ms": "", "n_negative": 0, "frac_negative": ""}
    return {"n_matched": len(deltas),
            "median_ms": round(st.median(deltas) / 1e6, 6),
            "n_negative": neg,
            "frac_negative": round(neg / len(deltas), 6)}


def verdict(tr):
    """The gate applied to TRANSPORT ONLY. Unknown when unread, never silently 'pass'.

    The paper's audit is broader: it applies the same >1% rule to producer scheduling lag and
    consumer output as well, and condemns a run if any component fails. That audit lives in
    docs/results/integrity_windows/ (Testbed A) and docs/results/integrity_by_condition.csv
    (Testbed B) and is the authoritative one -- 1,321 of 2,266. This column is narrower by
    construction and its counts are not comparable to those.
    """
    if tr is None:
        return "not-assessed"
    if not tr["n_matched"]:
        return "no-matched-events"
    if tr["frac_negative"] > NEG_FRACTION_LIMIT or tr["median_ms"] < 0:
        return "condemned"
    return "usable"


def _count_lines(path):
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as fh:
            return max(sum(1 for _ in fh) - 1, 0)
    except OSError:
        return ""


def usage_map(results_dir):
    """Which run ids are named by a tracked aggregate, so unused runs are visibly unused."""
    used = {}
    for path in glob.glob(os.path.join(results_dir, "**", "*.csv"), recursive=True):
        rel = os.path.relpath(path, results_dir).replace("\\", "/")
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                head = fh.readline()
                if "run" not in head.lower():
                    continue
                fh.seek(0)
                for r in csv.DictReader(fh):
                    rid = r.get("run_id") or r.get("run") or r.get("run_dir")
                    if rid:
                        used.setdefault(os.path.basename(str(rid).rstrip("/\\")), set()).add(rel)
        except (OSError, csv.Error):
            continue
    return used


def build(runs_dir, results_dir, fast=False, progress=None):
    used = usage_map(results_dir)
    rows = []
    names = sorted(d for d in os.listdir(runs_dir)
                   if os.path.isdir(os.path.join(runs_dir, d)))
    for i, name in enumerate(names, 1):
        d = os.path.join(runs_dir, name)
        meta = _read_meta(d)
        tti = _read_tti(d)
        tr = None if fast else transport_and_integrity(d)
        rows.append({
            "run_id": name,
            "campaign": campaign_of(name),
            "started": started_of(name, meta),
            "backend": meta.get("backend") or "",
            "config": topology_of(name, meta),
            "feeds": feeds_of(name, meta),
            "speedup": meta.get("speedup") if meta.get("speedup") is not None else "",
            "plan": os.path.basename(str(meta.get("plan_csv") or "")),
            "host": (meta.get("host_platform") or {}).get("node", ""),
            # `or ""` rather than a default: the key exists and is null on some cloud runs,
            # and a default only fires when the key is absent.
            "git_head": ((meta.get("git") or {}).get("head") or "")[:12],
            "n_code_files": len(meta.get("code_sha256") or {}),
            "n_produced": _count_lines(os.path.join(d, "producer.csv")),
            "n_consumed": _count_lines(os.path.join(d, "consumer_events.csv")),
            "n_matched": tr["n_matched"] if tr else "",
            "transport_median_ms": tr["median_ms"] if tr else "",
            "tti_median_ms": (tti.get("tti_p50_ms") if tti.get("tti_p50_ms") is not None
                              else (tti.get("p50_ms") if tti.get("p50_ms") is not None
                                    else "")),
            "n_negative_transport": tr["n_negative"] if tr else "",
            "frac_negative_transport": tr["frac_negative"] if tr else "",
            "transport_integrity": verdict(tr),
            "used_by": ";".join(sorted(used.get(name, []))[:3]),
        })
        if progress and i % progress == 0:
            print(f"  {i:,}/{len(names):,}", file=sys.stderr, flush=True)
    return rows


def archive_metadata(runs_dir, out_path):
    """Every meta.json, one per line, gzipped.

    The per-file code SHA-256 in these is the only record of exactly which code produced a run.
    The index keeps a boolean; this keeps the hashes. A run whose meta.json will not parse is
    counted and reported rather than dropped silently -- the count is the difference between
    "we archived everything" and "we archived what happened to work".
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    n = skipped = 0
    with gzip.open(out_path, "wt", encoding="utf-8", newline="\n") as gz:
        for name in sorted(os.listdir(runs_dir)):
            path = os.path.join(runs_dir, name, "meta.json")
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    meta = json.load(fh)
            except (OSError, ValueError):
                skipped += 1
                continue
            meta.setdefault("run_id", name)
            gz.write(json.dumps(meta, separators=(",", ":"), sort_keys=True) + "\n")
            n += 1
    return n, skipped


CONDITION_FIELDS = ["prefix", "timestamp", "concurrency", "reps", "speedup", "max_t_sim",
                    "plan_csv", "total_runs", "success_count", "failure_count", "source"]


def index_conditions(results_dir):
    """One row per orchestrator invocation, from its <prefix>_summary.json.

    This is the only record of trials that were launched and failed: a failed trial writes no run
    directory, so it is invisible to the run index and to every aggregate. Keeping the launched
    and failed counts is what lets a reader tell "we ran 20 and report 20" from "we ran 20, two
    died, and we report 18".
    """
    rows = []
    for path in sorted(glob.glob(os.path.join(results_dir, "**", "*_summary.json"),
                                 recursive=True)):
        try:
            with open(path, encoding="utf-8-sig") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if "total_runs" not in d:
            continue          # not an orchestrator summary
        rows.append({
            "prefix": d.get("prefix", ""),
            "timestamp": d.get("timestamp", ""),
            "concurrency": d.get("concurrency", ""),
            "reps": d.get("reps", ""),
            "speedup": d.get("speedup", ""),
            "max_t_sim": d.get("max_t_sim", ""),
            "plan_csv": os.path.basename(str(d.get("plan_csv") or "")),
            "total_runs": d.get("total_runs", 0),
            "success_count": d.get("success_count", 0),
            "failure_count": d.get("failure_count", 0),
            "source": os.path.relpath(path, results_dir).replace("\\", "/"),
        })
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the permanent per-run index")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--results", default="docs/results")
    ap.add_argument("--out", default="reproducibility/runs_index.csv")
    ap.add_argument("--fast", action="store_true",
                    help="skip the raw-CSV pass; integrity is then 'not-assessed'")
    ap.add_argument("--archive-meta", default=None,
                    help="also write every meta.json to this gzipped JSONL, one run per line")
    ap.add_argument("--conditions", default=None,
                    help="also index the orchestrator condition summaries to this CSV")
    ap.add_argument("--progress", type=int, default=100)
    args = ap.parse_args(argv)

    if not os.path.isdir(args.runs):
        print(f"no such runs directory: {args.runs}")
        return 1

    rows = build(args.runs, args.results, fast=args.fast, progress=args.progress)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    by = {}
    for r in rows:
        by[r["transport_integrity"]] = by.get(r["transport_integrity"], 0) + 1
    unused = sum(1 for r in rows if not r["used_by"])
    print(f"wrote {args.out}: {len(rows):,} runs")
    for k in sorted(by):
        print(f"  {k:20s} {by[k]:6,}")
    print(f"  {'named by no aggregate':20s} {unused:6,}")

    if args.conditions:
        crows = index_conditions(args.results)
        with open(args.conditions, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CONDITION_FIELDS)
            w.writeheader()
            w.writerows(crows)
        launched = sum(r["total_runs"] or 0 for r in crows)
        failed = sum(r["failure_count"] or 0 for r in crows)
        print(f"wrote {args.conditions}: {len(crows):,} conditions, "
              f"{launched:,} trials launched, {failed:,} failed")

    if args.archive_meta:
        n, skipped = archive_metadata(args.runs, args.archive_meta)
        size = os.path.getsize(args.archive_meta) / 1e6
        print(f"wrote {args.archive_meta}: {n:,} meta.json ({size:.2f} MB)"
              + (f", {skipped} unreadable" if skipped else ""))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
