"""The broker libraries are stubbed in one place, and this keeps it that way.

`tests/conftest.py` puts MagicMocks in sys.modules for kafka and redis, because the unit suite
runs where neither library is installed and no broker is listening. Five test modules used to do
it again at their own import time, and that is not harmless duplication:

    import redis                     # in scripts/redis_producer.py, at ITS import
    redis.Redis(...)                 # looks the attribute up on the object bound above

A script binds the module object present when it is imported. A test module imported later that
reassigns sys.modules['redis'] leaves the script holding the earlier object, while
`patch('redis.Redis', ...)` resolves through sys.modules and patches the later one. The patch then
reaches nothing: the producer goes on calling the old mock, the test's mock records no calls, and
four tests in test_redis_producer.py fail -- but only in module orders where the reassigning
module is imported after the one under test. In the full suite the alphabetical order happened to
hide it, so the suite was green and a four-module selection was not.

An order-dependent test is not a test of the thing it names; it is a test of the order. So the
rule is structural: conftest stubs them, nobody else does.
"""
import re
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
CONFTEST = TESTS.parent / "conftest.py"

#: Reassigning any of these is what breaks the binding; the libraries the unit suite never has.
STUBBED = ("kafka", "redis")
ASSIGNS = re.compile(r"^\s*sys\.modules\[['\"](?P<name>[\w.]+)['\"]\]\s*=", re.MULTILINE)


def stubbed_in(path):
    return [m.group("name") for m in ASSIGNS.finditer(path.read_text(encoding="utf-8"))
            if m.group("name").split(".")[0] in STUBBED]


def test_conftest_is_where_they_are_stubbed():
    """If this ever stops being true the rule below is vacuous rather than satisfied."""
    assert set(stubbed_in(CONFTEST)) >= {"kafka", "redis"}


@pytest.mark.parametrize("path", sorted(TESTS.glob("test_*.py")), ids=lambda p: p.name)
def test_no_test_module_stubs_them_again(path):
    again = stubbed_in(path)
    assert not again, (
        "%s reassigns sys.modules for %s. conftest.py has already stubbed them, and a script that "
        "has run `import %s` keeps the object that was there then -- patch() would target this "
        "one and reach nothing. Remove it and rely on conftest."
        % (path.name, ", ".join(sorted(set(again))), again[0].split(".")[0]))
