#!/usr/bin/env python3
"""
run_integrity.py -- right after a run: does it count, is it repeated, or does the campaign stop?

The experiment plan fixes these rules before any run. cloud/azure/campaign.sh applies them to each
run as it ends, on the machine that ran it, so they hold when nobody is watching.

  count    every check passed. The run enters the analysis.
  repeat   a condition the run was meant to have did not take: too few messages sent, or too few
           of them arrived; the send rate or the load off target; the settings changed during the
           run; the delay the broker held not the delay set, or its capture missing; the clock
           not logged; the client not set as every
           campaign sets it (Kafka's producer with 64 requests in flight, Redis's consumer
           acknowledging in batches of 200, each read from the client's own log line); files
           that cannot be read. The
           run keeps its files and its ledger row, marked failed with the reasons, and
           run_queue.py queues a copy, three attempts at most. Nothing a run measured can make it
           a repeat.
  stop     the instrument is in doubt: a message arrived before it was sent, or the "got it"
           median moved by more than a quarter of the added delay from the session's zero-delay
           median. The run is recorded as failed and the campaign stops.

`guard` reads the queue's ledger after every attempt and stops the campaign when attempts keep
failing: the last three all failed, or more than a fifth of the last twenty did, once ten have
finished.

Every check, with the value found and the limit it was held to, is written to
RUN_DIR/integrity.json, next to the run. Recorded beside the checks, and never judged: what ping made of
the added delay, and the TCP segments each side sent again during the run (the Tcp lines of
/proc/net/snmp, before and after, on the driver, in the receiver's namespace and on the broker),
which is where a stall of a fraction of a second would show.

CLI:
    python3 scripts/run_integrity.py check RUN_DIR --rate 50 --duration 130 --warmup-s 30
        [--calibration runs/azure/calibration.json]
    python3 scripts/run_integrity.py show RUN_DIR
    python3 scripts/run_integrity.py guard --queue runs/azure/queues/a1.csv
Exit codes: check 0 count, 1 repeat, 3 stop, 2 error. guard 0 carry on, 3 stop, 2 error.
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import delay_calibration  # noqa: E402
import pilot_checks  # noqa: E402
import run_queue  # noqa: E402

#: At least this share of the planned messages is sent after the warm-up, and this share of those
#: arrives.
MESSAGE_SHARE = 0.99
#: The send rate after the warm-up, as a share of the target either way.
RATE_TOLERANCE = 0.02
#: The measured load while messages are sent, in percentage points either way.
LOAD_POINTS = 3.0
#: Fewer utilisation samples than this inside the run cannot say what its load was.
MIN_LOAD_SAMPLES = 10
#: The delay the broker's own capture shows it held may differ from the one set by this much
#: (plan v7). It is read where the delay is added, and on three machine pairs it came within
#: 0.022 ms. Ping is kept as a record: on 17 September it read 0.4 to 0.5 ms above the round trip
#: our messages take, with a 90th percentile of 3 to 4 ms against TCP's 0.5.
DELAY_TOLERANCE_MS = 0.05
#: The client settings every campaign run uses (plan v6): the log that states it, the setting,
#: and its value.
CLIENT_SETTINGS = {"kafka": ("producer.log", "max_inflight", 64),
                   "redis": ("consumer.log", "ack_batch", 200)}
#: Where each side's Tcp counters are logged, by file-name prefix.
TCP_SIDES = {"driver": "", "receiver": "receiver_", "broker": "broker_"}
#: The guard: failed attempts in a row, and the share failed among the most recent ones.
GUARD_IN_A_ROW = 3
GUARD_WINDOW = 20
GUARD_MIN_FINISHED = 10
GUARD_SHARE = 0.20

COUNT, REPEAT, STOP = "count", "repeat", "stop"
EXIT = {COUNT: 0, REPEAT: 1, STOP: 3}
#: The checks whose failure puts the instrument in doubt. Any other failure is a repeat.
STOP_CHECKS = ("never_negative", "gotit_steady")
FINISHED = ("done", "failed", "abandoned")


def outcome(ok, value, limit, why):
    """One check: whether it passed, what was found, what was allowed, and why it failed."""
    return {"ok": bool(ok), "value": value, "limit": limit, "why": "" if ok else why}


def read_json(path):
    """A JSON file's contents. A missing or broken file is a ValueError that names it."""
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        raise ValueError("%s cannot be read (%s)" % (name, exc)) from exc
    except ValueError as exc:
        raise ValueError("%s is not valid JSON" % name) from exc


def _ns(value):
    return int(value) if value not in (None, "", "None") else None


def send_times(run_dir):
    """Every send time producer.csv holds, in nanoseconds since the epoch, in order."""
    times = []
    with open(os.path.join(run_dir, "producer.csv"), newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sent = _ns(row.get("t_prod_send_ns"))
            if sent is not None:
                times.append(sent)
    if not times:
        raise ValueError("producer.csv holds no send times")
    return sorted(times)


def message_checks(sent_after, received, rate, duration, warmup_s):
    """Enough of the planned messages sent after the warm-up, and enough of those arrived."""
    planned = rate * (duration - warmup_s)
    sent = len(sent_after)
    least_sent = MESSAGE_SHARE * planned
    checks = {"messages_sent": outcome(
        sent >= least_sent, sent, "at least %.0f" % least_sent,
        "%d messages were sent after the warm-up, fewer than %.0f%% of the %.0f planned"
        % (sent, 100 * MESSAGE_SHARE, planned))}
    least_received = MESSAGE_SHARE * sent
    checks["messages_received"] = outcome(
        sent > 0 and received >= least_received, received, "at least %.0f" % least_received,
        "%d of the %d messages sent after the warm-up arrived" % (received, sent))
    return checks


def rate_check(sent_after, rate):
    low, high = rate * (1 - RATE_TOLERANCE), rate * (1 + RATE_TOLERANCE)
    limit = "%.2f to %.2f a second" % (low, high)
    span_s = (sent_after[-1] - sent_after[0]) / 1e9 if len(sent_after) > 1 else 0.0
    if span_s <= 0:
        return outcome(False, None, limit, "too few distinct send times to measure the send rate")
    achieved = (len(sent_after) - 1) / span_s
    return outcome(low <= achieved <= high, achieved, limit,
                   "messages were sent at %.2f a second against %g" % (achieved, rate))


def load_check(run_dir, load_pct, first_ns, last_ns):
    """The mean measured load while messages were being sent, against the setting."""
    samples = []
    with open(os.path.join(run_dir, "utilisation.csv"), newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                at, rho = float(row["t_wall"]), float(row["rho"])
            except (KeyError, TypeError, ValueError):
                continue
            if first_ns <= at * 1e9 <= last_ns:
                samples.append(100.0 * rho)
    limit = "%g%% within %g points, from at least %d samples" % (load_pct, LOAD_POINTS,
                                                                  MIN_LOAD_SAMPLES)
    if len(samples) < MIN_LOAD_SAMPLES:
        return outcome(False, None, limit,
                       "only %d load samples fell while messages were sent" % len(samples))
    mean = statistics.mean(samples)
    return outcome(abs(mean - load_pct) <= LOAD_POINTS, mean, limit,
                   "the measured load was %.1f%% against %g%%" % (mean, load_pct))


def settings_check(run_dir):
    after = read_json(os.path.join(run_dir, "settings_after.json"))
    problems = after.get("problems") or []
    return outcome(after.get("ok") is True, problems, "the settings as the run set them",
                   "the settings changed during the run: %s"
                   % ("; ".join(problems) or "sched_settings.py gave no reason"))


def _path_difference(found):
    return float(found["receiver_median_ms"]) - float(found["host_median_ms"])


def delay_check(run_dir, delay_ms):
    """(the check, the added delay the broker held).

    Read from the broker's own capture of the run's delay pings: how much longer it held the
    replies to the receiver than the replies to the host. That is the treatment itself, measured
    where it is applied, to a few microseconds. Ping is recorded beside it and judges nothing: it
    reads about half a millisecond above the round trip our messages take, its 90th percentile is
    several times theirs, and in the receiver's namespace it invents a difference of 0.28 ms that
    TCP does not have. A run whose capture is missing is repeated, not taken on trust.
    """
    held = read_json(os.path.join(run_dir, "delay_hold.json"))
    try:
        added = float(held["receiver_hold_ms"]) - float(held["host_hold_ms"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("delay_hold.json lacks the two holds") from exc
    check = outcome(abs(added - delay_ms) <= DELAY_TOLERANCE_MS, added,
                    "%g ms within %.3f ms" % (delay_ms, DELAY_TOLERANCE_MS),
                    "the broker held %.3f ms against %g ms set" % (added, delay_ms))
    return check, added


def delay_by_ping_ms(run_dir):
    """What ping made of the run's added delay: the receiver's round trip minus the host's, less
    that same difference with no delay just before (delay_baseline.json). Recorded, never judged
    (plan v7); None when the files are missing or short."""
    try:
        measured = read_json(os.path.join(run_dir, "delay_measured.json"))
        added = _path_difference(measured)
        baseline_path = os.path.join(run_dir, "delay_baseline.json")
        if os.path.exists(baseline_path):
            added -= _path_difference(read_json(baseline_path))
        return added
    except (ValueError, KeyError, TypeError):
        return None


def client_check(run_dir, backend):
    """The client ran with the campaign's setting, as its own log line states it."""
    log_name, key, wanted = CLIENT_SETTINGS[backend]
    found = None
    pattern = re.compile(r"CONFIG effective .*\b%s=(\d+)" % key)
    with open(os.path.join(run_dir, log_name), encoding="utf-8", errors="replace") as fh:
        for line in fh:
            match = pattern.search(line)
            if match:
                found = int(match.group(1))
    return outcome(found == wanted, found, "%s=%d in %s" % (key, wanted, log_name),
                   "the %s client ran with %s=%s, not %d"
                   % (backend, key, "an unlogged value" if found is None else found, wanted))


def retransmitted(run_dir, side):
    """TCP segments one side sent again during the run; None when its counters were not logged."""
    counts = []
    for when in ("before", "after"):
        try:
            with open(os.path.join(run_dir, "%stcp_%s.txt" % (TCP_SIDES[side], when)),
                      encoding="utf-8") as fh:
                names, values = [line.split() for line in fh if line.startswith("Tcp:")][:2]
            counts.append(int(values[names.index("RetransSegs")]))
        except (OSError, ValueError):
            return None
    return counts[1] - counts[0]


def clock_offset_s(path):
    """chrony's clock offset in seconds, from one `chronyc -c tracking` line, or None."""
    try:
        with open(path, encoding="utf-8") as fh:
            return float(fh.readline().split(",")[4])
    except (OSError, IndexError, ValueError):
        return None


def clock_check(run_dir):
    offsets = [clock_offset_s(os.path.join(run_dir, name))
               for name in ("clock_before.txt", "clock_after.txt")]
    logged = [abs(v) for v in offsets if v is not None]
    return outcome(len(logged) == 2, max(logged) if logged else None, "logged before and after",
                   "the clock offset was not logged %s"
                   % ("on one side of the run" if logged else "before or after the run"))


def steal_pct(run_dir):
    """CPU time other tenants took during the run, in per cent, from two /proc/stat lines."""
    lines = []
    for name in ("stat_before.txt", "stat_after.txt"):
        try:
            with open(os.path.join(run_dir, name), encoding="utf-8") as fh:
                lines.append([int(v) for v in fh.readline().split()[1:9]])
        except (OSError, ValueError):
            return None
    delta = [after - before for before, after in zip(*lines)]
    if len(delta) < 8 or sum(delta) <= 0:
        return None
    return 100.0 * delta[7] / sum(delta)


def never_negative_check(summary):
    negative = summary["trip_negative"]
    return outcome(negative == 0, negative, "none",
                   "%d message(s) arrived before they were sent" % negative)


def gotit_checks(summary, params, added_ms, calibration):
    """The run's "got it" median against its session's zero-delay median.

    Empty when there is nothing to hold it against: no calibration, or no added delay.
    """
    if calibration is None or float(params.get("delay_ms") or 0) <= 0:
        return {}
    try:
        entry = calibration["calibration"][params["backend"]][str(params["load_pct"])]
        zero = entry["gotit_zero_median_ms"]
    except (KeyError, TypeError):
        zero = None
    why = None
    if zero is None:
        why = ("the calibration has no zero-delay got-it median for %s at %s%%"
               % (params.get("backend"), params.get("load_pct")))
    elif summary.get("gotit_median_ms") is None:
        why = "the run recorded no got-it times"
    elif added_ms is None:
        why = "the added delay was not measured"
    if why:
        return {"gotit_compared": outcome(False, None, "a zero-delay median and this run's", why)}
    shift = summary["gotit_median_ms"] - zero
    limit = delay_calibration.GROSS_SHARE * abs(added_ms)
    return {"gotit_steady": outcome(
        abs(shift) <= limit, shift, "within %.3f ms" % limit,
        "the got-it median moved %.3f ms, more than %.0f%% of the %.3f ms added"
        % (shift, 100 * delay_calibration.GROSS_SHARE, added_ms))}


def guarded(checks, name, compute):
    """Run one check, turning a file it cannot read into a failed check that says so."""
    try:
        checks[name] = compute()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        checks[name] = outcome(False, None, None, "the %s could not be checked: %s" % (name, exc))


def verdict(run_dir, checks, recorded):
    failed = [name for name, check in checks.items() if not check["ok"]]
    stops = [name for name in failed if name in STOP_CHECKS]
    kind = STOP if stops else (REPEAT if failed else COUNT)
    ordered = stops + [name for name in failed if name not in stops]
    return {"run_dir": run_dir, "verdict": kind, "reasons": [checks[n]["why"] for n in ordered],
            "checks": checks, "recorded": recorded}


def evaluate(run_dir, rate, duration, warmup_s, calibration=None,
             summarise=pilot_checks.summarise):
    """Every check on one run, and the verdict they give."""
    if rate <= 0 or duration <= warmup_s:
        raise ValueError("a run needs a positive rate and a duration longer than its warm-up")
    checks, recorded = {}, {"steal_pct": steal_pct(run_dir),
                            "delay_added_by_ping_ms": delay_by_ping_ms(run_dir),
                            "retransmitted": {side: retransmitted(run_dir, side)
                                              for side in TCP_SIDES}}
    try:
        params = read_json(os.path.join(run_dir, "queue_row.json"))["params"]
        sent = send_times(run_dir)
        summary = summarise(run_dir, warmup_s)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        checks["run_files"] = outcome(False, None, "readable",
                                      "the run's files could not be read: %s" % exc)
        return verdict(run_dir, checks, recorded)
    cutoff = sent[0] + int(warmup_s * 1e9)
    sent_after = [t for t in sent if t >= cutoff]
    recorded.update(messages=summary["messages"], trip_median_ms=summary["trip_median_ms"],
                    gotit_median_ms=summary.get("gotit_median_ms"),
                    gotit_p99_ms=summary.get("gotit_p99_ms"),
                    measured_negative_rate=summary.get("measured_negative_rate"))
    checks["never_negative"] = never_negative_check(summary)
    checks.update(message_checks(sent_after, summary["messages"], rate, duration, warmup_s))
    checks["send_rate"] = rate_check(sent_after, rate)
    window = (sent_after[0], sent_after[-1]) if sent_after else (cutoff, cutoff)
    guarded(checks, "load", lambda: load_check(run_dir, float(params["load_pct"]), *window))
    guarded(checks, "settings", lambda: settings_check(run_dir))
    guarded(checks, "client", lambda: client_check(run_dir, params["backend"]))
    added = None
    try:
        checks["delay"], added = delay_check(run_dir, float(params["delay_ms"]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        checks["delay"] = outcome(False, None, None, "the delay could not be checked: %s" % exc)
    recorded["delay_held_ms"] = added
    checks["clock"] = clock_check(run_dir)
    recorded["clock_offset_max_s"] = checks["clock"]["value"]
    checks.update(gotit_checks(summary, params, added, calibration))
    return verdict(run_dir, checks, recorded)


def guard(rows):
    """(stop, why) from a queue's ledger, reading attempts in the order they finished."""
    finished = sorted((r for r in rows if r["status"] in FINISHED and r["finished_utc"]),
                      key=lambda r: r["finished_utc"])
    failed = [r["status"] != "done" for r in finished]
    if len(failed) >= GUARD_IN_A_ROW and all(failed[-GUARD_IN_A_ROW:]):
        return True, ("the last %d attempts all failed; the latest because: %s"
                      % (GUARD_IN_A_ROW, finished[-1]["reason"] or "no reason was recorded"))
    recent = failed[-GUARD_WINDOW:]
    if len(finished) >= GUARD_MIN_FINISHED and sum(recent) > GUARD_SHARE * len(recent):
        return True, ("%d of the last %d attempts failed, more than %.0f%%"
                      % (sum(recent), len(recent), 100 * GUARD_SHARE))
    return False, "%d attempts finished, %d of them failed" % (len(finished), sum(failed))


def show(run_dir):
    """One line about a run's verdict, for the watch."""
    found = read_json(os.path.join(run_dir, "integrity.json"))
    return json.dumps({"run_dir": run_dir, "verdict": found.get("verdict"),
                       "reasons": found.get("reasons") or []}, sort_keys=True)


def main(argv=None, out=None, summarise=pilot_checks.summarise):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Does a run count, repeat, or stop its campaign?")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check")
    p.add_argument("run_dir")
    p.add_argument("--rate", type=float, required=True, help="messages a second, as planned")
    p.add_argument("--duration", type=float, required=True, help="seconds, as planned")
    p.add_argument("--warmup-s", type=float, default=30.0)
    p.add_argument("--calibration", default="", help="the session's delay_calibration.py fit")
    p = sub.add_parser("show")
    p.add_argument("run_dir")
    p = sub.add_parser("guard")
    p.add_argument("--queue", required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == "guard":
            stop, why = guard(run_queue.read_queue(args.queue))
            print(why, file=out)
            return EXIT[STOP] if stop else 0
        if args.command == "show":
            print(show(args.run_dir), file=out)
            return 0
        calibration = read_json(args.calibration) if args.calibration else None
        result = evaluate(args.run_dir, args.rate, args.duration, args.warmup_s, calibration,
                          summarise)
        with open(os.path.join(args.run_dir, "integrity.json"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        line = ("%s: %s" % (result["verdict"], "; ".join(result["reasons"]))
                if result["reasons"] else result["verdict"])
        print(line, file=out)
        return EXIT[result["verdict"]]
    except (OSError, ValueError, KeyError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
