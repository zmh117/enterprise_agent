"""Synthetic SVN fixture, only invoked in disposable Linux containers."""

import errno
import json
import os
from pathlib import Path
import subprocess
import sys

from app.modules.knowledge.infrastructure.code_checkout_client import WorkingCopyClient
from app.modules.knowledge.infrastructure.code_checkout_identity import persistent_identity
from app.modules.knowledge.infrastructure.code_svn import SvnCodeSource
from app.modules.knowledge.infrastructure.code_working_copy import SvnWorkingCopy
from app.python_runtime.code_checkout_reader import CodeCheckoutReader
from scripts.deployment_check import initialize_code_directories

ROOT = Path("/fixture")
CHECKOUT = ROOT / "checkouts"
PRIVATE = ROOT / "private"
GRANT = CHECKOUT / "grant.json"


def svn(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def prepare() -> None:
    initialize_code_directories(CHECKOUT, ROOT / "state")
    initialize_code_directories(CHECKOUT, ROOT / "state")
    PRIVATE.mkdir(mode=0o700)
    os.chown(PRIVATE, 10003, 10003)
    writable = ROOT / "reader-owned"
    writable.mkdir(mode=0o700)
    os.chown(writable, 10002, 10002)


def source() -> SvnCodeSource:
    repo = PRIVATE / "repo"
    return SvnCodeSource(
        branch_url=repo.as_uri() + "/trunk",
        expected_uuid=svn("svnlook", "uuid", str(repo)),
        branch_path="/trunk",
        config_directory=PRIVATE / "auth",
        allow_local_test=True,
    )


def checkout() -> None:
    # Exercise the actual credential entrypoint: it must remain private.
    previous = os.umask(0o077)
    assert previous == 0o077
    (PRIVATE / "synthetic-credential").write_text("fixture-only")
    assert (PRIVATE / "synthetic-credential").stat().st_mode & 0o777 == 0o600
    (PRIVATE / "auth").mkdir()
    repo = PRIVATE / "repo"
    svn("svnadmin", "create", str(repo))
    svn("svn", "mkdir", repo.as_uri() + "/trunk", "-m", "synthetic trunk")
    seed = PRIVATE / "seed"
    seed.mkdir()
    (seed / "规则.cpp").write_text("int synthetic_rule = 2;\n")
    svn("svn", "import", str(seed), repo.as_uri() + "/trunk", "-m", "synthetic r2")
    access = source()
    entry = dict(
        public_url="https://synthetic.invalid/trunk",
        branch_url="https://synthetic.invalid/trunk",
        repository_uuid=access.expected_uuid,
        branch_path="/trunk",
        auth_ref="auth",
    )
    client = WorkingCopyClient(entry, PRIVATE)
    client.source = access
    client.checkout(root=CHECKOUT, folder="copy", job_id="fixture", revision=2, paths=[""])
    key = persistent_identity(CHECKOUT / "copy", create=True)
    grant = dict(
        directory="copy",
        physical_key=key,
        allowed_paths=[""],
        revision=2,
        branch_path="trunk",
        repository_uuid=access.expected_uuid,
    )
    GRANT.write_text(json.dumps(grant))
    GRANT.chmod(0o640)


def update() -> None:
    writer = PRIVATE / "writer"
    access = source()
    svn("svn", "checkout", access.branch_url, str(writer))
    (writer / "新增 目录").mkdir()
    (writer / "新增 目录/新增规则.cpp").write_text("int new_rule = 3;\n")
    svn("svn", "add", str(writer / "新增 目录"))
    svn("svn", "commit", str(writer), "-m", "synthetic r3")
    grant = json.loads(GRANT.read_text())
    copy = SvnWorkingCopy(access, CHECKOUT / "copy", [""], physical_key=grant["physical_key"])
    copy.update(3, timeout=60)
    grant["revision"] = 3
    GRANT.write_text(json.dumps(grant))


def read(revision: int) -> None:
    grant = json.loads(GRANT.read_text())
    assert grant["revision"] == revision
    reader = CodeCheckoutReader(CHECKOUT, grant)
    assert "synthetic_rule" in reader.read("规则.cpp", 1, 2)["text"]
    if revision == 3:
        assert "new_rule" in reader.read("新增 目录/新增规则.cpp", 1, 2)["text"]
    try:
        (ROOT / "reader-owned/write").write_text("must not write")
    except OSError as exc:
        assert exc.errno == errno.EROFS
    else:
        raise AssertionError("Runtime mount allowed a write")
    try:
        (PRIVATE / "synthetic-credential").read_bytes()
    except PermissionError:
        pass
    else:
        raise AssertionError("Runtime read private credentials")


def outsider() -> None:
    try:
        (CHECKOUT / "copy/规则.cpp").read_bytes()
    except PermissionError:
        return
    raise AssertionError("unrelated UID read source")


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "read":
        read(int(sys.argv[2]))
    else:
        {"prepare": prepare, "checkout": checkout, "update": update, "outsider": outsider}[action]()
    print(json.dumps({"phase": action, "status": "passed"}))
