"""Tests for scripts/analyze_occupancy_law.py - target >=95% branch coverage.

Each law is asserted from both sides: data that satisfies it must be recognised, and data that
breaks it must be rejected. The geometry law gets the most attention because its argument is
logical rather than statistical -- one dominating pair refutes every monotone function of rho -
so the test must confirm the script does not water that down into a majority vote.
"""
import csv
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_occupancy_law import (  # noqa: E402
    load_pooled,
    load_priority,
    law_floor,
    law_ceiling,
    law_geometry,
    implied_occupancy,
    main,
)


def _pooled(tmp, rows, name="pooled.csv"):
    p = tmp / name
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["phase", "condition", "rho", "inversion_rate"])
        w.writeheader()
        for phase, cond, rho, inv in rows:
            w.writerow({"phase": phase, "condition": cond, "rho": rho, "inversion_rate": inv})
    return p


def _priority(tmp, rows, name="prio.csv"):
    p = tmp / name
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["level", "rho_base", "rho_rt", "inv_base", "inv_rt",
                                           "ratio", "disjoint", "n_base", "n_rt", "confounded"])
        w.writeheader()
        for lvl, rho, base, rt, conf in rows:
            w.writerow({"level": lvl, "rho_base": rho, "rho_rt": rho, "inv_base": base,
                        "inv_rt": rt, "ratio": rt / base, "disjoint": True,
                        "n_base": 3000, "n_rt": 3000, "confounded": conf})
    return p


# The measured ladder, so the tests exercise the shape the script actually meets.
REAL = [("ea3", "bg0", 0.0025, 0.00369), ("ea_sat", "bg0", 0.0025, 0.00335),
        ("ea3", "bg4", 0.5037, 0.00637), ("ea3", "bg5", 0.6284, 0.02446),
        ("ea4", "l70", 0.7032, 0.11089), ("ea3", "bg6", 0.7531, 0.07638),
        ("ea4", "l88", 0.8812, 0.22781), ("ea3", "bg7", 0.8775, 0.22379),
        ("ea4", "l95", 0.9501, 0.29715), ("ea4", "l99", 0.99, 0.32864),
        ("ea3", "bg8", 1.0, 0.37052)]
REAL_PRIO = [("l75", 0.75312, 0.13199, 0.00335, "False"),
             ("l88", 0.88089, 0.30486, 0.00570, "False")]


class TestLoading:
    def test_geometry_is_assigned_by_campaign(self, temp_dir):
        rows = load_pooled(str(_pooled(temp_dir, REAL)))
        by = {(r["phase"], r["geometry"]) for r in rows}
        assert ("ea4", "spread") in by and ("ea3", "concentrated") in by

    def test_rows_come_back_sorted_by_rho(self, temp_dir):
        rows = load_pooled(str(_pooled(temp_dir, REAL)))
        assert rows == sorted(rows, key=lambda r: r["rho"])

    def test_malformed_pooled_rows_skipped(self, temp_dir):
        p = temp_dir / "bad.csv"
        p.write_text("phase,condition,rho,inversion_rate\nea3,x,notanumber,0.1\n",
                     encoding="utf-8")
        assert load_pooled(str(p)) == []

    def test_confounded_priority_rows_are_dropped(self, temp_dir):
        p = _priority(temp_dir, [("l75", 0.75, 0.13, 0.003, "True"),
                                 ("l88", 0.88, 0.30, 0.006, "False")])
        rows = load_priority(str(p))
        assert len(rows) == 1 and rows[0]["level"] == "l88"

    def test_malformed_priority_rows_skipped(self, temp_dir):
        p = temp_dir / "bad2.csv"
        p.write_text("level,rho_base,inv_base,inv_rt,confounded\nl1,x,y,z,False\n",
                     encoding="utf-8")
        assert load_priority(str(p)) == []


class TestFloorLaw:
    def test_holds_when_the_real_time_floor_matches_idle(self, temp_dir):
        r = law_floor(load_pooled(str(_pooled(temp_dir, REAL))),
                      load_priority(str(_priority(temp_dir, REAL_PRIO))))
        assert r["testable"] and r["holds"] and r["ratio"] < 2.0

    def test_fails_when_the_floor_is_far_above_idle(self, temp_dir):
        """If real-time stamping under load were much worse than idle, the two states would not
        be the same state and the decomposition would be wrong."""
        bad = [("l75", 0.75, 0.13, 0.05, "False"), ("l88", 0.88, 0.30, 0.06, "False")]
        r = law_floor(load_pooled(str(_pooled(temp_dir, REAL))),
                      load_priority(str(_priority(temp_dir, bad))))
        assert r["testable"] and not r["holds"]

    def test_not_testable_without_idle_conditions(self, temp_dir):
        loaded_only = [row for row in REAL if row[2] > 0.5]
        r = law_floor(load_pooled(str(_pooled(temp_dir, loaded_only))),
                      load_priority(str(_priority(temp_dir, REAL_PRIO))))
        assert not r["testable"]

    def test_not_testable_without_real_time_arms(self, temp_dir):
        r = law_floor(load_pooled(str(_pooled(temp_dir, REAL))), [])
        assert not r["testable"]


class TestCeilingLaw:
    def test_holds_on_the_measured_ladder(self, temp_dir):
        r = law_ceiling(load_pooled(str(_pooled(temp_dir, REAL))))
        assert r["testable"] and r["holds"] and r["ceiling"] < 0.6

    def test_fails_when_the_rate_climbs_toward_one(self, temp_dir):
        """A rate approaching 1 has no ceiling worth claiming and p*S would not bound it."""
        rows = REAL[:-3] + [("ea4", "l95", 0.9501, 0.85), ("ea4", "l97", 0.97, 0.92),
                            ("ea4", "l99", 0.99, 0.97)]
        r = law_ceiling(load_pooled(str(_pooled(temp_dir, rows))))
        assert r["testable"] and not r["holds"]

    def test_fails_when_campaigns_disagree_about_the_ceiling(self, temp_dir):
        rows = REAL[:-3] + [("ea4", "l95", 0.9501, 0.30), ("ea4", "l99", 0.99, 0.33),
                            ("ea9", "x", 0.96, 0.02), ("ea9", "y", 0.98, 0.03)]
        r = law_ceiling(load_pooled(str(_pooled(temp_dir, rows))))
        assert r["testable"] and not r["holds"], "a ceiling that moves between campaigns is none"

    def test_not_testable_with_too_few_high_conditions(self, temp_dir):
        low = [row for row in REAL if row[2] < 0.9]
        assert not law_ceiling(load_pooled(str(_pooled(temp_dir, low))))["testable"]


class TestGeometryLaw:
    def test_one_dominating_pair_is_enough(self, temp_dir):
        """The argument is a contradiction, not a vote: a single pair must carry it."""
        rows = [("ea3", "a", 0.60, 0.050), ("ea3", "b", 0.80, 0.060),
                ("ea4", "c", 0.70, 0.090)]      # spread at 0.70 beats concentrated at 0.80
        r = law_geometry(load_pooled(str(_pooled(temp_dir, rows))))
        assert r["testable"] and r["holds"] and r["n_dominating"] >= 1

    def test_not_supported_when_rho_explains_everything(self, temp_dir):
        """Both geometries on one increasing curve in rho: nothing to see, and the script
        must not manufacture support from matched pairs alone."""
        rows = [("ea3", "a", 0.60, 0.05), ("ea3", "b", 0.80, 0.15),
                ("ea4", "c", 0.70, 0.10), ("ea4", "d", 0.90, 0.25)]
        r = law_geometry(load_pooled(str(_pooled(temp_dir, rows))))
        assert r["testable"] and not r["holds"] and r["n_dominating"] == 0

    def test_saturated_cells_are_not_used_as_partners(self, temp_dir):
        """rho pinned at 1.000 is unresolved, so 'lower rho' against it means nothing."""
        rows = [("ea3", "sat", 1.0, 0.02), ("ea4", "c", 0.70, 0.30)]
        r = law_geometry(load_pooled(str(_pooled(temp_dir, rows))))
        assert not r["testable"] or r["n_dominating"] == 0

    def test_matched_pairs_are_reported_separately(self, temp_dir):
        rows = [("ea3", "a", 0.8775, 0.22379), ("ea4", "b", 0.8812, 0.22781)]
        r = law_geometry(load_pooled(str(_pooled(temp_dir, rows))))
        assert r["n_matched"] == 1 and r["matched"][0]["spread_worse"]

    def test_not_testable_with_one_geometry(self, temp_dir):
        rows = [("ea3", "a", 0.6, 0.05), ("ea3", "b", 0.8, 0.15)]
        assert not law_geometry(load_pooled(str(_pooled(temp_dir, rows))))["testable"]


class TestImpliedOccupancy:
    def test_p_lands_in_range_and_rises(self, temp_dir):
        rows, occ = implied_occupancy(load_pooled(str(_pooled(temp_dir, REAL))), 0.0045, 0.3705)
        assert occ["valid"] and occ["all_in_range"] and occ["monotone"]
        assert len(rows) == len(REAL)

    def test_rejects_an_inverted_floor_and_ceiling(self, temp_dir):
        _, occ = implied_occupancy(load_pooled(str(_pooled(temp_dir, REAL))), 0.5, 0.1)
        assert not occ["valid"]

    def test_flags_p_outside_range(self, temp_dir):
        """A ceiling below the data puts p above 1, which means the decomposition leaks."""
        _, occ = implied_occupancy(load_pooled(str(_pooled(temp_dir, REAL))), 0.0045, 0.05)
        assert occ["valid"] and not occ["all_in_range"]


class TestMain:
    def test_end_to_end_on_the_measured_ladder(self, temp_dir, capsys):
        rc = main(["--pooled", str(_pooled(temp_dir, REAL)),
                   "--priority", str(_priority(temp_dir, REAL_PRIO)),
                   "--out", str(temp_dir / "o")])
        out = capsys.readouterr().out
        assert rc == 0
        assert "HOLDS" in out and "DOMINATING" in out
        laws = {r["law"]: r["holds"] for r in csv.DictReader(open(temp_dir / "o" / "occupancy_law.csv"))}
        assert laws["L1_floor_is_idle"] == "True" and laws["L2_ceiling_below_one"] == "True"
        occ = list(csv.DictReader(open(temp_dir / "o" / "implied_occupancy.csv")))
        assert len(occ) == len(REAL)

    def test_reports_a_failing_floor_law(self, temp_dir, capsys):
        bad = [("l75", 0.75, 0.13, 0.05, "False"), ("l88", 0.88, 0.30, 0.06, "False")]
        main(["--pooled", str(_pooled(temp_dir, REAL)),
              "--priority", str(_priority(temp_dir, bad)), "--out", str(temp_dir / "o")])
        assert "FAILS" in capsys.readouterr().out

    def test_reports_untestable_laws_without_crashing(self, temp_dir, capsys):
        few = [("ea3", "a", 0.5, 0.006), ("ea3", "b", 0.6, 0.02)]
        main(["--pooled", str(_pooled(temp_dir, few)),
              "--priority", str(_priority(temp_dir, REAL_PRIO)), "--out", str(temp_dir / "o")])
        assert "not testable" in capsys.readouterr().out

    def test_missing_input(self, temp_dir, capsys):
        assert main(["--pooled", str(temp_dir / "no.csv"),
                     "--priority", str(_priority(temp_dir, REAL_PRIO))]) == 1
        assert "missing input" in capsys.readouterr().out

    def test_empty_input(self, temp_dir, capsys):
        p = temp_dir / "empty.csv"
        p.write_text("phase,condition,rho,inversion_rate\n", encoding="utf-8")
        assert main(["--pooled", str(p),
                     "--priority", str(_priority(temp_dir, REAL_PRIO)),
                     "--out", str(temp_dir / "o")]) == 1
        assert "no usable rows" in capsys.readouterr().out
