"""Tests for index_external_campaigns.

The point of this ledger is that a 31 MB cell log can be deleted once its row exists. That makes
two properties load-bearing, and they are what these tests are mostly about:

  * a failed or invalid cell still appears, with the reason -- otherwise a sweep quietly becomes
    a selection of the runs that worked;
  * a count taken from the quantised periodic lines is never presented as if it were exact.
"""
import csv
import hashlib
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from index_external_campaigns import (  # noqa: E402
    FIELDS, index_cell, invalid_reason, is_cell, main, parse_cell_name, parse_counts,
    parse_result_csv, parse_workload, read_tail, sha256_of, walk, zero_share,
)

SUMMARY = "SBL_DISCARD_SUMMARY kept=1821 zero=118608 negative=0 most_negative_micros=0"
RESULT_ROW = ("OpenMessaging Benchmark,embedded,1,118608,118608,0,0,1821,24,3,0,"
              "10.0.1.221:19092")
WORKLOAD = ("name: sbl-audit\ntopics: 1\nmessageSize: 200\nproducerRate: 500\n"
            "testDurationMinutes: 3\n")


def make_cell(root, campaign, name, *, log=SUMMARY, result=RESULT_ROW, workload=WORKLOAD):
    d = root / campaign / name
    d.mkdir(parents=True)
    if log is not None:
        (d / "omb_stdout.log").write_text("noise\n" * 50 + log + "\n", encoding="utf-8")
    if result is not None:
        (d / "omb_loaded_result.csv").write_text(result + "\n", encoding="utf-8")
    if workload is not None:
        (d / "omb_workload.yaml").write_text(workload, encoding="utf-8")
    return d


class TestCellName:
    def test_load_level_and_rep(self):
        assert parse_cell_name("l88_rep2") == {"axis": "load_pct", "level": "88", "rep": "2"}

    def test_message_size_axis(self):
        assert parse_cell_name("s4096_rep1") == {"axis": "message_size", "level": "4096",
                                                 "rep": "1"}

    def test_an_unrecognised_name_is_blank_not_an_error(self):
        """A cell whose directory we did not name still gets a row."""
        assert parse_cell_name("smoke") == {"axis": "", "level": "", "rep": ""}


class TestParsers:
    def test_workload_scalars(self, tmp_path):
        p = tmp_path / "w.yaml"
        p.write_text(WORKLOAD, encoding="utf-8")
        assert parse_workload(str(p)) == {"message_size_b": "200", "producer_rate": "500",
                                          "duration_min": "3"}

    def test_an_explicit_warmup_is_read(self, tmp_path):
        p = tmp_path / "w.yaml"
        p.write_text(WORKLOAD + "warmupDurationMinutes: 0\n", encoding="utf-8")
        assert parse_workload(str(p))["warmup_min"] == "0"

    def test_a_missing_workload_is_empty(self, tmp_path):
        assert parse_workload(str(tmp_path / "absent.yaml")) == {}

    def test_result_row_maps_to_named_fields(self, tmp_path):
        p = tmp_path / "r.csv"
        p.write_text(RESULT_ROW + "\n", encoding="utf-8")
        r = parse_result_csv(str(p))
        assert r["kept"] == "1821" and r["discarded_zero"] == "118608"
        assert r["bootstrap"] == "10.0.1.221:19092"

    def test_a_short_result_row_does_not_raise(self, tmp_path):
        p = tmp_path / "r.csv"
        p.write_text("OMB,embedded,1\n", encoding="utf-8")
        assert parse_result_csv(str(p))["kept"] == ""

    def test_a_missing_result_is_empty(self, tmp_path):
        assert parse_result_csv(str(tmp_path / "absent.csv")) == {}

    def test_an_empty_result_file_is_empty(self, tmp_path):
        p = tmp_path / "r.csv"
        p.write_text("", encoding="utf-8")
        assert parse_result_csv(str(p)) == {}

    def test_the_tail_is_read_when_the_log_is_larger_than_the_window(self, tmp_path):
        p = tmp_path / "big.log"
        p.write_text("x" * 5000 + "\nTAILMARK\n", encoding="utf-8")
        assert "TAILMARK" in read_tail(str(p), nbytes=100)

    def test_a_short_log_is_read_whole(self, tmp_path):
        p = tmp_path / "s.log"
        p.write_text("HEADMARK\n", encoding="utf-8")
        assert "HEADMARK" in read_tail(str(p), nbytes=1 << 20)

    def test_sha256_matches_hashlib(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"abc" * 1000)
        assert sha256_of(str(p)) == hashlib.sha256(b"abc" * 1000).hexdigest()


class TestCounts:
    def test_the_shutdown_hook_is_the_exact_source(self, tmp_path):
        d = make_cell(tmp_path, "load_sweep", "l0_rep1")
        counts, source, size, digest = parse_counts(str(d))
        assert source == "shutdown_hook"
        assert counts == {"kept": "1821", "discarded_zero": "118608",
                          "discarded_negative": "0", "most_negative_micros": "0"}
        assert size > 0 and len(digest) == 64

    def test_periodic_lines_are_labelled_quantised_and_yield_no_counts(self, tmp_path):
        """The count is a multiple of the print interval, so it must not be handed out."""
        d = make_cell(tmp_path, "load_sweep", "l0_rep1",
                      log="SBL_DISCARD_ZERO total=50000")
        counts, source, _size, _d = parse_counts(str(d))
        assert source == "periodic_quantised" and counts == {}

    def test_a_log_with_neither_says_so(self, tmp_path):
        d = make_cell(tmp_path, "load_sweep", "l0_rep1", log="nothing useful here")
        _c, source, _s, _d = parse_counts(str(d))
        assert source == "none_in_log"

    def test_a_missing_log_is_absent_and_unhashed(self, tmp_path):
        d = make_cell(tmp_path, "load_sweep", "l0_rep1", log=None)
        counts, source, size, digest = parse_counts(str(d))
        assert (counts, source, size, digest) == ({}, "absent", 0, "")

    def test_the_last_summary_wins(self, tmp_path):
        d = make_cell(
            tmp_path, "load_sweep", "l0_rep1",
            log=("SBL_DISCARD_SUMMARY kept=1 zero=2 negative=3 most_negative_micros=-4\n"
                 "SBL_DISCARD_SUMMARY kept=9 zero=8 negative=7 most_negative_micros=-6"))
        counts, _s, _sz, _d = parse_counts(str(d))
        assert counts["kept"] == "9" and counts["most_negative_micros"] == "-6"

    def test_a_negative_most_negative_parses(self, tmp_path):
        d = make_cell(tmp_path, "x", "l0_rep1",
                      log="SBL_DISCARD_SUMMARY kept=1 zero=1 negative=1 "
                          "most_negative_micros=-4096")
        assert parse_counts(str(d))[0]["most_negative_micros"] == "-4096"


class TestZeroShare:
    def test_share_is_over_everything_seen(self):
        assert zero_share("10", "90", "0") == pytest.approx(0.9)

    def test_negatives_are_in_the_denominator(self):
        assert zero_share("0", "50", "50") == pytest.approx(0.5)

    def test_nothing_seen_is_blank_not_zero(self):
        """Zero would read as 'no zeros were discarded', which is a different statement."""
        assert zero_share("0", "0", "0") == ""

    def test_unparseable_is_blank(self):
        assert zero_share("", "n/a", None) == ""


class TestInvalidReason:
    def test_the_invalid_campaign_is_flagged(self, tmp_path):
        assert "INVALID" in invalid_reason(str(tmp_path / "c"), "INVALID", {"valid": "1"})

    def test_a_cell_named_invalid_is_flagged(self, tmp_path):
        d = tmp_path / "run.INVALID"
        assert "INVALID" in invalid_reason(str(d), "load_sweep", {"valid": "1"})

    def test_the_campaigns_own_valid_flag_is_honoured(self, tmp_path):
        assert invalid_reason(str(tmp_path), "load_sweep", {"valid": "0"}) == \
            "campaign marked valid=0"

    def test_no_result_row_is_a_reason(self, tmp_path):
        assert invalid_reason(str(tmp_path), "load_sweep", {}) == "no result row written"

    def test_a_good_cell_has_no_reason(self, tmp_path):
        assert invalid_reason(str(tmp_path), "load_sweep", {"valid": "1"}) == ""


class TestIsCell:
    def test_a_directory_with_a_log_is_a_cell(self, tmp_path):
        d = make_cell(tmp_path, "c", "l0_rep1")
        assert is_cell(str(d))

    def test_an_empty_directory_is_not(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        assert not is_cell(str(d))

    def test_a_file_is_not(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_text("x", encoding="utf-8")
        assert not is_cell(str(p))


class TestIndexCell:
    def test_a_full_row_is_produced(self, tmp_path):
        d = make_cell(tmp_path, "load_sweep", "l88_rep2")
        row = index_cell(str(d), "load_sweep")
        assert set(row) == set(FIELDS)
        assert row["campaign"] == "load_sweep" and row["cell"] == "l88_rep2"
        assert row["axis"] == "load_pct" and row["level"] == "88" and row["rep"] == "2"
        assert row["valid"] == "1" and row["invalid_reason"] == ""
        assert row["count_source"] == "shutdown_hook"
        assert row["message_size_b"] == "200" and row["producer_rate"] == "500"
        assert row["zero_share"] == pytest.approx(118608 / (118608 + 1821))

    def test_the_log_overrides_a_disagreeing_result_row(self, tmp_path):
        """The result CSV is derived from the log, so the log is the primary source."""
        d = make_cell(tmp_path, "c", "l0_rep1",
                      result="OMB,embedded,1,1,1,0,0,999999,24,3,0,b")
        assert index_cell(str(d), "c")["kept"] == "1821"

    def test_a_cell_with_no_log_still_carries_the_result_row(self, tmp_path):
        d = make_cell(tmp_path, "c", "l0_rep1", log=None)
        row = index_cell(str(d), "c")
        assert row["kept"] == "1821" and row["count_source"] == "absent"

    def test_an_invalid_cell_is_indexed_not_dropped(self, tmp_path):
        d = make_cell(tmp_path, "c", "l0_rep1",
                      result="OMB,embedded,0,0,0,0,0,0,0,3,0,b")
        row = index_cell(str(d), "c")
        assert row["valid"] == "0" and row["invalid_reason"] == "campaign marked valid=0"

    def test_a_cell_with_no_result_row_is_invalid_with_a_reason(self, tmp_path):
        d = make_cell(tmp_path, "c", "l0_rep1", result=None)
        row = index_cell(str(d), "c")
        assert row["valid"] == "0" and row["invalid_reason"] == "no result row written"

    def test_a_missing_warmup_key_is_recorded_as_the_default_not_as_none(self, tmp_path):
        """OMB warms up for a minute unless told otherwise, and our early cells never told it.

        Leaving this blank would read as 'no warmup', which is the opposite of what happened --
        and it is the difference between counting 120,000 samples and 90,000.
        """
        d = make_cell(tmp_path, "c", "l0_rep1")
        assert index_cell(str(d), "c")["warmup_min"] == "1(default)"

    def test_an_explicit_zero_warmup_is_not_overwritten_by_the_default(self, tmp_path):
        d = make_cell(tmp_path, "c", "l0_rep1",
                      workload=WORKLOAD + "warmupDurationMinutes: 0\n")
        assert index_cell(str(d), "c")["warmup_min"] == "0"

    def test_a_cell_with_no_workload_file_claims_no_warmup_either_way(self, tmp_path):
        d = make_cell(tmp_path, "c", "l0_rep1", workload=None)
        assert index_cell(str(d), "c")["warmup_min"] == ""

    def test_the_mtime_is_recorded(self, tmp_path):
        d = make_cell(tmp_path, "c", "l0_rep1")
        assert index_cell(str(d), "c")["mtime_utc"].endswith("Z")

    def test_an_unreadable_mtime_leaves_the_row_intact(self, tmp_path, monkeypatch):
        """A stat failure must not cost us the whole row; the counts are the point."""
        d = make_cell(tmp_path, "c", "l0_rep1")

        def boom(_path):
            raise OSError("stat failed")

        monkeypatch.setattr("index_external_campaigns.os.path.getmtime", boom)
        row = index_cell(str(d), "c")
        assert row["mtime_utc"] == "" and row["kept"] == "1821"


class TestWalk:
    def test_cells_are_found_under_campaigns(self, tmp_path):
        make_cell(tmp_path, "load_sweep", "l0_rep1")
        make_cell(tmp_path, "load_sweep", "l50_rep1")
        make_cell(tmp_path, "resolution", "s4096_rep1")
        rows = walk(str(tmp_path))
        assert len(rows) == 3
        assert {r["campaign"] for r in rows} == {"load_sweep", "resolution"}

    def test_a_campaign_that_is_itself_a_cell_is_indexed(self, tmp_path):
        """A smoke test writes straight into the campaign directory; it must not fall out."""
        d = tmp_path / "smoke"
        d.mkdir()
        (d / "omb_stdout.log").write_text(SUMMARY, encoding="utf-8")
        rows = walk(str(tmp_path))
        assert len(rows) == 1 and rows[0]["campaign"] == "smoke"

    def test_loose_files_at_the_root_are_ignored(self, tmp_path):
        (tmp_path / "notes.md").write_text("x", encoding="utf-8")
        make_cell(tmp_path, "c", "l0_rep1")
        assert len(walk(str(tmp_path))) == 1

    def test_a_campaign_with_no_cells_contributes_nothing(self, tmp_path):
        (tmp_path / "empty").mkdir()
        assert walk(str(tmp_path)) == []

    def test_non_cell_subdirectories_are_skipped_without_hiding_their_siblings(self, tmp_path):
        """Campaign directories accumulate scratch dirs; a cell beside one is still indexed."""
        make_cell(tmp_path, "load_sweep", "l0_rep1")
        (tmp_path / "load_sweep" / "tmp_payloads").mkdir()
        (tmp_path / "load_sweep" / "notes.txt").write_text("x", encoding="utf-8")
        rows = walk(str(tmp_path))
        assert [r["cell"] for r in rows] == ["l0_rep1"]

    def test_a_missing_root_is_empty(self, tmp_path):
        assert walk(str(tmp_path / "absent")) == []

    def test_rows_are_ordered_deterministically(self, tmp_path):
        for name in ("l50_rep1", "l0_rep1", "l88_rep1"):
            make_cell(tmp_path, "load_sweep", name)
        assert [r["cell"] for r in walk(str(tmp_path))] == ["l0_rep1", "l50_rep1", "l88_rep1"]


class TestCLI:
    def test_it_writes_the_ledger(self, tmp_path, capsys):
        make_cell(tmp_path, "load_sweep", "l0_rep1")
        make_cell(tmp_path, "load_sweep", "l50_rep1")
        out = tmp_path / "idx" / "external.csv"
        assert main(["--root", str(tmp_path), "--out", str(out)]) == 0
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert len(rows) == 2
        assert list(rows[0]) == list(FIELDS)
        assert "indexed 2 cells" in capsys.readouterr().out

    def test_an_empty_root_is_an_error(self, tmp_path, capsys):
        assert main(["--root", str(tmp_path / "absent"), "--out", str(tmp_path / "o.csv")]) == 1
        assert "no campaign cells" in capsys.readouterr().out

    def test_the_summary_counts_valid_and_exact_separately(self, tmp_path, capsys):
        make_cell(tmp_path, "c", "l0_rep1")
        make_cell(tmp_path, "c", "l50_rep1", log="SBL_DISCARD_ZERO total=50000",
                  result="OMB,embedded,0,0,0,0,0,0,0,3,50,b")
        main(["--root", str(tmp_path), "--out", str(tmp_path / "o.csv")])
        out = capsys.readouterr().out
        assert "valid            : 1" in out
        assert "invalid          : 1" in out
        assert "exact counts     : 1" in out
        assert "quantised/absent : 1" in out
