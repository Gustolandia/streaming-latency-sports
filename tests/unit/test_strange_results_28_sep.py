"""The record of 28 September, the-strange-results-read-28-sep.md, read against its answers.

Every number the record gives is recomputed here from the files beside it in
strange-results-28-sep/ -- what m0_bursts.py, pause_census.py, cliff_shape.py and a9_decompose.py
wrote -- or from the final judging's own answers in judged-27-sep/. A record rewritten, or an
answer read again, cannot drift from the other unseen.
"""
import csv
import json
import math
import statistics
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
LAW = REPO / "docs" / "results" / "law"
HERE = LAW / "strange-results-28-sep"
JUDGED = LAW / "judged-27-sep" / "all"


def _record():
    return " ".join((LAW / "the-strange-results-read-28-sep.md").read_text(
        encoding="utf-8").split())


def _json(name, where=HERE):
    return json.loads((where / name).read_text(encoding="utf-8"))


def _csv(name):
    with open(HERE / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _f(value, places):
    return "%.*f" % (places, value)


def _has(*phrases):
    text = _record()
    for phrase in phrases:
        assert " ".join(phrase.split()) in text, phrase


def _span(values, places):
    return _f(min(values), places), _f(max(values), places)


# --- M0 ---------------------------------------------------------------------------------------------

def _growth(part, delay, rank):
    row = next(r for r in _csv("m0_by_rank.csv") if r["part"] == part
               and float(r["delay_ms"]) == delay and int(r["rank"]) == rank)
    return row


def test_the_bursts_and_each_ranks_growth():
    rows = [r for r in _csv("m0_by_rank.csv") if float(r["delay_ms"]) == 0.0]
    for part in ("kafka", "redis ack 1", "redis ack 200"):
        mine = [r for r in rows if r["part"] == part]
        total = sum(int(r["messages"]) for r in mine)
        leaders = sum(int(r["messages"]) for r in mine if r["rank"] == "0")
        assert (leaders, total) == (4020, 7490)
    _has("4,020 of 7,490 (53.7%) lead their burst", "the other 3,470 follow")
    labels = {"kafka": "Kafka (rule: 1, 1, 1, 1, 1)",
              "redis ack 200": "Redis, batches of 200 (rule: 1, 2, 2, 2, 2)",
              "redis ack 1": "Redis, one at a time (rule: 1, 3, 4, 5, 6)"}
    for part, label in labels.items():
        cells = [_f(float(_growth(part, 8.0, rank)["growth_per_ms"]), 3) for rank in range(5)]
        rules = [_growth(part, 8.0, rank)["rule"] for rank in range(5)]
        assert label.endswith("(rule: %s)" % ", ".join(rules))
        _has("| %s | %s |" % (label, " | ".join(cells)))


def test_the_slopes_measured_and_predicted():
    parts = _json("m0_bursts.json")
    names = {"kafka": "Kafka", "redis ack 1": "Redis, one at a time",
             "redis ack 200": "Redis, batches of 200"}
    for part, label in names.items():
        s = parts[part]["slope"]
        _has("| %s | %s | %s | %s | %s |" % (label, _f(s["all"], 3), _f(s["recorded"], 3),
                                               _f(s["unrecorded"], 3), _f(s["predicted"], 3)))
    frozen = _json("m0.json", JUDGED)["parts"]
    for part in names:
        assert frozen[part]["departure"]["slope"] == pytest.approx(parts[part]["slope"]["recorded"])
    _has("Redis's trip grows 1.18 and 1.31 times the delay")


def test_the_step_and_how_a_line_reads_it():
    parts = _json("m0_bursts.json")
    one, batches = parts["redis ack 1"], parts["redis ack 200"]
    assert one["step"]["share"] == pytest.approx(0.5367, abs=1e-4)
    assert 0.5 / one["step"]["share"] == pytest.approx(0.932, abs=5e-4)
    _has("(π₀ = 0.537)", "93.2nd percentile", "Q₀(0.932)",
         "M(0) = **%s ms** for Redis acknowledging each message and **%s ms** in batches"
         % (_f(one["step"]["step_ms"], 2), _f(batches["step"]["step_ms"], 2)))
    measured = one["median_trip_ms"]["measured"]
    _has("the median grows %s ms from 0 to 2 ms and %s ms from 2 to 8"
         % (_f(measured["2"] - measured["0"], 2), _f(measured["8"] - measured["2"], 2)))
    #: A step at every delay above zero, read by a straight line through 0, 2 and 8 ms.
    x = (0.0, 2.0, 8.0)
    mean = sum(x) / 3
    step = [0.0, 1.0, 1.0]
    cov = sum((a - mean) * (b - 2.0 / 3) for a, b in zip(x, step)) / 3
    var = sum((a - mean) ** 2 for a in x) / 3
    assert cov / var == pytest.approx(0.096, abs=5e-4)
    _has("a slope of 1 + 0.096 × the step")


def test_the_frozen_replay_pinned_on_the_leaders():
    parts = _json("m0_bursts.json")
    runs = parts["redis ack 1"]["replay"] + parts["redis ack 200"]["replay"]
    assert (len(parts["redis ack 1"]["replay"]), len(parts["redis ack 200"]["replay"])) == (12, 13)
    assert all(r["median_is_smallest"] for r in runs)
    low, high = _span([r["at_smallest"] * 100 for r in runs], 1)
    _has("In **all 12 and all 13 recorded Redis runs**",
         "shared by %s to %s%% of its messages" % (low, high))
    one = [r["others_median_ms"] for r in parts["redis ack 1"]["replay"] if r["delay_ms"] == 8.0]
    batches = [r["others_median_ms"] for r in parts["redis ack 200"]["replay"]
               if r["delay_ms"] == 8.0]
    assert {_f(v, 1) for v in batches} == {"17.1"}
    _has("medians of %s to %s ms (one at a time) and 17.1 (batches)" % _span(one, 1),
         "measured %s and %s" % (_f(float(_growth("redis ack 1", 8.0, 1)["median_trip_ms"]), 1),
                                 _f(float(_growth("redis ack 200", 8.0, 1)["median_trip_ms"]),
                                    1)))


def test_the_recordings_effect_on_the_median_and_the_tail():
    parts = _json("m0_bursts.json")
    redis = [parts[p]["recording"][d] for p in ("redis ack 1", "redis ack 200")
             for d in ("0", "2", "8")]
    _has("0.02 to 0.06 ms above the unrecorded runs' in the middle"
         if _span([r["leaders_median_ms"] for r in redis], 2) == ("0.02", "0.06") else "!",
         "and %s to %s ms above them at the 93.2nd percentile"
         % _span([r["leaders_quantile_ms"] for r in redis], 2))
    for part, words in (("redis ack 1", "one at a time"), ("redis ack 200", "in batches")):
        at8 = parts[part]["recording"]["8"]
        assert at8["median_ms"] == pytest.approx(at8["leaders_quantile_ms"])
        assert _f(at8["median_ms"], 3) in _record()
    _has("**+0.601 ms one at a time and +0.524 in batches, exactly the leaders' 93.2nd "
         "percentile's move**",
         "it moves %s to %s ms" % _span([parts[p]["recording"]["0"]["median_ms"]
                                          for p in ("redis ack 1", "redis ack 200")], 2),
         "Kafka's median moves %s to %s ms at every delay"
         % _span([parts["kafka"]["recording"][d]["median_ms"] for d in ("0", "2", "8")], 2))
    frozen = _json("m0.json", JUDGED)["parts"]["redis ack 1"]["recording_effect"]["by_setup"]
    assert _f(frozen["M0-redis-l75-ack1-d8000"]["trip_ms"], 2) == "0.65"
    _has("(0.65 ms at 8 ms, against the 0.02 the plan allows)")


# --- the pauses ------------------------------------------------------------------------------------

def test_the_episodes_by_kind():
    found = _json("pause_summary.json")
    kinds = found["kinds"]
    assert sum(k["episodes"] for k in kinds.values()) == 269
    assert (kinds["receiver"]["episodes"], kinds["broker"]["episodes"],
            kinds["both"]["episodes"]) == (152, 116, 1)
    assert kinds["broker"]["backends"] == ["kafka"]
    assert kinds["receiver"]["backends"] == ["kafka", "redis"]
    _has("There are **269**: 152 on the receiving side (Kafka and Redis), 116 at the broker (Kafka "
         "only), and one of %s s that was both" % _f(kinds["both"]["longest_ms"] / 1000, 1),
         "| Median, longest | %s s, %s s | %s s, %s s |" % (
             _f(kinds["receiver"]["median_ms"] / 1000, 1),
             _f(kinds["receiver"]["longest_ms"] / 1000, 1),
             _f(kinds["broker"]["median_ms"] / 1000, 2),
             _f(kinds["broker"]["longest_ms"] / 1000, 1)),
         "stopped too, in %d of %d episodes of a second or more" % (
             kinds["receiver"]["long_with_the_sampler_stopped"],
             kinds["receiver"]["long_with_the_sampler_timed"]))
    assert kinds["broker"]["long_with_the_sampler_stopped"] == 0
    _has("on time in all %d" % kinds["broker"]["long_with_the_sampler_timed"])
    lost, of = found["heartbeat_lost"]["3 s or more"]
    _has("in %d of %d episodes of 3 s or more, the broker could not heartbeat" % (lost, of))


def test_the_runs_the_pauses_fell_in():
    found = _json("pause_summary.json")
    paused, runs = found["runs_with_a_pause"], found["runs"]
    assert paused["matched"] + paused["matched-b"] == 221
    _has("On the x86 pairs 221 runs had one",
         "One pause in %s Arm runs against %d in %s and %d in %s on x86" % (
             "{:,}".format(runs["arm"]), paused["matched"], "{:,}".format(runs["matched"]),
             paused["matched-b"], "{:,}".format(runs["matched-b"])))
    arm = [r for r in _csv("pause_episodes.csv") if r["pair"] == "arm"]
    assert paused["arm"] == len(arm) == 1
    _has("had one episode of %s s in 2,159 runs" % _f(float(arm[0]["worst_ms"]) / 1000, 1))


def test_the_disk_and_the_sampler():
    found = _json("pause_summary.json")
    iowait = found["iowait"]
    _has("spent a median of **%s CPU-seconds** (first x86) and **%s** (second x86)"
         % (_f(iowait["matched"]["paused_median_s"], 2), _f(iowait["matched-b"]["paused_median_s"],
                                                             2)),
         "runs with no pause spent **%s**" % _f(iowait["matched"]["quiet_median_s"], 2))
    assert iowait["matched-b"]["quiet_median_s"] == iowait["matched"]["quiet_median_s"]
    line = found["iowait_on_pause"]
    _has("Over the %d paused runs the disk wait grows **%s CPU-seconds per second of pause** "
         "(correlation %s)" % (line["runs"], _f(line["slope"], 2), _f(line["correlation"], 2)))
    assert found["steal"]["most_s"] == 0.0
    _has("from any of the %s runs that record it" % "{:,}".format(found["steal"]["runs_read"]))
    reads = found["redis_receiver_inside_reads"]
    _has("In the %d Redis episodes of half a second or more" % reads["episodes"],
         "at most **%d%%**" % round(100 * reads["most_inside"]))
    longest = max(_csv("pause_episodes.csv"), key=lambda r: float(r["worst_ms"])
                  if r["kind"] == "receiver" else 0.0)
    assert longest["backend"] == "redis" and float(longest["inside_reads"]) < 0.01
    _has("The longest, %s s, began just after" % _f(float(longest["worst_ms"]) / 1000, 1))


def test_the_hour():
    hour = _json("pause_summary.json")["hour"]
    assert hour["runs"] == 68 and hour["runs"] / 4 == 17
    _has("in **%d of %d runs**, against the 17 an even spread gives (Rayleigh test p = %s, mean "
         "minute %s)" % (hour["by_quarter"][0], hour["runs"], _f(hour["rayleigh_p"], 3),
                         _f(hour["mean_minute"], 1)))


# --- the cliff -------------------------------------------------------------------------------------

def _levels(view, point):
    return [r for r in _csv("cliff_levels.csv") if r["view"] == view and r["point"] == point
            and r["of_p09s"]]


def test_the_rate_at_half_the_slice():
    rows = _levels("data", "p05s")
    ratios = [float(r["of_p09s"]) for r in rows]
    _has("**Measured, the rate at half the slice is %s to %s times the rate at 0.9 of it**"
         % _span(ratios, 2))
    at = dict(((r["block"], r["backend"], float(r["slice_ms"])), _f(float(r["of_p09s"]), 2))
              for r in rows)
    _has("Redis: %s at 2.25 ms, %s at 3 ms, %s at 4.5 ms and %s at 6 ms" % tuple(
        at[("A1", "redis", s)] for s in (2.25, 3.0, 4.5, 6.0)),
        "Kafka: %s at 4.5 ms and %s at 6 ms" % tuple(at[("A1", "kafka", s)] for s in (4.5, 6.0)),
        "Redis: %s, %s and %s at 1.5, 3 and 4.5 ms" % tuple(at[("A4", "redis", s)]
                                                           for s in (1.5, 3.0, 4.5)),
        "Kafka: %s at 4.5 ms" % at[("A4", "kafka", 4.5)])
    big = [float(r["of_p09s"]) for r in rows if float(r["slice_ms"]) >= 4.5]
    shape = [float(r["of_p09s"]) for r in _levels("residual", "p05s")
             if float(r["slice_ms"]) >= 4.5]
    _has("At 4.5 and 6 ms the data's rate at half the slice is %s to %s times" % _span(big, 2),
         "the rest-of-a-slice shape gives %s to %s" % _span(shape, 2))
    kafka = lambda view: [float(r["of_p09s"]) for r in _levels(view, "f15h")
                          if r["backend"] == "kafka"]
    assert max(kafka("plan")) == 0.0
    _has("Kafka keeps %s to %s of its plateau, where the shape keeps %s to %s"
         % (_span(kafka("data"), 2) + _span(kafka("residual"), 2)))


def test_the_shapes_through_the_frozen_judges():
    rows = _csv("cliff_judged.csv")

    def two(prediction, part, view):
        row = next(r for r in rows if r["prediction"] == prediction and r["part"] == part
                   and r["view"] == view)
        return "%s, %s" % (_f(float(row["free"]), 3), _f(float(row["fitted"]), 3))
    for prediction, part, label in (("P1", "kafka", "P1 slope, Kafka (first x86)"),
                                    ("P1", "redis", "P1 slope, Redis (first x86)"),
                                    ("P9", "kafka", "P9 slope, Kafka (Arm)"),
                                    ("P9", "redis", "P9 slope, Redis (Arm)")):
        _has("| %s | %s | %s | %s |" % (label, two(prediction, part, "data"),
                                          two(prediction, part, "plan"),
                                          two(prediction, part, "residual")))
    for view in ("data",):
        judged = _json("p1_a1.json", JUDGED)["by_part"]["kafka"]["by_summary"]["fitted"]["value"]
        assert _f(judged, 3) == two("P1", "kafka", view).split(", ")[1]
    misfit = _json("cliff_summary.json")["misfit"]
    assert misfit["plan"]["points"] == misfit["residual"]["points"] == 94
    _has("sits **%s** from the data on average over 94 points, against **%s** for the plan's "
         "formula (%s against %s past half the slice)" % (
             _f(misfit["residual"]["mean_gap"], 3), _f(misfit["plan"]["mean_gap"], 3),
             _f(misfit["residual"]["mean_gap_past_half"], 3),
             _f(misfit["plan"]["mean_gap_past_half"], 3)))


def test_the_fitted_starts():
    rows = _csv("cliff_widths.csv")

    def starts(view):
        return ", ".join(_f(float(r["fitted_start_ms"]), 2) for r in sorted(
            (r for r in rows if r["view"] == view and r["backend"] == "redis"
             and r["slice_ms"] == "3.0"), key=lambda r: float(r["tick_ms"])))
    data, plan, shape = starts("data"), starts("plan"), starts("residual")
    frozen = _json("p2d_a2_redis.json", JUDGED)["by_summary"]["fitted"]["start_ms"]
    assert [_f(frozen["[%s, 3.0]" % t], 2) for t in ("1.0", "4.0", "10.0")] == data.split(", ")
    _has("the data's fitted start is %s and %s ms" % tuple(data.rsplit(", ", 1)),
         "the plan's formula gives %s and %s" % tuple(plan.rsplit(", ", 1)),
         "the rest-of-a-slice shape %s and %s" % tuple(shape.rsplit(", ", 1)))


def test_p2_in_a_lawful_world_and_slice_by_slice():
    rows = _csv("cliff_judged.csv")

    def value(prediction, block, view, summary):
        row = next(r for r in rows if r["prediction"] == prediction and r["block"] == block
                   and r["view"] == view)
        return row[summary]
    assert value("P2", "A2 kafka", "plan", "free") == ""
    _has("a width ratio of %s (free) and %s (fitted) on Redis"
         % (_f(float(value("P2", "A2 redis", "plan", "free")), 2),
            _f(float(value("P2", "A2 redis", "plan", "fitted")), 2)),
         "P2b %s and %s, against 6 to 14" % (_f(float(value("P2b", "A2 redis", "plan", "free")), 2),
                                             _f(float(value("P2b", "A2 redis", "plan", "fitted")),
                                                2)),
         "its fitted one %s and %s" % (_f(float(value("P2", "A2 kafka", "plan", "fitted")), 2),
                                       _f(float(value("P2b", "A2 kafka", "plan", "fitted")), 1)))
    lines = _json("cliff_summary.json")["width_lines"]
    lawful = [lines["plan"][k][s] for k in ("redis, 1.5", "redis, 3", "kafka, 3")
              for s in ("free", "fitted")]
    _has("gives %s to %s for P2 and %s to %s for P2b" % (
        _span([x["ratio_250"] for x in lawful], 1) + _span([x["ratio_100"] for x in lawful], 1)))
    assert all(2.5 <= x["ratio_250"] <= 5.5 and 6 <= x["ratio_100"] <= 14 for x in lawful)

    def line(view, key, summary):
        x = lines[view][key][summary]
        return "%s + %s h" % (_f(x["intercept"], 2), _f(x["slope"], 2))
    labels = {"kafka, 1.5": "Kafka, 1.5 ms", "kafka, 3": "Kafka, 3 ms",
              "redis, 1.5": "Redis, 1.5 ms", "redis, 3": "Redis, 3 ms"}
    text = _record().replace("**", "")
    for key, label in labels.items():
        data = lines["data"][key]
        row = "| %s | %s | %s | %s, %s |" % (label, line("data", key, "free"),
                                             line("data", key, "fitted"),
                                             _f(data["free"]["ratio_100"], 2),
                                             _f(data["fitted"]["ratio_100"], 2))
        assert row.replace("+ -", "+ −").replace("| -", "| −") in text.replace("−", "−"), row
    _has("(Redis at 3 ms, fitted: %s, against the measured %s)"
         % (line("residual", "redis, 3", "fitted"), line("data", "redis, 3", "fitted")))


# --- A9 and P6 --------------------------------------------------------------------------------------

PARTS = {"arm, kafka": "Arm, Kafka", "arm, redis": "Arm, Redis",
         "matched, kafka": "first x86, Kafka", "matched, redis": "first x86, Redis",
         "matched-b, kafka": "second x86, Kafka", "matched-b, redis": "second x86, Redis"}


def test_a9_2_against_a9_2b():
    a9 = _json("a9_summary.json")["a9"]
    for key, label in PARTS.items():
        p = a9[key]
        assert p["identity_holds"] is True
        _has("| %s | %s | %d | %s | %s | %s |" % (
            label, _f(p["a9_2_over_a9_2b"], 3), round(p["waits_per_s"]),
            _f(p["mean_excess_ms"], 2), _f(p["rate_times_excess"], 3),
            _f(p["share_over_by_acks"], 3)))
    assert sum(p["decomposed"] for p in a9.values()) == 268
    _has("in all 268 runs it could be read on",
         "The thread waits %d to %d times a second" % (
             round(min(p["waits_per_s"] for p in a9.values())),
             round(max(p["waits_per_s"] for p in a9.values()))),
         "by only %s to %s ms on average" % _span([p["mean_excess_ms"] for p in a9.values()], 2),
         "comes to %s to %s" % _span([p["rate_times_excess"] for p in a9.values()], 2),
         "is %s to %s times as likely" % _span([p["share_over_by_acks"] for p in a9.values()], 2))
    frozen = _json("a9.json", JUDGED)["by_part"]
    ratios = [frozen[k]["median_ratio"] / frozen[k]["a9_2b"]["median_ratio"] for k in PARTS]
    assert min(ratios) > 0.06 and max(ratios) < 0.17, "six to ten times too few"


def test_a9s_recording_and_a6s():
    a9 = _json("a9_summary.json")
    effect = dict((k, _f(a9["a9"][k]["recorded_over_unrecorded"], 2)) for k in PARTS)
    _has("**%s, %s and %s for Kafka** on the Arm, first and second x86 pairs, and **%s, %s and %s "
         "for Redis**" % tuple(effect[k] for k in ("arm, kafka", "matched, kafka",
                                                   "matched-b, kafka", "arm, redis",
                                                   "matched, redis", "matched-b, redis")))
    a6 = sorted(_f(p["recorded_over_unrecorded"], 2) for p in a9["a6"].values())
    _has("read the same way: %s to %s" % (a6[0], a6[-1]))


def test_the_histogram_against_the_events():
    found = _json("a9_summary.json")
    rows = {"arm, kafka": "Arm, Kafka", "matched, kafka": "first x86, Kafka",
            "matched, redis": "first x86, Redis", "matched-b, kafka": "second x86, Kafka"}

    def n(x):
        return "{:,}".format(int(math.floor(x + 0.5)))
    for key, label in rows.items():
        a6, a9 = found["a6"][key], found["a9"][key]
        _has("| %s | %s, %s%% | %s, %s%% | %s, %s%% |" % (
            label, n(a6["waits"]), _f(100 * a6["over_1ms"], 1), n(a9["wake_waits"]),
            _f(100 * a9["wake_over_1ms"], 1), n(a9["preempt_waits"]),
            _f(100 * a9["preempt_over_1ms"], 1)))
    times = [found["a9"][k]["preempt_waits"] / found["a9"][k]["wake_waits"] for k in rows]
    _has("%s to %s times as many" % _span(times, 1))
    p6 = _json("p6_a6.json", JUDGED)["by_part"]
    kafka = [p6[k]["median_ratio"] for k in ("arm, kafka", "matched, kafka", "matched-b, kafka")]
    _has("P6's over-prediction on Kafka (%s to %s)" % _span(kafka, 1))


# --- P4 ------------------------------------------------------------------------------------------

def test_p4_where_it_makes_no_claim():
    plateaus = _json("cliff_summary.json")["plateaus"]["A7"]
    _has("**%s** for Kafka and **%s** for Redis; go-first takes both to **%s**" % (
        _f(plateaus["kafka"]["ordinary"], 4), _f(plateaus["redis"]["ordinary"], 4),
        _f(max(plateaus["kafka"]["go_first"], plateaus["redis"]["go_first"]), 4)))
    assert plateaus["redis"]["ordinary"] < 0.02 <= plateaus["kafka"]["ordinary"]
    _has("Redis's is %s%%" % _f(100 * plateaus["redis"]["ordinary"], 2))
    frozen = _json("p4_a7.json", JUDGED)
    assert frozen["confirmed"] is False and frozen["by_part"]["kafka"]["confirmed"] is True
    assert frozen["by_part"]["redis"]["by_summary"]["free"]["value"] is None
    assert "tested" not in frozen["by_part"]["redis"]


# --- what stays open ----------------------------------------------------------------------------------

def test_what_stays_open():
    moves = [_json("p3a_%s.json" % c, JUDGED)["by_summary"]["free"]["value"]
             for c in ("x86_1", "x86_2", "x86_3", "x86_3r", "arm")]
    _has("by %s ms" % " and ".join([", ".join(_f(m, 3).replace("-", "−") for m in moves[:-1]),
                                    _f(moves[-1], 3).replace("-", "−")]))
    assert all(m < 0 for m in moves)
    ratios = [_json(n, JUDGED)["by_summary"]["free"]["value"]
              for n in ("p8_a8_x86.json", "p8_a8_arm.json")]
    _has("Python's plateau is %s (x86) and %s (Arm) times Java's" % (_f(ratios[0], 2),
                                                                     _f(ratios[1], 2)))
    rows = _csv("cliff_judged.csv")
    kafka = [next(r for r in rows if r["prediction"] == "P1" and r["part"] == "kafka"
                  and r["view"] == v)["free"] for v in ("data", "plan", "residual")]
    _has("Its free slope, %s, is below what either shape above gives the same design (%s and %s)"
         % tuple(_f(float(v), 3) for v in kafka))
    a9 = _json("a9.json", JUDGED)["by_part"]
    shares, running = [], []
    for part in a9.values():
        for load in part["loads"].values():
            shares.append(load["a9_1"]["mostly_waiting"] / load["a9_1"]["negative_readings"])
            running.append(load["a9_1"]["mean_shares"]["running"])
    _has("The share is %d to %d%%" % (math.floor(100 * min(shares)), round(100 * max(shares))),
         "spent %d to %d%% of the interval running" % (round(100 * min(running)),
                                                     round(100 * max(running))))

    def by_load(part, load):
        return statistics.median(s["ratio"] for k, s in a9[part]["a9_2b"]["setups"].items()
                                 if "-l%d-" % load in k and s["ratio"] is not None)
    _has("(median ratio %s and %s) and comes to %s and %s at 88%%" % (
        _f(by_load("arm, kafka", 75), 2), _f(by_load("matched-b, kafka", 75), 2),
        _f(by_load("arm, kafka", 88), 2), _f(by_load("matched-b, kafka", 88), 2)))


# --- the expected ones -----------------------------------------------------------------------------

def test_the_expected_ones_and_their_formulas():
    p3b = []
    for c in ("x86_1", "x86_2", "x86_3", "x86_3r", "arm"):
        free = _json("p3b_%s.json" % c, JUDGED)["by_summary"]["free"]
        p3b.append("+%s (%s to %s)" % (_f(free["value"], 3), _f(free["interval"][0], 3),
                                       _f(free["interval"][1], 3)))
        assert free["interval"][0] > 0
    _has(", ".join(p3b))
    p1 = _json("p1_a1.json", JUDGED)["by_part"]
    redis = p1["redis"]["by_summary"]["free"]
    _has("Redis, first x86: %s (%s to %s), 5 of 5 slices in band" % (
        _f(redis["value"], 3), _f(redis["interval"][0], 3), _f(redis["interval"][1], 3)))
    assert all(p1["redis"]["by_summary"]["free"]["in_band"].values())
    assert all(p1["kafka"]["by_summary"]["free"]["in_band"].values())
    p9 = _json("p9_a4.json", JUDGED)["by_part"]
    _has("Arm: Kafka %s and Redis %s, every slice in band" % (
        _f(p9["kafka"]["by_summary"]["free"]["value"], 3),
        _f(p9["redis"]["by_summary"]["free"]["value"], 3)))
    slices = _json("p7_a5.json", JUDGED)["by_part"]["redis"]["by_summary"]["free"]["halfway_ms"]
    for cores, s in slices.items():
        assert float(list(s)[0]) == pytest.approx(0.7 * (1 + math.log2(int(cores))))
    assert all(_json("p7_a5.json", JUDGED)["by_part"]["redis"]["read_back"].values())
    _has("s(n) = s₀ × (1 + log₂ n), s₀ read off the kernel: 0.7 ms on the second x86 pair's, "
         "where A5 ran | 1.4, 2.1 and 2.8 ms read back at 2, 4 and 8 CPUs")
    p2c = _json("p2c_a2_redis.json", JUDGED)["by_summary"]["fitted"]
    _has("b = %s (%s to %s), a from −%s to %s" % (
        _f(p2c["value"], 3), _f(p2c["interval"][0], 3), _f(p2c["interval"][1], 3),
        _f(-p2c["intercept"][0], 2), _f(p2c["intercept"][1], 2)))
    for name, label in (("p8_a8_x86.json", "1,227 times (x86)"), ("p8_a8_arm.json",
                                                                  "184 times (Arm)")):
        fitted = _json(name, JUDGED)["by_summary"]["fitted"]
        assert fitted["java_cliff"] == 1.0 and fitted["draws"] == 2000
        assert "{:,}".format(round(fitted["java_priority_cut"])) in label
    _has("the cliff in 2,000 of 2,000 draws on both pairs; cut 1,227 times (x86) and 184 times "
         "(Arm)")
    a9 = _json("a9.json", JUDGED)["by_part"]
    for key, label in (("arm, redis", "Arm Redis"), ("matched, kafka", "first x86 Kafka"),
                       ("matched, redis", "first x86 Redis"),
                       ("matched-b, redis", "second x86 Redis")):
        b = a9[key]["a9_2b"]
        _has("%s %d of %d, %s%s" % (label, b["within_band"], b["setups_with_a_ratio"],
                                     "median " if key == "arm, redis" else "",
                                     _f(b["median_ratio"], 2)))
    waiting = dict((k, [_f(100 * l["a9_1"]["mostly_waiting"] / l["a9_1"]["negative_readings"], 1)
                        for _, l in sorted(a9[k]["loads"].items())])
                   for k in ("matched, redis", "matched-b, redis"))
    _has("%s%% and %s%% (first x86), %s%% and %s%% (second)" % tuple(
        waiting["matched, redis"] + waiting["matched-b, redis"]))
    m0 = _json("m0.json", JUDGED)["parts"]
    kafka = m0["kafka"]
    _has("%s (%s to %s) on the recorded runs, %s unrecorded" % (
        _f(kafka["departure"]["slope"], 3), _f(kafka["departure"]["interval"][0], 3),
        _f(kafka["departure"]["interval"][1], 3), _f(kafka["unrecorded_departure"]["slope"], 3)))
    ranks = [float(r["growth_per_ms"]) for r in _csv("m0_by_rank.csv")
             if r["part"] == "kafka" and r["delay_ms"] == "8.0"]
    _has("every rank %s to %s" % _span(ranks, 2))
    _has("%s (one at a time), %s (batches)" % (
        _f(m0["redis ack 1"]["M-H1"]["arrival_shift_ms"]["8"], 2),
        _f(m0["redis ack 200"]["M-H1"]["arrival_shift_ms"]["8"], 2)))
    floor = [float(r["rate"]) for r in _levels("data", "f2sh")] + [
        float(r["rate"]) for r in _csv("cliff_levels.csv") if r["view"] == "data"
        and r["point"] == "f2sh"]
    assert max(floor) <= 0.0001
    _has("0.0000 to 0.0001 at twice the slice plus a tick")
    lines = _json("cliff_summary.json")["width_lines"]["data"]

    def line(key, summary):
        x = lines[key][summary]
        return ("%s + %s h" % (_f(x["intercept"], 2), _f(x["slope"], 2))).replace("-", "−")
    _has("Kafka, fitted: %s; Redis: %s free, %s fitted" % (
        line("kafka, 1.5", "fitted"), line("redis, 1.5", "free"), line("redis, 1.5", "fitted")))


def test_the_record_names_its_programs_and_is_indexed():
    text = _record()
    for script in ("m0_bursts.py", "pause_census.py", "cliff_shape.py", "a9_decompose.py"):
        assert "(../../../scripts/%s)" % script in text
        assert (REPO / "scripts" / script).exists()
    index = (REPO / "docs" / "results" / "README.md").read_text(encoding="utf-8")
    assert "the-strange-results-read-28-sep.md" in index
    for placeholder in ("A9_TABLE", "A9_WAITS_PER_S", "A9_SHARE_RANGE", "A9_EXCESS_RANGE",
                        "A9_EFFECT", "A6_TEXT", "A6_EFFECT", "EXPECTED_TABLE"):
        assert placeholder not in text, "a placeholder left in the text"
