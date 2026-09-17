#!/usr/bin/env python3
"""
receiver_delay.py -- delay what the receiver gets, and nothing else, and prove that.

Why this exists. The sender and the receiver run on one machine, so the broker's replies to both
travel the same link. A delay added to that whole link slows the producer's "got it" reply
exactly as much as the message. The two timestamps move together and the span between them does
not change. That is how the earlier broker-side delay (E-B2, see
cloud/campaigns/stamping_priority.sh) produced a null: it acted on both sides of a subtraction.

The fix gives the receiver its own address.

  driver   a network namespace, sblrecv, holding an ipvlan interface on the driver's network
           card with the receiver's address, which Azure already routes to that card. A process
           started inside it (`ip netns exec sblrecv ...`) connects from that address. The clock
           and the scheduler are still the host's: a namespace moves the network, not time.
  broker   a four-band priority queue on the broker's card. The default priority map only ever
           uses the first three bands, so the fourth holds exactly what the filter puts there:
           packets addressed to the receiver. A netem delay sits on that band alone.

The trial runners start the consumer through SBL_CONSUMER_WRAP, so a campaign sets it to
`sudo ip netns exec sblrecv sudo -u $USER` and nothing else about the run changes.

The check, at every delay step. ping the broker from the host and from the namespace. The host's
round trip carries the producer's path and must not move. The namespace's carries the receiver's
and must move by the added delay. Both medians are recorded, and a run is given the measured
added delay, not the setting.

Commands are printed; --apply also runs them, and they need root:
    python3 scripts/receiver_delay.py broker --dst 10.1.1.11 --delay-ms 0.5 --apply
    python3 scripts/receiver_delay.py broker-clear --apply
    python3 scripts/receiver_delay.py driver --address 10.1.1.11/24 --gateway 10.1.1.1 --apply
    python3 scripts/receiver_delay.py driver-clear --apply
    python3 scripts/receiver_delay.py measure --broker 10.1.1.21 --out step.json
    python3 scripts/receiver_delay.py verify --baseline base.json --step step.json --added-ms 0.5
"""
import argparse
import ipaddress
import json
import re
import statistics
import subprocess
import sys

NETNS = "sblrecv"
LINK = "sblrecv0"

#: netem's own queue must never be the bottleneck. cloud/netem.sh records the multi-second stall
#: its default limit of 1000 packets caused.
LIMIT = 200000

#: Linux's default priority map. It names bands 0, 1 and 2 only, so with four bands the fourth
#: receives nothing the filter does not send it.
PRIOMAP = "1 2 2 2 1 2 0 0 1 1 1 1 1 1 1 1"

PING_TIME = re.compile(r"time=([\d.]+) ms")
#: One echo packet as tcpdump -nn -tt --time-stamp-precision=nano prints it.
CAPTURE_LINE = re.compile(r"^(\d+\.\d+) IP (\S+) > (\S+): ICMP echo (request|reply), "
                          r"id (\d+), seq (\d+)")


def delay_us(ms):
    """A delay in whole microseconds, the unit tc is given, so 0.5 ms reaches tc exactly."""
    us = int(round(float(ms) * 1000))
    if us < 0:
        raise ValueError("a delay cannot be negative: %s ms" % ms)
    return us


def broker_commands(dst, delay_ms, dev="eth0"):
    """(argv, may_fail) pairs that delay packets to `dst` alone, starting from a clean card.

    Delay steps are applied between runs, never during one: deleting the root queue drops what
    netem is holding.
    """
    ipaddress.ip_address(dst)
    us = delay_us(delay_ms)
    return [
        (["tc", "qdisc", "del", "dev", dev, "root"], True),
        (["tc", "qdisc", "add", "dev", dev, "root", "handle", "1:", "prio", "bands", "4",
          "priomap"] + PRIOMAP.split(), False),
        (["tc", "qdisc", "add", "dev", dev, "parent", "1:4", "handle", "40:", "netem",
          "delay", "%dus" % us, "limit", str(LIMIT)], False),
        (["tc", "filter", "add", "dev", dev, "parent", "1:0", "protocol", "ip", "prio", "1",
          "u32", "match", "ip", "dst", "%s/32" % dst, "flowid", "1:4"], False),
    ]


def broker_clear_commands(dev="eth0"):
    return [(["tc", "qdisc", "del", "dev", dev, "root"], True)]


def driver_commands(address, gateway, dev="eth0", mode="l2"):
    """(argv, may_fail) pairs that build the receiver's namespace from scratch."""
    if "/" not in address:
        raise ValueError("give the receiver's address with its subnet prefix, "
                         "for example 10.1.1.11/24, not %r" % address)
    iface = ipaddress.ip_interface(address)
    gw = ipaddress.ip_address(gateway)
    if gw not in iface.network:
        raise ValueError("gateway %s is not in the receiver's subnet %s" % (gw, iface.network))
    # Azure's first boot writes every address of the card into netplan, so the host holds the
    # receiver's address too and sends its own subnet traffic from it. Once the namespace owns
    # the address, the replies to that traffic land in the namespace and the host loses the
    # broker. Every boot puts the address back; deleting one that is already gone is harmless.
    # It must leave netplan's own settings too: on 16 September a package upgrade restarted
    # systemd-networkd in the middle of a pilot, networkd put the address back from those
    # settings, and the driver lost its broker. The card's own address comes by DHCP, so its
    # static addresses are exactly the ones Azure added for the receiver. Both commands can run
    # again and again; the next boot writes the address back and the next session removes it.
    return [
        (["ip", "netns", "del", NETNS], True),
        (["ip", "link", "del", LINK], True),
        (["ip", "addr", "del", str(iface), "dev", dev], True),
        (["netplan", "set", "--origin-hint", "50-cloud-init",
          "ethernets.%s.addresses=null" % dev], False),
        (["netplan", "generate"], False),
        (["ip", "netns", "add", NETNS], False),
        (["ip", "link", "add", LINK, "link", dev, "type", "ipvlan", "mode", mode], False),
        (["ip", "link", "set", LINK, "netns", NETNS], False),
        (["ip", "-n", NETNS, "addr", "add", str(iface), "dev", LINK], False),
        (["ip", "-n", NETNS, "link", "set", "lo", "up"], False),
        (["ip", "-n", NETNS, "link", "set", LINK, "up"], False),
        (["ip", "-n", NETNS, "route", "add", "default", "via", str(gw)], False),
    ]


def driver_clear_commands():
    return [(["ip", "netns", "del", NETNS], True), (["ip", "link", "del", LINK], True)]


def broker_holds_ms(text, host, receiver):
    """{"host": [...], "receiver": [...]}: how long the broker held each echo reply, in ms.

    Read from the broker's own capture: the kernel stamps a request as it arrives and a reply as
    it leaves the queue the delay sits in, so the difference is the delay the broker added plus
    its own handling, whatever the network does before or after. Ping prints its round trips to
    0.01 ms above 1 ms and to 0.1 ms above 10 ms; the capture prints nanoseconds.
    """
    asked, held = {}, {"host": [], "receiver": []}
    for line in (text or "").splitlines():
        found = CAPTURE_LINE.match(line)
        if not found:
            continue
        stamp, src, dst, kind, ident, seq = found.groups()
        if kind == "request":
            asked[(src, ident, seq)] = float(stamp)
            continue
        start = asked.get((dst, ident, seq))
        side = "receiver" if dst == receiver else "host" if dst == host else None
        if start is not None and side:
            held[side].append((float(stamp) - start) * 1000.0)
    return held


def hold_summary(held):
    """Median holds for both sides, or a ValueError when a side has none."""
    for side in ("host", "receiver"):
        if not held[side]:
            raise ValueError("the capture holds no answered ping from the %s" % side)
    return {"host_hold_ms": statistics.median(held["host"]),
            "receiver_hold_ms": statistics.median(held["receiver"]),
            "replies_host": len(held["host"]), "replies_receiver": len(held["receiver"])}


def verify_hold(baseline, step, added_ms, tolerance_ms=0.05):
    """(ok, report) for one delay step, from the broker's captures with and without the delay:
    the host's replies are held no longer than before, and the receiver's are held for the set
    delay beyond the host's."""
    host_shift = step["host_hold_ms"] - baseline["host_hold_ms"]
    excess = ((step["receiver_hold_ms"] - step["host_hold_ms"])
              - (baseline["receiver_hold_ms"] - baseline["host_hold_ms"]) - added_ms)
    report = {
        "added_ms_set": added_ms,
        "added_ms_held": added_ms + excess,
        "host_hold_shift_ms": host_shift,
        "receiver_excess_ms": excess,
        "tolerance_ms": tolerance_ms,
        "host_replies_not_held": abs(host_shift) <= tolerance_ms,
        "receiver_replies_held_for_the_delay": abs(excess) <= tolerance_ms,
    }
    report["ok"] = report["host_replies_not_held"] and report["receiver_replies_held_for_the_delay"]
    return report["ok"], report


def run_commands(commands, apply=False, run=subprocess.run, out=None):
    """Print each command; with `apply`, run it too, stopping at the first failure that counts."""
    out = out or sys.stdout
    for argv, may_fail in commands:
        note = "    # may fail harmlessly" if may_fail else ""
        print(("$ " if apply else "") + " ".join(argv) + note, file=out)
        if not apply:
            continue
        done = run(argv, capture_output=True, text=True)
        if done.returncode != 0 and not may_fail:
            print("FAILED (%d): %s" % (done.returncode, (done.stderr or "").strip()), file=out)
            return done.returncode
    return 0


def ping_times_ms(text):
    """Round-trip times from ping's per-reply lines."""
    return [float(v) for v in PING_TIME.findall(text or "")]


def ping_command(broker, count, interval, netns=None):
    argv = ["ping", "-n", "-c", str(count), "-i", str(interval), broker]
    return ["ip", "netns", "exec", netns] + argv if netns else argv


def measure(broker, count=200, interval=0.01, run=subprocess.run, blocks=4):
    """Median round trip to the broker from the host and from the receiver's namespace.

    The two pings alternate in blocks rather than running one after the other, so a drift in
    the path during the measurement lands on both.
    """
    host, receiver = [], []
    per_block = max(1, count // blocks)
    for _ in range(blocks):
        for times, netns in ((host, None), (receiver, NETNS)):
            done = run(ping_command(broker, per_block, interval, netns),
                       capture_output=True, text=True)
            if done.returncode != 0:
                raise RuntimeError("ping %s from %s failed: %s"
                                   % (broker, netns or "the host",
                                      (done.stderr or done.stdout or "").strip()))
            times.extend(ping_times_ms(done.stdout))
    if not host or not receiver:
        raise RuntimeError("ping printed no round-trip times")
    return {"broker": broker, "replies_host": len(host), "replies_receiver": len(receiver),
            "host_median_ms": statistics.median(host),
            "receiver_median_ms": statistics.median(receiver)}


def verify(baseline, step, added_ms, tolerance_ms=0.05):
    """(ok, report) for one delay step against the zero-delay baseline."""
    host_shift = step["host_median_ms"] - baseline["host_median_ms"]
    receiver_shift = step["receiver_median_ms"] - baseline["receiver_median_ms"]
    report = {
        "added_ms_set": added_ms,
        "added_ms_measured": receiver_shift - host_shift,
        "host_shift_ms": host_shift,
        "receiver_shift_ms": receiver_shift,
        "tolerance_ms": tolerance_ms,
        "sender_path_unchanged": abs(host_shift) <= tolerance_ms,
        "receiver_path_moved_by_the_delay": abs(receiver_shift - added_ms) <= tolerance_ms,
    }
    report["ok"] = report["sender_path_unchanged"] and report["receiver_path_moved_by_the_delay"]
    return report["ok"], report


def main(argv=None, run=subprocess.run, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Delay what the receiver gets, and prove it")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("broker")
    p.add_argument("--dst", required=True)
    p.add_argument("--delay-ms", type=float, required=True)
    p.add_argument("--dev", default="eth0")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("broker-clear")
    p.add_argument("--dev", default="eth0")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("driver")
    p.add_argument("--address", required=True)
    p.add_argument("--gateway", required=True)
    p.add_argument("--dev", default="eth0")
    p.add_argument("--mode", choices=("l2", "l3"), default="l2")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("driver-clear")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("measure")
    p.add_argument("--broker", required=True)
    p.add_argument("--count", type=int, default=200)
    p.add_argument("--interval", type=float, default=0.01)
    p.add_argument("--out", default="")
    p = sub.add_parser("verify")
    p.add_argument("--baseline", required=True)
    p.add_argument("--step", required=True)
    p.add_argument("--added-ms", type=float, required=True)
    p.add_argument("--tolerance-ms", type=float, default=0.05)
    p = sub.add_parser("holds")
    p.add_argument("--capture", required=True, help="the broker's tcpdump of the pings")
    p.add_argument("--host", required=True, help="the driver's own address")
    p.add_argument("--receiver", required=True, help="the receiver's address")
    p.add_argument("--out", default="")
    p = sub.add_parser("verify-hold")
    p.add_argument("--baseline", required=True)
    p.add_argument("--step", required=True)
    p.add_argument("--added-ms", type=float, required=True)
    p.add_argument("--tolerance-ms", type=float, default=0.05)
    args = ap.parse_args(argv)
    try:
        if args.command == "broker":
            return run_commands(broker_commands(args.dst, args.delay_ms, args.dev),
                                args.apply, run, out)
        if args.command == "broker-clear":
            return run_commands(broker_clear_commands(args.dev), args.apply, run, out)
        if args.command == "driver":
            return run_commands(driver_commands(args.address, args.gateway, args.dev,
                                                args.mode), args.apply, run, out)
        if args.command == "driver-clear":
            return run_commands(driver_clear_commands(), args.apply, run, out)
        if args.command == "measure":
            text = json.dumps(measure(args.broker, args.count, args.interval, run),
                              indent=2, sort_keys=True)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as fh:
                    fh.write(text + "\n")
            print(text, file=out)
            return 0
        if args.command == "holds":
            with open(args.capture, encoding="utf-8") as fh:
                summary = hold_summary(broker_holds_ms(fh.read(), args.host, args.receiver))
            text = json.dumps(summary, indent=2, sort_keys=True)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as fh:
                    fh.write(text + "\n")
            print(text, file=out)
            return 0
        with open(args.baseline, encoding="utf-8") as fh:
            baseline = json.load(fh)
        with open(args.step, encoding="utf-8") as fh:
            step = json.load(fh)
        check = verify_hold if args.command == "verify-hold" else verify
        ok, report = check(baseline, step, args.added_ms, args.tolerance_ms)
        print(json.dumps(report, indent=2, sort_keys=True), file=out)
        return 0 if ok else 1
    except (ValueError, RuntimeError, OSError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
