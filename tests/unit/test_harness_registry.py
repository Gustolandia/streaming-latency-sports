"""Tests for scripts/harness_registry.py - target >=95% branch coverage.

The registry's whole value is that its labels are derived rather than asserted, so the tests
here are of two kinds. The first kind pins the derivation machinery against synthetic rows whose
properties are known by construction. The second kind is a guard: it re-derives the class of
every committed evidence line and fails if a real harness stops classifying the way the paper
says it does. That second kind is what stops a later loosening of a regex from quietly changing
a sentence in Section II.
"""
import csv
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parent.parent.parent
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from harness_registry import (  # noqa: E402
    FIELDS,
    REGISTRY,
    by_harness,
    classified,
    load,
    main,
    paths,
    summary,
    within_harness_contrast,
)


def write_registry(tmp_path, rows):
    p = tmp_path / "registry.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(FIELDS))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return p


def row(harness="H", vendor="V", language="L", evidence="int x = 1;", **kw):
    base = {"harness": harness, "vendor": vendor, "language": language,
            "path": "end-to-end", "clock": "millisecond",
            "file": "a.c", "symbol": "f", "evidence": evidence,
            "source_url": "https://example.invalid", "retrieved": "2026-08-20", "note": ""}
    base.update(kw)
    return base


# --- the derivation ----------------------------------------------------------------------

def test_classified_derives_filter_from_evidence():
    rows = [row(evidence="if (endToEndLatencyMicros > 0) {")]
    got = classified(rows)
    assert got[0]["kinds"] == ["positive_only_filter"]
    assert got[0]["is_counter"] is False


def test_classified_derives_suppression_from_a_ternary_substitution():
    rows = [row(evidence="return (from < to) ? (to - from) : 1;")]
    assert classified(rows)[0]["kinds"] == ["silent_suppression"]


def test_classified_returns_empty_for_a_line_with_no_defect():
    """The counterexample row must come back clean, not be forced into a class."""
    rows = [row(evidence='name = "scheduler_discarded_samples",')]
    got = classified(rows)
    assert got[0]["kinds"] == []
    assert got[0]["is_counter"] is True


def test_a_line_can_belong_to_more_than_one_class():
    rows = [row(evidence="if (latency > 0) { d = now - publishTimestamp; }")]
    assert set(classified(rows)[0]["kinds"]) == {"cross_process_latency", "positive_only_filter"}


def test_classified_does_not_mutate_the_input_rows():
    rows = [row()]
    classified(rows)
    assert "kinds" not in rows[0]


# --- the fold ----------------------------------------------------------------------------

def test_by_harness_unions_classes_across_lines():
    rows = [row(harness="X", evidence="long d = now - publishTimestamp;"),
            row(harness="X", evidence="if (latencyUs > 0) {")]
    fold = by_harness(rows)
    assert fold["X"]["lines"] == 2
    assert fold["X"]["kinds"] == {"cross_process_latency", "positive_only_filter"}


def test_by_harness_counter_on_any_line_marks_the_harness():
    rows = [row(harness="X", evidence="if (latencyUs > 0) {"),
            row(harness="X", evidence="negativeLatencyCounter.inc();")]
    assert by_harness(rows)["X"]["counts_discards"] is True


# --- the summary -------------------------------------------------------------------------

def test_a_harness_that_filters_but_counts_is_not_silent():
    """The precedence bug this guards against made `|` and `-` associate the wrong way."""
    rows = [row(harness="Counted", evidence="if (latencyUs > 0) {"),
            row(harness="Counted", evidence="discardedCount++;"),
            row(harness="Silent", evidence="if (latencyUs > 0) {")]
    s = summary(rows)
    assert s["silent"] == ["Silent"]
    assert s["n_silent"] == 1
    assert s["counts_discards"] == ["Counted"]


def test_a_harness_that_suppresses_but_counts_is_not_silent():
    rows = [row(harness="S", evidence="return (from < to) ? (to - from) : 1;"),
            row(harness="S", evidence="invalid_samples++;")]
    assert summary(rows)["silent"] == []


def test_summary_counts_distinct_vendors_and_languages():
    rows = [row(harness="A", vendor="V1", language="C"),
            row(harness="B", vendor="V1", language="Rust"),
            row(harness="C", vendor="V2", language="C")]
    s = summary(rows)
    assert (s["harnesses"], s["vendors"], s["languages"]) == (3, 2, 2)
    assert s["evidence_lines"] == 3


def test_summary_reads_the_committed_registry_when_given_nothing():
    s = summary()
    assert s["harnesses"] >= 5


# --- loading -----------------------------------------------------------------------------

def test_load_rejects_a_registry_missing_a_column(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("harness,evidence\nX,y\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing column"):
        load(p)


def test_load_tolerates_an_empty_registry(tmp_path):
    p = write_registry(tmp_path, [])
    assert load(p) == []


# --- CLI ---------------------------------------------------------------------------------

def test_main_text_output(tmp_path, capsys):
    p = write_registry(tmp_path, [row(harness="X", evidence="if (latencyUs > 0) {")])
    assert main(["--registry", str(p)]) == 0
    out = capsys.readouterr().out
    assert "1 harnesses" in out and "positive_only_filter" in out and "no counter" in out


def test_main_reports_a_clean_harness_as_having_no_defect_class(tmp_path, capsys):
    p = write_registry(tmp_path, [row(harness="Good", evidence="discarded_samples++;")])
    assert main(["--registry", str(p)]) == 0
    out = capsys.readouterr().out
    assert "no defect class" in out and "counts discards" in out


def test_main_json_output(tmp_path, capsys):
    p = write_registry(tmp_path, [row(harness="X", evidence="if (latencyUs > 0) {")])
    assert main(["--registry", str(p), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["n_silent"] == 1


# --- the guard on the committed evidence -------------------------------------------------

EXPECTED = {
    "OpenMessaging Benchmark": ({"cross_process_latency", "positive_only_filter"}, False),
    # Round 6: the guard is on the counter, so the filter label is withdrawn -- the tool
    # computes the cross-process span and keeps every sample of it.
    "emqtt-bench":             ({"cross_process_latency"}, False),
    "Apache Pulsar perf":      ({"cross_process_latency", "positive_only_filter"}, False),
    "fio":                     ({"silent_suppression"}, False),
    "blktrace btt":            ({"silent_suppression"}, False),
    "wrk2":                    ({"library_refusal"}, False),
    "Rezolus":                 (set(), True),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_committed_evidence_still_classifies_as_the_paper_says(name):
    kinds, counts = EXPECTED[name]
    fold = by_harness(load())
    assert name in fold, "%s dropped out of the registry" % name
    assert fold[name]["kinds"] == kinds
    assert fold[name]["counts_discards"] is counts


def test_every_registry_row_carries_checkable_provenance():
    for r in load():
        assert r["source_url"].startswith("https://"), r
        assert r["retrieved"], r
        assert r["evidence"].strip(), r


def test_the_registry_contains_a_counterexample():
    """A survey that collected only confirmations would be an advertisement."""
    assert any(v["counts_discards"] for v in by_harness(load()).values())


def test_registry_path_points_at_the_committed_file():
    assert (ROOT / REGISTRY).is_file()


# --- the guard's scope, folded by path ---------------------------------------------------

def test_the_registry_records_which_span_each_finding_belongs_to():
    for r in load():
        assert r["path"], r
        assert r["clock"] in ("millisecond", "microsecond", "nanosecond"), r


def test_the_omb_guard_is_on_the_end_to_end_path_only():
    """The scoping a referee will check against MessageProducer.java in one click."""
    p = paths()
    e2e = p[("OpenMessaging Benchmark", "end-to-end")]
    pub = p[("OpenMessaging Benchmark", "publish")]
    assert "positive_only_filter" in e2e["kinds"]
    assert pub["kinds"] == set(), "the publish path carries no defect class"
    assert e2e["clock"] == "millisecond"
    assert pub["clock"] == "nanosecond"


def test_the_within_harness_contrast_finds_the_asymmetry():
    """The coarse clock and the filter land on the span that crosses processes."""
    c = within_harness_contrast()
    assert "OpenMessaging Benchmark" in c
    omb = c["OpenMessaging Benchmark"]
    assert omb["guarded"] == [("end-to-end", "millisecond")]
    assert omb["unguarded"] == [("publish", "nanosecond")]


def test_a_harness_with_one_path_shows_no_contrast():
    rows = [row(harness="X", path="only", evidence="if (latencyUs > 0) {")]
    assert within_harness_contrast(rows) == {}


def test_a_harness_guarded_on_every_path_shows_no_contrast():
    rows = [row(harness="X", path="a", evidence="if (latencyUs > 0) {"),
            row(harness="X", path="b", evidence="if (latencyMs > 0) {")]
    assert within_harness_contrast(rows) == {}


def test_the_round6_reaudit_headline_counts():
    """The counts Section IV-D quotes, after round 6's corrections.

    emqtt-bench was acquitted -- its guard is on a counter -- and two harnesses were added:
    Apache Pulsar (a second vendor's positivity filter) and wrk2 (the library-refusal class).
    Five of seven now dispose silently, and the two that do not are both named in the text:
    Rezolus counts, emqtt-bench keeps.
    """
    s = summary()
    assert s["harnesses"] == 7
    assert s["n_silent"] == 5
    assert s["counts_discards"] == ["Rezolus"]
    assert "emqtt-bench" not in s["silent"]
    assert "Apache Pulsar perf" in s["filters"]
    assert s["library_refusals"] == ["wrk2"]
