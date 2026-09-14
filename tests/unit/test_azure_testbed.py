"""Tests for scripts/azure_testbed.py.

Nothing here reaches Azure. Every command the program would run is checked as data, through a
fake runner that records what it was asked and answers from a script. That is the reason the
program exists: the trial account's thirty days must not be where its commands are first tried.
"""
import datetime
import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import azure_testbed as at  # noqa: E402

REPO = Path(__file__).parent.parent.parent
SOURCE = "203.0.113.7/32"


class FakeAz:
    """Answers az commands from (predicate, answer) rules and records every call.

    An answer is (code, stdout, stderr) or a function of the arguments returning one.
    """

    def __init__(self, rules=(), default=(0, "{}", "")):
        self.rules = list(rules)
        self.default = default
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        for match, answer in self.rules:
            if match(args):
                return answer(args) if callable(answer) else answer
        return self.default


def starts(*words):
    return lambda args: list(args[:len(words)]) == list(words)


@pytest.fixture
def spec():
    return at.load_spec()


def copy_of(spec):
    return json.loads(json.dumps(spec))


def write_spec(tmp_path, data):
    path = tmp_path / "testbed.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def run_main(argv, runner=None):
    out = io.StringIO()
    code = at.main(argv, runner=runner if runner is not None else FakeAz(), out=out)
    return code, out.getvalue()


class TestTheCommittedFile:

    def test_it_can_be_built(self, spec):
        assert at.spec_problems(spec) == []

    def test_matched_is_the_oracle_layout(self, spec):
        """sbl-drv had 4 OCPUs and sbl-b1 had 1; an x86 OCPU is two vCPUs, so 8 and 2."""
        roles = {h["role"]: h for _, h in at.profile_hosts(spec, "matched")}
        assert at.size_cpus(roles["driver"]["size"]) == 8
        assert at.size_cpus(roles["broker"]["size"]) == 2
        assert all(h["size"].endswith("as_v6") for h in roles.values()), (
            "Dasv6 is AMD EPYC Genoa, the generation of Oracle's E5")

    def test_arm_changes_the_machine_and_keeps_the_layout(self, spec):
        hosts = [h for _, h in at.profile_hosts(spec, "arm")]
        assert sorted(at.size_cpus(h["size"]) for h in hosts) == [2, 8]
        assert all(h["size"].endswith("ps_v6") and h["image"] == "arm64-jammy" for h in hosts)

    def test_it_points_at_the_setup_file_it_sends(self, spec):
        assert (REPO / spec["custom_data"]).is_file()


class TestSpecProblems:

    @staticmethod
    def broken(spec, mutate):
        data = copy_of(spec)
        mutate(data)
        return at.spec_problems(data)

    def test_a_subnet_outside_its_network(self, spec):
        found = self.broken(spec, lambda d: d["vnet"].update(cidr="10.9.0.0/16"))
        assert any("is not inside the network" in p for p in found)

    def test_an_unknown_role_image_and_size(self, spec):
        found = self.broken(spec, lambda d: d["hosts"]["sbl-az-b1"].update(
            role="spare", image="nope", size="Tiny"))
        assert any("role must be one of" in p for p in found)
        assert any("image 'nope'" in p for p in found)
        assert any("cannot read a CPU count" in p for p in found)
        assert any("no planning price" in p for p in found)

    @pytest.mark.parametrize("address,why", [
        ("10.1.1.1", "reserves"), ("10.1.1.3", "reserves"), ("10.1.1.255", "reserves"),
        ("10.1.2.5", "is outside"), ("not-an-ip", "is not an address")])
    def test_an_address_azure_would_refuse(self, spec, address, why):
        found = self.broken(spec, lambda d: d["hosts"]["sbl-az-b1"].update(private_ip=address))
        assert any("private_ip" in p and why in p for p in found), found

    def test_a_driver_without_its_receiver_or_a_way_in(self, spec):
        def mutate(d):
            del d["hosts"]["sbl-az-drv"]["receiver_ip"]
            d["hosts"]["sbl-az-drv"]["public_ip"] = False
        found = self.broken(spec, mutate)
        assert any("receiver_ip" in p and "not an address" in p for p in found)
        assert any("needs a public address" in p for p in found)

    def test_an_address_given_twice(self, spec):
        found = self.broken(spec, lambda d: d["hosts"]["sbl-az-b1"].update(
            private_ip="10.1.1.11"))
        assert any("is already sbl-az-drv's receiver_ip" in p for p in found)

    def test_profiles_that_cannot_run(self, spec):
        def mutate(d):
            d["profiles"]["ghost"] = {"hosts": ["sbl-az-nope"], "about": "x"}
            d["profiles"]["two"] = {"hosts": ["sbl-az-drv", "sbl-az-arm-drv"], "about": "x"}
        found = self.broken(spec, mutate)
        assert any("profile ghost names unknown machines" in p for p in found)
        assert any("profile two needs exactly one driver" in p for p in found)
        assert any("profile two needs at least one broker" in p for p in found)

    def test_loading_names_every_problem_at_once(self, spec, tmp_path):
        data = copy_of(spec)
        data["hosts"]["sbl-az-b1"].update(private_ip="10.1.1.2", size="Tiny")
        with pytest.raises(at.SpecError) as exc:
            at.load_spec(write_spec(tmp_path, data))
        assert "reserves" in str(exc.value) and "CPU count" in str(exc.value)

    def test_an_unknown_profile(self, spec):
        with pytest.raises(at.SpecError, match="no profile 'big'"):
            at.profile_hosts(spec, "big")


class TestSshSource:

    @pytest.mark.parametrize("source,fragment", [
        ("", "is required"), ("my laptop", "not an address range"),
        ("0.0.0.0/0", "would open SSH"), ("203.0.113.0/16", "would open SSH")])
    def test_a_range_that_opens_too_much_is_refused(self, source, fragment):
        assert fragment in at.ssh_source_problem(source)

    @pytest.mark.parametrize("source", [SOURCE, "203.0.113.7", "203.0.113.0/24"])
    def test_one_address_or_a_small_range_is_accepted(self, source):
        assert at.ssh_source_problem(source) is None


class TestPlan:

    def test_it_prints_every_command_and_runs_none(self):
        fake = FakeAz()
        code, text = run_main(["plan", "--ssh-source", SOURCE], fake)
        assert code == 0 and fake.calls == []
        commands = [line for line in text.splitlines() if line.startswith("az ")]
        assert commands[0].startswith("az group create --name sbl-az")
        assert any("--source-address-prefixes %s" % SOURCE in c for c in commands)
        assert any(c.startswith("az network nic ip-config create") and "10.1.1.11" in c
                   for c in commands)
        creates = [c for c in commands if c.startswith("az vm create")]
        assert len(creates) == 2
        assert "Standard_D8as_v6" in creates[0] and "--nics sbl-az-drv-nic" in creates[0]
        assert "--custom-data cloud/azure/cloud-init.yaml" in creates[0]

    def test_only_the_driver_is_reachable_from_outside(self):
        _, text = run_main(["plan", "--ssh-source", SOURCE])
        lines = text.splitlines()
        publics = [line for line in lines if line.startswith("az network public-ip create")]
        assert len(publics) == 1 and "sbl-az-drv-ip" in publics[0]
        broker_nic = [line for line in lines if line.startswith("az network nic create")
                      and "sbl-az-b1-nic" in line]
        assert broker_nic and "--public-ip-address" not in broker_nic[0]

    def test_a_missing_ssh_source_is_shown_as_a_placeholder(self):
        _, text = run_main(["plan"])
        assert "YOUR.ADDRESS/32" in text

    def test_the_summary_counts_and_prices_the_profile(self):
        _, text = run_main(["plan", "--profile", "arm"])
        assert "10 CPUs in all" in text
        assert "about $0.37 an hour" in text


class TestUp:

    @pytest.fixture
    def keyed(self, spec, tmp_path):
        key = tmp_path / "azure_sbl.pub"
        key.write_text("ssh-ed25519 AAAA test\n", encoding="utf-8")
        data = copy_of(spec)
        data["ssh_public_key"] = str(key)
        return write_spec(tmp_path, data)

    def up(self, spec_path, *extra):
        return ["--spec", spec_path, "up", "--ssh-source", SOURCE] + list(extra)

    def test_without_yes_nothing_is_created(self, keyed):
        fake = FakeAz()
        code, text = run_main(self.up(keyed), fake)
        assert code == 1 and fake.calls == []
        assert "Nothing was created" in text and "az vm create" in text

    @pytest.mark.parametrize("name,stem", [("absent.pub", "absent -N"),
                                           ("absent_key", "absent_key -N")])
    def test_a_missing_key_comes_with_the_command_that_makes_it(self, spec, tmp_path, name,
                                                                 stem):
        data = copy_of(spec)
        data["ssh_public_key"] = str(tmp_path / name)
        code, text = run_main(self.up(write_spec(tmp_path, data), "--yes"))
        assert code == 2 and "ssh-keygen -t ed25519 -f" in text and stem in text

    def test_an_open_ssh_source_is_refused_before_anything_runs(self, keyed):
        fake = FakeAz()
        code, text = run_main(["--spec", keyed, "up", "--ssh-source", "0.0.0.0/0", "--yes"],
                              fake)
        assert code == 2 and fake.calls == [] and "would open SSH" in text

    def test_with_yes_it_probes_then_creates_and_sends_clean_setup(self, keyed):
        sent = {}

        def vm_create(args):
            path = args[args.index("--custom-data") + 1]
            sent[args[args.index("--name") + 1]] = Path(path).read_bytes()
            sent["path"] = path
            return 0, "{}", ""

        missing = (3, "", "not found")
        fake = FakeAz(rules=[(starts("network", "public-ip", "show"), missing),
                             (starts("network", "nic", "show"), missing),
                             (starts("network", "nic", "ip-config", "show"), missing),
                             (starts("vm", "show"), missing),
                             (starts("vm", "create"), vm_create)])
        code, _ = run_main(self.up(keyed, "--yes"), fake)
        assert code == 0
        assert fake.calls[0][:2] == ["group", "create"]
        show = fake.calls.index(["vm", "show", "--resource-group", "sbl-az", "--name",
                                 "sbl-az-drv"])
        create = next(i for i, c in enumerate(fake.calls) if c[:2] == ["vm", "create"])
        assert show == create - 1
        assert sent["sbl-az-drv"].startswith(b"#cloud-config\n")
        assert b"\r\n" not in sent["sbl-az-drv"]
        assert not os.path.exists(sent["path"]), "the temporary setup file is removed"

    def test_what_already_exists_is_skipped(self, keyed):
        fake = FakeAz()
        code, text = run_main(self.up(keyed, "--yes"), fake)
        assert code == 0 and "already there" in text
        assert not any(c[:2] == ["vm", "create"] for c in fake.calls)

    def test_the_first_failure_stops_the_build(self, keyed):
        fake = FakeAz(rules=[(starts("network", "vnet", "create"), (1, "", "quota exceeded"))])
        code, text = run_main(self.up(keyed, "--yes"), fake)
        assert code == 1
        assert "FAILED: az network vnet create" in text and "quota exceeded" in text
        assert not any(c[:2] == ["network", "nsg"] for c in fake.calls)


class TestCustomData:

    def test_the_committed_file_is_ready_to_send(self):
        assert "\r" not in at.custom_data_text(str(REPO / "cloud" / "azure" / "cloud-init.yaml"))

    def test_crlf_is_stripped(self, tmp_path):
        path = tmp_path / "c.yaml"
        path.write_bytes(b"#cloud-config\r\npackages: []\r\n")
        assert at.custom_data_text(str(path)) == "#cloud-config\npackages: []\n"

    def test_a_file_that_is_not_cloud_config_is_refused(self, tmp_path):
        path = tmp_path / "c.yaml"
        path.write_text("packages: []\n", encoding="utf-8")
        with pytest.raises(at.SpecError, match="does not start with #cloud-config"):
            at.custom_data_text(str(path))


def sku(size, family, cpus=None, restrictions=()):
    caps = [{"name": "MemoryGB", "value": "32"}]
    if cpus is not None:
        caps.append({"name": "vCPUs", "value": str(cpus)})
    return {"name": size, "family": family, "restrictions": list(restrictions),
            "capabilities": caps}


def usage(**limits):
    return json.dumps([{"name": {"value": k}, "limit": v[0], "currentValue": v[1]}
                       for k, v in limits.items()])


DASV6 = {"Standard_D8as_v6": [sku("Standard_D8as_v6", "standardDASv6Family", 8)],
         "Standard_D2as_v6": [sku("Standard_D2as_v6", "standardDASv6Family", 2)]}


def preflight_az(skus=None, usage_text=None, account_code=0):
    skus = DASV6 if skus is None else skus

    def list_skus(args):
        return 0, json.dumps(skus.get(args[args.index("--size") + 1], [])), ""

    return FakeAz(rules=[
        (starts("account", "show"),
         (account_code, json.dumps({"name": "Azure subscription 1", "state": "Enabled"}),
          "Please run 'az login' to setup account.")),
        (starts("vm", "list-skus"), list_skus),
        (starts("vm", "list-usage"),
         (0, usage_text or usage(cores=(20, 0), standardDASv6Family=(20, 0)), "")),
    ])


class TestPreflight:

    def test_a_profile_that_fits(self):
        fake = preflight_az()
        code, text = run_main(["preflight"], fake)
        assert code == 0
        assert "subscription: Azure subscription 1 (Enabled)" in text
        assert "all CPUs in swedencentral: need 10, limit 20, in use 0 -> fits" in text
        assert "standardDASv6Family: need 10" in text
        assert all(c[0] in ("account", "vm") for c in fake.calls), "it only reads"

    def test_a_trial_sized_limit_is_reported_with_the_way_out(self):
        code, text = run_main(["preflight"], preflight_az(
            usage_text=usage(cores=(4, 0), standardDASv6Family=(4, 0))))
        assert code == 1
        assert "DOES NOT FIT" in text and "pay-as-you-go" in text

    def test_not_logged_in(self):
        code, text = run_main(["preflight"], preflight_az(account_code=1))
        assert code == 1 and "az login" in text

    def test_a_size_not_offered_in_the_location(self):
        code, text = run_main(["preflight"], preflight_az(
            skus={"Standard_D8as_v6": DASV6["Standard_D8as_v6"]}))
        assert code == 1 and "Standard_D2as_v6 is not offered" in text
        assert "pay-as-you-go" not in text, "a missing size is not a limit to raise"

    def test_a_size_restricted_for_the_subscription(self):
        restricted = dict(DASV6, Standard_D2as_v6=[sku(
            "Standard_D2as_v6", "standardDASv6Family", 2,
            [{"reasonCode": "NotAvailableForSubscription"}])])
        code, text = run_main(["preflight"], preflight_az(skus=restricted))
        assert code == 1 and "NotAvailableForSubscription" in text

    def test_a_family_with_no_reported_limit_cannot_be_confirmed(self):
        code, text = run_main(["preflight"], preflight_az(usage_text=usage(cores=(20, 0))))
        assert code == 1 and "no limit reported" in text

    def test_no_limits_at_all_means_virtual_machines_are_not_switched_on(self):
        """What the first real trial subscription returned before Microsoft.Compute was
        registered: an empty list, not an error."""
        code, text = run_main(["preflight"], preflight_az(usage_text="[]"))
        assert code == 1 and "not switched on yet" in text
        assert "az provider register --namespace Microsoft.Compute" in text

    def test_a_size_list_without_cpu_counts_falls_back_to_the_name(self):
        bare = {size: [sku(size, "standardDASv6Family")] for size in DASV6}
        code, text = run_main(["preflight"], preflight_az(skus=bare))
        assert code == 0 and "need 10" in text

    def test_the_size_list_failing(self):
        fake = FakeAz(rules=[(starts("vm", "list-skus"), (1, "", "throttled"))])
        code, text = run_main(["preflight"], fake)
        assert code == 1 and "could not list the sizes" in text

    def test_the_usage_list_failing(self):
        fake = preflight_az()
        fake.rules.insert(0, (starts("vm", "list-usage"), (1, "", "throttled")))
        code, text = run_main(["preflight"], fake)
        assert code == 1 and "could not read the CPU limits" in text


def listing(drv_private=("10.1.1.10", "10.1.1.11"), drv_public=("20.0.0.9",),
            names=("sbl-az-drv", "sbl-az-b1"), extra=()):
    table = {"sbl-az-drv": (drv_private, drv_public), "sbl-az-b1": (("10.1.1.21",), ())}
    table.update(dict(extra))
    return json.dumps([{"virtualMachine": {"name": name, "network": {
        "privateIpAddresses": list(table[name][0]),
        "publicIpAddresses": [{"ipAddress": p} for p in table[name][1]]}}}
        for name in names])


class TestHosts:

    def hosts_az(self, text, code=0):
        return FakeAz(rules=[(starts("vm", "list-ip-addresses"), (code, text, "denied"))])

    def test_it_writes_what_the_campaigns_and_the_session_read(self):
        code, text = run_main(["hosts"], self.hosts_az(listing()))
        assert code == 0
        for line in ("BROKER_PRIV=10.1.1.21", "SSH_KEY=$HOME/.ssh/azure_sbl",
                     "AZ_PROFILE=matched", "DRIVER_PUBLIC=20.0.0.9", "DRIVER_PRIV=10.1.1.10",
                     "RECEIVER_IP=10.1.1.11", "SUBNET_PREFIX=24", "SUBNET_GATEWAY=10.1.1.1"):
            assert line in text.splitlines()

    def test_the_file_is_written_with_lf(self, tmp_path):
        dest = tmp_path / "hosts.env"
        code, text = run_main(["hosts", "--write", str(dest)], self.hosts_az(listing()))
        assert code == 0 and "wrote" in text
        assert b"\r" not in dest.read_bytes() and b"BROKER_PRIV=10.1.1.21\n" in dest.read_bytes()

    @pytest.mark.parametrize("text,fragment", [
        (listing(names=("sbl-az-drv",)), "sbl-az-b1 does not exist"),
        (listing(drv_private=("10.1.1.10",)), "does not hold 10.1.1.11"),
        (listing(drv_private=()), "it holds nothing"),
        (listing(drv_public=()), "has no public address yet")])
    def test_an_address_that_is_not_where_the_file_says(self, text, fragment):
        code, out = run_main(["hosts"], self.hosts_az(text))
        assert code == 2 and fragment in out

    def test_the_listing_failing(self):
        code, out = run_main(["hosts"], self.hosts_az("", code=1))
        assert code == 2 and "could not list" in out

    def test_extra_brokers_get_the_names_cluster_campaigns_read(self, spec, tmp_path):
        data = copy_of(spec)
        for n, ip in (("b2", "10.1.1.22"), ("b3", "10.1.1.23")):
            data["hosts"]["sbl-az-%s" % n] = dict(data["hosts"]["sbl-az-b1"], private_ip=ip)
        data["profiles"]["cluster"] = {"hosts": ["sbl-az-drv", "sbl-az-b1", "sbl-az-b2",
                                                 "sbl-az-b3"], "about": "three brokers"}
        spec3 = at.load_spec(write_spec(tmp_path, data))
        text = listing(names=("sbl-az-drv", "sbl-az-b1", "sbl-az-b2", "sbl-az-b3"),
                       extra=(("sbl-az-b2", (("10.1.1.22",), ())),
                              ("sbl-az-b3", (("10.1.1.23",), ()))))
        env = at.hosts_env(spec3, "cluster", self.hosts_az(text),
                           now=datetime.datetime(2026, 9, 20, 9, 30))
        assert "BROKER2_PRIV=10.1.1.22\nBROKER3_PRIV=10.1.1.23\n" in env
        assert "at 2026-09-20T09:30:00Z" in env


class TestPower:

    def test_stop_without_yes_only_shows_the_deallocation(self):
        fake = FakeAz()
        code, text = run_main(["stop"], fake)
        assert code == 1 and fake.calls == []
        assert "az vm deallocate --resource-group sbl-az --name sbl-az-drv --no-wait" in text

    def test_start_with_yes_starts_every_machine(self):
        fake = FakeAz()
        code, _ = run_main(["start", "--yes"], fake)
        assert code == 0
        assert [c[:2] + [c[-2]] for c in fake.calls] == [["vm", "start", "sbl-az-drv"],
                                                         ["vm", "start", "sbl-az-b1"]]


class TestStatus:

    def test_machines_are_listed(self):
        fake = FakeAz(rules=[(starts("vm", "list"), (0, json.dumps([
            {"name": "sbl-az-drv", "hardwareProfile": {"vmSize": "Standard_D8as_v6"},
             "powerState": "VM deallocated", "publicIps": "20.0.0.9"}]), ""))])
        code, text = run_main(["status"], fake)
        assert code == 0 and "VM deallocated" in text and "20.0.0.9" in text

    def test_an_empty_group(self):
        code, text = run_main(["status"], FakeAz(default=(0, "[]", "")))
        assert code == 0 and "no machines in sbl-az" in text

    def test_the_listing_failing(self):
        code, text = run_main(["status"], FakeAz(default=(1, "", "gone")))
        assert code == 1 and "could not list the machines" in text


class TestDown:

    @pytest.mark.parametrize("argv", [["down"], ["down", "--confirm", "sbl"]])
    def test_nothing_is_deleted_without_the_group_name_typed_back(self, argv):
        fake = FakeAz()
        code, text = run_main(argv, fake)
        assert code == 1 and fake.calls == []
        assert "cannot be undone" in text and "az group delete --name sbl-az" in text

    def test_the_name_typed_back_starts_the_deletion(self):
        fake = FakeAz()
        code, text = run_main(["down", "--confirm", "sbl-az"], fake)
        assert code == 0 and fake.calls == [["group", "delete", "--name", "sbl-az", "--yes",
                                             "--no-wait"]]
        assert "has started" in text

    def test_a_failed_deletion_is_reported(self):
        code, text = run_main(["down", "--confirm", "sbl-az"], FakeAz(default=(1, "", "locked")))
        assert code == 1 and "FAILED: locked" in text


class TestRunner:

    def test_no_cli_is_a_sentence_not_a_traceback(self, monkeypatch):
        monkeypatch.delenv("AZ", raising=False)
        with pytest.raises(at.AzNotFound, match="not installed"):
            at.make_runner(which=lambda name: None)(["version"])

    def test_it_runs_what_which_found_and_returns_three_parts(self, monkeypatch):
        monkeypatch.delenv("AZ", raising=False)
        calls = []

        class Done:
            returncode, stdout, stderr = 0, "out", "err"

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return Done()

        runner = at.make_runner(run=run, which=lambda name: "C:/az/az.cmd")
        assert runner(("version",)) == (0, "out", "err")
        assert calls == [(["C:/az/az.cmd", "version"], {"capture_output": True, "text": True})]

    def test_the_az_variable_wins_over_the_path(self, monkeypatch):
        monkeypatch.setenv("AZ", "/opt/az/bin/az")
        seen = []

        class Done:
            returncode, stdout, stderr = 0, "", ""

        at.make_runner(run=lambda argv, **kw: seen.append(argv) or Done(),
                       which=lambda name: "/usr/bin/az")(["version"])
        assert seen == [["/opt/az/bin/az", "version"]]

    def test_a_missing_cli_ends_the_command_with_an_error_line(self):
        def missing(args):
            raise at.AzNotFound("the Azure CLI (az) is not installed")
        code, text = run_main(["preflight"], missing)
        assert code == 2 and "ERROR: the Azure CLI" in text


class TestMain:

    def test_it_builds_its_own_runner_when_given_none(self):
        out = io.StringIO()
        assert at.main(["plan"], out=out) == 0

    def test_an_unknown_profile_is_an_error_line(self):
        code, text = run_main(["plan", "--profile", "huge"])
        assert code == 2 and "no profile 'huge'" in text

    def test_a_missing_testbed_file_is_an_error_line(self, tmp_path):
        code, text = run_main(["--spec", str(tmp_path / "none.json"), "status"])
        assert code == 2 and "ERROR" in text
