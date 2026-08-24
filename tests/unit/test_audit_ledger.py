"""Tests for scripts/audit_ledger.py - target >=95% branch coverage.

This module exists because of round 16, though not for the reason the report gave. The
reviewer reported that the audit headline -- 1,321 of 2,266 runs -- did not reproduce from the
committed artifacts. It does, from
`docs/results/integrity_windows/clock_integrity_by_condition.csv` and
`docs/results/integrity_by_condition.csv`, and `TestAudit` had been asserting exactly that.
What the reviewer checked was `reproducibility/runs_index*.csv`, the campaign inventory, which
carries a transport-only verdict over every run that ever executed and answers a different
question.

The real defect was that the numbers were *typed* into both documents. Every other headline is
a macro recomputed at build time; this one required a reader to know which of several CSVs was
the right one, which is how a careful reviewer came to the wrong conclusion. So these tests
pin the derivation: the counts come from the audit's own files, the rate is over the runs the
audit covers, and a condition survives only if all of its runs do.
"""
import csv
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import audit_ledger as al  # noqa: E402

FIELDS = ["condition", "n_runs", "n_trustworthy", "worst_transport_ms",
          "median_neg_fraction", "usable"]


def _conditions(tmp_path, name, rows):
    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            full = {k: "" for k in FIELDS}
            full.update(r)
            w.writerow(full)
    return str(path)


def _row(name, n_runs, n_trustworthy, usable):
    return {"condition": name, "n_runs": n_runs, "n_trustworthy": n_trustworthy,
            "usable": str(usable)}


class TestCorpusCounts:

    def test_rejected_is_runs_minus_those_kept(self):
        rows = [_row("a", 10, 4, False), _row("b", 5, 5, True)]
        c = al.corpus_counts(rows)
        assert c["runs"] == 15
        assert c["rejected"] == 6
        assert c["pct"] == pytest.approx(40.0)

    def test_conditions_are_counted_and_the_usable_ones_named(self):
        rows = [_row("a", 10, 4, False), _row("b", 5, 5, True), _row("c", 2, 2, True)]
        c = al.corpus_counts(rows)
        assert c["conditions"] == 3
        assert c["usable_conditions"] == 2

    def test_a_condition_with_one_bad_run_is_not_usable(self):
        """The manuscript's rule, already decided in the column; this pins that reading."""
        rows = [_row("a", 10, 9, False)]
        c = al.corpus_counts(rows)
        assert c["usable_conditions"] == 0 and c["rejected"] == 1

    def test_an_empty_corpus_does_not_divide_by_zero(self):
        c = al.corpus_counts([])
        assert c == {"runs": 0, "rejected": 0, "conditions": 0,
                     "usable_conditions": 0, "pct": 0.0}

    def test_a_corpus_of_zero_run_conditions_reports_zero(self):
        c = al.corpus_counts([_row("a", 0, 0, False)])
        assert c["runs"] == 0 and c["pct"] == 0.0


class TestReadConditions:

    def test_a_missing_file_reads_as_empty(self, tmp_path):
        assert al.read_conditions(str(tmp_path / "absent.csv")) == []

    def test_a_byte_order_mark_does_not_corrupt_the_first_column(self, tmp_path):
        p = tmp_path / "bom.csv"
        p.write_bytes(b"\xef\xbb\xbfcondition,n_runs,n_trustworthy,usable\nc,4,1,False\n")
        rows = al.read_conditions(str(p))
        assert rows and rows[0]["condition"] == "c"

    def test_a_relative_path_resolves_against_the_repository(self):
        rows = al.read_conditions(al.CORPORA[0][1])
        assert rows, "the workstation audit file should be readable by its relative path"


class TestAudit:

    def test_the_total_sums_the_corpora(self, tmp_path):
        a = _conditions(tmp_path, "a.csv", [_row("x", 10, 2, False)])
        b = _conditions(tmp_path, "b.csv", [_row("y", 10, 8, False), _row("z", 5, 5, True)])
        out = al.audit((("A", a), ("B", b)))
        assert out["A"]["rejected"] == 8 and out["B"]["rejected"] == 2
        assert out["total"]["runs"] == 25
        assert out["total"]["rejected"] == 10
        assert out["total"]["conditions"] == 3
        assert out["total"]["usable_conditions"] == 1
        assert out["total"]["pct"] == pytest.approx(40.0)

    def test_a_total_over_no_runs_is_zero(self, tmp_path):
        a = _conditions(tmp_path, "a.csv", [])
        assert al.audit((("A", a),))["total"]["pct"] == 0.0

    def test_summary_is_the_audit(self):
        assert al.summary()["total"] == al.audit()["total"]


class TestAgainstTheCommittedRecord:
    """The values the manuscript prints, from the files that ship with it."""

    def test_the_workstation_corpus(self):
        c = al.audit()["workstation"]
        assert (c["runs"], c["rejected"], c["conditions"], c["usable_conditions"]) == \
            (1382, 862, 76, 8)

    def test_the_cloud_corpus(self):
        c = al.audit()["cloud"]
        assert (c["runs"], c["rejected"], c["conditions"], c["usable_conditions"]) == \
            (884, 459, 40, 13)

    def test_the_total_is_the_paper_headline(self):
        c = al.audit()["total"]
        assert (c["runs"], c["rejected"]) == (2266, 1321)
        assert round(c["pct"], 1) == 58.3

    def test_the_audit_corpus_is_not_the_span_recount_corpus(self):
        """Two populations, four paragraphs apart, that a reviewer read as a contradiction.

        The audit covers runs behind a reported result; the recount covers every cloud run
        that produced matched events. The main text now says so; this keeps them distinct so
        nobody 'reconciles' them by making one equal the other.
        """
        import recount_spans
        span = ROOT / "docs" / "results" / "span_recount.csv"
        if not span.exists():
            pytest.skip("span recount not present")
        recounted = recount_spans.totals(recount_spans.read_csv(str(span)))["runs"]
        assert recounted > al.audit()["cloud"]["runs"]
