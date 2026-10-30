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
AUDIT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "data", "broker_audit")


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


def producer(acknowledgment=True, **answers):
    """A producer interface whose answers are those given, and otherwise those of an
    acknowledgment that carries no broker time (or of no acknowledgment at all)."""
    out = {"interface": "publish",
           "P0": {"acknowledgment": acknowledgment,
                  "fields": ["message id"] if acknowledgment else [], "evidence": [item()]},
           "not_determined": [], "read_back": []}
    base = dict.fromkeys(ba.PRODUCER_ANSWERS, "no" if acknowledgment else "not applicable")
    base.update(answers)
    for q, answer in base.items():
        out[q] = {"answer": answer,
                  "evidence": [] if answer == "not applicable" else [item()]}
    if base["P1"] in ba.STAMPED:
        out["P1"].update(field="received_us", resolution="us", which="receive time")
    if base["P2"] in ba.STAMPED:
        out["P2"].update(field="sent_us", resolution="us")
    return out


def broker(*modes, **keys):
    out = {"broker": "Example MQ", "group": "A", "version": "1.2.3",
           "version_evidence": [item("version = 1.2.3")], "modes": list(modes) or [mode()],
           "producers": [producer()]}
    out.update(keys)
    return out


FOUND = [{"route": "seed", "source": "AMENDMENT_01.md", "query": "seed list"}]


def wide(**keys):
    """A broker of group C, found by the wide search."""
    return broker(**dict(dict(group="C", kind="broker", found_by=FOUND), **keys))


def write(tmp_path, *brokers, name="batch_01.json", precedents=None):
    path = tmp_path / name
    body = {"audited_utc": "2026-10-27", "brokers": list(brokers)}
    if precedents is not None:
        body = {"audited_utc": "2026-10-27", "precedents": precedents}
    path.write_text(json.dumps(body), encoding="utf-8")
    return str(path)


def precedent(**keys):
    out = {"name": "NTP", "standard": "RFC 5905, section 7.3",
           "sends": ["receive time (server clock)", "transmit time (server clock)"],
           "split": "The client subtracts the server's hold from its round trip.",
           "evidence": [item("Receive Timestamp (rec)", DOCS)]}
    out.update(keys)
    return out


def tiny_pdf(text):
    """A one-page PDF that shows `text`, built by hand so that the tests need no PDF writer."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 100] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            None,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    stream = b"BT /F1 12 Tf 10 50 Td (" + text.encode("latin-1") + b") Tj ET"
    objs[3] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


# --- the form ------------------------------------------------------------------------------------

def test_load_reads_the_files_named_and_by_default_the_batches(tmp_path, monkeypatch):
    one = write(tmp_path, broker(), broker(broker="Other MQ"))
    assert [b["broker"] for _, b in ba.load([one])] == ["Example MQ", "Other MQ"]
    write(tmp_path, broker(broker="Second"), name="batch_02.json")
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ba, "RECORDS", str(tmp_path / "batch_*.json"))
    assert [b["broker"] for _, b in ba.load()] == ["Example MQ", "Other MQ", "Second"]


def test_the_precedents_are_read_from_their_own_file_when_it_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(ba, "PRECEDENTS", str(tmp_path / "precedents.json"))
    assert ba.load_precedents() == []
    write(tmp_path, name="precedents.json", precedents=[precedent()])
    assert [p["name"] for _, p in ba.load_precedents()] == ["NTP"]
    assert ba.load_precedents([write(tmp_path, broker())]) == []


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
    assert ba.broker_faults(wide(producers=[producer(), producer(False),
                                            producer(P1="by configuration", P2="always")]),
                            "c") == []


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


def test_a_producer_missing_a_question_is_named_and_nothing_else_is_asked():
    p = producer()
    del p["P2"]
    assert ba.producer_faults(p, "p") == ["p: P2 is missing"]


def test_every_fault_of_a_producer_is_named():
    p = producer(P1="always", P2="sometimes", P3="not applicable")
    p["P0"] = {"acknowledgment": True, "fields": [], "evidence": []}
    del p["P1"]["resolution"]
    del p["P1"]["which"]
    p["P1"]["evidence"] = [{"url": PINNED}]
    p["not_determined"] = "P3"
    assert ba.producer_faults(p, "p") == [
        "p.P0: the list of fields is empty",
        "p.P0: no evidence",
        "p.P1[0]: an item is {url, quote}",
        "p.P1: a time is recorded with its resolution",
        "p.P2: 'sometimes' is not an answer the amendment allows",
        "p.P3: 'not applicable' exactly when there is no acknowledgment",
        "p.P1: which is 'receive time' or 'store time'",
        "p: not_determined is a list",
    ]
    q = producer(False, P1="no")
    q["P0"]["acknowledgment"] = "no"
    q["P1"]["evidence"] = []
    q["P2"]["evidence"] = [item("x", "ftp://example.org/x")]
    assert ba.producer_faults(q, "q") == [
        "q.P0: acknowledgment is true or false",
        "q.P1: no evidence",
        "q.P2[0]: the URL is not https"]
    r = producer(False, P3="no")
    r["P1"]["evidence"] = []
    r["read_back"] = {}
    assert ba.producer_faults(r, "r") == [
        "r.P3: 'not applicable' exactly when there is no acknowledgment",
        "r: read_back is a list"]


def test_every_fault_of_a_broker_is_named():
    b = broker(group="Z", version_evidence=[], modes=[], producers=[])
    del b["broker"]
    assert ba.broker_faults(b, "b") == [
        "b: broker is missing", "b: group is A, B or C", "b: the version has no evidence",
        "b: no modes", "b: no producers"]
    bad = mode()
    bad["Q2"]["answer"] = "maybe"
    worse = producer()
    worse["P3"]["answer"] = "maybe"
    assert ba.broker_faults(broker(bad, producers=[worse]), "b") == [
        "b/consumers.Q2: 'maybe' is not an answer the protocol allows",
        "b/consumers.Q2: with Q1 'no', it is 'not applicable'",
        "b/publish.P3: 'maybe' is not an answer the amendment allows"]


def test_a_broker_of_group_c_says_what_it_is_and_how_it_was_found():
    assert ba.found_by_faults(wide(), "c") == []
    b = wide(kind="queue", found_by=[])
    assert ba.broker_faults(b, "c") == [
        "c: kind is one the amendment names", "c: found_by is empty"]
    b = wide(found_by=FOUND + ["reddit", {"route": "route 3", "source": "x", "query": "y"},
                               {"route": "route 2", "source": "x"}])
    del b["kind"]
    assert ba.found_by_faults(b, "c") == [
        "c: kind is one the amendment names",
        "c.found_by[1]: an item is {route, source, query}, on a route the amendment names",
        "c.found_by[2]: an item is {route, source, query}, on a route the amendment names",
        "c.found_by[3]: an item is {route, source, query}, on a route the amendment names"]
    assert ba.broker_faults(broker(), "a") == []


def test_every_fault_of_a_precedent_is_named():
    assert ba.precedent_faults(precedent(), "p") == []
    p = precedent(standard=" ", sends=[], evidence=[])
    del p["split"]
    assert ba.precedent_faults(p, "p") == [
        "p: standard is missing", "p: split is missing",
        "p: the list of what it sends is empty", "p: no evidence"]
    assert ba.precedent_faults(precedent(evidence=[item("q", "http://x.org")]), "p") == [
        "p.evidence[0]: the URL is not https"]


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


@pytest.mark.parametrize("acked, answers, said", [
    (True, dict(P1="always", P2="always"), "hold in the acknowledgment"),
    (True, dict(P1="by configuration", P2="by configuration"), "hold in the acknowledgment"),
    (True, dict(P3="hold"), "hold in the acknowledgment"),
    (True, dict(P3="derivable hold", P1="not determined"), "hold in the acknowledgment"),
    (True, dict(P1="always"), "receive time only"),
    (True, dict(P2="by configuration"), "send time only"),
    (True, {}, "nothing"),
    (True, dict(P1="always", P2="not determined"), "receive time only (unless P2)"),
    (True, dict(P1="not determined", P2="no", P3="no"), "nothing (unless P1)"),
    (True, dict(P1="no", P2="no", P3="not determined"), "nothing (unless P3)"),
    (False, {}, "no acknowledgment"),
])
def test_the_producers_verdict_follows_the_amendments_rules(acked, answers, said):
    assert ba.ack_verdict(producer(acked, **answers)) == said


def test_the_times_in_an_acknowledgment_are_named_with_their_resolution_and_kind():
    assert ba.ack_times(producer()) == "none"
    assert ba.ack_times(producer(P1="by configuration", P2="always")) == (
        "received_us (us, receive time, by configuration); sent_us (us, send time)")
    p = producer(P3="derivable hold")
    assert ba.ack_times(p) == "a duration (?, derivable hold)"
    p["P1"] = {"answer": "always", "resolution": "ms", "which": "store time", "evidence": []}
    p["P3"].update(field="hold_ns", resolution="ns", answer="hold")
    assert ba.ack_times(p) == "a time (ms, store time); hold_ns (ns, hold)"


def test_the_producers_table_has_a_row_per_producer_interface():
    qos0 = producer(False)
    qos0["interface"] = "QoS 0"
    b = wide(producers=[producer(), qos0])
    rows = ba.producer_table([("b.json", b), ("a.json", broker(producers=[]))]).splitlines()
    assert len(rows) == 4
    assert rows[2] == "| Example MQ | publish | 1.2.3 | nothing | none |"
    assert rows[3] == "| Example MQ | QoS 0 | 1.2.3 | no acknowledgment | none |"


# --- the fetch-back ------------------------------------------------------------------------------

class Opener:
    """urlopen's stand-in: serves the pages it holds, and fails on any other URL."""

    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def __call__(self, request, timeout):
        self.asked.append((request.full_url, request.get_header("User-agent"), timeout))
        if request.full_url not in self.pages:
            raise OSError("no such page")
        page = self.pages[request.full_url]
        return io.BytesIO(page if isinstance(page, bytes) else page.encode("utf-8"))


def test_fetch_reads_the_page_as_text_with_the_checks_own_agent():
    opener = Opener({PINNED: "long brokerOutTime;\n"})
    assert ba.fetch(PINNED, opener) == "long brokerOutTime;\n"
    assert opener.asked == [(PINNED, ba.AGENT, 60)]


def test_fetch_reads_a_pdf_as_its_text():
    pdf = "https://docs.example.org/spec.pdf"
    opener = Opener({pdf: tiny_pdf("Receive Timestamp (rec): the time the request arrived")})
    assert ba.found("Receive Timestamp (rec)", ba.fetch(pdf, opener)) == "exact"


def test_a_pdfs_pages_are_read_in_order_and_a_blank_page_gives_nothing():
    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class Reader:
        def __init__(self, stream):
            assert stream.read() == b"%PDF-1.4 bytes"
            self.pages = [Page("first"), Page(None), Page("third")]

    assert ba.pdf_text(b"%PDF-1.4 bytes", Reader) == "first\n\nthird"


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
    brokers = ba.load([write(tmp_path, broker(m, producers=[]))])
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
    del b["producers"][0]["P3"]
    where = [w for w, _, _ in ba.every_quote(
        [("x/batch_09.json", b)], [("x/precedents.json", precedent()), ("y.json", {})])]
    assert where[:2] == ["batch_09.json:Example MQ.version", "batch_09.json:Example MQ/consumers.Q0"]
    assert "batch_09.json:Example MQ/consumers.Q5" not in where
    assert where[-4:] == ["batch_09.json:Example MQ/publish.P0", "batch_09.json:Example MQ/publish.P1",
                          "batch_09.json:Example MQ/publish.P2", "precedents.json:NTP"]


# --- the command line ----------------------------------------------------------------------------

def test_validate_reports_the_count_and_exits_by_the_faults(tmp_path):
    out = io.StringIO()
    assert ba.main(["validate", write(tmp_path, broker(mode(), mode()))], out) == 0
    assert out.getvalue() == "1 brokers, 2 modes, 1 producers, 0 precedents, 0 faults\n"
    out = io.StringIO()
    assert ba.main(["table", write(tmp_path, broker(group="Z"), name="bad.json")], out) == 1
    assert out.getvalue() == ("bad.json:Example MQ: group is A, B or C\n"
                              "1 brokers, 1 modes, 1 producers, 0 precedents, 1 faults\n")
    out = io.StringIO()
    bad = write(tmp_path, name="precedents.json", precedents=[precedent(sends=[])])
    assert ba.main(["validate", bad], out) == 1
    assert out.getvalue() == ("precedents.json:NTP: the list of what it sends is empty\n"
                              "0 brokers, 0 modes, 0 producers, 1 precedents, 1 faults\n")


def test_table_producers_and_check_on_sound_records(tmp_path):
    path = write(tmp_path, broker())
    ntp = write(tmp_path, name="precedents.json", precedents=[precedent()])
    out = io.StringIO()
    assert ba.main(["table", path], out) == 0
    assert out.getvalue().startswith("| Broker | Mode |")
    out = io.StringIO()
    assert ba.main(["producers", path], out) == 0
    assert out.getvalue().startswith("| Broker | Producer interface |")
    out = io.StringIO()
    page = "stamp = now() version = 1.2.3 Receive Timestamp (rec)"
    assert ba.main(["check", path, ntp], out, get=lambda url: page) == 0
    assert out.getvalue().endswith("12 quotes, 0 not found or not fetched\n")
    out = io.StringIO()
    assert ba.main(["check", path], out, get=lambda url: "") == 1
    assert out.getvalue().endswith("11 quotes, 11 not found or not fetched\n")


def test_the_record_forms_in_the_protocol_and_the_amendment_are_ones_this_script_reads():
    """The protocol's and the amendment's own examples, with their placeholders filled, pass the
    form check."""
    def example(name):
        text = open(os.path.join(AUDIT, name), encoding="utf-8").read()
        block = text.split("```json\n", 1)[1].split("```", 1)[0]
        return json.loads(block.replace('["..."]', json.dumps([item()])).replace('"..."', '"x"'))

    b = copy.deepcopy(example("PROTOCOL.md")["brokers"][0])
    b["version_evidence"] = [item()]
    b["modes"][0]["Q0"]["evidence"] = [item()]
    b["producers"] = [example("AMENDMENT_01.md")]
    assert ba.broker_faults(b, "example") == []


# --- the committed records -----------------------------------------------------------------------

def base(said):
    """A verdict without its "(unless ...)"."""
    return said.split(" (")[0]


def test_the_committed_records_keep_their_form_and_give_the_verdicts_reported():
    """The records coded from 27 to 29 October 2026, as data/broker_audit/README.md reports them:
    every one in the form the protocol and the amendment registered, the consumers' and the
    producers' verdicts, the requests that can wait, the read-backs and the quotes."""
    brokers = ba.load()
    assert [f for _, b in brokers for f in ba.broker_faults(b, b["broker"])] == []
    assert collections.Counter(b["group"] for _, b in brokers) == {"A": 18, "B": 5, "C": 199}
    modes = [m for _, b in brokers for m in b["modes"]]
    producers = [p for _, b in brokers for p in b["producers"]]
    assert (len(brokers), len(modes), len(producers)) == (222, 418, 390)
    assert collections.Counter(base(ba.verdict(m)) for m in modes) == {
        "wait in the message": 2, "stay in the message": 79, "arrival only": 149, "nothing": 188}
    assert collections.Counter(base(ba.ack_verdict(p)) for p in producers) == {
        "hold in the acknowledgment": 2, "receive time only": 38, "send time only": 4,
        "nothing": 248, "no acknowledgment": 98}
    assert collections.Counter(ba.requests_wait(m) for m in modes) == {
        "yes": 308, "no": 100, "not determined": 10}
    kept = [b["broker"] for _, b in brokers for m in b["modes"]
            if m["Q3"]["answer"] == "request arrival" and m["Q4"]["answer"] == "no"]
    assert (len(kept), len(set(kept))) == (20, 19)
    readings = [r for part in modes + producers for r in part["read_back"]]
    assert (len(readings), sum(1 for r in readings if not r["agrees"])) == (881, 15)
    changed = [part[q]["changed_on_read_back"] for part in modes + producers
               for q in sorted(ba.ANSWERS) + sorted(ba.PRODUCER_ANSWERS)
               if q in part and "changed_on_read_back" in part[q]]
    assert (len(changed), sum(1 for c in changed if "at" in c)) == (50, 4)
    assert len(ba.load_precedents()) == 42
    assert sum(1 for _ in ba.every_quote(brokers, ba.load_precedents())) == 14069


def test_the_cases_the_readme_names_carry_what_it_says():
    """The two interfaces that send the wait, the two acknowledgments that carry a hold, and the
    first audit's 23 brokers with the one correction and the one mode amendment 1 added."""
    brokers = ba.load()
    assert sorted(b["broker"] for _, b in brokers for m in b["modes"]
                  if ba.verdict(m) == "wait in the message") == ["Azurite", "Eclipse Zenoh"]
    assert sorted(b["broker"] for _, b in brokers for p in b["producers"]
                  if ba.ack_verdict(p) == "hold in the acknowledgment") == [
        "KubeMQ (community edition)", "Liftbridge"]
    first = [m for _, b in brokers if b["group"] != "C" for m in b["modes"]]
    assert collections.Counter(base(ba.verdict(m)) for m in first) == {
        "arrival only": 22, "stay in the message": 13, "nothing": 7}
    assert sorted((b["broker"], m["mode"], q) for _, b in brokers for m in b["modes"]
                  for q in sorted(ba.ANSWERS) if "corrected_in_amendment_1" in m[q]) == [
        ("Apache ActiveMQ Artemis", "AMQP 1.0 consumers", q) for q in ("Q3", "Q4", "Q5")]
    assert [(b["broker"], m["mode"]) for _, b in brokers for m in b["modes"]
            if m.get("added_in_amendment_1")] == [("Apache ActiveMQ Classic", "AMQP 1.0 consumers")]


def test_the_counts_the_brief_gives_beside_the_verdicts():
    """The brief's other counts: the brokers with a stay, the brokers that send a consumer no
    broker time, the stays known only to the whole second, the times kept and not sent, how the
    coded brokers were found, and the answers not determined."""
    brokers = ba.load()
    modes = [(b, m) for _, b in brokers for m in b["modes"]]
    said = collections.defaultdict(set)
    for b, m in modes:
        said[b["broker"]].add(base(ba.verdict(m)))
    assert sum(1 for v in said.values() if "stay in the message" in v) == 53
    assert sum(1 for v in said.values() if v == {"nothing"}) == 86
    assert sum(1 for _, m in modes if base(ba.verdict(m)) == "stay in the message"
               and not (m["Q3"]["answer"] == "send time" and m["Q4"]["answer"] == "yes")
               and m["Q5"]["answer"] == "derivable stay" and m["Q5"].get("resolution") == "s") == 36
    sent = [b["broker"] for b, m in modes
            if m["Q3"]["answer"] == "send time" and m["Q4"]["answer"] == "no"]
    assert (len(sent), len(set(sent))) == (61, 47)
    assert sum(1 for _, m in modes if m["Q3"]["answer"] == "request arrival"
               and m["Q4"]["answer"] == "no"
               and str(m["Q3"].get("resolution", "")).startswith("ns")) == 10
    assert collections.Counter(
        "seed" if any(f["route"] == "seed" for f in b["found_by"]) else "search"
        for _, b in brokers if b["group"] == "C") == {"seed": 111, "search": 88}
    parts = [p for _, b in brokers for p in b["modes"] + b["producers"]]
    assert sum(len(p["not_determined"]) for p in parts) == 333


def test_the_population_gives_every_product_found_a_decision_and_its_reason():
    """candidates.json: one entry per product found, each coded broker exactly once and in the
    batch file that holds its record, and every other one with its reason and the class the
    README counts it under."""
    with open(os.path.join(AUDIT, "candidates.json"), encoding="utf-8") as fh:
        products = json.load(fh)["products"]
    assert collections.Counter(p["decision"] for p in products) == {
        "coded": 222, "out": 689, "not checked": 188, "screened out": 133, "copy": 68,
        "not readable": 2}
    assert sorted((p["record"], p["name"]) for p in products if p["decision"] == "coded") == sorted(
        (os.path.basename(path), b["broker"]) for path, b in ba.load())
    assert all(p["reason"] and p["class"] for p in products if p["decision"] != "coded")

    def classes(decision):
        return collections.Counter(p["class"] for p in products if p["decision"] == decision)

    assert classes("not checked") == {
        "under 1,000 stars": 115, "stars not readable on another code host": 36,
        "archived or retired": 36, "no push since 27 October 2023": 1}
    assert classes("out") == {
        "client library or framework": 235, "not a broker": 210,
        "stream processor or workflow engine": 115, "proxy or router that holds no message": 40,
        "brokerless messaging library": 30, "notification service to devices or people": 28,
        "documentation not public, or no longer online": 27, "shut down by the coding date": 4}
    assert classes("screened out") == {
        "not a broker": 30, "documentation not public, or no longer online": 28,
        "a copy of another broker": 23, "documentation not readable by the check": 22,
        "below the scope rule": 19, "shut down by the coding date": 11}


def test_the_search_log_has_every_search_with_what_it_surfaced():
    """search_log.json: 766 searches on the amendment's two routes, each with its date, source,
    query and the products it surfaced, then route 2's hits and the feature requests."""
    with open(os.path.join(AUDIT, "search_log.json"), encoding="utf-8") as fh:
        log = json.load(fh)
    assert collections.Counter(s["route"] for s in log["searches"]) == {
        "route 1": 610, "route 2": 156}
    assert sorted(collections.Counter(s["part"] for s in log["searches"]).values()) == [
        156, 189, 421]
    assert all(s["date"] and s["source"] and s["query"] and isinstance(s["surfaced"], list)
               for s in log["searches"])
    assert (len(log["time_hits"]), len(log["feature_requests"])) == (47, 14)


def test_the_tables_file_holds_the_tables_the_script_computes():
    """TABLES.md cannot go stale: it holds both tables exactly as `table` and `producers` print
    them from the committed records."""
    with open(os.path.join(AUDIT, "TABLES.md"), encoding="utf-8") as fh:
        text = fh.read()
    brokers = ba.load()
    assert ba.table(brokers) in text
    assert ba.producer_table(brokers) in text
