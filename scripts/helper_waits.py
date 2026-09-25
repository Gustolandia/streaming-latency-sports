#!/usr/bin/env python3
"""
helper_waits.py -- whether the waits of the thread that stamps "got it" account for the negative
readings. Frozen in plan version 30, before any of A9's runs is read (D30-5, D30-6).

A negative reading is a message whose arrival was stamped before its acknowledgement was. The law
says why: the acknowledgement was ready at about t + g, the message arrived at about t + T, and
the thread that stamps the acknowledgement sat waiting for a CPU past the arrival. So a recording
of that thread's waits should predict how often it happens (P6), and each negative reading should
find the thread waiting (A9-1).

Two recordings answer it.

  A6  In a random half of A1's and A3's runs, every python3 thread's waits for a CPU in one
      histogram of 0.1 ms steps, with no clock and no thread (runqlat.txt). A run's rate is
      predicted as E-A9 predicted it, with nothing fitted: the share of recorded waits longer
      than T - g, the run's median trip less its median "got it" delay, which is the margin a
      wait must outlast for the reading to turn negative (A9-2 states the same condition). A
      share of a histogram is the only prediction a record with no clock and no thread supports.
  A9  In a random half of A9's runs, every python3 thread's scheduling events one by one
      (waits.txt), and each client's record of which of its threads stamps what, with both
      clocks read at its start and end (*_threads.json). The three questions version 28 froze:
      A9-1, what the stamping thread was doing between each negative reading's arrival and its
      stamp; A9-2, P6 on that thread alone, a run's rate predicted as the sum over its waits W of
      max(0, W - (T - g)), divided by the length D of the measured window; A9-3, where its waits
      end at each load. And one version 30 adds, before any A9 run (A9-2b): the share of the
      run's acknowledgements whose own wait for a CPU outlasted T - g.

Why A9-2b. A9-2's sum counts the time during which a message arriving at a random moment would
find the thread already stalled, which is the right count where the stalls come independently of
the messages. Both producers stamp from a thread that sleeps until an acknowledgement's reply
wakes it -- kafka-python's network thread in its selector, each Redis send worker on its socket
-- so the stall that decides a reading is the one its own acknowledgement began, and the sum
cannot see it. The share of those stalls longer than T - g is E-A9's prediction and A6's, made
message by message. Both are reported; A9-2 is judged as version 28 froze it.

P6's rule, in the plan since version 1: at least two thirds of setups within 0.67-1.5 of the
measured rate, and the median ratio at least 0.8. A setup's ratio is the mean of its recorded
runs' predictions over the mean of their measured rates. A setup whose recorded runs measured no
negative reading has no ratio; it is reported with its prediction and counted in neither share.
Nothing is pooled across machine pairs or backends, and a prediction holds only where every part
holds. A part with no ratio at all did not test it, and is reported out of reach.

Choices the plan leaves to the reading, each fixed here before the data:

  * The thread that stamped an acknowledgement is the one the producer names. Kafka names one;
    the Redis producer's send workers all stamp, so a message's stamper is the named thread that
    was on a CPU at the instant of its stamp. A stamp that finds none or several is unidentified.
  * A run is read only where the stamper of at least 90% of its acknowledgements is identified:
    below that the recording cannot be laid on the clients' clocks well enough to say which wait
    belongs to which message. It is reported and not read, as a run that lost events is.
  * A negative reading whose stamper is unidentified, or whose interval comes out empty on the
    tracer's clock, counts against A9-1: it was not shown to be waiting.
  * Where several threads stamp, A9-2 weighs each thread's waits by the share of the run's
    acknowledgements it stamped, since a thread's wait can only turn the messages it stamps; a
    prediction above one is one, since a rate cannot be.
  * A wait belongs to the measured window when it begins inside it, the window running from the
    first to the last message sent after the warm-up.
  * An acknowledgement's own wait (A9-2b) is the time its stamper spent waiting for a CPU from
    the later of its last wake from sleep and its previous stamp, up to this stamp.

Only runs the integrity rule passed, and only messages sent after the warm-up, as everywhere.

CLI:
    python scripts/helper_waits.py p6 --runs <campaign folder> [--runs ...] [--out answer.json]
    python scripts/helper_waits.py a9 --runs <campaign folder> [--runs ...] [--out answer.json]
"""
import argparse
import bisect
import csv
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import law_curve  # noqa: E402
import pilot_checks  # noqa: E402 - the one definition of a negative reading
import quality_report  # noqa: E402

#: P6's rule: the band a setup's ratio must fall in, the share of setups that must (two of
#: three), and how low the median ratio may go before the prediction is systematically too low.
BAND = (0.67, 1.5)
SHARE_WITHIN = (2, 3)
MEDIAN_AT_LEAST = 0.8
#: A9-1: the share of negative readings that must have spent more than half of the time between
#: arrival and stamp waiting for a CPU.
READINGS_WAITING = 0.9
MOSTLY = 0.5
#: The share of a run's acknowledgements whose stamper must be identified for the run to be read.
IDENTIFIED_AT_LEAST = 0.9
#: A9-3's percentiles, reported with the longest wait and no rule.
PERCENTILES = (50, 90, 99)
#: The warm-up every judge leaves out.
WARMUP_S = 30.0
#: What nothing is pooled across, as law_predictions.SPLIT_BY.
SPLIT_BY = ("pair", "backend")
#: Which setups each recording rides in.
BLOCKS = {"p6": ("A1", "A3"), "a9": ("A9",)}
#: bpftrace's linear histogram, one bin a line: [low, high) count, and the last bin open.
BIN = re.compile(r"^\[(\d+),\s*(\d+|\.\.\.)\)\s+(\d+)")
#: bpftrace's own report that its buffer overflowed and events were dropped.
LOST = re.compile(r"Lost \d+ events")
#: What a thread is doing between two of its events; unknown before its first.
STATES = ("waiting", "asleep", "running", "unknown")
NOT_RECORDED = "not recorded"
RULE = ("at least two thirds of setups predict their measured rate within %s-%s, and the median "
        "ratio is at least %s" % (BAND[0], BAND[1], MEDIAN_AT_LEAST))
A9_1_RULE = ("at a backend and load, at least %g%% of negative readings spent more than half of "
             "the time from arrival to stamp waiting for a CPU" % (100 * READINGS_WAITING))


# --- the A6 histogram --------------------------------------------------------------------------

def histogram(path):
    """[(low_us, high_us, count)] from a bpftrace linear histogram; an open last bin has None."""
    bins = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = BIN.match(line.strip())
            if m:
                bins.append((int(m.group(1)), None if m.group(2) == "..." else int(m.group(2)),
                             int(m.group(3))))
    return bins


def share_longer(bins, threshold_us):
    """The share of the waits longer than `threshold_us`, a bin across it counted in proportion.

    None where there is nothing to share out, or where the threshold falls inside the open last
    bin, whose waits the histogram does not place.
    """
    total = sum(n for _, _, n in bins)
    if not total:
        return None
    over = 0.0
    for low, high, n in bins:
        if low >= threshold_us:
            over += n
        elif high is None:
            if n:
                return None
        elif high > threshold_us:
            over += n * (high - threshold_us) / float(high - low)
    return over / total


def a6_prediction(run):
    """(the run's predicted rate, None) or (None, why it could not be read)."""
    path = os.path.join(run["run_dir"], "runqlat.txt")
    if not os.path.exists(path):
        return None, NOT_RECORDED
    if run.get("gotit_ms") is None:
        return None, "no median got-it delay"
    share = share_longer(histogram(path), (run["trip_ms"] - run["gotit_ms"]) * 1000.0)
    if share is None:
        return None, "the histogram holds no wait it can place against T - g"
    return share, None


# --- the A9 recording ---------------------------------------------------------------------------

def events(path, tids):
    """({tid: [(ns, kind)]} for the named threads in time order, whether any events were lost)."""
    wanted = set(tids)
    found, lost = dict((tid, []) for tid in wanted), False
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if (len(parts) == 3 and parts[0] in ("P", "S", "R", "W") and parts[1].isdigit()
                    and parts[2].isdigit()):
                tid = int(parts[1])
                if tid in wanted:
                    found[tid].append((int(parts[2]), parts[0]))
            elif LOST.search(line):
                lost = True
    for tid in found:
        found[tid].sort()
    return found, lost


class Timeline:
    """One thread's states over the recording: each moment its state changed, and to what.

    Taken off a CPU while it could still run (P), it waits for one; taken off because it slept
    (S), it is asleep; put on one (R), it runs. A wake-up (W) moves a sleeping thread to waiting;
    a thread still on its CPU, or already waiting, is not woken into anything new.
    """

    def __init__(self, evts):
        self.times, self.states, self.wakes, state = [], [], [], "unknown"
        for ns, kind in evts:
            if kind == "R":
                new = "running"
            elif kind == "P":
                new = "waiting"
            elif kind == "S":
                new = "asleep"
            else:
                new = "waiting" if state in ("asleep", "unknown") else state
            if new != state:
                if state == "asleep":
                    self.wakes.append(ns)
                self.times.append(ns)
                self.states.append(new)
                state = new

    def at(self, ns):
        """What the thread was doing at `ns`."""
        i = bisect.bisect_right(self.times, ns)
        return self.states[i - 1] if i else "unknown"

    def spent(self, start, end):
        """{state: ns} the thread spent in each state from `start` to `end`."""
        spent = dict((state, 0) for state in STATES)
        i = bisect.bisect_right(self.times, start)
        state, at = (self.states[i - 1] if i else "unknown"), start
        while i < len(self.times) and self.times[i] < end:
            spent[state] += self.times[i] - at
            at, state = self.times[i], self.states[i]
            i += 1
        spent[state] += end - at
        return spent

    def waits(self, start, end):
        """The thread's waits for a CPU, in ns, that began between `start` and `end`."""
        first = bisect.bisect_left(self.times, start)
        last = bisect.bisect_right(self.times, end)
        return [self.times[i + 1] - self.times[i] for i in range(first, last)
                if self.states[i] == "waiting" and i + 1 < len(self.times)]

    def own_wait(self, stamp, previous):
        """How long the thread waited for a CPU before `stamp`: from the later of its last wake
        from sleep and `previous`, its stamp before this one, or None if it never slept or
        stamped before."""
        i = bisect.bisect_right(self.wakes, stamp)
        since = max([t for t in (self.wakes[i - 1] if i else None, previous) if t is not None]
                    or [None])
        return None if since is None else self.spent(since, stamp)["waiting"]


def to_monotonic(record):
    """The tracer's CLOCK_MONOTONIC for a client's CLOCK_REALTIME stamp.

    The client read both clocks back to back at its start and its end; the offset between them is
    drawn straight between those two readings, so a clock slewed steadily over the run is followed.
    """
    first, last = record["clocks"][0], record["clocks"][-1]
    lead = first["realtime_ns"] - first["monotonic_ns"]
    drift = (last["realtime_ns"] - last["monotonic_ns"]) - lead
    span = float(last["realtime_ns"] - first["realtime_ns"])

    def convert(realtime_ns):
        share = (realtime_ns - first["realtime_ns"]) / span if span else 0.0
        return realtime_ns - lead - drift * share
    return convert


def thread_records(run_dir):
    """{"producer": record, "consumer": record}, each found by the role it names."""
    found = {}
    for name in sorted(os.listdir(run_dir)):
        if not name.endswith("_threads.json"):
            continue
        record = quality_report.read_json(os.path.join(run_dir, name))
        roles = record.get("roles") or {}
        if roles.get("stamps_ack"):
            found["producer"] = record
        if roles.get("stamps_receive"):
            found["consumer"] = record
    return found


def messages(run_dir, warmup_s=WARMUP_S):
    """[(send, ack, arrival)] in the clients' ns, for the messages pilot_checks.spans measures:
    sent after the warm-up, arrived, and acknowledged."""
    sent = {}
    with open(os.path.join(run_dir, "producer.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sent[r["event_id"]] = (pilot_checks._int(r.get("t_prod_send_ns")),
                                   pilot_checks._int(r.get("t_broker_ack_ns")))
    starts = [s for s, _ in sent.values() if s is not None]
    if not starts:
        return []
    cutoff = min(starts) + int(warmup_s * 1e9)
    found = []
    with open(os.path.join(run_dir, "consumer_events.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            send, ack = sent.get(r["event_id"], (None, None))
            arrival = pilot_checks._int(r.get("t_consume_ns"))
            if send is None or arrival is None or ack is None or send < cutoff:
                continue
            found.append((send, ack, arrival))
    return found


def a9_run(run, warmup_s=WARMUP_S):
    """What one recorded A9 run says, or (None, why it was not read)."""
    run_dir = run["run_dir"]
    path = os.path.join(run_dir, "waits.txt")
    if not os.path.exists(path):
        return None, NOT_RECORDED
    records = thread_records(run_dir)
    if "producer" not in records or "consumer" not in records:
        return None, "no thread record from both clients"
    if run.get("gotit_ms") is None:
        return None, "no median got-it delay"
    stampers = sorted(records["producer"]["roles"]["stamps_ack"])
    evts, lost = events(path, stampers)
    err = os.path.join(run_dir, "waits.err")
    if os.path.exists(err):
        with open(err, encoding="utf-8", errors="replace") as fh:
            lost = lost or bool(LOST.search(fh.read()))
    if lost:
        return None, "the recording lost events"
    lines = dict((tid, Timeline(found)) for tid, found in evts.items())
    producer, consumer = to_monotonic(records["producer"]), to_monotonic(records["consumer"])
    sent = messages(run_dir, warmup_s)
    if not sent:
        return None, "no message measured"
    stamped_by = []
    for _, ack, _ in sent:
        on = [tid for tid in stampers if lines[tid].at(producer(ack)) == "running"]
        stamped_by.append(on[0] if len(on) == 1 else None)
    identified = sum(1 for tid in stamped_by if tid is not None)
    if identified < IDENTIFIED_AT_LEAST * len(sent):
        return None, ("the stamper of %d of %d acknowledgements was identified, under %g%%"
                      % (identified, len(sent), 100 * IDENTIFIED_AT_LEAST))
    margin = (run["trip_ms"] - run["gotit_ms"]) * 1e6
    readings, own, previous = [], [], {}
    for (_, ack, arrival), tid in sorted(zip(sent, stamped_by), key=lambda pair: pair[0][1]):
        if tid is not None:
            stamp = producer(ack)
            own.append(lines[tid].own_wait(stamp, previous.get(tid)))
            previous[tid] = stamp
        if arrival - ack >= 0:
            continue
        start, end = consumer(arrival), producer(ack)
        if tid is None or end <= start:
            readings.append(None)
            continue
        spent = lines[tid].spent(start, end)
        readings.append(dict((state, spent[state] / float(end - start)) for state in STATES))
    window = (producer(min(s for s, _, _ in sent)), producer(max(s for s, _, _ in sent)))
    length = window[1] - window[0]
    by_thread = dict((tid, lines[tid].waits(*window)) for tid in stampers)
    predicted = None if length <= 0 else min(1.0, sum(
        (sum(1 for t in stamped_by if t == tid) / float(identified))
        * sum(max(0.0, wait - margin) for wait in by_thread[tid]) / length
        for tid in stampers))
    seen = [wait for wait in own if wait is not None]
    return {"readings": readings, "predicted": predicted,
            "predicted_own": sum(1 for wait in seen if wait > margin) / float(len(seen))
            if seen else None,
            "waits_ms": [wait / 1e6 for tid in stampers for wait in by_thread[tid]],
            "identified": identified, "acknowledgements": len(sent),
            "stamping_threads": len(stampers)}, None


# --- runs, setups and the rule -----------------------------------------------------------------

def counted_runs(folders, blocks):
    """The runs the integrity rule passed, as the judges read them, from the named blocks, each
    with its own folder and its median "got it" delay."""
    found = []
    for folder in folders:
        where = dict((os.path.basename(d), d) for d in quality_report.run_dirs_under(folder))
        for run in law_curve.read_runs(folder):
            if str(run.get("setup") or "").split("-")[0] not in blocks:
                continue
            run_dir = where[run["run"]]
            recorded = quality_report.read_json(
                os.path.join(run_dir, "integrity.json")).get("recorded", {})
            found.append(dict(run, run_dir=run_dir, gotit_ms=recorded.get("gotit_median_ms")))
    return found


def split(runs, keys=SPLIT_BY):
    """{part: its runs}, a part for each value of `keys`."""
    parts = {}
    for run in runs:
        parts.setdefault(", ".join(str(run.get(key)) for key in keys), []).append(run)
    return parts


def _mean(values):
    return sum(values) / float(len(values)) if values else None


def setups_of(runs, predict):
    """{campaign/setup: its recorded runs' mean prediction, mean measured rate and ratio}.

    Each campaign's setup is its own: two campaigns that ran the same setup ran it at different
    sittings. The runs that did not record are kept apart, and their mean rate is reported
    beside, because the recording has an effect of its own to be seen (A6).
    """
    setups = {}
    for run in runs:
        entry = setups.setdefault("%s/%s" % (run.get("campaign"), run.get("setup")),
                                  {"pairs": [], "unrecorded": [], "not_read": []})
        value, why = predict(run)
        if why == NOT_RECORDED:
            entry["unrecorded"].append(run["negative_rate"])
        elif why is not None:
            entry["not_read"].append({"run": run["run"], "why": why})
        else:
            entry["pairs"].append((value, run["negative_rate"]))
    for entry in setups.values():
        pairs = entry.pop("pairs")
        predicted = _mean([p for p, _ in pairs])
        measured = _mean([m for _, m in pairs])
        entry.update(recorded_runs=len(pairs), predicted=predicted, measured=measured,
                     ratio=predicted / measured if measured else None,
                     unrecorded_rate=_mean(entry.pop("unrecorded")))
    return setups


def rule(setups):
    """P6's rule over one part's setups."""
    ratios = [entry["ratio"] for entry in setups.values() if entry["ratio"] is not None]
    within = sum(1 for ratio in ratios if BAND[0] <= ratio <= BAND[1])
    median = statistics.median(ratios) if ratios else None
    held = (bool(ratios) and SHARE_WITHIN[1] * within >= SHARE_WITHIN[0] * len(ratios)
            and median >= MEDIAN_AT_LEAST)
    return {"confirmed": held, "tested": bool(ratios), "setups_with_a_ratio": len(ratios),
            "within_band": within, "median_ratio": median,
            "setups_without_a_rate": sorted(name for name, entry in setups.items()
                                            if entry["ratio"] is None
                                            and entry["recorded_runs"]),
            "setups": setups}


def _whole(by_part, **rest):
    """The answer over every part: held only where every part holds."""
    out = {"confirmed": bool(by_part) and all(part["confirmed"] for part in by_part.values()),
           "tested": bool(by_part) and all(part["tested"] for part in by_part.values()),
           "by_part": by_part}
    out.update(rest)
    return out


def judge_p6(runs):
    """P6 on A6's recordings."""
    by_part = dict((part, rule(setups_of(some, a6_prediction)))
                   for part, some in sorted(split(runs).items()))
    return _whole(by_part, prediction="P6", recording="A6", rule=RULE,
                  predicted_as="the share of recorded waits longer than T - g")


def percentiles(values):
    """{p50, p90, p99, longest} of a list, by the inclusive method; None for an empty one."""
    if not values:
        return None
    ordered = sorted(values)
    cuts = statistics.quantiles(ordered, n=100, method="inclusive") if len(ordered) > 1 \
        else [ordered[0]] * 99
    found = dict(("p%d" % p, cuts[p - 1]) for p in PERCENTILES)
    found["longest"] = ordered[-1]
    return found


def a9_1(readings):
    """A9-1 at one backend and load, over its negative readings."""
    shown = [r for r in readings if r is not None]
    waiting = sum(1 for r in shown if r["waiting"] > MOSTLY)
    return {"holds": bool(readings) and waiting >= READINGS_WAITING * len(readings),
            "negative_readings": len(readings), "mostly_waiting": waiting,
            "not_shown": len(readings) - len(shown),
            "mean_shares": dict((state, _mean([r[state] for r in shown])) for state in STATES)
            if shown else None}


def judge_a9(runs, warmup_s=WARMUP_S):
    """A9-1, A9-2 (and A9-2b beside it) and A9-3, each part on its own."""
    read, not_read = {}, []
    for run in runs:
        found, why = a9_run(run, warmup_s)
        if why is None:
            read[run["run"]] = found
        elif why != NOT_RECORDED:
            not_read.append({"run": run["run"], "why": why})
    refused = set(item["run"] for item in not_read)

    def predictor(key):
        def predict(run):
            if run["run"] in read:
                return read[run["run"]][key], None
            return None, "not read" if run["run"] in refused else NOT_RECORDED
        return predict

    by_part = {}
    for part, some in sorted(split(runs).items()):
        loads = {}
        for load, at in sorted(split(some, ("load_pct",)).items()):
            mine = [read[run["run"]] for run in at if run["run"] in read]
            loads[load] = {
                "a9_1": a9_1([r for found in mine for r in found["readings"]]),
                "a9_3": {"waits_ms": percentiles([w for found in mine for w in found["waits_ms"]]),
                         "slices_ms": sorted(set(run.get("slice_ms") for run in at)),
                         "ticks_ms": sorted(set(run.get("tick_ms") for run in at))}}
        answer = rule(setups_of(some, predictor("predicted")))
        answer.update(loads=loads, a9_2b=rule(setups_of(some, predictor("predicted_own"))),
                      a9_1_holds=all(one["a9_1"]["holds"] for one in loads.values()))
        by_part[part] = answer
    return _whole(by_part, prediction="P6", recording="A9", rule=RULE, not_read=not_read,
                  predicted_as="the sum of max(0, W - (T - g)) over the stamping thread's waits, "
                               "over the window's length (A9-2)",
                  a9_2b_predicted_as="the share of acknowledgements whose own wait outlasted "
                                     "T - g (A9-2b)",
                  a9_2b_confirmed=bool(by_part) and all(part["a9_2b"]["confirmed"]
                                                        for part in by_part.values()),
                  a9_1_rule=A9_1_RULE,
                  a9_1_holds=bool(by_part) and all(part["a9_1_holds"]
                                                   for part in by_part.values()))


def _round(value):
    return None if value is None else round(value, 4)


def _word(found):
    return "confirmed" if found["confirmed"] else (
        "not confirmed" if found["tested"] else "out of reach")


def lines(found):
    """The answer as a person reads it."""
    out = ["P6 on %s's recording: %s" % (found["recording"], _word(found)),
           "  rule: %s" % found["rule"], "  predicted as: %s" % found["predicted_as"]]
    if found["recording"] == "A9":
        out += ["  A9-2b, %s: %s" % (found["a9_2b_predicted_as"],
                                     "confirmed" if found["a9_2b_confirmed"] else
                                     "not confirmed"),
                "  A9-1: %s (%s)" % ("holds" if found["a9_1_holds"] else "does not hold",
                                     found["a9_1_rule"])]
    for part, answer in sorted(found["by_part"].items()):
        out.append("  %s: %s; %d of %d setups within the band, median ratio %s" % (
            part, _word(answer), answer["within_band"], answer["setups_with_a_ratio"],
            _round(answer["median_ratio"])))
        for load, said in sorted(answer.get("loads", {}).items()):
            one, where = said["a9_1"], said["a9_3"]["waits_ms"]
            out.append("    load %s: A9-1 %s, %d of %d negative readings mostly waiting; waits "
                       "%s ms" % (load, "holds" if one["holds"] else "does not hold",
                                  one["mostly_waiting"], one["negative_readings"],
                                  None if where is None else
                                  dict((k, _round(v)) for k, v in sorted(where.items()))))
    for item in found.get("not_read", []):
        out.append("  not read: %s -- %s" % (item["run"], item["why"]))
    return out


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Whether the stamping thread's waits predict the "
                                             "negative rate: P6, on A6's and A9's recordings")
    ap.add_argument("recording", choices=sorted(BLOCKS))
    ap.add_argument("--runs", action="append", required=True,
                    help="a campaign's folder of copied runs; give one for each campaign")
    ap.add_argument("--warmup-s", type=float, default=WARMUP_S)
    ap.add_argument("--out", default="", help="write the answer here as JSON")
    args = ap.parse_args(argv)
    try:
        runs = counted_runs(args.runs, BLOCKS[args.recording])
        if not runs:
            raise ValueError("no counted run of %s under %s"
                             % (" or ".join(BLOCKS[args.recording]), ", ".join(args.runs)))
        found = judge_p6(runs) if args.recording == "p6" else judge_a9(runs, args.warmup_s)
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(found, indent=2, sort_keys=True, default=str) + "\n")
        for line in lines(found):
            print(line, file=out)
        return 0 if found["confirmed"] else (1 if found["tested"] else 3)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
