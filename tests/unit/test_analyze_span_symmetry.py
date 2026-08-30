"""Tests for scripts/analyze_span_symmetry.py.

Everything the script prints rests on four small computations -- the mirrored-mass score, the
independence convolution, the variance-identity correlation, and the recovery identity -- so
each is pinned on constructed distributions whose right answer is known by hand, and the main
pass is run over a synthetic two-condition JSON with one gate-split pair.
"""
import csv
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import analyze_span_symmetry as ass  # noqa: E402

STEP = ass.STEP


class TestScore:
    def test_a_mirror_symmetric_series_scores_zero_about_its_centre(self):
        counts = {-2 * STEP: 5, -STEP: 9, 0: 9, STEP: 5}
        assert ass.asym_score(counts, 0) == 0.0

    def test_a_one_sided_series_scores_one(self):
        counts = {0: 5, STEP: 9}
        assert ass.asym_score(counts, 0) == 1.0

    def test_an_empty_window_returns_none_rather_than_dividing(self):
        assert ass.asym_score({}, 0) is None

    def test_best_centre_finds_the_construction_point(self):
        centre = 600
        series = sorted({centre - 2 * STEP: 3, centre - STEP: 7, centre: 7,
                         centre + STEP: 3}.items())
        c, score = ass.best_centre(series, 20, 600)
        assert c == centre and score == 0.0


class TestPieces:
    def test_median_walks_the_cumulative_mass(self):
        series = [(0, 4), (STEP, 4), (2 * STEP, 4)]
        assert ass.median_us(series, 12) == STEP

    def test_median_of_an_exhausted_series_returns_the_last_edge(self):
        assert ass.median_us([(0, 1)], 10) == 0

    def test_median_of_nothing_is_zero(self):
        assert ass.median_us([], 0) == 0.0

    def test_the_convolution_of_two_point_masses_is_their_difference(self):
        d = [(1000, 10)]
        a = [(400, 10)]
        pred = ass.convolve_diff(d, a, 10, 10)
        assert pred == {600: 1.0}

    def test_tv_distance_is_zero_against_itself_and_one_against_disjoint(self):
        p = {0: 1.0}
        assert ass.tv_distance(p, [(0, 5)], 5) == 0.0
        assert ass.tv_distance(p, [(STEP, 5)], 5) == 1.0

    def test_neg_fraction_sums_only_the_negative_keys(self):
        assert ass.neg_fraction({-STEP: 0.25, 0: 0.5, STEP: 0.25}) == 0.25
        assert ass.neg_fraction([1, 2]) is None

    def test_moments_of_an_empty_series_are_zero(self):
        assert ass.moments([], 0) == (0.0, 0.0)

    def test_moments_recover_a_two_point_spread(self):
        """Bins at 0 and 100 us have centres 25 and 125: mean 75, variance 50^2."""
        m, v = ass.moments([(0, 1), (2 * STEP, 1)], 2)
        assert m == 75.0 and v == 2500.0


def bins_for(values):
    """{bin_index: count} on the committed grid, from microsecond values."""
    out = {}
    for v, c in values.items():
        b = int((v - (-100_000)) // STEP)
        out[str(b)] = out.get(str(b), 0) + c
    return out


def condition(s_vals, d_vals, a_vals, n_pad=0):
    def q(vals):
        n = sum(vals.values()) + n_pad
        return {"n": n, "under": 0, "over": n_pad, "bins": bins_for(vals)}
    return {"S": q(s_vals), "D": q(d_vals), "A": q(a_vals)}


def triangle(centre, scale=100):
    """Symmetric under the score's pairing (counts[c + k*STEP] == counts[c - (k+1)*STEP]),
    so its best centre is the construction point exactly. n = 28 * scale."""
    return {centre - 2 * STEP: 5 * scale, centre - STEP: 9 * scale,
            centre: 9 * scale, centre + STEP: 5 * scale}


def synthetic(tmp_path, extra_conditions=0, neg_lobe=False):
    """A gate-split pair on symmetric triangles, one condition too small to analyse, and
    optionally more pass conditions so the summary's IQR branches run."""
    big_s = triangle(600)
    if neg_lobe:
        big_s = dict(big_s)
        big_s[-400] = 60
    conds = {
        "kafka_n2_feed1#pass": condition(big_s, triangle(1200), triangle(600)),
        "kafka_n2_feed1#fail": condition(big_s, triangle(1200), triangle(600)),
        "redis_n1_feed1#pass": condition({600: 10}, {600: 10}, {600: 10}),
    }
    for i in range(extra_conditions):
        conds["redis_n%d_feed1#pass" % (i + 2)] = condition(
            big_s, triangle(1200), triangle(600))
    payload = {
        "runs": 4, "events": 1, "bin_lo_us": -100_000, "bin_hi_us": 100_000,
        "bin_width_us": STEP, "alphas": [1.0], "ratio_hist_tenth_decades": {},
        "conditions": conds,
    }
    p = tmp_path / "in.json"
    p.write_text(json.dumps(payload))
    return p


class TestMain:
    def test_the_pass_and_fail_populations_are_scored_separately(self, tmp_path,
                                                                 monkeypatch, capsys):
        monkeypatch.setattr(ass, "IN_JSON", str(synthetic(tmp_path)))
        monkeypatch.setattr(ass, "OUT_CSV", str(tmp_path / "out.csv"))
        ass.main()
        text = capsys.readouterr().out
        assert "gate-passing runs" in text and "gate-failing runs" in text
        rows = list(csv.DictReader(open(tmp_path / "out.csv")))
        # the small condition is skipped, the pair survives
        assert {r["condition"] for r in rows} == {"kafka_n2_feed1#pass",
                                                  "kafka_n2_feed1#fail"}

    def test_the_recovery_identity_is_exact_on_point_masses(self, tmp_path, monkeypatch,
                                                            capsys):
        """D at 1200, A at 600: med(D) - med(A) = 600, and S's bulk sits at 600, so the
        recovered median must equal the true one bin-for-bin."""
        monkeypatch.setattr(ass, "IN_JSON", str(synthetic(tmp_path)))
        monkeypatch.setattr(ass, "OUT_CSV", str(tmp_path / "out.csv"))
        ass.main()
        rows = list(csv.DictReader(open(tmp_path / "out.csv")))
        for r in rows:
            assert int(float(r["recovery_err_us"])) == 0

    def test_a_remedy_subset_smaller_than_three_is_skipped_not_crashed(self, tmp_path,
                                                                       monkeypatch, capsys):
        payload = json.loads((synthetic(tmp_path)).read_text())
        del payload["conditions"]["kafka_n2_feed1#fail"]
        p = tmp_path / "in2.json"
        p.write_text(json.dumps(payload))
        monkeypatch.setattr(ass, "IN_JSON", str(p))
        monkeypatch.setattr(ass, "OUT_CSV", str(tmp_path / "out2.csv"))
        ass.main()
        assert "skipped" in capsys.readouterr().out

    def test_a_tiny_corpus_says_not_estimable_rather_than_crashing(self, tmp_path,
                                                                   monkeypatch, capsys):
        """Two analysable conditions is below every quantile's n=4 floor: the summary must
        degrade to its no-IQR lines rather than raise StatisticsError."""
        monkeypatch.setattr(ass, "IN_JSON", str(synthetic(tmp_path)))
        monkeypatch.setattr(ass, "OUT_CSV", str(tmp_path / "out.csv"))
        ass.main()
        text = capsys.readouterr().out
        assert "not estimable" in text and "no IQR" in text

    def test_a_corpus_wide_enough_for_quantiles_prints_the_iqr_lines(self, tmp_path,
                                                                     monkeypatch, capsys):
        monkeypatch.setattr(ass, "IN_JSON",
                            str(synthetic(tmp_path, extra_conditions=4, neg_lobe=True)))
        monkeypatch.setattr(ass, "OUT_CSV", str(tmp_path / "out.csv"))
        ass.main()
        text = capsys.readouterr().out
        assert text.count("IQR") >= 4
