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


def _shape(tmp, acks):
    """ack_wait_shape.json as a9_decompose.py writes it, with only what the figure reads."""
    path = tmp / "ack_wait_shape.json"
    path.write_text(json.dumps({"slice_ms": 3.0, "tick_ms": 1.0, "parts": dict(
        (", ".join(key), {"acks": n, "runs": 3}) for key, n in acks.items())}),
        encoding="utf-8")
    return path


#: Each synthetic part's acknowledgments: 1/6 and 1/20 of them wait past 1 ms (below).
ACKS = {("matched", "kafka", "88"): 3000, ("arm", "redis", "75"): 2000}


def _real_like(tmp):
    """Two parts that follow the rest of a slice at two scales, and bins of each kind."""
    waits = _waits(tmp, {("matched", "kafka", "88"): lambda x: 0.2 * REST(x, 3.0, 1.0),
                         ("arm", "redis", "75"): lambda x: 0.06 * REST(x, 3.0, 1.0)})
    summary = _summary(tmp, {"matched, kafka": {"wake_bins": EVEN, "preempt_bins": LOBE},
                             "arm, redis": {"wake_bins": EVEN, "preempt_bins": LOBE}})
    _shape(tmp, ACKS)
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


class TestThePaperPanel:
    """Fig. 3 since 15 Oct 2026: each part a thin line, their median bold, and the tail past
    3 ms again on a log axis, so that what the rest-of-a-slice shape sets at zero shows."""

    @staticmethod
    def _panel(waits):
        fig, ax = plt.subplots(figsize=(3.46, 2.4))
        tail = fig_mod.plot_survival_compact(ax, fig_mod.load_waits(waits))
        return fig, ax, tail

    def test_each_part_is_a_thin_line_in_its_brokers_colour(self, temp_dir):
        waits, _ = _real_like(temp_dir)
        fig, ax, _ = self._panel(waits)
        thin = [l for l in ax.get_lines() if l.get_linewidth() < 1.0 and l.get_marker() == "None"
                and len(l.get_xdata()) == len(AT_MS)]
        plt.close(fig)
        assert len(thin) == 2, "one line a part, no markers"
        assert sorted(matplotlib.colors.to_hex(l.get_color()) for l in thin) == \
            ["#1f77b4", "#d62728"]
        for line in thin:
            assert list(line.get_ydata()) == pytest.approx(
                [REST(x, 3.0, 1.0) / REST(1.0, 3.0, 1.0) for x in line.get_xdata()])

    def test_the_median_is_bold_and_is_the_parts_median(self, temp_dir):
        parts = {("matched", "kafka", "75"): lambda x: 0.10 * REST(x, 3.0, 1.0),
                 ("matched", "kafka", "88"): lambda x: 0.20 * (REST(x, 3.0, 1.0) + 0.01 * x),
                 ("arm", "redis", "75"): lambda x: 0.05 * (REST(x, 3.0, 1.0) + 0.03 * x)}
        waits = _waits(temp_dir, parts)
        fig, ax, _ = self._panel(waits)
        (median,) = [l for l in ax.get_lines() if l.get_marker() == "o"]
        plt.close(fig)
        assert median.get_linewidth() > 1.0 and matplotlib.colors.to_hex(median.get_color()) == \
            "#000000"
        loaded = fig_mod.load_waits(waits)
        xs, want = fig_mod.median_shares(loaded)
        assert list(median.get_xdata()) == xs and list(median.get_ydata()) == pytest.approx(want)
        normalised = [fig_mod.normalised(p)[1] for p in loaded.values()]
        assert want[-1] == pytest.approx(sorted(n[-1] for n in normalised)[1]), "the middle one"

    def test_the_legend_names_the_shapes_the_median_and_the_brokers(self, temp_dir):
        waits, _ = _real_like(temp_dir)
        fig, ax, _ = self._panel(waits)
        legend = ax.get_legend()
        labels = [t.get_text() for t in legend.get_texts()]
        handles = dict(zip(labels, getattr(legend, "legend_handles", None)
                           or getattr(legend, "legendHandles", [])))
        sizes = (ax.xaxis.get_label().get_fontsize(), ax.yaxis.get_label().get_fontsize(),
                 ax.get_xticklabels()[0].get_fontsize())
        plt.close(fig)
        assert labels == ["rest of a slice", "whole slice", "median", "Kafka", "Redis"]
        # 15 Oct 2026, an internal review: a broker's entry drawn as its parts are, 0.6 pt at 60%,
        # was the faintest line in the legend; it is a sample of the colour, opaque, at 1.2 pt.
        for broker in ("Kafka", "Redis"):
            assert handles[broker].get_linewidth() == pytest.approx(1.2)
            assert handles[broker].get_alpha() in (None, 1.0)
        # The ticks and the axis labels at 8 pt, as the paper's other figures; they printed at
        # 10.1 pt beside 8 pt legends.
        assert sizes == (8, 8, 8)

    def test_the_paper_panel_is_the_column_exactly(self, temp_dir):
        """Saved whole: cropped, it was 3.46 in and the page enlarged it, 1.8 pt taller."""
        from pypdf import PdfReader
        waits, _ = _real_like(temp_dir)
        pdf = fig_mod.build_paper_panel(waits, temp_dir / "out")
        box = PdfReader(str(pdf)).pages[0].mediabox
        assert (float(box.width) / 72.0, float(box.height) / 72.0) == pytest.approx(
            fig_mod.PAPER_IN, abs=0.005)
        assert fig_mod.PAPER_IN[0] == 3.5

    def test_an_unknown_broker_still_gets_a_colour_and_a_name(self, temp_dir):
        waits = _waits(temp_dir, {("other", "nats", "75"): lambda x: 0.1 * REST(x, 3.0, 1.0)})
        fig, ax, _ = self._panel(waits)
        labels = [t.get_text() for t in ax.get_legend().get_texts()]
        plt.close(fig)
        assert "Nats" in labels

    def test_the_inset_draws_the_tail_past_three_ms_on_a_log_axis(self, temp_dir):
        """A referee: a linear axis hides the tail past s + h, where the rest-of-a-slice shape
        is zero; the inset shows how much of the waits it leaves out."""
        waits, _ = _real_like(temp_dir)
        fig, ax, tail = self._panel(waits)
        try:
            assert tail in ax.child_axes and tail.get_yscale() == "log"
            assert tuple(tail.get_xlim()) == pytest.approx((3.0, 5.1))
            rest = [l for l in tail.get_lines() if l.get_linestyle() == "-"
                    and l.get_linewidth() == 1.5]
            (shape,) = [l for l in rest if len(l.get_xdata()) > len(AT_MS)]
            ys = [y for x, y in zip(shape.get_xdata(), shape.get_ydata()) if x >= 4.0]
            assert all(y != y for y in ys), "the shape is undrawn where it is zero, past s + h"
            parts = [l for l in tail.get_lines() if l.get_linewidth() < 1.0
                     and len(l.get_xdata()) == len(AT_MS)]
            assert len(parts) == 2, "the parts are in the inset too"
            assert any(list(l.get_xdata()) == [4.0, 4.0] for l in tail.get_lines()), "s + h"
            card = [p for p in ax.patches if p.get_facecolor()[:3] == (1.0, 1.0, 1.0)]
            assert len(card) == 1, "a white card keeps the panel's grid off the inset's labels"
        finally:
            plt.close(fig)

    def test_the_slice_lines_stop_under_the_inset(self, temp_dir):
        waits, _ = _real_like(temp_dir)
        fig, ax, _ = self._panel(waits)
        verticals = [l for l in ax.get_lines() if len(l.get_xdata()) == 2
                     and l.get_xdata()[0] == l.get_xdata()[1]]
        plt.close(fig)
        assert sorted(l.get_xdata()[0] for l in verticals) == [3.0, 4.0]
        assert all(max(l.get_ydata()) < fig_mod.TAIL_INSET[1] for l in verticals)


class TestTheSharePastOneMs:
    """A referee: the caption normalises at 1 ms but never says what share of acknowledgments
    waited past it. The figure's builder writes it beside its data, per part and per broker."""

    def test_counts_are_recovered_and_pooled_per_broker_and_load(self, temp_dir):
        waits, _ = _real_like(temp_dir)
        found = fig_mod.share_past(fig_mod.load_waits(waits),
                                   fig_mod.load_acks(temp_dir / "ack_wait_shape.json"))
        assert found["parts"]["matched, kafka, 88"]["past"] == 500, "1/6 of 3,000"
        assert found["parts"]["arm, redis, 75"]["past"] == 100, "1/20 of 2,000"
        assert found["by_broker"]["kafka"]["share"] == pytest.approx(1 / 6.0)
        assert found["by_broker_and_load"]["redis, 75"]["acks"] == 2000
        assert found["all"]["past"] == 600 and found["all"]["acks"] == 5000
        assert found["all"]["share"] == pytest.approx(0.12), "pooled, not the parts' mean"
        assert found["all"]["share_lo"] == pytest.approx(0.05)
        assert found["all"]["share_hi"] == pytest.approx(1 / 6.0)

    def test_a_part_without_its_count_is_refused(self, temp_dir):
        waits, _ = _real_like(temp_dir)
        acks = {("matched", "kafka", "88"): 3000}
        with pytest.raises(ValueError, match="no acknowledgment count for part arm, redis, 75"):
            fig_mod.share_past(fig_mod.load_waits(waits), acks)

    def test_a_part_too_large_to_recover_its_count_is_refused(self, temp_dir):
        """Six decimals recover a count exactly below a million acknowledgments; above, the
        rounding could move it by a whole acknowledgment, and the file would say otherwise."""
        waits, _ = _real_like(temp_dir)
        acks = dict(ACKS)
        acks[("arm", "redis", "75")] = fig_mod.EXACT_BELOW
        with pytest.raises(ValueError, match="too many to recover its count"):
            fig_mod.share_past(fig_mod.load_waits(waits), acks)

    def test_the_committed_file_is_what_the_committed_data_give(self, temp_dir):
        """The file a macro will read must match the data it was computed from, as every
        number in the manuscript does: rebuilt here, it must equal the one in the repository."""
        root = Path(__file__).parent.parent.parent / "docs" / "results" / "law" / \
            "strange-results-28-sep"
        found = fig_mod.share_past(fig_mod.load_waits(root / "ack_waits.csv"),
                                   fig_mod.load_acks(root / "ack_wait_shape.json"))
        rebuilt = fig_mod.write_share(found, temp_dir / fig_mod.SHARE_FILE)
        assert Path(rebuilt).read_text(encoding="utf-8") == \
            (root / fig_mod.SHARE_FILE).read_text(encoding="utf-8")
        # 15 Oct 2026, as written: about one acknowledgment in ten waited past 1 ms, Kafka's
        # more often than Redis's, and both roughly twice as often at 88% load as at 75%.
        assert sum(p["acks"] for p in found["parts"].values()) == 1516342
        assert found["by_broker"]["kafka"]["share"] > found["by_broker"]["redis"]["share"]
        for broker in ("kafka", "redis"):
            loads = found["by_broker_and_load"]
            assert loads[broker + ", 88"]["share"] > 1.8 * loads[broker + ", 75"]["share"]


class TestTheFiguresClaim:

    def test_the_parts_median_follows_the_rest_of_a_slice_not_a_whole_one(self):
        """What the figure says, on the committed parts: past the slice, the median of the
        twelve sits much nearer the rest-of-a-slice shape than the whole-slice one."""
        root = Path(__file__).parent.parent.parent / "docs" / "results" / "law" / \
            "strange-results-28-sep"
        parts = fig_mod.load_waits(root / "ack_waits.csv")
        assert len(parts) == 12
        xs, median = fig_mod.median_shares(parts)
        whole = WAIT_SHAPES["whole slice"]

        def gap(shape):
            return sum(abs(m - shape(x, 3.0, 1.0) / shape(1.0, 3.0, 1.0))
                       for x, m in zip(xs, median) if 1.0 <= x <= 4.0)
        assert gap(REST) < 0.25 * gap(whole)


class TestMain:

    def test_it_writes_the_figure_in_both_formats(self, temp_dir, capsys, monkeypatch):
        data = temp_dir / "data"
        data.mkdir()
        waits, summary = _real_like(data)
        monkeypatch.setattr(fig_mod.figure_legibility, "check", lambda fig, stem: None)
        out = temp_dir / "figures"
        assert fig_mod.main(["--waits", str(waits), "--summary", str(summary),
                             "--out", str(out)]) == 0
        assert (out / "wait_shape.pdf").exists() and (out / "wait_shape.png").exists()
        assert (out / "residual_wait.pdf").exists()
        assert "OK wrote" in capsys.readouterr().out
        written = json.loads((data / fig_mod.SHARE_FILE).read_text(encoding="utf-8"))
        assert written["all"]["past"] == 600, "beside the waits it was read from"

    def test_the_share_can_be_read_and_written_elsewhere(self, temp_dir, monkeypatch):
        waits, summary = _real_like(temp_dir)
        monkeypatch.setattr(fig_mod.figure_legibility, "check", lambda fig, stem: None)
        elsewhere = temp_dir / "elsewhere"
        elsewhere.mkdir()
        shape = _shape(elsewhere, ACKS)
        (temp_dir / "ack_wait_shape.json").unlink()
        assert fig_mod.main(["--waits", str(waits), "--summary", str(summary),
                             "--out", str(temp_dir / "figures"), "--shape", str(shape),
                             "--share-out", str(elsewhere / "share.json")]) == 0
        assert json.loads((elsewhere / "share.json").read_text(encoding="utf-8"))["at_ms"] == 1.0
