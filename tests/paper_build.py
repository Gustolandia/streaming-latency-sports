"""The paper, its supplement and the postmortem, built for the gates that read what a build
leaves behind.

A build leaves .aux, .bbl, .blg and .log files beside each PDF, and git ignores them. A dozen
gates read them: whether every citation resolved, what BibTeX warned about, whether the
supplement's references into the main text found their labels, how many pages the paper runs
to. Without the files those gates skipped -- in CI always, and in any fresh checkout -- so they
ran only on the author's machine, after a build by hand, against whatever build was last made.

So the test session builds the paper itself whenever those files are missing or older than
anything they are built from. It builds in a scratch folder, from the sources as they stand, by
the README's own sequence: pdflatex, bibtex, pdflatex twice, the paper before the supplement,
whose references into the main text are read from paper.aux, and then the postmortem, whose
references read the archived paper's. Only the files a build leaves
beside a PDF are brought back. The committed PDFs are never touched: they are what a reader
gets, and what the rendered-page gates read.

With MiKTeX on the author's machine and TeX Live in CI, the gates hold the sources to both.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCUMENTS = ("paper", "supplement", "postmortem")
#: What a build leaves beside a PDF. The first four must exist; the rest a document may lack.
NEEDED = (".aux", ".bbl", ".blg", ".log")
LEFT = NEEDED + (".out", ".toc", ".lof", ".lot")
#: What the two documents are built from.
SOURCES = ("paper.tex", "supplement.tex", "postmortem.tex", "manuscript_references.bib")
#: 5 Oct 2026: the postmortem reads the labels of the paper it was written against, the version
#: before the rebuild, from the label map kept with that paper in the archive; without it a
#: scratch build leaves every one of the postmortem's main-text pointers undefined.
SOURCE_FOLDERS = (("docs/generated", "*.tex"), ("docs/results/figures", "*.pdf"),
                  ("docs/archive/2026-10-05-before-cleanup", "paper.aux"))

#: Why the build failed, if it did; the gates that need it say so when they fail.
FAILURE = None


class PaperBuildError(RuntimeError):
    pass


def sources():
    found = [REPO / name for name in SOURCES]
    for folder, pattern in SOURCE_FOLDERS:
        found += sorted((REPO / folder).glob(pattern))
    return found


def is_current():
    """Whether every file the gates need is here and newer than everything it is built from."""
    newest = max(p.stat().st_mtime for p in sources())
    for doc in DOCUMENTS:
        for suffix in NEEDED:
            left = REPO / (doc + suffix)
            if not left.is_file() or left.stat().st_mtime < newest:
                return False
    return True


def _run(command, cwd, ok=(0,)):
    done = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, errors="replace", timeout=600)
    if done.returncode not in ok:
        stem = command[-1].rsplit(".", 1)[0]
        log = Path(cwd) / (stem + (".blg" if command[0] == "bibtex" else ".log"))
        tail = log.read_text(encoding="utf-8", errors="replace")[-3000:] if log.is_file() else ""
        raise PaperBuildError("%s exited %d in the scratch build\n%s\n%s" % (
            " ".join(command), done.returncode, done.stdout[-2000:], tail))
    return done


def build(into=REPO):
    """Build both documents in a scratch folder and bring back what a build leaves beside them."""
    for tool in ("pdflatex", "bibtex"):
        if not shutil.which(tool):
            raise PaperBuildError(
                "%s is not on PATH: the paper gates need a TeX distribution (MiKTeX or TeX Live)"
                % tool)
    scratch = Path(tempfile.mkdtemp(prefix="sbl-paper-build-"))
    try:
        for source in sources():
            target = scratch / source.relative_to(REPO)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for doc in DOCUMENTS:
            latex = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", doc + ".tex"]
            _run(latex, scratch)
            #: 1 is BibTeX's word for "finished, with warnings"; the gates read what it warned.
            _run(["bibtex", doc], scratch, ok=(0, 1))
            _run(latex, scratch)
            _run(latex, scratch)
        for doc in DOCUMENTS:
            for suffix in LEFT:
                made = scratch / (doc + suffix)
                if made.is_file():
                    shutil.copyfile(made, Path(into) / made.name)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def ensure_built():
    """Build if anything the gates need is missing or stale; remember why, if it cannot be."""
    global FAILURE
    try:
        if not is_current():
            sys.stderr.write("building the paper, the supplement and the postmortem for the "
                             "gates that read the build (tests/paper_build.py)\n")
            build()
    except (PaperBuildError, OSError, subprocess.TimeoutExpired) as exc:
        FAILURE = str(exc)
        sys.stderr.write("THE PAPER DID NOT BUILD: %s\n" % FAILURE.splitlines()[0])


def need(name):
    """The path of a file a build leaves, failing -- never skipping -- when it is not there."""
    import pytest
    path = REPO / name
    if not path.is_file():
        pytest.fail("%s is missing: %s" % (name, FAILURE or "the paper was not built "
                                           "(tests/paper_build.py builds it at session start)"),
                    pytrace=False)
    return path


if __name__ == "__main__":
    build()
    print("built: " + ", ".join(d + s for d in DOCUMENTS for s in NEEDED))
