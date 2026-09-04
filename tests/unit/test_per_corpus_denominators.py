r"""A per-corpus numerator must not be quoted against the whole ledger's denominator.

`macros()` splits the OpenMessaging counts by driver, and its docstring says why:

    The Kafka/Redis split exists because the negative-sample story is scoped: the withdrawal
    rests on the Kafka-driver corpus staying at zero negatives, while the Redis-driver
    replication caught real ones. One unsplit total let a claim about one corpus be silently
    contradicted by the other.

The split was made for the *sample* counts and not for the *run* count, so for several rounds
Section IV-D read

    Across all \ombRuns runs the Kafka-driver corpus's \ombKafkaDiscarded discarded
    samples contain not one negative

with `\ombRuns` = 223, the whole ledger, against a Kafka-driver corpus of 214 -- and the whole
ledger holds 41,403 negatives, which the next sentence reports. The sentence had a true
reading. It also invited a reader to divide 10,913,263 by 223 and get a per-run rate belonging
to no corpus. There was no `\ombKafkaRuns` to reach for, so the prose reached for the only run
count that existed, which is the one the docstring warns about.

Round 51's referee judged the general rule -- every per-corpus quantity printed with a
per-corpus denominator -- too expensive to gate and better kept as an editorial habit. That is
right about the general rule. This is the narrow version: a short table of numerator macros
that each have a matching denominator, checked only for the mistake that actually happened.
Adding a family costs one line.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
GENERATED = REPO / "docs" / "generated" / "paper_numbers.tex"
DOCS = ("paper.tex", "supplement.tex")

#: (numerator macro, its own denominator, the whole-population denominator it must not sit
#: beside). Each entry is a family where a sentence naming a subset's count could reach for
#: the total's run count instead.
FAMILIES = (
    ("ombKafkaDiscarded", "ombKafkaRuns", "ombRuns"),
    ("ombKafkaNegatives", "ombKafkaRuns", "ombRuns"),
    ("ombRedisDiscarded", "ombRedisRuns", "ombRuns"),
    ("ombRedisNegatives", "ombRedisRuns", "ombRuns"),
)


def _source(name):
    path = REPO / name
    if not path.exists():                       # pragma: no cover - both ship in the repo
        pytest.skip("%s not present" % name)
    return re.sub(r"(?<!\\)%.*", "", path.read_text(encoding="utf-8"))


def _sentences(text):
    flat = re.sub(r"\s+", " ", text)
    return re.split(r"(?<=[.!?])\s+(?=[A-Z\\(])", flat)


@pytest.fixture(scope="module")
def macros():
    if not GENERATED.exists():                  # pragma: no cover - generated at build
        pytest.skip("docs/generated/paper_numbers.tex absent; run emit_paper_numbers.py")
    return dict(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}\{(.*)\}",
                           GENERATED.read_text(encoding="utf-8")))


class TestEveryPerCorpusNumeratorKeepsItsOwnDenominator:

    @pytest.mark.parametrize("numerator,own,whole", FAMILIES)
    def test_the_subset_count_is_never_quoted_against_the_total(self, numerator, own, whole):
        bad = []
        for name in DOCS:
            for sentence in _sentences(_source(name)):
                if ("\\" + numerator) not in sentence:
                    continue
                if ("\\" + whole) in sentence and ("\\" + own) not in sentence:
                    bad.append("%s: %r" % (name, sentence.strip()[:150]))
        assert not bad, (
            "\\%s counts one corpus and is quoted beside \\%s, which counts every corpus; "
            "use \\%s:\n  %s" % (numerator, whole, own, "\n  ".join(bad)))

    @pytest.mark.parametrize("numerator,own,whole", FAMILIES)
    def test_both_halves_of_every_family_are_emitted(self, macros, numerator, own, whole):
        for name in (numerator, own, whole):
            assert name in macros, (
                "\\%s is named in a denominator family but never emitted; the family is "
                "there so a sentence has the right one to reach for" % name)

    def test_the_denominators_add_up(self, macros):
        """If the subsets stop partitioning the whole, the rule is guarding nothing."""
        kafka, redis, total = (int(macros[k].replace("{,}", ""))
                               for k in ("ombKafkaRuns", "ombRedisRuns", "ombRuns"))
        assert kafka + redis == total, (
            "%d Kafka-driver runs + %d Redis-driver runs != %d in the ledger"
            % (kafka, redis, total))
        assert kafka and redis, "an empty corpus makes the split meaningless"

    def test_the_rule_can_fail(self):
        """The exact sentence that stood for several rounds."""
        broken = (r"Across all $\ombRuns$ runs the \kafka{}-driver corpus's "
                  r"$\ombKafkaDiscarded$ discarded samples contain not one negative.")
        fixed = (r"Across the \kafka{}-driver corpus's $\ombKafkaRuns$ runs its "
                 r"$\ombKafkaDiscarded$ discarded samples contain not one negative.")
        for text, should_flag in ((broken, True), (fixed, False)):
            hit = (r"\ombRuns" in text and r"\ombKafkaRuns" not in text
                   and r"\ombKafkaDiscarded" in text)
            assert hit is should_flag
