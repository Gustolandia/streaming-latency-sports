r"""Round 67. A histogram's mode count is the paper's own thesis pointed at the paper.

Figure 3 is titled *Traced run-queue stalls are trimodal* and Section~V-E counts three local
maxima on `bpftrace` log2 buckets. A mode count read off a histogram is a joint property of the
data and the bin edges --- and Section~VI's entire argument is that a millisecond quantum
decides what a benchmark prints while nobody discloses it. The bucket width came from the tool
exactly as the quantum did.

**The obvious answer was unavailable.** `runqlat.txt` is a 27-line summary; the per-event stall
durations were never retained, so rebinning raw data is impossible now and will stay
impossible. The referee proposed disclosure and the project's rule is that disclosure is the
last resort. So the check was rebuilt in the form the archived data supports: coarsening.
Merging adjacent log2 buckets gives log4 buckets, and the merge can be phased two ways. A mode
that survives both phasings is not sitting in one bucket by luck.

It survives. Three maxima at the tool's binning, three under both phasings of a doubled bin
width, and one or two under a quadrupled one --- so the structure is real down to a factor of
two in bin width and is resolution-limited beyond it. That is a stronger sentence than the
disclaimer, and it is computed rather than asserted.

The other three findings are small. Two of them were introduced by round 66's own revisions,
which is the recurring shape: a fix that is right in substance and clumsy in form.
"""
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
PAPER = REPO / "paper.tex"
SUPPLEMENT = REPO / "supplement.tex"
RECORD = REPO / "docs" / "results" / "external" / "stall_mode_robustness.json"

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests" / "unit"))

#: TC's own p95 sentence length, measured over five papers in docs/reference_tc: 37, 46, 46,
#: 50 and 52 words. Fifty sits at the upper end of what the journal prints and below the two
#: outliers, so it is a cap this manuscript can be held to rather than a number picked to
#: pass. The paper's own p95 is 39, better than any of the five.
MAX_SENTENCE_WORDS = 50


@pytest.fixture(scope="module")
def paper():
    return PAPER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supp():
    return SUPPLEMENT.read_text(encoding="utf-8")


class TestTheModeCountIsCheckedAgainstItsBinning:
    """R1. The claim survives, and the paper now says on what."""

    def test_the_committed_record_agrees_with_the_trace(self):
        import stall_mode_robustness as smr
        assert smr.main(["--check"]) == 0, \
            "docs/results/external/stall_mode_robustness.json disagrees with runqlat.txt"

    def test_the_modes_survive_a_doubled_bin_width_in_every_phase(self):
        r = json.loads(RECORD.read_text(encoding="utf-8"))
        two = [c for c in r["coarsenings"] if c["factor"] == 2]
        assert len(two) == 2, "a doubling has two phasings and both must be tested"
        assert all(c["agrees"] for c in two), (
            "the mode count changes when the bin width doubles, so `trimodal` is a property "
            "of bpftrace's bucket edges rather than of the stalls. The paper's claim has to "
            "change, not this test: %s" % two)
        assert r["base_modes"] == 3

    def test_the_resolution_limit_is_recorded_rather_than_hidden(self):
        r = json.loads(RECORD.read_text(encoding="utf-8"))
        assert r["survives_quadrupling"] is False, (
            "the structure now survives a quadrupled bin width, which is a stronger result "
            "than the manuscript claims; say so rather than leaving the weaker sentence.")

    def test_the_paper_states_which_inference_is_binning_free(self, paper):
        i = paper.index("stall_spectrum.pdf")
        section = paper[max(0, i - 4000):i + 4000]
        assert "monoton" in section, \
            "the power-law refutation rests on monotonicity, which no rebinning rescues"
        assert "\\stallCoarsenFactor" in section or "bin width" in section, (
            "Section V-E does not say that the mode count was checked against the binning. "
            "This paper argues that instruments impose structure that gets reported as a "
            "property of the system; Figure 3 reports local maxima of a bucketed histogram.")

    def test_the_paper_says_the_per_event_data_was_not_retained(self, paper, supp):
        both = paper + supp
        assert re.search(r"not retained|were not kept|only the .{0,24}histogram", both), (
            "neither document records that the per-event stall durations were not retained, "
            "so a reader cannot tell that rebinning is unavailable rather than unattempted.")

    def test_no_share_or_count_is_typed(self, paper):
        i = paper.index("stall_spectrum.pdf")
        caption = paper[i:paper.index("\\end{figure}", i)]
        for literal in ("20.0", "13.5", "10.5", "three local maxima"):
            assert literal not in caption, "%s is typed rather than emitted" % literal


class TestNoSentenceRunsPastWhatTheJournalPrints:
    """R2. Calibrated against five TC papers rather than chosen."""

    @staticmethod
    def _sentences():
        import test_sentence_length as T
        body = T.prose(PAPER, "\\section{Introduction}", "\\section*{Acknowledgment}")
        return [s for s in re.split(r"(?<=[.!?]) +", body) if len(s.split()) > 3]

    def test_the_longest_sentence_is_inside_the_journals_range(self):
        over = [(len(s.split()), " ".join(s.split())[:110]) for s in self._sentences()
                if len(s.split()) > MAX_SENTENCE_WORDS]
        assert not over, (
            "%d sentences run past %d words, the upper end of the p95 measured across five "
            "IEEE TC papers: %s" % (len(over), MAX_SENTENCE_WORDS,
                                    "; ".join("[%dw] %s" % o for o in over)))

    def test_the_distribution_still_beats_the_journal(self):
        lens = sorted(len(s.split()) for s in self._sentences())
        p95 = lens[int(0.95 * (len(lens) - 1))]
        assert statistics.median(lens) <= 22, "the median moved above the TC range"
        assert p95 <= 52, "the p95 moved past the worst of the five TC papers"

    def test_the_rule_can_fail(self):
        long_one = " ".join(["word"] * 57)
        assert len(long_one.split()) > MAX_SENTENCE_WORDS


class TestTheStallCaptionSaysEachThingOnce:
    r"""R3, pinned narrowly, because the general rule was built and then rejected.

    Round 66 put the three mode masses into Figure 3's caption, correctly, and wrote "of all
    wakeups" twice in sixty words. The obvious gate is *no caption repeats a three-word
    phrase*. It was built and measured against both documents, and it fires on Table~I:

        "Kafka on $8.67\%$ of its 367,894 events, Redis on $8.19\%$ of its 370,836"

    That repeat is deliberate parallelism and it is the clearest way to write the sentence.
    A rule that would push an author into degrading that caption to satisfy a counter is worse
    than no rule --- the same objection this project raised against a vocabulary gate in round
    59 and against a reachability rule that could not read ranges in round 66. **A gate that
    fires on good prose is a defect, not a standard.**

    So the general rule is not shipped and this pins the specific caption instead. It can only
    catch a recurrence of this defect, which is honest about what it is.
    """

    def test_the_caption_does_not_say_of_all_wakeups_twice(self, paper):
        i = paper.index("stall_spectrum.pdf")
        caption = " ".join(paper[i:paper.index("\\end{figure}", i)].split())
        assert caption.lower().count("of all wakeups") <= 1, (
            "Figure 3's caption says `of all wakeups` more than once in sixty words. The "
            "masses belong there; saying the denominator three times does not.")

    def test_the_body_still_states_the_denominator_once(self, paper):
        assert "of all wakeups" in paper, \
            "the share needs its denominator somewhere; the body carries it"

    def test_the_rejected_general_rule_would_have_fired_on_good_prose(self, paper):
        """Kept as evidence, so nobody rebuilds the rule without meeting the counter-example.

        The parallelism is `Kafka on X% of its N events, Redis on Y% of its M`, which a
        three-word repeated-phrase rule flags and which is the clearest way to write it.
        """
        caps = re.findall(r"\\caption(?:\[[^\]]*\])?\{(.{20,1600}?)\}\s*\n", paper, re.S)
        hits = 0
        for cap in caps:
            # Macros go first, exactly as the rejected rule did it: the repeat is `on ... of
            # its ... events, ... on ... of its`, and it is only visible once the emitted
            # numbers are removed.
            cap = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^{}]*\})?", " ", cap)
            words = re.sub(r"[^\w\s-]", " ", cap).lower().split()
            keys = [" ".join(words[k:k + 3]) for k in range(len(words) - 3)]
            hits += any(keys.count(k) > 1 for k in keys)
        assert hits, (
            "no caption repeats a three-word phrase any more, so the counter-example that "
            "justified not shipping the general rule is gone. Re-measure before relying on "
            "this reasoning again.")


class TestTheHdrHistogramFindingIsReadFromItsDocumentation:
    """R4(a). Verified; R4(b) was checked and is not cited, which is recorded in the source."""

    def test_the_supplement_records_what_the_documentation_omits(self, supp):
        assert "hdrhistogram_javadoc" in supp, \
            "the JavaDoc finding is cited nowhere in the supplement"
        i = supp.index("hdrhistogram_javadoc")
        window = supp[max(0, i - 1400):i + 600]
        assert "highestTrackableValue" in window, (
            "the passage does not say what the documentation does cover, which is the point: "
            "the exception is documented for the upper bound only.")

    def test_the_entry_is_in_the_bibliography(self):
        bib = (REPO / "manuscript_references.bib").read_text(encoding="utf-8")
        assert "hdrhistogram_javadoc" in bib
        assert "hdrhistogram.github.io" in bib

    def test_the_unverified_half_is_not_cited(self, supp):
        """Comments are stripped: the source records *why* it is not cited, deliberately.

        A note explaining a decision not to cite is the opposite of a citation, and a gate
        that could not tell them apart would delete the reasoning it exists to protect.
        """
        printed = re.sub(r"(?m)^%.*$", "", supp)
        for name in ("DataStax", "Cassandra driver"):
            assert name not in printed, (
                "%s is cited for a catch-and-warn disposition that was not read at source. "
                "Round 65's rule is that a citation is transcribed from the work itself; a "
                "search result is not that." % name)
