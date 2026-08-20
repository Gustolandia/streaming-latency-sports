"""Tests for scripts/kernel_constants.py.

The module exists because two constants the mechanism argument depends on were never
captured from the testbed, and the testbed is being reclaimed. They are therefore derived
from public inputs. A derivation that cannot be checked is no better than the private `cat`
it replaces, so these tests check the arithmetic against the kernel's own source rules and
the committed artefacts against their stated provenance.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import kernel_constants as kc  # noqa: E402


class TestKernelFormula:
    """Checked against kernel/sched/fair.c v6.8, not against our own output."""

    @pytest.mark.parametrize("cpus,factor", [(1, 1), (2, 2), (3, 2), (4, 3), (7, 3), (8, 4)])
    def test_log_scaling_matches_the_kernel(self, cpus, factor):
        """factor = 1 + ilog2(min(ncpus, 8)) under SCHED_TUNABLESCALING_LOG."""
        assert kc.sysctl_factor(cpus, "log") == factor

    def test_the_cpu_count_is_capped_at_eight(self):
        """get_update_sysctl_factor() clamps, so a bigger machine gets the same factor."""
        assert kc.sysctl_factor(64, "log") == kc.sysctl_factor(8, "log")

    def test_the_other_scaling_modes_are_implemented(self):
        assert kc.sysctl_factor(4, "none") == 1
        assert kc.sysctl_factor(4, "linear") == 4

    def test_an_unknown_scaling_is_refused(self):
        with pytest.raises(ValueError):
            kc.sysctl_factor(8, "quadratic")

    def test_ilog2_rejects_zero(self):
        with pytest.raises(ValueError):
            kc._ilog2(0)

    def test_the_eight_cpu_base_slice_is_three_milliseconds(self):
        """The number Section V-G rests on. 4 x 750000 ns."""
        assert kc.base_slice_ns(8) == 3_000_000

    def test_a_smaller_shape_would_give_a_different_slice(self):
        """Why the value could NOT have been read off a restored micro instance: it is
        computed from the online CPU count, so the same image on a one-vCPU shape reports
        0.75 ms rather than 3 ms."""
        assert kc.base_slice_ns(1) == 750_000
        assert kc.base_slice_ns(1) != kc.base_slice_ns(8)


class TestCpuCountFromTheCampaign:
    def test_it_recovers_eight_from_k_over_rho(self):
        est = kc.cpus_from_geometry()
        assert len(est) == 6, "six geometry conditions, six independent estimates"
        assert all(7.9 < e < 8.1 for e in est)

    def test_the_estimates_agree_closely_enough_to_round_safely(self):
        est = kc.cpus_from_geometry()
        assert max(est) - min(est) < 0.2, "the spread is the error bar on this number"


class TestCommittedConfig:
    def test_the_config_artefact_carries_its_provenance(self):
        raw = open(kc.CONFIG_FILE, encoding="utf-8").read()
        for token in ("sha256", "linux-buildinfo-6.8.0-1057-oracle", "6.8.0-1057-oracle"):
            assert token in raw, f"a reader must be able to re-fetch and verify: {token}"

    def test_the_tick_is_one_millisecond(self):
        cfg = kc.read_config()
        assert cfg["CONFIG_HZ"] == "1000"

    def test_hrtick_is_compiled_in(self):
        """Compiled in, but the v6.8 runtime default is off (SCHED_FEAT(HRTICK, false)),
        which is why slice expiry is observed at the tick rather than exactly."""
        assert kc.read_config()["CONFIG_SCHED_HRTICK"] == "y"


class TestDerivedConstants:
    def test_every_quantity_the_paper_quotes_is_present(self):
        c = kc.constants()
        for key in ("config_hz", "tick_ms", "cpus", "sysctl_factor",
                    "base_slice_ns", "base_slice_ms", "cpu_spread"):
            assert key in c

    def test_the_derived_slice_matches_the_papers_claim(self):
        c = kc.constants()
        assert c["cpus"] == 8
        assert c["sysctl_factor"] == 4
        assert c["base_slice_ms"] == pytest.approx(3.0)
        assert c["tick_ms"] == pytest.approx(1.0)

    def test_the_cli_reports_the_chain_not_just_the_answer(self, capsys):
        assert kc.main([]) == 0
        out = capsys.readouterr().out
        for token in ("CONFIG_HZ", "k/rho", "ilog2", "base slice"):
            assert token in out, "the derivation must be legible, not just its result"

    def test_json_mode(self, capsys):
        import json
        assert kc.main(["--json"]) == 0
        assert json.loads(capsys.readouterr().out)["base_slice_ns"] == 3_000_000


class TestTheCountHasTwoIndependentSources:
    """Raised by the author, 2026-08-20: is the 8 this machine, or a pool, or the old
    workstation? The workstation had 8 cores and 16 threads, so attaching its count to the
    cloud kernel would have been a real error. It is not: the mechanism campaigns run from
    cloud/campaigns/ and every cloud run records node=sbl-drv on 6.8.0-1057-oracle.
    """

    def test_the_campaigns_wrote_the_count_down_while_running(self):
        stated = kc.cores_from_campaign_logs()
        assert stated, "the logs state the machine they loaded; that is direct evidence"
        assert stated.most_common(1)[0][0] == 8

    def test_the_two_sources_agree(self):
        """One is what the operator told stress-ng, the other is what the utilisation
        measurement implies. Agreement is the point; disagreement would be a finding."""
        c = kc.constants()
        assert c["cpus_stated_in_logs"] == c["cpus"] == 8
        assert c["cpus_agree"] is True
        assert c["cpus_stated_mentions"] >= 20

    def test_a_missing_log_directory_degrades_rather_than_crashes(self, tmp_path):
        assert kc.cores_from_campaign_logs(str(tmp_path)) == {}

    def test_the_measured_utilisation_rules_out_a_sixteen_thread_machine(self):
        """The discriminator. Loading 7 cores measured rho = 0.878, which is 7/8. On the
        workstation's 16 threads the same load would have read 7/16 = 0.44."""
        est = kc.cpus_from_geometry()
        assert all(abs(e - 8) < 0.1 for e in est)
        assert not any(abs(e - 16) < 1.0 for e in est)
