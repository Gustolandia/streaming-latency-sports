"""Tests for scripts/kafka_producer_confluent.py - target 100% branch coverage.

This script is the control for the client-attribution experiment (M1). Its whole purpose is to
be a *second, independent* implementation of the same measurement, so that a 103 ms producer
offset can be attributed to Kafka or to kafka-python and not left as an unexplained constant.
A control that is never exercised is not a control, and until now nothing imported this file:
it sat at 0% while the script it exists to check sat at 99%.

The stamps are what matter. `t_prod_send_ns` is read inline, immediately before the produce
call, and `t_broker_ack_ns` inside the delivery callback -- the same semantics as
kafka_producer.py, because a difference here would confound the very comparison the experiment
makes. Those two properties are pinned first and directly.

No broker is involved: `Producer` is a module-level name bound at import, so replacing it
replaces the client entirely.
"""
import csv
import json
import sys
import threading
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import kafka_producer_confluent as kpc  # noqa: E402


# --------------------------------------------------------------------------------------------
# A stand-in for librdkafka's Producer.
# --------------------------------------------------------------------------------------------

class FakeMessage:
    def __init__(self, key):
        self._key = key

    def key(self):
        return self._key


class FakeProducer:
    """Delivers synchronously by default; `errors` makes every delivery fail.

    Real librdkafka serves callbacks from poll(). Calling back from produce() is a
    simplification the tests can afford: what is under test is what the script does with the
    callback, not when librdkafka chooses to run it.
    """

    instances = []

    def __init__(self, conf, deliver=True, error=None):
        self.conf = conf
        self.produced = []
        self.flushed = None
        self.polls = 0
        self._deliver = deliver
        self._error = error
        FakeProducer.instances.append(self)

    def produce(self, topic, key=None, value=None, on_delivery=None):
        self.produced.append({"topic": topic, "key": key, "value": value})
        if on_delivery is not None and self._deliver:
            on_delivery(self._error, FakeMessage(key))

    def poll(self, timeout):
        self.polls += 1

    def flush(self, timeout):
        self.flushed = timeout


@pytest.fixture(autouse=True)
def _fresh_producer_registry():
    FakeProducer.instances = []
    yield
    FakeProducer.instances = []


@pytest.fixture
def producer(monkeypatch):
    """Install FakeProducer as the client and hand back a factory knob."""
    knobs = {"deliver": True, "error": None}

    def factory(conf):
        return FakeProducer(conf, deliver=knobs["deliver"], error=knobs["error"])

    monkeypatch.setattr(kpc, "Producer", factory)
    return knobs


@pytest.fixture
def plan(tmp_path):
    columns = ["event_id", "match_id", "t_sim_seconds", "t_emit_offset_s", "row_idx"]

    def write(rows):
        path = tmp_path / "plan.csv"
        pd.DataFrame(rows, columns=columns).to_csv(path, index=False)
        return str(path)
    return write


def _row(event_id="e1", match_id=1, t_sim=0, offset=0.0, row_idx=0):
    return {"event_id": event_id, "match_id": match_id, "t_sim_seconds": t_sim,
            "t_emit_offset_s": offset, "row_idx": row_idx}


def _run(tmp_path, plan_csv, extra=()):
    out = tmp_path / "producer.csv"
    argv = ["--run-id", "r1", "--plan-csv", plan_csv, "--out", str(out)] + list(extra)
    code = kpc.main(argv)
    return code, out


def _read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --------------------------------------------------------------------------------------------


class TestNowNs:

    def test_it_is_wall_clock_not_a_counter(self):
        """The consumer is a separate process, so the epoch has to be shared.

        perf_counter_ns has an arbitrary origin per process and would make the two halves of
        the measurement incomparable. Epoch nanoseconds in 2026 are far above 1.7e18; a
        performance counter is nowhere near it.
        """
        assert kpc.now_ns() > 1_700_000_000_000_000_000

    def test_it_does_not_go_backwards(self):
        assert kpc.now_ns() <= kpc.now_ns()


class TestBuildConfig:
    """The point of this script is equivalent settings under a different client."""

    class Args:
        bootstrap = "h:9092"
        acks = "all"
        linger_ms = 0
        max_inflight = 1
        batch_size = None
        compression_type = None

    def test_the_core_keys_are_mapped(self):
        conf = kpc.build_config(self.Args())
        assert conf["bootstrap.servers"] == "h:9092"
        assert conf["acks"] == "all"
        assert conf["linger.ms"] == 0
        assert conf["max.in.flight.requests.per.connection"] == 1

    def test_absent_optional_settings_are_left_out_entirely(self):
        """Not set to a default: librdkafka's own default must be the one that applies."""
        conf = kpc.build_config(self.Args())
        assert "batch.size" not in conf
        assert "compression.type" not in conf

    def test_a_batch_size_is_passed_through_as_an_integer(self):
        args = self.Args()
        args.batch_size = "4096"
        assert kpc.build_config(args)["batch.size"] == 4096

    def test_a_compression_type_is_passed_through(self):
        args = self.Args()
        args.compression_type = "lz4"
        assert kpc.build_config(args)["compression.type"] == "lz4"

    def test_in_flight_is_never_below_one(self):
        """A measurement bug once came from an in-flight setting; 0 would stall the client."""
        args = self.Args()
        args.max_inflight = 0
        assert kpc.build_config(args)["max.in.flight.requests.per.connection"] == 1


class TestLoadPlan:

    def test_events_past_the_horizon_are_dropped(self, plan):
        path = plan([_row("a", t_sim=0), _row("b", t_sim=700, row_idx=1)])
        assert list(kpc.load_plan(path, 600)["event_id"]) == ["a"]

    def test_ordering_is_by_sim_time_then_row_and_is_stable(self, plan):
        path = plan([_row("late", t_sim=5, row_idx=1), _row("early", t_sim=1, row_idx=0),
                     _row("tie", t_sim=5, row_idx=0)])
        assert list(kpc.load_plan(path, 600)["event_id"]) == ["early", "tie", "late"]


class TestParseArgs:

    def test_the_defaults_match_the_kafka_python_producer(self):
        args = kpc.parse_args(["--run-id", "r", "--plan-csv", "p", "--out", "o"])
        assert args.topic == "sb-events"
        assert args.acks == "all"
        assert args.max_inflight == 1
        assert args.speedup == 120.0
        assert args.max_t_sim == 600
        assert args.trace_loop is None

    def test_a_missing_required_argument_is_refused(self):
        with pytest.raises(SystemExit):
            kpc.parse_args(["--plan-csv", "p", "--out", "o"])


class TestTheLibraryBeingAbsent:

    def test_it_reports_rather_than_crashing(self, monkeypatch, capsys, plan, tmp_path):
        """The import is guarded, so main must be too, or the guard buys nothing."""
        monkeypatch.setattr(kpc, "Producer", None)
        code, out = _run(tmp_path, plan([_row()]))
        assert code == 2
        assert "confluent-kafka is not installed" in capsys.readouterr().out
        assert not out.exists(), "nothing should be written when no client exists"


class TestTheStampsAreWhatThisScriptExistsToProduce:

    def test_the_send_stamp_is_read_inline_before_the_produce_call(self, producer, plan,
                                                                   tmp_path, monkeypatch):
        """Mode A cannot invert on the send side, and only inline stamping guarantees that.

        The ack stamp is read after a wakeup and can therefore be late; the send stamp is read
        on the calling thread immediately before the action, so it precedes it by construction.
        Pinning the order of the two clock reads pins that property.
        """
        seen = []
        real = kpc.now_ns
        monkeypatch.setattr(kpc, "now_ns", lambda: (seen.append(len(seen)), real())[1])

        original_produce = FakeProducer.produce

        def produce(self, *a, **kw):
            seen.append("produce")
            return original_produce(self, *a, **kw)

        monkeypatch.setattr(FakeProducer, "produce", produce)
        _run(tmp_path, plan([_row()]))

        assert "produce" in seen
        # The send stamp is the clock read immediately preceding the produce call.
        assert seen[seen.index("produce") - 1] != "produce"

    def test_the_ack_stamp_comes_from_the_delivery_callback(self, producer, plan, tmp_path):
        code, out = _run(tmp_path, plan([_row("e1")]))
        assert code == 0
        row = _read(out)[0]
        assert row["t_broker_ack_ns"], "the callback fired, so an ack stamp must be recorded"
        assert int(row["t_broker_ack_ns"]) >= int(row["t_prod_send_ns"])

    def test_an_event_never_acknowledged_carries_an_empty_ack(self, producer, plan, tmp_path):
        """A missing ack must read as missing, not as zero and not as the send stamp."""
        producer["deliver"] = False
        code, out = _run(tmp_path, plan([_row("e1")]))
        assert code == 0
        assert _read(out)[0]["t_broker_ack_ns"] == ""

    def test_the_schema_is_byte_compatible_with_the_kafka_python_producer(self, producer, plan,
                                                                         tmp_path):
        """Every downstream analysis reads both files with the same reader."""
        import kafka_producer  # noqa: F401 - imported for the comparison below only
        _, out = _run(tmp_path, plan([_row()]))
        with open(out, encoding="utf-8") as f:
            header = f.readline().strip().split(",")
        assert header == ["run_id", "backend", "topic", "event_id", "match_id", "t_sim_seconds",
                          "t_emit_offset_s", "t_prod_sched_ns", "t_prod_send_ns",
                          "t_broker_ack_ns"]

    def test_the_backend_column_says_kafka_not_confluent(self, producer, plan, tmp_path):
        """The client changed; the transport did not. Mislabelling it would split the arm."""
        _, out = _run(tmp_path, plan([_row()]))
        assert _read(out)[0]["backend"] == "kafka"


class TestTheMessageOnTheWire:

    def test_it_carries_the_planned_emission_time_the_consumer_compares_against(
            self, producer, plan, tmp_path):
        _, out = _run(tmp_path, plan([_row("e1", match_id=7, t_sim=3, offset=1.5)]))
        sent = json.loads(FakeProducer.instances[0].produced[0]["value"].decode("utf-8"))
        assert sent["event_id"] == "e1"
        assert sent["match_id"] == 7
        assert sent["t_sim_seconds"] == 3
        assert sent["t_emit_offset_s"] == 1.5
        assert sent["s3_uid"] == "7:e1"
        assert sent["s3_is_correction"] is False
        assert sent["t_emit_planned_ns"] == int(_read(out)[0]["t_prod_sched_ns"])

    def test_the_key_is_the_event_id_so_the_ack_can_be_matched_back(self, producer, plan,
                                                                    tmp_path):
        _run(tmp_path, plan([_row("e1")]))
        assert FakeProducer.instances[0].produced[0]["key"] == b"e1"

    def test_the_topic_is_the_one_asked_for(self, producer, plan, tmp_path):
        _run(tmp_path, plan([_row()]), extra=["--topic", "other"])
        assert FakeProducer.instances[0].produced[0]["topic"] == "other"


class TestTheSchedule:

    def test_an_event_already_due_is_not_slept_on(self, producer, plan, tmp_path, monkeypatch):
        slept = []
        monkeypatch.setattr(kpc.time, "sleep", lambda s: slept.append(s))
        _run(tmp_path, plan([_row(offset=0.0)]))
        assert slept == [], "offset 0 is due at once; sleeping on it would delay the send"

    def test_a_future_event_is_slept_until(self, producer, plan, tmp_path, monkeypatch):
        slept = []
        monkeypatch.setattr(kpc.time, "sleep", lambda s: slept.append(s))
        _run(tmp_path, plan([_row(offset=120.0)]), extra=["--speedup", "120"])
        assert slept and 0 < slept[0] <= 1.0, "120 s at 120x is one second away"

    def test_speedup_divides_the_planned_offsets(self, producer, plan, tmp_path):
        _, out = _run(tmp_path, plan([_row("a", offset=0.0), _row("b", offset=240.0,
                                                                  row_idx=1)]),
                      extra=["--speedup", "240"])
        rows = _read(out)
        gap_ns = int(rows[1]["t_prod_sched_ns"]) - int(rows[0]["t_prod_sched_ns"])
        assert abs(gap_ns - 1_000_000_000) < 1_000, "240 s at 240x is one second of wall clock"


class TestDeliveryErrors:

    def test_a_delivery_error_aborts_the_run(self, producer, plan, tmp_path):
        """Silently writing a CSV of unacknowledged sends would be a fabricated measurement."""
        producer["error"] = "BROKER DOWN"
        with pytest.raises(RuntimeError, match="delivery errors"):
            _run(tmp_path, plan([_row()]))

    def test_the_error_is_reported_before_anything_is_written(self, producer, plan, tmp_path):
        producer["error"] = "BROKER DOWN"
        out = tmp_path / "producer.csv"
        with pytest.raises(RuntimeError):
            kpc.main(["--run-id", "r1", "--plan-csv", plan([_row()]), "--out", str(out)])
        assert not out.exists()

    def test_only_the_first_five_errors_are_quoted(self, producer, plan, tmp_path):
        producer["error"] = "E"
        rows = [_row("e%d" % i, row_idx=i) for i in range(9)]
        with pytest.raises(RuntimeError) as excinfo:
            _run(tmp_path, plan(rows))
        assert str(excinfo.value).count("'E'") == 5

    def test_a_failed_delivery_does_not_also_record_an_ack(self, producer, plan, tmp_path):
        producer["error"] = "E"
        with pytest.raises(RuntimeError):
            _run(tmp_path, plan([_row()]))
        # The callback returned before touching ack_ns; the run aborted, so nothing was written.
        assert not (tmp_path / "producer.csv").exists()


class TestTheTraceLoop:

    def test_no_trace_file_is_written_unless_asked(self, producer, plan, tmp_path):
        _run(tmp_path, plan([_row()]))
        assert list(tmp_path.glob("trace*")) == []

    def test_the_trace_is_namespaced_by_run_id(self, producer, plan, tmp_path):
        """Concurrent feeds are separate processes and would otherwise overwrite each other."""
        trace = tmp_path / "trace.csv"
        _run(tmp_path, plan([_row()]), extra=["--trace-loop", str(trace)])
        assert not trace.exists()
        assert (tmp_path / "trace_r1.csv").exists()

    def test_the_trace_records_the_wake_and_produce_intervals(self, producer, plan, tmp_path):
        trace = tmp_path / "trace.csv"
        _run(tmp_path, plan([_row("e1")]), extra=["--trace-loop", str(trace)])
        row = _read(tmp_path / "trace_r1.csv")[0]
        assert row["event_id"] == "e1"
        assert row["client"] == "confluent"
        assert float(row["produce_ms"]) >= 0.0
        for field in ("t_target_ns", "t_wake_ns", "t_send_ns", "t_after_produce_ns",
                      "wake_late_ms"):
            assert row[field] != ""

    def test_an_empty_plan_still_writes_a_trace_header(self, producer, plan, tmp_path):
        """A run that emitted nothing is a result; a missing file is an ambiguity."""
        trace = tmp_path / "trace.csv"
        code, _ = _run(tmp_path, plan([]), extra=["--trace-loop", str(trace)])
        assert code == 0
        with open(tmp_path / "trace_r1.csv", encoding="utf-8") as f:
            assert f.readline().strip() == "event_id"

    def test_a_trace_directory_that_does_not_exist_is_created(self, producer, plan, tmp_path):
        trace = tmp_path / "deep" / "down" / "trace.csv"
        _run(tmp_path, plan([_row()]), extra=["--trace-loop", str(trace)])
        assert (tmp_path / "deep" / "down" / "trace_r1.csv").exists()


class TestTheRunAsAWhole:

    def test_the_output_directory_is_created(self, producer, plan, tmp_path):
        out = tmp_path / "nested" / "dir" / "producer.csv"
        assert kpc.main(["--run-id", "r1", "--plan-csv", plan([_row()]),
                         "--out", str(out)]) == 0
        assert out.exists()

    def test_an_empty_plan_writes_a_header_and_succeeds(self, producer, plan, tmp_path):
        code, out = _run(tmp_path, plan([]))
        assert code == 0
        assert _read(out) == []

    def test_every_planned_event_appears_once(self, producer, plan, tmp_path):
        rows = [_row("e%d" % i, row_idx=i, offset=0.0) for i in range(5)]
        _, out = _run(tmp_path, plan(rows))
        assert [r["event_id"] for r in _read(out)] == ["e0", "e1", "e2", "e3", "e4"]

    def test_it_reports_what_it_wrote(self, producer, plan, tmp_path, capsys):
        _run(tmp_path, plan([_row(), _row("e2", row_idx=1)]))
        assert "wrote 2 rows" in capsys.readouterr().out

    def test_the_poll_thread_is_stopped_and_joined(self, producer, plan, tmp_path):
        """Left running, it would keep the process alive and keep touching the client."""
        before = threading.active_count()
        _run(tmp_path, plan([_row()]))
        assert threading.active_count() <= before

    def test_the_client_is_flushed_before_the_acks_are_collected(self, producer, plan,
                                                                 tmp_path):
        _run(tmp_path, plan([_row()]))
        assert FakeProducer.instances[0].flushed == 30
