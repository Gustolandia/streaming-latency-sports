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
           command line; `uname -a`; eth0's address; and, since plan version 47, which hardware
           threads share each online CPU's core, as the kernel lists them.
  clients  for every process whose command line names one of the clients, and every stress-ng:
           each thread's id, name, scheduling policy and real-time priority, from
           /proc/PID/task/TID/stat, and since plan version 47 the CPUs it may run on, from
           /proc/PID/task/TID/status; the process's cgroup; and its autogroup. Since plan version
           47 the run's own working processes too (its captures, samplers, bpftrace, the socket
           load's duty cycle and the wait on the consumer's threads), so that a run that keeps a
           core for its consumer shows every one of them kept off it.
  softirq  plan version 47 (23 Oct 2026): for each CPU, the packets the kernel's network
           softirq processed and dropped and the times it ran out of its budget with packets
           still waiting (/proc/net/softnet_stat's first three columns, time_squeeze the third);
           and for each ksoftirqd thread, the time it ran and waited and its CPU time
           (/proc/PID/schedstat and stat). Taken before and after a run whose load is heavy in
           softirq work, and with the interrupt counters.
  broker   plan version 47 (23 Oct 2026), run on the broker host: each broker's image and its
           digest, as Docker holds them, and its server's own version: Redis's from INFO server,
           RabbitMQ's from rabbitmq-diagnostics, NATS's from the INFO it greets a client with,
           Kafka's from the name of its server's jar. `--out -` writes the facts to standard
           output, which is how the runner keeps them in each run's folder, and the integrity rule
           holds each run to its own broker's (scripts/run_integrity.py).

A fact that cannot be read, a command that cannot run or a file that is not there, is written as
null, with the reason under "unread" beside it, and nothing here stops a run. A process is found
by what /proc says of it, so one whose command line cannot be read is not one this can name, and
is left out. Every reader of /proc, /sys and /boot takes `root`, so that the tests can point it at
a fake tree, and the host's commands are run through `run`, which the tests replace.

CLI:
    python3 scripts/run_facts.py host --out RUN_DIR/run_facts.json
    python3 scripts/run_facts.py clients --out RUN_DIR/run_facts_clients.json
    python3 scripts/run_facts.py softirq --out RUN_DIR/softirq_before.json
    python3 scripts/run_facts.py broker --out -
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time

#: The commands whose output is a fact, as each is run.
STRESS_NG_VERSION = ("stress-ng", "--version")
IRQBALANCE = ("systemctl", "is-active", "irqbalance")
UNAME = ("uname", "-a")
#: The Python clients' own libraries, as the interpreter the runs use imports them: the driver
#: installs kafka-python>=2.3,<3 (cloud/azure/cloud-init.yaml), and which one ran decides which
#: thread writes a fetch, so each run records it (freeze 43, 22 Oct 2026). Plan version 47 (23 Oct
#: 2026) adds the two its new clients speak through, confluent-kafka with the librdkafka it carries
#: and pika, each named "absent" where it is not installed, so that a driver without them still
#: states the rest.
CLIENT_LIBRARIES = ("python3", "-c", "\n".join([
    "import importlib, sys",
    "said = ['python ' + sys.version.split()[0]]",
    "for name, module in (('kafka-python', 'kafka'), ('redis-py', 'redis'),",
    "                     ('confluent-kafka', 'confluent_kafka'), ('pika', 'pika')):",
    "    try:",
    "        found = importlib.import_module(module)",
    "    except ImportError:",
    "        said.append(name + ' absent')",
    "        continue",
    "    if module == 'confluent_kafka':",
    "        said.append('%s %s librdkafka %s' % (name, found.version()[0], found.libversion()[0]))",
    "    else:",
    "        said.append('%s %s' % (name, found.__version__))",
    "print(' '.join(said))"]))
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
#: The clients, by the script or program each one runs: the four Python clients every block has
#: run, A8's Java client, and since plan version 47 (23 Oct 2026) the consumers on librdkafka,
#: kafka-clients and franz-go, the waiting Redis consumer, and the NATS and RabbitMQ clients, the
#: Go one (harness/go-nats's natsgo-consumer) among them. The Java client runs as
#: `java -cp ... LawConsumer`, so its class's name is a word of its own there.
CLIENT_SCRIPTS = ("kafka_consumer.py", "kafka_producer.py", "redis_consumer.py",
                  "redis_producer.py", "LawProducer", "LawConsumer", "kafka_consumer_confluent.py",
                  "kafka_producer_confluent.py", "franz-consumer", "redis_consumer_waiting.py",
                  "nats_producer.py", "nats_consumer.py", "natsgo-consumer", "rabbitmq_producer.py",
                  "rabbitmq_consumer.py")
#: Plan version 47 (23 Oct 2026): where the kernel lists the online CPUs and each one's hardware
#: threads, kept as the kernel writes them (scripts/cpu_placement.py reads and chooses from them).
CPU_ONLINE = "sys/devices/system/cpu/online"
CPU_SIBLINGS = "sys/devices/system/cpu/cpu%s/topology/thread_siblings_list"
#: The line of /proc/PID/task/TID/status that gives the CPUs a thread may run on.
CPUS_ALLOWED = "Cpus_allowed_list:"
#: Plan version 47 (23 Oct 2026): the run's own working processes, by a word of their command
#: lines: the captures and bpftrace, the samplers, the socket load's duty cycle and the wait on
#: the consumer's thread list.
KIT_PROGRAMS = ("tcpdump", "bpftrace", "util_sampler.py", "phc_offset.py", "schedstat_sampler.py",
                "duty_cycle.py", "consumer_threads.py")
#: Plan version 47 (23 Oct 2026): the containers the brokers run in, by the names cloud/brokers.sh
#: gives them, and where the NATS server, a unit of the broker's own, greets a client.
BROKER_CONTAINERS = {"kafka": "broker", "redis": "redis", "rabbitmq": "rabbitmq"}
NATS_ADDRESS = ("127.0.0.1", 4222)
#: The commands that read the servers' own versions, inside their containers.
REDIS_INFO = ("docker", "exec", "redis", "redis-cli", "INFO", "server")
#: Asked as the broker's own user, as brokers.sh asks: a tool run as root can write the Erlang
#: cookie the broker then cannot read.
RABBITMQ_VERSION = ("docker", "exec", "--user", "rabbitmq", "rabbitmq", "rabbitmq-diagnostics",
                    "-q", "server_version")
#: Kafka's, from the name of its server's jar among the libraries apache/kafka's image keeps in
#: /opt/kafka/libs (kafka_2.13-4.1.1.jar): a listing starts no second JVM beside the broker's, and
#: only a version of digits and dots is taken, so that a test or sources jar is not read as one.
KAFKA_LIBS = ("docker", "exec", "broker", "ls", "/opt/kafka/libs")
KAFKA_JAR = re.compile(r"^kafka_\d+\.\d+-(\d+(?:\.\d+)+)\.jar$", re.M)
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
    """The client script a process's command line names, "stress-ng" for stress-ng's, the kit
    program it runs (KIT_PROGRAMS), or None."""
    for word in argv:
        if os.path.basename(word) in CLIENT_SCRIPTS:
            return os.path.basename(word)
    if is_stress_ng(root, pid, argv):
        return STRESS_NG
    for word in argv:
        if os.path.basename(word) in KIT_PROGRAMS:
            return os.path.basename(word)
    return None


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


def cpus_allowed(text):
    """The CPUs a thread may run on, from its status file's Cpus_allowed_list line, or None."""
    for line in text.splitlines():
        if line.startswith(CPUS_ALLOWED):
            return line[len(CPUS_ALLOWED):].strip()
    return None


def thread_facts(root, pid, tid):
    """{tid, comm, policy, policy_name, rt_priority, cpus_allowed_list, unread} for one thread.

    Plan version 47 (23 Oct 2026): the CPUs it may run on, as the kernel holds them, so that a run
    that pins its consumer to one core (whole_core) shows the pin took on every thread."""
    found = {"tid": int(tid), "comm": None, "policy": None, "policy_name": None,
             "rt_priority": None, "cpus_allowed_list": None, "unread": {}}
    text, why = read_text(root, os.path.join("proc", pid, "task", tid, "status"))
    if text is None:
        found["unread"]["status"] = why
    else:
        found["cpus_allowed_list"] = cpus_allowed(text)
        if found["cpus_allowed_list"] is None:
            found["unread"]["status"] = "it has no %s line" % CPUS_ALLOWED
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


def cpu_topology(root="/"):
    """({online, thread_siblings_list: {cpu: list or None}}, None) as the kernel writes them, or
    (None, why) where the online CPUs cannot be read. A CPU that is offline keeps no topology, and
    its list is None.

    Plan version 47 (23 Oct 2026): which hardware threads share a core decides what keeping a
    core for the consumer means (whole_core), so every run that records its facts keeps them."""
    online, why = stripped(read_text(root, CPU_ONLINE))
    if online is None:
        return None, "the online CPUs " + why
    cpus = sorted(int(name[3:]) for name in os.listdir(os.path.join(root, "sys/devices/system/cpu"))
                  if name.startswith("cpu") and name[3:].isdigit())
    siblings = {str(cpu): stripped(read_text(root, CPU_SIBLINGS % cpu))[0] for cpu in cpus}
    return {"online": online, "thread_siblings_list": siblings}, None


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
    put("cpu_topology", cpu_topology(root))
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


def softnet(root="/"):
    """([{line, processed, dropped, time_squeeze}], None) from /proc/net/softnet_stat, one line a
    CPU, each column in hexadecimal; or (None, why)."""
    text, why = read_text(root, "proc/net/softnet_stat")
    if text is None:
        return None, why
    found = []
    for n, line in enumerate(text.splitlines()):
        fields = line.split()
        try:
            found.append({"line": n, "processed": int(fields[0], 16),
                          "dropped": int(fields[1], 16), "time_squeeze": int(fields[2], 16)})
        except (IndexError, ValueError):
            return None, "line %d is not a softnet_stat line: %r" % (n, line)
    return found, None


def ksoftirqd(root="/"):
    """([{pid, comm, run_ns, wait_ns, slices, utime, stime, unread}], None) for every ksoftirqd
    thread, by its name; or (None, why) where the processes cannot be listed."""
    try:
        listed = pids(root)
    except OSError as exc:
        return None, "the processes cannot be listed: %s" % exc
    found = []
    for pid in listed:
        comm, _ = stripped(read_text(root, os.path.join("proc", pid, "comm")))
        if not (comm or "").startswith("ksoftirqd/"):
            continue
        thread = {"pid": int(pid), "comm": comm, "run_ns": None, "wait_ns": None, "slices": None,
                  "utime": None, "stime": None, "unread": {}}
        text, why = read_text(root, os.path.join("proc", pid, "schedstat"))
        try:
            thread["run_ns"], thread["wait_ns"], thread["slices"] = (
                int(v) for v in text.split()[:3])
        except (AttributeError, ValueError):
            thread["unread"]["schedstat"] = why or "it is not a schedstat line: %r" % text
        text, why = read_text(root, os.path.join("proc", pid, "stat"))
        try:
            rest = text[text.rindex(")") + 1:].split()
            thread["utime"], thread["stime"] = int(rest[11]), int(rest[12])
        except (AttributeError, ValueError, IndexError):
            thread["unread"]["stat"] = why or "it is not a stat line"
        found.append(thread)
    return found, None


def softirq_facts(root="/"):
    """The softirq's facts, as `softirq` writes them."""
    facts, unread = {"kind": "softirq", "t_ns": time.time_ns()}, {}
    for name, value_why in (("softnet", softnet(root)), ("ksoftirqd", ksoftirqd(root))):
        facts[name], why = value_why
        if why is not None:
            unread[name] = why
    facts["unread"] = unread
    return facts


def image_of(container, run):
    """({image, image_id, repo_digests}, None) for a running container, as Docker holds it, or
    (None, why)."""
    said, why = run(("docker", "inspect", "--format", "{{.Config.Image}} {{.Image}}", container))
    if said is None:
        return None, why
    image, _, image_id = said.partition(" ")
    digests, why = run(("docker", "image", "inspect", "--format", "{{json .RepoDigests}}",
                        image_id.strip()))
    try:
        repo_digests = json.loads(digests)
    except (TypeError, ValueError):
        repo_digests = None
        why = why or "its digests are not JSON: %r" % digests
    return {"image": image, "image_id": image_id.strip(), "repo_digests": repo_digests}, why


def nats_info(address=NATS_ADDRESS, connect=socket.create_connection):
    """({version, jetstream, server_id}, None) from the INFO a NATS server greets a client
    with, or (None, why)."""
    try:
        with connect(address, 5) as sock:
            sock.settimeout(5)
            line = sock.makefile("rb").readline().decode("utf-8", "replace")
    except OSError as exc:
        return None, "no NATS server answers at %s:%d: %s" % (address + (exc,))
    if not line.startswith("INFO "):
        return None, "the server's first line is not its INFO: %r" % line[:80]
    try:
        info = json.loads(line[5:])
    except ValueError:
        return None, "its INFO is not JSON: %r" % line[:80]
    return {"version": info.get("version"), "jetstream": info.get("jetstream") is True,
            "server_id": info.get("server_id")}, None


def broker_facts(run=run_command, connect=socket.create_connection):
    """The brokers' facts, as `broker` writes them, read on the broker host."""
    facts, unread = {"kind": "broker", "t_ns": time.time_ns()}, {}

    def put(name, value_why):
        value, why = value_why
        if why is not None:
            unread[name] = why
        return value

    for broker, container in sorted(BROKER_CONTAINERS.items()):
        facts[broker] = {"container": container,
                         "image": put(broker + ".image", image_of(container, run))}
    said = put("kafka.version", run(KAFKA_LIBS))
    found = KAFKA_JAR.search(said or "")
    facts["kafka"]["version"] = found.group(1) if found else None
    if said is not None and not found:
        unread["kafka.version"] = "/opt/kafka/libs holds no kafka_<scala>-<version>.jar"
    said = put("redis.version", run(REDIS_INFO))
    found = re.search(r"^redis_version:(\S+)", said or "", re.M)
    facts["redis"]["version"] = found.group(1) if found else None
    if said is not None and not found:
        unread["redis.version"] = "INFO server names no redis_version"
    said = put("rabbitmq.version", run(RABBITMQ_VERSION))
    facts["rabbitmq"]["version"] = said.splitlines()[-1].strip() if said else None
    facts["nats"] = put("nats", nats_info(NATS_ADDRESS, connect))
    facts["unread"] = unread
    return facts


def main(argv=None, out=None, run=run_command, connect=socket.create_connection):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="The facts of a run's machine and processes")
    ap.add_argument("--root", default="/",
                    help="filesystem root; the tests point it at a fake tree")
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("host", "clients", "softirq", "broker"):
        sub.add_parser(name).add_argument("--out", required=True, help="a file, or - for "
                                                                        "standard output")
    args = ap.parse_args(argv)
    if args.command == "host":
        facts = host_facts(args.root, run)
    elif args.command == "clients":
        facts = client_facts(args.root)
    elif args.command == "softirq":
        facts = softirq_facts(args.root)
    else:
        facts = broker_facts(run, connect)
    text = json.dumps(facts, indent=2, sort_keys=True) + "\n"
    said = "%s facts -> %s, %d unread" % (args.command, args.out, len(facts["unread"]))
    if args.out == "-":
        out.write(text)
        print(said, file=sys.stderr)
        return 0
    try:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as exc:
        print("ERROR: %s" % exc, file=out)
        return 2
    print(said, file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
