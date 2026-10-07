#!/usr/bin/env python3
"""
workload_stats.py
The workload the paper's runs carried: how large each message is and how fast it was published.

Section II names what a condition fixes -- the broker, the publish rate, the message size, the
background load and how often the consumer confirms -- and gave no number for the rate or the
size. Both are in every run's producer log, so they are counted here rather than recalled.

Message size. The producers do not send the football event itself. They send a JSON record of
its identifiers and timestamps (`msg` in scripts/kafka_producer.py and scripts/redis_producer.py,
written with json.dumps and compact separators), and every field of that record is a column of
producer.csv. Its size is therefore rebuilt exactly, byte for byte. One manipulation pads the
record (`--pad-bytes`, the E-A10 campaigns, Supplement S3.3); the run's own files do not record
the padding, so the sizes here are before padding, which is every unpadded run's size.

Publish rate. A run is one producer replaying one match. Its rate is the number of intervals
between its publish timestamps over the time from the first to the last.

The corpus is Table I's: the runs listed in docs/results/span_recount.csv. The raw archive is
not tracked (see recount_spans.py), so the per-run figures are written to a tracked CSV, and the
manuscript's macros are emitted from that.

CLI:
    python scripts/workload_stats.py --runs-dir cloud_archive/extracted/runs
    python scripts/workload_stats.py --archive cloud_archive/sbl_runs.tgz
"""
import argparse
import csv
import io
import json
import os
import re
import statistics
import sys
import tarfile

DEFAULT_ARCHIVE = os.path.join("cloud_archive", "sbl_runs.tgz")
DEFAULT_CORPUS = os.path.join("docs", "results", "span_recount.csv")
DEFAULT_OUT = os.path.join("docs", "results", "workload_by_run.csv")
FIELDS = ("run_id", "backend", "feeds", "messages", "duration_s", "publish_rate_hz",
          "bytes_min", "bytes_median", "bytes_max")


def message_bytes(row):
    """The size of the record a producer sent for one producer.csv row, before any padding."""
    msg = {
        "run_id": row["run_id"],
        "match_id": int(row["match_id"]),
        "event_id": row["event_id"],
        "t_sim_seconds": int(row["t_sim_seconds"]),
        "t_emit_offset_s": float(row["t_emit_offset_s"]),
        "t_emit_planned_ns": int(row["t_prod_sched_ns"]),
        "s3_uid": "%s:%s" % (int(row["match_id"]), row["event_id"]),
        "s3_rev": 1,
        "s3_is_correction": False,
    }
    return len(json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def feeds_of(run_id):
    """The number of matches the run's condition replayed at once, from its name."""
    m = re.match(r"concurrency_n(\d+)_", run_id)
    return int(m.group(1)) if m else ""


def summarise(run_id, backend, rows):
    """One run's row, or None when it has too few messages to have a rate."""
    sent = sorted(int(r["t_prod_send_ns"]) for r in rows)
    if len(sent) < 2 or sent[-1] <= sent[0]:
        return None
    duration = (sent[-1] - sent[0]) / 1e9
    sizes = sorted(message_bytes(r) for r in rows)
    return {"run_id": run_id, "backend": backend, "feeds": feeds_of(run_id),
            "messages": len(rows), "duration_s": "%.3f" % duration,
            "publish_rate_hz": "%.4f" % ((len(sent) - 1) / duration),
            "bytes_min": sizes[0], "bytes_median": int(statistics.median(sizes)),
            "bytes_max": sizes[-1]}


def _rows(blob):
    return list(csv.DictReader(io.StringIO(blob.decode("utf-8", errors="replace"))))


def _collect(found, wanted):
    """Rows for the corpus runs found, and the corpus runs that were not."""
    rows, missing = [], []
    for run_id, backend in wanted:
        if run_id not in found:
            missing.append(run_id)
            continue
        row = summarise(run_id, backend, _rows(found[run_id]))
        if row is None:
            missing.append(run_id)
            continue
        rows.append(row)
    return rows, missing


def scan_archive(path, wanted):
    """Stream the tarball once, keeping only the corpus runs' producer logs."""
    names = {run_id for run_id, _ in wanted}
    found = {}
    with tarfile.open(path, "r:gz") as tf:
        for member in tf:
            # The member rule recount_spans.scan_archive reads the same corpus with.
            parts = member.name.split("/")
            if (member.isfile() and len(parts) >= 3 and parts[0] == "runs"
                    and parts[-1] == "producer.csv" and parts[1] in names):
                found[parts[1]] = tf.extractfile(member).read()
    return _collect(found, wanted)


def scan_dir(path, wanted):
    """Same job over an unpacked runs/ tree."""
    found = {}
    for run_id, _ in wanted:
        fp = os.path.join(path, run_id, "producer.csv")
        if os.path.exists(fp):
            with open(fp, "rb") as fh:
                found[run_id] = fh.read()
    return _collect(found, wanted)


def read_corpus(path):
    """(run_id, backend) for every run of Table I's corpus."""
    with open(path, newline="", encoding="utf-8") as fh:
        return [(r["run_id"], r["backend"]) for r in csv.DictReader(fh)]


def write_csv(rows, path):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Message size and publish rate, run by run")
    ap.add_argument("--archive", default=DEFAULT_ARCHIVE)
    ap.add_argument("--runs-dir", default=None,
                    help="unpacked runs/ tree, used instead of the archive")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    if not os.path.exists(args.corpus):
        print("missing: %s" % args.corpus)
        return 1
    wanted = read_corpus(args.corpus)
    if args.runs_dir:
        if not os.path.isdir(args.runs_dir):
            print("missing: %s" % args.runs_dir)
            return 1
        rows, missing = scan_dir(args.runs_dir, wanted)
    else:
        if not os.path.exists(args.archive):
            print("missing: %s (pass --runs-dir for an unpacked tree)" % args.archive)
            return 1
        rows, missing = scan_archive(args.archive, wanted)
    # A partial table would describe a different corpus under Table I's name.
    if missing:
        print("%d corpus runs have no usable producer log, first %s -- refusing to write"
              % (len(missing), missing[0]))
        return 1
    write_csv(rows, args.out)
    print("wrote %s (%d runs)" % (args.out, len(rows)))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
