"""A name at the start of a reference note keeps its capital letter.

Round 81 (R2). `IEEEtran.bst` lowercases the first character of every `note` field. For a
sentence fragment that is right ("percentiles from integer-divided milliseconds"). For a name it
is a typo the build cannot see. The article printed "[5] ... Apr. 2026, open Compute Project" and
"[20] ... pp. 1-6, dTrace breakdown", and the supplement's copy of [5] did the same. LaTeX raises
no warning, BibTeX raises no warning, and the words are spelled right, so the only way to catch it
was to read the reference list.

Of the article's 45 notes, 14 are lowercased and 12 of those are fragments, where lowercase is
correct. So the rule cannot be "never lowercase". It is: **a note whose first word is a name
brace-protects that word**, and the rendered `.bbl` keeps its case.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
BIB = REPO / "manuscript_references.bib"


def notes(bib_text):
    """{key: note} for every entry with a note field, inner braces kept."""
    out = {}
    for m in re.finditer(r"@\w+\{([^,\s]+),(.*?)\n\}", bib_text, re.S):
        body = m.group(2)
        n = re.search(r"\bnote\s*=\s*\{", body)
        if not n:
            continue
        depth, j = 1, n.end()
        while j < len(body) and depth:
            depth += {"{": 1, "}": -1}.get(body[j], 0)
            j += 1
        out[m.group(1)] = " ".join(body[n.end():j - 1].split())
    return out


def leading_name(note):
    """The note's first word, or first two, if they are a name the style would lowercase.

    Only a first word that begins with a capital letter can be damaged: the style lowercases one
    character, so a note opening with `\\url{...}`, `\\texttt{...}` or "arXiv" is already what it
    will print. Among those, a name is a word with a capital after its first letter (DTrace,
    GitHub), an all-capitals word (IEEE), or a capitalized word followed directly by another
    (Open Compute). A first word already inside braces is safe and returns None.
    """
    if note.startswith("{"):
        return None
    words = note.split()
    if not words or not re.match(r"[A-Z]", words[0]):
        return None
    first = words[0]
    if re.search(r"[A-Za-z][A-Z]", first) or re.fullmatch(r"[A-Z]{2,}[.,;:]?", first):
        return first.rstrip(".,;:")
    if (len(words) > 1 and re.fullmatch(r"[A-Z][a-z]+", first)
            and re.fullmatch(r"[A-Z][a-z]+[.,;:]?", words[1])):
        return first + " " + words[1].rstrip(".,;:")
    return None


def cited(bbl):
    return re.findall(r"\\bibitem\{([^}]+)\}", bbl)


@pytest.fixture(scope="module")
def bib_notes():
    return notes(BIB.read_text(encoding="utf-8"))


@pytest.mark.parametrize("doc", ["paper", "supplement"])
def test_no_cited_note_lets_the_style_lowercase_a_name(doc, bib_notes):
    bbl = REPO / (doc + ".bbl")
    if not bbl.exists():
        pytest.skip("%s.bbl not built" % doc)
    offenders = sorted((key, leading_name(bib_notes[key]))
                       for key in cited(bbl.read_text(encoding="utf-8", errors="replace"))
                       if key in bib_notes and leading_name(bib_notes[key]))
    assert not offenders, "brace-protect the leading name: %s" % offenders


@pytest.mark.parametrize("doc,present,absent", [
    ("paper", ("Open Compute Project", "DTrace breakdown"), ("open Compute", "dTrace")),
    ("supplement", ("Open Compute Project",), ("open Compute",)),
])
def test_the_rendered_references_keep_the_two_names(doc, present, absent):
    bbl = REPO / (doc + ".bbl")
    if not bbl.exists():
        pytest.skip("%s.bbl not built" % doc)
    flat = " ".join(bbl.read_text(encoding="utf-8", errors="replace").split())
    flat = flat.replace("{", "").replace("}", "")
    for phrase in present:
        assert phrase in flat, phrase
    for phrase in absent:
        assert phrase not in flat, phrase


class TestTheRule:

    @pytest.mark.parametrize("note,name", [
        ("Open Compute Project, Unified Intelligent Infrastructure workstream", "Open Compute"),
        ("DTrace breakdown against a DAG hardware reference", "DTrace"),
        ("IEEE 1588 profile", "IEEE"),
        ("GitHub issue tracker", "GitHub"),
    ])
    def test_the_defects_and_their_kin_are_names(self, note, name):
        assert leading_name(note) == name

    @pytest.mark.parametrize("note", [
        "Physical impossibility as grounds for discarding a trace",
        "Talk, Strange Loop / QCon",
        "Reviewed-by V. Guittot",
        "Section~3, the five quality criteria",
        "Part no. 02-5952-0766",
        "The anomaly attributed to inter-node skew",
        "percentiles from integer-divided milliseconds",
        "{Open Compute Project}, Unified Intelligent Infrastructure workstream",
        "{DTrace} breakdown against a DAG hardware reference",
        "\\url{https://github.com/HdrHistogram/HdrHistogram_c}",
        "\\texttt{recordValue} rejects a negative",
        "arXiv:2504.11826",
        "",
    ])
    def test_fragments_and_protected_names_pass(self, note):
        assert leading_name(note) is None

    def test_the_reader_keeps_inner_braces(self):
        text = "@misc{k,\n  note = {{DTrace} breakdown},\n}\n\n@misc{j,\n  title = {x}\n}"
        assert notes(text) == {"k": "{DTrace} breakdown"}

    def test_the_bibliography_protects_both_entries(self, bib_notes):
        assert bib_notes["sharma2026causality"].startswith("{Open Compute Project}")
        assert bib_notes["villain2012probing"].startswith("{DTrace}")
