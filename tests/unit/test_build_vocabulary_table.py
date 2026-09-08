"""scripts/build_vocabulary_table.py: the committed term table the vocabulary gate reads.

The PDFs are gitignored and pdftotext is a system tool, so the table is the only thing a
test can hold. These tests hand in the text of each "paper" and check that the counts, the
journal split and the manuscript-word classes come out as the arithmetic says they must.
"""
import json
from pathlib import Path

import pytest

import build_vocabulary_table as bvt

#: More than 5,000 characters, so it counts as a readable paper.
LONG = ("the timestamp is read by the kernel and the scheduling latency of a run is "
        "measured per cell; we make three contributions. ") * 80


class TestPdfText:

    def test_returns_what_pdftotext_prints(self, monkeypatch):
        calls = []

        class R:
            stdout = "some text"

        monkeypatch.setattr(bvt.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or R())
        assert bvt.pdf_text(Path("x.pdf")) == "some text"
        assert calls[0][:2] == ["pdftotext", "-q"]

    def test_a_missing_or_hanging_pdftotext_reads_as_empty(self, monkeypatch):
        def boom(cmd, **kw):
            raise OSError("no pdftotext")
        monkeypatch.setattr(bvt.subprocess, "run", boom)
        assert bvt.pdf_text(Path("x.pdf")) == ""


class TestManuscriptWords:

    def test_strips_comments_math_commands_and_stop_words(self):
        tex = ("% a comment with secret\n"
               "The timestamp $x = stampvar$ is \\emph{late}~\\cite{key} and\n"
               "\\begin{equation}eqword\\end{equation} ready-made {braces}.")
        assert bvt.manuscript_words(tex) == ["timestamp", "late", "ready-made", "braces"]


class TestMain:

    def _root(self, tmp_path, monkeypatch, with_manifest=True):
        root = tmp_path
        tc = root / "docs" / "reference_tc"
        corp = root / "docs" / "reference_corpus" / "pdf"
        tc.mkdir(parents=True)
        corp.mkdir(parents=True)
        texts = {"curated.pdf": LONG, "2401.00001v1.pdf": LONG + " stamp ", "W1.pdf": LONG,
                 "short.pdf": "too short to be a paper", "neither.pdf": LONG}
        for k in range(8):
            texts["filler%02d.pdf" % k] = LONG
        (tc / "curated.pdf").write_bytes(b"%PDF")
        for name in texts:
            if name != "curated.pdf":
                (corp / name).write_bytes(b"%PDF")
        (root / "paper.tex").write_text(
            "The timestamp is late; the stamp is ours alone.\n", encoding="utf-8")
        if with_manifest:
            (root / "docs" / "reference_corpus" / "manifest.csv").write_text(
                "arxiv_id,title,journal_ref,categories,year,group,matched,pdf\n"
                "2401.00001v1,A,IEEE Transactions on Computers,cs.PF,2024,journal,tc,http://x\n"
                "W1,C,,openalex,2025,openalex,oa_tc,http://y\n"
                "neither,N,,cs.PF,2023,topic,timestamp,http://z\n", encoding="utf-8")
        monkeypatch.setattr(bvt, "ROOT", root)
        monkeypatch.setattr(bvt, "CORPORA", (tc, corp, root / "docs" / "missing"))
        monkeypatch.setattr(bvt, "pdf_text", lambda p: texts[p.name])
        return root

    def test_writes_the_table_with_the_journal_split(self, tmp_path, monkeypatch, capsys):
        root = self._root(tmp_path, monkeypatch)
        out = root / "docs" / "generated" / "corpus_vocabulary.json"
        assert bvt.main(["--out", str(out)]) == 0
        d = json.loads(out.read_text(encoding="utf-8"))
        # 13 PDFs, one too short to read: 12 papers; the curated one plus the two the
        # manifest marks (journal_ref set, or matched by an oa_/co_ query) are the journal's.
        assert d["corpus_papers"] == 12 and d["journal_papers"] == 3
        assert [Path(s) for s in d["corpus_sources"]] == [Path("docs/reference_tc"),
                                                          Path("docs/reference_corpus/pdf")]
        assert d["phrases"]["timestamp"]["papers"] == 12
        assert d["phrases"]["timestamp"]["share"] == 1.0
        assert d["phrases"]["stamp (bare)"] == {"papers": 1, "total": 1, "share": 0.083,
                                                "journal_papers": 1, "journal_total": 1,
                                                "journal_share": 0.333}
        assert d["phrases"]["we make .* contributions"]["papers"] == 12
        words = d["manuscript_words"]
        assert words["timestamp"]["class"] == "common"
        assert words["stamp"] == {"paper_uses": 1, "corpus_papers": 1, "corpus_share": 0.083,
                                  "class": "rare"}
        assert words["late"]["class"] == "absent"
        assert "late" in d["manuscript_words_absent_from_corpus"]
        assert d["manuscript_words_rare_in_corpus"] == ["stamp"]
        text = capsys.readouterr().out
        assert "corpus papers: 12  (of which the journal's own: 3)" in text
        assert "stamp (bare)" in text

    def test_without_a_manifest_only_the_curated_papers_are_the_journals(
            self, tmp_path, monkeypatch):
        root = self._root(tmp_path, monkeypatch, with_manifest=False)
        out = tmp_path / "t.json"
        assert bvt.main(["--out", str(out)]) == 0
        d = json.loads(out.read_text(encoding="utf-8"))
        assert d["corpus_papers"] == 12 and d["journal_papers"] == 1

    def test_an_unreadable_corpus_scores_everything_absent(self, tmp_path, monkeypatch):
        self._root(tmp_path, monkeypatch)
        monkeypatch.setattr(bvt, "pdf_text", lambda p: "")
        out = tmp_path / "t.json"
        assert bvt.main(["--out", str(out)]) == 0
        d = json.loads(out.read_text(encoding="utf-8"))
        assert d["corpus_papers"] == 0 and d["journal_papers"] == 0
        assert d["phrases"]["timestamp"]["share"] == 0.0
        assert d["phrases"]["timestamp"]["journal_share"] == 0.0
        assert d["manuscript_words"]["timestamp"]["class"] == "absent"
