"""Tests for scripts/consumer_threads.py: the consumer's thread list waited for before the producer
starts, and its fetch threads raised to real-time priority where the setup asks (fetch_rt).

The consumer, its threads and chrt are stood in for: a fake /proc that holds what the kernel would,
a list written as the three consumers write it, and a chrt that writes the policy it was asked for
into the fake /proc, so that what is read back is what a real raise would leave.
"""
import io
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import consumer_threads as ct  # noqa: E402

#: A thread's stat line as the kernel writes it, with its policy (field 41) and real-time priority
#: (field 40) to be filled in: the two fields the read back looks at.
STAT = ("{tid} ({comm}) S 1 1 1 0 -1 4194560 100 0 0 0 5 3 0 0 20 0 3 0 100 1000 100 "
        "18446744073709551615 1 1 0 0 0 0 0 0 0 0 0 0 17 0 {prio} {policy} 0 0 0 0 0 0 0 0 0 0 0")

#: The list as kafka_consumer_confluent.py writes it: the poll thread, librdkafka's broker thread
#: for the partition's leader, and two threads with no role.
CONFLUENT = ("tid,name,role,runtime_name\n"
             "4100,python3,poll,MainThread\n"
             "4101,rdk:main,,\n"
             "4102,rdk:broker1,fetch,\n"
             "4103,rdk:broker-1,,\n")
#: As harness/java's LawConsumer writes it: law-poll sends the fetches, as poll+fetch.
JAVA = ("tid,name,role,runtime_name\n"
        "5200,java,,\n"
        "5201,law-poll,poll+fetch,law-poll\n"
        "5202,\"kafka-coordin\",,\"kafka-coordinator-heartbeat-thread | sb-consumer-r1\"\n")
#: As harness/go's franz-consumer writes it: no thread has a role.
FRANZ = ("tid,name,role,runtime_name\n"
         "6300,franz-consumer,,\n"
         "6301,franz-consumer,,\n")


def proc_tree(tmp_path, threads, consumer_pid=4000, consumer_state="S"):
    """A fake /proc: the consumer's process, and each thread with its own stat, at SCHED_OTHER."""
    proc = tmp_path / "proc"
    (proc / str(consumer_pid)).mkdir(parents=True)
    (proc / str(consumer_pid) / "stat").write_text(
        STAT.format(tid=consumer_pid, comm="sudo", prio=0, policy=0).replace(
            ") S ", ") %s " % consumer_state), encoding="utf-8")
    for tid, comm in threads:
        (proc / str(tid)).mkdir()
        (proc / str(tid) / "stat").write_text(STAT.format(tid=tid, comm=comm, prio=0, policy=0),
                                              encoding="utf-8")
    return proc


def fake_chrt(proc, refuse=(), lie=(), calls=None):
    """chrt stood in for: it writes SCHED_FIFO (1) at the asked priority into the thread's stat,
    exits 1 for a tid in `refuse`, and for a tid in `lie` exits 0 having changed nothing."""
    calls = [] if calls is None else calls

    def run(command, **_kw):
        calls.append(command)
        tid, priority = command[-1], int(command[-2])
        if tid in refuse:
            return subprocess.CompletedProcess(command, 1, b"", b"chrt: failed: Operation not "
                                                                  b"permitted\n")
        if tid not in lie:
            path = proc / tid / "stat"
            comm = path.read_text(encoding="utf-8").split("(", 1)[1].split(")", 1)[0]
            path.write_text(STAT.format(tid=tid, comm=comm, prio=priority, policy=1),
                            encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, b"", b"")
    run.calls = calls
    return run


class Clock:
    """A monotonic clock that moves on by a tenth of a second at each sleep."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1
        self.now += seconds


def main(tmp_path, *extra, run=None, clock=None, proc=None, threads_text=None, pid=4000):
    """consumer_threads.main on a list at runs/r1/consumer_tids.csv, written first unless
    threads_text is None. (Exit code, what it printed, the record.)"""
    listed = tmp_path / "consumer_tids.csv"
    if threads_text is not None:
        listed.write_bytes(threads_text.encode("utf-8"))
    clock = clock or Clock()
    out, printed = tmp_path / "consumer_threads.json", io.StringIO()
    code = ct.main(["--threads", str(listed), "--pid", str(pid), "--out", str(out),
                    "--proc", str(proc)] + list(extra), out=printed, run=run or fake_chrt(proc),
                   clock=clock, sleep=clock.sleep, now_ns=lambda: 1_000_000)
    return code, printed.getvalue(), json.loads(out.read_text(encoding="utf-8"))


class TestTheListIsWaitedFor:

    def test_a_list_already_there_is_read_and_nothing_is_raised_unasked(self, tmp_path):
        proc = proc_tree(tmp_path, [(4102, "rdk:broker1")])
        run = fake_chrt(proc)
        code, printed, record = main(tmp_path, proc=proc, threads_text=CONFLUENT, run=run)
        assert code == 0 and printed.startswith("OK consumer threads: 4 listed, 0 raised")
        assert record["ok"] is True and record["why"] == "" and record["raised"] == []
        assert [r["name"] for r in record["rows"]] == ["python3", "rdk:main", "rdk:broker1",
                                                        "rdk:broker-1"]
        assert record["priority"] is None and record["t_listed_ns"] == 1_000_000
        assert run.calls == []

    def test_a_list_that_comes_later_is_waited_for_while_the_consumer_runs(self, tmp_path):
        proc = proc_tree(tmp_path, [])
        listed = tmp_path / "consumer_tids.csv"
        clock = Clock()

        def sleep(seconds):
            clock.sleep(seconds)
            if clock.sleeps == 3:
                listed.write_text(FRANZ, encoding="utf-8")
        out = tmp_path / "out.json"
        code = ct.main(["--threads", str(listed), "--pid", "4000", "--out", str(out),
                        "--proc", str(proc)], out=io.StringIO(), clock=clock, sleep=sleep)
        assert code == 0 and clock.sleeps == 3
        assert json.loads(out.read_text(encoding="utf-8"))["rows"][0]["name"] == "franz-consumer"

    def test_a_consumer_that_ends_before_its_list_fails_the_trial(self, tmp_path):
        proc = proc_tree(tmp_path, [])
        code, printed, record = main(tmp_path, proc=proc, pid=4999)
        assert code == 1 and printed.startswith("FATAL: the consumer's process 4999 ended before")
        assert record["ok"] is False and record["rows"] is None

    def test_a_consumer_left_a_zombie_has_ended(self, tmp_path):
        proc = proc_tree(tmp_path, [], consumer_state="Z")
        code, printed, _ = main(tmp_path, proc=proc)
        assert code == 1 and "ended before it wrote its thread list" in printed

    def test_a_consumer_whose_stat_cannot_be_parsed_is_taken_as_alive(self, tmp_path):
        proc = proc_tree(tmp_path, [])
        (proc / "4000" / "stat").write_text("garbled", encoding="utf-8")
        assert ct.alive(4000, str(proc)) is True

    def test_a_list_that_never_comes_fails_the_trial_once_the_wait_is_over(self, tmp_path):
        proc = proc_tree(tmp_path, [])
        clock = Clock()
        code, printed, record = main(tmp_path, "--timeout-s", "2", proc=proc, clock=clock)
        assert code == 1 and "wrote no thread list" in printed and "within 2 s" in printed
        assert clock.sleeps == 20, "looked at every tenth of a second until the wait was over"
        assert record["why"].endswith("it never had its partitions assigned")

    @pytest.mark.parametrize("text", ["tid,name,role\n1,x,\n", "", "a\x00b"])
    def test_a_list_that_is_not_the_consumers_fails_the_trial(self, tmp_path, text):
        proc = proc_tree(tmp_path, [])
        code, printed, record = main(tmp_path, proc=proc, threads_text=text)
        assert code == 1 and printed.startswith("FATAL: ") and record["ok"] is False


class TestTheFetchThreadsAreRaised:

    def test_confluents_broker_thread_alone_is_raised_and_read_back(self, tmp_path):
        proc = proc_tree(tmp_path, [(4100, "python3"), (4102, "rdk:broker1")])
        run = fake_chrt(proc)
        code, printed, record = main(tmp_path, "--priority", "80", proc=proc,
                                     threads_text=CONFLUENT, run=run)
        assert code == 0 and printed.startswith("OK consumer threads: 4 listed, 1 raised to "
                                                "SCHED_FIFO 80")
        assert run.calls == [["sudo", "chrt", "-f", "-p", "80", "4102"]]
        raised, = record["raised"]
        assert (raised["tid"], raised["name"], raised["role"]) == ("4102", "rdk:broker1", "fetch")
        assert (raised["policy_after"], raised["rt_priority_after"], raised["ok"]) == (
            "SCHED_FIFO", 80, True)
        assert raised["command"] == "sudo chrt -f -p 80 4102" and raised["t_ns"] == 1_000_000

    def test_javas_poll_thread_is_the_fetch_thread_and_another_chrt_can_be_named(self, tmp_path):
        proc = proc_tree(tmp_path, [(5201, "law-poll")])
        run = fake_chrt(proc)
        code, _, record = main(tmp_path, "--priority", "50", "--chrt", "chrt", proc=proc,
                               threads_text=JAVA, run=run)
        assert code == 0 and run.calls == [["chrt", "-f", "-p", "50", "5201"]]
        assert record["raised"][0]["rt_priority_after"] == 50

    def test_a_list_with_no_fetch_thread_fails_the_trial_and_raises_nothing(self, tmp_path):
        """franz-go sends its fetches from no thread of its own; a run that asked for its fetch
        thread at real-time priority must not run with nothing raised."""
        proc = proc_tree(tmp_path, [(6300, "franz-consumer")])
        run = fake_chrt(proc)
        code, printed, record = main(tmp_path, "--priority", "80", proc=proc, threads_text=FRANZ,
                                     run=run)
        assert code == 1 and "names no thread whose role holds fetch" in printed
        assert "franz-go" in printed and run.calls == [] and record["raised"] == []

    def test_a_raise_the_kernel_refused_fails_the_trial(self, tmp_path):
        proc = proc_tree(tmp_path, [(4102, "rdk:broker1")])
        code, printed, record = main(tmp_path, "--priority", "80", proc=proc,
                                     threads_text=CONFLUENT, run=fake_chrt(proc, refuse=("4102",)))
        assert code == 1 and "1 of the 1 fetch threads did not take SCHED_FIFO 80" in printed
        assert "exited 1" in printed and "Operation not permitted" in printed
        assert record["raised"][0]["ok"] is False

    def test_a_raise_that_exited_0_and_changed_nothing_fails_the_trial(self, tmp_path):
        proc = proc_tree(tmp_path, [(4102, "rdk:broker1")])
        code, printed, record = main(tmp_path, "--priority", "80", proc=proc,
                                     threads_text=CONFLUENT, run=fake_chrt(proc, lie=("4102",)))
        assert code == 1 and "now SCHED_OTHER 0" in printed and "nothing said" in printed
        assert record["raised"][0]["exit"] == 0

    def test_a_fetch_row_without_a_kernel_id_cannot_be_raised(self, tmp_path):
        """LawConsumer writes the JVM's own list, without ids, where the kernel lists none."""
        proc = proc_tree(tmp_path, [])
        text = "tid,name,role,runtime_name\n,,poll+fetch,law-poll\n"
        run = fake_chrt(proc)
        code, printed, record = main(tmp_path, "--priority", "80", proc=proc, threads_text=text,
                                     run=run)
        assert code == 1 and run.calls == []
        assert record["raised"][0]["said"].startswith("the row has no kernel id")

    @pytest.mark.parametrize("error", [OSError("no chrt"), subprocess.TimeoutExpired("chrt", 10)])
    def test_a_chrt_that_cannot_run_fails_the_trial(self, tmp_path, error):
        proc = proc_tree(tmp_path, [(4102, "rdk:broker1")])

        def run(command, **_kw):
            raise error
        code, _, record = main(tmp_path, "--priority", "80", proc=proc, threads_text=CONFLUENT,
                               run=run)
        assert code == 1 and record["raised"][0]["said"].startswith("could not run: ")

    def test_a_thread_gone_before_its_read_back_is_not_held(self, tmp_path):
        proc = proc_tree(tmp_path, [(4102, "rdk:broker1")])

        def run(command, **_kw):
            os.remove(proc / "4102" / "stat")
            return subprocess.CompletedProcess(command, 0, b"", b"")
        code, _, record = main(tmp_path, "--priority", "80", proc=proc, threads_text=CONFLUENT,
                               run=run)
        assert code == 1 and record["raised"][0]["policy_after"] is None

    @pytest.mark.parametrize("priority", ["0", "100"])
    def test_a_priority_chrt_cannot_give_is_refused(self, tmp_path, priority):
        with pytest.raises(SystemExit):
            main(tmp_path, "--priority", priority, proc=proc_tree(tmp_path, []),
                 threads_text=CONFLUENT)


def test_the_rows_with_a_fetch_role_are_the_fetch_threads():
    rows = [{"role": "poll"}, {"role": "fetch"}, {"role": "poll+fetch"}, {"role": ""},
            {"role": None}, {"role": "prefetch"}]
    assert ct.fetching(rows) == [{"role": "fetch"}, {"role": "poll+fetch"}]
