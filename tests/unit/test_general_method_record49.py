"""Freeze 46 (plan version 49) as registered: DESIGN49.md's fingerprint, the plan that freezes it,
the judge's margins, the block designs the queues are made from, version 47's runs the rounds were
drawn about and the rounds stated, and the freezes' own record. A change to any of them after the
fact fails here, as a freeze is never edited."""
import hashlib
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import general_method as gm  # noqa: E402
import general_method49 as g49  # noqa: E402
import run_queue as rq  # noqa: E402
import under_load_posthoc as ph  # noqa: E402

FOLDER = REPO / "docs" / "results" / "general_method"
#: DESIGN49.md's fingerprint, as registered; DESIGN49.sha256 holds the same.
FINGERPRINT49 = "15e7bd3d96e6c39813018fe7fb22f8672c11fda37531881e91f096626c7264e5"
#: Each block's design, version 47's design its setups come from, and its runs on each pair.
BLOCKS = {"r": ("gv", 12, 0), "j": ("gn", 12, 0), "g": ("gp", 6, 0), "q": ("gk", 12, 0),
          "z": ("ga", 0, 12)}
#: The rounds the rule asks, and the predictions no number of rounds up to twelve brings to the
#: bar under the rule (DESIGN49.md, "The rounds").
ROUNDS, UNREACHABLE = 6, ['R-c', 'J-b', 'G-b']
#: The share of made-up blocks confirming each prediction at six rounds, under the rule and with
#: the runs' own spread, as DESIGN49.md states them.
POWER = {"R-a": 0.994, "R-b": 1.0, "R-c": 0.0655, "R-d": 0.8425, "J-a": 1.0,
         "J-b": 0.002, "G-a": 0.9995, "G-b": 0.0605, "Q-a": 1.0, "Q-b": 1.0,
         "Q-c": 0.977, "Z-a": 1.0, "Z-b": 1.0}
POWER_PILOT = {"R-a": 1.0, "R-b": 1.0, "R-c": 1.0, "R-d": 1.0, "J-a": 1.0,
         "J-b": 1.0, "G-a": 0.9995, "G-b": 0.9995, "Q-a": 1.0, "Q-b": 1.0,
         "Q-c": 0.977, "Z-a": 1.0, "Z-b": 1.0}


def design(name):
    with open(FOLDER / name, encoding="utf-8") as fh:
        return json.load(fh)


def words(path):
    return " ".join(path.read_text(encoding="utf-8").split())


def test_the_design_is_the_one_registered():
    assert hashlib.sha256((FOLDER / "DESIGN49.md").read_bytes()).hexdigest() == FINGERPRINT49
    lines = (FOLDER / "DESIGN49.sha256").read_text(encoding="utf-8").splitlines()
    assert lines[0] == FINGERPRINT49 + " *DESIGN49.md"
    assert lines[2] == FINGERPRINT49 + " *docs/results/general_method/DESIGN49.md"


def test_the_design_checks_out_byte_for_byte():
    rules = (REPO / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "docs/results/general_method/DESIGN49.md -text" in rules


def test_the_judge_judges_by_the_margins_registered():
    assert (g49.GROWTH, g49.HOLDS_STILL, g49.WAITING, g49.CERTIFIED) == (1.5, 1.2, 0.999, 0.999)
    assert (g49.LEFT, g49.LEFT_US, g49.UNWAITED) == (0.1, 50.0, 0.5)
    assert g49.LEFT_US == ph.RESOLUTION_US, "the check's resolution"
    assert g49.BOUND == {"R": "", "J": "", "G": "_50ms"}
    assert g49.BOUND_MS == {"": 10.0, "_50ms": 50.0} and gm.CERTIFY_B_WIDE_MS == 50.0
    assert (gm.ALPHA, gm.BOOTSTRAP, gm.BOOTSTRAP_SEED, gm.INTERVAL) == (0.05, 2000, 20261104,
                                                                        0.95)
    assert (g49.GAP_DEPTH, g49.WAITING_DEPTH, g49.WAITING_PREFETCH) == (1, 256, 1000)
    assert gm.TAIL_PERCENTILE == 99, "the own tails' top 1%"
    assert g49.PREDICTIONS == ("R-a", "R-b", "R-c", "R-d", "J-a", "J-b", "G-a", "G-b", "Q-a",
                               "Q-b", "Q-c", "Z-a", "Z-b")
    assert (g49.BLOCKS, g49.ARM_BLOCK) == (("R", "J", "G", "Q", "Z"), "Z")
    assert g49.AGAINST == {"R-d": "R2000-redis-d1", "Q-b": "Q2000-kafka-rdk",
                           "Z-b": "Z2000-kafka-rdk"}


def test_each_block_runs_version_47s_setups_four_rounds():
    seen = {}
    for block, (source, x86, arm) in BLOCKS.items():
        d = design("g49%s_design.json" % block)
        old = dict((s["id"], s) for s in design("%s_design.json" % source)["setups"])
        assert d["rounds"] == 6 and d["seed"] == 20261104
        assert "RATE=2000 DURATION=70 WARMUP_S=20 PRIME_S=60" in d["about"]
        assert "DESIGN49.md" in d["about"] and "Freeze 46 (plan version 49)" in d["about"]
        assert len(d["setups"]) * 6 == x86 + arm
        for s in d["setups"]:
            assert s["id"].startswith(block.upper() + "2000-") and s["id"] not in seen
            twin = [o for o, n in g49.FROM47.items() if n == s["id"]]
            assert len(twin) == 1, s["id"]
            assert dict(s, id=None) == dict(old[twin[0]], id=None), "version 47's setup as run"
            seen[s["id"]] = s
        if block == "g":
            assert rq.check_design(d) == [
                "with a single setup, consecutive rounds cannot avoid repeating it"]
        else:
            assert rq.check_design(d) == []
    assert sorted(seen) == sorted(g49.FROM47.values())
    reached = set(s for setups in g49.REACHES.values() for s in setups)
    assert reached | set(g49.AGAINST.values()) == set(seen), "every setup run is judged"
    assert sum(b[1] for b in BLOCKS.values()) == 42 and sum(b[2] for b in BLOCKS.values()) == 12


def test_block_gs_queue_is_six_one_round_queues():
    d = design("g49g_design.json")
    rows = []
    for first in range(1, 7):
        rows.extend(rq.make_rows(dict(d, rounds=1, first_round=first)))
    assert [r["key"] for r in rows] == ["r%03d-G2000-rabbitmq-p1000-a1" % i for i in range(1, 7)]
    assert all(json.loads(r["params"])["prefetch"] == 1000 for r in rows)
    assert "first_round 1 to 6" in d["about"]


def test_the_rounds_were_drawn_about_version_47s_runs():
    rows = gm.read_table(str(FOLDER / "g49_from47_runs.csv"))
    runs47 = g49.from47(rows)
    assert sorted(runs47) == sorted(g49.FROM47.values())
    assert all(len(r) == 4 for r in runs47.values()) and len(rows) == 36
    judged = dict((r["run"], r["setup"]) for r in gm.read_table(str(FOLDER / "g_runs.csv")))
    assert all(judged[r["run"]] == r["setup"] for r in rows), "version 47's judged runs"
    assert all(g49.clears(runs47).values()), "every prediction holds on them (D49-9)"
    found = json.loads((FOLDER / "g49_power.json").read_text(encoding="utf-8"))
    assert (found["rounds"], found["spread"], found["blocks"], found["seed"]) == (
        ROUNDS, "rule", 2000, 20261104)
    assert [p for p in g49.PREDICTIONS if p in found["unreachable"]] == UNREACHABLE
    assert found["power"] == POWER
    pilot = json.loads((FOLDER / "g49_power_pilot_spread.json").read_text(encoding="utf-8"))
    assert (pilot["rounds"], pilot["spread"]) == (ROUNDS, "pilot")
    assert pilot["power"] == POWER_PILOT
    text = words(FOLDER / "DESIGN49.md")
    for name, table in (("The rule", POWER), ("The runs' own spread", POWER_PILOT)):
        row = "| %s | %s |" % (name, " | ".join("%.3f" % table[p] for p in g49.PREDICTIONS))
        assert row in text, name


def test_the_plan_is_fingerprinted_and_listed():
    folder = REPO / "freezes" / "46-experiment-plan"
    names = []
    for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split()
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name
        names.append(name)
    assert sorted(names) == ["experiment_plan.pdf", "experiment_plan.tex"]
    record = (REPO / "freezes" / "README.md").read_text(encoding="utf-8")
    assert "[`46-experiment-plan/`](46-experiment-plan/) | 25 October 2026 |" in record


def test_the_plan_says_what_the_design_says():
    plan = words(REPO / "freezes" / "46-experiment-plan" / "experiment_plan.tex")
    assert "Version 49, frozen on 25 October 2026" in plan
    for tag in range(1, 10):
        assert "D49-%d &" % tag in plan and "\\chg{D49-%d}" % tag in plan, tag
    assert "\\chg{D48-" not in plan and "\\chgold{D48-1}" in plan
    for phrase in ("$W$'s tail on/off ratio at least 1.5", "at $B = 50$~ms",
                   "at most a tenth of its rise at depth 1 in size",
                   "the client's part's own tail on/off ratio at least 1.5",
                   "and at most 50~$\\mu$s, the check's resolution",
                   "at least half of the messages found no fetch waiting in both load states",
                   "Q-c is described there, not judged", "asks six",
                   "42 runs on the x86 pair and 12 on the Arm pair",
                   "a run whose instrument does not check out",
                   "the largest values of 1\\% of the state's messages, at least one"):
        assert phrase in plan, phrase
    text = words(FOLDER / "DESIGN49.md")
    for phrase in ("`W`'s tail on/off ratio is at least 1.5", "with `B` = 50 ms",
                   "at most a tenth of its rise at depth 1, in size",
                   "the client's part's own tail on/off ratio is at least 1.5",
                   "and at most 50 µs, the check's resolution",
                   "at least half of the messages found no fetch waiting",
                   "Q-c is described there, not judged", "It asks for six rounds",
                   "That makes 42 runs on the x86 pair and 12 on the Arm pair",
                   "A run whose own instrument does not check out is left out",
                   "the largest values of 1% of the state's messages, by count, at least one"):
        assert phrase in text, phrase


def same(a, b, path="verdicts"):
    """Whether two judged outputs agree: their numbers to nine significant digits, everything else
    exactly. On 25 October 2026 the equivalence test's p, from scipy's t distribution, differed in
    its seventeenth digit between the library versions CI installs."""
    if isinstance(a, dict) and isinstance(b, dict):
        assert sorted(a) == sorted(b), path
        return all(same(a[k], b[k], "%s.%s" % (path, k)) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), path
        return all(same(x, y, "%s[%d]" % (path, i)) for i, (x, y) in enumerate(zip(a, b)))
    if isinstance(a, float) and isinstance(b, float):
        assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12), (path, a, b)
        return True
    assert a == b and type(a) is type(b), (path, a, b)
    return True


def test_the_comparison_still_tells_a_changed_verdict():
    assert same({"p": 0.00014186209660488227, "v": "confirmed", "n": [1, None]},
                {"p": 0.00014186209660488244, "v": "confirmed", "n": [1, None]})
    for changed in ({"p": 0.000141862, "v": "confirmed", "n": [1, None]},
                    {"p": 0.00014186209660488227, "v": "not confirmed", "n": [1, None]},
                    {"p": 0.00014186209660488227, "v": "confirmed", "n": [1, 0]},
                    {"p": 0.00014186209660488227, "v": "confirmed"}):
        try:
            same({"p": 0.00014186209660488227, "v": "confirmed", "n": [1, None]}, changed)
        except AssertionError:
            continue
        raise AssertionError("not told apart: %r" % changed)


def test_the_verdicts_are_the_judges_on_the_runs():
    """The verdicts recorded on 25 October 2026 are what the registered judge gives on the run
    tables read on the drivers: every prediction confirmed, on six runs of every setup, none left
    out."""
    rows = g49.read_tables([str(FOLDER / "g49_runs_x86.csv"), str(FOLDER / "g49_runs_arm.csv")])
    assert len(rows) == 54 and all(r["verdict"] == "count" for r in rows)
    out = json.loads(json.dumps(g49.judge(rows), sort_keys=True))
    recorded = json.loads((FOLDER / "g49_verdicts.json").read_text(encoding="utf-8"))
    assert same(out, recorded)
    assert [recorded[p]["verdict"] for p in g49.PREDICTIONS] == ["confirmed"] * 13
    assert recorded["described"]["left_out"] == []
    assert sorted(set((c["setup"], c["runs"]) for c in recorded["described"]["setups"])) == sorted(
        (s, 6) for s in g49.FROM47.values())


def test_every_judged_run_is_fingerprinted():
    """The drivers' fingerprint lists name every file of every run of this version, the judged
    runs among them."""
    for pair in ("x86", "arm"):
        listed = set()
        for line in (FOLDER / ("g49_SHA256SUMS_%s.txt" % pair)).read_text(
                encoding="utf-8").splitlines():
            digest, name = line.split(None, 1)
            assert len(digest) == 64
            listed.add(name.lstrip("*").split("/")[0])
        judged = set(r["run"] for r in gm.read_table(str(FOLDER / ("g49_runs_%s.csv" % pair))))
        assert judged <= listed and all(name.startswith("law_g49") for name in listed)
