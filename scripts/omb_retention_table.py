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

# OMB's own progress lines carry PUBLISH latency, and unlike the end-to-end figure it is NOT
# quantised to the millisecond grid -- it is measured inside one process, from send to ack, and
# prints to one decimal. That makes it an independent probe of where the path sits relative to a
# tick. If retention really is P(true latency >= one tick), publish latency should predict it,
# using data every run already wrote down.
PUB_LAT_RE = re.compile(r"Pub Latency \(ms\) avg:\s*([\d.]+)\s*-\s*50%:\s*([\d.]+)")
RESULT_JSON_RE = re.compile(r"omb_workload-[A-Za-z]+-[\d-]+\.json")

TAIL_BYTES = 512 * 1024

FIELDS = ("campaign", "cell", "kept", "discarded_zero", "discarded_negative",
          "retention_pct", "omb_p50_ms", "omb_p99_ms", "omb_max_ms", "omb_avg_ms",
          "pub_lat_p50_ms", "pub_lat_avg_ms", "result_json")


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

    # Median of the per-interval publish medians: one number for the run, robust to a slow start.
    pubs = PUB_LAT_RE.findall(text)
    pub_p50 = pub_avg = None
    if pubs:
        p50s = sorted(float(b) for _a, b in pubs)
        avgs = sorted(float(a) for a, _b in pubs)
        pub_p50 = p50s[len(p50s) // 2]
        pub_avg = avgs[len(avgs) // 2]

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
        "pub_lat_p50_ms": pub_p50, "pub_lat_avg_ms": pub_avg,
        "result_json": names[-1],
    }


def collect(root, omb_dir):
    # Any `<something>_rep<n>` directory, rather than an enumerated list of axis prefixes. The
    # rate-phase campaign names its cells r500_rep1, and an enumerated glob silently omitted them
    # -- a whole campaign missing from the table with nothing to indicate it. parse_cell already
    # rejects anything that is not a joinable cell, so the broad glob costs nothing.
    rows = []
    for cell in glob.glob(os.path.join(root, "*", "*_rep*")):
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

    # The independent check: publish latency is sub-millisecond and unquantised, so it can say
    # where the path sits relative to a tick without borrowing the quantised number's assumptions.
    pubs = [r["pub_lat_p50_ms"] for r in rows]
    rho_pub = spearman(pubs, pcts)
    if rho_pub is not None:
        print()
        print(f"Spearman(publish latency p50, retention) = {rho_pub:+.3f}")
        if rho_pub > 0.5:
            print("  Publish latency is measured in one process and is NOT quantised to the")
            print("  millisecond grid. That it predicts retention is independent support for")
            print("  retention being P(true latency >= one tick): the slower the path, the more")
            print("  samples clear a tick and survive the guard.")

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
