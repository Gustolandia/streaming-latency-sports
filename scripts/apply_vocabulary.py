#!/usr/bin/env python3
"""
apply_vocabulary.py
The one-pass vocabulary substitution of docs/writing_standards.md section A, applied to the
PROSE of paper.tex and supplement.tex and to nothing else.

What "prose" excludes, and why: comment lines (they are the revision record), math (symbols
are not words), \\texttt{} / \\brk{} arguments (they quote code, and `publishTimestamp`
or `stamp_ns` must not be touched), macro names (\\stampingpriority is an identifier), and
labels/refs/cites (keys). A rewrite that reached into any of those would break the build or
falsify a quotation, so the substitutions run only on runs of text between those islands.

The substitutions are the mechanical ones -- word for word. The ones that need a sentence
rewritten (instrument -> "timestamp resolution" or "the benchmark tool" depending on what was
meant; flight -> delivery or the measured interval; arm -> configuration or treatment) are
listed in REVIEW and reported with their line numbers rather than changed blind.

Every change is printed as  file:line  before -> after  so the diff can be read.

CLI:
    python scripts/apply_vocabulary.py [--check] [paper.tex supplement.tex]
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: (pattern, replacement) on prose only, case handled per match. Order matters: the longer
#: forms first so "timestamping" is not produced from an already-correct "timestamping".
MECHANICAL = [
    (r"\b(?<!time)(?<!Time)stamping\b", "timestamping"),
    (r"\b(?<!time)(?<!Time)stamped\b", "timestamped"),
    (r"\b(?<!time)(?<!Time)stamps\b", "timestamps"),
    (r"\b(?<!time)(?<!Time)stamp\b", "timestamp"),
    (r"\bStamping\b", "Timestamping"),
    (r"\bStamps\b", "Timestamps"),
    (r"\bStamp\b", "Timestamp"),
]

#: Words that need a human sentence, not a substitution. Reported, never changed.
REVIEW = [
    (r"\bflights?\b", "flight -> delivery / the measured interval / T_true after def"),
    (r"\b(?:the|an|our|its|this|that|whatever) instrument\b|\binstrument timescale\b",
     "instrument -> timestamp resolution / timestamping delay / the benchmark tool"),
    (r"\bguards?\b", "guard -> the admission condition (define once) / the > 0 filter"),
    (r"\barms?\b", "arm -> configuration / treatment (or define)"),
    (r"\bquantum\b", "quantum -> timestamp resolution where the sentence allows"),
    (r"\bMode~?[AB]\b", "Mode A/B -> descriptive section title"),
]

#: Regions that are not prose. Each is matched non-greedily and protected verbatim.
ISLANDS = re.compile(
    r"(?m)^%[^\n]*"                                # comment lines -- [^\n], not .*: the
                                                   # flag below is DOTALL and .* would run
                                                   # from the first comment to end of file
    r"|\\begin\{equation\*?\}.*?\\end\{equation\*?\}"
    r"|\\begin\{(?:verbatim|lstlisting)\}.*?\\end\{(?:verbatim|lstlisting)\}"
    r"|\$[^$\n]*\$"                                # inline math
    r"|\\(?:texttt|brk|cite|ref|eqref|label|href|url|includegraphics|input|bibliography"
    r"|bibliographystyle|newcommand|renewcommand|externaldocument)\*?\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
    r"|\\[a-zA-Z@]+",                              # any other command name (not its argument)
    re.S)


def rewrite(text, name, check):
    out, pos, changes, review = [], 0, [], []
    for m in ISLANDS.finditer(text):
        out.append(_prose_pass(text[pos:m.start()], text, pos, name, changes, review, check))
        out.append(m.group(0))
        pos = m.end()
    out.append(_prose_pass(text[pos:], text, pos, name, changes, review, check))
    return "".join(out), changes, review


def _prose_pass(chunk, whole, offset, name, changes, review, check):
    for rx, note in REVIEW:
        for m in re.finditer(rx, chunk):
            line = whole.count("\n", 0, offset + m.start()) + 1
            review.append("%s:%d  %-14s  %s" % (name, line, m.group(0), note))
    if check:
        return chunk

    def sub_all(c):
        for rx, rep in MECHANICAL:
            def repl(m, rep=rep):
                line = whole.count("\n", 0, offset + m.start()) + 1
                changes.append("%s:%d  %s -> %s" % (name, line, m.group(0), rep))
                return rep
            c = re.sub(rx, repl, c)
        return c
    return sub_all(chunk)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", default=["paper.tex", "supplement.tex"])
    ap.add_argument("--check", action="store_true", help="report only; change nothing")
    args = ap.parse_args(argv)
    total = 0
    for f in args.files:
        p = ROOT / f
        text = p.read_text(encoding="utf-8")
        new, changes, review = rewrite(text, f, args.check)
        if changes and not args.check:
            p.write_text(new, encoding="utf-8")
        print("== %s: %d mechanical change(s), %d sentence(s) for review" % (f, len(changes), len(review)))
        for c in changes:
            print("   " + c)
        for r in review:
            print("   REVIEW " + r)
        total += len(changes)
    return 0 if total or args.check else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
