#!/usr/bin/env python3
"""
recount_spans.py
Count negative values on every latency span the corpus can form, separately.

Why this exists. The manuscript's first failure mode was described, through v2, as a
causality violation: broker delay is consumer receipt minus the producer's receipt of the
broker acknowledgement, and a message cannot arrive before it is sent. A reviewer pointed
out that the second clause does not describe the first. The broker's append precedes both
the producer's receipt of the acknowledgement and the consumer's receipt of the record;
those are two branches of one event, and neither precedes the other. A negative difference
between them is therefore not impossible, and calling it impossible was wrong.

The corpus can settle the question, because the producer log carries the send stamp beside
the acknowledgement stamp. The span `t_cons_recv - t_prod_send` IS a chain: the producer
sends, the broker appends, the consumer receives. If the negatives were a physical
impossibility they would appear there too. If they are a late acknowledgement stamp they
will appear only on the acknowledgement-referenced span. This script counts both, per run,
over every archived run, so the claim rests on arithmetic rather than on argument.

What it found, and why the output is committed. Of 738,730 joined events, the
acknowledgement-referenced span is negative 62,264 times and the send-referenced span is
negative never. The raw archive is 800 MB and not tracked (see .gitignore), so a clean
clone cannot re-run this. The per-run counts are therefore written to a tracked CSV, the
manuscript's macros derive from that CSV, and `emit_paper_numbers.py --check` can gate a
build without the archive present. This mirrors how `runs_index_cloud.csv` already stands
in for the raw runs it summarises.

Definitions, all in nanoseconds from the same wall clock (CLOCK_REALTIME):
    ack-referenced  t_cons_recv_ns - t_broker_ack_ns   the manuscript's "broker transport"
    send-referenced t_cons_recv_ns - t_prod_send_ns    one-way delivery, a causal chain
    send-to-output  t_output_ns    - t_prod_send_ns    delivery plus consumer handling
    TTI             t_output_ns    - t_prod_sched_ns   the primary measure, a causal chain

CLI:
    python scripts/recount_spans.py --archive cloud_archive/sbl_runs.tgz
    python scripts/recount_spans.py --runs-dir runs/
    python scripts/recount_spans.py --summary            # read the committed CSV, print totals
"""
import argparse
import csv
import io
import json
import os
import statistics
import sys
import tarfile

DEFAULT_ARCHIVE = os.path.join("cloud_archive", "sbl_runs.tgz")
DEFAULT_OUT = os.path.join("docs", "results", "span_recount.csv")

FIELDS = [
    "run_id", "backend", "n_events",
    "neg_ack", "neg_send", "neg_output_send", "neg_tti",
    "min_ack_us", "min_send_us", "median_ack_us", "median_send_us",
]

# The four spans, as (output-prefix, consumer-column, producer-column). Keeping them in one
# table rather than four hand-written subtractions is the point: the bug this script exists
# to correct was a claim about one span being quietly applied to another.
SPANS = (
    ("ack", "t_cons_recv_ns", "t_broker_ack_ns"),
    ("send", "t_cons_recv_ns", "t_prod_send_ns"),
    ("output_send", "t_output_ns", "t_prod_send_ns"),
    ("tti", "t_output_ns", "t_prod_sched_ns"),
)


def parse_rows(blob):
    """CSV bytes to a list of dicts. Decoding is lenient: a run with one mangled byte is
    still worth counting, and refusing it would silently shrink the denominator."""
    text = blob.decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def join_run(prod_rows, cons_rows):
    """Join producer and consumer events on event_id and return {span_name: [deltas_ns]}.

    Events present on one side only are dropped. That is not a silent discard of the kind
    this project audits: an unjoined event has no span to compute, and the count of joined
    events is reported beside every total.
    """
    index = {}
    for row in prod_rows:
        try:
            index[row["event_id"]] = {
                "t_prod_sched_ns": int(row["t_prod_sched_ns"]),
                "t_prod_send_ns": int(row["t_prod_send_ns"]),
                "t_broker_ack_ns": int(row["t_broker_ack_ns"]),
            }
        except (KeyError, TypeError, ValueError):
            continue

    out = {name: [] for name, _, _ in SPANS}
    for row in cons_rows:
        prod = index.get(row.get("event_id"))
        if prod is None:
            continue
        try:
            cons = {
                "t_cons_recv_ns": int(row["t_cons_recv_ns"]),
                "t_output_ns": int(row["t_output_ns"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
        for name, cons_col, prod_col in SPANS:
            out[name].append(cons[cons_col] - prod[prod_col])
    return out


def summarise_run(run_id, backend, spans):
    """One CSV row from one run's span lists. Returns None when nothing joined."""
    ack = spans["ack"]
    if not ack:
        return None
    row = {
        "run_id": run_id,
        "backend": backend,
        "n_events": len(ack),
        "min_ack_us": round(min(ack) / 1000.0, 1),
        "min_send_us": round(min(spans["send"]) / 1000.0, 1),
        "median_ack_us": round(statistics.median(ack) / 1000.0, 1),
        "median_send_us": round(statistics.median(spans["send"]) / 1000.0, 1),
    }
    for name, _, _ in SPANS:
        row["neg_" + name] = sum(1 for v in spans[name] if v < 0)
    return row


def _backend_of(meta_blob, prod_rows):
    """meta.json is authoritative; the producer log is the fallback when it is absent."""
    if meta_blob is not None:
        try:
            return json.loads(meta_blob.decode("utf-8", errors="replace")).get("backend", "")
        except ValueError:
            pass
    return prod_rows[0].get("backend", "") if prod_rows else ""


def _emit(collected, rows, skipped):
    """Turn one run's collected files into a row or a skip reason."""
    for run_id, files in collected.items():
        if "producer" not in files or "consumer" not in files:
            missing = "producer.csv" if "producer" not in files else "consumer.csv"
            skipped.append((run_id, "missing " + missing))
            continue
        prod = parse_rows(files["producer"])
        cons = parse_rows(files["consumer"])
        if not prod or not cons:
            skipped.append((run_id, "empty prod=%d cons=%d" % (len(prod), len(cons))))
            continue
        row = summarise_run(run_id, _backend_of(files.get("meta"), prod),
                            join_run(prod, cons))
        if row is None:
            skipped.append((run_id, "no joined events"))
            continue
        rows.append(row)


def scan_archive(path):
    """Stream the tarball once. 56k members do not need to touch the disk to be counted."""
    collected = {}
    with tarfile.open(path, "r:gz") as tf:
        for member in tf:
            if not member.isfile():
                continue
            parts = member.name.split("/")
            if len(parts) < 3 or parts[0] != "runs":
                continue
            name = parts[-1]
            if name not in ("producer.csv", "consumer.csv", "meta.json"):
                continue
            handle = tf.extractfile(member)
            if handle is None:
                continue
            key = "meta" if name == "meta.json" else name.split(".")[0]
            collected.setdefault(parts[1], {})[key] = handle.read()
    rows, skipped = [], []
    _emit(collected, rows, skipped)
    return rows, skipped


def scan_dir(path):
    """Same job over an unpacked runs/ tree, for anyone without the archive."""
    collected = {}
    for run_id in sorted(os.listdir(path)):
        run_dir = os.path.join(path, run_id)
        if not os.path.isdir(run_dir):
            continue
        files = {}
        for name, key in (("producer.csv", "producer"), ("consumer.csv", "consumer"),
                          ("meta.json", "meta")):
            fp = os.path.join(run_dir, name)
            if os.path.exists(fp):
                with open(fp, "rb") as fh:
                    files[key] = fh.read()
        if files:
            collected[run_id] = files
    rows, skipped = [], []
    _emit(collected, rows, skipped)
    return rows, skipped


def totals(rows):
    """The aggregate the manuscript quotes. Percentages are of joined events."""
    events = sum(int(r["n_events"]) for r in rows)
    agg = {
        "runs": len(rows),
        "events": events,
        "runs_over_one_pct_ack": sum(
            1 for r in rows
            if int(r["n_events"]) and int(r["neg_ack"]) / int(r["n_events"]) > 0.01),
        "runs_negative_median_ack": sum(1 for r in rows if float(r["median_ack_us"]) < 0),
        # The shared-stamp contrast, and why it is worth its own counter.
        #
        # Both spans end at the *same* clock read in the consumer. They differ only in which
        # producer-side stamp they start from. So any artefact of the clock itself -- a
        # cross-CPU incoherence under thread migration, a hypervisor that does not expose an
        # invariant TSC, an NTP step -- perturbs the shared endpoint and moves both spans
        # together. A fault in one producer-side stamp moves only one.
        #
        # This counts the runs where, over an identical event set, the acknowledgement span
        # inverts and the send span does not. It is the discriminator between "the clock is
        # unreliable" and "one stamp is late", and it is a count rather than an argument.
        "runs_ack_only_inversions": sum(
            1 for r in rows if int(r["neg_ack"]) > 0 and int(r["neg_send"]) == 0),
        "runs_send_inverts": sum(1 for r in rows if int(r["neg_send"]) > 0),
    }
    for name, _, _ in SPANS:
        agg["neg_" + name] = sum(int(r["neg_" + name]) for r in rows)
        agg["pct_" + name] = (100.0 * agg["neg_" + name] / events) if events else 0.0
    return agg


def write_csv(rows, out):
    parent = os.path.dirname(out)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["run_id"]):
            writer.writerow(row)


def read_csv(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def report(agg):
    return (
        "runs %(runs)d  events %(events)d\n"
        "  ack-referenced   negatives %(neg_ack)d (%(pct_ack).4f%%)\n"
        "  send-referenced  negatives %(neg_send)d (%(pct_send).4f%%)\n"
        "  send-to-output   negatives %(neg_output_send)d (%(pct_output_send).4f%%)\n"
        "  TTI              negatives %(neg_tti)d (%(pct_tti).4f%%)\n"
        "  runs over 1%% negative on the ack span: %(runs_over_one_pct_ack)d\n"
        "  runs with a negative ack median:        %(runs_negative_median_ack)d\n" % agg)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Count negatives on each latency span separately")
    ap.add_argument("--archive", default=DEFAULT_ARCHIVE)
    ap.add_argument("--runs-dir", default=None,
                    help="unpacked runs/ tree, used instead of the archive")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--summary", action="store_true",
                    help="read the committed CSV and print totals; touches no archive")
    args = ap.parse_args(argv)

    if args.summary:
        if not os.path.exists(args.out):
            print("missing: %s" % args.out)
            return 1
        print(report(totals(read_csv(args.out))))
        return 0

    if args.runs_dir:
        if not os.path.isdir(args.runs_dir):
            print("missing: %s" % args.runs_dir)
            return 1
        rows, skipped = scan_dir(args.runs_dir)
    else:
        if not os.path.exists(args.archive):
            print("missing: %s (pass --runs-dir for an unpacked tree)" % args.archive)
            return 1
        rows, skipped = scan_archive(args.archive)

    if not rows:
        print("no runs produced a joined event -- refusing to write an empty recount")
        return 1

    write_csv(rows, args.out)
    print("wrote %s (%d runs, %d skipped)" % (args.out, len(rows), len(skipped)))
    print(report(totals(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
