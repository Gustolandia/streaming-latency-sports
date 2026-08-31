#!/usr/bin/env python3
"""
span_by_condition.py
Per-condition span histograms, and the decomposition the symmetry question needs.

Why this exists. The pooled histogram (`span_histogram.py`) mixes 74 experimental conditions
-- two brokers, sender counts from 1 to 20, feed counts from 1 to 12 -- so any statement about
its shape confounds within-condition structure with between-condition spread. A co-author
asked whether the distribution is symmetric, and the pooled answer (it is not) says nothing
about whether each condition's distribution is symmetric about its own centre, which is the
question the model actually makes a prediction about.

The decomposition. Every joined event carries four stamps, all on one wall clock, so three
derived quantities can be histogrammed per condition:

    S = t_cons_recv - t_broker_ack     the ack-referenced span, the one that goes negative
    D = t_cons_recv - t_prod_send      the send-referenced span, a causal chain, never negative
    A = t_broker_ack - t_prod_send     the producer-side ack lag, also single-clock

with S = D - A by construction. S's shape is therefore the cross-correlation of D's and A's
shapes, and any symmetry claim about S is a claim about that pair. Histogramming all three
separately is what lets the symmetry be tested rather than eyeballed.

Also collected per run, for the uncertainty audit: the number of events the millisecond
positivity guard would delete (ms-truncated difference <= 0), so that the pooled 45.8% can
carry a cluster-bootstrap interval over runs rather than a naively tight binomial one.

Gate split. The consistency check rejects a run when more than 1% of its events are negative
in a component or a median is negative. Both criteria are computable from this pass, so each
condition is accumulated twice -- once over gate-passing runs, once over gate-failing ones --
and the recovery estimator can be scored exactly where a remedy for already-collected data
earns its keep: on the rejected population.

The disease ratio. Using S as a delivery measurement errs by exactly -A per event, and the
sign check fires only where A > D. The fraction of events with A > alpha*D for a ladder of
alpha, plus a histogram of the per-event ratio A/D, is therefore the magnitude-and-shape of
the contamination the check does NOT see. Collected per run (the alpha ladder) and pooled
(the ratio histogram, tenth-decade log bins).

Outputs (committed, so a clean clone can reproduce every downstream number):
    docs/results/span_by_condition.json    per-condition binned histograms of S, D, A
    docs/results/span_run_level.csv        per-run counts for cluster bootstraps

CLI:
    python scripts/span_by_condition.py --archive cloud_archive/sbl_runs.tgz
"""
import argparse
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recount_spans

DEFAULT_ARCHIVE = os.path.join("cloud_archive", "sbl_runs.tgz")
OUT_JSON = os.path.join("docs", "results", "span_by_condition.json")
OUT_CSV = os.path.join("docs", "results", "span_run_level.csv")

#: Same fixed binning as span_histogram.py, for the same reason: committed artefacts whose
#: shape cannot drift when the corpus is rescanned.
BIN_LO_US = -100_000
BIN_HI_US = 100_000
BIN_WIDTH_US = 50

RUN_ID_RE = re.compile(r'concurrency_n(\d+)_\d+_\d+_([a-z]+)_feed(\d+)_rep(\d+)')

QUANTITIES = ("S", "D", "A")

#: The disease ladder: fraction of events whose ack lag exceeds alpha times delivery.
ALPHAS = (0.1, 0.25, 0.5, 1.0)


def condition_of(run_id):
    m = RUN_ID_RE.match(run_id)
    if not m:
        return None
    return "%s_n%s_feed%s" % (m.group(2), m.group(1), m.group(3))


def new_cond():
    acc = {q: {"bins": {}, "under": 0, "over": 0, "n": 0} for q in QUANTITIES}
    # Paired co-moments for rho(D, A), accumulated on the EVENTS rather than recovered
    # afterwards from the three marginal histograms.
    #
    # The earlier route used the variance identity, Var(S) = Var(D) + Var(A) - 2 rho sd sd,
    # reading all three variances off binned and edge-truncated histograms. Each margin
    # loses a different amount of tail mass to truncation, so the identity is not conserved
    # and rho is not bounded: five of seventy conditions came back with |rho| > 1, the
    # largest 2.16. A correlation outside [-1, 1] is not a small numerical annoyance in this
    # paper of all papers -- it is an instrument reporting an impossible value, which is the
    # thing the manuscript is about.
    #
    # Six running sums are exact, need one pass, and cost nothing beside the histograms
    # already being filled next to them.
    #
    # `outside` counts the pairs the window excludes, and it is reported rather than
    # discarded. Every other statistic in this file is computed on the +-100 ms histogram
    # window; a correlation computed over the untruncated stream would describe a different
    # population from the medians printed beside it. That matters here more than usually:
    # some redis_n5 conditions carry delivery values of order 10^8 us, so sd(D) came out at
    # 142 SECONDS and a handful of events set the correlation for the whole condition.
    #
    # A paper about an instrument that drops samples without counting them does not get to
    # drop samples without counting them.
    acc["pair"] = {"n": 0, "outside": 0,
                   "sd": 0.0, "sa": 0.0, "sdd": 0.0, "saa": 0.0, "sda": 0.0}
    return acc


def add(acc_q, value_us):
    acc_q["n"] += 1
    if value_us < BIN_LO_US:
        acc_q["under"] += 1
    elif value_us >= BIN_HI_US:
        acc_q["over"] += 1
    else:
        b = int((value_us - BIN_LO_US) // BIN_WIDTH_US)
        acc_q["bins"][b] = acc_q["bins"].get(b, 0) + 1


def consume_run(conds, run_rows, run_id, prod_rows, cons_rows):
    cond = condition_of(run_id)
    if cond is None:
        return 0
    index = {}
    for row in prod_rows:
        try:
            index[row["event_id"]] = (int(row["t_prod_send_ns"]), int(row["t_broker_ack_ns"]))
        except (KeyError, TypeError, ValueError):
            continue
    # First pass over the run in memory: the gate verdict needs the run's own events before
    # any condition-level accumulator is touched, so events are buffered per run. A run is a
    # few hundred events; this costs nothing.
    events = []
    for row in cons_rows:
        prod = index.get(row.get("event_id"))
        if prod is None:
            continue
        try:
            recv = int(row["t_cons_recv_ns"])
        except (KeyError, TypeError, ValueError):
            continue
        send_ns, ack_ns = prod
        events.append((recv - ack_ns, recv - send_ns, ack_ns - send_ns))
    if not events:
        return 0
    s_vals = sorted(e[0] for e in events)
    neg = sum(1 for e in events if e[0] < 0)
    med_s = s_vals[len(s_vals) // 2]
    gate_fail = (neg > 0.01 * len(events)) or (med_s < 0)
    key = cond + ("#fail" if gate_fail else "#pass")

    acc = conds.setdefault(key, new_cond())
    counted = ms_deleted = 0
    over = {a: 0 for a in ALPHAS}
    for s_ns, d_ns, a_ns in events:
        add(acc["S"], s_ns / 1000.0)
        add(acc["D"], d_ns / 1000.0)
        add(acc["A"], a_ns / 1000.0)
        d_us, a_us = d_ns / 1000.0, a_ns / 1000.0
        pair = acc["pair"]
        if (BIN_LO_US <= d_us < BIN_HI_US) and (BIN_LO_US <= a_us < BIN_HI_US):
            pair["n"] += 1
            pair["sd"] += d_us
            pair["sa"] += a_us
            pair["sdd"] += d_us * d_us
            pair["saa"] += a_us * a_us
            pair["sda"] += d_us * a_us
        else:
            pair["outside"] += 1
        counted += 1
        if d_ns > 0:
            r = a_ns / d_ns
            ratio_hist_add(r)
            for alpha in ALPHAS:
                if r > alpha:
                    over[alpha] += 1
    ms_deleted = sum(1 for row in cons_rows if _ms_deleted(row, index))
    rr = {"run_id": run_id, "condition": cond, "gate": "fail" if gate_fail else "pass",
          "n_events": counted, "neg_ack": neg, "ms_deleted": ms_deleted}
    for alpha in ALPHAS:
        rr["over_%g" % alpha] = over[alpha]
    run_rows.append(rr)
    return counted


def _ms_deleted(row, index):
    """Would the millisecond positivity guard delete this event? Uses the absolute stamps,
    exactly as span_histogram.py computes it."""
    prod = index.get(row.get("event_id"))
    if prod is None:
        return False
    try:
        recv = int(row["t_cons_recv_ns"])
    except (KeyError, TypeError, ValueError):
        return False
    return (recv // 1_000_000) - (prod[1] // 1_000_000) <= 0


#: Pooled histogram of the per-event ratio A/D, tenth-decade log bins over [1e-3, 1e3].
RATIO_HIST = {}


def ratio_hist_add(r):
    import math
    if r <= 0:
        RATIO_HIST["nonpos"] = RATIO_HIST.get("nonpos", 0) + 1
        return
    b = max(-30, min(30, int(math.floor(10.0 * math.log10(r)))))
    RATIO_HIST[b] = RATIO_HIST.get(b, 0) + 1


def scan_archive(path, progress=250):
    import tarfile
    conds, run_rows = {}, []
    pending = {}
    runs = events = 0
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
            pending.setdefault(run_id, {})[name.split(".")[0]] = handle.read()
            if len(pending[run_id]) == 2:
                files = pending.pop(run_id)
                prod = recount_spans.parse_rows(files["producer"])
                cons = recount_spans.parse_rows(files["consumer"])
                if prod and cons:
                    got = consume_run(conds, run_rows, run_id, prod, cons)
                    if got:
                        runs += 1
                        events += got
                        if progress and runs % progress == 0:
                            sys.stderr.write("  %d runs, %d events\r" % (runs, events))
                            sys.stderr.flush()
    sys.stderr.write("\n")
    return conds, run_rows, runs, events


def write_outputs(conds, run_rows, runs, events):
    payload = {
        "runs": runs, "events": events,
        "ratio_hist_tenth_decades": {str(k): v for k, v in sorted(RATIO_HIST.items(), key=lambda kv: str(kv[0]))},
        "alphas": list(ALPHAS),
        "bin_lo_us": BIN_LO_US, "bin_hi_us": BIN_HI_US, "bin_width_us": BIN_WIDTH_US,
        "conditions": {
            cond: dict(
                {q: {"n": acc[q]["n"], "under": acc[q]["under"], "over": acc[q]["over"],
                     "bins": {str(k): v for k, v in sorted(acc[q]["bins"].items())}}
                 for q in QUANTITIES},
                # Carried alongside the histograms, not derived from them: this is the whole
                # point of the fix. Truncation at the histogram edges is what made the
                # variance-identity route return correlations above one.
                pair=acc["pair"],
            )
            for cond, acc in sorted(conds.items())
        },
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        fields = ["run_id", "condition", "gate", "n_events", "neg_ack", "ms_deleted"] +                  ["over_%g" % a for a in ALPHAS]
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in sorted(run_rows, key=lambda r: r["run_id"]):
            w.writerow(r)
    return OUT_JSON, OUT_CSV


def main(argv=None):
    ap = argparse.ArgumentParser(description="Per-condition S, D, A histograms from the archive")
    ap.add_argument("--archive", default=DEFAULT_ARCHIVE)
    ap.add_argument("--progress", type=int, default=250)
    args = ap.parse_args(argv)
    conds, run_rows, runs, events = scan_archive(args.archive, args.progress)
    j, c = write_outputs(conds, run_rows, runs, events)
    print("runs %d  events %d  conditions %d" % (runs, events, len(conds)))
    print("wrote %s and %s" % (j, c))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
