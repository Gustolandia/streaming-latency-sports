"""scripts/apply_vocabulary.py: the mechanical stamp -> timestamp pass, prose only.

What the pass must not touch is the point of the test: comment lines, maths, \\texttt and
\\brk arguments (they quote identifiers) and command names. What it must report rather than
change -- flight, the instrument, guard, arm, quantum, Mode A/B -- is the REVIEW list.

Round 68 added the memory: the REVIEW list is adjudicated in
`docs/vocabulary_adjudications.json`, a clean run prints nothing, and a judgment that has
stopped matching fails as loudly as an unjudged word -- because an allowance for prose that
has since moved is a claim nobody checked.
"""
import json

import pytest

import apply_vocabulary as av

TEXT = ("The stamp is late; stamps are stamped while stamping, and a timestamp stays.\n"
        "% stamp in a comment line\n"
        "\\texttt{stamp_ns}, $stamp$, \\emph{stamp} keep. Stamps Stamp Stamping.\n"
        "In flight, the instrument, a guard, an arm, the quantum, Mode~A.\n")

EXPECTED = ("The timestamp is late; timestamps are timestamped while timestamping, and a "
            "timestamp stays.\n"
            "% stamp in a comment line\n"
            "\\texttt{stamp_ns}, $stamp$, \\emph{timestamp} keep. Timestamps Timestamp "
            "Timestamping.\n"
            "In flight, the instrument, a guard, an arm, the quantum, Mode~A.\n")


class TestRewrite:

    def test_prose_is_rewritten_and_islands_are_left_alone(self):
        new, changes, review = av.rewrite(TEXT, "t.tex", check=False)
        assert new == EXPECTED
        # The substitutions run pattern by pattern within each prose chunk, so the order is
        # not the order of the words in the text; the set is what the diff reader needs.
        assert sorted(changes) == sorted([
            "t.tex:1  stamping -> timestamping", "t.tex:1  stamped -> timestamped",
            "t.tex:1  stamps -> timestamps", "t.tex:1  stamp -> timestamp",
            "t.tex:3  stamp -> timestamp", "t.tex:3  Stamping -> Timestamping",
            "t.tex:3  Stamps -> Timestamps", "t.tex:3  Stamp -> Timestamp"])

    def test_review_words_are_reported_with_their_line_never_changed(self):
        _new, _changes, review = av.rewrite(TEXT, "t.tex", check=False)
        assert [r.split("  ")[1].strip() for r in review] == [
            "flight", "the instrument", "guard", "arm", "quantum", "Mode~A"]
        assert all(r.startswith("t.tex:4  ") for r in review)

    def test_check_mode_changes_nothing_and_still_reports(self):
        new, changes, review = av.rewrite(TEXT, "t.tex", check=True)
        assert new == TEXT and len(changes) == 8 and len(review) == 6


class TestMain:

    def test_files_with_changes_are_written_and_the_rest_left_alone(
            self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(av, "ROOT", tmp_path)
        (tmp_path / "a.tex").write_text(TEXT, encoding="utf-8")
        (tmp_path / "b.tex").write_text("clean text\n", encoding="utf-8")
        assert av.main(["a.tex", "b.tex"]) == 0
        assert (tmp_path / "a.tex").read_text(encoding="utf-8") == EXPECTED
        assert (tmp_path / "b.tex").read_text(encoding="utf-8") == "clean text\n"
        out = capsys.readouterr().out
        assert "== a.tex: 8 mechanical change(s), 6 sentence(s) for review" in out
        assert "== b.tex: 0 mechanical change(s), 0 sentence(s) for review" in out
        assert "   a.tex:1  stamp -> timestamp" in out
        assert "   REVIEW a.tex:4  flight" in out

    def test_check_leaves_the_file_as_it_was_and_fails_on_unjudged_words(
            self, tmp_path, monkeypatch, capsys):
        """Round 68: --check now has an exit status, so it can gate rather than inform.

        For several rounds it reported twenty-five review items every time, which meant the
        report was re-read from scratch every round and two genuine items sat inside
        twenty-three correct ones without being separated. A standing report of twenty-five
        is not a report.
        """
        monkeypatch.setattr(av, "ROOT", tmp_path)
        monkeypatch.setattr(av, "ADJUDICATIONS", tmp_path / "absent.json")
        (tmp_path / "a.tex").write_text(TEXT, encoding="utf-8")
        assert av.main(["--check", "a.tex"]) == 1
        assert (tmp_path / "a.tex").read_text(encoding="utf-8") == TEXT
        assert "== a.tex: 8 mechanical change(s), 6 sentence(s) for review" \
            in capsys.readouterr().out


class TestAdjudications:
    """The allow-list, its two scopes, and the two ways it is allowed to fail."""

    def test_a_missing_file_means_no_judgments_rather_than_an_error(self, tmp_path):
        assert av.load_adjudications(tmp_path / "nothing-here.json") == []

    def test_a_line_judgment_clears_one_occurrence_and_only_that_line(self):
        judged = [{"file": "t.tex", "key": "quantum", "scope": "line",
                   "anchor": "the quantum, defined right here", "reason": "the definition"}]
        text = ("the quantum, defined right here, is one millisecond.\n"
                "and later, an undefended quantum.\n")
        _new, _ch, review = av.rewrite(text, "t.tex", True, judged, set())
        assert len(review) == 1 and review[0].startswith("t.tex:2")

    def test_a_file_judgment_holds_only_while_what_it_requires_is_present(self):
        judged = [{"file": "t.tex", "key": "guard", "scope": "file",
                   "requires": "we define guard as follows", "reason": "defined in the doc"}]
        with_def = "we define guard as follows.\na guard here and a guard there.\n"
        _n, _c, review = av.rewrite(with_def, "t.tex", True, judged, set())
        assert review == []
        without = "a guard here and a guard there.\n"
        _n, _c, review = av.rewrite(without, "t.tex", True, judged, set())
        assert len(review) == 2, "losing the definition must bring every use back"

    def test_a_judgment_for_another_file_or_another_word_does_not_apply(self):
        judged = [{"file": "other.tex", "key": "guard", "scope": "file",
                   "requires": "x", "reason": "r"},
                  {"file": "t.tex", "key": "arm", "scope": "file",
                   "requires": "a guard here", "reason": "r"}]
        _n, _c, review = av.rewrite("a guard here.\n", "t.tex", True, judged, set())
        assert len(review) == 1

    def test_a_judgment_that_matches_nothing_is_reported_and_fails(
            self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(av, "ROOT", tmp_path)
        adj = tmp_path / "adj.json"
        adj.write_text(json.dumps({"judgments": [
            {"file": "a.tex", "key": "guard", "scope": "line",
             "anchor": "a sentence that is not there", "reason": "r"}]}), encoding="utf-8")
        monkeypatch.setattr(av, "ADJUDICATIONS", adj)
        (tmp_path / "a.tex").write_text("nothing to review here.\n", encoding="utf-8")
        assert av.main(["--check", "a.tex"]) == 1
        assert "STALE  a.tex  guard  matched nothing" in capsys.readouterr().out

    def test_a_stale_judgment_for_a_file_not_being_checked_is_not_reported(
            self, tmp_path, monkeypatch, capsys):
        """Checking one file must not condemn a judgment about the other."""
        monkeypatch.setattr(av, "ROOT", tmp_path)
        adj = tmp_path / "adj.json"
        adj.write_text(json.dumps({"judgments": [
            {"file": "b.tex", "key": "guard", "scope": "line",
             "anchor": "elsewhere", "reason": "r"}]}), encoding="utf-8")
        monkeypatch.setattr(av, "ADJUDICATIONS", adj)
        (tmp_path / "a.tex").write_text("nothing to review here.\n", encoding="utf-8")
        assert av.main(["--check", "a.tex"]) == 0
        assert "STALE" not in capsys.readouterr().out

    def test_writing_mode_never_fails_even_with_words_outstanding(
            self, tmp_path, monkeypatch):
        """--check gates; the rewriting pass reports and returns 0, as it always did."""
        monkeypatch.setattr(av, "ROOT", tmp_path)
        monkeypatch.setattr(av, "ADJUDICATIONS", tmp_path / "absent.json")
        (tmp_path / "a.tex").write_text(TEXT, encoding="utf-8")
        assert av.main(["a.tex"]) == 0


class TestFlightIsNotPreFlight:
    """Five of round 68's twenty-five standing items were this pattern, on the wrong side
    of a hyphen. The retired term is the bare noun; "pre-flight" and "in-flight" are
    ordinary technical English and needed a pattern fix, not an allowance."""

    @pytest.mark.parametrize("text", ["a pre-flight check", "one in-flight request"])
    def test_hyphenated_compounds_are_not_the_retired_noun(self, text):
        _n, _c, review = av.rewrite(text + "\n", "t.tex", True, [], set())
        assert review == []

    @pytest.mark.parametrize("text", ["a flight of messages", "two flights"])
    def test_the_bare_noun_still_reports(self, text):
        _n, _c, review = av.rewrite(text + "\n", "t.tex", True, [], set())
        assert len(review) == 1


class TestTheRepositorysOwnAdjudicationsAreExact:
    """The shipped list must clear the shipped documents with nothing left over."""

    def test_the_check_is_clean_on_both_documents(self, capsys):
        assert av.main(["--check", "paper.tex", "supplement.tex", "postmortem.tex"]) == 0
        out = capsys.readouterr().out
        assert "REVIEW" not in out and "STALE" not in out

    def test_every_judgment_carries_a_reason(self):
        for j in av.load_adjudications():
            assert j["reason"].strip(), j
            assert j["scope"] in ("file", "line"), j
            assert ("requires" in j) == (j["scope"] == "file"), j
            assert ("anchor" in j) == (j["scope"] == "line"), j


class TestCheckFailsOnAMechanicalChange:
    """3 Oct 2026: --check used to return before the substitutions, so a bare "stamp" passed
    every check. Four of them reached Supplement S3.10 that way, and four more had sat in the
    supplement and the postmortem since they were written."""

    def test_a_file_with_only_a_bare_stamp_fails_the_check(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(av, "ROOT", tmp_path)
        monkeypatch.setattr(av, "ADJUDICATIONS", tmp_path / "absent.json")
        (tmp_path / "a.tex").write_text("before each stamp\n", encoding="utf-8")
        assert av.main(["--check", "a.tex"]) == 1
        assert (tmp_path / "a.tex").read_text(encoding="utf-8") == "before each stamp\n"
        assert "a.tex:1  stamp -> timestamp" in capsys.readouterr().out


class TestTheIndustrysNames:
    """A10 (3 Oct 2026): the OpenMessaging Benchmark's names for the three quantities, the
    producer's act called publish, Karimov et al.'s processing-time latency, and Linux's
    scheduling policies."""

    def test_the_compounds_are_renamed_with_their_articles(self):
        text = ("A send lag, an acknowledgment lag and a delivery time; the send call, the send\n"
                "rate and two delivery times; Acknowledgment\nlag, a handling span and the\n"
                "send-referenced span.\n")
        new, changes, review = av.rewrite(text, "t.tex", check=False)
        assert new == ("A publish delay, a publish latency and an end-to-end latency; the publish "
                       "call, the publish rate and two end-to-end latencies; Publish latency, a "
                       "processing-time latency and the\npublish-timed span.\n")
        assert review == []

    def test_stolen_time_takes_linuxs_name(self):
        """4 Oct 2026: /proc/stat's steal, top's st, mpstat's %steal, KVM's steal time."""
        text = "stolen processor time, stolen virtual-CPU time, stolen vCPU time, stolen time\n"
        new, changes, review = av.rewrite(text, "t.tex", check=False)
        assert new == "steal time, steal time, steal time, steal time\n"

    def test_the_words_that_need_a_reading_are_reported(self):
        text = ("The producer sends; the go-first consumer at ordinary priority; the brake;\n"
                "the emission loop; ordinary least squares stays.\n")
        _new, _changes, review = av.rewrite(text, "t.tex", check=True)
        assert [r.split("  ")[1].strip() for r in review] == [
            "sends", "go-first", "ordinary", "brake", "emission"]

    def test_a_quotation_keeps_its_source_s_words(self):
        """A vendor's "send timestamp" is the vendor's: renaming it falsifies the quotation."""
        text = "``a 64-bit send timestamp in UNIX nanoseconds.'' Our send lag.\n"
        new, changes, review = av.rewrite(text, "t.tex", check=False)
        assert new == "``a 64-bit send timestamp in UNIX nanoseconds.'' Our publish delay.\n"
        assert changes == ["t.tex:1  send lag -> publish delay"] and review == []

    def test_a_quote_environment_is_layout_and_is_read(self):
        """The documents indent their own tables and code with it; treated as a quotation, it
        hid a table header, "send blocked", from the renaming (3 Oct 2026)."""
        text = "\\begin{quote}event & send blocked (ms)\\end{quote}\n"
        _new, _changes, review = av.rewrite(text, "t.tex", check=True)
        assert [r.split("  ")[1].strip() for r in review] == ["send"]

    def test_the_hyphenated_compounds_are_caught(self):
        """per-send and send-to-acknowledgment stepped over the bare-word pattern once."""
        text = "a per-send jitter; its send-to-acknowledgment difference; a send-side cost.\n"
        new, changes, review = av.rewrite(text, "t.tex", check=False)
        assert new == ("a per-publish jitter; its publish-to-acknowledgment difference; a "
                       "send-side cost.\n")
        assert [r.split("  ")[1].strip() for r in review] == ["send-side"]
