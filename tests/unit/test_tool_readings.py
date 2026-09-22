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

# Every fixture below is the shape the tool really prints, taken from its own source or its
# documentation rather than from what this reader would find convenient. Three parsers were wrong
# against the real thing and the tidy fixtures they were written against hid it: valkey-benchmark
# prints a table and not a list, memtier_benchmark has a p99.9 column, and rdkafka_performance
# divides by a thousand before printing. Keep these faithful.

VEGETA = """Requests      [total, rate, throughput]         600, 10.02, 9.99
Duration      [total, attack, wait]             59.9s, 59.888s, 2.393ms
Latencies     [min, mean, 50, 90, 95, 99, max]  1.109ms, 3.417ms, 2.913ms, 5.2ms, 6.1ms, 9.83ms, 21.4ms
Bytes In      [total, mean]                     123456, 205.76
Bytes Out     [total, mean]                     0, 0.00
Success       [ratio]                           100.00%
Status Codes  [code:count]                      200:600
Error Set:
"""

# hey separates its labels from its figures with a tab. The tab is written as an escape rather
# than typed, because a control character sitting in a source file is how a heredoc that expanded
# too early looks, and tests/unit/test_source_hygiene.py refuses them for that reason.
HEY = """Summary:
  Total:\t10.0021 secs
  Slowest:\t0.0214 secs
  Fastest:\t0.0011 secs
  Average:\t0.0034 secs
  Requests/sec:\t99.9790

Latency distribution:
  50% in 0.0029 secs
  99% in 0.0098 secs

Status code distribution:
  [200]\t900 responses
  [503]\t100 responses
"""

# valkey-benchmark's summary is a row of names then a row of figures, printed at %9.3f, with a
# p95 sitting between p50 and p99 (src/valkey-benchmark.c).
VALKEY = """====== GET ======
  100000 requests completed in 1.41 seconds
  1 parallel clients

Summary:
  throughput summary: 70921.98 requests per second
  latency summary (msec):
          avg       min       p50       p95       p99       max
        0.271     0.000     0.263     0.407     0.887     2.119
"""

# memtier_benchmark's real totals block: five decimals, and a p99.9 column before KB/sec.
MEMTIER = """ALL STATS
========================================================================
Type         Ops/sec     Hits/sec   Misses/sec    Avg. Latency     p50 Latency     p99 Latency   p99.9 Latency       KB/sec
------------------------------------------------------------------------
Sets         2312.01          ---          ---        22.43371        21.24700        47.35900       101.88700       178.00
Gets         2312.01      2312.01         0.00        22.42225        21.24700        47.35900       101.88700       464.47
Waits           0.00          ---          ---         0.00000         0.00000         0.00000         0.00000          ---
Totals       4624.02      2312.01         0.00        22.42798        21.24700        47.35900       101.88700       642.47
"""

# An older build, whose average column is headed "Latency" and which has no p99.9 at all.
MEMTIER_OLDER = """Type        Ops/sec    Hits/sec  Misses/sec      Latency     p50 Latency     p99 Latency       KB/sec
Totals     70123.40        0.00        0.00      0.54100         0.48700         1.82300      5412.10
"""

KAFKA = """Avg latency: 3.4210 ms
Percentiles: 50th = 3, 99th = 9, 99.9th = 21
"""

# ProducerPerformance prints a short line as it goes and a total carrying the percentiles:
# "%d%s records sent, %f records/sec (%.2f MB/sec), %.2f ms avg latency, %.2f ms max latency,
#  %d ms 50th, %d ms 95th, %d ms 99th, %d ms 99.9th.%n"
PRODUCER_PERF = """2510 records sent, 501.8 records/sec (0.24 MB/sec), 1.2 ms avg latency, \
25.0 ms max latency.
3000 records sent, 600.0 records/sec (0.29 MB/sec), 1.3 ms avg latency, 30.0 ms max latency.
3000 records sent, 599.880024 records/sec (0.29 MB/sec), 3.42 ms avg latency, \
21.40 ms max latency, 3 ms 50th, 6 ms 95th, 9 ms 99th, 21 ms 99.9th.
"""

# A run that was killed before it printed its total: only the progress lines are there.
PRODUCER_PERF_KILLED = """2510 records sent, 501.8 records/sec (0.24 MB/sec), \
1.2 ms avg latency, 25.0 ms max latency.
"""

WRK2 = """Running 1m test @ http://127.0.0.1:8080/
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     99%   +/- Stdev
    Latency     3.41ms    1.20ms   9.83ms   75.00%
    Req/Sec    50.10      5.20    60.00    68.00%
  Latency Distribution (HdrHistogram - Recorded Latency)
 50.000%    2.91ms
 75.000%    4.10ms
 90.000%    6.20ms
 99.000%    9.83ms
 99.900%   21.40ms

  3000 requests in 1.00m, 1.21MB read
Requests/sec:     50.00
"""

# PerfTest prints one of these a second and the same shape as its summary; whole microseconds.
RABBIT = """id: test-093012-123, time 1.000s, sent: 50 msg/s, received: 50 msg/s, \
min/median/75th/95th/99th consumer latency: 1109/2913/4100/6200/9830 µs
id: test-093012-123, time 60.000s, sent: 50 msg/s, received: 50 msg/s, \
min/median/75th/95th/99th consumer latency: 1110/2910/4100/6100/9840 µs
"""

# The NATS CLI writes Go durations, truncated to microseconds, each in its own unit.
NATS = """==============================
Pub Server RTT:  340µs
Sub Server RTT:  310µs
Minimum Latency: 1.109ms
Median Latency : 2.913ms
Maximum Latency: 21.4ms

HDR Percentiles:
10:       1.5ms
50:       2.913ms
99:       9.83ms
100:      21.4ms
"""

# librdkafka's format string is ", latency curr/avg/lo/hi %.2f/%.2f/%.2f/%.2fms" with every
# argument divided by 1000.0f first -- milliseconds, two decimals (examples/rdkafka_performance.c).
RDKAFKA = """%% 600 messages consumed (307200 bytes) in 60021ms: 9 msgs/s, 0.01 MB/s, \
latency curr/avg/lo/hi 3.12/3.42/1.11/21.40ms
"""

# k6 as the runner asks for it, with p(99) among the trend statistics.
K6 = """     http_req_duration..............: avg=3.41ms min=1.1ms med=2.91ms max=21.4ms p(99)=9.83ms
     iterations.....................: 600
"""

# k6 left at its defaults: avg, min, med, max, p(90), p(95) -- and no p(99) anywhere.
K6_DEFAULT_STATS = """     iteration_duration.............: avg=1.02s min=1.0s med=1.01s max=1.2s p(90)=1.05s p(95)=1.1s
     http_req_duration..............: avg=3.41ms min=1.1ms med=2.91ms max=21.4ms p(90)=5.2ms p(95)=6.1ms
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

    def test_hey_counts_every_status_code_it_answered_with(self):
        """900 of them were 200s and 100 were 503s; it kept a thousand."""
        assert tr.read_tool("hey", HEY)["kept"] == 1000

    def test_valkey_benchmark_and_the_floor_its_printing_puts_at_zero(self):
        got = tr.read_tool("valkey-benchmark", VALKEY)
        assert got["reported_ms"]["avg"] == pytest.approx(0.271)
        assert got["reported_ms"]["min"] == 0.0, "anything faster than its step reads as zero"
        assert got["kept"] == 100000
        assert got["step_ms"] == pytest.approx(0.001)

    def test_valkey_benchmark_does_not_read_its_p95_as_its_p99(self):
        """Its summary is a table with p95 between p50 and p99. Counting fields from the left
        would report 0.407 as the 99th percentile; reading the header reports 0.887."""
        got = tr.read_tool("valkey-benchmark", VALKEY)
        assert got["reported_ms"]["p50"] == pytest.approx(0.263)
        assert got["reported_ms"]["p99"] == pytest.approx(0.887)
        assert got["reported_ms"]["max"] == pytest.approx(2.119)

    def test_valkey_benchmark_does_not_read_a_column_name_as_a_number(self):
        """The names sit on their own line above the figures. A reader that ran past the newline
        would take the "50" out of "p50" and report an average of 50 ms."""
        assert tr.read_tool("valkey-benchmark", VALKEY)["reported_ms"]["avg"] < 1.0

    def test_memtier_totals_row_at_the_precision_it_really_prints(self):
        got = tr.read_tool("memtier_benchmark", MEMTIER)
        assert got["reported_ms"]["avg"] == pytest.approx(22.42798)
        assert got["reported_ms"]["p50"] == pytest.approx(21.247)
        assert got["reported_ms"]["p99"] == pytest.approx(47.359)
        assert got["step_ms"] == pytest.approx(1e-5), "five decimals of a millisecond"

    def test_memtier_does_not_read_its_p99_9_as_its_p99(self):
        """The p99.9 column arrived beside the others, so the field that holds p99 depends on the
        build. 101.887 is the p99.9 here and must not be reported as the 99th."""
        assert tr.read_tool("memtier_benchmark", MEMTIER)["reported_ms"]["p99"] != \
            pytest.approx(101.887)

    def test_memtier_on_a_build_that_heads_its_average_differently(self):
        got = tr.read_tool("memtier_benchmark", MEMTIER_OLDER)
        assert got["reported_ms"]["avg"] == pytest.approx(0.541)
        assert got["reported_ms"]["p99"] == pytest.approx(1.823)

    def test_kafka_end_to_end_prints_whole_milliseconds_for_its_percentiles(self):
        """The audit's finding: an exact average beside percentiles truncated to milliseconds."""
        got = tr.read_tool("kafka-end-to-end", KAFKA)
        assert got["reported_ms"]["avg"] == pytest.approx(3.421)
        assert got["reported_ms"]["p50"] == 3.0 and got["reported_ms"]["p99"] == 9.0
        assert got["step_ms"] == 1.0, "a whole millisecond, so it cannot see T1's 0.1 ms step"

    def test_librdkafka_prints_milliseconds_however_it_counts(self):
        """It counts microseconds and divides by a thousand before printing, so its figures are
        milliseconds at two decimals. Reading them as the microseconds it counts in would report
        every latency a thousandfold too small and put its step below any clock on earth."""
        got = tr.read_tool("rdkafka_performance", RDKAFKA)
        assert got["reported_ms"]["avg"] == pytest.approx(3.42)
        assert got["reported_ms"]["min"] == pytest.approx(1.11)
        assert got["reported_ms"]["max"] == pytest.approx(21.40)
        assert got["unit"] == "ms" and got["step_ms"] == pytest.approx(0.01)

    def test_k6_carries_a_unit_on_every_figure(self):
        got = tr.read_tool("k6", K6)
        assert got["reported_ms"]["avg"] == pytest.approx(3.41)
        assert got["reported_ms"]["p50"] == pytest.approx(2.91)
        assert got["reported_ms"]["p99"] == pytest.approx(9.83)
        assert got["reported_ms"]["min"] == pytest.approx(1.1)

    def test_k6_reads_the_request_and_not_the_loop_that_paces_it(self):
        """iteration_duration is printed first and includes our script's own sleep -- a second,
        not three milliseconds. The request metric is the one that means anything here."""
        got = tr.read_tool("k6", K6_DEFAULT_STATS)
        assert got["reported_ms"]["avg"] == pytest.approx(3.41)

    def test_k6_left_at_its_defaults_has_no_p99_and_is_not_given_its_p95(self):
        """Its default statistics stop at p(95). A missing percentile is missing."""
        assert "p99" not in tr.read_tool("k6", K6_DEFAULT_STATS)["reported_ms"]

    def test_kafka_producer_performance_reads_its_total_and_not_its_progress(self):
        """It prints a shorter line every few seconds and one total at the end. The total is the
        answer; reading a progress line would report a part of the run as the whole."""
        got = tr.read_tool("kafka-producer-perf", PRODUCER_PERF)
        assert got["reported_ms"]["avg"] == pytest.approx(3.42)
        assert got["reported_ms"]["p50"] == 3.0 and got["reported_ms"]["p99"] == 9.0
        assert got["kept"] == 3000

    def test_kafka_producer_performance_falls_back_when_there_is_no_total(self):
        """A run that was killed has progress lines and no total. That is a reading of what it
        managed, not nothing -- T2 needs to be able to say a tool died partway."""
        got = tr.read_tool("kafka-producer-perf", PRODUCER_PERF_KILLED)
        assert got["reported_ms"]["avg"] == pytest.approx(1.2)
        assert "p50" not in got["reported_ms"] and got["kept"] == 2510

    def test_wrk2_reads_its_average_and_its_histogram(self):
        got = tr.read_tool("wrk2", WRK2)
        assert got["reported_ms"]["avg"] == pytest.approx(3.41)
        assert got["reported_ms"]["p50"] == pytest.approx(2.91)
        assert got["reported_ms"]["p99"] == pytest.approx(9.83)
        assert got["kept"] == 3000

    def test_rabbitmq_perftest_takes_its_last_line_and_reads_microseconds(self):
        """It prints one of these a second; the last is the one that covers the whole run."""
        got = tr.read_tool("rabbitmq-perftest", RABBIT)
        assert got["reported_ms"]["min"] == pytest.approx(1.110)
        assert got["reported_ms"]["p50"] == pytest.approx(2.910)
        assert got["reported_ms"]["p99"] == pytest.approx(9.840)
        assert got["step_ms"] == pytest.approx(0.001), "whole microseconds"

    def test_rabbitmq_perftest_keeps_a_negative_where_it_prints_one(self):
        """The audit rates it high and says it keeps negatives. If it ever prints one, the
        reader must carry it through rather than lose it to a regex that wants digits."""
        text = RABBIT.replace("1110/2910", "-890/2910")
        assert tr.read_tool("rabbitmq-perftest", text)["reported_ms"]["min"] == \
            pytest.approx(-0.890)

    def test_perftest_is_read_when_it_prints_a_sixth_figure(self):
        """The build this block runs prints the maximum as well. The five-figure pattern
        matched the label and the first five numbers and stopped at the slash before the
        sixth, so every run of it read as nothing at all with its latencies in the file.
        """
        text = ('id: test-191012-635, consumer latency min/median/75th/95th/99th/max '
                '271/507/576/692/809/5112 µs')
        got = tr.read_tool("rabbitmq-perftest", text)["reported_ms"]
        assert got["min"] == pytest.approx(0.271)
        assert got["p50"] == pytest.approx(0.507)
        assert got["p99"] == pytest.approx(0.809)
        assert got["max"] == pytest.approx(5.112)

    def test_a_negative_minimum_survives_the_sixth_figure_too(self):
        """A negative minimum is the whole point of T2 for this tool."""
        text = ('id: t, consumer latency min/median/75th/95th/99th/max '
                '-890/975/1320/1900/2799/3000 µs')
        got = tr.read_tool("rabbitmq-perftest", text)["reported_ms"]
        assert got["min"] == pytest.approx(-0.890)

    def test_nats_reads_a_go_duration_in_whatever_unit_it_chose(self):
        """Go prints 1.109ms and 340µs on adjacent lines, so the unit travels with the figure."""
        got = tr.read_tool("nats-latency", NATS)
        assert got["reported_ms"]["min"] == pytest.approx(1.109)
        assert got["reported_ms"]["p50"] == pytest.approx(2.913)
        assert got["reported_ms"]["p99"] == pytest.approx(9.83)
        assert got["reported_ms"]["max"] == pytest.approx(21.4)

    def test_nats_is_read_with_the_clock_it_puts_on_every_line(self):
        """Written down from the documented report, the patterns began at the start of the line.
        Run against the tool, every line arrives with the time on it: T4 stopped saying nats had
        printed no latency at all, with its latencies in the file beside the message."""
        stamped = "\n".join("16:18:00 " + line for line in NATS.splitlines())
        got = tr.read_tool("nats-latency", stamped)
        assert got["reported_ms"]["min"] == pytest.approx(1.109)
        assert got["reported_ms"]["p50"] == pytest.approx(2.913)
        assert got["reported_ms"]["p99"] == pytest.approx(9.83)
        assert got["reported_ms"]["max"] == pytest.approx(21.4)

    def test_there_are_ten_tools_and_more(self):
        """The block is ten tools. Losing one to a typo in the table should fail here."""
        assert len(tr.READERS) >= 10


class TestTheStepBelongsToTheFigureAndNotTheTool:
    """Kafka's two tools both print an exact average beside percentiles chopped to whole
    milliseconds. That gap is what T-P1 and T-P2 predict, so a reading that carried one step for
    the whole tool would report the average as blind along with them and lose the finding."""

    def test_an_exact_average_beside_chopped_percentiles(self):
        got = tr.read_tool("kafka-end-to-end", KAFKA)
        assert got["steps_ms"]["avg"] == pytest.approx(1e-4)
        assert got["steps_ms"]["p50"] == 1.0

    def test_the_tools_own_step_is_the_coarsest_of_them(self):
        assert tr.read_tool("kafka-end-to-end", KAFKA)["step_ms"] == 1.0

    def test_producer_performance_shows_the_same_gap(self):
        got = tr.read_tool("kafka-producer-perf", PRODUCER_PERF)
        assert got["steps_ms"]["avg"] == pytest.approx(0.01)
        assert got["steps_ms"]["p99"] == 1.0

    def test_a_step_asked_of_one_figure_answers_for_that_figure(self):
        """T1 adds 0.1 ms. EndToEndLatency's percentiles cannot see it and its average can."""
        got = tr.read_tool("kafka-end-to-end", KAFKA)
        assert tr.below_its_step(got, 3.0, 3.1, "p50") is True
        assert tr.below_its_step(got, 3.0, 3.1, "avg") is False

    def test_a_figure_the_tool_did_not_print_falls_back_to_the_tools_own_step(self):
        got = tr.read_tool("kafka-end-to-end", KAFKA)
        assert tr.below_its_step(got, 3.0, 3.1, "min") is True

    @pytest.mark.parametrize("tool", sorted(tr.READERS))
    def test_every_tool_reads_nothing_from_nothing_without_falling_over(self, tool):
        got = tr.read_tool(tool, "")
        assert got["reported_ms"] == {} and got["tool"]

    def test_a_tool_with_no_reader_is_refused(self):
        with pytest.raises(ValueError, match="no reader for fio"):
            tr.read_tool("fio", "")


class TestReadingATableByItsOwnHeader:
    """The two tools that print tables have both moved their columns between versions, so the
    reading is taken by column name. What matters is what happens when a name is not where the
    reader expects it: nothing, rather than the neighbouring figure under the wrong label."""

    def test_a_column_the_header_does_not_have_is_absent_rather_than_guessed(self):
        got, steps = tr._by_column(["avg", "min"], ["1.0", "2.0"], tr.VALKEY_COLUMNS)
        assert set(got) == {"avg", "min"} and len(steps) == 2

    def test_a_header_wider_than_its_row_stops_at_the_figures_there_are(self):
        """A truncated line -- a run killed mid-print -- must not read past the end of it."""
        got, _ = tr._by_column(["avg", "min", "p50"], ["1.0"], tr.VALKEY_COLUMNS)
        assert got == {"avg": pytest.approx(1.0)}

    def test_a_field_that_is_not_a_number_is_not_made_into_one(self):
        """memtier prints --- where a row has no figure for that column."""
        got, _ = tr._by_column(["avg", "min"], ["---", "2.0"], tr.VALKEY_COLUMNS)
        assert got == {"min": pytest.approx(2.0)}

    @pytest.mark.parametrize("tool,text", [
        ("valkey-benchmark", "====== GET ======\n  100000 requests completed in 1.41 seconds\n"),
        ("memtier_benchmark", "ALL STATS\nnothing like a table here\n"),
    ])
    def test_output_without_the_table_reads_nothing_rather_than_falling_over(self, tool, text):
        assert tr.read_tool(tool, text)["reported_ms"] == {}


class TestWhatAToolCannotSee:

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


class TestWhatTheStaircaseSaysTheToolCanReport:
    """T1 adds a staircase and asks what each tool can report. The smallest step it *did* report
    is its step as measured rather than as printed, and T2 has to predict through it: a tool that
    cannot report a tenth of a millisecond does not meet a negative a tenth below zero either,
    because its clock puts that value at zero before its rule for odd values runs."""

    def rung(self, avg, step):
        return {"reported_ms": {"avg": avg}, "steps_ms": {"avg": step}, "step_ms": step}

    def test_a_fine_tool_reports_the_smallest_step_there_is(self):
        found = tr.step_seen([(0.0, self.rung(3.0, 0.001)), (0.1, self.rung(3.1, 0.001)),
                              (0.5, self.rung(3.5, 0.001))])
        assert found["smallest_reported_ms"] == 0.1 and found["zero_avg_ms"] == 3.0

    def test_a_whole_millisecond_tool_reports_none_of_the_small_ones(self):
        found = tr.step_seen([(0.0, self.rung(3.0, 1.0)), (0.1, self.rung(3.0, 1.0)),
                              (0.5, self.rung(3.0, 1.0)), (1.5, self.rung(4.0, 1.0))])
        assert found["smallest_reported_ms"] == 1.5
        assert [s["seen"] for s in found["steps"]] == [False, False, False, True]

    def test_a_tool_that_never_moves_has_no_measured_step_rather_than_a_zero(self):
        found = tr.step_seen([(0.0, self.rung(3.0, 1.0)), (2.0, self.rung(3.0, 1.0))])
        assert found["smallest_reported_ms"] is None

    def test_without_the_zero_step_nothing_can_be_compared(self):
        found = tr.step_seen([(0.1, self.rung(3.1, 0.001))])
        assert found["zero_avg_ms"] is None and found["smallest_reported_ms"] is None
        assert found["steps"][0]["moved_ms"] is None

    def test_a_step_the_tool_printed_nothing_for_is_not_a_step_it_reported(self):
        found = tr.step_seen([(0.0, self.rung(3.0, 0.001)),
                              (0.1, {"reported_ms": {}, "steps_ms": {}, "step_ms": None})])
        assert found["smallest_reported_ms"] is None and not found["steps"][1]["seen"]

    def test_the_zero_step_itself_is_never_the_answer(self):
        """Its own average against itself moves nothing, and a tool cannot report an added
        nothing however fine it is."""
        found = tr.step_seen([(0.0, self.rung(3.0, 0.0)), (0.1, self.rung(3.1, 0.001))])
        assert found["smallest_reported_ms"] == 0.1

    def test_it_reads_t1s_runs_off_their_own_folder_names(self, tmp_path):
        for name, avg in (("t1-vegeta-0ms", 3.0), ("t1-vegeta-0_1ms", 3.1),
                          ("t1-vegeta-1_5ms", 4.5)):
            folder = tmp_path / name
            folder.mkdir()
            (folder / "reading.json").write_text(
                json.dumps(self.rung(avg, 0.001)), encoding="utf-8")
        (tmp_path / "t3-vegeta-l88-firstno").mkdir()
        (tmp_path / "t1-vegeta-2_0ms").mkdir()  # started, never finished: no reading beside it
        found = tr._staircase_from(str(tmp_path), "vegeta")
        assert sorted(added for added, _ in found) == [0.0, 0.1, 1.5]

    def test_another_tools_runs_in_the_same_folder_are_left_alone(self, tmp_path):
        for name in ("t1-vegeta-0ms", "t1-hey-0ms"):
            folder = tmp_path / name
            folder.mkdir()
            (folder / "reading.json").write_text(
                json.dumps(self.rung(3.0, 0.001)), encoding="utf-8")
        assert len(tr._staircase_from(str(tmp_path), "hey")) == 1


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

    def staircase_at(self, tmp_path, avgs):
        for name, avg in avgs:
            folder = tmp_path / name
            folder.mkdir()
            (folder / "reading.json").write_text(json.dumps(
                {"reported_ms": {"avg": avg}, "steps_ms": {"avg": 0.001}, "step_ms": 0.001}),
                encoding="utf-8")

    def test_it_reads_a_whole_staircase_and_says_the_smallest_step(self, tmp_path):
        self.staircase_at(tmp_path, [("t1-hey-0ms", 3.0), ("t1-hey-0_1ms", 3.1)])
        code, said = self.run(["staircase", "--tool", "hey", "--dir", str(tmp_path)])
        assert code == 0 and json.loads(said)["smallest_reported_ms"] == 0.1

    def test_a_staircase_the_tool_never_answered_leaves_with_one(self, tmp_path):
        self.staircase_at(tmp_path, [("t1-hey-0ms", 3.0), ("t1-hey-0_1ms", 3.0)])
        where = tmp_path / "step.json"
        code, _ = self.run(["staircase", "--tool", "hey", "--dir", str(tmp_path),
                            "--out", str(where)])
        assert code == 1
        assert json.loads(where.read_text(encoding="utf-8"))["smallest_reported_ms"] is None
