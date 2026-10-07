"""Tests for scripts/backlog_census.py: the July testbed's two consumer faults, run by run."""
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import backlog_census as bc  # noqa: E402

PROD = ("event_id", "t_prod_send_ns", "t_broker_ack_ns")
CONS = ("event_id", "t_cons_recv_ns")


def _write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _run(root, name, backend, deliveries_ms, published=None, ack_after_ms=0.5, trace=None,
         meta=True, step_s=1.0):
    """A run whose i-th message is published at i steps and received deliveries_ms later."""
    d = root / name
    d.mkdir(parents=True)
    n = len(deliveries_ms) if published is None else published
    step = int(step_s * 1e9)
    prod = [("e%d" % i, i * step, i * step + int(ack_after_ms * 1e6)) for i in range(n)]
    cons = [("e%d" % i, i * step + int(x * 1e6)) for i, x in enumerate(deliveries_ms)]
    _write(d / "producer.csv", PROD, prod)
    _write(d / "consumer.csv", CONS, cons)
    if meta:
        (d / "meta.json").write_text(json.dumps({"backend": backend}), encoding="utf-8")
    if trace is not None:
        _write(d / "consumer_readtrace.csv", ("t_read_start_ns", "read_duration_ns",
                                              "n_messages"), [(0, 1, k) for k in trace])
    return d


class TestOneRun:

    def test_a_clean_run(self, tmp_path):
        d = _run(tmp_path, "r", "kafka", [2.0] * 5)
        row = bc.census("r", "kafka", str(d))
        assert (row["published"], row["consumed"], row["joined"], row["late"]) == (5, 5, 5, 0)
        assert row["first_waited"] == "" and row["foreign_read"] == ""
        assert (row["negatives"], row["late_wide"], row["neg_wide"]) == (0, 0, 0)

    def test_a_run_that_stopped_consuming_early(self, tmp_path):
        d = _run(tmp_path, "r", "kafka", [2.0] * 3, published=6)
        row = bc.census("r", "kafka", str(d))
        assert (row["published"], row["consumed"]) == (6, 3)

    def test_a_backlog_at_the_start(self, tmp_path):
        """The first three arrive together at 2.5 s; the third waited under the margin."""
        d = _run(tmp_path, "r", "redis", [2500.0, 1500.0, 500.0] + [3.0] * 7,
                 trace=[200, 200, 10])
        row = bc.census("r", "redis", str(d))
        assert row["late"] == 3 and row["first_waited"] == 1 and row["neg_late"] == 0
        assert row["late_wide"] == 3 and row["foreign_read"] == 410 - 10

    def test_a_wait_in_mid_run_leaves_the_first_message_prompt(self, tmp_path):
        """No backlog: the census shows a run whose late message is not a backlog's."""
        d = _run(tmp_path, "r", "kafka", [3.0] * 5 + [4000.0] + [3.0])
        row = bc.census("r", "kafka", str(d))
        assert row["late"] == 1 and row["first_waited"] == 0

    def test_a_consumer_that_never_caught_up(self, tmp_path):
        d = _run(tmp_path, "r", "redis", [9000.0 - 1000.0 * i for i in range(6)])
        row = bc.census("r", "redis", str(d))
        assert row["late"] == row["late_wide"] == 6 and row["first_waited"] == 1

    def test_a_start_up_wait_under_a_second_is_counted_wide_only(self, tmp_path):
        """Published every quarter second, the first three arrive together at 0.6 s."""
        d = _run(tmp_path, "r", "kafka", [600.0, 350.0, 100.0] + [3.0] * 9, step_s=0.25)
        row = bc.census("r", "kafka", str(d))
        assert (row["late"], row["late_wide"], row["neg_wide"]) == (0, 3, 0)

    def test_negatives_are_counted_and_kept_ones_stay_out_of_the_wide_count(self, tmp_path):
        d = _run(tmp_path, "r", "kafka", [0.2] * 4, ack_after_ms=0.5)
        row = bc.census("r", "kafka", str(d))
        assert (row["negatives"], row["late_wide"], row["neg_wide"]) == (4, 0, 0)

    def test_a_late_message_below_zero_is_counted(self, tmp_path):
        """The rule's argument says this cannot happen; the census would show it if it did."""
        d = _run(tmp_path, "r", "kafka", [5000.0] + [3.0] * 5, ack_after_ms=6000.0)
        row = bc.census("r", "kafka", str(d))
        assert row["neg_late"] >= 1 and row["neg_wide"] >= row["neg_late"]

    def test_an_unacknowledged_message_does_not_join(self, tmp_path):
        d = _run(tmp_path, "r", "kafka", [2.0, 2.0])
        rows = list(csv.reader(open(d / "producer.csv", encoding="utf-8")))
        rows[1][2] = ""
        _write(d / "producer.csv", rows[0], rows[1:])
        assert bc.census("r", "kafka", str(d))["joined"] == 1

    def test_the_backend_comes_from_meta(self, tmp_path):
        d = _run(tmp_path, "r", "redis", [2.0])
        assert bc.backend_of(str(d)) == "redis"


class TestTheCommandLine:

    def test_a_missing_folder_is_an_error(self, tmp_path, capsys):
        assert bc.main(["--runs-dir", str(tmp_path / "none")]) == 1
        assert "missing" in capsys.readouterr().out

    def test_several_folders_make_one_table(self, tmp_path):
        """The registered campaign keeps each pair's runs in a folder of its own."""
        _run(tmp_path / "arm", "a", "kafka", [2.0] * 3)
        _run(tmp_path / "matched", "m", "redis", [2.0] * 2)
        out = tmp_path / "azure.csv"
        assert bc.main(["--runs-dir", str(tmp_path / "arm"), "--runs-dir",
                        str(tmp_path / "matched"), "--out", str(out)]) == 0
        rows = list(csv.DictReader(open(out, encoding="utf-8")))
        assert [(r["run_id"], r["backend"]) for r in rows] == [("a", "kafka"), ("m", "redis")]

    def test_the_default_folder_is_the_july_archive(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        assert bc.main([]) == 1
        assert "cloud_archive" in capsys.readouterr().out

    def test_runs_without_files_or_matches_are_skipped(self, tmp_path):
        root = tmp_path / "runs"
        _run(root, "a", "kafka", [2.0] * 3)
        _run(root, "b", "redis", [], published=4)
        _run(root, "c", "kafka", [2.0], meta=False)
        (root / "stray.txt").write_text("x", encoding="utf-8")
        out = tmp_path / "deep" / "census.csv"
        assert bc.main(["--runs-dir", str(root), "--out", str(out)]) == 0
        rows = list(csv.DictReader(open(out, encoding="utf-8")))
        assert [r["run_id"] for r in rows] == ["a"]
        assert list(rows[0]) == list(bc.FIELDS)

    def test_no_run_with_a_match_is_refused(self, tmp_path, capsys):
        root = tmp_path / "runs"
        _run(root, "b", "redis", [], published=4)
        assert bc.main(["--runs-dir", str(root), "--out", str(tmp_path / "c.csv")]) == 1
        assert "refusing" in capsys.readouterr().out

    def test_a_bare_filename_needs_no_folder(self, tmp_path, monkeypatch):
        root = tmp_path / "runs"
        _run(root, "a", "kafka", [2.0])
        monkeypatch.chdir(tmp_path)
        assert bc.main(["--runs-dir", "runs", "--out", "census.csv"]) == 0
        assert (tmp_path / "census.csv").exists()


class TestTheCommittedCensus:

    ROWS = list(csv.DictReader(open(REPO / "docs" / "results" / "backlog_by_run.csv",
                                    encoding="utf-8")))

    def test_it_covers_table_ones_corpus_as_first_counted(self):
        assert len(self.ROWS) == 5913
        assert sum(int(r["joined"]) for r in self.ROWS) == 738730

    def test_the_messages_no_one_read(self):
        unread = [int(r["published"]) - int(r["consumed"]) for r in self.ROWS]
        assert sum(1 for x in unread if x) == 1491 and sum(unread) == 91177

    def test_the_late_messages_and_the_wider_check(self):
        """7 Oct 2026: 30,225 late in 2,099 runs; the wider check adds 1,898; neither holds a
        negative, so the corpus rate moves from 8.43% to 8.79% and, wider, to 8.81%."""
        total = lambda k: sum(int(r[k]) for r in self.ROWS)
        assert (total("late"), total("neg_late"), total("late_wide"), total("neg_wide")) == \
            (30225, 0, 32123, 0)
        assert sum(1 for r in self.ROWS if int(r["late"])) == 2099
        assert total("negatives") == 62264
