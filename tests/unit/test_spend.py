"""Tests for scripts/spend.py.

The bill arrives a day late, so the ledger has to be right about machine time: what it adds
between two looks, what it refuses to add across a gap when nobody was watching, and what it says
had been spent when a given run started.
"""
import datetime
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import spend  # noqa: E402

PAIR = {"matched": 0.48}


def moment(minutes, hour=12):
    return (datetime.datetime(2026, 9, 18, hour, 0, tzinfo=datetime.timezone.utc)
            + datetime.timedelta(minutes=minutes))


def an_hour_of(prices):
    """An hour of machine time as the watch would see it: a look every quarter of an hour."""
    ledger = spend.track(spend.load("no such file"), {}, moment(0))
    for minute in (15, 30, 45, 60):
        spend.track(ledger, prices, moment(minute))
    return ledger


class Done:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


class TestTheLedger:

    def test_the_first_look_starts_the_clock_and_charges_nothing(self):
        ledger = spend.track(spend.load("no such file"), PAIR, moment(0))
        assert ledger["total_usd"] == 0.0 and ledger["by_profile"] == {}
        assert ledger["started"] == "2026-09-18T12:00:00Z"

    def test_machine_time_between_two_looks_is_added_at_the_machines_price(self):
        ledger = spend.track(spend.load("no such file"), PAIR, moment(0))
        spend.track(ledger, PAIR, moment(5))
        assert ledger["total_usd"] == pytest.approx(0.48 * 5 / 60)
        assert ledger["by_profile"]["matched"] == pytest.approx(0.04)

    def test_each_pair_is_counted_on_its_own(self):
        ledger = an_hour_of({"matched": 0.48, "arm": 0.37})
        assert ledger["by_profile"] == {"matched": pytest.approx(0.48),
                                        "arm": pytest.approx(0.37)}
        assert ledger["total_usd"] == pytest.approx(0.85)

    def test_a_pair_that_is_off_costs_nothing(self):
        ledger = spend.track(spend.load("no such file"), PAIR, moment(0))
        spend.track(ledger, {}, moment(30))
        assert ledger["total_usd"] == 0.0

    def test_a_gap_nobody_watched_is_counted_short_and_not_guessed(self):
        """Fifteen minutes, not the four hours the watch was off for."""
        ledger = spend.track(spend.load("no such file"), PAIR, moment(0, hour=8))
        spend.track(ledger, PAIR, moment(0, hour=12))
        assert ledger["total_usd"] == pytest.approx(0.48 * 15 / 60)

    def test_it_survives_a_file_that_is_not_a_ledger(self, tmp_path):
        path = tmp_path / "spend.json"
        path.write_text("{oh dear", encoding="utf-8")
        assert spend.load(str(path))["total_usd"] == 0.0

    def test_two_looks_at_the_same_moment_add_nothing(self):
        ledger = spend.track(spend.load("no such file"), PAIR, moment(0))
        spend.track(ledger, PAIR, moment(0))
        assert ledger["total_usd"] == 0.0 and len(ledger["timeline"]) == 2

    def test_a_look_with_no_moment_given_is_taken_now(self):
        before = spend.now_utc()
        ledger = spend.track(spend.load("no such file"), PAIR)
        assert before <= spend.when(ledger["updated"]) + datetime.timedelta(seconds=1)

    def test_it_is_written_beside_the_working_folder_too(self, tmp_path, monkeypatch):
        """A bare name has no folder to make first."""
        monkeypatch.chdir(tmp_path)
        spend.save(spend.track(spend.load("none"), PAIR, moment(0)), "spend.json")
        assert spend.load("spend.json")["started"] == "2026-09-18T12:00:00Z"

    def test_it_is_written_and_read_back(self, tmp_path):
        path = str(tmp_path / "watch" / "spend.json")
        ledger = spend.track(spend.load(path), PAIR, moment(0))
        for minute in (15, 30):
            spend.track(ledger, PAIR, moment(minute))
        spend.save(ledger, path)
        again = spend.load(path)
        assert again["total_usd"] == pytest.approx(0.24)
        assert len(again["timeline"]) == 3


class TestWhatARunCost:
    """Every run's start is a point on the timeline, so a run can be told what had been spent."""

    def ledger(self):
        ledger = spend.track(spend.load("none"), PAIR, moment(0))
        for minute in (5, 10, 15):
            spend.track(ledger, PAIR, moment(minute))
        return ledger

    def test_a_run_that_started_between_two_looks_takes_the_earlier_one(self):
        assert spend.at(self.ledger(), "2026-09-18T12:07:00Z") == pytest.approx(0.04)

    def test_a_run_that_started_on_a_look(self):
        assert spend.at(self.ledger(), moment(10)) == pytest.approx(0.08)

    def test_a_run_before_the_ledger_began_has_nothing_to_take(self):
        assert spend.at(self.ledger(), "2026-09-18T11:00:00Z") is None

    def test_a_run_after_the_last_look_takes_the_last(self):
        assert spend.at(self.ledger(), "2026-09-18T23:00:00Z") == pytest.approx(0.12)

    def test_a_run_is_told_the_earlier_bill_too(self):
        ledger = self.ledger()
        ledger["before_usd"] = 8.49
        assert spend.at(ledger, moment(10)) == pytest.approx(8.57)
        assert spend.at(ledger, "2026-09-18T11:00:00Z") is None, "still nothing to take"

    def test_everything_spent_is_the_count_and_the_bill_it_was_seeded_with(self):
        assert spend.total({}) == 0.0
        assert spend.total({"total_usd": 0.12, "before_usd": 8.49}) == pytest.approx(8.61)

    def test_an_empty_ledger_says_nothing(self):
        assert spend.at({}, moment(0)) is None


class TestTheLineAPersonReads:

    def test_it_names_the_total_the_credit_and_each_pair(self):
        text = spend.line(an_hour_of({"matched": 0.48, "arm": 0.37}))
        assert "spent about $0.85 of $200" in text and "since 2026-09-18" in text
        assert "arm $0.37" in text and "matched $0.48" in text

    def test_a_ledger_seeded_with_an_earlier_bill_names_both(self):
        ledger = an_hour_of(PAIR)
        ledger["before_usd"] = 8.49
        text = spend.line(ledger)
        assert "spent about $8.97 of $200" in text
        assert "$8.49 of it billed before the watch began" in text

    def test_an_empty_ledger_still_reads(self):
        assert spend.line(spend.load("none")) == "spent about $0.00 of $200"


class TestWhatAzureCharged:

    USAGE = {"value": [
        {"properties": {"date": "2026-09-16T00:00:00Z", "costInUSD": 6.456}},
        {"properties": {"date": "2026-09-17T00:00:00Z", "costInUSD": 0.570}},
        {"properties": {"date": "2026-08-30T00:00:00Z", "costInUSD": 99.0}}]}

    def runner(self, usage=None, fail=None):
        def run(argv, **kwargs):
            if fail == "account" and argv[1] == "account":
                return Done("", 1, "please run az login")
            if argv[1] == "account":
                return Done("e62c0303\n")
            if fail == "rest":
                return Done("", 1, "Bad Request")
            return Done(json.dumps(usage if usage is not None else self.USAGE))
        return run

    def test_it_sums_what_was_charged_since_a_day(self):
        found = spend.billed("2026-09-01", self.runner())
        assert found["total_usd"] == pytest.approx(7.026)
        assert sorted(found["by_day"]) == ["2026-09-16", "2026-09-17"], "August is left out"

    def test_the_address_carries_nothing_a_shell_would_eat(self):
        """cmd.exe cuts at an ampersand and sh eats a dollar; either turns the bill into noise."""
        seen = []

        def run(argv, **kwargs):
            seen.append(argv)
            return Done("e62c0303") if argv[1] == "account" else Done(json.dumps(self.USAGE))
        spend.billed("2026-09-01", run)
        url = seen[-1][seen[-1].index("--url") + 1]
        assert "&" not in url and "$" not in url and url.startswith("https://management.azure.com/")

    def test_it_says_when_the_bill_did_not_fit_on_one_page(self):
        page = dict(self.USAGE, nextLink="https://management.azure.com/...")
        assert spend.billed("2026-09-01", self.runner(usage=page))["more"] is True
        code, text = TestMain().run(["billed"], run=self.runner(usage=page))
        assert code == 0 and "more rows than one page" in text

    def test_a_bill_with_nothing_on_it(self):
        found = spend.billed("2026-09-01", self.runner(usage={"value": []}))
        assert found["total_usd"] == 0.0 and found["currency"] == "USD"

    @pytest.mark.parametrize("fail,fragment", [("account", "could not read the subscription"),
                                               ("rest", "could not read the bill")])
    def test_it_says_when_azure_would_not_answer(self, fail, fragment):
        with pytest.raises(RuntimeError, match=fragment):
            spend.billed("2026-09-01", self.runner(fail=fail))


class TestMain:

    def run(self, argv, **kwargs):
        out = io.StringIO()
        return spend.main(argv, out=out, **kwargs), out.getvalue()

    def test_show_reads_the_ledger(self, tmp_path):
        path = str(tmp_path / "spend.json")
        ledger = spend.track(spend.load(path), PAIR, moment(0))
        for minute in (15, 30):
            spend.track(ledger, PAIR, moment(minute))
        spend.save(ledger, path)
        code, text = self.run(["show", "--ledger", path, "--credit-usd", "200"])
        assert code == 0 and "spent about $0.24 of $200" in text
        assert "the watch has been counting since 2026-09-18T12:00:00Z" in text

    def test_show_without_a_ledger_yet(self, tmp_path):
        code, text = self.run(["show", "--ledger", str(tmp_path / "none.json")])
        assert code == 0 and "spent about $0.00" in text and "counting since" not in text

    def test_seed_writes_what_was_billed_before_the_watch(self, tmp_path):
        path = str(tmp_path / "spend.json")
        code, text = self.run(["seed", "--usd", "8.49", "--ledger", path])
        assert code == 0 and "spent about $8.49 of $200" in text
        assert spend.load(path)["before_usd"] == 8.49

    def test_seed_can_take_the_figure_from_the_bill_itself(self, tmp_path):
        path = str(tmp_path / "spend.json")
        code, text = self.run(["seed", "--from-bill", "--ledger", path],
                              run=TestWhatAzureCharged().runner())
        assert code == 0 and "spent about $7.03 of $200" in text
        assert "$7.03 of it billed through 2026-09-17" in text
        assert spend.load(path)["before_through"] == "2026-09-17"

    def test_seed_with_neither_a_figure_nor_a_bill_says_so(self, tmp_path):
        code, text = self.run(["seed", "--ledger", str(tmp_path / "spend.json")])
        assert code == 2 and "seed needs --usd or --from-bill" in text

    def test_a_bill_with_no_days_still_seeds(self, tmp_path):
        path = str(tmp_path / "spend.json")
        code, _ = self.run(["seed", "--from-bill", "--ledger", path],
                           run=TestWhatAzureCharged().runner(usage={"value": []}))
        assert code == 0 and spend.load(path)["before_through"] == "none"

    def test_billed_prints_the_days(self):
        code, text = self.run(["billed"], run=TestWhatAzureCharged().runner())
        assert code == 0 and "billed since 2026-09-01: $7.03 over 2 day(s)" in text
        assert "  2026-09-16  $6.46" in text

    def test_billed_that_azure_refused_is_one_line(self):
        code, text = self.run(["billed"], run=TestWhatAzureCharged().runner(fail="rest"))
        assert code == 2 and text.startswith("ERROR: could not read the bill")
