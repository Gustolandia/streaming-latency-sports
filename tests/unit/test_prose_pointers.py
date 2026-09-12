r"""Cross-references that LaTeX cannot check, because they are written as prose.

Both documents point at supplement sections by number in running text --- "Supplement~S19",
"supplementary material S27" --- rather than with `\ref`. There are more than sixty of them,
and until round 45 nothing verified a single one. LaTeX has nothing to warn about: to the
compiler they are words.

What round 45 found at the end of one of those chains. Supplement S22 makes the strongest
claim in Section V --- nine arms, classified in advance by their phase denominator, seven
predicted full and two predicted flat, and every one of them behaving as predicted --- and
said the table backing it was in S27. S27 said the table had gone back to the main text. The
main text had two tables and neither was it. The table was real, correct and gated the whole
time; it was in S19. It had been in the main text for one revision at a reviewer's request,
left again when the page budget tightened, and the move updated neither signpost. So a
nine-fold confirmed prediction reached the reader as a sentence with a pointer to nowhere,
in a paper whose thesis is that a reader should not have to take a number on trust.

Three rules here, in increasing strictness:

  * every pointed-at section exists;
  * a pointer that promises an exhibit --- "the table in S27 states", "S22 draws" --- lands
    on a section that has a float;
  * no section whose own body says its content moved elsewhere is the target of a pointer,
    which is the specific shape of the S22 -> S27 chain.

The third is the one that would have caught it, and it is the one worth keeping: a forwarding
address is not a destination, and a document that leaves them behind will grow more.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent

#: Verbs that promise the reader will find an exhibit, not just discussion, at the far end.
EXHIBIT_VERBS = (
    "states", "gives", "draws", "lists", "tabulates", "plots", "shows", "reproduces",
    "tabulate", "table",
)

#: Phrases by which a section admits its content is somewhere else. A pointer that lands on
#: one of these has not reached the evidence; it has reached a forwarding address.
FORWARDING = (
    "is back in the main text",
    "is not duplicated here",
    "returned to the main text",
    "moved to s",
)


def _read(name):
    r"""The document with its LaTeX comments removed.

    Comments must go before anything reads context around a pointer. A `%` line after
    "(Supplement~S13)" explaining why a figure moved put the word "table" inside the sweep's
    context window and produced a finding about a sentence no reader will ever see. An
    escaped \% is not a comment.
    """
    tex = (REPO / name).read_text(encoding="utf-8")
    return re.sub(r"(?<!\\)%.*", "", tex)


def _sections():
    r"""{number: body} for every `\section{S<n>. ...}` in the supplement."""
    tex = _read("supplement.tex")
    marks = [(int(m.group(1)), m.start()) for m in
             re.finditer(r"\\section\{S(\d+)\.", tex)]
    out = {}
    for i, (num, at) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(tex)
        out[num] = tex[at:end]
    return out


def _pointers():
    r"""Every prose pointer in either document, as (source file, section number, context).

    The context is the remainder of the pointer's **own sentence**, not a fixed window.
    A 160-character window ran two sentences past the pointer and judged it by words that
    had nothing to do with it: round 49 added "...its content is on the flight axis
    (Supplement~S13)." and the window reached forward into "not because the two *states* are
    independent", matched "states" against the exhibit verbs as though it were the verb, and
    demanded a float in S13. The promise a pointer makes is made in the sentence that carries
    it; anything after the full stop belongs to the next claim.

    Round 73 found the same defect one character further out. A sentence can also end at a
    LaTeX structural command rather than at a capital letter, and when round 73's repair to
    Section VIII-C left a pointer as the last thing in its subsection, the window ran past the
    full stop into `\subsection{Threats and limitations} A negative span **shows**...` and
    demanded a float in S29. A sentence boundary is a full stop followed by the next thing,
    and in a `.tex` file the next thing is sometimes a backslash.
    """
    pat = re.compile(
        r"(?:Supplements?~?\s*|supplementary material~?\s*)S(\d+)(?:\.\d+)?", re.I)
    found = []
    for name in ("paper.tex", "supplement.tex"):
        tex = _read(name)
        for m in pat.finditer(tex):
            window = re.sub(r"\s+", " ", tex[m.start(): m.start() + 160])
            end = re.search("(?<=[.:;])" + chr(92) + "s+(?=[A-Z(" + chr(92) * 2
                            + "])", window)
            found.append((name, int(m.group(1)), window[:end.start()] if end else window))
    return found


@pytest.fixture(scope="module")
def sections():
    return _sections()


@pytest.fixture(scope="module")
def pointers():
    return _pointers()


class TestEveryProsePointerHasADestination:

    def test_the_documents_still_point_at_supplement_sections_in_prose(self, pointers):
        """If this drops to zero the rest of the file is vacuous and should be deleted."""
        assert len(pointers) >= 40, (
            "only %d prose pointers found; the regex has stopped matching the house form"
            % len(pointers))

    def test_every_pointed_at_section_exists(self, sections, pointers):
        missing = sorted({(src, num) for src, num, _ in pointers if num not in sections})
        assert not missing, (
            "these point at supplement sections that do not exist: %s"
            % ", ".join("%s -> S%d" % (s, n) for s, n in missing))

    def test_a_pointer_promising_an_exhibit_lands_on_one(self, sections, pointers):
        """"The table in S27 states each rate's cell width" must find a float in S27."""
        bad = []
        for src, num, context in pointers:
            low = context.lower()
            if not any(v in low for v in EXHIBIT_VERBS):
                continue
            body = sections.get(num, "")
            if r"\begin{table}" in body or r"\begin{figure}" in body:
                continue
            bad.append("%s -> S%d (%s...)" % (src, num, context[:70].strip()))
        assert not bad, (
            "these promise the reader an exhibit and land on a section with no table or "
            "figure: %s" % "; ".join(bad))

    def test_no_pointer_lands_on_a_forwarding_address(self, sections, pointers):
        """The S22 -> S27 defect, stated as a rule.

        A section that says its content is elsewhere is not a destination. Either the pointer
        should name the real location or the section should hold the thing again.
        """
        bad = []
        for src, num, context in pointers:
            body = sections.get(num, "").lower()
            hit = next((f for f in FORWARDING if f in body), None)
            if hit is None:
                continue
            # Naming the real destination in the same breath is a redirection a reader can
            # follow, not a dead end: "S27 (moved to S19)" is fine.
            if re.search(r"moved to s\d+|is table~", body[:600]):
                continue
            bad.append("%s -> S%d, whose body says %r" % (src, num, hit))
        assert not bad, (
            "these point at a section that says its content is somewhere else: %s"
            % "; ".join(bad))


class TestTheRuleWouldHaveCaughtTheDefect:
    """Round 45's chain, reconstructed, so the sweep is known to have teeth."""

    def test_a_forwarding_stub_is_detected(self):
        body = ("the table of replicate spread, which this section previously held, is back "
                "in the main text: the reviewer of v2.5 was right. it is not duplicated here.")
        assert any(f in body for f in FORWARDING)

    def test_a_real_section_is_not(self):
        body = ("every commensurate arm shows the spread its position predicts, and this is "
                "the table that lets a reader check it one rate at a time.")
        assert not any(f in body for f in FORWARDING)

    def test_an_exhibit_verb_is_recognised(self):
        context = "the grid table in supplementary material S27 states each rate's cell width"
        assert any(v in context.lower() for v in EXHIBIT_VERBS)


# ------------------------------------------------------- file paths named in prose

#: Directory prefixes that mean "a path in this repository" rather than a class name, a Java
#: package or a URL fragment. Anything inside `\texttt{}` that starts with one of these is a
#: promise the reader can follow, so it has to lead somewhere.
REPO_PREFIXES = ("docs/", "scripts/", "data/", "tests/", "external/", "build/")

#: Paths named in prose that the artefact deliberately does not carry, with the reason. An
#: entry here is a decision someone made and wrote down; a path that is neither present nor
#: listed fails. Keep this short -- it is a list of promises the reader cannot check.
ABSENT_BY_DESIGN = {
    "docs/results/external/novelty_sweep.csv":
        "written by a successful run of scripts/novelty_sweep.py and absent until one "
        "happens; the script refuses to write a partial or unstable sweep, and the prose "
        "that names it says so",
}


def _path_pointers():
    r"""Every repository path named inside `\texttt{}` in either document.

    Round 74's required item. `test_prose_pointers` verified every pointer to a supplement
    *section* and nothing verified a pointer to a *file*, while the two documents named
    twenty-two of them. Two led nowhere.

    The older one is the one that matters. Section VIII-D rests a limitation on the
    benchmark's distributed mode failing on every attempt, S24.1 said the diagnostics "are
    archived in `docs/results/external/dist_diag/`", and there is no such directory --- the
    records are real and sit under `omb_distributed_result.csv`, `dist_load0/` and
    `dist_load50/`. A reader checking the one claim Section VIII-D cannot support with data
    would have looked where they were sent, found nothing, and concluded the record did not
    exist. The project has a commit titled *"An artifact statement may not claim an
    availability its records do not have"*; this is that, one directory down.

    A trailing `*` is read as a glob and satisfied by any match, because
    `stamping_priority*.csv` legitimately names three files.
    """
    pat = re.compile(re.escape(chr(92) + "texttt{") + r"([^}]*)}")
    out = []
    for name in ("paper.tex", "supplement.tex"):
        tex = re.sub(r"(?m)^%[^\n]*", "", _read(name))
        for m in pat.finditer(tex):
            raw = m.group(1)
            if not any(p in raw for p in REPO_PREFIXES):
                continue
            path = (raw.replace(chr(92) + "_", "_")
                       .replace(chr(92) + "%", "%")
                       .replace(chr(92) + "&", "&").strip())
            if not path.startswith(REPO_PREFIXES):
                continue
            context = " ".join(tex[max(0, m.start() - 90):m.start() + 120].split())
            out.append((name, path, context))
    return out


def _resolves(path):
    """True if the path exists, as a file, a directory, or a glob with at least one match."""
    import glob as _glob
    if "*" in path or "?" in path:
        return bool(_glob.glob(str(REPO / path)))
    return (REPO / path).exists()


@pytest.fixture(scope="module")
def path_pointers():
    return _path_pointers()


class TestEveryFilePointerHasAFile:
    r"""A path in `\texttt{}` is a promise the reader can check in one command.

    The section-pointer rules above have been mistaken for covering these since round 45. They
    do not: a `\texttt{docs/...}` is invisible to every one of them, and to LaTeX, and to the
    reader until the moment they look.
    """

    def test_the_documents_still_name_paths(self, path_pointers):
        """If this drops to zero the class below is vacuous and should be deleted."""
        assert len(path_pointers) >= 15, (
            "only %d repository paths found in prose; the pattern has stopped matching"
            % len(path_pointers))

    def test_every_named_path_exists_or_is_listed_as_absent(self, path_pointers):
        bad = []
        for src, path, context in path_pointers:
            if _resolves(path) or path.rstrip("/") in ABSENT_BY_DESIGN:
                continue
            bad.append("%s -> %s (%s...)" % (src, path, context[:80].strip()))
        assert not bad, (
            "these name a path the artefact does not carry, and are not listed in "
            "ABSENT_BY_DESIGN with a reason: %s" % "; ".join(bad))

    def test_an_absent_path_is_disclosed_where_it_is_named(self, path_pointers):
        """Listing a path as absent is a decision; the reader has to be told it too.

        A reason recorded only in this file protects the test suite and nobody else. The
        sentence that names a path the artefact does not carry must say that it does not.
        """
        undisclosed = []
        for src, path, context in path_pointers:
            key = path.rstrip("/")
            if key not in ABSENT_BY_DESIGN:
                continue
            low = context.lower()
            if not any(w in low for w in ("absent", "not committed", "until", "declines",
                                          "not retained", "reconstruct")):
                undisclosed.append("%s -> %s (%s...)" % (src, path, context[:80].strip()))
        assert not undisclosed, (
            "these name a path the artefact does not carry without telling the reader so: %s"
            % "; ".join(undisclosed))

    def test_the_absent_list_has_not_gone_stale(self, path_pointers):
        """An entry for a path nothing names, or for one that has since appeared, is a
        decision about a document that has moved on. Reported as loudly as a broken pointer,
        for the reason round 69 gave about vocabulary adjudications."""
        named = {p.rstrip("/") for _, p, _ in path_pointers}
        stale = sorted(k for k in ABSENT_BY_DESIGN
                       if k not in named or _resolves(k))
        assert not stale, (
            "these are listed as absent by design but are either no longer named in prose or "
            "now present in the artefact: %s" % stale)

    def test_a_path_that_promises_an_archive_is_a_directory_with_something_in_it(
            self, path_pointers):
        """"archived in X/" has to find files, not an empty shell. The S24.1 defect passed
        every other check because the sentence was true of a directory that did not exist;
        it would pass this one too if the directory were created and left empty."""
        bad = []
        for src, path, context in path_pointers:
            low = context.lower()
            if not any(v in low for v in ("archived in", "are in", "committed in")):
                continue
            if path.rstrip("/") in ABSENT_BY_DESIGN:
                continue
            target = REPO / path
            if target.is_dir() and not any(target.iterdir()):
                bad.append("%s -> %s is empty" % (src, path))
        assert not bad, "; ".join(bad)
