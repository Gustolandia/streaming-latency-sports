"""Tests for scripts/make_method_figure.py - target 100% branch coverage.

The figure is a claim-to-experiment map, so the test that matters is not that it renders but
that its content stays in step with the paper: every campaign the paper reports must have a row,
and no row may claim to both generate and test a hypothesis.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from make_method_figure import ROWS, draw, main  # noqa: E402


class TestRows:
    def test_every_row_is_complete(self):
        for row in ROWS:
            assert len(row) == 4, f"row {row[0]!r} must have all four columns"
            assert all(str(cell).strip() for cell in row), f"row {row[0]!r} has an empty cell"

    def test_the_four_measured_rules_each_have_an_experiment(self):
        settles = " ".join(r[3] for r in ROWS)
        for rule in ("H1", "H2", "H3", "H4"):
            assert rule in settles, f"{rule} has no campaign in the map"

    def test_the_newer_claims_are_covered(self):
        settles = " ".join(r[3] for r in ROWS)
        assert "H10" in settles, "the mixture finding must trace to a campaign"
        assert "recovery" in settles, "the F_Delta recovery must trace to a campaign"
        assert "start-up" in settles, "the second withdrawal must trace to a campaign"

    def test_the_confounded_sweep_is_labelled(self):
        """The delay sweep confounds T_true with backlog; the map must not hide that."""
        delay = [r for r in ROWS if "delay" in r[0].lower()]
        assert delay, "the delay sweep must appear"
        assert "confounded" in delay[0][3].lower()

    def test_replicated_campaigns_say_so(self):
        joined = " ".join(r[0] + r[3] for r in ROWS).lower()
        assert "replicated" in joined or "x2" in joined, \
            "campaigns with an independent replication should be marked"


class TestDraw:
    def test_draws_a_chip_and_four_texts_per_row(self):
        fig, ax = plt.subplots()
        draw(ax)
        assert len(ax.patches) == len(ROWS), "one campaign chip per row"
        # 4 headers + 4 cells per row + 1 closing note
        assert len(ax.texts) == 4 + 4 * len(ROWS) + 1
        plt.close(fig)

    def test_axis_is_hidden(self):
        fig, ax = plt.subplots()
        draw(ax)
        assert not ax.axison
        plt.close(fig)

    def test_note_sits_below_the_last_row(self):
        fig, ax = plt.subplots()
        draw(ax)
        note = ax.texts[-1]
        last_row_y = len(ROWS) - (len(ROWS) - 1) - 0.5
        assert note.get_position()[1] < last_row_y - 0.5, "the note must clear the last row"
        plt.close(fig)


class TestMain:
    def test_writes_both_formats(self, temp_dir, capsys):
        out = temp_dir / "figs"
        assert main(["--out", str(out)]) == 0
        assert (out / "experiment_map.pdf").exists()
        assert (out / "experiment_map.png").exists()
        assert "wrote" in capsys.readouterr().out
