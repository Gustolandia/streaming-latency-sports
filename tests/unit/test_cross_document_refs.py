"""Pointers between the two documents, which LaTeX cannot check and nobody re-reads.

The manuscript and the supplement are separate compilations, so `\\ref` cannot reach across
them. Every pointer in one document at the other is therefore a *hand-typed number*, outside
every mechanism this project uses to stop numbers drifting. There are more than thirty of
them.

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
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
PAPER = REPO / "paper.tex"
SUPP = REPO / "supplement.tex"
AUX = REPO / "paper.aux"


@pytest.fixture(scope="module")
def paper():
    return PAPER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supp():
    if not SUPP.exists():
        pytest.skip("supplement not present")
    return SUPP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def aux():
    """label -> printed number, as LaTeX actually assigned them.

    `\\newlabel{sec:gate}{{\\mbox {III-B}}{3}{...}}` -- the number is the first group, with
    the \\mbox wrapper IEEEtran adds to subsection numbers stripped off.
    """
    if not AUX.exists():
        pytest.skip("paper.aux not present; build the paper first")
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

    @pytest.mark.parametrize("name", ["paper", "supplement"])
    def test_no_pointer_word_lacks_its_number(self, name, paper, supp):
        text = paper if name == "paper" else supp
        hits = []
        for m in self.STRANDED.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append("%s:%d  %r" % (name, line, text[m.start():m.start() + 48]))
        assert not hits, "pointer word with nothing to point at:\n  " + "\n  ".join(hits)


class TestTheSupplementNamesSectionsRatherThanNumberingThem:
    """Main-text section numbers live in one macro block, never inline in the prose.

    The check below this one asks whether a pointer resolves. That catches the pointer that
    breaks loudly and misses the one that stays valid while changing meaning: folding the
    broker results into the Discussion left four `Section~VI` pointers resolving perfectly to
    a section that was no longer the one they meant. No gate can see that, so the numbers stop
    being written by hand.
    """

    MACRO_PREFIX = "main"

    def test_no_section_number_is_written_inline(self):
        supp = (REPO / "supplement.tex").read_text(encoding="utf-8")
        body = supp.split(r"\begin{document}")[-1]
        bad = re.findall(r"Section~[IVX]+(?:-[A-D])?(?![a-zA-Z])", body)
        assert not bad, (
            "these point at the main text by number; use the macro block in the preamble so a "
            "renumbering is one edit: %s" % sorted(set(bad)))

    def test_every_macro_the_prose_uses_is_defined(self):
        supp = (REPO / "supplement.tex").read_text(encoding="utf-8")
        defined = set(re.findall(r"\\newcommand\{\\(main[A-Za-z]+)\}", supp))
        used = set(re.findall(r"Section~\\(main[A-Za-z]+)", supp))
        assert used, "the supplement must point at the main text somewhere"
        assert used <= defined, "undefined section macros: %s" % sorted(used - defined)

    def test_every_macro_defined_is_used(self):
        """A stale entry would quietly licence a number nothing checks."""
        supp = (REPO / "supplement.tex").read_text(encoding="utf-8")
        defined = set(re.findall(r"\\newcommand\{\\(main[A-Za-z]+)\}", supp))
        used = set(re.findall(r"Section~\\(main[A-Za-z]+)", supp))
        assert defined <= used, "defined but never used: %s" % sorted(defined - used)

    def test_the_macros_carry_numbers_the_paper_has(self):
        """The values are still numbers, so the resolve-check below still means something."""
        supp = (REPO / "supplement.tex").read_text(encoding="utf-8")
        values = dict(re.findall(r"\\newcommand\{\\(main[A-Za-z]+)\}\{([^}]*)\}", supp))
        assert values, "the macro block must exist"
        for name, number in sorted(values.items()):
            assert re.match(r"^[IVX]+(?:-[A-D])?$", number), \
                "%s holds %r, which is not a section number" % (name, number)


class TestSupplementPointsAtRealSections:
    """Every "Section~X of the main text" must be a section the main text has."""

    POINTER = re.compile(
        r"(?:main text's Section~|Section~)([IVX]+(?:-[A-D])?|[0-9]+(?:\.[0-9]+)?)"
        r"(?=[^a-zA-Z]|$)")

    def test_every_pointer_resolves(self, supp, aux):
        real = set(aux.values())
        bad = []
        for m in self.POINTER.finditer(supp):
            num = m.group(1)
            if num not in real:
                line = supp.count("\n", 0, m.start()) + 1
                bad.append("supplement:%d  Section~%s (the paper has no such number)"
                           % (line, num))
        assert not bad, "\n  " + "\n  ".join(bad)

    def test_pointers_use_roman_numerals(self, supp):
        """The paper numbers sections in Roman. An arabic pointer is a stale one.

        "the main text's Section~6.2" survived the round-5 sweep because the sweep looked for
        descriptive names, and this one was already a number -- just a number from a
        structure two restructures old.
        """
        arabic = []
        for m in re.finditer(r"(?:main text's )?Section~([0-9]+(?:\.[0-9]+)?)", supp):
            line = supp.count("\n", 0, m.start()) + 1
            arabic.append("supplement:%d  Section~%s" % (line, m.group(1)))
        assert not arabic, "arabic section pointers:\n  " + "\n  ".join(arabic)


class TestPaperPointsAtRealSupplementSections:
    """Every "Supplement~SNN" must be a section the supplement has.

    The reverse direction of the same defect. Round 3 raised it for the main text and it was
    fixed by hand; nothing has held it since.
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
    """A section created by moving text out of the paper must be pointed at by the paper.

    Round 20 moved three passages into S53, S54 and S55 and left two of the three pointers on
    the sections the content had left: Section IV-C went on citing S46 for a construction that
    is now in S54, and Section IV-D went on citing S43 for a driver explanation that is now in
    S53. Both pointers resolved, because both targets exist, so the resolve-check below saw
    nothing wrong. What no check asked was whether the *new* sections could be reached at all.

    The rule is deliberately not "every section labelled *moved from the main text* must be
    pointed at". Twenty of those are bulk moves from the TPDS-era restructure, when a
    fifty-eight-page draft became sixteen pages and the supplement absorbed whole sections at
    once; the supplement index documents them and the paper was never expected to name each.
    Everything from S45 onward is different in kind: each is a single passage lifted out of a
    paragraph that stayed behind, and the paragraph that stayed behind is the only route to
    it.
    """

    #: Where bulk relocation stopped and targeted relocation began.
    FIRST_TARGETED = 45

    def _sections(self, supp):
        return sorted({int(n) for n in re.findall(r"\\section\{S(\d+)\.", supp)})

    def _pointed_at(self, paper):
        out = set()
        for m in re.finditer(r"S(\d+)(?:\.\d+)?", paper):
            out.add(int(m.group(1)))
        return out

    def test_every_section_from_the_targeted_range_is_pointed_at(self, paper, supp):
        pointed = self._pointed_at(paper)
        missing = [n for n in self._sections(supp)
                   if n >= self.FIRST_TARGETED and n not in pointed]
        assert not missing, (
            "supplement section(s) the paper never sends anyone to: %s -- a passage moved out "
            "of a paragraph is reachable only through that paragraph, so a relocation without "
            "a pointer is a deletion with extra steps" % ["S%d" % n for n in missing])

    def test_the_boundary_is_where_we_say_it_is(self, supp):
        """If the targeted range ever starts below S45 this rule silently widens onto the
        bulk moves and starts failing on twenty sections nobody intended to point at."""
        sections = self._sections(supp)
        assert self.FIRST_TARGETED in sections, "S%d must exist" % self.FIRST_TARGETED
        assert max(sections) > self.FIRST_TARGETED, "no targeted relocations to police"

    def test_the_check_can_fail(self, paper, supp):
        """A reachability test that cannot notice an unreachable section is decoration."""
        pointed = self._pointed_at(paper)
        absent = max(self._sections(supp)) + 7
        assert absent not in pointed


class TestSupplementNumbering:
    """The contents list is read as a list. Two defects in it are visible at a glance."""

    def _order(self, supp):
        return [int(n) for n in re.findall(r"^\\section\{S(\d+)[.:]", supp, re.M)]

    def test_sections_appear_in_increasing_order(self, supp):
        order = self._order(supp)
        swaps = [(a, b) for a, b in zip(order, order[1:]) if a > b]
        assert not swaps, "sections out of order in the contents list: %s" % (
            ["S%d before S%d" % (a, b) for a, b in swaps],)

    def test_any_gap_is_explained(self, supp):
        """Gaps are allowed -- S14 and S30 were withdrawn and their numbers are cited in
        correspondence -- but only where the document says so, so a reader is not left
        counting."""
        order = self._order(supp)
        gaps = sorted(set(range(min(order), max(order) + 1)) - set(order))
        if not gaps:
            return
        note = re.search(r"\\emph\{On the numbering\.\}(.*)", supp)
        assert note, "the contents list has gaps (%s) and no note explaining them" % (
            ["S%d" % g for g in gaps],)
        for g in gaps:
            assert "S%d" % g in note.group(1), \
                "S%d is missing from the contents list and unexplained in the note" % g

    def test_headings_punctuate_consistently(self, supp):
        """S1--S5 used a colon where S6--S42 used a period, in the one list a reader scans
        top to bottom."""
        marks = {m.group(1) for m in re.finditer(r"^\\section\{S\d+([.:])", supp, re.M)}
        assert len(marks) == 1, "S-headings mix separators: %s" % sorted(marks)


class TestNoFloatOrEquationIsPointedAtByNumber:
    """Cross-document pointers must go through `\\ref`, never through a typed number.

    The supplement loads `xr` (`\\externaldocument{paper}`), so `\\ref{tab:spans}` resolves
    across the document boundary and renders "Table I". Two captions twenty lines apart in
    S51 already do exactly that and are correct.

    Six other sentences typed the number instead, and round 48 resolved every one against
    `paper.aux`. **Five were wrong.** Both "Table~II" pointers meant Table I: one inside a
    table caption whose entire job is distinguishing two corpora, and one inside the
    asymmetry disclosure rounds 43 and 44 asked for so a reader could check the direction of
    a bias -- it sent them to the only table in the paper with no per-broker columns. A third
    cited "Figure~1(a)", a panel of a figure that has no panels.

    The previous version of this check is why they survived. It asked whether a pointer
    *resolved* -- whether the paper had a Table II at all -- and it did, so the check passed
    while the pointer denoted the wrong table. It then listed the pointers it had seen in an
    `expected` set as a tripwire, which had the effect of blessing them. A pointer that
    resolves to the wrong float is invisible to any check that only asks whether the number
    exists.

    So the rule is not "resolve the number" but "do not write the number". `\\ref` cannot
    point at a float that is not there, and cannot be left behind by a renumbering.
    """

    #: A float or equation named by a literal number rather than by a `\ref`.
    LITERAL = re.compile(
        r"\b(Table|Figure|Fig\.|Equation|Equations)~?\s*"
        r"(?:[IVXL]+|[0-9]+)(?![-\w])")

    @pytest.mark.parametrize("name", ["paper", "supplement"])
    def test_no_pointer_names_a_number(self, name, paper, supp):
        text = paper if name == "paper" else supp
        text = re.sub(r"(?<!\\)%.*", "", text)
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

    def test_the_supplement_can_reach_the_paper(self, supp):
        """The rule above is only safe because `xr` is loaded. If it ever is not, every
        `\\ref` into the paper renders as `??` and this check would still pass."""
        assert re.search(r"\\externaldocument\{paper\}", supp), (
            "the supplement must load xr and \\externaldocument{paper}, or the cross-document "
            "\\ref calls this rule forces everyone to use will render as ??")

    def test_the_cross_document_refs_resolve(self, supp, aux):
        """Every label the supplement reaches for must be one the paper actually assigned."""
        if not aux:
            pytest.skip("paper.aux carries no labels; build the paper first")
        body = supp.split(r"\begin{document}")[-1]
        own = set(re.findall(r"\\label\{([^}]*)\}", body))
        bad = []
        for m in re.finditer(r"\\(?:eq)?ref\{((?:tab|fig|eq|sec):[^}]*)\}", body):
            label = m.group(1)
            if label in own or label in aux:
                continue
            line = body.count("\n", 0, m.start()) + 1
            bad.append("supplement:~%d  \\ref{%s} resolves in neither document" % (line, label))
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

    The supplement sets `secnumdepth` to 0 on purpose: its S-numbers are written into the
    heading text, and a second counter beside them would make the contents page read
    "I S36.". The side effect nobody had traced is that `\\section` then steps no *printed*
    counter, so a `\\label` on one stores the empty string, and

        Section~\\ref{sec:registry}

    typesets as `Section  found in shipping software` --- the pointer simply gone from the
    page. Two of them had been rendering as holes since round 43, in the prose and the
    caption of the figure a co-author asked for.

    Every existing gate passed. The label is defined, so LaTeX emits no warning and no `??`
    reaches the page; the undefined-reference count stays zero; `TestNoStrandedPointer` sees
    a `\\ref` after the tilde and is satisfied; and `test_the_cross_document_refs_resolve`
    above asks whether the label can be *found*, which it can. None of them asked whether it
    printed anything.

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

    @pytest.mark.parametrize("name", ["paper", "supplement"])
    def test_every_reference_prints_a_number(self, name):
        tex, aux = REPO / (name + ".tex"), REPO / (name + ".aux")
        if not tex.exists() or not aux.exists():
            pytest.skip("%s not built" % name)
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

    def test_the_supplement_still_has_labels_that_would_trip_this(self):
        """The rule is only live while such labels exist.

        If the supplement ever numbered its sections, every label would print something and
        this class would pass vacuously for the rest of time. Then it should be deleted
        rather than kept as decoration, and this assertion is what would say so.
        """
        aux = REPO / "supplement.aux"
        if not aux.exists():
            pytest.skip("supplement.aux not present; build the supplement first")
        blank = self._blank_labels(aux.read_text(encoding="utf-8", errors="replace"))
        assert blank, (
            "no label in the supplement prints an empty number any more; if section "
            "numbering was turned on, delete this class instead of leaving it passing")

    def test_the_check_can_fail(self):
        """Mutation: the sentence as it stood, against an aux that says the label is blank."""
        blank = self._blank_labels(r"\newlabel{sec:registry}{{}{47}{The registry}{}{}}")
        assert blank == {"sec:registry"}
        broken = r"the registry of Section~\ref{sec:registry} found in shipping software"
        assert [m.group(1) for m in self.REFERENCE.finditer(broken)] == ["sec:registry"]
        # and a numbered target is left alone
        assert not self._blank_labels(r"\newlabel{sec:gate}{{\mbox {III-B}}{3}{Gate}{}{}}")
