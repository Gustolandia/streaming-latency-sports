#!/usr/bin/env python3
"""
span_histogram.py
Bin every span the corpus can form, so the distribution can be drawn without the raw archive.

Why this exists. `recount_spans.py` answers "how many negatives", which is the number the
manuscript quotes. It cannot answer "what does the distribution look like", because it keeps
only per-run aggregates. A reader -- and a reviewer -- asked for the picture rather than the
fraction: plot the measured latencies, note the population sitting left of zero, then plot the
same population as the instrument leaves it once that population is deleted, and the two graphs
do not look alike. A retained fraction states that; a histogram shows it.

The raw archive is 800 MB and untracked, so a clean clone cannot re-run the scan. This script
therefore writes binned counts to a tracked CSV, exactly as `recount_spans.py` writes per-run
counts, and every plotting decision downstream reads the CSV rather than the archive. Bin edges
are fixed here and not chosen from the data, so the committed CSV cannot quietly change shape
when the corpus is rescanned.

Two spans matter and they behave differently, which is the whole point:

    ack-referenced   t_cons_recv - t_broker_ack    negative 62,264 times in 738,730 events
    send-referenced  t_cons_recv - t_prod_send     negative never, at nanosecond resolution

What the benchmark sees is neither. The OpenMessaging Benchmark reads a millisecond-resolution
publish stamp (Kafka's CreateTime) and differences it against a millisecond receive stamp, so
its sample is a difference of two truncated values, and it admits the sample only when that
difference is strictly positive (`if (endToEndLatencyMicros > 0)`). On a sub-millisecond path
that rule deletes a population the nanosecond measurement shows is perfectly ordered: the
zeros are an artefact of the grid, not of the network. This script tallies the millisecond
difference as well, so the deletion can be drawn against the truth on the same events.

Five dispositions for a non-positive sample are found in real software and audited in the
manuscript. All five are applied to the same measured population here:

    discard     OMB's `> 0` guard, and emqtt-bench's. The sample vanishes, uncounted.
    zero        fio `gettime.c` returns 0 on a detected backwards clock.
    unit        btt `tdelta()` returns 1 when from >= to.
    nan         KIP-489 yields NaN.
    keep        what this project does, and the only one that can be audited afterwards.

CLI:
    python scripts/span_histogram.py --archive cloud_archive/sbl_runs.tgz
    python scripts/span_histogram.py --runs-dir runs/
    python scripts/span_histogram.py --summary        # read the committed CSV, print totals
"""
import argparse
import csv
import json
import os
import sys

import recount_spans

DEFAULT_ARCHIVE = os.path.join("cloud_archive", "sbl_runs.tgz")
DEFAULT_OUT = os.path.join("docs", "results", "span_histogram.csv")
DEFAULT_STATS = os.path.join("docs", "results", "span_histogram_stats.json")

#: Bin edges in microseconds. Fixed, not data-derived: a committed CSV whose bins move when the
#: corpus is rescanned is not a record of anything. The window is wide enough to hold every
#: negative the corpus contains (the most negative run minimum is -99.8 ms) and counts outside
#: it are kept in the two overflow rows rather than dropped, because dropping what does not fit
#: is the failure this project is about.
BIN_LO_US = -100_000
BIN_HI_US = 100_000
BIN_WIDTH_US = 50

#: Spans binned, as (name, consumer-column, producer-column). Same table as recount_spans.
SPANS = recount_spans.SPANS

#: Millisecond-difference tallies are capped; anything beyond lands in the overflow key. The
#: collapse campaigns reach 500 s, and a dict keyed by every millisecond to 500,000 is noise.
MS_CAP = 200


def n_bins():
    return (BIN_HI_US - BIN_LO_US) // BIN_WIDTH_US


def bin_index(value_us):
    """Bin for a microsecond value, or None when it falls outside the window."""
    if value_us < BIN_LO_US or value_us >= BIN_HI_US:
        return None
    return int((value_us - BIN_LO_US) // BIN_WIDTH_US)


def bin_low_us(index):
    return BIN_LO_US + index * BIN_WIDTH_US


def new_accumulator():
    """Everything the scan accumulates. Plain dicts so the shape is visible in one place."""
    return {
        "hist": {name: [0] * n_bins() for name, _, _ in SPANS},
        "under": {name: 0 for name, _, _ in SPANS},
        "over": {name: 0 for name, _, _ in SPANS},
        "n": {name: 0 for name, _, _ in SPANS},
        "neg": {name: 0 for name, _, _ in SPANS},
        "zero": {name: 0 for name, _, _ in SPANS},
        # Millisecond-truncated difference, the quantity the benchmark actually holds.
        "ms": {name: {} for name, _, _ in SPANS},
        "runs": 0,
        "events": 0,
    }


def add_event(acc, name, delta_ns, recv_ns, ref_ns):
    """Tally one event on one span: the fine histogram, and the millisecond grid."""
    acc["n"][name] += 1
    if delta_ns < 0:
        acc["neg"][name] += 1
    elif delta_ns == 0:
        acc["zero"][name] += 1

    value_us = delta_ns / 1000.0
    index = bin_index(value_us)
    if index is None:
        if value_us < BIN_LO_US:
            acc["under"][name] += 1
        else:
            acc["over"][name] += 1
    else:
        acc["hist"][name][index] += 1

    # What a millisecond-resolution instrument would hold for this same event: two truncated
    # stamps, differenced. Not the true value rounded -- that is a different and kinder thing.
    ms = (recv_ns // 1_000_000) - (ref_ns // 1_000_000)
    key = ms if -MS_CAP <= ms <= MS_CAP else (MS_CAP + 1 if ms > MS_CAP else -MS_CAP - 1)
    acc["ms"][name][key] = acc["ms"][name].get(key, 0) + 1


def consume_run(acc, prod_rows, cons_rows):
    """Join one run and tally every event on every span. Returns events counted."""
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

    counted = 0
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
        counted += 1
        for name, cons_col, prod_col in SPANS:
            recv_ns = cons[cons_col]
            ref_ns = prod[prod_col]
            add_event(acc, name, recv_ns - ref_ns, recv_ns, ref_ns)
    return counted


def _flush(acc, files):
    """One buffered run into the accumulator, if it has both halves."""
    if "producer" not in files or "consumer" not in files:
        return False
    prod = recount_spans.parse_rows(files["producer"])
    cons = recount_spans.parse_rows(files["consumer"])
    if not prod or not cons:
        return False
    counted = consume_run(acc, prod, cons)
    if not counted:
        return False
    acc["runs"] += 1
    acc["events"] += counted
    return True


def scan_archive(path, acc=None, progress=None):
    """Stream the tarball, flushing each run as it completes.

    Unlike `recount_spans.scan_archive`, runs are flushed as the stream passes them rather than
    buffered to the end. That script holds every producer.csv in memory at once, which is about
    600 MB for this corpus; here the histogram is the only thing that grows.
    """
    import tarfile

    acc = new_accumulator() if acc is None else acc
    pending = {}
    with tarfile.open(path, "r:gz") as tf:
        for member in tf:
            if not member.isfile():
                continue
            parts = member.name.split("/")
            if len(parts) < 3 or parts[0] != "runs":
                continue
            name = parts[-1]
            if name not in ("producer.csv", "consumer.csv"):
                continue
            handle = tf.extractfile(member)
            if handle is None:
                continue
            run_id = parts[1]
            key = name.split(".")[0]
            pending.setdefault(run_id, {})[key] = handle.read()
            if len(pending[run_id]) == 2:
                _flush(acc, pending.pop(run_id))
                if progress and acc["runs"] % progress == 0:
                    sys.stderr.write("  %d runs, %d events\r" % (acc["runs"], acc["events"]))
                    sys.stderr.flush()
    for files in pending.values():
        _flush(acc, files)
    return acc


def scan_dir(path, acc=None):
    """Same job over an unpacked runs/ tree, for anyone without the archive."""
    acc = new_accumulator() if acc is None else acc
    for run_id in sorted(os.listdir(path)):
        run_dir = os.path.join(path, run_id)
        if not os.path.isdir(run_dir):
            continue
        files = {}
        for fname, key in (("producer.csv", "producer"), ("consumer.csv", "consumer")):
            fp = os.path.join(run_dir, fname)
            if os.path.exists(fp):
                with open(fp, "rb") as fh:
                    files[key] = fh.read()
        _flush(acc, files)
    return acc


def strategy_counts(acc, name):
    """What each real-world disposition does to this span's non-positive population.

    Returned as counts rather than as a redrawn histogram: the histogram transform is a
    presentation choice and belongs in the figure, but the counts are the fact.
    """
    total = acc["n"][name]
    neg = acc["neg"][name]
    zero = acc["zero"][name]
    nonpos = neg + zero
    return {
        "total": total,
        "negative": neg,
        "zero": zero,
        "non_positive": nonpos,
        "retained_discard": total - nonpos,
        "retained_zero": total,
        "retained_unit": total,
        "retained_nan": total - nonpos,
        "retained_keep": total,
        "reported_fraction_discard": (total - nonpos) / total if total else 0.0,
    }


def ms_retention(acc, name):
    """Retention under the benchmark's own rule: millisecond difference, keep if > 0."""
    table = acc["ms"][name]
    total = sum(table.values())
    kept = sum(count for value, count in table.items() if value > 0)
    return {
        "total": total,
        "kept": kept,
        "dropped": total - kept,
        "retention": kept / total if total else 0.0,
        "at_zero": table.get(0, 0),
        "below_zero": sum(c for v, c in table.items() if v < 0),
    }


def write_csv(acc, out):
    """Bin counts, one row per bin, every span in columns."""
    names = [name for name, _, _ in SPANS]
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["bin_low_us", "bin_high_us"] + names)
        for i in range(n_bins()):
            counts = [acc["hist"][name][i] for name in names]
            if not any(counts):
                continue
            writer.writerow([bin_low_us(i), bin_low_us(i) + BIN_WIDTH_US] + counts)
        writer.writerow(["UNDERFLOW", ""] + [acc["under"][n] for n in names])
        writer.writerow(["OVERFLOW", ""] + [acc["over"][n] for n in names])
    return out


def write_stats(acc, out):
    """Everything that is a count rather than a bin: totals, signs, the millisecond grid."""
    names = [name for name, _, _ in SPANS]
    payload = {
        "runs": acc["runs"],
        "events": acc["events"],
        "bin_lo_us": BIN_LO_US,
        "bin_hi_us": BIN_HI_US,
        "bin_width_us": BIN_WIDTH_US,
        "spans": {
            name: {
                "counts": strategy_counts(acc, name),
                "ms_rule": ms_retention(acc, name),
                "ms_table": {str(k): v for k, v in sorted(acc["ms"][name].items())},
            }
            for name in names
        },
    }
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    return out


def report(stats):
    """Print what the scan found, in the terms the figure will use."""
    print("runs   %d" % stats["runs"])
    print("events %d" % stats["events"])
    for name, payload in sorted(stats["spans"].items()):
        c = payload["counts"]
        m = payload["ms_rule"]
        if not c["total"]:
            continue
        print("")
        print("%-12s n=%d" % (name, c["total"]))
        print("   negative            %8d  (%.2f%%)"
              % (c["negative"], 100.0 * c["negative"] / c["total"]))
        print("   exactly zero        %8d" % c["zero"])
        print("   discard keeps       %8d  (%.2f%% of samples taken)"
              % (c["retained_discard"], 100.0 * c["reported_fraction_discard"]))
        print("   ms-grid: at 0 %d, below 0 %d, retention %.2f%%"
              % (m["at_zero"], m["below_zero"], 100.0 * m["retention"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bin every latency span, and the grid the benchmark sees")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--archive", nargs="?", const=DEFAULT_ARCHIVE)
    src.add_argument("--runs-dir")
    src.add_argument("--summary", action="store_true", help="read the committed stats and print")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--stats", default=DEFAULT_STATS)
    ap.add_argument("--progress", type=int, default=250)
    args = ap.parse_args(argv)

    if args.summary:
        with open(args.stats, encoding="utf-8") as fh:
            report(json.load(fh))
        return 0

    if args.runs_dir:
        acc = scan_dir(args.runs_dir)
    else:
        acc = scan_archive(args.archive or DEFAULT_ARCHIVE, progress=args.progress)

    sys.stderr.write("\n")
    write_csv(acc, args.out)
    write_stats(acc, args.stats)
    with open(args.stats, encoding="utf-8") as fh:
        report(json.load(fh))
    print("")
    print("wrote %s and %s" % (args.out, args.stats))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
