"""scripts/apply_vocabulary.py: the mechanical stamp -> timestamp pass, prose only.

What the pass must not touch is the point of the test: comment lines, maths, \\texttt and
\\brk arguments (they quote identifiers) and command names. What it must report rather than
change -- flight, the instrument, guard, arm, quantum, Mode A/B -- is the REVIEW list.
"""
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
        assert new == TEXT and changes == [] and len(review) == 6


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

    def test_check_leaves_the_file_as_it_was(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(av, "ROOT", tmp_path)
        (tmp_path / "a.tex").write_text(TEXT, encoding="utf-8")
        assert av.main(["--check", "a.tex"]) == 0
        assert (tmp_path / "a.tex").read_text(encoding="utf-8") == TEXT
        assert "== a.tex: 0 mechanical change(s), 6 sentence(s) for review" in capsys.readouterr().out
