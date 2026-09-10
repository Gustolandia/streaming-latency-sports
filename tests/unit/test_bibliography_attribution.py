"""A placeholder that renders is worse than one that fails to build.

Round 64 added a reference whose author field read *"Apache Pulsar enterprise benchmark
authors"*. There is no such group. The paper has one author and his name is on its first page:
Muhamed Ramees Cheriya Mukkolakkal, Platform Engineering, Brivo Systems. The BibTeX key
compounded it -- `feng2026pulsar` named a person with no connection to the work -- and the
whole entry was built from a referee's note rather than from the PDF, which was sitting in the
reference corpus the entire time.

It rendered. `[S87] Apache Pulsar enterprise benchmark authors, "1.5 million messages per
second on 3 machines..."` printed in the supplement's reference list, and every gate in this
repository passed it, because none of them reads an author field. LaTeX will happily typeset a
sentence describing the authors in the place where the authors go.

**Every other defect this project has found is about its own precision. This one is about
somebody else**, and it is the reference list -- the one part of a paper whose entire job is
attribution.

Two rules here. A `@misc`, `@inproceedings` or `@article` names people, so its author field may
not be a description of them; and a corporate author, which is legitimate and which this
bibliography has several of, is a named organization rather than a phrase about who wrote
something.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
BIB = REPO / "manuscript_references.bib"

#: Corporate authors that are real organizations, each with the entry that carries it. A body
#: that publishes under its own name is a legitimate author; the rule below is about phrases
#: that describe authorship instead of naming it.
CORPORATE = {
    "Hewlett-Packard", "Standard Performance Evaluation Corporation", "OpenMessaging Project",
    "Apache Software Foundation", "Index.dev", "StatsBomb", "IEEE", "Broadcom", "Synadia",
    "IOP Systems", "Linux Kernel Documentation", "National Institute of Standards",
    "Jaeger contributors", "OpenMessaging Benchmark contributors", "Apache Pulsar contributors",
    "Apache Kafka contributors", "Internet Engineering Task Force",
    # "The OpenTelemetry Authors" is the project's own copyright line and the name its
    # specifications are published under, so here the word "Authors" is part of a proper
    # noun rather than a description of who wrote something. The gate flagged it on the
    # first run, which is the rule working: a phrase that looks like a placeholder has to
    # be named as legitimate rather than silently allowed by a looser pattern.
    "OpenTelemetry Authors",
}

#: Words that describe a set of authors rather than naming one. "contributors" is on the list
#: and is also legitimate for a named project, which is why CORPORATE is checked first.
DESCRIPTIVE = (
    r"\bauthors\b", r"\bteam\b", r"\bgroup\b", r"\bet\s+al\b", r"\bvarious\b", r"\bunknown\b",
    r"\banonymous\b", r"\bstaff\b", r"\bmembers\b", r"\bTBD\b", r"\bTODO\b", r"\bXXX\b",
)


def _entries():
    """(key, type, author) for every entry that has an author field."""
    text = BIB.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"@(\w+)\{([^,]+),(.*?)(?=\n@|\Z)", text, re.S):
        body = m.group(3)
        a = re.search(r"author\s*=\s*\{(.*?)\}\s*,\s*\n", body, re.S)
        if not a:
            a = re.search(r"author\s*=\s*\{(.*)\}\s*\n\s*title", body, re.S)
        if a:
            out.append((m.group(2).strip(), m.group(1).lower(),
                        " ".join(a.group(1).split())))
    return out


def test_the_parser_finds_the_bibliography():
    entries = _entries()
    assert len(entries) > 100, \
        "only %d entries parsed; the extractor is broken rather than the file empty" % len(
            entries)


@pytest.mark.parametrize("key,kind,author", _entries())
def test_no_author_field_describes_the_authors_instead_of_naming_them(key, kind, author):
    stripped = author.strip("{} ")
    if any(c.lower() in stripped.lower() for c in CORPORATE):
        return
    hit = [p for p in DESCRIPTIVE if re.search(p, stripped, re.I)]
    assert not hit, (
        "%s's author field is %r, which describes the authors rather than naming them "
        "(matched %s). A reference list exists to attribute; a phrase in the author slot "
        "renders and miscredits somebody. If this is a real corporate author, add it to "
        "CORPORATE with the entry it belongs to." % (key, stripped, hit))


class TestTheEntryThatCausedThis:
    """Round 65's own defect, pinned in both of its halves."""

    def test_the_pulsar_entry_names_its_author(self):
        """One entry, naming the person on the paper's title page.

        The name is pinned by surname rather than by a particular BibTeX spelling. The entry
        that survived this episode predates it and reads `{M. R. C. Mukkolakkal}`, which
        IEEEtran renders correctly; the fuller `{Cheriya Mukkolakkal, Muhamed Ramees}` would
        too. What must not come back is a description where a name belongs.
        """
        text = BIB.read_text(encoding="utf-8")
        assert "Apache Pulsar enterprise benchmark authors" not in text, \
            "the placeholder author is back"
        assert "Mukkolakkal" in text, (
            "the Pulsar benchmark's author is missing. The paper's title page names one "
            "author -- Muhamed Ramees Cheriya Mukkolakkal -- and the PDF is in "
            "docs/reference_tc.")
        assert text.count("arXiv:2603.29113") == 1, (
            "the Pulsar paper has two entries again. It was already in this bibliography, "
            "correctly attributed, when round 64 added a second one under a fabricated "
            "author; look before adding.")

    def test_no_key_names_somebody_who_is_not_an_author(self):
        """`feng2026pulsar` named a person unconnected to the work."""
        text = BIB.read_text(encoding="utf-8")
        assert "feng2026pulsar" not in text, \
            "the key naming an unrelated person is back"
        for doc in ("supplement.tex", "paper.tex",
                    "docs/results/external/literature_regime.csv"):
            body = (REPO / doc).read_text(encoding="utf-8")
            assert "feng2026pulsar" not in body, "%s still cites the retired key" % doc

    def test_the_rule_can_fail(self):
        """The exact string that rendered, and the correction, so the rule cannot go slack."""
        bad = "Apache Pulsar enterprise benchmark authors"
        assert any(re.search(p, bad, re.I) for p in DESCRIPTIVE)
        assert not any(c.lower() in bad.lower() for c in CORPORATE)
        good = "Cheriya Mukkolakkal, Muhamed Ramees"
        assert not any(re.search(p, good, re.I) for p in DESCRIPTIVE)


class TestTheNewCitationWasReadFromItsTitlePage:
    """W1's entry, checked against the PDF rather than against a note about it."""

    def test_the_three_authors_are_named(self):
        text = BIB.read_text(encoding="utf-8")
        i = text.find("@misc{rodriguez2026causal")
        assert i > 0, "the causal-observation entry is missing"
        entry = text[i:text.index("\n}", i)]
        for surname in ("Rodr", "Casta", "Pi"):
            assert surname in entry, "the entry does not name all three authors"

    def test_the_supplement_says_what_it_does_not_show(self, ):
        supp = (REPO / "supplement.tex").read_text(encoding="utf-8")
        i = supp.find("rodriguez2026causal")
        assert i > 0, "the theorem is cited nowhere"
        window = supp[max(0, i - 1500):i + 1500]
        assert "structural rather than evidential" in window, (
            "the passage no longer says the connection is by structure rather than by shared "
            "result. It is a shared-memory concurrency proof; it reports neither failure mode "
            "and claiming more of it than that would be the overreach this project removes.")
