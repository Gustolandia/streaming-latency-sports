"""Tests for scripts/cpu_placement.py: the core a run keeps for its consumer, the CPUs everything
else runs on, the receiver card's interrupts and its receive queues' steering (plan version 47).

Each machine is a fake /sys and /proc in a folder of its own, as the kernel lays them out: the x86
pairs' eight vCPUs on four cores, each core's two threads numbered N and N+4 or side by side, and
the Arm pair's eight CPUs with one thread a core.
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import cpu_placement as cp  # noqa: E402

#: /proc/interrupts on a driver: two of the accelerated card's queues, one of Hyper-V's, a timer.
INTERRUPTS = ("           CPU0       CPU1       CPU2       CPU3\n"
              " 24:          5          7          0          1  Hyper-V PCIe MSI 1048576-edge "
              "mlx5_comp0@pci:7870:00:02.0\n"
              " 25:          0          0          9          0  Hyper-V PCIe MSI 1048577-edge "
              "mlx5_comp1@pci:7870:00:02.0\n"
              "  8:          0          0          0          0  IO-APIC   8-edge      rtc0\n")


def machine(tmp_path, siblings, online="0-7", interrupts=INTERRUPTS, affinity=None,
            devices=None):
    """A fake root: `siblings` is {cpu: thread_siblings_list}; `affinity` is {irq: (may, does)};
    `devices` is {device: {queue: rps_cpus}}. Returns the root, as a string."""
    root = tmp_path / "root"
    files = {cp.ONLINE: online, "proc/interrupts": interrupts}
    for cpu, text in siblings.items():
        files[cp.SIBLINGS % cpu] = text
    for irq, (may, does) in (affinity or {24: ("0-7", "0"), 25: ("0-7", "2")}).items():
        files["proc/irq/%d/smp_affinity_list" % irq] = may
        files["proc/irq/%d/effective_affinity_list" % irq] = does
    for device, queues in (devices or {}).items():
        for queue, mask in queues.items():
            files["%s/%s/rps_cpus" % (cp.QUEUES % device, queue)] = mask
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    return str(root)


#: Four cores of two threads each, the second thread four above the first, as Azure's x86 pairs.
APART = {cpu: "%d,%d" % (cpu % 4, cpu % 4 + 4) for cpu in range(8)}
#: The same, with each core's threads side by side.
TOGETHER = {cpu: "%d-%d" % (cpu - cpu % 2, cpu - cpu % 2 + 1) for cpu in range(8)}
#: The Arm pair: one thread a core.
ARM = {cpu: str(cpu) for cpu in range(8)}


def run(*argv):
    printed = io.StringIO()
    code = cp.main(list(argv), out=printed)
    return code, printed.getvalue().strip()


class TestTheLists:

    @pytest.mark.parametrize("text,cpus", [("0-3,6", [0, 1, 2, 3, 6]), ("5", [5]),
                                           ("0,2-3\n", [0, 2, 3]), ("3,1,1", [1, 3])])
    def test_a_list_reads_as_the_kernel_writes_it(self, text, cpus):
        assert cp.parse_list(text) == cpus

    @pytest.mark.parametrize("text", ["", "a", "1-", "-1", "3-1", "1,,2", "1-2-3", "1, 2"])
    def test_anything_else_is_refused(self, text):
        with pytest.raises(ValueError):
            cp.parse_list(text)

    @pytest.mark.parametrize("cpus,text", [([0, 1, 2, 3, 6], "0-3,6"), ([5], "5"), ([], ""),
                                           ([7, 1, 2], "1-2,7")])
    def test_and_is_written_back_the_same_way(self, cpus, text):
        assert cp.format_list(cpus) == text


class TestTheCore:

    @pytest.mark.parametrize("siblings,words", [
        (APART, "3 7 0-2,4-6 0-2,4-6 6"), (TOGETHER, "6 7 0-5 0-5 6"), (ARM, "7 - 0-6 0-6 7")])
    def test_the_highest_core_is_kept_and_everything_else_runs_beside_it(self, tmp_path,
                                                                        siblings, words):
        out = tmp_path / "core.json"
        code, said = run("--root", machine(tmp_path, siblings), "core", "--out", str(out))
        assert (code, said) == (0, words)
        record = json.loads(out.read_text(encoding="utf-8"))
        consumer, _, kit, load, count = words.split()
        assert str(record["consumer_cpu"]) == consumer and record["kit_list"] == kit
        assert record["load_list"] == load and len(record["load_cpus"]) == int(count)
        assert record["sibling_load"] is False and record["rule"] == cp.RULE
        assert record["online"] == "0-7" and len(record["topology"]) == 8

    def test_the_sibling_is_loaded_where_the_setup_asks_and_nothing_else_moves(self, tmp_path):
        out = tmp_path / "core.json"
        code, said = run("--root", machine(tmp_path, TOGETHER), "core", "--sibling-load",
                         "--out", str(out))
        assert (code, said) == (0, "6 7 0-5 0-5,7 7")
        record = json.loads(out.read_text(encoding="utf-8"))
        assert record["siblings"] == [7] and record["kit_cpus"] == [0, 1, 2, 3, 4, 5]
        assert record["load_cpus"] == [0, 1, 2, 3, 4, 5, 7] and record["sibling_load"] is True

    def test_a_core_with_no_sibling_cannot_have_one_loaded(self, tmp_path):
        code, said = run("--root", machine(tmp_path, ARM), "core", "--sibling-load", "--out",
                         str(tmp_path / "core.json"))
        assert code == 1 and said == "ERROR: CPU 7's core has no other hardware thread to load"

    def test_only_the_online_cpus_count(self, tmp_path):
        """A5 takes CPUs offline at boot; an offline sibling is idle by being offline."""
        code, said = run("--root", machine(tmp_path, {0: "0,4", 1: "1,5"}, online="0-1"),
                         "core", "--out", str(tmp_path / "core.json"))
        assert (code, said) == (0, "1 - 0 0 1")

    def test_a_single_core_leaves_nothing_for_the_rest(self, tmp_path):
        code, said = run("--root", machine(tmp_path, {0: "0-1", 1: "0-1"}, online="0-1"),
                         "core", "--out", str(tmp_path / "core.json"))
        assert (code, said) == (0, "0 1 - - 0")

    @pytest.mark.parametrize("drop", [cp.ONLINE, cp.SIBLINGS % 3])
    def test_a_topology_that_cannot_be_read_is_an_error(self, tmp_path, drop):
        root = machine(tmp_path, APART)
        os.remove(os.path.join(root, drop))
        code, said = run("--root", root, "core", "--out", str(tmp_path / "core.json"))
        assert code == 1 and said.startswith("ERROR: ") and "cannot be read" in said


class TestTheInterrupts:

    def test_reading_them_moves_nothing(self, tmp_path):
        root, out = machine(tmp_path, APART), tmp_path / "before.json"
        assert run("--root", root, "irqs", "--out", str(out)) == (
            0, "OK the receiver's interrupts -> %s" % out)
        record = json.loads(out.read_text(encoding="utf-8"))
        assert [(i["irq"], i["smp_affinity_list"], i["effective_affinity_list"])
                for i in record["irqs"]] == [(24, "0-7", "0"), (25, "0-7", "2")]
        assert record["ok"] is True and record["set"] is None and record["refused"] == {}

    def test_they_are_moved_read_back_and_put_back(self, tmp_path):
        root = machine(tmp_path, APART)
        before, moved, back = (tmp_path / name for name in ("b.json", "s.json", "r.json"))
        run("--root", root, "irqs", "--out", str(before))
        assert run("--root", root, "irqs", "--set", "3", "--out", str(moved))[0] == 0
        record = json.loads(moved.read_text(encoding="utf-8"))
        assert [i["smp_affinity_list"] for i in record["irqs"]] == ["3", "3"]
        assert record["set"] == "3" and record["ok"] is True
        assert run("--root", root, "irqs", "--restore", str(before), "--out", str(back))[0] == 0
        assert [i["smp_affinity_list"] for i in json.loads(back.read_text(
            encoding="utf-8"))["irqs"]] == ["0-7", "0-7"]

    def test_a_move_the_kernel_refuses_is_recorded_and_fails(self, tmp_path):
        """The kernel refuses an interrupt whose affinity it manages itself; here the file
        cannot be written at all."""
        root = machine(tmp_path, APART)
        target = os.path.join(root, "proc/irq/25/smp_affinity_list")
        os.remove(target)
        os.mkdir(target)
        out = tmp_path / "s.json"
        assert run("--root", root, "irqs", "--set", "3", "--out", str(out)) == (
            1, "FAILED the receiver's interrupts -> %s" % out)
        refused = json.loads(out.read_text(encoding="utf-8"))["refused"]
        assert list(refused) == ["25"] and refused["25"].startswith("the kernel refused 3: ")

    def test_a_move_that_reads_back_otherwise_fails(self, tmp_path, monkeypatch):
        root, out = machine(tmp_path, APART), tmp_path / "s.json"
        monkeypatch.setattr(cp, "write_value", lambda path, value: None)
        assert run("--root", root, "irqs", "--set", "3", "--out", str(out))[0] == 1
        refused = json.loads(out.read_text(encoding="utf-8"))["refused"]
        assert refused == {"24": "read back as 0-7, not 3", "25": "read back as 0-7, not 3"}

    def test_a_card_with_no_interrupt_to_move_fails_and_a_reading_of_none_does_not(
            self, tmp_path):
        root = machine(tmp_path, APART, interrupts="           CPU0\n  8:  0  rtc0\n")
        out = tmp_path / "s.json"
        assert run("--root", root, "irqs", "--set", "3", "--out", str(out))[0] == 1
        assert json.loads(out.read_text(encoding="utf-8"))["why"] == (
            "no interrupt of the receiver card was found to move")
        assert run("--root", root, "irqs", "--out", str(out))[0] == 0

    def test_a_table_that_cannot_be_read_fails_a_move_and_is_noted_in_a_reading(self, tmp_path):
        root = machine(tmp_path, APART)
        os.remove(os.path.join(root, "proc/interrupts"))
        out = tmp_path / "s.json"
        assert run("--root", root, "irqs", "--set", "3", "--out", str(out))[0] == 1
        assert run("--root", root, "irqs", "--out", str(out))[0] == 0
        assert json.loads(out.read_text(encoding="utf-8"))["why"].startswith("cannot be read")

    def test_a_restore_leaves_an_interrupt_it_has_no_record_of(self, tmp_path):
        root = machine(tmp_path, APART)
        before, back = tmp_path / "b.json", tmp_path / "r.json"
        before.write_text(json.dumps({"irqs": [{"irq": 24, "smp_affinity_list": "1"},
                                               {"irq": 25, "smp_affinity_list": None}]}),
                          encoding="utf-8")
        assert run("--root", root, "irqs", "--restore", str(before), "--out", str(back))[0] == 0
        assert [i["smp_affinity_list"] for i in json.loads(back.read_text(
            encoding="utf-8"))["irqs"]] == ["1", "0-7"]

    @pytest.mark.parametrize("argv", [["--set", "x"], ["--restore", "no-such-file.json"]])
    def test_a_move_it_cannot_read_is_an_error(self, tmp_path, argv):
        code, said = run("--root", machine(tmp_path, APART), "irqs", *argv, "--out",
                         str(tmp_path / "s.json"))
        assert code == 1 and said.startswith("ERROR: ")


class TestTheCpusThatTakeTheInterrupts:

    def test_those_the_run_gives_them_or_else_those_found_taking_them(self, tmp_path):
        record = tmp_path / "before.json"
        record.write_text(json.dumps({"irqs": [{"effective_affinity_list": "2"},
                                               {"effective_affinity_list": "0"},
                                               {"effective_affinity_list": None}]}),
                          encoding="utf-8")
        assert run("irq-cpus", "--irqs", str(record)) == (0, "0,2 2")
        assert run("irq-cpus", "--irqs", str(record), "--given", "3") == (0, "3 1")
        assert run("irq-cpus", "--given", "3", "--avoid", "6,7") == (0, "3 1")

    def test_a_load_of_its_own_needs_a_cpu_off_the_consumers_core(self, tmp_path):
        code, said = run("irq-cpus", "--given", "6-7", "--avoid", "6,7")
        assert code == 1 and said == ("ERROR: the card's interrupts are taken on 6-7, which the "
                                      "consumer's core 6,7 keeps for the consumer")

    def test_none_found_taking_them_is_an_error(self, tmp_path):
        record = tmp_path / "before.json"
        record.write_text(json.dumps({"irqs": None}), encoding="utf-8")
        code, said = run("irq-cpus", "--irqs", str(record))
        assert code == 1 and said.startswith("ERROR: no CPU was found taking")


class TestTheReceiveQueues:

    DEVICES = {"eth0": {"rx-0": "0", "rx-1": "00000000,00000003"}, "enP1s1": {"rx-0": "f"}}

    def test_each_queue_is_read_turned_off_and_put_back(self, tmp_path):
        root = machine(tmp_path, APART, devices=self.DEVICES)
        os.makedirs(os.path.join(root, cp.QUEUES % "eth0", "tx-0"))
        before, off, back = (tmp_path / name for name in ("b.json", "s.json", "r.json"))
        devs = ["--dev", "eth0", "--dev", "enP1s1"]
        assert run("--root", root, "rps", *devs, "--out", str(before)) == (
            0, "OK the receiver's receive queues -> %s" % before)
        assert [(q["device"], q["queue"], q["rps_cpus"]) for q in json.loads(
            before.read_text(encoding="utf-8"))["queues"]] == [
            ("eth0", "rx-0", "0"), ("eth0", "rx-1", "00000000,00000003"), ("enP1s1", "rx-0", "f")]
        assert run("--root", root, "rps", *devs, "--set", "0", "--out", str(off))[0] == 0
        assert {q["rps_cpus"] for q in json.loads(off.read_text(encoding="utf-8"))["queues"]} == {
            "0"}
        assert run("--root", root, "rps", "--restore", str(before), "--out", str(back))[0] == 0
        restored = json.loads(back.read_text(encoding="utf-8"))
        assert {(q["device"], q["queue"]): q["rps_cpus"] for q in restored["queues"]} == {
            ("eth0", "rx-0"): "0", ("eth0", "rx-1"): "00000000,00000003", ("enP1s1", "rx-0"): "f"}
        assert restored["devices"] == ["enP1s1", "eth0"], "the devices the record names"

    def test_a_device_that_is_not_there_fails(self, tmp_path):
        root, out = machine(tmp_path, APART, devices=self.DEVICES), tmp_path / "s.json"
        assert run("--root", root, "rps", "--dev", "sblrecv0", "--out", str(out))[0] == 1
        missing = json.loads(out.read_text(encoding="utf-8"))["missing"]
        assert missing["sblrecv0"].startswith("its queues cannot be listed: ")

    def test_a_queue_that_refuses_or_reads_back_otherwise_fails(self, tmp_path, monkeypatch):
        root, out = machine(tmp_path, APART, devices=self.DEVICES), tmp_path / "s.json"
        target = os.path.join(root, cp.QUEUES % "enP1s1", "rx-0", "rps_cpus")
        os.remove(target)
        os.mkdir(target)
        assert run("--root", root, "rps", "--dev", "enP1s1", "--set", "0", "--out",
                   str(out))[0] == 1
        assert list(json.loads(out.read_text(encoding="utf-8"))["refused"]) == ["enP1s1/rx-0"]
        root = machine(tmp_path / "second", APART, devices=self.DEVICES)
        monkeypatch.setattr(cp, "write_value", lambda path, value: None)
        assert run("--root", root, "rps", "--dev", "eth0", "--set", "0", "--out", str(out))[0] == 1
        assert json.loads(out.read_text(encoding="utf-8"))["refused"] == {
            "eth0/rx-1": "read back as 00000000,00000003, not 0"}

    def test_a_restore_leaves_a_queue_it_has_no_mask_for(self, tmp_path):
        root = machine(tmp_path, APART, devices=self.DEVICES)
        before, back = tmp_path / "b.json", tmp_path / "r.json"
        before.write_text(json.dumps({"queues": [
            {"device": "eth0", "queue": "rx-0", "rps_cpus": None}]}), encoding="utf-8")
        assert run("--root", root, "rps", "--restore", str(before), "--out", str(back))[0] == 0

    @pytest.mark.parametrize("mask", ["x", ""])
    def test_a_mask_that_is_not_one_is_an_error(self, tmp_path, mask):
        code, said = run("--root", machine(tmp_path, APART, devices=self.DEVICES), "rps",
                         "--dev", "eth0", "--set", mask, "--out", str(tmp_path / "s.json"))
        assert code == 1 and said.startswith("ERROR: ")
