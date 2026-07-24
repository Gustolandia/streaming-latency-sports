"""Tests for scripts/analyze_depth.py - target 100% branch coverage.

This script recomputes inversion rates from raw per-event data rather than trusting a summary,
because the summary is precisely what hides the failure the paper is about. The tests therefore
exercise the raw join directly, including the malformed cases a long campaign produces.
"""
import csv
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_depth import (  # noqa: E402
    run_inversion,
    run_transport_median,
    condition_timestamp,
    condition_inversion,
    condition_transport_by_backend,
    median_rho,
    delay_from_tag,
    n_from_tag,
    collect,
)

T0 = 1_700_000_000_000_000_000


def _run(runs_dir, run_id, transports_ms):
    """A run directory whose producer/consumer pair yields the given transport values."""
    d = runs_dir / run_id
    d.mkdir(parents=True, exist_ok=True)
    with (d / "producer.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "t_broker_ack_ns"])
        w.writeheader()
        for i in range(len(transports_ms)):
            w.writerow({"event_id": f"e{i}", "t_broker_ack_ns": T0})
    with (d / "consumer_events.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "t_consume_ns"])
        w.writeheader()
        for i, ms in enumerate(transports_ms):
            w.writerow({"event_id": f"e{i}", "t_consume_ns": T0 + int(ms * 1e6)})
    return d


def _condition(tmp, phase, name, ts, transports_by_backend, rho=None):
    cond = tmp / "depth" / phase / name
    (cond / f"concurrency_concurrency_{ts}").mkdir(parents=True, exist_ok=True)
    runs = tmp / "runs"
    for backend, vals in transports_by_backend.items():
        _run(runs, f"concurrency_{ts}_{backend}_feed1_rep1", vals)
    if rho is not None:
        with (cond / "utilisation.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["t_wall", "rho", "loadavg"])
            w.writeheader()
            for v in ([rho] if isinstance(rho, float) else rho):
                w.writerow({"t_wall": 1, "rho": v, "loadavg": 1.0})
    return cond, runs


class TestRunInversion:
    def test_counts_negative_transports(self, temp_dir):
        d = _run(temp_dir, "r1", [1.0, -2.0, 3.0, -4.0])
        assert run_inversion(str(d)) == (2, 4)

    def test_all_positive(self, temp_dir):
        assert run_inversion(str(_run(temp_dir, "r2", [1.0, 2.0]))) == (0, 2)

    def test_missing_files(self, temp_dir):
        d = temp_dir / "empty"
        d.mkdir()
        assert run_inversion(str(d)) == (0, 0)

    def test_events_without_an_acknowledgement_are_skipped(self, temp_dir):
        d = _run(temp_dir, "r3", [1.0])
        with (d / "producer.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["event_id", "t_broker_ack_ns"])
            w.writeheader()
            w.writerow({"event_id": "e0", "t_broker_ack_ns": "None"})
        assert run_inversion(str(d)) == (0, 0)

    def test_malformed_rows_do_not_crash(self, temp_dir):
        d = _run(temp_dir, "r4", [1.0])
        (d / "consumer_events.csv").write_text(
            "event_id,t_consume_ns\ne0,notanumber\n", encoding="utf-8")
        assert run_inversion(str(d)) == (0, 0)

    def test_events_without_a_receive_stamp_are_skipped(self, temp_dir):
        d = _run(temp_dir, "r5", [1.0])
        (d / "consumer_events.csv").write_text(
            "event_id,t_consume_ns\ne0,None\n", encoding="utf-8")
        assert run_inversion(str(d)) == (0, 0)


class TestRunTransportMedian:
    def test_median_of_the_values(self, temp_dir):
        d = _run(temp_dir, "t1", [1.0, 2.0, 9.0])
        assert run_transport_median(str(d)) == pytest.approx(2.0)

    def test_missing_files_is_none(self, temp_dir):
        d = temp_dir / "gone"
        d.mkdir()
        assert run_transport_median(str(d)) is None

    def test_no_joinable_events_is_none(self, temp_dir):
        d = _run(temp_dir, "t2", [])
        assert run_transport_median(str(d)) is None

    def test_unacknowledged_events_are_skipped(self, temp_dir):
        d = _run(temp_dir, "t3", [1.0])
        (d / "producer.csv").write_text(
            "event_id,t_broker_ack_ns\ne0,None\n", encoding="utf-8")
        assert run_transport_median(str(d)) is None

    def test_malformed_rows_are_none_not_a_crash(self, temp_dir):
        d = _run(temp_dir, "t4", [1.0])
        (d / "consumer_events.csv").write_text(
            "event_id,t_consume_ns\ne0,notanumber\n", encoding="utf-8")
        assert run_transport_median(str(d)) is None


class TestTagParsers:
    @pytest.mark.parametrize("name,expected", [("d0", 0.0), ("d20", 20.0), ("d50", 50.0)])
    def test_delay_from_tag(self, name, expected):
        assert delay_from_tag(f"/x/{name}") == expected

    def test_delay_from_tag_none(self):
        assert delay_from_tag("/x/callback") is None

    @pytest.mark.parametrize("name,expected", [("n1", 1), ("n12", 12)])
    def test_n_from_tag(self, name, expected):
        assert n_from_tag(f"/x/{name}") == expected

    def test_n_from_tag_none(self):
        assert n_from_tag("/x/bgfoo") is None


class TestConditionLevel:
    def test_timestamp_and_pooled_inversion(self, temp_dir):
        cond, runs = _condition(temp_dir, "eb", "d20", "n5_20260723_094017",
                                {"kafka": [1.0, -1.0]})
        assert condition_timestamp(str(cond)) == "n5_20260723_094017"
        assert condition_inversion(str(cond), str(runs)) == pytest.approx(0.5)

    def test_inversion_none_without_timestamp(self, temp_dir):
        d = temp_dir / "bare"
        d.mkdir()
        assert condition_inversion(str(d), str(temp_dir)) is None

    def test_inversion_none_when_no_events(self, temp_dir):
        cond, runs = _condition(temp_dir, "eb", "d0", "n5_20260723_000000", {"kafka": []})
        assert condition_inversion(str(cond), str(runs)) is None

    def test_transport_by_backend(self, temp_dir):
        cond, runs = _condition(temp_dir, "ec2", "callback", "n5_20260723_101112",
                                {"kafka": [0.6], "redis": [0.2]})
        t = condition_transport_by_backend(str(cond), str(runs))
        assert t["kafka"] == pytest.approx(0.6) and t["redis"] == pytest.approx(0.2)

    def test_transport_empty_without_timestamp(self, temp_dir):
        d = temp_dir / "bare2"
        d.mkdir()
        assert condition_transport_by_backend(str(d), str(temp_dir)) == {}

    def test_timestamp_skips_subdirs_that_do_not_carry_a_run_id(self, temp_dir):
        """The stray is created first so the scan must walk past it, not stop at it."""
        cond = temp_dir / "depth" / "eb" / "d0"
        (cond / "concurrency_concurrency_aborted").mkdir(parents=True)
        (cond / "concurrency_concurrency_n5_20260723_133000").mkdir()
        assert condition_timestamp(str(cond)) == "n5_20260723_133000"

    def test_inversion_ignores_stray_files_next_to_the_runs(self, temp_dir):
        cond, runs = _condition(temp_dir, "eb", "d0", "n5_20260723_140000", {"kafka": [1.0, -1.0]})
        (runs / "concurrency_n5_20260723_140000_kafka.log").write_text("x", encoding="utf-8")
        assert condition_inversion(str(cond), str(runs)) == pytest.approx(0.5)

    def test_transport_ignores_stray_files_and_unjoinable_runs(self, temp_dir):
        ts = "n5_20260723_150000"
        cond, runs = _condition(temp_dir, "ec2", "inline", ts, {"kafka": [0.6], "redis": [0.2]})
        (runs / f"concurrency_{ts}_kafka_feed2.log").write_text("x", encoding="utf-8")
        (runs / f"concurrency_{ts}_redis_feed2_rep1").mkdir()  # no CSVs: yields None
        t = condition_transport_by_backend(str(cond), str(runs))
        assert t["kafka"] == pytest.approx(0.6) and t["redis"] == pytest.approx(0.2)

    def test_median_rho(self, temp_dir):
        cond, _ = _condition(temp_dir, "ea_sat", "bg4", "n5_20260723_120000",
                             {"kafka": [1.0]}, rho=[0.2, 0.6, 0.4])
        assert median_rho(str(cond)) == pytest.approx(0.4)

    def test_median_rho_missing_file(self, temp_dir):
        d = temp_dir / "norho"
        d.mkdir()
        assert median_rho(str(d)) is None

    def test_median_rho_unparseable(self, temp_dir):
        d = temp_dir / "badrho"
        d.mkdir()
        (d / "utilisation.csv").write_text("t_wall,rho,loadavg\n1,xx,1\n", encoding="utf-8")
        assert median_rho(str(d)) is None


class TestCollect:
    def test_gathers_all_three_tables(self, temp_dir):
        _condition(temp_dir, "eb", "d0", "n5_20260101_000001", {"kafka": [1.0, -1.0]})
        _condition(temp_dir, "eb", "d20", "n5_20260101_000002", {"kafka": [1.0, 1.0]})
        _condition(temp_dir, "ea_sat", "bg0", "n5_20260101_000003",
                   {"kafka": [1.0, -1.0]}, rho=0.5)
        _condition(temp_dir, "ea2", "n3", "n3_20260101_000004", {"kafka": [-1.0, 1.0]})
        eb, ea, ea2 = collect(str(temp_dir / "depth"), str(temp_dir / "runs"))
        assert sorted(r["t_true_ms"] for r in eb) == [0.0, 20.0]
        assert ea and ea[0]["rho"] == pytest.approx(0.5)
        assert ea2 and ea2[0]["n_feeds"] == 3

    def test_ea_sat_supersedes_ea(self, temp_dir):
        """The pinned original ea phase is diluted by core pinning; ea_sat must win."""
        _condition(temp_dir, "ea", "c1_b0", "n5_20260101_000010", {"kafka": [1.0]}, rho=0.1)
        _condition(temp_dir, "ea_sat", "bg8", "n5_20260101_000011", {"kafka": [-1.0]}, rho=0.9)
        _, ea, _ = collect(str(temp_dir / "depth"), str(temp_dir / "runs"))
        assert [r["rho"] for r in ea] == [pytest.approx(0.9)]

    def test_falls_back_to_ea_when_no_saturation_sweep(self, temp_dir):
        _condition(temp_dir, "ea", "c1_b0", "n5_20260101_000020", {"kafka": [1.0]}, rho=0.1)
        _, ea, _ = collect(str(temp_dir / "depth"), str(temp_dir / "runs"))
        assert [r["rho"] for r in ea] == [pytest.approx(0.1)]

    def test_pools_knee_with_saturation(self, temp_dir):
        _condition(temp_dir, "ea_sat", "bg8", "n5_20260101_000030", {"kafka": [-1.0]}, rho=0.9)
        _condition(temp_dir, "ea_knee", "bg6", "n5_20260101_000031", {"kafka": [1.0]}, rho=0.75)
        _, ea, _ = collect(str(temp_dir / "depth"), str(temp_dir / "runs"))
        assert sorted(round(r["rho"], 2) for r in ea) == [0.75, 0.9]

    def test_conditions_without_data_are_dropped(self, temp_dir):
        _condition(temp_dir, "eb", "d0", "n5_20260101_000040", {"kafka": []})
        eb, _, _ = collect(str(temp_dir / "depth"), str(temp_dir / "runs"))
        assert eb == []

    def test_utilisation_condition_without_rho_is_dropped(self, temp_dir):
        """A saturation condition whose sampler trace is missing cannot enter the H2 fit."""
        _condition(temp_dir, "ea_sat", "bg4", "n5_20260101_000050", {"kafka": [1.0, -1.0]})
        _, ea, _ = collect(str(temp_dir / "depth"), str(temp_dir / "runs"))
        assert ea == []

    def test_non_directories_in_a_utilisation_phase_are_ignored(self, temp_dir):
        _condition(temp_dir, "ea_sat", "bg0", "n5_20260101_000060", {"kafka": [1.0]}, rho=0.1)
        (temp_dir / "depth" / "ea_sat" / "sweep.log").write_text("x", encoding="utf-8")
        _, ea, _ = collect(str(temp_dir / "depth"), str(temp_dir / "runs"))
        assert len(ea) == 1

    def test_process_count_condition_without_events_is_dropped(self, temp_dir):
        _condition(temp_dir, "ea2", "n3", "n3_20260101_000070", {"kafka": []})
        _, _, ea2 = collect(str(temp_dir / "depth"), str(temp_dir / "runs"))
        assert ea2 == []


class TestMain:
    """The driver that prints the H1/H2/H3/H4 verdicts."""

    @staticmethod
    def _full_corpus(tmp):
        # H1: inversion falls as the injected delay grows.
        for i, (tag, ts, vals) in enumerate([
                ("d0", "n5_20260101_100000", [-1.0, -1.0, -1.0, 1.0]),
                ("d5", "n5_20260101_100001", [-1.0, 1.0, 1.0, 1.0]),
                ("d50", "n5_20260101_100002", [1.0, 1.0, 1.0, 1.0])]):
            _condition(tmp, "eb", tag, ts, {"kafka": vals})
        # H2: inversion rises with utilisation.
        for tag, ts, vals, rho in [
                ("bg0", "n5_20260101_110000", [1.0, 1.0, 1.0, 1.0], 0.1),
                ("bg4", "n5_20260101_110001", [-1.0, 1.0, 1.0, 1.0], 0.5),
                ("bg8", "n5_20260101_110002", [-1.0, -1.0, -1.0, 1.0], 0.95)]:
            _condition(tmp, "ea_sat", tag, ts, {"kafka": vals}, rho=rho)
        # H4: inversion rises with process count.
        for tag, ts, vals in [
                ("n1", "n1_20260101_120000", [1.0, 1.0, 1.0, 1.0]),
                ("n3", "n3_20260101_120001", [-1.0, 1.0, 1.0, 1.0]),
                ("n6", "n6_20260101_120002", [-1.0, -1.0, 1.0, 1.0])]:
            _condition(tmp, "ea2", tag, ts, {"kafka": vals})
        # H3: both stamping modes, two backends each.
        for mode, ts in [("callback", "n5_20260101_130000"), ("inline", "n5_20260101_130001")]:
            _condition(tmp, "ec3", mode, ts, {"kafka": [0.6], "redis": [0.2]})
        return ["--depth-dir", str(tmp / "depth"), "--runs-dir", str(tmp / "runs"),
                "--out", str(tmp / "model")]

    def test_reports_every_hypothesis(self, temp_dir, capsys):
        from analyze_depth import main
        assert main(self._full_corpus(temp_dir)) == 0
        out = capsys.readouterr().out
        for token in ("H1 effect-size rule", "H2 utilisation rule",
                      "H4 oversubscription rule", "H3 stamping rule"):
            assert token in out, token
        assert (temp_dir / "model" / "eb_effect_size.csv").exists()
        assert (temp_dir / "model" / "ea_utilisation.csv").exists()
        assert (temp_dir / "model" / "ea2_process_count.csv").exists()

    def test_h1_direction_is_reported_correctly(self, temp_dir, capsys):
        from analyze_depth import main
        main(self._full_corpus(temp_dir))
        out = capsys.readouterr().out
        h1 = [ln for ln in out.splitlines() if ln.startswith("H1")][0]
        assert "SUPPORTED" in h1 and "NOT SUPPORTED" not in h1

    def test_a_stamping_mode_with_only_one_backend_is_not_compared(self, temp_dir, capsys):
        """H3 needs both backends in the same mode; a half-finished mode must not be reported."""
        from analyze_depth import main
        _condition(temp_dir, "ec3", "callback", "n5_20260101_140000",
                   {"kafka": [0.6], "redis": [0.2]})
        _condition(temp_dir, "ec3", "inline", "n5_20260101_140001", {"kafka": [0.6]})
        main(["--depth-dir", str(temp_dir / "depth"), "--runs-dir", str(temp_dir / "runs"),
              "--out", str(temp_dir / "model")])
        out = capsys.readouterr().out
        assert "callback" in out
        assert "H3 stamping rule" not in out

    def test_h3_is_supported_when_the_symmetric_stamp_shrinks_the_gap(self, temp_dir, capsys):
        from analyze_depth import main
        _condition(temp_dir, "ec3", "callback", "n5_20260101_150000",
                   {"kafka": [0.60], "redis": [0.20]})
        _condition(temp_dir, "ec3", "inline", "n5_20260101_150001",
                   {"kafka": [0.25], "redis": [0.20]})
        main(["--depth-dir", str(temp_dir / "depth"), "--runs-dir", str(temp_dir / "runs"),
              "--out", str(temp_dir / "model")])
        out = capsys.readouterr().out
        assert "E-C3" in out
        assert "H3 stamping rule: SUPPORTED" in out
        assert "calling thread" in out
        # A supported H3 is persisted for the paper to pin against.
        import csv as _csv
        rows = list(_csv.DictReader(open(temp_dir / "model" / "ec3_stamping.csv")))
        assert [r["stamp"] for r in rows] == ["callback", "inline"]
        assert float(rows[0]["difference_ms"]) == pytest.approx(0.40)
        assert float(rows[1]["difference_ms"]) == pytest.approx(0.05)

    def test_h3_is_not_supported_when_the_gap_survives_the_symmetric_stamp(self, temp_dir,
                                                                          capsys):
        from analyze_depth import main
        _condition(temp_dir, "ec3", "callback", "n5_20260101_160000",
                   {"kafka": [0.60], "redis": [0.20]})
        _condition(temp_dir, "ec3", "inline", "n5_20260101_160001",
                   {"kafka": [0.90], "redis": [0.20]})
        main(["--depth-dir", str(temp_dir / "depth"), "--runs-dir", str(temp_dir / "runs"),
              "--out", str(temp_dir / "model")])
        assert "H3 stamping rule: NOT SUPPORTED" in capsys.readouterr().out
        # The measurement is persisted whatever the verdict -- it is data, not confirmation.
        rows = list(csv.DictReader(open(temp_dir / "model" / "ec3_stamping.csv")))
        assert float(rows[1]["difference_ms"]) > float(rows[0]["difference_ms"])

    def test_the_old_asymmetric_pair_is_reported_as_untested(self, temp_dir, capsys):
        """ec2 compared two callback-stamping clients, so no verdict is available from it."""
        from analyze_depth import main
        _condition(temp_dir, "ec2", "callback", "n5_20260101_170000",
                   {"kafka": [0.60], "redis": [0.20]})
        _condition(temp_dir, "ec2", "inline", "n5_20260101_170001",
                   {"kafka": [0.25], "redis": [0.20]})
        main(["--depth-dir", str(temp_dir / "depth"), "--runs-dir", str(temp_dir / "runs"),
              "--out", str(temp_dir / "model")])
        out = capsys.readouterr().out
        assert "E-C2" in out and "untested" in out
        assert "SUPPORTED" not in out

    def test_ec3_supersedes_ec2_when_both_are_present(self, temp_dir, capsys):
        from analyze_depth import main
        _condition(temp_dir, "ec2", "callback", "n5_20260101_180000",
                   {"kafka": [9.0], "redis": [0.2]})
        _condition(temp_dir, "ec2", "inline", "n5_20260101_180001",
                   {"kafka": [9.0], "redis": [0.2]})
        _condition(temp_dir, "ec3", "callback", "n5_20260101_180002",
                   {"kafka": [0.60], "redis": [0.20]})
        _condition(temp_dir, "ec3", "inline", "n5_20260101_180003",
                   {"kafka": [0.25], "redis": [0.20]})
        main(["--depth-dir", str(temp_dir / "depth"), "--runs-dir", str(temp_dir / "runs"),
              "--out", str(temp_dir / "model")])
        out = capsys.readouterr().out
        assert "E-C3" in out and "E-C2" not in out
        assert "kafka 0.600" in out          # the ec3 numbers, not the ec2 decoys

    def test_returns_one_when_there_is_nothing_to_fit(self, temp_dir, capsys):
        from analyze_depth import main
        (temp_dir / "depth").mkdir()
        assert main(["--depth-dir", str(temp_dir / "depth"),
                     "--runs-dir", str(temp_dir / "runs"),
                     "--out", str(temp_dir / "m")]) == 1
        assert "insufficient data" in capsys.readouterr().out
