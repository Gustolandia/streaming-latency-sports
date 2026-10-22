"""Tests for scripts/under_load_power.py, the rounds rule for freeze 42's block U."""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import under_load_power as up  # noqa: E402


def test_a_spread_is_never_below_its_floor():
    assert up.mean_and_cv([100.0], 0.25) == (100.0, 0.25)
    m, cv = up.mean_and_cv([50.0, 150.0], 0.1)
    assert m == 100.0 and cv == pytest.approx(0.5)


def test_draws_keep_their_mean():
    rng = random.Random(1)
    values = [up.draw(rng, 200.0, 0.2) for _ in range(20000)]
    assert sum(values) / len(values) == pytest.approx(200.0, rel=0.02)


def test_the_loads_excess_is_scaled():
    par = up.parameters({"W": ((100.0, 100.0), (300.0, 300.0))}, 0.5)
    assert par["W"] == (100.0, up.IDLE_CV, 200.0, up.LOAD_CV)


def test_a_block_judges_the_three_clauses_as_the_design_states_them():
    rng = random.Random(2)
    plain = {"Tc": (100.0, 0.0001, 400.0, 0.0001), "W": (100.0, 0.0001, 400.0, 0.0001),
             "F": (100.0, 0.0001, 110.0, 0.0001)}
    assert up.one_block(rng, plain, 4) == (True, True, True)
    flat = {"Tc": (100.0, 0.0001, 100.0, 0.0001), "W": (100.0, 0.0001, 90.0, 0.0001),
            "F": (100.0, 0.0001, 90.0, 0.0001)}
    assert up.one_block(rng, flat, 4) == (False, False, False)


def test_the_simulation_is_fixed_by_its_seed():
    inputs = up.INPUTS[("redis", 2000)]
    a = up.power(inputs, 4, 200, 1.0, 7)
    assert a == up.power(inputs, 4, 200, 1.0, 7) and set(a) == {"U-a", "U-b", "U-c"}
    assert all(0.0 <= v <= 1.0 for v in a.values())
    rows = up.table(4, 50, 7)
    assert len(rows) == 2 * len(up.INPUTS) and {r[0] for r in rows} == {1.0, 0.5}


def test_the_joint_power_needs_all_four_cells_at_once():
    joint = up.joint_power(4, 300, 0.5, 7)
    alone = [up.power(up.INPUTS[k], 4, 300, 0.5, 7)["U-c"] for k in sorted(up.INPUTS)]
    assert joint["U-c"] <= min(alone) + 0.05 and set(joint) == {"U-a", "U-b", "U-c"}


def test_the_command_line_says_whether_four_rounds_are_enough(capsys, monkeypatch):
    assert up.main(["--blocks", "200"]) == 0
    out = capsys.readouterr().out
    assert "excess  broker  rate" in out and "at 4 rounds: enough" in out
    assert "all four cells at once, excess 0.50" in out
    monkeypatch.setattr(up, "POWER", 1.01)
    assert up.main(["--blocks", "50", "--rounds", "1"]) == 0
    assert "not enough" in capsys.readouterr().out
