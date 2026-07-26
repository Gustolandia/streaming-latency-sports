"""Tests for compare_campaign_passes.

The comparison exists to answer a question about our own reporting: is a three-replicate median
of OMB's retention a number worth publishing? The NOT REPRODUCIBLE verdict is the one that costs
us the per-level table in our own first sweep, so it is the one most of these tests exercise.
"""
import csv
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from compare_campaign_passes import (  # noqa: E402
    REPRODUCIBLE_PTS, compare, load, main, report, retention_by_level, verdict,
)

FIELDS = ("campaign", "cell", "axis", "level", "valid", "count_source", "zero_share")


def write_ledger(path, rows):
    """rows: (campaign, level, retention_pct) or (campaign, level, retention_pct, kwargs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for i, row in enumerate(rows):
            campaign, level, ret = row[:3]
            extra = row[3] if len(row) > 3 else {}
            w.writerow([campaign, f"l{level}_rep{i}", extra.get("axis", "load_pct"), level,
                        extra.get("valid", "1"), extra.get("count_source", "shutdown_hook"),
                        "" if ret is None else 1.0 - ret / 100.0])


class TestRetentionByLevel:
    def test_retention_is_derived_from_the_zero_share(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", "0", 1.51)])
        got = retention_by_level(load(str(p)), "load_sweep", "load_pct")
        assert got["0"][0] == pytest.approx(1.51)

    def test_only_the_named_campaign_contributes(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", "0", 10.0), ("load_sweep_p2", "0", 90.0)])
        got = retention_by_level(load(str(p)), "load_sweep", "load_pct")["0"]
        assert got == pytest.approx([10.0])

    def test_invalid_and_quantised_cells_are_excluded(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("c", "0", 10.0, {"valid": "0"}),
                         ("c", "0", 20.0, {"count_source": "periodic_quantised"}),
                         ("c", "0", 30.0)])
        assert retention_by_level(load(str(p)), "c", "load_pct")["0"] == pytest.approx([30.0])

    def test_the_other_axis_is_excluded(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("c", "0", 10.0), ("c", "200", 20.0, {"axis": "message_size"})])
        assert list(retention_by_level(load(str(p)), "c", "load_pct")) == ["0"]

    def test_a_blank_zero_share_is_skipped(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("c", "0", None), ("c", "0", 50.0)])
        assert retention_by_level(load(str(p)), "c", "load_pct")["0"] == pytest.approx([50.0])


class TestCompare:
    def test_medians_and_deltas_per_level(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("a", "0", 1.0), ("a", "0", 2.0), ("a", "0", 3.0),
                         ("b", "0", 10.0), ("b", "0", 20.0), ("b", "0", 30.0)])
        c = compare(load(str(p)), "a", "b", "load_pct")[0]
        assert c["median_a"] == pytest.approx(2.0)
        assert c["median_b"] == pytest.approx(20.0)
        assert c["delta_pts"] == pytest.approx(18.0)
        assert c["n_a"] == 3 and c["n_b"] == 3

    def test_spread_is_reported_and_is_none_for_a_single_cell(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("a", "0", 1.0), ("a", "0", 99.0), ("b", "0", 50.0)])
        c = compare(load(str(p)), "a", "b", "load_pct")[0]
        assert c["spread_a"] == pytest.approx(98.0)
        assert c["spread_b"] is None

    def test_levels_sort_numerically(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("a", "88", 1.0), ("a", "0", 1.0), ("a", "50", 1.0)])
        assert [c["level"] for c in compare(load(str(p)), "a", "b", "load_pct")] == \
            ["0", "50", "88"]

    def test_a_non_numeric_level_still_sorts(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("a", "0", 1.0), ("a", "default", 1.0)])
        levels = [c["level"] for c in compare(load(str(p)), "a", "b", "load_pct")]
        assert set(levels) == {"0", "default"}

    def test_a_level_present_in_only_one_pass_has_no_delta(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("a", "0", 1.0), ("b", "95", 1.0)])
        cs = {c["level"]: c for c in compare(load(str(p)), "a", "b", "load_pct")}
        assert cs["0"]["delta_pts"] is None and cs["95"]["delta_pts"] is None


class TestVerdict:
    def test_close_medians_are_reproducible(self):
        c = [{"delta_pts": 2.0}, {"delta_pts": 4.0}]
        v = verdict(c)
        assert v["outcome"] == "REPRODUCIBLE" and v["worst"] == 4.0

    def test_a_single_bad_level_decides_it(self):
        """One unreproducible level is enough; the table is published as a whole."""
        v = verdict([{"delta_pts": 1.0}, {"delta_pts": 60.0}])
        assert v["outcome"] == "NOT REPRODUCIBLE" and v["worst"] == 60.0

    def test_the_boundary_counts_as_reproducible(self):
        assert verdict([{"delta_pts": REPRODUCIBLE_PTS}])["outcome"] == "REPRODUCIBLE"

    def test_no_shared_level_is_undecided(self):
        v = verdict([{"delta_pts": None}])
        assert not v["decided"] and "no level" in v["why"]


class TestReportAndCLI:
    def _ledger(self, tmp_path, rows):
        p = tmp_path / "ledger.csv"
        write_ledger(p, rows)
        return p

    def test_the_unreproducible_verdict_turns_the_finding_on_us(self, tmp_path, capsys):
        p = self._ledger(tmp_path, [("a", "0", 1.51), ("a", "0", 0.83), ("a", "0", 100.0),
                                    ("b", "0", 95.0), ("b", "0", 99.0), ("b", "0", 100.0)])
        report(compare(load(str(p)), "a", "b", "load_pct"), "a", "b", "load_pct")
        out = capsys.readouterr().out
        assert "NOT REPRODUCIBLE" in out
        assert "applies to our own first sweep" in out

    def test_a_reproducible_pair_says_three_replicates_suffice(self, tmp_path, capsys):
        p = self._ledger(tmp_path, [("a", "0", 50.0), ("a", "0", 51.0), ("a", "0", 52.0),
                                    ("b", "0", 50.5), ("b", "0", 51.5), ("b", "0", 52.5)])
        report(compare(load(str(p)), "a", "b", "load_pct"), "a", "b", "load_pct")
        out = capsys.readouterr().out
        assert "REPRODUCIBLE" in out and "NOT REPRODUCIBLE" not in out
        assert "three replicates suffice" in out

    def test_an_undecided_comparison_prints_undecided(self, tmp_path, capsys):
        p = self._ledger(tmp_path, [("a", "0", 1.0)])
        report(compare(load(str(p)), "a", "b", "load_pct"), "a", "b", "load_pct")
        assert "UNDECIDED" in capsys.readouterr().out

    def test_the_cli_writes_the_csv(self, tmp_path, capsys):
        p = self._ledger(tmp_path, [("a", "0", 1.0), ("a", "0", 2.0),
                                    ("b", "0", 80.0), ("b", "0", 90.0)])
        out = tmp_path / "cmp.csv"
        assert main(["--ledger", str(p), "--pass-a", "a", "--pass-b", "b",
                     "--axis", "load_pct", "--out", str(out)]) == 0
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert rows[0]["level"] == "0" and float(rows[0]["delta_pts"]) > 10

    def test_a_missing_ledger_is_an_error(self, tmp_path, capsys):
        assert main(["--ledger", str(tmp_path / "absent.csv")]) == 1
        assert "missing" in capsys.readouterr().out

    def test_no_matching_campaigns_is_an_error(self, tmp_path, capsys):
        p = self._ledger(tmp_path, [("a", "0", 1.0)])
        assert main(["--ledger", str(p), "--pass-a", "x", "--pass-b", "y"]) == 1
        assert "no cells" in capsys.readouterr().out

    def test_no_out_still_reports(self, tmp_path, capsys):
        p = self._ledger(tmp_path, [("a", "0", 1.0), ("b", "0", 2.0)])
        assert main(["--ledger", str(p), "--pass-a", "a", "--pass-b", "b"]) == 0
        assert "per-level retention" in capsys.readouterr().out
