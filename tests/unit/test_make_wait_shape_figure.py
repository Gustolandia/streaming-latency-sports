"""Tests for scripts/make_wait_shape_figure.py - target 100% branch coverage.

The figure's argument is a comparison of shapes, so the tests guard what would let a misleading
one through: a part whose shares cannot be put on the common scale, a summary without the waits
in bins, and a density that does not sum to the waits it came from.
"""
import csv
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import make_wait_shape_figure as fig_mod  # noqa: E402
from a9_decompose import AT_MS, BAND_EDGES, WAIT_SHAPES  # noqa: E402

REST = WAIT_SHAPES["rest of a slice"]


def _waits(tmp, parts):
    """ack_waits.csv as a9_decompose.py writes it, each part's shares following `parts`."""
    path = tmp / "ack_waits.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["pair", "backend", "load_pct", "x_ms", "share", "rest of a slice",
                    "whole slice"])
        for (pair, backend, load), share_at in parts.items():
            for x in AT_MS:
                w.writerow([pair, backend, load, x, share_at(x), 0.0, 0.0])
    return path


def _summary(tmp, parts):
    path = tmp / "a9_summary.json"
    path.write_text(json.dumps({"a9": parts, "a6": {}}), encoding="utf-8")
    return path


EVEN = [0, 0, 10, 10, 10, 10, 10, 10, 2, 0]
LOBE = [8, 4, 4, 4, 4, 4, 8, 8, 2, 1]


def _real_like(tmp):
    """Two parts that follow the rest of a slice at two scales, and bins of each kind."""
    waits = _waits(tmp, {("matched", "kafka", "88"): lambda x: 0.2 * REST(x, 3.0, 1.0),
                         ("arm", "redis", "75"): lambda x: 0.06 * REST(x, 3.0, 1.0)})
    summary = _summary(tmp, {"matched, kafka": {"wake_bins": EVEN, "preempt_bins": LOBE},
                             "arm, redis": {"wake_bins": EVEN, "preempt_bins": LOBE}})
    return waits, summary


class TestLoad:

    def test_every_part_is_read_in_order_of_the_wait(self, temp_dir):
        waits, summary = _real_like(temp_dir)
        parts = fig_mod.load_waits(waits)
        assert sorted(parts) == [("arm", "redis", "75"), ("matched", "kafka", "88")]
        xs = [x for x, _ in parts[("matched", "kafka", "88")]]
        assert xs == sorted(xs) and len(xs) == 20
        assert fig_mod.load_bins(summary)["arm, redis"]["preempt"] == LOBE

    def test_an_empty_file_is_refused(self, temp_dir):
        with pytest.raises(ValueError, match="holds no part"):
            fig_mod.load_waits(_waits(temp_dir, {}))

    def test_a_part_with_nobody_waiting_past_a_millisecond_is_refused(self, temp_dir):
        path = _waits(temp_dir, {("arm", "kafka", "75"): lambda x: 0.1 if x < 1.0 else 0.0})
        with pytest.raises(ValueError, match="no acknowledgment waiting past 1 ms"):
            fig_mod.load_waits(path)

    def test_a_summary_without_the_bins_is_refused(self, temp_dir):
        path = _summary(temp_dir, {"arm, kafka": {"wake_bins": EVEN, "preempt_bins": None}})
        with pytest.raises(ValueError, match="lacks the waits in bins for arm, kafka"):
            fig_mod.load_bins(path)


class TestTheDensities:

    def test_they_are_shares_per_millisecond_and_sum_to_one_over_the_bins(self):
        found = fig_mod.densities(EVEN)
        widths = [b - a for a, b in zip(BAND_EDGES, BAND_EDGES[1:])]
        assert sum(d * w for d, w in zip(found, widths)) == pytest.approx(1.0)
        assert found[2] == pytest.approx(10 / 62.0 / 0.5)


class TestThePanels:

    def test_the_points_sit_on_the_rest_of_a_slice_when_they_follow_it(self, temp_dir):
        waits, _ = _real_like(temp_dir)
        fig, ax = plt.subplots()
        fig_mod.plot_survival(ax, fig_mod.load_waits(waits))
        curve = next(line for line in ax.get_lines() if line.get_label() == "rest of a slice")
        points = [line for line in ax.get_lines() if line.get_linestyle() == "None"]
        assert len(points) == 2
        for line in points:
            dodge = 0.0 if line.get_label() == "first x86, Kafka" else -0.06
            for x, y in zip(line.get_xdata(), line.get_ydata()):
                assert y == pytest.approx(REST(x - dodge, 3.0, 1.0) / REST(1.0, 3.0, 1.0))
        assert max(curve.get_ydata()) == pytest.approx(1.0 / REST(1.0, 3.0, 1.0))
        labels = [t.get_text() for t in ax.get_legend().get_texts()]
        assert "Arm64, Redis" in labels and "first x86, Kafka" in labels
        plt.close(fig)

    def test_an_unknown_pair_and_backend_still_get_a_colour_and_a_marker(self, temp_dir):
        waits = _waits(temp_dir, {("other", "nats", "75"): lambda x: 0.1 * REST(x, 3.0, 1.0)})
        fig, ax = plt.subplots()
        fig_mod.plot_survival(ax, fig_mod.load_waits(waits))
        (line,) = [l for l in ax.get_lines() if l.get_linestyle() == "None"]
        assert line.get_marker() == "^" and line.get_label() == "other, Nats"
        plt.close(fig)

    def test_each_part_gets_a_step_for_each_cause_and_one_label_each(self, temp_dir):
        _, summary = _real_like(temp_dir)
        fig, ax = plt.subplots()
        fig_mod.plot_causes(ax, fig_mod.load_bins(summary))
        assert len(ax.get_lines()) == 6, "two parts and the pool, for each cause"
        labels = [t.get_text() for t in ax.get_legend().get_texts()]
        assert labels == ["begun by a wake-up, pooled", "begun by a preemption, pooled"]
        pooled = [l for l in ax.get_lines() if l.get_linewidth() > 2]
        assert list(pooled[1].get_ydata()[:-1]) == pytest.approx(fig_mod.densities(
            [2 * n for n in LOBE])), "the pool is the parts' counts added"
        plt.close(fig)


class TestMain:

    def test_it_writes_the_figure_in_both_formats(self, temp_dir, capsys, monkeypatch):
        waits, summary = _real_like(temp_dir)
        monkeypatch.setattr(fig_mod.figure_legibility, "check", lambda fig, stem: None)
        out = temp_dir / "figures"
        assert fig_mod.main(["--waits", str(waits), "--summary", str(summary),
                             "--out", str(out)]) == 0
        assert (out / "wait_shape.pdf").exists() and (out / "wait_shape.png").exists()
        assert "OK wrote" in capsys.readouterr().out
