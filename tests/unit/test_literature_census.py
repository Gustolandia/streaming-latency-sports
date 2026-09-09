"""A claim about what a paper never says is a measurement, so it is measured.

Round 61's referee found that a 2024 survey of 27 stream-processing benchmarks never uses the
word "timestamp". That is the manuscript's gap claim turned from assertion into count -- and a
count typed into the supplement would have been invisible to `test_ledger_coverage`, which
catches a literal colliding with an emitted macro and cannot see a quantity that has only one
source. So it is derived, committed, and emitted.

`docs/reference_tc` is gitignored, so the census runs by hand and the build reads the CSV.
"""
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import literature_census as lc  # noqa: E402

pymupdf = pytest.importorskip("pymupdf")


def _pdf(path, pages, text):
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, page.rect.width - 40, page.rect.height - 40),
                            text if i == 0 else "filler", fontsize=9)
    doc.save(str(path))
    doc.close()
    return path


BODY = ("This benchmark measures latency. Latency matters. A benchmark reports LATENCY "
        "and the benchmark is a benchmark. ") * 3


class TestCensus:
    def test_it_counts_case_insensitively_and_across_inflections(self, tmp_path):
        p = _pdf(tmp_path / "a.pdf", 3, BODY + "Timestamps and timestamp resolution.")
        pages, chars, counts = lc.census(str(p), ("benchmark", "latency", "timestamp"))
        assert pages == 3
        assert chars > 100
        assert counts["latency"] == 9, "three per repetition, three repetitions"
        assert counts["timestamp"] == 2, "timestamps counts as timestamp"

    def test_a_term_that_never_occurs_counts_zero(self, tmp_path):
        p = _pdf(tmp_path / "b.pdf", 2, BODY)
        _pages, _chars, counts = lc.census(str(p), ("quantization",))
        assert counts["quantization"] == 0

    def test_a_missing_file_is_not_a_census(self, tmp_path):
        assert lc.census(str(tmp_path / "nope.pdf"), ("latency",)) is None

    def test_without_pymupdf_there_is_no_census(self, tmp_path, monkeypatch):
        p = _pdf(tmp_path / "c.pdf", 2, BODY)
        real = __import__

        def no_pymupdf(name, *a, **kw):
            if name == "pymupdf":
                raise ImportError("gone")
            return real(name, *a, **kw)

        monkeypatch.setattr("builtins.__import__", no_pymupdf)
        assert lc.census(str(p), ("latency",)) is None


class TestRecord:
    def test_a_missing_record_reads_as_empty(self, tmp_path):
        assert lc.read_record(str(tmp_path / "none.csv")) == []

    def test_counts_for_selects_one_source(self, tmp_path, monkeypatch):
        rec = tmp_path / "census.csv"
        with open(rec, "w", encoding="utf-8", newline="") as handle:
            w = csv.DictWriter(handle, fieldnames=lc.FIELDS)
            w.writeheader()
            w.writerow({"source": "a.pdf", "key": "alpha", "pages": "3", "chars": "900",
                        "term": "latency", "count": "6", "checked_utc": "2026-09-09"})
            w.writerow({"source": "b.pdf", "key": "beta", "pages": "4", "chars": "800",
                        "term": "latency", "count": "9", "checked_utc": "2026-09-09"})
        monkeypatch.setattr(lc, "read_record", lambda path=None: list(
            csv.DictReader(open(rec, encoding="utf-8", newline=""))))
        assert lc.counts_for("alpha") == {"latency": 6}
        assert lc.counts_for("beta") == {"latency": 9}


class TestMain:
    @pytest.fixture
    def corpus(self, tmp_path, monkeypatch):
        d = tmp_path / "corpus"
        d.mkdir()
        _pdf(d / "one.pdf", 3, BODY + " timestamp")
        monkeypatch.setattr(lc, "SOURCES", (("one.pdf", "onekey",
                                             ("benchmark", "latency", "timestamp")),))
        monkeypatch.setattr(lc, "REPO", str(tmp_path))
        return d

    def test_it_writes_a_record(self, corpus, tmp_path, capsys):
        out = "out.csv"
        assert lc.main(["--corpus", str(corpus), "--out", out]) == 0
        rows = list(csv.DictReader(open(tmp_path / out, encoding="utf-8", newline="")))
        assert {r["term"] for r in rows} == {"benchmark", "latency", "timestamp"}
        assert all(r["key"] == "onekey" for r in rows)
        assert "wrote" in capsys.readouterr().out

    def test_check_passes_on_an_agreeing_record(self, corpus, tmp_path, capsys):
        lc.main(["--corpus", str(corpus), "--out", "out.csv"])
        capsys.readouterr()
        assert lc.main(["--corpus", str(corpus), "--out", "out.csv", "--check"]) == 0
        assert "agrees with the corpus" in capsys.readouterr().out

    def test_check_fails_when_the_record_has_drifted(self, corpus, tmp_path, capsys):
        lc.main(["--corpus", str(corpus), "--out", "out.csv"])
        path = tmp_path / "out.csv"
        body = path.read_text(encoding="utf-8").replace(",latency,9,", ",latency,99,")
        path.write_text(body, encoding="utf-8")
        capsys.readouterr()
        assert lc.main(["--corpus", str(corpus), "--out", "out.csv", "--check"]) == 1
        assert "DRIFT" in capsys.readouterr().out

    def test_an_absent_corpus_is_expected_and_not_a_failure(self, tmp_path, monkeypatch,
                                                            capsys):
        """The corpus is gitignored: off the author's machine there is nothing to count."""
        monkeypatch.setattr(lc, "SOURCES", (("gone.pdf", "k", ("latency",)),))
        assert lc.main(["--corpus", str(tmp_path / "nothing"), "--out", "o.csv"]) == 0
        assert "cannot read" in capsys.readouterr().out

    def test_an_absent_corpus_also_passes_check(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(lc, "SOURCES", (("gone.pdf", "k", ("latency",)),))
        assert lc.main(["--corpus", str(tmp_path / "nothing"), "--out", "o.csv",
                        "--check"]) == 0
        assert "cannot read" in capsys.readouterr().out


def test_the_committed_record_still_agrees_with_the_corpus():
    """Bites on the author's machine, skips everywhere else -- like the corpus check."""
    if not Path(lc.CORPUS).is_dir():
        pytest.skip("no local reference corpus")
    if not (Path(lc.CORPUS) / lc.SOURCES[0][0]).exists():
        pytest.skip("the censused papers are not held locally")
    assert lc.main(["--check"]) == 0
