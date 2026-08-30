"""Tests for scripts/fit_stall_mixture.py.

An EM fitter earns trust two ways: it recovers a mixture it is handed (synthetic bins built
from known components), and its numerical guards actually guard (the far-tail truncated
moments that once returned inf - inf, and the zero-latency bucket that has no logarithm).
Both failure modes were hit on real captures before the guards existed, so both are pinned.
"""
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
