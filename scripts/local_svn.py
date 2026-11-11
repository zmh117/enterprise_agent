#!/usr/bin/env python3
"""本地 SVN 部署/检出；只使用 Docker，宿主机不需要安装 SVN。"""

import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local/code-svn/state"


def main() -> int:
    parser = argparse.ArgumentParser(description="本机 SVN 与 Docker 工程检出")
    parser.add_argument(
        "command", choices=["init", "import", "start", "stop", "info", "browse", "checkout"]
    )
    parser.add_argument("--source-root", type=Path, default=ROOT / "ones知识库/项目代码")
    parser.add_argument(
        "--destination", type=Path, help="独立维护检出的宿主目录；系统检出请使用知识库页面"
    )
    parser.add_argument("--revision", type=int)
    parser.add_argument(
        "--select", action="append", help="相对 SVN 文件或目录，可重复指定；省略为整个仓库"
    )
    args = parser.parse_args()
    env = {**os.environ, "CODE_SVN_IMPORT_ROOT": str(args.source_root.resolve())}
    compose = [
        "docker",
        "compose",
        "-f",
        str(ROOT / "docker-compose.yml"),
        "-f",
        str(ROOT / "docker-compose.code-svn-local.yml"),
    ]
    if args.command in {"init", "import", "info"}:
        if args.command == "init":
            if not STATE.is_dir():
                parser.error("请先运行 docker compose run --build --rm --no-deps code-storage-init")
            subprocess.run([*compose, "build", "code-svn"], check=True, cwd=ROOT, env=env)
        command = [*compose, "run", "--rm", "--no-deps", "code-svn-admin", args.command]
    elif args.command in {"start", "stop"}:
        command = (
            [*compose, "up", "-d", "--no-deps", "--no-build", "code-svn"]
            if args.command == "start"
            else [*compose, "stop", "code-svn"]
        )
    else:
        if args.destination is None:
            parser.error(
                "此命令仅供显式宿主目录维护；系统命名卷检出请使用知识库页面，或指定 --destination"
            )
        destination = args.destination.absolute()
        if destination.exists() or destination.is_symlink():
            if args.command == "checkout":
                parser.error("目标目录已存在，请选择新目录")
        if not destination.parent.is_dir():
            parser.error(
                "目标父目录未初始化，请先用 deployment_check.py init-code-directories 准备"
            )
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "enterprise_agent_knowledge_managed",
            "--read-only",
            "--user",
            "10003:10010",
            "--group-add",
            "10010",
            "--tmpfs",
            "/tmp:rw,size=128m,mode=1777",
        ]
        for source, target, readonly in [
            (STATE / "client", "/run/code-svn-auth", True),
            (STATE / "configuration", "/etc/code-svn", True),
            (ROOT / "backend", "/verify/backend", True),
            (destination.parent.resolve(), "/var/lib/code-svn/checkout", False),
        ]:
            command.extend(
                [
                    "--mount",
                    f"type=bind,src={source},dst={target}" + (",readonly" if readonly else ""),
                ]
            )
        command.extend(
            [
                "-e",
                "PYTHONPATH=/verify/backend:/app",
                "--entrypoint",
                "python",
                "enterprise-agent/knowledge-sync:local",
                "-m",
                "app.cli.code_checkout_local",
                args.command,
                "--folder",
                destination.name,
            ]
        )
        if args.revision is not None:
            command.extend(["--revision", str(args.revision)])
        for chosen in args.select or []:
            command.extend(["--select", chosen])
    return subprocess.run(command, cwd=ROOT, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
