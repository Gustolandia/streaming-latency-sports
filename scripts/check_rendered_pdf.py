#!/usr/bin/env python3
"""
check_rendered_pdf.py
Scan the *rendered* manuscript for macro residue and unresolved references.

Why this exists rather than a source-level grep. A dropped backslash turns `\\ref{tab:ea6}` into
the literal text "ef{tab:ea6}", and `\\texttt{x}` into "exttt{x}". LaTeX does not complain: the
source still parses, the build reports zero errors, and the defect is visible only in the output.
This happened three times in this project, twice surviving a full source-level check, because the
thing being checked was the input rather than the artefact a reader receives.

Unresolved references are the same class of failure. `\\ref` to a label that does not exist
renders as "??" and emits a warning that is easy to lose in a 3,000-line log.

pdftotext cannot map math-font glyphs, so `$E[\\Delta]$` extracts as "E[]" and `\\approx` as
nothing. Patterns that would fire on those are excluded by construction, not by tolerating a
known count -- a tolerated count silently absorbs the next real defect.

CLI:
    python scripts/check_rendered_pdf.py paper.pdf
    python scripts/check_rendered_pdf.py paper.pdf --text-out build/paper.txt

Exit status is 1 if anything is found, so it can gate a build.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Each entry: (name, pattern, why it matters).
CHECKS = (
    ("unresolved reference", r"\?\?",
     "a \\ref or \\cite to a label that does not exist"),
    ("unrendered tilde", r"(?:Section|Table|Figure)~",
     "a non-breaking space that reached the output as a literal character"),
    ("raw macro escape", r"\\(?:ref|cite|texttt|emph|label|textbf|section)",
     "a backslash survived into the output, so the macro never ran"),
    # The braces must NOT be required here. LaTeX consumes `{` and `}` as grouping characters,
    # so a mangled `\ref{sec:gate}` renders as "efsec:gate" with no brace surviving into the
    # output. An earlier version of this check demanded `ef\{` and therefore passed a manuscript
    # carrying five broken cross-references -- the exact failure the script exists to catch.
    ("lost-backslash residue",
     r"\bef(?:sec|tab|fig|eq|app|alg):|exttt|\bmph\{|\bextbf\{|ectionef|\bef\{|\bite\{",
     "the backslash was eaten and the macro name printed as text"),
    ("literal newline escape", r"\\n\b",
     "a Python-style escape reached the manuscript, usually via a heredoc"),
    ("placeholder left in", r"\b(?:TODO|FIXME|XXX)\b",
     "a note to self that was never resolved"),
    ("empty citation", r"\[\s*,|,\s*\]",
     "a citation list with a missing key"),
    # A command-line flag whose two hyphens were set as one en-dash. \texttt{--cpu} ligatures in
    # the monospace font, so the paper printed a flag nobody could type. Only visible in the
    # rendered output: the source is correct, and TeX reports nothing.
    ("hyphen ligature in a flag", r"–(?:cpu|speedup|plans|max|kafka|redis|out|trial|no)\b",
     "a CLI flag's double hyphen was set as an en-dash"),
)


def extract_text(pdf_path, text_out=None):
    """Rendered text of the PDF. Returns None if no extractor is available."""
    out = Path(text_out) if text_out else Path(tempfile.mkstemp(suffix=".txt")[1])
    if shutil.which("pdftotext"):
        # -layout keeps table cells on their own lines, so a mangled cell is not
        # concatenated with its neighbour into something that looks intentional.
        r = subprocess.run(["pdftotext", "-q", "-layout", str(pdf_path), str(out)],
                           capture_output=True)
        if r.returncode == 0 and out.exists():
            return out.read_text(encoding="utf-8", errors="replace")
    try:
        import pypdf
    except ImportError:
        return None
    reader = pypdf.PdfReader(str(pdf_path))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    out.write_text(text, encoding="utf-8")
    return text


def scan(text):
    """Every check that fired, with context. Empty list means clean."""
    findings = []
    for name, pattern, why in CHECKS:
        for m in re.finditer(pattern, text):
            context = text[max(0, m.start() - 60):m.end() + 60]
            findings.append({"check": name, "why": why, "match": m.group(0),
                             "context": " ".join(context.split())})
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scan the rendered PDF for macro residue")
    ap.add_argument("pdf", nargs="?", default="paper.pdf")
    ap.add_argument("--text-out", default=None, help="keep the extracted text here")
    args = ap.parse_args(argv)

    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"no such PDF: {pdf}")
        return 1

    text = extract_text(pdf, args.text_out)
    if text is None:
        # No extractor is not the same as no defects, and must not read as a pass.
        print("SKIP no PDF text extractor available (install poppler's pdftotext, or pypdf)")
        return 0

    findings = scan(text)
    if not findings:
        print(f"OK rendered text clean ({len(text):,} chars)")
        return 0

    by_check = {}
    for f in findings:
        by_check.setdefault(f["check"], []).append(f)
    print(f"FAIL {len(findings)} finding(s) in the rendered output\n")
    for check, group in by_check.items():
        print(f"  {check} ({len(group)}) -- {group[0]['why']}")
        for f in group[:5]:
            print(f"      ...{f['context']}...")
        if len(group) > 5:
            print(f"      (+{len(group) - 5} more)")
        print()
    return 1


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
