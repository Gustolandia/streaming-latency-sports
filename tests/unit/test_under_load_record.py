"""Freeze 42's record, docs/results/under_load, against the design it was fixed by.

The design was fingerprinted before any pilot or judged run of block U (22 Oct 2026). Its
fingerprint is checked here, so an edit made after the runs began fails the suite instead of
passing unseen, and every design file the pair runs from must be one the design's table counts.
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

#: The first characters of the fingerprint written into DESIGN.sha256 before the pilot.
FINGERPRINT = "b92ef54c"


def test_the_design_is_the_one_fingerprinted_before_the_runs():
    recorded = (HERE / "DESIGN.sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256((HERE / "DESIGN.md").read_bytes()).hexdigest() == recorded
    assert recorded.startswith(FINGERPRINT)


def test_the_design_checks_out_byte_for_byte():
    """A Windows checkout converts line endings unless git is told not to, and a converted copy
    would no longer match its fingerprint."""
    rules = (REPO / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "docs/results/under_load/DESIGN.md -text" in rules


def design(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


JUDGED = {2000: "u2000_design.json", 500: "u500_design.json", 50: "u50_design.json"}
PILOTS = {2000: "up2000_design.json", 500: "up500_design.json", 50: "up50_design.json"}
#: The pilot's second round (22 Oct 2026): its first round held an 80% load at 69.1-76.3% at 2,000
#: messages a second, so the loaded setups at both upper rates run again at 70% (D45-7).
SECOND = {2000: "up2000b_design.json", 500: "up500b_design.json"}
#: Its third round: the second held 70% at 63.3-64.5% at real-time priority at 2,000 messages a
#: second with the machine 78-86% busy, so the same setups run again with the duty corrected a
#: second time once the clients run (load_recorrect).
THIRD = {2000: "up2000c_design.json", 500: "up500c_design.json"}


def test_the_block_runs_what_the_design_table_counts():
    """A block one campaign short of its design went unnoticed for four days once (A4), so the
    files the pair runs from are counted against the table the predictions were fixed with."""
    table = {}
    for line in (HERE / "DESIGN.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| ([\d,]+) msg/s, 70 s \(20 s warm-up\) \| .* \| (\d+) \|$", line)
        if m:
            table[int(m.group(1).replace(",", ""))] = int(m.group(2))
    assert table == {2000: 24, 500: 24, 50: 16}
    for rate, name in JUDGED.items():
        d = design(name)
        assert d["rounds"] == 4 and len(d["setups"]) * d["rounds"] == table[rate], name
        assert "RATE=%d DURATION=70 WARMUP_S=20" % rate in d["about"], name
    assert sorted(p.name for p in HERE.glob("*_design.json")) == sorted(
        list(JUDGED.values()) + list(PILOTS.values()) + list(SECOND.values())
        + list(THIRD.values()))


def as_decided(pilot_setup):
    """A first-round pilot setup, run as the design was frozen, as the judged block runs it once
    D45-7 has set the load: its id judged, and a loaded setup at an upper rate at LOADED with the
    duty corrected a second time."""
    s = dict(pilot_setup, id="U" + pilot_setup["id"][2:])
    if s["load_pct"] and ul.setup_parts(s["id"])[0] in ul.UPPER_RATES:
        s.update(id=s["id"].replace("-l80", "-l%d" % LOADED), load_pct=LOADED,
                 load_recorrect=True)
    return s


def test_the_judge_reads_every_judged_setup_and_no_pilot():
    for rate, name in JUDGED.items():
        ids = [s["id"] for s in design(name)["setups"]]
        assert len(set(ids)) == len(ids), name
        assert all(ul.SETUP_ID.match(i) and ul.setup_parts(i)[0] == rate for i in ids), name
        pilot = design(PILOTS[rate])
        assert pilot["rounds"] == 1
        assert all(ul.PILOT_ID.match(s["id"]) and not ul.SETUP_ID.match(s["id"])
                   for s in pilot["setups"])
        assert [as_decided(s) for s in pilot["setups"]] == design(name)["setups"], name


def test_the_pilots_second_round_is_the_first_rounds_loaded_setups_at_70():
    for rate, name in SECOND.items():
        second = design(name)
        first = [s for s in design(PILOTS[rate])["setups"] if s["load_pct"]]
        assert second["rounds"] == 1 and len(second["setups"]) == 4
        assert [s["id"] for s in second["setups"]] == [s["id"].replace("-l80", "-l70")
                                                       for s in first]
        assert all(dict(s, load_pct=80, id=f["id"]) == f
                   for s, f in zip(second["setups"], first))
        assert {s["load_pct"] for s in second["setups"]} == {70}
        assert all(ul.PILOT_ID.match(s["id"]) and not ul.SETUP_ID.match(s["id"])
                   for s in second["setups"])
        assert "RATE=%d DURATION=70 WARMUP_S=20" % rate in second["about"]


def test_the_pilots_third_round_is_the_second_with_the_running_correction():
    for rate, name in THIRD.items():
        third, second = design(name), design(SECOND[rate])
        assert third["rounds"] == 1
        assert third["setups"] == [dict(s, load_recorrect=True) for s in second["setups"]]
        assert "RATE=%d DURATION=70 WARMUP_S=20" % rate in third["about"]


#: The loaded setups' level at 500 and 2,000 messages a second. The design's table says 80%; the
#: pilot held it at 69.1-76.3% at 2,000 a second, and D45-7 then gives every load setup at both
#: upper rates the highest load the pilot held within the rule's 3 points at both rates: 70%, with
#: the duty corrected a second time once the clients run (load_recorrect), held at 67.5-70.4% in
#: all eight. Recorded in README.md before any judged run.
LOADED = 70


def test_every_run_takes_every_instrument_and_the_setups_the_table_names():
    instruments = {"so_timestamps": "sched", "so_journal": True, "recv_capture": True,
                   "send_capture": True, "send_capture_both": True, "hw_capture": True,
                   "broker_capture": True, "slice_ns": 3000000, "delay_ms": 0}
    for rate, name in JUDGED.items():
        setups = design(name)["setups"]
        for s in setups:
            assert all(s.get(k) == v for k, v in instruments.items()), s["id"]
            assert bool(s.get("priority")) == s["id"].endswith("-rt"), s["id"]
        wanted = ({(0, False), (LOADED, False), (LOADED, True)} if rate in ul.UPPER_RATES
                  else {(0, False), (88, False)})
        for s in setups:
            assert bool(s.get("load_recorrect")) == (rate in ul.UPPER_RATES
                                                     and bool(s["load_pct"])), s["id"]
        for backend in ("kafka", "redis"):
            assert {(s["load_pct"], bool(s.get("priority"))) for s in setups
                    if s["backend"] == backend} == wanted, (name, backend)


def test_the_freeze_is_fingerprinted_and_listed():
    """The plan is checked against the fingerprints in its folder, as every freeze is, and the
    freezes' own record lists it."""
    folder = REPO / "freezes" / "42-experiment-plan"
    names = []
    for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split()
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name
        names.append(name)
    assert sorted(names) == ["experiment_plan.pdf", "experiment_plan.tex"]
    record = (REPO / "freezes" / "README.md").read_text(encoding="utf-8")
    assert "[`42-experiment-plan/`](42-experiment-plan/) | 22 October 2026 |" in record


def test_the_plan_says_what_the_design_says():
    """The plan's rows for block U carry the design's numbers, read against the files the pair
    runs from and the judge's own margins."""
    plan = " ".join((REPO / "freezes" / "42-experiment-plan" / "experiment_plan.tex")
                    .read_text(encoding="utf-8").split())
    assert "Version 45, frozen on 22 October 2026" in plan
    assert "Sixteen setups, four rounds, 64 runs" in plan
    assert sum(len(design(f)["setups"]) * design(f)["rounds"] for f in JUDGED.values()) == 64
    assert "at least 1.5 times its value idle" in plan and ul.GROWTH == 1.5
    assert "at most half its value at normal priority" in plan and ul.HALF == 0.5
    assert "where it is at least 0.9" in plan and ul.ONLY_PATH == 0.9
    assert "holds at least half of it" in plan and ul.NAMES_A_TERM == 0.5
    assert "pooled 99th percentile of $F$" in plan and ul.TAIL_PERCENTILE == 99
    for tag in range(1, 10):
        assert "D45-%d &" % tag in plan and "\\chg{D45-%d}" % tag in plan, tag
    assert "\\chg{D44-" not in plan, "version 44's tags are grey once version 45 is frozen"
