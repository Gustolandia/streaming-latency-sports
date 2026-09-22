#!/usr/bin/env python3
"""
testbed_watch.py -- watch the Azure testbed from your own computer, and say when something is off.

It reads the machines and changes nothing on them, with one exception it is told to make. Each
cycle opens one SSH session to each driver and one to each broker (through its driver), reads
what is happening, prints one status block per lane and appends it to runs/azure_watch/, and
writes the latest look to runs/azure_watch/status.json. A lane is one machine pair: its own
hosts file, its own machines, its own campaigns. It raises a flag when:

  IDLE     a driver is running, and so billing, with no campaign on it
  stuck    a campaign is running but nothing under ~/sbl has changed for STALE_MIN minutes
  late     the run in progress has been going far longer than this campaign's runs take. Runs
           take the same time to the second, so a late one is not slow, it is wrong
  stopped  a campaign stopped itself on a rule (a STOP_RULE line in its log): find the cause first
  complete a campaign finished: collect its runs (scripts/collect_runs.py), then start the next
  failed   new "[FAIL]" trials appeared in a campaign log since the previous cycle
  stop     a run's integrity verdict stopped its campaign (scripts/run_integrity.py)
  repeat   a run's integrity verdict sent it back to the queue
  pilot    the newest pilot failed a settings or network check (its harness verdict is judged by
           the session's calibration, and go-first by the campaign that tests it)
  broken   a finished run has a negative trip: arrival before sending, so the harness is wrong
  crazy    a finished run shows numbers no working setup produces: a median trip above
           CRAZY_TRIP_MS, fewer than FEW_MESSAGES messages, or a load CRAZY_LOAD_POINTS off
  off      a placed run missed its planned trip by more than OFF_TARGET_MS and OFF_TARGET_SHARE
  odd      a finished run, its verdict or its numbers could not be read
  load     stress-ng is running but the driver's CPUs are less than half busy
  disk     a disk is DISK_PCT% full; Kafka's logs once filled a 45 GB disk on Oracle
  memory   less than a tenth of memory is available
  steal    another tenant is taking more than STEAL_PCT% of the CPU, so runs will be noisier
  clock    chrony's offset is above CLOCK_S
  brokers  Kafka or Redis is not running on the broker
  receiver the receiver's namespace is gone, which means a reboot: run cloud/azure/session.sh
  unreachable  SSH fails; if the Azure CLI is present, the line also says whether the machine is
               running (billing) or deallocated (not billing)
  pairs    two lanes run the same queue, or the lanes run different commits of the code

Every look also shows one line per finished run, with its messages, trip, "got it" delay,
negative share, load and verdict, so absurd numbers are seen at once; and under any alert it
prints the command that stops that pair after the run in progress.

The exception: with --stop-idle-min N, a lane whose machines have been IDLE for N minutes is
stopped (deallocated), so it stops billing for CPUs.

What it cannot see: whether a number is right. It flags numbers no working harness produces and
the verdicts the runs already carry, and leaves the rest to the analysis.

Usage:
    python scripts/testbed_watch.py              # every 5 minutes until Ctrl+C
    python scripts/testbed_watch.py --once       # one check; exit 1 if anything is an ALERT
    python scripts/testbed_watch.py --lane a=cloud/hosts.env --lane b=cloud/hosts_b.env
    python scripts/testbed_watch.py --lane a=cloud/hosts.env --stop-idle-min 20
"""
import argparse
import datetime
import io
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import azure_testbed  # noqa: E402
import progress  # noqa: E402
import spend  # noqa: E402

HOSTS_ENV = os.path.join(azure_testbed.REPO, "cloud", "hosts.env")
LOG_DIR = os.path.join(azure_testbed.REPO, "runs", "azure_watch")
KEY = os.path.join("~", ".ssh", "azure_sbl")

STALE_MIN = 20
#: How long a run takes when nothing has gone wrong, until the queue itself says otherwise: 197
#: runs on three machine pairs took 160 s each, with about ten more between one run and the next.
RUN_SECONDS = 170
#: A run is late when it passes this much of what its own campaign's runs have been taking, and
#: LATE_FLOOR_S in any case, so that a quick campaign does not cry wolf.
LATE_SHARE = 1.5
LATE_FLOOR_S = 240
CRAZY_TRIP_MS = 50.0
FEW_MESSAGES = 100
CRAZY_LOAD_POINTS = 15.0
OFF_TARGET_MS = 1.0
OFF_TARGET_SHARE = 0.5
DISK_PCT = 80
MEM_FREE_FRACTION = 0.10
STEAL_PCT = 5.0
CLOCK_S = 0.001
IDLE_BUSY_PCT = 10.0
LOADED_BUSY_PCT = 50.0

COMMON_PROBE = r"""
c1=$(head -1 /proc/stat); sleep 2; c2=$(head -1 /proc/stat)
echo "cpu1=$c1"
echo "cpu2=$c2"
echo "ncpu=$(nproc)"
echo "mem_total_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
echo "mem_avail_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
echo "disk_pct=$(df --output=pcent / | tail -1 | tr -dc 0-9)"
echo "clock_offset_s=$(chronyc -c tracking 2>/dev/null | cut -d, -f5)"
"""

#: The trial directories campaigns write are runs/concurrency_* (the Oracle scripts and the pilot)
#: and runs/law_* (cloud/azure/campaign.sh). A run counts as finished once its tti_summary.json
#: exists, and only runs finished in the last @WINDOW@ minutes are read. The newest log is the
#: campaign's own, so a stop rule or a completion is read from it alone, and only the last of
#: them counts: a chain of campaigns (cloud/azure/stage0.sh) completes several before it ends.
#:
#: Two kinds of work, counted apart, because a pair is told off for different things.
#:
#: `campaign` is work that makes runs. If it is going and nothing under ~/sbl has changed for a
#: while, that is a stall and worth an alert.
#:
#: `queued` is work in hand that makes no runs yet: a chain waiting for a calibration to pass,
#: the rounds rule simulating the campaign it will then start, and a queue holding a list of
#: sessions it is working through. The queue matters most of the three, because it is idle by
#: design between jobs -- it has just rebooted the machine, or is waiting a minute before looking
#: again -- and a pair deallocated in that gap loses a list of work nobody is left watching.
#: Such a pair is not idle --
#: deallocating it destroys exactly what chain.sh exists to protect -- but neither is it stalled,
#: and an alert every five minutes for the hours a simulation takes is how a real stall comes to
#: be ignored. On 21 September the first x86 pair was flagged idle at 13:38:58 with a chain armed
#: on it, and was saved only because the simulation that began moments later holds one core:
#: 12.5% of eight, just over the 10% this calls busy. On a machine with sixteen that is 6.25%
#: and the pair would have gone.

DRIVER_PROBE = COMMON_PROBE + r"""
echo "campaign=$(pgrep -f 'cloud/azure/stage0.sh|cloud/azure/pilot.sh|cloud/azure/replicate_oracle.sh|cloud/azure/campaign.sh|cloud/campaigns/|run_concurrency_test.py|run_kafka_trial.sh|run_redis_trial.sh' | wc -l)"
echo "queued=$(pgrep -f 'cloud/azure/chain.sh|cloud/azure/stage1.sh|cloud/azure/queue.sh|rounds_rule.py' | wc -l)"
echo "stress=$(pgrep -x stress-ng | wc -l)"
echo "netns=$(ip netns list 2>/dev/null | grep -c '^sblrecv')"
queue=$(pgrep -af 'cloud/azure/campaign.sh' | grep -o 'runs/[^ ]*\.csv' | head -n 1)
cd ~/sbl 2>/dev/null || exit 0
echo "commit=$(git rev-parse --short HEAD 2>/dev/null)"
now=$(date +%s)
log=$(ls -t ./*.log 2>/dev/null | head -1)
if [ -n "$log" ]; then
  echo "log=$log"
  echo "log_tail=$(tail -n 1 "$log" | tr -d '\r' | cut -c1-160)"
  echo "log_age_s=$(( now - $(stat -c %Y "$log") ))"
  outcome=$(grep -E 'STOP_RULE|CAMPAIGN_COMPLETE' "$log" | tail -n 1 | tr -d '\r' | cut -c1-200)
  case "$outcome" in *STOP_RULE*) echo "stop_rule=$outcome" ;; esac
  echo "complete=$(printf '%s' "$outcome" | grep -c 'CAMPAIGN_COMPLETE')"
fi
#: What the queue says about time: how long the run in progress has been going, how long this
#: campaign's finished runs have taken from one start to the next, and how many are left.
TIMING='
import csv, datetime, json, statistics, sys
def when(text):
    return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)
out = {}
try:
    rows = list(csv.DictReader(open(sys.argv[1], newline="", encoding="utf-8")))
    now = datetime.datetime.now(datetime.timezone.utc)
    started = sorted(when(r["started_utc"]) for r in rows if r["started_utc"])
    cycles = [(b - a).total_seconds() for a, b in zip(started, started[1:])]
    running = [r for r in rows if r["status"] == "running" and r["started_utc"]]
    out["left"] = sum(1 for r in rows if r["status"] in ("queued", "running"))
    out["done"] = sum(1 for r in rows if r["status"] == "done")
    out["runs"] = len(rows)
    if cycles:
        out["cycle_s"] = statistics.median(cycles)
    if running:
        out["run_key"] = running[-1]["key"]
        out["run_started"] = running[-1]["started_utc"]
        out["run_age_s"] = (now - when(running[-1]["started_utc"])).total_seconds()
except Exception as exc:
    out["unreadable"] = type(exc).__name__
print(json.dumps(out))
'

if [ -n "$queue" ]; then
  echo "queue=$queue"
  echo "progress=$(python3 scripts/run_queue.py report --queue "$queue" 2>/dev/null | head -n 1)"
  echo "timing=$(python3 -c "$TIMING" "$queue" 2>/dev/null)"
fi
newest=$(ls -td runs/* runs/azure/*/* 2>/dev/null | head -1)
[ -n "$newest" ] && echo "activity_age_s=$(( now - $(stat -c %Y "$newest") ))"
echo "fails=$(cat ./*.log 2>/dev/null | grep -c '\[FAIL\]')"
v=$(ls -t runs/azure/pilot/*/verdicts.csv runs/azure/stage0/*/pilot/verdicts.csv 2>/dev/null | head -1)
[ -n "$v" ] && echo "verdict_no=$(grep -cE '^(settings|network),[^,]*,no,' "$v")"
for d in $(find runs -maxdepth 1 -mindepth 1 -type d \( -name 'concurrency_*' -o -name 'law_*' \) -mmin -@WINDOW@ 2>/dev/null | head -n 20); do
  if [ -f "$d/tti_summary.json" ]; then
    echo "run=$(python3 scripts/pilot_checks.py run "$d" --warmup-s 0 2>&1 | tr -d '\n ')"
  fi
  if [ -f "$d/integrity.json" ]; then
    echo "verdict=$(python3 scripts/run_integrity.py show "$d" 2>&1 | tr -d '\n')"
  fi
done
NUMBERS='
import json, sys
d = sys.argv[1]
out = {"run_dir": d}
try:
    found = json.load(open(d + "/integrity.json"))
    checks, recorded = found.get("checks") or {}, found.get("recorded") or {}
    out.update(verdict=found.get("verdict"), messages=recorded.get("messages"),
               trip_ms=recorded.get("trip_median_ms"), gotit_ms=recorded.get("gotit_median_ms"),
               negative_rate=recorded.get("measured_negative_rate"),
               load_pct=(checks.get("load") or {}).get("value"))
    params = json.load(open(d + "/queue_row.json"))["params"]
    out.update(load_target=params.get("load_pct"), target_trip_ms=params.get("target_trip_ms"))
except Exception as exc:
    out["unreadable"] = type(exc).__name__
print(json.dumps(out))
'
for d in $(find runs -maxdepth 1 -mindepth 1 -type d -name 'law_*' -mmin -@WINDOW@ 2>/dev/null | head -n 20); do
  if [ -f "$d/integrity.json" ]; then
    echo "numbers=$(python3 -c "$NUMBERS" "$d" 2>/dev/null)"
  fi
done
"""

BROKER_PROBE = COMMON_PROBE + r"""
echo "docker=$(docker ps --format '{{.Names}}:{{.State}}' 2>/dev/null | tr '\n' ' ')"
"""


def read_hosts(path):
    """KEY=VALUE pairs from hosts.env, refusing a file that lacks what the watch needs."""
    hosts = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                hosts[key] = value
    missing = [k for k in ("DRIVER_PUBLIC", "BROKER_PRIV", "AZ_PROFILE") if k not in hosts]
    if missing:
        raise ValueError("%s lacks %s; write it with scripts/azure_testbed.py hosts"
                         % (path, ", ".join(missing)))
    return hosts


def ssh_argv(ssh, key, host, jump=None):
    """An ssh command that runs a script read from stdin, optionally through the driver.

    Paths go with forward slashes: the jump to the broker runs inside a shell, which would eat
    the backslashes of a Windows key path, and ssh reads either kind.
    """
    ssh, key = ssh.replace("\\", "/"), key.replace("\\", "/")
    opts = ["-i", key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
            "-o", "StrictHostKeyChecking=accept-new"]
    argv = [ssh] + opts
    if jump:
        argv += ["-o", "ProxyCommand=%s %s -W %%h:%%p ubuntu@%s" % (ssh, " ".join(opts), jump)]
    return argv + ["ubuntu@%s" % host, "bash -s"]


#: Probe lines that come once per finished run, and the list each goes into.
LISTS = {"run": "runs", "verdict": "verdicts", "numbers": "numbers"}


def parse(text):
    """Probe output as a dict. Every run=, verdict= and numbers= line becomes one entry of the
    list LISTS names for it."""
    facts = {name: [] for name in LISTS.values()}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            continue
        if key in LISTS:
            try:
                entry = json.loads(value)
            except ValueError:
                entry = {"unreadable": value}
            facts[LISTS[key]].append(entry)
        else:
            facts[key] = value.strip()
    return facts


def run_script(run, argv, script, timeout):
    """(exit code, stdout, stderr) of a bash script fed to a machine's stdin over SSH.

    The script goes as bytes. In text mode, Python on Windows turns every newline it writes into
    CR LF, and bash on the machine then reads a stray carriage return at the end of every line.
    """
    done = run(argv, input=script.encode("utf-8"), capture_output=True, timeout=timeout)
    return (done.returncode, done.stdout.decode("utf-8", "replace"),
            done.stderr.decode("utf-8", "replace"))


def probe(run, argv, script, timeout=90):
    """(facts, "") from one SSH session, or (None, why) if it could not be read."""
    try:
        code, stdout, stderr = run_script(run, argv, script, timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if code != 0:
        lines = (stderr or stdout).strip().splitlines()
        return None, lines[-1] if lines else "ssh exited with %d" % code
    return parse(stdout), ""


def cpu_usage(first, second):
    """(busy %, steal %) between two aggregate /proc/stat lines, or (None, None)."""
    try:
        a = [int(v) for v in first.split()[1:9]]
        b = [int(v) for v in second.split()[1:9]]
    except (AttributeError, ValueError):
        return None, None
    delta = [y - x for x, y in zip(a, b)]
    total = sum(delta)
    if len(delta) < 8 or total <= 0:
        return None, None
    idle = delta[3] + delta[4]
    return 100.0 * (total - idle) / total, 100.0 * delta[7] / total


def number(facts, key, cast=float):
    try:
        return cast(facts[key])
    except (KeyError, ValueError, TypeError):
        return None


def machine_flags(name, facts):
    """Flags any machine can raise about itself."""
    flags = []
    _, steal = cpu_usage(facts.get("cpu1"), facts.get("cpu2"))
    disk = number(facts, "disk_pct", int)
    if disk is not None and disk >= DISK_PCT:
        flags.append(("ALERT", "disk: the %s's disk is %d%% full" % (name, disk)))
    total, avail = number(facts, "mem_total_kb"), number(facts, "mem_avail_kb")
    if total and avail is not None and avail / total < MEM_FREE_FRACTION:
        flags.append(("ALERT", "memory: the %s has %.0f%% of its memory free"
                      % (name, 100 * avail / total)))
    if steal is not None and steal > STEAL_PCT:
        flags.append(("WARN", "steal: another tenant took %.1f%% of the %s's CPU; runs now "
                      "will be noisier" % (steal, name)))
    offset = number(facts, "clock_offset_s")
    if offset is not None and abs(offset) > CLOCK_S:
        flags.append(("WARN", "clock: the %s's clock is %.2f ms off" % (name, 1000 * offset)))
    return flags


def run_flags(runs):
    """Flags about the numbers of runs that finished since the last look."""
    flags = []
    for run in runs:
        where = run.get("run_dir", "a run")
        if "unreadable" in run:
            flags.append(("WARN", "odd: could not read a finished run (%s)" % run["unreadable"][:80]))
        elif run.get("trip_negative"):
            flags.append(("ALERT", "broken: %s has %d messages that arrived before they were "
                          "sent; the harness is wrong" % (where, run["trip_negative"])))
        else:
            if (run.get("trip_median_ms") or 0) > CRAZY_TRIP_MS:
                flags.append(("ALERT", "crazy: %s has a median trip of %.1f ms"
                              % (where, run["trip_median_ms"])))
            # Only a campaign run has a planned message count; the pilot replays real matches,
            # whose feeds hold 71 to 148 events.
            if (os.path.basename(str(where)).startswith("law_")
                    and (run.get("messages") or 0) < FEW_MESSAGES):
                flags.append(("ALERT", "crazy: %s carried only %d messages"
                              % (where, run.get("messages") or 0)))
    return flags


def verdict_flags(verdicts):
    """Flags about the integrity verdicts runs were given since the last look."""
    flags = []
    for found in verdicts:
        where = found.get("run_dir", "a run")
        reasons = "; ".join(found.get("reasons") or [])
        if "unreadable" in found:
            flags.append(("WARN", "odd: could not read a run's integrity verdict (%s)"
                          % found["unreadable"][:80]))
        elif found.get("verdict") == "stop":
            flags.append(("ALERT", "stop: %s: %s" % (where, reasons)))
        elif found.get("verdict") == "repeat":
            flags.append(("WARN", "repeat: %s will run again: %s" % (where, reasons)))
    return flags


def _number(value):
    """A float, or None for anything that is not a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def numbers_flags(numbers):
    """Flags about what finished campaign runs measured against what they were set to."""
    flags = []
    for found in numbers:
        where = found.get("run_dir", "a run")
        if "unreadable" in found:
            flags.append(("WARN", "odd: could not read the numbers of %s (%s)"
                          % (where, str(found["unreadable"])[:80])))
            continue
        load, wanted = _number(found.get("load_pct")), _number(found.get("load_target"))
        if load is not None and wanted is not None and abs(load - wanted) > CRAZY_LOAD_POINTS:
            flags.append(("ALERT", "crazy: %s ran at %.0f%% load where %.0f%% was set; the load "
                          "generator may have died" % (where, load, wanted)))
        trip, target = _number(found.get("trip_ms")), _number(found.get("target_trip_ms"))
        if (trip is not None and target is not None
                and abs(trip - target) > max(OFF_TARGET_MS, OFF_TARGET_SHARE * target)):
            flags.append(("WARN", "off: %s measured a %.2f ms trip where %.2f ms was planned; "
                          "the calibration may be placing runs badly" % (where, trip, target)))
    return flags


def _shown(label, value, spec):
    """`label value`, the value formatted by `spec`, or `label ?` when it is not a number."""
    number = _number(value)
    return "%s %s" % (label, "?" if number is None else spec.format(number))


def run_line(run, numbers):
    """One finished run in a line. A campaign run shows the numbers its verdict was given on,
    after the warm-up, with its planned trip, load and verdict; another run shows what the probe
    read, warm-up included."""
    def pick(key, fallback):
        return numbers[key] if numbers.get(key) is not None else run.get(fallback)
    trip = _shown("trip", pick("trip_ms", "trip_median_ms"), "{:.2f} ms")
    if _number(numbers.get("target_trip_ms")) is not None:
        trip += _shown(" (planned", numbers["target_trip_ms"], "{:.2f} ms)")
    parts = [_shown("messages", pick("messages", "messages"), "{:,.0f}"), trip,
             _shown("got-it", pick("gotit_ms", "gotit_median_ms"), "{:.2f} ms"),
             _shown("negative", pick("negative_rate", "measured_negative_rate"), "{:.1%}")]
    if "load_pct" in numbers:
        parts.append(_shown("load", numbers["load_pct"], "{:.1f}%"))
    if numbers.get("verdict"):
        parts.append(numbers["verdict"])
    return "run %s: %s" % (os.path.basename(str(run.get("run_dir", "?"))), ", ".join(parts))


def timing(driver):
    """What the driver said about time, as numbers, or {} when it said nothing readable."""
    try:
        found = json.loads(driver.get("timing") or "{}")
    except ValueError:
        return {}
    return found if isinstance(found, dict) and "unreadable" not in found else {}


def due_line(driver):
    """One line on where the campaign has got to and when it is due, or None."""
    found = timing(driver)
    if not found.get("left"):
        return None
    cycle = found.get("cycle_s") or RUN_SECONDS
    left_s = cycle * found["left"]
    due = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=left_s)
    going = found.get("run_age_s")
    return ("queue: %d of %d done, %d left at %.0f s each, due %s UTC%s"
            % (found.get("done", 0), found.get("runs", 0), found["left"], cycle,
               due.strftime("%H:%M"),
               "" if going is None else "; %s running %.1f min" % (found.get("run_key", "a run"),
                                                                   going / 60)))


def began_a_run(driver, state):
    """(key, when it started) when the queue has begun a run since the last look, else None.

    A run takes under three minutes and the watch looks every few, so most runs begin and end
    between two looks; this catches the ones the watch is there for, and each is reported once.
    """
    found = timing(driver or {})
    began = found.get("run_started")
    if not began or began == state.get("run_started"):
        return None
    state["run_started"] = began
    return found.get("run_key") or "a run", began


def late_run(driver):
    """The run in progress, when it has been going far longer than this campaign's runs take."""
    found = timing(driver)
    going, cycle = found.get("run_age_s"), found.get("cycle_s") or RUN_SECONDS
    if going is None:
        return None
    limit = max(LATE_FLOOR_S, LATE_SHARE * cycle)
    if going <= limit:
        return None
    return ("late: %s has been running %.1f minutes; this campaign's runs take %.0f s and the "
            "limit is %.0f s" % (found.get("run_key", "the run in progress"), going / 60,
                                 cycle, limit))


def run_lines(driver):
    """A line for every run that finished since the last look."""
    numbers = {found.get("run_dir"): found for found in driver["numbers"]
               if "unreadable" not in found}
    return [run_line(run, numbers.get(run.get("run_dir"), {}))
            for run in driver["runs"] if "unreadable" not in run]


def evaluate(driver, broker, previous_fails=None):
    """Every flag for one cycle. A machine that could not be read is passed as None."""
    flags = []
    if driver is not None:
        flags += machine_flags("driver", driver)
        busy, _ = cpu_usage(driver.get("cpu1"), driver.get("cpu2"))
        campaign = number(driver, "campaign", int) or 0
        # A pair with a campaign chained behind a calibration, or simulating the rounds for one,
        # has work in hand and is not idle -- and it is quiet, because a chain sleeps between
        # looks. Only the stall alert below is about making runs; this is about having anything
        # to do at all.
        queued = number(driver, "queued", int) or 0
        if not campaign and not queued and (busy is None or busy < IDLE_BUSY_PCT):
            flags.append(("IDLE", "the machines are running with no campaign; stop them with "
                          "scripts/azure_testbed.py stop --yes"))
        overdue = late_run(driver)
        if campaign and overdue:
            flags.append(("ALERT", overdue))
        activity = number(driver, "activity_age_s", int)
        if campaign and activity is not None and activity > STALE_MIN * 60:
            flags.append(("ALERT", "stuck: a campaign is running but nothing has changed for "
                          "%d minutes" % (activity // 60)))
        if not campaign and driver.get("stop_rule"):
            flags.append(("ALERT", "stopped: the campaign stopped itself (%s); find the cause "
                          "before starting it again" % driver["stop_rule"]))
        if not campaign and number(driver, "complete", int):
            flags.append(("INFO", "complete: the campaign finished; collect its runs with "
                          "scripts/collect_runs.py, then start the next"))
        if (number(driver, "stress", int) or 0) and busy is not None and busy < LOADED_BUSY_PCT:
            flags.append(("WARN", "load: stress-ng is running but the CPUs are only %.0f%% busy"
                          % busy))
        fails = number(driver, "fails", int)
        if fails is not None and previous_fails is not None and fails > previous_fails:
            flags.append(("ALERT", "failed: %d new failed trials since the last look"
                          % (fails - previous_fails)))
        if number(driver, "verdict_no", int):
            flags.append(("ALERT", "pilot: the newest pilot failed %s settings or network "
                          "check(s); nothing should run on this pair" % driver["verdict_no"]))
        if number(driver, "netns", int) == 0:
            flags.append(("WARN", "receiver: the namespace is gone; run cloud/azure/session.sh"))
        flags += run_flags(driver["runs"])
        flags += verdict_flags(driver["verdicts"])
        flags += numbers_flags(driver["numbers"])
    if broker is not None:
        flags += machine_flags("broker", broker)
        docker = broker.get("docker", "")
        for container in ("broker", "redis"):
            if "%s:running" % container not in docker.split():
                flags.append(("ALERT", "brokers: %s is not running on the broker" % container))
    return flags


def power_states(runner, resource_group):
    """{machine: power state} from the Azure CLI, or {} if it cannot say."""
    try:
        code, out, _ = runner(["vm", "list", "--show-details", "--resource-group",
                               resource_group, "--output", "json"])
    except azure_testbed.AzNotFound:
        return {}
    if code != 0:
        return {}
    try:
        return {vm.get("name"): vm.get("powerState") for vm in json.loads(out)}
    except ValueError:
        return {}


def summary(name, address, facts):
    """One line about a machine that answered."""
    busy, steal = cpu_usage(facts.get("cpu1"), facts.get("cpu2"))
    parts = ["%s %s:" % (name, address),
             "CPU %s" % ("?" if busy is None else "%.0f%% (steal %.1f%%)" % (busy, steal)),
             "disk %s%%" % facts.get("disk_pct", "?")]
    total, avail = number(facts, "mem_total_kb"), number(facts, "mem_avail_kb")
    if total and avail is not None:
        parts.append("memory %.0f%% free" % (100 * avail / total))
    if "docker" in facts:
        parts.append("containers %s" % (facts["docker"].strip() or "none"))
    if "campaign" in facts:
        # "none" on a pair that is simulating the rounds for the campaign it is about to start,
        # or waiting for a calibration to pass, reads as "nothing is happening here" -- and the
        # person reading it is the one who would then stop the pair by hand.
        parts.append("campaign %s" % ("running" if number(facts, "campaign", int)
                                      else "queued" if number(facts, "queued", int) else "none"))
    if facts.get("progress"):
        parts.append("queue %s: %s" % (facts.get("queue", "?"), facts["progress"]))
    if "log" in facts:
        parts.append("log %s %s s ago: %s" % (facts["log"], facts.get("log_age_s", "?"),
                                              facts.get("log_tail", "")))
    return "  ".join(parts)


def cycle(hosts, spec, key, ssh, run, runner, state, stamp, window_min=15, lane="main"):
    """(lines, flags) for one look at one lane. `state` keeps what the next look compares."""
    driver, driver_err = probe(run, ssh_argv(ssh, key, hosts["DRIVER_PUBLIC"]),
                               DRIVER_PROBE.replace("@WINDOW@", str(window_min)))
    broker, broker_err = probe(run, ssh_argv(ssh, key, hosts["BROKER_PRIV"],
                                             jump=hosts["DRIVER_PUBLIC"]), BROKER_PROBE)
    flags = evaluate(driver, broker, state.get("fails"))
    profile = hosts["AZ_PROFILE"]
    own = azure_testbed.profile_spec(spec, profile)
    if driver is not None:
        state.update(fails=number(driver, "fails", int), commit=driver.get("commit") or None,
                     queue=driver.get("queue") or None, timing=timing(driver))
    else:
        state.update(commit=None, queue=None)
    machines = azure_testbed.profile_hosts(own, profile)
    names = dict((h["role"], n) for n, h in machines)
    if driver is None or broker is None:
        states = power_states(runner, own["resource_group"])
        for role, facts, err in (("driver", driver, driver_err), ("broker", broker, broker_err)):
            if facts is None:
                power = states.get(names[role])
                # A pair that was stopped because its work was done is the state we want it in,
                # not a fault. Alerting on it every look would bury the alerts that matter.
                if power and "deallocated" in power.lower():
                    flags.append(("INFO", "stopped: the %s is deallocated, so it is not billing"
                                  % role))
                    continue
                flags.append(("ALERT", "unreachable: the %s does not answer over SSH (%s)%s"
                              % (role, err, "; Azure says: %s" % power if power else "")))
    hourly = sum(own["hourly_usd"][h["size"]] for _, h in machines)
    #: Azure charges for a machine that is allocated, so a pair that answers is a pair being paid
    #: for. One that does not answer is counted at nothing: the estimate stays low on purpose, and
    #: `spend.py billed` reads what Azure actually charged.
    state["hourly_usd"] = hourly if (driver is not None or broker is not None) else 0.0
    state["began"] = began_a_run(driver, state)
    lines = ["%s  lane %s, profile %s, about $%.2f an hour while running%s"
             % (stamp, lane, profile, hourly,
                ", commit %s" % state["commit"] if state.get("commit") else "")]
    if driver is not None:
        lines.append("  " + summary("driver", hosts["DRIVER_PUBLIC"], driver))
        due = due_line(driver)
        if due:
            lines.append("  " + due)
        lines.append("  runs finished in the last %d min: %d" % (window_min, len(driver["runs"])))
        lines += ["  " + line for line in run_lines(driver)]
    if broker is not None:
        lines.append("  " + summary("broker", hosts["BROKER_PRIV"], broker))
    lines += ["  %s %s" % (level, message) for level, message in flags] or ["  all clear"]
    if driver is not None and any(level == "ALERT" and not message.startswith("unreachable")
                                  for level, message in flags):
        lines.append("  to stop this pair after the run in progress: %s 'touch sbl/runs/azure/STOP'"
                     % " ".join(ssh_argv(ssh, key, hosts["DRIVER_PUBLIC"])[:-1]))
    return lines, flags


def cross_lane_flags(states):
    """Flags about the lanes together: one queue on two pairs, or pairs on different code."""
    flags = []
    queues = {}
    for lane, state in sorted(states.items()):
        if state.get("queue"):
            queues.setdefault(state["queue"], []).append(lane)
    for queue, lanes in sorted(queues.items()):
        if len(lanes) > 1:
            flags.append(("ALERT", "pairs: lanes %s both run %s; a campaign runs on one pair"
                          % (" and ".join(lanes), queue)))
    commits = {state["commit"] for state in states.values() if state.get("commit")}
    if len(commits) > 1:
        flags.append(("WARN", "pairs: the lanes run different commits (%s); every pair should run "
                      "the same code" % ", ".join(sorted(commits))))
    return flags


def stop_idle(lane, hosts, spec, runner, state, idle, now, after_min):
    """Stop a lane's machines once they have been idle for `after_min` minutes.

    Returns flags: none until then, INFO once they are stopped, ALERT if stopping failed. With
    `after_min` at 0 the idle time is tracked and nothing is stopped.
    """
    if not idle:
        state.pop("idle_since", None)
        return []
    since = state.setdefault("idle_since", now)
    idle_min = int((now - since).total_seconds() // 60)
    if not after_min or idle_min < after_min:
        return []
    profile = hosts["AZ_PROFILE"]
    said = io.StringIO()
    try:
        code = azure_testbed.execute(
            azure_testbed.power_steps(azure_testbed.profile_spec(spec, profile), profile, "stop"),
            runner, said)
    except azure_testbed.AzNotFound as exc:
        code, said = 1, io.StringIO(str(exc))
    state.pop("idle_since", None)
    if code == 0:
        return [("INFO", "stopped: lane %s had been idle for %d minutes; its machines were "
                 "deallocated" % (lane, idle_min))]
    last = (said.getvalue().strip().splitlines() or ["exit %d" % code])[-1]
    return [("ALERT", "stopping: lane %s has been idle for %d minutes and could not be stopped "
             "(%s)" % (lane, idle_min, last))]


def far_along(states):
    """How much of the experiment has been run, counting the campaigns now under way.

    A campaign is copied home only once it has finished, so the runs its queue has already
    counted are added from the queue itself and counted once.
    """
    live = []
    for state in states.values():
        queue, done = state.get("queue"), (state.get("timing") or {}).get("done")
        if queue and done:
            # runs/azure/stage1/<pair>_<stamp>/<label>.csv: the folder names the pair that is
            # running it, which is what tells an instrument campaign on Arm from one on x86.
            live.append((os.path.basename(os.path.dirname(queue)),
                         os.path.basename(queue).rsplit(".", 1)[0], done))
    return progress.line(progress.add_live(progress.counted(), live))


def money_lines(lanes, hosts, states, ledger_path, credit_usd, now, status):
    """Add this look's machine time to the ledger and say what has been spent, and at what run."""
    running = {}
    for name, _ in lanes:
        hourly = states[name].get("hourly_usd")
        if hourly:
            profile = hosts[name]["AZ_PROFILE"]
            running[profile] = running.get(profile, 0.0) + hourly
    ledger = spend.track(spend.load(ledger_path), running, now)
    spend.save(ledger, ledger_path)
    status["spend"] = {"total_usd": round(ledger.get("total_usd", 0.0), 4),
                       "credit_usd": credit_usd, "by_profile": ledger.get("by_profile", {})}
    lines = ["  money: " + spend.line(ledger, credit_usd)]
    for name, _ in lanes:
        began = states[name].get("began")
        if began:
            had = spend.at(ledger, began[1])
            lines.append("  money: lane %s began %s at %s, with about $%.2f spent by then"
                         % (name, began[0], began[1],
                            spend.total(ledger) if had is None else had))
            lines.append("  " + far_along(states))
    return lines


def parse_lane(text):
    """(name, hosts file) from NAME=HOSTS_FILE."""
    name, sep, path = text.partition("=")
    if not (sep and name and path):
        raise ValueError("a lane is NAME=HOSTS_FILE, for example b=cloud/hosts_b.env, not %r"
                         % text)
    return name, path


def main(argv=None, run=subprocess.run, runner=None, sleep=time.sleep, clock=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Watch the Azure testbed and flag trouble")
    ap.add_argument("--hosts", default=HOSTS_ENV, help="the hosts file, when there is one lane")
    ap.add_argument("--lane", action="append", default=[],
                    help="NAME=HOSTS_FILE, once for each machine pair")
    ap.add_argument("--spec", default=azure_testbed.SPEC)
    ap.add_argument("--key", default=KEY)
    ap.add_argument("--ssh", default="ssh")
    ap.add_argument("--interval", type=int, default=300, help="seconds between looks")
    ap.add_argument("--window-min", type=int, default=15,
                    help="read the runs that finished in this many minutes")
    ap.add_argument("--stop-idle-min", type=int, default=0,
                    help="stop a lane's machines once idle this many minutes (0: never)")
    ap.add_argument("--once", action="store_true", help="one look; exit 1 on any ALERT")
    ap.add_argument("--cycles", type=int, default=0, help="stop after this many looks (0: never)")
    ap.add_argument("--log-dir", default=LOG_DIR)
    ap.add_argument("--ledger", default=spend.LEDGER,
                    help="where the machine time the watch has counted is kept")
    ap.add_argument("--credit-usd", type=float, default=200.0,
                    help="the credit the spending is measured against")
    args = ap.parse_args(argv)
    clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))
    try:
        lanes = [parse_lane(text) for text in args.lane] or [("main", args.hosts)]
        if len({name for name, _ in lanes}) != len(lanes):
            raise ValueError("lane names repeat: %s" % ", ".join(name for name, _ in lanes))
        hosts = {name: read_hosts(path) for name, path in lanes}
        spec = azure_testbed.load_spec(args.spec)
        for name, _ in lanes:
            azure_testbed.profile_hosts(spec, hosts[name]["AZ_PROFILE"])
    except (OSError, ValueError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2
    runner = runner or azure_testbed.make_runner()
    key = os.path.expanduser(args.key)
    os.makedirs(args.log_dir, exist_ok=True)
    cycles = 1 if args.once else args.cycles
    states = {name: {} for name, _ in lanes}
    alerts, done = False, 0
    try:
        while True:
            now = clock()
            stamp = now.strftime("%Y-%m-%d %H:%M:%S UTC")
            lines, everything, status = [], [], {"stamp": stamp, "lanes": {}}
            for name, _ in lanes:
                lane_lines, flags = cycle(hosts[name], spec, key, args.ssh, run, runner,
                                          states[name], stamp, args.window_min, name)
                idle = any(level == "IDLE" for level, _ in flags)
                stopped = stop_idle(name, hosts[name], spec, runner, states[name], idle, now,
                                    args.stop_idle_min)
                lines += lane_lines + ["  %s %s" % flag for flag in stopped]
                everything += flags + stopped
                status["lanes"][name] = {"profile": hosts[name]["AZ_PROFILE"],
                                         "commit": states[name].get("commit"),
                                         "queue": states[name].get("queue"),
                                         "flags": [list(flag) for flag in flags + stopped]}
            lines += money_lines(lanes, hosts, states, args.ledger, args.credit_usd, now, status)
            together = cross_lane_flags(states)
            lines += ["  %s %s" % flag for flag in together]
            everything += together
            status["pairs"] = [list(flag) for flag in together]
            text = "\n".join(lines)
            print(text, file=out)
            path = os.path.join(args.log_dir, "watch_%s.log" % now.strftime("%Y%m%d"))
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
            with open(os.path.join(args.log_dir, "status.json"), "w", encoding="utf-8") as fh:
                fh.write(json.dumps(status, indent=2, sort_keys=True) + "\n")
            alerts = alerts or any(level == "ALERT" for level, _ in everything)
            done += 1
            if cycles and done >= cycles:
                break
            sleep(args.interval)
    except KeyboardInterrupt:
        print("stopped", file=out)
        return 0
    return 1 if (args.once and alerts) else 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
