"""Supplement Part V, the pre-registered law campaign, read against the records it reports.

Every number S34 to S37 and their three tables print is recomputed here from committed files:
the run registry (docs/results/registry/), the final judging on all the runs and on each view
(docs/results/law/judged-27-sep/), the strange results of 28 September
(docs/results/law/strange-results-28-sep/), the frozen plan (freezes/28-experiment-plan/), and
every run's marks as scripts/law_runs.py reads them. A part rewritten, or an answer judged again,
cannot drift from the other unseen.
"""
import collections
import csv
import datetime
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
LAW = REPO / "docs" / "results" / "law"
JUDGED = LAW / "judged-27-sep"
STRANGE = LAW / "strange-results-28-sep"
REGISTRY = REPO / "docs" / "results" / "registry"
PLAN = REPO / "freezes" / "28-experiment-plan" / "experiment_plan.tex"
PAIRS = ("matched", "matched-b", "arm")

sys.path.insert(0, str(REPO / "scripts"))
import law_runs  # noqa: E402


def _flat(text):
    return " ".join(text.split())


@pytest.fixture(scope="module")
def part_v():
    """Part V's source, flattened.

    6 Oct 2026: the readings the paper's Limitations quote from this campaign are emitted
    (`law_reading_macros`, the `rec` and `pSix` families), and Part V prints them through those
    macros, so they are expanded to the numbers the pins below recompute.
    """
    text = (REPO / "postmortem.tex").read_text(encoding="utf-8")
    start = text.index(r"\section*{Part V. The pre-registered law campaign}")
    body = text[start:text.index(r"\bibliographystyle", start)]
    gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
    ledger = dict(re.findall(r"\\newcommand\{\\(\w+)\}\{(.*)\}\s*$", gen, re.M))
    body = re.sub(r"\\((?:rec|pSix)[A-Za-z]+)(?![A-Za-z])",
                  lambda m: ledger.get(m.group(1), m.group(0)), body)
    return _flat(body)


@pytest.fixture(scope="module")
def runs():
    return law_runs.load()


def _has(text, *phrases):
    for phrase in phrases:
        assert _flat(phrase) in text, phrase


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _answer(name, view="all"):
    return _json(JUDGED / view / (name + ".json"))


def _verdict(name, view="all"):
    lines = (JUDGED / view / (name + ".txt")).read_text(encoding="utf-8").splitlines()
    return next(l for l in lines if re.match(r"^(P\d|A9|M0|ERROR)", l))


def _f(value, places):
    return "%.*f" % (places, value)


def _comma(n):
    return format(n, ",")


def _quality():
    with open(JUDGED / "quality_by_campaign.csv", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _registry():
    rows = []
    for pair in PAIRS:
        with open(REGISTRY / ("runs_%s.csv" % pair), newline="", encoding="utf-8") as fh:
            rows += list(csv.DictReader(fh))
    return rows


# --- S34 ------------------------------------------------------------------------------------------

def test_the_plan_as_registered(part_v):
    plan = PLAN.read_text(encoding="utf-8")
    assert "What changed since version 31" in plan and "version 32" in plan.lower()
    _has(part_v, "the version in force at the end is the thirty-second, freeze~28")
    for rule in ("The first 30 seconds are discarded", "within 3 points of target",
                 "within 2\\% of target", "within 0.05~ms of the delay set",
                 "$0.5s$ and $0.9s$", "$s + 1.5h$ and $2(s + h)$", "at least 4",
                 "Ceiling:} 40 rounds"):
        assert rule in plan, rule
    _has(part_v, "after a 30~s warm-up", "the load within 3 points of its target",
         "publish rate within $2\\%$", "within $50\\,\\mu$s of its setting",
         "at least four and at most forty")


def test_the_history_of_the_plan(part_v):
    """Which changes came before any result, which after one, and what was added as it ran."""
    readme = (REPO / "freezes" / "README.md").read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")
    first = (REPO / "freezes" / "01-experiment-plan" / "experiment_plan.tex").read_text(
        encoding="utf-8")
    assert "Version 5, frozen on 16 September 2026" in first
    assert "| [`01-experiment-plan/`](01-experiment-plan/) | 16 September 2026 |" in readme
    assert "| [`04-experiment-plan/`](04-experiment-plan/) | 18 September 2026 |" in readme
    assert "no measured run was read" in readme and "It becomes P3a" in readme
    started = collections.defaultdict(list)
    for pair in PAIRS:
        with open(REGISTRY / ("campaigns_%s.csv" % pair), newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                started[row["block"]].append(row["first_started_utc"])
    tests_a_prediction = [t for block, times in started.items() if block != "P0" for t in times]
    assert min(tests_a_prediction) > "2026-09-18T19"
    for said in ("Version 6 corrects what the first runs of version 5 found",
                 "Those runs found faults in the machines, in our code and in two of version 5's "
                 "own checks",
                 "Version 7 corrects the instrument that judges the delay",
                 "A message cannot arrive sooner than the client's own zero-delay trip",
                 "P1 is judged on the slices the pair can reach",
                 "D26-1} A5's session at 2 CPUs finishes its last thirteen runs with the got-it "
                 "brake recording rather than stopping",
                 "Version 9 splits P3 in two",
                 "Version 14 is the first written after a campaign was run and read",
                 "P3a is now judged where the ordinary plateau is at least 2\\%",
                 "D8-2 & The brake that stops a session when a run's ``got it'' median moves",
                 "Version 16 corrects one brake", "Version 17 corrects one brake",
                 "Version 18 widens one brake, after that brake stopped a campaign",
                 "Version 20 widens two brakes",
                 "Version 19 corrects a program",
                 "D21-2 & A prediction is judged on the runs the integrity rule passed",
                 "Version 30 corrects the programs that judge",
                 "Version 24 gives the Arm pair A3's Kafka campaign",
                 "D27-2 & A second bridge session on the stock kernel for each backend",
                 "D27-3 & A1 gains a slice of 3.75~ms",
                 "D27-4 & A third x86 A3 Kafka campaign",
                 "Version 28 adds A9", "Version 29 builds M0's recording",
                 "no setup has been read at $T - g$ before this version is public"):
        assert said in plan, said
    _has(part_v, "The plan was first frozen as version~5 on 16~September 2026, before its first run",
         "Versions 6 to~8 corrected what stage~0's first runs found in the machines, the code and "
         "the plan's own checks, before any campaign that tests a prediction began, and version~8 "
         "has P1 and P9 judged only on the slices a pair can reach",
         "P3 became P3a and P3b in version~9, before any load run was read",
         "Version~14 judges P3a only where the plateau reaches $2\\%$",
         "corrected or widened in versions 8, 16, 17, 18 and~20",
         "for L5's last runs in version~26 and for every campaign in version~32",
         "versions 19, 21 and~30 corrected faults in programs that had already judged",
         "the Arm pair's load campaign (version~24); a 3.75~ms slice for L1, second bridge days "
         "and a third x86 load campaign (version~27); L9 (version~28); and M0's recording "
         "(version~29)",
         "P6 was given its program in version~30, at a margin no run had been read against")


def test_the_brake_as_it_ended(part_v):
    import delay_calibration
    import run_integrity
    plan = PLAN.read_text(encoding="utf-8")
    assert "The floor under the got-it brake's allowance goes from 0.10~ms to 0.25~ms" in plan
    assert (run_integrity.GOTIT_FLOOR_MS, run_integrity.GOTIT_NOISE_SHARE,
            delay_calibration.GROSS_SHARE) == (0.25, 3.0, 0.25)
    _has(part_v, "which from version~20 holds a run against its setup's earlier runs in the "
         "campaign and allows the largest of a quarter of the added delay, three times the "
         "scatter pooled over the campaign's setups, and 0.25~ms")


def test_the_rounds_each_campaign_ran(part_v):
    plan = PLAN.read_text(encoding="utf-8")
    assert "A2's fifteen campaigns run at the floor of 4 rounds" in plan and "M0 runs 10" in plan
    starts = set(law_runs._false_starts(str(REGISTRY)))
    rounds = collections.defaultdict(int)
    for row in _registry():
        if row["round"] and (row["pair"], row["campaign"]) not in starts:
            key = (row["block"], row["pair"], row["campaign"])
            rounds[key] = max(rounds[key], int(row["round"]))
    by_block = collections.defaultdict(set)
    for (block, _, _), n in rounds.items():
        by_block[block].add(n)
    assert by_block["A2"] == by_block["A9"] == {4} and by_block["M0"] == {10}
    _has(part_v, "L2 and L9 ran at the floor of four", "M0 ran at a fixed ten")


def test_the_machines_and_their_kernels(part_v):
    rows = _registry()
    models = collections.Counter((r["pair"], r["cpu_model"]) for r in rows if r["cpu_model"])
    assert set(m for (p, m) in models if p != "arm") == {"AMD EPYC 9V74 80-Core Processor"}
    assert set(m for (p, m) in models if p == "arm") == {"CPU implementer 0x41, part 0xd49"}
    assert "Arm Neoverse N2" in (REGISTRY / "README.md").read_text(encoding="utf-8")
    kernels = collections.Counter((r["pair"], r["kernel"]) for r in rows)
    assert kernels[("matched", "6.8.0-1064-azure")] == 65
    first = sorted(re.search(r"_(\d{8}T\d{6}Z)_r", r["run"]).group(1) for r in rows
                   if r["pair"] == "matched" and r["kernel"] == "6.8.0-1064-azure")
    later = sorted(re.search(r"_(\d{8}T\d{6}Z)_r", r["run"]).group(1) for r in rows
                   if r["pair"] == "matched" and r["kernel"] == "6.8.0-1065-azure")
    assert first[-1] < later[0], "the 1064 runs came first"
    builds = set(k for (p, k) in kernels if k.startswith("6.8.12-sbl"))
    assert builds == {"6.8.12-sbl1000", "6.8.12-sbl250", "6.8.12-sbl100"}
    assert set(p for (p, k) in kernels if k.startswith("6.8.12-sbl")) == {"matched", "matched-b"}
    assert set(k for (p, k) in kernels if p in ("matched-b", "arm") and k
               and not k.startswith("6.8.12")) == {"6.8.0-1064-azure"}
    _has(part_v, "6.8.0-1065 on the first x86 pair after its first 65 runs on 6.8.0-1064",
         "both x86 drivers also ran three kernels built from one source tree")
    unread = [r for r in rows if not r["kernel"]]
    assert len(unread) == 6 and all(r["verdict"] == "" for r in unread)
    _has(part_v, "six that ended before the integrity rule could judge them have no reading")
    sizes = set((r["pair"] == "arm", r["driver_size"], r["broker_size"]) for r in rows)
    assert sizes == {(False, "Standard_D8as_v6", "Standard_D2as_v6"),
                     (True, "Standard_D8ps_v6", "Standard_D2ps_v6")}
    testbed = _json(REPO / "cloud" / "azure" / "testbed.json")
    assert testbed["location"] == "swedencentral" and "All three pairs" in testbed["location_note"]
    _has(part_v, "each a driver with eight virtual CPUs and a broker with two, all in one region")


def test_the_deliveries_no_delay_can_reach_were_not_run(part_v):
    """Where a design point is missing, it is the shortest ones: below the client's own trip."""
    design = (REPO / "scripts" / "law_design.py").read_text(encoding="utf-8")
    assert "A point the placement cannot reach (below the zero-delay trip," in _flat(design)
    eight = ("p05s", "p09s", "c02h", "c04h", "c06h", "c08h", "f15h", "f2sh")
    starts = set(law_runs._false_starts(str(REGISTRY)))
    points = collections.defaultdict(set)
    for row in _registry():
        # A run with no reading of its kernel has no tick to place it by (S34).
        if row["block"] in ("A1", "A2", "A4", "A5", "A9") and row["kernel"] and \
                (row["pair"], row["campaign"]) not in starts:
            points[(row["block"], row["pair"], row["backend"], row["slice_set_ns"],
                    row["tick_ms"], row["cpus"])].add(row["point"])
    short = 0
    for cell, ran in points.items():
        assert ran <= set(eight), cell
        missing = [p for p in eight if p not in ran]
        assert missing == list(eight[:len(missing)]), (cell, missing)
        short += bool(missing)
    assert short > 0
    _has(part_v, "An end-to-end latency shorter than the client's own with nothing added "
         "cannot be set, and "
         "was not run")


def test_what_ran(part_v):
    quality = _quality()
    total = collections.Counter()
    for row in quality:
        for key in ("runs", "count", "repeat", "stop", "not_yet_judged", "runs_with_stalls"):
            total[key] += int(row[key])
    rows = _registry()
    assert len(rows) == 8108 and len(quality) == 156
    testing = collections.Counter(row["block"] for row in quality
                                  if row["block"] not in ("C0", "C0B", "B0", "P0", "SMOKE"))
    assert set(testing) == {"A1", "A2", "A3", "A4", "A5", "A7", "A8", "A9", "M0"}
    stamps = sorted(re.search(r"_(\d{8})T\d{6}Z", r["run"]).group(1) for r in rows
                    if re.search(r"_(\d{8})T\d{6}Z", r["run"]))
    finished = []
    for pair in PAIRS:
        with open(REGISTRY / ("campaigns_%s.csv" % pair), newline="", encoding="utf-8") as fh:
            finished += [row["last_finished_utc"] for row in csv.DictReader(fh)]
    assert stamps[0] == "20260916" and max(finished).startswith("2026-09-27")
    _has(part_v, "The registry holds %s runs, taken from 16 to 27 September 2026; %s lie in the %d "
         "campaigns the judging read, %d of them in the blocks that test predictions and %d "
         "calibrations, baselines, spread pilots and a smoke test, and the other six were set aside"
         % (_comma(8108), _comma(total["runs"]), len(quality), sum(testing.values()),
            len(quality) - sum(testing.values())),
         "Of the %s, %s counted, %d were repeated, %d stopped a campaign and %d ended before the "
         "rule could judge them" % (_comma(total["runs"]), _comma(total["count"]), total["repeat"],
                                    total["stop"], total["not_yet_judged"]))
    assert 8108 - total["runs"] == 6


def test_the_table_of_blocks(part_v):
    rows = collections.OrderedDict()
    merge = {"C0B": "C0", "B0": "B0, P0", "P0": "B0, P0", "SMOKE": "smoke test"}
    # The records name the law blocks A1 to A9; the supplement prints them L1 to L9 so that
    # none shares a name with Parts I to IV's E-labeled campaigns.
    merge.update(("A%d" % i, "L%d" % i) for i in range(1, 10))
    for row in _quality():
        block = merge.get(row["block"], row["block"])
        cells = rows.setdefault(block, collections.Counter())
        cells["campaigns"] += 1
        for key in ("runs", "count", "repeat", "stop", "not_yet_judged", "runs_with_stalls"):
            cells[key] += int(row[key])
    totals = collections.Counter()
    for block, cells in rows.items():
        totals.update(cells)
        text = "& %d & %s & %s & %d & %d & %d & %d\\\\" % (
            cells["campaigns"], _comma(cells["runs"]), _comma(cells["count"]), cells["repeat"],
            cells["stop"], cells["not_yet_judged"], cells["runs_with_stalls"])
        found = re.search(re.escape(block) + r" & [^&]*" + re.escape(text), part_v)
        assert found, (block, text)
    _has(part_v, "All & & %d & %s & %s & %d & %d & %d & %d\\\\" % (
        totals["campaigns"], _comma(totals["runs"]), _comma(totals["count"]), totals["repeat"],
        totals["stop"], totals["not_yet_judged"], totals["runs_with_stalls"]))


# --- S35 ------------------------------------------------------------------------------------------

def _summary(name, part=None, reading="free", view="all"):
    answer = _answer(name, view)
    by = answer["by_part"][part]["by_summary"] if part else answer["by_summary"]
    return by[reading]


def test_the_three_views_and_the_one_verdict_that_moves(part_v):
    flagged = _json(JUDGED / "views" / "unflagged.json")
    stopping = _json(JUDGED / "views" / "stopping.json")
    unpaused = _json(JUDGED / "views" / "unpaused.json")
    count = lambda view: sum(len(c["left_out"]) for c in view["campaigns"])
    assert (count(flagged), count(stopping), count(unpaused)) == (14, 1110, 222)
    _has(part_v, "without the 14 runs the stopping rule would have stopped, without all %s "
         "taken while "
         "it only recorded, and without the 222 a pause held" % _comma(1110))
    names = sorted(p.stem for p in (JUDGED / "all").glob("*.txt"))
    moved = [(view, n) for view in ("unflagged", "stopping", "unpaused") for n in names
             if _verdict(n, view) != _verdict(n)]
    assert moved == [("unpaused", "p3a_x86_1")]


def _verdict_cells(part_v, column=4):
    start = part_v.index("\\label{tab:lawverdicts}")
    body = part_v[part_v.index("\\midrule", start):part_v.index("\\bottomrule", start)]
    body = body[len("\\midrule"):].replace("\\tabularnewline", "\\\\")
    rows = [row.split("&") for row in body.split("\\\\") if row.strip()]
    return dict((cells[0].strip(), cells[column].replace("\\raggedright", "").strip())
                for cells in rows)


def test_the_one_verdict_that_moves_is_the_one_marked(part_v):
    moves = dict((row, cell) for row, cell in _verdict_cells(part_v, column=5).items()
                 if cell != "--")
    assert moves == {"P3a": "first x86, 19 Sep"}
    first = [row for row in _registry() if row["pair"] == "matched" and row["block"] == "A3"]
    folders = sorted(set(re.search(r"_(\d{8})T\d{6}Z_r", r["run"]).group(1) for r in first))
    assert folders[0] == "20260919"
    judged = (JUDGED / "all" / "p3a_x86_1.txt").read_text(encoding="utf-8")
    assert judged.startswith("campaigns/matched/a3_20260919T")
    assert not _answer("p3a_x86_1")["confirmed"] and _answer("p3a_x86_1", "unpaused")["confirmed"]


def test_the_verdict_column_is_the_frozen_answer(part_v):
    """Each verdict cell says what the frozen judge returned, broker by broker where they differ."""
    cells = _verdict_cells(part_v)
    both = lambda name: tuple(_answer(name + "_" + b)["confirmed"] for b in ("kafka", "redis"))
    parts = lambda name: tuple(_answer(name)["by_part"][b]["confirmed"]
                               for b in ("kafka", "redis"))
    campaigns = ("x86_1", "x86_2", "x86_3", "x86_3r", "arm")
    assert both("p2c_a2") == (False, True) and cells["P2c"] == "confirmed on \\redis{} only"
    for name, row in (("p4_a7", "P4"), ("p7_a5", "P7")):
        assert parts(name) == (True, False) and not _answer(name)["confirmed"]
        assert cells[row] == "confirmed on \\kafka{} only", row
    assert all(_answer("p3b_" + c)["confirmed"] for c in campaigns)
    assert cells["P3b"] == "confirmed on all five"
    assert not any(_answer("p3a_" + c)["confirmed"] for c in campaigns)
    assert cells["P3a"] == "not confirmed on any"
    nowhere = {"P1": ["p1_a1"], "P9": ["p9_a4"], "P2": ["p2_a2_kafka", "p2_a2_redis"],
               "P2b": ["p2b_a2_kafka", "p2b_a2_redis"], "P2d": ["p2d_a2_kafka", "p2d_a2_redis"],
               "P6": ["p6_a6"], "P8": ["p8_a8_x86", "p8_a8_arm", "p8_a8_arm_182140Z"]}
    for row, names in nowhere.items():
        assert not any(_answer(n)["confirmed"] for n in names), row
        assert cells[row] == "not confirmed", row
    a9 = _answer("a9")
    assert not a9["a9_1_holds"] and not a9["confirmed"] and not a9["a9_2b_confirmed"]
    assert cells["L9-1"] == cells["L9-2"] == cells["L9-2b"] == "not confirmed"
    assert cells["M0"] == "--" and "confirmed" not in _answer("m0")
    held_everywhere = [row for row, cell in cells.items() if cell.startswith("confirmed on all")]
    held_once = [row for row, cell in cells.items() if cell.endswith("only")]
    assert (held_everywhere, held_once) == (["P3b"], ["P2c", "P4", "P7"])
    _has(part_v, "\\caption{\\textbf{One prediction confirmed on every campaign, three on one "
         "broker, and the rest not.}")


def test_the_slice_rows_and_paragraph(part_v):
    for name, part, label in (("p1_a1", "kafka", "\\kafka{}"), ("p1_a1", "redis", "\\redis{}"),
                              ("p9_a4", "kafka", "\\kafka{}"), ("p9_a4", "redis", "\\redis{}")):
        free, fitted = _summary(name, part), _summary(name, part, "fitted")
        _has(part_v, "%s $%s$ ($%s$--$%s$) and $%s$" % (
            label, _f(free["value"], 3), _f(free["interval"][0], 3),
            _f(free["interval"][1], 3), _f(fitted["value"], 3)))
    band = lambda part, reading: _summary("p1_a1", part, reading)["in_band"]
    assert (sum(band("kafka", "free").values()), len(band("kafka", "free"))) == (4, 4)
    assert (sum(band("redis", "free").values()), len(band("redis", "free"))) == (5, 5)
    assert sum(band("kafka", "fitted").values()) == 2 and sum(band("redis", "fitted").values()) == 2
    _has(part_v, "four for \\kafka{} and five for \\redis{}; on the fitted shape it did at two of "
         "the four and two of the five")
    for part in ("kafka", "redis"):
        assert _summary("p9_a4", part)["confirmed"] and not _summary("p9_a4", part,
                                                                     "fitted")["confirmed"]


def test_the_tick_rows_and_paragraph(part_v):
    for name, label in (("p2_a2", "ratio, free and fitted:"), ("p2b_a2", "")):
        k = [_summary(name + "_kafka", reading=r)["value"] for r in ("free", "fitted")]
        r = [_summary(name + "_redis", reading=x)["value"] for x in ("free", "fitted")]
        _has(part_v, "%s \\kafka{} $%s$ and $%s$; \\redis{} $%s$ and $%s$" % (
            label, _f(k[0], 3), _f(k[1], 3), _f(r[0], 3), _f(r[1], 3)))
    for backend, label in (("kafka", "\\kafka{}"), ("redis", "\\redis{}")):
        fitted = _summary("p2c_a2_" + backend, reading="fitted")
        _has(part_v, "%s $%s$ ($%s$--$%s$)" % (label, _f(fitted["value"], 3),
                                                _f(fitted["interval"][0], 3),
                                                _f(fitted["interval"][1], 3)))
    assert _answer("p2c_a2_redis")["confirmed"] and not _answer("p2c_a2_kafka")["confirmed"]
    within = [v for b in ("kafka", "redis")
              for v in _summary("p2d_a2_" + b, reading="fitted")["within"].values()]
    assert (sum(within), len(within)) == (1, 12)
    _has(part_v, "within it at one of twelve slice and tick pairs",
         "held at one of the twelve slice and tick pairs")
    starts = _summary("p2d_a2_redis", reading="fitted")["start_ms"]
    before = [3.0 - starts[k] for k in ("[1.0, 3.0]", "[4.0, 3.0]", "[10.0, 3.0]")]
    _has(part_v, "\\redis{}'s fitted starts sit $%s$ to $%s$~ms before the slice at every tick"
         % (_f(min(before), 1), _f(max(before), 1)))
    kafka = _summary("p2d_a2_kafka", reading="fitted")["start_ms"]
    assert all(kafka[k] > 1.5 for k in ("[1.0, 1.5]", "[4.0, 1.5]", "[10.0, 1.5]"))


def test_the_load_rows_and_paragraph(part_v):
    campaigns = ("x86_1", "x86_2", "x86_3", "x86_3r", "arm")
    moves = [_summary("p3a_" + c)["value"] for c in campaigns]
    rises = [_summary("p3b_" + c)["value"] for c in campaigns]
    _has(part_v, "free move: " + ", ".join("$%s$" % _f(m, 3) for m in moves[:-1])
         + " and $%s$~ms" % _f(moves[-1], 3))
    first = _summary("p3b_x86_1")
    _has(part_v, "rise, free: $%s$ ($%s$--$%s$), %s" % (
        _f(first["value"], 3), _f(first["interval"][0], 3), _f(first["interval"][1], 3),
        ", ".join("$%s$" % _f(r, 3) for r in rises[1:-1]) + " and $%s$" % _f(rises[-1], 3)))
    assert all(_answer("p3b_" + c)["confirmed"] for c in campaigns)
    assert not any(_answer("p3a_" + c)["confirmed"] for c in campaigns)
    assert all(m < 0 for m in moves)
    _has(part_v, "by $%s$ to $%s$, every interval above zero" % (_f(min(rises), 3),
                                                                 _f(max(rises), 3)),
         "$%s$ to $%s$~ms on the free reading" % (_f(max(moves), 3), _f(min(moves), 3)))
    low = [v for c in campaigns for v in _answer("p3a_" + c).get("loads_out_of_reach",
                                                                 {}).values()]
    _has(part_v, "at $50\\%%$ the plateau, $%s$ to $%s\\%%$" % (_f(100 * min(low), 2),
                                                               _f(100 * max(low), 2)))
    for c in campaigns:
        free, fitted = _summary("p3a_" + c), _summary("p3a_" + c, reading="fitted")
        assert any(i[0] < -0.25 or i[1] > 0.25 for i in (free["interval"], fitted["interval"]))
    one = _summary("p3a_x86_1")["interval"]
    assert -0.25 <= one[0] and one[1] <= 0.25, "the first x86 campaign's free reading is inside"
    _has(part_v, "in the first x86 campaign only the fitted one did, by $%s$~ms"
         % _f(-0.25 - _summary("p3a_x86_1", reading="fitted")["interval"][0], 4))


def test_priority_and_the_core_count(part_v):
    plateaus = _json(STRANGE / "cliff_summary.json")["plateaus"]["A7"]
    _has(part_v, "\\kafka{} $%s$ to zero; \\redis{}'s plateau $%s$" % (
        _f(plateaus["kafka"]["ordinary"], 4), _f(plateaus["redis"]["ordinary"], 4)),
         "took the plateau from $%s$ to zero in every run" % _f(plateaus["kafka"]["ordinary"], 4))
    assert plateaus["kafka"]["go_first"] == 0.0
    p7 = _answer("p7_a5")["by_part"]
    assert p7["kafka"]["read_back"] == {"2": True, "4": True, "8": True} == \
        p7["redis"]["read_back"]
    assert p7["kafka"]["confirmed"] and p7["kafka"]["out_of_reach"] == ["2", "4"]
    assert not p7["redis"]["by_summary"]["fitted"]["confirmed"]
    band = lambda reading: p7["redis"]["by_summary"][reading]["in_band"]
    assert band("free") == {"2": True, "4": True, "8": True}
    assert band("fitted") == {"2": False, "4": False, "8": False}
    _has(part_v, "on \\redis{} the free reading placed the fall inside its band at all three core "
         "counts and the fitted shape at none, so P7 is confirmed on \\kafka{} only")
    plan = PLAN.read_text(encoding="utf-8")
    assert "1.4, 2.1 and 2.8~ms at 2, 4 and 8 cores" in plan
    _has(part_v, "$1.4$, $2.1$ and $2.8$~ms")


def test_the_clients(part_v):
    x86, arm = _summary("p8_a8_x86", reading="fitted"), _summary("p8_a8_arm", reading="fitted")
    _has(part_v, "Python over Java: $%s$ ($%s$--$%s$), and $%s$ ($%s$--$%s$) on Arm" % (
        _f(x86["value"], 3), _f(x86["interval"][0], 3), _f(x86["interval"][1], 3),
        _f(arm["value"], 3), _f(arm["interval"][0], 3), _f(arm["interval"][1], 3)))
    assert x86["java_cliff"] == arm["java_cliff"] == 1.0 and x86["draws"] == 2000
    _has(part_v, "in all 2,000 resampled rounds on both pairs, and priority cut its plateau "
         "%s times on the x86 pair and %d times on Arm" % (
             _comma(round(x86["java_priority_cut"])), round(arm["java_priority_cut"])),
         "$%s$ times Java's on the x86 pair and $%s$ times on Arm" % (
             _f(x86["value"], 2), _f(arm["value"], 2)))


def test_the_recordings(part_v):
    p6 = _answer("p6_a6")["by_part"]
    ratios = [p["median_ratio"] for p in p6.values()]
    assert len(p6) == 4 and all(p["within_band"] == 0 for p in p6.values())
    _has(part_v, "median ratio $%s$ to $%s$ over four pair and broker parts; no setup inside"
         % (_f(min(ratios), 2), _f(max(ratios), 2)),
         "over-predicted the rate $%s$ to $%s$ times" % (_f(min(ratios), 2), _f(max(ratios), 2)))
    a9 = _answer("a9")["by_part"]
    shares = [100.0 * load["a9_1"]["mostly_waiting"] / load["a9_1"]["negative_readings"]
              for part in a9.values() for load in part["loads"].values()]
    _has(part_v, "$%s$ to $%s\\%%$" % (_f(min(shares), 1), _f(max(shares), 1)))
    a9_2 = [part["median_ratio"] for part in a9.values()]
    _has(part_v, "median ratio $%s$ to $%s$" % (_f(min(a9_2), 3), _f(max(a9_2), 3)))
    assert 6 <= 1 / max(a9_2) and 1 / min(a9_2) <= 10
    met = [part for part in a9.values() if part["a9_2b"]["confirmed"]]
    medians = [part["a9_2b"]["median_ratio"] for part in a9.values()]
    assert len(met) == 4
    _has(part_v, "inside the rule on four of six parts; median ratio $%s$ to $%s$"
         % (_f(min(medians), 2), _f(max(medians), 2)))


def test_bursts(part_v):
    m0 = _answer("m0")["parts"]
    slopes = [m0[p]["departure"]["slope"] for p in ("kafka", "redis ack 1", "redis ack 200")]
    _has(part_v, "\\kafka{} $%s$; \\redis{} $%s$ and $%s$" % tuple(_f(s, 3) for s in slopes),
         "at a slope of $%s$; \\redis{}'s grew at $%s$ with one acknowledgment per message and at "
         "$%s$ in batches of 200" % tuple(_f(s, 3) for s in slopes))
    for part in ("redis ack 1", "redis ack 200"):
        hypotheses = m0[part]
        assert not any(hypotheses[h]["kept"] for h in ("M-H1", "M-H2", "M-H3", "M-H4"))
        assert hypotheses["M-H2"]["replayed_slope"] == pytest.approx(1.0, abs=0.01)
        assert hypotheses["M-H3"]["contribution_ms"] < 0.01
        assert hypotheses["M-H4"]["contribution_ms"] < 0.01
        shift = hypotheses["M-H1"]["arrival_shift_ms"]
        assert shift["8"] == pytest.approx(8.0, abs=0.05)
    _has(part_v, "added less than 0.01~ms")


# --- S36 ------------------------------------------------------------------------------------------

def test_the_table_of_marks(part_v, runs):
    counts = law_runs.counts(runs)
    for mark in law_runs.MARK_KEYS:
        cells = counts[mark]
        row = re.search(re.escape(mark) + r" & [^&]*& %d & %d & %d & " % (
            cells["matched"], cells["matched-b"], cells["arm"]), part_v)
        assert row, (mark, cells)
    _has(part_v, "of the registry's %s" % _comma(len(runs)))


def test_why_runs_were_out_of_every_judge(part_v, runs):
    counts = law_runs.counts(runs)
    total = lambda mark: sum(counts[mark].values())
    assert (total("void"), total("false start"), total("repeated"), total("stopped")) == \
        (6, 18, 76, 16)
    starts = set((r["pair"], r["folder"]) for r in runs if "false start" in r["marks"])
    assert len(starts) == 6
    _has(part_v, "Six runs are void", "Eighteen runs belong to six false starts",
         "The integrity rule repeated 76 runs",
         "16 runs stopped their campaigns on the stopping rule")
    reasons = collections.Counter()
    for run in runs:
        if "repeated" in run["marks"]:
            first = run["reasons"].split(";")[0]
            reasons["load" if "measured load" in first else
                    "files" if "could not be read" in first else
                    "rate" if "messages were sent at" in first else
                    "calibration" if "no zero-delay got-it median" in first else
                    "ping" if first.startswith("ping measured") and "void" in run["marks"] else
                    "unexplained"] += 1
    assert (reasons["rate"], reasons["calibration"], reasons["ping"], reasons["unexplained"]) == \
        (1, 3, 2, 0)
    assert "Version 7 corrects the instrument that judges the delay" in \
        PLAN.read_text(encoding="utf-8")
    _has(part_v, "the load off its target in %d, the run's files unreadable in %d, and another "
         "check in six: the publish rate once, the calibration in three and, in two void runs, a ping "
         "reading version~7 stopped judging" % (reasons["load"], reasons["files"]))
    stops = [r for r in runs if "stopped" in r["marks"]]
    assert all("got-it median moved" in r["reasons"] for r in stops)
    assert not any("before it was sent" in r["reasons"] for r in runs)
    arm_loads = set(re.findall(r"measured load was ([\d.]+)%", " ".join(
        r["reasons"] for r in runs if r["pair"] == "arm" and "false start" in r["marks"])))
    assert {"99.7", "99.8"} <= arm_loads
    _has(part_v, "$99.7$ to $99.8\\%$ against $75\\%$")


def test_each_false_start_and_its_cause(part_v, runs):
    """The six false starts, each with the cause the issues register gives it."""
    campaigns = {}
    for pair in PAIRS:
        with open(REGISTRY / ("campaigns_%s.csv" % pair), newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                campaigns[row["campaign"]] = dict(row, pair=pair)
    starts = sorted(c for c, row in campaigns.items() if row["complete"] != "True")
    assert starts == ["a2_20260921T140723Z", "a3_20260921T030021Z", "a4_20260918T211544Z",
                      "a4_20260918T211825Z", "a8_20260920T222915Z", "a8_20260921T025558Z"]
    stamp = lambda text: datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    gap = lambda a, b: (stamp(campaigns[b]["first_started_utc"])
                        - stamp(campaigns[a]["first_started_utc"])).total_seconds()
    assert round(gap("a4_20260918T211544Z", "a4_20260918T211825Z") / 60) == 3
    assert gap("a8_20260921T025558Z", "a8_20260921T025629Z") == 30
    assert campaigns["a8_20260921T025629Z"]["complete"] == "True"
    of = lambda name: [r for r in runs if r["run"].startswith("law_%s_" % name)]
    both = [r for name in ("a4_20260918T211544Z", "a4_20260918T211825Z", "a8_20260921T025558Z")
            for r in of(name) if r["verdict"] == "repeat"]
    twin = [r for r in of("a8_20260921T025629Z") if r["verdict"] == "repeat"
            and "measured load" in r["reasons"]]
    assert len(twin) == 2
    loads = set(re.search(r"measured load was ([\d.]+)% against 75%", r["reasons"]).group(1)
                for r in both + twin)
    assert loads == {"99.7", "99.8"}
    assert all("no zero-delay got-it median" in r["reasons"]
               for r in of("a8_20260920T222915Z"))
    over = [float(a) - float(b) for r in of("a3_20260921T030021Z")
            for a, b in re.findall(r"measured load was ([\d.]+)% against (\d+)%", r["reasons"])]
    assert len(over) == 3 == len(of("a3_20260921T030021Z"))
    by_hand, after = campaigns["a2_20260921T140723Z"], campaigns["a2_20260921T141744Z"]
    assert by_hand["ended"] == "stopped by hand" and by_hand["done"] == "2"
    assert (after["kernel"], after["complete"]) == (by_hand["kernel"], "True")
    assert round((stamp(after["first_started_utc"])
                  - stamp(by_hand["last_finished_utc"])).total_seconds() / 60) == 5
    register = (LAW / "issues-register.md").read_text(encoding="utf-8")
    for said in ("were started three minutes apart and ran at once",
                 "was started 30 seconds before", "no zero-delay got-it median for Kafka at 75%",
                 "was stopped by hand after 2 runs"):
        assert said in register, said
    _has(part_v, "two L4s started three minutes apart on 18~September, and an L8 started 30~s "
         "before its twin on 21~September",
         "Every run of theirs judged while both ran measured a load of $99.7$ to $99.8\\%$ against "
         "$75\\%$", "its two runs from those minutes were repeated",
         "an L8 on the Arm pair was placed from a calibration with no zero-delay median "
         "publish latency",
         "measured its load $%s$ to $%s$ points above target in each of its three runs"
         % (_f(min(over), 1), _f(max(over), 1)),
         "stopped by hand after two counted runs and followed five minutes later by a session on "
         "the same kernel that ran whole")


def test_what_the_plan_does_with_the_unexpected(part_v):
    plan = PLAN.read_text(encoding="utf-8")
    assert "A run whose conditions held but that gives a surprising number is a result, never a " \
           "re-run" in plan
    assert "it is logged with the reasons and re-queued" in plan
    _has(part_v, "a run whose conditions held is a result, never a re-run, and that a run which "
         "fails is logged with its reasons and kept")


def test_what_was_counted_with_a_warning(part_v, runs):
    counts = law_runs.counts(runs)
    assert counts["paused"] == {"matched": 112, "matched-b": 109, "arm": 1}
    _has(part_v, "In 222 runs, 112 and 109 of them on the two x86 pairs and one on Arm",
         "A further %d runs lie far from their setup's other repeats" % sum(counts["far"].values()),
         "Fourteen runs taken while the stopping rule only recorded would have stopped it")
    effect = _json(STRANGE / "a9_summary.json")["a9"]
    kafka = [p["recorded_over_unrecorded"] for k, p in effect.items() if k.endswith("kafka")]
    redis = [p["recorded_over_unrecorded"] for k, p in effect.items() if k.endswith("redis")]
    _has(part_v, "$%s$ to $%s$ times for \\kafka{} and $%s$ to $%s$ times for \\redis{}" % (
        _f(min(kafka), 2), _f(max(kafka), 2), _f(min(redis), 2), _f(max(redis), 2)))
    fitted = lambda view: float(re.search(
        r"fitted shape: .*95% interval (-?[\d.]+) to",
        (JUDGED / view / "p3a_x86_1.txt").read_text(encoding="utf-8")).group(1))
    _has(part_v, "ends $%s$~ms outside its bar with them and $%s$~ms inside without them" % (
        _f(-0.25 - fitted("all"), 4), _f(fitted("unpaused") + 0.25, 4)))
    pauses = _json(STRANGE / "pause_summary.json")
    assert pauses["together"]["within"] == {"matched & matched-b": 0}
    assert pauses["hour"]["rayleigh_p"] < 0.05 < pauses["hour_since_boot"]["rayleigh_p"]


def test_the_extreme_that_is_not_an_aberration(part_v, runs):
    run = max((r for r in runs if r["block"] == "A5" and r["rate"] is not None
               and not r["marks"]), key=lambda r: r["rate"])
    assert run["backend"] == "redis" and run["cpus"] == 4.0
    assert run["trip_median_ms"] < run["gotit_median_ms"]
    _has(part_v, "with a rate of $%s$, had an end-to-end latency of $%s$~ms and a publish "
         "latency of $%s$~ms"
         % (_f(run["rate"], 3), _f(run["trip_median_ms"], 3), _f(run["gotit_median_ms"], 3)))


def test_the_figures_are_there_and_drawn_from_every_run(part_v, runs):
    import make_law_figures
    for stem in make_law_figures.FIGURES:
        assert "docs/results/figures/%s.pdf" % stem in part_v
        assert (REPO / "docs" / "results" / "figures" / (stem + ".pdf")).exists()
    drawn = set()
    for spec in make_law_figures.FIGURES.values():
        for panel in spec["panels"]:
            drawn |= set((r["pair"], r["run"]) for r in make_law_figures.select(runs, panel))
    law = [r for r in runs if r["block"] in law_runs.LAW_BLOCKS]
    drawable = [r for r in law if r["trip_median_ms"] is not None and r["rate"] is not None]
    assert drawn == set((r["pair"], r["run"]) for r in drawable), "a run left out of every panel"
    _has(part_v, "every run of the law's blocks that measured an end-to-end latency and a "
         "rate, %s of their "
         "%s, is drawn" % (_comma(len(drawable)), _comma(len(law))))
    replicate = [r for r in runs if r["block"] == "A2" and r["pair"] == "matched-b"
                 and r["backend"] == "kafka"]
    assert set(r["tick_ms"] for r in replicate if r["tick_ms"]) == {1.0}
    plan = PLAN.read_text(encoding="utf-8")
    assert "becomes a replicate of that cell on a second" in plan, "D21-1"


# --- S37 ------------------------------------------------------------------------------------------

def test_the_bursts_read_after_the_verdicts(part_v):
    with open(STRANGE / "m0_by_rank.csv", newline="", encoding="utf-8") as fh:
        ranks = list(csv.DictReader(fh))
    zero = [r for r in ranks if float(r["delay_ms"]) == 0.0 and r["part"] == "kafka"]
    followers = sum(int(r["messages"]) for r in zero if r["rank"] != "0")
    total = sum(int(r["messages"]) for r in zero)
    _has(part_v, "$%d\\%%$ of messages arrive right behind another" % round(100.0 * followers
                                                                          / total))

    def growth(part, rank):
        return float(next(r for r in ranks if r["part"] == part and float(r["delay_ms"]) == 8.0
                          and int(r["rank"]) == rank)["growth_per_ms"])
    _has(part_v, "the followers grew $%s$ times in batches and $%s$, $%s$, $%s$ and $%s$ times one "
         "at a time" % ((_f(growth("redis ack 200", 1), 2),)
                        + tuple(_f(growth("redis ack 1", r), 2) for r in range(1, 5))))
    bursts = _json(STRANGE / "m0_bursts.json")
    parts = ("kafka", "redis ack 1", "redis ack 200")
    _has(part_v, "$%s$, $%s$ and $%s$ against the measured $%s$, $%s$ and $%s$ over all %d runs "
         "of each" % (tuple(_f(bursts[p]["slope"]["predicted"], 3) for p in parts)
                      + tuple(_f(bursts[p]["slope"]["all"], 3) for p in parts)
                      + (bursts["kafka"]["runs"],)))
    assert all(bursts[p]["runs"] == 30 for p in parts)
    judged = _answer("m0")["parts"]
    for p in parts:
        assert _f(judged[p]["departure"]["slope"], 3) == _f(bursts[p]["slope"]["recorded"], 3)
    for p in ("redis ack 1", "redis ack 200"):
        assert bursts[p]["slope"]["recorded"] > bursts[p]["slope"]["unrecorded"] + 0.05
    assert abs(bursts["kafka"]["slope"]["recorded"] - bursts["kafka"]["slope"]["unrecorded"]) < 0.01
    _has(part_v, "The slopes of S35 are the traced half's, the runs M0's reading is held to, and the "
         "recording raised \\redis{}'s",
         "on the traced half of the runs as M0's reading asks",
         "slope on the added delay, traced half: \\kafka{} $%s$"
         % _f(judged["kafka"]["departure"]["slope"], 3))
    plan = PLAN.read_text(encoding="utf-8")
    assert "the slope of the recorded runs' median trip on the delay each run's broker held" in plan


def test_why_p6_over_predicts(part_v):
    summary = _json(STRANGE / "a9_summary.json")
    a6 = summary["a6"]
    wake = [summary["a9"][part]["wake_waits"] for part in a6]
    held = [round(p["waits"]) for p in a6.values()]
    assert len(a6) == 4
    _has(part_v, "holds $%s$ to $%s$ waits a run" % tuple(
        _comma(v).replace(",", "{,}") for v in (min(held), max(held))),
         "begun by a wake-up alone, $%s$ to $%s$, over the same four pair and broker parts" % tuple(
             _comma(round(v)).replace(",", "{,}") for v in (min(wake), max(wake))))


def test_what_stays_open(part_v):
    _has(part_v, "\\kafka{}'s free slope on the slice, $%s$" % _f(_summary("p1_a1", "kafka")
                                                                    ["value"], 3))


def test_nothing_here_is_a_verdict_and_the_vocabulary_holds(part_v):
    _has(part_v, "none of it changes one", "is the one reported")
    for word in (r"\bstamps?\b", r"\bstamper", r"\binstrument\b", r"\bflight\b"):
        assert not re.search(word, part_v), word


def test_no_law_block_shares_a_name_with_an_earlier_campaign():
    """An outside editor's reading, 28 Sep: E-A5 in Part II was a priority manipulation and A5
    in Part V a core-count block; E-A9 the run-queue trace and A9 the per-acknowledgment wait
    recording. The law campaign's blocks print as L1 to L9 wherever the supplement reports
    them, and the plan's own names appear only where the two are mapped."""
    import make_law_figures
    text = (REPO / "postmortem.tex").read_text(encoding="utf-8")
    spans = [(text.index(r"\subsection{S16.10."),
              text.index(r"\section{", text.index(r"\subsection{S16.11."))),
             (text.index(r"\section*{Part V."), text.index(r"\bibliographystyle"))]
    prose = "\n".join(l for s, e in spans for l in text[s:e].split("\n")
                      if not l.lstrip().startswith("%"))
    prose = _flat(prose)
    mapping = ("The plan names its blocks A1 to~A9 and the three wait predictions A9-1, A9-2 "
               "and A9-2b; they are written L1 to~L9 and L9-1, L9-2 and L9-2b here")
    assert mapping in prose and "(Part~V; A9 in its plan)" in prose
    rest = prose.replace(mapping, "").replace("(Part~V; A9 in its plan)", "")
    assert not re.findall(r"(?<![-\w\\])A[1-9](?:-\d|s)?b?(?!\w)", rest)
    earlier = text[:spans[0][0]] + text[spans[0][1]:spans[1][0]]
    assert not re.findall(r"(?<![-\w\\])L[1-9](?:-\d)?b?(?!\w)", _flat(earlier)), (
        "an L-label outside the law campaign's sections")
    titles = [p["title"] for spec in make_law_figures.FIGURES.values() for p in spec["panels"]]
    assert titles and all(re.match(r"\([a-g]\) L[1-9], ", t) for t in titles)
