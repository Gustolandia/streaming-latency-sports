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
          "zero_share", "message_size_b", "producer_rate", "duration_min", "load_pct",
          "bootstrap", "count_source", "stdout_bytes", "stdout_sha256", "mtime_utc")


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
    want = {"messageSize": "message_size_b", "producerRate": "producer_rate",
            "testDurationMinutes": "duration_min"}
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
    """The single header-less row written by the campaign script."""
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = [r for r in csv.reader(fh) if r]
    except OSError:
        return {}
    if not rows:
        return {}
    row = rows[-1]
    return {k: (row[i] if i < len(row) else "") for i, k in enumerate(RESULT_FIELDS)}


def parse_counts(cell_dir):
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
    digest = sha256_of(log)

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


def invalid_reason(cell_dir, campaign, result):
    """Why a cell carries no measurement. Empty string means it does."""
    if campaign.upper() == "INVALID" or "INVALID" in os.path.basename(cell_dir).upper():
        return "marked INVALID by the campaign"
    if result.get("valid") == "0":
        return "campaign marked valid=0"
    if not result:
        return "no result row written"
    return ""


def index_cell(cell_dir, campaign):
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

    counts, source, size, digest = parse_counts(cell_dir)
    # The log is the primary source: the result CSV is derived from it by the campaign script, so
    # when they disagree the log wins and the disagreement is worth seeing.
    row.update(counts)
    row["count_source"] = source
    row["stdout_bytes"] = size
    row["stdout_sha256"] = digest

    row.update(parse_workload(os.path.join(cell_dir, "omb_workload.yaml")))
    row["zero_share"] = zero_share(row["kept"], row["discarded_zero"],
                                   row["discarded_negative"])

    reason = invalid_reason(cell_dir, campaign, result)
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


def walk(root):
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
            rows.append(index_cell(cdir, campaign))
            continue
        for cell in sorted(os.listdir(cdir)):
            cell_dir = os.path.join(cdir, cell)
            if is_cell(cell_dir):
                rows.append(index_cell(cell_dir, campaign))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Index external-harness campaign cells")
    ap.add_argument("--root", default="docs/results/external")
    ap.add_argument("--out", default="docs/results/external_campaigns_index.csv")
    args = ap.parse_args(argv)

    rows = walk(args.root)
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
    print(f"  logs covered     : {total_bytes / (1 << 20):.0f} MiB, hashed")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
