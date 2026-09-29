"""Pointers between the documents, which LaTeX cannot check and nobody re-reads.

The manuscript, the supplement and the postmortem are separate compilations, so `\\ref` cannot
reach across them unless `xr` carries it. Every pointer in one document at another is otherwise
a *hand-typed number*, outside every mechanism this project uses to stop numbers drifting.

Round 5 asked for twelve descriptive pointers ("the main text's attribution section") to be
replaced by numbers, and for five unresolvable `\\ref` calls to go. That fix ran a
substitution and left two sentences reading

    Equation~the main text tells a reader where to be careful

which compiled without a warning, rendered without an overfull box, and passed 2,473 tests.
It was found by eye, three rounds later. A third pointer still cited "the main text's
Section~6.2" -- arabic, where the paper numbers in Roman, and pointing at a section number
the paper has not used since the TC restructure.

These are all one defect class: a cross-document pointer that no longer denotes anything.
The checks below read `paper.aux`, which holds the real numbers LaTeX assigned, and hold
every pointer against it. A pointer that resolves to nothing now fails here rather than in
a referee's browser tab.

On 29 September 2026 the supplement became two documents: the journal supplement
(`supplement.tex`, organized by the paper's sections, what the paper points at) and the
postmortem (`postmortem.tex`, the old supplement whole, archived and not submitted). Both reach
into the paper through `xr`, so every rule here that held for the one now holds for both.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
PAPER = REPO / "paper.tex"
SUPP = REPO / "supplement.tex"
POST = REPO / "postmortem.tex"
AUX = REPO / "paper.aux"
COMPANIONS = ("supplement", "postmortem")


def _read(path):
    assert path.exists(), "%s is not present" % path.name
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def paper():
    return _read(PAPER)


@pytest.fixture(scope="module")
def supp():
    return _read(SUPP)


@pytest.fixture(scope="module")
def post():
    return _read(POST)


@pytest.fixture(scope="module")
def docs(paper, supp, post):
    return {"paper": paper, "supplement": supp, "postmortem": post}


@pytest.fixture(scope="module")
def aux():
    """label -> printed number, as LaTeX actually assigned them.

    `\\newlabel{sec:gate}{{\\mbox {III-B}}{3}{...}}` -- the number is the first group, with
    the \\mbox wrapper IEEEtran adds to subsection numbers stripped off.
    """
    assert AUX.exists(), "paper.aux not present; tests/paper_build.py builds it"
    out = {}
    for m in re.finditer(r"\\newlabel\{([^}]*)\}\{\{(.*?)\}\{\d+\}", AUX.read_text(encoding="utf-8")):
        label, printed = m.group(1), m.group(2)
        printed = printed.replace(r"\mbox", "").strip().strip("{}").strip()
        if printed:
            out[label] = printed
    return out


class TestNoStrandedPointer:
    """A float word with no number after it. This is what the round-5 substitution left."""

    # "Equation~the", "Section~ ", "Table~and" -- a pointer word followed by anything that
    # cannot begin a number or a \ref.
    STRANDED = re.compile(
        r"(Equation|Section|Table|Figure|Fig\.|Supplement)~(?!\\ref|\\[a-zA-Z]|[0-9IVXS])")

    @pytest.mark.parametrize("name", ("paper",) + COMPANIONS)
    def test_no_pointer_word_lacks_its_number(self, name, docs):
        text = docs[name]
        hits = []
        for m in self.STRANDED.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append("%s:%d  %r" % (name, line, text[m.start():m.start() + 48]))
        assert not hits, "pointer word with nothing to point at:\n  " + "\n  ".join(hits)


class TestTheCompanionsNameSectionsRatherThanNumberingThem:
    """Main-text section numbers are never written inline in the prose.

    The check below this one asks whether a pointer resolves. That catches the pointer that
    breaks loudly and misses the one that stays valid while changing meaning: folding the
    broker results into the Discussion left four `Section~VI` pointers resolving perfectly to
    a section that was no longer the one they meant. No gate can see that, so the numbers stop
    being written by hand. The postmortem does it through one macro block in its preamble; the
    journal supplement, written after xr was in place, through `\\ref{P-sec:...}` directly.
    """

    @pytest.mark.parametrize("name", COMPANIONS)
    def test_no_section_number_is_written_inline(self, name, docs):
        body = docs[name].split(r"\begin{document}")[-1]
        bad = re.findall(r"Section~[IVX]+(?:-[A-D])?(?![a-zA-Z])", body)
        assert not bad, (
            "these point at the main text by number; use \\ref{P-sec:...} or the macro block "
            "so a renumbering is no edit at all: %s" % sorted(set(bad)))

    def test_the_supplement_reaches_the_papers_sections_by_reference(self, supp):
        body = supp.split(r"\begin{document}")[-1]
        assert re.findall(r"\\ref\{P-sec:[^}]+\}", body), \
            "the supplement must point at the main text's sections somewhere"
        assert not re.search(r"\\newcommand\{\\main[A-Za-z]+\}", supp), (
            "the supplement carries a macro block of main-text sections; it reaches them with "
            "\\ref{P-sec:...}, so a block would only licence names nothing uses")

    def test_every_macro_the_prose_uses_is_defined(self, post):
        defined = set(re.findall(r"\\newcommand\{\\(main[A-Za-z]+)\}", post))
        used = set(re.findall(r"Section~\\(main[A-Za-z]+)", post))
        assert used, "the postmortem must point at the main text somewhere"
        assert used <= defined, "undefined section macros: %s" % sorted(used - defined)

    def test_every_macro_defined_is_used(self, post):
        """A stale entry would quietly licence a number nothing checks."""
        defined = set(re.findall(r"\\newcommand\{\\(main[A-Za-z]+)\}", post))
        used = set(re.findall(r"Section~\\(main[A-Za-z]+)", post))
        assert defined <= used, "defined but never used: %s" % sorted(defined - used)

    def test_no_two_macros_point_at_the_same_section(self, post):
        """Two names for one section is one name too many.

        Round 59 deleted Section V-C and repointed `\\mainGridInference` at `sec:extphase`,
        which `\\mainPhase` already named. Both resolved, both were used, and every existing
        check passed -- while a reader following the two names had no way to know they were
        being sent to the same place. Round 58's referee found it by reading the preamble.
        """
        pairs = re.findall(r"\\newcommand\{\\(main[A-Za-z]+)\}\{\\ref\{([^}]+)\}\}", post)
        seen = {}
        clashes = []
        for name, label in pairs:
            if label in seen:
                clashes.append("%s and %s both name %s" % (seen[label], name, label))
            seen[label] = name
        assert not clashes, "; ".join(clashes)

    def test_the_macros_read_the_paper_instead_of_repeating_it(self, post, paper):
        """Round 57: the values are `\\ref`s now, and that is strictly better than numbers.

        The postmortem loads `xr` and pulls `paper.aux`, so a macro no longer *repeats* the
        paper's numbering, it *reads* it, and a renumbering carries without an edit. What is
        pinned: every macro is a reference, and every label it names is a label the paper
        actually defines.
        """
        # The body is `\ref{...}`, so it carries a nested brace pair: matching to the first
        # `}` would capture `\ref{sec:audit` and report every macro as malformed.
        values = dict(re.findall(r"\\newcommand\{\\(main[A-Za-z]+)\}\{((?:[^{}]|\{[^{}]*\})*)\}",
                                 post))
        assert values, "the macro block must exist"
        labels = set(re.findall(r"\\label\{([^}]+)\}", paper))
        for name, body in sorted(values.items()):
            m = re.match(r"^\\ref\{([^}]+)\}$", body)
            assert m, ("%s holds %r; main-text pointers resolve through xr rather than "
                       "repeating a number by hand" % (name, body))
            # Round 68, W4: xr imports under a `P-` prefix so the 26 citation keys the two
            # documents share stop being reported as multiply defined on every build.
            assert m.group(1).startswith("P-"), (
                "%s points at %r without the xr prefix, so it will resolve to nothing"
                % (name, m.group(1)))
            target = m.group(1)[len("P-"):]
            assert target in labels, \
                "%s points at %r, which paper.tex does not define" % (name, target)

    def test_the_resolved_pointers_are_still_section_numbers(self, post, aux):
        """What the literals used to guarantee, now checked where the reader meets it."""
        values = dict(re.findall(r"\\newcommand\{\\(main[A-Za-z]+)\}\{\\ref\{([^}]+)\}\}",
                                 post))
        assert values, "the macro block must resolve through \\ref"
        for name, label in sorted(values.items()):
            #: The postmortem reads paper.aux through \externaldocument[P-]{paper}, so its
            #: references carry the P- prefix and paper.aux's own labels do not.
            target = label[len("P-"):] if label.startswith("P-") else label
            number = aux.get(target)
            assert number is not None, "%s points at %r, which paper.aux does not define" % (
                name, target)
            assert re.match(r"^[IVX]+(?:-[A-F])?$", number), \
                "%s resolves to %r, which is not a section number" % (name, number)


class TestCompanionsPointAtRealSections:
    """Every "Section~X of the main text" must be a section the main text has."""

    POINTER = re.compile(
        r"(?:main text's Section~|Section~)([IVX]+(?:-[A-D])?|[0-9]+(?:\.[0-9]+)?)"
        r"(?=[^a-zA-Z]|$)")

    @pytest.mark.parametrize("name", COMPANIONS)
    def test_every_pointer_resolves(self, name, docs, aux):
        text = docs[name]
        real = set(aux.values())
        bad = []
        for m in self.POINTER.finditer(text):
            num = m.group(1)
            if num not in real:
                line = text.count("\n", 0, m.start()) + 1
                bad.append("%s:%d  Section~%s (the paper has no such number)" % (name, line, num))
        assert not bad, "\n  " + "\n  ".join(bad)

    @pytest.mark.parametrize("name", COMPANIONS)
    def test_pointers_use_roman_numerals(self, name, docs):
        """The paper numbers sections in Roman. An arabic pointer is a stale one.

        "the main text's Section~6.2" survived the round-5 sweep because the sweep looked for
        descriptive names, and this one was already a number -- just a number from a
        structure two restructures old.
        """
        text = docs[name]
        arabic = []
        for m in re.finditer(r"(?:main text's )?Section~([0-9]+(?:\.[0-9]+)?)", text):
            line = text.count("\n", 0, m.start()) + 1
            arabic.append("%s:%d  Section~%s" % (name, line, m.group(1)))
        assert not arabic, "arabic section pointers:\n  " + "\n  ".join(arabic)


class TestPaperPointsAtRealSupplementSections:
    """Every "Supplement~SNN" must be a section the supplement has.

    The reverse direction of the same defect. Round 3 raised it for the main text and it was
    fixed by hand; nothing has held it since. The paper points at the journal supplement only;
    tests/unit/test_journal_supplement.py holds the subsection numbers and the budget.
    """

    def _supplement_sections(self, supp):
        return {int(n) for n in re.findall(r"^\\section\{S(\d+)[.:]", supp, re.M)}

    def test_every_supplement_pointer_exists(self, paper, supp):
        have = self._supplement_sections(supp)
        assert have, "no S-numbered sections found; the heading pattern changed"
        missing = sorted({int(n) for n in re.findall(r"Supplement~S(\d+)", paper)} - have)
        assert not missing, "paper cites supplement sections that do not exist: %s" % (
            ["S%d" % n for n in missing],)


class TestEveryTargetedRelocationIsReachable:
    """A section created by moving text out of the paper must be reachable from the paper.

    Round 20 moved three passages into S53, S54 and S55 and left two of the three pointers on
    the sections the content had left, so the new sections could not be reached at all. The
    targeted relocations were eight postmortem sections, each a passage lifted out of a
    paragraph that stayed behind:

      S7, S11, S12, S13, S14, S17, S24, S33 (postmortem numbering, v5 of 10 Sep)

    Until 29 September the paper pointed at each directly. Now it points at the journal
    supplement, which carries each one's content in a section the paper points at, and says
    where the full passage is. So the route is: the paper, a journal-supplement section, and
    either a "postmortem, S<n>" pointer or the concordance row in docs/supplement_index.md
    that names the postmortem section as that journal-supplement section's source.
    """

    TARGETED = frozenset({7, 11, 12, 13, 14, 17, 24, 33})

    def _post_sections(self, post):
        return sorted({int(n) for n in re.findall(r"\\section\{S(\d+)\.", post)})

    def _reached(self, supp):
        reached = {int(n) for n in re.findall(r"postmortem, S(\d+)", " ".join(supp.split()))}
        index = (REPO / "docs" / "supplement_index.md").read_text(encoding="utf-8")
        start = index.index("## Journal supplement and postmortem")
        end = index.find("\n## ", start + 5)
        table = index[start:end if end != -1 else len(index)]
        #: | S3 | Failure 1: the full evidence | postmortem S7, S8, S9, S12, ... |
        for row in re.findall(r"^\|\s*S\d+\s*\|.*$", table, re.M):
            reached |= {int(n) for n in re.findall(r"\bS(\d+)(?:\.\d+)?\b", row.split("|", 3)[3])}
        return reached

    def test_every_targeted_section_is_reached(self, supp, post):
        reached = self._reached(supp)
        missing = [n for n in self._post_sections(post) if n in self.TARGETED and n not in reached]
        assert not missing, (
            "postmortem section(s) no route from the paper reaches: %s -- a passage moved out "
            "of a paragraph is reachable only through that paragraph, so a relocation without "
            "a route is a deletion with extra steps" % ["S%d" % n for n in missing])

    def test_the_targeted_sections_exist(self, post):
        """A renumbering that loses one of them would make the rule above vacuous for it."""
        sections = set(self._post_sections(post))
        gone = sorted(self.TARGETED - sections)
        assert not gone, "targeted section(s) no longer exist: %s" % ["S%d" % n for n in gone]

    def test_the_check_can_fail(self, supp, post):
        """A reachability test that cannot notice an unreachable section is decoration."""
        absent = max(self._post_sections(post)) + 7
        assert absent not in self._reached(supp)


class TestSupplementNumbering:
    """The contents list is read as a list. Two defects in it are visible at a glance."""

    def _order(self, text):
        return [int(n) for n in re.findall(r"^\\section\{S(\d+)[.:]", text, re.M)]

    @pytest.mark.parametrize("name", COMPANIONS)
    def test_sections_appear_in_increasing_order(self, name, docs):
        order = self._order(docs[name])
        swaps = [(a, b) for a, b in zip(order, order[1:]) if a > b]
        assert not swaps, "%s: sections out of order in the contents list: %s" % (
            name, ["S%d before S%d" % (a, b) for a, b in swaps])

    @pytest.mark.parametrize("name", COMPANIONS)
    def test_any_gap_is_explained(self, name, docs):
        """Gaps are allowed -- S14 and S30 were withdrawn and their numbers are cited in
        correspondence -- but only where the document says so, so a reader is not left
        counting."""
        text = docs[name]
        order = self._order(text)
        gaps = sorted(set(range(min(order), max(order) + 1)) - set(order))
        if not gaps:
            return
        note = re.search(r"\\emph\{On the numbering\.\}(.*)", text)
        assert note, "%s: the contents list has gaps (%s) and no note explaining them" % (
            name, ["S%d" % g for g in gaps])
        for g in gaps:
            assert "S%d" % g in note.group(1), \
                "S%d is missing from the contents list and unexplained in the note" % g

    @pytest.mark.parametrize("name", COMPANIONS)
    def test_headings_punctuate_consistently(self, name, docs):
        """S1--S5 used a colon where S6--S42 used a period, in the one list a reader scans
        top to bottom."""
        marks = {m.group(1) for m in re.finditer(r"^\\section\{S\d+([.:])", docs[name], re.M)}
        assert len(marks) == 1, "%s: S-headings mix separators: %s" % (name, sorted(marks))


class TestNoFloatOrEquationIsPointedAtByNumber:
    """Cross-document pointers must go through `\\ref`, never through a typed number.

    The companions load `xr` (`\\externaldocument[P-]{paper}`), so `\\ref{P-tab:spans}`
    resolves across the document boundary and renders "Table I".

    Six sentences once typed the number instead, and round 48 resolved every one against
    `paper.aux`. **Five were wrong.** Both "Table~II" pointers meant Table I: one inside a
    table caption whose entire job is distinguishing two corpora, and one inside the
    asymmetry disclosure rounds 43 and 44 asked for so a reader could check the direction of
    a bias. A third cited "Figure~1(a)", a panel of a figure that has no panels.

    So the rule is not "resolve the number" but "do not write the number". `\\ref` cannot
    point at a float that is not there, and cannot be left behind by a renumbering.
    """

    #: A float or equation named by a literal number rather than by a `\ref`.
    LITERAL = re.compile(
        r"\b(Table|Figure|Fig\.|Equation|Equations)~?\s*"
        r"(?:[IVXL]+|[0-9]+)(?![-\w])")

    @pytest.mark.parametrize("name", ("paper",) + COMPANIONS)
    def test_no_pointer_names_a_number(self, name, docs):
        text = re.sub(r"(?<!\\)%.*", "", docs[name])
        # `\ref{...}` and `\cite{...}` carry digits and Roman numerals of their own.
        masked = re.sub(r"\\(?:eq)?ref\{[^}]*\}", "@@", text)
        masked = re.sub(r"\\cite\w*\{[^}]*\}", "@@", masked)
        bad = []
        for m in self.LITERAL.finditer(masked):
            line = masked.count("\n", 0, m.start()) + 1
            ctx = re.sub(r"\s+", " ", masked[max(0, m.start() - 60):m.start() + 60])
            bad.append("%s:%d  %r\n        ...%s..." % (name, line, m.group(0), ctx.strip()))
        assert not bad, (
            "cross-reference written as a literal number; use \\ref so it cannot rot:\n  "
            + "\n  ".join(bad))

    @pytest.mark.parametrize("name", COMPANIONS)
    def test_each_companion_can_reach_the_paper(self, name, docs):
        """The rule above is only safe because `xr` is loaded. If it ever is not, every
        `\\ref` into the paper renders as `??` and this check would still pass."""
        assert re.search(r"\\externaldocument\[P-\]\{paper\}", docs[name]), (
            "%s must load xr and \\externaldocument[P-]{paper}, or the cross-document \\ref "
            "calls this rule forces everyone to use will render as ??" % name)

    @pytest.mark.parametrize("name", COMPANIONS)
    def test_the_cross_document_refs_resolve(self, name, docs, aux):
        """Every label a companion reaches for must be one it or the paper actually assigned.

        Until 29 September this matched only unprefixed labels (`tab:...`), so every
        `\\ref{P-tab:...}` -- all of them, since the prefix was introduced -- went unchecked
        here; a missing one surfaced only as "??" in the built PDF."""
        assert aux, "paper.aux carries no labels; build the paper first"
        body = docs[name].split(r"\begin{document}")[-1]
        own = set(re.findall(r"\\label\{([^}]*)\}", body))
        bad = []
        for m in re.finditer(r"\\(?:eq)?ref\{(P-)?([a-z]+:[^}]*)\}", body):
            prefixed, label = m.group(1), m.group(2)
            if (prefixed and label in aux) or (not prefixed and (label in own or label in aux)):
                continue
            line = body.count("\n", 0, m.start()) + 1
            bad.append("%s:~%d  \\ref{%s%s} resolves nowhere" % (name, line, prefixed or "", label))
        assert not bad, "\n  " + "\n  ".join(bad)

    def test_the_check_can_fail(self):
        """A rule this absolute is worth proving it still bites."""
        assert self.LITERAL.search(r"the main text's Table~II, which covers")
        assert self.LITERAL.search(r"(Equation~3 of the main text)")
        assert self.LITERAL.search(r"drawn again in Figure~1")
        assert not self.LITERAL.search(r"Table~\ref{tab:spans} is clean".replace(
            r"\ref{tab:spans}", "@@"))


class TestNoReferenceResolvesToNothing:
    """A `\\ref` whose target prints no number --- the pointer that vanishes silently.

    The postmortem sets `secnumdepth` to 0 on purpose: its S-numbers are written into the
    heading text, and a second counter beside them would make the contents page read
    "I S36.". The side effect nobody had traced is that `\\section` then steps no *printed*
    counter, so a `\\label` on one stores the empty string, and

        Section~\\ref{sec:registry}

    typesets as `Section  found in shipping software` --- the pointer simply gone from the
    page. Two of them had been rendering as holes since round 43. The journal supplement sets
    its headings' label text to their S-numbers instead, so its internal `\\ref`s print them.

    So this one reads the `.aux` each document actually produced and requires every `\\ref`
    to come back with a number. It is the rendered value that is inspected, which is the
    lesson rounds 48 through 52 kept teaching: check the artifact, not the source.
    """

    #: `\newlabel{sec:registry}{{}{47}{...}}` -- the printed number is the first group, and
    #: here it is the empty ones we are hunting rather than skipping.
    NEWLABEL = re.compile(r"\\newlabel\{([^}]*)\}\{\{(.*?)\}\{\d+\}")

    #: `\eqref` and `\ref` both print the counter; `\pageref` prints a page and is exempt.
    REFERENCE = re.compile(r"\\(?:eq)?ref\{([^}]*)\}")

    def _blank_labels(self, aux_text):
        return {m.group(1) for m in self.NEWLABEL.finditer(aux_text)
                if not m.group(2).replace(r"\mbox", "").strip().strip("{}").strip()}

    @pytest.mark.parametrize("name", ("paper",) + COMPANIONS)
    def test_every_reference_prints_a_number(self, name):
        tex, aux = REPO / (name + ".tex"), REPO / (name + ".aux")
        assert tex.exists() and aux.exists(), "%s not built" % name
        blank = self._blank_labels(aux.read_text(encoding="utf-8", errors="replace"))
        body = tex.read_text(encoding="utf-8").split(r"\begin{document}")[-1]
        holes = []
        for m in self.REFERENCE.finditer(body):
            if m.group(1) in blank:
                line = body.count("\n", 0, m.start()) + 1
                holes.append("%s:~%d  \\ref{%s} prints nothing; write the number the heading "
                             "carries, as the rest of the document does"
                             % (name, line, m.group(1)))
        assert not holes, (
            "these references typeset as a hole in the sentence:\n  " + "\n  ".join(holes))

    def test_the_postmortem_still_has_labels_that_would_trip_this(self):
        """The rule is only live while such labels exist.

        If the postmortem ever numbered its sections, every label would print something and
        this class would pass vacuously for the rest of time. Then it should be deleted
        rather than kept as decoration, and this assertion is what would say so.
        """
        aux = REPO / "postmortem.aux"
        assert aux.exists(), "postmortem.aux not present; tests/paper_build.py builds it"
        blank = self._blank_labels(aux.read_text(encoding="utf-8", errors="replace"))
        assert blank, (
            "no label in the postmortem prints an empty number any more; if section "
            "numbering was turned on, delete this class instead of leaving it passing")

    def test_the_check_can_fail(self):
        """Mutation: the sentence as it stood, against an aux that says the label is blank."""
        blank = self._blank_labels(r"\newlabel{sec:registry}{{}{47}{The registry}{}{}}")
        assert blank == {"sec:registry"}
        broken = r"the registry of Section~\ref{sec:registry} found in shipping software"
        assert [m.group(1) for m in self.REFERENCE.finditer(broken)] == ["sec:registry"]
        # and a numbered target is left alone
        assert not self._blank_labels(r"\newlabel{sec:gate}{{\mbox {III-B}}{3}{Gate}{}{}}")
