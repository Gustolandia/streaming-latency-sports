"""The shell the tests run the kit's shell scripts in, the same way on Windows as on Linux.

The kit's scripts run on the Linux drivers, and the tests that run them were skipped on Windows.
That let a script, or a test of one, be broken for as long as nobody looked at Linux: CI failed 78
commits in a row between 22 and 25 September on tests the author's machine never ran. Every test
now runs on both.

Three things stood in the way on Windows.

* A bare "bash" is not Git's. CreateProcess looks in System32 before PATH, and System32's
  bash.exe is WSL's launcher, which runs the default distribution -- on the author's machine a
  Docker one with no bash in it at all. So the tests name the bash they mean.
* `python3` is a Microsoft Store alias that installs nothing and runs nothing. The scripts call
  `python3`, so the shell is given one that runs the Python running the tests.
* Git's own tools (awk, sed, timeout, ...) need not be on PATH. They sit beside its bash, and are
  put first on the PATH the shell is given.

What Git's bash cannot be is Linux: it has no flock, no setsid, no /proc of Linux's kind and no
`ps -eo`. A test of what the Linux kernel does -- how a lock is held, which process holds it -- is
run on Windows in the Linux the scripts are written for, through WSL (`linux_bash`).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PureWindowsPath

WINDOWS = sys.platform == "win32"
#: The distribution the kernel tests use on Windows: the drivers' own release.
WSL_DISTRIBUTION = os.environ.get("SBL_WSL_DISTRIBUTION", "Ubuntu-22.04")
REPO = Path(__file__).resolve().parent.parent


def _find_bash():
    """Git's bash on Windows, wherever Git is installed; the system's bash elsewhere."""
    if not WINDOWS:
        return shutil.which("bash")
    candidates = []
    git = shutil.which("git")
    if git:
        candidates += [up / "usr" / "bin" / "bash.exe" for up in Path(git).resolve().parents]
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"),
                 r"C:\Program Files"):
        if root:
            candidates.append(Path(root) / "Git" / "usr" / "bin" / "bash.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("bash")
    return found if found and "system32" not in found.lower() else None


BASH = _find_bash()


def _shell_path():
    """The PATH a shell is given: on Windows, a python3 that is this Python, then Git's tools."""
    if not WINDOWS or not BASH:
        return os.environ.get("PATH", "")
    shim = Path(tempfile.gettempdir()) / "sbl-test-python3"
    shim.mkdir(exist_ok=True)
    (shim / "python3").write_text('#!/bin/sh\nexec "%s" "$@"\n' % Path(sys.executable).as_posix(),
                                  encoding="utf-8", newline="\n")
    return os.pathsep.join([str(shim), str(Path(BASH).parent), os.environ.get("PATH", "")])


SHELL_PATH = _shell_path()


def shell_env(extra=None, path_first=()):
    """This process's environment with the PATH a shell is to be given, the folders in
    `path_first` ahead of it, and `extra` over the rest."""
    env = dict(os.environ)
    env.update(extra or {})
    env["PATH"] = os.pathsep.join([str(p) for p in path_first] + [SHELL_PATH])
    return env


def bash(args, extra_env=None, path_first=(), **kw):
    """`bash ARGS` with the right bash and PATH, taking what subprocess.run takes."""
    return subprocess.run([BASH] + list(args), env=shell_env(extra_env, path_first), **kw)


def tool(name):
    """A POSIX tool by name: on Windows the one beside Git's bash, rather than whatever program
    of that name comes first on PATH."""
    if WINDOWS and BASH:
        found = shutil.which(name, path=str(Path(BASH).parent))
        if found:
            return found
    return shutil.which(name) or name


def linux_path(path):
    """Where a path on this machine is seen from Linux: itself on Linux, under /mnt from WSL."""
    if not WINDOWS:
        return str(path)
    win = PureWindowsPath(os.path.abspath(path))
    return "/mnt/%s/%s" % (win.drive.rstrip(":").lower(), "/".join(win.parts[1:]))


def linux_bash(script, timeout=300):
    """Run SCRIPT in Linux's bash: here on Linux, and through WSL on Windows. The script finds
    the checkout it is to test in $REPO, and is given nothing else of this machine's."""
    body = "REPO=%s\n%s" % (_quoted(linux_path(REPO)), script)
    if WINDOWS:
        #: --exec, not --: without it WSL hands the command to a login shell first, which
        #: expands every $ in the script before bash ever sees it.
        command = ["wsl", "-d", WSL_DISTRIBUTION, "--exec", "bash", "-c", body]
    else:
        command = [BASH, "-c", body]
    return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=timeout)


def _quoted(text):
    return "'%s'" % text.replace("'", "'\\''")
