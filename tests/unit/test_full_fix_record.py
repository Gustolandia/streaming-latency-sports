"""F1's record, docs/results/full_fix/README.md, against the committed tables it reads from.

Every figure the record states is recomputed here from f1_runs.csv, f1_pilot_runs.csv and
f1_registry_runs.csv, and the verdicts file must be exactly what scripts/full_fix.py writes from
the run table. The frozen plan's pilot paragraph (freezes/39-experiment-plan) is held to the pilot's
table the same way. A sentence that drifts from its table fails here, not in a reader's hands.
"""
import collections
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
HERE = REPO / "docs" / "results" / "full_fix"
sys.path.insert(0, str(REPO / "scripts"))

import full_fix as ff  # noqa: E402


def table(name):
    with open(HERE / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def record():
    """The record's text with its line breaks folded, so a phrase may run across lines."""
    return " ".join((HERE / "README.md").read_text(encoding="utf-8").split())


RUNS = table("f1_runs.csv")
FOUND = ff.judge(RUNS)


def value(backend, load, priority, field):
    return ff.setup_value(RUNS, backend, load, priority, field)


def test_the_verdicts_are_what_the_code_writes_from_the_run_table():
    written = json.loads((HERE / "f1_verdicts.json").read_text(encoding="utf-8"))
    assert written == json.loads(json.dumps(dict(FOUND, pauses=ff.pauses(RUNS))))


def test_the_runs_and_where_they_ran():
    runs, text = table("f1_registry_runs.csv"), record()
    assert len(runs) == 60 and set(r["pair"] for r in runs) == {"matched"}
    assert collections.Counter(r["campaign"] for r in runs) == {"f1": 48, "f1_pilot2": 8,
                                                                "f1_pilot": 4}
    assert set((r["kernel"], r["online_cpus"], r["slice_in_force_ns"]) for r in runs) == {
        ("6.8.0-1065-azure", "8", "3000000")}
    judged = [r for r in runs if r["campaign"] == "f1"]
    assert all(r["verdict"] == "count" and r["attempt"] == "1" for r in judged)
    assert "every one passed the integrity rule at its first attempt" in text
    stopped = [r["run"] for r in runs if not r["verdict"]]
    assert stopped == ["law_f1_pilot_r001-F1-redis-l0-ord-a1"]
    assert "lists the stopped pilot run with no verdict" in text
    assert len(RUNS) == 48 and sorted(r["run"] for r in RUNS) == sorted(r["run"] for r in judged)


def test_every_prediction_held():
    assert {k: v["verdict"] for k, v in FOUND.items()} == dict.fromkeys(
        ("F-a", "F-b", "F-c", "F-d", "F-e"), "holds")
    text = record()
    for name in ("F-a", "F-b", "F-c", "F-d", "F-e"):
        assert "**%s held.**" % name in text
    assert "All five predictions held" in text


def _largest(field):
    return max(FOUND[field]["values"].items(), key=lambda kv: abs(kv[1][1] - kv[1][0]) / kv[1][0])


def test_the_wire_times_largest_moves():
    text = record()
    name, (base, other) = _largest("F-a")
    assert name == "redis, real-time priority: idle against load"
    assert "%.1f%%" % (100 * abs(other - base) / base) == "7.9%"
    assert "moved by at most 7.9%, against the 10% allowed" in text
    assert "from %.0f to %.0f µs" % (base, other) == "from 639 to 588 µs" and "from 639 to 588 µs" in text
    _, (base, other) = _largest("F-b")
    assert "%.1f%%" % (100 * abs(other - base) / base) == "7.2%"
    assert "moved by at most 7.2%, against 25%" in text


def test_nothing_below_zero_and_nothing_lost():
    text = record()
    assert sum(int(r["messages"]) for r in RUNS) == 239424 and "239,424 messages" in text
    assert all(r["wire_nonpositive"] == "0" and r["unmatched_tx"] == "0"
               and r["unmatched_rx"] == "0" and r["dropped"] == "0"
               and r["messages"] == r["stamped"] for r in RUNS)


def test_the_effect_is_there_and_is_the_hosts():
    text, d = record(), FOUND["F-d"]["values"]
    for broker, fold, lo, hi in (("kafka", "4.6", "1,801", "8,299"), ("redis", "4.3", "1,011",
                                                                      "4,396")):
        tail = d[broker]["D_p99"]
        assert "%.1f" % (tail[1] / tail[0]) == fold
        assert ("{:,.0f}".format(tail[0]), "{:,.0f}".format(tail[1])) == (lo, hi)
        assert "%s-fold on %s, from %s to %s µs" % (fold, broker.capitalize(), lo, hi) in text
    shares = ["%.1f%%" % (100 * abs(v["W_mean"][1] - v["W_mean"][0])
                          / (v["D_mean"][1] - v["D_mean"][0])) for v in (d["kafka"], d["redis"])]
    assert shares == ["0.2%", "5.1%"] and "moved by 0.2% and 5.1% of the rise" in text


def test_the_send_side():
    text, e = record(), FOUND["F-e"]["values"]
    assert "%.0f" % (e["kafka"][1] - e["kafka"][0]) == "626"
    assert "rose 626 µs on the mean, from 573 to 1,199 µs" in text
    assert ("%.0f" % e["kafka"][0], "{:,.0f}".format(e["kafka"][1])) == ("573", "1,199")
    assert "%.0f" % abs(e["redis"][1] - e["redis"][0]) == "4"
    assert ("%.0f" % e["redis"][0], "%.0f" % e["redis"][1]) == ("92", "88")
    assert "moved 4 µs, from 92 to 88 µs" in text


def test_no_pause_and_the_cards_description():
    text = record()
    assert ff.pauses(RUNS) == [] and "No message arrived more than 150 ms late" in text
    kernel = [value(b, load, p, "Kdelay_median") for b in ff.BACKENDS for load in (ff.IDLE, ff.BUSY)
              for p in (False, True)]
    assert ("%.0f" % min(kernel), "%.0f" % max(kernel)) == ("6", "20")
    assert "6 to 20 µs after the card did" in text
    for b in ff.BACKENDS:
        for p in (False, True):
            assert value(b, ff.IDLE, p, "Kdelay_median") > value(b, ff.BUSY, p, "Kdelay_median"), (
                "longest on an idle machine")
    fall = value("redis", ff.IDLE, True, "W_median") - value("redis", ff.BUSY, True, "W_median")
    card = value("redis", ff.IDLE, True, "Wcard_median") - value("redis", ff.BUSY, True,
                                                                  "Wcard_median")
    assert ("%.0f" % fall, "%.0f" % card) == ("50", "30")
    assert "Of the 50 µs by which" in text and "30 µs lay before the card" in text


def test_the_frozen_plans_pilot_paragraph_holds_to_the_pilots_table():
    """Freeze 39's D42-6 states the pilot's checks; the second attempt's table must bear them out."""
    plan = " ".join((REPO / "freezes" / "39-experiment-plan" / "experiment_plan.tex").read_text(
        encoding="utf-8").split())
    second = [r for r in table("f1_pilot_runs.csv") if r["run"].startswith("law_f1_pilot2_")]
    assert len(second) == 8, "all eight setups passed the integrity rule"
    idle = [float(r["load_measured"]) for r in second if r["load_pct"] == "0"]
    assert ("%.2f" % min(idle), "%.2f" % max(idle)) == ("0.45", "1.02")
    assert "measured load of 0.45 to 1.02\\%" in plan
    assert all(r["messages"] == r["stamped"] == "4988" and r["unmatched_tx"] == "0"
               and r["unmatched_rx"] == "0" and r["dropped"] == "0" for r in second)
    assert "each of the 4,988 messages" in plan
    assert all(r["wire_nonpositive"] == "0" and float(r["W_min"]) > 0 for r in second)
    assert all(float(r["Wcard_min"]) > 0 and float(r["Kdelay_min"]) > 0 for r in second), (
        "the card stamped every packet after it left the driver and before the kernel did")
    assert all(1400 <= float(r["card_window_ns"]) <= 1500 for r in second)
