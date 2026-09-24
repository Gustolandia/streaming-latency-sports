"""Our own HTTP client: the reference the HTTP tools' figures are read against.

Every number the tools block reports is meant to have a reference measured beside it -- our own
program, on the same path. For Kafka and Redis that program is the study's own producer and
consumer. For HTTP there was none, so vegeta, hey, k6 and wrk2 had no reference at all, and T2,
which takes its offsets from the reference's median trip and predicts each behaviour from its
trips, could not be asked of any of them.

This is that reference. One connection, kept alive as the tools keep theirs, a GET of the fixed
512-byte page paced at the rate the tools run at, each timed on the monotonic clock from the
moment the request is written to the moment the whole response has been read. What the tools
time is the same interval, so its median is a trip they can be held to. The first seconds are
set aside as the tools' own warm-up is. A request that does not come back 200 with the whole
page is counted and kept out: a failure is not a trip.
"""
import argparse
import http.client
import json
import statistics
import sys
import time

#: The page the tools block serves, fixed so every tool is timed against the same thing.
PAGE_BYTES = 512


def trips(host, port, path="/", rate=50.0, seconds=130.0, warmup_s=30.0,
          clock=time.perf_counter_ns, sleep=time.sleep, connect=http.client.HTTPConnection):
    """Paced GETs for `seconds`, as (trips in ms after the warm-up, how many sent, how many failed).

    Paced open-loop from a fixed start, so a slow response does not push every later request
    back, which is how a closed loop hides the very delays it is meant to time.
    """
    conn = connect(host, port, timeout=5)
    start, period_ns, n = clock(), int(1e9 / rate), 0
    found, failed = [], 0
    while True:
        #: The schedule decides when to stop, not the clock after the last answer: a request due
        #: at the end of the run is one past it, and the rate asked for is what is sent.
        due = start + n * period_ns
        if due - start >= seconds * 1e9:
            break
        now = clock()
        if due > now:
            sleep((due - now) / 1e9)
        began = clock()
        try:
            conn.request("GET", path)
            answer = conn.getresponse()
            body = answer.read()
            ok = answer.status == 200 and len(body) == PAGE_BYTES
        except (OSError, http.client.HTTPException):
            ok = False
            conn.close()
            conn = connect(host, port, timeout=5)
        ended = clock()
        n += 1
        if not ok:
            failed += 1
        elif began - start >= warmup_s * 1e9:
            found.append((ended - began) / 1e6)
    conn.close()
    return found, n, failed


def main(argv=None, out=None, clock=time.perf_counter_ns, sleep=time.sleep,
         connect=http.client.HTTPConnection):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Our own HTTP client, as the reference for T1 and T2")
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--path", default="/")
    ap.add_argument("--rate", type=float, default=50.0)
    ap.add_argument("--seconds", type=float, default=130.0)
    ap.add_argument("--warmup-s", type=float, default=30.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    found, sent, failed = trips(args.host, args.port, args.path, args.rate, args.seconds,
                                args.warmup_s, clock=clock, sleep=sleep, connect=connect)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"client": "http_reference.py", "trips_ms": found, "sent": sent,
                   "failed": failed, "target": "http://%s:%d%s" % (args.host, args.port,
                                                                   args.path)}, fh)
    if not found:
        print("no trip was timed: %d sent, %d failed" % (sent, failed), file=out)
        return 1
    print("%d trips timed of %d sent, %d failed; median %.3f ms"
          % (len(found), sent, failed, statistics.median(found)), file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - the dispatch is exercised through main()
    sys.exit(main())
