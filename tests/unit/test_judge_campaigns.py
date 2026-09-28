"""Tests for scripts/judge_campaigns.py, the runner every verdict is given by.

The rules are the judge's and are tested where they live (test_law_predictions.py). What is
pinned here is the runner's own promise: each folder is read as its own campaign, the runs the
integrity rule left out are named before the answer, the options reach the judge as the plan
writes them, and a failure is a sentence rather than a traceback.
"""
import json
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import judge_campaigns  # noqa: E402
from judge_campaigns import gather, main, read_back_pairs  # noqa: E402


class FakeCurve:
    """law_curve as the runner uses it: counted() per folder, left_out() over all of them."""

    def __init__(self, by_folder):
        self.by_folder, self.read = by_folder, []

    def counted(self, folder):
        self.read.append(folder)
        return self.by_folder[folder]

    @staticmethod
    def left_out(skipped):
        return ("left out %d run(s): %s" % (len(skipped), ", ".join(r["run"] for r in skipped))
                if skipped else None)


class FakeJudge:
    DRAWS = 2000

    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def judge(self, runs, prediction, tick_ms, draws, seed, read_back=None, anchor_ms=None):
        if self.fail:
            raise self.fail
        self.calls.append({"runs": runs, "prediction": prediction, "tick_ms": tick_ms,
                           "draws": draws, "seed": seed, "read_back": read_back,
                           "anchor_ms": anchor_ms})
        return {"confirmed": True, "runs": len(runs)}

    @staticmethod
    def lines(prediction, found):
        return ["%s: confirmed on %d runs" % (prediction, found["runs"])]


def _patch(monkeypatch, curve, judge):
    monkeypatch.setattr(judge_campaigns, "law_curve", curve)
    monkeypatch.setattr(judge_campaigns, "law_predictions", judge)


def test_read_back_is_a_map_of_core_counts_to_slices():
    assert read_back_pairs("2=1.4,4=2.1,8=2.8") == {2: 1.4, 4: 2.1, 8: 2.8}
    assert read_back_pairs("") == {}


def test_each_folder_is_read_as_its_own_campaign_and_the_left_out_are_named(monkeypatch,
                                                                            capsys):
    curve = FakeCurve({"a/runs": ([{"run": "r1"}], []),
                       "b/runs": ([{"run": "r2"}, {"run": "r3"}], [{"run": "r4"}])})
    _patch(monkeypatch, curve, FakeJudge())
    runs = gather(["a/runs", "b/runs"], sys.stdout)
    assert [r["run"] for r in runs] == ["r1", "r2", "r3"] and curve.read == ["a/runs", "b/runs"]
    out = capsys.readouterr().out
    assert "a/runs: 1 runs counted, 0 left out" in out and "left out 1 run(s): r4" in out


def test_nothing_left_out_says_nothing_about_it(monkeypatch, capsys):
    _patch(monkeypatch, FakeCurve({"a/runs": ([{"run": "r1"}], [])}), FakeJudge())
    gather(["a/runs"], sys.stdout)
    assert "left out 0" not in capsys.readouterr().out.replace("0 left out", "")


def test_the_options_reach_the_judge_as_written_and_the_answer_is_kept(monkeypatch, tmp_path,
                                                                        capsys):
    judge = FakeJudge()
    _patch(monkeypatch, FakeCurve({"a/runs": ([{"run": "r1"}], []),
                                   "b/runs": ([{"run": "r2"}], [])}), judge)
    answer = tmp_path / "p7.json"
    assert main(["P7", "a/runs", "b/runs", "--tick-ms", "4", "--anchor-ms", "3",
                 "--read-back", "2=1.4,8=2.8", "--draws", "50", "--seed", "3",
                 "--out", str(answer)]) == 0
    (call,) = judge.calls
    assert (call["prediction"], call["tick_ms"], call["anchor_ms"], call["draws"],
            call["seed"]) == ("P7", 4.0, 3.0, 50, 3)
    assert call["read_back"] == {2: 1.4, 8: 2.8} and len(call["runs"]) == 2
    assert json.loads(answer.read_text(encoding="utf-8")) == {"confirmed": True, "runs": 2}
    assert "P7: confirmed on 2 runs" in capsys.readouterr().out


def test_the_defaults_are_the_judges(monkeypatch, capsys):
    judge = FakeJudge()
    _patch(monkeypatch, FakeCurve({"a/runs": ([{"run": "r1"}], [])}), judge)
    assert main(["P4", "a/runs"]) == 0
    (call,) = judge.calls
    assert (call["tick_ms"], call["anchor_ms"], call["draws"], call["seed"]) == (
        1.0, None, FakeJudge.DRAWS, 0)
    assert call["read_back"] == {}


def test_a_failure_is_a_sentence_and_a_code(monkeypatch, capsys):
    _patch(monkeypatch, FakeCurve({"a/runs": ([{"run": "r1"}], [])}),
           FakeJudge(fail=ValueError("no rule for P0")))
    assert main(["P0", "a/runs"]) == 2
    assert capsys.readouterr().out.strip().splitlines()[-1] == "ERROR: no rule for P0"


def test_the_real_judge_is_asked_and_answers_in_its_own_words(tmp_path, capsys):
    """Without the fakes: a folder with no run is read as none, and the judge says why it
    cannot answer rather than the runner inventing one."""
    empty = tmp_path / "a1_20260918T194622Z" / "runs"
    empty.mkdir(parents=True)
    code = main(["P9", str(empty)])
    out = capsys.readouterr().out
    assert "0 runs counted, 0 left out" in out
    assert code in (0, 2) and out.strip()
