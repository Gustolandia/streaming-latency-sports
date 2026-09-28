"""The record of 28 September, judged-without-the-paused-runs.md, read against its answers.

Every number the record gives is recomputed here from the files beside it: the judges' answers on
all the runs and on the view without the paused ones (judged-27-sep/all and unpaused), the view's
own list of what it left out (judged-27-sep/views/unpaused.json), and the pause census's list of
paused runs (strange-results-28-sep/pause_runs.csv). The one verdict that changes is found by
comparing every answer, not by reading the record.
"""
import csv
import json
import re
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
LAW = REPO / "docs" / "results" / "law"
HERE = LAW / "judged-27-sep"
PAIRS = ("matched", "matched-b", "arm")


def _record():
    return " ".join((LAW / "judged-without-the-paused-runs.md").read_text(
        encoding="utf-8").split())


def _has(*phrases):
    text = _record()
    for phrase in phrases:
        assert " ".join(phrase.split()) in text, phrase


def _lines(view, name):
    return (HERE / view / (name + ".txt")).read_text(encoding="utf-8").splitlines()


def _verdict(view, name):
    return next(l for l in _lines(view, name) if re.match(r"^(P\d|A9|M0|ERROR)", l))


def _answers(view):
    return sorted(p.stem for p in (HERE / view).glob("*.txt"))


def _reading(view, name, summary, part=None):
    """(holds, measured, low, high) of a free or fitted reading, from the judge's own lines."""
    lines = _lines(view, name)
    if part:
        lines = lines[next(i for i, l in enumerate(lines) if l.startswith("  %s: " % part)):]
    line = next(l for l in lines if l.strip().startswith(summary + " shape:"))
    m = re.search(r"(holds|does not hold), measured (-?[\d.]+), 95% interval (-?[\d.]+) to "
                  r"(-?[\d.]+)", line)
    return m.group(1) == "holds", float(m.group(2)), float(m.group(3)), float(m.group(4))


def test_the_view_leaves_out_exactly_the_runs_the_census_marks_paused():
    view = json.loads((HERE / "views" / "unpaused.json").read_text(encoding="utf-8"))
    left = set((c["pair"], run) for c in view["campaigns"] for run in c["left_out"])
    with open(LAW / "strange-results-28-sep" / "pause_runs.csv", newline="",
              encoding="utf-8") as fh:
        paused = set((r["pair"], r["run"]) for r in csv.DictReader(fh) if r["paused"] == "True")
    assert left == paused
    counts = dict((pair, sum(1 for p, _ in left if p == pair)) for pair in PAIRS)
    kept = sum(c["kept"] for c in view["campaigns"])
    campaigns = len(view["campaigns"])
    _has("**%d runs**: %d on the first x86 pair, %d on the second and %d on the Arm pair, leaving "
         "%s runs in the %d campaigns" % (len(left), counts["matched"], counts["matched-b"],
                                          counts["arm"], format(kept, ","), campaigns))
    assert view["view"] == "unpaused" and "150 ms" in view["without"]


def test_every_answer_is_there_on_both_views():
    assert _answers("unpaused") == _answers("all") and len(_answers("all")) == 28
    for name in _answers("unpaused"):
        text = (HERE / "unpaused" / (name + ".txt")).read_text(encoding="utf-8")
        assert "brake_views" not in text and "Users" not in text, "a folder named as at home"


def test_one_verdict_changes_and_it_is_p3a_on_the_first_x86_pair():
    changed = [name for name in _answers("all")
               if _verdict("all", name) != _verdict("unpaused", name)]
    assert changed == ["p3a_x86_1"]
    assert _verdict("all", "p3a_x86_1") == "P3a: not confirmed"
    assert _verdict("unpaused", "p3a_x86_1") == "P3a: confirmed"
    _has("| P3a | A3, first x86 (19 September) | not confirmed | **confirmed** |")


def test_the_table_gives_every_verdict_as_the_judges_do():
    def said(view, *names):
        found = set(_verdict(view, n).split(": ", 1)[1] for n in names)
        assert len(found) == 1, (view, names, found)
        return found.pop()
    rows = [("P1", "A1, first x86", ["p1_a1"]),
            ("P2, P2b, P2d", "A2, both backends",
             ["p2_a2_kafka", "p2_a2_redis", "p2b_a2_kafka", "p2b_a2_redis", "p2d_a2_kafka",
              "p2d_a2_redis"]),
            ("P3a", "A3, the four other campaigns",
             ["p3a_arm", "p3a_x86_2", "p3a_x86_3", "p3a_x86_3r"]),
            ("P3b", "A3, five campaigns",
             ["p3b_arm", "p3b_x86_1", "p3b_x86_2", "p3b_x86_3", "p3b_x86_3r"]),
            ("P4", "A7, first x86", ["p4_a7"]), ("P6", "A6's recordings", ["p6_a6"]),
            ("P7", "A5, second x86", ["p7_a5"]),
            ("P8", "A8, both x86 and Arm", ["p8_a8_x86", "p8_a8_arm", "p8_a8_arm_182140Z"]),
            ("P9", "A4, Arm", ["p9_a4"]),
            ("A9-1, A9-2, A9-2b", "A9, all three pairs", ["a9"])]
    for prediction, block, names in rows:
        _has("| %s | %s | %s | %s |" % (prediction, block, said("all", *names),
                                         said("unpaused", *names)))
    assert said("all", "p2c_a2_kafka") == "not confirmed"
    assert said("all", "p2c_a2_redis") == said("unpaused", "p2c_a2_redis") == "confirmed"
    _has("| P2c | A2, Kafka / Redis | not confirmed / confirmed | the same |")


def test_p3a_on_the_edge_of_its_rule():
    for view, low, high in (("all", "-0.2526", "0.2341"), ("unpaused", "-0.2463", "0.2272")):
        holds, _, lo, hi = _reading(view, "p3a_x86_1", "fitted")
        assert ("%.4f" % lo, "%.4f" % hi) == (low, high)
        assert holds is (view == "unpaused")
        _has("**%s to %s ms**" % (low.replace("-", "−"), high))
    for view in ("all", "unpaused"):
        holds, _, lo, hi = _reading(view, "p3a_x86_1", "free")
        assert holds
    _has("(%s to %s, then %s to %s)" % tuple(
        ("%.4f" % v).replace("-", "−") for view in ("all", "unpaused")
        for v in _reading(view, "p3a_x86_1", "free")[2:]))
    _has("its lower end 0.0026 ms past the band", "0.0026 ms past the bar on one side and 0.0037 "
         "ms inside it on the other")
    assert "%.4f" % (-0.25 - _reading("all", "p3a_x86_1", "fitted")[2]) == "0.0026"
    assert "%.4f" % (_reading("unpaused", "p3a_x86_1", "fitted")[2] + 0.25) == "0.0037"
    counted = [int(re.search(r": (\d+) runs counted", l).group(1))
               for view in ("all", "unpaused") for l in _lines(view, "p3a_x86_1")
               if "runs counted" in l]
    assert counted == [288, 282], "six of the campaign's 288 runs left out"
    _has("On all 288 runs of that campaign", "Without its 6 paused runs")


def test_what_moved():
    def pair(view, name, summary, part=None):
        return _reading(view, name, summary, part)
    def slope(view, part, summary):
        """From the judge's JSON, which keeps the digits its printed line rounds away."""
        found = json.loads((HERE / view / "p1_a1.json").read_text(encoding="utf-8"))
        return "%.3f" % found["by_part"][part]["by_summary"][summary]["value"]
    k = [slope(v, "kafka", s) for v in ("all", "unpaused") for s in ("free", "fitted")]
    r = [slope(v, "redis", s) for v in ("all", "unpaused") for s in ("free", "fitted")]
    _has("the slope of the cliff on the slice, %s free and %s fitted, becomes %s and %s" % tuple(k),
         "On Redis %s and %s become %s and %s" % tuple(r))
    p8 = [pair(v, "p8_a8_x86", "fitted") for v in ("all", "unpaused")]
    _has("Python's plateau over Java's, %.2f (%.2f to %.2f), becomes %.2f (%.2f to %.2f)"
         % (p8[0][1:] + p8[1][1:]))
    a9 = dict((v, json.loads((HERE / v / "a9.json").read_text(encoding="utf-8")))
              for v in ("all", "unpaused"))
    for v in a9:
        met = sorted(name for name, p in a9[v]["by_part"].items() if p["a9_2b"]["confirmed"])
        assert len(met) == 4 and len(a9[v]["by_part"]) == 6
    assert sorted(n for n, p in a9["all"]["by_part"].items() if p["a9_2b"]["confirmed"]) == \
        sorted(n for n, p in a9["unpaused"]["by_part"].items() if p["a9_2b"]["confirmed"])

    def band(v):
        setups = a9[v]["by_part"]["matched, kafka"]["a9_2b"]["setups"].values()
        ratios = [s["ratio"] for s in setups if s["ratio"] is not None]
        return sum(1 for x in ratios if 0.67 <= x <= 1.5), len(ratios)
    (was_in, was_of), (now_in, now_of) = band("all"), band("unpaused")
    medians = ["%.2f" % a9[v]["by_part"]["matched, kafka"]["a9_2b"]["median_ratio"]
               for v in ("all", "unpaused")]
    _has("On the first x86 pair's Kafka part %d of %d setups are within the band, where %d of %d "
         "were, and its median ratio moves from %s to %s" % (now_in, now_of, was_in, was_of,
                                                             *medians))
    free = [pair(v, "p3a_x86_2", "free") for v in ("all", "unpaused")]
    _has("the free reading's move of the halfway point, %s ms, becomes %s ms" % tuple(
        ("%.3f" % f[1]).replace("-", "−") for f in free))
    assert all(f[2] < -0.25 and not f[0] for f in free), "its interval reached past the band"


def test_the_record_is_indexed_and_names_its_programs():
    text = _record()
    for script in ("pause_census.py", "brake_views.py"):
        assert "(../../../scripts/%s)" % script in text
    index = (REPO / "docs" / "results" / "README.md").read_text(encoding="utf-8")
    assert "judged-without-the-paused-runs.md" in index
