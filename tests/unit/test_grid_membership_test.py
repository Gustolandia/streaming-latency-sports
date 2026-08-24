"""Tests for grid_membership_test (referee M4).

The statistic replaces the branch-count binomial that smeared arms broke. What must hold: a
grid-pinned arm rejects the continuum; a continuum-like arm does not; a degenerate arm is
reported as unpowered rather than counted either way; and the exact binomial interval is correct
against known values, because a hand-rolled Clopper-Pearson that is silently wrong would
invalidate every branch weight the paper prints.
"""
import csv
import math
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from grid_membership_test import (  # noqa: E402
    analyse, arm_statistic, clopper_pearson, incommensurate_sd, load_arms, main, mc_pvalue,
    q_of, p_of, spearman, theta_local, vertex_distance,
)

FIELDS = ("campaign", "cell", "level", "valid", "count_source",
          "kept", "discarded_zero", "discarded_negative")


def write_ledger(path, rows):
    """rows: (rate, retention_pct[, campaign, valid, source])"""
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for i, r in enumerate(rows):
            rate, ret = r[0], r[1]
            camp = r[2] if len(r) > 2 else "rate_phase"
            valid = r[3] if len(r) > 3 else "1"
            src = r[4] if len(r) > 4 else "shutdown_hook"
            kept = int(round(ret * 1000))
            w.writerow([camp, "r%d_rep%d" % (rate, i), rate, valid, src,
                        kept, 100000 - kept, 0])


# A block of incommensurate arms defining theta ~ 50 and a ~1.2-point noise floor.
INC = ([(457, 49.0), (457, 50.0), (457, 51.0),
        (383, 49.5), (383, 50.5), (383, 51.5),
        (889, 48.5), (889, 49.5), (889, 50.5)])


class TestPrimitives:
    def test_fraction_arithmetic(self):
        assert (q_of(500), p_of(500)) == (1, 2)
        assert (q_of(300), p_of(300)) == (3, 10)
        assert q_of(457) > 64

    def test_vertex_distance_on_and_off_grid(self):
        assert vertex_distance(33.333, 3) == pytest.approx(0.0, abs=0.01)
        assert vertex_distance(50.0, 3) == pytest.approx(100.0 / 6, abs=0.01)

    def test_arm_statistic_is_normalised_by_cell_width(self):
        # Two replicates each 5 points off a q=1 vertex: D = 5/100.
        assert arm_statistic([5.0, 95.0], 1) == pytest.approx(0.05)
        # Same absolute distances at q=3 are three times larger in cell units.
        assert arm_statistic([38.333, 61.667], 3) == pytest.approx(0.15, abs=0.001)

    def test_spearman_known_values(self):
        assert spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)
        assert spearman([1, 2, 3], [30, 20, 10]) == pytest.approx(-1.0)
        assert spearman([1, 1, 1], [1, 2, 3]) == 0.0


class TestClopperPearson:
    """Checked against published exact intervals."""

    def test_zero_and_full_are_closed_at_the_boundary(self):
        lo, hi = clopper_pearson(0, 5)
        assert lo == 0.0 and hi == pytest.approx(0.522, abs=0.005)
        lo, hi = clopper_pearson(5, 5)
        assert hi == 1.0 and lo == pytest.approx(0.478, abs=0.005)

    def test_a_textbook_interval(self):
        lo, hi = clopper_pearson(2, 10)
        assert lo == pytest.approx(0.0252, abs=0.002)
        assert hi == pytest.approx(0.5561, abs=0.002)

    def test_interval_contains_the_point_estimate(self):
        for k, n in ((1, 5), (3, 7), (9, 12)):
            lo, hi = clopper_pearson(k, n)
            assert lo < k / n < hi


class TestNullIngredients:
    def test_theta_is_rate_local_and_clamped_outside_the_fit(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, INC)
        theta, pts = theta_local(load_arms(str(p)))
        assert theta is not None and len(pts) == 3
        # Outside the fitted range the nearest measured median is used, not the extrapolation.
        assert theta(2000) == pytest.approx(theta(889))
        assert theta(100) == pytest.approx(theta(383))

    def test_sigma_pools_within_arm_scatter(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, INC)
        sd = incommensurate_sd(load_arms(str(p)))
        assert 0.5 < sd < 2.0

    def test_no_incommensurate_arms_means_no_analysis(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0)])
        assert analyse(load_arms(str(p))) is None


class TestInference:
    def test_a_pinned_arm_rejects_the_continuum(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, INC + [(500, 0.5), (500, 0.7), (500, 99.8), (500, 99.9)])
        res = analyse(load_arms(str(p)), iters=2000)
        row = next(r for r in res["rows"] if r["rate_hz"] == 500)
        assert row["powered"] and row["p_value"] < 0.01

    def test_a_continuum_arm_does_not_reject(self, tmp_path):
        """Replicates scattered at theta look exactly like the null and must not reject."""
        p = tmp_path / "l.csv"
        write_ledger(p, INC + [(300, 49.0), (300, 50.0), (300, 50.6), (300, 51.0)])
        res = analyse(load_arms(str(p)), iters=2000)
        row = next(r for r in res["rows"] if r["rate_hz"] == 300)
        assert row["powered"] and row["p_value"] > 0.05

    def test_a_degenerate_arm_is_reported_unpowered(self, tmp_path):
        """theta on the arm's own grid: the test must say it cannot decide, not pick a side."""
        p = tmp_path / "l.csv"
        write_ledger(p, INC + [(400, 50.0), (400, 50.4), (400, 50.8)])
        res = analyse(load_arms(str(p)), iters=500)
        row = next(r for r in res["rows"] if r["rate_hz"] == 400)
        assert row["powered"] is False

    def test_branch_weights_only_where_classifiable(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, INC + [(500, 0.5), (500, 0.7), (500, 99.8), (500, 99.9),
                               (300, 45.0, "rate_phase2"), (300, 55.0, "rate_phase2"),
                               (300, 50.0, "rate_phase2")])
        res = analyse(load_arms(str(p)), iters=500)
        r500 = next(r for r in res["rows"] if r["rate_hz"] == 500)
        r300 = next(r for r in res["rows"] if r["rate_hz"] == 300)
        assert r500["branch_classifiable"] is True
        assert r500["upper_ci_lo"] < r500["upper_weight"] < r500["upper_ci_hi"]
        assert r300["branch_classifiable"] is False

    def test_single_replicate_arms_are_excluded(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, INC + [(625, 40.0)])
        res = analyse(load_arms(str(p)), iters=200)
        assert all(r["rate_hz"] != 625 for r in res["rows"])

    def test_mc_pvalue_is_anticonservative_never(self):
        """Observed exactly at the null centre must give a large p, by construction."""
        assert mc_pvalue(4, 3, 50.0, 1.2, observed=0.49, iters=500) > 0.3


class TestCLI:
    def test_reports_and_writes(self, tmp_path, capsys):
        led = tmp_path / "l.csv"
        write_ledger(led, INC + [(500, 0.5), (500, 99.8), (500, 99.9)])
        out = tmp_path / "g.csv"
        assert main(["--ledger", str(led), "--iters", "500", "--out", str(out)]) == 0
        text = capsys.readouterr().out
        assert "p_value" in text and "Spearman" not in text  # <3 arms: no correlation printed
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert rows and "p_value" in rows[0]

    def test_spearman_printed_with_three_or_more_arms(self, tmp_path, capsys):
        led = tmp_path / "l.csv"
        write_ledger(led, INC + [(500, 0.5), (500, 99.8), (300, 34.0), (300, 66.0),
                                 (625, 41.0), (625, 59.0)])
        assert main(["--ledger", str(led), "--iters", "300"]) == 0
        assert "Spearman" in capsys.readouterr().out

    def test_missing_ledger_errors(self, tmp_path, capsys):
        assert main(["--ledger", str(tmp_path / "no.csv")]) == 1
        assert "missing" in capsys.readouterr().out

    def test_no_null_available_errors(self, tmp_path, capsys):
        led = tmp_path / "l.csv"
        write_ledger(led, [(500, 1.0), (500, 99.0)])
        assert main(["--ledger", str(led)]) == 1
        assert "incommensurate" in capsys.readouterr().out


class TestTheLedgerRowsAndBetaEdgesThatAreRefused:
    """What the grid test declines to read, and the two ends of its own beta CDF.

    The grid law is the paper's strongest arithmetic claim, so what feeds it matters as much
    as the statistic: a row from the wrong campaign, an invalid cell, a count taken from
    somewhere other than the shutdown hook, or a level that will not parse must all be left
    out. Each of them would move theta without leaving a trace.
    """

    def test_a_row_from_another_campaign_is_not_read(self, tmp_path):
        p = tmp_path / "ledger.csv"
        write_ledger(p, [(457, 49.0), (457, 50.0), (457, 51.0, "some_other_campaign")])
        assert len(load_arms(p)[457]) == 2

    def test_an_invalid_cell_is_not_read(self, tmp_path):
        p = tmp_path / "ledger.csv"
        write_ledger(p, [(457, 49.0), (457, 50.0), (457, 51.0, "rate_phase", "0")])
        assert len(load_arms(p)[457]) == 2

    def test_a_count_from_the_wrong_source_is_not_read(self, tmp_path):
        """Only the shutdown hook counts the discards; the combined CSV does not."""
        p = tmp_path / "ledger.csv"
        write_ledger(p, [(457, 49.0), (457, 50.0),
                         (457, 51.0, "rate_phase", "1", "combined_csv")])
        assert len(load_arms(p)[457]) == 2

    def test_a_level_that_will_not_parse_is_not_read(self, tmp_path):
        p = tmp_path / "ledger.csv"
        write_ledger(p, [(457, 49.0), (457, 50.0)])
        with p.open("a", newline="", encoding="utf-8") as fh:
            fh.write("rate_phase,rX,not-a-number,1,shutdown_hook,50000,50000,0\n")
        assert load_arms(p) == {457: [49.0, 50.0]}

    def test_a_cell_that_measured_nothing_is_not_an_arm(self, tmp_path):
        """Zero kept and zero discarded is no retention at all, not a retention of zero."""
        p = tmp_path / "ledger.csv"
        write_ledger(p, [(457, 49.0), (457, 50.0)])
        with p.open("a", newline="", encoding="utf-8") as fh:
            fh.write("rate_phase,r457_empty,457,1,shutdown_hook,0,0,0\n")
        assert load_arms(p) == {457: [49.0, 50.0]}

    def test_the_interval_is_one_sided_at_the_ends_of_the_range(self):
        """Zero successes has no lower bound to estimate and n successes has no upper one;
        inventing either would narrow an interval the data do not support."""
        assert clopper_pearson(0, 10)[0] == 0.0
        assert clopper_pearson(10, 10)[1] == 1.0

    def test_the_continued_fraction_answers_even_when_it_does_not_converge_early(self):
        """Lentz's recurrence is capped at two hundred iterations.

        On the small arm counts this project measures it converges in a few dozen, but the
        cap is what guarantees the routine returns at all, and a run that reaches it must
        come back with the value it had rather than loop or raise. A million trials is well
        past the cap and is the case that exercises it.
        """
        lo, hi = clopper_pearson(500_000, 1_000_000)
        assert 0.49 < lo < 0.5 < hi < 0.51
        assert lo < hi
