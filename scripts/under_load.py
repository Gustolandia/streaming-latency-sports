#!/usr/bin/env python3
"""
under_load.py -- freeze 42's reader and judge (plan version 45, docs/results/under_load/DESIGN.md),
as plan version 46 amends it before any judged run (docs/results/under_load/DESIGN46.md): the
consumer's turnaround, where load and rate bite together, and where what remains lies.

Per message, on the driver's one clock, as freeze 41 read them (scripts/order_scope.py): t_tx_so and
t_rx_so from the clients' sockets, so W_so = t_rx_so - t_tx_so; t_rx_ack from the producer's
journal; t_req, the transmit timestamp of the request that delivered the message, from the
consumer's journal. Per request for messages k on a consumer connection (Kafka's fetch, Redis's
XREAD or XREADGROUP):

  t_req(k)    the transmit timestamp of the request's last byte
  t_ans(k)    the receive timestamp of the read that delivered its answer's last byte
  t_ask(k)    the receive timestamp of the answer to the request for messages before it
  X(k)        the time within [t_ask(k), t_req(k)] the connection's other requests (Redis's
              acknowledgment batches, a Kafka metadata request) spent waiting on the broker
  T_c(k)    = t_req(k) - t_ask(k) - X(k)   the turnaround: the consumer thread's own time between
                                           two requests for messages, with no broker time and no
                                           network crossing in it; zero where negative

Version 45 timed the turnaround from the answer to whatever request came last, so on Redis the
thread's work before each acknowledgment batch and the batch's own round trip fell outside it;
that turnaround, T_c45 = t_req(k) - t_any(k), is kept beside it. Per message, for the request that
delivered it,

  s_min = min(T_c, max(0, t_req - t_rx_ack))   what the thread surely added (U-c reads this)
  s_max = min(T_c, max(0, t_req - t_tx_so))    the most it can have added
  F     = W_so - s_min                         the thread-free latency (F_lo = W_so - s_max)

From the broker's own capture (broker_full.pcap, the broker's clock, differences only): P_in and
F_in, the arrivals of the last byte of the produce request that carried the message and of the
request that delivered it; A_out, the departure of its acknowledgment's last byte; R_out, the
departure of the byte that ends the message's own id in the answer that delivered it. R = R_out -
P_in is the broker's residence. The message lay stored and unasked-for at least S = max(0, F_in -
A_out), and the broker's own bound on the thread's saving, b_min = min(T_c, S), is never below
s_min, which also takes off the request's and the acknowledgment's network crossings. From the
card's own receive timestamp (freeze 39's instrument), put on the system's clock through samples
of the card's clock, Q = t_rx_so - t_card is the consumer kernel's receive processing and read
drain. Version 46's split, on one identity:

  W_so = floor + excess + hand + b_min + ack + wait + Q

  floor   the fixed delay of the message's two connections, the 1st percentile of W_so - R - Q
          over their messages in the run: each TCP connection on this network keeps its own
  excess  W_so - R - Q above it: the network crossings and the producer's sending path below its
          timestamp, beyond their floor
  hand    R - S: the broker's handling, the produce request's and the answer's
  ack     min(X, S - b_min): what the consumer's other requests kept the message waiting
  wait    S - b_min - ack: the rest of its time stored and unasked-for

so G = W_so - b_min - floor, the latency with neither the thread's surely-added time nor the path's
floor in it, is excess + hand + ack + wait + Q. U-e and U-f split G. Where no run of the block has
card timestamps, Q folds into the path's terms: every run's split carries it as zero, and the rows
say so. Otherwise a run without them, its card capture or its clock samples failed, has no split
and stays out of the pool. Version 45's split, F = (W_so - R - Q) + (R - s_min45) + Q, is still
described run by run.

Every value is in microseconds. A setup's value is the median over its passing runs of each run's
statistic, over the messages the journals time, except U-c's, which is the mean over its runs of
each run's mean over its own top 1% of W_so, so that W_so = F + s_min holds in the setup's values
as in each message. U-e and U-f pool a setup's messages over its runs whose split reaches at least
SPLIT_SHARE of their timed messages, as the design says; U-f compares, within each run at 50 a
second, the messages sent while the load was on with those sent while it was off.

CLI:
    python scripts/under_load.py read --runs FOLDER [--runs ...] --driver IP --broker IP \
        --receiver IP --out-runs CSV --out-tails CSV [--out-attempts CSV] [--warmup S] [--pilot]
    python scripts/under_load.py judge --runs-table CSV --tails-table CSV --out JSON \
        [--ladder-table CSV] [--attempts-table CSV]
"""
import argparse
import bisect
import csv
import json
import os
import random
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import full_fix as ff  # noqa: E402
import order_scope as osc  # noqa: E402
import recv_wait as rw  # noqa: E402
import so_journal as sj  # noqa: E402

#: A judged setup's id: its rate, broker and load, and "-rt" with the consumer at real-time
#: priority, or "-blocks" where the load runs in on/off blocks within the run (version 46, at 50 a
#: second). The pilot's ids start "UP", so they never match it.
SETUP_ID = re.compile(r"^U(\d+)-(kafka|redis)-l(\d+)(-rt|-blocks)?$")
PILOT_ID = re.compile(r"^UP(\d+)-(kafka|redis)-l(\d+)(-rt|-blocks)?$")

#: Block U runs 70 s with a 20 s warm-up at every rate, as block L did.
WARMUP_S = 20.0

#: The rates U-a to U-e judge, and the rate U-f traces.
UPPER_RATES = (500, 2000)
TRACE_RATE = 50

#: U-a and U-b: how much larger a 99th percentile must be under load than idle. U-a and U-d: the
#: most of it real-time priority may leave. U-c: the least share of U-b's rise the turnaround must
#: remove, and the share the lower end of its interval must reach for the paper to call it the
#: only path. U-e and U-f: the least share of a rise that names its term.
GROWTH = 1.5
HALF = 0.5
ONLY_PATH = 0.9
NAMES_A_TERM = 0.5

#: The percentile above which U-c reads a run's tail, and U-e a setup's pooled messages as its.
TAIL_PERCENTILE = 99

#: The share of a run's timed messages its split must reach for the run to enter U-e's and U-f's
#: pool: a packet dropped from a capture leaves every later byte of its stream unread, so a run
#: whose split falls short would pool only the messages before the hole. It is F-c's 0.5%.
SPLIT_SHARE = 0.995

#: Version 46's five terms of G, in the order the design lists them, and the fields pooled per
#: message: G, its terms, the path's floor, W_so, and the load's block when the message was sent.
TERMS = ("excess", "hand", "ack", "wait", "Q")
SPLIT_FIELDS = ("G",) + TERMS + ("floor", "W")

#: A connection pair's floor is the 1st percentile of its messages' path term, or the least of
#: them where the pair carried fewer than FLOOR_MIN: in block U's pilot each connection's path sat
#: at its own level, 330, 500, 590 or 655 us, each only 10-20 us wide.
FLOOR_PERCENTILE = 1
FLOOR_MIN = 100

#: U-f's blocks: a message sent within this long after the load was switched is left out, while
#: the processors settle into the new state.
BLOCK_GUARD_S = 1.0

#: U-c's interval: each setup's runs resampled with replacement this many times, from this seed,
#: and the central share of the resampled shares.
BOOTSTRAP = 2000
BOOTSTRAP_SEED = 20261022
INTERVAL = 0.95

#: Described: a message sent more than LATE_MS after the run's least lateness; a produce request
#: the broker held more than STALL_US before acknowledging it.
LATE_MS = 1.0
STALL_US = 1000.0

#: The Redis commands that ask for messages. The consumer's connection also carries its
#: acknowledgments (XACK), which ask for none.
ASKS = (b"XREAD", b"XREADGROUP")

#: The broker capture's own log, where tcpdump says how many packets the kernel dropped.
BROKER_LOG = "broker_full.err"

#: The fields described setup by setup, beside the predictions.
DESCRIBED = ("Tc_p50", "Tc45_p50", "Tc45_p99", "trip_p50", "W_p50", "F_p50", "F_lo_p50",
             "F_lo_p99", "D_p50", "D_p99", "R_p50", "R_p99", "Q_p50", "Q_p99", "s_min_p50",
             "s_min_p99", "s_max_p50", "s_max_p99", "b_min_p50", "b_min_p99", "b_max_p50",
             "b_max_p99", "range_p50", "range_p99", "brange_p50", "brange_p99", "net_p50",
             "net_p99", "brk_p50", "brk_p99", "excess_p50", "excess_p99", "hand_p50", "hand_p99",
             "ack_p50", "ack_p99", "wait_p50", "wait_p99", "G_p50", "G_p99", "Fb_p50", "Fb_p99",
             "W_tail", "F_tail", "F45_tail", "Fb_tail", "floor_pairs", "floor_lo", "floor_hi",
             "Dif_p50", "Dif_p99", "card_window_ns", "load_measured", "duty_pct",
             "late_p50_ms", "late_spread_ms", "late_share", "stall_share", "gc_producer",
             "gc_consumer", "Tc_wait_share", "Tc_cpu_share", "Tc_tail_mean", "Tc_tail_wait",
             "Tc_tail_cpu")


def _us(a, b):
    """(a - b) in microseconds, or None if either is missing."""
    return None if a is None or b is None else (a - b) / 1e3


def _median(values):
    return statistics.median(values) if values else None


def _p99(values):
    return rw.percentile(values, 99) if values else None


def _mean(values):
    return statistics.fmean(values) if values else None


def _float(value):
    """A table's value as a number, or None where it is empty."""
    return None if value in (None, "", "None") else float(value)


def setup_parts(setup):
    """(rate, backend, load, real-time) from a judged or a pilot setup id; None for any other."""
    m = SETUP_ID.match(setup) or PILOT_ID.match(setup)
    if not m:
        return None
    return int(m.group(1)), m.group(2), int(m.group(3)), m.group(4) == "-rt"


def in_blocks(setup):
    """Whether a judged or a pilot setup runs its load in on/off blocks."""
    m = SETUP_ID.match(setup) or PILOT_ID.match(setup)
    return bool(m) and m.group(4) == "-blocks"


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


def covered(spans, lo, hi):
    """How much of [lo, hi] the union of the (start, end) spans covers."""
    total, reach = 0, lo
    for a, b in sorted(spans):
        a, b = max(a, reach), min(b, hi)
        if b > a:
            total += b - a
            reach = b
    return total


def turnarounds(conns, backend):
    """Per request for messages on each consumer connection, in order, (t_req, t_ans, t_ask, X,
    t_any): t_ask the answer to the request for messages before it, X the time within that gap the
    connection's other requests waited on the broker, t_any the answer to whatever request came
    last, as version 45 timed the turnaround from. And {event id: (t_req, t_ask, X, t_any, the
    connection's local port)} for the request that delivered each message, its first delivery
    kept, as the journal's own reader keeps it."""
    per_request, by_id = [], {}
    for conn in conns.values():
        ask = last = None
        others = []
        for request_end, answer_start, answer_end, asks in requests_on(conn, backend):
            t_req = sj.tx_at(conn, request_end - 1)
            t_ans = sj.rx_at(conn, answer_end - 1)
            if asks:
                other = None
                if ask is not None and t_req is not None:
                    other = covered([s for s in others if None not in s], ask, t_req)
                per_request.append((t_req, t_ans, ask, other, last))
                for eid in sj.ids_in(conn.inb, answer_start, answer_end):
                    by_id.setdefault(eid, (t_req, ask, other, last, conn.local_port))
                ask, others = t_ans, []
            else:
                others.append((t_req, t_ans))
            last = t_ans
    return per_request, by_id


def producer_ports(stem):
    """{event id: the local port of the producer's connection that carried it}, from its journal;
    {} where the run wrote none."""
    ports = {}
    for conn in sj.load(stem).values():
        for eid in sj.ids_in(conn.out, 0, len(conn.out)):
            ports.setdefault(eid, conn.local_port)
    return ports


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


# --- what else the run wrote, version 46 ---------------------------------------------------------

def _rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def lateness(run_dir, warmup_s=WARMUP_S):
    """The producer's lateness after the warm-up, its send time less its planned time, in ms: the
    1st, 50th and 99th percentiles, the spread between the 1st and the 99th, and the share of
    messages more than LATE_MS past the 1st. All None where producer.csv plans nothing."""
    pairs = []
    for row in _rows(os.path.join(run_dir, "producer.csv")):
        sent, planned = row.get("t_prod_send_ns"), row.get("t_prod_sched_ns")
        if sent not in (None, "") and planned not in (None, ""):
            pairs.append((int(sent), int(planned)))
    out = dict.fromkeys(("late_p1_ms", "late_p50_ms", "late_p99_ms", "late_spread_ms",
                         "late_share"))
    if not pairs:
        return out
    # Whole nanoseconds: a time since 1970 in nanoseconds is past what a float holds exactly,
    # and a cut made in floats moved past the first message sent.
    cut = min(s for s, _ in pairs) + int(warmup_s * 1e9)
    late = [(s - p) / 1e6 for s, p in pairs if s >= cut]
    if not late:
        return out
    p1, p50, p99 = (rw.percentile(late, q) for q in (1, 50, 99))
    out.update(late_p1_ms=p1, late_p50_ms=p50, late_p99_ms=p99, late_spread_ms=p99 - p1,
               late_share=sum(1 for x in late if x - p1 > LATE_MS) / len(late))
    return out


def load_switches(run_dir):
    """([switch times], [states]) of the load's blocks, from load_blocks.csv; ([], []) where the
    run ran its load whole."""
    rows = sorted((int(r["t_ns"]), r["state"]) for r in
                  _rows(os.path.join(run_dir, "load_blocks.csv")))
    return [t for t, _ in rows], [s for _, s in rows]


def block_state(switches, t_ns):
    """"on" or "off" for a message sent at t_ns, by the block it was sent in; None where the run
    has no blocks, before the first switch, or within BLOCK_GUARD_S after one."""
    times, states = switches
    if not times or t_ns is None:
        return None
    i = bisect.bisect_right(times, t_ns) - 1
    if i < 0 or t_ns - times[i] < BLOCK_GUARD_S * 1e9:
        return None
    return states[i]


def schedstat(run_dir):
    """([t], [on-CPU ns], [run-queue ns]) from the consumer's samples of its own thread, taken just
    before each request; None where the run took none."""
    rows = sorted((int(r["t_ns"]), int(r["exec_ns"]), int(r["delay_ns"])) for r in
                  _rows(os.path.join(run_dir, "consumer_schedstat.csv")))
    if not rows:
        return None
    return [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]


def turnaround_parts(samples, requests):
    """[(T_c, waited for a core, ran on one)] in us for each request for messages that has a
    turnaround: the consumer thread's counters from its last sample at or before the previous
    answer to its last sample at or before the request, the samples being taken just before each
    request was made."""
    times, execs, delays = samples
    out = []
    for t_req, _, ask, other, _ in requests:
        if t_req is None or ask is None or other is None:
            continue
        i = bisect.bisect_right(times, ask) - 1
        j = bisect.bisect_right(times, t_req) - 1
        if i < 0:
            continue
        # A request sent before the previous answer came in has no turnaround, and no sample
        # falls between the two.
        j = max(i, j)
        out.append((max(0, t_req - ask - other) / 1e3, (delays[j] - delays[i]) / 1e3,
                    (execs[j] - execs[i]) / 1e3))
    return out


def gc_collections(path):
    """How many collections a client's collector made, by its own log; None without one."""
    if not os.path.exists(path):
        return None
    return len(rw.read_json(path).get("collections") or [])


def duty_in_effect(run_dir):
    """The duty stress-ng ran at: the second correction's, a frozen duty, or the first
    correction's; None for an idle run."""
    for name, key in (("load_recorrection.json", "duty_used_pct"),
                      ("load_correction.json", "duty_frozen_pct"),
                      ("load_correction.json", "duty_used_pct")):
        path = os.path.join(run_dir, name)
        if os.path.exists(path) and rw.read_json(path).get(key) is not None:
            return rw.read_json(path)[key]
    return None


#: The run's facts (scripts/run_facts.py) the reader carries into its row, described: each as
#: written, and the same for every run of a block unless something moved.
FACTS = ("stress_ng_version", "irqbalance", "net_irq_cpus", "preempt", "rt_runtime_us",
         "client_libraries", "client_policies")


def run_facts_summary(run_dir):
    """The run's facts in a few words, from run_facts.json and run_facts_clients.json: stress-ng's
    version, irqbalance's state, the processors the network's interrupts ran on, the kernel's
    preemption, the real-time throttle, the clients' libraries, and each client's and the load's
    scheduling policies, script by script. None where the run wrote no facts."""
    host = rw.read_json(os.path.join(run_dir, "run_facts.json"))
    clients = rw.read_json(os.path.join(run_dir, "run_facts_clients.json"))
    cpus = sorted(set(str(i.get("effective_affinity_list")) for i in host.get("network_irqs")
                      or []))
    preempt = [line for line in host.get("kernel_config") or []
               if line.startswith("CONFIG_PREEMPT") and line.endswith("=y")]
    policies = {}
    for process in clients.get("processes") or []:
        for thread in process.get("threads") or []:
            policies.setdefault(str(process.get("names")), set()).add(
                str(thread.get("policy_name")))
    return {"stress_ng_version": host.get("stress_ng_version"),
            "irqbalance": host.get("irqbalance"),
            "net_irq_cpus": ";".join(cpus) or None,
            "preempt": ";".join(preempt) or None,
            "rt_runtime_us": (host.get("sched") or {}).get("sched_rt_runtime_us"),
            "client_libraries": host.get("client_libraries"),
            "client_policies": ";".join("%s=%s" % (name, "/".join(sorted(found)))
                                        for name, found in sorted(policies.items())) or None}


def path_floors(parts):
    """{connection pair: its floor}, the 1st percentile of the path term over the pair's
    messages, or the least of them where it carried fewer than FLOOR_MIN."""
    nets = {}
    for p in parts:
        if p["net"] is not None:
            nets.setdefault(p["pair"], []).append(p["net"])
    return {pair: (rw.percentile(v, FLOOR_PERCENTILE) if len(v) >= FLOOR_MIN else min(v))
            for pair, v in nets.items()}


# --- one run -------------------------------------------------------------------------------------

def message_parts(m, timing, broker, card, card_ran=True):
    """One message's derived times, or None where the client side cannot time it: T_c, the
    saving's bounds and F, version 45's turnaround and F beside them, and, where the broker's
    capture and the card found it, R, the broker's bounds and the terms of both splits but the
    floor, which needs the run's other messages. Where the run took no card timestamps at all
    (card_ran false), the split carries Q as zero, folded into the path's terms."""
    t_req, ask, other, last, _ = timing
    if None in (m["Wso"], m["tx_so"], m["rx_so"], m["rx_ack"], t_req, ask, other):
        return None
    w = m["Wso"]
    t_c = max(0, t_req - ask - other)
    s_min = min(t_c, max(0, t_req - m["rx_ack"])) / 1e3
    s_max = min(t_c, max(0, t_req - m["tx_so"])) / 1e3
    out = {"W": w, "D": m["D"], "Tc": t_c / 1e3, "other": other / 1e3, "s_min": s_min,
           "s_max": s_max, "F": w - s_min, "F_lo": w - s_max, "Tc45": None, "s_min45": None,
           "F45": None, "flagged": t_req > m["tx_so"], "exact": m["rx_ack"] <= ask, "R": None,
           "b_min": None, "b_max": None, "stored": None, "stall": None, "Fb": None, "Q": None,
           "net": None, "brk": None, "q_term": None, "hand": None, "ack": None, "wait": None}
    if last is not None:
        t_c45 = max(0, t_req - last)
        out["Tc45"] = t_c45 / 1e3
        out["s_min45"] = min(t_c45, max(0, t_req - m["rx_ack"])) / 1e3
        out["F45"] = w - out["s_min45"]
    if broker is not None:
        p_in, a_out, f_in, r_out = broker
        out["R"] = _us(r_out, p_in)
        if None not in (p_in, a_out, f_in):
            stored = max(0, f_in - a_out)
            out["stored"] = stored / 1e3
            out["b_min"] = min(t_c, stored) / 1e3
            out["b_max"] = min(t_c, max(0, f_in - p_in)) / 1e3
            out["stall"] = (a_out - p_in) / 1e3
            out["Fb"] = w - out["b_min"]
    if card is not None:
        out["Q"] = _us(m["rx_so"], card)
    q_term = out["Q"] if card_ran else 0.0
    if out["R"] is not None and q_term is not None:
        out["net"] = w - out["R"] - q_term
        out["q_term"] = q_term
        if out["s_min45"] is not None:
            out["brk"] = out["R"] - out["s_min45"]
        if out["stored"] is not None:
            out["hand"] = out["R"] - out["stored"]
            out["ack"] = min(out["other"], out["stored"] - out["b_min"])
            out["wait"] = out["stored"] - out["b_min"] - out["ack"]
    return out


def _stats(row, name, values):
    row[name + "_p50"], row[name + "_p99"] = _median(values), _p99(values)


def _tail_means(row, timed):
    """U-c's per-run values: the means over the run's own top 1% of W_so of W_so, F, version 45's
    F and the broker-bound F."""
    cut = _p99([p["W"] for p in timed])
    top = [p for p in timed if cut is not None and p["W"] > cut]
    for name, field in (("W_tail", "W"), ("F_tail", "F"), ("F45_tail", "F45"),
                        ("Fb_tail", "Fb")):
        row[name] = _mean([p[field] for p in top if p[field] is not None])
    row["tail_n"] = len(top)


def _schedstat_row(row, run_dir, within):
    """The run's turnaround split between waiting for a core, running and the rest, from the
    consumer's samples of its own thread; all None where it took none."""
    for name in ("Tc_wait_share", "Tc_cpu_share", "Tc_tail_mean", "Tc_tail_wait", "Tc_tail_cpu"):
        row[name] = None
    samples = schedstat(run_dir)
    parts = turnaround_parts(samples, within) if samples else []
    spent = sum(t for t, _, _ in parts)
    if not spent:
        return
    row["Tc_wait_share"] = sum(w for _, w, _ in parts) / spent
    row["Tc_cpu_share"] = sum(c for _, _, c in parts) / spent
    cut = _p99([t for t, _, _ in parts])
    top = [p for p in parts if p[0] > cut]
    row["Tc_tail_mean"] = _mean([t for t, _, _ in top])
    row["Tc_tail_wait"] = _mean([w for _, w, _ in top])
    row["Tc_tail_cpu"] = _mean([c for _, _, c in top])


def read_run(run_dir, driver, broker, receiver, warmup_s=WARMUP_S, fold=False):
    """(one run's row, [split per message]) for the messages the split reaches, each in
    SPLIT_FIELDS' order with the load's block last. With `fold`, the block took no card
    timestamps, and the split carries Q as zero."""
    setup, params, msgs = osc.messages(run_dir, warmup_s)
    backend = params.get("backend")
    rate, _, _, _ = setup_parts(setup)
    judged = rw.read_json(os.path.join(run_dir, "integrity.json"))
    conns = sj.load(os.path.join(run_dir, "consumer_journal"))
    per_request, by_id = turnarounds(conns, backend)
    sent_on = producer_ports(os.path.join(run_dir, "producer_journal"))
    at_broker = broker_times(os.path.join(run_dir, "broker_full.pcap"), osc.PORTS[backend],
                             driver, receiver, backend)
    at_card = ff.card_times(run_dir, broker, receiver)
    switches = load_switches(run_dir)
    timed = []
    for m in msgs:
        got = by_id.get(m["eid"])
        if got is None:
            continue
        parts = message_parts(m, got, at_broker.get(m["eid"]), at_card.get(m["eid"]),
                              not fold)
        if parts is not None:
            parts["pair"] = (sent_on.get(m["eid"]), got[4])
            parts["state"] = block_state(switches, m["tx_so"])
            timed.append(parts)
    floors = path_floors(timed)
    for p in timed:
        p["floor"] = floors.get(p["pair"]) if p["net"] is not None else None
        p["excess"] = None if p["floor"] is None else p["net"] - p["floor"]
        p["G"] = None if p["hand"] is None else p["Fb"] - p["floor"]
    # The turnaround is read over the requests sent while the measured messages were in flight:
    # from the first one's publish to the last one's arrival.
    arrived = [m["rx_so"] for m in msgs if m["rx_so"] is not None]
    lo, hi = (min(m["pub"] for m in msgs), max(arrived)) if arrived else (None, None)
    within = [q for q in per_request if lo is not None and q[0] is not None and lo <= q[0] <= hi]
    turns = [(t - k - o) / 1e3 for t, _, k, o, _ in within if o is not None]
    turns45 = [(t - y) / 1e3 for t, _, _, _, y in within if y is not None]
    trips = [(a - t) / 1e3 for t, a, _, _, _ in within if a is not None]
    reads, multi = reads_drained(run_dir, conns, backend, broker, receiver)
    stalls = [p["stall"] for p in timed if p["stall"] is not None]
    row = {"run": os.path.basename(run_dir), "setup": setup, "rate": rate, "backend": backend,
           "load_pct": params.get("load_pct"), "priority": bool(params.get("priority")),
           "blocks": in_blocks(setup),
           "load_measured": ((judged.get("checks") or {}).get("load") or {}).get("value"),
           "duty_pct": duty_in_effect(run_dir),
           "dropped": ff.capture_drops(run_dir), "broker_dropped": broker_drops(run_dir),
           "card_folded": fold,
           "card_window_ns": ff.card_window(os.path.join(run_dir, "phc_offset.csv")),
           "messages": len(msgs), "timed": len(timed), "requests": len(within),
           "overlapped": sum(1 for x in turns if x < 0),
           "flagged": sum(1 for p in timed if p["flagged"]),
           "exact": sum(1 for p in timed if p["flagged"] and p["exact"]),
           "broker_matched": sum(1 for p in timed if p["R"] is not None),
           "card_matched": sum(1 for p in timed if p["Q"] is not None),
           "split": sum(1 for p in timed if p["G"] is not None),
           "on_n": sum(1 for p in timed if p["G"] is not None and p["state"] == "on"),
           "off_n": sum(1 for p in timed if p["G"] is not None and p["state"] == "off"),
           "floor_pairs": len(floors),
           "floor_lo": min(floors.values()) if floors else None,
           "floor_hi": max(floors.values()) if floors else None,
           "stall_share": (sum(1 for s in stalls if s > STALL_US) / len(stalls)) if stalls
           else None,
           "gc_producer": gc_collections(os.path.join(run_dir, "producer_gc.json")),
           "gc_consumer": gc_collections(os.path.join(run_dir, "consumer_gc.json")),
           "reads": reads, "reads_multi": multi}
    row.update(lateness(run_dir, warmup_s))
    row.update(run_facts_summary(run_dir))
    _stats(row, "Tc", [max(0.0, x) for x in turns])
    _stats(row, "Tc45", [max(0.0, x) for x in turns45])
    _stats(row, "trip", trips)
    for name in ("W", "F", "F_lo", "D", "R", "Q", "s_min", "s_max", "b_min", "b_max", "net",
                 "brk", "excess", "hand", "ack", "wait", "G", "Fb"):
        _stats(row, name, [p[name] for p in timed if p[name] is not None])
    row["W_mean"] = _mean([p["W"] for p in timed])
    _stats(row, "range", [p["s_max"] - p["s_min"] for p in timed])
    _stats(row, "brange", [p["b_max"] - p["b_min"] for p in timed if p["b_min"] is not None])
    _stats(row, "Dif", capture_agreement(run_dir, msgs, driver, broker, receiver))
    _tail_means(row, timed)
    _schedstat_row(row, run_dir, within)
    split = [tuple(p["q_term"] if name == "Q" else p[name] for name in SPLIT_FIELDS)
             + (p["state"],) for p in timed if p["G"] is not None]
    return row, split


def tail_summary(setup, split, runs_pooled=0):
    """A setup's pooled split: the means of G, its five terms, the floor and W_so over all the
    messages the split reaches in its pooled runs, over those above their pooled 99th percentile
    of G (U-e), and, where the setup runs its load in blocks, over those sent while it was on and
    while it was off (U-f)."""
    rate, backend, load, realtime = setup_parts(setup)
    cut = rw.percentile([s[0] for s in split], TAIL_PERCENTILE) if split else None
    tail = [s for s in split if cut is not None and s[0] > cut]
    out = {"setup": setup, "rate": rate, "backend": backend, "load_pct": load,
           "priority": realtime, "blocks": in_blocks(setup), "runs_pooled": runs_pooled,
           "split": len(split), "tail_cut": cut, "tail_n": len(tail)}
    for prefix, chosen in (("all", split), ("tail", tail),
                           ("on", [s for s in split if s[-1] == "on"]),
                           ("off", [s for s in split if s[-1] == "off"])):
        out[prefix + "_n"] = len(chosen)
        for i, name in enumerate(SPLIT_FIELDS):
            out["%s_%s" % (prefix, name)] = _mean([s[i] for s in chosen])
    return out


# --- the block -----------------------------------------------------------------------------------

def block_runs(folders, pilot=False):
    """({setup: [run folder]} for the block's passing runs, [(run, verdict)] for the rest, and
    {setup: [run folder]} for those). The pilot's runs are read only when asked for, and never
    judged."""
    wanted = PILOT_ID if pilot else SETUP_ID
    found, skipped, failed = {}, [], {}
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
                failed.setdefault(setup, []).append(path)
                continue
            found.setdefault(setup, []).append(path)
    return found, skipped, failed


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


def read_attempts(failed, driver, broker, receiver, warmup_s=WARMUP_S, fold=False):
    """A row for every attempt that did not pass, read as a passing run is where its files allow,
    so that each setup can be described with its failed attempts too; a run whose files cannot be
    read gives its id, its verdict and why."""
    rows = []
    for setup in sorted(failed):
        for path in failed[setup]:
            verdict = rw.read_json(os.path.join(path, "integrity.json"))
            base = {"run": os.path.basename(path), "setup": setup,
                    "verdict": verdict.get("verdict") or "not judged",
                    "reasons": "; ".join(verdict.get("reasons") or [])}
            try:
                row, _ = read_run(path, driver, broker, receiver, warmup_s, fold)
            except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                base["unreadable"] = "%s: %s" % (type(exc).__name__, exc)
                rows.append(base)
                continue
            row.update(base)
            rows.append(row)
    return rows


def read_block(folders, driver, broker, receiver, warmup_s=WARMUP_S, pilot=False):
    """(run rows, setup tails, skipped runs, failed attempts' rows). A setup's runs are read
    together, so that its messages are pooled once and never all held at once with another
    setup's. A run enters the pool only where its split reaches at least SPLIT_SHARE of its timed
    messages. Where no run of the block has card timestamps, the block is read again with Q folded
    into the path's terms."""
    found, skipped, failed = block_runs(folders, pilot)
    fold = False
    rows, tails = _pooled(found, driver, broker, receiver, warmup_s, fold)
    if rows and not any(r["card_matched"] for r in rows):
        fold = True
        rows, tails = _pooled(found, driver, broker, receiver, warmup_s, fold)
    return rows, tails, skipped, read_attempts(failed, driver, broker, receiver, warmup_s, fold)


# --- the judgments -------------------------------------------------------------------------------

def _picked(rows, **match):
    return [r for r in rows if all(r.get(k) == v for k, v in match.items())]


def _value(rows, field, **match):
    """A setup's value: the median over the runs that match, of each run's `field`."""
    return _median([_float(r[field]) for r in _picked(rows, **match)
                    if _float(r.get(field)) is not None])


def _verdict(checks):
    """Over the cells a prediction reaches: a cell missing a value it needs is out of reach,
    reported and not judged."""
    reached = [c for c in checks if c["holds"] is not None]
    if not reached:
        return "out of reach"
    return "confirmed" if all(c["holds"] for c in reached) else "not confirmed"


def _judged(checks):
    """A prediction's verdict and its cells. A cell U-c leaves unjudged because U-b did not hold
    there is listed apart from the cells out of reach, and a prediction left unjudged in every
    cell that way is "not judged", not out of reach."""
    out = {"verdict": _verdict(checks), "checks": checks,
           "out_of_reach": [(c["rate"], c["backend"]) for c in checks
                            if c["holds"] is None and c.get("after_U_b", True)],
           "not_judged": [(c["rate"], c["backend"]) for c in checks
                          if c["holds"] is None and not c.get("after_U_b", True)]}
    if out["verdict"] == "out of reach" and out["not_judged"] and not out["out_of_reach"]:
        out["verdict"] = "not judged"
    return out


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


def _three_picks(rows, rate, backend):
    load = loaded_level(rows, rate, backend)
    pick = dict(rate=rate, backend=backend)
    return (dict(load_pct=0, priority=False, **pick), dict(load_pct=load, priority=False, **pick),
            dict(load_pct=load, priority=True, **pick))


def three_setups(rows, field, rate, backend):
    """(idle, loaded at normal priority, loaded at real-time priority) values of `field`."""
    return tuple(_value(rows, field, **p) for p in _three_picks(rows, rate, backend))


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


def removal_share(idle, busy, f_field="F_tail"):
    """U-c's share from two setups' runs: 1 - (F_load - F_idle) / (W_load - W_idle), each the
    mean over the setup's runs of the run's mean over its own top 1% of W_so; None where a value
    is missing or W_so's tail did not rise."""
    means = []
    for runs, field in ((idle, "W_tail"), (busy, "W_tail"), (idle, f_field), (busy, f_field)):
        values = [_float(r.get(field)) for r in runs]
        means.append(None if not values or None in values else statistics.fmean(values))
    w_idle, w_busy, f_idle, f_busy = means
    if None in means or w_busy <= w_idle:
        return None
    return 1.0 - (f_busy - f_idle) / (w_busy - w_idle)


def removal_interval(idle, busy, f_field="F_tail", draws=BOOTSTRAP, seed=BOOTSTRAP_SEED):
    """(low, high, draws without a share): U-c's share with each setup's runs resampled with
    replacement, the central INTERVAL of the shares that came out; None, None where none did."""
    rng = random.Random(seed)
    shares = []
    for _ in range(draws):
        share = removal_share([rng.choice(idle) for _ in idle], [rng.choice(busy) for _ in busy],
                              f_field)
        if share is not None:
            shares.append(share)
    if not shares:
        return None, None, draws
    return (rw.percentile(shares, 100 * (1 - INTERVAL) / 2),
            rw.percentile(shares, 100 * (1 + INTERVAL) / 2), draws - len(shares))


def judge_removal(rows, gave_way, draws=BOOTSTRAP):
    """U-c, at each rate and broker where U-b holds (`gave_way`): the share of the rise of W_so's
    tail that removing the turnaround takes out, at least one half; and the decision that the
    turnaround is the only path, where the lower end of the share's interval is at least 0.9.
    Where U-b does not hold there is no rise to take out, and the cell is not judged. Beside it,
    the share with version 45's turnaround and with the broker's tighter bound, described."""
    checks = []
    for rate, backend in _cells():
        idle_pick, busy_pick, _ = _three_picks(rows, rate, backend)
        idle, busy = _picked(rows, **idle_pick), _picked(rows, **busy_pick)
        share = low = high = None
        undefined = 0
        judged = (rate, backend) in gave_way
        if judged and idle and busy:
            share = removal_share(idle, busy)
            low, high, undefined = removal_interval(idle, busy, draws=draws)
        checks.append({"rate": rate, "backend": backend, "share": share, "low": low,
                       "high": high, "undefined_draws": undefined,
                       "share_45": removal_share(idle, busy, "F45_tail") if judged else None,
                       "share_broker_bound": removal_share(idle, busy, "Fb_tail") if judged
                       else None,
                       "after_U_b": judged,
                       "holds": None if share is None else share >= HALF,
                       "only_path": low is not None and low >= ONLY_PATH})
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


def name_the_term(idle, busy, prefix, busy_prefix=None):
    """The decision U-e and U-f share: the rise of G from `idle` to `busy` (two tail rows, read
    under `prefix` and `busy_prefix`), its five terms' signed rises, the floor's, and the term
    that holds at least half of the rise, the largest if two do; None where none does or G did
    not rise."""
    busy_prefix = busy_prefix or prefix
    names = ("G",) + TERMS
    if idle is None or busy is None or any(
            idle.get("%s_%s" % (prefix, n)) is None or busy.get("%s_%s" % (busy_prefix, n)) is None
            for n in names):
        return {"rise": None, "terms": None, "floor": None, "named": None}
    moved = {n: busy["%s_%s" % (busy_prefix, n)] - idle["%s_%s" % (prefix, n)] for n in names}
    rise = moved.pop("G")
    holders = [n for n in TERMS if rise > 0 and moved[n] >= NAMES_A_TERM * rise]
    floors = (idle.get(prefix + "_floor"), busy.get(busy_prefix + "_floor"))
    return {"rise": rise, "terms": moved,
            "floor": None if None in floors else floors[1] - floors[0],
            "named": max(holders, key=lambda n: moved[n]) if holders else None}


def _tail(tails, rate, backend, load, realtime=False, blocks=False):
    for t in tails:
        if (t["rate"], t["backend"], t["load_pct"], t["priority"],
                bool(t.get("blocks"))) == (rate, backend, load, realtime, blocks):
            return t
    return None


def judge_split(rows, tails):
    """U-e at 500 and 2,000 a second, over each setup's tail; U-f at 50, within the runs that ran
    their load in blocks, the messages sent while it was on against those sent while it was off,
    with the comparison of those runs' on-blocks with the idle runs beside it, described."""
    decisions = []
    for rate, backend in _cells(UPPER_RATES):
        load = loaded_level(rows, rate, backend)
        entry = name_the_term(_tail(tails, rate, backend, 0), _tail(tails, rate, backend, load),
                              "tail")
        entry.update({"rate": rate, "backend": backend, "load": load})
        decisions.append(entry)
    traced = []
    for rate, backend in _cells((TRACE_RATE,)):
        load = loaded_level(rows, rate, backend)
        blocks = _tail(tails, rate, backend, load, blocks=True)
        entry = name_the_term(blocks, blocks, "off", "on")
        entry.update({"rate": rate, "backend": backend, "load": load,
                      "between_runs": name_the_term(_tail(tails, rate, backend, 0), blocks,
                                                    "all", "on")})
        traced.append(entry)
    return {"U-e": {"decisions": decisions}, "U-f": {"decisions": traced}}


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
        # The facts are words, not numbers: each one's distinct values over the setup's runs.
        for field in FACTS:
            entry[field] = sorted(set(str(r[field]) for r in runs
                                      if r.get(field) not in (None, "")))
        out.append(entry)
    return out


def wait_and_interference(rows):
    """Described: what of the turnaround's rise under load real-time priority takes away, the wait
    for a core (normal less real-time), and what it leaves, the work slowed by its neighbours
    (real-time less idle), at the median and at the 99th percentile."""
    out = []
    for rate, backend in _cells():
        entry = {"rate": rate, "backend": backend}
        for q in ("p50", "p99"):
            idle, busy, rt = three_setups(rows, "Tc_" + q, rate, backend)
            entry["wait_" + q] = None if None in (busy, rt) else busy - rt
            entry["interference_" + q] = None if None in (rt, idle) else rt - idle
        out.append(entry)
    return out


def with_failed(rows, attempts):
    """Described: each setup's attempts, how many failed, and the medians of W_so's and the
    turnaround's 99th percentiles over every attempt that could be read, failed ones too."""
    out = []
    for setup in sorted(set(r["setup"] for r in list(rows) + list(attempts))):
        mine = [r for r in rows if r["setup"] == setup]
        lost = [r for r in attempts if r["setup"] == setup]
        both = mine + [r for r in lost if not r.get("unreadable")]
        out.append({"setup": setup, "attempts": len(mine) + len(lost), "failed": len(lost),
                    "W_p99": _value(both, "W_p99"), "Tc_p99": _value(both, "Tc_p99")})
    return out


def capture_cost(rows, ladder):
    """What block U's extra instruments (the producer's journal, the card's capture, the broker's
    capture) cost, described: its idle medians of W_so and D at 500 and 2,000 a second less block
    L's (freeze 41's l_runs.csv), the same pair and rates with fewer instruments. Each connection
    keeps its own path delay and each run draws its connections afresh, so a difference here of
    a few hundred microseconds can be the paths alone."""
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


def judge(rows, tails, ladder=(), attempts=(), draws=BOOTSTRAP):
    out = {"U-a": judge_turnaround(rows), "U-b": judge_fix_alone(rows)}
    out["U-c"] = judge_removal(rows, set(map(tuple, out["U-b"]["gives_way_at"])), draws)
    out["U-d"] = judge_priority(rows)
    out.update(judge_split(rows, tails))
    out["described"] = {"setups": described(rows), "capture_cost": capture_cost(rows, ladder),
                        "wait_and_interference": wait_and_interference(rows),
                        "with_failed": with_failed(rows, attempts)}
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
        for key in ("priority", "blocks"):
            if key in r:
                r[key] = {"True": True, "False": False}.get(r[key], r[key])
        for key, value in list(r.items()):
            if key.startswith(("all_", "tail_", "on_", "off_")):
                r[key] = _float(value)
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
    p.add_argument("--out-attempts", default=None)
    p.add_argument("--warmup", type=float, default=WARMUP_S)
    p.add_argument("--pilot", action="store_true")
    p = sub.add_parser("judge")
    p.add_argument("--runs-table", required=True)
    p.add_argument("--tails-table", required=True)
    p.add_argument("--ladder-table", default=None)
    p.add_argument("--attempts-table", default=None)
    p.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "read":
        rows, tails, skipped, attempts = read_block(args.runs, args.driver, args.broker,
                                                    args.receiver, args.warmup, args.pilot)
        osc.write_csv(args.out_runs, rows)
        osc.write_csv(args.out_tails, tails)
        if args.out_attempts:
            osc.write_csv(args.out_attempts, attempts)
        for run, verdict in skipped:
            print("left out %s: %s" % (run, verdict))
        print("OK %d runs of block U%s -> %s" % (len(rows), "'s pilot" if args.pilot else "",
                                                 args.out_runs))
        return 0
    verdicts = judge(read_table(args.runs_table), read_table(args.tails_table),
                     osc.read_table(args.ladder_table), read_table(args.attempts_table))
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(verdicts, fh, indent=2, sort_keys=True)
        fh.write("\n")
    for name in sorted(k for k in verdicts if k != "described"):
        print("%s: %s" % (name, verdicts[name].get("verdict", "decision recorded")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
