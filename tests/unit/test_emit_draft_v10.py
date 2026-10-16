"""Tests for the macros and tables the revised draft of 15 October 2026 reads.

The draft quotes numbers no macro carried: how the one-process tools split by what they time,
how many of the tools' maintainers are organizations, the audit's count without its edge cases
and at its strictest, the law's freely fitted slopes, the share of acknowledgments past 1 ms,
what the socket-timestamping module cost and how wide the fix's intervals reach, where the
real-time floor sits in a run, the runs of the co-located control, and Redis's floor by load.
It also sets Table I narrow, says Table II's placement row in words, and asks Supplement S5 for
two tables, the audit's count under each reading and every tool run (since that evening one table
with the tools' slopes and clocks), and for its registry to name maintainers. Each is tested
against the committed artefacts the documents read, on a small world where its guards need one,
and with its file absent.
"""
import csv
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import emit_paper_numbers as epn  # noqa: E402
import harness_registry  # noqa: E402

REPO = SCRIPTS_DIR.parent
GENERATED = REPO / "docs" / "generated"


def _csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return str(path)


def _generated(name):
    return (GENERATED / name).read_text(encoding="utf-8").replace("\r\n", "\n")


# --- item 1: the one-process tools by what they time ---------------------------------------------

class TestTheOneProcessTools:

    def test_round_trips_and_acknowledgments_among_them(self):
        got = dict(epn.tools_block_macros())
        assert (got["toolsOneProcessTripWord"], got["toolsOneProcessAckWord"]) == ("eight", "four")
        assert got["toolsOneProcessWord"] == "19"


# --- item 2: the maintainers that are organizations ----------------------------------------------

class TestTheOrganizations:

    def test_the_committed_registry(self):
        got = dict(epn.registry_macros())
        assert (got["harnessOrganizationsWord"], got["harnessOrganizationsWordCap"]) == ("14",
                                                                                        "14")
        assert "harnessOrganizations" not in got, "the documents quote the word alone"
        s = harness_registry.summary()
        assert s["vendors"] - s["organizations"] == len(harness_registry.INDIVIDUAL_VENDORS)

    def test_a_person_no_row_names_stops_the_count(self, monkeypatch):
        monkeypatch.setitem(harness_registry.INDIVIDUAL_VENDORS, "Nobody", "a stale name")
        with pytest.raises(ValueError, match="Nobody"):
            epn.registry_macros()

    def test_the_summary_counts_the_vendors_it_does_not_name_as_people(self):
        def row(harness, vendor):
            return {"harness": harness, "vendor": vendor, "language": "C", "path": "end-to-end",
                    "clock": "millisecond", "file": "f.c", "symbol": "s", "evidence": "x = 1;",
                    "source_url": "u", "retrieved": "2026-10-15", "note": ""}
        s = harness_registry.summary([row("A", "Jens Axboe"), row("B", "A Company"),
                                      row("C", "A Company")])
        assert (s["vendors"], s["organizations"], s["individuals"]) == (2, 1, ["Jens Axboe"])

    def test_every_person_named_is_a_vendor_of_the_committed_registry_with_a_reason(self):
        vendors = {r["vendor"] for r in harness_registry.load()}
        assert set(harness_registry.INDIVIDUAL_VENDORS) <= vendors
        assert all(len(reason) > 20 for reason in harness_registry.INDIVIDUAL_VENDORS.values())


# --- item 3: the audit without its edge cases, and at its strictest ------------------------------

AUDIT = ("step", "cut", "cut_uncounted", "message_tools")


class TestTheAuditSteps:

    def test_the_committed_steps(self):
        assert epn.audit_step_macros() == [("auditLessEdgeWord", "17"),
                                           ("auditStrictWord", "twelve"),
                                           ("auditStrictUncountedWord", "eleven")]

    def test_a_missing_file_emits_nothing(self, tmp_path):
        assert epn.audit_step_macros(str(tmp_path / "none.csv")) == []

    def test_steps_named_otherwise_stop_the_sentence(self, tmp_path):
        rows = [(name, 5, 4, 24) for name, _flag in reversed(
            __import__("audit_sensitivity").STEPS)]
        with pytest.raises(ValueError, match="strictest reading"):
            epn.audit_step_macros(_csv(tmp_path / "a.csv", AUDIT, rows))

    def test_an_edge_step_that_leaves_out_other_kinds_stops_the_sentence(self, monkeypatch):
        monkeypatch.setattr(epn, "AUDIT_EDGE_STEP", "as counted")
        with pytest.raises(ValueError, match="edge cases"):
            epn.audit_step_macros()

    def test_the_generated_table(self):
        body = epn.render_audit_sensitivity_table()
        assert body == _generated("audit_sensitivity_table.tex")
        assert "Reading of the classification & Cut, of $24$ & Of them, uncounted \\\\" in body
        assert "Less a disposal the tool announces or crashes on & $12$ & $11$ \\\\" in body

    def test_steps_out_of_different_totals_are_refused(self, tmp_path):
        path = _csv(tmp_path / "a.csv", AUDIT, [("as counted", 19, 18, 24),
                                               ("less a thing", 18, 17, 23)])
        with pytest.raises(ValueError, match="same message tools"):
            epn.render_audit_sensitivity_table(path)


# --- items 4 to 7: the law's free slopes, the acknowledgments past 1 ms, the module, the fix -----

class TestTheReadings:

    def test_the_committed_values(self):
        got = dict(epn.law_free_slope_macros() + epn.ack_past_one_macros()
                   + epn.module_cost_macros() + epn.fix_interval_macros())
        assert got == {
            "lawFreeSlopeKafka": "0.76", "lawFreeSlopeRedis": "1.01",
            "ackPastOneKafkaLo": "8.6", "ackPastOneKafkaHi": "18.2",
            "ackPastOneRedisLo": "4.8", "ackPastOneRedisHi": "10.9",
            "moduleCostKafkaLo": "-51", "moduleCostKafkaHi": "+76",
            "moduleCostRedisLo": "+15", "moduleCostRedisHi": "+45",
            "moduleTailLo": "-197", "moduleTailHi": "+183",
            "fixCaptureMedianCIHiPct": "12", "fixCaptureTailCIHiPct": "44",
            "fixSocketMedianCIHiPct": "14"}

    @pytest.mark.parametrize("us, want", [(15.14, "+15"), (-50.87, "-51"), (0.2, "+0"),
                                          (75.5, "+76")])
    def test_a_signed_whole_microsecond(self, us, want):
        assert epn._signed_us(us) == want

    @pytest.mark.parametrize("emit", [epn.law_free_slope_macros, epn.ack_past_one_macros,
                                      epn.module_cost_macros, epn.fix_interval_macros])
    def test_a_missing_file_emits_nothing(self, emit, tmp_path):
        assert emit(str(tmp_path / "none")) == []

    def test_the_tail_spans_every_setup_and_the_cost_each_broker(self, tmp_path):
        head = ("backend", "load_pct", "priority", "client_without", "client_with",
                "client_change", "D_p99_without", "D_p99_with")
        path = _csv(tmp_path / "m.csv", head, [("kafka", 0, False, 1, 1, -3.4, 10, 12),
                                              ("kafka", 88, True, 1, 1, 7.6, 10, 9),
                                              ("redis", 0, False, 1, 1, 2.0, 5, 105.4)])
        assert dict(epn.module_cost_macros(path)) == {
            "moduleCostKafkaLo": "-3", "moduleCostKafkaHi": "+8", "moduleCostRedisLo": "+2",
            "moduleCostRedisHi": "+2", "moduleTailLo": "-1", "moduleTailHi": "+100"}

    def test_each_interval_reads_its_own_block_and_statistic(self, tmp_path):
        head = ("block", "latency", "statistic", "comparison", "move", "lo", "hi", "band",
                "point_inside", "interval_inside")
        rows = [("F1", "W", "median", "a", 0, 0, 0.101, 0.1, True, True),
                ("F1", "W", "p99", "a", 0, 0, 0.3, 0.25, True, True),
                ("F2", "Wso", "median", "a", 0, 0, 0.2, 0.1, True, True),
                ("F2", "Wso", "p99", "a", 0, 0, 500.0, 0.25, True, False)]
        assert dict(epn.fix_interval_macros(_csv(tmp_path / "f.csv", head, rows))) == {
            "fixCaptureMedianCIHiPct": "10", "fixCaptureTailCIHiPct": "30",
            "fixSocketMedianCIHiPct": "20"}


# --- item 8: the real-time floor -----------------------------------------------------------------

FLOOR = ("campaign", "phase", "cell", "backend", "run", "run_events", "run_negatives", "ranks",
         "first_instant", "first_ack_ms")


class TestTheFloor:

    def test_the_committed_floor(self):
        assert epn.rt_floor_macros() == [("rtFloorBurstWord", "five"), ("rtFloorAckLoMs", "107"),
                                         ("rtFloorAckHiMs", "395"), ("rtFloorRedisRankLo", "3"),
                                         ("rtFloorRedisRankHi", "145")]

    def test_a_missing_file_emits_nothing(self, tmp_path):
        assert epn.rt_floor_macros(str(tmp_path / "none.csv")) == []

    def test_a_negative_past_the_first_instant_stops_the_sentence(self, tmp_path):
        rows = [("E-A5", "ea5", "l75_rt", "kafka", "r1", 100, 1, "6", 5, "110.0"),
                ("E-A5", "ea5", "l75_rt", "redis", "r2", 100, 1, "40", 5, "5.0")]
        with pytest.raises(ValueError, match="rank 6"):
            epn.rt_floor_macros(_csv(tmp_path / "f.csv", FLOOR, rows))

    def test_runs_without_a_negative_set_no_bound(self, tmp_path):
        rows = [("E-A5", "ea5", "l75_rt", "kafka", "r1", 100, 2, "1 3", 5, "120.4"),
                ("E-A5", "ea5", "l75_rt", "kafka", "r2", 100, 0, "", 5, "900.0"),
                ("E-A5", "ea5", "l75_rt", "redis", "r3", 100, 2, "7 40", 5, "5.0")]
        assert dict(epn.rt_floor_macros(_csv(tmp_path / "f.csv", FLOOR, rows))) == {
            "rtFloorBurstWord": "three", "rtFloorAckLoMs": "120", "rtFloorAckHiMs": "120",
            "rtFloorRedisRankLo": "7", "rtFloorRedisRankHi": "40"}


# --- item 9: the co-located control --------------------------------------------------------------

RUNS = ("result", "campaign", "phase", "cell", "arm", "backend", "run", "run_events",
        "run_negatives")


class TestTheColocatedControl:

    def test_the_committed_runs(self):
        assert epn.colocated_macros() == [("colocatedRunsWord", "50")]

    def test_a_missing_file_emits_nothing(self, tmp_path):
        assert epn.colocated_macros(str(tmp_path / "none.csv")) == []

    def test_brokers_that_ran_different_counts_are_each_named(self, tmp_path):
        rows = [("colocation", "E-A8", "ea8", "colocated_l0", "co-located", "kafka", "a", 1, 0),
                ("colocation", "E-A8", "ea8", "colocated_l0", "co-located", "kafka", "b", 1, 0),
                ("colocation", "E-A8", "ea8", "colocated_l0", "co-located", "redis", "c", 1, 0),
                ("colocation", "E-A8", "ea8", "remote_l0", "remote", "redis", "d", 1, 0)]
        assert epn.colocated_macros(_csv(tmp_path / "r.csv", RUNS, rows)) == [
            ("colocatedKafkaRuns", "2"), ("colocatedRedisRuns", "1")]

    def test_table_two_leaves_the_control_out(self):
        own = epn._configuration_events()
        assert not any(campaign == "E-A8" for campaign, _cell, _b in own)


# --- item 12: Redis's floor by load --------------------------------------------------------------

class TestRedisFloorByLoad:

    def test_the_committed_pairs(self):
        assert dict(epn.redis_floor_macros()) == {
            "rtRedisFloorLightLoad": "0.0191", "rtRedisNormalLightLoad": "0.1229",
            "rtRedisFloorLightLoadPct": "1.9", "rtRedisNormalLightLoadPct": "12",
            "rtRedisLightLoadLo": "60", "rtRedisLightLoadHi": "75",
            "rtRedisFloorHeavyLoad": "0.0226", "rtRedisNormalHeavyLoad": "0.1676",
            "rtRedisFloorHeavyLoadPct": "2.3", "rtRedisNormalHeavyLoadPct": "17",
            "rtRedisHeavyLoadLo": "88", "rtRedisHeavyLoadHi": "95"}

    def test_a_missing_file_emits_nothing(self, tmp_path):
        assert epn.redis_floor_macros(str(tmp_path / "none.csv")) == []

    def test_each_group_takes_the_median_of_its_own_pairs(self, tmp_path):
        head = ("result", "campaign", "level", "backend", "top", "bottom", "top_rate", "top_lo",
                "top_hi", "bottom_rate", "bottom_lo", "bottom_hi", "factor", "factor_lo",
                "factor_hi", "disjoint")
        rows = [("priority", "E-A5", "l75", "redis", "n", "r", 0.2, 0, 0, 0.01, 0, 0, 1, 1, 1, 1),
                ("priority", "E-A5b", "l60", "redis", "n", "r", 0.1, 0, 0, 0.03, 0, 0, 1, 1, 1, 1),
                ("priority", "E-A5", "l88", "redis", "n", "r", 0.5, 0, 0, 0.04, 0, 0, 1, 1, 1, 1),
                ("priority", "E-A5", "l88", "kafka", "n", "r", 0.9, 0, 0, 0.9, 0, 0, 1, 1, 1, 1),
                ("placement", "E-A6", "k6", "redis", "n", "r", 0.9, 0, 0, 0.9, 0, 0, 1, 1, 1, 1)]
        got = dict(epn.redis_floor_macros(_csv(tmp_path / "i.csv", head, rows)))
        assert (got["rtRedisFloorLightLoad"], got["rtRedisNormalLightLoad"]) == ("0.0200", "0.1500")
        assert (got["rtRedisFloorHeavyLoad"], got["rtRedisNormalHeavyLoad"]) == ("0.0400",
                                                                              "0.5000")
        assert (got["rtRedisLightLoadLo"], got["rtRedisLightLoadHi"]) == ("60", "75")
        assert (got["rtRedisHeavyLoadLo"], got["rtRedisHeavyLoadHi"]) == ("88", "88")
        assert (got["rtRedisFloorLightLoadPct"], got["rtRedisNormalLightLoadPct"]) == ("2.0", "15")
        assert (got["rtRedisFloorHeavyLoadPct"], got["rtRedisNormalHeavyLoadPct"]) == ("4.0", "50")


# --- the real-time rates in percent ---------------------------------------------------------------

class TestRatesInPercent:
    """16 Oct 2026: the paper prints the real-time rates in percent, as it prints every other rate.
    The twins keep two significant figures and are rounded once, from the rate itself."""

    def test_two_significant_figures_at_every_scale(self):
        assert [epn.rate_pct(r) for r in (0.0017, 0.0144, 0.0191, 0.1229, 0.1676, 0.5)] == [
            "0.17", "1.4", "1.9", "12", "17", "50"]

    def test_the_twin_is_rounded_once(self):
        """The four-decimal fraction of 0.0144949 is 0.0145, which would print 1.5."""
        assert epn.rate_pct(0.0144949) == "1.4"
        assert epn.rate_pct(float("%.4f" % 0.0144949)) == "1.5"

    def test_a_rate_of_zero_or_less_prints_zero(self):
        assert epn.rate_pct(0.0) == "0" and epn.rate_pct(-0.01) == "0"

    def test_the_paper_prints_the_twins_and_no_fraction(self):
        paper = (REPO / "paper.tex").read_text(encoding="utf-8")
        for name in ("rtResidualMin", "rtResidualMax", "rtRedisResidualMin", "rtRedisResidualMax",
                     "rtRedisFloorLightLoad", "rtRedisFloorHeavyLoad", "rtRedisNormalLightLoad",
                     "rtRedisNormalHeavyLoad"):
            assert "\\%sPct$" % name in paper or "\\%sPct\\%%$" % name in paper, name
            assert "\\%s$" % name not in paper, name


# --- the list and the ledger ---------------------------------------------------------------------

class TestTheLedger:

    def test_every_draft_macro_is_in_the_committed_ledger(self):
        text = _generated("paper_numbers.tex")
        for name, value in epn.draft_v10_macros():
            assert "\\newcommand{\\%s}{%s}\n" % (name, value) in text, name

    def test_the_draft_reads_every_name(self):
        names = [n for n, _ in epn.draft_v10_macros()]
        # 16 Oct 2026: 36, with the four percent twins of Redis's floor by load.
        assert len(names) == len(set(names)) == 36


# --- items 10 and 11: Table I narrow, Table II's placement row in words ---------------------------

class TestTheTables:

    def test_table_two_says_how_many_cores(self):
        body = epn.render_mechanism_table()
        assert "Placement on six cores & " in body and "k=6" not in body
        assert body == _generated("mechanism_table.tex")

    def test_table_one_is_the_generated_file(self):
        assert epn.render_spans_table() == _generated("spans_table.tex")


# --- item 13: every tool run, for Supplement S5 ---------------------------------------------------

class TestTheToolsTable:
    """Supplement S5's table of every tool run. Since the evening of 15 Oct 2026 it is one table
    with the table of the tools' slopes and clocks (referee A 9.7, B U5): one row a tool, with
    what it times, what the reading at source found it doing with a value at or below zero, its
    T1, T2 and S1 results, and the block that ran it, so a tool's author finds it once."""

    def test_the_generated_table(self):
        body = epn.render_tools_table()
        assert body == _generated("tools_run_table.tex")
        assert body.count("\\\\\n") == 34, "two header rows and one row for each of the 32 tools"
        assert ("hey & round trip & not read & --- & 1.00--1.04 & one & 8/8 & --- & "
                "21--22 (25--26) & 25 Sep & first \\\\") in body
        assert ("SBK & one process & discard & yes & 0.58--0.91 & one & 7/8 & 4/4 & 35 (38) & "
                "11 Oct & first \\\\") in body
        assert ("Pub/Sub load test & two processes & substitute & no & --- & two & 0/8 & 3/4 & "
                "38 (41) & 13 Oct & second \\\\") in body
        assert ("Sarama producer & to ack. & truncate & no & 1.01--1.34 & one & 8/8 & 0/4 & "
                "35 (38) & 11 Oct & first \\\\") in body

    def test_the_rows_run_from_two_hosts_to_a_round_trip_alphabetically_within(self):
        """The paper's Table III order, so a reader moves between the two by interval, and the
        alphabet within each, so a tool's author finds the row without reading the column."""
        rows = [line.split(" & ") for line in epn.render_tools_table().splitlines()
                if line.endswith("\\\\") and " & " in line][2:]
        interval = {cell: trip for trip, cell in epn.TRIP_CELLS.items()}
        keys = [(epn.TOOLS_TABLE_ORDER.index(interval[r[1]]),
                 r[0].replace("\\kafka{}", "Kafka").lower()) for r in rows]
        assert keys == sorted(keys) and len(keys) == 32
        assert rows[0][1] == "two hosts" and rows[-1][1] == "round trip"

    def test_the_blocks_are_read_from_the_freezes_and_the_rounds(self):
        blocks = epn.tools_blocks()
        assert [b["plans"] for b in blocks] == [(25, 26), (33,), (35,), (36,), (37,), (38,),
                                                (39,), (40,), (41,)]
        assert [b["pair"] for b in blocks].count("second") == 4
        assert sum(len(b["tools"]) for b in blocks) == 32

    def test_a_freeze_typed_wrong_stops_the_table(self, monkeypatch):
        wrong = ((31,),) + epn.TOOLS_BLOCKS[1][1:]
        monkeypatch.setattr(epn, "TOOLS_BLOCKS", (epn.TOOLS_BLOCKS[0], wrong)
                            + epn.TOOLS_BLOCKS[2:])
        with pytest.raises(ValueError, match="freeze 31 holds version 34"):
            epn.tools_blocks()

    def test_a_freeze_whose_source_names_no_version_is_refused(self, tmp_path):
        folder = tmp_path / "21-experiment-plan"
        folder.mkdir()
        (folder / "experiment_plan.tex").write_text("no number here", encoding="utf-8")
        with pytest.raises(ValueError, match="names no plan version"):
            epn._plan_version(21, str(tmp_path))

    @pytest.mark.parametrize("blocks", ["drop the last", "repeat a tool"])
    def test_a_tool_in_no_block_or_in_two_stops_the_table(self, monkeypatch, blocks):
        last = epn.TOOLS_BLOCKS[-1]
        changed = {"drop the last": epn.TOOLS_BLOCKS[:-1],
                   "repeat a tool": epn.TOOLS_BLOCKS[:-1] + (last[:2] + (last[2] + ("hey",),),)}
        monkeypatch.setattr(epn, "TOOLS_BLOCKS", changed[blocks])
        with pytest.raises(ValueError, match="the tools blocks list"):
            epn.render_tools_table()

    def test_a_tool_with_no_registry_entry_stops_the_table(self, monkeypatch):
        monkeypatch.delitem(epn.TOOL_REGISTRY_PATHS, "hey")
        with pytest.raises(ValueError, match="TOOL_REGISTRY_PATHS maps"):
            epn.render_tools_table()

    def test_a_registry_span_the_registry_does_not_hold_stops_the_table(self, monkeypatch):
        """A tool sent to a span no registry row folds to would print nothing true."""
        monkeypatch.setitem(epn.TOOL_REGISTRY_PATHS, "hey", ("hey", "end-to-end"))
        with pytest.raises(ValueError, match="spans the registry does not hold"):
            epn.render_tools_table()

    def test_an_s1_tool_no_block_ran_stops_the_table(self):
        with pytest.raises(ValueError, match="which no tools block ran"):
            epn.render_tools_table(s1={"no-such-tool": (4, 4)})

    def test_s1_is_read_by_the_blocks_names_with_each_round_judged(self):
        """Twelve tools ran S1. Stream PerfTest ran it as one instance (D37-4), its row the one
        its block gives; Sarama's prediction failed in every round, Pub/Sub's in one."""
        held = epn._s1_held()
        assert len(held) == 12 and "stream-perftest-one" not in held
        assert held["stream-perftest"] == (4, 4)
        assert (held["sarama-producer-perf"], held["pubsub-loadtest"]) == ((0, 4), (3, 4))

    @pytest.mark.parametrize("fold, cells", [
        ({"kinds": {"positive_only_filter", "quantized_retention"}, "counts_discards": False},
         ("filter $>0$; truncate", "no")),
        ({"kinds": {"silent_suppression"}, "counts_discards": True}, ("substitute", "yes")),
        ({"kinds": set(), "counts_discards": True}, ("discard", "yes")),
        ({"kinds": set(), "counts_discards": False, "tally_guard": True},
         ("zero in average", "no")),
        ({"kinds": set(), "counts_discards": False}, ("---", "---")),
    ], ids=["two responses on one line", "counted", "a counted discard", "a tally's guard",
            "nothing removed"])
    def test_the_short_cells_say_what_the_registrys_cells_say(self, fold, cells):
        assert epn._tools_run_cells(fold) == cells

    def test_a_registry_response_with_no_short_word_stops_the_table(self, monkeypatch):
        monkeypatch.delitem(epn.TOOLS_TABLE_LABELS, "library_refusal")
        with pytest.raises(ValueError, match="short words"):
            epn.render_tools_table()

    def test_main_leaves_the_table_alone_without_s1s_verdicts(self, tmp_path, monkeypatch):
        """Its S1 column needs S1's verdicts; without them the table is not written, as without
        the tools block's own tables, rather than written with a column of nothing."""
        monkeypatch.setattr(epn, "S1_VERDICTS", str(tmp_path / "none.json"))
        led = _csv(tmp_path / "l.csv", LEDGER_FIELDS,
                   [("load_sweep", "c0", "1", "shutdown_hook", 10, 90, 0)])
        tools = tmp_path / "tools.tex"
        assert epn.main(["--ledger", led, "--out", str(tmp_path / "n.tex"), "--table",
                         str(tmp_path / "t.tex"), "--tools-table", str(tools)]) == 0
        assert not tools.exists()


# --- the registry names maintainers, as the paper counts them ------------------------------------

class TestTheRegistryNamesMaintainers:
    """15 Oct 2026, the referees' M5: the paper counts the tools' maintainers, organizations and
    people alike, so the registry's column says maintainer where it said vendor."""

    def test_the_column_is_the_maintainer(self):
        body = epn.render_registry_table()
        assert body == _generated("registry_table.tex")
        header = [line for line in body.splitlines() if line.startswith("Tool & ")]
        assert header == ["Tool & Language, maintainer & Span measured & Clock & What happens to "
                          "the value & Counts \\\\"]


# --- freeze 41, read through its own judges --------------------------------------------------------

LEDGER_FIELDS = ("campaign", "cell", "valid", "count_source",
                 "kept", "discarded_zero", "discarded_negative")


class TestFreezeFortyOne:
    """Freeze 41's macros and Supplement S3.11's table come through scripts/order_scope_numbers.py,
    which reads the record's run tables with the freeze's own judges (15 Oct 2026)."""

    def test_every_macro_is_in_the_committed_ledger(self):
        text = _generated("paper_numbers.tex")
        pairs = epn.order_scope_macros()
        assert len(pairs) > 30, "every block of the freeze is committed"
        for name, value in pairs:
            assert "\\newcommand{\\%s}{%s}\n" % (name, value) in text, name

    def test_the_committed_table(self):
        body = epn.render_order_scope_table()
        assert body == _generated("order_scope_table.tex")
        assert body.count("not confirmed") == 5, "K-d, R-a, R-b, P-b and L-b"

    def test_a_record_with_no_blocks_emits_nothing(self, tmp_path):
        assert epn.order_scope_macros(str(tmp_path)) == []
        assert epn.render_order_scope_table(str(tmp_path)) == ""

    @pytest.mark.parametrize("body", ["", "a table\n"])
    def test_main_writes_the_table_only_once_every_block_is_committed(self, tmp_path,
                                                                       monkeypatch, body):
        monkeypatch.setattr(epn, "render_order_scope_table", lambda *a, **kw: body)
        led = _csv(tmp_path / "l.csv", LEDGER_FIELDS,
                   [("load_sweep", "c0", "1", "shutdown_hook", 10, 90, 0)])
        scope = tmp_path / "scope.tex"
        assert epn.main(["--ledger", led, "--out", str(tmp_path / "n.tex"), "--table",
                         str(tmp_path / "t.tex"), "--order-scope-table", str(scope)]) == 0
        assert scope.exists() == bool(body)


# --- the groups against the exposure curve, by broker ---------------------------------------------

class TestTheGroupsAgainstTheCurve:
    """Section VI says all of Kafka's groups lie above the curve drawn at the median publish
    latency and Redis's straddle it; Supplement S2.1 gives the counts (15 Oct 2026, an internal
    review of the figures: the text had said that every group lies above it)."""

    def test_the_committed_counts_bear_out_the_sentences(self):
        m = dict(epn.exposure_side_macros())
        assert m["exposureKafkaAbove"] == m["exposureKafkaGroups"], "'all its groups' is false"
        assert 0 < int(m["exposureRedisAbove"]) < int(m["exposureRedisGroups"]), \
            "'straddle it' is false"
        paper = (REPO / "paper.tex").read_text(encoding="utf-8")
        assert "so all its groups lie above that\ncurve, while \\redis{}'s straddle it" in paper

    def test_a_group_lies_above_when_its_error_exceeds_the_median_publish_latency(self, tmp_path):
        path = _csv(tmp_path / "span_symmetry.csv",
                    ("condition", "median_A_us", "median_D_us", "median_S_us"),
                    [("kafka_a", 1000, 3000, 1500), ("kafka_b", 1000, 2000, 500),
                     ("redis_a", 200, 900, 800), ("redis_b", 200, 1500, 100),
                     ("redis_c", 0, 0, 0)])
        assert epn.exposure_side_macros(path) == [
            ("exposureKafkaGroups", "2"), ("exposureKafkaAbove", "2"),
            ("exposureRedisGroups", "2"), ("exposureRedisAbove", "1")]

    def test_a_missing_file_emits_nothing(self, tmp_path):
        assert epn.exposure_side_macros(str(tmp_path / "absent.csv")) == []


# --- the repair's error by broker and by the sign check's verdict ---------------------------------

class TestTheRepairByBrokerAndVerdict:
    """Supplement S2.1 says the pooled shift between the check's verdicts excludes zero because the
    rejected groups are mostly Redis's, whose errors are the larger, and that broker by broker the
    verdict makes no detectable difference; the paper's Section VI says the last (15 Oct 2026)."""

    def test_the_committed_values_bear_out_the_sentences(self):
        m = dict(epn._all_pairs(epn.measured(epn.load_cells(
            str(REPO / "docs" / "results" / "external_campaigns_index.csv")))))
        assert int(m["recoveryRedisFailN"]) > int(m["recoveryKafkaFailN"]), "'mostly Redis's'"
        assert float(m["recoveryErrRedis"]) > float(m["recoveryErrKafka"]), "'the larger'"
        for broker in ("Kafka", "Redis"):
            lo, hi = (float(v) for v in m["recovery%sShiftCI" % broker].split("$ to $"))
            assert lo < 0 < hi, "%s: 'no detectable difference' is false" % broker
        lo, _hi = (float(v) for v in m["recoveryShiftCI"].split("$ to $"))
        assert lo > 0, "the pooled shift no longer excludes zero; S2.1's 'because' is moot"
