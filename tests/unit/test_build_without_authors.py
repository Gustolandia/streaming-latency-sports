"""Tests for scripts/build_without_authors.py - target 100% branch coverage.

From 2026-09-09 every PDF that leaves the repository goes without an author list: the Zenodo
record's files and anything sent as an attachment. The author list is not settled, and a
circulated PDF is a durable public statement of authorship that a later correction does not
catch up with.

What is worth testing is not that pdflatex runs -- it does, and the build script's own
`--check` says so -- but the two decisions the script encodes. **What comes out**: the byline,
its affiliation footnotes and the author biographies. **What stays**: the acknowledgment, and
the two names that are credits rather than claims. A test that only counted removals would
pass on a script that stripped the acknowledgment too, which would erase a debt rather than a
claim.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import build_without_authors as bwa  # noqa: E402

REPO = SCRIPTS_DIR.parent


AUTHOR_BLOCK = r"""\author{Gustavo~Pedro~Ricou,~Romaric~Duvignau%
\thanks{G.~P.~Ricou is with Trinity College Dublin (e-mail: a@b.ie; c@d.ie).}
\thanks{R.~Duvignau is with Chalmers.}}
"""

SAMPLE = (r"\documentclass{IEEEtran}" + "\n" + AUTHOR_BLOCK +
          r"\begin{document}\maketitle Body text." + "\n"
          r"\begin{IEEEbiographynophoto}{Gustavo Pedro Ricou}" + "\n"
          r"He is a Software Engineer." + "\n"
          r"\end{IEEEbiographynophoto}" + "\n"
          r"\begin{IEEEbiographynophoto}{Romaric Duvignau}" + "\n"
          r"He is an Associate Professor." + "\n"
          r"\end{IEEEbiographynophoto}" + "\n"
          r"\end{document}")


class TestStrippingTheAuthorBlock:
    """The block is brace-matched, because a lazy regex stops inside an e-mail address."""

    def test_the_byline_and_its_footnotes_go_together(self):
        out, removed = bwa._strip_author_block(SAMPLE)
        assert "\\author{}" in out
        assert "Ricou" not in out.split("\\begin{document}")[0]
        assert "Chalmers" not in out
        assert "Trinity College Dublin" not in out

    def test_the_removed_text_is_returned_for_inspection(self):
        _, removed = bwa._strip_author_block(SAMPLE)
        assert removed.startswith("\\author{") and "Duvignau" in removed

    def test_a_lazy_match_would_have_stopped_early(self):
        """The defect this brace matching exists for, stated as a test.

        `\\author{...}` closes after three nested `\\thanks`, and the first `}` in the string
        is the one ending the first thanks' e-mail parenthesis. A regex terminated on the
        first brace leaves two affiliations and half a byline in the document.
        """
        first_brace = SAMPLE.index("}", SAMPLE.index("\\author{"))
        assert "Chalmers" in SAMPLE[first_brace:], \
            "the sample no longer exercises the nesting this test is about"
        out, _ = bwa._strip_author_block(SAMPLE)
        assert "Chalmers" not in out

    def test_the_body_survives_untouched(self):
        out, _ = bwa._strip_author_block(SAMPLE)
        assert "Body text." in out and "\\begin{document}" in out


class TestStrippingTheBiographies:
    def test_every_biography_environment_goes(self):
        out = bwa._strip_biographies(SAMPLE)
        assert "IEEEbiographynophoto" not in out
        assert "Software Engineer" not in out and "Associate Professor" not in out

    def test_a_document_without_biographies_is_unchanged(self):
        text = r"\documentclass{IEEEtran}\begin{document}Body.\end{document}"
        assert bwa._strip_biographies(text) == text


class TestPrepare:
    def test_it_writes_a_stripped_copy_beside_the_original(self, temp_dir):
        src = temp_dir / "src"
        src.mkdir()
        (src / "paper.tex").write_text(SAMPLE, encoding="utf-8", newline="")
        out = temp_dir / "out"
        out.mkdir()
        target, removed = bwa.prepare("paper", source_dir=str(src), out_dir=str(out))
        written = Path(target).read_text(encoding="utf-8")
        assert "Ricou" not in written and "IEEEbiographynophoto" not in written
        assert "Duvignau" in removed
        assert (src / "paper.tex").read_text(encoding="utf-8") == SAMPLE, \
            "prepare must not touch the submission source"


class TestTheRealSourcesStrip:
    """The script is only worth anything if it works on this repository's actual documents."""

    @pytest.mark.parametrize("name", ("paper", "supplement"))
    def test_the_committed_source_loses_every_author_name(self, name, temp_dir):
        target, _ = bwa.prepare(name, out_dir=str(temp_dir))
        text = Path(target).read_text(encoding="utf-8")
        front = text.split("\\begin{document}")[0]
        for surname in bwa.AUTHOR_NAMES:
            assert surname not in front, \
                "%s survives in %s's front matter" % (surname, name)

    def test_the_paper_keeps_its_acknowledgment(self, temp_dir):
        target, _ = bwa.prepare("paper", out_dir=str(temp_dir))
        text = Path(target).read_text(encoding="utf-8")
        assert "Acknowledgment" in text or "ACKNOWLEDGMENT" in text.upper(), \
            "the acknowledgment thanks people for specific help and must survive"

    def test_the_paper_keeps_its_title_and_abstract(self, temp_dir):
        target, _ = bwa.prepare("paper", out_dir=str(temp_dir))
        text = Path(target).read_text(encoding="utf-8")
        assert "Faster-than-Light" in text
        assert "\\begin{abstract}" in text


class TestOffendingNames:
    def test_a_clean_document_reports_nothing(self, monkeypatch, temp_dir):
        pdf = temp_dir / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Result(0, "no names here"))
        assert bwa.offending_names(str(pdf)) == []

    def test_an_author_surname_is_reported(self, monkeypatch, temp_dir):
        pdf = temp_dir / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: _Result(0, "by G. P. Ricou and N. Herbst"))
        assert bwa.offending_names(str(pdf)) == ["Herbst", "Ricou"]

    def test_the_allowed_credits_do_not_count(self, monkeypatch, temp_dir):
        """`Brendan Gregg` is cited work and `N. Herbst raised the comparison` is a credit.

        Neither asserts authorship, and a checker that flagged them would push an author into
        deleting a citation to satisfy a byline rule.
        """
        pdf = temp_dir / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        text = ("Brendan Gregg reported it as bimodal. "
                "N. Herbst raised the comparison.")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Result(0, text))
        assert bwa.offending_names(str(pdf)) == []


class _Result:
    def __init__(self, returncode, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class TestMain:
    def test_check_reports_clean_when_both_are_clean(self, monkeypatch, temp_dir, capsys):
        for name in ("paper", "supplement"):
            (temp_dir / (name + ".pdf")).write_bytes(b"%PDF-1.4")
        monkeypatch.setattr(bwa, "offending_names", lambda p: [])
        assert bwa.main(["--check", "--out", str(temp_dir)]) == 0
        assert capsys.readouterr().out.count("clean") == 2

    def test_check_fails_when_a_name_survives(self, monkeypatch, temp_dir, capsys):
        for name in ("paper", "supplement"):
            (temp_dir / (name + ".pdf")).write_bytes(b"%PDF-1.4")
        monkeypatch.setattr(bwa, "offending_names", lambda p: ["Ricou"])
        assert bwa.main(["--check", "--out", str(temp_dir)]) == 1
        assert "STILL NAMES Ricou" in capsys.readouterr().out

    def test_a_missing_pdf_is_a_failure_and_says_so(self, temp_dir, capsys):
        assert bwa.main(["--check", "--out", str(temp_dir)]) == 1
        assert "missing" in capsys.readouterr().out

    def test_an_unverifiable_build_is_reported_not_hidden(self, monkeypatch, temp_dir,
                                                          capsys):
        """No `pdftotext` means the promise is unchecked, and the output must say so rather
        than print "clean" on the strength of not having looked."""
        for name in ("paper", "supplement"):
            (temp_dir / (name + ".pdf")).write_bytes(b"%PDF-1.4")
        monkeypatch.setattr(bwa, "offending_names", lambda p: None)
        assert bwa.main(["--check", "--out", str(temp_dir)]) == 0
        out = capsys.readouterr().out
        assert "not verified" in out and "clean" not in out

    def test_without_check_it_builds(self, monkeypatch, temp_dir, capsys):
        built = []

        def fake_build(out_dir):
            built.append(out_dir)
            paths = []
            for name in ("paper", "supplement"):
                p = temp_dir / (name + ".pdf")
                p.write_bytes(b"%PDF-1.4")
                paths.append(str(p))
            return paths

        monkeypatch.setattr(bwa, "build", fake_build)
        monkeypatch.setattr(bwa, "offending_names", lambda p: [])
        assert bwa.main(["--out", str(temp_dir)]) == 0
        assert built == [str(temp_dir)]


class TestBuildOrchestration:
    """`build` shells out four times per document; the orchestration is what is checked."""

    def test_it_prepares_both_and_moves_both_pdfs(self, monkeypatch, temp_dir):
        calls = []

        def fake_run(cmd, cwd):
            calls.append(cmd[0])
            stem = cmd[-1].replace(".tex", "")
            Path(cwd, stem + ".pdf").write_bytes(b"%PDF-1.4")
            for ext in (".aux", ".log"):
                Path(cwd, stem + ext).write_text("x", encoding="utf-8")
            return 0

        monkeypatch.setattr(bwa, "_run", fake_run)
        out = bwa.build(str(temp_dir))
        assert [Path(p).name for p in out] == ["paper.pdf", "supplement.pdf"]
        assert all(Path(p).exists() for p in out)
        assert calls.count("pdflatex") == 8 and calls.count("bibtex") == 2
        # Nothing staged is left behind in the repository root.
        assert not list(REPO.glob("_noauth_*")), "the staged build files were not cleaned up"

    def test_the_helper_that_shells_out_returns_the_code(self):
        assert bwa._run([sys.executable, "-c", "raise SystemExit(3)"], str(REPO)) == 3
