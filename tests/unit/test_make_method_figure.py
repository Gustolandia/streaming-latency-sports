"""Tests for scripts/make_method_figure.py - target 100% branch coverage.

The figure is a claim-to-experiment map, so the test that matters is not that it renders but
that its content stays in step with the paper: every campaign the paper reports must have a row,
and no row may claim to both generate and test a hypothesis.
"""
from pathlib import Path
import sys

import pytest
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from make_method_figure import ROWS, draw, main  # noqa: E402


class TestRows:
    def test_every_row_is_complete(self):
        for row in ROWS:
            assert len(row) == 4, f"row {row[0]!r} must have all four columns"
            assert all(str(cell).strip() for cell in row), f"row {row[0]!r} has an empty cell"

    def test_the_four_measured_rules_each_have_an_experiment(self):
        settles = " ".join(r[3] for r in ROWS)
        for rule in ("H1", "H2", "H3", "H4"):
            assert rule in settles, f"{rule} has no campaign in the map"

    def test_the_newer_claims_are_covered(self):
        settles = " ".join(r[3] for r in ROWS)
        assert "H10" in settles, "the mixture finding must trace to a campaign"
        assert "recovery" in settles, "the F_Delta recovery must trace to a campaign"
        assert "start-up" in settles, "the second withdrawal must trace to a campaign"

    def test_the_confounded_sweep_is_labelled(self):
        """The delay sweep confounds T_true with backlog; the map must not hide that."""
        delay = [r for r in ROWS if "delay" in r[0].lower()]
        assert delay, "the delay sweep must appear"
        assert "confounded" in delay[0][3].lower()

    def test_replicated_campaigns_say_so(self):
        joined = " ".join(r[0] + r[3] for r in ROWS).lower()
        assert "replicated" in joined or "x2" in joined, \
            "campaigns with an independent replication should be marked"


class TestDraw:
    def test_draws_a_chip_and_four_texts_per_row(self):
        fig, ax = plt.subplots()
        draw(ax)
        assert len(ax.patches) == len(ROWS), "one campaign chip per row"
        # 4 headers + 4 cells per row + 1 closing note
        assert len(ax.texts) == 4 + 4 * len(ROWS) + 1
        plt.close(fig)

    def test_axis_is_hidden(self):
        fig, ax = plt.subplots()
        draw(ax)
        assert not ax.axison
        plt.close(fig)

    def test_note_sits_below_the_last_row(self):
        fig, ax = plt.subplots()
        draw(ax)
        note = ax.texts[-1]
        last_row_y = len(ROWS) - (len(ROWS) - 1) - 0.5
        assert note.get_position()[1] < last_row_y - 0.5, "the note must clear the last row"
        plt.close(fig)


class TestMain:
    def test_writes_both_formats(self, temp_dir, capsys):
        out = temp_dir / "figs"
        assert main(["--out", str(out)]) == 0
        assert (out / "experiment_map.pdf").exists()
        assert (out / "experiment_map.png").exists()
        assert "wrote" in capsys.readouterr().out


class TestTheTransportSpanCell:
    """E-A10's cell is drawn into the supplement, so its number is published output.

    Round 34 found the payload sweep's transport ratio typed in twenty places; this table was
    one of them. The cell reads the campaign now, and falls back to the published literal so a
    checkout without the artefact still draws the figure that was published rather than a
    different one.
    """

    def test_it_reads_the_campaign(self):
        import make_method_figure as mmf
        assert mmf._transport_span() == "77"

    def test_it_falls_back_when_the_artefact_is_missing(self, monkeypatch):
        import make_method_figure as mmf
        import stat_intervals
        monkeypatch.setattr(stat_intervals, "payload_span",
                            lambda *a, **kw: (_ for _ in ()).throw(OSError("no campaign")))
        assert mmf._transport_span() == "77", "the fallback is the published value"

    def test_the_fallback_equals_what_the_campaign_gives(self):
        """If these ever diverge the fallback is a second source, which is the whole defect."""
        import make_method_figure as mmf
        import stat_intervals
        live = "%.0f" % round(stat_intervals.payload_span()["transport_factor"])
        assert mmf._transport_span() == live

    def test_the_row_carries_the_span(self):
        from make_method_figure import ROWS
        rows = [r for r in ROWS if "E-A10" in r[0]]
        assert len(rows) == 1, "one E-A10 row"
        assert "77x" in rows[0][1], "the manipulated cell names the span"


class TestTheMapReadsItsResultCells:
    """The three remaining hard-coded result values, retired.

    Round 34 fixed the transport span in this table and recorded the other three as a
    follow-up: the priority range, the geometry factors with their shared utilisation, and the
    tail index. All four are published numbers -- this map is drawn into the supplement -- and
    all four duplicated quantities the ledger already emits.

    Each helper falls back to the literal that was there before, and each fallback is asserted
    equal to what the campaign returns. A fallback that drifts from the derivation is a second
    source wearing a disguise, which is the defect these helpers exist to remove.
    """

    def test_the_priority_range_reads_the_campaign(self):
        import make_method_figure as mmf
        import priority_pairs
        s = priority_pairs.summary()
        assert mmf._priority_range() == "%d pairs, %.0f-%.0fx" % (
            s["pairs"], s["factor_low"], s["factor_high"])

    def test_the_geometry_result_reads_the_campaign(self):
        import make_method_figure as mmf
        import stat_intervals
        got = mmf._geometry_result()
        assert "at rho %g" % stat_intervals.geometry_rho("ea6") in got
        for phase in ("ea6", "ea6b"):
            (_, kc, nc), (_, ks, ns) = stat_intervals.geometry_cells(phase)
            assert "%.2fx" % stat_intervals.ratio_z(ks, ns, kc, nc)[1] in got

    def test_the_tail_index_reads_the_fit(self):
        import make_method_figure as mmf
        import stat_intervals
        assert mmf._tail_index() == "%.2f" % -stat_intervals.payload_fit()[0]

    @pytest.mark.parametrize("helper,module,attr,expected", [
        ("_priority_range", "priority_pairs", "summary", "8 pairs, 7-80x"),
        ("_geometry_result", "stat_intervals", "geometry_cells",
         "2.07x, 2.05x, at rho 0.7531"),
        ("_tail_index", "stat_intervals", "payload_fit", "0.34"),
    ])
    def test_each_falls_back_to_the_published_literal(self, monkeypatch, helper, module,
                                                      attr, expected):
        import importlib
        import make_method_figure as mmf
        mod = importlib.import_module(module)
        monkeypatch.setattr(mod, attr,
                            lambda *a, **kw: (_ for _ in ()).throw(OSError("no campaign")))
        assert getattr(mmf, helper)() == expected

    @pytest.mark.parametrize("helper", ["_transport_span", "_priority_range",
                                        "_geometry_result", "_tail_index"])
    def test_the_fallback_equals_the_derivation(self, helper, monkeypatch):
        """Both branches must produce the same string on the committed campaigns."""
        import importlib
        import make_method_figure as mmf
        live = getattr(mmf, helper)()
        broken = {"_transport_span": ("stat_intervals", "payload_span"),
                  "_priority_range": ("priority_pairs", "summary"),
                  "_geometry_result": ("stat_intervals", "geometry_cells"),
                  "_tail_index": ("stat_intervals", "payload_fit")}[helper]
        mod = importlib.import_module(broken[0])
        monkeypatch.setattr(mod, broken[1],
                            lambda *a, **kw: (_ for _ in ()).throw(OSError("no campaign")))
        assert getattr(mmf, helper)() == live, \
            "%s's fallback has drifted from what the campaign returns" % helper

    def test_the_rows_carry_the_derived_strings(self):
        from make_method_figure import ROWS, _priority_range, _geometry_result, _tail_index
        joined = " ".join(r[3] for r in ROWS)
        assert _priority_range() in joined
        assert _geometry_result() in joined
        assert "tail index %s" % _tail_index() in joined


class TestTheHeldFixedBounds:
    """The two "held fixed: utilization, to X" cells, which round 48's image review read.

    Both stated how closely utilization was matched between a campaign's two arms, and both
    typed the number. The priority cell was merely coarse. **The co-location cell was wrong:**
    it published "to 0.002" while `colocation.csv` records the arms differing by 0.0025 at
    idle, so the bound excluded a value the campaign itself had recorded.

    Nothing is computed from either cell, which is why every results-checking gate in the
    repository passed over a false statement in a published figure for as long as it stood.
    """

    def test_the_priority_bound_covers_every_pair(self):
        import make_method_figure as mmf
        import priority_pairs
        bound = float(mmf._priority_rho_match())
        for p in priority_pairs.pairs():
            assert abs(p["rho"] - p["rho_rt"]) <= bound, \
                "the map claims a bound a matched pair exceeds"

    def test_the_priority_bound_is_tight(self):
        """A bound of 1.0 would also 'cover every pair'. It must be the ceiling, not slack."""
        import make_method_figure as mmf
        import priority_pairs
        worst = max(abs(p["rho"] - p["rho_rt"]) for p in priority_pairs.pairs())
        assert float(mmf._priority_rho_match()) - worst < 0.001

    def test_the_colocation_bound_covers_every_level(self):
        import csv
        import make_method_figure as mmf
        bound = float(mmf._colocation_rho_match())
        with open(SCRIPTS_DIR.parent / "docs" / "results" / "model" / "colocation.csv",
                  newline="", encoding="utf-8-sig") as handle:
            for r in csv.DictReader(handle):
                assert abs(float(r["rho_remote"]) - float(r["rho_colocated"])) <= bound

    def test_the_colocation_bound_excludes_the_value_that_was_published(self):
        """The specific defect: 0.002 was printed and 0.0025 was measured."""
        import make_method_figure as mmf
        assert float(mmf._colocation_rho_match()) > 0.002

    @pytest.mark.parametrize("helper,module,attr", [
        ("_priority_rho_match", "priority_pairs", "pairs"),
        ("_colocation_rho_match", "csv", "DictReader"),
    ])
    def test_each_falls_back_to_the_published_literal(self, monkeypatch, helper, module,
                                                      attr):
        import importlib
        import make_method_figure as mmf
        mod = importlib.import_module(module)
        monkeypatch.setattr(mod, attr,
                            lambda *a, **kw: (_ for _ in ()).throw(OSError("no campaign")))
        assert getattr(mmf, helper)() == "0.003"

    @pytest.mark.parametrize("helper,module,attr", [
        ("_priority_rho_match", "priority_pairs", "pairs"),
        ("_colocation_rho_match", "csv", "DictReader"),
    ])
    def test_the_fallback_equals_the_derivation(self, monkeypatch, helper, module, attr):
        import importlib
        import make_method_figure as mmf
        live = getattr(mmf, helper)()
        mod = importlib.import_module(module)
        monkeypatch.setattr(mod, attr,
                            lambda *a, **kw: (_ for _ in ()).throw(OSError("no campaign")))
        assert getattr(mmf, helper)() == live, \
            "%s's fallback has drifted from what the campaign returns" % helper

    def test_the_rows_carry_the_derived_bounds(self):
        from make_method_figure import ROWS, _colocation_rho_match, _priority_rho_match
        held = [r[2] for r in ROWS]
        assert "utilization,\nto %s" % _priority_rho_match() in held
        assert "utilization,\nto %s" % _colocation_rho_match() in held

    def test_the_map_spells_utilization_the_way_the_manuscript_does(self):
        """IEEE sets US spelling, and the manuscript uses "utilization" 43 times. The map
        rendered the British form in six drawn cells, so one document printed both."""
        from make_method_figure import ROWS
        drawn = " ".join(part for row in ROWS for part in row)
        assert "utilisation" not in drawn, "figure text must match the manuscript's spelling"


class TestTheSharedUtilisation:
    """`geometry_rho` is new; the pair's whole claim is that both arms reached one value."""

    def test_it_returns_the_value_both_arms_reached(self):
        import stat_intervals
        assert stat_intervals.geometry_rho("ea6") == pytest.approx(0.7531)

    def test_it_refuses_a_pair_that_disagrees(self, monkeypatch, tmp_path):
        import stat_intervals
        monkeypatch.setattr(stat_intervals, "_rows", lambda *p: [
            {"condition": "k6_conc", "rho": "0.7531"},
            {"condition": "k6_spread", "rho": "0.8000"}])
        with pytest.raises(ValueError, match="disagree on rho"):
            stat_intervals.geometry_rho("ea6")
