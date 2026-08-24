"""Tests for scripts/figure_style.py - target 100% branch coverage.

This module is the fix for a defect that survived six referee rounds: every figure in both
documents was embedding Type 3 DejaVu Sans, which is both the classic IEEE PDF eXpress
rejection and a family not on IEEE's list for text inside graphics. It survived because the
setting was one line per script in five scripts and nothing checked any of them.

The built PDFs are the real gate -- `test_pdf_compliance` reads the bytes IEEE will receive.
What is checked here is the policy this module hands matplotlib, and in particular the two
decisions that are easy to undo by accident: that maths is set to the text family rather than
to a stix set, and that a machine missing every listed font says so instead of quietly
producing DejaVu.
"""
import sys
from pathlib import Path

import pytest

matplotlib = pytest.importorskip("matplotlib")

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import figure_style  # noqa: E402


class TestApply:
    """Every assertion runs against a plain dict; the process rcParams are left alone."""

    def test_the_pdf_font_type_is_truetype_not_matplotlibs_default(self):
        """Type 3 is what you get by not choosing, and it is what gets a paper rejected."""
        rc = figure_style.apply({})
        assert rc["pdf.fonttype"] == 42
        assert rc["ps.fonttype"] == 42
        assert figure_style.TRUETYPE == 42

    def test_the_family_is_the_ieee_list_in_preference_order(self):
        rc = figure_style.apply({})
        assert rc["font.family"] == "sans-serif"
        assert rc["font.sans-serif"][:2] == ["Arial", "Helvetica"]

    def test_the_chain_ends_at_dejavu_so_any_machine_still_builds(self):
        """Failing the build on a missing font would be worse; the PDF gate catches it later."""
        assert figure_style.IEEE_SANS[-1] == "DejaVu Sans"

    def test_the_metric_substitutes_come_before_the_fallback(self):
        """A Linux build should land on Nimbus or Liberation, not back on DejaVu."""
        chain = figure_style.IEEE_SANS
        for name in ("Liberation Sans", "Nimbus Sans"):
            assert chain.index(name) < chain.index("DejaVu Sans")

    def test_the_list_it_sets_is_a_copy(self):
        """A caller mutating rcParams must not edit the module's own constant."""
        rc = figure_style.apply({})
        rc["font.sans-serif"].append("Comic Sans MS")
        assert "Comic Sans MS" not in figure_style.IEEE_SANS

    def test_maths_uses_the_text_family_rather_than_a_stix_set(self):
        """stix is TrueType and would pass the font rule, but it maps italic latin into the
        mathematical-alphanumeric block, so a label stops extracting as ordinary letters."""
        rc = figure_style.apply({})
        assert rc["mathtext.fontset"] == "custom"
        assert rc["mathtext.rm"] == "Arial"
        assert rc["mathtext.it"] == "Arial:italic"
        assert rc["mathtext.bf"] == "Arial:bold"
        assert rc["mathtext.default"] == "it"

    def test_every_mathtext_slot_is_set(self):
        """An unset slot silently falls back to DejaVu inside maths only."""
        rc = figure_style.apply({})
        for slot in ("rm", "it", "bf", "sf", "tt"):
            assert rc["mathtext.%s" % slot].startswith("Arial")

    def test_the_text_metrics_are_pinned(self):
        """Another script here sets font.size at import; without this, a combined build draws
        different figures from a standalone one and the layout gates measure the wrong page."""
        rc = figure_style.apply({})
        assert rc["font.size"] == 10.0
        assert rc["figure.figsize"] == [6.4, 4.8]
        assert rc["figure.dpi"] == 100.0

    def test_savefig_bbox_is_pinned_to_none(self):
        """'tight' changes the canvas after layout, so measured geometry stops matching."""
        rc = figure_style.apply({})
        assert rc["savefig.bbox"] is None
        assert rc["savefig.pad_inches"] == 0.1

    def test_the_pinned_metrics_are_matplotlibs_own_defaults(self):
        """Pinning must make a combined build agree with a standalone one, not change it."""
        with matplotlib.rc_context():
            matplotlib.rcdefaults()
            for key, value in figure_style.DEFAULT_METRICS.items():
                assert matplotlib.rcParams[key] == value, key

    def test_it_is_idempotent(self):
        assert figure_style.apply({}) == figure_style.apply(figure_style.apply({}))

    def test_it_returns_what_it_set(self):
        rc = {}
        assert figure_style.apply(rc) is rc

    def test_called_with_no_argument_it_sets_the_process_rcparams(self):
        with matplotlib.rc_context():
            matplotlib.rcParams["pdf.fonttype"] = 3
            figure_style.apply()
            assert matplotlib.rcParams["pdf.fonttype"] == 42


class TestResolvedFamily:
    """What the figure scripts print so a bad build machine is audible."""

    class _Font:
        def __init__(self, name):
            self.name = name

    def _installed(self, monkeypatch, names):
        import matplotlib.font_manager as fm
        monkeypatch.setattr(fm.fontManager, "ttflist",
                            [self._Font(n) for n in names])

    def test_it_reports_the_first_listed_font_that_is_installed(self, monkeypatch):
        self._installed(monkeypatch, ["Nimbus Sans", "Arial", "DejaVu Sans"])
        assert figure_style.resolved_family() == "Arial"

    def test_preference_order_beats_installation_order(self, monkeypatch):
        """The answer must be what matplotlib will pick, not what the system lists first."""
        self._installed(monkeypatch, ["DejaVu Sans", "Liberation Sans"])
        assert figure_style.resolved_family() == "Liberation Sans"

    def test_a_machine_with_none_of_them_reports_none_rather_than_a_guess(self, monkeypatch):
        """This is the case the function exists for: it must not answer DejaVu by accident."""
        self._installed(monkeypatch, ["Comic Sans MS"])
        assert figure_style.resolved_family() is None

    def test_no_fonts_at_all_is_none(self, monkeypatch):
        self._installed(monkeypatch, [])
        assert figure_style.resolved_family() is None

    def test_on_this_machine_it_finds_something(self):
        """DejaVu Sans ships with matplotlib, so a real answer here is always available."""
        assert figure_style.resolved_family() in figure_style.IEEE_SANS
