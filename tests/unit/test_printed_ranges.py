r"""Both ends of a printed range must be the same statistic, measured at two points.

Round 68's required item. Section V-D printed

    across our conditions it spans $\exposureLagLo$--$\exposureLagHi\,\mu$s, putting the
    $10$~ms error at $\exposureErrTen$--$\exposureErrTenHi\%$

where `exposureLagLo` and `exposureLagHi` are the tenth and ninetieth percentiles of the
acknowledgment lag -- and `exposureErrTen` is the **median**. So the sentence named a
tenth-to-ninetieth span and then derived from it a range whose bottom was the middle. A
reader who divided 500 by 10,000 got 5%, and the paper printed 7%. The same macro was used
twice in one paragraph, once correctly as the median and once as the bottom of a percentile
band, eight words apart.

**The check is on the names, and it needs no registry.** Every endpoint macro in this
project is named for its end -- `Lo`/`Hi`, `Low`/`High`, `Min`/`Max` -- so the two ends of a
legitimate range strip to the same stem under a *matched* pair of those tokens. A central
value has no such token, which is exactly how `exposureErrTen` differs from
`exposureErrTenLo`, and is exactly the defect. A registry of estimators would have caught
this too and would have to be maintained; the naming convention was already there and was
already true of all thirteen ranges but the broken one.

The tokens may be prefixes, suffixes or infixes: `flipLoSixtyFour`/`flipHiSixtyFour` puts
them in the middle, and the stems still have to match once they are removed.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
RE_BS = chr(92) + chr(92)

#: Matched endpoint families. Order within a pair is (low, high); a range must use one
#: family and must use both of its members, one on each end.
FAMILIES = [("Lo", "Hi"), ("Low", "High"), ("Min", "Max")]

#: `\macroA$--$\macroB`, with the maths delimiters optional so both `$\a$--$\b$` and
#: `$\a--\b$` are caught.
RANGE = re.compile(RE_BS + r"([A-Za-z]+)\}?\$?--\$?" + RE_BS + r"([A-Za-z]+)")
COMMENT = re.compile(r"(?m)^%[^\n]*")


def split_endpoint(name):
    """(stem, family, end) for an endpoint macro, or None if the name carries no end token.

    `Lo` is tried after `Low` so that `rtFactorLow` is not read as stem `rtFactorw`.
    """
    for family in sorted(FAMILIES, key=lambda f: -max(len(t) for t in f)):
        for end, token in zip(("lo", "hi"), family):
            for m in re.finditer(token, name):
                rest = name[:m.start()] + name[m.end():]
                if rest and rest != name:
                    return rest, family, end
    return None


def ranges_in(text):
    return RANGE.findall(COMMENT.sub("", text))


@pytest.mark.parametrize("doc", ["paper.tex", "supplement.tex"])
def test_both_ends_of_a_printed_range_are_the_same_statistic(doc):
    found = ranges_in((REPO / doc).read_text(encoding="utf-8"))
    assert found, "%s printed no two-macro ranges; the pattern has stopped matching" % doc
    for a, b in found:
        sa, sb = split_endpoint(a), split_endpoint(b)
        assert sa is not None, (
            "%s prints a range whose lower end is %r, which carries no endpoint token. A "
            "central value is not the bottom of a band: this is round 68's defect, where "
            "the median of the acknowledgment lag was printed as the low end of a "
            "tenth-to-ninetieth range." % (doc, a))
        assert sb is not None, (
            "%s prints a range whose upper end is %r, which carries no endpoint token."
            % (doc, b))
        assert sa[0] == sb[0], (
            "%s prints %r--%r, whose stems differ (%r vs %r). The two ends of a range are "
            "one statistic at two points." % (doc, a, b, sa[0], sb[0]))
        assert sa[1] == sb[1], (
            "%s prints %r--%r, which mix endpoint families (%r and %r)."
            % (doc, a, b, sa[1], sb[1]))
        assert (sa[2], sb[2]) == ("lo", "hi"), (
            "%s prints %r--%r, which is not a low end followed by a high one."
            % (doc, a, b))


def test_the_rule_rejects_the_defect_it_was_written_for():
    """A central value paired with a high end is what round 68 found, and must fail."""
    assert split_endpoint("exposureErrTen") is None
    assert split_endpoint("exposureErrTenHi") == ("exposureErrTen", ("Lo", "Hi"), "hi")
    assert split_endpoint("exposureErrTenLo") == ("exposureErrTen", ("Lo", "Hi"), "lo")


def test_the_rule_reads_infix_tokens_and_the_longer_family_first():
    assert split_endpoint("flipLoSixtyFour") == ("flipSixtyFour", ("Lo", "Hi"), "lo")
    assert split_endpoint("rtFactorLow") == ("rtFactor", ("Low", "High"), "lo")
    assert split_endpoint("ombGridRetentionMin") == ("ombGridRetention", ("Min", "Max"), "lo")


def test_a_range_across_stems_is_caught(tmp_path):
    doc = tmp_path / "bad.tex"
    doc.write_text(r"the band runs $\alphaLo$--$\betaHi$.", encoding="utf-8")
    (a, b), = ranges_in(doc.read_text(encoding="utf-8"))
    assert split_endpoint(a)[0] != split_endpoint(b)[0]


def test_comment_lines_are_not_scanned():
    text = "%% a comment naming $\\fooLo$--$\\barHi$\nreal text\n"
    assert ranges_in(text) == []
