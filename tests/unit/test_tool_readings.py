"""Reading each tool's own output, including the rounding the tools block exists to find.

The danger in a reader like this is tidiness: a parser that normalises a tool's answer destroys
the finding. hey printing four decimals of a second cannot report a difference below 0.1 ms, and
that ceiling has to survive into the reading, not be smoothed away. So these tests hold the
numbers *and* the step the tool's own printing puts under them.
"""
import base64
import io
import json
import os
import struct
import sys
import zlib

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

# What k6 printed on 24 September with no URL: sudo had cleared the environment it came through.
# Every iteration failed at once, so there is no request metric, and nothing crossed the wire.
K6_NO_REQUEST = """     data_received..................: 0 B     0 B/s
     data_sent......................: 0 B     0 B/s
     iteration_duration.............: avg=9.93µs min=7.44µs med=8.93µs p(99)=21.54µs max=31.86ms
     iterations.....................: 4895826 81596.947151/s
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

    def test_hey_is_read_as_it_prints_and_not_as_its_documentation_shows_it(self):
        """The fixture above was written from hey's documentation, one percent sign. The tool
        prints two, and on 25 September none of its percentiles had been read from any real run.
        These lines are from its T4 run on the first x86 pair."""
        printed = ("Summary:\n  Average:\t0.0009 secs\n\nLatency distribution:\n"
                   "  10%% in 0.0008 secs\n  50%% in 0.0008 secs\n  99%% in 0.0020 secs\n")
        got = tr.read_tool("hey", printed)
        assert got["reported_ms"]["p50"] == pytest.approx(0.8)
        assert got["reported_ms"]["p99"] == pytest.approx(2.0)

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

    @staticmethod
    def steps(values, figure="p50"):
        return [(added, {"reported_ms": {figure: value}})
                for added, value in zip((0.0, 0.5, 1.0, 1.5, 2.0), values)]

    def test_t1s_slope_is_one_for_a_round_trip(self):
        got = tr.slope_against_delay(self.steps((0.80, 1.30, 1.80, 2.30, 2.80)), "vegeta")
        assert got["slope"] == pytest.approx(1.0) and got["crossings"] == 1
        assert got["measured_the_path"] is True

    def test_and_two_for_a_send_an_acknowledgement_and_a_fetch(self):
        got = tr.slope_against_delay(self.steps((1.0, 2.0, 3.0, 4.0, 5.0)), "kafka-end-to-end")
        assert got["slope"] == pytest.approx(2.0) and got["crossings"] == 2
        assert got["measured_the_path"] is True

    def test_a_staircase_that_did_not_measure_the_path_is_said_to_be_one(self):
        """k6 on 24 September, which had made no request: 9 microseconds at every step."""
        got = tr.slope_against_delay(self.steps((0.0089, 0.0090, 0.0089, 0.0091, 0.0090)), "k6")
        assert got["slope"] == pytest.approx(0.0, abs=1e-3)
        assert got["measured_the_path"] is False

    def test_a_round_trip_read_twice_over_is_flagged_too(self):
        assert tr.slope_against_delay(self.steps((1.0, 2.0, 3.0, 4.0, 5.0)),
                                      "vegeta")["measured_the_path"] is False

    def test_it_takes_the_average_where_there_is_no_median(self):
        got = tr.slope_against_delay(self.steps((0.8, 1.3, 1.8, 2.3, 2.8), "avg"), "hey")
        assert got["figure"] == "avg" and got["measured_the_path"] is True

    def test_too_few_steps_or_one_delay_give_no_slope(self):
        assert tr.slope_against_delay(self.steps((0.8, 1.3)), "vegeta")["slope"] is None
        flat = [(1.0, {"reported_ms": {"p50": v}}) for v in (1.0, 1.1, 1.2)]
        assert tr.slope_against_delay(flat, "vegeta")["measured_the_path"] is None

    def test_k6_that_made_no_request_reported_nothing(self):
        """D25-3. What k6 printed on the first x86 pair on 24 September, run through sudo with its
        URL in an environment sudo had cleared: no request metric, because no request left, and
        an iteration time of nine microseconds, which is how long failing on "invalid URL" takes.
        The reader used to fall back to that line and report it as the latency."""
        got = tr.read_tool("k6", K6_NO_REQUEST)
        assert got["reported_ms"] == {}, "the time a failure took is not a latency"

    def test_k6_that_sent_no_byte_reported_nothing_whatever_else_it_printed(self):
        """A request metric beside zero bytes sent is still a run that measured nothing."""
        text = K6 + "     data_sent......................: 0 B 0 B/s\n"
        assert tr.read_tool("k6", text)["reported_ms"] == {}

    def test_k6_that_sent_something_is_read(self):
        text = K6 + "     data_sent......................: 51 kB 850 B/s\n"
        assert tr.read_tool("k6", text)["reported_ms"]["avg"] == pytest.approx(3.41)

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


# Freeze 30's five, each fixture cut from what the tool printed in the pilot of 9 October on the
# first x86 pair (runs/azure/collected/matched/pilot_v33_20261009T203142Z): lines kept as they
# came, the rest of the run's log left out.

PULSAR = (
    "2026-10-09T20:21:38,968+0000 [main] INFO  org.apache.pulsar.testclient.PerformanceConsumer"
    " - Throughput received:     402 msg --- 40.085  msg/s --- 0.157 Mbit/s  --- Latency: mean:"
    " 4.328 ms - med: 4 - 95pct: 6 - 99pct: 19 - 99.9pct: 42 - 99.99pct: 42 - Max: 42 {}\n"
    "2026-10-09T20:21:48,975+0000 [main] INFO  org.apache.pulsar.testclient.PerformanceConsumer"
    " - ------------------- DONE ----------------------- {}\n"
    "2026-10-09T20:21:48,976+0000 [perf-client-shutdown] INFO  org.apache.pulsar.testclient."
    "PerformanceConsumer - Aggregated throughput stats --- 500 records received --- 16.645 msg/s"
    " --- 0.065 Mbit/s --- AckRate: 16.64474808009164  msg/s --- ack failed 0 msg {}\n"
    "2026-10-09T20:21:48,983+0000 [perf-client-shutdown] INFO  org.apache.pulsar.testclient."
    "PerformanceConsumer - Aggregated latency stats --- Latency: mean: 4.214 ms - med: 4 - 95pct:"
    " 5 - 99pct: 10 - 99.9pct: 42 - 99.99pct: 42 - 99.999pct: 42 - Max: 42 {}\n")

EMQTT = (
    "Start with 1 workers, addrs pool size: 1 and req interval: 10 ms \n"
    "\n"
    "1s sub total=1 rate=0.99/sec\n"
    "1s connect_succ total=1 rate=0.99/sec\n"
    "5s publish_latency avg=1ms\n"
    "5s recv total=2 rate=0.40/sec\n"
    "6s publish_latency avg=1ms\n"
    "6s recv total=52 rate=50.00/sec\n"
    "15s publish_latency avg=1ms\n"
    "15s recv total=500 rate=48.00/sec\n"
    "# emqtt-bench's /metrics, read at the end of the run\n"
    "publish_latency 500\n"
    "recv 500\n"
    'e2e_latency_bucket{le="1"} 500\n'
    'e2e_latency_bucket{le="5"} 500\n'
    'e2e_latency_bucket{le="+Inf"} 500\n'
    "e2e_latency_count 500\n"
    "e2e_latency_sum 500\n")

OMB = (
    "20:25:51.916 [main] INFO DistributedWorkersEnsemble - Workers list - producers:"
    " [http://127.0.0.1:8180]\n"
    "20:25:51.916 [main] INFO DistributedWorkersEnsemble - Workers list - consumers:"
    " http://127.0.0.1:8182\n"
    "20:26:55.800 [main] INFO Benchmark - Writing test result into"
    " /home/ubuntu/pilot33/p_omb/result_dist.json\n"
    "# the benchmark's result file\n"
    "{\n"
    '  "workload" : "sbl-tools",\n'
    '  "driver" : "Kafka",\n'
    '  "aggregatedEndToEndLatencyQuantiles" : {\n'
    '    "91.3502806206669" : 2.0,\n'
    '    "98.8114889402443" : 3.0,\n'
    '    "99.70287223506108" : 4.0,\n'
    '    "100.0" : 12.0\n'
    "  },\n"
    '  "aggregatedEndToEndLatencyAvg" : 2.1066358534169694,\n'
    '  "aggregatedEndToEndLatency50pct" : 2.0,\n'
    '  "aggregatedEndToEndLatency99pct" : 4.0,\n'
    '  "aggregatedEndToEndLatencyMax" : 12.0\n'
    "}\n")

YCSB = (
    "[OVERALL], RunTime(ms), 10016\n"
    "[OVERALL], Throughput(ops/sec), 49.92012779552716\n"
    "[READ], Operations, 500\n"
    "[READ], AverageLatency(us), 667.286\n"
    "[READ], MinLatency(us), 599\n"
    "[READ], MaxLatency(us), 5551\n"
    "[READ], 50thPercentileLatency(us), 655\n"
    "[READ], 99thPercentileLatency(us), 792\n"
    "[READ], Return=OK, 500\n")

NATS_BENCH = (
    "20:28:22 Starting Core NATS service requester benchmark [clients=1, duration=10.00s,"
    " msg-size=512 B, msgs=500, sleep=0s, subject=sbl.bench, throughput=50]\n"
    "20:28:22 [1] Starting Core NATS service requester, requesting 500 messages\n\n"
    "NATS Core NATS service requester stats: 49 msgs/sec ~ 25 KiB/sec ~ min: 1,194.58us ~ avg:"
    " 1,267.59us ~ max: 3,132.66us ~ P50: 1,260.20us ~ P90: 1,290.43us ~ P99: 1,338.33us ~"
    " P99.9: 3,132.66us\n")


class TestFreeze30sFiveTools:
    """The five tools the plan registered and version 15 left unrun, read from what each printed
    in the pilot. Each reading keeps the step the tool's own record puts under its figures."""

    def test_pulsar_perf_reads_its_closing_line_and_not_a_running_one(self):
        got = tr.read_tool("pulsar-perf", PULSAR)
        assert got["reported_ms"] == {"avg": pytest.approx(4.214), "p50": 4.0, "p99": 10.0,
                                      "max": 42.0}
        assert got["steps_ms"]["avg"] == pytest.approx(0.001)
        assert got["steps_ms"]["p50"] == 1.0, "every percentile is a whole millisecond"

    def test_pulsar_perf_counts_what_arrived_and_says_nothing_of_what_it_kept(self):
        """Its count is every message received, the refused ones among them."""
        got = tr.read_tool("pulsar-perf", PULSAR)
        assert got["received"] == 500 and got["kept"] is None

    def test_pulsar_perf_without_its_closing_lines_reads_nothing(self):
        got = tr.read_tool("pulsar-perf", PULSAR.split("Aggregated")[0])
        assert got["reported_ms"] == {} and got["received"] is None

    def test_pulsar_perf_says_what_it_kept_from_the_histogram_file_it_writes(self):
        text = PULSAR + hdr_log([0, 0, 0, 0, 120, 280], [0, 0, 0, 0, 60, 40])
        got = tr.read_tool("pulsar-perf", text)
        assert got["kept"] == 500 and got["received"] == 500
        assert got["reported_ms"]["avg"] == pytest.approx(4.214)

    def test_pulsar_perfs_empty_histogram_prints_zeros_that_are_not_measurements(self):
        """The audit's finding (apache/pulsar#13250): an empty histogram prints a mean of 0.000
        and every percentile as 0. Where its file shows it kept nothing, there is no reading."""
        zeros = PULSAR.replace("mean: 4.214 ms - med: 4 - 95pct: 5 - 99pct: 10 - 99.9pct: 42"
                               " - 99.99pct: 42 - 99.999pct: 42 - Max: 42",
                               "mean: 0.000 ms - med: 0 - 95pct: 0 - 99pct: 0 - 99.9pct: 0"
                               " - 99.99pct: 0 - 99.999pct: 0 - Max: 0")
        got = tr.read_tool("pulsar-perf", zeros + hdr_log([], []))
        assert got["reported_ms"] == {} and got["kept"] == 0 and got["received"] == 500

    def test_pulsar_perfs_zeros_are_read_where_its_file_shows_it_kept_them(self):
        zeros = PULSAR.replace("mean: 4.214 ms - med: 4", "mean: 0.000 ms - med: 0")
        got = tr.read_tool("pulsar-perf", zeros + hdr_log([500]))
        assert got["kept"] == 500 and got["reported_ms"]["avg"] == 0.0

    @pytest.mark.parametrize("line", ["0.1,10.0,4.0,not base64 at all!",
                                      "0.1,10.0,4.0," + base64.b64encode(b"short").decode(),
                                      "0.1,10.0,4.0," + base64.b64encode(
                                          struct.pack(">ii", 0x1c849314, 4) + b"bad!").decode()])
    def test_a_histogram_file_that_cannot_be_read_counts_nothing_and_hides_nothing(self, line):
        got = tr.read_tool("pulsar-perf", PULSAR + tr.PULSAR_HISTOGRAM + "\n" + line + "\n")
        assert got["kept"] is None and got["reported_ms"]["p99"] == 10.0, \
            "the figures stand as printed when the file cannot say otherwise"


def _varint(n):
    """HdrHistogram's ZigZag LEB128 for one count, or a run of empty buckets as a negative."""
    v = n * 2 if n >= 0 else -n * 2 - 1
    out = bytearray()
    for i in range(9):
        if i == 8:
            out.append(v & 0xFF)
            break
        byte, v = v & 0x7F, v >> 7
        out.append(byte | (0x80 if v else 0))
        if not v:
            break
    return bytes(out)


def hdr_encode(counts, inner_cookie=0x1c849313):
    """One histogram as an HdrHistogram log writes it: counts by bucket, runs of empty ones as
    a negative, the V2 header, compressed, then base64."""
    payload, zeros = bytearray(), 0
    for count in counts:
        if count == 0:
            zeros += 1
            continue
        if zeros:
            payload += _varint(-zeros)
            zeros = 0
        payload += _varint(count)
    inner = struct.pack(">iiiiqqd", inner_cookie, len(payload), 0, 3, 1, 3600000000, 1.0) \
        + bytes(payload)
    squeezed = zlib.compress(inner)
    return base64.b64encode(struct.pack(">ii", 0x1c849314, len(squeezed)) + squeezed).decode()


def hdr_log(*intervals):
    """pulsar-perf's histogram file as the runner writes it after the log: a legend, then one
    interval a line."""
    lines = [tr.PULSAR_HISTOGRAM, "#[Histogram log format version 1.3]",
             '"StartTimestamp","Interval_Length","Interval_Max","Interval_Compressed_Histogram"']
    lines += ["%.3f,10.000,42.000,%s" % (10.0 * i, hdr_encode(c)) for i, c in enumerate(intervals)]
    return "\n" + "\n".join(lines) + "\n"


#: pulsar-perf's own histogram file from the shakedown of 9 October (host-pulsar-perf in
#: runs/azure/collected/matched/shakedown_v33_20261009T213112Z), written by its Java HdrHistogram
#: library, from a run at no offset in which the consumer said "1500 records received".
PULSAR_HLOG = (
    "#[Histogram log format version 1.3]\n"
    '"StartTimestamp","Interval_Length","Interval_Max","Interval_Compressed_Histogram"\n'
    "1791580211.996,10.611,0.000,HISTFAAAAB942pNpmSzMwMDAyAABrFAazDeun8Fg/wEqAgBL/APH\n"
    "1791580222.607,10.050,0.000,HISTFAAAAC542pNpmSzMwMDAzwABrFCaEUQY189gsP8AlehgXsMiw8XAwszCy8TNBACVogVi\n"
    "1791580232.657,10.019,0.000,HISTFAAAACZ42pNpmSzMwMDAzgABrFCaEUQY189gsP8AlfjA/IKZjwUAbTEFwg==\n"
    "1791580242.676,10.005,0.000,HISTFAAAACd42pNpmSzMwMDAwQABrFCaEUQY189gsP8AlZjFsouZh4UFAG/gBUI=\n"
    "1791580252.681,10.005,0.000,HISTFAAAAB942pNpmSzMwMDAyAABrFAazDeun8Fg/wEqAgBL/APH\n"
    "1791580262.686,10.013,0.000,HISTFAAAAB942pNpmSzMwMDAyAABrFAazDeun8Fg/wEqAgBL/APH\n")


class TestHdrHistogramCounts:
    """The count pulsar-perf's histogram file holds, decoded as HdrHistogram's Java code encodes."""

    def test_the_tools_own_file_counts_every_message_of_a_run_nothing_could_drop(self):
        """Not decoded by our own encoder: written by the Java library, and checked against the
        tool's own count of what it received, which at no offset is everything it kept."""
        counts = [tr.hdr_count(line.rsplit(",", 1)[1]) for line in PULSAR_HLOG.splitlines()
                  if not line.startswith(("#", '"'))]
        assert counts == [0, 499, 501, 500, 0, 0] and sum(counts) == 1500
        text = PULSAR.replace("500 records received", "1500 records received")
        got = tr.read_tool("pulsar-perf", text + tr.PULSAR_HISTOGRAM + "\n" + PULSAR_HLOG)
        assert got["kept"] == got["received"] == 1500

    def test_a_histogram_counts_its_buckets_and_skips_its_empty_runs(self):
        assert tr.hdr_count(hdr_encode([0, 0, 0, 7, 0, 5, 1])) == 13

    def test_an_empty_histogram_counts_nothing(self):
        assert tr.hdr_count(hdr_encode([])) == 0

    def test_a_count_needing_all_nine_bytes_is_read_whole(self):
        assert tr.hdr_count(hdr_encode([2 ** 57])) == 2 ** 57

    @pytest.mark.parametrize("encoded", [
        base64.b64encode(struct.pack(">ii", 0x1c849303, 0)).decode(),
        hdr_encode([1], inner_cookie=0x1c849304)])
    def test_anything_but_a_compressed_v2_histogram_is_refused(self, encoded):
        with pytest.raises(ValueError):
            tr.hdr_count(encoded)

    def test_emqtt_bench_takes_its_average_from_the_histogram_that_keeps_every_sample(self):
        got = tr.read_tool("emqtt-bench", EMQTT)
        assert got["reported_ms"] == {"avg": pytest.approx(1.0)}
        assert got["steps_ms"]["avg"] == pytest.approx(1.0 / 500), \
            "a sum of whole milliseconds over its count"
        assert got["kept"] == 500 and got["received"] == 500

    def test_emqtt_bench_keeps_its_consoles_averages_as_printed(self):
        assert tr.read_tool("emqtt-bench", EMQTT)["console_avg_ms"] == [1, 1, 1]

    def test_emqtt_bench_reads_a_negative_sum(self):
        """Under T2's offset the histogram's sum goes below zero; that is what it is for."""
        text = EMQTT.replace("e2e_latency_sum 500", "e2e_latency_sum -1500")
        assert tr.read_tool("emqtt-bench", text)["reported_ms"]["avg"] == pytest.approx(-3.0)

    @pytest.mark.parametrize("text", [
        EMQTT.split(tr.EMQTT_METRICS)[0],
        EMQTT.replace("e2e_latency_count 500", "e2e_latency_count 0"),
        "5s publish_latency avg=1ms\n" + tr.EMQTT_METRICS + "\ne2e_latency_count 3\n",
    ])
    def test_emqtt_bench_without_a_whole_histogram_reads_no_average(self, text):
        """No metrics read, an empty histogram, or a count with no sum: no average either way."""
        assert tr.read_tool("emqtt-bench", text)["reported_ms"] == {}

    def test_omb_reads_its_result_file_and_steps_its_percentiles_in_milliseconds(self):
        got = tr.read_tool("omb", OMB)
        assert got["reported_ms"] == {"avg": pytest.approx(2.1066358534169694), "p50": 2.0,
                                      "p99": 4.0, "max": 12.0, "min": 2.0}
        assert got["steps_ms"]["p50"] == got["steps_ms"]["min"] == 1.0, \
            "whole milliseconds by construction, whatever digits the file gives them"
        assert got["steps_ms"]["avg"] < 1e-9 and got["kept"] is None

    @pytest.mark.parametrize("text", [
        OMB.split(tr.OMB_RESULT)[0],
        OMB.split(tr.OMB_RESULT)[0] + tr.OMB_RESULT + "\nno file was written\n",
        OMB.split(tr.OMB_RESULT)[0] + tr.OMB_RESULT + "\n{ this is not json\n",
    ])
    def test_omb_without_a_result_file_reads_nothing(self, text):
        assert tr.read_tool("omb", text)["reported_ms"] == {}

    def test_omb_reads_only_the_file_and_not_what_follows_it(self):
        assert tr.read_tool("omb", OMB + "benchmark exit 0\n")["reported_ms"]["p99"] == 4.0

    def test_omb_takes_what_the_file_holds_and_leaves_out_what_it_does_not(self):
        text = (tr.OMB_RESULT + '\n{"aggregatedEndToEndLatencyAvg": 3, '
                '"aggregatedEndToEndLatency50pct": null, "aggregatedEndToEndLatencyQuantiles": '
                '{"100.0": "x"}}\n')
        assert tr.read_tool("omb", text)["reported_ms"] == {"avg": 3.0}

    def test_omb_whose_histogram_recorded_nothing_has_no_figures(self):
        """Its filter leaves nothing when every difference is at or below zero, and an empty
        histogram reports a mean, percentiles and a maximum of 0.0 that are not measurements."""
        text = (tr.OMB_RESULT + '\n{"aggregatedEndToEndLatencyAvg": 0.0, '
                '"aggregatedEndToEndLatency50pct": 0.0, "aggregatedEndToEndLatency99pct": 0.0, '
                '"aggregatedEndToEndLatencyMax": 0.0, "aggregatedEndToEndLatencyQuantiles": {}}\n')
        got = tr.read_tool("omb", text)
        assert got["reported_ms"] == {} and got["kept"] == 0

    def test_omb_with_quantiles_in_another_shape_has_no_minimum(self):
        text = (tr.OMB_RESULT + '\n{"aggregatedEndToEndLatencyAvg": 2.5, '
                '"aggregatedEndToEndLatencyQuantiles": [2.0, 3.0]}\n')
        assert tr.read_tool("omb", text)["reported_ms"] == {"avg": 2.5}

    def test_ycsb_reads_its_reads_in_microseconds(self):
        got = tr.read_tool("ycsb", YCSB)
        assert got["reported_ms"] == {"avg": pytest.approx(0.667286), "min": pytest.approx(0.599),
                                      "max": pytest.approx(5.551), "p50": pytest.approx(0.655),
                                      "p99": pytest.approx(0.792)}
        assert got["steps_ms"]["min"] == pytest.approx(0.001)
        assert got["steps_ms"]["avg"] == pytest.approx(1e-6)
        assert got["kept"] == 500

    def test_ycsb_reads_nothing_from_a_run_that_did_no_reads(self):
        got = tr.read_tool("ycsb", "[OVERALL], RunTime(ms), 10016\n")
        assert got["reported_ms"] == {} and got["kept"] is None

    def test_nats_bench_reads_microseconds_with_their_thousands_separators(self):
        got = tr.read_tool("nats-bench", NATS_BENCH)
        assert got["reported_ms"] == {"min": pytest.approx(1.19458), "avg": pytest.approx(1.26759),
                                      "max": pytest.approx(3.13266), "p50": pytest.approx(1.2602),
                                      "p99": pytest.approx(1.33833)}
        assert got["steps_ms"]["p99"] == pytest.approx(1e-5)

    def test_nats_bench_does_not_read_its_p99_9_as_its_p99(self):
        text = NATS_BENCH.replace("P99: 1,338.33us ~ ", "")
        assert "p99" not in tr.read_tool("nats-bench", text)["reported_ms"]

    def test_nats_bench_reads_nothing_from_a_run_with_no_stats(self):
        assert tr.read_tool("nats-bench", NATS_BENCH.split("\n\n")[0])["reported_ms"] == {}

    def test_each_of_the_five_crosses_the_delayed_direction_once(self):
        """D33-5: a reply to a request, or a message delivered to the process that subtracts."""
        staircase = [(0.0, {"reported_ms": {"avg": 1.0}}), (1.0, {"reported_ms": {"avg": 2.0}}),
                     (2.0, {"reported_ms": {"avg": 3.0}})]
        for tool in ("omb", "pulsar-perf", "emqtt-bench", "ycsb", "nats-bench"):
            assert tr.slope_against_delay(staircase, tool)["crossings"] == 1


#: Xinfra Monitor's reporter from the pilot of 11 October (runs/azure/collected/matched/pilot_v35,
#: t4-xinfra-monitor): its report before the first record, its first report after it, and its last
#: report of the run, each as the tool printed it.
XINFRA = (
    "[2026-10-11 01:51:55,458] INFO ==============================================================\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-delay-ms-avg=NaN\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-delay-ms-max=NaN\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-delay-ms-99th=NaN\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-delay-ms-999th=NaN\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-consumed-total=0.0\n"
    " (com.linkedin.xinfra.monitor.services.DefaultMetricsReporterService)\n"
    "[2026-10-11 01:51:56,458] INFO ==============================================================\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-delay-ms-avg=4.3125\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-delay-ms-max=20.0\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-delay-ms-99th=19.99200319872051\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-delay-ms-999th=19.99200319872051\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-consumed-total=16.0\n"
    " (com.linkedin.xinfra.monitor.services.DefaultMetricsReporterService)\n"
    "[2026-10-11 01:53:41,458] INFO ==============================================================\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-delay-ms-avg=1.2757158006362672\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-delay-ms-max=4.0\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-delay-ms-99th=2.998800479808077\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-delay-ms-999th=3.9984006397441023\n"
    "kmf.services:name=single-cluster-monitor,type=consume-service:records-consumed-total=4944.0\n"
    " (com.linkedin.xinfra.monitor.services.DefaultMetricsReporterService)\n")

#: Strimzi Canary against the Kafka 3.9.1 broker in the second pilot (pilot_v35b,
#: t4-strimzi-canary): the two lines of its /metrics the reader takes, among a few it does not, and
#: its log's first three lines; the last four log lines are in the same shape with other durations.
CANARY = (
    "# the canary's /metrics, read at the end of the run\n"
    "# HELP strimzi_canary_records_consumed_latency Records end-to-end latency in milliseconds\n"
    "# TYPE strimzi_canary_records_consumed_latency histogram\n"
    'strimzi_canary_records_consumed_latency_bucket{clientid="sbl-canary-1791684753",'
    'partition="0",le="5"} 3352\n'
    'strimzi_canary_records_consumed_latency_sum{clientid="sbl-canary-1791684753",partition="0"} 4432\n'
    'strimzi_canary_records_consumed_latency_count{clientid="sbl-canary-1791684753",partition="0"} 3360\n'
    'strimzi_canary_records_produced_latency_sum{clientid="sbl-canary-1791684753",partition="0"} 3061\n'
    "# the canary's log\n"
    "I1011 02:12:36.391796   18864 consumer.go:276] Message received: value={ProducerID:sbl-canary-"
    "1791684753, MessageID:1, Timestamp:1791684756242}, partition=0, offset=0, duration=149 ms\n"
    "I1011 02:12:36.391832   18864 consumer.go:276] Message received: value={ProducerID:sbl-canary-"
    "1791684753, MessageID:2, Timestamp:1791684756298}, partition=0, offset=1, duration=93 ms\n"
    "I1011 02:12:36.391841   18864 consumer.go:276] Message received: value={ProducerID:sbl-canary-"
    "1791684753, MessageID:3, Timestamp:1791684756320}, partition=0, offset=2, duration=71 ms\n"
    + "".join("I1011 02:12:37.%06d   18864 consumer.go:276] Message received: value={ProducerID:"
              "sbl-canary-1791684753, MessageID:%d, Timestamp:%d}, partition=0, offset=%d, "
              "duration=%d ms\n" % (100000 + i, 4 + i, 1791684757000 + 20 * i, 3 + i, d)
              for i, d in enumerate((1, 1, 2, 0))))

#: Trogdor in the second pilot (pilot_v35b, t4-trogdor), the consume task's status once it ended.
TROGDOR = """# trogdor's consume task
Task consume of type org.apache.kafka.trogdor.workload.ConsumeBenchSpec is DONE. FINISHED at 2026-10-11T02:15:30.592Z after 1m30s
Status: {
  "consumer.consume-0" : {
    "assignedPartitions" : [ "sbl-trogdor-1791684823-0" ],
    "totalMessagesReceived" : 3000,
    "totalBytesReceived" : 1548000,
    "averageMessageSizeBytes" : 516,
    "averageLatencyMs" : 112.18567,
    "p50LatencyMs" : 100,
    "p95LatencyMs" : 101,
    "p99LatencyMs" : 101,
    "recordProcessorStatus" : {
      "averageLatencyMs" : 2.1416667,
      "p50LatencyMs" : 2,
      "p95LatencyMs" : 3,
      "p99LatencyMs" : 3
    }
  }
}

# trogdor's produce task
Task produce of type org.apache.kafka.trogdor.workload.ProduceBenchSpec is DONE. FINISHED at 2026-10-11T02:15:07.632Z after 1m1s
Status: {
  "totalSent" : 3000,
  "averageLatencyMs" : 1.5553334,
  "p50LatencyMs" : 2,
  "p95LatencyMs" : 2,
  "p99LatencyMs" : 2,
  "transactionsCommitted" : 0
}
"""


def _stream_lines(first, last, eaten, figures):
    return "".join("%d, published 0 msg/s, confirmed 0 msg/s, consumed %d msg/s, latency "
                   "median/75th/95th/99th %s ms, chunk size 1\n" % (s, eaten, figures)
                   for s in range(first, last + 1))


#: Stream PerfTest's consumer instance in the third pilot (pilot_v35c, t4-stream-perftest): ten
#: seconds before the producer started, consuming nothing and printing zeros, then a line a second
#: as it printed them; the producer's own lines come before the runner's line and are not read.
STREAM = ("53, published 50 msg/s, confirmed 50 msg/s, consumed 0 msg/s, latency "
          "median/75th/95th/99th 0/0/0/0 ms, chunk size 0\n"
          + "# the stream consumer instance\n"
          + _stream_lines(1, 10, 0, "0/0/0/0")
          + _stream_lines(11, 12, 50, "2/2/2/2")
          + _stream_lines(13, 61, 50, "1/2/2/2")
          + _stream_lines(62, 62, 50, "1/2/2/5")
          + _stream_lines(63, 70, 50, "1/1/2/2"))


def _stream_metrics(count, total_s, eaten):
    return ("# the stream consumer's /metrics, read once the producer had finished\n"
            "# HELP rabbitmq_stream_latency_seconds message latency\n"
            "# TYPE rabbitmq_stream_latency_seconds summary\n"
            'rabbitmq_stream_latency_seconds{quantile="0.5",} 0.001\n'
            "rabbitmq_stream_latency_seconds_count %s\n"
            "rabbitmq_stream_latency_seconds_sum %s\n"
            "rabbitmq_stream_consumed_total %s\n" % (count, total_s, eaten))


class TestFreeze32sFourTools:
    """The four message tools of the reading of 10 and 11 October, read from what each printed in
    the pilots of 11 October. Each reading keeps the step its own record puts under its figures."""

    def test_xinfra_reads_the_runs_last_minute_and_not_its_first_report(self):
        got = tr.read_tool("xinfra-monitor", XINFRA)
        assert got["reported_ms"] == {"avg": pytest.approx(1.2757158006362672), "max": 4.0,
                                      "p99": pytest.approx(2.998800479808077)}
        assert got["received"] == 4944 and got["kept"] is None

    def test_xinfra_steps_its_percentile_by_its_bucket_and_not_by_its_digits(self):
        """2.998800479808077 is the bucket of 3 ms at the width of 5,000 over 5,002 ms."""
        steps = tr.read_tool("xinfra-monitor", XINFRA)["steps_ms"]
        assert steps["p99"] == steps["max"] == 1.0
        assert steps["avg"] < 1e-9, "the average keeps the step of the digits it prints"

    def test_xinfra_before_its_first_record_reads_nothing(self):
        got = tr.read_tool("xinfra-monitor", XINFRA.split("[2026-10-11 01:51:56,458]")[0])
        assert got["reported_ms"] == {} and got["steps_ms"] == {} and got["received"] == 0

    def test_xinfra_that_printed_no_report_counts_nothing(self):
        got = tr.read_tool("xinfra-monitor", "[2026-10-11 01:51:52,264] INFO Creating AdminClient.\n")
        assert got["reported_ms"] == {} and got["received"] is None

    def test_the_canary_takes_its_average_from_its_histogram(self):
        got = tr.read_tool("strimzi-canary", CANARY)
        assert got["reported_ms"]["avg"] == pytest.approx(4432 / 3360)
        assert got["steps_ms"]["avg"] == pytest.approx(1 / 3360), \
            "a sum of whole milliseconds over its count"
        assert got["histogram_count"] == 3360

    def test_the_canary_reads_its_percentiles_from_its_log_line_by_line(self):
        got = tr.read_tool("strimzi-canary", CANARY)
        assert got["logged"] == 7
        assert {k: got["reported_ms"][k] for k in ("min", "p50", "p99", "max")} == \
            {"min": 0.0, "p50": 2.0, "p99": 149.0, "max": 149.0}
        assert got["steps_ms"]["p50"] == got["steps_ms"]["min"] == 1.0

    def test_the_canary_reads_a_negative_duration_its_own_reader_skips(self):
        """tools/canary_latencies.py matches [0-9]+, which cannot match a minus sign."""
        text = CANARY.replace("duration=0 ms", "duration=-2 ms")
        assert tr.read_tool("strimzi-canary", text)["reported_ms"]["min"] == -2.0

    def test_a_canary_histogram_that_counted_nothing_gives_no_average(self):
        text = CANARY.replace('partition="0"} 3360', 'partition="0"} 0')
        got = tr.read_tool("strimzi-canary", text)
        assert "avg" not in got["reported_ms"] and got["histogram_count"] == 0

    def test_a_canary_with_metrics_and_no_log_has_its_average_alone(self):
        got = tr.read_tool("strimzi-canary", CANARY.split(tr.CANARY_LOG)[0])
        assert set(got["reported_ms"]) == {"avg"} and got["logged"] == 0

    def test_trogdor_reads_its_record_processor_and_not_consume_benchs_own_figures(self):
        """ConsumeBench's 112 ms is the wait between its batches, not a message's latency."""
        got = tr.read_tool("trogdor", TROGDOR)
        assert got["reported_ms"] == {"avg": pytest.approx(2.1416667), "p50": 2.0, "p99": 3.0}
        assert got["received"] == 3000
        assert got["steps_ms"]["p50"] == 1.0

    def test_trogdor_reads_the_zeros_it_puts_its_negatives_at(self):
        """With its consuming agent's clock 5 ms behind, in the second pilot."""
        text = (TROGDOR.replace('"averageLatencyMs" : 2.1416667', '"averageLatencyMs" : 0.044333335')
                .replace('"p50LatencyMs" : 2,\n      "p95LatencyMs" : 3,\n      "p99LatencyMs" : 3',
                         '"p50LatencyMs" : 0,\n      "p95LatencyMs" : 0,\n      "p99LatencyMs" : 0'))
        got = tr.read_tool("trogdor", text)
        assert got["reported_ms"] == {"avg": pytest.approx(0.044333335), "p50": 0.0, "p99": 0.0}

    def test_trogdor_asked_before_its_task_ended_reads_nothing(self):
        """As in the first pilot: ConsumeBench reports its status only once its task has ended."""
        text = ("# trogdor's consume task\nTask consume of type org.apache.kafka.trogdor.workload."
                "ConsumeBenchSpec is RUNNING. Started 2026-10-11T01:55:09.093Z; will stop after "
                "2m\nStatus: null\n\n" + TROGDOR.split("\n\n", 1)[1])
        got = tr.read_tool("trogdor", text)
        assert got["reported_ms"] == {} and got["received"] is None

    def test_stream_perftest_reads_the_consumer_and_leaves_out_its_idle_and_warm_up(self):
        """The ten seconds before the producer began print zeros, and are not seconds it timed."""
        got = tr.read_tool("stream-perftest", STREAM)
        assert got["reported_ms"] == {"p50": 1.0, "p99": 2.0}
        assert got["seconds"] == 70 and got["per_second"][10] == [11, 50, 2, 2]
        assert got["kept"] is None and got["received"] is None

    def test_stream_perftest_reads_its_average_and_what_it_kept_off_its_metrics(self):
        got = tr.read_tool("stream-perftest", STREAM + _stream_metrics("3000.0", "4.21", "3000.0"))
        assert got["reported_ms"]["avg"] == pytest.approx(4210 / 3000)
        assert got["steps_ms"]["avg"] == pytest.approx(1 / 3000)
        assert got["kept"] == got["received"] == 3000
        assert got["reported_ms"]["p50"] == 1.0

    def test_stream_perftest_that_kept_fewer_than_it_consumed_has_no_empty_second_read(self):
        """A second of four zeros may be a second it emptied; with fewer kept, it is not read."""
        text = (STREAM.replace(_stream_lines(13, 61, 50, "1/2/2/2"),
                               _stream_lines(13, 40, 50, "0/0/0/0") + _stream_lines(41, 61, 50, "3/4/4/4"))
                + _stream_metrics("1450.0", "4.93", "3000.0"))
        got = tr.read_tool("stream-perftest", text)
        assert got["kept"] == 1450 and got["received"] == 3000
        assert got["reported_ms"]["p50"] == 3.0, "the zeros of the emptied seconds are left out"

    def test_stream_perftest_that_kept_every_value_reads_a_zero_second_as_zeros(self):
        """Where nothing was dropped, four zeros can only be latencies of 0 ms."""
        text = (STREAM.replace(_stream_lines(13, 61, 50, "1/2/2/2"), _stream_lines(13, 61, 50, "0/0/0/0"))
                + _stream_metrics("3000.0", "0.0", "3000.0"))
        got = tr.read_tool("stream-perftest", text)
        assert got["reported_ms"] == {"avg": 0.0, "p50": 0.0, "p99": 0.0}

    def test_stream_perftest_that_kept_nothing_has_no_figures(self):
        """As in the third pilot, its consumer's clock 5 ms behind: zeros every second, none kept."""
        text = ("# the stream consumer instance\n" + _stream_lines(1, 10, 0, "0/0/0/0")
                + _stream_lines(11, 70, 50, "0/0/0/0") + _stream_metrics("0.0", "0.0", "3000.0"))
        got = tr.read_tool("stream-perftest", text)
        assert got["reported_ms"] == {} and got["kept"] == 0 and got["received"] == 3000

    def test_stream_perftest_with_a_count_and_no_consumed_total_judges_no_second_emptied(self):
        text = STREAM + _stream_metrics("3000.0", "4.21", "x").replace(
            "rabbitmq_stream_consumed_total x\n", "")
        got = tr.read_tool("stream-perftest", text)
        assert got["received"] is None and got["reported_ms"]["p50"] == 1.0

    def test_stream_perftest_without_the_runners_line_reads_the_whole_output(self):
        got = tr.read_tool("stream-perftest", STREAM.split("# the stream consumer instance\n")[1])
        assert got["reported_ms"] == {"p50": 1.0, "p99": 2.0}

    def test_each_of_the_four_crosses_the_delayed_direction_once(self):
        """D35-2: a record delivered to the process that subtracts."""
        staircase = [(0.0, {"reported_ms": {"avg": 1.0}}), (1.0, {"reported_ms": {"avg": 2.0}}),
                     (2.0, {"reported_ms": {"avg": 3.0}})]
        for tool in ("xinfra-monitor", "strimzi-canary", "trogdor", "stream-perftest"):
            assert tr.slope_against_delay(staircase, tool)["crossings"] == 1


def _ysb(written, seen=(5, 7)):
    """YSB's two files as the runner prints them after its run: updated.txt, then seen.txt, one
    integer a line, as its collection (core.clj:130-149) writes them."""
    return (tr.YSB_UPDATED + "\n" + "".join("%d\n" % v for v in written)
            + tr.YSB_SEEN + "\n" + "".join("%d\n" % v for v in seen))


class TestFreeze33sYsb:
    """The Yahoo Streaming Benchmark, read as the notebook it ships reads updated.txt."""

    def test_it_keeps_the_windows_at_or_above_ten_seconds_and_subtracts_them(self):
        got = tr.read_tool("ysb", _ysb([10000, 10400, 10950, 9800, 10210, 12000, -50]))
        assert got["windows_ms"] == [0, 210, 400, 950, 2000]
        assert got["kept"] == 5 and got["received"] == 7 and got["below_window"] == 2

    def test_its_figures_are_numpys_on_what_it_kept(self):
        """np.average 712.0, np.percentile 50 -> 400.0 and 99 -> 1958.0 on the same values."""
        got = tr.read_tool("ysb", _ysb([10000, 10400, 10950, 9800, 10210, 12000, -50]))
        assert got["reported_ms"] == {"avg": 712.0, "p50": 400.0, "p99": pytest.approx(1958.0),
                                      "min": 0.0, "max": 2000.0}
        assert got["steps_ms"]["avg"] == pytest.approx(0.2) and got["steps_ms"]["p99"] == 1.0

    def test_a_window_exactly_at_its_length_is_kept_as_zero(self):
        """Its filter is x >= window: it drops the negatives and keeps a zero."""
        got = tr.read_tool("ysb", _ysb([10000, 9999]))
        assert got["windows_ms"] == [0] and got["below_window"] == 1

    def test_a_run_whose_every_window_came_out_short_has_no_figures(self):
        got = tr.read_tool("ysb", _ysb([9500, 9990, -70646]))
        assert got["reported_ms"] == {} and got["kept"] == 0 and got["received"] == 3

    def test_a_run_that_wrote_no_file_counts_nothing_rather_than_zero(self):
        got = tr.read_tool("ysb", "Flink job submitted\n")
        assert got["kept"] is None and got["received"] is None and got["windows_ms"] == []

    def test_its_seen_counts_are_not_read_as_latencies(self):
        got = tr.read_tool("ysb", _ysb([10300], seen=(10500, 10600)))
        assert got["windows_ms"] == [300] and got["received"] == 1

    def test_every_written_window_is_kept_signed_for_ts_reference(self):
        """What YSB wrote, less the window, sign kept: the reference T2 predicts from (D36-3)."""
        got = tr.read_tool("ysb", _ysb([10000, 10400, 9700, 9300]))
        assert got["written_ms"] == [-700, -300, 0, 400] and got["windows_ms"] == [0, 400]


def _pkb(samples, failures=0, p50=24.0, p99=41.03):
    """PerfKit's metrics line, as latency_runner.py prints it with json.dumps when it ends."""
    import json
    mean = sum(samples) / len(samples) if samples else float("nan")
    return json.dumps({
        "e2e_latency_failure_counter": {"value": failures, "unit": "", "metadata": {}},
        "e2e_latency_mean": {"value": mean, "unit": "milliseconds", "metadata": {"samples": samples}},
        "e2e_latency_cold": {"value": samples[0] if samples else None, "unit": "milliseconds", "metadata": {}},
        "e2e_latency_p50": {"value": p50, "unit": "milliseconds", "metadata": {}},
        "e2e_latency_p99": {"value": p99, "unit": "milliseconds", "metadata": {}},
        "e2e_acknowledge_latency_mean": {"value": 30.0, "unit": "milliseconds", "metadata": {"samples": [30]}},
    })


class TestFreeze34sTools:
    """PerfKit's messaging benchmark, Stream PerfTest as one instance, and the canary's own log
    reader, read as freeze 34 reads them."""

    def test_pkb_reads_its_printed_figures_and_its_samples(self):
        text = "I1011 starting the run\n" + _pkb([25, 23, 24, 80]) + "\n"
        got = tr.read_tool("pkb", text)
        assert got["reported_ms"] == {"avg": 38.0, "p50": 24.0, "p99": pytest.approx(41.03),
                                      "min": 23.0, "max": 80.0}
        assert got["steps_ms"]["avg"] == pytest.approx(0.25) and got["steps_ms"]["min"] == 1.0
        assert got["kept"] == got["received"] == 4 and got["samples_ms"] == [25.0, 23.0, 24.0, 80.0]

    def test_pkb_keeps_a_value_below_zero_and_counts_its_failures(self):
        got = tr.read_tool("pkb", _pkb([25, -30, 24], failures=2))
        assert got["reported_ms"]["min"] == -30.0 and got["kept"] == 3
        assert got["received"] == 5 and got["failures"] == 2

    def test_pkb_reads_its_last_metrics_line_and_nothing_that_is_not_one(self):
        """Read from the end: a later line that is not JSON, or JSON of something else, is passed."""
        text = _pkb([10, 12]) + "\n" + "{not json\n" + '{"other": 1}\n' + "absl: done\n"
        assert tr.read_tool("pkb", text)["reported_ms"]["max"] == 12.0

    def test_pkb_without_its_metrics_line_reads_nothing(self):
        got = tr.read_tool("pkb", "Traceback (most recent call last):\n")
        assert got["reported_ms"] == {} and got["samples_ms"] == [] and got["kept"] is None

    def test_pkb_that_timed_nothing_has_no_figures(self):
        got = tr.read_tool("pkb", _pkb([], failures=100))
        assert got["reported_ms"] == {} and got["kept"] == 0 and got["received"] == 100

    def test_pkb_without_its_percentiles_still_reads_its_mean(self):
        import json
        line = json.loads(_pkb([10, 14]))
        del line["e2e_latency_p50"], line["e2e_latency_p99"]
        got = tr.read_tool("pkb", json.dumps(line))
        assert set(got["reported_ms"]) == {"avg", "min", "max"}

    def test_stream_perftest_as_one_instance_reads_as_two_do_under_its_own_name(self):
        got = tr.read_tool("stream-perftest-one", STREAM + _stream_metrics("3000.0", "4.21", "3000.0"))
        assert got["tool"] == "stream-perftest-one" and got["kept"] == 3000
        assert got["reported_ms"]["p50"] == 1.0

    def test_the_canary_counts_its_negative_durations_and_keeps_its_own_readers_average(self):
        text = (CANARY.replace("duration=0 ms", "duration=-48 ms")
                + "# the canary's own log reader on that log\n\nProducer Latency Average: \n1.1\n\n"
                  "E2E Latency Average: \n45.7\n")
        got = tr.read_tool("strimzi-canary", text)
        assert got["logged_negative"] == 1 and got["shipped_reader_avg"] == 45.7
        assert got["reported_ms"]["min"] == -48.0

    def test_a_canary_run_with_no_shipped_reader_output_has_no_such_average(self):
        got = tr.read_tool("strimzi-canary", CANARY)
        assert got["shipped_reader_avg"] is None and got["logged_negative"] == 0


class TestFreeze34sStepTest:
    """S1's one new reading: Xinfra Monitor's console under S1 carries kafka-clients' debug line
    for each value its percentiles pin to their floor (Percentiles.java:119-122 at 2.8.2)."""

    PINNED = ("[2026-10-11 13:00:01,123] DEBUG Received value {} which is less than min recordable"
              " value 0.0, will be pinned to the min value"
              " (org.apache.kafka.common.metrics.stats.Percentiles)\n")

    def test_each_value_pinned_to_the_floor_is_kept_beside_the_figures(self):
        got = tr.read_tool("xinfra-monitor",
                           XINFRA + self.PINNED.format("-18.0") + self.PINNED.format("-19.0"))
        assert got["pinned_below_ms"] == [-18.0, -19.0]
        assert got["reported_ms"]["p99"] == pytest.approx(2.998800479808077), \
            "the values it pinned do not move the percentile it prints"

    def test_a_run_without_the_line_pinned_nothing_it_said(self):
        assert tr.read_tool("xinfra-monitor", XINFRA)["pinned_below_ms"] == []

    def test_a_value_above_its_ceiling_is_not_read_as_one_below_its_floor(self):
        above = ("DEBUG Received value 6000.0 which is greater than max recordable value 5000.0,"
                 " will be pinned to the max value\n")
        assert tr.read_tool("xinfra-monitor", XINFRA + above)["pinned_below_ms"] == []


def _mqttb(runs, failures=0):
    """mqtt-benchmark's JSON results, as main.go marshals and indents them with tabs: one run per
    client and the totals, with the field names of its RunResults and TotalResults."""
    import json
    doc = {"runs": [{"id": i, "successes": n, "failures": f, "run_time": 60.0,
                     "msg_time_min": lo, "msg_time_max": hi, "msg_time_mean": mean,
                     "msg_time_std": 0.2, "msgs_per_sec": 1.0}
                    for i, (n, f, lo, hi, mean) in enumerate(runs)],
           "totals": {"ratio": 1.0, "successes": sum(r[0] for r in runs),
                      "failures": failures or sum(r[1] for r in runs), "total_run_time": 61.0,
                      "avg_run_time": 60.0, "msg_time_min": min(r[2] for r in runs),
                      "msg_time_max": max(r[3] for r in runs),
                      "msg_time_mean_avg": sum(r[4] for r in runs) / len(runs),
                      "msg_time_mean_std": 0.0, "total_msgs_per_sec": 50.0,
                      "avg_msgs_per_sec": 1.0}}
    return json.dumps(doc, indent="\t")


SARAMA = ("{n} records sent, 50.0 records/sec (0.02 MiB/sec ingress, 0.03 MiB/sec egress), "
          "{avg} ms avg latency, 0.5 ms stddev, {p50} ms 50th, 1.0 ms 75th, 1.0 ms 95th, "
          "{p99} ms 99th, 3.0 ms 99.9th, 0 total req. in flight\n")


def _sbk_total(records=3000, invalid=0, unit="ms", avg="0.6", low="0", high="12",
               p50="1", p99="2"):
    """SBK's total line as its console logger printed it in the pilot of 11 October: the time,
    Total and its prefix, its writers and readers, its request and timeout counts, then perl's
    results from the run's seconds on, every percentile of its default list, 5th to 99.99th, in
    its own name for the unit it was given."""
    names = ("5 10 15 20 25 30 35 40 45 50 55 60 65 70 75 80 85 90 92.5 95 97.5 99 99.25 99.5 "
             "99.75 99.9 99.95 99.99").split()
    values = {"50": p50, "99": p99}
    pct = ", ".join("%7s %s %sth" % (values.get(n, "0"), unit, n) for n in names)
    return ("2026-10-11 16:39:28, Total Kafka Write_Reading     0 writers,     0 readers,      "
            "1 max writers,     1 max readers,          0.0 write request MB,                0 write"
            " request records,         0.0 write request records/sec,     0.00 write request MB/sec,"
            "         0.0 read request MB,                 0 read request records,         0.0 read"
            " request records/sec,     0.00 read request MB/sec,     0.00 write response pending MB,"
            "             0 write response pending records,      0.00 read response pending MB,   "
            "          0 read response pending records,      0.00 write read request pending MB,  "
            "           0 write read request pending records,              0 write timeout events,"
            "     0.00 write timeout events/sec,             0 read timeout events,     0.00 read "
            "timeout events/sec,      60 seconds,         1.5 MB, %16d records,        50.0 "
            "records/sec,     0.02 MB/sec, %8s %s avg latency, %7s %s min latency, %7s %s max "
            "latency; %8d invalid latencies; Discarded Latencies:       0 lower,        0 higher; "
            "SLC-1:   0, SLC-2:   0; Latency Percentiles: %s\n"
            % (records, avg, unit, low, unit, high, unit, invalid, pct))


def _kgo(*workers):
    """kgo-repeater B's /status: the marker line the run prints, then the JSON list its handler
    writes indented, one entry per worker with its counts and its latencies in microseconds."""
    import json
    return (tr.KGO_STATUS + "\n" + json.dumps(
        [{"topics": ["sbl-kgo-1"], "produced": 0, "consumed": consumed, "enqueued": consumed,
          "errors": 0, "latency": {"ack": {"p50": 0, "p90": 0, "p99": 0},
                                   "e2e": {"p50": p50, "p90": p90, "p99": p99}}}
         for consumed, p50, p90, p99 in workers], indent="  ") + "\n")


class TestFreeze35sFourTools:
    """mqtt-benchmark, Sarama's kafka-producer-performance, SBK and kgo-repeater, each read where
    its source says it reports (freeze 35, D38-2)."""

    def test_mqtt_benchmark_weights_each_clients_mean_by_what_it_sent(self):
        got = tr.read_tool("mqtt-benchmark", _mqttb([(60, 0, 0.41, 1.9, 0.6), (30, 0, 0.38, 2.4, 0.9)]))
        assert got["reported_ms"]["avg"] == pytest.approx(0.7)
        assert (got["reported_ms"]["min"], got["reported_ms"]["max"]) == (0.38, 2.4)
        assert got["kept"] == 90 and got["received"] == 90 and got["step_ms"] == 1e-6

    def test_mqtt_benchmark_counts_its_failures_as_sent_and_not_kept(self):
        got = tr.read_tool("mqtt-benchmark", _mqttb([(59, 1, 0.4, 1.0, 0.5)]))
        assert got["kept"] == 59 and got["received"] == 60

    def test_mqtt_benchmark_reads_its_document_past_log_lines_and_braces_that_are_not_it(self):
        text = ("2026/10/11 18:00:00 CLIENT 3 Error sending message: {broker gone}\n"
                '{"runs": []}\n' + _mqttb([(60, 0, 0.4, 1.0, 0.5)]))
        assert tr.read_tool("mqtt-benchmark", text)["reported_ms"]["avg"] == 0.5

    def test_mqtt_benchmark_whose_clients_all_failed_has_no_figures(self):
        got = tr.read_tool("mqtt-benchmark", _mqttb([(0, 60, 0.0, 0.0, 0.0)]))
        assert got["reported_ms"] == {} and got["kept"] == 0 and got["received"] == 60

    def test_mqtt_benchmark_without_its_document_reads_nothing(self):
        got = tr.read_tool("mqtt-benchmark", "2026/10/11 CLIENT 0 had error connecting\n")
        assert got["reported_ms"] == {} and got["kept"] is None

    def test_sarama_reads_its_last_line_whole_milliseconds_and_all(self):
        text = (SARAMA.format(n=250, avg="0.9", p50="1.0", p99="4.0")
                + SARAMA.format(n=3000, avg="0.4", p50="0.0", p99="2.0"))
        got = tr.read_tool("sarama-producer-perf", text)
        assert got["reported_ms"]["p50"] == 0.0 and got["reported_ms"]["avg"] == 0.4
        assert got["reported_ms"]["p999"] == 3.0 and got["step_ms"] == 1.0
        assert got["records"] == 3000 and got["stddev_ms"] == 0.5 and got["kept"] is None

    def test_sarama_without_its_line_reads_nothing(self):
        got = tr.read_tool("sarama-producer-perf", "ERROR: Failed to create producer: EOF\n")
        assert got["reported_ms"] == {} and "records" not in got

    def test_sbk_reads_its_total_line_and_counts_what_it_called_invalid(self):
        text = (_sbk_total(records=2990, invalid=0).replace(", Total ", ", ")
                + _sbk_total(records=3000, invalid=17, low="0", p50="1", p99="3"))
        got = tr.read_tool("sbk", text)
        assert got["reported_ms"] == {"avg": 0.6, "min": 0.0, "max": 12.0, "p50": 1.0,
                                      "p90": 0.0, "p99": 3.0, "p999": 0.0}
        assert got["invalid"] == 17 and got["received"] == 3000 and got["kept"] is None
        assert got["steps_ms"]["p50"] == 1.0 and got["unit"] == "ms"

    def test_sbk_in_microseconds_is_read_in_milliseconds(self):
        got = tr.read_tool("sbk", _sbk_total(unit="mcs", avg="612.5", p50="600"))
        assert got["reported_ms"]["p50"] == pytest.approx(0.6)
        assert got["reported_ms"]["avg"] == pytest.approx(0.6125)
        assert got["steps_ms"]["p50"] == pytest.approx(0.001)

    def test_sbk_in_a_unit_it_does_not_know_keeps_its_counts_and_no_figures(self):
        got = tr.read_tool("sbk", _sbk_total(unit="FORTNIGHTS", invalid=2))
        assert got["reported_ms"] == {} and got["invalid"] == 2

    def test_sbk_without_its_total_line_reads_nothing(self):
        got = tr.read_tool("sbk", _sbk_total().replace(", Total ", ", "))
        assert got["reported_ms"] == {} and "invalid" not in got

    def test_kgo_repeater_reads_its_one_workers_end_to_end_latency_sign_and_all(self):
        got = tr.read_tool("kgo-repeater", _kgo((2998, -2190.0, -1980, -1500.5)))
        assert got["reported_ms"] == {"p50": -2.19, "p90": -1.98, "p99": -1.5005}
        assert got["received"] == 2998 and got["workers"] == 1 and got["kept"] is None

    def test_kgo_repeater_with_two_consuming_workers_reports_no_percentile_for_them(self):
        got = tr.read_tool("kgo-repeater", _kgo((10, 800, 900, 1000), (12, 810, 905, 990)))
        assert got["reported_ms"] == {} and got["received"] == 22 and got["workers"] == 2

    def test_kgo_repeater_that_consumed_nothing_reports_nothing(self):
        got = tr.read_tool("kgo-repeater", _kgo((0, 0, 0, 0)))
        assert got["reported_ms"] == {} and got["received"] is None

    def test_kgo_repeater_without_a_status_or_with_a_torn_one_reads_nothing(self):
        assert tr.read_tool("kgo-repeater", "curl: (7) Failed to connect\n")["reported_ms"] == {}
        assert tr.read_tool("kgo-repeater", tr.KGO_STATUS + "\n[{\"consumed\": 3")["reported_ms"] == {}
        assert tr.read_tool("kgo-repeater", tr.KGO_STATUS + "\n404 page not found\n")["workers"] == 0

    def test_kgo_repeater_without_a_figure_where_one_should_be_skips_it(self):
        text = _kgo((50, 800, 900, 1000)).replace('"p99": 1000', '"p99": null')
        assert set(tr.read_tool("kgo-repeater", text)["reported_ms"]) == {"p50", "p90"}


def _artemis(summary, warnings=0, intervals=1, array=True, producer=None):
    """Artemis's perf consumer as the run prints it: its console, with an AMQ132001 warning for each
    value it refused, then its --json file, interval objects and the summary joined by ",\\n", and
    then, where given, the producer's --json file with its own summary."""
    import json
    console = ["Connection brokerURL = tcp://10.2.1.21:61616"]
    console += ["2026-10-11 18:00:01,000 WARN  [org.apache.activemq.artemis.jms.client] AMQ132001:"
                " Unhandled exception thrown from onMessage"] * warnings
    objects = [json.dumps({"sampleType": "interval", "warmup": False, "time": i,
                           "transferTime": {"mean": "600.00", "50": 600, "count": 50}})
               for i in range(intervals)]
    if summary is not None:
        objects.append(json.dumps(dict({"sampleType": "summary", "time": 99}, **summary)))
    body = ",\n".join(objects)
    tail = ""
    if producer is not None:
        tail = (tr.ARTEMIS_PRODUCER_JSON + "\n" + json.dumps(
            {"sampleType": "interval", "time": 1, "sent": 50}) + ",\n"
            + json.dumps(dict({"sampleType": "summary", "time": 99}, **producer)) + "\n")
    return (tr.ARTEMIS_CONSOLE + "\n" + "\n".join(console) + "\n" + tr.ARTEMIS_JSON + "\n"
            + ("[" + body + "]" if array else body) + "\n" + tail)


TRANSFER = {"mean": "612.10", "50": 600, "90": 700, "99": 900, "99.9": 1200, "99.99": 1500,
            "max": 1800, "count": 2990}


def _rocket(*reports, sent=3000):
    """RocketMQ's Consumer reports (Consumer.java:115), each (TPS, AVG(B2C), MAX(B2C)), and the
    Producer's last line (Producer.java:393)."""
    lines = []
    for tps, avg, top in reports:
        shown = "%7.3f" % avg if avg == avg else "    NaN"
        lines.append("Current Time: 2026-10-11 18:00:10,000 | Consume TPS: %d | AVG(B2C) RT(ms): %s"
                     " | AVG(S2C) RT(ms): %s | MAX(B2C) RT(ms): %d | MAX(S2C) RT(ms): %d | Consume "
                     "Fail: 0" % (tps, shown, shown, top, top))
    if sent is not None:
        lines.append("[Complete] Send Total: %d | Send TPS: 1200 | Max RT(ms): 9 | Average RT(ms):"
                     "   0.800 | Send Failed: 0 | Response Failed: 0" % sent)
    return "\n".join(lines) + "\n"


def _bookkeeper(latencies_ns, p95="20.9", p99="21.5", completions=None, sent=None):
    """BookKeeper's benchmark as the run prints it: its log lines, slog's attributes in braces,
    then its dump file, "<ns>\\t<ms>ms" a line."""
    log = []
    if sent is not None:
        log.append("2026-10-11T18:01:00,000 - INFO  - [main:BenchThroughputLatency@193] - Sent {sent=%d}"
                   % sent)
    if completions is not None:
        log.append("2026-10-11T18:01:01,000 - INFO  - [main:BenchThroughputLatency@218] - Benchmark "
                   "complete {completions=%d, durationMs=60000, opsPerSec=50}" % completions)
    if p99 is not None:
        log.append("x - INFO - [main] - 99th percentile latency {latency=%s}" % p99)
    if p95 is not None:
        log.append("x - INFO - [main] - 95th percentile latency {latency=%s}" % p95)
    dump = "".join("%d\t%dms\n" % (n, n // 1000000) for n in latencies_ns)
    return "\n".join(log) + "\n" + tr.BOOKKEEPER_DUMP + "\n" + dump


class TestFreeze36sThreeTools:
    """Artemis's perf consumer, RocketMQ's benchmark Consumer and BookKeeper's benchmark, each read
    where its source says it reports (freeze 36, D39-2)."""

    def test_artemis_reads_its_summary_and_counts_its_refusals(self):
        text = _artemis({"result": "success", "totalReceived": 3010, "totalTransferTime": TRANSFER},
                        warnings=10)
        got = tr.read_tool("artemis-perf", text)
        assert got["reported_ms"] == {"avg": pytest.approx(0.6121), "p50": 0.6, "p90": 0.7,
                                      "p99": 0.9, "p999": 1.2, "max": 1.8}
        assert (got["kept"], got["received"], got["refused"], got["result"]) == (2990, 3010, 10, "success")

    def test_artemis_reads_what_its_producer_sent_apart_from_its_consumers_summary(self):
        text = _artemis({"result": "success", "totalReceived": 10, "totalTransferTime": TRANSFER},
                        producer={"result": "success", "totalSent": 10, "totalCompleted": 10})
        got = tr.read_tool("artemis-perf", text)
        assert (got["producer_sent"], got["producer_result"]) == (10, "success")
        assert got["received"] == 10 and got["kept"] == 2990, "the consumer's summary, not the producer's"
        bare = tr.read_tool("artemis-perf", _artemis(None, producer={"result": "success", "totalSent": 7}))
        assert bare["producer_sent"] == 7 and bare["reported_ms"] == {}
        assert tr.read_tool("artemis-perf", _artemis(None))["producer_sent"] is None

    def test_a_producer_stopped_before_its_summary_is_counted_from_its_intervals(self):
        """As in the pilot: eleven sent in its first second, none after, and no summary written."""
        import json
        stalled = (tr.ARTEMIS_PRODUCER_JSON + "\n"
                   + ",\n".join(json.dumps({"sampleType": "interval", "time": i, "sent": n})
                                for i, n in enumerate([11, 0, 0, 0])) + "\n")
        got = tr.read_tool("artemis-perf", _artemis(None) + stalled)
        assert (got["producer_sent"], got["producer_sent_from"]) == (11, "intervals")
        no_count = _artemis(None, producer={"result": "success"})
        got = tr.read_tool("artemis-perf", no_count)
        assert (got["producer_sent"], got["producer_sent_from"]) == (50, "intervals")

    def test_artemis_whose_histogram_counted_nothing_reports_no_figure(self):
        empty = dict(TRANSFER, count=0, mean="0.00", **{"50": 0, "max": 0})
        got = tr.read_tool("artemis-perf", _artemis({"result": "success", "totalReceived": 30000,
                                                     "totalTransferTime": empty}, warnings=3))
        assert got["reported_ms"] == {} and got["kept"] == 0 and got["received"] == 30000

    def test_artemis_without_an_array_or_a_summary_still_reads_what_is_there(self):
        text = _artemis({"result": "fail", "totalReceived": 5, "totalTransferTime": TRANSFER},
                        array=False)
        assert tr.read_tool("artemis-perf", text)["result"] == "fail"
        got = tr.read_tool("artemis-perf", _artemis(None, warnings=2))
        assert got["reported_ms"] == {} and got["refused"] == 2 and got["kept"] is None

    def test_artemis_passes_braces_that_are_not_json(self):
        text = _artemis({"result": "success", "totalReceived": 1,
                         "totalTransferTime": {"mean": "5.00", "count": 1}}).replace(
                             tr.ARTEMIS_JSON + "\n", tr.ARTEMIS_JSON + "\n{torn\n")
        got = tr.read_tool("artemis-perf", text)
        assert got["reported_ms"] == {"avg": 0.005} and got["kept"] == 1

    def test_artemis_with_nothing_printed_reads_nothing(self):
        got = tr.read_tool("artemis-perf", "Exception in thread main\n")
        assert got["reported_ms"] == {} and got["refused"] == 0

    def test_rocketmq_weights_its_reports_by_their_rate_and_keeps_their_largest_maximum(self):
        nan = float("nan")
        got = tr.read_tool("rocketmq-benchmark", _rocket((0, nan, 0), (300, 1.2, 9), (100, 2.0, 12)))
        assert got["reported_ms"] == {"avg": pytest.approx(1.4), "max": 12.0}
        assert got["reports"] == 2 and got["sent"] == 3000
        assert got["report_rows"] == [[300, 1.2, 9], [100, 2.0, 12]]
        assert got["s2c_avg_ms"] == pytest.approx(1.6) and got["consume_fail"] == 0

    def test_rocketmq_below_zero_on_average_with_a_maximum_of_zero(self):
        got = tr.read_tool("rocketmq-benchmark", _rocket((300, -2.1, 0)))
        assert got["reported_ms"] == {"avg": -2.1, "max": 0.0}

    def test_rocketmq_with_no_traffic_reads_nothing(self):
        got = tr.read_tool("rocketmq-benchmark", _rocket((0, float("nan"), 0), sent=None))
        assert got["reported_ms"] == {} and got["sent"] is None and got["s2c_avg_ms"] is None

    def test_bookkeeper_reads_its_dump_and_its_printed_percentiles(self):
        got = tr.read_tool("bookkeeper-benchmark", _bookkeeper([20100000, 20900000, 21500000],
                                                               completions=3, sent=3))
        assert got["reported_ms"] == {"p50": 20.9, "avg": pytest.approx(20.8333333),
                                      "min": 20.1, "max": 21.5, "p95": 20.9, "p99": 21.5}
        assert got["completions"] == 3 and got["sent"] == 3 and len(got["samples_ms"]) == 3

    def test_bookkeeper_without_its_dump_keeps_only_what_it_printed(self):
        got = tr.read_tool("bookkeeper-benchmark", _bookkeeper([], p95=None, p99="0.0"))
        assert got["reported_ms"] == {"p99": 0.0} and got["samples_ms"] == []
        assert got["completions"] is None and got["sent"] is None


F35 = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "tools_f35")


def _ran(name):
    with open(os.path.join(F35, name), encoding="utf-8") as fh:
        return fh.read()


class TestFreeze35sToolsAsTheyRan:
    """The four as they printed in the pilot of 11 October, on the first x86 pair: whole outputs,
    but SBK's, kept to its result lines and the shutdown that follows its total. A made-up world
    can drop what a real run prints, so each reader is held to what the tool itself wrote."""

    def test_mqtt_benchmark_fifty_clients_of_sixty_each(self):
        got = tr.read_tool("mqtt-benchmark", _ran("mqtt-benchmark_t4.txt"))
        assert got["reported_ms"]["avg"] == pytest.approx(0.6628642210000001)
        assert got["reported_ms"]["min"] == pytest.approx(0.5140859999999999)
        assert got["reported_ms"]["max"] == pytest.approx(1.06618)
        assert got["kept"] == got["received"] == 3000

    def test_sarama_whole_milliseconds_its_first_requests_in_its_tail(self):
        got = tr.read_tool("sarama-producer-perf", _ran("sarama-producer-perf_t4.txt"))
        assert got["reported_ms"] == {"avg": 1.7, "p50": 1.0, "p75": 1.0, "p95": 3.0, "p99": 24.7,
                                      "p999": 29.0}
        assert got["records"] == 3000

    def test_kgo_repeater_at_no_offset_and_with_its_clock_five_milliseconds_early(self):
        plain = tr.read_tool("kgo-repeater", _ran("kgo-repeater_t4.txt"))
        early = tr.read_tool("kgo-repeater", _ran("kgo-repeater_clock_5ms_early.txt"))
        assert plain["reported_ms"] == {"p50": 1.1105, "p90": 1.4305, "p99": 2.38025}
        assert early["reported_ms"] == {"p50": -3.966, "p90": -3.6205, "p99": -2.38225}
        assert (plain["received"], early["received"]) == (2905, 2904)

    def test_sbk_paced_and_under_the_steps(self):
        plain = tr.read_tool("sbk", _ran("sbk_t4.txt"))
        stepped = tr.read_tool("sbk", _ran("sbk_s1_stepped.txt"))
        assert plain["reported_ms"] == {"avg": 6.6, "min": 2.0, "max": 167.0, "p50": 5.0,
                                        "p90": 12.0, "p99": 17.0, "p999": 167.0}
        assert (plain["invalid"], plain["received"]) == (0, 3000)
        assert (stepped["invalid"], stepped["received"], stepped["reported_ms"]["min"]) == (58, 2992, 0.0)


F36 = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "tools_f36")


def _ran36(name):
    with open(os.path.join(F36, name), encoding="utf-8") as fh:
        return fh.read()


class TestFreeze36sToolsAsTheyRan:
    """The three as they printed in the pilots of 11 October on the second x86 pair. Whole outputs,
    but RocketMQ's without its logging library's lines about its own configuration, and the run with
    Artemis's consumer 5 ms behind, kept to its first 20 of 8,132 AMQ132001 warnings."""

    def test_artemis_at_no_offset(self):
        got = tr.read_tool("artemis-perf", _ran36("artemis-perf_t4.txt"))
        assert got["reported_ms"]["p50"] == pytest.approx(1.199)
        assert got["reported_ms"]["max"] == pytest.approx(24.447)
        assert (got["kept"], got["received"], got["refused"], got["producer_sent"]) == (3000, 3000, 0, 3000)

    def test_artemis_with_its_consumers_clock_five_milliseconds_behind(self):
        got = tr.read_tool("artemis-perf", _ran36("artemis-perf_consumer_5ms_behind.txt"))
        assert (got["kept"], got["received"], got["result"]) == (3000, 11132, "success")
        assert got["refused"] == 20 and got["reported_ms"]["p50"] == pytest.approx(1.407)

    def test_artemis_whose_producer_stopped_under_the_steps(self):
        got = tr.read_tool("artemis-perf", _ran36("artemis-perf_s1_stepped.txt"))
        assert (got["producer_sent"], got["producer_sent_from"], got["producer_result"]) == (6, "summary", "success")
        assert got["received"] == 6

    def test_rocketmq_at_no_offset_and_with_its_consumers_clock_behind(self):
        plain = tr.read_tool("rocketmq-benchmark", _ran36("rocketmq-benchmark_t4.txt"))
        behind = tr.read_tool("rocketmq-benchmark", _ran36("rocketmq-benchmark_consumer_5ms_behind.txt"))
        assert plain["reported_ms"] == {"avg": 1.789, "max": 111.0} and plain["sent"] == 3000
        assert behind["reported_ms"] == {"avg": -3.09, "max": 11.0}
        assert behind["report_rows"] == [[294, -3.09, 11]]

    def test_bookkeeper_every_latency_carries_its_throttles_wait(self):
        got = tr.read_tool("bookkeeper-benchmark", _ran36("bookkeeper-benchmark_t4.txt"))
        assert got["reported_ms"]["min"] == pytest.approx(22.3485, abs=1e-4)
        assert got["reported_ms"]["p50"] == pytest.approx(25.2338, abs=1e-4)
        assert (got["reported_ms"]["p95"], got["reported_ms"]["p99"]) == (pytest.approx(28.3125), pytest.approx(36.4701))
        assert (got["completions"], got["sent"], len(got["samples_ms"])) == (3001, 3002, 3001)


def _quiver(quartiles=(1, 1, 1, 2, 9), nines=(2, 3, 9, 9, 9), average=1.4, received=3000, sent=3000,
            transfers=((10, 11), (20, 22), (30, 30))):
    """A Quiver run's output as tools_run.sh prints it: the two consoles, the two summaries and the
    receiver's transfers, each under its header."""
    import json
    results = {"message_count": received, "latency_average": average,
               "latency_quartiles": list(quartiles), "latency_nines": list(nines)}
    parts = [tr.QUIVER_RECEIVER, "RESULTS", tr.QUIVER_SENDER, "", tr.QUIVER_SUMMARY,
             json.dumps({"config": {"impl": "qpid-jms"}, "results": results}, indent=2),
             tr.QUIVER_SENT, json.dumps({"results": {"message_count": sent}}), tr.QUIVER_TRANSFERS]
    parts += ["%d,%d" % (1760000000000 + s, 1760000000000 + r) for s, r in transfers]
    return "\n".join(parts) + "\n"


def _pravega(windows=((50, "2.3", "5.0"),), final=True, thrown=()):
    """A Pravega benchmark run as it prints: SimpleLogger's prefix, its window lines, its final line
    and whatever exceptions it printed."""
    head = "2026-10-11 22:00:01:123 +0000 [pool-2-thread-1] INFO io.pravega.perf.PerfStats - "
    lines = [head + "%8d records Write/Reading, %9.1f records/sec, %6.2f MiB/sec, %7s ms avg latency, "
             "%7s ms max latency" % (n, n / 1.0, 0.02, avg, top) for n, avg, top in windows]
    if final:
        lines.append(head + "2950 records Write/Reading, 49.153 records/sec, 512 bytes record size, 0.02 "
                     "MiB/sec, 2.4 ms avg latency, 31.0 ms max latency, 2 ms 50th, 3 ms 75th, 4 ms 95th, "
                     "6 ms 99th, 20 ms 99.9th, 31 ms 99.99th.")
    lines += list(thrown)
    return "\n".join(lines) + "\n"


class TestFreeze37sTwoTools:
    """Quiver's receiving arrow and the Pravega benchmark, each read where its source says it
    reports (freeze 37, D40-2)."""

    def test_quiver_reads_its_summary_and_its_transfers_with_their_sign(self):
        got = tr.read_tool("quiver", _quiver())
        assert got["reported_ms"] == {"avg": 1.4, "min": 1.0, "p25": 1.0, "p50": 1.0, "p75": 2.0,
                                      "max": 9.0, "p90": 2.0, "p99": 3.0, "p999": 9.0, "p9999": 9.0,
                                      "p99999": 9.0}
        assert got["samples_ms"] == [1, 2, 0] and got["below_zero"] == 0 and got["wrapped"] == []
        assert (got["kept"], got["received"], got["sent"]) == (3000, 3000, 3000)
        assert got["steps_ms"]["avg"] == 1e-3 and got["step_ms"] == 1.0

    def test_quiver_names_the_figures_its_unsigned_subtraction_wrapped(self):
        """As its wrapper computes them for the rows -5, +1 and 0: the value below zero lands at
        2^64 - 5, and numpy's percentiles of it at 2^64 after rounding (arrow.py:301-305)."""
        top = 2 ** 64
        got = tr.read_tool("quiver", _quiver(quartiles=(0, 0, 1, 2 ** 63, top), nines=(top,) * 5,
                                             average=6.148914691236517e18, received=3,
                                             transfers=((10, 5), (20, 21), (30, 30))))
        assert got["below_zero"] == 1 and got["samples_ms"] == [-5, 1, 0]
        assert got["reported_ms"]["max"] == float(top)
        assert got["wrapped"] == ["avg", "max", "p75", "p90", "p99", "p999", "p9999", "p99999"]

    def test_quiver_without_its_summary_or_transfers_reads_nothing(self):
        text = _quiver().split(tr.QUIVER_SUMMARY, 1)[0]
        got = tr.read_tool("quiver", text)
        assert got["reported_ms"] == {} and got["below_zero"] is None and got["samples_ms"] == []
        assert got["sent"] is None and got["kept"] is None

    def test_pravega_reads_its_final_line_and_its_windows(self):
        got = tr.read_tool("pravega-benchmark", _pravega(windows=((50, "2.3", "5.0"), (0, "NaN", "0.0"))))
        assert got["reported_ms"] == {"avg": 2.4, "max": 31.0, "p50": 2.0, "p75": 3.0, "p95": 4.0,
                                      "p99": 6.0, "p999": 20.0, "p9999": 31.0}
        assert (got["final"], got["kept"], got["windows"], got["thrown"]) == (True, 2950, 2, 0)
        assert got["window_rows"] == [[50, 2.3, 5.0], [0, None, 0.0]]
        assert got["steps_ms"]["avg"] == 0.1 and got["step_ms"] == 1.0

    def test_pravega_whose_statistics_died_on_a_value_below_zero(self):
        """Java 8 names the index after a colon; Java 11 and later say "Index -19 out of bounds"."""
        thrown = ("java.util.concurrent.ExecutionException: java.lang.ArrayIndexOutOfBoundsException: -18",
                  "Caused by: java.lang.ArrayIndexOutOfBoundsException: -18",
                  "java.lang.ArrayIndexOutOfBoundsException: Index -19 out of bounds for length 3600000")
        got = tr.read_tool("pravega-benchmark", _pravega(final=False, thrown=thrown))
        assert got["reported_ms"] == {} and got["final"] is False and got["kept"] is None
        assert got["thrown"] == 3 and got["thrown_at"] == [-19, -18] and got["windows"] == 1

    def test_pravega_with_no_records_at_all_reports_no_figure(self):
        text = _pravega(windows=()).replace("2.4 ms avg latency", "NaN ms avg latency")
        got = tr.read_tool("pravega-benchmark", text)
        assert got["reported_ms"] == {} and got["final"] is True and got["kept"] == 2950


F37 = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "tools_f37")


def _ran37(name):
    with open(os.path.join(F37, name), encoding="utf-8") as fh:
        return fh.read()


class TestFreeze37sToolsAsTheyRan:
    """The two as they printed in the pilots of 12 October on the second x86 pair. Quiver's outputs
    whole; the Pravega benchmark's without its client library's lines about its own connections."""

    def test_quiver_at_no_offset(self):
        got = tr.read_tool("quiver", _ran37("quiver_t4.txt"))
        assert (got["reported_ms"]["p50"], got["reported_ms"]["max"]) == (1.0, 48.0)
        assert got["reported_ms"]["avg"] == pytest.approx(1.141)
        assert (got["below_zero"], got["kept"], got["sent"], got["wrapped"]) == (0, 3000, 3000, [])
        assert min(got["samples_ms"]) == 1 and len(got["samples_ms"]) == 3000

    def test_quiver_with_its_receivers_clock_five_milliseconds_behind(self):
        """2,998 of 3,000 below zero, and every figure of its summary but the smallest wrapped."""
        got = tr.read_tool("quiver", _ran37("quiver_receiver_5ms_behind.txt"))
        assert got["below_zero"] == 2998 and got["reported_ms"]["min"] == 0.0
        assert got["reported_ms"]["p50"] == got["reported_ms"]["max"] == float(2 ** 64)
        assert got["reported_ms"]["avg"] == pytest.approx(1.8434446e19, rel=1e-6)
        assert "min" not in got["wrapped"] and len(got["wrapped"]) == 10

    def test_quiver_under_the_steps(self):
        """Seventeen transfers caught across a step, each 19 or 20 ms below zero: the maximum
        wraps, the median does not, and the average, over seventeen of 3,000, stays under 10^18."""
        got = tr.read_tool("quiver", _ran37("quiver_s1_stepped.txt"))
        assert got["below_zero"] == 17 and sorted(set(v for v in got["samples_ms"] if v < 0)) == [-20, -19]
        assert got["reported_ms"]["max"] == float(2 ** 64) and got["reported_ms"]["p50"] == 1.0
        assert 1e17 < got["reported_ms"]["avg"] < tr.QUIVER_WRAPPED_MS
        assert got["wrapped"] == ["max", "p999", "p9999", "p99999"]

    def test_pravega_at_no_offset(self):
        got = tr.read_tool("pravega-benchmark", _ran37("pravega-benchmark_t4.txt"))
        assert got["reported_ms"] == {"avg": 1.4, "max": 23.0, "p50": 1.0, "p75": 2.0, "p95": 2.0,
                                      "p99": 4.0, "p999": 5.0, "p9999": 7.0}
        assert (got["final"], got["kept"], got["windows"], got["thrown"]) == (True, 2862, 56, 0)

    def test_pravega_whose_statistics_died_under_the_steps(self):
        """One window, then nothing: no final line, and the exception its shutdown prints twice,
        from main and from its shutdown hook, each with its cause, naming the value, -18."""
        got = tr.read_tool("pravega-benchmark", _ran37("pravega-benchmark_s1_stepped.txt"))
        assert got["reported_ms"] == {} and got["final"] is False and got["windows"] == 1
        assert got["thrown"] == 6 and got["thrown_at"] == [-18]

    def test_pravega_under_libfaketime_waits_out_its_readers_timeout(self):
        """The instrument the second pilot replaced for this tool's T2 (D40-2): four windows hold a
        maximum of a second or near it, its reader's timeout, where the run without it held none."""
        got = tr.read_tool("pravega-benchmark", _ran37("pravega-benchmark_under_libfaketime.txt"))
        assert got["reported_ms"]["max"] == 1009.0 and got["reported_ms"]["avg"] == 19.9
        assert sum(1 for w in got["window_rows"] if w[2] > 500) == 4 and got["final"] is True


F38 = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "tools_f38")


def _ran38(name):
    with open(os.path.join(F38, name), encoding="utf-8") as fh:
        return fh.read()


class TestFreeze38sToolAsItRan:
    """Google's Pub/Sub load test as it printed in the pilots of 12 October on the second x86 pair:
    its outputs whole, client lines and check responses included."""

    def test_its_zero_step(self):
        """Both sides' medians printed as [11.4, 17.1) ms, the bucket below the one most of its
        values went into, [17.1, 25.6); 120 messages each, the preset's one a second for two
        minutes; and its driver's exit status 0."""
        got = tr.read_tool("pubsub-loadtest", _ran38("pubsub-loadtest_t1_zero_step.txt"))
        assert got["ranges"]["subscriber"]["p50"] == [11.390625, 17.0859375]
        assert got["ranges"]["publisher"]["p99"] == [25.62890625, 38.443359375]
        assert got["reported_ms"] == {"p50": 14.23828125, "p90": 21.357421875,
                                      "p99": 32.0361328125, "p999": 32.0361328125}
        assert got["steps_ms"]["p50"] == 17.0859375 - 11.390625
        assert (got["kept"], got["sent"], got["exit"], got["final"], got["thrown"]) == (
            120, 120, 0, True, 0)
        assert got["mentions_negative"] == 0 and got["missing"] is None
        sub = got["buckets"]["subscriber"]
        assert sub[7] == max(sub[:10]) and sum(sub[:6]) == 0, "no value under 11 ms"

    def test_an_attempt_whose_controller_never_started(self):
        """Its controller's call to Pub/Sub timed out before any message: nothing printed."""
        got = tr.read_tool("pubsub-loadtest", _ran38("pubsub-loadtest_never_started.txt"))
        assert got["reported_ms"] == {} and got["ranges"] == {} and got["buckets"] == {}
        assert (got["exit"], got["wrote_csv"], got["final"]) == (1, False, False)

    def test_its_t2_control_on_java_11(self):
        """The fourth pilot's, as the block will run it: on Java 11, nothing moved."""
        got = tr.read_tool("pubsub-loadtest", _ran38("pubsub-loadtest_t2_control.txt"))
        assert got["ranges"]["subscriber"]["p50"] == [17.0859375, 25.62890625]
        assert (got["final"], got["kept"], got["sent"], got["thrown"]) == (True, 120, 120, 0)
        assert got["set_aside"] == 0 and got["buckets"]["subscriber"][0] == 0

    def test_its_subscriber_s_clock_moved_back_past_its_trip(self):
        """101 of the 120 values its controller counted fell in bucket 0, and its controller threw
        while computing the subscriber's median: no percentile printed for either side, no
        output.csv, and the driver stopped at six minutes."""
        got = tr.read_tool("pubsub-loadtest", _ran38("pubsub-loadtest_t2_offset.txt"))
        assert (got["thrown"], got["mentions_negative"]) == (1, 1)
        assert got["ranges"] == {"subscriber": {}} and got["reported_ms"] == {}
        assert (got["exit"], got["wrote_csv"], got["final"]) == (124, False, False)
        sub = got["buckets"]["subscriber"]
        assert sub[0] == 101 and sum(sub) == 120

    def test_its_subscriber_s_clock_a_second_ahead(self):
        """Every value its subscriber counted went into bucket 17, [985.3, 1477.9) ms by its own
        binning, and the range its controller printed for that bucket lies wholly below 985.3 ms,
        Math.pow(1.5, 16) and (1.5, 17) on that JVM giving its bounds."""
        got = tr.read_tool("pubsub-loadtest", _ran38("pubsub-loadtest_t4_ahead.txt"))
        assert got["ranges"]["subscriber"]["p50"] == [656.8408355712891, 985.2612533569336]
        sub = got["buckets"]["subscriber"]
        assert sub[17] == 120 and sum(sub) == 120
        assert got["final"] is True and got["reported_ms"]["p50"] == 821.0510444641113

    def test_under_the_steps_and_its_control(self):
        """One step caught 34 of a burst of 40, in the burn-in its controller does not count; its
        printed median stayed its control's, and nothing it printed said so."""
        got = tr.read_tool("pubsub-loadtest", _ran38("pubsub-loadtest_s1_stepped.txt"))
        assert got["buckets_burn_in"]["subscriber"][0] == 34 and got["buckets"]["subscriber"][0] == 0
        assert (got["final"], got["mentions_negative"], got["kept"], got["set_aside"]) == (
            True, 0, 80, 1)
        control = tr.read_tool("pubsub-loadtest", _ran38("pubsub-loadtest_s1_control.txt"))
        assert got["ranges"]["subscriber"]["p50"] == control["ranges"]["subscriber"]["p50"]
        assert control["final"] is True and control["kept"] == 120


class TestThePubsubReader:
    """Each branch of read_pubsub_loadtest, on output shaped as cloud/azure/tools_run.sh prints it."""

    HEAD = "[main] INFO com.google.pubsub.flic.Driver - "
    CSV = ("Messaging Type,Language,Messaging Side,Num Clients,Cores Per Client,Message Size,"
           "CPU Scaling,QPS,Throughput (MB/s),50%ile Latency,90%ile Latency,99%ile Latency,"
           "99.9%ile Latency\n")

    def _run(self, console, status="0", csv=None, seconds="120", burn_in=None, aside=None):
        parts = []
        if aside is not None:
            parts += [tr.PUBSUB_ASIDE, aside]
        parts += [tr.PUBSUB_CONSOLE, console, tr.PUBSUB_STATUS, status]
        if seconds is not None:
            parts += [tr.PUBSUB_SECONDS, seconds]
        if burn_in is not None:
            parts += [tr.PUBSUB_BURN_IN, burn_in]
        parts += [tr.PUBSUB_CSV] + ([csv] if csv else [])
        return "\n".join(parts) + "\n"

    def test_a_run_whose_controller_threw_on_the_subscriber(self):
        console = "\n".join([
            self.HEAD + "Results for cps-gcloud-java-publisher:",
            self.HEAD + "50%: 11.390625 - 17.0859375",
            self.HEAD + "99%: 25.62890625 - 38.443359375",
            self.HEAD + "Results for cps-gcloud-java-subscriber:",
            'Exception in thread "main" java.lang.RuntimeException: Programming error: negative '
            "values appear in buckets.",
            "\tat com.google.pubsub.flic.common.LatencyTracker.getNthPercentileIndex(LatencyTracker.java:51)"])
        got = tr.read_tool("pubsub-loadtest", self._run(console, status="124"))
        assert got["reported_ms"] == {} and got["ranges"]["subscriber"] == {}
        assert got["publisher_ms"] == {"p50": (11.390625 + 17.0859375) / 2,
                                       "p99": (25.62890625 + 38.443359375) / 2}
        assert (got["thrown"], got["mentions_negative"], got["exit"]) == (1, 1, 124)
        assert (got["wrote_csv"], got["final"], got["kept"], got["sent"]) == (False, False, None,
                                                                             None)

    def test_a_bound_in_scientific_notation_and_a_line_before_any_side(self):
        console = "\n".join([self.HEAD + "50%: 1.0 - 2.0",
                             self.HEAD + "Results for cps-gcloud-java-subscriber:",
                             self.HEAD + "99.9%: 1.4778918457E7 - 2.2168377685E7"])
        got = tr.read_tool("pubsub-loadtest", self._run(console))
        assert got["ranges"] == {"subscriber": {"p999": [1.4778918457e7, 2.2168377685e7]}}

    def test_a_csv_cell_that_is_no_number_is_left_out_and_a_midpoint_gives_its_bucket(self):
        csv = self.CSV + "CPS_GCLOUD,JAVA,SUBSCRIBER,1,1,1,5,1,0,0.5,21.357421875,NaN,\n"
        got = tr.read_tool("pubsub-loadtest", self._run("", csv=csv))
        assert got["reported_ms"] == {"p50": 0.5, "p90": 21.357421875}
        assert got["steps_ms"] == {"p50": 1.0, "p90": pytest.approx(0.4 * 21.357421875)}
        assert got["kept"] == 120 and got["sent"] is None, "no publisher row"
        assert got["exit"] == 0 and got["final"] is True

    def test_a_run_without_its_seconds_counts_nothing(self):
        csv = self.CSV + "CPS_GCLOUD,JAVA,SUBSCRIBER,1,1,1,5,1,0,14.23828125,1,1,1\n"
        got = tr.read_tool("pubsub-loadtest", self._run("", csv=csv, seconds=None))
        assert got["kept"] is None and got["reported_ms"]["p50"] == 14.23828125

    def test_its_check_responses_are_summed_apart_from_the_burn_in(self):
        """Its controller counts a response's buckets only once the run outlasts the burn-in."""
        def check(side, buckets, seconds, nanos="84000000"):
            values = ["bucket_values: %d" % n for n in buckets]
            first = values[0] if values else "running_duration {"
            lines = ["[grpc-default-executor-1] INFO com.google.pubsub.flic.controllers.Client - "
                     "Connected to cps-gcloud-java-%s client.  Got check response: %s" % (side, first)]
            lines += values[1:] + (["running_duration {"] if values else [])
            return lines + ["  seconds: %d" % seconds, "  nanos: %s" % nanos, "}", ""]
        console = "\n".join(
            ["nanos: 5", "[pool-2-thread-1] INFO worker - starting in: seconds: 59", "nanos: 896"]
            + check("subscriber", [0, 0, 3], 30) + check("subscriber", [2, 0, 4, 1], 90)
            + check("publisher", [], 95) + check("subscriber", [0, 1], 60, nanos="5")
            + ["is_finished: true", "[main] INFO Driver - done"])
        got = tr.read_tool("pubsub-loadtest", self._run(console, burn_in="60"))
        assert got["buckets"] == {"subscriber": [2, 1, 4, 1], "publisher": []}
        assert got["buckets_burn_in"] == {"subscriber": [0, 0, 3]}
        no_burn_in = tr.read_tool("pubsub-loadtest", self._run(console))
        assert no_burn_in["buckets"]["subscriber"] == [2, 1, 7, 1], "every response counts"

    def test_what_it_says_went_missing_and_the_attempts_set_aside(self):
        console = "\n".join([self.HEAD + "Some published messages were not received!",
                             self.HEAD + "Missing 3 total messages."])
        got = tr.read_tool("pubsub-loadtest", self._run(console, aside="2"))
        assert (got["missing"], got["set_aside"]) == (3, 2)
        assert tr.read_tool("pubsub-loadtest", self._run(""))["set_aside"] is None

    def test_an_empty_output_reads_as_nothing(self):
        got = tr.read_tool("pubsub-loadtest", "")
        assert got["reported_ms"] == {} and got["exit"] is None and got["final"] is False
