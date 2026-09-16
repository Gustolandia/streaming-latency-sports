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
  stopped  a campaign stopped itself on a rule (a STOP_RULE line in its log): find the cause first
  complete a campaign finished: collect its runs (scripts/collect_runs.py), then start the next
  failed   new "[FAIL]" trials appeared in a campaign log since the previous cycle
  stop     a run's integrity verdict stopped its campaign (scripts/run_integrity.py)
  repeat   a run's integrity verdict sent it back to the queue
  pilot    the pilot's verdicts.csv has a check marked no
  broken   a finished run has a negative trip: arrival before sending, so the harness is wrong
  odd      a finished run's median trip is above ODD_TRIP_MS, or it carried few messages
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

HOSTS_ENV = os.path.join(azure_testbed.REPO, "cloud", "hosts.env")
LOG_DIR = os.path.join(azure_testbed.REPO, "runs", "azure_watch")
KEY = os.path.join("~", ".ssh", "azure_sbl")

STALE_MIN = 20
ODD_TRIP_MS = 50.0
FEW_MESSAGES = 100
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
DRIVER_PROBE = COMMON_PROBE + r"""
echo "campaign=$(pgrep -f 'cloud/azure/stage0.sh|cloud/azure/pilot.sh|cloud/azure/replicate_oracle.sh|cloud/azure/campaign.sh|cloud/campaigns/|run_concurrency_test.py|run_kafka_trial.sh|run_redis_trial.sh' | wc -l)"
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
if [ -n "$queue" ]; then
  echo "queue=$queue"
  echo "progress=$(python3 scripts/run_queue.py report --queue "$queue" 2>/dev/null | head -n 1)"
fi
newest=$(ls -td runs/* runs/azure/*/* 2>/dev/null | head -1)
[ -n "$newest" ] && echo "activity_age_s=$(( now - $(stat -c %Y "$newest") ))"
echo "fails=$(cat ./*.log 2>/dev/null | grep -c '\[FAIL\]')"
v=$(ls -t runs/azure/pilot/*/verdicts.csv 2>/dev/null | head -1)
[ -n "$v" ] && echo "verdict_no=$(grep -c ',no,' "$v")"
for d in $(find runs -maxdepth 1 -mindepth 1 -type d \( -name 'concurrency_*' -o -name 'law_*' \) -mmin -@WINDOW@ 2>/dev/null | head -n 20); do
  if [ -f "$d/tti_summary.json" ]; then
    echo "run=$(python3 scripts/pilot_checks.py run "$d" --warmup-s 0 2>&1 | tr -d '\n ')"
  fi
  if [ -f "$d/integrity.json" ]; then
    echo "verdict=$(python3 scripts/run_integrity.py show "$d" 2>&1 | tr -d '\n')"
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
    """An ssh command that runs a script read from stdin, optionally through the driver."""
    opts = ["-i", key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
            "-o", "StrictHostKeyChecking=accept-new"]
    argv = [ssh] + opts
    if jump:
        argv += ["-o", "ProxyCommand=%s %s -W %%h:%%p ubuntu@%s" % (ssh, " ".join(opts), jump)]
    return argv + ["ubuntu@%s" % host, "bash -s"]


def parse(text):
    """Probe output as a dict. Every run= line becomes one entry of "runs", and every verdict=
    line one entry of "verdicts"."""
    facts = {"runs": [], "verdicts": []}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            continue
        if key in ("run", "verdict"):
            try:
                entry = json.loads(value)
            except ValueError:
                entry = {"unreadable": value}
            facts[key + "s"].append(entry)
        else:
            facts[key] = value.strip()
    return facts


def probe(run, argv, script, timeout=90):
    """(facts, "") from one SSH session, or (None, why) if it could not be read."""
    try:
        done = run(argv, input=script, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if done.returncode != 0:
        lines = (done.stderr or done.stdout or "").strip().splitlines()
        return None, lines[-1] if lines else "ssh exited with %d" % done.returncode
    return parse(done.stdout), ""


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
            if (run.get("trip_median_ms") or 0) > ODD_TRIP_MS:
                flags.append(("WARN", "odd: %s has a median trip of %.1f ms"
                              % (where, run["trip_median_ms"])))
            if (run.get("messages") or 0) < FEW_MESSAGES:
                flags.append(("WARN", "odd: %s carried only %d messages"
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


def evaluate(driver, broker, previous_fails=None):
    """Every flag for one cycle. A machine that could not be read is passed as None."""
    flags = []
    if driver is not None:
        flags += machine_flags("driver", driver)
        busy, _ = cpu_usage(driver.get("cpu1"), driver.get("cpu2"))
        campaign = number(driver, "campaign", int) or 0
        if not campaign and (busy is None or busy < IDLE_BUSY_PCT):
            flags.append(("IDLE", "the machines are running with no campaign; stop them with "
                          "scripts/azure_testbed.py stop --yes"))
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
            flags.append(("ALERT", "pilot: %s check(s) in verdicts.csv are marked no"
                          % driver["verdict_no"]))
        if number(driver, "netns", int) == 0:
            flags.append(("WARN", "receiver: the namespace is gone; run cloud/azure/session.sh"))
        flags += run_flags(driver["runs"])
        flags += verdict_flags(driver["verdicts"])
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
        parts.append("campaign %s" % ("running" if number(facts, "campaign", int) else "none"))
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
                     queue=driver.get("queue") or None)
    else:
        state.update(commit=None, queue=None)
    machines = azure_testbed.profile_hosts(own, profile)
    names = dict((h["role"], n) for n, h in machines)
    if driver is None or broker is None:
        states = power_states(runner, own["resource_group"])
        for role, facts, err in (("driver", driver, driver_err), ("broker", broker, broker_err)):
            if facts is None:
                power = states.get(names[role])
                flags.append(("ALERT", "unreachable: the %s does not answer over SSH (%s)%s"
                              % (role, err, "; Azure says: %s" % power if power else "")))
    hourly = sum(own["hourly_usd"][h["size"]] for _, h in machines)
    lines = ["%s  lane %s, profile %s, about $%.2f an hour while running%s"
             % (stamp, lane, profile, hourly,
                ", commit %s" % state["commit"] if state.get("commit") else "")]
    if driver is not None:
        lines.append("  " + summary("driver", hosts["DRIVER_PUBLIC"], driver))
        lines.append("  runs finished in the last %d min: %d" % (window_min, len(driver["runs"])))
    if broker is not None:
        lines.append("  " + summary("broker", hosts["BROKER_PRIV"], broker))
    lines += ["  %s %s" % (level, message) for level, message in flags] or ["  all clear"]
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
