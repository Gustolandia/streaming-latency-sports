"""Tests for scripts/analyze_m1_client.py - target 100% branch coverage.

The classifier decides whether the producer offset belongs to Kafka or to one client library,
so all three verdicts are pinned, not just the one the real data produced.
"""
import csv
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_m1_client import (  # noqa: E402
    load_trace,
    client_stats,
    verdict,
    main,
)


def _trace(tmp, client, rep, wake_values, produce=0.1):
    """A --trace-loop CSV named the way kafka_producer.py namespaces it."""
    p = tmp / f"trace_{client}_n1_concurrency_n1_20260723_212300_kafka_feed1_rep{rep}.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "wake_late_ms", "produce_ms"])
        w.writeheader()
        for i, v in enumerate(wake_values):
            w.writerow({"event_id": f"e{i}", "wake_late_ms": v, "produce_ms": produce})
    return p


class TestLoadTrace:
    def test_reads_both_columns(self, temp_dir):
        p = _trace(temp_dir, "kafka-python", 1, [1.0, 2.0, 3.0])
        wake, prod = load_trace(p)
        assert wake == [1.0, 2.0, 3.0] and len(prod) == 3

    def test_missing_file_is_empty(self, temp_dir):
        assert load_trace(temp_dir / "nope.csv") == ([], [])

    def test_unparseable_rows_are_skipped(self, temp_dir):
        p = temp_dir / "t.csv"
        p.write_text("event_id,wake_late_ms,produce_ms\na,xx,0.1\nb,2.0,0.1\n", encoding="utf-8")
        wake, _ = load_trace(p)
        assert wake == [2.0]


class TestClientStats:
    def test_pools_across_replicates(self, temp_dir):
        _trace(temp_dir, "kafka-python", 1, [1.0] * 10)
        _trace(temp_dir, "kafka-python", 2, [3.0] * 10)
        s = client_stats(str(temp_dir), "kafka-python")
        assert s["files"] == 2 and s["events"] == 20
        assert s["wake_late_p50"] == pytest.approx(2.0)

    def test_captures_the_startup_maximum(self, temp_dir):
        """The one-off 103 ms cost must survive as the max even when the median is small."""
        _trace(temp_dir, "kafka-python", 1, [1.5] * 50 + [103.5])
        s = client_stats(str(temp_dir), "kafka-python")
        assert s["wake_late_max"] == pytest.approx(103.5)
        assert s["wake_late_p50"] == pytest.approx(1.5)

    def test_none_when_the_client_has_no_traces(self, temp_dir):
        assert client_stats(str(temp_dir), "confluent") is None

    def test_empty_trace_files_are_skipped(self, temp_dir):
        p = temp_dir / "trace_confluent_n1_x.csv"
        p.write_text("event_id,wake_late_ms,produce_ms\n", encoding="utf-8")
        assert client_stats(str(temp_dir), "confluent") is None


class TestVerdict:
    @staticmethod
    def _s(client, p95):
        return {"client": client, "wake_late_p95": p95}

    def test_both_clients_show_it(self):
        tag, why = verdict(self._s("kafka-python", 103.0), self._s("confluent", 99.0))
        assert tag == "BOTH" and "not of one library" in why

    def test_only_one_client_shows_it(self):
        tag, why = verdict(self._s("kafka-python", 103.0), self._s("confluent", 3.0))
        assert tag == "ONE" and "kafka-python" in why

    def test_only_the_second_client_shows_it(self):
        tag, why = verdict(self._s("kafka-python", 2.0), self._s("confluent", 99.0))
        assert tag == "ONE" and "confluent" in why

    def test_neither_reproduces_it(self):
        """What the real data gave: the offset is not a per-event constant in either client."""
        tag, why = verdict(self._s("kafka-python", 11.0), self._s("confluent", 3.4))
        assert tag == "NEITHER" and "not reproduced" in why

    def test_threshold_is_configurable(self):
        assert verdict(self._s("a", 60.0), self._s("b", 1.0), threshold_ms=50.0)[0] == "ONE"
        assert verdict(self._s("a", 60.0), self._s("b", 1.0), threshold_ms=80.0)[0] == "NEITHER"


class TestMain:
    def test_end_to_end(self, temp_dir, capsys):
        _trace(temp_dir, "kafka-python", 1, [1.6] * 50 + [103.5])
        _trace(temp_dir, "confluent", 1, [1.4] * 50 + [20.0])
        assert main(["--m1-dir", str(temp_dir)]) == 0
        out = capsys.readouterr().out
        assert "kafka-python" in out and "confluent" in out and "VERDICT" in out

    def test_missing_directory(self, temp_dir, capsys):
        assert main(["--m1-dir", str(temp_dir / "absent")]) == 1
        assert "missing M1 directory" in capsys.readouterr().out

    def test_refuses_with_only_one_client(self, temp_dir, capsys):
        _trace(temp_dir, "kafka-python", 1, [1.0, 2.0])
        assert main(["--m1-dir", str(temp_dir)]) == 1
        assert "need both clients" in capsys.readouterr().out
