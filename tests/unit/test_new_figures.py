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
    # 15 Oct 2026: the per-group histograms Fig. 2 splits by broker, summing to the pooled bins
    # above (bin index (lo + 100000) / 50).
    groups = tmp_path / "span_by_condition.json"
    groups.write_text(json.dumps({"bin_lo_us": -100000, "bin_width_us": 50, "conditions": {
        "kafka_n1_feed1#pass": {"S": {"bins": {"1992": 20, "2012": 900}, "under": 0,
                                      "over": 45}},
        "redis_n1_feed1#pass": {"S": {"bins": {"1992": 10, "2000": 50, "2012": 20},
                                      "under": 0, "over": 0}}}}), encoding="utf-8")
    monkeypatch.setattr(mdh, "BY_CONDITION_JSON", str(groups))
    return tmp_path


def _runs():
    """Per-run rates as manipulation_runs.rate_by_load gives them: two cells a broker."""
    out = []
    for backend in ("kafka", "redis"):
        for i in range(3):
            out.append({"backend": backend, "priority": "normal", "campaign": "E-A3",
                        "cell": "bg7", "rho": 0.8775, "rate": 0.2 + 0.01 * i,
                        "run": "r%s%d" % (backend, i)})
            out.append({"backend": backend, "priority": "real-time", "campaign": "E-A5",
                        "cell": "l88_rt", "rho": 0.8812, "rate": 0.0,
                        "run": "t%s%d" % (backend, i)})
    return out


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

    def test_the_two_panel_build_is_the_papers_first_figure(self, hist_env, tmp_path, capsys):
        """Panels (a) and (b) alone, as the paper's Fig. 1 since v5: both formats, one stem."""
        made = mdh.build_two_ways(str(tmp_path / "two"))
        assert sorted(os.path.basename(p) for p in made) == ["two_ways.pdf", "two_ways.png"]
        assert all(os.path.getsize(p) > 0 for p in made)
        rc = mdh.main(["--two", "--out-dir", str(tmp_path / "cli")])
        assert rc == 0
        assert "two_ways.pdf" in capsys.readouterr().out

    def test_the_column_build_is_the_distribution_of_s(self, hist_env, tmp_path, capsys):
        """The paper's Fig. 2 at column width: since 15 Oct 2026, (a) S by broker over the pooled
        bars with a linear inset, and (b) each run's rate against utilization."""
        made = mdh.build_s_distribution(str(tmp_path / "s"), runs=_runs())
        assert sorted(os.path.basename(p) for p in made) == ["s_distribution.pdf",
                                                             "s_distribution.png"]
        assert all(os.path.getsize(p) > 0 for p in made)
        # 15 Oct 2026: the cropped file, not the canvas, is what the page scales to the column.
        # Labels standing past the canvas made it 3.61 in, and the page shrank its 8 pt type.
        import figure_legibility
        from pypdf import PdfReader
        pdf = [p for p in made if p.endswith(".pdf")][0]
        width = float(PdfReader(pdf).pages[0].mediabox.width) / 72.0
        assert width <= figure_legibility.COLUMN_WIDTH_IN, width
        # 15 Oct 2026: saved whole, so the file is the canvas and the page prints it at its own
        # size; cropped, it came out 3.47 in and the page enlarged it, 5 pt taller.
        assert abs(width - figure_legibility.COLUMN_WIDTH_IN) < 0.005, width
        height = float(PdfReader(pdf).pages[0].mediabox.height) / 72.0
        assert abs(height - mdh.S_DISTRIBUTION_IN[1]) < 0.005, height
        rc = mdh.main(["--s-distribution", "--out-dir", str(tmp_path / "cli")])
        assert rc == 0
        assert "s_distribution.pdf" in capsys.readouterr().out


class TestFigureTwosPanels:
    """15 Oct 2026, both referees: S by broker on the same bins, the axis naming what a bar
    counts, a linear inset around zero, and the per-run rate against utilization."""

    def test_the_brokers_bins_sum_to_the_pooled_ones(self, hist_env):
        brokers, extra = mdh.read_broker_hist()
        assert brokers["kafka"] == [(-400, -350, 20), (600, 650, 900)]
        assert brokers["redis"] == [(-400, -350, 10), (0, 50, 50), (600, 650, 20)]
        assert extra == {"kafka": {"under": 0, "over": 45}, "redis": {"under": 0, "over": 0}}

    def test_an_outline_drops_to_zero_where_a_broker_has_no_messages(self):
        edges, counts = mdh._steps([(0, 50, 3), (100, 150, 2)], 0, 200)
        assert edges == [0, 50, 100, 150, 200] and counts == [3, 0, 2, 0]

    def test_panel_a_names_what_a_bar_counts_and_draws_each_broker(self, hist_env):
        fig, ax = plt.subplots()
        try:
            series, extra = mdh.read_hist()
            brokers, _ = mdh.read_broker_hist()
            mdh.plot_brokers(ax, series, extra, brokers)
            assert ax.get_ylabel() == "messages per 50 µs bin\n(log scale)"
            assert ax.get_yscale() == "log"
            # 15 Oct 2026: two columns of short entries, D's alone, so that the legend stands
            # above every bin; the caption says D never falls below zero.
            legend = ax.get_legend()
            assert [t.get_text() for t in legend.get_texts()] == [
                "Kafka", "Redis", "$D$", "both brokers"]
            assert getattr(legend, "_ncols", getattr(legend, "_ncol", None)) == 2
            # The ticks and the y label at 8 pt, as the paper's other figures; the x label, whose
            # subscripts are what the reader compares, at the size that prints them at 6.5 pt;
            # the counts written out, as 10^n their exponents printed at 5.6 pt.
            assert ax.yaxis.get_label().get_fontsize() == 8
            assert ax.xaxis.get_label().get_fontsize() == mdh.MATH_PT
            assert [ax.yaxis.get_major_formatter()(v, 0) for v in (1, 100, 1e4, 1e6)] == [
                "1", "100", "10k", "1M"]
            # 15 Oct 2026, later: one line for the page budget; the caption gives the counts
            # outside the window.
            assert ax.get_title(loc="left") == "(a) 30 below zero, 2.87% of 1,045"
            (inset,) = ax.child_axes
            assert inset.get_xlim() == (-mdh.INSET_US, mdh.INSET_US)
            assert inset.get_yscale() == "linear"
            assert [t.get_text() for t in inset.texts] == ["linear"]
        finally:
            plt.close(fig)

    def test_panel_a_without_its_inset(self, hist_env):
        fig, ax = plt.subplots()
        try:
            series, extra = mdh.read_hist()
            mdh.plot_brokers(ax, series, extra, mdh.read_broker_hist()[0], inset=False)
            assert ax.child_axes == []
        finally:
            plt.close(fig)

    def test_panel_b_draws_every_run_by_broker_and_priority(self):
        fig, axes = plt.subplots(1, 2, sharey=True)
        try:
            mdh.plot_rate_by_load(axes, _runs())
            for ax, name in zip(axes, ("Kafka", "Redis")):
                assert ax.get_title(loc="left") == name
                normal, rt = ax.collections
                assert len(normal.get_offsets()) == len(rt.get_offsets()) == 3
                xs = sorted(x for x, _ in normal.get_offsets())
                assert len(set(xs)) == 3, "runs of one cell are set apart"
            # 15 Oct 2026: in the Kafka panel's upper left, where no run reaches; in the Redis
            # panel it hid the highest run.
            assert axes[1].get_legend() is None
            labels = [t.get_text() for t in axes[0].get_legend().get_texts()]
            assert labels == ["normal priority", "real-time priority"]
            assert axes[0].get_ylim()[0] < 0.0, "a rate of zero is not cut by the axis"
            assert axes[0].get_ylim() == mdh.PANEL_B_YLIM
        finally:
            plt.close(fig)


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
