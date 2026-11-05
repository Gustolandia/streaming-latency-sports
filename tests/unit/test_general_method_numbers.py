"""The general method's numbers (scripts/general_method_numbers.py). Each macro is read from the
committed verdicts of plan versions 47 and 49, so the tests build small verdict files in the
judges' own shape and check what the paper would print, then read the committed files once.
Supplement S8.2's table of every prediction is checked the same way."""
import csv
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import general_method_numbers as gmn  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
GENERATED = REPO / "docs" / "generated"


def _write(root, name, data):
    path = Path(root) / gmn.DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _runs(root, rows):
    path = Path(root) / gmn.DIR / "g_runs.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(("setup", "b_checks", "silence_max_us"))
        w.writerows(rows)


def _lag(name, ratio, q_off, q_on, w_off, w_on):
    return {"setup": name, "Q_own_ratio": ratio, "Q_own_tail_off": q_off, "Q_own_tail_on": q_on,
            "W_tail_off": w_off, "W_tail_on": w_on}


def _world(root, rate=2000, load=(70, 70), blocks=(5, 5), silent_checks="False",
           nats_go_lag=0.7216):
    g47 = {
        "M1-a": {"checks": [
            {"holds": True, "q_p99": [98.13, 50.0], "q_min": [0.8, 1.0], "window_us": [1.472]},
            {"holds": False, "q_p99": [80.0], "q_min": [-61.303], "window_us": [1.482, 1.463]},
            {"holds": None, "q_p99": [], "q_min": [], "window_us": []}],
            "verdict": "not confirmed"},
        "M1-c": {"checks": [{"one_reply": True, "tail_diff": 2600.4},
                            {"one_reply": True, "tail_diff": 2651.7},
                            {"one_reply": False, "tail_diff": 1987.1}],
                 "verdict": "not confirmed"},
        "M2-b": {"checks": [{"points": [1.2, -3.05, None]}, {"points": None}],
                 "verdict": "confirmed"},
        "M2-c": {"checks": [], "out_of_reach": ["P2000-rabbitmq-p1000"], "verdict": "confirmed"},
        "M3-a": {"checks": [{"judged": True, "D_ratio": 1.141}, {"judged": True, "D_ratio": 1.4632},
                            {"judged": False, "D_ratio": 1.71}],
                 "verdict": "not confirmed"},
        "P-a": {"checks": [{"prefetch": 1000}], "verdict": "not judged"},
        "KC-a": {"checks": [{"Tc_ratio": 14.56, "rate": rate}, {"Tc_ratio": 35.72, "rate": rate}]},
        "KC-b": {"checks": [{"W_ratio": 4.14, "share": 0.9996, "judged": True, "rate": rate},
                            {"W_ratio": 1.93, "share": 2.06, "rate": rate},
                            {"W_ratio": 9.9, "share": 0.1, "judged": False, "rate": rate}]},
        "A": {"parts": {"KC-d": {"checks": [{"rate": rate}]}, "M2-c": {"checks": []}}},
        "described": {"anything": 1},
        "note": "not a prediction",
    }
    g49 = {
        "R-a": {"checks": [{"W_ratio": 2.1985, "W_rise": 1824.27, "rate": rate}],
                "verdict": "confirmed"},
        "R-c": {"checks": [{"setup": "R2000-redis-d256", "W_ratio": 0.9957, "D_own_ratio": 3.36}],
                "verdict": "confirmed"},
        "J-b": {"checks": [{"setup": "J2000-nats-go", "W_ratio": 1.0272, "D_own_ratio": 4.8}],
                "verdict": "confirmed"},
        "G-b": {"checks": [{"setup": "G2000-rabbitmq-p1000", "W_ratio": 0.9591,
                            "D_own_ratio": 17.8}], "verdict": "confirmed"},
        "Q-a": {"checks": [{"WF_own_tail_off": 54.2, "WF_own_tail_on": 3131.0}],
                "verdict": "confirmed"},
        "Q-b": {"checks": [{"rise": 10.145, "left": 0.0033}], "verdict": "confirmed"},
        "Q-c": {"checks": [{"unwaited_on": 0.6109, "unwaited_off": 0.8202,
                            "described": {"g_us": 730.34, "g_turnaround_us": 27.213}}],
                "verdict": "confirmed"},
        "Z-a": {"checks": [{"WF_own_tail_off": 22.87, "WF_own_tail_on": 2196.9}],
                "verdict": "confirmed"},
        "Z-b": {"checks": [{"left": 0.000684}], "verdict": "confirmed"},
        "described": {"setups": [
            _lag("R2000-redis-d256", 1.029, 85.74, 90.36, 835.1, 846.7),
            _lag("J2000-nats-go", nats_go_lag, 55.29, 43.14, 765.44, 787.06),
            _lag("G2000-rabbitmq-p1000", 0.7343, 71.37, 48.29, 977.51, 939.92)]},
    }
    design = {"setups": [{"load_pct": load[0], "load_blocks_s": blocks[0]},
                         {"load_pct": load[1], "load_blocks_s": blocks[1]}]}
    _write(root, "g_verdicts.json", g47)
    _write(root, "g49_verdicts.json", g49)
    _write(root, "g49r_design.json", design)
    _runs(root, [("P2000-rabbitmq-p1000", silent_checks, "13459.248"),
                 ("P2000-rabbitmq-p1000", "False", "19376.426"),
                 ("V2000-redis-d256", "True", "5965.5")])


def test_the_macros_read_the_verdicts_and_round_ranges_outward(tmp_path):
    _world(tmp_path)
    got = dict(gmn.macros(str(tmp_path)))
    assert got["gmRate"] == "2{,}000"
    assert (got["gmLoadPct"], got["gmLoadBlockS"]) == ("70", "5")
    assert (got["gmRaWRatio"], got["gmRaWRiseMs"]) == ("2.20", "1.82")
    assert (got["gmKCaTcRatioLo"], got["gmKCaTcRatioHi"]) == ("14.5", "35.8")
    # The check that was not judged stays out of KC-b's range.
    assert (got["gmKCbWRatioLo"], got["gmKCbWRatioHi"]) == ("1.93", "4.14")
    assert got["gmKCbSharePctLo"] == "99"


def test_section_six_reads_the_remedy_from_both_plans(tmp_path):
    """Section VI's numbers (3 Nov 2026): M2-b's largest gap in points (an absent estimate
    skipped), the held tails of R-c, J-b and G-b, Q-a and Q-b, plan 49's count, and M3-a's D."""
    _world(tmp_path)
    got = dict(gmn.macros(str(tmp_path)))
    assert got["gmMtwoBPointsHi"] == "3.1"
    assert (got["gmHoldRatioLo"], got["gmHoldRatioHi"]) == ("0.95", "1.03")
    assert (got["gmDGrowLo"], got["gmDGrowHi"]) == ("3.3", "17.8")
    assert (got["gmQaFromUs"], got["gmQaToMs"]) == ("54", "3.13")
    assert (got["gmQbRiseUs"], got["gmQbSharePct"]) == ("10.1", "0.33")
    assert got["gmLaterPredictions"] == "9"
    assert (got["gmMthreeADLo"], got["gmMthreeADHi"]) == ("1.14", "1.47")


def test_supplement_s8_2_reads_what_decided_each_prediction(tmp_path):
    """Supplement S8.2's numbers (3 Nov 2026): M1-a over the judged setups only, M1-c's two
    readings, the bound and the silences of the cell plan 47 could not judge, Q-c, Z-a and Z-b,
    and the parts of W beside the two held tails whose card-to-kernel lag moved."""
    _world(tmp_path)
    got = dict(gmn.macros(str(tmp_path)))
    assert (got["gmMoneAPnineUs"], got["gmMoneAFail"], got["gmMoneASetups"]) == ("99", "1", "2")
    assert (got["gmMoneAEarlyUs"], got["gmMoneAWindowNs"]) == ("62", "1{,}482")
    assert (got["gmMoneCLoMs"], got["gmMoneCHiMs"], got["gmMoneCLibMs"]) == ("2.6", "2.7", "2.0")
    assert got["gmMoneCBarUs"] == "10"
    assert (got["gmBetaMs"], got["gmBetaWideMs"]) == ("10", "50")
    assert (got["gmPaSilenceLoMs"], got["gmPaSilenceHiMs"]) == ("13.4", "19.4")
    assert got["gmPrefetchWide"] == "1{,}000"
    assert (got["gmQcNoneOnPct"], got["gmQcNoneOffPct"]) == ("61", "82")
    assert (got["gmQcGapUs"], got["gmQcTurnUs"]) == ("730", "27")
    assert (got["gmZaFromUs"], got["gmZaToMs"], got["gmZbSharePct"]) == ("23", "2.20", "0.07")
    assert (got["gmQownLo"], got["gmQownHi"], got["gmQownFallUs"]) == ("0.72", "0.74", "23.1")
    assert (got["gmWTailLoUs"], got["gmWTailHiUs"]) == ("765", "978")
    assert (got["gmQbackLo"], got["gmQbackHi"]) == ("0.98", "1.05")
    # Section VIII: the fixture's plan 47 has six predictions: two confirmed, three not confirmed
    # and one not judged.
    assert (got["gmFirstPredictions"], got["gmFirstNotConfirmedWord"]) == ("6", "three")
    assert (got["gmFirstConfirmedWord"], got["gmFirstNotJudgedWord"]) == ("two", "one")


def test_a_small_count_is_a_word_and_a_large_one_digits():
    assert (gmn.spell(9), gmn.spell(12), gmn.spell(13)) == ("nine", "twelve", "13")


def test_a_cell_whose_bound_held_in_some_run_is_refused(tmp_path):
    """The text says the check of the bound failed in every run of the cell it could not judge."""
    _world(tmp_path, silent_checks="True")
    with pytest.raises(ValueError, match="failed in every run"):
        gmn.macros(str(tmp_path))


def test_a_cell_with_no_runs_is_refused(tmp_path):
    _world(tmp_path)
    _runs(tmp_path, [("V2000-redis-d256", "True", "5965.5")])
    with pytest.raises(ValueError, match="failed in every run"):
        gmn.macros(str(tmp_path))


def test_a_lag_that_moved_elsewhere_is_refused(tmp_path):
    """The text names nats.go and RabbitMQ; if nats.go's lag held, the record no longer says so."""
    _world(tmp_path, nats_go_lag=0.95)
    with pytest.raises(ValueError, match="moved lags"):
        gmn.macros(str(tmp_path))


def test_a_plan_49_prediction_not_confirmed_is_refused(tmp_path):
    """Section VI says all of plan 49's predictions held."""
    _world(tmp_path)
    path = tmp_path / gmn.DIR / "g49_verdicts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["Z-b"]["verdict"] = "not confirmed"
    _write(tmp_path, "g49_verdicts.json", data)
    with pytest.raises(ValueError, match="not confirmed"):
        gmn.macros(str(tmp_path))


def test_a_rate_that_differs_between_runs_is_refused(tmp_path):
    _world(tmp_path)
    path = tmp_path / gmn.DIR / "g49_verdicts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["R-a"]["checks"][0]["rate"] = 500
    _write(tmp_path, "g49_verdicts.json", data)
    with pytest.raises(ValueError, match="rate"):
        gmn.macros(str(tmp_path))


def test_a_load_that_differs_between_setups_is_refused(tmp_path):
    _world(tmp_path, load=(70, 60))
    with pytest.raises(ValueError, match="load"):
        gmn.macros(str(tmp_path))


def test_rounding_is_outward_at_exact_values():
    assert gmn.down(1.25, 1) == "1.2" and gmn.up(1.25, 1) == "1.3"
    assert gmn.down(2.0, 2) == "2.00" and gmn.up(2.0, 2) == "2.00"
    assert gmn.thousands(12345) == "12{,}345"
    assert (gmn.number(150.0), gmn.number(1.2), gmn.number(99.9)) == ("150", "1.2", "99.9")


def test_the_committed_verdicts_give_the_readme_values():
    """The committed files give what docs/results/general_method/README.md reports: R-a's tail
    "rose 2.20 times under the load, by 1.82 ms", KC-a's 14.6 to 35.7 times (outward here),
    KC-b's "all of the rise" (at least 99%, rounded down); M1-a's 9 of 16 x86 setups and Q down
    to -62 us; M1-c's 2.6 to 2.7 ms and 2.0 ms; the silences of 13.4 to 19.4 ms (DESIGN49.md);
    Q-c's 61% and 82%, 730 us and 27 us; Z-a's 23 us to 2.20 ms and Z-b's 0.07%; and the card's
    lag for nats.go and RabbitMQ, 0.72 and 0.73 (0.74 outward), its fall added back leaving W's
    ratio at 1.04 and 0.99 (0.98 to 1.05 outward), against W's tails of 765 to 978 us."""
    got = dict(gmn.macros(str(REPO)))
    assert got["gmRate"] == "2{,}000" and got["gmLoadPct"] == "70" and got["gmLoadBlockS"] == "5"
    assert (got["gmRaWRatio"], got["gmRaWRiseMs"]) == ("2.20", "1.82")
    assert (got["gmKCaTcRatioLo"], got["gmKCaTcRatioHi"]) == ("14.5", "35.8")
    assert got["gmKCbSharePctLo"] == "99"
    assert (got["gmMoneAFail"], got["gmMoneASetups"], got["gmMoneAEarlyUs"]) == ("9", "16", "62")
    assert (got["gmMoneCLoMs"], got["gmMoneCHiMs"], got["gmMoneCLibMs"]) == ("2.6", "2.7", "2.0")
    assert (got["gmPaSilenceLoMs"], got["gmPaSilenceHiMs"]) == ("13.4", "19.4")
    assert (got["gmQcNoneOnPct"], got["gmQcNoneOffPct"]) == ("61", "82")
    assert (got["gmQcGapUs"], got["gmQcTurnUs"]) == ("730", "27")
    assert (got["gmZaFromUs"], got["gmZaToMs"], got["gmZbSharePct"]) == ("23", "2.20", "0.07")
    assert (got["gmQownLo"], got["gmQownHi"]) == ("0.72", "0.74")
    assert (got["gmQbackLo"], got["gmQbackHi"]) == ("0.98", "1.05")
    assert (got["gmWTailLoUs"], got["gmWTailHiUs"]) == ("765", "978")
    # README: "every one of the 13 predictions"; Q-b's rise, 10.145 us in the record, reads
    # 10.1 us there since the README's correction of 3 Nov 2026.
    assert (got["gmLaterPredictions"], got["gmQbRiseUs"]) == ("13", "10.1")
    # Plan 47's verdict table: 18 predictions, eight confirmed, nine not confirmed and one (P-a)
    # not judged.
    assert (got["gmFirstPredictions"], got["gmFirstNotConfirmedWord"]) == ("18", "nine")
    assert (got["gmFirstConfirmedWord"], got["gmFirstNotJudgedWord"]) == ("eight", "one")


# --- Supplement S8.2's table --------------------------------------------------------------------

def _verdict_world(root, extra47=None, drop49=None):
    """Every prediction the table lists, each confirmed, in the judges' shape; P-a and G-a carry
    the prefetch the table prints."""
    data = {}
    for plan, _, rows in gmn.tested({"P-a": {"checks": [{"prefetch": 1000}]}},
                                    {"G-a": {"checks": [{"prefetch": 1000}]}}):
        data[plan] = {key: {"checks": [], "verdict": "confirmed"} for key, _, _ in rows}
        data[plan]["described"] = {}
    data["47"]["P-a"] = {"checks": [{"prefetch": 1000}], "verdict": "not judged"}
    data["49"]["G-a"] = {"checks": [{"prefetch": 1000}], "verdict": "confirmed"}
    if extra47:
        data["47"][extra47] = {"checks": [], "verdict": "confirmed"}
    if drop49:
        del data["49"][drop49]
    _write(root, "g_verdicts.json", data["47"])
    _write(root, "g49_verdicts.json", data["49"])


def test_the_table_lists_every_prediction_with_its_verdict(tmp_path):
    _verdict_world(tmp_path)
    body = gmn.render_table(str(tmp_path))
    rows = [line for line in body.splitlines() if line.endswith("\\\\") and " & " in line]
    keys = [line.split(" & ")[0] for line in rows]
    assert keys[1:19] == [key for key, _, _ in gmn.tested(
        {"P-a": {"checks": [{"prefetch": 1000}]}}, {"G-a": {"checks": [{"prefetch": 1000}]}})[0][2]]
    assert "P-a & 4 & as M3-a, on RabbitMQ with credit for $1{,}000$ messages kept waiting " \
        "& not judged \\\\" in body
    assert "\\multicolumn{4}{@{}l}{Plan version 47}" in body
    assert "\\multicolumn{4}{@{}l}{Plan version 49}" in body
    # Each bar comes from the judge that applied it.
    assert "within $10\\,\\mu$s" in body and "$\\beta = 50$~ms" in body
    assert "at most $150\\,\\mu$s" in body and "$1.5$-fold" in body
    assert body.startswith("% Generated by") and body.endswith("\\end{tabular}\n")


@pytest.mark.parametrize("change", [{"extra47": "M9-z"}, {"drop49": "Z-b"}])
def test_a_plan_whose_verdicts_and_table_disagree_is_refused(tmp_path, change):
    _verdict_world(tmp_path, **change)
    with pytest.raises(ValueError, match="the table lists"):
        gmn.render_table(str(tmp_path))


def test_the_committed_table_is_the_generated_one():
    """Supplement S8.2: 31 predictions, 9 of plan 47 not confirmed (M1-a, M1-c, M3-a, M3-b, V-a,
    N-a, KC-c, KC-d, A) and P-a not judged, as docs/results/general_method/README.md gives them."""
    body = gmn.render_table(str(REPO))
    assert body == (GENERATED / "general_method_table.tex").read_text(
        encoding="utf-8").replace("\r\n", "\n")
    verdicts = [line.rsplit(" & ", 1)[1] for line in body.splitlines()
                if line.endswith("\\\\") and " & " in line and not line.startswith("&")]
    assert len(verdicts) == 31
    assert verdicts.count("not confirmed \\\\") == 9
    assert verdicts.count("not judged \\\\") == 1


class TestTheEmitterReadsThem:
    """emit_paper_numbers.general_method_macros, the ledger's door to these numbers (3 Nov 2026):
    every macro it gives is in the committed ledger, and a tree without the record gives none,
    so a stale number cannot print. Its table is written only where the record is."""

    def test_every_macro_is_in_the_committed_ledger(self):
        import emit_paper_numbers as epn
        text = (GENERATED / "paper_numbers.tex").read_text(encoding="utf-8")
        pairs = epn.general_method_macros(str(REPO))
        # 3 Nov 2026: ten for Section IV-D and Supplement S8.1, twelve for Section VI, 28 for
        # Supplement S8.2 and four for Section VIII.
        assert len(pairs) == 54
        for name, value in pairs:
            assert "\\newcommand{\\%s}{%s}\n" % (name, value) in text, name

    def test_a_tree_without_the_record_emits_nothing(self, tmp_path):
        import emit_paper_numbers as epn
        assert epn.general_method_macros(str(tmp_path)) == []
        assert epn.render_general_method_table(str(tmp_path)) == ""

    def test_the_table_it_writes_is_the_readers(self):
        import emit_paper_numbers as epn
        assert epn.render_general_method_table(str(REPO)) == gmn.render_table(str(REPO))

    @pytest.mark.parametrize("body", ["", "a table\n"])
    def test_main_writes_the_table_only_where_the_record_is(self, tmp_path, monkeypatch, body):
        import emit_paper_numbers as epn
        monkeypatch.setattr(epn, "render_general_method_table", lambda *a, **kw: body)
        led = tmp_path / "l.csv"
        with led.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(("campaign", "cell", "valid", "count_source", "kept", "discarded_zero",
                        "discarded_negative"))
            w.writerow(("load_sweep", "c0", "1", "shutdown_hook", 10, 90, 0))
        table = tmp_path / "gm.tex"
        assert epn.main(["--ledger", str(led), "--out", str(tmp_path / "n.tex"), "--table",
                         str(tmp_path / "t.tex"), "--general-method-table", str(table)]) == 0
        assert table.exists() == bool(body)
