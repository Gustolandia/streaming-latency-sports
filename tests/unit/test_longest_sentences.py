"""scripts/longest_sentences.py: the lister the sentence-length gate is tuned with.

The gate in test_sentence_length.py reports a median and a maximum and nothing else, which
is the right shape for a gate and the wrong shape for a repair: bringing an 81-word sentence
under the cap means finding it. This script lists the longest sentences with the line each
starts on, measured the way the gate measures them, so the splits are chosen rather than
discovered one failure at a time.
"""
import longest_sentences as ls


class TestProse:

    def test_markup_floats_maths_and_bios_are_removed(self):
        tex = "\n".join([
            r"\documentclass{IEEEtran}",
            r"\begin{document}",
            r"Hello \emph{world}~\cite{a}. Then $x = 1$ done.",
            r"\begin{figure}ignored caption\end{figure}",
            r"% a comment line",
            r"End.",
            r"\begin{IEEEbiographynophoto}{A} bio text \end{IEEEbiographynophoto}",
        ])
        body = ls.prose(tex)
        for kept in ("Hello", "done", "End", " X "):
            assert kept in body
        # A command's argument goes with the command: the gate the script mirrors strips
        # \emph{world} to a placeholder rather than counting "world" as prose.
        for gone in ("world", "ignored", "comment", "bio text", "documentclass", "{", "}", "~"):
            assert gone not in body


class TestSentences:

    def test_abbreviations_do_not_end_a_sentence(self):
        out = ls.sentences("See Fig. 3 and et al. wrote it. Next one.")
        assert [s.strip() for _, s in out] == ["See Fig. 3 and et al. wrote it.", "Next one."]

    def test_offsets_are_where_each_sentence_starts(self):
        text = "One two. Three four."
        assert [pos for pos, _ in ls.sentences(text)] == [0, 8]


class TestMain:

    def _write(self, tmp_path):
        path = tmp_path / "t.tex"
        path.write_text("\n".join([
            r"\begin{document}",
            "This long sentence has exactly twelve plain words in it to count.",
            "42.",
            r"The \foo{bar} macro sentence has several words here.",
            "Short one here.",
        ]), encoding="utf-8")
        return path

    def test_longest_first_with_its_line_and_stops_below_over(self, tmp_path, capsys):
        path = self._write(tmp_path)
        assert ls.main([str(path), "--top", "5", "--over", "5"]) == 0
        out = capsys.readouterr().out
        assert out.startswith("sentences: 3 ")          # the letterless "42." is not a sentence
        rows = [l for l in out.splitlines() if "words" in l and "line" in l]
        assert rows[0].startswith(" 12 words  line ~2 ")
        assert "line ~-1" in rows[1], "a sentence rewritten by macro stripping has no exact line"
        assert "Short one here" not in out, "rows under --over are not listed"

    def test_every_row_is_listed_when_none_is_under_over(self, tmp_path, capsys):
        path = self._write(tmp_path)
        assert ls.main([str(path), "--over", "1"]) == 0
        out = capsys.readouterr().out
        assert "Short one here" in out
