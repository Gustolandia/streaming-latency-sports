"""A file is evidence about a journal only if it is the paper it is named after.

Round 60 found a 5.7 KB Cloudflare block page on disk as `timerlat_TC.pdf` -- the manuscript's
own reference [35] and the closest paper at the target venue. Three rounds had recorded the
fetch as failed; each had also left the failure wearing the paper's filename, after which the
corpus reported the paper as held and every venue statistic counted it.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import check_reference_corpus as crc  # noqa: E402

pymupdf = pytest.importorskip("pymupdf")


def _pdf(path, pages, text):
    """A PDF whose first page carries `text`, wrapped so it is really on the page.

    `insert_text` draws one line and clips it at the page edge, which silently made every
    "long" fixture a thin one. The text goes in a box.
    """
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, page.rect.width - 40, page.rect.height - 40),
                            text if i == 0 else "body", fontsize=9)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def corpus(tmp_path):
    d = tmp_path / "reference_tc"
    d.mkdir()
    return d


LONG = ("A Real Title For A Paper With Authors And An Abstract " * 12)[:900]


class TestInspect:
    def test_a_paper_passes(self, corpus):
        assert crc.inspect(_pdf(corpus / "good.pdf", 12, LONG)) is None

    def test_a_bot_wall_is_named_as_one(self, corpus):
        p = _pdf(corpus / "wall.pdf", 1, "Enable JavaScript and cookies to continue")
        assert "bot wall" in crc.inspect(p)

    def test_a_bot_wall_is_caught_even_when_long_enough(self, corpus):
        """The phrase wins over the page floor, so the message names the real cause."""
        p = _pdf(corpus / "wall2.pdf", 9, "Just a moment... " + LONG)
        assert "bot wall" in crc.inspect(p)

    def test_too_few_pages(self, corpus):
        assert "page(s)" in crc.inspect(_pdf(corpus / "short.pdf", 2, LONG))

    def test_a_thin_first_page(self, corpus):
        assert "characters" in crc.inspect(_pdf(corpus / "thin.pdf", 9, "x"))

    def test_an_unreadable_file(self, corpus):
        p = corpus / "broken.pdf"
        p.write_bytes(b"not a pdf at all")
        assert "unreadable" in crc.inspect(p)

    def test_a_truncated_pdf_is_still_read_if_it_can_be(self, corpus):
        """Recorded rather than asserted the other way: MuPDF recovers a clipped file.

        A third of a nine-page PDF still opens, still reports pages and still yields its
        first page, so this check passes it. That is the right answer --- the content is
        there --- and it marks the boundary of what the crude test covers: a fetch that
        produces a *damaged* paper is not caught here, only one that produces no paper.
        """
        whole = _pdf(corpus / "whole.pdf", 9, LONG).read_bytes()
        p = corpus / "truncated.pdf"
        p.write_bytes(whole[: len(whole) // 3])
        crc.inspect(p)   # no verdict asserted; the point is that it does not crash

    def test_without_pymupdf_it_declines_to_judge(self, corpus, monkeypatch):
        """No verdict is better than a wrong one when the reader is missing."""
        p = _pdf(corpus / "good.pdf", 12, LONG)
        monkeypatch.setitem(sys.modules, "pymupdf", None)
        real = __import__

        def no_pymupdf(name, *a, **kw):
            if name == "pymupdf":
                raise ImportError("gone")
            return real(name, *a, **kw)

        monkeypatch.setattr("builtins.__import__", no_pymupdf)
        assert crc.inspect(p) is None


class TestSurvey:
    def test_reports_only_what_is_not_a_paper(self, corpus):
        _pdf(corpus / "good.pdf", 12, LONG)
        _pdf(corpus / "wall.pdf", 1, "Just a moment")
        (corpus / "notes.md").write_text("ignored", encoding="utf-8")
        found = crc.survey(str(corpus))
        assert [n for n, _ in found] == ["wall.pdf"]

    def test_a_missing_corpus_is_not_a_failure(self, tmp_path):
        assert crc.survey(str(tmp_path / "nope")) == []


class TestMain:
    def test_clean_corpus_returns_zero(self, corpus, capsys):
        _pdf(corpus / "good.pdf", 12, LONG)
        assert crc.main(["--corpus", str(corpus)]) == 0
        assert "every file is a paper" in capsys.readouterr().out

    def test_a_block_page_fails_the_check(self, corpus, capsys):
        _pdf(corpus / "good.pdf", 12, LONG)
        _pdf(corpus / "timerlat_TC.pdf", 1, "Enable JavaScript and cookies to continue")
        assert crc.main(["--corpus", str(corpus)]) == 1
        out = capsys.readouterr().out
        assert "NOT A PAPER" in out and "timerlat_TC.pdf" in out
        assert "overcount" in out

    def test_quiet_prints_nothing(self, corpus, capsys):
        _pdf(corpus / "wall.pdf", 1, "Access denied")
        assert crc.main(["--corpus", str(corpus), "--quiet"]) == 1
        assert capsys.readouterr().out == ""

    def test_a_missing_corpus_is_reported_and_passes(self, tmp_path, capsys):
        assert crc.main(["--corpus", str(tmp_path / "nope")]) == 0
        assert "nothing to check" in capsys.readouterr().out

    def test_a_missing_corpus_quietly_passes(self, tmp_path, capsys):
        assert crc.main(["--corpus", str(tmp_path / "nope"), "--quiet"]) == 0
        assert capsys.readouterr().out == ""


def test_the_real_corpus_holds_only_papers():
    """The corpus is gitignored, so this skips where it is absent and bites where it is not."""
    if not Path(crc.CORPUS).is_dir():
        pytest.skip("no local reference corpus")
    bad = crc.survey()
    assert not bad, "files in docs/reference_tc that are not papers: %s" % bad
