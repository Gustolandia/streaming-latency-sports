"""What IEEE receives, checked on the bytes rather than on our intention to have set an rcParam.

Round 6 ran `pdffonts` over the built PDFs and found 17 Type 3 fonts in the manuscript and 9 in
the supplement, every one from a figure. Nothing in the project was looking at the PDF's font
table, so a defect that a one-line rcParam fixes had survived six rounds and would have been
found by IEEE PDF eXpress instead of by us.

The same pass found British spelling throughout a journal that mandates American, index terms
in an order the style manual says must be alphabetical, accented author names that extracted as
mojibake, and -- worst of the four -- a figure in the paper that no script in any commit could
rebuild.

Every check below is on the artefact, not on the source that produced it. A test that asserts
`pdf.fonttype == 42` passes while the committed PDF still carries Type 3 from the last build;
a test that reads the PDF does not.
"""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parent.parent.parent
FIGDIR = ROOT / "docs" / "results" / "figures"
DOCS = ("paper.pdf", "supplement.pdf")

pytestmark = pytest.mark.skipif(shutil.which("pdffonts") is None,
                                reason="poppler-utils not installed")


def _fonts(pdf):
    out = subprocess.run(["pdffonts", str(pdf)], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 3:
            rows.append((parts[0], " ".join(parts[1:3])))
    return rows


def _text(pdf):
    return subprocess.run(["pdftotext", "-nopgbrk", "-enc", "UTF-8", str(pdf), "-"],
                          capture_output=True).stdout.decode("utf-8", "replace")


# --- Type 3 ---------------------------------------------------------------------------------

@pytest.mark.parametrize("name", DOCS)
def test_no_type3_fonts_in_the_documents(name):
    """Type 3 embeds glyphs as PostScript drawing operators. It rasterises badly and it is the
    classic PDF eXpress rejection. matplotlib emits it by default; nothing here may."""
    pdf = ROOT / name
    if not pdf.exists():
        pytest.skip("%s not built" % name)
    bad = [f for f, kind in _fonts(pdf) if kind.startswith("Type 3")]
    assert not bad, "%s embeds %d Type 3 font(s): %s" % (name, len(bad), bad)


def test_no_type3_fonts_in_any_figure():
    """Checked per figure as well as per document, so the failure names the figure to rebuild
    rather than leaving the author to bisect eight of them."""
    pdfs = sorted(FIGDIR.glob("*.pdf"))
    if not pdfs:
        pytest.skip("no figures built")
    bad = {p.name: [f for f, k in _fonts(p) if k.startswith("Type 3")] for p in pdfs}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, "figures embedding Type 3: %s" % bad


def test_figure_text_uses_an_ieee_listed_family():
    """IEEE names the acceptable typefaces for text inside graphics: Helvetica, Times New
    Roman, Arial, Cambria, Symbol. matplotlib's DejaVu default is not among them."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import figure_style
    allowed = {n.replace(" ", "").lower() for n in figure_style.IEEE_SANS[:-1]}
    allowed |= {"stixgeneral", "stixnonunicode", "stixsizeonesym", "dejavusans"}
    # TeX's symbol complement -- IEEE's list ends in "Symbol", and Computer Modern's
    # symbol/extension/math-italic faces are what fills that role where a glyph such as
    # a double arrow has no Arial form. Text glyphs never come from these.
    allowed |= {"cmsy10", "cmsy7", "cmsy8", "cmsy9", "cmex10", "cmmi10", "cmmi7", "cmmi8", "cmmi9", "cmr10", "cmr7"}
    offenders = {}
    for p in sorted(FIGDIR.glob("*.pdf")):
        for face, _ in _fonts(p):
            stem = face.split("+")[-1].replace("-", "").replace("MT", "").lower()
            stem = re.sub(r"(regular|italic|bold|oblique|roman)$", "", stem)
            if stem and not any(a.startswith(stem) or stem.startswith(a) for a in allowed):
                offenders.setdefault(p.name, set()).add(face)
    assert not offenders, "figures using a family outside the IEEE list: %s" % offenders


# --- text layer -----------------------------------------------------------------------------

@pytest.mark.parametrize("name", DOCS)
def test_accented_characters_extract_as_characters(name):
    """`Quema` and `Universite` lost their acutes to OT1 encoding: they rendered correctly and
    extracted as mojibake, which breaks copy-paste, indexing and citation linking."""
    pdf = ROOT / name
    if not pdf.exists():
        pytest.skip("%s not built" % name)
    txt = _text(pdf)
    assert "\ufffd" not in txt, "%s has %d unmappable glyph(s) in its text layer" % (
        name, txt.count("\ufffd"))


# --- house style ----------------------------------------------------------------------------

#: Words IEEE's style manual requires in American form. Kept as whole words with their American
#: spelling beside them, rather than as an `-ise -> -ize` regex, because such a regex also
#: rewrites `comprise`, `precise`, `concise`, `promise` and `wise`.
BRITISH = {
    "utilisation": "utilization", "utilised": "utilized", "utilise": "utilize",
    "synchronisation": "synchronization", "synchronised": "synchronized",
    "quantisation": "quantization", "quantised": "quantized",
    "normalised": "normalized", "normalisation": "normalization",
    "randomising": "randomizing", "randomised": "randomized",
    "parameterised": "parameterized", "parameterisation": "parameterization",
    "behaviour": "behavior", "behavioural": "behavioral",
    "artefact": "artifact", "artefacts": "artifacts",
    "modelling": "modeling", "modelled": "modeled",
    "analyse": "analyze", "analysed": "analyzed", "analysing": "analyzing",
    "colour": "color", "centre": "center", "labelled": "labeled",
    # -ise that becomes -ice, not -ize: the morphological rule below would
    # otherwise propose "practized".
    "practise": "practice", "practised": "practiced", "practising": "practicing",
    "summarise": "summarize", "recognise": "recognize", "organisation": "organization",
    "characterise": "characterize", "characterised": "characterized",
    "generalise": "generalize", "generalises": "generalize",
    "minimise": "minimize", "maximise": "maximize", "emphasise": "emphasize",
    "favour": "favor", "honour": "honor", "honours": "honors", "neighbour": "neighbor",
    # Merriam-Webster-first forms round 7 found surviving both rules: -dgement is not
    # an -ise ending, and these stems were simply absent from the table.
    "acknowledgement": "acknowledgment", "acknowledgements": "acknowledgments",
    "judgement": "judgment", "judgements": "judgments",
    "grey": "gray", "cancelled": "canceled", "cancelling": "canceling",
    "neighbouring": "neighboring", "neighbours": "neighbors",
}


#: Words that legitimately end in -ise/-ised/-ising/-isation and must not be rewritten. The
#: list below is the reason this check is not a bare `-ise -> -ize` regex.
NOT_BRITISH = {
    "advertise", "advise", "arise", "chastise", "circumcise", "comprise", "compromise",
    "concise", "demise", "despise", "devise", "disguise", "enterprise", "excise", "exercise",
    "expertise", "franchise", "improvise", "incise", "merchandise", "noise", "otherwise", "paradise", "practise",
    "poise", "praise", "precise", "premise", "promise", "raise", "revise", "rise", "supervise",
    "surmise", "surprise", "televise", "treatise", "wise",
}


def british_forms(text):
    """Every British spelling in `text`, by whichever of the two rules catches it.

    Two rules, because one is not enough. The explicit table catches words whose British form
    is not an `-ise` ending at all -- behaviour, artefact, modelling, centre. The morphological
    rule catches the `-ise` family including inflections, which is what a hand-written table
    keeps missing: the first version of this check listed `summarise` and passed a biography
    containing `summarises`, and listed `specialize` nowhere at all while the same sentence
    said `specialised`.
    """
    found = {}
    for brit, amer in BRITISH.items():
        n = len(re.findall(r"\b%s\b" % brit, text, re.I))
        if n:
            found[brit.lower()] = (n, amer)
    for m in re.finditer(r"\b([a-z]{4,}?is(?:e|es|ed|ing|ation|ations))\b", text, re.I):
        word = m.group(1).lower()
        stem = re.sub(r"is(e|es|ed|ing|ation|ations)$", "ise", word)
        if stem in NOT_BRITISH or word in NOT_BRITISH:
            continue
        if any(word.startswith(w) or w.startswith(word[:6]) for w in NOT_BRITISH
               if len(w) >= 6 and word[:6] == w[:6]):
            continue
        found.setdefault(word, (len(re.findall(r"\b%s\b" % word, text, re.I)),
                                word.replace("is", "iz", 1) if "isation" in word
                                else re.sub(r"is(e|es|ed|ing)$", r"iz\1", word)))
    return found


@pytest.mark.parametrize("name", ("paper.tex", "supplement.tex"))
def test_american_spelling(name):
    """IEEE: "Change all British spellings to American spellings." Both documents go to the
    same copy editor, so both are checked."""
    src = (ROOT / name)
    if not src.exists():
        pytest.skip("%s not present" % name)
    found = british_forms(src.read_text(encoding="utf-8"))
    assert not found, "%s: British spellings -- %s" % (
        name, ", ".join("%s x%d (-> %s)" % (b, n, a) for b, (n, a) in sorted(found.items())))


def test_index_terms_are_alphabetical():
    """IEEE Editorial Style Manual: index terms "appear in alphabetical order and as a final
    paragraph of the Abstract section"."""
    tex = (ROOT / "paper.tex").read_text(encoding="utf-8")
    m = re.search(r"\\begin\{IEEEkeywords\}(.*?)\\end\{IEEEkeywords\}", tex, re.S)
    assert m, "no IEEEkeywords block"
    terms = [t.strip().rstrip(".") for t in m.group(1).split(";") if t.strip()]
    assert len(terms) >= 3, "IEEE recommends a minimum of three index terms"
    lowered = [t.lower() for t in terms]
    assert lowered == sorted(lowered), (
        "index terms are not alphabetical; expected order:\n  %s" % ";\n  ".join(
            t for _, t in sorted(zip(lowered, terms))))


# --- reproducibility ------------------------------------------------------------------------

def test_every_paper_figure_has_a_generator():
    """The one that matters most.

    `payload_flip.pdf` -- Figure 5, the pre-registered payload manipulation -- entered the
    repository as a binary and no script in any commit could rebuild it. The artefact statement
    says every number is recomputed from the committed data by the archived code at build time;
    for one figure that was not true, and the only visible symptom was that it had been built
    by a different matplotlib version from every other figure.
    """
    tex = (ROOT / "paper.tex").read_text(encoding="utf-8")
    stems = {Path(m).stem for m in re.findall(r"\\includegraphics\[[^]]*\]\{([^}]*)\}", tex)}
    assert stems, "no figures found in paper.tex"
    sources = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                        for p in sorted((ROOT / "scripts").glob("*.py")))
    orphans = sorted(s for s in stems if '"%s"' % s not in sources and "'%s'" % s not in sources)
    assert not orphans, (
        "figures in the paper that no script builds: %s" % orphans)
