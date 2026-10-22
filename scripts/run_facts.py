#!/usr/bin/env python3
"""
run_facts.py -- the facts of a run that no client writes down: where the network's interrupts
may and do run, how the kernel was built and is set to schedule, and how the kernel schedules
each process the run measures and the load beside it.

Freeze 43 (22 Oct 2026, plan version 46). Block U's pilot did not record where the network's
interrupts ran, nor the kernel options and switches the scheduler's accounting rests on, nor how
each client thread was scheduled. cloud/azure/campaign.sh takes two readings where a setup asks
(run_facts): the machine's before the clients start, and the processes' RUN_FACTS_AFTER_S seconds
into the trial, while the clients run.

  host     the output of `stress-ng --version` and the command lines of the stress-ng processes
           running; what `systemctl is-active irqbalance` says; for every numbered interrupt in
           /proc/interrupts whose name mentions mlx, mana, eth or hv_netvsc, the CPUs it may run
           on (smp_affinity_list) and the ones it does (effective_affinity_list); the kernel's
           build options for preemption, the tick, interrupt and steal time accounting, the
           scheduler's statistics and its autogroups, from /boot/config-<release>; the real-time
           throttle and the schedstats and autogroup switches in /proc/sys/kernel; the boot's
           command line; `uname -a`; and eth0's address.
  clients  for every process whose command line names one of the four Python clients, and every
           stress-ng: each thread's id, name, scheduling policy and real-time priority, from
           /proc/PID/task/TID/stat; the process's cgroup; and its autogroup.

A fact that cannot be read, a command that cannot run or a file that is not there, is written as
null, with the reason under "unread" beside it, and nothing here stops a run. A process is found
by what /proc says of it, so one whose command line cannot be read is not one this can name, and
is left out. Every reader of /proc, /sys and /boot takes `root`, so that the tests can point it at
a fake tree, and the host's commands are run through `run`, which the tests replace.

CLI:
    python3 scripts/run_facts.py host --out RUN_DIR/run_facts.json
    python3 scripts/run_facts.py clients --out RUN_DIR/run_facts_clients.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

#: The commands whose output is a fact, as each is run.
STRESS_NG_VERSION = ("stress-ng", "--version")
IRQBALANCE = ("systemctl", "is-active", "irqbalance")
UNAME = ("uname", "-a")
#: The Python clients' own libraries, as the interpreter the runs use imports them: the driver
#: installs kafka-python>=2.3,<3 (cloud/azure/cloud-init.yaml), and which one ran decides which
#: thread writes a fetch, so each run records it (freeze 43, 22 Oct 2026).
CLIENT_LIBRARIES = ("python3", "-c", "import sys, kafka, redis; print('python %s kafka-python %s "
                    "redis-py %s' % (sys.version.split()[0], kafka.__version__, redis.__version__))")
#: How long a command may take before it counts as one that cannot run.
COMMAND_TIMEOUT_S = 10.0
#: The network's interrupts, by a word of their names: the accelerated cards' drivers (mlx, mana),
#: a queue named after its ethN device, and Hyper-V's own network driver.
NETWORK_IRQ_WORDS = ("mlx", "mana", "eth", "hv_netvsc")
#: The kernel build options kept, as /boot/config-<release> writes them, set or not set.
CONFIG_LINE = re.compile(
    r"^(?:# )?(?:CONFIG_PREEMPT\w*|CONFIG_HZ\w*|CONFIG_IRQ_TIME_ACCOUNTING"
    r"|CONFIG_PARAVIRT_TIME_ACCOUNTING|CONFIG_SCHED_INFO|CONFIG_SCHEDSTATS"
    r"|CONFIG_SCHED_AUTOGROUP)(?:=.*| is not set)$")
#: The scheduler's switches kept, from /proc/sys/kernel.
SCHED_SWITCHES = ("sched_rt_runtime_us", "sched_rt_period_us", "sched_schedstats",
                  "sched_autogroup_enabled")
#: The four Python clients, by the script each one runs.
CLIENT_SCRIPTS = ("kafka_consumer.py", "kafka_producer.py", "redis_consumer.py",
                  "redis_producer.py")
#: stress-ng's processes, by the start of their names: the parent's is stress-ng, and each
#: worker's stress-ng-cpu.
STRESS_NG = "stress-ng"
#: The scheduling policies, numbered as include/uapi/linux/sched.h numbers them.
POLICIES = {0: "SCHED_OTHER", 1: "SCHED_FIFO", 2: "SCHED_RR", 3: "SCHED_BATCH",
            5: "SCHED_IDLE", 6: "SCHED_DEADLINE"}
#: Where rt_priority and policy fall in /proc/PID/task/TID/stat once the name is taken out: proc(5)
#: numbers the fields from 1, the state is field 3 and the first after the name, rt_priority is
#: field 40 and policy field 41.
RT_PRIORITY_AT, POLICY_AT = 40 - 3, 41 - 3


def read_text(root, rel):
    """(a file's text, None), or (None, why) where it cannot be read."""
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as fh:
            return fh.read(), None
    except OSError as exc:
        return None, "cannot be read: %s" % exc


def stripped(found):
    """read_text's answer with the text stripped."""
    text, why = found
    return (None, why) if text is None else (text.strip(), None)


def run_command(argv, timeout=COMMAND_TIMEOUT_S):
    """(what a command printed, None), or (None, why) where it cannot run or says nothing.

    A command that runs and prints has stated a fact, whatever its exit status: `systemctl
    is-active` prints "inactive" and exits 3 for a service that is not running. One that prints
    only to its error stream has stated it there where it exits 0, and has failed otherwise."""
    shown = " ".join(argv)
    try:
        done = subprocess.run(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "%s did not finish within %g s" % (shown, timeout)
    except OSError as exc:
        return None, "%s cannot run: %s" % (shown, exc)
    out = done.stdout.decode("utf-8", "replace").strip()
    err = done.stderr.decode("utf-8", "replace").strip()
    if out:
        return out, None
    if err and done.returncode == 0:
        return err, None
    return None, "%s printed nothing and exited %d%s" % (shown, done.returncode,
                                                        ": " + err if err else "")


def kernel_config(root="/"):
    """(the lines of /boot/config-<release> for the options kept, None), or (None, why)."""
    release, why = stripped(read_text(root, "proc/sys/kernel/osrelease"))
    if release is None:
        return None, "the kernel's release " + why
    text, why = read_text(root, "boot/config-%s" % release)
    if text is None:
        return None, why
    return [line for line in text.splitlines() if CONFIG_LINE.match(line)], None


def network_irqs(root="/"):
    """([{irq, name, smp_affinity_list, effective_affinity_list, unread}], None) for every
    numbered interrupt whose name mentions one of NETWORK_IRQ_WORDS, or (None, why).

    /proc/interrupts heads its table with one column for each CPU online, and an interrupt's line
    is its number, a count for each of those CPUs, and then its name: the chip, the interrupt's
    number on that chip and the names of the handlers it serves."""
    text, why = read_text(root, "proc/interrupts")
    if text is None:
        return None, why
    lines = text.splitlines()
    cpus = len(lines[0].split()) if lines else 0
    found = []
    for line in lines[1:]:
        label, colon, rest = line.partition(":")
        if not colon or not label.strip().isdigit():
            continue
        name = " ".join(rest.split()[cpus:])
        if not any(word in name for word in NETWORK_IRQ_WORDS):
            continue
        irq = {"irq": int(label), "name": name, "unread": {}}
        for kind in ("smp_affinity_list", "effective_affinity_list"):
            irq[kind], why = stripped(read_text(root, "proc/irq/%s/%s" % (label.strip(), kind)))
            if why is not None:
                irq["unread"][kind] = why
        found.append(irq)
    return found, None


def sched_switches(root="/"):
    """({switch: its value or None}, {switch: why}) for SCHED_SWITCHES."""
    values, unread = {}, {}
    for name in SCHED_SWITCHES:
        values[name], why = stripped(read_text(root, "proc/sys/kernel/" + name))
        if why is not None:
            unread[name] = why
    return values, unread


def pids(root="/"):
    """The process ids /proc lists, in order. A /proc that cannot be listed is an OSError."""
    return sorted((name for name in os.listdir(os.path.join(root, "proc")) if name.isdigit()),
                  key=int)


def argv_of(root, pid):
    """A process's command line as its words, or None where it cannot be read."""
    try:
        with open(os.path.join(root, "proc", pid, "cmdline"), "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    return [word.decode("utf-8", "replace") for word in raw.split(b"\0") if word]


def is_stress_ng(root, pid, argv):
    """Whether the process is stress-ng's, by its own name or by the program it runs."""
    comm, _ = stripped(read_text(root, os.path.join("proc", pid, "comm")))
    return ((comm or "").startswith(STRESS_NG)
            or bool(argv) and os.path.basename(argv[0]).startswith(STRESS_NG))


def names(root, pid, argv):
    """The client script a process's command line names, "stress-ng" for stress-ng's, or None."""
    for word in argv:
        if os.path.basename(word) in CLIENT_SCRIPTS:
            return os.path.basename(word)
    return STRESS_NG if is_stress_ng(root, pid, argv) else None


def stress_ng_processes(root="/"):
    """([{pid, comm, cmdline}] for every stress-ng process, None), or (None, why)."""
    try:
        listed = pids(root)
    except OSError as exc:
        return None, "the processes cannot be listed: %s" % exc
    found = []
    for pid in listed:
        argv = argv_of(root, pid)
        if argv is not None and is_stress_ng(root, pid, argv):
            comm, _ = stripped(read_text(root, os.path.join("proc", pid, "comm")))
            found.append({"pid": int(pid), "comm": comm, "cmdline": " ".join(argv)})
    return found, None


def thread_stat(text):
    """{comm, policy, policy_name, rt_priority} from one /proc/PID/task/TID/stat line.

    The name sits between the first "(" and the last ")": a thread may put spaces and brackets of
    its own in its name, and nothing after the name can hold a bracket. A line that is not one
    is a ValueError or an IndexError."""
    comm = text[text.index("(") + 1:text.rindex(")")]
    fields = text[text.rindex(")") + 1:].split()
    policy = int(fields[POLICY_AT])
    return {"comm": comm, "policy": policy, "policy_name": POLICIES.get(policy),
            "rt_priority": int(fields[RT_PRIORITY_AT])}


def thread_facts(root, pid, tid):
    """{tid, comm, policy, policy_name, rt_priority, unread} for one thread."""
    found = {"tid": int(tid), "comm": None, "policy": None, "policy_name": None,
             "rt_priority": None, "unread": {}}
    text, why = read_text(root, os.path.join("proc", pid, "task", tid, "stat"))
    if text is None:
        found["unread"]["stat"] = why
        return found
    try:
        found.update(thread_stat(text))
    except (ValueError, IndexError) as exc:
        found["unread"]["stat"] = "the line cannot be read: %s" % exc
    return found


def process_facts(root, pid, argv, named):
    """{pid, names, cmdline, threads, cgroup, autogroup, unread} for one process."""
    found = {"pid": int(pid), "names": named, "cmdline": " ".join(argv), "threads": None,
             "cgroup": None, "autogroup": None, "unread": {}}
    try:
        tids = sorted((t for t in os.listdir(os.path.join(root, "proc", pid, "task"))
                       if t.isdigit()), key=int)
    except OSError as exc:
        found["unread"]["threads"] = "cannot be listed: %s" % exc
    else:
        found["threads"] = [thread_facts(root, pid, tid) for tid in tids]
    text, why = read_text(root, os.path.join("proc", pid, "cgroup"))
    if text is None:
        found["unread"]["cgroup"] = why
    else:
        found["cgroup"] = [line for line in text.splitlines() if line.strip()]
    found["autogroup"], why = stripped(read_text(root, os.path.join("proc", pid, "autogroup")))
    if why is not None:
        found["unread"]["autogroup"] = why
    return found


def host_facts(root="/", run=run_command):
    """The machine's facts, as `host` writes them."""
    facts, unread = {"kind": "host", "t_ns": time.time_ns()}, {}

    def put(name, value_why):
        facts[name], why = value_why
        if why is not None:
            unread[name] = why

    put("stress_ng_version", run(STRESS_NG_VERSION))
    put("stress_ng", stress_ng_processes(root))
    put("irqbalance", run(IRQBALANCE))
    put("network_irqs", network_irqs(root))
    put("kernel_config", kernel_config(root))
    facts["sched"], missing = sched_switches(root)
    unread.update(("sched." + name, why) for name, why in missing.items())
    put("cmdline", stripped(read_text(root, "proc/cmdline")))
    put("uname", run(UNAME))
    put("client_libraries", run(CLIENT_LIBRARIES))
    put("eth0_address", stripped(read_text(root, "sys/class/net/eth0/address")))
    facts["unread"] = unread
    return facts


def client_facts(root="/"):
    """The clients' and stress-ng's processes, as `clients` writes them."""
    facts = {"kind": "clients", "t_ns": time.time_ns(), "processes": None, "unread": {}}
    try:
        listed = pids(root)
    except OSError as exc:
        facts["unread"]["processes"] = "the processes cannot be listed: %s" % exc
        return facts
    facts["processes"] = []
    for pid in listed:
        argv = argv_of(root, pid)
        named = names(root, pid, argv) if argv is not None else None
        if named is not None:
            facts["processes"].append(process_facts(root, pid, argv, named))
    return facts


def main(argv=None, out=None, run=run_command):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="The facts of a run's machine and processes")
    ap.add_argument("--root", default="/",
                    help="filesystem root; the tests point it at a fake tree")
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("host", "clients"):
        sub.add_parser(name).add_argument("--out", required=True)
    args = ap.parse_args(argv)
    facts = host_facts(args.root, run) if args.command == "host" else client_facts(args.root)
    try:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(facts, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        print("ERROR: %s" % exc, file=out)
        return 2
    print("%s facts -> %s, %d unread" % (args.command, args.out, len(facts["unread"])), file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
