r"""No control character may sit in a source file, because one has, twice, and silently.

Round 76's referee found two of them in `test_pdf_compliance.py`: a literal TAB where
`\texttt` had been written and a literal backspace, 0x08, where `\brk` had been. Both were
produced the same way -- a shell heredoc expanding `\t` and `\b` before Python ever saw the
text -- and `docs/infrastructure.md` has carried that lesson since round 30. Carrying a
lesson is not the same as gating it.

What makes this worth a test rather than a fix is how it hid. The characters were inside a
`#` comment, so nothing executed them, no linter this project runs objects to a tab, and the
file's own tests all passed. The only visible symptom was that the comment explaining a
typographic repair had become unreadable -- "unbreakable [TAB]exttt identifiers", "what
[BS]rk fixed" -- which a reader would take for a typo rather than for data loss. A backspace
in a tracked file also corrupts terminal output of `git diff` and `git log -p`, so the next
person to read the history would see the damage and not its cause.

The rule is the narrow one that catches this class and nothing else: in text the repository
authors, no C0 control character except newline. Tabs included, deliberately -- this project
indents with spaces everywhere, so a tab is never intentional here and is the exact residue
`\t` leaves behind.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent

#: Directories holding files this project writes by hand. Generated trees, vendored data and
#: third-party captures are excluded: a benchmark's own log may legitimately carry anything,
#: and rewriting one to please a linter would be falsifying evidence.
AUTHORED = ("scripts", "tests", "docs/generated")
AUTHORED_FILES = ("paper.tex", "supplement.tex", "manuscript_references.bib",
                  "docs/infrastructure.md", "docs/writing_standards.md", "README.md")

SUFFIXES = {".py", ".tex", ".bib", ".md", ".cfg", ".toml", ".yml", ".yaml"}

#: Newline is the only C0 character a text file needs. Carriage return is tolerated because
#: the working tree is CRLF on this machine and git normalises it on the way in; every other
#: one is the residue of an escape that was expanded too early.
ALLOWED = {"\n", "\r"}


def _authored_files():
    seen = []
    for rel in AUTHORED:
        root = REPO / rel
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in SUFFIXES and "__pycache__" not in path.parts:
                seen.append(path)
    for rel in AUTHORED_FILES:
        path = REPO / rel
        if path.is_file():
            seen.append(path)
    return seen


def _offenders(text):
    """(index, character) for every C0 control character that is not a newline."""
    return [(i, ch) for i, ch in enumerate(text)
            if ch < " " and ch not in ALLOWED]


class TestNoSourceFileCarriesAControlCharacter:

    def test_the_repository_is_clean(self):
        bad = {}
        for path in _authored_files():
            hits = _offenders(path.read_text(encoding="utf-8", errors="replace"))
            if hits:
                bad[str(path.relative_to(REPO))] = [
                    (i, "0x%02x" % ord(ch)) for i, ch in hits[:5]]
        assert not bad, (
            "control character(s) in authored source. These are almost always a shell "
            "heredoc expanding a backslash escape before the file was written -- \\t "
            "becoming a tab, \\b a backspace. Write the file with the editor tool or a "
            "quoted heredoc and put the backslash back: %s" % bad)

    def test_the_sweep_reaches_the_file_the_defect_was_found_in(self):
        """A gate that silently covered nothing would be worse than no gate."""
        covered = {p.name for p in _authored_files()}
        for name in ("test_pdf_compliance.py", "emit_paper_numbers.py", "paper.tex",
                     "supplement.tex", "stat_intervals.py"):
            assert name in covered, "%s is outside the sweep" % name

    def test_it_would_have_caught_both_of_round_76_s(self):
        """Mutation: the two characters as they actually appeared in the file."""
        assert _offenders("from unbreakable \texttt identifiers")
        assert _offenders("and those are what \brk fixed")
        assert _offenders("a form feed \x0c also counts")

    def test_it_does_not_object_to_ordinary_text(self):
        assert not _offenders("a line\nand another\r\n")
        assert not _offenders(r"a raw \texttt token, backslash intact")
        assert not _offenders("accented text: Quéma, Université, µs")

    def test_the_allowance_is_only_the_line_ending(self):
        assert ALLOWED == {"\n", "\r"}, (
            "widening this set is how the next control character gets in; if one is "
            "genuinely needed, exclude the file and say why")


class TestTheLessonIsRecordedWhereItWillBeRead:

    def test_infrastructure_carries_the_heredoc_lesson(self):
        text = (REPO / "docs" / "infrastructure.md").read_text(encoding="utf-8")
        assert "heredoc" in text.lower()

    @pytest.mark.parametrize("name", ["paper.tex", "supplement.tex"])
    def test_neither_document_carries_one(self, name):
        """The documents are the deliverable, and a control character in a .tex file can
        change what TeX typesets rather than only what a reader of the source sees."""
        assert not _offenders((REPO / name).read_text(encoding="utf-8"))
