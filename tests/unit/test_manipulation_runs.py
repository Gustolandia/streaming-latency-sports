"""Tests for scripts/manipulation_runs.py - 100% branch coverage.

The three manipulations and the traced pairs are the paper's causal evidence, and their
intervals treated messages as independent while the supplement's own runs test says values
below zero cluster within a run. The script replaces those intervals with ones that resample
whole runs, on both brokers, so these tests hold the two places it could go wrong:

  the counts   `extract` must take the runs the existing analyses pooled, count a negative span
               the way they did, and write nothing unless the Kafka halves sum to the committed
               cell totals and every run of either broker carries the counts span_run_level.csv
               gives it. It is tested on a small run tree built in a temporary folder with the
               real layout and column names (copied from concurrency_n5_20260725_072848_kafka_
               feed1_rep1), because CI has no archive; and the committed file is checked against
               both committed records directly.
  the intervals  the bootstrap's handling of resamples with no value below zero, which decides
               whether a factor's interval has an upper end at all, and the pooling of two
               brokers, which must resample each broker's runs within that broker. Both are
               pinned on cases worked by hand, two of them with every resample scripted.
"""
import csv
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import manipulation_runs as mr  # noqa: E402

# --- a run tree shaped like the archive's ---------------------------------------------------

#: The three tables of a real run, column for column, and span_run_level.csv's header.
PRODUCER = ["run_id", "backend", "topic", "event_id", "match_id", "t_sim_seconds",
            "t_emit_offset_s", "t_prod_sched_ns", "t_prod_send_ns", "t_broker_ack_ns"]
CONSUMER_EVENTS = ["run_id", "backend", "topic", "partition", "offset", "t_consume_ns",
                   "event_id", "match_id", "t_sim_seconds", "t_emit_offset_s",
                   "t_emit_planned_ns", "s3_uid", "s3_rev", "s3_is_correction"]
CONSUMER = ["run_id", "backend", "topic", "event_id", "match_id", "t_sim_seconds",
            "t_cons_recv_ns", "t_output_ns"]
SPAN = ["run_id", "condition", "gate", "n_events", "neg_ack", "ms_deleted", "over_0.1",
        "over_0.25", "over_0.5", "over_1"]

#: Every other cell holds these runs: Kafka 4 events with 1 negative, Redis 3 with 1.
KAFKA_RUNS = [[-0.2, 0.3], [0.1, 0.2]]
REDIS_RUNS = [[0.1, -0.3], [0.4]]


def _world():
    """(result, campaign, folder, cell, arm, run-id timestamp, Kafka runs, Redis runs, has a
    cell folder), each run the spans of S in ms. A span of exactly zero is not negative."""
    w = [("priority", "E-A5", "ea5", "l75_base", "normal", "n5_20260725_072848",
          [[0.6, -0.3, 1.2], [-0.1, -2.0, 0.4, 0.0]],     # Kafka 7 events, 3 negative
          [[-0.5, 0.2], [0.3]], True),                     # Redis 3 events, 1 negative
         ("priority", "E-A5", "ea5", "l75_rt", "real-time", "n5_20260725_074637",
          [[0.5, -0.05], [0.0, 0.9, 1.1]],                 # Kafka 5 events, 1 negative
          [[0.4, -0.2], [-0.1]], True)]                    # Redis 3 events, 2 negative
    for result, campaign, folder, cell, arm, stamp in (
            ("placement", "E-A6", "ea6", "k6_conc", "concentrated", "n5_20260725_095336"),
            ("placement", "E-A6", "ea6", "k6_spread", "spread", "n5_20260725_101125"),
            ("placement", "E-A6b", "ea6b", "k6_conc", "concentrated", "n5_20260725_233510"),
            ("placement", "E-A6b", "ea6b", "k6_spread", "spread", "n5_20260725_235300"),
            ("path", "E-A10", "ea10", "pad0", "0", "n5_20260725_194347"),
            ("path", "E-A10", "ea10", "pad262144", "262144", "n5_20260725_203717"),
            ("path", "E-A10b", "ea10b", "pad0", "0", "n5_20260726_004701"),
            ("path", "E-A10b", "ea10b", "pad262144", "262144", "n5_20260726_014032"),
            ("ladder", "E-A3", "ea3", "bg0", "idle", "n5_20260724_114658"),
            ("ladder", "E-A3", "ea3", "bg7", "knee", "n5_20260724_131548")):
        w.append((result, campaign, folder, cell, arm, stamp, KAFKA_RUNS, REDIS_RUNS, True))
    # The traced cells are named by timestamp; the committed tree keeps no folder that would.
    for campaign, folder, cell, arm, stamp, _parts in mr.TRACE_CELLS:
        w.append(("trace", campaign, folder, cell, arm, stamp, KAFKA_RUNS, REDIS_RUNS, False))
    return w


WORLD = _world()
T0 = 1784964531484051161           # the first producer stamp of the run the columns come from


def _write(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(fields)
        w.writerows(rows)


def _run_id(stamp, backend, i):
    return "concurrency_%s_%s_feed%d_rep1" % (stamp, backend, i)


def write_run(runs, run_id, spans, backend="kafka", events_table=True, matched=True):
    """One run directory: producer, consumer_events, consumer and meta, as a driver leaves it."""
    folder = runs / run_id
    topic = "sb-events-n5-%s" % "-".join(run_id.split("_")[-2:])
    prod, events, cons = [], [], []
    for i, s in enumerate(spans):
        eid = "%08x-f177-49a8-9b19-%012x" % (i + 1, i + 1)
        sched = T0 + i * 1_000_000_000
        send, ack = sched + 253_156, sched + 108_549_430
        got = ack + int(round(s * 1e6))
        prod.append([run_id, backend, topic, eid, 3895052, 0, 0.0, sched, send, ack])
        seen = eid if matched else "never-produced-%d" % i
        events.append([run_id, backend, topic, 0, 12931 + i, got, seen, 3895052, 0, 0.0, sched,
                       "3895052:%s" % seen, 1, False])
        cons.append([run_id, backend, topic, seen, 3895052, 0, got, got + 381])
    _write(folder / "producer.csv", PRODUCER, prod)
    if events_table:
        _write(folder / "consumer_events.csv", CONSUMER_EVENTS, events)
    _write(folder / "consumer.csv", CONSUMER, cons)
    (folder / "meta.json").write_text(json.dumps({"backend": backend, "run_id": run_id,
                                                  "topic": topic}), encoding="utf-8")


def write_cell(depth, folder, cell, stamp):
    """A condition directory: its concurrency subdirectory names the runs by timestamp."""
    where = depth / folder / cell
    sub = where / ("concurrency_concurrency_%s" % stamp)
    sub.mkdir(parents=True)
    (sub / ("concurrency_%s_summary.json" % stamp)).write_text(
        json.dumps({"concurrency": 5, "reps": 5}), encoding="utf-8")
    _write(where / "condition.csv", ["tag", "n_feeds", "reps", "max_t_sim"], [[cell, 5, 5, 180]])
    _write(where / "utilisation.csv", ["t_wall", "rho", "loadavg"],
           [[1784964528.754272, 0.75, 1.35], [1784964529.2582395, 0.76, 1.35]])


def _counts(spans):
    return sum(len(s) for s in spans), sum(1 for s in spans for t in s if t < 0)


def write_span(path, world=WORLD, extra=(), altered=None):
    """span_run_level.csv as span_by_condition writes it, for every run the world counts."""
    rows = []
    for _r, _c, _f, cell, _a, stamp, kafka, redis, _has in world:
        for backend, runs in (("kafka", kafka), ("redis", redis)):
            for i, spans in enumerate(runs, 1):
                n, k = _counts([spans])
                rid = _run_id(stamp, backend, i)
                if rid == altered:
                    k += 1
                rows.append([rid, "%s_n5_feed%d" % (backend, i), "fail", n, k, 0, n, n, n, k])
    rows += [list(e) for e in extra]
    _write(path, SPAN, rows)


def write_model(model, world=WORLD, bump=None, runs_off=0):
    """The committed totals the analyses would have written for the Kafka halves of `world`.

    `bump` adds one negative to that cell's committed count; `runs_off` changes every run count
    a committed file records. A confounded pair whose cells do not exist is listed too: it must
    never be walked. The pooled knee file names bg0 in a second campaign, with other counts.
    """
    totals = {(c, cell): (_counts(kafka), len(kafka)) for _, c, _, cell, _, _, kafka, _, _
              in world}

    def k(campaign, cell):
        (n, neg), runs = totals[(campaign, cell)]
        return neg + (1 if bump == (campaign, cell) else 0), n, runs + runs_off

    kb, nb, _ = k("E-A5", "l75_base")
    kr, nr, _ = k("E-A5", "l75_rt")
    head = ["level", "rho_base", "rho_rt", "inv_base", "inv_rt", "ratio", "disjoint",
            "n_base", "n_rt", "confounded"]
    _write(model / "stamping_priority.csv", head,
           [["l75", 0.75312, 0.7525, kb / nb, kr / nr, (kr / nr) / (kb / nb), True, nb, nr,
             False],
            ["l88", 0.88, 0.95, 0.3, 0.01, 0.03, True, 2985, 2985, True]])
    for name in ("stamping_priority_ea5b.csv", "stamping_priority_ea7.csv"):
        _write(model / name, head, [])
    knee = ["phase", "condition", "rho", "inversion_rate", "n_inversions", "n_events", "n_runs"]
    for campaign, folder in (("E-A6", "ea6"), ("E-A6b", "ea6b")):
        rows = [[folder, "k5_conc", 0.6284, 0.02, 60, 2985, 25]]
        for cell in ("k6_conc", "k6_spread"):
            neg, n, runs = k(campaign, cell)
            rows.append([folder, cell, 0.7531, neg / n, neg, n, runs])
        _write(model / folder / "knee_resolution.csv", knee, rows)
    rows = [["ea_sat", "bg0", 0.0025, 0.00335, 6, 1791, 15]]
    for cell in ("bg0", "bg7"):
        neg, n, runs = k("E-A3", cell)
        rows.append(["ea3", cell, 0.5, neg / n, neg, n, runs])
    _write(model / "knee_resolution.csv", knee, rows)
    for campaign, parts in (("E-A10", ("ttrue_sweep.csv",)),
                            ("E-A10b", ("ea10b", "ttrue_sweep.csv"))):
        rows = []
        for pad in (0, 262144):
            neg, n, _ = k(campaign, "pad%d" % pad)
            rows.append([pad, 0.88, 0.7, neg / n, 0.0, 1.0, n])
        _write(model.joinpath(*parts), ["pad_bytes", "rho", "transport_ms", "inversion", "ci_lo",
                                        "ci_hi", "n_events"], rows)
    runq = ["tag", "arm", "rho", "inversion", "n_events", "p_tail", "estimator", "traced_events"]
    for parts, campaign, cells_ in ((("runq_tail.csv",), "E-A9", ("l88_base", "l88_rt")),
                                    (("ea9b_l75", "runq_tail.csv"), "E-A9b",
                                     ("l75_base", "l75_rt")),
                                    (("ea9b_l88", "runq_tail.csv"), "E-A9b",
                                     ("l88_base", "l88_rt"))):
        rows = []
        for cell in cells_:
            neg, n, _ = k(campaign, cell)
            rows.append([cell, cell.split("_")[1], 0.88, neg / n, n, 0.18, "exact counter", 5])
        _write(model.joinpath(*parts), runq, rows)
    rows = []
    for cell in ("l88_base", "l88_rt"):
        neg, n, runs = k("E-A9-untraced", cell)
        rows.append([cell, 0.88, neg / n, neg, n, runs])
    _write(model / "ea9_notrace" / "untraced_control.csv",
           ["condition", "rho", "inversion_rate", "n_inversions", "n_events", "n_runs"], rows)


@pytest.fixture
def world(tmp_path):
    depth, runs, model = tmp_path / "depth", tmp_path / "runs", tmp_path / "model"
    for _result, _campaign, folder, cell, _arm, stamp, kafka, redis, has_folder in WORLD:
        if has_folder:
            write_cell(depth, folder, cell, stamp)
        for backend, spans in (("kafka", kafka), ("redis", redis)):
            for i, s in enumerate(spans, 1):
                write_run(runs, _run_id(stamp, backend, i), s, backend)
    # Under E-A6's concentrated cell, two Kafka runs its analyses never pooled: one that never
    # wrote its consumer_events table, and one whose deliveries match nothing it produced.
    stamp = "n5_20260725_095336"
    write_run(runs, _run_id(stamp, "kafka", 3), [-5.0], events_table=False)
    write_run(runs, _run_id(stamp, "kafka", 4), [-5.0], matched=False)
    write_model(model)
    write_span(tmp_path / "span_run_level.csv")
    return {"depth": depth, "runs": runs, "model": model, "span": tmp_path / "span_run_level.csv",
            "out": tmp_path / "counts.csv"}


def _extract(w):
    return mr.main(["extract", "--depth", str(w["depth"]), "--runs", str(w["runs"]),
                    "--model", str(w["model"]), "--span", str(w["span"]), "--out", str(w["out"])])


def _rows(w):
    return mr.extract(str(w["depth"]), str(w["runs"]), str(w["model"]))


class TestExtract:

    def test_every_cell_of_both_brokers_is_written_one_row_per_run(self, world, capsys):
        assert _extract(world) == 0
        assert "every Kafka half reproduces" in capsys.readouterr().out
        with open(world["out"], newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert list(rows[0]) == mr.FIELDS
        assert len(rows) == 80, "two runs of each broker in each of twenty cells"
        # E-A9b has an l75_base too, among the traced cells: a cell is named with its campaign.
        base = [(r["backend"], r["run"], r["run_events"], r["run_negatives"]) for r in rows
                if (r["campaign"], r["cell"]) == ("E-A5", "l75_base")]
        assert base == [
            ("kafka", "concurrency_n5_20260725_072848_kafka_feed1_rep1", "3", "1"),
            ("kafka", "concurrency_n5_20260725_072848_kafka_feed2_rep1", "4", "2"),
            ("redis", "concurrency_n5_20260725_072848_redis_feed1_rep1", "2", "1"),
            ("redis", "concurrency_n5_20260725_072848_redis_feed2_rep1", "1", "0")]
        arms = {(r["campaign"], r["cell"]): r["arm"] for r in rows}
        assert arms[("E-A5", "l75_rt")] == "real-time"
        assert arms[("E-A6", "k6_conc")] == "concentrated"
        assert arms[("E-A10b", "pad262144")] == "262144"
        assert arms[("E-A9-untraced", "l88_rt")] == "real-time"
        assert arms[("E-A3", "bg7")] == "knee"
        assert mr.check(mr.read_runs(str(world["out"])), str(world["model"]),
                        str(world["span"])) == []

    def test_only_the_runs_the_analyses_pooled_are_counted(self, world):
        """A run with no consumer_events table and a run that matched nothing both sit under
        the cell's timestamp; neither is a row, and the other broker's runs are."""
        conc = [r["run"] for r in _rows(world) if (r["campaign"], r["cell"]) == ("E-A6", "k6_conc")]
        assert conc == ["concurrency_n5_20260725_095336_kafka_feed1_rep1",
                        "concurrency_n5_20260725_095336_kafka_feed2_rep1",
                        "concurrency_n5_20260725_095336_redis_feed1_rep1",
                        "concurrency_n5_20260725_095336_redis_feed2_rep1"]

    def test_a_traced_cell_is_found_by_its_timestamp_without_a_folder(self, world):
        assert not (world["depth"] / "ea9").exists()
        traced = [r["run"] for r in _rows(world) if (r["campaign"], r["cell"]) == ("E-A9", "l88_rt")]
        assert traced[0] == "concurrency_n5_20260725_211526_kafka_feed1_rep1"
        assert len(traced) == 4

    def test_a_span_of_exactly_zero_is_not_negative(self, world):
        got = mr.run_counts(str(world["depth"] / "ea5" / "l75_rt"), str(world["runs"]))
        assert [(n, k) for _, n, k in got] == [(2, 1), (3, 0)]

    def test_a_cell_with_no_concurrency_subdirectory_has_no_runs(self, world, tmp_path):
        (tmp_path / "bare").mkdir()
        assert mr.run_counts(str(tmp_path / "bare"), str(world["runs"])) == []

    def test_a_confounded_pair_is_never_walked(self, world):
        found = {(c, cell) for _, c, _, cell, _, _, _ in mr.cells(str(world["model"]))}
        assert ("E-A5", "l88_base") not in found and ("E-A5", "l75_rt") in found
        assert len(found) == 20

    def test_the_pooled_knee_file_is_read_for_the_campaign_asked(self, world):
        """bg0 is a cell of E-A3 and of ea_sat in one file; the phase column decides."""
        got = mr._counted(str(world["model"]), ("knee_resolution.csv",), "ea3", "bg0")
        assert got == {"n_events": 4, "n_negative": 1, "n_runs": 2}
        with pytest.raises(KeyError, match="no row for ea3/bg5"):
            mr._counted(str(world["model"]), ("knee_resolution.csv",), "ea3", "bg5")

    def test_a_kafka_half_that_does_not_sum_to_its_total_stops_the_write(self, world, capsys):
        write_model(world["model"], bump=("E-A9", "l88_base"))
        assert _extract(world) == 1
        out = capsys.readouterr().out
        assert "nothing written" in out
        assert ("E-A9 ea9/l88_base (normal): Kafka 2 runs, 4 events, 1 with S < 0; the "
                "committed analysis has ? runs, 4 events, 2 with S < 0") in out
        assert not world["out"].exists()

    def test_a_run_count_that_differs_is_named(self, world, capsys):
        write_model(world["model"], runs_off=1)
        assert _extract(world) == 1
        assert "the committed analysis has 3 runs" in capsys.readouterr().out

    def test_a_run_whose_counts_span_run_level_does_not_hold_is_named(self, world):
        rid = _run_id("n5_20260725_074637", "redis", 1)
        write_span(world["span"], altered=rid)
        rows = _rows(world)
        assert mr.check(rows, str(world["model"]), str(world["span"])) == [
            "%s: 2 events, 1 with S < 0; span_run_level.csv has (2, 2)" % rid]
        stray = dict(rows[0], run="concurrency_n5_20990101_000000_kafka_feed1_rep1")
        problems = mr.check([stray], str(world["model"]), str(world["span"]))
        assert "%s: 3 events, 1 with S < 0; span_run_level.csv has no such run" % stray["run"] \
            in problems

    def test_a_run_left_out_of_a_broker_is_named(self, world):
        extra = [(_run_id("n5_20260725_074637", "redis", 9), "redis_n5_feed9", "pass",
                  2, 0, 0, 2, 2, 2, 0)]
        write_span(world["span"], extra=extra)
        problems = mr.check(_rows(world), str(world["model"]), str(world["span"]))
        assert problems == ["E-A5 ea5/l75_rt (real-time): 2 redis runs; span_run_level.csv "
                            "holds 3 under concurrency_n5_20260725_074637_redis_"]

    def test_a_cell_drawn_from_two_timestamps_is_named(self, world):
        rows = _rows(world)
        moved = [dict(r, run=r["run"].replace("072848", "999999"))
                 if r["cell"] == "l75_base" and r["backend"] == "redis" else r for r in rows]
        problems = mr.check(moved, str(world["model"]), str(world["span"]))
        assert "E-A5 ea5/l75_base (normal): runs from 2 timestamps, not one" in problems

    def test_a_row_behind_no_result_is_named(self, world):
        rows = _rows(world)
        stray = dict(rows[0], campaign="E-A9c")
        problems = mr.check(rows + [stray], str(world["model"]), str(world["span"]))
        assert problems == ["priority E-A9c ea5/l75_base (normal): in the run file, behind none "
                            "of the results"]

    def test_without_the_archive_it_says_so(self, world, capsys):
        world["depth"] = world["depth"] / "absent"
        assert _extract(world) == 1
        assert "missing archive directory" in capsys.readouterr().out

    def test_without_the_committed_records_it_says_so(self, world, tmp_path, capsys):
        world["model"] = tmp_path / "no-model"
        assert _extract(world) == 1
        assert "cannot read the committed records" in capsys.readouterr().out


# --- the bootstrap ---------------------------------------------------------------------------

class Scripted:
    """A stream whose every resample is written out: `compare` asks for each stratum of the
    upper arm and then of the lower arm, once per draw."""

    def __init__(self, picks):
        self.picks = iter(picks)

    def choices(self, population, k):
        got = next(self.picks)
        assert len(got) == k
        return got


class TestCompare:

    def test_one_run_per_arm_gives_the_exact_factor_and_a_point_interval(self):
        d = mr.compare([[(10, 5)]], [[(10, 1)]], "one", draws=400)
        assert d["factor"] == pytest.approx(5.0)
        assert d["factor_ci"] == pytest.approx((5.0, 5.0))
        assert d["top"]["ci"] == pytest.approx((0.5, 0.5))
        assert d["bottom"]["ci"] == pytest.approx((0.1, 0.1))
        assert d["top"]["run_rates"] == [0.5] and d["bottom"]["run_rates"] == [0.1]
        assert d["disjoint"] is True
        assert (d["unbounded_draws"], d["undefined_draws"], d["draws"]) == (0, 0, 400)

    def test_a_draw_with_both_arms_zero_widens_the_interval_at_both_ends(self, monkeypatch):
        """Four draws, scripted, at 50%: one draw left outside at each end.

        Factors 2, 6 and 4, and one draw where both arms drew no negative. Placed at zero for
        the lower end and unbounded for the upper, it gives [2, 6]. Dropped, or put at either
        end for both, it would give [4, 4]: an interval narrower than the draws allow.
        """
        a, c, z = (10, 2), (10, 6), (10, 0)
        b, y = (10, 1), (10, 0)
        picks = [[a, a, a], [b, b, b],          # 0.2 over 0.1 -> 2
                 [c, z, z], [b, y, y],          # 0.2 over 1/30 -> 6
                 [c, c, z], [b, b, b],          # 0.4 over 0.1 -> 4
                 [z, z, z], [y, y, y]]          # nothing over nothing
        monkeypatch.setattr(mr, "_stream", lambda name: Scripted(picks))
        d = mr.compare([[a, z, c]], [[b, y, (10, 3)]], "scripted", draws=4, conf=0.5)
        assert d["factor_ci"] == pytest.approx((2.0, 6.0))
        assert (d["unbounded_draws"], d["undefined_draws"]) == (0, 1)
        assert d["top"]["ci"] == pytest.approx((0.2, 0.2))
        assert d["bottom"]["ci"] == pytest.approx((1 / 30, 0.1))
        assert d["factor"] == pytest.approx((8 / 30) / (4 / 30))
        assert d["disjoint"] is True

    def test_draws_with_a_zero_lower_arm_leave_the_factor_unbounded(self, monkeypatch):
        a, z, b, y = (10, 2), (10, 0), (10, 1), (10, 0)
        picks = [[a, a], [b, b],                # 2
                 [a, a], [b, y],                # 4
                 [a, z], [y, y],                # unbounded
                 [a, a], [y, y]]                # unbounded
        monkeypatch.setattr(mr, "_stream", lambda name: Scripted(picks))
        d = mr.compare([[a, z]], [[b, y]], "scripted", draws=4, conf=0.5)
        # Factors 2 and 4 and two unbounded draws: [2, 4, inf, inf], one left out at each end.
        assert d["factor_ci"][0] == pytest.approx(4.0)
        assert math.isinf(d["factor_ci"][1])
        assert (d["unbounded_draws"], d["undefined_draws"]) == (2, 0)
        # Upper rates 0.2, 0.2, 0.1, 0.2 and lower 0.1, 0.05, 0, 0.
        assert d["top"]["ci"] == pytest.approx((0.2, 0.2))
        assert d["bottom"]["ci"] == pytest.approx((0.0, 0.05))
        assert d["disjoint"] is True

    def test_two_brokers_are_resampled_each_within_its_own_runs(self, monkeypatch):
        """Pooled, a resample draws Kafka's runs from Kafka's and Redis's from Redis's, so it
        always holds as many of each as the campaign ran: the pooled rate counts both."""
        k1, k2, r1 = (10, 0), (10, 2), (10, 4)
        picks = [[k1, k1], [r1], [(10, 1)], [(10, 1)],     # (0 + 4) / 30 over 2 / 20
                 [k2, k2], [r1], [(10, 1)], [(10, 1)]]     # (4 + 4) / 30 over 2 / 20
        monkeypatch.setattr(mr, "_stream", lambda name: Scripted(picks))
        d = mr.compare([[k1, k2], [r1]], [[(10, 1)], [(10, 1)]], "pooled", draws=2, conf=0.5)
        assert d["top"]["runs"] == 3 and d["top"]["rate"] == pytest.approx(6 / 30)
        assert d["top"]["ci"] == pytest.approx((4 / 30, 8 / 30))
        assert d["factor_ci"] == pytest.approx(((4 / 30) / 0.1, (8 / 30) / 0.1))

    def test_a_seeded_pooled_resample_never_loses_a_broker(self):
        """Redis's single run holds 4 of 10 in every resample, so no pooled rate can fall
        below 4/30, which drawing the three runs as one population would allow."""
        d = mr.compare([[(10, 0), (10, 2)], [(10, 4)]], [[(10, 1)]], "strata", draws=4000)
        assert d["top"]["ci"][0] >= 4 / 30 - 1e-12

    def test_the_unbounded_share_is_the_chance_a_resample_misses_every_negative_run(self):
        """One lower-arm run in twenty-five holds every negative, as at 60% load in E-A5b's
        real-time arm on Kafka: a resample of 25 misses it with probability (24/25)^25."""
        top = [[(100, 10)] * 25]
        bottom = [[(100, 5)] + [(100, 0)] * 24]
        d = mr.compare(top, bottom, "binomial", draws=20000)
        assert d["unbounded_draws"] / 20000 == pytest.approx((24 / 25) ** 25, abs=0.015)
        assert math.isinf(d["factor_ci"][1])
        assert d["bottom"]["ci"][0] == 0.0

    def test_an_arm_with_no_negative_run_gets_no_interval(self):
        d = mr.compare([[(10, 3), (10, 2)]], [[(10, 0), (10, 0)]], "zero-below", draws=200)
        assert d["bottom"]["ci"] is None and d["factor_ci"] is None and d["disjoint"] is None
        assert math.isinf(d["factor"]) and d["unbounded_draws"] == 200
        d = mr.compare([[(10, 0)]], [[(10, 1)]], "zero-above", draws=200)
        assert d["top"]["ci"] is None and d["factor"] == 0.0 and d["factor_ci"] is None
        d = mr.compare([[(10, 0)]], [[(10, 0)]], "both", draws=200)
        assert d["factor"] is None and d["undefined_draws"] == 200

    def test_an_arm_with_no_runs_is_refused(self):
        with pytest.raises(ValueError, match="both arms need runs"):
            mr.compare([], [[(10, 1)]], "empty")

    def test_each_comparison_draws_from_its_own_stream(self):
        top, bottom = [[(50, 9), (50, 2), (60, 14)]], [[(50, 1), (50, 0), (60, 3)]]
        first = mr.compare(top, bottom, "priority|E-A5|l75|kafka", draws=2000)
        assert mr.compare(top, bottom, "priority|E-A5|l75|kafka", draws=2000) == first
        assert mr.compare(top, bottom, "priority|E-A5|l75|redis", draws=2000)["factor_ci"] \
            != first["factor_ci"]

    def test_the_interval_leaves_the_same_number_of_draws_out_at_each_end(self):
        assert mr._tail(4000, 0.95) == 100
        assert mr._tail(20000, 0.95) == 500
        assert mr._tail(4, 0.5) == 1


# --- the results, from a file ------------------------------------------------------------------

def _runs_csv(tmp_path, rows, name="runs.csv"):
    path = tmp_path / name
    _write(path, mr.FIELDS, rows)
    return str(path)


def _r(result, campaign, cell, arm, counts, folder="ea5", backend="kafka"):
    return [[result, campaign, folder, cell, arm, backend,
             "%s_%s_%s_run%d" % (campaign, cell, backend, i), n, k]
            for i, (n, k) in enumerate(counts, 1)]


def _small(backend, fall):
    """Every result on one broker. `fall` gives the padding sweep's three counts per 200."""
    def r(result, campaign, cell, arm, counts, folder="ea5"):
        return _r(result, campaign, cell, arm, counts, folder, backend)

    rows = (r("priority", "E-A7", "l75_base", "normal", [(100, 20), (100, 10)])
            + r("priority", "E-A7", "l75_rt", "real-time", [(100, 1), (100, 0)])
            + r("priority", "E-A5", "l88_base", "normal", [(100, 30), (100, 30)])
            + r("priority", "E-A5", "l88_rt", "real-time", [(100, 3), (100, 0)])
            + r("priority", "E-A5b", "l60_base", "normal", [(100, 5), (100, 4)])
            + r("priority", "E-A5b", "l60_rt", "real-time", [(100, 0), (100, 0)])
            + r("placement", "E-A6", "k6_conc", "concentrated", [(100, 8), (100, 9)], "ea6")
            + r("placement", "E-A6", "k6_spread", "spread", [(100, 17), (100, 17)], "ea6")
            + r("ladder", "E-A3", "bg0", "idle", [(100, 1), (100, 0)], "ea3")
            + r("ladder", "E-A3", "bg7", "knee", [(100, 22), (100, 20)], "ea3")
            + r("trace", "E-A9", "l88_base", "normal", [(100, 23), (100, 24)], "ea9")
            + r("trace", "E-A9", "l88_rt", "real-time", [(100, 0), (100, 0)], "ea9"))
    for pad, k in zip(("0", "4096", "262144"), fall):
        rows += r("path", "E-A10", "pad%s" % pad, pad, [(100, k // 2), (100, k - k // 2)],
                  "ea10")
    return rows


#: Kafka's sweep peaks at 4096 B, so its highest rate is not at zero padding; Redis's falls
#: monotonically.
SMALL = _small("kafka", (42, 58, 11)) + _small("redis", (40, 30, 10))


class TestTheResults:

    def test_read_runs_gives_integer_counts(self, tmp_path):
        rows = mr.read_runs(_runs_csv(tmp_path, SMALL))
        assert rows[0]["run_events"] == 100 and rows[0]["run_negatives"] == 20

    def test_a_broker_that_is_not_one_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="backend must be kafka, redis or both"):
            mr.priority_intervals(_runs_csv(tmp_path, SMALL), backend="rabbit", draws=10)

    def test_pairs_are_matched_by_campaign_and_load_and_ordered_by_load(self, tmp_path):
        pairs = mr.priority_intervals(_runs_csv(tmp_path, SMALL), draws=500)
        assert [(p["campaign"], p["level"]) for p in pairs] == [
            ("E-A5b", "l60"), ("E-A7", "l75"), ("E-A5", "l88")]
        e_a7 = pairs[1]
        assert e_a7["normal"] is e_a7["top"] and e_a7["real-time"] is e_a7["bottom"]
        assert e_a7["backend"] == "kafka"
        assert e_a7["factor"] == pytest.approx((30 / 200) / (1 / 200))
        assert e_a7["normal"]["run_rates"] == [0.2, 0.1]

    def test_both_brokers_pool_their_runs(self, tmp_path):
        pairs = mr.priority_intervals(_runs_csv(tmp_path, SMALL), backend="both", draws=500)
        e_a7 = pairs[1]
        assert e_a7["normal"]["runs"] == 4 and e_a7["backend"] == "both"
        assert e_a7["normal"]["rate"] == pytest.approx(60 / 400)

    def test_pooling_from_the_file_keeps_each_broker_s_runs_apart(self, tmp_path):
        """Read from the file, the pooled normal arm is Kafka's two runs and Redis's one, and
        Redis's run holds 4 of 10 in every resample: no pooled rate can fall below 4/30."""
        rows = (_r("priority", "E-A5", "l75_base", "normal", [(10, 0), (10, 2)])
                + _r("priority", "E-A5", "l75_base", "normal", [(10, 4)], backend="redis")
                + _r("priority", "E-A5", "l75_rt", "real-time", [(10, 1)])
                + _r("priority", "E-A5", "l75_rt", "real-time", [(10, 1)], backend="redis"))
        pair = mr.priority_intervals(_runs_csv(tmp_path, rows), backend="both", draws=4000)[0]
        assert pair["normal"]["ci"][0] >= 4 / 30 - 1e-12

    def test_the_summary_spans_the_pairs_and_counts_the_unbounded(self, tmp_path):
        pairs = mr.priority_intervals(_runs_csv(tmp_path, SMALL), draws=500)
        s = mr.priority_summary(pairs)
        # E-A5b's real-time arm has no negative: an unbounded factor, no interval, and so no
        # verdict on disjointness, which keeps the conjunction false.
        assert s["pairs"] == 3 and math.isinf(s["factor_high"])
        assert s["factor_low"] == pytest.approx(20.0)
        assert s["all_disjoint"] is False
        assert s["unbounded"] == 2, "E-A7 and E-A5 each have a real-time arm one run holds"
        assert mr.priority_summary([]) == {"pairs": 0, "factor_low": None, "factor_high": None,
                                           "all_disjoint": False, "unbounded": 0}
        assert mr.priority_summary([dict(pairs[1], factor=None)])["factor_low"] is None

    def test_the_traced_pairs_take_the_priority_shape(self, tmp_path):
        traced = mr.trace_intervals(_runs_csv(tmp_path, SMALL), draws=500)
        assert [(p["campaign"], p["level"]) for p in traced] == [("E-A9", "l88")]
        assert math.isinf(traced[0]["factor"]) and traced[0]["real-time"]["ci"] is None
        pooled = mr.trace_intervals(_runs_csv(tmp_path, SMALL), backend="both", draws=500)
        assert pooled[0]["real-time"]["runs"] == 4

    def test_placement_is_the_spread_rate_over_the_concentrated(self, tmp_path):
        d = mr.placement_intervals(_runs_csv(tmp_path, SMALL), draws=500)["E-A6"]
        assert d["spread"] is d["top"] and d["concentrated"] is d["bottom"]
        assert d["factor"] == pytest.approx(34 / 17)

    def test_the_fall_is_the_highest_pooled_rate_over_the_lowest(self, tmp_path):
        """As payload_span defines it. Here the highest rate is not at zero padding, so a
        fall taken between the two ends of the sweep is a different number, which `ends`
        gives."""
        path = _runs_csv(tmp_path, SMALL)
        d = mr.path_intervals(path, draws=500)["E-A10"]
        assert (d["high"], d["low"]) == ("4096", "262144")
        assert d["factor"] == pytest.approx(58 / 11)
        e = mr.path_intervals(path, draws=500, ends=True)["E-A10"]
        assert (e["high"], e["low"]) == ("0", "262144")
        assert e["factor"] == pytest.approx(42 / 11)

    def test_a_sweep_of_one_level_has_no_fall(self, tmp_path):
        path = _runs_csv(tmp_path, _r("path", "E-A10", "pad0", "0", [(100, 20)], "ea10"))
        with pytest.raises(ValueError, match="needs two padding levels"):
            mr.path_intervals(path, draws=100)

    def test_the_ladder_grows_from_idle_to_the_knee(self, tmp_path):
        d = mr.ladder_intervals(_runs_csv(tmp_path, SMALL), draws=500)["E-A3"]
        assert d["knee"] is d["top"] and d["idle"] is d["bottom"]
        assert d["factor"] == pytest.approx(42.0)


class TestReport:

    def test_it_prints_every_result_of_both_brokers_beside_wilson_and_katz(self, tmp_path):
        text = mr.report(_runs_csv(tmp_path, SMALL), draws=300)
        assert "Run-level 95% percentile intervals, 300 resamples" in text
        assert "==== kafka ====" in text and "==== redis ====" in text
        assert "E-A7          l75  runs 2/2  normal 0.1500" in text
        assert "(Wilson [" in text and "(Katz [" in text
        # The real-time arm with no negative: no run-level interval, and Katz cannot be taken.
        assert "real-time 0.0000 no interval (Wilson [0.0000, " in text
        assert "factor unbounded no interval (Katz no interval)" in text
        assert "Placement at k = 6" in text and "factor 2.00" in text
        assert "pad 4096 B 0.2900" in text and "growth 42.00" in text
        # Kafka's sweep is not monotone, so the ends are printed as well; Redis's is.
        assert text.count("not monotone") == 1
        assert "both brokers pooled" in text

    def test_a_file_holding_one_result_reports_the_others_as_empty(self, tmp_path):
        rows = (_r("placement", "E-A6", "k6_conc", "concentrated", [(100, 8)], "ea6")
                + _r("placement", "E-A6", "k6_spread", "spread", [(100, 17)], "ea6"))
        text = mr.report(_runs_csv(tmp_path, rows), draws=100)
        assert "0 pairs, factor none to none" in text and "factor 2.12" in text

    def test_main_prints_the_report(self, tmp_path, capsys):
        assert mr.main(["report", "--csv", _runs_csv(tmp_path, SMALL), "--draws", "200"]) == 0
        assert "Path length, the fall across the padding sweep" in capsys.readouterr().out


class TestTheIntervalsFile:
    """The committed intervals the paper's mechanism table and macros read (6 Oct 2026)."""

    def test_a_cell_is_blank_for_none_and_inf_for_unbounded(self):
        assert mr._cell(None) == "" and mr._cell(math.inf) == "inf"
        assert mr._cell(0.123456789) == "0.123457"

    def test_every_comparison_of_both_brokers_is_one_row(self, tmp_path):
        rows = mr.intervals(_runs_csv(tmp_path, SMALL), draws=300)
        kinds = [(r["result"], r["backend"]) for r in rows]
        for backend in ("kafka", "redis"):
            assert kinds.count(("priority", backend)) == 3
            assert kinds.count(("placement", backend)) == 1
            assert kinds.count(("path", backend)) == 1
            assert kinds.count(("path_ends", backend)) == 1
            assert kinds.count(("ladder", backend)) == 1
        assert kinds.count(("trace", "both")) == 1
        e_a5b = [r for r in rows if r["result"] == "priority" and r["campaign"] == "E-A5b"
                 and r["backend"] == "kafka"][0]
        # No real-time negative: the factor is unbounded, with no interval and no verdict.
        assert e_a5b["factor"] == "inf" and e_a5b["factor_lo"] == "" and e_a5b["disjoint"] == ""
        assert e_a5b["bottom_lo"] == "" and e_a5b["bottom_hi"] == ""
        e_a7 = [r for r in rows if r["result"] == "priority" and r["campaign"] == "E-A7"
                and r["backend"] == "kafka"][0]
        assert float(e_a7["factor"]) == pytest.approx(30.0) and e_a7["disjoint"] == "True"
        kafka_path = [r for r in rows if r["result"] == "path" and r["backend"] == "kafka"][0]
        assert (kafka_path["top"], kafka_path["bottom"]) == ("4096", "262144")

    def test_the_file_round_trips(self, tmp_path):
        rows = mr.intervals(_runs_csv(tmp_path, SMALL), draws=200)
        out = tmp_path / "sub" / "intervals.csv"
        mr.write_intervals(rows, str(out))
        assert mr.read_intervals(str(out)) == rows

    def test_main_writes_the_file(self, tmp_path, capsys):
        out = tmp_path / "intervals.csv"
        assert mr.main(["intervals", "--csv", _runs_csv(tmp_path, SMALL), "--out", str(out),
                        "--draws", "100"]) == 0
        assert "comparisons to" in capsys.readouterr().out and out.exists()

    def test_the_committed_intervals_hold_what_the_paper_prints(self):
        rows = mr.read_intervals()
        redis = [r for r in rows if r["result"] == "priority" and r["backend"] == "redis"]
        assert len(redis) == 8 and all(r["disjoint"] == "True" for r in redis)
        assert 5.5 < min(float(r["factor"]) for r in redis) < max(
            float(r["factor"]) for r in redis) < 8.5
        placement = {(r["campaign"], r["backend"]): float(r["factor"])
                     for r in rows if r["result"] == "placement"}
        assert placement[("E-A6", "kafka")] > 1 > placement[("E-A6", "redis")]
        assert placement[("E-A6b", "kafka")] > 1 > placement[("E-A6b", "redis")]


# --- the committed file --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def committed():
    return mr.read_runs()


class TestTheCommittedFile:

    def test_it_agrees_with_both_committed_records(self, committed):
        assert mr.check(committed) == []

    def test_every_cell_is_25_runs_whose_messages_and_late_ones_make_2985(self, committed):
        """Every cell published 2,985 matched messages in 25 runs, on each broker, and held all
        of them until 7 Oct 2026. The late messages of stale_backlog.py are left out since, so a
        cell's messages and its runs' late ones, counted by the census, make the 2,985."""
        import csv as _csv
        late = {r["run_id"]: int(r["late"]) for r in _csv.DictReader(open(
            ROOT / "docs" / "results" / "backlog_by_run.csv", encoding="utf-8"))}
        cells = {}
        for r in committed:
            c = cells.setdefault((r["campaign"], r["cell"], r["backend"]), [0, 0, 0])
            c[0] += 1
            c[1] += r["run_events"]
            c[2] += late[r["run"]]
        assert len(cells) == 76, ("16 priority, 4 placement, 8 path-length, 8 traced and 2 "
                                  "ladder cells, on two brokers")
        assert {(runs, kept + gone) for runs, kept, gone in cells.values()} == {(25, 2985)}
        assert min(kept for _, kept, _ in cells.values()) < 2985, "the late messages are out"

    def test_the_kafka_halves_give_the_committed_analyses_factors(self, monkeypatch):
        """The run file and the cell files must describe one set of messages."""
        import priority_pairs
        import stat_intervals
        monkeypatch.chdir(ROOT)                    # stat_intervals reads relative paths
        pairs = {(p["campaign"], p["level"]): p for p in mr.priority_intervals(draws=200)}
        for p in priority_pairs.usable():
            assert pairs[(p["campaign"], p["level"])]["factor"] == pytest.approx(p["factor"])
        place = mr.placement_intervals(draws=200)
        for campaign, phase in (("E-A6", "ea6"), ("E-A6b", "ea6b")):
            (_, kc, nc), (_, ks, ns) = stat_intervals.geometry_cells(phase)
            assert place[campaign]["factor"] == pytest.approx((ks / ns) / (kc / nc))
        fall = mr.path_intervals(draws=200)
        assert fall["E-A10"]["factor"] == pytest.approx(stat_intervals.payload_span()["rate_fall"])
        assert fall["E-A10b"]["factor"] == pytest.approx(
            stat_intervals.payload_span("ea10b")["rate_fall"])
        knee = {r["condition"]: r for r in mr._read_csv(
            str(ROOT / "docs" / "results" / "model" / "knee_resolution.csv"))
            if r["phase"] == "ea3"}
        assert mr.ladder_intervals(draws=200)["E-A3"]["factor"] == pytest.approx(
            int(knee["bg7"]["n_inversions"]) / int(knee["bg0"]["n_inversions"]))

    def test_the_kafka_halves_of_the_traced_cells_are_the_committed_rates(self):
        """runq_tail.csv's inversion column and the untraced control, to the four places the
        supplement prints."""
        got = {(p["campaign"], p["level"]): p for p in mr.trace_intervals(draws=200)}
        # 7 Oct 2026: without the late messages; 0.2315, 0.1276, 0.1956 and 0.2717 before.
        for key, normal, rt in ((("E-A9", "l88"), 0.2720, 0.0), (("E-A9b", "l75"), 0.1644, 0.0),
                                (("E-A9b", "l88"), 0.2588, 0.0),
                                (("E-A9-untraced", "l88"), 0.2728, 0.0050)):
            assert round(got[key]["normal"]["rate"], 4) == normal
            assert round(got[key]["real-time"]["rate"], 4) == rt

    @pytest.mark.parametrize("backend", mr.BACKENDS)
    def test_every_pair_is_still_disjoint_when_whole_runs_are_resampled(self, backend):
        """The caption's claim, "every pair falls, with disjoint intervals", on run-level
        intervals rather than on Wilson's, and on either broker."""
        pairs = mr.priority_intervals(backend=backend)
        assert len(pairs) == 8
        assert all(p["disjoint"] for p in pairs), [
            (p["campaign"], p["level"]) for p in pairs if not p["disjoint"]]

    @pytest.mark.parametrize("backend", mr.BACKENDS)
    def test_a_factor_is_unbounded_exactly_where_three_runs_or_fewer_hold_every_negative(
            self, backend):
        """A resample of 25 runs misses all r negative runs with probability (1 - r/25)^25,
        which passes the 2.5% tail at r = 3 and not at r = 4. Each pair's count of unbounded
        resamples must be that probability, and its upper end infinite exactly when r <= 3."""
        for p in mr.priority_intervals(backend=backend):
            r = sum(1 for k in p["real-time"]["run_rates"] if k > 0)
            share = (1 - r / 25.0) ** 25
            assert p["unbounded_draws"] / p["draws"] == pytest.approx(share, abs=0.01)
            assert math.isinf(p["factor_ci"][1]) == (r <= 3), (p["campaign"], p["level"], r)
