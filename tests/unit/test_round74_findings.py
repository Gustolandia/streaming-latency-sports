r"""Round 74's referee items, pinned so a later pass cannot quietly undo them.

Two required items, both about a representation nothing was checking.

R1. Round 73 closed the gap where a numeral touching a control word escaped the typed-numeral
inventory. This manuscript also spells small numbers as words -- deliberately, since eleven
`...Word` macros exist so a count can open a sentence -- and the inventory read digits.
Section VI-A typed *four* where `ombEscapeCellsWord` emits it and the supplement uses it;
Section VII typed *three* six lines below the same paragraph's `harnessDisposalClassesWord`.
The second was found by the new gate rather than by the referee.

R2. `test_prose_pointers.py` has verified every pointer to a supplement *section* since round
45. The documents also name twenty-two *file paths* and nothing looked at one of them. Two led
nowhere: the sweep ledger, absent by design and now disclosed as such, and
`docs/results/external/dist_diag/`, which S24.1 said held the distributed-mode diagnostics.
There is no such directory and the signatures it promised are in no file in the artefact -- a
`git grep` for `CompletionException` finds one hit, the sentence claiming they are archived.
The repair names the files that do exist and states the absence as the limitation it is.

And one correction to the referee. Its W1 offered a vendor benchmarking-methodology guide as a
new find; S33.4 had been discussing it, with a sharper reading, for rounds. What was missing
was its row in the ledger, which is the inverse defect and the easier one to miss.
"""
from pathlib import Path
import csv
import re
import sys

import pytest

REPO = Path(__file__).parent.parent.parent
RE_BS = chr(92) + chr(92)
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "supplement.tex").read_text(encoding="utf-8")


def _rendered(name):
    pdf = REPO / ("%s.pdf" % name)
    if not pdf.is_file():
        pytest.skip("%s not built" % pdf.name)
    import pypdf
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages)


class TestR1SpelledQuantitiesUseTheirMacro:

    def test_the_escaping_cells_come_from_the_ledger(self, paper, supplement):
        """The instance the referee found: emitted in one document, typed in the other."""
        i = paper.index("The only cells that escape")
        passage = " ".join(paper[i:i + 200].split())
        assert chr(92) + "ombEscapeCellsWord" in passage
        assert "escape are the four" not in passage
        assert chr(92) + "ombEscapeCellsWord" in supplement, (
            "the supplement used it first; both documents now agree")

    def test_the_disposal_classes_come_from_the_ledger(self, paper):
        """The instance the gate found, six lines below a use of the same macro."""
        i = paper.index("Substitution is the worst")
        passage = " ".join(paper[i:i + 200].split())
        assert chr(92) + "harnessDisposalClassesWord" in passage
        assert "worst of the three" not in passage

    def test_both_macros_still_say_what_the_sentences_need(self):
        import emit_paper_numbers as epn
        m = dict(epn.omb_macros()) if hasattr(epn, "omb_macros") else {}
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
        vals = dict(re.findall(RE_BS + r"newcommand\{" + RE_BS + r"(\w+)\}\{([^}]*)\}", gen))
        assert vals["ombEscapeCellsWord"] == "four"
        assert vals["harnessDisposalClassesWord"] == "three"
        assert m is not None

    def test_the_gloss_is_visibly_a_gloss(self, paper):
        """W2. `ombRetentionMinExact` is emitted; the four-in-ninety-thousand reading of it is
        an approximation and now says so, so it cannot be mistaken for a second measurement."""
        i = paper.index(chr(92) + "ombRetentionMinExact")
        passage = " ".join(paper[i:i + 160].split())
        assert "about four samples in ninety" in passage
        assert "four samples kept of ninety thousand" not in paper

    def test_the_word_gate_exists_and_enumerates_its_residue(self):
        sys.path.insert(0, str(REPO / "tests" / "unit"))
        import test_round72_findings as t72
        cls = t72.TestEveryWordSpelledQuantityIsADecisionToo
        assert "seven" in cls.ALLOWED_WORDS, (
            "the withdrawn E1 corpus's median: typed on purpose, and the referee said so")
        for word, reason in cls.ALLOWED_WORDS.items():
            assert len(reason.split()) >= 8, "%s has no real reason recorded" % word

    def test_paxson_is_not_yet_thirty_years_ago(self, paper):
        """W3. 2026 - 1998 = 28. The approximation is flagged as one."""
        assert "for nearly thirty years" in paper
        assert "have for thirty years" not in paper


class TestR2EveryPathNamedInProseResolves:

    def test_the_gate_reads_file_pointers_and_not_only_sections(self):
        src = (REPO / "tests" / "unit" / "test_prose_pointers.py").read_text(encoding="utf-8")
        assert "class TestEveryFilePointerHasAFile" in src
        assert "REPO_PREFIXES" in src and "ABSENT_BY_DESIGN" in src

    def test_no_document_names_the_directory_that_was_never_there(self, supplement):
        assert "dist_diag" not in supplement
        issue = (REPO / "docs" / "omb_distributed_issue.md").read_text(encoding="utf-8")
        assert "dist_diag" not in issue, (
            "the draft upstream report sent the benchmark's own maintainers to the same "
            "missing directory")

    def test_the_distributed_record_names_what_the_artefact_holds(self, supplement):
        i = supplement.index("S24.1. OpenMessaging distributed mode")
        section = " ".join(supplement[i:i + 1400].split())
        for path in ("omb\\_distributed\\_result.csv", "dist\\_load0/", "dist\\_load50/",
                     "omb\\_worker\\_client.log", "omb\\_worker\\_driver.log"):
            assert path in section, path
        for p in ("docs/results/external/omb_distributed_result.csv",
                  "docs/results/external/dist_load0",
                  "docs/results/external/dist_load50",
                  "external/omb/omb_worker_client.log",
                  "external/omb/omb_worker_driver.log"):
            assert (REPO / p).exists(), p

    def test_the_absence_is_stated_rather_than_papered_over(self, supplement):
        """The signatures are in no file. Saying so is the repair; a directory created to
        satisfy the sentence would have been worse than the broken pointer."""
        i = supplement.index("S24.1. OpenMessaging distributed mode")
        section = " ".join(supplement[i:i + 1400].split())
        assert "not retained" in section
        assert "limitation" in section

    def test_the_signature_really_is_only_in_the_prose(self):
        """If it is ever archived, this fails and the sentence above must be relaxed.

        Scoped to the directories that carry evidence rather than to the whole checkout: the
        result trees hold hundreds of thousands of rows and reading all of them to prove a
        negative is a minute per test run for a fact that cannot hide in a `span_recount` row.
        """
        roots = [REPO / "external", REPO / "cloud",
                 REPO / "docs" / "results" / "external", REPO / "docs"]
        hits = []
        for root in roots:
            if not root.is_dir():
                continue
            for p in root.rglob("*"):
                if not p.is_file() or p.suffix not in (".log", ".txt", ".json", ".md"):
                    continue
                # The two documents that *discuss* the absence quote the signature; they are
                # the record of what is missing, not the missing record.
                if p.name in ("infrastructure.md", "omb_distributed_issue.md"):
                    continue
                if "CompletionException" in p.read_text(encoding="utf-8", errors="ignore"):
                    hits.append(str(p.relative_to(REPO)))
        assert not hits, "the class-2 signature is archived after all: %s" % sorted(set(hits))

    def test_the_sweep_ledgers_absence_is_disclosed_where_it_is_named(self, supplement):
        i = supplement.index("novelty\\_sweep.csv")
        passage = " ".join(supplement[max(0, i - 300):i + 420].split())
        assert "absent from the artifact until one succeeds" in passage
        assert "declined twice" in passage, (
            "the reason is the interesting part: it refused rather than wrote a partial sweep")


class TestTheRefereesOwnItemWasAlreadyDone:
    """W1, corrected. The prose had the exhibit; the ledger did not have the row."""

    def test_the_methodology_guide_was_already_read(self, supplement):
        assert supplement.count("automq2026methodology") == 1, (
            "one citation, in the passage that was there before round 74 looked")
        i = supplement.index("automq2026methodology")
        passage = " ".join(supplement[max(0, i - 700):i + 400].split())
        assert "fairness guide" in passage or "fair" in passage
        assert "outlier handling" in passage, (
            "the supplement's reading is sharper than the referee's: it names the "
            "unfalsifiable gesture rather than only the omission")

    def test_the_ledger_now_carries_what_the_prose_asserts(self):
        rows = list(csv.DictReader(
            (REPO / "docs" / "results" / "external" / "literature_regime.csv")
            .open(encoding="utf-8")))
        row = [r for r in rows if r["citation_key"] == "automq2026methodology"]
        assert len(row) == 1 and row[0]["kind"] == "methodology"

    def test_the_denominator_the_main_text_quotes_did_not_move(self):
        import emit_paper_numbers as epn
        m = dict(epn.literature_macros()) if hasattr(epn, "literature_macros") else {}
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
        vals = dict(re.findall(RE_BS + r"newcommand\{" + RE_BS + r"(\w+)\}\{([^}]*)\}", gen))
        assert vals["litComparisonsWord"] == "four"
        assert vals["litInsideRegimeWord"] == "three"
        assert m is not None

    def test_no_row_is_double_counted(self):
        rows = list(csv.DictReader(
            (REPO / "docs" / "results" / "external" / "literature_regime.csv")
            .open(encoding="utf-8")))
        keys = [r["citation_key"] for r in rows]
        assert len(keys) == len(set(keys)), keys


class TestTheRenderedPageCarriesIt:

    def test_the_escaping_cells_and_the_classes_print(self):
        flat = "".join(_rendered("paper").split())
        assert "escapearethefourwhosepayload" in flat
        assert "worstofthethreeclasses" in flat

    def test_the_gloss_prints_as_an_approximation(self):
        flat = " ".join(_rendered("paper").split())
        assert "about four samples in ninety thousand" in flat
