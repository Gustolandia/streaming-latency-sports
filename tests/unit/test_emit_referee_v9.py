"""Tests for the numbers emitted for the referees' reports of 15 October 2026.

Both referees found Section VI's repair numbers computed by an estimator the text does not
describe, from medians floored to a 50 us bin; Table II's priority row a range of point factors
whose intervals it did not show; Table S6 one broker with message-level intervals; the kernel
trace's check made at one threshold for two brokers whose margins differ fivefold; the per-run
rates pooled across brokers; no definition of a matched workload; and Table I without the
smallest value of each span. Each new quantity is tested on a world small enough to work by
hand, and against the committed artefacts the documents read.
"""
import csv
import math
import statistics
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import emit_paper_numbers as epn  # noqa: E402
import stat_intervals  # noqa: E402

REPO = SCRIPTS_DIR.parent

INTERVALS = ("result", "campaign", "level", "backend", "top", "bottom", "top_rate", "top_lo",
             "top_hi", "bottom_rate", "bottom_lo", "bottom_hi", "factor", "factor_lo",
             "factor_hi", "disjoint")


def _csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return str(path)


def _interval(result, campaign, level, backend, factor, lo, hi):
    return (result, campaign, level, backend, "top", "bottom", "0.2", "0.1", "0.3", "0.01",
            "0.0", "0.02", factor, lo, hi, "True")


# --- Table II's priority row and its floor (P2) --------------------------------------------------

class TestThePriorityFloor:

    def _world(self, root):
        rows = [_interval("priority", "E-A5", "l75", "kafka", "39.4", "15.2", "inf"),
                _interval("priority", "E-A5b", "l70", "kafka", "7.2", "4.47", "14.8"),
                _interval("priority", "E-A5", "l88", "kafka", "53.5", "24.6", "451.476"),
                _interval("priority", "E-A5", "l75", "redis", "6.3", "5.0", "8.2"),
                _interval("priority", "E-A7", "l88", "redis", "7.5", "4.26", "10.1")]
        for campaign in ("E-A10", "E-A10b"):
            rows.append(_interval("path", campaign, "", "kafka", "3.8", "3.13", "4.83"))
        for campaign in ("E-A6", "E-A6b"):
            for level in ("k5", "k7"):
                rows.append(_interval("placement", campaign, level, "kafka", "1.2", "0.98",
                                      "1.4"))
        return _csv(root / "intervals.csv", INTERVALS, rows)

    def test_the_floor_is_the_smallest_lower_bound_and_names_its_pair(self, tmp_path):
        got = dict(epn.run_level_macros(self._world(tmp_path)))
        # 16 Oct 2026: 4.47 and 4.26, rounded down.
        assert (got["rtKafkaLowerBound"], got["rtKafkaLowerBoundLoad"],
                got["rtKafkaLowerBoundCampaign"]) == ("4.4", "70", "E-A5b")
        assert (got["rtRedisLowerBound"], got["rtRedisLowerBoundLoad"],
                got["rtRedisLowerBoundCampaign"]) == ("4.2", "88", "E-A7")
        assert (got["rtKafkaUnboundedPairs"], got["rtRedisUnboundedPairs"]) == ("1", "0")

    def test_the_committed_floors_are_the_referees(self):
        got = dict(epn.run_level_macros())
        # 15 Oct 2026: rounded down, as a lower bound must be; the bounds are 4.47 and 4.26,
        # which "%.1f" had printed as 4.5 and 4.3.
        assert (got["rtKafkaLowerBound"], got["rtRedisLowerBound"]) == ("4.4", "4.2")
        assert got["rtKafkaLowerBoundLoad"] == got["rtRedisLowerBoundLoad"] == "70"
        assert got["rtKafkaUnboundedPairs"] == "5"
        twins = dict(epn.spelled_twins(list(got.items())))
        assert twins["rtKafkaUnboundedPairsWord"] == "five"

    def test_a_lower_bound_is_rounded_down_to_its_tenth(self):
        assert [epn.floor_to_tenth(x) for x in (4.47, 4.26, 4.3, 4.5, 15.0)] == \
            ["4.4", "4.2", "4.3", "4.5", "15.0"]

    def test_an_upper_bound_is_rounded_up_to_its_tenth(self):
        assert [epn.ceil_to_tenth(x) for x in (14.7729, 9.99829, 4.3, 451.476)] == \
            ["14.8", "10.0", "4.3", "451.5"]

    def test_an_interval_is_rounded_outward(self):
        row = {"factor_lo": "4.46531", "factor_hi": "14.7729"}
        assert epn._outward_ci(row) == "4.4$--$14.8"
        assert epn._outward_ci(dict(row, factor_hi="inf")) == "4.4$--$\\infty"

    def test_table_two_prints_the_floor_beside_the_range(self):
        table = epn.render_mechanism_table()
        # 16 Oct 2026: the floor rounded down, as the text prints it.
        assert "$7$--$80$ [$\\geq 4.4$]" in table
        assert "$6.0$--$7.8$ [$\\geq 4.2$]" in table

    def test_without_the_intervals_file_nothing_is_emitted(self, tmp_path):
        assert epn.run_level_macros(str(tmp_path / "absent.csv")) == []


class TestTheRunLevelTwins:
    """P9: an interval over whole runs beside each message-level one of S3.1-S3.3."""

    def test_each_twin_is_its_comparisons_interval(self, tmp_path):
        got = dict(epn.run_level_macros(TestThePriorityFloor()._world(tmp_path)))
        assert got["rtLowFactorRunCI"] == "15$--$\\infty"
        assert got["rtHighFactorRunCI"] == "25$--$451"
        assert got["payloadRateFallRunCI"] == "3.1$--$4.8"
        assert got["payloadReplRateFallRunCI"] == "3.13$--$4.83"
        assert got["geomSevenOrigRunCI"] == "0.98$--$1.40"

    def test_the_committed_twins(self):
        got = dict(epn.run_level_macros())
        assert got["rtLowFactorRunCI"] == "15$--$\\infty"
        assert got["rtHighFactorRunCI"] == "25$--$451"
        assert got["payloadRateFallRunCI"] == "3.1$--$4.8"
        assert got["payloadReplRateFallRunCI"] == "3.32$--$5.01"
        # The replication's k = 7 contrast, which S3.2 says "only the replication resolves",
        # does not exclude one when whole runs are resampled.
        lo, hi = (float(v) for v in got["geomSevenReplRunCI"].split("$--$"))
        assert lo < 1.0 < hi

    def test_every_twin_carries_its_own_math(self):
        for name, value in epn.run_level_macros():
            if name.endswith("CI"):
                assert "$" in value, name


# --- Table S6 (P3) ---------------------------------------------------------------------------

class TestTheSupplementsPriorityTable:

    def test_both_brokers_and_every_pairs_interval(self):
        table = epn.render_priority_table()
        body = [ln for ln in table.splitlines() if ln.startswith("E-A")]
        assert len(body) == 8
        assert "\\multicolumn{3}{c}{\\kafka{}}" in table and "\\multicolumn{3}{c}{\\redis{}}" in table
        row = next(ln for ln in body if ln.startswith("E-A5b & $70\\%$"))
        # 16 Oct 2026: each interval rounded outward, so its lower end is the text's floor.
        assert "$7.2$ [$4.4$--$14.8$]" in row and "$6.0$ [$4.2$--$9.2$]" in row
        assert sum(ln.count("\\infty") for ln in body) == 5

    def test_its_cells_range_covers_both_brokers(self):
        got = dict(epn.cell_events_macros())
        counts = epn._configuration_events(results=("priority",))
        assert {b for (_c, _cell, b) in counts} == {"kafka", "redis"}
        assert got["prioEventsLo"] == epn.latex_thousands(min(counts.values()))
        assert (got["prioEventsLo"], got["prioEventsHi"]) == ("2{,}822", "2{,}985")

    def test_table_twos_count_leaves_out_the_cells_it_is_not_built_from(self):
        """E-A3's whole ladder and the placement cells at k = 5 and 7 joined the run file on
        15 Oct 2026; Table II's caption counts its own configurations, which did not change."""
        every = epn._configuration_events(results=("priority", "placement", "path", "ladder",
                                                   "load"))
        own = epn._configuration_events()
        assert ("E-A3", "bg5", "kafka") in every and ("E-A3", "bg5", "kafka") not in own
        assert ("E-A6", "k5_conc", "kafka") in every and ("E-A6", "k5_conc", "kafka") not in own
        got = dict(epn.cell_events_macros())
        assert (got["mechEventsLo"], got["mechEventsHi"]) == ("2{,}408", "2{,}985")


# --- the trace check's threshold and each broker's margin (P4) ----------------------------------

class TestTheTraceThresholds:

    @pytest.mark.parametrize("margin, edges", [(103.4, (64, 128)), (250.0, (128, 256)),
                                               (512.0, (512, 1024))])
    def test_the_log2_edges_around_a_margin(self, margin, edges):
        assert epn._log2_edges(margin) == edges

    def test_at_half_a_millisecond_the_pooled_ratios_are_the_papers(self):
        rows, margin = epn.trace_threshold_rows()
        assert margin == {"kafka": 0.5239, "redis": 0.1034}
        at = sorted(round(dict(r["pooled"])[500], 2) for r in rows)
        printed = sorted(float(v) for v in dict(epn.traced_pooled_macros())[
            "tracedPooledRatios"].replace(" and", ",").split(", "))
        assert at == printed == [0.84, 1.01, 1.17]

    def test_the_quarter_millisecond_reads_the_bucket_edge_above_it(self):
        import analyze_runq_tail as art
        parsed = art.parse_bpftrace(str(REPO / epn.TRACE_HISTOGRAMS[0][2]))
        rows, _ = epn.trace_threshold_rows()
        share = sum(c for lo, _hi, c in parsed["hist"] if lo >= 256) / parsed["total"]
        assert dict(rows[0]["pooled"])[250] == pytest.approx(share / rows[0]["rate"]["both"])

    def test_the_macros(self):
        got = dict(epn.trace_threshold_macros())
        assert (got["tracedThresholdLowMs"], got["tracedThresholdHighMs"]) == ("0.25", "2")
        assert (got["tracedThresholdRatioLo"], got["tracedThresholdRatioHi"]) == ("0.63", "1.61")
        assert (got["tracedKafkaMarginMs"], got["tracedRedisMarginMs"]) == ("0.52", "0.10")
        assert (got["tracedKafkaMarginRatioLo"], got["tracedKafkaMarginRatioHi"]) == (
            "0.66", "1.02")
        assert (got["tracedRedisMarginRatioLo"], got["tracedRedisMarginRatioHi"]) == (
            "2.3", "3.3")

    def test_without_the_margins_nothing_is_emitted(self, monkeypatch, tmp_path):
        monkeypatch.setattr(epn, "MARGINS_CSV", str(tmp_path / "absent.csv"))
        assert epn.trace_threshold_macros() == []

    def test_the_table(self):
        table = epn.render_trace_threshold_table()
        for row in ("$\\Pr[\\text{wait} \\geq 0.256\\,\\text{ms}]^{a}$ & $1.27$ & $1.61$ & $1.33$",
                    "$\\Pr[\\text{wait} > 0.5\\,\\text{ms}]$ & $0.84$ & $1.17$ & $1.01$",
                    "$\\Pr[\\text{wait} > 2\\,\\text{ms}]$ & $0.63$ & $0.86$ & $0.78$",
                    "\\kafka{}, $m = 0.52$~ms: $\\Pr[\\text{wait} > 0.5\\,\\text{ms}]$ & $0.66$ & "
                    "$1.02$ & $0.80$"):
            assert row in table, row
        assert "$2.5$--$3.2$ & $2.5$--$3.3$ & $2.3$--$3.0$" in table
        assert "$^{a}$" in table and "$^{b}$" in table


# --- the per-run rates by broker (P5) ------------------------------------------------------------

SPAN = ["run_id", "condition", "gate", "n_events", "neg_ack", "ms_deleted", "over_0.1",
        "over_0.25", "over_0.5", "over_1"]


class TestTheRunRates:

    def test_the_committed_runs(self):
        got = dict(epn.run_rate_macros())
        assert (got["spanKafkaRunRateMedianPct"], got["spanRedisRunRateMedianPct"]) == (
            "2.1", "5.9")
        assert got["spanConditions"] == "74"
        assert (got["spanCondRateLoPct"], got["spanCondRateMedianPct"],
                got["spanCondRateHiPct"]) == ("0.8", "1.8", "11.3")

    def test_a_condition_pools_its_runs_and_a_run_without_messages_has_no_rate(self, tmp_path):
        rows = [("r%d" % i, "kafka_n1_feed%d" % (i % 5), "pass", 100, i, 0, 0, 0, 0, 0)
                for i in range(10)]
        rows.append(("rz", "redis_n1_feed1", "pass", 0, 0, 0, 0, 0, 0, 0))
        got = dict(epn.run_rate_macros(_csv(tmp_path / "s.csv", SPAN, rows)))
        assert got["spanConditions"] == "5", "the condition with no messages has no rate"
        assert got["spanKafkaRunRateMedianPct"] == "4.5"
        assert "spanRedisRunRateMedianPct" not in got
        assert "spanRedisCondRateLoPct" not in got, "under four conditions, no quartiles"

    def test_a_missing_file_emits_nothing(self, tmp_path):
        assert epn.run_rate_macros(str(tmp_path / "absent.csv")) == []

    def test_too_few_conditions_have_no_quartiles(self, tmp_path):
        rows = [("r1", "kafka_n1_feed1", "pass", 10, 1, 0, 0, 0, 0, 0)]
        got = dict(epn.run_rate_macros(_csv(tmp_path / "s.csv", SPAN, rows)))
        assert got == {"spanKafkaRunRateMedianPct": "10.0"}


# --- the matched workloads of the gap distortion (P10) -----------------------------------------

class TestTheMatchedWorkloads:

    def test_a_workload_is_matched_by_senders_feeds_and_verdict(self, tmp_path):
        path = _csv(tmp_path / "s.csv", ("condition", "median_S_us", "median_D_us"), [
            ("kafka_n1_feed1#pass", 500, 2000), ("redis_n1_feed1#pass", 100, 800),
            ("kafka_n1_feed1#fail", 600, 2100), ("redis_n2_feed1#fail", 120, 900),
            ("redis_n1_feed1#fail", 0, 700)])
        pairs = epn.gap_pairs(path)
        assert [(p["senders"], p["feeds"], p["verdict"]) for p in pairs] == [("1", "1", "pass")]
        p = pairs[0]
        assert (p["gap_D"], p["gap_S"]) == (2.5, 5.0) and p["distortion"] == 2.0

    def test_without_both_brokers_or_the_file_there_are_no_pairs(self, tmp_path):
        assert epn.gap_pairs(str(tmp_path / "absent.csv")) is None
        path = _csv(tmp_path / "s.csv", ("condition", "median_S_us", "median_D_us"),
                    [("kafka_n1_feed1#pass", 500, 2000)])
        assert epn.gap_pairs(path) is None

    def test_the_committed_table_lists_the_pairs_the_paper_counts(self):
        pairs = epn.gap_pairs()
        assert len(pairs) == int(dict(epn.paired_gap_macros())["gapDistortionPairs"]) == 24
        for p in pairs:
            assert p["distortion"] == pytest.approx(p["gap_S"] / p["gap_D"])
        table = epn.render_gap_table()
        assert len([ln for ln in table.splitlines() if ln.startswith("$")]) == 24
        assert "Senders & Feeds & Check" in table


# --- Table I's smallest values (T1) --------------------------------------------------------------

class TestTheSmallestValues:

    @pytest.mark.parametrize("us, want", [(-99785.6, "-99{,}786"), (229.8, "230"),
                                          (1036.5, "1{,}036")])
    def test_the_signed_whole_microseconds(self, us, want):
        assert epn._signed_thousands(us) == want

    def test_the_committed_recount(self):
        got = dict(epn.span_macros())
        assert (got["spanAckMinUs"], got["spanOutputSendMinUs"], got["spanTtiMinUs"]) == (
            "-99{,}786", "230", "467")
        assert (got["spanSendFloorUs"], got["spanAckLagFloorUs"]) == ("220", "112")

    def test_a_recount_without_the_columns_gives_no_value(self):
        assert epn.span_floor_macros([{"min_ack_us": ""}]) == []

    def test_the_generated_table_names_the_ledgers_macros(self):
        table = epn.render_spans_table()
        for name in ("spanAckMinUs", "spanSendFloorUs", "spanOutputSendMinUs",
                     "spanAckLagFloorUs", "spanTtiMinUs", "spanKafkaNegAckPct"):
            assert "\\" + name in table, name
        # The revised draft's narrow layout, the same day: the compsoc column is narrower.
        assert "Span & From & \\kafka{} & \\redis{} & All & Least, $\\mu$s \\\\" in table
        assert "\\setlength{\\tabcolsep}{4pt}" in table
        assert "$E$ & $t_{\\mathrm{sched}}$ & " in table
        assert table.count("\\midrule") == 3


# --- the recovery and the understatement, by broker (P1) -----------------------------------------

class TestTheRepairByBroker:

    def test_the_committed_errors_by_broker(self):
        got = dict(epn.disease_macros())
        pops = stat_intervals.recovery_populations(split="broker")
        for name in ("Kafka", "Redis"):
            assert got["recoveryErr" + name] == "%.1f" % statistics.median(pops[name])
            assert got["recovery%sN" % name] == str(len(pops[name]))
        assert (got["recoveryErrKafka"], got["recoveryErrRedis"]) == ("0.4", "14.6")
        assert (got["recoveryErrKafkaHi"], got["recoveryKafkaMax"]) == ("1.3", "5.1")

    def test_the_verdicts_read_the_median_only_recovery(self):
        got = dict(epn.disease_macros())
        assert (got["recoveryErrPass"], got["recoveryErrFail"]) == ("3.0", "12.7")
        assert (got["recoveryErrPassHi"], got["recoveryErrFailHi"]) == ("13", "19")

    def test_groups_named_for_no_broker_give_no_broker_macros(self, tmp_path):
        path = _csv(tmp_path / "s.csv", ("condition", "recovery_err_us", "median_D_us",
                                         "rho_DA", "median_A_us", "median_S_us"),
                    [("p%d#pass" % i, 10 * i, 1000, 0.5, 10, 900) for i in range(4)]
                    + [("f%d#fail" % i, 10 * i, 1000, 0.5, 10, 900) for i in range(4)])
        got = dict(epn._recovery_macros(path))
        assert not [k for k in got if "Kafka" in k or "Redis" in k]

    def test_the_understatement_by_broker(self):
        got = dict(epn.disease_macros())
        rows = list(csv.DictReader(open(REPO / "docs" / "results" / "span_symmetry.csv",
                                        encoding="utf-8")))
        for broker in ("kafka", "redis"):
            frac = sorted(float(r["median_S_us"]) / float(r["median_D_us"]) for r in rows
                          if r["condition"].startswith(broker + "_"))
            key = "understate" + broker.capitalize()
            assert got[key + "Factor"] == "%.1f" % (1.0 / statistics.median(frac))
            assert got[key + "Worst"] == "%.1f" % (1.0 / frac[0])
            assert got[key + "Least"] == "%.1f" % (1.0 / frac[-1])
        assert (got["understateKafkaFactor"], got["understateRedisFactor"]) == ("3.8", "6.6")

    def test_a_broker_with_too_few_groups_has_no_understatement(self, tmp_path):
        rows = [("kafka_n%d_feed1#pass" % i, 0, 2000, 0.5, 1500, 500 + i) for i in range(4)]
        rows.append(("redis_n1_feed1#pass", 0, 800, 0.5, 500, 100))
        path = _csv(tmp_path / "s.csv", ("condition", "recovery_err_us", "median_D_us",
                                         "rho_DA", "median_A_us", "median_S_us"), rows)
        got = dict(epn._recovery_macros(path))
        assert "understateKafkaFactor" in got and "understateRedisFactor" not in got


class TestTheThirdsReadTheGridEstimator:
    """At native resolution no group recovers exactly, so the postmortem's S16.9 sentence on
    thirds is read from the estimator it was written against, from the columns that keep it.

    Later on 15 Oct 2026 S16.9 was rewritten to the native-resolution reading, and that bridge
    went: no thirds macro is emitted from either estimator. The grid is read now for what the
    rewritten section says of it, under names of its own: how many groups of each verdict it
    printed as exact, its step, and the largest of those groups' errors at native resolution,
    emitted only while every one of them is a Kafka group's."""

    COLS = ("condition", "recovery_err_us", "median_D_us", "rho_DA", "median_A_us",
            "median_S_us", "recovery_err_centre_us", "median_D_bin_us", "bin_width_us")

    def _grid(self, tmp_path, rows):
        return dict(epn._recovery_macros(_csv(tmp_path / "s.csv", self.COLS, rows)))

    def test_the_committed_thirds_are_the_grid_estimators(self):
        """Was: the committed thirds, 16.7 to 19.2, from the grid's columns. Now: the grid's
        exact recoveries, recounted here from the committed file."""
        got = dict(epn.disease_macros())
        assert not [k for k in got if "Thirds" in k]
        assert got["recoveryPassExact"] == "0", "the corrected recovery has no exact groups"
        rows = list(csv.DictReader(open(REPO / "docs" / "results" / "span_symmetry.csv",
                                        encoding="utf-8")))
        exact = [r for r in rows if float(r["recovery_err_centre_us"]) == 0.0]
        assert exact and all(r["condition"].startswith("kafka_") for r in exact)
        assert got["recoveryGridPassExactN"] == str(
            sum(r["condition"].endswith("#pass") for r in exact)) == "14"
        assert got["recoveryGridFailExactN"] == str(
            sum(r["condition"].endswith("#fail") for r in exact)) == "6"
        assert got["recoveryGridExactMaxUs"] == "%.0f" % max(
            abs(float(r["recovery_err_us"])) for r in exact) == "39"
        assert got["recoveryGridStepUs"] == "50"
        assert float(got["recoveryGridExactMaxUs"]) < float(got["recoveryGridStepUs"])

    def test_a_redis_group_the_grid_printed_as_exact_withdraws_the_sentence(self, tmp_path):
        """'Every one of them was Kafka's' is the sentence; one Redis group at zero voids it."""
        rows = [("kafka_n1_feed1#pass", 5, 1000, 0.5, 10, 900, 0, 1000, 50),
                ("redis_n1_feed1#fail", 7, 1000, 0.5, 10, 900, 0, 1000, 50)]
        assert not [k for k in self._grid(tmp_path, rows) if k.startswith("recoveryGrid")]

    def test_two_grids_withdraw_the_step(self, tmp_path):
        rows = [("kafka_n1_feed1#pass", 5, 1000, 0.5, 10, 900, 0, 1000, 50),
                ("kafka_n2_feed1#fail", 7, 1000, 0.5, 10, 900, 50, 1000, 100)]
        assert not [k for k in self._grid(tmp_path, rows) if k.startswith("recoveryGrid")]

    def test_a_grid_that_printed_nothing_exact_emits_nothing(self, tmp_path):
        rows = [("kafka_n1_feed1#pass", 5, 1000, 0.5, 10, 900, 50, 1000, 50),
                ("redis_n1_feed1#fail", 7, 1000, 0.5, 10, 900, -50, 1000, 50)]
        assert not [k for k in self._grid(tmp_path, rows) if k.startswith("recoveryGrid")]

    def test_a_group_with_no_grid_delivery_is_skipped(self, tmp_path):
        """A zero median of D on the grid is no denominator, as `recovery_populations` has it;
        its zero error is not an exact recovery."""
        rows = [("kafka_n1_feed1#pass", 5, 1000, 0.5, 10, 900, 0, 1000, 50),
                ("redis_n1_feed1#fail", 7, 1000, 0.5, 10, 900, 0, 0, 50)]
        got = self._grid(tmp_path, rows)
        assert (got["recoveryGridPassExactN"], got["recoveryGridFailExactN"]) == ("1", "0")
        assert got["recoveryGridExactMaxUs"] == "5"

    def test_a_file_without_the_grid_columns_emits_nothing_of_it(self, tmp_path):
        rows = [("kafka_n1_feed1#pass", 5, 1000, 0.5, 10, 900),
                ("kafka_n2_feed1#fail", 7, 1000, 0.5, 10, 900)]
        got = dict(epn._recovery_macros(_csv(tmp_path / "s.csv", self.COLS[:6], rows)))
        assert "recoveryPassN" in got
        assert not [k for k in got if k.startswith("recoveryGrid")]


class TestTheVerdictsInsideEachBroker:
    """15 Oct 2026, the postmortem's S16.9 rewritten. Pooled, the verdicts' shift excludes zero
    because the verdicts mix the brokers unevenly; inside each broker it does not. Each broker's
    shift is the pooled one's statistic, computed the same way -- the median of every pairwise
    difference, rejected minus accepted, with `hl_bootstrap_ci`'s resamples and seed -- with its
    TOST margin and its Kolmogorov-Smirnov test beside it."""

    def test_the_committed_shifts(self):
        got = dict(epn.disease_macros())
        assert (got["recoveryKafkaShift"], got["recoveryKafkaShiftCI"]) == (
            "0.16", "-0.17$ to $0.44")
        assert (got["recoveryRedisShift"], got["recoveryRedisShiftCI"]) == ("1.4", "-6.5$ to $6.5")
        assert (got["recoveryKafkaEquivMargin"], got["recoveryRedisEquivMargin"]) == ("0.39", "5.9")
        assert (got["recoveryKafkaKsD"], got["recoveryKafkaKsP"]) == ("0.42", "0.22")
        assert (got["recoveryRedisKsD"], got["recoveryRedisKsP"]) == ("0.26", "0.44")
        assert got["recoveryKsPerms"] == "20{,}000"
        assert (got["recoveryShift"], got["recoveryShiftCI"]) == ("3.7", "0.2$ to $11.3")

    def test_each_broker_s_shift_is_the_pooled_statistic(self):
        """Mirrors `recoveryShift`: the same estimator and the same bootstrap, inside a broker."""
        got = dict(epn.disease_macros())
        cells = stat_intervals.recovery_populations(split="both")
        for broker in ("Kafka", "Redis"):
            a, b = cells[broker + "Pass"], cells[broker + "Fail"]
            digits = 2 if broker == "Kafka" else 1
            lo, hi = stat_intervals.hl_bootstrap_ci(a, b)
            assert got["recovery%sShift" % broker] == "%.*f" % (
                digits, stat_intervals.hodges_lehmann(a, b))
            assert got["recovery%sShiftCI" % broker] == "%.*f$ to $%.*f" % (digits, lo, digits, hi)
            mlo, mhi = stat_intervals.hl_bootstrap_ci(a, b, conf=0.90)
            assert got["recovery%sEquivMargin" % broker] == "%.*f" % (
                digits, max(abs(mlo), abs(mhi)))
            assert got["recovery%sKsD" % broker] == "%.2f" % stat_intervals.ks_two_sample(a, b)

    def test_the_cells_are_printed_by_the_broker_rules(self):
        got = dict(epn.disease_macros())
        for name in ("KafkaPass", "KafkaFail", "RedisPass", "RedisFail"):
            v = stat_intervals.recovery_populations(split="both")[name]
            assert got["recoveryErr" + name] == "%.1f" % statistics.median(v)
            assert got["recovery%sMax" % name] == epn._exposure_pct(max(v))
            assert got["recovery%sN" % name] == str(len(v))
        assert (got["recoveryErrKafkaFailHi"], got["recoveryKafkaFailMax"]) == ("0.7", "1.3")
        assert (got["recoveryErrRedisPassHi"], got["recoveryErrRedisFailHi"]) == ("19", "20")

    COLS = ("condition", "recovery_err_us", "median_D_us", "rho_DA", "median_A_us",
            "median_S_us")

    def test_one_decimal_once_the_interval_reaches_a_point(self, tmp_path):
        rows = ([("kafka_n%d_feed1#pass" % i, e, 1000, 0.5, 10, 900)
                 for i, e in enumerate((10, 20, 30, 40))]
                + [("kafka_n%d_feed2#fail" % i, e, 1000, 0.5, 10, 900)
                   for i, e in enumerate((15, 35, 55, 75))])
        got = dict(epn._recovery_macros(_csv(tmp_path / "s.csv", self.COLS, rows)))
        assert got["recoveryKafkaShift"] == "2.0"
        assert got["recoveryKafkaShiftCI"].count(".") == 2
        assert all(len(v.split(".")[1]) == 1 for v in got["recoveryKafkaShiftCI"].split("$ to $"))

    def test_a_shift_a_hair_below_zero_prints_without_a_minus(self, tmp_path):
        """One group a side, a thousandth of a point apart: the shift rounds to zero at two
        decimals and must print 0.00, not -0.00."""
        rows = [("kafka_n1_feed1#pass", 10.01, 1000, 0.5, 10, 900),
                ("kafka_n2_feed1#fail", 10.0, 1000, 0.5, 10, 900)]
        got = dict(epn._recovery_macros(_csv(tmp_path / "s.csv", self.COLS, rows)))
        assert got["recoveryKafkaShift"] == "0.00"
        assert got["recoveryKafkaShiftCI"] == "0.00$ to $0.00"

    def test_a_broker_with_one_verdict_has_no_shift(self, tmp_path):
        rows = ([("kafka_n%d_feed1#pass" % i, 10 * i, 1000, 0.5, 10, 900) for i in range(3)]
                + [("redis_n%d_feed1#pass" % i, 10 * i, 1000, 0.5, 10, 900) for i in range(3)]
                + [("redis_n%d_feed2#fail" % i, 15 * i, 1000, 0.5, 10, 900) for i in range(3)])
        got = dict(epn._recovery_macros(_csv(tmp_path / "s.csv", self.COLS, rows)))
        assert "recoveryRedisShift" in got and "recoveryKsPerms" in got
        assert not [k for k in got if k.startswith("recoveryKafka") and "Shift" in k]
        assert "recoveryKafkaFailN" not in got

    def test_no_broker_with_both_verdicts_emits_no_test(self, tmp_path):
        rows = ([("kafka_n%d_feed1#pass" % i, 10 * i, 1000, 0.5, 10, 900) for i in range(3)]
                + [("redis_n%d_feed2#fail" % i, 15 * i, 1000, 0.5, 10, 900) for i in range(3)])
        got = dict(epn._recovery_macros(_csv(tmp_path / "s.csv", self.COLS, rows)))
        assert not [k for k in got if "Shift" in k and ("Kafka" in k or "Redis" in k)]
        assert "recoveryKsPerms" not in got
        assert "recoveryShift" in got, "the pooled shift needs only the two verdicts"


class TestTheExposureRounding:

    @pytest.mark.parametrize("pct, want", [(6.5, "6.5"), (6.84, "6.8"), (65.0, "65"),
                                           (0.725, "0.7"), (19.06, "19")])
    def test_two_figures_below_ten(self, pct, want):
        assert epn._exposure_pct(pct) == want

    def test_the_committed_exposure(self):
        got = dict(epn.exposure_macros())
        assert (got["exposureErrOne"], got["exposureErrTen"]) == ("68", "6.8")
        assert got["exposureCrossover"] == "0.68"
        lag = dict(epn.disease_macros())["ackLagMedianUs"]
        assert lag == "684" and not math.isclose(float(lag), 650.0)


class TestFigureTwoPanelBsRunCount:
    """Fig. 2(b) draws the runs of the load and priority campaigns, not every cloud run, and its
    caption counts them through the helper that hands the figure its runs."""

    def test_the_count_is_the_runs_the_panel_draws(self):
        import manipulation_runs
        runs = manipulation_runs.rate_by_load()
        assert dict(epn.s_rate_macros()) == {"sRateRuns": epn.latex_thousands(len(runs))}
        # E-A3's nine cells and the eight matched pairs' sixteen arms, 25 runs each, on both
        # brokers.
        assert epn.s_rate_macros() == [("sRateRuns", "1{,}250")]

    def test_the_caption_reads_the_count(self):
        paper = (REPO / "paper.tex").read_text(encoding="utf-8")
        start = paper.index("\\label{fig:twoways}")
        # Either form of the caption: \caption{...} or \caption[short]{...}.
        caption = paper[max(paper.rfind("\\caption{", 0, start),
                            paper.rfind("\\caption[", 0, start)):start]
        assert "\\sRateRuns" in caption
        assert "\\newcommand{\\sRateRuns}{1{,}250}" in (
            REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")

    @pytest.mark.parametrize("error", [OSError, KeyError, ImportError])
    def test_without_the_runs_nothing_is_emitted(self, monkeypatch, error):
        import manipulation_runs

        def gone(*_a, **_k):
            raise error("no runs")
        monkeypatch.setattr(manipulation_runs, "rate_by_load", gone)
        assert epn.s_rate_macros() == []
