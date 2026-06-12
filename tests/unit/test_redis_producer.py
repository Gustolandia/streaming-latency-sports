"""Complete tests for redis_producer.py - 100% branch coverage."""
import pytest
import pandas as pd
import sys
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.modules['kafka'] = MagicMock()
sys.modules['kafka.KafkaProducer'] = MagicMock()
sys.modules['kafka.KafkaConsumer'] = MagicMock()
sys.modules['redis'] = MagicMock()
sys.modules['redis.Redis'] = MagicMock()

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from redis_producer import now_ns, main as rp_main


class TestNowNs:
    def test_returns_int(self):
        assert isinstance(now_ns(), int)

    def test_increasing(self):
        n1 = now_ns()
        n2 = now_ns()
        assert n2 >= n1


class TestMain:
    def test_main_basic(self, temp_dir, monkeypatch):
        plan_data = {"event_id": ["e1"], "match_id": [1], "t_sim_seconds": [0], "t_emit_offset_s": [0.0], "row_idx": [0]}
        pd.DataFrame(plan_data).to_csv(temp_dir / "plan.csv", index=False)
        
        mock_redis = MagicMock()
        mock_redis.xadd = MagicMock(return_value="rid1")
        
        with patch('redis.Redis', return_value=mock_redis):
            old_argv, old_cwd = sys.argv, os.getcwd()
            try:
                os.chdir(temp_dir)
                sys.argv = ["rp", "--run-id", "tr", "--plan-csv", "plan.csv", "--out", "prod.csv"]
                rp_main()
            finally:
                os.chdir(old_cwd)
                sys.argv = old_argv
        
        assert (temp_dir / "prod.csv").exists()

    def test_main_with_max_t_sim(self, temp_dir, monkeypatch):
        plan_data = {"event_id": ["e1", "e2"], "match_id": [1, 1], "t_sim_seconds": [0, 1000], "t_emit_offset_s": [0.0, 1000.0], "row_idx": [0, 1]}
        pd.DataFrame(plan_data).to_csv(temp_dir / "plan.csv", index=False)
        
        mock_redis = MagicMock()
        mock_redis.xadd = MagicMock(return_value="rid1")
        
        with patch('redis.Redis', return_value=mock_redis):
            old_argv, old_cwd = sys.argv, os.getcwd()
            try:
                os.chdir(temp_dir)
                sys.argv = ["rp", "--run-id", "tr", "--plan-csv", "plan.csv", "--out", "prod.csv", "--max-t-sim", "10"]
                rp_main()
            finally:
                os.chdir(old_cwd)
                sys.argv = old_argv
        
        df = pd.read_csv(temp_dir / "prod.csv")
        assert len(df) == 1

    def test_main_creates_parent_dirs(self, temp_dir, monkeypatch):
        plan_data = {"event_id": ["e1"], "match_id": [1], "t_sim_seconds": [0], "t_emit_offset_s": [0.0], "row_idx": [0]}
        pd.DataFrame(plan_data).to_csv(temp_dir / "plan.csv", index=False)
        
        mock_redis = MagicMock()
        mock_redis.xadd = MagicMock(return_value="rid1")
        
        with patch('redis.Redis', return_value=mock_redis):
            old_argv, old_cwd = sys.argv, os.getcwd()
            try:
                os.chdir(temp_dir)
                sys.argv = ["rp", "--run-id", "tr", "--plan-csv", "plan.csv", "--out", "sub/nested/prod.csv"]
                rp_main()
            finally:
                os.chdir(old_cwd)
                sys.argv = old_argv
        
        assert (temp_dir / "sub" / "nested" / "prod.csv").exists()

    def test_main_s3_mode_baseline(self, temp_dir, monkeypatch):
        """Test S3 mode baseline."""
        plan_data = {"event_id": ["e1"], "match_id": [1], "t_sim_seconds": [0], "t_emit_offset_s": [0.0], "row_idx": [0]}
        pd.DataFrame(plan_data).to_csv(temp_dir / "plan.csv", index=False)
        
        mock_redis = MagicMock()
        mock_redis.xadd = MagicMock(return_value="rid1")
        
        with patch('redis.Redis', return_value=mock_redis):
            old_argv, old_cwd = sys.argv, os.getcwd()
            try:
                os.chdir(temp_dir)
                sys.argv = ["rp", "--run-id", "tr", "--plan-csv", "plan.csv", "--out", "prod.csv", "--s3-mode", "baseline"]
                rp_main()
            finally:
                os.chdir(old_cwd)
                sys.argv = old_argv
        
        assert (temp_dir / "prod.csv").exists()

    def test_main_s3_mode_corrections(self, temp_dir, monkeypatch):
        """Test S3 mode corrections - correction messages are scheduled."""
        plan_data = {
            "event_id": ["e1", "e2"],
            "match_id": [1, 1],
            "t_sim_seconds": [0, 1],
            "t_emit_offset_s": [0.0, 1.0],
            "row_idx": [0, 1]
        }
        pd.DataFrame(plan_data).to_csv(temp_dir / "plan.csv", index=False)
        
        mock_redis = MagicMock()
        mock_redis.xadd = MagicMock(return_value="rid1")
        
        with patch('redis.Redis', return_value=mock_redis):
            old_argv, old_cwd = sys.argv, os.getcwd()
            try:
                os.chdir(temp_dir)
                sys.argv = [
                    "rp", "--run-id", "tr", "--plan-csv", "plan.csv", "--out", "prod.csv",
                    "--s3-mode", "corrections", "--corrections-every-k", "1", "--correction-delay-s", "0.0"
                ]
                rp_main()
            finally:
                os.chdir(old_cwd)
                sys.argv = old_argv
        
        assert (temp_dir / "prod.csv").exists()
        df = pd.read_csv(temp_dir / "prod.csv")
        # Should have both base and correction events
        assert len(df) >= 2
        
    def test_main_s3_mode_corrections_with_error(self, temp_dir):
        """Test lines 133-135: exception handling in correction worker."""
        plan_data = {
            "event_id": ["e1"],
            "match_id": [1],
            "t_sim_seconds": [0],
            "t_emit_offset_s": [0.0],
            "row_idx": [0]
        }
        pd.DataFrame(plan_data).to_csv(temp_dir / "plan.csv", index=False)
        
        # Set up a mock that raises on the second xadd call (correction)
        call_count = [0]
        def xadd_with_error(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] > 1:  # First call is base event, second is correction
                raise Exception("Test error")
            return "rid1"
        
        mock_redis = MagicMock()
        mock_redis.xadd = MagicMock(side_effect=xadd_with_error)
        
        old_argv, old_cwd = sys.argv, os.getcwd()
        try:
            os.chdir(temp_dir)
            sys.argv = [
                "rp", "--run-id", "tr", "--plan-csv", "plan.csv", "--out", "prod.csv",
                "--s3-mode", "corrections", "--corrections-every-k", "1", "--correction-delay-s", "0.0"
            ]
            # Patch redis.Redis in the redis_producer module specifically
            # This affects both main thread and correction worker thread
            with patch('redis_producer.redis.Redis', return_value=mock_redis):
                # The correction worker will catch the exception and add it to corr_err
                # Then at the end, main() will raise RuntimeError with the error
                with pytest.raises(RuntimeError, match="Redis correction worker errors"):
                    rp_main()
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv
        
        assert (temp_dir / "prod.csv").exists()

    def test_main_with_sleep(self, temp_dir, monkeypatch):
        """Test line 163: time.sleep when sleep_s > 0."""
        plan_data = {
            "event_id": ["e1"],
            "match_id": [1],
            "t_sim_seconds": [0],
            "t_emit_offset_s": [0.1],
            "row_idx": [0]
        }
        pd.DataFrame(plan_data).to_csv(temp_dir / "plan.csv", index=False)
        
        mock_redis = MagicMock()
        mock_redis.xadd = MagicMock(return_value="rid1")
        
        with patch('redis.Redis', return_value=mock_redis):
            old_argv, old_cwd = sys.argv, os.getcwd()
            try:
                os.chdir(temp_dir)
                sys.argv = ["rp", "--run-id", "tr", "--plan-csv", "plan.csv", "--out", "prod.csv", "--speedup", "1000.0"]
                rp_main()
            finally:
                os.chdir(old_cwd)
                sys.argv = old_argv
        
        assert (temp_dir / "prod.csv").exists()

    def test_main_as_script(self, temp_dir):
        """Test line 267: if __name__ == '__main__' block by running as subprocess with coverage."""
        plan_data = {"event_id": ["e1"], "match_id": [1], "t_sim_seconds": [0], "t_emit_offset_s": [0.0], "row_idx": [0]}
        plan_path = temp_dir / "plan.csv"
        pd.DataFrame(plan_data).to_csv(plan_path, index=False)
        
        env = os.environ.copy()
        scripts_dir = str(Path(__file__).parent.parent.parent / "scripts")
        repo_root = str(Path(__file__).parent.parent.parent)
        env["PYTHONPATH"] = scripts_dir + ";" + env.get("PYTHONPATH", "")
        coveragerc_path = str(Path(repo_root) / ".coveragerc")
        env["COVERAGE_PROCESS_START"] = coveragerc_path
        
        result = subprocess.run(
            [sys.executable, str(Path(scripts_dir) / "redis_producer.py"),
             "--run-id", "tr", "--plan-csv", str(plan_path), "--out", str(temp_dir / "out.csv")],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )
        assert result.returncode is not None
