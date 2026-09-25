"""Tests for scripts/thread_record.py: which thread stamped what, and the two clocks."""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import thread_record as tr  # noqa: E402


class TestThreadRecord:

    def test_a_thread_is_noted_once_per_role(self):
        record = tr.ThreadRecord()
        for _ in range(3):
            record.note("stamps_ack")
        record.note("stamps_send")
        me = threading.get_native_id()
        assert record.roles == {"stamps_ack": {me}, "stamps_send": {me}}

    def test_two_threads_that_stamp_the_same_thing_are_both_kept(self):
        """The Redis producer's send workers: several threads, one job."""
        record = tr.ThreadRecord()
        seen = []

        def worker():
            record.note("stamps_ack")
            seen.append(threading.get_native_id())

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        record.note("stamps_ack")
        assert record.roles["stamps_ack"] == set(seen) | {threading.get_native_id()}

    def test_the_record_carries_both_clocks_at_both_ends(self, tmp_path):
        record = tr.ThreadRecord()
        record.note("stamps_receive")
        path = tmp_path / "consumer_threads.json"
        written = record.write(str(path))
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk == written
        assert on_disk["pid"] == os.getpid()
        assert on_disk["roles"] == {"stamps_receive": [threading.get_native_id()]}
        assert len(on_disk["clocks"]) == 2
        first, last = on_disk["clocks"]
        assert last["monotonic_ns"] >= first["monotonic_ns"]
        assert set(first) == {"realtime_ns", "monotonic_ns"}

    def test_the_record_goes_beside_the_csv_it_belongs_to(self):
        assert tr.beside(os.path.join("runs", "r1", "producer.csv")) == os.path.join(
            "runs", "r1", "producer_threads.json")
        assert tr.beside("consumer") == "consumer_threads.json"
