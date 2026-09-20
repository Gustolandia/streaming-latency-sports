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
    assert [p.name for p in SHELL] == ["campaign.sh", "machine_facts.sh", "pilot.sh",
                                       "replicate_oracle.sh", "session.sh", "stage0.sh",
                                       "stage1.sh"]


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
    assert 'session) UP_TO_MS="${UP_TO_MS:-8}"; C0_ROUNDS=2 ;;' in code, (
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
