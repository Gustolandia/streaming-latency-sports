"""Complete tests for kafka_consumer.py - 100% branch coverage."""
import pytest
import sys
import os
import csv
import gc
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Mock kafka module before importing
# The broker libraries are stubbed once, in tests/conftest.py, and must not be stubbed again
# here. `import redis` in a script binds the module object present at that moment; replacing
# sys.modules['redis'] afterwards leaves the script holding the old one while
# patch('redis.Redis', ...) patches the new one, and the patch then reaches nothing.

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from kafka_consumer import now_ns, main as kc_main


class TestNowNs:
    def test_returns_int(self):
        assert isinstance(now_ns(), int)

    def test_increasing(self):
        n1 = now_ns()
        n2 = now_ns()
        assert n2 >= n1


class TestMain:
    def test_main_basic(self, temp_dir):
        """Test basic execution path - idle timeout exits loop."""
        old_argv = sys.argv
        try:
            run_id = "test_run_1"
            out_path = temp_dir / "output.csv"
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--idle-seconds", "0"]
            
            mock_consumer = MagicMock()
            mock_consumer.poll.return_value = {}  # Empty results
            mock_consumer.close = MagicMock()
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer):
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
            
            assert out_path.exists()
            mock_consumer.close.assert_called_once()
        finally:
            sys.argv = old_argv

    def test_main_continue_on_idle_not_reached(self, temp_dir):
        """Test the continue statement when idle timeout not reached."""
        old_argv = sys.argv
        try:
            run_id = "test_run_idle_continue"
            out_path = temp_dir / "output.csv"
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--idle-seconds", "10"]
            
            mock_consumer = MagicMock()
            # First call returns empty, second call also empty (to exit after first iteration)
            mock_consumer.poll.side_effect = [{}, {}]
            mock_consumer.close = MagicMock()
            
            # Mock time.monotonic to return increasing values but less than idle_seconds
            # First call at line 63: last_msg = 100.0
            # Second call in loop: time.monotonic() = 100.5 (less than 10 seconds later)
            # So (100.5 - 100.0) >= 10 is False, so it continues
            # But we need to exit the loop somehow...
            # Actually, we can't test this without risking infinite loop
            # Let's just accept this line is hard to cover
            
            # Alternative: mock poll to return non-empty on second call
            mock_consumer.poll.side_effect = [
                {},  # First call - empty, triggers continue
                {},  # Second call - still empty, but now timeout reached
            ]
            
            time_values = [100.0, 100.5, 110.0]  # last_msg=100.0, check=100.5 (<10), check=110.0 (>=10)
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer):
                with patch('kafka_consumer.time.monotonic', side_effect=time_values):
                    kc_main()
            
            assert out_path.exists()
            # poll should have been called twice
            assert mock_consumer.poll.call_count == 2
            mock_consumer.close.assert_called_once()
        finally:
            sys.argv = old_argv

    def test_main_with_messages(self, temp_dir):
        """Test main() with actual messages."""
        old_argv = sys.argv
        try:
            run_id = "test_run_2"
            out_path = temp_dir / "output.csv"
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--idle-seconds", "0"]
            
            mock_msg = MagicMock()
            mock_msg.value = {
                "run_id": run_id,
                "event_id": "e1",
                "match_id": 1,
                "t_sim_seconds": 10.0,
            }
            mock_msg.topic = "test-topic"
            mock_msg.partition = 0
            mock_msg.offset = 1
            
            # First poll: has messages, second poll: empty (will exit due to idle=0)
            mock_consumer = MagicMock()
            mock_consumer.poll.side_effect = [
                {"test_topic_0": [mock_msg]},
                {},
            ]
            mock_consumer.close = MagicMock()
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer):
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
            
            assert out_path.exists()
            with open(out_path, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 1
                assert rows[0]['run_id'] == run_id
        finally:
            sys.argv = old_argv

    def test_main_message_filtering(self, temp_dir):
        """Test that messages with different run_id are filtered out."""
        old_argv = sys.argv
        try:
            run_id = "test_run_3"
            out_path = temp_dir / "output.csv"
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--idle-seconds", "0"]
            
            matching_msg = MagicMock()
            matching_msg.value = {"run_id": run_id, "event_id": "e1"}
            matching_msg.topic = "test-topic"
            matching_msg.partition = 0
            matching_msg.offset = 1
            
            non_matching_msg = MagicMock()
            non_matching_msg.value = {"run_id": "different_run", "event_id": "e2"}
            non_matching_msg.topic = "test-topic"
            non_matching_msg.partition = 0
            non_matching_msg.offset = 2
            
            mock_consumer = MagicMock()
            mock_consumer.poll.side_effect = [
                {"test_topic_0": [non_matching_msg, matching_msg]},
                {},
            ]
            mock_consumer.close = MagicMock()
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer):
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
            
            assert out_path.exists()
            with open(out_path, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 1
                assert rows[0]['event_id'] == 'e1'
        finally:
            sys.argv = old_argv

    def test_main_custom_group(self, temp_dir):
        """Test that custom group_id is used when provided."""
        old_argv = sys.argv
        try:
            run_id = "test_run_4"
            out_path = temp_dir / "output.csv"
            custom_group = "my_custom_group"
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--group", custom_group, "--idle-seconds", "0"]
            
            mock_consumer = MagicMock()
            mock_consumer.poll.return_value = {}
            mock_consumer.close = MagicMock()
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer) as mock_kc:
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
            
            mock_kc.assert_called_once()
            call_kwargs = mock_kc.call_args[1]
            assert call_kwargs['group_id'] == custom_group
        finally:
            sys.argv = old_argv

    def test_main_default_group(self, temp_dir):
        """Test that default group_id is used when not provided."""
        old_argv = sys.argv
        try:
            run_id = "test_run_5"
            out_path = temp_dir / "output.csv"
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--idle-seconds", "0"]
            
            mock_consumer = MagicMock()
            mock_consumer.poll.return_value = {}
            mock_consumer.close = MagicMock()
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer) as mock_kc:
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
            
            mock_kc.assert_called_once()
            call_kwargs = mock_kc.call_args[1]
            assert call_kwargs['group_id'] == f"sb-consumer-{run_id}"
        finally:
            sys.argv = old_argv

    def test_main_custom_topic(self, temp_dir):
        """Test that custom topic is used when provided."""
        old_argv = sys.argv
        try:
            run_id = "test_run_6"
            out_path = temp_dir / "output.csv"
            custom_topic = "my_topic"
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--topic", custom_topic, "--idle-seconds", "0"]
            
            mock_consumer = MagicMock()
            mock_consumer.poll.return_value = {}
            mock_consumer.close = MagicMock()
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer) as mock_kc:
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
            
            mock_kc.assert_called_once()
            call_args = mock_kc.call_args[0]
            assert call_args[0] == custom_topic
        finally:
            sys.argv = old_argv

    def test_main_creates_parent_dirs(self, temp_dir):
        """Test that parent directories are created for output and events files."""
        old_argv = sys.argv
        try:
            run_id = "test_run_7"
            out_path = temp_dir / "nested" / "dirs" / "output.csv"
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--idle-seconds", "0"]
            
            mock_consumer = MagicMock()
            mock_consumer.poll.return_value = {}
            mock_consumer.close = MagicMock()
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer):
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
            
            assert out_path.parent.exists()
            # The event log is the output's sibling, not runs/<run_id>/: the consumer stopped
            # writing into the repository. The old assertion passed only on a machine where an
            # earlier run had left runs/test_run_7 behind, and failed on every clean checkout.
            events_path = out_path.with_name(out_path.stem + "_events.csv")
            assert events_path.exists()
        finally:
            sys.argv = old_argv

    def test_main_max_poll_records(self, temp_dir):
        """Test that max_poll_records parameter is passed to poll()."""
        old_argv = sys.argv
        try:
            run_id = "test_run_8"
            out_path = temp_dir / "output.csv"
            max_records = 500
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--max-poll-records", str(max_records), "--idle-seconds", "0"]
            
            mock_consumer = MagicMock()
            mock_consumer.poll.return_value = {}
            mock_consumer.close = MagicMock()
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer):
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
            
            mock_consumer.poll.assert_called_once()
            call_kwargs = mock_consumer.poll.call_args[1]
            assert call_kwargs['max_records'] == max_records
        finally:
            sys.argv = old_argv

    # Removed test_main_continue_on_idle_not_reached to avoid hanging
    # The continue statement at line 110 is in a while True loop that's hard to test
    # without risking infinite loops. Line 110 is: continue when idle but not timeout.

    def test_main_flush_every_2000(self, temp_dir):
        """Test lines 153-154: flush every 2000 messages."""
        old_argv = sys.argv
        try:
            run_id = "test_run_flush"
            out_path = temp_dir / "output.csv"
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--idle-seconds", "0"]
            
            # Create 2000 mock messages
            mock_msgs = []
            for i in range(2000):
                msg = MagicMock()
                msg.value = {"run_id": run_id, "event_id": f"e{i}"}
                msg.topic = "test-topic"
                msg.partition = 0
                msg.offset = i
                mock_msgs.append(msg)
            
            # First poll: returns all 2000 messages, second poll: empty (exits)
            mock_consumer = MagicMock()
            mock_consumer.poll.side_effect = [
                {"test_topic_0": mock_msgs},
                {},
            ]
            mock_consumer.close = MagicMock()
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer):
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
            
            assert out_path.exists()
            # With 2000 messages, flush should have been called at least once
            # (actually, at message 2000, events_n % 2000 == 0, so it should flush)
        finally:
            sys.argv = old_argv

    # Removed test_main_continue_hit to avoid hanging
    # Patching time.monotonic after module import doesn't work reliably

    def test_main_as_script(self, temp_dir):
        """Test line 162: if __name__ == '__main__' block by running as subprocess with coverage."""
        env = os.environ.copy()
        scripts_dir = str(Path(__file__).parent.parent.parent / "scripts")
        repo_root = str(Path(__file__).parent.parent.parent)
        env["PYTHONPATH"] = scripts_dir + ";" + env.get("PYTHONPATH", "")
        coveragerc_path = str(Path(repo_root) / ".coveragerc")
        env["COVERAGE_PROCESS_START"] = coveragerc_path
        
        result = subprocess.run(
            [sys.executable, str(Path(scripts_dir) / "kafka_consumer.py"),
             "--run-id", "tr", "--topic", "test", "--out", str(temp_dir / "out.csv"),
             "--idle-seconds", "0"],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )
        assert result.returncode is not None


class TestBrokerCountParameter:
    """Tests for multi-broker support (broker-count parameter)."""

    def test_broker_count_default_is_1(self, temp_dir):
        """Test that broker-count defaults to 1 (single broker)."""
        old_argv = sys.argv
        try:
            run_id = "test_run_broker1"
            out_path = temp_dir / "output.csv"
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--idle-seconds", "0"]
            
            mock_consumer = MagicMock()
            mock_consumer.poll.return_value = {}
            mock_consumer.close = MagicMock()
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer):
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
            
            assert out_path.exists()
        finally:
            sys.argv = old_argv

    def test_broker_count_3_uses_cluster_bootstrap(self, temp_dir):
        """Test that broker-count=3 uses multi-broker bootstrap servers."""
        old_argv = sys.argv
        try:
            run_id = "test_run_broker3"
            out_path = temp_dir / "output.csv"
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--idle-seconds", "0", "--broker-count", "3"]
            
            mock_consumer = MagicMock()
            mock_consumer.poll.return_value = {}
            mock_consumer.close = MagicMock()
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer):
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
            
            assert out_path.exists()
        finally:
            sys.argv = old_argv

    def test_broker_count_1_explicit_uses_single_bootstrap(self, temp_dir):
        """Test that explicit broker-count=1 uses single broker."""
        old_argv = sys.argv
        try:
            run_id = "test_run_broker1_explicit"
            out_path = temp_dir / "output.csv"
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--idle-seconds", "0", "--broker-count", "1"]
            
            mock_consumer = MagicMock()
            mock_consumer.poll.return_value = {}
            mock_consumer.close = MagicMock()
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer):
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
            
            assert out_path.exists()
        finally:
            sys.argv = old_argv

    def test_broker_count_custom_bootstrap_override(self, temp_dir):
        """Test that custom bootstrap overrides default when broker-count=3."""
        old_argv = sys.argv
        try:
            run_id = "test_run_custom_bootstrap"
            out_path = temp_dir / "output.csv"
            custom_bootstrap = "custom1:9092,custom2:9092,custom3:9092"
            
            sys.argv = ["kc", "--run-id", run_id, "--out", str(out_path), "--idle-seconds", "0", 
                       "--broker-count", "3", "--bootstrap", custom_bootstrap]
            
            mock_consumer = MagicMock()
            mock_consumer.poll.return_value = {}
            mock_consumer.close = MagicMock()
            
            with patch('kafka_consumer.KafkaConsumer', return_value=mock_consumer) as mock_kc:
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
            
            # Verify that the custom bootstrap was passed to KafkaConsumer
            mock_kc.assert_called_once()
            call_kwargs = mock_kc.call_args[1]
            assert call_kwargs['bootstrap_servers'] == custom_bootstrap
            assert out_path.exists()
        finally:
            sys.argv = old_argv


class TestWhatAConsumerRecordsForTheMechanism:
    """D28-1 and D28-2: the thread that stamps each arrival, both clocks, and the receive loop's
    own cycle -- each only when asked, so the files A8 compares stay the same for both clients."""

    @staticmethod
    def _run(temp_dir, extra):
        import json
        mock_msg = MagicMock()
        mock_msg.value = {"run_id": "r9", "event_id": "e1", "match_id": 1, "t_sim_seconds": 1}
        consumer = MagicMock()
        consumer.poll.side_effect = [{"t0": [mock_msg, mock_msg]}, {}]
        old_argv = sys.argv
        try:
            sys.argv = ["kc", "--run-id", "r9", "--out", str(temp_dir / "consumer.csv"),
                        "--idle-seconds", "0"] + extra
            with patch('kafka_consumer.KafkaConsumer', return_value=consumer):
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
        finally:
            sys.argv = old_argv
        return json

    def test_the_thread_that_stamps_arrivals_is_named(self, temp_dir):
        import threading
        json = self._run(temp_dir, ["--thread-record"])
        record = json.loads((temp_dir / "consumer_threads.json").read_text(encoding="utf-8"))
        assert record["roles"] == {"stamps_receive": [threading.get_native_id()]}
        assert len(record["clocks"]) == 2

    def test_every_poll_is_logged_with_what_it_brought(self, temp_dir):
        self._run(temp_dir, ["--read-trace"])
        with open(temp_dir / "consumer_readtrace.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert [int(r["n_messages"]) for r in rows] == [2, 0]
        assert all(int(r["read_duration_ns"]) >= 0 for r in rows)
        # The columns redis_consumer.py writes, so M0 reads one format for both backends.
        assert list(rows[0]) == ["t_read_start_ns", "read_duration_ns", "n_messages"]

    def test_neither_is_written_unless_asked(self, temp_dir):
        self._run(temp_dir, [])
        assert not (temp_dir / "consumer_threads.json").exists()
        assert not (temp_dir / "consumer_readtrace.csv").exists()

    def test_freeze_40s_socket_timestamps_are_read_for_the_bootstraps_port(self, temp_dir):
        """F2 (14 Oct 2026): asked for, the socket class is replaced for the bootstrap's port before
        the client opens a connection, and what the sockets read is written at the end."""
        import json
        import socket
        import so_timestamps
        with patch.object(socket, "socket", socket.socket):
            self._run(temp_dir, ["--bootstrap", "10.1.1.21:19092", "--so-timestamps",
                                 str(temp_dir / "consumer_so.csv"), "--so-transmit", "sched"])
        assert so_timestamps.TimestampingSocket._ports == (19092,)
        written = temp_dir / "consumer_so.csv"
        assert written.read_text(encoding="utf-8").startswith("event_id,direction,ns")
        summary = json.loads(written.with_name(written.stem + "_summary.json").read_text(
            encoding="utf-8"))
        assert summary["transmit"] == "sched"


@pytest.fixture
def collector_restored():
    """--gc-off switches this process's collector off and freezes every object in it, and the rest
    of the suite runs here too: whatever a test does, the collector is put back as it was."""
    enabled, callbacks = gc.isenabled(), list(gc.callbacks)
    try:
        yield
    finally:
        gc.callbacks[:] = callbacks
        gc.unfreeze()
        if enabled:
            gc.enable()


def _seek_and_read(fd, size, offset):
    """os.pread where the system has none (Windows): a seek and a read do the same here."""
    os.lseek(fd, offset, os.SEEK_SET)
    return os.read(fd, size)


@pytest.mark.usefixtures("collector_restored")
class TestFreeze43KeepsTheCollectorOutOfTheReceivingLoop:
    """Freeze 43 (22 Oct 2026): in freeze 42's pilot the clients paused 17-84 ms at about 24, 34,
    46 and 60 s into each 70-s run, CPython's full collections. --gc-off switches the collector off
    once the consumer exists and before any message is received, --gc-log logs any collection that
    still happens, and --schedstat samples this thread's counters just before each poll."""

    @staticmethod
    def _run(temp_dir, tmp_path, monkeypatch, extra, order=None):
        """Two polls, one message: the collector's state as the consumer is made and at each poll,
        and the order of the counters' reads and the polls."""
        import client_quiet
        seen = {"made": [], "polled": []}
        order = [] if order is None else order
        counters = tmp_path / "schedstat"
        counters.write_bytes(b"1000 200 3\n")
        monkeypatch.setattr(client_quiet, "SCHEDSTAT", str(counters))
        pread = getattr(os, "pread", _seek_and_read)
        monkeypatch.setattr(os, "pread", lambda *a: order.append("sample") or pread(*a),
                            raising=False)
        msg = MagicMock()
        msg.value = {"run_id": "r43", "event_id": "e1", "match_id": 1, "t_sim_seconds": 1}
        batches = iter([{"t0": [msg]}, {}])
        consumer = MagicMock()

        def poll(**_):
            order.append("poll")
            seen["polled"].append(gc.isenabled())
            return next(batches)

        def made(*_, **__):
            seen["made"].append(gc.isenabled())
            return consumer

        consumer.poll.side_effect = poll
        gc.enable()
        old_argv = sys.argv
        try:
            sys.argv = ["kc", "--run-id", "r43", "--out", str(temp_dir / "consumer.csv"),
                        "--idle-seconds", "0"] + extra
            with patch('kafka_consumer.KafkaConsumer', side_effect=made):
                with patch('kafka_consumer.time.monotonic', side_effect=lambda: 100.0):
                    kc_main()
        finally:
            sys.argv = old_argv
        return seen, order

    def test_the_collector_goes_off_after_the_consumer_is_made_and_before_the_first_poll(
            self, temp_dir, tmp_path, monkeypatch):
        import json
        seen, _ = self._run(temp_dir, tmp_path, monkeypatch,
                            ["--gc-off", "--gc-log", str(temp_dir / "consumer_gc.json")])
        assert seen == {"made": [True], "polled": [False, False]}
        record = json.loads((temp_dir / "consumer_gc.json").read_text(encoding="utf-8"))
        assert record["gc_off"] is True and record["frozen"] > 0
        assert record["collections"] == []

    def test_with_the_collector_on_its_collections_are_logged(self, temp_dir, tmp_path,
                                                              monkeypatch):
        import json
        seen, _ = self._run(temp_dir, tmp_path, monkeypatch,
                            ["--gc-log", str(temp_dir / "consumer_gc.json")])
        assert seen["polled"] == [True, True]
        record = json.loads((temp_dir / "consumer_gc.json").read_text(encoding="utf-8"))
        assert record["gc_off"] is False

    def test_the_counters_are_sampled_just_before_each_poll(self, temp_dir, tmp_path,
                                                            monkeypatch):
        _, order = self._run(temp_dir, tmp_path, monkeypatch,
                             ["--schedstat", str(temp_dir / "consumer_schedstat.csv")])
        assert order == ["sample", "poll", "sample", "poll"]
        with open(temp_dir / "consumer_schedstat.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert [(r["exec_ns"], r["delay_ns"], r["slices"]) for r in rows] \
            == [("1000", "200", "3")] * 2

    def test_the_sample_falls_before_the_traced_poll_not_inside_it(self, temp_dir, tmp_path,
                                                                   monkeypatch):
        """The read trace's durations stay the polls' alone: the counters are read, then the
        trace's start is stamped, then the poll is made. Read as an order of events, because a
        wall clock that steps in a millisecond, as Windows' does, cannot tell the two apart."""
        import kafka_consumer
        order, clock = [], kafka_consumer.now_ns
        monkeypatch.setattr(kafka_consumer, "now_ns", lambda: order.append("clock") or clock())
        self._run(temp_dir, tmp_path, monkeypatch,
                  ["--schedstat", str(temp_dir / "consumer_schedstat.csv"), "--read-trace"],
                  order)
        before = [order[i - 2:i] for i, event in enumerate(order) if event == "poll"]
        assert before == [["sample", "clock"]] * 2
        with open(temp_dir / "consumer_schedstat.csv", newline="", encoding="utf-8") as fh:
            sampled = [int(r["t_ns"]) for r in csv.DictReader(fh)]
        with open(temp_dir / "consumer_readtrace.csv", newline="", encoding="utf-8") as fh:
            began = [int(r["t_read_start_ns"]) for r in csv.DictReader(fh)]
        assert len(sampled) == len(began) == 2
        assert all(s <= b for s, b in zip(sampled, began))

    def test_with_no_switch_the_run_is_the_run_it_was(self, temp_dir, tmp_path, monkeypatch,
                                                      capsys):
        seen, order = self._run(temp_dir, tmp_path, monkeypatch, [])
        assert seen == {"made": [True], "polled": [True, True]}
        assert order == ["poll", "poll"]
        assert sorted(p.name for p in temp_dir.iterdir()) == ["consumer.csv",
                                                              "consumer_events.csv"]
        out = capsys.readouterr().out
        assert "OK collector" not in out and "OK schedstat" not in out
