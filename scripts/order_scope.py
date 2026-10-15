#!/usr/bin/env python3
"""
order_scope.py -- freeze 41's judge (plan version 44, docs/results/order_scope/DESIGN.md): the
acknowledgment's own arrival, timed by the kernel; a positive control and a rate ladder for the
kernel-timed latency; and two checks of the timescale.

Per message, on the driver's one clock: t_pub, t_ack and t_recv from the clients; t_tx_so and t_rx_so
from their sockets (freeze 40); and, from the clients' journals (scripts/so_journal.py),

  t_rx_ack  the kernel's receive timestamp of the producer's read that completed the message's
            acknowledgment;
  t_req     the kernel's transmit timestamp of the consumer's request that delivered it.

  S      = t_recv - t_ack       the paper's span
  S_k    = t_rx_so - t_rx_ack   the same order, timed by the kernel: no client thread's wait in it
  d_ack  = t_ack - t_rx_ack     the acknowledging thread's delay: the late reading itself
  d_recv = t_recv - t_rx_so     the consumer's delay
  W_so   = t_rx_so - t_tx_so    the kernel-timed latency, as freeze 40 read it

On one clock S = S_k + d_recv - d_ack exactly, so S < 0 exactly when d_ack - d_recv > S_k. A message
carries the pull flag when t_req > t_tx_so: the request that delivered it left the client after the
message itself left, so it waited in the broker, and that wait is inside W.

Every value is in microseconds. A setup's value is the median over its runs of each run's statistic,
unless a prediction pools messages.

CLI:
    python scripts/order_scope.py read --block K --runs FOLDER [--runs ...] --driver IP \
        --broker IP --receiver IP --out CSV [--quintiles CSV] [--warmup S]
    python scripts/order_scope.py judge --block K --table CSV [--quintiles CSV] --out JSON
"""
import argparse
import bisect
import csv
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import full_fix as ff  # noqa: E402
import quality_report  # noqa: E402
import recv_wait as rw  # noqa: E402
import so_fix  # noqa: E402
import so_journal as sj  # noqa: E402

#: Where each block's setups start, by the prefix of their ids in the queue.
PREFIX = {"K": "K-", "R": "R-", "P": "P-", "L": "L", "I": "I-"}
#: The brokers' ports, for finding their connections in a capture.
PORTS = {"kafka": 9092, "redis": 6379}

#: K-v and L-a: how far two instruments' timestamps may lie apart at a setup's median, in us.
AGREE_US = 20.0
#: K-a: the most of Kafka's negative S that may have S_k < 0; K-b: the least of Redis's, at
#: real-time priority with sixteen workers.
RIVAL_SHARE = 0.10
REDIS_ORDER_SHARE = 0.5
#: K-c: d_ack's 99th percentile under load against idle, and at real-time priority against normal.
LOAD_RATIO = 1.5
RT_RATIO = 0.5
#: K-d: how many bins, how far the observed rate may lie from the prediction, and how many negative
#: values a bin needs before it is judged.
BINS = 5
FACTOR = 2.0
MIN_NEGATIVES = 20
#: K-d, described: the slice the runs set and the stock kernel's tick, in ms (settings_before.json:
#: config_hz 1000), for G; and the delay beyond which the acknowledging thread counts as waiting.
SLICE_MS = 3.0
TICK_MS = 1.0
WAITED_US = 100.0
#: K-e: the one-worker rate against the sixteen-worker rate that says the interpreter lock sets it.
GIL_RATIO = 0.5
#: R-a and R-b.
RTP_RATIO = 2.0 / 3.0
#: P-a and P-c: the slope's band, in ms per ms; P-b: how far A's median may move.
SLOPE = (0.9, 1.1)
A_MOVE = 0.10
#: L-b and L-c.
LADDER_MOVE = 0.10
FLAG_SHARE_AT_50 = 0.01
#: Block I: the mode of negative S it asks about, in us, and how much idle=poll must cut it.
BUMP = (-250.0, -150.0)
BUMP_CUT = 0.5


def rest_of_slice_g(x, s, h):
    """Equation S3, as scripts/emit_paper_numbers.rest_of_slice_g has it: the chance that a wait for
    the rest of a slice, then up to a tick, outlasts x (R + U, R uniform on [0, s], U on [0, h])."""
    if x <= 0:
        return 1.0
    if x <= h:
        return 1.0 - x * x / (2.0 * s * h)
    if x <= s:
        return 1.0 - (x - h / 2.0) / s
    if x < s + h:
        return (s + h - x) ** 2 / (2.0 * s * h)
    return 0.0


def _median(values):
    return statistics.median(values) if values else None


def _p99(values):
    return rw.percentile(values, 99) if values else None


def _share(part, whole):
    return part / float(whole) if whole else None


def _us(a, b):
    """(a - b) in microseconds, or None if either is missing."""
    return None if a is None or b is None else (a - b) / 1e3


def acknowledgment_times(run_dir):
    """{event id: t_ack} from the producer's own file."""
    found = {}
    with open(os.path.join(run_dir, "producer.csv"), encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("t_broker_ack_ns"):
                found[r["event_id"]] = int(r["t_broker_ack_ns"])
    return found


def setup_of(run_dir):
    """(the run's setup id, its params) from its queue row."""
    row = rw.read_json(os.path.join(run_dir, "queue_row.json"))
    return row.get("setup") or "", row.get("params") or {}


def messages(run_dir, warmup_s):
    """[dict per message sent after the warm-up that arrived], with every time the run holds."""
    setup, params = setup_of(run_dir)
    backend = params.get("backend")
    acks = acknowledgment_times(run_dir)
    so_tx, so_rx = so_fix.socket_times(run_dir)
    rx_ack = sj.acknowledgments(sj.load(os.path.join(run_dir, "producer_journal")), backend)
    req = sj.requests(sj.load(os.path.join(run_dir, "consumer_journal")), backend)
    out = []
    for eid, pub, recv in rw.messages(run_dir, warmup_s):
        m = {"eid": eid, "pub": pub, "recv": recv, "ack": acks.get(eid), "tx_so": so_tx.get(eid),
             "rx_so": so_rx.get(eid), "rx_ack": rx_ack.get(eid), "req": req.get(eid)}
        m["A"], m["D"], m["S"] = _us(m["ack"], pub), _us(recv, pub), _us(recv, m["ack"])
        m["Sk"], m["dack"] = _us(m["rx_so"], m["rx_ack"]), _us(m["ack"], m["rx_ack"])
        m["drecv"], m["Wso"] = _us(recv, m["rx_so"]), _us(m["rx_so"], m["tx_so"])
        m["flagged"] = (None if m["req"] is None or m["tx_so"] is None
                        else m["req"] > m["tx_so"])
        out.append(m)
    return setup, params, out


def _base(run_dir, setup, params):
    judged = rw.read_json(os.path.join(run_dir, "integrity.json"))
    return {"run": os.path.basename(run_dir), "setup": setup, "backend": params.get("backend"),
            "load_pct": params.get("load_pct"), "priority": bool(params.get("priority")),
            "load_measured": ((judged.get("checks") or {}).get("load") or {}).get("value"),
            "dropped": ff.capture_drops(run_dir)}


def read_order_run(run_dir, driver, broker, receiver, warmup_s):
    """Blocks K, R and I: one run's row, and its messages with every time, for pooling."""
    setup, params, msgs = messages(run_dir, warmup_s)
    out = _base(run_dir, setup, params)
    out.update({"workers": str(params.get("send_workers") or ""),
                "sched_features": params.get("sched_features") or "",
                "idle_poll": "" if params.get("idle_poll") is None else bool(params["idle_poll"]),
                "messages": len(msgs)})
    full = [m for m in msgs if None not in (m["S"], m["Sk"], m["dack"], m["drecv"])]
    out["timed"] = len(full)
    out["missing_ack"] = sum(1 for m in msgs if m["rx_ack"] is None)
    out["missing_req"] = sum(1 for m in msgs if m["req"] is None)
    negative = [m for m in full if m["S"] < 0]
    out["S_neg"] = len(negative)
    out["S_neg_Sk_neg"] = sum(1 for m in negative if m["Sk"] < 0)
    out["Sk_neg"] = sum(1 for m in full if m["Sk"] < 0)
    out["bump"] = sum(1 for m in negative if BUMP[0] <= m["S"] < BUMP[1])
    for name in ("S", "Sk", "dack", "drecv", "Wso"):
        values = [m[name] for m in full if m[name] is not None]
        out[name + "_median"], out[name + "_p99"] = _median(values), _p99(values)
    out["dack_waited"] = sum(1 for m in full if m["dack"] > WAITED_US)
    out["flagged"] = sum(1 for m in msgs if m["flagged"])
    backend = params.get("backend")
    pcap = os.path.join(run_dir, "sender_full.pcap")
    checks = []
    if os.path.exists(pcap):
        segments = sj.incoming_segments(pcap, broker, PORTS.get(backend), driver)
        conns = sj.load(os.path.join(run_dir, "producer_journal"))
        checks = [abs(j - c) / 1e3 for j, c in sj.acknowledgment_checks(conns, backend, segments)]
    out["ack_checked"] = len(checks)
    out["ack_diff_median"], out["ack_diff_p99"] = _median(checks), _p99(checks)
    limit = quality_report.STALL_MS * 1e3
    out["D_held"] = sum(1 for m in msgs if m["D"] is not None and m["D"] > limit)
    return out, full


def read_control_run(run_dir, driver, broker, receiver, warmup_s):
    """Block P: one run's medians of W_so, the captures' W, A and D."""
    setup, params, msgs = messages(run_dir, warmup_s)
    out = _base(run_dir, setup, params)
    out["delay_ms"] = params.get("delay_ms")
    sent = ff.departure_times(os.path.join(run_dir, "sender_full.pcap"), driver, broker)
    got = rw.kernel_times(os.path.join(run_dir, "receiver_full.pcap"), broker, receiver)
    out["messages"] = len(msgs)
    for name in ("Wso", "A", "D"):
        out[name + "_median"] = _median([m[name] for m in msgs if m[name] is not None])
    out["W_median"] = _median([_us(got[m["eid"]], sent[m["eid"]]) for m in msgs
                               if m["eid"] in sent and m["eid"] in got])
    return out, []


def read_ladder_run(run_dir, driver, broker, receiver, warmup_s):
    """Block L: one run's W_so against the captures' W, the pull flag, packets per read and S."""
    setup, params, msgs = messages(run_dir, warmup_s)
    out = _base(run_dir, setup, params)
    out["rate"] = int(setup.split("-", 1)[0][1:]) if setup.startswith("L") else None
    sent = ff.departure_times(os.path.join(run_dir, "sender_full.pcap"), driver, broker)
    got = rw.kernel_times(os.path.join(run_dir, "receiver_full.pcap"), broker, receiver)
    out["messages"] = len(msgs)
    wso = [m["Wso"] for m in msgs if m["Wso"] is not None]
    out["Wso_median"], out["Wso_p99"] = _median(wso), _p99(wso)
    both = [(m["Wso"], _us(got[m["eid"]], sent[m["eid"]])) for m in msgs
            if m["Wso"] is not None and m["eid"] in sent and m["eid"] in got]
    out["W_median"] = _median([w for _, w in both])
    dif = [abs(a - b) for a, b in both]
    out["Dif_median"], out["Dif_p99"] = _median(dif), _p99(dif)
    flagged = [m for m in msgs if m["flagged"] is not None]
    out["flag_known"] = len(flagged)
    out["flagged"] = sum(1 for m in flagged if m["flagged"])
    out["Wso_flagged_median"] = _median([m["Wso"] for m in flagged
                                         if m["flagged"] and m["Wso"] is not None])
    out["Wso_unflagged_median"] = _median([m["Wso"] for m in flagged
                                           if not m["flagged"] and m["Wso"] is not None])
    spans = [m["S"] for m in msgs if m["S"] is not None]
    out["S_count"], out["S_neg"] = len(spans), sum(1 for s in spans if s < 0)
    segments = sj.incoming_segments(os.path.join(run_dir, "receiver_full.pcap"), broker,
                                    PORTS.get(params.get("backend")), receiver)
    reads = multi = 0
    for conn in sj.load(os.path.join(run_dir, "consumer_journal")).values():
        segs = segments.get(str(conn.local_port))
        if not segs:
            continue
        counts = [n for n in sj.packets_per_read(conn, segs) if n]
        reads += len(counts)
        multi += sum(1 for n in counts if n > 1)
    out["reads"], out["reads_multi"] = reads, multi
    return out, []


READERS = {"K": read_order_run, "R": read_order_run, "I": read_order_run,
           "P": read_control_run, "L": read_ladder_run}


# --- K-d: the rate law, Pr[S < 0 | m] about p G(m), message by message ----------------------------

def bins_by_margin(setup, msgs):
    """[row per bin] for one setup: its messages with S_k >= 0 cut into BINS equal-count bins by
    S_k, each with the observed rate of S < 0, the prediction Pr[d_ack - d_recv > S_k] from the
    setup's own distribution of d_ack - d_recv, and the paper's p G(S_k), described."""
    delta = sorted(m["dack"] - m["drecv"] for m in msgs)
    p = _share(sum(1 for m in msgs if m["dack"] > WAITED_US), len(msgs))

    def outlasts(x):
        return 1.0 - bisect.bisect_right(delta, x) / float(len(delta))
    pool = sorted((m for m in msgs if m["Sk"] >= 0), key=lambda m: m["Sk"])
    rows = []
    for b in range(BINS):
        part = pool[b * len(pool) // BINS:(b + 1) * len(pool) // BINS]
        if not part:
            continue
        negatives = sum(1 for m in part if m["S"] < 0)
        rows.append({"setup": setup, "bin": b + 1, "messages": len(part),
                     "Sk_median": _median([m["Sk"] for m in part]), "negatives": negatives,
                     "observed": negatives / float(len(part)),
                     "predicted": statistics.fmean(outlasts(m["Sk"]) for m in part),
                     "pG": statistics.fmean(p * rest_of_slice_g(m["Sk"] / 1e3, SLICE_MS,
                                                                TICK_MS) for m in part)})
    return rows


# --- the judgments -----------------------------------------------------------------------------

def _value(rows, field, **match):
    """A setup's value: the median over the runs that match, of each run's `field`."""
    picked = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    return _median([float(r[field]) for r in picked if r.get(field) not in (None, "")])


def _sum(rows, field, **match):
    return sum(int(r[field]) for r in rows if all(r.get(k) == v for k, v in match.items())
               and r.get(field) not in (None, ""))


def _verdict(checks):
    return "confirmed" if checks and all(c["holds"] for c in checks) else "not confirmed"


def _setups(rows):
    return sorted(set(r["setup"] for r in rows))


def judge_order(rows, bins):
    """Block K's predictions."""
    out = {}
    checks = []
    for setup in _setups(rows):
        v = _value(rows, "ack_diff_median", setup=setup)
        checks.append({"setup": setup, "median_us": v, "holds": v is not None and v <= AGREE_US})
    out["K-v"] = {"verdict": _verdict(checks), "checks": checks}
    checks, described = [], []
    for setup in _setups(rows):
        neg, order = _sum(rows, "S_neg", setup=setup), _sum(rows, "S_neg_Sk_neg", setup=setup)
        timed, sk = _sum(rows, "timed", setup=setup), _sum(rows, "Sk_neg", setup=setup)
        backend = next(r["backend"] for r in rows if r["setup"] == setup)
        entry = {"setup": setup, "negatives": neg, "order_share": _share(order, neg),
                 "Sk_negative_share": _share(sk, timed)}
        described.append(entry)
        if backend == "kafka" and neg >= MIN_NEGATIVES:
            checks.append(dict(entry, holds=_share(order, neg) <= RIVAL_SHARE))
    out["K-a"] = {"verdict": _verdict(checks), "checks": checks}
    checks = []
    for row in described:
        r0 = next(r for r in rows if r["setup"] == row["setup"])
        if r0["backend"] == "redis" and r0["priority"] and not r0["workers"]:
            share = row["order_share"]
            checks.append(dict(row, holds=share is not None and share >= REDIS_ORDER_SHARE))
    out["K-b"] = {"verdict": _verdict(checks), "checks": checks, "described": described}
    checks = []
    for backend in ("kafka", "redis"):
        idle = _value(rows, "dack_p99", backend=backend, load_pct=0, priority=False, workers="")
        busy = _value(rows, "dack_p99", backend=backend, load_pct=88, priority=False, workers="")
        rt = _value(rows, "dack_p99", backend=backend, load_pct=88, priority=True, workers="")
        holds = None not in (idle, busy, rt) and busy >= LOAD_RATIO * idle and rt <= RT_RATIO * busy
        checks.append({"backend": backend, "idle": idle, "busy": busy, "rt": rt, "holds": holds})
    out["K-c"] = {"verdict": _verdict(checks), "checks": checks}
    checks = []
    for setup in sorted(set(b["setup"] for b in bins)):
        part = sorted((b for b in bins if b["setup"] == setup), key=lambda b: b["bin"])
        rates = [float(b["observed"]) for b in part]
        falls = all(later <= earlier for earlier, later in zip(rates, rates[1:]))
        near = [b for b in part if int(b["negatives"]) >= MIN_NEGATIVES]
        within = all(float(b["predicted"]) > 0
                     and 1.0 / FACTOR <= float(b["observed"]) / float(b["predicted"]) <= FACTOR
                     for b in near)
        checks.append({"setup": setup, "falls": falls, "judged_bins": len(near),
                       "within": within, "holds": falls and within and bool(near)})
    out["K-d"] = {"verdict": _verdict(checks), "checks": checks}
    decisions = []
    for load in (0, 88):
        one = [r for r in rows if r["backend"] == "redis" and r["load_pct"] == load
               and r["priority"] and r["workers"] == "1"]
        many = [r for r in rows if r["backend"] == "redis" and r["load_pct"] == load
                and r["priority"] and not r["workers"]]
        rate_one = _share(sum(int(r["S_neg"]) for r in one), sum(int(r["timed"]) for r in one))
        rate_many = _share(sum(int(r["S_neg"]) for r in many),
                           sum(int(r["timed"]) for r in many))
        lock = (None if rate_one is None or not rate_many
                else rate_one <= GIL_RATIO * rate_many)
        decisions.append({"load_pct": load, "rate_one_worker": rate_one,
                          "rate_sixteen": rate_many, "the_lock_sets_it": lock,
                          "order_share_one_worker": _share(
                              sum(int(r["S_neg_Sk_neg"]) for r in one),
                              sum(int(r["S_neg"]) for r in one))})
    out["K-e"] = {"decision": decisions}
    return out


def judge_parity(rows, bins):
    """Block R's predictions."""
    out = {}
    for name, field, pooled in (("R-a", "S_neg", True), ("R-b", "dack_p99", False)):
        checks = []
        for backend in ("kafka", "redis"):
            on_rows = [r for r in rows if r["backend"] == backend
                       and r["sched_features"] != "NO_RUN_TO_PARITY"]
            off_rows = [r for r in rows if r["backend"] == backend
                        and r["sched_features"] == "NO_RUN_TO_PARITY"]
            if pooled:
                on = _share(sum(int(r["S_neg"]) for r in on_rows),
                            sum(int(r["timed"]) for r in on_rows))
                off = _share(sum(int(r["S_neg"]) for r in off_rows),
                             sum(int(r["timed"]) for r in off_rows))
            else:
                on = _median([float(r[field]) for r in on_rows if r[field] not in (None, "")])
                off = _median([float(r[field]) for r in off_rows if r[field] not in (None, "")])
            holds = None not in (on, off) and off <= RTP_RATIO * on
            checks.append({"backend": backend, "on": on, "off": off, "holds": holds})
        out[name] = {"verdict": _verdict(checks), "checks": checks}
    return out


def _slope(points):
    """The least-squares slope of (x, y) points; None for fewer than two distinct x."""
    xs = [x for x, _ in points]
    if len(set(xs)) < 2:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(y for _, y in points)
    return (sum((x - mx) * (y - my) for x, y in points)
            / sum((x - mx) ** 2 for x in xs))


def judge_control(rows, bins):
    """Block P's predictions; W_so and D in us against the delay in ms, so a slope of 1,000 us per
    ms is one for one."""
    out = {}
    for name, field in (("P-a", "Wso_median"), ("P-c", "D_median")):
        checks = []
        for backend in ("kafka", "redis"):
            points = [(float(d), _value(rows, field, backend=backend, delay_ms=d))
                      for d in sorted(set(r["delay_ms"] for r in rows if r["backend"] == backend))]
            points = [(x, y) for x, y in points if y is not None]
            slope = _slope(points)
            per_ms = None if slope is None else slope / 1e3
            checks.append({"backend": backend, "slope_ms_per_ms": per_ms,
                           "holds": per_ms is not None and SLOPE[0] <= per_ms <= SLOPE[1]})
        out[name] = {"verdict": _verdict(checks), "checks": checks}
    checks = []
    for backend in ("kafka", "redis"):
        values = [_value(rows, "A_median", backend=backend, delay_ms=d)
                  for d in sorted(set(r["delay_ms"] for r in rows if r["backend"] == backend))]
        values = [v for v in values if v is not None]
        move = (max(values) - min(values)) / min(values) if values and min(values) else None
        checks.append({"backend": backend, "move": move,
                       "holds": move is not None and move <= A_MOVE})
    out["P-b"] = {"verdict": _verdict(checks), "checks": checks}
    return out


def judge_ladder(rows, bins):
    """Block L's predictions, rung by rung."""
    out = {}
    checks = []
    for setup in _setups(rows):
        v = _value(rows, "Dif_median", setup=setup)
        checks.append({"setup": setup, "median_us": v, "holds": v is not None and v <= AGREE_US})
    out["L-a"] = {"verdict": _verdict(checks), "checks": checks}
    checks = []
    for rate in sorted(set(r["rate"] for r in rows)):
        for backend in ("kafka", "redis"):
            idle = _value(rows, "Wso_median", rate=rate, backend=backend, load_pct=0)
            busy = _value(rows, "Wso_median", rate=rate, backend=backend, load_pct=88)
            holds = None not in (idle, busy) and abs(busy - idle) <= LADDER_MOVE * idle
            checks.append({"rate": rate, "backend": backend, "idle": idle, "busy": busy,
                           "holds": holds})
    out["L-b"] = {"verdict": _verdict(checks), "checks": checks,
                  "holds_at_rates": sorted(set(c["rate"] for c in checks) - set(
                      c["rate"] for c in checks if not c["holds"]))}
    checks, described = [], []
    for setup in _setups(rows):
        flagged, known = _sum(rows, "flagged", setup=setup), _sum(rows, "flag_known", setup=setup)
        reads, multi = _sum(rows, "reads", setup=setup), _sum(rows, "reads_multi", setup=setup)
        neg, count = _sum(rows, "S_neg", setup=setup), _sum(rows, "S_count", setup=setup)
        rate = next(r["rate"] for r in rows if r["setup"] == setup)
        entry = {"setup": setup, "rate": rate, "flagged_share": _share(flagged, known),
                 "Wso_flagged": _value(rows, "Wso_flagged_median", setup=setup),
                 "Wso_unflagged": _value(rows, "Wso_unflagged_median", setup=setup),
                 "multi_packet_read_share": _share(multi, reads),
                 "negative_span_rate": _share(neg, count)}
        described.append(entry)
        if rate == 50:
            share = entry["flagged_share"]
            checks.append(dict(entry, holds=share is not None and share <= FLAG_SHARE_AT_50))
    out["L-c"] = {"verdict": _verdict(checks), "checks": checks, "described": described}
    return out


def judge_idle(rows, bins):
    """Block I: the decision on Redis's mode between -250 and -150 us, and d_ack, described."""
    shares = {}
    for poll in (False, True):
        picked = [r for r in rows if r["backend"] == "redis" and r["idle_poll"] == poll]
        shares[poll] = _share(sum(int(r["bump"]) for r in picked),
                              sum(int(r["S_neg"]) for r in picked))
    idle_wake = (None if shares[False] is None or shares[True] is None
                 else shares[True] <= BUMP_CUT * shares[False])
    described = []
    for backend in ("kafka", "redis"):
        for poll in (False, True):
            described.append({
                "backend": backend, "idle_poll": poll,
                "dack_median": _value(rows, "dack_median", backend=backend, idle_poll=poll),
                "dack_waited_share": _share(
                    _sum(rows, "dack_waited", backend=backend, idle_poll=poll),
                    _sum(rows, "timed", backend=backend, idle_poll=poll))})
    return {"I": {"decision": {"bump_share_default": shares[False], "bump_share_poll": shares[True],
                               "the_mode_is_idle_wake": idle_wake},
                  "described": described}}


JUDGES = {"K": judge_order, "R": judge_parity, "P": judge_control, "L": judge_ladder,
          "I": judge_idle}


# --- files -----------------------------------------------------------------------------------------

def block_runs(folders, block):
    """[(run folder, its integrity verdict)] for every run of the block, by its setup's prefix,
    as full_fix.block_runs finds F1's."""
    found = []
    for folder in folders:
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if not name.startswith("law_") or not os.path.isdir(path):
                continue
            if setup_of(path)[0].startswith(PREFIX[block]):
                found.append((path, rw.read_json(os.path.join(path, "integrity.json"))
                              .get("verdict")))
    return found


def read_block(folders, block, driver, broker, receiver, warmup_s):
    """(run rows, bin rows, [(run, verdict)] for the runs the integrity rule did not pass)."""
    rows, bins, pooled, skipped = [], [], {}, []
    for path, verdict in block_runs(folders, block):
        if verdict != rw.PASSING:
            skipped.append((os.path.basename(path), verdict or "not judged"))
            continue
        row, msgs = READERS[block](path, driver, broker, receiver, warmup_s)
        rows.append(row)
        if (block == "K" and row["load_pct"] == 88 and not row["priority"]
                and not row["workers"]):
            pooled.setdefault(row["setup"], []).extend(msgs)
    for setup in sorted(pooled):
        bins += bins_by_margin(setup, pooled[setup])
    return rows, bins, skipped


def write_csv(path, rows):
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def read_table(path):
    """Rows of a table this program wrote, with its typed columns put back."""
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for key in ("load_pct", "rate", "delay_ms"):
            if r.get(key) not in (None, ""):
                r[key] = int(float(r[key]))
        for key in ("priority", "idle_poll"):
            if key in r:
                r[key] = {"True": True, "False": False}.get(r[key], r[key])
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("read")
    p.add_argument("--block", required=True, choices=sorted(PREFIX))
    p.add_argument("--runs", action="append", required=True)
    for name in ("--driver", "--broker", "--receiver"):
        p.add_argument(name, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--quintiles", default=None)
    p.add_argument("--warmup", type=float, default=rw.WARMUP_S)
    p = sub.add_parser("judge")
    p.add_argument("--block", required=True, choices=sorted(PREFIX))
    p.add_argument("--table", required=True)
    p.add_argument("--quintiles", default=None)
    p.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "read":
        rows, bins, skipped = read_block(args.runs, args.block, args.driver, args.broker,
                                         args.receiver, args.warmup)
        write_csv(args.out, rows)
        if args.quintiles:
            write_csv(args.quintiles, bins)
        for run, verdict in skipped:
            print("left out %s: %s" % (run, verdict))
        print("OK %d runs of block %s -> %s" % (len(rows), args.block, args.out))
        return 0
    rows = read_table(args.table)
    verdicts = JUDGES[args.block](rows, read_table(args.quintiles))
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(verdicts, fh, indent=2, sort_keys=True)
        fh.write("\n")
    for name in sorted(verdicts):
        print("%s: %s" % (name, verdicts[name].get("verdict", "decision recorded")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
