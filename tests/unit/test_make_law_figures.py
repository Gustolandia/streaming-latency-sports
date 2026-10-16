"""Tests for scripts/make_law_figures.py - target 100% branch coverage.

The figures' job is to leave nothing out and to say why each marked run is marked, so the tests
guard exactly that: every run a panel should hold is drawn, a run out of every judge is drawn as
a cross or a plus in its own colour and never as a counted point, every warning gets its ring,
and a value keeps one colour across a figure.
"""
import json
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
        assert mlf.variable(run, "client") == "Java, real-time"
        assert mlf.variable(run, "priority") == "real-time"
        assert mlf.variable(_run("r", 1.0, 0.1), "priority") == "normal"
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

    def test_a_panel_can_be_given_headroom_over_its_runs(self):
        """15 Oct 2026: figure_collisions.data_under_legends found two of L8's Arm64 runs
        under that panel's legend; its spec raises the panel's top over them."""
        spec = {"block": "A1", "pair": "arm", "backend": "kafka", "by": "slice",
                "title": "(b) test", "ylim_top": 0.25}
        fig, ax = plt.subplots()
        try:
            mlf.panel(ax, _world(), spec)
            assert ax.get_ylim()[1] == pytest.approx(0.25)
        finally:
            plt.close(fig)
        assert [p.get("ylim_top") for p in mlf.FIGURES["law_load"]["panels"]].count(0.25) == 1

    def test_redis_is_red_in_the_halfway_figure(self):
        """The paper's and the supplement's red, not the orange this figure had."""
        assert mlf.BROKERS["redis"][1] == "#d62728" and mlf.BROKERS["kafka"][1] == "#1f77b4"


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


class TestTheMarkLegend:
    """The legend speaks the manuscript's names, and the panels stand clear of it."""

    def test_it_uses_the_manuscripts_names(self):
        """3 Oct (A10): the plan's "got-it" is the publish latency, a duration is the end-to-end
        latency, never the bare "delivery", and the brake is the stopping rule."""
        fig, _ = mlf.figure(_world(), "test", dict(TestAFigure.SPEC, rings=tuple(mlf.RINGS)))
        said = [" ".join(t.get_text().split()) for t in fig.legends[0].get_texts()]
        said += [ax.get_xlabel() for ax in fig.get_axes() if ax.get_visible()]
        plt.close(fig)
        assert "diamond: the stopping rule would have stopped it" in said
        assert ("square: end-to-end latency, publish latency or held delay far from its "
                "fellows'") in said
        assert "End-to-end latency, the run's median (ms)" in said
        assert not [s for s in said if "got-it" in s or s.startswith("Delivery,")]

    @pytest.mark.parametrize("rings", [("paused", "flagged", "far"), tuple(mlf.RINGS)],
                             ids=["three lines", "four lines"])
    def test_the_panels_stand_clear_of_the_legend_however_tall_it_is(self, rings):
        """Three lines fit the fixed floor the panels had. L9's six marks, with the square's
        entry on two lines, make four, and on that floor the bottom panels' axis labels came
        down to 3 pt above the legend."""
        fig, _ = mlf.figure(_world(), "test", dict(TestAFigure.SPEC, rings=rings))
        fig.canvas.draw()      # an axis label takes its place from the layout only when drawn
        renderer = fig.canvas.get_renderer()
        top = fig.legends[0].get_window_extent(renderer).y1
        lowest = min(ax.xaxis.label.get_window_extent(renderer).y0 for ax in fig.get_axes()
                     if ax.get_visible())
        plt.close(fig)
        assert (lowest - top) / fig.dpi > 0.1, "an axis label sits on the legend"


REPO = Path(__file__).parent.parent.parent
JUDGED = REPO / "docs" / "results" / "law" / "judged-27-sep" / "all"


def _judged(name):
    return json.loads((JUDGED / (name + ".json")).read_text(encoding="utf-8"))["by_part"]


@pytest.fixture(scope="module")
def halfway():
    """Fig. S3 drawn once from the committed registry and judged records (about seven
    seconds: the judge's own function reads every slice's curve again)."""
    import law_runs
    fig, found = mlf.halfway_figure(law_runs.load(), judged_dir=str(JUDGED),
                                    quality_csv=str(JUDGED.parent / "quality_by_campaign.csv"))
    yield fig, found
    plt.close(fig)


def _panel(fig, title):
    (ax,) = [a for a in fig.get_axes() if a.get_title() == title]
    return ax


class TestTheHalfwayFigure:
    """Fig. S3 of the journal supplement since 15 Oct 2026: for each pair and broker, where each
    slice's fall is halfway down, free and fitted, against the band [s, s + h]. The referees
    could not see what the slice does among the runs' overlapping colours."""

    def test_every_judged_point_is_drawn_where_the_judge_put_it(self, halfway):
        fig, _ = halfway
        for spec in mlf.HALFWAY_PANELS:
            ax = _panel(fig, spec["title"])
            drawn = [(float(x), float(y)) for line in ax.get_lines()
                     if line.get_linestyle() == "None"
                     for x, y in zip(line.get_xdata(), line.get_ydata())]
            for backend, part in _judged(spec["judged"]).items():
                for summary, said in part["by_summary"].items():
                    for s, ms in said["halfway_ms"].items():
                        assert any(x == float(s) and abs(y - ms) < 1e-9 for x, y in drawn), \
                            (spec["title"], backend, summary, s)

    def test_each_line_has_the_judged_slope(self, halfway):
        """The judge's slope is a straight line through the halfway points; the line drawn
        through them is that line, so its slope is the judged one to the last digit."""
        fig, _ = halfway
        for spec in mlf.HALFWAY_PANELS:
            ax = _panel(fig, spec["title"])
            lines = [l for l in ax.get_lines() if l.get_linestyle() != "None"
                     and len(l.get_xdata()) == 2 and l.get_xdata()[0] != l.get_xdata()[1]
                     and matplotlib.colors.to_hex(l.get_color()) != "#666666"]
            slopes = sorted((l.get_ydata()[1] - l.get_ydata()[0])
                            / (l.get_xdata()[1] - l.get_xdata()[0]) for l in lines)
            judged = sorted(said["value"] for part in _judged(spec["judged"]).values()
                            for said in part["by_summary"].values())
            assert slopes == pytest.approx(judged, abs=1e-9), (spec["title"], slopes, judged)

    def test_the_arm_pairs_kafka_slice_out_of_reach_is_grey_and_in_the_slope(self, halfway):
        """Kafka's 1.5 ms slice on the Arm pair is out of reach of P9's band test, and the
        judged slope runs through it all the same: drawn without it, the line would not have
        the judged slope."""
        fig, found = halfway
        kafka = found["(b) L4, Arm64"]["kafka"]
        for summary in ("free", "fitted"):
            assert 1.5 in kafka[summary]["halfway"] and 1.5 not in kafka[summary]["in_reach"]
        grey = [l for l in _panel(fig, "(b) L4, Arm64").get_lines()
                if l.get_linestyle() == "None" and len(l.get_xdata())
                and matplotlib.colors.to_hex(l.get_markeredgecolor()) == mlf.OUT_OF_REACH]
        assert sorted(float(x) for l in grey for x in l.get_xdata()) == [1.5, 1.5]
        assert not [l for l in _panel(fig, "(a) L1, first x86").get_lines()
                    if l.get_linestyle() == "None" and len(l.get_xdata())
                    and matplotlib.colors.to_hex(l.get_markeredgecolor()) == mlf.OUT_OF_REACH]

    def test_the_band_runs_from_the_slice_to_a_tick_past_it_over_the_1_to_1_line(self,
                                                                                 halfway):
        fig, _ = halfway
        for spec in mlf.HALFWAY_PANELS:
            ax = _panel(fig, spec["title"])
            (band,) = ax.collections
            vertices = band.get_paths()[0].vertices
            lo, hi = mlf.HALFWAY_SLICES_MS
            for x, y in vertices:
                assert y == pytest.approx(x) or y == pytest.approx(x + mlf.TICK_MS), (x, y)
            (one,) = [l for l in ax.get_lines()
                      if matplotlib.colors.to_hex(l.get_color()) == "#666666"]
            assert list(one.get_xdata()) == list(one.get_ydata()) == [lo, hi]

    def test_each_panels_legend_gives_the_judged_slopes(self, halfway):
        fig, _ = halfway
        for spec in mlf.HALFWAY_PANELS:
            legend = _panel(fig, spec["title"]).get_legend()
            said = [t.get_text() for t in legend.get_texts()]
            assert legend.get_title().get_text() == "slope against $s$"
            for backend, part in _judged(spec["judged"]).items():
                for summary in ("free", "fitted"):
                    want = "%s, %s %.3f" % (mlf.BROKERS[backend][0], summary,
                                            part["by_summary"][summary]["value"])
                    assert want in said, want

    def test_a_judged_record_that_disagrees_is_refused(self, temp_dir):
        """The figure draws what the judge judged or nothing: a halfway point or a slope that
        the registry does not give back is an error, not a quiet second opinion."""
        import law_runs
        runs = law_runs.load()
        campaigns = mlf.judged_campaigns(str(JUDGED.parent / "quality_by_campaign.csv"))
        spec = mlf.HALFWAY_PANELS[0]
        for change, match in (("halfway", "is not the judged one"), ("value", "not the judged")):
            record = json.loads((JUDGED / "p1_a1.json").read_text(encoding="utf-8"))
            said = record["by_part"]["redis"]["by_summary"]["free"]
            if change == "halfway":
                said["halfway_ms"]["3.0"] += 0.01
            else:
                said["value"] += 0.01
            (temp_dir / "p1_a1.json").write_text(json.dumps(record), encoding="utf-8")
            with pytest.raises(ValueError, match=match):
                mlf.halfway_readings(runs, spec, judged_dir=str(temp_dir), campaigns=campaigns)


class TestMain:

    def test_it_writes_each_figure_or_only_the_one_asked_for(self, temp_dir, capsys,
                                                             monkeypatch):
        monkeypatch.setattr(mlf.law_runs, "load", _world)
        monkeypatch.setattr(mlf, "FIGURES", {"law_test": TestAFigure.SPEC,
                                             "law_other": TestAFigure.SPEC})
        drawn = []

        def extra(runs):
            drawn.append(len(runs))
            return mlf.figure(runs, "law_extra", TestAFigure.SPEC)
        monkeypatch.setattr(mlf, "EXTRA", {"law_extra": extra})
        out = temp_dir / "figs"
        assert mlf.main(["--out", str(out), "--only", "law_test"]) == 0
        assert (out / "law_test.pdf").exists() and not (out / "law_other.pdf").exists()
        assert not drawn, "an extra figure is built only when asked for or with every figure"
        assert mlf.main(["--out", str(out)]) == 0
        assert (out / "law_other.png").exists() and (out / "law_extra.pdf").exists()
        assert drawn == [len(_world())]
        assert "OK wrote" in capsys.readouterr().out

    def test_the_halfway_figure_is_built_from_the_committed_records(self, temp_dir, capsys):
        out = temp_dir / "figs"
        assert mlf.main(["--out", str(out), "--only", mlf.HALFWAY_STEM]) == 0
        assert (out / ("%s.pdf" % mlf.HALFWAY_STEM)).exists()
        assert not (out / "law_slice.pdf").exists()
