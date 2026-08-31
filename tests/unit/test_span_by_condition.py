"""Tests for scripts/span_by_condition.py.

The script's three jobs each get their own class: the S = D - A decomposition per condition,
the gate split that lets the recovery estimator be scored on the rejected population, and the
disease ladder whose top rung must reproduce the sign check exactly (over_1 == neg_ack).
"""
import csv
import io
import json
import os
import sys
import tarfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import span_by_condition as sbc  # noqa: E402


RUN = "concurrency_n2_20260101_000000_kafka_feed1_rep1"


@pytest.fixture(autouse=True)
def fresh_ratio_hist():
    """The pooled ratio histogram is module state; each test starts it empty."""
    sbc.RATIO_HIST.clear()
    yield
    sbc.RATIO_HIST.clear()


def prod_rows(events):
    return [{"event_id": e, "t_prod_send_ns": s, "t_broker_ack_ns": a}
            for e, (s, a, _r) in events.items()]


def cons_rows(events):
    return [{"event_id": e, "t_cons_recv_ns": r} for e, (_s, _a, r) in events.items()]


def clean_event(eid="e1"):
    """send 1 ms, ack 1.6 ms, recv 2.2 ms: S=+0.6 ms, D=+1.2 ms, A=+0.6 ms."""
    return {eid: (1_000_000, 1_600_000, 2_200_000)}


def inverted_event(eid="e2"):
    """ack after recv: S negative."""
    return {eid: (1_000_000, 9_000_000, 4_500_000)}


class TestConditionOf:
    def test_a_campaign_run_id_maps_to_backend_senders_feed(self):
        assert sbc.condition_of(RUN) == "kafka_n2_feed1"

    def test_a_foreign_run_id_is_declined(self):
        assert sbc.condition_of("mechanism_ea9_rep1") is None


class TestAdd:
    def test_in_window_under_and_over_each_take_their_branch(self):
        acc = sbc.new_cond()["S"]
        sbc.add(acc, 0.0)
        sbc.add(acc, sbc.BIN_LO_US - 1)
        sbc.add(acc, sbc.BIN_HI_US)
        assert (acc["n"], acc["under"], acc["over"]) == (3, 1, 1)
        assert sum(acc["bins"].values()) == 1


class TestConsumeRun:
    def test_a_clean_run_lands_in_the_pass_bucket(self):
        conds, rr = {}, []
        ev = clean_event()
        n = sbc.consume_run(conds, rr, RUN, prod_rows(ev), cons_rows(ev))
        assert n == 1
        assert list(conds) == ["kafka_n2_feed1#pass"]
        assert rr[0]["gate"] == "pass"

    def test_one_negative_in_two_events_fails_the_one_percent_gate(self):
        conds, rr = {}, []
        ev = {**clean_event("a"), **inverted_event("b")}
        sbc.consume_run(conds, rr, RUN, prod_rows(ev), cons_rows(ev))
        assert list(conds) == ["kafka_n2_feed1#fail"]

    def test_a_negative_median_fails_the_gate_on_its_own(self):
        """Both events inverted: the median of S is negative, which is the gate's second
        criterion, and the rate criterion would have caught it too -- so drive the median
        clause alone with a run that is all negatives."""
        conds, rr = {}, []
        ev = {**inverted_event("a"), **inverted_event("b")}
        sbc.consume_run(conds, rr, RUN, prod_rows(ev), cons_rows(ev))
        assert rr[0]["gate"] == "fail"

    def test_the_ladder_top_rung_equals_the_sign_check(self):
        conds, rr = {}, []
        ev = {**clean_event("a"), **inverted_event("b")}
        sbc.consume_run(conds, rr, RUN, prod_rows(ev), cons_rows(ev))
        assert rr[0]["over_1"] == rr[0]["neg_ack"] == 1

    def test_an_event_outside_the_window_is_counted_not_dropped(self):
        """The paired sums for rho(D, A) are taken on the same +-100 ms window as every
        median beside them, so a pair outside it must be excluded -- and counted.

        Silently dropping samples is the failure this paper documents; the accumulator that
        measures it does not get to do it. Here delivery is 0.5 s, far outside the window,
        so `outside` takes the event and the six co-moment sums do not.
        """
        conds, rr = {}, []
        far = {"far": (1_000_000, 1_600_000, 501_000_000)}
        sbc.consume_run(conds, rr, RUN, prod_rows({**clean_event("a"), **far}),
                        cons_rows({**clean_event("a"), **far}))
        pair = next(iter(conds.values()))["pair"]
        assert pair["outside"] == 1
        assert pair["n"] == 1                      # only the clean event
        assert rr[0]["n_events"] == 2              # both still counted as events

    def test_a_foreign_run_id_contributes_nothing(self):
        conds, rr = {}, []
        ev = clean_event()
        assert sbc.consume_run(conds, rr, "other_run", prod_rows(ev), cons_rows(ev)) == 0

    def test_a_run_with_no_joinable_events_contributes_nothing(self):
        conds, rr = {}, []
        ev = clean_event()
        cons = [{"event_id": "ghost", "t_cons_recv_ns": 1}]
        assert sbc.consume_run(conds, rr, RUN, prod_rows(ev), cons) == 0

    def test_mangled_rows_on_either_side_are_skipped(self):
        conds, rr = {}, []
        prod = prod_rows(clean_event()) + [{"event_id": "bad", "t_prod_send_ns": "x",
                                            "t_broker_ack_ns": 1}]
        cons = cons_rows(clean_event()) + [{"event_id": "bad", "t_cons_recv_ns": "y"},
                                           {"event_id": "e1", "t_cons_recv_ns": "z"}]
        assert sbc.consume_run(conds, rr, RUN, prod, cons) == 1

    def test_a_nonpositive_delivery_is_kept_out_of_the_ratio(self):
        """recv == send makes D zero; the ratio A/D is then undefined and the event must not
        enter the ladder, while still entering the histograms."""
        conds, rr = {}, []
        ev = {"z": (1_000_000, 1_600_000, 1_000_000)}
        sbc.consume_run(conds, rr, RUN, prod_rows(ev), cons_rows(ev))
        assert rr[0]["over_0.1"] == 0
        assert sum(sbc.RATIO_HIST.values()) == 0


class TestMsDeleted:
    def test_the_guard_fires_on_same_tick_and_inverted_events(self):
        ev = {**clean_event("a"), **inverted_event("b")}
        index = {e: (s, a) for e, (s, a, _r) in ev.items()}
        rows = cons_rows(ev)
        fired = [sbc._ms_deleted(r, index) for r in rows]
        assert fired == [False, True]

    def test_an_unjoined_or_mangled_row_does_not_fire(self):
        assert sbc._ms_deleted({"event_id": "ghost"}, {}) is False
        assert sbc._ms_deleted({"event_id": "a", "t_cons_recv_ns": "x"},
                               {"a": (1, 2)}) is False


class TestRatioHist:
    def test_a_nonpositive_ratio_takes_the_labelled_key(self):
        sbc.ratio_hist_add(-0.5)
        assert sbc.RATIO_HIST == {"nonpos": 1}

    def test_extremes_are_clamped_to_the_edge_bins(self):
        sbc.ratio_hist_add(1e9)
        sbc.ratio_hist_add(1e-9)
        assert set(sbc.RATIO_HIST) == {30, -30}

    def test_a_ratio_of_one_lands_in_bin_zero(self):
        sbc.ratio_hist_add(1.0)
        assert sbc.RATIO_HIST == {0: 1}


def make_archive(path, runs):
    def as_csv(rows, fields):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
        return buf.getvalue().encode("utf-8")
    with tarfile.open(path, "w:gz") as tf:
        d = tarfile.TarInfo("runs/dir")
        d.type = tarfile.DIRTYPE
        tf.addfile(d)
        for name, body in (("stray.txt", b"x"),):
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tf.addfile(info, io.BytesIO(body))
        for run_id, ev in runs.items():
            for name, body in (
                ("runs/%s/producer.csv" % run_id,
                 as_csv(prod_rows(ev), ["event_id", "t_prod_send_ns", "t_broker_ack_ns"])),
                ("runs/%s/consumer.csv" % run_id,
                 as_csv(cons_rows(ev), ["event_id", "t_cons_recv_ns"])),
                ("runs/%s/notes.log" % run_id, b"ignored"),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tf.addfile(info, io.BytesIO(body))


class TestScanAndOutputs:
    def test_the_archive_scan_splits_by_gate_and_writes_both_artefacts(self, tmp_path,
                                                                        monkeypatch, capsys):
        arc = tmp_path / "a.tgz"
        make_archive(str(arc), {
            RUN: clean_event(),
            RUN.replace("rep1", "rep2"): {**clean_event("a"), **inverted_event("b")},
        })
        monkeypatch.setattr(sbc, "OUT_JSON", str(tmp_path / "o.json"))
        monkeypatch.setattr(sbc, "OUT_CSV", str(tmp_path / "o.csv"))
        rc = sbc.main(["--archive", str(arc), "--progress", "1"])
        assert rc == 0
        data = json.load(open(tmp_path / "o.json"))
        assert set(data["conditions"]) == {"kafka_n2_feed1#pass", "kafka_n2_feed1#fail"}
        assert data["alphas"] == list(sbc.ALPHAS)
        rows = list(csv.DictReader(open(tmp_path / "o.csv")))
        assert {r["gate"] for r in rows} == {"pass", "fail"}
        assert "wrote" in capsys.readouterr().out

    def test_a_member_the_tar_declines_to_open_is_skipped(self, tmp_path, monkeypatch):
        arc = tmp_path / "a.tgz"
        make_archive(str(arc), {RUN: clean_event()})
        real = tarfile.TarFile.extractfile

        def declines(self, member):
            if "consumer" in member.name:
                return None
            return real(self, member)
        monkeypatch.setattr(tarfile.TarFile, "extractfile", declines)
        conds, rows, runs, events = sbc.scan_archive(str(arc))
        assert runs == 0

    def test_a_parseable_run_with_a_foreign_id_is_flushed_but_uncounted(self, tmp_path):
        """Both halves parse, but condition_of declines the run id: consume_run returns 0
        and the run must not bump the counters."""
        arc = tmp_path / "a.tgz"
        make_archive(str(arc), {"mechanism_ea9_rep1": clean_event()})
        conds, rows, runs, events = sbc.scan_archive(str(arc), progress=0)
        assert runs == 0 and conds == {}

    def test_a_progress_stride_larger_than_the_run_count_stays_quiet(self, tmp_path, capsys):
        arc = tmp_path / "a.tgz"
        make_archive(str(arc), {RUN: clean_event()})
        conds, rows, runs, events = sbc.scan_archive(str(arc), progress=5)
        assert runs == 1
        assert "runs," not in capsys.readouterr().err

    def test_an_empty_half_is_skipped_at_flush(self, tmp_path):
        arc = tmp_path / "a.tgz"
        with tarfile.open(str(arc), "w:gz") as tf:
            for name, body in (("runs/r/producer.csv", b"event_id\n"),
                               ("runs/r/consumer.csv", b"event_id\n")):
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tf.addfile(info, io.BytesIO(body))
        conds, rows, runs, events = sbc.scan_archive(str(arc), progress=0)
        assert runs == 0 and rows == []
