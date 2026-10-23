#!/usr/bin/env python3
"""
kafka_consumer_confluent.py -- the Kafka consumer on librdkafka, through confluent-kafka-python,
writing the files scripts/kafka_consumer.py writes, so that the reader and the integrity rule
cannot tell which client produced a run.

Block U found that a pull consumer lets its own thread's delays into the measured latency through
its next request, for kafka-python, which builds each fetch on the thread that calls poll(). None
of the measuring tools the paper audits uses kafka-python. librdkafka keeps the fetching off the
application's thread: each broker connection has a thread of its own, named rdk:broker<N> by the
broker's node id, which sends the next fetch as soon as the answer to the last one is handled,
whatever the application is doing, so long as no fetch is outstanding on that connection and the
partition's local queue holds fewer than queued.min.messages messages and less than
queued.max.messages.kbytes (librdkafka v2.15.1: rd_kafka_broker_consumer_serve and
rd_kafka_broker_thread_main in src/rdkafka_broker.c, rd_kafka_toppar_fetch_decide in
src/rdkafka_fetcher.c). poll() here takes a message from that queue and sends nothing.

What is kept from kafka_consumer.py: a group of its own, the earliest offset where the group has
none, the payload's JSON, the run filter on its run_id, the stop after --idle-seconds with no
message of this run, the two CSV files and their columns, and the stamps:

    t_consume_ns    time.time_ns(), CLOCK_REALTIME, as poll() hands this thread the message
    t_cons_recv_ns  the same reading, under the name consumer.csv gives it
    t_output_ns     time.time_ns() again, read next

Each message is identified as the broker identifies it, by the partition and offset librdkafka
hands back with it; the payload's event_id is only copied into its column.

Fetching is librdkafka's own, at its defaults, except where --fetch-wait-max-ms or
--queued-min-messages sets fetch.wait.max.ms or queued.min.messages.

The switches the other Python clients take are taken here, and do what they can:

  --so-timestamps, --so-transmit, --so-journal
        accepted, and nothing is read: the shim replaces Python's socket class, and librdkafka
        opens and reads its sockets in C, where that class is never used. A run that asks for
        them gets a summary saying so, beside where the reading would have gone; this client's
        kernel stamps come from the captures on its host.
  --gc-off, --gc-log
        as in every Python client: they act on this process's Python objects.
  --schedstat PATH
        samples the thread that sends the requests, and here that is librdkafka's broker thread,
        not this one: the CSV holds its header alone, and the reason is in the log and in the GC
        JSON.
  --thread-record, --read-trace
        as in kafka_consumer.py; a poll here brings one message at most.

--threads-out PATH writes, once the group has assigned the partitions, each of this process's
threads: its id, the kernel's name for it, its role (poll for the thread that calls poll() and
stamps the messages, fetch for rdk:broker<N> of each assigned partition's leader) and the name
Python gives it, if any. The kit sets one thread's policy from it with chrt -f -p 80 <tid>.

confluent-kafka is imported when a run starts, not when this file is, so the tests run without it.
"""
import argparse
import csv
import json
import os
import sys
import threading
import time
from pathlib import Path

import client_quiet
import law_clock
import so_timestamps
import thread_record

#: consumer.csv and consumer_events.csv, column for column as scripts/kafka_consumer.py writes them.
CONSUMER_COLUMNS = ["run_id", "backend", "topic", "event_id", "match_id", "t_sim_seconds",
                    "t_cons_recv_ns", "t_output_ns"]
EVENT_COLUMNS = ["run_id", "backend", "topic", "partition", "offset", "t_consume_ns", "event_id",
                 "match_id", "t_sim_seconds", "t_emit_offset_s", "t_emit_planned_ns", "s3_uid",
                 "s3_rev", "s3_is_correction"]

#: --threads-out's columns, the same in the three consumers that take it (this one,
#: harness/java/src/LawConsumer.java and harness/go/main.go).
THREAD_COLUMNS = ["tid", "name", "role", "runtime_name"]

#: Where the kernel lists this process's threads: one directory per thread, named by its id, with
#: the thread's name in `comm`. A module constant, so the tests can point it elsewhere.
TASKS = "/proc/self/task"

#: Why --so-timestamps reads nothing here, written where its summary would go.
SO_ELSEWHERE = ("librdkafka opens and reads its sockets in C, where the socket-timestamp shim, "
                "which replaces Python's socket class, never reaches; this client's kernel "
                "stamps come from the captures on its host")

#: Why --schedstat samples nothing here, in the client's log and in the GC JSON.
SCHEDSTAT_ELSEWHERE = ("librdkafka sends the fetch requests from its broker thread "
                       "(rdk:broker<N>), not from the thread that calls poll(), and this process "
                       "samples only the thread that calls poll()")


def now_ns():
    """Wall-clock epoch ns, CLOCK_REALTIME, the clock of the producer's stamps."""
    return time.time_ns()


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Kafka consumer on librdkafka (confluent-kafka)")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--topic", default="sb-events")
    ap.add_argument("--bootstrap", default="localhost:9092")
    # 23 Oct 2026: taken as kafka_consumer.py takes it, so that one command line in the kit serves
    # both; the brokers are the ones --bootstrap names.
    ap.add_argument("--broker-count", type=int, default=1, choices=[1, 3])
    ap.add_argument("--group", default=None)
    ap.add_argument("--idle-seconds", type=int, default=15)
    ap.add_argument("--poll-timeout-ms", type=int, default=1000)
    ap.add_argument("--fetch-wait-max-ms", type=int, default=None,
                    help="librdkafka's fetch.wait.max.ms; its default when not given")
    ap.add_argument("--queued-min-messages", type=int, default=None,
                    help="librdkafka's queued.min.messages; its default when not given")
    ap.add_argument("--threads-out", default=None,
                    help="once the partitions are assigned, write this process's threads here")
    ap.add_argument("--thread-record", action="store_true",
                    help="write which thread stamped the arrivals, and both clocks, beside the CSV")
    ap.add_argument("--read-trace", action="store_true",
                    help="write each poll's start, duration and message count beside the CSV")
    so_timestamps.add_arguments(ap)
    client_quiet.add_arguments(ap)
    return ap.parse_args(argv)


def build_config(args, group_id):
    """librdkafka's settings: a group of its own and the earliest offset, as kafka_consumer.py
    asks of kafka-python, and fetching at librdkafka's defaults unless a flag sets them."""
    conf = {
        "bootstrap.servers": args.bootstrap,
        "group.id": group_id,
        # 23 Oct 2026: the classic group protocol is librdkafka v2.15.1's default and the only one
        # kafka-python 2.3.2 speaks; named, so that a later default cannot change the block's.
        "group.protocol": "classic",
        "auto.offset.reset": "earliest",
        # 23 Oct 2026: the topic is named for the run and made by whichever client first asks the
        # broker for it, and the kit starts the consumer two seconds before the producer. Kafka's
        # Java consumer asks for a topic it subscribes to to be made (allow.auto.create.topics,
        # true by default in kafka-clients 3.9.0); librdkafka's consumer does not by default
        # (false, v2.15.1's CONFIGURATION.md), and would then wait on the producer making the
        # topic and on its own next metadata refresh to see it.
        "allow.auto.create.topics": True,
    }
    if args.fetch_wait_max_ms is not None:
        conf["fetch.wait.max.ms"] = args.fetch_wait_max_ms
    if args.queued_min_messages is not None:
        conf["queued.min.messages"] = args.queued_min_messages
    return conf


def load_client():
    """confluent_kafka, imported only when a run needs it."""
    import confluent_kafka
    return confluent_kafka


def fetch_names(client, consumer, topic, partitions):
    """The kernel's names for the threads that fetch the assigned partitions: rdk:broker<N>, N the
    node id of each one's leader. librdkafka names each broker's thread as it starts
    (rd_kafka_broker_thread_main, v2.15.1), and a broker learned from metadata has a thread of its
    own, apart from the bootstrap connection's (rd_kafka_broker_update). Where the leaders cannot
    be read, no thread is named, and the reason is in the log."""
    try:
        metadata = consumer.list_topics(topic, timeout=10)
    except client.KafkaException as exc:
        print("confluent consumer: no leaders read for --threads-out (%s)" % (exc,),
              file=sys.stderr, flush=True)
        return set()
    found = metadata.topics.get(topic)
    if found is None:
        return set()
    leaders = [found.partitions[p.partition].leader for p in partitions
               if p.partition in found.partitions]
    return set("rdk:broker%d" % leader for leader in leaders if leader >= 0)


def threads(task_dir):
    """[(tid, name)] for each thread the kernel lists for this process, in order of id. A thread
    that ends between the listing and the read of its name is left out."""
    rows = []
    for entry in sorted(os.listdir(task_dir), key=int):
        try:
            with open(os.path.join(task_dir, entry, "comm"), encoding="utf-8",
                      errors="replace") as fh:
                rows.append((int(entry), fh.read().rstrip("\n")))
        except OSError:
            pass
    return rows


def write_threads(path, poll_tid, fetching):
    """Write this process's threads to `path` by way of a file beside it, so that the kit, which
    waits for the file, never reads half a list. Where the kernel gives no list, the file holds
    its header alone and the reason is in the log. Returns how many threads were written."""
    named = dict((t.native_id, t.name) for t in threading.enumerate())
    try:
        rows = threads(TASKS)
    except OSError as exc:
        rows = []
        print("confluent consumer: no thread list to read (%s); %s holds its header alone"
              % (exc, path), file=sys.stderr, flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    partial = path + ".tmp"
    with open(partial, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(THREAD_COLUMNS)
        for tid, name in rows:
            held = (("poll", tid == poll_tid), ("fetch", name in fetching))
            w.writerow([tid, name, "+".join(role for role, on in held if on),
                        named.get(tid, "")])
    os.replace(partial, path)
    print("OK threads: %d listed -> %s" % (len(rows), path), flush=True)
    return len(rows)


def note_so_timestamps(args):
    """Where the run asked for socket timestamps, a summary saying where this client's kernel
    stamps come from instead, at the path so_timestamps.py would give the reading's summary, and
    no reading: an empty one would read as a shim that saw nothing. Returns the path, or None."""
    if not args.so_timestamps:
        return None
    path = os.path.splitext(args.so_timestamps)[0] + "_summary.json"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"client": "confluent", "kernel_stamps": "captures", "why": SO_ELSEWHERE,
                   "so_transmit": args.so_transmit, "so_journal": args.so_journal},
                  fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("OK socket timestamps: none read in this process; the kernel's stamps come from the "
          "captures -> %s" % path, flush=True)
    return path


def start_quiet(args):
    """client_quiet's switches where they mean what they say here: the collector's act on this
    process's Python objects; the counters' would sample the wrong thread, so none are taken and
    the reason goes where client_quiet puts a reason for having none."""
    quiet = client_quiet.start(argparse.Namespace(**dict(vars(args), schedstat=None)))
    if args.schedstat:
        quiet.unreadable = SCHEDSTAT_ELSEWHERE
        print("client_quiet: %s; the schedstat CSV will hold its header alone"
              % SCHEDSTAT_ELSEWHERE, file=sys.stderr, flush=True)
    return quiet


def main(argv=None):
    args = parse_args(argv)
    try:
        client = load_client()
    except ImportError:
        print("confluent-kafka is not installed; install it or use scripts/kafka_consumer.py")
        return 2
    record = thread_record.ThreadRecord() if args.thread_record else None
    polls = [] if args.read_trace else None

    # 23 Oct 2026: which build of the client ran is part of what the block reports, and the clock
    # is held to the bar every client's is held to (law_clock.py).
    print("CONFIG effective client=confluent confluent_kafka=%s librdkafka=%s "
          "fetch.wait.max.ms=%s queued.min.messages=%s clock_resolution_ns=%d"
          % (client.version()[0], client.libversion()[0],
             "default" if args.fetch_wait_max_ms is None else args.fetch_wait_max_ms,
             "default" if args.queued_min_messages is None else args.queued_min_messages,
             law_clock.demand_usable_resolution("the confluent-kafka consumer")), flush=True)

    group_id = args.group or "sb-consumer-%s" % args.run_id
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    events_path = out_path.with_name(out_path.stem + "_events.csv")

    consumer = client.Consumer(build_config(args, group_id))
    assigned = []

    def on_assign(_consumer, partitions):
        # 23 Oct 2026: confluent-kafka runs this from poll(), on this thread, and assigns the
        # partitions itself after it; the threads are listed once that poll returns.
        assigned.extend(partitions)

    consumer.subscribe([args.topic], on_assign=on_assign)
    # 23 Oct 2026: as in kafka_consumer.py, the collector goes off once the client exists and
    # before any message is received.
    quiet = start_quiet(args)
    poll_tid = threading.get_native_id()
    listed = args.threads_out is None
    timeout_s = args.poll_timeout_ms / 1000.0

    last_msg = time.monotonic()
    n = 0
    with out_path.open("w", newline="", encoding="utf-8") as f_out, events_path.open(
            "w", newline="", encoding="utf-8") as f_events:
        w = csv.DictWriter(f_out, fieldnames=CONSUMER_COLUMNS)
        w.writeheader()
        ew = csv.DictWriter(f_events, fieldnames=EVENT_COLUMNS)
        ew.writeheader()

        while True:
            t_poll_ns = now_ns() if polls is not None else None
            msg = consumer.poll(timeout_s)
            if polls is not None:
                polls.append((t_poll_ns, now_ns() - t_poll_ns,
                              0 if msg is None or msg.error() is not None else 1))
            if not listed and assigned:
                write_threads(args.threads_out, poll_tid,
                              fetch_names(client, consumer, args.topic, assigned))
                listed = True

            if msg is None or msg.error() is not None:
                if msg is not None:
                    print("confluent consumer: %s" % (msg.error(),), file=sys.stderr, flush=True)
                if (time.monotonic() - last_msg) >= args.idle_seconds:
                    break
                continue

            v = json.loads(msg.value().decode("utf-8"))
            if v.get("run_id") != args.run_id:
                continue
            last_msg = time.monotonic()

            t_consume_ns = now_ns()
            t_output_ns = now_ns()
            if record is not None:
                record.note("stamps_receive")
            w.writerow({"run_id": v.get("run_id"), "backend": "kafka", "topic": args.topic,
                        "event_id": v.get("event_id"), "match_id": v.get("match_id"),
                        "t_sim_seconds": v.get("t_sim_seconds"), "t_cons_recv_ns": t_consume_ns,
                        "t_output_ns": t_output_ns})
            ew.writerow({"run_id": v.get("run_id"), "backend": "kafka", "topic": msg.topic(),
                         "partition": msg.partition(), "offset": msg.offset(),
                         "t_consume_ns": t_consume_ns, "event_id": v.get("event_id"),
                         "match_id": v.get("match_id"), "t_sim_seconds": v.get("t_sim_seconds"),
                         "t_emit_offset_s": v.get("t_emit_offset_s"),
                         "t_emit_planned_ns": v.get("t_emit_planned_ns"),
                         "s3_uid": v.get("s3_uid"), "s3_rev": v.get("s3_rev"),
                         "s3_is_correction": v.get("s3_is_correction")})
            n += 1
            if n % 2000 == 0:
                f_events.flush()
                f_out.flush()

        if not listed:
            # 23 Oct 2026: never assigned, the list is still written, while the client's threads
            # are alive, so that the run's record holds it.
            write_threads(args.threads_out, poll_tid, set())

    consumer.close()
    note_so_timestamps(args)
    client_quiet.finish(quiet, args)
    if polls is not None:
        with out_path.with_name(out_path.stem + "_readtrace.csv").open(
                "w", newline="", encoding="utf-8") as fh:
            pw = csv.writer(fh)
            pw.writerow(["t_read_start_ns", "read_duration_ns", "n_messages"])
            pw.writerows(polls)
    if record is not None:
        record.write(thread_record.beside(out_path))
    print("OK confluent consumer: wrote %d rows -> %s" % (n, out_path))
    print("OK confluent consumer: wrote %d rows -> %s" % (n, events_path))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
