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
    python scripts/apply_vocabulary.py [--check] [paper.tex supplement.tex postmortem.tex]

Exit status: 1 if --check found a mechanical change still to make, an unjudged occurrence or a
stale judgment, else 0.
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
    # A10 (3 Oct 2026): the industry's names for the quantities, from the OpenMessaging
    # Benchmark's own result fields -- publishLatency (acknowledgment less send),
    # publishDelayLatency (send less the intended send) and endToEndLatency (receipt less
    # send). The producer's act is to publish. Compounds only: bare "send" has other senses
    # (a TCP segment sent again, a broker sending a fetch response) and is in REVIEW.
    # Words of a compound may sit either side of a line break in the source, hence \s+.
    (r"\bsend-referenced\b", "publish-referenced"),
    (r"\bSend-referenced\b", "Publish-referenced"),
    (r"\bper-send\b", "per-publish"),
    (r"\bsend-to-", "publish-to-"),
    (r"\bsend-lag\b", "publish-delay"),
    (r"\bsend\s+lags\b", "publish delays"),
    (r"\bsend\s+lag\b", "publish delay"),
    (r"\bSend\s+lag\b", "Publish delay"),
    (r"\bsend\s+calls\b", "publish calls"),
    (r"\bsend\s+call\b", "publish call"),
    (r"\bsend\s+rates\b", "publish rates"),
    (r"\bsend\s+rate\b", "publish rate"),
    (r"\bSend\s+rate\b", "Publish rate"),
    (r"\bsend\s+schedule\b", "publish schedule"),
    (r"\bsend\s+instants\b", "publish instants"),
    (r"\bsend\s+instant\b", "publish instant"),
    (r"\bsend\s+phases\b", "publish phases"),
    (r"\bsend\s+phase\b", "publish phase"),
    (r"\bsend\s+intervals\b", "publish intervals"),
    (r"\bsend\s+interval\b", "publish interval"),
    (r"\bsend\s+timestamps\b", "publish timestamps"),
    (r"\bsend\s+timestamp\b", "publish timestamp"),
    (r"\bsend\s+workers\b", "publish workers"),
    (r"\bsend\s+future\b", "publish future"),
    (r"\bsending\s+thread\b", "publishing thread"),
    (r"\ban\s+acknowledgment\s+lag\b", "a publish latency"),
    (r"\bAn\s+acknowledgment\s+lag\b", "A publish latency"),
    (r"\backnowledgment\s+lags\b", "publish latencies"),
    (r"\backnowledgment\s+lag\b", "publish latency"),
    (r"\bAcknowledgment\s+lag\b", "Publish latency"),
    (r"\btrue\s+delivery\s+times\b", "true end-to-end latencies"),
    (r"\btrue\s+delivery\s+time\b", "true end-to-end latency"),
    (r"\ba\s+delivery\s+time\b", "an end-to-end latency"),
    (r"\bA\s+delivery\s+time\b", "An end-to-end latency"),
    (r"\bdelivery-time\b", "end-to-end latency"),
    (r"\bdelivery\s+times\b", "end-to-end latencies"),
    (r"\bdelivery\s+time\b", "end-to-end latency"),
    (r"\bDelivery\s+times\b", "End-to-end latencies"),
    (r"\bDelivery\s+time\b", "End-to-end latency"),
    # Karimov et al.'s processing-time latency: from the record reaching the consumer to its
    # output. Its companion, event-time latency, is the paper's E, renamed by hand because the
    # old name it had, end-to-end latency, is now D's and only a reading can tell them apart.
    # 4 Oct 2026: the latency a one-clock tool cannot measure, and the model's factor in it.
    (r"\bone-way\s+delivery\b", "one-way latency"),
    (r"\bdelivery\s+factor\b", "latency factor"),
    # 4 Oct 2026: Linux's name. /proc/stat's field is steal, top prints st, mpstat %steal, and
    # KVM's interface is MSR_KVM_STEAL_TIME; the quantity is steal time.
    (r"\bstolen\s+(?:processor\s+|virtual-CPU\s+|vCPU\s+)?time\b", "steal time"),
    (r"\ba\s+handling\s+span\b", "a processing-time latency"),
    (r"\bhandling\s+spans\b", "processing-time latencies"),
    (r"\bhandling\s+span\b", "processing-time latency"),
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
    # Not `\bindependent\b`, for the reason `flight` is not `\bflights?\b`.
    # Two senses share the spelling. One is structural -- two waits being probabilistically
    # independent -- and this paper has a measured position on it, in bold, at a median
    # correlation of 0.84 and a 12.4x mispricing. The other means "by a separate route",
    # and it is what "arrived at independently" and "one independent harness" say; that
    # sense was never retired and eleven of the thirteen occurrences carry it. Listing the
    # bare word would file eleven judgments about prose needing none and bury the one that
    # matters, which is the failure mode round 68 found in `flight`.
    # So the pattern is the structural sense, reached through the nouns the claim is about.
    # It is deliberately a little eager: a neighbouring clause's "timestamps" can pull an
    # innocent sentence in, and a recorded judgment saying so costs one line and outlives a
    # cleverer pattern. The Conclusion's "threads that wait for a core independently", which
    # is what this entry exists for, matches on both nouns.
    ("independence",
     r"\b(?:wait|waits|waiting|waited|delay|delays|delaying|stall|stalls|thread"
     r"|threads|timestamp|timestamps)\b[^.]{0,110}?\bindependent(?:ly|ce)?\b",
     "independent(ly) of two waits -> on their own account (they are measured correlated)"),
    # A10 (3 Oct 2026). The producer publishes; "send" survives only where something else
    # sends -- TCP, a broker answering a fetch, a request on the wire -- and each such line is
    # adjudicated. The scheduling policies are Linux's: real-time and normal (sched(7)).
    # Not the compounds MECHANICAL renames, which would otherwise be reported and then fixed.
    ("send", r"(?<![-\w])(?:[Ss]end|[Ss]ends|[Ss]ent|[Ss]ending)(?![-\w])"
             r"(?!\s+(?:lags?|calls?|rates?|schedule|instants?|phases?|intervals?|timestamps?"
             r"|workers|future|thread)\b)",
     "send -> publish where the producer acts; otherwise adjudicate"),
    # The hyphenated compounds the pattern above steps over, other than those MECHANICAL
    # renames; "per-send" and "send-to-acknowledgment" survived the first pass that way.
    ("send-compound", r"(?<![\w-])[Ss]end-(?!referenced\b|lag\b|to-)\w+|\b(?!per-send\b)\w+-send\b",
     "a compound of send -> its publish form where the producer acts"),
    ("go-first", r"\b[Gg]o-first\b", "go-first -> real-time priority"),
    ("ordinary", r"\b[Oo]rdinary\b(?!\s+least\s+squares)",
     "ordinary -> normal where it names the scheduling policy (sched(7))"),
    ("brake", r"\bbrakes?\b", "brake -> stopping rule"),
    ("emission", r"\bemission\b", "emission -> event time / publish (the replay's schedule)"),
]

#: Regions that are not prose. Each is matched non-greedily and protected verbatim.
ISLANDS = re.compile(
    r"(?m)^%[^\n]*"                                # comment lines -- [^\n], not .*: the
                                                   # flag below is DOTALL and .* would run
                                                   # from the first comment to end of file
    r"|\\begin\{equation\*?\}.*?\\end\{equation\*?\}"
    r"|\\begin\{(?:verbatim|lstlisting)\}.*?\\end\{(?:verbatim|lstlisting)\}"
    # A quotation is its source's prose, not ours: a vendor's "send timestamp" stays as the
    # vendor wrote it (3 Oct 2026, when the publish renaming reached one). Not the quote
    # environment: the documents use it to indent code and their own tables, and an island
    # there hid a table header ("send blocked") from the renaming.
    r"|``.*?''"
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

    def sub_all(c):
        for rx, rep in MECHANICAL:
            def repl(m, rep=rep):
                line = whole.count("\n", 0, offset + m.start()) + 1
                changes.append("%s:%d  %s -> %s" % (name, line, m.group(0), rep))
                return rep
            c = re.sub(rx, repl, c)
        return c
    # --check runs the substitutions too, and keeps the text. It used to return before them,
    # so a bare "stamp" passed every check: four of them reached Supplement S3.10 on 3 Oct.
    done = sub_all(chunk)
    return chunk if check else done


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", default=["paper.tex", "supplement.tex", "postmortem.tex"])
    ap.add_argument("--check", action="store_true", help="report only; change nothing")
    args = ap.parse_args(argv)
    judgments = load_adjudications()
    used = set()
    unjudged = mechanical = 0
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
        mechanical += len(changes)
    # A judgment that matched nothing is not harmless: it says a sentence was read and
    # cleared, and that sentence is no longer there. Reported as loudly as an unjudged
    # occurrence, and for the same reason -- the list is only worth having if it is exact.
    stale = [j for j in judgments
             if id(j) not in used and j["file"] in args.files]
    for j in stale:
        print("   STALE  %s  %s  matched nothing: %s"
              % (j["file"], j["key"], j.get("anchor") or j.get("requires")))
    return 1 if (args.check and (unjudged or stale or mechanical)) else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
