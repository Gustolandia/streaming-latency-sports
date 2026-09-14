#!/usr/bin/env python3
"""
testbed_watch.py -- watch the Azure testbed from your own computer, and say when something is off.

It changes nothing on the machines. Each cycle opens one SSH session to the driver and one to
the broker (through the driver), reads what is happening, prints one status block and appends it
to runs/azure_watch/. It raises a flag when:

  IDLE     the driver is running, and so billing, with no campaign on it
  stuck    a campaign is running but nothing under ~/sbl has changed for STALE_MIN minutes
  failed   new "[FAIL]" trials appeared in a campaign log since the previous cycle
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

What it cannot see: whether a number is right. It flags numbers no working harness produces,
and leaves the rest to the analysis.

Usage:
    python scripts/testbed_watch.py              # every 5 minutes until Ctrl+C
    python scripts/testbed_watch.py --once       # one check; exit 1 if anything is an ALERT
"""
import argparse
import datetime
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
#: exists, and only runs finished in the last @WINDOW@ minutes are read.
DRIVER_PROBE = COMMON_PROBE + r"""
echo "campaign=$(pgrep -f 'cloud/azure/pilot.sh|cloud/azure/replicate_oracle.sh|cloud/azure/campaign.sh|cloud/campaigns/|run_concurrency_test.py|run_kafka_trial.sh|run_redis_trial.sh' | wc -l)"
echo "stress=$(pgrep -x stress-ng | wc -l)"
echo "netns=$(ip netns list 2>/dev/null | grep -c '^sblrecv')"
cd ~/sbl 2>/dev/null || exit 0
now=$(date +%s)
log=$(ls -t ./*.log 2>/dev/null | head -1)
if [ -n "$log" ]; then
  echo "log=$log"
  echo "log_tail=$(tail -n 1 "$log" | tr -d '\r' | cut -c1-160)"
  echo "log_age_s=$(( now - $(stat -c %Y "$log") ))"
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
    """Probe output as a dict; every run= line becomes one entry of "runs"."""
    facts = {"runs": []}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            continue
        if key == "run":
            try:
                facts["runs"].append(json.loads(value))
            except ValueError:
                facts["runs"].append({"unreadable": value})
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
    if "log" in facts:
        parts.append("log %s %s s ago: %s" % (facts["log"], facts.get("log_age_s", "?"),
                                              facts.get("log_tail", "")))
    return "  ".join(parts)


def cycle(hosts, spec, key, ssh, run, runner, state, stamp, window_min=15):
    """(lines, flags) for one look at the testbed."""
    driver, driver_err = probe(run, ssh_argv(ssh, key, hosts["DRIVER_PUBLIC"]),
                               DRIVER_PROBE.replace("@WINDOW@", str(window_min)))
    broker, broker_err = probe(run, ssh_argv(ssh, key, hosts["BROKER_PRIV"],
                                             jump=hosts["DRIVER_PUBLIC"]), BROKER_PROBE)
    flags = evaluate(driver, broker, state.get("fails"))
    if driver is not None:
        state["fails"] = number(driver, "fails", int)
    names = dict((h["role"], n) for n, h in azure_testbed.profile_hosts(spec, hosts["AZ_PROFILE"]))
    if driver is None or broker is None:
        states = power_states(runner, spec["resource_group"])
        for role, facts, err in (("driver", driver, driver_err), ("broker", broker, broker_err)):
            if facts is None:
                power = states.get(names[role])
                flags.append(("ALERT", "unreachable: the %s does not answer over SSH (%s)%s"
                              % (role, err, "; Azure says: %s" % power if power else "")))
    hourly = sum(spec["hourly_usd"][h["size"]]
                 for _, h in azure_testbed.profile_hosts(spec, hosts["AZ_PROFILE"]))
    lines = ["%s  profile %s, about $%.2f an hour while running"
             % (stamp, hosts["AZ_PROFILE"], hourly)]
    if driver is not None:
        lines.append("  " + summary("driver", hosts["DRIVER_PUBLIC"], driver))
        lines.append("  runs finished in the last %d min: %d" % (window_min, len(driver["runs"])))
    if broker is not None:
        lines.append("  " + summary("broker", hosts["BROKER_PRIV"], broker))
    lines += ["  %s %s" % (level, message) for level, message in flags] or ["  all clear"]
    return lines, flags


def main(argv=None, run=subprocess.run, runner=None, sleep=time.sleep, clock=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Watch the Azure testbed and flag trouble")
    ap.add_argument("--hosts", default=HOSTS_ENV)
    ap.add_argument("--spec", default=azure_testbed.SPEC)
    ap.add_argument("--key", default=KEY)
    ap.add_argument("--ssh", default="ssh")
    ap.add_argument("--interval", type=int, default=300, help="seconds between looks")
    ap.add_argument("--window-min", type=int, default=15,
                    help="read the runs that finished in this many minutes")
    ap.add_argument("--once", action="store_true", help="one look; exit 1 on any ALERT")
    ap.add_argument("--cycles", type=int, default=0, help="stop after this many looks (0: never)")
    ap.add_argument("--log-dir", default=LOG_DIR)
    args = ap.parse_args(argv)
    clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))
    try:
        hosts = read_hosts(args.hosts)
        spec = azure_testbed.load_spec(args.spec)
    except (OSError, ValueError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2
    runner = runner or azure_testbed.make_runner()
    key = os.path.expanduser(args.key)
    os.makedirs(args.log_dir, exist_ok=True)
    cycles = 1 if args.once else args.cycles
    state, alerts, done = {}, False, 0
    try:
        while True:
            now = clock()
            lines, flags = cycle(hosts, spec, key, args.ssh, run, runner, state,
                                 now.strftime("%Y-%m-%d %H:%M:%S UTC"), args.window_min)
            text = "\n".join(lines)
            print(text, file=out)
            path = os.path.join(args.log_dir, "watch_%s.log" % now.strftime("%Y%m%d"))
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
            alerts = alerts or any(level == "ALERT" for level, _ in flags)
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
