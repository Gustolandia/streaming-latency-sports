r"""Defects that exist only after the artists are placed, or only after LaTeX numbers a label.

Three classes, all found in round 44 by reading the built PDF rather than the source, and all
invisible to every gate that reads `.tex`.

**A cross-reference to a `\paragraph`.** IEEEtran numbers a paragraph inside a subsection as
"0a", so `\ref{sec:metrics}` renders as "Section III-A0a". There is no Section III-A0a. Two
were in the build: one pre-existing, one introduced by the round-43 edit that named `t_out`,
which is to say the round that fixed a dangling pointer created one.

**A sentence opening on a lowercase word.** A macro expanding to "five" lands at the head of a
sentence and the source still looks right. The project already generates a capitalised twin
for every such macro -- `\harnessSilentWordCap` is "Five" -- and the one place that needed it
was not using it.

**A generated macro no document reads.** Round 29's reason for generating them at all: "A
generated file carrying macros nobody reads is a place for a stale number to survive a
revision." Sixty-six of two hundred and seventy-five were unread when this was written. Most
are deliberate -- the `Word`/`WordCap` pairs exist so a number can open a sentence, and
keeping both halves is right even when one is idle. So this is an inventory with a ceiling
rather than a prohibition: the count may not grow without someone looking.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
PDFS = ("paper.pdf", "supplement.pdf")

#: Lowercase words that may legitimately open a fragment after a full stop.
CONTINUATIONS = ("e.g", "i.e", "vs", "cf", "pp", "vol")

#: Tokens whose trailing full stop is an abbreviation rather than a sentence end.
ABBREVIATIONS = frozenset((
    "al", "eg", "ie", "cf", "vs", "fig", "figs", "sec", "eq", "eqs", "no", "vol",
    "pp", "ref", "refs", "approx", "resp", "cs", "st", "ca", "dr", "prof", "inc",
))

#: What the unused-macro inventory stands at. A ceiling, not a target: it may fall freely and
#: may not rise without the reason being written down. It was 66 when round 44 first counted
#: it, and 64 after that round quoted the exposure lag and its percentiles; the four macros
#: round 44 added are all read.
#:
#: 66 again since round 60, and the reason is written down. `\tailSlope` and `\tailSlopeCI`
#: were read by exactly one paragraph -- the payload-sweep withdrawal -- and that paragraph
#: went to Supplement S15 with the rest of the archaeology, where the same fit is stated as
#: `\tailExponent` with the sign in the notation. They keep being emitted because they still
#: have a consumer that is not a document: `test_figure_ledger_agreement` checks the
#: experiment map's "slope 0.34" against `\tailSlope`, so deleting the macro would delete
#: the check that keeps a drawn number and the ledger in step.
UNUSED_MACRO_CEILING = 66


def rendered(name):
    path = REPO / name
    if not path.is_file():
        pytest.skip("%s not built" % name)
    out = subprocess.run(["pdftotext", "-q", "-nopgbrk", str(path), "-"],
                         capture_output=True, text=True, errors="replace")
    if out.returncode != 0:
        pytest.skip("pdftotext unavailable")
    return re.sub(r"\s+", " ", out.stdout)


class TestNoPointerLandsOnAParagraph:
    r"""`\ref` to a `\paragraph` renders as a section number that does not exist."""

    @pytest.mark.parametrize("name", PDFS)
    def test_no_section_pointer_carries_a_paragraph_suffix(self, name):
        bad = sorted(set(re.findall(r"Section[s]?~?\s+([IVX]+-[A-Z]\d[a-z])", rendered(name))))
        assert not bad, (
            "%s points at %s, which IEEEtran prints for a label sitting on a \\paragraph. "
            "A reader has no such section to find; point at the enclosing subsection."
            % (name, ", ".join(bad)))

    def test_the_check_would_fire_on_the_defect_it_was_written_for(self):
        """Round 44's two, reconstructed, so the rule is known to have teeth."""
        pat = re.compile(r"Section[s]?~?\s+([IVX]+-[A-Z]\d[a-z])")
        assert pat.findall("A fifth is consumer-internal (Section III-A0a).") == ["III-A0a"]
        assert pat.findall("Over the campaign of Section IV-B0a that silence") == ["IV-B0a"]
        assert not pat.findall("the audit of Section IV-D reads ten tools at source")


class TestNoSentenceOpensOnALowercaseWord:
    """A macro at the head of a sentence, in the one place the source cannot show it."""

    @staticmethod
    def offenders(text):
        out = []
        for m in re.finditer(r"(\w+)\.\s+([a-z]{2,})\s+(\w+\s+\w+\s+\w+)", text):
            before, word = m.group(1).lower(), m.group(2)
            # A stop that is not a sentence end: "et al.", "e.g.", "Fig. 3", "No. 4".
            if before in ABBREVIATIONS or word.lower().startswith(CONTINUATIONS):
                continue
            out.append("%s %s" % (word, m.group(3)))
        return out

    @pytest.mark.parametrize("name,expected", [("paper.pdf", 0), ("supplement.pdf", 0)])
    def test_the_known_offenders_are_gone(self, name, expected):
        """Not a general grammar check: a two-column reflow puts a continued sentence at the
        head of a line and this sweep cannot tell that from a real one. So it pins the three
        found in round 44 by their own text, and leaves the sweep to `test_the_sweep_still_sees`.
        """
        text = rendered(name)
        known = ("benchmark. five of the ten",
                 "not documented. the main text recovers",
                 "load model. the main text shows")
        found = [k for k in known if k in text]
        assert not found, "round 44's sentence-case defects are back: %s" % found

    def test_the_sweep_still_sees_the_shape(self):
        assert self.offenders("classified the benchmark. five of the ten dispose of it")
        assert not self.offenders("the rate fell 4.1x. The direction Equation 3 predicts here")
        assert not self.offenders("cited by Villain et al. and by Paxson in the same year")


class TestTheGeneratedLedgerIsRead:
    """Macros emitted and quoted nowhere."""

    @staticmethod
    def unused():
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex")
        if not gen.exists():                            # pragma: no cover - built by CI
            pytest.skip("paper_numbers.tex absent; run emit_paper_numbers.py")
        names = re.findall(r"\\newcommand\{\\(\w+)\}", gen.read_text(encoding="utf-8"))
        docs = ((REPO / "paper.tex").read_text(encoding="utf-8")
                + (REPO / "supplement.tex").read_text(encoding="utf-8"))
        return sorted(n for n in names
                      if not re.search(re.escape("\\" + n) + r"(?![A-Za-z])", docs))

    def test_the_unread_inventory_does_not_grow(self):
        unused = self.unused()
        assert len(unused) <= UNUSED_MACRO_CEILING, (
            "%d generated macros are read by neither document, up from %d. Either quote the "
            "new ones or stop emitting them: %s"
            % (len(unused), UNUSED_MACRO_CEILING, ", ".join(unused[:8])))

    def test_the_lag_the_exposure_curve_rests_on_is_printed(self):
        """M1's smallest symptom. The curve in Section VI-B is one number wearing nine rows,
        and that number was emitted and shown to nobody."""
        assert r"\ackLagMedianUs" not in self.unused(), \
            "the median acknowledgment lag must appear where the exposure curve is introduced"


#: Greek control words, and what each looks like once an escape has eaten its first letter.
#: `\rho` written through a shell that interprets `\r` becomes a carriage return plus `ho`;
#: `\tau` becomes a tab plus `au`; `\nu`, `\alpha`, `\beta` and `\f...` all have the shape.
#: Round 56 found two live instances in the built supplement -- "k/ho" on page 17 and "a
#: function of ho" on page 18 -- which every gate in the repository had passed, because LaTeX
#: typesets `ho` in math mode without complaint and no check asked whether a math span was
#: what its author meant.
GREEK_NAMES = (
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa",
    "lambda", "mu", "nu", "xi", "pi", "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi",
    "omega", "Delta", "Sigma", "Omega", "Gamma", "Lambda", "Theta", "Phi", "Psi",
)

#: Every distinct tail of two letters or more, longest first so a report names the longest
#: match. One-letter tails are dropped: "u" and "i" occur inside ordinary words and the
#: false-positive rate would swamp the signal the check exists for.
GREEK_TAILS = tuple(sorted({g[1:] for g in GREEK_NAMES if len(g) > 2},
                           key=len, reverse=True))


class TestNoControlWordLostItsBackslash:
    r"""A `\rho` whose backslash was eaten prints as the word `ho`, and compiles cleanly.

    This is the project's documented shell trap arriving in the manuscript: a heredoc that
    interprets escape sequences turns `\rho` into a newline and the letters `ho`. LaTeX is no
    help -- `$k/` newline `ho$` is valid math -- and neither is the reference gate, the
    vocabulary gate or the collision gate. It reached the printed page and stayed there for
    the rounds between the edit that made it and the referee who read the PDF.

    Both halves are checked, because either alone can be evaded: the source, which is where
    the repair goes, and the built document, which is what a reader holds.
    """

    @staticmethod
    def source_offenders():
        out = []
        for name in ("paper.tex", "supplement.tex"):
            path = REPO / name
            if not path.exists():                       # pragma: no cover - both are tracked
                continue
            text = path.read_text(encoding="utf-8").replace("\r", "")
            for n, line in enumerate(text.split("\n"), 1):
                stripped = line.lstrip()
                for tail in GREEK_TAILS:
                    if re.match(re.escape(tail) + r"[$\s}]", stripped):
                        out.append("%s:%d starts on %r, the tail of a Greek name"
                                   % (name, n, tail))
                        break
        return out

    @staticmethod
    def rendered_offenders():
        out = []
        for name in PDFS:
            text = rendered(name)
            for tail in GREEK_TAILS:
                if re.search(r"(?<![A-Za-z])" + re.escape(tail) + r"(?![A-Za-z])", text):
                    out.append("%s prints %r as a word" % (name, tail))
        return out

    def test_the_source_carries_no_orphaned_control_word(self):
        offenders = self.source_offenders()
        assert not offenders, "; ".join(offenders)

    def test_the_built_documents_print_no_orphaned_control_word(self):
        offenders = self.rendered_offenders()
        assert not offenders, "; ".join(offenders)

    def test_the_check_would_have_caught_round_56(self):
        """Mutation: the line as it stood, and as it now stands."""
        broken = "ho$ rather than from a shape description"
        assert any(re.match(re.escape(t) + r"[$\s}]", broken) for t in GREEK_TAILS)
        fixed = r"\rho$ rather than from a shape description"
        assert not any(re.match(re.escape(t) + r"[$\s}]", fixed) for t in GREEK_TAILS)


class TestAWrappedMathSpanDoesNotResumeOnBareLetters:
    r"""The source signature of the defect above, checked where the repair goes.

    Round 56's referee asked for a stricter rule than this one -- that no inline `$...$` span
    be broken across a line at all, "since that is the exact signature". It is not, and the
    corpus says so: the supplement wraps `$\approx` before `0.54$` and `$D = t_{\mathrm{recv}}
    -` before `t_{\mathrm{send}}$`, both legitimate and both flagged by that rule. A gate that
    would force those to reflow is a gate someone eventually turns off.

    What is exact is the shape the trap leaves. `\rho` losing its backslash-r puts a newline
    in front of the bare letters `ho`, so the continuation line is *nothing but letters* up to
    the closing dollar. The legitimate wraps never are: they resume on a digit, an operator or
    a control sequence, and `t_{\mathrm{send}}$` resumes on a letter that is followed by a
    subscript rather than by the dollar. So the rule is narrower than the referee's and true,
    which is the trade this project makes every time.
    """

    #: A continuation that is only letters, then the end of the span. `ho$`, `au$`, `lpha$`.
    BARE_RESUMPTION = re.compile(r"^[A-Za-z]{2,}\$")

    @staticmethod
    def _open_after(line):
        """True when `line` leaves an inline math span open."""
        # An escaped percent is a character, not a comment. Stripping from the first bare
        # "%" would have eaten the closing dollar of every "$\ombGridRetentionMax\%$".
        bare = re.sub(r"(?<!\\)%.*$", "", line).replace("\\$", "")
        return bare.count("$") % 2 == 1

    @classmethod
    def offenders(cls):
        out = []
        for name in ("paper.tex", "supplement.tex"):
            path = REPO / name
            if not path.exists():                       # pragma: no cover - both are tracked
                continue
            text = path.read_text(encoding="utf-8").replace("\r", "")
            lines = text.split("\n")
            for n, line in enumerate(lines[:-1], 1):
                if not cls._open_after(line):
                    continue
                if cls.BARE_RESUMPTION.match(lines[n].lstrip()):
                    out.append("%s:%d resumes an open math span on bare letters (%r)"
                               % (name, n + 1, lines[n].lstrip()[:12]))
        return out

    def test_no_open_span_resumes_on_bare_letters(self):
        offenders = self.offenders()
        assert not offenders, "; ".join(offenders[:6])

    def test_the_rule_separates_the_defect_from_the_legitimate_wraps(self):
        """Mutation, on the four lines that decided the rule's shape."""
        match = self.BARE_RESUMPTION.match
        assert match("ho$ rather than from a shape description")
        assert match("ho$ alone the model has no content")
        assert not match("0.54$~ms against \\redis{}")
        assert not match("t_{\\mathrm{send}}$ for \\kafka{}")


class TestARunInHeadingDoesNotDoublePunctuate:
    r"""IEEEtran ends a `\paragraph` run-in heading with its own colon.

    Seventy-four of the supplement's hundred and one headings already ended in a full stop, so
    they printed as ".:" -- "The powered measurement.: We measured transport directly". The
    main document had none of them, so the convention was right and only the longer document
    drifted from it, which is the failure mode the project keeps meeting: a rule held in most
    places is invisible to anyone reading linearly.
    """

    @staticmethod
    def source_offenders():
        out = []
        for name in ("paper.tex", "supplement.tex"):
            path = REPO / name
            if not path.exists():                       # pragma: no cover - both are tracked
                continue
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(r"\\paragraph\{([^}]*)\}", text):
                if m.group(1).rstrip().endswith((".", "?", "!")):
                    out.append("%s: %r" % (name, m.group(1)[:60]))
        return out

    def test_no_heading_supplies_the_punctuation_the_class_supplies(self):
        offenders = self.source_offenders()
        assert not offenders, (
            "%d run-in headings end in punctuation the class repeats: %s"
            % (len(offenders), "; ".join(offenders[:4])))

    def test_the_built_documents_print_no_double_punctuation(self):
        for name in PDFS:
            assert ".:" not in rendered(name), \
                "%s prints a full stop followed by a colon" % name


class TestTheTwoDocumentsDoNotShareANumberingSpace:
    r"""A submission is two PDFs, and until round 57 both numbered from one.

    The paper carried Fig. 1--5, Table I--II, equations (1)--(6) and references [1]--[45]; the
    supplement carried Fig. 1--12, Table I--XXVII, (1)--(2) and [1]--[90]. The paper sends a
    reader into the supplement thirty-two times, so the collisions were live rather than
    theoretical: the supplement's Table I is the withdrawn first result set and the paper's is
    the span table; the supplement's Equation 1 is a power-law fit the authors withdrew and the
    paper's is `S = D - A`, the identity the argument turns on; `[12]` is Karimov et al. in one
    document and a practitioner blog post in the other.

    IEEE's convention for supplementary material is the S prefix. This pins it in the built
    PDFs, because a preamble that stops applying is exactly the failure the prefix guards.
    """

    @staticmethod
    def _labels(name, pattern):
        return set(re.findall(pattern, rendered(name)))

    def test_the_supplement_prefixes_every_figure(self):
        assert not self._labels("supplement.pdf", r"Fig\. (\d+)\."), \
            "a supplement figure is numbered in the paper's space"
        assert self._labels("supplement.pdf", r"Fig\. S(\d+)\."), \
            "the supplement has no S-numbered figures; did the preamble stop applying?"

    def test_the_supplement_prefixes_every_table(self):
        romans = self._labels("supplement.pdf", r"TABLE ([IVXLC]+)\b")
        # One reference to the main text's Table I survives by design, in a caption that says
        # so: "this corpus is not the span recount of the main text's Table I". With the
        # supplement's own tables prefixed, that phrase is now unambiguous rather than a
        # collision, which is the whole point of the prefix.
        assert romans <= {"I"}, \
            "a supplement table is numbered in the paper's space: %s" % sorted(romans)
        assert self._labels("supplement.pdf", r"TABLE S(\d+)"), \
            "the supplement has no S-numbered tables"

    def test_the_supplement_prefixes_every_citation(self):
        assert not self._labels("supplement.pdf", r"\[(\d+)\]"), \
            "a supplement citation is numbered in the paper's space"
        assert self._labels("supplement.pdf", r"\[S(\d+)\]"), \
            "the supplement has no S-numbered citations"

    def test_the_paper_keeps_the_plain_numbering(self):
        """The prefix belongs to the supplement alone; the article is the article."""
        assert self._labels("paper.pdf", r"Fig\. (\d+)\."), "the paper's figures lost their numbers"
        assert not self._labels("paper.pdf", r"Fig\. S(\d+)\."), \
            "the paper has picked up the supplement's prefix"


class TestACaptionDoesNotOpenOnAnArticle:
    r"""IEEE Editorial Style Manual: "In general, do not use A, An, or The at the beginning of
    a figure or table caption."

    Round 57 measured the venue before asking for this, because a rule nobody follows is not a
    finding: across 26 TC papers in the reference corpus, 443 captions, 14% open on an article.
    This submission was at 41% -- the paper alone at 57% -- and the cause was a convention
    worth keeping. `test_caption_leads.py` requires every caption to open on its claim rather
    than on a label, and claims start with "The".

    The two rules are compatible, and the IEEE-copy-edited TC paper fetched that round shows it
    in print: its captions are claim sentences with no article. "The traced run-queue stall
    distribution is trimodal" became "Traced run-queue stalls are trimodal" -- shorter, still a
    claim, still bold, still first.
    """

    ARTICLE = re.compile(r"^(A|An|The)\b")

    @staticmethod
    def _leads(path):
        text = (REPO / path).read_text(encoding="utf-8")
        out = []
        for m in re.finditer(r"\\caption\{", text):
            i, depth = m.end(), 1
            while depth and i < len(text):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                i += 1
            body = text[m.end():i - 1]
            bold = re.match(r"\s*\\textbf\{((?:[^{}]|\{[^{}]*\})*)\}", body)
            raw = bold.group(1) if bold else body[:90]
            out.append(" ".join(re.sub(r"\\[a-zA-Z]+\{?|[{}$~\\]", " ", raw).split()))
        return out

    @pytest.mark.parametrize("path", ("paper.tex", "supplement.tex"))
    def test_no_caption_opens_on_an_article(self, path):
        bad = [c for c in self._leads(path) if self.ARTICLE.match(c)]
        assert not bad, ("%d captions in %s open on an article: %s"
                         % (len(bad), path, "; ".join(c[:50] for c in bad[:4])))

    def test_the_check_reads_the_bold_lead_and_not_the_caption_body(self):
        """Mutation: a body sentence starting with "The" is legal and must stay legal."""
        assert self.ARTICLE.match("The traced run-queue stall distribution is trimodal")
        assert not self.ARTICLE.match("Traced run-queue stalls are trimodal")
        assert not self.ARTICLE.match("Theoretical measured values of n")


class TestTheSupplementDoesNotTypeItsPointersIntoThePaper:
    r"""Twenty section pointers were typed constants in a document that loads `xr`.

    `\newcommand{\mainAuthors}{VII-B}`, used thirteen times, and nineteen more like it. All
    twenty were correct when round 57 checked them, which is the point: nothing would have
    said otherwise. Round 56 rewrote Section VI-E and compressed Section VII-A; one added or
    reordered section and thirteen pointers name something else, in a repository whose
    organising rule is that no number is typed.

    They now resolve through `xr`, so `paper.aux` is the source and a renumbering carries.
    """

    def test_every_main_text_pointer_is_a_reference(self):
        text = (REPO / "supplement.tex").read_text(encoding="utf-8")
        typed = [(n, v) for n, v in re.findall(r"\\newcommand\{\\(main\w+)\}\{([^}]*)\}", text)
                 if not v.startswith("\\ref{")]
        assert not typed, \
            ("%d pointers into the main text are typed rather than referenced: %s"
             % (len(typed), ", ".join("%s=%s" % t for t in typed[:5])))

    def test_the_machinery_they_depend_on_is_loaded(self):
        text = (REPO / "supplement.tex").read_text(encoding="utf-8")
        assert "\\usepackage{xr}" in text and "\\externaldocument{paper}" in text, \
            "the pointers resolve through xr; without it they render as ??"

    def test_no_pointer_renders_as_a_question_mark(self):
        """The failure mode of a broken xr link, checked where a reader would meet it."""
        assert "??" not in rendered("supplement.pdf"), \
            "an xr reference did not resolve; build paper.tex before supplement.tex"


class TestANumberedEquationIsReferencedSomewhereInTheSubmission:
    r"""Round 57 asked whether Equation 2 should keep its number, having found no reference to
    it in the paper. It should: the supplement cites it, through the same `xr` link as the
    section pointers, and the submission is both documents.

    That is the rule this pins -- a numbered display must be referenced *somewhere in the
    submission* -- rather than the narrower one that would have unnumbered a definition the
    other half of the submission points at.
    """

    def test_every_numbered_equation_is_referenced(self):
        paper = (REPO / "paper.tex").read_text(encoding="utf-8")
        supp = (REPO / "supplement.tex").read_text(encoding="utf-8")
        both = paper + supp
        labels = re.findall(r"\\label\{(eq:[^}]+)\}", paper)
        assert labels, "the paper has no labelled equations; this pin needs rewriting"
        for label in labels:
            assert re.search(r"\\(?:eq)?ref\{" + re.escape(label) + r"\}", both), \
                ("%s is numbered and referenced by neither document: cite it or unnumber it"
                 % label)
