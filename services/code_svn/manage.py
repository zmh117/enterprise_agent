"""本机 SVN 部署操作；工程原样复制，输出仅含数量、版本和摘要。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from typing import Any

STATE = Path("/state")
REPOSITORY = STATE / "repos/mes"
COMPONENTS = ("set_server", "set_web/EBR", "set_web/JTH")


def run(*args: str) -> str:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=1800)
    if result.returncode:
        raise ValueError("svn_deployment_command_failed")
    return result.stdout.decode().strip()


def inventory(root: Path) -> dict[str, Any]:
    rows: list[list[Any]] = []
    size = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            entry = Path(directory) / name
            relative = entry.relative_to(root).as_posix()
            if name == ".svn":
                raise ValueError("svn_reserved_metadata_in_source")
            mode = entry.lstat().st_mode
            value: list[Any]
            if stat.S_ISLNK(mode):
                value = ["link", relative, os.readlink(entry)]
            elif stat.S_ISDIR(mode):
                value = ["directory", relative]
            elif stat.S_ISREG(mode):
                with entry.open("rb") as stream:
                    checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                length = entry.stat().st_size
                size += length
                value = ["file", relative, length, checksum, bool(mode & stat.S_IXUSR)]
            else:
                raise ValueError("svn_unsupported_special_file")
            rows.append(value)
    rows.sort(key=lambda row: row[1])
    return {
        "entries": rows,
        "files": sum(r[0] == "file" for r in rows),
        "bytes": size,
        "digest": hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest(),
    }


def initialize() -> dict[str, Any]:
    tls = STATE / "tls"
    tls.mkdir(parents=True, exist_ok=True)
    certificate, key = tls / "server.crt", tls / "server.key"
    if certificate.exists() != key.exists():
        raise ValueError("svn_tls_incomplete")
    if not certificate.exists():
        run(
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "365",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
            "-subj",
            "/CN=code-svn",
            "-addext",
            "subjectAltName=DNS:code-svn,DNS:localhost,DNS:host.docker.internal,IP:127.0.0.1",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
        )
        key.chmod(0o600)
    if not REPOSITORY.exists():
        REPOSITORY.parent.mkdir(parents=True, exist_ok=True)
        run("svnadmin", "create", str(REPOSITORY))
        run(
            "svn",
            "mkdir",
            REPOSITORY.as_uri() + "/trunk",
            "--non-interactive",
            "-m",
            "初始化 MES 工程主干",
        )
    repository_uuid = run("svnlook", "uuid", str(REPOSITORY))
    auth = STATE / "client/mes-local"
    auth.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(certificate, auth / "server.crt")
    (auth / "servers").write_text(
        "[global]\nssl-authority-files = /run/code-svn-auth/mes-local/server.crt\nstore-passwords = no\nstore-auth-creds = no\n"
    )
    config = STATE / "configuration"
    config.mkdir(exist_ok=True)
    connection = {
        "branch_url": "https://code-svn:8443/repos/mes/trunk",
        "repository_uuid": repository_uuid,
        "branch_path": "/trunk",
        "auth_ref": "mes-local",
    }
    (config / "checkout.json").write_text(
        json.dumps(
            {"mes-local": {**connection, "public_url": "https://localhost:18443/repos/mes/trunk"}},
            indent=2,
        )
    )
    (config / "sources.json").write_text(
        json.dumps(
            {
                "mes-local": {
                    **connection,
                    "components": dict(
                        zip(("backend", "factory_frontend", "group_frontend"), COMPONENTS)
                    ),
                    "externals": {},
                }
            },
            indent=2,
        )
    )
    return {
        "repository_uuid": repository_uuid,
        "revision": int(run("svnlook", "youngest", str(REPOSITORY))),
    }


def import_project(root: Path) -> dict[str, Any]:
    proof = STATE / "import-proof.json"
    if proof.exists() or int(run("svnlook", "youngest", str(REPOSITORY))) != 1:
        raise ValueError("svn_initial_import_already_done")
    with tempfile.TemporaryDirectory(prefix="import-", dir=STATE) as temporary:
        stage = Path(temporary)
        before = {}
        for component in COMPONENTS:
            source = root / component
            if source.is_symlink() or not source.is_dir():
                raise ValueError("svn_source_component_invalid")
            before[component] = inventory(source)
            shutil.copytree(source, stage / component, symlinks=True)
            if inventory(stage / component) != before[component]:
                raise ValueError("svn_source_changed")
        run(
            "svn",
            "import",
            str(stage),
            REPOSITORY.as_uri() + "/trunk",
            "--non-interactive",
            "--no-ignore",
            "--no-auto-props",
            "--force",
            "-m",
            "完整导入后端、工厂端 EBR 与集团端 JTH 工程",
        )
        for component in COMPONENTS:
            if inventory(root / component) != before[component]:
                raise ValueError("svn_source_changed_during_import")
        result: dict[str, Any] = {
            "revision": int(run("svnlook", "youngest", str(REPOSITORY))),
            "components": before,
            "inventory": inventory(stage),
        }
        proof.write_text(json.dumps(result, ensure_ascii=False))
        return {
            "revision": result["revision"],
            **{k: v for k, v in result["inventory"].items() if k != "entries"},
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "import", "serve", "info"])
    parser.add_argument("--source", default="/input")
    args = parser.parse_args()
    try:
        if args.command == "serve":
            os.execvp("apache2", ["apache2", "-f", "/opt/code-svn/apache.conf", "-DFOREGROUND"])
        result = (
            initialize()
            if args.command == "init"
            else import_project(Path(args.source))
            if args.command == "import"
            else {
                "repository_uuid": run("svnlook", "uuid", str(REPOSITORY)),
                "revision": int(run("svnlook", "youngest", str(REPOSITORY))),
            }
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        code = (
            str(exc)
            if isinstance(exc, ValueError) and str(exc).startswith("svn_")
            else "svn_deployment_failed"
        )
        print(json.dumps({"error_code": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
