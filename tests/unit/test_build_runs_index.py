"""Tests for build_runs_index.

This index is what survives the raw data. Once producer.csv and consumer_events.csv are deleted
the integrity verdict in this file is the only remaining evidence that the audit rejecting 1,321
of 2,266 runs was ever computed, so the tests concentrate on the two ways it could quietly lie:
a run that was never assessed reading as clean, and a parse failure inflating the denominator so
the negative fraction comes out lower than it is.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from build_runs_index import (  # noqa: E402
    NEG_FRACTION_LIMIT, build, campaign_of, feeds_of, main, started_of,
    topology_of, transport_and_integrity, usage_map, verdict,
)


def _run(tmp, name, acks, consumes, meta=None, bom=False):
    d = tmp / "runs" / name
    d.mkdir(parents=True)
    with (d / "producer.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["event_id", "t_broker_ack_ns"])
        w.writerows(acks)
    with (d / "consumer_events.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["event_id", "t_consume_ns"])
        w.writerows(consumes)
    if meta is not None:
        enc = "utf-8-sig" if bom else "utf-8"
        (d / "meta.json").write_text(json.dumps(meta), encoding=enc)
    return d


class TestIntegrity:
    def test_a_clean_run_is_usable(self, tmp_path):
        d = _run(tmp_path, "r1", [("a", 100), ("b", 200)], [("a", 1100), ("b", 1200)])
        tr = transport_and_integrity(str(d))
        assert tr["n_matched"] == 2 and tr["n_negative"] == 0
        assert verdict(tr) == "usable"

    def test_negative_transport_beyond_the_limit_condemns(self, tmp_path):
        acks = [(str(i), 1000) for i in range(100)]
        # Two of a hundred invert: 2%, above the 1% rule.
        cons = [(str(i), 900 if i < 2 else 2000) for i in range(100)]
        d = _run(tmp_path, "r2", acks, cons)
        tr = transport_and_integrity(str(d))
        assert tr["frac_negative"] == pytest.approx(0.02)
        assert tr["frac_negative"] > NEG_FRACTION_LIMIT
        assert verdict(tr) == "condemned"

    def test_one_inversion_in_a_hundred_is_within_the_rule(self, tmp_path):
        acks = [(str(i), 1000) for i in range(100)]
        cons = [(str(i), 900 if i < 1 else 2000) for i in range(100)]
        tr = transport_and_integrity(str(_run(tmp_path, "r3", acks, cons)))
        assert verdict(tr) == "usable", "the rule is >1%, not >=1%"

    def test_a_negative_median_condemns_whatever_the_fraction(self, tmp_path):
        acks = [(str(i), 1000) for i in range(10)]
        cons = [(str(i), 100) for i in range(10)]     # every one inverted
        tr = transport_and_integrity(str(_run(tmp_path, "r4", acks, cons)))
        assert tr["median_ms"] < 0 and verdict(tr) == "condemned"

    def test_unparseable_events_leave_the_denominator_alone(self, tmp_path):
        """Counting a row we could not parse would dilute the fraction and flatter the run."""
        acks = [("a", 1000), ("b", 1000), ("c", "not-a-number")]
        cons = [("a", 900), ("b", 2000), ("c", 2000), ("d", 2000)]
        tr = transport_and_integrity(str(_run(tmp_path, "r5", acks, cons)))
        assert tr["n_matched"] == 2, "only events with both timestamps count"
        assert tr["frac_negative"] == pytest.approx(0.5)

    def test_a_run_with_no_overlap_is_not_usable(self, tmp_path):
        tr = transport_and_integrity(str(_run(tmp_path, "r6", [("a", 1)], [("z", 2)])))
        assert tr["n_matched"] == 0 and verdict(tr) == "no-matched-events"

    def test_missing_csvs_are_not_assessed_not_clean(self, tmp_path):
        d = tmp_path / "runs" / "empty"
        d.mkdir(parents=True)
        assert transport_and_integrity(str(d)) is None
        assert verdict(None) == "not-assessed"

    def test_fast_mode_never_reports_a_verdict_it_did_not_compute(self, tmp_path):
        """--fast skips the raw pass. Every row must then say so rather than defaulting."""
        _run(tmp_path, "r7", [("a", 100)], [("a", 50)])          # would be condemned
        rows = build(str(tmp_path / "runs"), str(tmp_path / "none"), fast=True)
        assert rows[0]["integrity"] == "not-assessed"
        assert rows[0]["frac_negative_transport"] == ""


class TestMetadata:
    def test_a_bom_in_meta_json_does_not_empty_the_row(self, tmp_path):
        """meta.json files carry a BOM. Plain utf-8 raises, and the reader swallows it."""
        d = _run(tmp_path, "concurrency_n5_20260101_000000_kafka_feed1_rep1",
                 [("a", 1)], [("a", 2)],
                 meta={"backend": "kafka", "git": {"head": "abc123def456"}}, bom=True)
        rows = build(str(tmp_path / "runs"), str(tmp_path / "none"), fast=True)
        assert rows[0]["backend"] == "kafka", "BOM broke the metadata read"
        assert rows[0]["git_head"] == "abc123def456"
        assert d.exists()


    def test_a_null_metadata_value_does_not_crash_the_pass(self, tmp_path):
        """A present-but-null key is not a missing key: the default never fires.

        meta.get("git", {}).get("head", "")[:12] raised on the cloud corpus, where some runs
        record "git": {"head": null}. One such run aborted the whole index build.
        """
        _run(tmp_path, "r1", [("a", 100)], [("a", 200)],
             meta={"git": {"head": None}, "backend": None, "plan_csv": None,
                   "speedup": None})
        rows = build(str(tmp_path / "runs"), str(tmp_path / "none"), fast=True)
        assert rows[0]["git_head"] == "" and rows[0]["backend"] == ""
        assert rows[0]["plan"] == "" and rows[0]["speedup"] == ""

    def test_a_null_git_object_is_also_safe(self, tmp_path):
        _run(tmp_path, "r1", [("a", 100)], [("a", 200)], meta={"git": None})
        rows = build(str(tmp_path / "runs"), str(tmp_path / "none"), fast=True)
        assert rows[0]["git_head"] == ""

    def test_feeds_come_from_the_id_or_the_topic(self):
        assert feeds_of("concurrency_n10_20260617_162947_kafka_feed1_rep1", {}) == "10"
        assert feeds_of("nothing-here", {"topic": "sb-events-n25-feed3"}) == "25"
        assert feeds_of("nothing-here", {}) == ""

    def test_topology_from_the_id_then_from_the_ports(self):
        assert topology_of("batch9_x_kafka_cluster_s1_n1_rep1", {}) == "cluster"
        assert topology_of("x", {"bootstrap": "localhost:19092"}) == "kafka-single"
        assert topology_of("x", {"redis": {"port": 16379}}) == "redis-single"
        assert topology_of("x", {}) == ""

    def test_the_start_time_is_recovered_from_the_id(self):
        assert started_of("concurrency_n5_20260726_013000_kafka", {}) == "2026-07-26T01:30:00Z"
        assert started_of("no-stamp", {"started": "later"}) == "later"

    def test_campaigns_are_named_and_unknown_says_unknown(self):
        assert campaign_of("concurrency_n5_x") == "concurrency"
        assert campaign_of("batch9p_x") == "s2sf12-acks"
        assert campaign_of("batch9_x") == "s2-batch"
        assert campaign_of("something-else") == "unknown"


class TestUsage:
    def test_a_run_named_by_an_aggregate_is_marked_used(self, tmp_path):
        res = tmp_path / "res"
        res.mkdir()
        (res / "agg.csv").write_text("run_id,x\nr1,1\n", encoding="utf-8")
        assert "agg.csv" in usage_map(str(res))["r1"]

    def test_a_csv_without_a_run_column_is_skipped(self, tmp_path):
        res = tmp_path / "res"
        res.mkdir()
        (res / "other.csv").write_text("rho,rate\n0.88,0.2\n", encoding="utf-8")
        assert usage_map(str(res)) == {}

    def test_an_unused_run_is_visibly_unused(self, tmp_path):
        _run(tmp_path, "orphan", [("a", 1)], [("a", 2)])
        (tmp_path / "res").mkdir()
        rows = build(str(tmp_path / "runs"), str(tmp_path / "res"), fast=True)
        assert rows[0]["used_by"] == ""


class TestCLI:
    def test_missing_runs_directory_is_an_error(self, tmp_path, capsys):
        assert main(["--runs", str(tmp_path / "absent")]) == 1

    def test_it_writes_every_declared_column(self, tmp_path):
        _run(tmp_path, "r1", [("a", 100)], [("a", 200)], meta={"backend": "redis"})
        out = tmp_path / "idx.csv"
        assert main(["--runs", str(tmp_path / "runs"), "--results", str(tmp_path / "none"),
                     "--out", str(out), "--progress", "0"]) == 0
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        from build_runs_index import FIELDS
        assert list(rows[0]) == FIELDS
        assert rows[0]["backend"] == "redis" and rows[0]["integrity"] == "usable"

    def test_the_summary_counts_each_verdict(self, tmp_path, capsys):
        _run(tmp_path, "good", [("a", 100)], [("a", 200)])
        _run(tmp_path, "bad", [(str(i), 1000) for i in range(10)],
             [(str(i), 100) for i in range(10)])
        main(["--runs", str(tmp_path / "runs"), "--results", str(tmp_path / "none"),
              "--out", str(tmp_path / "i.csv"), "--progress", "0"])
        out = capsys.readouterr().out
        assert "usable" in out and "condemned" in out
        assert "named by no aggregate" in out

class TestFailurePaths:
    """Every one of these is a way the index could lose a run without saying so."""

    def test_malformed_meta_json_does_not_drop_the_run(self, tmp_path):
        d = _run(tmp_path, "r1", [("a", 100)], [("a", 200)])
        (d / "meta.json").write_text("{not json", encoding="utf-8")
        rows = build(str(tmp_path / "runs"), str(tmp_path / "none"), fast=True)
        assert len(rows) == 1, "a bad meta.json must not remove the run from the index"
        assert rows[0]["run_id"] == "r1" and rows[0]["backend"] == ""

    def test_malformed_tti_summary_is_tolerated(self, tmp_path):
        d = _run(tmp_path, "r1", [("a", 100)], [("a", 200)])
        (d / "tti_summary.json").write_text("[[[", encoding="utf-8")
        rows = build(str(tmp_path / "runs"), str(tmp_path / "none"), fast=True)
        assert rows[0]["tti_median_ms"] == ""

    def test_an_unparseable_ack_row_is_skipped(self, tmp_path):
        """A non-integer ack must not abort the run's assessment."""
        d = _run(tmp_path, "r1", [("a", "x"), ("b", 100)], [("a", 1), ("b", 200)])
        tr = transport_and_integrity(str(d))
        assert tr["n_matched"] == 1

    def test_a_missing_producer_csv_is_not_assessed(self, tmp_path):
        d = _run(tmp_path, "r1", [("a", 100)], [("a", 200)])
        (d / "producer.csv").unlink()
        assert transport_and_integrity(str(d)) is None

    def test_line_count_of_an_absent_file_is_blank(self, tmp_path):
        from build_runs_index import _count_lines
        assert _count_lines(str(tmp_path / "nope.csv")) == ""

    def test_line_count_excludes_the_header(self, tmp_path):
        p = tmp_path / "x.csv"
        p.write_text("h\n1\n2\n", encoding="utf-8")
        from build_runs_index import _count_lines
        assert _count_lines(str(p)) == 2

    def test_an_unreadable_aggregate_does_not_abort_the_usage_scan(self, tmp_path, monkeypatch):
        res = tmp_path / "res"
        res.mkdir()
        (res / "good.csv").write_text("run_id\nr1\n", encoding="utf-8")
        (res / "bad.csv").write_text("run_id\nr2\n", encoding="utf-8")
        real = open

        def flaky(path, *a, **k):
            if str(path).endswith("bad.csv"):
                raise OSError("unreadable")
            return real(path, *a, **k)

        monkeypatch.setitem(__builtins__ if isinstance(__builtins__, dict)
                            else __builtins__.__dict__, "open", flaky)
        used = usage_map(str(res))
        assert "r1" in used, "one unreadable file must not lose the others"

    def test_progress_writes_to_stderr_not_the_index(self, tmp_path, capsys):
        for i in range(3):
            _run(tmp_path, f"r{i}", [("a", 100)], [("a", 200)])
        build(str(tmp_path / "runs"), str(tmp_path / "none"), fast=True, progress=1)
        cap = capsys.readouterr()
        assert "3" in cap.err and cap.out == "", "progress belongs on stderr"


class TestMetadataArchive:
    """The archive is the only place the per-file code hashes survive deletion."""

    def test_every_meta_json_is_written_one_per_line(self, tmp_path):
        import gzip
        from build_runs_index import archive_metadata
        _run(tmp_path, "r1", [("a", 1)], [("a", 2)], meta={"backend": "kafka"})
        _run(tmp_path, "r2", [("a", 1)], [("a", 2)], meta={"backend": "redis"}, bom=True)
        out = tmp_path / "arch.jsonl.gz"
        n, skipped = archive_metadata(str(tmp_path / "runs"), str(out))
        assert (n, skipped) == (2, 0)
        lines = gzip.open(out, "rt", encoding="utf-8").read().strip().split("\n")
        assert len(lines) == 2
        assert {json.loads(x)["backend"] for x in lines} == {"kafka", "redis"}

    def test_the_run_id_is_stamped_in_even_if_absent(self, tmp_path):
        import gzip
        from build_runs_index import archive_metadata
        _run(tmp_path, "named", [("a", 1)], [("a", 2)], meta={"backend": "kafka"})
        out = tmp_path / "a.jsonl.gz"
        archive_metadata(str(tmp_path / "runs"), str(out))
        rec = json.loads(gzip.open(out, "rt", encoding="utf-8").read().strip())
        assert rec["run_id"] == "named", "a record must identify its own run"

    def test_an_existing_run_id_is_not_overwritten(self, tmp_path):
        import gzip
        from build_runs_index import archive_metadata
        _run(tmp_path, "dirname", [("a", 1)], [("a", 2)],
             meta={"run_id": "the-real-id"})
        out = tmp_path / "a.jsonl.gz"
        archive_metadata(str(tmp_path / "runs"), str(out))
        rec = json.loads(gzip.open(out, "rt", encoding="utf-8").read().strip())
        assert rec["run_id"] == "the-real-id"

    def test_an_unparseable_meta_is_counted_not_dropped_silently(self, tmp_path):
        from build_runs_index import archive_metadata
        d = _run(tmp_path, "bad", [("a", 1)], [("a", 2)], meta={"x": 1})
        (d / "meta.json").write_text("{oops", encoding="utf-8")
        _run(tmp_path, "good", [("a", 1)], [("a", 2)], meta={"x": 2})
        n, skipped = archive_metadata(str(tmp_path / "runs"), str(tmp_path / "a.gz"))
        assert (n, skipped) == (1, 1), "a skipped file must be reported, not vanish"

    def test_runs_without_meta_are_simply_absent(self, tmp_path):
        from build_runs_index import archive_metadata
        _run(tmp_path, "nometa", [("a", 1)], [("a", 2)])
        n, skipped = archive_metadata(str(tmp_path / "runs"), str(tmp_path / "a.gz"))
        assert (n, skipped) == (0, 0)

    def test_the_cli_reports_the_archive(self, tmp_path, capsys):
        _run(tmp_path, "r1", [("a", 1)], [("a", 2)], meta={"backend": "kafka"})
        main(["--runs", str(tmp_path / "runs"), "--results", str(tmp_path / "none"),
              "--out", str(tmp_path / "i.csv"), "--progress", "0",
              "--archive-meta", str(tmp_path / "m.jsonl.gz")])
        assert "meta.json" in capsys.readouterr().out
