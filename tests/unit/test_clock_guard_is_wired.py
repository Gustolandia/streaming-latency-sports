"""Every process that stamps a time must measure its clock first, and say what it read.

The unit suite runs on a machine whose wall clock steps in about a millisecond, so conftest gives
law_clock a fine clock to read and the guard passes. That is the right thing for a test with a
mocked broker and the wrong thing to leave unwatched: it would let the guard be deleted without a
single test going red. These read the source instead, so the wiring is checked and not the clock.
"""
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent.parent / "scripts"

#: The four processes that read the wall clock to make a measurement, and the name each announces
#: itself by. The Java client's own guard is held by harness/java/src/LawSelfTest.java.
STAMPERS = {
    "kafka_producer.py": "the Kafka producer",
    "kafka_consumer.py": "the Kafka consumer",
    "redis_producer.py": "the Redis producer",
    "redis_consumer.py": "the Redis consumer",
}


@pytest.mark.parametrize("script,who", sorted(STAMPERS.items()))
class TestTheGuardIsWiredIntoEveryStamper:

    def source(self, script):
        return (SCRIPTS / script).read_text(encoding="utf-8")

    def test_it_asks_the_clock_before_it_runs(self, script, who):
        assert "law_clock.demand_usable_resolution(" in self.source(script)

    def test_it_names_itself_so_the_stop_says_which_process_refused(self, script, who):
        assert who in self.source(script)

    def test_it_records_what_the_clock_read_in_the_runs_own_files(self, script, who):
        """The figure belongs in the record, not only in the decision to go on."""
        assert "clock_resolution_ns=" in self.source(script)


class TestTheTwoClientsAreHeldToOneNumber:
    """A8 compares our Python client with Kafka's Java one; a bar only one of them cleared would
    be one more difference between them."""

    def test_the_java_client_and_the_python_one_demand_the_same_resolution(self):
        java = (SCRIPTS.parent / "harness" / "java" / "src" / "LawClock.java").read_text(
            encoding="utf-8")
        import sys
        sys.path.insert(0, str(SCRIPTS))
        import law_clock
        assert "FINEST_USABLE_NS = %d_000L" % (law_clock.FINEST_USABLE_NS // 1000) in java
