"""Tests for scripts/run_facts.py: a run's interrupt and scheduler facts, read from a fake machine
built to known answers, and once from a real kernel.

The fake machine is an Azure driver as /proc, /sys and /boot show it: four CPUs, an accelerated
card's interrupts beside the machine's others, the 6.8 Azure kernel's build options, and the
processes a loaded run of block U has running, the clients behind their sudo wrappers and
stress-ng with its workers. Each test changes one thing and says what it must decide.
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tests"))

import run_facts as rf  # noqa: E402
from posix_shell import linux_bash  # noqa: E402

RELEASE = "6.8.0-1064-azure"

#: /proc/interrupts with four CPUs online: two of the card's queues (mlx5), a MANA queue, an ethN
#: queue and a Hyper-V network line, beside interrupts that are not the network's, the lines the
#: kernel prints without a number, one with too few columns to name anything, and a stray line.
INTERRUPTS = (
    "           CPU0       CPU1       CPU2       CPU3       \n"
    "  8:          0          0          0          0   IO-APIC   8-edge      rtc0\n"
    " 24:          0          0          0       1234  Hyper-V PCIe MSI 1048576-edge      "
    "mlx5_async0@pci:7870:00:02.0\n"
    " 25:       5678          0          0          0  Hyper-V PCIe MSI 1048577-edge      "
    "mlx5_comp0@pci:7870:00:02.0\n"
    " 26:          1          2          3          4  Hyper-V PCIe MSI 2-edge      "
    "mana_q0@pci:7870:00:00.0\n"
    " 27:          0          0          0          0   PCI-MSI 524288-edge      eth0-TxRx-0\n"
    " 28:          0          0          0          0   VMBus 3-edge      hv_netvsc\n"
    " 29:          0          0\n"
    "NMI:          0          0          0          0   Non-maskable interrupts\n"
    "HYP:       1000       2000       3000       4000   Hypervisor callback interrupts\n"
    "ERR:          0\n"
    "a line without a colon\n")

#: The build options of the kind the 6.8 Azure kernel's config holds, among some that are not kept.
CONFIG = (
    "# Kernel hacking\n"
    "CONFIG_PREEMPT_BUILD=y\n"
    "# CONFIG_PREEMPT_NONE is not set\n"
    "CONFIG_PREEMPT_VOLUNTARY=y\n"
    "# CONFIG_PREEMPT is not set\n"
    "CONFIG_PREEMPT_COUNT=y\n"
    "CONFIG_PREEMPTION=y\n"
    "CONFIG_PREEMPT_DYNAMIC=y\n"
    "CONFIG_HZ_250=y\n"
    "# CONFIG_HZ_1000 is not set\n"
    "CONFIG_HZ=250\n"
    "# CONFIG_IRQ_TIME_ACCOUNTING is not set\n"
    "CONFIG_PARAVIRT_TIME_ACCOUNTING=y\n"
    "CONFIG_SCHED_INFO=y\n"
    "CONFIG_SCHEDSTATS=y\n"
    "CONFIG_SCHED_AUTOGROUP=y\n"
    "CONFIG_SCHED_DEBUG=y\n"
    "CONFIG_SCHED_INFO_EXTRA=y\n"
    "CONFIG_NO_HZ_IDLE=y\n")

KEPT = ["CONFIG_PREEMPT_BUILD=y", "# CONFIG_PREEMPT_NONE is not set", "CONFIG_PREEMPT_VOLUNTARY=y",
        "# CONFIG_PREEMPT is not set", "CONFIG_PREEMPT_COUNT=y", "CONFIG_PREEMPTION=y",
        "CONFIG_PREEMPT_DYNAMIC=y", "CONFIG_HZ_250=y", "# CONFIG_HZ_1000 is not set",
        "CONFIG_HZ=250", "# CONFIG_IRQ_TIME_ACCOUNTING is not set",
        "CONFIG_PARAVIRT_TIME_ACCOUNTING=y", "CONFIG_SCHED_INFO=y", "CONFIG_SCHEDSTATS=y",
        "CONFIG_SCHED_AUTOGROUP=y"]

#: A thread's stat line as Linux writes it, for a python3 thread at SCHED_FIFO 80: its priority
#: field (18) is -81, the kernel's -1 less the real-time priority, the processor (39) is 2,
#: rt_priority (40) is 80 and the policy (41) is 1.
FIFO_80 = ("{tid} ({comm}) S 12340 12345 12300 34816 12345 4194560 1630 0 0 0 3 1 0 0 -81 0 3 0 "
           "8657284 26083328 2414 18446744073709551615 94595393007616 94595395851121 "
           "140724662214144 0 0 0 0 16781312 134217730 0 0 0 17 2 80 1 0 0 0 94595396473008 "
           "94595396666008 94595414171648 140724662219621 140724662219646 140724662219646 "
           "140724662222823 0\n")
#: The same at normal priority: priority 20, nice 0, rt_priority 0, policy 0.
OTHER = FIFO_80.replace(" -81 0 3 0 ", " 20 0 3 0 ").replace(" 17 2 80 1 ", " 17 5 0 0 ")


def argv(*words):
    return b"\0".join(w.encode("utf-8") for w in words) + b"\0"


def machine():
    """The fake driver's files, by path under its root."""
    files = {
        "proc/interrupts": INTERRUPTS,
        "proc/irq/24/smp_affinity_list": "0-3\n", "proc/irq/24/effective_affinity_list": "3\n",
        "proc/irq/25/smp_affinity_list": "0-3\n", "proc/irq/25/effective_affinity_list": "0\n",
        "proc/irq/26/smp_affinity_list": "0-3\n",
        "proc/irq/8/smp_affinity_list": "0-3\n",
        "proc/sys/kernel/osrelease": RELEASE + "\n",
        "boot/config-" + RELEASE: CONFIG,
        "proc/sys/kernel/sched_rt_runtime_us": "950000\n",
        "proc/sys/kernel/sched_rt_period_us": "1000000\n",
        "proc/sys/kernel/sched_autogroup_enabled": "1\n",
        "proc/cmdline": "BOOT_IMAGE=/boot/vmlinuz-%s root=PARTUUID=0b1c ro console=ttyS0\n" % RELEASE,
        "sys/class/net/eth0/address": "60:45:bd:e9:60:ba\n",
        # Plan version 47 (23 Oct 2026): four CPUs online, two cores of two threads each, the last
        # CPU's topology not written, and an entry of the folder that is no CPU.
        "sys/devices/system/cpu/online": "0-3\n",
        "sys/devices/system/cpu/cpu0/topology/thread_siblings_list": "0-1\n",
        "sys/devices/system/cpu/cpu1/topology/thread_siblings_list": "0-1\n",
        "sys/devices/system/cpu/cpu2/topology/thread_siblings_list": "2-3\n",
        "sys/devices/system/cpu/cpu3/online": "1\n",
        "sys/devices/system/cpu/cpufreq/boost": "1\n",
        # The consumer, behind its namespace's sudo, at real-time priority: its main thread, one
        # whose name holds spaces and brackets, and one whose stat line is not one. Plan version
        # 47: the CPUs each may run on, one status file without the line, and one missing.
        "proc/100/cmdline": argv("python3", "scripts/kafka_consumer.py", "--run-id", "r1"),
        "proc/100/comm": "python3\n",
        "proc/100/task/100/stat": FIFO_80.format(tid=100, comm="python3"),
        "proc/100/task/100/status": "Name:\tpython3\nCpus_allowed:\t8\nCpus_allowed_list:\t3\n",
        "proc/100/task/101/status": "Name:\tmy (odd) name\n",
        "proc/100/task/101/stat": OTHER.format(tid=101, comm="my (odd) name"),
        "proc/100/task/102/stat": "102 python3 S\n",
        "proc/100/task/notes": "",
        "proc/100/cgroup": "0::/user.slice/user-1000.slice/session-3.scope\n\n",
        "proc/100/autogroup": "/autogroup-42 nice 0\n",
        # The producer's sudo, gone by the time its threads were looked for.
        "proc/110/cmdline": argv("sudo", "chrt", "-f", "80", "python3",
                                 "scripts/redis_producer.py"),
        "proc/110/comm": "sudo\n",
        # stress-ng: the parent, a worker by its own name, and one found by the program it runs.
        "proc/120/cmdline": argv("stress-ng", "--cpu", "4", "--cpu-load", "72", "--timeout",
                                 "3600s"),
        "proc/120/comm": "stress-ng\n",
        "proc/120/task/120/stat": OTHER.format(tid=120, comm="stress-ng"),
        "proc/120/cgroup": "0::/user.slice\n",
        "proc/120/autogroup": "/autogroup-7 nice 0\n",
        "proc/121/cmdline": argv("stress-ng", "--cpu", "4", "--cpu-load", "72", "--timeout",
                                 "3600s"),
        "proc/121/comm": "stress-ng-cpu\n",
        "proc/121/task/.keep": "",
        "proc/122/cmdline": argv("/usr/bin/stress-ng", "--cpu", "4"),
        # What is not the run's: the campaign, a pkill that names a client in its pattern, a
        # kernel thread, and a process gone before its command line was read.
        "proc/130/cmdline": argv("bash", "cloud/azure/campaign.sh", "runs/azure/queues/u50.csv"),
        "proc/130/comm": "bash\n",
        "proc/131/cmdline": argv("pkill", "-f", "kafka_producer.py|redis_producer.py"),
        "proc/131/comm": "pkill\n",
        "proc/140/cmdline": b"",
        "proc/140/comm": "kworker/0:1\n",
        "proc/150/comm": "python3\n",
        "proc/self/cmdline": argv("python3"),
        # Plan version 47 (23 Oct 2026): two of the run's own working processes, a capture behind
        # its sudo and the utilisation sampler.
        "proc/160/cmdline": argv("sudo", "tcpdump", "-i", "eth0", "-w", "x.pcap"),
        "proc/160/task/160/stat": OTHER.format(tid=160, comm="sudo"),
        "proc/161/cmdline": argv("python3", "scripts/util_sampler.py", "--out", "u.csv"),
        "proc/161/task/161/stat": OTHER.format(tid=161, comm="python3"),
    }
    return files


def tree(tmp_path, files=None, drop=()):
    """The fake machine under tmp_path, less the paths in `drop`; returns its root."""
    root = tmp_path / "root"
    for rel, content in (machine() if files is None else files).items():
        if rel in drop:
            continue
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return str(root)


#: What the host's four commands print on a driver.
COMMANDS = {rf.STRESS_NG_VERSION: ("stress-ng, version 0.13.12 (gcc 11.2, x86_64 Linux)", None),
            rf.IRQBALANCE: ("active", None),
            rf.UNAME: ("Linux driver 6.8.0-1064-azure #67-Ubuntu SMP x86_64 GNU/Linux", None),
            rf.CLIENT_LIBRARIES: ("python 3.10.12 kafka-python 2.3.2 redis-py 5.0.1", None)}


def fake_run(answers=None):
    """A command runner that answers from `answers` and remembers what it was asked."""
    asked = []

    def run(argv_):
        asked.append(tuple(argv_))
        return (answers or COMMANDS)[tuple(argv_)]
    run.asked = asked
    return run


class TestTheHost:

    def test_every_fact_of_a_driver_is_read(self, tmp_path):
        run = fake_run()
        facts = rf.host_facts(tree(tmp_path), run)
        assert run.asked == [rf.STRESS_NG_VERSION, rf.IRQBALANCE, rf.UNAME, rf.CLIENT_LIBRARIES]
        assert facts["client_libraries"] == "python 3.10.12 kafka-python 2.3.2 redis-py 5.0.1"
        assert facts["kind"] == "host" and isinstance(facts["t_ns"], int)
        assert facts["stress_ng_version"].startswith("stress-ng, version 0.13.12")
        assert facts["irqbalance"] == "active"
        assert facts["uname"].startswith("Linux driver 6.8.0-1064-azure")
        assert facts["stress_ng"] == [
            {"pid": 120, "comm": "stress-ng", "cmdline": "stress-ng --cpu 4 --cpu-load 72 "
                                                         "--timeout 3600s"},
            {"pid": 121, "comm": "stress-ng-cpu", "cmdline": "stress-ng --cpu 4 --cpu-load 72 "
                                                             "--timeout 3600s"},
            {"pid": 122, "comm": None, "cmdline": "/usr/bin/stress-ng --cpu 4"}]
        assert facts["kernel_config"] == KEPT
        assert facts["sched"] == {"sched_rt_runtime_us": "950000",
                                  "sched_rt_period_us": "1000000", "sched_schedstats": None,
                                  "sched_autogroup_enabled": "1"}
        assert facts["cmdline"].startswith("BOOT_IMAGE=/boot/vmlinuz-6.8.0-1064-azure")
        assert facts["eth0_address"] == "60:45:bd:e9:60:ba"
        assert facts["cpu_topology"] == {"online": "0-3", "thread_siblings_list": {
            "0": "0-1", "1": "0-1", "2": "2-3", "3": None}}
        assert list(facts["unread"]) == ["sched.sched_schedstats"]
        assert facts["unread"]["sched.sched_schedstats"].startswith("cannot be read: ")

    def test_the_networks_interrupts_with_the_cpus_each_may_and_does_run_on(self, tmp_path):
        """Numbered lines only, and only those whose name mentions the network's words; the
        counts are not part of the name, and an affinity file that is not there is unread."""
        irqs, why = rf.network_irqs(tree(tmp_path))
        assert why is None
        assert [(i["irq"], i["smp_affinity_list"], i["effective_affinity_list"])
                for i in irqs] == [(24, "0-3", "3"), (25, "0-3", "0"), (26, "0-3", None),
                                   (27, None, None), (28, None, None)]
        assert irqs[0]["name"] == "Hyper-V PCIe MSI 1048576-edge mlx5_async0@pci:7870:00:02.0"
        assert irqs[0]["unread"] == {}
        assert list(irqs[2]["unread"]) == ["effective_affinity_list"]
        assert sorted(irqs[3]["unread"]) == ["effective_affinity_list", "smp_affinity_list"]

    def test_an_empty_interrupt_table_names_no_interrupt(self, tmp_path):
        files = dict(machine(), **{"proc/interrupts": ""})
        assert rf.network_irqs(tree(tmp_path, files)) == ([], None)

    @pytest.mark.parametrize("drop,fact,fragment", [
        ("proc/interrupts", "network_irqs", "cannot be read: "),
        ("proc/sys/kernel/osrelease", "kernel_config", "the kernel's release cannot be read: "),
        ("boot/config-" + RELEASE, "kernel_config", "cannot be read: "),
        ("proc/cmdline", "cmdline", "cannot be read: "),
        ("sys/class/net/eth0/address", "eth0_address", "cannot be read: ")])
    def test_a_file_that_is_not_there_is_null_with_the_reason(self, tmp_path, drop, fact,
                                                              fragment):
        facts = rf.host_facts(tree(tmp_path, drop=(drop,)), fake_run())
        assert facts[fact] is None and facts["unread"][fact].startswith(fragment)

    def test_a_command_that_cannot_run_is_null_with_the_reason(self, tmp_path):
        answers = dict(COMMANDS)
        answers[rf.STRESS_NG_VERSION] = (None, "stress-ng --version cannot run: not found")
        answers[rf.IRQBALANCE] = (None, "systemctl is-active irqbalance printed nothing")
        facts = rf.host_facts(tree(tmp_path), fake_run(answers))
        assert facts["stress_ng_version"] is None and facts["irqbalance"] is None
        assert facts["unread"]["stress_ng_version"] == "stress-ng --version cannot run: not found"
        assert facts["unread"]["irqbalance"].startswith("systemctl is-active irqbalance")

    def test_a_machine_whose_processes_cannot_be_listed_still_gives_the_rest(self, tmp_path):
        files = {rel: text for rel, text in machine().items() if not rel.startswith("proc/")}
        facts = rf.host_facts(tree(tmp_path, files), fake_run())
        assert facts["stress_ng"] is None
        assert facts["unread"]["stress_ng"].startswith("the processes cannot be listed: ")
        assert facts["eth0_address"] == "60:45:bd:e9:60:ba"


class TestTheClients:

    def test_each_client_and_each_stress_ng_with_every_thread_it_has(self, tmp_path):
        facts = rf.client_facts(tree(tmp_path))
        assert facts["kind"] == "clients" and facts["unread"] == {}
        found = {p["pid"]: p for p in facts["processes"]}
        assert sorted(found) == [100, 110, 120, 121, 122, 160, 161]
        assert {pid: p["names"] for pid, p in found.items()} == {
            100: "kafka_consumer.py", 110: "redis_producer.py", 120: "stress-ng",
            121: "stress-ng", 122: "stress-ng", 160: "tcpdump", 161: "util_sampler.py"}
        consumer = found[100]
        assert consumer["cmdline"] == "python3 scripts/kafka_consumer.py --run-id r1"
        assert consumer["cgroup"] == ["0::/user.slice/user-1000.slice/session-3.scope"]
        assert consumer["autogroup"] == "/autogroup-42 nice 0"
        assert consumer["unread"] == {}
        main, odd, broken = consumer["threads"]
        assert main == {"tid": 100, "comm": "python3", "policy": 1, "policy_name": "SCHED_FIFO",
                        "rt_priority": 80, "cpus_allowed_list": "3", "unread": {}}
        assert odd == {"tid": 101, "comm": "my (odd) name", "policy": 0,
                       "policy_name": "SCHED_OTHER", "rt_priority": 0, "cpus_allowed_list": None,
                       "unread": {"status": "it has no Cpus_allowed_list: line"}}
        assert broken["tid"] == 102 and broken["policy"] is None
        assert broken["unread"]["stat"].startswith("the line cannot be read: ")
        assert broken["unread"]["status"].startswith("cannot be read: ")
        assert found[120]["threads"][0]["comm"] == "stress-ng"

    def test_what_a_vanished_process_leaves_unread_is_null_with_the_reason(self, tmp_path):
        found = {p["pid"]: p for p in rf.client_facts(tree(tmp_path))["processes"]}
        gone = found[110]
        assert (gone["threads"], gone["cgroup"], gone["autogroup"]) == (None, None, None)
        assert sorted(gone["unread"]) == ["autogroup", "cgroup", "threads"]
        assert gone["unread"]["threads"].startswith("cannot be listed: ")
        worker = found[121]
        assert worker["threads"] == [] and "threads" not in worker["unread"]

    def test_a_thread_whose_stat_cannot_be_read_is_null_with_the_reason(self, tmp_path):
        root = tree(tmp_path)
        found = rf.thread_facts(root, "100", "199")
        assert found["tid"] == 199 and found["comm"] is None
        assert found["unread"]["stat"].startswith("cannot be read: ")

    def test_the_policies_by_name(self):
        assert [rf.POLICIES[n] for n in (0, 1, 2, 3, 5, 6)] == [
            "SCHED_OTHER", "SCHED_FIFO", "SCHED_RR", "SCHED_BATCH", "SCHED_IDLE",
            "SCHED_DEADLINE"]
        assert rf.thread_stat(OTHER.format(tid=7, comm="x").replace(" 17 5 0 0 ", " 17 5 0 9 "))[
            "policy_name"] is None, "a policy this table does not know is kept by its number"

    @pytest.mark.parametrize("line", ["7 python3 S 1", "7 (python3) S 1 2 3",
                                      FIFO_80.format(tid=7, comm="x").replace(" 80 1 ", " x 1 ")])
    def test_a_line_that_is_not_a_stat_line_is_refused(self, line):
        with pytest.raises((ValueError, IndexError)):
            rf.thread_stat(line)

    def test_a_machine_whose_processes_cannot_be_listed_says_so(self, tmp_path):
        facts = rf.client_facts(str(tmp_path / "nothing"))
        assert facts["processes"] is None
        assert facts["unread"]["processes"].startswith("the processes cannot be listed: ")


#: A Python of its own for a command to run: isolated and without its site hooks, so that nothing
#: but the command speaks on its streams (under --cov, a site hook of coverage's writes there).
PYTHON = [sys.executable, "-I", "-S", "-c"]


class TestCommands:
    """The host's commands, run for real: what each printed, or why it could not say."""

    def test_what_a_command_prints_is_the_fact(self):
        assert rf.run_command(PYTHON + ["print(' inactive ')"]) == ("inactive", None)

    def test_a_command_that_says_something_and_fails_has_still_said_it(self):
        """systemctl is-active prints "inactive" and exits 3 for a service that is stopped."""
        said = rf.run_command(PYTHON + ["print('inactive'); raise SystemExit(3)"])
        assert said == ("inactive", None)

    def test_a_command_that_speaks_on_its_error_stream_and_succeeds(self):
        said = rf.run_command(PYTHON + ["import sys; sys.stderr.write('version 1.2\\n')"])
        assert said == ("version 1.2", None)

    @pytest.mark.parametrize("code,ending", [
        ("import sys; sys.stderr.write('no such unit\\n'); raise SystemExit(4)",
         "printed nothing and exited 4: no such unit"),
        ("raise SystemExit(1)", "printed nothing and exited 1"),
        ("pass", "printed nothing and exited 0")])
    def test_a_command_that_says_nothing_is_null_with_the_reason(self, code, ending):
        value, why = rf.run_command(PYTHON + [code])
        assert value is None and why.endswith(ending), why

    def test_a_command_that_is_not_there_cannot_run(self):
        value, why = rf.run_command(["no-such-program-sbl-43", "--version"])
        assert value is None and why.startswith("no-such-program-sbl-43 --version cannot run: ")

    def test_a_command_that_does_not_finish_is_given_up(self):
        value, why = rf.run_command(PYTHON + ["import time; time.sleep(5)"], timeout=0.2)
        assert value is None and why.endswith("did not finish within 0.2 s")


class TestMain:

    def test_host_writes_its_facts_where_it_is_told(self, tmp_path):
        out, printed = tmp_path / "run_facts.json", io.StringIO()
        code = rf.main(["--root", tree(tmp_path), "host", "--out", str(out)], out=printed,
                       run=fake_run())
        assert code == 0 and printed.getvalue().startswith("host facts -> ")
        assert printed.getvalue().endswith(", 1 unread\n")
        facts = json.loads(out.read_text(encoding="utf-8"))
        assert facts["kind"] == "host" and facts["kernel_config"] == KEPT

    def test_clients_writes_its_facts_where_it_is_told(self, tmp_path):
        out, printed = tmp_path / "run_facts_clients.json", io.StringIO()
        code = rf.main(["--root", tree(tmp_path), "clients", "--out", str(out)], out=printed)
        assert code == 0 and printed.getvalue().endswith(", 0 unread\n")
        facts = json.loads(out.read_text(encoding="utf-8"))
        assert [p["pid"] for p in facts["processes"]] == [100, 110, 120, 121, 122, 160, 161]

    def test_a_file_that_cannot_be_written_is_the_one_error(self, tmp_path):
        printed = io.StringIO()
        code = rf.main(["--root", tree(tmp_path), "clients", "--out",
                        str(tmp_path / "no-such-folder" / "x.json")], out=printed)
        assert code == 2 and printed.getvalue().startswith("ERROR: ")


def test_on_a_real_kernel_the_clients_are_found_and_their_threads_read_as_it_schedules_them():
    """Not a made-up world: on Linux (through WSL on Windows), a stand-in for a client, run under
    SCHED_BATCH, with a second thread whose name holds spaces and brackets, is found by the word
    of its command line and read from the kernel's own /proc, and the host's facts are written
    on a machine that lacks some of them."""
    script = r'''
set -e
work=$(mktemp -d)
cat > "$work/client.py" <<'PY'
import os, sys, threading, time
done = threading.Event()
t = threading.Thread(target=done.wait, daemon=True)
t.start()
with open("/proc/self/task/%d/comm" % t.native_id, "w") as fh:
    fh.write("my (odd) name")
open(sys.argv[2], "w").close()
time.sleep(30)
PY
chrt -b 0 python3 "$work/client.py" scripts/kafka_consumer.py "$work/ready" &
client=$!
for _ in $(seq 1 100); do [ -f "$work/ready" ] && break; sleep 0.1; done
python3 "$REPO/scripts/run_facts.py" clients --out "$work/clients.json" > /dev/null
python3 "$REPO/scripts/run_facts.py" host --out "$work/host.json" > /dev/null
echo "stat=$(cat /proc/$client/stat)"
kill "$client"
echo "pid=$client"
echo "clients=$(tr -d '\n' < "$work/clients.json")"
echo "host=$(tr -d '\n' < "$work/host.json")"
rm -rf "$work"
'''
    done = linux_bash(script, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    said = dict(line.split("=", 1) for line in done.stdout.splitlines() if "=" in line)
    clients, host = json.loads(said["clients"]), json.loads(said["host"])
    mine = [p for p in clients["processes"] if p["pid"] == int(said["pid"])]
    assert len(mine) == 1 and mine[0]["names"] == "kafka_consumer.py"
    threads = {t["comm"]: t for t in mine[0]["threads"]}
    assert sorted(threads) == ["my (odd) name", "python3"]
    for thread in threads.values():
        assert (thread["policy"], thread["policy_name"], thread["rt_priority"]) == (
            3, "SCHED_BATCH", 0), thread
    # The fake machine's stat lines have the kernel's own fields, the policy where it puts it.
    real = said["stat"].rsplit(") ", 1)[1].split()
    assert real[rf.POLICY_AT] == "3" and real[rf.RT_PRIORITY_AT] == "0"
    for line in (FIFO_80, OTHER):
        assert len(line.format(tid=1, comm="x").rsplit(") ", 1)[1].split()) == len(real)
    assert host["kind"] == "host" and isinstance(host["network_irqs"], list)
    assert host["uname"].startswith("Linux ")
    for name, why in host["unread"].items():
        assert why, name
    assert set(host) == {"kind", "t_ns", "stress_ng_version", "stress_ng", "irqbalance",
                         "network_irqs", "kernel_config", "sched", "cmdline", "uname",
                         "client_libraries", "eth0_address", "cpu_topology", "unread"}
    assert host["cpu_topology"]["online"] and host["cpu_topology"]["thread_siblings_list"]


# --- Plan version 47 (23 Oct 2026): the topology, the softirq's own counters and the brokers'
# images and versions.

class TestTheTopology:

    def test_a_machine_whose_online_cpus_cannot_be_read_says_so(self, tmp_path):
        facts = rf.host_facts(tree(tmp_path, drop=("sys/devices/system/cpu/online",)), fake_run())
        assert facts["cpu_topology"] is None
        assert facts["unread"]["cpu_topology"].startswith("the online CPUs cannot be read: ")

    def test_the_cpus_a_thread_may_run_on_are_its_status_files_line(self):
        assert rf.cpus_allowed("Name:\tx\nCpus_allowed_list:\t0-5,7\n") == "0-5,7"
        assert rf.cpus_allowed("Name:\tx\n") is None


SOFTNET = "0000abcd 00000001 00000005 00000000\n00000010 00000000 00000000 00000000\n"
#: A ksoftirqd thread's stat line: utime (field 14) 7 and stime (field 15) 9.
KSOFTIRQD_STAT = OTHER.format(tid=15, comm="ksoftirqd/0").replace(" 3 1 0 0 20 ", " 7 9 0 0 20 ")


def softirq_tree(tmp_path, softnet=SOFTNET, schedstat="1500 300 7\n"):
    files = {"proc/net/softnet_stat": softnet, "proc/15/comm": "ksoftirqd/0\n",
             "proc/15/stat": KSOFTIRQD_STAT, "proc/16/comm": "ksoftirqd/1\n",
             "proc/16/schedstat": "garbled\n", "proc/17/comm": "python3\n"}
    if schedstat is not None:
        files["proc/15/schedstat"] = schedstat
    return tree(tmp_path, files)


class TestTheSoftirq:

    def test_each_cpus_time_squeeze_and_each_ksoftirqds_time(self, tmp_path):
        facts = rf.softirq_facts(softirq_tree(tmp_path))
        assert facts["kind"] == "softirq" and facts["unread"] == {}
        assert facts["softnet"] == [
            {"line": 0, "processed": 0xabcd, "dropped": 1, "time_squeeze": 5},
            {"line": 1, "processed": 0x10, "dropped": 0, "time_squeeze": 0}]
        first, second = facts["ksoftirqd"]
        assert (first["pid"], first["comm"], first["run_ns"], first["wait_ns"], first["slices"],
                first["utime"], first["stime"], first["unread"]) == (
            15, "ksoftirqd/0", 1500, 300, 7, 7, 9, {})
        assert second["run_ns"] is None and second["unread"]["schedstat"].startswith(
            "it is not a schedstat line")
        assert second["unread"]["stat"].startswith("cannot be read: ")

    def test_a_thread_whose_schedstat_is_gone_says_why(self, tmp_path):
        first = rf.softirq_facts(softirq_tree(tmp_path, schedstat=None))["ksoftirqd"][0]
        assert first["unread"]["schedstat"].startswith("cannot be read: ")

    @pytest.mark.parametrize("softnet,why", [(None, "cannot be read: "),
                                             ("zz 0 0\n", "line 0 is not a softnet_stat line")])
    def test_a_softnet_that_cannot_be_read_says_why(self, tmp_path, softnet, why):
        files = {"proc/15/comm": "ksoftirqd/0\n"}
        if softnet is not None:
            files["proc/net/softnet_stat"] = softnet
        facts = rf.softirq_facts(tree(tmp_path, files))
        assert facts["softnet"] is None and facts["unread"]["softnet"].startswith(why)

    def test_a_machine_whose_processes_cannot_be_listed_says_so(self, tmp_path):
        facts = rf.softirq_facts(str(tmp_path / "nothing"))
        assert facts["ksoftirqd"] is None
        assert facts["unread"]["ksoftirqd"].startswith("the processes cannot be listed: ")


#: What the broker's commands print, for each broker running.
BROKER_COMMANDS = {
    ("docker", "inspect", "--format", "{{.Config.Image}} {{.Image}}", "broker"):
        ("apache/kafka:4.1.1 sha256:aaa", None),
    ("docker", "inspect", "--format", "{{.Config.Image}} {{.Image}}", "redis"):
        ("redis:7.4.11@sha256:449 sha256:bbb", None),
    ("docker", "inspect", "--format", "{{.Config.Image}} {{.Image}}", "rabbitmq"):
        ("rabbitmq:4.3.7@sha256:ddb sha256:ccc", None),
    ("docker", "image", "inspect", "--format", "{{json .RepoDigests}}", "sha256:aaa"):
        ('["apache/kafka@sha256:111"]', None),
    ("docker", "image", "inspect", "--format", "{{json .RepoDigests}}", "sha256:bbb"):
        ('["redis@sha256:449"]', None),
    ("docker", "image", "inspect", "--format", "{{json .RepoDigests}}", "sha256:ccc"):
        ("not json", None),
    rf.KAFKA_LIBS: ("connect-api-4.1.1.jar\nkafka-clients-4.1.1.jar\nkafka_2.13-4.1.1-test.jar\n"
                    "kafka_2.13-4.1.1.jar\nkafka-server-4.1.1.jar\n", None),
    rf.REDIS_INFO: ("# Server\r\nredis_version:7.4.11\r\nredis_mode:standalone", None),
    rf.RABBITMQ_VERSION: ("Asking node rabbit@x for its RabbitMQ version...\n4.3.7", None)}


class FakeSocket:
    def __init__(self, greeting):
        self.greeting = greeting

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def settimeout(self, _seconds):
        pass

    def makefile(self, _mode):
        return io.BytesIO(self.greeting)


def greeting(line):
    def connect(address, timeout):
        assert (address, timeout) == (rf.NATS_ADDRESS, 5)
        if line is None:
            raise ConnectionRefusedError("refused")
        return FakeSocket(line)
    return connect


class TestTheBrokers:

    def test_each_brokers_image_its_digest_and_its_servers_version(self):
        facts = rf.broker_facts(fake_run(BROKER_COMMANDS), greeting(
            b'INFO {"server_id":"N1","version":"2.15.1","jetstream":true}\r\n'))
        assert facts["kind"] == "broker"
        assert facts["kafka"] == {"container": "broker", "image": {
            "image": "apache/kafka:4.1.1", "image_id": "sha256:aaa",
            "repo_digests": ["apache/kafka@sha256:111"]}, "version": "4.1.1"}
        assert facts["redis"]["version"] == "7.4.11"
        assert facts["redis"]["image"]["repo_digests"] == ["redis@sha256:449"]
        assert facts["rabbitmq"]["version"] == "4.3.7"
        assert facts["rabbitmq"]["image"]["repo_digests"] is None
        assert facts["unread"] == {"rabbitmq.image": "its digests are not JSON: 'not json'"}
        assert facts["nats"] == {"version": "2.15.1", "jetstream": True, "server_id": "N1"}

    def test_a_broker_that_is_not_running_is_null_with_the_reason(self):
        answers = {key: (None, "docker printed nothing and exited 1") for key in BROKER_COMMANDS}
        answers[rf.REDIS_INFO] = ("# Server\r\nredis_mode:standalone", None)
        facts = rf.broker_facts(fake_run(answers), greeting(None))
        assert facts["kafka"]["image"] is None and facts["redis"]["version"] is None
        assert facts["rabbitmq"]["version"] is None and facts["nats"] is None
        assert facts["unread"]["redis.version"] == "INFO server names no redis_version"
        assert facts["unread"]["nats"].startswith("no NATS server answers at 127.0.0.1:4222")
        assert facts["unread"]["kafka.image"] == "docker printed nothing and exited 1"
        assert facts["kafka"]["version"] is None
        assert facts["unread"]["kafka.version"] == "docker printed nothing and exited 1"

    def test_a_kafka_whose_libraries_hold_no_server_jar_says_so(self):
        answers = dict(BROKER_COMMANDS)
        answers[rf.KAFKA_LIBS] = ("kafka-clients-4.1.1.jar\nkafka_2.13-4.1.1-test.jar\n", None)
        facts = rf.broker_facts(fake_run(answers), greeting(None))
        assert facts["kafka"]["version"] is None
        assert facts["unread"]["kafka.version"] == (
            "/opt/kafka/libs holds no kafka_<scala>-<version>.jar")

    @pytest.mark.parametrize("line,why", [(b"-ERR 'x'\r\n", "the server's first line is not"),
                                          (b"INFO {nope\r\n", "its INFO is not JSON")])
    def test_a_nats_server_that_greets_otherwise_says_why(self, line, why):
        value, said = rf.nats_info(rf.NATS_ADDRESS, greeting(line))
        assert value is None and said.startswith(why)


class TestPlanVersion47sMain:

    def test_softirq_writes_its_facts_where_it_is_told(self, tmp_path):
        out, printed = tmp_path / "softirq.json", io.StringIO()
        code = rf.main(["--root", softirq_tree(tmp_path), "softirq", "--out", str(out)],
                       out=printed)
        assert code == 0 and printed.getvalue().endswith(", 0 unread\n")
        assert json.loads(out.read_text(encoding="utf-8"))["kind"] == "softirq"

    def test_broker_writes_its_facts_to_standard_output_and_says_so_on_its_error_stream(
            self, capsys):
        printed = io.StringIO()
        code = rf.main(["broker", "--out", "-"], out=printed, run=fake_run(BROKER_COMMANDS),
                       connect=greeting(b'INFO {"version":"2.15.1","jetstream":true}\r\n'))
        assert code == 0 and json.loads(printed.getvalue())["kind"] == "broker"
        assert capsys.readouterr().err.startswith("broker facts -> -, 1 unread")
