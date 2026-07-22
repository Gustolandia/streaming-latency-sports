"""Tests for scripts/retention_bias.py - target 100% branch coverage."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from retention_bias import (  # noqa: E402
    hl_shift,
    retention,
    impute,
    tipping_point,
    analyse,
    main,
)


def _by_run(n=9, kafka=(1.0,) * 5, redis=(0.9,) * 5):
    rows = [{"backend": "kafka", "n": n, "transport_p50": v} for v in kafka]
    rows += [{"backend": "redis", "n": n, "transport_p50": v} for v in redis]
    return pd.DataFrame(rows)


def _integrity(n=9, k_measured=5, k_kept=5, r_measured=5, r_kept=5):
    return pd.DataFrame([
        {"condition": f"concurrency_n{n}_20260722_000000_kafka",
         "n_runs": k_measured, "n_trustworthy": k_kept},
        {"condition": f"concurrency_n{n}_20260722_000000_redis",
         "n_runs": r_measured, "n_trustworthy": r_kept},
    ])


class TestHlShift:
    def test_identical_samples_shift_by_zero(self):
        assert hl_shift([1, 2, 3], [1, 2, 3]) == pytest.approx(0.0)

    def test_constant_offset(self):
        assert hl_shift([5, 6, 7], [1, 2, 3]) == pytest.approx(4.0)

    def test_sign_follows_the_first_argument(self):
        assert hl_shift([1], [3]) == pytest.approx(-2.0)

    @pytest.mark.parametrize("a,b", [([], [1]), ([1], []), ([], [])])
    def test_empty_is_nan(self, a, b):
        assert np.isnan(hl_shift(a, b))


class TestRetention:
    def test_parses_n_and_backend_from_condition_names(self):
        r = retention(_integrity(n=12, r_measured=36, r_kept=19))
        redis = r[r["backend"] == "redis"].iloc[0]
        assert redis["n"] == 12 and redis["measured"] == 36 and redis["retained"] == 19

    def test_unrecognised_condition_names_are_skipped(self):
        df = pd.DataFrame([{"condition": "junk", "n_runs": 1, "n_trustworthy": 1}])
        assert retention(df).empty


class TestImpute:
    def test_adds_the_dropped_runs_at_the_given_value(self):
        assert impute([1.0, 2.0], 3, 9.0) == [1.0, 2.0, 9.0, 9.0, 9.0]

    def test_nothing_dropped_is_a_no_op(self):
        assert impute([1.0], 0, 9.0) == [1.0]


class TestTippingPoint:
    def test_none_when_nothing_was_dropped(self):
        assert tipping_point([1.0], [1.0], 0, margin=1.0) is None

    def test_none_when_the_median_cannot_be_moved_far_enough(self):
        """With retention above one half the median resists any imputed value."""
        assert tipping_point([1.0] * 10, [1.0] * 10, 3, margin=1.0) is None

    def test_found_when_the_dropped_runs_are_the_majority(self):
        """Below the breakdown point the imputed values take over the median."""
        tip = tipping_point([1.0] * 10, [1.0] * 4, 8, margin=1.0)
        assert tip is not None and tip > 1.0

    def test_returns_the_low_end_when_equivalence_is_already_broken(self):
        tip = tipping_point([100.0] * 5, [1.0] * 2, 6, margin=1.0)
        assert tip == pytest.approx(1.0)


class TestAnalyse:
    def test_full_retention_leaves_the_worst_case_unchanged(self):
        df = analyse(_by_run(), _integrity())
        row = df.iloc[0]
        assert row["n_redis_dropped"] == 0
        assert row["hl_shift_ms"] == pytest.approx(row["hl_shift_worst_case_ms"])
        assert row["above_breakdown"]

    def test_partial_retention_is_bounded_at_the_observed_maximum(self):
        df = analyse(_by_run(redis=(0.5, 0.9, 1.3)), _integrity(r_measured=6, r_kept=3))
        row = df.iloc[0]
        assert row["n_redis_dropped"] == 3
        assert row["redis_retention"] == pytest.approx(0.5)
        assert not row["above_breakdown"], "exactly one half is not above breakdown"
        # Imputing at the observed max can only push the shift down.
        assert row["hl_shift_worst_case_ms"] <= row["hl_shift_ms"]

    def test_flags_a_cell_that_falls_below_breakdown(self):
        df = analyse(_by_run(redis=(0.9, 0.9)), _integrity(r_measured=10, r_kept=2))
        assert not df.iloc[0]["above_breakdown"]
        assert df.iloc[0]["retention_margin"] < 0

    def test_a_cell_missing_one_backend_is_skipped(self):
        only_kafka = pd.DataFrame([{"backend": "kafka", "n": 9, "transport_p50": 1.0}])
        assert analyse(only_kafka, _integrity()).empty

    def test_covers_every_concurrency_level(self):
        by_run = pd.concat([_by_run(n=1), _by_run(n=9)], ignore_index=True)
        integrity = pd.concat([_integrity(n=1), _integrity(n=9)], ignore_index=True)
        assert sorted(analyse(by_run, integrity)["n"]) == [1, 9]


class TestMain:
    def _write(self, tmp, by_run, integrity):
        by_run.to_csv(tmp / "by_run.csv", index=False)
        integrity.to_csv(tmp / "integrity.csv", index=False)
        return ["--by-run-csv", str(tmp / "by_run.csv"),
                "--integrity-csv", str(tmp / "integrity.csv"),
                "--out", str(tmp / "out")]

    def test_end_to_end_reports_survival(self, temp_dir, capsys):
        args = self._write(temp_dir, _by_run(), _integrity())
        assert main(args) == 0
        out = capsys.readouterr().out
        assert "survives the worst case" in out
        assert "breakdown point" in out
        assert (temp_dir / "out" / "e1_retention_bias.csv").exists()

    def test_reports_failure_when_the_bound_does_not_hold(self, temp_dir, capsys):
        args = self._write(temp_dir,
                           _by_run(kafka=(100.0,) * 4, redis=(1.0,) * 2),
                           _integrity(r_measured=10, r_kept=2))
        assert main(args) == 0
        out = capsys.readouterr().out
        assert "does NOT survive" in out
        assert "WARNING" in out and "below 1/2" in out

    def test_missing_input(self, temp_dir, capsys):
        assert main(["--by-run-csv", str(temp_dir / "nope.csv"),
                     "--integrity-csv", str(temp_dir / "nope2.csv")]) == 1
        assert "missing input" in capsys.readouterr().out

    def test_no_comparable_cells(self, temp_dir, capsys):
        only_kafka = pd.DataFrame([{"backend": "kafka", "n": 9, "transport_p50": 1.0}])
        args = self._write(temp_dir, only_kafka, _integrity())
        assert main(args) == 1
        assert "no comparable cells" in capsys.readouterr().out
