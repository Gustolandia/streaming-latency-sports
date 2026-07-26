#!/usr/bin/env python3
"""
index_external_campaigns.py
One tracked row per external-harness campaign cell.

`build_runs_index.py` indexes our own harness: directories under `runs/` carrying a `meta.json`.
The OpenMessaging Benchmark campaigns have neither. A cell is a directory holding the workload
and driver YAML we generated, the patch we applied, a one-line result CSV, and a stdout log that
runs to about 31 MB. Fifteen cells of the load sweep are 300 MB whose entire information content
is four integers and a handful of configuration values.

That combination -- large, unindexed, and mostly redundant -- is how runs stop being tracked. This
script reads each cell once and writes a row that is sufficient on its own: what was configured,
what the instrumented counter reported, whether the count is exact or quantised, and the size and
SHA-256 of the log it came from. With the row committed, the log can be dropped and the claim it
supports is still checkable: re-run the cell, hash the log, compare.

Cells that produced no usable measurement are indexed too, with `valid=0` and the reason. A run
that failed is a fact about the campaign; leaving it out of the ledger is how a sweep silently
becomes a selection of its successes.

CLI:
    python scripts/index_external_campaigns.py --root docs/results/external \\
        --out docs/results/external_campaigns_index.csv
"""
import argparse
import csv
import hashlib
import os
import re
import sys

# The stdout log is tens of megabytes and the summary is printed by a JVM shutdown hook, so it is
# within the last few kilobytes. Reading the tail keeps this linear in cell count, not in bytes.
TAIL_BYTES = 256 * 1024

# Written by `omb_discard_count.sh`; the field order is fixed by that script.
RESULT_FIELDS = ("harness", "mode", "valid", "discarded_total", "discarded_zero",
                 "discarded_negative", "most_negative_micros", "kept", "pub_lines",
                 "duration_min", "load_pct", "bootstrap")

CELL_RE = re.compile(r"^(?P<axis>[ls])(?P<level>\d+)_rep(?P<rep>\d+)$")

SUMMARY_RE = re.compile(
    r"SBL_DISCARD_SUMMARY\s+kept=(?P<kept>\d+)\s+zero=(?P<zero>\d+)\s+"
    r"negative=(?P<negative>\d+)\s+most_negative_micros=(?P<most_negative>-?\d+)")

# The periodic progress lines. Falling back to these quantises the total to the print interval,
# which is why the source is recorded rather than assumed.
PERIODIC_RE = re.compile(r"SBL_DISCARD_(?:ZERO|NEGATIVE) total=(\d+)")

FIELDS = ("campaign", "cell", "axis", "level", "rep", "valid", "invalid_reason",
          "kept", "discarded_zero", "discarded_negative", "most_negative_micros",
          "zero_share", "message_size_b", "producer_rate", "duration_min", "warmup_min",
          "load_pct", "bootstrap", "count_source", "stdout_bytes", "stdout_sha256", "mtime_utc")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_tail(path, nbytes=TAIL_BYTES):
    """Last `nbytes` of a file, decoded leniently. Logs carry whatever the JVM emitted."""
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        if size > nbytes:
            fh.seek(size - nbytes)
        return fh.read().decode("utf-8", errors="replace")


def parse_cell_name(name):
    """`l88_rep2` -> load level 88, rep 2. `s4096_rep1` -> message size 4096, rep 1."""
    m = CELL_RE.match(name)
    if not m:
        return {"axis": "", "level": "", "rep": ""}
    axis = "load_pct" if m.group("axis") == "l" else "message_size"
    return {"axis": axis, "level": m.group("level"), "rep": m.group("rep")}


def parse_workload(path):
    """The few scalars we set. A hand-rolled reader beats a YAML dependency for eleven keys."""
    # warmupDurationMinutes decides whether a cell's counts are comparable with OMB's own
    # reported percentiles. Our counters never reset, so they span warmup and test; OMB resets
    # its histograms at the boundary. A cell that ran with a warmup is counting more samples than
    # the distribution it is being compared against, so the setting belongs in the ledger.
    want = {"messageSize": "message_size_b", "producerRate": "producer_rate",
            "testDurationMinutes": "duration_min", "warmupDurationMinutes": "warmup_min"}
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                key, sep, val = line.partition(":")
                if sep and key.strip() in want:
                    out[want[key.strip()]] = val.strip()
    except OSError:
        pass
    return out


def parse_result_csv(path):
    """The row the campaign script wrote, mapped by ITS OWN header.

    Earlier versions of the campaign wrote a different and shorter column set -- an invalid cell
    still writes `harness,mode,valid,discarded_nonpositive,reason,duration_min,load_pct`. Mapping
    such a row positionally onto today's twelve fields shifts every column: in the `smoke` cell it
    put the bootstrap string under `kept` and a `1` under `discarded_negative`, inventing a
    causality violation out of a schema assumption. That is the failure this project is about,
    committed by the instrument built to detect it.

    The header is in the file. Use it, and fall back to positional mapping only when there is no
    recognisable header to use.
    """
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = [r for r in csv.reader(fh) if r]
    except OSError:
        return {}
    if not rows:
        return {}

    header = [c.strip() for c in rows[0]]
    if "harness" in header and len(rows) > 1:
        row = rows[-1]
        by_name = {k: (row[i] if i < len(row) else "") for i, k in enumerate(header)}
        # Only fields this ledger knows about; an unrecognised column is not silently adopted.
        return {k: v for k, v in by_name.items() if k in RESULT_FIELDS}

    row = rows[-1]
    return {k: (row[i] if i < len(row) else "") for i, k in enumerate(RESULT_FIELDS)}


def parse_counts(cell_dir, hash_logs=True):
    """Counts plus where they came from.

    The shutdown hook prints exact totals once at exit. The periodic lines fire every 10,000, so
    reading them gives a lower bound rounded down to a multiple of 10,000 -- three runs with
    genuinely different totals once all reported 50000 that way. Which source was used decides
    whether the number can carry a claim, so it is a column rather than a footnote.
    """
    log = os.path.join(cell_dir, "omb_stdout.log")
    if not os.path.exists(log):
        return {}, "absent", 0, ""
    text = read_tail(log)
    size = os.path.getsize(log)
    # Hashing reads the whole log. Interim indexing runs while cells are being measured on the
    # same host, and a few hundred megabytes of disk reads during a latency measurement is
    # exactly the kind of self-inflicted perturbation this project exists to complain about.
    # The tail read above is a few kilobytes and is safe; the hash waits for the campaign to end.
    digest = sha256_of(log) if hash_logs else ""

    hits = list(SUMMARY_RE.finditer(text))
    if hits:
        g = hits[-1].groupdict()
        return ({"kept": g["kept"], "discarded_zero": g["zero"],
                 "discarded_negative": g["negative"],
                 "most_negative_micros": g["most_negative"]},
                "shutdown_hook", size, digest)
    if PERIODIC_RE.search(text):
        return {}, "periodic_quantised", size, digest
    return {}, "none_in_log", size, digest


def zero_share(kept, zero, negative):
    """Share of everything the harness saw that computed to exactly zero."""
    try:
        k, z, n = int(kept), int(zero), int(negative)
    except (TypeError, ValueError):
        return ""
    seen = k + z + n
    return "" if seen <= 0 else round(z / seen, 6)


def invalid_reason(cell_dir, campaign, result, counts=None, source=""):
    """Why a cell carries no measurement. Empty string means it does.

    The result CSV is written by the campaign script *after* the benchmark finishes, so a script
    that dies in between leaves a directory with a complete measurement in its log and no row.
    That is not an invalid cell; it is a valid cell with a missing receipt, and cell l95_rep2 --
    24 publish-rate lines, an exact summary of kept=93381 zero=27311 negative=0 -- is one.
    Treating the missing receipt as the verdict would discard a real measurement, which is the
    error this whole ledger exists to prevent.

    An exact shutdown summary reporting samples is therefore sufficient on its own: the hook only
    runs in a JVM that started, and non-zero counts only exist if the benchmark recorded latency.
    """
    if campaign.upper() == "INVALID" or "INVALID" in os.path.basename(cell_dir).upper():
        return "marked INVALID by the campaign"
    if result.get("valid") == "0":
        return "campaign marked valid=0"
    measured = bool(counts) and source == "shutdown_hook" and any(
        (counts.get(k) or "0") != "0"
        for k in ("kept", "discarded_zero", "discarded_negative"))
    if not result:
        if measured:
            return ""
        return "no result row written"
    return ""


def index_cell(cell_dir, campaign, hash_logs=True):
    name = os.path.basename(cell_dir)
    row = {k: "" for k in FIELDS}
    row["campaign"] = campaign
    row["cell"] = name
    row.update(parse_cell_name(name))

    result = parse_result_csv(os.path.join(cell_dir, "omb_loaded_result.csv"))
    for key in ("kept", "discarded_zero", "discarded_negative", "most_negative_micros",
                "duration_min", "load_pct", "bootstrap"):
        if result.get(key):
            row[key] = result[key]

    counts, source, size, digest = parse_counts(cell_dir, hash_logs=hash_logs)
    # The log is the primary source: the result CSV is derived from it by the campaign script, so
    # when they disagree the log wins and the disagreement is worth seeing.
    row.update(counts)
    row["count_source"] = source
    row["stdout_bytes"] = size
    row["stdout_sha256"] = digest

    workload_path = os.path.join(cell_dir, "omb_workload.yaml")
    row.update(parse_workload(workload_path))
    # The cells run before the setting was made explicit have no key at all, and OMB's default of
    # one minute applied to them silently. Recording that as blank would read as "no warmup",
    # which is the opposite of what happened, so it is marked as the default rather than left to
    # be guessed from the run date.
    if not row["warmup_min"] and os.path.exists(workload_path):
        row["warmup_min"] = "1(default)"
    row["zero_share"] = zero_share(row["kept"], row["discarded_zero"],
                                   row["discarded_negative"])

    reason = invalid_reason(cell_dir, campaign, result, counts, source)
    row["invalid_reason"] = reason
    row["valid"] = "0" if reason else (result.get("valid") or "1")

    try:
        import datetime as _dt
        row["mtime_utc"] = _dt.datetime.utcfromtimestamp(
            os.path.getmtime(cell_dir)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        pass
    return row


def is_cell(path):
    """A cell is a directory that a campaign wrote a run into."""
    if not os.path.isdir(path):
        return False
    return any(os.path.exists(os.path.join(path, f))
               for f in ("omb_stdout.log", "omb_loaded_result.csv", "omb_workload.yaml"))


def walk(root, hash_logs=True):
    """Campaign directories one level under root; cells one level under those.

    A campaign that wrote its cell straight into the campaign directory is handled too, so a
    smoke test does not silently fall out of the ledger.
    """
    rows = []
    if not os.path.isdir(root):
        return rows
    for campaign in sorted(os.listdir(root)):
        cdir = os.path.join(root, campaign)
        if not os.path.isdir(cdir):
            continue
        if is_cell(cdir):
            rows.append(index_cell(cdir, campaign, hash_logs=hash_logs))
            continue
        for cell in sorted(os.listdir(cdir)):
            cell_dir = os.path.join(cdir, cell)
            if is_cell(cell_dir):
                rows.append(index_cell(cell_dir, campaign, hash_logs=hash_logs))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Index external-harness campaign cells")
    ap.add_argument("--root", default="docs/results/external")
    ap.add_argument("--out", default="docs/results/external_campaigns_index.csv")
    ap.add_argument("--no-hash", action="store_true",
                    help="skip the SHA-256 of each log; safe to run while cells are "
                         "being measured on the same host")
    args = ap.parse_args(argv)

    rows = walk(args.root, hash_logs=not args.no_hash)
    if not rows:
        print(f"no campaign cells under {args.root}")
        return 1

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    valid = sum(1 for r in rows if r["valid"] == "1")
    exact = sum(1 for r in rows if r["count_source"] == "shutdown_hook")
    total_bytes = sum(int(r["stdout_bytes"] or 0) for r in rows)
    print(f"indexed {len(rows)} cells from {args.root}")
    print(f"  valid            : {valid}")
    print(f"  invalid          : {len(rows) - valid}")
    print(f"  exact counts     : {exact}")
    print(f"  quantised/absent : {len(rows) - exact}")
    hashed = "hashed" if not args.no_hash else "NOT hashed (--no-hash)"
    print(f"  logs covered     : {total_bytes / (1 << 20):.0f} MiB, {hashed}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
