"""Tests for scripts/uncertainty_audit.py.

The audit's value is its classification: a quantity put in the wrong class either demands an
interval that cannot exist or excuses one that should. So the tests pin one representative
through every class, and the two interval engines are checked against answers computable by
hand -- Wilson on a known proportion, and the cluster bootstrap against the property that
clustering can only widen, never narrow, the naive interval.
"""
import csv
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import uncertainty_audit as ua  # noqa: E402


class TestWilson:
    def test_a_half_proportion_is_centred_and_symmetric(self):
        lo, hi = ua.wilson(50, 100)
        assert lo < 0.5 < hi
        assert abs((0.5 - lo) - (hi - 0.5)) < 1e-9

    def test_the_empty_denominator_returns_a_degenerate_interval(self):
        assert ua.wilson(0, 0) == (0.0, 0.0)

    def test_extreme_proportions_stay_inside_the_unit_interval(self):
        lo, hi = ua.wilson(0, 20)
        assert lo == 0.0 and hi < 0.25
        lo, hi = ua.wilson(20, 20)
        assert lo > 0.75 and hi == 1.0


class TestClusterBootstrap:
    def test_the_point_estimate_is_the_pooled_rate(self):
        pairs = [(1, 10)] * 30
        v, lo, hi = ua.cluster_boot_rate(pairs, reps=200, seed=1)
        assert v == 10.0
        assert lo <= 10.0 <= hi

    def test_between_run_spread_widens_the_interval(self):
        """Same pooled rate, but one corpus concentrates the negatives in a few runs: its
        interval must be wider, which is the whole reason the run is the resampling unit."""
        even = [(1, 10)] * 30
        lumpy = [(10, 10)] * 3 + [(0, 10)] * 27
        _, lo_e, hi_e = ua.cluster_boot_rate(even, reps=300, seed=2)
        _, lo_l, hi_l = ua.cluster_boot_rate(lumpy, reps=300, seed=2)
        assert (hi_l - lo_l) > (hi_e - lo_e)

    def test_an_empty_resample_denominator_is_skipped_not_divided(self):
        """A corpus of zero-event runs can resample to an empty denominator; those draws are
        dropped and the survivors still form an interval."""
        pairs = [(0, 0)] * 5 + [(1, 2)]
        v, lo, hi = ua.cluster_boot_rate(pairs, reps=100, seed=3)
        assert v == 50.0 and lo >= 0.0


@pytest.fixture
def audit_env(tmp_path, monkeypatch):
    """A miniature ledger and run table exercising every classification rule."""
    tex = tmp_path / "numbers.tex"
    tex.write_text("\n".join([
        r"\newcommand{\tailSlope}{-0.34}",
        r"\newcommand{\tailSlopeCI}{-0.44$ to $-0.23}",
        r"\newcommand{\tracedMleAlpha}{1.19}",
        r"\newcommand{\tracedMleCI}{1.18$--$1.20}",
        r"\newcommand{\auditPct}{58.3}",
        r"\newcommand{\auditPctWorkstation}{62.4}",
        r"\newcommand{\auditPctCloud}{51.9}",
        r"\newcommand{\spanNegAckPct}{8.43}",
        r"\newcommand{\spanKafkaNegAckPct}{8.67}",
        r"\newcommand{\spanRedisNegAckPct}{8.19}",
        r"\newcommand{\spanRuns}{5{,}913}",           # exact count
        r"\newcommand{\spanRunsAckOnlyPct}{100}",     # population
        r"\newcommand{\tracedRate}{0.231}",           # decision list
        r"\newcommand{\chronyPairBound}{12}",         # not an estimate
        r"\newcommand{\harnessSilentWord}{five}",     # wording macro
        r"\newcommand{\mysteryPct}{12.3\%}",          # residual needs-data (regex declines \%)
        r"\newcommand{\oddPct}{12.3}",                # numeric but a Pct: an estimate, not a count
        r"\newcommand{\someCount}{4{,}212}",          # numeric, not a Pct: exact by rule
        "not a macro line",
    ]))
    runs = tmp_path / "recount.csv"
    with open(runs, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["run_id", "backend", "n_events", "neg_ack"])
        w.writeheader()
        for i in range(6):
            w.writerow({"run_id": "r%d" % i, "backend": "kafka" if i % 2 else "redis",
                        "n_events": 100, "neg_ack": 8})
    level = tmp_path / "level.csv"
    with open(level, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["run_id", "n_events", "ms_deleted"])
        w.writeheader()
        for i in range(6):
            w.writerow({"run_id": "r%d" % i, "n_events": 100, "ms_deleted": 45})
    out = tmp_path / "audit.csv"
    monkeypatch.setattr(ua, "NUMBERS_TEX", str(tex))
    monkeypatch.setattr(ua, "RUN_RECOUNT", str(runs))
    monkeypatch.setattr(ua, "RUN_LEVEL", str(level))
    monkeypatch.setattr(ua, "OUT", str(out))
    monkeypatch.setattr(ua, "BOOT_REPS", 60)
    return out


class TestMain:
    def _rows(self, out):
        return {r["quantity"]: r for r in csv.DictReader(open(out))}

    def test_every_class_receives_its_representative(self, audit_env, capsys):
        ua.main()
        rows = self._rows(audit_env)
        assert rows["tailSlope"]["class"] == "has-interval"
        assert rows["tracedMleAlpha"]["class"] == "has-interval"       # via the alias map
        assert rows["spanNegAckPct"]["class"] == "added-here"
        assert rows["spanRuns"]["class"] == "exact"
        assert rows["spanRunsAckOnlyPct"]["class"] == "population"
        # rtLowFactor used to stand for this class. Round 54 gave it a Katz interval, so it
        # is "has-interval" now and cannot represent the debt any more; tracedRate still
        # can, because its clustering unit is undecided rather than merely uncomputed.
        assert rows["tracedRate"]["class"] == "needs-data"
        assert rows["chronyPairBound"]["class"] == "not-an-estimate"
        assert rows["harnessSilentWord"]["class"] == "exact"
        assert rows["mysteryPct"]["class"] == "needs-data"
        assert rows["oddPct"]["class"] == "needs-data"
        assert rows["someCount"]["class"] == "exact"
        assert "intervals computed here" in capsys.readouterr().out

    def test_the_computed_intervals_carry_their_method(self, audit_env):
        ua.main()
        rows = self._rows(audit_env)
        assert "cluster bootstrap" in rows["spanNegAckPct"]["method"]
        assert "Wilson" in rows["auditPct"]["method"]
        assert rows["msGuardDeletionPct (fig. deletion_histogram)"]["interval_95"]

    def test_a_missing_run_level_file_drops_only_that_row(self, audit_env, monkeypatch):
        monkeypatch.setattr(ua, "RUN_LEVEL", str(audit_env) + ".does-not-exist")
        ua.main()
        rows = self._rows(audit_env)
        assert "msGuardDeletionPct (fig. deletion_histogram)" not in rows
        assert rows["spanNegAckPct"]["class"] == "added-here"
