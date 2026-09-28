"""Tests for scripts/make_law_figures.py - target 100% branch coverage.

The figures' job is to leave nothing out and to say why each marked run is marked, so the tests
guard exactly that: every run a panel should hold is drawn, a run out of every judge is drawn as
a cross or a plus in its own colour and never as a counted point, every warning gets its ring,
and a value keeps one colour across a figure.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import make_law_figures as mlf  # noqa: E402


def _run(name, trip, rate, marks=(), block="A1", pair="matched", backend="kafka",
         slice_ms=3.0, folder="a1_x", **extra):
    run = {"run": name, "block": block, "pair": pair, "backend": backend, "folder": folder,
           "slice_ms": slice_ms, "tick_ms": 1.0, "load_pct": 75.0, "cpus": None,
           "language": "python", "priority": False, "trip_median_ms": trip, "rate": rate,
           "marks": list(marks)}
    run.update(extra)
    return run


def _world():
    return [
        _run("counted", 1.0, 0.02),
        _run("other slice", 1.2, 0.03, slice_ms=1.5),
        _run("repeated", 1.1, 0.021, ["repeated"]),
        _run("stopped", 1.3, 0.022, ["stopped"]),
        _run("false start", 1.4, 0.023, ["false start", "repeated"]),
        _run("paused", 1.5, 0.018, ["paused"]),
        _run("flagged", 1.6, 0.017, ["flagged"]),
        _run("far", 1.7, 0.016, ["far"]),
        _run("traced", 1.8, 0.015, ["traced"]),
        _run("unjudged", None, None, ["unjudged"]),
        _run("elsewhere", 1.0, 0.02, pair="arm"),
        _run("other folder", 1.0, 0.02, folder="a1_y"),
    ]


class TestWhatAPanelColoursBy:

    def test_each_variable_is_read_off_the_run(self):
        run = _run("r", 1.0, 0.1, cpus=4.0, language="java", priority=True)
        assert mlf.variable(run, "slice") == 3.0 and mlf.variable(run, "cpus") == 4.0
        assert mlf.variable(run, "client") == "Java, go-first"
        assert mlf.variable(run, "priority") == "go-first"
        assert mlf.variable(_run("r", 1.0, 0.1), "priority") == "ordinary"
        assert mlf.variable(_run("r", 1.0, 0.1), "client") == "Python"

    def test_the_labels_carry_their_units(self):
        assert mlf.value_label(3.0, "slice") == "3 ms slice"
        assert mlf.value_label(75.0, "load") == "75% load"
        assert mlf.value_label(10.0, "tick") == "10 ms tick"
        assert mlf.value_label(2.0, "cpus") == "2 CPUs"
        assert mlf.value_label("Java", "client") == "Java"

    def test_colours_follow_the_sorted_values(self):
        found = mlf.colours([4.5, 1.5, 3.0, 1.5])
        assert list(found) == [1.5, 3.0, 4.5] and found[1.5] == mlf.PALETTE[0]


class TestAPanel:

    def test_it_draws_every_run_it_should_and_nothing_else(self):
        spec = {"block": "A1", "pair": "matched", "backend": "kafka", "by": "slice",
                "folders": ("a1_x",), "title": "(a) test"}
        chosen = [r["run"] for r in mlf.select(_world(), spec)]
        assert "elsewhere" not in chosen and "other folder" not in chosen
        assert "unjudged" not in chosen, "a run with no trip cannot be drawn"
        assert len(chosen) == 9

    def test_a_run_out_of_every_judge_is_a_cross_or_a_plus_never_a_point(self):
        fig, ax = plt.subplots()
        spec = {"block": "A1", "pair": "matched", "backend": "kafka", "by": "slice",
                "folders": ("a1_x",), "title": "(a) test"}
        drawn = mlf.panel(ax, _world(), spec)
        points = [c for c in ax.collections if c.get_label() in ("3 ms slice", "1.5 ms slice")]
        plotted = sorted(tuple(p) for c in points for p in c.get_offsets())
        assert (1.1, 0.021) not in plotted and (1.4, 0.023) not in plotted
        assert (1.0, 0.02) in plotted and (1.2, 0.03) in plotted
        assert drawn["runs"] == 9 and drawn["repeated"] == 2 and drawn["false start"] == 1
        assert drawn["paused"] == drawn["flagged"] == drawn["far"] == drawn["traced"] == 1
        crosses = [c for c in ax.collections if c.get_offsets().shape[0] and
                   c.get_label().startswith("_") and c.get_sizes()[0] == 36]
        offsets = sorted(tuple(p) for c in crosses for p in c.get_offsets())
        assert offsets == [(1.1, 0.021), (1.3, 0.022), (1.4, 0.023)], "one mark each, not two"
        plt.close(fig)

    def test_a_figure_palette_is_kept_to_the_values_a_panel_holds(self):
        fig, ax = plt.subplots()
        spec = {"block": "A1", "pair": "arm", "backend": "kafka", "by": "slice",
                "title": "(b) test"}
        mlf.panel(ax, _world(), spec, palette={1.5: "#000001", 3.0: "#000002"})
        labels = [t.get_text() for t in ax.get_legend().get_texts()]
        assert labels == ["3 ms slice"], "the Arm run is at 3 ms only"
        plt.close(fig)


class TestAFigure:

    SPEC = {"rows": 1, "cols": 3, "height": 3.0, "rings": ("paused", "traced"),
            "panels": [{"block": "A1", "pair": "matched", "backend": "kafka", "by": "slice",
                        "folders": ("a1_x",), "title": "(a) one"},
                       {"block": "A1", "pair": "arm", "backend": "kafka", "by": "slice",
                        "title": "(b) two"}]}

    def test_a_value_has_one_colour_in_every_panel_and_spare_slots_are_hidden(self):
        fig, drawn = mlf.figure(_world(), "test", self.SPEC)
        axes = fig.get_axes()
        colour = dict((ax.get_title(), [c for c in ax.collections
                                         if c.get_label() == "3 ms slice"][0].get_facecolor()[0][:3])
                      for ax in axes if ax.get_visible())
        assert list(colour["(a) one"]) == pytest.approx(list(colour["(b) two"]))
        assert not axes[2].get_visible() and len(drawn) == 2
        legend = fig.legends[0]
        texts = [t.get_text() for t in legend.get_texts()]
        assert texts[0].startswith("cross: not counted") and texts[-1].startswith("ringed gray")
        plt.close(fig)


class TestMain:

    def test_it_writes_each_figure_or_only_the_one_asked_for(self, temp_dir, capsys,
                                                             monkeypatch):
        monkeypatch.setattr(mlf.law_runs, "load", _world)
        monkeypatch.setattr(mlf, "FIGURES", {"law_test": TestAFigure.SPEC,
                                             "law_other": TestAFigure.SPEC})
        out = temp_dir / "figs"
        assert mlf.main(["--out", str(out), "--only", "law_test"]) == 0
        assert (out / "law_test.pdf").exists() and not (out / "law_other.pdf").exists()
        assert mlf.main(["--out", str(out)]) == 0
        assert (out / "law_other.png").exists()
        assert "OK wrote" in capsys.readouterr().out
