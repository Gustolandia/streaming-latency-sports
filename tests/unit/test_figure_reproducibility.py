r"""A rebuilt figure is byte-identical to the figure it rebuilds.

Round 76 changed one figure and regenerated eight. Git reported all eight modified. Seven had
identical extracted text, identical pixels and identical size; the only differing bytes, six or
seven per file, were inside `/CreationDate`. matplotlib writes the wall clock into every PDF,
so every build dirtied every figure and the history could not separate a figure that changed
from one that was merely rebuilt.

The repair is `SOURCE_DATE_EPOCH`, set once in `figure_style.apply()`, which every figure script
calls. These tests hold it there.
"""
import hashlib
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _draw(path):
    import matplotlib.pyplot as plt
    import figure_style
    figure_style.apply()
    fig, ax = plt.subplots(figsize=(2.0, 1.5))
    ax.plot([0, 1, 2], [0, 1, 4])
    ax.set_xlabel("x")
    fig.savefig(path)
    plt.close(fig)


class TestAFigureRebuildsToTheSameBytes:

    def test_two_builds_a_moment_apart_are_identical(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
        import time
        _draw(tmp_path / "a.pdf")
        time.sleep(1.1)                                  # past the clock's one-second grain
        _draw(tmp_path / "b.pdf")
        assert _digest(tmp_path / "a.pdf") == _digest(tmp_path / "b.pdf"), (
            "two builds of one figure differ; the wall clock is back in the PDF")

    def test_the_stamp_is_the_pinned_epoch_and_not_the_clock(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
        import figure_style
        _draw(tmp_path / "c.pdf")
        blob = (tmp_path / "c.pdf").read_bytes()
        assert b"/CreationDate" in blob
        assert os.environ["SOURCE_DATE_EPOCH"] == figure_style.SOURCE_DATE_EPOCH

    def test_an_externally_pinned_date_is_respected(self, monkeypatch):
        """`setdefault`, so a CI or a packager that pins a real date keeps it."""
        monkeypatch.setenv("SOURCE_DATE_EPOCH", "1767225600")
        import figure_style
        figure_style.apply()
        assert os.environ["SOURCE_DATE_EPOCH"] == "1767225600"

    def test_the_test_path_leaves_the_environment_alone(self, monkeypatch):
        """apply(rc=...) exists so tests can inspect the policy without mutating the process;
        that promise has to cover the environment as well as rcParams."""
        monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
        import figure_style
        figure_style.apply(rc={})
        assert "SOURCE_DATE_EPOCH" not in os.environ

    def test_every_figure_script_goes_through_apply(self):
        """The repair lives in one function, so it only reaches scripts that call it."""
        writers = [p for p in (REPO / "scripts").glob("make_*.py")
                   if "savefig" in p.read_text(encoding="utf-8")
                   and ".pdf" in p.read_text(encoding="utf-8")]
        assert writers, "no figure writers found; the glob has gone stale"
        missing = [p.name for p in writers
                   if "figure_style.apply" not in p.read_text(encoding="utf-8")]
        assert not missing, "figure scripts bypassing figure_style.apply(): %s" % missing
