r"""The artifact statement may not claim an availability the records do not have.

On 2026-09-11 all twelve Zenodo records were restricted --- files no longer downloadable,
pending submission --- while the manuscript went on saying that every number is recomputed
from the committed data by the archived code, printed beside two DOIs a reader cannot open.
Both halves were true separately. Together they mislead, because the claim is about what the
archive contains and the reader's next act is to try to fetch it.

The **version** in that sentence has been emitted since round 43, after a typed version went
stale the moment the next deposit landed. Access is the same kind of fact and had the same
defect waiting for it: nothing tied the sentence to the record's real state, so restricting
the records could not make the paper wrong in any way a build could see.

It now reads `access_right` from the deposit metadata --- Zenodo's own field, so there is one
place it is written --- and both records are checked against each other the way the version
already was. When the files are opened at acceptance, the sentence changes by itself.
"""
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import emit_paper_numbers as epn  # noqa: E402

#: Zenodo's vocabulary, and the phrase each one prints as.
PHRASES = {
    "open": "openly downloadable",
    "restricted": "restricted pending publication",
    "embargoed": "under embargo",
    "closed": "closed",
}


def _deposit(name):
    return json.loads((REPO / name).read_text(encoding="utf-8"))


class TestTheDepositRecordsDeclareTheirAccess:
    @pytest.mark.parametrize("name", [".zenodo.json", ".zenodo-data.json"])
    def test_access_right_is_present_and_valid(self, name):
        access = _deposit(name).get("access_right")
        assert access, "%s does not declare access_right" % name
        assert access in PHRASES, \
            "%s declares access_right=%r, which is not a Zenodo value" % (name, access)

    def test_the_two_records_agree(self):
        code, data = _deposit(".zenodo.json"), _deposit(".zenodo-data.json")
        assert code["access_right"] == data["access_right"], (
            "the code and data records declare different access. They are published as a "
            "pair and a reader who follows one to the other must not find one open and one "
            "shut.")


class TestTheManuscriptReadsItRatherThanAssertingIt:
    @pytest.fixture(scope="class")
    def paper(self):
        return (REPO / "paper.tex").read_text(encoding="utf-8")

    def test_the_artifact_line_states_the_access(self, paper):
        start = paper.index("resolve to the current version")
        para = paper[start:start + 320]
        assert "\\artifactAccessPhrase" in para, (
            "the artifact statement does not say whether the files can be fetched. It sits "
            "beside a claim that every number is recomputed from the archived code, which a "
            "reader will try to check.")

    def test_the_access_is_not_typed(self, paper):
        start = paper.index("resolve to the current version")
        para = paper[start:start + 320]
        for phrase in PHRASES.values():
            assert phrase not in para, (
                "%r is typed into the artifact line; it must come from the deposit "
                "metadata, or restricting the records will not make the paper wrong."
                % phrase)

    def test_the_built_pdf_carries_the_declared_state(self):
        """Read the artefact, not the source --- the lesson rounds 48 to 52 kept teaching."""
        pytest.importorskip("pypdf")
        from pypdf import PdfReader
        pdf = REPO / "paper.pdf"
        if not pdf.exists():                             # pragma: no cover - unbuilt tree
            pytest.skip("paper.pdf is not built")
        text = " ".join(" ".join(p.extract_text() for p in PdfReader(str(pdf)).pages).split())
        want = PHRASES[_deposit(".zenodo.json")["access_right"]]
        assert want in text, (
            "the built PDF does not say the files are %r. The macro is emitted; either the "
            "paper was not rebuilt after the deposit metadata changed, or the sentence "
            "dropped it." % want)


class TestTheEmitter:
    def test_it_emits_the_phrase_the_paper_reads(self, tmp_path):
        """The phrase only.

        A bare `artifactAccess` macro was emitted alongside it for one build and nothing
        quoted it, because the sentence wants the phrase. `test_rendered_prose` caught it as
        an unread macro, which is the right answer: a number or a word nobody quotes is one
        nobody checked.
        """
        code = tmp_path / "code.json"
        data = tmp_path / "data.json"
        for p in (code, data):
            p.write_text(json.dumps({"version": "1.2.3", "access_right": "open"}),
                         encoding="utf-8")
        out = dict(epn.artifact_macros(str(code), str(data)))
        assert out == {"artifactVersion": "1.2.3",
                       "artifactAccessPhrase": "openly downloadable"}

    def test_a_missing_sibling_file_falls_back_rather_than_crashing(self, tmp_path):
        """The branch that was nearly bought with a pragma instead of earned.

        The sibling record is read to check the two agree. If it is absent the build must
        still produce the paper from what it has, rather than failing on a cross-check it
        cannot perform.
        """
        code = tmp_path / "code.json"
        code.write_text(json.dumps({"version": "2.0.0", "access_right": "restricted"}),
                        encoding="utf-8")
        out = dict(epn.artifact_macros(str(code), str(tmp_path / "absent.json")))
        assert out["artifactAccessPhrase"] == "restricted pending publication"

    def test_a_disagreement_between_the_records_is_refused(self, tmp_path):
        code = tmp_path / "code.json"
        data = tmp_path / "data.json"
        code.write_text(json.dumps({"version": "1.0.0", "access_right": "open"}),
                        encoding="utf-8")
        data.write_text(json.dumps({"version": "1.0.0", "access_right": "restricted"}),
                        encoding="utf-8")
        with pytest.raises(ValueError, match="disagree on access"):
            epn.artifact_macros(str(code), str(data))

    def test_metadata_without_access_still_emits_the_version(self, tmp_path):
        """The field is new; a deposit file that predates it must not break the build."""
        code = tmp_path / "code.json"
        data = tmp_path / "data.json"
        for p in (code, data):
            p.write_text(json.dumps({"version": "0.9.0"}), encoding="utf-8")
        out = dict(epn.artifact_macros(str(code), str(data)))
        assert out == {"artifactVersion": "0.9.0"}

    def test_an_unknown_value_prints_itself(self, tmp_path):
        """Better a strange word in the paper than a confident wrong one."""
        code = tmp_path / "code.json"
        data = tmp_path / "data.json"
        for p in (code, data):
            p.write_text(json.dumps({"version": "1.0.0", "access_right": "mystery"}),
                         encoding="utf-8")
        out = dict(epn.artifact_macros(str(code), str(data)))
        assert out["artifactAccessPhrase"] == "mystery"


class TestTheRuleCanFail:
    def test_the_sentence_as_it_stood_would_be_rejected(self):
        stale = ("both resolve to the current version, v3.0.0. Every number here is "
                 "recomputed from the committed data by the archived code at build time.")
        assert "\\artifactAccessPhrase" not in stale
        assert not re.search(r"restricted|openly downloadable", stale)
