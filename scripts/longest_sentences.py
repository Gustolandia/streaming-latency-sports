#!/usr/bin/env python3
"""
longest_sentences.py
List the manuscript's longest sentences with their line numbers, the same way
tests/unit/test_sentence_length.py measures them, so the ones that breach the venue range
can be split deliberately rather than found by the gate one at a time.

CLI:
    python scripts/longest_sentences.py [paper.tex] [--top 15] [--over 40]
"""
import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def prose(tex):
    body = tex.split(r"\begin{document}", 1)[-1].split(r"\begin{IEEEbiographynophoto}", 1)[0]
    body = re.sub(r"(?m)^%[^\n]*", "", body)
    body = re.sub(r"\\begin\{(equation\*?|table\*?|figure\*?|IEEEkeywords)\}.*?\\end\{\1\}",
                  " ", body, flags=re.S)
    body = re.sub(r"\\(?:section|subsection|paragraph|label|cite|ref|eqref)\*?\{[^}]*\}", " ", body)
    body = re.sub(r"\$[^$\n]*\$", " X ", body)
    body = re.sub(r"\\[a-zA-Z@]+\*?(\{[^{}]*\})?", " X ", body)
    body = re.sub(r"[{}~]", " ", body)
    return body


def sentences(text):
    # A sentence ends at . ! ? followed by whitespace and an uppercase/quote/digit; the
    # abbreviations the manuscript uses (et al., Fig., vs.) are protected.
    text = re.sub(r"\b(et al|Fig|vs|e\.g|i\.e|cf)\.", lambda m: m.group(0).replace(".", "<dot>"), text)
    out, pos = [], 0
    for m in re.finditer(r"[.!?](?=\s+[A-Z\"'(\d]|\s*$)", text):
        out.append((pos, text[pos:m.end()].replace("<dot>", ".")))
        pos = m.end()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", default="paper.tex")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--over", type=int, default=40)
    args = ap.parse_args(argv)
    raw = (ROOT / args.file).read_text(encoding="utf-8")
    text = prose(raw)
    rows = []
    for pos, s in sentences(text):
        words = len(re.findall(r"[A-Za-z][A-Za-z'-]*", s))
        if words:
            line = raw.count("\n", 0, raw.find(s.strip()[:40])) + 1 if s.strip()[:40] in raw else -1
            rows.append((words, line, " ".join(s.split())))
    rows.sort(reverse=True)
    lengths = sorted(r[0] for r in rows)
    print("sentences: %d   median: %.1f   longest: %d" % (
        len(lengths), lengths[len(lengths) // 2], lengths[-1]))
    print()
    for words, line, s in rows[:args.top]:
        if words < args.over:
            break
        print("%3d words  line ~%-5s %s" % (words, line, s[:170]))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
