"""Tests for scripts/check_fork_exposure.py - target >=95% branch coverage.

The manuscript claimed the guard "appears unchanged in more than a dozen public forks". A
referee tried to verify it and could not, and said so rather than let silence imply
endorsement. The claim was not wrong -- it was unfalsifiable, which in a paper about
publishing the record behind a number is the worse failing.

This script makes it falsifiable: it walks the fork list, reads the file from each, and writes
what it found. The tests do not touch the network. What they pin is the classification -- the
three verdicts and the distinction that matters, which is that a fork whose file cannot be
read supports nothing either way and must not be counted as agreement.
"""
import csv
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_fork_exposure as cfe  # noqa: E402


class TestClassify:

    def test_a_file_carrying_the_guard_is_unchanged(self, monkeypatch):
        monkeypatch.setattr(cfe, "_fetch",
                            lambda url, raw=False, **kw: "if (endToEndLatencyMicros > 0) {")
        assert cfe.classify("someone/benchmark", "master") == "unchanged"

    def test_a_file_without_it_is_absent(self, monkeypatch):
        monkeypatch.setattr(cfe, "_fetch",
                            lambda url, raw=False, **kw: "recordValue(latency);")
        assert cfe.classify("someone/benchmark", "master") == "absent"

    def test_a_fetch_failure_is_unreadable_not_agreement(self, monkeypatch):
        """A fork that deleted the file, renamed it or went private supports nothing."""
        monkeypatch.setattr(cfe, "_fetch", lambda url, raw=False, **kw: "ERROR 404")
        assert cfe.classify("someone/benchmark", "master") == "unreadable"

    def test_an_html_error_page_is_unreadable(self, monkeypatch):
        """raw.githubusercontent answers a missing path with a page, not an exception."""
        monkeypatch.setattr(cfe, "_fetch",
                            lambda url, raw=False, **kw: "<!DOCTYPE HTML><html>404</html>")
        assert cfe.classify("someone/benchmark", "master") == "unreadable"

    def test_a_fragment_of_the_guard_does_not_count(self, monkeypatch):
        """'> 0' alone appears in unrelated code, which is why the whole condition is matched."""
        monkeypatch.setattr(cfe, "_fetch",
                            lambda url, raw=False, **kw: "if (payloadLength > 0) { }")
        assert cfe.classify("someone/benchmark", "master") == "absent"


class TestTotals:

    def test_unreadable_forks_are_in_neither_column(self):
        rows = [{"guard": "unchanged"}, {"guard": "unchanged"},
                {"guard": "absent"}, {"guard": "unreadable"}]
        t = cfe.totals(rows)
        assert t == {"checked": 3, "unchanged": 2, "absent": 1, "unreadable": 1}

    def test_an_empty_survey_totals_to_zero(self):
        assert cfe.totals([]) == {"checked": 0, "unchanged": 0, "absent": 0, "unreadable": 0}


class TestSurvey:

    def test_it_stops_once_the_limit_of_readable_forks_is_reached(self, monkeypatch):
        monkeypatch.setattr(cfe, "fork_names",
                            lambda upstream=cfe.UPSTREAM: [("f%d" % i, "master")
                                                           for i in range(20)])
        monkeypatch.setattr(cfe, "classify", lambda fork, branch: "unchanged")
        assert len(cfe.survey(limit=5)) == 5

    def test_unreadable_forks_do_not_count_towards_the_limit(self, monkeypatch):
        """Otherwise a run of dead forks ends the survey having read nothing."""
        seen = {"n": 0}

        def classify(fork, branch):
            seen["n"] += 1
            return "unreadable" if seen["n"] <= 4 else "unchanged"

        monkeypatch.setattr(cfe, "fork_names",
                            lambda upstream=cfe.UPSTREAM: [("f%d" % i, "master")
                                                           for i in range(20)])
        monkeypatch.setattr(cfe, "classify", classify)
        rows = cfe.survey(limit=3)
        assert cfe.totals(rows)["checked"] == 3
        assert cfe.totals(rows)["unreadable"] == 4

    def test_every_row_carries_the_date_it_was_checked(self, monkeypatch):
        monkeypatch.setattr(cfe, "fork_names",
                            lambda upstream=cfe.UPSTREAM: [("a/b", "main")])
        monkeypatch.setattr(cfe, "classify", lambda fork, branch: "unchanged")
        rows = cfe.survey(limit=1)
        assert rows[0]["checked_utc"] and rows[0]["default_branch"] == "main"


class TestForkNames:

    def test_an_api_failure_yields_no_names_rather_than_raising(self, monkeypatch):
        monkeypatch.setattr(cfe, "_fetch", lambda url, raw=False, **kw: {"error": "504"})
        assert cfe.fork_names() == []

    def test_a_short_page_ends_the_walk(self, monkeypatch):
        calls = {"n": 0}

        def fetch(url, raw=False, **kw):
            calls["n"] += 1
            return [{"full_name": "a/b", "default_branch": "master"}]

        monkeypatch.setattr(cfe, "_fetch", fetch)
        assert cfe.fork_names() == [("a/b", "master")]
        assert calls["n"] == 1, "a page shorter than the page size means there is no next page"

    def test_a_missing_default_branch_falls_back(self, monkeypatch):
        monkeypatch.setattr(cfe, "_fetch",
                            lambda url, raw=False, **kw: [{"full_name": "a/b"}])
        assert cfe.fork_names() == [("a/b", "master")]


class TestReadRecord:

    def test_a_missing_record_reads_as_empty(self, tmp_path):
        assert cfe.read_record(str(tmp_path / "absent.csv")) == []

    def test_the_committed_record_is_readable_and_consistent(self):
        """The number the manuscript prints comes from this file, so it must parse."""
        rows = cfe.read_record()
        if not rows:
            pytest.skip("no fork survey committed")
        t = cfe.totals(rows)
        assert t["checked"] == t["unchanged"] + t["absent"]
        assert t["unchanged"] > 12, "the manuscript's claim needs more than a dozen"
        assert all(r["checked_utc"] for r in rows)


class TestMain:

    def test_it_writes_the_record_and_reports(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(cfe, "survey",
                            lambda limit: [{"fork": "a/b", "default_branch": "master",
                                            "guard": "unchanged", "checked_utc": "2026-01-01"}])
        out = tmp_path / "rec.csv"
        assert cfe.main(["--out", str(out), "--limit", "1"]) == 0
        rows = list(csv.DictReader(open(out, encoding="utf-8")))
        assert rows[0]["fork"] == "a/b"
        assert "1 carry the guard unchanged" in capsys.readouterr().out

    def test_reaching_no_forks_leaves_the_record_alone(self, tmp_path, monkeypatch, capsys):
        """A network outage must not overwrite a good record with an empty one."""
        monkeypatch.setattr(cfe, "survey", lambda limit: [])
        out = tmp_path / "rec.csv"
        assert cfe.main(["--out", str(out), "--limit", "1"]) == 1
        assert not out.exists()
        assert "left alone" in capsys.readouterr().out


class TestFetch:
    """The retry path, which is most of what this script is and none of what it claims.

    A transient failure that returns "ERROR" is indistinguishable, downstream, from a fork
    that deleted the file -- both read as unreadable. That is the safe direction, but only if
    a transient failure is actually retried first, so the retry is pinned.
    """

    def _urlopen(self, monkeypatch, sequence):
        """Replace urlopen with one that yields the given results in order."""
        import urllib.request
        calls = {"n": 0}

        class Response:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body.encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(request, timeout=None):
            item = sequence[min(calls["n"], len(sequence) - 1)]
            calls["n"] += 1
            if isinstance(item, Exception):
                raise item
            return Response(item)

        monkeypatch.setattr(urllib.request, "urlopen", fake)
        monkeypatch.setattr(cfe.time, "sleep", lambda s: None)
        return calls

    def test_a_raw_body_comes_back_as_text(self, monkeypatch):
        self._urlopen(monkeypatch, ["hello"])
        assert cfe._fetch("http://x", raw=True) == "hello"

    def test_json_is_parsed(self, monkeypatch):
        self._urlopen(monkeypatch, ['{"a": 1}'])
        assert cfe._fetch("http://x") == {"a": 1}

    def test_a_transient_failure_is_retried(self, monkeypatch):
        calls = self._urlopen(monkeypatch, [OSError("boom"), '{"a": 2}'])
        assert cfe._fetch("http://x") == {"a": 2}
        assert calls["n"] == 2, "the first failure should have been retried"

    def test_persistent_failure_reports_rather_than_raises(self, monkeypatch):
        self._urlopen(monkeypatch, [OSError("down")])
        assert "error" in cfe._fetch("http://x")
        assert cfe._fetch("http://x", raw=True).startswith("ERROR")


class TestForkNamesPaging:

    def test_a_full_page_leads_to_the_next(self, monkeypatch):
        pages = {"n": 0}

        def fetch(url, raw=False, **kw):
            pages["n"] += 1
            if pages["n"] == 1:
                return [{"full_name": "a/%d" % i, "default_branch": "master"}
                        for i in range(100)]
            return [{"full_name": "b/1", "default_branch": "master"}]

        monkeypatch.setattr(cfe, "_fetch", fetch)
        names = cfe.fork_names()
        assert len(names) == 101
        assert pages["n"] == 2, "a full page should be followed by another request"


class TestTheEmittedMacrosMatchTheRecord:
    """The paper prints the survey's numbers, so the two must not drift apart.

    Round 16's lesson, applied here before it costs anything: a number is only as checkable as
    the path from the claim to the artifact. The macro is that path, and a macro that has
    stopped agreeing with its file is worse than a typed number, because it looks derived.
    """

    def test_the_counts_in_the_generated_file_are_the_counts_in_the_record(self):
        rows = cfe.read_record()
        if not rows:
            pytest.skip("no fork survey committed")
        generated = (ROOT / "docs" / "generated" / "paper_numbers.tex").read_text(
            encoding="utf-8")
        t = cfe.totals(rows)
        for macro, want in (("forkChecked", t["checked"]),
                            ("forkUnchanged", t["unchanged"]),
                            ("forkAbsent", t["absent"])):
            needle = "\\newcommand{\\%s}{%d}" % (macro, want)
            assert needle in generated, (
                "%s does not carry the survey's %d; re-run emit_paper_numbers.py"
                % (macro, want))

    def test_the_survey_date_is_carried_too(self):
        rows = cfe.read_record()
        if not rows:
            pytest.skip("no fork survey committed")
        generated = (ROOT / "docs" / "generated" / "paper_numbers.tex").read_text(
            encoding="utf-8")
        assert ("\\newcommand{\\forkCheckedOn}{%s}" % rows[0]["checked_utc"]) in generated


class TestTheWalkRunsOut:
    """Both loops end by exhausting what they were given, not only by finding enough.

    A survey that only ever stops early has never been asked what it does when the fork list
    or the page sequence runs out first, and both happen: the upstream repository has a finite
    number of forks, and it has fewer than three hundred.
    """

    def test_the_page_walk_stops_after_the_last_page_it_is_allowed(self, monkeypatch):
        """Three full pages and no fourth request: the cap is what ends it."""
        pages = {"n": 0}

        def fetch(url, raw=False, **kw):
            pages["n"] += 1
            return [{"full_name": "a/%d" % i, "default_branch": "master"}
                    for i in range(100)]

        monkeypatch.setattr(cfe, "_fetch", fetch)
        names = cfe.fork_names(pages=3)
        assert len(names) == 300
        assert pages["n"] == 3, "the page cap must end the walk, not a fourth request"

    def test_a_survey_shorter_than_its_limit_reads_every_fork(self, monkeypatch):
        """Asking for forty and finding three is three forks read, not an error."""
        monkeypatch.setattr(cfe, "fork_names",
                            lambda upstream=cfe.UPSTREAM: [("f%d" % i, "master")
                                                           for i in range(3)])
        monkeypatch.setattr(cfe, "classify", lambda fork, branch: "unchanged")
        rows = cfe.survey(limit=40)
        assert len(rows) == 3
        assert cfe.totals(rows)["checked"] == 3


class TestFetchAlwaysAnswers:
    """There is no path out of `_fetch` that returns nothing.

    `classify` calls `.startswith` on whatever comes back, so a `None` would surface as an
    AttributeError in the middle of a survey rather than as an unreadable fork.
    """

    def test_zero_attempts_still_answers(self):
        assert cfe._fetch("http://x", raw=True, tries=0).startswith("ERROR")
        assert "error" in cfe._fetch("http://x", tries=0)

    def test_a_fork_that_could_not_be_attempted_is_unreadable(self, monkeypatch):
        """The zero-attempt answer must classify, not crash: that is why it is a string."""
        real = cfe._fetch
        monkeypatch.setattr(cfe, "_fetch",
                            lambda url, raw=False, **kw: real(url, raw, tries=0))
        assert cfe.classify("a/b", "master") == "unreadable"

    def test_the_last_failure_is_the_one_reported(self, monkeypatch):
        """A run of different failures should end saying what stopped it last, not first."""
        import urllib.request
        errors = iter([OSError("first"), OSError("second"), OSError("third")])

        def fake(request, timeout=None):
            raise next(errors)

        monkeypatch.setattr(urllib.request, "urlopen", fake)
        monkeypatch.setattr(cfe.time, "sleep", lambda s: None)
        assert cfe._fetch("http://x", raw=True).endswith("third")

    def test_it_waits_between_attempts_but_not_after_the_last(self, monkeypatch):
        """A pause after the final failure is dead time on every unreadable fork, and there
        are forty of them."""
        import urllib.request
        pauses = []

        def fake(request, timeout=None):
            raise OSError("down")

        monkeypatch.setattr(urllib.request, "urlopen", fake)
        monkeypatch.setattr(cfe.time, "sleep", lambda s: pauses.append(s))
        cfe._fetch("http://x", tries=3, pause=0.5)
        assert pauses == [0.5, 0.5], "three attempts means two waits"
