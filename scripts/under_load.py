#!/usr/bin/env python3
"""
under_load.py -- freeze 42's reader and judge (plan version 45, docs/results/under_load/DESIGN.md):
the consumer's turnaround, where load and rate bite together, and where what remains lies.

Per message, on the driver's one clock, as freeze 41 read them (scripts/order_scope.py): t_tx_so and
t_rx_so from the clients' sockets, so W_so = t_rx_so - t_tx_so; t_rx_ack from the producer's
journal; t_req, the transmit timestamp of the request that delivered the message, from the
consumer's journal. New here, per request for messages k on a consumer connection (Kafka's fetch,
Redis's XREAD or XREADGROUP):

  t_req(k)    the transmit timestamp of the request's last byte
  t_ans(k)    the receive timestamp of the read that delivered its answer's last byte
  t_before(k) the receive timestamp of the answer to the request just before it on that
              connection, whatever that request asked
  T_c(k)    = t_req(k) - t_before(k)   the turnaround: the consumer's own time from an answer to
                                       its next request for messages, with no broker time or
                                       network crossing in it; a request sent before that answer
                                       came in counts as zero

and per message, for the request that delivered it,

  s_min = min(T_c, max(0, t_req - t_rx_ack))   what the thread surely added: the message was
                                               stored before its acknowledgment left the broker
  s_max = min(T_c, max(0, t_req - t_tx_so))    the most it can have added
  F     = W_so - s_min                         the thread-free latency (F_lo = W_so - s_max)

From the broker's own capture (broker_full.pcap, the broker's clock, differences only): P_in and
F_in, the arrivals of the last byte of the produce request that carried the message and of the
request that delivered it; A_out, the departure of its acknowledgment's last byte; R_out, the
departure of the byte that ends the message's own id in the answer that delivered it. R = R_out -
P_in is the broker's residence, and the broker-side saving range is
[min(T_c, max(0, F_in - A_out)), min(T_c, max(0, F_in - P_in))]. From the card's own receive
timestamp (freeze 39's instrument), put on the system's clock through samples of the card's
clock, Q = t_rx_so - t_card is the consumer kernel's receive processing. On one identity,

  F = (W_so - R - Q) + (R - s_min) + Q

the network crossings with the producer's sending path below its timestamp, the broker's
residence less the thread's saving, and the receive processing. Where no run of the block has
card timestamps, Q folds into the first term: every run's split carries it as zero, and the rows
say so. Otherwise a run without them, its card capture or its clock samples failed, has no split
and stays out of the pool.

Every value is in microseconds. A setup's value is the median over its passing runs of each run's
statistic, over the messages the journals time; U-e and U-f pool a setup's messages over its runs
whose split reaches at least SPLIT_SHARE of their timed messages, as the design says.

CLI:
    python scripts/under_load.py read --runs FOLDER [--runs ...] --driver IP --broker IP \
        --receiver IP --out-runs CSV --out-tails CSV [--warmup S] [--pilot]
    python scripts/under_load.py judge --runs-table CSV --tails-table CSV --out JSON \
        [--ladder-table CSV]
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import full_fix as ff  # noqa: E402
import order_scope as osc  # noqa: E402
import recv_wait as rw  # noqa: E402
import so_journal as sj  # noqa: E402

#: A judged setup's id: its rate, broker and load, and "-rt" at real-time priority. The pilot's
#: ids start "UP", so they never match it.
SETUP_ID = re.compile(r"^U(\d+)-(kafka|redis)-l(\d+)(-rt)?$")
PILOT_ID = re.compile(r"^UP(\d+)-(kafka|redis)-l(\d+)(-rt)?$")

#: Block U runs 70 s with a 20 s warm-up at every rate, as block L did.
WARMUP_S = 20.0

#: The rates U-a to U-e judge, and the rate U-f traces.
UPPER_RATES = (500, 2000)
TRACE_RATE = 50

#: U-a and U-b: how much larger a 99th percentile must be under load than idle. U-a and U-d: the
#: most of it real-time priority may leave. U-c: the least share of U-b's rise the turnaround must
#: remove, and the share at which the paper calls it the only path. U-e and U-f: the least share
#: of a rise that names its term.
GROWTH = 1.5
HALF = 0.5
ONLY_PATH = 0.9
NAMES_A_TERM = 0.5

#: The percentile above which U-e reads a setup's pooled messages as its tail.
TAIL_PERCENTILE = 99

#: The share of a run's timed messages its split must reach for the run to enter U-e's and U-f's
#: pool: a packet dropped from a capture leaves every later byte of its stream unread, so a run
#: whose split falls short would pool only the messages before the hole. It is F-c's 0.5%.
SPLIT_SHARE = 0.995

#: The split's three terms, in the order the design lists them.
TERMS = ("net", "brk", "Q")

#: The Redis commands that ask for messages. The consumer's connection also carries its
#: acknowledgments (XACK), which ask for none.
ASKS = (b"XREAD", b"XREADGROUP")

#: The broker capture's own log, where tcpdump says how many packets the kernel dropped.
BROKER_LOG = "broker_full.err"

#: The fields described setup by setup, beside the predictions.
DESCRIBED = ("Tc_p50", "trip_p50", "W_p50", "F_p50", "F_lo_p50", "F_lo_p99", "D_p50", "D_p99",
             "R_p50", "R_p99", "Q_p50", "Q_p99", "s_min_p50", "s_min_p99", "s_max_p50",
             "s_max_p99", "b_min_p50", "b_min_p99", "b_max_p50", "b_max_p99", "range_p50",
             "range_p99", "brange_p50", "brange_p99", "net_p50", "net_p99", "brk_p50", "brk_p99",
             "Dif_p50", "Dif_p99", "card_window_ns", "load_measured")


def _us(a, b):
    """(a - b) in microseconds, or None if either is missing."""
    return None if a is None or b is None else (a - b) / 1e3


def _median(values):
    return statistics.median(values) if values else None


def _p99(values):
    return rw.percentile(values, 99) if values else None


def _mean(values):
    return statistics.fmean(values) if values else None


def setup_parts(setup):
    """(rate, backend, load, real-time) from a judged or a pilot setup id; None for any other."""
    m = SETUP_ID.match(setup) or PILOT_ID.match(setup)
    if not m:
        return None
    return int(m.group(1)), m.group(2), int(m.group(3)), bool(m.group(4))


# --- the consumer's journal ----------------------------------------------------------------------

def command_name(data, start):
    """The first word of the RESP command that starts at `start`, upper-cased; b"" if none."""
    parts = data[start:start + 64].split(b"\r\n")
    return parts[2].upper() if len(parts) > 2 else b""


def requests_on(conn, backend):
    """[(request end, answer start, answer end, whether it asks for messages)] for every request
    on one connection with its answer, in order, paired by the wire format: Kafka's correlation
    id, Redis's order."""
    if backend == "kafka":
        answers = sj.kafka_responses(conn.inb)
        return [(e, answers[corr][0], answers[corr][1], key == sj.FETCH)
                for _, e, key, corr in sj.kafka_requests(conn.out) if corr in answers]
    return [(e, rs, re_, command_name(conn.out, s) in ASKS)
            for (s, e), (rs, re_) in zip(sj.resp_items(conn.out), sj.resp_items(conn.inb))]


def turnarounds(conns, backend):
    """Per request for messages on each consumer connection, in order, (t_req, t_ans, t_before);
    and {event id: (t_req, t_before)} for the request that delivered each message, its first
    delivery kept, as the journal's own reader keeps it."""
    per_request, by_id = [], {}
    for conn in conns.values():
        before = None
        for request_end, answer_start, answer_end, asks in requests_on(conn, backend):
            t_req = sj.tx_at(conn, request_end - 1)
            t_ans = sj.rx_at(conn, answer_end - 1)
            if asks:
                per_request.append((t_req, t_ans, before))
                for eid in sj.ids_in(conn.inb, answer_start, answer_end):
                    by_id.setdefault(eid, (t_req, before))
            before = t_ans
    return per_request, by_id


# --- the broker's capture ------------------------------------------------------------------------

def broker_streams(pcap, port):
    """{(client host, client port): {"in": Stream, "out": Stream}} from the broker's capture: what
    each client sent the broker's port, and what the broker sent back, each byte at the moment it
    was first captured."""
    streams = {}
    for ns, linktype, frame in rw.read_pcap(pcap):
        ip = rw.ip_payload(linktype, frame)
        seg = None if ip is None else rw.tcp_segment(ip)
        if seg is None or not seg[5]:
            continue
        if seg[3] == port:
            key, way = (seg[0], seg[2]), "in"
        elif seg[2] == port:
            key, way = (seg[1], seg[3]), "out"
        else:
            continue
        streams.setdefault(key, {}).setdefault(way, rw.Stream()).add(ns, seg[4], seg[5])
    return streams


def exchanges(inb, out, backend, api):
    """[(request start, request end, answer start, answer end)] on one connection, paired by the
    wire format: Kafka's correlation id, Redis's order. `api` picks Kafka's requests; each of a
    Redis client's connections carries one kind that carries ids."""
    if backend == "kafka":
        answers = sj.kafka_responses(out)
        return [(s, e) + answers[corr] for s, e, key, corr in sj.kafka_requests(inb)
                if key == api and corr in answers]
    return [(s, e, rs, re_) for (s, e), (rs, re_) in zip(sj.resp_items(inb), sj.resp_items(out))]


def ids_ending(data, start, end):
    """[(event id, offset of the byte that ends it)] for each id wholly inside data[start:end],
    once each, in the order of its first carrying. An id carried again within
    recv_wait.SAME_RECORD of its first carrying, as Kafka carries it in a record's key and its
    value, ends at its later carrying, which is where the consumer's socket and the card time it;
    one carried again further on is another message's, and is ignored."""
    first, last, order = {}, {}, []
    for m in rw.EVENT_ID.finditer(data, start, end):
        eid = m.group(0).decode("ascii")
        if eid not in first:
            first[eid] = m.start()
            order.append(eid)
        if m.start() - first[eid] <= rw.SAME_RECORD:
            last[eid] = m.end() - 1
    return [(eid, last[eid]) for eid in order]


def broker_times(pcap, port, driver, receiver, backend):
    """{event id: [P_in, A_out, F_in, R_out]} on the broker's clock, from its own capture, None
    where a time was not found. The producer's connections come from the driver's address and the
    consumer's from the receiver's.

    P_in and F_in are the arrivals of the last byte of the produce request and of the delivering
    request, when the broker could first act on each. A_out is the departure of the
    acknowledgment's last byte. R_out is the departure of the byte that ends the message's own id
    in the answer, the byte whose arrival the consumer's socket and the card time. An id carried
    again is a retry or a redelivery, and the carrying that reached the broker first is kept."""
    found = {}
    if not os.path.exists(pcap):
        return found
    for (host, _), pair in broker_streams(pcap, port).items():
        if host not in (driver, receiver) or "in" not in pair or "out" not in pair:
            continue
        inb, out = bytes(pair["in"].data), bytes(pair["out"].data)
        producing = host == driver
        api = sj.PRODUCE if producing else sj.FETCH
        at = 0 if producing else 2
        for s, e, rs, re_ in exchanges(inb, out, backend, api):
            arrived = pair["in"].readable(e - 1)
            carried = ids_ending(inb, s, e) if producing else ids_ending(out, rs, re_)
            for eid, last in carried:
                times = found.setdefault(eid, [None, None, None, None])
                if times[at] is not None and times[at] <= arrived:
                    continue
                times[at] = arrived
                times[at + 1] = pair["out"].readable(re_ - 1 if producing else last)
    return found


def broker_drops(run_dir):
    """How many packets the broker's kernel dropped from its capture, by tcpdump's own report;
    None where the run has no report or the report says nothing."""
    path = os.path.join(run_dir, BROKER_LOG)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as fh:
        said = ff.DROPPED.findall(fh.read())
    return int(said[-1]) if said else None


# --- the clients' captures, described ------------------------------------------------------------

def capture_agreement(run_dir, msgs, driver, broker, receiver):
    """[|W_so - W|] for the messages both client captures found, W timed from the captures as
    freeze 41's ladder timed it; [] where the run has either capture missing."""
    sent_path = os.path.join(run_dir, "sender_full.pcap")
    got_path = os.path.join(run_dir, "receiver_full.pcap")
    if not (os.path.exists(sent_path) and os.path.exists(got_path)):
        return []
    sent = ff.departure_times(sent_path, driver, broker)
    got = rw.kernel_times(got_path, broker, receiver)
    return [abs(m["Wso"] - _us(got[m["eid"]], sent[m["eid"]])) for m in msgs
            if m["Wso"] is not None and m["eid"] in sent and m["eid"] in got]


def reads_drained(run_dir, conns, backend, broker, receiver):
    """(reads, reads that drained more than one packet) on the consumer's connections, counted
    from the receiver's capture as freeze 41's ladder counted them; (0, 0) without that capture."""
    pcap = os.path.join(run_dir, "receiver_full.pcap")
    if not os.path.exists(pcap):
        return 0, 0
    segments = osc.journal_segments(pcap, conns, backend, broker, receiver)
    reads = multi = 0
    for conn in conns.values():
        segs = segments.get(str(conn.local_port))
        if not segs:
            continue
        counts = [n for n in sj.packets_per_read(conn, segs) if n]
        reads += len(counts)
        multi += sum(1 for n in counts if n > 1)
    return reads, multi


# --- one run -------------------------------------------------------------------------------------

def message_parts(m, timing, broker, card, card_ran=True):
    """One message's derived times, or None where the client side cannot time it: T_c, s_min,
    s_max, F, and, where the broker's capture and the card found it, R, the broker-side range and
    the split's three terms. Where the run took no card timestamps at all (card_ran false), the
    split carries Q as zero, folded into its first term."""
    t_req, before = timing
    if None in (m["Wso"], m["tx_so"], m["rx_so"], m["rx_ack"], t_req, before):
        return None
    t_c = max(0, t_req - before)
    s_min = min(t_c, max(0, t_req - m["rx_ack"])) / 1e3
    s_max = min(t_c, max(0, t_req - m["tx_so"])) / 1e3
    out = {"W": m["Wso"], "D": m["D"], "Tc": t_c / 1e3, "s_min": s_min, "s_max": s_max,
           "F": m["Wso"] - s_min, "F_lo": m["Wso"] - s_max, "flagged": t_req > m["tx_so"],
           "exact": m["rx_ack"] <= before, "R": None, "b_min": None, "b_max": None,
           "Q": None, "net": None, "brk": None, "q_term": None}
    if broker is not None:
        p_in, a_out, f_in, r_out = broker
        out["R"] = _us(r_out, p_in)
        if None not in (p_in, a_out, f_in):
            out["b_min"] = min(t_c, max(0, f_in - a_out)) / 1e3
            out["b_max"] = min(t_c, max(0, f_in - p_in)) / 1e3
    if card is not None:
        out["Q"] = _us(m["rx_so"], card)
    q_term = out["Q"] if card_ran else 0.0
    if out["R"] is not None and q_term is not None:
        out["net"] = out["W"] - out["R"] - q_term
        out["brk"] = out["R"] - s_min
        out["q_term"] = q_term
    return out


def _stats(row, name, values):
    row[name + "_p50"], row[name + "_p99"] = _median(values), _p99(values)


def read_run(run_dir, driver, broker, receiver, warmup_s=WARMUP_S, fold=False):
    """(one run's row, [(F, net, brk, Q, W)] for the messages the split reaches). With `fold`,
    the block took no card timestamps, and the split carries Q as zero."""
    setup, params, msgs = osc.messages(run_dir, warmup_s)
    backend = params.get("backend")
    rate, _, _, _ = setup_parts(setup)
    judged = rw.read_json(os.path.join(run_dir, "integrity.json"))
    conns = sj.load(os.path.join(run_dir, "consumer_journal"))
    per_request, by_id = turnarounds(conns, backend)
    at_broker = broker_times(os.path.join(run_dir, "broker_full.pcap"), osc.PORTS[backend],
                             driver, receiver, backend)
    at_card = ff.card_times(run_dir, broker, receiver)
    timed = []
    for m in msgs:
        got = by_id.get(m["eid"])
        if got is None:
            continue
        parts = message_parts(m, got, at_broker.get(m["eid"]), at_card.get(m["eid"]),
                              not fold)
        if parts is not None:
            timed.append(parts)
    # The turnaround is read over the requests sent while the measured messages were in flight:
    # from the first one's publish to the last one's arrival.
    arrived = [m["rx_so"] for m in msgs if m["rx_so"] is not None]
    lo, hi = (min(m["pub"] for m in msgs), max(arrived)) if arrived else (None, None)
    within = [(t, a, b) for t, a, b in per_request
              if lo is not None and t is not None and lo <= t <= hi]
    turns = [(t - b) / 1e3 for t, _, b in within if b is not None]
    trips = [(a - t) / 1e3 for t, a, _ in within if a is not None]
    reads, multi = reads_drained(run_dir, conns, backend, broker, receiver)
    row = {"run": os.path.basename(run_dir), "setup": setup, "rate": rate, "backend": backend,
           "load_pct": params.get("load_pct"), "priority": bool(params.get("priority")),
           "load_measured": ((judged.get("checks") or {}).get("load") or {}).get("value"),
           "dropped": ff.capture_drops(run_dir), "broker_dropped": broker_drops(run_dir),
           "card_folded": fold,
           "card_window_ns": ff.card_window(os.path.join(run_dir, "phc_offset.csv")),
           "messages": len(msgs), "timed": len(timed), "requests": len(within),
           "overlapped": sum(1 for x in turns if x < 0),
           "flagged": sum(1 for p in timed if p["flagged"]),
           "exact": sum(1 for p in timed if p["flagged"] and p["exact"]),
           "broker_matched": sum(1 for p in timed if p["R"] is not None),
           "card_matched": sum(1 for p in timed if p["Q"] is not None),
           "split": sum(1 for p in timed if p["net"] is not None),
           "reads": reads, "reads_multi": multi}
    _stats(row, "Tc", [max(0.0, x) for x in turns])
    _stats(row, "trip", trips)
    for name in ("W", "F", "F_lo", "D", "R", "Q", "s_min", "s_max", "b_min", "b_max", "net",
                 "brk"):
        _stats(row, name, [p[name] for p in timed if p[name] is not None])
    row["W_mean"] = _mean([p["W"] for p in timed])
    _stats(row, "range", [p["s_max"] - p["s_min"] for p in timed])
    _stats(row, "brange", [p["b_max"] - p["b_min"] for p in timed if p["b_min"] is not None])
    _stats(row, "Dif", capture_agreement(run_dir, msgs, driver, broker, receiver))
    split = [(p["F"], p["net"], p["brk"], p["q_term"], p["W"]) for p in timed
             if p["net"] is not None]
    return row, split


def tail_summary(setup, split, runs_pooled=0):
    """A setup's pooled split: the means of F and of its three terms over all the messages the
    split reaches in its pooled runs (U-f), and over those above their pooled 99th percentile of
    F (U-e)."""
    rate, backend, load, realtime = setup_parts(setup)
    cut = rw.percentile([s[0] for s in split], TAIL_PERCENTILE) if split else None
    tail = [s for s in split if cut is not None and s[0] > cut]
    out = {"setup": setup, "rate": rate, "backend": backend, "load_pct": load,
           "priority": realtime, "runs_pooled": runs_pooled, "split": len(split),
           "tail_cut": cut, "tail_n": len(tail)}
    for prefix, chosen in (("all", split), ("tail", tail)):
        for i, name in enumerate(("F",) + TERMS + ("W",)):
            out["%s_%s" % (prefix, name)] = _mean([s[i] for s in chosen])
    return out


# --- the block -----------------------------------------------------------------------------------

def block_runs(folders, pilot=False):
    """{setup: [run folder]} for the block's passing runs, and [(run, verdict)] for the rest. The
    pilot's runs are read only when asked for, and never judged."""
    wanted = PILOT_ID if pilot else SETUP_ID
    found, skipped = {}, []
    for folder in folders:
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if not name.startswith("law_") or not os.path.isdir(path):
                continue
            setup = osc.setup_of(path)[0]
            if not wanted.match(setup):
                continue
            verdict = rw.read_json(os.path.join(path, "integrity.json")).get("verdict")
            if verdict != rw.PASSING:
                skipped.append((name, verdict or "not judged"))
                continue
            found.setdefault(setup, []).append(path)
    return found, skipped


def _pooled(found, driver, broker, receiver, warmup_s, fold):
    rows, tails = [], []
    for setup in sorted(found):
        pooled, runs_pooled = [], 0
        for path in found[setup]:
            row, split = read_run(path, driver, broker, receiver, warmup_s, fold)
            row["pooled"] = bool(row["timed"]) and row["split"] >= SPLIT_SHARE * row["timed"]
            rows.append(row)
            if row["pooled"]:
                pooled += split
                runs_pooled += 1
        tails.append(tail_summary(setup, pooled, runs_pooled))
    return rows, tails


def read_block(folders, driver, broker, receiver, warmup_s=WARMUP_S, pilot=False):
    """(run rows, setup tails, skipped runs). A setup's runs are read together, so that its
    messages are pooled once and never all held at once with another setup's. A run enters the
    pool only where its split reaches at least SPLIT_SHARE of its timed messages. Where no run of
    the block has card timestamps, the block is read again with Q folded into the first term."""
    found, skipped = block_runs(folders, pilot)
    rows, tails = _pooled(found, driver, broker, receiver, warmup_s, False)
    if rows and not any(r["card_matched"] for r in rows):
        rows, tails = _pooled(found, driver, broker, receiver, warmup_s, True)
    return rows, tails, skipped


# --- the judgments -------------------------------------------------------------------------------

def _value(rows, field, **match):
    """A setup's value: the median over the runs that match, of each run's `field`."""
    picked = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    return _median([float(r[field]) for r in picked if r.get(field) not in (None, "")])


def _verdict(checks):
    """Over the cells a prediction reaches: a cell missing a value it needs is out of reach,
    reported and not judged."""
    reached = [c for c in checks if c["holds"] is not None]
    if not reached:
        return "out of reach"
    return "confirmed" if all(c["holds"] for c in reached) else "not confirmed"


def _judged(checks):
    """A prediction's verdict and its cells. A cell U-c leaves unjudged because U-b did not hold
    there is listed apart from the cells out of reach."""
    return {"verdict": _verdict(checks), "checks": checks,
            "out_of_reach": [(c["rate"], c["backend"]) for c in checks
                             if c["holds"] is None and c.get("after_U_b", True)],
            "not_judged": [(c["rate"], c["backend"]) for c in checks
                           if c["holds"] is None and not c.get("after_U_b", True)]}


def _holds(test, *values):
    """test(*values), or None, out of reach, where any value is missing."""
    return None if any(v is None for v in values) else bool(test(*values))


def loaded_level(rows, rate, backend):
    """The one background load the block ran at a rate on a broker, at either priority; None
    where it ran none. Two would be a block the design does not describe."""
    levels = sorted(set(r["load_pct"] for r in rows if r["rate"] == rate
                        and r["backend"] == backend and r["load_pct"]))
    if len(levels) > 1:
        raise ValueError("block U ran %s at %d a second at loads %s; the design has one"
                         % (backend, rate, levels))
    return levels[0] if levels else None


def three_setups(rows, field, rate, backend):
    """(idle, loaded at normal priority, loaded at real-time priority) values of `field`."""
    load = loaded_level(rows, rate, backend)
    pick = dict(rate=rate, backend=backend)
    return (_value(rows, field, load_pct=0, priority=False, **pick),
            _value(rows, field, load_pct=load, priority=False, **pick),
            _value(rows, field, load_pct=load, priority=True, **pick))


def _cells(rates=UPPER_RATES):
    return [(rate, backend) for rate in rates for backend in ("kafka", "redis")]


def judge_turnaround(rows):
    """U-a: the turnaround's 99th percentile grows under load, and real-time priority holds it."""
    checks = []
    for rate, backend in _cells():
        idle, busy, rt = three_setups(rows, "Tc_p99", rate, backend)
        grew = _holds(lambda i, b: b >= GROWTH * i, idle, busy)
        held = _holds(lambda b, r: r <= HALF * b, busy, rt)
        # A clause that failed fails the cell, whether or not the other could be read.
        holds = False if False in (grew, held) else (None if None in (grew, held) else True)
        checks.append({"rate": rate, "backend": backend, "idle": idle, "load": busy,
                       "realtime": rt, "grew": grew, "held": held, "holds": holds})
    return _judged(checks)


def judge_fix_alone(rows):
    """U-b: W_so's 99th percentile under load is at least GROWTH times idle."""
    checks = []
    for rate, backend in _cells():
        idle, busy, _ = three_setups(rows, "W_p99", rate, backend)
        checks.append({"rate": rate, "backend": backend, "idle": idle, "load": busy,
                       "holds": _holds(lambda i, b: b >= GROWTH * i, idle, busy)})
    out = _judged(checks)
    out["gives_way_at"] = [(c["rate"], c["backend"]) for c in checks if c["holds"]]
    return out


def judge_removal(rows, gave_way):
    """U-c, at each rate and broker where U-b holds (`gave_way`): the share of U-b's rise that
    removing the turnaround takes out, at least one half; and the decision, at 0.9, that the
    turnaround is the only path. Where U-b does not hold there is no rise to take out, and the
    cell is not judged."""
    checks = []
    for rate, backend in _cells():
        w_idle, w_busy, _ = three_setups(rows, "W_p99", rate, backend)
        f_idle, f_busy, _ = three_setups(rows, "F_p99", rate, backend)
        share = None
        if (rate, backend) in gave_way and None not in (f_idle, f_busy):
            share = 1.0 - (f_busy - f_idle) / (w_busy - w_idle)
        checks.append({"rate": rate, "backend": backend, "W_idle": w_idle, "W_load": w_busy,
                       "F_idle": f_idle, "F_load": f_busy, "share": share,
                       "after_U_b": (rate, backend) in gave_way,
                       "holds": None if share is None else share >= HALF,
                       "only_path": share is not None and share >= ONLY_PATH})
    return _judged(checks)


def judge_priority(rows):
    """U-d: under load, W_so's 99th percentile at real-time priority is at most half its value at
    normal priority."""
    checks = []
    for rate, backend in _cells():
        _, busy, rt = three_setups(rows, "W_p99", rate, backend)
        checks.append({"rate": rate, "backend": backend, "load": busy, "realtime": rt,
                       "holds": _holds(lambda b, r: r <= HALF * b, busy, rt)})
    return _judged(checks)


def name_the_term(idle, busy, prefix):
    """The decision U-e and U-f share: the rise of F from `idle` to `busy` (two tail rows), its
    three terms' rises, and the term that holds at least half of it, the largest if two do; None
    where none does or F did not rise."""
    keys = ["%s_%s" % (prefix, n) for n in ("F",) + TERMS]
    if idle is None or busy is None or any(row.get(k) is None for row in (idle, busy)
                                           for k in keys):
        return {"rise": None, "terms": None, "named": None}
    rise = busy[prefix + "_F"] - idle[prefix + "_F"]
    terms = {n: busy["%s_%s" % (prefix, n)] - idle["%s_%s" % (prefix, n)] for n in TERMS}
    holders = [n for n in TERMS if rise > 0 and terms[n] >= NAMES_A_TERM * rise]
    named = max(holders, key=lambda n: terms[n]) if holders else None
    return {"rise": rise, "terms": terms, "named": named}


def _tail(tails, rate, backend, load, realtime=False):
    for t in tails:
        if (t["rate"], t["backend"], t["load_pct"], t["priority"]) == (rate, backend, load,
                                                                         realtime):
            return t
    return None


def judge_split(rows, tails):
    """U-e at 500 and 2,000 a second, over each setup's tail; U-f at 50, over all its messages."""
    out = {}
    for name, rates, prefix in (("U-e", UPPER_RATES, "tail"), ("U-f", (TRACE_RATE,), "all")):
        decisions = []
        for rate, backend in _cells(rates):
            load = loaded_level(rows, rate, backend)
            entry = name_the_term(_tail(tails, rate, backend, 0),
                                  _tail(tails, rate, backend, load), prefix)
            entry.update({"rate": rate, "backend": backend, "load": load})
            decisions.append(entry)
        out[name] = {"decisions": decisions}
    return out


def described(rows):
    """Medians of what the predictions do not judge, setup by setup."""
    out = []
    for setup in sorted(set(r["setup"] for r in rows)):
        runs = [r for r in rows if r["setup"] == setup]
        entry = {"setup": setup}
        for field in DESCRIBED:
            entry[field] = _value(runs, field)
        for part, whole in (("flagged", "timed"), ("exact", "flagged"),
                            ("broker_matched", "timed"), ("card_matched", "timed"),
                            ("split", "timed"), ("reads_multi", "reads")):
            entry[part + "_share"] = _median([int(r[part]) / float(r[whole]) for r in runs
                                              if r.get(whole) not in (None, "")
                                              and int(r[whole])])
        out.append(entry)
    return out


def capture_cost(rows, ladder):
    """What block U's extra instruments (the producer's journal, the card's capture, the broker's
    capture) cost, described: its idle medians of W_so and D at 500 and 2,000 a second less block
    L's (freeze 41's l_runs.csv), the same pair and rates with fewer instruments."""
    out = []
    for rate, backend in _cells():
        pick = dict(rate=rate, backend=backend, load_pct=0)
        entry = {"rate": rate, "backend": backend}
        for mine, theirs, name in (("W_p50", "Wso_median", "W"), ("D_p50", "D_median", "D")):
            u = _value(rows, mine, priority=False, **pick)
            lad = _value(ladder, theirs, **pick)
            entry[name + "_U"], entry[name + "_L"] = u, lad
            entry[name + "_moved"] = None if None in (u, lad) else u - lad
        out.append(entry)
    return out


def judge(rows, tails, ladder=()):
    out = {"U-a": judge_turnaround(rows), "U-b": judge_fix_alone(rows)}
    out["U-c"] = judge_removal(rows, set(map(tuple, out["U-b"]["gives_way_at"])))
    out["U-d"] = judge_priority(rows)
    out.update(judge_split(rows, tails))
    out["described"] = {"setups": described(rows), "capture_cost": capture_cost(rows, ladder)}
    return out


# --- files ---------------------------------------------------------------------------------------

def read_table(path):
    """Rows of a table this program wrote, with its typed columns put back."""
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for key in ("rate", "load_pct"):
            if r.get(key) not in (None, ""):
                r[key] = int(float(r[key]))
        if "priority" in r:
            r["priority"] = {"True": True, "False": False}.get(r["priority"], r["priority"])
        for key, value in list(r.items()):
            if key.startswith(("all_", "tail_")) and value not in (None, ""):
                r[key] = float(value)
            elif key.startswith(("all_", "tail_")):
                r[key] = None
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("read")
    p.add_argument("--runs", action="append", required=True)
    for name in ("--driver", "--broker", "--receiver"):
        p.add_argument(name, required=True)
    p.add_argument("--out-runs", required=True)
    p.add_argument("--out-tails", required=True)
    p.add_argument("--warmup", type=float, default=WARMUP_S)
    p.add_argument("--pilot", action="store_true")
    p = sub.add_parser("judge")
    p.add_argument("--runs-table", required=True)
    p.add_argument("--tails-table", required=True)
    p.add_argument("--ladder-table", default=None)
    p.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "read":
        rows, tails, skipped = read_block(args.runs, args.driver, args.broker, args.receiver,
                                          args.warmup, args.pilot)
        osc.write_csv(args.out_runs, rows)
        osc.write_csv(args.out_tails, tails)
        for run, verdict in skipped:
            print("left out %s: %s" % (run, verdict))
        print("OK %d runs of block U%s -> %s" % (len(rows), "'s pilot" if args.pilot else "",
                                                 args.out_runs))
        return 0
    verdicts = judge(read_table(args.runs_table), read_table(args.tails_table),
                     osc.read_table(args.ladder_table))
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(verdicts, fh, indent=2, sort_keys=True)
        fh.write("\n")
    for name in sorted(k for k in verdicts if k != "described"):
        print("%s: %s" % (name, verdicts[name].get("verdict", "decision recorded")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
