"""Tests for scripts/brake_views.py -- the views of the runs with and without what the got-it
brake only recorded (plan version 32, D32-1).

Each state is pinned on the integrity record the driver actually writes: a run taken while the
brake stopped carries no `gotit_brake`; one taken while it recorded carries it, with the check it
would have stopped on beside it when that check could be made. The views are pinned by what they
keep, and by the one property that makes them safe to judge on: they are links to the collected
files, never copies or edits.
"""
import json
import os
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from brake_views import (  # noqa: E402
    brake_state, build, campaigns_under, census, main, run_folders,
)

RECORDING = "records and does not stop (D26-1, D32-1)"


def _run(folder, name, recorded=None, integrity=True):
    run = folder / "runs" / name
    run.mkdir(parents=True)
    (run / "queue_row.json").write_text(json.dumps({"setup": name}), encoding="utf-8")
    (run / "trial.log").write_text("measured\n", encoding="utf-8")
    if integrity:
        (run / "integrity.json").write_text(
            json.dumps({"verdict": "count", "recorded": recorded or {}}), encoding="utf-8")
    return run


def _campaign(root, pair, name, runs):
    folder = root / pair / name
    folder.mkdir(parents=True)
    (folder / "COLLECTED.json").write_text(json.dumps({"profile": pair}), encoding="utf-8")
    stage = folder / "runs" / "azure" / "stage1" / (pair + "_20260927T000000Z")
    stage.mkdir(parents=True)
    (stage / "designs.txt").write_text("design\n", encoding="utf-8")
    for run_name, recorded in runs:
        _run(folder, run_name, recorded)
    return folder


def _three(tmp_path):
    return _campaign(tmp_path / "campaigns", "arm", "a9_20260925T231103Z", [
        ("law_a9_r001-a1", {"trip_median_ms": 1.0}),
        ("law_a9_r002-a1", {"gotit_brake": RECORDING,
                            "gotit_steady": {"ok": True, "value": 0.1}}),
        ("law_a9_r003-a1", {"gotit_brake": RECORDING,
                            "gotit_steady": {"ok": False, "value": 0.4}}),
        ("law_a9_r004-a1", {"gotit_brake": RECORDING}),
    ])


class TestTheStateOfARun:
    def test_a_run_without_the_recording_note_was_taken_while_the_brake_stopped(self, tmp_path):
        assert brake_state(_run(tmp_path, "r", {"trip_median_ms": 1.0})) == "stopping"

    def test_a_recorded_run_whose_check_held_is_recorded(self, tmp_path):
        run = _run(tmp_path, "r", {"gotit_brake": RECORDING, "gotit_steady": {"ok": True}})
        assert brake_state(run) == "recorded"

    def test_a_recorded_run_whose_check_failed_is_flagged(self, tmp_path):
        run = _run(tmp_path, "r", {"gotit_brake": RECORDING, "gotit_steady": {"ok": False}})
        assert brake_state(run) == "flagged"

    def test_a_recorded_run_the_brake_could_not_judge_is_recorded(self, tmp_path):
        """Before a setup has two earlier runs the brake cannot judge; nothing flags the run."""
        assert brake_state(_run(tmp_path, "r", {"gotit_brake": RECORDING})) == "recorded"

    def test_a_run_with_no_integrity_record_is_not_called_recorded(self, tmp_path):
        """The judges leave such a run out anyway; it is not something the brake recorded."""
        assert brake_state(_run(tmp_path, "r", integrity=False)) == "stopping"

    def test_an_integrity_record_that_is_not_json_is_not_called_recorded(self, tmp_path):
        run = _run(tmp_path, "r", integrity=False)
        (run / "integrity.json").write_text("{not json", encoding="utf-8")
        assert brake_state(run) == "stopping"


class TestTheCensus:
    def test_each_state_is_counted_and_the_flagged_runs_named(self, tmp_path):
        _three(tmp_path)
        (row,) = census(str(tmp_path / "campaigns"))
        assert (row["stopping"], row["recorded"], row["flagged"], row["runs"]) == (1, 2, 1, 4)
        assert row["flagged_runs"] == ["law_a9_r003-a1"]

    def test_only_campaign_folders_are_read(self, tmp_path):
        _three(tmp_path)
        (tmp_path / "campaigns" / "NOTES.txt").write_text("x", encoding="utf-8")
        (tmp_path / "campaigns" / "arm" / "no_collected_note").mkdir()
        assert [c[1] for c in campaigns_under(str(tmp_path / "campaigns"))] == [
            "a9_20260925T231103Z"]

    def test_the_stage_folder_is_not_a_run(self, tmp_path):
        folder = _three(tmp_path)
        assert run_folders(str(folder)) == [
            "law_a9_r001-a1", "law_a9_r002-a1", "law_a9_r003-a1", "law_a9_r004-a1"]


class TestTheViews:
    def test_unflagged_leaves_out_the_flagged_run_only(self, tmp_path):
        _three(tmp_path)
        (row,) = build(str(tmp_path / "campaigns"), str(tmp_path / "views"), "unflagged")
        assert row["kept"] == 3 and row["left_out"] == ["law_a9_r003-a1"]
        kept = tmp_path / "views" / "unflagged" / "arm" / "a9_20260925T231103Z"
        assert run_folders(str(kept)) == ["law_a9_r001-a1", "law_a9_r002-a1", "law_a9_r004-a1"]

    def test_stopping_keeps_only_the_runs_taken_while_the_brake_stopped(self, tmp_path):
        _three(tmp_path)
        (row,) = build(str(tmp_path / "campaigns"), str(tmp_path / "views"), "stopping")
        assert row["kept"] == 1
        assert row["left_out"] == ["law_a9_r002-a1", "law_a9_r003-a1", "law_a9_r004-a1"]

    def test_a_view_is_links_to_the_collected_files_with_the_note_and_stage(self, tmp_path):
        folder = _three(tmp_path)
        build(str(tmp_path / "campaigns"), str(tmp_path / "views"), "unflagged")
        view = tmp_path / "views" / "unflagged" / "arm" / "a9_20260925T231103Z"
        original = folder / "runs" / "law_a9_r001-a1" / "trial.log"
        linked = view / "runs" / "law_a9_r001-a1" / "trial.log"
        assert os.path.samefile(original, linked), "a view must link, never copy"
        assert (view / "COLLECTED.json").exists()
        assert list((view / "runs" / "azure" / "stage1").iterdir())
        said = json.loads((tmp_path / "views" / "unflagged" / "VIEW.json").read_text())
        assert said["view"] == "unflagged" and said["keeps"] == ["stopping", "recorded"]

    def test_a_campaign_with_no_stage_folder_is_laid_out_without_one(self, tmp_path):
        root = tmp_path / "campaigns"
        folder = root / "arm" / "c0_20260922T015512Z"
        folder.mkdir(parents=True)
        (folder / "COLLECTED.json").write_text("{}", encoding="utf-8")
        _run(folder, "law_c0_r001-a1", {"trip_median_ms": 1.0})
        (row,) = build(str(root), str(tmp_path / "views"), "stopping")
        assert row["kept"] == 1
        assert not (tmp_path / "views" / "stopping" / "arm" / "c0_20260922T015512Z" / "runs"
                    / "azure").exists()

    def test_a_view_is_laid_out_once(self, tmp_path):
        _three(tmp_path)
        build(str(tmp_path / "campaigns"), str(tmp_path / "views"), "unflagged")
        with pytest.raises(ValueError, match="laid out once"):
            build(str(tmp_path / "campaigns"), str(tmp_path / "views"), "unflagged")

    def test_there_is_no_third_view(self, tmp_path):
        with pytest.raises(ValueError, match="the views are"):
            build(str(tmp_path), str(tmp_path / "views"), "all")


class TestTheCommandLine:
    def test_count_names_the_campaigns_the_brake_recorded_in(self, tmp_path, capsys):
        _three(tmp_path)
        _campaign(tmp_path / "campaigns", "arm", "a4_20260918T213410Z",
                  [("law_a4_r001-a1", {"trip_median_ms": 1.0})])
        assert main(["count", "--campaigns", str(tmp_path / "campaigns")]) == 0
        out = capsys.readouterr().out
        assert "a9_20260925T231103Z: 4 runs, 1 taken while the brake stopped, 2 recorded, " \
               "1 flagged law_a9_r003-a1" in out
        assert "a4_" not in out, "a campaign the brake never recorded in is not listed"

    def test_build_lays_out_both_views(self, tmp_path, capsys):
        _three(tmp_path)
        assert main(["build", "--campaigns", str(tmp_path / "campaigns"),
                     "--out", str(tmp_path / "views")]) == 0
        out = capsys.readouterr().out
        assert "stopping: 1 campaigns, 1 runs kept, 3 left out" in out
        assert "unflagged: 1 campaigns, 3 runs kept, 1 left out" in out

    def test_an_error_is_a_sentence_and_a_code(self, tmp_path, capsys):
        assert main(["count", "--campaigns", str(tmp_path / "absent")]) == 2
        assert capsys.readouterr().out.startswith("ERROR:")
