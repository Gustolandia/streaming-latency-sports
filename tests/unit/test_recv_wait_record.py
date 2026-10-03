"""R1's record, docs/results/recv_wait/README.md, against the committed tables it reads from.

Every figure the record states is recomputed here from r1_registry_runs.csv, r1_runs.csv and
r1_pauses.csv, and the comparison file must be exactly what scripts/recv_wait.py writes from the
run table. A sentence that drifts from its table fails here, not in a reader's hands.
"""
import collections
import csv
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
HERE = REPO / "docs" / "results" / "recv_wait"
sys.path.insert(0, str(REPO / "scripts"))

import recv_wait as rw  # noqa: E402


def table(name):
    with open(HERE / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def record():
    """The record's text with its line breaks folded, so a phrase may run across lines."""
    return " ".join((HERE / "README.md").read_text(encoding="utf-8").split())


def ms(us):
    return "%.2f" % (us / 1000.0)


FOUND = rw.compare(table("r1_runs.csv"))


def test_the_comparison_is_what_the_code_writes_from_the_run_table():
    written = (HERE / "r1_comparison.txt").read_text(encoding="utf-8")
    assert written == "\n".join(rw.lines(FOUND)) + "\n"


def test_the_runs_and_where_they_ran():
    runs, text = table("r1_registry_runs.csv"), record()
    assert len(runs) == 53 and "53 runs on the first x86 pair" in text
    assert set(r["pair"] for r in runs) == {"matched"}
    assert collections.Counter(r["campaign"] for r in runs) == {"r1_smoke": 2, "r1": 48,
                                                                "r1_more": 3}
    assert "the 48 runs of queue `r1`" in text and "the 3 runs of queue `r1_more`" in text
    assert set((r["kernel"], r["online_cpus"], r["slice_in_force_ns"]) for r in runs) == {
        ("6.8.0-1065-azure", "8", "3000000")}
    assert "kernel 6.8.0-1065-azure with 8 CPUs online and the 3 ms slice" in text
    smoke = [r for r in runs if r["campaign"] == "r1_smoke"]
    assert all(r["verdict"] == "repeat" and r["reasons"].startswith(
        "716 messages were sent after the warm-up, fewer than 99% of the 750 planned")
        for r in smoke)
    assert "716 messages were sent after the warm-up against the 750 planned" in text
    assert sum(1 for r in runs if r["verdict"] == "count") == 51 and "All 51 counted" in text
    assert len(table("r1_runs.csv")) == 51, "and every one of them was read"


def test_the_three_estimates_and_how_far_apart_they_lie():
    text = (HERE / "README.md").read_text(encoding="utf-8")
    for (broker, load), f in FOUND.items():
        cells = [ms(e) for e in f["estimates"]] + ["%.2f" % f["ratio"]]
        row = "| %s, %s%% | %s |" % (broker.capitalize(), load, " | ".join(cells))
        assert row in text, row


def test_the_verdicts_as_the_record_words_them():
    text = record()
    kafka75, kafka88 = FOUND[("kafka", "75")], FOUND[("kafka", "88")]
    redis75, redis88 = FOUND[("redis", "75")], FOUND[("redis", "88")]
    assert all(f["R1-a"] for f in FOUND.values())
    assert [f["R1-b"] for f in (kafka75, kafka88, redis75, redis88)] == [False, False, True, True]
    assert [f["R1-c"] for f in (kafka75, kafka88, redis75, redis88)] == [False, False, True, True]
    assert [f["R1-d"] for f in (kafka75, kafka88, redis75, redis88)] == [False, True, True, True]
    assert "R1-a holds and R1-b, R1-c and R1-d do not" in text
    assert "between %.1f and %.1f ms" % tuple(x / 1000 for x in rw.R1A_MEAN_US) in text
    assert "above %.1f ms" % (rw.R1A_P90_US / 1000) in text
    assert "below %.1f ms" % (rw.R1A_PRIORITY_MEAN_US / 1000) in text
    assert ("on Redis by %s ms at 75%% load and %s ms at 88%%" % (
        ms(redis75["p90_fall"]), ms(redis88["p90_fall"]))) in text
    assert ms(redis75["median_move"]) == ms(redis88["median_move"]) == "0.05"
    assert "moves its median by 0.05 ms at both" in text
    assert "falls %s ms at 75%%, short of the plan's %.0f ms" % (
        ms(kafka75["p90_fall"]), rw.R1B_P90_FALL_US / 1000) in text
    assert "at 88%% the median moves %s ms, past the plan's %.1f ms" % (
        ms(kafka88["median_move"]), rw.R1B_MEDIAN_MOVE_US / 1000) in text
    shares = [float(r["kernel_ge_wait_share"]) for r in table("r1_runs.csv")
              if r["kernel_ge_wait_share"]]
    assert len(shares) == 27 and min(shares) > 0.997
    assert "In every one of the 27 traced runs more than 99.7% of messages" in text
    assert "is %s and %s ms on Redis but %s and %s ms on Kafka, past the plan's %.1f ms" % (
        ms(redis75["difference"]), ms(redis88["difference"]), ms(kafka75["difference"]),
        ms(kafka88["difference"]), rw.R1C_DIFFERENCE_US / 1000) in text
    assert "method 1 gives %s ms against method 2's %s" % (
        ms(kafka75["estimates"][0]), ms(kafka75["estimates"][1])) in text


def test_the_pauses_as_the_record_tells_them():
    text, runs, pauses = record(), table("r1_runs.csv"), table("r1_pauses.csv")
    held = [r for r in runs if int(r["D_held"]) > 0]
    assert len(held) == len(pauses) == 5
    assert "Five of the 51 runs hold a message past the pause limit" in text
    redis = sorted((p for p in pauses if p["setup"].startswith("R1-redis")),
                   key=lambda p: float(p["worst_ms"]))
    assert len(redis) == 3 and all(p["setup"].endswith("-rtc") for p in redis)
    assert "last %s, %s and %s s" % tuple("%.2f" % (float(p["worst_ms"]) / 1000) for p in redis) \
        in text
    assert all(p["kind"] == "receiver" and float(p["max_gotit_ms"]) < 4 for p in redis)
    assert "the broker's confirmations stayed under 4 ms" in text
    assert "(for %s, %s and %s s)" % tuple("%.2f" % float(p["sampler_gap_s"]) for p in redis) \
        in text
    assert all(float(p["inside_reads"]) < 0.002 for p in redis)
    assert "under 0.2% of each pause inside a read" in text
    assert "waited %s, %s and %s s on the disk, in the same order" % tuple(
        "%.2f" % float(p["iowait_s"]) for p in redis) in text
    disk = [float(r["iowait_s"]) for r in runs]
    assert "against a median of %.2f s over all 51 runs" % statistics.median(disk) in text
    most = max(runs, key=lambda r: float(r["iowait_s"]))
    assert most["setup"] == "R1-redis-l75-ord" and most["D_held"] == "0"
    assert "an ordinary Redis run waited %.2f s on the disk and held nothing" % float(
        most["iowait_s"]) in text
    kafka = dict((p["kind"], p) for p in pauses if p["setup"].startswith("R1-kafka"))
    assert kafka["receiver"]["setup"] == "R1-kafka-l88-ord"
    assert float(kafka["receiver"]["sampler_gap_s"]) < pc_long()
    assert "a receiving-side pause of %.2f s in an ordinary run at 88%%" % (
        float(kafka["receiver"]["worst_ms"]) / 1000) in text
    assert "a broker-side one of %.2f s" % (float(kafka["broker"]["worst_ms"]) / 1000) in text
    cell = FOUND[("redis", "75")]["apart"]["untraced"]
    assert cell["runs"][1] == 2
    assert "the two untraced go-first Redis runs at 75%% show a mean D of %s ms" % ms(
        cell["D"]["mean"][1]) in text


def pc_long():
    """The census's own bound: a sampler gap this long means the sampler stopped too."""
    return rw.pc.LONG_S


def test_the_changelog_quotes_the_figures_the_paper_prints():
    """The repository's README says what Section VI-B now sizes, in figures typed by hand; they
    are held here to the macros the paper prints."""
    sys.path.insert(0, str(REPO / "scripts"))
    import emit_paper_numbers as epn
    m = dict(epn.recv_wait_macros(str(HERE)))
    readme = " ".join((REPO / "README.md").read_text(encoding="utf-8").split())
    assert "measured three ways in %s runs" % m["recvWaitRuns"] in readme
    assert "it added %s–%s ms to the mean latency" % (m["recvWaitAddedLo"],
                                                      m["recvWaitAddedHi"]) in readme
    assert "the median message waited %s–%s µs" % (m["recvWaitMedianLoUs"],
                                                   m["recvWaitMedianHiUs"]) in readme


def supplement_section():
    """Supplement S3.10, R1's account there, with its line breaks folded."""
    text = (REPO / "supplement.tex").read_text(encoding="utf-8")
    body = text.split("\\subsection{S3.10.", 1)[1].split("\\section{S4.", 1)[0]
    return " ".join(body.split())


class TestTheSupplementSays:
    """S3.10 states in words what its macros cannot carry: the design it ran, and which
    prediction failed where. Each is held here to the design file, the runner and the reading."""

    def test_the_design_it_describes_is_the_one_that_ran(self):
        import json
        text = supplement_section()
        design = json.loads((HERE / "r1_design.json").read_text(encoding="utf-8"))
        assert set(s["slice_ns"] for s in design["setups"]) == {3000000}
        assert "the base slice at $3$~ms" in text
        assert set(s["delay_ms"] for s in design["setups"]) == {0}
        assert "with no delay added" in text
        assert len(design["setups"]) == 8 and "Eight setups" in text
        assert design["rounds"] == 6 and "in six shuffled rounds" in text
        added = [r for r in table("r1_registry_runs.csv") if r["campaign"] == "r1_more"]
        assert len(added) == 3 and "Three runs added before anything was read" in text
        assert min(f["traced"][i] for f in FOUND.values() for i in (0, 1)) >= 3
        assert "at least three traced runs" in text
        runner = (REPO / "cloud" / "azure" / "campaign.sh").read_text(encoding="utf-8")
        assert 'consumer_wrap="sudo chrt -f 80 $consumer_wrap"' in runner
        assert "the real-time class at priority $80$" in text

    def test_what_it_says_happened_is_what_the_reading_found(self):
        text = supplement_section()
        kafka75, kafka88 = FOUND[("kafka", "75")], FOUND[("kafka", "88")]
        redis = [FOUND[("redis", "75")], FOUND[("redis", "88")]]
        assert all(f["D"]["p90"][1] < 1000 for f in redis)
        assert "it cut the ninetieth percentile of $D$ to under $1$~ms" in text
        assert all(abs(f["median_move"]) < 100 for f in redis)
        assert "left the median almost where it was" in text
        assert all(f["R1-a"] for f in FOUND.values()) and "The first prediction held" in text
        failed = sorted((p, key) for key, f in FOUND.items() for p in ("R1-b", "R1-c", "R1-d")
                        if not f[p])
        assert set(broker for _, (broker, _) in failed) == {"kafka"}
        assert set(p for p, _ in failed) == {"R1-b", "R1-c", "R1-d"}
        assert "The other three failed, each on \\kafka{}" in text
        assert kafka75["p90_fall"] < rw.R1B_P90_FALL_US
        assert kafka88["median_move"] > rw.R1B_MEDIAN_MOVE_US
        assert ("by less than the $\\recvPredFallMs$~ms predicted at $\\recvLowLoadPct\\%$ load, "
                "and moved the median by more than the $\\recvPredMoveMs$~ms allowed at "
                "$\\recvHighLoadPct\\%$") in text
        assert all(FOUND[(b, l)]["difference"] > rw.R1C_DIFFERENCE_US for b, l in FOUND
                   if b == "kafka")
        assert all(f["difference"] < rw.R1C_DIFFERENCE_US for f in redis)
        assert "where \\redis{}'s stayed under it" in text
        one, two, _ = kafka75["estimates"]
        assert two / one > rw.R1D_FACTOR
        assert "\\kafka{}'s first two estimates lie further apart" in text

    def test_its_qualifications_hold(self):
        text = supplement_section()
        assert rw.quality_report.STALL_MS == 150.0
        assert "more than $150$~ms late" in text
        thin = [f for f in FOUND.values() if f["apart"]["untraced"]["runs"][1] == 2]
        assert len(thin) == 3 and len(FOUND) == 4
        assert "three of the four go-first setups hold only two untraced runs" in text
        assert all(f["apart"]["traced"]["D"]["mean"][0] > f["apart"]["untraced"]["D"]["mean"][0]
                   for f in FOUND.values()), "the traced runs ran above the untraced everywhere"
