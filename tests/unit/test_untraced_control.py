"""Tests for scripts/untraced_control.py: the E-A9 untraced twin's two cells."""
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import untraced_control as uc  # noqa: E402

S = 10**9


def _write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _cell(depth, runs, name, ts, rho, spans_ms, late_first=0):
    """One condition of the twin: its utilisation, its campaign folder, and one Kafka run.

    Message i is published at i seconds and acknowledged 1 ms later; spans_ms[i] is S. The
    first `late_first` messages instead arrive together half a second after the last of them
    was published, as behind a stale backlog, before the next one is published.
    """
    cond = depth / uc.PHASE / name
    _write(cond / "utilisation.csv", ("rho",), [(rho,), (rho,)])
    (cond / ("concurrency_concurrency_%s" % ts)).mkdir(parents=True)
    run = runs / ("concurrency_%s_kafka_feed1_rep1" % ts)
    prod, cons, events = [], [], []
    burst = int((late_first - 0.5) * S)
    for i, s in enumerate(spans_ms):
        send, ack = i * S, i * S + 1_000_000
        recv = burst if i < late_first else ack + int(s * 1e6)
        prod.append(("e%d" % i, send, ack))
        cons.append(("e%d" % i, recv))
        events.append(("e%d" % i, recv))
    _write(run / "producer.csv", ("event_id", "t_prod_send_ns", "t_broker_ack_ns"), prod)
    _write(run / "consumer.csv", ("event_id", "t_cons_recv_ns"), cons)
    _write(run / "consumer_events.csv", ("event_id", "t_consume_ns"), events)


def _twin(tmp_path):
    depth, runs = tmp_path / "depth", tmp_path / "runs"
    _cell(depth, runs, "l88_base", "n5_20260101_000001", 0.881194, [-0.2, 1.0, 1.0, 1.0],
          late_first=2)
    _cell(depth, runs, "l88_rt", "n5_20260101_000002", 0.880888, [1.0, 1.0, -0.1, 1.0])
    return depth, runs


class TestTheCells:

    def test_two_cells_without_their_late_messages(self, tmp_path):
        depth, runs = _twin(tmp_path)
        rows = uc.control_rows(str(depth), str(runs))
        assert [r["condition"] for r in rows] == ["l88_base", "l88_rt"]
        base, rt = rows
        # The base cell's first two messages waited behind a backlog and are left out; one of
        # them would have been the cell's only value below zero.
        assert (base["n_events"], base["n_inversions"], base["n_runs"]) == (2, 0, 1)
        assert (rt["n_events"], rt["n_inversions"], rt["inversion_rate"]) == (4, 1, 0.25)
        assert base["rho"] == 0.88119 and rt["rho"] == 0.88089

    def test_a_cell_without_utilisation_or_runs_is_skipped(self, tmp_path):
        depth, runs = _twin(tmp_path)
        (depth / uc.PHASE / "l75_base").mkdir()
        (depth / uc.PHASE / "notes.txt").write_text("not a cell", encoding="utf-8")
        _write(depth / uc.PHASE / "l60_base" / "utilisation.csv", ("rho",), [(0.6,)])
        rows = uc.control_rows(str(depth), str(runs))
        assert [r["condition"] for r in rows] == ["l88_base", "l88_rt"]


class TestTheCommandLine:

    def test_it_writes_the_table(self, tmp_path):
        depth, runs = _twin(tmp_path)
        out = tmp_path / "model" / "ea9_notrace" / "untraced_control.csv"
        assert uc.main(["--depth-dir", str(depth), "--runs-dir", str(runs),
                        "--out", str(out)]) == 0
        rows = list(csv.DictReader(open(out, encoding="utf-8")))
        assert list(rows[0]) == list(uc.FIELDS) and len(rows) == 2

    def test_it_refuses_anything_but_two_cells(self, tmp_path, capsys):
        depth, runs = _twin(tmp_path)
        _cell(depth, runs, "l95_base", "n5_20260101_000003", 0.95, [1.0, 1.0])
        out = tmp_path / "c.csv"
        assert uc.main(["--depth-dir", str(depth), "--runs-dir", str(runs),
                        "--out", str(out)]) == 1
        assert "refusing" in capsys.readouterr().out and not out.exists()

    def test_a_bare_filename_needs_no_folder(self, tmp_path, monkeypatch):
        depth, runs = _twin(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert uc.main(["--depth-dir", str(depth), "--runs-dir", str(runs),
                        "--out", "control.csv"]) == 0
        assert (tmp_path / "control.csv").exists()


class TestTheCommittedTable:

    def test_it_holds_the_twin_without_its_late_messages(self):
        """7 Oct 2026: the normal-priority cell lost six late messages and no value below
        zero; the real-time cell lost none."""
        rows = {r["condition"]: r for r in csv.DictReader(open(
            REPO / "docs" / "results" / "model" / "ea9_notrace" / "untraced_control.csv",
            encoding="utf-8"))}
        assert (rows["l88_base"]["n_inversions"], rows["l88_base"]["n_events"]) == ("811", "2973")
        assert (rows["l88_rt"]["n_inversions"], rows["l88_rt"]["n_events"]) == ("15", "2985")
