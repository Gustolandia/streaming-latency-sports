#!/usr/bin/env python3
"""
under_load_posthoc.py -- freeze 43's block U read again after its verdicts, as the general method
reads any run. Everything this writes is post hoc: none of it was registered, none of it changes a
verdict, and every place it is reported says so.

The general method has four parts. Block U's own runs show three of them:

1. Kernel timestamps on the client machine, for every packet. Block U's clients took them on their
   sockets, one per read, and the client host's captures took them again, one per packet;
   under_load.py compares the two (Dif in u_runs.csv), and client_wire.py matches the captures by
   the broker's own ids. The check below is read both ways: from the sockets, and from the
   captures alone, as a tool that changes nothing in its client would read it.
2. A check any tool can run from those timestamps: was a request waiting at the broker when each
   message arrived? A message whose delivering request left the consumer after the producer had its
   acknowledgment surely found none, for

       t_req - t_rx_ack = (F_in - A_out) - C,   C = (the request's way up) + (the ack's way down),

   the two hosts' clocks cancelling, so t_req > t_rx_ack gives F_in > A_out whatever C is. C has a
   floor on each pair of connections, which the clients can estimate from their own round trips:

       C_hat = (least acknowledgment round trip on the producer's connection)
             + (least round trip on the consumer's connection of a request that cannot have waited)
             - (least W_so over the pair's messages)
             - allowance

   A request cannot have waited at the broker if it asks for no messages (an acknowledgment, a
   commit), or if its answer carried a message the certain reading shows was stored before it
   left. Each least value carries one broker service time and the two crossings of its
   connections, so what is left is the pair's own two crossings and the broker's least service
   times, which the allowance, set once per broker from a pilot's broker capture, takes off. Each
   least value is taken only where TRIANGLE_MIN values give it: a pair, a producer's connection or
   a consumer's with fewer has no estimate, and its messages only the certain reading.

   The check reads to a resolution of RESOLUTION_US: a message found no request waiting where it
   sat stored at the broker longer than that before its request came. A message whose request came
   within it carries no more than it of the client's time. By the certain reading that is where
   t_req - t_rx_ack > RESOLUTION_US, and by the estimate where t_req - t_rx_ack + C_hat >
   RESOLUTION_US. Both are checked here, message by message, against the broker's own record: the
   delivering request reached the broker more than RESOLUTION_US after the acknowledgment left it
   (none), before the message arrived (waiting), or in between (close).
3. Three latencies, each named:
   - D: what reaches the application;
   - W: what reaches this client's kernel;
   - F: what the broker and the network deliver to a ready receiver, ready as the protocol allows.
   Redis can keep a request waiting, so its F is E3: W less the time the message sat stored.
   Kafka cannot. The most a Kafka client can do is ask again at once, so its F is E2: W less what
   the thread added (b_min), with the round trip kept as real latency. Each is given from the
   broker's capture and, by the estimate above, from the clients' timestamps alone.
4. The remedy, requests kept waiting, is not in block U. Blocks V, N, K and P test it.

Beside them, the verdicts' own robustness:
- U-b and U-d on W_so less its pair's path floor, and U-d on the rise, (normal - real-time) /
  (normal - idle);
- every verdict and decision again with each run left out;
- a census of the stalls.

CLI:
    python scripts/under_load_posthoc.py calibrate --runs FOLDER [--runs ...] --driver IP \
        --broker IP --receiver IP --out JSON
    python scripts/under_load_posthoc.py read --runs FOLDER [--runs ...] --driver IP --broker IP \
        --receiver IP --allowance JSON --judged-runs CSV --out-runs CSV --out JSON
"""
import argparse
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import client_wire as cw  # noqa: E402
import full_fix as ff  # noqa: E402
import kafka_wire as kw  # noqa: E402
import order_scope as osc  # noqa: E402
import recv_wait as rw  # noqa: E402
import so_journal as sj  # noqa: E402
import under_load as ul  # noqa: E402

#: A message delayed this long, in microseconds, is part of a stall.
STALL_US = 50000.0

#: The allowance is rounded up to this step, in microseconds, so that it is never set to the
#: pilot's own last microsecond.
ALLOWANCE_STEP_US = 5.0

#: The check's resolution, in microseconds: a tenth of the gap between messages at 2,000 a second,
#: and above the broker's least service time, which C_hat carries before the allowance. Chosen
#: after reading block U, which is why every result here is post hoc.
RESOLUTION_US = 50.0

#: How many values each of the triangle's least values needs: the path floors' own rule.
TRIANGLE_MIN = ul.FLOOR_MIN

#: The requests that ask for messages, by the name client_wire gives each kind.
ASKING = frozenset(cw.ASKS) | frozenset([kw.api_name(sj.FETCH)])

#: The check's three readings: the certain one, which needs nothing but causality, and the
#: estimate with C_hat before and after the allowance.
READINGS = ("certain", "raw", "calibrated")

#: What each broker's ready receiver is: a request always waiting (E3), or one asked again at once
#: (E2).
READY = {"redis": "E3", "kafka": "E2"}

#: The census's fields per run.
CENSUS = ("stall_n", "stall_from_s", "stall_to_s", "stall_max_ms")

#: What each setup's summary gives, the median over its runs.
SETUP_FIELDS = ("broker_none_share", "broker_none0_share", "certain_none_share",
                "raw_none_share", "calibrated_none_share", "certain_agree", "raw_agree",
                "calibrated_agree", "wait_err_raw_p50", "wait_err_raw_p99",
                "cap_certain_none_share", "cap_raw_none_share", "cap_calibrated_none_share",
                "cap_certain_agree", "cap_raw_agree", "cap_calibrated_agree",
                "cap_wait_err_raw_p50", "cap_wait_err_raw_p99",
                "W_p50", "W_p99", "D_p50", "D_p99", "Fb_p50", "Fb_p99", "Fc_p50", "Fc_p99",
                "WF_p50", "WF_p99", "DW_p50", "DW_p99", "tri_over_share", "gap_smin_p50",
                "gap_tri_p50")


def _p(values, q):
    return rw.percentile(values, q) if values else None


def _share(part, whole):
    return part / float(whole) if whole else None


def _min_by(pairs, least=1):
    """{key: the least value} from (key, value) pairs, for each key with at least `least` values;
    a None key or value is left out."""
    out, counts = {}, {}
    for key, value in pairs:
        if key is None or value is None:
            continue
        counts[key] = counts.get(key, 0) + 1
        if key not in out or value < out[key]:
            out[key] = value
    return dict((k, v) for k, v in out.items() if counts[k] >= least)


# --- the check -----------------------------------------------------------------------------------

def found(broker):
    """What the broker's own capture says a message found: "none" where its delivering request
    reached the broker more than RESOLUTION_US after the acknowledgment left it, "waiting" where
    the request was there before the message arrived, "close" in between; None where a time is
    missing."""
    if broker is None or None in broker[:3]:
        return None
    p_in, a_out, f_in = broker[:3]
    if f_in - a_out > RESOLUTION_US * 1e3:
        return "none"
    return "waiting" if f_in <= p_in else "close"


def request_floors(conns, backend, stored_first):
    """{consumer connection's local port: the least round trip, us, of its requests that cannot
    have waited at the broker}: those that ask for no messages, and those whose answer carried a
    message in `stored_first`, the event ids the certain reading shows were stored before their
    request left."""
    found_ = []
    for conn in conns.values():
        for request_end, answer_start, answer_end, asks in ul.requests_on(conn, backend):
            if asks and not any(eid in stored_first
                                for eid in sj.ids_in(conn.inb, answer_start, answer_end)):
                continue
            t_req = sj.tx_at(conn, request_end - 1)
            t_ans = sj.rx_at(conn, answer_end - 1)
            if t_req is not None and t_ans is not None:
                found_.append((conn.local_port, (t_ans - t_req) / 1e3))
    return _min_by(found_, TRIANGLE_MIN)


def crossing_floors(parts, fetch_min):
    """({pair: C_hat before the allowance}, {pair: the least C the broker's capture shows}), for
    each pair of connections with every value it needs, each from at least TRIANGLE_MIN values."""
    ack_min = _min_by(((p["pair"][0], p["ack_rtt"]) for p in parts), TRIANGLE_MIN)
    w_min = _min_by(((p["pair"], p["W"]) for p in parts), TRIANGLE_MIN)
    raw = {pair: ack_min[pair[0]] + fetch_min[pair[1]] - w for pair, w in w_min.items()
           if pair[0] in ack_min and pair[1] in fetch_min}
    return raw, _min_by((p["pair"], p["C"]) for p in parts)


def readings(p, lift, cut):
    """The check's three readings for one message: whether it found no request waiting, to the
    check's resolution, by causality alone, by C_hat before the allowance (`lift`) and after it
    (`cut`); None where the estimate has no value."""
    return {"certain": p["slack"] > RESOLUTION_US,
            "raw": None if lift is None else p["slack"] + lift > RESOLUTION_US,
            "calibrated": None if lift is None or cut is None
            else p["slack"] + lift - cut > RESOLUTION_US}


def ready_latencies(p, c_hat):
    """Adds to one message the latencies a ready receiver would see: E2 and E3 from the broker's
    capture (E2b, E3b), from the clients' timestamps alone with C_hat (E2c, E3c), and the bound the
    estimate puts on what the thread added (s_tri)."""
    waited = max(0.0, p["slack"] + max(0.0, c_hat))
    p["s_tri"] = min(p["Tc"], waited)
    p["E2c"], p["E3c"] = p["W"] - p["s_tri"], p["W"] - waited
    p["E2b"] = p["Fb"]
    p["E3b"] = None if p["stored"] is None else p["W"] - p["stored"]


def _check_fields(prefix, parts, raw, true, cut):
    """The check's fields for one run under `prefix`: for each reading, how many messages it
    reached, the share it calls unwaited, and against the broker's record its agreement, its false
    calls and its misses; and the median and 99th percentile of the estimate's error on each
    message's wait at the broker."""
    row = {prefix + "pairs": len(raw),
           prefix + "overshoot_max_us": max((raw[k] - true[k] for k in raw if k in true),
                                            default=None)}
    for p in parts:
        lift = raw.get(p["pair"])
        p["none"] = readings(p, lift, cut)
        p["S_raw"] = None if lift is None else max(0.0, p["slack"] + lift)
    judged = [p for p in parts if p["found"] is not None]
    errors = [abs(p["S_raw"] - p["stored"]) for p in judged if p["S_raw"] is not None]
    row[prefix + "wait_err_raw_p50"], row[prefix + "wait_err_raw_p99"] = (_p(errors, 50),
                                                                          _p(errors, 99))
    for reading in READINGS:
        said = [p for p in parts if p["none"][reading] is not None]
        row[prefix + reading + "_n"] = len(said)
        row[prefix + reading + "_none_share"] = _share(sum(1 for p in said
                                                           if p["none"][reading]), len(said))
        both = [p for p in said if p["found"] is not None]
        row[prefix + reading + "_agree"] = _share(
            sum(1 for p in both if p["none"][reading] == (p["found"] == "none")), len(both))
        row[prefix + reading + "_false_none"] = sum(
            1 for p in both if p["none"][reading] and p["found"] != "none")
        row[prefix + reading + "_missed_none"] = sum(
            1 for p in both if not p["none"][reading] and p["found"] == "none")
    return row


def capture_check(messages, exchanges, at_broker, cut_ns, cut=None):
    """The check again from the client host's captures alone, as client_wire reads them: per
    packet, each message named by the broker's own id, its delivering request's departure
    against its acknowledgment's arrival, and C_hat from the captures' own round trips.
    `messages` and `exchanges` are client_wire's rows, `at_broker` the broker's times by event
    id, against which alone the event id is read, and `cut_ns` the end of the warm-up. The
    fields are named cap_."""
    by_exchange = dict(((r["consumer_port"], r["exchange"]), r) for r in exchanges)
    parts = []
    for m in messages:
        ex = by_exchange.get((m["consumer_port"], m["exchange"]))
        if None in (m["t_depart"], m["t_ack"], m["t_arrive"]) or ex is None or ex["t_req"] is None:
            continue
        if m["t_depart"] < cut_ns:
            continue
        b = at_broker.get(m["eid_got"])
        p = {"W": (m["t_arrive"] - m["t_depart"]) / 1e3, "slack": (ex["t_req"] - m["t_ack"]) / 1e3,
             "ack_rtt": (m["t_ack"] - m["t_depart"]) / 1e3, "found": found(b),
             "pair": (m["producer_port"], m["consumer_port"]),
             "request": (m["consumer_port"], m["exchange"])}
        p["stored"] = None if p["found"] is None else max(0, b[2] - b[1]) / 1e3
        p["C"] = None if p["found"] is None else (b[2] - b[1]) / 1e3 - p["slack"]
        parts.append(p)
    stored_first = set(p["request"] for p in parts if p["slack"] > 0)
    fetch_min = _min_by(((r["consumer_port"], (r["t_ans"] - r["t_req"]) / 1e3) for r in exchanges
                         if None not in (r["t_req"], r["t_ans"])
                         and (r["kind"] not in ASKING
                              or (r["consumer_port"], r["exchange"]) in stored_first)),
                        TRIANGLE_MIN)
    raw, true = crossing_floors(parts, fetch_min)
    row = {"cap_timed": len(parts)}
    row.update(_check_fields("cap_", parts, raw, true, cut))
    return row


def census(parts, first):
    """The run's stall: how many messages took longer than STALL_US, from when to when in seconds
    after the run's first send, and the longest, in ms; a count of 0 and Nones where none did."""
    slow = sorted((p for p in parts if p["W"] > STALL_US), key=lambda p: p["pub"])
    if not slow or first is None:
        return dict(zip(CENSUS, (len(slow), None, None, None)))
    return {"stall_n": len(slow), "stall_from_s": (slow[0]["pub"] - first) / 1e9,
            "stall_to_s": (slow[-1]["pub"] - first) / 1e9,
            "stall_max_ms": max(p["W"] for p in slow) / 1e3}


# --- one run -------------------------------------------------------------------------------------

def read_run(run_dir, driver, broker, receiver, allowance=None, warmup_s=ul.WARMUP_S):
    """(one run's post hoc row, its split as under_load.read_run gives it). C_hat is taken less
    the allowance for the run's broker, `allowance` being {"sockets": {broker: us}, "capture":
    {broker: us}}; the calibrated reading has no value without one. The check is read from the
    sockets and, where the run holds both client captures, from the captures alone."""
    setup, params, msgs = osc.messages(run_dir, warmup_s)
    backend = params.get("backend")
    conns = sj.load(os.path.join(run_dir, "consumer_journal"))
    _, by_id = ul.turnarounds(conns, backend)
    sent_on = ul.producer_ports(os.path.join(run_dir, "producer_journal"))
    at_broker = ul.broker_times(os.path.join(run_dir, "broker_full.pcap"), osc.PORTS[backend],
                                driver, receiver, backend)
    at_card = ff.card_times(run_dir, broker, receiver)
    switches = ul.load_switches(run_dir)
    parts = []
    for m in msgs:
        got = by_id.get(m["eid"])
        if got is None:
            continue
        b = at_broker.get(m["eid"])
        p = ul.message_parts(m, got, b, at_card.get(m["eid"]))
        if p is None:
            continue
        p["pair"] = (sent_on.get(m["eid"]), got[4])
        p["state"] = ul.block_state(switches, m["tx_so"])
        p["pub"], p["eid"] = m["pub"], m["eid"]
        p["slack"] = (got[0] - m["rx_ack"]) / 1e3
        p["ack_rtt"] = (m["rx_ack"] - m["tx_so"]) / 1e3
        p["found"] = found(b)
        p["C"] = None if p["found"] is None else (b[2] - b[1]) / 1e3 - p["slack"]
        parts.append(p)
    floors = ul.path_floors(parts)
    stored_first = set(p["eid"] for p in parts if p["slack"] > 0)
    raw, true = crossing_floors(parts, request_floors(conns, backend, stored_first))
    allowance = allowance or {}
    cut = allowance.get("sockets", {}).get(backend)
    for p in parts:
        p["floor"] = floors.get(p["pair"]) if p["net"] is not None else None
        p["excess"] = None if p["floor"] is None else p["net"] - p["floor"]
        p["G"] = None if p["hand"] is None else p["Fb"] - p["floor"]
        lift = raw.get(p["pair"])
        ready_latencies(p, 0.0 if lift is None or cut is None else lift - cut)
    rate, _, load, realtime = ul.setup_parts(setup)
    row = {"run": os.path.basename(run_dir), "setup": setup, "rate": rate, "backend": backend,
           "load_pct": load, "priority": realtime, "blocks": ul.in_blocks(setup),
           "timed": len(parts), "allowance_us": cut}
    row.update(_check_fields("", parts, raw, true, cut))
    judged = [p for p in parts if p["found"] is not None]
    row["broker_found"] = len(judged)
    row["broker_none0_share"] = _share(sum(1 for p in judged if p["stored"] > 0), len(judged))
    for kind in ("none", "waiting", "close"):
        row["broker_%s_share" % kind] = _share(sum(1 for p in judged if p["found"] == kind),
                                               len(judged))
    first = min((pub for _, pub, _ in rw.messages(run_dir, 0.0)), default=None)
    row["cap_allowance_us"] = allowance.get("capture", {}).get(backend)
    captured = all(os.path.exists(os.path.join(run_dir, name))
                   for name in ("sender_full.pcap", "receiver_full.pcap"))
    if captured and first is not None:
        messages, exchanges, _ = cw.read_run(run_dir, driver, broker, receiver)
        row.update(capture_check(messages, exchanges, at_broker, first + int(warmup_s * 1e9),
                                 row["cap_allowance_us"]))
    ready = READY.get(backend)
    for name in ("W", "D", "E2b", "E3b", "E2c", "E3c"):
        values = [p[name] for p in parts if p[name] is not None]
        row[name + "_p50"], row[name + "_p99"] = _p(values, 50), _p(values, 99)
    for side in ("b", "c"):
        for q in ("p50", "p99"):
            row["F%s_%s" % (side, q)] = row["%s%s_%s" % (ready, side, q)] if ready else None
    gaps = (("WF", [p["W"] - p[ready + "b"] for p in parts
                    if ready and p[ready + "b"] is not None]),
            ("DW", [p["D"] - p["W"] for p in parts if p["D"] is not None]),
            ("Wfloor", [p["W"] - p["floor"] for p in parts if p["floor"] is not None]))
    for name, values in gaps:
        row[name + "_p50"], row[name + "_p99"] = _p(values, 50), _p(values, 99)
    bounded = [p for p in parts if p["b_min"] is not None]
    over = [p["s_tri"] - p["b_min"] for p in bounded if p["s_tri"] > p["b_min"]]
    row["tri_over_share"] = _share(len(over), len(bounded))
    row["tri_over_max_us"] = max(over) if over else (0.0 if bounded else None)
    row["gap_smin_p50"] = _p([p["b_min"] - p["s_min"] for p in bounded], 50)
    row["gap_tri_p50"] = _p([p["b_min"] - p["s_tri"] for p in bounded], 50)
    row.update(census(parts, first))
    split = [tuple(p["q_term"] if name == "Q" else p[name] for name in ul.SPLIT_FIELDS)
             + (p["state"],) for p in parts if p["G"] is not None]
    row["pooled"] = bool(parts) and len(split) >= ul.SPLIT_SHARE * len(parts)
    return row, split


# --- the block -----------------------------------------------------------------------------------

def decisions_without(splits, idle_setup, busy_setup, prefix, busy_prefix=None):
    """(the decision on every pooled run, [(run left out, its decision)]): U-e's or U-f's naming,
    (the term named, the rise), with each run of the two setups left out in turn. `splits` is
    {(setup, run): split}, the pooled runs only."""
    def named(skip):
        pooled = {idle_setup: [], busy_setup: []}
        runs = {idle_setup: 0, busy_setup: 0}
        for (setup, run), split in sorted(splits.items()):
            if setup in pooled and run != skip:
                pooled[setup] += split
                runs[setup] += 1
        decision = ul.name_the_term(ul.tail_summary(idle_setup, pooled[idle_setup],
                                                    runs[idle_setup]),
                                    ul.tail_summary(busy_setup, pooled[busy_setup],
                                                    runs[busy_setup]),
                                    prefix, busy_prefix)
        return decision["named"], decision["rise"]
    runs = sorted(run for setup, run in splits if setup in (idle_setup, busy_setup))
    return named(None), [(run, named(run)) for run in runs]


def read_block(folders, driver, broker, receiver, allowance=None, warmup_s=ul.WARMUP_S,
               pilot=False):
    """(post hoc rows, {(rate, broker): U-e's or U-f's decisions with each run left out}). The
    runs are read one cell at a time, so that no more than one cell's messages are held at once,
    and a run enters a decision's pool by under_load's own rule."""
    found_, _, _ = ul.block_runs(folders, pilot)
    by_cell = {}
    for setup in found_:
        rate, backend, _, _ = ul.setup_parts(setup)
        by_cell.setdefault((rate, backend), []).append(setup)
    rows, decided = [], {}
    for cell in sorted(by_cell):
        splits = {}
        for setup in sorted(by_cell[cell]):
            for path in found_[setup]:
                row, split = read_run(path, driver, broker, receiver, allowance, warmup_s)
                rows.append(row)
                if row["pooled"]:
                    splits[(setup, row["run"])] = split
        parts = {s: ul.setup_parts(s) for s in by_cell[cell]}
        idle = [s for s in sorted(parts) if parts[s][2] == 0]
        busy = [s for s in sorted(parts) if parts[s][2] and not parts[s][3]]
        blocks = [s for s in busy if ul.in_blocks(s)]
        if cell[0] == ul.TRACE_RATE and blocks:
            decided[cell] = decisions_without(splits, blocks[0], blocks[0], "off", "on")
        elif cell[0] != ul.TRACE_RATE and idle and busy:
            decided[cell] = decisions_without(splits, idle[0], busy[0], "tail")
    return rows, decided


def calibrate(rows):
    """{"sockets": {broker: allowance in us}, "capture": {broker: allowance in us}}: for each
    instrument, each broker's largest overshoot of C_hat over the least C the broker's capture
    shows, over the pilot's pairs, rounded up to ALLOWANCE_STEP_US and never below zero."""
    found_ = {}
    for instrument, field in (("sockets", "overshoot_max_us"),
                              ("capture", "cap_overshoot_max_us")):
        out = {}
        for r in rows:
            v = r.get(field)
            if v is not None:
                out[r["backend"]] = max(out.get(r["backend"], v), v)
        found_[instrument] = dict((b, max(0.0, math.ceil(v / ALLOWANCE_STEP_US)
                                          * ALLOWANCE_STEP_US)) for b, v in out.items())
    return found_


# --- the verdicts again --------------------------------------------------------------------------

def _median(rows, field, **match):
    values = [ul._float(r.get(field)) for r in rows
              if all(r.get(k) == v for k, v in match.items())]
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def floored(rows):
    """U-b and U-d again, on W_so's 99th percentile as it is and less each pair's path floor, and
    U-d on the rise: per cell the growth under load, the ratio real-time priority leaves, and the
    share of the rise it takes back, each setup's value the median over its runs."""
    out = []
    for rate, backend in ul._cells():
        pick = dict(rate=rate, backend=backend)
        load = ul.loaded_level(rows, rate, backend)
        entry = dict(pick)
        for name, field in (("raw", "W_p99"), ("floored", "Wfloor_p99")):
            idle = _median(rows, field, load_pct=0, priority=False, **pick)
            busy = _median(rows, field, load_pct=load, priority=False, **pick)
            rt = _median(rows, field, load_pct=load, priority=True, **pick)
            known = None not in (idle, busy, rt)
            entry[name + "_growth"] = busy / idle if known else None
            entry[name + "_rt_ratio"] = rt / busy if known else None
            entry[name + "_rise_taken"] = ((busy - rt) / (busy - idle)
                                           if known and busy > idle else None)
        out.append(entry)
    return out


def _cell_holds(rows, draws):
    """{(prediction, rate, broker): whether the cell holds} for U-a to U-d and U-c's only-path
    decision, judged as under_load judges them, and {prediction: verdict}."""
    v = {"U-a": ul.judge_turnaround(rows), "U-b": ul.judge_fix_alone(rows)}
    v["U-c"] = ul.judge_removal(rows, set(map(tuple, v["U-b"]["gives_way_at"])), draws)
    v["U-d"] = ul.judge_priority(rows)
    cells = {}
    for name in sorted(v):
        for c in v[name]["checks"]:
            cells[(name, c["rate"], c["backend"])] = c["holds"]
            if name == "U-c":
                cells[("U-c only path", c["rate"], c["backend"])] = c["only_path"]
    return cells, {name: v[name]["verdict"] for name in v}


def leave_one_out(judged_rows, draws=ul.BOOTSTRAP):
    """Every verdict again with each judged run left out: [(prediction, rate, broker, run left
    out, held with it, held without)] wherever a cell changes, and [(run left out, prediction,
    verdict with it, verdict without)] wherever a verdict does."""
    cells, verdicts = _cell_holds(judged_rows, draws)
    flips, changed = [], []
    for r in judged_rows:
        rest = [x for x in judged_rows if x is not r]
        now, said = _cell_holds(rest, draws)
        flips += [key + (r["run"], cells[key], now[key]) for key in sorted(cells)
                  if now[key] != cells[key]]
        changed += [(r["run"], name, verdicts[name], said[name]) for name in sorted(verdicts)
                    if said[name] != verdicts[name]]
    return flips, changed


def by_setup(rows):
    """Each setup's medians over its runs of SETUP_FIELDS."""
    out = []
    for setup in sorted(set(r["setup"] for r in rows)):
        runs = [r for r in rows if r["setup"] == setup]
        entry = {"setup": setup, "runs": len(runs)}
        entry.update((field, _median(runs, field)) for field in SETUP_FIELDS)
        out.append(entry)
    return out


def summary(rows, decided, judged_rows, draws=ul.BOOTSTRAP):
    """Everything the read writes besides its rows."""
    flips, changed = leave_one_out(judged_rows, draws)
    totals = {}
    for reading in READINGS:
        totals[reading] = {k: sum(int(r[reading + "_" + k]) for r in rows)
                           for k in ("n", "false_none", "missed_none")}
    tri = [r for r in rows if r["tri_over_share"] is not None]
    return {
        "post_hoc": True,
        "setups": by_setup(rows),
        "check_totals": totals,
        "floored": floored(rows),
        "leave_one_out": {"cells": flips, "verdicts": changed},
        "decisions_without_a_run": {"%d %s" % cell: {"all_runs": d[0], "without": d[1]}
                                    for cell, d in sorted(decided.items())},
        "tri_valid": {"runs": len(tri),
                      "over_b_min_share_max": max((r["tri_over_share"] for r in tri),
                                                  default=None),
                      "over_b_min_max_us": max((r["tri_over_max_us"] for r in tri),
                                               default=None)},
        "stalls": [{k: r[k] for k in ("run", "setup") + CENSUS} for r in rows if r["stall_n"]],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("calibrate", "read"):
        p = sub.add_parser(name)
        p.add_argument("--runs", action="append", required=True)
        for flag in ("--driver", "--broker", "--receiver"):
            p.add_argument(flag, required=True)
        p.add_argument("--warmup", type=float, default=ul.WARMUP_S)
        p.add_argument("--out", required=True)
    p.add_argument("--allowance", required=True)
    p.add_argument("--judged-runs", required=True)
    p.add_argument("--out-runs", required=True)
    p.add_argument("--draws", type=int, default=ul.BOOTSTRAP)
    args = ap.parse_args(argv)
    if args.cmd == "calibrate":
        rows, _ = read_block(args.runs, args.driver, args.broker, args.receiver, None,
                             args.warmup, pilot=True)
        found_ = calibrate(rows)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(found_, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("allowance per instrument and broker, us, from %d pilot runs: %s"
              % (len(rows), json.dumps(found_, sort_keys=True)))
        return 0
    with open(args.allowance, encoding="utf-8") as fh:
        allowance = json.load(fh)
    rows, decided = read_block(args.runs, args.driver, args.broker, args.receiver, allowance,
                               args.warmup)
    osc.write_csv(args.out_runs, rows)
    out = summary(rows, decided, ul.read_table(args.judged_runs), args.draws)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("OK %d runs read again, post hoc -> %s" % (len(rows), args.out_runs))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
