"""Where the two consumers take their stamps, relative to the payload parse.

Round 43's finding, made into a gate. Supplement S43.1 audited three stamps, all
producer-side, while every span the paper reports *ends* at a consumer stamp -- and the two
consumers do not take theirs in the same place:

* `kafka_consumer.py` hands the client a `value_deserializer`, so the payload is parsed
  inside `poll()`. The parse falls **before** `t_cons_recv_ns`.
* `redis_consumer.py` stamps first and calls `json.loads` afterwards. The same parse falls
  **after** it.

So the transport proxy carries one broker's parse and not the other's: a median handling span
of 281 ns against 19,480 ns, a factor of 69. The manuscript now discloses it and bounds it at
2.4% of the delivery it sits inside. That disclosure is only true of the code it was measured
from, which is what these tests pin.

They are deliberately structural rather than numerical. The numbers live in the ledger and
have their own gates; what cannot be recovered from the ledger is *why* the two arms differ,
and a future campaign that quietly moved one stamp would leave every number in place and make
the supplement's explanation false.
"""
import re
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent.parent / "scripts"


def source(name):
    path = SCRIPTS / name
    if not path.exists():                               # pragma: no cover - both ship here
        pytest.skip("%s absent" % name)
    return path.read_text(encoding="utf-8")


def offset(text, pattern):
    m = re.search(pattern, text)
    assert m, "could not find %r; the consumer has been restructured" % pattern
    return m.start()


class TestKafkaParsesBeforeItStamps:
    def test_the_client_deserializes_the_payload_itself(self):
        """`value_deserializer` is what puts the parse inside `poll()`. Drop it and the
        parse moves into the loop body, changing which span carries it."""
        assert "value_deserializer" in source("kafka_consumer.py")

    def test_the_receive_stamp_comes_after_the_value_is_in_hand(self):
        text = source("kafka_consumer.py")
        assert offset(text, r"v = msg\.value") < offset(text, r"t_consume_ns = now_ns\(\)")

    def test_the_output_stamp_is_the_next_statement(self):
        """A few hundred nanoseconds apart, and the supplement says so. Anything between
        them would put work inside TTI that is not inside the transport proxy."""
        text = source("kafka_consumer.py")
        between = text[offset(text, r"t_cons_recv_ns = t_consume_ns"):
                       offset(text, r"t_output_ns = now_ns\(\)")]
        code = [ln.strip() for ln in between.splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        assert len(code) <= 1, "work has appeared between the consumer's two stamps: %s" % code


class TestRedisStampsBeforeItParses:
    def test_the_parse_sits_between_the_two_stamps(self):
        """This is the asymmetry itself. It is not a defect to be fixed here -- the campaign
        that measured it cannot be re-run -- but it must stay true of the code the
        supplement describes, or the description becomes fiction."""
        text = source("redis_consumer.py")
        recv = offset(text, r"t_cons_recv_ns = t_consume_ns")
        parse = offset(text, r"json\.loads\(fields\[")
        out = offset(text, r"t_output_ns = now_ns\(\)")
        assert recv < parse < out, \
            "the Redis consumer's payload parse has moved; S43.1 describes it as sitting " \
            "between t_recv and t_out, and the 19.5 us handling span is that parse"


class TestTheAsymmetryIsDisclosedWhereItIsDescribed:
    def test_the_supplement_names_both_placements(self):
        supp = (SCRIPTS.parent / "supplement.tex").read_text(encoding="utf-8")
        # LaTeX escapes the underscores, so compare on the text a reader sees.
        body = " ".join(supp.replace("\\_", "_").split())
        assert "value_deserializer" in body, \
            "S43.1 must say what puts Kafka's parse before the stamp"
        assert "json.loads" in body, "S43.1 must say what puts Redis's parse after it"
        for macro in (r"\spanKafkaHandlingNs", r"\spanRedisHandlingNs",
                      r"\spanHandlingRatio", r"\spanHandlingSharePct"):
            assert macro in body, "%s must be read from the ledger, not typed" % macro

    def test_the_main_text_bounds_it_where_it_could_matter(self):
        """The comparison it could touch is the broker equivalence, so the bound belongs
        beside that claim rather than only in a supplement a reader may not reach."""
        paper = (SCRIPTS.parent / "paper.tex").read_text(encoding="utf-8")
        i = paper.find(r"\label{sec:brokers}")
        assert i > 0, "the broker section must exist"
        section = " ".join(paper[i:i + 2500].split())
        assert r"\spanHandlingSharePct" in section, \
            "the asymmetry must be bounded where the comparison it could move is made"
        assert "deserializ" in section, "and the reader must be told what causes it"
