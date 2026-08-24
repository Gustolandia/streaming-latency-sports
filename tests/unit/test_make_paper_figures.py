"""Tests for scripts/make_paper_figures.py - target 100% branch coverage."""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from make_paper_figures import (  # noqa: E402
    condemned_at,
    plot_pipeline,
    plot_workload,
    plot_concurrency,
    plot_integrity,
    plot_model,
    plot_network,
    _read,
    _save,
    main,
)

INTEGRITY_COLS = ["run_id", "max_neg_fraction", "median_transport_ms",
                  "median_schedlag_ms", "median_output_ms"]


@pytest.fixture
def ax():
    fig, a = plt.subplots()
    yield a
    plt.close(fig)


@pytest.fixture
def axes_pair():
    fig, a = plt.subplots(1, 2)
    yield a
    plt.close(fig)


def _profiles(n=50):
    return pd.DataFrame({
        "mean_rate_evs": [0.30 + i * 0.004 for i in range(n)],
        "burstiness": [5.0 + i * 0.05 for i in range(n)],
    })


def _slots():
    return pd.DataFrame({"n_matches": [1] * 30 + [2] * 8 + [5] * 3 + [12]})


def _timeline():
    return pd.DataFrame({"in_play": [0] * 10 + [1] * 20 + [5] * 6 + [12] * 2 + [21]})


def _integrity(fracs=(0.0, 0.0005, 0.004, 0.03, 0.2), neg_median=False):
    rows = []
    for i, f in enumerate(fracs):
        rows.append({
            "run_id": f"run{i}",
            "max_neg_fraction": f,
            "median_transport_ms": -1.0 if (neg_median and i == 0) else 1.0,
            "median_schedlag_ms": 2.0,
            "median_output_ms": 0.0,
        })
    return pd.DataFrame(rows, columns=INTEGRITY_COLS)


class TestCondemnedAt:
    """The sensitivity curve must mirror clock_integrity.py's rule exactly."""

    def test_counts_runs_above_the_threshold(self):
        df = _integrity()
        assert condemned_at(df, 0.01) == 2      # 0.03 and 0.2
        assert condemned_at(df, 0.10) == 1      # 0.2 only

    def test_zero_threshold_condemns_every_inverted_run(self):
        assert condemned_at(_integrity(), 0.0) == 4   # everything but the clean run

    def test_a_negative_component_median_condemns_regardless_of_rate(self):
        """A run with zero inversions but a negative median is still unusable."""
        df = _integrity(neg_median=True)
        assert condemned_at(df, 0.5) == 1

    def test_threshold_is_monotone(self):
        df = _integrity()
        counts = [condemned_at(df, t) for t in (0.0, 0.001, 0.01, 0.1, 1.0)]
        assert counts == sorted(counts, reverse=True)


class TestPlots:
    def test_pipeline_draws_boxes_and_intervals(self, ax):
        plot_pipeline(ax)
        assert len(ax.patches) == 3, "producer, broker, consumer"
        assert not ax.axison

    def test_workload_marks_the_medians(self, axes_pair):
        plot_workload(axes_pair, _profiles())
        for a in axes_pair:
            assert a.get_legend() is not None
            assert len(a.patches) > 0

    def test_concurrency_uses_log_counts(self, axes_pair):
        plot_concurrency(axes_pair, _slots(), _timeline())
        assert all(a.get_yscale() == "log" for a in axes_pair)
        assert "12" in axes_pair[0].get_title()

    def test_integrity_shows_histogram_and_sensitivity(self, axes_pair):
        plot_integrity(axes_pair, _integrity())
        hist_ax, sens_ax = axes_pair
        assert hist_ax.get_xscale() == "log"
        assert len(sens_ax.get_lines()) >= 1
        assert "1 of 5 runs clean" in hist_ax.get_title()

    def test_model_diagram_draws_both_panels(self, axes_pair):
        """Panel (a) is a schematic; panel (b) must show the H1 overlap argument."""
        plot_model(axes_pair)
        mech_ax, h1_ax = axes_pair
        assert not mech_ax.axison, "the mechanism panel is a schematic, not a plot"
        assert len(h1_ax.get_lines()) >= 1, "the Delta density"
        # Two threshold markers: one small T_true, one large.
        assert len([ln for ln in h1_ax.get_lines() if ln.get_linestyle() == "--"]) == 2
        assert len(h1_ax.collections) == 2, "the two shaded inversion regions"

    def test_network_marks_the_batching_fix(self, ax):
        plot_network(ax)
        assert ax.get_yscale() == "log"
        assert len(ax.collections) == 1, "the batched-ack star"
        assert len(ax.texts) == 1, "the annotation"


class TestHelpers:
    def test_read_returns_none_for_a_missing_file(self, temp_dir):
        assert _read(temp_dir / "nope.csv") is None

    def test_read_loads_an_existing_file(self, temp_dir):
        p = temp_dir / "x.csv"
        _profiles(3).to_csv(p, index=False)
        assert len(_read(p)) == 3

    def test_save_writes_both_formats(self, temp_dir):
        fig, _ = plt.subplots()
        written = _save(fig, temp_dir / "f", "s")
        assert [p.name for p in written] == ["s.png", "s.pdf"]
        assert all(p.stat().st_size > 0 for p in written)


class TestMain:
    @staticmethod
    def _inputs(tmp):
        _profiles().to_csv(tmp / "profiles.csv", index=False)
        _slots().to_csv(tmp / "slots.csv", index=False)
        _timeline().to_csv(tmp / "timeline.csv", index=False)
        _integrity().to_csv(tmp / "integrity.csv", index=False)
        return ["--profiles-csv", str(tmp / "profiles.csv"),
                "--slots-csv", str(tmp / "slots.csv"),
                "--timeline-csv", str(tmp / "timeline.csv"),
                "--integrity-csv", str(tmp / "integrity.csv"),
                "--out", str(tmp / "figs")]

    def test_renders_every_figure(self, temp_dir, capsys):
        assert main(self._inputs(temp_dir)) == 0
        out = temp_dir / "figs"
        for stem in ("pipeline_schematic", "measurement_model", "workload_profile",
                     "kickoff_concurrency", "integrity_audit", "network_delay"):
            assert (out / f"{stem}.pdf").exists(), stem
        assert "skipped" not in capsys.readouterr().out

    def test_only_renders_one(self, temp_dir):
        args = self._inputs(temp_dir) + ["--only", "network_delay"]
        assert main(args) == 0
        out = temp_dir / "figs"
        assert (out / "network_delay.pdf").exists()
        assert not (out / "workload_profile.pdf").exists()

    def test_missing_input_is_skipped_and_reported(self, temp_dir, capsys):
        args = self._inputs(temp_dir)
        args[args.index("--profiles-csv") + 1] = str(temp_dir / "gone.csv")
        assert main(args) == 1
        captured = capsys.readouterr().out
        assert "skipped workload_profile: input missing" in captured
        assert (temp_dir / "figs" / "network_delay.pdf").exists(), "others still render"

    def test_font_scale_scales_numeric_rc_sizes(self, temp_dir, monkeypatch):
        """In force while the figures are drawn, and gone once the call returns.

        This used to assert that the scaling was still set afterwards, which passed only
        because main never restored it. Five of the six keys then stayed scaled for the rest
        of the process: every later figure was drawn half again too large, including the ones
        other tests build, and including the ones the layout gate renders and measures.
        """
        import matplotlib.pyplot as plt
        import make_paper_figures as mpf

        keys = ("font.size", "axes.titlesize", "axes.labelsize",
                "xtick.labelsize", "ytick.labelsize", "legend.fontsize")
        before = {k: plt.rcParams[k] for k in keys}

        seen = {}
        real_save = mpf._save

        def spy(fig, out_dir, stem, **kw):
            seen[stem] = float(plt.rcParams["font.size"])
            return real_save(fig, out_dir, stem, **kw)

        monkeypatch.setattr(mpf, "_save", spy)
        args = self._inputs(temp_dir) + ["--only", "measurement_model",
                                         "--font-scale", "1.5"]
        assert main(args) == 0
        assert (temp_dir / "figs" / "measurement_model.pdf").exists()

        assert seen["measurement_model"] == pytest.approx(float(before["font.size"]) * 1.5), \
            "the scaling was not in force while the figure was drawn"
        after = {k: plt.rcParams[k] for k in keys}
        assert after == before, \
            "main left rcParams scaled: %s" % {k: (before[k], after[k])
                                               for k in keys if after[k] != before[k]}


class TestTheSliceFallback:

    @staticmethod
    def _mpf():
        import make_paper_figures
        return make_paper_figures

    def test_an_unavailable_kernel_constant_falls_back_to_the_documented_default(self,
                                                                                 monkeypatch):
        """The scheduler slice is read from the campaign's own measurements, and a reader
        rebuilding the figures from the archive may not have the file it is derived from.

        Falling back keeps the figure buildable; falling back *silently to a different
        number* would not, which is why the default is a named constant the manuscript also
        carries rather than a literal at the call site.
        """
        import kernel_constants
        monkeypatch.setattr(kernel_constants, "constants",
                            lambda *a, **kw: (_ for _ in ()).throw(OSError("no artefact")))
        mpf = self._mpf()
        assert mpf._base_slice_ms() == mpf.DEFAULT_BASE_SLICE_MS

    def test_a_constants_file_missing_the_key_falls_back_too(self, monkeypatch):
        import kernel_constants
        monkeypatch.setattr(kernel_constants, "constants", lambda *a, **kw: {})
        mpf = self._mpf()
        assert mpf._base_slice_ms() == mpf.DEFAULT_BASE_SLICE_MS

    def test_a_real_constants_file_is_preferred_over_the_default(self, monkeypatch):
        """The negative controls above only mean something beside the case that works."""
        import kernel_constants
        monkeypatch.setattr(kernel_constants, "constants",
                            lambda *a, **kw: {"base_slice_ms": 7.5})
        assert self._mpf()._base_slice_ms() == 7.5
