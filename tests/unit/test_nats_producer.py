"""Tests for scripts/nats_producer.py: block N's producer against the scripted NATS server of
test_nats_wire.py, no network used. The producer's reader thread runs for real; the server can hold
its acknowledgments back and send them last first, answer a publish with an error or not at all,
or say something of its own just after a publish."""
import csv
import gc
import json
import os
import socket
import sys
import threading
from pathlib import Path

import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = Path(HERE).parent.parent
sys.path.insert(0, HERE)
sys.path.insert(0, str(REPO / "scripts"))

import nats_producer as producer  # noqa: E402
import nats_wire as nw  # noqa: E402
import test_nats_wire as tw  # noqa: E402

STREAM = "SBL_r1"
COLUMNS = ["run_id", "backend", "stream", "event_id", "match_id", "t_sim_seconds",
           "t_emit_offset_s", "t_prod_sched_ns", "t_prod_send_ns", "t_broker_ack_ns",
           "stream_seq"]


def plan(tmp_path, n=3, offsets=None):
    pd.DataFrame({"event_id": ["constant-%06d" % (i + 1) for i in range(n)],
                  "match_id": [3795506] * n, "t_sim_seconds": [0] * n,
                  "t_emit_offset_s": offsets or [0.0] * n,
                  "row_idx": list(range(n))}).to_csv(tmp_path / "plan.csv", index=False)


def run(tmp_path, server=None, extra=(), n=3, offsets=None):
    """The producer run over a plan of `n` events; (the server, producer.csv's rows)."""
    server = server or tw.FakeServer()
    plan(tmp_path, n, offsets)
    producer.main(["--run-id", "r1", "--plan-csv", str(tmp_path / "plan.csv"),
                   "--out", str(tmp_path / "producer.csv"), "--stream", STREAM] + list(extra),
                  dial=server.connect)
    return server, rows(tmp_path / "producer.csv")


def rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def stored(server):
    return [json.loads(p) for p in server.streams[STREAM]["messages"]]


def corrections(payload):
    return b"__rev2" in payload


class TestPublishing:

    def test_each_publish_is_written_with_its_acknowledgments_stream_sequence(self, tmp_path,
                                                                             capsys):
        server, written = run(tmp_path)
        assert list(written[0]) == COLUMNS
        assert [(r["event_id"], r["stream_seq"]) for r in written] == [
            ("constant-000001", "1"), ("constant-000002", "2"), ("constant-000003", "3")]
        assert all(r["backend"] == "nats" and r["stream"] == STREAM for r in written)
        assert all(int(r["t_broker_ack_ns"]) >= int(r["t_prod_send_ns"]) for r in written)
        assert [m["event_id"] for m in stored(server)] == [r["event_id"] for r in written]
        assert stored(server)[0]["s3_uid"] == "3795506:constant-000001"
        said = capsys.readouterr().out
        assert "CONFIG effective client=python clock_resolution_ns=" in said
        assert ("CONFIG effective server_version=2.15.1 jetstream=1 storage=file "
                "stream=SBL_r1 subject=sbl.SBL_r1") in said
        assert "OK nats producer: wrote 3 base rows -> %s" % (tmp_path / "producer.csv") in said

    def test_each_publish_has_a_reply_subject_of_its_own_under_one_inbox(self, tmp_path):
        server, _ = run(tmp_path)
        sock = server.sockets[0]
        publishes = [f.split() for f in sock.frames if f.startswith(b"PUB sbl.SBL_r1 ")]
        replies = [words[2].decode() for words in publishes]
        inbox = sock.subs["2"][:-1]
        assert replies == [inbox + "1", inbox + "2", inbox + "3"]
        assert [f.split()[0] for f in sock.frames[:5]] == [b"CONNECT", b"PING", b"SUB", b"PUB",
                                                            b"SUB"], "the stream is made first"

    def test_acknowledgments_are_matched_by_their_reply_subjects_not_their_order(self, tmp_path):
        server, written = run(tmp_path, tw.FakeServer(hold_acks=3))
        assert [r["stream_seq"] for r in written] == ["1", "2", "3"]
        acks = [int(r["t_broker_ack_ns"]) for r in written]
        assert acks[2] <= acks[0], "the third publish's acknowledgment came first"

    def test_the_stream_is_made_on_its_subject_kept_as_asked(self, tmp_path):
        server, _ = run(tmp_path, extra=["--subject", "sbl.r1.20261023", "--storage", "memory"])
        config = server.streams[STREAM]["config"]
        assert config["subjects"] == ["sbl.r1.20261023"] and config["storage"] == "memory"

    def test_a_stream_the_consumer_made_first_is_taken_as_it_is(self, tmp_path):
        server = tw.FakeServer()
        server.create_stream(STREAM, {"subjects": ["sbl.SBL_r1"], "storage": "file",
                                      "num_replicas": 1})
        server.streams[STREAM]["messages"].append(b'{"run_id":"r0"}')
        _, written = run(tmp_path, server)
        assert [r["stream_seq"] for r in written] == ["2", "3", "4"]

    def test_an_acknowledgment_is_read_for_its_stream_sequence(self):
        assert producer.acknowledged(nw.parse_frame(tw.PUB_ACK), "sbl.r1") == 42
        with pytest.raises(nw.JetStreamError, match="no stream takes subject sbl.r1"):
            producer.acknowledged(nw.parse_frame(tw.NO_RESPONDERS), "sbl.r1")


class TestThePlan:

    def test_events_after_the_last_simulated_second_are_left_out(self, tmp_path):
        pd.DataFrame({"event_id": ["e1", "e2"], "match_id": [1, 1], "t_sim_seconds": [0, 1000],
                      "t_emit_offset_s": [0.0, 1000.0], "row_idx": [0, 1]}).to_csv(
            tmp_path / "plan.csv", index=False)
        server = tw.FakeServer()
        producer.main(["--run-id", "r1", "--plan-csv", str(tmp_path / "plan.csv"),
                       "--out", str(tmp_path / "sub" / "producer.csv"), "--max-t-sim", "10"],
                      dial=server.connect)
        assert [r["event_id"] for r in rows(tmp_path / "sub" / "producer.csv")] == ["e1"]

    def test_the_loop_waits_for_an_event_still_ahead_of_the_clock(self, tmp_path, monkeypatch):
        slept = []
        monkeypatch.setattr(producer.time, "sleep", slept.append)
        run(tmp_path, extra=["--speedup", "1.0"], n=1, offsets=[5.0])
        assert any(4.0 < s <= 5.0 for s in slept), "it waited for the event, about five seconds"

    def test_the_filler_reaches_the_wire_and_is_constant(self, tmp_path):
        server, _ = run(tmp_path, extra=["--pad-bytes", "512"], n=1)
        assert stored(server)[0]["pad"] == "x" * 512
        server, _ = run(tmp_path, n=1)
        assert "pad" not in stored(server)[0]

    def test_an_empty_plan_writes_a_header_and_publishes_nothing(self, tmp_path):
        server, written = run(tmp_path, extra=["--max-t-sim", "-1"])
        assert written == [] and (tmp_path / "producer.csv").read_text(
            encoding="utf-8").startswith("run_id,backend,stream,event_id")
        assert server.streams[STREAM]["messages"] == []


class TestCorrections:

    def test_each_kth_event_is_corrected_on_the_same_connection(self, tmp_path, capsys):
        server, written = run(tmp_path, extra=["--s3-mode", "corrections",
                                               "--corrections-every-k", "1",
                                               "--correction-delay-s", "0.0"])
        assert [r["event_id"] for r in written[3:]] == [
            "constant-000001__rev2", "constant-000002__rev2", "constant-000003__rev2"]
        assert [r["t_prod_sched_ns"] for r in written[3:]] == [r["t_prod_sched_ns"]
                                                              for r in written[:3]]
        assert sorted(int(r["stream_seq"]) for r in written) == list(range(1, 7))
        assert sum(m["s3_is_correction"] for m in stored(server)) == 3
        assert len(server.sockets) == 1
        assert "wrote 3 correction rows" in capsys.readouterr().out

    def test_a_correction_due_later_is_waited_for(self, tmp_path):
        _, written = run(tmp_path, extra=["--s3-mode", "corrections", "--corrections-every-k",
                                          "2", "--correction-delay-s", "0.05"], n=2)
        assert [r["event_id"] for r in written] == ["constant-000001", "constant-000002",
                                                    "constant-000002__rev2"]
        assert int(written[2]["t_prod_sched_ns"]) == int(written[1]["t_prod_sched_ns"]) + 50000000

    @pytest.mark.parametrize("verdict,why", [("error", "maximum messages exceeded"),
                                             ("drop", "never acknowledged")])
    def test_a_correction_refused_or_never_answered_fails_the_run(self, tmp_path, verdict, why):
        server = tw.FakeServer()
        server.verdict = lambda payload: verdict if corrections(payload) else None
        with pytest.raises(RuntimeError, match="NATS correction worker errors.*" + why):
            run(tmp_path, server, ["--s3-mode", "corrections", "--corrections-every-k", "1",
                                   "--ack-wait-s", "0.2"], n=1)

    def test_a_correction_that_cannot_be_written_fails_the_run(self, tmp_path):
        server = tw.FakeServer()
        dial = server.connect

        def failing(address, timeout):
            sock = dial(address, timeout)
            sock.fail_send = corrections
            return sock
        with pytest.raises(RuntimeError, match="BrokenPipeError"):
            plan(tmp_path, 1)
            producer.main(["--run-id", "r1", "--plan-csv", str(tmp_path / "plan.csv"),
                           "--out", str(tmp_path / "producer.csv"), "--s3-mode", "corrections",
                           "--corrections-every-k", "1", "--ack-wait-s", "0.2"], dial=failing)

    def test_baseline_mode_sends_no_corrections(self, tmp_path):
        _, written = run(tmp_path, extra=["--s3-mode", "baseline"])
        assert len(written) == 3


class TestWhatFailsARun:

    def test_a_publish_refused_aborts_the_run_rather_than_shortening_it(self, tmp_path):
        server = tw.FakeServer()
        server.verdict = lambda payload: "error" if b"constant-000002" in payload else None
        with pytest.raises(RuntimeError, match="NATS base send errors.*maximum messages"):
            run(tmp_path, server)
        assert rows(tmp_path / "producer.csv") == [], "nothing is written when a send failed"

    def test_a_publish_never_acknowledged_aborts_the_run(self, tmp_path):
        server = tw.FakeServer()
        server.verdict = lambda payload: "drop" if b"constant-000003" in payload else None
        with pytest.raises(RuntimeError, match=r"never acknowledged within 0.2 s: 1 .*000003"):
            run(tmp_path, server, ["--ack-wait-s", "0.2"])

    def test_a_connection_that_fails_under_the_reader_aborts_the_run(self, tmp_path):
        server = tw.FakeServer()
        server.after_publish = lambda s, sock: sock.feed(b"-ERR 'Maximum Payload Violation'\r\n")
        with pytest.raises(RuntimeError, match="acknowledgment reader failed.*Maximum Payload"):
            run(tmp_path, server, ["--ack-wait-s", "5"])

    def test_an_answer_to_nothing_pending_an_info_and_the_servers_ping_are_taken_in_stride(
            self, tmp_path):
        server = tw.FakeServer()
        said = []

        def aside(s, sock):
            if not said:
                stray = sock.subs["2"][:-1] + "999"
                sock.feed(b"MSG %s 2 28\r\n{\"stream\":\"SBL_r1\",\"seq\":99}\r\n"
                          % stray.encode() + tw.INFO + b"PING\r\n")
                said.append(stray)
        server.after_publish = aside
        _, written = run(tmp_path, server)
        assert [r["stream_seq"] for r in written] == ["1", "2", "3"]
        assert b"PONG\r\n" in server.sockets[0].frames, "the reader answered the PING"


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


@pytest.mark.usefixtures("collector_restored")
class TestTheSwitchesTheOtherClientsHave:

    def test_the_main_loop_stamps_the_sends_and_the_reader_the_acknowledgments(self, tmp_path):
        run(tmp_path, extra=["--thread-record"])
        record = json.loads((tmp_path / "producer_threads.json").read_text(encoding="utf-8"))
        assert record["roles"]["stamps_send"] == [threading.get_native_id()]
        assert len(record["roles"]["stamps_ack"]) == 1
        assert record["roles"]["stamps_ack"] != record["roles"]["stamps_send"]
        assert len(record["clocks"]) == 2

    def test_the_corrections_thread_is_named_too(self, tmp_path):
        run(tmp_path, extra=["--thread-record", "--s3-mode", "corrections",
                             "--corrections-every-k", "1"], n=2)
        record = json.loads((tmp_path / "producer_threads.json").read_text(encoding="utf-8"))
        assert len(record["roles"]["stamps_send"]) == 2, "the main loop and the corrections"

    def test_socket_timestamps_are_asked_for_on_the_nats_port(self, tmp_path, monkeypatch):
        import so_timestamps
        monkeypatch.setattr(socket, "socket", socket.socket)
        run(tmp_path, extra=["--so-timestamps", str(tmp_path / "producer_so.csv"),
                             "--so-transmit", "sched"])
        assert so_timestamps.TimestampingSocket._ports == (4222,)
        written = tmp_path / "producer_so.csv"
        assert written.read_text(encoding="utf-8").startswith("event_id,direction,ns")
        summary = json.loads(written.with_name("producer_so_summary.json").read_text(
            encoding="utf-8"))
        assert summary["transmit"] == "sched"

    def test_the_collector_goes_off_after_the_connection_and_before_t0(self, tmp_path,
                                                                      monkeypatch):
        order, seen = [], []
        collect, clock = gc.collect, producer.now_ns
        monkeypatch.setattr(gc, "collect", lambda *a: order.append("collect") or collect(*a))
        monkeypatch.setattr(producer, "now_ns", lambda: order.append("clock") or clock())
        server = tw.FakeServer()
        server.after_publish = lambda s, sock: seen.append(gc.isenabled())
        gc.enable()
        run(tmp_path, server, ["--gc-off", "--gc-log", str(tmp_path / "producer_gc.json")])
        assert order[:2] == ["collect", "clock"], "the collection delays no message's schedule"
        assert seen == [False, False, False]
        record = json.loads((tmp_path / "producer_gc.json").read_text(encoding="utf-8"))
        assert record["gc_off"] is True and record["collections"] == []

    def test_with_no_switch_the_run_writes_its_csv_alone(self, tmp_path, capsys):
        run(tmp_path)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["plan.csv", "producer.csv"]
        out = capsys.readouterr().out
        assert "OK collector" not in out and "OK socket timestamps" not in out


class TestTheLoopTrace:

    def test_it_has_the_kafka_traces_columns_and_is_named_for_the_run(self, tmp_path):
        run(tmp_path, extra=["--trace-loop", str(tmp_path / "traces" / "loop.csv")])
        trace = rows(tmp_path / "traces" / "loop_r1.csv")
        assert list(trace[0]) == ["event_id", "client", "t_target_ns", "t_wake_ns", "t_send_ns",
                                  "t_after_produce_ns", "wake_late_ms", "produce_ms"]
        assert len(trace) == 3 and all(t["client"] == "nats-wire" for t in trace)
        assert all(float(t["produce_ms"]) >= 0 for t in trace)
        assert not (tmp_path / "traces" / "loop.csv").exists()

    def test_an_empty_plan_still_writes_a_header(self, tmp_path):
        run(tmp_path, extra=["--trace-loop", str(tmp_path / "loop.csv"), "--max-t-sim", "-1"])
        assert (tmp_path / "loop_r1.csv").read_text(encoding="utf-8").strip() == "event_id"
