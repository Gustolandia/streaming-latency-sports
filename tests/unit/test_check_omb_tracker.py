"""Offline tests for check_omb_tracker.py: every branch, with the network call replaced."""
import csv
import io
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import check_omb_tracker as cot  # noqa: E402

PAYLOAD = {"total_count": 1, "items": [
    {"number": 56, "created_at": "2018-03-22T10:00:00Z",
     "title": "Avoid adding negative metric values"}]}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_builds_a_repository_scoped_search_and_parses_it():
    seen = {}

    def opener(request, timeout):
        seen["url"], seen["timeout"] = request.full_url, timeout
        seen["accept"] = request.get_header("Accept")
        return _Response(json.dumps(PAYLOAD).encode("utf-8"))

    assert cot.fetch(opener=opener) == PAYLOAD
    assert "repo%3Aopenmessaging/benchmark%20endToEndLatencyMicros" in seen["url"]
    assert "order=asc" in seen["url"], "oldest first, so the first item is the origin"
    assert seen["timeout"] == 60 and seen["accept"] == "application/vnd.github+json"


def test_summarise_takes_the_oldest_item():
    row = cot.summarise(PAYLOAD, "2026-09-13")
    assert row == {"repository": "openmessaging/benchmark", "query": "endToEndLatencyMicros",
                   "checked": "2026-09-13", "total_items": 1, "first_item": 56,
                   "first_item_created": "2018-03-22",
                   "first_item_title": "Avoid adding negative metric values"}


def test_summarise_an_empty_search_is_a_row_of_nothing():
    row = cot.summarise({"items": []}, "2026-09-13")
    assert row["total_items"] == 0 and row["first_item"] == "" and row["first_item_created"] == ""


def test_the_ledger_round_trips(tmp_path):
    path = tmp_path / "t.csv"
    cot.write_ledger(cot.summarise(PAYLOAD, "2026-09-13"), path)
    got = cot.read_ledger(path)
    assert got["first_item"] == "56" and got["total_items"] == "1"


def test_a_ledger_without_exactly_one_row_is_refused(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text(",".join(cot.FIELDS) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one row"):
        cot.read_ledger(path)


def test_compare_ignores_the_date_and_the_title():
    recorded = {k: str(v) for k, v in cot.summarise(PAYLOAD, "2026-09-13").items()}
    live = cot.summarise(PAYLOAD, "2030-01-01")
    live["first_item_title"] = "retitled upstream"
    assert cot.compare(recorded, live) == []
    live["total_items"] = 2
    assert cot.compare(recorded, live) == ["total_items"]


def test_main_write_records_the_live_result(tmp_path, capsys):
    path = tmp_path / "t.csv"
    assert cot.main(["--write", "--ledger", str(path)], fetcher=lambda: PAYLOAD,
                    today="2026-09-13") == 0
    assert cot.read_ledger(path)["checked"] == "2026-09-13"
    assert "wrote" in capsys.readouterr().out


def test_main_reports_an_unchanged_tracker(tmp_path, capsys):
    path = tmp_path / "t.csv"
    cot.write_ledger(cot.summarise(PAYLOAD, "2026-09-13"), path)
    assert cot.main(["--ledger", str(path)], fetcher=lambda: PAYLOAD, today="2026-10-01") == 0
    assert "unchanged since 2026-09-13" in capsys.readouterr().out


def test_main_fails_when_someone_has_returned_to_it(tmp_path, capsys):
    path = tmp_path / "t.csv"
    cot.write_ledger(cot.summarise(PAYLOAD, "2026-09-13"), path)
    moved = {"total_count": 2, "items": PAYLOAD["items"] + [{"number": 400}]}
    assert cot.main(["--ledger", str(path)], fetcher=lambda: moved) == 1
    assert "total_items 1 -> 2" in capsys.readouterr().out


def test_main_defaults_the_date_to_today(tmp_path):
    path = tmp_path / "t.csv"
    assert cot.main(["--write", "--ledger", str(path)], fetcher=lambda: PAYLOAD) == 0
    assert len(cot.read_ledger(path)["checked"]) == 10


def test_the_committed_ledger_says_what_the_supplement_quotes():
    row = cot.read_ledger(REPO / cot.LEDGER)
    assert row["query"] == "endToEndLatencyMicros"
    assert row["first_item"] == "56" and row["first_item_created"].startswith("2018")
    assert row["total_items"] == "1"
