"""Tests for scripts/make_multimatch_plan.py - target >=95% branch coverage."""
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from make_multimatch_plan import read_match_ids, deterministic_jitter, main

COMMIT = "abc123"


def _per_match_plan(root, match_id, n=3, commit=COMMIT):
    d = root / commit / f"match_{match_id}"
    d.mkdir(parents=True)
    pd.DataFrame({
        "row_idx": range(n),
        "match_id": [match_id] * n,
        "event_id": [f"{match_id}-{i}" for i in range(n)],
        "t_sim_seconds": [i * 60 for i in range(n)],
        "t_emit_offset_s": [float(i * 60) for i in range(n)],
    }).to_csv(d / "replay_plan.csv", index=False)
    return d


def _ids_file(tmp, ids):
    p = tmp / "ids.txt"
    p.write_text("\n".join(["# comment", ""] + [str(i) for i in ids]) + "\n", encoding="utf-8")
    return p


class TestReadMatchIds:
    def test_skips_comments_and_blanks(self, temp_dir):
        assert read_match_ids(_ids_file(temp_dir, [1, 2, 3])) == [1, 2, 3]

    def test_empty_file_raises(self, temp_dir):
        p = temp_dir / "empty.txt"
        p.write_text("# only a comment\n", encoding="utf-8")
        with pytest.raises(ValueError):
            read_match_ids(p)


class TestJitter:
    def test_zero_max_gives_zero(self):
        assert deterministic_jitter(1, 42, 0) == 0.0

    def test_deterministic_and_bounded(self):
        a = deterministic_jitter(7, 42, 5.0)
        b = deterministic_jitter(7, 42, 5.0)
        assert a == b and -5.0 <= a <= 5.0

    def test_varies_by_match(self):
        assert deterministic_jitter(1, 42, 5.0) != deterministic_jitter(2, 42, 5.0)


class TestMain:
    def _run(self, temp_dir, extra=None, ids=(1, 2)):
        root = temp_dir / "plans"
        for mid in ids:
            _per_match_plan(root, mid)
        out = temp_dir / "out"
        args = ["--commit", COMMIT, "--match-ids-file", str(_ids_file(temp_dir, list(ids))),
                "--out-dir", str(out), "--speed-factor", "10", "--plans-root", str(root)]
        assert main(args + (extra or [])) == 0
        return out

    def test_merges_and_recomputes_schedule(self, temp_dir):
        out = self._run(temp_dir)
        df = pd.read_csv(out / "combined_plan.csv")
        assert len(df) == 6                       # two matches x three events
        assert set(df["match_id"]) == {1, 2}
        # schedule recomputed as sim time / speed factor (no jitter by default)
        assert df["t_emit_offset_s"].max() == pytest.approx(120 / 10)
        # globally ordered by emission time
        assert list(df["t_emit_offset_s"]) == sorted(df["t_emit_offset_s"])
        assert list(df["global_seq"]) == list(range(len(df)))

    def test_meta_records_provenance(self, temp_dir):
        out = self._run(temp_dir)
        meta = json.loads((out / "meta.json").read_text())
        assert meta["commit"] == COMMIT and meta["n_matches"] == 2
        assert meta["n_events_total"] == 6 and meta["speed_factor"] == 10.0

    def test_max_events_per_match_truncates(self, temp_dir):
        out = self._run(temp_dir, extra=["--max-events-per-match", "2"])
        assert len(pd.read_csv(out / "combined_plan.csv")) == 4

    def test_kickoff_jitter_shifts_schedule(self, temp_dir):
        out = self._run(temp_dir, extra=["--kickoff-jitter-max-s", "30"])
        meta = json.loads((out / "meta.json").read_text())
        assert any(v != 0 for v in meta["kickoff_offsets_s"].values())

    def test_missing_per_match_plan_raises(self, temp_dir):
        root = temp_dir / "plans"
        _per_match_plan(root, 1)                  # match 2 deliberately absent
        with pytest.raises(FileNotFoundError):
            main(["--commit", COMMIT, "--match-ids-file", str(_ids_file(temp_dir, [1, 2])),
                  "--out-dir", str(temp_dir / "o"), "--speed-factor", "10",
                  "--plans-root", str(root)])

    def test_plan_missing_required_columns_raises(self, temp_dir):
        root = temp_dir / "plans"
        d = root / COMMIT / "match_1"
        d.mkdir(parents=True)
        pd.DataFrame({"row_idx": [0]}).to_csv(d / "replay_plan.csv", index=False)
        with pytest.raises(ValueError):
            main(["--commit", COMMIT, "--match-ids-file", str(_ids_file(temp_dir, [1])),
                  "--out-dir", str(temp_dir / "o"), "--speed-factor", "10",
                  "--plans-root", str(root)])

    def test_parquet_failure_is_not_fatal(self, temp_dir, monkeypatch):
        import make_multimatch_plan as mmp

        def boom(self, *a, **k):
            raise ImportError("no pyarrow")

        monkeypatch.setattr(mmp.pd.DataFrame, "to_parquet", boom)
        out = self._run(temp_dir)
        assert (out / "combined_plan.csv").exists()
        assert json.loads((out / "meta.json").read_text())["outputs"]["combined_plan_parquet"] is None



class TestTheParquetSidecarIsOptional:
    """Both arms forced; see the same class in test_make_replay_plan.py for why."""

    def _run(self, temp_dir, ids=(1, 2)):
        root = temp_dir / "plans"
        for mid in ids:
            _per_match_plan(root, mid)
        out = temp_dir / "out"
        assert main(["--commit", COMMIT, "--match-ids-file",
                     str(_ids_file(temp_dir, list(ids))), "--out-dir", str(out),
                     "--speed-factor", "10", "--plans-root", str(root)]) == 0
        return out

    def test_a_missing_engine_warns_and_still_writes_the_csv(
            self, temp_dir, monkeypatch, capsys):
        def no_engine(self, *a, **k):
            raise ImportError("no pyarrow")
        monkeypatch.setattr(pd.DataFrame, "to_parquet", no_engine)
        out = self._run(temp_dir)
        text = capsys.readouterr().out
        assert "skipped parquet" in text and "ImportError" in text
        assert (out / "combined_plan.csv").exists()
        assert "combined_plan.parquet" not in text, (
            "the summary listed a sidecar that was never written")

    def test_the_sidecar_is_written_and_listed_when_an_engine_is_present(
            self, temp_dir, monkeypatch, capsys):
        """The arm this machine cannot reach on its own."""
        def fake_parquet(self, path, *a, **k):
            Path(path).write_bytes(b"PAR1")
        monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_parquet)
        out = self._run(temp_dir)
        assert (out / "combined_plan.parquet").exists()
        assert "combined_plan.parquet" in capsys.readouterr().out
