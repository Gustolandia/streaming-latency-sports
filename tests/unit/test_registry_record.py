"""The registry's README and the issues register's last section, read against the registry.

Written on 27 September 2026, when the three pairs came home and wrote their registries. Every
count the README's table gives and every count the register's account of how the programme ended
gives is recomputed here from the six CSVs, so a registry written again cannot leave the prose
behind it. The copies' own numbers (files and bytes brought home) live in each collection's
COLLECTED.json beside the runs, which stay on the author's machine, and are not read here.
"""
import collections
import csv
import re
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
REG = REPO / "docs" / "results" / "registry"
REGISTER = REPO / "docs" / "results" / "law" / "issues-register.md"
PAIRS = {"first x86": "matched", "second x86": "matched-b", "Arm": "arm"}
#: How the README names each kernel: our builds by their tick, a missing reading in words.
NAMES = {"6.8.12-sbl1000": "HZ=1000", "6.8.12-sbl250": "HZ=250", "6.8.12-sbl100": "HZ=100",
         "": "not read"}
#: The false starts the register names, by the timestamp their runs carry.
FALSE_STARTS = {"20260921T030021Z", "20260921T140723Z", "20260918T211544Z", "20260918T211825Z",
                "20260920T222915Z", "20260921T025558Z"}
#: The calibration opened by mistake on top of a running one (21 September), set aside as void.
VOID = {"20260921T185741Z"}
#: The run folders set aside on 16 September, when two calibrations wrote into one: no campaign.
COLLIDED = re.compile(r"^law_r001-C0-")


def _csv(name):
    with open(REG / name, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _readme():
    return (REG / "README.md").read_text(encoding="utf-8")


def _cells(pair):
    line = next(l for l in _readme().splitlines() if l.startswith("| %s |" % pair))
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _number(text):
    return int(text.replace(",", ""))


def test_each_pairs_row_is_its_registry():
    for pair, stem in PAIRS.items():
        runs, camps = _csv("runs_%s.csv" % stem), _csv("campaigns_%s.csv" % stem)
        _, files, sizes, _, kernels, n_runs, n_camps = _cells(pair)
        assert files == "`runs_%s.csv`, `campaigns_%s.csv`" % (stem, stem)
        assert {(r["driver_size"], r["broker_size"]) for r in runs} == {tuple(sizes.split(", "))}
        printed = dict(part.rsplit(": ", 1) for part in kernels.split("; "))
        counted = collections.Counter(NAMES.get(r["kernel"], r["kernel"]) for r in runs)
        assert {k: _number(v) for k, v in printed.items()} == dict(counted), pair
        assert _number(n_runs) == len(runs)
        assert n_camps == "%d, %d" % (len(camps), sum(c["complete"] == "True" for c in camps))


def test_the_processor_named_is_the_one_every_run_read():
    for pair, stem in PAIRS.items():
        named = _cells(pair)[3]
        read = {r["cpu_model"] for r in _csv("runs_%s.csv" % stem) if r["cpu_model"]}
        assert len(read) == 1, pair
        (model,) = read
        if model.startswith("CPU implementer"):
            assert model.split("CPU ", 1)[1] in named, "the Arm row must carry the part it read"
        else:
            assert model.startswith(named), pair


def _blank_kinds():
    kinds = collections.Counter()
    no_kernel = collections.Counter()
    for stem in PAIRS.values():
        rows = _csv("runs_%s.csv" % stem)
        for r in rows:
            if r["verdict"]:
                continue
            stamp = re.search(r"_(\d{8}T\d{6}Z)_", r["run"]).group(1)
            prefix = r["run"].split("_%s_" % stamp)[0]
            base = r["run"].rsplit("-a", 1)[0]
            if any(x["run"].startswith(base + "-a") and x["run"] != r["run"]
                   and x["verdict"] == "count" for x in rows):
                kind = "put back"
            elif stamp in FALSE_STARTS:
                kind = "false start"
            elif stamp in VOID:
                kind = "void"
            elif any(x["run"].startswith("%s_%s_" % (prefix, stamp)) and x["verdict"] == "count"
                     for x in rows):
                kind = "kept the rest"
            else:
                kind = "calibration again"
            kinds[kind] += 1
            if not r["kernel"]:
                no_kernel[kind] += 1
    return kinds, no_kernel


def test_the_blank_verdicts_are_accounted_for():
    kinds, no_kernel = _blank_kinds()
    text = " ".join(_readme().split())
    assert "Of the seventeen," in text and sum(kinds.values()) == 17
    assert "seven were put back and counted on their next attempt" in text
    assert "one is the first run of a false start" in text
    assert ("one is the only run of a calibration opened by mistake on top of a running one, "
            "void and set aside") in text
    assert "seven are the runs of calibrations that stopped and were run again whole" in text
    assert "one ended a round of a calibration that kept its other 22 runs" in text
    assert dict(kinds) == {"put back": 7, "false start": 1, "void": 1, "calibration again": 7,
                           "kept the rest": 1}
    assert "The six runs with no kernel reading are among them" in text
    assert dict(no_kernel) == {"put back": 3, "calibration again": 3}


def test_the_void_folders_are_the_ones_named():
    """Five collided on the second x86 pair and one duplicate on the first; none has a campaign."""
    collided = [r for r in _csv("runs_matched-b.csv") if COLLIDED.match(r["run"])]
    assert len(collided) == 5 and all(not r["campaign"] for r in collided)
    void = [r for r in _csv("runs_matched.csv") if any(s in r["run"] for s in VOID)]
    assert len(void) == 1 and not void[0]["verdict"]
    text = " ".join(_readme().split())
    assert ("five on the second x86 pair (16 September, when two calibrations wrote into one "
            "folder) and that one run on the first (21 September)") in text


def test_the_register_counts_what_the_registry_holds():
    section = REGISTER.read_text(encoding="utf-8")
    section = section[section.index("## How the programme ended"):]
    section = " ".join(section[:section.index("\n## ", 5)].split())
    total = complete = runs = 0
    parts = []
    for pair, stem in PAIRS.items():
        camps = _csv("campaigns_%s.csv" % stem)
        done = sum(c["complete"] == "True" for c in camps)
        total, complete = total + len(camps), complete + done
        runs += len(_csv("runs_%s.csv" % stem))
        parts.append((done, len(camps)))
    assert "complete: %d of %d across the three pairs" % (complete, total) in section
    assert "(first x86 %d of %d, second x86 %d of %d, Arm %d of %d)" % (
        parts[0] + parts[1] + parts[2]) in section
    assert "The %s false starts" % {6: "six"}[total - complete] in section
    assert "all %s runs and %d campaigns" % ("{:,}".format(runs), total) in section
