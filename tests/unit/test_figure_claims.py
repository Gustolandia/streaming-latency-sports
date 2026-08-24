"""Every figure is a claim; check it against the artefact and against its own caption.

The manuscript's numbers pass through a ledger and the test suite fails if text and data
disagree. Figures had no equivalent gate: a caption could state a mode share, a fold or a
count that the plotted data did not support, and nothing would notice. These tests close that
gap. They check three things per figure -- that the data drawn is the committed data, that the
quantity the caption states is the quantity the data gives, and that the caption reaches it
through a ledger macro rather than a typed literal.

The last of those matters most. A caption is prose, and prose is where numbers go stale.
"""
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import kernel_constants as kc        # noqa: E402
import make_result_figures as mrf    # noqa: E402
import stat_intervals as si          # noqa: E402
import tail_index_traced as tit      # noqa: E402

TEX = ((ROOT / "paper.tex").read_text(encoding="utf-8") + "\n"
       + (ROOT / "supplement.tex").read_text(encoding="utf-8"))
# The submission is both documents. The pipeline schematic moved to the supplement in
# round 16, when the figures were redrawn at printable type size and the paper had to
# give a full-width float back; "included" has to mean included in the package.
MACROS = dict(re.findall(
    r"\\newcommand\{\\(\w+)\}\{(.*?)\}\s*$",
    (ROOT / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8"), re.M))

FIGURE_STEMS = ("pipeline_schematic", "measurement_model", "deletion", "payload_flip",
                "grid_membership", "mechanism_forest", "stall_spectrum", "ttrue_law")


def caption_of(label):
    """The caption text belonging to a label, so a claim can be checked against its figure."""
    i = TEX.index("\\label{%s}" % label)
    j = TEX.rindex("\\caption{", 0, i)
    return TEX[j:i]


def _int(macro):
    return int(MACROS[macro].replace("{,}", "").replace(",", ""))


# --- fig:deletion -------------------------------------------------------------------------

def test_deletion_plots_every_committed_cell():
    assert len(mrf.retention_points()) == 75


def test_deletion_at_grid_count_is_the_ledgers():
    at_grid = [r for r, m in mrf.retention_points() if m <= mrf.QUANTUM_MS]
    assert len(at_grid) == _int("ombGridMedianCells")


def test_deletion_annotates_the_ledgers_fold():
    at_grid = [r for r, m in mrf.retention_points() if m <= mrf.QUANTUM_MS]
    assert round(max(at_grid) / min(at_grid)) == _int("ombRetentionFold")


def test_deletion_caption_reaches_the_fold_through_the_ledger():
    assert "ombRetentionFold" in caption_of("fig:deletion")


# --- fig:spectrum -------------------------------------------------------------------------

def test_spectrum_wakeup_count_is_the_ledgers():
    _, counters = mrf.stall_histogram()
    assert counters["count"] == _int("tracedEvents")


def test_spectrum_has_the_three_modes_the_caption_claims():
    bins, _ = mrf.stall_histogram()
    assert len(tit.modes(bins)) == _int("tracedModes")


def test_spectrum_mode_share_is_the_ledgers():
    bins, _ = mrf.stall_histogram()
    top = [m for m in tit.modes(bins) if m[0] == 2048][0]
    assert "%.1f" % (100 * top[2]) == MACROS["tracedModeShare"]


def test_spectrum_draws_the_derived_slice_not_a_literal():
    bins, _ = mrf.stall_histogram()
    los = [b[0] for b in bins]
    assert mrf._slice_bucket(los, kc.constants()["base_slice_ms"]) == 2048


def test_spectrum_caption_reaches_the_slice_through_the_ledger():
    assert "baseSliceMs" in caption_of("fig:spectrum")


# --- fig:grid -----------------------------------------------------------------------------

def test_grid_draws_every_arm():
    assert len(mrf.grid_rows()) == _int("gridArms")


def test_grid_powered_count_is_the_ledgers():
    assert len([r for r in mrf.grid_rows() if r["powered"]]) == _int("gridPowered")


def test_every_powered_arm_lies_below_the_diagonal():
    """The figure's entire message, and the paper's claim about the set."""
    assert all(r["d_obs"] < r["d_null"] for r in mrf.grid_rows() if r["powered"])


def test_grid_caption_reaches_the_flat_count_through_the_ledger():
    assert "gridFlat" in caption_of("fig:grid")


# --- fig:mechanism ------------------------------------------------------------------------

def test_mechanism_draws_four_matched_pairs():
    assert len(mrf.mechanism_arms()) == 8


def test_no_pair_of_arms_overlaps():
    """The caption says "no overlap". If that stops being true, the caption is a lie."""
    arms = mrf.mechanism_arms()
    for a, b in zip(arms[::2], arms[1::2]):
        lo_a, hi_a = si.wilson(a[2], a[3])
        lo_b, hi_b = si.wilson(b[2], b[3])
        assert hi_a < lo_b or hi_b < lo_a, "%s and %s overlap" % (a[1], b[1])


def test_mechanism_rates_match_the_ledger():
    a = mrf.mechanism_arms()[0]
    assert "%.4f" % (a[2] / a[3]) == MACROS["rtLowBase"]


# --- fig:ttrue ----------------------------------------------------------------------------

def test_ttrue_draws_the_four_payload_levels():
    assert len(mrf.ttrue_points()) == 4


def test_ttrue_falls_monotonically_as_the_caption_claims():
    ys = [p[1] for p in mrf.ttrue_points()]
    assert all(a > b for a, b in zip(ys, ys[1:]))


def test_ttrue_span_is_the_one_the_text_states():
    xs = [p[0] for p in mrf.ttrue_points()]
    assert round(xs[-1] / xs[0]) == 77


# --- every figure ---------------------------------------------------------------------------

@pytest.mark.parametrize("stem", FIGURE_STEMS)
def test_figure_is_built_and_included(stem):
    p = ROOT / "docs" / "results" / "figures" / ("%s.pdf" % stem)
    assert p.is_file() and p.stat().st_size > 1000, "%s not built" % stem
    assert "figures/%s.pdf" % stem in TEX, "%s built but not included" % stem


def test_every_figure_is_referenced_from_the_prose():
    labels = set(re.findall(r"\\label\{(fig:[^}]*)\}", TEX))
    refs = set(re.findall(r"\\ref\{(fig:[^}]*)\}", TEX))
    assert labels <= refs, "unreferenced: %s" % sorted(labels - refs)


def test_no_figure_is_scaled_on_inclusion():
    """Every figure is drawn at the width it prints at.

    This replaces a pin that required one width everywhere, which was right while every
    figure sat in a column and became wrong when three moved to full-width floats. The
    property that matters is not uniformity but the absence of scaling: a figure included at
    a fraction of its drawn width has its type reduced by that fraction, which is how the
    paper came to print labels at 2.7 pt against 9.5 pt body text.
    """
    widths = set(re.findall(r"\\includegraphics\[width=([^\]]*)\]", TEX))
    scaled = [w for w in widths if re.match(r"[\d.]+\\", w)]
    assert not scaled, ("figures included at a fraction of their drawn width: %s -- draw them "
                        "at the printed width instead" % sorted(scaled))
    assert widths <= {r"\columnwidth", r"\textwidth"}, \
        "unexpected include width: %s" % sorted(widths - {r"\columnwidth", r"\textwidth"})
