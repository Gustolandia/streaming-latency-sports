"""Tests for check_paper_omb_numbers.

This checker exists because the manuscript quotes the external campaign's run count in nine places
and its discard total in two, and those move whenever a campaign lands. It found a real error on
first run: 420,000 discarded samples quoted against a ledger holding 3,538,341, because a figure
computed from a nine-cell partial sweep had been paired with the full run count.

Two properties are load-bearing and tested as such: it must not flag run counts belonging to the
paper's *other* campaigns, and it must fail loudly if a negative sample ever appears, because that
single number invalidates the withdrawal the section is built on.
"""
import csv
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_paper_omb_numbers import (  # noqa: E402
    OMB_SUBSET_PATTERNS, find_quoted_discard_totals, find_quoted_run_counts,
    load_cells, main, measured,
)

LEDGER_FIELDS = ("campaign", "cell", "valid", "count_source",
                 "kept", "discarded_zero", "discarded_negative")


def write_ledger(path, rows):
    """rows: (campaign, kept, zero, neg[, valid, count_source])"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(LEDGER_FIELDS)
        for i, r in enumerate(rows):
            camp, kept, zero, neg = r[:4]
            valid = r[4] if len(r) > 4 else "1"
            src = r[5] if len(r) > 5 else "shutdown_hook"
            w.writerow([camp, "c%d" % i, valid, src, kept, zero, neg])


class TestLoadCells:
    def test_only_paper_campaigns_count(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 90, 0), ("smoke", 10, 90, 0)])
        assert [c["campaign"] for c in load_cells(str(p))] == ["load_sweep"]

    def test_invalid_cells_are_excluded(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 90, 0, "0")])
        assert load_cells(str(p)) == []

    def test_quantised_counts_are_excluded(self, tmp_path):
        """Periodic totals round to 10,000 and cannot carry a claim."""
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 90, 0, "1", "periodic_quantised")])
        assert load_cells(str(p)) == []


class TestMeasured:
    def test_totals_and_range(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 1, 99, 0), ("resolution", 99, 1, 0)])
        m = measured(load_cells(str(p)))
        assert m["n_runs"] == 2
        assert m["discarded_total"] == 100
        assert m["negatives"] == 0
        assert m["retention_min"] == pytest.approx(1.0)
        assert m["retention_max"] == pytest.approx(99.0)

    def test_negatives_are_summed(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 80, 7)])
        m = measured(load_cells(str(p)))
        assert m["negatives"] == 7
        assert m["discarded_total"] == 87

    def test_a_cell_that_saw_nothing_is_not_in_the_range(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 0, 0, 0), ("load_sweep", 50, 50, 0)])
        m = measured(load_cells(str(p)))
        assert m["retention_min"] == pytest.approx(50.0)


class TestRunCountExtraction:
    def test_the_omb_phrasings_are_found(self):
        src = ("Across $80$ instrumented runs the benchmark\n"
               "and ran the benchmark $80$ times.\n"
               "the $80$-run campaign of Section 6\n")
        assert sorted(v for v, _ in find_quoted_run_counts(src)) == [80, 80, 80]

    def test_other_campaigns_are_not_flagged(self):
        """The real false positives: our own mixture sweep and producer-offset result."""
        src = ("nine load levels from idle to oversubscription, $25$ runs each\n"
               "reproduced across both testbeds, four concurrency levels and $164$ runs\n"
               "The mixture, measured across nine load levels ($25$ runs each)\n")
        assert find_quoted_run_counts(src) == []

    def test_the_unsaturated_subset_has_its_own_pattern(self):
        src = "Across the $49$ runs on an unsaturated path, the benchmark computes\n"
        assert find_quoted_run_counts(src) == []
        assert find_quoted_run_counts(src, OMB_SUBSET_PATTERNS) == [(49, 1)]

    def test_line_numbers_are_reported(self):
        src = "filler\nfiller\nAcross $83$ instrumented runs\n"
        assert find_quoted_run_counts(src) == [(83, 3)]


class TestDiscardExtraction:
    def test_a_latex_thousands_separator_parses(self):
        src = "roughly $420{,}000$ discarded samples contain not one negative\n"
        assert find_quoted_discard_totals(src) == [(420000, 1)]

    def test_a_multi_group_separator_parses(self):
        """The single-separator pattern matched nothing past a million, which is exactly
        when the number most needed checking."""
        src = "in $3{,}538{,}341$ discarded samples there is not one negative\n"
        assert find_quoted_discard_totals(src) == [(3538341, 1)]

    def test_a_rounded_millions_figure_parses(self):
        src = "in roughly $3.5$ million discarded samples\n"
        assert find_quoted_discard_totals(src) == [(3500000, 1)]

    def test_a_number_far_from_the_word_discarded_is_not_captured(self):
        """Guards against sweeping up unrelated figures that happen to share a line."""
        src = "$1{,}321$ of $2{,}266$ runs were rejected, and separately some were discarded\n"
        got = find_quoted_discard_totals(src)
        assert all(v not in (1321, 2266) for v, _ in got)

    def test_no_total_quoted_is_empty(self):
        assert find_quoted_discard_totals("no numbers here\n") == []


class TestCLI:
    def _setup(self, tmp_path, paper_text, rows):
        led = tmp_path / "ledger.csv"
        write_ledger(led, rows)
        pap = tmp_path / "paper.tex"
        pap.write_text(paper_text, encoding="utf-8")
        return ["--ledger", str(led), "--paper", str(pap)]

    def test_matching_numbers_pass(self, tmp_path, capsys):
        args = self._setup(tmp_path, "Across $2$ instrumented runs\n",
                           [("load_sweep", 10, 90, 0), ("load_sweep", 20, 80, 0)])
        assert main(args) == 0
        assert "match the ledger" in capsys.readouterr().out

    def test_a_stale_run_count_fails(self, tmp_path, capsys):
        args = self._setup(tmp_path, "Across $80$ instrumented runs\n",
                           [("load_sweep", 10, 90, 0)])
        assert main(args) == 1
        out = capsys.readouterr().out
        assert "MISMATCH" in out and "paper 80, ledger 1" in out

    def test_a_negative_sample_fails_loudly(self, tmp_path, capsys):
        """The one number that invalidates the withdrawal the section is built on."""
        args = self._setup(tmp_path, "Across $1$ instrumented runs\n",
                           [("load_sweep", 10, 80, 3)])
        assert main(args) == 1
        out = capsys.readouterr().out
        assert "NEGATIVE SAMPLES PRESENT" in out
        assert "withdrawal it justifies must be revisited" in out

    def test_a_subset_larger_than_the_total_is_impossible(self, tmp_path, capsys):
        args = self._setup(tmp_path,
                           "Across $1$ instrumented runs\n"
                           "Across the $49$ runs on an unsaturated path\n",
                           [("load_sweep", 10, 90, 0)])
        assert main(args) == 1
        assert "IMPOSSIBLE" in capsys.readouterr().out

    def test_rounding_slack_accepts_a_rounded_total(self, tmp_path, capsys):
        args = self._setup(tmp_path,
                           "Across $1$ instrumented runs\n"
                           "roughly $100{,}000$ discarded samples\n",
                           [("load_sweep", 5, 99000, 0)])
        assert main(args) == 0
        assert "within rounding" in capsys.readouterr().out

    def test_a_missing_ledger_is_an_error(self, tmp_path, capsys):
        assert main(["--ledger", str(tmp_path / "no.csv"),
                     "--paper", str(tmp_path / "no.tex")]) == 1
        assert "missing" in capsys.readouterr().out

    def test_an_empty_ledger_is_an_error(self, tmp_path, capsys):
        led = tmp_path / "l.csv"
        write_ledger(led, [("smoke", 1, 1, 0)])
        pap = tmp_path / "p.tex"
        pap.write_text("nothing\n", encoding="utf-8")
        assert main(["--ledger", str(led), "--paper", str(pap)]) == 1
        assert "nothing to check against" in capsys.readouterr().out

    def test_a_paper_quoting_nothing_still_reports_the_measurements(self, tmp_path, capsys):
        args = self._setup(tmp_path, "no numbers at all\n", [("load_sweep", 10, 90, 0)])
        assert main(args) == 0
        out = capsys.readouterr().out
        assert "(none found)" in out and "admissible runs" in out
