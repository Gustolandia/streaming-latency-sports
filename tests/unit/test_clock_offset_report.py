"""Tests for clock_offset_report.

The claim this script guards is a negative one: "the distributed run showed no causality
violations". That claim is only meaningful alongside the clock bound and the timestamp
resolution, because two well-synchronised hosts subtracting millisecond-grained timestamps
*cannot* produce one. The MASKED verdict is the one that keeps a null result honest, so it is
what most of these tests are about.
"""
import csv
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from clock_offset_report import (  # noqa: E402
    main, max_error_ms, pair_bound_ms, parse_tracking, report, verdict,
)

TRACKING = """Reference ID    : 53D9A62D (83.217.166.45)
Stratum         : 2
Ref time (UTC)  : Sun Jul 26 15:41:43 2026
System time     : 0.000001604 seconds fast of NTP time
Last offset     : +0.000073387 seconds
RMS offset      : 0.000141769 seconds
Frequency       : 10.938 ppm slow
Root delay      : 0.002500000 seconds
Root dispersion : 0.000900000 seconds
"""


def tracking_with(**over):
    t = parse_tracking(TRACKING)
    t.update(over)
    return t


class TestParse:
    def test_the_offsets_are_read(self):
        t = parse_tracking(TRACKING)
        assert t["last_offset_s"] == pytest.approx(7.3387e-05)
        assert t["rms_offset_s"] == pytest.approx(0.000141769)
        assert t["stratum"] == 2

    def test_the_root_bound_fields_are_read(self):
        t = parse_tracking(TRACKING)
        assert t["root_delay_s"] == pytest.approx(0.0025)
        assert t["root_dispersion_s"] == pytest.approx(0.0009)

    def test_a_negative_last_offset_parses(self):
        t = parse_tracking(TRACKING.replace("+0.000073387", "-0.000073387"))
        assert t["last_offset_s"] == pytest.approx(-7.3387e-05)

    def test_empty_input_yields_all_none(self):
        assert parse_tracking("") == {"last_offset_s": None, "rms_offset_s": None,
                                      "stratum": None, "root_dispersion_s": None,
                                      "root_delay_s": None}

    def test_none_input_does_not_raise(self):
        assert parse_tracking(None)["stratum"] is None


class TestBound:
    def test_the_bound_is_dispersion_plus_half_the_delay(self):
        """The conventional bound, not the most flattering number on the page."""
        assert max_error_ms(parse_tracking(TRACKING)) == pytest.approx(
            (0.0009 + 0.0025 / 2) * 1000)

    def test_a_host_with_no_root_fields_has_no_bound(self):
        assert max_error_ms({"root_dispersion_s": None, "root_delay_s": None}) is None

    def test_one_present_field_is_enough(self):
        assert max_error_ms({"root_dispersion_s": 0.001, "root_delay_s": None}) == \
            pytest.approx(1.0)

    def test_the_pair_bound_is_the_sum(self):
        t = parse_tracking(TRACKING)
        assert pair_bound_ms(t, t) == pytest.approx(2 * max_error_ms(t))

    def test_a_pair_with_an_unbounded_host_has_no_bound(self):
        assert pair_bound_ms(parse_tracking(TRACKING), parse_tracking("")) is None


class TestVerdict:
    def test_a_tight_pair_at_millisecond_resolution_is_masked(self):
        v, why = verdict(0.5, 1.0)
        assert v == "MASKED"
        assert "not evidence that cross-host subtraction is safe" in why

    def test_a_loose_pair_is_visible(self):
        v, why = verdict(4.0, 1.0)
        assert v == "VISIBLE"
        assert "negative sample is possible from clock offset alone" in why

    def test_a_bound_exactly_at_the_resolution_counts_as_visible(self):
        assert verdict(1.0, 1.0)[0] == "VISIBLE"

    def test_no_bound_is_unknown_rather_than_safe(self):
        assert verdict(None, 1.0)[0] == "unknown"

    def test_no_resolution_is_unknown(self):
        assert verdict(0.5, 0)[0] == "unknown"

    def test_a_finer_resolution_can_flip_masked_to_visible(self):
        """Nanosecond stamping exposes the same clocks the millisecond stamp hides."""
        assert verdict(0.5, 1.0)[0] == "MASKED"
        assert verdict(0.5, 0.001)[0] == "VISIBLE"


class TestReport:
    def test_every_pair_is_reported(self, capsys):
        hosts = {"drv": parse_tracking(TRACKING), "b1": parse_tracking(TRACKING),
                 "b2": parse_tracking(TRACKING)}
        rows = report(hosts, 1.0)
        assert len(rows) == 3
        assert {(r["host_a"], r["host_b"]) for r in rows} == {("b1", "b2"), ("b1", "drv"),
                                                              ("b2", "drv")}
        assert "host" in capsys.readouterr().out

    def test_the_worst_pair_drives_the_overall_line(self, capsys):
        hosts = {"tight": parse_tracking(TRACKING),
                 "loose": tracking_with(root_dispersion_s=0.02, root_delay_s=0.02)}
        report(hosts, 1.0)
        out = capsys.readouterr().out
        assert "VISIBLE" in out and "overall" in out

    def test_a_host_without_a_bound_does_not_crash_the_table(self, capsys):
        hosts = {"a": parse_tracking(TRACKING), "b": parse_tracking("")}
        rows = report(hosts, 1.0)
        assert rows[0]["bound_ms"] == ""
        assert "-" in capsys.readouterr().out


class TestCLI:
    def _write(self, p, text=TRACKING):
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_it_writes_the_csv(self, tmp_path, capsys):
        """The fixture's root delay/dispersion put the pair bound at 4.3 ms, above a 1 ms tick."""
        a = self._write(tmp_path / "a.txt")
        b = self._write(tmp_path / "b.txt")
        out = tmp_path / "clocks.csv"
        assert main(["--tracking", f"drv={a}", "--tracking", f"b1={b}",
                     "--resolution-ms", "1.0", "--out", str(out)]) == 0
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert len(rows) == 1 and rows[0]["verdict"] == "VISIBLE"
        assert float(rows[0]["bound_ms"]) == pytest.approx(4.3)
        assert "VISIBLE" in capsys.readouterr().out

    def test_a_tightly_synced_pair_writes_masked(self, tmp_path):
        tight = TRACKING.replace("0.002500000", "0.000200000").replace(
            "0.000900000", "0.000100000")
        a = self._write(tmp_path / "a.txt", tight)
        b = self._write(tmp_path / "b.txt", tight)
        out = tmp_path / "clocks.csv"
        assert main(["--tracking", f"a={a}", "--tracking", f"b={b}", "--out", str(out)]) == 0
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert rows[0]["verdict"] == "MASKED"

    def test_one_host_is_not_enough(self, tmp_path, capsys):
        a = self._write(tmp_path / "a.txt")
        assert main(["--tracking", f"drv={a}"]) == 1
        assert "at least two hosts" in capsys.readouterr().out

    def test_a_malformed_spec_is_rejected(self, tmp_path, capsys):
        assert main(["--tracking", "no-equals-sign"]) == 1
        assert "bad --tracking" in capsys.readouterr().out

    def test_a_missing_file_is_rejected(self, tmp_path, capsys):
        assert main(["--tracking", f"drv={tmp_path / 'absent.txt'}"]) == 1
        assert "missing" in capsys.readouterr().out

    def test_no_out_still_reports(self, tmp_path, capsys):
        a = self._write(tmp_path / "a.txt")
        b = self._write(tmp_path / "b.txt")
        assert main(["--tracking", f"a={a}", "--tracking", f"b={b}"]) == 0
        assert "overall" in capsys.readouterr().out
