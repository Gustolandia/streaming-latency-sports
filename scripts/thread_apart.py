#!/usr/bin/env python3
"""
thread_apart.py -- every thread of the consumer's process but its main one moved onto the other
hardware threads of the core the run keeps for the consumer, as soon as it exists, so that the
main thread has the consumer's CPU to itself, where the setup asks (threads_apart).

Plan version 48 (23 Oct 2026). Block C runs kafka-python's consumer at SCHED_FIFO 80 on the first
thread of a core kept for it (whole_core). The taskset that pins it there is inherited by every
thread it starts, and kafka-python starts one beside the main thread when the consumer first
joins its group: the heartbeat thread, at the same priority on the same CPU. Two SCHED_FIFO
threads of one priority on one CPU take no turns, the one running keeping the CPU until it
blocks; in block C's pilot, with the card's interrupts on that CPU as well, the heartbeat thread
never ran, and the broker removed the consumer from its group once its 10 s session timeout had
passed. cloud/azure/campaign.sh runs this through sudo, in the background, from the trial's start:

  find     the consumer's own process, by its command line: a Python interpreter running
           scripts/kafka_consumer.py with the run's --run-id. The wraps that start it (taskset,
           sudo, chrt and ip netns exec) hold the same words further along their own command
           lines, and none of them is Python. It is waited for, --find-s at most.
  move     every --every-ms, until the process ends or the runner stops this: each of its
           threads but the main one, whose id is the process's, that may run anywhere but on
           exactly --siblings, as /proc/PID/task/TID/status lists its CPUs, is given --siblings
           with sched_setaffinity and read back. The heartbeat thread starts only at the group's
           first join, so the watch lasts as long as the consumer runs. A move that did not take
           is not tried again: what refused it would refuse it again.
  record   --out gets each move (the thread, its name, when, its CPUs before and after, and why
           it did not take where it did not), each thread's name and CPUs as last seen, the CPUs
           the main thread was seen on, and whether that was --cpu alone at every look. It is
           written whatever happened, with the reason where the threads were not kept apart: a
           process never found, a move that did not take, or a thread that ended before it could
           be moved, having run its whole life beside the main one. Nothing here stops the run;
           the integrity rule reads the record (scripts/run_integrity.py).

The process is looked at through /proc, as scripts/consumer_threads.py looks at it: one that has
ended but not yet been reaped is taken as ended, and so is one whose id another program has taken
since. SIGINT or SIGTERM stops the watch, and the record is still written. The readers take
`proc` and the moves go through `move`, so that the tests can point both at stand-ins of their
own; os.sched_setaffinity is Linux's alone, and is looked up only where no other is given.

CLI:
    sudo python3 scripts/thread_apart.py --out runs/RUN/thread_apart.json --run-id RUN \\
        --cpu 6 --siblings 7 [--every-ms 50] [--find-s 60]
Exit codes: 0 every thread of the consumer's but its main one ended on --siblings, and the main
thread was on --cpu alone at every look; 1 they were not, for the reason --out gives; 2 usage.
"""
import argparse
import json
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import consumer_threads  # noqa: E402
import cpu_placement  # noqa: E402
import run_facts  # noqa: E402

#: The consumer whose threads are moved, by the script its interpreter runs. Named here and never
#: on this program's own command line, where the patterns that find the clients (campaign.sh's
#: reap, scripts/run_facts.py's names) would take this for the consumer.
CONSUMER_SCRIPT = "kafka_consumer.py"
#: Where the kernel shows each process and thread, by id. A module constant, so that the tests can
#: point it at a tree of their own.
PROC = "/proc"
#: How often the consumer's threads are looked at, and how long its process is waited for.
EVERY_MS = 50.0
FIND_S = 60.0


def command_line(pid, proc=PROC):
    """A process's command line as its words, or None where it cannot be read."""
    text, _ = run_facts.read_text(proc, os.path.join(str(pid), "cmdline"))
    return None if text is None else [word for word in text.split("\0") if word]


def is_consumer(argv, run_id):
    """Whether a command line is the consumer's own process: a Python interpreter running
    CONSUMER_SCRIPT with the run's --run-id, as the trial runner starts it."""
    if not argv or not os.path.basename(argv[0]).startswith("python"):
        return False
    if CONSUMER_SCRIPT not in [os.path.basename(word) for word in argv[1:]]:
        return False
    return ("--run-id", run_id) in zip(argv, argv[1:]) or "--run-id=" + run_id in argv


def find(run_id, proc=PROC):
    """The ids of every process whose command line is the consumer's own, in order; none where
    the processes cannot be listed."""
    try:
        names = os.listdir(proc)
    except OSError:
        return []
    return [int(name) for name in sorted((n for n in names if n.isdigit()), key=int)
            if is_consumer(command_line(name, proc), run_id)]


def still_running(pid, run_id, proc=PROC):
    """Whether the consumer's process still runs under its id: not ended, and not another."""
    return consumer_threads.alive(pid, proc) and is_consumer(command_line(pid, proc), run_id)


def thread_ids(pid, proc=PROC):
    """The ids of the process's threads, in order, or None where they cannot be listed."""
    try:
        names = os.listdir(os.path.join(proc, str(pid), "task"))
    except OSError:
        return None
    return sorted(int(name) for name in names if name.isdigit())


def look(pid, tid, proc=PROC):
    """(its name, the CPUs it may run on as the kernel lists them) of one thread, the CPUs None
    where its status gives none; or None where the thread has gone."""
    where = os.path.join(str(pid), "task", str(tid))
    status, _ = run_facts.read_text(proc, os.path.join(where, "status"))
    if status is None:
        return None
    comm, _ = run_facts.stripped(run_facts.read_text(proc, os.path.join(where, "comm")))
    return comm, run_facts.cpus_allowed(status)


def exactly(listed, cpus):
    """Whether a list as the kernel writes one names exactly `cpus`."""
    try:
        return listed is not None and cpu_placement.parse_list(listed) == sorted(cpus)
    except ValueError:
        return False


def sibling_cpus(text, cpu):
    """The CPUs the other threads go on, from a list as the kernel writes one. A list that holds
    the consumer's own CPU is a ValueError: no thread moved onto it would be apart."""
    cpus = cpu_placement.parse_list(text)
    if cpu in cpus:
        raise ValueError("the siblings %s hold the consumer's own CPU %d, so no thread moved onto "
                         "them would be apart from its main one" % (text, cpu))
    return cpus


def move(pid, tid, comm, before, siblings, proc, setaffinity, now_ns):
    """One thread given the siblings, and read back: when, its CPUs before and after, whether it
    took, and why not where it did not."""
    done = {"tid": tid, "comm": comm, "t_ns": now_ns(), "affinity_before": before,
            "affinity_after": None, "ok": False, "why": ""}
    if setaffinity is None:
        done["why"] = "this system has no sched_setaffinity"
        return done
    try:
        setaffinity(tid, set(siblings))
    except OSError as exc:
        done["why"] = "the kernel refused it: %s" % exc
    seen = look(pid, tid, proc)
    done["affinity_after"] = None if seen is None else seen[1]
    if not done["why"] and seen is None:
        done["why"] = "the thread had gone before its CPUs could be read back"
    elif not done["why"] and not exactly(seen[1], siblings):
        done["why"] = "read back as %s, not %s" % (seen[1], cpu_placement.format_list(siblings))
    done["ok"] = not done["why"]
    return done


def wait_for(run_id, find_s, proc, clock, sleep, every_ms, stop):
    """Every id whose command line is the consumer's own, once one is there; none where `find_s`
    passes first, or the runner stops this."""
    deadline = clock() + find_s
    while not stop:
        found = find(run_id, proc)
        if found or clock() >= deadline:
            return found
        sleep(every_ms / 1000.0)
    return []


def watch(record, setaffinity, proc, sleep, now_ns, stop):
    """Every thread of the process but its main one moved onto the siblings as soon as it is
    seen, until the process ends or the runner stops this, into `record`."""
    pid, siblings = record["pid"], record["siblings"]
    last, refused, main_seen = {}, set(), []
    while not stop and still_running(pid, record["run_id"], proc):
        tids = thread_ids(pid, proc)
        if tids is None:
            break
        record["looks"] += 1
        for tid in tids:
            seen = look(pid, tid, proc)
            if seen is None:
                continue
            comm, cpus = seen
            if tid == pid:
                if cpus not in main_seen:
                    main_seen.append(cpus)
            elif tid not in refused and not exactly(cpus, siblings):
                done = move(pid, tid, comm, cpus, siblings, proc, setaffinity, now_ns)
                record["moves"].append(done)
                if not done["ok"]:
                    refused.add(tid)
                if done["affinity_after"] is not None:
                    cpus = done["affinity_after"]
            last[tid] = {"tid": tid, "comm": comm, "affinity": cpus, "main": tid == pid}
        sleep(record["every_ms"] / 1000.0)
    record["ended_by"] = "stopped" if stop else "the process ended"
    record["tasks"] = [last[tid] for tid in sorted(last)]
    record["main_affinity_seen"] = main_seen
    record["main_alone"] = bool(main_seen) and all(exactly(cpus, [record["cpu"]])
                                                   for cpus in main_seen)


def judged(record):
    """Why the record does not show the consumer's other threads apart from its main one, or ""
    where it does."""
    others = [t for t in record["tasks"] if not t["main"]]
    stray = [t for t in others if not exactly(t["affinity"], record["siblings"])]
    if stray:
        refused = [m["why"] for m in record["moves"] if m["tid"] == stray[0]["tid"] and m["why"]]
        return ("%d of the consumer's %d other thread(s) ended off %s: thread %d (%s) on %s%s"
                % (len(stray), len(others), record["siblings_list"], stray[0]["tid"],
                   stray[0]["comm"], stray[0]["affinity"], ": " + refused[-1] if refused else ""))
    if not record["looks"]:
        return ("the consumer's threads were never looked at: %s as soon as its process was "
                "found" % ("the runner stopped this" if record["ended_by"] == "stopped"
                           else "it ended"))
    if not record["main_alone"]:
        return ("the consumer's main thread was seen on %s, not on CPU %d alone"
                % (" and ".join(str(cpus) for cpus in record["main_affinity_seen"]) or "no CPU",
                   record["cpu"]))
    return ""


def main(argv=None, out=None, move=None, clock=time.monotonic, sleep=time.sleep,
         now_ns=time.time_ns, signals=signal.signal):
    stop = []
    for number in (signal.SIGINT, signal.SIGTERM):
        signals(number, lambda *_: stop.append(1))
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Move every thread of the consumer's process but its "
                                             "main one onto its core's other threads")
    ap.add_argument("--out", required=True, help="what was found and moved, as JSON")
    ap.add_argument("--run-id", required=True, help="the run whose consumer's threads are moved")
    ap.add_argument("--cpu", type=int, required=True, help="the consumer's CPU, its main thread's")
    ap.add_argument("--siblings", required=True,
                    help="the core's other threads, as the kernel lists CPUs: 7")
    ap.add_argument("--every-ms", type=float, default=EVERY_MS)
    ap.add_argument("--find-s", type=float, default=FIND_S)
    ap.add_argument("--proc", default=PROC, help="where the kernel shows its processes")
    args = ap.parse_args(argv)
    setaffinity = move if move is not None else getattr(os, "sched_setaffinity", None)
    record = {"run_id": args.run_id, "cpu": args.cpu, "siblings": None,
              "siblings_list": args.siblings, "every_ms": args.every_ms, "find_s": args.find_s,
              "t_start_ns": now_ns(), "t_found_ns": None, "t_end_ns": None, "pid": None,
              "matched": [], "cmdline": None, "looks": 0, "moves": [], "tasks": [],
              "main_affinity_seen": [], "main_alone": False, "ended_by": None, "ok": False,
              "why": ""}
    try:
        record["siblings"] = sibling_cpus(args.siblings, args.cpu)
        record["matched"] = wait_for(args.run_id, args.find_s, args.proc, clock, sleep,
                                     args.every_ms, stop)
        if not record["matched"]:
            record["ended_by"] = "stopped" if stop else "never found"
            record["why"] = ("the runner stopped this before the consumer's process was found"
                             if stop else "no process ran scripts/%s with --run-id %s within %g s"
                             % (CONSUMER_SCRIPT, args.run_id, args.find_s))
        else:
            record["pid"], record["t_found_ns"] = record["matched"][0], now_ns()
            record["cmdline"] = " ".join(command_line(record["pid"], args.proc) or [])
            watch(record, setaffinity, args.proc, sleep, now_ns, stop)
            record["why"] = judged(record)
    except (OSError, ValueError) as exc:
        record["why"] = str(exc)
    record["t_end_ns"], record["ok"] = now_ns(), not record["why"]
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    if not record["ok"]:
        print("FAILED the consumer's threads apart: %s -> %s" % (record["why"], args.out),
              file=out)
        return 1
    print("OK the consumer's threads apart: %d moved onto %s, the main thread on CPU %d alone "
          "-> %s" % (len([m for m in record["moves"] if m["ok"]]), args.siblings, args.cpu,
                     args.out), file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
