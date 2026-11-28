"""The real container of the code checks (ADR-048), on the image the user built (E4).

Skipped unless ``CERVEAU_CHECKS_IMAGE`` names that image (``sha256:<64 hex>``) and Docker runs:
it starts containers, so it stays out of ``make test`` and of the CI. Run it after building or
changing the image, or after a Docker update. It reads, from inside the container, what the
command line promises: no network interface but loopback, no capability, no new privilege, the
unprivileged user, a read-only root and copy, a writable ``/tmp`` only, the process limit, the
``timeout`` of the image and no proxy variable (B282, B284); then that a program that never ends
is stopped by the container's own limit, nobody killing it (B282).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from core.code.git import GitRunner
from core.code.repos import RepoReader
from core.code.sandbox import PROXY_VARIABLES, DockerRunner, Limits, copy_tree, docker_command
from tests.code_support import listed, make_repo

IMAGE = os.environ.get("CERVEAU_CHECKS_IMAGE", "")
pytestmark = pytest.mark.skipif(
    not re.fullmatch(r"sha256:[0-9a-f]{64}", IMAGE),
    reason="CERVEAU_CHECKS_IMAGE (sha256:<64 hex>) absent : conteneur réel non testé",
)

PROBE = """
import json, os, shutil, socket, subprocess
def writable(path):
    try:
        with open(os.path.join(path, "essai"), "w") as handle:
            handle.write("x")
        return True
    except OSError:
        return False
status = dict(line.split(":\\t", 1) for line in open("/proc/self/status").read().splitlines())
ruff = subprocess.run(["ruff", "--version"], capture_output=True, text=True)
proxies = sorted(name for name in os.environ if name.lower().endswith("_proxy"))
print(json.dumps({
    "interfaces": sorted(name for _, name in socket.if_nameindex()),
    "uid": os.getuid(),
    "gid": os.getgid(),
    "cap_eff": status["CapEff"].strip(),
    "no_new_privs": status["NoNewPrivs"].strip(),
    "root": writable("/"),
    "work": writable("/work"),
    "tmp": writable("/tmp"),
    "files": sorted(os.listdir("/work")),
    "pids_max": open("/sys/fs/cgroup/pids.max").read().strip(),
    "ruff": ruff.stdout.strip(),
    "timeout": shutil.which("timeout"),
    "proxies": proxies,
    "proxies_empty": all(os.environ[name] == "" for name in proxies),
}))
"""


def _copy(tmp_path: Path) -> Path:
    repo = make_repo(tmp_path / "projet", {"a.py": "x = 1\n"})
    reader = RepoReader(GitRunner(), cerveau_root=tmp_path / "cerveau-absent")
    opened = reader.open([listed("p", repo)], "p")
    copy = copy_tree(reader, opened, "HEAD", tmp_path / "copie", max_files=10, max_bytes=1_000)
    return copy.root


def _command(name: str, source: Path, max_seconds: int, code: str) -> list[str]:
    return docker_command(
        name,
        IMAGE,
        source,
        Limits(1, 256, 64),
        "python",
        ["-c", code],
        max_seconds=max_seconds,
        ends_by=int(time.time()) + max_seconds + 10,
    )


def test_the_container_is_confined(tmp_path: Path) -> None:
    name = "cerveau-check-test"
    command = _command(name, _copy(tmp_path), 60, PROBE)
    out = DockerRunner().run(command, name=name, timeout_s=60, max_bytes=100_000)
    assert (out.returncode, out.timed_out, out.truncated) == (0, False, False), out.stderr
    seen = json.loads(out.stdout)
    assert seen["interfaces"] == ["lo"]
    assert (seen["uid"], seen["gid"]) == (65534, 65534)
    assert seen["cap_eff"] == "0000000000000000"
    assert seen["no_new_privs"] == "1"
    assert (seen["root"], seen["work"], seen["tmp"]) == (False, False, True)
    assert seen["files"] == ["a.py"]
    assert seen["pids_max"] == "64"
    assert seen["ruff"].startswith("ruff ")
    assert seen["timeout"] == "/usr/bin/timeout"
    # Set empty by the command, so the client's configuration fills none of them (B284).
    assert seen["proxies"] == sorted(PROXY_VARIABLES)
    assert seen["proxies_empty"] is True


def test_a_program_that_never_ends_is_stopped_by_the_container_itself(tmp_path: Path) -> None:
    """B282: past its own limit the container ends (137, ``timeout -s KILL``), nobody killing
    it; the client's limit, far later, is not reached."""
    name = "cerveau-check-test-boucle"
    command = _command(name, _copy(tmp_path), 3, "while True: pass")
    start = time.monotonic()
    out = DockerRunner().run(command, name=name, timeout_s=60, max_bytes=100_000)
    assert (out.returncode, out.timed_out, out.stopped) == (137, False, None), out.stderr
    assert time.monotonic() - start < 30
