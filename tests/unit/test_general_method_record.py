"""Freeze 44 (plan version 47) as registered: the design's fingerprint, the plan that freezes it,
the design files the queues are made from, and the freezes' own record. A change to any of them
after the fact fails here, as a freeze is never edited."""
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import general_method as gm  # noqa: E402
import run_queue as rq  # noqa: E402
import under_load_posthoc as ph  # noqa: E402

FOLDER = REPO / "docs" / "results" / "general_method"
#: DESIGN47.md's fingerprint, as registered; DESIGN47.sha256 holds the same.
FINGERPRINT47 = "17d3ba50e87daefcf9229a3b265dd9e1c93b9fcdde3d47fa9aa4e6c7e14823fc"
#: Pilot round a's statements (D47-11), made before any judged run: block S's producer at
#: normal priority and block A's two Redis setups are left out, with the reasons in README.md.
BLOCKS = {"v": 3, "n": 3, "p": 2, "k": 5, "c": 3, "s": 1, "a": 2}
LEFT_OUT = ("S2000-redis-prodnormal", "A2000-redis-d1", "A2000-redis-d256")
#: The same: each setup's frozen duty, the starting duty corrected by the median miss of its
#: pilot runs where any of them missed 70% by more than 3 points. Block C has none until plan
#: version 48 amends it.
DUTIES = {"V2000-redis-d1": 75, "V2000-redis-d256": 75, "V2000-redis-d256-lib": 75,
          "N2000-nats-d1": 75, "N2000-nats-d256": 75, "N2000-nats-go": 75,
          "P2000-rabbitmq-p1": 72, "P2000-rabbitmq-p1000": 75,
          "K2000-kafka-python": 75, "K2000-kafka-java": 75, "K2000-kafka-franz": 75,
          "K2000-kafka-rdk": 75, "K2000-kafka-rdk-rt": 75, "S2000-redis-udp": 82,
          "A2000-kafka-rdk": 73, "A2000-kafka-rdk-rt": 73,
          # Block C's, from its own pilot under plan version 48 (DESIGN48.md, D48-2).
          "C2000-kafka-base": 75, "C2000-kafka-core": 75, "C2000-kafka-core-sib": 75}
#: Pilot round a's first attempt (23 Oct 2026): the Arm pair held 66.3% at a duty of 75 and
#: starts at 79; the x86 pair held 68.0%.
PILOTS = {"x86": (18, 75), "arm": (4, 79)}
#: The same: block C's isolated arms run the load on 6 and 7 of the 8 CPUs at the duty of the
#: baseline, 70% on each CPU the load runs on, and so 70% x 6/8 and x 7/8 of the machine.
LOADS = {"C2000-kafka-core": 53, "C2000-kafka-core-sib": 61}
#: The same: the consumers that are not Python sample no thread of their own.
UNSAMPLED = ("java", "franz", "nats-go")


def design(name):
    with open(FOLDER / name, encoding="utf-8") as fh:
        return json.load(fh)


def plan_text():
    return " ".join((REPO / "freezes" / "44-experiment-plan" / "experiment_plan.tex")
                    .read_text(encoding="utf-8").split())


def test_the_design_is_the_one_registered():
    assert hashlib.sha256((FOLDER / "DESIGN47.md").read_bytes()).hexdigest() == FINGERPRINT47
    assert (FOLDER / "DESIGN47.sha256").read_text(encoding="utf-8").split()[0] == FINGERPRINT47


def test_the_design_checks_out_byte_for_byte():
    """A Windows checkout converts line endings unless git is told not to, and a converted copy
    would no longer match its fingerprint."""
    rules = (REPO / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "docs/results/general_method/DESIGN47.md -text" in rules


def test_the_reader_judges_by_the_margins_registered():
    """Each margin the plan states is the one scripts/general_method.py judges with."""
    assert (gm.Q_P99_US, gm.M1C_ONE_US, gm.M1C_LIBRARY_US) == (150.0, 10.0, 100.0)
    assert (gm.M2B_POINTS, gm.M2C_WAITING, gm.M2C_CERTIFIED) == (6.0, 0.999, 0.999)
    assert (gm.CERTIFY_B_MS, gm.CERTIFY_B_DESCRIBED_MS, gm.Q_SHARE_OF_B) == (10.0, 2.0, 0.5)
    assert (gm.HOLDS_STILL, gm.GROWTH, gm.HALF) == (1.2, 1.5, 0.5)
    assert (gm.KC_C_FRACTION, gm.KC_H_RATIO, gm.KC_H_UNWAITED) == (0.5, 1.2, 0.5)
    assert gm.C_A_FRACTION == 1.0 / 3.0 and gm.ALPHA == 0.05
    assert (gm.BOOTSTRAP, gm.BOOTSTRAP_SEED, gm.INTERVAL) == (2000, 20261104, 0.95)
    assert (gm.WAITING_DEPTH, gm.WAITING_PREFETCH) == (256, 1000)
    assert (ph.RESOLUTION_US, ph.TRIANGLE_MIN) == (50.0, 100)


def test_each_block_runs_its_setups_four_rounds():
    seen = set()
    for block, setups in BLOCKS.items():
        d = design("g%s_design.json" % block)
        rq.check_design(d)
        assert d["rounds"] == 4 and d["seed"] == 20261104 and len(d["setups"]) == setups
        for s in d["setups"]:
            assert s["id"].startswith(block.upper() + "2000-") and s["id"] not in seen
            seen.add(s["id"])
            assert s["arrival"] == "poisson" and s["load_blocks_s"] == 5
            assert s["load_pct"] == LOADS.get(s["id"], 70)
            assert s["schedstat"] is (s.get("consumer") not in UNSAMPLED)
            assert s["producer_priority"] is (s["id"] != "S2000-redis-prodnormal")
            assert s.get("duty_pct") == DUTIES.get(s["id"]), "the duty the pilot froze"
            assert "RATE=2000 DURATION=70 WARMUP_S=20 PRIME_S=60" in d["about"]
    assert sum(BLOCKS[b] for b in BLOCKS if b != "a") * 4 == 68 and BLOCKS["a"] * 4 == 8
    assert sorted(DUTIES) == sorted(seen)


def test_the_pilot_runs_every_setup_once_at_the_starting_duty():
    judged = {}
    for block in BLOCKS:
        for s in design("g%s_design.json" % block)["setups"]:
            judged[s["id"]] = s
    for pair, (count, duty) in PILOTS.items():
        d = design("gpilot_%s_design.json" % pair)
        rq.check_design(d)
        assert d["rounds"] == 1 and len(d["setups"]) == count
        for s in d["setups"]:
            assert s["id"].endswith("-pilot") and s["duty_pct"] == duty
            if s["id"][:-len("-pilot")] in LEFT_OUT:
                assert s["id"][:-len("-pilot")] not in judged
                continue
            twin = judged[s["id"][:-len("-pilot")]]
            if twin["id"].startswith("C2000-"):
                # Plan version 48 amends block C's placement after this pilot ran it
                # (DESIGN48.md), and block C has its own pilot (gpilot_c48_design.json).
                twin = dict(twin, irq_cpus="core")
                twin.pop("threads_apart", None)
            assert dict(s, id=twin["id"], duty_pct=None) == dict(twin, duty_pct=None)


def test_the_remedy_setups_are_as_the_design_says():
    v = {s["id"]: s for s in design("gv_design.json")["setups"]}
    assert v["V2000-redis-d256"]["depth"] == 256 and v["V2000-redis-d256"]["one_reply_reads"]
    assert not v["V2000-redis-d256-lib"]["one_reply_reads"] and v["V2000-redis-d1"]["depth"] == 1
    k = {s["id"]: s for s in design("gk_design.json")["setups"]}
    assert k["K2000-kafka-rdk-rt"]["fetch_rt"] and "fetch_rt" not in k["K2000-kafka-rdk"]
    assert sorted(s["consumer"] for s in k.values()) == ["confluent", "confluent", "franz",
                                                         "java", "kafka-python"]
    c = {s["id"]: s for s in design("gc_design.json")["setups"]}
    # Plan version 48 (DESIGN48.md): the card's interrupts on the core's other thread, and the
    # consumer's other threads there too where the arm keeps the core.
    assert all(s["priority"] and s["irq_cpus"] == "sibling" and s["irqbalance_off"]
               and s["rps_off"] for s in c.values())
    assert [s["id"] for s in c.values() if s.get("threads_apart")] == [
        "C2000-kafka-core", "C2000-kafka-core-sib"]
    assert not c["C2000-kafka-base"].get("whole_core")
    assert c["C2000-kafka-core-sib"]["sibling_load"] and "sibling_load" not in c["C2000-kafka-core"]
    p = {s["id"]: s["prefetch"] for s in design("gp_design.json")["setups"]}
    assert p == {"P2000-rabbitmq-p1": 1, "P2000-rabbitmq-p1000": 1000}


def test_the_plan_is_fingerprinted_and_listed():
    folder = REPO / "freezes" / "44-experiment-plan"
    names = []
    for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split()
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name
        names.append(name)
    assert sorted(names) == ["experiment_plan.pdf", "experiment_plan.tex"]
    record = (REPO / "freezes" / "README.md").read_text(encoding="utf-8")
    assert "[`44-experiment-plan/`](44-experiment-plan/) | 23 October 2026 |" in record


def test_the_plan_says_what_the_design_says():
    plan = plan_text()
    assert "Version 47, frozen on 23 October 2026" in plan
    for tag in range(1, 13):
        assert "D47-%d &" % tag in plan and "\\chg{D47-%d}" % tag in plan, tag
    assert "\\chg{D46-" not in plan and "\\chgold{D46-1}" in plan
    for phrase in ("72 runs on the x86 pair and 16 on the Arm pair",
                   "$Q$'s 99th percentile at most 150~$\\mu$s",
                   "within 6 points of the broker's",
                   "at least 99.9\\% of messages",
                   "within 1/1.2 and 1.2 by two one-sided tests",
                   "at least half of the messages found no fetch waiting",
                   "at most a third of the baseline arm's",
                   "keep 256 requests waiting"):
        assert phrase in plan, phrase
    design_text = " ".join((FOLDER / "DESIGN47.md").read_text(encoding="utf-8").split())
    for phrase in ("`Q`'s 99th percentile is at most 150 µs", "within 6 points of the broker's",
                   "at least 99.9% of messages", "within 1/1.2 and 1.2 by TOST",
                   "at least half of the messages found no fetch waiting",
                   "at most a third of the baseline arm's"):
        assert phrase in design_text, phrase
    assert os.path.exists(str(FOLDER / "README.md"))
