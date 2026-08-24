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

    def test_report_returns_every_check(self):
        fig, ax = _blank()
        assert set(fc.report(fig)) == {"struck", "overlapping", "clipped", "crossed", "erased"}


class TestReferenceLinesThroughText:
    """The check written after a diagonal struck the same label through two attempted moves.

    `text_struck_by_ink` insets a label to its core on purpose, so that a gridline grazing a
    descender does not fail a figure. One glyph of sixteen is a few per cent of that core, and
    a reader sees it immediately -- so a long straight line gets a question of its own, asked
    against the label's full extent.
    """

    def test_a_diagonal_through_a_label_is_found(self):
        fig, ax = _blank()
        ax.plot([0, 1], [0, 1], ls="--", color="black", lw=1.0)
        ax.text(0.5, 0.5, "on the line", ha="center", va="center", fontsize=9)
        found = fc.reference_lines_through_text(fig)
        assert [d["text"] for d in found] == ["on the line"]
        assert found[0]["crossing_px"] > 0
        assert found[0]["line_px"] > 0

    def test_a_label_clear_of_the_line_is_not(self):
        fig, ax = _blank()
        ax.plot([0, 1], [0, 1], ls="--", color="black", lw=1.0)
        ax.text(0.2, 0.8, "above it", ha="center", va="center", fontsize=9)
        assert fc.reference_lines_through_text(fig) == []

    def test_only_the_terminal_glyph_need_be_struck(self):
        """The whole reason for the check: the ink test's inset does not reach the last letter."""
        fig, ax = _blank()
        ax.plot([0, 1], [0, 1], ls="--", color="black", lw=1.0)
        # Left-aligned so the label runs at the diagonal and meets it near its right edge.
        ax.text(0.30, 0.56, "a continuum would land here", ha="left", va="center", fontsize=9)
        assert [d["text"] for d in fc.reference_lines_through_text(fig)] \
            == ["a continuum would land here"]

    def test_a_short_line_is_not_a_reference_line(self):
        """Error bars, caps and whiskers cross labels all the time and are not rules."""
        fig, ax = _blank()
        ax.plot([0.48, 0.52], [0.5, 0.5], ls="-", color="black", lw=1.0)
        ax.text(0.5, 0.5, "beside a whisker", ha="center", va="center", fontsize=9)
        assert fc.reference_lines_through_text(fig) == []

    def test_a_label_on_its_own_patch_is_exempt(self):
        """An opaque patch interrupts the line, which is what the patch is for."""
        fig, ax = _blank()
        ax.plot([0, 1], [0, 1], ls="--", color="black", lw=1.0)
        ax.text(0.5, 0.5, "boxed", ha="center", va="center", fontsize=9,
                bbox=dict(facecolor="white", edgecolor="none"))
        assert fc.reference_lines_through_text(fig) == []

    def test_a_marker_only_series_is_not_a_line(self):
        fig, ax = _blank()
        ax.plot([0, 1], [0, 1], ls="none", marker="o", color="black")
        ax.text(0.5, 0.5, "scatter only", ha="center", va="center", fontsize=9)
        assert fc.reference_lines_through_text(fig) == []

    def test_an_invisible_line_is_not_drawn(self):
        fig, ax = _blank()
        line, = ax.plot([0, 1], [0, 1], ls="--", color="black")
        line.set_visible(False)
        ax.text(0.5, 0.5, "hidden line", ha="center", va="center", fontsize=9)
        assert fc.reference_lines_through_text(fig) == []

    def test_an_empty_series_has_no_segments(self):
        """Legend proxies are drawn with no data, and `zip` over one point yields nothing."""
        fig, ax = _blank()
        ax.plot([], [], ls="--", color="black", label="proxy")
        ax.plot([0.5], [0.5], ls="--", color="black")
        ax.text(0.5, 0.5, "one point", ha="center", va="center", fontsize=9)
        assert fc.reference_lines_through_text(fig) == []

    def test_a_non_finite_point_is_dropped(self):
        fig, ax = _blank()
        ax.plot([0, float("nan"), 1], [0, float("nan"), 1], ls="--", color="black")
        ax.text(0.5, 0.5, "gap in the line", ha="center", va="center", fontsize=9)
        # The surviving endpoints still span the axes, so the strike is still found.
        assert [d["text"] for d in fc.reference_lines_through_text(fig)] == ["gap in the line"]

    def test_an_axes_with_no_labels_is_skipped(self):
        fig, ax = _blank()
        ax.plot([0, 1], [0, 1], ls="--", color="black")
        assert fc.reference_lines_through_text(fig) == []

    def test_an_invisible_axes_is_skipped(self):
        fig, ax = _blank()
        ax.plot([0, 1], [0, 1], ls="--", color="black")
        ax.text(0.5, 0.5, "hidden axes", ha="center", va="center", fontsize=9)
        ax.set_visible(False)
        assert fc.reference_lines_through_text(fig) == []

    def test_a_text_on_another_axes_is_not_tested_against_this_line(self):
        fig, (a, b) = plt.subplots(1, 2, figsize=(6, 3))
        for ax in (a, b):
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
        a.plot([0, 1], [0, 1], ls="--", color="black")
        b.text(0.5, 0.5, "next door", ha="center", va="center", fontsize=9)
        assert fc.reference_lines_through_text(fig) == []

    def test_the_span_threshold_is_adjustable(self):
        """A caller that wants every line measured can say so; the default keeps it quiet."""
        fig, ax = _blank()
        ax.plot([0.40, 0.60], [0.5, 0.5], ls="-", color="black")
        ax.text(0.5, 0.5, "short rule", ha="center", va="center", fontsize=9)
        assert fc.reference_lines_through_text(fig) == []
        assert fc.reference_lines_through_text(fig, min_span_frac=0.01)


class TestTheOpaqueLegendExemption:
    """A legend is a patch with text on it, and exempt for the same reason a bbox is --
    but only when the patch is opaque. Matplotlib's default framealpha is 0.8, and a series
    running under a legend at 0.8 is visible through it."""

    def _legend_figure(self, **legend_kw):
        fig, ax = _blank()
        ax.plot([0, 1], [0, 1], ls="-", color="black", label="series")
        ax.legend(loc="center", **legend_kw)
        return fig

    def test_an_opaque_frame_exempts_its_entries(self):
        assert fc.reference_lines_through_text(self._legend_figure(framealpha=1.0)) == []

    def test_a_translucent_frame_does_not(self):
        found = fc.reference_lines_through_text(self._legend_figure(framealpha=0.8))
        assert [d["text"] for d in found] == ["series"]

    def test_a_frameless_legend_does_not(self):
        found = fc.reference_lines_through_text(self._legend_figure(frameon=False))
        assert [d["text"] for d in found] == ["series"]

    def test_a_frame_with_no_alpha_set_counts_as_opaque(self):
        """`get_alpha()` is None until someone sets it; the default patch is solid."""
        fig, ax = _blank()
        ax.plot([0, 1], [0, 1], ls="-", color="black", label="series")
        leg = ax.legend(loc="center")
        leg.get_frame().set_alpha(None)
        assert fc.reference_lines_through_text(fig) == []

    def test_a_label_that_is_not_a_legend_entry_is_still_tested(self):
        """The exemption is for legend text, not for every label on an axes that has one."""
        fig, ax = _blank()
        ax.plot([0, 1], [0, 1], ls="-", color="black", label="series")
        ax.legend(loc="upper left", framealpha=1.0)
        ax.text(0.6, 0.6, "loose label", ha="center", va="center", fontsize=9)
        found = fc.reference_lines_through_text(fig)
        assert "loose label" in [d["text"] for d in found]

    def test_an_axes_with_no_legend_at_all(self):
        fig, ax = _blank()
        ax.plot([0, 1], [0, 1], ls="-", color="black")
        ax.text(0.5, 0.5, "no legend here", ha="center", va="center", fontsize=9)
        assert [d["text"] for d in fc.reference_lines_through_text(fig)] == ["no legend here"]


class TestLabelPatchesOverSpines:
    """The inverse of every other check here.

    Those ask whether drawn ink has landed on a label. This asks whether a label's own
    background has erased something drawn -- specifically the axes frame, which is what a
    patch anchored on the axis limit paints over. Figure 5's factor column did exactly that
    and printed the right spine with three gaps in it.
    """

    def _at(self, x, **kw):
        fig, ax = _blank()
        ax.text(x, 0.5, "39×", ha="right", va="center", fontsize=8,
                bbox=dict(facecolor="white", edgecolor="none", pad=0.8, **kw))
        return fig

    def test_a_patch_on_the_limit_covers_the_spine(self):
        found = fc.label_patches_over_spines(self._at(1.0))
        assert [d["text"] for d in found] == ["39×"]
        assert found[0]["spine"] == "right"
        assert found[0]["cover_px"] > fc.MAX_SPINE_COVER_PX

    def test_a_patch_inside_the_limit_does_not(self):
        assert fc.label_patches_over_spines(self._at(0.94)) == []

    def test_a_label_with_no_patch_is_not_a_patch(self):
        """Bare text over a spine is the other checks' business, not this one's."""
        fig, ax = _blank()
        ax.text(1.0, 0.5, "39×", ha="right", va="center", fontsize=8)
        assert fc.label_patches_over_spines(fig) == []

    def test_a_translucent_patch_does_not_erase(self):
        found = fc.label_patches_over_spines(self._at(1.0, alpha=0.4))
        assert found == []

    def test_a_patch_with_no_alpha_set_counts_as_opaque(self):
        fig = self._at(1.0)
        for txt in fc._visible_texts(fig):
            if txt.get_bbox_patch() is not None:
                txt.get_bbox_patch().set_alpha(None)
        assert [d["text"] for d in fc.label_patches_over_spines(fig)] == ["39×"]

    def test_the_tolerance_is_adjustable(self):
        """A couple of pixels is antialiasing; the caller decides where the line is."""
        fig = self._at(1.0)
        assert fc.label_patches_over_spines(fig, max_cover_px=1000) == []
        assert fc.label_patches_over_spines(fig, max_cover_px=0.0)

    def test_an_axes_with_no_visible_spines_is_skipped(self):
        fig, ax = _blank()
        for s in ax.spines.values():
            s.set_visible(False)
        ax.text(1.0, 0.5, "39×", ha="right", va="center", fontsize=8,
                bbox=dict(facecolor="white", edgecolor="none"))
        assert fc.label_patches_over_spines(fig) == []

    def test_an_invisible_axes_is_skipped(self):
        fig = self._at(1.0)
        fig.axes[0].set_visible(False)
        assert fc.label_patches_over_spines(fig) == []

    def test_a_text_on_another_axes_is_not_tested_against_this_frame(self):
        fig, (a, b) = plt.subplots(1, 2, figsize=(6, 3))
        for ax in (a, b):
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
        b.text(1.0, 0.5, "39×", ha="right", va="center", fontsize=8,
               bbox=dict(facecolor="white", edgecolor="none"))
        found = fc.label_patches_over_spines(fig)
        # It covers b's own right spine and nothing of a's.
        assert all(d["text"] == "39×" for d in found)

    def test_a_horizontal_spine_is_measured_along_its_length(self):
        """A patch on the bottom spine hides a horizontal run, not a vertical one."""
        fig, ax = _blank()
        ax.text(0.5, 0.0, "wide label here", ha="center", va="center", fontsize=9,
                bbox=dict(facecolor="white", edgecolor="none"))
        found = fc.label_patches_over_spines(fig)
        assert any(d["spine"] == "bottom" for d in found)

    def test_the_check_reaches_check_and_names_the_spine(self):
        with pytest.raises(fc.FigureCollision, match="painted over the right spine"):
            fc.check(self._at(1.0), "erased_figure")


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


class TestTheArtistsAndBoxesTheGateMustStepOver:
    """Every defensive path in the gate, taken from the side it had never been taken.

    This gate is the reason three rounds of figure defects were caught, and the way it fails
    is silent: an exception in the middle of the sweep, or a box it declines to measure, means
    the figures after it are never inspected and the build passes. Each branch here is one
    place that could happen.
    """

    def test_an_axis_that_will_not_report_its_view_is_skipped(self, monkeypatch):
        """A custom projection can refuse `get_view_interval`; one such axis must not stop
        the stale-label sweep for the rest of the figure."""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6, 2))
        ax1.plot([0, 1], [0, 1])
        ax2.plot([0, 1], [0, 1])
        fig.canvas.draw()

        real = type(ax1.xaxis).get_view_interval
        calls = {"n": 0}

        def flaky(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("this projection has no view interval")
            return real(self)

        monkeypatch.setattr(type(ax1.xaxis), "get_view_interval", flaky)
        stale = fc._stale_tick_labels(fig)
        assert isinstance(stale, set)
        assert calls["n"] > 1, "the failure must not have ended the sweep"
        plt.close(fig)

    def test_a_tick_with_no_location_is_skipped(self, monkeypatch):
        """Some tick objects carry no position at all; asking whether one is in view is not
        a question that has an answer."""
        fig, ax = plt.subplots(figsize=(3, 2))
        ax.plot([0, 1], [0, 1])
        fig.canvas.draw()
        for tick in ax.xaxis.get_major_ticks():
            monkeypatch.setattr(tick, "get_loc", lambda: None, raising=False)
        assert isinstance(fc._stale_tick_labels(fig), set)
        plt.close(fig)

    def test_a_schematic_panel_with_its_frame_off_has_its_ticks_marked_stale(self):
        """Nothing draws them, and they can sit squarely on a neighbouring panel's title."""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6, 2))
        ax1.axis("off")
        ax2.set_title("a title the stale labels could land on")
        fig.canvas.draw()
        assert fc._stale_tick_labels(fig), "an axis-off panel must contribute stale labels"
        plt.close(fig)

    def test_a_label_whose_box_cannot_be_measured_is_skipped(self, monkeypatch):
        fig, ax = plt.subplots(figsize=(3, 2))
        ax.plot([0, 1], [0, 1], lw=12, color="black")
        ax.text(0.5, 0.5, "measured", ha="center", va="center")
        ax.set_title("also measured")
        calls = {"n": 0}
        real = fc._glyph_box

        def flaky(text, renderer):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("no extent")
            return real(text, renderer)

        monkeypatch.setattr(fc, "_glyph_box", flaky)
        got = fc.report(fig)
        assert isinstance(got["struck"], list)
        assert calls["n"] > 1
        plt.close(fig)

    def test_an_empty_label_box_is_not_a_label(self):
        """A Text carrying only whitespace measures zero and covers nothing."""
        fig, ax = plt.subplots(figsize=(3, 2))
        ax.plot([0, 1], [0, 1], lw=12, color="black")
        ax.text(0.5, 0.5, "   ", ha="center", va="center")
        assert fc.report(fig)["struck"] == []
        plt.close(fig)

    def test_a_label_off_the_canvas_is_not_reported_as_struck(self):
        """Its core lies outside the raster, so there is no ink to measure -- and a figure
        that places a label off the page has a different problem from a struck one."""
        fig, ax = plt.subplots(figsize=(3, 2))
        ax.plot([0, 1], [0, 1], lw=12, color="black")
        ax.text(-40.0, -40.0, "far off the page", transform=fig.dpi_scale_trans)
        got = fc.report(fig)
        assert not any("far off the page" in d["text"] for d in got["struck"])
        plt.close(fig)

    def test_a_pair_of_zero_area_labels_is_not_an_overlap(self):
        """Two boxes of no area intersect in no area; a share of 0/0 is not a fraction."""
        fig, ax = plt.subplots(figsize=(3, 2))
        ax.text(0.5, 0.5, "", ha="center")
        ax.text(0.5, 0.5, "", ha="center")
        assert fc.texts_overlapping(fig) == []
        plt.close(fig)


class TestTheTickSlotsAndBoxesThatAreAbsent:
    """Three `getattr(..., None)` guards, taken from the side where the attribute is missing.

    A tick carries two label slots and matplotlib has not always populated both, so the sweep
    reads them defensively. On this matplotlib both are always present, which is exactly why
    the absent case had never run: it is the version-portability path, and it is the one that
    would fire on a reader's machine rather than on ours.
    """

    def test_an_axis_off_panel_with_a_missing_label_slot_is_swept_anyway(self, monkeypatch):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6, 2))
        ax1.axis("off")
        ax2.set_title("a title the stale labels could land on")
        fig.canvas.draw()
        for axis in (ax1.xaxis, ax1.yaxis):
            for tick in list(axis.get_major_ticks()) + list(axis.get_minor_ticks()):
                monkeypatch.setattr(tick, "label2", None, raising=False)
        stale = fc._stale_tick_labels(fig)
        assert stale, "the label slot that is present must still be marked stale"
        plt.close(fig)

    def test_an_out_of_view_tick_with_a_missing_label_slot_is_swept_anyway(self, monkeypatch):
        """A locator produces ticks past the end of an axis; their Text objects persist with
        stale coordinates and can pile up in one spot."""
        fig, ax = plt.subplots(figsize=(3, 2))
        ax.plot([1, 10], [1, 10])
        ax.set_xscale("log")
        ax.set_xticks([1, 10])
        ax.set_xlim(2, 5)
        fig.canvas.draw()
        for tick in list(ax.xaxis.get_major_ticks()) + list(ax.xaxis.get_minor_ticks()):
            monkeypatch.setattr(tick, "label2", None, raising=False)
        assert isinstance(fc._stale_tick_labels(fig), set)
        plt.close(fig)

    def test_a_label_measuring_no_area_is_not_a_label(self):
        """A zero-width space is a string the gate would otherwise measure.

        It survives the emptiness test -- Python does not count it as whitespace -- carries
        the font's full line height, and occupies no width at all. Measured, its core would
        be a zero-area strip that any stroke passing nearby fills completely, and the gate
        would report a struck label that is not on the page. Such characters arrive in figure
        text pasted from a browser, so this is not a hypothetical string.
        """
        fig, ax = plt.subplots(figsize=(3, 2))
        ax.plot([0, 1], [0, 1], lw=12, color="black")
        zero_width = "\u200b"
        ax.text(0.5, 0.5, zero_width, ha="center", va="center")
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        measured = [fc._glyph_box(x, renderer) for x in fc._visible_texts(fig)
                    if x.get_text() == zero_width]
        assert measured and measured[0].width == 0, (
            "the fixture must actually measure zero, or this proves nothing")
        assert not any(d["text"] == zero_width for d in fc.report(fig)["struck"])
        plt.close(fig)
