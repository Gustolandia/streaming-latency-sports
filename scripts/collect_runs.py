#!/usr/bin/env python3
"""
collect_runs.py -- copy a finished campaign off its driver, with a fingerprint for every file.

A campaign's runs exist only on its driver until they are copied, and a copy is where results get
lost without anyone noticing: a transfer cut short, a file that changed after it was listed. So
the copy is checked end to end.

  1. On the driver, the campaign's queue names its run directories: every attempt, done or
     failed. Every file in them, and the queue itself, gets a SHA-256 fingerprint.
  2. They are packed into one archive there, and the archive is fingerprinted too.
  3. The archive comes here and its fingerprint is checked. It is unpacked, refusing any entry
     that would land outside the destination or is not a plain file or folder, and every file is
     checked against its fingerprint.
  4. SHA256SUMS and COLLECTED.json record what came, from which machine and commit, and when.

Nothing on the driver is deleted except the temporary folder this made there. A copy that fails
its check is reported, and the runs stay where they were.

Usage:
    python scripts/collect_runs.py --hosts cloud/hosts.env --queue runs/azure/queues/c0.csv
    python scripts/collect_runs.py --hosts cloud/hosts_b.env --queue runs/azure/queues/a5.csv
"""
import argparse
import datetime
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import azure_testbed  # noqa: E402
import testbed_watch  # noqa: E402

DEST = os.path.join(azure_testbed.REPO, "runs", "azure", "collected")
#: The only temporary folder this program will ask a driver to remove.
WORK_PREFIX = "/tmp/sbl_collect."

PACK = r"""set -euo pipefail
cd ~/sbl
queue=@QUEUE@
if [ ! -f "$queue" ]; then echo "error=there is no queue at $queue on the driver"; exit 0; fi
work=$(mktemp -d /tmp/sbl_collect.XXXXXX)
python3 - "$queue" > "$work/list" <<'PY'
import csv, os, sys
queue = sys.argv[1]
paths = [queue]
with open(queue, newline="", encoding="utf-8") as fh:
    for row in csv.DictReader(fh):
        run_dir = row.get("run_dir") or "runs/law_%s" % row["key"]
        if os.path.isdir(run_dir) and run_dir not in paths:
            paths.append(run_dir)
print("\n".join(paths))
PY
while IFS= read -r path; do find "$path" -type f -print0; done < "$work/list" \
  | sort -z | xargs -0 -r sha256sum > "$work/manifest"
tar -cf "$work/runs.tar" -T "$work/list"
echo "work=$work"
echo "archive=$work/runs.tar"
echo "archive_sha256=$(sha256sum "$work/runs.tar" | cut -d' ' -f1)"
echo "commit=$(git rev-parse HEAD)"
echo "host=$(hostname)"
sed 's/^/manifest=/' "$work/manifest"
"""


def remote_script(queue):
    """The packing script for one queue, with its path quoted for the shell."""
    return PACK.replace("@QUEUE@", shlex.quote(queue))


def parse_pack(text):
    """What the driver reported: its temporary folder, the archive, and every file's fingerprint."""
    facts = {"manifest": []}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            continue
        if key == "manifest":
            digest, _, path = value.partition("  ")
            facts["manifest"].append((digest.strip(), path.strip()))
        else:
            facts[key] = value.strip()
    if "error" in facts:
        raise RuntimeError(facts["error"])
    missing = [k for k in ("work", "archive", "archive_sha256") if k not in facts]
    if missing:
        raise RuntimeError("the driver's answer lacks %s" % ", ".join(missing))
    if not facts["manifest"]:
        raise RuntimeError("the driver listed no files to copy")
    return facts


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_extract(archive, dest):
    """Unpack `archive` into `dest`, refusing anything that is not a plain file or folder inside
    it. Every entry is checked before the first is written. Returns the files unpacked."""
    root = os.path.realpath(dest)
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        for member in members:
            target = os.path.realpath(os.path.join(root, member.name))
            if target != root and not target.startswith(root + os.sep):
                raise RuntimeError("the archive holds %r, which would land outside %s"
                                   % (member.name, dest))
            if not (member.isfile() or member.isdir()):
                raise RuntimeError("the archive holds %r, which is not a plain file or folder"
                                   % member.name)
        files = []
        for member in members:
            target = os.path.join(root, member.name)
            if member.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with tar.extractfile(member) as source, open(target, "wb") as copy:
                shutil.copyfileobj(source, copy)
            files.append(member.name)
    return files


def verify(dest, manifest):
    """Every file the driver fingerprinted that did not arrive here, or arrived different."""
    problems = []
    for digest, path in manifest:
        local = os.path.join(dest, path)
        if not os.path.isfile(local):
            problems.append("%s did not arrive" % path)
        elif sha256_file(local) != digest:
            problems.append("%s differs from the driver's copy" % path)
    return problems


def last_line(code, stdout, stderr):
    lines = (stderr or stdout or "").strip().splitlines()
    return lines[-1] if lines else "exit %d" % code


def collect(hosts, queue, dest, key, ssh="ssh", scp="scp", run=subprocess.run, clock=None):
    """Copy one campaign's runs and check them. Returns what COLLECTED.json records."""
    opts = ["-i", key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
            "-o", "StrictHostKeyChecking=accept-new"]
    driver = "ubuntu@%s" % hosts["DRIVER_PUBLIC"]
    home = os.path.join(dest, hosts["AZ_PROFILE"], os.path.splitext(os.path.basename(queue))[0])
    if os.path.exists(os.path.join(home, "COLLECTED.json")):
        raise RuntimeError("%s is already collected in %s; move that folder aside to collect it "
                           "again" % (queue, home))
    code, stdout, stderr = testbed_watch.run_script(
        run, [ssh] + opts + [driver, "bash -s"], remote_script(queue), 1800)
    if code != 0:
        raise RuntimeError("the driver could not pack the runs: %s"
                           % last_line(code, stdout, stderr))
    facts = parse_pack(stdout)
    if not facts["work"].startswith(WORK_PREFIX):
        raise RuntimeError("the driver named %r as its temporary folder; refusing to use it"
                           % facts["work"])
    try:
        os.makedirs(home, exist_ok=True)
        archive = os.path.join(home, "runs.tar")
        copied = run([scp] + opts + ["%s:%s" % (driver, facts["archive"]), archive],
                     capture_output=True, text=True, timeout=3600)
        if copied.returncode != 0:
            raise RuntimeError("the archive did not copy: %s"
                               % last_line(copied.returncode, copied.stdout, copied.stderr))
        digest = sha256_file(archive)
        if digest != facts["archive_sha256"]:
            raise RuntimeError("the archive's fingerprint here, %s, is not the driver's, %s"
                               % (digest, facts["archive_sha256"]))
        safe_extract(archive, home)
        problems = verify(home, facts["manifest"])
        if problems:
            more = " (and %d more)" % (len(problems) - 5) if len(problems) > 5 else ""
            raise RuntimeError("the copy does not match the driver: %s%s"
                               % ("; ".join(problems[:5]), more))
    finally:
        run([ssh] + opts + [driver, "rm -rf %s" % shlex.quote(facts["work"])],
            capture_output=True, text=True, timeout=120)
    now = (clock or (lambda: datetime.datetime.now(datetime.timezone.utc)))()
    record = {"queue": queue, "profile": hosts["AZ_PROFILE"], "driver": facts.get("host"),
              "driver_address": hosts["DRIVER_PUBLIC"], "commit": facts.get("commit"),
              "files": len(facts["manifest"]), "archive_sha256": digest,
              "collected_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    with open(os.path.join(home, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines("%s  %s\n" % pair for pair in facts["manifest"])
    with open(os.path.join(home, "COLLECTED.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def main(argv=None, run=subprocess.run, clock=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Copy a finished campaign off its driver, checked")
    ap.add_argument("--hosts", default=testbed_watch.HOSTS_ENV)
    ap.add_argument("--queue", required=True, help="the queue's path on the driver, under ~/sbl")
    ap.add_argument("--dest", default=DEST)
    ap.add_argument("--key", default=testbed_watch.KEY)
    ap.add_argument("--ssh", default="ssh")
    ap.add_argument("--scp", default="scp")
    args = ap.parse_args(argv)
    try:
        hosts = testbed_watch.read_hosts(args.hosts)
        record = collect(hosts, args.queue, args.dest, os.path.expanduser(args.key), args.ssh,
                         args.scp, run, clock)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, tarfile.TarError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2
    print("collected %d files of %s from %s (commit %s) into %s"
          % (record["files"], record["queue"], record["driver"], (record["commit"] or "?")[:8],
             os.path.join(args.dest, record["profile"])), file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
