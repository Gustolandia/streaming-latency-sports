"""A8 compares two clients, so the files they leave behind have to be indistinguishable.

The analysis must not be able to tell which client produced a run. That is not only the columns:
it is which files exist. scripts/pilot_checks.py reads the trip and the negative rate -- the
quantity the law is about, and the quantity A8 compares between the clients -- from
consumer_events.csv, and cloud/azure/campaign.sh refuses a run whose consumer_events.csv is
missing. A Java client writing consumer.csv alone would have failed every run of its half of A8
before a single one was judged, and the failure would have read as the run's fault.

These read the two clients' sources and hold their headers to each other. They are source checks
because the Java client cannot be run here: this machine's clock steps in about a millisecond and
LawClock refuses it, which is the other thing A8's design insists on.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
SCRIPTS = ROOT / "scripts"
JAVA = ROOT / "harness" / "java" / "src"


def python_fieldnames(script, which=0):
    """The `which`-th csv fieldnames list in one of our Python clients."""
    source = (SCRIPTS / script).read_text(encoding="utf-8")
    starts = [m.start() for m in re.finditer(r"fieldnames=\[", source)]
    start = starts[which]
    return re.findall(r'"([^"]+)"', source[start:source.index("]", start)])


def java_header(java_file, writer):
    """The header one of the Java client's writers writes, as a list of columns."""
    source = (JAVA / java_file).read_text(encoding="utf-8")
    start = source.index('%s.write("run_id,' % writer)
    chunk = source[start:source.index(");", start)]
    return [c for c in "".join(re.findall(r'"([^"]*)"', chunk)).split(",") if c]


class TestTheTwoClientsWriteTheSameColumns:

    def test_the_producers_agree(self):
        assert java_header("LawProducer.java", "writer") == python_fieldnames("kafka_producer.py")

    def test_the_consumers_agree_on_consumer_csv(self):
        assert java_header("LawConsumer.java", "writer") == python_fieldnames("kafka_consumer.py")

    def test_the_consumers_agree_on_the_event_log(self):
        """The file pilot_checks.py reads the negative rate from."""
        assert (java_header("LawConsumer.java", "eventWriter")
                == python_fieldnames("kafka_consumer.py", which=1))


class TestTheTwoClientsWriteTheSameFiles:

    def test_the_java_consumer_writes_the_event_log_at_all(self):
        source = (JAVA / "LawConsumer.java").read_text(encoding="utf-8")
        assert "_events.csv" in source, (
            "pilot_checks.py reads the trip and the negative rate from consumer_events.csv, and "
            "the campaign refuses a run without it")

    def test_it_names_the_event_log_beside_its_output_as_python_does(self):
        """Python: Path(out).with_name(Path(out).stem + '_events.csv'). Under test --out is a
        temporary file, so a run-directory path would write over a tracked one."""
        source = (JAVA / "LawConsumer.java").read_text(encoding="utf-8")
        assert 'stem + "_events.csv"' in source and "out.getFileName()" in source

    @pytest.mark.parametrize("needed", ["event_id", "t_consume_ns"])
    def test_the_event_log_carries_what_the_negative_rate_is_computed_from(self, needed):
        checks = (SCRIPTS / "pilot_checks.py").read_text(encoding="utf-8")
        assert needed in checks, "pilot_checks.py no longer reads %s; this test is stale" % needed
        assert needed in java_header("LawConsumer.java", "eventWriter")

    def test_the_receive_stamp_is_one_reading_under_two_names(self):
        """Python sets t_cons_recv_ns = t_consume_ns from a single read. Reading the clock twice
        would put a poll's scheduling between two numbers meant to be the same one."""
        source = (JAVA / "LawConsumer.java").read_text(encoding="utf-8")
        assert source.count("long tConsRecvNs = LawClock.nowNs();") == 1
        assert source.count("Long.toString(tConsRecvNs)") == 2


class TestTheTwoClientsSendTheSameMessage:
    """The event log copies fields out of the message, so a field one client omits is a column
    that is full for one half of A8 and empty for the other."""

    def python_message_fields(self):
        source = (SCRIPTS / "kafka_producer.py").read_text(encoding="utf-8")
        start = source.index("        msg = {")
        return re.findall(r'"([^"]+)":', source[start:source.index("        }", start)])

    def java_message_fields(self):
        source = (JAVA / "LawProducer.java").read_text(encoding="utf-8")
        start = source.index("private static String message(")
        body = source[start:source.index("return json.toString();", start)]
        names = re.findall(r'Json\.field\(json, "([^"]+)"', body)
        names += re.findall(r'\\"([a-z0-9_]+)\\":', body)
        # The last two share one append, and the patterns above overlap on it, so keep first sight.
        return list(dict.fromkeys(names))

    def test_both_carry_the_same_fields(self):
        assert sorted(self.java_message_fields()) == sorted(self.python_message_fields())

    def test_the_event_log_can_fill_every_column_it_copies(self):
        """Every event-log column that comes from the message must be a field both clients send."""
        from_message = ("event_id", "match_id", "t_sim_seconds", "t_emit_offset_s",
                        "t_emit_planned_ns", "s3_uid", "s3_rev", "s3_is_correction")
        sent = set(self.java_message_fields()) & set(self.python_message_fields())
        assert set(from_message) <= sent
        assert set(from_message) <= set(java_header("LawConsumer.java", "eventWriter"))
