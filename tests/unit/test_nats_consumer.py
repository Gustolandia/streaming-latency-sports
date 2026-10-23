"""Tests for scripts/nats_consumer.py: block N's pull consumer against the scripted NATS server of
test_nats_wire.py, no network used. The server stands in for nats-server with JetStream, and writes
what nats-server writes: each message under the stream's subject, to the oldest request waiting, and
each status under its request's reply subject. Its events are what happens while the consumer waits
(messages published, requests expiring, PINGs); the consumer's clock is the server's, so that time
passes only while a read waits, as it does for a client whose reads block; and its log says in what
order the requests and the acknowledgments reached it. The consumer probes its receive connection
every 0.1 s unless told otherwise, so the probes run through every test. The last classes run the
consumer through the socket-timestamp shim, with the kernel stood in for, and run
scripts/run_nats_trial.sh with stand-ins for the clients."""
import csv
import gc
import itertools
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = Path(HERE).parent.parent
sys.path.insert(0, HERE)
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import nats_consumer as nc  # noqa: E402
import nats_wire as nw  # noqa: E402
import so_timestamps as so  # noqa: E402
import test_nats_wire as tw  # noqa: E402
from posix_shell import bash  # noqa: E402

RUN = "r1"
STREAM = "SBL_r1"


def message(i, run_id=RUN):
    """The producer's i-th message, as nats_producer.py writes it."""
    return json.dumps({"run_id": run_id, "match_id": 3795506, "event_id": "constant-%06d" % i,
                       "t_sim_seconds": i, "t_emit_offset_s": float(i),
                       "t_emit_planned_ns": tw.T0 + i, "s3_uid": "3795506:constant-%06d" % i,
                       "s3_rev": 1, "s3_is_correction": False},
                      separators=(",", ":")).encode()


def publish(*numbers, run_id=RUN):
    """An event: messages published to the stream while the consumer waits."""
    return lambda server: server.store(STREAM, *[message(i, run_id) for i in numbers])


def run(tmp_path, *events, server=None, extra=(), dial=None):
    """The consumer run to its idle stop on the server's clock; (the server, the output folder)."""
    server = server or tw.FakeServer()
    server.events.extend(events)
    nc.main(["--run-id", RUN, "--out", str(tmp_path / "consumer.csv"), "--stream", STREAM,
             "--idle-seconds", "1"] + list(extra), dial=dial or server.connect,
            clock=server.clock)
    return server, tmp_path


def frames_of(data):
    """The whole frames in `data`, cut as a reader of a capture cuts them."""
    found, at = [], 0
    while at < len(data):
        n = nw.frame_length(data, at)
        found.append(data[at:at + n])
        at += n
    return found


def probes_sent(sock):
    """The probes a connection carried: its PINGs, but for the one sent with its CONNECT."""
    return sock.frames.count(nw.PING) - 1


def rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def kinds(server):
    """The requests and the acknowledgments, in the order the server had them."""
    return [kind for kind, _ in server.seen if kind in ("request", "ack")]


class TestAFewMessages:

    def test_they_are_written_with_their_stream_sequences_and_acknowledged(self, tmp_path, capsys):
        server, out = run(tmp_path, publish(1, 2, 3))
        written = rows(out / "consumer.csv")
        assert list(written[0]) == ["run_id", "backend", "stream", "event_id", "match_id",
                                    "t_sim_seconds", "t_cons_recv_ns", "t_output_ns", "stream_seq"]
        assert [(r["event_id"], r["stream_seq"]) for r in written] == [
            ("constant-000001", "1"), ("constant-000002", "2"), ("constant-000003", "3")]
        assert all(r["backend"] == "nats" and r["stream"] == STREAM for r in written)
        assert all(int(r["t_output_ns"]) >= int(r["t_cons_recv_ns"]) for r in written)
        events = rows(out / "consumer_events.csv")
        assert list(events[0]) == ["run_id", "backend", "stream", "stream_seq", "t_consume_ns",
                                   "event_id", "match_id", "t_sim_seconds", "t_emit_offset_s",
                                   "t_emit_planned_ns", "s3_uid", "s3_rev", "s3_is_correction"]
        assert [e["t_consume_ns"] for e in events] == [r["t_cons_recv_ns"] for r in written]
        assert events[2]["s3_uid"] == "3795506:constant-000003"
        said = capsys.readouterr().out
        assert "OK nats consumer: wrote 3 rows -> %s" % (out / "consumer.csv") in said
        assert "OK nats consumer: wrote 3 rows -> %s" % (out / "consumer_events.csv") in said
        assert "OK nats consumer: 4 pull requests sent, 0 ended without a message" in said
        assert ("CONFIG effective depth=1 expires_ms=30000 one_reply_reads=0 probe_ms=100 "
                "max_waiting=512 max_ack_pending=1000000 storage=file") in said
        assert "server_version=2.15.1 client=python clock_resolution_ns=" in said

    def test_each_replacement_goes_out_before_the_message_is_handled(self, tmp_path):
        server, _ = run(tmp_path, publish(1, 2, 3))
        assert kinds(server) == ["request", "request", "ack", "request", "ack", "request", "ack"]
        assert len(server.waiting(STREAM)) == 1, "one request still waiting at the end"

    def test_the_requests_and_the_messages_share_one_connection_and_the_acks_go_on_another(
            self, tmp_path):
        server, _ = run(tmp_path, publish(1, 2))
        receive, acks = server.sockets
        pulls = [f for f in receive.frames if f.startswith(b"PUB ")]
        assert len(pulls) == 3 and all(
            f.startswith(b"PUB $JS.API.CONSUMER.MSG.NEXT.SBL_r1.sbl-r1 _INBOX.") for f in pulls)
        assert all(f.endswith(b' 33\r\n{"batch":1,"expires":30000000000}\r\n') for f in pulls)
        ops = [f.split()[0] for f in receive.frames]
        assert ops[:4] == [b"CONNECT", b"PING", b"SUB", b"PUB"]
        assert [op for op in ops[4:] if op != b"PING"] == [b"PUB", b"PUB"], "and the probes"
        assert probes_sent(receive) > 0 and probes_sent(acks) == 0
        assert [s for s, _, _ in server.acks] == [acks, acks]
        assert all(f.endswith(b" 4\r\n+ACK\r\n") for f in acks.frames if b"$JS.ACK." in f)
        assert not [f for f in receive.frames if b"+ACK" in f]
        # Each request has a reply subject of its own: the message that answers it names it.
        replies = [f.split()[2] for f in pulls]
        assert len(set(replies)) == 3 and replies[0].endswith(b".1") and replies[2].endswith(b".3")

    def test_the_stream_and_the_durable_consumer_are_made_on_the_second_connection(
            self, tmp_path):
        server, _ = run(tmp_path, publish(1), extra=["--storage", "memory"])
        config = server.streams[STREAM]["config"]
        assert config["subjects"] == ["sbl.SBL_r1"] and config["storage"] == "memory"
        consumer = server.streams[STREAM]["consumers"]["sbl-r1"]["config"]
        assert consumer["ack_policy"] == "explicit" and consumer["deliver_policy"] == "all"
        assert consumer["max_waiting"] >= 128
        receive, acks = server.sockets
        assert [f for f in acks.frames if b"$JS.API.STREAM.CREATE" in f]
        assert not [f for f in receive.frames if b"$JS.API.STREAM" in f
                    or b"$JS.API.CONSUMER.CREATE" in f]

    def test_names_given_are_used_and_a_run_ids_own_are_made_safe(self, tmp_path):
        server = tw.FakeServer()
        server.events.append(lambda s: s.store("SBL_x", message(1, "law q1.7")))
        nc.main(["--run-id", "law q1.7", "--out", str(tmp_path / "c.csv"), "--stream", "SBL_x",
                 "--subject", "sbl.x.20261023", "--idle-seconds", "1"],
                dial=server.connect, clock=server.clock)
        assert b"MSG sbl.x.20261023 2 $JS.ACK.SBL_x.sbl-law_q1_7." in server.sockets[0].history
        assert list(server.streams["SBL_x"]["consumers"]) == ["sbl-law_q1_7"]
        assert server.streams["SBL_x"]["config"]["subjects"] == ["sbl.x.20261023"]
        assert rows(tmp_path / "c.csv")[0]["run_id"] == "law q1.7"
        server = tw.FakeServer()
        nc.main(["--run-id", RUN, "--out", str(tmp_path / "d.csv"), "--durable", "mine",
                 "--idle-seconds", "1"], dial=server.connect, clock=server.clock)
        assert list(server.streams["SBL_EVENTS"]["consumers"]) == ["mine"]

    def test_a_message_delivered_with_headers_of_its_own_is_a_message(self, tmp_path):
        def with_headers(server):
            consumer = server.streams[STREAM]["consumers"]["sbl-r1"]
            reply = consumer["waiting"].pop(0)
            block = b"NATS/1.0\r\nNats-Msg-Id: constant-000009\r\n\r\n"
            body = block + message(9)
            sock, sid = server.route(reply)
            # On the requests' subscription but under the stream's subject, as nats-server writes.
            sock.feed(b"HMSG sbl.SBL_r1 %s $JS.ACK.SBL_r1.sbl-r1.1.9.1.17.0 %d %d\r\n%s\r\n"
                      % (sid.encode(), len(block), len(body), body))
        server, out = run(tmp_path, with_headers)
        assert [(r["event_id"], r["stream_seq"]) for r in rows(out / "consumer.csv")] == [
            ("constant-000009", "9")]


class TestWhatIsNotWritten:

    def test_another_runs_message_is_acknowledged_and_not_written(self, tmp_path):
        server, out = run(tmp_path, publish(1, run_id="r0"), publish(2))
        assert [r["event_id"] for r in rows(out / "consumer.csv")] == ["constant-000002"]
        assert len(server.acks) == 2

    def test_a_message_delivered_again_is_acknowledged_and_not_written_again(self, tmp_path,
                                                                             capsys):
        server, out = run(tmp_path, publish(1, 2), lambda s: s.redeliver(STREAM, 1))
        assert [r["stream_seq"] for r in rows(out / "consumer.csv")] == ["1", "2"]
        assert len(server.acks) == 3
        assert "1 redeliveries not written" in capsys.readouterr().out


class TestTheDepth:

    def test_sixty_four_requests_wait_and_each_answer_is_replaced(self, tmp_path):
        server, out = run(tmp_path, publish(*range(1, 101)), extra=["--depth", "64"])
        assert [r["stream_seq"] for r in rows(out / "consumer.csv")] == [
            str(i) for i in range(1, 101)]
        assert len(server.requests) == 64 + 100
        assert len(server.waiting(STREAM)) == 64, "as many waiting at the end as at the start"
        assert kinds(server)[:65] == ["request"] * 65, "the first answer replaced before acked"

    @pytest.mark.parametrize("depth", ["0", "-1"])
    def test_a_depth_below_one_is_refused(self, tmp_path, depth):
        with pytest.raises(SystemExit):
            run(tmp_path, extra=["--depth", depth])

    @pytest.mark.parametrize("depth,limit", [(1, 512), (256, 1024)])
    def test_max_waiting_is_four_times_the_depth_and_never_below_512(self, tmp_path, capsys,
                                                                     depth, limit):
        server, out = run(tmp_path, publish(1, 2, 3), extra=["--depth", str(depth)])
        assert server.streams[STREAM]["consumers"]["sbl-r1"]["config"]["max_waiting"] == limit
        said = capsys.readouterr().out
        assert "CONFIG effective depth=%d " % depth in said and " max_waiting=%d " % limit in said
        assert len(server.waiting(STREAM)) == depth and len(rows(out / "consumer.csv")) == 3

    def test_a_max_waiting_below_the_depth_would_refuse_a_request_and_stop_the_run(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(nw, "max_waiting_for", lambda depth: depth - 1)
        with pytest.raises(RuntimeError, match="refused or ended a pull request: 409 Exceeded"):
            run(tmp_path, extra=["--depth", "3"])


class TestRequestsThatEndWithoutAMessage:

    @pytest.mark.parametrize("code,description", [(408, "Request Timeout"), (404, "No Messages"),
                                                  (409, "Leadership Change")])
    def test_one_that_ends_is_replaced_before_anything_else(self, tmp_path, capsys, code,
                                                            description):
        server, _ = run(tmp_path, lambda s: s.end_requests(STREAM, 1, code, description),
                        publish(1), extra=["--depth", "2"])
        assert kinds(server) == ["request", "request", "request", "request", "ack"]
        assert len(server.waiting(STREAM)) == 2
        assert ("1 ended without a message and replaced [(%d, 1)]" % code
                in capsys.readouterr().out)

    def test_a_heartbeat_ends_nothing(self, tmp_path):
        server, _ = run(tmp_path, lambda s: s.end_requests(STREAM, 1, 100, "Idle Heartbeat",
                                                           ends=False), extra=["--depth", "2"])
        assert len(server.requests) == 2 and len(server.waiting(STREAM)) == 2

    @pytest.mark.parametrize("code,description", [(409, "Exceeded MaxWaiting"), (503, "")])
    def test_a_request_refused_stops_the_run(self, tmp_path, code, description):
        with pytest.raises(RuntimeError, match="refused or ended a pull request: %d" % code):
            run(tmp_path, lambda s: s.end_requests(STREAM, 1, code, description))


class TestWhichRequestAMessageAnswered:
    """A message comes under the stream's subject and names no request: it answered the oldest
    request waiting, the order nats-server serves them in. A status names the request it ends."""

    def test_messages_and_statuses_come_as_nats_server_writes_them(self, tmp_path, capsys):
        server, out = run(tmp_path, publish(1), lambda s: s.end_requests(STREAM, 1),
                          extra=["--depth", "2"])
        receive = server.sockets[0]
        frames = [nw.parse_frame(f) for f in frames_of(receive.history)]
        replies = [f.split()[2].decode() for f in receive.frames
                   if f.startswith(b"PUB $JS.API.CONSUMER.MSG.NEXT.")]
        messages = [f for f in frames if nw.is_delivery(f, nc.PULL_SID)]
        statuses = [f for f in frames if f.op == "HMSG" and f.reply is None]
        assert [(f.subject, f.sid) for f in messages] == [("sbl.SBL_r1", "2")]
        assert [f.subject for f in statuses] == [replies[1]], "under request 2's reply subject"
        assert len(rows(out / "consumer.csv")) == 1 and len(server.waiting(STREAM)) == 2
        assert "1 ended without a message and replaced [(408, 1)]" in capsys.readouterr().out

    def test_a_message_answers_the_oldest_request_waiting(self, tmp_path, capsys):
        # Request 1 has the message; requests 2 and 3, the one sent in 1's place, then expire,
        # each found waiting; and request 4, sent in 2's place, has the next message.
        server, out = run(tmp_path, publish(1), lambda s: s.end_requests(STREAM, 2), publish(2),
                          extra=["--depth", "2"])
        assert [r["stream_seq"] for r in rows(out / "consumer.csv")] == ["1", "2"]
        assert "6 pull requests sent, 2 ended without a message and replaced [(408, 2)]" in (
            capsys.readouterr().out)
        assert server.waiting(STREAM) == server.requests[-2:]

    def test_a_status_ends_the_request_it_names_and_not_the_oldest(self, tmp_path, capsys):
        # Request 2 expires before request 1, and then request 1 does.
        server, out = run(tmp_path, lambda s: s.end_requests(STREAM, 1, at=1),
                          lambda s: s.end_requests(STREAM, 1), publish(1), extra=["--depth", "3"])
        assert "2 ended without a message and replaced [(408, 2)]" in capsys.readouterr().out
        assert len(rows(out / "consumer.csv")) == 1 and len(server.waiting(STREAM)) == 3

    def test_a_status_for_a_request_a_message_had_answered_stops_the_run(self, tmp_path):
        # A server that is not nats-server gives the message to the newest request; then the
        # oldest expires, the request the consumer took the message to have answered.
        with pytest.raises(RuntimeError, match="408 Request Timeout for pull request 1, which "
                                               "was not waiting"):
            run(tmp_path, publish(1), lambda s: s.end_requests(STREAM, 1),
                server=tw.FakeServer(newest_first=True), extra=["--depth", "2"])


class TestTheServersHousekeeping:

    def test_pings_are_answered_on_both_connections(self, tmp_path):
        server, _ = run(tmp_path, lambda s: s.sockets[0].feed(b"PING\r\n"),
                        lambda s: s.sockets[1].feed(b"PING\r\n"))
        receive, acks = server.sockets
        assert receive.frames.count(b"PONG\r\n") == 1 and acks.frames[-1] == b"PONG\r\n"
        assert [a for a in acks.attempts if a[1] == nw.MSG_DONTWAIT], (
            "the acknowledgments' connection is read without waiting")

    def test_an_err_on_the_acknowledgments_connection_stops_the_run(self, tmp_path):
        with pytest.raises(nw.ServerError, match="Stale Connection"):
            run(tmp_path, lambda s: s.sockets[1].feed(b"-ERR 'Stale Connection'\r\n"))

    def test_frames_that_are_not_the_requests_are_passed_over(self, tmp_path):
        server, out = run(tmp_path, lambda s: s.sockets[0].feed(tw.INFO + b"PONG\r\n"),
                          publish(1))
        assert len(rows(out / "consumer.csv")) == 1
        assert len(server.requests) == 2, "neither answered a request"

    def test_the_stream_is_deleted_when_asked(self, tmp_path, capsys):
        server, _ = run(tmp_path, publish(1), extra=["--delete-stream"])
        assert STREAM not in server.streams
        assert ", stream deleted" in capsys.readouterr().out


class TestOneReplyReads:

    def test_each_read_of_the_receive_connection_takes_one_frame(self, tmp_path, capsys):
        server = tw.FakeServer(coalesce=True)
        server, out = run(tmp_path, publish(1, 2, 3, 4), server=server,
                          extra=["--depth", "4", "--one-reply-reads"])
        receive = server.sockets[0]
        frames = frames_of(receive.history)
        assert receive.taken() == [len(f) for f in frames], "one read for each frame, PONGs too"
        ops = [nw.parse_frame(f).op for f in frames]
        assert ops[:7] == ["INFO", "PONG", "MSG", "MSG", "MSG", "MSG", "PONG"], (
            "the probe's PONG behind the four messages the server had sent before it")
        first, past, _ns = receive.packets[2]
        assert sum(len(f) for f in frames[2:6]) == past - first, "the four came in one packet"
        assert ops.count("MSG") == 4 and ops.count("PONG") == 1 + probes_sent(receive)
        assert len(rows(out / "consumer.csv")) == 4
        assert "one_reply_reads=1" in capsys.readouterr().out

    def test_the_read_trace_has_a_row_for_each_read(self, tmp_path):
        server, out = run(tmp_path, publish(1, 2), extra=["--one-reply-reads"])
        trace = rows(out / "consumer_readtrace.csv")
        assert list(trace[0]) == ["t_read_start_ns", "read_duration_ns", "n_messages"]
        assert sum(int(r["n_messages"]) for r in trace) == 2
        assert all(int(r["read_duration_ns"]) >= 0 for r in trace)


class TestTheProbes:
    """A PING on the receive connection every --probe-ms, and each PONG read: a PONG is neither a
    message nor a status, answers no request, and never comes between a message and the request
    sent in its place."""

    def test_one_goes_out_at_each_interval_and_each_pong_is_read(self, tmp_path, capsys):
        server, _ = run(tmp_path)
        receive, acks = server.sockets
        assert (socket.SOL_SOCKET, socket.SO_RCVTIMEO, nw.timeval(0.1)) in receive.options, (
            "a read of the receive connection waits at most one interval")
        assert probes_sent(receive) == 9, "one for each 0.1 s waited, up to the idle stop at 1 s"
        assert probes_sent(acks) == 0, "the acknowledgments' connection is not probed"
        said = capsys.readouterr().out
        assert " probe_ms=100 " in said
        assert "OK nats consumer: 9 probes sent on the receive connection, 9 PONGs read" in said

    def test_a_longer_interval_leaves_a_reads_wait_at_a_quarter_second(self, tmp_path, capsys):
        server, _ = run(tmp_path, extra=["--probe-ms", "400", "--idle-seconds", "2"])
        receive = server.sockets[0]
        assert (socket.SOL_SOCKET, socket.SO_RCVTIMEO, nw.timeval(nw.WAIT_S)) in receive.options
        assert probes_sent(receive) == 3, "at 0.5, 1.0 and 1.5 s, each at the end of a read's wait"
        assert "3 probes sent on the receive connection, 3 PONGs read" in capsys.readouterr().out

    def test_none_go_out_at_zero(self, tmp_path, capsys):
        server, out = run(tmp_path, publish(1), extra=["--probe-ms", "0"])
        receive = server.sockets[0]
        assert probes_sent(receive) == 0 and len(rows(out / "consumer.csv")) == 1
        assert (socket.SOL_SOCKET, socket.SO_RCVTIMEO, nw.timeval(nw.WAIT_S)) in receive.options
        said = capsys.readouterr().out
        assert " probe_ms=0 " in said
        assert "0 probes sent on the receive connection, 0 PONGs read" in said

    def test_a_negative_interval_is_refused(self, tmp_path):
        with pytest.raises(SystemExit):
            run(tmp_path, extra=["--probe-ms", "-1"])

    def test_a_pong_answers_no_request_and_is_no_message(self, tmp_path, capsys):
        server, out = run(tmp_path, publish(1, 2), publish(3), publish(4, 5),
                          extra=["--depth", "2"])
        receive = server.sockets[0]
        ops = [nw.parse_frame(f).op for f in frames_of(receive.history)]
        probes = probes_sent(receive)
        assert probes >= 3 and ops.count("PONG") == 1 + probes and ops.count("MSG") == 5
        assert len(server.requests) == 2 + 5, "one replacement for each message, none for a PONG"
        assert len(server.waiting(STREAM)) == 2
        assert [r["stream_seq"] for r in rows(out / "consumer.csv")] == ["1", "2", "3", "4", "5"]
        assert sum(int(r["n_messages"]) for r in rows(out / "consumer_readtrace.csv")) == 5
        said = capsys.readouterr().out
        assert "OK nats consumer: 7 pull requests sent, 0 ended" in said
        assert "%d probes sent on the receive connection, %d PONGs read" % (probes, probes) in said

    def test_a_probe_never_goes_out_between_a_message_and_its_replacement(self, tmp_path,
                                                                          monkeypatch):
        server = tw.FakeServer()
        steps = []
        next_frame, write = nw.Link.next_frame, nw.Link.write

        def reading(link):
            frame = next_frame(link)
            if frame is not None and link.sock is server.sockets[0]:
                steps.append("message" if nw.is_delivery(frame, nc.PULL_SID) else frame.op)
            return frame

        def writing(link, data):
            if link.sock is server.sockets[0]:
                steps.append("request" if data.startswith(b"PUB $JS.API.CONSUMER.MSG.NEXT.")
                             else data.split()[0].decode())
            write(link, data)
        monkeypatch.setattr(nw.Link, "next_frame", reading)
        monkeypatch.setattr(nw.Link, "write", writing)
        run(tmp_path, publish(1, 2, 3), publish(4), server=server, extra=["--depth", "2"])
        after = [steps[i + 1] for i, step in enumerate(steps) if step == "message"]
        assert after == ["request"] * 4, "each message's replacement went out first"
        assert ["message", "request", "PING"] in [steps[i:i + 3] for i in range(len(steps))], (
            "a probe fell due as a message came, and went out after the message's replacement")


class TestFlushing:

    def test_the_files_are_flushed_every_two_thousand_messages(self, tmp_path):
        server, out = run(tmp_path, publish(*range(1, 2001)), extra=["--depth", "64"])
        assert len(rows(out / "consumer.csv")) == 2000


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


def _seek_and_read(fd, size, offset):
    """os.pread where the system has none (Windows): a seek and a read do the same here."""
    os.lseek(fd, offset, os.SEEK_SET)
    return os.read(fd, size)


@pytest.mark.usefixtures("collector_restored")
class TestTheSwitchesTheOtherClientsHave:

    def test_the_thread_that_stamps_arrivals_is_named_when_asked(self, tmp_path):
        run(tmp_path, publish(1), extra=["--thread-record"])
        record = json.loads((tmp_path / "consumer_threads.json").read_text(encoding="utf-8"))
        assert record["roles"] == {"stamps_receive": [threading.get_native_id()]}

    def test_the_collector_goes_off_after_the_connections_and_before_the_first_request(
            self, tmp_path):
        seen = []
        server = tw.FakeServer()
        server.on_request = lambda reply: seen.append(gc.isenabled())
        gc.enable()
        run(tmp_path, publish(1, 2), server=server,
            extra=["--gc-off", "--gc-log", str(tmp_path / "consumer_gc.json")])
        assert seen == [False, False, False]
        record = json.loads((tmp_path / "consumer_gc.json").read_text(encoding="utf-8"))
        assert record["gc_off"] is True and record["collections"] == []

    def test_the_counters_are_sampled_just_before_each_request(self, tmp_path, monkeypatch):
        import client_quiet
        order = []
        counters = tmp_path / "schedstat"
        counters.write_bytes(b"1000 200 3\n")
        monkeypatch.setattr(client_quiet, "SCHEDSTAT", str(counters))
        pread = getattr(os, "pread", _seek_and_read)
        monkeypatch.setattr(os, "pread", lambda *a: order.append("sample") or pread(*a),
                            raising=False)
        server = tw.FakeServer()
        server.on_request = lambda reply: order.append("request")
        run(tmp_path, publish(1), server=server,
            extra=["--schedstat", str(tmp_path / "consumer_schedstat.csv")])
        assert order == ["sample", "request", "sample", "request"]
        assert len(rows(tmp_path / "consumer_schedstat.csv")) == 2

    def test_with_no_switch_nothing_else_is_written(self, tmp_path, capsys):
        run(tmp_path, publish(1))
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "consumer.csv", "consumer_events.csv", "consumer_readtrace.csv"]
        out = capsys.readouterr().out
        assert "OK collector" not in out and "OK socket timestamps" not in out


# --- through the socket-timestamp shim ----------------------------------------------------------

def queue_entry(ns, key):
    """A transmit timestamp on the error queue, as test_so_timestamps.py writes one."""
    return (b"", [(socket.SOL_SOCKET, so.SCM_TIMESTAMPING, tw.stamp(ns)),
                  (so.SOL_IP, so.IP_RECVERR,
                   so.EXTENDED_ERR.pack(42, so.SO_EE_ORIGIN_TIMESTAMPING, 0, 0, 0, 0, key)
                   + bytes(16))], so.MSG_ERRQUEUE, None)


@pytest.fixture
def shimmed(monkeypatch):
    """A dial whose sockets are the shim's own TimestampingSocket, with each call the shim makes
    into the kernel answered by a FakeSocket: the bytes, and an error queue that takes a transmit
    timestamp after every send, as SO_TIMESTAMPING fills it."""
    monkeypatch.setattr(socket, "socket", socket.socket)
    server = tw.FakeServer(coalesce=True)

    def dial(address, timeout):
        kernel = server.connect(address, timeout)
        kernel.errors, kernel.number, kernel.sent = [], len(server.sockets), 0
        sock = so.TimestampingSocket(socket.AF_INET, socket.SOCK_STREAM)
        sock._kernel = kernel
        sock.setsockopt = kernel.setsockopt
        return sock

    def sendall(sock, data, flags):
        kernel = sock._kernel
        kernel.sendall(data)
        kernel.sent += len(data)
        kernel.sends = getattr(kernel, "sends", 0) + 1
        kernel.errors.append(queue_entry(server.ns, kernel.sent - 1))

    def recvmsg(sock, bufsize, ancbufsize, flags):
        if flags & so.MSG_ERRQUEUE:
            return sock._kernel.errors.pop(0)
        return sock._kernel.recvmsg(bufsize, ancbufsize, flags)

    monkeypatch.setattr(so, "_getpeername", lambda sock: ("10.1.1.21", 4222))
    monkeypatch.setattr(so, "_getsockname", lambda sock: ("10.1.1.10", 40000 + sock._kernel.number))
    monkeypatch.setattr(so, "_setsockopt", lambda sock, flags: None)
    monkeypatch.setattr(so, "_sendall", sendall)
    monkeypatch.setattr(so, "_recv", lambda sock, n, flags: sock._kernel.recv(n, flags))
    monkeypatch.setattr(so, "_recvmsg", recvmsg)
    monkeypatch.setattr(so, "_queued", lambda sock: bool(sock._kernel.errors))
    monkeypatch.setattr(so, "_close", lambda sock: (sock._kernel.close(), so._BASE.close(sock)))
    return server, dial


class TestOneReplyReadsThroughTheShim:
    """The shim passes a peek through untouched and journals the read that takes the bytes, with
    that read's own receive timestamp; so with --one-reply-reads each row of the journal's reads is
    exactly one frame, timed by the packet that brought its last byte."""

    def test_each_journaled_read_is_one_frame_timed_by_the_packet_of_its_last_byte(
            self, tmp_path, shimmed):
        server, dial = shimmed
        stem = tmp_path / "consumer_journal"

        def split_one(s):
            s.split_next = 150
            s.store(STREAM, message(5))
        run(tmp_path, publish(1, 2, 3, 4), split_one, server=server, dial=dial,
            extra=["--depth", "4", "--one-reply-reads", "--so-timestamps",
                   str(tmp_path / "consumer_so.csv"), "--so-journal", str(stem)])
        receive, acks = server.sockets
        inbound = (tmp_path / "consumer_journal_conn0_in.bin").read_bytes()
        assert inbound == receive.history, "every byte the connection read, each once"
        frames = frames_of(inbound)
        ends = list(itertools.accumulate(len(f) for f in frames))
        with open(tmp_path / "consumer_journal_reads.csv", newline="", encoding="utf-8") as fh:
            reads = [r for r in csv.DictReader(fh) if r["conn"] == "0"]
        assert [int(r["end"]) for r in reads] == ends, "one read, one frame, and none peeked"
        ops = [nw.parse_frame(f).op for f in frames]
        messages = [i for i, op in enumerate(ops) if op == "MSG"]
        pongs = [i for i, op in enumerate(ops) if op == "PONG"][1:]
        assert ops[:2] == ["INFO", "PONG"] and len(messages) == 5, "INFO, PONG, the five messages"
        assert pongs and len(pongs) == len(ops) - 7, "and the probes' PONGs, each a read of its own"

        def packet_of(offset):
            return [ns for first, past, ns in receive.packets if first <= offset < past][0]
        assert [int(r["ns"]) for r in reads] == [packet_of(end - 1) for end in ends]
        burst = [int(reads[i]["ns"]) for i in messages[:4]]
        assert len(set(burst)) == 1, "four messages in one packet share its timestamp"
        fifth = messages[4]
        split = [first for first, past, ns in receive.packets if ns == int(reads[fifth]["ns"])][0]
        assert split == ends[fifth - 1] + 150, "the fifth is timed by the second of its packets"
        outbound = (tmp_path / "consumer_journal_conn0_out.bin").read_bytes()
        assert outbound == b"".join(receive.frames), "every byte written, the probes' PINGs too"
        assert probes_sent(receive) == len(pongs), "each probe's PONG was read"
        summary = json.loads((tmp_path / "consumer_so_summary.json").read_text(encoding="utf-8"))
        assert summary["ids_read"] == 5 and summary["ids_read_untimed"] == 0
        assert summary["journal_connections"] == 2
        assert summary["transmit_timestamps"] == receive.sends + acks.sends, (
            "every send's transmit timestamp was read off its error queue, peeks or not")
        assert not receive.errors and not acks.errors
        assert len(rows(tmp_path / "consumer.csv")) == 5


# --- the trial runner ---------------------------------------------------------------------------

def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


@pytest.mark.shell
class TestTheTrialRunner:
    """scripts/run_nats_trial.sh in a scratch folder: its Python stands in for each client by
    writing down how it was called, except where it runs the runner's own record of the run from
    stdin, and the wraps write down how they were called and run what they wrap."""

    @staticmethod
    def calls(tmp_path, *flags, **env):
        work = tmp_path / "work"
        stubs, calls = work / "bin", work / "calls.txt"
        python = Path(sys.executable).as_posix()
        for name, body in (
                ("py", 'if [ "$1" = - ]; then exec "%s" "$@"; fi\necho "python $*" >> "$CALLS"\n'
                 % python),
                ("schedwrap", 'echo "schedwrap $*" >> "$CALLS"\nexec "$@"\n'),
                ("prodwrap", 'echo "prodwrap $*" >> "$CALLS"\nexec "$@"\n'),
                ("sleep", ":\n")):
            os.chmod(_write(stubs / name, "#!/bin/sh\n" + body), 0o755)
        extra = {"PYTHON": (stubs / "py").as_posix(), "CALLS": calls.as_posix(),
                 "SBL_SCHED_WRAP": "", "SBL_PRODUCER_WRAP": "", "SBL_CONSUMER_WRAP": ""}
        extra.update(env)
        done = bash([(REPO / "scripts" / "run_nats_trial.sh").as_posix(), "r 1.x", "plan.csv",
                     "1", "10"] + list(flags), cwd=work, path_first=[stubs], extra_env=extra,
                    capture_output=True, text=True, stdin=subprocess.DEVNULL)
        assert done.returncode == 0, done.stdout + done.stderr
        meta = json.loads((work / "runs" / "r 1.x" / "meta.json").read_text(encoding="utf-8"))
        return calls.read_text(encoding="utf-8").splitlines(), meta

    @staticmethod
    def one(calls, start):
        """The one call that begins `start`. The consumer runs in the background, so the order
        its line and the producer's are written in is not the order they started in."""
        found = [c for c in calls if c.startswith(start)]
        assert len(found) == 1, calls
        return found[0]

    def test_the_runner_parses_has_lf_endings_and_starts_the_consumer_first(self):
        path = REPO / "scripts" / "run_nats_trial.sh"
        assert bash(["-n", path.as_posix()]).returncode == 0
        assert b"\r" not in path.read_bytes()
        text = path.read_text(encoding="utf-8")
        assert text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
        consumer = text.index("scripts/nats_consumer.py")
        assert text.index('> "runs/$RUN_ID/consumer.log" 2>&1 &\nCONS_PID=$!') > consumer
        assert consumer < text.index("sleep 1") < text.index("scripts/nats_producer.py")
        assert text.index('wait "$CONS_PID"') < text.index("scripts/compute_tti.py")

    def test_both_clients_get_one_set_of_names(self, tmp_path):
        calls, meta = self.calls(tmp_path)
        consumer = self.one(calls, "python scripts/nats_consumer.py ")
        producer = self.one(calls, "python scripts/nats_producer.py ")
        assert self.one(calls, "python scripts/compute_tti.py ")
        nats = meta["nats"]
        assert nats["stream"].startswith("SBL_r_1_x_") and nats["subject"].startswith(
            "sbl.r_1_x.") and nats["durable"] == "sbl-r_1_x"
        for line in (consumer, producer):
            assert "--stream %s --subject %s" % (nats["stream"], nats["subject"]) in line
        assert "--durable sbl-r_1_x" in consumer and "--depth 1" in consumer
        assert "--one-reply-reads" not in consumer and "--delete-stream" not in consumer
        assert "--speedup 1 --max-t-sim 10" in producer
        assert meta["backend"] == "nats" and nats["one_reply_reads"] is False
        assert sorted(meta["code_sha256"]) == [
            "scripts/compute_tti.py", "scripts/nats_consumer.py", "scripts/nats_producer.py",
            "scripts/nats_wire.py", "scripts/run_nats_trial.sh"]

    def test_the_settings_reach_the_clients_and_the_record(self, tmp_path):
        calls, meta = self.calls(
            tmp_path, "-NatsHost", "10.1.1.21", "-PORT", "4223", "-STREAM", "S", "-SUBJECT",
            "s.x", "-DURABLE", "d", "-DEPTH", "64", "-EXPIRES_S", "20", "-STORAGE", "memory",
            "-ONE_REPLY_READS", "-DELETE_STREAM", "-IDLE_SECONDS", "15", "-CONSUMER_EXTRA",
            "--gc-off", "-PRODUCER_EXTRA", "--pad-bytes 8", "-UNKNOWN",
            NATS_CONSUMER_OPTS="--thread-record")
        consumer = self.one(calls, "python scripts/nats_consumer.py ")
        producer = self.one(calls, "python scripts/nats_producer.py ")
        assert ("--host 10.1.1.21 --port 4223 --stream S --subject s.x --durable d "
                "--storage memory --depth 64 --expires-s 20 --idle-seconds 15 "
                "--one-reply-reads --delete-stream --gc-off") in consumer
        assert consumer.startswith("python scripts/nats_consumer.py --thread-record ")
        assert producer.endswith("--pad-bytes 8")
        assert meta["nats"] == {"host": "10.1.1.21", "port": 4223, "stream": "S",
                                "subject": "s.x", "durable": "d", "depth": 64,
                                "expires_s": 20.0, "storage": "memory",
                                "one_reply_reads": True, "delete_stream": True}
        assert meta["env"]["NATS_CONSUMER_OPTS"] == "--thread-record"

    def test_the_wraps_prefix_what_they_name(self, tmp_path):
        calls, meta = self.calls(tmp_path, SBL_SCHED_WRAP="schedwrap",
                                 SBL_PRODUCER_WRAP="prodwrap")
        sched = [c for c in calls if c.startswith("schedwrap ")]
        assert len(sched) == 2
        assert [c.split()[1] for c in sched if "nats_producer.py" in c] == ["prodwrap"], (
            "the producer's own wrap comes after the one both clients share")
        assert [c for c in sched if "nats_consumer.py" in c and "prodwrap" not in c]
        assert [c for c in calls if c.startswith("prodwrap ") and "nats_producer.py" in c]
        assert (meta["env"]["SBL_SCHED_WRAP"], meta["env"]["SBL_PRODUCER_WRAP"]) == (
            "schedwrap", "prodwrap")
