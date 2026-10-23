#!/usr/bin/env python3
"""
general_method.py -- freeze 44's reader and judge (plan version 47, docs/results/general_method/
DESIGN47.md): the general method, a method with a check built in and not a correction, tested on
four brokers (blocks V, N, P, K and C, the Arm pair's block A, and block S, described).

The method has four parts, and every run is read through all of them.

1. Kernel timestamps on the client machine, for every packet, from the client host's own captures
   (sender_full.pcap on the producer's host, receiver_full.pcap in the consumer's namespace), with
   no change to the client; each message matched by the broker's own id (scripts/client_wire.py):
   Kafka's topic, partition and offset, Redis's entry id, NATS JetStream's stream sequence, and on
   an AMQP classic queue the message-id property, checked against the order of the publishes and
   the deliveries. Per message, on the client host's one clock:

     W   t_arrive - t_depart, what reaches this client's kernel;
     D   t_consume - t_prod_send, what reaches the application: the clients' own stamps in
         consumer_events.csv and producer.csv, each joined to the wire by the broker's id. Where
         producer.csv names no broker id (Kafka's, until it carries the partition and offset), the
         producer's side is joined through the wire's own record, by the event id that record
         carries, and the row says so (producer_join).

   The timing is held to the card, an independent clock: per packet, Q is the kernel's capture time
   on receiver_full.pcap less the card's hardware timestamp of the same packet on receiver_hw.pcap,
   put on the system's clock through the card's clock samples (full_fix.to_system). For a Python
   client with socket journals the same messages are timed again by its sockets
   (client_wire.socket_run), W_so, described beside W: the socket and the capture read the same
   kernel value, so their agreement checks the matching, and their tails differ where one read
   took several packets.

2. A check any tool can run from those timestamps: was a request, or a credit, waiting at the
   broker when each message arrived? It is read as scripts/under_load_posthoc.py reads it
   (capture_parts, crossing_floors, readings and _check_fields, reused here): the certain reading,
   by cause and effect alone, a message whose delivering request left the consumer more than the
   resolution after the producer had its acknowledgment; and the estimate, the same test with the
   pair of connections' two crossings added back (C_hat), before the allowance (raw) and after it
   (calibrated). The request is the fetch, the XREADGROUP or the pull request that delivered the
   message, or on RabbitMQ the acknowledgment that freed the credit it went out on. Each reading
   is held message by message against the broker's own record (client_wire.broker_times, by the
   broker's ids): its agreement, its false calls and its misses. The share that found none is
   reported beside the latency. A probe's answer (a PONG, an AMQP synchronous method's -ok) cannot
   have waited, so the probes give the estimate its floor where every request for messages waits.

   Where requests are kept waiting, the clients' timestamps certify that one was, by counting on
   the message's delivering connection (certified): the credit its requests had granted by the
   message's departure less B, less the credit their answers had used by its acknowledgment's
   arrival plus B, is at least one. That holds where every one-way crossing and timing error is
   below B, and each run's checks of B say whether they were: no retransmission and no zero window
   on the delivering connection, its probes' round trips, the largest per-packet Q, and the
   longest silence in the client captures while the plan sent.

3. Three latencies, each named:

     F   what a ready receiver would get, as ready as the protocol allows: where requests or credit
         can wait (Redis, NATS, RabbitMQ), E3 = W - S, S the time the message sat stored at the
         broker before its request came; on Kafka, where they cannot, E2 = W - min(T_c, S), the
         latency had the client asked again at once, its round trip kept as real latency. Each
         from the broker's capture (F) and from the clients' timestamps alone (Fc);
     W   what reaches this client's kernel;
     D   what reaches the application.

   T_c, the turnaround, is version 46's, timed from the client host's capture: the delivering
   request's departure less the arrival of the answer to the previous request for messages on its
   connection, less that connection's other requests' round trips in between. On RabbitMQ it is
   the credit turnaround, a delivery's arrival to the departure of the acknowledgment that frees
   the next credit. Per load state (load_blocks.csv, a message by its departure, none within the
   guard after a switch), the tail mean of a quantity is its mean over the state's messages above
   the state's 99th percentile of W, and a run's on/off ratio the on-state's tail mean over the
   off-state's; read over every message, and over those the broker's record shows found a request
   or credit waiting.

4. The remedy by protocol. On Kafka the gap at the broker, from a fetch answer's departure to the
   next fetch's arrival, is split into the client's part (its turnaround) and the rest, two
   crossings and the broker; beside it, the share of time no fetch waited at the broker, and the
   model lambda g / (lambda g + exp(-lambda g)), lambda the run's send rate and g its median gap.

The judge holds the predictions to the run rows, each in its function's docstring, in
scripts/under_load.py's style: a cell is one setup, or one comparison of two; a setup's value is
the median over its passing runs of each run's statistic, unless a prediction says every run or a
mean; and a cell missing a value it needs is out of reach, reported and not judged. "Held still" is
an equivalence test within runs: two one-sided t-tests across a setup's runs on the logarithms of
its per-run on/off ratios, at ALPHA, within 1/HOLDS_STILL and HOLDS_STILL, with the plain ratio
beside it. Every judged share has a run-level bootstrap interval. Block S is described only; block
A repeats V-a, M2-c and KC-d on the Arm pair.

CLI:
    python scripts/general_method.py calibrate --runs FOLDER [--runs ...] --driver IP --broker IP \
        --receiver IP --out JSON
    python scripts/general_method.py read --runs FOLDER [--runs ...] --driver IP --broker IP \
        --receiver IP --allowance JSON --out-runs CSV [--warmup S] [--pilot]
    python scripts/general_method.py judge --runs-table CSV --out JSON [--draws N]
"""
import argparse
import bisect
import csv
import json
import math
import os
import random
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import client_wire as cw  # noqa: E402
import full_fix as ff  # noqa: E402
import order_scope as osc  # noqa: E402
import recv_wait as rw  # noqa: E402
import under_load as ul  # noqa: E402
import under_load_posthoc as ph  # noqa: E402

# --- the setups ----------------------------------------------------------------------------------

#: A setup's id: its block's letter, its rate, the rest of its name, and "-pilot" for the pilot's
#: runs, which are read only when asked for and never judged. The settings are read from the run's
#: queue row and its consumer's log, never from the id. Block U's ids start with U, so they never
#: match.
SETUP_ID = re.compile(r"^([VNPKCSA])(\d+)-(.+?)(-pilot)?$")

#: The blocks every prediction of the instrument and the check reaches (all but S); those whose
#: other predictions are judged on the second x86 pair; the Arm pair's block, and the scope's,
#: described only. A run on the Arm pair names its machine ARM (meta.json).
CHECKED_BLOCKS = ("V", "N", "P", "K", "C", "A")
JUDGED_BLOCKS = ("V", "N", "P", "K", "C")
REPLICATION_BLOCK, SCOPE_BLOCK = "A", "S"
ARM = "aarch64"

#: Each broker's consumer where the queue row names none (block U's runs); the Kafka clients that
#: fetch inside poll() on the caller's thread, and librdkafka, whose broker thread fetches; and
#: nats.go's Consume(), which keeps its own requests waiting.
CONSUMERS = {"kafka": "kafka-python", "redis": "redis-py", "nats": "python", "rabbitmq": "pika"}
IN_POLL = ("kafka-python", "java", "franz")
LIBRDKAFKA, NATS_GO = "confluent", "nats-go"

#: The run's warm-up, left out of every reading, and the load's two states.
WARMUP_S = ul.WARMUP_S
STATES = ("on", "off")

#: What a ready receiver is on each broker: a request always waiting (E3), or, on Kafka, one asked
#: again at once (E2).
READY = dict(ph.READY, nats="E3", rabbitmq="E3")

#: The percentile above a state's tail: its top 1% of W. The quantities whose tail means each state
#: gives, over its top 1% of W: W, D, the ready receiver's latency from the broker (F) and from the
#: clients alone (Fc), E2 (W less min(T_c, S)), W less what the turnaround surely added (Fs), and
#: the turnaround of each message's delivering request (Tc).
TAIL_PERCENTILE = ul.TAIL_PERCENTILE
TAILED = ("W", "D", "F", "Fc", "E2", "Fs", "Tc")

# --- the predictions' margins (DESIGN47.md) ------------------------------------------------------

#: M1-a: per packet, the kernel's capture time less the card's hardware timestamp: its 99th
#: percentile at most Q_P99_US in every run with the card captured, and none below minus the
#: card's clock window (block U, per packet: 18-20 us on Redis and idle Kafka, 82-99 us on loaded
#: Kafka, never earlier).
Q_P99_US = 150.0
#: M1-c, at WAITING_DEPTH: with one reply per read, the sockets' 99th percentile of W within
#: M1C_ONE_US of the capture's; with the library's own reads, under load, at least M1C_LIBRARY_US
#: above it.
M1C_ONE_US = 10.0
M1C_LIBRARY_US = 100.0
#: M2-b: in every run where the estimate has a value, its share that found none within this many
#: points of the broker's (block U's largest, read after its verdicts, was 5.9).
M2B_POINTS = 6.0
#: M2-c, the remedy's own check (V and N at WAITING_DEPTH, nats.go, P at WAITING_PREFETCH): the
#: broker's record shows a request or credit waiting for at least M2C_WAITING of messages, and the
#: clients' own timestamps certify one waiting, by counting (certified), for at least
#: M2C_CERTIFIED of them, with the bound B at CERTIFY_B_MS; the same at CERTIFY_B_DESCRIBED_MS is
#: described beside it.
M2C_WAITING = 0.999
M2C_CERTIFIED = 0.999
CERTIFY_B_MS = 10.0
CERTIFY_B_DESCRIBED_MS = 2.0
WAITING_DEPTH, WAITING_PREFETCH = 256, 1000
#: The checks of B, run by run, on the delivering connection, while the measured messages were
#: sent (from the warm-up's end to the plan's last send): no retransmission (a tail-loss probe
#: among them) and no zero window in the client host's capture; the longest probe round trip on the
#: same connection below B (on Redis, where nothing overtakes a blocked read, the XACK
#: connection's, a proxy); the longest per-packet Q below Q_SHARE_OF_B of B, since a receive
#: timestamp late by more than that could make an answer seem later than it was; and no stretch
#: longer than B
#: with no packet in either client capture.
Q_SHARE_OF_B = 0.5
PROBES = {"nats": "PING on the receive connection",
          "rabbitmq": "a synchronous method on the consumer's connection",
          "redis": "XACK on the second connection, a proxy: nothing overtakes a blocked read",
          "kafka": "requests for no messages on the fetch connection"}
#: M3-b's setups that leave a gap: V and N at GAPPED_DEPTH, P at GAPPED_PREFETCH, and the in-poll
#: Kafka clients at normal priority.
GAPPED_DEPTH, GAPPED_PREFETCH = 1, 1
#: M3-a and KC-d: W's tail is held still where its on/off ratio is equivalent to 1 within
#: HOLDS_STILL; D grows where its ratio is at least GROWTH. M3-b and KC-a: GROWTH again. M3-b and
#: KC-b: the least share of W's tail rise that removing the turnaround takes out. KC-c: the most
#: librdkafka's rise of the turnaround's tail may be of each in-poll client's. KC-h: the most the
#: turnaround's tail ratio may be with librdkafka's broker thread at real-time priority, and the
#: least share of messages that found no fetch waiting in each load state. C-a: the most the
#: isolated, sibling-idle arm's residual may be of the baseline's.
HOLDS_STILL = 1.2
GROWTH = ul.GROWTH
HALF = ul.HALF
KC_C_FRACTION = 0.5
KC_H_RATIO = 1.2
KC_H_UNWAITED = 0.5
C_A_FRACTION = 1.0 / 3.0
#: The equivalence test: its level, and the fewest runs it reads.
ALPHA = 0.05
TOST_MIN_RUNS = 2
#: Every judged share's interval: the runs resampled with replacement, each run's on- and
#: off-blocks together, this many times from this seed, and the central INTERVAL of the shares.
BOOTSTRAP = ul.BOOTSTRAP
BOOTSTRAP_SEED = 20261104
INTERVAL = ul.INTERVAL

#: The settings a cell lists, from its first run.
CELL_FIELDS = ("block", "rate", "backend", "consumer", "depth", "one_reply", "prefetch",
               "fetch_rt", "priority", "producer_priority", "whole_core", "sibling_load",
               "load_kind", "arch")

#: The fields described setup by setup, the median over its runs.
DESCRIBED = ("timed", "d_joined", "W_p50", "W_p99", "D_p50", "D_p99", "F_p50", "F_p99", "Fc_p50",
             "Fc_p99", "Tc_p50", "Tc_p99", "W_so_p50", "W_so_p99", "q_p50", "q_p99", "q_min",
             "certified_share", "certified_share_2ms", "retransmitted", "zero_windows",
             "probe_max_us", "q_max_us", "silence_max_us",
             "cap_certain_none_share", "cap_calibrated_none_share", "broker_none_share",
             "broker_waiting_share", "broker_close_share", "cap_certain_agree",
             "cap_calibrated_agree", "so_certain_agree", "so_calibrated_agree", "W_ratio",
             "D_ratio", "F_ratio", "Tc_ratio", "D_own_ratio", "Tc_req_ratio", "waiting_W_ratio",
             "waiting_D_ratio", "e2_share", "m1_dif_p50", "m1_dif_p99", "m1_tail_diff",
             "lam_per_s", "g_us", "g_turnaround_us", "g_rest_us", "nofetch_time_share",
             "kch_predicted", "softnet_squeezed", "softnet_dropped", "softirq_s")


def _p(values, q):
    return rw.percentile(values, q) if values else None


def _mean(values):
    return statistics.fmean(values) if values else None


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def _share(part, whole):
    return part / float(whole) if whole else None


def _ratio(on, off):
    return on / off if None not in (on, off) and off > 0 else None


def _int(value):
    """A value as a whole number, or None where it is empty or not one."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _flag(value):
    """A setting as true or false: a JSON boolean, a number, or the words a log or a table gives."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "one-reply")
    return bool(value)


# --- the run's setup -----------------------------------------------------------------------------

def setup_of(run_dir):
    """(the setup's id, its block's letter, whether it is a pilot's, its rate, the queue row's
    params); the letter and the rate None for an id of no block here."""
    setup, params = osc.setup_of(run_dir)
    m = SETUP_ID.match(setup)
    if m is None:
        return setup, None, False, None, params
    return setup, m.group(1), bool(m.group(4)), int(m.group(2)), params


#: A word=value setting on a client's CONFIG effective line.
SETTING = re.compile(r"(\w+)=(\S+)")


def client_config(run_dir):
    """{setting: value} from the CONFIG effective lines of the consumer's log, the settings the
    client says it ran with; {} where the run has no log."""
    path = os.path.join(run_dir, "consumer.log")
    found = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("CONFIG effective"):
                    found.update(SETTING.findall(line))
    return found


def run_settings(run_dir, backend, params, config):
    """The run's settings, each as its consumer's log says it applied it where the log says, else
    as its queue row asked: the consumer; the requests kept waiting (depth, Redis and NATS) and the
    credit (prefetch, RabbitMQ); whether each read takes one reply; Kafka's broker thread at
    real-time priority; the priorities; the whole-core arms' settings; the load's kind, level and
    blocks; the sends' arrival process; NATS's storage; and the machine."""
    depth = _int(config.get("depth", params.get("depth")))
    if depth is None and backend in ("redis", "nats"):
        depth = 1
    reads = config.get("reads", config.get("one_reply_reads"))
    platform = rw.read_json(os.path.join(run_dir, "meta.json")).get("host_platform") or {}
    return {"consumer": params.get("consumer") or CONSUMERS.get(backend),
            "depth": depth, "depth_asked": _int(params.get("depth")),
            "one_reply": _flag(params.get("one_reply_reads") if reads is None else reads),
            "prefetch": _int(config.get("prefetch", params.get("prefetch"))),
            "ack_batch": _int(config.get("ack_batch", params.get("ack_batch"))),
            "fetch_rt": _flag(params.get("fetch_rt")), "priority": _flag(params.get("priority")),
            "producer_priority": _flag(params.get("producer_priority")),
            "whole_core": _flag(params.get("whole_core")),
            "sibling_load": _flag(params.get("sibling_load")), "irq_cpus": params.get("irq_cpus"),
            "irqbalance_off": _flag(params.get("irqbalance_off")),
            "rps_off": _flag(params.get("rps_off")), "load_kind": params.get("load_kind"),
            "load_pct": params.get("load_pct"), "duty_pct": params.get("duty_pct"),
            "arrival": params.get("arrival"), "storage": config.get("storage"),
            "blocks": os.path.exists(os.path.join(run_dir, "load_blocks.csv")),
            "arch": platform.get("machine")}


# --- the clients' own files ----------------------------------------------------------------------

def key_of(backend, row):
    """A message's broker id from a row of client_wire's, or of a client's own file: Kafka's
    (topic, partition, offset), Redis's (stream, milliseconds, sequence), NATS's (stream, stream
    sequence), AMQP's (queue, message id); None where the row lacks one."""
    try:
        if backend == "kafka":
            return row["topic"], int(row["partition"]), int(row["offset"])
        if backend == "redis":
            ms, seq = str(row["redis_id"]).split("-")
            return row["stream"], int(ms), int(seq)
        if backend == "nats":
            return row["stream"], int(row["stream_seq"])
        queue = row.get("queue", row.get("stream"))
        return None if not row.get("message_id") else (queue, row["message_id"])
    except (KeyError, TypeError, ValueError):
        return None


def consumer_stamps(run_dir, backend):
    """{broker id: t_consume_ns} from consumer_events.csv, each message's first stamp kept."""
    found = {}
    for r in ul._rows(os.path.join(run_dir, "consumer_events.csv")):
        key = key_of(backend, r)
        if key is not None and r.get("t_consume_ns"):
            found.setdefault(key, int(r["t_consume_ns"]))
    return found


def producer_join(run_dir, backend):
    """(a function from a wire message's row to its producer's send stamp, t_prod_send_ns, None
    where it has none, and how the producer's side is joined): by the broker's id where
    producer.csv names it, Redis's entry id, NATS's stream sequence, or Kafka's partition and
    offset once the file carries them; on RabbitMQ by the confirm number the producer's channel
    gave each publish, which the wire's own publish carries; else, on Kafka, by the event id the
    wire's own record carries."""
    rows = [r for r in ul._rows(os.path.join(run_dir, "producer.csv")) if r.get("t_prod_send_ns")]
    if backend == "rabbitmq":
        numbers = dict((_int(r.get("delivery_tag")), int(r["t_prod_send_ns"])) for r in rows)
        return (lambda m: numbers.get(m["request"])), "confirm number"
    keyed = [r for r in rows if key_of(backend, r) is not None]
    if keyed:
        sent = {}
        for r in keyed:
            sent.setdefault(key_of(backend, r), int(r["t_prod_send_ns"]))
        return (lambda m: sent.get(key_of(backend, m))), "broker id"
    by_event = dict((r["event_id"], int(r["t_prod_send_ns"])) for r in rows)
    return (lambda m: by_event.get(m["eid_sent"])), "the wire's record"


def first_send(run_dir):
    """The run's first send stamp, from which its warm-up is counted; None without one."""
    sent = [int(r["t_prod_send_ns"]) for r in ul._rows(os.path.join(run_dir, "producer.csv"))
            if r.get("t_prod_send_ns")]
    return min(sent) if sent else None


# --- the turnaround and the gap at the broker ----------------------------------------------------

def turnarounds(exchanges):
    """({(consumer port, exchange): T_c in us} for every request that can wait at the broker (a
    fetch, an XREADGROUP or XREAD, a pull request, an acknowledgment that frees a credit), timed
    from the capture as scripts/under_load.py times it from the journal: its departure less the
    previous such request's answer's arrival, less the time within that gap the connection's other
    requests spent at the broker, zero where negative, None where a time is missing; and how many
    came out negative, a request sent before the previous answer came in, as requests kept waiting
    are)."""
    by_port, gaps, overlapped = {}, {}, 0
    for r in exchanges:
        by_port.setdefault(r["consumer_port"], []).append(r)
    for port, rows in by_port.items():
        ask, others = None, []
        for r in sorted(rows, key=lambda r: r["exchange"]):
            if r["kind"] not in cw.WAITING_KINDS:
                others.append((r["t_req"], r["t_ans"]))
                continue
            gap = None
            if ask is not None and r["t_req"] is not None:
                spent = r["t_req"] - ask - ul.covered([s for s in others if None not in s], ask,
                                                       r["t_req"])
                overlapped += spent < 0
                gap = max(0, spent) / 1e3
            gaps[(port, r["exchange"])] = gap
            ask, others = r["t_ans"], []
    return gaps, overlapped


def broker_gaps(exchanges, lo, hi):
    """{(consumer port, exchange): the gap at the broker, us, from the previous request for
    messages' answer's departure to this one's arrival on the same connection, zero where it came
    first}, for the requests that arrived within [lo, hi] on the broker's clock; and the share of
    that window in which no request for messages was at the broker, from each one's arrival to its
    answer's departure, over every connection. None for the share where the window is not known."""
    by_port, gaps, held = {}, {}, []
    for r in exchanges:
        if r["kind"] in cw.WAITING_KINDS:
            by_port.setdefault(r["consumer_port"], []).append(r)
            held.append((r["t_req"], r["t_ans"]))
    if None in (lo, hi):
        return gaps, None
    for rows in by_port.values():
        rows.sort(key=lambda r: r["exchange"])
        for before, now in zip(rows, rows[1:]):
            if None in (before["t_ans"], now["t_req"]) or not lo <= now["t_req"] <= hi:
                continue
            gaps[(now["consumer_port"], now["exchange"])] = max(
                0, now["t_req"] - before["t_ans"]) / 1e3
    span = hi - lo
    covered = ul.covered([s for s in held if None not in s], lo, hi)
    return gaps, (1.0 - covered / float(span) if span > 0 else None)


def kch_share(lam_per_s, g_us):
    """The model's share of messages that find no fetch waiting, lambda g / (lambda g +
    exp(-lambda g)); None where either is missing."""
    if None in (lam_per_s, g_us):
        return None
    x = lam_per_s * g_us / 1e6
    return x / (x + math.exp(-x))


# --- the instrument ------------------------------------------------------------------------------

def _packets(pcap, broker, receiver, port):
    """{(the receiver's port, sequence number, length): the capture time of the first packet that
    carried it} for every data packet from the broker's port to the receiver one capture holds."""
    found = {}
    if not os.path.exists(pcap):
        return found
    for ns, linktype, frame in rw.read_pcap(pcap):
        ip = rw.ip_payload(linktype, frame)
        seg = None if ip is None else rw.tcp_segment(ip)
        if seg is None or seg[:3] != (broker, receiver, port) or not seg[5]:
            continue
        found.setdefault((seg[3], seg[4], len(seg[5])), ns)
    return found


def card_lags(run_dir, broker, receiver, port):
    """({the receiver's port: [Q, us, for each data packet from the broker on that connection the
    receiver's capture and the card's both hold]}, the card's clock window in ns): Q the packet's
    kernel capture time on receiver_full.pcap less its hardware timestamp on receiver_hw.pcap, put
    on the system's clock through the card's clock samples (full_fix.to_system), a packet being
    the same in both captures by its connection, sequence number and length. (None, window) where
    the run has no card capture or no clock samples."""
    samples = os.path.join(run_dir, "phc_offset.csv")
    hw = os.path.join(run_dir, "receiver_hw.pcap")
    offsets, window = ff.card_offsets(samples), ff.card_window(samples)
    if not os.path.exists(hw) or not offsets:
        return None, window
    kernel = _packets(os.path.join(run_dir, "receiver_full.pcap"), broker, receiver, port)
    card = _packets(hw, broker, receiver, port)
    lags = {}
    for k in sorted(kernel):
        if k in card:
            lags.setdefault(k[0], []).append((kernel[k] - ff.to_system(card[k], offsets)) / 1e3)
    return lags, window


def payload_pairs(run_dir, driver, broker, receiver):
    """The event ids today's payload readers pair across the two client captures, by the packet
    that carried the end of each id out of the driver (full_fix.departure_times) and the moment it
    could first be read on the receiver (recv_wait.kernel_times); None without both captures."""
    sent_path = os.path.join(run_dir, "sender_full.pcap")
    got_path = os.path.join(run_dir, "receiver_full.pcap")
    if not (os.path.exists(sent_path) and os.path.exists(got_path)):
        return None
    sent = ff.departure_times(sent_path, driver, broker)
    return set(sent) & set(rw.kernel_times(got_path, broker, receiver))


def matching_check(backend, messages, paired):
    """M1-b's counts: the messages the broker's ids pair (both a departure and an arrival); the
    event ids the payload's pairing pairs that they do not; and the pairings that differ, a broker
    id whose two sides' event ids differ or are unread, or an event id at two broker ids. On
    RabbitMQ beside them, how many messages a publish's place in the confirm order and its
    delivery's place in the delivery order disagree on, where one connection each way carried them
    all."""
    both = [m for m in messages if m["t_depart"] is not None and m["t_arrive"] is not None]
    named = {}
    for m in both:
        if m["eid_sent"] is not None and m["eid_sent"] == m["eid_got"]:
            named[m["eid_sent"]] = named.get(m["eid_sent"], 0) + 1
    out = {"broker_pairs": len(both), "payload_pairs": None if paired is None else len(paired),
           "m1b_missed": None if paired is None else len(paired - set(named)),
           "m1b_differ": (sum(1 for m in both if m["eid_sent"] is None
                              or m["eid_sent"] != m["eid_got"])
                          + sum(1 for n in named.values() if n > 1)),
           "order_differ": None}
    if backend == "rabbitmq" and both and len(set(m["producer_port"] for m in both)) == 1 \
            and len(set(m["consumer_port"] for m in both)) == 1:
        published = sorted(both, key=lambda m: m["request"])
        got = sorted(both, key=lambda m: m["got_byte"])
        out["order_differ"] = sum(1 for a, b in zip(published, got) if a is not b)
    return out


# --- the check, certain by counting --------------------------------------------------------------

def _running(events):
    """(the times, the running sums of the values) of [(time, value)], in time order."""
    events = sorted(events)
    sums, total = [], 0
    for _, value in events:
        total += value
        sums.append(total)
    return [t for t, _ in events], sums


def _upto(ledger, t):
    """The sum of a ledger's values at times no later than t."""
    times, sums = ledger
    i = bisect.bisect_right(times, t)
    return sums[i - 1] if i else 0


def certified(parts, exchanges, b_ms):
    """(how many of the messages `parts` holds a request, or a credit, was certainly waiting for
    at the broker, how many could be counted), counting on each message's delivering connection:
    the credit its requests had granted by the message's departure (its last byte out) less B,
    each request timed by its own last byte out, less the credit their answers had used by the
    message's acknowledgment's arrival (its first byte in) plus B, each answer timed by its own
    first byte in, is at least one. A request granted one, a pull request its batch, and an AMQP
    consume its prefetch count and each acknowledgment the deliveries it covers; an answer, a 408
    or 409 among them, used what client_wire says it used, a heartbeat or a PONG nothing. So where
    every one-way crossing and timing error is less than B, as the run's checks hold it, a request
    reached the broker before the message did and was still unanswered when it came."""
    ledgers = {}
    for r in exchanges:
        grants, uses = ledgers.setdefault(r["consumer_port"], ([], []))
        if r["grant"] and r["t_req"] is not None:
            grants.append((r["t_req"], r["grant"]))
        uses.extend((t, used) for t, used in r["uses"] if t is not None and used)
    sums = dict((port, (_running(g), _running(u))) for port, (g, u) in ledgers.items())
    held = counted = 0
    b = int(b_ms * 1e6)
    for p in parts:
        m = p["message"]
        if m["t_ack_first"] is None or m["consumer_port"] not in sums:
            continue
        granted, used = sums[m["consumer_port"]]
        counted += 1
        held += _upto(granted, m["t_depart"] - b) - _upto(used, m["t_ack_first"] + b) >= 1
    return held, counted


def probes(backend, exchanges, delivering, lo, hi):
    """[The round trips, us, of the probes the run's checks hold B to, sent within [lo, hi]]: on
    the delivering connection, every request that neither asks for messages nor grants credit (on
    NATS the client's PINGs, on RabbitMQ a synchronous method); on Redis, where nothing overtakes a
    blocked read, every XACK's, on the second connection, a proxy (PROBES names each)."""
    if backend == "redis":
        chosen = [r for r in exchanges if r["kind"] == "XACK"]
    else:
        chosen = [r for r in exchanges if r["consumer_port"] in delivering
                  and r["kind"] not in cw.WAITING_KINDS and not r["grant"]]
    return [(r["t_ans"] - r["t_req"]) / 1e3 for r in chosen
            if None not in (r["t_req"], r["t_ans"], lo, hi) and lo <= r["t_req"] <= hi]


def silence(times, lo, hi):
    """The longest stretch of [lo, hi], us, in which a capture holds no packet; None without the
    window."""
    if None in (lo, hi) or hi <= lo:
        return None
    edges = [lo] + sorted(t for t in times if lo <= t <= hi) + [hi]
    return max(b - a for a, b in zip(edges, edges[1:])) / 1e3


def b_checks(row, b_ms):
    """Whether the run's checks of B hold at `b_ms`, from what read_run measured: no retransmission
    and no zero window on the delivering connection, its probes' longest round trip, the longest Q
    on it, and the longest silence while the plan sent, each below its bound. False where one fails,
    None where one cannot be read."""
    bound = b_ms * 1e3
    return _both(ul._holds(lambda a, z: a == 0 and z == 0, row["retransmitted"],
                           row["zero_windows"]),
                 ul._holds(lambda p: p < bound, row["probe_max_us"]),
                 ul._holds(lambda q: q < Q_SHARE_OF_B * bound, row["q_max_us"]),
                 ul._holds(lambda s: s < bound, row["silence_max_us"]))


#: The columns of /proc/net/softnet_stat a run's snapshots sum over the processors: packets
#: processed, dropped, and the times the receive softirq ran out of budget (time_squeeze); and
#: the softirq time in /proc/stat's cpu line, in clock ticks, its seventh field.
SOFTNET = (("softnet_processed", 0), ("softnet_dropped", 1), ("softnet_squeezed", 2))
TICKS_PER_S = 100.0


def _counters(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as fh:
        return [line.split() for line in fh if line.strip()]


def receive_path(run_dir):
    """Described, for block S: how much the receive path's counters moved over the run, from its
    before and after snapshots: softnet_stat's packets processed and dropped and its squeezes,
    summed over the processors, and the processors' softirq time in seconds; None for each where
    a snapshot is missing."""
    out = dict.fromkeys([name for name, _ in SOFTNET] + ["softirq_s"])
    before, after = (_counters(os.path.join(run_dir, "softnet_%s.txt" % w))
                     for w in ("before", "after"))
    if before and after:
        for name, column in SOFTNET:
            out[name] = sum(int(a[column], 16) - int(b[column], 16)
                            for a, b in zip(after, before))
    before, after = (_counters(os.path.join(run_dir, "stat_%s.txt" % w))
                     for w in ("before", "after"))
    cpu = [rows[0] for rows in (before, after) if rows and rows[0][0] == "cpu"]
    if len(cpu) == 2:
        out["softirq_s"] = (int(cpu[1][7]) - int(cpu[0][7])) / TICKS_PER_S
    return out


# --- one run -------------------------------------------------------------------------------------

def _stats(row, name, values):
    row[name + "_p50"], row[name + "_p99"] = _p(values, 50), _p(values, 99)


def state_tails(row, parts, name=""):
    """Per load state, over the state's messages above its 99th percentile of W, the tail mean of
    each of TAILED, and the state's count; then each one's on/off ratio and its rise, on less off;
    all written under `name`."""
    for state in STATES:
        chosen = [p for p in parts if p["state"] == state]
        cut = _p([p["W"] for p in chosen], TAIL_PERCENTILE)
        top = [p for p in chosen if p["W"] > cut]
        row["%sn_%s" % (name, state)] = len(chosen)
        for q in TAILED:
            row["%s%s_tail_%s" % (name, q, state)] = _mean([p[q] for p in top
                                                           if p[q] is not None])
    for q in TAILED:
        on, off = row["%s%s_tail_on" % (name, q)], row["%s%s_tail_off" % (name, q)]
        row["%s%s_ratio" % (name, q)] = _ratio(on, off)
        row["%s%s_rise" % (name, q)] = None if None in (on, off) else on - off


def own_tails(row, values, name):
    """Described beside the tail means over W's top 1%: a quantity's mean over its own top 1% in
    each load state, from [(value, state)], and the on/off ratio."""
    for state in STATES:
        chosen = [v for v, s in values if s == state and v is not None]
        cut = _p(chosen, TAIL_PERCENTILE)
        row["%s_tail_%s" % (name, state)] = _mean([v for v in chosen if v > cut])
    row[name + "_ratio"] = _ratio(row[name + "_tail_on"], row[name + "_tail_off"])


def _gap_parts(p, gap, cut, lift):
    """Adds to one message what its request's turnaround and a ready receiver make of it: T_c, what
    the turnaround surely added (s_min) and the broker's bound on it (b_min, min(T_c, S)), W less
    the first (Fs), and the ready receiver's latencies, E2 = W - b_min among them, from the broker
    and from the clients alone (under_load_posthoc's ready_latencies, C_hat less the allowance
    where both are known), which need the turnaround."""
    p["Tc"] = gap
    p["s_min"] = None if gap is None else min(gap, max(0.0, p["slack"]))
    p["b_min"] = None if gap is None or p["stored"] is None else min(gap, p["stored"])
    p["Fs"] = None if p["s_min"] is None else p["W"] - p["s_min"]
    p["Fb"] = None if p["b_min"] is None else p["W"] - p["b_min"]
    if gap is None:
        p.update(E2b=None, E3b=None, E2c=None, E3c=None, s_tri=None)
        return
    ph.ready_latencies(p, 0.0 if lift is None or cut is None else lift - cut)


def _check(row, prefix, parts, fetch_min, cut):
    """The check's fields under `prefix` (under_load_posthoc's), with the allowance it took, and
    C_hat per pair before the allowance."""
    raw, true = ph.crossing_floors(parts, fetch_min)
    row[prefix + "timed"], row[prefix + "allowance_us"] = len(parts), cut
    row.update(ph._check_fields(prefix, parts, raw, true, cut))
    return raw


def _broker_shares(row, parts, suffix=""):
    judged = [p for p in parts if p["found"] is not None]
    for kind in ("none", "waiting", "close"):
        row["broker_%s_share%s" % (kind, suffix)] = _share(
            sum(1 for p in judged if p["found"] == kind), len(judged))
    waiting = row["broker_waiting_share" + suffix]
    row["broker_unwaited_share" + suffix] = None if waiting is None else 1.0 - waiting
    return judged


def socket_side(row, run_dir, backend, at_broker, cut_ns, allowance):
    """The check again from the clients' own sockets, one timestamp per read (client_wire's
    socket_run, by broker ids), its fields named so_; and {broker id: W_so}. Both empty where the
    run wrote no journals."""
    messages, exchanges, summary = cw.socket_run(run_dir)
    if not messages:
        return {}
    parts, fetch_min = ph.capture_parts(messages, exchanges, at_broker, cut_ns,
                                        lambda m: key_of(backend, m))
    _check(row, "so_", parts, fetch_min, allowance.get("sockets", {}).get(backend))
    row["so_unread"] = summary["unreadable"]
    return dict((key_of(backend, m), (m["t_arrive"] - m["t_depart"]) / 1e3) for m in messages
                if None not in (m["t_depart"], m["t_arrive"]))


def instrument(row, parts, sockets):
    """W_so beside W over the messages both time, described (M1-c reads its tails): how many; the
    median and the 99th percentile of |W_so - W|, which check the matching, the two reading one
    kernel value; and the sockets' 99th percentile of W less the capture's, over every such message
    and over each load state's."""
    both = [(sockets[p["key"]], p) for p in parts if sockets.get(p["key"]) is not None]
    row["m1_matched"] = len(both)
    _stats(row, "m1_dif", [abs(w - p["W"]) for w, p in both])
    _stats(row, "W_so", [w for w, _ in both])
    for suffix, chosen in (("", both), ("_on", [b for b in both if b[1]["state"] == "on"]),
                           ("_off", [b for b in both if b[1]["state"] == "off"])):
        socket_tail, capture_tail = (_p([w for w, _ in chosen], 99),
                                     _p([p["W"] for _, p in chosen], 99))
        row["m1_tail_diff" + suffix] = (None if socket_tail is None
                                        else socket_tail - capture_tail)


def read_run(run_dir, driver, broker, receiver, allowance=None, warmup_s=WARMUP_S):
    """One run's row: its settings; the wire's counts; the card's check of the timing; the check
    from the captures, and from the sockets where the client journaled them, each held to the
    broker's record; the three latencies; each load state's tail means and ratios, over every
    message and over those that found a request waiting; Kafka's gap at the broker; and M1-b's
    matching. `allowance` is {"capture": {broker: us}, "sockets": {broker: us}}; the calibrated
    readings have no value without one."""
    setup, block, pilot, rate, params = setup_of(run_dir)
    backend = cw.backend_of(run_dir)
    allowance = allowance or {}
    row = {"run": os.path.basename(run_dir), "setup": setup, "block": block, "pilot": pilot,
           "rate": rate, "backend": backend,
           "verdict": rw.read_json(os.path.join(run_dir, "integrity.json")).get("verdict")}
    row.update(run_settings(run_dir, backend, params, client_config(run_dir)))
    messages, exchanges, wire, conns = cw.read_detail(run_dir, driver, broker, receiver)
    for name in ("matched", "sent_only", "got_only", "ids_differ", "ids_unread", "unreadable",
                 "holes", "unopened", "unframed"):
        row["wire_" + name] = wire[name]
    at_broker, broker_exchanges, at_wire = cw.broker_times(run_dir, driver, broker, receiver)
    row["broker_matched"], row["broker_unreadable"] = at_wire["matched"], at_wire["unreadable"]
    by_port, row["card_window_ns"] = card_lags(run_dir, broker, receiver, cw.PORTS[backend])
    lags = None if by_port is None else [q for port in sorted(by_port) for q in by_port[port]]
    row["q_n"] = None if lags is None else len(lags)
    _stats(row, "q", lags or [])
    row["q_min"] = min(lags) if lags else None
    # Whole nanoseconds, as under_load counts the warm-up: a float would not hold them exactly.
    first = first_send(run_dir)
    cut_ns = 0 if first is None else first + int(warmup_s * 1e9)
    key = lambda m: key_of(backend, m)  # noqa: E731
    parts, fetch_min = ph.capture_parts(messages, exchanges, at_broker, cut_ns, key)
    cut = allowance.get("capture", {}).get(backend)
    raw = _check(row, "cap_", parts, fetch_min, cut)
    row["broker_found"] = len(_broker_shares(row, parts))
    row["broker_none0_share"] = _share(sum(1 for p in parts if p["found"] is not None
                                           and p["stored"] > 0), row["broker_found"])
    gaps, row["overlapped"] = turnarounds(exchanges)
    send_of, row["producer_join"] = producer_join(run_dir, backend)
    got = consumer_stamps(run_dir, backend)
    switches = ul.load_switches(run_dir)
    ready = READY[backend]
    for p in parts:
        m = p["message"]
        p["key"] = key(m)
        t_send, t_got = send_of(m), got.get(p["key"])
        p["D"] = None if None in (t_send, t_got) else (t_got - t_send) / 1e3
        p["state"] = ul.block_state(switches, m["t_depart"])
        _gap_parts(p, gaps.get(p["request"]), cut, raw.get(p["pair"]))
        p["F"], p["Fc"], p["E2"] = p[ready + "b"], p[ready + "c"], p["E2b"]
    row["timed"], row["d_joined"] = len(parts), sum(1 for p in parts if p["D"] is not None)
    row["untimed_gap"] = sum(1 for p in parts if p["Tc"] is None)
    for name in ("W", "D", "F", "Fc", "E2b", "E3b", "E2c", "E3c", "Fs"):
        _stats(row, name, [p[name] for p in parts if p[name] is not None])
    # The turnaround is also read over the requests sent while the measured messages were in
    # flight, from the warm-up's end to the last one's arrival, each in the state it was sent in.
    last = max((p["message"]["t_arrive"] for p in parts), default=None)
    within = []
    for r in exchanges:
        k = (r["consumer_port"], r["exchange"])
        if k in gaps and None not in (r["t_req"], last) and cut_ns <= r["t_req"] <= last:
            within.append((gaps[k], ul.block_state(switches, r["t_req"])))
    row["requests"] = len(within)
    _stats(row, "Tc", [g for g, _ in within if g is not None])
    state_tails(row, parts)
    state_tails(row, [p for p in parts if p["found"] == "waiting"], "waiting_")
    own_tails(row, [(p["D"], p["state"]) for p in parts], "D_own")
    own_tails(row, within, "Tc_req")
    for state in STATES:
        _broker_shares(row, [p for p in parts if p["state"] == state], "_" + state)
    on, off = row["W_tail_on"], row["W_tail_off"]
    e2_on, e2_off = row["E2_tail_on"], row["E2_tail_off"]
    row["e2_share"] = (None if None in (on, off, e2_on, e2_off) or on <= off
                       else 1.0 - (e2_on - e2_off) / (on - off))
    # The gap at the broker, over the measured messages' span there, from the first one's arrival
    # to the last one's departure; and the send rate over their departures.
    departed = [p["message"]["t_depart"] for p in parts]
    span = (max(departed) - min(departed)) / 1e9 if departed else 0.0
    row["lam_per_s"] = (len(parts) - 1) / span if span > 0 else None
    on_broker = [at_broker.get(p["key"]) for p in parts]
    lo = min((b[0] for b in on_broker if b and b[0] is not None), default=None)
    hi = max((b[3] for b in on_broker if b and b[3] is not None), default=None)
    at_gaps, row["nofetch_time_share"] = broker_gaps(broker_exchanges, lo, hi)
    row["g_n"], row["g_us"] = len(at_gaps), _p(list(at_gaps.values()), 50)
    split = [(g, gaps.get(k)) for k, g in at_gaps.items() if gaps.get(k) is not None]
    row["g_turnaround_us"] = _p([t for _, t in split], 50)
    row["g_rest_us"] = _p([g - t for g, t in split], 50)
    row["kch_predicted"] = kch_share(row["lam_per_s"], row["g_us"])
    certify(row, run_dir, backend, parts, exchanges, conns, by_port, cut_ns, last)
    row.update(matching_check(backend, messages, payload_pairs(run_dir, driver, broker,
                                                               receiver)))
    instrument(row, parts, socket_side(row, run_dir, backend, at_broker, cut_ns, allowance))
    row.update(receive_path(run_dir))
    return row


def _within(times, lo, hi):
    return sum(1 for t in times if lo <= t <= hi)


def certify(row, run_dir, backend, parts, exchanges, conns, by_port, cut_ns, last):
    """M2-c's client clause in one run: the share of messages certified (certified) at B and at
    the described B; and what its checks of B read, on the delivering connection, the consumer's
    connections that delivered the measured messages, while the measured messages were sent, from
    the warm-up's end to the plan's last send: the retransmissions and zero windows there (beside
    them, those of the whole run and the producer's), the probes' round trips while the messages
    were in flight (what the probes were, said), the longest Q on the delivering connection, and
    the longest silence in either client capture; then whether the checks hold at each B. A
    stall in the warm-up, such as a producer's wait at its first send, touches no measured
    message."""
    for name, b_ms in (("", CERTIFY_B_MS), ("_2ms", CERTIFY_B_DESCRIBED_MS)):
        held, counted = certified(parts, exchanges, b_ms)
        row["certified_n" + name] = held
        row["certified_share" + name] = _share(held, counted)
    sent = [int(r["t_prod_send_ns"]) for r in ul._rows(os.path.join(run_dir, "producer.csv"))
            if r.get("t_prod_send_ns")]
    lo, hi = cut_ns, max(sent) if sent else None
    delivering = set(p["message"]["consumer_port"] for p in parts)
    mine = [c for port, c in conns["getting"].items() if port in delivering]
    row["delivering"] = ";".join(str(port) for port in sorted(delivering))
    for name, field in (("retransmitted", "resent"), ("zero_windows", "zero_windows")):
        row[name] = (sum(_within(getattr(c, field), lo, hi) for c in mine)
                     if mine and hi is not None else None)
        row[name + "_run"] = sum(len(getattr(c, field)) for c in mine) if mine else None
    row["retransmitted_producer"] = sum(len(c.resent) for c in conns["sending"].values())
    trips = probes(backend, exchanges, delivering, cut_ns, last)
    row["probe_kind"], row["probe_n"] = PROBES[backend], len(trips)
    row["probe_max_us"] = max(trips) if trips else None
    q = [x for port in delivering for x in (by_port or {}).get(port, [])]
    row["q_max_us"] = max(q) if q else None
    quiet = [silence([t for c in conns[side].values() for t in c.packets], lo, hi)
             if conns[side] else None for side in ("sending", "getting")]
    row["silence_max_us"] = None if None in quiet else max(quiet)
    row["b_checks"] = b_checks(row, CERTIFY_B_MS)
    row["b_checks_2ms"] = b_checks(row, CERTIFY_B_DESCRIBED_MS)


# --- the block -----------------------------------------------------------------------------------

def block_runs(folders, pilot=False):
    """({setup: [run folder]} for the passing runs of plan version 47's blocks, [(run, verdict)]
    for the others). The pilot's runs are read only when asked for, and never judged."""
    found, skipped = {}, []
    for folder in folders:
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if not name.startswith("law_") or not os.path.isdir(path):
                continue
            m = SETUP_ID.match(osc.setup_of(path)[0])
            if m is None or bool(m.group(4)) != pilot:
                continue
            verdict = rw.read_json(os.path.join(path, "integrity.json")).get("verdict")
            if verdict != rw.PASSING:
                skipped.append((name, verdict or "not judged"))
                continue
            found.setdefault(m.group(0), []).append(path)
    return found, skipped


def read_block(folders, driver, broker, receiver, allowance=None, warmup_s=WARMUP_S, pilot=False):
    """(one row per passing run, [(run, verdict)] for the runs left out)."""
    found, skipped = block_runs(folders, pilot)
    rows = [read_run(path, driver, broker, receiver, allowance, warmup_s)
            for setup in sorted(found) for path in found[setup]]
    return rows, skipped


def calibrate(rows):
    """{"sockets": {broker: us}, "capture": {broker: us}}: each instrument's allowance per broker
    from a pilot's rows, as under_load_posthoc calibrates it: the largest overshoot of C_hat over
    the least C the broker's capture shows, rounded up, never below zero."""
    return ph.calibrate([{"backend": r["backend"], "overshoot_max_us": r.get("so_overshoot_max_us"),
                          "cap_overshoot_max_us": r.get("cap_overshoot_max_us")} for r in rows])


# --- the judgments -------------------------------------------------------------------------------

def _f(row, field):
    return ul._float(row.get(field))


def _setups(rows, test):
    """[(setup, its runs)], in order, for each setup whose first run passes `test`."""
    by = {}
    for r in rows:
        by.setdefault(r["setup"], []).append(r)
    return [(setup, by[setup]) for setup in sorted(by) if test(by[setup][0])]


def _cell(setup, runs, **values):
    cell = {"setup": setup, "runs": len(runs)}
    cell.update((field, runs[0].get(field)) for field in CELL_FIELDS)
    cell.update(values)
    return cell


def _both(*clauses):
    """A cell from its clauses: a clause that failed fails it, whether or not another could be
    read; else one that could not be read leaves it out of reach."""
    return False if False in clauses else (None if None in clauses else True)


def _every(runs, test, *fields):
    """Whether `test` holds in every run: False where a run that has every value fails it, else
    None where a run lacks one, else True."""
    return _both(*[ul._holds(test, *(_f(r, f) for f in fields)) for r in runs])


def _judged(checks):
    """A prediction's verdict over its cells, as under_load judges them: a cell missing a value it
    needs is out of reach; a cell left unjudged because the prediction it rests on did not hold
    there (judged false) is listed apart, and a prediction left unjudged in every cell that way is
    "not judged"."""
    reached = [c for c in checks if c.get("judged", True)]
    out = {"verdict": ul._verdict(reached), "checks": checks,
           "out_of_reach": [c["setup"] for c in reached if c["holds"] is None],
           "not_judged": [c["setup"] for c in checks if not c.get("judged", True)]}
    if out["verdict"] == "out of reach" and out["not_judged"] and not out["out_of_reach"]:
        out["verdict"] = "not judged"
    return out


def holds_still(ratios, margin=HOLDS_STILL, alpha=ALPHA):
    """(whether the per-run on/off ratios are held still, the equivalence test's p): two one-sided
    t-tests across runs on the ratios' logarithms, that their mean lies above -log(margin) and below
    log(margin), each at `alpha`; held still where both reject. Runs whose ratios are all alike are
    held still where that ratio lies inside the margin. None, None with fewer than TOST_MIN_RUNS
    runs, or a run with no ratio."""
    from scipy import stats
    if len(ratios) < TOST_MIN_RUNS or any(r is None or r <= 0 for r in ratios):
        return None, None
    logs = [math.log(r) for r in ratios]
    bound, mean, sd = math.log(margin), statistics.fmean(logs), statistics.stdev(logs)
    if sd == 0:
        p = 0.0 if abs(mean) < bound else 1.0
    else:
        se, df = sd / math.sqrt(len(logs)), len(logs) - 1
        p = float(max(1.0 - stats.t.cdf((mean + bound) / se, df),
                      stats.t.cdf((mean - bound) / se, df)))
    return p < alpha, p


def onoff_share(runs, field="E2"):
    """The share of W's tail rise that removing the turnaround takes out, within runs:
    1 - (F_on - F_off) / (W_on - W_off), each the mean over the runs of the run's tail mean in that
    state, F being E2 = W - min(T_c, S); None where a value is missing or W's tail did not rise."""
    off = [{"W_tail": r.get("W_tail_off"), "F_tail": r.get(field + "_tail_off")} for r in runs]
    on = [{"W_tail": r.get("W_tail_on"), "F_tail": r.get(field + "_tail_on")} for r in runs]
    return ul.removal_share(off, on)


def share_interval(runs, field="E2", draws=BOOTSTRAP, seed=BOOTSTRAP_SEED):
    """(low, high, draws without a share): onoff_share with the runs resampled with replacement,
    each run's two states together, the central INTERVAL of the shares that came out; None, None
    where none did."""
    rng = random.Random(seed)
    shares = []
    for _ in range(draws):
        share = onoff_share([rng.choice(runs) for _ in runs], field)
        if share is not None:
            shares.append(share)
    if not shares:
        return None, None, draws
    return (rw.percentile(shares, 100 * (1 - INTERVAL) / 2),
            rw.percentile(shares, 100 * (1 + INTERVAL) / 2), draws - len(shares))


def _median_of(runs, field):
    return _median([_f(r, field) for r in runs])


def _three(value):
    """A check's result as a table holds it: True, False, or None where it could not be read."""
    return {True: True, "True": True, False: False, "False": False}.get(value)


def _certified(runs, suffix=""):
    """(a setup's certified share, the median over the runs whose checks of B hold, None where
    none does; and each run's (checks, share)), at B or, with suffix "_2ms", at the described B."""
    each = [(_three(r.get("b_checks" + suffix)), _f(r, "certified_share" + suffix))
            for r in runs]
    return _median([share for held, share in each if held]), each


def _python(row):
    return (_f(row, "m1_matched") or 0) > 0


def _waiting(row):
    """A setup that keeps requests or credit waiting: V and N at WAITING_DEPTH, nats.go, and P at
    WAITING_PREFETCH."""
    return ((row["block"] in ("V", "N") and _int(row.get("depth")) == WAITING_DEPTH)
            or (row["block"] == "N" and row.get("consumer") == NATS_GO)
            or (row["block"] == "P" and _int(row.get("prefetch")) == WAITING_PREFETCH))


def _kafka_normal(row):
    return row["block"] == "K" and not row.get("fetch_rt") and not row.get("priority")


def _in_poll(row):
    return _kafka_normal(row) and row.get("consumer") in IN_POLL


def _gapped(row):
    """A setup that leaves a gap: V and N at GAPPED_DEPTH (not nats.go), P at GAPPED_PREFETCH, and
    every in-poll Kafka client at normal priority."""
    return ((row["block"] in ("V", "N") and _int(row.get("depth")) == GAPPED_DEPTH
             and row.get("consumer") != NATS_GO)
            or (row["block"] == "P" and _int(row.get("prefetch")) == GAPPED_PREFETCH)
            or _in_poll(row))


def _fetch_rt(row):
    return row["block"] == "K" and row.get("consumer") == LIBRDKAFKA and bool(row.get("fetch_rt"))


def judge_card(rows):
    """M1-a: in every run with the card captured, Q's 99th percentile is at most Q_P99_US, and no Q
    is below minus the card's clock window."""
    checks = []
    for s, runs in _setups(rows, lambda r: True):
        carded = [r for r in runs if (_f(r, "q_n") or 0) > 0]
        windows = [None if _f(r, "card_window_ns") is None else _f(r, "card_window_ns") / 1e3
                   for r in carded]
        held = [_both(ul._holds(lambda q: q <= Q_P99_US, _f(r, "q_p99")),
                      ul._holds(lambda q, w: q >= -w, _f(r, "q_min"), w))
                for r, w in zip(carded, windows)]
        checks.append(_cell(s, runs, q_p99=[_f(r, "q_p99") for r in carded],
                            q_min=[_f(r, "q_min") for r in carded], window_us=windows,
                            holds=_both(*held) if held else None))
    return _judged(checks)


def judge_matching(rows):
    """M1-b: the broker-id matching pairs every message the payload-id matching pairs, and pairs
    none differently, in every run; on RabbitMQ, the confirm order and the delivery order agree
    too."""
    checks = []
    for s, runs in _setups(rows, lambda r: True):
        clauses = [_every(runs, lambda n: n == 0, "m1b_missed"),
                   _every(runs, lambda n: n == 0, "m1b_differ")]
        if runs[0]["backend"] == "rabbitmq":
            clauses.append(_every(runs, lambda n: n == 0, "order_differ"))
        checks.append(_cell(s, runs, missed=[_f(r, "m1b_missed") for r in runs],
                            differ=[_f(r, "m1b_differ") for r in runs],
                            order_differ=[_f(r, "order_differ") for r in runs],
                            holds=_both(*clauses)))
    return _judged(checks)


def judge_reads(rows):
    """M1-c, on V and N at WAITING_DEPTH: with one reply per read, the sockets' 99th percentile of
    W is within M1C_ONE_US of the capture's; with the library's own reads, under load (the
    on-blocks), it exceeds the capture's by at least M1C_LIBRARY_US."""
    checks = []
    for s, runs in _setups(rows, lambda r: r["block"] in ("V", "N") and _python(r)
                           and _int(r.get("depth")) == WAITING_DEPTH):
        if runs[0].get("one_reply"):
            diff = _median_of(runs, "m1_tail_diff")
            holds = ul._holds(lambda d: abs(d) <= M1C_ONE_US, diff)
        else:
            diff = _median_of(runs, "m1_tail_diff_on")
            holds = ul._holds(lambda d: d >= M1C_LIBRARY_US, diff)
        checks.append(_cell(s, runs, tail_diff=diff, holds=holds))
    return _judged(checks)


def judge_causality(rows):
    """M2-a: in no run does the certain reading call a message unwaited that the broker's record
    shows waiting or close."""
    return _judged([_cell(s, runs, false_none=[_f(r, "cap_certain_false_none") for r in runs],
                          holds=_every(runs, lambda n: n == 0, "cap_certain_false_none"))
                    for s, runs in _setups(rows, lambda r: True)])


def judge_calibrated(rows):
    """M2-b: in every run where the estimate has a value, its share of messages that found none is
    within M2B_POINTS points of the broker's."""
    checks = []
    for s, runs in _setups(rows, lambda r: True):
        points = [None if None in (_f(r, "cap_calibrated_none_share"), _f(r, "broker_none_share"))
                  else 100.0 * (_f(r, "cap_calibrated_none_share") - _f(r, "broker_none_share"))
                  for r in runs]
        known = [ul._holds(lambda g: abs(g) <= M2B_POINTS, g) for g in points if g is not None]
        checks.append(_cell(s, runs, points=points, holds=all(known) if known else None))
    return _judged(checks)


def judge_manipulation(rows):
    """M2-c, the remedy's own check, on V and N at WAITING_DEPTH, nats.go and P at
    WAITING_PREFETCH: the broker's record shows a request or credit waiting for at least M2C_WAITING
    of messages, and the clients' own timestamps certify one waiting (certified, at B
    CERTIFY_B_MS) for at least M2C_CERTIFIED of them, a setup's value the median over its runs, the
    certified share over only the runs whose checks of B hold: a run whose checks fail, or cannot
    be read, leaves its client clause out of reach. Beside them: the same at the described B, what
    the probes were, and the estimate's share that found none where it has a value."""
    checks = []
    for s, runs in _setups(rows, _waiting):
        waiting = _median_of(runs, "broker_waiting_share")
        share, each = _certified(runs)
        held = ul._holds(lambda w: w >= M2C_WAITING, waiting)
        certain = ul._holds(lambda c: c >= M2C_CERTIFIED, share)
        checks.append(_cell(s, runs, waiting=waiting, certified=share,
                            runs_checked=[c for c, _ in each], runs_certified=[x for _, x in each],
                            certified_2ms=_certified(runs, "_2ms")[0],
                            probes=sorted(set(str(r.get("probe_kind")) for r in runs)),
                            estimate_none=_median_of(runs, "cap_calibrated_none_share"),
                            broker_held=held, client_held=certain, holds=_both(held, certain)))
    return _judged(checks)


def _still(runs, prefix="", judged=True):
    """W's tail held still and D's growing, over one setup's runs, read over the messages `prefix`
    names: the equivalence test, the plain ratio beside it, and D's ratio."""
    ratios = [_f(r, prefix + "W_ratio") for r in runs]
    still, p = holds_still(ratios) if judged else (None, None)
    w, d = _median(ratios), _median_of(runs, prefix + "D_ratio")
    grew = ul._holds(lambda x: x >= GROWTH, d) if judged else None
    return {"W_ratio": w, "W_ratio_within": ul._holds(lambda x: 1 / HOLDS_STILL <= x
                                                      <= HOLDS_STILL, w),
            "tost_p": p, "W_held_still": still, "D_ratio": d, "D_grew": grew,
            "holds": _both(still, grew) if judged else None}


def judge_ready(rows, manipulation):
    """M3-a: where M2-c holds, over the messages the broker's record shows found a request or
    credit waiting, W's tail is held still, while D's on/off ratio is at least GROWTH. The same over
    all messages is described. A cell where M2-c did not hold is not judged."""
    held = dict((c["setup"], c["holds"]) for c in manipulation["checks"])
    checks = []
    for s, runs in _setups(rows, _waiting):
        judged = held.get(s) is True
        cell = _cell(s, runs, judged=judged, **_still(runs, "waiting_", judged))
        cell["all_messages"] = _still(runs)
        checks.append(cell)
    return _judged(checks)


def _by_broker(verdict, backend):
    """A prediction's cells on one broker alone, judged again."""
    return _judged([c for c in verdict["checks"] if c["backend"] == backend])


def _removal(runs, judged, draws):
    """The share of W's tail rise that removing the turnaround takes out (E2), with its interval,
    where W rose; nothing where it did not."""
    if not judged:
        return {"share": None, "low": None, "high": None, "undefined_draws": None,
                "removed": None}
    share = onoff_share(runs)
    low, high, undefined = share_interval(runs, "E2", draws)
    return {"share": share, "low": low, "high": high, "undefined_draws": undefined,
            "share_certain": onoff_share(runs, "Fs"),
            "removed": ul._holds(lambda x: x >= HALF, share)}


def judge_gap(rows, draws=BOOTSTRAP):
    """M3-b: at GAPPED_DEPTH (V, N), at GAPPED_PREFETCH (P), and for each in-poll Kafka client at
    normal priority, W's tail on/off ratio is at least GROWTH; where it is, removing the client's
    part of the request gap (E2 = W - min(T_c, S)) takes out at least HALF of the rise, from tail
    means, a setup's value the mean over its runs, with a run-level interval."""
    checks = []
    for s, runs in _setups(rows, _gapped):
        w = _median_of(runs, "W_ratio")
        rose = ul._holds(lambda x: x >= GROWTH, w)
        removal = _removal(runs, rose is True, draws)
        checks.append(_cell(s, runs, W_ratio=w, rose=rose,
                            holds=rose if not rose else removal["removed"], **removal))
    return _judged(checks)


def judge_turnaround(rows):
    """KC-a: each in-poll Kafka client at normal priority: its turnaround's tail mean is at least
    GROWTH times higher in the on-blocks."""
    return _judged([_cell(s, runs, Tc_ratio=_median_of(runs, "Tc_ratio"),
                          holds=ul._holds(lambda x: x >= GROWTH, _median_of(runs, "Tc_ratio")))
                    for s, runs in _setups(rows, _in_poll)])


def judge_fetch_share(rows, draws=BOOTSTRAP):
    """KC-b: in each Kafka client at normal priority where W's tail on/off ratio is at least
    GROWTH, removing the turnaround takes out at least HALF of the rise, as M3-b reads it. A client
    whose W did not rise so is not judged."""
    checks = []
    for s, runs in _setups(rows, _kafka_normal):
        w = _median_of(runs, "W_ratio")
        judged = ul._holds(lambda x: x >= GROWTH, w) is True
        removal = _removal(runs, judged, draws)
        checks.append(_cell(s, runs, W_ratio=w, judged=judged, holds=removal["removed"],
                            **removal))
    return _judged(checks)


def judge_librdkafka(rows):
    """KC-c: librdkafka's rise of the turnaround's tail mean (on less off) is at most KC_C_FRACTION
    of each in-poll client's, at normal priority, each setup's rise the median over its runs."""
    rises = dict((runs[0].get("consumer"), (s, _median_of(runs, "Tc_rise")))
                 for s, runs in _setups(rows, _kafka_normal))
    ours = rises.get(LIBRDKAFKA, (None, None))
    checks = []
    for client in IN_POLL:
        theirs = rises.get(client, (None, None))
        checks.append({"setup": ours[0], "against": theirs[0], "backend": "kafka",
                       "consumer": client, "rise": ours[1], "rise_against": theirs[1],
                       "holds": ul._holds(lambda a, b: a <= KC_C_FRACTION * b, ours[1],
                                          theirs[1])})
    return _judged(checks)


def judge_fetch_thread(rows):
    """KC-d: with only librdkafka's broker thread at real-time priority, W's tail is held still as
    M3-a reads it, over all messages, while D's on/off ratio is at least GROWTH."""
    return _judged([_cell(s, runs, **_still(runs)) for s, runs in _setups(rows, _fetch_rt)])


def judge_round_trip(rows):
    """KC-h: with librdkafka's broker thread at real-time priority, its turnaround's tail on/off
    ratio is at most KC_H_RATIO, and in both load states at least KC_H_UNWAITED of the messages
    found no fetch waiting, by the broker's record (none or close; the none share beside). Described
    beside it: the share of time no fetch waited at the broker, and the model's share."""
    checks = []
    for s, runs in _setups(rows, _fetch_rt):
        tc = _median_of(runs, "Tc_ratio")
        on, off = (_median_of(runs, "broker_unwaited_share_" + state) for state in STATES)
        held = ul._holds(lambda x: x <= KC_H_RATIO, tc)
        left = ul._holds(lambda a, b: min(a, b) >= KC_H_UNWAITED, on, off)
        checks.append(_cell(s, runs, Tc_ratio=tc, turnaround_held=held,
                            unwaited_on=on, unwaited_off=off, none_share_on=_median_of(
                                runs, "broker_none_share_on"),
                            none_share_off=_median_of(runs, "broker_none_share_off"),
                            left_waiting=left, holds=_both(held, left),
                            described={"nofetch_time_share": _median_of(runs,
                                                                        "nofetch_time_share"),
                                       "broker_unwaited_share": _median_of(
                                           runs, "broker_unwaited_share"),
                                       "kch_predicted": _median_of(runs, "kch_predicted"),
                                       "g_us": _median_of(runs, "g_us"),
                                       "g_turnaround_us": _median_of(runs, "g_turnaround_us"),
                                       "g_rest_us": _median_of(runs, "g_rest_us")}))
    return _judged(checks)


def judge_whole_core(rows):
    """C-a: in block C, the residual (W's on-block tail mean less its off-block one, within runs)
    with the consumer alone on its core and the sibling idle is at most C_A_FRACTION of the baseline
    arm's; the sibling-loaded arm is described between them."""
    arms = {}
    for s, runs in _setups(rows, lambda r: r["block"] == "C"):
        first = runs[0]
        arm = ("loaded" if first.get("sibling_load") else "idle") if first.get("whole_core") \
            else "baseline"
        arms.setdefault(arm, (s, _median_of(runs, "W_rise")))
    base, idle, loaded = (arms.get(a, (None, None)) for a in ("baseline", "idle", "loaded"))
    return _judged([{"setup": idle[0], "against": base[0], "backend": "kafka",
                     "residual": idle[1], "residual_baseline": base[1],
                     "described": {"sibling_loaded": loaded[0], "residual": loaded[1]},
                     "holds": ul._holds(lambda a, b: a <= C_A_FRACTION * b, idle[1], base[1])}])


def described(rows):
    """Medians over each setup's runs of what the predictions do not judge, or judge elsewhere."""
    out = []
    for s, runs in _setups(rows, lambda r: True):
        entry = _cell(s, runs, producer_join=sorted(set(str(r.get("producer_join"))
                                                        for r in runs)))
        entry.update((field, _median_of(runs, field)) for field in DESCRIBED)
        out.append(entry)
    return out


def scope(rows):
    """Block S, described only: how M1-a, M2-a, M2-c and M3-a fare with the producer at normal
    priority, and under a load heavy in network softirq work, with the receive path's counters,
    setup by setup."""
    out = []
    for s, runs in _setups(rows, lambda r: True):
        share, each = _certified(runs)
        entry = _cell(s, runs, q_p99=[_f(r, "q_p99") for r in runs],
                      q_min=[_f(r, "q_min") for r in runs],
                      certain_false_none=[_f(r, "cap_certain_false_none") for r in runs],
                      waiting=_median_of(runs, "broker_waiting_share"), certified=share,
                      runs_checked=[c for c, _ in each],
                      estimate_none=_median_of(runs, "cap_calibrated_none_share"),
                      squeezed=[_f(r, "softnet_squeezed") for r in runs],
                      dropped=[_f(r, "softnet_dropped") for r in runs],
                      softirq_s=[_f(r, "softirq_s") for r in runs])
        entry["waiting_messages"] = _still(runs, "waiting_")
        entry["all_messages"] = _still(runs)
        out.append(entry)
    return out


def _all(verdicts):
    """One verdict over several: not confirmed where one is not, confirmed only where every one
    is, else out of reach."""
    said = [v["verdict"] for v in verdicts]
    if "not confirmed" in said:
        return "not confirmed"
    return "confirmed" if said and all(v == "confirmed" for v in said) else "out of reach"


def judge(rows, draws=BOOTSTRAP):
    """Every prediction over the run rows: the instrument's and the check's over every block but
    S; the others on the x86 pair's blocks V, N, P, K and C; the replication's, block A, on the Arm
    pair; block S described."""
    rows = [r for r in rows if not r.get("pilot")]
    checked = [r for r in rows if r["block"] in CHECKED_BLOCKS]
    main = [r for r in rows if r["block"] in JUDGED_BLOCKS and r.get("arch") != ARM]
    out = {"M1-a": judge_card(checked), "M1-b": judge_matching(checked),
           "M1-c": judge_reads(main), "M2-a": judge_causality(checked),
           "M2-b": judge_calibrated(checked), "M2-c": judge_manipulation(main)}
    out["M3-a"] = judge_ready(main, out["M2-c"])
    out["M3-b"] = judge_gap(main, draws)
    out["V-a"], out["N-a"], out["P-a"] = (_by_broker(out["M3-a"], b)
                                          for b in ("redis", "nats", "rabbitmq"))
    out.update({"KC-a": judge_turnaround(main), "KC-b": judge_fetch_share(main, draws),
                "KC-c": judge_librdkafka(main), "KC-d": judge_fetch_thread(main),
                "KC-h": judge_round_trip(main), "C-a": judge_whole_core(main)})
    # Block A repeats V's and K's setups on the Arm pair, and is judged as they are.
    arm = [dict(r, block="K" if r["backend"] == "kafka" else "V") for r in rows
           if r["block"] == REPLICATION_BLOCK]
    manipulation = _by_broker(judge_manipulation(arm), "redis")
    parts = {"V-a": _by_broker(judge_ready(arm, manipulation), "redis"), "M2-c": manipulation,
             "KC-d": judge_fetch_thread(arm)}
    out["A"] = {"verdict": _all(parts.values()), "parts": parts}
    out["S"] = {"described": scope([r for r in rows if r["block"] == SCOPE_BLOCK])}
    out["described"] = {"setups": described(rows)}
    return out


# --- files ---------------------------------------------------------------------------------------

#: The run table's columns that are whole numbers and those that are true or false.
INTS = ("rate", "depth", "depth_asked", "prefetch", "ack_batch", "load_pct")
FLAGS = ("pilot", "one_reply", "fetch_rt", "priority", "producer_priority", "whole_core",
         "sibling_load", "irqbalance_off", "rps_off", "blocks")


def read_table(path):
    """Rows of a run table this program wrote, with its typed columns put back."""
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for key in INTS:
            if key in r:
                r[key] = _int(r[key])
        for key in FLAGS:
            if key in r:
                r[key] = r[key] == "True"
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("calibrate", "read"):
        p = sub.add_parser(name)
        p.add_argument("--runs", action="append", required=True)
        for flag in ("--driver", "--broker", "--receiver"):
            p.add_argument(flag, required=True)
        p.add_argument("--warmup", type=float, default=WARMUP_S)
        p.add_argument("--out" if name == "calibrate" else "--out-runs", required=True)
    p.add_argument("--allowance", required=True)
    p.add_argument("--pilot", action="store_true")
    p = sub.add_parser("judge")
    p.add_argument("--runs-table", required=True)
    p.add_argument("--draws", type=int, default=BOOTSTRAP)
    p.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "calibrate":
        rows, _ = read_block(args.runs, args.driver, args.broker, args.receiver, None,
                             args.warmup, pilot=True)
        found = calibrate(rows)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(found, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("allowance per instrument and broker, us, from %d pilot runs: %s"
              % (len(rows), json.dumps(found, sort_keys=True)))
        return 0
    if args.cmd == "read":
        with open(args.allowance, encoding="utf-8") as fh:
            allowance = json.load(fh)
        rows, skipped = read_block(args.runs, args.driver, args.broker, args.receiver, allowance,
                                   args.warmup, args.pilot)
        osc.write_csv(args.out_runs, rows)
        for run, verdict in skipped:
            print("left out %s: %s" % (run, verdict))
        print("OK %d runs of plan version 47%s -> %s" % (len(rows), "'s pilot" if args.pilot
                                                          else "", args.out_runs))
        return 0
    verdicts = judge(read_table(args.runs_table), args.draws)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(verdicts, fh, indent=2, sort_keys=True)
        fh.write("\n")
    for name in sorted(k for k in verdicts if k not in ("described", "S")):
        print("%s: %s" % (name, verdicts[name]["verdict"]))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
