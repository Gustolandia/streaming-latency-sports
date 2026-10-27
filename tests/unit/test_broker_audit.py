"""Tests for scripts/broker_audit.py: the broker audit's form, the verdicts its rules give, and the
fetch-back of its quotes, against records built here and pages served by a stub."""
import collections
import copy
import io
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "scripts"))

import broker_audit as ba  # noqa: E402

PINNED = "https://raw.githubusercontent.com/org/repo/v1.2.3/src/Broker.java"
DOCS = "https://docs.example.org/consume"


def item(quote="stamp = now()", url=PINNED):
    return {"url": url, "quote": quote}


def mode(**answers):
    """A mode whose answers are those given, and otherwise those of a broker that keeps nothing."""
    out = {"mode": "consumers",
           "Q0": {"fields": ["offset", "payload"], "evidence": [item()]},
           "not_determined": [], "read_back": []}
    base = {"Q1": "no", "Q2": "not applicable", "Q3": "no", "Q4": "not applicable", "Q5": "no",
            "Q6": "none", "Q7": "none"}
    base.update(answers)
    for q, answer in base.items():
        out[q] = {"answer": answer,
                  "evidence": [] if answer == "not applicable" else [item()]}
    if base["Q1"] in ba.STAMPED:
        out["Q1"].update(field="arrival_ms", resolution="ms")
    if base["Q3"] in ("request arrival", "send time"):
        out["Q3"].update(field="out_ms", resolution="ms")
    return out


def broker(*modes, **keys):
    out = {"broker": "Example MQ", "group": "A", "version": "1.2.3",
           "version_evidence": [item("version = 1.2.3")], "modes": list(modes) or [mode()]}
    out.update(keys)
    return out


def write(tmp_path, *brokers, name="batch_01.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"audited_utc": "2026-10-27", "brokers": list(brokers)}),
                    encoding="utf-8")
    return str(path)


# --- the form ------------------------------------------------------------------------------------

def test_load_reads_the_files_named_and_by_default_the_batches(tmp_path, monkeypatch):
    one = write(tmp_path, broker(), broker(broker="Other MQ"))
    assert [b["broker"] for _, b in ba.load([one])] == ["Example MQ", "Other MQ"]
    write(tmp_path, broker(broker="Second"), name="batch_02.json")
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ba, "RECORDS", str(tmp_path / "batch_*.json"))
    assert [b["broker"] for _, b in ba.load()] == ["Example MQ", "Other MQ", "Second"]


def test_a_url_is_pinned_by_the_ref_it_names():
    assert ba.ref_of(PINNED) == "v1.2.3"
    assert ba.ref_of("https://github.com/org/repo/blob/0123abc/docs/x.md") == "0123abc"
    assert ba.ref_of(DOCS) is None


def test_every_fault_of_an_evidence_item_is_named():
    faults = ba.evidence_faults([
        "a bare string",
        {"url": PINNED},
        {"url": "http://example.org/x", "quote": "q"},
        {"url": "https://raw.githubusercontent.com/org/repo/main/x", "quote": "q"},
        {"url": "https://github.com/org/repo/blob/HEAD/x", "quote": "q"},
        {"url": PINNED, "quote": "  "},
        {"url": PINNED, "quote": "x" * (ba.QUOTE_MOST + 1)},
        {"url": DOCS, "quote": "x" * ba.QUOTE_MOST},
    ], "here")
    assert faults == [
        "here[0]: an item is {url, quote}",
        "here[1]: an item is {url, quote}",
        "here[2]: the URL is not https",
        "here[3]: the URL names the moving branch 'main'",
        "here[4]: the URL names the moving branch 'HEAD'",
        "here[5]: the quote is empty",
        "here[6]: the quote is longer than 300 characters",
    ]


def test_a_sound_record_has_no_fault():
    assert ba.broker_faults(broker(mode(), mode(Q1="always", Q2="yes", Q3="send time", Q4="yes",
                                            Q5="stay", Q6="per request", Q7="credit or several")),
                            "b") == []


def test_a_mode_missing_a_question_is_named_and_nothing_else_is_asked():
    m = mode()
    del m["Q4"]
    assert ba.mode_faults(m, "m") == ["m: Q4 is missing"]


def test_every_fault_of_a_mode_is_named():
    m = mode(Q1="always", Q2="not applicable", Q3="no", Q4="yes", Q6="sometimes")
    m["Q0"] = {"fields": [], "evidence": []}
    del m["Q1"]["resolution"]
    m["Q5"]["evidence"] = []
    m["Q7"]["evidence"] = [{"url": PINNED}]
    m["read_back"] = None
    assert ba.mode_faults(m, "m") == [
        "m.Q0: the list of fields is empty",
        "m.Q0: no evidence",
        "m.Q5: no evidence",
        "m.Q6: 'sometimes' is not an answer the protocol allows",
        "m.Q7[0]: an item is {url, quote}",
        "m.Q2: 'not applicable' only when Q1 is 'no'",
        "m.Q4: with Q3 'no', it is 'not applicable'",
        "m.Q1: a stamp is recorded with its resolution",
        "m: read_back is a list",
    ]


def test_every_fault_of_a_broker_is_named():
    b = broker(group="C", version_evidence=[], modes=[])
    del b["broker"]
    assert ba.broker_faults(b, "b") == [
        "b: broker is missing", "b: group is A or B", "b: the version has no evidence",
        "b: no modes"]
    bad = mode()
    bad["Q2"]["answer"] = "maybe"
    assert ba.broker_faults(broker(bad), "b") == [
        "b/consumers.Q2: 'maybe' is not an answer the protocol allows",
        "b/consumers.Q2: with Q1 'no', it is 'not applicable'"]


# --- the verdicts --------------------------------------------------------------------------------

ARRIVAL = dict(Q1="always", Q2="yes")


@pytest.mark.parametrize("answers, said", [
    (dict(ARRIVAL, Q3="request arrival", Q4="yes"), "wait in the message"),
    (dict(Q5="derivable wait"), "wait in the message"),
    (dict(Q5="wait", Q3="not determined", Q4="not determined"), "wait in the message"),
    (dict(ARRIVAL, Q3="send time", Q4="yes"), "stay in the message"),
    (dict(Q1="by configuration", Q2="yes", Q5="derivable stay"), "stay in the message"),
    (dict(Q5="stay"), "stay in the message"),
    (dict(ARRIVAL, Q3="send time", Q4="no"), "arrival only"),
    (dict(ARRIVAL, Q3="request arrival", Q4="no"), "arrival only"),
    (dict(Q1="always", Q2="no"), "nothing"),
    (dict(Q3="send time", Q4="yes"), "nothing"),
    (dict(ARRIVAL, Q3="not determined", Q4="not determined"),
     "arrival only (unless Q3, Q4)"),
    (dict(ARRIVAL, Q3="not determined", Q4="no"), "arrival only"),
    (dict(Q1="not determined", Q2="not determined"), "nothing (unless Q1, Q2)"),
])
def test_the_verdict_follows_the_registered_rules(answers, said):
    assert ba.verdict(mode(**answers)) == said


@pytest.mark.parametrize("answer, said", [
    ("standing", "yes"), ("credit or several", "yes"), ("one at a time", "no"), ("none", "no"),
    ("not determined", "not determined")])
def test_requests_wait_where_they_can_stand_or_several_can(answer, said):
    assert ba.requests_wait(mode(Q7=answer)) == said


@pytest.mark.parametrize("answer, said", [
    ("per message", "yes"), ("per request", "yes"), ("aggregate only", "no"), ("none", "no"),
    ("not determined", "not determined")])
def test_broker_access_counts_only_timing_per_message_or_request(answer, said):
    assert ba.broker_access(mode(Q6=answer)) == said


def test_the_stamps_are_named_with_their_resolution_and_kind():
    assert ba.stamps(mode()) == ("none", "none")
    assert ba.stamps(mode(Q1="by configuration", Q2="yes")) == (
        "arrival_ms (ms, arrival, by configuration)", "none")
    assert ba.stamps(mode(Q1="always", Q2="yes", Q3="send time", Q4="yes")) == (
        "arrival_ms (ms, arrival); out_ms (ms, send time)", "none")
    assert ba.stamps(mode(Q1="always", Q2="no", Q3="request arrival", Q4="no")) == (
        "none", "arrival_ms (ms, arrival); out_ms (ms, request arrival)")
    m = mode(Q5="derivable stay")
    m["Q5"]["resolution"] = "s"
    assert ba.stamps(m) == ("a duration (s, derivable stay)", "none")
    m["Q5"].update(field="expiry interval", answer="not determined")
    assert ba.stamps(m) == ("none", "none")


def test_the_table_has_a_row_per_mode():
    rows = ba.table([("b.json", broker(mode(), mode(Q7="standing")))]).splitlines()
    assert len(rows) == 4
    assert rows[2] == "| Example MQ | consumers | 1.2.3 | nothing | none | none | no | no |"
    assert rows[3].endswith("| yes | no |")


# --- the fetch-back ------------------------------------------------------------------------------

class Opener:
    """urlopen's stand-in: serves the pages it holds, and fails on any other URL."""

    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def __call__(self, request, timeout):
        self.asked.append((request.full_url, request.get_header("User-agent"), timeout))
        if request.full_url not in self.pages:
            raise OSError("no such page")
        return io.BytesIO(self.pages[request.full_url].encode("utf-8"))


def test_fetch_reads_the_page_as_text_with_the_checks_own_agent():
    opener = Opener({PINNED: "long brokerOutTime;\n"})
    assert ba.fetch(PINNED, opener) == "long brokerOutTime;\n"
    assert opener.asked == [(PINNED, ba.AGENT, 60)]


def test_a_page_is_read_as_it_is_and_if_html_without_its_tags():
    assert ba.readings("a  b\n c") == ["a b c"]
    page = "<html><style>p{}</style><p>The <code>x-opt</code>&amp;time</p><td>a</td><td>b</td>"
    assert ba.readings(page)[1:] == ["The x-opt&timeab", "The x-opt &time a b"]


def test_a_quote_is_found_exactly_by_its_spacing_or_not_at_all():
    assert ba.found("The  x-opt &time", "<p>The <code>x-opt</code> &amp;time</p>") == "exact"
    assert ba.found("a b", "<td>a</td><td>b</td>") == "exact"
    assert ba.found("foo(a,b)", "foo(a, b)") == "spacing"
    assert ba.found("brokerInTime", "brokerOutTime") is None


def test_check_fetches_each_page_once_and_reports_every_quote(tmp_path):
    m = mode(Q1="always", Q2="yes")
    m["Q1"]["evidence"] = [item("stamp =  now()", DOCS)]
    m["Q2"]["evidence"] = [item("not on the page")]
    m["Q3"]["evidence"] = [item("x", "https://gone.example.org/x")]
    m["Q7"]["evidence"] = [item("stamp=now()")]
    brokers = ba.load([write(tmp_path, broker(m))])
    opener = Opener({PINNED: "stamp = now(); version = 1.2.3", DOCS: "<p>stamp = now()</p>"})
    lines, failures = ba.check(brokers, lambda url: ba.fetch(url, opener))
    assert failures == 2
    assert [line.split()[0] for line in lines] == [
        "OK", "OK", "OK", "MISSING", "FETCH", "OK", "OK", "OK"]
    assert "OK (spacing)" in lines[-1]
    assert sorted(set(url for url, _, _ in opener.asked)) == sorted(
        [PINNED, DOCS, "https://gone.example.org/x"])
    assert len(opener.asked) == 3


def test_every_quote_names_where_it_stands():
    b = broker()
    del b["modes"][0]["Q5"]
    where = [w for w, _, _ in ba.every_quote([("x/batch_09.json", b)])]
    assert where[:2] == ["batch_09.json:Example MQ.version", "batch_09.json:Example MQ/consumers.Q0"]
    assert "batch_09.json:Example MQ/consumers.Q5" not in where


# --- the command line ----------------------------------------------------------------------------

def test_validate_reports_the_count_and_exits_by_the_faults(tmp_path):
    out = io.StringIO()
    assert ba.main(["validate", write(tmp_path, broker(mode(), mode()))], out) == 0
    assert out.getvalue() == "1 brokers, 2 modes, 0 faults\n"
    out = io.StringIO()
    assert ba.main(["table", write(tmp_path, broker(group="Z"), name="bad.json")], out) == 1
    assert out.getvalue() == "bad.json:Example MQ: group is A or B\n1 brokers, 1 modes, 1 faults\n"


def test_table_and_check_on_sound_records(tmp_path):
    path = write(tmp_path, broker())
    out = io.StringIO()
    assert ba.main(["table", path], out) == 0
    assert out.getvalue().startswith("| Broker | Mode |")
    out = io.StringIO()
    assert ba.main(["check", path], out, get=lambda url: "stamp = now() version = 1.2.3") == 0
    assert out.getvalue().endswith("7 quotes, 0 not found or not fetched\n")
    out = io.StringIO()
    assert ba.main(["check", path], out, get=lambda url: "") == 1
    assert out.getvalue().endswith("7 quotes, 7 not found or not fetched\n")


def test_the_record_form_in_the_protocol_is_one_this_script_reads():
    """The protocol's own example, with its placeholders filled, passes the form check."""
    text = open(os.path.join(os.path.dirname(os.path.dirname(HERE)), "data", "broker_audit",
                             "PROTOCOL.md"), encoding="utf-8").read()
    example = text.split("```json\n", 1)[1].split("```", 1)[0]
    filled = example.replace('["..."]', json.dumps([item()])).replace('"..."', '"x"')
    record = json.loads(filled)
    b = copy.deepcopy(record["brokers"][0])
    b["version_evidence"] = [item()]
    b["modes"][0]["Q0"]["evidence"] = [item()]
    assert ba.broker_faults(b, "example") == []


def test_the_committed_records_keep_their_form_and_give_the_verdicts_reported():
    """The records coded on 27 October 2026, as data/broker_audit/README.md reports them: every one
    in the protocol's form, no broker that sends a request's arrival, and every read-back
    agreeing with its answer."""
    brokers = ba.load()
    assert [f for _, b in brokers for f in ba.broker_faults(b, b["broker"])] == []
    modes = [m for _, b in brokers for m in b["modes"]]
    assert (len(brokers), len(modes)) == (23, 41)
    said = collections.Counter(ba.verdict(m).split(" (")[0] for m in modes)
    assert said == {"arrival only": 23, "stay in the message": 11, "nothing": 7}
    assert collections.Counter(ba.requests_wait(m) for m in modes) == {
        "yes": 32, "no": 8, "not determined": 1}
    assert sum(len(m["read_back"]) for m in modes) == 72
    assert all(r["agrees"] for m in modes for r in m["read_back"])
    assert sum(1 for _ in ba.every_quote(brokers)) == 1477
