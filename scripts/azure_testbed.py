#!/usr/bin/env python3
"""
azure_testbed.py -- plan, check, create, pause and remove the Azure testbed.

cloud/provision.sh did this job for Oracle as a shell script. This one is a program, for three
reasons that come from the trial account rather than from Azure itself:

  * The credit lasts thirty days from sign-up, and a trial's CPU limit cannot be raised. So the
    first time a command meets the account must not be the first time it runs. Every command is
    built as data first: `plan` prints all of them with no account at all, and the tests check
    them.
  * Nothing that costs money, stops a machine or deletes anything runs without `--yes`, and
    `down` also wants the resource group's name typed back.
  * No credential passes through it. `az login` is done by a person, in a browser.

The layout is cloud/azure/testbed.json: machines, sizes, fixed private addresses, and profiles
that group them. "matched" is the Oracle layout on the same AMD generation; "arm" is the same
layout on a materially different machine. Addresses are fixed so that a hosts.env written once
stays true across every stop and start.

Each driver's network card gets a second address, the receiver's. Azure routes it to the card,
and scripts/receiver_delay.py puts the receiving program behind it.

As on Oracle, no broker port is reachable from the internet. An unauthenticated Redis on a public
address is taken over within minutes, so SSH from one address is the only way in.

Usage:
    python scripts/azure_testbed.py plan --profile matched --ssh-source 203.0.113.7/32
    python scripts/azure_testbed.py preflight --profile matched
    python scripts/azure_testbed.py up --profile matched --ssh-source 203.0.113.7/32 --yes
    python scripts/azure_testbed.py hosts --profile matched --write cloud/hosts.env
    python scripts/azure_testbed.py stop --profile matched --yes
    python scripts/azure_testbed.py start --profile matched --yes
    python scripts/azure_testbed.py status
    python scripts/azure_testbed.py down --confirm sbl-az

A profile can name its own region, resource group, network, firewall and prices. "matched-b" names
its own group and network: the matched layout again, so that a second x86 pair runs beside the
first without sharing a machine. It sat in another region until Sweden Central's CPU limit was
raised, which is what the region and price overrides are for. Every command takes --profile and
acts in that profile's group:
    python scripts/azure_testbed.py up --profile matched-b --ssh-source 203.0.113.7/32 --yes
    python scripts/azure_testbed.py down --profile matched-b --confirm sbl-azb
"""
import argparse
import datetime
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(REPO, "cloud", "azure", "testbed.json")
ROLES = ("driver", "broker")
PROFILE_COMMANDS = ("plan", "preflight", "up", "hosts", "stop", "start")


class SpecError(ValueError):
    """The testbed file describes something that cannot be built."""


class AzNotFound(RuntimeError):
    """The Azure CLI is not installed, or is not on PATH."""


# --- the testbed file ------------------------------------------------------------------------

def size_cpus(size):
    """vCPUs from an Azure size name: Standard_D8as_v6 has 8.

    A planning figure only. `preflight` reads the real count from the subscription's size list.
    """
    m = re.match(r"Standard_[A-Za-z]+?(\d+)", size or "")
    if not m:
        raise SpecError("cannot read a CPU count from size %r" % (size,))
    return int(m.group(1))


def address_problem(subnet, value):
    """Why `value` cannot be a fixed address in `subnet`, or None if it can.

    Azure keeps the first four addresses of every subnet and its last one. A file naming one of
    them fails at creation time, after the network already exists.
    """
    try:
        addr = ipaddress.ip_address(value)
    except (TypeError, ValueError):
        return "%r is not an address" % (value,)
    if addr not in subnet:
        return "%s is outside %s" % (addr, subnet)
    if int(addr) - int(subnet.network_address) < 4 or addr == subnet.broadcast_address:
        return "%s is one of the five addresses Azure reserves in every subnet" % addr
    return None


#: How a machine's disk is attached. The x86 v6 sizes boot only from NVMe; Azure lists only
#: SCSI for the Arm v6 sizes, so a machine may name it instead.
DISK_CONTROLLERS = ("NVMe", "SCSI")


def host_problems(spec, subnet, name, host, seen):
    """Problems with one machine. `seen` maps addresses already taken to their owners."""
    out = []
    if host.get("disk_controller", "NVMe") not in DISK_CONTROLLERS:
        out.append("%s: disk_controller must be one of %s"
                   % (name, ", ".join(DISK_CONTROLLERS)))
    if host.get("role") not in ROLES:
        out.append("%s: role must be one of %s" % (name, ", ".join(ROLES)))
    if host.get("image") not in spec["images"]:
        out.append("%s: image %r is not listed under images" % (name, host.get("image")))
    try:
        size_cpus(host.get("size"))
    except SpecError as exc:
        out.append("%s: %s" % (name, exc))
    if host.get("size") not in spec["hourly_usd"]:
        out.append("%s: size %r has no planning price" % (name, host.get("size")))
    addresses = [("private_ip", host.get("private_ip"))]
    if host.get("role") == "driver":
        addresses.append(("receiver_ip", host.get("receiver_ip")))
        if not host.get("public_ip"):
            out.append("%s: a driver needs a public address; it is the way in" % name)
    for field, value in addresses:
        problem = address_problem(subnet, value)
        if problem:
            out.append("%s: %s: %s" % (name, field, problem))
        elif value in seen:
            out.append("%s: %s %s is already %s" % (name, field, value, seen[value]))
        else:
            seen[value] = "%s's %s" % (name, field)
    return out


def host_vnet(spec, name):
    """The network a machine's addresses must fit: that of the first profile naming it, or the
    file's own when that profile names none."""
    for profile in spec["profiles"].values():
        if name in profile.get("hosts", []):
            return profile.get("vnet", spec["vnet"])
    return spec["vnet"]


def spec_problems(spec):
    """Every reason the file cannot be built, so a broken file is fixed in one pass."""
    out = []
    seen = {}
    for vnet in [spec["vnet"]] + [p["vnet"] for p in spec["profiles"].values() if "vnet" in p]:
        if vnet["cidr"] in seen:
            continue
        seen[vnet["cidr"]] = {}
        subnet = ipaddress.ip_network(vnet["subnet_cidr"])
        network = ipaddress.ip_network(vnet["cidr"])
        if not subnet.subnet_of(network):
            out.append("subnet %s is not inside the network %s" % (subnet, network))
    for name, host in spec["hosts"].items():
        vnet = host_vnet(spec, name)
        out += host_problems(spec, ipaddress.ip_network(vnet["subnet_cidr"]), name, host,
                             seen[vnet["cidr"]])
    for pname, profile in spec["profiles"].items():
        unknown = [h for h in profile["hosts"] if h not in spec["hosts"]]
        if unknown:
            out.append("profile %s names unknown machines: %s" % (pname, ", ".join(unknown)))
            continue
        roles = [spec["hosts"][h].get("role") for h in profile["hosts"]]
        if roles.count("driver") != 1:
            out.append("profile %s needs exactly one driver" % pname)
        if not roles.count("broker"):
            out.append("profile %s needs at least one broker" % pname)
    return out


def load_spec(path=SPEC):
    """The testbed file, refused whole if anything in it cannot be built."""
    with open(path, encoding="utf-8") as fh:
        spec = json.load(fh)
    problems = spec_problems(spec)
    if problems:
        raise SpecError("%s cannot be built:\n  %s" % (path, "\n  ".join(problems)))
    return spec


def profile_hosts(spec, profile):
    """[(name, machine)] for a profile, in the order the profile lists them."""
    if profile not in spec["profiles"]:
        raise SpecError("no profile %r; the file has %s"
                        % (profile, ", ".join(sorted(spec["profiles"]))))
    return [(name, spec["hosts"][name]) for name in spec["profiles"][profile]["hosts"]]


#: What a profile may name for itself instead of taking the file's. A pair in another region needs
#: its own resource group and network, because an Azure network belongs to one region.
PROFILE_OVERRIDES = ("location", "resource_group", "vnet", "nsg")


def profile_spec(spec, profile):
    """The testbed file as one profile sees it: its own region, group, network, firewall and
    prices where it names them, and the file's everywhere else."""
    profile_hosts(spec, profile)
    own = spec["profiles"][profile]
    resolved = dict(spec)
    for key in PROFILE_OVERRIDES:
        if key in own:
            resolved[key] = own[key]
    if "hourly_usd" in own:
        resolved["hourly_usd"] = dict(spec["hourly_usd"], **own["hourly_usd"])
    return resolved


def gateway(spec):
    """The subnet's default gateway. Azure always puts it at the first host address."""
    return str(ipaddress.ip_network(spec["vnet"]["subnet_cidr"]).network_address + 1)


def ssh_source_problem(source):
    """Why `source` may not be the one range allowed to reach SSH, or None if it may."""
    if not source:
        return ("--ssh-source is required: your own public address as a /32, "
                "for example 203.0.113.7/32")
    try:
        net = ipaddress.ip_network(source, strict=False)
    except ValueError:
        return "--ssh-source %r is not an address range" % source
    if net.num_addresses > 256:
        return ("--ssh-source %s would open SSH to %d addresses; give your own address as a /32"
                % (net, net.num_addresses))
    return None


def custom_data_text(path):
    r"""The cloud-init file as a machine must receive it: LF line endings, header intact.

    A Windows checkout can hold CRLF copies of text files. cloud-init does not recognise a first
    line of `#cloud-config\r`, so the machine would boot with none of its setup and nothing would
    say why. .gitattributes pins YAML to LF; this does not rely on it.
    """
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read().replace("\r\n", "\n")
    if not text.startswith("#cloud-config\n"):
        raise SpecError("%s does not start with #cloud-config" % path)
    return text


# --- the commands ----------------------------------------------------------------------------

def step(args, about, probe=None):
    """One az command, what it is for, and an optional command that succeeds if it is done."""
    return {"args": list(args), "about": about, "probe": list(probe) if probe else None}


def tag_args(spec, extra=None):
    tags = dict(spec["tags"])
    tags.update(extra or {})
    return ["%s=%s" % kv for kv in sorted(tags.items())]


def network_steps(spec, ssh_source):
    rg, vnet, nsg = spec["resource_group"], spec["vnet"], spec["nsg"]
    return [
        step(["group", "create", "--name", rg, "--location", spec["location"],
              "--tags"] + tag_args(spec),
             "resource group %s: everything lives in it, so one delete removes everything" % rg),
        step(["network", "vnet", "create", "--resource-group", rg, "--name", vnet["name"],
              "--address-prefixes", vnet["cidr"], "--subnet-name", vnet["subnet"],
              "--subnet-prefixes", vnet["subnet_cidr"]],
             "private network %s, subnet %s" % (vnet["cidr"], vnet["subnet_cidr"])),
        step(["network", "nsg", "create", "--resource-group", rg, "--name", nsg],
             "firewall %s: machines on the network reach each other, and nothing outside "
             "reaches them" % nsg),
        step(["network", "nsg", "rule", "create", "--resource-group", rg, "--nsg-name", nsg,
              "--name", "ssh-from-operator", "--priority", "100", "--direction", "Inbound",
              "--access", "Allow", "--protocol", "Tcp", "--source-address-prefixes",
              ssh_source, "--destination-port-ranges", "22"],
             "SSH from %s only; no broker port is ever opened to the internet" % ssh_source),
        step(["network", "vnet", "subnet", "update", "--resource-group", rg,
              "--vnet-name", vnet["name"], "--name", vnet["subnet"],
              "--network-security-group", nsg],
             "the firewall covers every machine on the subnet"),
    ]


def host_steps(spec, name, host, custom_data):
    rg, vnet = spec["resource_group"], spec["vnet"]
    nic = "%s-nic" % name
    steps = []
    nic_args = ["network", "nic", "create", "--resource-group", rg, "--name", nic,
                "--vnet-name", vnet["name"], "--subnet", vnet["subnet"],
                "--private-ip-address", host["private_ip"], "--accelerated-networking", "true"]
    if host.get("public_ip"):
        pip = "%s-ip" % name
        steps.append(step(
            ["network", "public-ip", "create", "--resource-group", rg, "--name", pip,
             "--sku", "Standard", "--allocation-method", "Static"],
            "%s: a fixed public address, so hosts.env stays true across stop and start" % name,
            probe=["network", "public-ip", "show", "--resource-group", rg, "--name", pip]))
        nic_args += ["--public-ip-address", pip]
    steps.append(step(nic_args, "%s: network card at %s" % (name, host["private_ip"]),
                      probe=["network", "nic", "show", "--resource-group", rg, "--name", nic]))
    if host["role"] == "driver":
        steps.append(step(
            ["network", "nic", "ip-config", "create", "--resource-group", rg,
             "--nic-name", nic, "--name", "receiver",
             "--private-ip-address", host["receiver_ip"]],
            "%s: the receiver's own address %s, so a delay can reach it alone"
            % (name, host["receiver_ip"]),
            probe=["network", "nic", "ip-config", "show", "--resource-group", rg,
                   "--nic-name", nic, "--name", "receiver"]))
    steps.append(step(
        ["vm", "create", "--resource-group", rg, "--name", name, "--size", host["size"],
         "--image", spec["images"][host["image"]], "--nics", nic,
         "--admin-username", spec["admin_user"], "--authentication-type", "ssh",
         "--ssh-key-values", os.path.expanduser(spec["ssh_public_key"]),
         "--custom-data", custom_data, "--os-disk-size-gb", str(spec["os_disk_gb"]),
         "--storage-sku", spec["storage_sku"], "--os-disk-delete-option", "Delete",
         "--disk-controller-type", host.get("disk_controller", "NVMe"), "--tags"] + tag_args(spec, {"role": host["role"]}),
        "%s: %s, %d CPUs, %s" % (name, host["size"], size_cpus(host["size"]), host["role"]),
        probe=["vm", "show", "--resource-group", rg, "--name", name]))
    return steps


def up_steps(spec, profile, ssh_source, custom_data):
    steps = network_steps(spec, ssh_source)
    for name, host in profile_hosts(spec, profile):
        steps += host_steps(spec, name, host, custom_data)
    return steps


def power_steps(spec, profile, action):
    """Deallocate every machine of a profile (the CPUs stop billing) or start them again."""
    verb = {"stop": "deallocate", "start": "start"}[action]
    return [step(["vm", verb, "--resource-group", spec["resource_group"], "--name", name,
                  "--no-wait"], "%s %s" % (verb, name))
            for name, _ in profile_hosts(spec, profile)]


def show(args):
    return "az " + " ".join(shlex.quote(a) for a in args)


def print_plan(steps, out):
    for i, s in enumerate(steps, 1):
        print("# %d. %s" % (i, s["about"]), file=out)
        print(show(s["args"]), file=out)


def plan_summary(spec, profile):
    hosts = profile_hosts(spec, profile)
    lines = ["profile %s: %s" % (profile, spec["profiles"][profile]["about"])]
    for name, host in hosts:
        lines.append("  %-16s %-18s %2d CPUs  %-6s  $%.3f/h"
                     % (name, host["size"], size_cpus(host["size"]), host["role"],
                        spec["hourly_usd"][host["size"]]))
    per_hour = sum(spec["hourly_usd"][h["size"]] for _, h in hosts)
    lines.append("  %d CPUs in all, about $%.2f an hour while running ($%.2f a day if left on);"
                 " a deallocated machine costs only its disk"
                 % (sum(size_cpus(h["size"]) for _, h in hosts), per_hour, 24 * per_hour))
    lines.append("  prices: %s" % spec["hourly_usd_source"])
    return lines


# --- running ---------------------------------------------------------------------------------

def make_runner(az=None, run=subprocess.run, which=shutil.which):
    """A function that runs one az command and returns (exit code, stdout, stderr).

    The CLI is looked up when a command runs, not when the program starts, so `plan` works on a
    computer without it. On Windows the CLI is az.cmd, which a bare "az" in an argument list does
    not find; the full path from `which` does.
    """
    def runner(args):
        exe = az or os.environ.get("AZ") or which("az")
        if not exe:
            raise AzNotFound("the Azure CLI (az) is not installed or not on PATH; "
                             "cloud/azure/README.md says how to get it")
        done = run([exe] + list(args), capture_output=True, text=True)
        return done.returncode, done.stdout, done.stderr
    return runner


def execute(steps, runner, out):
    """Run steps in order, skipping any whose probe finds the thing already there.

    Stops at the first failure and returns its exit code, so a half-built testbed is reported
    where it broke instead of under a pile of later errors. Running `up` again carries on from
    there, because the probes skip what exists.
    """
    for i, s in enumerate(steps, 1):
        if s["probe"] and runner(s["probe"])[0] == 0:
            print("%d/%d already there: %s" % (i, len(steps), s["about"]), file=out)
            continue
        print("%d/%d %s" % (i, len(steps), s["about"]), file=out)
        code, _, err = runner(s["args"])
        if code != 0:
            print("FAILED: %s\n%s" % (show(s["args"]), err.strip()), file=out)
            return code
    return 0


def sku_cpus(sku):
    """vCPUs as the size list reports them, or None if it does not say."""
    for cap in sku.get("capabilities") or []:
        if cap.get("name") == "vCPUs":
            return int(cap["value"])
    return None


def preflight(spec, profile, runner, out):
    """Read the subscription's real limits and say whether the profile fits. Changes nothing."""
    code, stdout, err = runner(["account", "show", "--output", "json"])
    if code != 0:
        print("not logged in, or no subscription; run `az login` first\n%s" % err.strip(),
              file=out)
        return 1
    account = json.loads(stdout)
    print("subscription: %s (%s)" % (account.get("name"), account.get("state")), file=out)
    location, ok, short = spec["location"], True, False
    need = {"cores": 0}
    for name, host in profile_hosts(spec, profile):
        size = host["size"]
        code, stdout, err = runner(["vm", "list-skus", "--location", location, "--size", size,
                                    "--resource-type", "virtualMachines", "--all",
                                    "--output", "json"])
        if code != 0:
            print("could not list the sizes in %s: %s" % (location, err.strip()), file=out)
            return 1
        sku = next((s for s in json.loads(stdout) if s.get("name") == size), None)
        if sku is None:
            print("  %s: %s is not offered in %s; try another location in testbed.json"
                  % (name, size, location), file=out)
            ok = False
            continue
        reasons = [r.get("reasonCode", "restricted") for r in sku.get("restrictions") or []]
        if reasons:
            print("  %s: %s is restricted in %s for this subscription (%s); try another "
                  "location in testbed.json" % (name, size, location, ", ".join(reasons)),
                  file=out)
            ok = False
        cpus = sku_cpus(sku) or size_cpus(size)
        need["cores"] += cpus
        family = sku.get("family", "unknown family")
        need[family] = need.get(family, 0) + cpus
    code, stdout, err = runner(["vm", "list-usage", "--location", location, "--output", "json"])
    if code != 0:
        print("could not read the CPU limits in %s: %s" % (location, err.strip()), file=out)
        return 1
    usage = {u["name"]["value"]: u for u in json.loads(stdout)}
    if not usage:
        # Found on the first real account: a new subscription has Microsoft.Compute unregistered,
        # and Azure then reports an empty limit list rather than an error.
        print("Azure reports no CPU limits at all in %s. On a new subscription that means "
              "virtual machines are not switched on yet: az provider register --namespace "
              "Microsoft.Compute" % location, file=out)
        return 1
    for key in sorted(need, key=lambda k: (k != "cores", k)):
        label = "all CPUs in %s" % location if key == "cores" else key
        if key not in usage:
            print("  %s: no limit reported, so the fit cannot be confirmed" % label, file=out)
            ok = False
            continue
        limit, used = int(usage[key]["limit"]), int(usage[key]["currentValue"])
        if need[key] > limit - used:
            ok, short = False, True
        print("  %s: need %d, limit %d, in use %d -> %s"
              % (label, need[key], limit, used,
                 "fits" if need[key] <= limit - used else "DOES NOT FIT"), file=out)
    if short:
        print("A free trial cannot raise its CPU limits. Moving the subscription to "
              "pay-as-you-go keeps the remaining credit and allows a limit request "
              "(Subscriptions > Usage + quotas).", file=out)
    return 0 if ok else 1


def addresses_by_machine(listing):
    """{name: {"private": [...], "public": [...]}} from `az vm list-ip-addresses` output."""
    found = {}
    for entry in listing:
        vm = entry.get("virtualMachine") or {}
        net = vm.get("network") or {}
        found[vm.get("name")] = {
            "private": list(net.get("privateIpAddresses") or []),
            "public": [p["ipAddress"] for p in net.get("publicIpAddresses") or []
                       if p.get("ipAddress")],
        }
    return found


def hosts_env(spec, profile, runner, now=None):
    """The hosts.env text for a profile, after checking every address is where the file says."""
    code, stdout, err = runner(["vm", "list-ip-addresses", "--resource-group",
                                spec["resource_group"], "--output", "json"])
    if code != 0:
        raise RuntimeError("could not list the machines' addresses: %s" % err.strip())
    found = addresses_by_machine(json.loads(stdout))
    hosts = profile_hosts(spec, profile)
    problems = []
    for name, host in hosts:
        got = found.get(name)
        if got is None:
            problems.append("%s does not exist in %s" % (name, spec["resource_group"]))
            continue
        wanted = [host["private_ip"]]
        if host["role"] == "driver":
            wanted.append(host["receiver_ip"])
            if not got["public"]:
                problems.append("%s has no public address yet" % name)
        for address in wanted:
            if address not in got["private"]:
                problems.append("%s does not hold %s (it holds %s)"
                                % (name, address, ", ".join(got["private"]) or "nothing"))
    if problems:
        raise RuntimeError("; ".join(problems))
    driver_name, driver = [(n, h) for n, h in hosts if h["role"] == "driver"][0]
    brokers = [h for _, h in hosts if h["role"] == "broker"]
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = ["# Written by scripts/azure_testbed.py hosts --profile %s at %s." % (profile, stamp),
             "# The first names are the ones cloud/campaigns/common.sh reads.",
             "BROKER_PRIV=%s" % brokers[0]["private_ip"]]
    for n, broker in enumerate(brokers[1:3], 2):
        lines.append("BROKER%d_PRIV=%s" % (n, broker["private_ip"]))
    lines += ["SSH_KEY=$HOME/.ssh/azure_sbl",
              "AZ_PROFILE=%s" % profile,
              "DRIVER_NAME=%s" % driver_name,
              "DRIVER_PUBLIC=%s" % found[driver_name]["public"][0],
              "DRIVER_PRIV=%s" % driver["private_ip"],
              "RECEIVER_IP=%s" % driver["receiver_ip"],
              "SUBNET_PREFIX=%d" % ipaddress.ip_network(spec["vnet"]["subnet_cidr"]).prefixlen,
              "SUBNET_GATEWAY=%s" % gateway(spec)]
    return "\n".join(lines) + "\n"


# --- the subcommands -------------------------------------------------------------------------

def cmd_plan(spec, args, runner, out):
    for line in plan_summary(spec, args.profile):
        print(line, file=out)
    print("", file=out)
    print_plan(up_steps(spec, args.profile, args.ssh_source or "YOUR.ADDRESS/32",
                        spec["custom_data"]), out)
    return 0


def cmd_up(spec, args, runner, out):
    problem = ssh_source_problem(args.ssh_source)
    key = os.path.expanduser(spec["ssh_public_key"])
    if problem is None and not os.path.isfile(key):
        problem = ("no SSH public key at %s; make the pair with: ssh-keygen -t ed25519 -f %s -N ''"
                   % (key, key[:-len(".pub")] if key.endswith(".pub") else key))
    if problem:
        print("ERROR: %s" % problem, file=out)
        return 2
    text = custom_data_text(os.path.join(REPO, spec["custom_data"]))
    if not args.yes:
        for line in plan_summary(spec, args.profile):
            print(line, file=out)
        print_plan(up_steps(spec, args.profile, args.ssh_source, spec["custom_data"]), out)
        print("\nNothing was created. Add --yes to create it; the machines bill from the moment "
              "they exist.", file=out)
        return 1
    fd, path = tempfile.mkstemp(prefix="sbl-cloud-init-", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return execute(up_steps(spec, args.profile, args.ssh_source, path), runner, out)
    finally:
        os.remove(path)


def cmd_preflight(spec, args, runner, out):
    return preflight(spec, args.profile, runner, out)


def cmd_hosts(spec, args, runner, out):
    text = hosts_env(spec, args.profile, runner)
    if not args.write:
        out.write(text)
        return 0
    with open(args.write, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote %s" % args.write, file=out)
    return 0


def cmd_power(spec, args, runner, out):
    steps = power_steps(spec, args.profile, args.command)
    if not args.yes:
        print_plan(steps, out)
        print("\nNothing was changed. Add --yes to %s the machines." % args.command, file=out)
        return 1
    return execute(steps, runner, out)


def cmd_status(spec, args, runner, out):
    code, stdout, err = runner(["vm", "list", "--show-details", "--resource-group",
                                spec["resource_group"], "--output", "json"])
    if code != 0:
        print("could not list the machines: %s" % err.strip(), file=out)
        return 1
    machines = json.loads(stdout)
    if not machines:
        print("no machines in %s" % spec["resource_group"], file=out)
    for vm in machines:
        print("%-16s %-18s %-20s %s"
              % (vm.get("name"), (vm.get("hardwareProfile") or {}).get("vmSize"),
                 vm.get("powerState"), vm.get("publicIps") or "-"), file=out)
    return 0


def cmd_down(spec, args, runner, out):
    rg = spec["resource_group"]
    command = ["group", "delete", "--name", rg, "--yes", "--no-wait"]
    if args.confirm != rg:
        print("This deletes every machine, disk and address in %s, and cannot be undone." % rg,
              file=out)
        print("To go ahead, run it again with --confirm %s. It would run:\n%s"
              % (rg, show(command)), file=out)
        return 1
    code, _, err = runner(command)
    if code != 0:
        print("FAILED: %s" % err.strip(), file=out)
        return code
    print("deletion of %s has started; `status` shows when it is gone" % rg, file=out)
    return 0


COMMANDS = {"plan": cmd_plan, "preflight": cmd_preflight, "up": cmd_up, "hosts": cmd_hosts,
            "stop": cmd_power, "start": cmd_power, "status": cmd_status, "down": cmd_down}


def main(argv=None, runner=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(
        description="Plan, check, create, pause and remove the Azure testbed")
    ap.add_argument("--spec", default=SPEC)
    sub = ap.add_subparsers(dest="command", required=True)
    parsers = {name: sub.add_parser(name) for name in PROFILE_COMMANDS + ("status", "down")}
    for parser in parsers.values():
        parser.add_argument("--profile", default="matched")
    for name in ("plan", "up"):
        parsers[name].add_argument("--ssh-source", default="")
    for name in ("up", "stop", "start"):
        parsers[name].add_argument("--yes", action="store_true")
    parsers["hosts"].add_argument("--write", default="")
    parsers["down"].add_argument("--confirm", default="")
    args = ap.parse_args(argv)
    runner = runner or make_runner()
    try:
        spec = profile_spec(load_spec(args.spec), args.profile)
        return COMMANDS[args.command](spec, args, runner, out)
    except (RuntimeError, ValueError, OSError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
