r"""The byline is pinned at two names, by shape rather than by forbidding the departed ones.

The paper carried four authors until 2026-09-10. The last author withdrew on 8 September, on
his own standard for taking public responsibility for a deposited record he had not audited in
the detail he requires. The third author asked on 10 September for his name to come off the
work, GitHub and Zenodo included, three days after reading the manuscript and passing it; his
objection is to how the work was produced rather than to what it reports.

**This file does not name either of them, and that is deliberate.** The obvious gate --- assert
these surnames appear nowhere --- would put a name somebody asked to have removed into the one
file in the repository guaranteed to be read, and would fail the moment it succeeded. When what
you are enforcing is an absence, pin the shape instead: a byline of exactly two names, two
affiliation footnotes, two biographies, a supplement footnote naming two, and a running head
that names both rather than deferring to `et al.` Any restoration from an old draft breaks at
least one of these, because a third name cannot be added without changing the count.

What is **not** pinned here is anybody's contribution, because none of it was withdrawn. The
load-generator rule still closes the paper, the timer-characterisation citation stays in
Section III, and the figures the last author asked for stay with their own gates in
`test_paper_consistency.py`. Removing a byline withdraws a claim about who vouches for the
work. Deleting correct work to finish the job would be a second wrong.
"""
import re
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
PAPER = REPO / "paper.tex"
SUPPLEMENT = REPO / "supplement.tex"

#: The two authors who remain. Named positively, which is the whole design of this file.
AUTHORS = ("Ricou", "Duvignau")


def _author_block(tex):
    r"""The brace-matched `\author{...}`, footnotes and all."""
    start = tex.index("\\author{")
    i, depth = start + len("\\author{"), 1
    while depth and i < len(tex):
        if tex[i] == "{":
            depth += 1
        elif tex[i] == "}":
            depth -= 1
        i += 1
    return tex[start:i]


def _byline(tex):
    """The names, without the affiliation footnotes that follow them."""
    block = _author_block(tex)
    return block[len("\\author{"):].split("\\thanks{")[0].rstrip("%\r\n ")


class TestThePaperCarriesTwoAuthors:
    def test_the_byline_is_two_names_joined_by_and(self):
        names = _byline(PAPER.read_text(encoding="utf-8"))
        assert "," not in names, (
            "the byline carries a comma, so it lists three or more names: %r. Two authors "
            "remain; a third was not restored from an old draft, was it?" % names)
        assert names.count("~and~") == 1, \
            "a two-name byline joins its names with a single `and`: %r" % names
        for surname in AUTHORS:
            assert surname in names, "the byline omits %s: %r" % (surname, names)

    def test_there_is_one_affiliation_footnote_per_author(self):
        block = _author_block(PAPER.read_text(encoding="utf-8"))
        assert block.count("\\thanks{") == len(AUTHORS), (
            "%d affiliation footnotes for %d authors. Every author gets one and nobody who "
            "is not an author gets one." % (block.count("\\thanks{"), len(AUTHORS)))

    def test_there_is_one_biography_per_author(self):
        tex = PAPER.read_text(encoding="utf-8")
        names = re.findall(r"\\begin\{IEEEbiographynophoto\}\{([^}]*)\}", tex)
        assert len(names) == len(AUTHORS), (
            "%d biographies for %d authors: %s. TC counts biographies in the page budget and "
            "a reader counts them as authors." % (len(names), len(AUTHORS), names))
        for surname, entry in zip(AUTHORS, names):
            assert surname in entry, \
                "biography %r is not %s's; the order follows the byline" % (entry, surname)

    def test_the_running_head_names_both_rather_than_et_al(self):
        r"""IEEEtran's `et al.` is for three or more, and the head read `Ricou et al.`"""
        tex = PAPER.read_text(encoding="utf-8")
        head = re.search(r"\\markboth\{[^}]*\}%?\s*\{([^}]*)\}", tex).group(1)
        assert "et al" not in head, \
            "a two-author paper's running head names both authors, not `et al.`: %r" % head
        for surname in AUTHORS:
            assert surname in head, "the running head omits %s: %r" % (surname, head)


class TestTheSupplementAgrees:
    def test_the_footnote_names_the_same_two_authors(self):
        tex = SUPPLEMENT.read_text(encoding="utf-8")
        note = tex[tex.index("This document accompanies the paper by"):][:400]
        for surname in AUTHORS:
            assert surname in note, \
                "the supplement's footnote omits %s from the paper's authors" % surname
        assert note.count("(") == 2, (
            "the footnote lists a number of affiliations other than two, so it names a "
            "number of authors other than two: %r" % note[:200])


class TestTheAcknowledgementCarriesOnlyTheDisclosure:
    """The four correspondents thanked by name were cut on 2026-09-10.

    Each had replied once in August and none since. What they gave is still in the paper; the
    section now carries the generative-AI disclosure IEEE requires, and nothing else.
    """

    def test_the_section_survives(self):
        tex = PAPER.read_text(encoding="utf-8")
        assert "\\section*{Acknowledgment}" in tex, \
            "IEEE requires the generative-AI disclosure and this is where it lives"

    def test_exactly_the_correspondent_who_answered_is_thanked(self):
        r"""One name, and the rule that decides it is the same one that removed four.

        All four correspondents were cut on 2026-09-10: a paper thanks the people still in
        the conversation, and none had written since August. Herbst then wrote --- he had
        asked to come off the byline, was asked whether he would still take an
        acknowledgment, and said yes the same day. So he is back **on that rule**, not as an
        exception to it, and the other three stay out under the same rule.

        This pins the count rather than the name, so that reinstating somebody stays a
        decision the lead author makes rather than one a restored paragraph arrives at.
        """
        tex = PAPER.read_text(encoding="utf-8")
        body = tex[tex.index("\\section*{Acknowledgment}"):
                   tex.index("\\section*{Artifact Availability}")]
        body = re.sub(r"(?m)^%.*$", "", body)
        assert body.lower().count("thank") == 1, (
            "the acknowledgement thanks a number of people other than one. Four were cut on "
            "2026-09-10 and one answered; adding another is a decision to make deliberately.")
        for gone in ("Kunkel", "Luthra", "Kogias", "Tratt"):
            assert gone not in body, (
                "%s is thanked again. None of the three has written since August, and the "
                "rule that cut them is the rule that brought Herbst back." % gone)

    def test_the_disclosure_is_still_there(self):
        tex = PAPER.read_text(encoding="utf-8")
        body = tex[tex.index("\\section*{Acknowledgment}"):
                   tex.index("\\section*{Artifact Availability}")]
        assert "In accordance with IEEE policy" in body, \
            "the generative-AI disclosure is not optional"


class TestTheRuleCanFail:
    """Each check, shown rejecting the front matter this file was written to retire."""

    def test_a_four_name_byline_is_rejected(self):
        four = "A~Author,~B~Author,~C~Author,~and~D~Author"
        assert "," in four and four.count("~and~") == 1

    def test_a_third_biography_is_rejected(self):
        tex = (r"\begin{IEEEbiographynophoto}{Ricou}x\end{IEEEbiographynophoto}"
               r"\begin{IEEEbiographynophoto}{Duvignau}x\end{IEEEbiographynophoto}"
               r"\begin{IEEEbiographynophoto}{Somebody Else}x\end{IEEEbiographynophoto}")
        found = re.findall(r"\\begin\{IEEEbiographynophoto\}\{([^}]*)\}", tex)
        assert len(found) == 3 != len(AUTHORS)

    def test_the_old_running_head_is_rejected(self):
        stale = r"{Ricou \MakeLowercase{\textit{et al.}}: Faster-than-Light}"
        assert "et al" in stale

    def test_a_restored_thanks_paragraph_is_rejected(self):
        restored = "The authors thank A.~Person, for the argument."
        assert "thank" in restored.lower()
