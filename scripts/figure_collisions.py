"""Layout defects that every font, glyph and Type-3 gate passes.

Three rounds of review have now found a figure defect that no automated check could see,
because all of them ask about *content* -- which font, which glyph, which family -- and each
defect was about *geometry*:

- round 12: Figure 5(b)'s ``32 KB`` label struck through by the half-cell rule;
- round 13: ``window_sweep``'s minor-tick formatter printing ``180`` under ``2 x 10^2``;
- round 15: a density curve drawn through a two-line annotation, an arrow drawn through a
  bar's percentage label, three grid lines drawn through their own right-hand labels, and a
  scatter marker sliced in half by the x-axis spine.

Each was repaired where it was found, and each repair was shaped like its instance. The class
is wider than any of them: *ink lands where a reader needs to see something else*. This module
gates the class, on the only evidence that settles it -- the rendered pixels.

Two checks, both run from the ``_save`` of every figure script, so a new figure cannot be
added without being subject to them.

**Text struck by ink.** The figure is rasterised with every text object hidden, and each
label's own rectangle is then read out of that raster. Ink found there is ink the reader must
read through. Light fills behind a label -- a shaded region, a faint gridline -- are not
damage; a curve, a rule or an arrow is.

Only the *core* of each label is read, not its full box. A box includes leading above the
capitals and the descender well below the baseline, and a design that flanks a rule with a
label above and a label below -- which is a good design -- puts that rule inside both boxes
while touching neither set of glyphs. Reading the middle band asks the question that matters,
which is whether the reader's eye has to separate a glyph from a stroke.

**Markers cut by a spine.** A scatter point drawn at the very edge of the axes is clipped by
the frame, and half a marker reads as a plotting error rather than as data. Marker extent is
in points and the axes are in pixels, so this is a question the data cannot answer.
"""

import io

import numpy as np

# A pixel darker than this (0 = black, 1 = white) counts as ink rather than as background.
# Gridlines here render at alpha 0.25 on white -- luminance about 0.85 -- and a shaded region
# at about 0.93; a 60%-grey curve lands near 0.4 and a coloured arrow lower still.
INK_LUMINANCE = 0.62

# Fraction of a label's core that may carry ink before the label counts as struck. A hairline
# grazing a corner is not a defect; a stroke crossing the glyphs is. A single thin rule drawn
# through a small label covers several percent of it.
MAX_INK_FRACTION = 0.012

# The share of the text box treated as glyph core. Vertically this drops the leading above the
# capitals and the descender well below the baseline; horizontally it drops the side bearings.
# 72% rather than 58%: cap height starts well inside a text box, so a narrower band excludes
# the very strokes a rule crossing the capitals would hit -- which is how an axes frame came to
# be drawn through the top of a two-line annotation with the check reporting it clean.
CORE_HEIGHT = 0.72
# 96% horizontally. The vertical inset earns its keep -- it is what stops a rule
# flanked by a label above and a label below from reading as a strike on either.
# There is no equivalent design horizontally, and an 88% band put a frame touching
# the last glyph of an annotation outside the region being read.
CORE_WIDTH = 0.96

# How much of the smaller of two labels may be covered by the other before they count as
# printed over each other. Adjacent labels routinely share a hair of their boxes; a label
# printed through another shares most of one.
MIN_TEXT_OVERLAP = 0.10

RENDER_DPI = 200


class FigureCollision(AssertionError):
    """A figure has ink where a reader needs to see something else."""


def _raster(fig, dpi):
    """The figure as a luminance array, without touching the file the caller is writing.

    The render is pinned rather than inherited. `bbox_inches=None` does not mean "no tight
    box", it means "ask rcParams", and a module elsewhere in this repository sets
    `savefig.bbox = 'tight'` at import time. Under that setting the raster is cropped, its
    geometry stops matching the window extents the boxes were measured in, and the check
    quietly finds nothing at all.
    """
    import matplotlib

    buf = io.BytesIO()
    with matplotlib.rc_context({"savefig.bbox": None, "savefig.pad_inches": 0.0,
                                "savefig.transparent": False}):
        fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
    buf.seek(0)
    from PIL import Image
    with Image.open(buf) as im:
        arr = np.asarray(im.convert("L"), dtype=np.float32) / 255.0
    return arr


def _stale_tick_labels(fig):
    """Tick labels for ticks outside the current view, which exist but are never drawn.

    A locator produces a tick for every candidate position and the Text objects persist with
    stale coordinates, so several can pile up in one spot off the end of an axis. Asking the
    page whether they were drawn does not work: their boxes overlap labels that *were* drawn,
    and they take the credit. The axis knows the answer exactly -- the tick is in view or it
    is not.
    """
    stale = set()
    for ax in fig.axes:
        if not getattr(ax, "axison", True):
            # A schematic panel turns its frame off. The tick Text objects survive, carrying
            # positions from the layout, and nothing draws them -- but they can sit squarely
            # on a neighbouring panel's title, where asking the page whether they were drawn
            # answers yes on the strength of the title's own ink.
            for axis in (ax.xaxis, ax.yaxis):
                for tick in list(axis.get_major_ticks()) + list(axis.get_minor_ticks()):
                    for lab in (getattr(tick, "label1", None), getattr(tick, "label2", None)):
                        if lab is not None:
                            stale.add(id(lab))
                stale.add(id(axis.get_label()))
            continue
        for axis in (ax.xaxis, ax.yaxis):
            try:
                lo, hi = sorted(axis.get_view_interval())
                ticks = list(axis.get_major_ticks()) + list(axis.get_minor_ticks())
            except Exception:
                continue
            span = (hi - lo) or 1.0
            for tick in ticks:
                loc = getattr(tick, "get_loc", lambda: None)()
                if loc is None:
                    continue
                if not (lo - 1e-9 * abs(span) <= loc <= hi + 1e-9 * abs(span)):
                    for lab in (getattr(tick, "label1", None), getattr(tick, "label2", None)):
                        if lab is not None:
                            stale.add(id(lab))
    return stale


def _visible_texts(fig):
    from matplotlib.text import Text
    stale = _stale_tick_labels(fig)
    out = []
    for obj in fig.findobj(Text):
        if not obj.get_visible():
            continue
        if not (obj.get_text() or "").strip():
            continue
        if id(obj) in stale:
            continue
        out.append(obj)
    return out


def _glyph_box(text, renderer):
    """The rectangle the glyphs occupy -- not the annotation's, which includes its arrow.

    Annotation overrides get_window_extent to return the union of the text and the leader it
    draws. Measuring ink in that box asks whether a label's own arrow is ink, and the answer
    is always yes, so every annotated label reports itself as struck. The base class method
    gives the glyphs alone.
    """
    from matplotlib.text import Text
    return Text.get_window_extent(text, renderer=renderer)


def _drawn_boxes(fig, dpi=RENDER_DPI):
    """(text, box, ink-only raster, scale) for every label actually printed on the page.

    A locator makes a Text for every tick it produces, in view or not, so a figure carries
    labels that exist but are never drawn -- and several of them can share a position off the
    edge of the axes. Comparing the page with and without glyphs is what distinguishes a
    label a reader can see from one only the object graph knows about.
    """
    texts = _visible_texts(fig)
    if not texts:
        return [], None, 1.0

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    boxes = []
    for t in texts:
        try:
            bb = _glyph_box(t, renderer)
        except Exception:
            continue
        if bb.width > 0 and bb.height > 0:
            boxes.append((t, bb))

    full = _raster(fig, dpi)

    engine = fig.get_layout_engine()
    positions = [(ax, ax.get_position().frozen()) for ax in fig.axes]
    states = []
    for t, _ in boxes:
        # Painted transparent rather than hidden or emptied: an Annotation's arrow is anchored
        # to its text box, so emptying the string collapses the arrow the check looks for, and
        # hiding the object removes it outright. Colour takes the glyphs off the page and
        # leaves every box, endpoint and layout decision untouched -- and unlike an emptied
        # string it survives the Formatter that rewrites tick labels.
        states.append((t, t.get_color()))
        t.set_color((0.0, 0.0, 0.0, 0.0))
    try:
        fig.set_layout_engine("none")
        for ax, pos in positions:
            ax.set_position(pos)
        inkless = _raster(fig, dpi)
    finally:
        for obj, was in states:
            obj.set_color(was)
        for ax, pos in positions:
            ax.set_position(pos)
        if engine is not None:
            fig.set_layout_engine(engine)

    scale = dpi / float(fig.dpi)
    drawn = []
    for t, bb in boxes:
        sl = _slice(bb, fig, scale, inkless.shape)
        if sl is None:
            continue
        y0, y1, x0, x1 = sl
        if not (full[y0:y1, x0:x1] != inkless[y0:y1, x0:x1]).any():
            continue          # nothing changed when the glyphs went: not printed here
        drawn.append((t, bb))
    return drawn, inkless, scale


def _slice(bb, fig, scale, shape):
    """The raster window for a text's core, or None if it lies off the canvas."""
    import numpy as _np
    cx0, cy0, cx1, cy1 = _core(bb)
    height_px, width_px = shape
    x0 = max(0, int(_np.floor(cx0 * scale)))
    x1 = min(width_px, int(_np.ceil(cx1 * scale)))
    y0 = max(0, int(_np.floor((fig.bbox.height - cy1) * scale)))
    y1 = min(height_px, int(_np.ceil((fig.bbox.height - cy0) * scale)))
    if x1 <= x0 or y1 <= y0:
        return None
    return y0, y1, x0, x1


def text_struck_by_ink(fig, dpi=RENDER_DPI, max_fraction=MAX_INK_FRACTION):
    """Labels with ink drawn through them, worst first.

    Removing the glyphs and re-rendering is what separates a label's own strokes from
    everything drawn under them; differencing two rasters would only rediscover the glyphs.
    """
    drawn, inkless, scale = _drawn_boxes(fig, dpi)
    if not drawn:
        return []
    found = []
    for t, bb in drawn:
        # `_drawn_boxes` has already sliced each of these against the same raster and kept
        # only the ones that landed on the canvas with a non-empty patch, so the slice here
        # cannot be None and the patch cannot be empty. Guards for both stood here and could
        # not be reached; they are gone rather than excused.
        y0, y1, x0, x1 = _slice(bb, fig, scale, inkless.shape)
        patch = inkless[y0:y1, x0:x1]
        fraction = float((patch < INK_LUMINANCE).mean())
        if fraction > max_fraction:
            found.append({
                "text": " ".join((t.get_text() or "").split())[:60],
                "fraction": round(fraction, 4),
                "box": (round(bb.x0, 1), round(bb.y0, 1), round(bb.x1, 1), round(bb.y1, 1)),
            })
    found.sort(key=lambda d: -d["fraction"])
    return found


def _core(bb):
    """The glyph core of a text box: the rectangle a reader's eye actually needs clear."""
    dx = bb.width * (1.0 - CORE_WIDTH) / 2.0
    dy = bb.height * (1.0 - CORE_HEIGHT) / 2.0
    return bb.x0 + dx, bb.y0 + dy, bb.x1 - dx, bb.y1 - dy


def texts_overlapping(fig, min_overlap=MIN_TEXT_OVERLAP):
    """Pairs of labels printed over each other, worst first.

    Round 13's defect was of this kind and not of the ink kind: set_xticks replaces a log
    axis's major ticks and leaves the minor decade formatter running, so two tick labels
    printed in the same place. Neither is struck by anything drawn; they strike each other.
    """
    # Full glyph boxes here, not the cores the ink check uses. The core inset exists so that
    # a rule running between two stacked labels is not read as striking either of them; two
    # labels printed over each other have no such innocent reading, and insetting both boxes
    # lets a single-line label hide inside the interline gap of a two-line one.
    drawn, _, _ = _drawn_boxes(fig)
    boxes = [(t, (bb.x0, bb.y0, bb.x1, bb.y1)) for t, bb in drawn]

    found = []
    for i in range(len(boxes)):
        ta, (ax0, ay0, ax1, ay1) = boxes[i]
        area_a = (ax1 - ax0) * (ay1 - ay0)
        for j in range(i + 1, len(boxes)):
            tb, (bx0, by0, bx1, by1) = boxes[j]
            w = min(ax1, bx1) - max(ax0, bx0)
            h = min(ay1, by1) - max(ay0, by0)
            if w <= 0 or h <= 0:
                continue
            # Both boxes came from `_drawn_boxes`, which keeps only positive width and
            # height, so the smaller area is positive by construction.
            area_b = (bx1 - bx0) * (by1 - by0)
            share = (w * h) / min(area_a, area_b)
            if share > min_overlap:
                found.append({
                    "a": " ".join((ta.get_text() or "").split())[:40],
                    "b": " ".join((tb.get_text() or "").split())[:40],
                    "overlap": round(share, 3),
                })
    found.sort(key=lambda d: -d["overlap"])
    return found


def _marker_sets(ax, fig):
    """Every drawn marker on these axes, as (points, radius in pixels).

    Markers arrive two ways and only one of them is a collection: ax.scatter makes a
    PathCollection sized in points squared, ax.plot makes a Line2D sized in points. The
    figure with the clipped marker uses the second, so a check that reads only the first
    finds nothing and reports success.
    """
    out = []
    for coll in ax.collections:
        if not coll.get_visible():
            continue
        if not hasattr(coll, "get_sizes") or not hasattr(coll, "get_offsets"):
            continue  # error bars and shaded bands are line collections, not markers
        offsets, sizes = coll.get_offsets(), coll.get_sizes()
        if offsets is None or len(offsets) == 0 or sizes is None or len(sizes) == 0:
            continue
        out.append((offsets, float(np.sqrt(np.max(sizes))) / 2.0 * fig.dpi / 72.0))
    for line in ax.lines:
        if not line.get_visible() or line.get_marker() in ("", "None", None, " "):
            continue
        data = line.get_xydata()
        if data is None or len(data) == 0:
            continue  # legend proxies are plotted empty
        out.append((data, float(line.get_markersize()) / 2.0 * fig.dpi / 72.0))
    return out


def markers_clipped_by_axes(fig, tolerance_frac=0.35):
    """Scatter points whose marker is cut by the axes frame.

    A point exactly on a limit is drawn half outside and clipped to half a marker, which
    reads as a rendering fault. The test is in pixels because marker radius is in points:
    whether a point collides with the spine depends on the figure's size, not on the numbers.
    """
    fig.canvas.draw()
    out = []
    for ax in fig.axes:
        if not ax.get_visible():
            continue
        bb = ax.get_window_extent()
        for offsets, radius_px in _marker_sets(ax, fig):
            pts = ax.transData.transform(np.asarray(offsets, dtype=float))
            for (px, py), (ux, uy) in zip(pts, np.asarray(offsets, dtype=float)):
                if not (np.isfinite(px) and np.isfinite(py)):
                    continue
                over = max(
                    bb.x0 - (px - radius_px), (px + radius_px) - bb.x1,
                    bb.y0 - (py - radius_px), (py + radius_px) - bb.y1,
                )
                if over > tolerance_frac * radius_px:
                    out.append({
                        "point": (float(ux), float(uy)),
                        "overhang_px": round(float(over), 2),
                        "radius_px": round(radius_px, 2),
                    })
    return out


def report(fig):
    """All three checks as data, for callers that want to look rather than fail."""
    return {"struck": text_struck_by_ink(fig),
            "overlapping": texts_overlapping(fig),
            "clipped": markers_clipped_by_axes(fig)}


def check(fig, stem=""):
    """Both checks, raising with everything needed to find the defect on the page."""
    found = report(fig)
    if not any(found.values()):
        return
    lines = ["%s: layout collisions" % (stem or "figure")]
    for d in found["struck"]:
        lines.append("  text struck by ink: %r -- %.1f%% of its core carries drawn ink"
                     % (d["text"], 100 * d["fraction"]))
    for d in found["overlapping"]:
        lines.append("  labels printed over each other: %r and %r share %.0f%% of the smaller"
                     % (d["a"], d["b"], 100 * d["overlap"]))
    for d in found["clipped"]:
        lines.append("  marker clipped by axes: point %s overhangs the frame by %.1f px "
                     "(marker radius %.1f px)"
                     % (d["point"], d["overhang_px"], d["radius_px"]))
    raise FigureCollision("\n".join(lines))
