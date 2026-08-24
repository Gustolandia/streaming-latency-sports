"""Type size inside a figure, measured as the reader receives it.

Sixteen rounds of review checked which typeface a figure used, whether its glyphs were
mapped, whether it embedded Type 3, and whether anything collided. None asked how big the
letters were. They were small: every figure in the paper printed below IEEE's minimum, and
one printed at 2.7 pt against 9.5 pt body text, because figures authored five and seven
inches wide were being included in a 2.87-inch box.

The arithmetic is the whole problem and it is invisible in both halves of it. Nothing in the
figure script knows the include width; nothing in the manuscript knows the font sizes. This
module is where the two meet.

**The rule.** A figure's printed type size is its authored size times the ratio of the width
it is included at to the width it was drawn at. Every string a reader has to read must land
at ``MIN_PRINT_PT`` or above.

**The width comes from the manuscript, not from a table someone maintains.** ``print_widths``
parses the ``\\includegraphics`` directives out of the .tex sources, so a figure moved between
a column and a full-width float is measured against where it actually ends up.
"""

import os
import re

#: IEEE's graphics guidance asks for figure text of roughly 8-10 pt, and TC requires figures
#: to be "reasonably sized (readable)". Body text here is 9.5 pt.
MIN_PRINT_PT = 8.0

#: IEEEtran, 10pt journal, US letter. One column and the full text block.
COLUMN_WIDTH_IN = 3.5
TEXT_WIDTH_IN = 7.16

#: Widths a one-column supplement uses; its \columnwidth is the whole text block.
ONECOLUMN_WIDTH_IN = 6.5

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FigureTooSmall(AssertionError):
    """A figure prints type the reader cannot reasonably be asked to read."""


def _width_of(expr, onecolumn):
    """Inches for a LaTeX width expression such as ``0.82\\columnwidth``."""
    m = re.match(r"([\d.]*)\s*\\(columnwidth|textwidth|linewidth)", expr.strip())
    if not m:
        return None
    factor = float(m.group(1)) if m.group(1) else 1.0
    unit = m.group(2)
    if onecolumn:
        base = ONECOLUMN_WIDTH_IN
    elif unit == "textwidth":
        base = TEXT_WIDTH_IN
    else:
        base = COLUMN_WIDTH_IN
    return factor * base


def print_widths(tex_paths=("paper.tex", "supplement.tex")):
    """{figure stem: printed width in inches}, read from the manuscript sources.

    ``\\columnwidth`` is a column everywhere. LaTeX does *not* redefine it inside a starred
    float -- this module assumed it did for one round, which let three figures print at a
    column width, type near 3.8 pt, while the check reported them compliant. Measured off the
    printed page they were 3.37 in wide, not 7.16. ``\\linewidth`` is the one that follows the
    enclosing box, so only that is resolved against the environment.
    """
    out = {}
    for name in tex_paths:
        path = name if os.path.isabs(name) else os.path.join(REPO, name)
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        onecolumn = "onecolumn" in src.split("\\begin{document}")[0]
        for env in re.finditer(
                r"\\begin\{(figure\*?)\}(.*?)\\end\{figure\*?\}", src, re.S):
            starred = env.group(1).endswith("*")
            for inc in re.finditer(r"\\includegraphics\[([^\]]*)\]\{([^}]*)\}", env.group(2)):
                opts, target = inc.group(1), inc.group(2)
                stem = os.path.splitext(os.path.basename(target))[0]
                m = re.search(r"width=([^,\]]+)", opts)
                if not m:
                    continue
                expr = m.group(1)
                if starred and "linewidth" in expr:
                    expr = expr.replace("linewidth", "textwidth")
                width = _width_of(expr, onecolumn)
                if width is not None:
                    out[stem] = width
    return out


def printed_sizes(fig, printed_in):
    """Every distinct type size in the figure, as printed, smallest first."""
    from matplotlib.text import Text
    fig.canvas.draw()
    authored_in = fig.get_size_inches()[0]
    if not authored_in:
        return []
    scale = printed_in / authored_in
    sizes = {round(t.get_fontsize() * scale, 2)
             for t in fig.findobj(Text)
             if t.get_visible() and (t.get_text() or "").strip()}
    return sorted(sizes)


def offenders(fig, printed_in, minimum=MIN_PRINT_PT):
    """The strings that print below the minimum, with their sizes."""
    from matplotlib.text import Text
    fig.canvas.draw()
    authored_in = fig.get_size_inches()[0]
    if not authored_in:
        return []
    scale = printed_in / authored_in
    bad = []
    for t in fig.findobj(Text):
        if not t.get_visible() or not (t.get_text() or "").strip():
            continue
        size = t.get_fontsize() * scale
        if size < minimum - 1e-9:
            bad.append({"text": " ".join(t.get_text().split())[:40],
                        "pt": round(size, 2)})
    bad.sort(key=lambda d: d["pt"])
    return bad


def check(fig, stem, widths=None, minimum=MIN_PRINT_PT):
    """Raise unless every label in this figure prints at or above the minimum.

    A figure the manuscript does not include is not checked: it has no printed width, and
    guessing one would either invent a failure or hide a real one.
    """
    widths = print_widths() if widths is None else widths
    if stem not in widths:
        return
    bad = offenders(fig, widths[stem], minimum)
    if not bad:
        return
    lines = ["%s prints type below %.1f pt (included at %.2f in, drawn at %.2f in):"
             % (stem, minimum, widths[stem], fig.get_size_inches()[0])]
    for d in bad[:8]:
        lines.append("    %5.1f pt  %r" % (d["pt"], d["text"]))
    if len(bad) > 8:
        lines.append("    ... and %d more" % (len(bad) - 8))
    raise FigureTooSmall("\n".join(lines))
