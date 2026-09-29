"""Supplement S16.10 and S16.11, the pre-registered law campaign, read against its answers.

Every number the two subsections print is recomputed here from the committed records of that
campaign: the strange results of 28 September (docs/results/law/strange-results-28-sep/), the
final judging on all the runs and without the paused ones (docs/results/law/judged-27-sep/), and
the run registry (docs/results/registry/). The subsections were written after the verdicts and
change none of them, so the tests also hold them to saying so.
"""
import csv
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
LAW = REPO / "docs" / "results" / "law"
STRANGE = LAW / "strange-results-28-sep"
JUDGED = LAW / "judged-27-sep"


def _ledger():
    gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
    return dict(re.findall(r"\\newcommand\{\\(\w+)\}\{(.*)\}\s*$", gen, re.M))


def _section(start, end):
    """One section's source, flattened, with S16.11's emitted readings printed as numbers.

    v5.1 (29 Sep): S16.11's judge readings are emitted (`cliff_macros`) where they were typed,
    after one of its ranges was found to leave out, silently, the slice it does not cover. The
    pins below were written against the printed numbers and recompute them from the artifacts,
    so the macros are expanded first and the pins keep checking the numbers, not the markup.
    """
    text = (REPO / "postmortem.tex").read_text(encoding="utf-8")
    body = text[text.index(start):text.index(end, text.index(start))]
    ledger = _ledger()
    body = re.sub(r"\\(cliff[A-Za-z]+)(?![A-Za-z])",
                  lambda m: ledger.get(m.group(1), m.group(0)), body)
    return " ".join(body.split())


@pytest.fixture(scope="module")
def s1610():
    return _section(r"\subsection{S16.10.", r"\subsection{S16.11.")


@pytest.fixture(scope="module")
def s1611():
    return _section(r"\subsection{S16.11.", r"\section{S17.")


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _span(values, places):
    return "%.*f" % (places, min(values)), "%.*f" % (places, max(values))


def _has(text, *phrases):
    for phrase in phrases:
        assert " ".join(phrase.split()) in text, phrase


def test_the_campaign_is_counted_as_the_final_judging_counted_it(s1610):
    quality = _csv(JUDGED / "quality_by_campaign.csv")
    runs = sum(int(r["runs"]) for r in quality)
    assert len(quality) == 156 and runs == 8102
    _has(s1610, "in %s runs over %d campaigns in September 2026" % (format(runs, ","),
                                                                     len(quality)))
    assert set(r["pair"] for r in quality) == {"matched", "matched-b", "arm"}


def test_the_rate_at_half_the_slice(s1610):
    rows = [r for r in _csv(STRANGE / "cliff_levels.csv") if r["view"] == "data"
            and r["point"] == "p05s" and r["of_p09s"]]
    ratios = [float(r["of_p09s"]) for r in rows]
    assert len(rows) == 10
    assert sum(1 for r in rows if r["block"] == "A1") == 6
    assert sum(1 for r in rows if r["block"] == "A4") == 4
    _has(s1610, "$%s$ to $%s$ times its value at 0.9 of the slice, in each of the ten slice and "
                "broker combinations" % _span(ratios, 2),
         "six on the first x86 pair and four on the Arm pair")


def test_each_acknowledgments_wait(s1610):
    parts = _json(STRANGE / "ack_wait_shape.json")["parts"]
    assert len(parts) == 12
    _has(s1610, "%s of them in %d runs" % (format(sum(p["acks"] for p in parts.values()), ","),
                                           sum(p["runs"] for p in parts.values())))
    pct = lambda key: [100 * p[key] for p in parts.values()]
    _has(s1610, "$%s$ to $%s\\%%$ were still waiting at 2~ms, $%s$ to $%s\\%%$ at 3~ms and $%s$ to "
                "$%s\\%%$ past 4~ms" % (_span(pct("over_2_of_over_1"), 1)
                                        + _span(pct("over_3_of_over_1"), 1)
                                        + _span(pct("past_4_of_over_1"), 1)))
    left = lambda shape: [p[shape]["rms_of_scale"] for p in parts.values()]
    _has(s1610, "a root mean square of $%s$ to $%s$ of that scale over the twelve parts, and the "
                "whole-slice shape $%s$ to $%s$" % (_span(left("rest of a slice"), 3)
                                                    + _span(left("whole slice"), 3)))


def test_the_two_shapes_keep_what_the_text_says(s1610):
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    import a9_decompose
    rest = a9_decompose.WAIT_SHAPES["rest of a slice"]
    whole = a9_decompose.WAIT_SHAPES["whole slice"]
    assert whole(3.0, 3.0, 1.0) == 1.0 and whole(4.0, 3.0, 1.0) == 0.0
    assert "%.0f" % (100 * rest(2.0, 3.0, 1.0) / rest(1.0, 3.0, 1.0)) == "60"
    assert "%.0f" % (100 * rest(3.0, 3.0, 1.0) / rest(1.0, 3.0, 1.0)) == "20"
    assert rest(4.0, 3.0, 1.0) == 0.0
    _has(s1610, "keeps $60\\%$ to 2~ms, $20\\%$ to 3~ms and none past 4~ms")
    # The traced mode's octave, read from the ledger, holds half of such a wait.
    ledger = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
    lo = float(re.search(r"\\newcommand\{\\tracedModeLo\}\{([\d.]+)\}", ledger).group(1))
    hi = float(re.search(r"\\newcommand\{\\tracedModeHi\}\{([\d.]+)\}", ledger).group(1))
    assert rest(lo, 3.0, 1.0) - rest(hi, 3.0, 1.0) == pytest.approx(0.5)
    _has(s1610, "puts half its mass in the octave from $\\tracedModeLo$ to $\\tracedModeHi$~ms")


def test_the_prediction_from_the_waits_and_the_recordings_effect(s1610):
    a9 = _json(JUDGED / "all" / "a9.json")["by_part"]
    met = sum(1 for p in a9.values() if p["a9_2b"]["confirmed"])
    medians = [p["a9_2b"]["median_ratio"] for p in a9.values()]
    assert (met, len(a9)) == (4, 6)
    _has(s1610, "met its rule on four of six pair and broker parts, with medians of prediction "
                "over measurement of $%s$ to $%s$" % _span(medians, 2))
    summary = _json(STRANGE / "a9_summary.json")["a9"]
    kafka = [p["recorded_over_unrecorded"] for k, p in summary.items() if k.endswith("kafka")]
    redis = [p["recorded_over_unrecorded"] for k, p in summary.items() if k.endswith("redis")]
    _has(s1610, "$%s$ to $%s$ times for \\kafka{} and $%s$ to $%s$ times for \\redis{}"
         % (_span(kafka, 2) + _span(redis, 2)))


def test_a_preemption_and_a_wake_up(s1610):
    parts = _json(STRANGE / "a9_summary.json")["a9"]
    preempt = [p["preempt_band_ratio"] for p in parts.values()]
    wake_x86 = [p["wake_band_ratio"] for k, p in parts.items() if not k.startswith("arm")]
    wake_arm = [parts[k]["wake_band_ratio"] for k in ("arm, kafka", "arm, redis")]
    _has(s1610, "is $%s$ to $%s$ for waits begun by a preemption, on all three pairs, and $%s$ to "
                "$%s$ for waits begun by a wake-up on the two x86 pairs, $%s$ and $%s$ on the Arm "
                "pair" % (_span(preempt, 2) + _span(wake_x86, 2)
                          + tuple("%.2f" % v for v in wake_arm)))


def test_the_table_of_slopes_is_the_judges(s1610):
    judged = dict(((r["prediction"], r["part"], r["view"]), r)
                  for r in _csv(STRANGE / "cliff_judged.csv"))
    for prediction, pair in (("P1", "first x86"), ("P9", "Arm")):
        for part, broker in (("kafka", "\\kafka{}"), ("redis", "\\redis{}")):
            cells = []
            for view in ("data", "plan", "residual"):
                row = judged[(prediction, part, view)]
                cells += ["%.3f" % float(row["free"]), "%.3f" % float(row["fitted"])]
            row_text = "%s & %s & %s\\\\" % (pair, broker, " & ".join(cells))
            assert row_text in s1610, row_text


def test_the_judge_of_the_tick_and_its_lawful_world(s1611):
    judged = dict(((r["prediction"], r["block"], r["view"]), r)
                  for r in _csv(STRANGE / "cliff_judged.csv"))
    plan = judged[("P2", "A2 redis", "plan")]
    _has(s1611, "the P2 program returns $%.2f$ on the free reading and $%.2f$ on the fitted shape "
                "for \\redis{}" % (float(plan["free"]), float(plan["fitted"])))
    lines = _json(STRANGE / "cliff_summary.json")["width_lines"]
    reach = ("kafka, 3", "redis, 1.5", "redis, 3")
    p2 = [lines["plan"][k][s]["ratio_250"] for k in reach for s in ("free", "fitted")]
    p2b = [lines["plan"][k][s]["ratio_100"] for k in reach for s in ("free", "fitted")]
    _has(s1611, "the same formula gives $%s$ to $%s$ for P2 and $%s$ to $%s$ for P2b"
         % (_span(p2, 1) + _span(p2b, 1)))

    def line(view, key, summary):
        found = lines[view][key][summary]
        sign = "-" if found["intercept"] < 0 else "+"
        return "$%.2fh %s %.2f$~ms" % (found["slope"], sign, abs(found["intercept"]))
    _has(s1611, "%s on the free reading and %s on the fitted shape for \\redis{} and %s fitted for "
                "\\kafka{}" % (line("data", "redis, 1.5", "free"),
                               line("data", "redis, 1.5", "fitted"),
                               line("data", "kafka, 1.5", "fitted")),
         "Equation~\\ref{eq:restofslice} gives %s for \\redis{} there, against the measured %s"
         % (line("residual", "redis, 3", "fitted"), line("data", "redis, 3", "fitted")))
    verdicts = dict((name, (JUDGED / "all" / (name + ".txt")).read_text(encoding="utf-8"))
                    for name in ("p2_a2_kafka", "p2_a2_redis", "p2b_a2_kafka", "p2b_a2_redis",
                                 "p2c_a2_kafka", "p2c_a2_redis"))
    said = dict((n, re.search(r"^P2\w?: (.+)$", t, re.M).group(1)) for n, t in verdicts.items())
    assert set(said[n] for n in ("p2_a2_kafka", "p2_a2_redis", "p2b_a2_kafka",
                                 "p2b_a2_redis")) == {"not confirmed"}
    assert (said["p2c_a2_kafka"], said["p2c_a2_redis"]) == ("not confirmed", "confirmed")
    _has(s1611, "P2's and P2b's verdicts, not confirmed on either broker, therefore carry no "
                "evidence about the law either way",
         "its verdicts, not confirmed on \\kafka{} and confirmed on \\redis{}, rest on them too")


def test_p4(s1611):
    plateaus = _json(STRANGE / "cliff_summary.json")["plateaus"]["A7"]
    _has(s1611, "\\redis{}'s ordinary plateau in that campaign was $%.2f\\%%$"
         % (100 * plateaus["redis"]["ordinary"]),
         "On \\kafka{}, whose plateau was $%.2f\\%%$, priority took the rate to zero"
         % (100 * plateaus["kafka"]["ordinary"]))
    assert plateaus["kafka"]["go_first"] == 0.0
    text = (JUDGED / "all" / "p4_a7.txt").read_text(encoding="utf-8")
    assert "\nP4: not confirmed\n" in text and "  kafka: confirmed" in text
    assert "  redis: not confirmed" in text


def test_the_paused_runs(s1611):
    pauses = _json(STRANGE / "pause_summary.json")
    view = _json(JUDGED / "views" / "unpaused.json")
    left = [(c["pair"], r) for c in view["campaigns"] for r in c["left_out"]]
    by_pair = lambda pair: sum(1 for p, _ in left if p == pair)
    _has(s1611, "In %d of the 8,102 runs a message arrived more than 150~ms late after the "
                "warm-up, %d and %d of them on the two x86 pairs and one on the Arm pair"
         % (len(left), by_pair("matched"), by_pair("matched-b")))
    assert by_pair("arm") == 1
    longest = max(k["longest_ms"] for k in pauses["kinds"].values())
    _has(s1611, "the longest pause lasted $%.1f$~s" % (longest / 1000.0))
    hour = pauses["hour"]
    _has(s1611, "%d of %d in its first quarter" % (hour["by_quarter"][0], hour["runs"]))
    assert pauses["together"]["within"] == {"matched & matched-b": 0}
    assert pauses["together"]["window_s"] == 5.0 and "within 5~s of one on the other" in s1611
    assert pauses["hour_since_boot"]["rayleigh_p"] > 0.05 > hour["rayleigh_p"]

    def low(name):
        text = (JUDGED / name / "p3a_x86_1.txt").read_text(encoding="utf-8")
        return float(re.search(r"fitted shape: .*95% interval (-?[\d.]+) to", text).group(1))
    _has(s1611, "ends $%.4f$~ms outside its $\\pm 0.25$~ms bar with them and $%.4f$~ms inside it "
                "without them" % (-0.25 - low("all"), low("unpaused") + 0.25))


def test_nothing_here_is_offered_as_a_verdict(s1610, s1611):
    assert "changes none of them" in s1610 and "no verdict is changed" in s1611
    assert "are the ones reported" in s1611
    for word in (r"\bstamps?\b", r"\bstamper", r"\binstrument"):
        assert not re.search(word, s1610 + s1611), word
