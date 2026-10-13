#!/usr/bin/env python3
"""
phc_offset.py -- how far a network card's own clock (a PTP hardware clock, /dev/ptpN) lies from
the system's CLOCK_REALTIME, sampled through a run, so that the card's receive timestamps can be put
on the system's clock beside the kernel's.

The card stamps each packet it receives on its own clock (tcpdump -j adapter_unsynced). That clock
is not the system's and drifts against it, so each hardware timestamp is converted by the offset
measured nearest it. The kernel's PTP_SYS_OFFSET call reads the system clock, the card's clock and
the system clock again, n times; the reading with the narrowest system window brackets the card's
reading most tightly, and its offset is the card's reading less the middle of that window.

    sudo python3 phc_offset.py --device /dev/ptp1 --interval 0.5 --out phc_offset.csv

Runs until it is stopped. One row per sample: the system time at the middle of the window, the
card's time less it, and the window's width, all in nanoseconds.
"""
import argparse
import os
import signal
import struct
import time

#: struct ptp_sys_offset { unsigned int n_samples; unsigned int rsv[3];
#:                         struct ptp_clock_time ts[2 * PTP_MAX_SAMPLES + 1]; }
#: struct ptp_clock_time { __s64 sec; __u32 nsec; __u32 reserved; }
PTP_MAX_SAMPLES = 25
CLOCK_TIME = struct.Struct("=qII")
SIZE = 16 + CLOCK_TIME.size * (2 * PTP_MAX_SAMPLES + 1)
#: _IOW('=', 5, struct ptp_sys_offset)
PTP_SYS_OFFSET = (1 << 30) | (SIZE << 16) | (ord("=") << 8) | 5


def _ioctl(fd, request, buf):
    """The kernel's call. fcntl is imported here, where it is used, so the module imports on any
    system, Windows among them, where the tests run with a stand-in for it."""
    import fcntl
    return fcntl.ioctl(fd, request, buf, True)


def sample(fd, n=10):
    """(system ns at the middle of the narrowest window, card ns less it, the window in ns)."""
    buf = bytearray(SIZE)
    struct.pack_into("=I", buf, 0, n)
    _ioctl(fd, PTP_SYS_OFFSET, buf)
    ts = [CLOCK_TIME.unpack_from(buf, 16 + i * CLOCK_TIME.size) for i in range(2 * n + 1)]
    ns = [sec * 1000000000 + nsec for sec, nsec, _ in ts]
    best = min(range(n), key=lambda i: ns[2 * i + 2] - ns[2 * i])
    before, card, after = ns[2 * best], ns[2 * best + 1], ns[2 * best + 2]
    middle = (before + after) // 2
    return middle, card - middle, after - before


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sample a PTP hardware clock against CLOCK_REALTIME")
    ap.add_argument("--device", required=True)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--count", type=int, default=0, help="stop after this many; 0 runs on")
    args = ap.parse_args(argv)
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    fd = os.open(args.device, os.O_RDWR)
    taken = 0
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("system_ns,card_minus_system_ns,window_ns\n")
        while not stop and (not args.count or taken < args.count):
            fh.write("%d,%d,%d\n" % sample(fd))
            fh.flush()
            taken += 1
            time.sleep(args.interval)
    os.close(fd)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
