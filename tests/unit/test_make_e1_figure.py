"""Tests for scripts/make_e1_figure.py - target 100% branch coverage."""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from make_e1_figure import (  # noqa: E402
    condition_medians,
    plot_tti,
    plot_decomposition,
    _save,
    main,
)

COLUMNS = ["backend", "n", "tti_p50", "schedlag_p50", "transport_p50"]


def _rows(backend, n, reps, tti, sched, transport):
    return [
        {"backend": backend, "n": n, "tti_p50": tti + i,
         "schedlag_p50": sched, "transport_p50": transport}
        for i in range(reps)
    ]


def _frame(*groups):
    rows = []
    for g in groups:
        rows.extend(_rows(*g))
    return pd.DataFrame(rows, columns=COLUMNS)


def _corpus():
    """Two backends across two concurrency levels, shaped like the real E1 corpus."""
    return _frame(
        ("kafka", 1, 3, 105.0, 103.0, 0.79),
        ("kafka", 9, 3, 105.0, 103.0, 0.80),
        ("redis", 1, 3, 5.0, 1.4, 0.72),
        ("redis", 9, 3, 5.0, 1.9, 0.81),
    )


@pytest.fixture
def ax():
    fig, a = plt.subplots()
    yield a
    plt.close(fig)


class TestConditionMedians:
    def test_collapses_runs_to_one_row_per_cell(self):
        med = condition_medians(_corpus())
        assert len(med) == 4
        assert set(med["backend"]) == {"kafka", "redis"}

    def test_takes_the_median_not_the_mean(self):
        # tti values are 105, 106, 107 -> median 106, mean 106 too, so use a skewed set.
        df = _frame(("kafka", 1, 4, 105.0, 103.0, 0.79))
        df.loc[3, "tti_p50"] = 1000.0  # a startup outlier the median must ignore
        med = condition_medians(df)
        assert med["tti_p50"].iloc[0] == pytest.approx(106.5)

    def test_sorted_by_backend_then_n(self):
        med = condition_medians(_corpus())
        assert list(med["backend"]) == ["kafka", "kafka", "redis", "redis"]
        assert list(med["n"]) == [1, 9, 1, 9]

    def test_empty_passes_through(self):
        empty = pd.DataFrame(columns=COLUMNS)
        assert condition_medians(empty).empty


class TestPlotTti:
    def test_draws_one_line_per_backend(self, ax):
        plot_tti(ax, condition_medians(_corpus()))
        assert len(ax.get_lines()) == 2
        assert ax.get_yscale() == "log"

    def test_skips_a_missing_backend(self, ax):
        redis_only = _frame(("redis", 1, 2, 5.0, 1.4, 0.72))
        plot_tti(ax, condition_medians(redis_only))
        assert len(ax.get_lines()) == 1


class TestPlotDecomposition:
    def test_draws_two_bars_per_backend_per_n(self, ax):
        plot_decomposition(ax, condition_medians(_corpus()))
        # 2 backends x 2 components x 2 concurrency levels
        assert len(ax.patches) == 8
        assert [t.get_text() for t in ax.get_xticklabels()] == ["1", "9"]

    def test_skips_a_missing_backend(self, ax):
        kafka_only = _frame(("kafka", 1, 2, 105.0, 103.0, 0.79))
        plot_decomposition(ax, condition_medians(kafka_only))
        assert len(ax.patches) == 2

    def test_absent_cell_plots_as_zero(self, ax):
        """Redis is measured at N=9 only; its N=1 bars must still be placed, at zero."""
        ragged = _frame(
            ("kafka", 1, 2, 105.0, 103.0, 0.79),
            ("kafka", 9, 2, 105.0, 103.0, 0.80),
            ("redis", 9, 2, 5.0, 1.9, 0.81),
        )
        plot_decomposition(ax, condition_medians(ragged))
        assert len(ax.patches) == 8
        assert sum(1 for p in ax.patches if p.get_height() == 0) == 2


class TestSave:
    def test_writes_png_and_pdf(self, temp_dir):
        fig, _ = plt.subplots()
        written = _save(fig, temp_dir / "figs", "stem")
        plt.close(fig)
        assert [p.name for p in written] == ["stem.png", "stem.pdf"]
        assert all(p.exists() and p.stat().st_size > 0 for p in written)


class TestMain:
    def test_end_to_end(self, temp_dir, capsys):
        src = temp_dir / "by_run.csv"
        _corpus().to_csv(src, index=False)
        out = temp_dir / "figures"
        assert main(["--by-run-csv", str(src), "--out", str(out), "--stem", "e1"]) == 0
        assert (out / "e1.pdf").exists()
        assert "wrote" in capsys.readouterr().out

    def test_missing_input_is_an_error(self, temp_dir, capsys):
        assert main(["--by-run-csv", str(temp_dir / "nope.csv")]) == 1
        assert "missing input" in capsys.readouterr().out

    def test_empty_input_is_an_error(self, temp_dir, capsys):
        src = temp_dir / "empty.csv"
        pd.DataFrame(columns=COLUMNS).to_csv(src, index=False)
        assert main(["--by-run-csv", str(src), "--out", str(temp_dir / "o")]) == 1
        assert "no rows to plot" in capsys.readouterr().out
