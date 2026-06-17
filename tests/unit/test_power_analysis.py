"""Tests for scripts/power_analysis.py - target >=95% coverage."""
import json
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

import power_analysis
from power_analysis import (
    achieved_power,
    required_sample_size,
    analyze_power,
    main,
)


class TestAchievedPower:
    def test_zero_when_tiny_sample(self):
        assert achieved_power(0.5, 1) == 0.0

    def test_zero_effect(self):
        assert achieved_power(0.0, 100) == 0.0

    def test_power_increases_with_n(self):
        assert achieved_power(0.5, 100) > achieved_power(0.5, 10)

    def test_power_in_unit_interval(self):
        p = achieved_power(0.8, 50)
        assert 0.0 <= p <= 1.0


class TestRequiredSampleSize:
    def test_zero_effect_infinite(self):
        assert required_sample_size(0.0) == float("inf")

    def test_smaller_effect_needs_more(self):
        assert required_sample_size(0.2) > required_sample_size(0.8)

    def test_returns_int(self):
        assert isinstance(required_sample_size(0.5), int)


class TestAnalyzePower:
    def test_structure(self):
        rep = analyze_power(20)
        assert rep["n_per_group"] == 20
        assert set(rep["by_effect_size"]) == {"small", "medium", "large"}
        for r in rep["by_effect_size"].values():
            assert "required_n_per_group" in r
            assert "achieved_power_at_n" in r
            assert "adequately_powered" in r

    def test_custom_effect_sizes(self):
        rep = analyze_power(30, effect_sizes={"tiny": 0.1})
        assert list(rep["by_effect_size"]) == ["tiny"]

    def test_large_n_adequately_powered_for_medium(self):
        rep = analyze_power(500)
        assert rep["by_effect_size"]["medium"]["adequately_powered"] is True


class TestFallback:
    def test_normal_approx_matches_when_forced(self, monkeypatch):
        # Force the fallback path and confirm it returns sane values
        monkeypatch.setattr(power_analysis, "_HAVE_SM", False)
        assert 0.0 <= achieved_power(0.5, 40) <= 1.0
        assert required_sample_size(0.5) > 0


class TestMain:
    def test_main_writes_output(self, temp_dir, capsys):
        out = temp_dir / "power.json"
        rc = main(["--n", "20", "--out", str(out)])
        assert rc == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["n_per_group"] == 20
        captured = capsys.readouterr()
        assert "Power analysis" in captured.out

    def test_main_custom_params(self, temp_dir):
        out = temp_dir / "sub" / "power.json"
        rc = main(["--n", "64", "--alpha", "0.01", "--power", "0.9", "--out", str(out)])
        assert rc == 0
        assert out.exists()
