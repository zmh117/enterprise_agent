"""Transient response limits and exact service/operation identities; synthetic payloads only."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.modules.identity.application.principal_jwt import PrincipalJwks
from app.modules.identity.application.service_principal import (
    CodeControlServicePrincipalVerifier,
    ServicePrincipalTokenError,
)
from app.modules.knowledge.api.code_result_endpoint import code_result_app
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_result_buffer import CodeResultBuffer
from app.modules.knowledge.domain.normalization import digest
from app.shared.code_result_contract import CODE_RESULT_PATH
from backend.tests.test_service_principal_identity import _issuer


class Clock:
    def __init__(self):
        self.seconds = 0.0
        self.start = datetime(2030, 1, 1, tzinfo=UTC)

    def tick(self):
        return self.seconds

    def now(self):
        return self.start + timedelta(seconds=self.seconds)


def test_buffer_deadline_replay_capacity_and_copy():
    clock = Clock()
    buffer = CodeResultBuffer(capacity=100, clock=clock.tick, wall_clock=clock.now)
    deadline = clock.now() + timedelta(seconds=200)
    data = {"text": "synthetic code"}
    result_hash = buffer.put("one", 1, data, deadline_at=deadline)
    data["text"] = "mutated caller"
    result = buffer.get("one", 1, expected_hash=result_hash)
    assert result == {"text": "synthetic code"}
    result["text"] = "mutated response"
    assert buffer.get("one", 1, expected_hash=result_hash)["text"] == "synthetic code"
    with pytest.raises(CodeKnowledgeError, match="CODE_HISTORY_RESULT_CHANGED"):
        buffer.put("one", 1, data, deadline_at=deadline)
    with pytest.raises(CodeKnowledgeError, match="CODE_RESULT_BUFFER_FULL"):
        buffer.put("two", 1, {"text": "x" * 90}, deadline_at=deadline)
    clock.seconds = 59
    buffer.put("one", 1, {"text": "synthetic code"}, deadline_at=deadline)
    clock.seconds = 60
    with pytest.raises(CodeKnowledgeError, match="CODE_RESULT_EXPIRED"):
        buffer.get("one", 1, expected_hash=result_hash)
    buffer.put("two", 1, {"text": "small"}, deadline_at=clock.now() + timedelta(seconds=1))
    clock.seconds = 61
    with pytest.raises(CodeKnowledgeError, match="CODE_RESULT_EXPIRED"):
        buffer.get("two", 1, expected_hash=digest({"text": "small"}))


def test_buffer_never_spills_oversize_result_or_restores_after_restart():
    deadline = datetime.now(UTC) + timedelta(seconds=100)
    buffer = CodeResultBuffer()
    with pytest.raises(CodeKnowledgeError, match="CODE_HISTORY_RESPONSE_TOO_LARGE"):
        buffer.put("large", 1, {"text": "x" * (512 * 1024)}, deadline_at=deadline)
    result_hash = buffer.put("one", 1, {"text": "synthetic"}, deadline_at=deadline)
    with pytest.raises(CodeKnowledgeError, match="CODE_RESULT_EXPIRED"):
        CodeResultBuffer().get("one", 1, expected_hash=result_hash)
    buffer.discard("one")
    with pytest.raises(CodeKnowledgeError, match="CODE_RESULT_EXPIRED"):
        buffer.get("one", 1, expected_hash=result_hash)


def fixture_endpoint():
    issuer, audit = _issuer()
    jwks = PrincipalJwks.from_dict({"keys": [issuer.signing_key.public_jwk()]})
    verifier = CodeControlServicePrincipalVerifier(jwks, now=lambda: 1_900_000_000)
    token = issuer.issue_code_control().access_token
    payload = {"diff": "synthetic private diff"}
    buffer = CodeResultBuffer()
    result_hash = buffer.put(
        "operation", 2, payload, deadline_at=datetime.now(UTC) + timedelta(seconds=100)
    )
    calls = []

    def authorize(operation, claim):
        calls.append((operation, claim))
        if (operation, claim) != ("operation", 2):
            raise CodeKnowledgeError("CODE_OPERATION_MISMATCH")
        return {"result_hash": result_hash, "authorization_hash": "valid"}

    app = code_result_app(verifier=verifier, buffer=buffer, authorize=authorize)
    return (
        TestClient(app, base_url="http://knowledge-sync:8096"),
        token,
        calls,
        issuer,
        audit,
        buffer,
    )


def test_endpoint_accepts_only_control_identity_and_current_operation():
    client, token, calls, issuer, audit, buffer = fixture_endpoint()
    response = client.post(
        CODE_RESULT_PATH,
        json={"operation_id": "operation", "claim_version": 2},
        headers={"Authorization": "Bearer " + token},
    )
    assert response.status_code == 200 and response.json() == {"diff": "synthetic private diff"}
    assert response.headers["cache-control"] == "no-store" and len(calls) == 2
    denied = client.post(
        CODE_RESULT_PATH,
        json={"operation_id": "operation", "claim_version": 2},
        headers={"Authorization": "Bearer " + issuer.issue("f" * 48).access_token},
    )
    assert denied.status_code == 403 and "synthetic private diff" not in denied.text
    assert len(calls) == 2
    wrong = client.post(
        CODE_RESULT_PATH,
        json={"operation_id": "operation", "claim_version": 1},
        headers={"Authorization": "Bearer " + token},
    )
    assert wrong.status_code == 403
    assert "synthetic private diff" not in str(audit.events) and token not in str(audit.events)
    buffer.clear()
    expired = client.post(
        CODE_RESULT_PATH,
        json={"operation_id": "operation", "claim_version": 2},
        headers={"Authorization": "Bearer " + token},
    )
    assert expired.status_code == 410


@pytest.mark.parametrize(
    "extra",
    [{"Origin": "http://browser"}, {"Cookie": "session=synthetic"}, {"Host": "localhost:8096"}],
)
def test_endpoint_rejects_browser_or_host_access(extra):
    client, token, calls, *_ = fixture_endpoint()
    result = client.post(
        CODE_RESULT_PATH,
        json={"operation_id": "operation", "claim_version": 2},
        headers={"Authorization": "Bearer " + token, **extra},
    )
    assert result.status_code == 403 and not calls


def test_control_token_expiry_and_role_cannot_be_requested_by_bootstrap():
    issuer, _ = _issuer()
    token = issuer.issue_code_control().access_token
    jwks = PrincipalJwks.from_dict({"keys": [issuer.signing_key.public_jwk()]})
    with pytest.raises(ServicePrincipalTokenError):
        CodeControlServicePrincipalVerifier(jwks, now=lambda: 1_900_000_301).verify(token)
    with pytest.raises(ServicePrincipalTokenError):
        issuer.issue("code-knowledge-control-plane")


def test_endpoint_rechecks_authorization_and_buffer_expiry_before_return():
    issuer, _ = _issuer()
    verifier = CodeControlServicePrincipalVerifier(
        PrincipalJwks.from_dict({"keys": [issuer.signing_key.public_jwk()]}),
        now=lambda: 1_900_000_000,
    )
    for change in ("authorization", "expiry"):
        clock = Clock()
        buffer = CodeResultBuffer(clock=clock.tick, wall_clock=clock.now)
        result_hash = buffer.put(
            "one",
            1,
            {"text": "synthetic private payload"},
            deadline_at=clock.now() + timedelta(seconds=20),
        )
        calls = []

        def authorize(operation, claim):
            calls.append((operation, claim))
            if len(calls) == 2 and change == "expiry":
                clock.seconds = 21
            return {
                "result_hash": result_hash,
                "identity": len(calls) if change == "authorization" else 1,
            }

        app = code_result_app(verifier=verifier, buffer=buffer, authorize=authorize)
        with TestClient(app, base_url="http://knowledge-sync:8096") as client:
            result = client.post(
                CODE_RESULT_PATH,
                headers={"Authorization": "Bearer " + issuer.issue_code_control().access_token},
                json={"operation_id": "one", "claim_version": 1},
            )
        assert result.status_code == (403 if change == "authorization" else 410)
        assert "synthetic private payload" not in result.text


def test_result_client_checks_digest_limits_and_does_not_follow_redirects():
    import httpx
    from app.modules.knowledge.infrastructure.code_result_client import CodeResultClient
    from app.shared.code_result_contract import CODE_RESULT_URL

    payload = {"text": "synthetic response"}
    for mode, expected_error in (
        ("success", None),
        ("changed", "CODE_HISTORY_RESULT_CHANGED"),
        ("redirect", "CODE_RESULT_DENIED"),
        ("oversize", "CODE_HISTORY_RESPONSE_TOO_LARGE"),
        ("expired", "CODE_RESULT_EXPIRED"),
    ):
        calls = []

        def respond(request):
            calls.append(request)
            assert str(request.url) == CODE_RESULT_URL
            assert request.headers["authorization"] == "Bearer synthetic-service-token"
            if mode == "redirect":
                return httpx.Response(307, headers={"location": "https://untrusted.invalid"})
            if mode == "oversize":
                return httpx.Response(200, content=b"x" * (512 * 1024 + 1))
            if mode == "expired":
                return httpx.Response(410, json={"error_code": "CODE_RESULT_EXPIRED"})
            return httpx.Response(200, json=payload)

        client = CodeResultClient(
            lambda: "synthetic-service-token", transport=httpx.MockTransport(respond)
        )
        if expected_error:
            with pytest.raises(CodeKnowledgeError, match=expected_error):
                client.read(
                    "one",
                    1,
                    result_hash="f" * 64 if mode == "changed" else digest(payload),
                    remaining=2,
                )
        else:
            assert client.read("one", 1, result_hash=digest(payload), remaining=2) == payload
        assert len(calls) == 1


def test_directory_preview_has_separate_bound_without_relaxing_raw_results():
    import httpx
    from app.modules.knowledge.infrastructure.code_result_client import CodeResultClient

    payload = {
        "revision": 2,
        "repository_uuid": "synthetic-repository",
        "directories": ["set_server"],
        "files": [f"set_server/{i:05d}-" + "a" * 80 + ".cpp" for i in range(7000)],
        "registration_hash": "a" * 64,
    }
    deadline = datetime.now(UTC) + timedelta(seconds=100)
    buffer = CodeResultBuffer()
    with pytest.raises(CodeKnowledgeError, match="CODE_HISTORY_RESPONSE_TOO_LARGE"):
        buffer.put("raw", 1, payload, deadline_at=deadline)
    result_hash = buffer.put("preview", 1, payload, deadline_at=deadline, is_directory_preview=True)
    client = CodeResultClient(
        lambda: "synthetic-token",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)),
    )
    assert (
        client.read("preview", 1, result_hash=result_hash, remaining=10, is_directory_preview=True)
        == payload
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_HISTORY_RESPONSE_TOO_LARGE"):
        client.read("preview", 1, result_hash=result_hash, remaining=10)
    with pytest.raises(CodeKnowledgeError, match="CODE_RESULT_INVALID"):
        buffer.put(
            "wrong", 1, {"diff": "synthetic"}, deadline_at=deadline, is_directory_preview=True
        )
    payload["files"] *= 4
    with pytest.raises(CodeKnowledgeError, match="CODE_HISTORY_RESPONSE_TOO_LARGE"):
        buffer.put("huge", 1, payload, deadline_at=deadline, is_directory_preview=True)
