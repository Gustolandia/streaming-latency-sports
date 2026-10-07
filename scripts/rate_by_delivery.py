#!/usr/bin/env python3
"""
rate_by_delivery.py
The negative-span rate as a function of the delivery, inside each condition.

Why this exists. The paper's two-state law, eq:occupancy, says that to leading order
Pr[S < 0 | x] ~ p G(x): the chance that a value of S = D - A falls below zero is the waiting
probability times the chance that a residual wait outlasts x. G is a survival function, so when
x is read as D, the end-to-end latency, the law predicts a rate that cannot rise as D grows. A
referee asks for the range in which the law holds. An exploration of 2 September binned each
condition's messages by their own D and found the rate rising rather than falling in many
conditions, but neither its script nor the counts it read were committed, so nobody could check
it. This script makes the same comparison from a committed table and reports what that table
gives.

Two commands, because the raw runs are not in the repository.

    extract   (the author's machine) reads the unpacked raw runs in cloud_archive/extracted/runs/,
              the same 11,955 producer and consumer files that cloud_archive/sbl_runs.tgz holds,
              and writes docs/results/model/rate_by_delivery_counts.csv: for each condition,
              gate verdict and delivery bin, how many messages there were and how many had S < 0.
    analyze   (anywhere) reads only that table and writes docs/results/model/rate_by_delivery.csv.

The population is the corpus behind fig:twoways, message for message. Each run goes through
span_by_condition.consume_run, the function that built span_by_condition.json, so the condition
key and the gate verdict are that script's own. The spans come from recount_spans.join_run, and
a run stops the extraction if they do not hold exactly the messages and negatives consume_run
counted. The table is written only if its sums reproduce span_by_condition.json for every
condition and gate, and the run count with them (5,863 runs and 708,505 messages since 7 Oct
2026, when the late messages of stale_backlog.py were left out).

The bins. d_bin = floor(24 log10(D / 1 us)) over D > 0, so a bin covers 10^(d_bin/24) to
10^((d_bin+1)/24) microseconds. Every message in the corpus has D > 0. Twenty-four per decade is
the smallest count that regroups exactly into the 4, 8 and 12 bins per decade the exploration
used, with edges on whole decades as its bins had (the delivery values it printed are the
centres of eighth-decade bins: 1540 us is 10^(25.5/8)).

The test. For each condition and each binning, separately for the runs that passed the gate,
the runs that failed it, and both pooled, the rate in each bin gets its Wilson 95% interval.
Only bins holding at least MIN_COUNT messages take part, and a condition is testable at a
binning when at least two bins do. A step joins two consecutive bins that take part; it is a
significant rise when the longer-delivery bin's interval lies wholly above the other's. That is
stricter than a two-proportion z test, and it is the test the exploration used. The rise factor
is the ratio of the two rates; a rise out of a bin with no negatives has no finite factor and is
written as inf.

CLI:
    python scripts/rate_by_delivery.py extract     # raw runs -> the counts table
    python scripts/rate_by_delivery.py analyze     # the counts table -> results and summary
"""
import argparse
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recount_spans  # noqa: E402
import stale_backlog  # noqa: E402
import span_by_condition  # noqa: E402
from stat_intervals import wilson  # noqa: E402

RUNS_DIR = os.path.join("cloud_archive", "extracted", "runs")
SPAN_JSON = os.path.join("docs", "results", "span_by_condition.json")
COUNTS_CSV = os.path.join("docs", "results", "model", "rate_by_delivery_counts.csv")
OUT_CSV = os.path.join("docs", "results", "model", "rate_by_delivery.csv")

#: Delivery bins per decade in the committed table: the least common multiple of BINNINGS.
FINE_PER_DECADE = 24
BINNINGS = (4, 8, 12)
GROUPS = ("pass", "fail", "pooled")

#: The fewest messages a bin must hold to take part. It is the smallest count at which the
#: Wilson 95% interval on the corpus's own negative-span rate (62,264 of 738,730 messages,
#: 8.43%, the corpus as counted before the late messages were left out) is narrower than that
#: rate; at 172 the interval runs from 5.1% to 13.5%. A bin with
#: fewer messages cannot place its rate within plus or minus half of it, so it is left out
#: rather than allowed to decide a step. The count was fixed from the corpus-wide rate before
#: any bin's rate was read, and it was not adjusted afterwards. The summary repeats the
#: result at half and at double this minimum, and the tests recompute it from
#: span_by_condition.json.
MIN_COUNT = 172

# "events" and "negatives", not n_events: every n_events column under docs/results/model is
# read as a mechanism cell of 2,985 messages by the paper's denominator gate.
COUNT_FIELDS = ["condition", "gate", "d_bin", "events", "negatives"]
OUT_FIELDS = ["condition", "group", "bins_per_decade", "testable", "bins_used",
              "significant_rise", "largest_rise_factor"]


class Mismatch(RuntimeError):
    """The table would not describe the messages span_by_condition.py counted."""


def delivery_bin(d_ns):
    """floor(24 log10(D / 1 us)) for a delivery of d_ns > 0 nanoseconds, in exact integers.

    d_ns ** 24 has floor(24 log10 d_ns) + 1 decimal digits, and 1 us is 10**3 ns, so the bin is
    that digit count less 1 + 3 * 24. Floating point would give a delivery lying exactly on an
    edge, such as a whole number of milliseconds from a coarse clock, to whichever side the
    rounding fell."""
    return len(str(d_ns ** FINE_PER_DECADE)) - 1 - 3 * FINE_PER_DECADE


def _read_rows(path):
    with open(path, "rb") as fh:
        return recount_spans.parse_rows(fh.read())


def iter_runs(runs_dir):
    """(run_id, producer rows, consumer rows) for every run folder holding both files.

    These are span_by_condition.scan_archive's rules, applied to the unpacked tree: a run is a
    folder under runs/ holding producer.csv and consumer.csv, named by its run id; both files
    are parsed by the same parser; and a run with an empty half is passed over."""
    for run_id in sorted(os.listdir(runs_dir)):
        producer = os.path.join(runs_dir, run_id, "producer.csv")
        consumer = os.path.join(runs_dir, run_id, "consumer.csv")
        if not (os.path.isfile(producer) and os.path.isfile(consumer)):
            continue
        prod, cons = _read_rows(producer), _read_rows(consumer)
        if prod and cons:
            yield run_id, prod, cons


def count_run(run_id, prod, cons, counts):
    """Add one run to counts, {(condition, gate, d_bin): [messages, negatives]}.

    consume_run is called on the run exactly as span_by_condition's own scan calls it, and its
    run row supplies the condition and the gate verdict. Returns the run's message count (0 for
    a run consume_run does not count) and how many of its messages had no D > 0 to bin."""
    run_rows = []
    if not span_by_condition.consume_run({}, run_rows, run_id, prod, cons):
        return 0, 0
    run = run_rows[-1]
    # 7 Oct 2026: the same messages consume_run keeps, the late ones left out by id.
    spans = recount_spans.join_run(prod, cons, skip=stale_backlog.late_ids(prod, cons))
    pairs = list(zip(spans["ack"], spans["send"]))      # (S, D) per message, in ns
    negatives = sum(1 for s, _ in pairs if s < 0)
    if (len(pairs), negatives) != (run["n_events"], run["neg_ack"]):
        raise Mismatch("%s: messages %d here and %d in span_by_condition, negatives %d here "
                       "and %d there" % (run_id, len(pairs), run["n_events"], negatives,
                                         run["neg_ack"]))
    unbinned = 0
    for s, d in pairs:
        if d <= 0:
            unbinned += 1
            continue
        cell = counts.setdefault((run["condition"], run["gate"], delivery_bin(d)), [0, 0])
        cell[0] += 1
        cell[1] += int(s < 0)
    return len(pairs), unbinned


def scan(runs_dir):
    """Count the whole tree. Returns (counts, runs, messages, unbinned)."""
    counts = {}
    runs = messages = unbinned = 0
    saved = dict(span_by_condition.RATIO_HIST)
    try:
        for run_id, prod, cons in iter_runs(runs_dir):
            got, lost = count_run(run_id, prod, cons, counts)
            if got:
                runs += 1
                messages += got
                unbinned += lost
    finally:
        # consume_run also feeds span_by_condition's pooled ratio histogram, which is module
        # state; it is left as it was found.
        span_by_condition.RATIO_HIST.clear()
        span_by_condition.RATIO_HIST.update(saved)
    return counts, runs, messages, unbinned


def json_totals(span):
    """{condition#gate: (messages, negatives)} as span_by_condition.json holds them.

    The negatives are read off its histogram of S: the underflow plus every bin wholly below
    zero, which needs zero to fall on a bin edge."""
    lo, width = span["bin_lo_us"], span["bin_width_us"]
    if (0 - lo) % width:
        raise ValueError("zero is not an edge of span_by_condition.json's bins of S")
    zero = (0 - lo) // width
    out = {}
    for key, cond in span["conditions"].items():
        s = cond["S"]
        out[key] = (s["n"], s["under"] + sum(v for b, v in s["bins"].items() if int(b) < zero))
    return out


def check_totals(counts, span, runs=None):
    """Every difference between the table and span_by_condition.json; empty when they agree."""
    mine = {}
    for (condition, gate, _), (n, neg) in counts.items():
        cell = mine.setdefault("%s#%s" % (condition, gate), [0, 0])
        cell[0] += n
        cell[1] += neg
    theirs = json_totals(span)
    diffs = []
    for key in sorted(set(mine) | set(theirs)):
        here, there = tuple(mine.get(key, (0, 0))), tuple(theirs.get(key, (0, 0)))
        if here != there:
            diffs.append("%s: messages %d here and %d in the JSON, negatives %d here and %d "
                         "in the JSON" % (key, here[0], there[0], here[1], there[1]))
    if runs is not None and runs != span["runs"]:
        diffs.append("runs %d here and %d in the JSON" % (runs, span["runs"]))
    return diffs


def write_counts(counts, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(COUNT_FIELDS)
        for (condition, gate, b), (n, neg) in sorted(counts.items()):
            w.writerow([condition, gate, b, n, neg])


def read_counts(path):
    counts = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            counts[(row["condition"], row["gate"], int(row["d_bin"]))] = (
                int(row["events"]), int(row["negatives"]))
    return counts


def regroup(counts, per_decade):
    """{(condition, group): {bin: [messages, negatives]}} at per_decade bins per decade, for
    each gate verdict and for both pooled. Floor division keeps the edges on whole decades,
    below 1 us as above it."""
    if FINE_PER_DECADE % per_decade:
        raise ValueError("%d bins per decade do not nest in %d" % (per_decade, FINE_PER_DECADE))
    step = FINE_PER_DECADE // per_decade
    out = {}
    for (condition, gate, b), (n, neg) in counts.items():
        for group in (gate, "pooled"):
            cell = out.setdefault((condition, group), {}).setdefault(b // step, [0, 0])
            cell[0] += n
            cell[1] += neg
    return out


def assess(bins, min_count):
    """One condition's bins, {bin: (messages, negatives)}, read for a significant rise.

    Returns (bins_used, rises): how many bins hold at least min_count messages, and the factor
    of every step between consecutive such bins whose longer-delivery interval lies wholly
    above the shorter-delivery one."""
    used = [(n, neg) for _, (n, neg) in sorted(bins.items()) if n >= min_count]
    rises = []
    for (n1, k1), (n2, k2) in zip(used, used[1:]):
        if wilson(k2, n2)[0] > wilson(k1, n1)[1]:
            rises.append((k2 / n2) / (k1 / n1) if k1 else math.inf)
    return len(used), rises


def analyze(counts, min_count=MIN_COUNT):
    """One result per condition, group and binning, ordered for reading."""
    rows = []
    for per_decade in BINNINGS:
        for (condition, group), bins in regroup(counts, per_decade).items():
            used, rises = assess(bins, min_count)
            rows.append({"condition": condition, "group": group,
                         "bins_per_decade": per_decade, "testable": int(used >= 2),
                         "bins_used": used, "significant_rise": int(bool(rises)),
                         "largest_rise_factor": max(rises) if rises else None})
    rows.sort(key=lambda r: (r["condition"], GROUPS.index(r["group"]), r["bins_per_decade"]))
    return rows


def result_fields(row):
    """A result as the strings its CSV row holds."""
    factor = row["largest_rise_factor"]
    return [row["condition"], row["group"], str(row["bins_per_decade"]), str(row["testable"]),
            str(row["bins_used"]), str(row["significant_rise"]),
            "" if factor is None else "%.3f" % factor]


def write_results(rows, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(OUT_FIELDS)
        for row in rows:
            w.writerow(result_fields(row))


def summarize(rows):
    """{(bins_per_decade, group): conditions, testable, rising and the largest rise of each
    rising condition}."""
    table = {}
    for row in rows:
        s = table.setdefault((row["bins_per_decade"], row["group"]),
                             {"conditions": 0, "testable": 0, "rising": 0, "factors": []})
        s["conditions"] += 1
        s["testable"] += row["testable"]
        s["rising"] += row["significant_rise"]
        if row["largest_rise_factor"] is not None:
            s["factors"].append(row["largest_rise_factor"])
    return table


def factor_range(factors):
    """The range of the conditions' largest rises, with any infinite one counted beside it."""
    if not factors:
        return "none"
    finite = sorted(f for f in factors if not math.isinf(f))
    parts = []
    if finite:
        parts.append("%.2fx to %.2fx" % (finite[0], finite[-1]))
    if len(finite) < len(factors):
        parts.append("%d from a bin with no negatives" % (len(factors) - len(finite)))
    return "; ".join(parts)


EMPTY = {"conditions": 0, "testable": 0, "rising": 0, "factors": []}


def summary_lines(rows, min_count=MIN_COUNT):
    table = summarize(rows)
    lines = ["minimum %d messages per bin; a rise counts when the longer-delivery bin's Wilson "
             "95%% interval lies wholly above the bin before it" % min_count,
             "%-9s %-7s %10s %9s %7s  %s" % ("binning", "group", "conditions", "testable",
                                            "rising", "largest rise per rising condition")]
    for per_decade in BINNINGS:
        for group in GROUPS:
            s = table.get((per_decade, group), EMPTY)
            lines.append("%-9s %-7s %10d %9d %7d  %s" % (
                "%d/decade" % per_decade, group, s["conditions"], s["testable"], s["rising"],
                factor_range(s["factors"])))
    return lines


def sensitivity_line(rows, min_count):
    """Rising over testable conditions at every binning and group, on one line."""
    table = summarize(rows)
    parts = []
    for per_decade in BINNINGS:
        cells = []
        for group in GROUPS:
            s = table.get((per_decade, group), EMPTY)
            cells.append("%s %d/%d" % (group, s["rising"], s["testable"]))
        parts.append("%d/decade %s" % (per_decade, ", ".join(cells)))
    return "sensitivity, minimum %d (rising/testable): %s" % (min_count, "; ".join(parts))


def extract(runs_dir, span_json, out):
    if not os.path.isdir(runs_dir):
        print("STOP: no unpacked runs at %s; `tar -xzf cloud_archive/sbl_runs.tgz -C "
              "cloud_archive/extracted` puts them there" % runs_dir)
        return 1
    try:
        counts, runs, messages, unbinned = scan(runs_dir)
    except Mismatch as exc:
        print("STOP: %s" % exc)
        return 1
    with open(span_json, encoding="utf-8") as fh:
        span = json.load(fh)
    diffs = check_totals(counts, span, runs)
    if unbinned:
        diffs.insert(0, "messages with no delivery above zero to bin: %d" % unbinned)
    if diffs:
        print("STOP: the table does not reproduce %s, so it was not written:" % span_json)
        for diff in diffs:
            print("  " + diff)
        return 1
    write_counts(counts, out)
    print("runs %d, messages %d, negatives %d, condition and gate keys %d: every key's messages "
          "and negatives equal %s" % (runs, messages, sum(neg for _, neg in counts.values()),
                                      len({key[:2] for key in counts}), span_json))
    print("wrote %s (%d rows)" % (out, len(counts)))
    return 0


def analyze_command(counts_path, out):
    counts = read_counts(counts_path)
    rows = analyze(counts)
    write_results(rows, out)
    for line in summary_lines(rows):
        print(line)
    for min_count in (MIN_COUNT // 2, MIN_COUNT * 2):
        print(sensitivity_line(analyze(counts, min_count), min_count))
    print("wrote %s (%d rows)" % (out, len(rows)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="The negative-span rate by delivery bin, inside each condition")
    sub = ap.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="raw runs to the committable counts table")
    ex.add_argument("--runs-dir", default=RUNS_DIR)
    ex.add_argument("--span-json", default=SPAN_JSON)
    ex.add_argument("--out", default=COUNTS_CSV)
    an = sub.add_parser("analyze", help="the counts table to the results and the summary")
    an.add_argument("--counts", default=COUNTS_CSV)
    an.add_argument("--out", default=OUT_CSV)
    args = ap.parse_args(argv)
    if args.command == "extract":
        return extract(args.runs_dir, args.span_json, args.out)
    return analyze_command(args.counts, args.out)


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
