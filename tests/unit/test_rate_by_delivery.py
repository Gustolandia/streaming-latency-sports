"""Tests for scripts/rate_by_delivery.py: 100% branch coverage.

The script has two halves, and so do the tests.

`extract` is run on a small run tree laid out like the real one. Each run folder holds the same
files as a real run folder, and producer.csv and consumer.csv carry the same columns. The tree
also holds a run with no producer.csv, as 41 real runs have none; a run with an empty half; a
run id from outside the campaign; and the campaign's run lists beside the folders. Its table is
checked by hand, and against the span_by_condition.json that span_by_condition.py's own scan
writes for the same runs packed into an archive.

`analyze` is run on a made-up counts table whose every verdict can be checked by hand.

The committed counts table is held to the committed span_by_condition.json, and the committed
results to the committed counts table.
"""
import csv
import json
import math
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import rate_by_delivery as rbd  # noqa: E402
import span_by_condition as sbc  # noqa: E402
from stat_intervals import wilson  # noqa: E402

REPO = SCRIPTS_DIR.parent
SPAN_JSON = REPO / "docs" / "results" / "span_by_condition.json"
COUNTS_CSV = REPO / "docs" / "results" / "model" / "rate_by_delivery_counts.csv"
RESULTS_CSV = REPO / "docs" / "results" / "model" / "rate_by_delivery.csv"


@pytest.fixture(autouse=True)
def fresh_ratio_hist():
    """span_by_condition's pooled ratio histogram is module state; each test starts it empty."""
    sbc.RATIO_HIST.clear()
    yield
    sbc.RATIO_HIST.clear()


# ------------------------------------------------------------ a run tree shaped like the real one

#: The columns of a real run's files (runs/concurrency_n12_20260723_050408_kafka_feed10_rep1).
PRODUCER_COLUMNS = ["run_id", "backend", "topic", "event_id", "match_id", "t_sim_seconds",
                    "t_emit_offset_s", "t_prod_sched_ns", "t_prod_send_ns", "t_broker_ack_ns"]
CONSUMER_COLUMNS = ["run_id", "backend", "topic", "event_id", "match_id", "t_sim_seconds",
                    "t_cons_recv_ns", "t_output_ns"]
EVENTS_COLUMNS = ["run_id", "backend", "topic", "partition", "offset", "t_consume_ns",
                  "event_id", "match_id", "t_sim_seconds", "t_emit_offset_s",
                  "t_emit_planned_ns", "s3_uid", "s3_rev", "s3_is_correction"]

CAMPAIGN = "concurrency_n2_20260101_000000"
PASS_RUN = CAMPAIGN + "_kafka_feed1_rep1"
FAIL_RUN = CAMPAIGN + "_kafka_feed1_rep2"
T0 = 1_784_783_055_883_100_746        # a stamp of the campaign's era, ns since the epoch
MS = 1_000_000

#: (D, A) per message, in ns. None of the pass run's spans is negative; the last is exactly
#: zero, which is not negative and sits in the first bin of span_by_condition.json's histogram
#: of S that is not below zero. One of the fail run's three is negative, which fails the gate's
#: 1% rule. Its other two sit either side of the 1 ms edge: 999,999 ns is in bin 71 and
#: exactly 1 ms opens bin 72.
PASS_MESSAGES = [(1500 * 1000, 900 * 1000), (1500 * 1000, 1000 * 1000),
                 (2500 * 1000, 1200 * 1000), (1500 * 1000, 1500 * 1000)]
FAIL_MESSAGES = [(MS, 400 * 1000), (2500 * 1000, 2600 * 1000), (MS - 1, 200 * 1000)]
#: The table those two runs must give. d_bin = floor(24 log10(D / 1 us)): 1.5 ms is in bin 76,
#: 2.5 ms in bin 81.
EXPECTED_ROWS = [
    ["condition", "gate", "d_bin", "events", "negatives"],
    ["kafka_n2_feed1", "fail", "71", "1", "0"],
    ["kafka_n2_feed1", "fail", "72", "1", "0"],
    ["kafka_n2_feed1", "fail", "81", "1", "1"],
    ["kafka_n2_feed1", "pass", "76", "3", "0"],
    ["kafka_n2_feed1", "pass", "81", "1", "0"],
]


def _write_csv(path, columns, rows, newline="\n"):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator=newline)
        w.writerow(columns)
        w.writerows(rows)


def make_run(runs, run_id, messages, producer=True, empty_producer=False, blank_output=None):
    """One run folder, with every file a real one has and the real columns.

    blank_output names a message whose consumer row loses its t_output_ns."""
    folder = runs / run_id
    folder.mkdir(parents=True)
    backend = "kafka" if "_kafka_" in run_id else "redis"
    topic = "sb-events-" + run_id.split("_", 4)[-1].replace("_", "-")
    prod, cons, events = [], [], []
    for i, (d_ns, a_ns) in enumerate(messages):
        eid = "7f498384-e379-41b8-bdd2-%012d" % i
        sched = T0 + i * 250 * MS
        send = sched + 328_532
        recv = send + d_ns
        output = "" if i == blank_output else recv + 510
        prod.append([run_id, backend, topic, eid, 3895134, i, float(i), sched, send, send + a_ns])
        cons.append([run_id, backend, topic, eid, 3895134, i, recv, output])
        events.append([run_id, backend, topic, 0, 8 + i, recv, eid, 3895134, i, float(i), sched,
                       "3895134:" + eid, 1, False])
    if producer:
        _write_csv(folder / "producer.csv", PRODUCER_COLUMNS, [] if empty_producer else prod)
    _write_csv(folder / "consumer.csv", CONSUMER_COLUMNS, cons)
    _write_csv(folder / "consumer_events.csv", EVENTS_COLUMNS, events, newline="\r\n")
    (folder / "producer.log").write_text(
        "OK %s producer: wrote %d rows -> runs/%s/producer.csv\n" % (backend, len(prod), run_id))
    (folder / "consumer.log").write_text(
        "OK %s consumer: wrote %d rows -> runs/%s/consumer.csv\n" % (backend, len(cons), run_id))
    (folder / "meta.json").write_text(json.dumps({"run_id": run_id, "backend": backend,
                                                  "topic": topic, "speedup": 120.0}))
    if producer:
        (folder / "tti_summary.json").write_text(json.dumps({"n_matched": len(messages)}))
        (folder / "tti_summary.printed.json").write_text("Computed TTI metrics\n")


def make_tree(tmp_path, extra=()):
    """The runs folder: two counted runs and every kind of folder the scan must pass over."""
    runs = tmp_path / "extracted" / "runs"
    runs.mkdir(parents=True)
    make_run(runs, PASS_RUN, PASS_MESSAGES)
    make_run(runs, FAIL_RUN, FAIL_MESSAGES)
    make_run(runs, CAMPAIGN + "_kafka_feed11_rep1", PASS_MESSAGES, producer=False)
    make_run(runs, CAMPAIGN + "_redis_feed1_rep1", PASS_MESSAGES, empty_producer=True)
    make_run(runs, "mechanism_ea9_rep1", FAIL_MESSAGES)
    for run_id, messages, options in extra:
        make_run(runs, run_id, messages, **options)
    (runs / ("_concurrency_" + CAMPAIGN + "_runs.txt")).write_text(
        "runs/%s\nruns/%s\n" % (PASS_RUN, FAIL_RUN))
    return runs


def span_json_from_archive(tmp_path, runs, monkeypatch):
    """span_by_condition.json as span_by_condition.py writes it, from the same runs packed into
    an archive the way cloud_archive/sbl_runs.tgz packs them."""
    archive = tmp_path / "sbl_runs.tgz"
    with tarfile.open(str(archive), "w:gz") as tf:
        for path in sorted(runs.rglob("*")):
            if path.is_file():
                tf.add(str(path), arcname="runs/" + path.relative_to(runs).as_posix())
    out = tmp_path / "span_by_condition.json"
    monkeypatch.setattr(sbc, "OUT_JSON", str(out))
    monkeypatch.setattr(sbc, "OUT_CSV", str(tmp_path / "span_run_level.csv"))
    assert sbc.main(["--archive", str(archive), "--progress", "0"]) == 0
    sbc.RATIO_HIST.clear()
    return out


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


class TestDeliveryBin:
    def test_an_edge_belongs_to_the_bin_it_opens(self):
        assert rbd.delivery_bin(MS - 1) == 71
        assert rbd.delivery_bin(MS) == 72

    def test_whole_decades_land_on_multiples_of_24(self):
        for k in range(0, 13):
            assert rbd.delivery_bin(10 ** k) == 24 * (k - 3)

    def test_it_agrees_with_floating_point_away_from_the_edges(self):
        for d_ns in range(1_234, 10 ** 9, 7_654_321):
            assert rbd.delivery_bin(d_ns) == math.floor(24 * math.log10(d_ns / 1000.0))

    def test_the_corpus_values_quoted_in_the_docstring(self):
        assert rbd.delivery_bin(1500 * 1000) == 76
        assert rbd.delivery_bin(2500 * 1000) == 81


class TestExtract:
    def test_the_table_is_the_one_counted_by_hand_and_by_span_by_condition(self, tmp_path,
                                                                          monkeypatch, capsys):
        runs = make_tree(tmp_path)
        span = span_json_from_archive(tmp_path, runs, monkeypatch)
        assert set(json.loads(span.read_text())["conditions"]) == {
            "kafka_n2_feed1#pass", "kafka_n2_feed1#fail"}
        out = tmp_path / "model" / "counts.csv"
        assert rbd.main(["extract", "--runs-dir", str(runs), "--span-json", str(span),
                         "--out", str(out)]) == 0
        assert _rows(out) == EXPECTED_ROWS
        said = capsys.readouterr().out
        assert "runs 2, messages 7, negatives 1, condition and gate keys 2" in said
        assert "(5 rows)" in said

    def test_the_ratio_histogram_is_left_as_it_was_found(self, tmp_path, monkeypatch):
        runs = make_tree(tmp_path)
        span = span_json_from_archive(tmp_path, runs, monkeypatch)
        sbc.RATIO_HIST["sentinel"] = 1
        rbd.main(["extract", "--runs-dir", str(runs), "--span-json", str(span),
                  "--out", str(tmp_path / "counts.csv")])
        assert sbc.RATIO_HIST == {"sentinel": 1}

    def test_a_missing_tree_says_where_it_comes_from(self, tmp_path, capsys):
        out = tmp_path / "counts.csv"
        assert rbd.main(["extract", "--runs-dir", str(tmp_path / "nowhere"),
                         "--out", str(out)]) == 1
        assert "tar -xzf cloud_archive/sbl_runs.tgz" in capsys.readouterr().out
        assert not out.exists()

    def test_a_run_whose_join_disagrees_with_consume_run_stops_everything(self, tmp_path,
                                                                         monkeypatch, capsys):
        """A consumer row without t_output_ns: consume_run counts the message, join_run cannot
        form all six spans and drops it. The extraction must stop rather than lose it."""
        runs = make_tree(tmp_path)
        span = span_json_from_archive(tmp_path, runs, monkeypatch)
        make_run(runs, CAMPAIGN + "_kafka_feed1_rep3", PASS_MESSAGES, blank_output=1)
        sbc.RATIO_HIST["sentinel"] = 1
        out = tmp_path / "counts.csv"
        assert rbd.main(["extract", "--runs-dir", str(runs), "--span-json", str(span),
                         "--out", str(out)]) == 1
        said = capsys.readouterr().out
        assert ("STOP: %s_kafka_feed1_rep3: messages 3 here and 4 in span_by_condition, "
                "negatives 0 here and 0 there" % CAMPAIGN) in said
        assert not out.exists()
        assert sbc.RATIO_HIST == {"sentinel": 1}

    def test_a_table_that_misses_the_json_names_each_difference_and_is_not_written(
            self, tmp_path, monkeypatch, capsys):
        runs = make_tree(tmp_path)
        span = span_json_from_archive(tmp_path, runs, monkeypatch)
        data = json.loads(span.read_text())
        data["conditions"]["kafka_n2_feed1#pass"]["S"]["n"] += 1
        data["runs"] += 1
        span.write_text(json.dumps(data))
        out = tmp_path / "counts.csv"
        assert rbd.main(["extract", "--runs-dir", str(runs), "--span-json", str(span),
                         "--out", str(out)]) == 1
        said = capsys.readouterr().out
        assert ("kafka_n2_feed1#pass: messages 4 here and 5 in the JSON, negatives 0 here and 0 "
                "in the JSON") in said
        assert "runs 2 here and 3 in the JSON" in said
        assert "kafka_n2_feed1#fail" not in said
        assert not out.exists()

    def test_a_message_with_no_delivery_cannot_be_binned_and_says_so(self, tmp_path,
                                                                    monkeypatch, capsys):
        """recv == send: D = 0, so the message has no bin. span_by_condition.json counts it,
        so the table cannot reproduce the JSON and must not be written."""
        runs = make_tree(tmp_path, extra=[(CAMPAIGN + "_kafka_feed1_rep3",
                                           PASS_MESSAGES + [(0, 200 * 1000)], {})])
        span = span_json_from_archive(tmp_path, runs, monkeypatch)
        out = tmp_path / "counts.csv"
        assert rbd.main(["extract", "--runs-dir", str(runs), "--span-json", str(span),
                         "--out", str(out)]) == 1
        said = capsys.readouterr().out
        assert "messages with no delivery above zero to bin: 1" in said
        assert ("kafka_n2_feed1#fail: messages 7 here and 8 in the JSON, negatives 1 here and 2 "
                "in the JSON") in said
        assert not out.exists()

    def test_negatives_cannot_be_read_off_bins_that_straddle_zero(self):
        span = {"bin_lo_us": -125, "bin_width_us": 50, "conditions": {}}
        with pytest.raises(ValueError, match="zero is not an edge"):
            rbd.json_totals(span)


# ------------------------------------------------------------ a counts table checked by hand

#: Every fine bin is a multiple of 6, so each sits alone in its bin at 4, 8 and 12 per decade
#: (12, 24, 36 for 72; 13, 26, 39 for 78; 14, 28, 42 for 84) and all three binnings must agree.
HAND = {
    # 5% -> 20% -> 11%: one significant rise (x4.0), then a fall, which is not a rise.
    ("kafka_n5_feed4", "pass", 72): (600, 30),
    ("kafka_n5_feed4", "pass", 78): (600, 120),
    ("kafka_n5_feed4", "pass", 84): (600, 66),
    # 100 messages is under the minimum; 10% -> 11% overlaps. Pooled: 5% -> 17.5% (x3.5) -> 11%.
    ("kafka_n5_feed4", "fail", 72): (100, 5),
    ("kafka_n5_feed4", "fail", 78): (200, 20),
    ("kafka_n5_feed4", "fail", 84): (200, 22),
    # 0 of 400 -> 10%: interval [0, 0.0095] against a lower bound of 0.074, with no finite factor.
    ("redis_n1_feed1", "pass", 72): (400, 0),
    ("redis_n1_feed1", "pass", 78): (400, 40),
    # One bin over the minimum: not testable, however steep the sparse bin after it.
    ("redis_n2_feed2", "pass", 72): (500, 10),
    ("redis_n2_feed2", "pass", 78): (100, 50),
    # 5% -> 20% across a sparse bin, which is passed over rather than bridged.
    ("kafka_n9_feed3", "fail", 72): (300, 15),
    ("kafka_n9_feed3", "fail", 78): (50, 25),
    ("kafka_n9_feed3", "fail", 84): (300, 60),
}
#: condition, group, testable, bins_used, significant_rise, largest_rise_factor (all binnings).
HAND_RESULTS = [
    ("kafka_n5_feed4", "pass", "1", "3", "1", "4.000"),
    ("kafka_n5_feed4", "fail", "1", "2", "0", ""),
    ("kafka_n5_feed4", "pooled", "1", "3", "1", "3.500"),
    ("kafka_n9_feed3", "fail", "1", "2", "1", "4.000"),
    ("kafka_n9_feed3", "pooled", "1", "2", "1", "4.000"),
    ("redis_n1_feed1", "pass", "1", "2", "1", "inf"),
    ("redis_n1_feed1", "pooled", "1", "2", "1", "inf"),
    ("redis_n2_feed2", "pass", "0", "1", "0", ""),
    ("redis_n2_feed2", "pooled", "0", "1", "0", ""),
]


def _hand_rows():
    return [[c, g, str(k), t, u, r, f] for c, g, t, u, r, f in HAND_RESULTS
            for k in rbd.BINNINGS]


class TestRegroup:
    COUNTS = {("c", "pass", 72 + i): (10 * (i + 1), i + 1) for i in range(6)}

    def test_fine_bins_merge_into_coarse_ones_on_whole_decades(self):
        counts = dict(self.COUNTS)
        counts[("c", "fail", -1)] = (7, 1)
        assert rbd.regroup(counts, 4) == {("c", "pass"): {12: [210, 21]},
                                          ("c", "fail"): {-1: [7, 1]},
                                          ("c", "pooled"): {12: [210, 21], -1: [7, 1]}}
        assert rbd.regroup(counts, 8)[("c", "pass")] == {24: [60, 6], 25: [150, 15]}
        assert rbd.regroup(counts, 12)[("c", "pass")] == {36: [30, 3], 37: [70, 7],
                                                          38: [110, 11]}

    def test_a_binning_that_does_not_nest_is_refused(self):
        with pytest.raises(ValueError, match="do not nest"):
            rbd.regroup(self.COUNTS, 5)


class TestAssess:
    def test_the_intervals_behind_the_hand_verdicts(self):
        """The Wilson bounds the hand table's verdicts rest on, to four places, so a reader can
        check each verdict without running anything: a rise counts when the second interval
        starts above the end of the first."""
        def bounds(k, n):
            return tuple(round(x, 4) for x in wilson(k, n))
        assert bounds(30, 600) == (0.0352, 0.0705) and bounds(120, 600) == (0.1699, 0.2339)
        assert bounds(0, 400) == (0.0, 0.0095) and bounds(40, 400) == (0.0743, 0.1333)
        assert bounds(20, 200) == (0.0657, 0.1494) and bounds(22, 200) == (0.0738, 0.1609)
        assert bounds(15, 300) == (0.0305, 0.0808) and bounds(60, 300) == (0.1587, 0.2489)
        assert bounds(35, 700) == (0.0362, 0.0687) and bounds(140, 800) == (0.1502, 0.2029)
        assert bounds(5, 100) == (0.0215, 0.1118)      # overlaps 20 of 200: no rise at 86

    def test_a_point_rise_inside_overlapping_intervals_is_not_counted(self):
        assert rbd.assess({1: (200, 20), 2: (200, 22)}, rbd.MIN_COUNT) == (2, [])

    def test_a_significant_fall_is_not_a_rise(self):
        assert rbd.assess({1: (600, 120), 2: (600, 30)}, rbd.MIN_COUNT) == (2, [])

    def test_a_sparse_bin_is_left_out_and_its_neighbours_compared(self):
        assert rbd.assess({1: (300, 15), 2: (50, 25), 3: (300, 60)}, rbd.MIN_COUNT) == (2, [4.0])

    def test_a_rise_from_no_negatives_has_no_finite_factor(self):
        assert rbd.assess({1: (400, 0), 2: (400, 40)}, rbd.MIN_COUNT) == (2, [math.inf])

    def test_a_bin_holding_exactly_the_minimum_takes_part(self):
        m = rbd.MIN_COUNT
        assert rbd.assess({1: (m, 0), 2: (m, m)}, m) == (2, [math.inf])
        assert rbd.assess({1: (m - 1, 0), 2: (m, m)}, m) == (1, [])

    def test_every_rise_is_kept_and_the_result_reports_the_largest(self):
        """2% -> 10% -> 40%: two significant rises, x5 then x4; the row carries the x5."""
        bins = {1: (600, 12), 2: (600, 60), 3: (600, 240)}
        assert rbd.assess(bins, rbd.MIN_COUNT) == (3, [5.0, 4.0])
        rows = rbd.analyze({("x", "pass", 72 + 6 * b): v for b, v in bins.items()})
        assert {r["largest_rise_factor"] for r in rows} == {5.0}


class TestAnalyze:
    def test_the_hand_table_gives_the_hand_verdicts_at_every_binning(self):
        rows = rbd.analyze(HAND)
        assert [rbd.result_fields(r) for r in rows] == _hand_rows()

    def test_the_summary_counts_conditions_testable_rising_and_the_range(self):
        lines = rbd.summary_lines(rbd.analyze(HAND))
        assert lines[0].startswith("minimum 172 messages per bin")
        body = lines[2:]
        assert len(body) == 9
        assert body[0].split() == ["4/decade", "pass", "3", "2", "2", "4.00x", "to", "4.00x;",
                                   "1", "from", "a", "bin", "with", "no", "negatives"]
        assert body[1].split() == ["4/decade", "fail", "2", "2", "1", "4.00x", "to", "4.00x"]
        assert body[2].split()[:7] == ["4/decade", "pooled", "4", "3", "3", "3.50x", "to"]
        assert body[8].split()[:2] == ["12/decade", "pooled"]

    def test_the_sensitivity_lines_follow_the_minimum_by_hand(self):
        """At 86 the fail run's 100-message bin and the 100-message steep bin take part; at 344
        every bin of 300 or fewer drops out."""
        half = rbd.sensitivity_line(rbd.analyze(HAND, 86), 86)
        assert half == ("sensitivity, minimum 86 (rising/testable): "
                        + "; ".join("%d/decade pass 3/3, fail 1/2, pooled 4/4" % k
                                    for k in rbd.BINNINGS))
        double = rbd.sensitivity_line(rbd.analyze(HAND, 344), 344)
        assert double == ("sensitivity, minimum 344 (rising/testable): "
                          + "; ".join("%d/decade pass 2/2, fail 0/0, pooled 2/2" % k
                                      for k in rbd.BINNINGS))

    def test_a_group_with_no_conditions_is_summarised_as_empty(self):
        only_pass = {key: value for key, value in HAND.items() if key[1] == "pass"}
        lines = rbd.summary_lines(rbd.analyze(only_pass))
        assert lines[3].split() == ["4/decade", "fail", "0", "0", "0", "none"]

    def test_factor_ranges(self):
        assert rbd.factor_range([]) == "none"
        assert rbd.factor_range([2.0, 1.5]) == "1.50x to 2.00x"
        assert rbd.factor_range([math.inf]) == "1 from a bin with no negatives"
        assert rbd.factor_range([math.inf, 3.0]) == "3.00x to 3.00x; 1 from a bin with no negatives"

    def test_the_analyze_command_writes_the_results_and_prints_the_summary(self, tmp_path,
                                                                          capsys):
        counts = tmp_path / "counts.csv"
        rbd.write_counts(HAND, str(counts))
        out = tmp_path / "results.csv"
        assert rbd.main(["analyze", "--counts", str(counts), "--out", str(out)]) == 0
        assert _rows(out) == [rbd.OUT_FIELDS] + _hand_rows()
        said = capsys.readouterr().out
        assert "sensitivity, minimum 86 " in said and "sensitivity, minimum 344 " in said
        assert "(27 rows)" in said


# ------------------------------------------------------------ the committed artefacts

class TestCommitted:
    def test_the_minimum_is_the_smallest_count_that_resolves_the_corpus_rate(self):
        """Fixed from the corpus as it was counted before any bin was read, and kept.

        7 Oct 2026: that corpus still held the late messages, which the census counts. Without
        them the rate is higher and the same rule would give a smaller minimum; the summary
        repeats every result at half and at double the minimum, which brackets both.
        """
        census = list(csv.DictReader(open(REPO / "docs" / "results" / "backlog_by_run.csv",
                                          encoding="utf-8")))
        negatives = sum(int(r["negatives"]) for r in census)
        rate = negatives / sum(int(r["joined"]) for r in census)
        assert round(100 * rate, 2) == 8.43

        def width(n, p):
            lo, hi = wilson(p * n, n)
            return hi - lo
        assert width(rbd.MIN_COUNT, rate) < rate <= width(rbd.MIN_COUNT - 1, rate)
        span = json.loads(SPAN_JSON.read_text(encoding="utf-8"))
        now = sum(neg for _, neg in rbd.json_totals(span).values()) / span["events"]
        assert round(100 * now, 2) == 8.79
        assert rbd.MIN_COUNT // 2 < min(n for n in range(2, rbd.MIN_COUNT)
                                        if width(n, now) < now) < rbd.MIN_COUNT

    def test_the_counts_table_reproduces_span_by_condition_json(self):
        counts = rbd.read_counts(str(COUNTS_CSV))
        span = json.loads(SPAN_JSON.read_text(encoding="utf-8"))
        assert rbd.check_totals(counts, span) == []
        # 7 Oct 2026: 708,505 since the late messages were left out, from 738,730; none of
        # them was below zero, so the negatives did not move.
        assert sum(n for n, _ in counts.values()) == span["events"] == 708_505
        assert sum(neg for _, neg in counts.values()) == 62_264

    def test_the_results_are_what_the_counts_table_gives(self):
        computed = rbd.analyze(rbd.read_counts(str(COUNTS_CSV)))
        assert _rows(RESULTS_CSV) == [rbd.OUT_FIELDS] + [rbd.result_fields(r) for r in computed]
