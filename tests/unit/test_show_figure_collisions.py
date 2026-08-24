"""Tests for scripts/show_figure_collisions.py - target 100% branch coverage.

This is the viewer for the collision gate: it renders what the gate saw -- the figure with its
glyphs painted transparent -- and outlines the core of every label the gate flagged. Two rounds
of figure defects were diagnosed with it, and one of those rounds went wrong because the *gate*
was believed over the page. A viewer that is itself unchecked is a poor place to put that much
trust, so what is pinned here is the correspondence: the rectangle it draws must be the
rectangle the gate measured, and the raster it draws it on must be the ink-only one.

It also pins the thing this module gets wrong most easily. It replaces `_save` on two other
modules to intercept figures, and a replacement left in place would silently stop those modules
saving anything for the rest of the process.
"""
import sys
from pathlib import Path

import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import figure_collisions as fc  # noqa: E402
import show_figure_collisions as sfc  # noqa: E402


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def _struck_figure():
    """A figure with a label a heavy stroke runs straight through."""
    fig, ax = plt.subplots(figsize=(4, 3))
    ax.plot([0, 1], [0, 1], lw=14, color="black")
    ax.text(0.5, 0.5, "struck label", ha="center", va="center", fontsize=9)
    return fig


def _colours(fig):
    """{id(text): colour} for every visible label, keyed by object.

    Keyed by identity rather than by position: measuring a figure materialises tick labels, so
    the *list* of visible texts is longer afterwards even though nothing was recoloured.
    """
    return {id(t): t.get_color() for t in fc._visible_texts(fig)}


def _clean_figure():
    fig, ax = plt.subplots(figsize=(4, 3))
    ax.plot([0, 1], [0, 1], lw=1, color="black")
    ax.set_title("clean")
    return fig


class TestSafe:
    """The console this runs on is cp1252 and the labels are not."""

    def test_plain_text_survives_readably(self):
        assert "hello" in sfc._safe("hello")

    def test_a_minus_sign_does_not_raise_and_does_not_vanish(self):
        out = sfc._safe("− 5 × 10")
        out.encode("ascii")            # the point: it is now printable anywhere
        assert "2212" in out and "d7" in out

    def test_the_result_is_pure_ascii_whatever_goes_in(self):
        sfc._safe("τ ≥ Δ").encode("ascii")


class TestAnnotateRaster:

    def test_it_outlines_the_label_the_gate_flagged(self, tmp_path):
        """The red rectangle must land on the flagged label, or the picture misleads."""
        from PIL import Image
        import numpy as np

        fig = _struck_figure()
        findings = fc.report(fig)["struck"]
        assert findings, "fixture must actually collide, or this test proves nothing"

        out = tmp_path / "shot.png"
        assert sfc.annotate_raster(fig, findings, out) == out

        arr = np.asarray(Image.open(out).convert("RGB"))
        red = ((arr[:, :, 0] > 180) & (arr[:, :, 1] < 80) & (arr[:, :, 2] < 80))
        assert red.any(), "no outline was drawn"

    def test_the_raster_it_draws_on_has_the_glyphs_removed(self, tmp_path):
        """It must show the gate's view. With the text still in it, nothing is diagnosable."""
        from PIL import Image
        import numpy as np

        fig = _struck_figure()
        findings = fc.report(fig)["struck"]
        out = tmp_path / "shot.png"
        sfc.annotate_raster(fig, findings, out)

        arr = np.asarray(Image.open(out).convert("L"))
        # The diagonal is the only dark ink left; a raster still carrying the label would
        # have markedly more.
        with_text = fc._raster(fig, fc.RENDER_DPI)
        assert (arr < 100).sum() < (with_text < 0.4).sum()

    def test_the_label_colours_are_put_back(self, tmp_path):
        """It paints text transparent to measure ink. Leaving it so would erase the figure."""
        fig = _struck_figure()
        findings = fc.report(fig)["struck"]
        before = _colours(fig)
        sfc.annotate_raster(fig, findings, tmp_path / "s.png")
        assert _colours(fig) == before
        assert all(c != (0.0, 0.0, 0.0, 0.0) for c in before.values())

    def test_the_colours_are_put_back_even_when_rastering_fails(self, tmp_path, monkeypatch):
        fig = _struck_figure()
        findings = fc.report(fig)["struck"]
        before = _colours(fig)
        monkeypatch.setattr(sfc.fc, "_raster", lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("render failed")))
        with pytest.raises(RuntimeError):
            sfc.annotate_raster(fig, findings, tmp_path / "s.png")
        assert _colours(fig) == before

    def test_a_finding_with_no_matching_label_is_skipped_not_fatal(self, tmp_path):
        """The gate reports text; the viewer looks it up. A miss must not lose the picture."""
        fig = _struck_figure()
        bogus = [{"text": "a label this figure does not contain", "fraction": 0.5}]
        assert sfc.annotate_raster(fig, bogus, tmp_path / "s.png").exists()

    def test_a_label_whose_box_cannot_be_measured_is_skipped(self, tmp_path, monkeypatch):
        """Some artists refuse a window extent; one of them must not stop the render."""
        calls = {"n": 0}

        def flaky(text, renderer):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("no extent")
            return fc._glyph_box(text, renderer)

        fig = _struck_figure()
        findings = fc.report(fig)["struck"]
        monkeypatch.setattr(sfc.fc, "_glyph_box", flaky)
        assert sfc.annotate_raster(fig, findings, tmp_path / "s.png").exists()
        assert calls["n"] > 1, "the failure must not have ended the loop"

    def test_long_labels_are_truncated_the_same_way_the_gate_truncates_them(self, tmp_path):
        """Both sides key on the first 60 characters; if they disagree, nothing matches."""
        fig, ax = plt.subplots(figsize=(4, 3))
        ax.plot([0, 1], [0, 1], lw=14, color="black")
        ax.text(0.5, 0.5, "x" * 200, ha="center", va="center", fontsize=9)
        findings = fc.report(fig)["struck"]
        assert findings and len(findings[0]["text"]) <= 60
        # A key longer than 60 would never be found, and nothing would ever be outlined.
        sfc.annotate_raster(fig, findings, tmp_path / "s.png")


class TestMain:
    """`main` drives the real figure builders; here they are replaced with known figures."""

    @pytest.fixture
    def builders(self, monkeypatch):
        import make_paper_figures as mpf
        import make_result_figures as mrf

        made = {"figs": [_clean_figure()]}

        def build(out_dir):
            fig = made["figs"].pop(0) if made["figs"] else _clean_figure()
            return mrf._save(fig, out_dir, "stem%d" % made.setdefault("n", 0))

        for name in ("build_deletion", "build_spectrum", "build_grid",
                     "build_mechanism", "build_ttrue", "build_payload"):
            monkeypatch.setattr(mrf, name, build)
        monkeypatch.setattr(mpf, "main", lambda argv: mpf._save(_clean_figure(), None, "paper"))
        return made

    def test_a_clean_set_of_figures_exits_zero(self, builders, tmp_path, capsys):
        assert sfc.main(["--out", str(tmp_path / "shots")]) == 0
        assert "0 of 7 figures carry a collision" in capsys.readouterr().out

    def test_a_collision_exits_nonzero_and_leaves_a_raster(self, builders, tmp_path, capsys):
        builders["figs"] = [_struck_figure()]
        out = tmp_path / "shots"
        assert sfc.main(["--out", str(out)]) == 1
        printed = capsys.readouterr().out
        assert "struck" in printed
        assert list(out.glob("*.png")), "the picture is the whole point of the tool"

    def test_the_output_directory_is_created(self, builders, tmp_path):
        out = tmp_path / "deep" / "shots"
        sfc.main(["--out", str(out)])
        assert out.is_dir()

    def test_an_overlap_is_reported_without_a_raster(self, builders, tmp_path, capsys,
                                                     monkeypatch):
        """Only struck labels get a picture; overlaps are legible from the text alone."""
        monkeypatch.setattr(sfc.fc, "report", lambda fig: {
            "struck": [], "overlapping": [{"a": "one", "b": "two", "overlap": 0.4}],
            "clipped": []})
        out = tmp_path / "shots"
        assert sfc.main(["--out", str(out)]) == 1
        assert "overlap" in capsys.readouterr().out
        assert list(out.glob("*.png")) == []

    def test_a_clipped_marker_is_reported(self, builders, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(sfc.fc, "report", lambda fig: {
            "struck": [], "overlapping": [],
            "clipped": [{"point": "(1.0, 2.0)", "overhang_px": 3.5, "radius_px": 6.0}]})
        assert sfc.main(["--out", str(tmp_path / "shots")]) == 1
        assert "clipped point" in capsys.readouterr().out

    def test_it_defaults_to_a_build_directory(self, builders, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        sfc.main([])
        assert (tmp_path / "build" / "collisions").is_dir()

    def test_it_puts_back_the_save_functions_it_replaced(self, builders, tmp_path):
        """A module left holding the inspector silently stops saving figures for good."""
        import make_paper_figures as mpf
        import make_result_figures as mrf

        before = (mrf._save, mpf._save)
        sfc.main(["--out", str(tmp_path / "shots")])
        assert (mrf._save, mpf._save) == before

    def test_they_are_put_back_even_when_a_builder_raises(self, builders, tmp_path,
                                                          monkeypatch):
        import make_paper_figures as mpf
        import make_result_figures as mrf

        before = (mrf._save, mpf._save)
        monkeypatch.setattr(mrf, "build_grid", lambda out_dir: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            sfc.main(["--out", str(tmp_path / "shots")])
        assert (mrf._save, mpf._save) == before
