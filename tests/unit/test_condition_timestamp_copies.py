"""The run-id parser that seven analysis scripts each carry their own copy of.

`condition_timestamp` reads the timestamp a condition's trials share out of the name of its
concurrency subdirectory. Seven scripts define it, and the bodies are byte-identical -- only the
docstrings differ. Every one of them had the same branch uncovered: a subdirectory that matches
the glob but not the timestamp pattern, where the function must keep looking rather than
answer.

Testing them together rather than seven times over is not only shorter. The risk in seven
copies of a parser is that they stop being seven copies, and no per-script test can see that.
This file pins the behaviour once, against every copy, and pins that they are still the same
function.

The branch itself is not hypothetical. These directories accumulate `concurrency_concurrency_`
subdirectories from interrupted runs and from tooling that writes its own scratch folders, and
a parser that answered `None` on meeting the first of them would silently drop the condition
from every analysis that walks it.
"""
import importlib
import inspect
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

#: Every script defining it. A new copy appearing is caught by the last test here.
CARRIERS = ("analyze_clean_sweep", "analyze_collapse", "analyze_depth",
            "analyze_e1_replication", "analyze_knee", "analyze_moments", "analyze_window")

GOOD = "concurrency_concurrency_n4_20260712_101500"
JUNK = "concurrency_concurrency_scratch"


@pytest.fixture(params=CARRIERS)
def parser(request):
    """`condition_timestamp` from one carrier, named for readable failures."""
    module = importlib.import_module(request.param)
    fn = module.condition_timestamp
    fn.carrier = request.param
    return fn


def _condition(tmp_path, *subdirs):
    root = tmp_path / "cond"
    for name in subdirs:
        (root / name).mkdir(parents=True)
    root.mkdir(exist_ok=True)
    return str(root)


class TestEveryCopy:

    def test_it_reads_the_timestamp_out_of_the_subdirectory_name(self, parser, tmp_path):
        assert parser(_condition(tmp_path, GOOD)) == "n4_20260712_101500"

    def test_a_subdirectory_that_does_not_carry_a_timestamp_is_stepped_over(self, parser,
                                                                           tmp_path):
        """The branch none of the seven had covered.

        Interrupted runs and scratch folders leave directories that match the glob and carry
        no run id. Answering None on the first of them would drop the whole condition.
        """
        assert parser(_condition(tmp_path, JUNK, GOOD)) == "n4_20260712_101500"

    def test_a_condition_of_nothing_but_junk_has_no_timestamp(self, parser, tmp_path):
        assert parser(_condition(tmp_path, JUNK, "concurrency_concurrency_x")) is None

    def test_a_condition_with_no_subdirectories_has_no_timestamp(self, parser, tmp_path):
        assert parser(_condition(tmp_path)) is None

    def test_a_directory_that_does_not_exist_has_no_timestamp(self, parser, tmp_path):
        assert parser(str(tmp_path / "never-created")) is None

    def test_directories_outside_the_naming_convention_are_not_consulted(self, parser,
                                                                         tmp_path):
        """Only `concurrency_concurrency_*` is a trial directory; the rest are other things."""
        assert parser(_condition(tmp_path, "logs_n9_20260101_000000")) is None

    def test_the_run_id_must_be_fully_formed_to_count(self, parser, tmp_path):
        """A truncated stamp comes from a run that died mid-write; it names no complete trial."""
        assert parser(_condition(tmp_path, "concurrency_concurrency_n4_20260712")) is None

    def test_a_worker_count_is_required(self, parser, tmp_path):
        assert parser(_condition(tmp_path, "concurrency_concurrency_20260712_101500")) is None


class TestTheCopiesHaveNotDrifted:
    """Seven copies of a parser is a fact about this repository; seven *different* parsers
    would be a defect no single script's tests could see."""

    @staticmethod
    def _body(name):
        module = importlib.import_module(name)
        source = textwrap.dedent(inspect.getsource(module.condition_timestamp))
        # The docstrings differ deliberately, describing each script's own use.
        return [line for line in source.splitlines()
                if line.strip() and not line.strip().startswith(('"""', "'''"))]

    def test_all_seven_bodies_are_the_same_code(self):
        bodies = {name: self._body(name) for name in CARRIERS}
        first = bodies[CARRIERS[0]]
        for name, body in bodies.items():
            assert body == first, "%s has drifted from %s" % (name, CARRIERS[0])

    def test_the_list_above_is_every_script_that_defines_it(self):
        defining = sorted(p.stem for p in SCRIPTS_DIR.glob("*.py")
                          if "def condition_timestamp(" in p.read_text(encoding="utf-8"))
        assert defining == sorted(CARRIERS), (
            "a new copy appeared or one was removed; the shared behaviour above must cover it")
