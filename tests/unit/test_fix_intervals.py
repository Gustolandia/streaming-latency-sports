"""Tests for scripts/fix_intervals.py: the moves' intervals and the module's cost."""
import csv
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import fix_intervals as fi  # noqa: E402


def rows(latency, values):
    """A run table: values maps (backend, load, priority) to each run's (median, p99)."""
    out = []
    for (b, load, p), runs in values.items():
        for i, (med, p99) in enumerate(runs):
            out.append({"backend": b, "load_pct": str(load), "priority": str(p),
                        "%s_median" % latency: str(med), "%s_p99" % latency: str(p99),
                        "D_median": str(med + 500), "D_p99": str(p99 + 900), "W_median": str(med),
                        "run": "r%d" % i})
    return out


def table(latency, spread=1.0, base=800.0):
    values = {}
    for b in fi.BACKENDS:
        for load in (fi.IDLE, fi.BUSY):
            for p in (False, True):
                values[(b, load, p)] = [(base + spread * i, 2 * base + spread * i)
                                        for i in range(6)]
    return rows(latency, values)


class TestMoves:
    def test_a_move_and_its_interval(self):
        assert fi.move([100.0, 100.0], [110.0, 110.0]) == 0.10
        lo, hi = fi.interval([100.0] * 6, [105.0] * 6, random.Random(1), resamples=50)
        assert lo == hi == 0.05

    def test_every_comparison_is_judged_against_its_band(self):
        out = fi.move_rows(table("W"), "F1", "W", resamples=40)
        assert len(out) == 16 and {r["statistic"] for r in out} == {"median", "p99"}
        assert all(r["point_inside"] and r["interval_inside"] for r in out)
        wide = fi.move_rows(table("W", spread=300.0), "F1", "W", resamples=200)
        assert any(r["point_inside"] and not r["interval_inside"] for r in wide), (
            "a point inside the band whose interval is not")

    def test_a_setup_with_no_runs_is_left_out(self):
        some = [r for r in table("W") if not (r["backend"] == "redis" and r["load_pct"] == "88")]
        out = fi.move_rows(some, "F1", "W", resamples=10)
        assert len(out) == 16 - 2 * 3, (
            "each statistic loses Redis's three comparisons that need its busy setups")


class TestTheCost:
    def test_the_clients_time_with_and_without_the_module(self):
        f1, f2 = table("W"), table("Wso")
        for r in f2:
            r["D_median"] = str(float(r["D_median"]) + 30)
        out = fi.cost_rows(f1, f2)
        assert len(out) == 8 and all(abs(r["client_change"] - 30.0) < 1e-9 for r in out)
        f2 = [r for r in f2 if r["backend"] == "kafka"]
        assert len(fi.cost_rows(f1, f2)) == 4, "a setup either block lacks is left out"


class TestTheCommandLine:
    def test_it_writes_both_tables(self, tmp_path, capsys):
        for name, latency in (("f1.csv", "W"), ("f2.csv", "Wso")):
            data = table(latency)
            if latency == "Wso":
                for r in data:
                    r["Wso_median"] = r["W_median"]
            with open(tmp_path / name, "w", encoding="utf-8", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(data[0]))
                w.writeheader()
                w.writerows(data)
        assert fi.main(["--f1", str(tmp_path / "f1.csv"), "--f2", str(tmp_path / "f2.csv"),
                        "--moves", str(tmp_path / "m.csv"), "--cost", str(tmp_path / "c.csv"),
                        "--resamples", "20"]) == 0
        assert "OK 32 comparisons" in capsys.readouterr().out
        assert len(list(csv.DictReader(open(tmp_path / "c.csv", encoding="utf-8")))) == 8
