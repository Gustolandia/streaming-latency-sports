"""Tests for scripts/quality_report.py.

The report decides nothing, so what matters is that it reads what the driver wrote, notices a
repeat that sits far from its fellows, and says so without touching the run.
"""
import io
import json
import os
import pathlib
import sys
import tarfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import quality_report as qr  # noqa: E402

START = 1789000000000000000


def write_run(folder, name, setup="C0-kafka-l75-d0a", round_="1", delay_ms=0.0, trip_ms=2.0,
              verdict="count", reasons=(), load=75.2, steal=0.0, resent=(0, 0, 0),
              messages=4988, stall_at=None, files=("queue_row.json", "integrity.json",
                                                   "producer.csv", "consumer_events.csv")):
    """One copied run directory, as campaign.sh and run_integrity.py leave it."""
    run = folder / name
    run.mkdir(parents=True, exist_ok=True)
    if "queue_row.json" in files:
        (run / "queue_row.json").write_text(json.dumps(
            {"key": name, "round": round_, "setup": setup,
             "params": json.dumps({"backend": setup.split("-")[1], "load_pct": 75,
                                   "delay_ms": delay_ms})}), encoding="utf-8")
    if "integrity.json" in files:
        (run / "integrity.json").write_text(json.dumps(
            {"verdict": verdict, "reasons": list(reasons),
             "checks": {"send_rate": {"value": 50.1}, "load": {"value": load}},
             "recorded": {"messages": messages, "trip_median_ms": trip_ms,
                          "gotit_median_ms": 1.5, "delay_held_ms": delay_ms + 0.01,
                          "steal_pct": steal, "clock_offset_max_s": 2e-5,
                          "retransmitted": dict(zip(("driver", "receiver", "broker"), resent))}}),
            encoding="utf-8")
    if "producer.csv" in files:
        rows = ["event_id,t_prod_send_ns"]
        rows += ["e%d,%d" % (i, START + i * 20_000_000) for i in range(3000)]
        (run / "producer.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    if "consumer_events.csv" in files:
        rows = ["event_id,t_consume_ns"]
        for i in range(3000):
            late = stall_at * 1e6 if (stall_at and i == 2500) else trip_ms * 1e6
            rows.append("e%d,%d" % (i, START + i * 20_000_000 + int(late)))
        (run / "consumer_events.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(run)


@pytest.fixture(autouse=True)
def a_ledger_of_its_own(tmp_path, monkeypatch):
    """No test reads or writes the repo's own spending ledger."""
    monkeypatch.setattr(qr.spend, "LEDGER", str(tmp_path / "spend.json"))


class TestOneRun:

    def test_it_reads_what_the_driver_wrote(self, tmp_path):
        found = qr.one_run(write_run(tmp_path, "law_c0_r001-a1"))
        assert found["verdict"] == "count" and found["problems"] == []
        assert found["messages"] == 4988 and found["trip_median_ms"] == 2.0
        assert found["load_pct"] == 75.2 and found["retransmitted_total"] == 0
        assert found["stalls"] == 0 and found["worst_trip_ms"] is None

    def test_a_pause_after_the_warm_up_is_counted(self, tmp_path):
        found = qr.one_run(write_run(tmp_path, "law_c0_r001-a1", stall_at=700.0))
        assert found["stalls"] == 1 and found["worst_trip_ms"] == pytest.approx(700.0)

    def test_a_pause_inside_the_warm_up_is_not(self, tmp_path):
        """The first 30 seconds are the consumer starting up, and the plan discards them."""
        run = write_run(tmp_path, "law_c0_r001-a1")
        rows = (tmp_path / "law_c0_r001-a1" / "consumer_events.csv").read_text().splitlines()
        rows[1] = "e0,%d" % (START + 400_000_000)
        (tmp_path / "law_c0_r001-a1" / "consumer_events.csv").write_text("\n".join(rows) + "\n",
                                                                         encoding="utf-8")
        assert qr.one_run(run)["stalls"] == 0

    @pytest.mark.parametrize("dropped,fragment", [
        (("queue_row.json",), "queue row"),
        (("integrity.json",), "verdict"),
        (("producer.csv",), "messages"),
        (("consumer_events.csv",), "messages")])
    def test_a_file_it_cannot_read_is_a_problem_not_a_crash(self, tmp_path, dropped, fragment):
        kept = tuple(f for f in ("queue_row.json", "integrity.json", "producer.csv",
                                 "consumer_events.csv") if f not in dropped)
        found = qr.one_run(write_run(tmp_path, "law_c0_r001-a1", files=kept))
        assert any(fragment in problem for problem in found["problems"]), found["problems"]

    def test_a_producer_file_with_no_send_times(self, tmp_path):
        run = write_run(tmp_path, "law_c0_r001-a1")
        (tmp_path / "law_c0_r001-a1" / "producer.csv").write_text(
            "event_id,t_prod_send_ns\ne0,\n", encoding="utf-8")
        assert qr.stalls(run) == (0, None)

    def test_a_consumer_row_without_its_stamp_is_skipped(self, tmp_path):
        run = write_run(tmp_path, "law_c0_r001-a1")
        rows = (tmp_path / "law_c0_r001-a1" / "consumer_events.csv").read_text().splitlines()
        rows[2500] = "e2499,"
        (tmp_path / "law_c0_r001-a1" / "consumer_events.csv").write_text(
            "\n".join(rows) + "\n", encoding="utf-8")
        assert qr.stalls(run) == (0, None)

    def test_the_messages_can_be_left_unread(self, tmp_path):
        found = qr.one_run(write_run(tmp_path, "law_c0_r001-a1"), want_stalls=False)
        assert "stalls" not in found


class TestTheWaypointCheck:
    """A setup's repeats run at different times on purpose, so one repeat far from its fellows
    says the machine was in a different state then."""

    def repeats(self, tmp_path, trips, setup="C0-kafka-l75-d0a"):
        return [qr.one_run(write_run(tmp_path, "law_c0_r%03d-a1" % (i + 1), setup=setup,
                                     round_=str(i + 1), trip_ms=t), want_stalls=False)
                for i, t in enumerate(trips)]

    def test_repeats_that_agree_raise_nothing(self, tmp_path):
        assert qr.waypoints(self.repeats(tmp_path, [2.00, 2.03, 1.98, 2.01])) == []

    def test_one_repeat_far_from_the_others_is_registered(self, tmp_path):
        found = qr.waypoints(self.repeats(tmp_path, [2.00, 2.03, 1.98, 3.40]))
        trips = [m for m in found if m["quantity"] == "trip_median_ms"]
        assert len(trips) == 1 and trips[0]["repeats"] == 4
        assert [f["run"] for f in trips[0]["far"]] == ["law_c0_r004-a1"]
        assert trips[0]["far"][0]["robust_z"] > 5

    def test_a_small_difference_is_left_alone_however_steady_the_rest(self, tmp_path):
        """With repeats that agree exactly, any difference is infinitely many deviations; the
        floor keeps that from crying wolf over a hundredth of a millisecond."""
        found = qr.waypoints(self.repeats(tmp_path, [2.0, 2.0, 2.0, 2.05]))
        assert [m for m in found if m["quantity"] == "trip_median_ms"] == []
        found = qr.waypoints(self.repeats(tmp_path, [2.0, 2.0, 2.0, 2.5]))
        far = [m for m in found if m["quantity"] == "trip_median_ms"][0]["far"]
        assert far[0]["robust_z"] is None and far[0]["distance_ms"] == pytest.approx(0.5)

    def test_a_wide_but_even_spread_flags_nobody(self, tmp_path):
        """Each repeat is a fifth of a millisecond from the middle, but so is every other."""
        found = qr.waypoints(self.repeats(tmp_path, [2.0, 2.3, 2.6, 2.9]))
        assert [m for m in found if m["quantity"] == "trip_median_ms"] == []

    def test_two_repeats_are_too_few_to_judge_one_another(self, tmp_path):
        assert qr.waypoints(self.repeats(tmp_path, [2.0, 3.5])) == []

    def test_a_repeat_that_sits_near_the_others_is_passed_over(self, tmp_path):
        """One repeat is far and the next is not, so the loop has to keep going past it."""
        found = qr.waypoints(self.repeats(tmp_path, [2.0, 2.02, 1.99, 2.01, 3.4]))
        far = [m for m in found if m["quantity"] == "trip_median_ms"][0]["far"]
        assert [f["run"] for f in far] == ["law_c0_r005-a1"]

    def test_a_setup_with_one_run_has_nothing_to_spread_against(self, tmp_path):
        write_run(tmp_path, "law_c0_r000-a1", files=("queue_row.json",))
        write_run(tmp_path, "law_c0_r001-a1", setup="C0-redis-l75-d8000", trip_ms=9.0)
        write_run(tmp_path, "law_c0_r002-a1", setup="C0-kafka-l75-d0a", trip_ms=2.0)
        write_run(tmp_path, "law_c0_r003-a1", setup="C0-kafka-l75-d0a", round_="2", trip_ms=2.1)
        found = qr.report(qr.run_dirs_under(str(tmp_path)), want_stalls=False)
        assert sorted(found["setup_spread"]) == ["C0-kafka-l75-d0a"]

    def test_each_setup_is_held_against_itself(self, tmp_path):
        runs = self.repeats(tmp_path, [2.0, 2.0, 2.0], setup="C0-kafka-l75-d0a")
        runs += self.repeats(tmp_path / "b", [9.0, 9.0, 9.0], setup="C0-kafka-l75-d8000")
        assert qr.waypoints(runs) == [], "a longer delay is not an outlier"


class TestPausesAreAWaypointToo:
    """A repeat with a hundred pauses beside fellows with none is as much worth registering as
    one whose trip moved: it is the same machine in a different state."""

    def test_one_repeat_full_of_pauses_is_registered(self, tmp_path):
        runs = [qr.one_run(write_run(tmp_path, "law_c0_r%03d-a1" % (i + 1), round_=str(i + 1),
                                     stall_at=None if i else 700.0))
                for i in range(4)]
        found = [m for m in qr.waypoints(runs) if m["quantity"] == "stalls"]
        assert found == [] , "one pause is under the floor"
        for run in runs[:1]:
            run["stalls"] = 82
        found = [m for m in qr.waypoints(runs) if m["quantity"] == "stalls"]
        assert len(found) == 1 and found[0]["far"][0]["value"] == 82

    def test_a_report_that_did_not_read_the_messages_says_nothing_about_pauses(self, tmp_path):
        runs = [qr.one_run(write_run(tmp_path, "law_c0_r%03d-a1" % (i + 1), round_=str(i + 1)),
                           want_stalls=False) for i in range(4)]
        assert [m for m in qr.waypoints(runs) if m["quantity"] == "stalls"] == []


class TestAReportAskedForMidCampaign:
    """Both found on 24 September, running this on three drivers while their campaigns ran.
    Mid-campaign is when a report is most use, and it printed only an error."""

    def test_a_run_still_going_is_counted_as_not_yet_judged(self, tmp_path):
        runs = tmp_path / "runs"
        write_run(runs, "law_a3_x_r001-A3-kafka-l50-s3000-c02h-a1")
        write_run(runs, "law_a3_x_r001-A3-kafka-l50-s3000-c04h-a1")
        os.remove(runs / "law_a3_x_r001-A3-kafka-l50-s3000-c04h-a1" / "integrity.json")
        found = qr.report(qr.run_dirs_under(str(runs)), want_stalls=False)
        assert found["verdicts"].get("not yet judged") == 1
        assert None not in found["verdicts"]

    def test_and_the_report_of_it_can_be_written_down(self, tmp_path):
        """A None key beside string ones is what sorted keys could not order."""
        runs = tmp_path / "runs"
        write_run(runs, "law_a3_x_r001-A3-kafka-l50-s3000-c02h-a1")
        write_run(runs, "law_a3_x_r001-A3-kafka-l50-s3000-c04h-a1")
        os.remove(runs / "law_a3_x_r001-A3-kafka-l50-s3000-c04h-a1" / "integrity.json")
        out = tmp_path / "report.json"
        said = io.StringIO()
        assert qr.main(["--runs", str(runs), "--no-stalls", "--out", str(out)], said) == 0
        assert "ERROR" not in said.getvalue()
        assert json.loads(out.read_text(encoding="utf-8"))["verdicts"]["not yet judged"] == 1

    def test_a_directory_named_like_a_queue_is_not_read_as_one(self, tmp_path):
        """On a driver the folder above the runs was /tmp, holding a directory called x.csv."""
        runs = tmp_path / "runs"
        write_run(runs, "law_c0_x_r001-C0-kafka-l75-d0a-a1")
        (tmp_path / "stray.csv").mkdir()
        assert qr.queue_rows(str(runs)) == []

    def test_nor_is_a_csv_that_is_not_a_queue(self, tmp_path):
        """Anything else in that folder would have been taken for this campaign's queue."""
        runs = tmp_path / "runs"
        write_run(runs, "law_c0_x_r001-C0-kafka-l75-d0a-a1")
        (tmp_path / "prices.csv").write_text("region,usd\nswedencentral,0.48\n", encoding="utf-8")
        assert qr.queue_rows(str(runs)) == []


class TestWhatARunCost:
    """The queue says when each run began; the watch's ledger says what had been spent by then."""

    @staticmethod
    def ledger():
        return {"timeline": [["2026-09-16T15:00:00Z", 1.0], ["2026-09-16T15:30:00Z", 2.5]],
                "total_usd": 2.5}

    def campaign(self, tmp_path, queue=True, packed=False):
        home = tmp_path / "c0_20260916T150602Z"
        runs = home / "runs"
        for key in ("r001-C0-kafka", "r002-C0-redis"):
            write_run(runs, "law_c0_20260916T150602Z_" + key)
        if queue:
            here = home / "c0_20260916T150602Z.csv"
            here.write_text("key,status,started_utc\n"
                            "r001-C0-kafka,done,2026-09-16T15:05:00Z\n"
                            "r002-C0-redis,done,2026-09-16T15:44:00Z\n", encoding="utf-8")
            if packed:
                with tarfile.open(home / "runs.tar", "w") as archive:
                    archive.add(str(here), arcname="runs/azure/stage0/c0/queue.csv")
                here.unlink()
        return str(runs)

    def found(self, runs, ledger=None):
        return qr.report(qr.run_dirs_under(runs), False, ledger=ledger, folder=runs)

    def test_each_run_carries_what_had_been_spent_when_it_began(self, tmp_path):
        found = self.found(self.campaign(tmp_path), self.ledger())
        began = dict((r["run"].split("Z_")[-1], r.get("spent_usd_at_start")) for r in found["runs"])
        assert began["r001-C0-kafka"] == 1.0, "the last look before it had reached a dollar"
        assert began["r002-C0-redis"] == 2.5

    def test_the_queue_is_read_out_of_the_tar_it_was_packed_in(self, tmp_path):
        found = self.found(self.campaign(tmp_path, packed=True), self.ledger())
        assert all(r.get("started_utc") for r in found["runs"])

    def test_a_campaign_without_its_queue_says_nothing_about_money(self, tmp_path):
        found = self.found(self.campaign(tmp_path, queue=False), self.ledger())
        assert all("spent_usd_at_start" not in r for r in found["runs"])
        assert not any(line.startswith("money:") for line in qr.lines(found))

    def test_a_tar_that_holds_no_queue_leaves_the_money_out(self, tmp_path):
        runs = self.campaign(tmp_path, queue=False)
        home = pathlib.Path(runs).parent
        (home / "notes.txt").write_text("nothing here", encoding="utf-8")
        with tarfile.open(home / "runs.tar", "w") as archive:
            archive.add(str(home / "notes.txt"), arcname="runs/notes.txt")
        assert qr.queue_rows(runs) == []

    def test_a_run_the_queue_does_not_name_is_left_alone(self, tmp_path):
        runs = self.campaign(tmp_path)
        write_run(pathlib.Path(runs), "law_c0_20260916T150602Z_r009-C0-ghost")
        ghost = [r for r in self.found(runs, self.ledger())["runs"]
                 if r["run"].endswith("ghost")][0]
        assert "spent_usd_at_start" not in ghost

    def test_a_run_older_than_the_ledger_has_nothing_to_carry(self, tmp_path):
        later = {"timeline": [["2026-09-17T00:00:00Z", 9.0]], "total_usd": 9.0}
        found = self.found(self.campaign(tmp_path), later)
        assert all(r["spent_usd_at_start"] is None for r in found["runs"])

    def test_the_line_says_what_the_campaign_went_through(self, tmp_path):
        found = self.found(self.campaign(tmp_path), self.ledger())
        assert ("money: these runs began between about $1.00 and $2.50 spent; about $1.50 went "
                "on the campaign up to its last run") in qr.lines(found)

    def test_without_a_ledger_the_report_is_as_it_was(self, tmp_path):
        found = self.found(self.campaign(tmp_path))
        assert all("spent_usd_at_start" not in r for r in found["runs"])

    def test_the_command_reads_the_ledger_it_is_given(self, tmp_path):
        runs = self.campaign(tmp_path)
        path = tmp_path / "spend.json"
        path.write_text(json.dumps(self.ledger()), encoding="utf-8")
        out = io.StringIO()
        assert qr.main(["--runs", runs, "--no-stalls", "--ledger", str(path)], out=out) == 0
        assert "money: these runs began between about $1.00 and $2.50" in out.getvalue()


class TestTheWholeReport:

    def campaign(self, tmp_path, trips=(2.0, 2.05, 1.97, 3.4)):
        for i, trip in enumerate(trips):
            write_run(tmp_path, "law_c0_r%03d-a1" % (i + 1), round_=str(i + 1), trip_ms=trip)
        write_run(tmp_path, "law_c0_r005-a1", setup="C0-redis-l75-d0a", trip_ms=0.9,
                  verdict="repeat", reasons=("the load was 61.2%, not 75%",), load=61.2)
        return qr.report(qr.run_dirs_under(str(tmp_path)), want_stalls=False)

    def test_it_counts_verdicts_and_names_the_repeats(self, tmp_path):
        found = self.campaign(tmp_path)
        assert found["verdicts"] == {"count": 4, "repeat": 1}
        text = "\n".join(qr.lines(found))
        assert "repeat: law_c0_r005-a1 (the load was 61.2%, not 75%)" in text
        assert "repeats far from their fellows (registered, not removed)" in text
        assert "law_c0_r004-a1" in text

    def test_a_quiet_campaign_says_so(self, tmp_path):
        text = "\n".join(qr.lines(self.campaign(tmp_path, trips=(2.0, 2.05, 1.97, 2.02))))
        assert "no repeat lies far from its fellows" in text
        assert "run-to-run spread of the trip: widest" in text

    def test_from_the_command_line(self, tmp_path):
        self.campaign(tmp_path)
        out = io.StringIO()
        dest = tmp_path / "report.json"
        code = qr.main(["--runs", str(tmp_path), "--out", str(dest), "--no-stalls"], out=out)
        assert code == 0 and "5 run(s): count 4, repeat 1" in out.getvalue()
        saved = json.loads(dest.read_text(encoding="utf-8"))
        assert saved["waypoints"][0]["setup"] == "C0-kafka-l75-d0a"

    def test_a_run_it_could_not_read_is_named_in_the_text(self, tmp_path):
        write_run(tmp_path, "law_c0_r001-a1", files=("integrity.json",))
        found = qr.report(["%s/law_c0_r001-a1" % tmp_path], want_stalls=False)
        text = "\n".join(qr.lines(found))
        assert "unreadable: law_c0_r001-a1: the queue row could not be read" in text
        assert found["runs_with_problems"] == ["law_c0_r001-a1"]
        assert "run-to-run spread" not in text, "one run has nothing to be spread against"

    def test_it_prints_without_being_asked_to_save(self, tmp_path):
        write_run(tmp_path, "law_c0_r001-a1")
        write_run(tmp_path, "law_c0_r002-a1", round_="2")
        out = io.StringIO()
        assert qr.main(["--runs", str(tmp_path), "--no-stalls"], out=out) == 0
        assert "2 run(s): count 2" in out.getvalue()

    def test_a_folder_with_no_runs(self, tmp_path):
        out = io.StringIO()
        assert qr.main(["--runs", str(tmp_path)], out=out) == 2
        assert out.getvalue().startswith("ERROR: no run directories")

    def test_pauses_are_counted_across_the_campaign(self, tmp_path):
        write_run(tmp_path, "law_c0_r001-a1", stall_at=600.0)
        write_run(tmp_path, "law_c0_r002-a1", round_="2")
        found = qr.report(qr.run_dirs_under(str(tmp_path)))
        assert found["stalls_total"] == 1
        assert "pauses over 150 ms after the warm-up: 1 message(s), worst 600 ms" in \
            "\n".join(qr.lines(found))
