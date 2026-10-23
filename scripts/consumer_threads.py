#!/usr/bin/env python3
"""
consumer_threads.py -- the consumer's list of its own threads, waited for before the producer
starts, and, where the setup asks (fetch_rt), each thread that sends the fetches raised to
real-time priority before any message is sent.

Plan version 47 (23 Oct 2026). Block K asks what each Kafka client's fetching does when the thread
that sends its fetches never waits for a core. Three consumers write their threads under
--threads-out, once the group has assigned them the partitions, one row each with the columns
tid, name, role and runtime_name:

  scripts/kafka_consumer_confluent.py   rdk:broker<N>, role fetch, for each assigned partition's
                                        leader; the thread that calls poll(), role poll
  harness/java's LawConsumer            law-poll, role poll+fetch: under the classic protocol the
                                        thread that polls sends every fetch
  harness/go's franz-consumer           no role in any row: Go names no thread, and no OS thread
                                        is the fetching one, so only the whole process can be
                                        raised (harness/go/README.md)

scripts/run_kafka_trial.sh starts such a consumer in the background and runs this before the
producer, so that no message is sent before the group has its partitions and, where asked, the
fetch threads have their policy:

  wait     until the list is there. Each consumer writes it beside its path and then moves it
           onto it, so the list is never read half written. The consumer's process ending first,
           or --timeout-s passing, fails the trial: a run whose consumer never joined its group
           would wait out its messages at the broker.
  raise    with --priority P, `chrt -f -p P <tid>` for each thread whose role holds fetch, and
           each thread's policy then read back from /proc/<tid>/stat. A list with no such row
           fails the trial, as a raise that did not take does: a run that asked for its fetch
           thread at real-time priority must never run with nothing raised.
  record   --out gets the list as it was read, when the wait began and when the list was found,
           and for each raise when it was made, the command, its exit status, what it printed
           and the policy read back. It is written whatever happened, with the reason where the
           trial is failed.

The process is checked through /proc rather than with a signal: the consumer runs behind sudo,
whose process this user may not signal, and a process that has ended but not yet been reaped is
taken as ended.

CLI:
    python3 scripts/consumer_threads.py --threads runs/RUN/consumer_tids.csv --pid PID \
        --out runs/RUN/consumer_threads.json [--timeout-s 60] [--priority 80] [--chrt "sudo chrt"]
Exit codes: 0 the list was read, and every fetch thread raised where asked; 1 the trial fails,
for the reason printed last; 2 usage.
"""
import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_facts  # noqa: E402

#: --threads-out's columns, as the three consumers that write the list write them.
COLUMNS = ["tid", "name", "role", "runtime_name"]
#: The role a row carries when its thread sends the fetches, alone or beside another (poll+fetch).
FETCH = "fetch"
#: Where the kernel shows each process and thread, by id. A module constant, so that the tests can
#: point it at a tree of their own.
PROC = "/proc"
#: How often the list and the consumer's process are looked at while the wait lasts.
LOOK_S = 0.1
#: How long one chrt may take before it counts as one that did not run.
CHRT_TIMEOUT_S = 10.0


class Failed(Exception):
    """The trial fails, for the reason given."""


def alive(pid, proc=PROC):
    """Whether the process `pid` is still running: its stat can be read and it is no zombie."""
    text, _ = run_facts.read_text(proc, os.path.join(str(pid), "stat"))
    if text is None:
        return False
    try:
        return text[text.rindex(")") + 1:].split()[0] != "Z"
    except (ValueError, IndexError):
        return True


def read_rows(path):
    """The thread list's rows, as dicts, held to the three consumers' columns."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != COLUMNS:
            raise Failed("%s has the columns %s, not %s" % (path, reader.fieldnames, COLUMNS))
        return list(reader)


def wait_for(path, pid, timeout_s, proc=PROC, clock=time.monotonic, sleep=time.sleep):
    """The thread list's rows once the consumer has written them. Fails where the consumer's
    process ends first, or where `timeout_s` passes with no list."""
    deadline = clock() + timeout_s
    while True:
        if os.path.exists(path):
            return read_rows(path)
        if not alive(pid, proc):
            raise Failed("the consumer's process %d ended before it wrote its thread list %s; "
                         "see its log" % (pid, path))
        if clock() >= deadline:
            raise Failed("the consumer wrote no thread list at %s within %g s: it never had its "
                         "partitions assigned" % (path, timeout_s))
        sleep(LOOK_S)


def fetching(rows):
    """The rows whose role holds fetch."""
    return [row for row in rows if FETCH in (row.get("role") or "").split("+")]


def policy_of(tid, proc=PROC):
    """(policy name, real-time priority) of thread `tid`, from /proc/<tid>/stat, or (None, None)
    where it cannot be read."""
    text, _ = run_facts.read_text(proc, os.path.join(str(tid), "stat"))
    try:
        found = run_facts.thread_stat(text or "")
    except (ValueError, IndexError):
        return None, None
    return found["policy_name"], found["rt_priority"]


def raise_thread(row, priority, chrt, proc=PROC, run=subprocess.run, now_ns=time.time_ns):
    """`chrt -f -p PRIORITY <tid>` for one row of the list, and what it left: when it was run,
    the command, its exit status, what it printed and the policy read back. "ok" only where the
    command exited 0 and the thread then holds SCHED_FIFO at that priority."""
    done = {"tid": row.get("tid"), "name": row.get("name"), "role": row.get("role"),
            "runtime_name": row.get("runtime_name"), "t_ns": now_ns(), "command": None,
            "exit": None, "said": "", "policy_after": None, "rt_priority_after": None,
            "ok": False}
    tid = (row.get("tid") or "").strip()
    if not tid.isdigit():
        done["said"] = "the row has no kernel id for its thread, so nothing can be raised"
        return done
    command = shlex.split(chrt) + ["-f", "-p", str(priority), tid]
    done["command"] = " ".join(command)
    try:
        ran = run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, timeout=CHRT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        done["said"] = "could not run: %s" % exc
        return done
    done["exit"] = ran.returncode
    done["said"] = (ran.stdout + ran.stderr).decode("utf-8", "replace").strip()
    done["policy_after"], done["rt_priority_after"] = policy_of(tid, proc)
    done["ok"] = (ran.returncode == 0 and done["policy_after"] == "SCHED_FIFO"
                  and done["rt_priority_after"] == priority)
    return done


def settle(args, record, run, clock, sleep, now_ns):
    """Wait for the list, then raise its fetch threads where asked, into `record`."""
    rows = wait_for(args.threads, args.pid, args.timeout_s, args.proc, clock, sleep)
    record.update(t_listed_ns=now_ns(), rows=rows)
    if args.priority is None:
        return
    found = fetching(rows)
    if not found:
        raise Failed("the consumer's thread list names no thread whose role holds fetch, so its "
                     "fetches cannot be raised alone; a consumer that sends them from no thread "
                     "of its own (franz-go) can only be raised whole")
    for row in found:
        record["raised"].append(raise_thread(row, args.priority, args.chrt, args.proc, run,
                                             now_ns))
    missed = [done for done in record["raised"] if not done["ok"]]
    if missed:
        raise Failed("%d of the %d fetch threads did not take SCHED_FIFO %d: thread %s (%s) "
                     "exited %s, now %s %s: %s"
                     % (len(missed), len(found), args.priority, missed[0]["tid"],
                        missed[0]["name"], missed[0]["exit"], missed[0]["policy_after"],
                        missed[0]["rt_priority_after"], missed[0]["said"] or "nothing said"))


def main(argv=None, out=None, run=subprocess.run, clock=time.monotonic, sleep=time.sleep,
         now_ns=time.time_ns):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Wait for the consumer's thread list, and raise its "
                                             "fetch threads where asked")
    ap.add_argument("--threads", required=True, help="the consumer's --threads-out")
    ap.add_argument("--pid", type=int, required=True, help="the consumer's process")
    ap.add_argument("--out", required=True, help="what was found and done, as JSON")
    ap.add_argument("--timeout-s", type=float, default=60.0)
    ap.add_argument("--priority", type=int, default=None, choices=range(1, 100),
                    metavar="1-99", help="raise each fetch thread to SCHED_FIFO at this priority")
    ap.add_argument("--chrt", default="sudo chrt", help="the chrt to run, with what runs it")
    ap.add_argument("--proc", default=PROC, help="where the kernel shows its processes")
    args = ap.parse_args(argv)
    record = {"threads": args.threads, "pid": args.pid, "priority": args.priority,
              "t_wait_ns": now_ns(), "t_listed_ns": None, "rows": None, "raised": [],
              "ok": False, "why": ""}
    try:
        settle(args, record, run, clock, sleep, now_ns)
        record["ok"] = True
    except (Failed, OSError, ValueError, csv.Error) as exc:
        record["why"] = str(exc)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    if not record["ok"]:
        print("FATAL: %s" % record["why"], file=out)
        return 1
    print("OK consumer threads: %d listed, %d raised to SCHED_FIFO %s -> %s"
          % (len(record["rows"]), len(record["raised"]), args.priority, args.out), file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
