"""
Unit tests for run_concurrency_test.py
Tests the concurrency test orchestration script.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from scripts.run_concurrency_test import run_trial, main, resolve_plans, plan_for_feed


class TestDistinctMatchPlans:
    """Per-match plan selection so each feed carries a different real match."""

    def test_resolve_plans_empty_when_no_dir(self):
        assert resolve_plans("", "default.csv") == []

    def test_resolve_plans_finds_nested_replay_plans(self, temp_dir):
        for mid in ("match_1", "match_2"):
            d = temp_dir / mid
            d.mkdir()
            (d / "replay_plan.csv").write_text("row_idx\n1\n")
        found = resolve_plans(str(temp_dir), "default.csv")
        assert len(found) == 2 and all(f.endswith("replay_plan.csv") for f in found)

    def test_resolve_plans_falls_back_to_flat_csvs(self, temp_dir):
        (temp_dir / "a.csv").write_text("x\n")
        (temp_dir / "b.csv").write_text("x\n")
        assert len(resolve_plans(str(temp_dir), "default.csv")) == 2

    def test_resolve_plans_empty_dir(self, temp_dir):
        assert resolve_plans(str(temp_dir), "default.csv") == []

    def test_plan_for_feed_uses_default_without_plans(self):
        assert plan_for_feed([], 3, "default.csv") == "default.csv"

    def test_plan_for_feed_assigns_distinct_and_wraps(self):
        plans = ["m1.csv", "m2.csv", "m3.csv"]
        assert [plan_for_feed(plans, f, "d.csv") for f in (1, 2, 3)] == plans
        assert plan_for_feed(plans, 4, "d.csv") == "m1.csv"  # wraps

    def test_main_passes_distinct_plans_per_feed(self, temp_dir):
        for mid in ("match_1", "match_2"):
            d = temp_dir / mid
            d.mkdir()
            (d / "replay_plan.csv").write_text("row_idx\n1\n")
        test_args = ['scripts/run_concurrency_test.py', '5', 'data/test.csv', '1',
                     '--plans-dir', str(temp_dir)]
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('t', True, 'ok')
                try:
                    main()
                except SystemExit:
                    pass
                used = {c[0][1] for c in mock_run_trial.call_args_list}
                assert len(used) == 2  # two distinct match plans, wrapped over 5 feeds
                assert all("replay_plan.csv" in u for u in used)

    def test_trial_timeout_is_configurable(self, temp_dir):
        # true real-time replays run as long as the window they replay, so 300s is not enough
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            run_trial(run_id="t", plan_csv="p.csv", backend="kafka", speedup=1,
                      max_t_sim=600, trial_timeout=900)
            assert mock_run.call_args[1]["timeout"] == 900

    def test_trial_timeout_message_reports_value(self, temp_dir):
        import subprocess as sp
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.side_effect = sp.TimeoutExpired("c", 900)
            _, ok, msg = run_trial(run_id="t", plan_csv="p.csv", backend="kafka", speedup=1,
                                   max_t_sim=600, trial_timeout=900)
            assert ok is False and "900" in msg

    def test_main_passes_trial_timeout(self):
        test_args = ['scripts/run_concurrency_test.py', '1', 'data/test.csv', '1',
                     '--trial-timeout', '900']
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('t', True, 'ok')
                try:
                    main()
                except SystemExit:
                    pass
                assert all(c[1].get('trial_timeout') == 900
                           for c in mock_run_trial.call_args_list)

    def test_fractional_speedup_supported(self):
        # true real-time replay of a 120x-baked plan needs speedup = 1/120
        test_args = ['scripts/run_concurrency_test.py', '1', 'data/test.csv', '1',
                     '--speedup', '0.008333']
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('t', True, 'ok')
                try:
                    main()
                except SystemExit:
                    pass
                assert all(c[0][3] == pytest.approx(0.008333)
                           for c in mock_run_trial.call_args_list)

    def test_main_warns_and_falls_back_when_plans_dir_empty(self, temp_dir, capsys):
        test_args = ['scripts/run_concurrency_test.py', '1', 'data/test.csv', '1',
                     '--plans-dir', str(temp_dir)]
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('t', True, 'ok')
                try:
                    main()
                except SystemExit:
                    pass
                assert all(c[0][1] == 'data/test.csv' for c in mock_run_trial.call_args_list)


class TestRunTrial:
    """Tests for run_trial function."""

    def test_run_trial_kafka_success(self, temp_dir):
        """Test successful Kafka trial execution."""
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            result = run_trial(
                run_id="test_kafka_001",
                plan_csv="data/test.csv",
                backend="kafka",
                speedup=120,
                max_t_sim=600,
                bootstrap="localhost:9092",
                redis_host="localhost",
                redis_port=6379,
                topic="test-topic"
            )
            
            assert result[0] == "test_kafka_001"
            assert result[1] is True
            assert "Completed" in result[2]

    def test_run_trial_kafka_with_bootstrap(self, temp_dir):
        """Test Kafka trial with bootstrap servers."""
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            result = run_trial(
                run_id="test_kafka_002",
                plan_csv="data/test.csv",
                backend="kafka",
                speedup=120,
                max_t_sim=600,
                bootstrap="localhost:9092",
                redis_host="localhost",
                redis_port=6379,
                topic=None  # Should use bootstrap
            )
            
            assert result[1] is True

    def test_run_trial_redis_success(self, temp_dir):
        """Test successful Redis trial execution."""
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            result = run_trial(
                run_id="test_redis_001",
                plan_csv="data/test.csv",
                backend="redis",
                speedup=120,
                max_t_sim=600,
                bootstrap="localhost:9092",
                redis_host="localhost",
                redis_port=6379,
                stream="test-stream"
            )
            
            assert result[0] == "test_redis_001"
            assert result[1] is True

    def test_run_trial_redis_with_host_port(self, temp_dir):
        """Test Redis trial with host and port."""
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            result = run_trial(
                run_id="test_redis_002",
                plan_csv="data/test.csv",
                backend="redis",
                speedup=120,
                max_t_sim=600,
                bootstrap="localhost:9092",
                redis_host="localhost",
                redis_port=6379,
                stream=None  # Should use redis_host and redis_port
            )
            
            assert result[1] is True

    def test_run_trial_unknown_backend(self, temp_dir):
        """Test trial with unknown backend."""
        result = run_trial(
            run_id="test_invalid",
            plan_csv="data/test.csv",
            backend="invalid",
            speedup=120,
            max_t_sim=600
        )
        
        assert result[1] is False
        assert "Unknown backend" in result[2]

    def test_run_trial_nonzero_exit_code(self, temp_dir):
        """Test trial with non-zero exit code."""
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, 
                stdout="", 
                stderr="Error: Connection failed"
            )
            
            result = run_trial(
                run_id="test_fail",
                plan_csv="data/test.csv",
                backend="kafka",
                speedup=120,
                max_t_sim=600
            )
            
            assert result[1] is False
            assert "Failed with exit code 1" in result[2]

    def test_run_trial_timeout(self, temp_dir):
        """Test trial timeout."""
        import subprocess
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("test", 300)
            
            result = run_trial(
                run_id="test_timeout",
                plan_csv="data/test.csv",
                backend="kafka",
                speedup=120,
                max_t_sim=600
            )
            
            assert result[1] is False
            assert "timed out" in result[2].lower() or "Timeout" in result[2]

    def test_run_trial_exception(self, temp_dir):
        """Test trial with unexpected exception."""
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.side_effect = RuntimeError("Unexpected error")
            
            result = run_trial(
                run_id="test_error",
                plan_csv="data/test.csv",
                backend="kafka",
                speedup=120,
                max_t_sim=600
            )
            
            assert result[1] is False
            assert "Unexpected error" in result[2]

    def test_run_trial_command_construction_kafka(self, temp_dir):
        """Test that Kafka command is constructed correctly."""
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            run_trial(
                run_id="test_kafka",
                plan_csv="data/test.csv",
                backend="kafka",
                speedup=120,
                max_t_sim=600,
                topic="test-topic"
            )
            
            # Check that subprocess.run was called
            assert mock_run.called
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            
            # cmd is a list, check that it contains expected parts
            assert 'powershell' in cmd
            assert '-ExecutionPolicy' in cmd
            assert 'Bypass' in cmd
            # The command string is in the last element
            cmd_str = cmd[-1]
            assert 'run_kafka_trial.ps1' in cmd_str
            assert 'test_kafka' in cmd_str
            assert 'data/test.csv' in cmd_str
            assert '120' in cmd_str
            assert '600' in cmd_str

    def test_run_trial_command_construction_redis(self, temp_dir):
        """Test that Redis command is constructed correctly."""
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            run_trial(
                run_id="test_redis",
                plan_csv="data/test.csv",
                backend="redis",
                speedup=120,
                max_t_sim=600,
                redis_host="localhost",
                redis_port=6379,
                stream="test-stream"
            )
            
            # Check that subprocess.run was called
            assert mock_run.called
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            
            # cmd is a list, check that it contains expected parts
            assert 'powershell' in cmd
            # The command string is in the last element
            cmd_str = cmd[-1]
            assert 'run_redis_trial.ps1' in cmd_str
            assert 'test_redis' in cmd_str
            assert 'localhost' in cmd_str
            assert '6379' in cmd_str


class TestMain:
    """Tests for main function."""

    def test_main_arguments(self, temp_dir):
        """Test that main parses arguments correctly."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '5',
            'data/test.csv',
            '1',
            '--speedup', '120',
            '--max-t-sim', '600'
        ]
        
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('test_run', True, 'Success')
                
                # This will exit, so we need to catch SystemExit
                with pytest.raises(SystemExit) as exc_info:
                    main()
                
                # Should exit with code 0 (success)
                assert exc_info.value.code == 0

    def test_main_creates_output_directory(self, temp_dir):
        """Test that main creates output directory."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '1',
            'data/test.csv',
            '1'
        ]
        
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('test_run', True, 'Success')
                with patch('scripts.run_concurrency_test.Path') as mock_path:
                    mock_dir = MagicMock()
                    mock_path.return_value = mock_dir
                    mock_dir.exists.return_value = False
                    
                    try:
                        main()
                    except SystemExit:
                        pass
                    
                    # Check mkdir was called
                    mock_dir.mkdir.assert_called()

    def test_main_creates_run_list_file(self, temp_dir):
        """Test that main creates run list file."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '1',
            'data/test.csv',
            '1'
        ]
        
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('test_run', True, 'Success')
                with patch('builtins.open', create=True) as mock_open:
                    mock_file = MagicMock()
                    mock_open.return_value.__enter__.return_value = mock_file
                    
                    try:
                        main()
                    except SystemExit:
                        pass
                    
                    # Check that file was written
                    assert mock_open.called

    def test_main_creates_summary_json(self, temp_dir):
        """Test that main creates summary JSON file."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '5',
            'data/test.csv',
            '2'
        ]
        
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('test_run', True, 'Success')
                with patch('scripts.run_concurrency_test.Path') as mock_path:
                    with patch('scripts.run_concurrency_test.json.dump') as mock_json_dump:
                        try:
                            main()
                        except SystemExit:
                            pass
                        
                        # Check that json.dump was called
                        assert mock_json_dump.called

    def test_main_creates_unique_run_ids(self, temp_dir):
        """Test that main creates unique run IDs for each feed."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '5',
            'data/test.csv',
            '1'
        ]
        
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('test_run', True, 'Success')
                
                try:
                    main()
                except SystemExit:
                    pass
                
                # Should have called run_trial 10 times (5 kafka + 5 redis)
                assert mock_run_trial.call_count == 10
                
                # Check that all calls have unique run_ids
                run_ids = set()
                for call_args in mock_run_trial.call_args_list:
                    run_id = call_args[0][0]
                    assert run_id not in run_ids
                    run_ids.add(run_id)

    def test_main_handles_failures(self, temp_dir):
        """Test that main handles failed trials."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '1',
            'data/test.csv',
            '1'
        ]
        
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                # One success, one failure (for kafka and redis)
                mock_run_trial.side_effect = [
                    ('kafka_run', True, 'Success'),
                    ('redis_run', False, 'Error')
                ]
                
                with pytest.raises(SystemExit) as exc_info:
                    main()
                
                # Should exit with code 1 (failure)
                assert exc_info.value.code == 1

    def test_main_all_success_exit_zero(self, temp_dir):
        """Test that main exits with 0 when all succeed."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '1',
            'data/test.csv',
            '1'
        ]
        
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('test_run', True, 'Success')
                
                with pytest.raises(SystemExit) as exc_info:
                    main()
                
                # Should exit with code 0 (success)
                assert exc_info.value.code == 0

    def test_main_valid_concurrency_choices(self, temp_dir):
        """Test that main accepts valid concurrency choices."""
        for n in [1, 5, 10, 20]:
            test_args = [
                'scripts/run_concurrency_test.py',
                str(n),
                'data/test.csv',
                '1'
            ]
            
            with patch('sys.argv', test_args):
                with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                    mock_run_trial.return_value = ('test_run', True, 'Success')
                    
                    try:
                        main()
                    except SystemExit:
                        pass  # Expected
                    
                    # Each feed should have 2 calls (kafka + redis)
                    assert mock_run_trial.call_count == n * 2

    def test_main_invalid_concurrency_choice(self, temp_dir):
        """Test that main rejects invalid concurrency choices."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '3',  # Invalid - not in [1, 5, 10, 20]
            'data/test.csv',
            '1'
        ]
        
        with patch('sys.argv', test_args):
            with pytest.raises(SystemExit) as exc_info:
                main()
            
            # Should exit with code 2 (argument error)
            assert exc_info.value.code == 2

    def test_main_multiple_repetitions(self, temp_dir):
        """Test that main runs multiple repetitions."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '1',
            'data/test.csv',
            '3'  # 3 repetitions
        ]
        
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('test_run', True, 'Success')
                
                try:
                    main()
                except SystemExit:
                    pass
                
                # Should have 3 reps * 1 concurrency * 2 backends = 6 calls
                assert mock_run_trial.call_count == 6


class TestArgumentParsing:
    """Tests for argument parsing."""

    def test_default_arguments(self):
        """Test default argument values."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '5',
            'data/test.csv',
            '1'
        ]
        
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('test', True, 'Success')
                with patch('scripts.run_concurrency_test.datetime') as mock_datetime:
                    mock_datetime.now.return_value.strftime.return_value = '20260612_120000'
                    try:
                        main()
                    except SystemExit:
                        pass
                    
                    # Check that datetime.now was called for timestamp
                    mock_datetime.now.assert_called()

    def test_custom_speedup(self):
        """Test custom speedup argument."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '5',
            'data/test.csv',
            '1',
            '--speedup', '240'
        ]
        
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('test', True, 'Success')
                try:
                    main()
                except SystemExit:
                    pass
                
                # Check that speedup=240 was passed to run_trial
                for call_args in mock_run_trial.call_args_list:
                    assert call_args[0][3] == 240  # speedup parameter

    def test_custom_max_t_sim(self):
        """Test custom max_t_sim argument."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '5',
            'data/test.csv',
            '1',
            '--max-t-sim', '1200'
        ]
        
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('test', True, 'Success')
                try:
                    main()
                except SystemExit:
                    pass
                
                # Check that max_t_sim=1200 was passed to run_trial
                for call_args in mock_run_trial.call_args_list:
                    assert call_args[0][4] == 1200  # max_t_sim parameter

    def test_custom_kafka_bootstrap(self):
        """Test custom Kafka bootstrap argument."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '1',
            'data/test.csv',
            '1',
            '--kafka-bootstrap', 'custom:9092'
        ]
        
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('test', True, 'Success')
                try:
                    main()
                except SystemExit:
                    pass
                
                # Check that custom bootstrap was passed
                for call_args in mock_run_trial.call_args_list:
                    # bootstrap is the 6th parameter (index 5)
                    if call_args[0][2] == 'kafka':  # backend
                        assert call_args[0][5] == 'custom:9092'

    def test_custom_redis_host_port(self):
        """Test custom Redis host and port arguments."""
        test_args = [
            'scripts/run_concurrency_test.py',
            '1',
            'data/test.csv',
            '1',
            '--redis-host', 'custom-host',
            '--redis-port', '6380'
        ]
        
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('test', True, 'Success')
                try:
                    main()
                except SystemExit:
                    pass
                
                # Check that custom redis config was passed
                for call_args in mock_run_trial.call_args_list:
                    if call_args[0][2] == 'redis':  # backend
                        assert call_args[0][6] == 'custom-host'  # redis_host
                        assert call_args[0][7] == 6380  # redis_port


# Parametrized tests for edge cases

@pytest.mark.parametrize("backend", ["kafka", "redis"])
def test_run_trial_all_backends(backend, temp_dir):
    """Parametrized test for all supported backends."""
    with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
        
        result = run_trial(
            run_id=f"test_{backend}",
            plan_csv="data/test.csv",
            backend=backend,
            speedup=120,
            max_t_sim=600
        )
        
        assert result[1] is True


@pytest.mark.parametrize("speedup", [60, 120, 240, 480])
def test_run_trial_various_speedups(speedup, temp_dir):
    """Parametrized test with various speedup values."""
    with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
        
        result = run_trial(
            run_id="test_speedup",
            plan_csv="data/test.csv",
            backend="kafka",
            speedup=speedup,
            max_t_sim=600
        )
        
        assert result[1] is True


@pytest.mark.parametrize("max_t_sim", [60, 600, 6000])
def test_run_trial_various_max_t_sim(max_t_sim, temp_dir):
    """Parametrized test with various max_t_sim values."""
    with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
        
        result = run_trial(
            run_id="test_max_t_sim",
            plan_csv="data/test.csv",
            backend="kafka",
            speedup=120,
            max_t_sim=max_t_sim
        )
        
        assert result[1] is True


class TestBrokerCountAndClusterMode:
    """Tests for broker-count and cluster-mode parameters in run_concurrency_test.py."""

    def test_run_trial_with_broker_count(self, temp_dir):
        """Test run_trial with broker_count parameter."""
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            result = run_trial(
                run_id="test_broker_count",
                plan_csv="data/test.csv",
                backend="kafka",
                speedup=120,
                max_t_sim=600,
                bootstrap="localhost:9092",
                redis_host="localhost",
                redis_port=6379,
                topic="test-topic",
                broker_count=3,
                cluster_mode=False
            )
            
            assert result[0] == "test_broker_count"
            assert result[1] is True
            # Verify broker_count was passed to command
            call_args = mock_run.call_args[0][0]
            assert "-BROKER_COUNT 3" in str(call_args)

    def test_run_trial_with_cluster_mode(self, temp_dir):
        """Test run_trial with cluster_mode parameter for Redis."""
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            result = run_trial(
                run_id="test_cluster_mode",
                plan_csv="data/test.csv",
                backend="redis",
                speedup=120,
                max_t_sim=600,
                bootstrap="localhost:9092",
                redis_host="localhost",
                redis_port=6379,
                stream="test:stream",
                broker_count=3,
                cluster_mode=True
            )
            
            assert result[0] == "test_cluster_mode"
            assert result[1] is True
            # Verify cluster_mode was passed to command
            call_args = mock_run.call_args[0][0]
            assert "-CLUSTER_MODE" in str(call_args)
            assert "-NODE_COUNT 3" in str(call_args)

    def test_run_trial_producer_extra_kafka(self, temp_dir):
        """producer_extra is appended to the Kafka trial command."""
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            run_trial(
                run_id="test_pe", plan_csv="data/test.csv", backend="kafka",
                speedup=10, max_t_sim=600, bootstrap="localhost:19092",
                topic="t", producer_extra="--max-inflight 64",
            )
            cmd_str = str(mock_run.call_args[0][0])
            assert '-PRODUCER_EXTRA "--max-inflight 64"' in cmd_str

    def test_run_trial_producer_extra_not_for_redis(self, temp_dir):
        """producer_extra is ignored for the Redis backend (Kafka-only knob)."""
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            run_trial(
                run_id="test_pe_r", plan_csv="data/test.csv", backend="redis",
                speedup=10, max_t_sim=600, redis_host="localhost", redis_port=16379,
                stream="s", producer_extra="--max-inflight 64",
            )
            cmd_str = str(mock_run.call_args[0][0])
            assert 'PRODUCER_EXTRA' not in cmd_str

    def test_main_passes_kafka_producer_extra(self):
        """--kafka-producer-extra flows through to the Kafka run_trial call."""
        test_args = [
            'scripts/run_concurrency_test.py', '1', 'data/test.csv', '1',
            '--kafka-producer-extra', '--max-inflight 64',
        ]
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('test', True, 'Success')
                try:
                    main()
                except SystemExit:
                    pass
                kafka_calls = [c for c in mock_run_trial.call_args_list if c[0][2] == 'kafka']
                assert kafka_calls
                assert all(c[1].get('producer_extra') == '--max-inflight 64' for c in kafka_calls)

    def test_run_trial_broker_count_default(self, temp_dir):
        """Test run_trial with default broker_count (1)."""
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
            
            result = run_trial(
                run_id="test_broker_default",
                plan_csv="data/test.csv",
                backend="kafka",
                speedup=120,
                max_t_sim=600,
                bootstrap="localhost:9092",
                redis_host="localhost",
                redis_port=6379,
                topic="test-topic"
            )
            
            assert result[0] == "test_broker_default"
            assert result[1] is True
            # Verify default broker_count=1 was passed
            call_args = mock_run.call_args[0][0]
            assert "-BROKER_COUNT 1" in str(call_args)


class TestRedisConsumerExtra:
    """Passthrough for the ack-batching mitigation (tests hypothesis H5's prediction P4)."""

    def test_consumer_extra_appended_for_redis(self, temp_dir):
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            run_trial(run_id="t", plan_csv="p.csv", backend="redis", speedup=1, max_t_sim=600,
                      stream="s", consumer_extra="--ack-batch 200")
            assert '-CONSUMER_EXTRA "--ack-batch 200"' in str(mock_run.call_args[0][0])

    def test_consumer_extra_not_used_for_kafka(self, temp_dir):
        with patch('scripts.run_concurrency_test.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            run_trial(run_id="t", plan_csv="p.csv", backend="kafka", speedup=1, max_t_sim=600,
                      topic="t", consumer_extra="--ack-batch 200")
            assert "CONSUMER_EXTRA" not in str(mock_run.call_args[0][0])

    def test_main_passes_redis_consumer_extra(self):
        test_args = ['scripts/run_concurrency_test.py', '1', 'data/test.csv', '1',
                     '--redis-consumer-extra', '--ack-batch 200']
        with patch('sys.argv', test_args):
            with patch('scripts.run_concurrency_test.run_trial') as mock_run_trial:
                mock_run_trial.return_value = ('t', True, 'ok')
                try:
                    main()
                except SystemExit:
                    pass
                redis_calls = [c for c in mock_run_trial.call_args_list if c[0][2] == 'redis']
                assert redis_calls
                assert all(c[1].get('consumer_extra') == '--ack-batch 200' for c in redis_calls)
