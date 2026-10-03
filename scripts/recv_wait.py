#!/usr/bin/env python3
"""
recv_wait.py -- how much the receiving thread's own wait for a CPU lengthens a latency timed
from the send, D = t_recv - t_send. R1, exploratory, planned before its runs on 3 Oct 2026
(docs/results/recv_wait/r1_plan.md).

Why. Timing from the send cancels the acknowledging thread's wait: it lengthens the
acknowledgment lag A and shortens the transport proxy S by the same amount, and D = S + A
message by message. It does not cancel the receiving thread's wait. The consumer reads the clock
only after its thread has been woken and given a CPU, so every D carries that wait, always
positive, where no sign check can see it.

Three measurements, made in the same runs:

  1. go-first priority for the consumer alone (the queue's consumer_priority): what it removes
     from D at unchanged load;
  2. the receiving thread's own wait before it stamps a message, from waits.txt in the traced
     half: the time it spent waiting for a CPU from the later of its last wake from sleep and
     its previous stamp up to this stamp, which is helper_waits' own wait (A9-2b) pointed at the
     thread the consumer names for stamps_receive;
  3. the kernel's receive time: t_recv less the arrival, in receiver_full.pcap, of the packet
     that carries the end of the message's event id in the reassembled broker-to-receiver byte
     stream. That delay holds the wake-up, the wait for a CPU and the client's own work.

And what the earlier campaigns already said, recomputed from their runs: method 2 on the law
campaign's traced runs (A9), and D with and without go-first for both processes that read the
clock (A7). Only runs the integrity rule passed are read, and only messages sent after the
warm-up, as everywhere. Beside each comparison stand the runs that hold a message past the
quality report's pause limit: a pause releases every message it held at once, and one pause can
carry a run's mean. Each pause is then read with the 28 September census's own functions, for
what else stopped with it.

CLI:
    python scripts/recv_wait.py read --runs FOLDER [--runs ...] --broker IP --receiver IP --out CSV
    python scripts/recv_wait.py compare --table CSV [--out TXT]
    python scripts/recv_wait.py pauses --runs FOLDER [--runs ...] --out CSV
    python scripts/recv_wait.py traced --runs CAMPAIGN [--runs ...] --out CSV
    python scripts/recv_wait.py priority --runs CAMPAIGN [--runs ...] --out CSV
"""
import argparse
import bisect
import csv
import glob
import json
import os
import re
import socket
import statistics
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helper_waits as hw  # noqa: E402
import pause_census as pc  # noqa: E402
import quality_report  # noqa: E402

#: The warm-up every reading leaves out.
WARMUP_S = 30.0
#: The synthetic plan's event ids, as the payload carries them.
EVENT_ID = re.compile(rb"constant-\d{6}")
#: Bytes after an id's first sight that still belong to its record (Kafka repeats the id as the
#: record's key and inside its value).
SAME_RECORD = 2048
#: The verdict of a run the integrity rule passed.
PASSING = "count"
#: R1's runs, by the setup their queue row names. Not by folder: campaign.sh names a run's folder
#: after its queue, and amendment R1-1's runs came from a second queue, r1_more.
R1_SETUP = "R1-"
#: The plan's rules (r1_plan.md), in microseconds.
R1A_MEAN_US = (300.0, 1200.0)
R1A_P90_US = 1500.0
R1A_PRIORITY_MEAN_US = 100.0
R1B_P90_FALL_US = 1000.0
R1B_MEDIAN_MOVE_US = 300.0
R1C_SHARE = 0.95
R1C_DIFFERENCE_US = 300.0
R1D_FACTOR = 1.5
#: The statistics kept for every quantity.
STATS = ("n", "median", "mean", "p90", "p99")

# --- the capture ----------------------------------------------------------------------------------

#: A classic pcap file's magic number: byte order, and how many ns one fraction unit is.
MAGIC = {b"\xd4\xc3\xb2\xa1": ("<", 1000), b"\xa1\xb2\xc3\xd4": (">", 1000),
         b"\x4d\x3c\xb2\xa1": ("<", 1), b"\xa1\xb2\x3c\x4d": (">", 1)}
#: Link layers tcpdump writes: where the protocol number is, and where the IP packet starts.
LINK = {113: (14, 16), 276: (0, 20), 1: (12, 14)}
#: Link layers with no header before the IP packet.
RAW = (12, 101, 228)


def read_pcap(path):
    """[(ns, link layer, frame)] from a classic pcap file, micro- or nanosecond; a record that the
    end of the file cuts short is left out."""
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 24:
        return []
    if data[:4] not in MAGIC:
        raise ValueError("%s is not a classic pcap file" % path)
    endian, scale = MAGIC[data[:4]]
    linktype = struct.unpack(endian + "I", data[20:24])[0]
    out, i = [], 24
    while i + 16 <= len(data):
        sec, frac, incl, _orig = struct.unpack(endian + "IIII", data[i:i + 16])
        i += 16
        if i + incl > len(data):
            break
        out.append((sec * 1000000000 + frac * scale, linktype, data[i:i + incl]))
        i += incl
    return out


def ip_payload(linktype, frame):
    """The IPv4 packet inside one captured frame, or None."""
    if linktype in RAW:
        return frame
    if linktype not in LINK:
        return None
    at, start = LINK[linktype]
    if len(frame) < start:
        return None
    return frame[start:] if struct.unpack(">H", frame[at:at + 2])[0] == 0x0800 else None


def tcp_segment(ip):
    """(source, destination, source port, destination port, sequence, payload), or None."""
    if len(ip) < 20 or ip[0] >> 4 != 4 or ip[9] != 6:
        return None
    total = struct.unpack(">H", ip[2:4])[0] or len(ip)
    tcp = ip[(ip[0] & 0x0F) * 4:total]
    if len(tcp) < 20:
        return None
    sport, dport, seq = struct.unpack(">HHI", tcp[:8])
    return (socket.inet_ntoa(ip[12:16]), socket.inet_ntoa(ip[16:20]), sport, dport, seq,
            bytes(tcp[(tcp[12] >> 4) * 4:]))


class Stream:
    """One direction of one TCP connection, reassembled in order, with the moment each byte could
    first be read: a byte is readable once it and every byte before it have arrived."""

    def __init__(self):
        self.base, self.data, self.ends, self.times, self.pending = None, bytearray(), [], [], {}

    def offset(self, seq):
        """Where `seq` falls in the stream, sequence wrap-around included."""
        rel = (seq - self.base) & 0xFFFFFFFF
        return rel - 0x100000000 if rel >= 0x80000000 else rel

    def add(self, ns, seq, payload):
        if not payload:
            return
        if self.base is None:
            self.base = seq
        start = self.offset(seq)
        if start > len(self.data):
            self.pending.setdefault(start, (ns, payload))
            return
        if start + len(payload) <= len(self.data):
            return
        self._append(ns, payload[len(self.data) - start:])
        for held in sorted(self.pending):
            if held > len(self.data):
                break
            then, chunk = self.pending.pop(held)
            if held + len(chunk) > len(self.data):
                self._append(max(then, ns), chunk[len(self.data) - held:])

    def _append(self, ns, chunk):
        self.data += chunk
        self.ends.append(len(self.data))
        self.times.append(ns)

    def readable(self, offset):
        """When the byte at `offset` could first be read; None beyond what arrived."""
        i = bisect.bisect_right(self.ends, offset)
        return self.times[i] if i < len(self.times) else None


def kernel_times(path, broker, receiver):
    """{event id: ns at which its record's id could first be read}, broker to receiver only."""
    streams = {}
    for ns, linktype, frame in read_pcap(path):
        ip = ip_payload(linktype, frame)
        seg = None if ip is None else tcp_segment(ip)
        if seg is None or seg[0] != broker or seg[1] != receiver:
            continue
        streams.setdefault(seg[2:4], Stream()).add(ns, seg[4], seg[5])
    found = {}
    for stream in streams.values():
        first = {}
        for m in EVENT_ID.finditer(bytes(stream.data)):
            eid = m.group(0).decode("ascii")
            if m.start() - first.setdefault(eid, m.start()) > SAME_RECORD:
                continue
            when = stream.readable(m.end() - 1)
            found[eid] = max(found.get(eid, when), when)
    return found


# --- one run --------------------------------------------------------------------------------------

def read_json(path):
    """The JSON object at `path`, or {} where there is none."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def messages(run_dir, warmup_s=WARMUP_S):
    """[(event id, send ns, receipt ns)] for the messages sent after the warm-up that arrived."""
    sent = {}
    with open(os.path.join(run_dir, "producer.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("t_prod_send_ns"):
                sent[r["event_id"]] = int(r["t_prod_send_ns"])
    if not sent:
        return []
    cutoff = min(sent.values()) + int(warmup_s * 1e9)
    found = []
    with open(os.path.join(run_dir, "consumer_events.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            send = sent.get(r["event_id"])
            if send is None or send < cutoff or not r.get("t_consume_ns"):
                continue
            found.append((r["event_id"], send, int(r["t_consume_ns"])))
    return found


def receive_waits(run_dir, msgs):
    """({event id: the receiving thread's own wait in ns, or None}, None), or (None, why)."""
    path = os.path.join(run_dir, "waits.txt")
    if not os.path.exists(path):
        return None, hw.NOT_RECORDED
    records = hw.thread_records(run_dir)
    if "consumer" not in records:
        return None, "no thread record from the consumer"
    stampers = sorted(records["consumer"]["roles"]["stamps_receive"])
    evts, lost = hw.events(path, stampers)
    err = os.path.join(run_dir, "waits.err")
    if os.path.exists(err):
        with open(err, encoding="utf-8", errors="replace") as fh:
            lost = lost or bool(hw.LOST.search(fh.read()))
    if lost:
        return None, "the recording lost events"
    lines = dict((tid, hw.Timeline(found)) for tid, found in evts.items())
    clock = hw.to_monotonic(records["consumer"])
    waits, previous = {}, {}
    for eid, _send, receipt in sorted(msgs, key=lambda m: m[2]):
        stamp = clock(receipt)
        on = [tid for tid in stampers if lines[tid].at(stamp) == "running"]
        if len(on) != 1:
            continue
        waits[eid] = lines[on[0]].own_wait(stamp, previous.get(on[0]))
        previous[on[0]] = stamp
    if len(waits) < hw.IDENTIFIED_AT_LEAST * len(msgs):
        return None, ("the receiving thread was identified for %d of %d messages"
                      % (len(waits), len(msgs)))
    return waits, None


def percentile(values, q):
    """The q-th percentile, linearly interpolated between the two nearest ranks."""
    ordered = sorted(values)
    k = (len(ordered) - 1) * q / 100.0
    low = int(k)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (k - low)


def summarize(prefix, values):
    """{prefix_n, prefix_median, prefix_mean, prefix_p90, prefix_p99}; all None but n if empty."""
    if not values:
        return dict(("%s_%s" % (prefix, s), 0 if s == "n" else None) for s in STATS)
    return {"%s_n" % prefix: len(values), "%s_median" % prefix: statistics.median(values),
            "%s_mean" % prefix: statistics.fmean(values),
            "%s_p90" % prefix: percentile(values, 90), "%s_p99" % prefix: percentile(values, 99)}


def read_run(run_dir, broker, receiver, warmup_s=WARMUP_S):
    """One R1 run's three measurements, in microseconds."""
    row = read_json(os.path.join(run_dir, "queue_row.json"))
    params = row.get("params") or {}
    msgs = messages(run_dir, warmup_s)
    out = {"run": os.path.basename(run_dir), "setup": row.get("setup"),
           "backend": params.get("backend"), "load_pct": params.get("load_pct"),
           "consumer_priority": bool(params.get("consumer_priority")),
           "traced": os.path.exists(os.path.join(run_dir, "waits.txt")), "messages": len(msgs)}
    delays = [(receipt - send) / 1e3 for _, send, receipt in msgs]
    out.update(summarize("D", delays))
    # A pause holds every message sent while it lasts and releases them together, so one pause
    # can carry a run's mean; the quality report's limit says which runs hold one.
    out["D_max"] = max(delays) if delays else None
    out["D_held"] = sum(1 for delay in delays if delay > quality_report.STALL_MS * 1e3)
    out["iowait_s"] = pc.iowait_s(run_dir)
    waits, why = receive_waits(run_dir, msgs) if msgs else (None, "no message measured")
    out["wait_note"] = why or ""
    out.update(summarize("wait", [] if waits is None else [
        waits[eid] / 1e3 for eid, _, _ in msgs if waits.get(eid) is not None]))
    kernel, both, unmatched = [], [], None
    pcap = os.path.join(run_dir, "receiver_full.pcap")
    if os.path.exists(pcap):
        times = kernel_times(pcap, broker, receiver)
        unmatched = sum(1 for eid, _, _ in msgs if eid not in times)
        for eid, _send, receipt in msgs:
            if eid not in times:
                continue
            kernel.append((receipt - times[eid]) / 1e3)
            if waits is not None and waits.get(eid) is not None:
                both.append((kernel[-1], waits[eid] / 1e3))
    out.update(summarize("kernel", kernel))
    out["kernel_unmatched"] = unmatched
    out["kernel_negative"] = sum(1 for delay in kernel if delay < 0)
    out["kernel_ge_wait_share"] = (sum(1 for d, w in both if d >= w) / float(len(both))
                                   if both else None)
    out["kernel_minus_wait_median"] = (statistics.median(d - w for d, w in both)
                                       if both else None)
    return out


def r1_runs(folders, setup=R1_SETUP):
    """(run folder, the setup its queue row names, its integrity verdict) for every R1 run."""
    for folder in folders:
        for run_dir in sorted(glob.glob(os.path.join(folder, "law_*"))):
            named = read_json(os.path.join(run_dir, "queue_row.json")).get("setup") or ""
            if named.startswith(setup):
                yield (run_dir, named,
                       read_json(os.path.join(run_dir, "integrity.json")).get("verdict"))


def read_campaign(folders, broker, receiver, setup=R1_SETUP, warmup_s=WARMUP_S):
    """(rows for the R1 runs the integrity rule passed, [(run, verdict)] for the others)."""
    rows, skipped = [], []
    for run_dir, _named, verdict in r1_runs(folders, setup):
        if verdict != PASSING:
            skipped.append((os.path.basename(run_dir), verdict or "not judged"))
            continue
        rows.append(read_run(run_dir, broker, receiver, warmup_s))
    return rows, skipped


def pause_rows(folders, setup=R1_SETUP):
    """Every pause in the R1 runs the integrity rule passed, read with the 28 September census's
    own functions (scripts/pause_census.py): how long and how many it held, its kind by how long
    the broker's confirmations were held, the longest gap of the driver's sampler across it, the
    share of it the consumer spent inside a read, and the run's disk wait (iowait)."""
    rows = []
    for run_dir, named, verdict in r1_runs(folders, setup):
        if verdict != PASSING:
            continue
        for ep in pc.episodes(pc.messages(run_dir)):
            rows.append({"run": os.path.basename(run_dir), "setup": named,
                         "worst_ms": ep["worst_ms"], "late": ep["late"], "kind": pc.kind(ep),
                         "max_gotit_ms": ep["max_gotit_ms"],
                         "sampler_gap_s": pc.sampler_gap_s(run_dir, ep["start"], ep["end"]),
                         "inside_reads": pc.inside_reads(run_dir, ep["start"], ep["end"]),
                         "iowait_s": pc.iowait_s(run_dir)})
    return rows


# --- the comparison and the plan's predictions ----------------------------------------------------

def _value(row, key):
    value = row.get(key)
    return None if value in (None, "", "None") else float(value)


def setup_median(rows, key):
    """The median over runs of a run-level statistic; None where no run has it."""
    values = [v for v in (_value(r, key) for r in rows) if v is not None]
    return statistics.median(values) if values else None


def _flag(row, key):
    return str(row.get(key)) == "True"


def _fall(before, after):
    return None if before is None or after is None else before - after


def _before_after(before, after, prefix):
    """{statistic: (its median over the `before` runs, its median over the `after` runs)}."""
    return dict((stat, (setup_median(before, "%s_%s" % (prefix, stat)),
                        setup_median(after, "%s_%s" % (prefix, stat)))) for stat in STATS[1:])


def compare(rows):
    """{(broker, load): what the three methods say, and each prediction's verdict}."""
    parts = {}
    for row in rows:
        parts.setdefault((row["backend"], str(row["load_pct"])), []).append(row)
    found = {}
    for key, part in sorted(parts.items()):
        ordinary = [r for r in part if not _flag(r, "consumer_priority")]
        go_first = [r for r in part if _flag(r, "consumer_priority")]
        o_traced = [r for r in ordinary if _flag(r, "traced")]
        g_traced = [r for r in go_first if _flag(r, "traced")]
        d = _before_after(ordinary, go_first, "D")
        wait = _before_after(o_traced, g_traced, "wait")
        kernel = _before_after(ordinary, go_first, "kernel")
        # The plan reports traced and untraced runs apart wherever D is compared, since the
        # tracer is not a free observer; and the kernel's delay, which holds the traced wait.
        apart = {}
        for subset, o_runs, g_runs in (
                ("untraced", [r for r in ordinary if not _flag(r, "traced")],
                 [r for r in go_first if not _flag(r, "traced")]),
                ("traced", o_traced, g_traced)):
            apart[subset] = {"runs": (len(o_runs), len(g_runs)),
                             "D": _before_after(o_runs, g_runs, "D"),
                             "kernel": _before_after(o_runs, g_runs, "kernel")}
        estimates = (_fall(*d["mean"]), _fall(*wait["mean"]), _fall(*kernel["mean"]))
        traced = o_traced + g_traced
        shares = [v for v in (_value(r, "kernel_ge_wait_share") for r in traced) if v is not None]
        share, lowest = (statistics.median(shares), min(shares)) if shares else (None, None)
        difference = setup_median(traced, "kernel_minus_wait_median")
        p90_fall, median_move = _fall(*d["p90"]), _fall(*d["median"])
        o_mean, o_p90, g_mean = wait["mean"][0], wait["p90"][0], wait["mean"][1]
        positive = [e for e in estimates if e is not None and e > 0]
        ratio = max(positive) / min(positive) if len(positive) == 3 else None
        found[key] = {
            "runs": (len(ordinary), len(go_first)), "traced": (len(o_traced), len(g_traced)),
            "D": d, "wait": wait, "kernel": kernel, "apart": apart, "estimates": estimates,
            "ratio": ratio, "share": share, "lowest_share": lowest, "difference": difference,
            "p90_fall": p90_fall, "median_move": median_move,
            "unmatched": sum(int(_value(r, "kernel_unmatched") or 0) for r in part),
            "held": sorted((r.get("run"), int(_value(r, "D_held")), _value(r, "D_max"))
                           for r in part if (_value(r, "D_held") or 0) > 0),
            "R1-a": (o_mean is not None and R1A_MEAN_US[0] <= o_mean <= R1A_MEAN_US[1]
                     and o_p90 is not None and o_p90 > R1A_P90_US
                     and g_mean is not None and g_mean < R1A_PRIORITY_MEAN_US),
            "R1-b": (p90_fall is not None and p90_fall >= R1B_P90_FALL_US
                     and abs(median_move) < R1B_MEDIAN_MOVE_US),
            "R1-c": (share is not None and share >= R1C_SHARE and difference is not None
                     and difference < R1C_DIFFERENCE_US),
            "R1-d": ratio is not None and ratio <= R1D_FACTOR}
    return found


def _ms(us):
    return "-" if us is None else "%.2f ms" % (us / 1000.0)


def _changes(pairs):
    return "; ".join("%s %s -> %s" % (stat, _ms(pairs[stat][0]), _ms(pairs[stat][1]))
                     for stat in STATS[1:])


def _share(share):
    return "-" if share is None else "%.1f%%" % (100 * share)


def lines(found):
    """The comparison as text, part by part, then the predictions' tallies."""
    out = []
    for (broker, load), f in sorted(found.items()):
        out.append("%s at %s%% load: %d ordinary runs (%d traced), %d go-first-consumer runs "
                   "(%d traced)" % (broker, load, f["runs"][0], f["traced"][0], f["runs"][1],
                                    f["traced"][1]))
        for name, label in (("D", "method 1, D"), ("wait", "method 2, traced own wait"),
                            ("kernel", "method 3, kernel receipt to stamp")):
            out.append("  %s: %s" % (label, _changes(f[name])))
            if name == "wait":
                continue
            for subset in ("untraced", "traced"):
                runs = f["apart"][subset]["runs"]
                out.append("    %s runs only, %d -> %d: %s" % (
                    subset, runs[0], runs[1], _changes(f["apart"][subset][name])))
        out.append("  estimates of the mean inflation: method 1 %s, method 2 %s, method 3 %s; "
                   "largest over smallest %s" % (tuple(_ms(e) for e in f["estimates"]) + (
                       "-" if f["ratio"] is None else "%.2f" % f["ratio"],)))
        out.append("  kernel delay at least the traced wait for %s of messages (median over "
                   "traced runs; lowest run %s); median difference %s; messages not found in the "
                   "capture: %d" % (_share(f["share"]), _share(f["lowest_share"]),
                                    _ms(f["difference"]), f["unmatched"]))
        out.append("  runs holding a message over the quality report's %.0f ms pause limit: %s"
                   % (quality_report.STALL_MS, "; ".join(
                       "%s, %d messages, longest %s" % (run, n, _ms(longest))
                       for run, n, longest in f["held"]) or "none"))
        out.append("  " + ", ".join("%s %s" % (p, "holds" if f[p] else "fails")
                                    for p in ("R1-a", "R1-b", "R1-c", "R1-d")))
    for p in ("R1-a", "R1-b", "R1-c", "R1-d"):
        out.append("%s holds in %d of %d broker-and-load parts" % (
            p, sum(1 for f in found.values() if f[p]), len(found)))
    return out


# --- what the earlier campaigns already said ------------------------------------------------------

def traced_runs(folders, warmup_s=WARMUP_S):
    """Method 2 on the law campaign's traced runs (A9): one row per run read, and the reasons
    the others were not."""
    rows, skipped = [], {}
    for folder in folders:
        pair = os.path.basename(os.path.dirname(os.path.normpath(folder)))
        for run in hw.counted_runs([folder], ("A9",)):
            msgs = messages(run["run_dir"], warmup_s)
            waits, why = receive_waits(run["run_dir"], msgs)
            if waits is None:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            row = {"pair": pair, "backend": run["backend"], "load_pct": run.get("load_pct"),
                   "setup": run["setup"], "run": run["run"], "messages": len(msgs)}
            row.update(summarize("D", [(receipt - send) / 1e3 for _, send, receipt in msgs]))
            row.update(summarize("wait", [waits[e] / 1e3 for e, _, _ in msgs
                                          if waits.get(e) is not None]))
            rows.append(row)
    return rows, skipped


def priority_runs(folders, warmup_s=WARMUP_S):
    """D with and without go-first for both clock-reading processes (A7), pooled by pair,
    broker, delivery point and priority: one row each."""
    pooled = {}
    for folder in folders:
        pair = os.path.basename(os.path.dirname(os.path.normpath(folder)))
        for run in hw.counted_runs([folder], ("A7",)):
            key = (pair, run["backend"], run.get("point"),
                   "go-first" if run.get("priority") else "ordinary")
            pooled.setdefault(key, []).extend(
                (receipt - send) / 1e3 for _, send, receipt in messages(run["run_dir"], warmup_s))
    rows = []
    for (pair, backend, point, priority), values in sorted(pooled.items(), key=str):
        row = {"pair": pair, "backend": backend, "point": point, "priority": priority}
        row.update(summarize("D", values))
        rows.append(row)
    return rows


# --- the command line -----------------------------------------------------------------------------

def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["empty"])
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("read")
    p.add_argument("--runs", action="append", required=True)
    p.add_argument("--broker", required=True)
    p.add_argument("--receiver", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("compare")
    p.add_argument("--table", required=True)
    p.add_argument("--out")
    for name in ("pauses", "traced", "priority"):
        p = sub.add_parser(name)
        p.add_argument("--runs", action="append", required=True)
        p.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.command == "read":
        rows, skipped = read_campaign(args.runs, args.broker, args.receiver)
        write_csv(args.out, rows)
        out.write("%d runs read, %d not read%s\n" % (len(rows), len(skipped), "".join(
            "\n  %s: %s" % pair for pair in skipped)))
    elif args.command == "compare":
        with open(args.table, newline="", encoding="utf-8") as fh:
            text = "\n".join(lines(compare(list(csv.DictReader(fh))))) + "\n"
        out.write(text)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
    elif args.command == "pauses":
        rows = pause_rows(args.runs)
        write_csv(args.out, rows)
        out.write("%d pauses in %d runs\n" % (len(rows), len(set(r["run"] for r in rows))))
    elif args.command == "traced":
        rows, skipped = traced_runs(args.runs)
        write_csv(args.out, rows)
        out.write("%d traced runs read; not read: %s\n" % (len(rows), skipped or "none"))
    else:
        rows = priority_runs(args.runs)
        write_csv(args.out, rows)
        out.write("%d pooled rows\n" % len(rows))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
