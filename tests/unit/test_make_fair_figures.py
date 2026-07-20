"""Tests for scripts/make_fair_figures.py - target >=95% branch coverage."""
from pathlib import Path
import sys

import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from make_fair_figures import (
    plot_vs_n,
    make_latency_figure,
    make_staleness_figure,
    main,
)
import matplotlib.pyplot as plt


def _latency_csv(path, with_config=True):
    rows = []
    for n in (1, 5, 10, 20):
        rows.append({"backend": "kafka", "config": "single", "n": n, "transport_p50": 2 + n})
        rows.append({"backend": "redis", "config": "single", "n": n, "transport_p50": 4 * n})
        rows.append({"backend": "kafka", "config": "cluster", "n": n, "transport_p50": 3})
    df = pd.DataFrame(rows)
    if not with_config:
        df = df.drop(columns=["config"])
    df.to_csv(path, index=False)


def _staleness_csv(path):
    rows = []
    for n in (1, 5, 10, 20):
        rows.append({"backend": "kafka", "config": "single", "n_concurrency": n, "decision_staleness_prob_s": 0.1 * n})
        rows.append({"backend": "redis", "config": "single", "n_concurrency": n, "decision_staleness_prob_s": 5 * n})
    pd.DataFrame(rows).to_csv(path, index=False)


class TestPlot:
    def test_plot_runs_and_skips_empty_backend(self):
        df = pd.DataFrame([{"backend": "kafka", "n": 1, "v": 2},
                           {"backend": "kafka", "n": 5, "v": 3}])  # no redis rows
        fig, ax = plt.subplots()
        plot_vs_n(ax, df, "n", "v", "t", "y")  # redis series skipped, no crash
        plt.close(fig)


class TestLatencyFigure:
    def test_creates_files(self, temp_dir):
        csv = temp_dir / "lat.csv"
        _latency_csv(csv)
        out = temp_dir / "figs"
        assert make_latency_figure(csv, out) is True
        assert (out / "latency_vs_concurrency.png").exists()
        assert (out / "latency_vs_concurrency.pdf").exists()

    def test_no_config_column(self, temp_dir):
        csv = temp_dir / "lat.csv"
        _latency_csv(csv, with_config=False)
        out = temp_dir / "figs"
        assert make_latency_figure(csv, out) is True

    def test_empty_after_filter(self, temp_dir):
        csv = temp_dir / "lat.csv"
        _latency_csv(csv)
        out = temp_dir / "figs"
        assert make_latency_figure(csv, out, config="nonexistent") is False


class TestStalenessFigure:
    def test_creates_files(self, temp_dir):
        csv = temp_dir / "ds.csv"
        _staleness_csv(csv)
        out = temp_dir / "figs"
        assert make_staleness_figure(csv, out) is True
        assert (out / "decision_staleness_vs_concurrency.png").exists()

    def test_plain_n_column_and_empty(self, temp_dir):
        csv = temp_dir / "ds.csv"
        pd.DataFrame([{"backend": "kafka", "config": "cluster", "n": 1, "decision_staleness_prob_s": 1.0}]).to_csv(csv, index=False)
        out = temp_dir / "figs"
        # only cluster rows -> single filter empties it
        assert make_staleness_figure(csv, out) is False


class TestMain:
    def test_end_to_end(self, temp_dir, capsys):
        lat = temp_dir / "lat.csv"; _latency_csv(lat)
        ds = temp_dir / "ds.csv"; _staleness_csv(ds)
        out = temp_dir / "figs"
        rc = main(["--latency-csv", str(lat), "--staleness-csv", str(ds), "--out", str(out)])
        assert rc == 0
        assert (out / "latency_vs_concurrency.png").exists()
        assert (out / "decision_staleness_vs_concurrency.png").exists()

    def test_missing_inputs(self, temp_dir):
        rc = main(["--latency-csv", str(temp_dir / "no.csv"),
                   "--staleness-csv", str(temp_dir / "no2.csv"), "--out", str(temp_dir / "f")])
        assert rc == 1
