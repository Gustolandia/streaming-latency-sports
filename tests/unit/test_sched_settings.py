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
#: A feature line of the kind a 6.8 kernel shows in debugfs: every feature on one line, the off
#: ones with NO_ in front, and a space before the newline. RUN_TO_PARITY is on, as by default.
FEATURES = ("PLACE_LAG PLACE_DEADLINE_INITIAL RUN_TO_PARITY NO_NEXT_BUDDY WAKEUP_PREEMPTION "
            "NO_HRTICK NO_HRTICK_DL NONTASK_CAPACITY TTWU_QUEUE SIS_UTIL ")


def fake_root(tmp_path, release="6.8.0-1017-azure", hz="1000", slice_ns="3000000", scaling="1",
              preempt="none (voluntary) full", online="0-7", cpuinfo=AMD,
              clocksource="hyperv_clocksource_tsc_page", features=FEATURES):
    values = {"release": release, "base_slice_ns": slice_ns, "tunable_scaling": scaling,
              "preempt": preempt, "online": online, "cpuinfo": cpuinfo,
              "clocksource": clocksource, "sched_features": features}
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


class TestTheKernelsOwnConstant:

    def test_it_is_recovered_from_the_default_slice(self, tmp_path):
        assert ss.read_settings(fake_root(tmp_path))["normalised_slice_ns"] == 750000

    def test_the_first_azure_kernel_carried_the_smaller_one(self, tmp_path):
        """6.8.0-1064-azure on 8 CPUs reported 2.8 ms, where its version predicts 3 ms."""
        s = ss.read_settings(fake_root(tmp_path, release="6.8.0-1064-azure", slice_ns="2800000"))
        assert s["normalised_slice_ns"] == 700000 and s["rule_slice_ns"] == 3000000

    def test_nothing_is_recovered_from_nothing(self, tmp_path):
        assert ss.read_settings(str(tmp_path))["normalised_slice_ns"] is None


class TestOnlineCpus:

    @staticmethod
    def cpu_tree(tmp_path, listed="0-3", n=4):
        root = fake_root(tmp_path, online=listed)
        base = tmp_path / "sys" / "devices" / "system" / "cpu"
        for i in range(n):
            (base / ("cpu%d" % i)).mkdir(parents=True, exist_ok=True)
            if i:
                (base / ("cpu%d" % i) / "online").write_text("1\n", encoding="utf-8")
        (base / "cpufreq").mkdir(exist_ok=True)
        return root

    def test_cpus_past_the_count_go_offline_and_the_list_is_read_back(self, tmp_path):
        root = self.cpu_tree(tmp_path, listed="0-1")
        assert ss.set_online_cpus(2, root) == 2
        base = tmp_path / "sys" / "devices" / "system" / "cpu"
        assert [(base / ("cpu%d" % i) / "online").read_text(encoding="utf-8")
                for i in (1, 2, 3)] == ["1\n", "0\n", "0\n"]

    def test_a_count_the_kernel_did_not_take_is_refused(self, tmp_path):
        with pytest.raises(ss.CpusNotApplied, match="asked for 2"):
            ss.set_online_cpus(2, self.cpu_tree(tmp_path, listed="0-3"))

    @pytest.mark.parametrize("n", [0, 5])
    def test_a_count_the_machine_cannot_have(self, tmp_path, n):
        with pytest.raises(ValueError, match="cannot have"):
            ss.set_online_cpus(n, self.cpu_tree(tmp_path))

    def test_the_command(self, tmp_path):
        out = io.StringIO()
        assert ss.main(["--root", self.cpu_tree(tmp_path, listed="0-2"), "set-cpus", "3"],
                       out=out) == 0
        assert "3 CPUs online" in out.getvalue()
        out = io.StringIO()
        assert ss.main(["--root", str(tmp_path / "missing"), "set-cpus", "3"], out=out) == 1
        assert out.getvalue().startswith("ERROR:")


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

    def test_a_machine_with_the_wrong_number_of_cpus_is_caught(self, tmp_path):
        """A5's sessions reach their core count at boot, so this is where a wrong one shows up.

        Booting with maxcpus=2 gives a machine that has two CPUs for about a second, and then has
        eight because a udev rule onlines them; the run directory would still say two.
        """
        s = ss.read_settings(fake_root(tmp_path, online="0-7"))
        assert ss.problems(s, cpus=2) == ["8 CPUs are online, not 2"]

    def test_a_machine_with_the_core_count_it_was_asked_for_passes(self, tmp_path):
        s = ss.read_settings(fake_root(tmp_path, online="0-1"))
        assert ss.problems(s, cpus=2) == []

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

    def test_check_can_be_asked_for_a_core_count(self, tmp_path):
        root = fake_root(tmp_path, online="0-7")
        code, text = self.run(["--root", root, "check", "--cpus", "2"])
        assert code == 1 and json.loads(text)["problems"] == ["8 CPUs are online, not 2"]
        code, text = self.run(["--root", root, "check", "--cpus", "8"])
        assert code == 0 and json.loads(text)["ok"] is True

    def test_set_slice(self, tmp_path):
        code, text = self.run(["--root", fake_root(tmp_path), "set-slice", "2250000"])
        assert code == 0 and "2250000 ns, and read back" in text

    def test_set_slice_where_debugfs_is_absent(self, tmp_path):
        code, text = self.run(["--root", str(tmp_path / "nowhere"), "set-slice", "2250000"])
        assert code == 1 and text.startswith("ERROR:")


class TestSchedulerFeatures:
    """Freeze 41 (15 Oct 2026). Block R runs with the scheduler's RUN_TO_PARITY feature on, the
    kernel's default, and off. Every other run is held to on wherever the kernel shows its
    features, so a feature that a crashed run left off fails the next run instead of
    contaminating it; where the kernel shows none, the features are recorded as unknown."""

    def run(self, argv):
        out = io.StringIO()
        return ss.main(argv, out=out), out.getvalue()

    def check(self, root, *args):
        code, text = self.run(["--root", root, "check"] + list(args))
        return code, json.loads(text)

    def test_they_are_read_with_each_off_one_under_its_own_name(self, tmp_path):
        features = ss.read_settings(fake_root(tmp_path))["sched_features"]
        assert features["RUN_TO_PARITY"] is True and features["PLACE_LAG"] is True
        assert features["HRTICK"] is False and features["NEXT_BUDDY"] is False
        assert not [name for name in features if name.startswith("NO_")]
        assert len(features) == 10, "every feature on the line, and nothing else"

    @pytest.mark.parametrize("features", [None, "", " \n"])
    def test_a_kernel_that_shows_none_has_them_recorded_as_unknown(self, tmp_path, features):
        """An older kernel, or a machine without debugfs: named under "missing", not guessed."""
        s = ss.read_settings(fake_root(tmp_path, features=features))
        assert s["sched_features"] is None and s["missing"] == ["sched_features"]
        assert ss.problems(s) == [], "a record nothing was asked of is not a problem"

    def test_one_is_turned_off_and_back_on_and_read_back_each_time(self, tmp_path):
        root = fake_root(tmp_path)
        assert ss.set_feature("NO_RUN_TO_PARITY", root) == "NO_RUN_TO_PARITY"
        assert ss.read_settings(root)["sched_features"]["RUN_TO_PARITY"] is False
        assert ss.set_feature("RUN_TO_PARITY", root) == "RUN_TO_PARITY"
        assert ss.read_settings(root)["sched_features"]["RUN_TO_PARITY"] is True
        written = (tmp_path / ss.FILES["sched_features"]).read_text(encoding="utf-8")
        assert written == "RUN_TO_PARITY\n", "the name alone, as debugfs takes it"

    def test_a_state_the_kernel_did_not_keep_is_refused(self, tmp_path, monkeypatch):
        root = fake_root(tmp_path)
        monkeypatch.setattr(ss, "_read", lambda r, rel: "PLACE_LAG RUN_TO_PARITY")
        with pytest.raises(ss.FeatureNotApplied, match="wrote NO_RUN_TO_PARITY .* read back"):
            ss.set_feature("NO_RUN_TO_PARITY", root)

    def test_features_that_cannot_be_read_back_are_refused_too(self, tmp_path, monkeypatch):
        root = fake_root(tmp_path)
        monkeypatch.setattr(ss, "_read", lambda r, rel: None)
        with pytest.raises(ss.FeatureNotApplied, match="read back None"):
            ss.set_feature("RUN_TO_PARITY", root)

    @pytest.mark.parametrize("name", ["run_to_parity", "NO_", "NO_NO_HRTICK", "RUN TO PARITY",
                                      "", "2DOUBLE_TICK"])
    def test_a_name_that_is_no_features_is_refused_before_anything_is_written(self, tmp_path,
                                                                              name):
        root = fake_root(tmp_path)
        with pytest.raises(ValueError, match="NAME or NO_NAME"):
            ss.set_feature(name, root)
        assert ss.read_settings(root)["sched_features"]["RUN_TO_PARITY"] is True

    def test_a_run_that_asks_for_it_off_is_held_to_off(self, tmp_path):
        root = fake_root(tmp_path)
        code, found = self.check(root, "--feature", "NO_RUN_TO_PARITY")
        assert code == 1 and found["problems"] == [
            "the scheduler feature RUN_TO_PARITY is on, not off"]
        ss.set_feature("NO_RUN_TO_PARITY", root)
        code, found = self.check(root, "--feature", "NO_RUN_TO_PARITY")
        assert code == 0 and found["ok"] is True
        assert found["settings"]["sched_features"] == {"RUN_TO_PARITY": False}, \
            "and the state it was held to is in the record the run keeps"

    def test_a_feature_a_crashed_run_left_off_fails_the_next_run(self, tmp_path):
        """The hold every run without a feature of its own is under."""
        left = FEATURES.replace(" RUN_TO_PARITY", " NO_RUN_TO_PARITY")
        code, found = self.check(fake_root(tmp_path / "left", features=left),
                                 "--feature-if-known", "RUN_TO_PARITY")
        assert code == 1 and found["problems"] == [
            "the scheduler feature RUN_TO_PARITY is off, not on"]
        code, found = self.check(fake_root(tmp_path / "default"),
                                 "--feature-if-known", "RUN_TO_PARITY")
        assert code == 0 and found["problems"] == []

    @pytest.mark.parametrize("features", [None, "PLACE_LAG NO_HRTICK"])
    def test_a_kernel_that_cannot_show_it_holds_no_run_to_the_default(self, tmp_path, features):
        """No features to be read, or an older kernel that has no RUN_TO_PARITY at all."""
        code, found = self.check(fake_root(tmp_path, features=features),
                                 "--feature-if-known", "RUN_TO_PARITY")
        assert code == 0 and found["problems"] == []

    @pytest.mark.parametrize("features,said", [
        (None, "the scheduler's features could not be read"),
        ("PLACE_LAG NO_HRTICK", "the kernel has no scheduler feature RUN_TO_PARITY")])
    def test_but_a_run_that_asks_for_one_by_name_is_held_to_it_there_too(self, tmp_path,
                                                                         features, said):
        code, found = self.check(fake_root(tmp_path, features=features),
                                 "--feature", "NO_RUN_TO_PARITY")
        assert code == 1 and found["problems"] == [said]

    def test_a_name_that_is_no_features_stops_the_command_before_it_reads(self, tmp_path,
                                                                         capsys):
        for argv in (["check", "--feature", "no_run_to_parity"],
                     ["check", "--feature-if-known", "NO_"], ["set-feature", "RUN TO PARITY"]):
            with pytest.raises(SystemExit) as stopped:
                ss.main(["--root", fake_root(tmp_path)] + argv, out=io.StringIO())
            assert stopped.value.code == 2, argv
            assert "NAME or NO_NAME" in capsys.readouterr().err

    def test_set_feature(self, tmp_path):
        code, text = self.run(["--root", fake_root(tmp_path), "set-feature", "NO_RUN_TO_PARITY"])
        assert code == 0 and "scheduler feature NO_RUN_TO_PARITY set, and read back" in text
        code, text = self.run(["--root", str(tmp_path / "nowhere"), "set-feature",
                               "RUN_TO_PARITY"])
        assert code == 1 and text.startswith("ERROR:")
