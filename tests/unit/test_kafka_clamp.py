"""K1: Kafka's end-to-end tool against an independent arrival observer.

The tool waits for each acknowledgment before it polls for the record, so a record readable
before its acknowledgment is timed no earlier than the acknowledgment. These tests hold the
pairing and the figures to records shaped as the traced copy and the observer write them: a
trace line per record with its offset and three wall-clock instants in microseconds and the
tool's own elapsed nanoseconds, and an arrival line per record the observer read.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import kafka_clamp as kc  # noqa: E402

TRACE_FIELDS = ("i", "partition", "offset", "begin_us", "ack_us", "poll_us", "elapsed_ns")
ARRIVAL_FIELDS = ("partition", "offset", "arrival_us")
#: A wall-clock instant in microseconds of the kind Instant.now() gives on 10 October 2026.
T0 = 1791590000000000


def _trace(i, offset, ack_after_us, poll_after_us):
    """One record: began at T0 + i ms, acknowledged and polled the given microseconds later."""
    begin = T0 + i * 1000
    return {"i": str(i), "partition": "0", "offset": str(offset), "begin_us": str(begin),
            "ack_us": str(begin + ack_after_us), "poll_us": str(begin + poll_after_us),
            "elapsed_ns": str(poll_after_us * 1000 + 300)}


def _arrival(offset, at_us):
    return {"partition": "0", "offset": str(offset), "arrival_us": str(at_us)}


#: Four records. The first two were readable before their acknowledgments came back (by 120 and
#: 40 microseconds); the last two only after (by 30 and 210).
TRACE = [_trace(0, 100, 610, 700), _trace(1, 101, 580, 650), _trace(2, 102, 900, 1180),
         _trace(3, 103, 2400, 2900)]
ARRIVALS = [_arrival(100, T0 + 490), _arrival(101, T0 + 1000 + 540), _arrival(102, T0 + 2000 + 930),
            _arrival(103, T0 + 3000 + 2610)]


class TestPairing:

    def test_each_record_is_paired_with_the_instant_the_observer_read_it(self):
        paired, missed = kc.pair(TRACE, ARRIVALS)
        assert missed == 0
        assert [round(p["s_ms"], 3) for p in paired] == [-0.12, -0.04, 0.03, 0.21]
        assert [round(p["observed_ms"], 3) for p in paired] == [0.49, 0.54, 0.93, 2.61]

    def test_a_record_the_observer_never_read_is_counted_not_dropped(self):
        paired, missed = kc.pair(TRACE, ARRIVALS[:3])
        assert (len(paired), missed) == (3, 1)

    def test_a_record_read_twice_keeps_its_first_reading(self):
        paired, _ = kc.pair(TRACE[:1], [_arrival(100, T0 + 800), _arrival(100, T0 + 490)])
        assert round(paired[0]["s_ms"], 3) == -0.12


class TestWhatTheToolPrints:

    def test_its_percentiles_are_whole_milliseconds_indexed_at_n_times_q(self):
        """EndToEndLatency.java:122 and 167-170: integer milliseconds, sorted, index n*q."""
        assert kc.kafka_percentile([0.4, 0.9, 1.2, 3.7], 0.5) == 1
        assert kc.kafka_percentile([0.4, 0.9, 1.2, 3.7], 0.99) == 3


class TestJudge:

    def test_the_figures_of_one_run(self):
        got = kc.judge(TRACE, ARRIVALS)
        assert (got["traced"], got["paired"], got["early"]) == (4, 4, 2)
        assert got["early_share"] == 0.5
        assert got["tool_prints"]["p50"] == 1 and got["tool_prints"]["p99"] == 2
        assert got["elapsed_covers_ack"] is True
        assert round(got["early_reported_late_by_ms"]["max"], 3) == 0.21

    def test_a_run_with_no_early_record_reports_none(self):
        got = kc.judge(TRACE[2:], ARRIVALS[2:])
        assert got["early"] == 0 and "early_reported_late_by_ms" not in got

    def test_nothing_paired_says_so(self):
        got = kc.judge(TRACE, [])
        assert got["paired"] == 0 and got["missed_by_observer"] == 4
        assert "nothing can be paired" in got["why"]

    def test_an_elapsed_time_shorter_than_its_own_acknowledgment_is_flagged(self):
        """A trace in which the tool's elapsed time ended before its acknowledgment did is not the
        tool's order of events, and the run's check says so."""
        bad = dict(TRACE[0], elapsed_ns=str(100_000))
        assert kc.judge([bad], ARRIVALS[:1])["elapsed_covers_ack"] is False


class TestMain:

    def _write(self, path, fields, rows):
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        return str(path)

    def test_it_writes_the_figures_and_leaves_with_zero(self, tmp_path, capsys):
        trace = self._write(tmp_path / "t.csv", TRACE_FIELDS, TRACE)
        arr = self._write(tmp_path / "a.csv", ARRIVAL_FIELDS, ARRIVALS)
        out = tmp_path / "k1.json"
        assert kc.main(["judge", "--trace", trace, "--arrivals", arr, "--out", str(out)]) == 0
        assert json.loads(out.read_text("utf-8"))["early"] == 2
        assert '"paired": 4' in capsys.readouterr().out

    def test_nothing_paired_leaves_with_one(self, tmp_path):
        trace = self._write(tmp_path / "t.csv", TRACE_FIELDS, TRACE)
        arr = self._write(tmp_path / "a.csv", ARRIVAL_FIELDS, [])
        assert kc.main(["judge", "--trace", trace, "--arrivals", arr]) == 1


class TestTornRows:
    """A writer stopped mid-line leaves a row whose last number is cut short and still a number.

    In the pilot of 11 October the observer was killed with its buffer full, every cell kept
    exactly 64 KB of rows, and the torn last one put the observed average at minus 735 million ms.
    """

    def _text(self, path, text):
        path.write_text(text, encoding="utf-8", newline="")
        return str(path)

    def test_a_last_line_without_its_end_is_left_out_and_counted(self, tmp_path):
        path = self._text(tmp_path / "a.csv", "partition,offset,arrival_us\n"
                          "0,100,%d\n0,101,1791590" % (T0 + 490))
        rows, torn = kc._rows(path)
        assert [r["offset"] for r in rows] == ["100"] and torn == 1

    def test_a_row_missing_a_field_is_left_out_and_counted(self, tmp_path):
        path = self._text(tmp_path / "a.csv", "partition,offset,arrival_us\n"
                          "0,100,%d\n0,101\n0,102,\n" % (T0 + 490))
        rows, torn = kc._rows(path)
        assert [r["offset"] for r in rows] == ["100"] and torn == 2

    def test_a_row_with_a_field_too_many_is_left_out_and_counted(self, tmp_path):
        path = self._text(tmp_path / "a.csv", "partition,offset,arrival_us\n"
                          "0,100,%d\n0,101,%d,9\n" % (T0 + 490, T0 + 1490))
        rows, torn = kc._rows(path)
        assert [r["offset"] for r in rows] == ["100"] and torn == 1

    def test_whole_rows_written_with_windows_line_ends_are_all_kept(self, tmp_path):
        path = self._text(tmp_path / "a.csv", "partition,offset,arrival_us\r\n0,100,%d\r\n"
                          % (T0 + 490))
        assert kc._rows(path) == ([{"partition": "0", "offset": "100",
                                    "arrival_us": str(T0 + 490)}], 0)

    def test_the_command_says_how_many_rows_it_left_out(self, tmp_path):
        trace = TestMain()._write(tmp_path / "t.csv", TRACE_FIELDS, TRACE)
        body = "".join("0,%s,%s\n" % (a["offset"], a["arrival_us"]) for a in ARRIVALS)
        arr = self._text(tmp_path / "a.csv", "partition,offset,arrival_us\n" + body
                         + "0,104,17915")
        out = tmp_path / "k1.json"
        assert kc.main(["judge", "--trace", trace, "--arrivals", arr, "--out", str(out)]) == 0
        got = json.loads(out.read_text("utf-8"))
        assert got["torn_rows"] == {"trace": 0, "arrivals": 1}
        assert got["paired"] == 4 and got["observed_ms"]["avg"] > 0
