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


# --- plan version 46 -------------------------------------------------------------------------

def pilot_row(backend, rate, load, rt, tc, w, wt="", ft=""):
    return {"backend": backend, "rate": str(rate), "load_pct": str(load), "priority": str(rt),
            "Tc_p99": str(tc), "W_p99": str(w), "W_tail": str(wt), "F_tail": str(ft)}


def pilot_rows(rt_w=1500.0):
    """Every cell idle (two runs), loaded and loaded at real-time priority (one run each)."""
    rows = []
    for backend in ("kafka", "redis"):
        for rate in (500, 2000):
            rows += [pilot_row(backend, rate, 0, False, 400, 1500, 2000, 1500),
                     pilot_row(backend, rate, 0, False, 420, 1600, 2100, 1550),
                     pilot_row(backend, rate, 70, False, 4000, 6000, 6500, 1800),
                     pilot_row(backend, rate, 70, True, 600, rt_w)]
    return rows


def test_a_pilots_table_gives_each_cell_its_runs():
    inputs = up.pilot_inputs(pilot_rows())
    assert sorted(inputs) == [("kafka", 500), ("kafka", 2000), ("redis", 500), ("redis", 2000)]
    cell = inputs[("kafka", 500)]
    assert cell["Tc"] == ((400.0, 420.0), (4000.0,), (600.0,))
    assert cell["Wt"] == ((2000.0, 2100.0), (6500.0,)) and cell["Ft"][1] == (1800.0,)
    partial = [r for r in pilot_rows() if not (r["backend"] == "redis" and r["priority"] == "True")]
    assert sorted(up.pilot_inputs(partial)) == [("kafka", 500), ("kafka", 2000)]


def test_version_46s_parameters_scale_every_loaded_setup():
    par = up.parameters46({"W": ((100.0, 100.0), (300.0,), (200.0,))}, 0.5)
    assert par["W"] == [(100.0, up.IDLE_CV), (200.0, up.LOAD_CV), (150.0, up.LOAD_CV)]


def test_one_cell_and_the_judges_way_of_counting_u_c():
    rng = random.Random(3)
    tight = lambda *means: [(m, 0.0001) for m in means]  # noqa: E731
    par = {"Tc": tight(400.0, 4000.0, 600.0), "W": tight(1500.0, 6000.0, 1500.0),
           "Wt": tight(2000.0, 6500.0), "Ft": tight(1500.0, 1800.0)}
    assert up.one_cell46(rng, par, 4) == (True, True, True, True, True)
    flat = {"Tc": tight(400.0, 400.0, 400.0), "W": tight(1500.0, 1500.0, 1500.0),
            "Wt": tight(2000.0, 1900.0), "Ft": tight(1500.0, 1500.0)}
    assert up.one_cell46(rng, flat, 4) == (False, False, False, False, False)
    yes, no = (True, True, True, True, True), (True, True, False, False, True)
    assert up.verdicts46([yes, no])["U-c"] and not up.verdicts46([yes, no])["U-b"]
    assert not up.verdicts46([no, no])["U-c"], "U-c is not confirmed where U-b holds nowhere"


def test_version_46s_joint_power_and_which_clauses_clear_their_margins():
    inputs = up.pilot_inputs(pilot_rows())
    p = up.joint_power46(inputs, 4, 100, 1.0, 7)
    assert set(p) == set(up.CLAUSES) and p == up.joint_power46(inputs, 4, 100, 1.0, 7)
    assert p["U-a growth"] > 0.9 and p["U-d"] > 0.9
    assert all(up.clears(inputs).values())
    marginal = up.clears(up.pilot_inputs(pilot_rows(rt_w=3500.0)))
    assert not marginal["U-d"] and marginal["U-b"]
    assert not any(up.clears({}).values())


def test_the_rounds_the_rule_asks(monkeypatch):
    inputs = up.pilot_inputs(pilot_rows())
    rounds, p = up.rounds_needed(inputs, 100, 7, start=4, most=5)
    assert rounds == 4 and p["U-c"] > up.POWER
    monkeypatch.setattr(up, "POWER", 1.01)
    rounds, p = up.rounds_needed(inputs, 20, 7, start=4, most=5)
    assert rounds is None and set(p) == set(up.CLAUSES)


def test_the_command_line_reads_a_pilots_table(tmp_path, capsys, monkeypatch):
    import csv
    path = str(tmp_path / "up_runs.csv")
    rows = pilot_rows(rt_w=3500.0)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    assert up.main(["--pilot-table", path, "--blocks", "60", "--most", "5"]) == 0
    out = capsys.readouterr().out
    assert "cells with every input: kafka 500, kafka 2000, redis 500, redis 2000" in out
    assert "U-d no" in out and "4 rounds, excess 0.50" in out and "the rule asks 4 rounds" in out
    monkeypatch.setattr(up, "POWER", 1.01)
    assert up.main(["--pilot-table", path, "--blocks", "20", "--most", "4"]) == 0
    assert "no number of rounds up to 4" in capsys.readouterr().out
