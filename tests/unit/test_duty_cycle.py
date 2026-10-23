"""Tests for scripts/duty_cycle.py: a command's whole process group held at a duty, by stopping and
continuing it in every period (plan version 47's socket and UDP loads).

The command and the signals are stood in for: a child that ends after a given number of looks,
and a killpg that writes down what it was sent, so that what the group was sent, in what order and
for how long it ran, is read from the calls alone.
"""
import os
import signal
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import duty_cycle as dc  # noqa: E402


class Child:
    """A child that runs for `looks` looks at poll() and then ends with `code`."""

    def __init__(self, looks, code=0):
        self.pid = 4321
        self.looks = looks
        self.code = code
        self.waited = False

    def poll(self):
        self.looks -= 1
        return self.code if self.looks < 0 else None

    def wait(self):
        self.waited = True
        return self.code


def world(child, gone=False):
    """(popen, killpg, sleep, what happened): each call written down in order."""
    happened = []

    def popen(command, start_new_session=False):
        happened.append(("start", tuple(command), start_new_session))
        return child

    def killpg(pid, sig):
        happened.append(("signal", pid, sig))
        if gone:
            raise ProcessLookupError(pid)

    def sleep(seconds):
        happened.append(("sleep", round(seconds, 6)))
    return popen, killpg, sleep, happened


def test_the_group_runs_for_its_share_of_each_period_and_is_continued_at_its_end():
    child = Child(looks=4)
    popen, killpg, sleep, happened = world(child)
    code = dc.main(["--duty", "70", "--", "stress-ng", "--sock", "6"], popen=popen,
                   killpg=killpg, sleep=sleep)
    assert code == 0 and child.waited
    assert happened[0] == ("start", ("stress-ng", "--sock", "6"), True), "a group of its own"
    period = [("sleep", 0.07), ("signal", 4321, dc.SIGSTOP), ("sleep", 0.03),
              ("signal", 4321, dc.SIGCONT)]
    assert happened[1:] == period * 2, "two whole periods, the group continued at each end"


def test_a_period_of_its_own_and_a_command_that_ends_in_its_running_share():
    child = Child(looks=1, code=3)
    popen, killpg, sleep, happened = world(child)
    code = dc.main(["--duty", "25", "--period-ms", "200", "--", "stress-ng", "--udp", "1"],
                   popen=popen, killpg=killpg, sleep=sleep)
    assert code == 3, "its exit status is the command's"
    assert happened[1:] == [("sleep", 0.05)], "no stop sent to a command that has ended"


def test_at_a_duty_of_100_the_group_is_never_stopped():
    child = Child(looks=3)
    popen, killpg, sleep, happened = world(child)
    dc.main(["--duty", "100", "--", "stress-ng"], popen=popen, killpg=killpg, sleep=sleep)
    assert [h for h in happened if h[0] == "signal"] == []
    assert happened[1:] == [("sleep", 0.1)] * 3


def test_a_group_already_gone_is_not_an_error():
    child = Child(looks=2)
    popen, killpg, sleep, happened = world(child, gone=True)
    assert dc.main(["--duty", "50", "--", "x"], popen=popen, killpg=killpg, sleep=sleep) == 0


@pytest.mark.parametrize("sig", dc.PASSED_ON)
def test_a_term_or_an_int_is_passed_on_to_the_group_continued_first(sig):
    child = Child(looks=10)
    popen, killpg, _, happened = world(child)

    def sleep(seconds):
        happened.append(("sleep", round(seconds, 6)))
        if len(happened) == 2:
            signal.getsignal(sig)(sig, None)
    before = {s: signal.getsignal(s) for s in dc.PASSED_ON}
    dc.main(["--duty", "70", "--", "x"], popen=popen, killpg=killpg, sleep=sleep)
    assert happened[1:] == [("sleep", 0.07), ("signal", 4321, dc.SIGSTOP), ("sleep", 0.03),
                            ("signal", 4321, dc.SIGCONT), ("signal", 4321, dc.SIGCONT),
                            ("signal", 4321, sig)]
    assert {s: signal.getsignal(s) for s in dc.PASSED_ON} == before, "the handlers put back"


@pytest.mark.parametrize("argv", [
    ["--duty", "70"], ["--duty", "70", "--"], ["--duty", "0", "--", "x"],
    ["--duty", "101", "--", "x"], ["--duty", "50", "--period-ms", "0", "--", "x"],
    ["--", "x"]])
def test_what_it_cannot_run_as_asked_is_refused(argv):
    with pytest.raises(SystemExit):
        dc.main(argv, popen=None, killpg=None, sleep=None)


def test_the_signals_are_linuxs_own():
    assert (dc.SIGSTOP, dc.SIGCONT) == (getattr(signal, "SIGSTOP", 19),
                                        getattr(signal, "SIGCONT", 18))
    assert dc.PERIOD_MS == 100.0


def test_its_own_command_line_is_read_when_none_is_given(monkeypatch):
    child = Child(looks=0)
    popen, killpg, sleep, happened = world(child)
    monkeypatch.setattr(sys, "argv", ["duty_cycle.py", "--duty", "50", "--", "y"])
    assert dc.main(popen=popen, killpg=killpg, sleep=sleep) == 0
    assert happened[0][1] == ("y",)
