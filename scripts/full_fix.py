#!/usr/bin/env python3
"""
full_fix.py -- freeze 39's test of a full fix: both of a message's timestamps taken where it leaves
and enters the client machine, in the kernel, so that no program thread's wait for a core enters
the latency it reports.

Per message, on the driver's one clock:

  t_pub   the producer's clock at the publish call (producer.csv, t_prod_send_ns);
  t_tx    the kernel's capture time of the packet carrying the end of the message's event id in
          the reassembled driver-to-broker stream (sender_full.pcap, root namespace, eth0);
  t_rx    the same in the broker-to-receiver stream (receiver_full.pcap, the receiver's namespace,
          as R1 captured it);
  t_recv  the consumer's clock when it stamps the message (consumer_events.csv, t_consume_ns).

  D       = t_recv - t_pub     what a benchmark timed from the publish call reports;
  W       = t_rx - t_tx        the wire time, network and broker: the fix;
  H_send  = t_tx - t_pub       the host's wait before the bytes leave;
  H_recv  = t_recv - t_rx      the host's wait after they arrive; D = H_send + W + H_recv.

The receiving side's event ids are found exactly as recv_wait.py finds them, by its own
kernel_times(). The sending side's are found by departure_times() below, which times each id by
its own packet, since a message leaves when its packet does, whatever became of those before it.

A pause, which holds messages and releases them together, is marked as R1 marked it: each run
counts the messages whose D, and whose W, pass the quality report's limit, and the judge lists
those runs beside its verdicts.

CLI:
    python scripts/full_fix.py read --runs FOLDER [--runs ...] --driver IP --broker IP \
        --receiver IP --out CSV
    python scripts/full_fix.py judge --table CSV --out JSON
"""
import argparse
import bisect
import csv
import glob
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import quality_report  # noqa: E402
import recv_wait as rw  # noqa: E402

#: The block's setups, by the prefix of their ids in the queue.
SETUP = "F1-"

#: F-a and F-b: how far W's median and 99th percentile may move between the loads and between the
#: priorities, as a share of the value they are held against.
MEDIAN_SHARE = 0.10
TAIL_SHARE = 0.25
#: F-c: the share of a run's messages that may go unmatched in either capture.
UNMATCHED_SHARE = 0.005
#: F-d: how much larger D's 99th percentile must be at the load than idle, at normal priority, for
#: the effect the fix removes to be present; and the most of the rise in D's mean W may carry.
EFFECT_RATIO = 1.5
WIRE_SHARE_OF_RISE = 0.2
#: F-e: Kafka's send-side wait under the load, and the most Redis's may move, in microseconds.
KAFKA_SEND_RISE_US = 200.0
REDIS_SEND_MOVE_US = 100.0

#: Each span's statistics, in microseconds. The smallest shows that the times come in the order a
#: message meets them.
STATS = ("min", "median", "mean", "p99")
FIELDS = (("run", "setup", "backend", "load_pct", "priority", "load_measured", "dropped",
           "stamped", "messages", "unmatched_tx", "unmatched_rx", "wire_nonpositive", "D_max",
           "D_held", "W_held")
          + tuple("%s_%s" % (span, stat) for span in ("D", "W", "Hsend", "Hrecv") for stat in STATS)
          # Described, not judged: the card's own arrival time, where the run captured it, and how
          # tightly each sample of its clock was bracketed by the system's.
          + ("card_matched", "card_window_ns")
          + tuple("%s_%s" % (span, stat) for span in ("Wcard", "Kdelay") for stat in STATS))


#: How much of the segment before it a segment is searched with, so that an event id straddling
#: the two is found. An id is fifteen bytes.
JOINT = 64


def _offset(seq, base):
    """Where `seq` falls in its stream, from the connection's first captured sequence number, the
    32-bit wrap-around included, as recv_wait.Stream.offset reckons it."""
    rel = (seq - base) & 0xFFFFFFFF
    return rel - 0x100000000 if rel >= 0x80000000 else rel


def departure_times(path, src, dst):
    """{event id: ns at which the packet carrying the end of its id first left}, from src to dst.

    A message leaves the machine when its own packet does, whatever became of the packets before
    it, so this does not wait for the stream to be whole, as recv_wait.kernel_times rightly does
    on the receiving side, where a byte can be read only once every byte before it has arrived. A
    segment is searched together with the end of the segment just before it in the stream, so an
    id that straddles the two is found. A segment sent twice keeps the time it was first sent. An
    id carried twice in one record is timed by its later carrying, as kernel_times times it, and
    an id seen again further on than recv_wait.SAME_RECORD is another message's and is ignored."""
    conns = {}
    for ns, linktype, frame in rw.read_pcap(path):
        ip = rw.ip_payload(linktype, frame)
        seg = None if ip is None else rw.tcp_segment(ip)
        if seg is None or seg[0] != src or seg[1] != dst or not seg[5]:
            continue
        conns.setdefault(seg[2:4], []).append((ns, seg[4], seg[5]))
    found = {}
    for packets in conns.values():
        base = packets[0][1]
        first_sent = {}
        for ns, seq, payload in packets:
            first_sent.setdefault(_offset(seq, base), (ns, payload))
        ends = {start + len(payload): payload for start, (_, payload) in first_sent.items()}
        carried = {}
        for start in sorted(first_sent):
            ns, payload = first_sent[start]
            joint = ends.get(start, b"")[-JOINT:]
            for m in rw.EVENT_ID.finditer(joint + payload):
                if m.end() <= len(joint):
                    continue
                at = carried.setdefault(m.group(0).decode("ascii"), {})
                end = start - len(joint) + m.end()
                at[end] = min(at.get(end, ns), ns)
        for eid, at in carried.items():
            first = min(at)
            found[eid] = max(t for end, t in at.items() if end - first <= rw.SAME_RECORD)
    return found


def card_offsets(path):
    """[(system ns, card ns less system ns)] from phc_offset.py's samples, in time order; [] where
    the run took none."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return sorted((int(r["system_ns"]), int(r["card_minus_system_ns"]))
                      for r in csv.DictReader(fh))


def card_window(path):
    """The median width, in ns, of the two system readings that bracket each sample of the card's
    clock: how closely the card's time is put on the system's. None where the run took none."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", newline="") as fh:
        widths = [int(r["window_ns"]) for r in csv.DictReader(fh)]
    return statistics.median(widths) if widths else None


#: Each capture's own log, where tcpdump says at its end how many packets the kernel dropped.
CAPTURE_LOGS = ("sender_full.err", "receiver_full.err", "receiver_hw.err")
DROPPED = re.compile(r"^(\d+) packets dropped by kernel\s*$", re.M)


def capture_drops(run_dir):
    """How many packets the kernel dropped from the run's captures, by their own reports at their
    end; None where a capture that ran left no report, or none ran."""
    total, seen = 0, False
    for name in CAPTURE_LOGS:
        path = os.path.join(run_dir, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            said = DROPPED.findall(fh.read())
        if not said:
            return None
        total, seen = total + int(said[-1]), True
    return total if seen else None


def to_system(card_ns, offsets):
    """A time on the card's clock put on the system's: less the card's offset at that moment,
    interpolated between the samples either side of it (held at the end samples beyond them).
    The offset is looked up at the card time less a first offset, so the lookup is made at the
    system time it stands for; the offset moves by microseconds a second, so once is enough."""
    def offset_at(system_ns):
        at = [s for s, _ in offsets]
        i = bisect.bisect_left(at, system_ns)
        if i == 0:
            return offsets[0][1]
        if i == len(offsets):
            return offsets[-1][1]
        (s0, o0), (s1, o1) = offsets[i - 1], offsets[i]
        return o0 + (o1 - o0) * (system_ns - s0) / float(s1 - s0)
    first = offsets[len(offsets) // 2][1]
    #: In whole nanoseconds: the offset, milliseconds at most, is exact as a float, but a time since
    #: 1970 is not, a double's spacing there being 256 ns.
    return card_ns - int(round(offset_at(card_ns - first)))


def card_times(run_dir, broker, receiver):
    """{event id: the card's arrival time of the packet carrying the end of its id, on the system's
    clock}; {} where the run has no card capture or no clock samples."""
    pcap = os.path.join(run_dir, "receiver_hw.pcap")
    offsets = card_offsets(os.path.join(run_dir, "phc_offset.csv"))
    if not os.path.exists(pcap) or not offsets:
        return {}
    return {eid: to_system(ns, offsets) for eid, ns in rw.kernel_times(pcap, broker,
                                                                        receiver).items()}


def times(run_dir, driver, broker, receiver):
    """[(event id, t_pub, t_tx, t_rx, t_recv)] for the run's messages found in both captures, how
    many messages the consumer stamped, and how many of those each capture missed."""
    msgs = rw.messages(run_dir)
    sent = departure_times(os.path.join(run_dir, "sender_full.pcap"), driver, broker)
    got = rw.kernel_times(os.path.join(run_dir, "receiver_full.pcap"), broker, receiver)
    rows = [(eid, pub, sent[eid], got[eid], recv) for eid, pub, recv in msgs
            if eid in sent and eid in got]
    return rows, len(msgs), sum(1 for eid, _, _ in msgs if eid not in sent), sum(
        1 for eid, _, _ in msgs if eid not in got)


def read_run(run_dir, driver, broker, receiver):
    """One run's four spans, in microseconds."""
    row = rw.read_json(os.path.join(run_dir, "queue_row.json"))
    params = row.get("params") or {}
    found, stamped, missed_tx, missed_rx = times(run_dir, driver, broker, receiver)
    judged = rw.read_json(os.path.join(run_dir, "integrity.json"))
    out = {"run": os.path.basename(run_dir), "setup": row.get("setup"),
           "backend": params.get("backend"), "load_pct": params.get("load_pct"),
           "priority": bool(params.get("priority")),
           # The load the integrity rule measured, and what the captures dropped.
           "load_measured": ((judged.get("checks") or {}).get("load") or {}).get("value"),
           "dropped": capture_drops(run_dir), "stamped": stamped, "messages": len(found),
           "unmatched_tx": missed_tx, "unmatched_rx": missed_rx,
           "card_window_ns": card_window(os.path.join(run_dir, "phc_offset.csv"))}
    spans = {"D": [(recv - pub) / 1e3 for _, pub, _, _, recv in found],
             "W": [(rx - tx) / 1e3 for _, _, tx, rx, _ in found],
             "Hsend": [(tx - pub) / 1e3 for _, pub, tx, _, _ in found],
             "Hrecv": [(recv - rx) / 1e3 for _, _, _, rx, recv in found]}
    out["wire_nonpositive"] = sum(1 for w in spans["W"] if w <= 0)
    # A pause holds every message sent while it lasts and releases them together, so one pause can
    # carry a run's mean. It is marked as R1 marked it, by the quality report's limit, in D and in
    # W: a pause in the broker holds both, and one in the host holds D alone.
    limit = quality_report.STALL_MS * 1e3
    out["D_max"] = max(spans["D"]) if spans["D"] else None
    out["D_held"] = sum(1 for d in spans["D"] if d > limit)
    out["W_held"] = sum(1 for w in spans["W"] if w > limit)
    card = card_times(run_dir, broker, receiver)
    on_card = [(tx, rx, card[eid]) for eid, _, tx, rx, _ in found if eid in card]
    out["card_matched"] = len(on_card)
    spans["Wcard"] = [(c - tx) / 1e3 for tx, _, c in on_card]
    spans["Kdelay"] = [(rx - c) / 1e3 for _, rx, c in on_card]
    for name, values in spans.items():
        out[name + "_min"] = min(values) if values else None
        out[name + "_median"] = statistics.median(values) if values else None
        out[name + "_mean"] = statistics.fmean(values) if values else None
        out[name + "_p99"] = rw.percentile(values, 99) if values else None
    return out


#: The two loads and the two priorities the block compares.
IDLE, BUSY = 0, 88
BACKENDS = ("kafka", "redis")


def setup_value(rows, backend, load, priority, field):
    """A setup's value: the median over its runs of each run's statistic, or None with no run."""
    found = [float(r[field]) for r in rows
             if r["backend"] == backend and int(float(r["load_pct"])) == load
             and str(r["priority"]) == str(priority) and r.get(field) not in ("", None)]
    return statistics.median(found) if found else None


def _within(value, base, share):
    return None if value is None or base is None else abs(value - base) <= share * base


def _verdict(results):
    """holds where every comparison held, fails where any failed, else undecided."""
    if any(r is False for r in results):
        return "fails"
    return "holds" if results and all(r is True for r in results) else "undecided"


def held_still(rows, field, share):
    """F-a and F-b: the field's setup value held within `share` between the loads at each
    priority and between the priorities at each load, on both brokers."""
    results, shown = [], {}
    for b in BACKENDS:
        for p in (False, True):
            idle, busy = setup_value(rows, b, IDLE, p, field), setup_value(rows, b, BUSY, p, field)
            results.append(_within(busy, idle, share))
            shown["%s, %s priority: idle against load" % (b, "real-time" if p else "normal")] = (
                idle, busy)
        for load in (IDLE, BUSY):
            normal = setup_value(rows, b, load, False, field)
            fast = setup_value(rows, b, load, True, field)
            results.append(_within(fast, normal, share))
            shown["%s, %d%% load: normal against real-time" % (b, load)] = (normal, fast)
    return {"verdict": _verdict(results), "values": shown}


def nothing_lost(rows):
    """F-c: no wire time at or below zero, and under UNMATCHED_SHARE of each run's messages
    missing from either capture."""
    bad = [r["run"] for r in rows
           if int(r["wire_nonpositive"]) or not int(r["stamped"])
           or max(int(r["unmatched_tx"]), int(r["unmatched_rx"]))
           > UNMATCHED_SHARE * int(r["stamped"])]
    return {"verdict": "holds" if rows and not bad else ("fails" if bad else "undecided"),
            "runs_against": bad}


def the_hosts_effect(rows):
    """F-d: at normal priority, D's 99th percentile at the load at least EFFECT_RATIO times idle, and
    W's mean moving by less than WIRE_SHARE_OF_RISE of the rise in D's mean."""
    results, shown = [], {}
    for b in BACKENDS:
        tail = [setup_value(rows, b, load, False, "D_p99") for load in (IDLE, BUSY)]
        d = [setup_value(rows, b, load, False, "D_mean") for load in (IDLE, BUSY)]
        w = [setup_value(rows, b, load, False, "W_mean") for load in (IDLE, BUSY)]
        if None in tail + d + w:
            results.append(None)
            continue
        rise = d[1] - d[0]
        results.append(tail[1] >= EFFECT_RATIO * tail[0] and rise > 0
                       and abs(w[1] - w[0]) < WIRE_SHARE_OF_RISE * rise)
        shown[b] = {"D_p99": tail, "D_mean": d, "W_mean": w}
    return {"verdict": _verdict(results), "values": shown}


def the_send_side(rows):
    """F-e: Kafka's send-side wait rises under the load by at least KAFKA_SEND_RISE_US at normal
    priority, and Redis's moves by less than REDIS_SEND_MOVE_US."""
    k = [setup_value(rows, "kafka", load, False, "Hsend_mean") for load in (IDLE, BUSY)]
    r = [setup_value(rows, "redis", load, False, "Hsend_mean") for load in (IDLE, BUSY)]
    if None in k + r:
        return {"verdict": "undecided", "values": {"kafka": k, "redis": r}}
    held = k[1] - k[0] >= KAFKA_SEND_RISE_US and abs(r[1] - r[0]) < REDIS_SEND_MOVE_US
    return {"verdict": "holds" if held else "fails", "values": {"kafka": k, "redis": r}}


def judge(rows):
    return {"F-a": held_still(rows, "W_median", MEDIAN_SHARE),
            "F-b": held_still(rows, "W_p99", TAIL_SHARE),
            "F-c": nothing_lost(rows), "F-d": the_hosts_effect(rows), "F-e": the_send_side(rows)}


def pauses(rows):
    """The runs a pause held messages in, reported beside the verdicts as R1 reported them: [run,
    setup, messages held in D, messages held in W, D's largest in microseconds]."""
    return [[r["run"], r["setup"], int(float(r["D_held"])), int(float(r["W_held"])),
             float(r["D_max"])] for r in rows if int(float(r.get("D_held") or 0))]


def block_runs(folders, setup=SETUP):
    """(run folder, its integrity verdict) for every run of the block, by the setup its queue row
    names, as recv_wait.r1_runs finds R1's."""
    for folder in folders:
        for run_dir in sorted(glob.glob(os.path.join(folder, "law_*"))):
            named = rw.read_json(os.path.join(run_dir, "queue_row.json")).get("setup") or ""
            if named.startswith(setup):
                yield run_dir, rw.read_json(os.path.join(run_dir, "integrity.json")).get("verdict")


def read_block(folders, driver, broker, receiver, setup=SETUP):
    """(rows for the runs the integrity rule passed, [(run, verdict)] for the others)."""
    rows, skipped = [], []
    for run_dir, verdict in block_runs(folders, setup):
        if verdict != rw.PASSING:
            skipped.append((os.path.basename(run_dir), verdict or "not judged"))
            continue
        rows.append(read_run(run_dir, driver, broker, receiver))
    return rows, skipped


def write_csv(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Freeze 39's test of a full fix")
    sub = ap.add_subparsers(dest="cmd", required=True)
    read = sub.add_parser("read", help="each passing run's four spans, from its two captures")
    read.add_argument("--runs", action="append", required=True)
    for name in ("--driver", "--broker", "--receiver", "--out"):
        read.add_argument(name, required=True)
    judged = sub.add_parser("judge", help="F-a to F-e, from the table read writes")
    judged.add_argument("--table", required=True)
    judged.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "read":
        rows, skipped = read_block(args.runs, args.driver, args.broker, args.receiver)
        if not rows:
            print("no passing run of the block under %s" % ", ".join(args.runs))
            return 1
        write_csv(args.out, rows)
        print("%d runs read; left out: %s" % (len(rows), skipped or "none"))
        return 0
    with open(args.table, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    found, held = judge(rows), pauses(rows)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(dict(found, pauses=held), fh, indent=2, sort_keys=True)
        fh.write("\n")
    for name in sorted(found):
        print("%s  %s" % (name, found[name]["verdict"]))
    print("runs a pause held messages in: %d" % len(held))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
