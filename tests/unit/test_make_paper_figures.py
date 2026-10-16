"""Tests for scripts/make_paper_figures.py - target 100% branch coverage."""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from make_paper_figures import (  # noqa: E402
    condemned_at,
    plot_pipeline,
    plot_workload,
    plot_concurrency,
    plot_integrity,
    plot_model,
    plot_network,
    _read,
    _save,
    main,
)

INTEGRITY_COLS = ["run_id", "max_neg_fraction", "median_transport_ms",
                  "median_schedlag_ms", "median_output_ms"]


@pytest.fixture
def ax():
    fig, a = plt.subplots()
    yield a
    plt.close(fig)


@pytest.fixture
def axes_pair():
    fig, a = plt.subplots(1, 2)
    yield a
    plt.close(fig)


def _profiles(n=50):
    """Shaped like the corpus's profiles, bell-shaped about 0.41 events/s and 6.6x: a flat world
    fills every corner of the histograms, where the real one leaves room for their legends, and
    figure_collisions.data_under_legends (15 Oct 2026) holds the legends to that room."""
    from statistics import NormalDist
    z = [NormalDist().inv_cdf((i + 0.5) / n) for i in range(n)]
    return pd.DataFrame({
        "mean_rate_evs": [0.41 + 0.05 * v for v in z],
        "burstiness": [6.6 + 1.0 * v for v in z],
    })


def _slots():
    return pd.DataFrame({"n_matches": [1] * 30 + [2] * 8 + [5] * 3 + [12]})


def _timeline():
    return pd.DataFrame({"in_play": [0] * 10 + [1] * 20 + [5] * 6 + [12] * 2 + [21]})


def _integrity(fracs=(0.0, 0.0005, 0.004, 0.03, 0.2), neg_median=False):
    rows = []
    for i, f in enumerate(fracs):
        rows.append({
            "run_id": f"run{i}",
            "max_neg_fraction": f,
            "median_transport_ms": -1.0 if (neg_median and i == 0) else 1.0,
            "median_schedlag_ms": 2.0,
            "median_output_ms": 0.0,
        })
    return pd.DataFrame(rows, columns=INTEGRITY_COLS)


class TestCondemnedAt:
    """The sensitivity curve must mirror clock_integrity.py's rule exactly."""

    def test_counts_runs_above_the_threshold(self):
        df = _integrity()
        assert condemned_at(df, 0.01) == 2      # 0.03 and 0.2
        assert condemned_at(df, 0.10) == 1      # 0.2 only

    def test_zero_threshold_condemns_every_inverted_run(self):
        assert condemned_at(_integrity(), 0.0) == 4   # everything but the clean run

    def test_a_negative_component_median_condemns_regardless_of_rate(self):
        """A run with zero inversions but a negative median is still unusable."""
        df = _integrity(neg_median=True)
        assert condemned_at(df, 0.5) == 1

    def test_threshold_is_monotone(self):
        df = _integrity()
        counts = [condemned_at(df, t) for t in (0.0, 0.001, 0.01, 0.1, 1.0)]
        assert counts == sorted(counts, reverse=True)


class TestPlots:
    def test_pipeline_draws_boxes_and_intervals(self, ax):
        plot_pipeline(ax)
        # Three stage boxes of the same width; everything else drawn as a patch is an icon
        # (v4.1: an application window for producer and consumer, a queue for the broker).
        boxes = [p for p in ax.patches if abs(p.get_width() - 2.4) < 1e-9]
        assert len(boxes) == 3, "producer, broker, consumer"
        assert len(ax.patches) > 3, "each stage carries its icon"
        assert not ax.axison

    def test_workload_marks_the_medians(self, axes_pair):
        plot_workload(axes_pair, _profiles())
        for a in axes_pair:
            assert a.get_legend() is not None
            assert len(a.patches) > 0

    def test_concurrency_uses_log_counts(self, axes_pair):
        plot_concurrency(axes_pair, _slots(), _timeline())
        assert all(a.get_yscale() == "log" for a in axes_pair)
        assert "12" in axes_pair[0].get_title()

    def test_integrity_shows_histogram_and_sensitivity(self, axes_pair):
        plot_integrity(axes_pair, _integrity())
        hist_ax, sens_ax = axes_pair
        assert hist_ax.get_xscale() == "log"
        assert len(sens_ax.get_lines()) >= 1
        # Round 54: the title says what it counts. "Clean" meant a run that passes the
        # audit everywhere else in the submission, and this count is the stricter one --
        # runs with no negative span at all -- so the two read as a contradiction beside
        # panel (b)'s condemned share.
        assert "1 of 5 runs with no negative span" in hist_ax.get_title()

    def test_model_diagram_draws_both_panels(self, axes_pair):
        """Panel (a) is a schematic; panel (b) must show the H1 overlap argument."""
        plot_model(axes_pair)
        mech_ax, h1_ax = axes_pair
        assert not mech_ax.axison, "the mechanism panel is a schematic, not a plot"
        assert len(h1_ax.get_lines()) >= 1, "the Delta density"
        # Two threshold markers: one small T_true, one large.
        assert len([ln for ln in h1_ax.get_lines() if ln.get_linestyle() == "--"]) == 2
        assert len(h1_ax.collections) == 2, "the two shaded inversion regions"

    def test_network_marks_the_batching_fix(self, ax):
        plot_network(ax)
        assert ax.get_yscale() == "log"
        assert len(ax.collections) == 1, "the batched-ack star"
        assert len(ax.texts) == 1, "the annotation"

    def test_the_figures_use_the_manuscripts_names(self):
        """3 Oct (A10): D is the end-to-end latency, never the bare "delivery", and "tick" is the
        scheduler's alone, so the timestamp's step is a millisecond and its edges boundaries."""
        import make_paper_figures as mpf
        fig, axes = plt.subplots(3, 1)
        try:
            mpf.plot_mechanism(axes[0])
            mpf.plot_quantum_geometry(axes[1:])
            said = [" ".join(t.get_text().split()) for a in axes for t in a.texts]
            said += [a.get_title(loc="left") for a in axes] + [a.get_xlabel() for a in axes]
        finally:
            plt.close(fig)
        assert any(s.endswith("although the end-to-end latency $D>0$") for s in said)
        assert "ms boundary" in said and "next boundary" in said
        assert any(s.startswith("(a) One end-to-end latency of") for s in said)
        assert "phase of the publish instant within one millisecond" in said
        assert not [s for s in said if "tick" in s]


class TestTheSystemPanel:
    """Fig. 1 (a) since 4 Oct 2026: where everything runs, the two legs, and the quantities."""

    def test_it_names_the_machines_the_legs_and_what_each_latency_covers(self):
        import make_paper_figures as mpf
        fig, ax = plt.subplots()
        try:
            mpf.plot_system(ax)
            said = [" ".join(t.get_text().split()) for t in ax.texts]
        finally:
            plt.close(fig)
        # 15 Oct 2026, an internal review: "(the driver)" left the heading, since the text never
        # defines the word; the broker's order is Kafka's, and Redis often delivers first.
        for want in ("Client machine", "Broker machine", "Producer process",
                     "Consumer process", "leg 1: publish", "acknowledgment", "leg 2: deliver",
                     "$A$: leg 1, out and back", "$D$: leg 1, then leg 2", "read late",
                     r"a tool that reports $D$ in steps of $\tau$ and drops $\leq 0$",
                     "both processes read one clock", "(Redis: often 3 before 2)"):
            assert want in said, want
        assert not [s for s in said if "driver" in s]
        assert not ax.axison, "a schematic, not a plot"

    def test_a_tools_failures_sit_outside_our_consumers_box(self):
        """15 Oct 2026, a referee: inside the consumer process's box, "drops <= 0" and "reports D
        in steps of tau" read as properties of our own consumer, which keeps every value. They
        are a tool's, so they sit under its name outside the box; the late reading, which our
        producer's I/O thread does, stays inside the producer's."""
        import make_paper_figures as mpf
        fig, ax = plt.subplots(figsize=(7.16, 1.56))
        try:
            mpf.plot_system(ax)
            fig.canvas.draw()
            inv = ax.transData.inverted()

            def extent(text):
                bb = matplotlib.text.Text.get_window_extent(text, fig.canvas.get_renderer())
                (x0, y0), (x1, y1) = inv.transform([[bb.x0, bb.y0], [bb.x1, bb.y1]])
                return x0, y0, x1, y1

            def box(colour):
                (rect,) = [p for p in ax.patches if p.get_edgecolor()[:3]
                           == matplotlib.colors.to_rgb(colour)]
                return rect.get_x(), rect.get_y(), rect.get_x() + rect.get_width(), \
                    rect.get_y() + rect.get_height()

            def inside(text, frame):
                x0, y0, x1, y1 = extent(text)
                return frame[0] <= x0 and x1 <= frame[2] and frame[1] <= y0 and y1 <= frame[3]

            red = [t for t in ax.texts if t.get_color() == mpf.FAILURE_RED]
            note = [t for t in red if t.get_text().startswith("a tool that")]
            late = [t for t in red if t.get_text() == "read late"]
            consumer, producer = box(mpf.REDIS), box(mpf.KAFKA)
            assert len(note) == 1 and len(late) == 1 and len(red) == 2
            x0, y0, x1, y1 = extent(note[0])
            assert y1 < consumer[1], "the tool's note sits under the consumer's box, not in it"
            assert not any(inside(t, consumer) for t in red), "no red note in our consumer"
            assert inside(late[0], producer), "the late reading is our producer's"
        finally:
            plt.close(fig)

    def test_the_timeline_draws_every_quantity_of_the_model(self):
        """Panel (b) draws every timestamp and span of Section II-B, E and its parts included:
        the author asked for "the diagram for the whole system where all fundamental
        quantities are very clear" (4 Oct 2026). Before that day t_out and E were named in the
        text and drawn nowhere."""
        import make_paper_figures as mpf
        fig, ax = plt.subplots()
        try:
            mpf.plot_mechanism(ax)
            said = " | ".join(" ".join(t.get_text().split()) for t in ax.texts)
        finally:
            plt.close(fig)
        for want in (r"$t_{\mathrm{sched}}$", r"$t_{\mathrm{pub}}$", "publish delay",
                     r"t_{\mathrm{ack}}", r"t_{\mathrm{recv}}", r"t_{\mathrm{out}}",
                     r"$\delta_{\mathrm{ack}}$", r"$\delta_{\mathrm{recv}}$",
                     r"$D$: end-to-end latency", r"$A$: publish latency",
                     r"$E$: event-time latency", "processing-time latency",
                     r"$S=t_{\mathrm{recv}}-t_{\mathrm{ack}}<0$",
                     r"ack arrives, $t_{\mathrm{rx,ack}}$", r"message arrives, $t_{\mathrm{rx}}$",
                     r"$\delta_{\mathrm{ack}}$: the thread's delay",
                     "$m$"):
            assert want in said, want

    def test_the_process_box_is_named_on_the_title_row(self):
        """15 Oct 2026: the box's label moved to the panel's title row, a row less, and says
        that the consumer reads the same clock (an internal review)."""
        import make_paper_figures as mpf
        fig, ax = plt.subplots()
        try:
            mpf.plot_mechanism(ax)
            assert ax.get_title(loc="right") == \
                "producer process; the consumer reads the same clock"
            assert ax.get_ylim() == mpf.MECH_YLIM
        finally:
            plt.close(fig)


class TestTheSymbolsPrintLargeEnoughToTellApart:
    """15 Oct 2026, an internal review of the printed figures: at 8 pt the subscripts that tell
    t_rx,ack, t_ack, t_rx and t_recv apart printed at 5.6 pt. Every label carrying a subscript
    in Figs. 1 and 5 is set at MATH_PT, and the consumer's orange is a line colour only."""

    @staticmethod
    def _texts(draw, figsize=(7.16, 3.0)):
        fig, ax = plt.subplots(figsize=figsize)
        try:
            draw(ax)
            return [(t.get_text(), t.get_fontsize(), t.get_color()) for t in ax.texts
                    if t.get_text()]
        finally:
            plt.close(fig)

    @pytest.mark.parametrize("name", ["plot_system", "plot_mechanism", "plot_kernel_fix"])
    def test_every_subscripted_label_is_set_at_math_pt(self, name):
        import make_paper_figures as mpf
        texts = self._texts(getattr(mpf, name))
        scripted = [(s, size) for s, size, _c in texts if "$" in s and "_" in s]
        assert scripted, "the panel draws no subscripted label; the fixture is broken"
        assert all(size == mpf.MATH_PT for _s, size in scripted), scripted
        assert mpf.MATH_PT * 0.7 >= 6.5

    @pytest.mark.parametrize("name", ["plot_system", "plot_mechanism", "plot_kernel_fix"])
    def test_no_word_is_set_in_the_consumers_line_orange(self, name):
        import make_paper_figures as mpf
        colours = {matplotlib.colors.to_hex(c) for _s, _size, c in self._texts(
            getattr(mpf, name))}
        assert matplotlib.colors.to_hex(mpf.REDIS) not in colours
        assert matplotlib.colors.to_hex(mpf.CONSUMER_INK) in colours

    def test_the_margin_runs_from_the_acknowledgments_arrival_to_the_records(self):
        """15 Oct 2026, both referees: Equation 3 conditions on the margin m, the time the
        message still needs to reach the consumer once the acknowledgment has reached the
        producer, so the panel draws it between the two arrivals and nowhere else."""
        import make_paper_figures as mpf
        fig, ax = plt.subplots()
        try:
            mpf.plot_mechanism(ax)
            arrivals = sorted(float(line.get_xdata()[0]) for line in ax.get_lines()
                              if line.get_marker() == "|")
            brackets = [a for a in ax.texts if a.get_text() == "" and a.arrow_patch is not None
                        and a.arrow_patch.get_arrowstyle().__class__.__name__ == "CurveAB"
                        and a.arrow_patch.get_edgecolor()[:3] == (0.0, 0.0, 0.0)]
            spans = sorted((min(a.xyann[0], a.xy[0]), max(a.xyann[0], a.xy[0]))
                           for a in brackets)
            (label,) = [t for t in ax.texts if t.get_text() == "$m$"]
        finally:
            plt.close(fig)
        assert len(arrivals) == 2, "the acknowledgment's arrival and the record's"
        assert tuple(arrivals) in spans, (arrivals, spans)
        assert arrivals[0] < label.get_position()[0] < arrivals[1]


class TestTheKernelFigure:
    """Section VI's figure since 15 Oct 2026: the fix, drawn for the industry's reader, on Fig.
    1(b)'s four lanes since a referee asked the same day. The producer's I/O thread waits for a
    core before the kernel timestamps the message as it leaves; the acknowledgment and the
    record each arrive with the kernel's receive timestamp before a thread waits and reads the
    clock; the consumer's fetch request reaches the broker first. D over its three parts, so
    both waits on the message's path land visibly outside W."""

    @staticmethod
    def _drawn():
        """Everything the tests read off the figure, found by what it is, not by its index."""
        import make_paper_figures as mpf
        fig, ax = plt.subplots(figsize=mpf.KERNEL_FIG_IN)
        try:
            mpf.plot_kernel_fix(ax)
            lanes = dict((" ".join(t.get_text().split()), t.get_position()[1]) for t in ax.texts
                         if " ".join(t.get_text().split()) in (
                             "producer app thread", "client I/O thread", "broker",
                             "consumer app thread"))
            on = dict((y, name) for name, y in lanes.items())

            def colour_of(artist, colour):
                return matplotlib.colors.to_rgb(artist) == matplotlib.colors.to_rgb(colour)

            marks = [(line.get_marker(), line.get_color(), float(line.get_xdata()[0]),
                      float(line.get_ydata()[0])) for line in ax.get_lines()
                     if line.get_marker() not in ("None", "", None) and len(line.get_xdata())]
            arrows = [(a.arrow_patch.get_edgecolor()[:3], a.xyann, a.xy) for a in ax.texts
                      if a.get_text() == "" and a.arrow_patch is not None]
            said = [" ".join(t.get_text().split()) for t in ax.texts]
            found = {"lanes": lanes, "said": said, "axison": ax.axison,
                     "kernel": sorted((on[y], x) for m, c, x, y in marks
                                      if m == "|" and colour_of(c, mpf.KERNEL) and y in on),
                     "reads": dict((on[y], x) for m, c, x, y in marks if m == "o" and y in on),
                     "append": [x for m, c, x, y in marks if m == "D"],
                     "waits": sorted((on[a[1]], a[0], b[0]) for e, a, b in arrows
                                     if e == matplotlib.colors.to_rgb(mpf.FAILURE_RED)
                                     and a[1] == b[1] and a[1] in on),
                     "brackets": dict(), "fetch": [(a, b) for e, a, b in arrows
                                                   if e == matplotlib.colors.to_rgb(mpf.REDIS)]}
            # A bracket is level and off every lane; the red one off the lanes is the key's.
            for e, a, b in arrows:
                if a[1] == b[1] and a[1] not in on \
                        and e != matplotlib.colors.to_rgb(mpf.FAILURE_RED):
                    found["brackets"].setdefault(e, []).append((a[0], b[0], a[1]))
            return found, mpf
        finally:
            plt.close(fig)

    def test_it_draws_every_quantity_the_caption_names(self):
        found, _ = self._drawn()
        for want in ("producer app thread", "client I/O thread", "broker", "consumer app thread",
                     r"$t_{\mathrm{pub}}$", r"$t_{\mathrm{tx}}$", r"$t_{\mathrm{rx,ack}}$",
                     r"$t_{\mathrm{ack}}$", r"$t_{\mathrm{rx}}$", r"$t_{\mathrm{recv}}$",
                     r"$\delta_{\mathrm{ack}}$", r"$\delta_{\mathrm{recv}}$", "fetch", "$S_k$",
                     r"$D$: end-to-end latency", r"$H_{\mathrm{out}}$",
                     r"$W$: kernel-timed latency", r"$H_{\mathrm{in}}$", "kernel timestamp",
                     "a thread's delay", r"$\delta_{\mathrm{tx}}$"):
            assert want in found["said"], want
        # 15 Oct 2026, an internal review: the key names a thread's delay, which holds any wait
        # for a core, and every delay drawn is named, the I/O thread's before it writes too.
        assert "waits for a core" not in found["said"]
        assert not found["axison"], "a schematic, not a plot"

    def test_the_kernel_timestamps_each_packet_on_the_thread_lanes(self):
        """Fig. 1(b)'s lanes, each thread its own: the departure and the acknowledgment's arrival
        on the producer's I/O thread, the record's arrival on the consumer's thread, and the
        three clock reads where Fig. 1(b) has them."""
        found, _ = self._drawn()
        lanes = [name for name, _ in sorted(found["lanes"].items(), key=lambda kv: -kv[1])]
        assert lanes == ["producer app thread", "client I/O thread", "broker",
                         "consumer app thread"]
        assert [lane for lane, _ in found["kernel"]] == ["client I/O thread", "client I/O thread",
                                                         "consumer app thread"]
        assert sorted(found["reads"]) == ["client I/O thread", "consumer app thread",
                                          "producer app thread"]

    def test_both_waits_on_the_messages_path_lie_outside_w(self):
        """The point of the drawing. The producer's wait (on Kafka, the thread that writes the
        message out) ends where W starts, at t_tx, and the consumer's starts where W ends, at
        t_rx, so neither is inside W; the acknowledging thread's wait starts at t_rx,ack."""
        found, mpf = self._drawn()
        w0, w1, _ = min(found["brackets"][matplotlib.colors.to_rgb(mpf.KERNEL)],
                        key=lambda b: b[2])
        io = sorted(x for lane, x in found["kernel"] if lane == "client I/O thread")
        x_tx, x_rxack = io
        (x_rx,) = [x for lane, x in found["kernel"] if lane == "consumer app thread"]
        assert (w0, w1) == (x_tx, x_rx)
        assert len(found["waits"]) == 3, \
            "the producer's, the acknowledging thread's and the consumer's"
        send, ack = sorted(w for w in found["waits"] if w[0] == "client I/O thread")
        (recv,) = [w for w in found["waits"] if w[0] == "consumer app thread"]
        assert send[1] < send[2] == w0, "the producer's wait ends at t_tx, before W"
        assert w1 == recv[1] < recv[2], "the consumer's wait starts at t_rx, after W"
        assert ack[1] == x_rxack < ack[2] == found["reads"]["client I/O thread"]
        assert recv[2] == found["reads"]["consumer app thread"]

    def test_d_is_its_three_parts_and_s_k_runs_between_the_two_arrivals(self):
        found, mpf = self._drawn()
        t_pub = found["reads"]["producer app thread"]
        t_recv = found["reads"]["consumer app thread"]
        x_tx, x_rxack = sorted(x for lane, x in found["kernel"] if lane == "client I/O thread")
        (x_rx,) = [x for lane, x in found["kernel"] if lane == "consumer app thread"]
        brackets = found["brackets"]
        (d,) = brackets[matplotlib.colors.to_rgb(mpf.END_TO_END)]
        assert (d[0], d[1]) == (t_pub, t_recv)
        assert sorted((a, b) for a, b, _ in brackets[matplotlib.colors.to_rgb(mpf.GREY)]) == \
            [(t_pub, x_tx), (x_rx, t_recv)], "H_out and H_in"
        kernel = sorted(brackets[matplotlib.colors.to_rgb(mpf.KERNEL)], key=lambda b: -b[2])
        assert [(a, b) for a, b, _ in kernel] == [(x_rxack, x_rx), (x_tx, x_rx)], "S_k, then W"

    def test_the_fetch_request_reaches_the_broker_before_the_message(self):
        """A referee: one more arrow helps a tool author more than a paragraph. The request
        leaves the consumer before the message leaves the producer, so the message never waits
        in the broker for a request, which would put that wait inside W."""
        found, _ = self._drawn()
        (start, end), = found["fetch"]
        x_tx = min(x for lane, x in found["kernel"] if lane == "client I/O thread")
        (x_append,) = found["append"]
        assert start[1] == found["lanes"]["consumer app thread"]
        assert end[1] == found["lanes"]["broker"]
        assert start[0] < x_tx and end[0] < x_append


class TestHelpers:
    def test_read_returns_none_for_a_missing_file(self, temp_dir):
        assert _read(temp_dir / "nope.csv") is None

    def test_read_loads_an_existing_file(self, temp_dir):
        p = temp_dir / "x.csv"
        _profiles(3).to_csv(p, index=False)
        assert len(_read(p)) == 3

    def test_save_writes_both_formats(self, temp_dir):
        fig, _ = plt.subplots()
        written = _save(fig, temp_dir / "f", "s")
        assert [p.name for p in written] == ["s.png", "s.pdf"]
        assert all(p.stat().st_size > 0 for p in written)

    def test_a_close_crop_takes_the_margin_it_is_given(self, temp_dir):
        """15 Oct 2026: a figure drawn edge to edge at its printed width is cropped close, or the
        default tenth of an inch on each side makes the file wider than the page and it is
        shrunk on inclusion."""
        from pypdf import PdfReader

        def width(**kw):
            fig, ax = plt.subplots(figsize=(3.0, 1.0))
            ax.axis("off")
            ax.plot([0, 1], [0, 1])
            fig.subplots_adjust(left=0.0, right=1.0, top=1.0, bottom=0.0)
            (pdf,) = [p for p in _save(fig, temp_dir / "g", "c", check_layout=False, **kw)
                      if p.suffix == ".pdf"]
            return float(PdfReader(str(pdf)).pages[0].mediabox.width) / 72.0
        assert width() == pytest.approx(3.2, abs=0.01)
        assert width(pad_inches=0.02) == pytest.approx(3.04, abs=0.01)
        # 15 Oct 2026: saved whole, the file is the canvas, whatever savefig.bbox says.
        with matplotlib.rc_context({"savefig.bbox": "tight"}):
            assert width(whole=True) == pytest.approx(3.0, abs=0.001)


class TestMain:
    @staticmethod
    def _inputs(tmp):
        _profiles().to_csv(tmp / "profiles.csv", index=False)
        _slots().to_csv(tmp / "slots.csv", index=False)
        _timeline().to_csv(tmp / "timeline.csv", index=False)
        # Peaked as the corpus is, many runs at a few per cent and a thin tail on each side:
        # five runs of one each put every bar at the top of its panel, under any legend.
        _integrity(fracs=[0.0] * 10 + [0.05] * 8 + [0.06] * 6 + [0.001, 0.002, 0.2]).to_csv(
            tmp / "integrity.csv", index=False)
        return ["--profiles-csv", str(tmp / "profiles.csv"),
                "--slots-csv", str(tmp / "slots.csv"),
                "--timeline-csv", str(tmp / "timeline.csv"),
                "--integrity-csv", str(tmp / "integrity.csv"),
                "--out", str(tmp / "figs")]

    def test_renders_every_figure(self, temp_dir, capsys):
        assert main(self._inputs(temp_dir)) == 0
        out = temp_dir / "figs"
        for stem in ("pipeline_schematic", "measurement_model", "kernel_timestamps",
                     "workload_profile", "kickoff_concurrency", "integrity_audit",
                     "network_delay"):
            assert (out / f"{stem}.pdf").exists(), stem
        assert "skipped" not in capsys.readouterr().out

    def test_figs_1_and_5_are_never_shrunk_on_the_page(self, temp_dir):
        """The legibility gate reads the canvas; the page prints the cropped file. Until 15 Oct
        2026 Fig. 1's file was 7.29 in for the 7.16 in page, so its 8 pt type printed at 7.9 pt.
        Each file must be no wider than the width the paper includes it at."""
        import figure_legibility
        from pypdf import PdfReader
        assert main(self._inputs(temp_dir) + ["--only", "measurement_model"]) == 0
        assert main(self._inputs(temp_dir) + ["--only", "kernel_timestamps"]) == 0
        printed = figure_legibility.print_widths()
        for stem in ("measurement_model", "kernel_timestamps"):
            pdf = temp_dir / "figs" / ("%s.pdf" % stem)
            width = float(PdfReader(str(pdf)).pages[0].mediabox.width) / 72.0
            assert width <= printed[stem] + 1e-3, (stem, width, printed[stem])
            # 15 Oct 2026: saved whole at exactly the printed width, so that the page neither
            # enlarges the file (it printed Fig. 1 1.5 pt taller) nor shrinks its type.
            assert width == pytest.approx(printed[stem], abs=0.005), (stem, width)


    def test_only_renders_one(self, temp_dir):
        args = self._inputs(temp_dir) + ["--only", "network_delay"]
        assert main(args) == 0
        out = temp_dir / "figs"
        assert (out / "network_delay.pdf").exists()
        assert not (out / "workload_profile.pdf").exists()

    def test_missing_input_is_skipped_and_reported(self, temp_dir, capsys):
        args = self._inputs(temp_dir)
        args[args.index("--profiles-csv") + 1] = str(temp_dir / "gone.csv")
        assert main(args) == 1
        captured = capsys.readouterr().out
        assert "skipped workload_profile: input missing" in captured
        assert (temp_dir / "figs" / "network_delay.pdf").exists(), "others still render"

    def test_font_scale_scales_numeric_rc_sizes(self, temp_dir, monkeypatch):
        """In force while the figures are drawn, and gone once the call returns.

        This used to assert that the scaling was still set afterwards, which passed only
        because main never restored it. Five of the six keys then stayed scaled for the rest
        of the process: every later figure was drawn half again too large, including the ones
        other tests build, and including the ones the layout gate renders and measures.
        """
        import matplotlib.pyplot as plt
        import make_paper_figures as mpf

        keys = ("font.size", "axes.titlesize", "axes.labelsize",
                "xtick.labelsize", "ytick.labelsize", "legend.fontsize")
        before = {k: plt.rcParams[k] for k in keys}

        seen = {}
        real_save = mpf._save

        def spy(fig, out_dir, stem, **kw):
            seen[stem] = float(plt.rcParams["font.size"])
            return real_save(fig, out_dir, stem, **kw)

        monkeypatch.setattr(mpf, "_save", spy)
        args = self._inputs(temp_dir) + ["--only", "measurement_model",
                                         "--font-scale", "1.5"]
        assert main(args) == 0
        assert (temp_dir / "figs" / "measurement_model.pdf").exists()

        assert seen["measurement_model"] == pytest.approx(float(before["font.size"]) * 1.5), \
            "the scaling was not in force while the figure was drawn"
        after = {k: plt.rcParams[k] for k in keys}
        assert after == before, \
            "main left rcParams scaled: %s" % {k: (before[k], after[k])
                                               for k in keys if after[k] != before[k]}


class TestTheSliceFallback:

    @staticmethod
    def _mpf():
        import make_paper_figures
        return make_paper_figures

    def test_an_unavailable_kernel_constant_falls_back_to_the_documented_default(self,
                                                                                 monkeypatch):
        """The scheduler slice is read from the campaign's own measurements, and a reader
        rebuilding the figures from the archive may not have the file it is derived from.

        Falling back keeps the figure buildable; falling back *silently to a different
        number* would not, which is why the default is a named constant the manuscript also
        carries rather than a literal at the call site.
        """
        import kernel_constants
        monkeypatch.setattr(kernel_constants, "constants",
                            lambda *a, **kw: (_ for _ in ()).throw(OSError("no artefact")))
        mpf = self._mpf()
        assert mpf._base_slice_ms() == mpf.DEFAULT_BASE_SLICE_MS

    def test_a_constants_file_missing_the_key_falls_back_too(self, monkeypatch):
        import kernel_constants
        monkeypatch.setattr(kernel_constants, "constants", lambda *a, **kw: {})
        mpf = self._mpf()
        assert mpf._base_slice_ms() == mpf.DEFAULT_BASE_SLICE_MS

    def test_a_real_constants_file_is_preferred_over_the_default(self, monkeypatch):
        """The negative controls above only mean something beside the case that works."""
        import kernel_constants
        monkeypatch.setattr(kernel_constants, "constants",
                            lambda *a, **kw: {"base_slice_ms": 7.5})
        assert self._mpf()._base_slice_ms() == 7.5

    def test_the_tick_is_read_as_the_slice_is_with_the_same_fallback(self, monkeypatch):
        import kernel_constants
        mpf = self._mpf()
        monkeypatch.setattr(kernel_constants, "constants", lambda *a, **kw: {"tick_ms": 4.0})
        assert mpf._tick_ms() == 4.0
        monkeypatch.setattr(kernel_constants, "constants", lambda *a, **kw: {})
        assert mpf._tick_ms() == mpf.DEFAULT_TICK_MS


class TestTheWaitOfAThreadKeptWaiting:
    """The schematic's second state: the rest of another task's slice, then up to a tick."""

    def _density(self):
        import make_paper_figures
        return make_paper_figures.rest_of_a_slice_density

    def test_it_is_a_trapezoid_rising_across_the_tick_level_to_the_slice_and_falling(self):
        f = self._density()
        assert f(-0.5, 3.0, 1.0) == 0.0 and f(4.0, 3.0, 1.0) == 0.0
        assert f(0.5, 3.0, 1.0) == pytest.approx(0.5 / 3.0)
        assert f(2.0, 3.0, 1.0) == pytest.approx(1.0 / 3.0)
        assert f(3.5, 3.0, 1.0) == pytest.approx(0.5 / 3.0)

    def test_it_integrates_to_one(self):
        f = self._density()
        step = 0.001
        assert sum(f(step * (k + 0.5), 3.0, 1.0) for k in range(4000)) * step == \
            pytest.approx(1.0, abs=1e-6)
