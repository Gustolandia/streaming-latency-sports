"""Tests for analyze_omb_discards.

This script decides whether OMB's discards are the failure the paper is about. The manuscript
already asserted one answer on the strength of a counter that could not tell the two apart, so
the tests that matter are the ones proving the classifier can return each verdict — including the
one that costs us the claim.
"""
import csv
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_omb_discards import (  # noqa: E402
    NEGATIVE_FLOOR, load, main, summarise, verdict,
)


def _rows(axis, spec):
    """spec: (level, zero, negative, kept) tuples."""
    return [{axis: str(lvl), "discarded_zero": str(z), "discarded_negative": str(n),
             "kept": str(k), "most_negative_micros": "0"} for lvl, z, n, k in spec]


class TestSummarise:
    def test_shares_are_over_everything_the_harness_saw(self):
        s = summarise(_rows("load_pct", [(0, 90, 0, 10)]), "load_pct")[0]
        assert s["zero_share"] == pytest.approx(0.9)
        assert s["kept_share"] == pytest.approx(0.1)

    def test_replicates_are_reduced_by_median_not_mean(self):
        rows = _rows("load_pct", [(0, 10, 0, 90), (0, 20, 0, 80), (0, 900, 0, 100)])
        s = summarise(rows, "load_pct")[0]
        assert s["n"] == 3
        assert s["zero_share"] == pytest.approx(0.2), "an outlier rep must not drag the level"

    def test_levels_sort_numerically(self):
        rows = _rows("load_pct", [(88, 1, 0, 1), (0, 1, 0, 1), (50, 1, 0, 1)])
        assert [s["level"] for s in summarise(rows, "load_pct")] == ["0", "50", "88"]

    def test_a_cell_that_saw_nothing_is_dropped(self):
        assert summarise(_rows("load_pct", [(0, 0, 0, 0)]), "load_pct") == []

    def test_unparseable_counts_do_not_crash(self):
        rows = [{"load_pct": "0", "discarded_zero": "n/a", "discarded_negative": "",
                 "kept": "100", "most_negative_micros": ""}]
        assert summarise(rows, "load_pct")[0]["kept_share"] == pytest.approx(1.0)


class TestVerdict:
    def test_zeros_only_is_resolution(self):
        v = verdict(summarise(_rows("load_pct",
                                    [(0, 59000, 0, 1000), (88, 6000, 0, 20000)]), "load_pct"))
        assert v["outcome"].startswith("RESOLUTION")
        assert v["neg_total"] == 0

    def test_the_falling_zero_share_is_detected(self):
        v = verdict(summarise(_rows("load_pct",
                                    [(0, 59000, 0, 1000), (88, 6000, 0, 20000)]), "load_pct"))
        assert v["zero_falls"] and v["zero_last"] < v["zero_first"]

    def test_material_negatives_without_dominant_zeros_is_causality(self):
        v = verdict(summarise(_rows("load_pct",
                                    [(0, 100, 5, 10000), (88, 100, 2000, 10000)]), "load_pct"))
        assert v["outcome"] == "CAUSALITY"

    def test_dominant_zeros_plus_real_negatives_is_both(self):
        """The reading that would mean the single counter hid the interesting failure."""
        v = verdict(summarise(_rows("load_pct",
                                    [(0, 50000, 10, 5000), (88, 50000, 3000, 5000)]), "load_pct"))
        assert v["outcome"] == "BOTH"

    def test_a_handful_of_negatives_is_below_the_floor(self):
        """At these counts a few negatives are not distinguishable from a blip."""
        v = verdict(summarise(_rows("load_pct",
                                    [(0, 50000, 1, 50000), (88, 40000, 2, 50000)]), "load_pct"))
        assert v["max_neg_share"] < NEGATIVE_FLOOR
        assert v["outcome"].startswith("RESOLUTION")

    def test_one_level_cannot_show_a_direction(self):
        v = verdict(summarise(_rows("load_pct", [(0, 100, 0, 100)]), "load_pct"))
        assert not v["decided"] and "two levels" in v["why"]

    def test_zeros_that_do_not_fall_say_so(self):
        v = verdict(summarise(_rows("load_pct",
                                    [(0, 5000, 0, 5000), (88, 5000, 0, 5000)]), "load_pct"))
        assert v["outcome"] == "RESOLUTION (direction untested)"


class TestCLI:
    def _write(self, path, axis, spec):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow([axis, "discarded_zero", "discarded_negative", "kept",
                        "most_negative_micros"])
            for lvl, z, n, k in spec:
                w.writerow([lvl, z, n, k, 0])

    def test_nothing_to_do_is_an_error(self, capsys):
        assert main([]) == 1
        assert "nothing to do" in capsys.readouterr().out

    def test_a_missing_file_is_an_error(self, tmp_path):
        assert main(["--sweep", str(tmp_path / "absent.csv")]) == 1

    def test_a_header_only_file_is_not_a_result(self, tmp_path, capsys):
        p = tmp_path / "s.csv"
        p.write_text("load_pct,discarded_zero\n", encoding="utf-8")
        assert main(["--sweep", str(p)]) == 1
        assert "every cell failed" in capsys.readouterr().out

    def test_it_reports_and_explains_resolution(self, tmp_path, capsys):
        p = tmp_path / "s.csv"
        self._write(p, "load_pct", [(0, 59000, 0, 1000), (88, 6000, 0, 20000)])
        assert main(["--sweep", str(p)]) == 0
        out = capsys.readouterr().out
        assert "RESOLUTION" in out
        assert "not the causality violation this paper is about" in out

    def test_the_summary_csv_carries_every_level(self, tmp_path):
        p = tmp_path / "s.csv"
        self._write(p, "load_pct", [(0, 10, 0, 90), (88, 20, 0, 80)])
        out = tmp_path / "sum.csv"
        main(["--sweep", str(p), "--out", str(out)])
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert [r["level"] for r in rows] == ["0", "88"]
        assert rows[0]["axis"] == "background load"

    def test_both_axes_can_be_read_together(self, tmp_path, capsys):
        a, b = tmp_path / "a.csv", tmp_path / "b.csv"
        self._write(a, "load_pct", [(0, 10, 0, 90), (88, 20, 0, 80)])
        self._write(b, "message_size", [(200, 90, 0, 10), (65536, 5, 0, 95)])
        assert main(["--sweep", str(a), "--resolution", str(b)]) == 0
        out = capsys.readouterr().out
        assert "background load" in out and "message size" in out

    def test_load_reads_the_rows(self, tmp_path):
        p = tmp_path / "s.csv"
        self._write(p, "load_pct", [(0, 1, 0, 1)])
        assert len(load(str(p))) == 1


class TestEdges:
    def test_a_row_missing_the_axis_column_is_skipped(self):
        rows = [{"discarded_zero": "10", "discarded_negative": "0", "kept": "90"}]
        assert summarise(rows, "load_pct") == []

    def test_a_non_numeric_level_still_sorts(self):
        rows = _rows("message_size", [(200, 10, 0, 90)])
        rows.append({"message_size": "default", "discarded_zero": "5",
                     "discarded_negative": "0", "kept": "95", "most_negative_micros": "0"})
        levels = [s["level"] for s in summarise(rows, "message_size")]
        assert set(levels) == {"200", "default"}

    def test_the_worst_negative_is_the_most_negative_seen(self):
        rows = [{"load_pct": "88", "discarded_zero": "0", "discarded_negative": "5",
                 "kept": "100", "most_negative_micros": "-40"},
                {"load_pct": "88", "discarded_zero": "0", "discarded_negative": "5",
                 "kept": "100", "most_negative_micros": "-900"}]
        assert summarise(rows, "load_pct")[0]["most_negative"] == -900

    def test_an_undecided_verdict_prints_as_undecided(self, tmp_path, capsys):
        p = tmp_path / "s.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["load_pct", "discarded_zero", "discarded_negative", "kept",
                        "most_negative_micros"])
            w.writerow([0, 10, 0, 90, 0])
        assert main(["--sweep", str(p)]) == 0
        assert "UNDECIDED" in capsys.readouterr().out
