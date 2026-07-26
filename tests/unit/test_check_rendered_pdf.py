"""Tests for check_rendered_pdf.

The point of the script is to catch what a source-level check cannot, so the tests feed it the
exact residue strings that got through before: "ef{tab:x}" from a dropped backslash, "??" from a
\\ref to a label that was never defined, and "exttt{" from a mangled heredoc.

The false-positive direction matters as much. pdftotext renders $E[\\Delta]$ as "E[]", and an
earlier version of this check flagged it. A check that cries wolf on correct output gets muted,
and then it is not a check.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_rendered_pdf import CHECKS, extract_text, main, scan  # noqa: E402


class TestScan:
    def test_clean_text_yields_nothing(self):
        assert scan("The rate falls by a factor of 39. See Section 7 and Table 4.") == []

    @pytest.mark.parametrize("text,expected", [
        ("as shown in Table ?? the rate", "unresolved reference"),
        ("see Section~7 for the sweep", "unrendered tilde"),
        (r"the value \ref{tab:ea6} appears", "raw macro escape"),
        ("printed as ef{tab:ea6} instead", "lost-backslash residue"),
        ("the file exttt{LocalWorker.java} at", "lost-backslash residue"),
        (r"a line break\n reached the text", "literal newline escape"),
        ("TODO rewrite this paragraph", "placeholder left in"),
        ("citation [12, ] is short one key", "empty citation"),
    ])
    def test_each_residue_class_is_caught(self, text, expected):
        found = {f["check"] for f in scan(text)}
        assert expected in found, f"{text!r} should trip {expected}, got {found or 'nothing'}"

    def test_math_glyph_dropout_is_not_a_finding(self):
        """pdftotext cannot map Delta or approx. That is the extractor, not the manuscript."""
        assert scan("It is E[], not its variance, that biases a comparison.") == []
        assert scan("Symmetric instrumentation gives E[]  0: noise, no systematic error.") == []

    def test_findings_carry_context_and_reason(self):
        found = scan("the rate " + "x" * 200 + " Table ?? here")
        assert len(found) == 1
        assert found[0]["match"] == "??"
        assert "Table" in found[0]["context"]
        assert found[0]["why"]

    def test_every_check_declares_a_reason(self):
        for name, pattern, why in CHECKS:
            assert name and pattern and why, f"{name} is missing a field"


class TestExtract:
    def test_missing_extractor_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr("shutil.which", lambda _: None)
        monkeypatch.setitem(sys.modules, "pypdf", None)
        # A None module makes `import pypdf` succeed but attribute access fail; force ImportError.
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "pypdf":
                raise ImportError("no pypdf")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert extract_text(tmp_path / "x.pdf") is None

    def test_pdftotext_path_reads_the_output(self, monkeypatch, tmp_path):
        out = tmp_path / "t.txt"

        def fake_run(cmd, **kw):
            Path(cmd[-1]).write_text("extracted body", encoding="utf-8")
            return type("R", (), {"returncode": 0})()

        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/pdftotext")
        monkeypatch.setattr("subprocess.run", fake_run)
        assert extract_text(tmp_path / "x.pdf", out) == "extracted body"

    def test_pypdf_fallback_reads_every_page(self, monkeypatch, tmp_path):
        """The machine that builds the paper has pdftotext; a reviewer's may only have pypdf."""
        import types
        fake = types.ModuleType("pypdf")

        class _Page:
            def __init__(self, t):
                self._t = t

            def extract_text(self):
                return self._t

        class _Reader:
            def __init__(self, _path):
                # A page that extracts as None is normal for image-only pages and must not
                # crash the join.
                self.pages = [_Page("page one"), _Page(None), _Page("page three")]

        fake.PdfReader = _Reader
        monkeypatch.setitem(sys.modules, "pypdf", fake)
        monkeypatch.setattr("shutil.which", lambda _: None)
        out = tmp_path / "o.txt"
        text = extract_text(tmp_path / "x.pdf", out)
        assert text == "page one\n\npage three"
        assert out.read_text(encoding="utf-8") == text

    def test_pdftotext_failure_falls_through_to_pypdf(self, monkeypatch, tmp_path):
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/pdftotext")
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **k: type("R", (), {"returncode": 1})())
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "pypdf":
                raise ImportError("absent")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert extract_text(tmp_path / "x.pdf", tmp_path / "o.txt") is None


class TestCLI:
    def test_missing_pdf_is_an_error(self, tmp_path):
        assert main([str(tmp_path / "absent.pdf")]) == 1

    def test_clean_pdf_passes(self, monkeypatch, tmp_path):
        pdf = tmp_path / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        monkeypatch.setattr("check_rendered_pdf.extract_text", lambda *a, **k: "all fine here")
        assert main([str(pdf)]) == 0

    def test_dirty_pdf_fails(self, monkeypatch, tmp_path, capsys):
        pdf = tmp_path / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        monkeypatch.setattr("check_rendered_pdf.extract_text",
                            lambda *a, **k: "see Table ?? and ef{tab:x}")
        assert main([str(pdf)]) == 1
        out = capsys.readouterr().out
        assert "unresolved reference" in out and "lost-backslash residue" in out

    def test_many_findings_are_truncated_with_a_count(self, monkeypatch, tmp_path, capsys):
        pdf = tmp_path / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        monkeypatch.setattr("check_rendered_pdf.extract_text", lambda *a, **k: "?? " * 9)
        assert main([str(pdf)]) == 1
        assert "+4 more" in capsys.readouterr().out

    def test_no_extractor_does_not_read_as_a_pass(self, monkeypatch, tmp_path, capsys):
        """Returning 0 is deliberate, but it must say SKIP rather than OK."""
        pdf = tmp_path / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        monkeypatch.setattr("check_rendered_pdf.extract_text", lambda *a, **k: None)
        assert main([str(pdf)]) == 0
        out = capsys.readouterr().out
        assert "SKIP" in out and "OK" not in out


class TestTheManuscriptItself:
    def test_the_committed_pdf_is_clean(self):
        pdf = Path(__file__).resolve().parents[2] / "paper.pdf"
        if not pdf.exists():
            pytest.skip("paper.pdf not built")
        text = extract_text(pdf)
        if text is None:
            pytest.skip("no PDF text extractor available")
        findings = scan(text)
        assert not findings, "\n".join(f"{f['check']}: ...{f['context']}..." for f in findings[:8])
