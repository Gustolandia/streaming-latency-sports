r"""Round 81's referee items, pinned so a later pass cannot quietly undo them.

Accept, with two items before proof.

R1. Round 80 moved Section VIII-B's independence factor to 7.4 within runs above a 0.1% floor, and
two supplement sentences kept describing the number it replaced. S12 called the pooled, unfloored
"12.4x against 21.3x" the overshoot "of Section VIII-B". S24.2 said VIII-B alone quotes the
within-run figure, which V-A now reports first. The emitter adds the ratio of medians over the
floored within-run population, and S12 sets both estimators side by side in both populations.
`test_supplement_pointers.py` gains the gate this class of defect needed: a number beside a
main-text pointer must be one that section prints. Its first run found two more.

R2. The bibliography style lowercases the first letter of a note, and two of the article's notes
began with a name ([5] "open Compute Project", [20] "dTrace"). Gated in
`test_bibliography_note_case.py`.

W1 Table S26 carries its replication (E-C4), a bootstrap interval over runs for every change,
Kafka's share, and a clause on independent rounding. W2 S30 says Flink's latency tracking is opt-in
and meant for debugging. W3 the supplement's review note is in the tense of the submission. W4 S33
records 2026 practitioner advice that reads a negative latency as skew. W5 Section V-A names the
two quantities it calls independent.
"""
from pathlib import Path
import csv
import io
import math
import re
import statistics
import sys
import tarfile

import pytest

REPO = Path(__file__).parent.parent.parent
BS = chr(92)
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests" / "unit"))

RUNS_CSV = REPO / "docs" / "results" / "model" / "ec3_stamping_runs.csv"
SUMMARY_CSV = REPO / "docs" / "results" / "model" / "ec3_stamping.csv"
REPLICATION_CSV = (REPO / "cloud_archive" / "extracted" / "docs" / "results" / "depth_rep2"
                   / "model" / "ec3_stamping.csv")


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


def _entry(bib, key):
    i = bib.index("{" + key + ",")
    return flat(bib[i:bib.index("\n}", i)])


def _s12(supplement):
    text = flat(supplement)
    i = text.index("This project has been caught by the same distinction")
    return text[i:i + 1100]


# ---------------------------------------------------------------- R1

class TestR1TheSupplementDescribesTheNumberTheArticlePrints:

    def test_the_ratio_of_medians_is_over_the_floored_within_run_population(self, ledger):
        import emit_paper_numbers as epn
        rows = csv.DictReader(open(REPO / "docs" / "results" / "span_symmetry.csv",
                                   encoding="utf-8"))
        kept = []
        for r in rows:
            o, p = float(r["neg_frac_obs_pairs"]), float(r["neg_frac_pred_within"])
            if o == o and p == p and o > epn.INDEP_FLOOR:
                kept.append((o, p))
        want = statistics.median(p for _, p in kept) / statistics.median(o for o, _ in kept)
        assert ledger["indepWithinFlooredRatioOfMedians"] == "%.1f" % want
        assert len(kept) == int(ledger["indepWithinFlooredN"])

    def test_at_the_floor_the_estimators_nearly_agree_and_without_it_they_do_not(self, ledger):
        at_floor = float(ledger["indepWithinFloored"]) / float(
            ledger["indepWithinFlooredRatioOfMedians"])
        unfloored = float(ledger["indepRatioOfMedians"]) / float(ledger["indepOvershoot"])
        assert abs(at_floor - 1.0) < 0.2, "S12 says they nearly agree at the floor"
        assert unfloored > 1.5, "S12 says they differ without it"

    @staticmethod
    def _emit(tmp_path, body):
        import emit_paper_numbers as epn
        p = tmp_path / "s.csv"
        p.write_text("condition,neg_frac_obs,neg_frac_pred_indep,neg_frac_obs_pairs,"
                     "neg_frac_pred_within\n" + body, encoding="utf-8")
        return dict(epn.separability_macros(path=str(p)))

    def test_the_emitter_uses_the_floored_rows_only(self, tmp_path):
        got = self._emit(tmp_path, "a,0.01,0.2,0.01,0.1\n"
                                   "b,0.02,0.2,0.02,0.3\n"
                                   "c,0.0005,0.05,0.0005,0.04\n")   # below the floor
        assert got["indepWithinFlooredRatioOfMedians"] == "13.3"      # 0.2 / 0.015

    def test_no_floored_rows_emit_no_ratio_of_medians(self, tmp_path):
        got = self._emit(tmp_path, "a,0.0005,0.05,0.0005,0.04\n")
        assert "indepWithinFlooredRatioOfMedians" not in got

    def test_s12_sets_both_estimators_in_both_populations(self, supplement):
        s = _s12(supplement)
        for macro in ("indepOvershoot", "indepRatioOfMedians", "indepWithinFloored",
                      "indepWithinFlooredRatioOfMedians", "indepFloorPct", "indepWithinFlooredN"):
            assert BS + macro in s, macro
        assert "independence overshoot of Section~" not in s
        assert "Sections~" + BS + "mainAudit{} and~" + BS + "mainAuthors{} quote the median of " \
               "ratios at that floor" in s

    def test_s24_2_names_both_sections(self, supplement):
        s = _between(supplement, "S24.2. The statistical inventory", "S24.3. The metric map")
        assert ("Sections~" + BS + "mainAudit{} and~" + BS + "mainAuthors{} quote the within-run "
                "figure at the floor") in s
        assert "Section~" + BS + "mainAuthors{} quotes the within-run figure" not in s

    def test_both_article_sections_print_the_within_run_figure(self, paper):
        import test_supplement_pointers as tsp
        for label in ("sec:audit", "sec:authors"):
            text = tsp.section_source(paper, label)
            for macro in ("indepWithinFloored", "indepWithinFlooredN", "indepFloorPct"):
                assert re.search(re.escape(BS + macro) + r"(?![A-Za-z])", text), (label, macro)

    def test_the_two_misattributed_numbers_now_point_where_they_are_printed(self, supplement):
        text = flat(supplement)
        assert (BS + "newcommand{" + BS + "mainSettle}{" + BS + "ref{P-sec:twostate}}") in text
        assert "Section~" + BS + "mainSettle{} of the main text gives $" + BS + "rtFactorLow$" in text
        assert "mode of Section~" + BS + "mainSpectrum{} sits on" in text
        assert "finding in Section~" + BS + "mainBrokers{} --- our own two clients differ" in text


# ---------------------------------------------------------------- W1: the numbers

def _runs():
    return list(csv.DictReader(open(RUNS_CSV, encoding="utf-8")))


def _cell_medians(rows, campaign):
    cells = {}
    for r in rows:
        if r["campaign"] == campaign:
            cells.setdefault((r["stamp"], r["backend"]), []).append(float(r["median_ms"]))
    return {k: statistics.median(v) for k, v in cells.items()}, {k: len(v) for k, v in cells.items()}


class TestW1TableS26CarriesItsReplicationAndItsIntervals:

    @pytest.mark.parametrize("campaign,summary", [("E-C3", SUMMARY_CSV), ("E-C4", REPLICATION_CSV)])
    def test_the_per_run_file_reproduces_the_committed_summaries(self, campaign, summary):
        if not summary.exists():
            pytest.skip("archived replication summary not extracted")
        med, _ = _cell_medians(_runs(), campaign)
        for r in csv.DictReader(open(summary, encoding="utf-8")):
            for backend in ("kafka", "redis"):
                assert round(med[(r["stamp"], backend)], 4) == float(r[backend + "_ms"]), \
                    (campaign, r["stamp"], backend)

    def test_every_cell_holds_the_runs_the_table_says(self, ledger):
        for campaign, macro, n in (("E-C3", "hThreeRuns", 10), ("E-C4", "hThreeRepRuns", 30)):
            _, counts = _cell_medians(_runs(), campaign)
            assert set(counts.values()) == {n}, campaign
            assert ledger[macro] == str(n)

    def test_the_intervals_are_seeded_and_bracket_their_estimates(self):
        import stat_intervals as si
        first, second = si.h3_stamping_intervals(), si.h3_stamping_intervals()
        assert first == second and set(first) == {"E-C3", "E-C4"}
        for c in first.values():
            for name, value in c["change"].items():
                lo, hi = c["ci"][name]
                assert lo <= value <= hi, name

    def test_the_shrinkage_is_kafkas_and_redis_spans_zero_in_both_campaigns(self):
        import stat_intervals as si
        for campaign, c in si.h3_stamping_intervals().items():
            assert c["ci"]["difference"][1] < 0, campaign
            assert c["ci"]["kafka"][1] < 0, campaign
            lo, hi = c["ci"]["redis"]
            assert lo < 0 < hi, "the caption says Redis's interval spans zero: %s" % campaign

    def test_the_ledger_carries_the_intervals_shares_and_residual(self, ledger):
        import stat_intervals as si
        iv = si.h3_stamping_intervals()
        for campaign, prefix in (("E-C3", "hThree"), ("E-C4", "hThreeRep")):
            c = iv[campaign]
            for name, label in (("kafka", "Kafka"), ("redis", "Redis"), ("difference", "Diff")):
                assert ledger[prefix + label + "ChangeCI"] == "%+.3f$, $%+.3f" % c["ci"][name]
            lo, hi = c["ci"]["difference"]
            assert ledger[prefix + "ShrinkageCI"] == "%.3f$--$%.3f" % (-hi, -lo)
            assert ledger[prefix + "KafkaSharePct"] == "%.0f" % (100 * c["kafka_share"])
        assert ledger["hThreeKafkaSharePct"] == "98", "round 81's '98%, not entirely'"
        tost = float(ledger["tostHL"])
        residual = [tost - float(ledger["hThreeShrinkage"]), tost - float(ledger["hThreeRepShrinkage"])]
        assert ledger["hThreeResidualRange"] == "%.2f$--$%.2f" % (min(residual), max(residual))

    def test_table_s26_prints_both_campaigns_with_intervals(self, supplement):
        i = supplement.index(BS + "label{tab:h3}")
        block = supplement[supplement.rindex(BS + "begin{table}", 0, i):
                           supplement.index(BS + "end{table}", i)]
        for macro in ("hThreeRuns", "hThreeRepRuns", "hThreeKafkaChangeCI", "hThreeRedisChangeCI",
                      "hThreeDiffChangeCI", "hThreeRepKafkaCallback", "hThreeRepDiffInline",
                      "hThreeRepDiffChange", "hThreeRepDiffChangeCI", "hThreeShrinkageCI",
                      "hThreeRepShrinkageCI", "hThreeKafkaSharePct", "hThreeRepKafkaSharePct"):
            assert BS + macro in block, macro
        text = flat(block)
        assert "rounded independently" in text and "E-C4" in text
        assert "entirely on" not in text

    def test_s2_and_the_limitation_quote_the_interval_and_the_replication(self, supplement):
        text = flat(supplement)
        assert ("accounts for $" + BS + "hThreeShrinkage$~ms of the gap [95" + BS
                + "% bootstrap over runs: $" + BS + "hThreeShrinkageCI$]") in text
        assert "difference of $" + BS + "hThreeResidualRange$~ms" in text
        assert "near $0.34$~ms" not in text
        assert ("sizing the shrinkage at $" + BS + "hThreeRepShrinkage$~ms against $" + BS
                + "hThreeShrinkage$~ms") in text


# ---------------------------------------------------------------- W1: the pipeline pieces

def _csv_bytes(fields, rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _run_tables(transports_ms):
    prod = _csv_bytes(["event_id", "t_broker_ack_ns"],
                      [{"event_id": "e%d" % i, "t_broker_ack_ns": 1_000_000}
                       for i in range(len(transports_ms))])
    cons = _csv_bytes(["event_id", "t_consume_ns"],
                      [{"event_id": "e%d" % i, "t_consume_ns": 1_000_000 + int(ms * 1e6)}
                       for i, ms in enumerate(transports_ms)])
    return prod, cons


TS_CB, TS_IN = "n2_20260724_031934", "n2_20260724_033718"


class TestTheArchiveReader:

    def test_campaign_timestamps_come_from_the_condition_directories(self):
        import h3_stamping_runs as h3
        names = ["docs/results/depth/ec3/callback/concurrency_concurrency_%s/s.json" % TS_CB,
                 "docs/results/depth_rep2/ec3/inline/concurrency_concurrency_%s" % TS_IN,
                 "docs/results/depth/ea6/concurrency_concurrency_n2_20260101_000000/s.json"]
        assert h3.campaign_timestamps(names) == {TS_CB: ("E-C3", "callback"),
                                                 TS_IN: ("E-C4", "inline")}

    def test_run_key_accepts_only_the_wanted_runs_tables(self):
        import h3_stamping_runs as h3
        stamps = {TS_CB: ("E-C3", "callback")}
        good = "runs/concurrency_%s_kafka_feed1_rep1/producer.csv" % TS_CB
        assert h3.run_key(good, stamps) == (TS_CB, "kafka", "concurrency_%s_kafka_feed1_rep1"
                                            % TS_CB, "producer")
        assert h3.run_key("runs/concurrency_n2_20990101_000000_kafka_x/producer.csv", stamps) is None
        assert h3.run_key("runs/concurrency_%s_kafka_x/stats.json" % TS_CB, stamps) is None

    def test_run_medians_keeps_complete_joinable_runs_only(self):
        import h3_stamping_runs as h3
        stamps = {TS_CB: ("E-C3", "callback")}
        base = "runs/concurrency_%s_%s_feed1_%s/%s.csv"
        p1, c1 = _run_tables([1.0, 2.0, 9.0])
        p2, c2 = _run_tables([3.0])
        members = [
            (base % (TS_CB, "redis", "rep1", "consumer_events"), c1),
            (base % (TS_CB, "redis", "rep1", "producer"), p1),
            (base % (TS_CB, "kafka", "rep2", "producer"), p2),
            (base % (TS_CB, "kafka", "rep2", "consumer_events"), c2),
            (base % (TS_CB, "kafka", "rep3", "producer"), p2),                  # no consumer table
            (base % (TS_CB, "kafka", "rep4", "producer"), p2),                  # malformed consumer
            (base % (TS_CB, "kafka", "rep4", "consumer_events"),
             b"event_id,t_consume_ns\ne0,notanumber\n"),
            (base % (TS_CB, "kafka", "rep5", "producer"),                       # nothing joins
             b"event_id,t_broker_ack_ns\ne0,None\n"),
            (base % (TS_CB, "kafka", "rep5", "consumer_events"), c2),
            ("runs/unrelated/producer.csv", p1),
        ]
        rows = h3.run_medians(members, stamps)
        assert [(r["backend"], r["run"].rsplit("_", 1)[1], r["median_ms"]) for r in rows] == [
            ("kafka", "rep2", "3.000000"), ("redis", "rep1", "2.000000")]
        assert set(rows[0]) == set(h3.FIELDS)

    def _archives(self, tmp_path, with_conditions=True):
        docs, runs = tmp_path / "docs.tgz", tmp_path / "runs.tgz"
        with tarfile.open(docs, "w:gz") as tar:
            names = (["docs/results/depth/ec3/callback/concurrency_concurrency_%s/s.json" % TS_CB]
                     if with_conditions else ["docs/results/other/readme.txt"])
            for name in names:
                data = b"{}"
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        with tarfile.open(runs, "w:gz") as tar:
            folder = tarfile.TarInfo("runs/concurrency_%s_kafka_feed1_rep1" % TS_CB)
            folder.type = tarfile.DIRTYPE                      # not a file: never read
            tar.addfile(folder)
            prod, cons = _run_tables([0.5, 0.7])
            for table, data in (("producer", prod), ("consumer_events", cons)):
                info = tarfile.TarInfo("runs/concurrency_%s_kafka_feed1_rep1/%s.csv" % (TS_CB, table))
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return docs, runs

    def test_main_writes_the_per_run_file(self, tmp_path, capsys):
        import h3_stamping_runs as h3
        docs, runs = self._archives(tmp_path)
        out = tmp_path / "runs.csv"
        assert h3.main(["--runs-archive", str(runs), "--docs-archive", str(docs),
                        "--out", str(out)]) == 0
        rows = list(csv.DictReader(open(out, encoding="utf-8")))
        assert [(r["campaign"], r["stamp"], r["backend"], r["median_ms"]) for r in rows] == [
            ("E-C3", "callback", "kafka", "0.600000")]
        assert "E-C3: 1 runs" in capsys.readouterr().out

    def test_main_declines_an_archive_without_the_conditions(self, tmp_path, capsys):
        import h3_stamping_runs as h3
        docs, runs = self._archives(tmp_path, with_conditions=False)
        assert h3.main(["--runs-archive", str(runs), "--docs-archive", str(docs),
                        "--out", str(tmp_path / "x.csv")]) == 1
        assert not (tmp_path / "x.csv").exists()

    def test_the_rows_join_is_the_directory_join(self):
        import analyze_depth as ad
        prod = [{"event_id": "e0", "t_broker_ack_ns": "1000000"},
                {"event_id": "e1", "t_broker_ack_ns": ""}]
        cons = [{"event_id": "e0", "t_consume_ns": "3000000"},
                {"event_id": "e1", "t_consume_ns": "5000000"}]
        assert ad.transport_median_from_rows(prod, cons) == pytest.approx(2.0)
        with pytest.raises(ValueError):
            ad.transport_median_from_rows(prod, [{"event_id": "e0", "t_consume_ns": "x"}])


class TestTheInterval:

    def _file(self, tmp_path, rows):
        p = tmp_path / "r.csv"
        p.write_bytes(_csv_bytes(["campaign", "stamp", "backend", "run", "median_ms"], rows))
        return str(p)

    @staticmethod
    def _cells(campaign, values):
        rows = []
        for (stamp, backend), vals in values.items():
            for i, v in enumerate(vals):
                rows.append({"campaign": campaign, "stamp": stamp, "backend": backend,
                             "run": "r%d" % i, "median_ms": v})
        return rows

    def test_an_unreadable_or_malformed_file_gives_nothing(self, tmp_path):
        import stat_intervals as si
        assert si.h3_stamping_intervals(str(tmp_path / "absent.csv")) == {}
        bad = tmp_path / "bad.csv"
        bad.write_text("campaign,stamp\nE-C3,callback\n", encoding="utf-8")
        assert si.h3_stamping_intervals(str(bad)) == {}
        worse = tmp_path / "worse.csv"
        worse.write_text("campaign,stamp,backend,run,median_ms\nE-C3,callback,kafka,r,x\n",
                         encoding="utf-8")
        assert si.h3_stamping_intervals(str(worse)) == {}

    def test_a_campaign_missing_a_cell_is_left_out(self, tmp_path):
        import stat_intervals as si
        rows = self._cells("E-C9", {("callback", "kafka"): [1.0], ("callback", "redis"): [1.0],
                                    ("inline", "kafka"): [1.0]})
        assert si.h3_stamping_intervals(self._file(tmp_path, rows), n_boot=50) == {}

    def test_a_zero_shrinkage_has_no_share(self, tmp_path):
        import stat_intervals as si
        cells = {(s, b): [1.0, 1.0] for s in ("callback", "inline") for b in ("kafka", "redis")}
        got = si.h3_stamping_intervals(self._file(tmp_path, self._cells("E-C9", cells)), n_boot=50)
        assert math.isnan(got["E-C9"]["kafka_share"])
        assert got["E-C9"]["ci"]["difference"] == (0.0, 0.0)

    def test_the_share_is_kafkas_change_over_the_differences(self, tmp_path):
        import stat_intervals as si
        cells = {("callback", "kafka"): [0.4], ("inline", "kafka"): [0.3],
                 ("callback", "redis"): [0.1], ("inline", "redis"): [0.15]}
        c = si.h3_stamping_intervals(self._file(tmp_path, self._cells("E-C9", cells)),
                                     n_boot=20)["E-C9"]
        assert c["change"]["difference"] == pytest.approx(-0.15)
        assert c["kafka_share"] == pytest.approx(0.1 / 0.15)


class TestTheEmitterBranches:

    def test_without_the_per_run_file_only_the_summary_is_emitted(self, tmp_path):
        import emit_paper_numbers as epn
        got = dict(epn.h3_stamping_macros(str(SUMMARY_CSV), str(tmp_path / "absent.csv")))
        assert "hThreeShrinkage" in got and "hThreeRuns" not in got
        assert "hThreeResidualRange" not in got

    def test_unequal_cells_print_a_range_and_no_tost_no_residual(self, tmp_path, monkeypatch):
        import emit_paper_numbers as epn
        rows = []
        for stamp in ("callback", "inline"):
            for backend, vals in (("kafka", [0.4, 0.5]), ("redis", [0.1])):
                for i, v in enumerate(vals):
                    rows.append({"campaign": "E-C3", "stamp": stamp, "backend": backend,
                                 "run": "r%d" % i, "median_ms": v})
        p = tmp_path / "r.csv"
        p.write_bytes(_csv_bytes(["campaign", "stamp", "backend", "run", "median_ms"], rows))
        monkeypatch.setattr(epn, "tost_macros", lambda: [])
        got = dict(epn.h3_stamping_macros(str(SUMMARY_CSV), str(p)))
        assert got["hThreeRuns"] == "1$--$2"
        assert "hThreeRepRuns" not in got and "hThreeResidualRange" not in got


# ---------------------------------------------------------------- W2 to W5

class TestW2FlinkIsOptIn:

    def test_s30_says_it_is_opt_in_and_for_debugging(self, supplement, bib):
        s = _between(supplement, "S30. Where the timestamp is written", "S31. Neighboring rules")
        assert "an opt-in metric its documentation recommends for debugging only" in s
        assert "disabled by default" in s and "Once enabled" in s
        assert "is disabled by default" in _entry(bib, "flink_metrics_docs")


class TestW3TheReviewNoteIsInTheSubmissionsTense:

    def test_the_note(self, supplement):
        assert ("Before this submission, the manuscript had not been submitted to, or reviewed by, "
                "any journal") in flat(supplement)


class TestW4TheSkewReadingIn2026:

    def test_s33_records_the_guide_beside_the_maintainer(self, supplement, paper):
        s = _between(supplement, "S33. Where our reading parts", "S33.1. The survey")
        assert BS + "cite{hasija2026kafkalag}" in s and BS + "cite{omb_issue216}" in s
        assert "a skew problem, not a fast consumer" in s
        assert "hasija" not in paper.lower(), "supplement only, at 45 of 45 references"

    def test_the_entry_names_its_author_and_quotes_what_was_read(self, bib):
        e = _entry(bib, "hasija2026kafkalag")
        assert "Hasija, Chirag" in e and "Accessed: Sep. 14, 2026" in e
        assert "If your p50 latency is negative you have a skew problem, not a fast consumer" in e


class TestW5SectionVANamesWhatIsIndependent:

    def test_the_sentence(self, paper):
        assert "treating the two as independent within a run would overpredict them" in flat(paper)


class TestTheRenderedPagesCarryIt:

    def test_the_article(self):
        text = re.sub(r"(\w)- (\w)", r"\1\2", _rendered("paper"))
        assert re.search(r"treating\s*the\s*two\s*as\s*independent", text)
        assert "Open Compute Project" in text and "DTrace breakdown" in text

    def test_the_supplement(self):
        text = re.sub(r"(\w)- (\w)", r"\1\2", _rendered("supplement"))
        assert "rounded independently" in text and "Before this submission" in text
        assert "opt-in metric" in text and re.search(r"nearly\s*agree", text)
