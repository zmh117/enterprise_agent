from __future__ import annotations

import hmac
import json
import logging
import os
import shutil
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.modules.agent.infrastructure.generated_runtime_contracts import validate_contract
from app.modules.agent.infrastructure.runtime_protocol import (
    CURRENT_RUNTIME_PROTOCOL_VERSION,
    RuntimeProtocolError,
    SUPPORTED_RUNTIME_PROTOCOL_VERSIONS,
    validate_execution_request,
    validate_runtime_contract,
)
from app.shared.config import Settings, load_settings
from app.shared.database import Database
from app.shared.master_key import load_master_key_settings

from .grant import RuntimeGrantError, RuntimeGrantVerifier
from .invocations import (
    InvocationSecretContext,
    InvocationConflictError,
    PythonInvocationRegistry,
    PythonTerminalLedger,
    TerminalLedgerConflictError,
)
from .model_binding import PythonModelBindingResolver
from .job_sandbox import JobSandboxLimits, JobSandboxManager
from .executor import (
    PROTOCOL_VERSION,
    PYTHON_RUNTIME_KIND,
    PYTHON_RUNTIME_VERSION,
    PythonRuntimeExecutor,
)


@dataclass
class PythonRuntimeDependencies:
    database: Database
    registry: PythonInvocationRegistry
    grant_verifier: RuntimeGrantVerifier
    executor: PythonRuntimeExecutor
    model_probe_token: str
    settings: Settings
    sandbox_manager: JobSandboxManager | None = None


def create_app(dependencies: PythonRuntimeDependencies | None = None) -> FastAPI:
    runtime = dependencies or _default_dependencies()
    cleanup_stop = threading.Event()
    cleanup_thread: threading.Thread | None = None

    def cleanup_residuals() -> None:
        if runtime.sandbox_manager is None:
            return

        def is_running(job_id: str) -> bool:
            row = runtime.database.execute_one(
                "select status from agent_job where id = ?",
                (job_id,),
            )
            return row is not None and str(row.get("status") or "") == "RUNNING"

        try:
            runtime.sandbox_manager.cleanup_residuals(is_running)
        except Exception:
            logging.getLogger(__name__).warning(
                "Python Runtime sandbox residual scan failed safely"
            )

    def start_sandbox_cleanup() -> None:
        nonlocal cleanup_thread
        if runtime.sandbox_manager is None:
            return
        cleanup_residuals()
        interval = max(
            30,
            min(
                3600,
                int(os.getenv("PYTHON_AGENT_RUNTIME_SANDBOX_CLEANUP_INTERVAL_SECONDS", "300")),
            ),
        )

        def periodic() -> None:
            while not cleanup_stop.wait(interval):
                cleanup_residuals()

        cleanup_thread = threading.Thread(
            target=periodic,
            name="python-runtime-sandbox-cleaner",
            daemon=True,
        )
        cleanup_thread.start()

    def stop_sandbox_cleanup() -> None:
        cleanup_stop.set()
        if cleanup_thread is not None:
            cleanup_thread.join(timeout=2)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> Any:
        start_sandbox_cleanup()
        try:
            yield
        finally:
            stop_sandbox_cleanup()

    app = FastAPI(
        title="Enterprise Python Agent Runtime",
        version=PYTHON_RUNTIME_VERSION,
        lifespan=lifespan,
    )

    @app.exception_handler(RuntimeGrantError)
    async def runtime_grant_error(
        _request: Request,
        exc: RuntimeGrantError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"code": exc.code, "message": "Runtime 服务身份校验失败"},
        )

    @app.exception_handler(InvocationConflictError)
    @app.exception_handler(TerminalLedgerConflictError)
    async def invocation_conflict(
        _request: Request,
        exc: Exception,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "code": getattr(exc, "code", "runtime_invocation_conflict"),
                "message": "Invocation 与既有请求冲突",
            },
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/version")
    def version() -> dict[str, str]:
        return {
            "runtime": PYTHON_RUNTIME_KIND,
            "runtime_version": PYTHON_RUNTIME_VERSION,
            "protocol_version": CURRENT_RUNTIME_PROTOCOL_VERSION,
            "supported_protocol_versions": ",".join(
                SUPPORTED_RUNTIME_PROTOCOL_VERSIONS
            ),
            "sdk_version": runtime.executor.sdk_version,
            "cli_version": runtime.executor.cli_version,
        }

    @app.get("/ready")
    def ready() -> JSONResponse:
        database_status = "ready"
        try:
            runtime.database.execute_one("select 1 as ready")
        except Exception:
            database_status = "unavailable"
        master_key_status = (
            "ready" if bool(runtime.settings.app_config_master_key) else "unavailable"
        )
        sandbox_status = "unavailable"
        sandbox_capacity_bytes = 0
        sandbox_max_file_bytes = 0
        sandbox_max_files = 0
        if runtime.sandbox_manager is not None:
            limits = runtime.sandbox_manager.limits
            sandbox_capacity_bytes = limits.capacity_bytes
            sandbox_max_file_bytes = limits.max_file_bytes
            sandbox_max_files = limits.max_files
            try:
                runtime.sandbox_manager.root.mkdir(parents=True, exist_ok=True, mode=0o700)
                available = shutil.disk_usage(runtime.sandbox_manager.root).free
                if (
                    limits.capacity_bytes >= 64 * 1024 * 1024
                    and available >= 64 * 1024 * 1024
                ):
                    sandbox_status = "ready"
            except OSError:
                sandbox_status = "unavailable"
        is_ready = (
            database_status == "ready"
            and master_key_status == "ready"
            and sandbox_status == "ready"
        )
        return JSONResponse(
            status_code=200 if is_ready else 503,
            content={
                "ready": is_ready,
                "database": database_status,
                "master_key": master_key_status,
                "sandbox": sandbox_status,
                "sandbox_capacity_bytes": sandbox_capacity_bytes,
                "sandbox_max_file_bytes": sandbox_max_file_bytes,
                "sandbox_max_files": sandbox_max_files,
            },
        )

    @app.post("/internal/v1/executions")
    async def execute(
        request: Request,
        authorization: str = Header(default=""),
    ) -> StreamingResponse:
        raw = await request.body()
        try:
            payload = json.loads(raw)
            validated = dict(validate_execution_request(payload, encoded_bytes=len(raw)))
        except (UnicodeError, ValueError, TypeError, RuntimeProtocolError) as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "runtime_request_invalid", "message": "Runtime 请求校验失败"},
            ) from exc
        if validated["runtime_kind"] != PYTHON_RUNTIME_KIND:
            raise HTTPException(
                status_code=400,
                detail={"code": "runtime_kind_mismatch", "message": "Runtime 请求目标不匹配"},
            )
        runtime.grant_verifier.verify(_bearer(authorization), validated)
        invocation = runtime.registry.acquire(
            validated,
            _principal_secret_context(request, validated),
        )

        def stream() -> Any:
            for event in invocation.stream():
                yield json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.post("/internal/v1/executions/{invocation_id}/cancel")
    async def cancel(
        invocation_id: str,
        request: Request,
        authorization: str = Header(default=""),
    ) -> dict[str, str]:
        invocation = runtime.registry.get(invocation_id)
        if invocation is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "runtime_invocation_not_found", "message": "未找到执行"},
            )
        payload = await request.json()
        try:
            validate_runtime_contract("CancelRequest", payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Runtime 取消请求无效") from exc
        if (
            payload["invocation_id"] != invocation.request["invocation_id"]
            or payload["request_digest"] != invocation.request["request_digest"]
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "runtime_request_digest_mismatch", "message": "取消请求冲突"},
            )
        runtime.grant_verifier.verify(_bearer(authorization), invocation.request)
        cancelled = invocation.cancel()
        return {"status": "cancelled" if cancelled else "already_terminal"}

    @app.get("/internal/v1/executions/{invocation_id}/terminal")
    def terminal(
        invocation_id: str,
        authorization: str = Header(default=""),
    ) -> dict[str, Any]:
        invocation = runtime.registry.get(invocation_id)
        if invocation is None:
            raise HTTPException(status_code=404, detail="未找到执行")
        runtime.grant_verifier.verify(_bearer(authorization), invocation.request)
        result = invocation.terminal()
        if result is None:
            raise HTTPException(status_code=409, detail="执行尚未结束")
        return result

    @app.post("/internal/v1/model-probes")
    async def model_probe(
        request: Request,
        authorization: str = Header(default=""),
    ) -> dict[str, Any]:
        if not _constant_token(runtime.model_probe_token, _bearer(authorization)):
            raise HTTPException(status_code=401, detail="模型探针服务身份校验失败")
        payload = await request.json()
        try:
            validate_contract("ModelProbeRequest", payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="模型探针请求无效") from exc
        if payload["runtime_kind"] != PYTHON_RUNTIME_KIND:
            raise HTTPException(status_code=400, detail="Runtime 请求目标不匹配")
        started = time.monotonic()
        try:
            response = runtime.executor.probe(dict(payload))
        except Exception as exc:
            response = {
                "protocol_version": PROTOCOL_VERSION,
                "runtime_kind": PYTHON_RUNTIME_KIND,
                "probe_id": payload["probe_id"],
                "success": False,
                "connection_revision_id": payload["model_connection"]["revision_id"],
                "provider_host": "unavailable",
                "model": "unavailable",
                "runtime_version": PYTHON_RUNTIME_VERSION,
                "sdk_version": runtime.executor.sdk_version,
                "duration_ms": min(30_000, int((time.monotonic() - started) * 1000)),
                "failure": {
                    "code": str(getattr(exc, "error_code", "model_connection_test_failed")),
                    "safe_message": str(getattr(exc, "safe_message", "模型连接测试失败")),
                },
            }
        validate_contract("ModelProbeResponse", response)
        return response

    @app.post("/internal/v1/model-probes/draft")
    async def draft_model_probe(
        request: Request,
        authorization: str = Header(default=""),
    ) -> dict[str, Any]:
        if not _constant_token(runtime.model_probe_token, _bearer(authorization)):
            raise HTTPException(status_code=401, detail="模型探针服务身份校验失败")
        payload = await request.json()
        try:
            validate_contract("DraftModelProbeRequest", payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="草稿模型探针请求无效") from exc
        if payload["runtime_kind"] != PYTHON_RUNTIME_KIND:
            raise HTTPException(status_code=400, detail="Runtime 请求目标不匹配")
        started = time.monotonic()
        try:
            response = runtime.executor.probe_draft(dict(payload))
        except Exception as exc:
            response = {
                "protocol_version": PROTOCOL_VERSION,
                "runtime_kind": PYTHON_RUNTIME_KIND,
                "probe_id": payload["probe_id"],
                "success": False,
                "connection_revision_id": f"draft-{payload['probe_id']}",
                "provider_host": "unavailable",
                "model": "unavailable",
                "runtime_version": PYTHON_RUNTIME_VERSION,
                "sdk_version": runtime.executor.sdk_version,
                "duration_ms": min(30_000, int((time.monotonic() - started) * 1000)),
                "failure": {
                    "code": str(getattr(exc, "error_code", "model_connection_test_failed")),
                    "safe_message": str(getattr(exc, "safe_message", "模型连接测试失败")),
                },
            }
        validate_contract("ModelProbeResponse", response)
        return response

    return app


def _default_dependencies() -> PythonRuntimeDependencies:
    settings = load_master_key_settings(load_settings())
    database = Database(settings.database_dsn)
    binding_resolver = PythonModelBindingResolver(
        database,
        master_key=settings.app_config_master_key,
        allowed_hosts=settings.model_provider_host_allowlist,
    )
    sandbox_root = Path(
        os.getenv(
            "PYTHON_AGENT_RUNTIME_SANDBOX_ROOT",
            "/tmp/enterprise-agent-python-runtime-sandboxes",
        )
    )
    if not sandbox_root.is_absolute():
        raise ValueError("PYTHON_AGENT_RUNTIME_SANDBOX_ROOT must be absolute")
    sandbox_manager = JobSandboxManager(
        sandbox_root,
        limits=JobSandboxLimits(
            capacity_bytes=int(
                os.getenv("PYTHON_AGENT_RUNTIME_SANDBOX_CAPACITY_BYTES", str(224 * 1024 * 1024))
            ),
            max_files=int(os.getenv("PYTHON_AGENT_RUNTIME_SANDBOX_MAX_FILES", "40")),
            max_file_bytes=int(
                os.getenv("PYTHON_AGENT_RUNTIME_SANDBOX_MAX_FILE_BYTES", str(15 * 1024 * 1024))
            ),
        ),
    )
    if sandbox_manager.limits.capacity_bytes < 64 * 1024 * 1024:
        raise ValueError("Python Runtime sandbox capacity must be at least 64 MiB")
    executor = PythonRuntimeExecutor(
        binding_resolver,
        limits=settings.execution,
        mcp_server_url=os.getenv("MCP_TOOL_SERVER_URL", "http://tool-mcp:9103/mcp"),
        ones_mcp_server_url=os.getenv(
            "ONES_MCP_SERVER_URL",
            "http://ones-mcp:9104/mcp",
        ),
        file_mcp_server_url=os.getenv(
            "FILE_MCP_SERVER_URL",
            "http://file-service:9105/mcp",
        ),
        fake_provider_mode=_fake_provider_mode(settings.environment),
        sandbox_manager=sandbox_manager,
    )
    ledger = PythonTerminalLedger(
        database,
        ttl_seconds=int(os.getenv("PYTHON_AGENT_RUNTIME_LEDGER_TTL_SECONDS", "3600")),
    )
    probe_token_path = Path(settings.agent_runtime.model_probe_auth_token_file)
    model_probe_token = probe_token_path.read_text(encoding="utf-8").strip()
    return PythonRuntimeDependencies(
        database=database,
        registry=PythonInvocationRegistry(executor, ledger),
        grant_verifier=RuntimeGrantVerifier.from_file(
            os.getenv("RUNTIME_GRANT_PUBLIC_KEY_FILE", "")
        ),
        executor=executor,
        model_probe_token=model_probe_token,
        settings=settings,
        sandbox_manager=sandbox_manager,
    )


def _bearer(authorization: str) -> str:
    if not authorization.startswith("Bearer "):
        return ""
    return authorization.removeprefix("Bearer ").strip()


def _principal_secret_context(
    request: Request,
    payload: dict[str, Any],
) -> InvocationSecretContext:
    values = request.headers.getlist("x-mcp-principal-token")
    file_values = request.headers.getlist("x-file-principal-token")
    requires_principal = any(
        str(server.get("server_code") or "") == "ones-mcp"
        for server in payload.get("mcp_servers") or []
        if isinstance(server, dict)
    )
    requires_file_principal = any(
        str(server.get("server_code") or "") == "file-service"
        for server in payload.get("mcp_servers") or []
        if isinstance(server, dict)
    )
    if len(values) > 1 or len(file_values) > 1:
        raise HTTPException(
            status_code=401,
            detail={"code": "runtime_principal_token_invalid", "message": "平台身份凭证无效"},
        )
    token = values[0].strip() if values else ""
    file_token = file_values[0].strip() if file_values else ""
    if (requires_principal and not token) or (requires_file_principal and not file_token):
        raise HTTPException(
            status_code=401,
            detail={"code": "runtime_principal_token_missing", "message": "缺少平台身份凭证"},
        )
    if (not requires_principal and token) or (not requires_file_principal and file_token):
        raise HTTPException(
            status_code=401,
            detail={"code": "runtime_principal_token_unexpected", "message": "平台身份凭证无效"},
        )
    if (
        len(token) > 8192
        or len(file_token) > 8192
        or "\r" in token
        or "\n" in token
        or "\r" in file_token
        or "\n" in file_token
    ):
        raise HTTPException(
            status_code=401,
            detail={"code": "runtime_principal_token_invalid", "message": "平台身份凭证无效"},
        )
    return InvocationSecretContext(
        principal_token=token,
        file_principal_token=file_token,
    )


def _constant_token(expected: str, provided: str) -> bool:
    return bool(
        len(expected) >= 32
        and len(expected) == len(provided)
        and hmac.compare_digest(expected, provided)
    )


def _fake_provider_mode(environment: str) -> bool:
    mode = os.getenv("AGENT_RUNTIME_TEST_PROVIDER_MODE", "disabled").strip().lower()
    if mode not in {"disabled", "deterministic"}:
        raise ValueError("AGENT_RUNTIME_TEST_PROVIDER_MODE must be disabled or deterministic")
    if mode == "deterministic" and environment not in {"test", "testing"}:
        raise ValueError("deterministic fake provider is restricted to APP_ENV=test/testing")
    return mode == "deterministic"
