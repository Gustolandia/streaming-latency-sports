"""Freeze 45 (plan version 48) as registered: DESIGN48.md's fingerprint, the plan that freezes it,
block C's amended design and its own pilot, and the freezes' own record. A change to any of them
after the fact fails here, as a freeze is never edited."""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import run_queue as rq  # noqa: E402

FOLDER = REPO / "docs" / "results" / "general_method"
#: DESIGN48.md's fingerprint, as registered; DESIGN48.sha256 holds the same.
FINGERPRINT48 = "215ecb3d629c151613d44447de4e6ad8b00f8ac0736964e988e33bd7d9b44a7e"
#: Block C's arms and their loads, which version 48 does not change.
ARMS = {"C2000-kafka-base": 70, "C2000-kafka-core": 53, "C2000-kafka-core-sib": 61}


def design(name):
    with open(FOLDER / name, encoding="utf-8") as fh:
        return json.load(fh)


def words(path):
    return " ".join(path.read_text(encoding="utf-8").split())


def test_the_design_is_the_one_registered():
    assert hashlib.sha256((FOLDER / "DESIGN48.md").read_bytes()).hexdigest() == FINGERPRINT48
    lines = (FOLDER / "DESIGN48.sha256").read_text(encoding="utf-8").splitlines()
    assert lines[0] == FINGERPRINT48 + " *DESIGN48.md"
    assert lines[2] == FINGERPRINT48 + " *docs/results/general_method/DESIGN48.md"


def test_block_c_is_placed_as_version_48_says():
    d = design("gc_design.json")
    rq.check_design(d)
    assert d["rounds"] == 4 and d["seed"] == 20261104 and "DESIGN48.md" in d["about"]
    arms = {s["id"]: s for s in d["setups"]}
    assert {i: s["load_pct"] for i, s in arms.items()} == ARMS
    for s in arms.values():
        assert s["irq_cpus"] == "sibling" and s["irqbalance_off"] and s["rps_off"]
        assert s["priority"] and s["consumer"] == "kafka-python"
        assert s.get("threads_apart") is s.get("whole_core"), "apart only where the core is kept"
        assert s["duty_pct"] == 75, "the duty block C's own pilot froze"
    assert arms["C2000-kafka-core-sib"]["sibling_load"]
    assert not arms["C2000-kafka-base"].get("whole_core")


def test_block_cs_own_pilot_runs_each_arm_once_at_the_starting_duty():
    pilot = design("gpilot_c48_design.json")
    rq.check_design(pilot)
    judged = {s["id"]: s for s in design("gc_design.json")["setups"]}
    assert pilot["rounds"] == 1 and len(pilot["setups"]) == len(ARMS)
    for s in pilot["setups"]:
        assert s["id"].endswith("-pilot") and s["duty_pct"] == 75
        twin = judged[s["id"][:-len("-pilot")]]
        assert dict(s, id=twin["id"], duty_pct=None) == dict(twin, duty_pct=None)


def test_the_plan_is_fingerprinted_and_listed():
    folder = REPO / "freezes" / "45-experiment-plan"
    names = []
    for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split()
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name
        names.append(name)
    assert sorted(names) == ["experiment_plan.pdf", "experiment_plan.tex"]
    record = (REPO / "freezes" / "README.md").read_text(encoding="utf-8")
    assert "[`45-experiment-plan/`](45-experiment-plan/) | 23 October 2026 |" in record


def test_the_plan_says_what_the_design_says():
    plan = words(REPO / "freezes" / "45-experiment-plan" / "experiment_plan.tex")
    assert "Version 48, frozen on 23 October 2026" in plan
    for tag in range(1, 5):
        assert "D48-%d &" % tag in plan and "\\chg{D48-%d}" % tag in plan, tag
    assert "\\chg{D47-" not in plan and "\\chgold{D47-1}" in plan
    for phrase in ("(\\texttt{irq\\_cpus: sibling})", "(\\texttt{threads\\_apart},",
                   "at most 0.70 of its vCPU", "at least 99.9\\% of each card interrupt's count",
                   "after blocks V, N, P, K and S", "C-a, its margin and the arms' loads"):
        assert phrase in plan, phrase
    design_text = words(FOLDER / "DESIGN48.md")
    for phrase in ("(`irq_cpus: sibling`)", "(`threads_apart`,", "at most 0.70 of its vCPU",
                   "At least 99.9% of each card interrupt's count",
                   "after blocks V, N, P, K and S", "Unchanged: C-a, its margin"):
        assert phrase in design_text, phrase
