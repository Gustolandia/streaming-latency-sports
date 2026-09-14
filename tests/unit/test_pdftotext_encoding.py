"""Every pdftotext call names its output encoding.

xpdf's pdftotext, the extractor this project runs (4.06, on the author's machine and in CI),
writes Latin-1 unless it is told otherwise, and two things then go wrong without a sound.
Windows decodes Latin-1 bytes without complaint while Linux refuses them, so a check can pass
on one machine and crash on the other. And Latin-1 has no en-dash or em-dash: xpdf writes them
as "-" and "--", so the 48 en-dashes and 60 em-dashes in paper.pdf never reached the checks that
read it, and the rendered-PDF check for a command-line flag set with an en-dash could not fire.

So every argv that starts with "pdftotext", in scripts/ and in tests/, must carry "-enc"
followed by "UTF-8". The scan reads list and tuple literals. An argv assembled some other way
would escape it, and none is assembled that way today.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def pdftotext_argvs(source):
    """(line, names UTF-8) for every list or tuple literal in `source` that starts "pdftotext"."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
            continue
        values = [e.value if isinstance(e, ast.Constant) else None for e in node.elts]
        if values[0] != "pdftotext":
            continue
        found.append((node.lineno, ("-enc", "UTF-8") in list(zip(values, values[1:]))))
    return found


def unencoded(source):
    """Lines of the pdftotext argvs in `source` that leave the encoding to xpdf's default."""
    return [line for line, named in pdftotext_argvs(source) if not named]


def sources():
    """Every Python file the scan covers."""
    return sorted((REPO / "scripts").glob("*.py")) + sorted((REPO / "tests").rglob("*.py"))


class TestTheScanHasTeeth:

    def test_a_call_without_an_encoding_is_flagged(self):
        broken = 'subprocess.run(["pdftotext", "-q", "paper.pdf", "-"], capture_output=True)\n'
        assert unencoded(broken) == [1]

    def test_an_encoding_other_than_utf8_is_flagged(self):
        latin = 'x = 1\nsubprocess.run(("pdftotext", "-enc", "Latin1", "paper.pdf", "-"))\n'
        assert unencoded(latin) == [2]

    def test_utf8_named_anywhere_in_the_argv_passes(self):
        fixed = ('subprocess.run(["pdftotext", "-q", "-layout", "-enc", "UTF-8", str(pdf), '
                 'str(out)])\n')
        assert unencoded(fixed) == []

    def test_an_argv_for_another_program_is_not_read(self):
        other = 'a = ["pdflatex", "-q"]\nb = []\nc = [str(p), "pdftotext"]\nd = ("-enc",)\n'
        assert pdftotext_argvs(other) == []


class TestEveryCallNamesItsEncoding:

    def test_the_scan_finds_the_calls_it_is_about(self):
        """If this drops to nothing the check below passes by finding nothing to check."""
        total = sum(len(pdftotext_argvs(p.read_text(encoding="utf-8"))) for p in sources())
        assert total >= 10, "only %d pdftotext argvs found; has the scan stopped matching?" % total

    def test_no_pdftotext_argv_leaves_the_encoding_to_the_default(self):
        missing = ["%s:%d" % (p.relative_to(REPO).as_posix(), line)
                   for p in sources() for line in unencoded(p.read_text(encoding="utf-8"))]
        assert not missing, (
            "pdftotext without \"-enc\", \"UTF-8\" writes Latin-1, so en-dashes arrive as hyphens "
            "and the text decodes differently on Windows and Linux: %s" % ", ".join(missing))
