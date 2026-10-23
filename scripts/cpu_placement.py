#!/usr/bin/env python3
"""
cpu_placement.py -- where a run puts its consumer, its own processes, its load and the receiver
card's interrupts, where its setup asks: whole_core, sibling_load, irq_cpus and rps_off (plan
version 47, 23 Oct 2026).

Block C asks what real-time priority leaves of the consumer's delay once its thread has a core to
itself. Two hardware threads of one core share that core's execution units, so a thread alone on
a CPU whose sibling runs the load still shares its core. whole_core gives the consumer the first
thread of one physical core, keeps every other process the run starts off both of the core's
threads, and runs the load on every other CPU; sibling_load runs the load on the core's other
threads as well, so that the arm with the sibling loaded is the same setup otherwise.

  core     reads each online CPU's topology/thread_siblings_list under /sys/devices/system/cpu
           and takes the physical core whose first thread is the highest-numbered of any core,
           away from CPU 0, where the boot's own work and the first of each device's interrupt
           queues land. It prints five words for the runner: the consumer's CPU; the core's other
           threads; the CPUs every other process of the run is kept on; the load's CPUs; and the
           load's count, a list being - where it is empty. --out gets the topology, the choice and
           the rule. A machine without hardware threads (the Arm pair) has one thread to a core:
           no sibling is left idle, and none can be loaded (--sibling-load is then refused).
  irqs     the receiver card's interrupts, as scripts/run_facts.py finds them (their names hold
           mlx, mana, eth or hv_netvsc), each with the CPUs it may and does run on, to --out. With
           --set LIST each one's smp_affinity_list is written first and read back; with --restore
           FILE each is given back the smp_affinity_list FILE recorded. A write the kernel refuses
           (it refuses one for an interrupt whose affinity it manages itself) is recorded with
           its reason, and the exit status is 1.
  irq-cpus the CPUs that take the card's interrupts: the list the run gives them (--given), or
           else the CPUs an `irqs` record (--irqs) found each one running on, its effective
           affinity, printed as a list and its count, for a load that runs where the interrupts
           are taken (load_kind udp). With --avoid LIST it fails where they share a CPU with
           LIST, the consumer's core.
  rps      the receive queues of each --dev and the CPUs Receive Packet Steering hands their
           packets to (rps_cpus, a mask in hexadecimal; 0 is none, the packets staying on the CPU
           that took the interrupt), to --out. With --set MASK each queue's mask is written first
           and read back; with --restore FILE each queue FILE names is given back its mask.

Nothing is moved that the setup does not name; the runner records what it moves before and after
the run either way, and puts it back afterwards. Every reader takes `root`, so that the tests can
point it at a tree of their own.

CLI:
    python3 scripts/cpu_placement.py core [--sibling-load] --out RUN_DIR/core_choice.json
    python3 scripts/cpu_placement.py irqs --out RUN_DIR/irq_affinity_before.json
    sudo python3 scripts/cpu_placement.py irqs --set 2-3 --out RUN_DIR/irq_affinity_set.json
    sudo python3 scripts/cpu_placement.py irqs --restore RUN_DIR/irq_affinity_before.json \
        --out RUN_DIR/irq_affinity_restored.json
    python3 scripts/cpu_placement.py irq-cpus --irqs RUN_DIR/irq_affinity_before.json [--given 3]
    sudo python3 scripts/cpu_placement.py rps --dev eth0 --set 0 --out RUN_DIR/rps_set.json
Exit codes: 0 done; 1 a core, an interrupt or a queue could not be placed, as --out says; 2 usage.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_facts  # noqa: E402

#: Where the kernel lists the online CPUs, and each one's hardware threads.
ONLINE = "sys/devices/system/cpu/online"
SIBLINGS = "sys/devices/system/cpu/cpu%d/topology/thread_siblings_list"
#: Where the kernel lists a device's queues; a receive queue is rx-<n>, and its RPS mask rps_cpus.
QUEUES = "sys/class/net/%s/queues"
#: The rule the core is chosen by, written beside the choice.
RULE = ("the physical core whose first thread is the highest-numbered of the online cores, away "
        "from CPU 0; the consumer on that first thread, every other process of the run off the "
        "core, and the load on every other online CPU, and on the core's other threads where "
        "the setup loads them")


def parse_list(text):
    """[cpu, ...] from a list as the kernel writes one: "0-3,6" is [0, 1, 2, 3, 6]. Anything else
    is a ValueError."""
    found = []
    for part in text.strip().split(","):
        low, dash, high = part.partition("-")
        if not low.isdigit() or (dash and not high.isdigit()):
            raise ValueError("%r is not a list of CPUs" % text)
        first, last = int(low), int(high) if dash else int(low)
        if last < first:
            raise ValueError("%r is not a list of CPUs" % text)
        found.extend(range(first, last + 1))
    return sorted(set(found))


def format_list(cpus):
    """The kernel's own form of a list, ranges joined: [0, 1, 2, 3, 6] is "0-3,6"."""
    parts, cpus = [], sorted(cpus)
    start = 0
    for i in range(1, len(cpus) + 1):
        if i == len(cpus) or cpus[i] != cpus[i - 1] + 1:
            first, last = cpus[start], cpus[i - 1]
            parts.append("%d" % first if first == last else "%d-%d" % (first, last))
            start = i
    return ",".join(parts)


def topology(root="/"):
    """(online CPUs, {cpu: its online hardware threads}) as the kernel lists them. A file that
    cannot be read or parsed is a ValueError that names it."""
    text, why = run_facts.read_text(root, ONLINE)
    if text is None:
        raise ValueError("the online CPUs " + why)
    online = parse_list(text)
    siblings = {}
    for cpu in online:
        text, why = run_facts.read_text(root, SIBLINGS % cpu)
        if text is None:
            raise ValueError("CPU %d's hardware threads %s" % (cpu, why))
        siblings[cpu] = sorted({cpu} | {c for c in parse_list(text) if c in online})
    return online, siblings


def choose_core(online, siblings, sibling_load=False):
    """{core, consumer_cpu, siblings, kit_cpus, load_cpus, sibling_load} by RULE. Loading the
    siblings of a core that has none is a ValueError."""
    cores = sorted({tuple(threads) for threads in siblings.values()})
    core = max(cores, key=lambda threads: threads[0])
    others = [cpu for cpu in online if cpu not in core]
    if sibling_load and len(core) < 2:
        raise ValueError("CPU %d's core has no other hardware thread to load" % core[0])
    return {"core": list(core), "consumer_cpu": core[0], "siblings": list(core[1:]),
            "kit_cpus": others, "load_cpus": others + (list(core[1:]) if sibling_load else []),
            "sibling_load": sibling_load}


def core(root, out_path, sibling_load=False):
    """The `core` subcommand: the choice, written to `out_path`, and the runner's five words."""
    online, siblings = topology(root)
    chosen = choose_core(online, siblings, sibling_load)
    lists = {name: format_list(chosen[name]) for name in ("siblings", "kit_cpus", "load_cpus")}
    record = dict(chosen, online=format_list(online), rule=RULE, t_ns=time.time_ns(),
                  topology={str(cpu): format_list(threads) for cpu, threads in siblings.items()},
                  siblings_list=lists["siblings"], kit_list=lists["kit_cpus"],
                  load_list=lists["load_cpus"])
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return "%d %s %s %s %d" % (chosen["consumer_cpu"], lists["siblings"] or "-",
                               lists["kit_cpus"] or "-", lists["load_cpus"] or "-",
                               len(chosen["load_cpus"]))


def write_value(path, value):
    """Write one setting into a file of the kernel's; the reason, or None where it took."""
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(value + "\n")
    except OSError as exc:
        return "the kernel refused %s: %s" % (value, exc)
    return None


def given_back(item, given, root):
    """One interrupt given `given`, and read back: the reason it did not take, or None."""
    rel = "proc/irq/%d/smp_affinity_list" % item["irq"]
    refused = write_value(os.path.join(root, rel), given)
    item["smp_affinity_list"], _ = run_facts.stripped(run_facts.read_text(root, rel))
    if refused is None and (item["smp_affinity_list"] is None
                            or parse_list(item["smp_affinity_list"]) != parse_list(given)):
        refused = "read back as %s, not %s" % (item["smp_affinity_list"], given)
    return refused


def irqs(root, out_path, set_to=None, restore=None):
    """The `irqs` subcommand: the card's interrupts, after each is set or restored where asked,
    into `out_path`. Returns whether every interrupt that was to be moved took its CPUs; a reading
    alone always returns True, with what could not be read under "why"."""
    if set_to is not None:
        parse_list(set_to)
    wanted = {}
    if restore is not None:
        with open(restore, encoding="utf-8") as fh:
            wanted = {item["irq"]: item.get("smp_affinity_list")
                      for item in json.load(fh).get("irqs") or []}
    found, why = run_facts.network_irqs(root)
    record = {"t_ns": time.time_ns(), "set": set_to, "restored_from": restore, "irqs": found,
              "why": why, "refused": {}}
    for item in found or []:
        given = set_to if set_to is not None else wanted.get(item["irq"])
        refused = given_back(item, given, root) if given else None
        if refused:
            record["refused"][str(item["irq"])] = refused
    none_to_move = set_to is not None and found == []
    if none_to_move:
        record["why"] = "no interrupt of the receiver card was found to move"
    moving = set_to is not None or restore is not None
    record["ok"] = not (record["refused"] or none_to_move or (moving and found is None))
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record["ok"]


def interrupt_cpus(irqs_path=None, given=None, avoid=None):
    """The `irq-cpus` subcommand's two words: the CPUs that take the card's interrupts, as a list,
    and their count. A ValueError where there are none, or where they share a CPU with `avoid`."""
    if given is not None:
        cpus = parse_list(given)
    else:
        with open(irqs_path, encoding="utf-8") as fh:
            found = json.load(fh).get("irqs") or []
        cpus = sorted({cpu for item in found if item.get("effective_affinity_list")
                       for cpu in parse_list(item["effective_affinity_list"])})
    if not cpus:
        raise ValueError("no CPU was found taking the receiver card's interrupts")
    shared = sorted(set(cpus) & set(parse_list(avoid))) if avoid is not None else []
    if shared:
        raise ValueError("the card's interrupts are taken on %s, which the consumer's core %s "
                         "keeps for the consumer" % (format_list(shared), avoid))
    return "%s %d" % (format_list(cpus), len(cpus))


def mask_value(text):
    """A mask as the kernel writes one, "00000000,0000000f" or "f", as a number."""
    return int(text.replace(",", ""), 16)


def receive_queues(root, devices):
    """[{device, queue, rps_cpus}] for every receive queue of each device, and {device: why} for a
    device whose queues cannot be listed."""
    found, missing = [], {}
    for device in devices:
        try:
            names = sorted(n for n in os.listdir(os.path.join(root, QUEUES % device))
                           if n.startswith("rx-"))
        except OSError as exc:
            missing[device] = "its queues cannot be listed: %s" % exc
            continue
        for name in names:
            mask, _ = run_facts.stripped(run_facts.read_text(
                root, "%s/%s/rps_cpus" % (QUEUES % device, name)))
            found.append({"device": device, "queue": name, "rps_cpus": mask})
    return found, missing


def rps(root, out_path, devices, set_to=None, restore=None):
    """The `rps` subcommand: each receive queue's RPS mask, after it is set or restored where
    asked, into `out_path`. Returns whether every queue that was to be changed took its mask, and
    every device asked for was there."""
    if set_to is not None:
        mask_value(set_to)
    wanted = {}
    if restore is not None:
        with open(restore, encoding="utf-8") as fh:
            before = json.load(fh)
        wanted = {(q["device"], q["queue"]): q.get("rps_cpus") for q in before.get("queues") or []}
        devices = sorted({device for device, _ in wanted} | set(devices))
    found, missing = receive_queues(root, devices)
    record = {"t_ns": time.time_ns(), "devices": list(devices), "set": set_to,
              "restored_from": restore, "queues": found, "missing": missing, "refused": {}}
    for queue in found:
        given = set_to if set_to is not None else wanted.get((queue["device"], queue["queue"]))
        if not given:
            continue
        rel = "%s/%s/rps_cpus" % (QUEUES % queue["device"], queue["queue"])
        refused = write_value(os.path.join(root, rel), given)
        queue["rps_cpus"], _ = run_facts.stripped(run_facts.read_text(root, rel))
        if refused is None and (queue["rps_cpus"] is None
                                or mask_value(queue["rps_cpus"]) != mask_value(given)):
            refused = "read back as %s, not %s" % (queue["rps_cpus"], given)
        if refused:
            record["refused"]["%s/%s" % (queue["device"], queue["queue"])] = refused
    record["ok"] = not (record["refused"] or missing)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record["ok"]


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Where the consumer, the run's processes, the load "
                                             "and the card's interrupts run")
    ap.add_argument("--root", default="/", help="filesystem root; the tests point it at a "
                                                "fake tree")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("core")
    p.add_argument("--out", required=True)
    p.add_argument("--sibling-load", action="store_true",
                   help="the load on the core's other hardware threads too")
    p = sub.add_parser("irq-cpus")
    p.add_argument("--irqs", default=None, help="an `irqs` record")
    p.add_argument("--given", default=None, help="the CPUs the run gives the interrupts")
    p.add_argument("--avoid", default=None, help="CPUs the interrupts' load must stay off")
    for name, value in (("irqs", "a list of CPUs: 0-3,6"), ("rps", "a mask in hexadecimal: 0")):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True)
        move = p.add_mutually_exclusive_group()
        move.add_argument("--set", dest="set_to", default=None, help=value)
        move.add_argument("--restore", default=None, help="an earlier record to put back")
        if name == "rps":
            p.add_argument("--dev", dest="devices", action="append", default=[],
                           help="a device whose receive queues to read; repeated for more")
    args = ap.parse_args(argv)
    try:
        if args.command == "core":
            print(core(args.root, args.out, args.sibling_load), file=out)
            return 0
        if args.command == "irq-cpus":
            print(interrupt_cpus(args.irqs, args.given, args.avoid), file=out)
            return 0
        if args.command == "irqs":
            ok, what = irqs(args.root, args.out, args.set_to, args.restore), "interrupts"
        else:
            ok, what = rps(args.root, args.out, args.devices, args.set_to,
                           args.restore), "receive queues"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 1
    print("%s the receiver's %s -> %s" % ("OK" if ok else "FAILED", what, args.out), file=out)
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
