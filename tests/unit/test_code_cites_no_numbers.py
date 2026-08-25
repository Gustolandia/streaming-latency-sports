r"""Code may not cite the manuscript by number.

The manuscript never writes an equation number. It writes `\ref{eq:negspan}` and LaTeX
resolves it, so a renumbering fixes every citation at once. The scripts have no such
mechanism, and they wrote the numbers anyway.

Round 35 found `make_result_figures` telling its reader that Figure 7 illustrates "Equation 2"
while the caption that same function emits into the paper says Equation 3. Equation 2 is the
definition of the measured span; Equation 3 is the rate as a function of `T_true`, which is
what the figure draws. Five of the eight equation citations in `scripts/` happened to be right
at the time, which is the problem rather than the consolation: nothing kept them right, and
nobody had reason to check.

The section citations were worse and nobody had looked at all. Seventeen of them, spread over
ten files, every one in the arabic numbering the paper used before the TC restructure --
"Section 6.7", "Section 7.4", "Section 8.3". The manuscript has been Roman I through VII for
many rounds and has no Section 8 whatsoever. These are not stale by a renumbering; they name a
document that no longer exists.

The rule is therefore the simple one: **a script names what it is talking about, or describes
it, and never cites a number it cannot resolve.** "the two-state model", "the rate as a
function of T_true", "the external-campaign section" all survive a renumbering. "Equation 6"
does not.

`ALLOWED` exists for a citation into someone else's numbered document -- an RFC clause, a
standard's section -- where the number is the stable identifier and there is nothing to
resolve it against. Each entry says which document.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
SCRIPTS = REPO / "scripts"

#: A reference into our own manuscript, by a number the code cannot resolve.
PATTERNS = (
    (re.compile(r"\bEquations?\s+\d+", re.I), "equation number"),
    # The period is optional: "Eq 4" cites just as unresolvably as "Eq. 4", and the first
    # version of this pattern required the dot and so missed it. `\b` after `Eqs?` keeps
    # "Equation" out of this rule's way -- it has its own line above.
    (re.compile(r"\bEqs?\b\.?\s*\d+", re.I), "equation number"),
    (re.compile(r"\bSections?\s+\d+(?:\.\d+)*", re.I), "section number"),
)

#: (file, exact text) -> which external numbered document it cites. Nothing here yet: every
#: numbered citation in `scripts/` pointed at our own manuscript.
ALLOWED = {}


def offenders():
    """[(relative path, line, matched text, kind)] for every unresolvable citation."""
    out = []
    for path in sorted(SCRIPTS.glob("*.py")):
        rel = "scripts/%s" % path.name
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for rx, kind in PATTERNS:
                for m in rx.finditer(line):
                    if (rel, m.group(0)) in ALLOWED:
                        continue
                    out.append((rel, n, m.group(0), kind))
    return out


class TestNoScriptCitesTheManuscriptByNumber:

    def test_there_are_no_unresolvable_citations(self):
        bad = offenders()
        assert not bad, (
            "script(s) citing the manuscript by a number nothing can resolve -- name the "
            "thing or describe it instead:\n  "
            + "\n  ".join("%s:%d  %r (%s)" % (f, n, txt, kind) for f, n, txt, kind in bad))

    def test_every_exemption_names_its_document(self):
        assert all(v and len(v) > 10 for v in ALLOWED.values())

    def test_no_exemption_is_stale(self):
        live = {(f, txt) for f, _, txt, _ in offenders()} | {
            k for k in ALLOWED}
        assert all(k in live for k in ALLOWED), "exemption matching nothing"


class TestTheCheckCanFail:
    """The round-35 defect and its neighbours, reconstructed."""

    def test_it_catches_an_equation_number(self):
        rx = PATTERNS[0][0]
        assert rx.search("This is Equation 2 as an experiment")
        assert rx.search("Under Equation 6 an event can be stamped")

    def test_it_catches_the_abbreviated_form(self):
        assert PATTERNS[1][0].search("see Eq. 4 for the retention identity")
        assert PATTERNS[1][0].search("see Eq 4 for the retention identity")

    def test_it_catches_a_section_number(self):
        rx = PATTERNS[2][0]
        assert rx.search("Section 6.7 of the manuscript reported")
        assert rx.search("the 1.66x of Section 8.3")
        assert rx.search("every claim in Section 7 traces to a row")

    def test_a_described_reference_passes(self):
        """What the repair looks like: name the thing, not its number."""
        for ok in ("the rate as a function of T_true",
                   "the two-state model",
                   "the external-campaign section",
                   "eq:negspan"):
            assert not any(rx.search(ok) for rx, _ in PATTERNS), ok

    def test_a_label_is_not_a_number(self):
        assert not any(rx.search(r"\ref{eq:negspan}") for rx, _ in PATTERNS)

    def test_version_and_size_numbers_are_not_citations(self):
        """The rule is about the words Equation and Section, not about digits."""
        for ok in ("Python 3.10", "kernel 6.8", "256 KB", "figsize=(3.50, 2.86)"):
            assert not any(rx.search(ok) for rx, _ in PATTERNS), ok
