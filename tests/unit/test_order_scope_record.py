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


#: Each judged block's files, as the design's table counts its runs.
JUDGED = {"K": ["k_design.json"], "R": ["r_design.json"], "P": ["p_design.json"],
          "L": ["l50_design.json", "l500_design.json", "l5000_design.json"],
          "I": ["i_default_design.json", "i_poll_design.json"]}


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
        assert counted == runs, (block, counted, runs)
        assert {design(f)["rounds"] for f in files} == {rounds}, block
        ids = [s["id"] for f in files for s in design(f)["setups"]]
        assert len(set(ids)) == len(ids) and all(i.startswith(block) for i in ids), block


#: The pilot's files: K and R in one queue, L one per rung, I one run on the idle=poll boot.
PILOTS = ["k_pilot_design.json", "lp50_design.json", "lp500_design.json", "lp5000_design.json",
          "ip_design.json"]


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


def test_every_setup_records_what_its_predictions_read():
    """K's checks need the journal on both clients and both directions of the producer's
    connection captured; R and I need both journals; L, as the design says, the consumer's
    journal alone; P and L need both captures."""
    for f in JUDGED["K"] + JUDGED["R"] + JUDGED["I"]:
        assert all(s.get("so_journal") is True and s.get("so_timestamps") == "sched"
                   for s in design(f)["setups"]), f
    for f in JUDGED["L"] + PILOTS[1:4]:
        assert all(s.get("so_journal") == "consumer" and s.get("so_timestamps") == "sched"
                   for s in design(f)["setups"]), f
    for f in JUDGED["K"] + JUDGED["L"]:
        assert all(s.get("send_capture_both") for s in design(f)["setups"]), f
    for f in JUDGED["K"] + JUDGED["P"] + JUDGED["L"]:
        assert all(s.get("recv_capture") and s.get("send_capture")
                   for s in design(f)["setups"]), f
    assert [s["load_pct"] for s in design("r_design.json")["setups"]] == [88] * 4
    assert {s["delay_ms"] for s in design("p_design.json")["setups"]} == {0, 1, 2}
