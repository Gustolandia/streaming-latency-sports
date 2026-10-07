"""Tests for scripts/stale_backlog.py: the July runs' messages that waited behind a backlog."""
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import stale_backlog as sb  # noqa: E402

S = 10**9  # one second in ns


def _late(deliveries_ms, step_ns=S):
    """The rule's flags for messages published every step and delivered deliveries_ms later."""
    sent = [i * step_ns for i in range(len(deliveries_ms))]
    return sb.late(sent, [s + int(d * 1e6) for s, d in zip(sent, deliveries_ms)])


class TestWhatIsLate:

    def test_a_backlog_at_the_start_is_late_until_the_consumer_caught_up(self):
        """The first three arrive together at 2.5 s; the third waited only 500 ms."""
        assert _late([2500.0, 1500.0, 500.0] + [3.0] * 7) == [True] * 3 + [False] * 7

    def test_a_delivery_within_the_margin_finds_no_backlog(self):
        assert not any(_late([2.0] * 20 + [1001.0]))

    def test_a_message_published_after_the_catch_up_is_kept(self):
        """Published 1 ms after the last late message arrived, and delivered at once."""
        sent = [0, S, 2 * S + 1_000_000]
        received = [2 * S, 2 * S, 2 * S + 3_000_000]
        assert sb.late(sent, received) == [True, True, False]

    def test_a_long_path_is_judged_against_its_own_deliveries(self):
        """Padding to 256 KB takes about 190 ms on Kafka; none of it is late."""
        assert not any(_late([180.0 + i for i in range(30)]))

    def test_a_run_that_caught_up_only_at_its_end_keeps_its_prompt_messages(self):
        """Published every 10 s, caught up at 275 s: nine tenths late, and a percentile would
        sit among them and keep a minute-late tail."""
        d = [275000.0 - 10000.0 * i for i in range(28)] + [20.8, 21.0]
        assert _late(d, 10 * S) == [True] * 28 + [False] * 2

    def test_a_run_that_never_caught_up_is_late_throughout(self):
        assert all(_late([460000.0 - 1000.0 * i for i in range(30)]))

    def test_a_wait_in_mid_run_leaves_the_earlier_messages(self):
        """The consumer had received them long before; only the burst it waited for counts."""
        assert _late([3.0] * 5 + [4000.0] + [3.0]) == [False] * 5 + [True, False]

    def test_the_burst_is_the_second_before_the_catch_up(self):
        """The last late message arrives at 4 s. A message received at 2.002 s was not in the
        burst; one received at 3.2 s, after waiting 100 ms, was."""
        sent = [0, 2 * S, int(2.5 * S), int(3.1 * S)]
        received = [int(1.5 * S), 2 * S + 2_000_000, 4 * S, int(3.2 * S)]
        assert sb.late(sent, received) == [True, False, True, True]

    def test_a_fastest_delivery_of_exactly_a_second_still_counts(self):
        assert not any(_late([1000.0] * 10))

    def test_no_messages_gives_no_flags(self):
        assert sb.late([], []) == []

    def test_the_margin_is_a_second(self):
        assert sb.LATE_MARGIN_MS == 1000.0


class TestTheCensusBearsTheRuleOut:
    """The facts the rule rests on, read from the committed census of the July runs."""

    ROWS = list(csv.DictReader(open(REPO / "docs" / "results" / "backlog_by_run.csv",
                                    encoding="utf-8")))

    def test_no_message_left_out_has_s_below_zero(self):
        assert sum(int(r["neg_late"]) for r in self.ROWS) == 0

    def test_every_backlog_began_at_its_runs_start(self):
        """In every run with late messages its first published message waited beyond the
        margin, so no wait in mid-run carried earlier messages with it."""
        late = [r for r in self.ROWS if int(r["late"])]
        assert late and all(r["first_waited"] == "1" for r in late)

    def test_every_redis_run_with_one_had_read_other_runs_messages(self):
        """Where its consumer logged its reads, which all but five Redis runs did."""
        late_redis = [r for r in self.ROWS if r["backend"] == "redis" and int(r["late"])
                      and r["foreign_read"] != ""]
        assert late_redis and all(int(r["foreign_read"]) > 0 for r in late_redis)


def _prod(n, step_ns=S):
    return [{"event_id": "e%d" % i, "t_prod_send_ns": str(i * step_ns)} for i in range(n)]


def _cons(deliveries_ms, step_ns=S):
    return [{"event_id": "e%d" % i, "t_cons_recv_ns": str(i * step_ns + int(d * 1e6))}
            for i, d in enumerate(deliveries_ms)]


class TestTheLateMessagesById:

    def test_the_ids_of_the_late_messages(self):
        late = sb.late_ids(_prod(5), _cons([1500.0, 500.0, 3.0, 3.0, 3.0]))
        assert late == {"e0", "e1"}

    def test_unmatched_or_broken_rows_are_not_judged(self):
        prod = _prod(4) + [{"event_id": "bad", "t_prod_send_ns": "x"}, {"t_prod_send_ns": "1"}]
        cons = _cons([3.0, 3.0, 3.0]) + [{"event_id": "nope", "t_cons_recv_ns": "9"},
                                         {"event_id": "e3", "t_cons_recv_ns": ""},
                                         {"event_id": "bad", "t_cons_recv_ns": "5"}]
        cons[0]["t_cons_recv_ns"] = str(5 * S)
        assert sb.late_ids(prod, cons) == {"e0"}

    def test_a_run_folder(self, tmp_path):
        """Published every 2 s, so the second message comes after the catch-up at 1.2 s."""
        for name, rows in (("producer.csv", _prod(3, 2 * S)),
                           ("consumer.csv", _cons([1200.0, 2.0, 2.0], 2 * S))):
            with open(tmp_path / name, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        assert sb.late_ids_in(str(tmp_path)) == {"e0"}

    def test_a_folder_without_both_records_has_none(self, tmp_path):
        (tmp_path / "producer.csv").write_text("event_id,t_prod_send_ns\n", encoding="utf-8")
        assert sb.late_ids_in(str(tmp_path)) == set()
