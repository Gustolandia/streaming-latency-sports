"""Every test runs on Windows and on Linux: none may skip because of the platform it is on.

Until 27 September the tests of the kit's shell scripts skipped on Windows, the author's
machine, and CI ran on Linux alone. A test could be red on one platform and never looked at
from the other: CI failed 78 commits in a row between 22 and 25 September on tests the author's
machine never ran. CI now runs the suite on both, and this holds the tests to it. A test that
needs something one platform lacks is given it (tests/posix_shell.py: Git's bash, a python3,
and WSL's Linux for what only the Linux kernel does), not skipped.

Read from the source, so it also catches a skip that has not yet been reached: any skip whose
condition names the platform -- sys.platform, os.name, platform.system(), or a name built from
one of them.
"""
import ast
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent.parent
#: Words that make a condition a question about the platform.
PLATFORM_WORDS = ("sys.platform", "os.name", "platform.system", "platform.platform",
                  "WINDOWS", "win32", "IS_WINDOWS", "ON_WINDOWS")


def _is_skip_mark(func):
    """pytest.mark.skipif, pytest.mark.xfail, unittest.skipIf/skipUnless and their bare names."""
    text = ast.unparse(func)
    return text.endswith(("mark.skipif", "mark.xfail", "skipIf", "skipUnless"))


def _is_skip_call(func):
    return ast.unparse(func) in ("pytest.skip", "pytest.xfail", "skip", "xfail")


def _names_the_platform(node):
    text = ast.unparse(node)
    return any(word in text for word in PLATFORM_WORDS)


def platform_skips(source, name="<source>"):
    """Every place in SOURCE that skips a test for the platform it runs on, as (line, text)."""
    found = []
    tree = ast.parse(source, filename=name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_skip_mark(node.func):
            conditions = list(node.args[:1]) + [k.value for k in node.keywords
                                                if k.arg in ("condition",)]
            if any(_names_the_platform(c) for c in conditions):
                found.append((node.lineno, ast.unparse(node)[:120]))
        if isinstance(node, ast.If) and _names_the_platform(node.test):
            for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if isinstance(inner, ast.Call) and _is_skip_call(inner.func):
                    found.append((inner.lineno, ast.unparse(node.test)[:120]))
    return found


def test_no_test_anywhere_skips_for_its_platform():
    offenders = []
    for path in sorted(TESTS.rglob("*.py")):
        for line, text in platform_skips(path.read_text(encoding="utf-8"), str(path)):
            offenders.append("%s:%d: %s" % (path.relative_to(TESTS), line, text))
    assert not offenders, "tests that skip for the platform:\n" + "\n".join(offenders)


@pytest.mark.parametrize("source", [
    'import sys, pytest\n@pytest.mark.skipif(sys.platform == "win32", reason="x")\ndef test(): pass\n',
    'import os, pytest\nneeds = pytest.mark.skipif(os.name == "nt" or 1, reason="x")\n',
    'import platform, pytest\ndef test():\n    if platform.system() == "Windows":\n'
    '        pytest.skip("no")\n',
    'import sys, unittest\n@unittest.skipIf(sys.platform.startswith("win"), "x")\ndef test(): pass\n',
    'import pytest\nWINDOWS = True\n@pytest.mark.xfail(WINDOWS, reason="x")\ndef test(): pass\n',
])
def test_the_guard_sees_each_way_a_platform_skip_is_written(source):
    assert platform_skips(source)


@pytest.mark.parametrize("source", [
    'import pytest, shutil\n@pytest.mark.skipif(shutil.which("pdffonts") is None, reason="x")\n'
    'def test(): pass\n',
    'import sys\nWINDOWS = sys.platform == "win32"\ndef test():\n    assert WINDOWS in (True, False)\n',
    'import sys, pytest\ndef test():\n    if sys.platform == "win32":\n        x = 1\n',
])
def test_the_guard_leaves_what_is_not_a_platform_skip_alone(source):
    assert not platform_skips(source)
