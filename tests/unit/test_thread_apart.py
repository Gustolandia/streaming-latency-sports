"""Tests for scripts/thread_apart.py: every thread of the consumer's process but its main one moved
onto the other threads of the core the run keeps for the consumer, as soon as it exists, where the
setup asks (threads_apart, plan version 48).

The consumer, its wraps and its threads are stood in for by a fake /proc that holds what the kernel
would: each process's command line and stat, and each thread's name and status. sched_setaffinity
is stood in for by a mover that writes the CPUs it is given into the thread's status, so that what
is read back is what a real move would leave; the clock and the sleeps are stand-ins too, and a
sleep can change the tree between two looks, as the consumer does when it starts its heartbeat
thread or ends, and as the runner does when it stops the watch.
"""
import errno
import io
import json
import os
import shutil
import signal
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import cpu_placement  # noqa: E402
import thread_apart as ta  # noqa: E402

RUN = "law_gc_r001-C2000-kafka-core-a1"
#: The consumer's own command line, as scripts/run_kafka_trial.sh starts kafka-python's.
CONSUMER = ["python3", "scripts/kafka_consumer.py", "--run-id", RUN, "--out",
            "runs/%s/consumer.csv" % RUN, "--bootstrap", "10.0.0.4:19092", "--topic",
            "sb-events-%s" % RUN, "--idle-seconds", "15", "--broker-count", "1"]
#: A process's stat line as the kernel writes it, with its state (field 3) to be filled in.
STAT = ("{pid} ({comm}) {state} 1 {pid} {pid} 0 -1 4194560 100 0 0 0 5 3 0 0 -81 0 2 0 100 1000 "
        "100 18446744073709551615 1 1 0 0 0 0 0 0 0 0 0 0 17 6 80 1 0 0 0 0 0 0 0 0 0 0 0\n")
#: A thread's status as the kernel writes it, the lines around the one read kept.
STATUS = ("Name:\t{comm}\nUmask:\t0022\nState:\tS (sleeping)\nTgid:\t{pid}\nPid:\t{tid}\n"
          "Cpus_allowed:\t{mask:x}\nCpus_allowed_list:\t{cpus}\nvoluntary_ctxt_switches:\t12\n")
#: Where nothing is to be stood in for, so that the module looks sched_setaffinity up itself.
LOOKED_UP = object()


class Proc:
    """A fake /proc: processes by their command lines, each with its threads' names and CPUs, laid
    out as the kernel lays them out, beside entries of the kernel's own that name no process."""

    def __init__(self, tmp_path):
        self.root = tmp_path / "proc"
        (self.root / "self").mkdir(parents=True)
        (self.root / "uptime").write_text("100.00 700.00\n", encoding="utf-8")

    def process(self, pid, argv, state="S"):
        where = self.root / str(pid)
        (where / "task").mkdir(parents=True)
        (where / "cmdline").write_bytes(b"".join(word.encode("utf-8") + b"\0" for word in argv))
        self.state(pid, state, os.path.basename(argv[0]) if argv else "kworker/6:1")

    def state(self, pid, state, comm="python3"):
        (self.root / str(pid) / "stat").write_text(STAT.format(pid=pid, comm=comm, state=state),
                                                   encoding="utf-8")

    def consumer(self, pid=4000, cpus="6", state="S"):
        """The consumer's process with its main thread, pinned where taskset put it."""
        self.process(pid, CONSUMER, state)
        self.thread(pid, pid, cpus)

    def thread(self, pid, tid, cpus, comm="python3", status=None):
        where = self.root / str(pid) / "task" / str(tid)
        where.mkdir(parents=True, exist_ok=True)
        (where / "comm").write_text(comm + "\n", encoding="utf-8")
        if status is None:
            mask = sum(1 << cpu for cpu in cpu_placement.parse_list(cpus))
            status = STATUS.format(comm=comm, pid=pid, tid=tid, mask=mask, cpus=cpus)
        (where / "status").write_text(status, encoding="utf-8")

    def cpus_of(self, pid, tid):
        text = (self.root / str(pid) / "task" / str(tid) / "status").read_text(encoding="utf-8")
        return [line.split("\t", 1)[1] for line in text.splitlines()
                if line.startswith("Cpus_allowed_list:")][0]

    def command(self, pid, argv):
        (self.root / str(pid) / "cmdline").write_bytes(b"".join(w.encode() + b"\0" for w in argv))

    def end(self, pid):
        shutil.rmtree(str(self.root / str(pid)))


class Mover:
    """sched_setaffinity stood in for: it writes the CPUs it is given into the thread's status, as
    the kernel would, and keeps each call. A tid in `refuse` is refused as the kernel refuses a
    caller without the right (EPERM); one in `lie` is left as it was; one in `vanish` ends as it
    is moved, before anything can read it back."""

    def __init__(self, proc, pid=4000, refuse=(), lie=(), vanish=()):
        self.proc, self.pid = proc, pid
        self.refuse, self.lie, self.vanish = set(refuse), set(lie), set(vanish)
        self.calls = []

    def __call__(self, tid, cpus):
        self.calls.append((tid, sorted(cpus)))
        if tid in self.refuse:
            raise PermissionError(errno.EPERM, "Operation not permitted")
        where = self.proc.root / str(self.pid) / "task" / str(tid)
        if tid in self.vanish:
            shutil.rmtree(str(where))
        elif tid not in self.lie:
            comm = (where / "comm").read_text(encoding="utf-8").strip()
            self.proc.thread(self.pid, tid, cpu_placement.format_list(cpus), comm)


class Sleeps:
    """time.sleep and time.monotonic stood in for: each sleep moves the clock on by what it was
    asked, and after the sleeps `at` numbers, does what the consumer or the runner does then."""

    def __init__(self, at=None):
        self.now, self.count, self.asked = 0.0, 0, []
        self.at = at or {}

    def clock(self):
        return self.now

    def __call__(self, seconds):
        self.count += 1
        self.asked.append(seconds)
        self.now += seconds
        for then in self.at.get(self.count, ()):
            then()


class Signals:
    """signal.signal stood in for: the handlers main() installs, kept, and sent on asking."""

    def __init__(self):
        self.installed = {}

    def __call__(self, number, handler):
        self.installed[number] = handler

    def send(self, number=signal.SIGINT):
        self.installed[number](number, None)


def run(tmp_path, proc, *extra, mover=None, sleeps=None, signals=None, cpu="6", siblings="7"):
    """thread_apart.main on the fake /proc, into tmp_path/thread_apart.json. (Exit code, what it
    printed, the record.)"""
    out, printed = tmp_path / "thread_apart.json", io.StringIO()
    sleeps = sleeps or Sleeps()
    ticks = iter(range(1, 100000))
    code = ta.main(["--out", str(out), "--run-id", RUN, "--cpu", cpu, "--siblings", siblings,
                    "--proc", str(proc.root)] + list(extra), out=printed,
                   move=(None if mover is LOOKED_UP else mover or Mover(proc)),
                   clock=sleeps.clock, sleep=sleeps, now_ns=lambda: next(ticks) * 1000,
                   signals=signals or Signals())
    return code, printed.getvalue(), json.loads(out.read_text(encoding="utf-8"))


class TestTheConsumerIsFound:

    def test_only_the_consumers_own_python_process_with_the_runs_id_is_taken(self, tmp_path):
        """Go-first's sudo before the pin, taskset, the sudo and ip netns exec of the wrap, the
        sudo -u after it: each holds the consumer's words further along its command line, and
        none of them is Python. Nor is another run's consumer, the producer, this program itself,
        a kernel thread, or a process whose command line cannot be read."""
        proc = Proc(tmp_path)
        wrap = ["sudo", "ip", "netns", "exec", "sblrecv", "sudo", "-u", "tester"]
        proc.process(3000, ["sudo", "chrt", "-f", "80", "taskset", "-c", "6"] + wrap + CONSUMER)
        proc.process(3001, wrap + CONSUMER)
        proc.process(3002, wrap[1:] + CONSUMER)
        proc.process(3003, wrap[5:] + CONSUMER)
        proc.consumer()
        proc.process(4100, ["python3", "scripts/kafka_consumer.py", "--run-id",
                            "law_gc_r000-C2000-kafka-core-a1", "--out", "x.csv"])
        proc.process(4200, ["python3", "scripts/kafka_producer.py", "--run-id", RUN])
        proc.process(4300, ["python3", "scripts/thread_apart.py", "--out",
                            "runs/%s/thread_apart.json" % RUN, "--run-id", RUN, "--cpu", "6",
                            "--siblings", "7"])
        proc.process(4400, [])
        (proc.root / "4500").mkdir()
        assert ta.find(RUN, str(proc.root)) == [4000]

    def test_the_interpreter_may_be_named_in_full_and_the_id_joined_to_its_flag(self):
        assert ta.is_consumer(["/usr/bin/python3.12", "-u", "scripts/kafka_consumer.py",
                               "--run-id=" + RUN], RUN)
        assert not ta.is_consumer(["python3", "scripts/kafka_consumer.py", "--run-id=" + RUN + "x"],
                                  RUN)
        assert not ta.is_consumer(["python3", "scripts/kafka_consumer.py", "--out", RUN], RUN), \
            "the id as another flag's value is not the run's"
        assert not ta.is_consumer(None, RUN)

    def test_a_proc_that_cannot_be_listed_holds_no_consumer(self, tmp_path):
        assert ta.find(RUN, str(tmp_path / "nowhere")) == []

    def test_a_consumer_that_starts_later_is_waited_for(self, tmp_path):
        proc = Proc(tmp_path)
        sleeps = Sleeps({3: [proc.consumer], 5: [lambda: proc.end(4000)]})
        code, _, record = run(tmp_path, proc, sleeps=sleeps)
        assert code == 0 and record["pid"] == 4000 and record["matched"] == [4000]
        assert sleeps.asked[:3] == [0.05] * 3, "looked for every 50 ms"
        assert record["t_start_ns"] < record["t_found_ns"] < record["t_end_ns"]
        assert record["cmdline"] == " ".join(CONSUMER) and record["looks"] == 2

    def test_a_consumer_never_found_is_written_down_and_fails_the_record(self, tmp_path):
        proc = Proc(tmp_path)
        sleeps = Sleeps()
        code, printed, record = run(tmp_path, proc, "--every-ms", "250", "--find-s", "1",
                                    sleeps=sleeps)
        why = "no process ran scripts/kafka_consumer.py with --run-id %s within 1 s" % RUN
        assert code == 1 and printed.startswith("FAILED the consumer's threads apart: " + why)
        assert record["why"] == why and record["ok"] is False and record["pid"] is None
        assert record["ended_by"] == "never found" and sleeps.count == 4
        assert (record["looks"], record["moves"], record["tasks"]) == (0, [], [])
        assert (record["every_ms"], record["find_s"], record["siblings"]) == (250.0, 1.0, [7])

    def test_a_runner_that_stops_it_before_the_consumer_appears_is_written_down(self, tmp_path):
        proc = Proc(tmp_path)
        signals = Signals()
        sleeps = Sleeps({2: [signals.send]})
        code, _, record = run(tmp_path, proc, sleeps=sleeps, signals=signals)
        assert code == 1 and sleeps.count == 2 and record["ended_by"] == "stopped"
        assert record["why"] == "the runner stopped this before the consumer's process was found"
        assert set(signals.installed) == {signal.SIGINT, signal.SIGTERM}


class TestTheThreadsAreMovedApart:

    def test_the_heartbeat_thread_is_moved_as_soon_as_it_starts_and_the_main_one_left(
            self, tmp_path):
        """kafka-python starts its heartbeat thread at the group's first join, on the CPU the
        taskset gave the whole process; it is moved at the first look that sees it, and left
        alone after, and the main thread is never touched."""
        proc = Proc(tmp_path)
        proc.consumer()
        mover = Mover(proc)
        sleeps = Sleeps({2: [lambda: proc.thread(4000, 4001, "6")],
                         5: [lambda: proc.state(4000, "Z")]})
        code, printed, record = run(tmp_path, proc, mover=mover, sleeps=sleeps)
        assert code == 0 and printed.startswith("OK the consumer's threads apart: 1 moved onto 7, "
                                                "the main thread on CPU 6 alone -> ")
        assert mover.calls == [(4001, [7])]
        moved, = record["moves"]
        assert {key: moved[key] for key in ("tid", "comm", "affinity_before", "affinity_after",
                                            "ok", "why")} == {
            "tid": 4001, "comm": "python3", "affinity_before": "6", "affinity_after": "7",
            "ok": True, "why": ""}
        assert record["tasks"] == [
            {"tid": 4000, "comm": "python3", "affinity": "6", "main": True},
            {"tid": 4001, "comm": "python3", "affinity": "7", "main": False}]
        assert record["main_affinity_seen"] == ["6"] and record["main_alone"] is True
        assert (record["looks"], record["ended_by"], record["ok"], record["why"]) == (
            5, "the process ended", True, "")
        assert proc.cpus_of(4000, 4001) == "7" and proc.cpus_of(4000, 4000) == "6"
        assert sleeps.asked == [0.05] * 5, "looked at every 50 ms until the process ended"

    def test_a_thread_already_on_the_siblings_is_left_where_it_is(self, tmp_path):
        proc = Proc(tmp_path)
        proc.consumer()
        proc.thread(4000, 4001, "7")
        mover = Mover(proc)
        code, _, record = run(tmp_path, proc, mover=mover,
                              sleeps=Sleeps({2: [lambda: proc.end(4000)]}))
        assert code == 0 and mover.calls == [] and record["moves"] == []
        assert record["tasks"][1]["affinity"] == "7"

    def test_a_thread_put_back_beside_the_main_one_is_moved_again(self, tmp_path):
        proc = Proc(tmp_path)
        proc.consumer()
        proc.thread(4000, 4001, "6")
        mover = Mover(proc)
        sleeps = Sleeps({2: [lambda: proc.thread(4000, 4001, "6")], 4: [lambda: proc.end(4000)]})
        code, _, record = run(tmp_path, proc, mover=mover, sleeps=sleeps)
        assert code == 0 and mover.calls == [(4001, [7])] * 2
        assert [m["ok"] for m in record["moves"]] == [True, True]

    def test_a_move_the_kernel_refused_is_written_down_tried_once_and_fails_the_record(
            self, tmp_path):
        proc = Proc(tmp_path)
        proc.consumer()
        proc.thread(4000, 4001, "6")
        mover = Mover(proc, refuse={4001})
        code, printed, record = run(tmp_path, proc, mover=mover,
                                    sleeps=Sleeps({4: [lambda: proc.end(4000)]}))
        refused = "the kernel refused it: [Errno %d] Operation not permitted" % errno.EPERM
        assert mover.calls == [(4001, [7])], "what refused it would refuse it again"
        moved, = record["moves"]
        assert (moved["ok"], moved["why"], moved["affinity_after"]) == (False, refused, "6")
        why = "1 of the consumer's 1 other thread(s) ended off 7: thread 4001 (python3) on 6: "
        assert record["why"] == why + refused and record["ok"] is False
        assert code == 1 and printed.startswith("FAILED the consumer's threads apart: " + why)
        assert record["tasks"][1] == {"tid": 4001, "comm": "python3", "affinity": "6",
                                      "main": False}

    def test_a_move_that_changed_nothing_fails_the_record(self, tmp_path):
        proc = Proc(tmp_path)
        proc.consumer()
        proc.thread(4000, 4001, "6", comm="kafka-hb")
        code, _, record = run(tmp_path, proc, mover=Mover(proc, lie={4001}),
                              sleeps=Sleeps({2: [lambda: proc.end(4000)]}))
        assert code == 1 and record["moves"][0]["why"] == "read back as 6, not 7"
        assert record["why"] == ("1 of the consumer's 1 other thread(s) ended off 7: thread 4001 "
                                 "(kafka-hb) on 6: read back as 6, not 7")

    def test_a_thread_that_ended_as_it_was_moved_ran_its_life_beside_the_main_one(self, tmp_path):
        proc = Proc(tmp_path)
        proc.consumer()
        proc.thread(4000, 4001, "6")
        code, _, record = run(tmp_path, proc, mover=Mover(proc, vanish={4001}),
                              sleeps=Sleeps({3: [lambda: proc.end(4000)]}))
        moved, = record["moves"]
        assert (moved["affinity_after"], moved["why"]) == (
            None, "the thread had gone before its CPUs could be read back")
        assert code == 1 and record["tasks"][1]["affinity"] == "6"
        assert record["why"].startswith("1 of the consumer's 1 other thread(s) ended off 7: "
                                        "thread 4001 (python3) on 6: the thread had gone")

    def test_a_thread_listed_but_gone_before_it_is_read_is_passed_over(self, tmp_path):
        proc = Proc(tmp_path)
        proc.consumer()
        (proc.root / "4000" / "task" / "4002").mkdir()
        mover = Mover(proc)
        code, _, record = run(tmp_path, proc, mover=mover,
                              sleeps=Sleeps({2: [lambda: proc.end(4000)]}))
        assert code == 0 and mover.calls == [] and [t["tid"] for t in record["tasks"]] == [4000]

    def test_a_thread_whose_status_names_no_cpus_is_moved_and_read_back(self, tmp_path):
        proc = Proc(tmp_path)
        proc.consumer()
        proc.thread(4000, 4001, "6", status="Name:\tpython3\nState:\tS (sleeping)\n")
        code, _, record = run(tmp_path, proc, sleeps=Sleeps({2: [lambda: proc.end(4000)]}))
        moved, = record["moves"]
        assert code == 0 and (moved["affinity_before"], moved["affinity_after"]) == (None, "7")

    def test_a_system_without_sched_setaffinity_moves_nothing_and_says_so(self, tmp_path,
                                                                          monkeypatch):
        """It is Linux's alone: the module imports and runs anywhere, and moves nothing there."""
        monkeypatch.delattr(os, "sched_setaffinity", raising=False)
        proc = Proc(tmp_path)
        proc.consumer()
        proc.thread(4000, 4001, "6")
        code, _, record = run(tmp_path, proc, mover=LOOKED_UP,
                              sleeps=Sleeps({3: [lambda: proc.end(4000)]}))
        moved, = record["moves"]
        assert (moved["why"], moved["affinity_after"]) == ("this system has no sched_setaffinity",
                                                          None)
        assert code == 1 and record["tasks"][1]["affinity"] == "6"

    def test_a_main_thread_seen_anywhere_but_on_the_consumers_cpu_alone_fails(self, tmp_path):
        proc = Proc(tmp_path)
        proc.consumer()
        sleeps = Sleeps({2: [lambda: proc.thread(4000, 4000, "6-7")], 4: [lambda: proc.end(4000)]})
        code, _, record = run(tmp_path, proc, sleeps=sleeps)
        assert record["main_affinity_seen"] == ["6", "6-7"] and record["main_alone"] is False
        assert code == 1 and record["why"] == ("the consumer's main thread was seen on 6 and 6-7, "
                                               "not on CPU 6 alone")
        assert record["moves"] == [], "the main thread is never moved"

    def test_a_main_thread_never_read_is_not_taken_as_alone(self, tmp_path):
        proc = Proc(tmp_path)
        proc.process(4000, CONSUMER)
        (proc.root / "4000" / "task" / "4000").mkdir()
        code, _, record = run(tmp_path, proc, sleeps=Sleeps({2: [lambda: proc.end(4000)]}))
        assert record["looks"] == 2 and record["main_affinity_seen"] == []
        assert code == 1 and record["why"] == ("the consumer's main thread was seen on no CPU, not "
                                               "on CPU 6 alone")


class TestTheWatchEnds:

    def test_stopped_while_it_watches_it_writes_what_it_saw(self, tmp_path):
        proc = Proc(tmp_path)
        proc.consumer()
        proc.thread(4000, 4001, "6")
        signals = Signals()
        sleeps = Sleeps({3: [lambda: signals.send(signal.SIGTERM)]})
        code, _, record = run(tmp_path, proc, sleeps=sleeps, signals=signals)
        assert code == 0 and record["ended_by"] == "stopped" and record["looks"] == 3
        assert [t["affinity"] for t in record["tasks"]] == ["6", "7"]

    def test_a_process_whose_id_another_program_has_taken_has_ended(self, tmp_path):
        proc = Proc(tmp_path)
        proc.consumer()
        sleeps = Sleeps({2: [lambda: proc.command(4000, ["python3", "-c", "pass"])]})
        code, _, record = run(tmp_path, proc, sleeps=sleeps)
        assert code == 0 and record["looks"] == 2 and record["ended_by"] == "the process ended"

    def test_threads_that_can_no_longer_be_listed_end_the_watch(self, tmp_path):
        proc = Proc(tmp_path)
        proc.consumer()
        sleeps = Sleeps({2: [lambda: shutil.rmtree(str(proc.root / "4000" / "task"))]})
        code, _, record = run(tmp_path, proc, sleeps=sleeps)
        assert code == 0 and record["looks"] == 2 and sleeps.count == 2

    def test_a_consumer_that_ended_as_it_was_found_was_never_looked_at(self, tmp_path):
        """A process that has ended but not yet been reaped is taken as ended."""
        proc = Proc(tmp_path)
        proc.consumer(state="Z")
        code, _, record = run(tmp_path, proc)
        assert code == 1 and record["pid"] == 4000 and record["looks"] == 0
        assert record["why"] == ("the consumer's threads were never looked at: it ended as soon "
                                 "as its process was found")

    def test_a_watch_stopped_as_soon_as_it_found_the_process_says_so(self):
        record = {"tasks": [], "moves": [], "siblings": [7], "siblings_list": "7", "cpu": 6,
                  "looks": 0, "main_affinity_seen": [], "main_alone": False,
                  "ended_by": "stopped"}
        assert ta.judged(record) == ("the consumer's threads were never looked at: the runner "
                                     "stopped this as soon as its process was found")


class TestWhatItIsGiven:

    @pytest.mark.parametrize("siblings,why", [
        ("6", "the siblings 6 hold the consumer's own CPU 6, so no thread moved onto them would be "
              "apart from its main one"),
        ("6-7", "the siblings 6-7 hold the consumer's own CPU 6"),
        ("-", "'-' is not a list of CPUs")])
    def test_siblings_that_hold_the_consumers_cpu_or_none_are_refused(self, tmp_path, siblings,
                                                                      why):
        proc = Proc(tmp_path)
        proc.consumer()
        code, printed, record = run(tmp_path, proc, siblings=siblings)
        assert code == 1 and record["why"].startswith(why) and record["pid"] is None
        assert record["siblings"] is None and record["siblings_list"] == siblings
        assert printed.startswith("FAILED the consumer's threads apart: ")

    def test_a_list_names_exactly_its_cpus_or_it_does_not(self):
        assert ta.exactly("7", [7]) and ta.exactly("5,7", [7, 5]) and ta.exactly("6-7", [6, 7])
        assert not ta.exactly("6-7", [7]) and not ta.exactly(None, [7])
        assert not ta.exactly("7-x", [7]), "a list the kernel would not write names nothing"

    def test_a_command_line_without_its_cpu_is_refused(self, tmp_path):
        with pytest.raises(SystemExit) as stopped:
            ta.main(["--out", str(tmp_path / "x.json"), "--run-id", RUN, "--siblings", "7"],
                    out=io.StringIO(), signals=Signals())
        assert stopped.value.code == 2 and not (tmp_path / "x.json").exists()
