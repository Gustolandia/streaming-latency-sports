"""Tests for analyze_phase_quantisation.

The script decides whether the phase effect is binary (commensurate or not) or quantised by the
denominator q. The verdicts that matter most are the ones that decline to decide: with only q=1 and
large-q rates measured, or with every arm predicting the same class, a tool that announced a rule
anyway would be doing what this paper spends a section warning against.

The exact-fraction arithmetic is load-bearing. 2.000 and 2.188 must not both round to "close enough
to 2", which is why the denominator is computed with Fraction rather than floats.

Two of these test classes exist because the analysis was wrong before it was right, and each pins
the corrected behaviour so it cannot quietly regress:

- TestDegeneracy: `spread ~ 100/q` is an upper bound, not a point prediction. An arm whose
  continuous value sits on a grid point is predicted to be FLAT, so the even-q arms are evidence
  for the model rather than exceptions needing exclusion. The tests assert the rule is stated
  generally -- at T_true/tau = 1/3 it must be q=3 that goes blind and q=2 that discriminates, not
  a hardcoded parity check fitted to this dataset.

- TestPower: spread is a range statistic, so an arm needs enough replicates to realise both
  bracketing grid points before a flat result means anything. Without that guard an unfinished arm
  reads as a refutation, which is exactly what the 600 msg/s arm did at n=2. The guard is
  deliberately asymmetric -- a full-spread result is decisive at any n -- and a test asserts it
  cannot be used to excuse a well-powered miss.
"""
import csv
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_phase_quantisation import (  # noqa: E402
    DEFAULT_NOISE_PTS, MAX_MEANINGFUL_Q, continuous_noise_pts, continuous_retention,
    grid_distance_pts, group_by_rate, load_rate_cells, main, phase_denominator, report, verdict,
)

FIELDS = ("campaign", "cell", "level", "valid", "count_source",
          "kept", "discarded_zero", "discarded_negative")


def write_ledger(path, rows):
    """rows: (rate, retention_pct[, campaign, valid, count_source])"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for i, r in enumerate(rows):
            rate, ret = r[0], r[1]
            camp = r[2] if len(r) > 2 else "rate_phase"
            valid = r[3] if len(r) > 3 else "1"
            src = r[4] if len(r) > 4 else "shutdown_hook"
            kept = int(round(ret * 1000))
            zero = 100000 - kept
            w.writerow([camp, f"r{rate}_rep{i}", rate, valid, src, kept, zero, 0])


class TestPhaseDenominator:
    def test_exact_multiples_give_one(self):
        for rate in (1000, 500, 250, 200, 125):
            assert phase_denominator(rate) == 1, f"{rate}/s should be q=1"

    def test_half_integer_gives_two(self):
        assert phase_denominator(400) == 2      # 2.5 ms = 5/2

    def test_thirds_give_three(self):
        assert phase_denominator(300) == 3      # 10/3 ms

    def test_quarters_give_four(self):
        assert phase_denominator(800) == 4      # 1.25 ms = 5/4

    def test_an_awkward_rate_gives_a_large_denominator(self):
        """457/s is 2.188 ms; it must not collapse to 'about 2'."""
        assert phase_denominator(457) > MAX_MEANINGFUL_Q

    def test_exact_arithmetic_separates_near_neighbours(self):
        """The whole result rests on 2.000 and 2.188 being different in kind."""
        assert phase_denominator(500) == 1
        assert phase_denominator(457) != 1

    def test_a_different_tick_rescales(self):
        # At a 2 ms tick, 1000/s gives interval/tick = 0.5 = 1/2, so q=2.
        assert phase_denominator(1000, tick_ms=2.0) == 2

    def test_nonsense_input_is_none(self):
        assert phase_denominator(0) is None
        assert phase_denominator(500, tick_ms=0) is None


class TestLoading:
    def test_only_rate_campaigns_contribute(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 50.0), (500, 50.0, "load_sweep")])
        assert len(load_rate_cells(str(p))) == 1

    def test_chain17_rate_cells_merge_into_the_arms(self, tmp_path):
        """`ultimate` extends the existing arms; its payload/duration companions must not.

        A 1-minute or 32 KB replicate slipping into a rate arm would corrupt the very spread the
        analysis tests, so the exclusion of the companion campaigns is load-bearing, not tidiness.
        """
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 50.0), (500, 60.0, "ultimate"),
                         (500, 70.0, "ultimate_dur1"), (500, 80.0, "ultimate_dur10"),
                         (500, 90.0, "ultimate_pay300")])
        got = load_rate_cells(str(p))
        assert sorted(c["retention"] for c in got) == [50.0, 60.0]

    def test_invalid_and_quantised_cells_excluded(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 50.0, "rate_phase", "0"),
                         (500, 50.0, "rate_phase", "1", "periodic_quantised"),
                         (500, 50.0)])
        assert len(load_rate_cells(str(p))) == 1

    def test_retention_is_recovered(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 42.5)])
        assert load_rate_cells(str(p))[0]["retention"] == pytest.approx(42.5, abs=0.01)

    def test_unparseable_counts_are_skipped_not_fatal(self, tmp_path):
        """A malformed row must not take the whole analysis down with it."""
        p = tmp_path / "l.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(FIELDS)
            w.writerow(["rate_phase", "bad", "n/a", "1", "shutdown_hook", "x", "y", ""])
            w.writerow(["rate_phase", "ok", "500", "1", "shutdown_hook", "50000", "50000", "0"])
        got = load_rate_cells(str(p))
        assert len(got) == 1 and got[0]["rate"] == 500

    def test_a_nonsense_rate_is_skipped(self, tmp_path):
        """A rate of zero has no interval and so no phase; it must not divide by it."""
        p = tmp_path / "l.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(FIELDS)
            w.writerow(["rate_phase", "z", "0", "1", "shutdown_hook", "500", "500", "0"])
            w.writerow(["rate_phase", "ok", "500", "1", "shutdown_hook", "50000", "50000", "0"])
        got = load_rate_cells(str(p))
        assert len(got) == 1 and got[0]["rate"] == 500

    def test_a_cell_that_saw_nothing_is_skipped(self, tmp_path):
        p = tmp_path / "l.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(FIELDS)
            w.writerow(["rate_phase", "empty", "500", "1", "shutdown_hook", "0", "0", "0"])
        assert load_rate_cells(str(p)) == []


class TestGrouping:
    def test_spread_and_q_per_rate(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0), (457, 50.0), (457, 51.0)])
        g = {x["rate"]: x for x in group_by_rate(load_rate_cells(str(p)))}
        assert g[500]["q"] == 1 and g[500]["spread"] == pytest.approx(98.0, abs=0.1)
        assert g[457]["commensurate"] is False
        assert g[457]["spread"] == pytest.approx(1.0, abs=0.1)

    def test_a_single_replicate_has_no_spread(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 50.0)])
        assert group_by_rate(load_rate_cells(str(p)))[0]["spread"] is None

    def test_cell_width_is_100_over_q(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(400, 10.0), (400, 60.0)])
        g = group_by_rate(load_rate_cells(str(p)))[0]
        assert g["q"] == 2 and g["cell_width"] == pytest.approx(50.0)

    def test_no_incommensurate_rate_means_no_prediction_not_a_zero(self, tmp_path):
        """Without a continuous value there is no cell position, so nothing is predicted.

        Printing 0.0 here would claim a flat arm was expected, which is a measurement that was
        never made.
        """
        p = tmp_path / "l.csv"
        write_ledger(p, [(400, 10.0), (400, 60.0)])
        g = group_by_rate(load_rate_cells(str(p)))[0]
        assert g["predicted_spread"] is None
        assert g["predicted_full"] is None


class TestDegeneracy:
    """A grid cannot be told from the continuum when the continuous value lands on it.

    This is the rule that makes the even-q arms uninformative at an operating point where
    T_true/tau is near 0.5, and it is the reason odd q were run. It has to be a *general* test
    against the measured continuous value -- a hardcoded "skip even q" would be an exclusion
    fitted to one dataset, and would silently mislead at any other T_true/tau.
    """

    def test_the_continuous_value_is_the_incommensurate_median(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(457, 48.0), (457, 50.0), (457, 52.0), (500, 99.0)])
        assert continuous_retention(group_by_rate(load_rate_cells(str(p)))) == pytest.approx(50.0)

    def test_no_incommensurate_rate_means_no_continuous_value(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 99.0)])
        assert continuous_retention(group_by_rate(load_rate_cells(str(p)))) is None

    def test_an_even_count_of_values_averages_the_middle_pair(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(457, 40.0), (457, 50.0), (457, 60.0), (457, 70.0)])
        assert continuous_retention(group_by_rate(load_rate_cells(str(p)))) == pytest.approx(55.0)

    def test_noise_falls_back_when_nothing_incommensurate_was_measured(self):
        assert continuous_noise_pts([]) == DEFAULT_NOISE_PTS

    def test_noise_is_the_half_range_of_the_incommensurate_replicates(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(457, 46.0), (457, 54.0)])
        assert continuous_noise_pts(group_by_rate(load_rate_cells(str(p)))) == pytest.approx(4.0)

    def test_noise_never_collapses_to_zero(self, tmp_path):
        """Identical replicates would otherwise make every grid look resolvable."""
        p = tmp_path / "l.csv"
        write_ledger(p, [(457, 50.0), (457, 50.0)])
        assert continuous_noise_pts(group_by_rate(load_rate_cells(str(p)))) == pytest.approx(0.5)

    def test_a_half_continuous_value_sits_on_every_even_grid(self):
        for q in (2, 4, 6, 8):
            assert grid_distance_pts(q, 50.0) == pytest.approx(0.0)

    def test_odd_grids_keep_their_distance_from_a_half(self):
        assert grid_distance_pts(3, 50.0) == pytest.approx(100.0 / 6, abs=0.1)
        assert grid_distance_pts(5, 50.0) == pytest.approx(10.0, abs=0.1)

    def test_the_rule_is_not_about_parity(self):
        """At T_true/tau = 1/3 it is q=3 that goes degenerate and q=2 that discriminates."""
        assert grid_distance_pts(3, 33.333) == pytest.approx(0.0, abs=0.01)
        assert grid_distance_pts(2, 33.333) > 15.0

    def test_nonsense_q_gives_no_distance(self):
        assert grid_distance_pts(0, 50.0) is None
        assert grid_distance_pts(None, 50.0) is None
        assert grid_distance_pts(3, None) is None

    def test_even_arms_sit_on_the_grid_and_odd_arms_do_not(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(457, 49.0), (457, 50.0),      # continuous ~49.5
                         (400, 50.0), (400, 68.0),      # q=2 -> grid passes through 50
                         (300, 35.0), (300, 65.0)])     # q=3 -> nearest grid point is 33.3
        g = {x["rate"]: x for x in group_by_rate(load_rate_cells(str(p)))}
        assert g[400]["cell_fraction"] < 0.1        # on a grid point
        assert g[300]["cell_fraction"] > 0.9        # nearly midway

    def test_an_on_grid_arm_is_predicted_flat_and_counts_when_it_is(self, tmp_path):
        """The correction that matters.

        Under the earlier formulation `spread ~ 100/q` was treated as a point prediction, so a
        flat q=2 arm looked like a failure and had to be excluded to save the law. It is not a
        failure: sitting on a grid point is exactly the condition that predicts a flat arm, so it
        is evidence *for* the model and is counted as such.
        """
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0),       # q=1 mid-cell  -> full
                         (400, 50.0), (400, 52.0),      # q=2 on grid   -> flat
                         (300, 40.0), (300, 74.0),      # q=3 mid-cell  -> full
                         (457, 49.0), (457, 50.0)])
        g = {x["rate"]: x for x in group_by_rate(load_rate_cells(str(p)))}
        assert g[400]["predicted_full"] is False and g[400]["observed_full"] is False
        v = verdict(group_by_rate(load_rate_cells(str(p))))
        assert v["outcome"] == "QUANTISED"
        assert "q=2 flat/flat" in v["why"]

    def test_an_on_grid_arm_that_shows_full_spread_refutes(self, tmp_path):
        """The model has to be able to fail, and this is the shape of its failure."""
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0),
                         (400, 20.0), (400, 80.0),      # q=2 on grid but spread 60
                         (457, 49.0), (457, 50.0)])
        g = {x["rate"]: x for x in group_by_rate(load_rate_cells(str(p)))}
        assert g[400]["predicted_full"] is False and g[400]["observed_full"] is True
        v = verdict(group_by_rate(load_rate_cells(str(p))))
        assert v["outcome"] in ("UNCLEAR", "REFUTED")
        assert "q=2 flat/full" in v["why"]

    def test_a_uniform_prediction_cannot_confirm_the_model(self, tmp_path):
        """Agreeing with a prediction that never varies is not evidence."""
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0),       # q=1 full
                         (300, 40.0), (300, 74.0),      # q=3 full
                         (457, 49.0), (457, 50.0)])
        v = verdict(group_by_rate(load_rate_cells(str(p))))
        assert not v["decided"]
        assert "would not distinguish this model from a constant" in v["why"]

    def test_the_table_shows_the_cell_position_behind_each_call(self, tmp_path, capsys):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0), (400, 50.0), (400, 52.0),
                         (457, 49.0), (457, 50.0)])
        report(group_by_rate(load_rate_cells(str(p))))
        out = capsys.readouterr().out
        assert "incell" in out
        assert "continuous value" in out
        assert "flat/flat" in out

    def test_a_mismatch_is_marked_in_the_table(self, tmp_path, capsys):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0), (400, 20.0), (400, 80.0),
                         (457, 49.0), (457, 50.0)])
        report(group_by_rate(load_rate_cells(str(p))))
        assert "MISS" in capsys.readouterr().out

    def test_the_cell_position_reaches_the_csv(self, tmp_path):
        p = tmp_path / "l.csv"
        out = tmp_path / "q.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0), (400, 50.0), (400, 52.0),
                         (457, 49.0), (457, 50.0)])
        main(["--ledger", str(p), "--out", str(out)])
        rows = {r["rate_hz"]: r for r in csv.DictReader(out.open(encoding="utf-8"))}
        assert float(rows["400"]["cell_fraction"]) < 0.1
        assert rows["400"]["predicted_full"] == "False"
        assert rows["400"]["observed_full"] == "False"
        assert rows["500"]["predicted_full"] == "True"

    def test_a_missing_prediction_prints_as_missing_not_as_zero(self, tmp_path, capsys):
        """No incommensurate arm means no continuous value, so no prediction exists.

        Printing 0.0 would assert that a flat arm was expected -- a claim about a measurement
        never taken. It must render as absent, and it must not crash on the None either.
        """
        p = tmp_path / "l.csv"
        write_ledger(p, [(400, 10.0), (400, 60.0)])
        report(group_by_rate(load_rate_cells(str(p))))
        row = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip().startswith("400/s")]
        assert row, "the arm should still be listed"
        # Columns: rate q n width incell pred spread call ... -- check the prediction column
        # itself, since "0.0" appears as a substring of the 50.0 width and spread either way.
        fields = row[0].split()
        assert fields[5] == "-", "prediction should be absent, not zero: %r" % row[0]
        assert fields[4] == "-", "cell position should be absent too"


class TestPower:
    """An arm with too few replicates cannot refute a full-spread prediction.

    Spread is a range statistic: one branch gives zero spread however right the model is. At
    300 msg/s only one replicate in five took the upper branch, so two replicates would show a flat
    arm about two thirds of the time by luck. Counting that as a miss would let an unfinished arm
    read as evidence against -- which is exactly what happened to the 600 msg/s arm mid-collection.
    """

    def test_a_flat_result_on_too_few_replicates_is_set_aside(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0),       # q=1 full, well powered
                         (400, 50.0), (400, 52.0),      # q=2 on grid -> flat
                         (600, 34.0), (600, 34.3),      # q=3 full predicted, n=2, came out flat
                         (457, 49.0), (457, 50.0)])
        g = {x["rate"]: x for x in group_by_rate(load_rate_cells(str(p)))}
        assert g[600]["underpowered"] is True
        v = verdict(group_by_rate(load_rate_cells(str(p))))
        assert v["outcome"] == "QUANTISED"
        assert not any(x["rate"] == 600 for x in v["disagree"])
        assert "underpowered and set aside: q=3 at n=2" in v["why"]

    def test_enough_replicates_makes_a_flat_result_count_against(self, tmp_path):
        """The guard must not simply excuse every inconvenient arm."""
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0),
                         (400, 50.0), (400, 52.0),
                         (600, 34.0), (600, 34.1), (600, 34.2), (600, 34.3), (600, 34.4),
                         (457, 49.0), (457, 50.0)])
        g = {x["rate"]: x for x in group_by_rate(load_rate_cells(str(p)))}
        assert g[600]["underpowered"] is False
        v = verdict(group_by_rate(load_rate_cells(str(p))))
        assert v["outcome"] in ("UNCLEAR", "REFUTED")
        assert any(x["rate"] == 600 for x in v["disagree"])

    def test_a_full_result_is_informative_at_any_n(self, tmp_path):
        """The asymmetry: only the flat case is withheld, never the decisive one."""
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0),
                         (400, 20.0), (400, 80.0),      # q=2 on grid but full spread -- a MISS
                         (457, 49.0), (457, 50.0)])
        g = {x["rate"]: x for x in group_by_rate(load_rate_cells(str(p)))}
        assert g[400]["underpowered"] is False, "a full result must never be set aside"
        v = verdict(group_by_rate(load_rate_cells(str(p))))
        assert any(x["rate"] == 400 for x in v["disagree"])

    def test_an_all_underpowered_run_is_undecided_and_says_why(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(600, 34.0), (600, 34.3),      # the only commensurate arm, n=2, flat
                         (457, 49.0), (457, 50.0)])
        v = verdict(group_by_rate(load_rate_cells(str(p))))
        assert not v["decided"]
        assert "underpowered" in v["why"] and "q=3 at n=2" in v["why"]

    def test_underpowered_arms_are_reported_not_hidden(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0), (400, 50.0), (400, 52.0),
                         (600, 34.0), (600, 34.3), (457, 49.0), (457, 50.0)])
        v = verdict(group_by_rate(load_rate_cells(str(p))))
        assert [g["rate"] for g in v["underpowered"]] == [600]


class TestVerdict:
    def _from(self, tmp_path, rows):
        p = tmp_path / "v.csv"
        write_ledger(p, rows)
        return verdict(group_by_rate(load_rate_cells(str(p))))

    def test_without_an_incommensurate_rate_nothing_can_be_said(self, tmp_path):
        """No continuous value means no cell position, so no arm has a prediction."""
        v = self._from(tmp_path, [(500, 1.0), (500, 99.0), (400, 20.0), (400, 70.0)])
        assert not v["decided"]
        assert "continuous value is unknown" in v["why"]

    def test_without_a_commensurate_rate_the_rule_is_untested(self, tmp_path):
        v = self._from(tmp_path, [(457, 49.0), (457, 50.0), (383, 51.0), (383, 52.0)])
        assert not v["decided"]
        assert "untested" in v["why"]

    def test_both_classes_matching_is_quantised(self, tmp_path):
        v = self._from(tmp_path, [(500, 1.0), (500, 99.0),      # q=1 mid  -> full, is full
                                  (400, 50.0), (400, 52.0),      # q=2 grid -> flat, is flat
                                  (300, 40.0), (300, 74.0),      # q=3 mid  -> full, is full
                                  (457, 49.0), (457, 50.0)])
        assert v["outcome"] == "QUANTISED"
        assert v["disagree"] == []

    def test_a_full_arm_that_comes_out_flat_is_a_miss(self, tmp_path):
        v = self._from(tmp_path, [(500, 49.0), (500, 50.0), (500, 50.5),  # q=1 full, but flat
                                  (400, 50.0), (400, 52.0),      # q=2 grid -> flat, is flat
                                  (457, 49.0), (457, 50.0)])
        assert v["decided"]
        assert v["outcome"] in ("UNCLEAR", "REFUTED")
        assert any(g["q"] == 1 for g in v["disagree"])

    def test_everything_wrong_is_refuted_not_unclear(self, tmp_path):
        v = self._from(tmp_path, [(500, 49.0), (500, 50.0), (500, 50.5),  # q=1 full, but flat
                                  (400, 20.0), (400, 80.0),      # q=2 grid -> flat, but full
                                  (457, 49.0), (457, 50.0)])
        assert v["outcome"] == "REFUTED"

    def test_the_verdict_names_every_arm_and_both_of_its_classes(self, tmp_path):
        """A reader must be able to check the call without rerunning anything."""
        v = self._from(tmp_path, [(500, 1.0), (500, 99.0), (400, 50.0), (400, 52.0),
                                  (300, 40.0), (300, 74.0), (457, 49.0), (457, 50.0)])
        for frag in ("q=1 full/full", "q=2 flat/flat", "q=3 full/full"):
            assert frag in v["why"]


class TestCLI:
    def test_it_reports_and_writes(self, tmp_path, capsys):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0), (457, 50.0), (457, 51.0)])
        out = tmp_path / "q.csv"
        assert main(["--ledger", str(p), "--out", str(out)]) == 0
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert {r["rate_hz"] for r in rows} == {"500", "457"}
        assert "phase denominator" in capsys.readouterr().out

    def test_the_quantised_narrative_only_prints_when_earned(self, tmp_path, capsys):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0), (457, 50.0), (457, 51.0)])
        main(["--ledger", str(p)])
        assert "rule is arithmetic" not in capsys.readouterr().out

    def test_the_quantised_narrative_prints_when_every_arm_matches(self, tmp_path, capsys):
        """The payoff sentence: safety comes from a large denominator, not a chosen rate."""
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0),           # q=1 mid-cell  -> full, is full
                         (400, 50.0), (400, 52.0),          # q=2 on grid   -> flat, is flat
                         (300, 40.0), (300, 74.0),          # q=3 mid-cell  -> full, is full
                         (457, 49.0), (457, 50.0)])         # large q       -> continuous
        assert main(["--ledger", str(p)]) == 0
        out = capsys.readouterr().out
        assert "QUANTISED" in out
        assert "rule is arithmetic" in out
        assert "large denominator" in out

    def test_a_decided_but_unquantised_run_states_the_outcome_without_the_narrative(
            self, tmp_path, capsys):
        """Reaching a verdict is not the same as reaching *that* verdict."""
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 49.0), (500, 50.0), (500, 50.5),  # q=1 full, but flat -- MISS
                         (400, 50.0), (400, 52.0),      # q=2 on grid  -> flat, is flat
                         (300, 40.0), (300, 74.0),      # q=3 mid-cell -> full, is full
                         (457, 49.0), (457, 50.0)])
        report(group_by_rate(load_rate_cells(str(p))))
        out = capsys.readouterr().out
        assert "UNCLEAR" in out              # 2 of 3 match: short of confirmed, short of refuted
        assert "rule is arithmetic" not in out

    def test_a_missing_ledger_is_an_error(self, tmp_path, capsys):
        assert main(["--ledger", str(tmp_path / "no.csv")]) == 1
        assert "missing" in capsys.readouterr().out

    def test_a_ledger_without_rate_cells_is_an_error(self, tmp_path, capsys):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 50.0, "load_sweep")])
        assert main(["--ledger", str(p)]) == 1
        assert "no rate-varying cells" in capsys.readouterr().out

    def test_an_undecided_run_says_so(self, tmp_path, capsys):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0)])
        main(["--ledger", str(p)])
        assert "UNDECIDED" in capsys.readouterr().out
