"""Tests for scripts/analyze_runq_tail.py - target >=95% branch coverage.

This is the closing test of the mechanism, so the tests are built around the ways it could
flatter it. Data is synthesised for each of the three pre-registered outcomes and each must be
recognised, including REFUTED. The instrument check is tested for its ability to withhold a
result that would otherwise look like a clean match.
"""
import csv
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import analyze_runq_tail as art  # noqa: E402
from analyze_runq_tail import (  # noqa: E402
    parse_bpftrace,
    tail_probability,
    instrument_check,
    verdict,
    main,
)

# A realistic bpftrace dump: log2 histogram plus the exact threshold counters.
DUMP = """Attaching 4 probes...

@usecs:
[0]                  100 |@@@@                                    |
[1]                  400 |@@@@@@@@@@@@@@@@                        |
[2, 4)               900 |@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@    |
[4, 8)               600 |@@@@@@@@@@@@@@@@@@@@@@@@                |
[512, 1K)            180 |@@@@@@@                                 |
[1K, 2K)              20 |@                                       |

@count: 2200
@over_500us: 200
@over_1000us: 20
"""


def _cell(tmp, tag, dump=DUMP):
    d = tmp / tag
    d.mkdir(parents=True, exist_ok=True)
    (d / "runqlat.txt").write_text(dump, encoding="utf-8")
    return d


def _stats(rho, inv, n=3000):
    return {"rho": rho, "n_events": n, "n_runs": 5, "mu": 0.6, "sigma_core": 0.2,
            "tails": {0.0: inv}, "runs_z_median": -5.0}


class TestParse:
    def test_binary_suffixes_are_parsed(self, temp_dir):
        """A dump whose whole tail is suffixed. Dropping these would understate the tail and
        could turn a match into an apparent refutation, so it is asserted directly."""
        dump = "\n".join(["@usecs:", "[4, 8)  10 |@|", "[1K, 2K)  7 |@|",
                          "[2M, 4M)  3 |@|", ""])
        p = parse_bpftrace(_cell(temp_dir, "s", dump) / "runqlat.txt")
        assert (1024, 2048, 7) in p["hist"] and (2097152, 4194304, 3) in p["hist"]
        assert p["total"] == 20

    def test_reads_histogram_and_counters(self, temp_dir):
        p = parse_bpftrace(_cell(temp_dir, "x") / "runqlat.txt")
        assert p["counters"]["count"] == 2200
        assert p["counters"]["over_500us"] == 200
        # The K/M/G suffixes must be parsed, not dropped: these are the tail buckets.
        assert (512, 1024, 180) in p["hist"]
        assert (1024, 2048, 20) in p["hist"]

    def test_missing_file_returns_none(self, temp_dir):
        assert parse_bpftrace(temp_dir / "nope.txt") is None

    def test_empty_dump_returns_none(self, temp_dir):
        assert parse_bpftrace(_cell(temp_dir, "e", "Attaching 4 probes...\n\n")
                              / "runqlat.txt") is None

    def test_total_falls_back_to_the_histogram(self, temp_dir):
        d = _cell(temp_dir, "n", "@usecs:\n[0]   5 |@|\n[2, 4)   7 |@|\n")
        assert parse_bpftrace(d / "runqlat.txt")["total"] == 12


class TestTailProbability:
    def test_prefers_the_exact_counter(self, temp_dir):
        p = parse_bpftrace(_cell(temp_dir, "x") / "runqlat.txt")
        val, how = tail_probability(p, 500)
        assert val == pytest.approx(200 / 2200) and how == "exact counter"

    def test_falls_back_to_the_histogram_and_understates(self, temp_dir):
        """No counter for this threshold: only whole buckets above it are counted, which can
        only make the tail look SMALLER. A match found this way is not an estimator artefact."""
        p = parse_bpftrace(_cell(temp_dir, "x") / "runqlat.txt")
        val, how = tail_probability(p, 256)
        assert how == "histogram lower bound"
        assert val == pytest.approx(200 / 2200)      # the 512 and 1K buckets only

    def test_no_events_gives_none(self):
        assert tail_probability({"hist": [], "counters": {}, "total": 0}, 500)[0] is None

    def test_none_input_gives_none(self):
        assert tail_probability(None, 500)[0] is None


class TestInstrumentCheck:
    def test_passes_when_tracing_does_not_move_the_rate(self):
        c = instrument_check({"inversion": 0.2300}, 0.2214)
        assert c["checked"] and c["ok"] and c["drift"] < 0.25

    def test_fails_when_tracing_moves_the_rate(self):
        """A trace that changes the measurement describes a different machine."""
        c = instrument_check({"inversion": 0.5000}, 0.2214)
        assert c["checked"] and not c["ok"]

    def test_not_checked_without_a_baseline(self):
        assert not instrument_check({"inversion": 0.23}, None)["checked"]

    def test_not_checked_without_a_base_arm(self):
        assert not instrument_check(None, 0.2214)["checked"]


class TestVerdict:
    OK = {"checked": True, "ok": True}

    def _rows(self, p_base, inv_base, p_rt, inv_rt):
        return [{"arm": "base", "p_tail": p_base, "inversion": inv_base},
                {"arm": "rt", "p_tail": p_rt, "inversion": inv_rt}]

    def test_match_when_tail_tracks_the_rate_in_level_and_ratio(self):
        v = verdict(self._rows(0.22, 0.22, 0.005, 0.005), self.OK)
        assert v["decided"] and v["outcome"] == "MATCH"

    def test_wrong_scale_when_only_the_ratio_reproduces(self):
        """Tail is 10x the inversion rate in both arms: right ratio, wrong level."""
        v = verdict(self._rows(2.2, 0.22, 0.05, 0.005), self.OK)
        assert v["outcome"] == "WRONG SCALE" and v["ratio_ok"] and not v["levels_ok"]

    def test_refuted_when_the_tail_barely_moves(self):
        """The outcome that goes against the paper's own account."""
        v = verdict(self._rows(0.22, 0.22, 0.20, 0.005), self.OK)
        assert v["outcome"] == "REFUTED"

    def test_withheld_when_the_instrument_perturbed_the_measurement(self):
        v = verdict(self._rows(0.22, 0.22, 0.005, 0.005), {"checked": True, "ok": False})
        assert not v["decided"] and "instrument changed" in v["why"]

    def test_needs_both_arms(self):
        rows = [{"arm": "base", "p_tail": 0.2, "inversion": 0.2}]
        assert not verdict(rows, self.OK)["decided"]

    def test_needs_a_traced_tail_in_each_arm(self):
        rows = [{"arm": "base", "p_tail": None, "inversion": 0.2},
                {"arm": "rt", "p_tail": 0.005, "inversion": 0.005}]
        assert not verdict(rows, self.OK)["decided"]

    def test_zero_rt_tail_does_not_divide(self):
        v = verdict(self._rows(0.22, 0.22, 0.0, 0.005), self.OK)
        assert v["decided"] and v["tail_ratio"] == float("inf")


class TestMain:
    def _run(self, temp_dir, capsys, base_inv, rt_inv, untraced=0.2214, dumps=None):
        d = temp_dir / "ea9"
        _cell(d, "l88_base", (dumps or {}).get("base", DUMP))
        _cell(d, "l88_rt", (dumps or {}).get("rt", DUMP))
        stats = [_stats(0.88, base_inv), _stats(0.88, rt_inv)]
        with patch.object(art, "condition_stats", side_effect=stats):
            rc = main(["--depth", str(d), "--runs", "runs", "--untraced-base", str(untraced),
                       "--out", str(temp_dir / "o")])
        return rc, capsys.readouterr().out

    def test_reports_a_match(self, temp_dir, capsys):
        rt_dump = DUMP.replace("@over_500us: 200", "@over_500us: 11")
        rc, out = self._run(temp_dir, capsys, 0.2300, 0.0050, dumps={"rt": rt_dump})
        assert rc == 0 and "MATCH" in out
        rows = list(csv.DictReader(open(temp_dir / "o" / "runq_tail.csv")))
        assert len(rows) == 2 and rows[0]["estimator"] == "exact counter"

    def test_reports_refuted(self, temp_dir, capsys):
        _, out = self._run(temp_dir, capsys, 0.2300, 0.0050)   # identical dumps: tail unmoved
        assert "REFUTED" in out

    def test_two_levels_in_one_directory_are_refused(self, temp_dir, capsys):
        """E-A9b writes l75 and l88 into one directory, and the script picked whichever arm
        sorted first. Given the 88% baseline it compared the 75% traced arm against it, reported
        42.3% drift and withheld everything -- a spurious verdict from a comparison across load
        levels that nobody asked for."""
        d = temp_dir / "ea9b"
        for tag in ("l75_base", "l75_rt", "l88_base", "l88_rt"):
            _cell(d, tag, DUMP)
        rc = main(["--depth", str(d), "--runs", "runs", "--untraced-base", "0.2214",
                   "--out", str(temp_dir / "o")])
        out = capsys.readouterr().out
        assert rc == 1
        assert "2 load levels" in out and "l75" in out and "l88" in out
        # The refusal message explains itself using the word "verdict", so look for the
        # section header the script prints when it actually reaches one.
        assert "== verdict ==" not in out, "no verdict may be reached for a refused directory"
        assert "PERTURBED" not in out, "no instrument check may run across levels either"

    def test_an_unknown_level_is_an_error(self, temp_dir, capsys):
        d = temp_dir / "ea9b"
        _cell(d, "l75_base", DUMP)
        _cell(d, "l75_rt", DUMP)
        assert main(["--depth", str(d), "--runs", "runs", "--level", "l99",
                     "--out", str(temp_dir / "o")]) == 1
        assert "no such level" in capsys.readouterr().out

    def test_a_zero_arm_prints_its_own_verdict_not_REFUTED(self, temp_dir, capsys):
        """verdict() had a branch for the zero arm and the printer did not.

        Everything that was not MATCH or WRONG SCALE fell through to "REFUTED. The traced tail
        does not move with the inversion rate." So a LEVEL MATCH -- the positive result -- was
        announced as the strongest negative the script can emit. The E-A9b 75% level hit exactly
        this, and reading the printed line rather than the CSV would have retracted a finding
        that had not failed.
        """
        rt_dump = DUMP.replace("@over_500us: 200", "@over_500us: 11")
        _, out = self._run(temp_dir, capsys, 0.2300, 0.0, dumps={"rt": rt_dump})
        assert "LEVEL MATCH, RATIO UNTESTABLE" in out
        assert "REFUTED" not in out
        assert "undefined here rather than answered" in out

    def test_a_zero_arm_with_a_bad_level_prints_mismatch_not_REFUTED(self, temp_dir, capsys):
        """The other zero-arm outcome needs its own wording too, for the same reason."""
        base_dump = DUMP.replace("@over_500us: 200", "@over_500us: 995")
        rt_dump = DUMP.replace("@over_500us: 200", "@over_500us: 11")
        _, out = self._run(temp_dir, capsys, 0.0100, 0.0,
                           dumps={"base": base_dump, "rt": rt_dump}, untraced=0.0100)
        assert "LEVEL MISMATCH" in out
        assert "REFUTED" not in out

    def test_withholds_when_tracing_perturbed_the_run(self, temp_dir, capsys):
        _, out = self._run(temp_dir, capsys, 0.5000, 0.0050)
        assert "PERTURBED" in out and "UNDECIDED" in out

    def test_runs_without_an_untraced_baseline(self, temp_dir, capsys):
        d = temp_dir / "ea9"
        _cell(d, "l88_base"); _cell(d, "l88_rt")
        with patch.object(art, "condition_stats",
                          side_effect=[_stats(0.88, 0.23), _stats(0.88, 0.005)]):
            main(["--depth", str(d), "--runs", "runs", "--out", str(temp_dir / "o")])
        out = capsys.readouterr().out
        assert "not checked" in out and "UNDECIDED" in out

    def test_skips_arms_without_run_data(self, temp_dir, capsys):
        d = temp_dir / "ea9"
        _cell(d, "l88_base"); _cell(d, "l88_rt")
        with patch.object(art, "condition_stats", return_value=None):
            rc = main(["--depth", str(d), "--runs", "runs", "--out", str(temp_dir / "o")])
        assert rc == 1 and "no arm has both" in capsys.readouterr().out

    def test_ignores_unknown_arm_directories(self, temp_dir, capsys):
        d = temp_dir / "ea9"
        _cell(d, "l88_base"); _cell(d, "l88_rt"); _cell(d, "l88_other")
        (d / "notes.txt").write_text("x", encoding="utf-8")
        with patch.object(art, "condition_stats",
                          side_effect=[_stats(0.88, 0.23), _stats(0.88, 0.005)]):
            main(["--depth", str(d), "--runs", "runs", "--out", str(temp_dir / "o")])
        rows = list(csv.DictReader(open(temp_dir / "o" / "runq_tail.csv")))
        assert {r["arm"] for r in rows} == {"base", "rt"}

    def test_reports_wrong_scale_end_to_end(self, temp_dir, capsys):
        """Ratio reproduces, absolute level does not. The honest middle outcome."""
        base = DUMP.replace("@over_500us: 200", "@over_500us: 2000").replace(
            "@count: 2200", "@count: 2200")
        rt = DUMP.replace("@over_500us: 200", "@over_500us: 44")
        _, out = self._run(temp_dir, capsys, 0.2300, 0.0050,
                           dumps={"base": base, "rt": rt})
        assert "RIGHT RATIO, WRONG LEVEL" in out

    def test_arm_directory_without_a_trace_is_skipped(self, temp_dir, capsys):
        """A cell whose bpftrace output never appeared must not be silently counted."""
        d = temp_dir / "ea9"
        (d / "l88_base").mkdir(parents=True)          # no runqlat.txt
        _cell(d, "l88_rt")
        with patch.object(art, "condition_stats", return_value=_stats(0.88, 0.005)):
            main(["--depth", str(d), "--runs", "runs", "--out", str(temp_dir / "o")])
        rows = list(csv.DictReader(open(temp_dir / "o" / "runq_tail.csv")))
        assert [r["arm"] for r in rows] == ["rt"]

    def test_missing_directory(self, temp_dir, capsys):
        assert main(["--depth", str(temp_dir / "nope")]) == 1
        assert "missing campaign directory" in capsys.readouterr().out


class TestArmDrivenToZero:
    """The real-time arm recorded exactly ZERO inversions in E-A9.

    An earlier version required inversion > 0 for a row to be usable, which dropped that arm and
    reported UNDECIDED while the base arm was showing a clean quantitative match. An arm driven
    to the floor is the strongest form of the predicted direction; discarding it for being
    awkward to divide by is the wrong instinct.
    """
    OK = {"checked": True, "ok": True}

    def _real(self):
        return [{"arm": "base", "p_tail": 0.18068, "inversion": 0.23149},
                {"arm": "rt", "p_tail": 0.01845, "inversion": 0.0}]

    def test_the_level_match_survives_a_zero_arm(self):
        v = verdict(self._real(), self.OK)
        assert v["decided"] and v["levels_ok"]
        assert v["outcome"] == "LEVEL MATCH, RATIO UNTESTABLE"
        assert v["base_level"] == pytest.approx(0.78, abs=0.01)

    def test_the_ratio_test_is_undefined_not_passed(self):
        """With no finite inversion ratio there is nothing to compare the tail ratio against.
        Reporting that as a pass would claim a test that was never run."""
        v = verdict(self._real(), self.OK)
        assert v["ratio_ok"] is None and v["rt_floored"]

    def test_the_tail_ratio_is_still_reported(self):
        v = verdict(self._real(), self.OK)
        assert v["tail_ratio"] == pytest.approx(9.79, abs=0.05)

    def test_a_zero_arm_with_a_bad_level_is_a_mismatch(self):
        rows = [{"arm": "base", "p_tail": 0.99, "inversion": 0.01},
                {"arm": "rt", "p_tail": 0.5, "inversion": 0.0}]
        assert verdict(rows, self.OK)["outcome"] == "LEVEL MISMATCH"

    def test_a_zero_base_arm_gives_nothing_to_account_for(self):
        rows = [{"arm": "base", "p_tail": 0.18, "inversion": 0.0},
                {"arm": "rt", "p_tail": 0.02, "inversion": 0.0}]
        assert not verdict(rows, self.OK)["decided"]


class TestTheDepthDirectoryAsItIsFoundOnDisk:

    def test_an_arm_that_is_not_a_directory_yields_nothing(self, temp_dir):
        """`load_arm` is given a name from a glob, and a glob matches files too."""
        (temp_dir / "l95_base").write_text("not a directory", encoding="utf-8")
        assert art.load_arm(str(temp_dir), "l95_base", "runs") is None

    def test_an_arm_that_does_not_exist_yields_nothing(self, temp_dir):
        assert art.load_arm(str(temp_dir), "l95_never", "runs") is None

    def test_a_file_beside_the_cells_is_stepped_over(self, temp_dir, capsys):
        _cell(temp_dir, "l95_base")
        _cell(temp_dir, "l95_rt")
        (temp_dir / "l95_notes").write_text("x", encoding="utf-8")
        with patch.object(art, "condition_stats", side_effect=[_stats(0.95, 0.30),
                                                               _stats(0.95, 0.01)]):
            main(["--depth", str(temp_dir), "--runs", "runs",
                  "--out", str(temp_dir / "out")])
        assert "l95" in capsys.readouterr().out

    def test_asking_for_one_level_analyses_only_that_level(self, temp_dir, capsys):
        """Two levels in one directory cannot be analysed together: the instrument check and
        the verdict are both per-level, so pooling them compares arms across levels."""
        for tag in ("l70_base", "l70_rt", "l95_base", "l95_rt"):
            _cell(temp_dir, tag)
        with patch.object(art, "condition_stats", return_value=_stats(0.95, 0.10)):
            code = main(["--depth", str(temp_dir), "--runs", "runs",
                         "--level", "l95", "--out", str(temp_dir / "out")])
        out = capsys.readouterr().out
        assert code in (0, 1)
        assert "l70" not in out, "the level that was not asked for must not be analysed"

    def test_asking_for_a_level_that_is_not_there_is_refused(self, temp_dir, capsys):
        for tag in ("l95_base", "l95_rt"):
            _cell(temp_dir, tag)
        assert main(["--depth", str(temp_dir), "--runs", "runs",
                     "--level", "l70", "--out", str(temp_dir / "out")]) == 1
        assert "no such level" in capsys.readouterr().out
