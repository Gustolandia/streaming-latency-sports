r"""A range whose endpoints the ledger emits must read from the ledger.

Section VI-B said the real-time collapse was "$7$ to $80\times$" while **eight other sites**
across the two documents read `\rtFactorLow`--`\rtFactorHigh`: the abstract, Contribution 2,
Sections V-C and VI-D, three places in the supplement, and the experiment map, which derives
it from `priority_pairs.summary()`. One site in nine typed what the rest resolved, and it was
in the rules section, which is the part of the paper an author is most likely to lift.

`test_ledger_coverage` could not see it and should not try. That sweep skips bare integers by
design, because integers collide with ordinary prose: an exhaustive count in round 37 found
151 numerals in the main text, 54 of which happened to equal some macro's value and almost all
of which were noise --- "$1$~ms stamp", "$q = 1$", a "$0.5$~ms path". Policing single integers
would drown the signal.

A *range* is different. Two emitted values, in the right order, joined by a dash or by "to",
is not a coincidence; it is the quantity. So this rule looks only at pairs, and derives the
pairs it polices from the documents themselves --- a pair counts only once the documents
already write it as `\A--\B` somewhere, which is the evidence that the two macros belong
together. Nothing is hard-coded and nothing needs maintaining.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
GENERATED = REPO / "docs" / "generated" / "paper_numbers.tex"
DOCS = ("paper.tex", "supplement.tex")

#: How a range gets written when it is typed rather than read. Order matters: the longest
#: joiner first, so "--" is not reported twice as two "-" matches.
JOINERS = (r"\s*--\s*", r"\s+to\s+", r"\s*-\s*")


def macros():
    if not GENERATED.exists():                          # pragma: no cover - built by CI
        pytest.skip("docs/generated/paper_numbers.tex absent; run emit_paper_numbers.py")
    return dict(re.findall(r"\\newcommand\{\\(\w+)\}\{(.*)\}\s*$",
                           GENERATED.read_text(encoding="utf-8"), re.M))


def masked(text):
    """Blank comments, tabular bodies and \\input, keeping line numbers honest."""
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))
    text = re.sub(r"\\begin\{tabular\}.*?\\end\{tabular\}", blank, text, flags=re.S)
    text = re.sub(r"\\input\{[^}]*\}", blank, text)
    return re.sub(r"(?m)%[^\n]*", blank, text)


def macro_ranges():
    """{(lo, hi): (macroA, macroB)} for every pair the documents already write as a range."""
    m = macros()
    out = {}
    for doc in DOCS:
        text = (REPO / doc).read_text(encoding="utf-8")
        for a, b in re.findall(r"\\(\w+)\$?\s*--\s*\$?\\(\w+)", text):
            if a in m and b in m:
                lo, hi = m[a].strip(), m[b].strip()
                if re.fullmatch(r"-?\d+(?:\.\d+)?", lo) and re.fullmatch(r"-?\d+(?:\.\d+)?", hi):
                    out[(lo, hi)] = (a, b)
    return out


def typed_ranges(text):
    """[(line, matched text, macroA, macroB)] for every range written out by hand."""
    found = []
    for (lo, hi), (ma, mb) in macro_ranges().items():
        for joiner in JOINERS:
            pattern = (r"(?<![\d.\w])\$?" + re.escape(lo) + r"\$?" + joiner
                       + r"\$?" + re.escape(hi) + r"(?![\d.])")
            for hit in re.finditer(pattern, text):
                found.append((text.count("\n", 0, hit.start()) + 1,
                              " ".join(hit.group(0).split()), ma, mb))
    # A "--" match also matches the "-" pattern; keep one report per position.
    seen, out = set(), []
    for line, txt, ma, mb in sorted(found):
        if line in seen:
            continue
        seen.add(line)
        out.append((line, txt, ma, mb))
    return out


class TestNoRangeIsTypedWhereItsMacrosExist:

    @pytest.mark.parametrize("doc", DOCS)
    def test_the_document_reads_its_ranges(self, doc):
        bad = typed_ranges(masked((REPO / doc).read_text(encoding="utf-8")))
        assert not bad, (
            "range(s) typed where the ledger emits both endpoints -- the other sites read "
            "the macros and these do not:\n  "
            + "\n  ".join("%s:%d  %r should read \\%s--\\%s" % (doc, ln, txt, a, b)
                          for ln, txt, a, b in bad))

    def test_there_is_at_least_one_macro_range_to_police(self):
        """If ranges stop being written with macros the rule goes quiet; say so loudly."""
        assert macro_ranges(), "no macro range found in either document -- notation changed?"

    def test_the_pairs_come_from_the_documents_not_from_a_list(self):
        """Self-maintaining: a pair is policed because the prose already pairs it."""
        pairs = macro_ranges()
        assert ("7", "80") in pairs, "the real-time collapse range should be discovered"
        assert pairs[("7", "80")] == ("rtFactorLow", "rtFactorHigh")


class TestTheCheckCanFail:
    """The round-37 defect, and the shapes that must not fire."""

    def test_it_finds_the_typed_form(self):
        assert typed_ranges(r"cut the negative-span rate $7$ to $80\times$ at fixed load")

    def test_it_finds_the_dashed_form(self):
        assert typed_ranges(r"the factor ranges $7$--$80\times$ over eight pairs")

    def test_the_macro_form_passes(self):
        assert not typed_ranges(r"collapses it $\rtFactorLow$--$\rtFactorHigh\times$")

    def test_a_lone_endpoint_is_not_a_range(self):
        """Why this rule is about pairs: singletons are the noise the ledger sweep avoids."""
        assert not typed_ranges(r"a $1$~ms stamp, $q = 7$ phases, and $80$ events")

    def test_a_longer_number_containing_an_endpoint_is_not_a_match(self):
        assert not typed_ranges(r"from $170$ to $800$ microseconds")

    def test_a_comment_is_not_policed(self):
        assert not typed_ranges(masked("% the old wording said $7$ to $80\\times$ here\n"))

    def test_one_report_per_site(self):
        r"""`--` also matches the `-` joiner; the site must be named once, not twice."""
        hits = typed_ranges(r"the factor ranges $7$--$80\times$ over eight pairs")
        assert len(hits) == 1
