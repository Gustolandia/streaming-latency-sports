"""The subprocess-coverage hook the six broker scripts carry at the top of the file.

Those six run as real processes in some tests -- a producer and a consumer talking to a mocked
broker cannot be exercised any other way -- and coverage does not follow a fork on its own. The
hook starts it when `COVERAGE_PROCESS_START` names a config file.

Why this file exists at all: `tests/conftest.py` sets that variable before anything is
imported, so in-process the hook's condition is *always* true and the branch where it is absent
is never taken. That is not an exotic corner. It is what happens on every machine that runs
these scripts for real -- the testbed, the cloud driver, a reader reproducing the work -- and
the hook must be inert there, not raising and not requiring coverage to be installed.

The modules are loaded under private names rather than reloaded in place. Reloading would swap
the module object other tests already hold references to; loading a second copy from the same
file gives coverage the same line numbers and disturbs nothing.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

#: Every script carrying the hook. A new one added without a line here is caught below.
HOOKED = ("compare_plans", "compute_tti", "kafka_consumer", "kafka_producer",
          "redis_consumer", "redis_producer")


def _load_a_second_copy(name):
    """Execute the module body again, under a throwaway name."""
    path = SCRIPTS_DIR / ("%s.py" % name)
    spec = importlib.util.spec_from_file_location("_hookprobe_%s" % name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", HOOKED)
def test_the_hook_is_inert_when_no_coverage_run_asked_for_it(name, monkeypatch):
    """The ordinary case: someone runs the script. Nothing may happen and nothing may fail."""
    monkeypatch.delenv("COVERAGE_PROCESS_START", raising=False)
    module = _load_a_second_copy(name)
    assert hasattr(module, "main"), "the module body must have run to completion"


@pytest.mark.parametrize("name", HOOKED)
def test_the_hook_starts_coverage_when_asked(name, monkeypatch, tmp_path):
    """The reason it is there: a subprocess must record what it executed."""
    started = []
    fake = type(sys)("coverage")
    fake.process_start = lambda: started.append(True)
    monkeypatch.setitem(sys.modules, "coverage", fake)
    monkeypatch.setenv("COVERAGE_PROCESS_START", str(tmp_path / ".coveragerc"))
    _load_a_second_copy(name)
    assert started == [True]


@pytest.mark.parametrize("name", HOOKED)
def test_a_broken_coverage_install_does_not_stop_the_script(name, monkeypatch, tmp_path):
    """These scripts produce measurements. Losing a run to the instrumentation is the one
    failure mode worse than losing the instrumentation."""
    fake = type(sys)("coverage")

    def explode():
        raise RuntimeError("coverage is misconfigured")

    fake.process_start = explode
    monkeypatch.setitem(sys.modules, "coverage", fake)
    monkeypatch.setenv("COVERAGE_PROCESS_START", str(tmp_path / ".coveragerc"))
    module = _load_a_second_copy(name)
    assert hasattr(module, "main"), "the script must survive its own instrumentation failing"


def test_the_list_above_is_the_list_of_scripts_that_carry_the_hook():
    """A seventh script gaining the hook silently would gain an uncovered branch with it."""
    carrying = sorted(p.stem for p in SCRIPTS_DIR.glob("*.py")
                      if "COVERAGE_PROCESS_START" in p.read_text(encoding="utf-8"))
    assert carrying == sorted(HOOKED)
