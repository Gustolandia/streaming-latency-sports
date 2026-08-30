"""Tests for the three figure scripts added for the co-author call:
make_deletion_histogram.py, make_thread_figure.py, make_axis_comparison.py.

Figures are tested the way the rest of the suite tests them -- on the properties a viewer
depends on (axis scales, series counts, the numbers printed into annotations), not on pixels.
Each build runs against small committed-format fixtures, both layout variants are exercised,
and the quantile helper's off-by-one-bin convention is pinned to the manuscript's own 8.43%,
because getting it wrong once already moved a headline number to 11.27%.
"""
import csv
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import make_deletion_histogram as mdh  # noqa: E402
import make_thread_figure as mtf  # noqa: E402
import make_axis_comparison as mac  # noqa: E402


def write_hist_csv(path, rows, names=("ack", "send", "output_send", "tti")):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["bin_low_us", "bin_high_us"] + list(names))
        for r in rows:
            w.writerow(r)


@pytest.fixture
def hist_env(tmp_path, monkeypatch):
    """A small span histogram + stats pair in the committed format."""
    hist = tmp_path / "span_histogram.csv"
    write_hist_csv(hist, [
        [-400, -350, 30, 0, 0, 0],
        [0, 50, 50, 20, 20, 20],
        [600, 650, 920, 980, 980, 980],
        ["UNDERFLOW", "", 0, 0, 0, 0],
        ["OVERFLOW", "", 45, 0, 0, 0],
    ])
    stats = tmp_path / "span_histogram_stats.json"
    counts = {"total": 1000, "negative": 30, "zero": 0, "non_positive": 30,
              "retained_discard": 970, "retained_nan": 970, "retained_zero": 1000,
              "retained_unit": 1000, "retained_keep": 1000,
              "reported_fraction_discard": 0.97}
    ms_rule = {"total": 1000, "kept": 542, "dropped": 458, "retention": 0.542,
               "at_zero": 430, "below_zero": 28}
    stats.write_text(json.dumps({
        "runs": 4, "events": 1000,
        "spans": {"ack": {"counts": counts, "ms_rule": ms_rule,
                          "ms_table": {"-1": 28, "0": 430, "1": 500, "2": 42}}},
    }))
    monkeypatch.setattr(mdh, "HIST_CSV", str(hist))
    monkeypatch.setattr(mdh, "STATS_JSON", str(stats))
    monkeypatch.setattr(mac, "HIST_CSV", str(hist))
    return tmp_path


class TestDeletionHistogram:
    def test_read_hist_separates_bins_from_the_overflow_rows(self, hist_env):
        series, extra = mdh.read_hist()
        assert extra["ack"]["over"] == 45 and extra["ack"]["under"] == 0
        assert len(series["ack"]) == 3

    def test_thousands_formatter_abbreviates_only_from_one_thousand(self):
        assert mdh._thousands(500, None) == "500"
        assert mdh._thousands(300000, None) == "300k"

    def test_the_measured_panel_is_log_scaled_with_the_overflow_in_the_title(self, hist_env):
        fig, ax = plt.subplots()
        series, extra = mdh.read_hist()
        mdh.plot_measured(ax, series, extra)
        assert ax.get_yscale() == "log"
        assert "45" in ax.get_title(loc="left")
        plt.close(fig)

    def test_the_grid_panel_prints_the_deletion_percentage(self, hist_env):
        fig, ax = plt.subplots()
        mdh.plot_grid(ax, mdh.read_stats())
        texts = " ".join(t.get_text() for t in ax.texts)
        assert "45.8%" in texts
        plt.close(fig)

    def test_the_strategies_panel_marks_the_invented_value_bars(self, hist_env):
        fig, ax = plt.subplots()
        mdh.plot_strategies(ax, mdh.read_stats())
        texts = [t.get_text() for t in ax.texts]
        assert texts.count("value not\nmeasured") == 2
        plt.close(fig)

    def test_paper_build_stacks_and_talk_build_rows(self, hist_env, tmp_path):
        paper = mdh.build(str(tmp_path / "f1"), talk=False)
        talk = mdh.build(str(tmp_path / "f2"), talk=True)
        assert any(p.endswith(".pdf") for p in paper)
        assert all(p.endswith(".png") for p in talk)

    def test_main_reports_what_it_wrote(self, hist_env, tmp_path, capsys):
        rc = mdh.main(["--out-dir", str(tmp_path / "figs")])
        assert rc == 0
        assert "wrote" in capsys.readouterr().out


class TestThreadFigure:
    def test_the_diagram_names_every_lane_and_the_inequality(self):
        fig, ax = plt.subplots()
        mtf.plot_threads(ax)
        texts = " ".join(t.get_text() for t in ax.texts)
        for needle in ("producer app thread", "client callback thread", "BROKER",
                       "consumer app thread", "waiting for a core"):
            assert needle in texts
        plt.close(fig)

    def test_both_variants_build(self, tmp_path):
        paper = mtf.build(str(tmp_path / "a"), talk=False)
        talk = mtf.build(str(tmp_path / "b"), talk=True)
        assert len(paper) == 2 and len(talk) == 1

    def test_main_builds_the_talk_variant_on_request(self, tmp_path, capsys):
        rc = mtf.main(["--talk", "--out-dir", str(tmp_path)])
        assert rc == 0
        assert "talk" in capsys.readouterr().out


@pytest.fixture
def omb_env(tmp_path, monkeypatch):
    out = tmp_path / "omb.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["percentile", "latency_ms"])
        for p, v in [(4.48, 1.0), (50.0, 2.0), (99.0, 30.0), (99.97, 600.0)]:
            w.writerow([p, v])
    monkeypatch.setattr(mac, "OMB_CSV", str(out))
    return out


class TestAxisComparison:
    def test_the_quantile_convention_matches_the_manuscript(self, hist_env):
        """The percentile paired with a bin edge is the share strictly below it, over ALL
        events including the 45 above the window: 30 negatives of 1,045 puts the zero
        crossing at 2.87%. Pairing the cumulative count after the bin instead would misplace
        it -- the 8.43-vs-11.27 bug this test exists to pin."""
        pts, total, over, _ = mac.our_quantiles(span="ack")
        crossing = next(p for p, v in pts if v >= 0)
        assert crossing == pytest.approx(100.0 * 30 / 1045)
        assert over == 45 and total == 1045

    def test_the_native_panel_reproduces_the_published_tail_axis(self, omb_env):
        fig, ax = plt.subplots()
        mac.plot_omb_native(ax, mac.omb_published_quantiles.read_csv(str(omb_env)))
        labels = [t.get_text() for t in ax.get_xticklabels()]
        assert labels == ["90.0 %", "99.0 %", "99.9 %", "99.99 %", "99.999 %"]
        plt.close(fig)

    def test_the_shared_axis_panels_annotate_floor_and_crossing(self, hist_env, omb_env):
        omb = mac.omb_published_quantiles.read_csv(str(omb_env))
        fig, (a1, a2) = plt.subplots(1, 2)
        mac.plot_omb(a1, omb)
        texts1 = " ".join(t.get_text() for t in a1.texts)
        assert "floor = 1 ms" in texts1
        ack, total, over, _ = mac.our_quantiles(span="ack")
        send = mac.our_quantiles(span="send")[0]
        mac.plot_ours(a2, ack, send, 100.0 * over / total)
        texts2 = " ".join(t.get_text() for t in a2.texts)
        assert "crosses zero at the" in texts2 and "4.3%" in texts2
        plt.close(fig)

    def test_a_span_with_no_nonnegative_bins_draws_without_a_crossing_marker(self, omb_env):
        fig, ax = plt.subplots()
        mac.plot_ours(ax, [(0.0, -500.0), (50.0, -100.0)], [(0.0, -500.0)], 0.0)
        texts = " ".join(t.get_text() for t in ax.texts)
        assert "crosses zero" not in texts
        plt.close(fig)

    def test_build_produces_both_figures_in_both_variants(self, hist_env, omb_env, tmp_path):
        paper = mac.build(str(tmp_path / "p"), talk=False)
        talk = mac.build(str(tmp_path / "t"), talk=True)
        assert sum(1 for f in paper if "axis_comparison" in f) == 2
        assert sum(1 for f in talk if "omb_axes_explained" in f) == 1

    def test_main_prints_each_artefact(self, hist_env, omb_env, tmp_path, capsys):
        rc = mac.main(["--out-dir", str(tmp_path)])
        assert rc == 0
        assert capsys.readouterr().out.count("wrote") >= 2
