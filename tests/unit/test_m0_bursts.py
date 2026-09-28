"""Tests for scripts/m0_bursts.py: M0 read message by message, on made-up campaigns whose bursts
and delays are chosen so that every number can be worked out by hand."""
import csv
import json
import os
import statistics
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import m0_bursts as mb  # noqa: E402
import m0_read  # noqa: E402

MS = 1000000
BASE = 1790000000 * 1000 * MS


def write_run(where, backend, ack, delay, messages, recorded=False):
    """One M0 run on disk. `messages` is [(sched_ms, send_ms, trip_ms, redis_seq)], times from the
    run's start; a redis_seq of None leaves the stream id empty, as Kafka's rows are."""
    where.mkdir(parents=True)
    key = where.name.split("law_m0_x_")[1]
    trips = [trip for _, send, trip, _ in messages if send >= 30000]
    (where / "queue_row.json").write_text(json.dumps(
        {"key": key, "round": key[1:4], "setup": key[5:].rsplit("-", 1)[0],
         "params": {"backend": backend, "block": "M0", "delay_ms": delay,
                    "ack_batch": ack if backend == "redis" else None, "load_pct": 75,
                    "point": "d%d" % (delay * 1000), "plan": "football"}}), encoding="utf-8")
    (where / "integrity.json").write_text(json.dumps(
        {"verdict": "count", "recorded": {"trip_median_ms": statistics.median(trips),
                                          "gotit_median_ms": 1.0,
                                          "measured_negative_rate": 0.0,
                                          "delay_held_ms": delay + 0.01}}), encoding="utf-8")
    with open(where / "producer.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["event_id", "t_prod_sched_ns", "t_prod_send_ns", "redis_id"])
        for i, (sched, send, _, seq) in enumerate(messages):
            w.writerow(["e%d" % i, BASE + sched * MS, BASE + int(send * MS),
                        "" if seq is None else "%d-%d" % (BASE // MS + sched, seq)])
        w.writerow(["unsent", BASE, "", ""])
    with open(where / "consumer_events.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["event_id", "t_consume_ns"])
        for i, (_, send, trip, _) in enumerate(messages):
            if i != 1:  # the second message of the run never arrives
                w.writerow(["e%d" % i, BASE + int((send + trip) * MS)])
        w.writerow(["stray", ""])
    (where / "consumer.log").write_text("CONFIG effective ack_batch=%d count=200 block_ms=1000\n"
                                        % (ack or 1), encoding="utf-8")
    if recorded:
        #: A capture with nothing in it: the run recorded, and its packets are not read here.
        (where / "receiver.pcap").write_bytes(struct.pack("<IHHiIII", 0xa1b23c4d, 2, 4, 0, 0,
                                                          200, 1))


def burst_messages(backend, ack, delay, spread=0.0, bursts=60):
    """A burst every second: one alone, then a leader with one follower, in turn -- so two in
    three measured messages lead. A leader takes 1.0, 1.1, 1.2 or 1.3 ms plus the delay; a
    follower 1.05 ms plus its own growth times the delay, so at no delay the followers sit among
    the leaders and at any delay above them. The 30 bursts past the warm-up hold seven leaders at
    1.0 and at 1.1 ms, eight at 1.2 and at 1.3, and fifteen followers."""
    k = mb.growth(backend, ack, 1)
    out = []
    for b in range(bursts):
        sched = b * 1000
        lead = 1.0 + 0.1 * (b % 4) + spread + delay
        out.append((sched, sched + 0.5, lead, 0 if backend == "redis" else None))
        if b % 2:
            out.append((sched, sched + 0.4, 1.05 + spread + k * delay,
                        1 if backend == "redis" else None))
    return out


def campaign(root, backend="redis", ack=200, rounds=2, spread_recorded=0.5):
    runs = root / "m0" / "runs"
    for r in range(1, rounds + 1):
        for delay in mb.DELAYS:
            for rec in (True, False):
                part = "%s-l75%s" % (backend, "-ack%d" % ack if backend == "redis" else "")
                key = "r%03d-M0-%s-d%d-%s" % (r, part, delay * 1000, "rec" if rec else "plain")
                write_run(runs / ("law_m0_x_" + key), backend, ack, delay,
                          burst_messages(backend, ack, delay,
                                         spread=spread_recorded if rec else 0.0),
                          recorded=rec)
    (root / "m0" / "COLLECTED.json").write_text(json.dumps({"profile": "matched"}),
                                                encoding="utf-8")
    return root / "m0"


class TestBursts:

    def test_a_burst_is_led_by_the_message_the_broker_took_first(self, tmp_path):
        where = tmp_path / "runs" / "law_m0_x_r001-M0-redis-l75-ack200-d0-rec"
        #: Two messages of one second; the second was sent first but the broker added it later.
        write_run(where, "redis", 200, 0.0, [(0, 0.0, 1.0, 0), (0, 0.1, 1.0, 0),
                                             (40000, 40000.2, 3.0, 1),
                                             (40000, 40000.1, 5.0, 0)])
        assert sorted(mb.bursts(str(where))) == [(3.0, 1), (5.0, 0)]

    def test_kafka_orders_a_burst_by_when_its_messages_were_sent(self, tmp_path):
        where = tmp_path / "runs" / "law_m0_x_r001-M0-kafka-l75-d0-rec"
        write_run(where, "kafka", None, 0.0, [(0, 0.0, 1.0, None), (0, 0.1, 1.0, None),
                                              (40000, 40000.2, 3.0, None),
                                              (40000, 40000.1, 5.0, None)])
        assert sorted(mb.bursts(str(where))) == [(3.0, 1), (5.0, 0)]

    def test_a_malformed_stream_id_falls_back_to_the_send(self):
        row = {"redis_id": "x-y", "t_prod_send_ns": "7"}
        assert mb._broker_order(row) == (7, 0)
        assert mb._broker_order(dict(row, redis_id="12-3")) == (12, 3)

    def test_a_run_that_sent_nothing_has_no_messages(self, tmp_path):
        where = tmp_path / "empty"
        where.mkdir()
        (where / "producer.csv").write_text("event_id,t_prod_sched_ns,t_prod_send_ns\n",
                                            encoding="utf-8")
        (where / "consumer_events.csv").write_text("event_id,t_consume_ns\n", encoding="utf-8")
        assert mb.bursts(str(where)) == []

    @pytest.mark.parametrize("backend,ack,rank,k", [
        ("kafka", None, 0, 1), ("kafka", None, 3, 1), ("redis", 200, 0, 1), ("redis", 200, 1, 2),
        ("redis", 200, 4, 2), ("redis", 1, 0, 1), ("redis", 1, 1, 3), ("redis", 1, 3, 5)])
    def test_the_growth_follows_the_loop(self, backend, ack, rank, k):
        assert mb.growth(backend, ack, rank) == k


class TestTheReading:

    def read(self, tmp_path, **kw):
        runs = m0_read.m0_runs(str(campaign(tmp_path, **kw)))
        return mb.read(runs)

    def test_each_rank_grows_by_its_own_rule(self, tmp_path):
        found = self.read(tmp_path, ack=1)
        rows = dict(((r["delay_ms"], r["rank"]), r) for r in found["by_rank"])
        assert rows[(0.0, 0)]["growth_per_ms"] is None
        assert rows[(8.0, 0)]["growth_per_ms"] == pytest.approx(1.0)
        assert rows[(8.0, 1)]["growth_per_ms"] == pytest.approx(3.0), "1.3 ms to 25.3 ms"
        assert rows[(8.0, 1)]["rule"] == 3
        assert rows[(2.0, 1)]["messages"] == 2 * 2 * 15

    def test_the_prediction_from_no_delay_meets_the_measured_slope(self, tmp_path):
        """A run's 23rd of 45 trips is its median. At no delay that is 1.1 ms, among the
        followers at 1.05; at 2 and 8 ms every follower has moved above every leader, and the
        23rd is the fastest of the eight leaders at 1.3 -- 3.3 and 9.3 ms. The line through
        1.1, 3.3 and 9.3 at 0, 2 and 8 has a slope of 53/52, and the prediction, built from the
        zero-delay runs alone, meets the runs' own medians."""
        part = self.read(tmp_path)["parts"]["redis ack 200"]
        assert part["leaders_share"] == pytest.approx(2.0 / 3.0)
        assert part["slope"]["predicted"] == pytest.approx(53.0 / 52.0)
        assert part["slope"]["all"] == pytest.approx(53.0 / 52.0)
        assert part["slope"]["recorded"] == pytest.approx(53.0 / 52.0)
        assert part["median_trip_ms"]["predicted"] == pytest.approx(
            {"0": 1.35, "2": 3.55, "8": 9.55})
        assert part["median_trip_ms"]["measured"] == pytest.approx(
            part["median_trip_ms"]["predicted"])

    def test_the_step_is_the_leaders_quantile_above_the_median(self, tmp_path):
        """All zero-delay messages together: 120 leaders (the recorded ones half a millisecond
        slower) and 60 followers. Their median is 1.4 ms, between the fastest recorded leaders
        at 1.5 and the slowest unrecorded ones at 1.3; the leaders' 3/4 quantile is 1.7 ms."""
        part = self.read(tmp_path)["parts"]["redis ack 200"]
        assert part["step"] == pytest.approx({"share": 2.0 / 3.0, "quantile": 1.7,
                                              "median": 1.4, "step_ms": 0.3})

    def test_kafka_has_no_step_and_no_replay(self, tmp_path):
        part = self.read(tmp_path, backend="kafka", ack=None)["parts"]["kafka"]
        assert part["step"]["step_ms"] is None and part["replay"] == []

    def test_the_recording_moves_the_leaders_tail_by_what_it_added(self, tmp_path):
        part = self.read(tmp_path)["parts"]["redis ack 200"]
        at8 = part["recording"]["8"]
        assert at8["leaders_median_ms"] == pytest.approx(0.5)
        assert at8["leaders_quantile_ms"] == pytest.approx(0.5)

    def test_a_delay_without_both_halves_is_not_compared(self):
        runs = [{"set_ms": 0.0, "recorded": True, "messages": [(1.0, 0)]}]
        assert mb.recording(runs, 0.6)["0"] is None
        both = runs + [{"set_ms": 0.0, "recorded": False, "messages": [(1.0, 0)]}]
        assert mb.recording(both, None)["0"] is None
        assert mb.recording(both, 0.5)["0"] is None
        assert mb.recording(both, 0.6)["0"]["median_ms"] == 0.0

    def test_a_step_needs_the_leaders_to_be_more_than_half(self):
        runs = [{"set_ms": 0.0, "backend": "redis", "ack_batch": 200,
                 "messages": [(1.0, 0), (2.0, 1)]}]
        assert mb.step(runs)["step_ms"] is None
        assert mb.leaders_share([{"messages": []}]) is None
        assert mb.step([dict(runs[0], set_ms=2.0, messages=[(1.0, 0)])])["step_ms"] is None

    def test_a_run_without_messages_adds_no_predicted_point(self):
        run = {"backend": "redis", "ack_batch": 1, "messages": []}
        assert mb.predicted_medians([run]) == []
        assert mb._slope([(0.0, 1.0), (0.0, 1.2)]) is None
        assert mb._mean_by_delay([(0.0, 1.0)]) == {"0": 1.0}
        assert mb.at([{"set_ms": None}], 0.0) == []


class TestTheFrozenReplay:

    def run(self, tmp_path, batch=1, block=1000):
        where = tmp_path / "r"
        where.mkdir(exist_ok=True)
        (where / "consumer.log").write_text(
            "CONFIG effective ack_batch=%d count=200 block_ms=%d\n" % (batch, block),
            encoding="utf-8")
        return {"run": "r", "run_dir": str(where), "held_ms": 8.0, "gotit_ms": 1.0,
                "set_ms": 8.0}

    def patch(self, monkeypatch, sends, transit=0.5):
        monkeypatch.setattr(m0_read, "sends", lambda d: sends)
        monkeypatch.setattr(m0_read, "read_cycle", lambda d: [(BASE - 10 * MS, 0, 0)])
        monkeypatch.setattr(m0_read, "transit_ms", lambda run: transit)

    def test_every_leader_gets_the_same_trip(self, tmp_path, monkeypatch):
        """A leader a second for a minute, and a follower a microsecond behind it every other
        second. The replay finds a read waiting for every leader and answers it at once: half
        its got-it (0.5 ms), half the transit up and down (0.25 ms) and the 8 ms held, 8.75 ms
        each. Past the warm-up, 30 leaders and 15 followers: the median is a leader's trip."""
        sends = sorted([BASE + b * 1000 * MS for b in range(60)]
                       + [BASE + b * 1000 * MS + 1000 for b in range(1, 60, 2)])
        self.patch(monkeypatch, sends)
        run = self.run(tmp_path)
        trips = mb.replayed_trips(run, {"within": 0.6 * MS, "onward": 0.7 * MS})
        #: The replay works in floating-point nanoseconds since 1970, which at 1.79e18 are
        #: spaced 256 ns apart, so a leader's 8.75 ms comes out within a few hundred ns of it.
        leader = min(trips)
        assert leader == pytest.approx(8.75, abs=0.001)
        assert len(trips) == 45 and trips.count(leader) == 30
        assert statistics.median(trips) == leader and max(trips) > 17.0
        monkeypatch.setattr(m0_read, "zero_costs", lambda runs: {"within": 0.6 * MS,
                                                                 "onward": 0.7 * MS})
        rows = mb.replay_pinned([run])
        #: A follower waits for the leader's answer, its acknowledgement (0.7 + 8 ms), the read
        #: going up (0.25) and its own answer (8.25): 25.95 ms, less the microsecond it was late.
        assert rows == [{"run": "r", "delay_ms": 8.0, "at_smallest": pytest.approx(2.0 / 3.0),
                         "median_is_smallest": True,
                         "others_median_ms": pytest.approx(25.949, abs=0.001)}]

    def test_a_replay_of_leaders_alone_has_no_other_trip(self, tmp_path, monkeypatch):
        self.patch(monkeypatch, [BASE + b * 1000 * MS for b in range(60)])
        monkeypatch.setattr(m0_read, "zero_costs", lambda runs: {"within": 0.6 * MS,
                                                                 "onward": 0.7 * MS})
        rows = mb.replay_pinned([self.run(tmp_path)])
        assert rows[0]["at_smallest"] == 1.0 and rows[0]["others_median_ms"] is None

    def test_batches_and_a_read_that_does_not_block(self, tmp_path, monkeypatch):
        sends = [BASE, BASE + 30000 * MS, BASE + 30000 * MS + 1000]
        self.patch(monkeypatch, sends)
        trips = mb.replayed_trips(self.run(tmp_path, batch=200, block=0),
                                  {"within": 0.1 * MS, "onward": 0.1 * MS})
        assert len(trips) == 2 and trips[1] > trips[0]

    def test_what_the_replay_cannot_read(self, tmp_path, monkeypatch):
        run = self.run(tmp_path)
        costs = {"within": 1.0, "onward": 1.0}
        self.patch(monkeypatch, [])
        assert mb.replayed_trips(run, costs) is None
        self.patch(monkeypatch, [BASE], transit=None)
        assert mb.replayed_trips(run, costs) is None
        self.patch(monkeypatch, [BASE])
        assert mb.replayed_trips(run, {"within": None, "onward": 1.0}) is None
        monkeypatch.setattr(m0_read, "read_cycle", lambda d: [])
        assert mb.replayed_trips(run, costs) is None
        monkeypatch.setattr(m0_read, "zero_costs", lambda runs: {"within": None, "onward": None})
        assert mb.replay_pinned([run]) == []


class TestTheCommand:

    def test_it_writes_the_table_and_the_parts(self, tmp_path, capsys):
        folder = campaign(tmp_path, ack=1)
        out = tmp_path / "out"
        assert mb.main(["--runs", str(folder), "--out", str(out)]) == 0
        said = capsys.readouterr().out
        assert "redis ack 1: leaders 0.667" in said and "settles" in said
        rows = list(csv.DictReader(open(out / "m0_by_rank.csv", encoding="utf-8")))
        assert rows[0]["part"] == "redis ack 1" and rows[0]["growth_per_ms"] == ""
        parts = json.loads((out / "m0_bursts.json").read_text(encoding="utf-8"))
        assert parts["redis ack 1"]["replay"] == []

    def test_kafka_says_no_step_and_no_replay(self, tmp_path, capsys):
        folder = campaign(tmp_path, backend="kafka", ack=None)
        assert mb.main(["--runs", str(folder)]) == 0
        said = capsys.readouterr().out
        assert "kafka: leaders" in said and "settles" not in said and "replay" not in said

    def test_the_replay_line_is_printed_where_there_is_one(self):
        found = {"parts": {"redis ack 1": {
            "leaders_share": 0.6, "step": {"step_ms": None},
            "slope": {"all": 1.1, "recorded": 1.2, "unrecorded": 1.0, "predicted": 1.1},
            "replay": [{"median_is_smallest": True}, {"median_is_smallest": False}]}}}
        assert mb.lines(found)[-1].endswith("in 1 of 2 recorded runs")
        assert mb._r(None) is None

    def test_an_empty_folder_is_an_error(self, tmp_path, capsys):
        (tmp_path / "runs").mkdir()
        assert mb.main(["--runs", str(tmp_path / "runs")]) == 2
        assert "ERROR: no counted M0 run" in capsys.readouterr().out
