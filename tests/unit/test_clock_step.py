"""Moving a machine's clock for the Go tools' T2, measured against the hypervisor's clock.

The real thing steps CLOCK_REALTIME and reads /dev/ptp_hyperv. Here a pair of clocks that only
move when told stand in: a system clock that can be stepped, and a PTP clock that cannot.
"""
import io
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import clock_step as cs  # noqa: E402

PTP = -29   # a dynamic clock id, as phc_clock_id gives for the descriptor 3


class Clocks:
    """A system clock `ahead_ns` ahead of the PTP clock, every read costing `read_ns`.

    `slow` names the reads, counted from 1, that take ten times as long -- preempted -- and read
    the PTP late by `lopsided_ns`, which is what a preempted read of the Hyper-V clock does.
    """

    def __init__(self, ahead_ns=0, read_ns=1_000, slow=(), lopsided_ns=0):
        self.ptp, self.ahead, self.read, self.slow, self.lopsided = 10**18, ahead_ns, read_ns, \
            set(slow), lopsided_ns
        self.reads = 0
        self.stepped = []

    def gettime(self, clock_id):
        self.reads += 1
        cost = self.read * (10 if self.reads in self.slow else 1)
        self.ptp += cost
        if clock_id == cs.REALTIME:
            return self.ptp + self.ahead
        assert clock_id == PTP, "only the two clocks are read"
        return self.ptp - (self.lopsided if self.reads in self.slow else 0)

    def settime(self, clock_id, value):
        assert clock_id == cs.REALTIME, "only the system clock is ever set"
        self.stepped.append(value)
        self.ahead = value - self.ptp


class TestTheMeasure:

    def test_the_dynamic_clock_id_is_the_kernels(self):
        assert cs.phc_clock_id(3) == PTP

    def test_it_reads_how_far_the_system_clock_is_from_the_ptp(self):
        assert cs.offset_ns(PTP, gettime=Clocks(ahead_ns=7_000).gettime) == pytest.approx(7_000)

    def test_a_preempted_read_does_not_move_it(self):
        """On the first x86 pair the plain median of every pair wandered 60 microseconds where
        chrony put the clocks 0.15 apart; keeping the fastest pairs is what steadied it."""
        slow = set(range(2, 180, 3)[:40])          # most of the PTP reads, preempted and late
        clocks = Clocks(ahead_ns=0, slow=slow, lopsided_ns=40_000)
        assert cs.offset_ns(PTP, gettime=clocks.gettime) == pytest.approx(0, abs=1_000)


class TestTheStep:

    def test_it_moves_the_system_clock_by_what_was_asked_and_says_what_moved(self):
        clocks = Clocks()
        found = cs.shift(-1.812, PTP, gettime=clocks.gettime, settime=clocks.settime)
        assert len(clocks.stepped) == 1, "one write of the system clock"
        assert found["asked_ms"] == -1.812
        assert found["moved_ms"] == pytest.approx(-1.812, abs=0.002)
        assert found["before_ms"] == pytest.approx(0, abs=0.002)

    def test_and_back_again(self):
        clocks = Clocks()
        cs.shift(-3.8, PTP, gettime=clocks.gettime, settime=clocks.settime)
        back = cs.shift(3.8, PTP, gettime=clocks.gettime, settime=clocks.settime)
        assert back["after_ms"] == pytest.approx(0, abs=0.002)


class TestTheCommand:

    def run(self, argv, clocks):
        opened, closed = [], []
        said = io.StringIO()
        code = cs.main(argv, said, opener=lambda path, flags: opened.append(path) or 3,
                       closer=closed.append, gettime=clocks.gettime, settime=clocks.settime)
        return code, said.getvalue(), opened, closed

    def test_measure_says_the_distance_in_ms(self):
        code, said, opened, closed = self.run(["measure"], Clocks(ahead_ns=25_000))
        assert code == 0 and float(said) == pytest.approx(0.025, abs=0.002)
        assert opened == [cs.PHC] and closed == [3], "the device is closed again"

    def test_shift_writes_what_moved(self, tmp_path):
        out = tmp_path / "moved.json"
        clocks = Clocks()
        code, said, _, closed = self.run(["shift", "--ms", "-2.5", "--out", str(out)], clocks)
        written = json.loads(out.read_text(encoding="utf-8"))
        assert code == 0 and closed == [3]
        assert written["moved_ms"] == pytest.approx(-2.5, abs=0.002)
        assert json.loads(said)["asked_ms"] == -2.5

    def test_shift_without_a_file_still_says_what_moved(self):
        code, said, _, _ = self.run(["shift", "--ms", "1.0"], Clocks())
        assert code == 0 and json.loads(said)["moved_ms"] == pytest.approx(1.0, abs=0.002)
