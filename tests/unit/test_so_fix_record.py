"""F2's record, docs/results/so_fix/README.md, against the committed tables it reads from.

Every figure the record states is recomputed here from f2_runs.csv, f2_pilot_runs.csv and
f2_registry_runs.csv, and the verdicts file must be exactly what scripts/so_fix.py writes from the
run table. The frozen plan's pilot paragraph (freezes/40-experiment-plan) is held to the pilot's
table the same way. A sentence that drifts from its table fails here, not in a reader's hands.
"""
import collections
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
HERE = REPO / "docs" / "results" / "so_fix"
sys.path.insert(0, str(REPO / "scripts"))

import full_fix as ff  # noqa: E402
import so_fix as sf  # noqa: E402


def table(name):
    with open(HERE / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def record():
    """The record's text with its line breaks folded, so a phrase may run across lines."""
    return " ".join((HERE / "README.md").read_text(encoding="utf-8").split())


RUNS = table("f2_runs.csv")
FOUND = sf.judge(RUNS)


def value(backend, load, priority, field):
    return ff.setup_value(RUNS, backend, load, priority, field)


def test_the_verdicts_are_what_the_code_writes_from_the_run_table():
    written = json.loads((HERE / "f2_verdicts.json").read_text(encoding="utf-8"))
    assert written == json.loads(json.dumps(dict(FOUND, pauses=sf.pauses(RUNS))))


def test_the_runs_and_where_they_ran():
    runs, text = table("f2_registry_runs.csv"), record()
    assert len(runs) == 60 and set(r["pair"] for r in runs) == {"matched"}
    assert collections.Counter(r["campaign"] for r in runs) == {"f2": 48, "f2_pilot": 8,
                                                                "f2_smoke": 4}
    judged = [r for r in runs if r["campaign"] == "f2"]
    assert all(r["verdict"] == "count" and r["attempt"] == "1" and r["so_timestamps"] == "sched"
               for r in judged)
    assert "every one passed the integrity rule at its first attempt" in text
    unjudged = sorted(r["run"] for r in runs if not r["verdict"])
    assert unjudged == ["law_f2_smoke_r001-F2-kafka-l0-ord-a%d" % i for i in (1, 2, 3)]
    assert "lists the three failed Kafka attempts of the pilot's first step with no verdict" in text
    assert sorted(r["run"] for r in RUNS) == sorted(r["run"] for r in judged)


def test_every_prediction_held():
    assert {k: v["verdict"] for k, v in FOUND.items()} == dict.fromkeys(
        ("G-a", "G-b", "G-c", "G-d", "G-e"), "holds")
    text = record()
    for name in ("G-a", "G-b", "G-c", "G-d", "G-e"):
        assert "**%s held.**" % name in text
    assert "All five predictions held" in text


def test_the_two_instruments_agree():
    text = record()
    medians = [m for m, _ in FOUND["G-a"]["values"].values()]
    tails = [t for _, t in FOUND["G-a"]["values"].values()]
    assert ("%.1f" % min(medians), "%.1f" % max(medians), "%.1f" % max(tails)) == (
        "2.4", "3.0", "5.9")
    assert "was 2.4 to 3.0 µs, against the 20 µs allowed" in text
    assert "at most 5.9 µs, against 100 µs" in text
    lowest = min(float(r["rx_same_share"]) for r in RUNS)
    assert 0.984 <= lowest < 0.985 and "98.4% or more of each run's messages" in text
    lead = [float(r["tx_diff_median"]) for r in RUNS]
    assert ("%.1f" % -max(lead), "%.1f" % -min(lead)) == ("2.3", "3.2")
    assert "came 2.3 to 3.2 µs before the capture's" in text


def _largest(name):
    return max(FOUND[name]["values"].items(), key=lambda kv: abs(kv[1][1] - kv[1][0]) / kv[1][0])


def test_the_sockets_latency_held_still():
    text = record()
    name, (base, other) = _largest("G-b")
    assert name == "kafka, 0% load: normal against real-time"
    assert "%.1f%%" % (100 * abs(other - base) / base) == "7.8%"
    assert ("%.0f" % base, "%.0f" % other) == ("814", "750")
    assert "moved by at most 7.8%, against 10%: on Kafka with no background load, from 814 µs" \
           in text
    _, (base, other) = _largest("G-c")
    assert "%.1f%%" % (100 * abs(other - base) / base) == "12.2%"
    assert "moved by at most 12.2%, against 25%" in text


def test_nothing_below_zero_and_nothing_missing():
    text = record()
    assert sum(int(r["so_messages"]) for r in RUNS) == 239424 and "239,424 messages" in text
    assert all(r["so_nonpositive"] == "0" and r["so_missing_tx"] == "0"
               and r["so_missing_rx"] == "0" and r["dropped"] == "0" for r in RUNS)


def test_the_effect_is_there_and_is_the_clients():
    text, effect = record(), FOUND["G-e"]["values"]
    for broker, fold, lo, hi in (("kafka", "4.2", "1,977", "8,371"),
                                 ("redis", "4.7", "981", "4,579")):
        tail = effect[broker]["D_p99"]
        assert "%.1f" % (tail[1] / tail[0]) == fold
        assert ("{:,.0f}".format(tail[0]), "{:,.0f}".format(tail[1])) == (lo, hi)
        assert "%s-fold on %s, from %s to %s µs" % (fold, broker.capitalize(), lo, hi) in text
    shares = ["%.1f%%" % (100 * abs(v["Wso_mean"][1] - v["Wso_mean"][0])
                          / (v["D_mean"][1] - v["D_mean"][0]))
              for v in (effect["kafka"], effect["redis"])]
    assert shares == ["5.1%", "0.2%"] and "moved by 5.1% and 0.2% of the rise" in text


def test_the_pauses_are_kafkas_and_outside_the_client():
    held = sf.pauses(RUNS)
    assert len(held) == 3 and all("-F2-kafka-" in run for run, *_ in held)
    assert all(in_d == in_w for _, _, in_d, in_w, _ in held), "held in D and W_so alike"
    assert "In three Kafka runs a pause held messages more than 150 ms" in record()


def test_the_frozen_plans_pilot_paragraph_holds_to_the_pilots_table():
    """Freeze 40's D43-6 states the pilot's checks; the second step's table must bear them out."""
    plan = " ".join((REPO / "freezes" / "40-experiment-plan" / "experiment_plan.tex").read_text(
        encoding="utf-8").split())
    pilot = table("f2_pilot_runs.csv")
    assert len(pilot) == 8, "all eight setups passed the integrity rule"
    idle = [float(r["load_measured"]) for r in pilot if r["load_pct"] == "0"]
    assert ("%.2f" % min(idle), "%.2f" % max(idle)) == ("0.52", "1.28")
    assert "measured load of 0.52 to 1.28\\%" in plan
    assert all(r["messages"] == r["stamped"] == r["so_messages"] == "4988"
               and r["so_missing_tx"] == r["so_missing_rx"] == r["dropped"] == "0"
               and r["so_nonpositive"] == "0" for r in pilot)
    assert "each of the 4,988 messages" in plan
