"""K1: Kafka's end-to-end tool against an independent arrival observer.

The tool waits for each acknowledgment before it polls for the record, so a record readable
before its acknowledgment is timed no earlier than the acknowledgment. These tests hold the
pairing and the figures to records shaped as the traced copy and the observer write them: a
trace line per record with its offset and three wall-clock instants in microseconds and the
tool's own elapsed nanoseconds, and an arrival line per record the observer read.
"""
import csv
import json
import os
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
        #: open(), not Path.write_text(): its newline argument came in Python 3.10, and CI runs 3.9.
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
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


def _k1(share, covers=True, traced=3000, paired=3000, late=True, torn=0):
    """One run's k1.json as the judge writes it, with the share of early records given."""
    got = {"traced": traced, "paired": paired, "missed_by_observer": traced - paired,
           "early": int(share * paired), "early_share": share, "elapsed_covers_ack": covers,
           "s_ms": {"p01": -0.2, "p50": 0.2, "p99": 0.7},
           "tool_prints": {"avg": 1.7, "p50": 1, "p99": 3},
           "observed_ms": {"avg": 1.0, "p50": 0.9, "p99": 2.1},
           "torn_rows": {"trace": 0, "arrivals": torn}}
    if late:
        got["early_reported_late_by_ms"] = {"p50": 1.2, "p99": 2.7, "max": 3.2}
    return got


def _block(tmp_path, shares, skip=(), overrides=None):
    """Six rounds of the four cells in tools.sh's folders, each cell's share from `shares`."""
    for rnd in range(1, 7):
        folder = tmp_path / ("tools_v35" if rnd == 1 else "tools_v35_round%d" % rnd)
        for (load, first), share in shares.items():
            if (rnd, load, first) in skip:
                continue
            run = folder / ("k1-l%s-first%s" % (load, first))
            run.mkdir(parents=True, exist_ok=True)
            extra = (overrides or {}).get((rnd, load, first), {})
            (run / "k1.json").write_text(json.dumps(_k1(share, **extra)), encoding="utf-8")
    return str(tmp_path)


#: The pilot's shape: a few early idle, many at 88% load, none with go-first.
PILOT = {("0", "no"): 0.026, ("0", "yes"): 0.006, ("88", "no"): 0.27, ("88", "yes"): 0.0}


class TestTheBlock:
    """K1 across its six rounds, judged as freeze 32 froze it (D35-7)."""

    def test_every_round_and_cell_is_a_row_with_its_figures(self, tmp_path):
        rows = kc.block_rows(_block(tmp_path, PILOT))
        assert len(rows) == 24 and all(r["judged"] for r in rows)
        first = rows[0]
        assert (first["round"], first["load_pct"], first["go_first"]) == (1, "0", "no")
        assert first["s_p50_ms"] == 0.2 and first["tool_p99_ms"] == 3 and first["late_max_ms"] == 3.2
        assert first["observed_p99_ms"] == 2.1 and first["torn_rows"] == 0

    def test_the_pilots_shape_holds_every_prediction(self, tmp_path):
        found = kc.verdicts(kc.block_rows(_block(tmp_path, PILOT)))
        assert {k: v["verdict"] for k, v in found.items()} == {
            "K1-a": "holds", "K1-b": "holds", "K1-c": "holds", "K1-d": "holds"}
        assert found["K1-b"]["held_in_rounds"] == [1, 2, 3, 4, 5, 6]

    def test_one_round_against_a_prediction_fails_it(self, tmp_path):
        """All six rounds or nothing: one round where load did not raise the share fails K1-c."""
        root = _block(tmp_path, PILOT)
        path = os.path.join(root, "tools_v35_round4", "k1-l0-firstno", "k1.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(_k1(0.5), fh)
        found = kc.verdicts(kc.block_rows(root))
        assert found["K1-c"]["verdict"] == "fails" and found["K1-c"]["failed_in_rounds"] == [4]
        assert found["K1-b"]["verdict"] == "holds"

    def test_a_run_the_observer_read_too_little_of_is_not_judged(self, tmp_path):
        """Below 99% of the traced records, the run is reported and its round is not judged."""
        root = _block(tmp_path, PILOT, overrides={(2, "88", "no"): {"paired": 2900}})
        rows = kc.block_rows(root)
        assert not [r for r in rows if (r["round"], r["load_pct"], r["go_first"]) == (2, "88", "no")][0]["judged"]
        found = kc.verdicts(rows)
        assert found["K1-b"]["verdict"] == "undecided" and found["K1-b"]["not_judged_in_rounds"] == [2]
        assert found["K1-d"]["not_judged_in_rounds"] == [2]

    def test_a_missing_run_is_a_row_that_says_so_and_leaves_its_round_unjudged(self, tmp_path):
        root = _block(tmp_path, PILOT, skip={(6, "88", "yes")})
        rows = kc.block_rows(root)
        missing = [r for r in rows if (r["round"], r["load_pct"], r["go_first"]) == (6, "88", "yes")][0]
        assert missing["traced"] == "" and missing["judged"] is False
        found = kc.verdicts(rows)
        assert found["K1-d"]["verdict"] == "undecided" and found["K1-a"]["runs"] == 23

    def test_a_trace_that_does_not_cover_its_acknowledgment_fails_k1_a_and_is_not_judged(self, tmp_path):
        root = _block(tmp_path, PILOT, overrides={(3, "0", "yes"): {"covers": False}})
        rows = kc.block_rows(root)
        assert kc.verdicts(rows)["K1-a"]["verdict"] == "fails"
        assert sum(1 for r in rows if not r["judged"]) == 1

    def test_no_run_at_all_fails_k1_a_and_leaves_the_rest_undecided(self, tmp_path):
        found = kc.verdicts(kc.block_rows(str(tmp_path)))
        assert found["K1-a"] == {"verdict": "fails", "runs": 0}
        assert all(found[k]["verdict"] == "undecided" for k in ("K1-b", "K1-c", "K1-d"))

    def test_a_run_with_no_early_record_has_no_lateness(self, tmp_path):
        shares = dict(PILOT)
        root = _block(tmp_path, shares, overrides={(1, "88", "yes"): {"late": False}})
        row = [r for r in kc.block_rows(root) if (r["round"], r["load_pct"], r["go_first"]) == (1, "88", "yes")][0]
        assert row["late_p50_ms"] == "" and row["judged"]

    def test_a_run_written_without_its_torn_count_counts_none(self, tmp_path):
        root = _block(tmp_path, PILOT)
        path = os.path.join(root, "tools_v35", "k1-l0-firstno", "k1.json")
        got = json.load(open(path, encoding="utf-8"))
        del got["torn_rows"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(got, fh)
        assert kc.block_rows(root)[0]["torn_rows"] == 0

    def test_the_command_writes_the_table_and_the_verdicts(self, tmp_path, capsys):
        root = _block(tmp_path / "runs", PILOT)
        out, verdicts = tmp_path / "k1.csv", tmp_path / "k1_verdicts.json"
        assert kc.main(["block", "--root", root, "--out", str(out), "--verdicts", str(verdicts)]) == 0
        with out.open(encoding="utf-8") as fh:
            assert len(list(csv.DictReader(fh))) == 24
        assert json.loads(verdicts.read_text("utf-8"))["K1-d"]["verdict"] == "holds"
        assert '"K1-a"' in capsys.readouterr().out

    def test_the_command_on_a_folder_with_no_run_leaves_with_one(self, tmp_path):
        out, verdicts = tmp_path / "k1.csv", tmp_path / "v.json"
        assert kc.main(["block", "--root", str(tmp_path), "--out", str(out),
                        "--verdicts", str(verdicts)]) == 1
