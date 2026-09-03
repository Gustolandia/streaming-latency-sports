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
    DERIVED_MACROS, OMB_SUBSET_PATTERNS, find_quoted_discard_totals, find_quoted_run_counts,
    REDIS_CAMPAIGNS, _worst_run, find_undermined_macros, load_cells, main, measured,
)
from emit_paper_numbers import render  # noqa: E402

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

    def test_a_total_wrapped_onto_the_next_line_is_found(self):
        """The defect this check was blind to.

        Two of the manuscript's four discard totals were written with a LaTeX line break between
        the number and the word `discarded`. A line-by-line scan saw neither, so the check
        reported "2 sites, both stale" when the truth was "4 sites, and I can only see half of
        them". A gate that under-reports its own coverage is worse than no gate.
        """
        src = ("and our own earlier reading of these discards: in roughly $420{,}000$\n"
               "discarded samples there is not one negative\n")
        assert find_quoted_discard_totals(src) == [(420000, 1)]

    def test_line_numbers_survive_the_whole_source_scan(self):
        src = "filler\n" * 9 + "in $1{,}000$ discarded samples\n"
        assert find_quoted_discard_totals(src) == [(1000, 10)]

    def test_a_sentence_boundary_still_stops_the_match(self):
        """Scanning the whole source must not let a match run across unrelated sentences."""
        src = "we saw $12{,}345$ events. Much later the run discarded something\n"
        assert find_quoted_discard_totals(src) == []


class TestDerivationIsStillInPlace:
    def test_a_manuscript_using_both_macros_is_clean(self):
        src = "Across $\\ombRuns$ runs, $\\ombDiscarded$ discarded samples\n"
        assert find_undermined_macros(src) == []

    def test_a_dropped_macro_is_named(self):
        assert find_undermined_macros("Across $\\ombRuns$ runs\n") == ["ombDiscarded"]

    def test_every_derived_macro_is_checked(self):
        assert set(find_undermined_macros("nothing\n")) == set(DERIVED_MACROS)


class TestCLI:
    """The contract changed when the numbers became derived.

    The old question was "does the digit in the manuscript match the ledger?". A digit that
    matches today is still a defect, because it matches by coincidence and the next campaign
    silently invalidates it. The question is now "is the manuscript still deriving this at all?",
    and a hand-typed number fails even when it is arithmetically right.
    """

    # A manuscript that derives its numbers properly. Used wherever the test is about something
    # other than the derivation itself.
    DERIVED = ("Across $\\ombRuns$ instrumented runs\n"
               "in $\\ombDiscarded$ discarded samples there is not one negative\n")

    def _setup(self, tmp_path, paper_text, rows, generated=None):
        led = tmp_path / "ledger.csv"
        write_ledger(led, rows)
        pap = tmp_path / "paper.tex"
        pap.write_text(paper_text, encoding="utf-8")
        gen = tmp_path / "paper_numbers.tex"
        if generated is None:
            generated = render(measured(load_cells(str(led))))
        gen.write_text(generated, encoding="utf-8")
        return ["--ledger", str(led), "--paper", str(pap), "--generated", str(gen)]

    def test_a_derived_manuscript_passes(self, tmp_path, capsys):
        args = self._setup(tmp_path, self.DERIVED,
                           [("load_sweep", 10, 90, 0), ("load_sweep", 20, 80, 0)])
        assert main(args) == 0
        assert "match the ledger" in capsys.readouterr().out

    def test_a_hand_typed_run_count_fails_even_when_it_is_correct(self, tmp_path, capsys):
        """The core of the new contract: right-today is not the same as right."""
        args = self._setup(tmp_path,
                           self.DERIVED + "Across $1$ instrumented runs\n",
                           [("load_sweep", 10, 90, 0)])
        assert main(args) == 1
        out = capsys.readouterr().out
        assert "hand-typed" in out
        assert "will not stay that way" in out
        assert "use \\ombRuns" in out

    def test_a_hand_typed_run_count_that_is_also_wrong_names_the_ledger(self, tmp_path, capsys):
        args = self._setup(tmp_path, self.DERIVED + "Across $80$ instrumented runs\n",
                           [("load_sweep", 10, 90, 0)])
        assert main(args) == 1
        assert "ledger: 1" in capsys.readouterr().out

    def test_a_hand_typed_discard_total_fails(self, tmp_path, capsys):
        args = self._setup(tmp_path, self.DERIVED + "roughly $100{,}000$ discarded samples\n",
                           [("load_sweep", 5, 99000, 0)])
        assert main(args) == 1
        assert "use \\ombDiscarded" in capsys.readouterr().out

    def test_dropping_a_macro_is_caught(self, tmp_path, capsys):
        """A manuscript that stops using the macro has gone back to typing the number."""
        args = self._setup(tmp_path, "Across $\\ombRuns$ instrumented runs\n",
                           [("load_sweep", 10, 90, 0)])
        assert main(args) == 1
        out = capsys.readouterr().out
        assert "\\ombDiscarded" in out and "NOT USED" in out

    def test_a_stale_generated_file_is_caught(self, tmp_path, capsys):
        """The failure mode the macros create: paper consistent with a file, file behind reality."""
        args = self._setup(tmp_path, self.DERIVED, [("load_sweep", 10, 90, 0)],
                           generated="\\newcommand{\\ombRuns}{999}\n")
        assert main(args) == 1
        out = capsys.readouterr().out
        assert "STALE" in out and "regenerate with" in out

    def test_a_missing_generated_file_is_caught(self, tmp_path, capsys):
        led = tmp_path / "l.csv"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        pap = tmp_path / "p.tex"
        pap.write_text(self.DERIVED, encoding="utf-8")
        assert main(["--ledger", str(led), "--paper", str(pap),
                     "--generated", str(tmp_path / "absent.tex")]) == 1
        assert "run scripts/emit_paper_numbers.py" in capsys.readouterr().out

    def test_a_kafka_corpus_negative_fails_loudly(self, tmp_path, capsys):
        """The withdrawal rests on the Kafka-driver corpus staying negative-free."""
        args = self._setup(tmp_path, self.DERIVED, [("load_sweep", 10, 80, 3)])
        assert main(args) == 1
        out = capsys.readouterr().out
        assert "KAFKA-DRIVER CORPUS HAS 3 NEGATIVES" in out
        assert "withdrawal's basis is false" in out

    def test_a_redis_corpus_negative_is_a_finding_not_a_failure(self, tmp_path, capsys):
        """The Redis-driver replication caught real negatives; the paper reports them, so the
        gate must pin the count without failing the build."""
        args = self._setup(tmp_path, self.DERIVED,
                           [("load_sweep", 10, 80, 0), ("ultimate_redis", 5, 80, 7)])
        assert main(args) == 0
        out = capsys.readouterr().out
        assert "Kafka-driver corpus: 0 negatives" in out
        assert "Redis-driver corpus: 7 negatives" in out

    def test_a_subset_larger_than_the_total_is_impossible(self, tmp_path, capsys):
        args = self._setup(tmp_path,
                           self.DERIVED + "Across the $49$ runs on an unsaturated path\n",
                           [("load_sweep", 10, 90, 0)])
        assert main(args) == 1
        assert "IMPOSSIBLE" in capsys.readouterr().out

    def test_a_plausible_subset_is_reported_without_failing(self, tmp_path, capsys):
        """A smaller number here is legitimate and must not be forced to equal the total."""
        args = self._setup(tmp_path,
                           self.DERIVED + "Across the $1$ runs on an unsaturated path\n",
                           [("load_sweep", 10, 90, 0), ("load_sweep", 20, 80, 0)])
        assert main(args) == 0
        assert "verify separately" in capsys.readouterr().out

    def test_a_malformed_count_does_not_take_the_check_down(self, tmp_path, capsys):
        """A single unparseable cell must not stop the gate from reporting the rest."""
        led = tmp_path / "l.csv"
        with led.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(LEDGER_FIELDS)
            w.writerow(["load_sweep", "bad", "1", "shutdown_hook", "x", "y", ""])
            w.writerow(["load_sweep", "ok", "1", "shutdown_hook", "10", "90", "0"])
        pap = tmp_path / "p.tex"
        pap.write_text(self.DERIVED, encoding="utf-8")
        gen = tmp_path / "g.tex"
        gen.write_text(render(measured(load_cells(str(led)))), encoding="utf-8")
        assert main(["--ledger", str(led), "--paper", str(pap), "--generated", str(gen)]) == 0
        assert "admissible runs        : 2" in capsys.readouterr().out

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

    def test_the_measurements_are_reported_even_when_the_paper_is_silent(self, tmp_path, capsys):
        args = self._setup(tmp_path, self.DERIVED, [("load_sweep", 10, 90, 0)])
        assert main(args) == 0
        out = capsys.readouterr().out
        assert "admissible runs" in out
        assert "none -- every run count comes from" in out


class TestWorstRun:
    """The single worst Redis run, which the main text quotes as its sharpest instance.

    "41,397 of them in a single run where they were half of all samples taken, beside six
    kept" -- both numbers were typed, in a round that found the same defect twice over in
    the two sentences carrying "zero" and "not one negative". A count that makes a sentence
    worth reading is the last count that should reach the page by hand.
    """

    @staticmethod
    def cell(neg, kept, zero):
        return {"discarded_negative": str(neg), "kept": str(kept),
                "discarded_zero": str(zero)}

    def test_it_picks_the_run_with_the_most_negatives(self):
        got = _worst_run([
            self.cell(10, 900, 90),
            self.cell(41397, 6, 41266),
            self.cell(300, 700, 0),
        ])
        assert got["redis_worst_negatives"] == 41397
        assert got["redis_worst_kept"] == 6
        assert got["redis_worst_share"] == pytest.approx(50.08, abs=0.01)

    def test_no_cells_gives_no_worst_run(self):
        got = _worst_run([])
        assert got == {"redis_worst_negatives": None, "redis_worst_kept": None,
                       "redis_worst_share": None}

    def test_a_run_that_saw_nothing_has_no_share(self):
        """Division by the number of samples taken, when none were."""
        got = _worst_run([self.cell(0, 0, 0)])
        assert got["redis_worst_negatives"] == 0
        assert got["redis_worst_share"] is None

    def test_the_committed_ledger_gives_the_number_the_paper_prints(self):
        import os
        cells = load_cells(os.path.join("docs", "results",
                                             "external_campaigns_index.csv"))
        redis = [c for c in cells if c.get("campaign") in REDIS_CAMPAIGNS]
        got = _worst_run(redis)
        assert got["redis_worst_negatives"] == 41397
        assert got["redis_worst_kept"] == 6
        assert got["redis_worst_share"] == pytest.approx(50.08, abs=0.05), \
            "the main text calls this half of all samples taken"
