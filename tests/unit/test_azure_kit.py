"""The Azure kit's files that are not Python: the machine setup, the shell scripts, the guide.

They run on machines this suite never sees, so what can be checked here is what breaks them
silently there: a CRLF line ending, a script that carries on after an error it should stop at, a
setup file that is not cloud-config, and a guide that names a file that does not exist.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
KIT = REPO / "cloud" / "azure"
SHELL = sorted(KIT.glob("*.sh"))

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
import testbed_watch  # noqa: E402
from posix_shell import bash, linux_bash, tool  # noqa: E402


def test_the_kit_has_the_scripts_the_guide_describes():
    assert [p.name for p in SHELL] == ["a2_session.sh", "campaign.sh", "chain.sh", "cpus.sh",
                                       "idle.sh", "kernels.sh",
                                       "machine_facts.sh", "pilot.sh", "queue.sh", "replicate_oracle.sh",
                                       "resume.sh", "session.sh", "stage0.sh", "stage1.sh",
                                       "stop_self.sh", "stop_when_idle.sh", "tools.sh",
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


@pytest.mark.parametrize("path", SHELL, ids=lambda p: p.name)
def test_bash_parses_it(path):
    assert bash(["-n", str(path)]).returncode == 0


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
    order = ['cp "$STAGE0/$f" "$DIR/$f"', 'yield path, bool(node["gate"].get("ok"))',
             'log "rounds: $ROUNDS"', "law_design.py design", "run_queue.py make",
             "bash cloud/azure/campaign.sh", "CAMPAIGN_COMPLETE"]
    places = [code.index(step) for step in order]
    assert places == sorted(places), "the steps run in the plan's order"
    assert code.index('log "rounds: $ROUNDS"') < code.index("law_design.py design"), \
        "the rounds are in the log before the campaign is even designed"
    assert 'log "rounds from: $ROUNDS_NOTE"' in code, "and where the number came from"


def test_stage_1_will_not_place_a_campaign_from_a_calibration_that_failed():
    code = (KIT / "stage1.sh").read_text(encoding="utf-8").split("set -o pipefail", 1)[1]
    assert "did not pass its gate for" in code
    assert code.index('yield path, bool(node["gate"].get("ok"))') < code.index("law_design.py design")


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
    # The paper's batched acknowledgement reaches the Redis consumer, M0's own batch after it
    # where the setup names one (D29-1), and A9's thread record in the runs that ask (D28-1);
    # freeze 43's client flags last, empty unless a row asks.
    assert ('-CONSUMER_EXTRA "$REDIS_CONSUMER_EXTRA${ACK_BATCH:+ --ack-batch $ACK_BATCH}'
            ' $record_args $so_cons$cons_flags"') in code
    helper = (KIT / "campaign.sh").read_text(encoding="utf-8").split("tcp_counters () {", 1)[1]
    for side in ('"$RUN_DIR/tcp_$1.txt"', "sudo ip netns exec sblrecv grep",
                 '"$RUN_DIR/broker_tcp_$1.txt"'):
        assert side in helper.split("\n}\n", 1)[0], side


def test_the_campaign_clients_use_the_papers_own_settings():
    """Kafka's in-flight setting was there all along; Redis's batched acknowledgement was not."""
    common = (REPO / "cloud" / "campaigns" / "common.sh").read_text(encoding="utf-8")
    assert 'KAFKA_PRODUCER_EXTRA="${KAFKA_PRODUCER_EXTRA:---max-inflight 64}"' in common
    assert 'REDIS_CONSUMER_EXTRA="${REDIS_CONSUMER_EXTRA:---ack-batch 200}"' in common
    supplement = (REPO / "postmortem.tex").read_text(encoding="utf-8")
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
    # the dispatch changes is which program sends and which receives. Plan version 47 (23 Oct
    # 2026): the consumer forks once, on the consumer that receives (-CONSUMER, or the client's
    # own), and the producer once, on the client, so that -CONSUMER swaps the consumer alone.
    assert code.count('if [ "$CLIENT" = java ]; then') == 1, \
        "the producer, and nothing else forks on the client"
    assert code.count('case "$RECEIVER" in') == 1, "and the consumer on the consumer"
    assert 'RECEIVER="${CONSUMER:-kafka-python}"\n[ "$CLIENT" = java ] && RECEIVER=java' in code
    assert 'if [ "$RECEIVER" = java ] && [ ! -d harness/java/out ]; then' in code, \
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
        assert "receiver_delay.py broker --dst $RECEIVER_IP" in code, (
            "added on the broker's card toward the receiver's namespace, the same place and the "
            "same way the law campaigns add it")
        assert "needs_namespace" in code and "delay_arrives" in code, (
            "and the staircase does not start until the delay is shown to reach the tool")
        assert "broker-clear" in code, "and the delay is taken off afterwards"

    def rdkafka_invocations(self):
        """The tool's own command lines, continuations joined and comments dropped.

        Read physical lines and an argument on the second half of a wrapped command reads as
        absent, which is a test that passes by not looking.
        """
        code = self.runner().split("  rdkafka_performance)", 1)[1].split(";;", 1)[0]
        joined, held = [], ""
        for line in code.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.endswith("\\"):
                held += line[:-1] + " "
                continue
            joined.append(held + line)
            held = ""
        if held:
            joined.append(held)
        return joined

    def test_rdkafkas_consumer_is_started_before_the_producer_it_measures(self):
        """-o end is what makes the order matter, and the order was settled before it was there.

        The note here used to say the consumer starts at the end of the topic of its own accord.
        It does not: its default is the beginning, and the shakedown of 23 September read the
        previous trial's messages back and reported their age as latency. With -o end the claim
        is true because the invocation makes it true, and a producer that has already finished
        is a producer this consumer never sees.
        """
        code = self.runner().split("  rdkafka_performance)", 1)[1].split(";;", 1)[0]
        lines = [line.strip() for line in code.splitlines() if not line.strip().startswith("#")]
        consumer = next(i for i, line in enumerate(lines) if " -C " in line)
        producer = next(i for i, line in enumerate(lines) if " -P " in line)
        assert consumer < producer, "the consumer is listening before anything is sent"
        assert lines[consumer].endswith("&") or lines[consumer + 1].endswith("&"), \
            "and it is the one left running in the background"
        assert 'wait "$consumer"' in code, "the run ends when the consumer has its messages"

    def test_rdkafkas_consumer_is_told_which_partition_to_read(self):
        """Its usage says the partition "defaults to random", and without one it reads nothing.

        This is the whole of why the tool measured nothing: not the topic, not the order of the
        two instances, both of which were tried. The same invocation with -p 0 added and nothing
        else changed read every message the producer sent, on a one-partition topic
        (docs/results/tools/rdkafka-shakedown.md, trials A to C). A tool that measures nothing
        must not be reported as a tool that measured zero.
        """
        consumer = next(line for line in self.rdkafka_invocations() if " -C " in line)
        assert " -p 0 " in consumer, "attached to the partition rather than to a random one"
        assert " -o end " in consumer, "and reading only what this run sent"

    def test_rdkafkas_producer_is_paced_like_every_other_tool_in_the_block(self):
        """Unpaced, what it reports is its own batching rather than a trip.

        The other ten tools are all held to RATE. Without -r this one enqueues the whole count
        at once: the shakedown's readings fell in exact 20 ms steps from 1005 ms, every message
        stamped at its own enqueue time and all of them arriving together.
        """
        producer = next(line for line in self.rdkafka_invocations() if " -P " in line)
        assert '-r "$RATE"' in producer, "paced at the rate the rest of the block runs at"

    def test_a_tool_that_never_finishes_cannot_take_the_pair_with_it(self):
        """The only limit above the tool was the queue's own twelve hours."""
        runner = self.runner()
        assert "SBL_TOOL_GUARDED" in runner and "exec timeout -k 30" in runner
        assert runner.index("SBL_TOOL_GUARDED") < runner.index('case "$TOOL" in'), \
            "the guard is in place before any tool runs"

    def test_the_tools_talk_across_the_pair_and_not_to_themselves(self):
        """T1 adds its delay on the broker, to traffic bound for the driver. Every target in the
        runner defaulted to 127.0.0.1 until 22 September, which put the tool and the server it
        measured on one machine, so the delay landed on a path the tool never used and T1 could
        not work at all."""
        runner = self.runner()
        #: The code, not the comment that explains why the code is as it is.
        code = " ".join(line for line in runner.splitlines()
                        if not line.lstrip().startswith("#"))
        #: Freeze 30's two-process tools talk to themselves -- OMB's coordinator to its workers,
        #: emqtt-bench's subscriber serving its own metrics -- and that one loopback address is
        #: named once and used only for them.
        own = 'OWN="${SBL_TOOL_OWN:-127.0.0.1}"'
        assert code.count(own) == 1
        assert "127.0.0.1" not in code.replace(own, ""), "no target is the machine the tool runs on"
        #: Freeze 32 adds Trogdor's agents and coordinator, which its node file places on the
        #: loopback, and whose coordinator the client asks on its port 8889; freeze 33, YSB's Flink
        #: JobManager, waited for on its RPC port 6123 and asked on its REST port 8081 whether its
        #: TaskManager has registered, and that TaskManager told the same loopback as its address.
        #: Freeze 35 adds kgo-repeater's consuming repeater, reset and read on its control port 7884.
        for line in re.findall(r"^.*\$OWN\b.*$", runner, re.M):
            assert any(own_use in line for own_use in ("--workers", "--restapi", "/metrics",
                                                       ":8889", "trogdor.conf", ":8081/",
                                                       "/6123", "taskmanager.host", ":7884/")), \
                "the loopback names a tool's own processes, never a server: %s" % line.strip()
        assert "localhost" not in code
        for target in ("SBL_TOOL_HTTP:-http://$BROKER_PRIV:8080/", "SBL_VALKEY_HOST:-$BROKER_PRIV",
                       "SBL_KAFKA:-$BROKER_PRIV:19092", "SBL_NATS:-nats://$BROKER_PRIV:4222"):
            assert target in runner, target

    def test_t3_crosses_load_with_go_first(self):
        code = self.tools()
        assert "for load in 0 88; do" in code, "idle and at 88% load"
        assert "for first in no yes; do" in code, "with and without go-first"
        assert 'wrap="$NETNS chrt -f 80"' in code, (
            "go-first inside the namespace, which is the path the delay reaches")
        assert "chrt -f 80" in code, "go-first on the tool's own process"

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
        for server in ("nginx", "rabbitmq-server", "nats-server", "mosquitto", "sbl-pulsar"):
            assert server in code, "%s is one of the servers the tools need" % server
        #: Where the servers are set up. OMB's build leaves out its own docker module, which is the
        #: one other place the word appears, and that is the point of naming it there.
        setup = code.split("\nbrokers () {", 1)[1].split("\n# T1:", 1)[0]
        assert "docker" not in setup.lower(), "natively, so nothing sits in the path"
        assert "listen 8080" in code, "the HTTP tools' target is the block's own site"
        assert "webServicePort=8090" in setup, "and Pulsar's web port does not take nginx's 8080"

    def test_what_is_installed_is_fingerprinted_rather_than_assumed(self):
        code = self.tools()
        assert "hashlib.sha256" in code, "the build that ran, not the version we meant to install"
        assert "installed.json" in code

    def test_the_tool_is_the_only_thing_the_conditions_reach(self):
        """T1 to T4 all invoke one runner, so they differ in the conditions and in nothing
        else; the wrapper prefixes the tool's own process and nothing around it.

        Five invocations, not four: T2 runs the tool a third time at no offset as its control
        (D23-1), and that one carries no wrapper at all, which is the whole point of it. And a
        sixth since freeze 33: YSB's reference is YSB itself at no delay (D36-3), in the
        namespace, as T1's zero step runs it. And four more since freeze 34: PerfKit's T1, its zero
        step alone, and its reference, PerfKit itself, both unwrapped since its broker is a managed
        service T1 cannot reach; and S1's control and its stepped run, both in the namespace and
        neither otherwise wrapped, since what differs between them is the machine's clock. And one
        more since freeze 36: the reference of each of its three, the tool itself at no offset, in
        the namespace as T1's zero step runs it (D39-3); freeze 37's Quiver there under
        libfaketime at no offset, since libfaketime alone lengthens its receiver's trip (D40-3).
        And one more since freeze 38: the Pub/Sub load test's reference, itself at no offset,
        unwrapped as PerfKit's (D41-3). Its T4 takes a wrap of its own, the subscriber's clock a
        second ahead, through the same call as every other tool's T4.
        """
        code = self.tools()
        assert code.count("bash cloud/azure/tools_run.sh") == 12
        assert 'SBL_TOOL_WRAP="$wrap" bash cloud/azure/tools_run.sh "$tool" "$out/reference_tool"' in code
        assert 'local wrap="$NETNS"' in code
        assert 'if [ "$tool" = quiver ]; then wrap="$NETNS faketime -f -0.000000000"; fi' in code
        assert 'SBL_TOOL_WRAP="$NETNS" bash cloud/azure/tools_run.sh ysb' in code
        assert 'bash cloud/azure/tools_run.sh pkb "$out/reference_pkb"' in code
        assert code.count('SBL_TOOL_WRAP="$NETNS" bash cloud/azure/tools_run.sh "$tool" "$control"') == 1
        assert code.count('SBL_TOOL_WRAP="$NETNS" bash cloud/azure/tools_run.sh "$tool" "$run"') == 1
        assert 'SBL_TOOL_WRAP="$wrap"' in code
        assert 'WRAP="${SBL_TOOL_WRAP:-}"' in self.runner()

    def case(self, tool):
        """One tool's lines in the runner, comments dropped and continuations joined."""
        code = self.runner().split("\n  %s)" % tool, 1)[1].split(";;", 1)[0]
        joined, held = [], ""
        for line in code.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.endswith("\\"):
                held += line[:-1] + " "
                continue
            joined.append(held + line)
            held = ""
        return joined

    def test_the_lines_the_readers_look_for_are_the_lines_the_runner_writes(self):
        """Three of freeze 30's tools put a second output after their log, under a line of their
        own, and the reader finds it by that line. A word changed on one side alone would read
        every run as having no histogram, no metrics or no result file."""
        sys.path.insert(0, str(REPO / "scripts"))
        import tool_readings
        runner = self.runner()
        for line in (tool_readings.EMQTT_METRICS, tool_readings.OMB_RESULT,
                     tool_readings.PULSAR_HISTOGRAM):
            assert 'echo "%s"' % line in runner, line

    def test_pulsar_perfs_consumer_listens_first_runs_by_time_and_writes_its_histogram(self):
        """Stopped by a count, it exits on the last message before recording that message's latency
        and before writing its last ten seconds to the file."""
        lines = self.case("pulsar-perf")
        consumer = next(i for i, line in enumerate(lines) if " consume " in line)
        producer = next(i for i, line in enumerate(lines) if " produce " in line)
        assert consumer < producer and lines[consumer].endswith("&")
        assert lines[consumer].startswith("$WRAP ") and not lines[producer].startswith("$WRAP")
        assert "-sp Latest" in lines[consumer] and "-time " in lines[consumer]
        assert " -m " not in lines[consumer], "a count stops it before its last interval is written"
        assert '--histogram-file "$histogram"' in lines[consumer]

    def test_emqtt_bench_subtracts_in_the_wrapped_subscriber_and_is_read_after_its_publisher(self):
        lines = self.case("emqtt-bench")
        sub = next(i for i, line in enumerate(lines) if " sub " in line)
        pub = next(i for i, line in enumerate(lines) if " pub " in line)
        metrics = next(i for i, line in enumerate(lines) if " curl " in line and "/metrics" in line)
        assert sub < pub < metrics, "listening first, and its histogram read once the sends are done"
        assert lines[sub].startswith("$NS ") and "$REST" in lines[sub]
        assert "$REST" not in lines[pub] and "$NS" not in lines[pub]
        assert lines[sub].count("--payload-hdrs ts") == 1 and "--payload-hdrs ts" in lines[pub]
        assert lines[metrics].startswith("$NS "), "asked in the network the subscriber is in"

    def test_omb_runs_distributed_with_the_wrap_on_the_consumer_worker_alone(self):
        lines = self.case("omb")
        workers = [line for line in lines if "bin/benchmark-worker" in line]
        assert len(workers) == 2 and all(line.startswith("$NS ") for line in workers)
        assert "$REST" not in workers[0] and "--port 8180" in workers[0], "the producer's worker"
        assert "$REST" in workers[1] and "--port 8182" in workers[1], "the consumer's, wrapped"
        coordinator = next(line for line in lines if "bin/benchmark --workers" in line)
        assert "http://$OWN:8180,http://$OWN:8182" in coordinator, \
            "producers to the first worker, consumers to the second"
        assert lines.index(coordinator) < lines.index("stop_own"), "and both stopped after it"

    def test_the_one_process_tools_wrap_what_they_time_and_nothing_else(self):
        ycsb = self.case("ycsb")
        load = next(line for line in ycsb if " load redis " in line)
        run = next(line for line in ycsb if " run redis " in line)
        assert not load.startswith("$WRAP") and run.startswith("$WRAP"), \
            "the records are loaded outside the wrap and the timing"
        nats = self.case("nats-bench")
        serve = next(line for line in nats if "service serve" in line)
        request = next(line for line in nats if "service request" in line)
        assert not serve.startswith("$WRAP") and request.startswith("$WRAP")
        assert nats.index(serve) < nats.index(request)

    def test_t2_takes_its_control_with_no_offset_and_before_the_offsets(self):
        """Without it, "its figures did not move" cannot be told from "it did something none of
        the four behaviours describes" -- the two produced the same sentence until 23 September,
        and valkey-benchmark's first complete T2 is the run that produced it.
        """
        code = self.tools()
        t2 = code.split("\nt2 () {", 1)[1].split("\n}\n", 1)[0]
        control = t2.index('bash cloud/azure/tools_run.sh "$tool" "$control"')
        offsets = t2.index("for ms in $offsets; do")
        assert control < offsets, "the control is taken before the offset runs, not after"
        assert "SBL_TOOL_WRAP" not in t2[control:t2.index("\n", control)], \
            "the control runs with the clock the machine actually has"
        assert "--control" in t2 and "--shift-ms" in t2, \
            "and both reach the judge, which cannot decide the verdict without them"


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

    def test_a_go_tool_gets_the_machines_own_clock_moved_not_the_preload(self):
        """Go reads the clock without the C library, so the preload never reaches it, and a run
        under it would be a run with no offset at all. D15-1 says what to do instead: move the
        machine's own clock and put it back. Until 25 September this script only refused."""
        code = self.tools()
        listed = re.search(r'^GO_TOOLS="([^"]*)"', code, re.M).group(1).replace("\\\n", " ")
        #: Freeze 35 adds three: mqtt-benchmark, Sarama's tool and kgo-repeater (D38-2).
        assert listed.split() == ["vegeta", "hey", "k6", "nats-latency", "nats-bench",
                                  "strimzi-canary", "mqtt-benchmark", "sarama-producer-perf",
                                  "kgo-repeater"]
        t2 = code.split("\nt2 () {", 1)[1].split("\n}\n", 1)[0]
        assert "how=clock" in t2 and "step_clock" in t2
        go = t2.split('*" $tool "*)', 1)[1].split(";;", 1)[0]
        assert "faketime" not in go, "a Go tool is never given the preload that cannot reach it"

    def test_it_will_not_move_a_clock_under_a_running_campaign(self):
        """Every process on the machine sees the step, a campaign's among them."""
        t2 = self.tools().split("\nt2 () {", 1)[1].split("\n}\n", 1)[0]
        assert "machine_is_quiet" in t2 and "a campaign is running here" in t2

    def test_the_step_is_measured_against_the_hypervisors_clock(self):
        """D23-1: a run whose offset is not confirmed is not made. The measure is the PTP clock,
        which stepping the system clock does not move."""
        step = self.tools().split("\nstep_clock () {", 1)[1].split("\n}\n", 1)[0]
        assert "clock_step.py shift" in step and "clock_step.json" in step
        assert "systemctl stop chrony" in step, "or chrony pulls the clock back during the run"

    def test_the_clock_is_put_back_whatever_happens(self):
        """After each run, before the next reading is taken, and on any way out of the stage."""
        code = self.tools()
        t2 = code.split("\nt2 () {", 1)[1].split("\n}\n", 1)[0]
        assert "trap unstep_clock EXIT" in t2
        loop = t2.split("for ms in $offsets; do", 1)[1]
        assert loop.index("unstep_clock") < loop.index("tool_readings.py read")
        back = code.split("\nunstep_clock () {", 1)[1].split("\n}\n", 1)[0]
        assert "systemctl start chrony" in back

    def test_a_tool_in_neither_list_is_refused_rather_than_assumed(self):
        assert "not in either T2 list" in self.tools()

    def test_no_stage_runs_a_tool_the_machine_does_not_have(self):
        """The Arm pair produced ten wrk2 folders whose readings are empty and whose whole
        output is `exec of "wrk" failed`, and three rabbitmq-perftest ones saying "no main
        manifest attribute". The install had said MISSING for the first and recorded the second
        as present because the jar existed."""
        code = self.tools()
        assert "have_tool () {" in code
        for stage in ("t1", "t2", "t3", "t4"):
            body = code.split("\n%s () {" % stage, 1)[1].split("\n}", 1)[0]
            assert 'have_tool "$tool"' in body, "%s runs it without asking" % stage
            assert body.index('have_tool "$tool"') < len(body) // 2, \
                "%s asks before it measures anything" % stage

    def test_a_jar_without_a_main_class_is_not_a_tool(self):
        """`java -jar` needs one. Maven leaves a plain perf-test jar beside the runnable one,
        and the plain one was copied, fingerprinted and recorded as installed."""
        code = self.tools()
        assert "runnable_jar () {" in code and "Main-Class" in code
        built = code.split("get_perftest () {", 1)[1].split("\n}", 1)[0]
        assert 'runnable_jar "$candidate"' in built, "the jar chosen is one that can start"
        assert "-Puber-jar" in built, "and the profile is asked for when the plain build has none"
        assert 'runnable_jar "$jar"' in built, "a jar already here is checked, not trusted"
        assert "def startable(path):" in code, "and the record of what is installed agrees"

    def test_the_offset_is_measured_before_anything_is_run_under_it(self):
        """libfaketime's fractional spellings differ between builds, so the one that works is
        found by measuring the shift, not by assuming a format."""
        code = self.tools()
        assert "faketime_spelling ()" in code
        assert "no libfaketime offset of $ms ms could be confirmed" in code
        assert "offset_spelling.txt" in code, "and what was used is recorded beside the run"
        assert "offset_measured.json" in code, "and what the clock did, beside what was asked"

    def test_no_spelling_is_tried_that_libfaketime_reads_as_minutes(self):
        """It has no millisecond unit: "-1.812ms" is 1.812 minutes with the s ignored, which
        moves the clock back 108 seconds. Fractional seconds are the grammar."""
        code = self.tools().split("offset_as () {", 1)[1].split("\n}", 1)[0]
        for spelt in ("}ms", "ms'", 'ms"', "}m'", '}m"'):
            assert spelt not in code, "a spelling ending in %r is minutes to libfaketime" % spelt
        assert "'-%.9f' %" in code and "'-%.9fs' %" in code, "fractional seconds, both ways"

    def test_the_offset_is_measured_as_a_difference_against_no_offset(self):
        """Starting faketime and date costs about two milliseconds, which is more than the
        offsets T2 uses; reading the clock either side of one faked reading therefore measured a
        correct spelling as anything at all, and T2 stopped on a machine that was fine. The cost
        is the same at any offset, so it cancels in a difference."""
        code = self.tools().split("faketime_spelling () {", 1)[1].split("\n}", 1)[0]
        assert 'offset_as "$grammar" 0' in code, "the same measurement at no offset"
        assert 'offset_as "$grammar" "$ms"' in code
        assert "float(sys.argv[1]) - float(sys.argv[2])" in code, "and what separates them"
        reading = self.tools().split("faketime_reading () {", 1)[1].split("\n}", 1)[0]
        assert "statistics.median" in reading, "a median over repeats, not one reading"
        assert "FAKETIME_READS" in reading

    def test_what_the_tool_did_is_judged_against_our_own_trips(self):
        code = self.tools()
        assert "tool_negatives.py judge" in code
        assert "--exit-code" in code, "a tool that died is one of the answers"
        assert "T1 left no reference trips at" in code

    def test_the_reference_is_read_from_where_t1_wrote_it(self):
        """It looked for the file inside the T2 run's own folder, where nothing puts it, so the
        condition could never hold: every T2 run ended with a warning about a file that was
        never meant to be there, and nothing was ever judged."""
        body = self.tools().split("\nt2 () {", 1)[1].split("\n}", 1)[0]
        assert 'local trips="$DIR/t1-$tool-0ms/reference_trips.json"' in body
        assert '--reference "$trips"' in body
        assert 'if [ -s "$trips" ]; then' in body
        assert '"$DIR/$run/reference_trips.json"' not in body, \
            "nothing puts a reference in the T2 run's folder"

    def test_what_the_clock_did_reaches_the_run_that_asks_for_it(self):
        """faketime_spelling is read through $(...), which is a subshell: a variable set in it
        never reaches the caller, and the first version set one -- so every run recorded
        "measured ? ms" while the number was there to be had."""
        code = self.tools()
        assert "FAKETIME_MOVED_MS" not in code, "a variable set in a subshell reaches nobody"
        spelling = code.split("faketime_spelling () {", 1)[1].split("\n}", 1)[0]
        assert 'echo "$(offset_as "$grammar" "$ms") $moved"' in spelling
        t2 = code.split("\nt2 () {", 1)[1].split("\n}", 1)[0]
        assert 'spelling="${said%% *}"; moved="${said##* }"' in t2
        assert 'measured $moved ms' in t2

    def test_the_got_it_brake_records_when_the_campaign_or_its_pair_is_told_to(self):
        """D26-1 and D32-1. Asked for by name it wins; otherwise the pair's own word in
        runs/azure/gotit_brake decides, so that a campaign its queue starts after a reboot records
        too; with neither, the rule is the default and nothing is passed. A word that is neither
        stops the campaign before its first run, and a campaign that records says so at the head
        of its own log."""
        code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
        assert 'GOTIT_BRAKE="${GOTIT_BRAKE:-$(cat runs/azure/gotit_brake 2>/dev/null)}"' in code
        assert '[ -n "$GOTIT_BRAKE" ] && gotit_args=(--gotit-brake "$GOTIT_BRAKE")' in code
        check = code.split("scripts/run_integrity.py check", 1)[1].split("\n  case $?", 1)[0]
        assert '"${gotit_args[@]}"' in check
        guard = code.split('case "$GOTIT_BRAKE" in', 1)[1].split("esac", 1)[0]
        assert '""|stop|record) ;;' in guard and "exit 1" in guard
        assert code.index('case "$GOTIT_BRAKE" in') < code.index("\nwhile true; do")
        assert "${GOTIT_BRAKE:+; the got-it brake: $GOTIT_BRAKE (D26-1, D32-1)}" in code

    def test_each_round_of_the_block_has_a_folder_of_its_own(self):
        """D4-2: tool campaigns run four rounds. The block ran once, into folders named for the
        tool and the step, so a second pass would have landed on the first (25 September)."""
        code = self.tools()
        assert 'ROUND="${SBL_TOOLS_ROUND:-1}"' in code
        assert 'BASE="${SBL_TOOLS_DIR:-runs/azure/tools}"' in code, \
            "the eleven's round 1 stays where it always was, and another block names its own"
        assert '1) DIR="$BASE" ;;' in code
        assert '[2-9]) DIR="${BASE}_round$ROUND" ;;' in code

    def test_no_stage_writes_over_runs_that_are_already_there(self):
        code = self.tools()
        for stage, pattern in (("t1", '"t1-$tool-*ms/tool.txt"'), ("t2", '"t2-$tool-*/tool.txt"'),
                               ("t3", '"t3-$tool-*/tool.txt"'), ("t4", '"t4-$tool/tool.txt"')):
            body = code.split("\n%s () {" % stage, 1)[1].split("\n}\n", 1)[0]
            guard = 'not_run_yet %s "$tool" %s' % (stage.upper(), pattern)
            assert guard in body, stage
            assert body.index(guard) < body.index("mkdir"), "%s asks before it makes a folder" % stage

    def test_a_tools_count_is_held_against_what_it_was_asked_to_send(self):
        """Not against the number of trips in our reference, another run of another client: held
        against our 5,000, wrk2's count of all 3,001 it sent read as short, and a run was decided
        on it (25 September)."""
        run = (KIT / "tools_run.sh").read_text(encoding="utf-8")
        assert 'echo $(( RATE * SECONDS_TO_RUN )) > "$OUT/asked_to_send.txt"' in run
        assert run.index("asked_to_send.txt") > run.index('mkdir -p "$OUT"'), \
            "written once the run's folder exists"
        t2 = self.tools().split("\nt2 () {", 1)[1].split("\n}\n", 1)[0]
        judge = t2[t2.index("tool_negatives.py judge"):]
        assert '"$DIR/$run/asked_to_send.txt"' in judge and '"--sent %s"' in judge

    def test_the_clock_is_stepped_where_the_step_can_be_undone(self):
        """The same trap one function along. step_clock records what it stepped for unstep_clock
        to undo, and it was called through $(...), so the record was made in a subshell and
        unstep_clock found nothing to put back. On 25 September each Go tool's second offset
        landed on top of its first: 5.3 to 5.7 ms from the PTP clock where 3.8 was planned."""
        code = self.tools()
        assert "$(step_clock" not in code, "a variable set in a subshell reaches nobody"
        step = code.split("\nstep_clock () {", 1)[1].split("\n}\n", 1)[0]
        assert 'STEPPED_MS="$ms"' in step and "STEP_MOVED=$(" in step
        t2 = code.split("\nt2 () {", 1)[1].split("\n}\n", 1)[0]
        assert 'step_clock "$ms" "$DIR/$run"' in t2 and 'moved="$STEP_MOVED"' in t2

    def test_the_clock_is_measured_after_it_is_put_back_and_nothing_runs_on_from_one_held_off(
            self):
        """Nothing said so on 25 September: the only sign was the offset printed at the end."""
        t2 = self.tools().split("\nt2 () {", 1)[1].split("\n}\n", 1)[0]
        loop = t2.split("for ms in $offsets; do", 1)[1]
        back = loop[loop.index("unstep_clock"):]
        assert "clock_step.py measure" in back and "clock_back.json" in back
        assert "abs(float(sys.argv[1])) <= 0.25" in back
        assert "from a clock still held off" in back
        assert back.index("clock_back.json") < back.index("tool_readings.py read")


QUEUE = KIT / "queue.sh"
IDLE = KIT / "idle.sh"


def _queue_call(tmp_path, call, extra_env=None):
    """One of queue.sh's own functions, sourced in a scratch checkout and asked a question.

    Sourcing runs the dispatch at the foot of the script, which with no argument is `show`, and
    show only reads. That is cheaper than a second copy of the parsing here, and a copy is what
    would rot.
    """
    root = _scratch_checkout(tmp_path)
    script = "cd '%s' && . cloud/azure/queue.sh >/dev/null 2>&1; %s" % (root.as_posix(), call)
    done = bash(["-c", script], capture_output=True, text=True, extra_env=extra_env)
    return done.stdout.strip()


def _scratch_checkout(tmp_path):
    """Enough of a checkout for the script to load: it reads the pair's addresses through
    common.sh, which refuses to load without them, as every campaign script here does.

    common.sh then changes to REPO_ROOT -- $HOME/sbl unless it is told otherwise -- and will not
    go on without a replay plan under data/. The first version of this gave it neither, and made
    its folders as though it would only ever be called once, when a test calls it once for each
    question. So every test built on it failed on Linux from the day they were written, 22
    September, while Windows skipped them; CI said so on every commit from then on.
    """
    root = tmp_path / "sbl"
    for where in ("cloud/azure", "cloud/campaigns", "data/plans/scratch"):
        (root / where).mkdir(parents=True, exist_ok=True)
    shutil.copy(QUEUE, root / "cloud" / "azure" / "queue.sh")
    # Freeze 41: the queue reads whether a boot has idle=poll through idle.sh, as it reads a core
    # count through cpus.sh.
    shutil.copy(IDLE, root / "cloud" / "azure" / "idle.sh")
    shutil.copy(REPO / "cloud" / "campaigns" / "common.sh", root / "cloud" / "campaigns")
    (root / "data" / "plans" / "scratch" / "replay_plan.csv").write_text("event_id\n",
                                                                          encoding="utf-8")
    (root / "cloud" / "hosts.env").write_text(
        "\n".join(["BROKER_PRIV=10.9.9.9", "RECEIVER_IP=10.9.9.8", "SUBNET_PREFIX=24",
                   "SUBNET_GATEWAY=10.9.9.1", "AZ_PROFILE=scratch",
                   "REPO_ROOT=%s" % root.as_posix(), ""]), encoding="utf-8")
    return root


#: These run the scripts themselves, in Git's bash on Windows (tests/posix_shell.py). They were
#: skipped there until 27 September; nothing is skipped now.
needs_bash = pytest.mark.shell


@needs_bash
def test_a_jobs_note_keeps_its_spaces_and_the_keys_before_it_keep_their_meaning(tmp_path):
    """The rounds note is a sentence, so it is the last key on the line and takes the rest of it.
    Everything before it is still read as key=value, including a note that contains an = sign."""
    line = "boot=hz100 backend=kafka rounds=4 note=P2: 4 rounds, power unknown (a=b)"
    assert _queue_call(tmp_path, 'field "%s" note' % line) == "P2: 4 rounds, power unknown (a=b)"
    assert _queue_call(tmp_path, 'field "%s" backend' % line) == "kafka"
    assert _queue_call(tmp_path, 'field "%s" rounds' % line) == "4"


@needs_bash
def test_a_key_that_ends_another_key_is_not_that_key(tmp_path):
    """`ounds` is inside `rounds`, and a substring match would hand the campaign a round count
    nobody asked for. The keys are matched with their space and their equals sign."""
    line = "boot=none block=A4 rounds=4"
    assert _queue_call(tmp_path, 'field "%s" ounds' % line) == ""
    assert _queue_call(tmp_path, 'field "%s" c0' % line) == ""
    assert _queue_call(tmp_path, 'field "%s" block' % line) == "A4"


@needs_bash
def test_a_campaigns_loads_and_its_calibrations_load_are_two_keys(tmp_path):
    """`load` is inside `loads`. A campaign that runs part of its block's loads (D27-4) must not
    hand its calibration the wrong one, nor a single-load job read a list it was never given."""
    line = "boot=none block=A3 loads=75,88 rounds=16"
    assert _queue_call(tmp_path, 'field "%s" loads' % line) == "75,88"
    assert _queue_call(tmp_path, 'field "%s" load' % line) == ""
    assert _queue_call(tmp_path, 'field "boot=none block=A2 load=88" loads') == ""


@needs_bash
def test_the_queue_reaches_as_far_as_a_session_driven_from_outside_does(tmp_path):
    """Two copies of one piece of arithmetic. A calibration that does not reach a campaign's
    longest trip does not fail: the design quietly drops the setups it cannot reach, so the two
    copies disagreeing would cost points rather than raise anything."""
    outside = (KIT / "a2_session.sh").read_text(encoding="utf-8")
    outside = outside.split("reach_ms () {", 1)[1].split("\n}", 1)[0]
    for boot, hz in (("hz1000", "1000"), ("hz250", "250"), ("hz100", "100")):
        mine = _queue_call(tmp_path, "reach_ms %s" % boot)
        theirs = bash(["-c", "reach_ms () {%s\n}\nreach_ms %s" % (outside, hz)],
                      capture_output=True, text=True).stdout.strip()
        assert mine == theirs, boot
    assert _queue_call(tmp_path, "reach_ms hz1000") == "8"
    assert _queue_call(tmp_path, "reach_ms hz100") == "32"


@needs_bash
def test_a_list_is_added_to_and_counted_from_the_disk(tmp_path):
    root = _scratch_checkout(tmp_path)
    for spec in ("boot=hz100 block=A2", "boot=cpu2 block=A5", "boot=none block=A4"):
        bash(["cloud/azure/queue.sh", "add", spec], cwd=root, check=True, capture_output=True)
    shown = bash(["cloud/azure/queue.sh", "show"], cwd=root, capture_output=True,
                 text=True).stdout
    assert "jobs: 3, on job 1, phase prep" in shown
    assert "boot=cpu2 block=A5" in shown


def test_a_job_still_at_work_after_twelve_hours_is_waited_on_not_left():
    """26 September: the 16-round A3 with its calibration ran past twelve hours; the queue went
    on while its last runs were going, cut it at 191 of 192, and the A9 it started beside it
    stopped within a minute. The guard is for a job that died without saying so."""
    code = QUEUE.read_text(encoding="utf-8").replace("\r\n", "\n")
    guard = code.split('if [ "$waited" -ge 720 ]; then', 1)[1].split("\n          fi\n", 1)[0]
    assert guard.index("if work_running; then") < guard.index("requeue_once")
    assert "still at work after" in guard and "waiting on it" in guard
    assert "nothing of it running; going on to the next" in guard


RESUME = KIT / "resume.sh"


def _resumable(tmp_path, release, statuses=("done", "queued"), stop=False):
    """A scratch checkout holding one stopped campaign: its queue, log, calibration and the
    settings that name the kernel it ran on."""
    root = _scratch_checkout(tmp_path)
    shutil.copy(RESUME, root / "cloud" / "azure" / "resume.sh")
    shutil.copy(KIT / "campaign.sh", root / "cloud" / "azure" / "campaign.sh")
    folder = root / "runs" / "azure" / "stage1" / "scratch_20260926T000000Z"
    folder.mkdir(parents=True)
    (folder / "a1_20260926T000000Z.csv").write_text(
        "key,status\n" + "".join("r%03d,%s\n" % (i, s) for i, s in enumerate(statuses)),
        encoding="utf-8")
    (folder / "campaign_a1_20260926T000000Z.log").write_text("STOP_RULE: the brake\n",
                                                            encoding="utf-8")
    (folder / "calibration.json").write_text("{}", encoding="utf-8")
    (folder / "settings.json").write_text(json.dumps({"release": release} if release else {}),
                                          encoding="utf-8")
    if stop:
        (root / "runs" / "azure" / "STOP").write_text("", encoding="utf-8")
    return root, "runs/azure/stage1/scratch_20260926T000000Z"


def _resume(root, folder):
    return bash(["cloud/azure/resume.sh", folder], cwd=root, capture_output=True, text=True,
                extra_env={"HOME": str(root.parent)})


@needs_bash
def test_a_campaign_is_finished_only_on_the_kernel_it_ran_on(tmp_path):
    """D32-2: a campaign's remaining runs are its runs only on the kernel its first ones had."""
    root, folder = _resumable(tmp_path, "6.8.0-not-this-one")
    said = _resume(root, folder)
    assert said.returncode == 2 and "a campaign is finished on its own kernel" in said.stdout


@needs_bash
def test_a_campaign_with_nothing_left_is_left_alone_and_one_without_a_kernel_is_not_resumed(
        tmp_path):
    here = subprocess.run(["uname", "-r"], capture_output=True, text=True).stdout.strip()
    root, folder = _resumable(tmp_path / "done", here, statuses=("done", "done", "failed"))
    said = _resume(root, folder)
    assert said.returncode == 0 and "nothing left to run" in said.stdout
    root, folder = _resumable(tmp_path / "blind", None)
    said = _resume(root, folder)
    assert said.returncode == 2 and "does not say which kernel it ran on" in said.stdout
    root, folder = _resumable(tmp_path / "stop", here, stop=True)
    said = _resume(root, folder)
    assert said.returncode == 2 and "STOP is present" in said.stdout


def test_a_resumed_campaign_runs_on_its_own_queue_and_calibration_with_the_brake_recording():
    code = RESUME.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert 'GOTIT_BRAKE=record CALIBRATION="$DIR/calibration.json" bash cloud/azure/campaign.sh' \
        ' "$QUEUE_CSV"' in code
    assert '| tee "${MAIN_LOG%.log}.resumed.log" >> "$MAIN_LOG"' in code, \
        "the resumed part is in the campaign's own log, where the queue reads it"
    assert code.index("broker-clear --apply") < code.index("bash cloud/azure/campaign.sh")
    assert 'grep -qw sblrecv' in code


def test_the_queue_goes_on_when_one_job_stops_itself():
    """The rule a chain driven from outside used was to stop the lot, and it is the wrong one
    here: the next job is a different kernel asking a different question, and a campaign that
    tripped a brake has still measured everything up to the trip."""
    code = QUEUE.read_text(encoding="utf-8")
    waiting = code.split("      waiting)", 1)[1].split("\n        ;;", 1)[0]
    assert waiting.count("advance") == 3, "done, stopped and given up on all move to the next job"
    assert "requeue_once" in waiting
    assert "exit 1" not in waiting


def test_the_code_is_brought_up_to_date_once_a_job_has_booted_and_before_it_measures():
    """A pair driven by the queue ran whatever code it had when the list was put on it.

    The block jobs go straight to stage0.sh and chain.sh; only the cmd= jobs pulled, because
    their commands happen to say so. matched-b sat four commits behind for a day that way,
    including the commit that corrects a campaign's load to the load the machine shows.
    """
    code = QUEUE.read_text(encoding="utf-8")
    start = code.split("start_job () {", 1)[1].split("\n}", 1)[0]
    assert "pull_code" in start
    assert start.index("verify_boot") < start.index("pull_code") < start.index("stage0.sh session")


def test_the_pull_will_not_merge_and_its_failure_is_a_line_rather_than_a_stopped_job():
    code = QUEUE.read_text(encoding="utf-8")
    body = code.split("pull_code () {", 1)[1].split("\n}", 1)[0]
    assert "--ff-only" in body, "a tree edited on the machine stops rather than merges"
    assert "return 1" not in body and "exit" not in body, \
        "the code it has ran the last job; a pair that goes quiet is worse"
    assert "log " in body, "what it did, or could not do, is in the log either way"


def test_the_loop_runs_from_a_copy_so_a_pull_cannot_rewrite_it_underneath():
    """Bash reads a script as it goes and keeps its place by byte offset, so a loop that pulls
    its own source can carry on in the middle of something else."""
    code = QUEUE.read_text(encoding="utf-8")
    run = code.split("  run)", 1)[1].split("run_loop ;;", 1)[0]
    assert "$RUNNING_NAME" in run and "cp " in run and "exec bash" in run
    assert 'RUNNING_NAME=".queue.running.sh"' in code
    assert code.index("RUNNING_NAME=") < code.index("  run)"), "set before it is used"


def test_the_check_that_the_loop_is_alive_needs_no_name_for_it():
    """The check exists because a lock left by a killed loop made `start` say "running" over a
    queue that was not. It once found the loop by the name of the copy the loop runs from, where a
    renamed copy would have blinded it -- and on 26 September the text of a caller naming that copy
    fooled it. It now follows the process it started, which has no name to get wrong."""
    code = QUEUE.read_text(encoding="utf-8")
    check = code.split("  start)", 1)[1].split(";;", 1)[0].split("sleep 4", 1)[1]
    assert 'kill -0 "$started"' in check
    assert "awk" not in check and "RUNNING_NAME" not in check and ".queue.running" not in check


@needs_bash
def test_a_round_finds_its_own_folder_and_will_not_write_over_runs_already_in_it(tmp_path):
    """tools.sh's own lines for the round and the guard, run as they are written."""
    code = (KIT / "tools.sh").read_text(encoding="utf-8")
    start = 'BASE="${SBL_TOOLS_DIR:-runs/azure/tools}"'
    rounds = start + code.split(start, 1)[1].split("\nesac\n", 1)[0] + "\nesac\n"
    guard = "not_run_yet () {" + code.split("\nnot_run_yet () {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    head = "log () { echo \"$*\"; }\nstop () { log \"STOP_RULE: $*\"; exit 1; }\n"

    def ask(round_, then, base=None):
        env = {"SBL_TOOLS_ROUND": round_}
        if base:
            env["SBL_TOOLS_DIR"] = base
        return bash(["-c", head + rounds + guard + then], cwd=tmp_path, capture_output=True,
                    text=True, extra_env=env)

    assert ask("1", 'echo "$DIR"').stdout.strip() == "runs/azure/tools"
    assert ask("3", 'echo "$DIR"').stdout.strip() == "runs/azure/tools_round3"
    assert ask("x", 'echo "$DIR"').returncode == 2, "a round that is not a number is refused"
    #: Freeze 30's block writes under a name of its own, so none of its rounds can land in the
    #: eleven's folders.
    assert ask("1", 'echo "$DIR"', "runs/azure/tools_v33").stdout.strip() == "runs/azure/tools_v33"
    assert ask("4", 'echo "$DIR"', "runs/azure/tools_v33").stdout.strip() \
        == "runs/azure/tools_v33_round4"
    first = tmp_path / "runs" / "azure" / "tools_round2" / "t1-vegeta-0_5ms"
    first.mkdir(parents=True)
    assert ask("2", 'not_run_yet T1 vegeta "t1-vegeta-*ms/tool.txt"; echo free').stdout.strip() \
        == "free", "a folder with no run in it is not a run"
    (first / "tool.txt").write_text("Requests [total] 3000\n", encoding="utf-8")
    done = ask("2", 'not_run_yet T1 vegeta "t1-vegeta-*ms/tool.txt"; echo free')
    assert done.returncode == 1 and "free" not in done.stdout
    assert "T1 for vegeta has already run in round 2" in done.stdout
    assert ask("3", 'not_run_yet T1 vegeta "t1-vegeta-*ms/tool.txt"; echo free').stdout.strip() \
        == "free", "and another round is another folder"


@needs_bash
def test_a_clock_stepped_for_a_run_is_stepped_back_after_it(tmp_path):
    """T2's own lines for a Go tool's offset, run with stand-ins for sudo and the clock. Every
    line of the first version read right, and a test of the two functions on their own passes on
    it: what was wrong was the call, which kept the record of the step in a subshell. So this runs
    the call as T2 makes it, and asks that the step back was asked for, by the amount stepped."""
    code = (KIT / "tools.sh").read_text(encoding="utf-8")
    functions = "".join(
        name + " () {" + code.split("\n" + name + " () {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
        for name in ("step_clock", "unstep_clock"))
    t2 = code.split("\nt2 () {", 1)[1].split("\n}\n", 1)[0]
    loop = t2.split("for ms in $offsets; do", 1)[1]
    stepping = loop.split('if [ "$how" = clock ]; then\n', 1)[1].split("\n    else\n", 1)[0]
    calls = (tmp_path / "calls").as_posix()
    script = "\n".join([
        "log () { :; }",
        "stop () { echo \"stopped: $*\"; exit 3; }",
        "python3 () { \"" + Path(sys.executable).as_posix() + "\" \"$@\"; }",
        "sudo () {",
        "  echo \"$*\" >> \"" + calls + "\"",
        "  case \"$*\" in",
        "    *\"clock_step.py shift\"*\"--out \"*) echo '{\"moved_ms\": -1.4987}' > \"${@: -1}\" ;;",
        "  esac",
        "}",
        functions,
        "ms=1.5; DIR=\"" + tmp_path.as_posix() + "\"; run=r1; mkdir -p \"$DIR/$run\"",
        "STEPPED_MS=\"\"; STEP_MOVED=\"\"",
        stepping,
        "echo \"moved=$moved\"",
        "unstep_clock",
    ])
    done = bash(["-c", script], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "moved=1.4987" in done.stdout, "how far it moved reaches the run"
    asked = (tmp_path / "calls").read_text(encoding="utf-8").splitlines()
    assert asked[0] == "systemctl stop chrony"
    assert asked[1].startswith("python3 scripts/clock_step.py shift --ms=-1.5 --out ")
    assert asked[2] == "python3 scripts/clock_step.py shift --ms=1.5", \
        "the step back, by what was stepped, in the shell that ran the tool"
    assert asked[3] == "systemctl start chrony"


def test_a_command_job_gets_the_receivers_namespace_back_after_a_reboot():
    """It never survives one. A block job is given it back by rebuild_session; a command was
    given nothing, so the tools block's own guard stopped four jobs in a row on the Arm pair
    -- correctly, since a tool outside it is not reached by the delay."""
    code = QUEUE.read_text(encoding="utf-8")
    booted = code.split("      booted)", 1)[1].split("elif start_job", 1)[0]
    assert "grep -qw sblrecv || namespace_back" in booted
    said = "asked for before the command runs, not after"
    assert booted.index("sblrecv") < booted.index("timeout 43200"), said


def test_a_commands_log_says_which_attempt_of_which_job_wrote_what():
    """The log is appended to, so it keeps a put-back job's first attempt and whatever held that
    number before a list was rewritten. Without a header the top of cmd-12.log was an error from
    a different job hours earlier, and it was read as this one's twice."""
    code = QUEUE.read_text(encoding="utf-8")
    booted = code.split("      booted)", 1)[1].split("\n        ;;", 1)[0]
    assert '>> "$out"' in booted, "kept, not truncated"
    header = booted.split('echo "=== ', 1)[1].split("\n", 1)[0]
    assert "job $(read_at)" in header and "$cmd" in header and "date -u" in header
    assert booted.index('echo "=== ') < booted.index('timeout 43200'), "written before it runs"


def test_a_job_is_put_back_once_and_never_retried_in_place():
    """One more go is worth having; two is a retry loop wearing a different hat, and the second
    failure of the same job is information rather than bad luck."""
    code = QUEUE.read_text(encoding="utf-8")
    body = code.split("requeue_once () {", 1)[1].split("\n}", 1)[0]
    assert 'grep -qxF "$line" "$RETRIED"' in body, "it remembers which jobs have had their second"
    assert body.index("$RETRIED") < body.index('>> "$JOBS"'), "remembered before it is queued"


def test_a_job_that_keeps_rebooting_is_given_up_on():
    """A machine that will not come up the way it was asked is a machine that reboots for ever
    on one job, and it bills the whole time."""
    code = QUEUE.read_text(encoding="utf-8")
    prep = code.split("      prep)", 1)[1].split(";;", 1)[0]
    assert '[ "$n" -gt 2 ]' in prep
    assert "advance" in prep.split('[ "$n" -gt 2 ]', 1)[1]


def test_the_campaign_it_waits_for_is_one_that_did_not_exist_when_it_started():
    """Reading the newest campaign folder reads the last campaign's until this one makes its own,
    and on 21 September that started a calibration on a busy pair and rebooted under a running
    one. The folders are remembered before anything starts."""
    code = QUEUE.read_text(encoding="utf-8")
    start = code.split("start_job () {", 1)[1].split("\n}", 1)[0]
    assert start.index('> "$SEEN"') < start.index("stage0.sh session"), \
        "remembered before the calibration, let alone the campaign"
    state = code.split("campaign_state () {", 1)[1].split("\n}", 1)[0]
    assert 'grep -qxF "$d" "$SEEN" 2>/dev/null && continue' in state


def test_what_makes_it_survive_the_reboot_is_on_the_machine_itself():
    """The whole point. A session driven from a laptop dies with the laptop; this leaves itself a
    note on the driver and an @reboot line to read it."""
    code = QUEUE.read_text(encoding="utf-8")
    assert "@reboot" in code and "crontab -" in code
    assert "queue.sh run" in code.split("@reboot", 1)[1]
    started = code.split("  start)", 1)[1].split(";;", 1)[0]
    assert started.index("crontab -") < started.index("setsid -w nohup"), \
        "the line is in before the loop starts, so a reboot in between is still caught"
    stopped = code.split("  stop)", 1)[1].split(";;", 1)[0]
    assert "crontab -l" in stopped and "grep -v" in stopped, "stopping takes the line out again"


def test_only_one_loop_runs_at_a_time():
    """Two loops on one pair would boot two kernels and place two campaigns on whichever won."""
    code = QUEUE.read_text(encoding="utf-8")
    assert code.count("flock -n") == 2, "the @reboot line and the loop it starts"


def test_the_lock_stays_with_flock_and_is_never_handed_to_a_campaign():
    """On 26 September both x86 loops were stopped and started again while M0 and A3 ran, and
    neither new loop ran: each campaign still held the lock its loop had handed it, since flock
    passes its lock to the command it runs and so to everything that command starts."""
    code = QUEUE.read_text(encoding="utf-8")
    started = code.split("  start)", 1)[1].split(";;", 1)[0]
    assert started.count("flock -n -o") == 2, "the @reboot line and the loop it starts"


def test_start_looks_at_the_process_it_started_not_at_command_lines():
    """A search for a command line that read like a loop's found the text of the command that had
    called start, and said "running" over two pairs that had no loop."""
    code = QUEUE.read_text(encoding="utf-8")
    started = code.split("  start)", 1)[1].split(";;", 1)[0]
    assert "started=$!" in started and 'kill -0 "$started"' in started
    assert "ps -eo" not in started
    assert "setsid -w" in started, "so the process it looks at lives as long as the loop does"


#: A scratch checkout made inside Linux, for the two tests of what the Linux kernel does with the
#: queue's lock. They run in WSL on Windows: Git's bash has no flock, no setsid and no /proc of
#: Linux's kind, and the drivers these scripts run on are Linux.
_LINUX_SCRATCH = r"""
set -u
root=$(mktemp -d)/sbl
mkdir -p "$root/cloud/azure" "$root/cloud/campaigns" "$root/data/plans/scratch" \
  "$root/runs/azure/queue" "$root/bin"
cp "$REPO/cloud/azure/queue.sh" "$root/cloud/azure/"
cp "$REPO/cloud/campaigns/common.sh" "$root/cloud/campaigns/"
printf 'event_id\n' > "$root/data/plans/scratch/replay_plan.csv"
printf 'BROKER_PRIV=10.9.9.9\nRECEIVER_IP=10.9.9.8\nSUBNET_PREFIX=24\nSUBNET_GATEWAY=10.9.9.1\nAZ_PROFILE=scratch\nREPO_ROOT=%s\n' \
  "$root" > "$root/cloud/hosts.env"
# crontab -l has no table to print here; only crontab - reads what it is given. So nothing is
# installed on the machine running the tests.
printf '#!/bin/sh\n[ "$1" = -l ] && exit 1\ncat > /dev/null\n' > "$root/bin/crontab"
chmod +x "$root/bin/crontab"
export PATH="$root/bin:$PATH"
cd "$root"
"""


def test_a_loop_refused_by_a_held_lock_is_reported_whatever_its_caller_says():
    """26 September again: the lock is held by something the old loop started, and the command
    that calls start names the loop in its own text, as the one that night did. Start is not the
    caller's last command, or bash would become it and the caller's text would be gone: the
    command of 26 September went on to read the log after it."""
    done = linux_bash(_LINUX_SCRATCH + r"""
flock runs/azure/queue/lock sleep 30 &
holder=$!
sleep 1
bash -c ': "pgrep -f [.]queue.running.sh run"; bash cloud/azure/queue.sh start; echo "exit=$?"' \
  > out 2> err < /dev/null
kill "$holder"
cat out; echo "--- err"; cat err
""")
    out, _, err = done.stdout.partition("--- err")
    assert "exit=1" in out, done.stdout + done.stderr
    assert "FAILED to start" in err and "running" not in out
    assert "fuser -v" in err


def test_a_loop_that_starts_is_reported_by_its_process_and_holds_the_lock_alone():
    """The other way round, with a job that waits on work already on the pair, so the loop lives
    past the check. Whatever the loop starts must not come to hold the lock: the holders are read
    from /proc, and there must be one, and it must be flock."""
    done = linux_bash(_LINUX_SCRATCH + r"""
printf 'boot=none note=wait\n' > runs/azure/queue/jobs.txt
bash -c 'exec -a "bash cloud/azure/campaign.sh x" sleep 60' &
work=$!
bash cloud/azure/queue.sh start > out 2> err < /dev/null
echo "exit=$?"
loop=$(sed -n 's/.*running (process \([0-9]*\)).*/\1/p' out)
target=$(readlink -f runs/azure/queue/lock)
holders=""
for fd in /proc/[0-9]*/fd/*; do
  [ "$(readlink "$fd" 2>/dev/null)" = "$target" ] && holders="$holders $(echo "$fd" | cut -d/ -f3)"
done
echo "holders=$holders"
for h in $holders; do echo "comm=$(cat "/proc/$h/comm")"; done
kill -0 "$loop" 2>/dev/null && echo "alive=yes"
for h in $holders; do kill -- "-$h" 2>/dev/null; done
kill "$work" 2>/dev/null
cat out err
""")
    text = done.stdout
    assert "exit=0" in text, text + done.stderr
    holders = re.search(r"holders=(.*)", text).group(1).split()
    assert len(holders) == 1, "the loop and what it starts hold nothing: %s" % holders
    assert "comm=flock" in text and "alive=yes" in text


def test_a_job_that_needs_no_reboot_does_not_take_one():
    """The tool campaigns and a second campaign on a kernel already booted need nothing but the
    machine they are on, and a reboot would cost half an hour and a session rebuild for nothing."""
    code = QUEUE.read_text(encoding="utf-8")
    prep = code.split("      prep)", 1)[1].split(";;", 1)[0]
    assert 'if [ "$boot" = none ]; then' in prep
    assert prep.index('if [ "$boot" = none ]; then') < prep.index("systemctl reboot")
    assert "none|stock) return 0" in code, "the stock kernel is booted, not built"


def test_the_machine_is_checked_against_what_the_job_asked_for():
    """A session that reached its core count or its tick some other way than the one asked for
    would not fail. It would run, and be filed under a name that is not true -- which is what
    maxcpus did on 21 September, coming up with all eight CPUs under a folder saying two."""
    code = QUEUE.read_text(encoding="utf-8")
    verify = code.split("verify_boot () {", 1)[1].split("\n}", 1)[0]
    assert "kernels.sh check" in verify and "cpus.sh check" in verify
    assert "*sbl*)" in verify, "a bridge session must not be on a tick build"
    start = code.split("start_job () {", 1)[1].split("\n}", 1)[0]
    assert start.index("verify_boot") < start.index("stage0.sh session")


def test_a_list_can_be_put_on_a_pair_that_is_already_working():
    """A queue installed mid-session would otherwise take its first job at once and reboot under
    a running calibration -- what went wrong twice on 21 September. A first job with no block of
    its own starts nothing and waits for what is already there."""
    code = QUEUE.read_text(encoding="utf-8")
    start = code.split("start_job () {", 1)[1].split("\n}", 1)[0]
    holding = start.split('if [ -z "$block" ]; then', 1)[1].split("fi", 1)[0]
    assert "return 0" in holding and "stage0.sh" not in holding
    assert start.index('if [ -z "$block" ]; then') < start.index("verify_boot"), \
        "it starts nothing, so it also rebuilds nothing and checks no boot"
    assert start.index('if [ -z "$block" ]; then') < start.index("rebuild_session")


def test_a_core_count_is_read_once_and_reaches_all_three_places_that_need_it():
    """A5 asks for its core count at boot, calibrates on that boot and designs its runs for it.
    Two of those three do not fail when they disagree: a campaign designed for eight CPUs on a
    machine booted with two would run, and be filed under a name that is not true. So the boot,
    the calibration and the design all read the one word on the job line."""
    code = QUEUE.read_text(encoding="utf-8")
    start = code.split("start_job () {", 1)[1].split("\n}", 1)[0]
    assert 'case "$boot" in cpu*) cores="${boot#cpu}" ;; esac' in start, "read once, from the boot"
    assert 'CPUS="$cores"' in start, "the calibration is measured at that count"
    assert '[ -n "$cores" ]   && args+=(--cores "$cores")' in start, "and the design writes it"
    assert start.count('cores="${boot#cpu}"') == 1, "one place, so there is nothing to disagree"


def test_a_campaign_that_runs_part_of_its_loads_is_calibrated_at_each_of_them():
    """D27-4: A3 at 75 and 88 only. The loads reach two places that do not fail when they
    disagree -- a calibration that misses one leaves the design nothing to place that load's
    runs from -- so both read the one word on the job line."""
    code = QUEUE.read_text(encoding="utf-8")
    start = code.split("start_job () {", 1)[1].split("\n}", 1)[0]
    assert start.count('loads="$(field "$line" loads)"') == 1
    assert 'C0_LOADS="$loads"' in start, "the calibration covers each of them"
    assert '[ -n "$loads" ]   && args+=(--loads "$loads")' in start, "and the design runs them"
    assert start.index('C0_LOADS="$loads"') < start.index("stage0.sh session")


def test_a_block_with_no_core_count_is_given_none():
    """A2 runs at whatever the machine has, and law_design refuses a core count for a block whose
    design has none, so an empty one must not be passed at all."""
    code = QUEUE.read_text(encoding="utf-8")
    start = code.split("start_job () {", 1)[1].split("\n}", 1)[0]
    assert 'local cores=""' in start
    assert start.index('local cores=""') < start.index('args+=(--cores')



def test_a_holding_job_waits_on_the_machine_rather_than_on_a_word_in_a_log():
    """A job of its own waits for a campaign folder that was not there when it started. A job
    that only holds the list back cannot: the session it waits for may have made its folder
    already, so no new one is coming and the wait would run to its twelve-hour limit. What it is
    really waiting for is the machine, so it asks the machine."""
    code = QUEUE.read_text(encoding="utf-8")
    assert "work_running () {" in code
    assert "ps -eo args --no-headers" in code, "read here, not over ssh"
    assert "!/awk/" in code, "and not matching the command line that carries the pattern"
    waiting = code.split("      waiting)", 1)[1].split("\n        ;;", 1)[0]
    assert 'if [ -z "$(field "$line" block)" ]; then' in waiting
    assert "work_running" in waiting


@needs_bash
@pytest.mark.parametrize("line,busy", [
    ("bash cloud/azure/campaign.sh runs/azure/stage1/x/a3.csv", True),
    ("bash cloud/azure/chain.sh A3 --rounds 24", True),
    # The tools block makes runs for hours and never through campaign.sh. Read on the first x86
    # pair mid-staircase on 24 September, the pattern without these called that pair quiet.
    ("bash cloud/azure/tools.sh t4 memtier_benchmark", True),
    ("bash cloud/azure/tools_run.sh rdkafka_performance runs/azure/tools/t1-x", True),
    # The loop that asks is not work: counting itself, it would never let a list end.
    ("bash cloud/azure/queue.sh run", False),
    ("bash cloud/azure/.queue.running.sh run", False),
    ("sleep 60", False)])
def test_what_the_queue_counts_as_the_pair_being_at_work(tmp_path, line, busy):
    """Run the awk program queue.sh actually carries, not a copy of its pattern."""
    code = QUEUE.read_text(encoding="utf-8")
    body = code.split("work_running () {", 1)[1].split("\n}", 1)[0]
    program = body.split("awk '", 1)[1].rsplit("'", 1)[0]
    found = subprocess.run([tool("awk"), program], input=line + "\n", capture_output=True,
                           text=True)
    assert (found.returncode == 0) is busy, \
        "%r should read as %s" % (line, "work" if busy else "not work")


class TestAPairStopsWhenItsWorkEnds:
    """stop_when_idle.sh, written when the PC running the watch was restarted and took the idle
    rule with it. The queue could not stand in: its holding job gives up after twelve hours, and
    the Arm pair's A3 had sixteen left."""

    def code(self):
        return (KIT / "stop_when_idle.sh").read_text(encoding="utf-8")

    def test_it_reads_the_work_from_the_environment_not_its_own_command_line(self):
        """A pattern on the command line is a process the pattern matches, for ever."""
        code = self.code()
        assert 'ENVIRON["WORK"]' in code and "!/awk/" in code
        assert "export WORK" in code

    def test_it_waits_for_quiet_looks_in_a_row_before_it_stops_anything(self):
        """Work hands over, and a waiter between two pieces of it is asleep for a minute."""
        code = self.code()
        assert "quiet=0" in code, "any look that finds work starts the count again"
        assert 'LOOKS="${LOOKS:-2}"' in code

    def test_it_stops_the_pair_the_way_the_queue_does(self):
        """Through the driver's own identity, so it needs nobody's login and nobody's PC."""
        code = self.code()
        assert code.rstrip().endswith("bash cloud/azure/stop_self.sh")
        assert 'cd "$HOME/sbl"' in code, "from outside the checkout as well as inside it"

    @needs_bash
    @pytest.mark.parametrize("pattern,refused", [
        # A plain word matches its own spelling. Found by testing it on the first x86 pair with
        # a made-up process name: the waiter counted the test's own command line as work.
        ("run_t2_all", True),
        ("azure/(tools)[.]sh|run_t2_all", True),
        # One bracketed letter, and it matches the process but no longer its own text.
        ("run_t2_al[l]", False),
        ("azure/(campaign|stage0|stage1|chain)[.]sh", False),
        ("azure/(campaign|stage0|stage1|chain|tools|tools_run)[.]sh|run_t2_al[l]|run_missing_tool[s]",
         False)])
    def test_it_refuses_a_pattern_that_matches_its_own_spelling(self, pattern, refused):
        """Such a pattern counts any command line carrying it as work, and the pair never stops."""
        code = self.code()
        guard = code.split("if printf '%s\\n' \"$WORK\" | awk '", 1)[1].split("'", 1)[0]
        found = subprocess.run([tool("awk"), guard], input=pattern + "\n", capture_output=True,
                               text=True, env=dict(os.environ, WORK=pattern))
        assert (found.returncode == 0) is refused, pattern

    def test_it_has_no_limit_of_its_own(self):
        """The queue's twelve hours is the reason this exists."""
        code = self.code()
        assert "720" not in code and "12 hours" not in code

    @needs_bash
    def test_it_parses(self):
        assert bash(["-n", str(KIT / "stop_when_idle.sh")]).returncode == 0


@needs_bash
def test_a_command_and_a_note_each_take_the_rest_of_their_line(tmp_path):
    """Two keys hold sentences rather than words. A job carries at most one, and the keys before
    it are still read as key=value."""
    job = "boot=none cmd=bash cloud/azure/tools.sh t1 vegeta"
    assert _queue_call(tmp_path, 'field "%s" cmd' % job) == "bash cloud/azure/tools.sh t1 vegeta"
    assert _queue_call(tmp_path, 'field "%s" boot' % job) == "none"
    assert _queue_call(tmp_path, 'field "%s" note' % job) == ""
    assert _queue_call(tmp_path, 'field "%s" block' % job) == "", \
        "a word key must not reach into the command"
    noted = "boot=hz100 block=A2 note=4 rounds, power unknown"
    assert _queue_call(tmp_path, 'field "%s" cmd' % noted) == ""
    assert _queue_call(tmp_path, 'field "%s" note' % noted) == "4 rounds, power unknown"


def test_work_that_no_calibration_places_is_still_on_the_list():
    """The tools block is not a campaign: nothing places it and no chain waits on one. It is run
    by the loop itself rather than let go of, because the loop is already the thing that
    survives, and a command that outlived it would have nobody to tell."""
    code = QUEUE.read_text(encoding="utf-8")
    booted = code.split("      booted)", 1)[1].split("\n        ;;", 1)[0]
    assert 'cmd="$(field "$line" cmd)"' in booted
    assert "timeout 43200" in booted, "a command that hangs does not hang the list"
    assert 'requeue_once "$line"' in booted, "one that fails gets its second go like any job"
    assert booted.index("timeout 43200") < booted.index("advance")
    assert "rebuild_session" not in booted.split('if [ -n "$cmd" ]', 1)[1].split("elif", 1)[0], \
        "the tools block puts up its own servers, and rebuilding ours would fight it"


class TestACampaignIsGatedOnTheCalibrationItIsPlacedFrom:
    """It used to require every gate in the file, whichever backend the campaign ran.

    That cost three sessions on 22 September. On the second x86 pair Kafka's calibration cannot
    be known within 0.3 ms on the coarse-tick kernels -- 0.311 to 0.410 against the 0.3 the gate
    asks -- while Redis's is 0.128 to 0.237 on every one of them. Redis campaigns were refused
    for the state of a calibration they are not placed from, each after about two and a half
    hours of calibrating.
    """

    def _gate(self, tmp_path, calibration, *backends):
        """The gate check exactly as stage1.sh runs it."""
        code = (KIT / "stage1.sh").read_text(encoding="utf-8")
        code = code.split("python3 -c '", 1)[1].split("' \\\n", 1)[0]
        path = tmp_path / "calibration.json"
        path.write_text(json.dumps({"calibration": calibration}), encoding="utf-8")
        done = subprocess.run([sys.executable, "-c", code, str(path), *backends],
                              capture_output=True)
        return done.returncode == 0

    def _fit(self, ok):
        return {"75": {"gate": {"ok": ok, "known_within_the_bound": ok}}}

    def test_a_redis_campaign_runs_when_redis_passed_and_kafka_did_not(self, tmp_path):
        both = {"kafka": self._fit(False), "redis": self._fit(True)}
        assert self._gate(tmp_path, both, "redis") is True
        assert self._gate(tmp_path, both, "kafka") is False

    def test_naming_no_backend_still_requires_them_all(self, tmp_path):
        """A5 runs both backends in one campaign and is placed from both fits."""
        both = {"kafka": self._fit(False), "redis": self._fit(True)}
        assert self._gate(tmp_path, both) is False
        assert self._gate(tmp_path, {"kafka": self._fit(True), "redis": self._fit(True)}) is True

    def test_a_campaign_naming_two_backends_needs_both(self, tmp_path):
        both = {"kafka": self._fit(False), "redis": self._fit(True)}
        assert self._gate(tmp_path, both, "redis", "kafka") is False

    def test_an_a8_session_keyed_by_client_is_still_reached(self, tmp_path):
        """Its gates sit one level deeper: client, then backend, then load."""
        keyed = {"python": {"kafka": self._fit(True)}, "java": {"kafka": self._fit(False)}}
        assert self._gate(tmp_path, keyed, "kafka") is False
        passing = {"python": {"kafka": self._fit(True)}, "java": {"kafka": self._fit(True)}}
        assert self._gate(tmp_path, passing, "kafka") is True

    def test_a_backend_the_calibration_never_fitted_is_refused(self, tmp_path):
        """Not silently allowed: no gate matching the campaign's backend means nothing placed it."""
        assert self._gate(tmp_path, {"redis": self._fit(True)}, "kafka") is False

    def test_an_empty_calibration_is_refused(self, tmp_path):
        assert self._gate(tmp_path, {}, "redis") is False
        assert self._gate(tmp_path, {}) is False


class TestEveryPinnedToolHasSomethingThatInstallsIt:
    """install listed the pins, installed the build dependencies, and then only *reported* which
    tools were present. Nothing in it fetched or built a single one of the ten.

    It ran on the broker on 22 September in under a second and said MISSING eleven times, and
    every T1 job behind it failed. The step had never been run on a machine -- T1 and T2 were
    checked against made-up tools -- so nothing had ever asked it to produce a binary.
    """

    def _tools(self):
        text = (KIT / "tools.sh").read_text(encoding="utf-8")
        table = text.split("PINNED='", 1)[1].split("'", 1)[0]
        return [line.split("|")[0] for line in table.strip().splitlines() if line.strip()]

    def test_the_block_pins_the_ten_tools_the_plan_counts(self):
        """Eleven for the first block (ten runnable, Kafka's two bundled tools apart), the five
        freeze 30 adds (D33-1), the four freeze 32 adds (D35-1), YSB (D36-1), freeze 34's
        PerfKit and Stream PerfTest as one instance, which shares its jar with the two-instance
        runs but is its own way of running it, freeze 35's four (D38-1), freeze 36's three
        (D39-1), freeze 37's two (D40-1), and freeze 38's Pub/Sub load test (D41-1)."""
        assert len(self._tools()) == 33

    @pytest.mark.parametrize("tool", ["vegeta", "hey", "k6", "wrk2", "valkey-benchmark",
                                      "memtier_benchmark", "rdkafka_performance",
                                      "kafka-end-to-end", "kafka-producer-perf",
                                      "rabbitmq-perftest", "nats-latency", "omb", "pulsar-perf",
                                      "emqtt-bench", "ycsb", "nats-bench"])
    def test_each_one_is_fetched_or_built_by_the_install_step(self, tool):
        """The invariant that was missing. A tool named in the table and nowhere else in the
        step is a tool the step cannot produce, and every run of it fails hours later."""
        install = (KIT / "tools.sh").read_text(encoding="utf-8").split("install () {", 1)[1]
        builders = {"vegeta": "go_tool vegeta", "hey": "go_tool hey", "k6": "go_tool k6",
                    "wrk2": "git_build wrk2", "valkey-benchmark": "git_build valkey",
                    "memtier_benchmark": "git_build memtier",
                    "rdkafka_performance": "git_build librdkafka",
                    "kafka-end-to-end": "get_kafka", "kafka-producer-perf": "get_kafka",
                    "rabbitmq-perftest": "get_perftest", "nats-latency": "go_tool nats",
                    "omb": "get_omb 5b1fa709", "pulsar-perf": "get_pulsar",
                    "emqtt-bench": "get_emqtt_bench cb86b188", "ycsb": "get_ycsb 66302f30",
                    "nats-bench": "go_tool nats"}
        assert builders[tool] in install, "%s has nothing that installs it" % tool

    def test_the_five_are_installed_at_the_versions_their_pins_name(self):
        """The table and the step that installs say the same thing, so neither can drift alone."""
        text = (KIT / "tools.sh").read_text(encoding="utf-8")
        table = dict(line.split("|")[0::2] for line in
                     text.split("PINNED='", 1)[1].split("'", 1)[0].strip().splitlines())
        install = text.split("\ninstall () {", 1)[1].split("\n}\n", 1)[0]
        for tool, call in (("omb", "get_omb"), ("emqtt-bench", "get_emqtt_bench"),
                           ("ycsb", "get_ycsb")):
            assert "%s %s" % (call, table[tool]) in install, tool
        assert table["pulsar-perf"] == re.search(r'PULSAR_VERSION="([\d.]+)"', text).group(1)
        assert table["nats-bench"] == table["nats-latency"], "one build of the NATS CLI"

    def test_what_their_builders_fetch_is_checked_against_a_published_checksum(self):
        text = (KIT / "tools.sh").read_text(encoding="utf-8")
        for name, bits in (("MAVEN_SHA512", 128), ("OTP_SHA256", 64), ("PULSAR_SHA512", 128)):
            assert re.search(r'%s="[0-9a-f]{%d}"' % (name, bits), text), name
        check = text.split("\nfetch_checked () {", 1)[1].split("\n}\n", 1)[0]
        assert 'sha$3sum" -c -' in check, "and the archive is refused when it does not match"

    def test_java_17_comes_in_without_taking_java_11s_place(self):
        """Installing 17 made it the default in the pilot; the first eleven ran on 11."""
        body = (KIT / "tools.sh").read_text(encoding="utf-8").split("\nget_java17 () {", 1)[1] \
            .split("\n}\n", 1)[0]
        assert 'update-alternatives --set "$t" "$JAVA11/bin/$t"' in body

    def test_a_tool_that_will_not_build_does_not_stop_the_other_nine(self):
        """A block reporting on nine tools is worth more than one reporting on none because a
        single upstream moved."""
        text = (KIT / "tools.sh").read_text(encoding="utf-8")
        for helper in ("go_tool () {", "git_build () {", "get_kafka () {", "get_perftest () {",
                       "get_java17 () {", "get_maven () {", "get_omb () {", "get_pulsar () {",
                       "get_emqtt_bench () {", "get_ycsb () {"):
            body = text.split(helper, 1)[1].split("\n}", 1)[0]
            assert "WARN" in body and "stop " not in body, helper

    def test_the_compiler_is_pinned_like_the_tools_it_builds(self):
        """Ubuntu 22.04 ships Go 1.18 and k6 needs newer, so the toolchain is fetched -- and it
        is part of what produced a binary whose behaviour this block reports."""
        text = (KIT / "tools.sh").read_text(encoding="utf-8")
        assert re.search(r'GO_VERSION="\d+\.\d+\.\d+"', text)
        assert "go.dev/dl/go$GO_VERSION" in text

    def test_what_each_build_resolved_is_written_down(self):
        """Three of the eleven are pinned "resolve", and the plan says what actually installed is
        recorded before any T1 run."""
        text = (KIT / "tools.sh").read_text(encoding="utf-8")
        for record in ("commit_$name.txt", "kafka_tools_version.txt", "commit_perftest.txt",
                       "version_$binary.txt"):
            assert record in text, record


class TestTheLoadIsCorrectedToWhatTheMachineShows:
    """stress-ng is told a duty; what the machine shows is that duty plus the harness's own use.

    On eight CPUs the harness is under a point of the machine and nobody noticed. On two it is
    over three, and A5's two-CPU calibration failed its own runs at 78.1% against a 75% design --
    three of them, before it had measured anything. Widening the check would have been the wrong
    answer: A5 compares core counts at one load, so two CPUs at 78 and eight at 75 puts a
    difference in load exactly where the difference in cores is meant to be.
    """

    def code(self):
        return (KIT / "campaign.sh").read_text(encoding="utf-8")

    def test_the_duty_is_corrected_against_what_the_machine_shows(self):
        code = self.code()
        assert "load_correction.json" in code, "and what it was corrected to is written down"
        block = code.split("sampler_pid=$!", 1)[1].split("if [ -n \"$TRACE_HALF\"", 1)[0]
        # Plan version 47 (23 Oct 2026): through load_start, which starts every load the runner runs.
        assert 'load_start "$adjusted" "$want_cpus" 3600s' in block
        assert 'kill -9 "$stress_pid"' in block, "the first one is stopped before the second starts"

    def test_the_first_one_is_stopped_with_a_signal_it_cannot_decline(self):
        """A polite TERM and then a wait is a wait for stress-ng's own hour-long timeout.

        On 23 September four runs of matched's A2 took 62.7 minutes each rather than 2.8, and
        matched-b spent four of its twelve hours the same way and left 24 of its 60 runs
        unmeasured. Every run that stalled took this branch and no run outside it stalled, on
        either pair, 52 runs to nothing. The wait is what makes the signal matter: a TERM that
        stress-ng ignores turns the next line into a blocking wait for --timeout 3600s.
        """
        code = self.code()
        block = code.split("sampler_pid=$!", 1)[1].split("if [ -n \"$TRACE_HALF\"", 1)[0]
        for line in block.split("\n"):
            if 'wait "$stress_pid"' not in line:
                continue
            assert 'kill -9 "$stress_pid"' in line, \
                "waiting on a process stopped by anything it can decline can wait the hour out"

    def test_it_happens_before_anything_is_counted(self):
        """A correction made after the warm-up would move the load under the measured messages."""
        code = self.code()
        assert code.index("load_correction.json") < code.index("run_kafka_trial.sh") \
            or code.index("load_correction.json") < code.index("WARMUP"), \
            "corrected before the trial runs"

    def test_the_correction_is_bounded(self):
        """A machine that shows something absurd must not be asked for a duty that is absurd."""
        code = self.code()
        assert "min(100.0, max(1.0, out))" in code

    def test_a_machine_that_shows_nothing_is_left_alone(self):
        """No samples yet is not a reason to change the duty to something invented."""
        code = self.code()
        assert 'if [ -n "$shown" ]; then' in code

    def test_the_design_is_what_the_check_still_judges(self):
        """The correction moves the duty, never the number the run is held to."""
        integrity = (REPO / "scripts" / "run_integrity.py").read_text(encoding="utf-8")
        assert 'float(params["load_pct"])' in integrity, "judged against the designed load"
        assert "LOAD_POINTS = 3.0" in integrity, "and the tolerance is unchanged"


class TestTheReferenceEveryToolNumberIsReadAgainst:
    """The block's first paragraph says every number a tool reports has a reference measured
    beside it. Nothing took that reference.

    reference_trips.json was read in two places -- T2's offsets are set from the median true trip
    and the tool's own bias is cancelled against it -- and written in none. T2 would have stopped
    on its first run, hours after the tools were built, asking for a file nothing creates.
    """

    def tools(self):
        return (KIT / "tools.sh").read_text(encoding="utf-8")

    def test_the_reference_is_taken_and_not_only_read(self):
        code = self.tools()
        assert "reference_for () {" in code
        assert code.count("reference_trips.json") >= 3, "written as well as read twice"

    def test_it_is_our_own_client_on_the_same_path(self):
        """Not the tool's own reading of itself, which is the thing being judged."""
        code = self.tools().split("reference_for () {", 1)[1].split("\n}", 1)[0]
        assert "bash scripts/run_kafka_trial.sh" in code
        assert "bash scripts/run_redis_trial.sh" in code
        assert "pilot_checks" in code, "trips read the way every campaign reads them"

    def test_it_is_called_the_way_a_campaign_calls_it(self):
        """"The same client every law campaign uses" has to mean the same client, the same
        workload and the same path, or the trip it measures is not the trip the tools are read
        against. Passing only a run id and a plan left the trial on its own defaults: localhost
        for the broker, so the consumer was refused at 127.0.0.1:6379 while redis ran on the
        other machine; a StatsBomb plan at whatever rate it holds, where every campaign runs a
        synthetic constant-rate one; and no consumer wrap, so nothing sat behind the receiver's
        address.
        """
        code = self.tools().split("reference_for () {", 1)[1].split("\n}", 1)[0]
        campaign = (KIT / "campaign.sh").read_text(encoding="utf-8")
        for flag in ("-BOOTSTRAP", "-RedisHost", "-PORT", "-IDLE_SECONDS"):
            assert flag in code, "%s reaches the trial in a campaign and must here too" % flag
        for name in ("KAFKA_BOOTSTRAP", "REDIS_HOST", "REDIS_PORT"):
            assert name in code and name in campaign, name
        assert "data/synthetic/constant_r" in code, "the plan every campaign runs, not any plan"
        assert "assert_plan_rate" in code, "and at the speedup that plan's rate asks for"
        assert 'SBL_CONSUMER_WRAP="$NETNS' in code, \
            "the consumer behind the receiver's address, as campaign.sh puts it"

    def test_no_local_uses_a_name_the_same_local_declares(self):
        """Bash expands every word of a `local` before it runs any of them.

        So `local tool="$1" run="$DIR/t1-$tool-0ms"` reads $tool before it exists, and under
        `set -u` the script is over in the same second it started. The queue's field reader was
        written that way once and the tools block's reference command once more.
        """
        for path in sorted(KIT.glob("*.sh")) + sorted((KIT.parent / "campaigns").glob("*.sh")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                said = line.strip()
                if not said.startswith("local "):
                    continue
                rest = said[len("local "):]
                declared = set(re.findall(r"(\w+)=", rest))
                used = set(re.findall(r"\$\{?(\w+)", rest))
                assert not (declared & used), \
                    "%s:%d reads %s on the `local` that declares it" % (
                        path.name, n, ", ".join(sorted(declared & used)))

    def test_no_line_continuation_was_written_as_two_characters(self):
        """A backslash-n in the middle of a command is not a new line, it is the argument `n`.

        It gets there because a doubled backslash arrives as one through a shell heredoc, and it
        has done so three times now. Here it put `n` on the end of two tools_run.sh calls and the
        redirection on the same line; tools_run.sh reads only its first two arguments, so nothing
        was measured wrongly, which is exactly why nobody would have noticed.
        """
        #: A space either side, which is what a continuation would have had and what a newline
        #: inside a printf format -- `%s}\n' \` -- does not.
        for path in sorted(KIT.glob("*.sh")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                assert " \\n " not in line.split("#", 1)[0], \
                    "%s:%d writes a line continuation as two characters" % (path.name, n)

    def test_it_is_taken_at_the_zero_step(self):
        """T2 reads t1-<tool>-0ms, and an offset measured under an added delay is not the
        path's own trip."""
        t1 = self.tools().split("t1 () {", 1)[1].split("\n}", 1)[0]
        assert '[ "$ms" = 0 ] && reference_for' in t1

    def test_a_protocol_we_have_no_client_for_says_so(self):
        """wrk2 speaks HTTP and PerfTest speaks AMQP. Saying so beats inventing a reference."""
        code = self.tools().split("reference_for () {", 1)[1].split("\n}", 1)[0]
        assert "no client of ours speaks" in code
        for tool in ("valkey-benchmark", "memtier_benchmark"):
            assert tool in code, tool
        for tool in ("rdkafka_performance", "kafka-end-to-end", "kafka-producer-perf"):
            assert tool in code, tool

    def test_a_staircase_that_ran_without_one_can_be_given_a_reference_on_its_own(self):
        """Five staircases were measured soundly while the reference could not connect.

        Re-running T1 would overwrite those measurements with a second set for the sake of one
        file, and the folders carry no timestamp, so there would be nothing left of the first.
        """
        code = self.tools()
        assert "  reference) reference " in code, "it has a command of its own"
        body = code.split("\nreference () {", 1)[1].split("\n}", 1)[0]
        assert "hold_for 0" in body, "the same zero hold the zero step applies"
        assert "needs_namespace" in body and "release_delay" in body
        assert "reference_for" in body, "and the same call, so it is the same measurement"
        assert "reference.first_attempt.log" in body, "what failed is kept"
        assert "taken_after_the_staircase" in body, "and the folder says it came later"

    def test_it_will_not_replace_a_reference_t1_already_took(self):
        """The one taken at the zero step is the one the design asks for."""
        body = self.tools().split("\nreference () {", 1)[1].split("\n}", 1)[0]
        guard = body.split('[ -s "$run/reference_trips.json" ]', 1)[1].split("\n", 2)
        assert "stop" in " ".join(guard[:2])
        assert body.index("reference_trips.json") < body.index("reference_for"), \
            "checked before anything is measured"

    def test_t2_still_refuses_rather_than_guesses_without_one(self):
        t2 = self.tools().split("t2 () {", 1)[1].split("\n}", 1)[0]
        assert "T2 needs T1's zero-delay run" in t2

def test_the_amqp_broker_lets_the_driver_in():
    """RabbitMQ lets its default user in from the machine itself and nowhere else. Every
    broker here is on the other machine by design, so PerfTest got ACCESS_REFUSED on every
    run and printed no latency at all: ten staircase steps of nothing, and a T2 that would
    not start for want of the reference T1 never took."""
    code = (KIT / "tools.sh").read_text(encoding="utf-8")
    brokers = code.split("\nbrokers_here () {", 1)[1].split("\n}", 1)[0]
    assert "loopback_users = none" in brokers
    assert "/etc/rabbitmq/conf.d/" in brokers, "its own file, not an edit of theirs"
    said = "written before the restart that reads it"
    assert brokers.index("loopback_users") < brokers.index("restart rabbitmq-server"), said


class TestTheServersAreSetUpWhereTheToolsReachThem:
    """The test above passed all along, and on 24 September PerfTest got ACCESS_REFUSED anyway.
    It checks what the setup writes; nothing checked which machine it was written on. `brokers`
    was run on the driver, set the driver's servers up, asked 127.0.0.1 whether they answered,
    and certified a machine the tools never talk to. Thirty runs of two tools measured nothing.
    """

    def code(self):
        return (KIT / "tools.sh").read_text(encoding="utf-8")

    def entry(self):
        return self.code().split("\nbrokers () {", 1)[1].split("\n}", 1)[0]

    def test_from_anywhere_but_the_broker_it_does_the_work_on_the_broker(self):
        entry = self.entry()
        assert 'grep -q " ${BROKER_PRIV}/"' in entry, "it asks whether it is the broker"
        call = entry.split('remote_broker "', 1)[1].split('" \\', 1)[0]
        assert call.startswith("cd sbl && ") and call.endswith("bash cloud/azure/tools.sh brokers")

    def test_the_broker_is_told_its_own_address_and_brought_up_to_date(self):
        """The broker has no hosts.env -- session.sh leaves that on the driver only -- so
        common.sh would not load there, and on 25 September its checkout was eight commits old.
        The delegation had been read in a test and never run end to end."""
        call = self.entry().split('remote_broker "', 1)[1].split('" \\', 1)[0]
        assert "BROKER_PRIV=$BROKER_PRIV bash cloud/azure/tools.sh brokers" in call
        assert "git pull -q --ff-only origin main" in call
        assert call.index("git pull") < call.index("tools.sh brokers"), "brought up first"

    def test_and_then_checks_from_here_rather_than_from_127_0_0_1(self):
        entry = self.entry()
        assert "server_answers" in entry, "asked the way the tools will be answered"
        assert "127.0.0.1" not in entry, "not the loopback of a machine the tools do not use"
        after = entry.split("remote_broker", 1)[1]
        assert "server_answers" in after, "and after the setup, not before it"

    def test_on_the_broker_it_is_the_setup_it_always_was(self):
        assert self.entry().rstrip().endswith("brokers_here")

    def test_each_servers_check_asks_what_its_tool_needs_not_whether_a_port_is_open(self):
        body = self.code().split("\nserver_answers () {", 1)[1].split("\n}", 1)[0]
        assert '"200 512"' in body, "the fixed page, the size every HTTP tool is timed against"
        assert "+PONG" in body, "a Redis that answers"
        assert "loopback_users" in body, "a RabbitMQ that lets the tools' user in from here"
        assert '"INFO"' in body, "a NATS server's greeting"

    def test_every_stage_asks_before_it_runs(self):
        """A server can go between one stage and the next."""
        code = self.code()
        for stage in ("t1", "t2", "t3", "t4"):
            body = code.split("\n%s () {" % stage, 1)[1].split("\n}\n", 1)[0]
            head = body.split("\n")[:5]
            assert any('needs_server "$tool"' in line for line in head), stage

    def test_nats_is_a_unit_that_outlives_the_session_that_started_it(self):
        body = self.code().split("\nbrokers_here () {", 1)[1].split("\n}", 1)[0]
        assert "nohup nats-server" not in body
        assert "/etc/systemd/system/sbl-nats.service" in body
        assert "Restart=always" in body and "enable --now sbl-nats" in body


@pytest.mark.parametrize("script", ["campaign.sh", "tools.sh"])
def test_no_stress_ng_is_waited_for_after_a_signal_it_can_decline(script):
    """A TERM stress-ng ignores turns the wait after it into a wait for its own --timeout.

    Found in campaign.sh on 23 September -- an hour for a three-minute run -- and fixed there. The
    same two lines were in T3, and every 88% step of every tool took ten minutes for one until
    24 September. Asked of every script that starts it, so a third copy cannot hide the same way.
    """
    code = (KIT / script).read_text(encoding="utf-8")
    for line in code.splitlines():
        if re.search(r"\bwait \"\$stress", line):
            assert re.search(r"kill -9 \"\$stress", line), \
                "%s waits on a stress-ng stopped by a signal it can decline: %s" % (
                    script, line.strip())


class TestEveryToolHasAReferenceOfOurOwn:
    """Seven of the eleven tools had no reference until 25 September, because the study's own
    program speaks Kafka and Redis only. T2 takes its offsets and its predictions from one."""

    def reference(self):
        code = (KIT / "tools.sh").read_text(encoding="utf-8")
        return code.split("\nreference_for () {", 1)[1].split("\n}\n", 1)[0]

    @pytest.mark.parametrize("tool,client", [
        ("vegeta", "http_reference.py"), ("hey", "http_reference.py"),
        ("k6", "http_reference.py"), ("wrk2", "http_reference.py"),
        ("rabbitmq-perftest", "amqp_reference.py"), ("nats-latency", "nats_reference.py"),
        ("nats-bench", "nats_reference.py"), ("emqtt-bench", "mqtt_reference.py"),
        ("pulsar-perf", "pulsar_reference.py")])
    def test_each_protocol_has_a_client(self, tool, client):
        cases = self.reference().split('case "$tool" in', 1)[1].split("esac", 1)[0]
        line = next(l for l in cases.splitlines() if re.search(r"(^|\|)\s*%s[|)]" % re.escape(
            tool), l.strip()))
        assert client in line, "%s is referenced by %s" % (tool, client)
        assert (REPO / "scripts" / client).exists()

    def test_the_client_is_given_its_settings_as_arguments_that_sudo_keeps(self):
        """The environment is what sudo cleared for k6, which then made no request at all."""
        body = self.reference()
        run = body.split('if [ -n "$client" ]; then', 1)[1].split("fi", 1)[0]
        assert "$NETNS" in run, "from inside the receiver's namespace, like every tool here"
        assert "--rate" in run and "--seconds" in run and "--out" in run

    def test_the_amqp_client_is_installed_pinned(self):
        code = (KIT / "tools.sh").read_text(encoding="utf-8")
        install = code.split("\ninstall () {", 1)[1].split("\n}\n", 1)[0]
        assert re.search(r'pip3 install -q "pika==\d+\.\d+\.\d+"', install)
        assert re.search(r'pip3 install -q "pulsar-client==\d+\.\d+\.\d+"', install), \
            "and so is the library the Pulsar reference speaks through"

    def test_the_tools_that_speak_kafka_or_redis_are_read_against_our_own_program(self):
        """OMB and YCSB speak to the same Kafka and Redis the law campaigns do, so their reference
        is the study's own client, as it is for the five tools that speak those already."""
        cases = self.reference().split('case "$tool" in', 1)[1].split("esac", 1)[0]
        assert re.search(r"^\s*valkey-benchmark\|memtier_benchmark\|ycsb\) backend=redis", cases,
                         re.M)
        assert re.search(r"\|omb\) backend=kafka", cases)


class TestFreeze21InTheToolsBlock:
    """What freeze 21 changed in how the tools are run and judged."""

    def tools(self):
        return (KIT / "tools.sh").read_text(encoding="utf-8")

    def test_k6_takes_its_settings_as_flags_that_sudo_keeps(self):
        """D25-3. Through the environment, sudo cleared them and k6 made no request at all."""
        runner = (KIT / "tools_run.sh").read_text(encoding="utf-8")
        k6 = runner.split("\n  k6)", 1)[1].split(";;", 1)[0]
        command = [line for line in k6.splitlines() if not line.strip().startswith("#")]
        body = "\n".join(command)
        for name in ("SBL_DURATION", "SBL_TARGET", "SBL_RATE"):
            assert "--env %s=" % name in body, name
            assert not re.search(r"^\s*%s=" % name, body, re.M), \
                "%s is not set as an environment prefix, which sudo clears" % name

    def test_t2_is_judged_with_the_noise_of_the_tools_own_staircase(self):
        """D25-2: the judge is given the T1 runs, and so judges as freeze 21 says."""
        t2 = self.tools().split("\nt2 () {", 1)[1].split("\n}\n", 1)[0]
        judge = t2.split("tool_negatives.py judge", 1)[1].split("|| log", 1)[0]
        assert '--staircase "$DIR" --tool "$tool"' in judge
        assert "--control" in judge and "--shift-ms" in judge

    def test_t1_asks_whether_it_measured_the_path(self):
        """D25-5: the slope is recorded at the end of every staircase, and a flat one said so."""
        t1 = self.tools().split("\nt1 () {", 1)[1].split("\n}\n", 1)[0]
        tail = t1.split("release_delay", 1)[1]
        assert "tool_readings.py staircase" in tail and "measured_the_path" in tail
        assert tail.index("tool_readings.py staircase") < tail.index("CAMPAIGN_COMPLETE: T1")


def test_a_jar_is_asked_whether_it_starts_whatever_the_record_says():
    """The first x86 pair's record predated the question, and said yes to a jar that could not."""
    code = (KIT / "tools.sh").read_text(encoding="utf-8")
    have = code.split("\nhave_tool () {", 1)[1].split("\n}", 1)[0]
    assert "rabbitmq-perftest)" in have and "runnable_jar" in have


class TestAPairThatTurnsItselfOff:
    """A machine that has finished its list kept billing until somebody noticed, and nothing on
    it could do anything about it: no Azure CLI and no identity, so deallocating a pair could
    only be done from outside, by hand. Two days of unattended work meant two days in which the
    only thing between a finished pair and an empty subscription was somebody looking."""

    def code(self):
        return (KIT / "stop_self.sh").read_text(encoding="utf-8")

    def body(self):
        return self.code().split("main () {", 1)[1].split("\n}", 1)[0]

    def test_it_deallocates_and_does_nothing_else(self):
        """Deallocated is the word that matters: a machine shut down from inside is still
        allocated and still billed. And the role it holds allows nothing else -- asked to
        restart itself, a driver is refused with 403."""
        code = self.code()
        assert "/deallocate?api-version=" in code
        for verb in ("/delete", "/start?", "/restart?", "/powerOff"):
            assert verb not in code, "it has no business asking for %s" % verb

    def test_the_broker_goes_before_the_machine_running_this(self):
        assert "for vm in $others $me; do" in self.body(), "itself last: it is its own last act"

    def test_it_only_ever_touches_its_own_resource_group(self):
        """Each pair is its own resource group, so "every machine in my group" is exactly this
        pair. The identity is scoped there and refused elsewhere; this is the second lock."""
        code = self.code()
        assert "resourceGroupName" in code, "the group comes from the machine's own metadata"
        assert "$IMDS/instance?api-version=" in code
        assert "MOST_IN_A_PAIR=4" in code
        assert "does not look like this pair; stopping nothing" in self.body()

    def test_it_needs_the_identity_and_says_so_when_there_is_none(self):
        body = self.body()
        assert "nothing can be stopped from inside" in body
        assert body.index("token") < body.index("deallocate")


def test_the_pair_stops_itself_only_when_the_list_is_exhausted():
    """The one place it is safe: the list is empty, which is true only after the jobs put back
    for a second go have run too. A pair asked to stop keeps its list and is handled above."""
    code = QUEUE.read_text(encoding="utf-8")
    loop = code.split("run_loop () {", 1)[1]
    ended = loop.split('if [ -z "$line" ]; then', 1)[1].split("return 0", 1)[0]
    assert "stop_when_done" in ended and "stop_self.sh" in ended
    said = "a pair asked to stop is answered before a pair that has simply finished"
    assert loop.index("$STOPFILE") < loop.index("stop_when_done"), said


def test_stopping_itself_is_an_instruction_about_one_list_and_not_a_standing_rule():
    """Left in place the marker made the pair unreachable: starting it to collect its runs
    let the loop find an empty list again and turn it off inside a minute. The Arm pair did
    exactly that, twice, before anything could be copied off it."""
    code = QUEUE.read_text(encoding="utf-8")
    loop = code.split("run_loop () {", 1)[1]
    armed = loop.split('if [ -e "$DIR/stop_when_done" ]; then', 1)[1].split("\n      fi", 1)[0]
    assert 'rm -f "$DIR/stop_when_done"' in armed, "the marker is taken when it fires"
    said = "taken before the pair is asked to go, not after"
    assert armed.index("rm -f") < armed.index("stop_self.sh"), said


def test_stopping_itself_is_asked_for_and_can_be_taken_back():
    code = QUEUE.read_text(encoding="utf-8")
    assert "  arm-stop)" in code and "  disarm-stop)" in code
    assert "arm-stop|disarm-stop" in code, "and both are in the usage line"


def test_the_helper_blocks_runs_record_every_event_and_name_their_threads():
    """D28-1: A9 reads each negative reading against the waits of the one thread that stamped its
    acknowledgement. So for A9's traced runs, and only those, the campaign records every python3
    thread's scheduling events rather than a histogram, probes that recording against live traffic
    before the first run, and asks both clients to name the threads that stamp."""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert 'EVENTS_BT="runs/azure/waits.bt"' in code
    events = code.split("cat > \"$EVENTS_BT\" <<'BT'\n", 1)[1].split("\nBT\n", 1)[0]
    for kind in "PSRW":
        assert 'printf("%s %%d %%llu\\n"' % kind in events, kind
    assert 'if (args->prev_state == 0) { printf("P ' in events, "preempted while it could run"
    assert '"TRACE_EVENTS": "1" if p.get("trace_events") else ""' in code
    assert "event probe ok" in code and 'sudo timeout 8 bpftrace "$EVENTS_BT"' in code
    run = code.split("run_one () {", 1)[1]
    assert 'sudo bpftrace "$EVENTS_BT" > "$RUN_DIR/waits.txt"' in run
    assert 'sudo bpftrace "$TRACE_BT" > "$RUN_DIR/runqlat.txt"' in run, "A1 and A3 as they were"
    assert 'record_args="--thread-record"' in run
    # Freeze 40 (14 Oct 2026) appends each client's socket file, empty unless a row asks; freeze
    # 43 (22 Oct 2026) the clients' collector and schedstat flags after them, empty unless a row
    # asks (test_freeze_43s_client_flags_reach_the_clients_that_take_them).
    assert '-PRODUCER_EXTRA "$KAFKA_PRODUCER_EXTRA $record_args $so_prod$prod_flags"' in run
    assert '-CONSUMER_EXTRA "$record_args $read_args $so_cons$cons_flags"' in run
    # Freeze 41 (15 Oct 2026): and the Redis producer's send workers after them, where a row names
    # a count (test_freeze_41s_one_worker_setups_reach_the_redis_producer_and_no_other).
    assert ('-PRODUCER_EXTRA "$record_args $so_prod${SEND_WORKERS:+ --send-workers $SEND_WORKERS}'
            '$prod_flags"') in run
    assert ('-CONSUMER_EXTRA "$REDIS_CONSUMER_EXTRA${ACK_BATCH:+ --ack-batch $ACK_BATCH}'
            ' $record_args $so_cons$cons_flags"') in run
    assert run.index('local record_args=""') < run.index('record_args="--thread-record"')


def test_m0_replays_its_own_plan_and_records_what_its_hypotheses_are_judged_by():
    """S0-2 and D29-1. M0 replays the football match in bursts, is held to that plan's own count
    and rate, sets the Redis consumer's acknowledgement batch from its setup, and in its recorded
    half captures the packets at both ends and the receive loop's cycle, each capture stopped by
    its own process id. Every other block runs exactly as it did."""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert 'find data/processed/replay_plans -name replay_plan.csv | sort | head -n 1' in code
    assert 'FOOT_SPEEDUP=$(assert_plan_rate "$FOOT_PLAN" 10)' in code, "as the pilot did"
    assert "python3 scripts/replay_window.py" in code
    assert '"PLAN_KIND": p.get("plan") or ""' in code and '"CAPTURE": "1" if p.get("capture")' in code
    run = code.split("run_one () {", 1)[1]
    assert 'local run_plan="$SYN_PLAN" run_speedup="$SPEEDUP" run_maxt="$DURATION"' in run
    assert 'plan_args=(--planned "$FOOT_PLANNED")' in run
    assert run.count('"$RUN_ID" "$run_plan"') == 4, "every backend replays the run's own plan"
    assert '--rate "$run_rate"' in run and '"${plan_args[@]}"' in run
    assert 'read_args="--read-trace"' in run
    assert 'sudo ip netns exec sblrecv tcpdump -i any -s 200 -w "$RUN_DIR/receiver.pcap"' in run
    assert "tcpdump -i eth0 -s 200 -w /tmp/sbl_m0.pcap host $RECEIVER_IP" in run
    # The receiver's capture is stopped by its own command line. Signalled through the sudo that
    # started it, it was never stopped at all: sudo does not relay a signal sent from its own
    # process group, and M0's first recorded run waited six hours on it (26 September). This
    # test used to assert that very line.
    stop = run.split('if [ -n "$receiver_capture" ]; then', 1)[1].split("\n  fi", 1)[0]
    assert 'sudo kill -INT "$receiver_capture"' not in stop
    assert 'sudo pkill -INT -f "[t]cpdump -i any -s 200 -w $RUN_DIR/receiver.pcap"' in stop
    assert 'sudo pkill -KILL -f "[t]cpdump -i any -s 200 -w $RUN_DIR/receiver.pcap"' in stop
    assert 'for _ in $(seq 1 20); do ps -p "$receiver_capture" > /dev/null || break' in stop, \
        "the wait is bounded"
    assert stop.index("pkill -KILL") > stop.index("pkill -INT") and \
        stop.index('wait "$receiver_capture"') > stop.index("pkill -KILL")
    assert '> "$RUN_DIR/broker.pcap"' in run
    assert run.index("tcpdump -i eth0 -s 200") > run.index("tcpdump -i eth0 -nn"), \
        "M0's capture starts after the delay's own capture has been read"


def _row_reader_says(params, key="r001-R1-redis-l75-ord-a1"):
    """What campaign.sh's own row reader sets for a queue row: its Python, run as the runner runs
    it, on a row with the parameters every block gives and `params` over them."""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    program = code.split("eval \"$(python3 - \"$ROW\" <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    row = {"key": key, "params": dict({"backend": "redis", "load_pct": 75, "delay_ms": 0},
                                      **params)}
    said = subprocess.run([sys.executable, "-", json.dumps(row)], input=program, text=True,
                          capture_output=True, check=True).stdout
    return dict(shlex.split(line)[0].split("=", 1) for line in said.splitlines())


def test_r1s_switches_reach_the_runner_and_raise_nothing_else():
    """R1 (3 Oct 2026): a row's consumer_priority and recv_capture become CONSUMER_PRIORITY and
    RECV_CAPTURE. Go-first for the consumer alone must not raise the producer as well, or what it
    removes from D is no longer the receiving thread's own wait; and a row of any other block
    sets neither, so every earlier block runs as it did."""
    r1 = _row_reader_says({"consumer_priority": True, "recv_capture": True,
                           "trace_half": True, "trace_events": True})
    assert (r1["CONSUMER_PRIORITY"], r1["RECV_CAPTURE"], r1["PRIORITY"]) == ("1", "1", "")
    a7 = _row_reader_says({"priority": True})
    assert (a7["CONSUMER_PRIORITY"], a7["RECV_CAPTURE"], a7["PRIORITY"]) == ("", "", "1")
    assert r1["SEND_CAPTURE"] == a7["SEND_CAPTURE"] == "", "neither captures the sender"
    assert r1["HW_CAPTURE"] == a7["HW_CAPTURE"] == "", "and neither the card's own stamps"
    assert r1["SO_STAMPS"] == a7["SO_STAMPS"] == "", "nor reads the sockets' own timestamps"


def test_freeze_39s_switch_reaches_the_runner():
    """Freeze 39 (13 Oct 2026): a row's send_capture becomes SEND_CAPTURE, beside R1's receiver
    capture, and its go-first raises both processes that read the clock, as A7's did."""
    f1 = _row_reader_says({"send_capture": True, "recv_capture": True, "priority": True,
                           "load_pct": 0, "hw_capture": True})
    assert (f1["SEND_CAPTURE"], f1["RECV_CAPTURE"], f1["PRIORITY"], f1["LOAD"],
            f1["HW_CAPTURE"]) == ("1", "1", "1", "0", "1")


def test_freeze_40s_switch_reaches_the_runner():
    """Freeze 40 (14 Oct 2026): a row's so_timestamps names where the clients' sockets take the
    transmit timestamp, and becomes SO_STAMPS; a row without it leaves SO_STAMPS empty."""
    f2 = _row_reader_says({"so_timestamps": "sched", "send_capture": True, "recv_capture": True})
    assert (f2["SO_STAMPS"], f2["SEND_CAPTURE"], f2["RECV_CAPTURE"]) == ("sched", "1", "1")
    assert _row_reader_says({})["SO_STAMPS"] == ""


def _socket_files(tmp_path, so_stamps, so_journal=""):
    """What freeze 40's lines hand each client, run as the runner runs them, with an unset
    variable an error; freeze 41's journal among them, where a row asks for one."""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    first = "  # Freeze 40 (14 Oct 2026): the clients read"
    block = first + code.split(first, 1)[1].split("  began=$(date -u +%s)", 1)[0]
    script = "\n".join(["set -uo pipefail", "lines () {", block,
                        '  echo "producer=$so_prod"', '  echo "consumer=$so_cons"', "}",
                        "lines", ""])
    said = bash(["-c", script], extra_env={"RUN_DIR": "runs/law_f2_r001", "SO_STAMPS": so_stamps,
                                           "SO_JOURNAL": so_journal},
                capture_output=True, text=True, check=True).stdout
    return dict(line.split("=", 1) for line in said.splitlines())


@needs_bash
def test_freeze_40s_clients_each_write_their_own_socket_file(tmp_path):
    """Asked for, the producer and the consumer each write the timestamps their sockets read
    beside the run, the transmit timestamp taken where the row says; not asked for, neither is
    handed anything, so every earlier block's clients start exactly as before."""
    asked = _socket_files(tmp_path, "sched")
    assert asked == {
        "producer": "--so-timestamps runs/law_f2_r001/producer_so.csv --so-transmit sched",
        "consumer": "--so-timestamps runs/law_f2_r001/consumer_so.csv --so-transmit sched"}
    assert _socket_files(tmp_path, "") == {"producer": "", "consumer": ""}


def _run_script(path, script, env, **kw):
    """`bash PATH`, the script written to PATH first, with `env` over the shell's environment.

    Git's bash on Windows drops, without a word, whatever follows the first 8,200 or so characters
    of a script handed to it with -c: a longer block runs cut short, and fails, or passes, on the
    part that is left. On 22 October 2026 freeze 43's comments took the R1 lines past it, so a
    block that long is run from a file of its own."""
    return bash([_write(path, script).as_posix()], extra_env=env, **kw)


def _r1_runner(tmp_path, name, **switches):
    """A run's R1 lines, from the wraps it hands the trial runner to the stop of its capture, in
    bash, with every command that needs a machine stood in for by one that writes down how it
    was called. (The wraps handed over, the calls.)"""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    run = code.split("run_one () {", 1)[1]
    first = '  [ -n "$PRIORITY" ] && wrap_sched='
    start = first + run.split(first, 1)[1].split("  chronyc -c tracking", 1)[0]
    head = '  if [ -n "$recv_full" ]; then'
    stop = head + run.split(head, 1)[1].split("\n  fi\n", 1)[0] + "\n  fi\n"
    for head in ('  if [ -n "$hw_full" ]; then', '  if [ -n "$send_full" ]; then',
                 '  if [ -n "$broker_full" ]; then'):
        stop += head + run.split(head, 1)[1].split("\n  fi\n", 1)[0] + "\n  fi\n"
    run_dir, calls = tmp_path / name, tmp_path / (name + "_calls.txt")
    run_dir.mkdir()
    # Freeze 43 (22 Oct 2026): the card's device is the SLAVE carrying eth0's own address, which
    # the runner reads from ETH0_ADDRESS; here eth0's address in LINKS, unless a test names another.
    address = _write(tmp_path / (name + "_eth0_address"), "60:45:bd:e9:60:ba\n")
    script = "\n".join([
        # ethtool, run through sudo, answers with the card's clock where FAKE_PHC names one, and
        # ip with the links FAKE_LINK lists. What the broker is asked over ssh is written down too.
        'sudo () { echo "sudo $*" >> "$CALLS";'
        ' [ "$1" != ethtool ] || echo "PTP Hardware Clock: ${FAKE_PHC:-none}"; }',
        'remote_broker () { echo "remote_broker $*" >> "$CALLS"; }',
        'ip () { printf "%s\\n" "${FAKE_LINK:-}"; }', "sleep () { :; }", "ps () { return 1; }",
        "r1 () {", '  local wrap_sched=""', start,
        '  echo "consumer=$consumer_wrap"', '  echo "producer=$wrap_sched"', stop, "}", "r1", ""])
    env = {"CALLS": calls.as_posix(), "RUN_DIR": run_dir.as_posix(), "BROKER_PRIV": "10.9.9.9",
           "DRIVER_PRIV": "10.8.8.8", "RECEIVER_IP": "10.7.7.7", "ME": "tester", "PRIORITY": "",
           "CONSUMER_PRIORITY": "", "RECV_CAPTURE": "", "SEND_CAPTURE": "", "HW_CAPTURE": "",
           "SEND_CAPTURE_BOTH": "", "CAPTURE_BUFFER": "", "BROKER_CAPTURE": "",
           "BACKEND": "kafka", "KAFKA_BOOTSTRAP": "10.9.9.9:19092", "REDIS_PORT": "6379",
           "ETH0_ADDRESS": address.as_posix()}
    env.update(switches)
    said = _run_script(tmp_path / (name + "_r1.sh"), script, env, capture_output=True, text=True,
                       check=True).stdout
    handed = dict(line.split("=", 1) for line in said.splitlines())
    return handed, (calls.read_text(encoding="utf-8").splitlines() if calls.exists() else [])


@needs_bash
def test_r1_raises_the_consumer_alone_and_only_when_asked(tmp_path):
    """R1's first method reads what go-first for the consumer removes from D, so the consumer and
    nothing else runs under SCHED_FIFO 80, and the producer's wrap stays empty. Without the
    switch the consumer starts exactly as before, and A7's go-first for both is left as it was."""
    plain, calls = _r1_runner(tmp_path, "plain")
    assert plain == {"consumer": "sudo ip netns exec sblrecv sudo -u tester", "producer": ""}
    assert calls == [], "no capture is started, and none is stopped"
    raised, _ = _r1_runner(tmp_path, "raised", CONSUMER_PRIORITY="1")
    assert raised == {"consumer": "sudo chrt -f 80 sudo ip netns exec sblrecv sudo -u tester",
                      "producer": ""}
    both, _ = _r1_runner(tmp_path, "both", PRIORITY="1")
    assert both == {"consumer": "sudo ip netns exec sblrecv sudo -u tester",
                    "producer": "sudo chrt -f 80"}


@needs_bash
def test_r1s_capture_is_full_length_in_nanoseconds_and_stopped_by_its_own_command_line(tmp_path):
    """R1's third method times each receipt from the kernel's own timestamp, so the receiver's
    packets are captured inside its namespace at full length, stamped to the nanosecond. The
    capture is stopped by the command line that started it: a signal sent through the sudo that
    started M0's capture never reached it, and held a run six hours (26 September)."""
    _, calls = _r1_runner(tmp_path, "captured", RECV_CAPTURE="1")
    started = [c for c in calls if "pkill" not in c]
    assert started == ["sudo ip netns exec sblrecv tcpdump -i any -s 0 --time-stamp-precision="
                       "nano -w %s/receiver_full.pcap host 10.9.9.9"
                       % (tmp_path / "captured").as_posix()]
    stops = [c.split(" -f ", 1) for c in calls if "pkill" in c]
    assert [how for how, _ in stops] == ["sudo pkill -INT", "sudo pkill -KILL"]
    for how, pattern in stops:
        assert re.search(pattern, started[0]), "pkill -f finds the capture by its command line"
        assert not re.search(pattern, "%s -f %s" % (how, pattern)), \
            "and not the sudo that runs pkill, whose command line holds the pattern itself"


@needs_bash
def test_freeze_39s_capture_is_the_senders_packets_and_stopped_by_its_own_command_line(tmp_path):
    """Freeze 39 times each message's departure from the kernel's own timestamp, so the
    producer's packets are captured in the driver's own namespace on eth0, at full length and to
    the nanosecond, from the driver to the broker and not the commands sent over ssh. The capture
    is stopped as R1's is, by its own command line."""
    _, calls = _r1_runner(tmp_path, "sent", SEND_CAPTURE="1")
    started = [c for c in calls if "pkill" not in c]
    assert started == ["sudo tcpdump -i eth0 -s 0 --time-stamp-precision=nano -w "
                       "%s/sender_full.pcap src host 10.8.8.8 and dst host 10.9.9.9 and not "
                       "port 22" % (tmp_path / "sent").as_posix()]
    stops = [c.split(" -f ", 1) for c in calls if "pkill" in c]
    assert [how for how, _ in stops] == ["sudo pkill -INT", "sudo pkill -KILL"]
    for how, pattern in stops:
        assert re.search(pattern, started[0]), "pkill -f finds the capture by its command line"
        assert not re.search(pattern, "%s -f %s" % (how, pattern))
    both, calls = _r1_runner(tmp_path, "both", SEND_CAPTURE="1", RECV_CAPTURE="1")
    assert len([c for c in calls if "pkill" not in c]) == 2, "each capture starts once"


#: The driver's links as `ip -br link` showed them on 13 October: the accelerated-networking device
#: is eth0's SLAVE and carries the same address.
LINKS = ("eth0             UP             60:45:bd:e9:60:ba <BROADCAST,MULTICAST,UP,LOWER_UP> \n"
         "enP58460s1       UP             60:45:bd:e9:60:ba <BROADCAST,MULTICAST,SLAVE,UP,LOWER_UP> ")


@needs_bash
def test_freeze_39s_card_capture_is_on_the_device_that_carries_the_packets_with_its_clock(tmp_path):
    """Freeze 39 also captures the receiver's packets as the network card stamped them, described
    and not judged: on the accelerated-networking device, the link `ip -br link` shows as a SLAVE,
    with the card's clock, which ethtool names, sampled beside it. Both are stopped by their own
    command lines. A card without a clock, or no such device, captures nothing and says so. The
    first pilot read the wrong column, the address, and captured nothing (13 October)."""
    _, calls = _r1_runner(tmp_path, "card", HW_CAPTURE="1", FAKE_LINK=LINKS, FAKE_PHC="1")
    run = (tmp_path / "card").as_posix()
    started = [c for c in calls if "pkill" not in c]
    assert started == [
        "sudo ethtool -T enP58460s1",
        "sudo tcpdump -i enP58460s1 -j adapter_unsynced -s 0 --time-stamp-precision=nano -w "
        "%s/receiver_hw.pcap src host 10.9.9.9 and dst host 10.7.7.7" % run,
        "sudo python3 scripts/phc_offset.py --device /dev/ptp1 --interval 0.5 --out "
        "%s/phc_offset.csv" % run]
    assert (tmp_path / "card" / "hw_device.txt").read_text().split() == ["enP58460s1", "/dev/ptp1"]
    stops = [c.split(" -f ", 1) for c in calls if "pkill" in c]
    assert [how for how, _ in stops] == ["sudo pkill -INT", "sudo pkill -INT", "sudo pkill -KILL"]
    for (how, pattern), target in zip(stops, (started[1], started[2], started[1])):
        assert re.search(pattern, target), "pkill -f finds each by its command line"
        assert not re.search(pattern, "%s -f %s" % (how, pattern))
    for name, link, clock in (("clockless", LINKS, ""), ("plain", LINKS.split("\n")[0], "1")):
        _, calls = _r1_runner(tmp_path, name, HW_CAPTURE="1", FAKE_LINK=link, FAKE_PHC=clock)
        assert not [c for c in calls if "tcpdump" in c or "pkill" in c], name
    assert (tmp_path / "clockless" / "hw_device.txt").read_text().split() == ["enP58460s1", "none"]
    assert (tmp_path / "plain" / "hw_device.txt").read_text().split() == ["none", "none"]


def _load_lines(tmp_path, load, **setting):
    """A run's load lines, from starting stress-ng to the duty's correction, in bash, with stress-ng,
    the sampler and the correction's Python stood in for by commands that write down how they
    were called. (The calls.) They run as the runner runs them: with an unset variable an error,
    and stress_pid declared without a value, as the runner declares it."""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    first = "  # Freeze 39 (13 Oct 2026): a load of 0 is idle"
    block = first + code.split(first, 1)[1].split("  # M0 replays the football plan", 1)[0]
    calls = tmp_path / ("load_%s_calls.txt" % load)
    script = "\n".join([
        "set -uo pipefail",
        'stress-ng () { echo "stress-ng $*" >> "$CALLS"; }',
        'python3 () { echo "python3 $1" >> "$CALLS"; }', "sleep () { :; }",
        "kill () { :; }", "wait () { :; }", "pkill () { :; }", _function("load_start"),
        "lines () {", "  local stress_pid sampler_pid", block, "}", "lines",
        "builtin wait", ""])
    env = {"CALLS": calls.as_posix(), "RUN_DIR": tmp_path.as_posix(), "LOAD": str(load),
           "want_cpus": "8"}
    env.update(setting)
    bash(["-c", script], extra_env=env, capture_output=True, text=True, check=True)
    return calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []


@needs_bash
def test_a_load_of_zero_is_idle_and_any_other_is_stress_ng(tmp_path):
    """Freeze 39's idle setups start no load at all: stress-ng told a duty of zero would still be
    running, and the correction would lift its duty to one percent. The sampler runs in both, so
    the integrity rule still measures the load. The first pilot's first idle run stopped the
    runner (13 October): nothing set stress_pid, and the runner treats an unset variable as an
    error."""
    idle = _load_lines(tmp_path, 0)
    assert not [c for c in idle if c.startswith("stress-ng")]
    assert "python3 scripts/util_sampler.py" in idle
    busy = _load_lines(tmp_path, 88)
    assert [c for c in busy if c.startswith("stress-ng")] == [
        "stress-ng --cpu 8 --cpu-load 88 --timeout 3600s"]


def test_no_stop_run_through_sudo_finds_its_own_sudo():
    """pkill leaves itself out but not the sudo that runs it, and that sudo's command line holds
    the pattern. Written plainly, the forced stop of R1's capture killed its own sudo in every
    one of R1's 53 runs, and each run's log said so (3 October)."""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    stops = re.findall(r'(sudo pkill -[A-Z]+) -f "([^"]+)"', code)
    assert len(stops) == 9, ("R1's capture, freeze 39's sender capture, its card capture with the "
                             "card's clock sampler, and M0's, each asked politely, the captures "
                             "then forced")
    for how, pattern in stops:
        # As the shell hands each pattern to pkill, with its variables expanded.
        for name, value in (("$RUN_DIR", "runs/law_r1_r001-R1-redis-l75-rtc-a1"),
                            ("$hw_dev", "enP58460s1"), ("$hw_clock", "/dev/ptp1")):
            pattern = pattern.replace(name, value)
        started = ("sudo ip netns exec sblrecv " + pattern.replace("[t]", "t").replace("[p]", "p")
                   + " host 10.1.1.21")
        assert re.search(pattern, started), pattern
        assert not re.search(pattern, "%s -f %s" % (how, pattern)), pattern


class TestFreeze37sTwoTools:
    """Quiver and the Pravega benchmark (D40-1, D40-2): each built from the version the reading
    read, with what each build fetches checked against its publisher's checksum, each run as its
    own documentation runs it, and the rest of the wrap on the process that subtracts."""

    def tools(self):
        return (KIT / "tools.sh").read_text(encoding="utf-8")

    def case(self, tool):
        runner = (KIT / "tools_run.sh").read_text(encoding="utf-8")
        return runner.split("\n  %s)" % tool, 1)[1].split(";;", 1)[0]

    def test_what_their_builds_fetch_is_checked_against_a_published_checksum(self):
        text = self.tools()
        for name, bits in (("PROTON_SHA512", 128), ("GRADLE4_SHA256", 64), ("PRAVEGA_SHA512", 128)):
            assert re.search(r'%s="[0-9a-f]{%d}"' % (name, bits), text), name
        assert 'gradle4.zip 256 "$GRADLE4_SHA256"' in text
        assert 'proton.tgz "$PROTON_SHA512"' in text and 'pravega.tgz "$PRAVEGA_SHA512"' in text

    def test_each_is_built_at_the_commit_its_pin_names(self):
        text = self.tools()
        table = dict(line.split("|")[0::2] for line in
                     text.split("PINNED='", 1)[1].split("'", 1)[0].strip().splitlines())
        install = text.split("\ninstall_for () {", 1)[1].split("\n}\n", 1)[0]
        assert "get_quiver %s" % table["quiver"] in install
        assert "get_pravega_benchmark %s" % table["pravega-benchmark"] in install

    def test_both_take_the_offset_on_the_process_that_subtracts(self):
        """Quiver's receiver under libfaketime; the Pravega benchmark, one JVM that libfaketime
        slows, by the machine's own clock, as the Go tools are (D40-2)."""
        text = self.tools()
        fakeable = text.split('FAKEABLE="', 1)[1].split('"', 1)[0].split()
        stepped = text.split('CLOCK_T2="', 1)[1].split('"', 1)[0].split()
        assert "quiver" in fakeable and "pravega-benchmark" not in fakeable
        assert stepped == ["pravega-benchmark"]
        assert 'case " $GO_TOOLS $CLOCK_T2 " in' in text.split("\nt2 () {", 1)[1]
        quiver = self.case("quiver")
        assert '$NS $REST quiver-arrow receive "$q_url"' in quiver, "the receiver subtracts"
        assert '$NS quiver-arrow send "$q_url" "${q_args[@]}" --rate "$RATE"' in quiver
        assert "--duration 0" in quiver and "--timeout 120" in quiver
        assert '$WRAP env JAVA_HOME="$JAVA8"' in self.case("pravega-benchmark"), "one process"

    def test_quivers_leftovers_are_found_by_its_queue_and_not_by_the_pkill_that_finds_them(self):
        quiver = self.case("quiver")
        pattern = re.search(r'OWN_PATTERN="([^"]+)"', quiver).group(1).replace("$q_id", "17602")
        assert re.search(pattern, "java -classpath q.jar net.ssorj.quiver.QuiverArrowJms path=sbl-quiver-17602")
        assert re.search(pattern, "python3 /usr/local/bin/quiver-arrow receive amqp://h:61616/sbl-quiver-17602")
        assert not re.search(pattern, "sudo pkill -f -- " + pattern)

    def test_pravegas_server_is_started_as_its_documentation_starts_it_with_its_address(self):
        server = self.tools().split("\nserver36 () {", 1)[1].split("\n}\n", 1)[0]
        assert "bin/pravega-standalone" in server
        assert "-Dpravegaservice.service.published.host.nameOrIp=$BROKER_PRIV" in server
        assert "-Xmx2g" in server and "Pravega Sandbox is running locally now" in server
        assert "pkill -f -- 'io.pravega.local.LocalPravegaEmulator'" in server


class TestFreeze38sOneTool:
    """Google's Pub/Sub load test (D41-1, D41-2): built from the commit the reading read as its
    run.py builds it, against the project made for it with a key kept off the repository, its driver
    and both clients in one namespace, and the rest of the wrap on the subscriber alone."""

    def tools(self):
        return (KIT / "tools.sh").read_text(encoding="utf-8")

    def case(self):
        """Up to the next case label: the java it writes holds a `;;` of its own."""
        runner = (KIT / "tools_run.sh").read_text(encoding="utf-8")
        return runner.split("\n  pubsub-loadtest)", 1)[1].split("\n  *)\n", 1)[0]

    def test_it_is_built_at_the_commit_its_pin_names_as_its_run_py_builds_it(self):
        text = self.tools()
        table = dict(line.split("|")[0::2] for line in
                     text.split("PINNED='", 1)[1].split("'", 1)[0].strip().splitlines())
        assert table["pubsub-loadtest"] == "cd7d07bbfa4b81afc148f31a091f9b0d958dbe01"
        install = text.split("\ninstall_for () {", 1)[1].split("\n}\n", 1)[0]
        assert "get_pubsub_loadtest %s" % table["pubsub-loadtest"] in install
        build = text.split("\nget_pubsub_loadtest () {", 1)[1].split("\n}\n", 1)[0]
        assert 'JAVA_HOME="$JAVA8" mvn -B -q package' in build
        assert "cp target/driver.jar target/classes/gce/" in build

    def test_its_key_is_named_and_never_held_in_the_repository(self):
        text, runner = self.tools(), (KIT / "tools_run.sh").read_text(encoding="utf-8")
        for script in (text, runner):
            assert 'PUBSUB_KEY="${SBL_PUBSUB_KEY:-$HOME/.gcp_pubsub_key.json}"' in script
            assert "private_key" not in script and "BEGIN PRIVATE" not in script
        server = text.split("\nserver_answers () {", 1)[1].split("\n}\n", 1)[0]
        assert '[ -s "$PUBSUB_KEY" ]' in server and "pubsub.googleapis.com/443" in server

    def test_the_rest_of_the_wrap_goes_to_the_subscriber_alone(self):
        """The driver reaches its clients on loopback, so the namespace is all three processes';
        the moved clock or go-first belongs to the subscriber, which subtracts (D41-2)."""
        case = self.case()
        fakeable = self.tools().split('FAKEABLE="', 1)[1].split('"', 1)[0].split()
        assert "pubsub-loadtest" in fakeable
        assert 'timeout -k 20 "$PUBSUB_LIMIT" env PATH="$p_bin:' in case, "on the machine itself"
        assert "$NS" not in case.split("for p_try", 1)[1], "the namespace has no name resolver"
        assert "com.google.pubsub.clients.gcloud.CPSSubscriberTask" in case
        assert 'exec ${p_sudo} ${REST} \\"$p_java\\"' in case
        assert 'p_sudo="sudo env GOOGLE_APPLICATION_CREDENTIALS=$PUBSUB_KEY HOME=$HOME"' in case
        #: The pilots: under libfaketime Java 8's sleep never returns, and on Java 11 and 17 it
        #: hangs only with the monotonic clock left alone, so it runs on 11 with neither.
        assert 'p_java="$JAVA11/bin/java"' in case and "--exclude-monotonic" not in case.split(
            "p_java=", 1)[1]
        assert 'PATH="$p_bin:$JAVA11/bin:' in case and "$JAVA8" not in case
        assert 'exec \\"$p_java\\" \\"\\$@\\"' in case
        assert "--local" in case and "--test_parameters latency" in case
        assert 'rm -f "$OUT/asked_to_send.txt"' in case, "its rate is its preset's"

    def test_its_driver_is_stopped_inside_the_runner_s_own_limit(self):
        """So that the runner still prints the status and the CSV T2-l is judged by, after up to
        three attempts a minute apart, the two that never started set aside."""
        runner = (KIT / "tools_run.sh").read_text(encoding="utf-8")
        assert 'LIMIT=$(( 3 * PUBSUB_LIMIT + 3 * 60 ))' in runner
        case = self.case()
        assert "for p_try in 1 2 3; do" in case and 'grep -q "Will start burn-in time"' in case
        assert 'mv "$here/driver.txt" "$here/attempt_${p_try}_never_started.txt"' in case
        assert 'mv "$here/driver.txt" "$here/attempt_${p_try}_client_failed.txt"' in case
        assert '! grep -q "health checks, something went wrong"' in case
        for head in ("attempts set aside", "driver's console", "driver's exit status",
                     "test seconds", "output.csv"):
            assert 'echo "# pubsub %s"' % head in case

    def test_its_leftovers_are_found_and_not_the_pkill_that_finds_them(self):
        pattern = re.search(r'OWN_PATTERN="([^"]+)"', self.case()).group(1)
        assert re.search(pattern, "java -Xmx5000M -cp target/classes/gce/driver.jar "
                                  "com.google.pubsub.clients.gcloud.CPSSubscriberTask --port=4")
        assert re.search(pattern, "/usr/lib/jvm/java-8-openjdk-amd64/bin/java -jar "
                                  "target/driver.jar --project sbl-pubsub-load-test")
        assert not re.search(pattern, "sudo pkill -f -- " + pattern)

    def test_t1_is_its_zero_step_t4_runs_a_second_ahead_and_s1_steps_50_ms(self):
        text = self.tools()
        t1 = text.split("\nt1 () {", 1)[1].split("\n}\n", 1)[0]
        assert "pkb|pubsub-loadtest)" in t1 and "Google's Cloud Pub/Sub" in t1
        t4 = text.split("\nt4 () {", 1)[1].split("\n}\n", 1)[0]
        assert 'wrap="$NETNS faketime -f +1.000000000"' in t4
        assert 'faketime_reading "+1.000000000"' in t4
        assert 'S1_STEP_MS_PUBSUB="${SBL_S1_STEP_MS_PUBSUB:-50}"' in text
        s1 = text.split("\ns1 () {", 1)[1].split("\n}\n", 1)[0]
        assert 'if [ "$tool" = pubsub-loadtest ]; then step="$S1_STEP_MS_PUBSUB"; fi' in s1

    def test_its_reference_is_the_top_of_the_bucket_above_its_printed_median(self):
        """Its controller prints each bound one bucket below the values in it (D41-3)."""
        ref = self.tools().split("\nreference_for () {", 1)[1].split("\n}\n", 1)[0]
        mine = ref.split("    pubsub-loadtest)", 1)[1].split("return 0 ;;", 1)[0]
        assert '"trips_ms": [1.5 * printed[1]]' in mine


# --- Freeze 41 (15 Oct 2026): the acknowledgment's own arrival, and where the kernel-timed latency
# holds (docs/results/order_scope/DESIGN.md). What its five blocks ask of the kit: the clients'
# journal (K, R, I, L), both directions of the sender (K), one send worker (K), the scheduler's
# RUN_TO_PARITY feature (R), campaigns at other rates (L) and a boot with idle=poll (I).

#: The arguments of the kind an Azure image boots its stock kernel with, after the image itself.
STOCK_ARGS = "root=PARTUUID=0b1c2d3e ro console=tty1 console=ttyS0 earlyprintk=ttyS0 panic=-1"


def _write(path, text):
    """A file as Linux writes one, with no carriage return on any platform; returns its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def test_freeze_41s_switches_reach_the_runner_and_a_row_without_them_sets_none():
    """A row's six new settings become the runner's six variables. A row of any earlier block
    names none of them and leaves all six empty, so its run is launched exactly as before."""
    k = _row_reader_says({"so_timestamps": "sched", "so_journal": True, "send_capture": True,
                          "send_capture_both": True, "send_workers": 1, "idle_poll": False})
    assert (k["SO_JOURNAL"], k["SEND_CAPTURE_BOTH"], k["SEND_WORKERS"], k["IDLE_POLL"]) == (
        "1", "1", "1", "0")
    r = _row_reader_says({"sched_features": "NO_RUN_TO_PARITY", "idle_poll": True})
    assert (r["SCHED_FEATURES"], r["IDLE_POLL"]) == ("NO_RUN_TO_PARITY", "1")
    ladder = _row_reader_says({"so_journal": "consumer", "capture_buffer": True})
    assert (ladder["SO_JOURNAL"], ladder["CAPTURE_BUFFER"]) == ("consumer", "1")
    assert _row_reader_says({"send_workers": 0})["SEND_WORKERS"] == "0", \
        "a count of none is handed on for the runner to refuse, not dropped for the default"
    earlier = _row_reader_says({"so_timestamps": "sched", "send_capture": True})
    for name in ("SO_JOURNAL", "SEND_CAPTURE_BOTH", "CAPTURE_BUFFER", "SEND_WORKERS",
                 "SCHED_FEATURES", "IDLE_POLL"):
        assert earlier[name] == "", name


@needs_bash
def test_freeze_41s_journal_is_handed_to_the_clients_that_keep_one(tmp_path):
    """Blocks K, R and I journal both clients' broker connections and block L the consumer's
    alone, each under a path stem beside the run, after the socket timestamps that write it. A row
    that asks for no journal hands each client exactly what freeze 40 did."""
    so = "--so-timestamps runs/law_f2_r001/%s_so.csv --so-transmit sched"
    journal = " --so-journal runs/law_f2_r001/%s_journal"
    assert _socket_files(tmp_path, "sched", "1") == {
        "producer": so % "producer" + journal % "producer",
        "consumer": so % "consumer" + journal % "consumer"}
    assert _socket_files(tmp_path, "sched", "consumer") == {
        "producer": so % "producer", "consumer": so % "consumer" + journal % "consumer"}
    assert _socket_files(tmp_path, "sched") == {"producer": so % "producer",
                                                "consumer": so % "consumer"}


def _setup_says(tmp_path, cmdline=None, **setting):
    """The REASON freeze 41's checks of a setup give, from their lines in run_one, run as the
    runner runs them, with an unset variable an error; empty when the setup can run as written.
    `cmdline` is this boot's command line, in a file of its own, or None for no file at all."""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    run = code.split("run_one () {", 1)[1]
    first = "  # Freeze 41 (15 Oct 2026): a setup that asks"
    block = first + run.split(first, 1)[1].split(
        "  sudo python3 scripts/sched_settings.py set-cpus", 1)[0]
    boot = Path(tempfile.mkdtemp(dir=str(tmp_path))) / "cmdline"
    if cmdline is not None:
        _write(boot, cmdline + "\n")
    script = "\n".join(["set -uo pipefail", "checks () {", block, "}", 'REASON=""', "checks",
                        'echo "REASON=$REASON"', ""])
    env = dict({"BACKEND": "redis", "SO_JOURNAL": "", "SO_STAMPS": "", "SEND_CAPTURE": "",
                "SEND_CAPTURE_BOTH": "", "SEND_WORKERS": "", "SCHED_FEATURES": "",
                "IDLE_POLL": "", "BOOT_CMDLINE": boot.as_posix()}, **setting)
    said = bash(["-c", script], extra_env=env, capture_output=True, text=True,
                check=True).stdout
    return said.strip().rsplit("REASON=", 1)[1]


@needs_bash
@pytest.mark.parametrize("setting,said", [
    ({"SO_JOURNAL": "1"}, "so_journal needs so_timestamps"),
    ({"SO_JOURNAL": "consumer"}, "so_journal needs so_timestamps"),
    ({"SO_JOURNAL": "both", "SO_STAMPS": "sched"},
     'so_journal is true, for both clients, or "consumer", not "both"'),
    ({"SEND_CAPTURE_BOTH": "1"}, "send_capture_both needs send_capture"),
    ({"SEND_WORKERS": "1", "BACKEND": "kafka"},
     "send_workers is the Redis producer's setting, and this run is kafka"),
    ({"SEND_WORKERS": "0"}, 'send_workers is a whole number of at least one, not "0"'),
    ({"SEND_WORKERS": "01"}, 'send_workers is a whole number of at least one, not "01"'),
    ({"SEND_WORKERS": "True"}, 'send_workers is a whole number of at least one, not "True"'),
    ({"SCHED_FEATURES": "NO_HRTICK"},
     'sched_features is RUN_TO_PARITY or NO_RUN_TO_PARITY, not "NO_HRTICK"')])
def test_a_setup_the_runner_cannot_give_as_written_fails_before_the_machine_is_touched(
        tmp_path, setting, said):
    """Each of these would otherwise run and be filed under a setting it did not have: a journal
    nothing writes, a one-way capture read as two-way, the producer's sixteen workers read as one,
    or a scheduler feature that nothing puts back after the run."""
    assert _setup_says(tmp_path, **setting).startswith(said)


@needs_bash
@pytest.mark.parametrize("setting", [
    {}, {"SO_JOURNAL": "1", "SO_STAMPS": "sched"}, {"SO_JOURNAL": "consumer", "SO_STAMPS": "sched"},
    {"SEND_CAPTURE_BOTH": "1", "SEND_CAPTURE": "1"}, {"SEND_WORKERS": "1"},
    {"SEND_WORKERS": "16"}, {"SCHED_FEATURES": "NO_RUN_TO_PARITY"},
    {"SCHED_FEATURES": "RUN_TO_PARITY"}])
def test_and_a_setup_it_can_give_passes_those_checks(tmp_path, setting):
    assert _setup_says(tmp_path, **setting) == ""


@needs_bash
@pytest.mark.parametrize("cmdline,wanted,said", [
    (STOCK_ARGS + " idle=poll", "1", ""),
    ("idle=poll " + STOCK_ARGS, "1", ""),
    (STOCK_ARGS, "1", "the setup asks for idle=poll and this boot's command line does not hold it"),
    (STOCK_ARGS + " idle=polling", "1",
     "the setup asks for idle=poll and this boot's command line does not hold it"),
    (STOCK_ARGS + " xidle=poll", "1",
     "the setup asks for idle=poll and this boot's command line does not hold it"),
    (STOCK_ARGS, "0", ""),
    (STOCK_ARGS + " idle=halt", "0", ""),
    (STOCK_ARGS + " idle=poll", "0",
     "the setup asks for the default boot and this boot's command line holds idle=poll"),
    (None, "1", "could not be read, so the boot the setup names cannot be confirmed"),
    (None, "0", "could not be read, so the boot the setup names cannot be confirmed"),
    (None, "", "")])
def test_a_run_of_block_i_counts_only_on_the_boot_its_setup_names(tmp_path, cmdline, wanted,
                                                                   said):
    """The two boots differ in idle= and in nothing else, so nothing but the boot's own command
    line tells a run on one from a run on the other. A setup that names no boot is not asked."""
    found = _setup_says(tmp_path, cmdline, IDLE_POLL=wanted)
    assert (found.endswith(said) and found != "") if said else found == ""


def _machine_settings(tmp_path, features):
    """A machine's scheduler files as sched_settings.py reads them, in a fake tree: the stock 6.8
    kernel on eight CPUs, its features as debugfs shows them, or no features file at all."""
    root = tmp_path / "machine"
    for rel, text in (("proc/sys/kernel/osrelease", "6.8.0-1064-azure"),
                      ("boot/config-6.8.0-1064-azure", "CONFIG_HZ=250"),
                      ("sys/kernel/debug/sched/base_slice_ns", "2800000"),
                      ("sys/kernel/debug/sched/tunable_scaling", "1"),
                      ("sys/devices/system/cpu/online", "0-7"),
                      ("sys/kernel/debug/sched/features", features)):
        if text is not None:
            _write(root / rel, text + "\n")
    return root


#: A feature line of the kind debugfs shows on a kernel at its defaults, RUN_TO_PARITY on, and
#: the same line as a run of block R that set NO_RUN_TO_PARITY and then crashed would leave it.
DEFAULT_FEATURES = "PLACE_LAG PLACE_DEADLINE_INITIAL RUN_TO_PARITY NO_NEXT_BUDDY NO_HRTICK "
LEFT_OFF = DEFAULT_FEATURES.replace(" RUN_TO_PARITY", " NO_RUN_TO_PARITY")

#: sudo standing in for itself by running sched_settings.py against the fake machine, and writing
#: down how it was called.
_SUDO_SCHED = ('sudo () { echo "$*" >> "$CALLS"; shift 2; '
               'python3 scripts/sched_settings.py --root "$MACHINE" "$@"; }')


def _settings_lines(tmp_path, features, **setting):
    """A run's settings lines, from the slice to the check before the run, run as the runner runs
    them, with sched_settings.py itself reading and writing a fake machine. (The REASON, what the
    check before the run wrote, and how sched_settings.py was called.)"""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    run = code.split("run_one () {", 1)[1]
    first = '  if [ -n "$SLICE_NS" ]; then'
    last = 'REASON="the settings before the run do not match the setup"; return; }'
    block = first + run.split(first, 1)[1].split(last, 1)[0] + last
    machine = _machine_settings(tmp_path, features)
    calls, run_dir = tmp_path / "calls.txt", tmp_path / "run"
    run_dir.mkdir()
    script = "\n".join(["set -uo pipefail", _SUDO_SCHED, "settings () {", "  local check_args=()",
                        block, "}", 'REASON=""', "settings", 'echo "REASON=$REASON"', ""])
    env = dict({"CALLS": calls.as_posix(), "RUN_DIR": run_dir.as_posix(),
                "MACHINE": machine.as_posix(), "SLICE_NS": "", "HZ": "", "SCHED_FEATURES": ""},
               **setting)
    said = bash(["-c", script], cwd=REPO, extra_env=env, capture_output=True, text=True,
                check=True).stdout
    before = run_dir / "settings_before.json"
    return (said.strip().rsplit("REASON=", 1)[1],
            json.loads(before.read_text(encoding="utf-8")) if before.exists() else None,
            calls.read_text(encoding="utf-8").splitlines() if calls.exists() else [])


@needs_bash
def test_block_r_sets_its_feature_and_the_check_before_the_run_holds_the_machine_to_it(tmp_path):
    """A setup that names NO_RUN_TO_PARITY has it written through debugfs beside the slice, and
    the check before the run holds the machine to it and records the features with the rest."""
    reason, before, calls = _settings_lines(tmp_path, DEFAULT_FEATURES,
                                            SCHED_FEATURES="NO_RUN_TO_PARITY")
    assert reason == "" and before["ok"] is True
    assert before["settings"]["sched_features"]["RUN_TO_PARITY"] is False
    assert calls == ["python3 scripts/sched_settings.py set-feature NO_RUN_TO_PARITY",
                     "python3 scripts/sched_settings.py check --feature NO_RUN_TO_PARITY"]


@needs_bash
def test_every_other_run_is_held_to_the_default_so_a_feature_left_off_fails_it(tmp_path):
    """A run whose setup names no feature sets none, and its check holds the machine to
    RUN_TO_PARITY on. A feature that a crashed run of block R left off fails the next run before
    any traffic, rather than contaminating it."""
    reason, before, calls = _settings_lines(tmp_path / "default", DEFAULT_FEATURES)
    assert reason == "" and before["ok"] is True
    assert calls == ["python3 scripts/sched_settings.py check --feature-if-known RUN_TO_PARITY"]
    reason, before, _ = _settings_lines(tmp_path / "left", LEFT_OFF)
    assert reason == "the settings before the run do not match the setup"
    assert before["problems"] == ["the scheduler feature RUN_TO_PARITY is off, not on"]


@needs_bash
def test_a_kernel_that_shows_no_features_fails_no_run_for_them_and_records_them_unknown(tmp_path):
    """An older kernel, or one without debugfs: there is nothing to hold a run to."""
    reason, before, _ = _settings_lines(tmp_path, None)
    assert reason == "" and before["ok"] is True
    assert before["settings"]["sched_features"] is None
    assert "sched_features" in before["settings"]["missing"]


def _features_back(tmp_path, features, sched_features):
    """features_back as the runner defines it, run with sudo standing in as above. (What it wrote,
    the features the machine shows after it, and how sched_settings.py was called.)"""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    body = "features_back () {" + code.split("\nfeatures_back () {", 1)[1].split("\n}\n", 1)[0]
    machine = _machine_settings(tmp_path, features)
    calls, out = tmp_path / "calls.txt", tmp_path / "feature_back.txt"
    script = "\n".join(["set -uo pipefail", 'log () { echo "$*"; }', _SUDO_SCHED, body, "}",
                        'features_back "$OUT"', ""])
    env = {"CALLS": calls.as_posix(), "MACHINE": machine.as_posix(), "OUT": out.as_posix(),
           "SCHED_FEATURES": sched_features}
    bash(["-c", script], cwd=REPO, extra_env=env, capture_output=True, text=True, check=True)
    shown = (machine / "sys/kernel/debug/sched/features").read_text(encoding="utf-8").split()
    return (out.read_text(encoding="utf-8") if out.exists() else None, shown,
            calls.read_text(encoding="utf-8").splitlines() if calls.exists() else [])


@needs_bash
def test_a_run_that_set_a_feature_puts_the_default_back_and_any_other_run_touches_nothing(
        tmp_path):
    said, shown, calls = _features_back(tmp_path / "r", LEFT_OFF, "NO_RUN_TO_PARITY")
    assert "RUN_TO_PARITY" in shown and "NO_RUN_TO_PARITY" not in shown
    assert calls == ["python3 scripts/sched_settings.py set-feature RUN_TO_PARITY"]
    assert "scheduler feature RUN_TO_PARITY set, and read back" in said
    said, shown, calls = _features_back(tmp_path / "k", LEFT_OFF, "")
    assert (said, calls) == (None, []) and "NO_RUN_TO_PARITY" in shown, \
        "a run that names no feature changed none; what it finds is its own check's to judge"


def test_the_default_goes_back_after_every_run_that_set_a_feature_however_it_ended():
    """However run_one returned -- a failed check, a failed trial, or a run that counted -- the
    loop puts the default back before the queue is told, and a campaign stopped in the middle of
    a run puts it back on its way out. The check after the run, which writes
    settings_after.json, comes first and takes the same arguments as the check before it, so it
    holds the treatment the run had."""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    loop = code.split("\nwhile true; do", 1)[1]
    assert loop.index("\n  run_one\n") \
        < loop.index('\n  features_back "$RUN_DIR/feature_back.txt"\n') \
        < loop.index("run_queue.py finish")
    leaving = code.split("finish_campaign () {", 1)[1].split("\n}", 1)[0]
    assert "features_back /dev/null" in leaving, "into no run's folder"
    run = code.split("run_one () {", 1)[1].split("\n}\n", 1)[0]
    assert run.index('check_args+=(--feature "$SCHED_FEATURES")') \
        < run.index('check "${check_args[@]}" > "$RUN_DIR/settings_before.json"') \
        < run.index('check "${check_args[@]}" > "$RUN_DIR/settings_after.json"')


@needs_bash
def test_freeze_41s_sender_capture_keeps_both_directions_in_a_larger_buffer(tmp_path):
    """Block K checks each acknowledgment's arrival in the journal against the arrival the capture
    saw, so the sender's capture keeps the broker's packets to the driver as well as the driver's
    to the broker, still without ssh. Both full captures then get a 32 MiB buffer, placed after
    the file name so that the patterns that stop them still find them, and not their own sudo."""
    _, calls = _r1_runner(tmp_path, "both", SEND_CAPTURE="1", SEND_CAPTURE_BOTH="1",
                          RECV_CAPTURE="1")
    run = (tmp_path / "both").as_posix()
    started = [c for c in calls if "pkill" not in c]
    assert started == [
        "sudo ip netns exec sblrecv tcpdump -i any -s 0 --time-stamp-precision=nano -w "
        "%s/receiver_full.pcap -B 32768 host 10.9.9.9" % run,
        "sudo tcpdump -i eth0 -s 0 --time-stamp-precision=nano -w %s/sender_full.pcap -B 32768 "
        "host 10.8.8.8 and host 10.9.9.9 and not port 22" % run]
    stops = [c.split(" -f ", 1) for c in calls if "pkill" in c]
    assert [how for how, _ in stops] == ["sudo pkill -INT", "sudo pkill -KILL"] * 2
    for (how, pattern), target in zip(stops, (started[0], started[0], started[1], started[1])):
        assert re.search(pattern, target), "pkill -f finds the capture by its command line"
        assert not re.search(pattern, "%s -f %s" % (how, pattern))
    # The buffer alone, asked for where a block captures one way at a high rate (block L).
    _, calls = _r1_runner(tmp_path, "buffered", SEND_CAPTURE="1", RECV_CAPTURE="1",
                          CAPTURE_BUFFER="1")
    run = (tmp_path / "buffered").as_posix()
    assert [c for c in calls if "pkill" not in c] == [
        "sudo ip netns exec sblrecv tcpdump -i any -s 0 --time-stamp-precision=nano -w "
        "%s/receiver_full.pcap -B 32768 host 10.9.9.9" % run,
        "sudo tcpdump -i eth0 -s 0 --time-stamp-precision=nano -w %s/sender_full.pcap -B 32768 "
        "src host 10.8.8.8 and dst host 10.9.9.9 and not port 22" % run]


def _trial_handed(tmp_path, backend, send_workers=""):
    """What the runner hands the trial runner, from its lines from the start of the trial to its
    end, run as the runner runs them with an unset variable an error, and `timeout` standing in
    for the trial by writing down its arguments, one to a line. (Those, and the producer's socket
    arguments the run was given.)"""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    run = code.split("run_one () {", 1)[1]
    first = "  began=$(date -u +%s)"
    block = first + run.split(first, 1)[1].split("  ended=$(date -u +%s)", 1)[0]
    calls = tmp_path / ("handed_%s_%s.txt" % (backend, send_workers or "none"))
    script = "\n".join(["set -uo pipefail", 'timeout () { printf "%s\\n" "$@" > "$CALLS"; }',
                        "trial () {", "  local rc began", block, "}", "trial", ""])
    so = "--so-timestamps %s/producer_so.csv --so-transmit sched" % tmp_path.as_posix()
    env = {"CALLS": calls.as_posix(), "BACKEND": backend, "SEND_WORKERS": send_workers,
           "RUN_ID": "law_k_r001", "RUN_DIR": tmp_path.as_posix(), "DURATION": "130",
           "run_plan": "plan.csv", "run_speedup": "1", "run_maxt": "130",
           "KAFKA_BOOTSTRAP": "10.9.9.9:19092", "KAFKA_PRODUCER_EXTRA": "--max-inflight 64",
           "REDIS_HOST": "10.9.9.9", "REDIS_PORT": "6379",
           "REDIS_CONSUMER_EXTRA": "--ack-batch 200", "ACK_BATCH": "", "record_args": "",
           "read_args": "", "so_prod": so, "so_cons": so.replace("producer", "consumer"),
           "consumer_wrap": "sudo ip netns exec sblrecv sudo -u tester", "wrap_sched": "",
           # Freeze 43 (22 Oct 2026): the producer's own wrap and the clients' flags, none asked.
           "producer_wrap": "", "prod_flags": "", "cons_flags": "",
           # Plan version 47 (23 Oct 2026): the plan's arrivals and the values set in one place.
           "run_arrival": "constant", "run_seed": "", "THREADS_WAIT_S": "60",
           "FETCH_RT_PRIORITY": "80"}
    bash(["-c", script], extra_env=env, capture_output=True, text=True, check=True)
    return calls.read_text(encoding="utf-8").splitlines(), so


@needs_bash
def test_freeze_41s_one_worker_setups_reach_the_redis_producer_and_no_other(tmp_path):
    """Block K's two one-worker setups hand the Redis producer --send-workers 1, after everything
    it was handed before. A setup that names no count hands it exactly what freeze 40 did, and the
    Kafka producer, which has no such setting, is never handed one."""
    def producer(handed):
        return handed[handed.index("-PRODUCER_EXTRA") + 1]
    one, so = _trial_handed(tmp_path, "redis", "1")
    assert "scripts/run_redis_trial.sh" in one
    assert producer(one) == " %s --send-workers 1" % so
    plain, so = _trial_handed(tmp_path, "redis")
    assert producer(plain) == " %s" % so, '"$record_args $so_prod", as before'
    kafka, so = _trial_handed(tmp_path, "kafka", "1")
    assert "scripts/run_kafka_trial.sh" in kafka
    assert producer(kafka) == "--max-inflight 64  %s" % so
    assert not [arg for arg in kafka if "--send-workers" in arg]


#: A menu file like the one Ubuntu ships in /etc/grub.d, before anything of ours is written to it.
UBUNTU_CUSTOM = ("#!/bin/sh\nexec tail -n +3 $0\n# This file provides an easy way to add custom "
                 "menu entries.  Simply type the\n# menu entries you want to add after this "
                 "comment.  Be careful not to change\n# the 'exec tail' line above.\n")
#: The same file once cpus.sh has asked for two CPUs: cpus.sh's own entry is its whole content.
CPUS_CUSTOM = ("#!/bin/sh\nexec tail -n +3 $0\n# Written by cloud/azure/cpus.sh.\n"
               "menuentry 'sbl: 6.8.0-1064-azure, 2 CPUs' --id sbl-cpus {\n"
               "  linux /boot/vmlinuz-6.8.0-1064-azure %s nr_cpus=2\n}\n" % STOCK_ARGS)


def _idle_sh(tmp_path, argv, cmdline=None, custom=UBUNTU_CUSTOM, kept=None, menu_takes=True):
    """idle.sh, run in a scratch checkout against a fake machine: its command line; two stock
    kernels and one of A2's tick builds; the menu file in /etc/grub.d and the copy kept aside, if
    any; and stand-ins for sudo, findmnt, update-grub and grub-reboot that write down how they
    were called. update-grub does what grub-mkconfig does with /etc/grub.d -- runs each numbered
    file and gathers what it prints into the menu -- unless `menu_takes` is false.
    (The finished process, the machine, the calls.)"""
    checkout = _scratch_checkout(tmp_path)
    machine, stubs, calls = tmp_path / "machine", tmp_path / "bin", tmp_path / "calls.txt"
    for kernel in ("6.8.0-1017-azure", "6.8.0-1064-azure", "6.8.12-sbl1000"):
        _write(machine / "boot" / ("vmlinuz-" + kernel), "")
        _write(machine / "boot" / ("initrd.img-" + kernel), "")
    _write(machine / "boot" / "grub" / "grub.cfg", "")
    if cmdline is not None:
        _write(machine / "proc" / "cmdline", cmdline + "\n")
    if custom is not None:
        _write(machine / "etc" / "grub.d" / "40_custom", custom)
    if kept is not None:
        _write(machine / "etc" / "grub.d" / "40_custom.sbl-orig", kept)
    for name, body in (
            ("sudo", 'echo "sudo $*" >> "$CALLS"\nexec "$@"\n'),
            ("findmnt", "echo 0f1e2d3c-4b5a-4968-8776-655443322110\n"),
            ("update-grub", 'echo update-grub >> "$CALLS"\n'
                            '[ "$MENU_TAKES" = 1 ] || exit 0\n'
                            ': > "$SBL_ROOT/boot/grub/grub.cfg"\n'
                            'for f in "$SBL_ROOT"/etc/grub.d/[0-9][0-9]_*; do\n'
                            '  case "$f" in *.sbl-orig) continue ;; esac\n'
                            '  sh "$f" >> "$SBL_ROOT/boot/grub/grub.cfg"\n'
                            'done\n'),
            ("grub-reboot", 'echo "grub-reboot $*" >> "$CALLS"\n')):
        os.chmod(_write(stubs / name, "#!/bin/sh\n" + body), 0o755)
    done = bash(["cloud/azure/idle.sh"] + argv, cwd=checkout, path_first=[stubs],
                extra_env={"SBL_ROOT": machine.as_posix(), "CALLS": calls.as_posix(),
                           "MENU_TAKES": "1" if menu_takes else "0"},
                capture_output=True, text=True)
    return done, machine, (calls.read_text(encoding="utf-8").splitlines()
                           if calls.exists() else [])


@needs_bash
def test_idle_poll_is_asked_for_once_on_the_stock_kernel_from_the_running_boots_arguments(
        tmp_path):
    """The entry is the running boot's own arguments, less the image it booted and any idle= or
    core count a boot of this kit left there, plus idle=poll; on the newest stock kernel, not a
    tick build; and selected for the next boot only. The script does not reboot: it says to."""
    cmdline = ("BOOT_IMAGE=/boot/vmlinuz-6.8.0-1064-azure %s idle=halt nr_cpus=2 "
               "intel_idle.max_cstate=1" % STOCK_ARGS)
    done, machine, calls = _idle_sh(tmp_path, ["boot", "poll"], cmdline)
    assert done.returncode == 0, done.stdout + done.stderr
    entry = (machine / "etc" / "grub.d" / "42_sbl_idle").read_text(encoding="utf-8").splitlines()
    assert "menuentry 'sbl: 6.8.0-1064-azure, idle=poll' --id sbl-idle {" in entry
    assert ("  linux /boot/vmlinuz-6.8.0-1064-azure %s intel_idle.max_cstate=1 idle=poll"
            % STOCK_ARGS) in entry
    assert "  initrd /boot/initrd.img-6.8.0-1064-azure" in entry
    assert "  search --no-floppy --fs-uuid --set=root 0f1e2d3c-4b5a-4968-8776-655443322110" \
        in entry
    assert [c for c in calls if c.startswith("grub-reboot")] == ["grub-reboot sbl-idle"]
    assert not [c for c in calls if c.split()[:2] in (["sudo", "reboot"], ["sudo", "systemctl"],
                                                      ["sudo", "shutdown"])]
    assert "reboot now, then run: bash cloud/azure/idle.sh status" in done.stdout


@needs_bash
def test_idle_sh_leaves_cpus_sh_s_menu_file_alone_and_both_entries_reach_the_menu(tmp_path):
    """cpus.sh writes the whole of 40_custom and puts its saved copy back to restore, so idle.sh
    keeps its entry in a file of its own. Where cpus.sh has asked for a core count, its file and
    the copy it kept aside are as they were, and the menu holds both entries; on a fresh machine
    the image's own file is kept aside, as cpus.sh keeps it, and left as it is."""
    cmdline = "BOOT_IMAGE=/boot/vmlinuz-6.8.0-1064-azure " + STOCK_ARGS
    done, machine, _ = _idle_sh(tmp_path / "after_cpus", ["boot", "poll"], cmdline,
                                custom=CPUS_CUSTOM, kept=UBUNTU_CUSTOM)
    assert done.returncode == 0, done.stdout + done.stderr
    grub_d = machine / "etc" / "grub.d"
    assert (grub_d / "40_custom").read_bytes() == CPUS_CUSTOM.encode("utf-8")
    assert (grub_d / "40_custom.sbl-orig").read_bytes() == UBUNTU_CUSTOM.encode("utf-8")
    menu = (machine / "boot" / "grub" / "grub.cfg").read_text(encoding="utf-8")
    assert "--id sbl-cpus {" in menu and "--id sbl-idle {" in menu
    done, machine, _ = _idle_sh(tmp_path / "fresh", ["boot", "poll"], cmdline)
    assert done.returncode == 0, done.stdout + done.stderr
    grub_d = machine / "etc" / "grub.d"
    assert (grub_d / "40_custom").read_bytes() == UBUNTU_CUSTOM.encode("utf-8")
    assert (grub_d / "40_custom.sbl-orig").read_bytes() == UBUNTU_CUSTOM.encode("utf-8")


@needs_bash
def test_an_entry_that_did_not_reach_the_menu_is_never_selected(tmp_path):
    """grub-reboot naming an id the menu does not hold would leave the next boot to whatever grub
    makes of it, so a menu that did not take the entry stops the script before grub-reboot."""
    done, _, calls = _idle_sh(tmp_path, ["boot", "poll"],
                              "BOOT_IMAGE=/boot/vmlinuz-6.8.0-1064-azure " + STOCK_ARGS,
                              menu_takes=False)
    assert done.returncode == 1 and "STOP_RULE: the entry did not reach the menu" in done.stdout
    assert "update-grub" in calls and not [c for c in calls if "grub-reboot" in c]


@needs_bash
@pytest.mark.parametrize("argv,cmdline,said", [
    (["boot", "halt"], STOCK_ARGS, 'the one idle= this boots is poll, not "halt"'),
    (["boot"], STOCK_ARGS, 'the one idle= this boots is poll, not ""'),
    (["boot", "poll"], "BOOT_IMAGE=/boot/vmlinuz-6.8.0-1064-azure idle=poll",
     "came back empty; refusing to write a boot entry from it"),
    (["boot", "poll"], None, "came back empty; refusing to write a boot entry from it")])
def test_idle_sh_writes_no_entry_it_cannot_stand_behind(tmp_path, argv, cmdline, said):
    done, machine, calls = _idle_sh(tmp_path, argv, cmdline)
    assert done.returncode == 1 and "STOP_RULE: " in done.stdout and said in done.stdout
    assert not (machine / "etc" / "grub.d" / "42_sbl_idle").exists()
    assert not [c for c in calls if "grub-reboot" in c]


@needs_bash
def test_idle_sh_says_how_it_is_used(tmp_path):
    done, _, _ = _idle_sh(tmp_path, [], STOCK_ARGS)
    assert done.returncode == 2
    assert "usage: bash cloud/azure/idle.sh boot poll | status" in done.stderr


@needs_bash
@pytest.mark.parametrize("cmdline,holds", [
    (STOCK_ARGS + " idle=poll", True), ("idle=poll " + STOCK_ARGS, True),
    (STOCK_ARGS + " idle=poll intel_idle.max_cstate=1", True), (STOCK_ARGS, False),
    (STOCK_ARGS + " idle=polling", False), (STOCK_ARGS + " xidle=poll", False),
    (STOCK_ARGS + " idle=halt", False)])
def test_idle_sh_and_the_runner_read_a_boot_the_same_way(tmp_path, cmdline, holds):
    """The queue asks idle.sh whether a boot holds idle=poll, and the runner reads /proc/cmdline
    itself before each of block I's runs. Both read it as an argument of its own, and agree."""
    done, _, _ = _idle_sh(tmp_path, ["status"], cmdline)
    assert done.returncode == 0
    assert done.stdout == ("idle=poll on\n" if holds else "idle=poll off\n")
    assert (_setup_says(tmp_path, cmdline, IDLE_POLL="1") == "") is holds
    assert (_setup_says(tmp_path, cmdline, IDLE_POLL="0") == "") is not holds


@needs_bash
def test_idle_sh_will_not_guess_a_boot_whose_command_line_it_cannot_read(tmp_path):
    done, _, _ = _idle_sh(tmp_path, ["status"], None)
    assert done.returncode == 1 and "could not be read" in done.stdout
    assert "idle=poll on" not in done.stdout and "idle=poll off" not in done.stdout


def test_the_queue_names_the_idlepoll_boot_among_its_boots():
    code = QUEUE.read_text(encoding="utf-8")
    assert "#   boot=      hz1000 | hz250 | hz100 | stock | cpu2 | cpu4 | cpu8 | idlepoll | none" \
        in code


@needs_bash
@pytest.mark.parametrize("boot,release,cmdline,ok", [
    ("idlepoll", "6.8.0-1064-azure", STOCK_ARGS + " idle=poll", True),
    ("idlepoll", "6.8.0-1064-azure", STOCK_ARGS, False),
    ("idlepoll", "6.8.12-sbl1000", STOCK_ARGS + " idle=poll", False),
    ("idlepoll", "6.8.0-1064-azure", None, False),
    ("stock", "6.8.0-1064-azure", STOCK_ARGS, True),
    ("stock", "6.8.0-1064-azure", STOCK_ARGS + " idle=poll", False),
    ("stock", "6.8.0-1064-azure", None, False),
    ("stock", "6.8.12-sbl1000", STOCK_ARGS, False),
    ("none", "6.8.12-sbl1000", STOCK_ARGS + " idle=poll", True)])
def test_the_queue_checks_block_is_boot_and_that_no_other_boot_has_idle_poll(
        tmp_path, boot, release, cmdline, ok):
    """idlepoll must come back on the stock kernel with idle=poll, and every other boot without
    it. A boot that came back on the wrong entry would pass every other check and have its runs
    filed under the other boot's name. none reboots nothing and is not asked."""
    machine = tmp_path / "machine"
    if cmdline is not None:
        _write(machine / "proc" / "cmdline", cmdline + "\n")
    said = _queue_call(tmp_path, 'uname () { echo "%s"; }; verify_boot %s; echo "rc=$?"'
                       % (release, boot), extra_env={"SBL_ROOT": machine.as_posix()})
    assert said.splitlines()[-1] == ("rc=0" if ok else "rc=1"), said


@needs_bash
def test_the_queue_asks_idle_sh_for_the_idlepoll_boot_and_for_no_other(tmp_path):
    root = _scratch_checkout(tmp_path)
    _write(root / "cloud" / "azure" / "idle.sh", 'echo "$*" > asked.txt\n')
    record = root / "asked.txt"
    for boot, asked in (("idlepoll", "boot poll\n"), ("stock", None), ("none", None)):
        if record.exists():
            record.unlink()
        script = "cd '%s' && . cloud/azure/queue.sh >/dev/null 2>&1; ask_for_boot %s" % (
            root.as_posix(), boot)
        bash(["-c", script], capture_output=True, text=True)
        found = record.read_text(encoding="utf-8") if record.exists() else None
        assert found == asked, boot


@needs_bash
def test_a_command_job_can_run_a_campaign_at_another_rate(tmp_path):
    """Block L runs campaigns at 500 and 5,000 messages a second, each a command job with the
    campaign's rate, duration and warm-up written before it. The loop runs a command through
    bash -c, so those settings reach the command's environment; this runs the loop's own line."""
    root = _scratch_checkout(tmp_path)
    _write(root / "probe.sh",
           'echo "rate=$RATE duration=$DURATION warmup=$WARMUP_S queue=$1"\n')
    code = QUEUE.read_text(encoding="utf-8").replace("\r\n", "\n")
    booted = code.split("      booted)", 1)[1].split("\n        ;;", 1)[0]
    line = next(text.strip() for text in booted.splitlines() if "timeout 43200" in text)
    job = ("boot=idlepoll cmd=RATE=500 DURATION=70 WARMUP_S=20 bash probe.sh "
           "runs/azure/queues/l500.csv")
    out = (tmp_path / "cmd.log").as_posix()
    said = _queue_call(tmp_path, 'cmd="$(field "%s" cmd)"; out="%s"; %s; cat "$out"'
                       % (job, out, line))
    assert said == "rate=500 duration=70 warmup=20 queue=runs/azure/queues/l500.csv"
    assert _queue_call(tmp_path, 'field "%s" boot' % job) == "idlepoll"


# --- Freeze 42 (22 Oct 2026): the consumer's turnaround where load and rate bite together
# (docs/results/under_load/DESIGN.md). What block U asks of the kit beyond freeze 41's: the
# broker's own capture of its port.

def test_freeze_42s_broker_capture_reaches_the_runner_and_a_row_without_it_sets_none():
    """A row's broker_capture becomes BROKER_CAPTURE; a row of any earlier block names none, and
    its run is launched exactly as before."""
    assert _row_reader_says({"broker_capture": True})["BROKER_CAPTURE"] == "1"
    assert _row_reader_says({"so_timestamps": "sched", "so_journal": True})["BROKER_CAPTURE"] == ""


@needs_bash
def test_freeze_42s_broker_capture_is_its_own_port_stopped_by_its_id_and_copied_into_the_run(
        tmp_path):
    """Block U splits each message's kernel-timed latency at the broker, so the broker captures
    its own port, both directions, at full length and to the nanosecond, with the larger buffer.
    It is stopped by its own id and waited for before the capture and tcpdump's count of drops are
    copied into the run's folder, and the broker's copies are removed. Redis's port for Redis, and
    nothing asked of the broker where the setup asks for no capture."""
    _, calls = _r1_runner(tmp_path, "kafka", BROKER_CAPTURE="1")
    remote = [c for c in calls if c.startswith("remote_broker ")]
    assert remote[0] == (
        "remote_broker sudo sh -c 'kill -INT $(cat /dev/shm/sbl_bfull.pid 2>/dev/null) 2>/dev/null; "
        "rm -f /dev/shm/sbl_bfull.pcap /dev/shm/sbl_bfull.err; nohup tcpdump -i eth0 -s 0 "
        "--time-stamp-precision=nano -B 32768 -w /dev/shm/sbl_bfull.pcap tcp port 19092 > "
        "/dev/shm/sbl_bfull.err 2>&1 & echo $! > /dev/shm/sbl_bfull.pid'")
    assert remote[1].startswith("remote_broker sudo kill -INT $(cat /dev/shm/sbl_bfull.pid)")
    assert "sudo kill -0 $(cat /dev/shm/sbl_bfull.pid) 2>/dev/null || break" in remote[1]
    assert remote[2:] == [
        "remote_broker sudo cat /dev/shm/sbl_bfull.pcap",
        "remote_broker sudo cat /dev/shm/sbl_bfull.err; sudo rm -f /dev/shm/sbl_bfull.pcap "
        "/dev/shm/sbl_bfull.err /dev/shm/sbl_bfull.pid"]
    assert (tmp_path / "kafka" / "broker_full.pcap").exists()
    assert (tmp_path / "kafka" / "broker_full.err").exists()
    _, calls = _r1_runner(tmp_path, "redis", BROKER_CAPTURE="1", BACKEND="redis")
    assert "tcp port 6379 >" in [c for c in calls if c.startswith("remote_broker ")][0]
    # Pilot round a of plan version 47: on the broker's memory, never its disk. On the Arm pair
    # the capture's writes to disk held Kafka's acknowledgements for 190 to 610 ms.
    assert "/tmp/sbl_bfull" not in _campaign()
    assert all("/dev/shm/sbl_bfull" in c for c in calls if c.startswith("remote_broker "))
    _, calls = _r1_runner(tmp_path, "none")
    assert not [c for c in calls if c.startswith("remote_broker ")]


@needs_bash
def test_freeze_42s_card_capture_takes_the_larger_buffer_where_the_setup_does(tmp_path):
    """Block U runs the card's capture on a loaded driver at 2,000 messages a second, where a
    dropped packet would leave every later byte of its stream unread, so it takes the 32 MiB
    buffer wherever the setup's other captures do, after the file name, so that the patterns that
    stop it still find it. Freeze 39's setups, which ask for no larger buffer, capture as before."""
    _, calls = _r1_runner(tmp_path, "buffered", HW_CAPTURE="1", SEND_CAPTURE="1",
                          SEND_CAPTURE_BOTH="1", FAKE_LINK=LINKS, FAKE_PHC="1")
    run = (tmp_path / "buffered").as_posix()
    card = [c for c in calls if "adapter_unsynced" in c and "pkill" not in c]
    assert card == ["sudo tcpdump -i enP58460s1 -j adapter_unsynced -s 0 --time-stamp-precision="
                    "nano -w %s/receiver_hw.pcap -B 32768 src host 10.9.9.9 and dst host 10.7.7.7"
                    % run]
    stops = [c.split(" -f ", 1)[1] for c in calls if "pkill" in c and "adapter_unsynced" in c]
    assert stops and all(re.search(pattern, card[0]) for pattern in stops)


def test_freeze_42s_second_correction_reaches_the_runner_and_a_row_without_it_sets_none():
    """A row's load_recorrect becomes LOAD_RECORRECT; a row of any earlier block names none."""
    assert _row_reader_says({"load_recorrect": True})["LOAD_RECORRECT"] == "1"
    assert _row_reader_says({"broker_capture": True})["LOAD_RECORRECT"] == ""


def _recorrect(tmp_path, name, rows, want="70", duty="70"):
    """recorrect_load, run in bash as the runner defines it, with its Python the real one and
    sleep, pkill and stress-ng stood in for by commands that write down how they were called.
    (The calls, the record it wrote or None.)"""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    head = "recorrect_load () {"
    function = head + code.split(head, 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    run = tmp_path / name
    run.mkdir()
    if rows is not None:
        (run / "utilisation.csv").write_text(
            "t_wall,rho,loadavg,rho_clients\n" + "".join(
                "%d,%s,1.0,%s\n" % (i, rho, clients) for i, (rho, clients) in enumerate(rows)),
            encoding="utf-8")
    calls = tmp_path / (name + "_calls.txt")
    script = "\n".join([
        'python3 () { "$PYTHON" "$@"; }', 'sleep () { echo "sleep $*" >> "$CALLS"; }',
        'pkill () { echo "pkill $*" >> "$CALLS"; }',
        'stress-ng () { echo "stress-ng $*" >> "$CALLS"; }', _function("load_start"), function,
        'recorrect_load "$RUN" %s %s 8' % (want, duty), "builtin wait", ""])
    env = {"CALLS": calls.as_posix(), "RUN": run.as_posix(),
           "PYTHON": Path(sys.executable).as_posix()}
    bash(["-c", script], extra_env=env, capture_output=True, text=True, check=True)
    record = run / "load_recorrection.json"
    return ((calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []),
            json.loads(record.read_text(encoding="utf-8")) if record.exists() else None)


@needs_bash
def test_freeze_42s_second_correction_moves_the_duty_by_what_the_running_clients_cost(tmp_path):
    """Ten seconds into the trial, inside its warm-up, the duty is corrected against the
    background load the machine shows less the clients' own share, the quantity the integrity
    rule reads, and stress-ng is restarted there. Block U's pilot held 63.3% of a 70% load with
    real-time clients at 2,000 messages a second: here the last six samples show 63%, so the
    duty goes to 77. Older samples are not read, and a duty already right is left alone."""
    early = [("0.10", "0.20")] * 4
    calls, record = _recorrect(tmp_path, "short", early + [("0.85", "0.22")] * 6)
    assert calls == ["sleep 10", "pkill -9 -x stress-ng",
                     "stress-ng --cpu 8 --cpu-load 77 --timeout 3600s"]
    assert record == {"designed_pct": 70, "shown_running_pct": 63.0, "duty_before_pct": 70,
                      "duty_used_pct": 77}
    calls, record = _recorrect(tmp_path, "right", [("0.92", "0.22")] * 6)
    assert calls == ["sleep 10"] and record["duty_used_pct"] == 70


@needs_bash
def test_freeze_42s_second_correction_is_bounded_and_leaves_a_silent_machine_alone(tmp_path):
    calls, record = _recorrect(tmp_path, "absurd", [("0.0", "0.0")] * 6, duty="95")
    assert record["duty_used_pct"] == 100 and calls[-1].endswith("--cpu-load 100 --timeout 3600s")
    for name, rows in (("none", None), ("empty", []), ("garbled", [("x", "y")] * 6)):
        calls, record = _recorrect(tmp_path, name, rows)
        assert calls == ["sleep 10"] and record is None, name


def test_freeze_42s_second_correction_runs_only_where_asked_and_never_outlives_the_trial():
    """It starts only where the setup asks and a load is running, before the trial and so before
    the warm-up it must fall inside; and once the trial has ended it is stopped, so that a trial
    that ended early cannot have stress-ng restarted under the next run's setup."""
    code = (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    run = code.split("run_one () {", 1)[1]
    start = run.index('if [ -n "${LOAD_RECORRECT:-}" ] && [ -n "${stress_pid:-}" ]; then')
    assert run.index("began=$(date -u +%s)") < start < run.index("run_kafka_trial.sh")
    assert 'recorrect_load "$RUN_DIR" "$LOAD" "${adjusted:-$LOAD}" "$want_cpus" &' in run
    stop = run.index('if [ -n "$recorrect_pid" ]; then kill "$recorrect_pid" 2>/dev/null; '
                     'wait "$recorrect_pid" 2>/dev/null; fi')
    assert run.index("ended=$(date -u +%s)") < stop, "stopped once the trial has ended"
    assert "pkill -9 -x stress-ng" in run[stop:], "and before the run's own load is stopped"
    assert 'sleep "${RECORRECT_AFTER_S:-10}"' in code, "ten seconds, inside a 20 s warm-up"


# --- Freeze 43 (22 Oct 2026, plan version 46): what block U's pilot found, answered in the kit
# before any judged run (docs/results/under_load/README.md). The producer runs at real-time
# priority in every setup, the clients' collector is off or logged and the consumer samples its
# schedstat, each setup's duty is frozen from the pilot, the 50-a-second load runs in on and off
# blocks within each run, each run keeps its interrupt and scheduler facts, the brokers are primed
# before a campaign's first run, and the card's capture is pinned to eth0's own address.

#: The runner's seven new variables, in the order the row reader sets them.
FREEZE_43 = ("PRODUCER_PRIORITY", "GC_OFF", "GC_LOG", "SCHEDSTAT", "DUTY", "LOAD_BLOCKS",
             "RUN_FACTS")


def _campaign():
    return (KIT / "campaign.sh").read_text(encoding="utf-8").replace("\r\n", "\n")


def _function(name):
    """One of campaign.sh's functions, as the runner defines it."""
    head = "%s () {" % name
    return head + _campaign().split("\n" + head, 1)[1].split("\n}\n", 1)[0] + "\n}\n"


def _lines_from(first, last):
    """run_one's lines from `first` up to `last`."""
    run = _campaign().split("run_one () {", 1)[1]
    return first + run.split(first, 1)[1].split(last, 1)[0]


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else None


def test_freeze_43s_switches_reach_the_runner_and_a_row_without_them_sets_none():
    """A row's seven new settings become the runner's seven variables; a row of any earlier block
    names none of them and leaves all seven empty, so its run is launched exactly as before. The
    lateness limit is no variable of the runner's: run_integrity.py reads it from the queue row.
    And a frozen duty, or a load in blocks, is never corrected a second time."""
    asked = _row_reader_says({"producer_priority": True, "gc_off": True, "gc_log": True,
                              "schedstat": True, "duty_pct": 72, "load_blocks_s": 5,
                              "run_facts": True, "lateness_p99_ms": 10})
    assert [asked[name] for name in FREEZE_43] == ["1", "1", "1", "1", "72", "5", "1"]
    assert not [name for name in asked if "LATE" in name]
    for param, name in (("producer_priority", "PRODUCER_PRIORITY"), ("gc_off", "GC_OFF"),
                        ("gc_log", "GC_LOG"), ("schedstat", "SCHEDSTAT"),
                        ("run_facts", "RUN_FACTS")):
        alone = _row_reader_says({param: True})
        assert [found for found in FREEZE_43 if alone[found]] == [name], \
            "%s sets its own variable and no other" % param
    earlier = _row_reader_says({"broker_capture": True, "load_recorrect": True,
                                "so_timestamps": "sched", "so_journal": True})
    assert [earlier[name] for name in FREEZE_43] == [""] * 7
    assert earlier["LOAD_RECORRECT"] == "1", "freeze 42's second correction, as it was"
    for frozen in ({"duty_pct": 72}, {"load_blocks_s": 5}):
        assert _row_reader_says(dict(frozen, load_recorrect=True))["LOAD_RECORRECT"] == ""
    none = _row_reader_says({"duty_pct": 0, "load_blocks_s": 0})
    assert (none["DUTY"], none["LOAD_BLOCKS"]) == ("0", "0"), \
        "a value of none is handed on for the runner to refuse, not dropped for the default"


def _freeze_43_setup_says(tmp_path, **setting):
    """The REASON freeze 43's checks of a setup give, from their lines in run_one, run as the
    runner runs them, with an unset variable an error; empty when the setup can run as written."""
    block = _lines_from("  # Freeze 43 (22 Oct 2026): so does a setup that names one",
                        "  # Freeze 41 (15 Oct 2026): a setup that asks")
    script = "\n".join(["set -uo pipefail", "checks () {", block, "}", 'REASON=""', "checks",
                        'echo "REASON=$REASON"', ""])
    env = dict({"DUTY": "", "LOAD_BLOCKS": "", "LOAD": "70", "GC_OFF": "", "GC_LOG": "",
                "SCHEDSTAT": "", "CLIENT": ""}, **setting)
    path = Path(tempfile.mkdtemp(dir=str(tmp_path))) / "checks.sh"
    said = _run_script(path, script, env, capture_output=True, text=True, check=True).stdout
    return said.strip().rsplit("REASON=", 1)[1]


@needs_bash
@pytest.mark.parametrize("setting,said", [
    ({"DUTY": "0"}, 'duty_pct is a whole percentage from 1 to 100, not "0"'),
    ({"DUTY": "101"}, 'duty_pct is a whole percentage from 1 to 100, not "101"'),
    ({"DUTY": "1000"}, 'duty_pct is a whole percentage from 1 to 100, not "1000"'),
    ({"DUTY": "72.5"}, 'duty_pct is a whole percentage from 1 to 100, not "72.5"'),
    ({"DUTY": "072"}, 'duty_pct is a whole percentage from 1 to 100, not "072"'),
    ({"DUTY": "-5"}, 'duty_pct is a whole percentage from 1 to 100, not "-5"'),
    ({"LOAD_BLOCKS": "0"}, 'load_blocks_s is a whole number of seconds of at least one, not "0"'),
    ({"LOAD_BLOCKS": "5.0"},
     'load_blocks_s is a whole number of seconds of at least one, not "5.0"'),
    ({"LOAD_BLOCKS": "05"}, 'load_blocks_s is a whole number of seconds of at least one, not "05"'),
    ({"DUTY": "72", "LOAD": "0"},
     "duty_pct and load_blocks_s set how a load runs, and a load of 0 starts none"),
    ({"LOAD_BLOCKS": "5", "LOAD": "0"},
     "duty_pct and load_blocks_s set how a load runs, and a load of 0 starts none"),
    ({"GC_OFF": "1", "CLIENT": "java"},
     "gc_off, gc_log and schedstat are the Python clients' settings, and this run's client is java"),
    ({"GC_LOG": "1", "CLIENT": "java"},
     "gc_off, gc_log and schedstat are the Python clients' settings, and this run's client is java"),
    ({"SCHEDSTAT": "1", "CLIENT": "java"},
     "gc_off, gc_log and schedstat are the Python clients' settings, and this run's client is java")])
def test_a_freeze_43_setup_the_runner_cannot_give_fails_before_the_machine_is_touched(
        tmp_path, setting, said):
    """stress-ng takes a whole percentage and the blocks a whole number of seconds, so 72.5 or
    5.0 would be read by neither as the setup wrote it; a load of 0 starts no stress-ng for a duty
    or for blocks to apply to; and Kafka's Java client has no collector switch or schedstat."""
    assert _freeze_43_setup_says(tmp_path, **setting) == said


@needs_bash
@pytest.mark.parametrize("setting", [
    {}, {"DUTY": "1"}, {"DUTY": "9"}, {"DUTY": "10"}, {"DUTY": "77"}, {"DUTY": "100"},
    {"LOAD_BLOCKS": "5"}, {"LOAD_BLOCKS": "10"}, {"DUTY": "88", "LOAD_BLOCKS": "5"},
    {"GC_OFF": "1", "GC_LOG": "1", "SCHEDSTAT": "1"},
    {"GC_OFF": "1", "SCHEDSTAT": "1", "CLIENT": "python"}, {"LOAD": "0"}])
def test_and_a_freeze_43_setup_it_can_give_passes_those_checks(tmp_path, setting):
    assert _freeze_43_setup_says(tmp_path, **setting) == ""


@needs_bash
def test_freeze_43s_frozen_duty_is_not_corrected_and_blocks_start_no_load_before_the_clients(
        tmp_path):
    """A setup with a frozen duty starts stress-ng at that duty, makes no correction before the
    clients, and says so beside the run; a setup whose load runs in blocks starts none before the
    clients, whatever duty its blocks will run at; and every other setup starts its load at the
    design and corrects it as before."""
    runs = {name: tmp_path / name for name in ("frozen", "blocks", "blocks_at_load", "before")}
    for run in runs.values():
        run.mkdir()
    calls = _load_lines(runs["frozen"], 70, DUTY="77")
    assert [c for c in calls if c.startswith("stress-ng")] == [
        "stress-ng --cpu 8 --cpu-load 77 --timeout 3600s"]
    assert "python3 -c" not in calls, "no correction before the clients"
    assert json.loads((runs["frozen"] / "load_correction.json").read_text(encoding="utf-8")) == {
        "designed_pct": 70, "duty_frozen_pct": 77}
    calls = _load_lines(runs["blocks"], 88, DUTY="88", LOAD_BLOCKS="5")
    assert not [c for c in calls if c.startswith("stress-ng")] and "python3 -c" not in calls
    assert "python3 scripts/util_sampler.py" in calls, "the load is measured all the same"
    assert json.loads((runs["blocks"] / "load_correction.json").read_text(encoding="utf-8")) == {
        "designed_pct": 88, "duty_frozen_pct": 88}
    calls = _load_lines(runs["blocks_at_load"], 88, LOAD_BLOCKS="5")
    assert not [c for c in calls if c.startswith("stress-ng")]
    assert not (runs["blocks_at_load"] / "load_correction.json").exists()
    calls = _load_lines(runs["before"], 70)
    assert [c for c in calls if c.startswith("stress-ng")] == [
        "stress-ng --cpu 8 --cpu-load 70 --timeout 3600s"]
    assert "python3 -c" in calls, "and the correction is made as before"


def _load_blocks(tmp_path, looks, **given):
    """load_blocks as the runner defines it, run in the foreground, with stress-ng, sleep, pkill,
    kill and date stood in for by commands that write down how they were called, the clock a
    second further on at each reading, and the campaign that started the blocks alive for `looks`
    looks. (load_blocks.csv's lines, the calls, stress-ng's calls.)"""
    run = tmp_path / "run"
    run.mkdir(parents=True)
    calls, stress, clock = tmp_path / "calls.txt", tmp_path / "stress.txt", tmp_path / "clock"
    script = "\n".join([
        "set -uo pipefail", "looks=0",
        'kill () { if [ "$1" = -0 ]; then looks=$((looks + 1)); [ "$looks" -le "$LOOKS" ];'
        ' return; fi; echo "kill $1" >> "$CALLS"; }',
        'date () { local t; t=$(( $(cat "$CLOCK" 2>/dev/null || echo 0) + 1 ));'
        ' echo "$t" > "$CLOCK"; echo "${t}000000000"; }',
        'sleep () { echo "sleep $*" >> "$CALLS"; }', 'pkill () { echo "pkill $*" >> "$CALLS"; }',
        'stress-ng () { echo "stress-ng $*" >> "$STRESS"; }', _function("load_start"),
        _function("load_blocks"),
        'load_blocks "$RUN" "$DUTY" "$CPUS" "$BLOCK_S"', "builtin wait", ""])
    env = dict({"CALLS": calls.as_posix(), "STRESS": stress.as_posix(),
                "CLOCK": clock.as_posix(), "RUN": run.as_posix(), "LOOKS": str(looks),
                "DUTY": "88", "CPUS": "8", "BLOCK_S": "5"}, **given)
    _run_script(tmp_path / "blocks.sh", script, env, capture_output=True, text=True, check=True)
    return (_lines(run / "load_blocks.csv"), _lines(calls) or [], _lines(stress) or [])


@needs_bash
def test_freeze_43s_load_runs_in_blocks_on_then_off_and_writes_each_switch(tmp_path):
    """From the trial's start stress-ng runs for a block and stops for a block, beginning on, at
    the setup's duty on every online CPU, each switch written with the time it was made; each
    block's stress-ng is stopped by a signal it cannot decline, and would stop by itself at twice
    the block's length; and no block starts once the campaign that started them is gone."""
    blocks, calls, stress = _load_blocks(tmp_path / "two", 2)
    assert blocks == ["t_ns,state", "1000000000,on", "2000000000,off", "3000000000,on",
                      "4000000000,off"]
    assert stress == ["stress-ng --cpu 8 --cpu-load 88 --timeout 10s"] * 2
    assert calls == ["sleep 5", "kill -9", "pkill -9 -x stress-ng", "sleep 5"] * 2
    assert _load_blocks(tmp_path / "gone", 0) == (["t_ns,state"], [], [])


@needs_bash
def test_freeze_43s_blocks_are_stopped_by_a_signal_they_cannot_decline_then_their_load(tmp_path):
    """The blocks' own process first, so that it starts no stress-ng after the one stopped next,
    and then every stress-ng; with no blocks running, nothing is touched."""
    calls = tmp_path / "calls.txt"
    script = "\n".join([
        "set -uo pipefail", 'pkill () { echo "pkill $*" >> "$CALLS"; }',
        _function("stop_load_blocks"), 'BLOCKS_PID=""', "stop_load_blocks", 'echo "idle=$?"',
        "sleep 60 &", "BLOCKS_PID=$!", "blocks=$BLOCKS_PID", "stop_load_blocks",
        'if kill -0 "$blocks" 2>/dev/null; then echo "blocks=alive"; else echo "blocks=gone"; fi',
        'echo "left=[$BLOCKS_PID]"', ""])
    said = _run_script(tmp_path / "stop.sh", script, {"CALLS": calls.as_posix()},
                       capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL)
    assert said.stdout.split() == ["idle=0", "blocks=gone", "left=[]"]
    assert _lines(calls) == ["pkill -9 -x stress-ng"]


def test_freeze_43s_blocks_start_with_the_trial_and_never_outlive_it():
    """They start once the trial has started, and stop as soon as it ends, early or not, before
    the counters after the run are read; reap stops them before anything else, so that a run or
    a campaign stopped in the middle of such a run leaves none to start a stress-ng after its own
    is stopped; and the process id that lets it is declared before any function that reads it."""
    code = _campaign()
    run = code.split("run_one () {", 1)[1].split("\n}\n", 1)[0]
    start = run.index('load_blocks "$RUN_DIR" "${DUTY:-$LOAD}" "$want_cpus" "$LOAD_BLOCKS" &')
    assert run.index("began=$(date -u +%s)") < start < run.index("run_kafka_trial.sh")
    stop = run.index("\n  stop_load_blocks\n")
    assert run.index("ended=$(date -u +%s)") < stop \
        < run.index('head -n 1 /proc/stat > "$RUN_DIR/stat_after.txt"')
    reap = _function("reap")
    assert reap.index("stop_load_blocks") < reap.index("pkill -9 -x stress-ng")
    assert "reap\n" in _function("finish_campaign"), "a campaign stopped mid-run stops them too"
    assert 'BLOCKS_PID=""' in code.split("\nlog () {", 1)[0]


def _trial_starts(tmp_path, **setting):
    """What run_one starts and stops around the trial, from the trial's start to the counters
    after it, run as the runner runs it with an unset variable an error: the trial, the load's
    blocks, the clients' facts, the second correction and kill stood in for by commands that write
    down how they were called, each into a file of its own, the background ones with their own
    process ids. (Each file's lines, None where nothing was called.)"""
    rec = tmp_path / "rec"
    rec.mkdir(parents=True)
    block = _lines_from("  began=$(date -u +%s)",
                        '  head -n 1 /proc/stat > "$RUN_DIR/stat_after.txt"')
    script = "\n".join([
        "set -uo pipefail",
        'timeout () { printf "%s\\n" "$@" > "$REC/trial"; printf "%s\\n"'
        ' "consumer=$SBL_CONSUMER_WRAP" "sched=$SBL_SCHED_WRAP" "producer=$SBL_PRODUCER_WRAP"'
        ' > "$REC/wraps"; printf "%s\\n" "arrival=${SBL_PLAN_ARRIVAL:-}" "seed=${SBL_PLAN_SEED:-}"'
        ' "wait=${SBL_THREADS_WAIT_S:-}" "priority=${SBL_FETCH_RT_PRIORITY:-}" > "$REC/plan"; }',
        'load_blocks () { echo "$BASHPID $*" > "$REC/blocks"; }',
        'run_facts_later () { echo "$BASHPID $*" > "$REC/facts"; }',
        'recorrect_load () { echo "$BASHPID $*" > "$REC/recorrect"; }',
        'stop_load_blocks () { echo "BLOCKS_PID=$BLOCKS_PID" >> "$REC/stops"; BLOCKS_PID=""; }',
        'kill () { echo "kill $*" >> "$REC/kills"; }',
        "trial () {", '  local rc began ended stress_pid="" adjusted=""', block, "}",
        'BLOCKS_PID=""', "trial", "builtin wait", ""])
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    so = "--so-timestamps %s/%%s_so.csv --so-transmit sched" % run_dir.as_posix()
    env = dict({"REC": rec.as_posix(), "RUN_DIR": run_dir.as_posix(), "RUN_ID": "law_u50_r001",
                "BACKEND": "kafka", "LOAD": "70", "want_cpus": "8", "DUTY": "", "LOAD_BLOCKS": "",
                "RUN_FACTS": "", "LOAD_RECORRECT": "", "CLIENT": "", "ACK_STAMP": "",
                "DURATION": "70", "run_plan": "plan.csv", "run_speedup": "1", "run_maxt": "70",
                "KAFKA_BOOTSTRAP": "10.9.9.9:19092", "KAFKA_PRODUCER_EXTRA": "--max-inflight 64",
                "REDIS_HOST": "10.9.9.9", "REDIS_PORT": "6379",
                "REDIS_CONSUMER_EXTRA": "--ack-batch 200", "ACK_BATCH": "", "SEND_WORKERS": "",
                "record_args": "", "read_args": "", "so_prod": so % "producer",
                "so_cons": so % "consumer",
                "consumer_wrap": "sudo ip netns exec sblrecv sudo -u tester", "wrap_sched": "",
                "producer_wrap": "", "prod_flags": "", "cons_flags": "",
                # Plan version 47 (23 Oct 2026): the plan's arrivals, the values set in one
                # place, and the new brokers' addresses.
                "run_arrival": "constant", "run_seed": "", "THREADS_WAIT_S": "60",
                "FETCH_RT_PRIORITY": "80", "NATS_HOST": "10.9.9.9", "NATS_PORT": "4222",
                "NATS_STORAGE": "memory", "RABBITMQ_URI": "amqp://guest:guest@10.9.9.9:5672"},
               **setting)
    _run_script(tmp_path / "trial.sh", script, env, capture_output=True, text=True, check=True)
    found = {name: _lines(rec / name)
             for name in ("trial", "wraps", "blocks", "facts", "recorrect", "stops", "kills",
                          "plan")}
    found["run_dir"], found["so"] = run_dir.as_posix(), so
    return found


@needs_bash
def test_freeze_43s_producer_wrap_and_client_flags_reach_the_trial_runner(tmp_path):
    """The producer's own wrap is handed to the trial runner beside the other two, and the
    clients' flags follow everything each client was handed before, on either broker. A setup
    that asks for none hands the runner an empty wrap and exactly what freeze 42 did."""
    prod = " --gc-off --gc-log runs/law_u50_r001/producer_gc.json"
    cons = (" --gc-off --gc-log runs/law_u50_r001/consumer_gc.json"
            " --schedstat runs/law_u50_r001/consumer_schedstat.csv")
    for backend in ("kafka", "redis"):
        found = _trial_starts(tmp_path / backend, BACKEND=backend,
                              producer_wrap="sudo chrt -f 80", prod_flags=prod, cons_flags=cons)
        trial, so = found["trial"], found["so"]
        assert "scripts/run_%s_trial.sh" % backend in trial
        assert found["wraps"] == ["consumer=sudo ip netns exec sblrecv sudo -u tester", "sched=",
                                  "producer=sudo chrt -f 80"]
        assert trial[trial.index("-PRODUCER_EXTRA") + 1].endswith(" " + so % "producer" + prod)
        assert trial[trial.index("-CONSUMER_EXTRA") + 1].endswith(" " + so % "consumer" + cons)
    plain = _trial_starts(tmp_path / "plain")
    assert plain["wraps"][2] == "producer="
    trial = plain["trial"]
    assert trial[trial.index("-PRODUCER_EXTRA") + 1] == "--max-inflight 64  " + plain["so"] % (
        "producer")
    assert trial[trial.index("-CONSUMER_EXTRA") + 1] == "  " + plain["so"] % "consumer"


@needs_bash
def test_freeze_43s_blocks_and_facts_start_with_the_trial_and_are_stopped_when_it_ends(tmp_path):
    """The blocks run at the frozen duty where the setup names one and at the design otherwise,
    on every online CPU, for the setup's block; the clients' facts are read in the background,
    and that reading is stopped once the trial ends; a setup that asks for neither starts
    neither, and the stop finds nothing to stop."""
    found = _trial_starts(tmp_path / "u50", LOAD="88", DUTY="91", LOAD_BLOCKS="5", RUN_FACTS="1")
    blocks_pid, blocks = found["blocks"][0].split(" ", 1)
    assert blocks == "%s 91 8 5" % found["run_dir"]
    facts_pid, facts = found["facts"][0].split(" ", 1)
    assert facts == found["run_dir"] and blocks_pid != facts_pid
    assert found["stops"] == ["BLOCKS_PID=%s" % blocks_pid], "the blocks' own process is stopped"
    assert found["kills"] == ["kill %s" % facts_pid], "the facts' reading, and nothing else"
    assert found["recorrect"] is None
    at_load = _trial_starts(tmp_path / "at_load", LOAD="88", LOAD_BLOCKS="5")
    assert at_load["blocks"][0].split(" ", 1)[1] == "%s 88 8 5" % at_load["run_dir"]
    assert at_load["facts"] is None and at_load["kills"] is None
    neither = _trial_starts(tmp_path / "neither")
    assert (neither["blocks"], neither["facts"], neither["kills"]) == (None, None, None)
    assert neither["stops"] == ["BLOCKS_PID="], "asked to stop, with nothing to stop"


def _producer_wrap(tmp_path, **setting):
    block = _lines_from("  # Freeze 43 (22 Oct 2026): the producer alone at real-time priority",
                        "  # Freeze 41 (15 Oct 2026): a 32 MiB capture buffer")
    script = "\n".join(["set -uo pipefail", "wraps () {", block,
                        '  echo "producer=$producer_wrap"', "}", "wraps", ""])
    env = dict({"PRIORITY": "", "PRODUCER_PRIORITY": ""}, **setting)
    path = Path(tempfile.mkdtemp(dir=str(tmp_path))) / "wraps.sh"
    said = _run_script(path, script, env, capture_output=True, text=True, check=True).stdout
    return said.strip().split("=", 1)[1]


@needs_bash
def test_freeze_43s_producer_alone_goes_first_where_asked_and_go_first_already_raises_both(
        tmp_path):
    """With the producer at real-time priority in every setup of the block, only the consumer's
    priority varies between them. Where go-first already raises both clients, the producer's own
    wrap stays empty, so the producer is not raised twice."""
    assert _producer_wrap(tmp_path, PRODUCER_PRIORITY="1") == "sudo chrt -f 80"
    assert _producer_wrap(tmp_path, PRODUCER_PRIORITY="1", PRIORITY="1") == ""
    assert _producer_wrap(tmp_path) == ""
    assert _producer_wrap(tmp_path, PRIORITY="1") == ""


def _client_flags(tmp_path, **setting):
    block = _lines_from("  # Freeze 43 (22 Oct 2026): the clients' own garbage collector",
                        "  began=$(date -u +%s)")
    script = "\n".join(["set -uo pipefail", "flags () {", block, '  echo "producer=$prod_flags"',
                        '  echo "consumer=$cons_flags"', "}", "flags", ""])
    env = dict({"RUN_DIR": "runs/law_u50_r001"}, **setting)
    path = Path(tempfile.mkdtemp(dir=str(tmp_path))) / "flags.sh"
    said = _run_script(path, script, env, capture_output=True, text=True, check=True).stdout
    return dict(line.split("=", 1) for line in said.splitlines())


@needs_bash
def test_freeze_43s_client_flags_reach_the_clients_that_take_them(tmp_path):
    """gc_off turns both clients' collector off and logs what still runs, each into its own file;
    gc_log logs without turning it off; schedstat is the consumer's alone; a setup that asks for
    none hands the clients nothing new."""
    gc = " --gc-log runs/law_u50_r001/%s_gc.json"
    sched = " --schedstat runs/law_u50_r001/consumer_schedstat.csv"
    assert _client_flags(tmp_path) == {"producer": "", "consumer": ""}
    off = {"producer": " --gc-off" + gc % "producer", "consumer": " --gc-off" + gc % "consumer"}
    assert _client_flags(tmp_path, GC_OFF="1") == off
    assert _client_flags(tmp_path, GC_OFF="1", GC_LOG="1") == off
    assert _client_flags(tmp_path, GC_LOG="1") == {"producer": gc % "producer",
                                                   "consumer": gc % "consumer"}
    assert _client_flags(tmp_path, SCHEDSTAT="1") == {"producer": "", "consumer": sched}
    assert _client_flags(tmp_path, GC_OFF="1", SCHEDSTAT="1") == {
        "producer": off["producer"], "consumer": off["consumer"] + sched}


#: A driver with a second accelerated device, listed first and carrying an address of its own,
#: beside the one that carries eth0's address.
TWO_CARDS = ("eth0             UP             60:45:bd:e9:60:ba <BROADCAST,MULTICAST,UP,LOWER_UP> \n"
             "enP11111s1       UP             00:22:48:aa:bb:cc "
             "<BROADCAST,MULTICAST,SLAVE,UP,LOWER_UP> \n"
             "enP58460s1       UP             60:45:bd:e9:60:ba "
             "<BROADCAST,MULTICAST,SLAVE,UP,LOWER_UP> ")


@needs_bash
def test_freeze_43s_card_capture_is_pinned_to_eth0s_own_address(tmp_path):
    """Until freeze 43 the first SLAVE `ip -br link` listed was taken. Now it is the SLAVE that
    carries eth0's address as the kernel gives it, in whatever case; where none carries it, or
    eth0's address cannot be read, nothing is captured, as on a machine with no card."""
    _, calls = _r1_runner(tmp_path, "pinned", HW_CAPTURE="1", FAKE_LINK=TWO_CARDS, FAKE_PHC="1")
    started = [c for c in calls if "pkill" not in c]
    assert started[0] == "sudo ethtool -T enP58460s1"
    assert started[1].startswith("sudo tcpdump -i enP58460s1 -j adapter_unsynced ")
    shown = (tmp_path / "pinned" / "hw_device.txt").read_text(encoding="utf-8").split()
    assert shown == ["enP58460s1", "/dev/ptp1"]
    upper = _write(tmp_path / "upper_address", "60:45:BD:E9:60:BA\n")
    _r1_runner(tmp_path, "upper", HW_CAPTURE="1", FAKE_LINK=TWO_CARDS, FAKE_PHC="1",
               ETH0_ADDRESS=upper.as_posix())
    shown = (tmp_path / "upper" / "hw_device.txt").read_text(encoding="utf-8").split()
    assert shown == ["enP58460s1", "/dev/ptp1"]
    another = TWO_CARDS.rsplit("\n", 1)[0]
    for name, links, given in (("another", another, {}),
                               ("unread", TWO_CARDS,
                                {"ETH0_ADDRESS": (tmp_path / "no_address").as_posix()})):
        _, calls = _r1_runner(tmp_path, name, HW_CAPTURE="1", FAKE_LINK=links, FAKE_PHC="1",
                              **given)
        assert not [c for c in calls if "tcpdump" in c or "ethtool" in c], name
        shown = (tmp_path / name / "hw_device.txt").read_text(encoding="utf-8").split()
        assert shown == ["none", "none"], name


def _trial_runner_calls(tmp_path, runner, producer_wrap, sched_wrap=""):
    """scripts/RUNNER run in a scratch folder: its Python stands in for each client by writing
    down how it was called, except where it runs the runner's own record of the run from stdin,
    and SBL_SCHED_WRAP and SBL_PRODUCER_WRAP name wraps that write down how they were called and
    then run what they wrap. (The calls, the env meta.json records.)"""
    work = tmp_path / runner
    stubs, calls = work / "bin", work / "calls.txt"
    python = Path(sys.executable).as_posix()
    for name, body in (
            ("py", 'if [ "$1" = - ]; then exec "%s" "$@"; fi\necho "python $*" >> "$CALLS"\n'
             % python),
            ("schedwrap", 'echo "schedwrap $*" >> "$CALLS"\nexec "$@"\n'),
            ("prodwrap", 'echo "prodwrap $*" >> "$CALLS"\nexec "$@"\n'),
            ("sleep", ":\n"), ("redis-cli", ":\n")):
        os.chmod(_write(stubs / name, "#!/bin/sh\n" + body), 0o755)
    done = bash([(REPO / "scripts" / runner).as_posix(), "r001", "plan.csv", "1", "10"],
                cwd=work, path_first=[stubs],
                extra_env={"PYTHON": (stubs / "py").as_posix(), "CALLS": calls.as_posix(),
                           "SBL_SCHED_WRAP": sched_wrap, "SBL_PRODUCER_WRAP": producer_wrap,
                           "SBL_CONSUMER_WRAP": ""},
                capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stdout + done.stderr
    meta = json.loads((work / "runs" / "r001" / "meta.json").read_text(encoding="utf-8"))
    return _lines(calls), meta["env"]


@needs_bash
@pytest.mark.parametrize("runner,producer,consumer", [
    ("run_kafka_trial.sh", "scripts/kafka_producer.py", "scripts/kafka_consumer.py"),
    ("run_redis_trial.sh", "scripts/redis_producer.py", "scripts/redis_consumer.py")])
def test_freeze_43s_producer_wrap_prefixes_the_producer_alone_after_the_sched_wrap(
        tmp_path, runner, producer, consumer):
    """SBL_PRODUCER_WRAP prefixes the producer's command and nothing else, after SBL_SCHED_WRAP,
    and meta.json's env records it, so that a run's own files say which arm it belonged to.
    Empty, it adds nothing, and the producer starts exactly as before."""
    calls, env = _trial_runner_calls(tmp_path / "alone", runner, "prodwrap")
    wrapped = [c for c in calls if c.startswith("prodwrap ")]
    assert len(wrapped) == 1 and producer in wrapped[0], calls
    assert [c for c in calls if c.startswith("python " + consumer)], "the consumer, unwrapped"
    assert [c for c in calls if c.startswith("python scripts/compute_tti.py")]
    assert env["SBL_PRODUCER_WRAP"] == "prodwrap"
    calls, env = _trial_runner_calls(tmp_path / "both", runner, "prodwrap", "schedwrap")
    sched = [c for c in calls if c.startswith("schedwrap ")]
    assert [c.split()[1] for c in sched if producer in c] == ["prodwrap"], \
        "the producer's own wrap comes after the one both clients share"
    assert [c for c in sched if consumer in c and "prodwrap" not in c]
    assert [c for c in calls if c.startswith("prodwrap ")] and not [
        c for c in calls if c.startswith("prodwrap ") and producer not in c]
    assert (env["SBL_SCHED_WRAP"], env["SBL_PRODUCER_WRAP"]) == ("schedwrap", "prodwrap")
    calls, env = _trial_runner_calls(tmp_path / "plain", runner, "")
    assert not [c for c in calls if "prodwrap" in c] and env["SBL_PRODUCER_WRAP"] == ""
    assert [c for c in calls if c.startswith("python " + producer)]


def test_freeze_43s_producer_wrap_reaches_the_java_producer_too_and_no_consumer():
    """A8's Java producer is wrapped as the Python one is, and no line that starts a consumer
    carries the producer's wrap, in either runner."""
    for runner in ("run_kafka_trial.sh", "run_redis_trial.sh"):
        text = (REPO / "scripts" / runner).read_text(encoding="utf-8")
        assert 'PRODUCER_WRAP="${SBL_PRODUCER_WRAP:-}"' in text
        assert '"SBL_PRODUCER_WRAP": os.environ.get("SBL_PRODUCER_WRAP", "")' in text
        wrapped = [line.strip() for line in text.splitlines()
                   if "$PRODUCER_WRAP" in line and not line.lstrip().startswith("#")]
        assert wrapped and all(line.startswith("$SCHED_WRAP $PRODUCER_WRAP ") for line in wrapped)
        assert not [line for line in wrapped if "onsumer" in line]
    kafka = (REPO / "scripts" / "run_kafka_trial.sh").read_text(encoding="utf-8")
    assert '  $SCHED_WRAP $PRODUCER_WRAP "$JAVA_BIN" -cp "$JAVA_CP" LawProducer \\' in kafka


@needs_bash
def test_freeze_43s_clients_facts_are_read_once_while_the_clients_run(tmp_path):
    """RUN_FACTS_AFTER_S into the trial, 15 s unless set, inside block U's 20 s warm-up."""
    run = tmp_path / "run"
    run.mkdir()
    for after, slept in (("", "15"), ("3", "3")):
        calls = tmp_path / ("calls_%s.txt" % slept)
        script = "\n".join(['sleep () { echo "sleep $*" >> "$CALLS"; }',
                            'python3 () { echo "python3 $*" >> "$CALLS"; }',
                            _function("run_facts_later"), 'run_facts_later "$RUN"', ""])
        env = {"CALLS": calls.as_posix(), "RUN": run.as_posix()}
        if after:
            env["RUN_FACTS_AFTER_S"] = after
        _run_script(tmp_path / ("facts_%s.sh" % slept), script, env, capture_output=True,
                    text=True, check=True)
        assert _lines(calls) == ["sleep " + slept, "python3 scripts/run_facts.py clients --out "
                                 "%s/run_facts_clients.json" % run.as_posix()]


@needs_bash
def test_freeze_43s_interrupt_counters_are_the_kernels_own_before_and_after(tmp_path):
    """/proc/interrupts, /proc/softirqs and /proc/net/softnet_stat, copied as they are, before
    and after; a file that cannot be read leaves the reason in its place and stops nothing."""
    proc, run = tmp_path / "proc", tmp_path / "run"
    run.mkdir()
    texts = {"interrupts": "           CPU0       CPU1\n 24:   5   7   mlx5_comp0@pci\n",
             "softirqs": "                    CPU0       CPU1\n      NET_RX:     11     13\n",
             "net/softnet_stat": "0000abcd 00000000 00000001\n0000beef 00000000 00000000\n"}
    for name, text in texts.items():
        _write(proc / name, text)
    script = "\n".join(["set -uo pipefail", _function("interrupt_counters"),
                        "interrupt_counters before", 'rm "$PROC_DIR/softirqs"',
                        "interrupt_counters after", 'echo "carried on"', ""])
    said = _run_script(tmp_path / "counters.sh", script,
                       {"PROC_DIR": proc.as_posix(), "RUN_DIR": run.as_posix()},
                       capture_output=True, text=True, check=True).stdout
    assert said == "carried on\n"
    for name, saved in (("interrupts", "interrupts"), ("softirqs", "softirqs"),
                        ("net/softnet_stat", "softnet")):
        assert (run / ("%s_before.txt" % saved)).read_text(encoding="utf-8") == texts[name]
    assert (run / "interrupts_after.txt").read_text(encoding="utf-8") == texts["interrupts"]
    assert "softirqs" in (run / "softirqs_after.txt").read_text(encoding="utf-8")


def test_freeze_43s_run_facts_are_taken_before_the_clients_while_they_run_and_after():
    """The machine's facts and the interrupt counters once every capture has started and before
    the clients do; the clients' facts in the background once the trial has started; and the
    counters again once it has ended. A setup that asks for none of it takes none."""
    run = _campaign().split("run_one () {", 1)[1].split("\n}\n", 1)[0]
    order = ['remote_broker "sudo sh -c \'kill -INT \\$(cat /dev/shm/sbl_bfull.pid',
             "tcp_counters before", "interrupt_counters before",
             'python3 scripts/run_facts.py host --out "$RUN_DIR/run_facts.json"',
             "began=$(date -u +%s)", 'run_facts_later "$RUN_DIR" &', "run_kafka_trial.sh",
             "ended=$(date -u +%s)", 'if [ -n "$facts_pid" ]; then kill "$facts_pid"',
             "tcp_counters after", '[ -z "${RUN_FACTS:-}" ] || interrupt_counters after']
    places = [run.index(step) for step in order]
    assert places == sorted(places)
    assert 'if [ -n "${RUN_FACTS:-}" ]; then\n    interrupt_counters before' in run
    assert 'if [ -n "${RUN_FACTS:-}${WHOLE_CORE:-}" ]; then\n    run_facts_later "$RUN_DIR" &' in run


def _prime(tmp_path, rc_kafka="0", rc_redis="0"):
    """prime_brokers as the runner defines it, run in a scratch folder, with reap, log, date and
    the trials stood in for by commands that write down how they were called, the n-th trial's
    arguments and wraps into files of their own. (The calls, the trials' arguments, their wraps,
    the folder they ran in.)"""
    work, rec = tmp_path / "work", tmp_path / "rec"
    work.mkdir()
    rec.mkdir()
    script = "\n".join([
        "set -uo pipefail", "trials=0",
        'reap () { echo reap >> "$REC/calls"; }', 'log () { echo "LOG $*" >> "$REC/calls"; }',
        "date () { echo 20261023T010203Z; }",
        'timeout () { trials=$((trials + 1)); printf "%s\\n" "$@" > "$REC/trial_$trials";'
        ' printf "%s\\n" "consumer=${SBL_CONSUMER_WRAP:-}" "sched=${SBL_SCHED_WRAP:-}"'
        ' "producer=${SBL_PRODUCER_WRAP:-}" > "$REC/wraps_$trials"; echo "trial $trials";'
        ' [ "$trials" = 1 ] && return "$RC_KAFKA"; return "$RC_REDIS"; }',
        _function("prime_brokers"), "prime_brokers", ""])
    env = {"REC": rec.as_posix(), "RC_KAFKA": rc_kafka, "RC_REDIS": rc_redis,
           "QUEUE_NAME": "u50", "ME": "tester", "PRIME_S": "60",
           "SYN_PLAN": "data/synthetic/constant_r50_d70/replay_plan.csv", "SPEEDUP": "1.000000",
           "KAFKA_BOOTSTRAP": "10.9.9.9:19092", "KAFKA_PRODUCER_EXTRA": "--max-inflight 64",
           "REDIS_HOST": "10.9.9.9", "REDIS_PORT": "6379",
           "REDIS_CONSUMER_EXTRA": "--ack-batch 200"}
    _run_script(tmp_path / "prime.sh", script, env, cwd=work, capture_output=True, text=True,
                check=True)
    return (_lines(rec / "calls"), [_lines(rec / ("trial_%d" % n)) for n in (1, 2)],
            [_lines(rec / ("wraps_%d" % n)) for n in (1, 2)], work)


@needs_bash
def test_freeze_43s_brokers_are_primed_kafka_then_redis_idle_into_folders_nothing_reads(
        tmp_path):
    """One trial on each broker, Kafka first, on the campaign's plan at its speed for PRIME_S
    seconds, with the consumer behind the receiver's address and the clients' standing settings,
    no other wrap and no capture; each into a folder of its own named for the queue, the broker
    and the time, its log beside it; and the campaign carries on whatever a trial exits with."""
    calls, trials, wraps, work = _prime(tmp_path, rc_redis="3")
    kafka, redis = ("law_u50_prime_%s_20261023T010203Z" % b for b in ("kafka", "redis"))
    assert calls == ["reap", "LOG PRIME kafka: runs/%s exit 0" % kafka,
                     "reap", "LOG PRIME redis: runs/%s exit 3" % redis]
    plan = "data/synthetic/constant_r50_d70/replay_plan.csv"
    assert trials[0] == ["-k", "30", "360", "bash", "scripts/run_kafka_trial.sh", kafka, plan,
                         "1.000000", "60", "-BOOTSTRAP", "10.9.9.9:19092", "-PRODUCER_EXTRA",
                         "--max-inflight 64", "-IDLE_SECONDS", "15"]
    assert trials[1] == ["-k", "30", "360", "bash", "scripts/run_redis_trial.sh", redis, plan,
                         "1.000000", "60", "-RedisHost", "10.9.9.9", "-PORT", "6379",
                         "-CONSUMER_EXTRA", "--ack-batch 200", "-IDLE_SECONDS", "15"]
    assert wraps == [["consumer=sudo ip netns exec sblrecv sudo -u tester", "sched=",
                      "producer="]] * 2
    for n, run_id in enumerate((kafka, redis), start=1):
        assert _lines(work / "runs" / run_id / "trial.log") == ["trial %d" % n]


def _prime_s_says(prime_s, duration="70"):
    code = _campaign()
    first = "# Freeze 43 (22 Oct 2026): the priming trials replay"
    block = first + code.split(first, 1)[1].split("\nesac\n", 1)[0] + "\nesac\n"
    script = "\n".join(["set -uo pipefail", 'log () { echo "$*"; }', block, 'echo "carried on"',
                        ""])
    return bash(["-c", script], extra_env={"PRIME_S": prime_s, "DURATION": duration},
                capture_output=True, text=True)


@needs_bash
@pytest.mark.parametrize("prime_s,said", [
    ("", None), ("1", None), ("60", None), ("70", None),
    ("71", "FATAL: PRIME_S is at most the plan's 70 s, not 71"),
    ("0", 'FATAL: PRIME_S is a whole number of seconds of at least one, not "0"'),
    ("060", 'FATAL: PRIME_S is a whole number of seconds of at least one, not "060"'),
    ("6O", 'FATAL: PRIME_S is a whole number of seconds of at least one, not "6O"'),
    ("1.5", 'FATAL: PRIME_S is a whole number of seconds of at least one, not "1.5"'),
    ("-1", 'FATAL: PRIME_S is a whole number of seconds of at least one, not "-1"')])
def test_freeze_43s_priming_is_a_whole_number_of_seconds_the_plan_holds(prime_s, said):
    """The priming trials replay the campaign's own plan, DURATION seconds of it, so a priming
    longer than that, or one in no whole number of seconds, stops the campaign before its first
    run rather than priming for some other time."""
    done = _prime_s_says(prime_s)
    if said is None:
        assert done.returncode == 0 and done.stdout == "carried on\n"
    else:
        assert done.returncode == 1 and done.stdout == said + "\n"


def test_freeze_43s_brokers_are_primed_once_before_the_queues_first_run_and_only_when_asked():
    """After the campaign's settings are checked and its line is logged, before the queue is
    first read; and a campaign without PRIME_S primes nothing and logs the line it always did."""
    code = _campaign()
    assert 'PRIME_S="${PRIME_S:-}"' in code
    queue = code.split("# --- the queue ", 1)[1]
    order = ['case "$GOTIT_BRAKE" in', 'case "$PRIME_S" in', 'log "campaign: ',
             '[ -z "$PRIME_S" ] || prime_brokers', 'RECOVER="--recover"', "\nwhile true; do"]
    places = [queue.index(step) for step in order]
    assert places == sorted(places)
    assert queue.count("prime_brokers") == 1, "called once, and nowhere in the loop"
    assert "${PRIME_S:+; each broker primed for $PRIME_S s first}" in code


@needs_bash
def test_freeze_43s_run_line_names_each_new_switch_and_an_earlier_row_none(tmp_path):
    """The line every run logs names each of freeze 43's switches where the row sets it, in the
    style of the earlier ones, and a row that sets none logs the line it always did."""
    line = next(text.strip() for text in _campaign().splitlines()
                if text.strip().startswith('log "run $KEY: '))
    names = ("KEY", "BACKEND", "LOAD", "SLICE_NS", "DELAY_MS", "PRIORITY", "CONSUMER_PRIORITY",
             "RECV_CAPTURE", "SEND_CAPTURE", "HW_CAPTURE", "SO_STAMPS", "SO_JOURNAL",
             "SEND_CAPTURE_BOTH", "SEND_WORKERS", "SCHED_FEATURES", "IDLE_POLL", "BROKER_CAPTURE",
             "LOAD_RECORRECT", "CPUS") + FREEZE_43
    row = dict({name: "" for name in names}, KEY="r001-U50-redis-l88-blocks-a1",
               BACKEND="redis", LOAD="88", DELAY_MS="0")
    script = "\n".join(["set -uo pipefail", 'log () { echo "$*"; }', line, ""])
    plain = _run_script(tmp_path / "plain.sh", script, row, capture_output=True, text=True,
                        check=True).stdout.strip()
    assert plain == ("run r001-U50-redis-l88-blocks-a1: redis, load 88%, slice kernel default, "
                     "delay 0 ms")
    asked = dict(row, PRODUCER_PRIORITY="1", GC_OFF="1", GC_LOG="1", SCHEDSTAT="1", DUTY="88",
                 LOAD_BLOCKS="5", RUN_FACTS="1", CPUS="8")
    asked = _run_script(tmp_path / "asked.sh", script, asked, capture_output=True, text=True,
                        check=True).stdout.strip()
    assert asked == plain + (", go-first producer, collectors off, collections logged, consumer "
                             "schedstat, duty frozen at 88%, load in 5 s blocks, run facts, "
                             "8 CPUs online")


# --- Plan version 47 (23 Oct 2026): the general method's blocks (V, N, P, K, C, A, S). What they
# ask of the kit beyond freeze 43's: two more brokers, a consumer of each block's own, the fetch
# threads at real-time priority, Poisson arrivals, a core kept for the consumer, the card's
# interrupts and receive steering placed, and two loads heavy in softirq work.

#: The runner's twelve new variables, in the order the row reader sets them.
V47 = ("CONSUMER", "DEPTH", "ONE_REPLY", "PREFETCH", "FETCH_RT", "ARRIVAL", "WHOLE_CORE",
       "SIBLING_LOAD", "IRQ_CPUS", "IRQBALANCE_OFF", "RPS_OFF", "LOAD_KIND")


def test_v47s_fields_reach_the_runner_and_a_row_without_them_sets_none():
    """A row's twelve new settings become the runner's twelve variables; a row of any earlier
    block names none of them and leaves all twelve empty, so its run is launched exactly as before;
    and a value of none is handed on for the runner to refuse, not dropped for a default."""
    asked = _row_reader_says({"backend": "kafka", "consumer": "confluent", "depth": 256,
                              "one_reply_reads": True, "prefetch": 1000, "fetch_rt": True,
                              "arrival": "poisson", "whole_core": True, "sibling_load": True,
                              "irq_cpus": "core", "irqbalance_off": True, "rps_off": True,
                              "load_kind": "udp"})
    assert [asked[name] for name in V47] == ["confluent", "256", "1", "1000", "1", "poisson", "1",
                                             "1", "core", "1", "1", "udp"]
    earlier = _row_reader_says({"broker_capture": True, "duty_pct": 72, "load_blocks_s": 5,
                                "producer_priority": True, "ack_batch": 200})
    assert [earlier[name] for name in V47] == [""] * 12
    assert earlier["ACK_BATCH"] == "200", "M0's batch, as it was"
    none = _row_reader_says({"depth": 0, "prefetch": 0, "ack_batch": 0, "irq_cpus": 3})
    assert (none["DEPTH"], none["PREFETCH"], none["ACK_BATCH"], none["IRQ_CPUS"]) == (
        "0", "0", "0", "3")


def test_v47s_setup_ids_are_queue_keys_the_runner_and_its_rules_read():
    """Setup ids such as V2000-redis-d256 and C2000-kafka-core-sib-pilot make keys whose round,
    setup and attempt the integrity rule reads back, and a failed attempt's copy keeps its setup."""
    sys.path.insert(0, str(REPO / "scripts"))
    import run_integrity
    import run_queue
    ids = ["V2000-redis-d256", "K2000-kafka-rdk-rt", "C2000-kafka-core-sib",
           "C2000-kafka-core-sib-pilot", "N2000-nats-d256-pilot"]
    design = {"seed": 20261023, "rounds": 2, "setups": [
        {"id": i, "backend": "redis", "load_pct": 70, "delay_ms": 0} for i in ids]}
    rows = run_queue.make_rows(design)
    for row in rows:
        assert run_integrity.setup_of(row["key"]) == (int(row["round"]), row["setup"], 1)
    copy = run_queue.fail(rows, rows[0]["key"], "a reason", clock=lambda: "2026-10-23T00:00:00Z")
    assert run_integrity.setup_of(copy["key"]) == (1, rows[0]["setup"], 2)


def _v47_setup_says(tmp_path, **setting):
    """The REASON plan version 47's checks of a setup give, from their lines in run_one, run as
    the runner runs them, from the checkout, with an unset variable an error; empty when the
    setup can run as written."""
    block = _lines_from("  # Plan version 47 (23 Oct 2026): so does a setup that names one of",
                        "  # Freeze 43 (22 Oct 2026): so does a setup that names one")
    script = "\n".join(["set -uo pipefail", "checks () {", block, "}", 'REASON=""', "checks",
                        'echo "REASON=$REASON"', ""])
    env = dict({"BACKEND": "kafka", "LOAD": "70", "PLAN_KIND": ""}, **setting)
    path = Path(tempfile.mkdtemp(dir=str(tmp_path))) / "checks.sh"
    said = _run_script(path, script, env, capture_output=True, text=True, check=True,
                       cwd=str(REPO)).stdout
    return said.strip().rsplit("REASON=", 1)[1]


@needs_bash
@pytest.mark.parametrize("setting,said", [
    ({"BACKEND": "pulsar"}, 'backend is kafka, redis, nats or rabbitmq, not "pulsar"'),
    ({"BACKEND": "redis", "CONSUMER": "confluent"},
     "consumer confluent is one of Kafka's consumers, and this run is redis"),
    ({"CONSUMER": "waiting"}, "consumer waiting is one of Redis's consumers, and this run is kafka"),
    ({"BACKEND": "rabbitmq", "CONSUMER": "nats-go"},
     "consumer nats-go is one of NATS's consumers, and this run is rabbitmq"),
    ({"CONSUMER": "librdkafka"}, "consumer is kafka-python, confluent, java or franz for Kafka"),
    ({"CONSUMER": "java", "CLIENT": "java"},
     "consumer swaps Kafka's consumer alone and language both clients"),
    ({"BACKEND": "redis", "DEPTH": "256"}, "depth is the waiting consumers' setting"),
    ({"BACKEND": "nats", "CONSUMER": "nats-go", "DEPTH": "256"},
     "depth is the waiting consumers' setting"),
    ({"BACKEND": "nats", "DEPTH": "0"}, 'depth is a whole number of requests of at least one, not "0"'),
    ({"BACKEND": "nats", "DEPTH": "064"}, 'depth is a whole number of requests of at least one'),
    ({"BACKEND": "redis", "ONE_REPLY": "1"}, "one_reply_reads is the waiting consumers' setting"),
    ({"BACKEND": "nats", "CONSUMER": "nats-go", "ONE_REPLY": "1"},
     "one_reply_reads is the waiting consumers' setting"),
    ({"PREFETCH": "1000"}, "prefetch is RabbitMQ's consumer's setting, and this run is kafka"),
    ({"BACKEND": "rabbitmq", "PREFETCH": "01"}, 'prefetch is a whole number of messages, 0 for no'),
    ({"BACKEND": "rabbitmq", "PREFETCH": "-1"}, 'prefetch is a whole number of messages'),
    ({"ACK_BATCH": "200"}, "ack_batch is the Redis and RabbitMQ consumers' setting, and this run is kafka"),
    ({"BACKEND": "nats", "ACK_BATCH": "200"}, "ack_batch is the Redis and RabbitMQ consumers'"),
    ({"BACKEND": "redis", "ACK_BATCH": "0"}, 'ack_batch is a whole number of at least one, not "0"'),
    ({"BACKEND": "rabbitmq", "ACK_BATCH": "10"},
     "ack_batch 10 is more than the 1 messages the prefetch lets the broker send unacknowledged"),
    ({"BACKEND": "rabbitmq", "ACK_BATCH": "10", "PREFETCH": "5"}, "ack_batch 10 is more than the 5"),
    ({"FETCH_RT": "1", "CONSUMER": "franz"},
     "fetch_rt raises the thread that sends the fetches, and franz-go sends them from none"),
    ({"FETCH_RT": "1"}, "fetch_rt raises the fetch threads a consumer names in its thread list"),
    ({"FETCH_RT": "1", "BACKEND": "nats", "CONSUMER": "nats-go"},
     "fetch_rt raises the fetch threads a consumer names"),
    ({"SCHEDSTAT": "1", "CONSUMER": "franz"},
     "schedstat samples the Python consumer's own thread, and this run's consumer is franz"),
    ({"SCHEDSTAT": "1", "BACKEND": "nats", "CONSUMER": "nats-go"}, "schedstat samples"),
    ({"ARRIVAL": "bursty"}, 'arrival is constant or poisson, not "bursty"'),
    ({"ARRIVAL": "poisson", "PLAN_KIND": "football"},
     "arrival sets the steady plan's arrivals, and this run replays the football plan"),
    ({"LOAD_KIND": "disk"}, 'load_kind is cpu, sock or udp, not "disk"'),
    ({"LOAD_KIND": "udp", "LOAD": "0"}, "load_kind sets what the load runs, and a load of 0"),
    ({"SIBLING_LOAD": "1"}, "sibling_load loads the other threads of the core whole_core keeps"),
    ({"SIBLING_LOAD": "1", "WHOLE_CORE": "1", "LOAD": "0"}, "sibling_load runs the load on the"),
    ({"SIBLING_LOAD": "1", "WHOLE_CORE": "1", "LOAD_KIND": "udp"},
     "sibling_load runs the load on the core's other threads, and a udp load runs where"),
    ({"IRQ_CPUS": "3-1"}, 'irq_cpus is core, or a list of CPUs as the kernel writes one'),
    ({"IRQ_CPUS": "cores"}, 'irq_cpus is core, or a list of CPUs')])
def test_a_v47_setup_the_runner_cannot_give_fails_before_the_machine_is_touched(
        tmp_path, setting, said):
    """Each would otherwise run, and be filed, under a setting it did not have."""
    assert _v47_setup_says(tmp_path, **setting).startswith(said)


@needs_bash
@pytest.mark.parametrize("setting", [
    {}, {"CONSUMER": "kafka-python"}, {"CONSUMER": "confluent", "FETCH_RT": "1"},
    {"CONSUMER": "java", "FETCH_RT": "1"}, {"CONSUMER": "franz"},
    {"BACKEND": "redis", "CONSUMER": "waiting", "DEPTH": "256", "ONE_REPLY": "1",
     "ACK_BATCH": "200"},
    {"BACKEND": "redis", "ACK_BATCH": "1"},
    {"BACKEND": "nats", "DEPTH": "256", "ONE_REPLY": "1"},
    {"BACKEND": "nats", "CONSUMER": "python", "DEPTH": "1"},
    {"BACKEND": "nats", "CONSUMER": "nats-go"},
    {"BACKEND": "rabbitmq", "PREFETCH": "1000", "ACK_BATCH": "200"},
    {"BACKEND": "rabbitmq", "PREFETCH": "0", "ACK_BATCH": "5000"}, {"BACKEND": "rabbitmq", "PREFETCH": "1"},
    {"ARRIVAL": "poisson"}, {"ARRIVAL": "constant"}, {"LOAD_KIND": "sock"}, {"LOAD_KIND": "udp"},
    {"LOAD_KIND": "cpu", "LOAD": "0"}, {"WHOLE_CORE": "1", "SIBLING_LOAD": "1"},
    {"IRQ_CPUS": "core"}, {"IRQ_CPUS": "3"}, {"IRQ_CPUS": "1-2,4-5"},
    {"SCHEDSTAT": "1", "CONSUMER": "confluent"}])
def test_and_a_v47_setup_it_can_give_passes_those_checks(tmp_path, setting):
    assert _v47_setup_says(tmp_path, **setting) == ""


def _load_start(tmp_path, *args, **setting):
    """load_start as the runner defines it, with stress-ng and python3 stood in for by commands
    that write down how they were called. (The calls.)"""
    work = Path(tempfile.mkdtemp(dir=str(tmp_path)))
    calls = work / "calls.txt"
    script = "\n".join([
        "set -uo pipefail", 'stress-ng () { echo "stress-ng $*" >> "$CALLS"; }',
        'python3 () { echo "python3 $*" >> "$CALLS"; }', _function("load_start"),
        'load_start %s' % " ".join(args), "builtin wait", ""])
    env = dict({"CALLS": calls.as_posix(), "DUTY_PERIOD_MS": "100", "UDP_WORKERS_PER_CPU": "1"},
               **setting)
    _run_script(work / "load.sh", script, env, capture_output=True, text=True, check=True)
    return _lines(calls)


@needs_bash
def test_v47s_load_is_the_cpu_stressor_unless_the_setup_names_another(tmp_path):
    """Every earlier block's load, as it was; a load kept off the consumer's core on the CPUs the
    run leaves it, one worker each; the socket and UDP loads held at the duty by the duty cycle,
    the UDP one with its workers for each CPU it is given."""
    assert _load_start(tmp_path, "88", "8", "3600s") == [
        "stress-ng --cpu 8 --cpu-load 88 --timeout 3600s"]
    assert _load_start(tmp_path, "75", "8", "10s", LOAD_TASKSET="0-5", LOAD_CPUS="6") == [
        "stress-ng --cpu 6 --cpu-load 75 --taskset 0-5 --timeout 10s"]
    assert _load_start(tmp_path, "75", "8", "10s", LOAD_KIND="sock") == [
        "python3 scripts/duty_cycle.py --duty 75 --period-ms 100 -- stress-ng --sock 8 "
        "--timeout 10s"]
    assert _load_start(tmp_path, "75", "8", "3600s", LOAD_KIND="udp", LOAD_TASKSET="3",
                       LOAD_CPUS="1", UDP_WORKERS_PER_CPU="2") == [
        "python3 scripts/duty_cycle.py --duty 75 --period-ms 100 -- stress-ng --udp 2 "
        "--taskset 3 --timeout 3600s"]


def test_v47s_load_is_started_by_one_function_wherever_the_runner_starts_one():
    """The run's own load, its correction, the second correction and every block of a load in
    blocks: no stress-ng is started anywhere else."""
    code = _campaign()
    starts = [line.strip() for line in code.splitlines() if re.match(r"\s*stress-ng --", line)]
    assert [line.split()[1] for line in starts] == ["--sock", "--udp", "--cpu"]
    body = _function("load_start")
    assert all(line in body for line in starts), "every one of them in load_start"
    for caller in ("recorrect_load", "load_blocks"):
        assert "load_start " in _function(caller), caller
    run = code.split("run_one () {", 1)[1]
    assert run.count('load_start "${DUTY:-$LOAD}" "$want_cpus" 3600s') == 1
    assert run.count('load_start "$adjusted" "$want_cpus" 3600s') == 1


def _placement(tmp_path, cores="6 7 0-5 0-5 6", irqbalance=True, udp="3 1", links=None,
               **setting):
    """Plan version 47's placement lines in run_one, run as the runner runs them with an unset
    variable an error, with python3, sudo, systemctl, taskset and ip stood in for by commands that
    write down how they were called: cpu_placement.py's core and irq-cpus answer `cores` and
    `udp`, and irqbalance runs until a sudo stops it. (The calls, what the runner then holds.)"""
    run_dir, calls = tmp_path / "run", tmp_path / "calls.txt"
    run_dir.mkdir(parents=True)
    active = tmp_path / "irqbalance_active"
    if irqbalance:
        active.write_text("", encoding="utf-8")
    block = _lines_from("  # Plan version 47 (23 Oct 2026): where the setup places the run",
                        "  # The two ping paths can differ with no delay at all")
    script = "\n".join([
        "set -uo pipefail",
        'python3 () { echo "python3 $*" >> "$CALLS"; case "$*" in *" core "*) echo "$CORES";; '
        '*" irq-cpus "*) echo "$UDP";; esac; }',
        'sudo () { echo "sudo $*" >> "$CALLS"; [ "$*" != "systemctl stop irqbalance" ] || '
        'rm -f "$ACTIVE"; }',
        'systemctl () { echo "systemctl $*" >> "$CALLS"; [ -f "$ACTIVE" ] || return 3; '
        '[ "$1 $2" = "is-active --quiet" ] || echo active; }',
        'taskset () { echo "taskset $*" >> "$CALLS"; echo "pid 99\'s current affinity list: 0-7"; }',
        'ip () { printf "%s\\n" "$FAKE_LINK"; }',
        "placing () {", block, "}",
        'REASON=""; CORE_CPU=""; LOAD_TASKSET=""; LOAD_CPUS=""; KIT_MASK_BEFORE=""; IRQS_MOVED=""',
        'RPS_MOVED=""; IRQBALANCE_STOPPED=""', "placing",
        'printf "%s\\n" "REASON=$REASON" "CORE_CPU=$CORE_CPU" "LOAD_TASKSET=$LOAD_TASKSET" '
        '"LOAD_CPUS=$LOAD_CPUS" "KIT_MASK_BEFORE=$KIT_MASK_BEFORE" "IRQS_MOVED=$IRQS_MOVED" '
        '"RPS_MOVED=$RPS_MOVED" "RPS_DEVICES=${RPS_DEVICES:-}" '
        '"IRQBALANCE_STOPPED=$IRQBALANCE_STOPPED"', ""])
    address = _write(tmp_path / "eth0_address", "60:45:bd:e9:60:ba\n")
    env = dict({"CALLS": calls.as_posix(), "RUN_DIR": run_dir.as_posix(), "CORES": cores,
                "UDP": udp, "ACTIVE": active.as_posix(), "FAKE_LINK": LINKS if links is None
                else links, "ETH0_ADDRESS": address.as_posix(), "LOAD": "70", "ALL_CPUS": "8",
                "RECEIVER_LINK": "sblrecv0"}, **setting)
    said = _run_script(tmp_path / "placing.sh", script, env, capture_output=True, text=True,
                       check=True).stdout
    held = dict(line.split("=", 1) for line in said.splitlines() if "=" in line)
    return _lines(calls) or [], held


@needs_bash
def test_v47s_placement_moves_nothing_a_setup_does_not_name(tmp_path):
    calls, held = _placement(tmp_path)
    assert calls == [] and held["REASON"] == ""
    assert [held[name] for name in ("CORE_CPU", "LOAD_TASKSET", "KIT_MASK_BEFORE", "IRQS_MOVED",
                                    "RPS_MOVED", "IRQBALANCE_STOPPED")] == [""] * 6


@needs_bash
def test_v47s_whole_core_keeps_the_core_for_the_consumer_and_the_run_off_it(tmp_path):
    """The core is chosen, the load placed on the other CPUs, and the campaign's own CPUs
    narrowed so that every process it starts runs off the core; what was there before is kept
    for placement_back; nothing else is moved."""
    calls, held = _placement(tmp_path, WHOLE_CORE="1")
    run = (tmp_path / "run").as_posix()
    assert calls[0] == "python3 scripts/cpu_placement.py core --out %s/core_choice.json" % run
    assert (held["CORE_CPU"], held["LOAD_TASKSET"], held["LOAD_CPUS"]) == ("6", "0-5", "6")
    assert calls[1] == "python3 scripts/cpu_placement.py irqs --out %s/irq_affinity_before.json" % run
    assert "systemctl is-active irqbalance" in calls
    assert [c for c in calls if c.startswith("taskset ")][1].startswith("taskset -pc 0-5 ")
    assert held["KIT_MASK_BEFORE"] == "0-7"
    assert not [c for c in calls if c.startswith("sudo ")], "no interrupt, queue or service moved"
    assert held["IRQS_MOVED"] == held["RPS_MOVED"] == held["IRQBALANCE_STOPPED"] == ""


@needs_bash
def test_v47s_sibling_load_asks_the_core_with_the_load_on_its_sibling(tmp_path):
    calls, held = _placement(tmp_path, cores="6 7 0-5 0-5,7 7", WHOLE_CORE="1", SIBLING_LOAD="1")
    assert calls[0].startswith("python3 scripts/cpu_placement.py core --sibling-load --out ")
    assert (held["LOAD_TASKSET"], held["LOAD_CPUS"]) == ("0-5,7", "7")
    assert [c for c in calls if c.startswith("taskset ")][1].startswith("taskset -pc 0-5 "), \
        "the run's own processes stay off both of the core's threads"


@needs_bash
@pytest.mark.parametrize("cores,said", [
    ("0 1 - - 0", "whole_core keeps the only core for the consumer, and leaves no CPU for the load"),
    ("0 - - 1 1", "whole_core keeps the only core for the consumer, and leaves no CPU for the "
                  "run's other processes")])
def test_v47s_a_core_that_leaves_nothing_for_the_rest_fails_the_run(tmp_path, cores, said):
    _, held = _placement(tmp_path, cores=cores, WHOLE_CORE="1")
    assert held["REASON"] == said


@needs_bash
def test_v47s_card_interrupts_go_to_the_cores_first_thread_with_irqbalance_stopped(tmp_path):
    """irq_cpus core, block C's baseline arm: the core is chosen but the consumer is not pinned
    to it nor the run kept off it; irqbalance is stopped first and the interrupts moved after."""
    calls, held = _placement(tmp_path, IRQ_CPUS="core", IRQBALANCE_OFF="1")
    run = (tmp_path / "run").as_posix()
    assert held["REASON"] == "" and held["CORE_CPU"] == "" and held["LOAD_TASKSET"] == ""
    order = [calls.index("sudo systemctl stop irqbalance"),
             calls.index("sudo python3 scripts/cpu_placement.py irqs --set 6 --out "
                         "%s/irq_affinity_set.json" % run)]
    assert order == sorted(order)
    assert held["IRQS_MOVED"] == "%s/irq_affinity_before.json" % run
    assert held["IRQBALANCE_STOPPED"] == "1" and held["KIT_MASK_BEFORE"] == ""
    _, given = _placement(tmp_path / "list", IRQ_CPUS="3", IRQBALANCE_OFF="1")
    assert given["IRQS_MOVED"].endswith("/irq_affinity_before.json")


@needs_bash
def test_v47s_interrupts_moved_while_irqbalance_runs_fail_the_run(tmp_path):
    _, held = _placement(tmp_path, IRQ_CPUS="3")
    assert held["REASON"].startswith("irq_cpus moves the receiver card's interrupts, and "
                                     "irqbalance is running")
    assert held["IRQS_MOVED"] == ""
    calls, held = _placement(tmp_path / "idle", irqbalance=False, IRQ_CPUS="3")
    assert held["REASON"] == "" and held["IRQBALANCE_STOPPED"] == ""
    assert "sudo systemctl stop irqbalance" not in calls


@needs_bash
def test_v47s_udp_load_runs_where_the_card_takes_its_interrupts(tmp_path):
    """On the CPUs the run gives the interrupts where it gives them; otherwise where they were
    found running; and away from a core kept for the consumer."""
    calls, held = _placement(tmp_path, LOAD_KIND="udp", udp="2 1")
    run = (tmp_path / "run").as_posix()
    assert ("python3 scripts/cpu_placement.py irq-cpus --irqs %s/irq_affinity_before.json"
            % run) in calls
    assert (held["LOAD_TASKSET"], held["LOAD_CPUS"]) == ("2", "1")
    calls, held = _placement(tmp_path / "given", LOAD_KIND="udp", IRQ_CPUS="3",
                             IRQBALANCE_OFF="1", WHOLE_CORE="1")
    assert ("python3 scripts/cpu_placement.py irq-cpus --irqs %s/irq_affinity_before.json "
            "--given 3 --avoid 6,7" % (tmp_path / "given" / "run").as_posix()) in calls
    _, held = _placement(tmp_path / "none", LOAD_KIND="udp", udp="ERROR: no CPU")
    assert held["REASON"] == "" or held["REASON"].startswith("the udp load")


@needs_bash
def test_v47s_receive_steering_is_turned_off_on_the_cards_queues_and_the_receivers(tmp_path):
    calls, held = _placement(tmp_path, RPS_OFF="1", links=TWO_CARDS)
    run = (tmp_path / "run").as_posix()
    assert held["RPS_DEVICES"] == "--dev eth0 --dev enP58460s1", "the device carrying eth0's address"
    assert ("python3 scripts/cpu_placement.py rps --dev eth0 --dev enP58460s1 --out "
            "%s/rps_before.json" % run) in calls
    assert ("sudo ip netns exec sblrecv python3 scripts/cpu_placement.py rps --dev sblrecv0 "
            "--out %s/rps_receiver_before.json" % run) in calls
    sets = [c for c in calls if "--set 0" in c]
    assert sets == ["sudo python3 scripts/cpu_placement.py rps --dev eth0 --dev enP58460s1 "
                    "--set 0 --out %s/rps_set.json" % run,
                    "sudo ip netns exec sblrecv python3 scripts/cpu_placement.py rps --dev "
                    "sblrecv0 --set 0 --out %s/rps_receiver_set.json" % run]
    assert held["RPS_MOVED"] == run


def _placement_back(tmp_path, **held):
    """placement_back as the runner defines it, run with what a run placed, its commands stood in
    for. (The calls, what is left held.)"""
    calls = tmp_path / "calls.txt"
    script = "\n".join([
        "set -uo pipefail", 'log () { echo "LOG $*" >> "$CALLS"; }',
        'sudo () { echo "sudo $*" >> "$CALLS"; }', 'systemctl () { echo "systemctl $*" >> "$CALLS"; }',
        'taskset () { echo "taskset $1 $2" >> "$CALLS"; }', _function("placement_back"),
        'placement_back "$RUN"',
        'echo "left=[$KIT_MASK_BEFORE$RPS_MOVED$IRQS_MOVED$IRQBALANCE_STOPPED]"', ""])
    env = dict({"CALLS": calls.as_posix(), "RUN": tmp_path.as_posix(), "KIT_MASK_BEFORE": "",
                "RPS_MOVED": "", "IRQS_MOVED": "", "IRQBALANCE_STOPPED": ""}, **held)
    said = _run_script(tmp_path / "back.sh", script, env, capture_output=True, text=True,
                       check=True).stdout
    return _lines(calls) or [], said.strip()


@needs_bash
def test_v47s_placement_is_put_back_in_order_and_nothing_is_left_held(tmp_path):
    """The campaign's own CPUs, the receive queues, the interrupts, and irqbalance last, which
    would otherwise move the interrupts again as it started; a run that placed nothing changes
    nothing."""
    calls, left = _placement_back(tmp_path, KIT_MASK_BEFORE="0-7", RPS_MOVED="runs/x",
                                  IRQS_MOVED="runs/x/irq_affinity_before.json",
                                  IRQBALANCE_STOPPED="1")
    run = tmp_path.as_posix()
    assert calls == [
        "taskset -pc 0-7",
        "sudo python3 scripts/cpu_placement.py rps --restore runs/x/rps_before.json --out "
        "%s/rps_restored.json" % run,
        "sudo ip netns exec sblrecv python3 scripts/cpu_placement.py rps --restore "
        "runs/x/rps_receiver_before.json --out %s/rps_receiver_restored.json" % run,
        "sudo python3 scripts/cpu_placement.py irqs --restore runs/x/irq_affinity_before.json "
        "--out %s/irq_affinity_restored.json" % run,
        "sudo systemctl start irqbalance", "systemctl is-active irqbalance"]
    assert left == "left=[]"
    assert _placement_back(tmp_path / "none") == ([], "left=[]")


def test_v47s_placement_is_put_back_after_every_run_and_when_the_campaign_stops():
    code = _campaign()
    loop = code.split("\nwhile true; do", 1)[1]
    assert loop.index("  run_one\n") < loop.index('  placement_back "$RUN_DIR"') \
        < loop.index("python3 scripts/run_queue.py finish")
    assert 'placement_back "${RUN_DIR:-runs/azure}"' in _function("finish_campaign")
    assert "irqs_back" not in code


@needs_bash
def test_v47s_consumer_is_pinned_to_the_kept_core_ahead_of_its_wrap(tmp_path):
    """taskset first, so that every process of the consumer's wrap and the consumer's own threads
    take the core; a run that keeps none starts it as before."""
    pinned, _ = _r1_runner(tmp_path, "pinned", CORE_CPU="6", CONSUMER_PRIORITY="1")
    assert pinned["consumer"] == ("taskset -c 6 sudo chrt -f 80 sudo ip netns exec sblrecv sudo "
                                  "-u tester")
    plain, _ = _r1_runner(tmp_path, "plain", CORE_CPU="")
    assert plain["consumer"] == "sudo ip netns exec sblrecv sudo -u tester"


@needs_bash
@pytest.mark.parametrize("backend,port", [("nats", "4222"), ("rabbitmq", "5672")])
def test_v47s_broker_capture_is_the_new_brokers_own_port(tmp_path, backend, port):
    _, calls = _r1_runner(tmp_path, backend, BROKER_CAPTURE="1", BACKEND=backend,
                          NATS_PORT="4222", RABBITMQ_PORT="5672")
    assert "tcp port %s >" % port in [c for c in calls if c.startswith("remote_broker ")][0]


@needs_bash
@pytest.mark.parametrize("backend,asked", [
    ("kafka", "docker logs --timestamps --since 100 --until 171 broker"),
    ("redis", "docker logs --timestamps --since 100 --until 171 redis"),
    ("rabbitmq", "docker logs --timestamps --since 100 --until 171 rabbitmq"),
    ("nats", "sudo journalctl -u sbl-nats-js -o short-iso-precise --since @100 --until @171")])
def test_v47s_broker_log_is_each_brokers_own(tmp_path, backend, asked):
    block = _lines_from("  container=redis\n", '  if [ -n "$recv_full" ]; then')
    calls = tmp_path / "calls.txt"
    script = "\n".join(["set -uo pipefail",
                        'remote_broker () { echo "$*" >> "$CALLS"; echo "a log line"; }',
                        "logs () {", "  container=redis", block, "}", "logs", ""])
    env = {"CALLS": calls.as_posix(), "RUN_DIR": tmp_path.as_posix(), "BACKEND": backend,
           "began": "100", "ended": "170"}
    _run_script(tmp_path / "logs.sh", script, env, capture_output=True, text=True, check=True)
    assert _lines(calls) == [asked]
    assert (tmp_path / "broker_log.txt").read_text(encoding="utf-8") == "a log line\n"


@needs_bash
@pytest.mark.parametrize("backend,setting,runner,flags", [
    ("kafka", {"CONSUMER": "confluent", "FETCH_RT": "1"}, "scripts/run_kafka_trial.sh",
     ["-CONSUMER", "confluent", "-FETCH_RT"]),
    ("redis", {"CONSUMER": "waiting", "DEPTH": "256", "ONE_REPLY": "1", "ACK_BATCH": "200"},
     "scripts/run_redis_trial.sh", ["-CONSUMER", "waiting", "-DEPTH", "256", "-ONE_REPLY_READS"]),
    ("nats", {"DEPTH": "256", "ONE_REPLY": "1"}, "scripts/run_nats_trial.sh",
     ["-DEPTH", "256", "-ONE_REPLY_READS"]),
    ("nats", {"CONSUMER": "nats-go"}, "scripts/run_nats_trial.sh", ["-CONSUMER", "nats-go"]),
    ("rabbitmq", {"PREFETCH": "1000", "ACK_BATCH": "200"}, "scripts/run_rabbitmq_trial.sh",
     ["-PREFETCH", "1000"])])
def test_v47s_each_backend_has_its_runner_with_the_setups_own_flags(tmp_path, backend, setting,
                                                                   runner, flags):
    found = _trial_starts(tmp_path / backend, BACKEND=backend, **setting)
    trial = found["trial"]
    assert trial[trial.index("bash") + 1] == runner
    assert trial[-len(flags):] == flags, "after -IDLE_SECONDS, the setup's own flags"
    consumer_extra = trial[trial.index("-CONSUMER_EXTRA") + 1]
    if backend == "rabbitmq":
        assert trial[trial.index("-URI") + 1] == "amqp://guest:guest@10.9.9.9:5672"
        assert consumer_extra.endswith(" --ack-batch 200"), "the batch where the client takes it"
        assert trial[trial.index("-PRODUCER_EXTRA") + 1] == " " + found["so"] % "producer", \
            "and none of Kafka's producer settings, nor Redis's send workers"
    if backend == "nats":
        assert trial[trial.index("-NatsHost") + 1:trial.index("-NatsHost") + 7] == [
            "10.9.9.9", "-PORT", "4222", "-STORAGE", "memory", "-DELETE_STREAM"]
        assert "--read-trace" not in consumer_extra
    if backend == "redis":
        assert consumer_extra.startswith("--ack-batch 200 --ack-batch 200 ")


@needs_bash
def test_v47s_runners_are_told_the_plans_arrivals_and_the_values_set_in_one_place(tmp_path):
    found = _trial_starts(tmp_path / "k", BACKEND="kafka", run_arrival="poisson",
                          run_seed="12345")
    assert found["plan"] == ["arrival=poisson", "seed=12345", "wait=60", "priority=80"]
    found = _trial_starts(tmp_path / "n", BACKEND="nats", THREADS_WAIT_S="90")
    assert found["plan"] == ["arrival=constant", "seed=", "wait=90", "priority="]


@needs_bash
def test_v47s_poisson_runs_replay_the_campaigns_poisson_plan(tmp_path):
    block = _lines_from("  local run_plan=", "  local record_args=")
    script = "\n".join(["set -uo pipefail", "plans () {", block,
                        '  echo "$run_plan $run_speedup $run_arrival ${run_seed:-none}"', "}",
                        "plans", ""])
    env = {"SYN_PLAN": "constant.csv", "SPEEDUP": "1.01", "DURATION": "70", "RATE": "2000",
           "POISSON_PLAN": "poisson.csv", "POISSON_SPEEDUP": "1.02", "PLAN_SEED": "7",
           "PLAN_KIND": "", "ARRIVAL": ""}
    said = _run_script(tmp_path / "plain.sh", script, env, capture_output=True, text=True,
                       check=True).stdout.strip()
    assert said == "constant.csv 1.01 constant none"
    said = _run_script(tmp_path / "poisson.sh", script, dict(env, ARRIVAL="poisson"),
                       capture_output=True, text=True, check=True).stdout.strip()
    assert said == "poisson.csv 1.02 poisson 7"


def test_v47s_poisson_plan_is_drawn_once_before_the_first_run_from_one_seed():
    code = _campaign()
    assert 'PLAN_SEED="${PLAN_SEED:-12345}"' in code
    assert ('POISSON_PLAN="data/synthetic/poisson_r${RATE}_d${DURATION}_s${PLAN_SEED}/'
            'replay_plan.csv"') in code
    first = code.split("# --- the queue ", 1)[0]
    assert ("python3 scripts/make_synthetic_plan.py --arrival poisson \\\n      --rate \"$RATE\" "
            "--duration \"$DURATION\" --seed \"$PLAN_SEED\" --out \"$POISSON_PLAN\"") in first
    assert 'POISSON_SPEEDUP=$(assert_plan_rate "$POISSON_PLAN" 1)' in first


@needs_bash
def test_v47s_queue_says_which_backends_consumers_and_arrivals_its_runs_need(tmp_path):
    sys.path.insert(0, str(REPO / "scripts"))
    import run_queue
    design = {"seed": 1, "rounds": 1, "setups": [
        {"id": "a", "backend": "nats", "consumer": "nats-go", "arrival": "poisson"},
        {"id": "b", "backend": "kafka", "consumer": "confluent", "fetch_rt": False},
        {"id": "c", "backend": "rabbitmq"}]}
    queue = tmp_path / "q.csv"
    run_queue.write_queue(str(queue), run_queue.make_rows(design))
    head = "queue_says () {"
    function = head + _campaign().split(head, 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    script = "\n".join([function, 'queue_says backend', 'queue_says consumer',
                        'queue_says arrival', 'queue_says fetch_rt', ""])
    said = _run_script(tmp_path / "says.sh", script, {"QUEUE": queue.as_posix()},
                       capture_output=True, text=True, check=True).stdout.splitlines()
    assert said == ["kafka nats rabbitmq", "confluent nats-go", "poisson", ""]


def _nats_check(port):
    code = _campaign()
    snippet = code.split('NATS_SAYS=$(python3 - "$NATS_HOST" "$NATS_PORT" <<\'PY\'\n', 1)[1]
    snippet = snippet.split("\nPY\n", 1)[0]
    return subprocess.run([sys.executable, "-", "127.0.0.1", str(port)], input=snippet,
                          text=True, capture_output=True)


@pytest.mark.parametrize("info,ok,said", [
    (b'INFO {"version":"2.15.1","jetstream":true}\r\n', True, "nats-server 2.15.1, JetStream on"),
    (b'INFO {"version":"2.15.1"}\r\n', False, "nats-server 2.15.1, JetStream off"),
    (b"-ERR 'nope'\r\n", False, "nats-server None, JetStream off")])
def test_v47s_nats_is_asked_as_its_clients_ask_it_whether_jetstream_is_on(info, ok, said):
    """The tools block's NATS listens on the same port with JetStream off, and every client of
    block N needs JetStream, so the campaign reads the server's INFO before the first run."""
    import socket
    import threading
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def greet():
        conn, _ = server.accept()
        conn.sendall(info)
        conn.close()
    threading.Thread(target=greet, daemon=True).start()
    done = _nats_check(server.getsockname()[1])
    server.close()
    assert (done.returncode == 0) is ok and done.stdout.strip() == said


def test_v47s_nats_that_does_not_answer_is_said_so():
    import socket
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    done = _nats_check(port)
    assert done.returncode == 1 and done.stdout.startswith("no answer: ")


def test_v47s_campaign_refuses_a_queue_whose_brokers_or_consumers_are_not_there():
    first = _campaign().split("# --- the queue ", 1)[0]
    for needed in ('grep -q "^rabbitmq:running"', "import pika", "import confluent_kafka",
                   '"$SBL_JAVA" -cp harness/java/out LawSelfTest',
                   "[ -x harness/go/out/franz-consumer ]",
                   "[ -x harness/go-nats/out/natsgo-consumer ]", '"jetstream"'):
        assert needed in first, needed
    assert 'export SBL_JAVA="${SBL_JAVA:-$JAVA17_BIN}"' in first
    assert ('JAVA17_BIN="/usr/lib/jvm/java-17-openjdk-$(dpkg --print-architecture 2>/dev/null)'
            '/bin/java"') in _campaign(), "the Arm pair's own Java"


def test_v47s_every_new_client_is_reaped_by_a_word_of_its_own():
    reap = _function("reap")
    for client in ("kafka_consumer_confluent.py", "kafka_producer_confluent.py",
                   "franz-consumer", "natsgo-consumer", "redis_consumer_waiting.py",
                   "nats_producer.py", "nats_consumer.py", "rabbitmq_producer.py",
                   "rabbitmq_consumer.py", "consumer_threads.py", "duty_cycle.py"):
        assert re.search(r'pkill -f "[^"]*\b%s\b' % re.escape(client), reap), client
    occupancy = (REPO / "cloud" / "campaigns" / "occupancy_measured.sh").read_text(
        encoding="utf-8")
    body = occupancy.split("reap () {", 1)[1].split("\n}\n", 1)[0]
    assert 'pkill -f "$OTHER_CLIENTS"' in body and 'pkill -f "$STAMPERS"' in body
    assert '--pattern "$STAMPERS"' in occupancy, "what it samples is what it always sampled"
    for client in ("kafka_consumer_confluent.py", "natsgo-consumer", "rabbitmq_consumer.py"):
        assert client in occupancy.split('OTHER_CLIENTS="', 1)[1].split("\n\nreap", 1)[0]


@needs_bash
def test_v47s_brokers_are_primed_where_the_queue_runs_them(tmp_path):
    def prime(backends):
        calls, trials, _, _ = _prime_more(tmp_path / backends.replace(" ", "_"), backends)
        return calls, trials
    calls, trials = prime("kafka nats rabbitmq redis")
    assert [c.split(":")[0] for c in calls if c.startswith("LOG")] == [
        "LOG PRIME kafka", "LOG PRIME redis", "LOG PRIME nats", "LOG PRIME rabbitmq"]
    assert trials[2][4:6] == ["scripts/run_nats_trial.sh", trials[2][5]]
    assert trials[2][-7:] == ["-PORT", "4222", "-STORAGE", "memory", "-DELETE_STREAM",
                              "-IDLE_SECONDS", "15"]
    assert trials[3][4] == "scripts/run_rabbitmq_trial.sh"
    assert trials[3][-4:] == ["-URI", "amqp://guest:guest@10.9.9.9:5672", "-IDLE_SECONDS", "15"]
    calls, _ = prime("kafka redis")
    assert len([c for c in calls if c.startswith("LOG")]) == 2, "as it always was"


def _prime_more(tmp_path, backends):
    """prime_brokers with QUEUE_BACKENDS set, its trials written down. (Calls, trials, -, -.)"""
    work, rec = tmp_path / "work", tmp_path / "rec"
    work.mkdir(parents=True)
    rec.mkdir()
    script = "\n".join([
        "set -uo pipefail", "trials=0",
        'reap () { :; }', 'log () { echo "LOG $*" >> "$REC/calls"; }',
        "date () { echo 20261023T010203Z; }",
        'timeout () { trials=$((trials + 1)); printf "%s\\n" "$@" > "$REC/trial_$trials"; }',
        _function("prime_brokers"), "prime_brokers", ""])
    env = {"REC": rec.as_posix(), "QUEUE_NAME": "v2000", "ME": "tester", "PRIME_S": "60",
           "SYN_PLAN": "plan.csv", "SPEEDUP": "1.000000", "KAFKA_BOOTSTRAP": "10.9.9.9:19092",
           "KAFKA_PRODUCER_EXTRA": "--max-inflight 64", "REDIS_HOST": "10.9.9.9",
           "REDIS_PORT": "6379", "REDIS_CONSUMER_EXTRA": "--ack-batch 200",
           "NATS_HOST": "10.9.9.9", "NATS_PORT": "4222", "NATS_STORAGE": "memory",
           "RABBITMQ_URI": "amqp://guest:guest@10.9.9.9:5672", "QUEUE_BACKENDS": backends}
    _run_script(tmp_path / "prime.sh", script, env, cwd=work, capture_output=True, text=True,
                check=True)
    trials = [_lines(rec / ("trial_%d" % n)) for n in range(1, 5)]
    return _lines(rec / "calls"), trials, None, work


@needs_bash
def test_v47s_a_runner_that_refuses_says_why_in_the_ledger(tmp_path):
    block = _lines_from('  # Plan version 47 (23 Oct 2026): a runner that refused the run says why',
                        '  if [ ! -f "$RUN_DIR/producer.csv" ]')
    script = "\n".join(["set -uo pipefail", "after () {", block, "}", 'REASON=""', "after",
                        'echo "REASON=$REASON"', ""])
    _write(tmp_path / "trial.log", "[1/4] starting consumer (franz)...\nFATAL: the consumer's "
                                   "threads were not settled before the producer; see x\n")
    said = _run_script(tmp_path / "after.sh", script, {"RUN_DIR": tmp_path.as_posix(), "rc": "3"},
                       capture_output=True, text=True, check=True).stdout.strip()
    assert said == ("REASON=the trial exited with 3: the consumer's threads were not settled "
                    "before the producer; see x; see %s/trial.log" % tmp_path.as_posix())
    _write(tmp_path / "trial.log", "Traceback\n")
    said = _run_script(tmp_path / "after2.sh", script, {"RUN_DIR": tmp_path.as_posix(), "rc": "1"},
                       capture_output=True, text=True, check=True).stdout.strip()
    assert said == "REASON=the trial exited with 1; see %s/trial.log" % tmp_path.as_posix()


def test_v47s_every_run_keeps_its_brokers_facts_and_a_softirq_load_its_counters():
    run = _campaign().split("run_one () {", 1)[1].split("\n}\n", 1)[0]
    order = ["tcp_counters before", 'case "${RUN_FACTS:-}:${LOAD_KIND:-}" in :sock|:udp) '
             "interrupt_counters before ;; esac",
             'remote_broker "cd sbl && python3 scripts/run_facts.py broker --out -"',
             "began=$(date -u +%s)", "ended=$(date -u +%s)",
             'case "${RUN_FACTS:-}:${LOAD_KIND:-}" in :sock|:udp) interrupt_counters after ;; esac',
             'python3 scripts/cpu_placement.py irqs --out "$RUN_DIR/irq_affinity_after.json"',
             'taskset -pc $$ > "$RUN_DIR/kit_mask_after.txt"']
    places = [run.index(step) for step in order]
    assert places == sorted(places)
    assert '> "$RUN_DIR/broker_facts.json"' in run
    assert 'if [ -n "${RUN_FACTS:-}${WHOLE_CORE:-}" ]; then\n    run_facts_later "$RUN_DIR" &' \
        in run, "a run that keeps a core reads where its processes ran"


@needs_bash
def test_v47s_interrupt_counters_read_time_squeeze_and_ksoftirqds_time(tmp_path):
    proc, run = tmp_path / "proc", tmp_path / "run"
    run.mkdir()
    _write(proc / "net" / "softnet_stat", "0000abcd 00000000 00000005\n")
    _write(proc / "interrupts", "")
    _write(proc / "softirqs", "")
    _write(proc / "15" / "comm", "ksoftirqd/0\n")
    _write(proc / "15" / "schedstat", "1500 300 7\n")
    script = "\n".join(["set -uo pipefail", _function("interrupt_counters"),
                        "interrupt_counters before", ""])
    _run_script(tmp_path / "softirq.sh", script, {"PROC_DIR": proc.as_posix(),
                                                  "RUN_DIR": run.as_posix()},
                capture_output=True, text=True, check=True, cwd=str(REPO))
    facts = json.loads((run / "softirq_before.json").read_text(encoding="utf-8"))
    assert facts["softnet"] == [{"line": 0, "processed": 0xabcd, "dropped": 0, "time_squeeze": 5}]
    assert facts["ksoftirqd"][0]["run_ns"] == 1500 and facts["ksoftirqd"][0]["comm"] == "ksoftirqd/0"


@needs_bash
def test_v47s_run_line_names_each_new_setting_and_an_earlier_row_none(tmp_path):
    line = next(text.strip() for text in _campaign().splitlines()
                if text.strip().startswith('log "run $KEY: '))
    row = {"KEY": "r001-C2000-kafka-core-sib-a1", "BACKEND": "kafka", "LOAD": "70",
           "DELAY_MS": "0"}
    script = "\n".join(["set -uo pipefail", 'log () { echo "$*"; }', line, ""])
    plain = _run_script(tmp_path / "plain.sh", script, row, capture_output=True, text=True,
                        check=True).stdout.strip()
    assert plain == "run r001-C2000-kafka-core-sib-a1: kafka, load 70%, slice kernel default, delay 0 ms"
    asked = dict(row, CONSUMER="confluent", DEPTH="256", ONE_REPLY="1", PREFETCH="1000",
                 FETCH_RT="1", ARRIVAL="poisson", WHOLE_CORE="1", SIBLING_LOAD="1",
                 IRQ_CPUS="core", IRQBALANCE_OFF="1", RPS_OFF="1", LOAD_KIND="udp")
    asked = _run_script(tmp_path / "asked.sh", script, asked, capture_output=True, text=True,
                        check=True).stdout.strip()
    assert asked == plain + (", consumer confluent, depth 256, one-reply reads, prefetch 1000, "
                             "fetch threads at real-time priority, poisson arrivals, the consumer "
                             "alone on a core, its sibling loaded, card interrupts on core, "
                             "irqbalance off, receive steering off, udp load")


def test_v47s_values_are_set_in_one_place():
    """Each value the new settings run with is named once, near the top, for the pilot to change."""
    code = _campaign()
    top = code.split("\nlog () {", 1)[0]
    for line in ('THREADS_WAIT_S="${THREADS_WAIT_S:-60}"',
                 'FETCH_RT_PRIORITY="${FETCH_RT_PRIORITY:-80}"',
                 'DUTY_PERIOD_MS="${DUTY_PERIOD_MS:-100}"',
                 'UDP_WORKERS_PER_CPU="${UDP_WORKERS_PER_CPU:-1}"', 'RECEIVER_LINK="sblrecv0"'):
        assert line in top, line
        name = line.split("=", 1)[0]
        assert len(re.findall(r"(?m)^%s=" % name, code)) == 1, "%s is set once" % name
    common = (REPO / "cloud" / "campaigns" / "common.sh").read_text(encoding="utf-8")
    for line in ('NATS_PORT="${NATS_PORT:-4222}"', 'NATS_STORAGE="${NATS_STORAGE:-memory}"',
                 'RABBITMQ_PORT="${RABBITMQ_PORT:-5672}"',
                 'RABBITMQ_URI="${RABBITMQ_URI:-amqp://guest:guest@$BROKER_PRIV:$RABBITMQ_PORT}"'):
        assert line in common, line
    sys.path.insert(0, str(REPO / "scripts"))
    import run_integrity
    assert run_integrity.MAX_WAITING_PER_REQUEST == 2,         "NATS's consumer is held to room for twice its depth, whatever rule it is made by"


# --- Plan version 47 (23 Oct 2026): the trial runners

def _runner_calls(tmp_path, runner, *flags, fail_threads=False, **env):
    """scripts/RUNNER run in a scratch folder, as _trial_runner_calls runs it, with the Java, Go
    and NATS Go consumers stood in for by programs that write down how they were called, and
    consumer_threads.py answering as `fail_threads` says. (The calls, meta.json, what it printed,
    its exit code.)"""
    work = tmp_path / runner
    stubs, calls = work / "bin", work / "calls.txt"
    python = Path(sys.executable).as_posix()
    py = ('if [ "$1" = - ]; then exec "%s" "$@"; fi\necho "python $*" >> "$CALLS"\n'
          'case "$*" in *consumer_threads.py*) [ -z "$FAIL_THREADS" ] || exit 1;; esac\n' % python)
    for name, body in (("py", py), ("java17", 'echo "java $*" >> "$CALLS"\n'),
                       ("sleep", ":\n"), ("redis-cli", ":\n")):
        os.chmod(_write(stubs / name, "#!/bin/sh\n" + body), 0o755)
    for binary in ("harness/go/out/franz-consumer", "harness/go-nats/out/natsgo-consumer"):
        os.chmod(_write(work / binary, '#!/bin/sh\necho "%s $*" >> "$CALLS"\n' % binary), 0o755)
    (work / "harness" / "java" / "out").mkdir(parents=True)
    given = {"PYTHON": (stubs / "py").as_posix(), "CALLS": calls.as_posix(),
             "SBL_JAVA": (stubs / "java17").as_posix(), "FAIL_THREADS": "1" if fail_threads
             else "", "SBL_SCHED_WRAP": "", "SBL_PRODUCER_WRAP": "", "SBL_CONSUMER_WRAP": ""}
    given.update(env)
    done = bash([(REPO / "scripts" / runner).as_posix(), "r001", "plan.csv", "1", "10"] +
                list(flags), cwd=work, path_first=[stubs], extra_env=given, capture_output=True,
                text=True, stdin=subprocess.DEVNULL)
    meta_path = work / "runs" / "r001" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
    return _lines(calls) or [], meta, done.stdout + done.stderr, done.returncode


def _one(calls, start):
    found = [c for c in calls if c.startswith(start)]
    assert len(found) == 1, calls
    return found[0]


@needs_bash
@pytest.mark.parametrize("consumer,start", [
    ("confluent", "python scripts/kafka_consumer_confluent.py --run-id r001 "),
    ("java", "java -cp harness/java/out:harness/java/lib/kafka-clients.jar:harness/java/lib/"
             "slf4j-api.jar LawConsumer --run-id r001 "),
    ("franz", "harness/go/out/franz-consumer --run-id r001 ")])
def test_v47s_kafka_runner_swaps_the_consumer_alone_and_waits_for_its_thread_list(
        tmp_path, consumer, start):
    """kafka_producer.py sends in every run; the consumer writes its threads, and the producer is
    started only once consumer_threads.py has found them; the Java and Go consumers are handed none
    of the Python clients' flags, and meta.json says which."""
    calls, meta, said, code = _runner_calls(
        tmp_path, "run_kafka_trial.sh", "-CONSUMER", consumer, "-CONSUMER_EXTRA",
        " --gc-off --so-timestamps x.csv", KAFKA_CONSUMER_OPTS="--max-poll-records 5")
    assert code == 0, said
    line = _one(calls, start)
    assert "--threads-out runs/r001/consumer_tids.csv" in line
    assert "--max-poll-records" not in line, "kafka-python's knobs are refused by the others"
    assert _one(calls, "python scripts/kafka_producer.py ").startswith(
        "python scripts/kafka_producer.py --run-id r001 ")
    waited = _one(calls, "python scripts/consumer_threads.py ")
    assert waited.startswith("python scripts/consumer_threads.py --threads runs/r001/"
                             "consumer_tids.csv --pid ")
    assert waited.endswith(" --timeout-s 60 --out runs/r001/consumer_threads.json")
    assert calls.index(waited) < calls.index(_one(calls, "python scripts/kafka_producer.py "))
    assert meta["consumer"] == {"client": consumer, "threads_out": "runs/r001/consumer_tids.csv",
                                "fetch_rt": False, "extra_not_handed": (
                                    None if consumer == "confluent" else
                                    "--gc-off --so-timestamps x.csv")}
    assert ("--gc-off" in line) is (consumer == "confluent")
    assert ("NOTE: the %s consumer takes none of the Python clients' flags" % consumer in said) \
        is (consumer != "confluent")


@needs_bash
def test_v47s_kafka_runner_raises_the_fetch_threads_where_asked(tmp_path):
    calls, meta, said, code = _runner_calls(tmp_path, "run_kafka_trial.sh", "-CONSUMER",
                                            "confluent", "-FETCH_RT",
                                            SBL_FETCH_RT_PRIORITY="70", SBL_THREADS_WAIT_S="30")
    assert code == 0, said
    assert _one(calls, "python scripts/consumer_threads.py ").endswith(
        " --timeout-s 30 --out runs/r001/consumer_threads.json --priority 70")
    assert meta["consumer"]["fetch_rt"] is True


@needs_bash
def test_v47s_kafka_runner_stops_a_trial_whose_threads_were_not_settled(tmp_path):
    calls, _, said, code = _runner_calls(tmp_path, "run_kafka_trial.sh", "-CONSUMER", "franz",
                                         "-FETCH_RT", fail_threads=True)
    assert code == 3 and "FATAL: the consumer's threads were not settled before the producer" in said
    assert not [c for c in calls if "kafka_producer.py" in c], "no message is sent"


@needs_bash
@pytest.mark.parametrize("flags,said", [
    (["-CONSUMER", "rdkafka"], "FATAL: -CONSUMER is kafka-python, confluent, java or franz"),
    (["-CONSUMER", "confluent", "-CLIENT", "java"], "FATAL: -CLIENT java swaps both clients"),
    (["-FETCH_RT"], "FATAL: -FETCH_RT raises the fetch threads a consumer names"),
    (["-CONSUMER", "kafka-python", "-FETCH_RT"], "FATAL: -FETCH_RT raises the fetch threads")])
def test_v47s_kafka_runner_refuses_what_it_cannot_run(tmp_path, flags, said):
    calls, _, printed, code = _runner_calls(tmp_path, "run_kafka_trial.sh", *flags)
    assert code == 2 and said in printed and calls == []


@needs_bash
def test_v47s_kafka_runner_records_the_plan_and_the_code_that_ran(tmp_path):
    calls, meta, said, code = _runner_calls(tmp_path, "run_kafka_trial.sh",
                                            SBL_PLAN_ARRIVAL="poisson", SBL_PLAN_SEED="12345")
    assert code == 0, said
    assert meta["plan"] == {"path": "plan.csv", "sha256": None, "arrival": "poisson",
                            "seed": 12345}
    assert meta["consumer"] == {"client": "kafka-python", "threads_out": None, "fetch_rt": False,
                                "extra_not_handed": None}
    assert {"scripts/kafka_consumer_confluent.py", "scripts/consumer_threads.py",
            "harness/java/src/LawConsumer.java", "harness/go/main.go",
            "harness/go/out/franz-consumer"} <= set(meta["code_sha256"])
    assert not [c for c in calls if "consumer_threads.py" in c], "kafka-python names no threads"
    _, meta, _, _ = _runner_calls(tmp_path / "steady", "run_kafka_trial.sh")
    assert meta["plan"]["arrival"] is None and meta["plan"]["seed"] is None


@needs_bash
def test_v47s_redis_runner_swaps_in_the_waiting_consumer(tmp_path):
    calls, meta, said, code = _runner_calls(tmp_path, "run_redis_trial.sh", "-CONSUMER", "waiting",
                                            "-DEPTH", "256", "-ONE_REPLY_READS",
                                            "-CONSUMER_EXTRA", "--ack-batch 200")
    assert code == 0, said
    line = _one(calls, "python scripts/redis_consumer_waiting.py ")
    assert line.endswith("--node-count 1 --depth 256 --one-reply-reads --ack-batch 200")
    assert not [c for c in calls if "scripts/redis_consumer.py" in c]
    assert (meta["redis"]["consumer"], meta["redis"]["depth"], meta["redis"]["one_reply_reads"]) \
        == ("waiting", 256, True)
    assert {"scripts/redis_consumer_waiting.py", "scripts/resp_wire.py"} <= set(meta["code_sha256"])
    calls, meta, _, _ = _runner_calls(tmp_path / "plain", "run_redis_trial.sh")
    assert _one(calls, "python scripts/redis_consumer.py ")
    assert (meta["redis"]["consumer"], meta["redis"]["depth"]) == ("redis-py", None)


@needs_bash
@pytest.mark.parametrize("flags,said", [
    (["-CONSUMER", "fast"], "FATAL: -CONSUMER is redis-py or waiting"),
    (["-DEPTH", "64"], "FATAL: -DEPTH and -ONE_REPLY_READS are the waiting consumer's"),
    (["-CONSUMER", "redis-py", "-ONE_REPLY_READS"], "FATAL: -DEPTH and -ONE_REPLY_READS")])
def test_v47s_redis_runner_refuses_what_its_consumer_does_not_take(tmp_path, flags, said):
    calls, _, printed, code = _runner_calls(tmp_path, "run_redis_trial.sh", *flags)
    assert code == 2 and said in printed and calls == []


def _free_port():
    import socket
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return str(port)


@needs_bash
def test_v47s_nats_runner_runs_natsgo_with_its_own_flags_and_waits_for_its_threads(tmp_path):
    """nats.go's consumer is handed the run's names, its storage, its idle time and its thread
    list, and none of the python consumer's flags; it deletes no stream, so the runner deletes it
    once the consumer is done, and says so where the server cannot be reached."""
    port = _free_port()
    calls, meta, said, code = _runner_calls(tmp_path, "run_nats_trial.sh", "-CONSUMER", "nats-go",
                                            "-NatsHost", "127.0.0.1", "-PORT", port,
                                            "-STORAGE", "memory", "-DELETE_STREAM",
                                            "-CONSUMER_EXTRA", "--gc-off",
                                            NATS_CONSUMER_OPTS="--thread-record")
    assert code == 0, said
    line = _one(calls, "harness/go-nats/out/natsgo-consumer ")
    stream, subject = meta["nats"]["stream"], meta["nats"]["subject"]
    assert line == ("harness/go-nats/out/natsgo-consumer --run-id r001 --out runs/r001/consumer.csv "
                    "--host 127.0.0.1 --port %s --stream %s --subject %s --durable sbl-r001 "
                    "--storage memory --idle-seconds 30 --threads-out runs/r001/consumer_tids.csv"
                    % (port, stream, subject))
    assert "NOTE: the stream %s could not be deleted; it stays on the server" % stream in said
    _, _, kept, _ = _runner_calls(tmp_path / "kept", "run_nats_trial.sh", "-CONSUMER", "nats-go",
                                  "-NatsHost", "127.0.0.1", "-PORT", port)
    assert "could not be deleted" not in kept, "nothing deleted that the run did not ask"
    _, _, python, _ = _runner_calls(tmp_path / "python", "run_nats_trial.sh", "-DELETE_STREAM",
                                    "-NatsHost", "127.0.0.1", "-PORT", port)
    assert "could not be deleted" not in python, "the python consumer deletes its own"
    waited = _one(calls, "python scripts/consumer_threads.py ")
    assert calls.index(waited) < calls.index(_one(calls, "python scripts/nats_producer.py "))
    assert meta["consumer"] == {"client": "nats-go", "threads_out": "runs/r001/consumer_tids.csv",
                                "extra_not_handed": "--thread-record --gc-off"}
    assert meta["nats"]["depth"] is None and meta["nats"]["storage"] == "memory"
    assert meta["nats"]["delete_stream"] is True
    assert {"harness/go-nats/main.go", "harness/go-nats/out/natsgo-consumer"} <= set(
        meta["code_sha256"])
    assert "NOTE: the nats-go consumer takes none of the python consumer's flags" in said


def test_v47s_runner_deletes_natsgos_stream_as_the_python_consumer_deletes_its_own(
        monkeypatch, capsys):
    """The runner's own deletion, run in this process against the scripted NATS server the
    NATS clients' tests use: the stream asked for is gone, and the runner says so."""
    import socket
    sys.path.insert(0, str(Path(__file__).parent))
    import test_nats_wire
    text = (REPO / "scripts" / "run_nats_trial.sh").read_text(encoding="utf-8")
    snippet = text.split("<<'PY' || echo \"NOTE: the stream $STREAM could not be deleted", 1)[1]
    snippet = snippet.split("\n", 1)[1].split("\nPY\n", 1)[0]
    server = test_nats_wire.FakeServer()
    server.create_stream("SBL_r001_1", {"subjects": ["sbl.r001.1"], "storage": "memory",
                                        "num_replicas": 1})
    monkeypatch.setattr(socket, "create_connection", server.connect)
    monkeypatch.setattr(sys, "argv", ["-", "127.0.0.1", "4222", "SBL_r001_1"])
    monkeypatch.chdir(REPO)
    exec(compile(snippet, "run_nats_trial.sh", "exec"), {"__name__": "__main__"})
    assert "SBL_r001_1" not in server.streams
    assert capsys.readouterr().out == "OK stream deleted: SBL_r001_1\n"


@needs_bash
@pytest.mark.parametrize("flags,said,status", [
    (["-CONSUMER", "nats-js"], "FATAL: -CONSUMER is python or nats-go", 2),
    (["-CONSUMER", "nats-go", "-DEPTH", "256"], "FATAL: -DEPTH and -ONE_REPLY_READS are the python", 2)])
def test_v47s_nats_runner_refuses_what_its_consumer_does_not_take(tmp_path, flags, said, status):
    calls, _, printed, code = _runner_calls(tmp_path, "run_nats_trial.sh", *flags)
    assert code == status and said in printed and calls == []


@needs_bash
def test_v47s_nats_runner_stops_a_trial_whose_go_consumer_listed_no_threads(tmp_path):
    calls, _, said, code = _runner_calls(tmp_path, "run_nats_trial.sh", "-CONSUMER", "nats-go",
                                         fail_threads=True)
    assert code == 3 and "FATAL: the consumer's threads were not listed before the producer" in said
    assert not [c for c in calls if "nats_producer.py" in c]


@needs_bash
def test_v47s_runners_record_the_plan_they_replay(tmp_path):
    for runner in ("run_redis_trial.sh", "run_nats_trial.sh", "run_rabbitmq_trial.sh"):
        _, meta, said, code = _runner_calls(tmp_path / runner, runner, SBL_PLAN_ARRIVAL="poisson",
                                            SBL_PLAN_SEED="7")
        assert code == 0, said
        assert meta["plan"] == {"path": "plan.csv", "sha256": None, "arrival": "poisson",
                                "seed": 7}, runner


# --- Plan version 47 (23 Oct 2026): the brokers and the driver's clients

BROKERS = REPO / "cloud" / "brokers.sh"


def _brokers():
    return BROKERS.read_text(encoding="utf-8")


def test_v47s_broker_images_are_pinned_in_one_place_by_digest_where_given():
    text = _brokers()
    assert b"\r" not in BROKERS.read_bytes() and bash(["-n", BROKERS.as_posix()]).returncode == 0
    pins = {"KAFKA_IMAGE": "apache/kafka:4.1.1",
            "REDIS_IMAGE": "redis:7.4.11@sha256:44960b3100c48159a66d28c18b0588c193492e25f7551d60"
                           "e51dd464fc3eca5b",
            "RABBITMQ_IMAGE": "rabbitmq:4.3.7@sha256:ddb072727ae2209a054515e806b0daa875cf611a7bb8"
                              "592345c7ddceaa8ef63c",
            "NATS_VERSION": "v2.15.1",
            "NATS_SHA256_AMD64": "bf5edc7b1ce98e885c368cb43a886eb148dc5d0551d99f3cf6141fb5e1954c70",
            "NATS_SHA256_ARM64": "e2fbab4cad7d3c76e3052eb959570393c9d73ba756b70bf8e9eea61e9ae6d49c"}
    for name, value in pins.items():
        assert text.count('%s="' % name) == 1 and '%s="%s"' % (name, value) in text, name
    for use in ('"$REDIS_IMAGE"', '"$KAFKA_IMAGE"', '"$RABBITMQ_IMAGE"'):
        assert use in text, use
    assert "redis:7 " not in text and "apache/kafka:4.1.1 >" not in text, "no tag outside the pins"


def test_v47s_nats_runs_with_jetstream_on_its_own_port_with_the_tools_blocks_server_stopped():
    text = _brokers()
    nats = text.split("# --- NATS with JetStream", 1)[1].split("# --- RabbitMQ", 1)[0]
    order = ["nats_install\n", "systemctl disable --now sbl-nats ", "port_free 4222",
             'rm -rf "$NATS_STORE"', "/etc/systemd/system/sbl-nats-js.service",
             "systemctl start sbl-nats-js", '"jetstream":true']
    places = [nats.index(step, nats.index("if wanted nats")) for step in order]
    assert places == sorted(places)
    assert "ExecStart=%s -p 4222 -js -sd %s" in nats
    assert "Restart=" not in nats, "a broker that died stops the runs that need it, loudly"
    rabbit = text.split("# --- RabbitMQ", 1)[1]
    order = ["systemctl disable --now rabbitmq-server", "port_free 5672",
             "loopback_users = none", "docker run -d --name rabbitmq -p 5672:5672",
             "rabbitmq-diagnostics -q check_port_listener 5672"]
    places = [rabbit.index(step) for step in order]
    assert places == sorted(places)
    assert '-v "$RABBITMQ_CONF:/etc/rabbitmq/conf.d/20-sbl.conf:ro"' in rabbit
    # Asked as root before the broker is up, the tool writes the Erlang cookie as root, and the
    # broker cannot read it.
    assert "docker exec --user rabbitmq rabbitmq rabbitmq-diagnostics" in rabbit
    assert "docker exec rabbitmq " not in rabbit


def _nats_install(tmp_path, pin=None, sums=None):
    """brokers.sh's nats_install, run against a release folder of our own: a real archive holding
    a nats-server, its SHA256SUMS, and curl copying from the folder. (Exit code, what it said,
    the install folder.)"""
    import hashlib
    import tarfile
    release, work = tmp_path / "release", tmp_path / "install"
    release.mkdir(parents=True)
    asset = "nats-server-v2.15.1-linux-amd64.tar.gz"
    inner = tmp_path / "nats-server-v2.15.1-linux-amd64"
    inner.mkdir(parents=True)
    _write(inner / "nats-server", "#!/bin/sh\necho nats-server: v2.15.1\n")
    def executable(info):
        # As the release's own archive holds it. Git Bash calls a file with a #! line
        # executable whatever its mode, and Linux does not (CI, 23 Oct 2026).
        if info.isfile():
            info.mode = 0o755
        return info

    with tarfile.open(release / asset, "w:gz") as tar:
        tar.add(str(inner), arcname="nats-server-v2.15.1-linux-amd64", filter=executable)
    digest = hashlib.sha256((release / asset).read_bytes()).hexdigest()
    _write(release / "SHA256SUMS", (sums or "%s  %s\n") % (digest, asset)
           if sums is None else sums)
    head = "nats_install () {"
    function = head + _brokers().split(head, 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    script = "\n".join([
        "set -euo pipefail", 'fatal () { echo "FATAL: $*"; exit 1; }',
        'uname () { echo x86_64; }',
        'curl () { local out="$3" url="$4"; cp "$RELEASE/${url##*/}" "$out"; }',
        'install () { mkdir -p "$(dirname "$5")"; cp "$4" "$5"; }',
        function, "nats_install", 'echo "installed"', ""])
    env = {"RELEASE": release.as_posix(), "NATS_VERSION": "v2.15.1",
           "NATS_SHA256_AMD64": pin or digest, "NATS_SHA256_ARM64": "0" * 64,
           "NATS_DIR": work.as_posix()}
    done = _run_script(tmp_path / "install.sh", script, env, capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr, work, digest


@needs_bash
def test_v47s_nats_is_installed_only_after_both_checks_and_checked_again_each_session(tmp_path):
    code, said, work, digest = _nats_install(tmp_path / "good")
    assert code == 0 and said.strip().endswith("installed"), said
    assert (work / "nats-server").exists() and (work / "nats-server-v2.15.1-linux-amd64.tar.gz").exists()
    code, said, _, _ = _nats_install(tmp_path / "pin", pin="0" * 64)
    assert code == 1 and "does not match the hash pinned in cloud/brokers.sh" in said
    code, said, work, _ = _nats_install(tmp_path / "sums", sums="%s  other.tar.gz\n" % ("1" * 64))
    assert code == 1 and "does not match the release's own SHA256SUMS" in said
    assert not (work / "nats-server").exists(), "nothing installed from an archive that failed"


def test_v47s_brokers_runs_the_brokers_it_is_asked_for_and_says_what_ran():
    text = _brokers()
    assert 'ALL="kafka redis nats rabbitmq"' in text and 'WANTED="${*:-$ALL}"' in text
    for broker in ("redis", "kafka", "nats", "rabbitmq"):
        assert "if wanted %s; then" % broker in text, broker
    assert "docker rm -f broker redis rabbitmq" in text
    assert 'docker inspect --format "$name {{.Config.Image}} {{.Image}}"' in text
    assert '"$NATS_DIR/nats-server" --version' in text


def test_v47s_the_driver_installs_each_client_at_its_version_on_its_own_architecture():
    tools = (KIT / "tools.sh").read_text(encoding="utf-8")
    body = tools.split("\nclients () {", 1)[1].split("\n}\n", 1)[0]
    assert 'CONFLUENT_KAFKA_VERSION="2.15.1"' in tools and 'PIKA_VERSION="1.3.2"' in tools
    order = ['sudo pip3 install -q "confluent-kafka==$CONFLUENT_KAFKA_VERSION"',
             'sudo pip3 install -q "pika==$PIKA_VERSION"', "openjdk-17-jdk-headless",
             'sudo update-alternatives --set "$t" "$java11/bin/$t"',
             'PATH="$java17/bin:$PATH" bash harness/java/build.sh', "get_go ||",
             "bash harness/go/build.sh", "bash harness/go-nats/build.sh",
             '"$dir/clients_installed.json"']
    places = [body.index(step) for step in order]
    assert places == sorted(places)
    assert 'java17="/usr/lib/jvm/java-17-openjdk-$arch"' in body and "dpkg --print-architecture" in body
    assert "confluent_kafka.version()[0] != '$CONFLUENT_KAFKA_VERSION'" in body, "left as it is"
    for record in ("harness/go/out/BUILD_INFO.txt", "harness/go-nats/out/BUILD_INFO.txt"):
        assert record in body, "each Go consumer's compiler and modules are written down"
    assert "clients) clients ;;" in tools
