"""Draw what ``figure_collisions`` is complaining about.

A gate that says "this label is 6.2% covered" is hard to act on; the useful artifact is the
picture it saw. This renders each figure's ink-only raster -- the figure with its glyphs
painted transparent -- and outlines the core of every label the gate flagged, so the stroke
crossing it is visible at a glance.

Run it whenever the collision gate fails, and when adding a figure, to see the check's view
of it:

    python scripts/show_figure_collisions.py --out /tmp/collisions
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")

import figure_collisions as fc  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def _safe(s):
    """Console-safe: these labels carry minus signs and times signs that cp1252 refuses."""
    return repr(s).encode("ascii", "backslashreplace").decode("ascii")


def annotate_raster(fig, findings, path):
    """The ink-only raster with each flagged label's core outlined."""
    from PIL import Image, ImageDraw

    texts = fc._visible_texts(fig)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    boxes = {}
    for t in texts:
        try:
            boxes[" ".join((t.get_text() or "").split())[:60]] = fc._glyph_box(t, renderer)
        except Exception:
            continue

    states = [(t, t.get_color()) for t in texts]
    for t, _ in states:
        t.set_color((0.0, 0.0, 0.0, 0.0))
    try:
        arr = fc._raster(fig, fc.RENDER_DPI)
    finally:
        for t, was in states:
            t.set_color(was)

    im = Image.fromarray((arr * 255).astype("uint8")).convert("RGB")
    draw = ImageDraw.Draw(im)
    scale = fc.RENDER_DPI / float(fig.dpi)
    for found in findings:
        bb = boxes.get(found["text"])
        if bb is None:
            continue
        dx = bb.width * (1.0 - fc.CORE_WIDTH) / 2.0
        dy = bb.height * (1.0 - fc.CORE_HEIGHT) / 2.0
        draw.rectangle(
            [(bb.x0 + dx) * scale, (fig.bbox.height - bb.y1 + dy) * scale,
             (bb.x1 - dx) * scale, (fig.bbox.height - bb.y0 - dy) * scale],
            outline=(220, 20, 20))
    im.save(path)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="build/collisions")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    seen = []

    def inspect(fig, stem):
        found = fc.report(fig)
        if found["struck"]:
            annotate_raster(fig, found["struck"], out / ("%s.png" % stem))
        seen.append((stem, found))
        plt.close(fig)

    import make_paper_figures as mpf
    import make_result_figures as mrf

    # Both modules get their _save replaced so the figures can be inspected instead of
    # written. Putting them back is not tidiness: this process may go on to build figures for
    # real, and a module left holding an inspector silently stops saving anything. The suite
    # has lost a round to exactly this class of leak before.
    saved = [(mrf, mrf._save), (mpf, mpf._save)]
    try:
        mrf._save = lambda fig, out_dir, stem, **kw: (inspect(fig, stem), out / stem)[1]
        for build in (mrf.build_deletion, mrf.build_spectrum, mrf.build_grid,
                      mrf.build_mechanism, mrf.build_ttrue, mrf.build_payload):
            build(out)

        mpf._save = lambda fig, out_dir, stem, **kw: (inspect(fig, stem), [out / stem])[1]
        mpf.main(["--out", str(out)])
    finally:
        for module, original in saved:
            module._save = original

    bad = 0
    for stem, found in seen:
        # `probed` is the register of what each check examined, not a finding. Counting it as
        # one made this test always true and would have called every figure dirty.
        findings = {k: v for k, v in found.items() if k != "probed"}
        if not any(findings.values()):
            continue
        bad += 1
        print("%s" % stem)
        for d in findings["struck"]:
            print("    struck  %-44s %5.1f%%" % (_safe(d["text"]), 100 * d["fraction"]))
        for d in findings["overlapping"]:
            print("    overlap %-44s over %s (%.0f%%)"
                  % (_safe(d["a"]), _safe(d["b"]), 100 * d["overlap"]))
        for d in findings["clipped"]:
            print("    clipped point %-28s overhang %.1f px of r=%.1f px"
                  % (d["point"], d["overhang_px"], d["radius_px"]))
        # Everything else the report carries, printed generically. Three checks were added
        # after this tool was written and none of them was printed; a finding that counts
        # toward the verdict and never appears is worse than no tool at all.
        for kind in sorted(set(findings) - {"struck", "overlapping", "clipped"}):
            for d in findings[kind]:
                print("    %-7s %s" % (kind[:7], _safe(str(d))))
    print("\n%d of %d figures carry a collision; rasters in %s" % (bad, len(seen), out))
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
