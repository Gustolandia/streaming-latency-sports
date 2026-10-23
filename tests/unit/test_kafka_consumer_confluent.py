"""Tests for scripts/kafka_consumer_confluent.py - 100% branch coverage.

The block this consumer is built for runs Kafka's own consumers beside the project's, and reads the
latency from the captures on the client's host. So what has to hold here is that the files are
kafka_consumer.py's files, column for column; that each message is identified by the partition and
offset the library hands back, with the payload's run_id deciding only whether it is this run's;
and that the thread list the kit sets a thread's policy from names the thread that fetches.

confluent-kafka is not installed here, and the script imports it only when a run starts, so a
module put in sys.modules stands in for it, as FakeProducer stands in for librdkafka's producer in
test_kafka_producer_confluent.py.
"""
import ast
import csv
import gc
import json
import os
import re
import socket
import sys
import threading
import types
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import kafka_consumer_confluent as kcc  # noqa: E402

TOPIC = "sb-events-r1"
#: A poll that runs the rebalance callback, as librdkafka does inside poll(), and returns nothing.
ASSIGN = object()


# --------------------------------------------------------------------------------------------
# A stand-in for confluent_kafka.
# --------------------------------------------------------------------------------------------

class FakeError(object):
    def __init__(self, text):
        self.text = text

    def __str__(self):
        return self.text


class FakeMessage(object):
    def __init__(self, payload=None, error=None, topic=TOPIC, partition=0, offset=0):
        self._value = (None if payload is None
                       else json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        self._error = error
        self._topic = topic
        self._partition = partition
        self._offset = offset

    def error(self):
        return self._error

    def value(self):
        return self._value

    def topic(self):
        return self._topic

    def partition(self):
        return self._partition

    def offset(self):
        return self._offset


class FakeTopicPartition(object):
    def __init__(self, topic, partition):
        self.topic = topic
        self.partition = partition


class FakeKafkaException(Exception):
    pass


class World(object):
    """What the fake library will do: one script entry per poll, then empty polls."""

    def __init__(self):
        self.script = []
        self.partitions = [FakeTopicPartition(TOPIC, 0)]
        self.metadata = metadata({0: 1})
        self.metadata_error = None
        self.consumers = []
        self.at_poll = []
        self.watch = None


class FakeConsumer(object):

    def __init__(self, conf, world):
        self.conf = conf
        self.world = world
        self.subscribed = None
        self.on_assign = None
        self.timeouts = []
        self.metadata_asked = []
        self.closed = False
        self.gc_when_made = gc.isenabled()
        world.consumers.append(self)

    def subscribe(self, topics, on_assign=None):
        self.subscribed = topics
        self.on_assign = on_assign

    def poll(self, timeout):
        self.timeouts.append(timeout)
        watch = self.world.watch
        self.world.at_poll.append((gc.isenabled(), os.path.exists(watch) if watch else None))
        step = self.world.script.pop(0) if self.world.script else None
        if step is ASSIGN:
            self.on_assign(self, list(self.world.partitions))
            return None
        return step

    def list_topics(self, topic, timeout=None):
        self.metadata_asked.append((topic, timeout))
        if self.world.metadata_error is not None:
            raise FakeKafkaException(self.world.metadata_error)
        return self.world.metadata

    def close(self):
        self.closed = True


def metadata(leaders, topic=TOPIC):
    """ClusterMetadata's shape: topics by name, each with its partitions' leaders."""
    partitions = dict((p, types.SimpleNamespace(leader=leader)) for p, leader in leaders.items())
    return types.SimpleNamespace(topics={topic: types.SimpleNamespace(partitions=partitions)})


@pytest.fixture
def world(monkeypatch):
    found = World()
    module = types.ModuleType("confluent_kafka")
    module.Consumer = lambda conf: FakeConsumer(conf, found)
    module.KafkaException = FakeKafkaException
    module.version = lambda: ("2.15.1", 0x020f0100)
    module.libversion = lambda: ("2.15.1", 0x020f01ff)
    monkeypatch.setitem(sys.modules, "confluent_kafka", module)
    return found


@pytest.fixture
def collector_restored():
    """--gc-off switches this process's collector off and freezes every object in it, and the rest
    of the suite runs here too: whatever a test does, the collector is put back as it was."""
    enabled, callbacks = gc.isenabled(), list(gc.callbacks)
    try:
        yield
    finally:
        gc.callbacks[:] = callbacks
        gc.unfreeze()
        if enabled:
            gc.enable()


def payload(event_id="constant-000001", run_id="r1", **extra):
    value = {"run_id": run_id, "match_id": 900000, "event_id": event_id, "t_sim_seconds": 5,
             "t_emit_offset_s": 0.02, "t_emit_planned_ns": 1761200000000000000,
             "s3_uid": "900000:" + event_id, "s3_rev": 1, "s3_is_correction": False}
    value.update(extra)
    return value


def run(tmp_path, extra=(), idle="0"):
    out = tmp_path / "consumer.csv"
    code = kcc.main(["--run-id", "r1", "--out", str(out), "--idle-seconds", idle,
                     "--topic", TOPIC] + list(extra))
    return code, out


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def tasks(tmp_path, names):
    """A stand-in for /proc/self/task: a directory per thread id with its name in comm; a name of
    None is a thread that ended before its name was read."""
    root = tmp_path / "task"
    for tid, name in names.items():
        (root / str(tid)).mkdir(parents=True)
        if name is not None:
            (root / str(tid) / "comm").write_bytes(name.encode("utf-8") + b"\n")
    return root


def kafka_consumer_fieldnames(which):
    """The `which`-th csv fieldnames list in scripts/kafka_consumer.py, read from its source as
    test_two_clients_write_the_same_files.py reads them."""
    source = (SCRIPTS_DIR / "kafka_consumer.py").read_text(encoding="utf-8")
    start = [m.start() for m in re.finditer(r"fieldnames=\[", source)][which]
    return re.findall(r'"([^"]+)"', source[start:source.index("]", start)])


# --------------------------------------------------------------------------------------------


class TestNowNs:

    def test_it_is_the_wall_clock_the_producer_stamps_with(self):
        assert kcc.now_ns() > 1_700_000_000_000_000_000


class TestParseArgs:

    def test_the_defaults_are_kafka_consumers(self):
        args = kcc.parse_args(["--run-id", "r", "--out", "o"])
        assert (args.topic, args.bootstrap, args.idle_seconds, args.poll_timeout_ms) \
            == ("sb-events", "localhost:9092", 15, 1000)
        assert args.group is None and args.threads_out is None
        assert args.fetch_wait_max_ms is None and args.queued_min_messages is None

    def test_a_missing_required_argument_is_refused(self):
        with pytest.raises(SystemExit):
            kcc.parse_args(["--out", "o"])

    def test_the_switches_the_kit_hands_kafka_consumer_are_taken(self):
        """One command line in the kit serves both consumers."""
        args = kcc.parse_args(["--run-id", "r", "--out", "o", "--broker-count", "3",
                               "--so-timestamps", "s.csv", "--so-transmit", "sched",
                               "--so-journal", "j", "--gc-off", "--gc-log", "g.json",
                               "--schedstat", "s.csv", "--thread-record", "--read-trace"])
        assert args.broker_count == 3 and args.so_transmit == "sched" and args.gc_off


class TestBuildConfig:

    def args(self, extra=()):
        return kcc.parse_args(["--run-id", "r", "--out", "o", "--bootstrap", "h:9092"]
                              + list(extra))

    def test_a_group_of_its_own_from_the_earliest_offset_on_the_classic_protocol(self):
        conf = kcc.build_config(self.args(), "g1")
        assert conf == {"bootstrap.servers": "h:9092", "group.id": "g1",
                        "group.protocol": "classic", "auto.offset.reset": "earliest",
                        "allow.auto.create.topics": True}

    def test_fetching_is_left_at_librdkafkas_defaults_unless_asked(self):
        conf = kcc.build_config(self.args(), "g1")
        assert "fetch.wait.max.ms" not in conf and "queued.min.messages" not in conf

    def test_the_two_fetch_settings_pass_through_when_asked(self):
        conf = kcc.build_config(self.args(["--fetch-wait-max-ms", "5",
                                           "--queued-min-messages", "10"]), "g1")
        assert conf["fetch.wait.max.ms"] == 5 and conf["queued.min.messages"] == 10


class TestTheClientIsImportedWhenARunStarts:

    def test_importing_the_script_does_not_import_the_library(self):
        tree = ast.parse((SCRIPTS_DIR / "kafka_consumer_confluent.py").read_text(
            encoding="utf-8"))
        top = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        names = [alias.name for node in top if isinstance(node, ast.Import)
                 for alias in node.names]
        names += [node.module for node in top if isinstance(node, ast.ImportFrom)]
        assert "confluent_kafka" not in names

    def test_a_run_imports_it(self, world):
        assert kcc.load_client() is sys.modules["confluent_kafka"]

    def test_without_it_the_run_says_so_and_writes_nothing(self, monkeypatch, tmp_path,
                                                            capsys):
        monkeypatch.setitem(sys.modules, "confluent_kafka", None)
        code, out = run(tmp_path)
        assert code == 2
        assert "confluent-kafka is not installed" in capsys.readouterr().out
        assert not out.exists()


class TestTheFilesAreKafkaConsumersFiles:

    def test_the_columns_are_kafka_consumers_column_for_column(self, world, tmp_path):
        assert kcc.CONSUMER_COLUMNS == kafka_consumer_fieldnames(0)
        assert kcc.EVENT_COLUMNS == kafka_consumer_fieldnames(1)
        world.script = [FakeMessage(payload())]
        _, out = run(tmp_path)
        assert list(read(out)[0]) == kafka_consumer_fieldnames(0)
        assert list(read(tmp_path / "consumer_events.csv")[0]) == kafka_consumer_fieldnames(1)

    def test_a_message_of_this_run_is_written_to_both(self, world, tmp_path):
        world.script = [FakeMessage(payload(), partition=0, offset=41)]
        _, out = run(tmp_path)
        row = read(out)[0]
        assert (row["run_id"], row["backend"], row["topic"], row["event_id"], row["match_id"],
                row["t_sim_seconds"]) == ("r1", "kafka", TOPIC, "constant-000001", "900000", "5")
        event = read(tmp_path / "consumer_events.csv")[0]
        assert (event["partition"], event["offset"], event["topic"]) == ("0", "41", TOPIC)
        assert (event["t_emit_offset_s"], event["t_emit_planned_ns"], event["s3_uid"],
                event["s3_rev"]) == ("0.02", "1761200000000000000", "900000:constant-000001",
                                     "1")

    def test_values_are_written_as_kafka_consumers_csv_writer_writes_them(self, world,
                                                                          tmp_path):
        """json.loads makes false a Python False, and the csv writer writes it so; an absent
        field is an empty cell."""
        message = payload()
        del message["s3_uid"]
        world.script = [FakeMessage(message)]
        run(tmp_path)
        event = read(tmp_path / "consumer_events.csv")[0]
        assert event["s3_is_correction"] == "False" and event["s3_uid"] == ""

    def test_the_receive_stamp_is_one_reading_under_two_names(self, world, tmp_path):
        world.script = [FakeMessage(payload())]
        _, out = run(tmp_path)
        row, event = read(out)[0], read(tmp_path / "consumer_events.csv")[0]
        assert row["t_cons_recv_ns"] == event["t_consume_ns"]
        assert int(row["t_output_ns"]) >= int(row["t_cons_recv_ns"]) > 1_700_000_000 * 10 ** 9

    def test_another_runs_messages_and_those_with_no_run_id_are_skipped(self, world, tmp_path):
        no_run = payload("constant-000003")
        del no_run["run_id"]
        world.script = [FakeMessage(payload("constant-000002", run_id="r0"), offset=1),
                        FakeMessage(no_run, offset=2), FakeMessage(payload(), offset=3)]
        _, out = run(tmp_path)
        assert [r["event_id"] for r in read(out)] == ["constant-000001"]
        assert [r["offset"] for r in read(tmp_path / "consumer_events.csv")] == ["3"]

    def test_a_message_is_told_apart_by_its_partition_and_offset_not_its_event_id(
            self, world, tmp_path):
        """Two messages carrying one event id are two messages: the broker's ids tell them
        apart, and the payload's event_id is only copied into its column."""
        world.script = [FakeMessage(payload(), partition=0, offset=7),
                        FakeMessage(payload(), partition=1, offset=7)]
        run(tmp_path)
        events = read(tmp_path / "consumer_events.csv")
        assert [(e["partition"], e["offset"], e["event_id"]) for e in events] \
            == [("0", "7", "constant-000001"), ("1", "7", "constant-000001")]

    def test_the_output_directory_is_made(self, world, tmp_path):
        out = tmp_path / "nested" / "run" / "consumer.csv"
        assert kcc.main(["--run-id", "r1", "--out", str(out), "--idle-seconds", "0"]) == 0
        assert out.exists() and (out.parent / "consumer_events.csv").exists()

    def test_it_says_what_it_wrote_and_which_build_ran(self, world, tmp_path, capsys):
        world.script = [FakeMessage(payload()), FakeMessage(payload("constant-000002"))]
        _, out = run(tmp_path)
        said = capsys.readouterr().out
        assert "OK confluent consumer: wrote 2 rows -> %s" % out in said
        assert "OK confluent consumer: wrote 2 rows -> %s" % (tmp_path / "consumer_events.csv") \
            in said
        config = [line for line in said.splitlines() if line.startswith("CONFIG effective")][0]
        assert "client=confluent confluent_kafka=2.15.1 librdkafka=2.15.1" in config
        assert "fetch.wait.max.ms=default queued.min.messages=default" in config
        assert re.search(r"clock_resolution_ns=\d+$", config)

    def test_the_config_line_names_the_fetch_settings_asked_for(self, world, tmp_path, capsys):
        run(tmp_path, ["--fetch-wait-max-ms", "5", "--queued-min-messages", "10"])
        assert "fetch.wait.max.ms=5 queued.min.messages=10" in capsys.readouterr().out
        assert world.consumers[0].conf["fetch.wait.max.ms"] == 5

    def test_a_group_of_its_own_unless_one_is_named(self, world, tmp_path):
        run(tmp_path)
        run(tmp_path, ["--group", "mine"])
        assert [c.conf["group.id"] for c in world.consumers] == ["sb-consumer-r1", "mine"]


class TestThePollLoop:

    def test_it_subscribes_to_the_topic_polls_in_seconds_and_closes(self, world, tmp_path):
        run(tmp_path, ["--poll-timeout-ms", "50"])
        consumer = world.consumers[0]
        assert consumer.subscribed == [TOPIC] and callable(consumer.on_assign)
        assert consumer.timeouts == [0.05] and consumer.closed

    def test_an_empty_poll_before_the_idle_time_polls_again(self, world, tmp_path):
        with patch("kafka_consumer_confluent.time.monotonic", side_effect=[100.0, 100.5, 110.0]):
            run(tmp_path, idle="10")
        assert len(world.consumers[0].timeouts) == 2

    def test_an_error_is_logged_not_written_and_waited_on_like_an_empty_poll(
            self, world, tmp_path, capsys):
        world.script = [FakeMessage(error=FakeError("Broker: Unknown topic or partition")),
                        FakeMessage(payload())]
        with patch("kafka_consumer_confluent.time.monotonic",
                   side_effect=[100.0, 100.5, 101.0, 111.0]):
            _, out = run(tmp_path, idle="10")
        assert "confluent consumer: Broker: Unknown topic or partition" in capsys.readouterr().err
        assert [r["event_id"] for r in read(out)] == ["constant-000001"]

    def test_the_files_are_flushed_every_2000_messages(self, world, tmp_path):
        world.script = [FakeMessage(payload("constant-%06d" % i), offset=i) for i in range(2000)]
        _, out = run(tmp_path)
        assert len(read(out)) == 2000


class TestTheThreadList:
    """--threads-out: the kit sets one thread's policy from it, by the thread's kernel id, once the
    thread exists."""

    @pytest.fixture
    def threads(self, tmp_path, monkeypatch):
        """The poll thread, librdkafka's main thread, the bootstrap connection's thread, broker 1's
        thread, and one that ends before its name is read."""
        me = threading.get_native_id()
        root = tasks(tmp_path, {me: "python3", 900001: "rdk:main", 900002: "rdk:broker-1",
                                900003: "rdk:broker1", 900004: None})
        monkeypatch.setattr(kcc, "TASKS", str(root))
        return me

    def test_once_assigned_every_thread_is_listed_with_the_fetching_one_named(
            self, world, tmp_path, threads, capsys):
        world.script = [ASSIGN]
        run(tmp_path, ["--threads-out", str(tmp_path / "consumer_tids.csv")])
        rows = read(tmp_path / "consumer_tids.csv")
        assert list(rows[0]) == ["tid", "name", "role", "runtime_name"]
        # In order of id, the thread that ended before its name was read left out.
        assert [(int(r["tid"]), r["name"], r["role"]) for r in rows] == sorted([
            (threads, "python3", "poll"), (900001, "rdk:main", ""),
            (900002, "rdk:broker-1", ""), (900003, "rdk:broker1", "fetch")])
        poll = [r for r in rows if r["role"] == "poll"][0]
        assert poll["runtime_name"] == threading.current_thread().name
        assert [r["runtime_name"] for r in rows if r["role"] != "poll"] == ["", "", ""]
        assert capsys.readouterr().out.count("OK threads: 4 listed") == 1
        assert world.consumers[0].metadata_asked == [(TOPIC, 10)]

    def test_the_list_is_there_before_the_next_poll_and_written_once(self, world, tmp_path,
                                                                     threads):
        path = tmp_path / "consumer_tids.csv"
        world.watch = str(path)
        world.script = [None, ASSIGN, FakeMessage(payload()), FakeMessage(payload())]
        with patch("kafka_consumer_confluent.time.monotonic",
                   side_effect=[100.0, 100.5] + [101.0] * 3 + [200.0]):
            run(tmp_path, ["--threads-out", str(path)], idle="10")
        assert [seen for _, seen in world.at_poll] == [False, False, True, True, True]
        assert not os.path.exists(str(path) + ".tmp")

    def test_a_leader_on_each_of_two_brokers_names_both_threads(self, world, tmp_path,
                                                                threads, monkeypatch):
        root = tasks(tmp_path / "three", {900011: "rdk:broker1", 900012: "rdk:broker2",
                                          900013: "rdk:broker3"})
        monkeypatch.setattr(kcc, "TASKS", str(root))
        world.partitions = [FakeTopicPartition(TOPIC, 0), FakeTopicPartition(TOPIC, 1)]
        world.metadata = metadata({0: 2, 1: 3, 2: 1})
        world.script = [ASSIGN]
        run(tmp_path, ["--threads-out", str(tmp_path / "t.csv")])
        assert [r["role"] for r in read(tmp_path / "t.csv")] == ["", "fetch", "fetch"]

    @pytest.mark.parametrize("found", [
        metadata({0: -1}),                       # no leader yet
        metadata({1: 1}),                        # the assigned partition is not in it
        metadata({0: 1}, topic="another-topic"),  # the topic is not in it
    ], ids=["no-leader", "no-partition", "no-topic"])
    def test_where_no_leader_is_read_no_thread_is_named_fetch(self, world, tmp_path, threads,
                                                              found):
        world.metadata = found
        world.script = [ASSIGN]
        run(tmp_path, ["--threads-out", str(tmp_path / "t.csv")])
        assert "fetch" not in [r["role"] for r in read(tmp_path / "t.csv")]

    def test_metadata_that_cannot_be_read_does_not_stop_the_run(self, world, tmp_path, threads,
                                                                 capsys):
        world.metadata_error = "Local: Timed out"
        world.script = [ASSIGN, FakeMessage(payload())]
        with patch("kafka_consumer_confluent.time.monotonic",
                   side_effect=[100.0, 100.5, 101.0, 200.0]):
            code, out = run(tmp_path, ["--threads-out", str(tmp_path / "t.csv")], idle="10")
        assert code == 0 and len(read(out)) == 1
        assert "no leaders read for --threads-out (Local: Timed out)" in capsys.readouterr().err
        assert [r["role"] for r in read(tmp_path / "t.csv") if r["role"]] == ["poll"]

    def test_a_thread_that_both_polls_and_fetches_carries_both_roles(self, world, tmp_path,
                                                                    monkeypatch):
        """The three consumers share the vocabulary; Kafka's Java consumer fetches on its poll
        thread, and its row reads poll+fetch."""
        root = tasks(tmp_path, {threading.get_native_id(): "rdk:broker1"})
        monkeypatch.setattr(kcc, "TASKS", str(root))
        world.script = [ASSIGN]
        run(tmp_path, ["--threads-out", str(tmp_path / "t.csv")])
        assert read(tmp_path / "t.csv")[0]["role"] == "poll+fetch"

    def test_never_assigned_the_list_is_written_at_the_end(self, world, tmp_path, threads):
        run(tmp_path, ["--threads-out", str(tmp_path / "t.csv")])
        rows = read(tmp_path / "t.csv")
        assert len(rows) == 4 and "fetch" not in [r["role"] for r in rows]
        assert world.consumers[0].metadata_asked == []

    def test_where_the_kernel_lists_no_threads_the_file_holds_its_header(
            self, world, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(kcc, "TASKS", str(tmp_path / "no-proc-here"))
        world.script = [ASSIGN]
        run(tmp_path, ["--threads-out", str(tmp_path / "deep" / "t.csv")])
        with open(tmp_path / "deep" / "t.csv", encoding="utf-8") as fh:
            assert fh.read() == "tid,name,role,runtime_name\n"
        assert "no thread list to read" in capsys.readouterr().err

    def test_nothing_is_listed_unless_asked(self, world, tmp_path, threads):
        world.script = [ASSIGN]
        run(tmp_path)
        assert world.consumers[0].metadata_asked == []
        assert sorted(p.name for p in tmp_path.iterdir()) == ["consumer.csv",
                                                              "consumer_events.csv", "task"]


class TestTheSocketTimestampSwitches:
    """librdkafka's sockets are opened in C, where the shim's socket class never reaches."""

    def test_they_are_taken_nothing_is_read_and_the_summary_says_where_the_stamps_come_from(
            self, world, tmp_path, capsys):
        before = socket.socket
        run(tmp_path, ["--so-timestamps", str(tmp_path / "consumer_so.csv"),
                       "--so-transmit", "sched", "--so-journal", str(tmp_path / "journal")])
        assert socket.socket is before, "the shim must not be put in"
        assert not (tmp_path / "consumer_so.csv").exists()
        summary = json.loads((tmp_path / "consumer_so_summary.json").read_text(encoding="utf-8"))
        assert summary == {"client": "confluent", "kernel_stamps": "captures",
                           "why": kcc.SO_ELSEWHERE, "so_transmit": "sched",
                           "so_journal": str(tmp_path / "journal")}
        assert "the kernel's stamps come from the captures" in capsys.readouterr().out

    def test_unasked_there_is_no_summary(self, world, tmp_path):
        run(tmp_path)
        assert not list(tmp_path.glob("*_summary.json"))


@pytest.mark.usefixtures("collector_restored")
class TestTheCollectorSwitches:

    def test_the_collector_goes_off_after_the_consumer_is_made_and_before_the_first_poll(
            self, world, tmp_path):
        gc.enable()
        world.script = [FakeMessage(payload())]
        run(tmp_path, ["--gc-off", "--gc-log", str(tmp_path / "consumer_gc.json")])
        assert world.consumers[0].gc_when_made is True
        assert [enabled for enabled, _ in world.at_poll] == [False, False]
        record = json.loads((tmp_path / "consumer_gc.json").read_text(encoding="utf-8"))
        assert record["gc_off"] is True and record["schedstat_unreadable"] is None

    def test_the_counters_are_not_sampled_from_the_wrong_thread(self, world, tmp_path, capsys):
        run(tmp_path, ["--schedstat", str(tmp_path / "consumer_schedstat.csv"),
                       "--gc-log", str(tmp_path / "consumer_gc.json")])
        with open(tmp_path / "consumer_schedstat.csv", encoding="utf-8") as fh:
            assert fh.read() == "t_ns,exec_ns,delay_ns,slices\n"
        record = json.loads((tmp_path / "consumer_gc.json").read_text(encoding="utf-8"))
        assert record["schedstat_unreadable"] == kcc.SCHEDSTAT_ELSEWHERE
        assert kcc.SCHEDSTAT_ELSEWHERE in capsys.readouterr().err

    def test_with_no_switch_the_collector_is_left_alone(self, world, tmp_path, capsys):
        gc.enable()
        world.script = [FakeMessage(payload())]
        run(tmp_path)
        assert [enabled for enabled, _ in world.at_poll] == [True, True]
        said = capsys.readouterr()
        assert "OK collector" not in said.out and "client_quiet" not in said.err


class TestTheTraceAndTheThreadRecord:

    def test_every_poll_is_traced_with_what_it_brought(self, world, tmp_path):
        world.script = [FakeMessage(payload()), FakeMessage(error=FakeError("x"))]
        with patch("kafka_consumer_confluent.time.monotonic",
                   side_effect=[100.0, 100.0, 100.5, 200.0]):
            run(tmp_path, ["--read-trace"], idle="10")
        rows = read(tmp_path / "consumer_readtrace.csv")
        assert list(rows[0]) == ["t_read_start_ns", "read_duration_ns", "n_messages"]
        assert [int(r["n_messages"]) for r in rows] == [1, 0, 0]
        assert all(int(r["read_duration_ns"]) >= 0 for r in rows)

    def test_the_thread_that_stamps_arrivals_is_recorded(self, world, tmp_path):
        world.script = [FakeMessage(payload())]
        run(tmp_path, ["--thread-record"])
        record = json.loads((tmp_path / "consumer_threads.json").read_text(encoding="utf-8"))
        assert record["roles"] == {"stamps_receive": [threading.get_native_id()]}

    def test_neither_is_written_unless_asked(self, world, tmp_path):
        world.script = [FakeMessage(payload())]
        run(tmp_path)
        assert not (tmp_path / "consumer_readtrace.csv").exists()
        assert not (tmp_path / "consumer_threads.json").exists()
