"""Tests for scripts/normalize_access_dates.py - target 100% branch coverage.

The script exists because round 79's referee found the bibliography dating its sources four
ways. Its contract is narrow: rewrite a date phrase into IEEE's form, never invent a date, and
report any retired form it is asked to check.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import normalize_access_dates as nad  # noqa: E402


class TestIeee:
    def test_every_month_uses_its_ieee_abbreviation(self):
        got = [nad.ieee("2026", m, "1") for m in range(1, 13)]
        assert got[0] == "Accessed: Jan. 1, 2026"
        assert got[4] == "Accessed: May 1, 2026", "May is not abbreviated"
        assert got[8] == "Accessed: Sep. 1, 2026", "the form IEEEtran renders here"

    def test_a_leading_zero_day_is_dropped(self):
        assert nad.ieee("2026", "08", "03") == "Accessed: Aug. 3, 2026"


class TestNormalize:
    def test_the_iso_read_form(self):
        assert nad.normalize("Read 2026-08-21}") == ("Accessed: Aug. 21, 2026}", 1)

    def test_a_clause_after_a_semicolon_becomes_its_own_sentence(self):
        assert nad.normalize("x; accessed 19 August 2026}") == ("x. Accessed: Aug. 19, 2026}", 1)

    def test_the_form_after_a_full_stop_keeps_its_stop(self):
        assert nad.normalize("x. accessed 2 March 2026}") == ("x. Accessed: Mar. 2, 2026}", 1)

    def test_the_form_at_the_start_of_a_line(self):
        assert nad.normalize("Accessed 5 May 2026}") == ("Accessed: May 5, 2026}", 1)

    def test_a_full_month_name_is_abbreviated(self):
        assert nad.normalize("Accessed: June 15, 2026}") == ("Accessed: Jun. 15, 2026}", 1)

    def test_text_without_a_date_is_untouched(self):
        assert nad.normalize("a note, 21 July 2026, no access date") == \
            ("a note, 21 July 2026, no access date", 0)

    def test_normalizing_twice_changes_nothing(self):
        once, _ = nad.normalize("Read 2026-09-13} y; accessed 1 January 2026}")
        assert nad.normalize(once) == (once, 0)


class TestOldForms:
    def test_each_retired_form_is_reported_with_its_line(self):
        text = "ok\nRead 2026-08-21\nx accessed 19 August 2026\nAccessed: June 15, 2026"
        hits = nad.old_forms(text)
        assert [line for line, _ in hits] == [2, 3, 4]

    def test_a_form_broken_across_a_line_is_found_and_rewritten(self):
        """The first run missed three entries whose note wrapped between "Read" and the date,
        and so did the check: both read the text one line at a time."""
        text = "x. Read\n                  2026-09-10}"
        assert [line for line, _ in nad.old_forms(text)] == [1]
        assert nad.normalize(text) == ("x. Accessed: Sep. 10, 2026}", 1)

    def test_the_ieee_form_is_not_a_retired_form(self):
        assert nad.old_forms("Accessed: Aug. 21, 2026") == []

    def test_may_is_its_own_abbreviation_and_is_not_retired(self):
        """May is spelled the same in full and abbreviated. Before this test the retired
        month-day-year pattern matched the correct IEEE form and failed the check on it."""
        assert nad.old_forms("Accessed: May 5, 2026") == []
        assert nad.normalize("Accessed: May 5, 2026") == ("Accessed: May 5, 2026", 0)


class TestMain:
    def _bib(self, tmp_path, text):
        p = tmp_path / "refs.bib"
        p.write_text(text, encoding="utf-8")
        return p

    def test_check_fails_on_a_retired_form_and_writes_nothing(self, tmp_path, capsys):
        p = self._bib(tmp_path, "@misc{a, note={Read 2026-09-01}}\n")
        assert nad.main([str(p), "--check"]) == 1
        assert "Read 2026-09-01" in p.read_text(encoding="utf-8")
        assert "refs.bib:1: Read 2026-09-01" in capsys.readouterr().out

    def test_check_passes_on_a_clean_file(self, tmp_path):
        p = self._bib(tmp_path, "@misc{a, note={Accessed: Sep. 1, 2026}}\n")
        assert nad.main([str(p), "--check"]) == 0

    def test_rewrite_changes_the_file(self, tmp_path, capsys):
        p = self._bib(tmp_path, "@misc{a, note={Read 2026-09-01}}\n")
        assert nad.main([str(p)]) == 0
        assert p.read_text(encoding="utf-8") == "@misc{a, note={Accessed: Sep. 1, 2026}}\n"
        assert "rewrote 1 date(s)" in capsys.readouterr().out

    def test_rewrite_leaves_a_clean_file_byte_for_byte(self, tmp_path, capsys):
        p = self._bib(tmp_path, "@misc{a, note={Accessed: Sep. 1, 2026}}\r\n")
        before = p.read_bytes()
        assert nad.main([str(p)]) == 0
        assert p.read_bytes() == before, "nothing to rewrite, so nothing written"
        assert "rewrote 0 date(s)" in capsys.readouterr().out
