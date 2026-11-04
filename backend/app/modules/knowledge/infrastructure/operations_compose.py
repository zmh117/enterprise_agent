"""仅管理主 Compose 中固定知识服务；任何 API 参数均不能变成命令或路径。"""

import json
import os
from pathlib import Path
import re
import subprocess
from threading import Event
from typing import Any

from app.modules.knowledge.domain.operations import SERVICES, invalid
from app.modules.knowledge.infrastructure.operations_process import run_process
from app.modules.knowledge.infrastructure.operations_repository import OperationsRepository

BUILD_SERVICES = ("knowledge-embedding", "knowledge-reranker", "knowledge-mcp", "knowledge-sync")


class KnowledgeCompose:
    def __init__(self, ops: OperationsRepository, stop: Event):
        self.ops, self.stop = ops, stop
        self.root = Path(os.environ.get("KNOWLEDGE_DEPLOY_ROOT", "/deployment")).resolve()
        self.project = os.environ.get("KNOWLEDGE_COMPOSE_PROJECT", "enterprise_agent")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", self.project):
            raise invalid("knowledge_ops_configuration_invalid")

    def command(self, *arguments: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--project-directory",
            str(self.root),
            "-f",
            str(self.root / "docker-compose.yml"),
            *arguments,
        ]

    def environment(self, version: str | None = None) -> dict[str, str]:
        # 使用与主部署相同的 .env 和固定镜像名；不传播 Compose 文件或远端 daemon 覆盖。
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("COMPOSE_") and key not in {"DOCKER_HOST", "DOCKER_CONTEXT"}
        }
        env["DOCKER_HOST"] = "unix:///var/run/docker.sock"
        return env

    def services(self) -> list[dict[str, str]]:
        result = subprocess.run(
            self.command("ps", "--all", "--format", "json"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=15,
            env=self.environment(),
            cwd=self.root,
        )
        if result.returncode or len(result.stdout) > 256_000:
            raise invalid("knowledge_ops_status_unavailable")
        try:
            raw = result.stdout.decode().strip()
            rows = (
                json.loads(raw)
                if raw.startswith("[")
                else [json.loads(line) for line in raw.splitlines() if line]
            )
            states = {}
            for row in rows:
                service = row.get("Service")
                if service in SERVICES:
                    state, health = row.get("State"), row.get("Health")
                    states[service] = {
                        "name": service,
                        "state": state
                        if state
                        in {
                            "running",
                            "exited",
                            "created",
                            "restarting",
                            "paused",
                            "dead",
                            "removing",
                        }
                        else "unknown",
                        "health": health
                        if health in {"healthy", "unhealthy", "starting"}
                        else "none",
                    }
            return [
                states.get(name, {"name": name, "state": "absent", "health": "none"})
                for name in SERVICES
            ]
        except (ValueError, TypeError, KeyError):
            raise invalid("knowledge_ops_status_unavailable") from None

    def observe(self) -> None:
        snapshot: dict[str, Any]
        try:
            snapshot = {"services": self.services(), "error_code": None}
        except Exception:
            snapshot = {"services": [], "error_code": "knowledge_ops_status_unavailable"}
        previous = self.ops.runtime("controller")["snapshot"].get("services", [])
        for service in snapshot["services"]:
            if service not in previous:
                self.ops.event(
                    None,
                    service["name"],
                    "service_state",
                    {
                        "phase": service["state"],
                        "error_code": "knowledge_service_unhealthy"
                        if service["health"] == "unhealthy"
                        else "none",
                    },
                )
        self.ops.heartbeat("controller", snapshot)

    def _run(
        self,
        operation: dict[str, Any],
        stage: str,
        arguments: list[str],
        *,
        service: str = "controller",
        version: str | None = None,
        timeout: int = 3600,
    ) -> None:
        self.ops.update(operation["id"], stage=stage)
        self.ops.event(operation["id"], service, stage)
        last_step = 0

        def line(raw: str) -> None:
            nonlocal last_step
            # BuildKit 输出只提取数字步骤，不保存命令、路径、仓库地址等文本。
            match = re.match(r"^#(\d+) \[", raw)
            if match and int(match[1]) > last_step:
                last_step = int(match[1])
                self.ops.event(operation["id"], service, "build_step", {"step": last_step})

        result = run_process(
            self.command(*arguments),
            stop=self.stop,
            heartbeat=self.observe,
            line=line,
            env=self.environment(version),
            cwd=str(self.root),
            timeout=timeout,
        )
        if result:
            raise invalid(
                "knowledge_ops_interrupted"
                if self.stop.is_set()
                else "knowledge_ops_command_failed"
            )

    def execute(self, operation: dict[str, Any]) -> None:
        if not (self.root / "docker-compose.yml").is_file():
            raise invalid("knowledge_ops_configuration_invalid")
        kind = operation["kind"]
        if kind == "build":
            version = operation["id"]
            for service in BUILD_SERVICES:
                self._run(
                    operation,
                    "building",
                    ["--progress", "plain", "build", service],
                    service=service,
                    version=version,
                )
            state = self.ops.runtime("deployment")["snapshot"]
            self.ops.heartbeat("deployment", {**state, "built_version": version})
        elif kind == "up":
            self.start(operation)
        elif kind == "stop":
            self._run(operation, "stopping_sync", ["stop", "--timeout", "240", "knowledge-sync"])
            self._run(
                operation,
                "stopping_services",
                [
                    "stop",
                    "--timeout",
                    "240",
                    "knowledge-mcp",
                    "knowledge-embedding-online",
                    "knowledge-reranker",
                    "knowledge-embedding",
                    "knowledge-qdrant",
                ],
            )
            if any(s["state"] not in {"absent", "exited", "created"} for s in self.services()):
                raise invalid("knowledge_ops_stop_incomplete")
        else:
            raise invalid()
        self.observe()

    def start(self, operation: dict[str, Any]) -> None:
        version = self.ops.runtime("deployment")["snapshot"].get("built_version")
        # 主 Compose 也可直接构建/启动；缺镜像由 --no-build 失败关闭，无需伪造网页构建记录。
        # external:true 卷/网络的缺失会令预检失败，不会隐式创建空库。
        self._run(
            operation,
            "preflight",
            ["run", "--rm", "--no-deps", "knowledge-check", "schema"],
            version=version,
        )
        # 应用版本前先收束旧同步，防止模型准备/容器切换期间仍有写者。
        self._run(
            operation,
            "stopping_sync",
            ["stop", "--timeout", "240", "knowledge-sync"],
            version=version,
        )
        for service in ("knowledge-model-prepare", "knowledge-reranker-prepare"):
            self._run(
                operation,
                "models",
                ["run", "--rm", "--no-deps", service],
                service=service,
                version=version,
                timeout=7200,
            )
        self._run(
            operation,
            "starting",
            [
                "up",
                "-d",
                "--no-deps",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "600",
                *SERVICES[:-1],
            ],
            version=version,
        )
        self._run(
            operation,
            "preflight",
            ["run", "--rm", "--no-deps", "knowledge-check", "ready"],
            version=version,
        )
        self._run(
            operation,
            "starting",
            [
                "up",
                "-d",
                "--no-deps",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "120",
                "knowledge-sync",
            ],
            version=version,
        )
        state = self.ops.runtime("deployment")["snapshot"]
        self.ops.heartbeat("deployment", {**state, "running_version": version})

    def reconcile(self, operation: dict[str, Any]) -> None:
        # 重启不重复执行发布操作；停止可由实际观察证明，启动还需版本及依赖证明。
        services = self.services()
        stopped = operation["kind"] == "stop" and all(
            s["state"] in {"absent", "exited", "created"} for s in services
        )
        self.ops.update(
            operation["id"],
            state="SUCCEEDED" if stopped else "INTERRUPTED",
            stage="reconciled" if stopped else "interrupted",
            error_code=None if stopped else "knowledge_ops_interrupted",
        )
        self.ops.event(operation["id"], "controller", "reconciled" if stopped else "interrupted")
