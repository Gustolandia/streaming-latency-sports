"""The Pub/Sub load test in freeze 38's block, read after its runs (scripts/pubsub_post_hoc.py): its
controller's percentile search run again on the counts its driver logged, held to what each run
printed, on runs shaped as cloud/azure/tools.sh leaves them."""
import csv
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import pubsub_post_hoc as ph  # noqa: E402

F38 = Path(__file__).resolve().parents[1] / "fixtures" / "tools_f38"


def _run(root, folder, name, fixture=None, text=None):
    path = root / folder / name
    path.mkdir(parents=True)
    if fixture is not None:
        shutil.copy(F38 / fixture, path / "tool.txt")
    if text is not None:
        (path / "tool.txt").write_text(text, encoding="utf-8")
    return path


def _block(root):
    """One round of the pilots' runs and the block's second round's stepped run, as tools.sh
    names their folders, beside a folder no run of this tool leaves and a run that left nothing;
    and the round's reference, kept in its zero step's folder, whose own output is not there."""
    _run(root, "tools_v41", "t2-pubsub-loadtest-control", "pubsub-loadtest_t2_control.txt")
    _run(root, "tools_v41", "t2-pubsub-loadtest-26_629ms", "pubsub-loadtest_t2_offset.txt")
    _run(root, "tools_v41", "t4-pubsub-loadtest", "pubsub-loadtest_t4_ahead.txt")
    _run(root, "tools_v41", "s1-pubsub-loadtest-stepped", "pubsub-loadtest_s1_stepped_round2.txt")
    _run(root, "tools_v41", "s1-pubsub-loadtest-control", "pubsub-loadtest_s1_control_round2.txt")
    _run(root, "tools_v41", "t3-pubsub-loadtest-l0-firstno")
    _run(root, "tools_v41", "t2-quiver-4_000ms", "pubsub-loadtest_t2_control.txt")
    zero = _run(root, "tools_v41", "t1-pubsub-loadtest-0ms")
    shutil.copy(F38 / "pubsub-loadtest_t2_control.txt", zero / "reference.log")
    return root


class TestTheControllersSearch:
    def test_a_median_lies_where_the_counts_below_fall_short_of_half(self):
        assert ph.controller_bucket([0, 0, 3, 3], 50.0) == 2
        assert ph.controller_bucket([0, 0, 2, 4], 50.0) == 3

    def test_half_in_bucket_0_has_it_throw(self):
        assert ph.controller_bucket([3, 0, 3], 50.0) is None
        assert ph.controller_bucket([1, 0, 3], 50.0) == 2

    def test_no_counts_give_bucket_0(self):
        assert ph.controller_bucket([], 50.0) == 0

    def test_a_99th_percentile_reaches_the_top(self):
        assert ph.controller_bucket([0] * 7 + [117, 2, 1], 99.0) == 8


class TestTheRuns:
    def test_each_run_read_again(self, tmp_path):
        rows = {(r["stage"], r["run"]): r for r in ph.runs(str(_block(tmp_path)))}
        assert sorted(rows) == [("s1", "control"), ("s1", "stepped"), ("t1", "reference"),
                                ("t2", "26_629ms"), ("t2", "control"), ("t4", "ahead")]
        assert rows[("t1", "reference")]["median_bucket"] == 8
        control = rows[("t2", "control")]
        assert (control["median_bucket"], control["median_throws"], control["counted"]) == (
            8, False, 120)
        assert control["printed_p50_high"] == 25.62890625 and control["kept"] == 120
        moved = rows[("t2", "26_629ms")]
        assert (moved["median_bucket"], moved["median_throws"], moved["bucket0"]) == ("", True, 101)
        assert moved["printed_p50_low"] == "" and moved["kept"] == "" and moved["thrown"] == 1
        assert rows[("t4", "ahead")]["median_bucket"] == 17

    def test_the_stepped_run_whose_median_fell_two_buckets(self):
        """Round 2's stepped run: its first burst came with a running duration below zero, the steps
        put 17 of its 80 counted values in bucket 0, and its median stays in bucket 7 without them,
        two below its control's."""
        text = (F38 / "pubsub-loadtest_s1_stepped_round2.txt").read_text(encoding="utf-8")
        row = ph._row("2", "s1-pubsub-loadtest-stepped", text)
        assert (row["counted"], row["kept"], row["bucket0"]) == (80, 80, 17)
        assert (row["median_bucket"], row["median_bucket_without_0"]) == (7, 7)
        assert (row["low_bucket"], row["high_bucket"]) == (0, 9)
        assert float(row["first_burst_s"]) < 0 and row["set_aside"] == 1
        control = ph._row("2", "s1-pubsub-loadtest-control", (
            F38 / "pubsub-loadtest_s1_control_round2.txt").read_text(encoding="utf-8"))
        assert control["median_bucket"] == 9 and float(control["first_burst_s"]) > 0

    def test_a_round_whose_folder_is_missing_has_no_rows(self, tmp_path):
        assert ph.runs(str(tmp_path)) == []

    def test_a_round_without_its_reference_has_its_runs_alone(self, tmp_path):
        _run(tmp_path, "tools_v41_round2", "t4-pubsub-loadtest", "pubsub-loadtest_t4_ahead.txt")
        (row,) = ph.runs(str(tmp_path))
        assert (row["round"], row["stage"], row["run"]) == ("2", "t4", "ahead")

    def test_a_run_whose_search_disagrees_with_what_it_printed_stops_the_reading(self):
        text = (F38 / "pubsub-loadtest_t2_control.txt").read_text(encoding="utf-8")
        wrong = text.replace("50%: 17.0859375 - 25.62890625", "50%: 7.59375 - 11.390625", 1)
        assert wrong != text
        with pytest.raises(ValueError, match="gives bucket 8, and it printed"):
            ph._row("1", "t2-pubsub-loadtest-control", wrong)

    def test_a_run_read_without_its_burn_in_stops_the_reading(self):
        """The first pilot's zero step was printed before its runner gave the burn-in's length, so
        every response is read as past it, the start-up burst of 40 slow values among them, and its
        controller's search on those counts lands a bucket above the median it printed."""
        text = (F38 / "pubsub-loadtest_t1_zero_step.txt").read_text(encoding="utf-8")
        with pytest.raises(ValueError, match=r"gives bucket 8, and it printed \[11.390625"):
            ph._row("1", "t1-pubsub-loadtest-0ms", text)

    def test_a_run_that_printed_nothing_and_threw_nothing_stops_the_reading(self):
        text = (F38 / "pubsub-loadtest_t2_offset.txt").read_text(encoding="utf-8")
        quiet = text.replace("Programming error: negative values appear in buckets.", "")
        with pytest.raises(ValueError, match="printed nothing for its subscriber"):
            ph._row("1", "t2-pubsub-loadtest-26_629ms", quiet)

    def test_a_run_with_no_counts_logged(self):
        """A console with no check response in it: no counts, so its controller's search gives
        bucket 0, whose range it prints as 0 to 1 ms; nothing counted, set aside or timed."""
        text = "\n".join([
            "# pubsub driver's console",
            "[main] INFO com.google.pubsub.flic.Driver - Results for cps-gcloud-java-subscriber:",
            "[main] INFO com.google.pubsub.flic.Driver - 50%: 0.0 - 1.0",
            "# pubsub driver's exit status", "0", ""])
        row = ph._row("1", "t1-pubsub-loadtest-0ms", text)
        assert (row["counted"], row["bucket0"], row["low_bucket"], row["high_bucket"]) == (
            0, 0, "", "")
        assert (row["median_bucket"], row["median_bucket_without_0"]) == (0, "")
        assert (row["first_burst_s"], row["set_aside"], row["kept"]) == ("", "", "")


class TestMain:
    def test_it_writes_the_table(self, tmp_path, capsys):
        out = tmp_path / "out" / "pubsub_runs.csv"
        assert ph.main(["--root", str(_block(tmp_path / "root")), "--out", str(out)]) == 0
        with out.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 6 and tuple(rows[0]) == ph.FIELDS
        assert rows[-1]["run"] == "reference"
        assert "6 runs read again" in capsys.readouterr().out

    def test_no_runs_is_said_and_writes_nothing(self, tmp_path, capsys):
        out = tmp_path / "pubsub_runs.csv"
        assert ph.main(["--root", str(tmp_path), "--out", str(out)]) == 1
        assert not out.exists() and "no Pub/Sub load test runs" in capsys.readouterr().out
