"""Tests for scripts/m0_read.py: M0's four explanations, each on a made-up run shaped like the ones
campaign.sh writes -- the integrity record, the queue row, both captures as tcpdump writes them,
the receive loop's own trace and stamps, the consumer's printed settings -- and each piece on
numbers worked out by hand."""
import io
import json
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import m0_read as m0  # noqa: E402
import pcap_read as pr  # noqa: E402

RECEIVER, BROKER = "10.1.1.11", "10.1.1.21"
US, MS = 1000, 1000000
BASE = 1789762672 * 1000 * MS
#: The broker's clock runs 3 ms ahead of the driver's: the transit must not see it.
OFFSET = 3 * MS


def packet(payload=b"", src=RECEIVER, dst=BROKER, sport=40000, dport=6379, seq=1000, ack=1,
           flags=pr.PSH | pr.ACK, carried=None):
    tcp = struct.pack("!HHIIHH", sport, dport, seq, ack, (5 << 12) | flags, 502) + b"\0" * 4 \
        + payload
    total = 40 + (len(payload) if carried is None else carried)
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, total, 1, 0, 64, 6, 0,
                     bytes(int(x) for x in src.split(".")), bytes(int(x) for x in dst.split(".")))
    return ip + tcp


def capture(path, linktype, frames, snap=200):
    out = struct.pack("<IHHiIII", 0xa1b23c4d, 2, 4, 0, 0, snap, linktype)
    for ns, body in sorted(frames, key=lambda pair: pair[0]):
        whole = (b"\x02" * 12 + struct.pack("!H", pr.IPV4) + body if linktype == 1
                 else struct.pack("!H", pr.IPV4) + b"\0" * 18 + body)
        kept = whole[:snap]
        seconds, rest = divmod(ns, 1000000000)
        out += struct.pack("<IIII", seconds, rest, len(kept), len(whole)) + kept
    path.write_bytes(out)


def segment(ns, src=RECEIVER, dst=BROKER, sport=40000, dport=6379, seq=1000, ack=1, length=0,
            flags=pr.ACK, payload=b""):
    return {"ns": ns, "src": src, "sport": sport, "dst": dst, "dport": dport, "seq": seq,
            "ack": ack, "flags": flags, "window": 502, "length": length, "payload": payload}


class TestTheDeparture:

    def runs(self, trips, rounds=4):
        return [{"held_ms": held, "trip_ms": trip + 0.01 * r, "round": str(r),
                 "campaign": "m0"} for r in range(1, rounds + 1)
                for held, trip in trips]

    def test_it_is_the_slope_less_one_times_eight_and_keeps_its_sign(self):
        more = m0.departure(self.runs([(0.0, 1.0), (2.0, 3.6), (8.0, 11.4)]), draws=50)
        assert more["slope"] == pytest.approx(1.3) and more["departure_ms"] == \
            pytest.approx(2.4)
        less = m0.departure(self.runs([(0.0, 1.0), (2.0, 2.8), (8.0, 8.2)]), draws=50)
        assert less["departure_ms"] == pytest.approx(-0.8)
        assert less["interval"][0] <= less["slope"] <= less["interval"][1]

    def test_runs_at_one_delay_give_no_slope(self):
        found = m0.departure(self.runs([(2.0, 3.0)]), draws=10)
        assert found["slope"] is None and found["departure_ms"] is None

    @pytest.mark.parametrize("contribution,departure,kept", [
        (1.2, 2.4, True), (1.1, 2.4, False), (-1.2, 2.4, False), (-0.4, -0.8, True),
        (None, 2.4, False), (1.0, 0.0, False), (1.0, None, False)])
    def test_an_explanation_accounts_for_half_with_the_same_sign(self, contribution, departure,
                                                                 kept):
        assert m0.accounts_for(contribution, departure) is kept


class TestTheRecordingsOwnEffect:

    def test_the_log_stays_on_only_where_every_setup_moved_less_than_0_02_ms(self):
        def run(setup, recorded, trip, gotit):
            return {"setup": setup, "recorded": recorded, "trip_ms": trip, "gotit_ms": gotit}
        runs = [run("a", True, 1.00, 0.80), run("a", False, 1.01, 0.81),
                run("b", True, 2.00, 0.80), run("b", False, 2.01, 0.79)]
        found = m0.recording_effect(runs)
        assert found["log_stays_on"] is True
        assert found["by_setup"]["a"]["trip_ms"] == pytest.approx(-0.01)
        runs.append(run("c", True, 3.00, 0.80))
        assert m0.recording_effect(runs)["log_stays_on"] is False, "a setup with no unrecorded run"
        runs[-1:] = [run("c", True, 3.05, 0.80), run("c", False, 3.00, 0.80)]
        assert m0.recording_effect(runs)["log_stays_on"] is False
        assert m0.recording_effect([])["log_stays_on"] is False


class TestTheCaptures:

    def exchange(self, t1, up, wait, held, down, seq, reply_seq):
        """One request and its reply, seen at both ends; the broker's clock runs OFFSET ahead,
        and its capture sees the reply after the delay was added."""
        t2 = t1 + up + OFFSET
        t3 = t2 + wait + held
        t4 = t3 - OFFSET + down
        request = dict(seq=seq, length=40, flags=pr.PSH | pr.ACK)
        reply = dict(src=BROKER, dst=RECEIVER, sport=6379, dport=40000, seq=reply_seq,
                     length=300, flags=pr.PSH | pr.ACK)
        return ([segment(t1, **request), segment(t4, **reply)],
                [segment(t2, **request), segment(t3, **reply)])

    def test_the_transit_holds_no_clock_offset_and_no_wait_at_the_broker(self):
        receiver, broker = [], []
        for i in range(5):
            near, far = self.exchange(BASE + i * 10 * MS, 60 * US, (i + 1) * MS, 2 * MS, 70 * US,
                                      1000 + 40 * i, 5000 + 300 * i)
            receiver += near
            broker += far
        pairs = m0.exchanges(receiver, broker, 6379)
        assert len(pairs) == 5
        assert all((t2 - t1) + (t4 - t3) == 130 * US for t1, t2, t3, t4 in pairs)

    def test_a_request_the_broker_never_saw_and_one_with_no_reply_are_passed_over(self):
        near, far = self.exchange(BASE, 60 * US, MS, 0, 70 * US, 1000, 5000)
        lost = segment(BASE + 5 * MS, seq=1040, length=40)
        late = segment(BASE + 9 * MS, seq=1080, length=40)
        pairs = m0.exchanges(near + [lost, late], far + [dict(late, ns=late["ns"] + OFFSET)], 6379)
        assert len(pairs) == 1

    def test_the_data_connection_is_the_one_that_brought_the_most(self):
        small = segment(1, src=BROKER, dst=RECEIVER, sport=6379, dport=40001, length=10)
        big = segment(2, src=BROKER, dst=RECEIVER, sport=6379, dport=40000, length=500)
        other = segment(3, src=BROKER, dst=RECEIVER, sport=22, dport=40002, length=900)
        assert m0.data_flow([small, big, other], 6379) == ((RECEIVER, 40000), (BROKER, 6379))
        assert m0.data_flow([other], 6379) is None
        assert m0.exchanges([other], [], 6379) == []

    def test_a_packet_listed_twice_is_read_once(self):
        one = segment(BASE, length=40)
        again = dict(one, ns=BASE + 10 * US)
        later = dict(one, ns=BASE + 200 * US)
        assert len(m0._deduplicated([one, again, later])) == 2

    def test_kafka_fetches_are_tied_to_their_answers_by_the_correlation_id(self):
        def request(ns, api, corr, seq):
            body = struct.pack("!ihhi", 60, api, 11, corr) + b"\0" * 48
            return segment(ns, dport=9092, seq=seq, length=len(body), payload=body)

        def answer(ns, corr, size, seq, first=True, length=None):
            body = struct.pack("!ii", size, corr) if first else b"x" * 8
            return segment(ns, src=BROKER, dst=RECEIVER, sport=9092, dport=40000, seq=seq,
                           length=length or size + 4, payload=body)
        flow = ((RECEIVER, 40000), (BROKER, 9092))
        found = m0.kafka_fetches([
            request(BASE, 1, 7, 100), request(BASE + MS, 8, 8, 160),
            answer(BASE + 2 * MS, 8, 20, 900),
            answer(BASE + 3 * MS, 7, 2000, 924, length=1448),
            answer(BASE + 4 * MS, 7, 2000, 2372, first=False, length=556),
            segment(BASE + 5 * MS, src=BROKER, dst=RECEIVER, sport=9092, dport=40000, seq=2928,
                    length=4, payload=b"\0\0"),
            request(BASE + 6 * MS, 1, 9, 220)], flow)
        assert found == [(BASE, BASE + 4 * MS)], "the offset commit's answer is not a fetch's"


class TestHeldRequests:

    FLOW = ((RECEIVER, 40000), (BROKER, 6379))

    def run(self, ack_after_us, leave_after_ack_us, issued_before_ack=True):
        """An XACK leaves at 0; the broker's acknowledgement of it comes `ack_after_us` later;
        the next read leaves `leave_after_ack_us` after that."""
        ack_at = BASE + ack_after_us * US
        issued = ack_at - 20 * US if issued_before_ack else ack_at + 5 * US
        segs = [segment(BASE, seq=1000, length=30, payload=b"*4\r\n$4\r\nXACK"),
                segment(ack_at, src=BROKER, dst=RECEIVER, sport=6379, dport=40000, seq=1,
                        ack=1030),
                segment(ack_at + leave_after_ack_us * US, seq=1030, length=60,
                        payload=b"*6\r\n$10\r\nXREADGROUP")]
        return m0.held_requests(segs, self.FLOW, lambda seg: issued)

    def test_a_request_that_waited_for_the_acknowledgement_is_held(self):
        assert self.run(200, 10) == [(BASE + 210 * US, 30 * US)]

    def test_not_held_where_the_data_was_barely_outstanding_or_the_request_came_late(self):
        assert self.run(80, 10) == [], "acknowledged within 100 us: nothing was waiting on it"
        assert self.run(200, 60) == [], "left 60 us after: not released by it"
        assert self.run(200, 10, issued_before_ack=False) == []

    def test_sequence_numbers_that_wrap_are_still_covered(self):
        assert m0.covered(10, 20) and not m0.covered(20, 10)
        assert m0.covered((1 << 32) - 5, 3), "past the top of the circle"


class TestTheReplay:

    def test_a_message_that_finds_a_read_waiting_is_answered_at_once(self):
        """A read at 0 reaches the broker at 1; a message there at 5 goes back at 5, lands at
        5 + 1 + 2 held, and the next read leaves 3 after its stamp."""
        assert m0.replay([5], 0, 1, 1, 2, within=0, onward=3) == [8]

    def test_messages_waiting_at_the_broker_go_together_and_wait_their_turn(self):
        """Three messages already there when the read arrives at 1, one acknowledgement round
        trip (4) apart; a count of two sends the third with the next read."""
        stamped = m0.replay([0, 0, 0], 0, 1, 1, 2, within=4, onward=3, count=2)
        assert stamped[:2] == [4, 8]
        assert stamped[2] == 8 + 3 + 1 + 1 + 2, "the next read leaves at 11, answered at 12"

    def test_a_read_that_times_out_comes_back_empty_and_another_goes(self):
        """Nothing until 50. Reads reach the broker at 1, 18 and 35 and each waits 10 there and
        comes back empty 16 later; the fourth reaches it at 52, after the message, and takes it
        back at once."""
        assert m0.replay([50], 0, 1, 1, 2, within=0, onward=3, wait_ns=10) == [52 + 1 + 2]

    def test_kafka_sends_the_next_fetch_when_the_answer_lands(self):
        stamped = m0.replay([5, 5.5], 0, 1, 1, 2, within=0.1, onward=3,
                            next_after_last_stamp=False)
        assert stamped == [8, 8 + 3 + 1 + 1 + 2 + 0.0 - 0.0 + 0.0]


def m0_world(root, backend="redis", ack=1, rates=(0.0, 2.0, 8.0), grow=1.3, wake=(0.05, 1.3),
             recorded=True, rounds=2):
    """A small M0 campaign on disk: at each delay, `rounds` runs, recorded and not. Trips grow
    `grow` times the held delay, and the receiving thread's median wake-up wait goes from
    wake[0] ms at no delay to wake[1] ms at 8 ms."""
    runs = root / "m0_campaign" / "runs"
    runs.mkdir(parents=True)
    (root / "m0_campaign" / "COLLECTED.json").write_text(json.dumps({"profile": "matched"}),
                                                         encoding="utf-8")
    port = m0.PORTS[backend]
    for r in range(1, rounds + 1):
        for held in rates:
            for rec in ((True, False) if recorded else (False,)):
                key = "r%03d-M0-%s-l75%s-d%d-%s" % (r, backend,
                                                    "-ack%d" % ack if backend == "redis" else "",
                                                    held * 1000, "rec" if rec else "plain")
                where = runs / ("law_m0_x_" + key)
                where.mkdir()
                trip = 1.0 + grow * held + 0.01 * r
                (where / "queue_row.json").write_text(json.dumps(
                    {"key": key, "round": str(r), "setup": key[5:].rsplit("-", 1)[0],
                     "params": {"backend": backend, "block": "M0", "delay_ms": held,
                                "ack_batch": ack if backend == "redis" else None,
                                "load_pct": 75, "point": "d%d" % (held * 1000),
                                "plan": "football"}}), encoding="utf-8")
                (where / "integrity.json").write_text(json.dumps(
                    {"verdict": "count", "recorded": {"trip_median_ms": trip,
                                                      "gotit_median_ms": 0.8,
                                                      "measured_negative_rate": 0.01,
                                                      "delay_held_ms": held + 0.004}}),
                    encoding="utf-8")
                if rec:
                    write_recording(where, backend, port, held, wake[0] + (wake[1] - wake[0])
                                    * held / 8.0)
    return runs


def write_recording(where, backend, port, held, wake_ms, n=60, period_ms=1000.0):
    """One recorded run's files: a burst of two messages a second for a minute, each burst
    fetched by one read, the second message stamped one acknowledgement round trip after the
    first; the receiving thread woken for each answer."""
    sends, got, reads, events = [], [], [], []
    near, far = [], []
    up, down = 60 * US, 70 * US
    #: The loop issues each read as soon as it has acknowledged the last message of the one
    #: before, and the read waits at the broker for the next burst; the first read goes out
    #: half a second before the first burst.
    start = BASE - 500 * MS
    for i in range(n):
        send = BASE + int(i * period_ms * MS)
        at_broker = send + 400 * US
        t2 = start + up + OFFSET
        t3 = at_broker + OFFSET + int(held * MS)
        t4 = t3 - OFFSET + down
        stamp = t4 + int(wake_ms * MS) + 20 * US
        second = stamp + 130 * US + int(held * MS)
        sends += [(2 * i, send, send + 800 * US), (2 * i + 1, send, send + 801 * US)]
        got += [(2 * i, stamp), (2 * i + 1, second)]
        reads.append((start, stamp - start, 2))
        issued, start = start, second + 150 * US + int(held * MS)
        body = (b"*6\r\n$10\r\nXREADGROUP" if backend == "redis"
                else struct.pack("!ihhi", 60, 1, 11, i) + b"\0" * 20)
        near += [(issued, packet(body, dport=port, seq=1000 + 100 * i)),
                 (t4, packet(struct.pack("!ii", 40, i) + b"\0" * 40, src=BROKER, dst=RECEIVER,
                             sport=port, dport=40000, seq=9000 + 44 * i))]
        far += [(t2, packet(body, dport=port, seq=1000 + 100 * i)),
                (t3, packet(struct.pack("!ii", 40, i) + b"\0" * 40, src=BROKER, dst=RECEIVER,
                            sport=port, dport=40000, seq=9000 + 44 * i))]
        mono = t4 - BASE + 10 ** 12
        events += [(mono - 5 * MS, "S"), (mono, "W"), (mono + int(wake_ms * MS), "R")]
    capture(where / "receiver.pcap", 276, near)
    capture(where / "broker.pcap", 1, far)
    (where / "producer.csv").write_text(
        "run_id,backend,event_id,t_prod_send_ns,t_broker_ack_ns\n" + "".join(
            "r,%s,e%d,%d,%d\n" % (backend, i, s, a) for i, s, a in sends), encoding="utf-8")
    (where / "consumer_events.csv").write_text(
        "run_id,backend,event_id,t_consume_ns\n" + "".join(
            "r,%s,e%d,%d\n" % (backend, i, t) for i, t in got), encoding="utf-8")
    (where / "consumer_readtrace.csv").write_text(
        "t_read_start_ns,read_duration_ns,n_messages\n" + "".join(
            "%d,%d,%d\n" % row for row in reads), encoding="utf-8")
    (where / "consumer.log").write_text(
        "CONFIG effective ack_batch=1 count=100 block_ms=1000 cluster=False client=python\n",
        encoding="utf-8")
    clocks = [{"realtime_ns": BASE - 5 * 10 ** 9, "monotonic_ns": 10 ** 12 - 5 * 10 ** 9},
              {"realtime_ns": BASE + 70 * 10 ** 9, "monotonic_ns": 10 ** 12 + 70 * 10 ** 9}]
    (where / "producer_threads.json").write_text(json.dumps(
        {"pid": 1, "roles": {"stamps_ack": [11]}, "clocks": clocks}), encoding="utf-8")
    (where / "consumer_threads.json").write_text(json.dumps(
        {"pid": 2, "roles": {"stamps_receive": [21]}, "clocks": clocks}), encoding="utf-8")
    (where / "waits.txt").write_text("Attaching 2 probes...\n" + "".join(
        "%s 21 %d\n" % (kind, ns) for ns, kind in sorted(events)), encoding="utf-8")


class TestWhatARunCannotSay:
    """Each reading says None, or nothing, where its run does not carry what it reads."""

    def held_run(self, tmp_path):
        """A Redis run whose next read, issued at 150 us, left at 210 us: 10 us after the broker
        acknowledged an XACK that had been outstanding 200 us."""
        where = tmp_path / "run"
        where.mkdir()
        t = BASE + 40 * 10 ** 9
        capture(where / "receiver.pcap", 276, [
            (t, packet(b"*4\r\n$4\r\nXACK", seq=1000)),
            (t + 200 * US, packet(src=BROKER, dst=RECEIVER, sport=6379, dport=40000, seq=1,
                                  ack=1000 + 12, flags=pr.ACK)),
            (t + 210 * US, packet(b"*6\r\n$10\r\nXREADGROUP", seq=1012)),
            (t + 300 * US, packet(b"*1\r\n", src=BROKER, dst=RECEIVER, sport=6379,
                                  dport=40000, seq=1, ack=1031)),
            (t + 400 * US, packet(b"PING", seq=1031)),
            (t + 600 * US, packet(src=BROKER, dst=RECEIVER, sport=6379, dport=40000, seq=5,
                                  ack=1035, flags=pr.ACK)),
            (t + 610 * US, packet(b"*2\r\n$4\r\nXACK", seq=1035))])
        (where / "producer.csv").write_text(
            "event_id,t_prod_send_ns,t_broker_ack_ns\ne0,%d,%d\ne1,%d,%d\n"
            % (BASE, BASE + MS, t, t + MS), encoding="utf-8")
        (where / "consumer_events.csv").write_text(
            "event_id,t_consume_ns\ne0,%d\ne1,%d\n" % (BASE + 2 * MS, t + 590 * US),
            encoding="utf-8")
        (where / "consumer_readtrace.csv").write_text(
            "t_read_start_ns,read_duration_ns,n_messages\n%d,1,1\n%d,1,1\n"
            % (BASE, t + 150 * US), encoding="utf-8")
        return {"run_dir": str(where), "backend": "redis"}

    def test_a_request_issued_before_the_acknowledgement_that_released_it_was_held(self, tmp_path):
        """The read (issued 150, left 210, released at 200) held 60 us; the XACK after the stamp
        at 590 left at 610, 10 us after the acknowledgement at 600 released the PING before it:
        held 20 us. The PING's own reply came 90 us after it, too soon to have held anything.
        One message was sent after the warm-up, so the hold per measured message is all 80 us."""
        per_message, count = m0.held_per_message_ms(self.held_run(tmp_path))
        assert count == 2 and per_message == pytest.approx(0.060 + 0.020)

    def test_a_run_with_no_capture_no_data_connection_or_no_message_says_so(self, tmp_path):
        run = self.held_run(tmp_path)
        assert m0.held_per_message_ms(dict(run, backend="kafka")) == (None, 0)
        (tmp_path / "run" / "producer.csv").write_text("event_id,t_prod_send_ns\n",
                                                       encoding="utf-8")
        assert m0.held_per_message_ms(run) == (None, 0)
        capture(tmp_path / "run" / "receiver.pcap", 276, [(BASE, packet(b"x", sport=22,
                                                                         dport=40000))])
        assert m0.held_per_message_ms(run) == (None, 0)
        (tmp_path / "run" / "receiver.pcap").unlink()
        assert m0.held_per_message_ms(run) == (None, 0)
        assert m0.transit_ms(dict(run, backend="redis")) is None

    def test_the_loop_logs_that_do_not_add_up_are_not_read(self, tmp_path):
        run_dir = self.held_run(tmp_path)["run_dir"]
        with open(os.path.join(run_dir, "consumer_readtrace.csv"), "a", encoding="utf-8") as fh:
            fh.write("%d,1,5\n" % (BASE + 50 * 10 ** 9))
        assert m0.loop_costs(run_dir) == (None, None)
        os.remove(os.path.join(run_dir, "consumer_readtrace.csv"))
        assert m0.read_cycle(run_dir) == [] and m0.loop_costs(run_dir) == (None, None)
        with pytest.raises(ValueError, match="did not print its settings"):
            m0.redis_config(run_dir if os.path.exists(os.path.join(run_dir, "consumer.log"))
                            else (open(os.path.join(run_dir, "consumer.log"), "w").close()
                                  or run_dir))

    def test_a_wake_up_reading_needs_the_events_and_both_records(self, tmp_path):
        runs = m0.m0_runs(str(m0_world(tmp_path, rounds=1)))
        recorded = [run for run in runs if run["recorded"]][0]
        assert m0.receiving_wake_ms(recorded) is not None
        with open(os.path.join(recorded["run_dir"], "waits.txt"), "a", encoding="utf-8") as fh:
            fh.write("Lost 3 events\n")
        assert m0.receiving_wake_ms(recorded) is None
        os.remove(os.path.join(recorded["run_dir"], "waits.txt"))
        assert m0.receiving_wake_ms(recorded) is None

    def test_only_m0_runs_are_read_and_bare_acknowledgements_pass_through(self, tmp_path):
        runs_folder = m0_world(tmp_path, rounds=1)
        other = runs_folder / "law_a9_x"
        other.mkdir()
        (other / "queue_row.json").write_text(json.dumps(
            {"key": "k", "round": "1", "setup": "A9-kafka-l75-s3000-p09s",
             "params": {"backend": "kafka"}}), encoding="utf-8")
        (other / "integrity.json").write_text(json.dumps(
            {"verdict": "count", "recorded": {"trip_median_ms": 1.0,
                                              "measured_negative_rate": 0.1}}), encoding="utf-8")
        assert all(run["setup"].startswith("M0-") for run in m0.m0_runs(str(runs_folder)))
        flow = ((RECEIVER, 40000), (BROKER, 9092))
        bare = [segment(BASE, dport=9092), segment(BASE, src=BROKER, dst=RECEIVER, sport=9092,
                                                    dport=40000)]
        assert m0.kafka_fetches(bare, flow) == []
        assert m0.held_requests([segment(BASE), segment(BASE, src=BROKER, dst=RECEIVER,
                                                         sport=6379, dport=40000, flags=0)],
                                ((RECEIVER, 40000), (BROKER, 6379)), lambda seg: 0) == []


class TestTheWholeReading:

    def test_it_reads_each_explanation_and_says_which_hold(self, tmp_path):
        runs = m0.m0_runs(str(m0_world(tmp_path)))
        assert len(runs) == 12 and sum(1 for run in runs if run["recorded"]) == 6
        found = m0.judge(runs, draws=40)
        part = found["parts"]["redis ack 1"]
        assert part["departure"]["slope"] == pytest.approx(1.3, abs=1e-3)
        assert part["departure"]["departure_ms"] == pytest.approx(2.4, abs=0.01)
        shift = part["M-H1"]["arrival_shift_ms"]
        assert shift["8"] == pytest.approx(8.004) and part["M-H1"]["kept"] is False
        assert part["M-H3"]["contribution_ms"] == pytest.approx(1.25, abs=1e-6)
        assert part["M-H3"]["kept"] is True
        assert part["M-H4"]["held_requests"] == 0 and part["M-H4"]["kept"] is False
        assert part["M-H2"]["tested"] is True and part["M-H2"]["replayed_slope"] is not None
        assert part["M-H2"]["loop_costs_ns"]["within"] == 130 * US
        # Each read carries a burst of two; the second is stamped one acknowledgement round trip
        # after the first, and that round trip carries the delay: the median trip of the pair
        # grows 1.5 times the delay, against the 1.3 the runs measured.
        assert part["M-H2"]["replayed_slope"] == pytest.approx(1.5, abs=0.01)
        assert part["M-H2"]["kept"] is False
        assert part["recording_effect"]["log_stays_on"] is True
        text = "\n".join(m0.lines(found))
        assert "redis ack 1: slope 1.3" in text and "M-H3: kept" in text

    def test_kafka_is_read_too_and_its_held_requests_are_not_tested(self, tmp_path):
        found = m0.judge(m0.m0_runs(str(m0_world(tmp_path, backend="kafka"))), draws=20)
        part = found["parts"]["kafka"]
        assert part["M-H4"]["tested"] is False
        assert "M-H4: not tested" in "\n".join(m0.lines(found))
        assert part["M-H2"]["loop_costs_ns"]["onward"] is not None

    def test_the_command_writes_the_answer_and_says_what_went_wrong(self, tmp_path):
        folder = str(m0_world(tmp_path, rounds=1))
        out, where = io.StringIO(), str(tmp_path / "m0.json")
        assert m0.main(["--runs", folder, "--draws", "10", "--out", where], out=out) == 0
        assert m0.main(["--runs", folder, "--draws", "10"], out=io.StringIO()) == 0
        assert json.load(open(where, encoding="utf-8"))["at_ms"] == 8.0
        empty = tmp_path / "none" / "runs"
        empty.mkdir(parents=True)
        assert m0.main(["--runs", str(empty)], out=out) == 2

    def test_a_loop_that_never_carried_two_messages_leaves_m_h2_untested(self, tmp_path,
                                                                           monkeypatch):
        monkeypatch.setattr(m0, "loop_costs", lambda run_dir: (None, 5 * MS))
        found = m0.judge(m0.m0_runs(str(m0_world(tmp_path, rounds=1))), draws=10)
        said = found["parts"]["redis ack 1"]["M-H2"]
        assert said["tested"] is False and said["kept"] is False
        assert "M-H2: not tested" in "\n".join(m0.lines(found))
