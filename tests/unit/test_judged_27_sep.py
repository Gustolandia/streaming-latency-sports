"""The record of 27 September, judged-with-and-without-the-brake.md, read against its answers.

Every number the record gives is recomputed here from the files beside it in judged-27-sep/: the
judges' own answers on each view, the two views' lists of what they left out, and the quality of
every campaign. A record rewritten, or answers judged again, cannot drift apart unseen.
"""
import csv
import json
import re
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
LAW = REPO / "docs" / "results" / "law"
HERE = LAW / "judged-27-sep"
VIEWS = ("all", "unflagged", "stopping")
PAIRS = {"matched": "first x86", "matched-b": "second x86", "arm": "Arm"}


def _record():
    return " ".join((LAW / "judged-with-and-without-the-brake.md").read_text(
        encoding="utf-8").split())


def _answer(view, name):
    return json.loads((HERE / view / (name + ".json")).read_text(encoding="utf-8"))


def _verdict(view, name):
    """The judge's first line of answer; the lines before it count each folder's runs."""
    lines = (HERE / view / (name + ".txt")).read_text(encoding="utf-8").splitlines()
    return next(l for l in lines if re.match(r"^(P\d|A9|M0|ERROR)", l))


def _shape(view, name, shape, part=None):
    """(holds, measured) of a free or fitted reading, from the judge's own lines."""
    lines = (HERE / view / (name + ".txt")).read_text(encoding="utf-8").splitlines()
    if part:
        start = next(i for i, l in enumerate(lines) if l.startswith("  %s: " % part))
        lines = lines[start:]
    for line in lines:
        m = re.match(r"^\s+%s shape: (holds|does not hold), measured (-?[\d.]+)" % shape, line)
        if m:
            return m.group(1) == "holds", float(m.group(2))
    raise AssertionError("no %s reading in %s" % (shape, name))


def test_no_verdict_differs_between_the_views():
    names = sorted(p.stem for p in (HERE / "all").glob("*.txt"))
    assert len(names) == 28
    for name in names:
        words = {view: _verdict(view, name) for view in VIEWS}
        assert len(set(words.values())) == 1, (name, words)
    text = _record()
    assert "no verdict changes" in text


def test_what_the_views_left_out():
    views = {v: json.loads((HERE / "views" / (v + ".json")).read_text(encoding="utf-8"))
             for v in ("unflagged", "stopping")}
    flagged = [c for c in views["unflagged"]["campaigns"]]
    recorded = [c for c in views["stopping"]["campaigns"]]
    assert sum(len(c["left_out"]) for c in flagged) == 14
    assert sum(len(c["left_out"]) for c in recorded) == 1110 and len(recorded) == 22
    text = _record()
    assert "1,110 runs were taken while the brake recorded, in 22 campaigns" in text
    assert "it would have stopped on 14 of them" in text
    for pair, word in PAIRS.items():
        mine = [c for c in recorded if c["pair"] == pair]
        flags = sum(len(c["left_out"]) for c in flagged if c["pair"] == pair)
        row = "| %s | %d | %d | %d |" % (word, len(mine), sum(len(c["left_out"]) for c in mine),
                                          flags)
        assert row in text, row


def test_the_moves_the_record_names():
    text = _record()
    assert round(_shape("all", "p2b_a2_kafka", "fitted")[1], 2) == 5.36
    assert round(_shape("stopping", "p2b_a2_kafka", "fitted")[1], 2) == 6.13
    assert "P2b's fitted ratio on Kafka goes from 5.36 to 6.13" in text
    assert round(_shape("all", "p2_a2_redis", "free")[1], 2) == 1.06
    assert round(_shape("stopping", "p2_a2_redis", "free")[1], 2) == 0.78
    assert round(_shape("all", "p8_a8_arm", "free")[1], 2) == 4.25
    assert round(_shape("stopping", "p8_a8_arm", "free")[1], 2) == 3.95
    assert "from 4.25 to 3.95" in text


def test_p1_on_kafka_is_in_reach_and_not_confirmed():
    body = (HERE / "all" / "p1_a1.txt").read_text(encoding="utf-8")
    kafka = body[body.index("  kafka: "):body.index("  redis: ")]
    assert "in reach: 4 slices, where the rule needs 4" in kafka
    holds, slope = _shape("all", "p1_a1", "free", "kafka")
    assert not holds and round(slope, 2) == 0.76
    assert round(_shape("all", "p1_a1", "fitted", "kafka")[1], 2) == 0.23
    assert "the free slope is 0.76 (95% interval 0.60 to 1.02)" in _record()


def test_the_new_a3_a8_a2_and_p6_numbers():
    text = _record()
    assert round(_shape("all", "p3b_x86_3", "free")[1], 3) == 0.048
    assert round(_shape("all", "p3b_x86_3r", "free")[1], 3) == 0.041
    for name in ("p3a_x86_1", "p3a_x86_2", "p3a_x86_3", "p3a_x86_3r", "p3a_arm"):
        assert _verdict("all", name) == "P3a: not confirmed"
    for name in ("p3b_x86_1", "p3b_x86_2", "p3b_x86_3", "p3b_x86_3r", "p3b_arm"):
        assert _verdict("all", name) == "P3b: confirmed"
    assert round(_shape("all", "p8_a8_arm_182140Z", "free")[1], 2) == 4.33
    assert round(_shape("all", "p2c_a2_redis", "fitted")[1], 2) == 0.87
    assert "its fitted slope now 0.87 (0.81 to 1.03)" in text
    parts = _answer("all", "p6_a6")["by_part"]
    medians = {part: round(p["median_ratio"], 2) for part, p in parts.items()}
    assert medians == {"arm, kafka": 2.49, "matched, kafka": 3.24, "matched, redis": 13.08,
                       "matched-b, kafka": 2.63}
    assert all(p["within_band"] == 0 for p in parts.values())


def test_the_a9_table_is_its_answer():
    found = _answer("all", "a9")
    text = _record()
    names = {"arm": "Arm", "matched": "first x86", "matched-b": "second x86"}
    for part, p in found["by_part"].items():
        pair, backend = part.split(", ")
        shares = []
        for load in ("75", "88"):
            one = p["loads"][load]["a9_1"]
            shares.append("%.1f%%" % (100.0 * one["mostly_waiting"] / one["negative_readings"]))
        b = p["a9_2b"]
        a92 = "%d of %d, %.3f" % (p["within_band"], p["setups_with_a_ratio"], p["median_ratio"])
        a92b = "%d of %d, %.2f" % (b["within_band"], b["setups_with_a_ratio"], b["median_ratio"])
        wrap = (lambda s, bold: "**%s**" % s if bold else s)
        row = "| %s, %s | %s | %s | %s |" % (
            names[pair], backend.capitalize() if backend == "kafka" else "Redis",
            wrap(" / ".join(shares), p["a9_1_holds"]), a92, wrap(a92b, b["confirmed"]))
        assert row in text, row
    assert not found["confirmed"] and not found["a9_2b_confirmed"] and not found["a9_1_holds"]


def test_the_m0_table_is_its_answer():
    found = _answer("all", "m0")
    text = _record()
    for part, label in (("kafka", "Kafka"), ("redis ack 1", "Redis, one acknowledgement per "
                                                            "message"),
                        ("redis ack 200", "Redis, acknowledgements in batches of 200")):
        p = found["parts"][part]
        lo, hi = p["departure"]["interval"]
        row = "| %s | %.3f (%.3f to %.3f) |" % (label, p["departure"]["slope"], lo, hi)
        assert row in text, part
        assert not p["recording_effect"]["log_stays_on"]


def test_the_quality_table_is_the_csv():
    rows = list(csv.DictReader((HERE / "quality_by_campaign.csv").open(encoding="utf-8")))
    text = _record()
    for pair, word in PAIRS.items():
        mine = [r for r in rows if r["pair"] == pair]
        n = lambda key: sum(int(r[key]) for r in mine)
        row = "| %s | %d | %s | %s | %d | %d (%s) |" % (
            word, len(mine), "{:,}".format(n("runs")), "{:,}".format(n("count")),
            n("far_repeats"), n("runs_with_stalls"), "{:,}".format(n("stalled_messages")))
        assert row in text, row
    assert sum(int(r["runs_over_a_tenth_stalled"]) for r in rows) == 7
    assert "more than 10% in seven runs" in text
