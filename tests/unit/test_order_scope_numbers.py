"""Freeze 41's numbers (scripts/order_scope_numbers.py): each macro is read through the block's own
judge from a committed run table, so the tests build small tables in the reader's own format and
check what the paper would print."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import order_scope as osc  # noqa: E402
import order_scope_numbers as osn  # noqa: E402


def _write(root, name, rows):
    osc.write_csv(os.path.join(root, name), rows)


def control_rows():
    rows = []
    for backend, a in (("kafka", (1000.0, 1100.0, 1050.0)), ("redis", (700.0, 750.0, 770.0))):
        for delay, a_med in zip((0, 1, 2), a):
            rows.append({"run": "r-%s-%d" % (backend, delay), "setup": "P-%s-d%d" % (backend, delay),
                         "backend": backend, "delay_ms": delay, "Wso_median": 500 + 950 * delay,
                         "D_median": 800 + 960 * delay, "A_median": a_med, "W_median": 500})
    return rows


def ladder_rows():
    rows = []

    def row(setup, rate, backend, load, wso, wso_mean, d_mean, flagged, flag_known, s_neg,
            s_count, wf=None, wu=None):
        rows.append({"run": "r-" + setup, "setup": setup, "rate": rate, "backend": backend,
                     "load_pct": load, "Wso_median": wso, "Wso_mean": wso_mean,
                     "D_mean": d_mean, "Dif_median": 2.5, "flagged": flagged,
                     "flag_known": flag_known, "Wso_flagged_median": wf,
                     "Wso_unflagged_median": wu, "reads": 10, "reads_multi": 1,
                     "S_neg": s_neg, "S_count": s_count})
    row("L50-kafka-l0", 50, "kafka", 0, 880.0, 880.0, 1880.0, 0, 100, 1, 100)
    row("L50-kafka-l88", 50, "kafka", 88, 830.0, 830.0, 3200.0, 0, 100, 15, 100)
    row("L50-redis-l0", 50, "redis", 0, 460.0, 460.0, 700.0, 0, 100, 0, 100)
    row("L50-redis-l88", 50, "redis", 88, 580.0, 580.0, 1300.0, 0, 100, 6, 100)
    row("L500-kafka-l0", 500, "kafka", 0, 740.0, 740.0, 1000.0, 0, 100, 90, 100)
    row("L500-redis-l0", 500, "redis", 0, 470.0, 470.0, 700.0, 0, 100, 10, 100)
    row("L2000-kafka-l0", 2000, "kafka", 0, 1200.0, 1200.0, 1500.0, 99, 100, 4, 100,
        wf=1210.0, wu=770.0)
    row("L2000-redis-l0", 2000, "redis", 0, 950.0, 950.0, 1200.0, 96, 100, 1, 100,
        wf=950.0, wu=550.0)
    return rows


def idle_rows():
    rows = []
    for backend in ("kafka", "redis"):
        for poll, bump in ((False, 4), (True, 6)):
            rows.append({"run": "r-%s-%s" % (backend, poll), "setup": "I-%s" % backend,
                         "backend": backend, "idle_poll": poll, "bump": bump, "S_neg": 100,
                         "dack_median": 60.0, "dack_waited": 9, "timed": 100})
    return rows


class TestSmallHelpers:
    def test_counts_are_spelled_to_twelve_and_digits_after(self):
        assert osn.spell(2) == "two" and osn.spell(12) == "twelve" and osn.spell(13) == "13"

    def test_thousands_take_the_separator_math_mode_keeps(self):
        assert osn.thousands(2000) == "2{,}000" and osn.thousands(500) == "500"
        assert osn.thousands(1234567) == "1{,}234{,}567"


class TestTheMacros:
    def test_no_committed_table_gives_no_macro(self, tmp_path):
        assert osn.order_scope_macros(str(tmp_path)) == []

    def test_the_positive_control(self, tmp_path):
        _write(str(tmp_path), "p_runs.csv", control_rows())
        got = dict(osn.order_scope_macros(str(tmp_path)))
        assert got["osSlopeWLo"] == "0.95" and got["osSlopeWHi"] == "0.95"
        assert got["osSlopeDLo"] == "0.96" and got["osSlopeDHi"] == "0.96"
        # A moved 10% on Kafka (1000 to 1100) and 10% on Redis (700 to 770).
        assert got["osAMoveLoPct"] == "10" and got["osAMoveHiPct"] == "10"

    def test_the_ladder(self, tmp_path):
        _write(str(tmp_path), "l_runs.csv", ladder_rows())
        got = dict(osn.order_scope_macros(str(tmp_path)))
        assert got["osTopRate"] == "2{,}000" and got["osMidRate"] == "500"
        assert got["osLadderAgreeHiUs"] == "2.5"
        assert got["osLadderKafkaMovePct"] == "5.7"
        assert got["osLadderRedisRisePct"] == "26"
        # W_so's mean rose 120 us against D's 600: a fifth.
        assert got["osLadderRedisSharePct"] == "20"
        assert (got["osPullTopLoPct"], got["osPullTopHiPct"]) == ("96.0", "99.0")
        assert (got["osPullExtraLoUs"], got["osPullExtraHiUs"]) == ("400", "440")
        # At 500 a second, one of the two runs has most of its S below zero.
        assert (got["osMidSplitRunsWord"], got["osMidRunsWord"]) == ("one", "two")

    def test_the_idle_boots(self, tmp_path):
        _write(str(tmp_path), "i_runs.csv", idle_rows())
        got = dict(osn.order_scope_macros(str(tmp_path)))
        assert (got["osBumpDefaultPct"], got["osBumpPollPct"]) == ("4.0", "6.0")

    def test_a_setup_value_with_no_reading_is_none(self):
        assert osn._setup_value([{"x": ""}], "x") is None
        assert osn._setup_value([{"x": "3"}, {"x": "5"}], "x") == pytest.approx(4.0)


def order_rows():
    """Block K, nine setups, one run each, with the fields its judge and macros read."""
    rows = []

    def row(setup, backend, load, prio, workers, s_neg, s_order, sk_neg, sk_med, dack99):
        rows.append({"run": "r-" + setup, "setup": setup, "backend": backend, "load_pct": load,
                     "priority": prio, "workers": workers, "timed": 1000, "S_neg": s_neg,
                     "S_neg_Sk_neg": s_order, "Sk_neg": sk_neg, "Sk_median": sk_med,
                     "ack_diff_median": 0.5, "dack_p99": dack99})
    row("K-kafka-l0-ord", "kafka", 0, False, "", 1, 0, 0, 90.0, 200.0)
    row("K-kafka-l88-ord", "kafka", 88, False, "", 100, 1, 0, 80.0, 4000.0)
    row("K-kafka-l88-rt", "kafka", 88, True, "", 30, 2, 5, 70.0, 300.0)
    row("K-redis-l0-ord", "redis", 0, False, "", 40, 38, 900, -20.0, 100.0)
    row("K-redis-l0-rt", "redis", 0, True, "", 50, 50, 950, -50.0, 90.0)
    row("K-redis-l88-ord", "redis", 88, False, "", 130, 120, 100, 10.0, 3000.0)
    row("K-redis-l88-rt", "redis", 88, True, "", 20, 20, 800, -30.0, 80.0)
    row("K-redis-l0-rt-w1", "redis", 0, True, "1", 1, 1, 900, -5.0, 85.0)
    row("K-redis-l88-rt-w1", "redis", 88, True, "1", 2, 1, 500, -5.0, 85.0)
    return rows


def order_bins():
    def b(setup, n, neg, obs, pred):
        return {"setup": setup, "bin": n, "messages": 200, "Sk_median": 50.0 * n,
                "negatives": neg, "observed": obs, "predicted": pred, "pG": 0.5}
    return [b("K-kafka-l88-ord", 1, 30, 0.10, 0.12), b("K-kafka-l88-ord", 2, 25, 0.11, 0.10),
            b("K-redis-l88-ord", 1, 25, 0.05, 0.08), b("K-redis-l88-ord", 2, 5, 0.01, 0.08)]


def parity_rows():
    rows = []
    for backend, (on, off, d_on, d_off) in (("kafka", (100, 110, 4000.0, 4100.0)),
                                            ("redis", (60, 50, 3000.0, 3100.0))):
        for feat, neg, dack in (("RUN_TO_PARITY", on, d_on), ("NO_RUN_TO_PARITY", off, d_off)):
            rows.append({"run": "r-%s-%s" % (backend, feat), "setup": "R-%s" % backend,
                         "backend": backend, "sched_features": feat, "S_neg": neg,
                         "timed": 1000, "dack_p99": dack})
    return rows


class TestBlockK:
    def test_the_order_macros(self, tmp_path):
        _write(str(tmp_path), "k_runs.csv", order_rows())
        _write(str(tmp_path), "k_bins.csv", order_bins())
        got = dict(osn.order_scope_macros(str(tmp_path)))
        assert (got["osKafkaMarginLoUs"], got["osKafkaMarginHiUs"]) == ("70", "90")
        # The judged Kafka setup with the most values below zero: 1 of 100 had S_k < 0.
        assert got["osKafkaLatePct"] == "99.0"
        # Three of the four sixteen-worker Redis runs had the delivery first for most messages.
        assert (got["osRedisFirstRuns"], got["osRedisRuns"]) == ("3", "4")
        assert (got["osRedisLeadLoUs"], got["osRedisLeadHiUs"]) == ("20", "50")
        assert (got["osRedisOrderLoPct"], got["osRedisOrderHiPct"]) == ("92", "100")
        assert (got["osDackLoadKafka"], got["osDackLoadRedis"]) == ("20", "30")
        assert (got["osDackBusyKafkaMs"], got["osDackBusyRedisMs"]) == ("4.0", "3.0")
        # Bins with fewer values below zero than K-d judges are left out of the factor.
        assert (got["osKdFactorKafka"], got["osKdFactorRedis"]) == ("1.20", "1.60")
        assert (got["osGilIdleSixteenPct"], got["osGilIdleOnePct"]) == ("5.0", "0.10")

    def test_a_setup_with_too_few_values_is_its_own_factor_one(self):
        assert osn.fifths_factor(order_bins(), "K-none") == 1.0


class TestTheVerdictTable:
    def test_empty_until_every_block_is_committed(self, tmp_path):
        _write(str(tmp_path), "k_runs.csv", order_rows())
        _write(str(tmp_path), "k_bins.csv", order_bins())
        assert osn.render_order_scope_table(str(tmp_path)) == ""

    def test_one_row_per_prediction_from_the_judges(self, tmp_path):
        root = str(tmp_path)
        _write(root, "k_runs.csv", order_rows())
        _write(root, "k_bins.csv", order_bins())
        _write(root, "r_runs.csv", parity_rows())
        _write(root, "p_runs.csv", control_rows())
        _write(root, "l_runs.csv", ladder_rows())
        _write(root, "i_runs.csv", idle_rows())
        table = osn.render_order_scope_table(root)
        names = [line.split(" & ")[0] for line in table.splitlines()
                 if " & " in line and not line.startswith("&")]
        assert names == ["K-v", "K-a", "K-b", "K-c", "K-d", "K-e", "R-a", "R-b", "P-a",
                         "P-b", "P-c", "L-a", "L-b", "L-c", "I"]
        assert r"$99.0\%$ of $100$" in table and r"\kafka{} within $1.20\times$" in table
        assert r"\kafka{} $1.10\times$" in table and r"\redis{} $0.83\times$" in table
        assert r"50/s \redis{} $+26.1\%$" in table
        assert table.startswith("% Generated") and table.rstrip().endswith(r"\end{tabular}")
