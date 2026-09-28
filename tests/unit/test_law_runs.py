"""Tests for scripts/law_runs.py: every run of the law campaign and the marks that say what was
aberrant about it, on a made-up repository laid out as the real one is -- the registry's columns,
the judging's quality table and flagged view, and the pause census's list."""
import csv
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import law_runs as lr  # noqa: E402

COLUMNS = ["run", "campaign", "pair", "block", "setup", "backend", "load_pct", "slice_set_ns",
           "point", "tick_ms", "cpus", "language", "priority", "recorded_half", "verdict",
           "trip_median_ms", "gotit_median_ms", "delay_held_ms", "measured_negative_rate",
           "reasons", "gotit_brake"]


def _run(name, campaign, pair="matched", block="A1", setup="A1-kafka-l75-s3000-p09s",
         verdict="count", trip="3.0", gotit="1.0", held="0.5", rate="0.05",
         recorded="False", slice_ns="3000000", reasons=""):
    return {"run": name, "campaign": campaign, "pair": pair, "block": block, "setup": setup,
            "backend": "kafka", "load_pct": "75", "slice_set_ns": slice_ns, "point": "p09s",
            "tick_ms": "1.0", "cpus": "", "language": "", "priority": "False",
            "recorded_half": recorded, "verdict": verdict, "trip_median_ms": trip,
            "gotit_median_ms": gotit, "delay_held_ms": held, "measured_negative_rate": rate,
            "reasons": reasons, "gotit_brake": ""}


def repository(tmp_path, runs, false_starts=(), flagged=(), paused=()):
    registry = tmp_path / "registry"
    registry.mkdir()
    for pair in lr.PAIRS:
        with open(registry / ("runs_%s.csv" % pair), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(r for r in runs if r["pair"] == pair)
        with open(registry / ("campaigns_%s.csv" % pair), "w", newline="",
                  encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["campaign", "complete"])
            for p, campaign in false_starts:
                if p == pair:
                    w.writerow([campaign, "False"])
            w.writerow(["whole_campaign", "True"])
    judged = tmp_path / "judged"
    (judged / "views").mkdir(parents=True)
    folders = sorted(set((r["pair"], lr.folder_of(r["run"])) for r in runs
                         if lr.folder_of(r["run"]) and "void" not in r["run"]))
    with open(judged / "quality_by_campaign.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pair", "campaign"])
        w.writerows(folders)
    (judged / "views" / "unflagged.json").write_text(json.dumps({"campaigns": [
        {"pair": pair, "campaign": "x", "left_out": [name]} for pair, name in flagged]}),
        encoding="utf-8")
    pauses = tmp_path / "pause_runs.csv"
    with open(pauses, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pair", "run", "paused"])
        for r in runs:
            w.writerow([r["pair"], r["run"], "True" if (r["pair"], r["run"]) in paused
                        else "False"])
    return str(registry), str(judged), str(pauses)


def _by_name(runs):
    return dict((r["run"], r) for r in runs)


class TestTheCampaignOfARun:

    def test_the_folder_is_read_off_the_run_name(self):
        assert lr.folder_of("law_a3_20260919T171733Z_r016-A3-kafka-l75-s3000-p09s-a1") == \
            "a3_20260919T171733Z"
        assert lr.folder_of("law_c0_python_20260921T215138Z_r002-C0-kafka-l75-python-d0a-a1") \
            == "c0_python_20260921T215138Z"
        assert lr.folder_of("law_r001-C0-kafka-l75-d0a-a1") is None


class TestTheMarks:

    def world(self, tmp_path):
        runs = [
            _run("law_a1_x_r001-A1-a1", "a1_x"),
            _run("law_a1_x_r002-A1-a1", "a1_x", verdict="repeat",
                 reasons="the measured load was 70.9% against 75%"),
            _run("law_a1_x_r003-A1-a1", "a1_x", verdict="stop"),
            _run("law_a1_x_r004-A1-a1", "a1_x", verdict="", trip="", rate=""),
            _run("law_a1_x_r005-A1-a1", "a1_x"),
            _run("law_a1_x_r006-A1-a1", "a1_x"),
            _run("law_a1_x_r007-A1-a1", "a1_x", trip="4.0"),
            _run("law_r001-C0-kafka-l75-d0a-a1", "", pair="matched-b", block="C0"),
            _run("law_c0_void_r001-C0-a1", "c0_void", block="C0"),
            _run("law_a4_f_r001-A4-a1", "a4_f", pair="arm", block="A4", verdict="repeat"),
            _run("law_a9_y_r001-A9-a1", "a9_y", block="A9", recorded="True"),
            _run("law_a1_z_r001-A1-a1", "a1_z", recorded="True", slice_ns=""),
        ]
        paths = repository(tmp_path, runs, false_starts=[("arm", "a4_f")],
                           flagged=[("matched", "law_a1_x_r005-A1-a1")],
                           paused=[("matched", "law_a1_x_r006-A1-a1")])
        return _by_name(lr.load(*paths))

    def test_each_run_carries_what_happened_to_it(self, tmp_path):
        runs = self.world(tmp_path)
        assert runs["law_a1_x_r001-A1-a1"]["marks"] == []
        assert runs["law_a1_x_r002-A1-a1"]["marks"] == ["repeated"]
        assert runs["law_a1_x_r003-A1-a1"]["marks"] == ["stopped"]
        assert runs["law_a1_x_r004-A1-a1"]["marks"] == ["unjudged"]
        assert runs["law_a1_x_r004-A1-a1"]["trip_median_ms"] is None
        assert runs["law_a1_x_r005-A1-a1"]["marks"] == ["flagged"]
        assert runs["law_a1_x_r006-A1-a1"]["marks"] == ["paused"]
        assert runs["law_a1_x_r007-A1-a1"]["marks"] == ["far"], "a trip 1 ms from its fellows"

    def test_a_run_no_judged_campaign_holds_is_void(self, tmp_path):
        runs = self.world(tmp_path)
        assert runs["law_r001-C0-kafka-l75-d0a-a1"]["marks"] == ["void"]
        assert runs["law_c0_void_r001-C0-a1"]["marks"] == ["void"]

    def test_a_false_start_keeps_its_own_verdict_beside_it(self, tmp_path):
        runs = self.world(tmp_path)
        assert runs["law_a4_f_r001-A4-a1"]["marks"] == ["false start", "repeated"]

    def test_only_a9s_and_m0s_traced_half_is_marked_traced(self, tmp_path):
        runs = self.world(tmp_path)
        assert runs["law_a9_y_r001-A9-a1"]["marks"] == ["traced"]
        assert runs["law_a1_z_r001-A1-a1"]["marks"] == [], "A6's histogram left the rate alone"
        assert runs["law_a1_z_r001-A1-a1"]["slice_ms"] is None
        assert runs["law_a1_x_r001-A1-a1"]["slice_ms"] == 3.0
        assert runs["law_a1_x_r001-A1-a1"]["language"] == "python"


class TestFarFromItsFellows:

    def _repeats(self, trips, gotits=None):
        gotits = gotits or [1.0] * len(trips)
        return [{"pair": "matched", "folder": "c", "setup": "s", "run": "r%d" % i,
                 "trip_median_ms": t, "gotit_median_ms": g, "delay_held_ms": 0.5}
                for i, (t, g) in enumerate(zip(trips, gotits))]

    def test_a_trip_five_robust_deviations_out_and_past_its_floor_is_far(self):
        runs = self._repeats([3.00, 3.01, 2.99, 3.02, 2.98, 4.00])
        assert lr.far_runs(runs) == {("matched", "r5")}

    def test_a_distance_under_the_floor_is_never_far(self):
        runs = self._repeats([3.000, 3.000, 3.000, 3.100])
        assert lr.far_runs(runs) == set(), "0.1 ms is under the trip's 0.20 ms floor"

    def test_with_no_spread_at_all_anything_past_the_floor_is_far(self):
        runs = self._repeats([3.0, 3.0, 3.0, 3.5])
        assert lr.far_runs(runs) == {("matched", "r3")}

    def test_fewer_than_three_repeats_are_not_held_against_each_other(self):
        runs = self._repeats([3.0, 9.0])
        assert lr.far_runs(runs) == set()

    def test_a_missing_value_is_left_out_of_its_quantity_only(self):
        runs = self._repeats([3.0, 3.0, 3.0, 3.5], gotits=[None, 1.0, 1.0, 1.0])
        assert lr.far_runs(runs) == {("matched", "r3")}


class TestTheCounts:

    def test_every_mark_is_counted_pair_by_pair_and_block_by_block(self, tmp_path):
        runs = list(TestTheMarks().world(tmp_path).values())
        every = lr.counts(runs)
        assert every["void"] == {"matched": 1, "matched-b": 1, "arm": 0}
        assert every["repeated"] == {"matched": 1, "matched-b": 0, "arm": 1}
        law = lr.counts(runs, lr.LAW_BLOCKS)
        assert law["void"] == {"matched": 0, "matched-b": 0, "arm": 0}
        assert law["traced"]["matched"] == 1


class TestTheCommand:

    def test_it_prints_every_mark(self, tmp_path, capsys):
        runs = [_run("law_a1_x_r001-A1-a1", "a1_x")]
        registry, judged, pauses = repository(tmp_path, runs)
        assert lr.main(["--registry", registry, "--judged", judged, "--pauses", pauses]) == 0
        said = capsys.readouterr().out
        assert "runs: 1, of them in the law's blocks: 1" in said
        assert "paused       counted; all blocks first x86 0" in said

    def test_a_missing_file_is_an_error(self, tmp_path, capsys):
        assert lr.main(["--registry", str(tmp_path)]) == 2
        assert capsys.readouterr().out.startswith("ERROR:")
