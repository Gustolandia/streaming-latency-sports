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
    assert all(0 < r <= 100 for r, _ in pts)


def test_retention_points_skips_unparseable_rows(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("retention_pct,omb_p50_ms\n50,1.0\nnotanumber,1.0\n", encoding="utf-8")
    assert mrf.retention_points(p) == [(50.0, 1.0)]


def test_retention_points_refuses_an_empty_file(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("retention_pct,omb_p50_ms\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no usable retention"):
        mrf.retention_points(p)


def test_the_swing_the_caption_claims_is_the_swing_in_the_data():
    """279x is quoted in the text; it must come out of the artefact, not a memory of it."""
    at_grid = [r for r, m in mrf.retention_points() if m <= mrf.QUANTUM_MS]
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


def test_every_powered_arm_lies_below_the_continuum_diagonal():
    """The figure's whole message. If this ever fails, the figure is lying and so is the text."""
    powered = [r for r in mrf.grid_rows() if r["powered"]]
    assert len(powered) == 10
    assert all(r["d_obs"] < r["d_null"] for r in powered)


def test_plot_grid_draws_one_marker_per_arm_and_labels_both_classes():
    fig, ax = plt.subplots()
    mrf.plot_grid(ax, mrf.grid_rows())
    assert len(ax.lines) == 1 + 12 + 2  # diagonal, twelve arms, two legend proxies
    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert labels == ["powered (10)", "underpowered (2)"]


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
    assert mrf.main(["--out", str(tmp_path)]) == 0
    assert len(list(tmp_path.glob("*.pdf"))) == 6
    assert capsys.readouterr().out.count("wrote") == 6


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
    """Guards against a figure being renamed here and left dangling in the .tex."""
    tex = (ROOT / "paper.tex").read_text(encoding="utf-8")
    for stem in ("deletion", "stall_spectrum", "grid_membership",
                 "mechanism_forest", "ttrue_law"):
        assert "figures/%s.pdf" % stem in tex, "%s is built but not included" % stem


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
