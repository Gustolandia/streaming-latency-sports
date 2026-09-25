#!/usr/bin/env python3
"""
m0_read.py -- why the trip does not grow one-for-one with the added delay: M0, read as plan
version 31 fixes it, before any of M0's runs is read (D31-1).

The pilot found the departure only in bursts: two milliseconds of delay lengthened Redis's trip by
2.5-3.2 ms and Kafka's by 1.7-2.0, where steady traffic grew one-for-one (D6-7). M0 replays the
football match in bursts at 0, 2 and 8 ms, Redis both acknowledging each message and in batches
of 200, and in a random half of its runs records the packets at both ends, the receive loop's
cycle and every python3 thread's scheduling events. Four explanations, each kept or dropped by its
own test, and more than one may hold (M-H1 to M-H4).

The departure. At each backend -- and for Redis, at each acknowledgement batch -- the slope b of
the runs' median trip on the delay each run's broker actually held (delay_held_ms), over the
recorded runs, with a 95% interval from resampling whole rounds. The departure is D = (b - 1) x 8
ms, signed: positive where the trip grows more than one-for-one, as Redis's did. An explanation
"accounts for at least half" of it where its own contribution C, in milliseconds at 8 ms, has D's
sign and at least half its size. The departure is read on the recorded runs, the same runs the
explanations are read from; the unrecorded runs' departure is reported beside it, with the
recording's own effect at each setup.

  M-H1  the network: the delay reaching the receiver's card is the broker's held delay plus any
        change in the wire's own transit. The transit of a request and its reply, taken from the
        two captures as (request reaches broker - request leaves receiver) + (reply reaches
        receiver - reply leaves broker), holds no clock offset: the offset enters the two legs
        with opposite signs. Kept where the arrival shift at 8 ms differs from 8 ms by more than
        0.05 ms.
  M-H3  the wake-up: the receiving thread's median wait for a CPU after each wake from sleep, its
        change from 0 to 8 ms is C.
  M-H4  the TCP acknowledgement: a request held for one leaves the receiver within 50 us of an
        incoming acknowledgement of data the receiver had outstanding for over 100 us, after the
        program issued it; C is the change in the mean hold per message. Both clients set
        TCP_NODELAY (redis-py 7.4.1, kafka-python 2.3.2), so Nagle's algorithm cannot hold a
        request; only the send window can, and the test is run as written.
  M-H2  the receive loop: a replay of each recorded run's messages through the loop's own rules,
        fed with the constants measured from that run's capture and logs and never with its
        per-message outcomes; kept where the replayed slope is within 0.05 of the measured one.
        The loop's own costs are measured on the part's 0 ms runs; where those never carried two
        messages in one reply, the cost of the second is unknown and M-H2 is not tested there.

CLI:
    python scripts/m0_read.py --runs <M0 campaign folder> [--out answer.json]
"""
import argparse
import bisect
import csv
import json
import os
import random
import re
import statistics
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helper_waits  # noqa: E402 - the scheduling events and the clocks, read one way
import law_curve  # noqa: E402
import law_predictions  # noqa: E402
import pcap_read  # noqa: E402
import quality_report  # noqa: E402

#: Where the departure is read, and the tests' own thresholds (plan, M-H1 to M-H4).
AT_MS = 8.0
MH1_MS = 0.05
MH2_SLOPE = 0.05
HALF = 0.5
#: The recording's own effect the plan allows before the request-timing log goes off.
RECORDING_MS = 0.02
#: M-H4: how soon after an incoming acknowledgement a held request leaves, and how long the data
#: it acknowledges must have been outstanding.
HELD_WITHIN_US = 50
OUTSTANDING_US = 100
#: -i any can list one packet twice; a copy within this many microseconds is the same packet.
SAME_PACKET_US = 50
DRAWS = 2000
LEVEL = 0.95
PORTS = {"kafka": 9092, "redis": 6379}
#: Kafka's API key for Fetch, and the fetch settings the consumer runs with (kafka-python's
#: defaults, which scripts/kafka_consumer.py leaves as they are).
FETCH = 1
FETCH_MAX_WAIT_NS = 500 * 1000000
#: What the Redis consumer prints of its own settings at the start of every run.
REDIS_CONFIG = re.compile(r"CONFIG effective ack_batch=(\d+) count=(\d+) block_ms=(\d+)")


# --- the runs ------------------------------------------------------------------------------------

def m0_runs(folder):
    """M0's counted runs, as the judges read them, with what M0 needs beside: the delay the broker
    held, the median got-it delay, the acknowledgement batch, and whether the run recorded."""
    where = dict((os.path.basename(d), d) for d in quality_report.run_dirs_under(folder))
    found = []
    for run in law_curve.read_runs(folder):
        if not str(run.get("setup") or "").startswith("M0-"):
            continue
        run_dir = where[run["run"]]
        recorded = quality_report.read_json(os.path.join(run_dir, "integrity.json")).get(
            "recorded", {})
        row = quality_report.read_json(os.path.join(run_dir, "queue_row.json"))
        params = row["params"] if isinstance(row["params"], dict) else json.loads(row["params"])
        found.append(dict(run, run_dir=run_dir, held_ms=recorded.get("delay_held_ms"),
                          gotit_ms=recorded.get("gotit_median_ms"),
                          set_ms=params.get("delay_ms"), ack_batch=params.get("ack_batch"),
                          recorded=os.path.exists(os.path.join(run_dir, "receiver.pcap"))))
    return found


def part_of(run):
    """The part a run is read in: the backend, and for Redis the acknowledgement batch."""
    return run["backend"] if run["backend"] != "redis" else "redis ack %s" % run["ack_batch"]


def split(runs):
    parts = {}
    for run in runs:
        parts.setdefault(part_of(run), []).append(run)
    return parts


def _median(values):
    kept = [v for v in values if v is not None]
    return statistics.median(kept) if kept else None


def _mean(values):
    kept = [v for v in values if v is not None]
    return sum(kept) / float(len(kept)) if kept else None


# --- the departure and the recording's own effect -----------------------------------------------

def slope(runs):
    """The slope of the runs' median trip on the delay their broker held, or None."""
    line = law_predictions.straight_line([run["held_ms"] for run in runs],
                                         [run["trip_ms"] for run in runs])
    return None if line is None else line[0]


def departure(runs, draws=DRAWS, seed=0):
    """{slope, interval, departure_ms} over the runs, with an interval from whole rounds."""
    rng = random.Random(seed)
    value = slope(runs)
    drawn = [s for s in (slope(law_curve.resample(runs, rng)) for _ in range(draws))
             if s is not None]
    low, high = law_curve.interval(drawn, LEVEL)
    return {"slope": value, "interval": [low, high], "runs": len(runs),
            "departure_ms": None if value is None else (value - 1.0) * AT_MS}


def accounts_for(contribution, departure_ms):
    """Whether a contribution accounts for at least half of the departure: its sign and half its
    size. A departure of nothing leaves nothing to account for."""
    if contribution is None or not departure_ms:
        return False
    return contribution * departure_ms > 0 and abs(contribution) >= HALF * abs(departure_ms)


def recording_effect(runs):
    """At each setup, how far the recorded runs' median trip and median got-it delay sit from the
    unrecorded runs', and whether every setup stays within the plan's 0.02 ms."""
    setups = {}
    for run in runs:
        side = "recorded" if run["recorded"] else "unrecorded"
        setups.setdefault(run["setup"], {"recorded": [], "unrecorded": []})[side].append(run)
    found, within = {}, True
    for setup, sides in sorted(setups.items()):
        entry = {}
        for key in ("trip_ms", "gotit_ms"):
            a = _median([run[key] for run in sides["recorded"]])
            b = _median([run[key] for run in sides["unrecorded"]])
            entry[key] = None if a is None or b is None else a - b
            within = within and entry[key] is not None and abs(entry[key]) < RECORDING_MS
        found[setup] = entry
    return {"by_setup": found, "log_stays_on": within and bool(found)}


# --- M-H3: the receiving thread's wake-ups ------------------------------------------------------

def wake_waits(line, start, end):
    """The thread's waits for a CPU that began with a wake from sleep between `start` and `end`."""
    return [line.times[i + 1] - line.times[i] for i in range(1, len(line.times) - 1)
            if line.states[i] == "waiting" and line.states[i - 1] == "asleep"
            and start <= line.times[i] <= end]


def receiving_wake_ms(run):
    """The median wake-up wait, in ms, of the thread that stamps arrivals, over the run's
    measured window; or None where the run has no event recording or thread record."""
    path = os.path.join(run["run_dir"], "waits.txt")
    records = helper_waits.thread_records(run["run_dir"]) if os.path.exists(path) else {}
    if "consumer" not in records or "producer" not in records:
        return None
    tids = sorted(records["consumer"]["roles"]["stamps_receive"])
    evts, lost = helper_waits.events(path, tids)
    sent = helper_waits.messages(run["run_dir"])
    if lost or not sent:
        return None
    producer = helper_waits.to_monotonic(records["producer"])
    start, end = producer(min(s for s, _, _ in sent)), producer(max(s for s, _, _ in sent))
    waits = [w for tid in tids for w in wake_waits(helper_waits.Timeline(evts[tid]), start, end)]
    return statistics.median(waits) / 1e6 if waits else None


def at_delay(runs, set_ms):
    return [run for run in runs if run.get("set_ms") is not None
            and abs(run["set_ms"] - set_ms) < 1e-6]


def contribution(runs, per_run):
    """C: the mean of a per-run quantity over the 8 ms runs less its mean over the 0 ms runs."""
    high = _mean([per_run(run) for run in at_delay(runs, AT_MS)])
    low = _mean([per_run(run) for run in at_delay(runs, 0.0)])
    return None if high is None or low is None else high - low


# --- the captures --------------------------------------------------------------------------------

def _deduplicated(segments):
    """The segments with a copy -i any listed twice taken out."""
    kept, last = [], {}
    for seg in segments:
        key = (seg["src"], seg["sport"], seg["dst"], seg["dport"], seg["seq"], seg["ack"],
               seg["length"], seg["flags"])
        if key in last and seg["ns"] - last[key] <= SAME_PACKET_US * 1000:
            continue
        last[key] = seg["ns"]
        kept.append(seg)
    return kept


def data_flow(segments, port):
    """(receiver end, broker end) of the connection that carried the most bytes to the receiver
    from the backend's port, or None."""
    carried = {}
    for seg in segments:
        if seg["sport"] == port and seg["length"]:
            key = ((seg["dst"], seg["dport"]), (seg["src"], seg["sport"]))
            carried[key] = carried.get(key, 0) + seg["length"]
    return max(carried, key=lambda key: (carried[key], key)) if carried else None


def exchanges(receiver, broker, port):
    """[(t1, t2, t3, t4)] for each request of the receiver's data connection and the reply that
    followed it, from the two captures: t1 the request leaves the receiver, t2 it reaches the
    broker, t3 the reply leaves the broker, t4 the reply reaches the receiver."""
    receiver, broker = _deduplicated(receiver), _deduplicated(broker)
    flow = data_flow(receiver, port)
    if flow is None:
        return []
    near, far = flow

    def keyed(segments, source):
        return dict(((seg["seq"], seg["length"]), seg["ns"]) for seg in segments
                    if (seg["src"], seg["sport"]) == source and seg["length"])
    up_at_receiver, up_at_broker = keyed(receiver, near), keyed(broker, near)
    down_at_receiver, down_at_broker = keyed(receiver, far), keyed(broker, far)
    replies = sorted((ns, key) for key, ns in down_at_broker.items() if key in down_at_receiver)
    found = []
    for key, t1 in sorted(up_at_receiver.items(), key=lambda pair: pair[1]):
        t2 = up_at_broker.get(key)
        if t2 is None:
            continue
        after = [(ns, reply) for ns, reply in replies if ns >= t2]
        if after:
            t3, reply = after[0]
            found.append((t1, t2, t3, down_at_receiver[reply]))
    return found


def capture_of(run, name):
    path = os.path.join(run["run_dir"], name)
    return pcap_read.segments(path) if os.path.exists(path) else None


def transit_ms(run):
    """The run's median wire transit of a request and its reply, in ms, with no clock offset."""
    receiver, broker = capture_of(run, "receiver.pcap"), capture_of(run, "broker.pcap")
    if not receiver or not broker:
        return None
    pairs = exchanges(receiver, broker, PORTS[run["backend"]])
    return _median([((t2 - t1) + (t4 - t3)) / 1e6 for t1, t2, t3, t4 in pairs])


def arrival_shift(runs, set_ms, transits):
    """M-H1's arrival shift at `set_ms`: the median delay the broker held there, plus the change
    in the median wire transit from the 0 ms runs to these."""
    here = at_delay(runs, set_ms)
    held = _median([run["held_ms"] for run in here])
    now = _median([transits.get(run["run"]) for run in here])
    before = _median([transits.get(run["run"]) for run in at_delay(runs, 0.0)])
    return None if held is None or now is None or before is None else held + (now - before)


# --- M-H4: requests held for an acknowledgement --------------------------------------------------

def kafka_fetches(segments, flow):
    """[(request_leaves_ns, response_arrives_ns)] for each Fetch on the data connection, the
    response counted as arrived when its last byte did. Kafka frames every request and response
    with a 4-byte length; a request carries its API key (Fetch is 1) and a correlation id, and a
    response the same id, so each response is tied to its request by the id."""
    near, far = flow
    asked, found, inbound = {}, [], None
    for seg in _deduplicated(segments):
        body = seg["payload"]
        if (seg["src"], seg["sport"]) == near and seg["length"] >= 12 and len(body) >= 12:
            if struct.unpack("!h", body[4:6])[0] == FETCH:
                asked[struct.unpack("!i", body[8:12])[0]] = seg["ns"]
        elif (seg["src"], seg["sport"]) == far and seg["length"]:
            if inbound is None:
                if len(body) < 8:
                    continue
                size, corr = struct.unpack("!ii", body[:8])
                inbound = [corr, size + 4]
            inbound[1] -= seg["length"]
            if inbound[1] <= 0:
                if inbound[0] in asked:
                    found.append((asked.pop(inbound[0]), seg["ns"]))
                inbound = None
    return found


def covered(end, ack):
    """Whether an acknowledgement number covers a sequence number, in TCP's 32-bit circle."""
    return (ack - end) % (1 << 32) < (1 << 31)


def held_requests(segments, flow, issued):
    """[(leave_ns, hold_ns)] for each request that left right after an acknowledgement of data the
    receiver had outstanding, after the program issued it. `issued(segment)` gives the time the
    program issued the request that segment carries, or None where it cannot say."""
    near, far = flow
    found, unacked, acked = [], [], None
    for seg in _deduplicated(segments):
        if (seg["src"], seg["sport"]) == near and seg["length"]:
            if acked is not None and seg["ns"] - acked <= HELD_WITHIN_US * 1000:
                when = issued(seg)
                if when is not None and when < acked:
                    found.append((seg["ns"], seg["ns"] - when))
            unacked.append(((seg["seq"] + seg["length"]) % (1 << 32), seg["ns"]))
        elif (seg["src"], seg["sport"]) == far and seg["flags"] & pcap_read.ACK:
            cleared = [sent for end, sent in unacked if covered(end, seg["ack"])]
            unacked = [(end, sent) for end, sent in unacked if not covered(end, seg["ack"])]
            acked = seg["ns"] if any(seg["ns"] - sent > OUTSTANDING_US * 1000
                                     for sent in cleared) else None
    return found


def held_per_message_ms(run):
    """(the run's total hold on requests held for an acknowledgement, per measured message, in
    ms; how many requests were held), or (None, 0) where the run cannot be read for it. The Redis
    program logs when it issues each read (its read trace) and each acknowledgement (right after
    the stamp it follows); the Kafka library's fetches are issued out of the program's sight, so no
    Kafka request can be shown to have been held."""
    receiver = capture_of(run, "receiver.pcap")
    if not receiver or run["backend"] != "redis":
        return None, 0
    flow = data_flow(receiver, PORTS["redis"])
    sent = helper_waits.messages(run["run_dir"])
    if flow is None or not sent:
        return None, 0
    reads = sorted(start for start, _, _ in read_cycle(run["run_dir"]))
    stamps = sorted(stamps_in_order(run["run_dir"]))

    def issued(seg):
        body = seg["payload"].upper()
        times = reads if b"XREADGROUP" in body else (stamps if b"XACK" in body else [])
        i = bisect.bisect_right(times, seg["ns"])
        return times[i - 1] if i else None
    holds = held_requests(receiver, flow, issued)
    return sum(hold for _, hold in holds) / 1e6 / len(sent), len(holds)


# --- M-H2: the receive loop, replayed -----------------------------------------------------------

def read_cycle(run_dir):
    """[(start_ns, duration_ns, messages)] for each read (Redis) or poll (Kafka) the receiving
    program logged, in order."""
    path = os.path.join(run_dir, "consumer_readtrace.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [(int(r["t_read_start_ns"]), int(r["read_duration_ns"]), int(r["n_messages"]))
                for r in csv.DictReader(fh)]


def stamps_in_order(run_dir):
    """The receiving program's arrival stamps, in the order it wrote them."""
    with open(os.path.join(run_dir, "consumer_events.csv"), newline="", encoding="utf-8") as fh:
        return [int(r["t_consume_ns"]) for r in csv.DictReader(fh) if r.get("t_consume_ns")]


def loop_costs(run_dir):
    """(the median gap between two stamps of one reply, the median gap from a reply's last stamp
    to the next read), in ns, from the program's own logs; None for either it cannot give, and
    both None where the log's message count is not the stamps' count."""
    cycle, stamps = read_cycle(run_dir), stamps_in_order(run_dir)
    if not cycle or sum(n for _, _, n in cycle) != len(stamps):
        return None, None
    within, onward, i = [], [], 0
    for k, (_, _, n) in enumerate(cycle):
        mine, i = stamps[i:i + n], i + n
        within += [b - a for a, b in zip(mine, mine[1:])]
        if mine and k + 1 < len(cycle):
            onward.append(cycle[k + 1][0] - mine[-1])
    return _median(within), _median(onward)


def sends(run_dir):
    """Every send time the producer wrote, in ns, in order."""
    with open(os.path.join(run_dir, "producer.csv"), newline="", encoding="utf-8") as fh:
        return sorted(int(r["t_prod_send_ns"]) for r in csv.DictReader(fh)
                      if r.get("t_prod_send_ns"))


def replay(arrivals, start, up, down, held, within, onward, count=None, wait_ns=None,
           next_after_last_stamp=True):
    """Each message's replayed stamp, in the order of `arrivals` (its time at the broker), through
    one receive loop: a request leaves at `start` and reaches the broker `up` later; the broker
    answers at once with what it holds (up to `count`), or with the first message to come within
    `wait_ns`, or with nothing when that runs out; the answer lands `down` plus the held delay
    later; its messages are stamped `within` apart; and the next request leaves `onward` after
    the last stamp (Redis) or after the answer lands (Kafka)."""
    order = sorted(range(len(arrivals)), key=lambda j: arrivals[j])
    stamped, t, i = [None] * len(arrivals), start, 0
    while i < len(order):
        at_broker = t + up
        first = arrivals[order[i]]
        if wait_ns is not None and first > at_broker + wait_ns:
            t = at_broker + wait_ns + down + held + onward
            continue
        leave = max(at_broker, first)
        batch = []
        while i < len(order) and arrivals[order[i]] <= leave and (count is None
                                                                  or len(batch) < count):
            batch.append(order[i])
            i += 1
        land = leave + down + held
        for j, m in enumerate(batch):
            stamped[m] = land + j * within
        t = (stamped[batch[-1]] if next_after_last_stamp else land) + onward
    return stamped


def zero_costs(runs):
    """The loop's own costs at no added delay, the medians over the part's recorded 0 ms runs:
    {within, onward}; for Kafka `onward` is the gap from a fetch's answer landing to the next
    fetch leaving, read off the capture."""
    within, onward = [], []
    for run in at_delay(runs, 0.0):
        a, b = loop_costs(run["run_dir"])
        within.append(a)
        if run["backend"] == "kafka":
            receiver = capture_of(run, "receiver.pcap")
            flow = data_flow(receiver, PORTS["kafka"]) if receiver else None
            cycle = kafka_fetches(receiver, flow) if flow else []
            b = _median([nxt[0] - prev[1] for prev, nxt in zip(cycle, cycle[1:])])
        onward.append(b)
    return {"within": _median(within), "onward": _median(onward)}


def redis_config(run_dir):
    """(ack_batch, count, block_ms) as the Redis consumer printed them for the run."""
    with open(os.path.join(run_dir, "consumer.log"), encoding="utf-8", errors="replace") as fh:
        m = REDIS_CONFIG.search(fh.read())
    if not m:
        raise ValueError("%s: the consumer did not print its settings" % run_dir)
    return tuple(int(x) for x in m.groups())


def replayed_trip_ms(run, costs, warmup_s=helper_waits.WARMUP_S):
    """The run's median replayed trip over its measured messages, in ms, or None."""
    sent = sends(run["run_dir"])
    cycle = read_cycle(run["run_dir"])
    transit = transit_ms(run)
    if (not sent or not cycle or transit is None or run.get("gotit_ms") is None
            or run.get("held_ms") is None or None in costs.values()):
        return None
    held = run["held_ms"] * 1e6
    half = transit * 1e6 / 2.0
    arrivals = [s + run["gotit_ms"] * 1e6 / 2.0 for s in sent]
    if run["backend"] == "redis":
        batch, count, block_ms = redis_config(run["run_dir"])
        each = held if batch == 1 else 0.0
        stamped = replay(arrivals, cycle[0][0], half, half, held, costs["within"] + each,
                         costs["onward"] + each, count=count,
                         wait_ns=block_ms * 1e6 if block_ms else None)
    else:
        stamped = replay(arrivals, cycle[0][0], half, half, held, costs["within"],
                         costs["onward"], wait_ns=FETCH_MAX_WAIT_NS, next_after_last_stamp=False)
    cutoff = sent[0] + warmup_s * 1e9
    return _median([(done - s) / 1e6 for s, done in zip(sent, stamped) if s >= cutoff])


# --- the answer ----------------------------------------------------------------------------------

def judge(runs, draws=DRAWS, seed=0):
    """M0's answer at each backend (and Redis acknowledgement batch)."""
    parts = {}
    for name, some in sorted(split(runs).items()):
        recorded = [run for run in some if run["recorded"]]
        found = departure(recorded, draws, seed)
        moved = found["departure_ms"]
        transits = dict((run["run"], transit_ms(run)) for run in recorded)
        shift = dict(("%g" % d, arrival_shift(recorded, d, transits)) for d in (2.0, AT_MS))
        wake = contribution(recorded, receiving_wake_ms)
        holds = dict((run["run"], held_per_message_ms(run)) for run in recorded)
        hold = contribution(recorded, lambda run: holds[run["run"]][0])
        held_count = sum(n for _, n in holds.values())
        costs = zero_costs(recorded)
        replayed = [dict(run, trip_ms=replayed_trip_ms(run, costs)) for run in recorded]
        again = slope([run for run in replayed if run["trip_ms"] is not None])
        at = "%g" % AT_MS
        parts[name] = {
            "departure": found,
            "unrecorded_departure": departure([run for run in some if not run["recorded"]],
                                              draws, seed),
            "recording_effect": recording_effect(some),
            "M-H1": {"kept": shift[at] is not None and abs(shift[at] - AT_MS) > MH1_MS,
                     "arrival_shift_ms": shift},
            "M-H2": {"kept": again is not None and found["slope"] is not None
                     and abs(again - found["slope"]) <= MH2_SLOPE, "replayed_slope": again,
                     "tested": None not in costs.values(), "loop_costs_ns": costs},
            "M-H3": {"kept": accounts_for(wake, moved), "contribution_ms": wake},
            "M-H4": {"kept": held_count > 0 and accounts_for(hold, moved),
                     "tested": name != "kafka", "held_requests": held_count,
                     "contribution_ms": hold}}
    return {"parts": parts, "at_ms": AT_MS}


def _round(value):
    return None if value is None else round(value, 4)


def lines(found):
    """The answer as a person reads it."""
    out = ["M0: why the trip does not grow one-for-one"]
    for name, part in sorted(found["parts"].items()):
        dep = part["departure"]
        out.append("  %s: slope %s (95%% %s to %s), departure %s ms at %g ms" % (
            name, _round(dep["slope"]), _round(dep["interval"][0]), _round(dep["interval"][1]),
            _round(dep["departure_ms"]), found["at_ms"]))
        for test in ("M-H1", "M-H2", "M-H3", "M-H4"):
            said = part[test]
            word = "kept" if said["kept"] else (
                "not tested" if said.get("tested") is False else "dropped")
            rest = dict((k, v) for k, v in sorted(said.items()) if k not in ("kept", "tested"))
            out.append("    %s: %s  %s" % (test, word, rest))
        out.append("    the request-timing log %s" % (
            "stays on" if part["recording_effect"]["log_stays_on"] else "goes off"))
    return out


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="M0: why the trip does not grow one-for-one")
    ap.add_argument("--runs", required=True, help="M0's campaign folder of copied runs")
    ap.add_argument("--draws", type=int, default=DRAWS)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    try:
        runs = m0_runs(args.runs)
        if not runs:
            raise ValueError("no counted M0 run under %s" % args.runs)
        found = judge(runs, args.draws, args.seed)
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(found, indent=2, sort_keys=True, default=str) + "\n")
        for line in lines(found):
            print(line, file=out)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
