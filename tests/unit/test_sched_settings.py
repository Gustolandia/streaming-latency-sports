"""Tests for scripts/sched_settings.py, against fake /proc, /sys and /boot trees.

The values are the ones the law needs, so the tests pin the arithmetic that turns them into a
prediction as well as the reading: the kernel's rule for the default slice, including the smaller
constant that arrived in Linux 6.15.
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import sched_settings as ss  # noqa: E402

AMD = "processor : 0\nmodel name : AMD EPYC 9V74 80-Core Processor\n"
ARM = "processor : 0\nCPU implementer : 0x41\nCPU part : 0xd49\n"


def fake_root(tmp_path, release="6.8.0-1017-azure", hz="1000", slice_ns="3000000", scaling="1",
              preempt="none (voluntary) full", online="0-7", cpuinfo=AMD,
              clocksource="hyperv_clocksource_tsc_page"):
    values = {"release": release, "base_slice_ns": slice_ns, "tunable_scaling": scaling,
              "preempt": preempt, "online": online, "cpuinfo": cpuinfo,
              "clocksource": clocksource}
    for key, rel in ss.FILES.items():
        if values[key] is None:
            continue
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(values[key] + "\n", encoding="utf-8")
    if release and hz is not None:
        (tmp_path / "boot").mkdir(exist_ok=True)
        (tmp_path / "boot" / ("config-%s" % release)).write_text(
            "CONFIG_SCHED_HRTICK=y\nCONFIG_HZ_%s=y\nCONFIG_HZ=%s\n" % (hz, hz), encoding="utf-8")
    return str(tmp_path)


class TestReading:

    def test_an_azure_driver(self, tmp_path):
        s = ss.read_settings(fake_root(tmp_path))
        assert s["release"] == "6.8.0-1017-azure"
        assert s["config_hz"] == 1000 and s["tick_ms"] == 1.0
        assert s["base_slice_ns"] == 3_000_000
        assert s["tunable_scaling"] == "log"
        assert s["preempt"] == "voluntary"
        assert s["online_cpus"] == 8
        assert s["cpu_model"] == "AMD EPYC 9V74 80-Core Processor"
        assert s["clocksource"] == "hyperv_clocksource_tsc_page"
        assert s["rule_slice_ns"] == 3_000_000, "on 6.8, 8 CPUs give 4 x 0.75 ms"
        assert s["missing"] == []

    def test_the_broker_rule_on_two_cpus(self, tmp_path):
        s = ss.read_settings(fake_root(tmp_path, online="0-1", slice_ns="1500000"))
        assert s["rule_slice_ns"] == 1_500_000

    def test_the_rule_starts_from_a_smaller_constant_from_6_15(self, tmp_path):
        s = ss.read_settings(fake_root(tmp_path, release="6.17.0-1003-azure"))
        assert s["rule_slice_ns"] == 2_800_000, "4 x 0.70 ms"

    def test_the_rule_follows_the_scaling_the_kernel_reports(self, tmp_path):
        s = ss.read_settings(fake_root(tmp_path, scaling="2"))
        assert s["tunable_scaling"] == "linear" and s["rule_slice_ns"] == 8 * 750_000

    def test_an_arm_machine_is_named_by_its_part_number(self, tmp_path):
        s = ss.read_settings(fake_root(tmp_path, cpuinfo=ARM))
        assert s["cpu_model"] == "CPU implementer 0x41, part 0xd49"

    def test_nothing_readable_is_all_missing_and_nothing_is_guessed(self, tmp_path):
        s = ss.read_settings(str(tmp_path))
        assert s["missing"] == list(ss.ESSENTIAL + ss.RECORDED)
        assert s["rule_slice_ns"] is None and s["tick_ms"] is None

    @pytest.mark.parametrize("change,key", [
        ({"slice_ns": "abc"}, "base_slice_ns"),
        ({"scaling": "7"}, "tunable_scaling"),
        ({"hz": None}, "config_hz"),
        ({"cpuinfo": "processor : 0\n"}, "cpu_model"),
        ({"release": ""}, "release"),
        ({"clocksource": ""}, "clocksource"),
        ({"preempt": "none voluntary full"}, "preempt")])
    def test_an_unreadable_item_is_named(self, tmp_path, change, key):
        s = ss.read_settings(fake_root(tmp_path, **change))
        assert key in s["missing"] and s[key] is None

    def test_an_unparseable_release_gives_no_prediction(self, tmp_path):
        s = ss.read_settings(fake_root(tmp_path, release="custom"))
        assert s["release"] == "custom" and s["rule_slice_ns"] is None


class TestHelpers:

    @pytest.mark.parametrize("text,count", [("0-7", 8), ("0-3,6,8-9", 7), ("0", 1),
                                            ("0-1,", 2)])
    def test_cpu_lists(self, text, count):
        assert ss.count_cpu_list(text) == count

    def test_a_config_without_hz(self):
        assert ss.config_hz("CONFIG_SMP=y\n") is None
        assert ss.config_hz(None) is None


class TestSetting:

    def test_a_slice_is_written_and_read_back(self, tmp_path):
        root = fake_root(tmp_path)
        assert ss.set_base_slice(1_500_000, root) == 1_500_000
        assert ss.read_settings(root)["base_slice_ns"] == 1_500_000

    def test_a_slice_must_be_positive(self, tmp_path):
        with pytest.raises(ValueError, match="positive"):
            ss.set_base_slice(0, fake_root(tmp_path))

    def test_a_value_the_kernel_did_not_keep_is_refused(self, tmp_path, monkeypatch):
        root = fake_root(tmp_path)
        monkeypatch.setattr(ss, "_read", lambda r, rel: "3000000")
        with pytest.raises(ss.SliceNotApplied, match="read back '3000000'"):
            ss.set_base_slice(1_500_000, root)


class TestProblems:

    def test_matching_settings_have_none(self, tmp_path):
        assert ss.problems(ss.read_settings(fake_root(tmp_path)), 3_000_000, 1000) == []

    def test_each_kind_of_mismatch_is_a_sentence(self, tmp_path):
        s = ss.read_settings(fake_root(tmp_path, slice_ns="abc", hz="250"))
        found = ss.problems(s, 3_000_000, 1000)
        assert "base_slice_ns could not be read" in found
        assert "the base slice is None ns, not 3000000" in found
        assert "CONFIG_HZ is 250, not 1000" in found

    def test_a_missing_record_that_the_law_does_not_need_is_not_a_problem(self, tmp_path):
        s = ss.read_settings(fake_root(tmp_path, preempt=None, clocksource=None))
        assert s["missing"] == ["preempt", "clocksource"]
        assert ss.problems(s) == []


class TestMain:

    def run(self, argv):
        out = io.StringIO()
        return ss.main(argv, out=out), out.getvalue()

    def test_read(self, tmp_path):
        code, text = self.run(["--root", fake_root(tmp_path), "read"])
        assert code == 0 and json.loads(text)["base_slice_ns"] == 3_000_000

    def test_check_passes_and_fails_with_its_reasons(self, tmp_path):
        root = fake_root(tmp_path)
        code, text = self.run(["--root", root, "check", "--slice-ns", "3000000", "--hz", "1000"])
        assert code == 0 and json.loads(text)["ok"] is True
        code, text = self.run(["--root", root, "check", "--slice-ns", "1500000"])
        assert code == 1 and json.loads(text)["problems"] == [
            "the base slice is 3000000 ns, not 1500000"]

    def test_set_slice(self, tmp_path):
        code, text = self.run(["--root", fake_root(tmp_path), "set-slice", "2250000"])
        assert code == 0 and "2250000 ns, and read back" in text

    def test_set_slice_where_debugfs_is_absent(self, tmp_path):
        code, text = self.run(["--root", str(tmp_path / "nowhere"), "set-slice", "2250000"])
        assert code == 1 and text.startswith("ERROR:")
