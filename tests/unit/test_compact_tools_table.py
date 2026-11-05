"""The paper's compact Table III and Supplement S5's per-tool table say the same thing.

3 Nov 2026, the author's page decision of that day: the per-tool rows of the paper's Table III
moved, word for word, to S5 (stab:toolrows), and the paper keeps one row per group of tools with
each outcome's count, the counts of the marked cuts and the count of tools whose latency moves in
whole milliseconds. Every number of the compact table is a count of S5's rows, so this test counts
those rows and checks every cell, and checks S5's own group headings against its rows too.

3 Nov 2026: moved to Supplement S5 by the author's decision, so that the paper fits the journal's
12 free pages. The compact table is S5's own now (stab:toolgroups), beside the per-tool table whose
rows it counts; the paper states its point in words. The checks read it there.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: A phrase only that row's first cell holds -> how many tools the row holds.
TOOLS_IN_ROW = {
    "Apache Pulsar's performance client": 1, "rdkafka": 1, "OpenMessaging Benchmark": 1,
    "RabbitMQ Stream PerfTest": 1, "Yahoo Streaming Benchmark": 1, "Artemis": 1,
    "emqtt-bench": 1, "Pub/Sub": 1, "Trogdor": 1, "Quiver": 1, "kgo-repeater": 2,
    "PerfKit Benchmarker": 1, "Storage Benchmark Kit": 1, "Strimzi Canary": 1,
    "NATS command-line latency test": 1, "Pravega benchmark": 1, "end-to-end tool": 1,
    "RabbitMQ PerfTest": 1, "Xinfra Monitor": 1, "BookKeeper": 1, "producer tool": 1,
    "Sarama": 2, "wrk2": 1, "\\texttt{hey}": 7,
}

#: How a row's third cell opens -> the outcome the compact table counts it under.
OUTCOMES = (
    (r"^(Dropped|A zero dropped)", "Dropped"),
    (r"^(Refused|An array index that throws|Printed as impossible)", "Refused"),
    (r"^(Replaced|An arrival before its acknowledgment replaced)", "Replaced"),
    (r"^(Kept|Every value kept)", "Kept"),
    (r"^(Never met|Cannot fall below zero)", "Never met"),
)
COLUMNS = ("Dropped", "Refused", "Replaced", "Kept", "Never met")
DAGGER, DDAGGER = "$^\\dagger$", "$^\\ddagger$"


def _outcome(cell):
    found = [name for pattern, name in OUTCOMES if re.match(pattern, cell)]
    assert len(found) == 1, "no single outcome for %r" % cell[:60]
    return found[0]


def _rows_by_group(journal):
    """For each group of S5's table: its heading and its rows, (first, step, outcome cell)."""
    body = journal[journal.index("\\label{stab:toolrows}"):]
    body = body[body.index("\\midrule"):body.index("\\end{tabular}")]
    groups = []
    for chunk in body.split("\\\\"):
        chunk = " ".join(re.sub(r"\\(?:mid|bottom)rule", "", chunk).split())
        if not chunk:
            continue
        if chunk.startswith("\\multicolumn"):
            groups.append((chunk, []))
            continue
        cells = [c.strip() for c in chunk.split("&")]
        groups[-1][1].append((cells[0], cells[1], cells[2]))
    return groups


def _tools(first):
    keys = [k for k in TOOLS_IN_ROW if k in first]
    assert len(keys) == 1, "row %r matches %s; give it one entry" % (first, keys)
    return TOOLS_IN_ROW[keys[0]]


def _counted(rows):
    """What the compact table should print for one group of rows."""
    out = {"Tools": 0, "Step": 0}
    for column in COLUMNS:
        out[column] = 0
        out[column + DAGGER] = 0
        out[column + DDAGGER] = 0
    for first, step, cell in rows:
        n = _tools(first)
        outcome = _outcome(cell)
        out["Tools"] += n
        out[outcome] += n
        for mark in (DAGGER, DDAGGER):
            if mark in cell:
                out[outcome + mark] += 1
        steps = [s.strip() for s in step.split(",")]
        steps = steps if len(steps) == n else steps * n
        out["Step"] += sum(1 for s in steps if s == "1~ms")
    return out


def _cell(text):
    """"5 (1$^\\dagger$, 1$^\\ddagger$)" -> (5, {dagger: 1, ddagger: 1})."""
    m = re.match(r"^(\d+)(?:\s*\((.*)\))?$", text.strip())
    assert m, "not a count: %r" % text
    marks = {}
    for part in (m.group(2) or "").split(","):
        part = part.strip()
        if not part:
            continue
        k = re.match(r"^(\d+)(\$\^\\(?:dagger|ddagger)\$)$", part)
        assert k, "not a marked count: %r" % part
        marks[k.group(2)] = int(k.group(1))
    return int(m.group(1)), marks


def _compact(journal):
    """The compact table's rows: title -> its seven numeric cells (S5's since 3 Nov 2026)."""
    body = journal[journal.index("\\label{stab:toolgroups}"):]
    body = body[body.index("\\midrule"):body.index("\\end{tabular}")]
    rows = {}
    for chunk in body.split("\\\\"):
        chunk = " ".join(re.sub(r"\\(?:mid|bottom)rule", "", chunk).split())
        if not chunk:
            continue
        cells = [c.strip() for c in chunk.split("&")]
        assert len(cells) == 8, "a compact row needs eight cells: %r" % chunk
        rows[cells[0]] = cells[1:]
    return rows


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def journal():
    return (REPO / "supplement.tex").read_text(encoding="utf-8")


def test_every_row_of_s5_is_counted_once(journal):
    firsts = [first for _, rows in _rows_by_group(journal) for first, _, _ in rows]
    used = sorted(k for first in firsts for k in TOOLS_IN_ROW if k in first)
    assert used == sorted(TOOLS_IN_ROW), "S5's rows and this test's map have drifted apart"


def test_s5s_group_headings_count_their_rows(journal):
    """The heading of each group, "13 tools; 5 drop, 1 refuses, ...", as both referees asked."""
    verbs = {"drop": "Dropped", "refuse": "Refused", "replace": "Replaced", "keep": "Kept",
             "never meet": "Never met"}
    for heading, rows in _rows_by_group(journal):
        counted = _counted(rows)
        m = re.search(r"(\d+) tools;(.*)\}", heading)
        assert m and int(m.group(1)) == counted["Tools"], heading
        for n, verb in re.findall(r"(\d+) (drops?|refuses?|replaces?|keeps?|never meet)",
                                  m.group(2)):
            column = verbs[re.sub(r"s$", "", verb) if verb != "never meet" else verb]
            assert int(n) == counted[column], (heading, verb)


def test_the_compact_table_counts_s5s_rows(journal):
    compact = _compact(journal)
    groups = _rows_by_group(journal)
    totals = {}
    for (heading, rows), (title, cells) in zip(groups, [(t, c) for t, c in compact.items()
                                                        if t != "All"]):
        assert title in heading, "the groups are in S5's order, titled word for word: %r" % title
        counted = _counted(rows)
        assert int(cells[0]) == counted["Tools"], title
        for column, cell in zip(COLUMNS, cells[1:6]):
            n, marks = _cell(cell)
            assert n == counted[column], (title, column)
            for mark in (DAGGER, DDAGGER):
                assert marks.get(mark, 0) == counted[column + mark], (title, column, mark)
        assert int(cells[6]) == counted["Step"], (title, "step")
        for key in ["Tools", "Step"] + list(COLUMNS):
            totals[key] = totals.get(key, 0) + counted[key]
    assert len(groups) == len(compact) - 1 == 4
    all_row = compact["All"]
    assert [int(c) for c in all_row] == [totals["Tools"]] + [totals[c] for c in COLUMNS] + [
        totals["Step"]]


def test_the_compact_table_names_no_tool(journal):
    """The author, 8 Oct 2026: a table names every tool, alphabetically, or none, and never the
    OpenMessaging Benchmark alone. The compact table names none (in S5 since 3 Nov 2026)."""
    body = journal[journal.index("\\label{stab:toolgroups}"):]
    body = body[:body.index("\\end{tabular}")]
    for first in TOOLS_IN_ROW:
        assert first not in body, first


def test_the_checks_would_catch_a_wrong_cell():
    assert _cell("5 (1$^\\dagger$, 1$^\\ddagger$)") == (5, {DAGGER: 1, DDAGGER: 1})
    assert _cell("0") == (0, {})
    with pytest.raises(AssertionError):
        _cell("five")
    with pytest.raises(AssertionError):
        _cell("2 (one)")
    with pytest.raises(AssertionError):
        _outcome("Something else")
    rows = [("\\texttt{hey}, more", "${\\le}0.1$~ms", "Cannot fall below zero"),
            ("\\texttt{kgo-repeater}; RocketMQ benchmark", "1~$\\mu$s, 1~ms", "Kept" + DAGGER)]
    counted = _counted(rows)
    assert (counted["Tools"], counted["Never met"], counted["Kept"], counted["Step"]) == (
        9, 7, 2, 1)
    assert counted["Kept" + DAGGER] == 1
