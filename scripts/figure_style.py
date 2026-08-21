#!/usr/bin/env python3
"""
figure_style.py
One place where every figure in the paper agrees about fonts.

Why this file exists. Round 6 ran `pdffonts` over the built PDFs and found 17 Type 3 fonts in
the manuscript and 9 in the supplement -- every one of them from a figure, and every one of
them DejaVu Sans. Two separate problems hid behind that:

  Type 3 is matplotlib's default PDF font mode (`pdf.fonttype: 3`). Type 3 fonts embed glyphs
  as uninterpreted PostScript drawing operators. They rasterise poorly under magnification and
  they are the classic IEEE PDF eXpress rejection. Nothing in the figure code chose this; it is
  what you get by not choosing.

  DejaVu Sans is matplotlib's default family, and it is not on the list IEEE publishes for
  text inside graphics -- "Helvetica, Times New Roman, Arial, Cambria, Symbol".

Both are one-line settings, and the reason they survived six rounds is that they were one line
*per script*, in five scripts, none of which was looking. So the setting now lives here, the
five figure scripts import it before they draw anything, and a test asserts the property on the
built PDFs rather than on this file -- because what matters is the bytes IEEE receives, not our
intention to have set an rcParam.

Arial is chosen over Helvetica because Helvetica is not installed on the build machine and
matplotlib would silently fall through to DejaVu; the fallback chain below ends at DejaVu Sans
deliberately, so a machine with no listed font still builds, and the PDF test is what catches
it. Metrically-compatible substitutes come before the fallback so a Linux build lands on
Nimbus/Liberation rather than back on DejaVu.

Usage, before the first pyplot import that draws:

    import figure_style
    figure_style.apply()
"""
import matplotlib

# The IEEE list, in the order we prefer them, with metric-compatible substitutes for build
# machines that have neither Arial nor Helvetica installed.
IEEE_SANS = [
    "Arial", "Helvetica",
    "Liberation Sans", "Nimbus Sans", "FreeSans", "Arimo",
    "DejaVu Sans",
]

#: TrueType. The whole point of this module: anything but matplotlib's default of 3.
TRUETYPE = 42


def apply(rc=None):
    """Set the font policy. Idempotent, and safe to call from every script.

    `rc` is for tests, which pass a dict to check what would be set without touching the
    global state of the process they run in.
    """
    target = matplotlib.rcParams if rc is None else rc
    target["pdf.fonttype"] = TRUETYPE
    target["ps.fonttype"] = TRUETYPE
    target["font.family"] = "sans-serif"
    target["font.sans-serif"] = list(IEEE_SANS)
    # Maths inside a figure label goes through a separate resolver. `stix`/`stixsans` are
    # TrueType and would satisfy the font rule, but they map italic latin to the Unicode
    # mathematical-alphanumeric block, so `$t_{\mathrm{sched}}$` stops extracting as "tsched"
    # and comes out as U+1D635.... A figure label that cannot be searched or read aloud is a
    # worse outcome than the one we were fixing, so maths is set to the same family as the
    # text and extracts as ordinary letters.
    target["mathtext.fontset"] = "custom"
    for slot, suffix in (("rm", ""), ("it", ":italic"), ("bf", ":bold"),
                         ("sf", ""), ("tt", "")):
        target["mathtext.%s" % slot] = "%s%s" % (IEEE_SANS[0], suffix)
    target["mathtext.default"] = "it"
    return target


def resolved_family():
    """The family matplotlib will actually use, after the fallback chain resolves.

    Reported by the figure scripts so a build on a machine missing every listed font says so
    out loud instead of quietly producing DejaVu.
    """
    import matplotlib.font_manager as fm
    installed = {f.name for f in fm.fontManager.ttflist}
    for name in IEEE_SANS:
        if name in installed:
            return name
    return None


if __name__ == "__main__":
    apply()
    print("pdf.fonttype = %s" % matplotlib.rcParams["pdf.fonttype"])
    print("resolved family = %s" % resolved_family())
