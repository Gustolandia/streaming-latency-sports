"""Tests for scripts/make_result_figures.py - target >=95% branch coverage.

A figure is a claim, and these three carry claims the text also makes: that retention swings
by a factor the caption states, that the traced histogram has three modes with the largest of
the upper two on the scheduler slice, and that every powered grid arm sits below the continuum
diagonal. So the tests check the *content* of what gets drawn, not merely that a file appears.
Where a helper decides something -- which bucket the slice falls in, which cells count as
printing at the grid -- it is pinned against cases worked by hand.
"""
import csv
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import make_result_figures as mrf  # noqa: E402


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


# --- retention -----------------------------------------------------------------------------

def test_retention_points_reads_every_committed_cell():
    pts = mrf.retention_points()
    assert len(pts) == 75
    assert all(0 < r <= 100 for r, _, _ in pts)


def test_retention_points_skips_unparseable_rows(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("retention_pct,omb_p50_ms\n50,1.0\nnotanumber,1.0\n", encoding="utf-8")
    assert mrf.retention_points(p) == [(50.0, 1.0, "")]


def test_retention_points_refuses_an_empty_file(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("retention_pct,omb_p50_ms\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no usable retention"):
        mrf.retention_points(p)


def test_the_swing_the_caption_claims_is_the_swing_in_the_data():
    """279x is quoted in the text; it must come out of the artefact, not a memory of it."""
    at_grid = [r for r, m, _ in mrf.retention_points() if m <= mrf.QUANTUM_MS]
    assert len(at_grid) == 71
    assert round(max(at_grid) / min(at_grid)) == 279


def test_plot_deletion_draws_every_cell_and_splits_at_the_quantum():
    fig, ax = plt.subplots()
    pts = mrf.retention_points()
    mrf.plot_deletion(ax, pts)
    drawn = sum(c.get_offsets().shape[0] for c in ax.collections)
    assert drawn == len(pts)
    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert "printed at the grid (71)" in labels
    assert "printed above it (4)" in labels


def test_plot_deletion_uses_log_axes():
    """Linear axes hide the finding: two decades of retention against one printed value."""
    fig, ax = plt.subplots()
    mrf.plot_deletion(ax, mrf.retention_points())
    assert ax.get_xscale() == "log" and ax.get_yscale() == "log"


def test_plot_deletion_annotates_the_measured_ratio():
    fig, ax = plt.subplots()
    mrf.plot_deletion(ax, mrf.retention_points())
    assert any("279" in t.get_text() for t in ax.texts)


# --- markers the legend counts have to be markers the eye can count ------------------------

def test_spread_coincident_separates_markers_that_would_render_as_one():
    """The defect this exists for, in its own numbers.

    The two 256 KB replicates print 42,393 and 42,973 ms at 100% retention -- 1.4% apart on
    an axis spanning five decades. The legend said four cells sat above the grid and three
    circles were drawn. A figure in this paper that loses one of its own four markers is
    making the argument against itself.
    """
    xs = [42393.087, 42973.183]
    out = mrf.spread_coincident(xs, [100.0, 100.0])
    assert max(out) / min(out) >= mrf.SEPARATION_RATIO * 0.99


def test_the_separation_is_two_marker_widths_and_not_one():
    """One diameter of centre separation leaves two circles touching.

    That was the first answer, and round 45 found the consequence at print size: the two
    256 KB markers rendered as a single figure-of-eight, which is the undercount the
    spreading exists to prevent arriving one step later. Two diameters is what makes two
    markers read as two.

    The arithmetic, in the units the page is printed in: the deletion figure's axis spans
    0.30 to 129,000 ms, which is 5.6 decades across a 3.4 in column, so a decade is about
    44 pt. A marker at s=18 is about 4.8 pt across, so two diameters is 9.6 pt, or 0.22 of
    a decade.
    """
    import math
    decades = math.log10(129000.0 / 0.30)
    column_pt = 3.4 * 72.0
    pt_per_decade = column_pt / decades
    marker_pt = 18 ** 0.5 * 1.13          # scatter s is an area in pt^2; ~4.8 pt across
    want_decades = 2.0 * marker_pt / pt_per_decade
    assert math.log10(mrf.SEPARATION_RATIO) >= want_decades * 0.9, (
        "SEPARATION_RATIO of %.2f is %.3f of a decade; two marker widths needs %.3f, and "
        "below that the two circles touch and read as one"
        % (mrf.SEPARATION_RATIO, math.log10(mrf.SEPARATION_RATIO), want_decades))
    # And not so large that the displacement stops being a rendering nudge.
    assert mrf.SEPARATION_RATIO < 2.0, "a factor this large misreports position"


def test_spread_coincident_keeps_the_group_centred():
    """Symmetric, so no reading of position moves beyond the separation itself."""
    xs = [1000.0, 1010.0]
    out = mrf.spread_coincident(xs, [50.0, 50.0])
    before = (xs[0] * xs[1]) ** 0.5
    after = (out[0] * out[1]) ** 0.5
    assert abs(after / before - 1.0) < 1e-9


def test_spread_coincident_leaves_separated_markers_alone():
    xs = [235.0, 519.0]
    assert mrf.spread_coincident(xs, [34.4, 35.9]) == xs


def test_spread_coincident_leaves_a_lone_marker_alone():
    assert mrf.spread_coincident([42393.0], [100.0]) == [42393.0]


def test_spread_coincident_handles_three_at_one_place():
    out = mrf.spread_coincident([100.0, 101.0, 102.0], [7.0, 7.0, 7.0])
    assert len(set(round(v, 6) for v in out)) == 3


def test_every_above_grid_marker_is_separately_visible():
    """End to end, on the committed cells: four cells above the grid, four distinct x."""
    pts = mrf.retention_points()
    above = [(m, r) for r, m, _ in pts if m > mrf.QUANTUM_MS]
    xs = mrf.spread_coincident([m for m, _ in above], [r for _, r in above])
    assert len(above) == 4
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            far_apart = max(xs[i], xs[j]) / min(xs[i], xs[j]) >= mrf.SEPARATION_RATIO * 0.99
            assert far_apart or above[i][1] != above[j][1]


# --- the stall spectrum --------------------------------------------------------------------

def test_stall_histogram_parses_the_committed_dump():
    bins, counters = mrf.stall_histogram()
    assert len(bins) == 16
    assert counters["count"] == 551956


def test_stall_histogram_refuses_a_dump_with_no_buckets(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("Attaching 3 probes...\n@count: 5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no histogram buckets"):
        mrf.stall_histogram(p)


def test_the_spectrum_marks_three_modes():
    bins, _ = mrf.stall_histogram()
    fig, ax = plt.subplots()
    mrf.plot_spectrum(ax, bins, slice_ms=3.0)
    pct = [t.get_text() for t in ax.texts if t.get_text().endswith("%")]
    assert len(pct) == 3
    assert "10.5%" in pct


def test_the_slice_annotation_names_the_slice_and_the_rise():
    bins, _ = mrf.stall_histogram()
    fig, ax = plt.subplots()
    mrf.plot_spectrum(ax, bins, slice_ms=3.0)
    said = " ".join(t.get_text() for t in ax.texts)
    assert "3 ms" in said and "4.5" in said


def test_the_spectrum_omits_the_slice_annotation_when_no_constant_is_available():
    bins, _ = mrf.stall_histogram()
    fig, ax = plt.subplots()
    mrf.plot_spectrum(ax, bins, slice_ms=None)
    assert not any("base slice" in t.get_text() for t in ax.texts)


@pytest.mark.parametrize("us,want", [(1, "1"), (512, "512"), (1024, "1K"), (2048, "2K"),
                                     (32768, "32K")])
def test_bucket_labels(us, want):
    assert mrf._us_label(us) == want


@pytest.mark.parametrize("slice_ms,want", [
    (3.0, 2048),     # 3 ms lands in [2K, 4K): the committed testbed
    (0.75, 512),     # a one-vCPU shape would land two octaves down
    (2.048, 2048),   # exactly on a bucket edge belongs to that bucket
])
def test_slice_bucket_selection(slice_ms, want):
    los = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]
    assert mrf._slice_bucket(los, slice_ms) == want


def test_slice_bucket_below_every_bucket_returns_nothing():
    assert mrf._slice_bucket([1024, 2048], 0.001) is None


# --- grid ------------------------------------------------------------------------------------

def test_grid_rows_carry_both_distances_for_every_arm():
    rows = mrf.grid_rows()
    assert len(rows) == 12
    assert all({"rate_hz", "q", "powered", "d_obs", "d_null"} <= set(r) for r in rows)


def test_every_arm_carries_the_null_it_is_being_judged_against():
    """The figure drew each arm against a diagonal and asked the eye to judge distance from
    a line with nothing to say how far an arm can fall by chance. The p-values answering
    that were printed only in a supplement table."""
    rows = mrf.grid_rows()
    assert all(r["d_null_lo"] is not None and r["d_null_hi"] is not None for r in rows)


def test_the_diagonal_is_the_null_the_test_actually_uses():
    """The x axis says "expected from a continuum", so it has to be that expectation.

    It was not. The column held the distance of theta from its nearest vertex with no
    replicate noise -- the distance of the expectation -- while the test simulates noisy
    replicates and takes the expectation of the distance. Noise at mid-cell can only carry
    a replicate towards a vertex, so the two differ, by up to 0.04 here; on five of the
    twelve arms the noiseless value fell outside the simulated null's own central 90%, and
    the supplement's caption claimed it *was* that expectation. Containment is the cheap
    invariant that would have caught it, so it is now a gate.
    """
    for r in mrf.grid_rows():
        assert r["d_null_lo"] <= r["d_null"] <= r["d_null_hi"], r["rate_hz"]


def test_each_null_bar_is_dodged_off_its_own_arm():
    """The bar is the reference; the marker is the thing being judged against it.

    Drawn on the same abscissa the two read as one object, and in the right-hand fifth --
    five of twelve arms within 0.05 of each other -- bars, diagonal and neighbours
    interleaved into a smudge at column width. The dodge is a rendering offset and is
    checked as one: every bar moves by exactly the stated fraction, and every marker keeps
    the x the ledger measured.

    It does not claim to take the bars off the diagonal. A vertical bar centred on the
    null's centre is cut by the diagonal near its middle, and no displacement small enough
    to be honest would change that.

    The offset is mirrored for an arm sitting within one dodge of the axis. It is absolute,
    so it is a fiftieth of the crowded arms' abscissae and two thirds of the leftmost one's,
    and on the printed page that put the 400 msg/s bar onto the left spine, nearer the
    origin than its own marker. The arms that need the dodge are the ones where it is
    proportionally invisible; the arms where it is proportionally huge have nothing beside
    them to crowd.
    """
    fig, ax = plt.subplots()
    rows = mrf.grid_rows()
    mrf.plot_grid(ax, rows)
    bars = [ln for ln in ax.lines
            if len(ln.get_xdata()) == 2 and ln.get_xdata()[0] == ln.get_xdata()[1]
            and ln.get_ydata()[0] != ln.get_ydata()[1]]
    assert len(bars) == len(rows), "one bar per arm"

    lim = max([r["d_null"] for r in rows] + [r["d_obs"] for r in rows]
              + [r["d_null_hi"] for r in rows]) * 1.12
    dodge = mrf.DODGE_FRACTION * lim
    assert dodge > 0.005, "a dodge this small would not clear a marker at column width"

    def placed(x):
        return x + dodge if x < 2 * dodge else x - dodge

    want = sorted(round(placed(r["d_null"]), 6) for r in rows)
    assert sorted(round(b.get_xdata()[0], 6) for b in bars) == want

    # Every bar stays inside the panel, which is the defect the mirror exists to prevent.
    left = -lim * 0.02
    assert all(b.get_xdata()[0] > left for b in bars), \
        "a null bar is drawn on or outside the left spine"

    # And the mirror actually fires here: without it this figure has a bar at 0.007 against
    # a spine at -0.011, which is the rendering round 45 found.
    assert any(r["d_null"] < 2 * dodge for r in rows), \
        "no arm is near the axis, so the mirror is untested by this ledger"

    # The marker keeps its measured position: the offset is on the reference, not the data.
    drawn = {round(ln.get_xdata()[0], 6) for ln in ax.lines if len(ln.get_xdata()) == 1}
    assert {round(r["d_null"], 6) for r in rows} <= drawn


def test_the_caption_states_the_reading_rule_with_its_direction():
    """A rule for reading a picture is wrong if it is wrong on the picture's own points.

    The caption said "a marker clear of its bar is an arm that rejects". The test is
    one-sided towards the grid -- `mc_pvalue` counts draws at or below the observed
    distance -- so an arm rejects by sitting *below* its band, and the generating function's
    own docstring has said "below" since the bands were added. The caption dropped the
    direction, and two of the twelve points it plots are the counterexample: both squares
    sit clear of their bars, above them, at p = 1.000 and 0.992. A reader applying the rule
    as written reads the two least significant arms in the figure as rejections.

    The main text had it right the whole time -- "which side of the diagonal it falls on is
    not evidence either way" -- which is what makes this a caption defect rather than a
    misunderstanding.
    """
    import stat_intervals
    caption = _figure_caption(r"\label{fig:grid}")
    low = caption.lower()
    assert "below" in low, \
        "the caption must say which side of its bar a rejecting marker is on"
    assert "clear of its bar is an arm" not in low, \
        "the direction-blind form of the rule is back"

    # The two squares are the reason the direction matters, so check they still are.
    above = [c for c in stat_intervals.grid_cells()
             if not c["powered"] and c["d_observed"] > c["d_null_hi"]]
    assert len(above) == 2, (
        "the no-power arms no longer sit above their own bands; the caption's exception "
        "may need rewording with them")


def _figure_caption(label):
    r"""The `\caption{...}` of the float carrying `label`, brace-matched."""
    tex = (ROOT / "paper.tex").read_text(encoding="utf-8")
    at = tex.index(label)
    start = tex.rindex(r"\caption{", 0, at) + len(r"\caption{")
    depth, i = 1, start
    while depth:
        if tex[i] == "{":
            depth += 1
        elif tex[i] == "}":
            depth -= 1
        i += 1
    return tex[start:i - 1]


def test_the_bands_agree_with_the_p_values_they_were_drawn_from():
    """Same Monte Carlo, same seed, so the picture and the table cannot part.

    An arm that rejects at 0.05 one-sided has an observed distance below the null's 5th
    percentile, and an arm that does not, does not. The unresolved arm is the one this
    pins hardest: it rejects before correction and not after, so it must sit just below
    its own band rather than clear of it.
    """
    import stat_intervals
    for c in stat_intervals.grid_cells():
        below = c["d_observed"] < c["d_null_lo"]
        assert below == (c["p_raw"] < 0.05), c["rate_hz"]


def test_every_powered_arm_lies_below_the_continuum_diagonal():
    """The figure's whole message. If this ever fails, the figure is lying and so is the text."""
    powered = [r for r in mrf.grid_rows() if r["powered"]]
    assert len(powered) == 10
    assert all(r["d_obs"] < r["d_null"] for r in powered)


def test_plot_grid_draws_one_marker_per_arm_and_labels_every_class():
    """Three classes, not two.

    Powered against underpowered is not the distinction the claim turns on: one powered arm
    does not reject after correction, and drawing it like the nine that do showed ten
    successes where the text claims nine. The counts stay pinned because they are what
    catches an arm silently dropped from the figure.
    """
    fig, ax = plt.subplots()
    mrf.plot_grid(ax, mrf.grid_rows())
    # diagonal, twelve null bands, twelve arms, four legend proxies
    assert len(ax.lines) == 1 + 12 + 12 + 4
    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert labels == ["rejects the null (9)", "unresolved (1)", "no power (2)",
                      "the null's central 90%"]


# --- builders ----------------------------------------------------------------------------

@pytest.mark.parametrize("name,stem", [("deletion", "deletion"),
                                       ("spectrum", "stall_spectrum"),
                                       ("grid", "grid_membership"),
                                       ("mechanism", "mechanism_forest"),
                                       ("ttrue", "ttrue_law")])
def test_each_builder_writes_a_pdf(tmp_path, name, stem):
    assert mrf.main(["--out", str(tmp_path), "--only", name]) == 0
    out = tmp_path / ("%s.pdf" % stem)
    assert out.is_file() and out.stat().st_size > 1000


def test_main_builds_every_figure_by_default(tmp_path, capsys):
    """Seven since round 17, when the priority ladder joined them.

    The count is pinned rather than loosened: a builder that stops running is the failure
    this catches, and it only catches it if the number is exact.
    """
    assert mrf.main(["--out", str(tmp_path)]) == 0
    assert len(list(tmp_path.glob("*.pdf"))) == 7
    assert capsys.readouterr().out.count("wrote") == 7


def test_the_spectrum_builder_takes_the_slice_from_the_derived_constants(tmp_path):
    """The 3 ms in the caption and the 3 ms in the figure must have one source."""
    import kernel_constants
    mrf.build_spectrum(tmp_path)
    assert kernel_constants.constants()["base_slice_ms"] == 3.0


def test_the_spectrum_builder_survives_missing_kernel_constants(tmp_path, monkeypatch):
    import kernel_constants
    monkeypatch.setattr(kernel_constants, "constants",
                        lambda: (_ for _ in ()).throw(OSError("no config")))
    assert mrf.build_spectrum(tmp_path).is_file()


def test_figures_the_manuscript_includes_are_the_ones_this_script_writes():
    """Guards against a figure being renamed here and left dangling in the .tex.

    The manuscript is two documents, and which one carries a figure is an editorial
    decision that moves: round 57 sent `mechanism_forest` to the supplement because it
    plotted two tables the main text already prints. What must never happen is a figure
    this script builds appearing in NEITHER file, which is the dangling case the test is
    for, so both are searched and the figure has to land in one of them.
    """
    tex = ((ROOT / "paper.tex").read_text(encoding="utf-8")
           + (ROOT / "supplement.tex").read_text(encoding="utf-8"))
    for stem in ("deletion", "stall_spectrum", "grid_membership",
                 "mechanism_forest", "ttrue_law"):
        assert "figures/%s.pdf" % stem in tex, "%s is built but included nowhere" % stem


# --- the mechanism forest and the T_true law ---------------------------------------------

def test_the_forest_carries_all_four_matched_pairs():
    arms = mrf.mechanism_arms()
    assert len(arms) == 8, "four pairs, two arms each"
    groups = {g for g, _, _, _ in arms}
    assert groups == {"Priority, 75%", "Priority, 88%",
                      "Geometry, original", "Geometry, replication"}


def test_no_pair_of_arms_overlaps():
    """The figure's whole message, and the paper's causal claim. If this fails, both lie."""
    import stat_intervals
    arms = mrf.mechanism_arms()
    for a, b in zip(arms[::2], arms[1::2]):
        lo_a, hi_a = stat_intervals.wilson(a[2], a[3])
        lo_b, hi_b = stat_intervals.wilson(b[2], b[3])
        assert hi_a < lo_b or hi_b < lo_a, "%s vs %s overlap" % (a[1], b[1])


def test_the_forest_draws_a_line_and_a_point_per_arm():
    fig, ax = plt.subplots()
    mrf.plot_mechanism(ax, mrf.mechanism_arms())
    assert len(ax.lines) == 2 * 8


def test_ttrue_points_are_the_committed_payload_sweep():
    pts = mrf.ttrue_points()
    assert len(pts) == 4
    xs = [p[0] for p in pts]
    assert xs == sorted(xs)
    assert round(xs[-1] / xs[0]) == 77, "the span the manuscript quotes"


def test_the_inversion_rate_falls_as_the_interval_grows():
    """A load-driven account predicts no change; the figure claims a monotone fall."""
    ys = [p[1] for p in mrf.ttrue_points()]
    assert all(a > b for a, b in zip(ys, ys[1:]))


def test_ttrue_refuses_an_empty_sweep(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("transport_ms,inversion,ci_lo,ci_hi\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no rows"):
        mrf.ttrue_points(p)


def test_the_ttrue_annotation_says_transport_not_payload():
    """Payload starts at zero bytes, so 77x is a ratio in transport. Do not mislabel it."""
    fig, ax = plt.subplots()
    mrf.plot_ttrue(ax, mrf.ttrue_points())
    said = " ".join(t.get_text() for t in ax.texts)
    assert "transport" in said and "payload" not in said


class TestTheArmsAndClassesThatAreAbsent:
    """What each figure builder does when a class, a campaign or a file is not there.

    These builders read the committed artefacts, and a reader rebuilding the figures from the
    archive may hold a subset of them. A legend entry for a class with no members, or an arm
    assembled from a campaign that is not present, would put a mark on the page that no data
    supports -- which in a paper about numbers with no path to their evidence is the one
    defect it cannot afford.
    """

    @staticmethod
    def _cell(rate, powered=True, verdict="grid", d_obs=0.4, d_null=0.6):
        return {"rate_hz": rate, "q": 3, "powered": powered,
                "d_obs": d_obs, "d_null": d_null, "verdict": verdict}

    def test_a_grid_class_with_no_members_gets_no_legend_entry(self):
        """Three classes are possible; a campaign need not produce all three, and a legend
        entry reading "no power (0)" would advertise a class the figure does not contain."""
        import matplotlib.pyplot as _plt
        fig, ax = _plt.subplots()
        mrf.plot_grid(ax, [self._cell(300)])
        labels = [x.get_text() for x in ax.get_legend().get_texts()]
        assert any("rejects the null" in lbl for lbl in labels)
        assert not any("no power" in lbl for lbl in labels)
        assert not any("unresolved" in lbl for lbl in labels)
        _plt.close(fig)

    def test_every_class_present_gets_its_own_entry_with_its_count(self):
        """The negative control above only means something beside the full case."""
        import matplotlib.pyplot as _plt
        fig, ax = _plt.subplots()
        mrf.plot_grid(ax, [self._cell(300),
                           self._cell(400, verdict="unresolved"),
                           self._cell(500, powered=False)])
        labels = " ".join(x.get_text() for x in ax.get_legend().get_texts())
        assert "rejects the null (1)" in labels
        assert "unresolved (1)" in labels
        assert "no power (1)" in labels
        _plt.close(fig)

    def test_a_geometry_campaign_that_is_absent_is_stepped_over(self, monkeypatch):
        """E-A6b replicates E-A6, and an archive can carry one without the other."""
        monkeypatch.setattr(mrf.stat_intervals, "priority_cells",
                            lambda: [("l75", 10, 100, 1, 100)])

        def only_the_first(phase="ea6"):
            if phase == "ea6":
                return [("k5_conc", 10, 100), ("k5_spread", 20, 100)]
            raise OSError("no such campaign in this archive")

        monkeypatch.setattr(mrf.stat_intervals, "geometry_cells", only_the_first)
        arms = mrf.mechanism_arms()
        assert any(a[0] == "Geometry, original" for a in arms)
        assert not any(a[0] == "Geometry, replication" for a in arms)

    def test_a_missing_span_recount_yields_no_arms_rather_than_raising(self, tmp_path):
        """The recount is an optional artefact; its absence is not a figure failure."""
        assert mrf.backend_arms(tmp_path / "never-written.csv") == []

    def test_a_backend_that_recorded_no_events_is_not_an_arm(self, tmp_path, monkeypatch):
        """A zero denominator is not a rate of zero, and drawn beside the others it would
        read as a broker that never inverts."""
        import recount_spans
        path = tmp_path / "span_recount.csv"
        path.write_text("run_id\n", encoding="utf-8")
        monkeypatch.setattr(recount_spans, "read_csv", lambda p: [])
        monkeypatch.setattr(recount_spans, "by_backend", lambda rows: {
            "kafka": {"events": 0, "neg_ack": 0},
            "redis": {"events": 100, "neg_ack": 3}})
        assert [a[0] for a in mrf.backend_arms(path)] == ["Redis"]

    def test_a_payload_row_whose_counts_will_not_parse_is_skipped(self, tmp_path):
        """One damaged replicate must cost that replicate, not the arm."""
        rows = []
        for label, keys, _colour in mrf.PAYLOAD_ARMS:
            for campaign, level in keys:
                rows.append("%s,1,shutdown_hook,%s,not-a-number,0,0" % (campaign, level))
                rows.append("%s,1,shutdown_hook,%s,50,50,0" % (campaign, level))
        path = tmp_path / "index.csv"
        path.write_text("campaign,valid,count_source,level,kept,discarded_zero,"
                        "discarded_negative\n" + "\n".join(rows) + "\n",
                        encoding="utf-8")
        arms = mrf.payload_arms(path)
        assert [a[0] for a in arms] == [a[0] for a in mrf.PAYLOAD_ARMS]
        assert all(vals == [50.0] * len(vals) for _, vals, _ in arms)

    def test_a_cell_that_measured_nothing_contributes_no_replicate(self, tmp_path):
        """Kept and discarded both zero is a cell that measured nothing, and an arm built
        only from such cells has no retention to draw."""
        label, keys, _colour = mrf.PAYLOAD_ARMS[0]
        rows = ["%s,1,shutdown_hook,%s,0,0,0" % (campaign, level)
                for campaign, level in keys]
        path = tmp_path / "index.csv"
        path.write_text("campaign,valid,count_source,level,kept,discarded_zero,"
                        "discarded_negative\n" + "\n".join(rows) + "\n",
                        encoding="utf-8")
        with pytest.raises(ValueError, match="no replicates for payload arm"):
            mrf.payload_arms(path)

    def test_the_spectrum_falls_back_when_the_slice_cannot_be_read(self, tmp_path,
                                                                   monkeypatch):
        """The scheduler slice annotates the histogram; without it the figure still builds,
        and it builds without the annotation rather than with a guessed one."""
        import kernel_constants
        monkeypatch.setattr(kernel_constants, "constants",
                            lambda *a, **kw: (_ for _ in ()).throw(OSError("no artefact")))
        out = mrf.build_spectrum(tmp_path)
        assert Path(str(out)).exists() or out is not None

    def test_an_explicit_slice_is_used_without_consulting_the_artefact(self, tmp_path,
                                                                       monkeypatch):
        """The caller can hand the slice in, and then the kernel constants must not be read.

        `make_paper_figures` already resolves the slice once for the whole build; reading it
        again here would let one figure annotate a different value from its neighbour.
        """
        import kernel_constants
        monkeypatch.setattr(kernel_constants, "constants",
                            lambda *a, **kw: (_ for _ in ()).throw(
                                AssertionError("the artefact must not be consulted")))
        out = mrf.build_spectrum(tmp_path, slice_ms=7.5)
        assert out is not None


def test_a_histogram_that_starts_above_the_tick_gets_no_tick_rule():
    """The 1 ms mark is drawn only if a bucket contains it.

    A capture whose smallest bucket already exceeds a millisecond has no bucket the tick falls
    in, and a rule drawn at the left edge would assert a boundary the axis does not carry.
    """
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    bins = [(2048, 4096, 10), (4096, 8192, 6), (8192, 16384, 3)]
    mrf.plot_spectrum(ax, bins, slice_ms=3.0)
    assert not [t for t in ax.texts if "tick" in t.get_text()]
    plt.close(fig)


def test_a_histogram_containing_the_tick_gets_the_rule():
    """The negative control above only means something beside the case that draws it."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    bins = [(256, 512, 8), (512, 1024, 10), (1024, 2048, 6), (2048, 4096, 9)]
    mrf.plot_spectrum(ax, bins, slice_ms=3.0)
    assert [t for t in ax.texts if "1 ms tick" in t.get_text()]
    plt.close(fig)


def test_a_pair_with_a_zero_arm_gets_no_factor():
    """A ratio against zero is not a factor, and printing "inf" beside a real pair would
    read as a measurement rather than a division that could not be done."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    arms = [("Priority, 75%", "ordinary", 0, 100), ("Priority, 75%", "real-time", 5, 100),
            ("Priority, 88%", "ordinary", 30, 100), ("Priority, 88%", "real-time", 3, 100)]
    mrf.plot_mechanism(ax, arms)
    printed = [t.get_text() for t in ax.texts if t.get_text().endswith("×")]
    assert len(printed) == 1, "only the pair with two non-zero arms carries a factor"
    plt.close(fig)
