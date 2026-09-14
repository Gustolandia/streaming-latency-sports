"""Tests for scripts/run_queue.py.

The queue is where "random order" and "every run tracked" stop being intentions. So the tests
pin the rules as behaviour: every setup once per round, no setup twice in a row, a failure
recorded and re-queued rather than overwritten, and no way to re-run a finished run.
"""
import io
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import run_queue as rq  # noqa: E402

STAMP = "2026-09-20T09:30:00Z"


def fixed():
    return STAMP


def design(n=3, rounds=4, seed=7):
    return {"seed": seed, "rounds": rounds,
            "setups": [{"id": "s%d" % i, "slice_ns": 750000 * (i + 1)} for i in range(n)]}


def executed_order(rows):
    return [r["setup"] for r in rows]


def test_the_ledger_clock_is_utc_to_the_second():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", rq.now_utc())


class TestMaking:

    def test_every_setup_runs_once_per_round(self):
        rows = rq.make_rows(design(n=3, rounds=4))
        for r in range(1, 5):
            assert sorted(x["setup"] for x in rows if x["round"] == str(r)) == ["s0", "s1", "s2"]

    def test_the_seed_fixes_the_order_and_is_written_down(self):
        a, b = rq.make_rows(design(seed=11)), rq.make_rows(design(seed=11))
        assert executed_order(a) == executed_order(b)
        assert {r["seed"] for r in a} == {"11"}
        assert executed_order(a) != executed_order(rq.make_rows(design(seed=12)))

    @pytest.mark.parametrize("seed", range(40))
    def test_no_setup_ever_runs_twice_in_a_row(self, seed):
        """Two setups over twenty rounds forces the reshuffle to happen, often."""
        order = executed_order(rq.make_rows(design(n=2, rounds=20, seed=seed)))
        assert all(a != b for a, b in zip(order, order[1:]))

    def test_rows_carry_their_parameters_without_the_id(self):
        row = rq.make_rows(design(n=2, rounds=1))[0]
        assert json.loads(row["params"]) == {"slice_ns": 750000 * (int(row["setup"][1]) + 1)}
        assert row["key"] == "r001-%s-a1" % row["setup"]
        assert (row["status"], row["attempt"]) == ("queued", "1")

    def test_a_single_setup_in_a_single_round_is_allowed(self):
        assert len(rq.make_rows(design(n=1, rounds=1))) == 1

    @pytest.mark.parametrize("bad,fragment", [
        ({"seed": 1, "rounds": 1, "setups": []}, "no setups"),
        ({"seed": 1, "rounds": 1}, "no setups"),
        ({"seed": 1, "rounds": 1, "setups": [{"slice_ns": 1}]}, "non-empty string id"),
        ({"seed": 1, "rounds": 1, "setups": [{"id": "a"}, {"id": "a"}]}, "ids repeat: a"),
        ({"seed": 1, "rounds": 0, "setups": [{"id": "a"}]}, "rounds must be"),
        ({"seed": 1, "rounds": "3", "setups": [{"id": "a"}]}, "rounds must be"),
        ({"seed": 1, "rounds": True, "setups": [{"id": "a"}]}, "rounds must be"),
        ({"seed": 1, "rounds": 2, "setups": [{"id": "a"}]}, "cannot avoid repeating"),
        ({"seed": None, "rounds": 1, "setups": [{"id": "a"}]}, "seed must be"),
        ({"seed": True, "rounds": 1, "setups": [{"id": "a"}]}, "seed must be")])
    def test_a_design_that_cannot_become_a_queue(self, bad, fragment):
        with pytest.raises(ValueError, match=fragment):
            rq.make_rows(bad)


class TestRunning:

    def test_next_hands_out_the_first_queued_run(self):
        rows = rq.make_rows(design())
        row = rq.take_next(rows, clock=fixed)
        assert row is rows[0] and row["status"] == "running" and row["started_utc"] == STAMP

    def test_a_run_left_running_blocks_the_queue(self):
        rows = rq.make_rows(design())
        rq.take_next(rows, clock=fixed)
        with pytest.raises(RuntimeError, match="still marked running"):
            rq.take_next(rows, clock=fixed)

    def test_recovering_records_the_lost_run_as_a_failure(self):
        rows = rq.make_rows(design())
        lost = rq.take_next(rows, clock=fixed)["key"]
        row = rq.take_next(rows, recover=True, clock=fixed)
        failed = rows[rq.index(rows, lost)]
        assert failed["status"] == "failed" and "runner stopped" in failed["reason"]
        assert row["status"] == "running" and row["key"] != lost
        assert any(r["key"].endswith("-a2") and r["status"] == "queued" for r in rows)

    def test_an_empty_queue_hands_out_nothing(self):
        rows = rq.make_rows(design(n=1, rounds=1))
        rq.finish(rows, rq.take_next(rows, clock=fixed)["key"], "done", run_dir="runs/x",
                  clock=fixed)
        assert rq.take_next(rows, clock=fixed) is None

    def test_done(self):
        rows = rq.make_rows(design())
        key = rq.take_next(rows, clock=fixed)["key"]
        assert rq.finish(rows, key, "done", run_dir="runs/r1", clock=fixed) is None
        row = rows[rq.index(rows, key)]
        assert (row["status"], row["run_dir"], row["finished_utc"]) == ("done", "runs/r1", STAMP)

    def test_only_a_running_run_can_finish(self):
        rows = rq.make_rows(design())
        with pytest.raises(RuntimeError, match="is queued, not running"):
            rq.finish(rows, rows[0]["key"], "done")

    def test_a_failure_needs_its_reason_and_a_known_status(self):
        rows = rq.make_rows(design())
        key = rq.take_next(rows, clock=fixed)["key"]
        with pytest.raises(ValueError, match="needs its reason"):
            rq.finish(rows, key, "failed")
        with pytest.raises(ValueError, match="done or failed"):
            rq.finish(rows, key, "surprising")

    def test_a_failure_is_kept_and_a_copy_goes_later_in_the_queue(self):
        rows = rq.make_rows(design(n=3, rounds=4))
        key = rq.take_next(rows, clock=fixed)["key"]
        copy = rq.finish(rows, key, "failed", reason="broker unreachable", clock=fixed)
        at = rq.index(rows, copy["key"])
        original = rows[rq.index(rows, key)]
        assert original["status"] == "failed" and original["reason"] == "broker unreachable"
        assert copy["attempt"] == "2" and copy["key"] == key[:-1] + "2"
        assert at > rq.index(rows, key)
        neighbours = {rows[at - 1]["setup"], rows[at + 1]["setup"] if at + 1 < len(rows) else None}
        assert copy["setup"] not in neighbours

    def test_a_copy_is_placed_the_same_way_every_time(self):
        orders = []
        for _ in range(2):
            rows = rq.make_rows(design(n=3, rounds=4))
            key = rq.take_next(rows, clock=fixed)["key"]
            rq.finish(rows, key, "failed", reason="x", clock=fixed)
            orders.append([r["key"] for r in rows])
        assert orders[0] == orders[1]

    def test_after_the_last_attempt_the_run_is_abandoned_not_deleted(self):
        rows = rq.make_rows(design(n=1, rounds=1))
        messages = []
        for _ in range(rq.MAX_ATTEMPTS):
            key = rq.take_next(rows, clock=fixed)["key"]
            messages.append(rq.finish(rows, key, "failed", reason="disk full", clock=fixed))
        assert messages[-1] is None
        assert [r["status"] for r in rows] == ["failed"] * (rq.MAX_ATTEMPTS - 1) + ["abandoned"]
        assert rq.take_next(rows, clock=fixed) is None

    def test_an_unknown_run(self):
        with pytest.raises(KeyError, match="no run 'r9'"):
            rq.index([], "r9")


class TestFiles:

    def test_a_queue_survives_the_round_trip_and_leaves_no_temporary_file(self, tmp_path):
        path = str(tmp_path / "queue.csv")
        rows = rq.make_rows(design())
        rq.write_queue(path, rows)
        assert rq.read_queue(path) == rows
        assert not os.path.exists(path + ".tmp")

    def test_an_unknown_status_is_refused(self, tmp_path):
        path = str(tmp_path / "queue.csv")
        rows = rq.make_rows(design(n=1, rounds=1))
        rows[0]["status"] = "rerun"
        rq.write_queue(path, rows)
        with pytest.raises(ValueError, match="has status 'rerun'"):
            rq.read_queue(path)


class TestReport:

    @pytest.mark.parametrize("hour,label", [("00", "night"), ("05", "night"), ("06", "morning"),
                                            ("12", "afternoon"), ("18", "evening"),
                                            ("23", "evening")])
    def test_time_of_day(self, hour, label):
        assert rq.bucket("2026-09-20T%s:10:00Z" % hour) == label

    def test_counts_balance_and_failures(self):
        rows = rq.make_rows(design(n=2, rounds=2))
        for row, hour in zip(rows[:3], ("03", "09", "21")):
            row.update(status="done", started_utc="2026-09-20T%s:00:00Z" % hour)
        rows[3].update(status="failed", reason="timeout")
        lines = rq.report(rows)
        assert lines[0] == "runs: queued 0, running 0, done 3, failed 1, abandoned 0"
        assert "failures:" in lines and any("failed: timeout" in line for line in lines)

    def test_no_failures_no_failure_section(self):
        assert "failures:" not in rq.report(rq.make_rows(design()))


class TestSessions:

    def test_sessions_come_in_rounds_and_never_repeat_back_to_back(self):
        order = rq.session_order(["hz1000", "hz250", "arm"], 3, seed=5)
        assert sorted(order) == sorted(["hz1000", "hz250", "arm"] * 3)
        assert all(a != b for a, b in zip(order, order[1:]))

    def test_one_session_once_is_fine(self):
        assert rq.session_order(["only"], 1, seed=1) == ["only"]

    @pytest.mark.parametrize("types,repeats,fragment", [
        ([], 2, "no session types"), (["a", "a"], 1, "types repeat"),
        (["a", "b"], 0, "at least 1"), (["a"], 2, "cannot avoid following itself")])
    def test_orders_that_cannot_be_made(self, types, repeats, fragment):
        with pytest.raises(ValueError, match=fragment):
            rq.session_order(types, repeats, seed=1)


class TestMain:

    @staticmethod
    def run(argv):
        out = io.StringIO()
        return rq.main(argv, out=out, clock=fixed), out.getvalue()

    @pytest.fixture
    def queue(self, tmp_path):
        design_path = tmp_path / "design.json"
        design_path.write_text(json.dumps(design(n=2, rounds=2)), encoding="utf-8")
        path = str(tmp_path / "queue.csv")
        code, text = self.run(["make", "--design", str(design_path), "--out", path])
        assert code == 0 and text.startswith("4 runs in 2 rounds, seed 7")
        return path, str(design_path)

    def test_a_queue_is_never_remade_over_itself(self, queue):
        path, design_path = queue
        code, text = self.run(["make", "--design", design_path, "--out", path])
        assert code == 2 and "exists" in text
        assert self.run(["make", "--design", design_path, "--out", path, "--force"])[0] == 0
        self.run(["next", "--queue", path])
        code, text = self.run(["make", "--design", design_path, "--out", path, "--force"])
        assert code == 2 and "has started" in text

    def test_next_finish_and_report(self, queue):
        path, _ = queue
        code, text = self.run(["next", "--queue", path])
        first = json.loads(text)
        assert code == 0 and first["attempt"] == "1" and "slice_ns" in first["params"]
        code, text = self.run(["finish", "--queue", path, "--key", first["key"],
                               "--status", "failed", "--reason", "broker restarted"])
        assert code == 0 and "queued again as" in text
        second = json.loads(self.run(["next", "--queue", path])[1])
        assert self.run(["finish", "--queue", path, "--key", second["key"], "--status",
                         "done", "--run-dir", "runs/x"]) == (0, "%s done\n" % second["key"])
        code, text = self.run(["report", "--queue", path])
        assert code == 0 and "done 1, failed 1" in text

    def test_the_last_attempt_says_abandoned_and_an_empty_queue_says_finished(self, tmp_path):
        design_path = tmp_path / "d.json"
        design_path.write_text(json.dumps(design(n=1, rounds=1)), encoding="utf-8")
        path = str(tmp_path / "q.csv")
        self.run(["make", "--design", str(design_path), "--out", path])
        for attempt in range(rq.MAX_ATTEMPTS):
            key = json.loads(self.run(["next", "--queue", path])[1])["key"]
            code, text = self.run(["finish", "--queue", path, "--key", key, "--status",
                                   "failed", "--reason", "no route"])
        assert "abandoned" in text
        assert self.run(["next", "--queue", path]) == (3, "the queue is finished\n")

    def test_sessions(self):
        code, text = self.run(["sessions", "--types", "hz1000, hz250", "--repeats", "2",
                               "--seed", "3"])
        assert code == 0 and len(text.splitlines()) == 4 and text.startswith("1. hz")

    def test_errors_are_lines_not_tracebacks(self, queue):
        path, _ = queue
        assert self.run(["finish", "--queue", path, "--key", "nope", "--status", "done"])[0] == 2
        self.run(["next", "--queue", path])
        code, text = self.run(["next", "--queue", path])
        assert code == 2 and "--recover" in text
