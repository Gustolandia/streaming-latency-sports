"""The Azure kit's files that are not Python: the machine setup, the shell scripts, the guide.

They run on machines this suite never sees, so what can be checked here is what breaks them
silently there: a CRLF line ending, a script that carries on after an error it should stop at, a
setup file that is not cloud-config, and a guide that names a file that does not exist.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
KIT = REPO / "cloud" / "azure"
SHELL = sorted(KIT.glob("*.sh"))

sys.path.insert(0, str(REPO / "scripts"))
import testbed_watch  # noqa: E402


def test_the_kit_has_the_scripts_the_guide_describes():
    assert [p.name for p in SHELL] == ["campaign.sh", "pilot.sh", "replicate_oracle.sh",
                                       "session.sh", "stage0.sh"]


@pytest.mark.parametrize("path", SHELL + [KIT / "cloud-init.yaml"], ids=lambda p: p.name)
def test_every_file_a_linux_machine_reads_has_lf_endings(path):
    assert b"\r" not in path.read_bytes()


def test_the_machine_setup_is_cloud_config_with_the_campaign_tools():
    text = (KIT / "cloud-init.yaml").read_text(encoding="utf-8")
    assert text.startswith("#cloud-config\n")
    for package in ("docker.io", "chrony", "stress-ng", "bpftrace", "iputils-ping"):
        assert "  - %s\n" % package in text, package
    assert "github.com/Gustolandia/streaming-latency-sports.git" in text
    assert "pip3 freeze >" in text, "the installed versions are written down"
    assert "/var/lib/sbl-cloud-init-done" in text, "session.sh waits for this marker"
    assert "/var/lib/sbl-cloud-init-done" in (KIT / "session.sh").read_text(encoding="utf-8")


@pytest.mark.parametrize("path", SHELL, ids=lambda p: p.name)
def test_every_script_stops_on_errors_or_says_why_it_does_not(path):
    """The driver scripts carry on past a failing check on purpose, like every campaign."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text or ("campaigns/common.sh" in text and "set +e" in text)


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"),
                    reason="bash -n needs a POSIX bash")
@pytest.mark.parametrize("path", SHELL, ids=lambda p: p.name)
def test_bash_parses_it(path):
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0


def test_the_pilot_uses_the_hook_the_trial_runners_read():
    pilot = (KIT / "pilot.sh").read_text(encoding="utf-8")
    assert 'SBL_CONSUMER_WRAP="sudo ip netns exec sblrecv' in pilot
    for runner in ("run_kafka_trial.sh", "run_redis_trial.sh"):
        assert "SBL_CONSUMER_WRAP" in (REPO / "scripts" / runner).read_text(encoding="utf-8")


def test_stage_0_runs_its_steps_in_order_each_gated_on_the_last():
    """The chain runs unattended for hours, so its order and its gates are checked here."""
    code = (KIT / "stage0.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    order = ["bash cloud/azure/pilot.sh", "pilot_checks.py shakedown", "sched_settings.py read",
             "design C0", "delay_calibration.py fit", "design B0", '[ "$FIT" = 0 ] ||',
             "design P0"]
    places = [code.index(step) for step in order]
    assert places == sorted(places), "the steps run in the plan's order"
    assert "first) UP_TO_MS=16; C0_ROUNDS=4 ;;" in code, "the first pair's C0 is the staircase"
    assert 'campaign "p0_$START" "$DIR/calibration.json"' in code, "P0 is held to the calibration"
    assert code.rstrip().endswith('its queues and files are in $DIR"')


def test_the_watch_counts_the_chain_as_a_campaign():
    """Between two campaigns the chain runs no campaign.sh, and a watch that took that for idle
    would deallocate the pair in the middle of stage 0."""
    assert "cloud/azure/stage0.sh" in testbed_watch.DRIVER_PROBE


#: Files the guide names that the kit writes rather than ships, and why. Each must be ignored by
#: git, so an entry here cannot hide a committed file that went missing.
WRITTEN = {
    "cloud/hosts.env": "written by scripts/azure_testbed.py hosts; the addresses belong to one "
                       "provisioning and are never committed",
    "cloud/hosts_b.env": "written by scripts/azure_testbed.py hosts --profile matched-b; the "
                         "second pair's addresses, never committed either",
    "cloud/hosts_arm.env": "written by scripts/azure_testbed.py hosts --profile arm; the Arm "
                           "pair's addresses, never committed either",
}


def _named_in_guide():
    text = (KIT / "README.md").read_text(encoding="utf-8")
    return set(re.findall(r"`((?:scripts|cloud)/[\w./-]+)`", text))


def test_the_guide_names_only_files_that_exist():
    named = _named_in_guide()
    assert len(named) >= 10, "the guide points at the files it describes"
    missing = sorted(p for p in named if p not in WRITTEN and not (REPO / p).exists())
    assert not missing, missing


def test_every_written_file_is_named_and_ignored_by_git():
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    for path, why in WRITTEN.items():
        assert path in _named_in_guide(), "a stale exemption: %s" % path
        assert path in ignored, "%s is exempt as written, not shipped, so git must ignore it" % path
        assert len(why) > 20


def test_the_guide_lists_every_file_in_the_kit():
    text = (KIT / "README.md").read_text(encoding="utf-8")
    for path in sorted(KIT.iterdir()):
        if path.name != "README.md":
            assert "`cloud/azure/%s`" % path.name in text, path.name


def test_the_testbed_file_sends_this_setup_file():
    spec = json.loads((KIT / "testbed.json").read_text(encoding="utf-8"))
    assert spec["custom_data"] == "cloud/azure/cloud-init.yaml"
