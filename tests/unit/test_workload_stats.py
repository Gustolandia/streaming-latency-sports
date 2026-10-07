"""Tests for scripts/workload_stats.py: the message size and publish rate of every run."""
import csv
import io
import json
import sys
import tarfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import workload_stats as ws  # noqa: E402

PRODUCER = ("run_id", "backend", "topic", "event_id", "match_id", "t_sim_seconds",
            "t_emit_offset_s", "t_prod_sched_ns", "t_prod_send_ns", "t_broker_ack_ns")
RUN = "concurrency_n5_20260725_072848_kafka_feed1_rep1"


def _row(send_ns, event="4af6d17a-69ad-4bca-aece-f3be76c10138", offset="0.0", sched=10):
    return {"run_id": RUN, "backend": "kafka", "topic": "t", "event_id": event,
            "match_id": "3895134", "t_sim_seconds": "0", "t_emit_offset_s": offset,
            "t_prod_sched_ns": str(sched), "t_prod_send_ns": str(send_ns),
            "t_broker_ack_ns": str(send_ns + 5)}


def _csv_bytes(rows):
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=PRODUCER, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return out.getvalue().encode("utf-8")


class TestTheRecordIsRebuiltExactly:

    def test_the_size_is_the_record_the_producer_wrote(self):
        """Written out by hand, in the order and with the separators the producers use."""
        sent = ('{"run_id":"%s","match_id":3895134,'
                '"event_id":"4af6d17a-69ad-4bca-aece-f3be76c10138","t_sim_seconds":0,'
                '"t_emit_offset_s":0.0,"t_emit_planned_ns":10,'
                '"s3_uid":"3895134:4af6d17a-69ad-4bca-aece-f3be76c10138","s3_rev":1,'
                '"s3_is_correction":false}' % RUN)
        assert ws.message_bytes(_row(1)) == len(sent.encode("utf-8"))

    def test_a_longer_offset_or_timestamp_is_counted(self):
        assert ws.message_bytes(_row(1, offset="12.5", sched=1784783055883100746)) \
            > ws.message_bytes(_row(1))

    def test_the_rebuild_matches_json_dumps_on_the_same_record(self):
        row = _row(1)
        msg = {"run_id": RUN, "match_id": 3895134, "event_id": row["event_id"],
               "t_sim_seconds": 0, "t_emit_offset_s": 0.0, "t_emit_planned_ns": 10,
               "s3_uid": "3895134:" + row["event_id"], "s3_rev": 1, "s3_is_correction": False}
        assert ws.message_bytes(row) == len(json.dumps(msg, separators=(",", ":")))


class TestOneRun:

    def test_the_feed_count_is_read_from_the_name(self):
        assert ws.feeds_of(RUN) == 5
        assert ws.feeds_of("concurrency_n12_20260723_050408_redis_feed10_rep1") == 12
        assert ws.feeds_of("batch9_kafka_rep1") == ""

    def test_a_run_gives_its_rate_and_sizes(self):
        rows = [_row(0), _row(1_000_000_000), _row(2_000_000_000, offset="12.5")]
        got = ws.summarise(RUN, "kafka", rows)
        assert got["messages"] == 3 and got["feeds"] == 5
        assert got["duration_s"] == "2.000" and got["publish_rate_hz"] == "1.0000"
        assert got["bytes_min"] < got["bytes_max"]
        assert got["bytes_min"] <= got["bytes_median"] <= got["bytes_max"]

    def test_one_message_has_no_rate(self):
        assert ws.summarise(RUN, "kafka", [_row(0)]) is None

    def test_messages_published_at_one_instant_have_no_rate(self):
        assert ws.summarise(RUN, "kafka", [_row(5), _row(5)]) is None


def _corpus(tmp_path, names):
    path = tmp_path / "corpus.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["run_id", "backend", "n_events"])
        for name in names:
            w.writerow([name, "kafka", "3"])
    return path


def _runs_dir(tmp_path, runs):
    root = tmp_path / "runs"
    for name, rows in runs.items():
        (root / name).mkdir(parents=True)
        (root / name / "producer.csv").write_bytes(_csv_bytes(rows))
    return root


GOOD = [_row(0), _row(500_000_000)]


class TestReadingAnUnpackedTree:

    def test_every_corpus_run_found(self, tmp_path):
        root = _runs_dir(tmp_path, {"a": GOOD, "b": GOOD})
        rows, missing = ws.scan_dir(str(root), [("a", "kafka"), ("b", "redis")])
        assert [r["run_id"] for r in rows] == ["a", "b"] and missing == []
        assert rows[1]["backend"] == "redis" and rows[0]["publish_rate_hz"] == "2.0000"

    def test_a_run_without_a_log_or_a_rate_is_named(self, tmp_path):
        root = _runs_dir(tmp_path, {"a": GOOD, "short": [_row(0)]})
        rows, missing = ws.scan_dir(str(root), [("a", "kafka"), ("gone", "kafka"),
                                                ("short", "kafka")])
        assert [r["run_id"] for r in rows] == ["a"] and missing == ["gone", "short"]


def _archive(tmp_path, members):
    path = tmp_path / "runs.tgz"
    with tarfile.open(path, "w:gz") as tf:
        for name, data in members:
            if data is None:
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                tf.addfile(info)
                continue
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


class TestReadingTheArchive:

    def test_only_the_corpus_producer_logs_are_read(self, tmp_path):
        path = _archive(tmp_path, [
            ("runs", None), ("runs/a", None),
            ("runs/a/producer.csv", _csv_bytes(GOOD)),
            ("runs/a/consumer.csv", b"not read"),
            ("runs/other/producer.csv", _csv_bytes(GOOD)),
            ("logs/a/producer.csv", _csv_bytes(GOOD)),
            ("producer.csv", _csv_bytes(GOOD)),
            ("runs/b/nested/producer.csv", _csv_bytes([_row(0), _row(250_000_000)]))])
        rows, missing = ws.scan_archive(str(path), [("a", "kafka"), ("b", "redis")])
        assert [r["run_id"] for r in rows] == ["a", "b"] and missing == []
        assert rows[1]["publish_rate_hz"] == "4.0000"

    def test_a_corpus_run_absent_from_the_archive_is_named(self, tmp_path):
        path = _archive(tmp_path, [("runs/a/producer.csv", _csv_bytes(GOOD))])
        rows, missing = ws.scan_archive(str(path), [("a", "kafka"), ("z", "kafka")])
        assert len(rows) == 1 and missing == ["z"]


class TestTheFiles:

    def test_the_corpus_is_read_as_run_and_broker(self, tmp_path):
        assert ws.read_corpus(_corpus(tmp_path, ["a", "b"])) == [("a", "kafka"), ("b", "kafka")]

    def test_the_table_is_written_with_its_header(self, tmp_path):
        out = tmp_path / "deep" / "w.csv"
        ws.write_csv([ws.summarise("a", "kafka", GOOD)], str(out))
        rows = list(csv.DictReader(open(out, encoding="utf-8")))
        assert list(rows[0]) == list(ws.FIELDS) and rows[0]["run_id"] == "a"

    def test_a_bare_filename_needs_no_folder(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ws.write_csv([], "w.csv")
        assert (tmp_path / "w.csv").read_text(encoding="utf-8").startswith("run_id,")


class TestTheCommandLine:

    def test_a_missing_corpus_is_an_error(self, tmp_path, capsys):
        assert ws.main(["--corpus", str(tmp_path / "none.csv")]) == 1
        assert "missing" in capsys.readouterr().out

    def test_a_missing_tree_is_an_error(self, tmp_path):
        corpus = _corpus(tmp_path, ["a"])
        assert ws.main(["--corpus", str(corpus), "--runs-dir", str(tmp_path / "none")]) == 1

    def test_a_missing_archive_is_an_error(self, tmp_path, capsys):
        corpus = _corpus(tmp_path, ["a"])
        assert ws.main(["--corpus", str(corpus), "--archive", str(tmp_path / "x.tgz")]) == 1
        assert "--runs-dir" in capsys.readouterr().out

    def test_a_partial_corpus_is_refused(self, tmp_path, capsys):
        corpus = _corpus(tmp_path, ["a", "gone"])
        root = _runs_dir(tmp_path, {"a": GOOD})
        out = tmp_path / "w.csv"
        assert ws.main(["--corpus", str(corpus), "--runs-dir", str(root),
                        "--out", str(out)]) == 1
        assert "refusing" in capsys.readouterr().out and not out.exists()

    def test_the_tree_writes_the_table(self, tmp_path):
        corpus = _corpus(tmp_path, ["a"])
        root = _runs_dir(tmp_path, {"a": GOOD})
        out = tmp_path / "w.csv"
        assert ws.main(["--corpus", str(corpus), "--runs-dir", str(root),
                        "--out", str(out)]) == 0
        assert len(list(csv.DictReader(open(out, encoding="utf-8")))) == 1

    def test_the_archive_writes_the_table(self, tmp_path):
        corpus = _corpus(tmp_path, ["a"])
        path = _archive(tmp_path, [("runs/a/producer.csv", _csv_bytes(GOOD))])
        out = tmp_path / "w.csv"
        assert ws.main(["--corpus", str(corpus), "--archive", str(path),
                        "--out", str(out)]) == 0
        assert out.exists()


class TestTheCommittedTable:
    """The table the paper's numbers come from covers exactly Table I's corpus."""

    def test_it_has_a_row_for_every_corpus_run(self):
        table = REPO / "docs" / "results" / "workload_by_run.csv"
        corpus = REPO / "docs" / "results" / "span_recount.csv"
        mine = {r["run_id"] for r in csv.DictReader(open(table, encoding="utf-8"))}
        theirs = {r["run_id"] for r in csv.DictReader(open(corpus, encoding="utf-8"))}
        # 7 Oct 2026: 5,863 since the late messages were left out; 50 runs had no other.
        assert mine == theirs and len(mine) == 5863

    def test_every_run_had_a_rate_and_a_size(self):
        table = REPO / "docs" / "results" / "workload_by_run.csv"
        for r in csv.DictReader(open(table, encoding="utf-8")):
            assert float(r["publish_rate_hz"]) > 0 and int(r["bytes_min"]) > 200, r["run_id"]
