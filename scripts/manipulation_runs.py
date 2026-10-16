#!/usr/bin/env python3
"""
manipulation_runs.py
Intervals that resample whole runs, for the manipulations and the traced cells, on both brokers.

Why this exists. Supplement S3.1-S3.3 give each manipulation's negative-span rates per cell of
2,985 messages, with Wilson intervals on the rates and Katz intervals on the factors between
them. Both intervals treat the messages as independent draws. They are not: the supplement's own
runs test shows that values of S below zero cluster within a run, and in the real-time cells
the clustering is extreme -- most runs hold none and a few hold several. A referee asked for
intervals that resample whole runs instead, the treatment `analyze_collapse.run_intervals`
already gives the reproduction comparison. Every one of these campaigns also ran both brokers,
25 runs each per cell, while the committed rates are the Kafka halves alone (condition_stats
reads Kafka unless told otherwise); this file carries both.

Two halves, in the repository's usual pattern (see span_by_condition.py):

  extract   walks the cells in the archived runs and writes one row per run to
            docs/results/model/manipulation_run_counts.csv: the run's broker, its matched events
            and how many of them have S < 0, by the join and the comparison condition_stats()
            uses for the negative-span rate. It writes nothing unless two committed records
            agree with it: the Kafka half of every cell must sum to the totals its analysis
            committed, and every run of either broker must carry the counts
            docs/results/span_run_level.csv gives it, with no run missing or added.
  report    reads only that file and prints every interval, per broker, beside the Wilson and
            Katz intervals the same pooled counts give.

Which cells, by result:

  priority   every matched pair the range in the main text is built from
             (`priority_pairs.usable`), a normal-priority cell l<load>_base and a real-time cell
             l<load>_rt of E-A5, E-A5b or E-A7.
  placement  the k = 6 cells, concentrated and spread, of E-A6 and its replication E-A6b, which
             `stat_intervals.geometry_cells` reads; since 15 Oct 2026 the k = 5 and k = 7
             cells too, which the supplement's placement table prints a z for.
  path       the four padding levels of E-A10 and of its repeat E-A10b. `payload_span` takes the
             fall as the level with the highest pooled rate over the level with the lowest.
  trace      the kernel-traced pairs, E-A9 at 88% load and E-A9b at 75% and 88%, and E-A9's
             untraced twin, whose probe failed. Their runs are named by timestamp in TRACE_CELLS
             rather than read from the cell folders, which the committed tree keeps without the
             concurrency subdirectory that names them.
  ladder     the two ends of E-A3's load ladder, idle (bg0) and the knee (bg7), between which
             `stat_intervals.load_growth` takes the growth of the rate.
  load       every cell of E-A3's ladder, at normal priority (15 Oct 2026), for the per-run
             rates the paper's Fig. 2 draws against utilization (`rate_by_load`). No interval
             is taken from them.
  colocation E-A8, the co-located control (15 Oct 2026): idle and at 88% load, the brokers on
             a broker machine (remote) and on the client machine itself (co-located). The
             paper and Supplement S1 count its runs per broker; no interval is taken from them.

A third table, `floor`, needs the archive too: for every run of the priority pairs' real-time
cells, on both brokers, where in the run each value of S below zero sits (its rank by publish
time) and how long the run waited for its first acknowledgment (15 Oct 2026). It is checked
against the run file and written to docs/results/model/rt_floor_runs.csv.

The bootstrap. Each arm's runs are resampled with replacement, independently of the other
arm's, and each resample pools its runs: negatives over events. Pooling both brokers resamples
each broker's runs within that broker, as the campaign ran them, 25 and 25. The 95% interval is
the percentile one, with as many draws below its lower end as above its upper end. Each
comparison draws from its own stream -- the seed plus a checksum of the comparison's name and
broker, as in analyze_collapse -- so adding a comparison moves no other interval.

A factor is unbounded in a resample whose lower arm drew no value below zero. Those draws are
counted and kept: when more of them than one tail's share fall at the top, the interval's upper
end is unbounded (math.inf), and the count says how often it happened. A resample in which both
arms are zero defines no factor at all. It is counted too, and placed at whichever end widens
the interval -- at zero for the lower end, unbounded for the upper -- so that no value it might
have taken could give a wider interval than the one reported. An arm in which no run holds a
value below zero gets no interval, and neither does a factor taken from it, for the reason
`run_intervals` gives: every resample of zeros is zero, and a zero-width interval would claim a
certainty the runs do not give. The report prints Wilson's interval there, which does bound a
zero.

CLI:
    python scripts/manipulation_runs.py extract     # needs cloud_archive/extracted
    python scripts/manipulation_runs.py report      # reads only the committed file
"""
import argparse
import csv
import glob
import math
import os
import random
import re
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import priority_pairs  # noqa: E402
import stat_intervals  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(REPO, "docs", "results", "model")
RUNS_CSV = os.path.join(MODEL, "manipulation_run_counts.csv")
SPAN_CSV = os.path.join(REPO, "docs", "results", "span_run_level.csv")
ARCHIVE = os.path.join(REPO, "cloud_archive", "extracted")
DEPTH = os.path.join(ARCHIVE, "docs", "results", "depth")
RUNS = os.path.join(ARCHIVE, "runs")

#: Both brokers every one of these campaigns ran. "both" pools them.
BACKENDS = ("kafka", "redis")
RESULTS = ("priority", "placement", "path", "trace", "ladder", "load", "colocation")
#: A run's counts are `run_events` and `run_negatives`, not n_events: every `n_events` column
#: under docs/results/model is a cell's denominator, and a gate holds each of them to 2,985.
FIELDS = ["result", "campaign", "phase", "cell", "arm", "backend", "run", "run_events",
          "run_negatives"]
RUN_ID = re.compile(r"^concurrency_(n\d+_\d{8}_\d{6})_(kafka|redis)_")

#: The results folder each priority campaign's cells sit in, beside the file
#: `priority_pairs.CAMPAIGNS` names for its committed totals.
PRIORITY_PHASES = {"E-A5": "ea5", "E-A5b": "ea5b", "E-A7": "ea7"}
#: (cell suffix, arm, rate column, events column) in the committed priority files.
PRIORITY_ARMS = (("base", "normal", "inv_base", "n_base"), ("rt", "real-time", "inv_rt", "n_rt"))
PLACEMENT = (("E-A6", "ea6"), ("E-A6b", "ea6b"))
#: The two cells `stat_intervals.geometry_cells` compares, and what each placement is.
PLACEMENT_ARMS = (("k6_conc", "concentrated"), ("k6_spread", "spread"))
#: 15 Oct 2026: the supplement's placement table prints a z at k = 5 and k = 7 as well, a
#: test that treats messages as independent (both referees, S8). The runs of those cells are
#: counted too, so each row can carry an interval that resamples whole runs; the k = 6 pair
#: keeps its own name above, which the paper's figures and macros read.
PLACEMENT_LEVELS = ("k5", "k6", "k7")
#: 15 Oct 2026: E-A3's whole load ladder, every cell at normal priority, so that the per-run
#: rate can be drawn against the client machine's utilization on both brokers (referee B, Fig.
#: 2). The ladder's two ends, idle and the knee, are the `ladder` result above.
LOAD = ("E-A3", "ea3", ("bg0", "bg2", "bg4", "bg5", "bg6", "bg7", "bg8", "bg10", "bg12"))
#: 15 Oct 2026: E-A8, the co-located control, as (campaign, results folder, committed file,
#: loads). Each load has a remote cell and a co-located one; the committed file gives each arm's
#: Kafka events and rate, which the Kafka halves must reproduce.
COLOCATION = ("E-A8", "ea8", "colocation.csv", ("0", "88"))
COLOCATION_ARMS = (("remote", "remote", "n_remote", "inv_remote"),
                   ("colocated", "co-located", "n_colocated", "inv_colocated"))
#: (campaign, results folder, committed sweep file under docs/results/model).
PATH = (("E-A10", "ea10", ("ttrue_sweep.csv",)),
        ("E-A10b", "ea10b", ("ea10b", "ttrue_sweep.csv")))
#: (campaign, results folder, cell, arm, run-id timestamp, committed file under the model
#: folder). The Kafka halves must reproduce the inversion column of runq_tail.csv and the
#: counts of the untraced control.
TRACE_CELLS = (
    ("E-A9", "ea9", "l88_base", "normal", "n5_20260725_205720", ("runq_tail.csv",)),
    ("E-A9", "ea9", "l88_rt", "real-time", "n5_20260725_211526", ("runq_tail.csv",)),
    ("E-A9-untraced", "ea9_notrace", "l88_base", "normal", "n5_20260725_190710",
     ("ea9_notrace", "untraced_control.csv")),
    ("E-A9-untraced", "ea9_notrace", "l88_rt", "real-time", "n5_20260725_192514",
     ("ea9_notrace", "untraced_control.csv")),
    ("E-A9b", "ea9b", "l75_base", "normal", "n5_20260726_015949", ("ea9b_l75", "runq_tail.csv")),
    ("E-A9b", "ea9b", "l75_rt", "real-time", "n5_20260726_021754", ("ea9b_l75", "runq_tail.csv")),
    ("E-A9b", "ea9b", "l88_base", "normal", "n5_20260726_023645", ("ea9b_l88", "runq_tail.csv")),
    ("E-A9b", "ea9b", "l88_rt", "real-time", "n5_20260726_025451", ("ea9b_l88", "runq_tail.csv")),
)
#: The cells `stat_intervals.load_growth` divides, as (campaign, folder, cell, arm).
LADDER = (("E-A3", "ea3", "bg0", "idle"), ("E-A3", "ea3", "bg7", "knee"))

#: Resamples behind every interval, and the seed they start from: analyze_collapse's count, and
#: a seed of this file's own.
BOOT_DRAWS = 20000
BOOT_SEED = 20261006
CONF = 0.95


# ---------------------------------------------------------------- the cells and their totals
def _read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _counted(model_dir, parts, phase, cell):
    """A cell's committed totals from a file that names cells by "condition" or "tag".

    knee_resolution and the untraced control carry exact counts and a run count; runq_tail
    carries a rate and its denominator, whose product, rounded, is the count. A "phase" column,
    where there is one, must match: the pooled knee file names bg0 in two campaigns.
    """
    for r in _read_csv(os.path.join(model_dir, *parts)):
        if r.get("condition", r.get("tag")) == cell and r.get("phase", phase) == phase:
            n = int(r["n_events"])
            if "n_inversions" in r:
                return {"n_events": n, "n_negative": int(r["n_inversions"]),
                        "n_runs": int(r["n_runs"])}
            return {"n_events": n, "n_negative": round(float(r["inversion"]) * n),
                    "n_runs": None}
    raise KeyError("%s has no row for %s/%s" % (os.path.join(*parts), phase, cell))


def cells(model_dir=MODEL):
    """Every cell, with the totals its committed analysis reports for its Kafka half.

    Returns [(result, campaign, phase, cell, arm, committed, timestamp)]: `committed` is
    {"n_events", "n_negative", "n_runs"}, with "n_runs" None where the file records no run
    count, and `timestamp` names the cell's runs where the cell folder cannot (TRACE_CELLS),
    else None.
    """
    out = []
    for campaign, filename in priority_pairs.CAMPAIGNS:
        for r in _read_csv(os.path.join(model_dir, filename)):
            if str(r.get("confounded")) == "True":
                continue        # withheld by the campaign's own rule; see priority_pairs.usable
            for suffix, arm, rate, events in PRIORITY_ARMS:
                n = int(r[events])
                out.append(("priority", campaign, PRIORITY_PHASES[campaign],
                            "%s_%s" % (r["level"], suffix), arm,
                            {"n_events": n, "n_negative": round(float(r[rate]) * n),
                             "n_runs": None}, None))
    for campaign, phase in PLACEMENT:
        for level in PLACEMENT_LEVELS:
            for cell, arm in PLACEMENT_ARMS:
                cell = cell.replace("k6", level)
                out.append(("placement", campaign, phase, cell, arm,
                            _counted(model_dir, (phase, "knee_resolution.csv"), phase, cell),
                            None))
    for campaign, phase, parts in PATH:
        for r in _read_csv(os.path.join(model_dir, *parts)):
            n = int(r["n_events"])
            out.append(("path", campaign, phase, "pad%s" % r["pad_bytes"], r["pad_bytes"],
                        {"n_events": n, "n_negative": round(float(r["inversion"]) * n),
                         "n_runs": None}, None))
    for campaign, phase, cell, arm, stamp, parts in TRACE_CELLS:
        out.append(("trace", campaign, phase, cell, arm,
                    _counted(model_dir, parts, phase, cell), stamp))
    for campaign, phase, cell, arm in LADDER:
        out.append(("ladder", campaign, phase, cell, arm,
                    _counted(model_dir, ("knee_resolution.csv",), phase, cell), None))
    campaign, phase, ladder = LOAD
    for cell in ladder:
        out.append(("load", campaign, phase, cell, "normal",
                    _counted(model_dir, ("knee_resolution.csv",), phase, cell), None))
    campaign, phase, filename, loads = COLOCATION
    committed = {r["load"]: r for r in _read_csv(os.path.join(model_dir, filename))}
    for load in loads:
        for placement, arm, events, rate in COLOCATION_ARMS:
            n = int(committed[load][events])
            out.append(("colocation", campaign, phase, "%s_l%s" % (placement, load), arm,
                        {"n_events": n, "n_negative": round(float(committed[load][rate]) * n),
                         "n_runs": None}, None))
    return out


def _stamp(run):
    m = RUN_ID.match(run)
    return m.group(1) if m else None


def check(rows, model_dir=MODEL, span_csv=SPAN_CSV):
    """Every way the per-run rows disagree with the two committed records, as sentences.

    The Kafka half of each cell must sum to its committed events and negatives, and to its run
    count where the file has one. Every row, of either broker, must carry the counts
    span_run_level.csv gives its run; each cell's runs must come from one timestamp, and for
    each broker they must be exactly the runs span_run_level.csv holds under it. A row that
    belongs to no cell is named too. An empty list is agreement.
    """
    span = {r["run_id"]: (int(r["n_events"]), int(r["neg_ack"])) for r in _read_csv(span_csv)}
    out, groups = [], {}
    for r in rows:
        groups.setdefault((r["result"], r["campaign"], r["phase"], r["cell"], r["arm"]),
                          []).append(r)
        mine = (int(r["run_events"]), int(r["run_negatives"]))
        if span.get(r["run"]) != mine:
            out.append("%s: %d events, %d with S < 0; span_run_level.csv has %s"
                       % ((r["run"],) + mine + (span.get(r["run"], "no such run"),)))
    wanted = set()
    for result, campaign, phase, cell, arm, c, _stamped in cells(model_dir):
        key = (result, campaign, phase, cell, arm)
        wanted.add(key)
        mine = groups.get(key, [])
        kafka = [r for r in mine if r["backend"] == "kafka"]
        runs = len(kafka)
        n = sum(int(r["run_events"]) for r in kafka)
        k = sum(int(r["run_negatives"]) for r in kafka)
        where = "%s %s/%s (%s)" % (campaign, phase, cell, arm)
        if (n, k) != (c["n_events"], c["n_negative"]) or c["n_runs"] not in (None, runs):
            out.append("%s: Kafka %d runs, %d events, %d with S < 0; the committed analysis "
                       "has %s runs, %d events, %d with S < 0"
                       % (where, runs, n, k, "?" if c["n_runs"] is None else c["n_runs"],
                          c["n_events"], c["n_negative"]))
        stamps = {_stamp(r["run"]) for r in mine}
        if len(stamps) != 1 or None in stamps:
            out.append("%s: runs from %d timestamps, not one" % (where, len(stamps)))
            continue
        stamp = stamps.pop()
        for backend in BACKENDS:
            have = sorted(r["run"] for r in mine if r["backend"] == backend)
            prefix = "concurrency_%s_%s_" % (stamp, backend)
            held = sorted(run for run in span if run.startswith(prefix))
            if have != held:
                out.append("%s: %d %s runs; span_run_level.csv holds %d under %s"
                           % (where, len(have), backend, len(held), prefix))
    for key in sorted(set(groups) - wanted):
        out.append("%s %s %s/%s (%s): in the run file, behind none of the results" % key)
    return out


# ---------------------------------------------------------------- extract (needs the archive)
def run_counts(cell_dir, runs_dir, backend="kafka", stamp=None):
    """[(run id, run_events, run_negatives)] for one cell and broker, in run-id order.

    The runs are the ones condition_stats() pools: the cell's run-id timestamp (`stamp`, or
    the one its concurrency subdirectory carries) names them, and a run counts only if it
    yields matched events. Each run's spans come from `analyze_collapse.run_series`, and a span
    counts as negative by the comparison behind the rate the analyses report (`tails[0.0]`,
    S < -0.0).
    """
    # Imported here, not at the top: analyze_collapse brings numpy and pandas with it, and the
    # functions that read the committed file are called from the ledger.
    from analyze_collapse import condition_timestamp, run_series
    stamp = stamp or condition_timestamp(cell_dir)
    if not stamp:
        return []
    out = []
    pattern = os.path.join(runs_dir, "concurrency_%s_%s_*" % (stamp, backend))
    for run in sorted(glob.glob(pattern)):
        series = run_series(run)
        if series:
            out.append((os.path.basename(run), len(series), sum(1 for t in series if t < -0.0)))
    return out


def extract(depth_dir=DEPTH, runs_dir=RUNS, model_dir=MODEL):
    """One row of FIELDS per run, for every cell and both brokers."""
    rows = []
    for result, campaign, phase, cell, arm, _committed, stamp in cells(model_dir):
        for backend in BACKENDS:
            for run, n, k in run_counts(os.path.join(depth_dir, phase, cell), runs_dir,
                                        backend, stamp):
                rows.append({"result": result, "campaign": campaign, "phase": phase,
                             "cell": cell, "arm": arm, "backend": backend, "run": run,
                             "run_events": n, "run_negatives": k})
    return rows


def write(rows, out=RUNS_CSV):
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return out


#: The cell whose median S estimates each broker's margin, and the file it is written to.
MARGIN_CELL = ("E-A3", "ea3", "bg0")
MARGINS_CSV = os.path.join(MODEL, "broker_margins.csv")
MARGIN_FIELDS = ["campaign", "phase", "cell", "backend", "rho", "n_events", "median_s_ms"]


def margins(depth_dir=DEPTH, runs_dir=RUNS, cell=MARGIN_CELL):
    """Each broker's margin, estimated as its median S in E-A3's idle cell (15 Oct 2026).

    The kernel-trace check compares the share of waits longer than the margin with the rate,
    and it used one threshold for both brokers, 0.5 ms, "our estimate of the margin". That
    number was first written on 25 Jul 2026 as the broker transport, "around 0.5 ms", a
    rounding of Kafka's median S at low load: analyze_collapse reads Kafka unless told
    otherwise, and E-A3's idle cell gives 0.52 ms. With no background load a thread rarely
    waits, so the median of S there is the margin S would equal with no wait at all. Both
    referees asked for each broker's own (A M6(a); B m6). The same rule on Redis's runs.
    """
    from analyze_collapse import condition_stats
    campaign, phase, name = cell
    out = []
    for backend in BACKENDS:
        s = condition_stats(os.path.join(depth_dir, phase, name), runs_dir, backend=backend)
        if s is None:
            raise ValueError("%s/%s holds no usable %s runs" % (phase, name, backend))
        out.append({"campaign": campaign, "phase": phase, "cell": name, "backend": backend,
                    "rho": "%.4f" % s["rho"], "n_events": s["n_events"],
                    "median_s_ms": "%.4f" % s["mu"]})
    return out


#: The padding campaign's medians of A, D and S per padding level and broker.
PADDING_CSV = os.path.join(MODEL, "padding_spans.csv")
PADDING_FIELDS = ["campaign", "phase", "cell", "pad_bytes", "backend", "n_events",
                  "median_a_ms", "median_d_ms", "median_s_ms"]


def run_spans(run_dir):
    """[(A, D, S)] in milliseconds for every message of one run, by run_series's join.

    The same producer and consumer files, the same timestamps and the same late messages left
    out as `analyze_collapse.run_series`, which gives S alone; here the publish timestamp is
    kept too, so A = t_ack - t_pub and D = t_recv - t_pub sit beside S = t_recv - t_ack.
    """
    import stale_backlog
    prod = os.path.join(run_dir, "producer.csv")
    cons = os.path.join(run_dir, "consumer_events.csv")
    if not (os.path.exists(prod) and os.path.exists(cons)):
        return []
    late = stale_backlog.late_ids_in(run_dir)
    sent = {}
    for r in _read_csv(prod):
        if r.get("t_broker_ack_ns") not in (None, "", "None"):
            sent[r["event_id"]] = (int(r["t_prod_send_ns"]), int(r["t_broker_ack_ns"]))
    out = []
    for r in _read_csv(cons):
        s = sent.get(r["event_id"])
        if s is None or r.get("t_consume_ns") in (None, "", "None") or r["event_id"] in late:
            continue
        recv = int(r["t_consume_ns"])
        out.append(((s[1] - s[0]) / 1e6, (recv - s[0]) / 1e6, (recv - s[1]) / 1e6))
    return out


def padding_spans(depth_dir=DEPTH, runs_dir=RUNS, model_dir=MODEL):
    """The medians of A, D and S at each padding level of E-A10 and E-A10b, on both brokers.

    15 Oct 2026, referee A (m25): the paper's Fig. 6 draws A/D for one path at a fixed publish
    latency and none of its points tests that 1/D. The referee proposed the padding campaign as
    that evidence, load held and the publish latency nearly held while the end-to-end latency
    grows. The medians say otherwise on Kafka: there the publish latency grows with the payload
    almost as fast as the end-to-end latency, 2.5 to 128 ms against 3.1 to 173 ms, so A/D stays
    near three quarters; on Redis it grows 3.6-fold against 4.7. One row per campaign, padding
    level and broker, over the runs `run_counts` counts for the cell.
    """
    import statistics
    from analyze_collapse import condition_timestamp
    out = []
    for campaign, phase, parts in PATH:
        for r in _read_csv(os.path.join(model_dir, *parts)):
            cell = "pad%s" % r["pad_bytes"]
            stamp = condition_timestamp(os.path.join(depth_dir, phase, cell))
            for backend in BACKENDS:
                spans = [s for run in sorted(glob.glob(os.path.join(
                    runs_dir, "concurrency_%s_%s_*" % (stamp, backend)))) for s in run_spans(run)]
                if not spans:
                    raise ValueError("%s %s holds no %s messages" % (campaign, cell, backend))
                out.append({"campaign": campaign, "phase": phase, "cell": cell,
                            "pad_bytes": r["pad_bytes"], "backend": backend,
                            "n_events": len(spans),
                            "median_a_ms": "%.4f" % statistics.median(a for a, _, _ in spans),
                            "median_d_ms": "%.4f" % statistics.median(d for _, d, _ in spans),
                            "median_s_ms": "%.4f" % statistics.median(s for _, _, s in spans)})
    return out


def check_padding(rows, model_dir=MODEL, runs_csv=RUNS_CSV):
    """Every way the padding medians disagree with the committed records, as sentences.

    Kafka's median S must be the transport the sweep files committed, and each cell's message
    count must be the one the run file gives it on its broker.
    """
    out = []
    counts = {}
    for r in read_runs(runs_csv):
        if r["result"] == "path":
            key = (r["campaign"], r["cell"], r["backend"])
            counts[key] = counts.get(key, 0) + r["run_events"]
    transport = {}
    for campaign, _phase, parts in PATH:
        for r in _read_csv(os.path.join(model_dir, *parts)):
            transport[(campaign, "pad%s" % r["pad_bytes"])] = float(r["transport_ms"])
    for r in rows:
        where = "%s %s %s" % (r["campaign"], r["cell"], r["backend"])
        if counts.get((r["campaign"], r["cell"], r["backend"])) != r["n_events"]:
            out.append("%s: %d messages; the run file has %s" % (
                where, r["n_events"], counts.get((r["campaign"], r["cell"], r["backend"]))))
        if r["backend"] == "kafka" and abs(float(r["median_s_ms"]) - transport[
                (r["campaign"], r["cell"])]) > 5e-5:
            out.append("%s: median S %s ms; the sweep committed %.6f" % (
                where, r["median_s_ms"], transport[(r["campaign"], r["cell"])]))
    return out


def write_padding(rows, out=PADDING_CSV):
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PADDING_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return out


def read_padding(path=PADDING_CSV):
    """The committed padding medians, numbers as floats."""
    rows = []
    for r in _read_csv(path):
        r = dict(r)
        for k in ("median_a_ms", "median_d_ms", "median_s_ms"):
            r[k] = float(r[k])
        rows.append(r)
    return rows


def write_margins(rows, out=MARGINS_CSV):
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=MARGIN_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return out


def read_margins(path=MARGINS_CSV):
    """{backend: margin in ms} from the committed file."""
    return {r["backend"]: float(r["median_s_ms"]) for r in _read_csv(path)}


# ---------------------------------------------------------------- the real-time floor
#: Where in its run each value of S below zero sits, for every run of the priority pairs'
#: real-time cells on both brokers (15 Oct 2026).
RT_FLOOR_CSV = os.path.join(MODEL, "rt_floor_runs.csv")
RT_FLOOR_FIELDS = ["campaign", "phase", "cell", "backend", "run", "run_events", "run_negatives",
                   "ranks", "first_instant", "first_ack_ms"]


def run_ranks(run_dir):
    """(matched events, ranks, first instant, first acknowledgment in ms) for one run.

    A message's rank is its place among the run's acknowledged messages by publish time, the
    first published being 1, and `ranks` are those of the messages with S < 0, by run_series's
    join with the late messages left out. `first instant` counts the messages the replay
    published at its first simulated instant, the smallest t_sim_seconds; the first
    acknowledgment is timed from the run's first publish. A run that left no table, or no
    acknowledged message, gives (0, [], 0, None).
    """
    import stale_backlog
    prod = os.path.join(run_dir, "producer.csv")
    cons = os.path.join(run_dir, "consumer_events.csv")
    if not (os.path.exists(prod) and os.path.exists(cons)):
        return 0, [], 0, None
    sent = {}
    for i, r in enumerate(_read_csv(prod)):
        if r.get("t_broker_ack_ns") not in (None, "", "None"):
            sent[r["event_id"]] = (int(r["t_prod_send_ns"]), i, int(r["t_broker_ack_ns"]),
                                   float(r["t_sim_seconds"]))
    if not sent:
        return 0, [], 0, None
    rank = {e: k + 1 for k, e in enumerate(sorted(sent, key=lambda e: sent[e][:2]))}
    start = min(v[3] for v in sent.values())
    first_instant = sum(1 for v in sent.values() if v[3] == start)
    first_ack = (min(v[2] for v in sent.values()) - min(v[0] for v in sent.values())) / 1e6
    late = stale_backlog.late_ids_in(run_dir)
    n, ranks = 0, []
    for r in _read_csv(cons):
        v = sent.get(r["event_id"])
        if v is None or r.get("t_consume_ns") in (None, "", "None") or r["event_id"] in late:
            continue
        n += 1
        if int(r["t_consume_ns"]) - v[2] < 0:
            ranks.append(rank[r["event_id"]])
    return n, sorted(ranks), first_instant, first_ack


def rt_floor(depth_dir=DEPTH, runs_dir=RUNS, model_dir=MODEL):
    """One row per run of the priority pairs' real-time cells, on both brokers (15 Oct 2026).

    Both referees asked what sets the real-time floor, the rate that stays above zero with the
    thread at real-time priority. On Kafka every such value is one of a run's first few
    messages, the ones the replay publishes at its first instant, which wait about a tenth of a
    second or more for the first acknowledgment; on Redis they are spread through the run. The
    runs are the ones `run_counts` counts for each cell.
    """
    from analyze_collapse import condition_timestamp
    out = []
    for result, campaign, phase, cell, arm, _committed, stamp in cells(model_dir):
        if result != "priority" or arm != "real-time":
            continue
        stamp = stamp or condition_timestamp(os.path.join(depth_dir, phase, cell))
        for backend in BACKENDS:
            for run in sorted(glob.glob(os.path.join(runs_dir,
                                                     "concurrency_%s_%s_*" % (stamp, backend)))):
                n, ranks, first_instant, first_ack = run_ranks(run)
                if n:
                    out.append({"campaign": campaign, "phase": phase, "cell": cell,
                                "backend": backend, "run": os.path.basename(run),
                                "run_events": n, "run_negatives": len(ranks),
                                "ranks": " ".join(str(k) for k in ranks),
                                "first_instant": first_instant,
                                "first_ack_ms": "%.1f" % first_ack})
    return out


def check_rt_floor(rows, runs_csv=RUNS_CSV):
    """Every way the floor rows disagree with the run file, as sentences: each run must carry the
    events and negatives the run file gives it, and every real-time priority run must be here."""
    committed = {r["run"]: r for r in read_runs(runs_csv)
                 if r["result"] == "priority" and r["arm"] == "real-time"}
    out, have = [], set()
    for r in rows:
        have.add(r["run"])
        c = committed.get(r["run"])
        mine = (r["run_events"], r["run_negatives"])
        if c is None:
            out.append("%s: no real-time priority run of that name in the run file" % r["run"])
        elif (c["run_events"], c["run_negatives"]) != mine:
            out.append("%s: %d events, %d with S < 0; the run file has %d and %d"
                       % ((r["run"],) + mine + (c["run_events"], c["run_negatives"])))
    out += ["%s: in the run file, not among the floor's runs" % run
            for run in sorted(set(committed) - have)]
    return out


def write_rt_floor(rows, out=RT_FLOOR_CSV):
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RT_FLOOR_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return out


def read_rt_floor(path=RT_FLOOR_CSV):
    """The committed floor rows, with the ranks as a list of ints and the times as floats."""
    rows = []
    for r in _read_csv(path):
        r = dict(r)
        r["ranks"] = [int(k) for k in r["ranks"].split()]
        for key in ("run_events", "run_negatives", "first_instant"):
            r[key] = int(r[key])
        r["first_ack_ms"] = float(r["first_ack_ms"])
        rows.append(r)
    return rows


# ---------------------------------------------------------------- the committed file
def read_runs(path=RUNS_CSV):
    """The committed rows, with the two counts as integers."""
    rows = []
    for r in _read_csv(path):
        r = dict(r)
        r["run_events"], r["run_negatives"] = int(r["run_events"]), int(r["run_negatives"])
        rows.append(r)
    return rows


def _arms(rows, result, key, backend):
    """{group: {arm: [stratum, ...]}} for one result, where a stratum is one broker's runs as
    (run_events, run_negatives) pairs: one stratum for a broker, two when `backend` is
    "both"."""
    if backend not in BACKENDS + ("both",):
        raise ValueError("backend must be kafka, redis or both, not %r" % backend)
    wanted = BACKENDS if backend == "both" else (backend,)
    found = {}
    for r in rows:
        if r["result"] == result and r["backend"] in wanted:
            found.setdefault(key(r), {}).setdefault(r["arm"], {}).setdefault(
                r["backend"], []).append((r["run_events"], r["run_negatives"]))
    return {g: {arm: [by[b] for b in wanted if b in by] for arm, by in arms.items()}
            for g, arms in found.items()}


def _stream(name):
    return random.Random(BOOT_SEED + zlib.crc32(name.encode("utf-8")))


def _tail(draws, conf):
    """How many draws the percentile interval leaves outside it at each end."""
    return int(round(draws * (1.0 - conf) / 2.0))


def _draw(rng, strata):
    """One resample of an arm: every stratum's runs drawn with replacement, then pooled."""
    n = k = 0
    for runs in strata:
        dn, dk = map(sum, zip(*rng.choices(runs, k=len(runs))))
        n += dn
        k += dk
    return n, k


def _arm(strata, draws_of_rate, t):
    """Pooled rate, run-level interval and per-run rates for one arm."""
    runs = [r for s in strata for r in s]
    n = sum(r[0] for r in runs)
    k = sum(r[1] for r in runs)
    draws_of_rate.sort()
    return {"runs": len(runs), "n_events": n, "n_negative": k, "rate": k / n,
            "ci": (draws_of_rate[t], draws_of_rate[-1 - t]) if k else None,
            "run_rates": [kr / nr for nr, kr in runs]}


def compare(top, bottom, name, draws=BOOT_DRAWS, conf=CONF):
    """Two arms and the factor between them, top over bottom, with run-level intervals.

    `top` and `bottom` are lists of strata, each a non-empty list of (events, negatives), one
    per run: a broker's runs, or both brokers' as two strata. Returns {"top": arm,
    "bottom": arm, "factor", "factor_ci", "unbounded_draws", "undefined_draws", "draws",
    "conf", "disjoint"}, where an arm is {"runs", "n_events", "n_negative", "rate", "ci",
    "run_rates"}. "factor" is the pooled rate over the pooled rate (math.inf when only the
    lower arm is zero, None when both are); "factor_ci" may end at math.inf, and is None when
    either arm holds no negative in any run; "disjoint" says whether the two arms' rate
    intervals are disjoint, and is None when either has no interval.
    """
    if not top or not bottom:
        raise ValueError("%s: both arms need runs" % name)
    rng, t = _stream(name), _tail(draws, conf)
    rates_top, rates_bottom, ratios = [], [], []
    unbounded = undefined = 0
    for _ in range(draws):
        n_a, k_a = _draw(rng, top)
        n_b, k_b = _draw(rng, bottom)
        rates_top.append(k_a / n_a)
        rates_bottom.append(k_b / n_b)
        if k_b:
            ratios.append((k_a / n_a) / (k_b / n_b))
        elif k_a:
            unbounded += 1
        else:
            undefined += 1
    a, b = _arm(top, rates_top, t), _arm(bottom, rates_bottom, t)
    if a["n_negative"] and b["n_negative"]:
        low = sorted(ratios + [math.inf] * unbounded + [0.0] * undefined)
        high = sorted(ratios + [math.inf] * (unbounded + undefined))
        factor_ci = (low[t], high[-1 - t])
    else:
        factor_ci = None
    if b["n_negative"]:
        factor = a["rate"] / b["rate"]
    else:
        factor = math.inf if a["n_negative"] else None
    if a["ci"] is None or b["ci"] is None:
        disjoint = None
    else:
        disjoint = a["ci"][1] < b["ci"][0] or b["ci"][1] < a["ci"][0]
    return {"top": a, "bottom": b, "factor": factor, "factor_ci": factor_ci,
            "unbounded_draws": unbounded, "undefined_draws": undefined, "draws": draws,
            "conf": conf, "disjoint": disjoint}


def _pairs(result, path, backend, draws, conf):
    """Normal over real-time for every (campaign, load) of a result, ordered by load."""
    out = []
    groups = _arms(read_runs(path), result,
                   lambda r: (r["campaign"], r["cell"].rpartition("_")[0]), backend)
    for (campaign, level), arms in groups.items():
        d = compare(arms.get("normal", []), arms.get("real-time", []),
                    "%s|%s|%s|%s" % (result, campaign, level, backend), draws, conf)
        d.update(campaign=campaign, level=level, backend=backend, normal=d["top"])
        d["real-time"] = d["bottom"]
        out.append(d)
    out.sort(key=lambda d: (int(d["level"].lstrip("l")), d["campaign"]))
    return out


def priority_intervals(path=RUNS_CSV, backend="kafka", draws=BOOT_DRAWS, conf=CONF):
    """Every matched pair on one broker ("kafka", "redis", or "both" pooled): the
    normal-priority rate over the real-time rate.

    Returns a list of compare()'s dict, each with "campaign", "level" (as in
    `priority_pairs.pairs`, "l75") and "backend" added, and "normal" and "real-time" naming its
    two arms ("top" and "bottom"), ordered by load and then by campaign.
    """
    return _pairs("priority", path, backend, draws, conf)


def trace_intervals(path=RUNS_CSV, backend="kafka", draws=BOOT_DRAWS, conf=CONF):
    """The traced pairs, E-A9 and E-A9b, and E-A9's untraced twin, in priority_intervals'
    shape. On Kafka the traced real-time arms hold no value below zero, so their factor is
    unbounded and has no interval; "both" pools the two brokers' runs."""
    return _pairs("trace", path, backend, draws, conf)


def priority_summary(pairs):
    """The range of the factor over the pairs, whether every pair's two rate intervals are
    disjoint, and how many pairs have a factor interval with no upper end."""
    factors = [p["factor"] for p in pairs if p["factor"] is not None]
    return {"pairs": len(pairs),
            "factor_low": min(factors) if factors else None,
            "factor_high": max(factors) if factors else None,
            "all_disjoint": bool(pairs) and all(p["disjoint"] for p in pairs),
            "unbounded": sum(1 for p in pairs
                             if p["factor_ci"] is not None and math.isinf(p["factor_ci"][1]))}


def placement_intervals(path=RUNS_CSV, backend="kafka", draws=BOOT_DRAWS, conf=CONF,
                        level="k6"):
    """{campaign: compare()'s dict}: the spread placement's rate over the concentrated one's,
    the direction `stat_intervals.ratio_z(ks, ns, kc, nc)` takes, with "spread" and
    "concentrated" naming the two arms.

    `level` is the number of busy cores, "k5", "k6" or "k7" (15 Oct 2026); k = 6 keeps the
    resampling stream it always had, so its interval does not move."""
    out = {}
    rows = [r for r in read_runs(path) if r["result"] != "placement"
            or r["cell"].partition("_")[0] == level]
    stream = "" if level == "k6" else "|" + level
    for campaign, arms in _arms(rows, "placement", lambda r: r["campaign"], backend).items():
        d = compare(arms.get("spread", []), arms.get("concentrated", []),
                    "placement|%s|%s%s" % (campaign, backend, stream), draws, conf)
        d.update(backend=backend, spread=d["top"], concentrated=d["bottom"], level=level)
        out[campaign] = d
    return out


def path_intervals(path=RUNS_CSV, backend="kafka", draws=BOOT_DRAWS, conf=CONF, ends=False):
    """{campaign: compare()'s dict}: the fall in the rate across the padding sweep.

    `stat_intervals.payload_span` defines the fall as the highest pooled rate of the sweep over
    the lowest, and its Katz interval holds those two levels fixed; so does this one, resampling
    the runs of the two levels the pooled rates pick. With `ends`, the two levels are instead
    the least and the most padding, which is the same pair wherever the sweep falls
    monotonically. "high" and "low" name the two, in bytes of padding.
    """
    out = {}
    for campaign, arms in _arms(read_runs(path), "path", lambda r: r["campaign"],
                                backend).items():
        if len(arms) < 2:
            raise ValueError("%s: a fall needs two padding levels, found %d"
                             % (campaign, len(arms)))
        if ends:
            high, low = min(arms, key=int), max(arms, key=int)
        else:
            rate = {a: sum(k for s in st for _, k in s) / sum(n for s in st for n, _ in s)
                    for a, st in arms.items()}
            high, low = max(rate, key=rate.get), min(rate, key=rate.get)
        d = compare(arms[high], arms[low], "path|%s|%s|%s" % (campaign, backend, ends),
                    draws, conf)
        d.update(backend=backend, high=high, low=low)
        out[campaign] = d
    return out


def ladder_intervals(path=RUNS_CSV, backend="kafka", draws=BOOT_DRAWS, conf=CONF):
    """{campaign: compare()'s dict}: the growth of the rate from E-A3's idle cell to its knee,
    the quotient `stat_intervals.load_growth` takes, with "knee" and "idle" naming the arms."""
    out = {}
    for campaign, arms in _arms(read_runs(path), "ladder", lambda r: r["campaign"],
                                backend).items():
        d = compare(arms.get("knee", []), arms.get("idle", []),
                    "ladder|%s|%s" % (campaign, backend), draws, conf)
        d.update(backend=backend, knee=d["top"], idle=d["bottom"])
        out[campaign] = d
    return out


def rate_by_load(path=RUNS_CSV, model_dir=MODEL):
    """Every run of E-A3's load ladder and of the priority pairs, as the paper's Fig. 2 draws
    them: [{"backend", "priority", "campaign", "cell", "rho", "rate", "run"}], one per run.

    15 Oct 2026, referee B (Fig. 2): one look at the per-run rate against the client machine's
    utilization, by broker, at normal and at real-time priority, shows the rate rising with load
    at normal priority and staying low at real-time priority. `rho` is the cell's achieved
    utilization, from the file its committed analysis wrote: knee_resolution.csv for E-A3's
    cells, the campaign's priority file for each arm of a pair. A run's rate is its values of S
    below zero over its matched messages.
    """
    rho = {}
    for r in _read_csv(os.path.join(model_dir, "knee_resolution.csv")):
        if r["phase"] == LOAD[1]:
            rho[(LOAD[0], r["condition"])] = float(r["rho"])
    for campaign, filename in priority_pairs.CAMPAIGNS:
        for r in _read_csv(os.path.join(model_dir, filename)):
            rho[(campaign, r["level"] + "_base")] = float(r["rho_base"])
            rho[(campaign, r["level"] + "_rt")] = float(r["rho_rt"])
    out = []
    for r in read_runs(path):
        if r["result"] not in ("load", "priority") or not r["run_events"]:
            continue
        out.append({"backend": r["backend"], "priority": r["arm"], "campaign": r["campaign"],
                    "cell": r["cell"], "rho": rho[(r["campaign"], r["cell"])],
                    "rate": r["run_negatives"] / r["run_events"], "run": r["run"]})
    return out


# ---------------------------------------------------------------- report
def _ci(ci, fmt):
    if ci is None:
        return "no interval"
    hi = "unbounded" if math.isinf(ci[1]) else fmt % ci[1]
    return "[%s, %s]" % (fmt % ci[0], hi)


def _katz(top, bottom):
    try:
        return stat_intervals.ratio_ci(top["n_negative"], top["n_events"],
                                       bottom["n_negative"], bottom["n_events"])
    except ValueError:
        return None


def _rate(arm):
    """An arm's rate, its run-level interval and Wilson's beside it."""
    return "%.4f %s (Wilson %s)" % (
        arm["rate"], _ci(arm["ci"], "%.4f"),
        _ci(stat_intervals.wilson(arm["n_negative"], arm["n_events"]), "%.4f"))


def _num(value, fmt="%.2f"):
    """A factor as printed: "none" when it is undefined, "unbounded" when it is infinite."""
    return "none" if value is None else ("unbounded" if math.isinf(value) else fmt % value)


def _factor(d, fmt="%.2f"):
    return "%s %s (Katz %s); unbounded in %d of %d resamples, undefined in %d" % (
        _num(d["factor"], fmt), _ci(d["factor_ci"], fmt), _ci(_katz(d["top"], d["bottom"]), fmt),
        d["unbounded_draws"], d["draws"], d["undefined_draws"])


def _pair_lines(pairs):
    lines = []
    for p in pairs:
        nm, rt = p["normal"], p["real-time"]
        lines.append("  %-13s %-4s runs %d/%d  normal %s  real-time %s"
                     % (p["campaign"], p["level"], nm["runs"], rt["runs"], _rate(nm), _rate(rt)))
        lines.append("      factor %s; rate intervals disjoint: %s"
                     % (_factor(p, "%.1f"), p["disjoint"]))
    return lines


def report(path=RUNS_CSV, draws=BOOT_DRAWS, conf=CONF):
    """Every interval, per broker: run-level beside Wilson's (rates) and Katz's (factors)."""
    pct = "%g%%" % (100 * conf)
    lines = ["Run-level %s percentile intervals, %d resamples of whole runs per comparison; "
             "Wilson and Katz %s intervals from the same pooled counts beside them." % (
                 pct, draws, pct)]
    for backend in BACKENDS:
        lines += ["", "==== %s ====" % backend,
                  "Real-time priority, normal over real-time, every matched pair:"]
        pairs = priority_intervals(path, backend, draws, conf)
        lines += _pair_lines(pairs)
        s = priority_summary(pairs)
        lines.append("  %d pairs, factor %s to %s; every pair's rate intervals disjoint: %s; "
                     "factor interval unbounded above in %d" % (
                         s["pairs"], _num(s["factor_low"]), _num(s["factor_high"]),
                         s["all_disjoint"], s["unbounded"]))
        for level in PLACEMENT_LEVELS:
            lines.append("Placement at k = %s, spread over concentrated:" % level[1:])
            for campaign, d in sorted(placement_intervals(path, backend, draws, conf,
                                                          level).items()):
                lines.append("  %-6s concentrated %s  spread %s" % (
                    campaign, _rate(d["concentrated"]), _rate(d["spread"])))
                lines.append("      factor %s" % _factor(d))
        lines.append("Path length, the fall across the padding sweep (highest rate over lowest):")
        ends = path_intervals(path, backend, draws, conf, ends=True)
        for campaign, d in sorted(path_intervals(path, backend, draws, conf).items()):
            lines.append("  %-6s pad %s B %s  pad %s B %s" % (
                campaign, d["high"], _rate(d["top"]), d["low"], _rate(d["bottom"])))
            lines.append("      fall %s" % _factor(d))
            e = ends[campaign]
            if (e["high"], e["low"]) != (d["high"], d["low"]):
                lines.append("      not monotone: least over most padding, pad %s B over pad "
                             "%s B, %s" % (e["high"], e["low"], _factor(e)))
        lines.append("Load ladder, knee over idle:")
        for campaign, d in sorted(ladder_intervals(path, backend, draws, conf).items()):
            lines.append("  %-6s idle %s  knee %s" % (campaign, _rate(d["idle"]),
                                                     _rate(d["knee"])))
            lines.append("      growth %s" % _factor(d))
    for backend in BACKENDS + ("both",):
        lines += ["", "Traced pairs and the untraced twin, %s:" % (
            "both brokers pooled" if backend == "both" else backend)]
        lines += _pair_lines(trace_intervals(path, backend, draws, conf))
    return "\n".join(lines)


# ---------------------------------------------------------------- the committed intervals
#: Every comparison, per broker, as the paper's mechanism table and macros read it. Twenty
#: thousand resamples a comparison is too slow to repeat at every build, so the intervals are
#: computed once from the committed runs file and committed beside it (6 Oct 2026).
INTERVALS_CSV = os.path.join(MODEL, "manipulation_intervals.csv")
INTERVAL_FIELDS = ["result", "campaign", "level", "backend", "top", "bottom",
                   "top_rate", "top_lo", "top_hi", "bottom_rate", "bottom_lo", "bottom_hi",
                   "factor", "factor_lo", "factor_hi", "disjoint"]


def _cell(value):
    """A number as the intervals file holds it: blank for none, "inf" for unbounded."""
    if value is None:
        return ""
    return "inf" if math.isinf(value) else "%.6g" % value


def _interval_row(result, campaign, level, backend, top, bottom, d):
    a_lo, a_hi = d["top"]["ci"] or (None, None)
    b_lo, b_hi = d["bottom"]["ci"] or (None, None)
    f_lo, f_hi = d["factor_ci"] or (None, None)
    return {"result": result, "campaign": campaign, "level": level, "backend": backend,
            "top": top, "bottom": bottom,
            "top_rate": _cell(d["top"]["rate"]), "top_lo": _cell(a_lo), "top_hi": _cell(a_hi),
            "bottom_rate": _cell(d["bottom"]["rate"]), "bottom_lo": _cell(b_lo),
            "bottom_hi": _cell(b_hi), "factor": _cell(d["factor"]), "factor_lo": _cell(f_lo),
            "factor_hi": _cell(f_hi),
            "disjoint": "" if d["disjoint"] is None else str(d["disjoint"])}


def intervals(path=RUNS_CSV, draws=BOOT_DRAWS, conf=CONF):
    """Every comparison of the report, one row each, for the intervals file."""
    rows = []
    for backend in BACKENDS:
        for p in priority_intervals(path, backend, draws, conf):
            rows.append(_interval_row("priority", p["campaign"], p["level"], backend, "normal",
                                      "real-time", p))
        for level in PLACEMENT_LEVELS:
            for campaign, d in sorted(placement_intervals(path, backend, draws, conf,
                                                          level).items()):
                rows.append(_interval_row("placement", campaign, level, backend, "spread",
                                          "concentrated", d))
        for ends, result in ((False, "path"), (True, "path_ends")):
            for campaign, d in sorted(path_intervals(path, backend, draws, conf, ends).items()):
                rows.append(_interval_row(result, campaign, "", backend, d["high"], d["low"], d))
        for campaign, d in sorted(ladder_intervals(path, backend, draws, conf).items()):
            rows.append(_interval_row("ladder", campaign, "", backend, "knee", "idle", d))
    for backend in BACKENDS + ("both",):
        for p in trace_intervals(path, backend, draws, conf):
            rows.append(_interval_row("trace", p["campaign"], p["level"], backend, "normal",
                                      "real-time", p))
    return rows


def write_intervals(rows, out=INTERVALS_CSV):
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=INTERVAL_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def read_intervals(path=INTERVALS_CSV):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------- driver
def main(argv=None):
    ap = argparse.ArgumentParser(description="Run-level intervals for the manipulations")
    sub = ap.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="per-run counts from the archive, checked and written")
    ex.add_argument("--depth", default=DEPTH)
    ex.add_argument("--runs", default=RUNS)
    ex.add_argument("--model", default=MODEL)
    ex.add_argument("--span", default=SPAN_CSV)
    ex.add_argument("--out", default=RUNS_CSV)
    rp = sub.add_parser("report", help="every interval, from the committed file only")
    rp.add_argument("--csv", default=RUNS_CSV)
    rp.add_argument("--draws", type=int, default=BOOT_DRAWS)
    iv = sub.add_parser("intervals", help="write every interval to the committed file")
    iv.add_argument("--csv", default=RUNS_CSV)
    iv.add_argument("--out", default=INTERVALS_CSV)
    iv.add_argument("--draws", type=int, default=BOOT_DRAWS)
    mg = sub.add_parser("margins", help="each broker's margin from the archive, written")
    mg.add_argument("--depth", default=DEPTH)
    mg.add_argument("--runs", default=RUNS)
    mg.add_argument("--out", default=MARGINS_CSV)
    sp = sub.add_parser("spans", help="the padding campaign's medians of A, D and S, checked")
    sp.add_argument("--depth", default=DEPTH)
    sp.add_argument("--runs", default=RUNS)
    sp.add_argument("--out", default=PADDING_CSV)
    sp.add_argument("--model", default=MODEL)
    sp.add_argument("--csv", default=RUNS_CSV)
    fl = sub.add_parser("floor", help="where each real-time value below zero sits, checked")
    fl.add_argument("--depth", default=DEPTH)
    fl.add_argument("--runs", default=RUNS)
    fl.add_argument("--out", default=RT_FLOOR_CSV)
    fl.add_argument("--model", default=MODEL)
    fl.add_argument("--csv", default=RUNS_CSV)
    args = ap.parse_args(argv)

    if args.command == "floor":
        try:
            rows = rt_floor(args.depth, args.runs, args.model)
        except (OSError, KeyError, ValueError) as exc:
            print("cannot read the real-time cells: %s" % exc)
            return 1
        problems = check_rt_floor(rows, args.csv)
        if problems:
            print("the floor does not reproduce the run file; nothing written:")
            for p in problems:
                print("  " + p)
            return 1
        write_rt_floor(rows, args.out)
        for backend in BACKENDS:
            mine = [r for r in rows if r["backend"] == backend and r["run_negatives"]]
            print("%-5s %d runs hold %d values below zero" % (
                backend, len(mine), sum(r["run_negatives"] for r in mine)))
        print("wrote %s" % args.out)
        return 0

    if args.command == "spans":
        try:
            rows = padding_spans(args.depth, args.runs, args.model)
        except (OSError, KeyError, ValueError) as exc:
            print("cannot read the padding campaign: %s" % exc)
            return 1
        problems = check_padding(rows, args.model, args.csv)
        if problems:
            print("the medians do not reproduce the committed records; nothing written:")
            for p in problems:
                print("  " + p)
            return 1
        write_padding(rows, args.out)
        for r in rows:
            print("%-6s %-9s %-5s A %s ms  D %s ms  S %s ms over %d messages" % (
                r["campaign"], r["cell"], r["backend"], r["median_a_ms"], r["median_d_ms"],
                r["median_s_ms"], r["n_events"]))
        print("wrote %s" % args.out)
        return 0

    if args.command == "report":
        print(report(args.csv, args.draws))
        return 0
    if args.command == "margins":
        try:
            rows = margins(args.depth, args.runs)
        except (OSError, ValueError) as exc:
            print("cannot estimate the margins: %s" % exc)
            return 1
        write_margins(rows, args.out)
        for r in rows:
            print("%-5s median S %s ms over %d messages at rho %s" % (
                r["backend"], r["median_s_ms"], r["n_events"], r["rho"]))
        print("wrote %s" % args.out)
        return 0
    if args.command == "intervals":
        rows = intervals(args.csv, args.draws)
        write_intervals(rows, args.out)
        print("wrote %d comparisons to %s" % (len(rows), args.out))
        return 0
    for folder in (args.depth, args.runs):
        if not os.path.isdir(folder):
            print("missing archive directory: %s" % folder)
            return 1
    try:
        rows = extract(args.depth, args.runs, args.model)
        problems = check(rows, args.model, args.span)
    except (OSError, KeyError, ValueError) as exc:
        print("cannot read the committed records: %s" % exc)
        return 1
    if problems:
        print("the runs do not reproduce the committed records; nothing written:")
        for p in problems:
            print("  " + p)
        return 1
    write(rows, args.out)
    for result in RESULTS:
        for backend in BACKENDS:
            mine = [r for r in rows if r["result"] == result and r["backend"] == backend]
            print("%-9s %-5s %3d runs in %2d cells, %d events, %d with S < 0" % (
                result, backend, len(mine), len({(r["campaign"], r["cell"]) for r in mine}),
                sum(r["run_events"] for r in mine), sum(r["run_negatives"] for r in mine)))
    print("every Kafka half reproduces its committed totals, and every run of both brokers "
          "its counts in span_run_level.csv; wrote %s" % args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
