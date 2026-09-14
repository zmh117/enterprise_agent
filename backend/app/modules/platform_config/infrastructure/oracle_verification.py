"""Private, draft-bound Oracle verification. Never part of the Agent tool catalog."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import uuid
from dataclasses import asdict
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt

from app.modules.platform_config.application.governed_resources import (
    GovernedResourceService,
    ResourceTechnicalVerifier,
    ResourceVerificationOutcome,
)
from app.modules.platform_config.application.resource_scope_bindings import (
    assert_resource_scope_bindings_publishable,
)
from app.shared.database import assert_external_io_allowed

ORACLE_VERIFY_PATH = "/internal/resources/oracle/verify"
MAX_REQUEST_BYTES = 4096
MAX_RESPONSE_BYTES = 16384
_ISSUER = "enterprise-agent:oracle-verification:v1"
_REQUEST_AUDIENCE = "tool-mcp:oracle-verification"
_RESPONSE_AUDIENCE = "api-server:oracle-verification"


class OracleDelegationError(ValueError):
    pass


def blocked(code: str, message: str) -> ResourceVerificationOutcome:
    return ResourceVerificationOutcome(
        status="BLOCKED",
        provider_contract_version="oracle_11g_v1",
        checks={"error_code": code, "real_connection_verified": False},
        safe_error_summary=message,
    )


class OracleVerificationTickets:
    def __init__(self, master_key: str) -> None:
        if not master_key:
            raise OracleDelegationError("Oracle verification signing key is unavailable")
        self._key = hmac.new(
            master_key.encode(),
            b"enterprise-agent:oracle-verification:v1",
            hashlib.sha256,
        ).digest()
        self._consumed: dict[str, int] = {}
        self._lock = threading.Lock()

    def issue(self, payload: dict[str, Any], *, response: bool = False) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "iss": _ISSUER,
                "aud": _RESPONSE_AUDIENCE if response else _REQUEST_AUDIENCE,
                "iat": now,
                "exp": now + 60,
                "jti": uuid.uuid4().hex,
                "payload": payload,
            },
            self._key,
            algorithm="HS256",
        )

    def read(self, ticket: str, *, response: bool = False) -> dict[str, Any]:
        try:
            if not isinstance(ticket, str) or len(ticket) > MAX_RESPONSE_BYTES:
                raise ValueError("Invalid ticket size")
            claims = jwt.decode(
                ticket,
                self._key,
                algorithms=["HS256"],
                issuer=_ISSUER,
                audience=_RESPONSE_AUDIENCE if response else _REQUEST_AUDIENCE,
                options={"require": ["iss", "aud", "iat", "exp", "jti", "payload"]},
            )
            if not 0 < claims["exp"] - claims["iat"] <= 60:
                raise ValueError("Invalid ticket lifetime")
            if not isinstance(claims["payload"], dict) or not isinstance(claims["jti"], str):
                raise ValueError("Invalid ticket payload")
            if not response:
                with self._lock:
                    now = int(time.time())
                    self._consumed = {k: v for k, v in self._consumed.items() if v > now}
                    if claims["jti"] in self._consumed or len(self._consumed) >= 4096:
                        raise ValueError("Ticket replay or capacity limit")
                    self._consumed[claims["jti"]] = claims["exp"]
            return dict(claims["payload"])
        except Exception as exc:
            raise OracleDelegationError("Oracle verification ticket rejected") from exc


def draft_binding(resource: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "resource_id": resource["id"],
        "resource_code": resource["code"],
        "draft_id": draft["id"],
        "draft_revision": draft["draft_revision"],
        "content_hash": draft["content_hash"],
        "provider_type": draft["provider_type"],
        "provider_contract_version": "oracle_11g_v1",
    }


def ticket_digest(ticket: str) -> str:
    return hashlib.sha256(ticket.encode()).hexdigest()


class RemoteOracleVerifier:
    def __init__(
        self,
        *,
        base_url: str,
        allowed_hosts: tuple[str, ...],
        master_key: str,
        allow_privileged_account: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._allowed_hosts = allowed_hosts
        self._master_key = master_key
        self._allow_privileged_account = allow_privileged_account
        self._transport = transport

    def verify(
        self,
        *,
        resource: dict[str, Any],
        draft: dict[str, Any],
        actor_id: str,
    ) -> ResourceVerificationOutcome:
        try:
            endpoint = urlsplit(self._base_url)
            if (
                endpoint.scheme not in {"http", "https"}
                or endpoint.hostname not in self._allowed_hosts
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
                or endpoint.path not in {"", "/"}
            ):
                raise OracleDelegationError("Oracle verification target is not allowed")
            tickets = OracleVerificationTickets(self._master_key)
            request = {**draft_binding(resource, draft), "actor_id": actor_id}
            ticket = tickets.issue(request)
            if len(json.dumps({"ticket": ticket}).encode()) > MAX_REQUEST_BYTES:
                raise OracleDelegationError("Oracle verification request is too large")
            assert_external_io_allowed("resource_verify.oracle_delegate")
            with httpx.Client(
                timeout=httpx.Timeout(90, connect=5),
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as client:
                with client.stream(
                    "POST",
                    self._base_url.rstrip("/") + ORACLE_VERIFY_PATH,
                    json={"ticket": ticket},
                ) as response:
                    if response.status_code != 200:
                        raise OracleDelegationError("Oracle verification service rejected request")
                    raw = bytearray()
                    for chunk in response.iter_bytes(chunk_size=4096):
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE_BYTES:
                            raise OracleDelegationError("Oracle verification response is too large")
            envelope = json.loads(raw)
            result = tickets.read(envelope["ticket"], response=True)
            if result.get("request_digest") != ticket_digest(ticket):
                raise OracleDelegationError("Oracle verification response binding mismatch")
            outcome = ResourceVerificationOutcome(**result["outcome"])
            validate_outcome(outcome, allow_privileged_account=self._allow_privileged_account)
            return outcome
        except httpx.TimeoutException:
            return blocked(
                "oracle_verification_timeout",
                "Oracle 技术验证超时，请检查 tool-mcp 和数据库网络后重试",
            )
        except Exception:
            return blocked(
                "oracle_verification_unavailable",
                "Oracle 验证服务不可用或委派校验失败，请检查 tool-mcp、内部地址和平台主密钥是否一致",
            )


def validate_outcome(
    outcome: ResourceVerificationOutcome, *, allow_privileged_account: bool
) -> None:
    if (
        outcome.status not in {"PASSED", "FAILED", "BLOCKED"}
        or outcome.provider_contract_version != "oracle_11g_v1"
        or not isinstance(outcome.checks, dict)
        or not isinstance(outcome.safe_error_summary, str)
        or len(outcome.safe_error_summary) > 512
    ):
        raise OracleDelegationError("Invalid Oracle outcome")
    allowed_checks = {
        "connection",
        "real_connection_verified",
        "available",
        "readonly_account",
        "readonly_transaction",
        "privileged_account_allowed",
        "server_version",
        "character_sets",
        "client_mode",
        "client_version",
        "client_architecture",
        "error_code",
        "driver_code",
    }
    if set(outcome.checks) - allowed_checks or len(json.dumps(outcome.checks)) > 4096:
        raise OracleDelegationError("Oracle check fields are not allowed")
    if outcome.status == "PASSED":
        checks = outcome.checks
        if not (
            checks.get("connection") is True
            and checks.get("real_connection_verified") is True
            and checks.get("readonly_transaction") is True
            and checks.get("client_mode") == "thick"
            and str(checks.get("client_version", "")).startswith("19")
            and str(checks.get("server_version", "")).startswith("11.2.0.4")
            and checks.get("character_sets")
            == {
                "NLS_CHARACTERSET": "AL32UTF8",
                "NLS_NCHAR_CHARACTERSET": "AL16UTF16",
            }
            and (
                checks.get("readonly_account") is True
                or (allow_privileged_account and checks.get("privileged_account_allowed") is True)
            )
        ):
            raise OracleDelegationError("Oracle success evidence is incomplete")


class OracleVerificationHandler:
    def __init__(
        self,
        *,
        resources: GovernedResourceService,
        verifier: ResourceTechnicalVerifier,
        master_key: str,
        allow_privileged_account: bool = False,
    ) -> None:
        self._resources = resources
        self._verifier = verifier
        self._tickets = OracleVerificationTickets(master_key)
        self._allow_privileged_account = allow_privileged_account
        self._capacity = threading.BoundedSemaphore(2)

    def handle(self, envelope: dict[str, Any]) -> dict[str, str]:
        if set(envelope) != {"ticket"}:
            raise OracleDelegationError("Oracle verification accepts only a ticket")
        ticket = envelope["ticket"]
        request = self._tickets.read(ticket)
        if not self._capacity.acquire(blocking=False):
            return self._response(
                ticket, blocked("oracle_verification_busy", "Oracle 技术验证繁忙，请稍后重试")
            )
        try:
            resources = self._resources
            resources.require_admin(str(request.get("actor_id") or ""))
            resource = resources._resource(str(request.get("resource_code") or ""))
            resources._require_identity_enabled(resource)
            draft = resources.repository.get_draft(str(resource["id"]))
            expected = {**draft_binding(resource, draft), "actor_id": request["actor_id"]}
            if request != expected or draft["provider_type"] != "oracle":
                raise OracleDelegationError("Oracle draft identity changed")
            if (
                resources.provider_contracts.require("oracle").contract_version
                != request["provider_contract_version"]
            ):
                raise OracleDelegationError("Oracle provider contract changed")
            assert_resource_scope_bindings_publishable(
                draft.get("scope_bindings"),
                resource_kind=str(resource["resource_kind"]),
                scope_type=str(resource["scope_type"]),
            )
            outcome = self._verifier.verify(resource=resource, draft=draft)
            validate_outcome(outcome, allow_privileged_account=self._allow_privileged_account)
            return self._response(ticket, outcome)
        finally:
            self._capacity.release()

    def _response(self, ticket: str, outcome: ResourceVerificationOutcome) -> dict[str, str]:
        return {
            "ticket": self._tickets.issue(
                {"request_digest": ticket_digest(ticket), "outcome": asdict(outcome)},
                response=True,
            )
        }
