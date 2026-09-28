#!/usr/bin/env python3
"""
pause_census.py -- every pause the quality report counted, and what else stopped with it. Read on
28 September 2026, after the final judging (D32-1). It decides nothing and leaves no run out.

A pause is a message that arrived more than quality_report.STALL_MS (150 ms) after it was sent,
past the warm-up. The messages one pause holds are released together, so a run's late messages
are gathered into episodes: late messages released within a second of each other are one.

What else stopped, over each episode -- from the first late message's send to the last release:
  the producer    the longest wait from a message's scheduled time to its send, and the longest
                  "got it" (the broker's acknowledgement coming back), over the messages sent then;
  the sampler     util_sampler.py, a separate process on the driver that writes a line of its own
                  every half second: the longest gap between its lines across the episode;
  the broker      for Kafka, whether its log in that window shows the broker failing to send its
                  own controller a heartbeat.
And for each run, the CPU time the driver's processors spent idle while a task waited on the disk
(iowait, the fifth figure of /proc/stat's cpu line, read before and after the run, in 1/100 s).

Kinds of episode:
  broker     the acknowledgements were held as long as the deliveries: the longest got-it in the
             episode is at least half the episode's length;
  receiver   the acknowledgements came back as usual: the longest got-it stayed under the pause
             limit, so only the receiving side stopped;
  both       anything between.
For Redis, whether the receiving program was inside a read of the broker while it lay paused, from
its own trace of each read, is recorded too: a program waiting on the network sits inside a read.

CLI:
    python scripts/pause_census.py --root runs/azure/final_campaigns --out <folder>
"""
import argparse
import csv
import datetime
import glob
import json
import math
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quality_report  # noqa: E402

LIMIT_MS = quality_report.STALL_MS
WARMUP_S = 30.0
#: Late messages released this close together were held by one pause.
SAME_EPISODE_S = 1.0
#: An episode this long or longer is a long one; the sampler writes every half second, so a gap
#: longer than this is a sampler that stopped too.
LONG_S = 1.0
#: /proc/stat counts in USER_HZ, 100 a second on every Linux the pairs ran.
USER_HZ = 100.0
HEARTBEAT = re.compile(r"Unable to send a heartbeat|BROKER_HEARTBEAT|due to request timeout")
STAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?Z")


# --- one run --------------------------------------------------------------------------------------

def messages(run_dir):
    """[{sched, send, ack, arrival}] in ns for every message sent, arrival None where none came."""
    sent = []
    with open(os.path.join(run_dir, "producer.csv"), newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("t_prod_send_ns"):
                sent.append({"id": row.get("event_id"), "send": int(row["t_prod_send_ns"]),
                             "sched": int(row["t_prod_sched_ns"]) if row.get("t_prod_sched_ns")
                             else None,
                             "ack": int(row["t_broker_ack_ns"]) if row.get("t_broker_ack_ns")
                             else None})
    name = "consumer_events.csv"
    stamp = "t_consume_ns"
    if not os.path.exists(os.path.join(run_dir, name)):
        name, stamp = "consumer.csv", "t_cons_recv_ns"
    arrived = {}
    with open(os.path.join(run_dir, name), newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get(stamp):
                arrived[row.get("event_id")] = int(row[stamp])
    for msg in sent:
        msg["arrival"] = arrived.get(msg["id"])
    return sent


def episodes(sent, limit_ms=LIMIT_MS, warmup_s=WARMUP_S):
    """The run's pauses: [{start, end, worst_ms, late, max_lag_ms, max_gotit_ms}], each running
    from its first late message's send to its last release, over the messages sent after the
    warm-up; the producer's figures are over every message sent inside that span."""
    if not sent:
        return []
    cutoff = min(m["send"] for m in sent) + warmup_s * 1e9
    late = sorted((m for m in sent if m["send"] >= cutoff and m["arrival"] is not None
                   and (m["arrival"] - m["send"]) / 1e6 > limit_ms), key=lambda m: m["arrival"])
    found = []
    for m in late:
        if found and m["arrival"] - found[-1]["end"] < SAME_EPISODE_S * 1e9:
            ep = found[-1]
            ep.update(end=m["arrival"], late=ep["late"] + 1, start=min(ep["start"], m["send"]),
                      worst_ms=max(ep["worst_ms"], (m["arrival"] - m["send"]) / 1e6))
        else:
            found.append({"start": m["send"], "end": m["arrival"], "late": 1,
                          "worst_ms": (m["arrival"] - m["send"]) / 1e6})
    for ep in found:
        inside = [m for m in sent if ep["start"] <= m["send"] <= ep["end"]]
        lags = [(m["send"] - m["sched"]) / 1e6 for m in inside if m["sched"] is not None]
        acks = [(m["ack"] - m["send"]) / 1e6 for m in inside if m["ack"] is not None]
        ep["max_lag_ms"] = max(lags) if lags else None
        ep["max_gotit_ms"] = max(acks) if acks else None
    return found


def kind(ep, limit_ms=LIMIT_MS):
    """"broker", "receiver" or "both", by how long the acknowledgements were held."""
    held = ep["max_gotit_ms"] or 0.0
    if held >= 0.5 * ep["worst_ms"]:
        return "broker"
    return "receiver" if held < limit_ms else "both"


def sampler_gap_s(run_dir, start, end):
    """The longest gap in seconds between the sampler's lines that overlaps [start, end], or None
    where the sampler wrote nothing around it."""
    path = os.path.join(run_dir, "utilisation.csv")
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as fh:
        times = [float(row["t_wall"]) for row in csv.DictReader(fh) if row.get("t_wall")]
    lo, hi = start / 1e9, end / 1e9
    gaps = [b - a for a, b in zip(times, times[1:]) if b > lo and a < hi]
    return max(gaps) if gaps else None


def _cpu(path):
    with open(path, encoding="utf-8") as fh:
        return [int(x) for x in fh.read().split()[1:]]


def cpu_seconds(run_dir, field):
    """CPU-seconds of one of /proc/stat's cpu figures over the run -- 4 is the time processors
    waited idle on the disk (iowait), 7 the time other tenants took (steal) -- or None."""
    try:
        before = _cpu(os.path.join(run_dir, "stat_before.txt"))
        after = _cpu(os.path.join(run_dir, "stat_after.txt"))
        return (after[field] - before[field]) / USER_HZ
    except (OSError, ValueError, IndexError):
        return None


def iowait_s(run_dir):
    """CPU-seconds the driver's processors waited idle on the disk over the run, or None."""
    return cpu_seconds(run_dir, 4)


def _ns(match):
    when = datetime.datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(
        tzinfo=datetime.timezone.utc)
    return int(when.timestamp()) * 10 ** 9 + int(((match.group(2) or "") + "0" * 9)[:9])


def heartbeat_lost(run_dir, start, end):
    """Whether the broker's log, from a second before the episode to three after, shows the
    broker failing to heartbeat its controller."""
    path = os.path.join(run_dir, "broker_log.txt")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = STAMP.match(line)
            if m and HEARTBEAT.search(line) and start - 1e9 <= _ns(m) <= end + 3e9:
                return True
    return False


def inside_reads(run_dir, start, end):
    """The share of [start, end] the receiving program spent inside a read of the broker, from
    its own trace of each read; None where it kept none."""
    path = os.path.join(run_dir, "consumer_readtrace.csv")
    if not os.path.exists(path) or end <= start:
        return None
    covered = 0
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            a = int(row["t_read_start_ns"])
            b = a + int(row["read_duration_ns"])
            covered += max(0, min(b, end) - max(a, start))
    return covered / float(end - start)


# --- every run --------------------------------------------------------------------------------------

def paused_runs(campaign_dir):
    """{run: backend} for the runs the campaign's quality report found a pause in."""
    report = quality_report.read_json(os.path.join(campaign_dir, "quality_report.json"))
    return dict((r["run"], r.get("backend")) for r in report.get("runs", []) if r.get("stalls"))


def census(root):
    """(episodes, runs): every episode of every paused run, and every run with its iowait."""
    eps, runs = [], []
    for campaign_dir in sorted(glob.glob(os.path.join(root, "*", "*"))):
        report = os.path.join(campaign_dir, "quality_report.json")
        if not os.path.exists(report):
            continue
        pair, campaign = os.path.basename(os.path.dirname(campaign_dir)), \
            os.path.basename(campaign_dir)
        paused = paused_runs(campaign_dir)
        for run_dir in quality_report.run_dirs_under(os.path.join(campaign_dir, "runs")):
            run = os.path.basename(run_dir)
            found = []
            if run in paused:
                for ep in episodes(messages(run_dir)):
                    ep.update(pair=pair, campaign=campaign, run=run, backend=paused[run],
                              kind=kind(ep), sampler_gap_s=sampler_gap_s(run_dir, ep["start"],
                                                                         ep["end"]),
                              heartbeat_lost=heartbeat_lost(run_dir, ep["start"], ep["end"]),
                              inside_reads=inside_reads(run_dir, ep["start"], ep["end"]))
                    found.append(ep)
            eps += found
            runs.append({"pair": pair, "campaign": campaign, "run": run,
                         "iowait_s": iowait_s(run_dir), "steal_s": cpu_seconds(run_dir, 7),
                         "paused": bool(found),
                         "receiver_paused_s": sum(ep["worst_ms"] for ep in found
                                                  if ep["kind"] == "receiver") / 1000.0})
    return eps, runs


# --- what they add up to -----------------------------------------------------------------------------

def rayleigh_p(minutes):
    """The Rayleigh test's p-value that times of the hour are spread evenly round the clock
    (Zar's approximation), and the mean minute."""
    n = len(minutes)
    c = sum(math.cos(2 * math.pi * m / 60.0) for m in minutes)
    s = sum(math.sin(2 * math.pi * m / 60.0) for m in minutes)
    z = (c * c + s * s) / n
    p = math.exp(-z) * (1 + (2 * z - z * z) / (4 * n)
                        - (24 * z - 132 * z ** 2 + 76 * z ** 3 - 9 * z ** 4) / (288 * n * n))
    return min(1.0, max(0.0, p)), (math.degrees(math.atan2(s, c)) % 360.0) / 6.0


def _minute(ns):
    when = datetime.datetime.fromtimestamp(ns / 1e9, datetime.timezone.utc)
    return when.minute + when.second / 60.0


def _line(xs, ys):
    """(slope, correlation) of ys on xs."""
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / sxx, sxy / math.sqrt(sxx * syy)


def summary(eps, runs):
    out = {"episodes": {}, "runs_with_a_pause": {}, "runs": {}}
    for ep in eps:
        key = "%s, %s, %s" % (ep["pair"], ep["backend"], ep["kind"])
        out["episodes"][key] = out["episodes"].get(key, 0) + 1
    for run in runs:
        out["runs"][run["pair"]] = out["runs"].get(run["pair"], 0) + 1
        if run["paused"]:
            out["runs_with_a_pause"][run["pair"]] = out["runs_with_a_pause"].get(run["pair"], 0) + 1
    stolen = [run["steal_s"] for run in runs if run.get("steal_s") is not None]
    out["steal"] = {"runs_read": len(stolen), "most_s": max(stolen) if stolen else None}
    by_kind = {}
    for ep in eps:
        by_kind.setdefault(ep["kind"], []).append(ep)
    out["kinds"] = {}
    for name, some in sorted(by_kind.items()):
        durations = sorted(ep["worst_ms"] for ep in some)
        long = [ep for ep in some if ep["worst_ms"] >= LONG_S * 1000]
        timed = [ep for ep in long if ep["sampler_gap_s"] is not None]
        out["kinds"][name] = {
            "episodes": len(some), "median_ms": statistics.median(durations),
            "longest_ms": durations[-1], "long": len(long),
            "long_with_the_sampler_stopped": sum(1 for ep in timed
                                                 if ep["sampler_gap_s"] > LONG_S),
            "long_with_the_sampler_timed": len(timed),
            "backends": sorted(set(ep["backend"] for ep in some))}
    broker = [ep for ep in eps if ep["kind"] == "broker"]
    out["heartbeat_lost"] = dict(
        (band, [sum(1 for ep in broker if lo <= ep["worst_ms"] < hi and ep["heartbeat_lost"]),
                sum(1 for ep in broker if lo <= ep["worst_ms"] < hi)])
        for band, lo, hi in (("under 1 s", 0, 1000), ("1 to 3 s", 1000, 3000),
                             ("3 s or more", 3000, float("inf"))))
    reads = [ep["inside_reads"] for ep in eps if ep["kind"] == "receiver"
             and ep["backend"] == "redis" and ep["inside_reads"] is not None
             and ep["worst_ms"] >= 500]
    out["redis_receiver_inside_reads"] = {"episodes": len(reads),
                                          "most_inside": max(reads) if reads else None}
    long_paused = [r for r in runs if r["receiver_paused_s"] >= LONG_S and r["iowait_s"] is not None]
    quiet = [r["iowait_s"] for r in runs if not r["paused"] and r["iowait_s"] is not None]
    out["iowait"] = {}
    for pair in sorted(set(r["pair"] for r in runs)):
        mine = [r["iowait_s"] for r in long_paused if r["pair"] == pair]
        still = [r["iowait_s"] for r in runs if r["pair"] == pair and not r["paused"]
                 and r["iowait_s"] is not None]
        out["iowait"][pair] = {"paused_runs": len(mine),
                               "paused_median_s": statistics.median(mine) if mine else None,
                               "quiet_runs": len(still),
                               "quiet_median_s": statistics.median(still) if still else None}
    if len(long_paused) >= 3:
        slope, r = _line([x["receiver_paused_s"] for x in long_paused],
                         [x["iowait_s"] for x in long_paused])
        out["iowait_on_pause"] = {"runs": len(long_paused), "slope": slope, "correlation": r,
                                  "quiet_median_s": statistics.median(quiet) if quiet else None}
    longest = {}
    for ep in eps:
        if ep["kind"] == "receiver" and ep["worst_ms"] >= LONG_S * 1000:
            key = (ep["pair"], ep["run"])
            if key not in longest or ep["worst_ms"] > longest[key]["worst_ms"]:
                longest[key] = ep
    minutes = [_minute(ep["start"]) for ep in longest.values()]
    if minutes:
        p, mean = rayleigh_p(minutes)
        out["hour"] = {"runs": len(minutes),
                       "by_quarter": [sum(1 for m in minutes if 15 * q <= m < 15 * (q + 1))
                                      for q in range(4)],
                       "rayleigh_p": p, "mean_minute": mean}
    return out


# --- the command --------------------------------------------------------------------------------------

FIELDS = ["pair", "campaign", "run", "backend", "kind", "start_utc", "worst_ms", "late",
          "max_lag_ms", "max_gotit_ms", "sampler_gap_s", "heartbeat_lost", "inside_reads"]


def _utc(ns):
    return datetime.datetime.fromtimestamp(ns / 1e9, datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _r(value, places=6):
    return round(value, places) if isinstance(value, float) else value


def write(eps, runs, found, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "pause_episodes.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for ep in sorted(eps, key=lambda e: (e["pair"], e["start"])):
            w.writerow(dict((k, _r(ep.get(k))) for k in FIELDS if k != "start_utc")
                       | {"start_utc": _utc(ep["start"])})
    with open(os.path.join(out_dir, "pause_runs.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["pair", "campaign", "run", "iowait_s", "steal_s",
                                           "paused", "receiver_paused_s"], lineterminator="\n")
        w.writeheader()
        for run in runs:
            w.writerow(dict((k, _r(v)) for k, v in run.items()))
    with open(os.path.join(out_dir, "pause_summary.json"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(json.dumps(found, indent=2, sort_keys=True) + "\n")


def lines(found):
    out = ["Pauses: every episode the quality report's late messages make up"]
    for name, k in found["kinds"].items():
        out.append("  %s: %d episodes (%s), median %.0f ms, longest %.0f ms; of %d of a second "
                   "or more with the sampler running, it stopped too in %d"
                   % (name, k["episodes"], ", ".join(k["backends"]), k["median_ms"],
                      k["longest_ms"], k["long_with_the_sampler_timed"],
                      k["long_with_the_sampler_stopped"]))
    for pair, w in found["iowait"].items():
        out.append("  %s: iowait %s s in runs paused a second or more (%d), %s s in runs with no "
                   "pause (%d)" % (pair, _r(w["paused_median_s"], 2), w["paused_runs"],
                                   _r(w["quiet_median_s"], 2), w["quiet_runs"]))
    return out


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Every pause, and what else stopped with it")
    ap.add_argument("--root", required=True, help="a folder of <pair>/<campaign>/runs folders")
    ap.add_argument("--out", default="", help="write the episodes, runs and summary here")
    args = ap.parse_args(argv)
    try:
        eps, runs = census(args.root)
        if not runs:
            raise ValueError("no campaign with a quality report under %s" % args.root)
        found = summary(eps, runs)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2
    if args.out:
        write(eps, runs, found, args.out)
    for line in lines(found):
        print(line, file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
