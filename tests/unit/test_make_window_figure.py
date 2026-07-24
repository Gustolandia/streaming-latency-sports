"""Tests for scripts/make_window_figure.py - target 100% branch coverage.

The figure's whole argument is that one series grows while another stays flat, so the tests
guard the cases where a partial or untraced sweep would let a misleading figure through.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from make_window_figure import load, plot_counts, plot_share, main  # noqa: E402

COLUMNS = ["window_s", "runs", "events_per_run", "schedlag_p50", "schedlag_max",
           "trace_runs", "trace_events", "slow_wake", "slow_produce"]


def _sweep(tmp, rows):
    df = pd.DataFrame(rows, columns=COLUMNS)
    p = tmp / "window_sweep.csv"
    df.to_csv(p, index=False)
    return p


def _real(tmp):
    """The measured sweep: events grow 8.9x, affected count fixed at four."""
    return _sweep(tmp, [
        [60, 3, 57, 1.57, 103.5, 3, 57, 4, 1],
        [180, 3, 148, 1.60, 103.4, 3, 148, 4, 1],
        [600, 3, 465, 1.59, 103.5, 3, 507, 4, 1],
    ])


@pytest.fixture
def ax():
    fig, a = plt.subplots()
    yield a
    plt.close(fig)


class TestLoad:
    def test_orders_by_window(self, temp_dir):
        p = _sweep(temp_dir, [
            [600, 3, 465, 1.59, 103.5, 3, 507, 4, 1],
            [60, 3, 57, 1.57, 103.5, 3, 57, 4, 1],
        ])
        df = load(p)
        assert list(df["window_s"]) == [60, 600]

    def test_rejects_a_single_window(self, temp_dir):
        p = _sweep(temp_dir, [[60, 3, 57, 1.57, 103.5, 3, 57, 4, 1]])
        with pytest.raises(ValueError, match="at least two"):
            load(p)

    def test_rejects_a_missing_column(self, temp_dir):
        df = pd.DataFrame([[60, 57], [600, 507]], columns=["window_s", "trace_events"])
        p = temp_dir / "w.csv"
        df.to_csv(p, index=False)
        with pytest.raises(ValueError, match="re-run analyze_window"):
            load(p)

    def test_rejects_an_untraced_window(self, temp_dir):
        """A blank count panel is worse than no figure -- it reads as a measured zero."""
        p = _sweep(temp_dir, [
            [60, 3, 57, 1.57, 103.5, 0, None, None, None],
            [600, 3, 465, 1.59, 103.5, 3, 507, 4, 1],
        ])
        with pytest.raises(ValueError, match="untraced"):
            load(p)


class TestPlotCounts:
    def test_draws_both_series(self, temp_dir, ax):
        plot_counts(ax, load(_real(temp_dir)))
        assert len(ax.get_lines()) == 2
        assert ax.get_xscale() == "log" and ax.get_yscale() == "log"

    def test_annotates_the_growth_factor(self, temp_dir, ax):
        plot_counts(ax, load(_real(temp_dir)))
        texts = [t.get_text() for t in ax.texts]
        assert any("8.9" in t for t in texts), texts
        assert any("fixed" in t for t in texts)


class TestPlotShare:
    def test_draws_measured_and_predicted(self, temp_dir, ax):
        plot_share(ax, load(_real(temp_dir)))
        assert len(ax.get_lines()) == 2

    def test_share_falls_as_the_window_grows(self, temp_dir, ax):
        plot_share(ax, load(_real(temp_dir)))
        measured = ax.get_lines()[0].get_ydata()
        assert measured[0] > measured[-1], "the whole point is that the share falls"
        assert measured[0] == pytest.approx(100 * 4 / 57, abs=0.2)


class TestMain:
    def test_end_to_end_writes_both_formats(self, temp_dir, capsys):
        src = _real(temp_dir)
        out = temp_dir / "figs"
        assert main(["--sweep-csv", str(src), "--out", str(out)]) == 0
        assert (out / "window_sweep.pdf").exists()
        assert (out / "window_sweep.png").exists()
        assert "wrote" in capsys.readouterr().out
