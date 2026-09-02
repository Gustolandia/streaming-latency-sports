"""Tests for scripts/fit_stall_mixture.py.

An EM fitter earns trust two ways: it recovers a mixture it is handed (synthetic bins built
from known components), and its numerical guards actually guard (the far-tail truncated
moments that once returned inf - inf, and the zero-latency bucket that has no logarithm).
Both failure modes were hit on real captures before the guards existed, so both are pinned.
"""
import io
import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import fit_stall_mixture as fsm  # noqa: E402


def normal_bins(mu, sigma, n, lo=-4.0, hi=16.0, width=1.0):
    """Integer counts of N(mu, sigma) over unit buckets in log2 space."""
    bins = []
    x = lo
    while x < hi:
        p = fsm.Phi((x + width - mu) / sigma) - fsm.Phi((x - mu) / sigma)
        c = int(round(n * p))
        if c:
            bins.append((x, x + width, c))
        x += width
    return bins


def merge(*binlists):
    out = {}
    for bl in binlists:
        for lo, hi, c in bl:
            out[(lo, hi)] = out.get((lo, hi), 0) + c
    return [(lo, hi, c) for (lo, hi), c in sorted(out.items())]


class TestNumerics:
    def test_phi_and_Phi_agree_with_the_standard_normal(self):
        assert abs(fsm.Phi(0.0) - 0.5) < 1e-12
        assert abs(fsm.phi(0.0) - 1.0 / math.sqrt(2 * math.pi)) < 1e-12

    def test_bucket_mass_is_clamped_away_from_zero(self):
        assert fsm._bucket_mass(0.0, 0.1, 50.0, 51.0) >= 1e-300

    def test_far_tail_moments_return_the_near_edge_not_infinity(self):
        """The guard that fixed the NaN on the go-first arm: a bucket 250 sigma above the
        component must report the bucket's lower edge, not an astronomical extrapolation."""
        m1, m2 = fsm._trunc_moments(1.5, 0.01, 19.0, 20.0)
        assert (m1, m2) == (19.0, 19.0 * 19.0)
        m1, m2 = fsm._trunc_moments(1.5, 0.01, -20.0, -19.0)
        assert (m1, m2) == (-19.0, 19.0 * 19.0)

    def test_interior_moments_stay_inside_the_bucket(self):
        m1, m2 = fsm._trunc_moments(0.5, 1.0, 0.0, 1.0)
        assert 0.0 <= m1 <= 1.0
        assert m2 >= m1 * m1


class TestLoadBins:
    def test_the_zero_bucket_is_mapped_below_one_microsecond(self, tmp_path):
        p = tmp_path / "r.txt"
        p.write_text("@count: 10\n@usecs: \n[0]  3 |@|\n[1]  7 |@@@|\n")
        bins, counters = fsm.load_bins(str(p))
        assert bins[0][0] == math.log2(0.25) and bins[0][1] == 0.0
        assert counters["count"] == 10

    def test_empty_buckets_are_dropped(self, tmp_path):
        p = tmp_path / "r.txt"
        p.write_text("@usecs: \n[1]  5 |@|\n[2, 4)  0 |  |\n[4, 8)  5 |@|\n")
        bins, _ = fsm.load_bins(str(p))
        assert len(bins) == 2


class TestFit:
    def test_a_single_component_is_recovered(self):
        bins = normal_bins(mu=3.0, sigma=1.0, n=50_000)
        w, mu, sg, ll = fsm.fit_best(bins, 1, restarts=2)
        assert abs(mu[0] - 3.0) < 0.1 and abs(sg[0] - 1.0) < 0.1

    def test_two_separated_components_are_recovered_with_their_weights(self):
        bins = merge(normal_bins(1.0, 0.5, 30_000), normal_bins(11.0, 0.5, 10_000))
        w, mu, sg, ll = fsm.fit_best(bins, 2, restarts=3)
        assert abs(mu[0] - 1.0) < 0.2 and abs(mu[1] - 11.0) < 0.2
        assert abs(w[0] - 0.75) < 0.05

    def test_components_come_back_sorted_by_location(self):
        bins = merge(normal_bins(9.0, 0.5, 10_000), normal_bins(1.0, 0.5, 10_000))
        _w, mu, _sg, _ll = fsm.fit_best(bins, 2, restarts=2)
        assert mu == sorted(mu)

    def test_bic_charges_three_parameters_per_component_minus_the_simplex(self):
        assert fsm.bic(-10.0, 2, 100) == 20.0 + 5 * math.log(100)

    def test_more_components_never_lower_the_likelihood(self):
        bins = merge(normal_bins(1.0, 0.6, 20_000), normal_bins(8.0, 0.8, 20_000))
        _, _, _, ll1 = fsm.fit_best(bins, 1, restarts=2)
        _, _, _, ll2 = fsm.fit_best(bins, 2, restarts=2)
        assert ll2 >= ll1


class TestGuards:
    def test_more_components_than_buckets_all_start_on_the_one_bucket(self):
        """A one-bucket histogram asked for three components: the quantile walk drains every
        target on that bucket, and the fit still returns k sorted components."""
        bins = [(0.0, 1.0, 1000)]
        w, mu, sg, _ll = fsm.em_fit(bins, 3, seed=0, iters=3)
        assert len(mu) == 3 and mu == sorted(mu)

    def test_a_zero_weight_component_is_skipped_in_the_e_step(self):
        """Weight exactly zero makes every responsibility for that component zero, which is
        the underflow the guard exists for; its accumulators must stay empty."""
        num_w, _m1, _m2 = fsm._estep([(0.0, 1.0, 100)], [1.0, 0.0], [0.5, 5.0], [1.0, 1.0])
        assert num_w[1] == 0.0

    def test_a_starved_component_keeps_its_parameters_in_the_m_step(self):
        w, mu, sg = [0.5, 0.5], [0.0, 5.0], [1.0, 1.0]
        fsm._mstep(100, w, mu, sg, [100.0, 0.0], [50.0, 0.0], [30.0, 0.0])
        assert (mu[1], sg[1]) == (5.0, 1.0)


class TestBootstrap:
    def test_intervals_cover_the_construction_on_a_clean_mixture(self):
        bins = merge(normal_bins(1.0, 0.5, 30_000), normal_bins(11.0, 0.5, 10_000))
        ci = fsm.bootstrap(bins, 2, reps=8, seed=3)
        lo, hi = ci["mu_us"][1]
        assert lo <= 2.0 ** 11.0 <= hi
        wlo, whi = ci["w"][0]
        assert wlo <= 0.75 <= whi

    def test_a_bucket_holding_all_the_mass_ends_the_resampling_walk_early(self):
        """probs = [1, 0]: the first draw is exact and consumes everything, so the walk's
        early-exit branch runs before the zero-probability bucket is reached."""
        bins = [(0.0, 1.0, 500), (1.0, 2.0, 0)]
        ci = fsm.bootstrap(bins, 1, reps=2, seed=1)
        assert len(ci["w"]) == 1


class TestAnalyse:
    def _capture(self, tmp_path, text):
        p = tmp_path / "runqlat.txt"
        p.write_text(text)
        return str(p)

    def test_the_elbow_report_and_region_weights_are_printed(self, tmp_path, capsys):
        text = "@count: 40000\n@usecs: \n" + \
            "[1]  20000 |@|\n[2, 4)  9000 |@|\n[128, 256)  9000 |@|\n[2K, 4K)  2000 |@|\n"
        out = fsm.analyse(self._capture(tmp_path, text), "toy", kmax=3, reps=0)
        assert out["best_k"] in (1, 2, 3)
        printed = capsys.readouterr().out
        assert "region weights" in printed and "BIC argmin" in printed

    def test_reps_zero_skips_the_bootstrap(self, tmp_path, capsys):
        text = "@usecs: \n[1]  1000 |@|\n[2, 4)  1000 |@|\n"
        fsm.analyse(self._capture(tmp_path, text), "toy", kmax=1, reps=0)
        assert "bootstrapping" not in capsys.readouterr().out

    def test_reps_positive_prints_component_intervals(self, tmp_path, capsys):
        text = "@usecs: \n[1]  2000 |@|\n[2, 4)  2000 |@|\n"
        fsm.analyse(self._capture(tmp_path, text), "toy", kmax=1, reps=3)
        assert "comp 1" in capsys.readouterr().out


class TestMain:
    def test_both_arms_are_fitted_and_the_json_written(self, tmp_path, monkeypatch, capsys):
        base = tmp_path / "base.txt"
        rt = tmp_path / "rt.txt"
        base.write_text("@usecs: \n[1]  5000 |@|\n[2, 4)  3000 |@|\n[2K, 4K)  1000 |@|\n")
        rt.write_text("@usecs: \n[0]  100 |@|\n[1]  8000 |@|\n[2, 4)  900 |@|\n")
        out = tmp_path / "m.json"
        monkeypatch.setattr(fsm, "BASE", str(base))
        monkeypatch.setattr(fsm, "RT", str(rt))
        monkeypatch.setattr(fsm, "OUT", str(out))
        rc = fsm.main(["--kmax", "2", "--boot", "2"])
        assert rc == 0
        data = json.load(open(out))
        assert set(data) == {"base", "rt"}
        assert "wrote" in capsys.readouterr().out


class TestTheSelectorReportsTheDataNotTheFlag:
    """`best_k` must be the elbow, and `bic_argmin_k` must be labelled as the argmin.

    Until round 44 the artefact stored argmin under the name `best_k` and recorded 6 for
    both arms -- because kmax was 6. At n of order 5e5 one more component costs 3 ln n,
    about 40, and buys likelihood in the thousands, so BIC improves through whatever kmax
    it is offered. The stored "best" was a command-line flag wearing the name of a finding,
    and the bootstrap intervals described a six-component fit nobody quotes.
    """

    THREE_CLUSTERS = chr(10).join([
        "@usecs: ",
        "[1]  120000 |@|",
        "[2, 4)  60000 |@|",
        "[4, 8)  20000 |@|",
        "[64, 128)  40000 |@|",
        "[128, 256)  90000 |@|",
        "[256, 512)  30000 |@|",
        "[2K, 4K)  50000 |@|",
        "[4K, 8K)  15000 |@|",
        "",
    ])

    def _src(self, tmp_path):
        p = tmp_path / "runqlat.txt"
        p.write_text(self.THREE_CLUSTERS)
        return str(p)

    def test_the_elbow_is_the_same_answer_at_every_kmax(self, tmp_path):
        """The property argmin lacks. This is the whole point of the fix."""
        elbows, argmins = set(), set()
        for kmax in (4, 5, 6):
            out = fsm.analyse(self._src(tmp_path), "toy", kmax=kmax, reps=0)
            elbows.add(out["best_k"])
            argmins.add(out["bic_argmin_k"])
        assert len(elbows) == 1, (
            "the elbow moved with kmax (%s); it is supposed to be a property of the data"
            % sorted(elbows))
        assert len(argmins) > 1, (
            "argmin did not move with kmax on this fixture (%s), so the fixture no longer "
            "demonstrates the defect the elbow exists to avoid -- give it more mass or "
            "more separated clusters" % sorted(argmins))

    def test_argmin_is_kept_but_no_longer_called_best(self, tmp_path):
        out = fsm.analyse(self._src(tmp_path), "toy", kmax=6, reps=0)
        # Not "argmin == kmax": on a fixture this clean BIC does eventually saturate, and
        # the 5->6 step is worth -40. That is precisely the difference from the real corpus,
        # where lognormal-shape misfit keeps paying and argmin never stops. What must hold
        # everywhere is the ordering -- the elbow stops no later than argmin does.
        assert out["best_k"] < out["bic_argmin_k"], (
            "elbow %d, argmin %d: the two agree here, so this fixture is not exercising the "
            "gap between them" % (out["best_k"], out["bic_argmin_k"]))
        assert out["kmax"] == 6, "kmax must be recorded, because argmin depends on it"
        assert "%.2f" not in out["selection_rule"], "the rule string was stored unformatted"
        assert "per sample" in out["selection_rule"]

    def test_the_per_sample_curve_is_published_so_the_rule_can_be_argued_with(self, tmp_path):
        out = fsm.analyse(self._src(tmp_path), "toy", kmax=4, reps=0)
        per = out["bic_drop_per_sample"]
        assert set(per) == {2, 3, 4}
        for k, v in per.items():
            assert abs(v - out["bic_drops"][k] / out["n"]) < 1e-12

    def test_the_bootstrap_describes_the_fit_that_gets_quoted(self, tmp_path):
        """CIs at argmin would document a fit the paper never shows."""
        out = fsm.analyse(self._src(tmp_path), "toy", kmax=6, reps=3)
        k = out["best_k"]
        assert "ci95" in out["fits"][k], "the bootstrap ran somewhere other than the elbow"
        assert len(out["fits"][k]["ci95"]["w"]) == k
        assert "ci95" not in out["fits"][out["bic_argmin_k"]] or k == out["bic_argmin_k"]

    def test_non_monotone_drops_are_flagged_rather_than_hidden(self, tmp_path):
        """The rt arm really does gain more at k=4 than at k=3; a reader must be told."""
        out = fsm.analyse(self._src(tmp_path), "toy", kmax=5, reps=0)
        assert isinstance(out["bic_drops_monotone"], bool)

    def test_the_real_rt_trace_is_non_monotone_and_says_so(self):
        """Not a hypothetical branch: the rt arm gains more at k=4 than at k=3.

        752573, 10499, 13628 -- the third component buys less than the fourth. That is a
        sign the component count is not identified for this arm at all, and a reader who is
        handed "K = 2" without the caveat would take it for a measurement. The base arm is
        monotone; only rt trips this, which is itself worth knowing.
        """
        here = os.path.dirname(os.path.abspath(__file__))
        rt = os.path.join(here, "..", "..", "docs", "results", "depth", "ea9",
                          "l88_rt", "runqlat.txt")
        if not os.path.exists(rt):
            pytest.skip("depth trace not present in this checkout")
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = fsm.analyse(rt, "rt", kmax=4, reps=0)
        assert out["bic_drops_monotone"] is False, (
            "the rt drops became monotone (%s); if the trace or the fitter changed this "
            "test is now checking nothing" % out["bic_drops"])
        assert "not monotone" in buf.getvalue(), (
            "the caveat was computed but never printed, so a reader of the log would take "
            "the selected K at face value")
        assert out["best_k"] == 2

class TestElbowRule:
    def test_it_stops_at_the_component_before_the_first_cheap_one(self):
        drops = {2: 100.0, 3: 50.0, 4: 1.0, 5: 0.5}
        assert fsm.elbow_k(drops, n=100, kmax=5, threshold=0.05) == 3

    def test_it_returns_kmax_when_every_component_still_pays(self):
        assert fsm.elbow_k({2: 100.0, 3: 100.0}, n=10, kmax=3, threshold=0.05) == 3

    def test_it_normalises_by_n_so_the_threshold_travels(self):
        """The same absolute gain means everything on 1e3 samples and nothing on 1e6."""
        drops = {2: 4000.0}
        assert fsm.elbow_k(drops, n=1000, kmax=2, threshold=0.05) == 2
        assert fsm.elbow_k(drops, n=500000, kmax=2, threshold=0.05) == 1

    def test_degenerate_inputs_fall_back_to_one_component(self):
        assert fsm.elbow_k({}, n=100, kmax=4) == 1
        assert fsm.elbow_k({2: 5.0}, n=0, kmax=4) == 1


class TestTheShippedArtefactCarriesTheHonestNumber:
    ART = os.path.join("docs", "results", "stall_mixture.json")

    def _load(self):
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "..", self.ART)
        if not os.path.exists(path):
            pytest.skip("artefact not built in this checkout")
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_the_committed_json_does_not_record_best_k_equal_to_kmax(self):
        """The signature of the old defect, checked on the file that actually ships."""
        for arm, d in self._load().items():
            assert d["best_k"] < d["kmax"], (
                "%s records best_k == kmax == %d, which is what argmin returns when BIC "
                "never stops improving; the selector has regressed" % (arm, d["kmax"]))
            assert d["best_k"] == fsm.elbow_k(
                {int(k): v for k, v in d["bic_drops"].items()}, d["n"], d["kmax"]), (
                "%s: the stored best_k does not match the rule applied to the stored "
                "drops" % arm)

    def test_the_base_arm_still_separates_into_the_three_regions_of_the_figure(self):
        """The trimodal claim rests on regions, not on k -- so check the regions."""
        data = self._load()
        base = data["base"]["fits"][str(data["base"]["best_k"])]["group_w"]
        assert all(g > 0.01 for g in base), (
            "the base arm no longer populates all three regions (%s); the figure caption "
            "would then be describing something the fit does not show" % base)
        rt = data["rt"]["fits"][str(data["rt"]["best_k"])]["group_w"]
        assert rt[2] < 0.01, (
            "the rt arm grew a >1ms stall region (%.3f); suppressing exactly that is what "
            "the arm is for" % rt[2])
