"""Tests for mark_load_bearing.

The column exists because the index's earlier `used_by` answered a narrower question than it
appeared to. The mechanism analyses find their runs by matching a timestamp from a condition
directory, never by naming a run_id in a CSV, so every run behind the geometry contrast, the
payload sweep and the kernel trace read as unused. On the cloud corpus 5,114 of 5,690
load-bearing runs are found only that way. The test that matters most is therefore the one
asserting a condition-matched run is kept even when no aggregate names it.
"""
import csv
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from mark_load_bearing import (  # noqa: E402
    annotate, classify, condition_timestamps, main, named_by_aggregate,
)

TS = "n5_20260726_013000"
RUN = f"concurrency_{TS}_kafka_feed1_rep1"


def _index(tmp, run_ids):
    p = tmp / "idx.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["run_id", "campaign"])
        w.writeheader()
        for r in run_ids:
            w.writerow({"run_id": r, "campaign": "concurrency"})
    return p


def _condition(tmp, phase, cell):
    d = tmp / "res" / phase / cell / f"concurrency_concurrency_{TS}"
    d.mkdir(parents=True)
    return d


class TestConditionMatching:
    def test_a_condition_matched_run_is_load_bearing_without_any_aggregate(self, tmp_path):
        """The whole point. No CSV names this run; an analysis script still depends on it."""
        _condition(tmp_path, "depth", "l88_base")
        idx = _index(tmp_path, [RUN])
        rows, _ = annotate(str(idx), str(tmp_path / "res"))
        assert rows[0]["load_bearing"] == "yes"
        assert rows[0]["load_bearing_why"].startswith("condition:")

    def test_a_run_from_a_different_timestamp_is_not_swept_in(self, tmp_path):
        _condition(tmp_path, "depth", "l88_base")
        other = "concurrency_n5_20260101_000000_kafka_feed1_rep1"
        rows, _ = annotate(str(_index(tmp_path, [other])), str(tmp_path / "res"))
        assert rows[0]["load_bearing"] == "no"

    def test_the_prefix_must_match_the_whole_timestamp(self, tmp_path):
        """A run id that merely contains the timestamp elsewhere must not count."""
        _condition(tmp_path, "depth", "l88_base")
        rows, _ = annotate(str(_index(tmp_path, [f"other_{TS}_x"])), str(tmp_path / "res"))
        assert rows[0]["load_bearing"] == "no"

    def test_timestamps_are_found_at_several_depths(self, tmp_path):
        _condition(tmp_path, "depth", "l75_rt")
        (tmp_path / "res" / "window").mkdir(parents=True)
        (tmp_path / "res" / "window" / f"concurrency_concurrency_{TS}").mkdir()
        found = condition_timestamps(str(tmp_path / "res"))
        assert TS in found
        assert {"depth", "window"} & found[TS]


class TestAggregateMatching:
    def test_a_named_run_is_load_bearing(self, tmp_path):
        res = tmp_path / "res"
        res.mkdir()
        (res / "agg.csv").write_text("run_id,x\nr1,1\n", encoding="utf-8")
        rows, _ = annotate(str(_index(tmp_path, ["r1"])), str(res))
        assert rows[0]["load_bearing"] == "yes"
        assert rows[0]["load_bearing_why"] == "aggregate:agg.csv"

    def test_a_csv_with_no_run_column_is_ignored(self, tmp_path):
        res = tmp_path / "res"
        res.mkdir()
        (res / "x.csv").write_text("rho,rate\n0.88,0.2\n", encoding="utf-8")
        assert named_by_aggregate(str(res)) == {}

    def test_an_unreadable_csv_does_not_abort_the_scan(self, tmp_path, monkeypatch):
        res = tmp_path / "res"
        res.mkdir()
        (res / "good.csv").write_text("run_id\nr1\n", encoding="utf-8")
        (res / "bad.csv").write_text("run_id\nr2\n", encoding="utf-8")
        real = open

        def flaky(path, *a, **k):
            if str(path).endswith("bad.csv"):
                raise OSError("nope")
            return real(path, *a, **k)

        import builtins
        monkeypatch.setattr(builtins, "open", flaky)
        assert "r1" in named_by_aggregate(str(res))


class TestClassify:
    def test_reasons_are_recorded_not_just_the_boolean(self):
        reasons = classify("r1", {"r1": {"a.csv"}}, {})
        assert reasons == ["aggregate:a.csv"]

    def test_both_reasons_can_apply(self):
        reasons = classify(RUN, {RUN: {"a.csv"}}, {TS: {"depth"}})
        assert len(reasons) == 2

    def test_nothing_depending_on_it_gives_no_reason(self):
        assert classify("orphan", {}, {}) == []


class TestCLI:
    def test_a_missing_index_is_an_error(self, tmp_path, capsys):
        assert main(["--index", str(tmp_path / "absent.csv")]) == 1

    def test_an_empty_index_is_an_error(self, tmp_path, capsys):
        p = tmp_path / "e.csv"
        p.write_text("run_id\n", encoding="utf-8")
        (tmp_path / "res").mkdir()
        assert main(["--index", str(p), "--results", str(tmp_path / "res")]) == 1
        assert "empty" in capsys.readouterr().out

    def test_it_rewrites_in_place_and_appends_the_columns(self, tmp_path, capsys):
        _condition(tmp_path, "depth", "l88_base")
        idx = _index(tmp_path, [RUN, "orphan"])
        assert main(["--index", str(idx), "--results", str(tmp_path / "res")]) == 0
        rows = list(csv.DictReader(idx.open(encoding="utf-8")))
        assert list(rows[0])[-2:] == ["load_bearing", "load_bearing_why"]
        assert {r["run_id"]: r["load_bearing"] for r in rows} == {RUN: "yes", "orphan": "no"}
        out = capsys.readouterr().out
        assert "load-bearing" in out and "nothing depends on" in out

    def test_out_leaves_the_original_untouched(self, tmp_path):
        idx = _index(tmp_path, ["orphan"])
        before = idx.read_text(encoding="utf-8")
        (tmp_path / "res").mkdir()
        out = tmp_path / "copy.csv"
        main(["--index", str(idx), "--results", str(tmp_path / "res"), "--out", str(out)])
        assert idx.read_text(encoding="utf-8") == before
        assert "load_bearing" in out.read_text(encoding="utf-8")


class TestThePathsAndRowsThatNameNoRun:

    def test_a_condition_path_carrying_no_timestamp_names_no_run(self, tmp_path):
        """The globs match `concurrency_concurrency_*` by name, and not every such directory
        carries a run id: interrupted runs and scratch folders leave ones that do not. A run
        id invented from such a name would mark an unrelated run as load-bearing."""
        cond = tmp_path / "results" / "depth" / "ea3"
        (cond / f"concurrency_concurrency_{TS}").mkdir(parents=True)
        (cond / "concurrency_concurrency_scratch").mkdir()
        found = condition_timestamps(str(tmp_path / "results"))
        assert list(found) == [TS]

    def test_an_aggregate_row_with_no_run_id_names_no_run(self, tmp_path):
        """A blank or total row must not be read as a dependency on some run."""
        results = tmp_path / "results"
        results.mkdir()
        with (results / "agg.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["run_id", "value"])
            w.writerow(["", 1])
            w.writerow([RUN, 2])
        assert set(named_by_aggregate(str(results))) == {RUN}
