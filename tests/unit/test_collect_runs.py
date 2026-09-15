"""Tests for scripts/collect_runs.py.

Nothing here reaches a machine. A fake driver answers the packing script from files in a
temporary folder: it packs a real archive and fingerprints real files, so every check the copy
makes runs against bytes, including the ways a copy goes wrong.
"""
import datetime
import hashlib
import io
import json
import re
import shutil
import sys
import os
import tarfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import collect_runs as cr  # noqa: E402

QUEUE = "runs/azure/queues/c0.csv"
HOSTS = {"DRIVER_PUBLIC": "4.223.79.212", "AZ_PROFILE": "matched", "BROKER_PRIV": "10.1.1.21"}
STAMP = datetime.datetime(2026, 9, 16, 8, 0, tzinfo=datetime.timezone.utc)
HEADER = "key,round,setup,params,status,attempt,reason,started_utc,finished_utc,run_dir,seed\n"


class Done:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


@pytest.fixture
def driver(tmp_path):
    """A driver's checkout: one queue, a run that finished, and an attempt that failed."""
    home = tmp_path / "driver"
    (home / "runs" / "azure" / "queues").mkdir(parents=True)
    (home / QUEUE).write_text(
        HEADER + "r001-s0-a1,1,s0,{},done,1,,t,t,runs/law_r001-s0-a1,1\n"
        "r001-s1-a1,1,s1,{},failed,1,load off,t,t,,1\n"
        "r002-s0-a1,2,s0,{},queued,1,,,,,1\n", encoding="utf-8")
    for run, names in (("law_r001-s0-a1", ("producer.csv", "integrity.json")),
                       ("law_r001-s1-a1", ("trial.log",))):
        (home / "runs" / run).mkdir(parents=True)
        for name in names:
            (home / "runs" / run / name).write_text("%s of %s\n" % (name, run), encoding="utf-8")
    return home


def fake_driver(home, tmp_path, seen, tamper=None, ssh_code=0, scp_code=0):
    """Answers the three things collect asks of a driver: pack, copy, and remove the folder."""
    work = tmp_path / "remote_work"

    def run(argv, **kwargs):
        seen.append(argv)
        if argv[0] == "scp":
            if scp_code:
                return Done("", scp_code, "lost connection")
            shutil.copyfile(str(work / "runs.tar"), argv[-1])
            return Done()
        if argv[-1].startswith("rm -rf"):
            return Done()
        if ssh_code:
            return Done("", ssh_code, "banner\nPermission denied (publickey).")
        assert "queue=%s\n" % QUEUE in kwargs["input"]
        paths = [QUEUE] + [p for p in ("runs/law_r001-s0-a1", "runs/law_r001-s1-a1")
                           if (home / p).is_dir()]
        work.mkdir(exist_ok=True)
        manifest = []
        with tarfile.open(str(work / "runs.tar"), "w") as tar:
            for p in paths:
                tar.add(str(home / p), arcname=p)
                full = home / p
                files = [full] if full.is_file() else sorted(f for f in full.rglob("*")
                                                             if f.is_file())
                manifest += [(digest(f), f.relative_to(home).as_posix()) for f in files]
        lines = ["Warning: Permanently added the host key", "work=/tmp/sbl_collect.test",
                 "archive=/tmp/sbl_collect.test/runs.tar",
                 "archive_sha256=%s" % digest(work / "runs.tar"), "commit=0a1b2c3d4e5f6a7b",
                 "host=sbl-az-drv"]
        lines += ["manifest=%s  %s" % pair for pair in sorted(manifest, key=lambda m: m[1])]
        text = "\n".join(lines) + "\n"
        return Done(tamper(text) if tamper else text)
    return run


def collect(driver, tmp_path, seen=None, **kwargs):
    seen = [] if seen is None else seen
    return cr.collect(HOSTS, QUEUE, str(tmp_path / "here"), "key",
                      run=fake_driver(driver, tmp_path, seen, **kwargs), clock=lambda: STAMP)


class TestACampaignArrivesWhole:

    def test_every_file_arrives_checked_and_recorded(self, driver, tmp_path):
        seen = []
        record = collect(driver, tmp_path, seen)
        home = tmp_path / "here" / "matched" / "c0"
        assert record["files"] == 4 and record["driver"] == "sbl-az-drv"
        assert record["commit"] == "0a1b2c3d4e5f6a7b" and record["driver_address"] == "4.223.79.212"
        assert (home / "runs" / "law_r001-s1-a1" / "trial.log").read_text(encoding="utf-8") == \
            "trial.log of law_r001-s1-a1\n", "a failed attempt's files come too"
        sums = (home / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        assert len(sums) == 4 and sums[0].endswith("  runs/azure/queues/c0.csv")
        with open(home / "COLLECTED.json", encoding="utf-8") as fh:
            assert json.load(fh)["collected_utc"] == "2026-09-16T08:00:00Z"
        assert seen[-1][-1] == "rm -rf /tmp/sbl_collect.test"

    def test_a_campaign_already_collected_is_not_copied_over(self, driver, tmp_path):
        home = tmp_path / "here" / "matched" / "c0"
        home.mkdir(parents=True)
        (home / "COLLECTED.json").write_text("{}", encoding="utf-8")
        seen = []
        with pytest.raises(RuntimeError, match="already collected"):
            collect(driver, tmp_path, seen)
        assert seen == []

    def test_the_queue_path_is_quoted_for_the_shell(self):
        script = cr.remote_script("runs/azure/queues/a b.csv")
        assert "queue='runs/azure/queues/a b.csv'\n" in script and "@QUEUE@" not in script
        assert "sha256sum" in script and 'tar -cf "$work/runs.tar"' in script


class TestACopyThatCannotBeTrusted:

    def test_a_driver_that_cannot_be_reached(self, driver, tmp_path):
        with pytest.raises(RuntimeError, match="could not pack the runs: Permission denied"):
            collect(driver, tmp_path, ssh_code=255)

    @pytest.mark.parametrize("tamper,fragment", [
        (lambda t: "error=there is no queue at x on the driver\n", "there is no queue at x"),
        (lambda t: re.sub(r"archive_sha256=\w+\n", "", t), "lacks archive_sha256"),
        (lambda t: re.sub(r"manifest=.*\n", "", t), "listed no files to copy"),
        (lambda t: t.replace("work=/tmp/sbl_collect.test", "work=/home/ubuntu"),
         "refusing to use it")])
    def test_an_answer_that_is_not_what_a_packing_gives(self, driver, tmp_path, tamper, fragment):
        seen = []
        with pytest.raises(RuntimeError, match=re.escape(fragment)):
            collect(driver, tmp_path, seen, tamper=tamper)
        assert not any(a[-1].startswith("rm -rf") for a in seen), (
            "nothing is removed when the driver's own answer is in doubt")

    def test_an_archive_that_did_not_copy_is_cleaned_up_after(self, driver, tmp_path):
        seen = []
        with pytest.raises(RuntimeError, match="did not copy: lost connection"):
            collect(driver, tmp_path, seen, scp_code=1)
        assert seen[-1][-1] == "rm -rf /tmp/sbl_collect.test"

    def test_an_archive_whose_fingerprint_differs(self, driver, tmp_path):
        tamper = lambda t: re.sub(r"archive_sha256=\w+", "archive_sha256=" + "0" * 64, t)
        with pytest.raises(RuntimeError, match="is not the driver's"):
            collect(driver, tmp_path, tamper=tamper)

    def test_files_that_changed_or_never_came(self, driver, tmp_path):
        def tamper(text):
            out = []
            for line in text.splitlines():
                if line.startswith("manifest=") and line.endswith("producer.csv"):
                    line = "manifest=%s  %s" % ("f" * 64, line.split("  ", 1)[1])
                out.append(line)
            out += ["manifest=%s  runs/law_ghost/x%d.csv" % ("0" * 64, i) for i in range(6)]
            return "\n".join(out) + "\n"
        with pytest.raises(RuntimeError) as exc:
            collect(driver, tmp_path, tamper=tamper)
        text = str(exc.value)
        assert "runs/law_r001-s0-a1/producer.csv differs from the driver's copy" in text
        assert "runs/law_ghost/x0.csv did not arrive" in text and text.endswith("(and 2 more)")
        assert not (tmp_path / "here" / "matched" / "c0" / "COLLECTED.json").exists()

    def test_the_last_line_of_an_empty_answer(self):
        assert cr.last_line(Done("", 3, "")) == "exit 3"


def archive_with(tmp_path, *entries):
    path = tmp_path / "a.tar"
    with tarfile.open(str(path), "w") as tar:
        for kind, name in entries:
            info = tarfile.TarInfo(name)
            if kind == "file":
                data = b"x"
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            elif kind == "dir":
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            else:
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                tar.addfile(info)
    return str(path)


class TestUnpacking:

    def test_plain_files_and_folders_unpack(self, tmp_path):
        archive = archive_with(tmp_path, ("dir", "."), ("dir", "runs"), ("file", "runs/a.csv"))
        assert cr.safe_extract(archive, str(tmp_path / "out")) == ["runs/a.csv"]
        assert (tmp_path / "out" / "runs" / "a.csv").read_bytes() == b"x"

    @pytest.mark.parametrize("entries,fragment", [
        ((("file", "../evil.txt"),), "would land outside"),
        ((("file", "ok.txt"), ("link", "runs/link")), "not a plain file or folder")])
    def test_what_would_write_outside_or_is_a_link_is_refused_before_anything_lands(
            self, tmp_path, entries, fragment):
        with pytest.raises(RuntimeError, match=fragment):
            cr.safe_extract(archive_with(tmp_path, *entries), str(tmp_path / "out"))
        assert not (tmp_path / "out" / "ok.txt").exists()


class TestMain:

    @staticmethod
    def hosts(tmp_path):
        path = tmp_path / "hosts.env"
        path.write_text("DRIVER_PUBLIC=4.223.79.212\nBROKER_PRIV=10.1.1.21\nAZ_PROFILE=matched\n",
                        encoding="utf-8")
        return str(path)

    def test_it_says_what_came_and_where(self, driver, tmp_path):
        out = io.StringIO()
        code = cr.main(["--hosts", self.hosts(tmp_path), "--queue", QUEUE, "--dest",
                        str(tmp_path / "here")], run=fake_driver(driver, tmp_path, []),
                       clock=lambda: STAMP, out=out)
        assert code == 0 and "collected 4 files of %s from sbl-az-drv (commit 0a1b2c3d)" % QUEUE \
            in out.getvalue()

    def test_a_driver_that_does_not_say_its_commit(self, driver, tmp_path):
        out = io.StringIO()
        tamper = lambda t: re.sub(r"commit=\w+\n", "", t)
        code = cr.main(["--hosts", self.hosts(tmp_path), "--queue", QUEUE, "--dest",
                        str(tmp_path / "here")],
                       run=fake_driver(driver, tmp_path, [], tamper=tamper), out=out)
        assert code == 0 and "(commit ?)" in out.getvalue()

    def test_errors_are_one_line(self, tmp_path):
        out = io.StringIO()
        assert cr.main(["--hosts", str(tmp_path / "none.env"), "--queue", QUEUE], out=out) == 2
        assert out.getvalue().startswith("ERROR:")
