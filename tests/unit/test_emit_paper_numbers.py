"""Tests for emit_paper_numbers.

The manuscript's campaign counts were hand-typed in eleven places and went stale in all eleven
together: the paper said 80 runs and 420,000 discarded samples when the ledger held 108 and
4,377,904. This script exists so that number lives in exactly one place.

The tests that matter here are not the formatting ones. They are: that `--check` actually fails on
a stale file (a check that cannot fail is worse than no check), and that the script refuses to emit
numbers from an empty ledger rather than confidently writing zeroes into a manuscript.
"""
import csv
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_fork_exposure  # noqa: E402
import emit_paper_numbers as epn  # noqa: E402
import stat_intervals  # noqa: E402
from emit_paper_numbers import (  # noqa: E402
    HEADER, latex_thousands, macros, main, render,
)
from check_paper_omb_numbers import load_cells, measured  # noqa: E402

LEDGER_FIELDS = ("campaign", "cell", "valid", "count_source",
                 "kept", "discarded_zero", "discarded_negative")


def write_ledger(path, rows):
    """rows: (campaign, kept, discarded_zero, discarded_negative)"""
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(LEDGER_FIELDS)
        for i, (camp, kept, zero, neg) in enumerate(rows):
            w.writerow([camp, "c%d" % i, "1", "shutdown_hook", kept, zero, neg])


def measured_from(path):
    return measured(load_cells(str(path)))


class TestThousandsSeparator:
    def test_short_numbers_are_untouched(self):
        assert latex_thousands(0) == "0"
        assert latex_thousands(999) == "999"

    def test_groups_are_counted_from_the_right(self):
        assert latex_thousands(1000) == "1{,}000"
        assert latex_thousands(12345) == "12{,}345"
        assert latex_thousands(123456) == "123{,}456"

    def test_millions_get_every_separator(self):
        assert latex_thousands(4377904) == "4{,}377{,}904"
        assert latex_thousands(1000000) == "1{,}000{,}000"

    def test_the_separator_is_the_brace_form_math_mode_needs(self):
        """A bare comma in math mode renders with the wrong spacing."""
        assert "," not in latex_thousands(4377904).replace("{,}", "")
        assert "{,}" in latex_thousands(4377904)


class TestMacros:
    def test_the_quantities_the_manuscript_quotes_are_all_present(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 90, 0), ("load_sweep", 30, 70, 0)])
        names = {n for n, _ in macros(measured_from(p))}
        assert {"ombRuns", "ombDiscarded", "ombKept", "ombNegatives"} <= names

    def test_values_come_from_the_ledger(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 1000, 2000, 0), ("load_sweep", 500, 1500, 0)])
        got = dict(macros(measured_from(p)))
        assert got["ombRuns"] == "2"
        assert got["ombDiscarded"] == "3{,}500"
        assert got["ombKept"] == "1{,}500"

    def test_retention_bounds_are_emitted_when_measurable(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 25, 75, 0), ("load_sweep", 90, 10, 0)])
        got = dict(macros(measured_from(p)))
        assert got["ombRetentionMin"] == "25.00"
        assert got["ombRetentionMax"] == "90.00"

    def test_retention_bounds_are_omitted_when_no_cell_saw_a_sample(self, tmp_path):
        """Emitting a bound from nothing would put a fabricated number in the manuscript."""
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 0, 0, 0)])
        names = {n for n, _ in macros(measured_from(p))}
        assert "ombRetentionMin" not in names
        assert "ombRetentionMax" not in names

    def test_a_negative_count_is_emitted_verbatim(self, tmp_path):
        """The section's withdrawal rests on this being zero; it must never be massaged."""
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 80, 7)])
        assert dict(macros(measured_from(p)))["ombNegatives"] == "7"


class TestRender:
    def test_output_is_valid_newcommands(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 90, 0)])
        text = render(measured_from(p))
        assert "\\newcommand{\\ombRuns}{1}" in text
        for line in text.splitlines():
            assert line.startswith("%") or line.startswith("\\newcommand{\\")

    def test_the_file_says_not_to_edit_it(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 90, 0)])
        assert HEADER in render(measured_from(p))
        assert "Do not edit by hand" in render(measured_from(p))

    def test_rendering_is_deterministic(self, tmp_path):
        """--check compares text, so any instability would make it fail at random."""
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 90, 0), ("resolution", 5, 5, 0)])
        assert render(measured_from(p)) == render(measured_from(p))


class TestCLI:
    def test_it_writes_the_file_and_lists_what_it_wrote(self, tmp_path, capsys):
        led, out = tmp_path / "l.csv", tmp_path / "gen" / "n.tex"
        tbl = tmp_path / "gen" / "t.tex"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        assert main(["--ledger", str(led), "--out", str(out), "--table", str(tbl)]) == 0
        assert "\\newcommand{\\ombRuns}{1}" in out.read_text(encoding="utf-8")
        assert "ombRuns" in capsys.readouterr().out

    def test_it_creates_the_parent_directory(self, tmp_path):
        led, out = tmp_path / "l.csv", tmp_path / "a" / "b" / "c" / "n.tex"
        tbl = tmp_path / "a" / "b" / "c" / "t.tex"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        assert main(["--ledger", str(led), "--out", str(out), "--table", str(tbl)]) == 0
        assert out.exists()

    def test_check_passes_on_a_current_file(self, tmp_path, capsys):
        led, out = tmp_path / "l.csv", tmp_path / "n.tex"
        tbl = tmp_path / "t.tex"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        main(["--ledger", str(led), "--out", str(out), "--table", str(tbl)])
        assert main(["--ledger", str(led), "--out", str(out), "--table", str(tbl), "--check"]) == 0
        assert "match the artefacts" in capsys.readouterr().out

    def test_check_fails_once_the_ledger_moves(self, tmp_path, capsys):
        """The whole point: this is what catches a campaign landing after the last build."""
        led, out = tmp_path / "l.csv", tmp_path / "n.tex"
        tbl = tmp_path / "t.tex"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        main(["--ledger", str(led), "--out", str(out), "--table", str(tbl)])
        write_ledger(led, [("load_sweep", 10, 90, 0), ("load_sweep", 20, 80, 0)])
        assert main(["--ledger", str(led), "--out", str(out), "--table", str(tbl), "--check"]) == 1
        out_txt = capsys.readouterr().out
        assert "STALE" in out_txt and "regenerate with" in out_txt

    def test_check_writes_nothing(self, tmp_path):
        """A check that repaired the file would always pass and never report anything."""
        led, out = tmp_path / "l.csv", tmp_path / "n.tex"
        tbl = tmp_path / "t.tex"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        main(["--ledger", str(led), "--out", str(out), "--table", str(tbl)])
        before = out.read_text(encoding="utf-8")
        write_ledger(led, [("load_sweep", 10, 90, 0), ("load_sweep", 20, 80, 0)])
        main(["--ledger", str(led), "--out", str(out), "--table", str(tbl), "--check"])
        assert out.read_text(encoding="utf-8") == before

    def test_check_on_a_file_that_does_not_exist_says_how_to_make_it(self, tmp_path, capsys):
        led = tmp_path / "l.csv"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        assert main(["--ledger", str(led), "--out", str(tmp_path / "no.tex"), "--check"]) == 1
        assert "run without --check" in capsys.readouterr().out

    def test_crlf_in_the_committed_file_is_not_a_difference(self, tmp_path):
        """The working tree is CRLF on Windows; that must not read as a stale file."""
        led, out = tmp_path / "l.csv", tmp_path / "n.tex"
        tbl = tmp_path / "t.tex"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        main(["--ledger", str(led), "--out", str(out), "--table", str(tbl)])
        body = out.read_text(encoding="utf-8")
        with out.open("w", encoding="utf-8", newline="") as fh:
            fh.write(body.replace("\n", "\r\n"))
        assert main(["--ledger", str(led), "--out", str(out), "--table", str(tbl), "--check"]) == 0

    def test_a_bare_filename_needs_no_parent_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        write_ledger(tmp_path / "l.csv", [("load_sweep", 10, 90, 0)])
        assert main(["--ledger", "l.csv", "--out", "n.tex"]) == 0
        assert (tmp_path / "n.tex").exists()

    def test_a_missing_ledger_is_an_error(self, tmp_path, capsys):
        assert main(["--ledger", str(tmp_path / "no.csv"), "--out", str(tmp_path / "n.tex")]) == 1
        assert "missing" in capsys.readouterr().out

    def test_it_refuses_to_emit_from_an_empty_ledger(self, tmp_path, capsys):
        """Writing zeroes into the manuscript would be worse than failing."""
        led = tmp_path / "l.csv"
        write_ledger(led, [("smoke", 1, 1, 0)])          # not a paper campaign
        assert main(["--ledger", str(led), "--out", str(tmp_path / "n.tex")]) == 1
        assert "refusing to emit numbers from nothing" in capsys.readouterr().out
        assert not (tmp_path / "n.tex").exists()


class TestAgainstTheRealLedger:
    """The committed artefacts, checked as a pair."""

    ROOT = Path(__file__).resolve().parents[2]

    def test_the_committed_macro_file_matches_the_committed_ledger(self):
        led = self.ROOT / "docs" / "results" / "external_campaigns_index.csv"
        gen = self.ROOT / "docs" / "generated" / "paper_numbers.tex"
        if not led.exists() or not gen.exists():
            pytest.skip("ledger or generated file not present")
        want = render(measured(load_cells(str(led))))
        have = gen.read_text(encoding="utf-8").replace("\r\n", "\n")
        assert have == want, "run python scripts/emit_paper_numbers.py and commit the result"

    def test_the_manuscript_uses_the_macros_it_is_given(self):
        paper = self.ROOT / "paper.tex"
        gen = self.ROOT / "docs" / "generated" / "paper_numbers.tex"
        if not paper.exists() or not gen.exists():
            pytest.skip("paper or generated file not present")
        src = paper.read_text(encoding="utf-8", errors="replace")
        assert "\\input{docs/generated/paper_numbers}" in src
        for name in ("ombRuns", "ombDiscarded"):
            assert ("\\" + name) in src, "%s is emitted but the manuscript ignores it" % name


class TestTheRefereeDrivenMacroGroups:
    """The macro groups added for the TC revision.

    Each exists because a number reached the page without passing through this script and
    turned out to be wrong: the grid table printed uncorrected p-values under a caption
    claiming correction, the retention sentence quoted a denominator no artefact contained,
    and the traced tail index was a slope with no interval. The behaviour under a missing
    artefact matters as much as the happy path, because a group that silently returns
    nothing leaves an undefined macro in the manuscript, and the build must fail loudly
    rather than typeset the macro name.
    """

    def test_grid_macros_report_the_corrected_count(self):
        got = dict(epn.grid_macros())
        assert got["gridArms"] == "12"
        assert got["gridPowered"] == "10"
        assert got["gridReject"] == "9"
        assert got["gridUnresolvedRate"] == "900"
        assert float(got["gridUnresolvedRaw"]) < 0.05 < float(got["gridUnresolvedHolm"])

    def test_the_generated_table_prints_corrected_values_only(self):
        body = epn.render_grid_table()
        assert r"p_{\mathrm{Holm}}" in body, "the column must say which p it shows"
        assert "0.044" not in body, "the raw value must not survive into the table"
        assert "not resolved" in body, "the unresolved arm must be labelled as such"
        assert body.count(r"\\") == 13, "twelve arms plus the header row"

    def test_retention_macros_supply_the_denominator_the_text_lost(self):
        got = dict(epn.retention_macros())
        assert got["ombMedianCells"] == "75"
        assert got["ombGridMedianCells"] == "71"
        assert got["ombRetentionFold"] == "279"

    def test_traced_macros_carry_intervals_not_bare_points(self):
        got = dict(epn.traced_macros())
        assert "$--$" in got["tracedExcCI"] and "$--$" in got["tracedMleCI"]
        assert float(got["tracedMleAlpha"]) > float(got["tracedExcAlpha"])

    def test_tost_macros_print_the_result_the_text_asserted(self):
        got = dict(epn.tost_macros())
        assert got["tostMargin"] == "1"
        assert "$--$" in got["tostHLCI"]

    def test_tost_macros_are_absent_when_the_artefact_is(self, tmp_path):
        assert epn.tost_macros(str(tmp_path / "nope.csv")) == []

    def test_tost_macros_are_absent_when_the_artefact_is_headers_only(self, tmp_path):
        p = tmp_path / "t.csv"
        p.write_text("n,margin,hl_shift,hl_ci90_lo,hl_ci90_hi\n", encoding="utf-8")
        assert epn.tost_macros(str(p)) == []

    @pytest.mark.parametrize("group", ["grid_macros", "retention_macros", "traced_macros"])
    def test_each_group_degrades_to_empty_when_its_artefact_is_unreadable(self, group,
                                                                          monkeypatch):
        """A checkout without the results tree still emits the campaign numbers. The
        manuscript's own consistency tests are what forbid quoting a macro that then does
        not exist."""
        import stat_intervals
        import tail_index_traced
        for mod, name in ((stat_intervals, "grid_cells"),
                          (stat_intervals, "retention_cells"),
                          (tail_index_traced, "report")):
            monkeypatch.setattr(mod, name, lambda *a, **k: (_ for _ in ()).throw(OSError))
        assert getattr(epn, group)() == []

    def test_traced_macros_are_empty_when_the_named_histogram_is_absent(self, monkeypatch):
        import tail_index_traced
        monkeypatch.setattr(tail_index_traced, "report", lambda *a, **k: [])
        assert epn.traced_macros() == []

    def test_grid_macros_omit_the_unresolved_names_when_every_arm_resolves(self, monkeypatch):
        import stat_intervals
        monkeypatch.setattr(stat_intervals, "grid_cells", lambda *a, **k: [
            {"rate_hz": 1, "p": 1, "q": 1, "n": 5, "d_observed": 0.1, "d_null": 0.4,
             "p_raw": 0.001, "p_holm": 0.003, "powered": True, "verdict": "grid"}])
        got = dict(epn.grid_macros())
        assert got["gridReject"] == "1"
        assert "gridUnresolvedRate" not in got
        assert "gridFlatRates" not in got, "no flat arms means no flat-arm macro"

    def test_retention_macros_are_empty_when_no_cell_reports_a_grid_median(self, monkeypatch):
        import stat_intervals
        monkeypatch.setattr(stat_intervals, "retention_cells", lambda *a, **k: [
            {"campaign": "x", "cell": "y", "retention_pct": 50.0, "p50_ms": 235.0,
             "pub_p50_ms": 0.3, "kept": 10}])
        assert epn.retention_macros() == []

    def test_every_macro_the_manuscript_inputs_is_uniquely_named(self):
        from check_paper_omb_numbers import load_cells, measured
        cells = load_cells("docs/results/external_campaigns_index.csv")
        names = [n for n, _ in epn.all_pairs(measured(cells))]
        assert len(names) == len(set(names)), "a duplicate \newcommand would fail the build"


class TestRegistryMacros:
    """The audited-harness survey reaches the page as counts, not adjectives.

    Section II says how many independent harnesses dispose of an inverted sample without
    counting it. That sentence used to be a claim about the field backed by prose; it is now
    a fold over committed evidence whose labels are recomputed on every build. These tests
    exist so that loosening a classifier pattern cannot quietly change what the paper says.
    """

    def test_the_counts_come_from_the_committed_registry(self):
        import harness_registry
        got = dict(epn.registry_macros())
        s = harness_registry.summary()
        assert got["harnessAudited"] == str(s["harnesses"])
        assert got["harnessSilent"] == str(s["n_silent"])

    def test_the_survey_covers_more_than_one_vendor_and_language(self):
        got = dict(epn.registry_macros())
        assert int(got["harnessVendors"]) >= 4
        assert int(got["harnessLanguages"]) >= 3

    def test_both_disposal_classes_are_represented(self):
        got = dict(epn.registry_macros())
        assert int(got["harnessFilters"]) >= 2
        assert int(got["harnessSuppressors"]) >= 2

    def test_at_least_one_harness_counts_its_discards(self):
        """Without a counterexample the survey would be an advertisement."""
        assert int(dict(epn.registry_macros())["harnessCounting"]) >= 1

    def test_silent_never_exceeds_the_harnesses_audited(self):
        got = dict(epn.registry_macros())
        assert int(got["harnessSilent"]) <= int(got["harnessAudited"])

    def test_the_small_counts_are_also_emitted_as_words(self):
        """IEEE style spells a small number in prose, and the alternative to emitting the
        word was transcribing it into the manuscript, where it would go stale on its own."""
        got = dict(epn.registry_macros())
        assert got["harnessAuditedWord"] == epn._spell(int(got["harnessAudited"]))
        assert got["harnessSilentWord"] == epn._spell(int(got["harnessSilent"]))

    def test_every_word_has_a_capitalised_twin(self):
        """Several of these open a sentence, and a macro cannot know that it does."""
        got = dict(epn.registry_macros())
        words = [k for k in got if k.endswith("Word")]
        assert words
        for k in words:
            cap = got[k + "Cap"]
            assert cap == got[k][:1].upper() + got[k][1:]

    def test_a_count_past_twelve_keeps_its_digits(self):
        """Where house style stops spelling, so does this."""
        assert epn._spell(12) == "twelve"
        assert epn._spell(13) == "13"
        assert epn._spell(0) == "zero"

    def test_a_missing_registry_yields_no_macros_rather_than_wrong_ones(self, monkeypatch):
        import harness_registry
        monkeypatch.setattr(harness_registry, "summary",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))
        assert epn.registry_macros() == []

class TestThePriorityResidualRange:
    """Section V-C names a constant the model fixes in advance, and S47 used to state the
    range the manipulated arm actually covers from two numbers typed by hand. A referee
    pointed out that a third of the arms sit outside the constant, which makes "floor" the
    wrong word for it -- so the range is emitted and the sentence reads off the ladder."""

    def test_the_range_comes_from_the_committed_pairs(self):
        import priority_pairs
        got = dict(epn.priority_residual_macros())
        rates = [p["rate_rt"] for p in priority_pairs.usable()]
        assert got["rtResidualMin"] == "%.4f" % min(rates)
        assert got["rtResidualMax"] == "%.4f" % max(rates)
        assert got["rtResidualPairs"] == str(len(rates))

    def test_the_range_straddles_the_constant_the_model_names(self):
        """The finding behind the wording change: 0.004 is a scale, not a bound."""
        got = dict(epn.priority_residual_macros())
        assert float(got["rtResidualMin"]) < 0.004 < float(got["rtResidualMax"])

    def test_missing_campaign_files_yield_no_macros_rather_than_wrong_ones(self, monkeypatch):
        import priority_pairs
        monkeypatch.setattr(priority_pairs, "usable",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))
        assert epn.priority_residual_macros() == []

    def test_an_empty_ladder_yields_no_macros(self, monkeypatch):
        """min() of nothing raises; returning early says so without a traceback."""
        import priority_pairs
        monkeypatch.setattr(priority_pairs, "usable", lambda *a, **k: [])
        assert epn.priority_residual_macros() == []

    def test_the_group_is_wired_into_the_emitted_file(self):
        names = {n for n, _ in epn.all_pairs(measured(load_cells(
            Path(__file__).parent.parent.parent / "docs" / "results"
            / "external_campaigns_index.csv")))}
        assert {"rtResidualMin", "rtResidualMax", "rtResidualPairs"} <= names


class TestTheSignedPayloadSlope:
    """One word and one sign for one quantity. The ledger emitted only the magnitude, so
    Section V-D said "exponent 0.339" while Figure 6 drew "slope -0.34" from the same fit."""

    def test_the_slope_is_signed_and_the_exponent_is_its_magnitude(self):
        got = dict(epn.stat_macros())
        assert got["tailSlope"].startswith("-")
        assert abs(float(got["tailSlope"])) == round(float(got["tailExponent"]), 2)

    def test_the_interval_carries_its_own_math_so_the_signs_print_as_minus(self):
        got = dict(epn.stat_macros())
        assert "$" in got["tailSlopeCI"], "used inside $...$; the word must leave math mode"
        lo, hi = got["tailSlopeCI"].split("$ to $")
        assert float(lo) < float(got["tailSlope"]) < float(hi)


    def test_the_group_is_wired_into_the_emitted_file(self):
        names = {n for n, _ in epn.all_pairs(measured(load_cells(
            Path(__file__).parent.parent.parent / "docs" / "results"
            / "external_campaigns_index.csv")))}
        assert {"harnessAudited", "harnessSilent"} <= names


class TestGuardScopeMacros:
    """The scope of the OpenMessaging guard, computed from the registry rather than recalled.

    A referee who opens MessageProducer.java finds a nanosecond clock and no filter. That does
    not contradict the paper, but an unqualified "the benchmark filters" would. These macros
    put the qualifier where it cannot be forgotten: derived from the evidence at build time.
    """

    def test_the_guarded_span_is_the_cross_process_one(self):
        got = dict(epn.registry_macros())
        assert got["ombGuardedPath"] == "end-to-end"
        assert got["ombGuardedClock"] == "millisecond"

    def test_the_unguarded_span_is_the_same_process_one(self):
        got = dict(epn.registry_macros())
        assert got["ombUnguardedPath"] == "publish"
        assert got["ombUnguardedClock"] == "nanosecond"

    def test_the_coarse_clock_lands_on_the_guarded_span(self):
        """The asymmetry the paper draws its conclusion from."""
        got = dict(epn.registry_macros())
        assert got["ombGuardedClock"] == "millisecond"
        assert got["ombUnguardedClock"] == "nanosecond"
        assert got["ombGuardedClock"] != got["ombUnguardedClock"]

    def test_the_contrast_count_is_emitted(self):
        assert int(dict(epn.registry_macros())["harnessSplitGuard"]) >= 1

    def test_a_registry_without_the_contrast_still_emits_the_survey(self, monkeypatch):
        import harness_registry
        monkeypatch.setattr(harness_registry, "within_harness_contrast", lambda *a, **k: {})
        got = dict(epn.registry_macros())
        assert "harnessAudited" in got
        assert "ombGuardedPath" not in got

    def test_a_broken_contrast_does_not_break_the_build(self, monkeypatch):
        import harness_registry
        monkeypatch.setattr(harness_registry, "within_harness_contrast",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))
        got = dict(epn.registry_macros())
        assert "harnessAudited" in got


class TestRegistryTableVocabulary:
    """The renderer's maps must cover everything the classifier can say.

    Round 6 taught the classifier `library_refusal` and added two harnesses; the renderer's
    label and citation maps, being hand-written, learned neither. wrk2's Disposal cell
    rendered as "---", identical to the two counterexamples -- the table acquitted a tool the
    text convicts -- and the caption's hand-written source list kept six keys in the old row
    order beside the sentence "this table is generated at build time". These pins make the
    next vocabulary gap a test failure instead of a round-8 finding.
    """

    def test_every_disposal_class_has_a_table_label(self):
        from audit_external_harness import DISPOSAL_KINDS
        missing = set(DISPOSAL_KINDS) - set(epn.REGISTRY_LABELS)
        assert not missing, "class(es) the table would render as an acquittal: %s" % sorted(
            missing)

    def test_every_registry_harness_has_a_citation_key(self):
        import harness_registry
        harnesses = {r["harness"] for r in harness_registry.load()}
        missing = harnesses - set(epn.REGISTRY_CITES)
        assert not missing, "harness(es) absent from the caption's sources: %s" % sorted(
            missing)

    def test_the_sources_macro_matches_the_rows_in_count_and_order(self):
        """The caption claims "in row order"; the macro and the tabular must agree."""
        import harness_registry
        rows = sorted(harness_registry.paths())
        macro = dict(epn.registry_sources_macro())["registryTableSources"]
        keys = macro[len(r"\cite{"):-1].split(",")
        assert len(keys) == len(rows), (len(keys), len(rows))
        assert keys == [epn.REGISTRY_CITES[h] for h, _ in rows]

    def test_the_supplement_caption_uses_the_generated_list(self):
        r"""A hand-written \cite list beside "generated at build time" is the round-7 bug."""
        from pathlib import Path
        supp = (Path(__file__).parent.parent.parent / "supplement.tex").read_text(
            encoding="utf-8")
        i = supp.index(r"\label{tab:registry}")
        caption = supp[supp.rindex(r"\caption{", 0, i):i]
        assert r"\registryTableSources" in caption
        assert r"\cite{openmessaging2018" not in caption, "hand-written source list is back"


class TestTracedRatioMacros:
    """The unfitted cross-instrument check, emitted rather than hand-copied.

    Section V-C quotes these three ratios and Section V-E now leans on them again, to bound
    a userspace serialisation the traced estimator cannot see. Two uses of one number is
    exactly when it should stop being typed.
    """

    def test_the_ratios_come_from_the_artefacts(self):
        pairs = dict(epn.traced_ratio_macros())
        if not pairs:
            pytest.skip("runq_tail artefacts absent")
        import csv
        import glob
        expected = []
        for path in sorted(glob.glob("docs/results/**/runq_tail.csv", recursive=True)):
            with open(path, encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    inv, tail = float(row["inversion"]), float(row["p_tail"])
                    if inv > 0:
                        expected.append(tail / inv)
        expected.sort()
        assert pairs["tracedRatios"] == ", ".join("%.2f" % r for r in expected)
        assert pairs["tracedRatioArms"] == str(len(expected))

    def test_the_bound_brackets_unity(self):
        """The argument in Section V-E is the direction of the disagreement, not its size."""
        pairs = dict(epn.traced_ratio_macros())
        if not pairs:
            pytest.skip("runq_tail artefacts absent")
        lo, hi = float(pairs["tracedRatioLo"]), float(pairs["tracedRatioHi"])
        assert lo < 1.0 < hi, \
            "the elimination argument requires the kernel-only estimator to straddle the " \
            "observed rate rather than fall short of it; got %.2f-%.2f" % (lo, hi)

    def test_floored_arms_contribute_no_ratio(self):
        """A real-time arm with zero inversions has no finite ratio to report."""
        pairs = dict(epn.traced_ratio_macros())
        if not pairs:
            pytest.skip("runq_tail artefacts absent")
        assert "inf" not in pairs["tracedRatios"]


class TestTheMacrosThatAreOmittedRatherThanGuessed:
    """The emitter reads a dozen artefacts and any of them can be missing or partial.

    This is the round-16 lesson applied to the emitter itself: a macro is the path from a
    sentence to its evidence, and a macro emitted from evidence that is not there is worse
    than a typed number, because it looks derived. Each branch below is a place where the
    emitter must decline.
    """

    def test_a_backend_whose_name_is_not_a_latex_word_gets_no_macros(self, tmp_path,
                                                                     monkeypatch):
        """Macro names are LaTeX control words, so a backend called `redis-2` cannot become
        one. Emitting it anyway would write a file that does not compile."""
        import recount_spans
        path = tmp_path / "span_recount.csv"
        path.write_text("run_id\n", encoding="utf-8")
        agg = {"runs": 1, "events": 10, "neg_ack": 1, "pct_ack": 10.0, "neg_send": 0,
               "neg_output_send": 0, "neg_tti": 0, "runs_over_one_pct_ack": 1,
               "runs_ack_only_inversions": 1, "runs_ack_inverts": 1,
               "runs_send_inverts": 0, "deepest_ack_inversion_us": 1000.0,
               "send_span_floor_us": 50.0, "offset_margin_factor": 3.0}
        monkeypatch.setattr(recount_spans, "read_csv", lambda p: [])
        monkeypatch.setattr(recount_spans, "totals", lambda rows: agg)
        monkeypatch.setattr(recount_spans, "by_backend", lambda rows: {
            "kafka": dict(agg), "redis-2": dict(agg)})
        names = [n for n, _ in epn.span_macros(str(path))]
        assert "spanKafkaEvents" in names
        assert not any("redis-2" in n for n in names)

    def test_one_backend_alone_emits_no_other_floor(self, tmp_path, monkeypatch):
        """The manuscript says the pooled floor is the smaller of two. With one backend there
        is no other, and a macro naming one would assert a comparison never made."""
        import recount_spans
        path = tmp_path / "span_recount.csv"
        path.write_text("run_id\n", encoding="utf-8")
        agg = {"runs": 1, "events": 10, "neg_ack": 1, "pct_ack": 10.0, "neg_send": 0,
               "neg_output_send": 0, "neg_tti": 0, "runs_over_one_pct_ack": 1,
               "runs_ack_only_inversions": 1, "runs_ack_inverts": 0,
               "runs_send_inverts": 0, "deepest_ack_inversion_us": 1000.0,
               "send_span_floor_us": 50.0, "offset_margin_factor": 3.0}
        monkeypatch.setattr(recount_spans, "read_csv", lambda p: [])
        monkeypatch.setattr(recount_spans, "totals", lambda rows: agg)
        monkeypatch.setattr(recount_spans, "by_backend", lambda rows: {"kafka": dict(agg)})
        names = [n for n, _ in epn.span_macros(str(path))]
        assert "spanSendFloorOtherUs" not in names

    def test_a_traced_row_that_will_not_parse_is_skipped(self, tmp_path, monkeypatch):
        """These files are written by several campaigns and one damaged row must not cost
        the cross-instrument check its other arms."""
        results = tmp_path / "docs" / "results" / "ea9"
        results.mkdir(parents=True)
        (results / "runq_tail.csv").write_text(
            "arm,inversion,p_tail\n"
            "base,not-a-number,0.5\n"
            "base,0.10,0.20\n"
            "base,0.20,0.30\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        got = dict(epn.traced_ratio_macros())
        assert got, "the readable rows must still produce ratios"

    def test_a_priority_level_that_was_not_run_emits_nothing_for_it(self, monkeypatch):
        monkeypatch.setattr(stat_intervals, "priority_cells",
                            lambda: [("l75", 10, 100, 1, 100)])
        monkeypatch.setattr(stat_intervals, "geometry_cells",
                            lambda phase="ea6": [])
        names = [n for n, _ in epn.stat_macros()]
        assert any("Low" in n for n in names)
        assert not any("High" in n for n in names)

    def test_a_geometry_campaign_that_is_absent_emits_nothing_for_it(self, monkeypatch):
        monkeypatch.setattr(stat_intervals, "priority_cells", lambda: [])

        def only_the_first(phase="ea6"):
            if phase == "ea6":
                return [("k5_conc", 10, 100), ("k5_spread", 20, 100)]
            raise OSError("no such campaign in this archive")

        monkeypatch.setattr(stat_intervals, "geometry_cells", only_the_first)
        names = [n for n, _ in epn.stat_macros()]
        assert any("GeomOrig" in n for n in names)
        assert not any("GeomRepl" in n for n in names)

    def test_a_geometry_campaign_with_one_arm_is_not_a_comparison(self, monkeypatch):
        """The pair is what the claim rests on; one arm alone cannot make it."""
        monkeypatch.setattr(stat_intervals, "priority_cells", lambda: [])
        monkeypatch.setattr(stat_intervals, "geometry_cells",
                            lambda phase="ea6": [("k5_conc", 10, 100)])
        assert not any("Geom" in n for n, _ in epn.stat_macros())

    def test_an_unreadable_payload_fit_emits_no_tail_exponent(self, monkeypatch):
        monkeypatch.setattr(stat_intervals, "priority_cells", lambda: [])
        monkeypatch.setattr(stat_intervals, "geometry_cells",
                            lambda phase="ea6": [])
        monkeypatch.setattr(stat_intervals, "payload_fit",
                            lambda *a, **kw: (_ for _ in ()).throw(OSError("absent")))
        assert not any("tailExponent" in n for n, _ in epn.stat_macros())

    def test_a_traced_estimate_missing_its_optional_parts_emits_only_what_it_has(
            self, monkeypatch):
        """The exceedance index, the octaves, the mode, the tail refit and the goodness of
        fit are each optional. A partial estimate must produce a partial macro set, not a
        crash and not a fabricated entry."""
        import tail_index_traced
        monkeypatch.setattr(tail_index_traced, "report", lambda *a, **kw: [{
            "tag": "ea9/l88_base", "traced_events": 1000,
            "mle_alpha": 1.2, "mle_lo": 1.0, "mle_hi": 1.4,
            "octaves": [(256, 1.1)], "modes": [(512, 10, 0.1, 2.0)],
            "gof_boot": 0}])
        names = [n for n, _ in epn.traced_macros()]
        assert "tracedMleAlpha" in names
        for absent in ("tracedExcAlpha", "tracedOctaveA", "tracedModeLo",
                       "tracedTailAlpha", "tracedGofP"):
            assert absent not in names, absent

    def test_a_complete_traced_estimate_emits_every_part(self, monkeypatch):
        """The negative control above only means something beside the full case."""
        import tail_index_traced
        monkeypatch.setattr(tail_index_traced, "report", lambda *a, **kw: [{
            "tag": "ea9/l88_base", "traced_events": 1000,
            "mle_alpha": 1.2, "mle_lo": 1.0, "mle_hi": 1.4,
            "exc_alpha": 1.3, "exc_lo": 1.1, "exc_hi": 1.5,
            "octaves": [(256, 1.1), (512, 2.2)],
            "modes": [(2048, 30, 0.3, 4.0), (512, 10, 0.1, 2.0)],
            "tail_alpha": 1.4, "tail_lo": 1.2, "tail_hi": 1.6, "tail_from_us": 4096,
            "gof_p": 0.0, "gof_boot": 10000}])
        got = dict(epn.traced_macros())
        assert got["tracedExcAlpha"] == "1.30"
        assert got["tracedOctaveA"] == "1.10" and got["tracedOctaveB"] == "2.20"
        assert got["tracedModeLo"] == "2" and got["tracedModeHi"] == "4"
        assert got["tracedTailFrom"] == "4"
        assert got["tracedGofP"] == "<0.0001", "an exact zero must be reported as a bound"

    def test_a_mechanism_artefact_that_is_absent_emits_nothing_for_it(self, monkeypatch):
        """Four independent reads, each guarded, and each able to be the missing one."""
        for name in ("harness_cells", "occupancy_bounds", "load_growth", "observer_effect"):
            monkeypatch.setattr(stat_intervals, name,
                                lambda *a, **kw: (_ for _ in ()).throw(OSError("absent")))
        assert epn.mechanism_macros() == []

    def test_mechanism_reads_that_return_nothing_emit_nothing(self, monkeypatch):
        """Present but empty is a different case from absent, and both must be silent."""
        monkeypatch.setattr(stat_intervals, "harness_cells", lambda *a, **kw: {})
        monkeypatch.setattr(stat_intervals, "occupancy_bounds", lambda *a, **kw: {})
        monkeypatch.setattr(stat_intervals, "load_growth", lambda *a, **kw: {})
        monkeypatch.setattr(stat_intervals, "observer_effect", lambda *a, **kw: {})
        assert epn.mechanism_macros() == []

    def test_a_missing_fork_survey_emits_no_fork_macros(self, monkeypatch):
        """The manuscript's fork sentence is gated on these; with no survey there is no
        sentence, and a count of zero would be a claim the survey never made."""
        monkeypatch.setattr(check_fork_exposure, "read_record", lambda *a, **kw: [])
        assert epn.fork_macros() == []

    def test_a_priority_table_that_cannot_be_rendered_is_reported_not_fatal(self, tmp_path,
                                                                            monkeypatch,
                                                                            capsys):
        """A checkout without the priority campaigns must still build the other tables."""
        monkeypatch.setattr(epn, "render_priority_table",
                            lambda *a, **kw: (_ for _ in ()).throw(OSError("no campaigns")))
        out = tmp_path / "generated"
        epn.main(["--out", str(out / "paper_numbers.tex"),
                  "--table", str(out / "grid_table.tex"),
                  "--registry-table", str(out / "registry_table.tex"),
                  "--priority-table", str(out / "priority_table.tex")])
        printed = capsys.readouterr().out
        assert "priority table not generated" in printed
        assert (out / "paper_numbers.tex").exists()


class TestTheChronyBounds:
    """Section VI-D's three clock numbers, which were right and typed for twenty-nine rounds.

    Round 29 checked `4`--`7`~ms and `12`~ms against the committed `chronyc tracking` captures
    and found all three correct. Correct is a property of this tree; derived is a property of
    every later one, and the function that computes them had been sitting in
    `clock_offset_report` the whole time.
    """

    def test_it_emits_the_range_and_the_worst_pair(self):
        got = dict(epn.chrony_bound_macros())
        assert set(got) == {"chronyHostBoundLo", "chronyHostBoundHi",
                            "chronyPairBound", "chronyHosts"}
        lo, hi = int(got["chronyHostBoundLo"]), int(got["chronyHostBoundHi"])
        assert 0 < lo <= hi
        assert int(got["chronyHosts"]) >= 2

    def test_the_pair_is_the_two_worst_hosts_not_twice_the_range(self):
        """The distinction the prose now makes: adding the printed endpoints gives a different
        and larger number, which is what a reader would otherwise compute."""
        got = dict(epn.chrony_bound_macros())
        hi, pair = int(got["chronyHostBoundHi"]), int(got["chronyPairBound"])
        assert pair <= 2 * hi
        assert pair >= hi, "the worst pair includes the worst host"

    def test_a_missing_capture_directory_emits_nothing(self, tmp_path):
        assert epn.chrony_bound_macros(path=str(tmp_path / "absent")) == []

    def test_one_host_is_not_a_pair(self, tmp_path):
        """A pair bound needs two hosts; one capture is not a claim about disagreement."""
        (tmp_path / "only.txt").write_text(
            "Root delay      : 0.004000000 seconds\n"
            "Root dispersion : 0.001000000 seconds\n", encoding="utf-8")
        assert epn.chrony_bound_macros(path=str(tmp_path)) == []

    def test_a_capture_without_the_fields_is_skipped(self, tmp_path):
        for name, body in (("a.txt", "Stratum : 3\n"),
                           ("b.txt", "Root delay      : 0.004000000 seconds\n"
                                     "Root dispersion : 0.001000000 seconds\n"),
                           ("c.txt", "Root delay      : 0.006000000 seconds\n"
                                     "Root dispersion : 0.002000000 seconds\n")):
            (tmp_path / name).write_text(body, encoding="utf-8")
        got = dict(epn.chrony_bound_macros(path=str(tmp_path)))
        assert got["chronyHosts"] == "2", "the capture with no bound fields is not a host"
        assert got["chronyPairBound"] == "8"   # (1+2) + (2+3) ms


class TestThePayloadSpanMacros:
    """The payload sweep's endpoints, emitted in round 34 after seventeen typed copies."""

    def test_it_emits_both_precisions_and_the_replication(self):
        got = dict(epn.stat_macros())
        for key in ("payloadTransportFactor", "payloadTransportFactorRound",
                    "payloadRateFall", "payloadRateFallExact", "payloadRhoSpread",
                    "payloadLevels", "payloadReplTransportFactor", "payloadReplRateFall"):
            assert key in got, "%s is not emitted" % key
        assert round(float(got["payloadTransportFactor"])) == \
            float(got["payloadTransportFactorRound"])
        assert float(got["payloadRateFallExact"]) == pytest.approx(
            float(got["payloadRateFall"]), abs=0.05)

    def test_a_missing_primary_campaign_drops_only_its_macros(self, monkeypatch):
        """A checkout without the sweep still emits everything else, as span_macros does."""
        import stat_intervals
        real = stat_intervals.payload_span

        def only_repl(phase=None):
            if phase is None:
                raise OSError("no primary sweep")
            return real(phase)

        monkeypatch.setattr(stat_intervals, "payload_span", only_repl)
        got = dict(epn.stat_macros())
        assert "payloadTransportFactor" not in got
        assert "payloadReplTransportFactor" in got, "the replication is independent"
        assert "tailSlope" in got, "the fit is unaffected"

    def test_a_missing_replication_drops_only_its_macros(self, monkeypatch):
        import stat_intervals
        real = stat_intervals.payload_span

        def only_primary(phase=None):
            if phase is not None:
                raise OSError("no replication sweep")
            return real(phase)

        monkeypatch.setattr(stat_intervals, "payload_span", only_primary)
        got = dict(epn.stat_macros())
        assert "payloadTransportFactor" in got
        assert "payloadReplTransportFactor" not in got


def write_symmetry(path, rows):
    """rows: (condition, median_A_us). The two columns the exposure curve reads."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["condition", "median_A_us"])
        for cond, a in rows:
            w.writerow([cond, a])
    return path


class TestTheExposureCurve:
    """The curve the manuscript quotes in Section VI-B and tabulates in Supplement S48.

    Both come from `_exposure_lags`, which is the point: before round 42 the prose carried
    the numbers as literals and the table computed them, and the two could drift apart
    without anything failing.
    """

    # kafka lags 1500, redis 500 -> typical 1000, hi 1500, lo 500. Chosen so that every
    # emitted quantity is a round number a reader can check by hand.
    BALANCED = [("kafka_n1", 1500), ("kafka_n5", 1500),
                ("redis_n1", 500), ("redis_n5", 500)]

    def test_the_lags_are_the_median_per_broker_and_overall(self, tmp_path):
        p = write_symmetry(tmp_path / "s.csv", self.BALANCED)
        assert epn._exposure_lags(str(p)) == (1000.0, 1500.0, 500.0)

    def test_a_missing_file_yields_nothing_rather_than_zeroes(self, tmp_path):
        """The whole module's rule: refuse to emit rather than emit a confident zero."""
        missing = str(tmp_path / "absent.csv")
        assert epn._exposure_lags(missing) is None
        assert epn.render_exposure_table(missing) == ""

    def test_rows_with_no_measured_lag_are_skipped_and_may_leave_nothing(self, tmp_path):
        """A zero median_A_us is a condition that never recorded an ack lag, not a lag of 0."""
        p = write_symmetry(tmp_path / "z.csv", [("kafka_n1", 0), ("redis_n1", 0)])
        assert epn._exposure_lags(str(p)) is None
        assert epn.render_exposure_table(str(p)) == ""

    def test_a_zero_row_beside_a_real_one_drops_only_the_zero(self, tmp_path):
        p = write_symmetry(tmp_path / "m.csv", [("kafka_n1", 0), ("kafka_n5", 800),
                                                ("redis_n1", 400)])
        assert epn._exposure_lags(str(p)) == (600.0, 800.0, 400.0)

    def test_the_wider_lag_is_hi_whichever_broker_carries_it(self, tmp_path):
        """hi and lo are the ends of the gap, not the brokers. Reversing which client
        stamps late must not reverse the sign of the reported gap."""
        p = write_symmetry(tmp_path / "r.csv", [("kafka_n1", 500), ("redis_n1", 1500)])
        typical, hi, lo = epn._exposure_lags(str(p))
        assert (hi, lo) == (1500.0, 500.0)

    @pytest.mark.parametrize("broker", ["kafka", "redis"])
    def test_one_broker_alone_falls_back_to_the_overall_median(self, tmp_path, broker):
        """With nothing to compare against there is no gap, so both ends are the median.

        Parametrized over which broker is the one present: the two fallbacks are separate
        expressions, and a corpus missing Kafka exercises a different one from a corpus
        missing Redis.
        """
        p = write_symmetry(tmp_path / "k.csv", [(broker + "_n1", 900), (broker + "_n5", 900)])
        assert epn._exposure_lags(str(p)) == (900.0, 900.0, 900.0)

    def test_the_macros_are_the_arithmetic_the_prose_quotes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        d = tmp_path / "docs" / "results"
        d.mkdir(parents=True)
        write_symmetry(d / "span_symmetry.csv", self.BALANCED)
        got = dict(epn.exposure_macros())
        # error is typical/T_true: 1000us against 10ms is 10%, against 100ms is 1%,
        # against 1ms is 100%. The gap at 10ms is 1-(10000-1500)/(10000-500) = 10.5%.
        assert got == {"exposureErrTen": "10", "exposureErrHundred": "1",
                       "exposureErrOne": "100", "exposureGapTen": "11",
                       "exposureCrossover": "1.00"}

    def test_the_macros_are_absent_rather_than_wrong_when_the_data_is(self, tmp_path,
                                                                     monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert epn.exposure_macros() == []

    def test_the_table_reaches_below_the_crossover(self, tmp_path):
        """The round-42 finding: the table used to start at 1ms and render everything
        below it as a dash, hiding the regime published sub-millisecond medians sit in."""
        p = write_symmetry(tmp_path / "s.csv", self.BALANCED)
        table = epn.render_exposure_table(str(p))
        assert "$0.25$~ms" in table and "$0.5$~ms" in table
        assert "---" not in table, "a dash hides the rows where the error exceeds 100%"
        # below the crossover the displacement is larger than the path
        assert "$400$" in table, "0.25ms against a 1000us lag is a 400% error"



class TestTheLadderRefusesRatherThanGuesses:
    """The refusal paths of disease_macros and _recovery_macros.

    These are the branches that decline to emit when the ledger cannot support a number.
    They are the module's reason for existing -- the campaign counts went stale in eleven
    places at once because something was willing to write a plausible value -- and nothing
    was exercising them.
    """

    FIELDS = ("n_events", "neg_ack", "over_0.1", "over_0.5", "over_1")

    def _ladder(self, path, rows):
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(self.FIELDS)
            for r in rows:
                w.writerow(r)
        return str(path)

    def test_an_absent_ledger_emits_nothing(self, tmp_path):
        assert epn.disease_macros(str(tmp_path / "absent.csv")) == []

    def test_a_header_with_no_runs_emits_nothing(self, tmp_path):
        assert epn.disease_macros(self._ladder(tmp_path / "d.csv", [])) == []

    def test_runs_that_recorded_no_events_emit_nothing(self, tmp_path):
        """Zero events is not zero percent; it is no denominator."""
        p = self._ladder(tmp_path / "d.csv", [(0, 0, 0, 0, 0), (0, 0, 0, 0, 0)])
        assert epn.disease_macros(p) == []

    def test_the_top_rung_must_equal_the_sign_count(self, tmp_path):
        """alpha = 1 IS the sign check, so a ladder disagreeing with the negative count
        means one of the two is wrong and neither should reach the manuscript."""
        p = self._ladder(tmp_path / "d.csv", [(100, 7, 40, 20, 9)])
        with pytest.raises(ValueError, match="ladder top rung"):
            epn.disease_macros(p)

    def test_the_recovery_estimator_is_absent_rather_than_wrong(self, tmp_path):
        assert epn._recovery_macros(str(tmp_path / "absent.csv")) == []


class TestTheRecoveryMacrosDeclineRatherThanInvent:
    """The other half of every guard in `_recovery_macros`.

    Run against the real corpus each quantity is measurable, so the arms that refuse were
    dead in practice. A refusal path that has never run is not a safeguard, it is an
    assumption.
    """

    COLS = ("condition", "recovery_err_us", "median_D_us", "rho_DA",
            "median_A_us", "median_S_us")

    def _sym(self, path, rows):
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(self.COLS)
            for r in rows:
                w.writerow(r)
        return str(path)

    def test_a_corpus_with_nothing_measurable_emits_nothing(self, tmp_path):
        """No gate outcome in the condition name, no delivery, no rho, no lag."""
        p = self._sym(tmp_path / "s.csv", [("kafka_n1", 0, 0, "nan", "", 0)])
        assert epn._recovery_macros(p) == []

    def test_an_empty_rho_column_is_not_a_rho_of_zero(self, tmp_path):
        p = self._sym(tmp_path / "s.csv", [("kafka_n1", 0, 0, "", "", 0)])
        assert "spanRhoMedian" not in dict(epn._recovery_macros(p))

    def test_the_gap_needs_both_brokers(self, tmp_path):
        """One broker is not a comparison, so no distortion factor is emitted."""
        p = self._sym(tmp_path / "s.csv", [("kafka_n1", 1, 10, "0.5", "700", 5)])
        got = dict(epn._recovery_macros(p))
        assert "ackLagMedianUs" in got and "reportedFraction" in got
        assert "gapTrue" not in got and "gapDistortion" not in got

    def test_a_zero_reported_span_blocks_the_ratio_rather_than_dividing_by_it(self, tmp_path):
        """redis reports a median span of zero: the reported gap is undefined, not infinite."""
        p = self._sym(tmp_path / "s.csv", [("kafka_n1", 1, 10, "0.5", "700", 5),
                                           ("redis_n1", 1, 5, "0.5", "500", 0)])
        got = dict(epn._recovery_macros(p))
        assert "gapTrue" not in got, "a gap was emitted from a zero denominator"

    def test_the_bootstrap_skips_degenerate_resamples(self, tmp_path):
        """With one of redis's two spans at zero, some resamples have a zero median and
        cannot contribute a ratio. They are dropped, and the interval comes from the rest."""
        p = self._sym(tmp_path / "s.csv", [("kafka_n1", 1, 10, "0.5", "700", 5),
                                           ("kafka_n5", 1, 10, "0.5", "700", 5),
                                           ("redis_n1", 1, 5, "0.5", "500", 0),
                                           ("redis_n5", 1, 5, "0.5", "500", 4)])
        got = dict(epn._recovery_macros(p))
        assert "gapDistortion" in got
        assert "$--$" in got["gapDistortionCI"]

    def test_a_ladder_without_the_alpha_columns_emits_only_the_counts(self, tmp_path):
        """The over_* columns are optional; their absence must not fabricate a rung."""
        p = tmp_path / "d.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(("n_events", "neg_ack"))
            w.writerow((100, 7))
        got = dict(epn.disease_macros(str(p)))
        assert got["diseaseEvents"] == "100"
        assert not [k for k in got if k.startswith("diseaseOver")]


class TestTheDepositedVersionIsRead:
    """`artifact_macros` names the release the archive is deposited under.

    It exists because the version was typed into the manuscript and went stale the moment a
    new version was deposited: v2.7.0 was published carrying a PDF that said v2.6.0.
    """

    def _write(self, path, **fields):
        import json
        path.write_text(json.dumps(fields), encoding="utf-8")
        return str(path)

    def test_the_version_comes_from_the_deposit_metadata(self, tmp_path):
        code = self._write(tmp_path / "z.json", version="9.9.9")
        data = self._write(tmp_path / "zd.json", version="9.9.9")
        assert epn.artifact_macros(code, data) == [("artifactVersion", "9.9.9")]

    def test_absent_metadata_emits_nothing(self, tmp_path):
        """A checkout without the deposit files still builds; the manuscript's own gates are
        what forbid quoting a macro that was never emitted."""
        assert epn.artifact_macros(str(tmp_path / "gone.json")) == []

    def test_metadata_without_a_version_emits_nothing(self, tmp_path):
        code = self._write(tmp_path / "z.json", title="no version here")
        assert epn.artifact_macros(code) == []

    def test_a_missing_sibling_is_not_a_disagreement(self, tmp_path):
        """Only the code record is required; the data record may not be checked out."""
        code = self._write(tmp_path / "z.json", version="1.2.3")
        assert epn.artifact_macros(code, str(tmp_path / "absent.json")) == \
            [("artifactVersion", "1.2.3")]

    def test_the_two_records_may_not_disagree(self, tmp_path):
        """They are deposited as a pair. Publishing 2.7.0 code beside 2.6.0 data would put
        two versions of one release in front of a reader who follows the cross-reference."""
        code = self._write(tmp_path / "z.json", version="2.7.0")
        data = self._write(tmp_path / "zd.json", version="2.6.0")
        with pytest.raises(ValueError, match="disagree on the version"):
            epn.artifact_macros(code, data)


class TestWhatTheGuardDeletesIsEmitted:
    """The deletion figure's headline, so the supplement can state it rather than plot it.

    The counts are exact arithmetic on the joined corpus; the interval is a cluster bootstrap
    over runs, read from the committed uncertainty audit rather than recomputed, because two
    implementations of one resampling scheme drift.
    """

    def _stats(self, path, **ms):
        import json
        path.write_text(json.dumps({"spans": {"ack": {"ms_rule": ms}}}), encoding="utf-8")
        return str(path)

    def _audit(self, path, row="msGuardDeletionPct (fig. deletion_histogram)",
               interval="[45.4%, 46.2%]"):
        path.write_text(
            "quantity,value,class,interval_95,method,note\n"
            '%s,45.8%%,added-here,"%s",boot,note\n' % (row, interval), encoding="utf-8")
        return str(path)

    def test_the_counts_and_the_fraction_come_from_the_corpus(self, tmp_path):
        s = self._stats(tmp_path / "s.json", total=1000, dropped=458, kept=542,
                        at_zero=400, below_zero=58)
        a = self._audit(tmp_path / "a.csv")
        got = dict(epn.deletion_macros(s, a))
        assert got["msGuardDropped"] == "458"
        assert got["msGuardKept"] == "542"
        assert got["msGuardAtZero"] == "400"
        assert got["msGuardBelowZero"] == "58"
        assert got["msGuardDeletedPct"] == "45.8"
        assert got["msGuardDeletedCI"] == "45.4$--$46.2"

    def test_absent_stats_emit_nothing(self, tmp_path):
        assert epn.deletion_macros(str(tmp_path / "gone.json")) == []

    def test_stats_without_the_millisecond_rule_emit_nothing(self, tmp_path):
        import json
        p = tmp_path / "s.json"
        p.write_text(json.dumps({"spans": {"ack": {}}}), encoding="utf-8")
        assert epn.deletion_macros(str(p)) == []

    def test_an_empty_corpus_emits_nothing_rather_than_dividing_by_it(self, tmp_path):
        s = self._stats(tmp_path / "s.json", total=0, dropped=0, kept=0,
                        at_zero=0, below_zero=0)
        assert epn.deletion_macros(s) == []

    def test_the_counts_still_emit_when_the_audit_is_absent(self, tmp_path):
        """The interval is a nicety; the counts are the claim."""
        s = self._stats(tmp_path / "s.json", total=100, dropped=46, kept=54,
                        at_zero=40, below_zero=6)
        got = dict(epn.deletion_macros(s, str(tmp_path / "no-audit.csv")))
        assert got["msGuardDeletedPct"] == "46.0"
        assert "msGuardDeletedCI" not in got

    def test_an_audit_without_the_row_yields_no_interval(self, tmp_path):
        s = self._stats(tmp_path / "s.json", total=100, dropped=46, kept=54,
                        at_zero=40, below_zero=6)
        a = self._audit(tmp_path / "a.csv", row="somethingElse")
        assert "msGuardDeletedCI" not in dict(epn.deletion_macros(s, a))
