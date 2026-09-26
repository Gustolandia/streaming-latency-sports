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
           median moved from the session's zero-delay median by more than a quarter of the added
           delay and by more than the session's own got-it noise -- GOTIT_FLOOR_MS, the plan's
           equivalence margin, or three times the scatter of its zero-delay runs, whichever is
           larger. A brake below that noise would stop a session for standing still. The run is
           recorded as failed and the campaign stops.

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
#: Except where the setup itself asks for something else. A8 takes the got-it note two ways, and
#: taking it inline forces one request in flight: above one, the blocking wait resolves an older
#: event and the stamp would belong to a different message, so both clients refuse. A run that
#: asked for inline and then reported 64 would be the fault this check exists to catch, and one
#: that asked for inline and reported 1 is doing as it was told (D4-9).
INLINE_MAX_INFLIGHT = 1
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


def message_checks(sent_after, received, rate, duration, warmup_s, planned=None):
    """Enough of the planned messages sent after the warm-up, and enough of those arrived.

    `planned` is given where the plan states its count outright. M0 replays the football match
    in bursts, and a burst's count is the plan's own events in the window, not a rate times a
    time (D29-1); every other campaign sends steadily and leaves it to the arithmetic.
    """
    planned = rate * (duration - warmup_s) if planned is None else planned
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


def client_check(run_dir, backend, ack_stamp=None, ack_batch=None):
    """The client ran with the setting this setup asked for, as its own log line states it.

    M0 acknowledges Redis messages one at a time as well as in batches of 200, the intervention
    on M-H2 (S0-2, D29-1), so a Redis setup that names its batch is held to that batch."""
    log_name, key, wanted = CLIENT_SETTINGS[backend]
    if backend == "kafka" and ack_stamp == "inline":
        wanted = INLINE_MAX_INFLIGHT
    if backend == "redis" and ack_batch:
        wanted = int(ack_batch)
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


#: The brake on the got-it median never sits below this, nor below this many times the scatter
#: the campaign itself showed.
#:
#: It was 0.10, the plan's own equivalence margin for P5(c), and that margin is the right size
#: for the question P5(c) asks -- whether the added delay moved the got-it -- and the wrong size
#: for this one, which is whether the instrument broke mid-campaign. Within-campaign drift has
#: now been measured on two sound campaigns: A8 moved 0.124 ms on the Arm pair and 0.134 on the
#: x86 pair, both over hours, both with nothing else wrong.
#:
#: The x86 stop is the one to read closely, because it was not the floor that bit. The campaign's
#: own pooled scatter put the allowance at 0.132 ms and the move was 0.134: an eight-hour
#: campaign stopped at 86 of 144 runs, after four earlier stops, on an overshoot of two
#: microseconds. That is the real fault in setting this from the campaign's own scatter alone --
#: three times a very tight scatter is a very tight allowance, and A8's within-setup scatter is
#: 0.012 to 0.036 ms. The floor is what stops the allowance collapsing onto the noise, and at
#: 0.10 it was below the drift sound campaigns show, so it never did that job.
#:
#: Nothing is given up by raising it. Every run's got-it median, its distance from its setup's
#: centre and its distance from the session's calibration are written beside it either way
#: (D17-3), so P5(c) is judged from the calibration exactly as before, on the same numbers.
#: What changes is only whether a campaign is allowed to finish.
GOTIT_FLOOR_MS = 0.25
GOTIT_NOISE_SHARE = 3.0
#: How many earlier counted runs of the same setup the brake needs before it can judge one
#: (plan version 17, D17-1). Below this a run's got-it is recorded and not braked: a comparison
#: against one other run is a comparison against that run's noise as much as against this one's.
GOTIT_MIN_EARLIER = 2
#: How much the pooled scatter must rest on before the brake uses it (plan version 18, D18-2):
#: one degree of freedom for each counted run beyond the first in every setup. Below this a run
#: is recorded and not braked.
#:
#: Version 17 took the scatter from the judged setup's own earlier runs, which on the first
#: braked run of a setup means two points and one degree of freedom -- not an estimate of spread.
#: A2's first session gave ten within-setup scatters from 0.053 to 0.227 ms around a pooled
#: 0.133, and was stopped by the 0.053 on a run 0.275 from its centre. The scatter belongs to the
#: sitting, so it is pooled; the centre stays the setup's own, so no other sitting's drift enters.
GOTIT_MIN_POOL_DF = 5
#: A queue key: the round, the setup, and which attempt at it. The setup is everything the brake
#: needs to hold like against like -- the client, where the note is taken, the slice and the
#: delay -- so two keys with the same middle are two runs of the same thing.
SETUP_KEY = re.compile(r"^r(?P<round>\d+)-(?P<setup>.+)-a(?P<attempt>\d+)$")

#: Where a calibration takes its "got it" note. Stage 0 calibrates with the client's own
#: defaults and never passes --ack-stamp, and the clients default to the callback, so every
#: calibration this plan takes is a callback one. test_azure_kit holds stage 0 to that.
CALIBRATED_AT = "callback"


def gotit_comparable(params):
    """Whether this run takes its "got it" note the way the calibration took it.

    A8 varies where the note is taken, and taking it inline forces the producer to one message
    in flight where the calibration ran with sixty-four. Those are two different producers on
    purpose: it is the treatment A8 exists to measure. Holding such a run against the
    calibration's median asks what that treatment did, not what the added delay did -- and
    P5(c) asks only the second.

    On the Arm pair on 20 September this stopped A8 on its first Python run. The got-it median
    sat 0.167 ms from the calibration's where the brake allowed 0.145, and what moved it was the
    note's place, not the delay: the Java runs, whose inline and callback medians happen to lie
    0.06 ms apart, sailed through the same brake. A rule that stops one client and not the other
    for a difference neither of them was asked about is not a check on the instrument.
    """
    return (params.get("ack_stamp") or CALIBRATED_AT) == CALIBRATED_AT


def calibration_entry(calibration, params):
    """The fit this run's got-it median is held against, for its backend and load.

    A session that opens A8 fits one calibration per client and joins them under the client's
    name, because the delay's effect on the trip belongs to the client and the two fits are not
    interchangeable. Its file is therefore a level deeper than every other session's. Reading it
    as though it were flat finds no entry at all, and a missing entry is a repeat -- so a whole
    A8 campaign would run twice and the second time would fail in exactly the same way.

    So the client's own fit is taken where the file has one, and the flat shape otherwise.
    Neither is assumed: a run that matches neither is reported as having no entry, which is what
    the caller turns into a stated reason.
    """
    fit = (calibration or {}).get("calibration")
    if not isinstance(fit, dict):
        return None
    where = [(params.get("backend"), str(params.get("load_pct")))]
    if params.get("language"):
        where.insert(0, (params["language"], params.get("backend"), str(params.get("load_pct"))))
    for path in where:
        node = fit
        for step in path:
            node = node.get(step) if isinstance(node, dict) else None
        if isinstance(node, dict) and node.get("gotit_zero_median_ms") is not None:
            return node
    return None


def setup_of(key):
    """(round, setup, attempt) from a queue key, or None if it is not one."""
    found = SETUP_KEY.match(key or "")
    if not found:
        return None
    return (int(found.group("round")), found.group("setup"), int(found.group("attempt")))


def _campaign_runs(run_dir):
    """((round, setup, attempt) for this run, and the same plus the got-it for its campaign's).

    One walk of the folder for the two things the brake needs: the judged setup's own earlier
    runs, which give the centre, and every setup's runs, which give the pooled scatter. Only
    runs that counted, and only this campaign's -- a run directory is law_<campaign>_<key>, so
    what is left after the key is the campaign, and A2 runs each kernel with each backend on two
    different days, carrying the same keys on another boot behind another calibration.
    """
    try:
        key = read_json(os.path.join(run_dir, "queue_row.json")).get("key")
        mine = setup_of(key)
    except (OSError, ValueError, AttributeError):
        return None, []
    if mine is None:
        return None, []
    here = os.path.abspath(run_dir)
    parent = os.path.dirname(here)
    campaign = os.path.basename(here)[:-len(key)]
    rows = []
    for name in sorted(os.listdir(parent)):
        other = os.path.join(parent, name)
        if os.path.abspath(other) == here or not os.path.isdir(other):
            continue
        try:
            their_key = read_json(os.path.join(other, "queue_row.json")).get("key")
            theirs = setup_of(their_key)
            judged = read_json(os.path.join(other, "integrity.json"))
        except (OSError, ValueError, AttributeError):
            continue
        if theirs is None or name[:-len(their_key)] != campaign:
            continue
        if judged.get("verdict") != "count":
            continue
        median = (judged.get("recorded") or {}).get("gotit_median_ms")
        if median is not None:
            rows.append(theirs + (median,))
    return mine, rows


def campaign_spread(run_dir):
    """(the got-it scatter pooled over this campaign's setups, the degrees of freedom behind it).

    Every counted run's distance from its own setup's centre, taken together (plan version 18,
    D18-1). Run-to-run scatter in the got-it belongs to the sitting, not to one setup: A2's first
    session gave ten within-setup figures from 0.053 to 0.227 ms around a pooled 0.133, which is
    one quantity seen through two or three points each. Taking it from the judged setup alone
    means taking a standard deviation from two points, and that stopped a sound campaign.

    None until the pool has GOTIT_MIN_POOL_DF degrees of freedom (D18-2), because a pool of two
    or three runs is the same fault one level up. The judged run is not in it: a run may not
    widen the allowance it is about to be measured against.
    """
    _, rows = _campaign_runs(run_dir)
    by_setup = {}
    for _, setup, _, median in rows:
        by_setup.setdefault(setup, []).append(median)
    residuals, freedom = [], 0
    for medians in by_setup.values():
        if len(medians) < 2:
            continue
        centre = statistics.median(medians)
        residuals += [median - centre for median in medians]
        freedom += len(medians) - 1
    if freedom < GOTIT_MIN_POOL_DF:
        return None, freedom
    return statistics.pstdev(residuals), freedom


def earlier_same_setup(run_dir):
    """The got-it medians of this campaign's earlier counted runs of this very setup.

    Not the session's calibration (plan version 17, D17-1). A campaign runs hours after the
    calibration it is placed from and its got-it drifts in between, by an amount that has nothing
    to do with the delay -- and the allowance it was charged against is a quarter of that delay.
    Two campaigns measured that drift at 0.022 ms and 0.124 ms on near-equal noise floors, so it
    is the drift that varies. Within one campaign the drift is common to the runs compared and
    cancels, which is the whole reason for looking here instead.

    Earlier means earlier in the queue's own order for this setup -- a lower round, or an earlier
    attempt at the same round -- and not whatever the filesystem happens to report, so the answer
    does not depend on when anything was written.
    """
    mine, rows = _campaign_runs(run_dir)
    if mine is None:
        return []
    return [median for (rounds, setup, attempt, median) in rows
            if setup == mine[1] and (rounds, attempt) < (mine[0], mine[2])]


def gotit_shift_from_calibration(summary, params, calibration):
    """How far this run's got-it median sits from the session's zero-delay one, or None.

    Recorded for every run and braking none of them (plan version 17, D17-3). It is the number
    the brake used to stop campaigns with, and it is worth keeping for exactly the reason it was
    no good as a brake: it measures the drift between two sittings.
    """
    if calibration is None or summary.get("gotit_median_ms") is None:
        return None
    entry = calibration_entry(calibration, params)
    zero = entry.get("gotit_zero_median_ms") if entry else None
    return None if zero is None else summary["gotit_median_ms"] - zero


def gotit_checks(summary, params, added_ms, earlier=(), spread=None):
    """The run's "got it" median against its own campaign's earlier runs of the same setup.

    Empty when there is nothing to hold it against: no added delay, a note taken a way the runs
    it would be compared with never took it, or too few of them yet.
    """
    if float(params.get("delay_ms") or 0) <= 0:
        return {}
    if not gotit_comparable(params):
        # Not a failed check: there is nothing here to fail. The run's own got-it median is
        # recorded beside it, and the campaign compares the runs that share a note's place with
        # each other, which is where P5(c)'s question can actually be asked of them.
        return {}
    why = None
    if summary.get("gotit_median_ms") is None:
        why = "the run recorded no got-it times"
    elif added_ms is None:
        why = "the added delay was not measured"
    if why:
        return {"gotit_compared": outcome(False, None, "a got-it median and an added delay", why)}
    if len(earlier) < GOTIT_MIN_EARLIER:
        # The first runs of a setup have nothing like themselves to be held against yet. Their
        # got-it is recorded, and the runs after them are judged against these.
        return {}
    if spread is None:
        # The campaign has not yet run enough to say how much its got-it moves between runs
        # (D18-2). Judging against what it has would be a spread taken from two or three points.
        return {}
    base = statistics.median(earlier)
    shift = summary["gotit_median_ms"] - base
    #: The brake clears the scatter this campaign actually shows as well as its share of the
    #: delay: a quarter of a small delay is less than the got-it median moves between runs.
    noise = max(GOTIT_FLOOR_MS, GOTIT_NOISE_SHARE * spread)
    limit = max(delay_calibration.GROSS_SHARE * abs(added_ms), noise)
    return {"gotit_steady": outcome(
        abs(shift) <= limit, shift, "within %.3f ms" % limit,
        "the got-it median moved %.3f ms from this campaign's %d earlier runs of the same setup,"
        " more than %.0f%% of the %.3f ms added and more than the %.3f ms this campaign's got-it"
        " moves between runs" % (shift, len(earlier), 100 * delay_calibration.GROSS_SHARE,
                                 added_ms, noise))}


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


#: What the got-it brake does with a run it would stop. "stop" is the rule; "record" is asked for
#: by name, for one campaign's remaining runs, and says so beside every run it applies to (D26-1).
#: A5's session at 2 CPUs stopped twice on its got-it -- a move of 0.505 ms with 0.98 ms added,
#: then 0.660 ms with 0.046 ms added, where the delay cannot be what moved it -- and its last
#: thirteen runs were run with the brake recording, a change made after both stops and frozen
#: before those runs began. The allowance, what a run is held against and what the brake would
#: have said are all unchanged and all kept.
GOTIT_BRAKE_MODES = ("stop", "record")


def evaluate(run_dir, rate, duration, warmup_s, calibration=None,
             summarise=pilot_checks.summarise, gotit_brake="stop", planned=None):
    """Every check on one run, and the verdict they give."""
    if gotit_brake not in GOTIT_BRAKE_MODES:
        raise ValueError("the got-it brake either stops or records, not %r" % (gotit_brake,))
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
    checks.update(message_checks(sent_after, summary["messages"], rate, duration, warmup_s,
                                 planned))
    checks["send_rate"] = rate_check(sent_after, rate)
    window = (sent_after[0], sent_after[-1]) if sent_after else (cutoff, cutoff)
    guarded(checks, "load", lambda: load_check(run_dir, float(params["load_pct"]), *window))
    guarded(checks, "settings", lambda: settings_check(run_dir))
    guarded(checks, "client",
            lambda: client_check(run_dir, params["backend"], params.get("ack_stamp"),
                                 params.get("ack_batch")))
    added = None
    try:
        checks["delay"], added = delay_check(run_dir, float(params["delay_ms"]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        checks["delay"] = outcome(False, None, None, "the delay could not be checked: %s" % exc)
    recorded["delay_held_ms"] = added
    checks["clock"] = clock_check(run_dir)
    recorded["clock_offset_max_s"] = checks["clock"]["value"]
    earlier = earlier_same_setup(run_dir)
    spread, freedom = campaign_spread(run_dir)
    got = gotit_checks(summary, params, added, earlier, spread)
    if gotit_brake == "record":
        #: D26-1: what the brake would have said travels with the run and stops nothing.
        recorded["gotit_brake"] = "records and does not stop (D26-1, D32-1)"
        if "gotit_steady" in got:
            recorded["gotit_steady"] = got.pop("gotit_steady")
    checks.update(got)
    recorded["gotit_earlier_same_setup"] = len(earlier)
    # What the allowance was built from, so a brake that stops a campaign can be argued with
    # afterwards from the campaign's own files (D18-3).
    recorded["gotit_campaign_spread_ms"] = spread
    recorded["gotit_campaign_spread_df"] = freedom
    recorded["gotit_setup_centre_ms"] = statistics.median(earlier) if earlier else None
    # Kept and no longer braking anything (D17-3): the distance between this run and a sitting
    # hours before it measures the drift between them, which is why it was the wrong thing to
    # stop a campaign with and the right thing to be able to read afterwards.
    recorded["gotit_shift_from_calibration_ms"] = gotit_shift_from_calibration(
        summary, params, calibration)
    # Which runs the brake could judge travels with the run, so a campaign that measured its
    # got-it a way the calibration never did says so in its own files rather than in a note.
    recorded["gotit_compared_with_calibration"] = bool(
        calibration is not None and float(params.get("delay_ms") or 0) > 0
        and gotit_comparable(params))
    recorded["gotit_note_at"] = params.get("ack_stamp") or CALIBRATED_AT
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
    p.add_argument("--planned", type=int, default=None,
                   help="messages planned after the warm-up, where the plan says outright rather "
                        "than rate times time: M0's replay in bursts (D29-1)")
    p.add_argument("--calibration", default="", help="the session's delay_calibration.py fit")
    p.add_argument("--gotit-brake", choices=GOTIT_BRAKE_MODES, default="stop",
                   help="what the got-it brake does with a run it would stop: the rule stops the "
                        "campaign; 'record' keeps the verdict it would have given beside the run "
                        "and stops nothing (D26-1)")
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
                          summarise, gotit_brake=args.gotit_brake, planned=args.planned)
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
