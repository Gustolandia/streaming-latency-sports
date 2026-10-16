"""No test may write into docs/generated through scripts/emit_paper_numbers.py's defaults.

Tests that run the emitter's main() name the outputs they assert on and let the rest default,
and every default is a committed file under docs/generated. On 15 Oct 2026 a test session that
had started before a generator change rewrote two committed tables with the old code. The
autouse fixture `_emitter_outputs_stay_out_of_the_repo` in tests/conftest.py now points every
default output at the test's temporary directory; these tests hold it to that.
"""
import csv
import os
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import emit_paper_numbers as epn  # noqa: E402

REPO = SCRIPTS_DIR.parent
GENERATED = REPO / "docs" / "generated"
SOURCE = (SCRIPTS_DIR / "emit_paper_numbers.py").read_text(encoding="utf-8")


def _snapshot():
    return {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in GENERATED.iterdir()}


class TestTheDefaultsPointAway:

    def test_every_generated_default_is_patched_into_the_temporary_directory(self, temp_dir):
        named = re.findall(r'(?m)^(DEFAULT_[A-Z0-9_]+) = os\.path\.join\("docs", "generated", ',
                           SOURCE)
        assert len(named) >= 20, "the emitter's output constants were not found"
        for name in named:
            value = getattr(epn, name)
            assert Path(value).parent == temp_dir / "generated", (name, value)

    def test_every_output_option_defaults_to_a_patched_constant(self):
        """main() reads its defaults from those constants when it builds its parser; an option
        whose default is typed in place would escape the fixture."""
        main = SOURCE[SOURCE.index("def main(argv=None):"):]
        main = main[:main.index("args = ap.parse_args(argv)")]
        options = re.findall(r'ap\.add_argument\("(--[a-z0-9-]+)"(.*?)\)\n', main, re.S)
        assert len(options) >= 20
        for option, rest in options:
            if option in ("--ledger", "--check"):
                continue                        # the input, and a switch
            assert re.search(r"default=DEFAULT_[A-Z0-9_]+$", rest.strip()), (option, rest)


class TestMainLeavesTheCommittedTablesAlone:

    def test_a_run_naming_only_its_own_outputs_writes_nothing_in_the_repository(
            self, tmp_path, monkeypatch, temp_dir):
        # Fast stand-ins for the slow parts; the paths main() writes to are the real defaults.
        monkeypatch.setattr(epn, "all_pairs", lambda m: [])
        for name in dir(epn):
            if name.startswith("render_") and name.endswith("_table"):
                monkeypatch.setattr(epn, name, lambda *a, **kw: "stub\n")
        led = tmp_path / "l.csv"
        with led.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(("campaign", "cell", "valid", "count_source", "kept", "discarded_zero",
                        "discarded_negative"))
            w.writerow(("load_sweep", "c0", "1", "shutdown_hook", 10, 90, 0))
        before = _snapshot()
        assert epn.main(["--ledger", str(led), "--out", str(tmp_path / "n.tex")]) == 0
        assert _snapshot() == before, "main() rewrote a committed file under docs/generated"
        written = sorted(os.listdir(temp_dir / "generated"))
        assert "grid_table.tex" in written and "registry_table.tex" in written, written
