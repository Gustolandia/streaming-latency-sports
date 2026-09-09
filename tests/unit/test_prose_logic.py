"""Sentences that disagree with their neighbours, which no gate about values can see.

Round 58 found three of them in one round, all introduced by the restructure that moved
material between sections, and all invisible to every existing check because each sentence is
individually true and individually well-formed.

**A section that states its claim, then states it again.** The new Section VII opened on
"Neither failure is one project's oversight: ... five of the ten we read dispose of a sample
without counting it", and sixty words later its third paragraph said "Five of the ten dispose
of the sample without counting it, in three classes --- a pattern rather than one project's
oversight". Both halves of the opening, verbatim, in a section 315 words long. The opening had
been written *from* the paragraph it introduces.

**A connective whose antecedent moved.** "Nor is the admission condition confined to the tool
we measured" was the second of two paired "Nor is..." continuations. The first moved to
another section in the split, and the survivor was left negating a positive claim.

**A pointer that did not follow its definition.** Section V-E said "not the timestamp
resolution of Section VI" after the restructure moved that definition to Section II, sending a
reader forward for something they had already been given three sections earlier.

None of these is a wrong number. All three are a sentence that was right where it used to be.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
DOCS = ("paper.tex", "supplement.tex")

#: Words too common to make a shingle meaningful on their own.
_STOP = frozenset(("the", "a", "an", "of", "to", "in", "is", "it", "and", "that", "this",
                   "for", "on", "as", "at", "by", "with", "from", "not", "its", "than"))


def _plain(text):
    """LaTeX out, words in. Comments, tables, macros, math and markup all go.

    Tabular bodies go first and whole. A table is a grid of values, not prose, and its rows
    repeat each other's column separators by construction: left in, every table in the
    manuscript reports itself as a section repeating itself.
    """
    text = re.sub(r"(?m)(?<!\\)%.*$", " ", text)
    text = re.sub(r"\\begin\{tabular\}.*?\\end\{tabular\}", " . ", text, flags=re.S)
    text = re.sub(r"\\input\{[^}]*\}", " . ", text)
    text = re.sub(r"\\(begin|end)\{[^}]*\}", " . ", text)
    text = re.sub(r"\$[^$]*\$", " NUM ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(\{[^{}]*\})?", " ", text)
    return re.sub(r"[{}~^_\\]", " ", text)


def _sections(path):
    """(heading, body) for every \\section in one document.

    Biographies are cut first. They sit after the conclusion in the source, so they land in
    the last section's body, and two of the four authors are at the same institution: without
    this the rule reports "Trinity College Dublin, Ireland" as a section repeating itself.
    """
    raw = (REPO / path).read_text(encoding="utf-8")
    raw = re.sub(r"\\begin\{IEEEbiographynophoto\}.*?\\end\{IEEEbiographynophoto\}",
                 " ", raw, flags=re.S)
    parts = re.split(r"\\section\{([^}]*)\}", raw)
    out = []
    for i in range(1, len(parts), 2):
        out.append((parts[i], parts[i + 1]))
    return out


def _sentences(body):
    text = " ".join(_plain(body).split())
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) >= 6]


def _shingles(sentence, n=4):
    """Runs of `n` consecutive *content* words, articles and prepositions dropped.

    Over the raw words this misses the defect it was written for. Round 58's two sentences
    said "dispose of **a** sample without counting it" and "dispose of **the** sample without
    counting it" -- a near-repetition, not a verbatim one, and a shingle that keeps stopwords
    sees two different strings. Dropping them makes the rule about what a sentence says
    rather than how it is worded, which is the thing being checked.
    """
    words = [w.lower().strip(".,;:()[]\u2014-\u2019'\"") for w in sentence.split()]
    words = [w for w in words if w and w != "num" and w not in _STOP]
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


class TestNoSectionStatesItsClaimTwice:
    r"""Four consecutive content words, repeated inside one section of the article.

    **The article only, and the reason is not laziness.** The supplement is a postmortem whose
    form is restatement: it records what an earlier version said and then what replaced it,
    and several of those pairs are marked "in the round-2 restatement" in the text itself.
    Applying this rule there would flag the document doing its job. The article has no such
    licence -- it is twelve pages and every sentence in it displaced another.
    """

    @pytest.mark.parametrize("path", ("paper.tex",))
    def test_no_four_word_run_repeats_inside_one_section(self, path):
        offenders = []
        for heading, body in _sections(path):
            seen = {}
            for sentence in _sentences(body):
                for sh in _shingles(sentence):
                    if sh in seen and seen[sh] != sentence:
                        offenders.append("%s / %s: %r" % (path, heading[:34], sh))
                    seen.setdefault(sh, sentence)
        assert not offenders, ("a section says the same thing twice:\n  "
                               + "\n  ".join(sorted(set(offenders))[:6]))

    def test_the_check_would_have_caught_round_58(self):
        """The defect and its repair, as strings."""
        a = "Neither failure is one project's oversight: the tools are few and shared, and " \
            "five of the ten we read dispose of a sample without counting it."
        b = "Five of the ten dispose of the sample without counting it, in three classes " \
            "-- a pattern rather than one project's oversight, and one of them is Pulsar."
        assert _shingles(a) & _shingles(b), "the shingle width no longer sees the repetition"
        c = "The admission condition is not confined to the tool we measured: 40 of the 40 " \
            "public forks we could read carry the expression unchanged."
        assert not (_shingles(c) & _shingles(b)), "the repair should not trip the rule"


class TestAConnectiveHasSomethingToConnectTo:
    r""""Nor" needs a negative before it, and "either" needs a pair.

    Round 58: a split left "Nor is the admission condition confined to the tool we measured"
    opening a section, immediately after a positive claim. It had been the second of two
    paired continuations and the first had moved. The sentence is well formed and false to
    its position, which is the only kind of error this file is about.
    """

    NEGATIVE = re.compile(r"\b(not|no|never|neither|nor|none|nothing|cannot|"
                          r"n't|without|fails?|failed)\b", re.I)

    @pytest.mark.parametrize("path", DOCS)
    def test_every_nor_follows_a_negative(self, path):
        offenders = []
        for heading, body in _sections(path):
            sentences = _sentences(body)
            for i, sentence in enumerate(sentences):
                if not re.match(r"^Nor\b", sentence):
                    continue
                if i == 0 or not self.NEGATIVE.search(sentences[i - 1]):
                    offenders.append("%s / %s: %r" % (path, heading[:34], sentence[:70]))
        assert not offenders, ("a \"Nor\" has nothing to negate:\n  " + "\n  ".join(offenders))

    def test_the_check_separates_the_two_cases(self):
        assert self.NEGATIVE.search("Neither failure is one project's oversight.")
        assert not self.NEGATIVE.search("The tools are few and shared, and five of ten do it.")


class TestAnEquationIsNotCitedBeforeItAppears:
    r"""Within one subsection, a reference to an equation may not precede the equation.

    Section VI-B read "the correlation it does have ... carries the sign Equation 4 predicts"
    four lines above Equation 4's display. Across sections a forward pointer is ordinary; in
    the same subsection it asks the reader to accept a justification they have not been given
    yet, which is rule B7 of the writing standards in miniature.
    """

    @pytest.mark.parametrize("path", DOCS)
    def test_no_reference_precedes_its_own_display_in_one_subsection(self, path):
        raw = (REPO / path).read_text(encoding="utf-8")
        offenders = []
        chunks = re.split(r"\\(?:sub)?section\{[^}]*\}", raw)
        for chunk in chunks:
            for m in re.finditer(r"\\(?:eq)?ref\{(eq:[^}]+)\}", chunk):
                label = "\\label{%s}" % m.group(1)
                at = chunk.find(label)
                if at > m.start():
                    offenders.append("%s: %s cited at %d, displayed at %d"
                                     % (path, m.group(1), m.start(), at))
        assert not offenders, ("an equation is cited above its own display:\n  "
                               + "\n  ".join(offenders))
