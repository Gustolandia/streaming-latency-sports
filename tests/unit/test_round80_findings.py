r"""Round 80's referee items, pinned so a later pass cannot quietly undo them.

Accept, with one item before proof.

R1. Section VIII-B paired a within-run correlation (0.80) with an independence factor computed
from condition-pooled margins. It quoted a median over 61 conditions as if over 70, and gave 12.4
as a stable number when its size depends on where the denominator is floored: the same pipeline
gives 7.3 with a 0.1% floor, over 54 conditions. `span_by_condition.py` now counts, exactly and
inside each run, the negatives that random pairing would produce, and `analyze_span_symmetry.py`
carries that beside the observed rate over the same pairs. The emitter publishes the factor at
both floors, pooled and within-run, each with its denominator. Section VIII-B quotes the within-run
factor at the floor, with its count; S24.2 prints all four. The direction holds in every condition.

W1 S24.2 prints the interquartile ranges of both correlations. W2 S19's "164 runs" are the cloud
testbed's. W3 Table S26 is emitted from its CSV and carries the change row that S2's pointer needs.
W4 S30 records Flink's latency tracking. W5 Section IV-D says the pacer-jitter range spans runs.
"""
from pathlib import Path
import csv
import re
import statistics
import sys

import pytest

REPO = Path(__file__).parent.parent.parent
BS = chr(92)
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests" / "unit"))


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "supplement.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def bib():
    return (REPO / "manuscript_references.bib").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ledger():
    gen = REPO / "docs" / "generated" / "paper_numbers.tex"
    if not gen.exists():                                # pragma: no cover - built by CI
        pytest.skip("paper_numbers.tex absent; run emit_paper_numbers.py")
    return dict(re.findall(BS * 2 + r"newcommand\{" + BS * 2 + r"(\w+)\}\{(.*)\}\s*$",
                           gen.read_text(encoding="utf-8"), re.M))


def flat(text):
    return " ".join(text.split())


def _between(text, start, end):
    i = text.index(start)
    return flat(text[i:text.index(end, i)])


def _rendered(name):
    pdf = REPO / ("%s.pdf" % name)
    if not pdf.is_file():
        pytest.skip("%s not built" % pdf.name)
    import pypdf
    return flat("\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages))


def _span_rows():
    return list(csv.DictReader(open(REPO / "docs" / "results" / "span_symmetry.csv",
                                    encoding="utf-8")))


class TestR1TheIndependenceFactorStatesItsUnitFloorAndDenominator:

    def test_all_four_versions_are_emitted_with_their_denominators(self, ledger):
        for key in ("indepOvershoot", "indepOvershootN", "indepPooledFloored",
                    "indepPooledFlooredN", "indepWithinAll", "indepWithinAllN",
                    "indepWithinFloored", "indepWithinFlooredN", "indepFloorPct"):
            assert key in ledger, key
        assert ledger["indepFloorPct"] == "0.1"
        assert int(ledger["indepWithinFlooredN"]) <= int(ledger["indepWithinAllN"]) \
            <= int(ledger["indepWithinConditions"])

    def test_they_are_the_values_the_referee_computed(self, ledger):
        assert (ledger["indepOvershoot"], ledger["indepOvershootN"]) == ("12.4", "61")
        assert ledger["indepPooledFlooredN"] == ledger["indepWithinFlooredN"] == "54"
        assert abs(float(ledger["indepPooledFloored"]) - 7.35) < 0.1
        assert abs(float(ledger["indepWithinFloored"]) - 7.4) < 0.2

    def test_the_floor_moves_it_and_the_unit_barely_does(self, ledger):
        pooled0, within0 = float(ledger["indepOvershoot"]), float(ledger["indepWithinAll"])
        pooledf, withinf = float(ledger["indepPooledFloored"]), float(ledger["indepWithinFloored"])
        assert abs(pooled0 - within0) < 1.0 and abs(pooledf - withinf) < 1.0
        assert pooled0 > 1.5 * pooledf, "if the floor stopped mattering, S24.2's sentence is wrong"

    def test_independence_overpredicts_everywhere_in_both_units(self, ledger):
        assert ledger["indepWithinOvershootConditions"] == ledger["indepWithinConditions"] \
            == ledger["indepOvershootConditions"] == "70"

    def test_the_rule_quotes_within_run_numbers_beside_the_within_run_correlation(self, paper):
        i = paper.index("Two delays with one cause are not independent")
        rule = flat(paper[i:i + 700])
        assert "within a run overpredicts" in rule
        for macro in ("spanRhoWithinMedian", "indepWithinConditions", "indepWithinFloored",
                      "indepWithinFlooredN", "indepFloorPct"):
            assert BS + macro in rule, macro
        assert BS + "indepOvershoot$" not in rule, "the pooled factor beside a within-run correlation"

    def test_the_supplement_prints_every_version(self, supplement):
        s = _between(supplement, "S24.2. The statistical inventory", "S24.3. The metric map")
        for macro in ("indepOvershoot$", "indepOvershootN", "indepPooledFloored$",
                      "indepPooledFlooredN", "indepWithinAll$", "indepWithinAllN",
                      "indepWithinFloored$", "indepWithinFlooredN", "indepFloorPct",
                      "indepWithinOvershootConditions"):
            assert BS + macro in s, macro

    def test_random_pairing_is_counted_exactly_inside_each_run(self):
        import span_by_condition as sbc
        # D 100, 200, 300 us; A 150, 250, 50 us. Random pairing within the run expects
        # (1 + 2 + 0) / 3 = 1 negative; the actual pairs carry 2.
        ev = {}
        for k, (d, a) in enumerate(((100, 150), (200, 250), (300, 50))):
            send = 1_000_000_000 + k * 10_000_000
            ev["e%d" % k] = (send, send + a * 1000, send + d * 1000)
        prod = [{"event_id": e, "t_prod_send_ns": s, "t_broker_ack_ns": a}
                for e, (s, a, _r) in ev.items()]
        cons = [{"event_id": e, "t_cons_recv_ns": r} for e, (_s, _a, r) in ev.items()]
        conds = {}
        sbc.consume_run(conds, [], "concurrency_n2_20260101_000000_kafka_feed1_rep1", prod, cons)
        (acc,) = conds.values()
        assert acc["indep_within"] == {"n": 3, "obs": 2, "pred": 1.0}

    def test_the_analysis_carries_both_columns_for_every_condition(self):
        rows = _span_rows()
        assert len(rows) == 70
        for r in rows:
            assert r["neg_frac_obs_pairs"] not in ("", "nan")
            assert r["neg_frac_pred_within"] not in ("", "nan")

    def test_the_analysis_reads_the_within_run_sums(self, tmp_path, monkeypatch):
        import json
        import analyze_span_symmetry as ass
        import test_analyze_span_symmetry as tass
        payload = json.loads(tass.synthetic(tmp_path).read_text(encoding="utf-8"))
        payload["conditions"]["kafka_n2_feed1#pass"]["indep_within"] = {"n": 200, "obs": 10,
                                                                        "pred": 40.0}
        path = tmp_path / "indep.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(ass, "IN_JSON", str(path))
        monkeypatch.setattr(ass, "OUT_CSV", str(tmp_path / "out.csv"))
        ass.main()
        rows = {r["condition"]: r for r in csv.DictReader(open(tmp_path / "out.csv"))}
        row = rows["kafka_n2_feed1#pass"]
        assert (float(row["neg_frac_obs_pairs"]), float(row["neg_frac_pred_within"])) == (0.05, 0.2)
        assert rows["kafka_n2_feed1#fail"]["neg_frac_pred_within"] in ("nan", "")

    @staticmethod
    def _emit(tmp_path, text):
        import emit_paper_numbers as epn
        p = tmp_path / "s.csv"
        p.write_text(text, encoding="utf-8")
        return dict(epn.separability_macros(path=str(p)))

    def test_the_emitter_floors_and_skips_as_it_says(self, tmp_path):
        got = self._emit(tmp_path,
                         "condition,neg_frac_obs,neg_frac_pred_indep,neg_frac_obs_pairs,"
                         "neg_frac_pred_within\n"
                         "a,0.01,0.2,0.01,0.1\n"        # above the floor in both units
                         "b,0.0005,0.05,0.0005,0.04\n"  # below the floor: counted, not floored
                         "c,0.0,0.1,nan,nan\n")         # no within-run sums
        assert got["indepConditions"] == "3" and got["indepWithinConditions"] == "2"
        assert (got["indepPooledFloored"], got["indepPooledFlooredN"]) == ("20.0", "1")
        assert (got["indepWithinAll"], got["indepWithinAllN"]) == ("45.0", "2")
        assert (got["indepWithinFloored"], got["indepWithinFlooredN"]) == ("10.0", "1")

    def test_an_older_csv_emits_only_the_pooled_versions(self, tmp_path):
        got = self._emit(tmp_path, "condition,neg_frac_obs,neg_frac_pred_indep\n"
                                   "a,0.0005,0.05\n")
        assert "indepOvershoot" in got and "indepPooledFloored" not in got
        assert not [k for k in got if k.startswith("indepWithin")]

    def test_within_run_rates_all_zero_emit_counts_but_no_factor(self, tmp_path):
        got = self._emit(tmp_path,
                         "condition,neg_frac_obs,neg_frac_pred_indep,neg_frac_obs_pairs,"
                         "neg_frac_pred_within\n"
                         "a,0.01,0.2,0.0,0.1\n")
        assert got["indepWithinConditions"] == "1"
        assert "indepWithinAll" not in got and "indepWithinFloored" not in got

    def test_a_condition_independence_underpredicts_is_counted_but_not_as_overshoot(self, tmp_path):
        # Every real condition overpredicts, so without this row the other side of the count
        # was never taken, and "in all N conditions" could not have come out as anything else.
        got = self._emit(tmp_path,
                         "condition,neg_frac_obs,neg_frac_pred_indep,neg_frac_obs_pairs,"
                         "neg_frac_pred_within\n"
                         "a,0.01,0.2,0.01,0.1\n"
                         "b,0.01,0.2,0.05,0.02\n")
        assert got["indepWithinConditions"] == "2"
        assert got["indepWithinOvershootConditions"] == "1"


class TestW1TheCorrelationsCarryTheirSpread:

    def test_the_interquartile_ranges_are_the_data(self, ledger):
        rows = _span_rows()
        for macro, col in (("spanRhoIQR", "rho_DA"), ("spanRhoWithinIQR", "rho_DA_within")):
            vals = [float(r[col]) for r in rows]
            q = statistics.quantiles(vals, n=4)
            assert ledger[macro] == "%.2f$--$%.2f" % (q[0], q[2]), macro

    def test_the_within_run_lower_quartile_is_the_longer_tail(self, ledger):
        pooled_lo = float(ledger["spanRhoIQR"].split("$")[0])
        within_lo = float(ledger["spanRhoWithinIQR"].split("$")[0])
        assert within_lo < pooled_lo - 0.05

    def test_s24_2_prints_both(self, supplement):
        s = _between(supplement, "S24.2. The statistical inventory", "S24.3. The metric map")
        assert BS + "spanRhoIQR" in s and BS + "spanRhoWithinIQR" in s


class TestW2TheOffsetCountsBelongToTheCloudTestbed:

    def test_the_sentence_says_which_testbed_the_counts_are_from(self, supplement):
        text = flat(supplement)
        assert ("reproduced on both testbeds, and on the cloud testbed across four concurrency "
                "levels and $164$ runs") in text
        assert "across both testbeds, four concurrency levels" not in text


class TestW3TableS26ShowsTheNumberItIsPointedAtFor:

    def test_every_cell_is_emitted_from_the_csv(self, ledger):
        rows = {r["stamp"]: r for r in csv.DictReader(
            open(REPO / "docs" / "results" / "model" / "ec3_stamping.csv", encoding="utf-8"))}
        cb, inl = rows["callback"], rows["inline"]
        assert ledger["hThreeKafkaCallback"] == "%.3f" % float(cb["kafka_ms"])
        assert ledger["hThreeDiffInline"] == "%+.3f" % float(inl["difference_ms"])
        shrink = float(cb["difference_ms"]) - float(inl["difference_ms"])
        assert ledger["hThreeShrinkage"] == "%.3f" % shrink
        assert ledger["hThreeDiffChange"] == "%+.3f" % -shrink

    def test_the_table_reads_the_ledger_and_has_a_change_row(self, supplement):
        i = supplement.index(BS + "label{tab:h3}")
        block = supplement[supplement.rindex(BS + "begin{table}", 0, i):
                           supplement.index(BS + "end{table}", i)]
        assert "Change" in block and BS + "hThreeShrinkage" in block
        assert "0.392" not in block and "0.286" not in block, "a typed cell came back"

    def test_the_pointer_and_the_limitation_quote_the_emitted_shrinkage(self, supplement):
        text = flat(supplement)
        assert "Table~" + BS + "ref{tab:h3} shows that $" + BS + "hThreeShrinkage$~ms" in text
        assert "$0.07$~ms of the gap" not in text
        assert "how the $" + BS + "hThreeShrinkage$~ms offset scales" in text

    def test_a_missing_or_malformed_csv_emits_nothing(self, tmp_path):
        import emit_paper_numbers as epn
        assert epn.h3_stamping_macros(str(tmp_path / "absent.csv")) == []
        bad = tmp_path / "bad.csv"
        bad.write_text("stamp,kafka_ms\ncallback,0.3\n", encoding="utf-8")
        assert epn.h3_stamping_macros(str(bad)) == []


class TestW4FlinkIsRecordedBesideTheRuntimes:

    def test_s30_names_the_metric_and_its_precondition(self, supplement, paper):
        s = _between(supplement, "S30. Where the timestamp is written", "S31. Neighboring rules")
        assert BS + "cite{flink_latencystats}" in s and BS + "cite{flink_metrics_docs}" in s
        assert "getMarkedTime" in s and "in sync" in s
        assert "flink" not in paper.lower(), "supplement only, at 45 of 45 references"

    def test_the_entries_quote_what_was_read(self, bib):
        for key, want in (("flink_latencystats", "System.currentTimeMillis() - marker.getMarkedTime()"),
                          ("flink_metrics_docs", "Flink assumes that the clocks of all machines")):
            i = bib.index("{" + key + ",")
            entry = flat(bib[i:bib.index("\n}", i)])
            assert want in entry and "Accessed: Sep. 14, 2026" in entry, key


class TestW5ThePacerRangeSaysWhatItSpans:

    def test_the_run_count_is_emitted_from_the_rows_that_give_the_range(self, ledger):
        import stat_intervals as si
        assert ledger["pacerJitterRuns"] == str(si.harness_pacer_jitter_runs())
        assert int(ledger["pacerJitterRuns"]) > 1

    def test_rows_without_the_column_are_not_counted(self, monkeypatch):
        import stat_intervals as si
        monkeypatch.setattr(si, "_rows", lambda *parts: [{"jitter_p90_us": "66.3"},
                                                         {"jitter_p90_us": "x"}, {}])
        assert si.harness_pacer_jitter_runs() == 1

    def test_the_sentence_says_across_how_many_runs(self, paper):
        assert ("at p90 across its $" + BS + "pacerJitterRuns$ runs") in flat(paper)


class TestTheRenderedPagesCarryIt:

    def test_the_article(self):
        # Hyphenation and glyph spacing differ between extractors, and one of them drops the
        # space on either side of inline math, so the phrase is matched on its words rather
        # than on one exact string.
        text = re.sub(r"(\w)- (\w)", r"\1\2", _rendered("paper"))
        assert re.search(r"within a run\s*overpredicts", text)
        assert re.search(r"rate above\s*0\.1\s*%", text)
        assert re.search(r"at p90 across its\s*\d+\s*runs", text)

    def test_the_supplement(self):
        text = _rendered("supplement")
        assert "interquartile range" in text and "latency metric sits in this regime" in text
