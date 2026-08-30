"""Tests for scripts/omb_published_quantiles.py.

The script recovers a data series from a chart's tooltip text, so the thing to pin is the
recovery itself: well-formed tooltips come back as sorted (percentile, latency) pairs, junk is
declined rather than misparsed, and the two facts the figure quotes -- the 1 ms floor and the
percentile it appears at -- are computed, not asserted.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import omb_published_quantiles as opq  # noqa: E402


def svg(points, junk=True):
    descs = "".join('<desc class="value">%s %%: %s</desc>' % (p, v) for p, v in points)
    if junk:
        descs += '<desc class="value">not a pair</desc>'
        descs += '<desc class="x top">12</desc>'
    return "<svg>%s</svg>" % descs


class TestParse:
    def test_points_come_back_sorted_by_percentile(self, tmp_path):
        p = tmp_path / "c.svg"
        p.write_text(svg([("90.0", "3"), ("4.5", "1"), ("99.9", "600")]))
        pts = opq.parse_svg(str(p))
        assert pts == [(4.5, 1.0), (90.0, 3.0), (99.9, 600.0)]

    def test_junk_descs_are_declined_not_misparsed(self, tmp_path):
        p = tmp_path / "c.svg"
        p.write_text(svg([("50", "2")]))
        assert len(opq.parse_svg(str(p))) == 1


class TestDescribe:
    def test_the_floor_and_its_percentile_are_computed(self):
        d = opq.describe([(4.5, 1.0), (10.0, 1.0), (90.0, 3.0)])
        assert d["latency_floor_ms"] == 1.0
        assert d["percentile_at_floor"] == 4.5
        assert d["below_one_ms"] == 0 and d["below_zero"] == 0

    def test_an_empty_series_describes_to_nothing(self):
        assert opq.describe([]) == {}


class TestRoundTrip:
    def test_csv_out_and_back_preserves_the_series(self, tmp_path, monkeypatch):
        out = tmp_path / "q.csv"
        opq.write_csv([(4.5, 1.0), (90.0, 3.0)], str(out))
        assert opq.read_csv(str(out)) == [(4.5, 1.0), (90.0, 3.0)]

    def test_a_bare_filename_writes_in_place(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        opq.write_csv([(1.0, 1.0)], "bare.csv")
        assert (tmp_path / "bare.csv").exists()


class TestMain:
    def test_svg_mode_writes_and_reports(self, tmp_path, capsys):
        p = tmp_path / "c.svg"
        p.write_text(svg([("4.5", "1"), ("99.9", "692")]))
        out = tmp_path / "q.csv"
        rc = opq.main(["--svg", str(p), "--out", str(out)])
        assert rc == 0 and out.exists()
        text = capsys.readouterr().out
        assert "floor sits at" in text and "wrote" in text

    def test_summary_mode_reads_the_committed_csv(self, tmp_path, capsys):
        out = tmp_path / "q.csv"
        opq.write_csv([(4.5, 1.0), (99.0, 5.0)], str(out))
        rc = opq.main(["--summary", "--out", str(out)])
        assert rc == 0
        assert "points recovered" in capsys.readouterr().out

    def test_no_mode_at_all_is_an_argparse_error(self, capsys):
        with pytest.raises(SystemExit):
            opq.main([])
        assert "give --svg" in capsys.readouterr().err

    def test_an_svg_with_no_plotted_values_refuses_loudly(self, tmp_path):
        p = tmp_path / "c.svg"
        p.write_text("<svg><desc class='x top'>12</desc></svg>")
        with pytest.raises(SystemExit, match="no plotted values"):
            opq.main(["--svg", str(p), "--out", str(tmp_path / "q.csv")])
