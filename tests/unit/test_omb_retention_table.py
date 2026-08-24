"""Tests for omb_retention_table.

This script produces a table the paper will print, so the tests are mostly about the two claims
that table makes: that the reported median is insensitive to how much data survived, and that the
reported average moves inversely with retention. Both are properties of the join, so a join that
silently pairs the wrong result file would fabricate them.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from omb_retention_table import (  # noqa: E402
    FIELDS, collect, main, parse_cell, report, spearman,
)


def pub_lines(*p50s, avg=0.9):
    """OMB's per-interval progress lines, which carry unquantised publish latency."""
    return "".join(
        f"INFO WorkloadGenerator - Pub rate 500.0 msg/s | "
        f"Pub Latency (ms) avg: {avg} - 50%: {v} - 99%: 4.3 - Max: 18.3\n"
        for v in p50s)


def make_cell(root, campaign, name, *, kept=1821, zero=118608, neg=0,
              stamp="2026-07-26-14-44-01", omb_dir=None, result=None, write_json=True,
              pub=None):
    d = root / campaign / name
    d.mkdir(parents=True, exist_ok=True)
    jname = f"omb_workload-Kafka-{stamp}.json"
    (d / "omb_stdout.log").write_text(
        "filler\n" * 20
        + (pub if pub is not None else "")
        + f"INFO Benchmark - Writing test result into {jname}\n"
        + f"SBL_DISCARD_SUMMARY kept={kept} zero={zero} negative={neg} "
          "most_negative_micros=0\n",
        encoding="utf-8")
    if write_json and omb_dir is not None:
        omb_dir.mkdir(parents=True, exist_ok=True)
        payload = result if result is not None else {
            "endToEndLatency50pct": [1.0], "endToEndLatency99pct": [6.0],
            "endToEndLatencyMax": [8.0], "endToEndLatencyAvg": [1.2308]}
        (omb_dir / jname).write_text(json.dumps(payload), encoding="utf-8")
    return d


class TestJoin:
    def test_a_cell_is_joined_to_the_result_it_names(self, tmp_path):
        omb = tmp_path / "omb"
        d = make_cell(tmp_path / "ext", "load_sweep", "l0_rep1", omb_dir=omb)
        row = parse_cell(str(d), str(omb))
        assert row["kept"] == 1821 and row["discarded_zero"] == 118608
        assert row["omb_p50_ms"] == 1.0 and row["omb_avg_ms"] == pytest.approx(1.2308)
        assert row["retention_pct"] == pytest.approx(100 * 1821 / 120429, abs=1e-3)

    def test_the_named_file_is_used_not_the_newest(self, tmp_path):
        """A proximity join would pair this cell with the later, unrelated result."""
        omb = tmp_path / "omb"
        d = make_cell(tmp_path / "ext", "c", "l0_rep1", omb_dir=omb,
                      stamp="2026-07-26-10-00-00")
        (omb / "omb_workload-Kafka-2026-07-26-23-59-59.json").write_text(
            json.dumps({"endToEndLatency50pct": [999.0]}), encoding="utf-8")
        assert parse_cell(str(d), str(omb))["omb_p50_ms"] == 1.0

    def test_the_last_summary_and_last_json_name_win(self, tmp_path):
        omb = tmp_path / "omb"
        d = make_cell(tmp_path / "ext", "c", "l0_rep1", omb_dir=omb)
        with (d / "omb_stdout.log").open("a", encoding="utf-8") as fh:
            fh.write("SBL_DISCARD_SUMMARY kept=5 zero=5 negative=1 most_negative_micros=-9\n")
        row = parse_cell(str(d), str(omb))
        assert row["kept"] == 5 and row["discarded_negative"] == 1

    def test_scalar_result_fields_are_accepted(self, tmp_path):
        omb = tmp_path / "omb"
        d = make_cell(tmp_path / "ext", "c", "l0_rep1", omb_dir=omb,
                      result={"endToEndLatency50pct": 2.0, "endToEndLatencyAvg": 2.5})
        row = parse_cell(str(d), str(omb))
        assert row["omb_p50_ms"] == 2.0 and row["omb_p99_ms"] is None

    def test_an_empty_list_field_is_none(self, tmp_path):
        omb = tmp_path / "omb"
        d = make_cell(tmp_path / "ext", "c", "l0_rep1", omb_dir=omb,
                      result={"endToEndLatency50pct": []})
        assert parse_cell(str(d), str(omb))["omb_p50_ms"] is None

    def test_a_cell_whose_result_file_is_gone_is_not_joined(self, tmp_path):
        omb = tmp_path / "omb"
        d = make_cell(tmp_path / "ext", "c", "l0_rep1", omb_dir=omb, write_json=False)
        omb.mkdir(parents=True, exist_ok=True)
        assert parse_cell(str(d), str(omb)) is None

    def test_a_cell_with_no_summary_is_not_joined(self, tmp_path):
        omb = tmp_path / "omb"
        d = tmp_path / "ext" / "c" / "l0_rep1"
        d.mkdir(parents=True)
        (d / "omb_stdout.log").write_text(
            "Writing test result into omb_workload-Kafka-2026-01-01-00-00-00.json\n",
            encoding="utf-8")
        assert parse_cell(str(d), str(omb)) is None

    def test_a_cell_with_no_log_is_not_joined(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        assert parse_cell(str(d), str(tmp_path)) is None

    def test_unparseable_json_is_not_joined(self, tmp_path):
        omb = tmp_path / "omb"
        d = make_cell(tmp_path / "ext", "c", "l0_rep1", omb_dir=omb)
        (omb / "omb_workload-Kafka-2026-07-26-14-44-01.json").write_text("{", encoding="utf-8")
        assert parse_cell(str(d), str(omb)) is None

    def test_publish_latency_is_the_median_of_the_interval_medians(self, tmp_path):
        """One number per run, robust to a slow first interval."""
        omb = tmp_path / "omb"
        d = make_cell(tmp_path / "ext", "c", "l0_rep1", omb_dir=omb,
                      pub=pub_lines(9.9, 0.3, 0.4, 0.4, 0.5))
        row = parse_cell(str(d), str(omb))
        assert row["pub_lat_p50_ms"] == pytest.approx(0.4)
        assert row["pub_lat_avg_ms"] == pytest.approx(0.9)

    def test_a_cell_with_no_progress_lines_has_no_publish_latency(self, tmp_path):
        omb = tmp_path / "omb"
        d = make_cell(tmp_path / "ext", "c", "l0_rep1", omb_dir=omb)
        row = parse_cell(str(d), str(omb))
        assert row["pub_lat_p50_ms"] is None and row["pub_lat_avg_ms"] is None

    def test_a_summary_of_all_zeros_gives_blank_retention_not_a_crash(self, tmp_path):
        omb = tmp_path / "omb"
        d = make_cell(tmp_path / "ext", "c", "l0_rep1", kept=0, zero=0, neg=0, omb_dir=omb)
        assert parse_cell(str(d), str(omb))["retention_pct"] == ""


class TestCollect:
    def test_both_axis_prefixes_are_found_and_sorted(self, tmp_path):
        omb, ext = tmp_path / "omb", tmp_path / "ext"
        make_cell(ext, "resolution", "s200_rep1", omb_dir=omb, stamp="2026-07-26-16-50-14")
        make_cell(ext, "load_sweep", "l0_rep1", omb_dir=omb, stamp="2026-07-26-14-44-01")
        rows = collect(str(ext), str(omb))
        assert [(r["campaign"], r["cell"]) for r in rows] == [
            ("load_sweep", "l0_rep1"), ("resolution", "s200_rep1")]

    def test_a_new_axis_prefix_is_collected_without_being_enumerated(self, tmp_path):
        """The rate-phase campaign uses r500_rep1; an enumerated glob dropped it silently."""
        omb, ext = tmp_path / "omb", tmp_path / "ext"
        make_cell(ext, "rate_phase", "r500_rep1", omb_dir=omb, stamp="2026-07-26-18-00-00")
        make_cell(ext, "rate_phase", "r457_rep1", omb_dir=omb, stamp="2026-07-26-18-10-00")
        rows = collect(str(ext), str(omb))
        assert {r["cell"] for r in rows} == {"r457_rep1", "r500_rep1"}

    def test_unjoinable_cells_are_skipped_silently(self, tmp_path):
        omb, ext = tmp_path / "omb", tmp_path / "ext"
        make_cell(ext, "c", "l0_rep1", omb_dir=omb)
        (ext / "c" / "l9_rep9").mkdir(parents=True)
        assert len(collect(str(ext), str(omb))) == 1

    def test_a_file_matching_the_glob_is_not_treated_as_a_cell(self, tmp_path):
        omb, ext = tmp_path / "omb", tmp_path / "ext"
        make_cell(ext, "c", "l0_rep1", omb_dir=omb)
        (ext / "c" / "l1_rep1").write_text("not a dir", encoding="utf-8")
        assert len(collect(str(ext), str(omb))) == 1

    def test_an_empty_root_collects_nothing(self, tmp_path):
        assert collect(str(tmp_path / "absent"), str(tmp_path)) == []


class TestSpearman:
    def test_a_perfect_inverse_is_minus_one(self):
        assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)

    def test_a_perfect_direct_is_plus_one(self):
        assert spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)

    def test_ties_use_average_ranks(self):
        assert spearman([1, 1, 2, 2], [1, 1, 2, 2]) == pytest.approx(1.0)

    def test_too_few_points_is_none(self):
        assert spearman([1, 2], [2, 1]) is None

    def test_a_constant_series_has_no_correlation(self):
        assert spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None

    def test_non_numeric_entries_are_dropped(self):
        assert spearman(["", 2, 3, 4], [None, 3, 2, 1]) == pytest.approx(-1.0)

    def test_the_measured_direction_is_negative(self):
        """Retention down, reported average up -- the finding the table exists to show."""
        retention = [1.51, 0.83, 100.0, 76.32, 99.40]
        avg = [1.2308, 2.6250, 1.0000, 1.0274, 1.0392]
        assert spearman(retention, avg) < -0.5


class TestReportAndCLI:
    def _two_cells(self, tmp_path):
        omb, ext = tmp_path / "omb", tmp_path / "ext"
        make_cell(ext, "load_sweep", "l0_rep2", kept=998, zero=119414, omb_dir=omb,
                  stamp="2026-07-26-14-53-00",
                  result={"endToEndLatency50pct": [1.0], "endToEndLatency99pct": [10.0],
                          "endToEndLatencyMax": [10.0], "endToEndLatencyAvg": [2.625]})
        make_cell(ext, "load_sweep", "l0_rep3", kept=120425, zero=4, omb_dir=omb,
                  stamp="2026-07-26-15-02-00",
                  result={"endToEndLatency50pct": [1.0], "endToEndLatency99pct": [1.0],
                          "endToEndLatencyMax": [1.0], "endToEndLatencyAvg": [1.0]})
        return ext, omb

    def test_the_report_states_the_p50_is_unmoved(self, tmp_path, capsys):
        ext, omb = self._two_cells(tmp_path)
        report(collect(str(ext), str(omb)))
        out = capsys.readouterr().out
        assert "reported p50 takes 1 distinct value(s): 1.0" in out
        assert "negative samples across every cell: 0" in out
        assert "retention ranges from 0.83% to 100.00%" in out

    def test_an_empty_report_does_not_crash(self, capsys):
        assert report([]) is None

    def test_the_report_states_the_inverse_relationship(self, tmp_path, capsys):
        """With enough cells the correlation is computed, and it is the headline."""
        ext, omb = tmp_path / "ext", tmp_path / "omb"
        spec = [("l0_rep1", 1821, 118608, 1.2308), ("l0_rep2", 998, 119414, 2.6250),
                ("l0_rep3", 120425, 4, 1.0000), ("l50_rep1", 91982, 28542, 1.0274),
                ("l75_rep2", 24376, 96259, 1.7419)]
        for i, (name, kept, zero, avg) in enumerate(spec):
            make_cell(ext, "load_sweep", name, kept=kept, zero=zero, omb_dir=omb,
                      stamp=f"2026-07-26-14-{i:02d}-00",
                      result={"endToEndLatency50pct": [1.0], "endToEndLatency99pct": [4.0],
                              "endToEndLatencyMax": [8.0], "endToEndLatencyAvg": [avg]})
        rho = report(collect(str(ext), str(omb)))
        out = capsys.readouterr().out
        assert rho is not None and rho < -0.5
        assert "Spearman(retention, reported average) = -" in out
        assert "higher latency the more data it drops" in out

    def test_publish_latency_predicting_retention_is_reported_as_independent(self, tmp_path,
                                                                            capsys):
        """If a sub-millisecond, unquantised probe tracks retention, say why that matters."""
        ext, omb = tmp_path / "ext", tmp_path / "omb"
        spec = [("l0_rep1", 200, 100000, 0.2), ("l0_rep2", 30000, 90000, 0.4),
                ("l0_rep3", 80000, 40000, 0.6), ("l0_rep4", 119000, 1000, 0.8)]
        for i, (name, kept, zero, p) in enumerate(spec):
            make_cell(ext, "c", name, kept=kept, zero=zero, omb_dir=omb,
                      stamp=f"2026-07-26-19-{i:02d}-00", pub=pub_lines(p),
                      result={"endToEndLatency50pct": [1.0], "endToEndLatencyAvg": [1.1]})
        rho = report(collect(str(ext), str(omb)))
        out = capsys.readouterr().out
        assert "Spearman(publish latency p50, retention) = +1.000" in out
        assert "independent support" in out
        # These cells share one reported average, so the retention/average correlation is
        # undefined -- correctly None. The publish probe is independent of it, which is the point.
        assert rho is None

    def test_a_weak_publish_correlation_prints_no_explanation(self, tmp_path, capsys):
        """A 0.1 ms spread predicting nothing must not be dressed up as a mechanism."""
        ext, omb = tmp_path / "ext", tmp_path / "omb"
        spec = [("l0_rep1", 200, 100000, 0.4), ("l0_rep2", 30000, 90000, 0.3),
                ("l0_rep3", 80000, 40000, 0.4), ("l0_rep4", 119000, 1000, 0.3)]
        for i, (name, kept, zero, p) in enumerate(spec):
            make_cell(ext, "c", name, kept=kept, zero=zero, omb_dir=omb,
                      stamp=f"2026-07-26-20-{i:02d}-00", pub=pub_lines(p),
                      result={"endToEndLatency50pct": [1.0], "endToEndLatencyAvg": [1.1]})
        report(collect(str(ext), str(omb)))
        assert "independent support" not in capsys.readouterr().out

    def test_a_positive_correlation_prints_no_explanation(self, tmp_path, capsys):
        """The narrative line is asserted by the data, not printed unconditionally."""
        ext, omb = tmp_path / "ext", tmp_path / "omb"
        for i, (name, kept, avg) in enumerate([("l0_rep1", 10, 1.0), ("l0_rep2", 20, 2.0),
                                               ("l0_rep3", 30, 3.0)]):
            make_cell(ext, "c", name, kept=kept, zero=100, omb_dir=omb,
                      stamp=f"2026-07-26-15-{i:02d}-00",
                      result={"endToEndLatencyAvg": [avg]})
        report(collect(str(ext), str(omb)))
        assert "higher latency the more data it drops" not in capsys.readouterr().out

    def test_a_log_longer_than_the_tail_window_still_joins(self, tmp_path):
        """Real logs are ~31 MB; only the tail is read, and the summary lives there."""
        omb, ext = tmp_path / "omb", tmp_path / "ext"
        d = make_cell(ext, "c", "l0_rep1", omb_dir=omb)
        log = d / "omb_stdout.log"
        body = log.read_text(encoding="utf-8")
        log.write_text("PADDING\n" * 100000 + body, encoding="utf-8")
        assert log.stat().st_size > 512 * 1024
        assert parse_cell(str(d), str(omb))["kept"] == 1821

    def test_the_cli_writes_the_table(self, tmp_path, capsys):
        ext, omb = self._two_cells(tmp_path)
        out = tmp_path / "retention.csv"
        assert main(["--root", str(ext), "--omb-dir", str(omb), "--out", str(out)]) == 0
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert len(rows) == 2 and list(rows[0]) == list(FIELDS)
        assert rows[0]["result_json"].endswith(".json")

    def test_nothing_joinable_is_an_error(self, tmp_path, capsys):
        assert main(["--root", str(tmp_path / "absent"), "--omb-dir", str(tmp_path)]) == 1
        assert "could be joined" in capsys.readouterr().out

    def test_no_out_still_prints(self, tmp_path, capsys):
        ext, omb = self._two_cells(tmp_path)
        assert main(["--root", str(ext), "--omb-dir", str(omb)]) == 0
        assert "kept" in capsys.readouterr().out


class TestACorpusWithNoMeasurableRetention:

    def test_the_range_line_is_omitted_rather_than_printed_over_nothing(self, tmp_path,
                                                                        capsys):
        """Retention is kept/(kept+discarded). A cell that recorded no discards at all has no
        percentage, and `min()` over an empty list is not a range -- it is an exception.
        """
        import omb_retention_table as ort
        rows = [{"campaign": "e-x", "cell": "c1", "kept": 0, "discarded_zero": 0,
                 "discarded_negative": 0, "retention_pct": "",
                 "omb_p50_ms": None, "omb_p99_ms": None, "omb_avg_ms": None,
                 "pub_lat_p50_ms": None}]
        ort.report(rows)
        out = capsys.readouterr().out
        assert "retention ranges from" not in out
        assert "negative samples across every cell: 0" in out
