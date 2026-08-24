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

import emit_paper_numbers as epn  # noqa: E402
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

    def test_a_missing_registry_yields_no_macros_rather_than_wrong_ones(self, monkeypatch):
        import harness_registry
        monkeypatch.setattr(harness_registry, "summary",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))
        assert epn.registry_macros() == []

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
        keys = macro[len("\cite{"):-1].split(",")
        assert len(keys) == len(rows), (len(keys), len(rows))
        assert keys == [epn.REGISTRY_CITES[h] for h, _ in rows]

    def test_the_supplement_caption_uses_the_generated_list(self):
        """A hand-written \cite list beside "generated at build time" is the round-7 bug."""
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
