from __future__ import annotations

import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.modules.agent.infrastructure.generated_runtime_contracts import validate_contract
from app.modules.agent.infrastructure.runtime_protocol import (
    RuntimeProtocolError,
    validate_execution_request,
)
from app.shared.config import Settings, load_settings
from app.shared.database import Database
from app.shared.master_key import load_master_key_settings

from .grant import RuntimeGrantError, RuntimeGrantVerifier
from .invocations import (
    InvocationConflictError,
    PythonInvocationRegistry,
    PythonTerminalLedger,
    TerminalLedgerConflictError,
)
from .model_binding import PythonModelBindingResolver
from .sdk_executor import (
    PROTOCOL_VERSION,
    PYTHON_RUNTIME_KIND,
    PYTHON_RUNTIME_VERSION,
    PythonRuntimeSdkExecutor,
)


@dataclass
class PythonRuntimeDependencies:
    database: Database
    registry: PythonInvocationRegistry
    grant_verifier: RuntimeGrantVerifier
    executor: PythonRuntimeSdkExecutor
    model_probe_token: str
    settings: Settings


def create_app(dependencies: PythonRuntimeDependencies | None = None) -> FastAPI:
    runtime = dependencies or _default_dependencies()
    app = FastAPI(title="Enterprise Python Agent Runtime", version=PYTHON_RUNTIME_VERSION)

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
            "protocol_version": PROTOCOL_VERSION,
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
        is_ready = database_status == "ready" and master_key_status == "ready"
        return JSONResponse(
            status_code=200 if is_ready else 503,
            content={
                "ready": is_ready,
                "database": database_status,
                "master_key": master_key_status,
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
        invocation = runtime.registry.acquire(validated)

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
            validate_contract("CancelRequest", payload)
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

    return app


def _default_dependencies() -> PythonRuntimeDependencies:
    settings = load_master_key_settings(load_settings())
    database = Database(settings.database_dsn)
    binding_resolver = PythonModelBindingResolver(
        database,
        master_key=settings.app_config_master_key,
        allowed_hosts=settings.model_provider_host_allowlist,
    )
    executor = PythonRuntimeSdkExecutor(
        binding_resolver,
        limits=settings.execution,
        mcp_server_url=os.getenv("MCP_TOOL_SERVER_URL", "http://tool-mcp:9103/mcp"),
        fake_provider_mode=_fake_provider_mode(settings.environment),
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
    )


def _bearer(authorization: str) -> str:
    if not authorization.startswith("Bearer "):
        return ""
    return authorization.removeprefix("Bearer ").strip()


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
