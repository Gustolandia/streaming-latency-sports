"""Freeze 42's record, docs/results/under_load, against the designs it was fixed by: version 45's
(DESIGN.md) and version 46's amendment before any judged run (DESIGN46.md).

Each design was fingerprinted before the runs it governs: version 45's before any pilot or judged
run of block U, version 46's before its pilot's round d and any judged run (22 Oct 2026). The
fingerprints are checked here, so an edit made after the runs began fails the suite instead of
passing unseen, and every design file the pair runs from must be one a design's table counts.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
HERE = REPO / "docs" / "results" / "under_load"
sys.path.insert(0, str(REPO / "scripts"))

import under_load as ul  # noqa: E402

#: The first characters of the fingerprints written into DESIGN.sha256 before freeze 42's pilot
#: and into DESIGN46.sha256 before version 46's.
FINGERPRINT = "b92ef54c"
FINGERPRINT46 = "76c4553e"


def design(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def table_of(text):
    """{rate: runs} from a design's table of the block."""
    table = {}
    for line in text.splitlines():
        m = re.match(r"^\| ([\d,]+) msg/s, 70 s \(20 s warm-up\) \| .* \| (\d+) \|$", line)
        if m:
            table[int(m.group(1).replace(",", ""))] = int(m.group(2))
    return table


# --- version 45 ----------------------------------------------------------------------------------

def test_the_design_is_the_one_fingerprinted_before_the_runs():
    for doc, sums, prefix in (("DESIGN.md", "DESIGN.sha256", FINGERPRINT),
                              ("DESIGN46.md", "DESIGN46.sha256", FINGERPRINT46)):
        recorded = (HERE / sums).read_text(encoding="utf-8").split()[0]
        assert hashlib.sha256((HERE / doc).read_bytes()).hexdigest() == recorded, doc
        assert recorded.startswith(prefix), doc


def test_the_designs_check_out_byte_for_byte():
    """A Windows checkout converts line endings unless git is told not to, and a converted copy
    would no longer match its fingerprint."""
    rules = (REPO / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "docs/results/under_load/DESIGN.md -text" in rules
    assert "docs/results/under_load/DESIGN46.md -text" in rules


PILOTS = {2000: "up2000_design.json", 500: "up500_design.json", 50: "up50_design.json"}
#: The pilot's second round (22 Oct 2026): its first round held an 80% load at 69.1-76.3% at 2,000
#: messages a second, so the loaded setups at both upper rates ran again at 70% (D45-7).
SECOND = {2000: "up2000b_design.json", 500: "up500b_design.json"}
#: Its third round: the second held 70% at 63.3-64.5% at real-time priority at 2,000 messages a
#: second with the machine 78-86% busy, so the same setups ran again with the duty corrected a
#: second time once the clients run (load_recorrect).
THIRD = {2000: "up2000c_design.json", 500: "up500c_design.json"}


def test_freeze_42s_pilot_rounds_are_as_they_ran():
    assert table_of((HERE / "DESIGN.md").read_text(encoding="utf-8")) == {2000: 24, 500: 24,
                                                                           50: 16}
    for rate, name in PILOTS.items():
        pilot = design(name)
        assert pilot["rounds"] == 1 and len(pilot["setups"]) == (6 if rate in ul.UPPER_RATES
                                                                 else 4)
        assert all(ul.PILOT_ID.match(s["id"]) and not ul.SETUP_ID.match(s["id"])
                   for s in pilot["setups"])
    for rate, name in SECOND.items():
        second = design(name)
        first = [s for s in design(PILOTS[rate])["setups"] if s["load_pct"]]
        assert second["rounds"] == 1 and len(second["setups"]) == 4
        assert [s["id"] for s in second["setups"]] == [s["id"].replace("-l80", "-l70")
                                                       for s in first]
        assert all(dict(s, load_pct=80, id=f["id"]) == f
                   for s, f in zip(second["setups"], first))
        assert "RATE=%d DURATION=70 WARMUP_S=20" % rate in second["about"]
    for rate, name in THIRD.items():
        third, second = design(name), design(SECOND[rate])
        assert third["rounds"] == 1
        assert third["setups"] == [dict(s, load_recorrect=True) for s in second["setups"]]
        assert "RATE=%d DURATION=70 WARMUP_S=20" % rate in third["about"]


# --- version 46 ----------------------------------------------------------------------------------

JUDGED = {2000: "u2000_design.json", 500: "u500_design.json", 50: "u50_design.json"}
#: Version 46's pilot, round d, and its two runs with the collector left on.
FOURTH = {2000: "up2000d_design.json", 500: "up500d_design.json", 50: "up50d_design.json"}
COLLECTOR = "ug2000_design.json"

#: The loaded setups' level at 500 and 2,000 messages a second, as D45-7 set it, and the 50 a
#: second blocks' load and duty: 88% asked at a duty of 88 held 88.1% in freeze 42's pilot.
LOADED = 70
BLOCKS = {"load_pct": 88, "load_blocks_s": 5, "duty_pct": 88}

INSTRUMENTS = {"so_timestamps": "sched", "so_journal": True, "recv_capture": True,
               "send_capture": True, "send_capture_both": True, "hw_capture": True,
               "broker_capture": True, "slice_ns": 3000000, "delay_ms": 0}
#: Version 46's additions, in every run: the producer at real-time priority, the collector off,
#: the consumer thread's own counters, the run's facts and the lateness rule.
V46 = {"producer_priority": True, "gc_off": True, "schedstat": True, "run_facts": True,
       "lateness_p99_ms": 10}


def test_the_block_runs_what_version_46s_table_counts():
    """A block one campaign short of its design went unnoticed for four days once (A4), so the
    files the pair runs from are counted against the table the predictions were fixed with."""
    table = table_of((HERE / "DESIGN46.md").read_text(encoding="utf-8"))
    assert table == {2000: 24, 500: 24, 50: 16}
    for rate, name in JUDGED.items():
        d = design(name)
        assert d["rounds"] == 4 and len(d["setups"]) * d["rounds"] == table[rate], name
        assert "RATE=%d DURATION=70 WARMUP_S=20 PRIME_S=60" % rate in d["about"], name
    assert sorted(p.name for p in HERE.glob("*_design.json")) == sorted(
        list(JUDGED.values()) + list(PILOTS.values()) + list(SECOND.values())
        + list(THIRD.values()) + list(FOURTH.values()) + [COLLECTOR])


def test_every_run_takes_every_instrument_and_the_setups_the_table_names():
    for rate, name in JUDGED.items():
        setups = design(name)["setups"]
        ids = [s["id"] for s in setups]
        assert len(set(ids)) == len(ids), name
        assert all(ul.SETUP_ID.match(i) and ul.setup_parts(i)[0] == rate for i in ids), name
        for s in setups:
            assert all(s.get(k) == v for k, v in dict(INSTRUMENTS, **V46).items()), s["id"]
            assert bool(s.get("priority")) == s["id"].endswith("-rt"), s["id"]
            assert not s.get("load_recorrect") and not s.get("gc_log"), s["id"]
        for backend in ("kafka", "redis"):
            mine = [s for s in setups if s["backend"] == backend]
            if rate in ul.UPPER_RATES:
                assert {(s["load_pct"], bool(s.get("priority"))) for s in mine} == {
                    (0, False), (LOADED, False), (LOADED, True)}, (name, backend)
                # Each loaded setup's duty is frozen from pilot round d before any judged run.
                assert all("duty_pct" not in s and "load_blocks_s" not in s for s in mine)
            else:
                assert [s["id"] for s in mine] == ["U50-%s-l0" % backend,
                                                   "U50-%s-l88-blocks" % backend]
                assert all(s[k] == v for k, v in BLOCKS.items()) and ul.in_blocks(mine[1]["id"])
                assert "duty_pct" not in mine[0] and mine[0]["load_pct"] == 0


def as_judged(pilot_setup):
    """A round-d pilot setup as the judged block runs it: its id judged, and without the second
    correction the pilot uses to find each loaded setup's duty."""
    s = dict(pilot_setup, id="U" + pilot_setup["id"][2:])
    s.pop("load_recorrect", None)
    return s


def test_round_d_is_the_judged_block_once_with_the_duty_found_in_the_run():
    for rate, name in FOURTH.items():
        pilot = design(name)
        assert pilot["rounds"] == 1
        assert all(ul.PILOT_ID.match(s["id"]) and not ul.SETUP_ID.match(s["id"])
                   for s in pilot["setups"])
        assert [as_judged(s) for s in pilot["setups"]] == design(JUDGED[rate])["setups"], name
        for s in pilot["setups"]:
            assert bool(s.get("load_recorrect")) == (rate in ul.UPPER_RATES
                                                     and bool(s["load_pct"])), s["id"]
        assert "RATE=%d DURATION=70 WARMUP_S=20 PRIME_S=60" % rate in pilot["about"]


def test_the_collectors_runs_keep_it_on_and_are_never_read_by_the_blocks_reader():
    runs = design(COLLECTOR)
    idle = {s["backend"]: s for s in design(FOURTH[2000])["setups"] if not s["load_pct"]}
    assert runs["rounds"] == 1 and len(runs["setups"]) == 2
    for s in runs["setups"]:
        assert not ul.SETUP_ID.match(s["id"]) and not ul.PILOT_ID.match(s["id"])
        assert s == dict(idle[s["backend"]], id=s["id"], gc_off=False, gc_log=True)
    assert "RATE=2000 DURATION=70 WARMUP_S=20 PRIME_S=60" in runs["about"]


def test_the_freezes_are_fingerprinted_and_listed():
    """Each plan is checked against the fingerprints in its folder, as every freeze is, and the
    freezes' own record lists it."""
    record = (REPO / "freezes" / "README.md").read_text(encoding="utf-8")
    for number in (42, 43):
        folder = REPO / "freezes" / ("%d-experiment-plan" % number)
        names = []
        for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            digest, name = line.split()
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name
            names.append(name)
        assert sorted(names) == ["experiment_plan.pdf", "experiment_plan.tex"]
        assert "[`%d-experiment-plan/`](%d-experiment-plan/) | 22 October 2026 |" % (
            number, number) in record


def plan_text(number):
    return " ".join((REPO / "freezes" / ("%d-experiment-plan" % number) / "experiment_plan.tex")
                    .read_text(encoding="utf-8").split())


def test_version_45s_plan_says_what_its_design_says():
    plan = plan_text(42)
    assert "Version 45, frozen on 22 October 2026" in plan
    assert "Sixteen setups, four rounds, 64 runs" in plan
    assert "at least 1.5 times its value idle" in plan and ul.GROWTH == 1.5
    assert "at most half its value at normal priority" in plan and ul.HALF == 0.5
    assert "where it is at least 0.9" in plan and ul.ONLY_PATH == 0.9
    assert "holds at least half of it" in plan and ul.NAMES_A_TERM == 0.5
    for tag in range(1, 10):
        assert "D45-%d &" % tag in plan and "\\chg{D45-%d}" % tag in plan, tag
    assert "\\chg{D44-" not in plan, "version 44's tags are grey once version 45 is frozen"


def test_version_46s_plan_says_what_its_design_says():
    """The plan's rows for the amendment carry the design's numbers, read against the files the
    pair runs from and the judge's own constants."""
    plan = plan_text(43)
    assert "Version 46, frozen on 22 October 2026" in plan
    assert "Sixteen setups, four rounds, 64 runs" in plan
    assert sum(len(design(f)["setups"]) * design(f)["rounds"] for f in JUDGED.values()) == 64
    assert "the lower end of its 95\\% interval is at least 0.9" in plan
    assert ul.ONLY_PATH == 0.9 and ul.INTERVAL == 0.95 and ul.BOOTSTRAP == 2000
    assert "seed 20261022" in plan and ul.BOOTSTRAP_SEED == 20261022
    assert "its spread between its 1st and 99th percentiles at most 10~ms" in plan
    assert "the 1st percentile of" in plan and ul.FLOOR_PERCENTILE == 1
    assert "fewer than 100" in plan and ul.FLOOR_MIN == 100
    assert "within 1~s after a switch" in plan and ul.BLOCK_GUARD_S == 1.0
    assert "5-s blocks" in plan and BLOCKS["load_blocks_s"] == 5
    for tag in range(1, 13):
        assert "D46-%d &" % tag in plan and "\\chg{D46-%d}" % tag in plan, tag
    assert "\\chg{D45-" not in plan, "version 45's tags are grey once version 46 is frozen"
