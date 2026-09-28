"""Tests for scripts/pause_census.py: pauses gathered into episodes and read against the producer,
the sampler, the broker's log and the driver's disk, on made-up runs laid out as the final
campaigns are: <pair>/<campaign>/runs/<run>, with the campaign's quality report beside its runs."""
import csv
import datetime
import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import pause_census as pc  # noqa: E402

MS = 1000000
S = 1000 * MS
#: 28 September 2026, 10:00:00 UTC, in ns: a quarter past is minute 15.
BASE = int(datetime.datetime(2026, 9, 28, 10, 0, 0,
                             tzinfo=datetime.timezone.utc).timestamp()) * S


def write_run(where, trips, acks=None, lags=None, sampler=None, iowait=(0, 0), broker_log="",
              reads=None, events=True):
    """A run of one message every 20 ms for a minute, each with the trip given for it (ms, by
    index; 1 ms otherwise), a got-it of 1 ms unless `acks` says otherwise, and sent on time
    unless `lags` says otherwise."""
    where.mkdir(parents=True)
    (where / "queue_row.json").write_text("{}", encoding="utf-8")
    acks, lags = acks or {}, lags or {}
    rows, arrivals = [], []
    for i in range(3000):
        send = BASE + i * 20 * MS + int(lags.get(i, 0.0) * MS)
        rows.append(["e%d" % i, BASE + i * 20 * MS, send, send + int(acks.get(i, 1.0) * MS)])
        arrivals.append(["e%d" % i, send + int(trips.get(i, 1.0) * MS)])
    rows.append(["unsent", BASE, "", ""])
    with open(where / "producer.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["event_id", "t_prod_sched_ns", "t_prod_send_ns", "t_broker_ack_ns"])
        w.writerows(rows)
    name, stamp = ("consumer_events.csv", "t_consume_ns") if events else \
        ("consumer.csv", "t_cons_recv_ns")
    with open(where / name, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["event_id", stamp])
        w.writerows(arrivals + [["lost", ""]])
    (where / "stat_before.txt").write_text("cpu  1 2 3 4 %d 6 7 0\n" % iowait[0], encoding="utf-8")
    (where / "stat_after.txt").write_text("cpu  1 2 3 4 %d 6 7 0\n" % iowait[1], encoding="utf-8")
    if sampler is not None:
        (where / "utilisation.csv").write_text(
            "t_wall,rho,loadavg\n" + "".join("%.3f,0.75,5\n" % (t / 1e9) for t in sampler)
            + ",,\n", encoding="utf-8")
    if broker_log:
        (where / "broker_log.txt").write_text(broker_log, encoding="utf-8")
    if reads is not None:
        (where / "consumer_readtrace.csv").write_text(
            "t_read_start_ns,read_duration_ns,n_messages\n"
            + "".join("%d,%d,1\n" % r for r in reads), encoding="utf-8")


def pause(start_index, seconds):
    """Trips for messages held by one pause: sent from `start_index` on, all released together
    `seconds` after the first of them was sent."""
    release = start_index * 20 + seconds * 1000
    return dict((i, release - i * 20) for i in range(start_index, 3000)
                if i * 20 < release - 150)


def sampler_lines(gap_from=None, gap_s=0.0):
    """The sampler's line every half second, with one gap of `gap_s` beginning at `gap_from` ns."""
    out, t = [], BASE
    while t < BASE + 61 * S:
        out.append(t)
        t += S // 2 if gap_from is None or not gap_from <= t < gap_from + S // 2 else \
            int(gap_s * S)
    return out


def quality(campaign, runs):
    campaign.mkdir(parents=True, exist_ok=True)
    (campaign / "quality_report.json").write_text(json.dumps({"runs": [
        {"run": name, "backend": backend, "stalls": stalls} for name, backend, stalls in runs]}),
        encoding="utf-8")


class TestOneRun:

    def test_a_pause_is_one_episode_and_its_producer_is_read_over_it(self, tmp_path):
        where = tmp_path / "r"
        write_run(where, pause(2000, 3), acks={2010: 2.0}, lags={2005: 0.5})
        eps = pc.episodes(pc.messages(str(where)))
        assert len(eps) == 1
        ep = eps[0]
        assert ep["start"] == BASE + 2000 * 20 * MS and ep["worst_ms"] == pytest.approx(3000)
        assert ep["late"] == len(pause(2000, 3))
        assert ep["max_gotit_ms"] == pytest.approx(2.0) and ep["max_lag_ms"] == pytest.approx(0.5)
        assert pc.kind(ep) == "receiver"

    def test_two_pauses_a_second_apart_are_two_episodes(self, tmp_path):
        trips = pause(1600, 1)
        trips.update(pause(2500, 2))
        where = tmp_path / "r"
        write_run(where, trips, events=False)
        assert [round(ep["worst_ms"]) for ep in pc.episodes(pc.messages(str(where)))] == \
            [1000, 2000]

    def test_nothing_late_before_the_warm_up_ends(self, tmp_path):
        where = tmp_path / "r"
        write_run(where, pause(100, 5))
        assert pc.episodes(pc.messages(str(where))) == []
        assert pc.episodes([]) == []

    def test_a_run_with_no_schedule_or_acknowledgement_leaves_them_unknown(self):
        sent = [{"send": 0, "sched": None, "ack": None, "arrival": 0},
                {"send": 31 * S, "sched": None, "ack": None, "arrival": 32 * S}]
        ep = pc.episodes(sent)[0]
        assert ep["max_lag_ms"] is None and ep["max_gotit_ms"] is None
        assert pc.kind(ep) == "receiver"

    @pytest.mark.parametrize("gotit,kind", [(600.0, "broker"), (500.0, "broker"),
                                            (149.0, "receiver"), (300.0, "both")])
    def test_the_kind_follows_how_long_the_acknowledgements_were_held(self, gotit, kind):
        assert pc.kind({"max_gotit_ms": gotit, "worst_ms": 1000.0}) == kind

    def test_the_sampler_gap_across_an_episode(self, tmp_path):
        where = tmp_path / "r"
        write_run(where, {}, sampler=sampler_lines(gap_from=BASE + 40 * S, gap_s=3.0))
        assert pc.sampler_gap_s(str(where), BASE + 40 * S, BASE + 42 * S) == pytest.approx(3.0)
        assert pc.sampler_gap_s(str(where), BASE + 10 * S, BASE + 11 * S) == pytest.approx(0.5)
        assert pc.sampler_gap_s(str(where), BASE + 100 * S, BASE + 101 * S) is None
        assert pc.sampler_gap_s(str(tmp_path), 0, 1) is None

    def test_the_disk_wait_is_read_from_the_cpu_line(self, tmp_path):
        where = tmp_path / "r"
        write_run(where, {}, iowait=(500, 820))
        assert pc.iowait_s(str(where)) == pytest.approx(3.2)
        assert pc.iowait_s(str(tmp_path)) is None
        (where / "stat_after.txt").write_text("cpu  1 2\n", encoding="utf-8")
        assert pc.iowait_s(str(where)) is None

    def test_a_heartbeat_the_broker_could_not_send_is_found_in_its_window(self, tmp_path):
        where = tmp_path / "r"
        log = ("2026-09-28T10:00:41.500000000Z [x] INFO Unable to send a heartbeat because "
               "the RPC got timed out\n"
               "2026-09-28T10:00:50Z [x] INFO Disconnecting from node 1 due to request timeout\n"
               "a line without a time\n")
        write_run(where, {}, broker_log=log)
        assert pc.heartbeat_lost(str(where), BASE + 41 * S, BASE + 42 * S) is True
        assert pc.heartbeat_lost(str(where), BASE + 49 * S, BASE + 49 * S + 100) is True
        assert pc.heartbeat_lost(str(where), BASE + 30 * S, BASE + 35 * S) is False
        assert pc.heartbeat_lost(str(tmp_path), 0, 1) is False

    def test_the_share_of_a_pause_spent_inside_a_read(self, tmp_path):
        where = tmp_path / "r"
        write_run(where, {}, reads=[(BASE + 40 * S, 250 * MS), (BASE + 41 * S, 5 * S)])
        assert pc.inside_reads(str(where), BASE + 40 * S, BASE + 41 * S) == pytest.approx(0.25)
        assert pc.inside_reads(str(where), BASE + 41 * S, BASE + 41 * S) is None
        assert pc.inside_reads(str(tmp_path), 0, 1) is None


def world(root):
    """Two pairs. On `x86`, a Kafka campaign: one run the broker held for 4 s, one whose receiver
    stopped for 2 s at a quarter past with the sampler and the disk, one quiet; and a Redis
    campaign with a receiver pause of 1.5 s and two quiet runs. On `arm`, one quiet run. And a
    folder that is not a campaign."""
    k = root / "x86" / "a1_k"
    held = pause(2000, 4)
    write_run(k / "runs" / "law_k1", held, acks=dict((i, 3500.0) for i in held),
              sampler=sampler_lines(),
              broker_log="2026-09-28T10:00:41Z [x] INFO Unable to send a heartbeat\n")
    write_run(k / "runs" / "law_k2", pause(2000, 2), iowait=(0, 250),
              sampler=sampler_lines(gap_from=BASE + 40 * S, gap_s=2.5))
    write_run(k / "runs" / "law_k3", {}, iowait=(0, 10))
    quality(k, [("law_k1", "kafka", 90), ("law_k2", "kafka", 40), ("law_k3", "kafka", 0)])
    r = root / "x86" / "a1_r"
    write_run(r / "runs" / "law_r1", pause(2250, 1.5), iowait=(0, 180),
              reads=[(BASE + 45 * S - 10 * MS, 5 * MS)])
    write_run(r / "runs" / "law_r2", {}, iowait=(0, 8))
    write_run(r / "runs" / "law_r3", {}, iowait=(0, 9))
    quality(r, [("law_r1", "redis", 30)])
    write_run(root / "arm" / "a4" / "runs" / "law_a1", {}, iowait=(0, 11))
    quality(root / "arm" / "a4", [])
    (root / "arm" / "not_a_campaign").mkdir()
    return root


class TestTheCensus:

    def test_every_run_is_read_and_every_pause_found(self, tmp_path):
        eps, runs = pc.census(str(world(tmp_path)))
        assert len(runs) == 7
        assert sorted((ep["run"], ep["kind"]) for ep in eps) == [
            ("law_k1", "broker"), ("law_k2", "receiver"), ("law_r1", "receiver")]
        k1 = next(ep for ep in eps if ep["run"] == "law_k1")
        assert k1["heartbeat_lost"] is True and k1["sampler_gap_s"] == pytest.approx(0.5)
        k2 = next(ep for ep in eps if ep["run"] == "law_k2")
        assert k2["sampler_gap_s"] == pytest.approx(2.5) and k2["inside_reads"] is None
        r1 = next(ep for ep in eps if ep["run"] == "law_r1")
        assert r1["inside_reads"] == pytest.approx(0.0)
        quiet = next(r for r in runs if r["run"] == "law_k3")
        assert quiet == {"pair": "x86", "campaign": "a1_k", "run": "law_k3", "iowait_s": 0.1,
                         "steal_s": 0.0, "paused": False, "receiver_paused_s": 0.0}

    def test_what_they_add_up_to(self, tmp_path):
        eps, runs = pc.census(str(world(tmp_path)))
        found = pc.summary(eps, runs)
        assert found["episodes"] == {"x86, kafka, broker": 1, "x86, kafka, receiver": 1,
                                     "x86, redis, receiver": 1}
        assert found["runs"] == {"x86": 6, "arm": 1} and found["runs_with_a_pause"] == {"x86": 3}
        assert found["steal"] == {"runs_read": 7, "most_s": 0.0}
        assert found["kinds"]["receiver"]["long_with_the_sampler_stopped"] == 1
        assert found["kinds"]["receiver"]["long_with_the_sampler_timed"] == 1
        assert found["kinds"]["broker"]["long_with_the_sampler_stopped"] == 0
        assert found["heartbeat_lost"]["3 s or more"] == [1, 1]
        assert found["redis_receiver_inside_reads"] == {"episodes": 1, "most_inside": 0.0}
        assert found["iowait"]["x86"] == {"paused_runs": 2, "paused_median_s": 2.15,
                                          "quiet_runs": 3, "quiet_median_s": 0.09}
        assert found["iowait"]["arm"]["paused_median_s"] is None
        assert "iowait_on_pause" not in found, "two paused runs draw no line"
        assert found["hour"]["runs"] == 2 and found["hour"]["by_quarter"] == [2, 0, 0, 0]

    def test_the_line_of_disk_wait_on_pause(self):
        runs = [{"pair": "x", "iowait_s": 1.0 * s + 0.1, "paused": True,
                 "receiver_paused_s": float(s)} for s in (1, 2, 3, 5)]
        found = pc.summary([], runs + [{"pair": "x", "iowait_s": 0.1, "paused": False,
                                        "receiver_paused_s": 0.0}])
        assert found["iowait_on_pause"] == {"runs": 4, "slope": pytest.approx(1.0),
                                            "correlation": pytest.approx(1.0),
                                            "quiet_median_s": 0.1}
        assert "hour" not in found and found["redis_receiver_inside_reads"]["most_inside"] is None
        assert found["steal"] == {"runs_read": 0, "most_s": None}

    def test_a_runs_longest_pause_is_the_one_timed_against_the_hour(self):
        eps = [{"kind": "receiver", "worst_ms": w, "pair": "x", "run": "r", "backend": "kafka",
                "start": BASE + at * 60 * S, "sampler_gap_s": None, "heartbeat_lost": False,
                "inside_reads": None} for w, at in ((1500, 20), (3000, 50), (1200, 5))]
        found = pc.summary(eps, [{"pair": "x", "iowait_s": None, "paused": True,
                                  "receiver_paused_s": 5.7}])
        assert found["hour"]["by_quarter"] == [0, 0, 0, 1]
        assert found["hour"]["mean_minute"] == pytest.approx(50.0)


class TestTheHour:

    def test_times_spread_round_the_clock_are_not_clustered(self):
        p, _ = pc.rayleigh_p([m + 0.5 for m in range(60)])
        assert p == pytest.approx(1.0)

    def test_times_bunched_at_twelve_past_are(self):
        p, mean = pc.rayleigh_p([11.0, 12.0, 12.5, 13.0, 14.0] * 6)
        assert p < 1e-6 and mean == pytest.approx(12.5, abs=0.01)

    def test_the_line(self):
        slope, r = pc._line([1.0, 2.0, 3.0], [2.0, 4.0, 6.5])
        assert slope == pytest.approx(2.25) and r == pytest.approx(0.997949, abs=1e-5)
        assert pc._minute(BASE + 15 * 60 * S + 30 * S) == pytest.approx(15.5)
        assert math.isclose(pc._minute(BASE), 0.0)


class TestTheCommand:

    def test_it_writes_the_episodes_the_runs_and_the_summary(self, tmp_path, capsys):
        root = world(tmp_path / "w")
        out = tmp_path / "out"
        assert pc.main(["--root", str(root), "--out", str(out)]) == 0
        said = capsys.readouterr().out
        assert "receiver: 2 episodes (kafka, redis)" in said
        assert "x86: iowait 2.15 s in runs paused a second or more (2)" in said
        rows = list(csv.DictReader(open(out / "pause_episodes.csv", encoding="utf-8")))
        assert [r["start_utc"] for r in rows][0] == "2026-09-28T10:00:40.000Z"
        assert rows[0]["kind"] == "broker" and rows[0]["heartbeat_lost"] == "True"
        runs = list(csv.DictReader(open(out / "pause_runs.csv", encoding="utf-8")))
        assert len(runs) == 7
        summary = json.loads((out / "pause_summary.json").read_text(encoding="utf-8"))
        assert summary["runs"] == {"arm": 1, "x86": 6}

    def test_it_prints_without_writing(self, tmp_path, capsys):
        assert pc.main(["--root", str(world(tmp_path))]) == 0
        assert "Pauses" in capsys.readouterr().out

    def test_a_folder_with_no_campaign_is_an_error(self, tmp_path, capsys):
        assert pc.main(["--root", str(tmp_path)]) == 2
        assert "ERROR: no campaign" in capsys.readouterr().out
