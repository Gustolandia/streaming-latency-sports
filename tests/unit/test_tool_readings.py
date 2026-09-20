"""Reading each tool's own output, including the rounding the tools block exists to find.

The danger in a reader like this is tidiness: a parser that normalises a tool's answer destroys
the finding. hey printing four decimals of a second cannot report a difference below 0.1 ms, and
that ceiling has to survive into the reading, not be smoothed away. So these tests hold the
numbers *and* the step the tool's own printing puts under them.
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import tool_readings as tr  # noqa: E402

VEGETA = """Requests      [total, rate, throughput]  600, 10.02, 9.99
Duration      [total, attack, wait]     1m0s, 59.9s, 2.393ms
Latencies     [min, mean, 50, 90, 95, 99, max]  1.109ms, 3.417ms, 2.913ms, 5.2ms, 6.1ms, 9.83ms, 21.4ms
Bytes In      [total, mean]             123456, 205.76
Success       [ratio]                   100.00%
"""

HEY = """Summary:
  Total:	10.0021 secs
  Slowest:	0.0214 secs
  Fastest:	0.0011 secs
  Average:	0.0034 secs
  Requests/sec:	99.9790

Latency distribution:
  50% in 0.0029 secs
  99% in 0.0098 secs
"""

VALKEY = """====== GET ======
  100000 requests completed in 1.41 seconds

Latency by percentile distribution:
avg       0.271
min       0.000
p50       0.263
p99       0.887
max       2.119
"""

MEMTIER = """
Type    Ops/sec  Hits/sec  Misses/sec  Avg. Latency  p50 Latency  p99 Latency  KB/sec
Totals  70123.4  0.0       0.0         0.541         0.487        1.823        5412.1
"""

KAFKA = """Avg latency: 3.4210 ms
Percentiles: 50th = 3, 99th = 9, 99.9th = 21
"""

RDKAFKA = """%% 600 messages produced, latency curr/avg/lo/hi 3120/3417/1109/21400us
"""

K6 = """     http_req_duration..............: avg=3.41ms min=1.1ms med=2.91ms max=21.4ms p(99)=9.83ms
     iterations.....................: 600
"""


class TestTheStepAToolsPrintingPutsUnderIt:

    @pytest.mark.parametrize("text,step", [
        ("3.417", 0.001), ("0.0034", 0.0001), ("3", 1.0), ("21.4", 0.1), ("0.000", 0.001),
    ])
    def test_the_digits_say_the_smallest_step(self, text, step):
        assert tr.step_of(text) == pytest.approx(step)

    def test_a_number_with_no_digits_has_no_step(self):
        assert tr.step_of("none") is None
        assert tr.step_of(None) is None

    def test_a_step_is_converted_with_its_unit(self):
        """hey prints four decimals of a second, so it cannot see below a tenth of a
        millisecond -- which is the step T1 adds."""
        assert tr.as_ms(tr.step_of("0.0034"), "s") == pytest.approx(0.1)


class TestUnits:

    @pytest.mark.parametrize("unit,ms", [("ns", 1e-6), ("us", 1e-3), ("µs", 1e-3),
                                         ("ms", 1.0), ("s", 1000.0)])
    def test_each_unit_a_tool_prints(self, unit, ms):
        assert tr.as_ms(1.0, unit) == pytest.approx(ms)

    def test_a_unit_we_do_not_know_is_refused_rather_than_assumed(self):
        assert tr.as_ms(1.0, "furlongs") is None

    def test_nothing_converts_to_nothing(self):
        assert tr.as_ms(None, "ms") is None and tr.as_ms(1.0, None) is None


class TestEachToolsOwnOutput:

    def test_vegeta_keeps_its_named_figures_and_its_count(self):
        got = tr.read_tool("vegeta", VEGETA)
        assert got["reported_ms"]["avg"] == pytest.approx(3.417)
        assert got["reported_ms"]["p50"] == pytest.approx(2.913)
        assert got["reported_ms"]["p99"] == pytest.approx(9.83)
        assert got["reported_ms"]["min"] == pytest.approx(1.109)
        assert got["kept"] == 600
        assert got["step_ms"] == pytest.approx(0.1), "21.4ms is its coarsest printing"

    def test_vegeta_with_no_latencies_line_reports_nothing_rather_than_zero(self):
        assert tr.read_tool("vegeta", "Success [ratio] 100.00%")["reported_ms"] == {}

    def test_hey_is_read_in_seconds_and_its_step_is_a_tenth_of_a_millisecond(self):
        got = tr.read_tool("hey", HEY)
        assert got["reported_ms"]["avg"] == pytest.approx(3.4)
        assert got["reported_ms"]["p50"] == pytest.approx(2.9)
        assert got["reported_ms"]["p99"] == pytest.approx(9.8)
        assert got["step_ms"] == pytest.approx(0.1)

    def test_valkey_benchmark_and_the_floor_its_printing_puts_at_zero(self):
        got = tr.read_tool("valkey-benchmark", VALKEY)
        assert got["reported_ms"]["avg"] == pytest.approx(0.271)
        assert got["reported_ms"]["min"] == 0.0, "anything faster than its step reads as zero"
        assert got["kept"] == 100000
        assert got["step_ms"] == pytest.approx(0.001)

    def test_memtier_totals_row(self):
        got = tr.read_tool("memtier_benchmark", MEMTIER)
        assert got["reported_ms"]["avg"] == pytest.approx(0.541)
        assert got["reported_ms"]["p50"] == pytest.approx(0.487)
        assert got["reported_ms"]["p99"] == pytest.approx(1.823)

    def test_kafka_end_to_end_prints_whole_milliseconds_for_its_percentiles(self):
        """The audit's finding: an exact average beside percentiles truncated to milliseconds."""
        got = tr.read_tool("kafka-end-to-end", KAFKA)
        assert got["reported_ms"]["avg"] == pytest.approx(3.421)
        assert got["reported_ms"]["p50"] == 3.0 and got["reported_ms"]["p99"] == 9.0
        assert got["step_ms"] == 1.0, "a whole millisecond, so it cannot see T1's 0.1 ms step"

    def test_librdkafka_reports_microseconds(self):
        got = tr.read_tool("rdkafka_performance", RDKAFKA)
        assert got["reported_ms"]["avg"] == pytest.approx(3.417)
        assert got["reported_ms"]["min"] == pytest.approx(1.109)
        assert got["reported_ms"]["max"] == pytest.approx(21.4)
        assert got["unit"] == "us" and got["step_ms"] == pytest.approx(0.001)

    def test_k6_carries_a_unit_on_every_figure(self):
        got = tr.read_tool("k6", K6)
        assert got["reported_ms"]["avg"] == pytest.approx(3.41)
        assert got["reported_ms"]["p50"] == pytest.approx(2.91)
        assert got["reported_ms"]["p99"] == pytest.approx(9.83)
        assert got["reported_ms"]["min"] == pytest.approx(1.1)

    @pytest.mark.parametrize("tool", sorted(tr.READERS))
    def test_every_tool_reads_nothing_from_nothing_without_falling_over(self, tool):
        got = tr.read_tool(tool, "")
        assert got["reported_ms"] == {} and got["tool"]

    def test_a_tool_with_no_reader_is_refused(self):
        with pytest.raises(ValueError, match="no reader for fio"):
            tr.read_tool("fio", "")


class TestWhatATeaCannotSee:

    def test_a_difference_under_the_tools_step_is_out_of_its_reach(self):
        """T1 adds 0.1 ms steps. A tool printing whole milliseconds cannot report them, and that
        is a fact about the tool rather than a failed run."""
        reading = tr.read_tool("kafka-end-to-end", KAFKA)
        assert tr.below_its_step(reading, 3.0, 3.1) is True

    def test_a_difference_above_it_is_within_reach(self):
        reading = tr.read_tool("kafka-end-to-end", KAFKA)
        assert tr.below_its_step(reading, 3.0, 5.0) is False

    def test_a_finer_tool_can_see_the_same_step(self):
        assert tr.below_its_step(tr.read_tool("vegeta", VEGETA), 3.0, 3.2) is False

    @pytest.mark.parametrize("reading,a,b", [
        ({"step_ms": None}, 1.0, 2.0), ({"step_ms": 1.0}, None, 2.0), ({"step_ms": 1.0}, 1.0, None),
    ])
    def test_without_the_pieces_it_says_nothing_rather_than_guessing(self, reading, a, b):
        assert tr.below_its_step(reading, a, b) is None


class TestTheCommand:

    def run(self, argv):
        out = io.StringIO()
        return tr.main(argv, out), out.getvalue()

    def test_it_reads_a_file_and_prints_the_reading(self, tmp_path):
        path = tmp_path / "vegeta.txt"
        path.write_text(VEGETA, encoding="utf-8")
        code, text = self.run(["read", "--tool", "vegeta", "--file", str(path)])
        assert code == 0 and json.loads(text)["kept"] == 600

    def test_it_can_write_the_reading_beside_the_run(self, tmp_path):
        path = tmp_path / "hey.txt"
        path.write_text(HEY, encoding="utf-8")
        where = tmp_path / "reading.json"
        code, _ = self.run(["read", "--tool", "hey", "--file", str(path),
                            "--out", str(where)])
        assert code == 0
        assert json.loads(where.read_text(encoding="utf-8"))["step_ms"] == pytest.approx(0.1)

    def test_a_tool_that_reported_nothing_leaves_with_one(self, tmp_path):
        path = tmp_path / "empty.txt"
        path.write_text("nothing here", encoding="utf-8")
        code, _ = self.run(["read", "--tool", "k6", "--file", str(path)])
        assert code == 1, "a run whose tool printed no latency is not a reading"
