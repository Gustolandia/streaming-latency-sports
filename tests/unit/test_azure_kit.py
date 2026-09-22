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
                                       "machine_facts.sh", "pilot.sh", "queue.sh", "replicate_oracle.sh",
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
        assert "receiver_delay.py broker --dst $RECEIVER_IP" in code, (
            "added on the broker's card toward the receiver's namespace, the same place and the "
            "same way the law campaigns add it")
        assert "needs_namespace" in code and "delay_arrives" in code, (
            "and the staircase does not start until the delay is shown to reach the tool")
        assert "broker-clear" in code, "and the delay is taken off afterwards"

    def test_rdkafkas_consumer_is_started_before_the_producer_it_measures(self):
        """It starts at the end of the topic, so a producer that has already finished is one it
        never sees. With the producer first it printed "0 messages consumed" once a second and
        had a pair to itself for twenty-eight minutes."""
        code = self.runner().split("  rdkafka_performance)", 1)[1].split(";;", 1)[0]
        lines = [line.strip() for line in code.splitlines() if not line.strip().startswith("#")]
        consumer = next(i for i, line in enumerate(lines) if " -C " in line)
        producer = next(i for i, line in enumerate(lines) if " -P " in line)
        assert consumer < producer, "the consumer is listening before anything is sent"
        assert lines[consumer].endswith("&") or lines[consumer + 1].endswith("&"), \
            "and it is the one left running in the background"
        assert 'wait "$consumer"' in code, "the run ends when the consumer has its messages"

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
        assert "127.0.0.1" not in code, "no target is the machine the tool runs on"
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
        assert "no reference trips beside this run" in code


QUEUE = KIT / "queue.sh"


def _queue_call(tmp_path, call):
    """One of queue.sh's own functions, sourced in a scratch checkout and asked a question.

    Sourcing runs the dispatch at the foot of the script, which with no argument is `show`, and
    show only reads. That is cheaper than a second copy of the parsing here, and a copy is what
    would rot.
    """
    root = _scratch_checkout(tmp_path)
    script = "cd '%s' && . cloud/azure/queue.sh >/dev/null 2>&1; %s" % (root.as_posix(), call)
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return done.stdout.strip()


def _scratch_checkout(tmp_path):
    """Enough of a checkout for the script to load: it reads the pair's addresses through
    common.sh, which refuses to load without them, as every campaign script here does."""
    root = tmp_path / "sbl"
    (root / "cloud" / "azure").mkdir(parents=True)
    (root / "cloud" / "campaigns").mkdir(parents=True)
    shutil.copy(QUEUE, root / "cloud" / "azure" / "queue.sh")
    shutil.copy(REPO / "cloud" / "campaigns" / "common.sh", root / "cloud" / "campaigns")
    (root / "cloud" / "hosts.env").write_text(
        "\n".join(["BROKER_PRIV=10.9.9.9", "RECEIVER_IP=10.9.9.8", "SUBNET_PREFIX=24",
                   "SUBNET_GATEWAY=10.9.9.1", "AZ_PROFILE=scratch", ""]), encoding="utf-8")
    return root


needs_bash = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"),
                                reason="these run the script itself")


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
def test_the_queue_reaches_as_far_as_a_session_driven_from_outside_does(tmp_path):
    """Two copies of one piece of arithmetic. A calibration that does not reach a campaign's
    longest trip does not fail: the design quietly drops the setups it cannot reach, so the two
    copies disagreeing would cost points rather than raise anything."""
    outside = (KIT / "a2_session.sh").read_text(encoding="utf-8")
    outside = outside.split("reach_ms () {", 1)[1].split("\n}", 1)[0]
    for boot, hz in (("hz1000", "1000"), ("hz250", "250"), ("hz100", "100")):
        mine = _queue_call(tmp_path, "reach_ms %s" % boot)
        theirs = subprocess.run(
            ["bash", "-c", "reach_ms () {%s\n}\nreach_ms %s" % (outside, hz)],
            capture_output=True, text=True).stdout.strip()
        assert mine == theirs, boot
    assert _queue_call(tmp_path, "reach_ms hz1000") == "8"
    assert _queue_call(tmp_path, "reach_ms hz100") == "32"


@needs_bash
def test_a_list_is_added_to_and_counted_from_the_disk(tmp_path):
    root = _scratch_checkout(tmp_path)
    for spec in ("boot=hz100 block=A2", "boot=cpu2 block=A5", "boot=none block=A4"):
        subprocess.run(["bash", "cloud/azure/queue.sh", "add", spec], cwd=root, check=True,
                       capture_output=True)
    shown = subprocess.run(["bash", "cloud/azure/queue.sh", "show"], cwd=root,
                           capture_output=True, text=True).stdout
    assert "jobs: 3, on job 1, phase prep" in shown
    assert "boot=cpu2 block=A5" in shown


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


@needs_bash
def test_the_check_that_the_loop_is_alive_knows_the_copy_by_name(tmp_path):
    """The check exists because a lock left by a killed loop made `start` say "running" over a
    queue that was not. Renaming what it runs from must not blind it again."""
    code = QUEUE.read_text(encoding="utf-8")
    pattern = code.split("if ps -eo args --no-headers | awk '", 1)[1].split("'", 1)[0]
    for line in ("bash cloud/azure/queue.sh run", "bash cloud/azure/.queue.running.sh run"):
        done = subprocess.run(["bash", "-c", "echo '%s' | awk '%s'" % (line, pattern)],
                              capture_output=True, text=True)
        assert done.returncode == 0, "%r is the loop and the check missed it" % line
    done = subprocess.run(["bash", "-c", "echo 'bash cloud/azure/queue.sh show' | awk '%s'"
                           % pattern], capture_output=True, text=True)
    assert done.returncode != 0, "only the loop counts, not every call of the script"


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
    assert started.index("crontab -") < started.index("setsid nohup"), \
        "the line is in before the loop starts, so a reboot in between is still caught"
    stopped = code.split("  stop)", 1)[1].split(";;", 1)[0]
    assert "crontab -l" in stopped and "grep -v" in stopped, "stopping takes the line out again"


def test_only_one_loop_runs_at_a_time():
    """Two loops on one pair would boot two kernels and place two campaigns on whichever won."""
    code = QUEUE.read_text(encoding="utf-8")
    assert code.count("flock -n") == 2, "the @reboot line and the loop it starts"


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
        assert len(self._tools()) == 11, "ten runnable plus wrk2's pair"

    @pytest.mark.parametrize("tool", ["vegeta", "hey", "k6", "wrk2", "valkey-benchmark",
                                      "memtier_benchmark", "rdkafka_performance",
                                      "kafka-end-to-end", "kafka-producer-perf",
                                      "rabbitmq-perftest", "nats-latency"])
    def test_each_one_is_fetched_or_built_by_the_install_step(self, tool):
        """The invariant that was missing. A tool named in the table and nowhere else in the
        step is a tool the step cannot produce, and every run of it fails hours later."""
        install = (KIT / "tools.sh").read_text(encoding="utf-8").split("install () {", 1)[1]
        builders = {"vegeta": "go_tool vegeta", "hey": "go_tool hey", "k6": "go_tool k6",
                    "wrk2": "git_build wrk2", "valkey-benchmark": "git_build valkey",
                    "memtier_benchmark": "git_build memtier",
                    "rdkafka_performance": "git_build librdkafka",
                    "kafka-end-to-end": "get_kafka", "kafka-producer-perf": "get_kafka",
                    "rabbitmq-perftest": "get_perftest", "nats-latency": "go_tool nats"}
        assert builders[tool] in install, "%s has nothing that installs it" % tool

    def test_a_tool_that_will_not_build_does_not_stop_the_other_nine(self):
        """A block reporting on nine tools is worth more than one reporting on none because a
        single upstream moved."""
        text = (KIT / "tools.sh").read_text(encoding="utf-8")
        for helper in ("go_tool () {", "git_build () {", "get_kafka () {", "get_perftest () {"):
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
        assert "stress-ng --cpu \"$want_cpus\" --cpu-load \"$adjusted\"" in block
        assert 'kill "$stress_pid"' in block, "the first one is stopped before the second starts"

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
