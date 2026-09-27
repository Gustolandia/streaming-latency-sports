"""The rule that nothing in this suite may skip, tested on its own (tests/no_skips.py).

Each way a test can skip is written into a scratch suite, and the suite is run with the rule
loaded: every one must fail, with the skip's own reason, and a test that passes must still pass.
A module skipped whole as it is collected fails the collection, which stops the run -- as loud as
a skip can be made.
"""
import os
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent

SKIPPING_TESTS = (
    "import pytest\n"
    "def test_called():\n"
    "    pytest.skip('a file it needs is missing')\n"
    "@pytest.mark.skipif(True, reason='a mark that holds')\n"
    "def test_marked():\n"
    "    pass\n"
    "@pytest.mark.skip(reason='kept for the record')\n"
    "def test_unconditional():\n"
    "    pass\n"
    "@pytest.fixture\n"
    "def needs():\n"
    "    pytest.skip('a fixture gave up')\n"
    "def test_by_fixture(needs):\n"
    "    pass\n"
    "@pytest.mark.xfail(reason='known to fail')\n"
    "def test_expected_to_fail():\n"
    "    assert False\n"
    "def test_that_passes():\n"
    "    assert True\n")

SKIPPING_MODULE = (
    "import pytest\n"
    "pytest.importorskip('a_module_nobody_installed')\n"
    "def test_never_reached():\n"
    "    pass\n")


def _run(tmp_path, source, plugin=True):
    (tmp_path / "test_scratch.py").write_text(source, encoding="utf-8")
    command = [sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider",
               "--rootdir", str(tmp_path), str(tmp_path)]
    if plugin:
        command[3:3] = ["-p", "no_skips"]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")]))
    #: The scratch suite is not this one: it measures no coverage of its own.
    env.pop("COVERAGE_PROCESS_START", None)
    done = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True,
                          timeout=120)
    return done.returncode, done.stdout + done.stderr


def test_every_way_a_test_can_skip_fails_with_its_reason(tmp_path):
    code, out = _run(tmp_path, SKIPPING_TESTS)
    assert code != 0, out
    for reason in ("a file it needs is missing", "a mark that holds", "kept for the record",
                   "a fixture gave up", "known to fail"):
        assert reason in out, "%r did not fail: %s" % (reason, out[-3000:])
    assert "nothing in this suite may skip" in out
    last = out.strip().splitlines()[-1]
    assert "skipped" not in last and "xfailed" not in last, "a skip got through: " + last
    assert "PASSED test_scratch.py::test_that_passes" in out, "a passing test must still pass"


def test_a_module_skipped_as_it_is_collected_fails_the_collection(tmp_path):
    code, out = _run(tmp_path, SKIPPING_MODULE)
    assert code != 0, out
    assert "a_module_nobody_installed" in out and "nothing in this suite may skip" in out
    assert "skipped" not in out.strip().splitlines()[-1]


def test_without_the_rule_the_same_suites_are_green(tmp_path):
    """The scratch suites really do skip: without the rule they pass, skipping."""
    code, out = _run(tmp_path, SKIPPING_TESTS, plugin=False)
    assert code == 0, out
    last = out.strip().splitlines()[-1]
    assert "1 passed" in last and "4 skipped" in last and "1 xfailed" in last, last
    code, out = _run(tmp_path, SKIPPING_MODULE, plugin=False)
    #: 5 is pytest's "no tests ran": the only module skipped whole, and that is not a failure.
    assert code == 5 and "1 skipped" in out.strip().splitlines()[-1], out
