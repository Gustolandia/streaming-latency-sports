"""scripts/fetch_vocabulary_corpus.py: the corpus fetcher, with every network call faked.

The script exists so that "how does the field write?" is answered by a query rather than a
guess. Nothing here touches the network: the arXiv Atom feed, the OpenAlex JSON and the PDF
bytes are all handed in, and the two failure branches -- a query that errors and a download
that errors -- are driven by fakes that raise, so they are tested rather than excluded.
"""
import csv
import json

import pytest

import fetch_vocabulary_corpus as fvc

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>A   title
      wrapped</title>
    <arxiv:journal_ref>IEEE Transactions on Computers, 2024</arxiv:journal_ref>
    <category term="cs.PF"/><category term="cs.DC"/>
    <published>2024-01-02T00:00:00Z</published>
    <link title="doi" href="https://doi.org/x"/>
    <link title="pdf" href="http://arxiv.org/pdf/2401.00001v1"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00002v1</id>
    <title>Second</title>
    <published>2023-05-05T00:00:00Z</published>
  </entry>
</feed>
"""

OPENALEX = {"results": [
    {"id": "https://openalex.org/W1", "title": " Kept   paper ", "publication_year": 2025,
     "primary_location": {"source": {"display_name": "IEEE Transactions on Computers"}},
     "open_access": {"oa_url": "https://x/1.pdf"}},
    {"id": "https://openalex.org/W2", "title": "Wrong venue", "publication_year": 2025,
     "primary_location": {"source": {"display_name": "IEEE Transactions on Cloud Computing"}},
     "open_access": {"oa_url": "https://x/2.pdf"}},
    {"id": "https://openalex.org/W3", "title": "No pdf", "publication_year": 2024,
     "primary_location": {"source": {"display_name": "IEEE Transactions on Computers"}},
     "open_access": {"oa_url": None}},
    {"id": "https://openalex.org/W4", "title": None, "publication_year": None,
     "primary_location": None, "open_access": None},
]}


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _urlopen(payload, seen):
    def fake(url, timeout=None):
        seen.append(url)
        return _Response(payload)
    return fake


def _boom(*a, **k):
    raise AssertionError("the network was touched")


class TestQuery:

    def test_parses_the_atom_feed(self, monkeypatch):
        seen = []
        monkeypatch.setattr(fvc.urllib.request, "urlopen", _urlopen(ATOM, seen))
        out = fvc.query('jr:"Transactions on Computers"', 7)
        assert "max_results=7" in seen[0] and "search_query=" in seen[0]
        assert out[0] == {"arxiv_id": "2401.00001v1", "title": "A title wrapped",
                          "journal_ref": "IEEE Transactions on Computers, 2024",
                          "categories": "cs.PF,cs.DC", "year": "2024",
                          "pdf": "http://arxiv.org/pdf/2401.00001v1"}
        assert out[1]["pdf"] == "" and out[1]["journal_ref"] == ""
        assert out[1]["categories"] == "" and out[1]["year"] == "2023"


class TestOpenAlex:

    def test_keeps_only_the_venue_asked_for_and_only_with_a_pdf(self, monkeypatch):
        seen = []
        monkeypatch.setattr(fvc.urllib.request, "urlopen",
                            _urlopen(json.dumps(OPENALEX).encode(), seen))
        out = fvc.openalex("IEEE Transactions on Computers", 50)
        assert "mailto=" in seen[0] and "per-page=50" in seen[0]
        assert out == [{"arxiv_id": "W1", "title": "Kept paper",
                        "journal_ref": "IEEE Transactions on Computers",
                        "categories": "openalex", "year": "2025", "pdf": "https://x/1.pdf"}]


class TestFetchPdf:

    def test_a_real_file_already_present_is_not_fetched_again(self, tmp_path, monkeypatch):
        dest = tmp_path / "a.pdf"
        dest.write_bytes(b"%PDF" + b"x" * 20000)
        monkeypatch.setattr(fvc.urllib.request, "urlopen", _boom)
        assert fvc.fetch_pdf("http://x/a.pdf", dest) == "cached"

    def test_a_landing_page_is_not_kept(self, tmp_path, monkeypatch):
        seen = []
        monkeypatch.setattr(fvc.urllib.request, "urlopen", _urlopen(b"<html>not a paper", seen))
        dest = tmp_path / "b.pdf"
        assert fvc.fetch_pdf("http://x/b", dest) == "not-a-pdf"
        assert not dest.exists()
        assert seen[0].get_header("User-agent") == "vocabulary-corpus/1.0"

    def test_a_pdf_is_written(self, tmp_path, monkeypatch):
        payload = b"%PDF-1.4 " + b"y" * 100
        monkeypatch.setattr(fvc.urllib.request, "urlopen", _urlopen(payload, []))
        dest = tmp_path / "c.pdf"
        assert fvc.fetch_pdf("http://x/c.pdf", dest) == "fetched"
        assert dest.read_bytes() == payload


class TestMain:

    def _fakes(self, monkeypatch):
        A = {"arxiv_id": "2401.00001v1", "title": "A", "journal_ref": "TC",
             "categories": "cs.PF", "year": "2024", "pdf": "http://x/a.pdf"}
        B = {"arxiv_id": "2401.00002v1", "title": "B", "journal_ref": "",
             "categories": "", "year": "2023", "pdf": ""}
        C = {"arxiv_id": "W1", "title": "C", "journal_ref": "IEEE Transactions on Computers",
             "categories": "openalex", "year": "2025", "pdf": "https://x/c.pdf"}
        calls, fetched = [], []

        def query(q, n):
            if q == fvc.JOURNAL_QUERIES["tc"]:
                return [dict(A), dict(B)]
            if q == fvc.COMMENT_QUERIES["co_tc"]:
                return [dict(A)]                      # a duplicate of A, by another route
            if q == fvc.TOPIC_QUERIES["timestamp"]:
                raise RuntimeError("HTTP 503")
            return []

        def openalex(venue, n):
            calls.append(n)
            return [dict(C)] if venue == "IEEE Transactions on Computers" else []

        def fetch_pdf(url, dest):
            fetched.append((url, dest.name))
            if url.endswith("c.pdf"):
                raise OSError("timed out")
            return "fetched"

        monkeypatch.setattr(fvc, "query", query)
        monkeypatch.setattr(fvc, "openalex", openalex)
        monkeypatch.setattr(fvc, "fetch_pdf", fetch_pdf)
        monkeypatch.setattr(fvc.time, "sleep", lambda s: None)
        return calls, fetched

    def test_the_manifest_dedupes_and_the_download_loop_reports_each_file(
            self, tmp_path, monkeypatch, capsys):
        calls, fetched = self._fakes(monkeypatch)
        out = tmp_path / "corpus"
        assert fvc.main(["--out", str(out), "--per-query", "10"]) == 0
        text = capsys.readouterr().out
        assert "query timestamp failed: HTTP 503" in text
        with open(out / "manifest.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert [r["arxiv_id"] for r in rows] == ["2401.00001v1", "2401.00002v1", "W1"]
        assert rows[0]["matched"] == "tc|co_tc" and rows[0]["group"] == "journal"
        assert rows[2]["group"] == "openalex"
        assert calls == [40] * len(fvc.OPENALEX_VENUES), "four times per-query, capped at 200"
        assert fetched == [("http://x/a.pdf", "2401.00001v1.pdf"), ("https://x/c.pdf", "W1.pdf")]
        assert "FAILED timed out" in text and "pdfs present: 1" in text

    def test_no_download_stops_at_the_manifest(self, tmp_path, monkeypatch):
        calls, fetched = self._fakes(monkeypatch)
        out = tmp_path / "corpus"
        assert fvc.main(["--out", str(out), "--no-download"]) == 0
        assert fetched == [] and (out / "manifest.csv").exists()
