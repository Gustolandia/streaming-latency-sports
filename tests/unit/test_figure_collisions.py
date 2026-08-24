"""Tests for scripts/figure_collisions.py - target >=95% branch coverage.

The module exists because three consecutive referee rounds found a figure defect that every
automated check passed: a label struck through by a rule, two tick labels printed in one
place, a curve drawn through an annotation, an arrow through a bar's percentage, a marker
sliced in half by a spine. All of them are geometry, and every gate the repository had asks
about content -- which font, which glyph, which family.

So these tests are built the way the defects arrived: a figure is constructed with the defect
in it and the check has to name it, then the same figure without it and the check has to stay
quiet. A detector that reports nothing is indistinguishable from a clean figure unless the
positive case is pinned too, and the two false-alarm shapes the referee warned about --
a label flanking a rule, a tick that exists but is never drawn -- are pinned as passing.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import figure_collisions as fc  # noqa: E402


@pytest.fixture(autouse=True)
def _pinned_rc():
    """Draw these figures under known metrics.

    Another module in this repository sets font.size and a default figure size at import
    time, so a synthetic figure built here comes out at whatever size the last importer
    chose, and a check about geometry then measures a different picture in a full suite run
    than it does alone. The gate was written because output depended on things nobody chose;
    its own tests should not.
    """
    with matplotlib.rc_context(matplotlib.rcParamsDefault):
        yield
    plt.close("all")


def _blank(figsize=(4, 3)):
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    return fig, ax


class TestTextStruckByInk:

    def test_a_rule_through_a_label_is_found(self):
        fig, ax = _blank()
        ax.axhline(0.5, color="black", lw=1.2)
        ax.text(0.5, 0.5, "struck through", ha="center", va="center", fontsize=9)
        found = fc.text_struck_by_ink(fig)
        assert [d["text"] for d in found] == ["struck through"]
        assert found[0]["fraction"] > fc.MAX_INK_FRACTION

    def test_the_same_label_clear_of_the_rule_is_not(self):
        fig, ax = _blank()
        ax.axhline(0.5, color="black", lw=1.2)
        ax.text(0.5, 0.8, "clear of it", ha="center", va="center", fontsize=9)
        assert fc.text_struck_by_ink(fig) == []

    def test_a_label_flanking_a_rule_is_not_struck(self):
        """The design the referee warned against over-correcting: labels either side of a
        rule, where the rule is inside both boxes and through neither set of glyphs."""
        fig, ax = _blank()
        ax.axhline(0.5, color="black", lw=1.0)
        ax.text(0.9, 0.505, "above", ha="right", va="bottom", fontsize=8)
        ax.text(0.9, 0.495, "below", ha="right", va="top", fontsize=8)
        assert fc.text_struck_by_ink(fig) == []

    def test_a_pale_background_fill_is_not_ink(self):
        """A label over a shaded region is legible; a label over a curve is not."""
        fig, ax = _blank()
        ax.fill_between([0, 1], [0, 0], [1, 1], color="#1f77b4", alpha=0.06)
        ax.text(0.5, 0.5, "on a tint", ha="center", va="center", fontsize=9)
        assert fc.text_struck_by_ink(fig) == []

    def test_an_annotations_own_arrow_does_not_count_against_it(self):
        """Annotation.get_window_extent returns the union of the text and its arrow, so
        reading that box makes every annotated label report itself."""
        fig, ax = _blank()
        ax.annotate("labelled", xy=(0.2, 0.2), xytext=(0.6, 0.6), fontsize=9,
                    arrowprops=dict(arrowstyle="->", lw=0.8))
        assert fc.text_struck_by_ink(fig) == []

    def test_an_arrow_through_a_different_label_is_found(self):
        fig, ax = _blank()
        ax.text(0.5, 0.5, "in the way", ha="center", va="center", fontsize=9)
        ax.annotate("source", xy=(0.5, 0.15), xytext=(0.5, 0.85), fontsize=8, ha="center",
                    arrowprops=dict(arrowstyle="->", lw=1.2))
        assert "in the way" in [d["text"] for d in fc.text_struck_by_ink(fig)]

    def test_an_opaque_backing_box_counts_as_the_repair_it_is(self):
        fig, ax = _blank()
        ax.axhline(0.5, color="black", lw=1.2)
        ax.text(0.5, 0.5, "masked", ha="center", va="center", fontsize=9,
                bbox=dict(facecolor="white", edgecolor="none", pad=1.5))
        assert fc.text_struck_by_ink(fig) == []

    def test_a_figure_with_no_text_is_handled(self):
        fig, ax = plt.subplots(figsize=(2, 2))
        ax.set_xticks([])
        ax.set_yticks([])
        ax.plot([0, 1], [0, 1])
        assert fc.text_struck_by_ink(fig) == []

    def test_the_colour_of_every_label_is_restored(self):
        fig, ax = _blank()
        ax.text(0.5, 0.5, "coloured", color="#b22222", fontsize=9)
        # Drawn first: a tick label carries no string until the axis has been rendered once,
        # so a list taken before the draw is a different set of objects from one taken after.
        fig.canvas.draw()
        before = {id(t): t.get_color() for t in fc._visible_texts(fig)}
        assert "#b22222" in before.values()
        fc.text_struck_by_ink(fig)
        assert {id(t): t.get_color() for t in fc._visible_texts(fig)} == before


class TestTextsOverlapping:

    def test_two_labels_in_one_place_are_found(self):
        """Round 13's defect: a minor-tick formatter printing under a major tick label."""
        fig, ax = _blank()
        ax.text(0.5, 0.5, "AAAAAA", ha="center", va="center", fontsize=9)
        ax.text(0.5, 0.5, "BBBBBB", ha="center", va="center", fontsize=9)
        found = fc.texts_overlapping(fig)
        assert len(found) == 1
        assert {found[0]["a"], found[0]["b"]} == {"AAAAAA", "BBBBBB"}
        assert found[0]["overlap"] > 0.9

    def test_adjacent_labels_are_not_overlapping(self):
        fig, ax = _blank()
        ax.text(0.2, 0.5, "left", ha="center", va="center", fontsize=9)
        ax.text(0.8, 0.5, "right", ha="center", va="center", fontsize=9)
        assert fc.texts_overlapping(fig) == []

    def test_a_single_line_label_inside_a_two_line_one_is_found(self):
        fig, ax = _blank()
        ax.text(0.5, 0.5, "first line\nsecond line", ha="center", va="center", fontsize=9)
        ax.text(0.5, 0.5, "inside", ha="center", va="center", fontsize=8)
        assert fc.texts_overlapping(fig)

    def test_ticks_outside_the_view_do_not_count(self):
        """A locator keeps a Text for every candidate tick; several stack up off the end of
        an axis, and asking the page whether they were drawn gets the wrong answer because
        their boxes sit on labels that were."""
        fig, ax = _blank()
        ax.set_xticks([0.0, 0.25, 0.5, 0.75, 1.0, 5.0, 7.0])
        ax.set_xlim(0, 1)
        assert fc.texts_overlapping(fig) == []


class TestMarkersClippedByAxes:

    def test_a_point_on_the_limit_is_found(self):
        fig, ax = _blank()
        ax.plot([0.5], [0.0], "o", ms=6)
        found = fc.markers_clipped_by_axes(fig)
        assert len(found) == 1
        assert found[0]["point"] == (0.5, 0.0)
        assert found[0]["overhang_px"] > 0

    def test_a_point_inside_the_limits_is_not(self):
        fig, ax = _blank()
        ax.plot([0.5], [0.5], "o", ms=6)
        assert fc.markers_clipped_by_axes(fig) == []

    def test_scatter_collections_are_checked_too(self):
        fig, ax = _blank()
        ax.scatter([0.0], [0.5], s=80)
        assert fc.markers_clipped_by_axes(fig)

    def test_a_line_without_markers_is_ignored(self):
        fig, ax = _blank()
        ax.plot([0, 1], [0, 1], lw=1.5)
        assert fc.markers_clipped_by_axes(fig) == []

    def test_an_empty_legend_proxy_is_ignored(self):
        fig, ax = _blank()
        ax.plot([], [], "o", ms=6, label="proxy")
        assert fc.markers_clipped_by_axes(fig) == []

    def test_error_bars_do_not_crash_the_check(self):
        """errorbar makes LineCollections, which have no marker sizes."""
        fig, ax = _blank()
        ax.errorbar([0.5], [0.5], yerr=[0.1], fmt="o", ms=4)
        assert fc.markers_clipped_by_axes(fig) == []


class TestCheck:

    def test_a_clean_figure_raises_nothing(self):
        fig, ax = _blank()
        ax.text(0.5, 0.8, "fine", ha="center", fontsize=9)
        ax.plot([0.5], [0.5], "o", ms=5)
        fc.check(fig, "clean")

    def test_a_struck_label_raises_with_its_name(self):
        fig, ax = _blank()
        ax.axhline(0.5, color="black", lw=1.2)
        ax.text(0.5, 0.5, "run over", ha="center", va="center", fontsize=9)
        with pytest.raises(fc.FigureCollision) as exc:
            fc.check(fig, "struck_figure")
        assert "struck_figure" in str(exc.value)
        assert "run over" in str(exc.value)

    def test_overlapping_labels_raise(self):
        fig, ax = _blank()
        ax.text(0.5, 0.5, "XXXXXX", ha="center", va="center", fontsize=9)
        ax.text(0.5, 0.5, "YYYYYY", ha="center", va="center", fontsize=9)
        with pytest.raises(fc.FigureCollision, match="printed over each other"):
            fc.check(fig, "overlap_figure")

    def test_a_clipped_marker_raises(self):
        fig, ax = _blank()
        ax.plot([0.0], [0.5], "o", ms=7)
        with pytest.raises(fc.FigureCollision, match="clipped by axes"):
            fc.check(fig, "clipped_figure")

    def test_the_stem_defaults_to_a_readable_name(self):
        fig, ax = _blank()
        ax.plot([0.0], [0.5], "o", ms=7)
        with pytest.raises(fc.FigureCollision, match="^figure:"):
            fc.check(fig)

    def test_report_returns_all_three_checks(self):
        fig, ax = _blank()
        assert set(fc.report(fig)) == {"struck", "overlapping", "clipped"}


class TestEveryShippedFigure:
    """The gate runs inside _save, so building the figures is the assertion."""

    def test_result_figures_build_without_a_collision(self, tmp_path):
        import make_result_figures as mrf
        for build in (mrf.build_deletion, mrf.build_spectrum, mrf.build_grid,
                      mrf.build_mechanism, mrf.build_ttrue, mrf.build_payload):
            build(tmp_path)

    def test_paper_figures_build_without_a_collision(self, tmp_path):
        import make_paper_figures as mpf
        mpf.main(["--out", str(tmp_path)])


class TestTheDefensiveEdges:
    """The guards that keep one odd figure from taking the whole build down.

    These are cheap to write and worth having: a check wired into every figure's save path
    fails the build when it throws, so an unhandled edge here costs more than the defect it
    was looking for.
    """

    def test_a_label_off_the_canvas_is_skipped(self):
        fig, ax = _blank()
        ax.text(-40.0, -40.0, "far outside", fontsize=9)
        assert fc.text_struck_by_ink(fig) == []

    def test_a_zero_area_label_does_not_divide_by_zero(self):
        fig, ax = _blank()
        ax.text(0.5, 0.5, "normal", ha="center", fontsize=9)
        ax.text(0.5, 0.5, "tiny", ha="center", fontsize=0.0)
        fc.texts_overlapping(fig)   # must not raise

    def test_an_invisible_axes_is_skipped(self):
        fig, (ax, hidden) = plt.subplots(1, 2, figsize=(5, 2))
        hidden.plot([0.0], [0.0], "o", ms=8)
        hidden.set_visible(False)
        assert fc.markers_clipped_by_axes(fig) == []

    def test_an_invisible_collection_is_skipped(self):
        fig, ax = _blank()
        coll = ax.scatter([0.0], [0.5], s=90)
        coll.set_visible(False)
        assert fc.markers_clipped_by_axes(fig) == []

    def test_a_non_finite_point_is_skipped(self):
        import numpy as np
        fig, ax = _blank()
        ax.plot([np.nan], [np.nan], "o", ms=8)
        assert fc.markers_clipped_by_axes(fig) == []

    def test_two_kinds_of_collision_are_both_reported(self):
        fig, ax = _blank()
        ax.text(0.5, 0.5, "PPPPPP", ha="center", va="center", fontsize=9)
        ax.text(0.5, 0.5, "QQQQQQ", ha="center", va="center", fontsize=9)
        ax.plot([0.0], [0.5], "o", ms=7)
        with pytest.raises(fc.FigureCollision) as exc:
            fc.check(fig, "both")
        message = str(exc.value)
        assert "printed over each other" in message
        assert "clipped by axes" in message
