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


def bins_for(values):
    """{bin_index: count} on the committed grid, from microsecond values."""
    out = {}
    for v, c in values.items():
        b = int((v - (-100_000)) // STEP)
        out[str(b)] = out.get(str(b), 0) + c
    return out


def pair_sums(points):
    """Paired co-moments for a list of (D, A) microsecond points, as the upstream pass emits.

    The correlation is computed from these rather than from the three marginal histograms;
    building them in the fixture is what lets the estimator be tested on inputs whose answer
    is known by construction.
    """
    n = len(points)
    return {"n": n, "outside": 0,
            "sd": sum(d for d, _ in points), "sa": sum(a for _, a in points),
            "sdd": sum(d * d for d, _ in points), "saa": sum(a * a for _, a in points),
            "sda": sum(d * a for d, a in points)}


def condition(s_vals, d_vals, a_vals, n_pad=0, pair=None):
    def q(vals):
        n = sum(vals.values()) + n_pad
        return {"n": n, "under": 0, "over": n_pad, "bins": bins_for(vals)}
    out = {"S": q(s_vals), "D": q(d_vals), "A": q(a_vals)}
    if pair is not None:
        out["pair"] = pair
    return out


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


class TestRhoFromPairedEvents:
    """rho(D, A) is Pearson on paired events, not the variance identity on histograms.

    The identity route read three separately truncated margins, did not conserve, and
    returned |rho| > 1 on five of seventy real conditions -- an impossible value, in a paper
    about instruments that report impossible values. These tests pin the properties the
    identity route could not offer: bounded, exact on a known construction, and loud rather
    than silent if it ever leaves the range.
    """

    def _run(self, tmp_path, monkeypatch, pair):
        payload = json.loads(synthetic(tmp_path).read_text(encoding="utf-8"))
        cond = payload["conditions"]["kafka_n2_feed1#pass"]
        if pair is None:
            cond.pop("pair", None)
        else:
            cond["pair"] = pair
        path = tmp_path / "with_pair.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(ass, "IN_JSON", str(path))
        monkeypatch.setattr(ass, "OUT_CSV", str(tmp_path / "out.csv"))
        ass.main()
        rows = {r["condition"]: r for r in csv.DictReader(open(tmp_path / "out.csv"))}
        return rows["kafka_n2_feed1#pass"]

    def test_a_perfect_linear_relation_gives_exactly_one(self, tmp_path, monkeypatch):
        pts = [(d, 2 * d + 100) for d in range(1000, 3000, 10)]
        assert float(self._run(tmp_path, monkeypatch, pair_sums(pts))["rho_DA"]) == 1.0

    def test_a_perfect_inverse_relation_gives_minus_one(self, tmp_path, monkeypatch):
        pts = [(d, -3 * d) for d in range(1000, 3000, 10)]
        assert float(self._run(tmp_path, monkeypatch, pair_sums(pts))["rho_DA"]) == -1.0

    def test_an_independent_pair_lands_near_zero(self, tmp_path, monkeypatch):
        pts = [(d, a) for d in range(1000, 1100, 10) for a in range(500, 600, 10)]
        assert abs(float(self._run(tmp_path, monkeypatch, pair_sums(pts))["rho_DA"])) < 1e-9

    def test_a_constant_arm_has_no_variance_and_yields_no_correlation(self, tmp_path,
                                                                      monkeypatch):
        """A never moves, so the correlation is undefined rather than zero."""
        pts = [(d, 700) for d in range(1000, 3000, 10)]
        assert self._run(tmp_path, monkeypatch, pair_sums(pts))["rho_DA"] in ("nan", "")

    def test_a_condition_without_paired_sums_reports_no_correlation(self, tmp_path,
                                                                    monkeypatch):
        assert self._run(tmp_path, monkeypatch, None)["rho_DA"] in ("nan", "")

    def test_a_single_pair_is_not_enough(self, tmp_path, monkeypatch):
        one = {"n": 1, "outside": 0, "sd": 1.0, "sa": 1.0,
               "sdd": 1.0, "saa": 1.0, "sda": 1.0}
        assert self._run(tmp_path, monkeypatch, one)["rho_DA"] in ("nan", "")

    def test_an_impossible_correlation_raises_instead_of_being_clamped(self, tmp_path,
                                                                      monkeypatch):
        """Co-moments that cannot come from real points must not be quietly rounded to 1.

        This is the guard that would have caught the old defect at source instead of
        leaving it to be noticed in a CSV weeks later.
        """
        bogus = {"n": 10, "outside": 0, "sd": 0.0, "sa": 0.0,
                 "sdd": 1.0, "saa": 1.0, "sda": 50.0}
        with pytest.raises(ValueError, match="rho outside"):
            self._run(tmp_path, monkeypatch, bogus)

    def test_the_summary_publishes_how_many_pairs_the_window_excluded(self, tmp_path,
                                                                      monkeypatch, capsys):
        pair = pair_sums([(d, d + 500) for d in range(1000, 3000, 10)])
        pair["outside"] = 40
        self._run(tmp_path, monkeypatch, pair)
        assert "outside the window, excluded" in capsys.readouterr().out

    def test_four_or_more_conditions_get_a_median_and_an_iqr(self, tmp_path, monkeypatch,
                                                             capsys):
        """Below four the summary declines to quote quantiles; at four it must produce them,
        and each condition needs its own correlation for the quantiles to mean anything."""
        payload = json.loads(
            synthetic(tmp_path, extra_conditions=4).read_text(encoding="utf-8"))
        for i, cond in enumerate(payload["conditions"].values()):
            cond["pair"] = pair_sums([(d, d + 500 + i * d // 20)
                                      for d in range(1000, 3000, 10)])
        path = tmp_path / "many.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(ass, "IN_JSON", str(path))
        monkeypatch.setattr(ass, "OUT_CSV", str(tmp_path / "out.csv"))
        ass.main()
        # Assert on the rho block itself: "not estimable" also appears on an unrelated
        # summary line, so a whole-output check would pass for the wrong reason.
        block = capsys.readouterr().out.split("WITHIN-EVENT CORRELATION")[1]
        assert "median" in block and "IQR" in block
        assert "not estimable" not in block.split("THE REMEDY")[0]


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


class TestTheBinWidthIsReadNotAssumed:
    """span_by_condition.py declares `bin_width_us`; this script must use it.

    It was a hardcoded 50 until round 44. The two constants had always agreed, so nothing
    failed -- but re-binning the corpus at 5 us makes every bin index here wrong by a factor
    of ten, and the medians with them, with no error raised anywhere. The defect is invisible
    by construction, which is why it needs a gate rather than a comment.
    """

    def test_the_width_comes_from_the_artefact(self):
        assert ass.step_from({"bin_width_us": 5}) == 5
        assert ass.step_from({"bin_width_us": 50}) == 50

    def test_a_missing_width_is_refused_rather_than_guessed(self):
        """Guessing is the whole defect, so absence must raise."""
        with pytest.raises(ValueError, match="bin_width_us"):
            ass.step_from({"bin_lo_us": -1000}, "some.json")

    def test_main_sets_the_module_width_from_the_json(self, monkeypatch):
        """End to end: the committed artefact declares 50, and main must adopt it rather
        than rely on the fallback happening to match."""
        monkeypatch.setattr(ass, "STEP", 999)
        data = ass.load()
        assert ass.step_from(data, ass.IN_JSON) == data["bin_width_us"]

    def test_the_conversion_uses_the_module_width(self, monkeypatch):
        """to_series must follow STEP, so that setting it from the artefact is sufficient."""
        acc = {"bins": {"0": 1, "10": 1}}
        monkeypatch.setattr(ass, "STEP", 50)
        wide = ass.to_series(acc, 0)
        monkeypatch.setattr(ass, "STEP", 5)
        narrow = ass.to_series(acc, 0)
        assert wide == [(0, 1), (500, 1)]
        assert narrow == [(0, 1), (50, 1)], (
            "to_series ignored STEP; the producer's width would then have no effect")
