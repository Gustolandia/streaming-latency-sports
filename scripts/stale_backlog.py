#!/usr/bin/env python3
"""
stale_backlog.py
Which messages of a July 2026 cloud run arrived late because the consumer was still reading
other runs' messages. Every analysis of those runs leaves them out.

What happened. The July testbed's runs reused topic and stream names from one campaign to the
next (sb-events-n5-feed2-rep1, sb:events:n5:feed2:rep1, ...), and nothing cleared them:
scripts/run_redis_trial.sh deleted its stream with redis-cli, which the driver did not have,
and discarded the error, and the Kafka trial never cleared its topics. A run's consumer reads
its topic or stream from the beginning, under a group of its own, and discards other runs'
messages, so it first read every earlier campaign's messages. Until it caught up, its own
messages waited: seconds on Kafka, and up to ten minutes on Redis.

The rule. A message is late when its delivery took more than LATE_MARGIN_MS longer than the
run's fastest. The consumer caught up when it received the last such message, and a message
published before then that reached it within LATE_MARGIN_MS of that instant is late too: it came
in the same burst, and waited behind the same backlog for less than the margin. The margin finds
a backlog, and the burst bounds it. Every message of a run is late when even its fastest
delivery took longer than LATE_MARGIN_MS, because its consumer never caught up. A wait in
mid-run would not take the run's earlier messages with it, since the consumer had received
those long before, and on these runs there is none: in every run with a late message its first
published message is one (backlog_census.py, first_waited). A delivery on this testbed takes
milliseconds, and the longest manipulation,
padding to 256 KB, about 190 ms on Kafka; a wait behind a backlog takes seconds to minutes. Over
the 5,913 runs of Table I's corpus (7 Oct 2026) the two are apart: a run's fastest delivery took
1.5 ms at the median and under 111 ms in 99% of runs, none between 300 ms and 1 s, and over a
second in the 50 runs that never caught up. Of the 30,225 messages the rule flags, in 2,099
runs, none has a value of S below zero, which a message that waited in the broker for its
consumer cannot have; in every run they are its first messages; and every Redis run with one
had read other runs' messages first, by its read trace.

The fastest delivery rather than a percentile: a run whose consumer caught up only for its last
few messages has most of its deliveries late, and a percentile would sit among them.

A backlog read in under a second escapes the rule. backlog_census.py counts what a wider rule
would also leave out, and the supplement reports how little that moves the rate.

The registered Azure campaign cleared its streams; 0.04% of its messages are late, and its
programs were fixed before its runs, so the rule applies to the July runs alone.
"""

import csv
import os

#: How much later than the run's fastest delivery a message may arrive and still count, in ms.
LATE_MARGIN_MS = 1000.0


def late(sent_ns, received_ns):
    """One flag per message, in the order given: True where it waited behind a backlog.

    sent_ns and received_ns are the messages' publish and receipt timestamps in nanoseconds.
    """
    deliveries = [(r - s) / 1e6 for s, r in zip(sent_ns, received_ns)]
    if not deliveries:
        return []
    fastest = min(deliveries)
    if fastest > LATE_MARGIN_MS:
        # The consumer never caught up: even the run's fastest delivery waited.
        return [True] * len(deliveries)
    waited = [r for d, r in zip(deliveries, received_ns) if d > fastest + LATE_MARGIN_MS]
    if not waited:
        return [False] * len(deliveries)
    # The consumer caught up when it received the last of them. A message published before then
    # that reached it within the margin of that instant came in the same burst, and waited
    # behind the same backlog for less than the margin; one it had received earlier had not.
    caught_up = max(waited)
    burst = caught_up - LATE_MARGIN_MS * 1e6
    return [d > fastest + LATE_MARGIN_MS or (s < caught_up and r >= burst)
            for d, s, r in zip(deliveries, sent_ns, received_ns)]


def late_ids(prod_rows, cons_rows):
    """The event ids of a run's late messages, from its producer and consumer records.

    Every reader of the July runs skips these ids, whichever consumer file it reads, so they
    all leave out the same messages and their cross-checks still agree. D is the consumer's
    receipt timestamp less the producer's publish timestamp; a message missing either, or
    unmatched, has no D and is not judged.
    """
    sent = {}
    for row in prod_rows:
        try:
            sent[row["event_id"]] = int(row["t_prod_send_ns"])
        except (KeyError, TypeError, ValueError):
            continue
    ids, sends, receipts = [], [], []
    for row in cons_rows:
        send = sent.get(row.get("event_id"))
        if send is None:
            continue
        try:
            recv = int(row["t_cons_recv_ns"])
        except (KeyError, TypeError, ValueError):
            continue
        ids.append(row["event_id"])
        sends.append(send)
        receipts.append(recv)
    return {i for i, flag in zip(ids, late(sends, receipts)) if flag}


def late_ids_in(run_dir):
    """The same, read from a run folder's producer.csv and consumer.csv; empty without them."""
    paths = [os.path.join(run_dir, name) for name in ("producer.csv", "consumer.csv")]
    if not all(os.path.exists(p) for p in paths):
        return set()
    rows = []
    for path in paths:
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            rows.append(list(csv.DictReader(fh)))
    return late_ids(*rows)
