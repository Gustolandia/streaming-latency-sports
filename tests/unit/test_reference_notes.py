"""A reference prints a citation; what the project knows about the source is kept, unprinted.

An outside editor's reading (28 Sep 2026) found the reference lists doing a second job. Twenty of
the article's forty-five entries and most of the supplement's carried commentary in the printed
`note` field: what a source says, how it bears on the paper, and in two cases the bibliography's
own housekeeping ("Year corrected 2026-09-22 ...", "The key is left as it is because the
supplement cites it"). IEEE references are citations. The commentary moved to `annote`, which
IEEEtran.bst does not print, so the audit trail stays in the repository and the reader gets an
author, a title, a venue, a date and a way to find it.

The same reading turned up a defect no gate had caught: the supplement cited IEEE Std 1241's
clauses as \\S3.4.1 and \\S1.4.1, where the source-verified record says \\S6.4.1 and \\S5.4.1. The
supplement's renumbering of 10 September had rewritten a standard's clause numbers as if they
were its own section numbers. The last class below holds the text to the record.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
BIB = REPO / "manuscript_references.bib"


def _bibliographies():
    """Both reference files, joined: the one the paper and the supplement cite, and the
    postmortem's own, which moved to a file of its own on 7 Oct 2026. An entry is checked
    wherever it lives."""
    return "\n".join((REPO / name).read_text(encoding="utf-8")
                     for name in ("manuscript_references.bib", "postmortem_references.bib"))

#: What a printed note may carry: a locator, an access date, an identifier or a publication
#: detail. Anything left over after these are removed is commentary.
ALLOWED = [
    r"\\url\{[^}]*\}",
    r"Accessed:\s*[A-Z][a-z]{2,3}\.?\s+\d{1,2},\s+\d{4}\.?",
    r"Wayback snapshot [\d-]+ \(id \d+\)",
    r"Available at [\w./-]+/?",
    r"arXiv:\s*\d{4}\.\d{4,5}(v\d+)?",
    # The HP note's "undated, year from its HP Journal citation" left the printed note on
    # 1 Oct 2026 (an outside editor: references are citations, not notes); it lives in annote.
    r"Part no\.\\ [\d-]+",
    r"Revision of IEEE Std [\d-]+",
    r"Obsoletes RFC \d+",
    r"Talk, Strange Loop / QCon",
    # 6 Oct 2026: the talk's venue and place, beside the recording's URL, which the review of
    # that day asked for; a publication detail, like the venue it replaces.
    r"Talk, Strange Loop 2015, St\. Louis, MO, USA",
    r"Version \d+(\.\d+)*",
    r"Issue \\#\d+, opened \d{4}-\d{2}-\d{2}",
    r"\{Open Compute Project\}, Unified Intelligent Infrastructure workstream",
    r"Assigned to the Hewlett-Packard Company",
    r"\d{1,2} [A-Z][a-z]+ \d{4}",
]


def entries(text):
    """{key: body} for every entry."""
    return {m.group(1): m.group(2)
            for m in re.finditer(r"@\w+\{([^,\s]+),(.*?)\n\}", text, re.S)}


def field(body, name):
    """The braced value of one field, inner braces kept; None if absent."""
    m = re.search(r"(?:^|\n)\s*%s\s*=\s*\{" % name, body)
    if not m:
        return None
    depth, j = 1, m.end()
    while j < len(body) and depth:
        depth += {"{": 1, "}": -1}.get(body[j], 0)
        j += 1
    return " ".join(body[m.end():j - 1].split())


def residue(note):
    """What is left of a printed note once every allowed piece is removed."""
    for pattern in ALLOWED:
        note = re.sub(pattern, " ", note)
    return re.sub(r"[\s.,;:]+", " ", note).strip()


def cited(doc):
    bbl = REPO / (doc + ".bbl")
    if not bbl.exists():
        pytest.skip("%s.bbl not built" % doc)
    return set(re.findall(r"\\bibitem\{([^}]+)\}", bbl.read_text(encoding="utf-8",
                                                                errors="replace")))


@pytest.fixture(scope="module")
def bib():
    return entries(_bibliographies())


class TestAPrintedNoteIsACitation:

    @pytest.mark.parametrize("doc", ["paper", "supplement", "postmortem"])
    def test_every_cited_note_is_citation_data_only(self, doc, bib):
        bad = {}
        for key in sorted(cited(doc)):
            note = field(bib.get(key, ""), "note")
            if note and residue(note):
                bad[key] = residue(note)
        assert not bad, "commentary printed in a reference: %s" % bad

    @pytest.mark.parametrize("phrase", [
        "corrected", "key is left", "records what we first read", "Round", "referee",
        "this entry", "the main text", "this paper", "Verified on",
    ])
    def test_no_printed_note_keeps_house(self, phrase, bib):
        printed = [key for key, body in bib.items()
                   if phrase.lower() in (field(body, "note") or "").lower()]
        assert not printed, (phrase, printed)


class TestTheCommentaryIsKept:

    def test_the_audit_trail_moved_rather_than_vanished(self, bib):
        # 82 from 7 Oct 2026, across both reference files, where 95 of 182 entries carried an
        # annote: 13 of the 47 entries nothing cited had one, and they left together on the
        # author's instruction.
        annotated = [key for key, body in bib.items() if field(body, "annote")]
        assert len(annotated) >= 82

    @pytest.mark.parametrize("key,kept", [
        ("indexdev2026brokers", "S1.9 records what we first read here"),
        ("fruth2021telltale", "Year corrected 2026-09-22"),
        ("tahir2022delayed", "corrected 2026-09-22 against Crossref"),
        ("omb_issue216", "inter-node skew, on a same-node report"),
        ("kafka19888", "merged 2025-11-26"),
    ])
    def test_the_notes_an_auditor_needs_are_still_there(self, bib, key, kept):
        assert kept in field(bib[key], "annote")
        assert kept not in (field(bib[key], "note") or "")

    def test_the_rule_would_have_caught_the_entries_it_was_written_for(self):
        assert residue("The key is left as it is because the supplement cites it.")
        assert residue(r"\url{https://www.index.dev/x}; S1.9 records what we first read here.")
        assert not residue(r"\url{https://github.com/apache/kafka}. Accessed: Aug. 31, 2026")
        assert not residue("arXiv:2504.11826")


class TestAStandardsClauseIsNotRenumbered:

    def test_ieee_1241_is_cited_by_its_own_clause_numbers(self, bib):
        record = field(bib["ieee1241"], "annote")
        assert r"\S6.4.1, Eq.~(28)" in record and r"\S5.4.1, Eq.~(18)" in record
        supplement = " ".join((REPO / "postmortem.tex").read_text(encoding="utf-8").split())
        assert r"(\S6.4.1, Eq.~(28))" in supplement
        assert r"(\S5.4.1, Eq.~(18))" in supplement
        assert r"\S3.4.1" not in supplement and r"\S1.4.1" not in supplement
