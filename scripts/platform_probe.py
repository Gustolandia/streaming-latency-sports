#!/usr/bin/env python3
"""
platform_probe.py
Measure the testbed properties that bound every latency number this project reports.

Two of our headline figures turned out to be properties of the host rather than of either
broker, and a reader cannot judge them without knowing the platform:

  * Producer scheduling lag (~8 ms median) is bounded below by the resolution of the
    sleep primitive the replay loop uses. On Windows the system timer tick is classically
    15.6 ms, which would put a uniform wait's median near 7.8 ms -- indistinguishable from
    what we measure. This probe reports the granularity actually achieved.
  * Broker transport bottoms out near 1 ms even at N=1. When brokers run under Docker
    Desktop the container network is inside a WSL2 virtual machine, so "loopback" in fact
    crosses a virtual NIC. This probe reports the measured round trip to each broker port
    so the floor is disclosed rather than assumed.

Everything here is descriptive: it characterises the testbed, it does not change any result.

CLI:
    python scripts/platform_probe.py --out docs/results/platform/platform.json
"""
import argparse
import json
import platform
import socket
import statistics
import sys
import time
from pathlib import Path


def timer_resolution(samples=2000, clock=time.perf_counter):
    """Smallest non-zero gap the clock can report, in seconds.

    Polls the clock in a tight loop and keeps the smallest forward step observed. This is the
    floor on any duration we can measure at all.
    """
    smallest = None
    prev = clock()
    for _ in range(samples):
        cur = clock()
        delta = cur - prev
        prev = cur
        if delta > 0 and (smallest is None or delta < smallest):
            smallest = delta
    return smallest


def sleep_granularity(target_s=0.001, trials=200, sleep=time.sleep, clock=time.perf_counter):
    """How long a short sleep actually takes.

    The replay loop waits until each event's scheduled emission time, so the achievable
    precision of that wait sets a floor on producer scheduling lag. Requesting 1 ms and
    measuring what we get exposes a coarse system tick directly.
    """
    observed = []
    for _ in range(trials):
        t0 = clock()
        sleep(target_s)
        observed.append(clock() - t0)
    observed.sort()
    return {
        "requested_ms": target_s * 1e3,
        "trials": trials,
        "min_ms": observed[0] * 1e3,
        "median_ms": statistics.median(observed) * 1e3,
        "max_ms": observed[-1] * 1e3,
        "overshoot_median_ms": (statistics.median(observed) - target_s) * 1e3,
    }


def parse_ports(specs):
    """Turn ["kafka=localhost:19092", ...] into {"kafka": ("localhost", 19092)}.

    Ports are explicit rather than defaulted because this repo's compose file remaps them
    (Redis 16379->6379, Kafka 19092); probing a port nothing listens on would silently
    characterise a closed socket instead of the broker.
    """
    out = {}
    for spec in specs:
        if "=" not in spec or ":" not in spec:
            raise ValueError(f"bad --port spec {spec!r}; expected name=host:port")
        name, addr = spec.split("=", 1)
        host, port = addr.rsplit(":", 1)
        out[name] = (host, int(port))
    return out


def tcp_rtt(host, port, trials=50, timeout=2.0, connect=None):
    """Median TCP connect round trip to a broker port, in ms.

    A connect is one round trip on an established route, so this measures the path the
    producer's traffic actually takes -- including any virtual-machine hop -- without
    depending on a broker client library.
    """
    connect = connect or _default_connect
    rtts, errors = [], 0
    for _ in range(trials):
        t0 = time.perf_counter()
        try:
            connect(host, port, timeout)
        except OSError:
            errors += 1
            continue
        rtts.append((time.perf_counter() - t0) * 1e3)
    if not rtts:
        return {"host": host, "port": port, "trials": trials, "errors": errors,
                "reachable": False}
    rtts.sort()
    return {
        "host": host, "port": port, "trials": trials, "errors": errors, "reachable": True,
        "min_ms": rtts[0], "median_ms": statistics.median(rtts), "max_ms": rtts[-1],
    }


def _default_connect(host, port, timeout):  # pragma: no cover - exercised via injection
    s = socket.create_connection((host, port), timeout=timeout)
    s.close()


def redis_ping_rtt(host, port, trials=200, timeout=2.0, opener=None):
    """Round trip of a PING on an *established* connection, in ms.

    This is the quantity the round-trip-bound consumption argument turns on: a consumer that
    awaits a reply per message is capped near 1/RTT, and RTT here means the cost of one
    request/response on an open socket -- not the cost of establishing one. Connection setup
    is far more expensive and would badly overstate the floor.
    """
    opener = opener or _default_socket
    try:
        sock = opener(host, port, timeout)
    except OSError:
        return {"host": host, "port": port, "reachable": False, "trials": trials}
    rtts = []
    try:
        for _ in range(trials):
            t0 = time.perf_counter()
            sock.sendall(b"PING\r\n")
            if not sock.recv(64):
                break
            rtts.append((time.perf_counter() - t0) * 1e3)
    except OSError:
        pass
    finally:
        sock.close()
    if not rtts:
        return {"host": host, "port": port, "reachable": False, "trials": trials}
    rtts.sort()
    return {
        "host": host, "port": port, "reachable": True, "trials": len(rtts),
        "min_ms": rtts[0], "median_ms": statistics.median(rtts), "max_ms": rtts[-1],
        "implied_ceiling_msgs_per_s": 1000.0 / statistics.median(rtts),
    }


def _default_socket(host, port, timeout):  # pragma: no cover - exercised via injection
    return socket.create_connection((host, port), timeout=timeout)


def platform_info():
    """Static description of the host, for the manuscript's disclosure paragraph."""
    return {
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


# Where Linux publishes the identity and coherence properties of the clock a timestamp
# actually comes from. These are read-only sysfs and procfs paths; the probe never writes.
CLOCKSOURCE_CURRENT = "/sys/devices/system/clocksource/clocksource0/current_clocksource"
CLOCKSOURCE_AVAILABLE = "/sys/devices/system/clocksource/clocksource0/available_clocksource"
CPUINFO = "/proc/cpuinfo"

# The CPU flags that decide whether a timestamp counter can be trusted across cores, and
# whether the hypervisor asserts cross-vCPU monotonicity to its guest.
TSC_FLAGS = ("constant_tsc", "nonstop_tsc", "tsc_reliable", "tsc_known_freq", "hypervisor")


def clock_provenance(root="", reader=None):
    """Which clock the host's timestamps come from, and what it guarantees across CPUs.

    This exists because a referee asked a question the campaign could not answer. The
    manuscript argues that inverted intervals come from a late stamp rather than from an
    incoherent clock, and a reviewer reasonably asked which clocksource the machines used --
    a virtualised guest need not be given a counter that is coherent across its vCPUs. The
    campaign never recorded it, the instances have since been reclaimed, and the answer is
    therefore unrecoverable for the runs already reported.

    It is recoverable for every run after this one. The cost is four file reads, and the
    alternative is discovering the same gap again at the next review.

    Returns a dict with the current and available clocksources and the TSC-related CPU flags,
    or Nones where the platform does not publish them (Windows, macOS, a stripped container).
    """
    read = reader if reader is not None else _read_text
    out = {"current_clocksource": None, "available_clocksource": None, "cpu_flags": {}}

    cur = read(root + CLOCKSOURCE_CURRENT)
    if cur:
        out["current_clocksource"] = cur.strip()
    avail = read(root + CLOCKSOURCE_AVAILABLE)
    if avail:
        out["available_clocksource"] = avail.split()

    info = read(root + CPUINFO)
    if info:
        flags = set()
        for line in info.splitlines():
            if line.startswith("flags") and ":" in line:
                flags |= set(line.split(":", 1)[1].split())
        out["cpu_flags"] = {f: (f in flags) for f in TSC_FLAGS}
    return out


def _read_text(path):  # pragma: no cover - exercised through injection
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def probe(ports=None, trials=50, sleep_trials=200, connect=None, redis_name="redis",
          opener=None):
    """Full testbed characterisation as a JSON-serialisable dict."""
    ports = ports if ports is not None else {"kafka": ("localhost", 9092),
                                             "redis": ("localhost", 6379)}
    res = timer_resolution()
    out = {
        "platform": platform_info(),
        "clock_provenance": clock_provenance(),
        "timer_resolution_ns": None if res is None else res * 1e9,
        "sleep_1ms": sleep_granularity(0.001, sleep_trials),
        "sleep_10ms": sleep_granularity(0.010, max(20, sleep_trials // 10)),
        "broker_rtt": {name: tcp_rtt(h, p, trials, connect=connect)
                       for name, (h, p) in sorted(ports.items())},
    }
    if redis_name in ports:
        h, p = ports[redis_name]
        out["redis_ping_rtt"] = redis_ping_rtt(h, p, max(20, trials * 4), opener=opener)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Characterise the measurement testbed")
    ap.add_argument("--out", default="docs/results/platform/platform.json")
    ap.add_argument("--trials", type=int, default=50)
    ap.add_argument("--sleep-trials", type=int, default=200)
    ap.add_argument("--port", action="append", default=[], metavar="NAME=HOST:PORT",
                    help="broker endpoint to probe; repeatable "
                         "(e.g. --port kafka=localhost:19092 --port redis=localhost:16379)")
    ap.add_argument("--clock-only", action="store_true",
                    help="record only the clock's identity and cross-CPU guarantees, and "
                         "exit; needs no brokers running, so it can be run on a restored "
                         "image whose services were never started")
    args = ap.parse_args(argv)

    if args.clock_only:
        info = {"platform": platform_info(), "clock_provenance": clock_provenance()}
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(info, indent=2, sort_keys=True), encoding="utf-8")
        cp = info["clock_provenance"]
        print("platform          : %s" % info["platform"]["platform"])
        print("current clocksource: %s" % (cp["current_clocksource"] or "not published"))
        print("available          : %s" % (", ".join(cp["available_clocksource"] or [])
                                           or "not published"))
        for flag, present in sorted(cp["cpu_flags"].items()):
            print("  %-16s %s" % (flag, "yes" if present else "no"))
        print("\nwrote %s" % out)
        return 0

    try:
        ports = parse_ports(args.port) if args.port else None
    except ValueError as e:
        print(e)
        return 1
    info = probe(ports=ports, trials=args.trials, sleep_trials=args.sleep_trials)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(info, indent=2, sort_keys=True), encoding="utf-8")

    p = info["platform"]
    print(f"platform      : {p['platform']} (Python {p['python_version']})")
    if info["timer_resolution_ns"] is not None:
        print(f"timer resol.  : {info['timer_resolution_ns']:.0f} ns")
    s = info["sleep_1ms"]
    print(f"sleep(1ms)    : median {s['median_ms']:.3f} ms "
          f"(overshoot {s['overshoot_median_ms']:+.3f} ms, max {s['max_ms']:.3f} ms)")
    s10 = info["sleep_10ms"]
    print(f"sleep(10ms)   : median {s10['median_ms']:.3f} ms "
          f"(overshoot {s10['overshoot_median_ms']:+.3f} ms)")
    for name, r in info["broker_rtt"].items():
        if r["reachable"]:
            print(f"{name:<14}: TCP connect RTT median {r['median_ms']:.3f} ms "
                  f"(min {r['min_ms']:.3f}, max {r['max_ms']:.3f})")
        else:
            print(f"{name:<14}: unreachable ({r['errors']} errors)")
    ping = info.get("redis_ping_rtt")
    if ping and ping["reachable"]:
        print(f"redis PING    : established-connection RTT median {ping['median_ms']:.3f} ms "
              f"=> ceiling {ping['implied_ceiling_msgs_per_s']:.0f} msg/s")
    elif ping:
        print("redis PING    : unreachable")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
