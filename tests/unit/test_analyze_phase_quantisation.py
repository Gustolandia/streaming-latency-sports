"""Tests for analyze_phase_quantisation.

The script decides whether the phase effect is binary (commensurate or not) or quantised by the
denominator q. The verdict that matters most is UNDECIDED: with only q=1 and large-q rates
measured, the quantisation rule is untested, and a tool that announced a rule from those two
points would be doing what this paper spends a section warning against.

The exact-fraction arithmetic is also load-bearing. 2.000 and 2.188 must not both round to
"close enough to 2", which is why the denominator is computed with Fraction rather than floats.
"""
import csv
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_phase_quantisation import (  # noqa: E402
    MAX_MEANINGFUL_Q, group_by_rate, load_rate_cells, main, phase_denominator, report, verdict,
)

FIELDS = ("campaign", "cell", "level", "valid", "count_source",
          "kept", "discarded_zero", "discarded_negative")


def write_ledger(path, rows):
    """rows: (rate, retention_pct[, campaign, valid, count_source])"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for i, r in enumerate(rows):
            rate, ret = r[0], r[1]
            camp = r[2] if len(r) > 2 else "rate_phase"
            valid = r[3] if len(r) > 3 else "1"
            src = r[4] if len(r) > 4 else "shutdown_hook"
            kept = int(round(ret * 1000))
            zero = 100000 - kept
            w.writerow([camp, f"r{rate}_rep{i}", rate, valid, src, kept, zero, 0])


class TestPhaseDenominator:
    def test_exact_multiples_give_one(self):
        for rate in (1000, 500, 250, 200, 125):
            assert phase_denominator(rate) == 1, f"{rate}/s should be q=1"

    def test_half_integer_gives_two(self):
        assert phase_denominator(400) == 2      # 2.5 ms = 5/2

    def test_thirds_give_three(self):
        assert phase_denominator(300) == 3      # 10/3 ms

    def test_quarters_give_four(self):
        assert phase_denominator(800) == 4      # 1.25 ms = 5/4

    def test_an_awkward_rate_gives_a_large_denominator(self):
        """457/s is 2.188 ms; it must not collapse to 'about 2'."""
        assert phase_denominator(457) > MAX_MEANINGFUL_Q

    def test_exact_arithmetic_separates_near_neighbours(self):
        """The whole result rests on 2.000 and 2.188 being different in kind."""
        assert phase_denominator(500) == 1
        assert phase_denominator(457) != 1

    def test_a_different_tick_rescales(self):
        # At a 2 ms tick, 1000/s gives interval/tick = 0.5 = 1/2, so q=2.
        assert phase_denominator(1000, tick_ms=2.0) == 2

    def test_nonsense_input_is_none(self):
        assert phase_denominator(0) is None
        assert phase_denominator(500, tick_ms=0) is None


class TestLoading:
    def test_only_rate_campaigns_contribute(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 50.0), (500, 50.0, "load_sweep")])
        assert len(load_rate_cells(str(p))) == 1

    def test_invalid_and_quantised_cells_excluded(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 50.0, "rate_phase", "0"),
                         (500, 50.0, "rate_phase", "1", "periodic_quantised"),
                         (500, 50.0)])
        assert len(load_rate_cells(str(p))) == 1

    def test_retention_is_recovered(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 42.5)])
        assert load_rate_cells(str(p))[0]["retention"] == pytest.approx(42.5, abs=0.01)

    def test_unparseable_counts_are_skipped_not_fatal(self, tmp_path):
        """A malformed row must not take the whole analysis down with it."""
        p = tmp_path / "l.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(FIELDS)
            w.writerow(["rate_phase", "bad", "n/a", "1", "shutdown_hook", "x", "y", ""])
            w.writerow(["rate_phase", "ok", "500", "1", "shutdown_hook", "50000", "50000", "0"])
        got = load_rate_cells(str(p))
        assert len(got) == 1 and got[0]["rate"] == 500

    def test_a_cell_that_saw_nothing_is_skipped(self, tmp_path):
        p = tmp_path / "l.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(FIELDS)
            w.writerow(["rate_phase", "empty", "500", "1", "shutdown_hook", "0", "0", "0"])
        assert load_rate_cells(str(p)) == []


class TestGrouping:
    def test_spread_and_q_per_rate(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0), (457, 50.0), (457, 51.0)])
        g = {x["rate"]: x for x in group_by_rate(load_rate_cells(str(p)))}
        assert g[500]["q"] == 1 and g[500]["spread"] == pytest.approx(98.0, abs=0.1)
        assert g[457]["commensurate"] is False
        assert g[457]["spread"] == pytest.approx(1.0, abs=0.1)

    def test_a_single_replicate_has_no_spread(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 50.0)])
        assert group_by_rate(load_rate_cells(str(p)))[0]["spread"] is None

    def test_predicted_spread_is_100_over_q(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [(400, 10.0), (400, 60.0)])
        g = group_by_rate(load_rate_cells(str(p)))[0]
        assert g["q"] == 2 and g["predicted_spread"] == pytest.approx(50.0)


class TestVerdict:
    def _g(self, *specs):
        """specs: (q_rate, spread)"""
        return [{"rate": r, "q": phase_denominator(r), "spread": s,
                 "commensurate": phase_denominator(r) <= MAX_MEANINGFUL_Q}
                for r, s in specs]

    def test_only_the_extremes_is_undecided(self):
        """The state this tool was written in: a rule announced here would be unfounded."""
        v = verdict(self._g((500, 99.0), (457, 2.0)))
        assert not v["decided"] and "untested" in v["why"]

    def test_no_incommensurate_rate_is_undecided(self):
        v = verdict(self._g((500, 99.0), (400, 50.0)))
        assert not v["decided"]

    def test_a_falling_spread_is_quantised(self):
        v = verdict(self._g((500, 99.0), (400, 50.0), (300, 33.0), (800, 25.0), (457, 2.0)))
        assert v["outcome"] == "QUANTISED"

    def test_intermediate_q_behaving_like_multiples_is_binary(self):
        v = verdict(self._g((500, 99.0), (400, 97.0), (300, 96.0), (457, 2.0)))
        assert v["outcome"].startswith("BINARY (any rational")

    def test_intermediate_q_behaving_like_incommensurate_is_binary(self):
        v = verdict(self._g((500, 99.0), (400, 3.0), (300, 4.0), (457, 2.0)))
        assert v["outcome"].startswith("BINARY (only exact")

    def test_disordered_intermediates_are_unclear(self):
        v = verdict(self._g((500, 99.0), (400, 20.0), (300, 80.0), (457, 2.0)))
        assert v["outcome"] == "UNCLEAR"


class TestCLI:
    def test_it_reports_and_writes(self, tmp_path, capsys):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0), (457, 50.0), (457, 51.0)])
        out = tmp_path / "q.csv"
        assert main(["--ledger", str(p), "--out", str(out)]) == 0
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert {r["rate_hz"] for r in rows} == {"500", "457"}
        assert "phase denominator" in capsys.readouterr().out

    def test_the_quantised_narrative_only_prints_when_earned(self, tmp_path, capsys):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0), (457, 50.0), (457, 51.0)])
        main(["--ledger", str(p)])
        assert "rule is arithmetic" not in capsys.readouterr().out

    def test_the_quantised_narrative_prints_when_the_curve_holds(self, tmp_path, capsys):
        """The payoff sentence: safety comes from a large denominator, not a chosen rate."""
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0),          # q=1  -> spread 98
                         (400, 25.0), (400, 74.0),          # q=2  -> spread 49
                         (300, 40.0), (300, 74.0),          # q=3  -> spread 34
                         (457, 50.0), (457, 52.0)])         # large q -> spread 2
        assert main(["--ledger", str(p)]) == 0
        out = capsys.readouterr().out
        assert "QUANTISED" in out
        assert "rule is arithmetic" in out
        assert "large denominator" in out

    def test_a_missing_ledger_is_an_error(self, tmp_path, capsys):
        assert main(["--ledger", str(tmp_path / "no.csv")]) == 1
        assert "missing" in capsys.readouterr().out

    def test_a_ledger_without_rate_cells_is_an_error(self, tmp_path, capsys):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 50.0, "load_sweep")])
        assert main(["--ledger", str(p)]) == 1
        assert "no rate-varying cells" in capsys.readouterr().out

    def test_an_undecided_run_says_so(self, tmp_path, capsys):
        p = tmp_path / "l.csv"
        write_ledger(p, [(500, 1.0), (500, 99.0)])
        main(["--ledger", str(p)])
        assert "UNDECIDED" in capsys.readouterr().out
