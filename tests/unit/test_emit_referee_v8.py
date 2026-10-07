"""Tests for the numbers emitted for the 6 October 2026 revision.

The revision moved several quantities out of the prose and into the ledger: the trace ratios the
tracer check admits, the registered campaign's predictions of the rate from recorded waits, the
spread of the negative-span rate over runs, the steal time the registered campaign recorded, the
count of conditions behind the seventy groups of runs, and the rest-of-slice model's own bucket
ratio beside the measured one. Each is tested on a world small enough to work by hand, and against
the committed artefacts the paper reads.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import emit_paper_numbers as epn  # noqa: E402

REPO = SCRIPTS_DIR.parent


def _csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


RUNQ = ("tag", "arm", "rho", "inversion", "n_events", "p_tail", "estimator", "traced_events")


INTERVALS = ("result", "campaign", "level", "backend", "top", "bottom", "top_rate", "top_lo",
             "top_hi", "bottom_rate", "bottom_lo", "bottom_hi", "factor", "factor_lo",
             "factor_hi", "disjoint")


def _trace_row(campaign, level, backend, normal, rt):
    return ("trace", campaign, level, backend, "normal", "real-time", normal, "", "", rt, "",
            "", "", "", "", "")


class TestTheTraceCheckOnTheRunsItTraced:
    """The share of traced waits over the rate of both brokers' runs, which the trace counts."""

    def _world(self, root, twin):
        runq = root / "runq_tail.csv"
        _csv(runq, RUNQ, [("l88_base", "base", "0.88", "0.20", "100", "0.20", "exact", "1"),
                          ("l88_rt", "rt", "0.88", "0.0", "100", "0.01", "exact", "1")])
        runq_b = root / "b" / "runq_tail.csv"
        _csv(runq_b, RUNQ, [("l75_base", "base", "0.75", "0.10", "100", "0.15", "exact", "1"),
                            ("l75_rt", "rt", "0.75", "0.0", "100", "0.02", "exact", "1")])
        intervals = root / "intervals.csv"
        _csv(intervals, INTERVALS, [
            _trace_row("E-A9", "l88", "both", "0.25", "0.01"),
            _trace_row("E-A9b", "l75", "both", "0.10", "0.008"),
            _trace_row("E-A9-untraced", "l88", "both", twin, "0.012"),
            _trace_row("E-A9", "l88", "redis", "0.15", "0.020"),
            _trace_row("E-A9b", "l75", "redis", "0.11", "0.014"),
            _trace_row("E-A9-untraced", "l88", "redis", "0.15", "0.019")])
        files = ((str(runq), "E-A9"), (str(runq_b), "E-A9b"))
        return str(intervals), files

    def test_every_configuration_within_the_tolerance_is_compared(self, tmp_path):
        path, files = self._world(tmp_path, "0.24")
        got = dict(epn.traced_pooled_macros(path, files))
        # 0.20 over 0.25 and 0.15 over 0.10; the 75% configuration has no twin.
        assert got["tracedPooledRatios"] == "0.80 and 1.50"
        assert got["tracedPooledWord"] == "two"
        assert got["tracedPooledDriftMaxPct"] == "4"
        assert (got["tracedRedisRtLoPct"], got["tracedRedisRtHiPct"]) == ("1.4", "2.0")
        # The real-time arms over their pooled rates, 0.01 over 0.01 and 0.02 over 0.008,
        # reported whether or not the base arm beside them was admitted.
        assert (got["tracedPooledRtRatioLo"], got["tracedPooledRtRatioHi"]) == ("1.0", "2.5")

    def test_a_configuration_that_drifts_past_the_rule_is_set_aside(self, tmp_path):
        path, files = self._world(tmp_path, "0.40")
        got = dict(epn.traced_pooled_macros(path, files))
        assert got["tracedPooledRatios"] == "1.50" and got["tracedPooledWord"] == "one"
        assert got["tracedPooledDriftMaxPct"] == "38"

    def test_a_missing_file_emits_nothing(self, tmp_path):
        path, files = self._world(tmp_path, "0.24")
        assert epn.traced_pooled_macros(str(tmp_path / "none.csv"), files) == []
        assert epn.traced_pooled_macros(path, ((str(tmp_path / "x.csv"), "E-A9"),)) == []

    def test_the_committed_runs_admit_all_three(self):
        got = dict(epn.traced_pooled_macros())
        # 7 Oct 2026: recounted without the late messages of stale_backlog.py.
        assert got["tracedPooledRatios"] == "0.84, 1.01 and 1.17"
        assert got["tracedPooledWord"] == "three" and got["tracedPooledDriftMaxPct"] == "4"
        assert (got["tracedPooledRtRatioLo"], got["tracedPooledRtRatioHi"]) == ("1.6", "2.0")

    def test_the_kafka_ratios_as_first_computed_are_kept(self):
        got = dict(epn.traced_ratio_macros())
        # 7 Oct 2026: recounted without the late messages of stale_backlog.py.
        assert got["tracedRatios"] == "0.66, 0.80, 1.02" and got["tracedRatioArms"] == "3"


class TestTheListAsASentenceNamesIt:
    @pytest.mark.parametrize("items, want", [
        ([], ""), (["a"], "a"), (["a", "b"], "a and b"), (["a", "b", "c"], "a, b and c")])
    def test_the_join(self, items, want):
        assert epn._and_join(items) == want


def _law_world(root, most_steal=0.0, confirmed=(True, False)):
    judged, after = root / "judged", root / "after"
    judged.mkdir()
    after.mkdir()
    (judged / "p6_a6.json").write_text(json.dumps({"by_part": {
        "x, kafka": {"median_ratio": 2.0}, "x, redis": {"median_ratio": 8.0}}}))
    (judged / "a9.json").write_text(json.dumps({"by_part": {
        "x, kafka": {"median_ratio": 0.1, "a9_2b": {"median_ratio": 1.2,
                                                    "confirmed": confirmed[0]},
                     "loads": {"75": {"a9_1": {"mostly_waiting": 8, "negative_readings": 10,
                                               "holds": False}},
                               "88": {"a9_1": {"mostly_waiting": 19,
                                               "negative_readings": 20, "holds": True}}}},
        "x, redis": {"median_ratio": 0.2, "a9_2b": {"median_ratio": 1.1,
                                                    "confirmed": confirmed[1]},
                     "loads": {"75": {"a9_1": {"mostly_waiting": 9, "negative_readings": 10,
                                               "holds": True}}}}}}))
    for name, value in (("p8_a8_x86", 3.0), ("p8_a8_arm", 4.0)):
        (judged / (name + ".json")).write_text(json.dumps(
            {"by_summary": {"free": {"value": value}}}))
    (after / "a9_summary.json").write_text(json.dumps({"a9": {
        "x, kafka": {"recorded_over_unrecorded": 1.4},
        "y, kafka": {"recorded_over_unrecorded": 1.5},
        "x, redis": {"recorded_over_unrecorded": 3.7},
        "y, redis": {"recorded_over_unrecorded": 4.3}}}))
    (after / "pause_summary.json").write_text(json.dumps(
        {"steal": {"runs_read": 1234, "most_s": most_steal}}))
    (after / "ack_wait_shape.json").write_text(json.dumps({"parts": {
        "x, kafka, 75": {"acks": 1000, "runs": 2}, "x, redis, 75": {"acks": 500, "runs": 1}}}))
    return str(judged), str(after)


class TestTheRegisteredTracePredictions:
    def test_every_quantity_comes_from_its_file(self, tmp_path):
        judged, after = _law_world(tmp_path)
        got = dict(epn.law_reading_macros(judged=judged, after=after))
        assert (got["pSixRatioLo"], got["pSixRatioHi"]) == ("2.00", "8.00")
        assert (got["recTimeWeightedRatioLo"], got["recTimeWeightedRatioHi"]) == ("0.100",
                                                                                  "0.200")
        assert (got["recOwnWaitRatioLo"], got["recOwnWaitRatioHi"]) == ("1.10", "1.20")
        assert (got["recOwnWaitPartsInWord"], got["recOwnWaitPartsWord"]) == ("one", "two")
        assert (got["recMostlyWaitingLo"], got["recMostlyWaitingHi"]) == ("80.0", "95.0")
        assert (got["recMostlyWaitingHoldsWord"], got["recMostlyWaitingPartsWord"]) == (
            "two", "three")
        assert (got["recRaisedLo"], got["recRaisedHi"]) == ("1.40", "4.30")
        assert (got["recRaisedKafkaLo"], got["recRaisedKafkaHi"]) == ("1.40", "1.50")
        assert (got["recRaisedRedisLo"], got["recRaisedRedisHi"]) == ("3.70", "4.30")
        assert (got["pyOverJavaX"], got["pyOverJavaArm"]) == ("3.00", "4.00")
        assert got["stealRunsRead"] == "1{,}234"
        assert got["stealFinding"] == "none"
        assert (got["recWaitAcks"], got["recWaitRuns"], got["recWaitPartsWord"]) == (
            "1{,}500", "3", "two")

    def test_a_run_that_records_steal_changes_the_sentence(self, tmp_path):
        judged, after = _law_world(tmp_path, most_steal=0.25)
        got = dict(epn.law_reading_macros(judged=judged, after=after))
        assert got["stealFinding"] == "at most 0.2~s in any run" or \
            got["stealFinding"] == "at most 0.3~s in any run"
        assert got["stealFinding"] != "none"

    def test_a_missing_file_emits_nothing_rather_than_part_of_a_range(self, tmp_path):
        judged, after = _law_world(tmp_path)
        Path(after, "pause_summary.json").unlink()
        assert epn.law_reading_macros(judged=judged, after=after) == []

    def test_the_committed_verdicts_reproduce_table_s16(self):
        got = dict(epn.law_reading_macros())
        assert (got["pSixRatioLo"], got["pSixRatioHi"]) == ("2.49", "13.08")
        assert (got["recTimeWeightedRatioLo"], got["recTimeWeightedRatioHi"]) == ("0.104",
                                                                                  "0.165")
        assert (got["recOwnWaitRatioLo"], got["recOwnWaitRatioHi"]) == ("1.11", "1.30")
        assert (got["recOwnWaitPartsInWord"], got["recOwnWaitPartsWord"]) == ("four", "six")
        assert (got["recMostlyWaitingLo"], got["recMostlyWaitingHi"]) == ("79.4", "92.0")
        assert (got["recMostlyWaitingHoldsWord"], got["recMostlyWaitingPartsWord"]) == (
            "four", "twelve")
        assert (got["recRaisedKafkaLo"], got["recRaisedKafkaHi"]) == ("1.36", "1.49")
        assert (got["recRaisedRedisLo"], got["recRaisedRedisHi"]) == ("3.69", "4.33")
        assert (got["pyOverJavaX"], got["pyOverJavaArm"]) == ("3.25", "4.25")
        assert got["stealFinding"] == "none"


class TestTheRestOfASliceModel:
    """Equation S3, branch by branch, for a 3 ms slice and a 1 ms tick."""

    @pytest.mark.parametrize("x, want", [
        (-1.0, 1.0), (0.0, 1.0), (0.5, 1.0 - 0.25 / 6.0), (1.0, 1.0 - 1.0 / 6.0),
        (2.0, 0.5), (3.0, 1.0 / 6.0), (3.5, 0.25 / 6.0), (4.0, 0.0), (9.0, 0.0)])
    def test_the_survival_function(self, x, want):
        assert epn.rest_of_slice_g(x, 3.0, 1.0) == pytest.approx(want)

    def test_the_model_ratio_is_emitted_beside_the_measured_one(self):
        got = dict(epn.traced_macros())
        # A 2.8 ms slice (the 0.70 ms constant on eight CPUs) and a 1 ms tick, on the buckets'
        # true edges: 2.048-4.096 ms over 1.024-2.048 ms.
        assert got["tracedModelRatio"] == "1.2"
        assert float(got["tracedModeRatio"]) > float(got["tracedModelRatio"]), \
            "the supplement says the waits gather at the slice more than an even spread"

    def test_without_the_kernel_constants_the_model_ratio_is_omitted(self, monkeypatch):
        import kernel_constants

        def broken():
            raise OSError("no config")
        monkeypatch.setattr(kernel_constants, "constants", broken)
        got = dict(epn.traced_macros())
        assert "tracedModelRatio" not in got and "tracedModeRatio" in got

    def test_an_empty_lower_bucket_gives_no_ratio(self, monkeypatch):
        monkeypatch.setattr(epn, "rest_of_slice_g", lambda x, s, h: 0.0)
        got = dict(epn.traced_macros())
        assert "tracedModelRatio" not in got


RECOUNT = ("run_id", "backend", "n_events", "neg_ack", "neg_send", "neg_output_send", "neg_tti",
           "neg_output", "neg_acklag", "min_ack_us", "min_send_us", "median_ack_us",
           "median_send_us", "median_output_ns", "min_acklag_us")


class TestTheSpreadOverRuns:
    def test_the_spread_is_read_from_the_runs(self, tmp_path):
        p = tmp_path / "recount.csv"
        _csv(p, RECOUNT, [
            ("r1", "kafka", "100", "0", "0", "0", "0", "0", "0", "1", "1", "5", "9", "100", "1"),
            ("r2", "kafka", "100", "10", "0", "0", "0", "0", "0", "-1", "1", "5", "9", "100", "1"),
            ("r3", "redis", "100", "40", "0", "0", "0", "0", "0", "-1", "1", "5", "9", "100", "1")])
        got = dict(epn.span_macros(str(p)))
        assert got["spanRunRateMedianPct"] == "10.0"
        assert got["spanRunRateMaxPct"] == "40"
        assert got["spanRunsNoNegative"] == "1"

    def test_runs_without_messages_carry_no_rate(self, tmp_path):
        p = tmp_path / "recount.csv"
        _csv(p, RECOUNT, [
            ("r1", "kafka", "0", "0", "0", "0", "0", "0", "0", "1", "1", "5", "9", "100", "1")])
        try:
            got = dict(epn.span_macros(str(p)))
        except ZeroDivisionError:
            pytest.fail("a run with no messages must not divide by zero")
        assert "spanRunRateMedianPct" not in got

    def test_the_committed_recount(self):
        got = dict(epn.span_macros())
        # 7 Oct 2026: recounted without the late messages of stale_backlog.py.
        assert got["spanRunsNoNegative"] == "1{,}314"
        assert got["spanRunRateMedianPct"] == "3.6"
        assert got["spanRunRateMaxPct"] == "55"


class TestTheGroupsAndTheirConditions:
    def test_seventy_groups_come_from_fifty_one_conditions(self):
        got = dict(epn._recovery_macros())
        assert got["spanRatioConditions"] == "70"
        assert got["spanRatioBaseConditions"] == "51"


class TestTheManipulationsOnBothBrokers:
    """Table II and the macros beside it, from the committed run-level intervals."""

    def _world(self, root, kafka_priority=("27.4", "7.2")):
        rows = []
        for factor in kafka_priority:
            rows.append(("priority", "E-A5", "l75", "kafka", "normal", "real-time", "0.1",
                         "", "", "0.004", "", "", factor, "4.0", "inf", "True"))
        for factor, rt in (("6.0", "0.017"), ("7.8", "0.0245")):
            rows.append(("priority", "E-A5", "l75", "redis", "normal", "real-time", "0.12",
                         "", "", rt, "", "", factor, "5.0", "9.0", "True"))
        for campaign in ("E-A6", "E-A6b"):
            for broker, factor in (("kafka", "2.07"), ("redis", "0.65")):
                rows.append(("placement", campaign, "k6", broker, "spread", "concentrated", "",
                             "", "", "", "", "", factor, "0.5", "3.6", "True"))
        for campaign in ("E-A10", "E-A10b"):
            for broker, factor in (("kafka", "4.09"), ("redis", "8.0")):
                rows.append(("path", campaign, "", broker, "0", "262144", "", "", "", "", "",
                             "", factor, "3.3", "10.5", "True"))
        for broker in ("kafka", "redis"):
            rows.append(("ladder", "E-A3", "", broker, "knee", "idle", "", "", "", "", "", "",
                         "60.7", "32.8", "215", "True"))
        path = root / "intervals.csv"
        _csv(path, INTERVALS, rows)
        return str(path)

    def test_the_macros_the_documents_quote(self, tmp_path):
        got = dict(epn.mechanism_interval_macros(self._world(tmp_path)))
        assert (got["rtRedisFactorLow"], got["rtRedisFactorHigh"]) == ("6.0", "7.8")
        assert (got["rtRedisResidualMin"], got["rtRedisResidualMax"]) == ("0.0170", "0.0245")
        assert got["placeRedisOrig"] == "0.65" and got["placeKafkaOrigCI"] == "0.50$--$3.60"
        assert got["pathRedisOrig"] == "8.0" and got["pathRedisOrigCI"] == "3.3$--$10.5"
        assert set(got) - {"rtRedisFactorLow", "rtRedisFactorHigh", "rtRedisResidualMin",
                           "rtRedisResidualMax"} == set(epn.MECH_QUOTED)

    def test_an_unbounded_interval_ends_at_infinity(self):
        assert epn._mech_ci({"factor_lo": "4.0", "factor_hi": "inf"}) == "4.00$--$\\infty"

    def test_a_missing_or_doubled_row_stops_the_build(self, tmp_path):
        rows = epn._mech_rows(self._world(tmp_path))
        with pytest.raises(ValueError, match="2 rows"):
            epn._mech_pick(rows + rows, "placement", "E-A6", "kafka")
        with pytest.raises(ValueError, match="0 rows"):
            epn._mech_pick(rows, "placement", "E-A9", "kafka")

    def test_absent_intervals_emit_nothing(self, tmp_path):
        assert epn.mechanism_interval_macros(str(tmp_path / "none.csv")) == []

    def test_the_table_prints_both_brokers_and_a_range_for_priority(self, tmp_path):
        table = epn.render_mechanism_table(self._world(tmp_path))
        assert "$7$--$27$" in table, "a range reaching ten drops its decimals, as the text does"
        assert "$6.0$--$7.8$" in table, "below ten it keeps one"
        assert "$0.65$ [$0.50$--$3.60$]" in table and "$61$ [$33$--$215$]" in table

    def test_the_committed_table_holds_the_reversal(self):
        table = epn.render_mechanism_table()
        # 7 Oct 2026: recounted without the late messages of stale_backlog.py.
        assert "$2.07$ [$1.36$--$3.60$]" in table and "$0.65$ [$0.55$--$0.78$]" in table
        # The priority range reads as the text's \rtFactorLow--\rtFactorHigh does.
        macros = dict(epn.priority_macros())
        assert "$%s$--$%s$" % (macros["rtFactorLow"], macros["rtFactorHigh"]) in table


class TestTheGroupsBehindSectionSix:
    @pytest.mark.parametrize("condition, want", [
        ("kafka_n12_feed1#pass", "K 12 1 p"), ("redis_n5_feed3#fail", "R 5 3 f"),
        ("kafka_n1_feed1", "K 1 1 -"), ("odd_name", "odd\\_name")])
    def test_a_group_is_labelled_by_broker_senders_feeds_and_verdict(self, condition, want):
        assert epn._group_label(condition) == want

    def test_the_table_has_every_group_in_two_halves(self, tmp_path):
        path = tmp_path / "sym.csv"
        _csv(path, ("condition", "n_events", "median_S_us", "median_D_us", "median_A_us",
                    "recovered_medD_us"),
             [("kafka_n1_feed1#pass", "10", "500", "2000", "1500", "2050"),
              ("redis_n1_feed1#fail", "10", "100", "800", "600", "700"),
              ("redis_n2_feed1#pass", "10", "0", "0", "0", "0")])
        table = epn.render_groups_table(str(path))
        assert "K 1 1 p & $2.00$ & $1.50$ & $0.50$ & $75$ & $2$" in table
        assert "R 1 1 f & $0.80$ & $0.60$ & $0.10$ & $75$ & $12$" in table
        assert "R 2 1 p & $0.00$ & $0.00$ & $0.00$ & $0$ & $0$" in table
        assert " & & & & & " in table, "an odd count pads the right half"

    def test_the_committed_groups(self):
        table = epn.render_groups_table()
        assert table.count(" p & ") + table.count(" f & ") == 70


class TestFigureTwosWindow:
    def test_both_sides_of_the_window_are_counted(self):
        got = dict(epn.s_window_macros())
        # 7 Oct 2026: 49,511 above the window as first counted; the late messages, which
        # waited seconds, were most of them.
        assert got == {"sWindowBinUs": "50", "sWindowMs": "5", "sWindowBelow": "558",
                       "sWindowAbove": "19{,}295"}

    def test_without_the_histogram_nothing_is_emitted(self, monkeypatch):
        import make_deletion_histogram

        def gone():
            raise OSError("no histogram")
        monkeypatch.setattr(make_deletion_histogram, "read_hist", gone)
        assert epn.s_window_macros() == []


class TestTheHistogramPrintsAWholeMillisecondAsTheTopOfABucket:
    @pytest.mark.parametrize("printed, whole", [
        (1.0, True), (2.0, True), (507.001, True), (750.003, True), (1145.007, True),
        (0.433, False), (1.5, False), (262.144, False)])
    def test_the_bucket_rule(self, printed, whole):
        assert epn._whole_ms_as_printed(printed) is whole

    def test_the_committed_audit(self):
        got = dict(epn.reach_macros())
        assert got["reachFinerReports"] == "9" and got["reachSubMsReportsWord"] == "two"


class TestTheRateAgainstTheDeliveryInsideAConditions:
    def test_the_quoted_binning_and_the_range(self, tmp_path):
        path = tmp_path / "rbd.csv"
        rows = []
        for b in (4, 8, 12):
            rows += [("c1", "pooled", b, "1", "3", "1", "2.0"),
                     ("c2", "pooled", b, "1", "3", "1" if b == 12 else "0", ""),
                     ("c3", "pooled", b, "0", "1", "0", ""),
                     ("c1", "pass", b, "1", "2", "0", ""), ("c1", "fail", b, "1", "2", "1", "")]
        _csv(path, ("condition", "group", "bins_per_decade", "testable", "bins_used",
                    "significant_rise", "largest_rise_factor"), rows)
        got = dict(epn.rate_by_delivery_macros(str(path)))
        assert (got["rbdUp"], got["rbdTestable"]) == ("1", "2")
        assert (got["rbdPassUp"], got["rbdPassTestable"]) == ("0", "1")
        assert (got["rbdFailUp"], got["rbdFailTestable"]) == ("1", "1")
        assert (got["rbdUpLo"], got["rbdUpHi"]) == ("1", "2")
        assert got["rbdBinsPerDecade"] == "8" and got["rbdMinCount"] == "172"

    def test_absent_table_emits_nothing(self, tmp_path):
        assert epn.rate_by_delivery_macros(str(tmp_path / "none.csv")) == []

    def test_the_committed_table(self):
        got = dict(epn.rate_by_delivery_macros())
        assert (got["rbdUp"], got["rbdTestable"]) == ("24", "56")


class TestTheSliceConstantOfTheKernelThatRan:
    def test_the_backported_constant_gives_a_slice_of_two_point_eight(self):
        got = dict(epn.kernel_macros())
        assert got["sliceConstantMs"] == "0.70" and got["baseSliceMs"] == "2.8"
        assert got["baseSliceNs"] == "2{,}800{,}000"


WORKLOAD = ("run_id", "backend", "feeds", "messages", "duration_s", "publish_rate_hz",
            "bytes_min", "bytes_median", "bytes_max")


class TestTheWorkloadSectionTwoQuotes:
    """7 Oct 2026: the message size and publish rate, from scripts/workload_stats.py."""

    def _world(self, root):
        table = root / "workload.csv"
        _csv(table, WORKLOAD, [("a", "kafka", "5", "10", "10", "0.5", "250", "260", "300"),
                               ("b", "redis", "12", "10", "10", "1.0", "255", "300", "321"),
                               ("c", "kafka", "", "10", "10", "2.0", "260", "270", "280")])
        sweep = root / "sweep.csv"
        _csv(sweep, ("pad_bytes", "rho"), [("0", "0.88"), ("65536", "0.88")])
        return str(table), (str(sweep), str(root / "absent.csv"))

    def test_the_range_the_size_and_the_padding(self, tmp_path):
        table, pads = self._world(tmp_path)
        got = dict(epn.workload_macros(table, pads))
        assert float(got["workloadRateLo"]) < 1.0 < float(got["workloadRateHi"])
        assert "workloadRateMedian" not in got, "the paper quotes the range, not the median"
        assert (got["workloadBytesLo"], got["workloadBytesHi"]) == ("250", "321")
        assert got["workloadFeedsMax"] == "12", "a run whose name carries no count is skipped"
        assert got["workloadPadMaxKB"] == "64"

    def test_without_the_sweeps_the_padding_is_not_claimed(self, tmp_path):
        table, _ = self._world(tmp_path)
        got = dict(epn.workload_macros(table, (str(tmp_path / "none.csv"),)))
        assert "workloadPadMaxKB" not in got and "workloadBytesLo" in got

    def test_a_missing_table_emits_nothing(self, tmp_path):
        assert epn.workload_macros(str(tmp_path / "none.csv")) == []

    def test_the_committed_table(self):
        got = dict(epn.workload_macros())
        assert (got["workloadRateLo"], got["workloadRateHi"]) == ("0.60", "1.03")
        assert (got["workloadBytesLo"], got["workloadBytesHi"]) == ("253", "321")
        assert (got["workloadFeedsMax"], got["workloadPadMaxKB"]) == ("12", "256")
