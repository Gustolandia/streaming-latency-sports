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
       + (ROOT / "postmortem.tex").read_text(encoding="utf-8") + "\n"
       # 4 Oct 2026: the journal supplement carries the traced stall spectrum now.
       + (ROOT / "supplement.tex").read_text(encoding="utf-8"))
# The submission is both documents. The pipeline schematic moved to the supplement in
# round 16, when the figures were redrawn at printable type size and the paper had to
# give a full-width float back; "included" has to mean included in the package.
# The width gate reads the two documents it was written for. The journal supplement is set
# in one column, where a fraction of the column enlarges a figure drawn for a 3.5-inch
# column rather than shrinking its type.
SUBMISSION_TEX = ((ROOT / "paper.tex").read_text(encoding="utf-8") + "\n"
                  + (ROOT / "postmortem.tex").read_text(encoding="utf-8"))
MACROS = dict(re.findall(
    r"\\newcommand\{\\(\w+)\}\{(.*?)\}\s*$",
    (ROOT / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8"), re.M))

FIGURE_STEMS = ("pipeline_schematic", "measurement_model", "deletion_phases", "payload_flip",
                "grid_membership", "mechanism_forest", "stall_spectrum", "ttrue_law",
                # Round 54: the exposure table drawn as a curve, in the supplement beside
                # the table, because the main text is at the journal's page limit.
                "exposure_curve",
                # 5 Oct 2026: the rebuilt paper opens its results on the distribution of S
                # alone. It took the place of `two_ways`, the two failures side by side, which
                # no document includes any more (the artifact index declares it).
                "s_distribution",
                # 4 Oct 2026: what the remedies buy, whose panel (a) carries the exposure curve
                # the column figure drew; the column figure was retired with its builder.
                "remedies",
                # 15 Oct 2026: the fix, drawn in Section VI for the industry's reader.
                "kernel_timestamps",
                # 15 Oct 2026: the eight matched pairs' real-time factors on both brokers, with
                # their run-level intervals, for the supplement's S3.1 (both referees).
                "priority_forest")

#: Figures built for a passage the text has not yet written, each with the date and why. The
#: inclusion check below exempts them and fails once the text includes one, so that the entry
#: is removed in the revision that includes it rather than left to vouch for nothing.
#: Empty since 15 Oct 2026, when Supplement S3.1 took up priority_forest, drawn that day.
AWAITING_INCLUSION = {}


def caption_of(label):
    """The caption text belonging to a label, so a claim can be checked against its figure."""
    i = TEX.index("\\label{%s}" % label)
    j = max(TEX.rindex("\\caption{", 0, i) if "\\caption{" in TEX[:i] else -1, TEX.rindex("\\caption[", 0, i) if "\\caption[" in TEX[:i] else -1)
    return TEX[j:i]


def caption_of_figure(stem):
    """The caption of the float that draws `figures/<stem>.pdf`, whatever its label.

    A figure that moves between the documents changes its label with its document (the
    deletion figure was the paper's fig:deletion until 5 Oct 2026, and the supplement gives
    it a label of its own), and the claim its caption makes does not move with it."""
    inc = TEX.index("figures/%s.pdf" % stem)
    start = TEX.rindex("\\begin{figure", 0, inc)
    end = TEX.index("\\end{figure", inc)
    float_ = TEX[start:end]
    at = max(float_.find("\\caption{"), float_.find("\\caption["))
    assert at >= 0, "the float drawing %s has no caption" % stem
    return float_[at:]


def _int(macro):
    return int(MACROS[macro].replace("{,}", "").replace(",", ""))


# --- the deletion figure (deletion_phases) ------------------------------------------------

def test_deletion_plots_every_committed_cell():
    assert len(mrf.retention_points()) == 75


def test_deletion_at_grid_count_is_the_ledgers():
    at_grid = [r for r, m, _ in mrf.retention_points() if m <= mrf.AT_GRID_MAX_MS]
    assert len(at_grid) == _int("ombGridMedianCells")


def test_deletion_annotates_the_ledgers_fold():
    at_grid = [r for r, m, _ in mrf.retention_points() if m <= mrf.AT_GRID_MAX_MS]
    assert round(max(at_grid) / min(at_grid)) == _int("ombRetentionFold")


def test_deletion_caption_reaches_the_fold_through_the_ledger():
    # 5 Oct 2026: the figure is the journal supplement's (S4.1); found by the file it draws.
    # 6 Oct 2026: the paper's again, Section V-C's, and found the same way.
    assert "ombRetentionFold" in caption_of_figure("deletion_phases")


# --- fig:twoways: the distribution of S ----------------------------------------------------

def test_s_distribution_draws_the_counts_its_caption_states():
    """The paper's Fig. 2 since 5 Oct 2026. Its caption counts the messages and the values of S
    below zero, and says D on the same messages never falls below zero. The histogram it draws
    must hold exactly those counts, and the caption must reach both through the ledger."""
    import make_deletion_histogram as mdh
    series, extra = mdh.read_hist()

    def counted(name, below_zero=False):
        bins = sum(c for lo, _hi, c in series[name] if lo < 0 or not below_zero)
        return bins + extra[name]["under"] + (0 if below_zero else extra[name]["over"])

    assert counted("ack") == _int("spanEvents")
    assert counted("ack", below_zero=True) == _int("spanNegAck")
    assert counted("send", below_zero=True) == _int("spanNegSend") == 0
    caption = caption_of_figure("s_distribution")
    assert "\\spanEvents" in caption and "\\spanNegAck" in caption


# --- fig:exposure -------------------------------------------------------------------------

def test_exposure_curve_and_its_table_share_one_source():
    """The figure is the table drawn. If they parted, one of them would be wrong.

    Both read `_exposure_lags()`, so this checks the wiring rather than the arithmetic: the
    curve's median and band must be the same three lags the table's columns are built from.
    """
    import emit_paper_numbers as epn
    lags = epn._exposure_lags()
    assert lags is not None, "the exposure source is missing"
    typical, _hi, _lo, p10, p90 = lags
    assert p10 <= typical <= p90, "the band must bracket the line drawn inside it"
    # The crossover the text quotes beside panel (a) is where the publish latency equals the
    # end-to-end latency.
    assert "%.2f" % (typical / 1000.0) == MACROS["exposureCrossover"]


def test_exposure_caption_reaches_its_numbers_through_the_ledger():
    """Since 5 Oct 2026 the caption gives the band's two ends, not the crossover (the text
    beside it quotes that). They must come through the ledger and be the lags the band is
    drawn between. 15 Oct 2026: the figure is the journal supplement's Fig. S1 (S2.1), and its
    label moved with it."""
    import emit_paper_numbers as epn
    caption = caption_of("sfig:exposure")
    assert "\\exposureLagLo" in caption and "\\exposureLagHi" in caption
    _typical, _hi, _lo, p10, p90 = epn._exposure_lags()
    assert (MACROS["exposureLagLo"], MACROS["exposureLagHi"]) == ("%.0f" % p10, "%.0f" % p90)


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
    # 4 Oct 2026: the traced stall spectrum is the journal supplement's now (sfig:spectrum).
    assert "baseSliceMs" in caption_of("sfig:spectrum")


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
    # 7 Oct 2026: 77 as first computed; 74 without the late messages, whose long waits had
    # lifted the padded cells' median S.
    assert round(xs[-1] / xs[0]) == 74


# --- every figure ---------------------------------------------------------------------------

@pytest.mark.parametrize("stem", FIGURE_STEMS)
def test_figure_is_built_and_included(stem):
    p = ROOT / "docs" / "results" / "figures" / ("%s.pdf" % stem)
    assert p.is_file() and p.stat().st_size > 1000, "%s not built" % stem
    included = "figures/%s.pdf" % stem in TEX
    if stem in AWAITING_INCLUSION:
        assert not included, ("%s is included now; remove its AWAITING_INCLUSION entry (%s)"
                              % (stem, AWAITING_INCLUSION[stem]))
    else:
        assert included, "%s built but not included" % stem


def test_a_figure_awaits_inclusion_only_while_it_is_registered():
    """The exemption names registered figures only, each with its date and reason."""
    assert set(AWAITING_INCLUSION) <= set(FIGURE_STEMS)
    assert all(re.match(r"\d{1,2} [A-Z][a-z]{2} \d{4}: \w", reason)
               for reason in AWAITING_INCLUSION.values())


# --- the referees' figures of 15 Oct 2026 --------------------------------------------------

def test_s_distribution_outlines_sum_to_the_pooled_bars():
    """Fig. 2(a)'s two broker outlines partition the pooled histogram, bin for bin."""
    import make_deletion_histogram as mdh
    series, extra = mdh.read_hist()
    brokers, broker_extra = mdh.read_broker_hist()
    assert set(brokers) == {"kafka", "redis"}
    pooled = {lo: c for lo, _hi, c in series["ack"]}
    summed = {}
    for rows in brokers.values():
        for lo, _hi, c in rows:
            summed[lo] = summed.get(lo, 0) + c
    assert summed == {lo: c for lo, c in pooled.items() if c}
    for side in ("under", "over"):
        assert sum(e[side] for e in broker_extra.values()) == extra["ack"][side]


def test_s_distribution_panel_b_draws_every_run_of_the_ladder_and_the_pairs():
    """Fig. 2(b): every run of E-A3's nine cells and of the eight pairs, on both brokers, and
    at every pair the median run at normal priority above the median run at real-time."""
    import statistics
    import manipulation_runs as mr
    runs = mr.rate_by_load()
    assert len(runs) == 2 * (9 + 2 * _int("rtPairs")) * 25
    by = {}
    for r in runs:
        by.setdefault((r["backend"], r["campaign"], r["cell"].rpartition("_")[0],
                       r["priority"]), []).append(r["rate"])
    pairs = {k[:3] for k in by if k[3] == "real-time"}
    assert len(pairs) == 2 * _int("rtPairs")
    for key in pairs:
        assert statistics.median(by[key + ("normal",)]) > statistics.median(
            by[key + ("real-time",)]), key


def test_remedies_dots_are_the_median_only_recovery_by_broker():
    """Fig. 6's dots are |med S + med A - med D| / med D, the recovery Section VI describes,
    and every group names its broker in the counts the ledger prints."""
    rows = mrf.repair_rows()
    pops = si.recovery_populations(split="broker")
    for key, name in (("kafka", "Kafka"), ("redis", "Redis")):
        mine = sorted(r[2] for r in rows if r[3] == key)
        assert mine == pytest.approx(pops[name])
        assert len(mine) == _int("recovery%sN" % name)


def test_remedies_padding_points_are_the_committed_medians():
    """The padding trajectories: E-A10 and E-A10b, four levels on each broker, A/D as drawn."""
    import manipulation_runs as mr
    pts = mrf.padding_points()
    assert sorted((c, b) for c, b, _p in pts) == [
        ("E-A10", "kafka"), ("E-A10", "redis"), ("E-A10b", "kafka"), ("E-A10b", "redis")]
    rows = {(r["campaign"], r["backend"], r["median_d_ms"]): r for r in mr.read_padding()}
    for campaign, broker, path in pts:
        assert len(path) == 4
        assert [d for d, _e in path] == sorted(d for d, _e in path), "D grows with padding"
        for d, e in path:
            r = rows[(campaign, broker, d)]
            assert e == pytest.approx(100.0 * r["median_a_ms"] / r["median_d_ms"])


def test_deletion_marks_exactly_the_cells_at_incommensurate_rates():
    """Fig. 4(b) rings the captured settings paced at a rate Section V-C calls incommensurate."""
    marked = mrf.incommensurate_points()
    loose = {c["rate_hz"] for c in si.spread_cells() if not c["commensurate"]}
    assert len(loose) == _int("spreadIncommensurate")
    assert {p[2] for p in marked} <= loose
    assert len(marked) == 8 and {p[2] for p in marked} == {383, 457}
    drawn = {(r, m) for r, m, _ in mrf.retention_points()}
    assert all((p[0], p[1]) in drawn for p in marked)


def test_priority_forest_draws_every_pair_and_the_ledgers_floor():
    """The forest's pairs, its dashed floor and its unbounded intervals are the ledger's."""
    import math
    import emit_paper_numbers
    rows = mrf.priority_forest_rows()
    for key, name in (("kafka", "Kafka"), ("redis", "Redis")):
        assert len(rows[key]) == _int("rtPairs")
        # 16 Oct 2026: the floor is rounded down, as a lower bound must be.
        assert emit_paper_numbers.floor_to_tenth(min(p["lo"] for p in rows[key])) == \
            MACROS["rt%sLowerBound" % name]
        assert sum(1 for p in rows[key] if math.isinf(p["hi"])) == _int(
            "rt%sUnboundedPairs" % name)


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
    widths = set(re.findall(r"\\includegraphics\[width=([^\]]*)\]", SUBMISSION_TEX))
    scaled = [w for w in widths if re.match(r"[\d.]+\\", w)]
    assert not scaled, ("figures included at a fraction of their drawn width: %s -- draw them "
                        "at the printed width instead" % sorted(scaled))
    assert widths <= {r"\columnwidth", r"\textwidth"}, \
        "unexpected include width: %s" % sorted(widths - {r"\columnwidth", r"\textwidth"})


#: 15 Oct 2026: the figures drawn or redrawn for the referees' reports of that day.
REDRAWN_15_OCT = ("s_distribution", "remedies", "deletion_phases", "exposure_curve",
                  "recovery_populations", "priority_forest")


@pytest.mark.parametrize("stem", REDRAWN_15_OCT)
def test_a_redrawn_figure_is_never_shrunk_on_the_page(stem):
    """The legibility gate measures a figure's canvas; the page prints the cropped file, scaled
    to the width the document includes it at. Fig. 2's labels stood past its canvas on 15 Oct
    2026, its file came out 3.61 in for the 3.5 in column, and its 8 pt type would have printed
    at 7.8 pt with every gate green. So no file redrawn that day may be wider than the width a
    document prints it at, or, while it awaits inclusion, the width it is drawn for."""
    import figure_legibility
    import make_result_figures as mrf
    from pypdf import PdfReader
    printed = figure_legibility.print_widths()
    if stem in AWAITING_INCLUSION:
        printed[stem] = mrf.SUPPLEMENT_WIDTH_IN
    pdf = ROOT / "docs" / "results" / "figures" / ("%s.pdf" % stem)
    width = float(PdfReader(str(pdf)).pages[0].mediabox.width) / 72.0
    # A hair's tolerance: a figure saved whole at exactly its printed width (15 Oct 2026) is
    # that width to the PDF's rounding, which a strict comparison reads as a millionth too wide.
    assert width <= printed[stem] + 1e-6, "%s is %.2f in, printed at %.2f in" % (
        stem, width, printed[stem])
