r"""The supplement's subsections: numbered, unique, sequential, and reachable by name.

Every cross-document check this project owns works at *section* granularity. `S52` either
exists or it does not; `Supplement~S52` either resolves or it does not. That was enough while
the supplement's subsections were scenery. It stopped being enough in round 26, which inserted
a subsection in the middle of S52, renumbered the one below it, and left the one below *that*
alone. The result was two subsections both called S52.3, printed one under the other in the
contents list on the same page:

    S52.3. How large the literature is that misses this ................ 45
    S52.3. Where scheduling delay comes from, and what the queueing .... 45

Nothing failed. `TestSupplementNumbering` checks that *sections* are ordered and gap-free and
saw one S52. `TestPaperPointsAtRealSupplementSections` parses `Supplement~S(\d+)` and saw a
pointer to S52, which exists. The defect lived one level below every gate in the suite, and it
was visible in the printed front matter of the document.

The same round produced its sibling. Section II-A cites `Supplement~S52.2` for a claim about
how large the literature is; the field-size synthesis had moved to S52.3 in that same edit, and
S52.2 is now a reading of one framework, which sizes nothing. The pointer *resolves* --- S52.2
exists --- so a resolution check cannot see it. What is wrong is the destination, not the
address, and the only machine-checkable trace of that is that the sentence and its target no
longer share any subject matter.

Four rules here, in increasing order of how much they assume:

1. every subsection carries an ``SNN.M.'' number (three did not, and printed as bare titles
   in a contents list where twenty-seven of thirty were numbered);
2. the number agrees with the section the subsection is in, is unique, and leaves no gap;
3. every ``Supplement~SNN.M'' in the paper names a subsection that exists;
4. the sentence making the pointer shares a content word with the subsection it points at.

Rule 4 is a heuristic and is the only one that can be wrong. It compares against the target's
heading *and body*, not the heading alone: a claim about ``its measurement section'' correctly
points at a subsection titled ``A framework that does not have the problem'', and only the body
knows they are about the same thing. Where a genuine pointer shares no vocabulary with its
target, `LOOSE` records it with a reason rather than the rule being softened --- the same
bargain the ledger sweep makes.

Two more came from summaries that moved into the section they summarized (27 September): no
heading may be followed directly by another, and no section's prose may name the section it
is in.
"""
import re
from collections import defaultdict
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
PAPER = REPO / "paper.tex"
SUPP = REPO / "supplement.tex"

#: Pointers whose sentence shares no content word with the subsection it names, with the
#: reason each is nonetheless correct. Keyed by (target, a fragment of the citing sentence).
LOOSE = {}

#: Words that carry no subject matter, so sharing one proves nothing.
STOP = frozenset("""
a an and are as at be been but by can cannot did do does for from had has have how in into is
it its not of on one only or our ours out over own same so than that the their them then there
these they this those to under until up upon was we were what when where which while who why
with would you your section supplement supplements figure table equation see also both each
""".split())


@pytest.fixture(scope="module")
def paper():
    return PAPER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supp():
    if not SUPP.exists():                               # pragma: no cover - always present
        pytest.skip("supplement not present")
    return SUPP.read_text(encoding="utf-8")


def _subsections(supp):
    """[(char position, raw title)] for every subsection, numbered or not."""
    return [(m.start(), m.group(1))
            for m in re.finditer(r"\\subsection\{([^}]*)\}", supp)]


def _numbered(supp):
    """[(section, sub, title, position)] for the subsections that carry an SNN.M number."""
    out = []
    for pos, title in _subsections(supp):
        m = re.match(r"S(\d+)\.(\d+)\.\s*(.*)", title)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), m.group(3), pos))
    return out


def _owning_section(supp, pos):
    """The S-number of the section a given position falls inside."""
    last = None
    for m in re.finditer(r"\\section\{S(\d+)[.:]", supp):
        if m.start() > pos:
            break
        last = int(m.group(1))
    return last


#: Sentence and clause boundaries, in the order a claim is cut back to.
_BREAKS = ".;:"

#: Below this many content words a clause is too thin to judge, and the window steps back to
#: the previous boundary. `(Supplement~S40.4)` on its own carries none.
_MIN_WORDS = 2


def _pointers(paper):
    """[(section, sub, citing clause)] for every Supplement~SNN.M in the main text.

    The clause, not the paragraph. A first attempt at this took everything back to the previous
    full stop, and on the one pointer that was actually misdirected that reached across two
    semicolons into a sentence about the gray literature --- which shares a word with almost
    anything, so the rule passed on the defect it was written for. The window therefore starts
    at the nearest boundary and steps back only while it holds too little to judge.

    A leading backslash is excluded so that a standards clause -- the supplement cites
    `\\S6.4.1` of IEEE 1241 -- is never mistaken for a pointer at ourselves.
    """
    out = []
    for m in re.finditer(r"(?<!\\)\bS(\d+)\.(\d+)\b", paper):
        end = min([p for p in (paper.find(c, m.end()) for c in _BREAKS) if p != -1]
                  + [len(paper)])
        start = max(paper.rfind(c, 0, m.start()) for c in _BREAKS)
        while start > 0:
            clause = paper[start + 1:end]
            if len(_words(clause)) >= _MIN_WORDS:
                break
            start = max(paper.rfind(c, 0, start) for c in _BREAKS)
        out.append((int(m.group(1)), int(m.group(2)),
                    " ".join(paper[start + 1:end].split())))
    return out


def _words(text):
    text = re.sub(r"\\[a-zA-Z]+\s*", " ", text)         # macros carry no prose
    text = re.sub(r"[^a-zA-Z ]", " ", text)
    return {w[:5] for w in text.lower().split() if len(w) > 3 and w not in STOP}


def _body(supp, pos):
    """Heading plus prose of the subsection beginning at `pos`, to the next heading."""
    nxt = re.search(r"\\(?:sub)?section\{", supp[pos + 10:])
    end = pos + 10 + nxt.start() if nxt else len(supp)
    return supp[pos:end]


def _empty_headings(tex):
    """Titles of headings followed by another heading, with no prose between them."""
    prose = re.sub(r"(?<!\\)%.*", "", tex)
    return re.findall(r"\\(?:sub)*section\*?\{([^}]*)\}\s*(?:\\label\{[^}]*\}\s*)?"
                      r"(?=\\(?:sub)*section)", prose)


def _self_pointers(tex):
    """[(section, context)] wherever a section's prose names the section it is in.

    Headings are removed first, and a subsection's number (S4.1 inside S4) points somewhere
    else, so neither counts.
    """
    prose = re.sub(r"(?<!\\)%.*", "", tex)
    heads = list(re.finditer(r"\\section\{(S\d+)\.", prose))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(prose)
        body = re.sub(r"\\(?:sub)*section\*?\{[^}]*\}", "", prose[m.end():end])
        for hit in re.finditer(r"(?<![\w.])%s(?!\d)(?!\.\d)" % m.group(1), body):
            out.append((m.group(1),
                        " ".join(body[max(0, hit.start() - 60):hit.end()].split())))
    return out


class TestEverySubsectionIsNumbered:
    """A contents list where some entries have numbers and some do not is read as a mistake.

    `TestSupplementNumbering.test_headings_punctuate_consistently` exists because S6--S9 used
    a colon where S3--S39 used a period. This is that defect one level down and larger: three
    subsections under S5 and S7 printed as bare titles beside twenty-seven numbered ones.
    """

    def test_no_subsection_lacks_its_number(self, supp):
        bare = [t for _, t in _subsections(supp) if not re.match(r"S\d+\.\d+\.", t)]
        assert not bare, (
            "subsection(s) with no SNN.M number, which print as bare titles in a contents "
            "list where the rest are numbered: %s" % bare)

    def test_the_check_would_notice_a_bare_title(self):
        assert not re.match(r"S\d+\.\d+\.", "The result")
        assert re.match(r"S\d+\.\d+\.", "S5.1. The result")


class TestSubsectionNumbersAreWellFormed:

    def test_each_number_agrees_with_its_section(self, supp):
        wrong = [("S%d.%d" % (sec, sub), title[:40], "inside S%d" % _owning_section(supp, pos))
                 for sec, sub, title, pos in _numbered(supp)
                 if _owning_section(supp, pos) != sec]
        assert not wrong, "subsection number(s) disagreeing with the section they sit in: %s" % (
            wrong,)

    def test_no_number_is_used_twice(self, supp):
        seen = defaultdict(list)
        for sec, sub, title, _ in _numbered(supp):
            seen[(sec, sub)].append(title)
        dup = {"S%d.%d" % k: v for k, v in seen.items() if len(v) > 1}
        assert not dup, (
            "subsection number(s) used more than once -- both print in the contents list and "
            "a citation of the number cannot be resolved by a reader: %s" % dup)

    def test_numbers_run_without_a_gap(self, supp):
        """S1 starts at .0 and the rest at .1, so the rule is contiguity, not a fixed start."""
        by = defaultdict(list)
        for sec, sub, _, _ in _numbered(supp):
            by[sec].append(sub)
        broken = {}
        for sec, subs in by.items():
            want = list(range(min(subs), min(subs) + len(subs)))
            if sorted(subs) != want:
                broken["S%d" % sec] = sorted(subs)
        assert not broken, "subsection numbering with a gap or a repeat: %s" % broken

    def test_numbers_appear_in_increasing_order(self, supp):
        by = defaultdict(list)
        for sec, sub, _, _ in _numbered(supp):
            by[sec].append(sub)
        swaps = {"S%d" % sec: subs for sec, subs in by.items() if subs != sorted(subs)}
        assert not swaps, "subsections printed out of numerical order: %s" % swaps


class TestThePaperPointsAtSubsectionsThatExist:

    def test_every_subsection_pointer_resolves(self, paper, supp):
        have = {(sec, sub) for sec, sub, _, _ in _numbered(supp)}
        missing = sorted({(sec, sub) for sec, sub, _ in _pointers(paper)} - have)
        assert not missing, "paper cites supplement subsection(s) that do not exist: %s" % (
            ["S%d.%d" % k for k in missing],)

    def test_a_standards_clause_is_not_read_as_a_pointer(self):
        r"""The supplement cites `\S6.4.1` of IEEE 1241; we do not own that number."""
        assert not _pointers(r"the clause (\S6.4.1, Eq.~(28)) requires")
        assert _pointers("as Supplement~S3.4 shows")


class TestAPointerLandsOnItsSubject:
    r"""The address resolves; does the destination hold the claim?

    Round 26 moved the field-size synthesis from S52.2 to S52.3 and left Section II-A citing
    S52.2 for it. Every resolution check passed, because S52.2 exists. What a reader gets is a
    sentence about how large a literature is, pointing at a reading of a single framework.

    This is the only rule here that can be wrong about a correct pointer, so it is deliberately
    weak: one shared word stem, matched against the target's heading *and* body, is enough. A
    pointer that shares nothing at all with its destination is either misdirected or is asking
    the reader to take the connection on faith.
    """

    def test_every_pointer_shares_a_word_with_its_target(self, paper, supp):
        bodies = {(sec, sub): _body(supp, pos) for sec, sub, _, pos in _numbered(supp)}
        bad = []
        for sec, sub, sentence in _pointers(paper):
            target = bodies.get((sec, sub))
            if target is None:                          # resolution is the other test's job
                continue
            if _words(sentence) & _words(target):
                continue
            if any(frag in sentence for (tgt, frag) in LOOSE if tgt == (sec, sub)):
                continue
            bad.append("S%d.%d <- %s" % (sec, sub, sentence[:110]))
        assert not bad, (
            "pointer(s) sharing no subject matter with the subsection they name -- the address "
            "resolves but the destination does not hold the claim:\n  " + "\n  ".join(bad))

    def test_every_exemption_carries_a_reason(self):
        assert all(v and len(v) > 20 for v in LOOSE.values())

    def test_a_misdirected_pointer_is_caught(self):
        """The round-26 defect, reconstructed: the claim and the wrong target share nothing."""
        claim = "the OpenMessaging Benchmark is the shared instrument; S52.2 sizes that literature"
        wrong = r"\subsection{S52.2. A framework that does not have the problem} It stamps in " \
                "nanoseconds on one host and applies no guard."
        right = r"\subsection{S52.3. How large the literature is that misses this} A preprint " \
                "synthesizes 42 peer-reviewed studies."
        assert not (_words(claim) & _words(wrong)), "the wrong target must share nothing"
        assert _words(claim) & _words(right), "the right target must share something"


class TestNoUnitIsEmptyOrPointsAtItself:
    """Two defects a summary leaves behind when it moves into the section it summarized.

    The main text's fourteen-line account of the replay-rate episode moved into S4 as S4.2,
    under an S4.1 heading with nothing beneath it, and still ended by sending the reader to
    "supplementary material S4" -- from inside S4. The same pointer closed paragraphs in S10,
    S22, S23, S24 and S27 (found 27 September); in four of them it ended a second copy of what
    the section already said in full. Neither defect stops LaTeX, and the first printed in the
    contents list as a heading with nothing under it.
    """

    def test_no_heading_is_empty(self, supp):
        assert not _empty_headings(supp), _empty_headings(supp)

    def test_no_section_points_at_itself(self, supp):
        assert not _self_pointers(supp), _self_pointers(supp)


class TestTheseChecksCanFail:
    """Every rule above is asserted to notice its own defect, on a fixture built to carry it."""

    #: One of each defect the two rules of 27 September look for, and what they must allow:
    #: a pointer to a subsection of the same section, and one to a different section.
    MOVED = "\n".join([
        r"\section{S4. An episode}", "The full record, then the co-location note in S4.1.",
        r"\subsection{S4.1. Empty}",
        r"\subsection{S4.2. A summary}", "The full episode is supplementary material S4.",
        r"\section{S40. Another}", r"\label{sec:x}", "As S4 says, and as S40 says too.",
    ])

    def test_the_empty_heading_rule_fires(self):
        assert _empty_headings(self.MOVED) == ["S4.1. Empty"]

    def test_the_self_pointer_rule_fires(self):
        found = _self_pointers(self.MOVED)
        assert [section for section, _ in found] == ["S4", "S40"]
        assert found[0][1].endswith("is supplementary material S4")

    # Synthetic numbers: this fixture is a broken document of its own, not the supplement,
    # so its S9/S7 have nothing to do with any real section (the v4 renumbering sweep once
    # rewrote them along with the real pointers and every self-test below went wrong).
    BROKEN = "\n".join([
        r"\section{S9. A section}",
        r"\subsection{S9.1. First}", "prose",
        r"\subsection{S9.1. Duplicate number}", "prose",
        r"\subsection{S9.4. Gap below me}", "prose",
        r"\subsection{S7.1. Wrong parent}", "prose",
        r"\subsection{Bare title}", "prose",
    ])

    def test_the_duplicate_rule_fires(self):
        seen = defaultdict(list)
        for sec, sub, title, _ in _numbered(self.BROKEN):
            seen[(sec, sub)].append(title)
        assert [k for k, v in seen.items() if len(v) > 1] == [(9, 1)]

    def test_the_gap_rule_fires(self):
        subs = sorted(s for sec, s, _, _ in _numbered(self.BROKEN) if sec == 9)
        assert subs != list(range(min(subs), min(subs) + len(subs)))

    def test_the_parent_rule_fires(self):
        assert [(sec, _owning_section(self.BROKEN, pos))
                for sec, _, _, pos in _numbered(self.BROKEN)
                if _owning_section(self.BROKEN, pos) != sec] == [(7, 9)]

    def test_the_bare_title_rule_fires(self):
        assert [t for _, t in _subsections(self.BROKEN)
                if not re.match(r"S\d+\.\d+\.", t)] == ["Bare title"]

    def test_the_resolution_rule_fires(self):
        have = {(sec, sub) for sec, sub, _, _ in _numbered(self.BROKEN)}
        assert (9, 99) not in have

    def test_a_body_stops_at_the_next_heading(self):
        pos = _numbered(self.BROKEN)[0][3]
        body = _body(self.BROKEN, pos)
        assert "First" in body and "Duplicate" not in body

    def test_stopwords_cannot_carry_a_match(self):
        assert not (_words("this is the section that we see") & _words("both of them also"))
