#!/usr/bin/env python3
"""Build author-free copies of the paper and the supplement.

Why this exists. From 2026-09-09 every PDF that leaves the repository -- the Zenodo record's
files and anything sent as an attachment -- carries no author list. The author list is not
settled -- two authors withdrew, on 2026-09-08 and 2026-09-10 -- and a
circulated PDF is a durable public statement of authorship that a later correction does not
catch up with. The submission build is unchanged: `paper.pdf` and `supplement.pdf` keep their
byline, because a journal submission must name its authors.

What "without authors" means here, precisely, and why each part:

  * the byline goes, replaced by nothing at all -- not by "Anonymous", which asserts a
    double-blind convention this is not, and not by the lead author alone, which would assert
    the very authorship question that is open;
  * the affiliation footnotes go with it, because they name the same people;
  * the author biographies go, for the same reason;
  * the acknowledgment stays. It once thanked correspondents by name, on the rule that a
    credit is true whoever the authors turn out to be and that removing one erases a debt
    rather than a claim; those names were cut from the manuscript itself on 2026-09-10, and
    what remains is the disclosure IEEE requires. The rule is unchanged: this build strips
    claims of authorship and nothing else.

Everything else is byte-for-byte the document the submission carries: same text, same figures,
same numbers, same page count minus the biographies' share.

Usage:
    python scripts/build_without_authors.py            # writes build/no_authors/*.pdf
    python scripts/build_without_authors.py --check    # verify, do not build
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "build", "no_authors")

#: Every name that must not survive into a circulated PDF's front matter or back matter.
AUTHOR_NAMES = ("Ricou", "Duvignau")

# There was an exception list here, for two in-body names that were credits rather than
# claims: `Brendan Gregg`, the author of the `runqlat` post and no relation to the
# co-author who then shared his surname, and one contributor's credit line in the
# supplement. Both authors have since withdrawn, so neither surname is checked any more
# and the credit line is gone from the source. The list went with them rather than
# lingering as an exception to a rule it no longer meets. `Brendan Gregg` still appears
# in the body, correctly, and is now simply not a name this check looks for.


def _strip_author_block(text):
    """Replace `\\author{...}` with an empty one, footnotes and all.

    Brace-matched rather than regex-terminated: the block carries three `\\thanks` with nested
    braces, and a lazy match would stop at the first closing brace inside an e-mail address.
    """
    start = text.index("\\author{")
    i, depth = start + len("\\author{"), 1
    while depth and i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[:start] + "\\author{}" + text[i:], text[start:i]


def _strip_biographies(text):
    """Remove every `IEEEbiographynophoto` environment, and the comment introducing them."""
    return re.sub(r"\\begin\{IEEEbiographynophoto\}.*?\\end\{IEEEbiographynophoto\}\s*",
                  "", text, flags=re.S)


def prepare(name, source_dir=REPO, out_dir=OUT):
    """Write the author-free .tex beside a copy of everything the build needs."""
    path = os.path.join(source_dir, name + ".tex")
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    text, removed = _strip_author_block(text)
    text = _strip_biographies(text)
    target = os.path.join(out_dir, name + ".tex")
    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return target, removed


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode


def build(out_dir=OUT):
    """Both documents, in the order `xr` needs: paper first, then supplement."""
    os.makedirs(out_dir, exist_ok=True)
    # The build reads figures, the bibliography and paper.aux by relative path, so it runs in
    # the repository root with the stripped sources placed there under a distinct name.
    for name in ("paper", "supplement"):
        prepare(name, out_dir=out_dir)
    for name in ("paper", "supplement"):
        staged = os.path.join(REPO, "_noauth_" + name + ".tex")
        shutil.copyfile(os.path.join(out_dir, name + ".tex"), staged)
    # `\externaldocument{paper}` in the supplement points at the submission build's aux file,
    # which is correct: the section numbers are the same in both, and the submission build is
    # the one whose numbering a reader of either PDF will meet.
    for name in ("paper", "supplement"):
        stem = "_noauth_" + name
        for _ in range(2):
            _run(["pdflatex", "-interaction=nonstopmode", stem + ".tex"], REPO)
        _run(["bibtex", stem], REPO)
        for _ in range(2):
            _run(["pdflatex", "-interaction=nonstopmode", stem + ".tex"], REPO)
        produced = os.path.join(REPO, stem + ".pdf")
        if not os.path.exists(produced):                # pragma: no cover - build failure
            raise SystemExit("author-free build failed for %s" % name)
        shutil.move(produced, os.path.join(out_dir, name + ".pdf"))
        # Everything the staged build made, by prefix rather than by a list of extensions.
        # The list missed `.toc`, which the supplement produces and the paper does not, so a
        # stray file survived in the repository root and showed up in `git status`. A build
        # that cleans up by enumerating what it expects will always miss the one it did not.
        for leftover in glob.glob(os.path.join(REPO, stem + ".*")):
            os.remove(leftover)
    return [os.path.join(out_dir, n + ".pdf") for n in ("paper", "supplement")]


def offending_names(pdf_path):
    """Author surnames still readable in a built PDF, minus the ones that may stay."""
    out = subprocess.run(["pdftotext", "-q", "-nopgbrk", pdf_path, "-"],
                         capture_output=True, text=True, errors="replace")
    if out.returncode != 0:                             # pragma: no cover - no poppler
        return None
    text = out.stdout
    return sorted({n for n in AUTHOR_NAMES if n in text})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="report on an existing build instead of rebuilding")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)

    pdfs = ([os.path.join(args.out, n + ".pdf") for n in ("paper", "supplement")]
            if args.check else build(args.out))
    bad = False
    for pdf in pdfs:
        if not os.path.exists(pdf):
            print("missing: %s" % pdf)
            bad = True
            continue
        names = offending_names(pdf)
        if names is None:
            print("%s: built (pdftotext unavailable, not verified)" % pdf)
            continue
        print("%s: %s" % (pdf, "clean" if not names else "STILL NAMES " + ", ".join(names)))
        bad = bad or bool(names)
    return 1 if bad else 0


if __name__ == "__main__":                              # pragma: no cover - CLI
    sys.exit(main())
