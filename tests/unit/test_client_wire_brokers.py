"""Tests for scripts/client_wire.py's other readings, against runs built here packet by packet in
the shape the kit writes them: NATS JetStream and AMQP 0-9-1 on the client host's captures, each
message by the broker's own id; the broker's own capture, read by the same walks on its own clock
(broker_times), for all four brokers; and the clients' own journals (socket_run).

The NATS frames are written as nats-server 2.15 writes them: a delivered message under the stream's
own subject, with its $JS.ACK reply subject in the nine-token and the eleven-token forms; and also
under the request's reply subject, the form test_nats_wire.py's scripted server writes. The AMQP
frames are test_amqp_frames.py's, pika 1.3.2's encoding. Each made-up connection is seen by both
its captures (Pair): every piece crosses in WAY, and the broker's clock runs CLOCK ahead, so a
reading that took a time from the wrong capture is off by milliseconds.

World, at the end, makes a whole run of any of the four brokers from a schedule, with the clients'
own files beside the captures; test_general_method.py reads its runs."""
import json
import os
import socket
import struct
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "scripts"))

import amqp_frames as af  # noqa: E402
import client_wire as cw  # noqa: E402
import nats_wire as nw  # noqa: E402
import test_amqp_frames as taf  # noqa: E402
import test_client_wire as tcw  # noqa: E402
import test_nats_wire as tnw  # noqa: E402

US = 1000
T0 = tcw.T0
DRIVER, BROKER, RECEIVER = tcw.DRIVER, tcw.BROKER, tcw.RECEIVER
at = tcw.at
PORT = {"kafka": 19092, "redis": 6379, "nats": 4222, "rabbitmq": 5672}
#: The broker's clock runs CLOCK us ahead of the client hosts', and every crossing takes WAY us.
CLOCK, WAY = 7000, 100
#: A client's socket times what it sends TX_LEAD us before its host's capture does, and what it
#: reads RX_LAG us after.
TX_LEAD, RX_LAG = 3, 2

STREAM, SUBJECT, DURABLE = "SBL_r1", "sbl.r1", "sbl-r1"
INBOX_REQ, INBOX_ACK = "_INBOX.0c9d8e7f6a5b4c3d2e1f00", "_INBOX.1a2b3c4d5e6f708192a3b4"
INBOX_PULL, INBOX_API = "_INBOX.4f1c2b7a9e3d5c8b1a0f6e", "_INBOX.9e8d7c6b5a4f3e2d1c0b0a"
QUEUE = "sb-events-r1"


def eid(i):
    return "constant-%06d" % i


def on_broker(outgoing, us):
    """When the broker's capture saw a piece the client's timed at `us`, on the broker's clock: a
    request WAY after it left, an answer WAY before it arrived."""
    return us + CLOCK + (WAY if outgoing else -WAY)


class Pair(object):
    """One made-up connection as both its captures saw it: the client host's (`client`) and the
    broker's own (`broker`), each a test_client_wire.Wire, timed by on_broker; and every piece each
    way (`pieces`, (us, bytes)), from which the client's journal is written."""

    def __init__(self, client, port, broker_port):
        self.port = port
        self.client = tcw.Wire(client, port, broker_port)
        self.broker = tcw.Wire(client, port, broker_port)
        self.pieces = {True: [], False: []}

    def carry(self, outgoing, us, data):
        """`data` sent next one way, in one packet the client's capture timed at `us`; where it
        starts in its stream."""
        start = self.client.carry(outgoing, us, data)
        self.broker.carry(outgoing, on_broker(outgoing, us), data)
        self.pieces[outgoing].append((us, data))
        return start


def write_captures(run, sending, getting):
    """The run's three captures: sender_full.pcap on the driver's Ethernet link, receiver_full.pcap
    in the receiver's namespace (Linux cooked v2), and the broker's own, broker_full.pcap."""
    with open(os.path.join(run, "sender_full.pcap"), "wb") as fh:
        fh.write(tcw.pcap_bytes([p for w in sending for p in w.client.packets], tcw.ether, 1))
    with open(os.path.join(run, "receiver_full.pcap"), "wb") as fh:
        fh.write(tcw.pcap_bytes([p for w in getting for p in w.client.packets], tcw.sll2, 276))
    with open(os.path.join(run, "broker_full.pcap"), "wb") as fh:
        fh.write(tcw.pcap_bytes([p for w in list(sending) + list(getting)
                                 for p in w.broker.packets], tcw.ether, 1))


def write_journal(stem, pairs, broker_port, other=None):
    """One client's journal, as scripts/so_timestamps.py --so-journal writes it, of its connections:
    every piece each way, each piece sent one send call timed TX_LEAD before its host's capture,
    each piece read one read timed RX_LAG after it. `other`, a connection to another port, is
    journaled too, as the journal holds any connection the client asked it to."""
    streams = ["conn,local_port,peer_host,peer_port"]
    reads, keys = ["conn,end,bytes,ns"], ["conn,key,ns"]
    pairs = list(pairs)
    for i, pair in enumerate(pairs + ([other] if other else [])):
        port = broker_port if i < len(pairs) else broker_port + 1
        streams.append("%d,%d,%s,%d" % (i, pair.port, BROKER, port))
        for outgoing in (True, False):
            data, end = b"", 0
            for us, piece in pair.pieces[outgoing]:
                data += piece
                end += len(piece)
                if outgoing:
                    keys.append("%d,%d,%d" % (i, end - 1, at(us) - TX_LEAD * US))
                else:
                    reads.append("%d,%d,%d,%d" % (i, end, len(piece), at(us) + RX_LAG * US))
            with open("%s_conn%d_%s.bin" % (stem, i, "out" if outgoing else "in"), "wb") as fh:
                fh.write(data)
    for suffix, lines in (("streams", streams), ("reads", reads), ("txkeys", keys)):
        with open("%s_%s.csv" % (stem, suffix), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


def new_run(root, name, backend, setup=None, params=None):
    run = os.path.join(str(root), name)
    os.makedirs(run)
    with open(os.path.join(run, "queue_row.json"), "w", encoding="utf-8") as fh:
        json.dump({"setup": setup or "V2000-%s-d1" % backend,
                   "params": dict({"backend": backend}, **(params or {}))}, fh)
    return run


# --- NATS's frames, as nats-server writes them ----------------------------------------------------

def payload(i):
    """The producer's message for event i, as nats_producer.py writes it."""
    return tnw.PAYLOAD.replace(b"constant-000001", eid(i).encode())


def msg(subject, sid, reply, data):
    """MSG <subject> <sid> [reply] <size>, and the payload."""
    return (("MSG %s %s %s%d\r\n" % (subject, sid, "%s " % reply if reply else "", len(data)))
            .encode() + data + b"\r\n")


def hmsg(subject, sid, reply, headers, data):
    return (("HMSG %s %s %s%d %d\r\n" % (subject, sid, "%s " % reply if reply else "",
                                          len(headers), len(headers) + len(data))).encode()
            + headers + data + b"\r\n")


def status(subject, code, description, fields=()):
    """A status message, as nats-server ends a pull request with one."""
    block = nw.header_block(fields, (code, description))
    return b"HMSG %s 2 %d %d\r\n%s\r\n" % (subject.encode(), len(block), len(block), block)


def ack_subject(seq, cseq, delivered=1, pending=0, eleven=False):
    tail = "%s.%s.%d.%d.%d.%d.%d" % (STREAM, DURABLE, delivered, seq, cseq, T0 + seq * US,
                                     pending)
    return "$JS.ACK." + ("_.ShJBUMLJFlgLb7Z8f7bAwh." if eleven else "") + tail


def pull(j):
    subject, data = nw.pull_request(STREAM, DURABLE, 30 * 10**9)
    return nw.pub(subject, data, "%s.%d" % (INBOX_PULL, j))


def pub_ack(seq):
    return b'{"stream":"%s","seq":%d}' % (STREAM.encode(), seq)


TIMEOUT_FIELDS = (("Nats-Pending-Messages", "1"), ("Nats-Pending-Bytes", "0"))


def nats_world(root):
    """A NATS run and where its frames lie. The producer: its stream made, publishes 1 and 2
    acknowledged out of order (publish 1 sent in two packets), 3 answered by 503 (no stream), 4 by
    an error and 7 by an answer that is no acknowledgment, 5 published with headers, and 6 never
    answered. The consumer's receive connection: two pull requests waiting; message 1 delivered
    under the stream's subject, so to the oldest request; message 2 under request 2's own subject,
    with an eleven-token acknowledgment subject; a heartbeat, a PONG and a reply to nothing; request
    3 ended by 408; message 3, published with headers, to the oldest left, request 4; message 1
    delivered again; a status that does not read; a delivery whose acknowledgment subject does not
    read; one with no request outstanding; and bytes that lose the walk's place. The consumer's
    acknowledgments' connection: the stream and the consumer made, an acknowledgment, the server's
    PING answered, and a request still unanswered at the end."""
    where = {}
    p = Pair(DRIVER, 41000, PORT["nats"])
    p.carry(False, 5, tnw.INFO)
    p.carry(True, 10, nw.connect("sbl-nats-producer") + nw.PING)
    p.carry(False, 15, nw.PONG)
    create = nw.stream_create(STREAM, [SUBJECT])
    p.carry(True, 20, nw.sub(INBOX_REQ + ".*", 1) + nw.pub(create[0], create[1], INBOX_REQ + ".1"))
    p.carry(False, 30, msg(INBOX_REQ + ".1", 1, None, b'{"did_create":true}'))
    p.carry(True, 40, nw.sub(INBOX_ACK + ".*", 2))
    first = nw.pub(SUBJECT, payload(1), INBOX_ACK + ".1")
    where["pub1"] = p.carry(True, 100, first[:30])
    p.carry(True, 105, first[30:])
    where["pub1_end"] = where["pub1"] + len(first)
    p.carry(True, 200, nw.pub(SUBJECT, payload(2), INBOX_ACK + ".2"))
    p.carry(False, 250, msg(INBOX_ACK + ".2", 2, None, pub_ack(2)))
    p.carry(False, 260, msg(INBOX_ACK + ".1", 2, None, pub_ack(1)))
    p.carry(True, 300, nw.pub(SUBJECT, payload(3), INBOX_ACK + ".3"))
    p.carry(False, 350, status(INBOX_ACK + ".3", 503, ""))
    p.carry(True, 400, nw.pub(SUBJECT, payload(4), INBOX_ACK + ".4"))
    p.carry(False, 450, msg(INBOX_ACK + ".4", 2, None,
                            b'{"error":{"code":503,"err_code":10077,"description":"maximum '
                            b'messages exceeded"},"stream":"SBL_r1","seq":0}'))
    p.carry(True, 500, nw.hpub(SUBJECT, nw.header_block([("Nats-Msg-Id", eid(5))]), payload(5),
                               INBOX_ACK + ".5"))
    p.carry(False, 550, msg(INBOX_ACK + ".5", 2, None, pub_ack(3)))
    p.carry(False, 560, msg("elsewhere", 9, None, b"hi"))
    p.carry(True, 600, nw.pub(SUBJECT, payload(6), INBOX_ACK + ".6"))
    p.carry(True, 650, nw.pub(SUBJECT, payload(7), INBOX_ACK + ".7"))
    p.carry(False, 660, msg(INBOX_ACK + ".7", 2, None, b'{"stream":"SBL_r1"}'))
    p.carry(False, 700, nw.PING)
    p.carry(True, 705, nw.PONG)

    r = Pair(RECEIVER, 42000, PORT["nats"])
    r.carry(False, 5, tnw.INFO)
    r.carry(True, 10, nw.connect("sbl-nats-consumer") + nw.PING)
    r.carry(False, 15, nw.PONG)
    r.carry(True, 20, nw.sub(INBOX_PULL + ".*", 2))
    r.carry(True, 50, pull(1))
    r.carry(True, 51, pull(2))
    delivered = msg(SUBJECT, 2, ack_subject(1, 1, pending=1), payload(1))
    where["d1"] = r.carry(False, 270, delivered) + len(delivered)
    r.carry(True, 280, pull(3))
    delivered = msg(INBOX_PULL + ".2", 2, ack_subject(2, 2, eleven=True), payload(2))
    where["d2"] = r.carry(False, 290, delivered) + len(delivered)
    r.carry(True, 300, pull(4))
    r.carry(False, 400, status(INBOX_PULL + ".3", 100, "Idle Heartbeat"))
    r.carry(False, 410, nw.PONG)
    r.carry(False, 420, msg(INBOX_REQ + ".1", 1, None, b"{}"))
    r.carry(False, 500, status(INBOX_PULL + ".3", 408, "Request Timeout", TIMEOUT_FIELDS))
    r.carry(True, 510, pull(5))
    delivered = hmsg(SUBJECT, 2, ack_subject(3, 3), nw.header_block([("Nats-Msg-Id", eid(5))]),
                     payload(5))
    where["d3"] = r.carry(False, 560, delivered) + len(delivered)
    r.carry(False, 600, msg(SUBJECT, 2, ack_subject(1, 4, delivered=2), payload(1)))
    r.carry(True, 610, pull(6))
    r.carry(False, 615, b"HMSG %s.6 2 10 10\r\nBROKEN\r\n\r\n\r\n" % INBOX_PULL.encode())
    r.carry(False, 620, msg(SUBJECT, 2, "$JS.ACK.garbled", payload(7)))
    r.carry(False, 650, msg(SUBJECT, 2, ack_subject(9, 6), payload(9)))
    r.carry(False, 700, b"MSG x 1 5\r\nabcdefgh\r\n")

    a = Pair(RECEIVER, 42001, PORT["nats"])
    a.carry(False, 5, tnw.INFO)
    a.carry(True, 11, nw.connect("sbl-nats-consumer-acks") + nw.PING)
    a.carry(False, 16, nw.PONG)
    a.carry(True, 21, nw.sub(INBOX_API + ".*", 1) + nw.pub(create[0], create[1], INBOX_API + ".1"))
    a.carry(False, 31, msg(INBOX_API + ".1", 1, None, b'{"did_create":false}'))
    made = nw.consumer_create(STREAM, DURABLE)
    a.carry(True, 41, nw.pub(made[0], made[1], INBOX_API + ".2"))
    a.carry(False, 46, msg(INBOX_API + ".2", 1, None, b'{"name":"sbl-r1"}'))
    a.carry(True, 275, nw.ack(ack_subject(1, 1, pending=1)))
    a.carry(False, 700, nw.PING)
    a.carry(True, 705, nw.PONG)
    a.carry(True, 800, nw.pub(*nw.stream_delete(STREAM), reply=INBOX_API + ".3"))
    run = new_run(root, "law_n1", "nats")
    write_captures(run, [p], [r, a])
    write_journal(os.path.join(run, "producer_journal"), [p], PORT["nats"])
    write_journal(os.path.join(run, "consumer_journal"), [r, a], PORT["nats"], other=a)
    return run, where


@pytest.fixture(scope="module")
def nats_run(tmp_path_factory):
    return nats_world(tmp_path_factory.mktemp("nats"))


class TestNatsOnTheClientsCaptures:
    def test_each_message_by_its_stream_sequence(self, nats_run):
        run, where = nats_run
        messages, _, _ = cw.read_run(run, DRIVER, BROKER, RECEIVER)
        assert [(m["stream"], m["stream_seq"]) for m in messages] == [(STREAM, s)
                                                                      for s in (1, 2, 3)]
        one, two, three = messages
        assert one == {"stream": STREAM, "stream_seq": 1, "eid_sent": eid(1), "eid_got": eid(1),
                       "t_depart": at(105), "t_ack": at(260), "producer_port": 41000,
                       "request": 1, "sent_byte": where["pub1_end"] - 1, "t_arrive": at(270),
                       "consumer_port": 42000, "exchange": 1, "got_byte": where["d1"] - 1}
        assert (two["t_depart"], two["t_ack"], two["request"], two["t_arrive"],
                two["exchange"]) == (at(200), at(250), 2, at(290), 2), (
            "acknowledged before message 1, and delivered under its request's own subject")
        assert (three["eid_sent"], three["eid_got"], three["t_depart"], three["t_ack"],
                three["request"], three["t_arrive"], three["exchange"], three["got_byte"]) == (
            eid(5), eid(5), at(500), at(550), 5, at(560), 4, where["d3"] - 1), (
            "published and delivered with headers; delivered to the oldest request left, the "
            "one 408 ended being passed over")

    def test_every_request_on_both_consumer_connections(self, nats_run):
        run, _ = nats_run
        _, exchanges, _ = cw.read_run(run, DRIVER, BROKER, RECEIVER)
        rows = [(r["consumer_port"], r["exchange"], r["kind"], r["t_req"], r["t_ans"],
                 r["carried"], r["ids"]) for r in exchanges]
        assert rows == [
            (42000, 0, "PING", at(10), at(15), 0, ""),
            (42000, 1, cw.PULL, at(50), at(270), 1, STREAM + ":1"),
            (42000, 2, cw.PULL, at(51), at(290), 1, STREAM + ":2"),
            (42000, 3, cw.PULL, at(280), at(500), 0, ""),
            (42000, 4, cw.PULL, at(300), at(560), 1, STREAM + ":3"),
            (42000, 5, cw.PULL, at(510), at(600), 1, STREAM + ":1"),
            (42000, 6, cw.PULL, at(610), at(620), 0, ""),
            (42001, 0, "PING", at(11), at(16), 0, ""),
            (42001, 1, "STREAM.CREATE", at(21), at(31), 0, ""),
            (42001, 2, "CONSUMER.CREATE", at(41), at(46), 0, ""),
            (42001, 3, "STREAM.DELETE", at(800), None, 0, "")]

    def test_what_it_counted(self, nats_run):
        run, _ = nats_run
        _, _, summary = cw.read_run(run, DRIVER, BROKER, RECEIVER)
        assert {k: summary[k] for k in ("producer_connections", "consumer_connections", "matched",
                                        "sent_only", "got_only", "ids_differ", "ids_unread",
                                        "exchanges", "answered", "carried", "publishes",
                                        "publishes_unanswered", "publishes_refused", "statuses",
                                        "unrequested", "unreadable", "unframed")} == {
            "producer_connections": 1, "consumer_connections": 2, "matched": 3, "sent_only": 0,
            "got_only": 0, "ids_differ": 0, "ids_unread": 0, "exchanges": 11, "answered": 10,
            "carried": 4, "publishes": 7, "publishes_unanswered": 1, "publishes_refused": 3,
            "statuses": 1, "unrequested": 1, "unreadable": 2, "unframed": 21}
        assert summary["first_unreadable"] == ("a payload not followed by CRLF where its size "
                                               "said it ends")
        assert "kafka" not in cw.EXTRA_COUNTS and "batches" in summary

    def test_the_command_line_writes_nats_columns(self, nats_run, tmp_path, capsys):
        run, _ = nats_run
        out_m, out_x = str(tmp_path / "m.csv"), str(tmp_path / "x.csv")
        cw.main(["--run", run, "--driver", DRIVER, "--broker", BROKER, "--receiver", RECEIVER,
                 "--out-messages", out_m, "--out-exchanges", out_x])
        with open(out_m, encoding="utf-8") as fh:
            assert fh.readline().strip().split(",")[:2] == ["stream", "stream_seq"]
        assert "3 messages by the broker's ids: 3 both ways" in capsys.readouterr().out


class TestNatsOnTheBrokersCapture:
    def test_each_messages_four_times_on_the_brokers_clock(self, nats_run):
        run, _ = nats_run
        times, exchanges, summary = cw.broker_times(run, DRIVER, BROKER, RECEIVER)
        b = lambda outgoing, us: at(on_broker(outgoing, us))  # noqa: E731
        assert times[(STREAM, 1)] == [b(True, 105), b(False, 260), b(True, 50), b(False, 270)]
        assert times[(STREAM, 2)] == [b(True, 200), b(False, 250), b(True, 51), b(False, 290)]
        assert times[(STREAM, 3)] == [b(True, 500), b(False, 550), b(True, 300), b(False, 560)]
        assert sorted(times) == [(STREAM, 1), (STREAM, 2), (STREAM, 3)]
        assert (exchanges[3]["t_req"], exchanges[3]["t_ans"]) == (b(True, 280), b(False, 500)), (
            "a request's arrival, and the departure of the status that ended it")
        assert summary["matched"] == 3 and summary["statuses"] == 1

    def test_without_the_brokers_capture_nothing_is_timed(self, tmp_path):
        run = new_run(tmp_path, "law_none", "nats")
        times, exchanges, summary = cw.broker_times(run, DRIVER, BROKER, RECEIVER)
        assert (times, exchanges, summary["producer_connections"]) == ({}, [], 0)


class TestNatsOnTheJournals:
    def test_the_same_messages_timed_by_the_sockets(self, nats_run):
        run, where = nats_run
        messages, exchanges, summary = cw.socket_run(run)
        one = messages[0]
        assert (one["stream_seq"], one["t_depart"], one["t_ack"], one["t_arrive"]) == (
            1, at(105) - TX_LEAD * US, at(260) + RX_LAG * US, at(270) + RX_LAG * US), (
            "the send call that carried the publish's last byte, and the reads that delivered "
            "the acknowledgment and the message")
        assert one["got_byte"] == where["d1"] - 1 and one["producer_port"] == 41000
        assert summary["consumer_connections"] == 2, "the journal's connection to another port " \
                                                     "is left out"
        assert summary["unopened"] == 0 and summary["holes"] == 0
        assert exchanges[1]["t_req"] == at(50) - TX_LEAD * US

    def test_a_run_with_no_journals_has_no_rows(self, tmp_path):
        run = new_run(tmp_path, "law_none", "nats")
        assert cw.socket_run(run)[:2] == ([], [])


# --- AMQP's frames --------------------------------------------------------------------------------

def handshake(pair, outgoing_first=10):
    """The protocol header and the connection's opening, then channel 1 opened and the queue
    declared, each answered."""
    us = outgoing_first
    pair.carry(True, us, af.PROTOCOL_HEADER)
    for outgoing, data in ((False, taf.method(0, 10, 10, b"\x00\x09start")),
                           (True, taf.method(0, 10, 11, b"start-ok")),
                           (False, taf.method(0, 10, 30, b"tune")),
                           (True, taf.method(0, 10, 31, b"tune-ok") + taf.method(0, 10, 40, b"/")),
                           (False, taf.method(0, 10, 41)),
                           (True, taf.method(1, 20, 10)), (False, taf.method(1, 20, 11)),
                           (True, taf.declare(1, QUEUE, passive=False)),
                           (False, taf.declare_ok(1, QUEUE))):
        us += 1
        pair.carry(outgoing, us, data)
    return us


def body(i):
    return taf.payload(eid(i))


def published(i, with_id=True):
    """A publish of event i to the queue, through the default exchange, transient, its event id
    the message-id, as rabbitmq_producer.py publishes it."""
    data = body(i)
    if with_id:
        return taf.content(1, taf.publish(1, QUEUE), data, eid(i))
    return taf.publish(1, QUEUE) + taf.header(1, len(data), delivery_mode=1) + taf.body(1, data)


def delivery(tag, i, redelivered=False, with_id=True, consumer="ctag1.a"):
    data = body(i)
    opening = taf.deliver(1, tag, consumer, redelivered, "", QUEUE)
    if with_id:
        return taf.content(1, opening, data, eid(i))
    return opening + taf.header(1, len(data), delivery_mode=1) + taf.body(1, data)


def amqp_world(root):
    """An AMQP run and where its frames lie. The producer, in confirm mode: publishes 1 to 4
    confirmed by a multiple ack (1, 2), a nack (3) and an ack (4), publish 1 in two packets; 5
    without a message-id; 6 never confirmed. The consumer, at prefetch 1, acknowledging each
    delivery: event 1 on its first credit, then 2, 4, one without a message-id, 6, 2 delivered
    again, and 7, whose freeing acknowledgment the capture does not hold."""
    where = {}
    p = Pair(DRIVER, 43000, PORT["rabbitmq"])
    us = handshake(p)
    p.carry(True, us + 1, taf.select(1))
    p.carry(False, us + 2, taf.method(1, 85, 11))
    first = published(1)
    where["pub1"] = p.carry(True, 100, first[:40])
    p.carry(True, 104, first[40:])
    where["pub1_end"] = where["pub1"] + len(first)
    p.carry(True, 200, published(2))
    p.carry(True, 300, published(3))
    p.carry(False, 350, taf.ack(1, 2, multiple=True))
    p.carry(True, 400, published(4))
    p.carry(False, 420, taf.nack(1, 3))
    p.carry(False, 450, taf.ack(1, 4))
    p.carry(True, 500, published(5, with_id=False))
    p.carry(True, 600, published(6))
    p.carry(False, 610, taf.HEARTBEAT)

    c = Pair(RECEIVER, 44000, PORT["rabbitmq"])
    us = handshake(c)
    c.carry(True, us + 1, taf.qos(1, 1))
    c.carry(False, us + 2, taf.method(1, 60, 11))
    c.carry(True, us + 3, taf.consume(1, QUEUE, "ctag1.a"))
    c.carry(False, us + 4, taf.method(1, 60, 21, taf.shortstr("ctag1.a")))
    where["consume"] = us + 3
    for tag, i, t_got, t_ack, extra in ((1, 1, 150, 170, {}), (2, 2, 250, 260, {}),
                                        (3, 4, 460, 470, {}), (4, 5, 520, 530, {"with_id": False}),
                                        (5, 6, 610, 650, {}), (6, 2, 700, None,
                                                               {"redelivered": True}),
                                        (7, 7, 750, None, {})):
        data = delivery(tag, i, **extra)
        where["d%d" % tag] = c.carry(False, t_got, data) + len(data)
        if t_ack is not None:
            c.carry(True, t_ack, taf.ack(1, tag))
    c.carry(True, 760, taf.HEARTBEAT)
    run = new_run(root, "law_p1", "rabbitmq", "P2000-rabbitmq-q1")
    write_captures(run, [p], [c])
    write_journal(os.path.join(run, "producer_journal"), [p], PORT["rabbitmq"])
    write_journal(os.path.join(run, "consumer_journal"), [c], PORT["rabbitmq"])
    return run, where


@pytest.fixture(scope="module")
def amqp_run(tmp_path_factory):
    return amqp_world(tmp_path_factory.mktemp("amqp"))


class TestAmqpOnTheClientsCaptures:
    def test_each_message_by_its_queue_and_message_id(self, amqp_run):
        run, where = amqp_run
        messages, _, _ = cw.read_run(run, DRIVER, BROKER, RECEIVER)
        m = dict((row["message_id"], row) for row in messages)
        assert sorted(m) == [eid(i) for i in (1, 2, 3, 4, 6, 7)]
        assert m[eid(1)] == {"queue": QUEUE, "message_id": eid(1), "eid_sent": eid(1),
                             "eid_got": eid(1), "t_depart": at(104), "t_ack": at(350),
                             "producer_port": 43000, "request": 1,
                             "sent_byte": where["pub1_end"] - 1, "t_arrive": at(150),
                             "consumer_port": 44000, "exchange": 4, "got_byte": where["d1"] - 1}
        assert (m[eid(2)]["t_ack"], m[eid(2)]["t_arrive"], m[eid(2)]["exchange"]) == (
            at(350), at(250), 5), "confirmed by the multiple ack; delivered first on ack 1's credit"
        assert (m[eid(3)]["t_depart"], m[eid(3)]["t_ack"], m[eid(3)]["t_arrive"]) == (
            at(300), None, None), "refused by the nack, and never delivered"
        assert (m[eid(4)]["t_ack"], m[eid(4)]["t_arrive"], m[eid(4)]["exchange"]) == (
            at(450), at(460), 6)
        assert (m[eid(6)]["request"], m[eid(6)]["t_ack"], m[eid(6)]["exchange"]) == (6, None, 8)
        assert (m[eid(7)]["t_depart"], m[eid(7)]["t_arrive"], m[eid(7)]["exchange"]) == (
            None, at(750), None), "its credit's acknowledgment is not in the capture"

    def test_every_request_and_the_credit_it_freed(self, amqp_run):
        run, where = amqp_run
        _, exchanges, _ = cw.read_run(run, DRIVER, BROKER, RECEIVER)
        rows = [(r["exchange"], r["kind"], r["t_ans"] is not None, r["carried"], r["ids"])
                for r in exchanges]
        assert rows == [(0, "connection.open", True, 0, ""), (1, "channel.open", True, 0, ""),
                        (2, "queue.declare", True, 0, ""), (3, "basic.qos", True, 0, ""),
                        (4, "basic.consume", True, 1, QUEUE + ":" + eid(1)),
                        (5, "basic.ack", True, 1, QUEUE + ":" + eid(2)),
                        (6, "basic.ack", True, 1, QUEUE + ":" + eid(4)),
                        (7, "basic.ack", True, 0, ""),
                        (8, "basic.ack", True, 1, QUEUE + ":" + eid(6)),
                        (9, "basic.ack", True, 1, QUEUE + ":" + eid(2))]
        consume, ack1, ack3 = exchanges[4], exchanges[5], exchanges[7]
        assert (consume["t_req"], ack1["t_req"], ack1["t_ans"], ack3["t_ans"]) == (
            at(where["consume"]), at(170), at(250), at(520)), (
            "basic.consume answered by its consume-ok; each acknowledgment by the delivery its "
            "credit let go, one without a message-id among them")

    def test_what_it_counted(self, amqp_run):
        run, _ = amqp_run
        _, _, summary = cw.read_run(run, DRIVER, BROKER, RECEIVER)
        assert {k: summary[k] for k in ("matched", "sent_only", "got_only", "ids_differ",
                                        "publishes", "publishes_unanswered", "publishes_refused",
                                        "unkeyed", "unreleased", "unreadable", "unframed")} == {
            "matched": 4, "sent_only": 1, "got_only": 1, "ids_differ": 0, "publishes": 6,
            "publishes_unanswered": 1, "publishes_refused": 1, "unkeyed": 2, "unreleased": 1,
            "unreadable": 0, "unframed": 0}

    def test_on_the_brokers_capture_f_in_is_the_freeing_acknowledgment(self, amqp_run):
        run, where = amqp_run
        times, _, _ = cw.broker_times(run, DRIVER, BROKER, RECEIVER)
        b = lambda outgoing, us: at(on_broker(outgoing, us))  # noqa: E731
        assert times[(QUEUE, eid(2))] == [b(True, 200), b(False, 350), b(True, 170),
                                          b(False, 250)]
        assert times[(QUEUE, eid(1))][2] == b(True, where["consume"]), "the first credit's"
        assert times[(QUEUE, eid(7))] == [None, None, None, b(False, 750)]
        assert times[(QUEUE, eid(3))] == [b(True, 300), None, None, None]

    def test_on_the_journals(self, amqp_run):
        run, _ = amqp_run
        messages, _, _ = cw.socket_run(run)
        one = [m for m in messages if m["message_id"] == eid(1)][0]
        assert (one["t_depart"], one["t_ack"], one["t_arrive"]) == (
            at(104) - TX_LEAD * US, at(350) + RX_LAG * US, at(150) + RX_LAG * US)


class StubConn(cw.Conn):
    """A connection whose bytes are given and whose times are the bytes' own offsets, for the
    pairing alone."""

    def __init__(self, port, out, inb):
        cw.Conn.__init__(self, port)
        self.out_data, self.in_data = out, inb

    def left(self, offset):
        return offset

    def came(self, offset):
        return offset


def counts(backend):
    found = dict.fromkeys(cw.COUNTS + cw.EXTRA_COUNTS[backend], 0)
    found["first_unreadable"] = ""
    return found


class TestAmqpPairing:
    def test_a_tag_the_broker_named_and_deliveries_with_no_consume(self):
        out = (af.PROTOCOL_HEADER + taf.qos(1, 1) + taf.consume(1, QUEUE, "")
               + taf.consume(2, QUEUE, "") + taf.ack(1, 1))
        inb = (taf.method(1, 60, 21, taf.shortstr("amq.ctag-xyz"))
               + taf.method(2, 60, 21, taf.shortstr("amq.ctag-2")) + taf.method(1, 60, 11)
               + taf.method(1, 60, 11) + taf.method(3, 20, 11)
               + delivery(1, 1, consumer="amq.ctag-xyz") + delivery(2, 2, consumer="amq.ctag-xyz")
               + taf.deliver(3, 1, "x", False, "", QUEUE)
               + taf.header(3, len(body(3)), message_id=eid(3)) + taf.body(3, body(3)))
        found, rows = cw.amqp_consumed({1: StubConn(1, out, inb)}, counts("rabbitmq"))
        assert [r["kind"] for r in rows] == ["basic.qos", "basic.consume", "basic.consume",
                                             "basic.ack"]
        assert rows[1]["ids"] == QUEUE + ":" + eid(1), "the first consume of its channel"
        assert rows[3]["ids"] == QUEUE + ":" + eid(2)
        assert found[(QUEUE, eid(3))][3] is None, "channel 3 has no basic.consume"

    def test_bytes_that_are_not_amqp_are_counted_and_the_reading_stops(self):
        tally = counts("rabbitmq")
        items, stop = cw.amqp_items(af.PROTOCOL_HEADER + taf.ack(1, 1) + b"\x07garbage!", tally)
        assert [i.name for i in items] == ["basic.ack"] and stop == 8 + len(taf.ack(1, 1))
        assert tally["unreadable"] == 1 and "no AMQP frame" in tally["first_unreadable"]
        assert cw.amqp_items(b"", tally) == ([], 0)
        assert cw.amqp_items(af.PROTOCOL_HEADER, tally) == ([], 8)

    def test_a_content_that_does_not_follow_its_method_is_counted(self):
        tally = counts("rabbitmq")
        out = af.PROTOCOL_HEADER + taf.select(1) + taf.header(1, 3, message_id="a")
        inb = taf.publish(1, QUEUE) + taf.publish(1, QUEUE)
        assert cw.amqp_produced({1: StubConn(1, out, b"")}, tally) == {}
        assert cw.amqp_consumed({1: StubConn(1, b"", inb)}, tally) == ({}, [])
        assert tally["unreadable"] == 2


GO_INBOX = "_INBOX.Vb0oXZ0nmBO1xEmkqGTUfB"


def go_pull(batch_json):
    """A pull request as nats.go's Consume() sends it: many messages, every request to the one
    inbox its subscription listens on, with an idle heartbeat."""
    return nw.pub("$JS.API.CONSUMER.MSG.NEXT.%s.%s" % (STREAM, DURABLE), batch_json, GO_INBOX)


@pytest.fixture(scope="module")
def go_read(tmp_path_factory):
    """nats.go's Consume(): two requests waiting at once, of three messages and of five, served in
    turn as nats-server's waiting queue serves them; a 408 that names the shared inbox ends the
    first request still owed any, the second, three short; then requests whose batch does not
    read, taken as one message each."""
    g = Pair(RECEIVER, 42100, PORT["nats"])
    g.carry(False, 5, tnw.INFO)
    g.carry(True, 10, nw.connect("nats.go") + nw.PING)
    g.carry(False, 15, nw.PONG)
    g.carry(True, 20, nw.sub(GO_INBOX, 2))
    g.carry(True, 30, go_pull(b'{"batch":3,"expires":30000000000,"idle_heartbeat":15000000000}'))
    g.carry(True, 40, go_pull(b'{"batch":5,"expires":30000000000,"idle_heartbeat":15000000000}'))
    for k, us in enumerate((100, 110, 120, 130, 140)):
        g.carry(False, us, msg(SUBJECT, 2, ack_subject(k + 1, k + 1), payload(k + 1)))
    g.carry(False, 150, status(GO_INBOX, 408, "Request Timeout", TIMEOUT_FIELDS))
    g.carry(False, 160, status(GO_INBOX, 100, "Idle Heartbeat"))
    g.carry(True, 170, go_pull(b"not json"))
    g.carry(True, 171, go_pull(b'{"batch":"x"}'))
    g.carry(False, 200, msg(SUBJECT, 2, ack_subject(6, 6), payload(6)))
    g.carry(False, 210, msg(SUBJECT, 2, ack_subject(7, 7), payload(7)))
    g.carry(False, 300, status(GO_INBOX, 408, "Request Timeout", TIMEOUT_FIELDS))
    run = new_run(tmp_path_factory.mktemp("go"), "law_g1", "nats", "N2000-nats-go")
    write_captures(run, [], [g])
    return cw.read_run(run, DRIVER, BROKER, RECEIVER)


class TestNatsGoBatches:
    def test_each_request_gets_its_turn(self, go_read):
        messages, exchanges, summary = go_read
        by_seq = dict((m["stream_seq"], m["exchange"]) for m in messages)
        assert by_seq == {1: 1, 2: 2, 3: 1, 4: 2, 5: 1, 6: 3, 7: 4}
        assert [(r["kind"], r["carried"], r["t_ans"]) for r in exchanges] == [
            ("PING", 0, at(15)), (cw.PULL, 3, at(100)), (cw.PULL, 2, at(110)),
            (cw.PULL, 1, at(200)), (cw.PULL, 1, at(210))]
        assert summary["statuses"] == 1 and summary["unrequested"] == 0

    def test_the_batch_a_request_asks_for(self):
        assert cw._batch(b'{"batch":500,"expires":1}') == 500
        assert cw._batch(b'{"expires":1}') == 1 and cw._batch(b"[1]") == 1
        assert cw._batch(b'{"batch":0}') == 1 and cw._batch(b"no") == 1

    def test_the_waiting_queue_by_itself(self):
        w = cw.Waiting([0, 1, 2], {0: 10, 1: None, 2: 50}, {0: 2, 1: 1, 2: 1})
        assert w.take(20) == 0, "request 1's time is unknown, so it is taken to have arrived"
        assert list(w.queue) == [1, 0], "request 0, still owed one, goes to the back"
        assert w.take(30, named=2) == 2 and w.left[2] == 0, "named, though not yet arrived"
        assert w.take(40) == 1 and w.take(45) == 0 and w.take(60) is None
        w.end(1)
        assert w.left[1] == 0


class TestNatsPairing:
    def test_frames_cut_short_or_not_the_protocol(self):
        tally = counts("nats")
        assert cw.nats_frames(b"PING\r\nPO", tally) == ([(0, 6, nw.Frame("PING", None, None,
                                                                           None, b"", b""))], 6)
        assert cw.nats_frames(b"MSG a 1 2 3 4 2\r\nab\r\n", tally)[1] == 0
        assert tally["unreadable"] == 1 and "arguments" in tally["first_unreadable"]

    def test_small_pieces(self):
        assert cw._number(INBOX_PULL + ".17") == 17 and cw._number("_INBOX.x.y") is None
        assert cw._api_kind("$JS.API.CONSUMER.MSG.NEXT.S.d") == cw.PULL
        assert cw._api_kind("$JS.API.STREAM.INFO.S") == "STREAM.INFO"
        frame = nw.parse_frame(b"HMSG a 2 10 10\r\nBROKEN\r\n\r\n\r\n")
        assert cw._status(frame) is None
        assert cw._status(nw.parse_frame(status("a", 408, "Request Timeout"))) == (
            408, "Request Timeout")


def uses_of(rows, port):
    """(kind, grant, [(first byte's arrival, credit used)]) for each exchange on one connection."""
    return [(r["kind"], r["grant"], r["uses"]) for r in rows if r["consumer_port"] == port]


class TestTheCreditLedger:
    """Each request's grant of credit as it left, and each frame that answered it with the credit
    it used, timed by its first byte: what the reader counts to certify a request was waiting."""

    def test_nats_pull_requests_and_their_answers(self, nats_run):
        run, _ = nats_run
        _, exchanges, _ = cw.read_run(run, DRIVER, BROKER, RECEIVER)
        assert uses_of(exchanges, 42000) == [
            ("PING", 0, []), (cw.PULL, 1, [(at(270), 1)]), (cw.PULL, 1, [(at(290), 1)]),
            (cw.PULL, 1, [(at(500), 1)]), (cw.PULL, 1, [(at(560), 1)]),
            (cw.PULL, 1, [(at(600), 1)]), (cw.PULL, 1, [(at(620), 1)])], (
            "the 408 ends request 3, the heartbeat before it uses nothing, and the delivery whose "
            "acknowledgment subject did not read still used request 6")
        assert [g for _, g, _ in uses_of(exchanges, 42001)] == [0, 0, 0, 0]

    def test_nats_gos_batches_and_the_status_that_ends_one(self, go_read):
        _, exchanges, _ = go_read
        assert uses_of(exchanges, 42100) == [
            ("PING", 0, []), (cw.PULL, 3, [(at(100), 1), (at(120), 1), (at(140), 1)]),
            (cw.PULL, 5, [(at(110), 1), (at(130), 1), (at(150), 3)]),
            (cw.PULL, 1, [(at(200), 1)]), (cw.PULL, 1, [(at(210), 1)])], (
            "the 408 at 150 ends the rest of request 2's credit, three messages")

    def test_amqp_credit_from_the_consume_and_each_acknowledgment(self, amqp_run):
        run, _ = amqp_run
        _, exchanges, _ = cw.read_run(run, DRIVER, BROKER, RECEIVER)
        assert uses_of(exchanges, 44000)[3:] == [
            ("basic.qos", 0, []), ("basic.consume", 1, [(at(150), 1), (at(750), 1)]),
            ("basic.ack", 1, [(at(250), 1)]), ("basic.ack", 1, [(at(460), 1)]),
            ("basic.ack", 1, [(at(520), 1)]), ("basic.ack", 1, [(at(610), 1)]),
            ("basic.ack", 1, [(at(700), 1)])], (
            "the consume grants the prefetch count; the delivery no acknowledgment freed uses "
            "the consume's credit, and the one without a message-id is counted all the same")

    def test_a_consume_on_a_channel_with_no_prefetch_count_grants_any_number(self):
        out = af.PROTOCOL_HEADER + taf.consume(1, QUEUE, "c")
        _, rows = cw.amqp_consumed({1: StubConn(1, out, b"")}, counts("rabbitmq"))
        assert rows[0]["grant"] == cw.UNLIMITED

    def test_kafka_and_redis_one_request_one_answer(self, tmp_path):
        (tmp_path / "k").mkdir()
        (tmp_path / "r").mkdir()
        run, _ = tcw.kafka_world(tmp_path / "k")
        _, exchanges, _ = cw.read_run(run, DRIVER, BROKER, RECEIVER)
        assert [(r["kind"], r["grant"], r["uses"]) for r in exchanges[:3]] == [
            ("ApiVersions", 0, []), ("Fetch", 1, [(at(1200), 1)]), ("Fetch", 1, [(at(1600), 1)])]
        assert exchanges[4]["uses"] == [], "a fetch still in flight"
        run, _ = tcw.redis_world(tmp_path / "r")
        _, exchanges, _ = cw.read_run(run, DRIVER, BROKER, RECEIVER)
        assert [(r["kind"], r["grant"], r["uses"]) for r in exchanges[2:5]] == [
            ("XREADGROUP", 1, [(at(170), 1)]), ("XREADGROUP", 1, [(at(240), 1)]),
            ("XACK", 0, [])]
        assert exchanges[7]["uses"] == []


def ip_tcp_window(src, dst, sport, dport, seq, flags, window, payload=b""):
    """A TCP packet advertising `window`."""
    tcp = struct.pack(">HHIIBBHHH", sport, dport, seq, 0, 5 << 4, flags, window, 0, 0) + payload
    return struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 0, 0, 64, 6, 0,
                       socket.inet_aton(src), socket.inet_aton(dst)) + tcp


class TestTheNetworksRecord:
    def test_retransmissions_zero_windows_and_every_packets_time(self, tmp_path):
        w = tcw.Wire(RECEIVER, 42000, PORT["nats"])
        w.carry(False, 10, tnw.INFO)
        w.carry(True, 20, nw.connect("x") + nw.PING)
        w.again(True, 40, 0, 5)
        w.carry(False, 50, nw.PONG)
        w.again(False, 60, 0, 10)
        seq = 70000 + 1 + len(w.data[False])
        w.packets.append((at(70), ip_tcp_window(RECEIVER, BROKER, 42000, PORT["nats"], 1, 0x10,
                                                0)))
        w.packets.append((at(80), ip_tcp_window(BROKER, RECEIVER, PORT["nats"], 42000, seq, 0x14,
                                                0)))
        run = new_run(tmp_path, "law_r1", "nats")
        with open(os.path.join(run, "receiver_full.pcap"), "wb") as fh:
            fh.write(tcw.pcap_bytes(w.packets, tcw.sll2, 276))
        conn = cw.connections(os.path.join(run, "receiver_full.pcap"), BROKER, PORT["nats"],
                              RECEIVER)[42000]
        assert conn.resent == [at(40), at(60)], "the client's PING sent again, and the INFO"
        assert conn.zero_windows == [at(70)], "a reset advertising none is no window"
        assert conn.packets == sorted(ns for ns, _ in w.packets)

    def test_the_detail_a_run_is_read_with(self, nats_run, amqp_run):
        run, _ = nats_run
        messages, _, _, conns = cw.read_detail(run, DRIVER, BROKER, RECEIVER)
        assert [m["t_ack_first"] for m in messages] == [at(260), at(250), at(550)]
        assert sorted(conns["sending"]) == [41000] and sorted(conns["getting"]) == [42000, 42001]
        assert "t_ack_first" not in cw.read_run(run, DRIVER, BROKER, RECEIVER)[0][0]
        run, _ = amqp_run
        messages = dict((m["message_id"], m) for m in cw.read_detail(run, DRIVER, BROKER,
                                                                      RECEIVER)[0])
        assert (messages[eid(2)]["t_ack_first"], messages[eid(3)]["t_ack_first"],
                messages[eid(7)]["t_ack_first"]) == (at(350), None, None), (
            "the multiple ack's first byte; a refused publish; one this capture never saw sent")

    def test_an_acknowledgment_in_two_packets_is_first_in_with_its_first(self, tmp_path):
        p = tcw.Wire(DRIVER, 47560, PORT["redis"])
        p.carry(True, 200, tcw.XADD_14)
        p.carry(False, 230, tcw.XADD_14_REPLY[:6])
        p.carry(False, 260, tcw.XADD_14_REPLY[6:])
        run = new_run(tmp_path, "law_x", "redis")
        with open(os.path.join(run, "sender_full.pcap"), "wb") as fh:
            fh.write(tcw.pcap_bytes(p.packets, tcw.ether, 1))
        message = cw.read_detail(run, DRIVER, BROKER, RECEIVER)[0][0]
        assert (message["t_ack_first"], message["t_ack"]) == (at(230), at(260))

    def test_the_command_line_leaves_out_what_rows_hold_only_in_memory(self, tmp_path):
        path = str(tmp_path / "x.csv")
        cw.write_csv(path, [{"a": 1, "uses": [(1, 1)]}], ("a",))
        with open(path, encoding="utf-8") as fh:
            assert fh.read() == "a\n1\n"


def fetch_v10_answer(corr, topic, records):
    """A fetch response, version 10, with one topic and one partition carrying `records`: no
    aborted transactions, high watermark 60."""
    part = struct.pack(">ihqqqi", 0, 0, 60, 60, 0, 0) + struct.pack(">i", len(records)) + records
    body = (struct.pack(">ihii", 0, 0, 0, 1) + struct.pack(">h", len(topic)) + topic
            + struct.pack(">i", 1) + part)
    return tcw.kafka_response(corr, body)


class TestKafkaOnTheBrokersCapture:
    def test_a_produce_request_reaches_the_broker_whole(self, tmp_path):
        """One produce request carrying two records, its first record's last byte in its first
        packet: on the producer's host the first record left with that packet, but the broker
        could act on neither record before the request's last byte had come."""
        two = [tcw.record(0, eid(0).encode(), tcw.value(eid(0).encode())),
               tcw.record(1, eid(1).encode(), tcw.value(eid(1).encode()))]
        request = tcw.produce_v8(7, TOPIC.encode(), 0, tcw.batch(0, two))
        p = Pair(DRIVER, 40001, PORT["kafka"])
        p.carry(True, 100, request[:-30])
        p.carry(True, 140, request[-30:])
        p.carry(False, 300, tcw.produce_v8_answer(7, TOPIC.encode(), 0, 0, 50))
        c = Pair(RECEIVER, 40002, PORT["kafka"])
        c.carry(True, 400, tcw.kafka_request(1, 10, 9, b""))
        c.carry(False, 500, fetch_v10_answer(9, TOPIC.encode(), tcw.batch(50, two)))
        run = new_run(tmp_path, "law_k1", "kafka")
        write_captures(run, [p], [c])
        messages, _, _ = cw.read_run(run, DRIVER, BROKER, RECEIVER)
        assert [(m["offset"], m["t_depart"]) for m in messages] == [(50, at(100)), (51, at(140))]
        times, _, _ = cw.broker_times(run, DRIVER, BROKER, RECEIVER)
        whole = at(on_broker(True, 140))
        assert [times[(TOPIC, 0, o)][0] for o in (50, 51)] == [whole, whole]


# --- the other pieces -----------------------------------------------------------------------------

class TestPieces:
    def test_ports_and_kinds(self):
        assert cw.PORTS == {"kafka": 19092, "redis": 6379, "nats": 4222, "rabbitmq": 5672}
        assert cw.WAITING_KINDS == frozenset(["XREAD", "XREADGROUP", "Fetch", cw.PULL,
                                              "basic.ack", "basic.nack", "basic.reject"])
        assert "basic.consume" in cw.SYNCHRONOUS and "connection.start-ok" not in cw.SYNCHRONOUS

    def test_one_pass_over_a_capture_for_several_hosts(self, nats_run):
        run, _ = nats_run
        found = cw.connections_of(os.path.join(run, "broker_full.pcap"), BROKER, PORT["nats"],
                                  (DRIVER, RECEIVER, "10.9.9.9"), at_broker=True)
        assert sorted(found[DRIVER]) == [41000] and sorted(found[RECEIVER]) == [42000, 42001]
        assert found["10.9.9.9"] == {} and found[DRIVER][41000].at_broker
        conn = found[DRIVER][41000]
        assert conn.left(0) == conn.out.readable(0) != conn.sent.at(0) or conn.left(0) == at(
            on_broker(True, 10)), "a client's byte is timed by when the broker could read it"
        assert cw.connections(os.path.join(run, "nowhere.pcap"), BROKER, 1, DRIVER) == {}

    def test_a_byte_sent_twice_is_timed_differently_by_each_capture(self, tmp_path):
        w = tcw.Wire(DRIVER, 40000, 4222)
        w.carry(True, 100, b"PING\r\n")
        w.carry(True, 300, b"PONG\r\n")
        w.again(True, 200, 0, 6)
        run = new_run(tmp_path, "law_x", "nats")
        with open(os.path.join(run, "p.pcap"), "wb") as fh:
            fh.write(tcw.pcap_bytes(w.packets, tcw.ether, 1))
        client = cw.connections(os.path.join(run, "p.pcap"), BROKER, 4222, DRIVER)[40000]
        broker = cw.connections_of(os.path.join(run, "p.pcap"), BROKER, 4222, (DRIVER,),
                                   at_broker=True)[DRIVER][40000]
        assert client.left(10) == at(300) and broker.left(10) == at(300)
        assert client.left(0) == at(100) == broker.left(0)

    def test_a_broker_not_read_here_is_refused(self, tmp_path):
        run = new_run(tmp_path, "law_x", "pulsar")
        for read in (lambda: cw.broker_times(run, DRIVER, BROKER, RECEIVER),
                     lambda: cw.socket_run(run)):
            with pytest.raises(ValueError, match="names no broker read here"):
                read()


# --- whole runs from a schedule, for every broker -------------------------------------------------

TOPIC, TID = tcw.TOPIC, tcw.TID
REDIS_STREAM = tcw.STREAM.decode()
REDIS_MS = 1792694468000
CTAG = "ctag1.a"


def broker_id(backend, i):
    """Message i's broker id in World's runs."""
    return {"kafka": (TOPIC, 0, i), "redis": (REDIS_STREAM, REDIS_MS, i), "nats": (STREAM, i + 1),
            "rabbitmq": (QUEUE, eid(i))}[backend]


class World(object):
    """A whole made-up run of one broker from its schedule, every time in us on the client hosts'
    clock: `sends`, [(departure, acknowledgment)] per message i, its event id eid(i); and `asks`,
    [(request, answer, [messages])] per consumer request for messages, in order. Each message rides
    its own produce request, XADD, PUB or publish on the producer's one connection, and each
    request is a fetch, an XREADGROUP, a pull request (answered by a 408 where it carries no
    message), or on RabbitMQ the basic.consume and then the acknowledgment of each delivery in
    turn (prefetch 1). The clients' own files are written beside the captures: producer.csv sent
    SEND_LEAD before each departure, consumer_events.csv stamped `lags[i]` after each arrival, the
    consumer's CONFIG line, meta.json, integrity.json and, where given, load_blocks.csv and the
    journals."""

    SEND_LEAD = 10
    #: The card's capture, where asked: every packet the receiver's capture holds, hardware
    #: timestamped CARD_LAG us before the kernel's time, on the card's clock, CARD_AHEAD ahead of
    #: the system's, its samples each bracketed by a WINDOW_NS window.
    CARD_LAG, CARD_AHEAD, WINDOW_NS = 20, 3000, 1500
    #: A NATS probe's round trip, where the run's consumer sends them: two crossings and a little.
    PROBE_TRIP = 210

    def __init__(self, backend, sends, asks, lags=None, setup=None, params=None, config="",
                 blocks=(), journals=False, offsets=False, machine="x86_64", verdict="count",
                 preamble=True, card=False, counters=False, probes=()):
        self.backend, self.sends, self.asks = backend, list(sends), list(asks)
        self.lags = lags or [100.0] * len(self.sends)
        self.setup, self.params, self.config = setup, params or {}, config
        self.blocks, self.journals, self.offsets = blocks, journals, offsets
        self.machine, self.verdict, self.preamble = machine, verdict, preamble
        self.card, self.counters, self.probes = card, counters, probes
        self.producer = Pair(DRIVER, 40001, PORT[backend])
        self.consumer = Pair(RECEIVER, 40002, PORT[backend])
        self.arrive = {}
        getattr(self, "_" + backend)()

    # -- each broker's frames
    def _kafka(self):
        p, c = self.producer, self.consumer
        for i, (sent, acked) in enumerate(self.sends):
            records = tcw.batch(0, [tcw.record(0, eid(i).encode(), tcw.value(eid(i).encode()))])
            p.carry(True, sent, tcw.produce_v8(i + 1, TOPIC.encode(), 0, records))
            p.carry(False, acked, tcw.produce_v8_answer(i + 1, TOPIC.encode(), 0, 0, i))
        c.carry(True, -50, tcw.kafka_request(3, 12, 1, tcw.NO_TAGS + b"\x01" + tcw.NO_TAGS))
        c.carry(False, -40, tcw.metadata_v12_answer(1, TOPIC.encode(), TID))
        for k, (asked, answered, ids) in enumerate(self.asks):
            c.carry(True, asked, tcw.kafka_request(1, 16, 100 + k, tcw.NO_TAGS + b"\x00"))
            records = b"".join(tcw.batch(i, [tcw.record(0, eid(i).encode(),
                                                         tcw.value(eid(i).encode()))])
                               for i in ids)
            c.carry(False, answered, tcw.fetch_v16_answer(100 + k, [(TID, 0, 0, records)]))
            self.arrive.update((i, answered) for i in ids)

    def _redis(self):
        p, c = self.producer, self.consumer
        stream = REDIS_STREAM.encode()
        for i, (sent, acked) in enumerate(self.sends):
            p.carry(True, sent, tcw.resp(b"XADD", stream, b"*", b"value",
                                         tcw.value(eid(i).encode())))
            rid = b"%d-%d" % (REDIS_MS, i)
            p.carry(False, acked, b"$%d\r\n%s\r\n" % (len(rid), rid))
        for asked, answered, ids in self.asks:
            c.carry(True, asked, tcw.XREADGROUP)
            reply = (b"*1\r\n*2\r\n$%d\r\n%s\r\n*%d\r\n" % (len(stream), stream, len(ids))
                     + b"".join(tcw.entry(b"%d-%d" % (REDIS_MS, i), eid(i).encode())
                                for i in ids)) if ids else b"*-1\r\n"
            c.carry(False, answered, reply)
            self.arrive.update((i, answered) for i in ids)

    def _nats(self):
        p, c = self.producer, self.consumer
        if self.preamble:
            p.carry(False, -100, tnw.INFO)
            p.carry(True, -99, nw.connect("sbl-nats-producer") + nw.PING)
            p.carry(False, -98, nw.PONG + b"")
            p.carry(True, -97, nw.sub(INBOX_ACK + ".*", 2))
        for i, (sent, acked) in enumerate(self.sends):
            p.carry(True, sent, nw.pub(SUBJECT, payload(i), "%s.%d" % (INBOX_ACK, i + 1)))
            p.carry(False, acked, msg("%s.%d" % (INBOX_ACK, i + 1), 2, None, pub_ack(i + 1)))
        c.carry(False, -100, tnw.INFO)
        c.carry(True, -99, nw.connect("sbl-nats-consumer") + nw.PING)
        c.carry(False, -98, nw.PONG)
        c.carry(True, -97, nw.sub(INBOX_PULL + ".*", 2))
        for k, (asked, answered, ids) in enumerate(self.asks):
            c.carry(True, asked, pull(k + 1))
        # The probes, each a PING answered PROBE_TRIP later; and the answers in the order they
        # came back, each a delivery under the stream's subject or a 408 ending its request.
        for us in self.probes:
            c.carry(True, us, nw.PING)
        back = [(us + self.PROBE_TRIP, None, nw.PONG) for us in self.probes]
        for k, (asked, answered, ids) in enumerate(self.asks):
            if ids:
                back.append((answered, ids[0], msg(SUBJECT, 2, ack_subject(ids[0] + 1, k + 1),
                                                   payload(ids[0]))))
            else:
                back.append((answered, None, status("%s.%d" % (INBOX_PULL, k + 1), 408,
                                                    "Request Timeout", TIMEOUT_FIELDS)))
        for answered, i, data in sorted(back, key=lambda b: b[0]):
            c.carry(False, answered, data)
            if i is not None:
                self.arrive[i] = answered

    def _rabbitmq(self):
        p, c = self.producer, self.consumer
        handshake(p, -100)
        p.carry(True, -80, taf.select(1))
        p.carry(False, -79, taf.method(1, 85, 11))
        for i, (sent, acked) in enumerate(self.sends):
            p.carry(True, sent, published(i))
            p.carry(False, acked, taf.ack(1, i + 1))
        handshake(c, -100)
        c.carry(True, -80, taf.qos(1, 1))
        c.carry(False, -79, taf.method(1, 60, 11))
        tag = 0
        for k, (asked, answered, ids) in enumerate(self.asks):
            if k == 0:
                c.carry(True, asked, taf.consume(1, QUEUE, CTAG))
                c.carry(False, asked + 1, taf.method(1, 60, 21, taf.shortstr(CTAG)))
            else:
                c.carry(True, asked, taf.ack(1, tag))
            for i in ids:
                tag += 1
                c.carry(False, answered, delivery(tag, i))
                self.arrive[i] = answered

    # -- the run's folder
    def write(self, root, name="law_w1"):
        backend = self.backend
        run = new_run(root, name, backend, self.setup, self.params)
        write_captures(run, [self.producer], [self.consumer])
        if self.journals:
            write_journal(os.path.join(run, "producer_journal"), [self.producer], PORT[backend])
            write_journal(os.path.join(run, "consumer_journal"), [self.consumer], PORT[backend])
        column = {"kafka": "topic", "redis": "stream", "nats": "stream", "rabbitmq": "stream"}
        where = {"kafka": TOPIC, "redis": REDIS_STREAM, "nats": STREAM, "rabbitmq": QUEUE}
        own = {"redis": "redis_id", "nats": "stream_seq", "rabbitmq": "delivery_tag"}
        ids = {"redis": lambda i: "%d-%d" % (REDIS_MS, i), "nats": lambda i: i + 1,
               "rabbitmq": lambda i: i + 1}
        head = ["run_id", "backend", column[backend], "event_id", "t_prod_sched_ns",
                "t_prod_send_ns", "t_broker_ack_ns"]
        extra = ([own[backend]] if backend in own else []) + (
            ["partition", "offset"] if self.offsets else [])
        lines = [",".join(head + extra)]
        for i, (sent, acked) in enumerate(self.sends):
            values = [name, backend, where[backend], eid(i), str(at(sent - 50)),
                      str(at(sent - self.SEND_LEAD)), str(at(acked + 5))]
            values += [str(ids[backend](i))] if backend in own else []
            values += ["0", str(i)] if self.offsets else []
            lines.append(",".join(values))
        with open(os.path.join(run, "producer.csv"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        events = {"kafka": ["topic", "partition", "offset"], "redis": ["stream", "redis_id"],
                  "nats": ["stream", "stream_seq"],
                  "rabbitmq": ["stream", "message_id", "delivery_tag"]}[backend]
        lines = [",".join(["run_id", "backend"] + events + ["t_consume_ns", "event_id"])]
        for tag, i in enumerate(sorted(self.arrive, key=lambda i: self.arrive[i]), 1):
            key = {"kafka": [TOPIC, "0", str(i)], "redis": [REDIS_STREAM, ids["redis"](i)],
                   "nats": [STREAM, str(i + 1)], "rabbitmq": [QUEUE, eid(i), str(tag)]}[backend]
            stamp = at(self.arrive[i]) + int(self.lags[i] * US)
            lines.append(",".join([name, backend] + key + [str(stamp), eid(i)]))
        with open(os.path.join(run, "consumer_events.csv"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        with open(os.path.join(run, "consumer.log"), "w", encoding="utf-8") as fh:
            fh.write("sudo: a line before\nCONFIG effective %s client=python\nOK done\n"
                     % self.config)
        with open(os.path.join(run, "meta.json"), "w", encoding="utf-8") as fh:
            json.dump({"host_platform": {"machine": self.machine}}, fh)
        with open(os.path.join(run, "integrity.json"), "w", encoding="utf-8") as fh:
            json.dump({"verdict": self.verdict}, fh)
        if self.blocks:
            with open(os.path.join(run, "load_blocks.csv"), "w", encoding="utf-8") as fh:
                fh.write("t_ns,state\n" + "".join("%d,%s\n" % (at(us), state)
                                                  for us, state in self.blocks))
        if self.card:
            ahead = (self.CARD_AHEAD - self.CARD_LAG) * US
            seen = [(ns + ahead, ip) for ns, ip in self.consumer.client.packets]
            with open(os.path.join(run, "receiver_hw.pcap"), "wb") as fh:
                fh.write(tcw.pcap_bytes(seen, tcw.ether, 1))
            with open(os.path.join(run, "phc_offset.csv"), "w", encoding="utf-8") as fh:
                fh.write("system_ns,card_minus_system_ns,window_ns\n" + "".join(
                    "%d,%d,%d\n" % (at(us), self.CARD_AHEAD * US, self.WINDOW_NS)
                    for us in (-10**7, 10**7)))
        if self.counters:
            for when, more in (("before", 0), ("after", 1)):
                with open(os.path.join(run, "softnet_%s.txt" % when), "w",
                          encoding="utf-8") as fh:
                    fh.write("%08x %08x %08x 00000000\n%08x %08x %08x 00000000\n"
                             % (100 + 50 * more, 0, 1 + 2 * more, 200 + 70 * more, more, 3))
                with open(os.path.join(run, "stat_%s.txt" % when), "w", encoding="utf-8") as fh:
                    fh.write("cpu  841723 0 35424 4362940 56032 0 %d 0 0 0\n" % (7126 + 30 * more))
        return run


#: Four messages and four requests, every broker alike: message 1 waited stored 250 us for its
#: request (the request left 150 us after the acknowledgment arrived), message 2 found its
#: request waiting, message 3's came 40 us after its acknowledgment left the broker.
SENDS = [(1000, 1400), (2000, 2400), (3000, 3400), (4000, 4400)]
ASKS = [(500, 1500, [0]), (2550, 3200, [1]), (1900, 2600, []), (3260, 3900, [2]), (4100, 4900, [3])]


def schedule(backend):
    """SENDS and ASKS shaped for each broker: on RabbitMQ every request carries one delivery, and
    on NATS each of its waiting requests one message or a 408."""
    asks = [a for a in ASKS if a[2]] if backend == "rabbitmq" else ASKS
    return SENDS, sorted(asks, key=lambda a: a[0])


@pytest.mark.parametrize("backend", ["kafka", "redis", "nats", "rabbitmq"])
class TestWorldsReadBackAsScheduled:
    def test_on_every_record(self, tmp_path, backend):
        sends, asks = schedule(backend)
        run = World(backend, sends, asks, journals=True).write(tmp_path)
        messages, exchanges, summary = cw.read_run(run, DRIVER, BROKER, RECEIVER)
        keys = [cw.KEY_FIELDS[backend] for _ in messages]
        assert summary["matched"] == 4 and summary["unreadable"] == 0
        by_key = dict((tuple(m[f] for f in k), m) for m, k in zip(messages, keys))
        times, _, _ = cw.broker_times(run, DRIVER, BROKER, RECEIVER)
        sockets = cw.socket_run(run)[0]
        for i, (sent, acked) in enumerate(sends):
            key = broker_id(backend, i)
            row_key = key if backend != "redis" else (key[0], "%d-%d" % key[1:])
            m = by_key[row_key]
            delivering = [a for a in asks if i in a[2]][0]
            assert (m["t_depart"], m["t_ack"], m["t_arrive"]) == (
                at(sent), at(acked), at(delivering[1])), (backend, i)
            request = [r for r in exchanges if (r["consumer_port"], r["exchange"])
                       == (m["consumer_port"], m["exchange"])][0]
            assert request["t_req"] == at(delivering[0]), (backend, i)
            assert times[key] == [at(on_broker(True, sent)), at(on_broker(False, acked)),
                                  at(on_broker(True, delivering[0])),
                                  at(on_broker(False, delivering[1]))], (backend, i)
            mine = [s for s in sockets if tuple(s[f] for f in cw.KEY_FIELDS[backend])
                    == row_key][0]
            assert (mine["t_depart"], mine["t_arrive"]) == (
                at(sent) - TX_LEAD * US, at(delivering[1]) + RX_LAG * US), (backend, i)
