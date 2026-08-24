"""The gate on the gate: what `# pragma: no cover` is allowed to hide.

The project's coverage standard is 100% of branches in `scripts/`, which is only worth stating
if the number cannot be bought. It can be, trivially, by excluding whatever does not pass --
and a suite that reports 100% while a hundred lines sit behind pragmas is worse than one that
honestly reports 95%, because the number stops being a question anyone asks.

Two rules, and they are different because the two kinds of exclusion are different.

**The `__main__` dispatch.** Ninety-one scripts end with the same two lines: a guard and a call
to `main()`. `main()` is called directly by those scripts' own tests, so the excluded lines are
not untested logic -- they are not logic. Running them under coverage would mean re-executing
each script through runpy with a synthetic argv, which buys the colour and no confidence. What
must be guaranteed instead is that nothing else is hiding there, so the rule is structural: the
block may hold only calls and imports, and no control flow at all. A conditional under a
pragma'd guard is exactly the thing this test exists to catch.

**Everything else.** Thirteen exclusions cover code that cannot run on this machine: a network
call, an import of an optional dependency, a free-threaded-build branch, a fallback for an
interpreter older than the one we test on. Each is legitimate and each is a place a future
untested branch could be quietly parked, so they are enumerated here by file and line-content.
Adding one means adding a line to this list, which is the point: the exclusion becomes a
decision someone made and wrote down rather than a comment that appeared.
"""
import ast
import re
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent.parent / "scripts"

PRAGMA = re.compile(r"#\s*pragma:\s*no cover(?P<reason>\s*-\s*\S.*)?$")
MAIN_GUARD = re.compile(r'^if __name__ == ([\'"])__main__\1:')

#: Every exclusion that is not a `__main__` dispatch, as (file, the code it hides, why).
#: A new entry here is a deliberate act; an exclusion that is not here fails the test below.
ALLOWED = {
    ("emit_paper_numbers.py", "except ImportError:"):
        "stat_intervals ships beside this file",
    ("fetch_statsbomb_corpus.py", "def _default_get(url, timeout=60):"):
        "reaches the network; the tests inject a fake",
    ("kafka_producer_confluent.py", "except ImportError:"):
        "confluent-kafka is optional and is not installed here",
    ("platform_probe.py", "def _default_connect(host, port, timeout):"):
        "opens a socket; the tests inject a fake",
    ("platform_probe.py", "def _default_socket(host, port, timeout):"):
        "opens a socket; the tests inject a fake",
    ("platform_probe.py", "def _read_text(path):"):
        "reads /proc and /sys; the tests inject a fake",
    ("platform_probe.py", "if flags is not None:"):
        "free-threaded builds only",
    ("power_analysis.py", "try:"):
        "statsmodels is optional and is not installed here",
    ("power_analysis.py", "except Exception:"):
        "statsmodels is optional and is not installed here",
    ("tail_index_traced.py", "if n * p > 30:"):
        "only on interpreters without random.binomialvariate",
    ("tail_index_traced.py", "return sum(1 for _ in range(n)"):
        "only on interpreters without random.binomialvariate",
    ("tail_index_traced.py", "except ValueError:"):
        "a bootstrap replicate with one populated bucket",
}


def _exclusions():
    """(file, line number, source line) for every pragma in scripts/."""
    out = []
    for path in sorted(SCRIPTS.glob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if PRAGMA.search(line):
                out.append((path, n, line))
    return out


def _statement(line):
    """The code an exclusion hides, with the pragma comment and indentation removed."""
    return PRAGMA.sub("", line).strip().rstrip()


ALL = _exclusions()
NON_MAIN = [(p, n, ln) for p, n, ln in ALL if not MAIN_GUARD.match(ln.strip())]
MAIN = [(p, n, ln) for p, n, ln in ALL if MAIN_GUARD.match(ln.strip())]


class TestThereAreExclusionsAndTheyAreFindable:

    def test_the_scan_found_the_dispatch_guards(self):
        """If this drops to nothing the rules below are vacuously true."""
        assert len(MAIN) > 50

    def test_the_scan_found_the_other_exclusions(self):
        assert NON_MAIN, "the inventory below would be checking nothing"


class TestTheDispatchGuardsHideNothingButDispatch:
    """A pragma on `if __name__ == "__main__":` excludes the whole block under it."""

    @staticmethod
    def _block(path, lineno):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and node.lineno == lineno:
                return node.body
        raise AssertionError("no if-statement at %s:%d" % (path.name, lineno))

    @pytest.mark.parametrize("path,lineno", [(p, n) for p, n, _ in MAIN],
                             ids=[p.name for p, _, _ in MAIN])
    def test_it_holds_only_calls_and_imports(self, path, lineno):
        """No branch, no loop, no definition -- nothing that could need a test of its own.

        A conditional parked here would be excluded from coverage while looking like the
        two-line dispatch every other script has, and nothing else in the suite would see it.
        """
        for stmt in self._block(path, lineno):
            assert isinstance(stmt, (ast.Expr, ast.Import, ast.ImportFrom, ast.Raise,
                                     ast.Pass)), (
                "%s:%d excludes a %s under its __main__ guard"
                % (path.name, stmt.lineno, type(stmt).__name__))
            if isinstance(stmt, ast.Expr):
                assert isinstance(stmt.value, ast.Call), (
                    "%s:%d excludes a bare expression" % (path.name, stmt.lineno))

    @pytest.mark.parametrize("path,lineno", [(p, n) for p, n, _ in MAIN],
                             ids=[p.name for p, _, _ in MAIN])
    def test_it_is_short(self, path, lineno):
        """Four statements is more than any dispatch here needs and less than any logic."""
        assert len(self._block(path, lineno)) <= 4, (
            "%s hides %d statements under its __main__ guard"
            % (path.name, len(self._block(path, lineno))))


class TestEveryOtherExclusionWasWrittenDown:

    @pytest.mark.parametrize("path,lineno,line", NON_MAIN,
                             ids=["%s:%d" % (p.name, n) for p, n, _ in NON_MAIN])
    def test_it_is_in_the_inventory_above(self, path, lineno, line):
        """An exclusion nobody listed is an exclusion nobody decided on."""
        key = (path.name, _statement(line))
        assert key in ALLOWED, (
            "%s:%d excludes %r with no entry in ALLOWED; add one saying why, or cover it"
            % (path.name, lineno, _statement(line)))

    @pytest.mark.parametrize("path,lineno,line", NON_MAIN,
                             ids=["%s:%d" % (p.name, n) for p, n, _ in NON_MAIN])
    def test_it_carries_a_reason_on_the_line_itself(self, path, lineno, line):
        """The inventory is here; the reason must also be where a reader of the code is."""
        assert PRAGMA.search(line).group("reason"), (
            "%s:%d excludes code with no reason on the line" % (path.name, lineno))

    def test_the_inventory_has_no_entries_that_no_longer_exist(self):
        """A stale entry would licence an exclusion someone reintroduces later."""
        present = {(p.name, _statement(ln)) for p, _, ln in NON_MAIN}
        assert set(ALLOWED) - present == set(), (
            "these entries name exclusions that are gone: %s" % (set(ALLOWED) - present,))

    def test_they_are_few(self):
        """Not a limit for its own sake: this many is what "cannot run here" honestly covers,
        and a jump would mean the standard had started being met by exclusion."""
        assert len(NON_MAIN) <= 20, (
            "%d exclusions outside the dispatch guards; 100%% is being bought, not earned"
            % len(NON_MAIN))
