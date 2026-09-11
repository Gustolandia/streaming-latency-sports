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

**The tool remembers what has already been judged.** Round 68: `--check` had reported
twenty-five review items for several rounds, so every round re-read all twenty-five from
scratch -- which is how two genuine ones (an undefined "arm" in both documents, in the
sentence reporting the one pre-registered prediction that failed) sat inside twenty-three
correct uses without being separated. A standing report of twenty-five is not a report. The
adjudications now live in `docs/vocabulary_adjudications.json` with a reason each, a clean
run prints nothing, and the exit status is non-zero when either an unjudged occurrence
appears or a judgment stops matching anything -- because an allowance that no longer applies
is a claim about prose that has since moved.

CLI:
    python scripts/apply_vocabulary.py [--check] [paper.tex supplement.tex]

Exit status: 1 if --check found an unjudged occurrence or a stale judgment, else 0.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADJUDICATIONS = ROOT / "docs" / "vocabulary_adjudications.json"

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

#: (key, pattern, advice). Words that need a human sentence, not a substitution: reported,
#: never changed. The key is what an adjudication in docs/vocabulary_adjudications.json
#: names, so that judgments survive rewording of the advice.
#:
#: `flight` is deliberately not `\bflights?\b`. The retired term is the bare noun -- "a
#: flight", the paper-specific name for a message's journey. "pre-flight" and "in-flight"
#: are ordinary technical English and always were: five of the twenty-five standing review
#: items in round 68 were this pattern firing on the wrong side of a hyphen. Allow-listing
#: them would have recorded a judgment about prose that needed none. The pattern was wrong,
#: so the pattern is what changed.
REVIEW = [
    ("flight", r"(?<!-)\bflights?\b(?!-)",
     "flight -> delivery / the measured interval / T_true after def"),
    ("instrument", r"\b(?:the|an|our|its|this|that|whatever) instrument\b"
                   r"|\binstrument timescale\b",
     "instrument -> timestamp resolution / timestamping delay / the benchmark tool"),
    ("guard", r"\bguards?\b", "guard -> the admission condition (define once) / the > 0 filter"),
    ("arm", r"\barms?\b", "arm -> configuration / treatment (or define)"),
    ("quantum", r"\bquantum\b", "quantum -> timestamp resolution where the sentence allows"),
    ("mode-label", r"\bMode~?[AB]\b", "Mode A/B -> descriptive section title"),
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


def load_adjudications(path=None):
    """The standing judgments, as a list of dicts. Missing file means none, not an error.

    The default is resolved here rather than bound in the signature, so that the module
    attribute is read at call time and a test can point the loader somewhere else.

    A judgment is `{file, key, scope, reason}` plus, for scope "line", an `anchor` that must
    appear on the occurrence's own line, and for scope "file", a `requires` string that must
    appear somewhere in the file. `requires` is what keeps a file-wide allowance honest: the
    supplement may use "guard" throughout because it defines the word in its vocabulary
    block, so the allowance is written to depend on that definition still being there. Lose
    the definition and every occurrence comes back.
    """
    try:
        raw = json.loads((path or ADJUDICATIONS).read_text(encoding="utf-8"))
    except OSError:
        return []
    return raw["judgments"]


def _judges(judgments, name, key, line_text, whole):
    """The judgment covering this occurrence, or None. Mutates nothing; marks by identity."""
    for j in judgments:
        if j["file"] != name or j["key"] != key:
            continue
        if j["scope"] == "file" and j["requires"] in whole:
            return j
        if j["scope"] == "line" and j["anchor"] in line_text:
            return j
    return None


def rewrite(text, name, check, judgments=(), used=None):
    out, pos, changes, review = [], 0, [], []
    ctx = (name, judgments, used if used is not None else set())
    for m in ISLANDS.finditer(text):
        out.append(_prose_pass(text[pos:m.start()], text, pos, ctx, changes, review, check))
        out.append(m.group(0))
        pos = m.end()
    out.append(_prose_pass(text[pos:], text, pos, ctx, changes, review, check))
    return "".join(out), changes, review


def _prose_pass(chunk, whole, offset, ctx, changes, review, check):
    name, judgments, used = ctx
    for key, rx, note in REVIEW:
        for m in re.finditer(rx, chunk):
            at = offset + m.start()
            line = whole.count("\n", 0, at) + 1
            start = whole.rfind("\n", 0, at) + 1
            end = whole.find("\n", at)
            line_text = whole[start:end if end >= 0 else len(whole)]
            j = _judges(judgments, name, key, line_text, whole)
            if j is not None:
                used.add(id(j))
                continue
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
    judgments = load_adjudications()
    used = set()
    unjudged = 0
    for f in args.files:
        p = ROOT / f
        text = p.read_text(encoding="utf-8")
        new, changes, review = rewrite(text, f, args.check, judgments, used)
        if changes and not args.check:
            p.write_text(new, encoding="utf-8")
        print("== %s: %d mechanical change(s), %d sentence(s) for review"
              % (f, len(changes), len(review)))
        for c in changes:
            print("   " + c)
        for r in review:
            print("   REVIEW " + r)
        unjudged += len(review)
    # A judgment that matched nothing is not harmless: it says a sentence was read and
    # cleared, and that sentence is no longer there. Reported as loudly as an unjudged
    # occurrence, and for the same reason -- the list is only worth having if it is exact.
    stale = [j for j in judgments
             if id(j) not in used and j["file"] in args.files]
    for j in stale:
        print("   STALE  %s  %s  matched nothing: %s"
              % (j["file"], j["key"], j.get("anchor") or j.get("requires")))
    return 1 if (args.check and (unjudged or stale)) else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
