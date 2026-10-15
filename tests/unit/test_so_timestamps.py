"""Tests for scripts/so_timestamps.py: the kernel's own timestamps read on a client's sockets
through SO_TIMESTAMPING. Every call into the operating system is stood in for by one that answers
as the Linux kernel does: transmit timestamps on the error queue, each with the byte offset of its
send call's last byte, and a receive timestamp with every read."""
import argparse
import json
import os
import socket
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import so_timestamps as so  # noqa: E402

T0 = 1791900000 * 10**9
PORT = 19092


def stamp(ns):
    """struct scm_timestamping: the software time first, then two empty ones."""
    return so.TIMESPEC.pack(ns // 10**9, ns % 10**9) + bytes(2 * so.TIMESPEC.size)


def queue_entry(ns, key, info=0, origin=so.SO_EE_ORIGIN_TIMESTAMPING, v6=False):
    level, kind = (so.SOL_IPV6, so.IPV6_RECVERR) if v6 else (so.SOL_IP, so.IP_RECVERR)
    return (b"", [(socket.SOL_SOCKET, so.SCM_TIMESTAMPING, stamp(ns)),
                  (level, kind, so.EXTENDED_ERR.pack(42, origin, 0, 0, 0, info, key) + bytes(16))],
            so.MSG_ERRQUEUE, None)


def record(eid):
    return b'{"key":"' + eid.encode() + b'","value":{"event_id":"' + eid.encode() + b'"}}'


class Kernel(object):
    """Stands in for one connection's kernel side: a peer, an error queue and arriving data."""

    def __init__(self, peer=("10.1.1.21", PORT)):
        self.peer = peer
        self.queue = []
        self.arriving = []
        self.flags = None
        self.sent = b""
        self.closed = False
        self.error_pending = False

    def install(self, monkeypatch, refuse=False, connected=True):
        def getpeername(sock):
            if not connected:
                raise OSError(107, "not connected")
            return self.peer

        def setsockopt(sock, flags):
            if refuse:
                raise OSError(92, "protocol not available")
            self.flags = flags

        def recvmsg(sock, bufsize, ancbufsize, flags):
            if flags & so.MSG_ERRQUEUE:
                if not self.queue:
                    # poll() said something waits, and it is a socket error, not a timestamp.
                    self.error_pending = False
                    raise ConnectionResetError(104, "reset")
                return self.queue.pop(0)
            data, ns = self.arriving.pop(0)
            return data, ([] if ns is None else [(socket.SOL_SOCKET, so.SCM_TIMESTAMPING,
                                                  stamp(ns))]), 0, None

        def recvmsg_into(sock, buffers, ancbufsize, flags):
            data, ancillary, msg_flags, addr = recvmsg(sock, 0, ancbufsize, flags)
            buffers[0][:len(data)] = data
            return len(data), ancillary, msg_flags, addr

        def send(sock, data, flags):
            n = min(len(data), 40)
            self.sent += bytes(memoryview(data)[:n])
            return n

        def sendall(sock, data, flags):
            self.sent += bytes(data)

        monkeypatch.setattr(so, "_getpeername", getpeername)
        monkeypatch.setattr(so, "_getsockname", lambda sock: ("10.1.1.10", 40001))
        monkeypatch.setattr(so, "_setsockopt", setsockopt)
        monkeypatch.setattr(so, "_recvmsg", recvmsg)
        monkeypatch.setattr(so, "_recvmsg_into", recvmsg_into)
        monkeypatch.setattr(so, "_send", send)
        monkeypatch.setattr(so, "_sendall", sendall)
        monkeypatch.setattr(so, "_recv", lambda sock, n, flags: b"plain")
        monkeypatch.setattr(so, "_recv_into", lambda sock, buf, n, flags: 0)
        monkeypatch.setattr(so, "_close", lambda sock: setattr(self, "closed", True))
        monkeypatch.setattr(so, "_queued", lambda sock: bool(self.queue) or self.error_pending)
        return self


@pytest.fixture
def ledger(monkeypatch):
    """A ledger installed for the broker's port, with socket.socket put back afterwards."""
    monkeypatch.setattr(socket, "socket", socket.socket)
    return so.install([PORT])


def client(kind=socket.SOCK_STREAM):
    return so.TimestampingSocket(socket.AF_INET, kind)


class TestTheKernelsMessages:
    def test_a_reads_software_timestamp(self):
        assert so.software_ns([(socket.SOL_SOCKET, so.SCM_TIMESTAMPING, stamp(T0 + 5))]) == T0 + 5
        assert so.software_ns([(socket.SOL_SOCKET, so.SCM_TIMESTAMPING, b"short")]) is None
        assert so.software_ns([(0, 11, b"")]) is None

    def test_a_transmit_timestamps_key(self):
        assert so.transmit_key(queue_entry(T0, 64)[1]) == 64
        assert so.transmit_key(queue_entry(T0, 64, v6=True)[1]) == 64
        assert so.transmit_key(queue_entry(T0, 64, info=1)[1]) is None, "a queue timestamp"
        assert so.transmit_key(queue_entry(T0, 64, info=1)[1], "sched") == 64
        assert so.transmit_key(queue_entry(T0, 64, origin=2)[1]) is None, "an ICMP error"
        assert so.transmit_key([(so.SOL_IP, so.IP_RECVERR, b"short")]) is None


class TestFindingIds:
    def test_an_id_is_found_by_its_last_byte_and_across_a_joint(self):
        one = record("constant-000001")
        assert so.carried(one, b"", 100) == [("constant-000001", 100 + one.index(b"000001") + 5),
                                             ("constant-000001", 100 + one.rindex(b"000001") + 5)]
        cut = one.index(b"-000001") + 3
        tail, rest = one[:cut], one[cut:]
        found = so.carried(rest, tail, cut)
        assert found[0] == ("constant-000001", one.index(b"000001") + 5)
        assert so.carried(b"no id here", one, len(one)) == [], "an id wholly before is not new"

    def test_a_message_is_timed_by_its_later_carrying_within_one_record(self):
        assert so.one_message([(10, T0), (60, T0 + 9), (5000, T0 + 99)]) == T0 + 9
        assert so.one_message([(10, None), (60, T0 + 9)]) == T0 + 9
        assert so.one_message([(10, None)]) is None


class TestTheSocket:
    def test_a_connection_to_the_broker_is_timestamped_both_ways(self, ledger, monkeypatch):
        kernel = Kernel().install(monkeypatch)
        sock = client()
        one, two = record("constant-000001"), record("constant-000002")
        assert sock.send(one) == 40, "a partial send counts only what went"
        sock.sendall(one[40:] + two)
        assert kernel.flags == ledger.flags and ledger.counts["connections"] == 1
        # The kernel timestamps the three send calls, keyed by their last bytes.
        ends = [39, len(one + two) - 1]
        kernel.queue += [queue_entry(T0 + 10, ends[0]), queue_entry(T0 + 20, ends[1]),
                         queue_entry(T0 + 21, ends[1]),
                         (b"", [(socket.SOL_SOCKET, so.SCM_TIMESTAMPING, stamp(T0))], 0, None)]
        kernel.arriving += [(one, T0 + 500), (two[:30], None), (two[30:], T0 + 700)]
        assert sock.recv(4096) == one
        buf = bytearray(4096)
        assert sock.recv_into(buf, 30) == 30 and bytes(buf[:30]) == two[:30]
        assert sock.recv_into(buf) == len(two) - 30
        tx, rx = ledger.transmit_times(), ledger.receive_times()
        assert tx == {"constant-000001": T0 + 20, "constant-000002": T0 + 20}, (
            "000001's last carrying, in the value, ends after the first send call")
        assert rx == {"constant-000001": T0 + 500, "constant-000002": T0 + 700}
        assert ledger.counts["transmit_timestamps"] == 3, (
            "each queue the packet entered gave one; the first is kept")
        assert ledger.counts["other_queue_entries"] == 1
        assert ledger.counts["reads"] == 3 and ledger.counts["reads_without_timestamp"] == 1
        kernel.error_pending = True
        assert sock.send(b"after") == 5, "a socket error on the queue ends the drain, not the send"
        sock.close()
        assert kernel.closed and ledger.streams[0].closed

    def test_other_connections_and_peeks_pass_straight_through(self, ledger, monkeypatch):
        kernel = Kernel(peer=("10.1.1.21", 6379)).install(monkeypatch)
        sock = client()
        assert sock.recv(10) == b"plain" and sock.recv_into(bytearray(4)) == 0
        assert sock.send(b"abc") == 3 and sock.sendall(b"abc") is None
        assert ledger.counts["connections"] == 0 and kernel.flags is None
        sock.close()
        Kernel(peer="").install(monkeypatch)
        unix = client()
        assert unix._sbl_stream() is None, "a Unix socket's peer is no address"
        unix.close()
        Kernel().install(monkeypatch)
        udp = client(socket.SOCK_DGRAM)
        assert udp._sbl_stream() is None
        udp.close()
        Kernel().install(monkeypatch)
        peeking = client()
        assert peeking.recv(10, so.MSG_PEEK) == b"plain"
        assert peeking.recv_into(bytearray(4), 0, so.MSG_PEEK) == 0
        peeking.close()

    def test_the_decision_waits_for_the_connection_and_a_refusal_is_counted(self, ledger,
                                                                            monkeypatch):
        kernel = Kernel().install(monkeypatch, connected=False)
        sock = client()
        assert sock._sbl_stream() is None and "_sbl_state" not in sock.__dict__
        Kernel().install(monkeypatch, refuse=True)
        assert sock._sbl_stream() is None and ledger.counts["refused"] == 1
        assert sock._sbl_stream() is None, "and the refusal is remembered"
        sock.close()
        assert kernel.flags is None

    def test_writing_drains_the_open_connections_and_counts_what_is_missing(
            self, ledger, monkeypatch, tmp_path):
        kernel = Kernel().install(monkeypatch)
        sock = client()
        sock.sendall(record("constant-000003"))
        sock.sendall(record("constant-000004"))
        kernel.queue.append(queue_entry(T0 + 30, len(record("constant-000003")) - 1))
        kernel.arriving.append((record("constant-000005"), None))
        sock.recv(4096)
        path = tmp_path / "out" / "producer_so.csv"
        summary = ledger.write(str(path))
        rows = path.read_text(encoding="utf-8").splitlines()
        assert rows[0] == "event_id,direction,ns"
        assert "constant-000003,tx,%d" % (T0 + 30) in rows and "constant-000004,tx," in rows
        assert "constant-000005,rx," in rows
        assert (summary["ids_sent"], summary["ids_sent_untimed"], summary["ids_read"],
                summary["ids_read_untimed"]) == (2, 1, 1, 1)
        saved = json.loads((tmp_path / "out" / "producer_so_summary.json").read_text(
            encoding="utf-8"))
        assert saved["transmit"] == "software" and saved["transmit_timestamps"] == 1
        assert saved["transmit_keys"] == 1
        sock.close()
        monkeypatch.chdir(tmp_path)
        assert ledger.write("bare.csv")["ids_sent"] == 2, "a path with no folder"
        assert (tmp_path / "bare_summary.json").exists()


class TestTheJournal:
    """Freeze 41: every byte each way, one row per read, every transmit timestamp, so that the
    acknowledgments and the consumer's requests can be matched after the run."""

    def test_every_byte_read_and_timestamp_is_kept_per_connection(self, monkeypatch, tmp_path):
        monkeypatch.setattr(socket, "socket", socket.socket)
        stem = tmp_path / "run" / "producer_journal"
        ledger = so.install([PORT], "sched", journal=str(stem))
        kernel = Kernel().install(monkeypatch)
        sock = client()
        one = record("constant-000007")
        assert sock.send(one) == 40
        sock.sendall(one[40:])
        kernel.queue.append(queue_entry(T0 + 10, 39, info=1))
        kernel.queue.append(queue_entry(T0 + 20, len(one) - 1, info=1))
        kernel.arriving += [(b"ack-one", T0 + 500), (b"ack-two", None)]
        assert sock.recv(64) == b"ack-one"
        buf = bytearray(64)
        assert sock.recv_into(buf) == 7
        summary = ledger.write(str(tmp_path / "run" / "producer_so.csv"))
        assert (summary["journal_connections"], summary["journal_reads"]) == (1, 2)
        assert (tmp_path / "run" / "producer_journal_conn0_out.bin").read_bytes() == one
        assert (tmp_path / "run" / "producer_journal_conn0_in.bin").read_bytes() == \
            b"ack-oneack-two"
        reads = (tmp_path / "run" / "producer_journal_reads.csv").read_text(
            encoding="utf-8").splitlines()
        assert reads == ["conn,end,bytes,ns", "0,7,7,%d" % (T0 + 500), "0,14,7,"]
        keys = (tmp_path / "run" / "producer_journal_txkeys.csv").read_text(
            encoding="utf-8").splitlines()
        assert keys == ["conn,key,ns", "0,39,%d" % (T0 + 10), "0,%d,%d" % (len(one) - 1, T0 + 20)]
        streams = (tmp_path / "run" / "producer_journal_streams.csv").read_text(
            encoding="utf-8").splitlines()
        assert streams == ["conn,local_port,peer_host,peer_port", "0,40001,10.1.1.21,%d" % PORT]
        sock.close()

    def test_a_connection_never_timestamped_writes_no_files_and_a_bare_stem_works(
            self, monkeypatch, tmp_path):
        monkeypatch.setattr(socket, "socket", socket.socket)
        monkeypatch.chdir(tmp_path)
        ledger = so.install([PORT], journal="bare")
        Kernel(peer=("10.1.1.21", 6379)).install(monkeypatch)
        monkeypatch.setattr(so, "_getsockname", lambda sock: "not a tuple")
        other = client()
        other.sendall(b"elsewhere")
        refused = so.Ledger("software", journal=None)
        assert refused.journal is None
        summary = ledger.write("bare.csv")
        assert summary["journal_connections"] == 0
        assert (tmp_path / "bare_reads.csv").read_text(encoding="utf-8") == "conn,end,bytes,ns\n"
        assert not list(tmp_path.glob("bare_conn*")), "no connection was timestamped"
        stream = so._Stream(None)
        so.Journal(str(tmp_path / "j")).open(stream, "unix", ("10.1.1.21", PORT))
        assert stream.index == 0 and stream.files["out"] is not None
        for fh in stream.files.values():
            fh.close()

    def test_a_run_asks_for_the_journal_by_its_switch(self, monkeypatch, tmp_path):
        ap = argparse.ArgumentParser()
        so.add_arguments(ap)
        monkeypatch.setattr(socket, "socket", socket.socket)
        on = ap.parse_args(["--so-timestamps", str(tmp_path / "c.csv"),
                            "--so-journal", str(tmp_path / "c_journal")])
        ledger = so.start(on, PORT)
        assert ledger.journal is not None and ledger.journal.stem == str(tmp_path / "c_journal")
        plain = ap.parse_args(["--so-timestamps", str(tmp_path / "d.csv")])
        assert so.start(plain, PORT).journal is None


class TestTheSystemCalls:
    def test_the_queue_is_asked_about_without_waiting(self, monkeypatch):
        """poll() with a timeout of zero, for POLLERR, which it reports unasked. Stood in for, as
        Windows has no poll()."""
        import select
        answers, seen = [[(3, 8 | 1)], [(3, 1)], []], []

        class Poll(object):
            def register(self, fd, mask):
                seen.append((fd, mask))

            def poll(self, timeout):
                seen.append(timeout)
                return answers.pop(0)
        monkeypatch.setattr(select, "poll", Poll, raising=False)
        monkeypatch.setattr(select, "POLLERR", 8, raising=False)
        sock = client()
        assert so._queued(sock) is True
        assert so._queued(sock) is False, "readable data alone is not the error queue"
        assert so._queued(sock) is False
        assert seen[:2] == [(sock.fileno(), 0), 0]
        sock.close()

    def test_each_reaches_the_original_socket_class(self, monkeypatch):
        calls = []

        class Base(object):
            pass
        for name in ("getpeername", "getsockname", "setsockopt", "send", "sendall", "recv",
                     "recv_into", "recvmsg", "recvmsg_into", "close"):
            setattr(Base, name, staticmethod(
                lambda *a, _n=name: calls.append((_n,) + a[1:]) or _n))
        monkeypatch.setattr(so, "_BASE", Base)
        so._getpeername("s")
        so._getsockname("s")
        so._setsockopt("s", 7)
        so._send("s", b"x", 0)
        so._sendall("s", b"x", 0)
        so._recv("s", 1, 0)
        so._recv_into("s", "b", 1, 0)
        so._recvmsg("s", 1, 2, 3)
        so._recvmsg_into("s", ["b"], 2, 3)
        so._close("s")
        assert [c[0] for c in calls] == ["getpeername", "getsockname", "setsockopt", "send",
                                         "sendall", "recv", "recv_into", "recvmsg",
                                         "recvmsg_into", "close"]
        assert calls[2] == ("setsockopt", socket.SOL_SOCKET, so.SO_TIMESTAMPING, 7)


class TestTheClientsLines:
    def test_the_switches_the_port_and_the_ledger(self, monkeypatch, tmp_path, capsys):
        ap = argparse.ArgumentParser()
        so.add_arguments(ap)
        off = ap.parse_args([])
        assert so.start(off, PORT) is None
        so.finish(None, off)
        assert so.port_of("10.1.1.21:19092", 9092) == 19092
        assert so.port_of("broker", 9092) == 9092 and so.port_of("a:b", 9) == 9
        assert so.port_of("h1:1,h2:2", 0) == 1
        monkeypatch.setattr(socket, "socket", socket.socket)
        on = ap.parse_args(["--so-timestamps", str(tmp_path / "c.csv"), "--so-transmit", "sched"])
        ledger = so.start(on, 6379)
        assert socket.socket is so.TimestampingSocket and so.TimestampingSocket._ports == (6379,)
        assert ledger.flags & so.SOF_TIMESTAMPING_TX_SCHED
        so.finish(ledger, on)
        assert "OK socket timestamps: 0 ids sent, 0 read" in capsys.readouterr().out
        assert (tmp_path / "c_summary.json").exists()
