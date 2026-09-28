#!/usr/bin/env python3
"""
m0_bursts.py -- M0 read message by message: why Redis's median trip grows faster than the delay
in bursts, and Kafka's does not. Read on 28 September 2026, after M0 was answered by the frozen
m0_read.py (D31-1). It answers nothing M0 asked and changes nothing M0 said: M-H1 to M-H4 were
kept or dropped by their own tests, and they stay as they were.

The football match sends its events in bursts: every event of one match second is scheduled for
the same instant. A burst's first message to reach the broker is its *leader*; the others are its
*followers*, numbered r = 1, 2, ... in the order the broker took them (a Redis stream's own ids;
for Kafka, the order they were sent). Each message's trip is read off its own two stamps, after
the warm-up, as every judge reads them.

How fast a message's trip grows with the delay d the broker holds -- its growth k -- follows from
the receive loop's own rules, with nothing fitted:

  Kafka              k = 1 for every message: the producer sends a burst in one request and the
                     consumer fetches it in one answer.
  Redis, batch > 1   k = 1 for the leader, whose read was already waiting at the broker; k = 2 for
                     a follower, which waits for the leader's delayed answer to land before the
                     next read is even sent, and then for its own.
  Redis, batch 1     k = r + 2 for follower r: those two, and one delayed acknowledgement round
                     trip for each message stamped before it in the same answer.

What the median does with them. A run's median trip M(d) is where its messages' trips, each
grown by its own k d, cross one half. The prediction takes the runs at no added delay, moves every
message by its own k d and takes the median; the slope of those medians on d is set against the
slope M0 measured. Once every follower has passed the median -- the leaders are more than half of
the messages -- M(d) = d + Q(1/(2 pi)), Q the leaders' own quantile at no delay and pi their share:
the departure stops growing and becomes a step, Q(1/(2 pi)) - M(0).

Why M-H2's replay could not show it. The frozen replay gives every leader the same trip, since it
feeds each message's arrival through fixed costs; with the leaders above half, its median is always
a leader's trip, d plus a constant, whatever the followers do. This reads that off the replay
itself: the share of each recorded run's replayed trips at their smallest value.

And why the recording moved Redis's trip most at 8 ms: there the median sits on the leaders'
upper tail, at that same quantile, and the recording moves the tail more than the middle.

CLI:
    python scripts/m0_bursts.py --runs <M0 campaign folder> --out <folder>
"""
import argparse
import csv
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helper_waits  # noqa: E402 - the warm-up every judge leaves out
import law_predictions  # noqa: E402
import m0_read  # noqa: E402

#: The delays M0 ran, in ms, and the one its departure is read at.
DELAYS = (0.0, 2.0, 8.0)
AT_MS = m0_read.AT_MS
#: A replayed trip this close to the run's smallest is the same trip.
SAME_TRIP_MS = 0.05


# --- a run's messages, in bursts ----------------------------------------------------------------

def _broker_order(row):
    """Where a message stands in the order the broker took its burst: a Redis stream id is the
    time the broker added it and a sequence number; a message without one is ordered by its send."""
    rid = (row.get("redis_id") or "").split("-")
    if len(rid) == 2 and rid[0].isdigit() and rid[1].isdigit():
        return (int(rid[0]), int(rid[1]))
    return (int(row["t_prod_send_ns"]), 0)


def bursts(run_dir, warmup_s=helper_waits.WARMUP_S):
    """[(trip_ms, rank)] for the run's measured messages: rank 0 is the leader of its burst."""
    sent = []
    with open(os.path.join(run_dir, "producer.csv"), newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("t_prod_send_ns") and row.get("t_prod_sched_ns"):
                sent.append(row)
    arrived = {}
    with open(os.path.join(run_dir, "consumer_events.csv"), newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("t_consume_ns"):
                arrived[row["event_id"]] = int(row["t_consume_ns"])
    if not sent:
        return []
    cutoff = min(int(row["t_prod_send_ns"]) for row in sent) + warmup_s * 1e9
    groups = {}
    for row in sent:
        groups.setdefault(row["t_prod_sched_ns"], []).append(row)
    found = []
    for group in groups.values():
        for rank, row in enumerate(sorted(group, key=_broker_order)):
            send = int(row["t_prod_send_ns"])
            if send >= cutoff and row["event_id"] in arrived:
                found.append(((arrived[row["event_id"]] - send) / 1e6, rank))
    return found


def growth(backend, ack_batch, rank):
    """k: how many delayed replies a message of this rank waits for, by the loop's own rules."""
    if backend != "redis" or rank == 0:
        return 1
    return rank + 2 if ack_batch == 1 else 2


# --- the reading ----------------------------------------------------------------------------------

def _quantile(values, share):
    """The value `share` of the way up the sorted values, the lower of two where it falls between."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(share * len(ordered))))]


def read_messages(runs):
    """Each run with its messages beside it, as `bursts` reads them."""
    return [dict(run, messages=bursts(run["run_dir"])) for run in runs]


def at(runs, delay):
    return [run for run in runs if run.get("set_ms") is not None
            and abs(run["set_ms"] - delay) < 1e-6]


def by_rank(runs):
    """[{part, delay_ms, rank, messages, median_trip_ms, growth_per_ms, rule}] over the runs."""
    table = {}
    for run in runs:
        for trip, rank in run["messages"]:
            key = (m0_read.part_of(run), run["set_ms"], rank)
            table.setdefault(key, []).append(trip)
    rows = []
    for (part, delay, rank), trips in sorted(table.items()):
        zero = table.get((part, 0.0, rank))
        run = next(r for r in runs if m0_read.part_of(r) == part)
        rows.append({"part": part, "delay_ms": delay, "rank": rank, "messages": len(trips),
                     "median_trip_ms": statistics.median(trips),
                     "growth_per_ms": (None if not delay or not zero else
                                       (statistics.median(trips) - statistics.median(zero))
                                       / delay),
                     "rule": growth(run["backend"], run["ack_batch"], rank)})
    return rows


def predicted_medians(zero_runs, delays=DELAYS):
    """[(d, median)] for each run at no added delay: every message moved by its own k d."""
    points = []
    for run in zero_runs:
        for d in delays:
            moved = [trip + growth(run["backend"], run["ack_batch"], rank) * d
                     for trip, rank in run["messages"]]
            if moved:
                points.append((d, statistics.median(moved)))
    return points


def _slope(points):
    line = law_predictions.straight_line([d for d, _ in points], [m for _, m in points])
    return None if line is None else line[0]


def _mean_by_delay(points, delays=DELAYS):
    return dict(("%g" % d, statistics.mean([m for x, m in points if x == d]))
                for d in delays if any(x == d for x, _ in points))


def leaders_share(runs):
    """pi: the share of the part's measured messages that lead their burst."""
    ranks = [rank for run in runs for _, rank in run["messages"]]
    return sum(1 for rank in ranks if rank == 0) / float(len(ranks)) if ranks else None


def step(runs):
    """{share, quantile, median, step_ms}: where the median settles once every follower has
    passed it -- the leaders' quantile at 1/(2 pi) at no delay -- and how far that is above the
    median at no delay, all messages of the part's zero-delay runs taken together. Only where the
    followers grow faster than the leaders: where every message grows alike, none passes another."""
    pi = leaders_share(runs)
    zero = at(runs, 0.0)
    leaders = [trip for run in zero for trip, rank in run["messages"] if rank == 0]
    every = [trip for run in zero for trip, _ in run["messages"]]
    faster = any(growth(run["backend"], run["ack_batch"], 1) > 1 for run in runs)
    if not faster or not pi or pi <= 0.5 or not leaders:
        return {"share": pi, "quantile": None, "median": None, "step_ms": None}
    q = _quantile(leaders, 0.5 / pi)
    m = statistics.median(every)
    return {"share": pi, "quantile": q, "median": m, "step_ms": q - m}


def recording(runs, share):
    """At each delay, how far the recorded runs sit from the unrecorded ones: all messages'
    median, the leaders' median, and the leaders' quantile the median settles on (1/(2 pi))."""
    found = {}
    for d in DELAYS:
        here = at(runs, d)
        sides = {}
        for side, flag in (("recorded", True), ("unrecorded", False)):
            mine = [run for run in here if run["recorded"] is flag]
            every = [trip for run in mine for trip, _ in run["messages"]]
            leaders = [trip for run in mine for trip, rank in run["messages"] if rank == 0]
            sides[side] = (every, leaders)
        if not all(sides[s][0] and sides[s][1] for s in sides) or not share or share <= 0.5:
            found["%g" % d] = None
            continue
        (a, la), (b, lb) = sides["recorded"], sides["unrecorded"]
        found["%g" % d] = {
            "median_ms": statistics.median(a) - statistics.median(b),
            "leaders_median_ms": statistics.median(la) - statistics.median(lb),
            "leaders_quantile_ms": _quantile(la, 0.5 / share) - _quantile(lb, 0.5 / share)}
    return found


def replayed_trips(run, costs, warmup_s=helper_waits.WARMUP_S):
    """Every measured message's trip in ms as the frozen replay of M-H2 gives it -- the same call
    m0_read.replayed_trip_ms makes, with each trip kept rather than their median -- or None."""
    if None in costs.values():
        return None
    sent = m0_read.sends(run["run_dir"])
    cycle = m0_read.read_cycle(run["run_dir"])
    transit = m0_read.transit_ms(run)
    if not sent or not cycle or transit is None:
        return None
    held = run["held_ms"] * 1e6
    half = transit * 1e6 / 2.0
    arrivals = [s + run["gotit_ms"] * 1e6 / 2.0 for s in sent]
    batch, count, block_ms = m0_read.redis_config(run["run_dir"])
    each = held if batch == 1 else 0.0
    stamped = m0_read.replay(arrivals, cycle[0][0], half, half, held, costs["within"] + each,
                             costs["onward"] + each, count=count,
                             wait_ns=block_ms * 1e6 if block_ms else None)
    cutoff = sent[0] + warmup_s * 1e9
    return [(done - s) / 1e6 for s, done in zip(sent, stamped) if s >= cutoff]


def replay_pinned(recorded):
    """[{run, delay_ms, at_smallest, median_is_smallest, others_median_ms}] for a Redis part's
    recorded runs: how many of the replayed trips are the replay's one smallest trip, whether its
    median is it, and the median of the trips it gives every other message."""
    costs = m0_read.zero_costs(recorded)
    rows = []
    for run in recorded:
        trips = replayed_trips(run, costs)
        if not trips:
            continue
        low = min(trips)
        others = [t for t in trips if t - low >= SAME_TRIP_MS]
        rows.append({"run": run["run"], "delay_ms": run["set_ms"],
                     "at_smallest": sum(1 for t in trips if t - low < SAME_TRIP_MS)
                     / float(len(trips)),
                     "median_is_smallest": statistics.median(trips) - low < SAME_TRIP_MS,
                     "others_median_ms": statistics.median(others) if others else None})
    return rows


def read_part(runs):
    """Everything this reads of one part (a backend, and for Redis an acknowledgement batch)."""
    share = leaders_share(runs)
    predicted = predicted_medians(at(runs, 0.0))
    measured = [(run["set_ms"], run["trip_ms"]) for run in runs]
    recorded = [run for run in runs if run["recorded"]]
    return {
        "runs": len(runs), "leaders_share": share,
        "slope": {"all": m0_read.slope(runs), "recorded": m0_read.slope(recorded),
                  "unrecorded": m0_read.slope([run for run in runs if not run["recorded"]]),
                  "predicted": _slope(predicted)},
        "median_trip_ms": {"measured": _mean_by_delay(measured),
                           "predicted": _mean_by_delay(predicted)},
        "step": step(runs), "recording": recording(runs, share),
        "replay": replay_pinned(recorded) if runs[0]["backend"] == "redis" else []}


def read(runs):
    """{part: its reading}, and the table by rank, for M0's counted runs."""
    runs = read_messages(runs)
    parts = m0_read.split(runs)
    return {"parts": dict((name, read_part(some)) for name, some in sorted(parts.items())),
            "by_rank": by_rank(runs)}


# --- the command ----------------------------------------------------------------------------------

def _r(value, places=6):
    return None if value is None else round(value, places)


def lines(found):
    out = ["M0 message by message (after M0's frozen reading; decides nothing)"]
    for name, part in found["parts"].items():
        slope = part["slope"]
        out.append("  %s: leaders %s of messages; slope measured %s (recorded %s, unrecorded %s), "
                   "predicted from the zero-delay runs %s%s"
                   % (name, _r(part["leaders_share"], 3), _r(slope["all"]),
                      _r(slope["recorded"]), _r(slope["unrecorded"]), _r(slope["predicted"]),
                      "" if part["step"]["step_ms"] is None
                      else "; the median settles %s ms above one-for-one"
                      % _r(part["step"]["step_ms"], 3)))
        pinned = part["replay"]
        if pinned:
            out.append("    frozen replay: median at its smallest trip in %d of %d recorded runs"
                       % (sum(1 for row in pinned if row["median_is_smallest"]), len(pinned)))
    return out


def write(found, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "m0_by_rank.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["part", "delay_ms", "rank", "messages",
                                           "median_trip_ms", "growth_per_ms", "rule"],
                           lineterminator="\n")
        w.writeheader()
        for row in found["by_rank"]:
            w.writerow(dict(row, median_trip_ms=_r(row["median_trip_ms"]),
                            growth_per_ms=_r(row["growth_per_ms"])))
    with open(os.path.join(out_dir, "m0_bursts.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(found["parts"], indent=2, sort_keys=True) + "\n")


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="M0 read message by message")
    ap.add_argument("--runs", required=True, help="M0's campaign folder of copied runs")
    ap.add_argument("--out", default="", help="write m0_by_rank.csv and m0_bursts.json here")
    args = ap.parse_args(argv)
    try:
        runs = m0_read.m0_runs(args.runs)
        if not runs:
            raise ValueError("no counted M0 run under %s" % args.runs)
        found = read(runs)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2
    if args.out:
        write(found, args.out)
    for line in lines(found):
        print(line, file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
