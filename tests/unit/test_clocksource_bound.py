"""Tests for scripts/clocksource_bound.py - target >=95% branch coverage.

The script turns "we never recorded the clocksource" into "here is the set it can have been,
and every member of that set carries the guarantee the reviewer asked about". That is a
load-bearing inference, so the tests pin both the arithmetic and the direction of each
exclusion: an exclusion that fires for the wrong reason would reach the same conclusion by
luck, and luck does not survive a re-run on different hardware.
"""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import clocksource_bound as cb  # noqa: E402


def write_platform(tmp_path, increment):
    p = tmp_path / "platform.json"
    payload = {"timer_resolution_ns": increment} if increment is not None else {}
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# --- the constants -------------------------------------------------------------------------

def test_pm_timer_tick_matches_the_kernel_constant():
    """include/linux/acpi_pmtmr.h: PMTMR_TICKS_PER_SEC 3579545."""
    assert cb.PMTMR_TICKS_PER_SEC == 3_579_545
    assert round(cb.pm_timer_tick_ns()) == 279


def test_kvm_clock_outranks_tsc():
    """Selection is by rating, and this ordering is why tsc implies a verified TSC."""
    assert cb.RATINGS["kvm-clock"] > cb.RATINGS["tsc"] > cb.RATINGS["hpet"] > cb.RATINGS["acpi_pm"]


# --- the exclusions, each for its own reason -----------------------------------------------

def test_acpi_pm_is_excluded_by_granularity_not_by_speed():
    """Its tick alone forecloses it; the argument must not silently rest on read cost."""
    ok, why = cb.admits(90.0, "acpi_pm")
    assert ok is False
    assert "tick" in why


def test_hpet_is_excluded_by_read_cost_only():
    """HPET's tick is ~70 ns, finer than the observed increment. Only cost excludes it."""
    ok, why = cb.admits(90.0, "hpet")
    assert ok is False
    assert "read" in why


def test_hpet_would_be_admitted_by_a_granularity_test_alone():
    """Guards against someone 'simplifying' the script into a wrong argument."""
    hpet_tick_ns = 1e9 / 14_318_180
    assert hpet_tick_ns < 90.0


def test_kvm_clock_without_the_vdso_is_excluded():
    """The branch that carries no cross-vCPU guarantee is the branch the bound removes."""
    ok, _ = cb.admits(90.0, "kvm-clock (no vDSO)")
    assert ok is False


@pytest.mark.parametrize("name", ["tsc", "kvm-clock"])
def test_the_fast_clocksources_are_admitted(name):
    ok, _ = cb.admits(90.0, name)
    assert ok is True


def test_a_slower_machine_admits_more_clocksources():
    """The bound must track the measurement, not be hard-wired to this testbed."""
    ok, _ = cb.admits(5000.0, "hpet")
    assert ok is True


def test_a_faster_machine_still_excludes_the_slow_sources():
    for name in ("hpet", "acpi_pm", "kvm-clock (no vDSO)"):
        assert cb.admits(40.0, name)[0] is False


# --- the committed measurement --------------------------------------------------------------

def test_the_reported_testbed_increment_is_the_committed_one():
    assert round(cb.measured_increment_ns()) == 90


def test_the_bound_leaves_only_the_two_coherent_clocksources():
    b = cb.bound()
    assert b["admitted"] == ["kvm-clock", "tsc"]
    assert set(b["excluded"]) == {"acpi_pm", "hpet", "kvm-clock (no vDSO)"}


def test_every_admitted_branch_carries_a_cross_vcpu_guarantee():
    """The whole point. vDSO kvm-clock requires PVCLOCK_TSC_STABLE_BIT; tsc is only selected
    where the kernel has checked it and has not turned it off."""
    assert cb.bound()["all_admitted_are_coherent"] is True


def test_a_platform_file_without_the_field_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="no timer_resolution_ns"):
        cb.measured_increment_ns(write_platform(Path("."), None))


def test_a_missing_platform_file_raises(tmp_path):
    with pytest.raises(OSError):
        cb.measured_increment_ns(tmp_path / "absent.json")


# --- CLI --------------------------------------------------------------------------------------

def test_main_text_output(capsys, tmp_path):
    p = write_platform(tmp_path, 90.0)
    assert cb.main(["--platform", str(p)]) == 0
    out = capsys.readouterr().out
    assert "EXCLUDED" in out and "kvm-clock, tsc" in out


def test_main_json_output(capsys, tmp_path):
    p = write_platform(tmp_path, 90.0)
    assert cb.main(["--platform", str(p), "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["admitted"] == ["kvm-clock", "tsc"]


def test_an_empty_admitted_set_is_not_reported_as_coherent(tmp_path):
    """A measurement so fast that nothing fits must not read as a positive result."""
    b = cb.bound(write_platform(tmp_path, 1.0))
    assert b["admitted"] == []
    assert b["all_admitted_are_coherent"] is False
