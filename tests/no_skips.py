"""Nothing in this suite may skip: a skip is reported as the failure it stands for.

A skipped test reports as neither passing nor failing, and a suite that skips can be green while
a check is made nowhere. The kit's shell tests skipped on Windows while CI ran only Linux, and a
dozen paper gates skipped wherever the paper had not been built by hand -- which was everywhere
but the author's machine. Every test now runs on Windows and on Linux (tests/posix_shell.py,
tests/paper_build.py), so a skip can only mean that something a test needs is missing, and it
fails with the skip's own reason. That holds for a skip in the test, in a mark, in a fixture,
and for a module skipped whole as it is collected.

Loaded by tests/conftest.py; a pytest plugin, so it can also be tested on its own.
"""
import pytest

SAID = "nothing in this suite may skip, and this"


def _reason(longrepr):
    """What the skip said: pytest keeps it as (file, line, reason) or as text."""
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.skipped:
        report.outcome = "failed"
        report.longrepr = "%s test skipped: %s" % (SAID, _reason(report.longrepr))


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    outcome = yield
    report = outcome.get_result()
    if report.skipped:
        report.outcome = "failed"
        report.longrepr = "%s module skipped as it was collected: %s" % (
            SAID, _reason(report.longrepr))
