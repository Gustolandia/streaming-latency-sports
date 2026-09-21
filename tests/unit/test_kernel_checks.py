"""The checks a kernel we built ourselves must pass before A2 runs on it.

A2 rests on three kernels differing in nothing but the tick, and on each machine really running
at the tick its config claims. A config file cannot establish either: a kernel can be configured
for 250 Hz and boot at something else, and two builds can agree on HZ and differ elsewhere. So
the tick is counted and the rest is read back, and a kernel that fails any of it does not run.
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import kernel_checks as kc  # noqa: E402

FEATURES_OFF = "GENTLE_FAIR_SLEEPERS NO_HRTICK NO_HRTICK_DL NO_DOUBLE_TICK START_DEBIT"
FEATURES_ON = "GENTLE_FAIR_SLEEPERS HRTICK NO_HRTICK_DL NO_DOUBLE_TICK START_DEBIT"
CONFIG = ("CONFIG_HZ=250\nCONFIG_NO_HZ=y\nCONFIG_NO_HZ_IDLE=y\nCONFIG_NO_HZ_COMMON=y\n"
          "CONFIG_HIGH_RES_TIMERS=y\n")


def interrupts(counts):
    return ("           CPU0       CPU1\n"
            "  0:         41          0   IO-APIC   2-edge      timer\n"
            " LOC:  %s   Local timer interrupts\n" % "   ".join(str(n) for n in counts))


class TestTheSliceTimer:

    def test_it_is_off_when_the_kernel_says_no_hrtick(self):
        assert kc.hrtick_on(FEATURES_OFF) is False

    def test_it_is_on_when_the_kernel_says_hrtick(self):
        assert kc.hrtick_on(FEATURES_ON) is True

    def test_hrtick_dl_alone_is_not_the_one_the_plan_asks_about(self):
        """HRTICK_DL times deadline tasks; the slice is HRTICK, and NO_HRTICK means off."""
        assert kc.hrtick_on("NO_HRTICK HRTICK_DL") is False

    def test_a_kernel_that_does_not_say_is_not_guessed_at(self):
        assert kc.hrtick_on("") is None
        assert kc.hrtick_on("GENTLE_FAIR_SLEEPERS START_DEBIT") is None


class TestCountingTheTick:

    def test_the_counted_tick_is_ticks_over_seconds(self):
        before = kc.local_timer_counts(interrupts([1000, 500]))
        after = kc.local_timer_counts(interrupts([3500, 600]))
        assert kc.measured_hz(before, after, 10.0) == 250.0

    def test_it_counts_the_busiest_cpu_because_an_idle_one_stops_its_tick(self):
        before = kc.local_timer_counts(interrupts([1000, 1000]))
        after = kc.local_timer_counts(interrupts([1010, 3500]))
        assert kc.measured_hz(before, after, 10.0) == 250.0

    def test_a_named_cpu_is_counted_instead(self):
        before = kc.local_timer_counts(interrupts([1000, 1000]))
        after = kc.local_timer_counts(interrupts([1010, 3500]))
        assert kc.measured_hz(before, after, 10.0, cpu=0) == 1.0

    def test_a_kernel_with_no_local_timer_line_gives_nothing(self):
        assert kc.local_timer_counts("  0:  41  IO-APIC  timer\n") == {}
        assert kc.measured_hz({}, {}, 10.0) is None

    @pytest.mark.parametrize("before,after,seconds", [
        ({0: 1}, {}, 10.0), ({}, {0: 1}, 10.0), ({0: 1}, {0: 2}, 0.0),
    ])
    def test_nothing_to_divide_gives_nothing(self, before, after, seconds):
        assert kc.measured_hz(before, after, seconds) is None

    def test_a_count_that_went_backwards_is_refused(self):
        """A counter that wrapped or a reading taken out of order is not a tick."""
        assert kc.measured_hz({0: 500}, {0: 100}, 10.0) is None

    def test_a_cpu_seen_only_afterwards_is_left_out(self):
        assert kc.measured_hz({0: 0}, {0: 2500, 1: 9}, 10.0) == 250.0

    def test_two_readings_sharing_no_cpu_give_nothing(self):
        """Not a tick of zero: there is no CPU whose count can be differenced at all."""
        assert kc.measured_hz({0: 1000}, {1: 3500}, 10.0) is None


class TestTheTicklessSettings:

    def test_it_reads_the_settings_the_three_builds_must_share(self):
        found = kc.nohz_settings(CONFIG)
        assert found["CONFIG_NO_HZ_IDLE"] == "y" and found["CONFIG_HIGH_RES_TIMERS"] == "y"
        assert found["CONFIG_NO_HZ_FULL"] is None, "absent is recorded as absent, not as off"

    def test_every_key_is_reported_even_from_nothing(self):
        assert set(kc.nohz_settings("")) == set(kc.NOHZ_KEYS)


class TestWhatStopsAKernelRunning:

    def reading(self, **over):
        base = {"settings": {"config_hz": 250, "base_slice_ns": 3000000},
                "nohz": kc.nohz_settings(CONFIG), "hrtick_on": False, "measured_hz": 249.4}
        base.update(over)
        return base

    def test_a_kernel_that_shows_everything_may_run(self):
        assert kc.problems(self.reading(), hz=250, slice_ns=3000000) == []

    def test_the_wrong_kernel_for_this_campaign_is_caught(self):
        wrong = kc.problems(self.reading(), hz=1000)
        assert any("reports HZ=250" in one for one in wrong)

    def test_the_high_resolution_slice_timer_being_on_voids_it(self):
        wrong = kc.problems(self.reading(hrtick_on=True), hz=250)
        assert any("would measure nothing" in one for one in wrong)

    def test_not_knowing_whether_it_is_on_is_not_the_same_as_it_being_off(self):
        wrong = kc.problems(self.reading(hrtick_on=None), hz=250)
        assert any("could not be read" in one for one in wrong)

    def test_a_tick_that_does_not_run_at_its_setting_is_caught(self):
        """The check a config file cannot make: configured for 250 and running at 100."""
        wrong = kc.problems(self.reading(measured_hz=100.0), hz=250)
        assert any("counted 100.0 Hz" in one and "60.0% out" in one for one in wrong)

    def test_a_tick_inside_the_plan_s_tolerance_passes(self):
        assert kc.problems(self.reading(measured_hz=250 * 1.049), hz=250) == []
        assert kc.problems(self.reading(measured_hz=250 * 1.051), hz=250) != []

    def test_a_tick_that_could_not_be_counted_at_all_is_caught(self):
        wrong = kc.problems(self.reading(measured_hz=None), hz=250)
        assert any("does not say what the machine is running" in one for one in wrong)

    def test_it_measures_against_the_running_kernel_when_none_is_asked_for(self):
        assert kc.problems(self.reading(measured_hz=100.0)) != []

    def test_a_kernel_that_reports_no_hz_at_all_is_not_measured_against_nothing(self):
        reading = self.reading(settings={"config_hz": None}, measured_hz=100.0)
        assert kc.problems(reading) == []

    def test_a_slice_that_did_not_take_is_caught(self):
        wrong = kc.problems(self.reading(), hz=250, slice_ns=1500000)
        assert any("reads back as 3000000 ns" in one for one in wrong)

    def test_builds_that_differ_in_more_than_the_tick_are_caught(self):
        other = dict(kc.nohz_settings(CONFIG), CONFIG_NO_HZ_FULL="y")
        wrong = kc.problems(self.reading(), hz=250, nohz_like=other)
        assert any("differ in more than the tick" in one for one in wrong)

    def test_builds_that_match_are_not(self):
        assert kc.problems(self.reading(), hz=250, nohz_like=kc.nohz_settings(CONFIG)) == []


class TestReadingAMachine:

    def machine(self, tmp_path, features=FEATURES_OFF, config=CONFIG, ticks=(0, 2500)):
        root = tmp_path
        (root / "boot").mkdir()
        (root / "proc").mkdir()
        (root / "sys/kernel/debug/sched").mkdir(parents=True)
        (root / "boot" / "config-6.8.0-1064-azure").write_text(config, encoding="utf-8")
        (root / "sys/kernel/debug/sched/features").write_text(features, encoding="utf-8")
        self.step = iter(ticks)
        return root

    def test_it_counts_across_the_wait_and_reports_what_it_found(self, tmp_path, monkeypatch):
        root = self.machine(tmp_path)
        counts = iter([interrupts([1000]), interrupts([3500])])
        monkeypatch.setattr(kc, "_slurp", lambda path: (
            next(counts) if path.endswith("interrupts") else
            open(path, encoding="utf-8").read() if os.path.exists(path) else ""))
        monkeypatch.setattr(kc.sched_settings, "read_settings",
                            lambda r: {"release": "6.8.0-1064-azure", "config_hz": 250,
                                       "base_slice_ns": 3000000})
        clock = iter([100.0, 110.0, 110.0])
        found = kc.read(str(root), seconds=10.0, sleep=lambda s: None, now=lambda: next(clock))
        assert found["measured_hz"] == 250.0 and found["hrtick_on"] is False
        assert found["counted_for_s"] == 10.0
        assert found["nohz"]["CONFIG_NO_HZ_IDLE"] == "y"

    def test_the_feature_list_can_come_from_a_file_read_with_sudo(self, tmp_path, monkeypatch):
        """debugfs is 0700 root, so the live path gives an unprivileged reader nothing.

        Reading it with sudo and passing the file must reach the same verdict; otherwise every
        check reports HRTICK "could not be read", which looks like a fault in the kernel.
        """
        root = self.machine(tmp_path, features=FEATURES_ON)   # what an unprivileged read cannot see
        elsewhere = tmp_path / "from-sudo.txt"
        elsewhere.write_text(FEATURES_OFF, encoding="utf-8")
        monkeypatch.setattr(kc.sched_settings, "read_settings",
                            lambda r: {"release": "6.8.0-1064-azure", "config_hz": 250})
        clock = iter([100.0, 110.0, 110.0])
        found = kc.read(str(root), seconds=10.0, sleep=lambda s: None, now=lambda: next(clock),
                        features_from=str(elsewhere))
        assert found["hrtick_on"] is False

    def test_without_that_file_it_still_reads_the_machine_s_own(self, tmp_path, monkeypatch):
        root = self.machine(tmp_path, features=FEATURES_ON)
        monkeypatch.setattr(kc.sched_settings, "read_settings",
                            lambda r: {"release": "6.8.0-1064-azure", "config_hz": 250})
        clock = iter([100.0, 110.0, 110.0])
        found = kc.read(str(root), seconds=10.0, sleep=lambda s: None, now=lambda: next(clock))
        assert found["hrtick_on"] is True

    def test_a_file_it_cannot_read_is_empty_rather_than_an_error(self, tmp_path):
        assert kc._slurp(str(tmp_path / "nothing")) == ""

    def test_a_file_it_can_read_comes_back_whole(self, tmp_path):
        path = tmp_path / "features"
        path.write_text(FEATURES_OFF, encoding="utf-8")
        assert kc._slurp(str(path)) == FEATURES_OFF


class TestTheCommand:

    def run(self, argv, monkeypatch, reading, seen=None):
        def fake(root, seconds, features_from=None):
            if seen is not None:
                seen.append(features_from)
            return reading
        monkeypatch.setattr(kc, "read", fake)
        out = io.StringIO()
        return kc.main(argv, out), out.getvalue()

    READING = {"settings": {"config_hz": 250, "base_slice_ns": 3000000},
               "nohz": {"CONFIG_NO_HZ": "y"}, "hrtick_on": False, "measured_hz": 250.0}

    def test_read_prints_what_the_machine_shows(self, monkeypatch):
        code, text = self.run(["read"], monkeypatch, self.READING)
        assert code == 0 and json.loads(text)["measured_hz"] == 250.0

    def test_check_passes_a_kernel_that_is_what_it_says(self, monkeypatch):
        code, text = self.run(["check", "--hz", "250", "--slice-ns", "3000000"],
                              monkeypatch, self.READING)
        assert code == 0 and json.loads(text)["ok"] is True

    def test_check_fails_and_says_why(self, monkeypatch):
        code, text = self.run(["check", "--hz", "1000"], monkeypatch, self.READING)
        found = json.loads(text)
        assert code == 1 and found["ok"] is False
        assert any("HZ=250" in one for one in found["problems"])

    def test_the_file_read_with_sudo_is_handed_to_the_reader(self, monkeypatch):
        """The shell does the sudo; the path it read into must actually reach read()."""
        seen = []
        code, _ = self.run(["check", "--hz", "250", "--features-from", "/tmp/feats.txt"],
                           monkeypatch, self.READING, seen)
        assert code == 0 and seen == ["/tmp/feats.txt"]

    def test_not_naming_one_leaves_the_reader_to_the_machine(self, monkeypatch):
        seen = []
        self.run(["check", "--hz", "250"], monkeypatch, self.READING, seen)
        assert seen == [None]

    def test_it_can_be_held_to_another_build_s_tickless_settings(self, monkeypatch, tmp_path):
        other = tmp_path / "hz1000.json"
        other.write_text(json.dumps({"nohz": {"CONFIG_NO_HZ": "n"}}), encoding="utf-8")
        code, text = self.run(["check", "--hz", "250", "--nohz-like", str(other)],
                              monkeypatch, self.READING)
        assert code == 1 and any("more than the tick" in one
                                 for one in json.loads(text)["problems"])
