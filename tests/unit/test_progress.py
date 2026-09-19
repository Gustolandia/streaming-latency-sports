"""Tests for scripts/progress.py.

The share of the experiment that has been run is a number a person will read at a glance and act
on, so what matters is that it counts the right runs: the ones that counted, from campaigns that
came home and from the one running now, each exactly once, and never more of a stage than the
plan set aside for it.
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import progress  # noqa: E402


def write_report(root, profile, label, counted=10, repeated=0):
    """A campaign copied home, with the report collect_runs.py leaves beside it."""
    where = root / profile / label
    where.mkdir(parents=True, exist_ok=True)
    verdicts = {"count": counted}
    if repeated:
        verdicts["repeat"] = repeated
    (where / "quality_report.json").write_text(json.dumps({"verdicts": verdicts, "runs": []}),
                                               encoding="utf-8")
    return where


class TestWhichStageACampaignBelongsTo:

    @pytest.mark.parametrize("label,stage", [
        ("a1_20260918T194622Z", "A1, the slice"),
        ("c0_20260917T231015Z", "stage 0, the instrument"),
        ("p0_20260918T014630Z", "stage 0, the instrument"),
        ("a4_20260918T213410Z", "A4, the Arm pair"),
        ("t3_20260920T000000Z", "T1 to T4, the tools"),
    ])
    def test_the_label_says_which_stage_it_is(self, label, stage):
        assert progress.stage_of(label) == stage

    def test_a_folder_that_belongs_to_no_stage_is_left_out(self):
        assert progress.stage_of("snapshot_20260916T184448Z") is None
        assert progress.stage_of("quarantine") is None

    def test_a_whole_path_is_read_by_its_own_name(self, tmp_path):
        assert progress.stage_of(str(tmp_path / "matched" / "a1_x")) == "A1, the slice"

    def test_the_plan_totals_what_its_table_says(self):
        assert progress.TOTAL == 3590, "the campaigns table of freeze 04"
        assert sum(runs for _, _, runs in progress.PLAN) == progress.TOTAL


class TestCountingWhatCameHome:

    def test_it_counts_the_runs_that_counted(self, tmp_path):
        write_report(tmp_path, "matched", "a1_one", counted=92)
        write_report(tmp_path, "matched", "c0_one", counted=56, repeated=3)
        found = progress.counted(str(tmp_path))
        assert found == {"A1, the slice": 92, "stage 0, the instrument": 56}, \
            "a run that was repeated is not a run the plan asked for"

    def test_campaigns_of_one_stage_add_up(self, tmp_path):
        for label in ("a1_one", "a1_two", "a1_three"):
            write_report(tmp_path, "matched", label, counted=60)
        assert progress.counted(str(tmp_path))["A1, the slice"] == 180

    def test_a_folder_it_cannot_read_is_passed_over(self, tmp_path):
        write_report(tmp_path, "matched", "a1_one", counted=92)
        bad = tmp_path / "matched" / "a1_broken"
        bad.mkdir(parents=True)
        (bad / "quality_report.json").write_text("{oh dear", encoding="utf-8")
        assert progress.counted(str(tmp_path)) == {"A1, the slice": 92}

    def test_nothing_collected_yet_is_no_runs(self, tmp_path):
        assert progress.counted(str(tmp_path)) == {}

    def test_what_is_not_a_campaign_of_the_plan_is_not_counted(self, tmp_path):
        """A folder of everything a driver held, copied before a pair is deleted, is not runs."""
        write_report(tmp_path, "matched", "a1_one", counted=92)
        write_report(tmp_path, "matched", "snapshot_20260916T184448Z", counted=400)
        assert progress.counted(str(tmp_path)) == {"A1, the slice": 92}


class TestTheCampaignRunningNow:

    def test_its_finished_runs_count_too(self):
        found = progress.add_live({"A1, the slice": 92}, {"a1_20260918T194622Z": 41})
        assert found["A1, the slice"] == 133

    def test_a_queue_of_no_stage_adds_nothing(self):
        assert progress.add_live({}, {"probe_of_something": 7}) == {}

    def test_nothing_running_changes_nothing(self):
        assert progress.add_live({"A1, the slice": 5}, None) == {"A1, the slice": 5}

    def test_it_does_not_change_what_it_was_given(self):
        came_home = {"A1, the slice": 92}
        progress.add_live(came_home, {"a1_x": 41})
        assert came_home == {"A1, the slice": 92}


class TestTheShare:

    def test_it_is_the_runs_done_over_the_runs_the_plan_asks_for(self):
        done, total, pct = progress.share({"A1, the slice": 296})
        assert done == 296 and total == 3590 and pct == pytest.approx(8.2, abs=0.1)

    def test_a_stage_never_counts_for_more_than_the_plan_set_aside(self):
        """A session calibration that had to be run again is work the plan asks for, but it does
        not make the experiment more complete."""
        done, _, _ = progress.share({"stage 0, the instrument": 579})
        assert done == 414

    def test_nothing_done_is_nothing(self):
        assert progress.share({}) == (0, 3590, 0.0)

    def test_everything_done_is_everything(self):
        every = dict((name, runs) for name, _, runs in progress.PLAN)
        assert progress.share(every) == (3590, 3590, 100.0)


class TestHowItReads:

    def test_the_one_line_names_the_share(self):
        said = progress.line({"A1, the slice": 296, "stage 0, the instrument": 414})
        assert said == "progress: 710 of 3,590 runs the plan asks for (19.8%)"

    def test_the_whole_picture_names_every_stage(self):
        said = progress.lines({"A1, the slice": 296})
        assert said[0].startswith("progress: 296 of 3,590")
        assert any("A1, the slice" in row and "296 of  592" in row for row in said)
        assert any("T1 to T4, the tools" in row for row in said)

    def test_a_stage_that_ran_more_than_its_share_says_so(self):
        said = "\n".join(progress.lines({"stage 0, the instrument": 579}))
        assert "414 of  414" in said and "and 165 more, which the plan did not set aside" in said


class TestTheCommand:

    def run(self, argv):
        out = io.StringIO()
        return progress.main(argv, out=out), out.getvalue()

    def test_it_reads_what_came_home(self, tmp_path):
        write_report(tmp_path, "matched", "a1_one", counted=92)
        code, said = self.run(["show", "--collected", str(tmp_path)])
        assert code == 0 and "progress: 92 of 3,590" in said and "A1, the slice" in said

    def test_it_can_say_the_one_line_alone(self, tmp_path):
        write_report(tmp_path, "matched", "a1_one", counted=92)
        code, said = self.run(["show", "--collected", str(tmp_path), "--quiet"])
        assert code == 0 and said.strip() == "progress: 92 of 3,590 runs the plan asks for (2.6%)"

    def test_a_folder_that_is_not_there_reads_as_nothing_done(self, tmp_path):
        code, said = self.run(["show", "--collected", str(tmp_path / "nowhere")])
        assert code == 0 and "progress: 0 of 3,590" in said

    def test_a_folder_it_cannot_walk_at_all_is_one_line_not_a_crash(self, monkeypatch):
        def refuse(_where):
            raise OSError("the folder cannot be read")
        monkeypatch.setattr(progress, "counted", refuse)
        code, said = self.run(["show"])
        assert code == 2 and said.startswith("ERROR: the folder cannot be read")
