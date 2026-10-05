r"""The journal supplement is the paper's evidence, organized the way the paper is.

Until the editorial revision of September 2026 the supplement was a 75-page single-author
postmortem in five parts organized by genre -- chronology, argument, apparatus, literature,
campaign -- so a reader following a pointer from the paper could land in any of eight sections
for one claim. An outside editor read its length and its byline as signs of an undecided paper
and asked for 25-30 pages organized by the paper's sections, with at most fifteen pointers from
the paper. The record itself was worth keeping and is kept, whole, as `postmortem.tex`, archived
with the data and not submitted. What reviewers receive is `supplement.tex`: under the paper's
byline, one section per part of the paper's argument, the evidence in the paper's order.

On 5 October 2026 the paper was rebuilt around four bottom lines and the supplement was cut to
what they need: six sections, S1 to S6, with their subsections merged or deleted and the rest
renumbered. The broker comparison, the withdrawn results and the related work in full (S7 to S9)
went, and with them the front matter's map from every paper section, whose job the paper's own
pointers now do.

These tests hold the shape that answer depends on: the outline, that every pointer from the
paper lands on a section or subsection that exists and that every section is pointed at, the
pointer floor (the author lifted the editor's ceiling on 5 October), the pointers into the
postmortem, the vocabulary, the reference budget and the page budget. Content pins live beside
the content they pin.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
BS = chr(92)

#: The sections in order, and their labels. Six since 5 Oct 2026: S7 (s:brokers), S8
#: (s:withdrawn) and S9 (s:related) were cut, and the postmortem holds their material whole.
OUTLINE = (
    ("S1", "s:setup"),
    ("S2", "s:signcheck"),
    ("S3", "s:failure1"),
    ("S4", "s:failure2"),
    ("S5", "s:tools"),
    ("S6", "s:law"),
)
#: The editor's budget for pointers from the paper into this document (review, section 9) was
#: fifteen. The author lifted it on 5 Oct 2026 when the paper was rebuilt: "No limits on
#: referencing the supplement." Only the floor below is held now.
POINTER = re.compile(r"Supplement~S(\d+)(?:\.(\d+))?(?:\s+and~S(\d+)(?:\.(\d+))?)?")


def _read(name):
    return (REPO / name).read_text(encoding="utf-8")


def _prose(tex):
    body = tex[tex.index(BS + "begin{document}"):]
    return re.sub(r"(?m)(?<!\\)%.*$", "", body)


@pytest.fixture(scope="module")
def supp():
    return _read("supplement.tex")


@pytest.fixture(scope="module")
def paper():
    return _read("paper.tex")


def _sections(tex):
    return [(m.group(1), m.start()) for m in re.finditer(r"\\section\{(S\d+)\.", tex)]


def _headings(tex):
    """Every S-number a heading carries: 'S3', 'S3.4', ..."""
    return set(re.findall(r"\\(?:sub)?section\{(S\d+(?:\.\d+)?)\.", tex))


def _pointers(paper):
    found = []
    for m in POINTER.finditer(_prose(paper)):
        found.append("S%s" % m.group(1) + (".%s" % m.group(2) if m.group(2) else ""))
        if m.group(3):
            found.append("S%s" % m.group(3) + (".%s" % m.group(4) if m.group(4) else ""))
    return found


def test_the_sections_are_in_the_papers_order(supp):
    got = [name for name, _ in _sections(supp)]
    assert got == [s for s, _ in OUTLINE], "the supplement's outline moved: %s" % got
    for name, label in OUTLINE:
        i = supp.index(BS + "section{%s." % name)
        head = supp[i:supp.index("\n", supp.index("\n", i) + 1)]
        assert BS + "label{%s}" % label in head, "%s must carry \\label{%s}" % (name, label)


def test_every_pointer_from_the_paper_lands_on_a_heading(supp, paper):
    heads = _headings(supp)
    bad = [p for p in _pointers(paper) if p not in heads]
    assert not bad, "the paper points at S-numbers no heading here carries: %s" % bad


def test_the_paper_points_at_every_section(supp, paper):
    """A section nobody is sent to is a deletion with extra steps."""
    pointed = {p.split(".")[0] for p in _pointers(paper)}
    missing = [s for s, _ in OUTLINE if s not in pointed]
    assert not missing, "the paper never points at %s" % missing


def test_the_paper_points_at_least_once_per_section(paper):
    """The floor is one pointer per section here, so it moved from nine to six with the cut of
    5 Oct 2026. The editor's ceiling of fifteen went the same day, at the author's word ("No
    limits on referencing the supplement"), so a pointer that helps a referee is never cut to
    fit a count."""
    n = len(POINTER.findall(_prose(paper)))
    assert n >= len(OUTLINE), (
        "%d pointers from the paper, fewer than one per section here, which means the pattern "
        "stopped matching" % n)


def test_no_pointer_uses_the_old_numbering(paper):
    """S10-S37 and 'Part V' were the postmortem's; a pointer to them now lands nowhere."""
    prose = _prose(paper)
    assert not re.search(r"Supplement~S(?:[1-9]\d)", prose), "a pointer into the old numbering"
    assert "Supplement Part" not in prose


def test_every_pointer_into_the_postmortem_names_a_section_it_has(supp):
    post = _read("postmortem.tex")
    heads = _headings(post)
    heads |= {"Part~" + p for p in re.findall(r"\\section\*\{Part ([IVX]+)\.", post)}
    found = re.findall(r"postmortem, (S\d+(?:\.\d+)?|Part~[IVX]+)", " ".join(
        _prose(supp).split()), re.I)
    assert found, "the supplement no longer points into the postmortem"
    bad = sorted({f for f in found if f not in heads})
    assert not bad, "pointers into the postmortem name sections it does not have: %s" % bad


def test_one_name_per_thing(supp):
    """The paper's terminology diet holds here too (editor, section 7)."""
    prose = " ".join(_prose(supp).lower().split())
    for retired in ("got-it delay", "admission condition", "time-to-insight", "scheduling failure",
                    "resolution failure mode", "mode a", "mode b"):
        # Word boundaries: "common-mode and" is not "Mode A".
        hit = re.search(r"\b%s\b" % re.escape(retired), prose)
        assert not hit, "%r is a retired name in the journal supplement: ...%s..." % (
            retired, prose[max(0, hit.start() - 60):hit.end() + 60] if hit else "")


def test_got_it_appears_only_as_the_plans_own_word(supp):
    """The frozen plans call the publish latency 'got-it'; a reader of the freezes needs the
    gloss once, and nothing else here may use the word."""
    prose = " ".join(_prose(supp).split())
    hits = [m.start() for m in re.finditer("got-it", prose)]
    assert len(hits) == 1, "'got-it' should appear once, as the plan's own name: %d" % len(hits)
    assert "The plan's own name for the publish latency" in prose[max(0, hits[0] - 200):hits[0]]


def test_withdrawals_are_told_in_one_place(supp):
    """The postmortem narrates withdrawals everywhere. This document told them in S8 alone
    until 5 Oct 2026, when S8 was cut, so now the postmortem is the one place and this document
    tells none."""
    # A label or a reference is a signpost, not a narration.
    prose = re.sub(r"\\(?:ref|label)\{[^}]*\}", "", _prose(supp))
    hit = re.search(r".{0,60}withdr.{0,60}", prose, re.I | re.S)
    assert not hit, "withdrawal narrated in the journal supplement: %r" % (
        hit.group(0) if hit else "")


def test_no_reviewer_talk(supp):
    prose = " ".join(_prose(supp).lower().split())
    for phrase in ("a reviewer", "the reviewer", "referee", "on review", "reviewers asked"):
        assert phrase not in prose, "%r: the document speaks to its reader, not about one" % phrase


def test_labels_do_not_collide_with_the_papers(supp):
    labels = re.findall(r"\\label\{([^}]*)\}", _prose(supp))
    bad = [lab for lab in labels if not re.match(r"(s|sfig|stab|seq):", lab)]
    assert not bad, "unprefixed labels would collide with the paper's: %s" % bad


def test_the_reference_list_stays_under_sixty():
    """Counted in the built bibliography, not in the source: the tool registry's table and
    other generated inputs cite through macros, and a count of the typed \\cite commands
    read 56 while the printed list held 63 (29 Sep).

    The floor only says the bibliography was built and read. It was 20 against a list of 56
    to 63; the cut of 5 Oct 2026 left 14 references, so it is 10 now."""
    import paper_build
    bbl = paper_build.need("supplement.bbl").read_text(encoding="utf-8", errors="replace")
    n = len(re.findall(r"\\bibitem", bbl))
    assert 10 <= n < 60, (
        "%d references; the editor's budget is under sixty, and fewer than ten means the "
        "bibliography was not built or not read" % n)


def test_the_postmortem_is_named_where_a_reader_starts(supp):
    front = supp[supp.index(BS + "maketitle"):_sections(supp)[0][1]]
    assert "postmortem" in front.lower(), "the front matter must say where the full record is"


def test_the_built_supplement_is_within_budget():
    """The editor's ceiling, 25-30 pages with a little room, still holds. The floor only
    catches a build that lost its content: it was 20 against 30 pages, and the cut of 5 Oct
    2026 left 16, so it is 12 now."""
    import paper_build
    from pypdf import PdfReader
    pdf = paper_build.need("supplement.pdf")
    pages = len(PdfReader(str(pdf)).pages)
    assert 12 <= pages <= 34, (
        "%d pages; the budget is at most 30, with a little room, and under 12 the build lost "
        "content" % pages)


def test_the_postmortem_says_what_it_is():
    """Not the supplementary material any more: the complete record, archived with the data,
    single-author as the second author asked on 8 Sep, and not part of the submission."""
    post = _read("postmortem.tex")
    head = post[post.index(BS + "begin{document}"):post.index(BS + "tableofcontents")]
    flat = " ".join(head.split())
    assert "The Complete Record behind" in flat
    assert "not part of the submission" in flat
    assert "Supplementary Material for" not in flat
    author = re.search(r"\\author\{(.*?)\\thanks", head, re.S).group(1)
    assert "Duvignau" not in author and "Ricou" in author, "the postmortem is single-author"
    assert "R.~Duvignau" in flat, "its footnote still names the paper's second author"
    assert not re.search(r"[Ss]upplementary material~?S\d", post), \
        "a self-reference that now names the other document"
