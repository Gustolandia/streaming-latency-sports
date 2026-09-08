#!/usr/bin/env python3
"""
build_vocabulary_table.py
Turn the reference corpus into a committed term table, and score the manuscript's own
vocabulary against it.

Two inputs, one output:

  docs/reference_tc/*.pdf          the Transactions on Computers papers fetched during review
  docs/reference_corpus/pdf/*.pdf  the journal-ref and topic corpus (gitignored)
      -> docs/generated/corpus_vocabulary.json   committed; the gate reads THIS, never the PDFs

For every word that appears in the manuscript's prose the table records how many corpus
papers use it (document frequency), how many times in total, and a rarity class:

  common    used in >= 10% of corpus papers
  rare      used in 1-9% of corpus papers
  absent    used in none

A word the paper uses that the field does not is not automatically wrong -- but it must be
either replaced by the field's word or defined before use, and the writing-standards gate
holds exactly that. A handful of PHRASES are tracked as well as words, because the field's
objections were to phrases ("the instrument", "in flight" vs "flight").

CLI:
    python scripts/build_vocabulary_table.py [--out docs/generated/corpus_vocabulary.json]
"""
import argparse
import collections
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPORA = (ROOT / "docs" / "reference_tc", ROOT / "docs" / "reference_corpus" / "pdf")

#: Phrases whose presence or absence in the field settles a vocabulary rule. Each is
#: matched case-insensitively on whitespace-normalised text.
PHRASES = {
    "timestamp": r"\btimestamps?\b",
    "time stamp": r"\btime[- ]stamps?\b",
    "stamp (bare)": r"(?<![a-z-])stamp(?:s|ed|ing)?\b",
    "timestamping": r"\btimestamping\b",
    "flight (bare)": r"(?<!in-)(?<!in )\bflights?\b",
    "in-flight": r"\bin[- ]flight\b",
    "the instrument": r"\bthe instrument\b",
    "instrumentation": r"\binstrumentation\b",
    "measurement mechanism": r"\bmeasurement mechanism\b",
    "timestamp resolution": r"\btimestamp resolution\b",
    "clock resolution": r"\bclock resolution\b",
    "scheduling latency": r"\bscheduling latency\b",
    "scheduling delay": r"\bscheduling delay\b",
    "tail latency": r"\btail latency\b",
    "end-to-end latency": r"\bend[- ]to[- ]end latency\b",
    "guard": r"\bguards?\b",
    "experimental arm": r"\b(?:experimental|treatment|control) arms?\b",
    "arm (any)": r"\barms?\b",
    "cell": r"\bcells?\b",
    "per-cell": r"\bper[- ]cell\b",
    "replicate": r"\breplicates?\b",
    "condition": r"\bconditions?\b",
    "run": r"\bruns?\b",
    "grid": r"\bgrid\b",
    "quantum": r"\bquantum\b",
    "quantization": r"\bquanti[sz]ation\b",
    "proxy": r"\bprox(?:y|ies)\b",
    "system model": r"\bsystem model\b",
    "measurement model": r"\bmeasurement model\b",
    "experimental setup": r"\bexperimental setup\b",
    "threats to validity": r"\bthreats to validity\b",
    "we make .* contributions": r"\bwe make (?:\w+ )?contributions\b",
    "our contributions": r"\bour contributions\b",
}

WORD = re.compile(r"[a-z][a-z-]{2,}")
STOP = set("the and for that with this from are was were not but which have has had its "
           "into than then they their there these those also can may our were will been being "
           "such each any all one two per via use used using over under between both while "
           "where when what how why who whom about after before during without within".split())


def pdf_text(path):
    try:
        r = subprocess.run(["pdftotext", "-q", str(path), "-"], capture_output=True,
                           text=True, timeout=180)
        return r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def manuscript_words(tex):
    """Prose words of the manuscript: comments, math, commands and their arguments removed."""
    t = re.sub(r"(?m)^%.*$", "", tex)
    t = re.sub(r"\$[^$]*\$", " ", t)
    t = re.sub(r"\\begin\{equation\*?\}.*?\\end\{equation\*?\}", " ", t, flags=re.S)
    t = re.sub(r"\\(?:cite|ref|label|eqref|href|url|includegraphics|input|bibliography)\{[^}]*\}", " ", t)
    t = re.sub(r"\\[a-zA-Z]+\*?", " ", t)
    t = re.sub(r"[{}~]", " ", t)
    return [w for w in WORD.findall(t.lower()) if w not in STOP]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "generated" / "corpus_vocabulary.json"))
    args = ap.parse_args(argv)

    docs = []
    for d in CORPORA:
        if d.exists():
            docs += sorted(d.glob("*.pdf"))
    texts = {p.name: re.sub(r"\s+", " ", pdf_text(p)).lower() for p in docs}
    texts = {k: v for k, v in texts.items() if len(v) > 5000}   # drop unreadable PDFs
    n = len(texts)

    # Which of these are the JOURNAL's own papers, as opposed to the topic neighbourhood?
    # docs/reference_tc is curated TC papers by construction; the fetched corpus says so in
    # its manifest (journal-ref set, or matched by the venue-comment / OpenAlex queries).
    journal = {p.name for p in (ROOT / "docs" / "reference_tc").glob("*.pdf")}
    manifest = ROOT / "docs" / "reference_corpus" / "manifest.csv"
    if manifest.exists():
        import csv
        with open(manifest, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                same = r.get("journal_ref") or re.search(r"\b(?:co|oa)_", r.get("matched", ""))
                if same:
                    journal.add(re.sub(r"[^A-Za-z0-9.]+", "_", r["arxiv_id"]) + ".pdf")
    journal_texts = {k: v for k, v in texts.items() if k in journal}
    nj = len(journal_texts)

    df, tf = collections.Counter(), collections.Counter()
    for t in texts.values():
        words = set()
        for w in WORD.findall(t):
            tf[w] += 1
            words.add(w)
        df.update(words)

    phrases = {}
    for name, rx in PHRASES.items():
        pat = re.compile(rx)
        docs_with = sum(1 for t in texts.values() if pat.search(t))
        total = sum(len(pat.findall(t)) for t in texts.values())
        j_with = sum(1 for t in journal_texts.values() if pat.search(t))
        j_total = sum(len(pat.findall(t)) for t in journal_texts.values())
        phrases[name] = {"papers": docs_with, "total": total,
                         "share": round(docs_with / n, 3) if n else 0.0,
                         "journal_papers": j_with, "journal_total": j_total,
                         "journal_share": round(j_with / nj, 3) if nj else 0.0}

    paper_words = manuscript_words((ROOT / "paper.tex").read_text(encoding="utf-8"))
    counts = collections.Counter(paper_words)
    scored = {}
    for w, c in counts.items():
        share = df[w] / n if n else 0.0
        cls = "common" if share >= 0.10 else ("rare" if df[w] else "absent")
        scored[w] = {"paper_uses": c, "corpus_papers": df[w], "corpus_share": round(share, 3),
                     "class": cls}

    absent = sorted((w for w, s in scored.items() if s["class"] == "absent"),
                    key=lambda w: -counts[w])
    rare = sorted((w for w, s in scored.items() if s["class"] == "rare"),
                  key=lambda w: -counts[w])

    out = {
        "corpus_papers": n,
        "journal_papers": nj,
        "corpus_sources": [str(d.relative_to(ROOT)) for d in CORPORA if d.exists()],
        "phrases": phrases,
        "manuscript_words": scored,
        "manuscript_words_absent_from_corpus": absent,
        "manuscript_words_rare_in_corpus": rare,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    print("corpus papers: %d  (of which the journal's own: %d)" % (n, nj))
    print("manuscript prose words: %d distinct" % len(scored))
    print("  absent from corpus: %d   rare (<10%% of papers): %d" % (len(absent), len(rare)))
    print("\nmost-used manuscript words the field does not use at all:")
    for w in absent[:25]:
        print("  %-22s x%d" % (w, counts[w]))
    print("\nphrase evidence:")
    for name, v in phrases.items():
        print("  %-28s %4d papers  %6d total  (%.0f%%)" % (name, v["papers"], v["total"], 100 * v["share"]))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
