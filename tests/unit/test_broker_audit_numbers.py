"""The broker audit's numbers (scripts/broker_audit_numbers.py): every count of the paper's Section
V-D and its broker table (tab:brokers) and of Supplement S7, read from the audit's committed record
with the verdict rules scripts/broker_audit.py holds. The tests build small records in the
protocol's own form, then read the committed one and the brokers the paper names."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import broker_audit  # noqa: E402
import broker_audit_numbers as ban  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def _q(answer, resolution=None, quote="q"):
    out = {"answer": answer, "evidence": [{"url": "https://example.org/v1", "quote": quote}]}
    if resolution is not None:
        out["resolution"] = resolution
    return out


def _mode(name, q1="no", q2="not applicable", q3="no", q4="not applicable", q5="no", q7="none",
          r1=None, r3=None, r5=None, read_back=(), not_determined=(), changed=False):
    m = {"mode": name, "Q0": _q("x"), "Q1": _q(q1, r1), "Q2": _q(q2), "Q3": _q(q3, r3),
         "Q4": _q(q4), "Q5": _q(q5, r5), "Q6": _q("none"), "Q7": _q(q7),
         "not_determined": list(not_determined), "read_back": list(read_back)}
    if changed:
        m["Q5"]["changed_on_read_back"] = {"from": "no", "why": "read back"}
    return m


def _producer(name, ack=True, p1="no", p2="no", p3="no", read_back=()):
    return {"interface": name, "P0": {"acknowledgment": ack, "evidence": []},
            "P1": _q(p1), "P2": _q(p2), "P3": _q(p3), "not_determined": [],
            "read_back": list(read_back)}


def _world(root, precedents=True):
    """Four brokers, one per way a broker is found, whose interfaces cover every verdict."""
    agree = [{"agrees": True}]
    doubt = [{"agrees": False}]
    brokers = [
        {"broker": "Alpha", "group": "A", "version": "1", "version_evidence": [],
         "modes": [
             # The wait: the request's arrival handed on with the arrival stamp, in ns.
             _mode("pull", q1="always", q2="yes", q3="request arrival", q4="yes", q7="standing",
                   r1="ns", r3="ns", read_back=agree),
             # A residence time, both ends finer than a millisecond.
             _mode("push", q1="always", q2="yes", q3="send time", q4="yes", q7="credit or several",
                   r1="µs", r3="us", read_back=doubt, changed=True),
         ],
         "producers": [_producer("publish", p3="hold", read_back=agree)]},
        {"broker": "Beta", "group": "B", "version": "1", "version_evidence": [],
         "modes": [
             # A residence time known only from a duration in whole seconds.
             _mode("expiry", q1="by configuration", q2="yes", q5="derivable stay", r1="s", r5="s",
                   q7="one at a time"),
             # The arrival only, with the request's arrival kept inside, to the nanosecond.
             _mode("fetch", q1="always", q2="yes", q3="request arrival", q4="no", r1="ms",
                   r3="ns (a clock)", q7="one at a time", not_determined=("Q6",)),
         ],
         "producers": [_producer("send", p1="always"), _producer("oneway", ack=False)]},
        {"broker": "Gamma", "group": "C", "version": "1", "version_evidence": [],
         "found_by": [{"route": "seed"}],
         "modes": [
             # Nothing: a send time kept inside only.
             _mode("read", q3="send time", q4="no", r3="ms", q7="not determined"),
             # A residence time in milliseconds at both ends.
             _mode("lease", q1="always", q2="yes", q3="send time", q4="yes", r1="ms", r3="ms"),
         ],
         "producers": [_producer("put", p2="always")]},
        {"broker": "Delta", "group": "C", "version": "1", "version_evidence": [],
         "found_by": [{"route": "route 1"}],
         "modes": [_mode("get")],
         "producers": [_producer("post")]},
    ]
    folder = Path(root) / ban.DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "batch_01.json").write_text(json.dumps({"brokers": brokers}), encoding="utf-8")
    if precedents:
        (folder / "precedents.json").write_text(json.dumps({"precedents": [
            {"name": "NTP", "evidence": [{"url": "https://example.org/rfc", "quote": "p"}]}]}),
            encoding="utf-8")
    decisions = ["coded"] * 4 + ["out", "out", "copy", "screened out", "not checked",
                                 "not readable", "not readable"]
    (folder / "candidates.json").write_text(json.dumps({"products": [
        {"name": "p%d" % i, "decision": d} for i, d in enumerate(decisions)]}), encoding="utf-8")
    (folder / "search_log.json").write_text(json.dumps({"searches": [{"q": 1}, {"q": 2}]}),
                                            encoding="utf-8")


def test_a_small_record_gives_each_count_by_the_registered_rules(tmp_path):
    _world(tmp_path)
    got = dict(ban.macros(str(tmp_path)))
    assert (got["baBrokers"], got["baFirstBrokers"], got["baToolBrokers"]) == ("4", "2", "1")
    assert (got["baCloudServicesWord"], got["baSeedBrokers"], got["baSearchBrokers"]) == (
        "one", "1", "1")
    assert (got["baConsumerModes"], got["baProducerModes"]) == ("7", "5")
    assert (got["baWaitModesWord"], got["baStayModes"], got["baStayBrokers"]) == ("one", "3", "3")
    assert got["baStaySecondModes"] == "1"
    assert (got["baArrivalModes"], got["baNothingModes"], got["baNothingBrokers"]) == (
        "1", "2", "1")
    assert (got["baKeptRequestModes"], got["baKeptRequestBrokers"]) == ("1", "1")
    assert got["baKeptRequestNsWord"] == "one"
    assert (got["baKeptSendModes"], got["baKeptSendBrokers"]) == ("1", "1")
    assert (got["baWaitCan"], got["baWaitCannot"], got["baWaitUnsettledWord"]) == (
        "2", "4", "one")
    assert (got["baHoldModesWord"], got["baOneTimeModes"], got["baReceiveOnlyModes"]) == (
        "one", "2", "1")
    assert (got["baSendOnlyModesWord"], got["baNoTimeModes"], got["baNoAckModes"]) == (
        "one", "1", "1")
    assert (got["baProducts"], got["baOut"], got["baCopies"], got["baScreenedOut"]) == (
        "11", "2", "1", "1")
    assert (got["baNotChecked"], got["baNotReadableWord"], got["baSearches"]) == ("1", "two", "2")
    # Every evidence item of every question, the precedent's included.
    assert (got["baQuotes"], got["baPrecedents"]) == (str(7 * 8 + 5 * 3 + 1), "1")
    assert (got["baReadBacks"], got["baReadBackDisagree"], got["baChangedOnReadBack"]) == (
        "3", "1", "1")
    assert got["baNotDetermined"] == "1"


def test_a_record_without_precedents_counts_none(tmp_path):
    _world(tmp_path, precedents=False)
    got = dict(ban.macros(str(tmp_path)))
    assert got["baPrecedents"] == "0" and got["baQuotes"] == str(7 * 8 + 5 * 3)


def test_a_folder_without_records_is_refused(tmp_path):
    (tmp_path / ban.DIR).mkdir(parents=True)
    with pytest.raises(ValueError, match="no batch file"):
        ban.records(str(tmp_path))


def test_a_stay_finer_than_a_millisecond_needs_both_ends_finer(tmp_path):
    _world(tmp_path)
    brokers, _ = ban.records(str(tmp_path))
    # Alpha's push hands on both ends in microseconds; Gamma's lease, in milliseconds, does not
    # count, nor Beta's duration in seconds, nor Alpha's pull, which tells the wait.
    assert ban.fine_stays(brokers) == ["Alpha"]
    assert ban.finer_than_ms("100 ns (UtcTime)") and ban.finer_than_ms("NTP64 on a router")
    assert not ban.finer_than_ms("ms (epoch)") and not ban.finer_than_ms(None)
    assert not ban.finer_than_ms("s in the header; µs as kept")


def test_counts_are_spelled_as_ieee_style_prints_them():
    assert (ban.spell(0), ban.spell(10), ban.spell(12), ban.spell(13)) == (
        "zero", "ten", "twelve", "13")
    assert ban.thousands(14069) == "14{,}069" and ban.thousands(766) == "766"
    assert ban.base("arrival only (unless Q5)") == "arrival only"


def test_the_committed_record_gives_the_counts_its_readme_reports():
    """data/broker_audit/README.md, "The answer in brief" and "How the brokers were found"."""
    got = dict(ban.macros(str(REPO)))
    expect = {
        "baBrokers": "222", "baFirstBrokers": "23", "baToolBrokers": "18",
        "baCloudServicesWord": "five", "baSeedBrokers": "111", "baSearchBrokers": "88",
        "baConsumerModes": "418", "baProducerModes": "390", "baWaitModesWord": "two",
        # 3 Nov 2026: 38, with gmqtt's two MQTT 5.0 interfaces (the README's corrections).
        "baStayModes": "79", "baStayBrokers": "53", "baStaySecondModes": "38",
        "baArrivalModes": "149", "baNothingModes": "188", "baNothingBrokers": "86",
        "baKeptRequestModes": "20", "baKeptRequestBrokers": "19", "baKeptRequestNsWord": "ten",
        "baKeptSendModes": "61", "baKeptSendBrokers": "47", "baWaitCan": "308",
        "baWaitCannot": "100", "baWaitUnsettledWord": "ten", "baHoldModesWord": "two",
        "baOneTimeModes": "42", "baReceiveOnlyModes": "38", "baSendOnlyModesWord": "four",
        "baNoTimeModes": "248", "baNoAckModes": "98", "baProducts": "1{,}302", "baOut": "689",
        "baCopies": "68", "baScreenedOut": "133", "baNotChecked": "188",
        "baNotReadableWord": "two", "baSearches": "766", "baQuotes": "14{,}069",
        "baPrecedents": "42", "baReadBacks": "881", "baReadBackDisagree": "15",
        "baChangedOnReadBack": "50", "baNotDetermined": "333",
        # 3 Nov 2026: the broker table prints its two smallest counts in digits, the prose in
        # words; and Section VI-C's sizes of a base-128 integer of microseconds.
        "baWaitModes": "2", "baHoldModes": "2",
        "baVarintOneUs": "128", "baVarintTwoUs": "16{,}384", "baVarintThreeUs": "2{,}097{,}152",
    }
    assert got == expect


def test_a_base_128_integer_takes_one_more_byte_at_each_power_of_128():
    """Section VI-C: seven bits of the value in each byte, so n bytes hold every wait below
    128 to the n microseconds."""
    assert ban.varint_limits() == [(1, 128), (2, 16384), (3, 2097152)]
    assert ban.varint_limits((4,)) == [(4, 268435456)]


#: Each broker the paper's Section V-D, its broker table and Supplement S7 name, with the record's
#: own name for it, its interface (a fragment of the record's name, or None for any) and the
#: verdict or kept time the text gives it.
NAMED = (
    ("Eclipse Zenoh", "queries answered by a storage", "wait in the message"),
    ("Azurite", "Get Messages", "wait in the message"),
    ("PGMQ", "read and read_with_poll", "stay in the message"),
    ("OPC UA (Part 4 subscriptions, Part 14 PubSub)", "subscriptions", "stay in the message"),
    ("Eclipse Zenoh", "subscribers", "stay in the message"),
    ("Apache ActiveMQ Classic", None, "stay in the message"),
    ("Apache RocketMQ", "pop consumption", "stay in the message"),
    ("Amazon SQS", None, "stay in the message"),
    ("Azure Service Bus", "peek-lock", "stay in the message"),
    ("RabbitMQ", "queues", "stay in the message"),
    ("Apache ActiveMQ Artemis", "AMQP 1.0 consumers", "stay in the message"),
    ("MQTT 5.0 (OASIS standard)", None, "stay in the message"),
    ("Apache Kafka", None, "arrival only"),
    ("Redis", "streams", "arrival only"),
    ("NATS", "JetStream", "arrival only"),
    ("Apache Pulsar", None, "arrival only"),
    ("Apache BookKeeper", None, "nothing"),
    ("Pravega", None, "nothing"),
    ("Beanstalkd", None, "nothing"),
)
KEPT = (("Apache Kafka", "consumer groups"), ("Apache Kafka", "share groups"),
        ("NATS", "JetStream pull consumers"), ("KubeMQ (community edition)", "queues"))
ACKED = (
    ("Liftbridge", "Publish and PublishAsync", "hold in the acknowledgment"),
    ("KubeMQ (community edition)", "SendQueueMessage", "hold in the acknowledgment"),
    ("Apache Kafka", "acks=1", "receive time only"),
    ("Redis", "XADD", "receive time only"),
    ("NATS", "JetStream publish with a reply subject", "nothing"),
    ("RabbitMQ", "publisher confirms", "nothing"),
    ("Apache Pulsar", "producer", "nothing"),
    ("Amazon SQS", "SendMessage", "nothing"),
    ("Apache Kafka", "acks=0", "no acknowledgment"),
)


def _by_name():
    return {b["broker"]: b for _, b in broker_audit.load()}


def test_every_broker_the_text_names_carries_the_verdict_it_names():
    brokers = _by_name()
    for name, mode, said in NAMED:
        verdicts = [ban.base(broker_audit.verdict(m)) for m in brokers[name]["modes"]
                    if mode is None or mode in m["mode"]]
        assert said in verdicts, (name, mode, said, verdicts)
    for name, mode in KEPT:
        assert any(m["Q3"]["answer"] == "request arrival" and m["Q4"]["answer"] == "no"
                   for m in brokers[name]["modes"] if mode in m["mode"]), (name, mode)
    for name, iface, said in ACKED:
        verdicts = [ban.base(broker_audit.ack_verdict(p)) for p in brokers[name]["producers"]
                    if iface in p["interface"]]
        assert said in verdicts, (name, iface, said, verdicts)


def test_only_the_three_the_text_names_tell_a_residence_time_finer_than_a_millisecond():
    assert ban.fine_stays(broker_audit.load()) == [
        "Eclipse Zenoh", "OPC UA (Part 4 subscriptions, Part 14 PubSub)", "PGMQ"]


def test_the_brokers_the_tools_time_tell_neither_the_wait_nor_a_fine_residence_time():
    """Section V-D's last paragraph and contribution 3: the brokers a tool of the tools audit can
    time (group A) tell at most the arrival, or a residence time in milliseconds or coarser."""
    tools = [b for _, b in broker_audit.load() if b["group"] == "A"]
    said = {ban.base(broker_audit.verdict(m)) for b in tools for m in b["modes"]}
    assert said == {"arrival only", "stay in the message", "nothing"}
    assert not set(ban.fine_stays([(None, b) for b in tools]))


class TestTheEmitterReadsThem:
    """emit_paper_numbers.broker_audit_macros, the ledger's door to these numbers (3 Nov 2026)."""

    def test_every_macro_is_in_the_committed_ledger(self):
        import emit_paper_numbers as epn
        text = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
        pairs = epn.broker_audit_macros(str(REPO))
        # 3 Nov 2026: 42, then the three sizes of Section VI-C and the table's two digit forms.
        assert len(pairs) == 47
        for name, value in pairs:
            assert "\\newcommand{\\%s}{%s}\n" % (name, value) in text, name

    def test_a_tree_without_the_record_emits_nothing(self, tmp_path):
        import emit_paper_numbers as epn
        assert epn.broker_audit_macros(str(tmp_path)) == []
