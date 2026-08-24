r"""Where a citation can live, and what counts as asking whether something is cited.

A round-19 review reported that `btt_inlines` was "cited in neither document", and the claim
was false. The reviewer had scanned `paper.tex` and `supplement.tex`, which is where citations
obviously live, and missed that some of them are emitted: the audited-harness table is
generated from `harness_registry.csv`, and its caption's source list is a `\cite{...}` group
built by `emit_paper_numbers.py` into `docs/generated/paper_numbers.tex`. Every tool in that
table is cited exactly once, through that macro.

The reviewer's instrument was wrong, not the manuscript. That is the same failure the paper
itself is about, so it gets the same treatment as any other: the question "is this cited"
becomes something a machine answers over the whole surface, rather than something a person
answers over the files they happened to think of.

The surface is `paper.tex` + `supplement.tex` + every `.tex` under `docs/generated/`. There is
no rule here against an uncited bibliography entry -- the `.bib` is a working file and holds
more than any one version cites -- but every citation must resolve, every audited harness must
be cited somewhere on the surface, and the reference list the paper actually prints must fit
inside what IEEE Transactions on Computers allows.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

BIB = REPO / "manuscript_references.bib"
GENERATED = REPO / "docs" / "generated"

#: What IEEE Transactions on Computers allows a regular paper. Verified against the journal's
#: Author Information page: "references which are capped at 45".
TC_REFERENCE_CAP = 45


def _bib_keys():
    return set(re.findall(r"@\w+\{([^,]+),", BIB.read_text(encoding="utf-8")))


def _surface():
    """Every file a citation may be written in, generated ones included."""
    out = [REPO / "paper.tex", REPO / "supplement.tex"]
    out += sorted(GENERATED.glob("*.tex"))
    return [p for p in out if p.exists()]


def _cited(paths):
    out = set()
    for p in paths:
        for group in re.findall(r"\\cite\{([^}]*)\}", p.read_text(encoding="utf-8")):
            out.update(k.strip() for k in group.split(",") if k.strip())
    return out


class TestTheSurfaceIsWhatWeThinkItIs:
    """If the surface silently shrank to two files, every check below would still pass and
    would answer a different question -- which is precisely how the wrong answer was got."""

    def test_the_generated_directory_is_part_of_it(self):
        names = {p.name for p in _surface()}
        assert "paper.tex" in names and "supplement.tex" in names
        assert any(p.parent == GENERATED for p in _surface()), \
            "the generated includes carry citations and must be scanned"

    def test_at_least_one_key_is_cited_only_through_a_generated_file(self):
        """The regression pin. This is the case a two-file scan gets wrong.

        If this ever empties it means every citation is now written by hand, and the check
        above stops being load-bearing -- at which point delete both rather than let them
        pass vacuously.
        """
        hand = _cited([REPO / "paper.tex", REPO / "supplement.tex"])
        everywhere = _cited(_surface())
        assert everywhere - hand, (
            "no citation is emitted rather than typed; if that is now true on purpose, this "
            "pin and the one above have nothing left to protect")


class TestEveryCitationResolves:

    def test_no_citation_names_a_missing_entry(self):
        missing = sorted(_cited(_surface()) - _bib_keys())
        assert not missing, "cited but not in the bibliography: %s" % missing

    def test_the_bibliography_parses_to_unique_keys(self):
        raw = re.findall(r"@\w+\{([^,]+),", BIB.read_text(encoding="utf-8"))
        dupes = sorted({k for k in raw if raw.count(k) > 1})
        assert not dupes, "duplicate bibliography keys: %s" % dupes


class TestEveryAuditedHarnessIsCited:
    """Section IV-D reads seven tools at source. A source claim without a source is the
    verifiability gap the paper's own reporting rules tell other people to close."""

    def _registry_cites(self):
        import emit_paper_numbers as epn
        return epn.REGISTRY_CITES

    def test_every_harness_in_the_registry_has_a_citation_key(self):
        import harness_registry
        named = {h for h, _ in harness_registry.paths()}
        mapped = set(self._registry_cites())
        assert named <= mapped, "harness with no citation key: %s" % sorted(named - mapped)

    def test_every_such_key_is_cited_on_the_surface(self):
        cited = _cited(_surface())
        import harness_registry
        named = {h for h, _ in harness_registry.paths()}
        missing = sorted(k for h, k in self._registry_cites().items()
                         if h in named and k not in cited)
        assert not missing, (
            "audited at source and cited nowhere: %s -- the registry has the URL, so this is "
            "a citation the manuscript owes rather than evidence it lacks" % missing)


class TestThePrintedReferenceListFitsTheJournal:

    def test_the_paper_cites_no_more_than_the_cap(self):
        """Counted over what the *paper* cites, since the supplement carries its own list."""
        paper_side = _cited([REPO / "paper.tex"] + sorted(GENERATED.glob("*.tex")))
        # A generated macro may be used by the supplement only; count what paper.tex reaches.
        used = {k for k in paper_side
                if re.search(r"\\cite\{[^}]*\b%s\b" % re.escape(k),
                             (REPO / "paper.tex").read_text(encoding="utf-8"))
                or _macro_reaches_paper(k)}
        assert len(used) <= TC_REFERENCE_CAP, (
            "%d references against a cap of %d" % (len(used), TC_REFERENCE_CAP))

    def test_the_rendered_bibliography_fits_the_cap(self):
        """What the built PDF actually prints, which is the number the editor counts."""
        pdf = REPO / "paper.pdf"
        if not pdf.is_file():
            pytest.skip("paper.pdf not built")
        try:
            out = subprocess.run(["pdftotext", "-q", "-nopgbrk", str(pdf), "-"],
                                 capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):     # pragma: no cover - tool absent
            pytest.skip("pdftotext not available")
        n = len(re.findall(r"^\[\d+\]", out, re.M))
        assert n, "no reference list found in the rendered paper"
        assert n <= TC_REFERENCE_CAP, "%d printed references against a cap of %d" % (
            n, TC_REFERENCE_CAP)


def _macro_reaches_paper(key):
    """Is this key cited through a generated macro that paper.tex uses?"""
    paper = (REPO / "paper.tex").read_text(encoding="utf-8")
    for gen in sorted(GENERATED.glob("*.tex")):
        text = gen.read_text(encoding="utf-8")
        for name, body in re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*\\cite\{[^}]*\}[^}]*)\}",
                                     text):
            if key in body and re.search(r"\\%s\b" % re.escape(name), paper):
                return True
    return False
