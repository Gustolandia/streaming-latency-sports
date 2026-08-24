"""Tests for scripts/figure_vocabulary.py - target 100% branch coverage.

Round 18's referee found four axis labels reading "inversion rate" after the manuscript had
renamed that quantity to "negative span". Two figure gates were already in place and neither
could see it: one measures how large the type is, the other what is drawn through it. Nothing
read what the type said.

The property this gate holds is narrow and worth stating exactly: **a term is policed only
once the manuscript has stopped using it.** That is what stops the rule rotting into a list of
forbidden strings nobody revisits -- retiring a term in the prose is what arms the check, and
while the prose still uses the term the check is deliberately inert. Both directions are
pinned below, because a gate that fires on everything and a gate that fires on nothing are
equally useless and look identical from a passing suite.
"""
import sys
from pathlib import Path

import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import figure_vocabulary as fv  # noqa: E402


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


@pytest.fixture
def manuscript(tmp_path):
    """A pair of stand-in sources, so the tests never depend on the real manuscript's state."""
    def write(paper="", supplement=""):
        (tmp_path / "paper.tex").write_text(paper, encoding="utf-8")
        (tmp_path / "supplement.tex").write_text(supplement, encoding="utf-8")
        return str(tmp_path)
    return write


def _fig(*labels):
    fig, ax = plt.subplots(figsize=(3, 2))
    if labels:
        ax.set_xlabel(labels[0])
    if len(labels) > 1:
        ax.set_ylabel(labels[1])
    if len(labels) > 2:
        ax.set_title(labels[2])
    return fig


class TestManuscriptUses:

    def test_it_counts_every_inflection(self, manuscript):
        """A term is not retired while "inversions" or "inversion rate" survives anywhere."""
        root = manuscript(paper="the inversion rate", supplement="two inversions")
        assert fv.manuscript_uses("inversion", root=root) == 2

    def test_it_ignores_case(self, manuscript):
        root = manuscript(paper="Inversion at the start of a sentence")
        assert fv.manuscript_uses("inversion", root=root) == 1

    def test_a_term_the_manuscript_has_dropped_counts_zero(self, manuscript):
        root = manuscript(paper="the negative-span rate", supplement="negative spans")
        assert fv.manuscript_uses("inversion", root=root) == 0

    def test_a_source_that_does_not_exist_contributes_nothing(self, tmp_path):
        """A checkout without the supplement must not make every term look retired."""
        (tmp_path / "paper.tex").write_text("inversion", encoding="utf-8")
        assert fv.manuscript_uses("inversion", root=str(tmp_path)) == 1

    def test_it_matches_on_a_word_boundary(self, manuscript):
        """"Subversion" is not "inversion"."""
        root = manuscript(paper="subversion of the schedule")
        assert fv.manuscript_uses("inversion", root=root) == 0

    def test_an_absolute_source_path_is_used_as_given(self, tmp_path):
        p = tmp_path / "elsewhere.tex"
        p.write_text("inversion", encoding="utf-8")
        assert fv.manuscript_uses("inversion", sources=(str(p),), root="/nonexistent") == 1


class TestRetiredTerms:

    def test_a_term_the_prose_still_uses_is_not_retired(self, manuscript):
        """The check must be inert before the rename lands, or it blocks the rename itself."""
        root = manuscript(paper="the inversion rate")
        assert fv.retired_terms(root=root) == ()

    def test_a_term_the_prose_has_dropped_is_retired(self, manuscript):
        root = manuscript(paper="the negative-span rate")
        assert fv.retired_terms(root=root) == (("inversion", "negative span"),)

    def test_the_committed_manuscript_has_retired_the_term(self):
        """The rename landed, so the gate is armed on the real sources."""
        assert ("inversion", "negative span") in fv.retired_terms()


class TestFigureTexts:

    def test_it_collects_the_labels(self):
        got = fv.figure_texts(_fig("x label", "y label", "a title"))
        for s in ("x label", "y label", "a title"):
            assert s in got

    def test_blank_strings_are_not_text(self):
        fig, ax = plt.subplots(figsize=(3, 2))
        ax.set_xlabel("   ")
        assert "" not in fv.figure_texts(fig)
        assert "   " not in fv.figure_texts(fig)

    def test_a_repeated_string_is_reported_once(self):
        fig, ax = plt.subplots(figsize=(3, 2))
        ax.set_xlabel("same")
        ax.set_ylabel("same")
        assert fv.figure_texts(fig).count("same") == 1

    def test_an_invisible_label_is_not_text(self):
        """Hidden artists print nothing, so they cannot mislead a reader."""
        fig, ax = plt.subplots(figsize=(3, 2))
        ax.set_xlabel("hidden")
        ax.xaxis.label.set_visible(False)
        assert "hidden" not in fv.figure_texts(fig)

    def test_whitespace_is_normalised(self):
        """A label broken over two lines is one string to a reader."""
        got = fv.figure_texts(_fig("negative-span\nrate"))
        assert "negative-span rate" in got


class TestOffending:

    def test_a_figure_using_the_retired_term_is_reported(self, manuscript):
        root = manuscript(paper="the negative-span rate")
        found = fv.offending(_fig("inversion rate (Wilson 95% interval)"), root=root)
        assert len(found) == 1
        assert found[0]["term"] == "inversion"
        assert found[0]["replacement"] == "negative span"
        assert "inversion rate" in found[0]["text"]

    def test_the_replacement_term_is_not_reported(self, manuscript):
        root = manuscript(paper="the negative-span rate")
        assert fv.offending(_fig("negative-span rate"), root=root) == []

    def test_nothing_is_reported_while_the_prose_still_uses_the_term(self, manuscript):
        """The exact case that must stay quiet: mid-rename, with both names in play."""
        root = manuscript(paper="the inversion rate")
        assert fv.offending(_fig("inversion rate"), root=root) == []

    def test_it_finds_the_term_wherever_it_sits(self, manuscript):
        root = manuscript(paper="negative span")
        found = fv.offending(_fig("x", "Inversion rate per run", "t"), root=root)
        assert len(found) == 1

    def test_every_offending_string_is_listed(self, manuscript):
        root = manuscript(paper="negative span")
        found = fv.offending(_fig("inversion rate", "inversion count"), root=root)
        assert len(found) == 2

    def test_report_wraps_the_same_answer(self, manuscript):
        root = manuscript(paper="negative span")
        got = fv.report(_fig("inversion rate"), root=root)
        assert list(got) == ["retired"]
        assert len(got["retired"]) == 1


class TestCheck:

    def test_a_clean_figure_passes(self, manuscript):
        root = manuscript(paper="negative span")
        fv.check(_fig("negative-span rate"), "clean", root=root)

    def test_a_figure_with_a_retired_term_raises(self, manuscript):
        root = manuscript(paper="negative span")
        with pytest.raises(fv.FigureUsesRetiredTerm) as excinfo:
            fv.check(_fig("inversion rate"), "mechanism_forest", root=root)
        message = str(excinfo.value)
        assert "mechanism_forest" in message
        assert "inversion" in message
        assert "negative span" in message, "the message must say what to use instead"

    def test_the_message_is_truncated_when_a_figure_is_full_of_them(self, manuscript):
        root = manuscript(paper="negative span")
        fig, ax = plt.subplots(figsize=(3, 2))
        for i in range(10):
            ax.text(0.1, 0.05 * i, "inversion %d" % i)
        with pytest.raises(fv.FigureUsesRetiredTerm) as excinfo:
            fv.check(fig, "busy", root=root)
        assert "and 2 more" in str(excinfo.value)

    def test_it_is_silent_before_the_rename_lands(self, manuscript):
        root = manuscript(paper="the inversion rate")
        fv.check(_fig("inversion rate"), "mid-rename", root=root)


class TestTheCommittedFiguresAreClean:
    """The gate is wired into both `_save` paths, so this is belt and braces -- but the
    figures on disk were built before it existed, and this is what says they were rebuilt."""

    def test_no_built_figure_carries_the_retired_term(self):
        pdfs = sorted((Path(__file__).parent.parent.parent / "docs" / "results"
                       / "figures").glob("*.pdf"))
        if not pdfs:
            pytest.skip("no figures built")
        pypdf = pytest.importorskip("pypdf")
        bad = []
        for path in pdfs:
            text = " ".join(p.extract_text() for p in pypdf.PdfReader(str(path)).pages)
            for term, _ in fv.retired_terms():
                if term.lower() in text.lower():
                    bad.append("%s says %r" % (path.name, term))
        assert not bad, "figures still carrying a retired term: %s" % bad


class TestTheRealFiguresPassTheirOwnGate:
    """Built through the real `_save`, which is where the gate is actually wired.

    The synthetic figures above prove the rule and `TestTheCommittedFiguresAreClean` proves
    what is already on disk. Neither runs the real builders, so a reverted axis label survives
    both: mutation testing put "inversion rate" back into three labels and this module stayed
    green. These are the tests that fail.
    """

    RESULT_BUILDERS = ("build_deletion", "build_spectrum", "build_grid", "build_mechanism",
                       "build_ttrue", "build_payload", "build_priority_ladder")

    @pytest.mark.parametrize("builder", RESULT_BUILDERS)
    def test_a_result_figure_builds_without_a_retired_term(self, builder, tmp_path):
        import make_result_figures as mrf
        getattr(mrf, builder)(str(tmp_path))

    def test_every_paper_figure_builds_without_a_retired_term(self, tmp_path):
        import make_paper_figures as mpf
        mpf.main(["--out", str(tmp_path)])

    def test_the_builder_list_is_the_whole_set(self):
        """A new figure added without a line here would never be checked."""
        import make_result_figures as mrf
        declared = {n for n in dir(mrf) if n.startswith("build_")}
        assert declared == set(self.RESULT_BUILDERS)


class TestMain:

    def test_it_reports_a_clean_set(self, tmp_path, capsys, monkeypatch):
        import make_paper_figures as mpf
        import make_result_figures as mrf
        for name in ("build_deletion", "build_spectrum", "build_grid", "build_mechanism",
                     "build_ttrue", "build_payload", "build_priority_ladder"):
            monkeypatch.setattr(mrf, name,
                                lambda out_dir: mrf._save(_fig("negative-span rate"),
                                                          out_dir, "stub"))
        monkeypatch.setattr(mpf, "main",
                            lambda argv: mpf._save(_fig("negative-span rate"), None, "paper"))
        assert fv.main(["--out", str(tmp_path / "v")]) == 0
        assert "0 figure(s)" in capsys.readouterr().out

    def test_it_reports_and_fails_on_a_dirty_one(self, tmp_path, capsys, monkeypatch):
        import make_paper_figures as mpf
        import make_result_figures as mrf
        for name in ("build_deletion", "build_spectrum", "build_grid", "build_mechanism",
                     "build_ttrue", "build_payload", "build_priority_ladder"):
            monkeypatch.setattr(mrf, name,
                                lambda out_dir: _fig("negative-span rate"))
        monkeypatch.setattr(mpf, "main", lambda argv: None)
        # One figure reaches the inspector carrying the old name.
        monkeypatch.setattr(mrf, "build_grid",
                            lambda out_dir: mrf._save(_fig("inversion rate"),
                                                      out_dir, "grid_membership"))
        assert fv.main(["--out", str(tmp_path / "v")]) == 1
        out = capsys.readouterr().out
        assert "grid_membership" in out
        assert "1 figure(s)" in out

    def test_it_says_so_and_stops_when_no_term_is_retired(self, tmp_path, capsys,
                                                          monkeypatch):
        """Before a rename lands there is nothing to police, and building every figure to
        discover that would be a minute of work for no answer."""
        monkeypatch.setattr(fv, "retired_terms", lambda *a, **kw: ())
        assert fv.main(["--out", str(tmp_path / "v")]) == 0
        assert "arms itself when a rename lands" in capsys.readouterr().out

    def test_it_puts_back_the_save_functions_it_replaced(self, tmp_path, monkeypatch):
        import make_paper_figures as mpf
        import make_result_figures as mrf
        before = (mrf._save, mpf._save)
        for name in ("build_deletion", "build_spectrum", "build_grid", "build_mechanism",
                     "build_ttrue", "build_payload", "build_priority_ladder"):
            monkeypatch.setattr(mrf, name, lambda out_dir: None)
        monkeypatch.setattr(mpf, "main", lambda argv: None)
        fv.main(["--out", str(tmp_path / "v")])
        assert (mrf._save, mpf._save) == before

    def test_they_are_put_back_even_when_a_builder_raises(self, tmp_path, monkeypatch):
        import make_paper_figures as mpf
        import make_result_figures as mrf
        before = (mrf._save, mpf._save)
        monkeypatch.setattr(mrf, "build_deletion", lambda out_dir: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            fv.main(["--out", str(tmp_path / "v")])
        assert (mrf._save, mpf._save) == before
