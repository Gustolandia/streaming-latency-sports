"""Tests for scripts/a9_decompose.py, on the made-up A9 runs test_helper_waits.py builds -- the
shape the frozen reader was tested on -- and on a few hand-written recordings."""
import csv
import importlib.util
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "scripts"))

import a9_decompose as ad  # noqa: E402

_spec = importlib.util.spec_from_file_location("helper_waits_world",
                                               os.path.join(HERE, "test_helper_waits.py"))
world = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(world)


def recorded(runs, key, setup, rate=0.1, backend="kafka", **shape):
    where = world.run_folder(runs, key, setup, backend=backend, trip=2.0, gotit=0.86, rate=rate)
    world.a9_world(where, **shape)
    return where


def plain(runs, key, setup, rate, backend="kafka"):
    return world.run_folder(runs, key, setup, backend=backend, trip=2.0, gotit=0.86, rate=rate)


class TestTheIdentity:

    def test_a9_2_is_the_waits_a_millisecond_times_the_share_over_times_the_excess(self, tmp_path):
        """A wait a message, every 20 ms; one in ten of 1.5 ms against a margin of 1.14, so
        each outlasts it by 0.36 ms. A9-2b: one in ten acknowledgements."""
        runs = world.campaign(tmp_path)
        recorded(runs, "r001-x", "A9-kafka-l75-s3000-p09s")
        run = ad.helper_waits.counted_runs([str(runs)], ("A9",))[0]
        found = ad.decompose(run)
        assert found["a9_2b"] == pytest.approx(0.1)
        assert found["share_over"] == pytest.approx(0.1, abs=0.002)
        assert found["mean_excess_ms"] == pytest.approx(0.36)
        assert found["waits_per_ms"] == pytest.approx(499 / 9980.0, rel=1e-3)
        assert found["product"] == pytest.approx(found["a9_2"], rel=1e-9)

    def test_a_run_not_read_or_with_no_long_wait_is_not_decomposed(self, tmp_path):
        runs = world.campaign(tmp_path)
        recorded(runs, "r001-x", "A9-kafka-l75-s3000-p09s", slow_every=0)
        run = ad.helper_waits.counted_runs([str(runs)], ("A9",))[0]
        assert ad.decompose(run) is None, "no wait outlasts the margin"
        runs2 = world.campaign(tmp_path, name="two")
        recorded(runs2, "r001-x", "A9-kafka-l75-s3000-p09s", stampers=(201, 202))
        assert ad.decompose(ad.helper_waits.counted_runs([str(runs2)], ("A9",))[0]) is None
        runs3 = world.campaign(tmp_path, name="lost")
        recorded(runs3, "r001-x", "A9-kafka-l75-s3000-p09s", lost=True)
        assert ad.decompose(ad.helper_waits.counted_runs([str(runs3)], ("A9",))[0]) is None

    def test_a_window_of_no_length_is_not_decomposed(self, tmp_path, monkeypatch):
        runs = world.campaign(tmp_path)
        recorded(runs, "r001-x", "A9-kafka-l75-s3000-p09s")
        monkeypatch.setattr(ad, "window_ms", lambda run_dir: 0.0)
        assert ad.decompose(ad.helper_waits.counted_runs([str(runs)], ("A9",))[0]) is None


class TestWaitsByCause:

    def write(self, tmp_path, lines):
        path = tmp_path / "waits.txt"
        path.write_text("Attaching 2 probes...\n" + "\n".join(lines) + "\nnot an event\n",
                        encoding="utf-8")
        return str(path)

    def test_a_wait_is_a_wake_up_or_a_preemption_until_the_thread_runs(self, tmp_path):
        path = self.write(tmp_path, [
            "W 7 1000000", "R 7 3000000",               # first seen woken: waits 2 ms
            "W 7 3500000",                               # woken while running: nothing
            "P 7 4000000", "R 7 4500000",               # preempted: waits 0.5 ms
            "S 7 5000000", "W 7 6000000", "R 7 6100000",  # asleep, woken: waits 0.1 ms
            "R 8 1000", "S 8 2000"])                    # a thread that never waited
        found = ad.waits_by_cause(path)
        assert found == {"wake": [pytest.approx(2.0), pytest.approx(0.1)],
                         "preempt": [pytest.approx(0.5)]}
        assert ad._share(found["wake"], 1.0) == 0.5 and ad._share([], 1.0) is None


class TestTheCampaigns:

    def world(self, tmp_path):
        runs = world.campaign(tmp_path)
        recorded(runs, "r001-a", "A9-kafka-l75-s3000-p09s", rate=0.1)
        plain(runs, "r001-b", "A9-kafka-l75-s3000-p09s", rate=0.04)
        recorded(runs, "r001-c", "A9-kafka-l75-s3000-c04h", rate=0.05)
        plain(runs, "r001-d", "A9-kafka-l75-s3000-c04h", rate=0.0)
        recorded(runs, "r001-e", "A9-kafka-l75-s3000-f2sh", rate=0.0, slow_every=0)
        a3 = world.campaign(tmp_path, name="stage1_a3")
        where = world.run_folder(a3, "r001-z", "A3-kafka-l75-s3000-p09s")
        (where / "runqlat.txt").write_text(world.lhist({0: 90, 1000: 10}), encoding="utf-8")
        world.run_folder(a3, "r002-z", "A3-kafka-l75-s3000-p09s")
        return runs, a3

    def test_every_recorded_run_and_the_recordings_own_effect(self, tmp_path):
        runs, a3 = self.world(tmp_path)
        rows = ad.a9_rows([str(runs)])
        assert len(rows) == 3 and sum(1 for r in rows if "a9_2" in r) == 2
        effect = ad.recording_effect([str(runs)])
        assert effect == {"matched, kafka": [pytest.approx(2.5)]}
        a6 = ad.a6_rows([str(a3)])
        assert a6 == [{"pair": "matched", "backend": "kafka", "run": "law_a3_r001-z",
                       "waits": 100, "over_1ms": pytest.approx(0.1)}]
        a6_effect = ad.recording_effect([str(a3)], ("A1", "A3"), "runqlat.txt")
        assert a6_effect == {"matched, kafka": [pytest.approx(1.0)]}
        found = ad.summary(rows, effect, a6, a6_effect)
        part = found["a9"]["matched, kafka"]
        assert part["runs"] == 3 and part["decomposed"] == 2 and part["identity_holds"] is True
        assert part["recorded_over_unrecorded"] == pytest.approx(2.5)
        assert part["wake_waits"] == 2000 and part["preempt_waits"] == 0, "the whole recording"
        assert found["a6"]["matched, kafka"] == {"runs": 1, "waits": 100,
                                                 "over_1ms": pytest.approx(0.1),
                                                 "recorded_over_unrecorded": pytest.approx(1.0)}

    def test_a_run_without_a_got_it_is_passed_over(self, tmp_path, monkeypatch):
        runs, _ = self.world(tmp_path)
        real = ad.helper_waits.counted_runs
        monkeypatch.setattr(ad.helper_waits, "counted_runs", lambda folders, blocks: [
            dict(run, gotit_ms=None) for run in real(folders, blocks)])
        assert ad.a9_rows([str(runs)]) == []

    def test_medians_of_nothing_are_nothing(self):
        found = ad.summary([{"pair": "p", "backend": "b", "wake_waits": 0, "preempt_waits": 0,
                             "wake_over_1ms": None, "preempt_over_1ms": None}], {}, [])
        assert found["a9"]["p, b"]["a9_2_over_a9_2b"] is None
        assert found["a9"]["p, b"]["recorded_over_unrecorded"] is None


class TestTheCommand:

    def test_it_writes_the_runs_the_histograms_and_the_summary(self, tmp_path, capsys):
        runs, a3 = TestTheCampaigns().world(tmp_path)
        out = tmp_path / "out"
        assert ad.main(["--a9", str(runs), "--a6", str(a3), "--out", str(out)]) == 0
        said = capsys.readouterr().out
        assert "matched, kafka: A9-2/A9-2b" in said and "A6 matched, kafka: 100 waits" in said
        rows = list(csv.DictReader(open(out / "a9_runs.csv", encoding="utf-8")))
        assert len(rows) == 3
        hist = list(csv.DictReader(open(out / "a6_histograms.csv", encoding="utf-8")))
        assert hist[0]["waits"] == "100"
        assert "a9" in json.loads((out / "a9_summary.json").read_text(encoding="utf-8"))

    def test_it_prints_without_writing_and_without_a6(self, tmp_path, capsys):
        runs, _ = TestTheCampaigns().world(tmp_path)
        assert ad.main(["--a9", str(runs)]) == 0
        assert "  A6 " not in capsys.readouterr().out

    def test_no_recorded_run_is_an_error(self, tmp_path, capsys):
        runs = world.campaign(tmp_path)
        plain(runs, "r001-b", "A9-kafka-l75-s3000-p09s", rate=0.04)
        assert ad.main(["--a9", str(runs)]) == 2
        assert "ERROR: no recorded A9 run" in capsys.readouterr().out
