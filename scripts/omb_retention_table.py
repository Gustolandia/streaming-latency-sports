#!/usr/bin/env python3
"""
omb_retention_table.py
What did the benchmark report, and how much of its data was behind it?

The discard sweep establishes that the OpenMessaging Benchmark drops most of its end-to-end
samples on a sub-millisecond path. This joins each cell to the latency summary OMB itself
published for that run, which is the part a user would actually read, and puts the two side by
side.

The join is exact rather than by timestamp proximity: each run writes
`Writing test result into omb_workload-Kafka-<stamp>.json` into its own log, so the cell names
its result file.

Two properties come out of the pairing, and neither is visible in OMB's output alone:

  * the reported median is the same whether the run kept 0.83% of its samples or 100% of them.
    It is one millisecond either way, because a millisecond-grained subtraction on a
    sub-millisecond path can only return small integers, and the survivors are the samples that
    reached one tick. Retention varies 120-fold across runs; the headline number does not move.

  * the reported *average* moves the wrong way. Discarding everything below one tick removes the
    fast samples, so what remains is the slow tail and the mean rises. The benchmark reports a
    higher average latency the more data it discards, which inverts the direction a reader would
    assume a "dropped samples" caveat implied -- if one were printed, which it is not.

Reported as Spearman rank correlation between retention and reported average, because the
relationship is monotone rather than linear and n is small.

CLI:
    python scripts/omb_retention_table.py --root docs/results/external --omb-dir ~/omb \\
        --out docs/results/external/omb_retention.csv
"""
import argparse
import csv
import glob
import json
import os
import re

SUMMARY_RE = re.compile(
    r"SBL_DISCARD_SUMMARY\s+kept=(\d+)\s+zero=(\d+)\s+negative=(\d+)")
RESULT_JSON_RE = re.compile(r"omb_workload-[A-Za-z]+-[\d-]+\.json")

TAIL_BYTES = 512 * 1024

FIELDS = ("campaign", "cell", "kept", "discarded_zero", "discarded_negative",
          "retention_pct", "omb_p50_ms", "omb_p99_ms", "omb_max_ms", "omb_avg_ms",
          "result_json")


def read_tail(path, nbytes=TAIL_BYTES):
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        if size > nbytes:
            fh.seek(size - nbytes)
        return fh.read().decode("utf-8", errors="replace")


def last_of(d, key):
    """OMB writes some fields as a per-interval list and some as a scalar."""
    v = d.get(key)
    if isinstance(v, list):
        return v[-1] if v else None
    return v


def parse_cell(cell_dir, omb_dir):
    """One row, or None if this cell cannot be joined to a published result."""
    log = os.path.join(cell_dir, "omb_stdout.log")
    if not os.path.exists(log):
        return None
    text = read_tail(log)

    sm = SUMMARY_RE.findall(text)
    names = RESULT_JSON_RE.findall(text)
    if not sm or not names:
        return None
    kept, zero, neg = (int(x) for x in sm[-1])

    path = os.path.join(os.path.expanduser(omb_dir), names[-1])
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None

    seen = kept + zero + neg
    return {
        "campaign": os.path.basename(os.path.dirname(cell_dir)),
        "cell": os.path.basename(cell_dir),
        "kept": kept, "discarded_zero": zero, "discarded_negative": neg,
        "retention_pct": round(100.0 * kept / seen, 4) if seen else "",
        "omb_p50_ms": last_of(d, "endToEndLatency50pct"),
        "omb_p99_ms": last_of(d, "endToEndLatency99pct"),
        "omb_max_ms": last_of(d, "endToEndLatencyMax"),
        "omb_avg_ms": last_of(d, "endToEndLatencyAvg"),
        "result_json": names[-1],
    }


def collect(root, omb_dir):
    rows = []
    for pattern in ("*/l*_rep*", "*/s*_rep*"):
        for cell in glob.glob(os.path.join(root, pattern)):
            if not os.path.isdir(cell):
                continue
            row = parse_cell(cell, omb_dir)
            if row:
                rows.append(row)
    rows.sort(key=lambda r: (r["campaign"], r["cell"]))
    return rows


def _rank(values):
    """Average ranks, so ties do not bias the correlation."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys):
    """Rank correlation. Returns None when it cannot be computed."""
    pairs = [(x, y) for x, y in zip(xs, ys)
             if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    n = len(pairs)
    if n < 3:
        return None
    rx = _rank([p[0] for p in pairs])
    ry = _rank([p[1] for p in pairs])
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx <= 0 or dy <= 0:
        return None
    return num / (dx * dy) ** 0.5


def report(rows):
    print(f"{'campaign':<14s}{'cell':<12s}{'kept':>9s}{'zero':>9s}{'neg':>5s}"
          f"{'kept %':>9s}{'p50':>6s}{'p99':>6s}{'avg':>9s}")
    for r in rows:
        pct = r["retention_pct"]
        print(f"{r['campaign'][:13]:<14s}{r['cell']:<12s}{r['kept']:>9d}"
              f"{r['discarded_zero']:>9d}{r['discarded_negative']:>5d}"
              f"{('' if pct == '' else f'{pct:.2f}%'):>9s}"
              f"{_s(r['omb_p50_ms']):>6s}{_s(r['omb_p99_ms']):>6s}"
              f"{_s(r['omb_avg_ms'], 4):>9s}")

    if not rows:
        return
    pcts = [r["retention_pct"] for r in rows]
    avgs = [r["omb_avg_ms"] for r in rows]
    p50s = [r["omb_p50_ms"] for r in rows]
    numeric = [p for p in pcts if isinstance(p, (int, float))]
    negs = sum(r["discarded_negative"] for r in rows)

    print()
    if numeric:
        print(f"retention ranges from {min(numeric):.2f}% to {max(numeric):.2f}% "
              f"across {len(rows)} cells")
    distinct_p50 = sorted({v for v in p50s if v is not None})
    print(f"reported p50 takes {len(distinct_p50)} distinct value(s): "
          f"{', '.join(str(v) for v in distinct_p50)}")
    print(f"negative samples across every cell: {negs}")

    rho = spearman(pcts, avgs)
    if rho is not None:
        print(f"\nSpearman(retention, reported average) = {rho:+.3f}")
        if rho < -0.5:
            print("  The reported average rises as retention falls. Discarding everything below")
            print("  one tick removes the fast samples, so the mean is computed over the slow")
            print("  tail: the benchmark reports a higher latency the more data it drops, and")
            print("  reports nothing about having dropped it.")
    return rho


def _s(v, nd=1):
    return "-" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Join OMB cells to their published latency")
    ap.add_argument("--root", default="docs/results/external")
    ap.add_argument("--omb-dir", default="~/omb")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    rows = collect(args.root, args.omb_dir)
    if not rows:
        print(f"no cells under {args.root} could be joined to a published OMB result")
        return 1
    report(rows)

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
