"""Tests for scripts/figure_legibility.py - target >=95% branch coverage.

Sixteen rounds of figure checking asked which typeface, which glyph, which font type and
what collides. None asked how big. Every figure in the paper printed below IEEE's minimum and
one printed at 2.7 pt, because the arithmetic that decides printed size is split between two
files that never met: the figure script sets the point size and knows nothing about the
include width, and the manuscript sets the include width and knows nothing about the point
size.

So the tests are mostly about the join. A width parsed wrongly is worse than no check at all,
because it produces a number that looks authoritative: reading 0.82\\columnwidth as a full
column understates the shrink and passes a figure that is too small, and missing the
\\columnwidth-inside-figure* substitution overstates it and fails a figure that is fine.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import figure_legibility as fl  # noqa: E402


@pytest.fixture(autouse=True)
def _pinned_rc():
    with matplotlib.rc_context(matplotlib.rcParamsDefault):
        yield
    plt.close("all")


def _fig(width_in, sizes):
    fig, ax = plt.subplots(figsize=(width_in, 2.0))
    for i, s in enumerate(sizes):
        ax.text(0.1, 0.1 + 0.2 * i, "label %d" % i, fontsize=s)
    ax.set_xticks([])
    ax.set_yticks([])
    return fig


class TestWidthParsing:

    def test_a_fraction_of_a_column(self):
        assert fl._width_of(r"0.82\columnwidth", False) == pytest.approx(0.82 * 3.5)

    def test_a_bare_column(self):
        assert fl._width_of(r"\columnwidth", False) == pytest.approx(3.5)

    def test_the_text_block_is_wider_than_a_column(self):
        assert fl._width_of(r"\textwidth", False) == pytest.approx(7.16)

    def test_linewidth_reads_as_a_column(self):
        assert fl._width_of(r"\linewidth", False) == pytest.approx(3.5)

    def test_a_one_column_document_has_no_narrow_column(self):
        """The supplement is onecolumn, where \\columnwidth is the whole text block."""
        assert fl._width_of(r"\columnwidth", True) == pytest.approx(6.5)

    def test_an_unparseable_width_returns_nothing_rather_than_guessing(self):
        assert fl._width_of("3in", False) is None
        assert fl._width_of("", False) is None


class TestPrintWidths:

    def _tex(self, tmp_path, body, preamble=""):
        p = tmp_path / "doc.tex"
        p.write_text(preamble + "\\begin{document}\n" + body, encoding="utf-8")
        return str(p)

    def test_a_column_figure(self, tmp_path):
        tex = self._tex(tmp_path, r"""
\begin{figure}[t]
\includegraphics[width=0.82\columnwidth]{a/b/deletion.pdf}
\end{figure}
""")
        assert fl.print_widths((tex,))["deletion"] == pytest.approx(0.82 * 3.5)

    def test_columnwidth_is_a_column_even_inside_a_starred_float(self, tmp_path):
        r"""LaTeX does not redefine \columnwidth inside figure*.

        This module assumed it did for one round, which let three figures print at a column
        width -- type near 3.8 pt -- while the check called them compliant. Measured off the
        printed page: 3.37 in, not 7.16.
        """
        tex = self._tex(tmp_path, r"""
\begin{figure*}[t]
\includegraphics[width=\columnwidth]{a/b/narrow.pdf}
\end{figure*}
""")
        assert fl.print_widths((tex,))["narrow"] == pytest.approx(3.5)

    def test_textwidth_inside_a_starred_float_is_the_text_block(self, tmp_path):
        tex = self._tex(tmp_path, r"""
\begin{figure*}[t]
\includegraphics[width=\textwidth]{a/b/wide.pdf}
\end{figure*}
""")
        assert fl.print_widths((tex,))["wide"] == pytest.approx(7.16)

    def test_linewidth_inside_a_starred_float_follows_the_box(self, tmp_path):
        tex = self._tex(tmp_path, r"""
\begin{figure*}[t]
\includegraphics[width=\linewidth]{a/b/follows.pdf}
\end{figure*}
""")
        assert fl.print_widths((tex,))["follows"] == pytest.approx(7.16)

    def test_a_one_column_document_uses_its_own_width(self, tmp_path):
        tex = self._tex(tmp_path, r"""
\begin{figure}[t]
\includegraphics[width=\columnwidth]{a/b/supp.pdf}
\end{figure}
""", preamble="\\documentclass[10pt,journal,onecolumn]{IEEEtran}\n")
        assert fl.print_widths((tex,))["supp"] == pytest.approx(6.5)

    def test_an_include_outside_a_float_is_not_measured(self, tmp_path):
        tex = self._tex(tmp_path, r"\includegraphics[width=\columnwidth]{a/b/loose.pdf}")
        assert "loose" not in fl.print_widths((tex,))

    def test_an_include_without_a_width_is_skipped(self, tmp_path):
        tex = self._tex(tmp_path, r"""
\begin{figure}[t]
\includegraphics{a/b/nowidth.pdf}
\end{figure}
""")
        assert "nowidth" not in fl.print_widths((tex,))

    def test_an_unparseable_width_is_skipped(self, tmp_path):
        tex = self._tex(tmp_path, r"""
\begin{figure}[t]
\includegraphics[width=5in]{a/b/absolute.pdf}
\end{figure}
""")
        assert "absolute" not in fl.print_widths((tex,))

    def test_a_missing_source_is_not_an_error(self, tmp_path):
        assert fl.print_widths((str(tmp_path / "absent.tex"),)) == {}


class TestPrintedSizes:

    def test_shrinking_a_figure_shrinks_its_type(self):
        fig = _fig(7.0, [8.0])
        assert fl.printed_sizes(fig, 3.5) == [pytest.approx(4.0)]

    def test_drawing_at_the_printed_width_leaves_type_alone(self):
        fig = _fig(3.5, [8.0])
        assert fl.printed_sizes(fig, 3.5) == [pytest.approx(8.0)]

    def test_enlarging_a_figure_enlarges_its_type(self):
        fig = _fig(3.5, [8.0])
        assert fl.printed_sizes(fig, 7.0) == [pytest.approx(16.0)]

    def test_a_zero_width_figure_reports_nothing(self):
        fig = _fig(3.5, [8.0])
        fig.set_size_inches(0, 2.0)
        assert fl.printed_sizes(fig, 3.5) == []


class TestOffenders:

    def test_type_below_the_floor_is_named_with_its_size(self):
        fig = _fig(7.0, [8.0])
        bad = fl.offenders(fig, 3.5)
        assert bad and bad[0]["pt"] == pytest.approx(4.0)
        assert "label" in bad[0]["text"]

    def test_type_at_the_floor_passes(self):
        fig = _fig(3.5, [8.0])
        assert fl.offenders(fig, 3.5) == []

    def test_the_worst_offender_is_reported_first(self):
        fig = _fig(7.0, [8.0, 12.0, 6.0])
        bad = fl.offenders(fig, 3.5)
        assert [d["pt"] for d in bad] == sorted(d["pt"] for d in bad)

    def test_a_zero_width_figure_has_no_offenders(self):
        fig = _fig(3.5, [8.0])
        fig.set_size_inches(0, 2.0)
        assert fl.offenders(fig, 3.5) == []


class TestCheck:

    def test_a_figure_the_manuscript_does_not_include_is_not_judged(self):
        """No printed width means no claim either way; guessing one invents a verdict."""
        fig = _fig(7.0, [4.0])
        fl.check(fig, "not-in-any-document", widths={})

    def test_a_legible_figure_raises_nothing(self):
        fig = _fig(3.5, [9.0])
        fl.check(fig, "ok", widths={"ok": 3.5})

    def test_an_illegible_figure_raises_with_the_numbers_that_matter(self):
        fig = _fig(7.0, [8.0])
        with pytest.raises(fl.FigureTooSmall) as exc:
            fl.check(fig, "squeezed", widths={"squeezed": 3.5})
        message = str(exc.value)
        assert "squeezed" in message
        assert "4.0 pt" in message
        assert "3.50 in" in message and "7.00 in" in message

    def test_a_long_list_of_offenders_is_truncated(self):
        fig = _fig(7.0, [6.0 + 0.1 * i for i in range(12)])
        with pytest.raises(fl.FigureTooSmall, match="and \\d+ more"):
            fl.check(fig, "many", widths={"many": 3.5})


class TestEveryShippedFigure:
    """The manuscripts' own figures, at the widths the manuscripts include them at."""

    def test_no_figure_prints_below_the_floor(self):
        widths = fl.print_widths()
        assert widths, "no include directives parsed; the check would be vacuous"

        seen = []

        def look(fig, stem):
            if stem in widths:
                seen.append(stem)
                fl.check(fig, stem, widths=widths)
            plt.close(fig)

        import make_result_figures as mrf
        import make_paper_figures as mpf
        original_result, original_paper = mrf._save, mpf._save
        try:
            mrf._save = lambda fig, out_dir, stem, **kw: (look(fig, stem), out_dir)[1]
            mpf._save = lambda fig, out_dir, stem, **kw: (look(fig, stem), [out_dir])[1]
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                for build in (mrf.build_deletion, mrf.build_spectrum, mrf.build_grid,
                              mrf.build_mechanism, mrf.build_ttrue, mrf.build_payload):
                    build(Path(tmp))
                mpf.main(["--out", tmp])
        finally:
            mrf._save, mpf._save = original_result, original_paper
        assert len(seen) >= 7, "expected every included figure to be measured, saw %s" % seen


class TestAnInclusionWithNoWidth:

    def test_it_is_left_out_rather_than_guessed_at(self, tmp_path):
        r"""``\includegraphics[trim=...]{fig}`` prints at the figure's natural size.

        The gate converts an authored type size to a printed one using the width the document
        asks for. With no width there is nothing to convert, and assuming a column would
        report a size the page does not have -- in the direction that passes.
        """
        tex = tmp_path / "paper.tex"
        tex.write_text(
            "\\documentclass{IEEEtran}\n"
            "\\begin{document}\n"
            "\\begin{figure}\\includegraphics[trim=1 2 3 4]{sized_by_nothing}"
            "\\end{figure}\n"
            "\\begin{figure}\\includegraphics[width=\\columnwidth]{sized}"
            "\\end{figure}\n"
            "\\end{document}\n", encoding="utf-8")
        widths = fl.print_widths([str(tex)])
        assert "sized" in widths, "the fixture must contain one figure the gate can measure"
        assert "sized_by_nothing" not in widths
