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
    assert [p.name for p in SHELL] == ["a2_session.sh", "campaign.sh", "chain.sh", "cpus.sh",
                                       "kernels.sh",
                                       "machine_facts.sh", "pilot.sh", "replicate_oracle.sh",
                                       "session.sh", "stage0.sh", "stage1.sh", "tools.sh",
                                       "tools_run.sh"]


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
             "design C0", "delay_calibration.py fit", "design B0", "so P0 cannot be placed",
             "design P0"]
    places = [code.index(step) for step in order]
    assert places == sorted(places), "the steps run in the plan's order"
    assert 'first) UP_TO_MS="${UP_TO_MS:-16}"; C0_ROUNDS=4 ;;' in code, (
        "the first pair's C0 is the staircase, and a session may ask for a longer one")
    assert 'campaign "p0_$START" "$DIR/calibration.json"' in code, "P0 is held to the calibration"
    assert "p0)" not in code and "freeze02" not in code, "no session carries on across a rule change"
    assert code.rstrip().endswith('its queues and files are in $DIR"')


def test_stage_1_runs_one_campaign_of_a_block_from_a_finished_stage_0():
    """A block is not a sitting: each campaign is placed from a stage 0 that passed, runs the
    rounds it is given, and says in its own log where that number came from."""
    code = (KIT / "stage1.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    order = ['cp "$STAGE0/$f" "$DIR/$f"', 'yield bool(node["gate"].get("ok"))',
             'log "rounds: $ROUNDS"', "law_design.py design", "run_queue.py make",
             "bash cloud/azure/campaign.sh", "CAMPAIGN_COMPLETE"]
    places = [code.index(step) for step in order]
    assert places == sorted(places), "the steps run in the plan's order"
    assert code.index('log "rounds: $ROUNDS"') < code.index("law_design.py design"), \
        "the rounds are in the log before the campaign is even designed"
    assert 'log "rounds from: $ROUNDS_NOTE"' in code, "and where the number came from"


def test_stage_1_will_not_place_a_campaign_from_a_calibration_that_failed():
    code = (KIT / "stage1.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    assert "did not pass its gate on every backend" in code
    assert code.index('yield bool(node["gate"].get("ok"))') < code.index("law_design.py design")


def test_stage_1_needs_the_block_the_rounds_and_the_session_it_comes_from():
    code = (KIT / "stage1.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    assert '[ -z "$BLOCK" ] || [ -z "$ROUNDS" ] || [ -z "$STAGE0" ]' in code
    assert "exit 2" in code, "it says how it is used rather than guessing"


def test_a_session_that_only_needs_its_calibration_stops_after_the_fit():
    """The plan asks every session for its own calibration, because a machine that was stopped and
    started can come back on another host. The baseline trips and the spread pilot belong to the
    pair, and repeating them would cost four hours a pair does not owe."""
    code = (KIT / "stage0.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    assert 'session) UP_TO_MS="${UP_TO_MS:-8}"; C0_ROUNDS="${C0_ROUNDS:-2}" ;;' in code, (
        "a session calibrates to 8 ms unless its campaign needs further")
    ends = code.split('if [ "$KIND" = session ]; then', 1)[1].split("\nfi\n", 1)[0]
    assert "CAMPAIGN_COMPLETE: the session's calibration passed" in ends
    assert "exit 0" in ends
    assert code.index('if [ "$KIND" = session ]; then') < code.index('design B0'), \
        "it stops before the baseline trips"
    assert code.index("delay_calibration.py fit") < code.index('if [ "$KIND" = session ]; then')


def test_a_second_stage_of_the_calibration_is_open_to_every_pair_but_the_first():
    """Only the first pair's staircase runs four rounds outright; every other session may need
    two more when its calibration is too loosely known."""
    code = (KIT / "stage0.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    assert 'if [ "$KIND" != first ]; then' in code


def test_a_later_session_repeats_the_network_part_of_its_shakedown():
    """A start after a stop can put a machine on another physical host: on 17 September the
    second x86 pair's two paths differed by 0.13 ms, where they had differed by 0.44 ms."""
    code = (KIT / "stage0.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    assert 'json.load(open(sys.argv[1]))["ok"]' in code
    assert 'cp "$EARLIER/shakedown.json" "$DIR/shakedown_earlier.json"' in code
    earlier = code.split('if [ -n "$EARLIER" ]; then', 1)[1].split("\nelse\n", 1)[0]
    assert 'PARTS=network bash cloud/azure/pilot.sh' in earlier and 'CHECKS="network"' in earlier
    assert 'CHECKS="settings,network,never_negative,load"' in code
    assert '--checks "$CHECKS" > "$DIR/shakedown.json"' in code


def test_the_calibration_runs_two_more_rounds_only_when_only_its_precision_failed():
    code = (KIT / "stage0.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    stage = code.split('if [ "$KIND" != first ]; then', 1)[1].split("\n  fi\n", 1)[0]
    order = ['--out "$DIR/calibration_first_stage$tag.json"', "delay_calibration.py needs-rounds",
             'design C0 "c0b$tag" "${SEED}4"', "--rounds 2 --first-round 3",
             'campaign "c0b$tag"', 'C0_QUEUES+=(--queue "$DIR/c0b$tag.csv")']
    places = [stage.index(step) for step in order]
    assert places == sorted(places)
    # Each client fits its own, and only then is the file law_design reads made: copied where
    # there is one client, joined where there are two.
    final = code.split(stage, 1)[1]
    assert final.index('fit "${C0_QUEUES[@]}"') < final.index('--out "$DIR/calibration$tag.json"')
    assert 'cp "$DIR/calibration_$START.json" "$DIR/calibration.json"' in final


def test_a_client_calibrates_only_the_backends_its_runner_can_dispatch_to():
    """Only the Kafka runner takes -CLIENT. A Redis run asked for Java quietly runs the Python
    client and is written down under Java's name, and a calibration mislabelled that way is worse
    than one not taken. This pins the coupling: if the Redis runner ever learns to dispatch on
    the client, this test fails and stage0.sh is revisited rather than silently left wrong."""
    redis = (REPO / "scripts" / "run_redis_trial.sh").read_text(encoding="utf-8")
    kafka = (REPO / "scripts" / "run_kafka_trial.sh").read_text(encoding="utf-8")
    assert "-CLIENT" in kafka, "the Kafka runner is the one that dispatches on the client"
    assert "-CLIENT" not in redis, (
        "the Redis runner now takes a client, so stage0.sh must stop restricting a named client "
        "to Kafka")
    code = (KIT / "stage0.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    assert '[ "$client" = python ] || args+=(--backend kafka)' in code


def test_the_calibration_takes_its_got_it_note_where_the_clients_default_to():
    """run_integrity.CALIBRATED_AT says every calibration is a callback one, and the got-it
    brake now leans on that. What makes it true is that stage 0 never asks for another: it
    passes the client and nothing else about how the note is taken."""
    sys.path.insert(0, str(REPO / "scripts"))
    import run_integrity
    stage0 = (KIT / "stage0.sh").read_text(encoding="utf-8")
    assert "--ack-stamp" not in stage0 and "ACK_STAMP" not in stage0
    producer = (REPO / "scripts" / "kafka_producer.py").read_text(encoding="utf-8")
    assert '"--ack-stamp", default="%s"' % run_integrity.CALIBRATED_AT in producer


class TestChainingACampaignBehindItsCalibration:
    """A pair that finishes its calibration and waits for someone to notice is a pair billing for
    nothing. Chaining it from a laptop works until the laptop closes: the calibration finishes,
    the campaign never starts, and the watch deallocates the pair half an hour later having
    learned nothing. This runs on the driver instead."""

    def chain(self):
        return (KIT / "chain.sh").read_text(encoding="utf-8")

    def test_it_waits_on_the_calibration_and_starts_nothing_if_it_failed(self):
        code = self.chain()
        assert "CAMPAIGN_COMPLETE: the session's calibration passed" in code
        assert "the session stopped, so no campaign starts" in code
        assert code.index("the session stopped") < code.index("bash cloud/azure/stage1.sh")

    def test_a_campaign_never_runs_at_a_number_nobody_set(self):
        assert "give either --rounds or --rounds-from" in self.chain()

    def test_the_backend_on_the_command_line_reaches_the_rounds_rule(self):
        """The levels the rounds are simulated from belong to one backend.

        They were read from BACKEND in the environment while the campaign took its backend from
        the command line, so asking for a Redis campaign simulated its rounds at Kafka's levels
        and wrote that into a note that reads like a measurement.
        """
        code = self.chain()
        assert '--backend) BACKEND="$2"' in code, "--backend must set the backend it simulates at"
        assert 'ARGS+=("$1" "$2")' in code, "and must still reach law_design"

    def test_the_rounds_are_simulated_for_the_block_that_will_run(self):
        """The design goes by name, not written out here, because written out it was wrong.

        Three loads and the default nine points for every block: A3 runs six points, A8 runs one
        load and two clients, and P8 compares those clients. In a world with none it confirmed in
        0% of campaigns at every round count, and the chain refused to start a sound campaign.
        """
        code = self.chain()
        assert '--block "$BLOCK"' in code
        assert "--loads 50,75,88" not in code, "the loads belong to the block, not to the chain"

    def test_the_previous_campaigns_console_log_is_kept(self):
        """It is the only record of what the driver printed while that campaign ran.

        A3's Kafka campaign finished with 216 runs and its Redis campaign was chained behind it;
        the line that made room for the new log would have taken the old one with it.
        """
        code = self.chain()
        assert "rm -f stage1.log" not in code, "the previous campaign's log is moved, not removed"
        assert 'mv stage1.log "$kept"' in code

    def test_one_backend_at_a_time_when_the_rounds_are_simulated(self):
        code = self.chain()
        assert "--rounds-from simulates at one backend's levels" in code
        assert code.index("BACKENDS_NAMED=0") < code.index('--backend) BACKEND="$2"')

    def test_the_rounds_can_be_simulated_from_the_pairs_own_spread_pilot(self):
        code = self.chain()
        assert "law_design.py rounds" in code and "rounds_rule.py for" in code
        assert code.index("the calibration passed") < code.index("law_design.py rounds"), \
            "simulated only once the calibration is done: a simulation beside a measurement " \
            "changes what is measured"

    def test_a_rule_that_never_confirms_starts_no_campaign(self):
        """P8 once confirmed in 0% of simulated campaigns at every round count, and the rule
        reported that as forty rounds and underpowered -- 1,440 runs to learn nothing."""
        code = self.chain()
        assert 'found.get("broken")' in code
        assert "the rounds rule gave no number" in code

    def test_the_note_says_what_set_the_number(self):
        code = self.chain()
        assert "ROUNDS_NOTE=" in code and "--rounds-note" in code
        assert "the spread pilot measured on this pair" in code


def test_a_campaign_is_placed_only_from_a_calibration_measured_on_this_boot():
    """Stage 0 says a stopped-and-started pair needs its own calibration, because it can come
    back on another host. On 21 September A8 was placed from one fitted at 22:28 on a pair that
    booted again at 00:48, and the got-it brake stopped it three runs in. The brake was right;
    nothing had said that placing the campaign at all was the mistake."""
    stage1 = (KIT / "stage1.sh").read_text(encoding="utf-8")
    assert "uptime -s" in stage1 and 'date -u -r "$STAGE0/calibration.json"' in stage1
    assert "before this" in stage1 and "needs a new session" in stage1
    assert stage1.index("uptime -s") < stage1.index("law_design.py design"), \
        "checked before the design is made, not after the runs are placed"


def test_a_campaign_says_which_runs_the_got_it_brake_can_judge_before_it_runs():
    """A8 takes its note two ways and a calibration takes it one way, so half its runs have no
    like-for-like baseline. On the Arm pair that was found on the third run, hours in, by the
    campaign stopping itself. It is now counted from the queue before anything runs."""
    stage1 = (KIT / "stage1.sh").read_text(encoding="utf-8")
    assert "gotit_brake.txt" in stage1
    assert "run_integrity.gotit_comparable" in stage1, "one rule, not a second copy of it"
    assert "no like-for-like baseline" in stage1
    assert stage1.index("gotit_brake.txt") < stage1.index("bash cloud/azure/campaign.sh"), \
        "counted before the campaign is launched, not after it stops itself"


def test_a_session_that_calibrates_twice_keeps_the_two_apart():
    """A8 compares two clients, and the delay's effect on the trip belongs to the client (D4-9),
    so law_design refuses to place one client's trips from the other's fit. Both C0s, both fits
    and both first-stage records carry the client in their name, or the second would write over
    the first."""
    code = (KIT / "stage0.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    assert 'CLIENTS="${CLIENTS:-}"' in code
    assert 'for client in $CLIENTS; do' in code
    assert 'calibrate "$client" "_${client}_$START"' in code
    for named in ('"c0$tag"', '"$DIR/calibration$tag.json"', '"$DIR/fit$tag.txt"',
                  '"$DIR/calibration_first_stage$tag.json"'):
        assert named in code, named
    # Only a session opens A8, and B0 and P0 would be handed a calibration keyed by client.
    assert '[ -n "$CLIENTS" ] && [ "$KIND" != session ]' in code


def test_a_session_leaves_nothing_of_its_own_on_a_machine():
    """On 17 September a patch tried on a machine before a freeze stayed on its broker."""
    session = (KIT / "session.sh").read_text(encoding="utf-8")
    step = session.split("== 4/8", 1)[1].split("== 5/8", 1)[0]
    assert "git checkout --quiet --force --detach $COMMIT" in step
    assert "git status --porcelain --untracked-files=no" in step


def test_nothing_upgrades_itself_under_a_campaign():
    """On 16 September an automatic upgrade restarted the driver's network service mid-pilot."""
    session = (KIT / "session.sh").read_text(encoding="utf-8")
    assert ("systemctl disable --now unattended-upgrades.service apt-daily.timer "
            "apt-daily-upgrade.timer") in session
    assert "APT::Periodic::Unattended-Upgrade" in session
    setup = (KIT / "cloud-init.yaml").read_text(encoding="utf-8")
    assert 'APT::Periodic::Unattended-Upgrade "0";' in setup
    assert "systemctl disable --now unattended-upgrades.service" in setup


def test_every_run_checks_the_machine_and_its_zero_delay_baseline_first():
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").split("run_one () {", 1)[1]
    order = ['grep -q " ${RECEIVER_IP}/"', "sudo ip netns exec sblrecv ip -o -4 addr show",
             'ping -n -c 2 -W 1 "$BROKER_PRIV"', "sudo fuser /var/lib/dpkg/lock-frontend",
             "sched_settings.py set-cpus", "broker_delay 0", "delay_baseline.json",
             'broker_delay "$DELAY_MS"', "delay_measured.json"]
    places = [code.index(step) for step in order]
    assert places == sorted(places)


def test_a_run_writes_only_into_a_folder_of_its_own():
    """Queue keys repeat from one queue to the next. On 16 September a restarted calibration wrote
    its first run into the folder of the attempt before it, and the watch saw a 35-minute trip."""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8")
    assert 'QUEUE_NAME="$(basename "$QUEUE" .csv)"' in code
    loop = code.split('RUN_ID="law_${QUEUE_NAME}_$KEY"', 1)[1]
    assert loop.index('if [ -e "$RUN_DIR" ]; then') < loop.index('mkdir -p "$RUN_DIR"')


def test_the_pilot_checks_the_delay_where_the_broker_adds_it():
    """Plan v6: the broker's own capture decides 0.05 ms, ping checks the delay end to end at the
    limit every run is held to, and five zero-delay readings check that the two paths agree."""
    pilot = (KIT / "pilot.sh").read_text(encoding="utf-8")
    network = pilot.split("if part network; then", 1)[1].split("# --- 3. harness", 1)[0]
    order = ["bash cloud/azure/machine_facts.sh", 'remote_broker "cd sbl && bash cloud/azure/machine_facts.sh"',
             "tcpdump -i eth0", "receiver_delay.py measure", 'wait "$capture"',
             "receiver_delay.py holds", 'for i in 1 2 3 4 5; do', "pilot_checks.py paths",
             "verdict paths", "0.25 + 0.05 * float", "receiver_delay.py verify-hold",
             '--tolerance-ms "$TOL"', 'if [ "$HELD" = 0 ]; then']
    places = [network.index(step) for step in order]
    assert places == sorted(places)
    assert 'PARTS="${PARTS:-settings network harness go-first}"' in pilot
    for name in ("settings", "network", "harness", "go-first"):
        assert "if part %s; then" % name in pilot, name
    assert '--redis-consumer-extra "$REDIS_CONSUMER_EXTRA"' in pilot
    assert '"$SEEN" = 0' not in network.split("verdict network", 1)[0], (
        "only the broker's own capture decides the delay (plan v7)")
    for tool in ("sockperf ping-pong --tcp", "sockperf ping-pong -i",
                 'sudo ip netns exec sblrecv sockperf', '"$OUT/sockperf_tcp_host.txt"',
                 '"$OUT/sockperf_udp_receiver.txt"'):
        assert tool in network, tool


def test_the_paths_are_recorded_and_the_treatment_is_judged():
    """Plan v7: ping reads about half a millisecond above our messages' round trip, and in the
    receiver's namespace it shows a difference of 0.28 ms that TCP does not."""
    chain = (KIT / "stage0.sh").read_text(encoding="utf-8")
    assert 'CHECKS="settings,network,never_negative,load"' in chain
    assert 'CHECKS="network"' in chain and "paths" not in chain.split("CHECKS=", 1)[1][:200]
    session = (KIT / "session.sh").read_text(encoding="utf-8")
    assert "sudo apt-get install -y tcpdump sockperf" in session
    assert "sockperf MISSING" in session
    assert "  - sockperf\n" in (KIT / "cloud-init.yaml").read_text(encoding="utf-8")
    assert "sockperf --version" in (KIT / "machine_facts.sh").read_text(encoding="utf-8")


def test_every_run_keeps_the_brokers_hold_its_tcp_counters_and_the_brokers_log():
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").split("run_one () {", 1)[1]
    order = ['broker_delay "$DELAY_MS"', "tcpdump -i eth0", 'capture_pid=$!',
             '--out "$RUN_DIR/delay_measured.json"', 'wait "$capture_pid"',
             '[ "$measured" = 0 ]', "receiver_delay.py holds", "tcp_counters before",
             'began=$(date -u +%s)', "run_kafka_trial.sh", "run_redis_trial.sh",
             'ended=$(date -u +%s)', "tcp_counters after", "docker logs --timestamps",
             "run_integrity.py check"]
    places = [code.index(step) for step in order]
    assert places == sorted(places)
    assert '-CONSUMER_EXTRA "$REDIS_CONSUMER_EXTRA"' in code
    helper = (KIT / "campaign.sh").read_text(encoding="utf-8").split("tcp_counters () {", 1)[1]
    for side in ('"$RUN_DIR/tcp_$1.txt"', "sudo ip netns exec sblrecv grep",
                 '"$RUN_DIR/broker_tcp_$1.txt"'):
        assert side in helper.split("\n}\n", 1)[0], side


def test_the_campaign_clients_use_the_papers_own_settings():
    """Kafka's in-flight setting was there all along; Redis's batched acknowledgement was not."""
    common = (REPO / "cloud" / "campaigns" / "common.sh").read_text(encoding="utf-8")
    assert 'KAFKA_PRODUCER_EXTRA="${KAFKA_PRODUCER_EXTRA:---max-inflight 64}"' in common
    assert 'REDIS_CONSUMER_EXTRA="${REDIS_CONSUMER_EXTRA:---ack-batch 200}"' in common
    supplement = (REPO / "supplement.tex").read_text(encoding="utf-8")
    assert "\\texttt{ack-batch} & $200$ & \\emph{Learned.}" in supplement


def test_the_machine_facts_never_stop_on_a_fact_they_cannot_read():
    facts = (KIT / "machine_facts.sh").read_text(encoding="utf-8")
    assert 'try () { "$@" 2>&1 || echo "(failed: $*)"; }' in facts
    body = facts.split("try () {", 1)[1]
    for command in ("ethtool -i", "ethtool -c", "ip -d link show", "grep -E \"^Tcp:\" /proc/net/snmp",
                    "command -v tcpdump"):
        assert command in body, command


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


def test_a_session_can_calibrate_at_a_reduced_core_count():
    """A5 gives each core count its own session with its own C0 (D4-6). Every queue row sets the
    run's core count from its own parameters, so an environment variable alone would be
    overwritten: the core count has to reach the design that writes those rows."""
    code = (KIT / "stage0.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    assert '[ -n "${CPUS:-}" ] && CPUS_ARG=(--cpus "$CPUS")' in code
    assert code.count('"${CPUS_ARG[@]}"') == 2, "both stages of the calibration"
    for stage in ('design C0 "c0$tag"', 'design C0 "c0b$tag"'):
        after = code.split(stage, 1)[1].split("campaign", 1)[0]
        assert '"${CPUS_ARG[@]}"' in after, stage


def test_a_session_given_no_core_count_asks_for_none():
    """The argument is an array so that an unset core count adds no argument at all, rather than
    an empty one the design would have to read as a number."""
    code = (KIT / "stage0.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    assert "CPUS_ARG=()" in code
    assert code.index("CPUS_ARG=()") < code.index('CPUS_ARG=(--cpus "$CPUS")')


def test_the_load_a_session_runs_at_and_the_loads_it_calibrates_for_are_separate():
    """A3 is placed from a calibration covering 50, 75 and 88% (D4-4), but the shakedown before
    it is one measurement at one load. On 19 September a session was given the three loads for
    both and stopped itself: pilot_checks reads --load-pct as a single number."""
    code = (KIT / "stage0.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    assert 'C0_LOADS="${C0_LOADS:-$LOAD_PCT}"' in code, "the calibration's loads default to the one"
    shakedown = [line for line in code.splitlines() if "--load-pct" in line]
    assert shakedown and all('"$LOAD_PCT"' in line for line in shakedown), \
        "the shakedown takes the session's own load, never a list"
    calibrations = [line for line in code.splitlines() if "--loads" in line]
    assert len(calibrations) == 2 and all('"$C0_LOADS"' in line for line in calibrations), \
        "both stages of the calibration take the loads a campaign will need"


def test_the_runner_can_swap_the_client_and_nothing_else():
    """A8 compares our Python client with Kafka's official Java one (D4-9). Everything around the
    client has to stay identical or the block compares two harnesses, so there is one script with
    one dispatch rather than two scripts that can drift apart."""
    code = (REPO / "scripts" / "run_kafka_trial.sh").read_text(encoding="utf-8")
    assert 'CLIENT="python"' in code, "the client defaults to the one every other block uses"
    assert '-CLIENT) CLIENT="$2"' in code and '-ACK_STAMP) ACK_STAMP="$2"' in code
    # One plan, one topic, one wrapping, one metadata block, one TTI computation: the only thing
    # the dispatch changes is which program sends and which receives.
    assert code.count('if [ "$CLIENT" = java ]; then') == 2, \
        "the consumer and the producer, and nothing else forks on the client"
    assert 'if [ "$CLIENT" = java ] && [ ! -d harness/java/out ]; then' in code, \
        "and one guard, which is a refusal before the run rather than a fork inside it"
    assert code.count('"$PY" scripts/compute_tti.py') == 1, \
        "the trips are computed once, by the same code, whichever client produced them"
    assert code.count("meta.json") == 1, "and one record of what ran"


def test_the_java_client_is_refused_before_a_run_when_it_is_not_built():
    """Failing here costs nothing; failing after the run costs the run."""
    code = (REPO / "scripts" / "run_kafka_trial.sh").read_text(encoding="utf-8")
    assert "harness/java/out is not built" in code
    assert code.index("is not built") < code.index("starting consumer"), \
        "the refusal comes before anything is started"


def test_where_the_got_it_note_is_taken_reaches_both_clients_the_same_way():
    code = (REPO / "scripts" / "run_kafka_trial.sh").read_text(encoding="utf-8")
    assert 'PRODUCER_EXTRA="$PRODUCER_EXTRA --ack-stamp $ACK_STAMP"' in code, \
        "one option, named the same in each client, rather than two spellings"


def test_the_campaign_hands_the_client_and_the_note_to_the_runner():
    code = (KIT / "campaign.sh").read_text(encoding="utf-8")
    assert '"CLIENT": p.get("language") or ""' in code
    assert '"ACK_STAMP": p.get("ack_stamp") or ""' in code
    # An empty value must add no argument at all, so every block that names no client is launched
    # exactly as it was before A8 existed.
    assert '[ -n "${CLIENT:-}" ] && client_args+=(-CLIENT "$CLIENT")' in code
    assert '"${client_args[@]}"' in code


def test_a_leftover_java_client_is_reaped_like_the_python_ones():
    code = (KIT / "campaign.sh").read_text(encoding="utf-8")
    assert 'pkill -f "LawProducer|LawConsumer"' in code, \
        "a leftover client would send into the next run's topic"


class TestTheToolsBlock:
    """T1 to T4 measure what ten tools report against our own record of the same traffic. What
    can be checked here is that the conditions the plan fixes are the ones the scripts set, and
    that nothing can be run whose answer cannot be read."""

    def tools(self):
        return (KIT / "tools.sh").read_text(encoding="utf-8")

    def runner(self):
        return (KIT / "tools_run.sh").read_text(encoding="utf-8")

    def test_t1_adds_the_plans_own_staircase_in_random_order(self):
        """The plan: 0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.1, 1.5 and 2.0 ms, in random order."""
        code = self.tools()
        assert 'steps="0 0.1 0.2 0.3 0.5 0.7 0.9 1.1 1.5 2.0"' in code
        assert "shuf" in code, "in random order, so a drift in time is not read as a step"
        assert "receiver_delay.py broker --delay-ms" in code, "receiver-only, as the plan says"
        assert "broker-clear" in code, "and the delay is taken off afterwards"

    def test_t3_crosses_load_with_go_first(self):
        code = self.tools()
        assert "for load in 0 88; do" in code, "idle and at 88% load"
        assert "for first in no yes; do" in code, "with and without go-first"
        assert 'wrap="sudo chrt -f 80"' in code, "go-first on the tool's own process"

    def test_every_tool_that_can_be_run_has_a_reader(self):
        """A run whose output nothing can read is a run that cost machine time and says nothing.
        This holds the runner and scripts/tool_readings.py to each other."""
        sys.path.insert(0, str(REPO / "scripts"))
        import tool_readings
        runnable = set(re.findall(r"^  ([a-z0-9_-]+)\)$", self.runner(), re.M))
        runnable.discard("*")
        assert runnable, "the runner names the tools it can run"
        missing = sorted(runnable - set(tool_readings.READERS))
        assert not missing, "no reader for %s" % ", ".join(missing)

    def test_every_tool_with_a_reader_is_pinned(self):
        """A tool's behaviour is what this block reports, so a tool that changed under us would
        be a different experiment."""
        sys.path.insert(0, str(REPO / "scripts"))
        import tool_readings
        code = self.tools()
        pinned = dict(re.findall(r"^([a-z0-9_-]+)\|[a-z]+\|(\S+)$", code, re.M))
        for tool in sorted(tool_readings.READERS):
            assert tool in pinned, "%s has a reader but no pinned version" % tool
            assert pinned[tool] == "resolve" or len(pinned[tool]) >= 5, \
                "%s is pinned to something too vague" % tool
        # "resolve" is an honest blank, not a pin: it says the fingerprint is recorded at install
        # and written back before anything runs. It is only allowed while the script refuses to
        # let a campaign past it, which is what makes it better than an invented commit.
        if "resolve" in pinned.values():
            assert "grep -q '|resolve$'" in code and "STOP_RULE" in code, \
                "a tool left unpinned must stop the block, not run under a blank"

    def test_a_tool_is_run_against_a_server_the_block_itself_puts_up(self):
        """Two of the ten speak to servers no law campaign needs, and the HTTP tools need
        something to fetch. They are installed on the machine rather than in containers: a
        container adds a network namespace and firewall rules between tool and broker, and this
        block measures tenths of a millisecond."""
        code = self.tools()
        assert "brokers ()" in code
        for server in ("nginx", "rabbitmq-server", "nats-server"):
            assert server in code, "%s is one of the servers the ten tools need" % server
        assert "docker" not in code.lower(), "natively, so nothing sits in the path"
        assert "listen 8080" in code, "the HTTP tools' target is the block's own site"

    def test_what_is_installed_is_fingerprinted_rather_than_assumed(self):
        code = self.tools()
        assert "hashlib.sha256" in code, "the build that ran, not the version we meant to install"
        assert "installed.json" in code

    def test_the_tool_is_the_only_thing_the_conditions_reach(self):
        """T1 to T4 all invoke one runner, so they differ in the conditions and in nothing
        else; the wrapper prefixes the tool's own process and nothing around it."""
        code = self.tools()
        assert code.count("bash cloud/azure/tools_run.sh") == 4
        assert 'SBL_TOOL_WRAP="$wrap"' in code
        assert 'WRAP="${SBL_TOOL_WRAP:-}"' in self.runner()


class TestA2sKernelBuild:
    """A2 asks whether the cliff's width follows the tick, and the tick is fixed when a kernel is
    compiled, so the block builds its own. What can be checked here is that the three differ in
    the tick and in nothing else, and that a build which cannot start says so."""

    def kernels(self):
        return (KIT / "kernels.sh").read_text(encoding="utf-8")

    def test_the_three_ticks_the_plan_asks_for(self):
        code = self.kernels()
        assert 'TICKS="${TICKS:-1000 250 100}"' in code
        assert "HZ=1000 build is the control" in code, "not Azure's stock kernel"

    def test_only_the_tick_changes_between_them(self):
        code = self.kernels()
        assert 'cp "/boot/config-$RELEASE" ".config"' in code, "from the running kernel's own"
        assert "--disable CONFIG_HZ_100 --disable CONFIG_HZ_250" in code
        assert '--enable "CONFIG_HZ_$hz" --set-val CONFIG_HZ "$hz"' in code
        assert '[ "$got" = "$hz" ] || stop' in code, "and the config is read back"

    def test_a_built_kernel_is_booted_once_so_a_failed_boot_costs_a_reboot(self):
        code = self.kernels()
        assert "grub-reboot" in code and "stock kernel stays the default" in code

    def test_it_boots_the_kernel_and_not_the_debug_symbols_beside_it(self):
        """Each build also makes a -dbg package, and "...-sbl1000-dbg_..." sorts before
        "...-sbl1000_..." because a hyphen comes before an underscore. Without the underscore the
        glob installs the symbols and points grub at an entry that is not a kernel -- which is
        what happened on the first real boot, on 21 September."""
        code = self.kernels()
        assert 'linux-image-*sbl"$hz"_*.deb' in code
        assert "*-dbg_*) stop" in code, "and it refuses outright if one still gets through"

    def test_none_of_it_is_run_as_root(self):
        """common.sh takes the checkout from HOME, so running the script under sudo sends it to
        /root/sbl. It calls sudo where it needs it instead."""
        code = self.kernels()
        assert "sudo bash cloud/azure/kernels.sh" not in code
        assert "running the script itself" in code and "/root" in code

    def test_the_source_can_be_fetched_on_a_machine_that_lists_no_source(self):
        """Azure's Ubuntu image carries no deb-src line at all, so apt-get source refuses before
        it starts. The build died on this the first time it ran."""
        code = self.kernels()
        assert "grep -qs '^deb-src'" in code
        assert "sources.list.d/sbl-kernel-source.list" in code, "in a file of our own"
        assert "upgrades nothing" in code

    def test_the_source_tree_is_picked_out_from_the_tarballs_beside_it(self):
        """apt leaves the tarball, diff and dsc next to the tree it unpacks, and all four begin
        with the package's name, so a glob matches the lot and mv reads the last as the
        destination. The build died on this the second time it ran."""
        code = self.kernels()
        assert "-type d -name 'linux-*'" in code
        assert "mv linux-azure-* linux-azure" not in code

    def test_which_source_tree_was_built_is_recorded(self):
        """The archive serves whatever it currently holds, which need not be the kernel running:
        on 20 September the running kernel was 1064 and the archive offered 1067."""
        assert "source_version.txt" in self.kernels()

    def test_what_was_built_is_written_where_the_repository_is(self):
        """$OLDPWD inside the build directory is not the repository. Writing built.txt through
        it fails, and the failing tee is what the stop rule reads -- so three kernels that took
        six hours would have reported that none was produced."""
        code = self.kernels()
        assert 'REPO="$(pwd)"' in code
        assert '"$REPO/$DIR/built.txt"' in code
        assert "$OLDPWD" not in code

    def test_the_configuration_step_is_not_fed_by_a_pipe(self):
        """This kit runs under pipefail. olddefconfig asks nothing, so "yes |" in front of it
        only means make finishes first, yes dies of a broken pipe with status 141, and the
        pipeline reports that -- stopping the build on a configuration that worked."""
        code = self.kernels()
        assert "yes \"\" | make olddefconfig" not in code
        assert "make olddefconfig >" in code, "and its output is kept, so a stop can say why"

    def test_a_source_that_could_not_be_fetched_stops_the_build(self):
        """Piping apt-get into tail reports tail's status, which is always zero, and the build
        would carry on with no source to build."""
        code = self.kernels()
        assert "apt-get source" in code
        assert "apt-get source \"linux-image-unsigned-$RELEASE\" | tail" not in code
        assert 'stop "the source for $RELEASE could not be fetched' in code


class TestT2ForcedNegatives:
    """T2 moves the clock the tool reads and asks what it did with the values that came out
    below zero. Its whole danger is silence: a run where the offset never reached the tool looks
    exactly like a tool that handles negatives perfectly."""

    def tools(self):
        return (KIT / "tools.sh").read_text(encoding="utf-8")

    def test_the_offsets_come_from_the_trip_they_act_on(self):
        """Plan version 15, D15-1. Half a millisecond against a 3 ms trip puts nothing below
        zero, so a fixed pair of offsets asks nothing of most of these tools."""
        code = self.tools()
        assert '(t+1.0, t+3.0)' in code, "the session's own median trip plus one and plus three"
        assert "for ms in $offsets; do" in code
        assert "statistics.median" in code, "from the trips T1 recorded, not from a guess"

    def test_t2_is_given_what_t1_found_the_tool_can_report(self):
        """D15-2: a tool that cannot report a tenth of a millisecond never meets one below zero
        either, so the prediction has to pass through the step T1 measured."""
        code = self.tools()
        assert "tool_readings.py staircase" in code
        assert "--step-ms" in code and "--plain" in code
        assert "which is a bound" in code, "and says so when it falls back to the printed step"

    def test_a_go_tool_is_refused_rather_than_run_without_an_offset(self):
        """Go reads the clock without the C library, so the preload never reaches it."""
        code = self.tools()
        assert 'GO_TOOLS="vegeta hey k6 nats-latency"' in code
        assert "needs the second machine with an offset clock" in code

    def test_a_tool_in_neither_list_is_refused_rather_than_assumed(self):
        assert "not in either T2 list" in self.tools()

    def test_the_offset_is_measured_before_anything_is_run_under_it(self):
        """libfaketime's fractional spellings differ between builds, so the one that works is
        found by measuring the shift, not by assuming a format."""
        code = self.tools()
        assert "faketime_spelling ()" in code
        assert "no libfaketime offset of $ms ms could be confirmed" in code
        assert "offset_spelling.txt" in code, "and what was used is recorded beside the run"

    def test_what_the_tool_did_is_judged_against_our_own_trips(self):
        code = self.tools()
        assert "tool_negatives.py judge" in code
        assert "--exit-code" in code, "a tool that died is one of the answers"
        assert "no reference trips beside this run" in code
