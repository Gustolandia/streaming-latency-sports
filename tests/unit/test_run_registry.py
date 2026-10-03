"""Tests for scripts/run_registry.py, on run and campaign folders shaped the way campaign.sh and
stage1.sh leave them: the queue row, the integrity record, the lane, the scheduler's reading, the
campaign's queue, settings and log."""
import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import run_registry as rr  # noqa: E402

SETTINGS = {"base_slice_ns": 1500000, "clocksource": "tsc", "config_hz": 1000,
            "cpu_model": "AMD EPYC 9V74 80-Core Processor", "online_cpus": 8,
            "release": "6.8.0-1065-azure", "tick_ms": 1.0}


def run(root, name, params, verdict="count", recorded=None, lane=None, settings=SETTINGS,
        files=()):
    where = root / name
    where.mkdir(parents=True)
    (where / "queue_row.json").write_text(json.dumps(
        {"attempt": "1", "key": name.split("_", 3)[-1], "round": "2",
         "setup": name.split("_", 3)[-1].split("-a1")[0][5:], "params": params}),
        encoding="utf-8")
    (where / "integrity.json").write_text(json.dumps(
        {"verdict": verdict, "reasons": ["the brake would have stopped it"] if verdict == "stop"
         else [], "recorded": recorded if recorded is not None else {
             "trip_median_ms": 2.1, "gotit_median_ms": 0.8, "measured_negative_rate": 0.02,
             "delay_held_ms": 1.01, "messages": 5000}}), encoding="utf-8")
    (where / "lane.json").write_text(json.dumps(lane if lane is not None else {
        "lane": "matched", "profile": "matched", "driver": "sbl-az-drv",
        "commit": "8762e02c191f17869e6ac2dff8cd7fb52031c878"}), encoding="utf-8")
    if settings is not None:
        (where / "settings_before.json").write_text(json.dumps(
            {"ok": True, "problems": [], "settings": settings}), encoding="utf-8")
    for extra in files:
        (where / extra).write_text("x", encoding="utf-8")
    return where


def campaign(root, folder, label, statuses, last_line, settings=SETTINGS):
    where = root / folder
    where.mkdir(parents=True)
    rows = ["key,round,setup,params,status,attempt,reason,started_utc,finished_utc,run_dir,seed"]
    for i, status in enumerate(statuses):
        done = status in ("done", "failed")
        rows.append("r%03d,1,s,{},%s,1,,2026-09-26T0%d:00:00Z,%s,,1" % (
            i, status, i % 10, "2026-09-26T0%d:02:00Z" % (i % 10) if done else ""))
    (where / ("%s.csv" % label)).write_text("\n".join(rows) + "\n", encoding="utf-8")
    (where / ("campaign_%s.log" % label)).write_text("first\n%s\n\n" % last_line, encoding="utf-8")
    if settings is not None:
        (where / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return where


class TestTheMachines:

    def test_each_driver_is_given_its_size_its_brokers_and_its_image(self):
        found = rr.machines()
        assert found["sbl-az-drv"] == ("Standard_D8as_v6", "Standard_D2as_v6",
                                       "Canonical:0001-com-ubuntu-server-jammy:22_04-lts-gen2:latest")
        assert found["sbl-az-arm-drv"][:2] == ("Standard_D8ps_v6", "Standard_D2ps_v6")
        assert found["sbl-azb-drv"][0] == "Standard_D8as_v6"

    def test_a_spec_that_is_not_there_gives_nothing(self, tmp_path):
        assert rr.machines(str(tmp_path / "none.json")) == {}

    def test_a_driver_with_no_broker_and_an_image_not_listed_are_kept_as_they_are(self, tmp_path):
        spec = tmp_path / "spec.json"
        spec.write_text(json.dumps({"hosts": {"d": {"role": "driver", "size": "S", "image": "raw"}},
                                    "profiles": {"p": {"hosts": ["d"]}, "q": {"hosts": []}}}),
                        encoding="utf-8")
        assert rr.machines(str(spec)) == {"d": ("S", None, "raw")}


class TestTheRuns:

    def test_a_run_carries_its_design_its_machine_its_kernel_and_its_verdict(self, tmp_path):
        where = run(tmp_path, "law_a1_20260918T194622Z_r002-A1-redis-l75-s1500-c04h-a1",
                    {"backend": "redis", "block": "A1", "load_pct": 75, "slice_ns": 1500000,
                     "point": "c04h", "delay_ms": 1.012, "cpus": None, "priority": False,
                     "trace_half": True}, files=("runqlat.txt",))
        row = rr.run_row(str(where), rr.machines())
        assert row["campaign"] == "a1_20260918T194622Z" and row["pair"] == "matched"
        assert (row["driver_size"], row["broker_size"]) == ("Standard_D8as_v6", "Standard_D2as_v6")
        assert row["kernel"] == "6.8.0-1065-azure" and row["config_hz"] == 1000
        assert row["cpu_model"] == "AMD EPYC 9V74 80-Core Processor" and row["online_cpus"] == 8
        assert row["slice_set_ns"] == 1500000 and row["slice_in_force_ns"] == 1500000
        assert row["delay_set_ms"] == 1.012 and row["delay_held_ms"] == 1.01
        assert row["verdict"] == "count" and row["recorded_half"] is True
        assert row["commit"] == "8762e02c191f" and row["block"] == "A1" and row["round"] == "2"

    def test_a_run_whose_files_say_less_still_has_a_row_and_a_folder_that_is_not_a_run_has_none(
            self, tmp_path):
        where = run(tmp_path, "law_m0_20260926T133519Z_r001-M0-kafka-l75-d8000-a1",
                    json.dumps({"backend": "kafka", "delay_ms": 8.0}), verdict="stop",
                    recorded={"gotit_brake": "records and does not stop (D26-1, D32-1)"},
                    lane={}, settings=None)
        row = rr.run_row(str(where), {})
        assert row["block"] == "M0" and row["pair"] == "" and row["kernel"] is None
        assert row["gotit_brake"].startswith("records") and row["recorded_half"] is False
        assert row["reasons"] == "the brake would have stopped it"
        assert rr.run_row(str(tmp_path / "nothing"), {}) is None
        assert rr.campaign_of("stage1") == "" and rr.campaign_of("law_x") == ""

    def test_an_r1_run_names_its_stampless_queue_and_both_of_its_settings(self, tmp_path):
        """R1 (3 Oct 2026) named its first queue r1, with no stamp, raised the consumer alone and
        captured the receiver's packets in every run. The registry says all three."""
        where = run(tmp_path, "law_r1_r001-R1-kafka-l75-rtc-a1",
                    {"backend": "kafka", "load_pct": 75, "delay_ms": 0, "slice_ns": 3000000,
                     "consumer_priority": True, "recv_capture": True, "trace_half": True,
                     "trace_events": True}, files=("waits.txt",))
        row = rr.run_row(str(where), {})
        assert row["campaign"] == "r1" and row["block"] == "R1" and row["recorded_half"]
        assert row["consumer_priority"] is True and row["recv_capture"] is True
        assert row["priority"] is None, "the producer was never raised"
        more = rr.run_row(str(run(tmp_path, "law_r1_more_r007-R1-redis-l88-ord-a1",
                                  {"backend": "redis", "load_pct": 88, "delay_ms": 0,
                                   "recv_capture": True})), {})
        assert more["campaign"] == "r1_more" and more["consumer_priority"] is None
        assert rr.campaign_of("law_r1_r001-R1-kafka-l75-ord-a1", "r001-R1-kafka-l75-ord-a1") \
            == "r1"
        assert rr.campaign_of("law_r1_r001", "r002") == "", "a key the name does not end with"
        assert rr.campaign_of("law_x", "x") == "", "nothing left to be the queue's name"
        assert rr.campaign_of("run_r1_r001", "r001") == "", "not a campaign's run"


class TestTheCampaigns:

    def test_a_complete_campaign_and_one_the_brake_stopped(self, tmp_path):
        done = rr.campaign_row(str(campaign(
            tmp_path, "matched_20260925T231407Z", "a2_20260925T231407Z",
            ["done", "failed", "done"], "2026-09-26T01:10:50Z CAMPAIGN_COMPLETE")))
        assert done["complete"] is True and done["designed_runs"] == 2 and done["ended"] == "complete"
        assert done["failed_attempts"] == 1 and done["block"] == "A2"
        assert done["kernel"] == "6.8.0-1065-azure"
        assert done["first_started_utc"] == "2026-09-26T00:00:00Z"
        stopped = rr.campaign_row(str(campaign(
            tmp_path, "matched_20260926T035408Z", "a1_20260926T035408Z",
            ["done", "done", "queued", "running", "abandoned"],
            "2026-09-26T06:32:07Z STOP_RULE: the got-it median moved 0.380 ms")))
        assert stopped["complete"] is False and stopped["left"] == 2 and stopped["abandoned"] == 1
        assert stopped["designed_runs"] == 5
        assert stopped["ended"] == "stopped: the got-it median moved 0.380 ms"

    def test_a_campaign_stopped_by_hand_one_not_ended_and_a_folder_without_a_queue(self, tmp_path):
        by_hand = rr.campaign_row(str(campaign(
            tmp_path, "b_1", "a2_20260921T140723Z", ["done", "queued"],
            "2026-09-21T14:12:48Z STOPPED at runs/azure/STOP", settings=None)))
        assert by_hand["ended"] == "stopped by hand" and by_hand["kernel"] is None
        going = rr.campaign_row(str(campaign(tmp_path, "b_2", "m0_20260926T133519Z", ["queued"],
                                             "run r001: redis")))
        assert going["ended"] == "not ended" and going["last_finished_utc"] == ""
        (tmp_path / "empty").mkdir()
        assert rr.campaign_row(str(tmp_path / "empty")) is None
        bare = campaign(tmp_path, "b_3", "a3_20260921T030021Z", [], "")
        (bare / "campaign_a3_20260921T030021Z.log").unlink()
        assert rr.campaign_row(str(bare))["ended"] == "not ended"


class TestTheCommand:

    def test_it_writes_both_registers_and_names_what_is_unfinished(self, tmp_path):
        runs = tmp_path / "runs"
        run(runs, "law_a1_20260918T194622Z_r002-A1-redis-l75-s1500-c04h-a1",
            {"backend": "redis", "block": "A1"})
        stage1 = tmp_path / "stage1"
        campaign(stage1, "matched_20260926T035408Z", "a1_20260926T035408Z", ["done", "queued"],
                 "STOP_RULE: the got-it median moved 0.380 ms")
        (stage1 / "loose.txt").write_text("", encoding="utf-8")
        out = io.StringIO()
        code = rr.main(["--runs", str(runs), "--out", str(tmp_path / "runs.csv"),
                        "--campaigns", str(stage1), "--campaigns-out",
                        str(tmp_path / "campaigns.csv")], out=out)
        assert code == 0
        text = out.getvalue()
        assert "1 runs -> " in text and "1 campaigns, 0 complete, 1 with runs left" in text
        assert "matched_20260926T035408Z: 1 of 2 done, 1 left" in text
        with open(tmp_path / "runs.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["kernel"] == "6.8.0-1065-azure" and list(rows[0]) == list(rr.RUN_FIELDS)

    def test_one_register_alone_and_nothing_asked(self, tmp_path):
        runs = tmp_path / "runs"
        runs.mkdir()
        assert rr.main(["--runs", str(runs), "--out", str(tmp_path / "r.csv")],
                       out=io.StringIO()) == 0
        assert rr.main(["--campaigns", str(runs), "--campaigns-out", str(tmp_path / "c.csv")],
                       out=io.StringIO()) == 0
        out = io.StringIO()
        assert rr.main([], out=out) == 2 and out.getvalue().startswith("ERROR")
