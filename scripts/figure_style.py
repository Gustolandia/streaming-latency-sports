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
import os

import matplotlib

# The IEEE list, in the order we prefer them, with metric-compatible substitutes for build
# machines that have neither Arial nor Helvetica installed.
IEEE_SANS = [
    "Arial", "Helvetica",
    "Liberation Sans", "Nimbus Sans", "FreeSans", "Arimo",
    "DejaVu Sans",
]

#: Text metrics, pinned to matplotlib's defaults so that a figure does not depend on what
#: else the process has imported. `--font-scale` multiplies these afterwards, by design.
DEFAULT_METRICS = {
    "font.size": 10.0,
    "axes.titlesize": "large",
    "axes.labelsize": "medium",
    "xtick.labelsize": "medium",
    "ytick.labelsize": "medium",
    "legend.fontsize": "medium",
    "figure.figsize": [6.4, 4.8],
    "figure.dpi": 100.0,
    "savefig.bbox": None,
    "savefig.pad_inches": 0.1,
}

#: TrueType. The whole point of this module: anything but matplotlib's default of 3.
TRUETYPE = 42

# The PDF creation stamp every figure carries, pinned so a rebuild is byte-identical to the
# build it repeats. Zero is the reproducible-builds convention: it claims no date at all
# rather than a plausible false one, and it prints as 1970, which no reader mistakes for the
# day a figure was made. See `apply()` and docs/infrastructure.md, lesson 1cu.
SOURCE_DATE_EPOCH = "0"


def apply(rc=None):
    """Set the font policy. Idempotent, and safe to call from every script.

    `rc` is for tests, which pass a dict to check what would be set without touching the
    global state of the process they run in.
    """
    target = matplotlib.rcParams if rc is None else rc
    if rc is None:
        # Byte-reproducible figures. Round 76 regenerated eight figures to change one and found
        # the other seven "modified" in git with identical text, identical pixels and identical
        # size -- six or seven differing bytes each, all inside `/CreationDate`. matplotlib
        # stamps the wall clock into every PDF it writes, so every build dirtied every figure,
        # and a reader of the history could not tell a figure that changed from one that was
        # merely rebuilt. In a repository whose claim is that every artifact is recomputed from
        # committed data, a diff that is noise is a diff nobody reads.
        #
        # SOURCE_DATE_EPOCH is the reproducible-builds convention and matplotlib's PDF backend
        # honours it. `setdefault`, so a CI or a packager can still pin a real date; the test
        # path (rc passed in) leaves the process environment alone, as it leaves rcParams alone.
        os.environ.setdefault("SOURCE_DATE_EPOCH", SOURCE_DATE_EPOCH)
    target["pdf.fonttype"] = TRUETYPE
    target["ps.fonttype"] = TRUETYPE
    target["font.family"] = "sans-serif"
    target["font.sans-serif"] = list(IEEE_SANS)
    # Size is as much a property of the artifact as family. Another script in this repository
    # sets font.size and a default figure size at import time, so in any process that has
    # imported it -- the test suite, or a driver that builds everything -- figures would come
    # out with different text metrics from the committed ones, and a layout check would be
    # measuring a different picture. These are matplotlib's own defaults, so a standalone
    # build is unchanged; pinning them makes a combined build agree with it.
    for key, value in DEFAULT_METRICS.items():
        target[key] = value
    # Maths inside a figure label goes through a separate resolver. `stix`/`stixsans` are
    # TrueType and would satisfy the font rule, but they map italic latin to the Unicode
    # mathematical-alphanumeric block, so `$t_{\mathrm{sched}}$` stops extracting as "tsched"
    # and comes out as U+1D635.... A figure label that cannot be searched or read aloud is a
    # worse outcome than the one we were fixing, so maths is set to the same family as the
    # text and extracts as ordinary letters.
    target["mathtext.fontset"] = "custom"
    # The family the text actually resolved to, not the first name on the list. Naming Arial
    # here sent the maths on a machine without Arial (the Ubuntu CI runner) to DejaVu Sans, while
    # the text beside it could be set in a metric-compatible substitute; the wider maths then
    # collided with its neighbours in the layout gate, on CI only. Where Arial is installed this
    # is Arial, exactly as before.
    family = resolved_family() or IEEE_SANS[-1]
    for slot, suffix in (("rm", ""), ("it", ":italic"), ("bf", ":bold"),
                         ("sf", ""), ("tt", "")):
        target["mathtext.%s" % slot] = "%s%s" % (family, suffix)
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


if __name__ == "__main__":  # pragma: no cover - a hand-run report on the two functions below
    apply()
    print("pdf.fonttype = %s" % matplotlib.rcParams["pdf.fonttype"])
    print("resolved family = %s" % resolved_family())
