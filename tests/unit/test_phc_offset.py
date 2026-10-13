"""Tests for scripts/phc_offset.py: a network card's clock sampled against the system's through the
kernel's PTP_SYS_OFFSET call, which is stood in for here by one that fills the reply as the kernel
does: system time, card time, system time, and so on, n times over."""
import os
import struct
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import phc_offset as po  # noqa: E402


def kernel_reply(readings):
    """An ioctl stand-in that writes `readings` (ns) into the reply as ptp_clock_time records."""
    def ioctl(fd, request, buf, mutate):
        assert request == po.PTP_SYS_OFFSET and mutate
        n = struct.unpack_from("=I", buf, 0)[0]
        assert len(readings) == 2 * n + 1
        for i, ns in enumerate(readings):
            po.CLOCK_TIME.pack_into(buf, 16 + i * po.CLOCK_TIME.size, ns // 10**9, ns % 10**9, 0)
        return 0
    return ioctl


def test_the_request_is_the_kernels():
    """_IOW('=', 5, struct ptp_sys_offset): write, its size, '=', 5."""
    assert po.SIZE == 16 + 16 * 51 and po.PTP_SYS_OFFSET == 0x43403D05


def test_the_narrowest_window_brackets_the_card_reading(monkeypatch):
    base = 1791892323 * 10**9
    # Three readings of the card between four of the system, the kernel's layout, neighbours
    # sharing a system reading; the second's window is the narrowest, 1,000 ns wide.
    readings = [base, base - 4800000 + 1500, base + 3000, base - 4800000 + 3500, base + 4000,
                base - 4800000 + 6000, base + 9000]
    monkeypatch.setitem(sys.modules, "fcntl", types.SimpleNamespace(ioctl=kernel_reply(readings)))
    middle, offset, window = po.sample(3, n=3)
    assert (middle, offset, window) == (base + 3500, -4800000, 1000)


def test_it_writes_a_row_a_sample_until_its_count(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(po.os, "open", lambda path, flags: calls.append(path) or 7)
    monkeypatch.setattr(po.os, "close", lambda fd: calls.append(("closed", fd)))
    monkeypatch.setattr(po, "sample", lambda fd: (100 + len(calls), -4800000, 1450))
    monkeypatch.setattr(po.time, "sleep", lambda s: None)
    out = tmp_path / "phc.csv"
    assert po.main(["--device", "/dev/ptp1", "--out", str(out), "--count", "3"]) == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "system_ns,card_minus_system_ns,window_ns" and len(lines) == 4
    assert calls[0] == "/dev/ptp1" and calls[-1] == ("closed", 7)


def test_a_signal_ends_it_after_the_sample_in_hand(monkeypatch, tmp_path):
    handlers = {}
    monkeypatch.setattr(po.signal, "signal", lambda sig, handler: handlers.__setitem__(sig, handler))
    monkeypatch.setattr(po.os, "open", lambda path, flags: 7)
    monkeypatch.setattr(po.os, "close", lambda fd: None)
    taken = []

    def sample(fd):
        taken.append(1)
        if len(taken) == 2:
            handlers[po.signal.SIGTERM]()
        return (len(taken), 0, 1)
    monkeypatch.setattr(po, "sample", sample)
    monkeypatch.setattr(po.time, "sleep", lambda s: None)
    out = tmp_path / "phc.csv"
    assert po.main(["--device", "/dev/ptp1", "--out", str(out)]) == 0
    assert len(out.read_text(encoding="utf-8").splitlines()) == 3, "two samples, then it stopped"
    handlers[po.signal.SIGINT]()
