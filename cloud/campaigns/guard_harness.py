#!/usr/bin/env python3
"""
guard_harness.py -- the timestamp-guard pattern with no JVM anywhere.

Referee concern M1: every instrumented run of the deletion law is OMB's Java stack, so the law
could in principle be a property of that code path rather than of the pattern it implements.
This harness is the pattern and nothing else, in ~200 lines of Python against Redis Streams:

    producer:  paced at a fixed rate; each message carries int(time.time()*1000) -- the same
               millisecond quantum as Java's System.currentTimeMillis
    consumer:  on receipt computes recv_ms - sent_ms and applies OMB's guard verbatim:
               d > 0 kept, d == 0 discarded, d < 0 discarded -- with the sign COUNTED, which is
               the instrumentation OMB lacked
    pacer:     absolute schedule (start + i*interval), sleep to the slot, and the offset between
               planned and actual send instant is RECORDED per send -- the per-run jitter
               instrument referee concern M3 asks for

Roles allow the two processes to run on one host (one clock: any negative is impossible, as on
the co-located OMB path) or on two hosts (two chrony-disciplined clocks: the cross-host case of
referee concern M2, which OMB's distributed mode never let us measure).

The consumer prints one JSON line; the producer prints one JSON line. The runner combines them
into the cell's harness_result.json. No statistics are computed here beyond counts and jitter
percentiles: analysis belongs to the committed analysis scripts, not the instrument.

Usage:
    guard_harness.py --role consumer --redis-host H --stream K --idle-exit 30
    guard_harness.py --role producer --redis-host H --stream K --rate 500 --duration 180
"""
import argparse
import json
import sys
import time

import redis


def now_ms():
    """The instrument's clock: wall time quantised to the millisecond, as OMB's stamps are."""
    return int(time.time() * 1000)


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    k = min(len(sorted_vals) - 1, max(0, int(round(p / 100.0 * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def run_producer(r, stream, rate, duration, payload_bytes):
    interval = 1.0 / rate
    n = int(duration * rate)
    pad = "x" * payload_bytes
    offsets_us = []
    start = time.perf_counter() + 0.25          # a beat of slack so slot 0 is not already late
    wall0 = time.time()
    for i in range(n):
        slot = start + i * interval
        while True:
            d = slot - time.perf_counter()
            if d <= 0:
                break
            time.sleep(d if d > 0.0005 else 0)   # busy-wait the last half millisecond
        offsets_us.append((time.perf_counter() - slot) * 1e6)
        r.xadd(stream, {"t": now_ms(), "p": pad}, maxlen=200000, approximate=True)
    r.xadd(stream, {"end": 1}, maxlen=200000, approximate=True)
    offsets_us.sort()
    print(json.dumps({
        "role": "producer", "rate": rate, "duration_s": duration, "sent": n,
        "payload_bytes": payload_bytes, "wall_start": wall0,
        "jitter_us": {"p50": percentile(offsets_us, 50), "p90": percentile(offsets_us, 90),
                      "p99": percentile(offsets_us, 99), "max": offsets_us[-1] if offsets_us else None},
    }))


def run_consumer(r, stream, idle_exit):
    kept = zero = neg = 0
    most_negative = None
    last_id = "0-0"
    idle_since = time.time()
    while True:
        resp = r.xread({stream: last_id}, count=1000, block=1000)
        if not resp:
            if time.time() - idle_since > idle_exit:
                break
            continue
        idle_since = time.time()
        for _, entries in resp:
            for eid, fields in entries:
                last_id = eid
                if b"end" in fields or "end" in fields:
                    print(json.dumps({"role": "consumer", "kept": kept, "discarded_zero": zero,
                                      "discarded_negative": neg,
                                      "most_negative_ms": most_negative}))
                    return
                sent = int(fields[b"t"] if b"t" in fields else fields["t"])
                d = now_ms() - sent
                # OMB's guard, verbatim in effect: only d > 0 reaches the histogram.
                if d > 0:
                    kept += 1
                elif d == 0:
                    zero += 1
                else:
                    neg += 1
                    if most_negative is None or d < most_negative:
                        most_negative = d
    # Idle timeout without an end marker: report what was seen, flagged.
    print(json.dumps({"role": "consumer", "kept": kept, "discarded_zero": zero,
                      "discarded_negative": neg, "most_negative_ms": most_negative,
                      "truncated": True}))


def main(argv=None):
    ap = argparse.ArgumentParser(description="The timestamp-guard pattern, minimally")
    ap.add_argument("--role", choices=("producer", "consumer"), required=True)
    ap.add_argument("--redis-host", default="127.0.0.1")
    ap.add_argument("--redis-port", type=int, default=6379)
    ap.add_argument("--stream", required=True)
    ap.add_argument("--rate", type=float, default=500.0)
    ap.add_argument("--duration", type=float, default=180.0)
    ap.add_argument("--payload-bytes", type=int, default=200)
    ap.add_argument("--idle-exit", type=float, default=30.0)
    ap.add_argument("--fresh", action="store_true", help="producer deletes the stream first")
    args = ap.parse_args(argv)

    r = redis.Redis(host=args.redis_host, port=args.redis_port, socket_timeout=30)
    r.ping()
    if args.role == "producer":
        if args.fresh:
            r.delete(args.stream)
        run_producer(r, args.stream, args.rate, args.duration, args.payload_bytes)
    else:
        run_consumer(r, args.stream, args.idle_exit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
