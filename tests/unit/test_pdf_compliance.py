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
    # Comments are not index terms. Round 34 put a two-line note inside the block explaining
    # a change to it, and this check read the note as two more terms and failed on their
    # ordering -- pointing at the comment, not at the terms, which cost a round-trip to
    # understand. A block comment is a normal thing to write; the reader of it is what was
    # wrong.
    body = re.sub(r"(?m)%[^\n]*", "", m.group(1))
    terms = [t.strip().rstrip(".") for t in body.split(";") if t.strip()]
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


# --- structure of the submission package -----------------------------------------------------

def test_supplement_section_labels_sit_on_their_headings():
    """A \\label{sec:...} must directly follow a sectioning command.

    Round 7 inserted two paragraphs immediately after their section headings, which pushed
    each section's existing lead below the newcomer and stranded the \\label mid-section.
    Nothing broke -- the labels were unreferenced -- but the reader met an example before the
    frame, twice, and the round-8 review had to find it by eye. A stranded label is the
    mechanical signature of that insertion pattern, so it is the thing pinned.
    """
    src = (ROOT / "supplement.tex")
    if not src.exists():
        pytest.skip("supplement not present")
    lines = src.read_text(encoding="utf-8").split("\n")
    stranded = []
    for i, line in enumerate(lines):
        if not re.match(r"\\label\\{sec:", line.strip()):
            continue
        j = i - 1
        while j >= 0 and (not lines[j].strip() or lines[j].strip().startswith("%")):
            j -= 1
        prev = lines[j].strip()
        if not prev.startswith(("\\section", "\\subsection", "\\paragraph")):
            stranded.append("%s (line %d, preceded by %r)" % (
                line.strip(), i + 1, prev[:40]))
    assert not stranded, "labels stranded below inserted content:\n  " + "\n  ".join(stranded)


@pytest.mark.parametrize("name", ("paper", "supplement"))
def test_bibtex_ran_clean(name):
    """The build's BibTeX logs must carry no warnings.

    Round 7 entered IEEE Std 1241 as `@standard`, which IEEEtran.bst half-understands:
    "Warning--missing institution" in the log and a dangling "Std.," in the rendered entry.
    A one-warning log is exactly the kind of blemish that survives because nothing reads
    logs; this reads the log.
    """
    blg = ROOT / ("%s.blg" % name)
    if not blg.exists():
        pytest.skip("no BibTeX log for %s" % name)
    warnings = [l for l in blg.read_text(encoding="utf-8", errors="ignore").splitlines()
                if l.startswith("Warning--")]
    assert not warnings, "%s.blg: %s" % (name, warnings)


@pytest.mark.parametrize("name", ["paper", "supplement"])
def test_no_font_shape_is_substituted(name):
    """The LaTeX log must record no font substitution.

    IEEEtran sets a table caption in small caps and Times has no small-caps italic, so every
    \\emph inside one asked for `T1/ptm/m/scit` and was quietly given `T1/ptm/m/it`
    instead -- eleven times across the two documents, and in the log every time.

    What the substitution produced was in fact what was wanted, which is the reason to gate
    it rather than to leave it: the appearance of the page was being decided by a fallback
    rule rather than by the source, and a fallback is only right by accident. Ask for the
    shape you want.
    """
    log = ROOT / ("%s.log" % name)
    if not log.exists():
        pytest.skip("no LaTeX log for %s; build it first" % name)
    lines = log.read_text(encoding="utf-8", errors="ignore").splitlines()
    warnings = [l.strip() for l in lines if "Font Warning" in l]
    assert not warnings, "%s.log requests font shapes it cannot have:\n  %s" % (
        name, "\n  ".join(sorted(set(warnings))))


def test_figure_text_layers_carry_no_unmapped_symbol():
    """A glyph with no Arial form falls back, renders correctly, and extracts as nonsense.

    Figure 1's headline once read "...written by two threads $\\Rightarrow$ it can come out
    negative", which drew correctly and extracted as "...two threads ) it can come out
    negative" -- the sentence a screen reader, a search index or a reviewer copying text would
    receive. The Type 3 and family gates both passed it, because the fallback face is an
    embedded CID font on the permitted list. Only the text layer shows the damage.

    The check is deliberately narrow: an isolated bracket surrounded by spaces is not something
    a figure label produces on purpose, and it is what this class of failure leaves behind.
    """
    offenders = {}
    for pdf in sorted(FIGDIR.glob("*.pdf")):
        text = _text(pdf)
        # Both brackets. The round-12 version of this test excused " ( " on the theory
        # that axis labels produce it legitimately, citing window_sweep.pdf -- which
        # turned out to be a second instance of this very defect, a mathtext \propto
        # falling back to Computer Modern. The exception was a description of the bug.
        for artifact in (" ) ", " ( ", "\ufffd"):
            if artifact in text:
                offenders.setdefault(pdf.name, set()).add(artifact.strip() or "U+FFFD")
    assert not offenders, \
        "figure text layers carry unmapped-glyph artifacts: %s" % offenders


def test_no_figure_falls_back_to_computer_modern():
    """No figure needs a Computer Modern glyph, so none should embed one.

    The family gate permits cm* faces because IEEE's list ends in "Symbol" and TeX's symbol
    complement fills that role. That remains true for the documents. For the *figures* it is
    now a dead allowance: both users of it -- a double arrow in Figure 1, a proportional-to in
    the window sweep -- were glyphs with no Arial form, and both rendered correctly while
    extracting as punctuation. Neither was visible to the Type 3 check or the family check.

    Holding the figure set to Arial alone converts that whole class from "caught after the
    fact by reading the text layer" into "cannot be introduced".
    """
    offenders = {}
    for pdf in sorted(FIGDIR.glob("*.pdf")):
        for face, _ in _fonts(pdf):
            stem = face.split("+")[-1].lower()
            if stem.startswith(("cm", "stix")):
                offenders.setdefault(pdf.name, set()).add(face)
    assert not offenders, (
        "figures fall back to a TeX symbol face: %s. A glyph with no Arial form renders "
        "correctly and extracts as punctuation; say it in words instead." % offenders)


def test_every_figure_is_used_or_declared():
    """A figure is either included by a document or declared in the artifact index.

    Three of the fifteen are included by neither, which is a defensible choice -- they are
    outputs of a committed generator and the campaigns behind them are still archived -- but
    it should be a stated choice rather than a thing a reader discovers. The index names each
    one and why it is kept, and this test makes a fourth impossible to add silently.
    """
    index = ROOT / "docs" / "supplement_index.md"
    if not index.exists():
        pytest.skip("artifact index absent")
    declared = index.read_text(encoding="utf-8")
    used = set()
    for doc in ("paper.tex", "supplement.tex"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        used |= {Path(m).stem for m in
                 re.findall(r"\\includegraphics\[[^\]]*\]\{([^}]*)\}", text)}
    undeclared = [p.stem for p in sorted(FIGDIR.glob("*.pdf"))
                  if p.stem not in used and ("`%s`" % p.stem) not in declared]
    assert not undeclared, (
        "figures neither included nor declared in docs/supplement_index.md: %s" % undeclared)


def test_the_inventory_figure_numbers_are_current():
    """"main text, Fig. N" in the artifact index must be the number the paper prints.

    Round 13 added the inventory and gated the figure *names*; round 14 observed that the
    numbers beside them were hand-typed and unchecked. Insert a float ahead of another and the
    index sends a reader to the wrong panel -- the same failure the supplement's float-pointer
    gate exists to prevent, one document across.
    """
    index = ROOT / "docs" / "supplement_index.md"
    aux = ROOT / "paper.aux"
    if not index.exists() or not aux.exists():
        pytest.skip("artifact index or paper.aux absent")

    printed = {}
    for label, num in re.findall(r"\\newlabel\{(fig:[^}]*)\}\{\{([^}]*)\}",
                                 aux.read_text(encoding="utf-8", errors="replace")):
        printed[label] = num

    # the figure a generator writes, keyed by the label the paper gives it
    stem_of_label = {}
    paper = (ROOT / "paper.tex").read_text(encoding="utf-8")
    # figure* as well as figure: three floats became full-width in round 16 and an
    # unstarred-only pattern reported that the paper had stopped carrying them.
    for block_ in re.findall(r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", paper, re.S):
        g = re.search(r"\\includegraphics\[[^\]]*\]\{([^}]*)\}", block_)
        lab = re.search(r"\\label\{(fig:[^}]*)\}", block_)
        if g and lab:
            stem_of_label[Path(g.group(1)).stem] = lab.group(1)

    bad = []
    for stem, claimed in re.findall(r"\|\s*`([a-z0-9_]+)`\s*\|\s*main text, Fig\.\s*(\d+)",
                                    index.read_text(encoding="utf-8")):
        label = stem_of_label.get(stem)
        if label is None:
            bad.append("%s: index says the main text carries it, the paper does not" % stem)
        elif printed.get(label) != claimed:
            bad.append("%s: index says Fig. %s, paper prints Fig. %s"
                       % (stem, claimed, printed.get(label)))
    assert not bad, "stale figure numbers in the artifact index:\n  " + "\n  ".join(bad)


#: How loose a line may be before it is a visible defect rather than a typesetting nicety.
#: TeX reports 10000 for a line it stretched as far as it is willing to go; in a two-column
#: IEEE measure that is a river of white space a reader sees before they read a word.
UNDERFULL_BADNESS_CEILING = 10000


def _before_the_bibliography(text):
    """The log up to the point LaTeX opened the `.bbl`, or all of it if it never did.

    This used to be `text.split(".bbl")[0]`, and round 48 found that the split had silently
    stopped working for the supplement. **LaTeX hard-wraps its log at 79 columns, and the
    wrap can fall inside a filename.** This build wrote

        ... [49] [50] (supplement.
        bbl [51]

    so the literal `.bbl` does not occur anywhere in the file, `split` returned the whole
    log, and every loose line in the bibliography was counted against the body -- which the
    docstring below explicitly says they must not be. `paper.log` was unaffected only
    because its wrap happened to fall elsewhere, so the bug was invisible in one of the two
    documents it applies to.

    Searching a newline-stripped copy and mapping the offset back is what makes the marker
    findable wherever the wrap lands.
    """
    keep = [i for i, ch in enumerate(text) if ch != "\n"]
    at = "".join(text[i] for i in keep).find(".bbl")
    return text if at == -1 else text[:keep[at]]


class TestTheBibliographyIsFoundWhereverTheLogWrapsIt:
    """The scoping helper, against the wrap that defeated its predecessor.

    Round 48: the supplement's log wrote `(supplement.` at the end of one line and `bbl` at
    the start of the next, so `".bbl" in text` was false and the bibliography was never
    excluded. One loose URL then failed a gate that exists to ignore loose URLs.
    """

    def test_an_unwrapped_marker_is_found(self):
        """Cuts at the same place the old `split(".bbl")[0]` did, so nothing else moves."""
        text = "body line\n(paper.bbl [12]\nUnderfull \\hbox (badness 10000)\n"
        assert _before_the_bibliography(text) == text.split(".bbl")[0]
        assert "Underfull" not in _before_the_bibliography(text)

    def test_a_marker_split_by_the_column_wrap_is_found(self):
        """The exact shape LaTeX produced: the wrap falls between "." and "bbl"."""
        text = "body line\n[49] [50] (supplement.\nbbl [51]\nUnderfull \\hbox (badness 10000)\n"
        head = _before_the_bibliography(text)
        assert "Underfull" not in head
        assert head.startswith("body line")

    def test_a_wrap_inside_the_stem_is_also_found(self):
        """The wrap can land anywhere, not only before the extension."""
        text = "body\n(suppleme\nnt.bbl [51]\nUnderfull \\hbox (badness 10000)\n"
        assert "Underfull" not in _before_the_bibliography(text)

    def test_a_log_with_no_bibliography_keeps_all_of_itself(self):
        text = "body\nUnderfull \\hbox (badness 10000) in paragraph at lines 1--2\n"
        assert _before_the_bibliography(text) == text

    def test_the_real_logs_lose_their_bibliographies(self):
        for name in ("paper", "supplement"):
            log = ROOT / ("%s.log" % name)
            if not log.exists():
                pytest.skip("no LaTeX log for %s" % name)
            text = log.read_text(encoding="utf-8", errors="ignore")
            head = _before_the_bibliography(text)
            assert len(head) < len(text), (
                "%s.log: the bibliography was not found, so its loose URLs are being "
                "counted against the body" % name)


@pytest.mark.parametrize("name", ["paper", "supplement"])
def test_no_line_is_stretched_to_the_limit(name):
    """The LaTeX log must record no underfull box at maximum badness.

    Overfull boxes were gated from early on and underfull ones never were, so for
    thirty-nine rounds the compliance table carried a column for one and nothing for the
    other. A referee reading the rendered PDF in round 40 found fifteen lines at badness
    10000 -- six of them in a single paragraph of Section IV-A -- which is what the missing
    column had been hiding.

    The cause is worth naming here because it will recur: `\texttt` tokens that TeX may
    neither hyphenate nor break, in a column too narrow to hold them.
    `TimeUnit.MILLISECONDS.toMicros(now - publishTimestamp)` is one word to TeX, and a line
    containing it is stretched around it. The repair is to permit breaks inside such tokens
    (see `\brk` in the preamble), NOT to relax the paragraph with \sloppy -- that trades a
    defect you can see for one spread thinly over the whole document.

    Lower-badness underfulls are left alone deliberately. They are ordinary consequences of
    a narrow measure and gating them would produce noise rather than findings.
    """
    log = ROOT / ("%s.log" % name)
    if not log.exists():
        pytest.skip("no LaTeX log for %s; build it first" % name)
    text = log.read_text(encoding="utf-8", errors="ignore")
    # The BODY only. Reference entries carry long URLs that cannot break except at their
    # slashes, so a two-column bibliography produces loose lines in every IEEE paper that
    # cites a repository; ten of them survive here and are not a defect of this manuscript.
    #
    # Scoping the sweep is not the same as lowering the bar to meet the result, and the
    # distinction matters enough to record: the round-40 report claimed six boxes in a
    # paragraph of Section IV-A, and that was WRONG. The line numbers belong to paper.bbl,
    # which LaTeX was reading at the time, and the offending text was "Apache Pulsar
    # contributors, PerformanceConsumer.java ... https://github.com/apache/pulsar". Five
    # boxes really were in the body, from unbreakable 	exttt identifiers, and those are
    # what rk fixed. A referee reading a log without checking which file its line numbers
    # index is making the same error as a reader trusting a benchmark's own output.
    head = _before_the_bibliography(text)
    worst = re.findall(
        r"Underfull \\hbox \(badness (\d+)\) in paragraph at lines ([\d]+--[\d]+)", head)
    offenders = sorted({loc for badness, loc in worst
                        if int(badness) >= UNDERFULL_BADNESS_CEILING})
    assert not offenders, (
        "%s.log: %d line(s) stretched to badness %d, in paragraphs at %s. Allow breaks "
        "inside the long \texttt tokens there rather than reaching for \sloppy."
        % (name, len(offenders), UNDERFULL_BADNESS_CEILING, ", ".join(offenders)))


@pytest.mark.parametrize("name", ["paper", "supplement"])
def test_breakable_spans_carry_no_spaces(name):
    r"""`\brk` is a url-style command, and those SILENTLY DROP SPACES.

    Round 40 introduced \brk to let TeX break long identifiers and applied it, among others,
    to `\brk{if (endToEndLatencyMicros > 0)}` -- a guard quoted from the audited benchmark's
    source. It rendered as `if (endToEndLatencyMicros>0)`. The spaces either side of the
    comparison were gone, and a line of somebody else's source, which this paper offers as
    evidence, had been silently altered by a typesetting macro.

    Nothing else would have caught it. The build is clean, the gates were green, and the text
    layer reads plausibly unless you are looking for the spaces. So the rule is mechanical:
    \brk takes identifiers, never fragments. Anything with a space stays in \texttt and finds
    another way to fit.
    """
    src = (ROOT / ("%s.tex" % name)).read_text(encoding="utf-8")
    offenders = [m for m in re.findall(r"\brk\{([^}]*)\}", src) if " " in m]
    assert not offenders, (
        "%s.tex: \brk would drop the spaces in %s. Use \texttt for anything containing a "
        "space -- a url-style command is not a verbatim." % (name, offenders))
