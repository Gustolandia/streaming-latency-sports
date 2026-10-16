"""Freeze 41's record, docs/results/order_scope, against the design it was fixed by.

The design was fingerprinted before any pilot or judged run of its blocks (15 Oct 2026). Its
fingerprint is checked here, so an edit made after the runs began fails the suite instead of
passing unseen, and every design file the pair ran from must name a block the design defines.
"""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
HERE = REPO / "docs" / "results" / "order_scope"
sys.path.insert(0, str(REPO / "scripts"))


def test_the_design_is_the_one_fingerprinted_before_the_runs():
    recorded = (HERE / "DESIGN.sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256((HERE / "DESIGN.md").read_bytes()).hexdigest() == recorded
    assert recorded.startswith("a81b3446")


def test_the_design_checks_out_byte_for_byte():
    """A Windows checkout converts line endings unless git is told not to, and a converted copy
    would no longer match its fingerprint."""
    rules = (REPO / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "docs/results/order_scope/DESIGN.md -text" in rules


def design(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def test_every_design_file_names_a_block_of_the_design():
    text = (HERE / "DESIGN.md").read_text(encoding="utf-8")
    for path in sorted(HERE.glob("*_design.json")):
        setups = design(path.name)["setups"]
        assert setups, path.name
        block = path.name.split("_")[0][0].upper()
        assert "| %s, " % block in text, (path.name, block)


#: Each judged block's files, as the design's table counts its runs. Block L's top rung is 2,000
#: messages a second: the pilot found the clients could not hold 5,000, and DESIGN.md names 2,000
#: as the rung that then replaces it.
JUDGED = {"K": ["k_design.json"], "R": ["r_design.json"], "P": ["p_design.json"],
          "L": ["l50_design.json", "l500_design.json", "l2000_design.json"],
          "I": ["i_default_design.json", "i_poll_design.json"]}
#: Runs the plan's pilot row (D44-10) took out of a block the design's table counts, and why. The
#: table is fingerprinted and cannot change, so the difference is recorded here, beside its reason.
PLAN_CHANGES = {"L": (-16, "the pilot held only 83.5-85.7% of an 88% load at 500 messages a "
                           "second and 80.0-81.9% at 2,000, so those rungs run their idle setups "
                           "only, and L-b is judged at 50")}


def test_each_block_runs_what_the_design_table_counts():
    """A block one campaign short of its design went unnoticed for four days once (A4), so the
    files the pairs run from are counted against the table the predictions were fixed with."""
    table = {}
    for line in (HERE / "DESIGN.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[4].isdigit():
            table[cells[0][0]] = (cells[1], int(cells[3]), int(cells[4]))
    assert sorted(table) == sorted(JUDGED)
    for block, files in JUDGED.items():
        pair, rounds, runs = table[block]
        counted = sum(len(design(f)["setups"]) * design(f)["rounds"] for f in files)
        assert counted == runs + PLAN_CHANGES.get(block, (0, ""))[0], (block, counted, runs)
        assert {design(f)["rounds"] for f in files} == {rounds}, block
        ids = [s["id"] for f in files for s in design(f)["setups"]]
        assert len(set(ids)) == len(ids) and all(i.startswith(block) for i in ids), block


#: The pilot's files: K and R in one queue, L one per rung (and the fallback rung, at both loads),
#: I one run on the idle=poll boot.
PILOTS = ["k_pilot_design.json", "lp50_design.json", "lp500_design.json", "lp5000_design.json",
          "ip_design.json", "lp2000_design.json", "lp500l88_design.json"]


def test_the_pilots_cannot_be_judged():
    """The judge reads a block's runs by their setup's prefix; the pilot's prefixes differ, and
    every design file in the folder is either a judged block's or the pilot's."""
    import order_scope as osc
    for name in PILOTS:
        for s in design(name)["setups"]:
            assert s["id"][:2] in ("KP", "RP", "LP", "IP"), s["id"]
            assert not any(osc.in_block(s["id"], b) for b in osc.PREFIX), s["id"]
            assert design(name)["rounds"] == 1, name
    for name in sum(JUDGED.values(), []):
        assert all(any(osc.in_block(s["id"], b) for b in osc.PREFIX)
                   for s in design(name)["setups"]), name
    listed = sorted(sum(JUDGED.values(), []) + PILOTS)
    assert sorted(p.name for p in HERE.glob("*_design.json")) == listed
    assert [osc.rate_of(s["id"]) for f in PILOTS[1:4] for s in design(f)["setups"]] == [
        50, 50, 500, 500, 5000, 5000]
    assert {osc.rate_of(s["id"]) for s in design("lp2000_design.json")["setups"]} == {2000}
    assert {s["load_pct"] for s in design("lp2000_design.json")["setups"]} == {0, 88}


def test_every_setup_records_what_its_predictions_read():
    """K's checks need the journal on both clients and both directions of the producer's
    connection captured; R and I need both journals; L, as the design says, the consumer's
    journal alone; P and L need both captures."""
    for f in JUDGED["K"] + JUDGED["R"] + JUDGED["I"]:
        assert all(s.get("so_journal") is True and s.get("so_timestamps") == "sched"
                   for s in design(f)["setups"]), f
    for f in JUDGED["L"] + PILOTS[1:4] + PILOTS[5:]:
        assert all(s.get("so_journal") == "consumer" and s.get("so_timestamps") == "sched"
                   for s in design(f)["setups"]), f
    for f in JUDGED["K"] + JUDGED["L"]:
        assert all(s.get("send_capture_both") for s in design(f)["setups"]), f
    for f in JUDGED["K"] + JUDGED["P"] + JUDGED["L"]:
        assert all(s.get("recv_capture") and s.get("send_capture")
                   for s in design(f)["setups"]), f
    assert [s["load_pct"] for s in design("r_design.json")["setups"]] == [88] * 4
    assert {s["delay_ms"] for s in design("p_design.json")["setups"]} == {0, 1, 2}


def test_the_freeze_is_fingerprinted_and_listed():
    """The plan is checked against the fingerprints in its folder, as every freeze is, and the
    freezes' own record lists it."""
    folder = REPO / "freezes" / "41-experiment-plan"
    names = []
    for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split()
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name
        names.append(name)
    assert sorted(names) == ["experiment_plan.pdf", "experiment_plan.tex"]
    record = (REPO / "freezes" / "README.md").read_text(encoding="utf-8")
    assert "[`41-experiment-plan/`](41-experiment-plan/) | 15 October 2026 |" in record


def test_the_plans_pilot_row_says_what_the_design_files_run():
    """D44-10's changes, read against the files the pairs run from."""
    plan = " ".join((REPO / "freezes" / "41-experiment-plan" / "experiment_plan.tex")
                    .read_text(encoding="utf-8").split())
    assert "the top rung is 2,000" in plan and "block L has 32 runs" in plan
    assert "L-b is judged at 50 messages a second alone" in plan
    assert sum(len(design(f)["setups"]) * design(f)["rounds"] for f in JUDGED["L"]) == 32
    for name in ("l500_design.json", "l2000_design.json"):
        assert {s["load_pct"] for s in design(name)["setups"]} == {0}, name
    assert {s["load_pct"] for s in design("l50_design.json")["setups"]} == {0, 88}


#: Each block, its committed run table, bin table and verdicts (15 Oct 2026, after the runs).
JUDGED_FILES = (("K", "k_runs.csv", "k_bins.csv", "k_verdicts.json"),
                ("R", "r_runs.csv", None, "r_verdicts.json"),
                ("P", "p_runs.csv", None, "p_verdicts.json"),
                ("L", "l_runs.csv", None, "l_verdicts.json"),
                ("I", "i_runs.csv", None, "i_verdicts.json"))


def _judged(block, runs, bins):
    import order_scope
    rows = order_scope.read_table(str(HERE / runs))
    bin_rows = order_scope.read_table(str(HERE / bins)) if bins else []
    return order_scope.JUDGES[block](rows, bin_rows)


def test_the_committed_verdicts_are_the_judges_own():
    """Each block's verdicts file is what scripts/order_scope.py's judge gives on the committed run
    table, so a verdict cannot be edited by hand, and a judge changed later shows here."""
    for block, runs, bins, verdicts in JUDGED_FILES:
        committed = json.loads((HERE / verdicts).read_text(encoding="utf-8"))
        assert json.loads(json.dumps(_judged(block, runs, bins), sort_keys=True)) == committed, block


def test_the_record_prints_each_verdict_as_the_judge_gave_it():
    """The record's tables of results, one row per prediction, against the verdicts files."""
    text = (HERE / "README.md").read_text(encoding="utf-8")
    printed = {}
    import re
    for line in text.splitlines():
        # A cell may hold an escaped bar, as "Pr[S < 0 \| S_k]" does; split on the others.
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if len(cells) == 4 and cells[0][:2] in ("K-", "R-", "P-", "L-"):
            printed[cells[0]] = cells[3]
    expected = {}
    for block, runs, bins, verdicts in JUDGED_FILES:
        for name, entry in json.loads((HERE / verdicts).read_text(encoding="utf-8")).items():
            if "verdict" in entry:
                expected[name] = entry["verdict"]
            else:
                expected[name] = "decision recorded"
    expected.pop("I")
    assert printed == expected
