r"""Sentence length in the main text, against the venue it is being submitted to.

N. Herbst read the shipped build and reported that average sentence length and complexity
ran "a bit higher" than he would have set them, and asked for the claim to be measured
rather than judged by ear. Round 43 measured it. From the LaTeX source, markup stripped,
Introduction to Acknowledgment: **mean 30.0 words, median 28, and 24% of sentences over
forty words**. The same extraction applied to five IEEE Transactions on Computers papers
held in `docs/reference_tc/` gives means of 23.4 to 27.8 and medians of 19 to 22.

The mean is 9% above the highest of the five. The median is 27% above it, and the median is
the number that matters: it says the whole distribution is shifted rather than that a
handful of long sentences are dragging an average. So the gate is on the median, set at the
top of the observed venue range, and a second, looser one caps the share of very long
sentences -- a paper can hold a good median while still stopping the reader dead twice a
page.

Deliberately not a style test. It cannot tell a long sentence that earns its length from one
that does not, and there is no attempt here to push the prose towards short declaratives:
the Feynman rule asks every section to open on a plain claim, not for every sentence to be
plain. What it can do is notice the distribution drifting back, which is what happened
between the round-40 build and this one without anyone seeing it.
"""
import re
import statistics
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent

#: The top of the range measured across five TC papers, so the paper sits inside the venue
#: rather than at some absolute ideal. Raising this number is allowed; doing it silently is
#: what the gate exists to prevent.
MEDIAN_CAP = 22
#: A quarter of the main text ran over forty words when this was written. A fifth is the
#: room left for sentences that genuinely need the length.
LONG_SHARE_CAP = 0.20
LONG_WORDS = 40


def prose(path, start, stop):
    """The document's running prose, with markup, floats and displayed maths removed.

    Floats go because a caption is a different register and is checked by its own rule;
    displayed equations go because a sentence whose grammatical completion is an equation is
    a real construction and counting the equation's tokens would punish it twice.
    """
    text = path.read_text(encoding="utf-8")
    i, j = text.find(start), text.find(stop)
    if i < 0 or j < 0:
        raise AssertionError("could not delimit the body of %s" % path.name)
    body = text[i:j]
    body = re.sub(r"(?m)^%.*$", "", body)
    # A removed float leaves nothing behind; a removed *display* leaves a full stop. The
    # first version of this deleted both alike and so glued "The replicate spread follows:"
    # to the sentence after the equation, reporting a 47-word sentence where the source has
    # a four-word lead-in and a display. A measurement that punishes ordinary mathematical
    # writing would have had us rewriting good prose to satisfy it.
    body = re.sub(r"\\begin\{(figure|table)\*?\}.*?\\end\{\1\*?\}", " ", body, flags=re.S)
    body = re.sub(r"\\begin\{equation\*?\}.*?\\end\{equation\*?\}", " . ", body, flags=re.S)
    body = re.sub(r"\\(label|ref|cite|eqref)\{[^}]*\}", " ", body)
    body = re.sub(r"\\[a-zA-Z]+\*?", " ", body)
    body = re.sub(r"[{}$~\\]", " ", body)
    return re.sub(r"\s+", " ", body)


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text)
            if len(s.split()) >= 5]


@pytest.fixture(scope="module")
def lengths():
    body = prose(REPO / "paper.tex", "\\section{Introduction}", "\\section*{Acknowledgment}")
    out = [len(s.split()) for s in sentences(body)]
    assert len(out) > 150, "the body did not parse into sentences; the extractor is wrong"
    return out


def test_the_median_sentence_sits_inside_the_venue_range(lengths):
    median = statistics.median(lengths)
    assert median <= MEDIAN_CAP, (
        "median sentence is %.1f words; five TC papers measured the same way run 19-22, "
        "and a reader meets the median far more often than the mean" % median)


def test_very_long_sentences_stay_a_minority(lengths):
    share = sum(1 for n in lengths if n > LONG_WORDS) / len(lengths)
    assert share <= LONG_SHARE_CAP, (
        "%.0f%% of sentences run over %d words" % (100 * share, LONG_WORDS))


def test_no_sentence_runs_past_the_point_of_recovery(lengths):
    """One sentence in the round-42 build ran to 89 words, wrapped a forty-word aside in
    em-dashes, and had a displayed equation for its main clause. A reader cannot hold that."""
    assert max(lengths) <= 60, "longest sentence is %d words" % max(lengths)
