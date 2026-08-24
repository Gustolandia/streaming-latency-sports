"""Tests for scripts/analyze_knee.py - target >=95% branch coverage.

This decides whether a withdrawn claim is restored, so the bar is set by tests rather than by
whoever reads the output. Both verdicts are pinned, and so is the precondition that the sweep
actually reached the interval where the two forms disagree -- a fit on points below rho=0.9
cannot discriminate no matter how good its R^2 looks.
"""
import csv
import math
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_knee import (  # noqa: E402
    condition_timestamp,
    median_rho,
    condition_inversion,
    collect,
    coverage,
    verdict,
    main,
)

T0 = 1_700_000_000_000_000_000


def _run(runs_dir, run_id, n_events, n_negative):
    d = runs_dir / run_id
    d.mkdir(parents=True, exist_ok=True)
    with (d / "producer.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "t_broker_ack_ns"])
        w.writeheader()
        for i in range(n_events):
            w.writerow({"event_id": f"e{i}", "t_broker_ack_ns": T0})
    with (d / "consumer_events.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "t_consume_ns"])
        w.writeheader()
        for i in range(n_events):
            delta = -1.0 if i < n_negative else 1.0
            w.writerow({"event_id": f"e{i}", "t_consume_ns": T0 + int(delta * 1e6)})
    return d


def _cond(tmp, phase, name, ts, rho, inversion, n_events=200):
    cond = tmp / "depth" / phase / name
    (cond / f"concurrency_concurrency_{ts}").mkdir(parents=True, exist_ok=True)
    _run(tmp / "runs", f"concurrency_{ts}_kafka_feed1_rep1",
         n_events, round(inversion * n_events))
    with (cond / "utilisation.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["t_wall", "rho", "loadavg"])
        w.writeheader()
        w.writerow({"t_wall": 1, "rho": rho, "loadavg": 1.0})
    return cond


def _ladder(tmp, rhos, shape, phase="ea4", scale=0.004):
    """Build conditions whose inversion rate follows a chosen functional form."""
    for i, r in enumerate(rhos):
        y = scale * (r / (1 - r)) if shape == "mg1" else scale * math.exp(4.7 * r)
        y = min(y, 0.49)
        _cond(tmp, phase, f"l{i}", f"n5_2026010{i % 10}_00000{i % 10}", r, y)


class TestPlumbing:
    def test_timestamp_rho_and_inversion(self, temp_dir):
        cond = _cond(temp_dir, "ea4", "l0", "n5_20260101_000000", 0.95, 0.25)
        assert condition_timestamp(str(cond)) == "n5_20260101_000000"
        assert median_rho(str(cond)) == 0.95
        inv = condition_inversion(str(cond), str(temp_dir / "runs"))
        assert inv == {"inversion_rate": 0.25, "n_inversions": 50, "n_events": 200, "n_runs": 1}

    def test_missing_pieces_are_none(self, temp_dir):
        d = temp_dir / "bare"
        d.mkdir()
        assert condition_timestamp(str(d)) is None
        assert median_rho(str(d)) is None
        assert condition_inversion(str(d), str(temp_dir)) is None

    def test_unparseable_rho(self, temp_dir):
        d = temp_dir / "bad"
        d.mkdir()
        (d / "utilisation.csv").write_text("t_wall,rho,loadavg\n1,x,1\n", encoding="utf-8")
        assert median_rho(str(d)) is None

    def test_malformed_run_is_skipped(self, temp_dir):
        cond = _cond(temp_dir, "ea4", "l0", "n5_20260101_000001", 0.9, 0.2)
        run = temp_dir / "runs" / "concurrency_n5_20260101_000001_kafka_feed1_rep1"
        (run / "consumer_events.csv").write_text("event_id,t_consume_ns\ne0,x\n", encoding="utf-8")
        assert condition_inversion(str(cond), str(temp_dir / "runs")) is None


class TestCollect:
    def test_pools_phases_sorted_by_rho(self, temp_dir):
        _cond(temp_dir, "ea3", "bg0", "n5_20260101_000000", 0.25, 0.004)
        _cond(temp_dir, "ea4", "l99", "n5_20260101_000001", 0.98, 0.30)
        rows = collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea3", "ea4"])
        assert [r["rho"] for r in rows] == [0.25, 0.98]
        assert rows[1]["phase"] == "ea4"

    def test_conditions_without_rho_are_dropped(self, temp_dir):
        cond = temp_dir / "depth" / "ea4" / "l0"
        (cond / "concurrency_concurrency_n5_20260101_000000").mkdir(parents=True)
        _run(temp_dir / "runs", "concurrency_n5_20260101_000000_kafka_feed1_rep1", 100, 10)
        assert collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea4"]) == []

    def test_non_directories_ignored(self, temp_dir):
        _cond(temp_dir, "ea4", "l0", "n5_20260101_000000", 0.9, 0.2)
        (temp_dir / "depth" / "ea4" / "notes.txt").write_text("x", encoding="utf-8")
        assert len(collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea4"])) == 1


class TestCoverage:
    def test_detects_reaching_the_interval(self):
        rows = [{"rho": r} for r in (0.5, 0.88, 0.95, 0.98)]
        c = coverage(rows)
        assert c["sufficient"] and c["n_high"] == 2 and c["max_rho"] == 0.98

    def test_detects_not_reaching_it(self):
        c = coverage([{"rho": r} for r in (0.25, 0.5, 0.878)])
        assert not c["sufficient"] and c["n_high"] == 0


class TestVerdict:
    def test_restored_when_mg1_wins_with_high_points(self, temp_dir):
        _ladder(temp_dir, [0.25, 0.5, 0.75, 0.88, 0.95, 0.98], "mg1")
        rows = collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea4"])
        v = verdict(rows)
        assert v["restored"], v["reason"]
        assert "beats the best alternative" in v["reason"]

    def test_withdrawal_stands_when_the_data_is_exponential(self, temp_dir):
        """Data generated FROM an exponential, with coverage above rho=0.90.

        This asserted "indistinguishable" until E-A4 ran. That was too weak: given points where
        the forms diverge, exponential data does not merely fail to support M/G/1, it tells the
        two apart and rules M/G/1 out. The verdict now says so, and the withdrawal still stands
        either way.
        """
        _ladder(temp_dir, [0.25, 0.5, 0.75, 0.88, 0.95, 0.98], "exp")
        rows = collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea4"])
        v = verdict(rows)
        assert not v["restored"] and v["refuted"]
        assert "M/G/1 is the one refuted" in v["reason"]

    def test_cannot_discriminate_without_high_points(self, temp_dir):
        """Even perfectly M/G/1-shaped data below the knee must not restore the claim."""
        _ladder(temp_dir, [0.1, 0.3, 0.5, 0.7, 0.85], "mg1")
        rows = collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea4"])
        v = verdict(rows)
        assert not v["restored"]
        assert "did not reach the interval" in v["reason"]

    def test_saturated_points_are_excluded_from_the_fit(self, temp_dir):
        _ladder(temp_dir, [0.25, 0.5, 0.88, 0.95, 0.98], "mg1")
        _cond(temp_dir, "ea4", "sat", "n5_20260102_000000", 1.0, 0.40)
        rows = collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea4"])
        v = verdict(rows)
        assert v["coverage"]["max_rho"] == 0.98, "rho=1 must not count as coverage"


class TestMain:
    def test_end_to_end_reports_a_verdict(self, temp_dir, capsys):
        _ladder(temp_dir, [0.25, 0.5, 0.75, 0.88, 0.95, 0.98], "mg1")
        rc = main(["--depth-dir", str(temp_dir / "depth"), "--runs-dir", str(temp_dir / "runs"),
                   "--phases", "ea4", "--out", str(temp_dir / "model")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "FUNCTIONAL FORM:" in out and "<- new" in out
        rows = list(csv.DictReader(open(temp_dir / "model" / "knee_resolution.csv")))
        assert len(rows) == 6

    def test_too_few_conditions(self, temp_dir, capsys):
        _cond(temp_dir, "ea4", "l0", "n5_20260101_000000", 0.9, 0.2)
        assert main(["--depth-dir", str(temp_dir / "depth"),
                     "--runs-dir", str(temp_dir / "runs"),
                     "--phases", "ea4", "--out", str(temp_dir / "model")]) == 1
        assert "insufficient conditions" in capsys.readouterr().out


class TestDecisiveLossIsReportedAsRefutation:
    """A wide M/G/1 loss must not be reported as 'indistinguishable'.

    Both outcomes fail the restoration rule, but they are not the same finding. Before E-A4 the
    honest statement was that the sweep could not separate the forms. After it, with points to
    rho=0.99, M/G/1 scored -0.047 against an exponential's 0.934 -- the forms ARE separated and
    M/G/1 is the one that lost. Reporting that as a null would understate the result in our own
    favour, which is the direction most in need of a guard.
    """

    def _rows(self, pairs):
        return [{"phase": "ea4", "condition": f"l{int(r*100)}", "rho": r, "inversion_rate": v}
                for r, v in pairs]

    def test_a_wide_loss_is_flagged_as_refuted(self):
        # Saturating data: rises fast then flattens, which is what E-A4 actually measured.
        pairs = [(0.25, 0.004), (0.50, 0.006), (0.70, 0.111), (0.80, 0.220),
                 (0.88, 0.228), (0.92, 0.240), (0.95, 0.297), (0.99, 0.329)]
        v = verdict(self._rows(pairs))
        assert not v["restored"] and v["refuted"]
        assert "M/G/1 is the one refuted" in v["reason"]
        assert "indistinguishable" not in v["reason"]

    def test_a_narrow_loss_is_still_reported_as_indistinguishable(self):
        """Where the forms genuinely cannot be told apart, the weaker wording is correct.

        Built by averaging an M/G/1 curve and an exponential one, so neither fits well and
        neither loses by much -- the situation the softer sentence was written for.
        """
        import math
        pairs = []
        for r in (0.25, 0.50, 0.70, 0.80, 0.88, 0.92, 0.95, 0.99):
            mg1 = 0.004 * (r / (1 - r))
            expo = 0.004 * math.exp(4.0 * r)
            pairs.append((r, (mg1 + expo) / 2))
        v = verdict(self._rows(pairs))
        assert not v["restored"]
        assert not v["refuted"], f"loss was wider than expected: {v['reason']}"
        assert "indistinguishable" in v["reason"]

    def test_insufficient_coverage_still_takes_priority(self):
        """With nothing above rho=0.90 the sweep cannot speak, whatever the fit says."""
        pairs = [(0.25, 0.004), (0.50, 0.006), (0.70, 0.111), (0.80, 0.220)]
        v = verdict(self._rows(pairs))
        assert not v["restored"] and "did not reach the interval" in v["reason"]


class TestTheRunsAndRowsThatMustBeSteppedOver:
    """The inversion rate is a ratio, so every skip here moves a numerator or a denominator.

    The comment in the script is explicit about the direction of the danger: an event counted
    into the total but lost before it reaches the numerator biases the rate downward, which is
    the direction that flatters the result.
    """

    def test_a_run_missing_one_of_its_two_files_is_stepped_over(self, temp_dir):
        """Interrupted runs leave a producer file and no consumer file, or the reverse."""
        ts = "n5_20260101_000000"
        cond = temp_dir / "depth" / "ea4" / "bg0"
        (cond / f"concurrency_concurrency_{ts}").mkdir(parents=True)
        half = temp_dir / "runs" / f"concurrency_{ts}_kafka_feed1_rep0"
        half.mkdir(parents=True)
        (half / "producer.csv").write_text("event_id,t_broker_ack_ns\n", encoding="utf-8")
        _run(temp_dir / "runs", f"concurrency_{ts}_kafka_feed1_rep1", 200, 20)
        with (cond / "utilisation.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["t_wall", "rho", "loadavg"])
            w.writeheader()
            w.writerow({"t_wall": 1, "rho": 0.5, "loadavg": 1.0})
        got = condition_inversion(str(cond), str(temp_dir / "runs"))
        assert got["n_runs"] == 1, "only the complete run should have been counted"
        assert got["n_events"] == 200
        assert abs(got["inversion_rate"] - 0.1) < 1e-12

    def test_an_unacknowledged_send_leaves_the_event_out_of_both_sides(self, temp_dir):
        """Not out of the numerator alone: that is the bias the script warns about."""
        d = temp_dir / "runs" / "concurrency_n5_20260101_000000_kafka_feed1_rep1"
        d.mkdir(parents=True)
        with (d / "producer.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["event_id", "t_broker_ack_ns"])
            w.writeheader()
            w.writerow({"event_id": "e0", "t_broker_ack_ns": ""})
            w.writerow({"event_id": "e1", "t_broker_ack_ns": T0})
        with (d / "consumer_events.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["event_id", "t_consume_ns"])
            w.writeheader()
            w.writerow({"event_id": "e0", "t_consume_ns": T0 - 1_000_000})
            w.writerow({"event_id": "e1", "t_consume_ns": T0 - 1_000_000})
        cond = temp_dir / "depth" / "ea4" / "bg0"
        (cond / "concurrency_concurrency_n5_20260101_000000").mkdir(parents=True)
        got = condition_inversion(str(cond), str(temp_dir / "runs"))
        assert got["n_events"] == 1, (
            "the unacknowledged event is in neither the numerator nor the total")
        assert got["n_inversions"] == 1
        assert got["inversion_rate"] == 1.0

    def test_a_consumed_event_with_no_ack_is_in_neither_side(self, temp_dir):
        d = temp_dir / "runs" / "concurrency_n5_20260101_000000_kafka_feed1_rep1"
        d.mkdir(parents=True)
        with (d / "producer.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["event_id", "t_broker_ack_ns"])
            w.writeheader()
            w.writerow({"event_id": "e1", "t_broker_ack_ns": T0})
        with (d / "consumer_events.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["event_id", "t_consume_ns"])
            w.writeheader()
            w.writerow({"event_id": "ghost", "t_consume_ns": T0 - 5_000_000})
            w.writerow({"event_id": "e1", "t_consume_ns": T0 + 1_000_000})
        cond = temp_dir / "depth" / "ea4" / "bg0"
        (cond / "concurrency_concurrency_n5_20260101_000000").mkdir(parents=True)
        got = condition_inversion(str(cond), str(temp_dir / "runs"))
        assert (got["n_events"], got["n_inversions"]) == (1, 0)

    def test_a_consumer_row_with_no_stamp_is_in_neither_side(self, temp_dir):
        d = temp_dir / "runs" / "concurrency_n5_20260101_000000_kafka_feed1_rep1"
        d.mkdir(parents=True)
        with (d / "producer.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["event_id", "t_broker_ack_ns"])
            w.writeheader()
            for i in range(2):
                w.writerow({"event_id": f"e{i}", "t_broker_ack_ns": T0})
        with (d / "consumer_events.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["event_id", "t_consume_ns"])
            w.writeheader()
            w.writerow({"event_id": "e0", "t_consume_ns": "None"})
            w.writerow({"event_id": "e1", "t_consume_ns": T0 - 1_000_000})
        cond = temp_dir / "depth" / "ea4" / "bg0"
        (cond / "concurrency_concurrency_n5_20260101_000000").mkdir(parents=True)
        got = condition_inversion(str(cond), str(temp_dir / "runs"))
        assert (got["n_events"], got["n_inversions"]) == (1, 1)
