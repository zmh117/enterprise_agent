from __future__ import annotations

import json
import time
from dataclasses import replace
from unittest.mock import patch

import httpx
import pytest
from starlette.testclient import TestClient

from app.bootstrap import build_test_container
from app.modules.platform_config.application.database_resource_verifier import (
    GovernedResourceTechnicalVerifier,
    Oracle11gReadonlyAccountProbe,
    OracleProbeFailure,
    oracle_failure,
)
from app.modules.platform_config.infrastructure.oracle_verification import (
    MAX_REQUEST_BYTES,
    ORACLE_VERIFY_PATH,
    OracleDelegationError,
    OracleVerificationHandler,
    OracleVerificationTickets,
    RemoteOracleVerifier,
    draft_binding,
    ticket_digest,
)
from app.services.tool_mcp import create_app, _service_from_container
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container, test_settings as runtime_settings
from backend.tests.test_database_resource_verifier import (
    FakeCursor,
    FakeOracleConnection,
    FakeOracleDriver,
)

MASTER_KEY = "oracle-verification-test-master-key"
ADMIN = "user_local_admin"
PASSWORD = "oracle-verification-password-canary"
NLS_QUERY = (
    "SELECT parameter, value FROM nls_database_parameters "
    "WHERE parameter IN ('NLS_CHARACTERSET', 'NLS_NCHAR_CHARACTERSET')"
)


class OracleDriver(FakeOracleDriver):
    calls = 0

    def connect(self, **kwargs):
        self.calls += 1
        return super().connect(**kwargs)

    def makedsn(self, host, port, **kwargs):
        super().makedsn(host, port, **kwargs)
        return "(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=oracle.test)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=ORCL)))"


@pytest.fixture
def oracle_setup():
    runtime = container()
    platform = runtime.platform_config_service
    resources = platform.governed_resources
    platform.upsert_environment({"code": "oracle_test"}, actor_id=ADMIN)
    platform.create_platform_secret(
        {"code": "oracle_test_password", "value": PASSWORD}, actor_id=ADMIN
    )
    created = resources.create_resource(
        {
            "code": "oracle_test",
            "name": "Oracle 测试",
            "resource_kind": "database",
            "scope_type": "environment",
            "environment_code": "oracle_test",
            "provider_type": "oracle",
            "config": {
                "host": "oracle.test",
                "port": 1521,
                "service_name": "ORCL",
                "username": "reader",
            },
            "secret_refs": {"password_ref": "secret://platform/oracle_test_password"},
        },
        actor_id=ADMIN,
    )
    cursor = FakeCursor(
        {
            "SELECT privilege FROM session_privs": [("CREATE SESSION",), ("SELECT ANY TABLE",)],
            "SELECT privilege FROM user_tab_privs_recd": [("SELECT",)],
            "SELECT granted_role FROM user_role_privs": [("CONNECT",)],
            NLS_QUERY: [("NLS_CHARACTERSET", "AL32UTF8"), ("NLS_NCHAR_CHARACTERSET", "AL16UTF16")],
            "SELECT 1 FROM dual": [(1,)],
        }
    )
    driver = OracleDriver(FakeOracleConnection(cursor))
    verifier = GovernedResourceTechnicalVerifier(
        resolve_secret=platform.secret_provider.resolve,
        allow_oracle_real_verification=True,
        timeout_seconds=5,
        probes={
            "oracle": Oracle11gReadonlyAccountProbe(
                oracledb_module=driver, client_ready=lambda: None
            )
        },
    )
    handler = OracleVerificationHandler(
        resources=resources, verifier=verifier, master_key=MASTER_KEY
    )
    try:
        yield runtime, resources, created, driver, handler
    finally:
        runtime.database.close()


def envelope(created, *, actor=ADMIN, master_key=MASTER_KEY, overrides=None):
    payload = {
        **draft_binding(created["resource"], created["draft"]),
        "actor_id": actor,
        **(overrides or {}),
    }
    return {"ticket": OracleVerificationTickets(master_key).issue(payload)}


def test_api_to_tool_mcp_verifies_and_publishes_current_draft_without_wire_password(oracle_setup):
    runtime, resources, created, driver, handler = oracle_setup
    observed = []
    with TestClient(
        create_app(_service_from_container(runtime), oracle_verification=handler)
    ) as client:

        def dispatch(request):
            request_body = json.loads(request.content)
            request_payload = OracleVerificationTickets(MASTER_KEY).read(request_body["ticket"])
            assert request_payload == {
                **draft_binding(created["resource"], created["draft"]),
                "actor_id": ADMIN,
            }
            observed.append(json.dumps(request_payload))
            result = client.post(ORACLE_VERIFY_PATH, content=request.content)
            observed.append(
                json.dumps(
                    OracleVerificationTickets(MASTER_KEY).read(
                        result.json()["ticket"],
                        response=True,
                    )
                )
            )
            return httpx.Response(result.status_code, content=result.content)

        resources.oracle_verifier = RemoteOracleVerifier(
            base_url="http://tool-mcp:9103",
            allowed_hosts=("tool-mcp",),
            master_key=MASTER_KEY,
            transport=httpx.MockTransport(dispatch),
        )
        verification = resources.verify_draft("oracle_test", actor_id=ADMIN)
        assert verification["status"] == "PASSED"
        assert verification["checks"]["real_connection_verified"] is True
        published = resources.publish_draft("oracle_test", actor_id=ADMIN)
        assert published["status"] == "PUBLISHED"
        assert published["content_hash"] == created["draft"]["content_hash"]
    assert driver.calls == 1
    assert driver.connect_kwargs["password"] == PASSWORD
    assert "(CONNECT_TIMEOUT=5)" in driver.connect_kwargs["dsn"]
    assert "(TRANSPORT_CONNECT_TIMEOUT=5)(RETRY_COUNT=0)" in driver.connect_kwargs["dsn"]
    assert driver.connection.closed and driver.connection.rolled_back
    assert PASSWORD not in "".join(observed)
    assert "password_ref" not in "".join(observed)


@pytest.mark.parametrize(
    "case",
    [
        "unsigned",
        "wrong_key",
        "expired",
        "tampered",
        "actor",
        "resource",
        "draft",
        "provider",
        "extra",
        "disabled",
        "oversized",
    ],
)
def test_internal_endpoint_rejects_invalid_request_before_probe(oracle_setup, case):
    runtime, resources, created, driver, handler = oracle_setup
    payload = envelope(created)
    if case == "unsigned":
        payload = {"ticket": "unsigned"}
    if case == "wrong_key":
        payload = envelope(created, master_key="other-key")
    if case == "expired":
        with patch("time.time", return_value=time.time() - 120):
            payload = envelope(created)
    if case == "tampered":
        parts = payload["ticket"].split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        payload = {"ticket": ".".join(parts)}
    if case == "actor":
        payload = envelope(created, actor="not-an-admin")
    if case == "resource":
        payload = envelope(created, overrides={"resource_id": "other"})
    if case == "draft":
        payload = envelope(created, overrides={"content_hash": "old-hash"})
    if case == "provider":
        payload = envelope(created, overrides={"provider_type": "mysql"})
    if case == "extra":
        payload["config"] = {"host": "arbitrary-target"}
    if case == "disabled":
        resources.set_resource_status(
            "oracle_test", "disabled", expected_revision=1, actor_id=ADMIN
        )
    if case == "oversized":
        payload = {"ticket": "x" * MAX_REQUEST_BYTES}
    with TestClient(
        create_app(_service_from_container(runtime), oracle_verification=handler)
    ) as client:
        response = client.post(ORACLE_VERIFY_PATH, json=payload)
    assert response.status_code in {403, 413}
    assert driver.calls == 0
    assert "ticket" not in response.text
    assert (
        resources.repository.matching_verification(
            resource_id=created["resource"]["id"],
            draft_revision=1,
            content_hash=created["draft"]["content_hash"],
        )
        is None
    )


def test_nonce_replay_and_concurrent_capacity_are_bounded(oracle_setup):
    _, _, created, driver, handler = oracle_setup
    request = envelope(created)
    handler.handle(request)
    with pytest.raises(OracleDelegationError):
        handler.handle(request)
    assert driver.calls == 1
    handler._capacity.acquire()
    handler._capacity.acquire()
    try:
        busy = handler.handle(envelope(created))
        result = OracleVerificationTickets(MASTER_KEY).read(busy["ticket"], response=True)
        assert result["outcome"]["checks"]["error_code"] == "oracle_verification_busy"
        assert driver.calls == 1
    finally:
        handler._capacity.release()
        handler._capacity.release()


@pytest.mark.parametrize(
    "case",
    [
        "unsigned",
        "different_request",
        "incomplete_success",
        "redirect",
        "too_large",
        "timeout",
        "wrong_host",
    ],
)
def test_remote_failure_never_creates_publishable_evidence(oracle_setup, case):
    _, resources, created, driver, handler = oracle_setup
    calls = []

    def dispatch(request):
        calls.append(str(request.url))
        if case == "timeout":
            raise httpx.ReadTimeout("sensitive exception text")
        if case == "redirect":
            return httpx.Response(307, headers={"location": "http://untrusted-target"})
        if case == "too_large":
            return httpx.Response(200, content=b"x" * 20000)
        envelope_in = json.loads(request.content)
        if case == "different_request":
            envelope_in = envelope(created)
        result = handler.handle(envelope_in)
        if case == "unsigned":
            result = {"ticket": "forged"}
        if case == "incomplete_success":
            result = {
                "ticket": OracleVerificationTickets(MASTER_KEY).issue(
                    {
                        "request_digest": ticket_digest(envelope_in["ticket"]),
                        "outcome": {
                            "status": "PASSED",
                            "provider_contract_version": "oracle_11g_v1",
                            "checks": {},
                        },
                    },
                    response=True,
                )
            }
        return httpx.Response(200, json=result)

    resources.oracle_verifier = RemoteOracleVerifier(
        base_url="http://untrusted-target" if case == "wrong_host" else "http://tool-mcp:9103",
        allowed_hosts=("tool-mcp",),
        master_key=MASTER_KEY,
        transport=httpx.MockTransport(dispatch),
    )
    result = resources.verify_draft("oracle_test", actor_id=ADMIN)
    assert result["status"] == "BLOCKED"
    assert len(calls) == (0 if case == "wrong_host" else 1)
    with pytest.raises(NonRetryableExecutionError):
        resources.publish_draft("oracle_test", actor_id=ADMIN)
    assert "sensitive exception text" not in json.dumps(result)


@pytest.mark.parametrize("mutation", ["draft", "identity"])
def test_result_is_discarded_when_draft_or_identity_changes_in_flight(oracle_setup, mutation):
    _, resources, created, _, handler = oracle_setup

    def dispatch(request):
        result = handler.handle(json.loads(request.content))
        if mutation == "identity":
            resources.set_resource_status(
                "oracle_test", "disabled", expected_revision=1, actor_id=ADMIN
            )
        else:
            resources.save_draft(
                "oracle_test",
                {
                    "provider_type": "oracle",
                    "config": {**created["draft"]["config"], "host": "changed.test"},
                    "secret_refs": created["draft"]["secret_refs"],
                },
                expected_revision=1,
                actor_id=ADMIN,
            )
        return httpx.Response(200, json=result)

    resources.oracle_verifier = RemoteOracleVerifier(
        base_url="http://tool-mcp:9103",
        allowed_hosts=("tool-mcp",),
        master_key=MASTER_KEY,
        transport=httpx.MockTransport(dispatch),
    )
    with pytest.raises(NonRetryableExecutionError):
        resources.verify_draft("oracle_test", actor_id=ADMIN)
    assert (
        resources.repository.matching_verification(
            resource_id=created["resource"]["id"],
            draft_revision=1,
            content_hash=created["draft"]["content_hash"],
        )
        is None
    )


@pytest.mark.parametrize("service_name,delegated", [("api-server", True), ("tool-mcp", False)])
def test_bootstrap_only_api_delegates_oracle_verification(service_name, delegated):
    runtime = build_test_container(
        replace(runtime_settings(), environment="test"), seed=True, service_name=service_name
    )
    try:
        assert (
            runtime.platform_config_service.governed_resources.oracle_verifier is not None
        ) is delegated
    finally:
        runtime.database.close()


def test_server_version_and_charset_errors_are_not_mislabeled_as_permissions(oracle_setup):
    _, resources, created, driver, handler = oracle_setup
    driver.connection.version = "19.0.0.0"
    result = handler.handle(envelope(created))
    outcome = OracleVerificationTickets(MASTER_KEY).read(result["ticket"], response=True)["outcome"]
    assert outcome["status"] == "FAILED"
    assert outcome["checks"]["error_code"] == "oracle_version_unsupported"
    assert outcome["checks"]["connection"] is True
    driver.connection.version = "11.2.0.4.0"
    driver.connection._cursor.responses[NLS_QUERY] = [("NLS_CHARACTERSET", "ZHS16GBK")]
    result = handler.handle(envelope(created))
    outcome = OracleVerificationTickets(MASTER_KEY).read(result["ticket"], response=True)["outcome"]
    assert outcome["checks"]["error_code"] == "oracle_charset_unsupported"


def test_missing_client_has_actionable_blocked_outcome_without_connection(monkeypatch):
    from app.modules.mcp_tool_runtime.infrastructure.db import oracle_client

    def missing(_mode):
        raise RuntimeError("unsafe client path detail")

    monkeypatch.setattr(oracle_client, "assert_oracle_client_mode_ready", missing)
    with pytest.raises(OracleProbeFailure) as failure:
        Oracle11gReadonlyAccountProbe().verify({}, timeout_seconds=5)
    assert failure.value.outcome.status == "BLOCKED"
    assert failure.value.outcome.checks["error_code"] == "oracle_client_unavailable"
    assert "unsafe client path detail" not in str(failure.value)


@pytest.mark.parametrize(
    "driver_code,category,status",
    [
        ("ORA-01017", "oracle_authentication_failed", "FAILED"),
        ("ORA-28000", "oracle_authentication_failed", "FAILED"),
        ("ORA-28001", "oracle_authentication_failed", "FAILED"),
        ("ORA-12514", "oracle_service_not_found", "FAILED"),
        ("ORA-12505", "oracle_service_not_found", "FAILED"),
        ("ORA-12541", "oracle_network_failed", "FAILED"),
        ("ORA-12170", "oracle_timeout", "FAILED"),
        ("DPI-1067", "oracle_timeout", "FAILED"),
        ("ORA-01031", "oracle_readonly_denied", "FAILED"),
        ("DPI-1047", "oracle_client_unavailable", "BLOCKED"),
        ("DPI-1072", "oracle_client_unavailable", "BLOCKED"),
        ("ORA-09999", "oracle_probe_failed", "FAILED"),
    ],
)
def test_driver_failure_classification_never_leaks_driver_text(driver_code, category, status):
    failure = oracle_failure(
        RuntimeError(f"{driver_code}: host=private.database password={PASSWORD}")
    )
    assert failure.outcome.status == status
    assert failure.outcome.checks["error_code"] == category
    assert failure.outcome.checks["driver_code"] == driver_code
    assert failure.outcome.checks["connection"] is False
    assert PASSWORD not in str(failure)
    assert "private.database" not in str(failure)


def test_oracle_authentication_failure_is_persisted_and_prevents_publication(oracle_setup):
    _, resources, _, driver, handler = oracle_setup

    def denied(**_kwargs):
        raise RuntimeError(f"ORA-01017: password={PASSWORD}")

    driver.connect = denied
    resources.oracle_verifier = RemoteOracleVerifier(
        base_url="http://tool-mcp:9103",
        allowed_hosts=("tool-mcp",),
        master_key=MASTER_KEY,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=handler.handle(json.loads(request.content)),
            )
        ),
    )
    result = resources.verify_draft("oracle_test", actor_id=ADMIN)
    assert result["status"] == "FAILED"
    assert result["checks"]["error_code"] == "oracle_authentication_failed"
    assert "ORA-01017" in result["safe_error_summary"]
    assert PASSWORD not in json.dumps(result)
    with pytest.raises(NonRetryableExecutionError):
        resources.publish_draft("oracle_test", actor_id=ADMIN)


def test_privileged_oracle_requires_local_policy_at_receiver_and_caller(oracle_setup):
    _, resources, created, driver, handler = oracle_setup
    driver.connection._cursor.responses["SELECT privilege FROM session_privs"] = [
        ("CREATE SESSION",),
        ("UPDATE ANY TABLE",),
    ]
    denied = OracleVerificationTickets(MASTER_KEY).read(
        handler.handle(envelope(created))["ticket"],
        response=True,
    )["outcome"]
    assert denied["status"] == "FAILED"
    assert denied["checks"]["error_code"] == "oracle_readonly_denied"
    local_verifier = GovernedResourceTechnicalVerifier(
        resolve_secret=lambda _: PASSWORD,
        allow_oracle_real_verification=True,
        probes={
            "oracle": Oracle11gReadonlyAccountProbe(
                oracledb_module=driver,
                client_ready=lambda: None,
                allow_privileged_account=True,
            )
        },
    )
    local_handler = OracleVerificationHandler(
        resources=resources,
        verifier=local_verifier,
        master_key=MASTER_KEY,
        allow_privileged_account=True,
    )

    def dispatch(request):
        return httpx.Response(200, json=local_handler.handle(json.loads(request.content)))

    for local in (False, True):
        remote = RemoteOracleVerifier(
            base_url="http://tool-mcp:9103",
            allowed_hosts=("tool-mcp",),
            master_key=MASTER_KEY,
            allow_privileged_account=local,
            transport=httpx.MockTransport(dispatch),
        )
        result = remote.verify(resource=created["resource"], draft=created["draft"], actor_id=ADMIN)
        assert result.status == ("PASSED" if local else "BLOCKED")
