"""Tests for the numbers emitted when the late messages were left out (7 October 2026).

Leaving out the messages that waited behind a stale backlog (scripts/stale_backlog.py) took a
different number from every cell, moved the traced and repeated campaigns most, and turned
three hand-typed tables into stale copies. The emitter now states each table's range of cells,
generates the placement, padding and tracer tables, reads the tracer's effect and the repeat's
fit from their files, and carries the census behind the supplement's account of both consumer
faults. Each is tested against the committed artefacts the documents read, and each guard
against a missing file on its own.
"""
import csv
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import emit_paper_numbers as epn  # noqa: E402
import priority_pairs  # noqa: E402
import stat_intervals  # noqa: E402

REPO = SCRIPTS_DIR.parent
GENERATED = REPO / "docs" / "generated"


def _boom(*_args, **_kwargs):
    raise OSError("gone")


def _generated(name):
    return (GENERATED / name).read_text(encoding="utf-8").replace("\r\n", "\n")


class TestEachTableStatesTheRangeOfItsCells:

    def test_the_committed_ranges(self):
        m = dict(epn.cell_events_macros())
        assert (m["mechEventsLo"], m["mechEventsHi"]) == ("2{,}408", "2{,}985")
        assert (m["tracerEventsLo"], m["tracerEventsHi"]) == ("2{,}257", "2{,}985")
        assert (m["prioEventsLo"], m["prioEventsHi"]) == ("2{,}973", "2{,}985")
        assert (m["geomEventsLo"], m["geomEventsHi"]) == ("2{,}497", "2{,}985")
        assert (m["payloadEventsLo"], m["payloadEventsHi"]) == ("2{,}408", "2{,}980")

    def test_a_configuration_sums_its_runs(self, tmp_path):
        path = tmp_path / "runs.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(("campaign", "cell", "backend", "run_events"))
            w.writerows([("E-A3", "bg0", "kafka", "100"), ("E-A3", "bg0", "kafka", "20"),
                         ("E-A3", "bg0", "redis", "7")])
        assert epn._configuration_events(str(path)) == {("E-A3", "bg0", "kafka"): 120,
                                                         ("E-A3", "bg0", "redis"): 7}

    def test_one_table_with_cells_that_agree_prints_one_number_twice(self):
        assert epn._events_span("x", [5, 5]) == [("xLo", "5"), ("xHi", "5")]

    def test_a_missing_file_drops_only_its_own_ranges(self, monkeypatch):
        """The run-level counts carry two tables, Table II's and the tracer table's."""
        for target, name, gone in ((epn, "_configuration_events", ("mech", "tracer")),
                                   (priority_pairs, "usable", ("prio",)),
                                   (epn, "_geometry_rows", ("geom",)),
                                   (epn, "_payload_rows", ("payload",))):
            with monkeypatch.context() as m:
                m.setattr(target, name, _boom)
                macros = dict(epn.cell_events_macros())
            assert not any(k.startswith(gone) for k in macros), name
            assert len(macros) == 10 - 2 * len(gone), name


class TestTheTracersEffect:

    def test_the_committed_twin_and_traced_cells(self):
        m = dict(epn.tracer_macros())
        assert (m["untracedRtNegatives"], m["untracedRtEvents"]) == ("15", "2{,}985")
        assert m["tracedKafkaDriftMaxPct"] == "5"
        assert (m["tracerRtEventsLo"], m["tracerRtEventsHi"]) == ("2{,}447", "2{,}723")
        assert m["tracedZeroChanceOne"] == "$1{\\times}10^{-6}$"
        assert m["tracedZeroChanceAll"] == "$10^{-17}$"

    def test_without_its_files_nothing_is_emitted(self, tmp_path):
        assert epn.tracer_macros(untraced=str(tmp_path / "none.csv")) == []


class TestTheGeneratedTables:

    def test_the_placement_table(self):
        body = epn.render_geometry_table()
        assert body == _generated("geometry_table.tex")
        assert "$7/8$ & $0.2281$ & $0.2415$ & $1.22$ & $0.2359$ & $0.2752$ & $3.20$" in body

    def test_the_padding_table(self):
        body = epn.render_payload_table()
        assert body == _generated("payload_table.tex")
        assert "$262{,}144$ & $51.768$ & $0.0683$ & $51.795$ & $0.0681$" in body

    def test_the_tracer_table(self):
        body = epn.render_tracer_table()
        assert body == _generated("tracer_table.tex")
        assert "E-A9 & real-time & $88\\%$ & $0.8819$ & $570{,}591$ & $0.018$ & $0.011$ & " \
               "$1.63^{\\ddagger}$ & $0.000$ & --- \\\\" in body

    def test_the_replications_seventh_core(self):
        assert dict(epn.geometry_seven_macros()) == {"geomSevenReplFactor": "1.17",
                                                     "geomSevenReplZ": "3.20"}
        assert epn.geometry_seven_macros("no_such_phase") == []


class TestTheRepeatsFit:

    def test_the_committed_repeat_and_the_trace_check(self):
        m = dict(epn.stat_macros())
        assert (m["tailExponentRepl"], m["tailPrefactorRepl"]) == ("0.333", "0.242")
        assert (m["tailPredictedPTail"], m["tailTracedPTail"]) == ("0.298", "0.181")
        assert (m["tailCrossRatio"], m["tailCrossRatioRepl"]) == ("1.65", "1.69")

    def test_without_the_repeat_its_numbers_are_not_claimed(self, monkeypatch):
        real = stat_intervals.payload_fit

        def only_the_first(phase=None):
            if phase == "ea10b":
                raise OSError("gone")
            return real(phase)
        monkeypatch.setattr(stat_intervals, "payload_fit", only_the_first)
        m = dict(epn.stat_macros())
        assert "tailExponent" in m and "tailExponentRepl" not in m


class TestTheCensusBehindTheDisclosure:

    def test_the_committed_census(self):
        m = dict(epn.backlog_macros())
        assert (m["backlogJoined"], m["backlogRateBeforePct"]) == ("738{,}730", "8.43")
        assert (m["backlogWideExtra"], m["backlogWideRatePct"]) == ("1{,}898", "8.81")
        assert (m["backlogFastestMedianMs"], m["backlogFastestHiMs"]) == ("1.5", "111")
        assert m["backlogLate"] == "30{,}225" and m["backlogRuns"] == "2{,}099"
        assert (m["backlogAzureRuns"], m["backlogAzureStartRuns"]) == ("9{,}055", "31")
        assert m["backlogAzureLatePct"] == "0.06"

    def test_without_the_registered_campaigns_census_it_is_not_described(self, tmp_path):
        m = dict(epn.backlog_macros(azure=str(tmp_path / "none.csv")))
        assert "backlogAzureLatePct" not in m and "backlogLate" in m


class TestTheRecoveryCaptionFollowsTheCurves:
    """S16.9's caption and its sentence on thirds hold only for the shape the data have."""

    def _macros(self, monkeypatch, crossings=None, split=None):
        if crossings is not None:
            monkeypatch.setattr(stat_intervals, "ecdf_crossings", lambda a, b: crossings)
        if split is not None:
            monkeypatch.setattr(stat_intervals, "equal_split_edges", lambda values: split)
        return dict(epn._recovery_macros())

    def test_the_committed_curves_cross_once(self):
        m = dict(epn._recovery_macros())
        assert m["recoveryEcdfCross"] == "18.2" and "recoveryEcdfCrossLo" not in m

    def test_two_crossings_give_a_change_and_a_change_back(self, monkeypatch):
        m = self._macros(monkeypatch, crossings=[18.2, 34.8])
        assert (m["recoveryEcdfCrossLo"], m["recoveryEcdfCrossHi"]) == ("18.2", "34.8")
        assert "recoveryEcdfCross" not in m

    def test_curves_that_never_cross_give_neither(self, monkeypatch):
        m = self._macros(monkeypatch, crossings=[])
        assert not any(k.startswith("recoveryEcdfCross") for k in m)

    def test_the_committed_thirds_stop_short_of_the_quartile(self):
        m = dict(epn._recovery_macros())
        assert (m["recoveryThirdsEdgeLo"], m["recoveryThirdsEdgeHi"]) == ("16.7", "19.2")

    def test_thirds_that_reach_the_quartile_withdraw_the_sentence(self, monkeypatch):
        m = self._macros(monkeypatch, split=(16.7, 20.0))
        assert "recoveryThirdsEdgeLo" not in m and "recoveryThirdsEdgeHi" not in m
