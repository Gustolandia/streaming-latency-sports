#!/usr/bin/env python3
"""Does any figure still call something by a name the manuscript has retired?

Round 18's referee found four axis labels reading ``inversion rate`` after the manuscript had
renamed that quantity to ``negative span``. The rename ran over the ``.tex`` sources; the
figures are generated, so their labels lived in a Python string and nothing connected the two.
On page 8 the old name and the new one appeared within centimetres of each other, naming the
same number.

The two gates already in place could not see it. ``figure_legibility`` measures how large the
type is and ``figure_collisions`` measures what is drawn through it; neither reads what the
type says. This one reads it.

**The rule is about the manuscript, not about a word list.** A term counts as retired only
once the documents have stopped using it, so the check arms itself when a rename lands and
stays inert before then. A list of forbidden strings maintained by hand would rot; a list
checked against the prose cannot, because the prose is what decides.

CLI:
    python scripts/figure_vocabulary.py          # check every figure the paper builds
"""

import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: (retired term, what replaced it). Inert until the manuscript stops using the term.
RETIRED = (
    ("inversion", "negative span"),
)

#: The manuscript sources whose vocabulary the figures must match.
SOURCES = ("paper.tex", "supplement.tex")


def manuscript_uses(term, sources=SOURCES, root=None):
    """How many times the manuscript still uses a term, as a word prefix, case-insensitively.

    A prefix rather than a whole word so that "inversions" and "inversion rate" both count:
    a term is not retired while any inflection of it survives.
    """
    root = root or REPO
    pattern = re.compile(r"\b%s" % re.escape(term), re.I)
    total = 0
    for name in sources:
        path = name if os.path.isabs(name) else os.path.join(root, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            total += len(pattern.findall(handle.read()))
    return total


def retired_terms(sources=SOURCES, root=None):
    """The terms the manuscript has actually stopped using, with their replacements."""
    return tuple((term, repl) for term, repl in RETIRED
                 if manuscript_uses(term, sources, root) == 0)


def figure_texts(fig):
    """Every non-empty string a figure will print, deduplicated, in drawing order."""
    from matplotlib.text import Text
    out, seen = [], set()
    for obj in fig.findobj(Text):
        if not obj.get_visible():
            continue
        s = " ".join((obj.get_text() or "").split())
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def offending(fig, sources=SOURCES, root=None):
    """[{term, replacement, text}] for every string in the figure carrying a retired term."""
    live = retired_terms(sources, root)
    if not live:
        return []
    found = []
    for s in figure_texts(fig):
        for term, repl in live:
            if re.search(r"\b%s" % re.escape(term), s, re.I):
                found.append({"term": term, "replacement": repl, "text": s})
    return found


def report(fig, sources=SOURCES, root=None):
    """The shape the other two figure gates return, so `_save` can treat all three alike."""
    return {"retired": offending(fig, sources, root)}


class FigureUsesRetiredTerm(AssertionError):
    """A figure prints a word the manuscript has stopped printing."""


def check(fig, stem, sources=SOURCES, root=None):
    """Raise unless every string in this figure uses the manuscript's current vocabulary.

    Called from `_save`, so a figure carrying a retired name cannot reach the disk. Unlike the
    legibility gate, this applies to every figure whether or not the manuscript includes it:
    a supplement figure names the same quantity as a main-text one, and the reader who meets
    both should meet one name.
    """
    bad = offending(fig, sources, root)
    if not bad:
        return
    lines = ["%s uses a term the manuscript has retired:" % stem]
    for d in bad[:8]:
        lines.append("    %r says %r; the manuscript says %r"
                     % (d["text"], d["term"], d["replacement"]))
    if len(bad) > 8:
        lines.append("    ... and %d more" % (len(bad) - 8))
    raise FigureUsesRetiredTerm("\n".join(lines))


def main(argv=None):
    import argparse
    import sys

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="build/vocabulary")
    args = ap.parse_args(argv)

    live = retired_terms()
    print("retired terms the manuscript no longer uses: %s"
          % (", ".join(t for t, _ in live) or "none"))
    if not live:
        print("nothing to police; the check arms itself when a rename lands")
        return 0

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import make_paper_figures as mpf
    import make_result_figures as mrf

    findings = {}

    def inspect(fig, stem):
        found = offending(fig)
        if found:
            findings[stem] = found
        plt.close(fig)

    saved = [(mrf, mrf._save), (mpf, mpf._save)]
    try:
        mrf._save = lambda fig, out_dir, stem, **kw: (inspect(fig, stem), out_dir)[1]
        for build in (mrf.build_deletion, mrf.build_spectrum, mrf.build_grid,
                      mrf.build_mechanism, mrf.build_ttrue, mrf.build_payload,
                      mrf.build_priority_ladder):
            build(args.out)
        mpf._save = lambda fig, out_dir, stem, **kw: (inspect(fig, stem), [out_dir])[1]
        mpf.main(["--out", args.out])
    finally:
        for module, original in saved:
            module._save = original

    for stem, found in sorted(findings.items()):
        for d in found:
            print("  %-22s %r still says %r; the manuscript says %r"
                  % (stem, d["text"], d["term"], d["replacement"]))
    print("\n%d figure(s) carry a term the manuscript has retired" % len(findings))
    return 1 if findings else 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
