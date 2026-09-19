from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
import json
import time

from fastapi.testclient import TestClient
import httpx
import jwt
import pytest

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.application.source_service import SourceBindingService
from app.modules.knowledge.infrastructure.ones_verifier import (
    OnesSourceVerifier,
    SOURCE_VERIFICATION_PATH,
)
from backend.tests.test_knowledge_chunks import import_rows
from backend.tests.test_knowledge_import import export_row
from backend.tests.test_ones_mcp_runtime import _fixture, _ProviderResponse
from services.ones_mcp_server.app import create_app
from services.ones_mcp_server.knowledge_verification import (
    OnesSourceVerification,
    OnesWorkItemReferenceService,
    SourceVerificationLimiter,
)


@pytest.fixture
def source_fixture(tmp_path):
    fixture = _fixture(capabilities=("ones_work_item_search", "ones_get_work_item_detail"))
    runtime, service, mock = fixture["runtime"], fixture["service"], fixture["mock"]
    db = runtime.database
    detail, listing = export_row()
    number = mock.config.tasks[0]["number"]
    detail["uuid"] = listing["uuid"] = f"MOCK-ONES-TASK-{number}"
    detail["number"] = listing["number"] = number
    listing["project"]["uuid"] = mock.config.project_uuid
    import_rows(db, tmp_path, [(detail, listing)])
    source_id = db.execute_one('select id from "knowledge.source"')["id"]
    projection = OnesWorkItemReferenceService(
        service.resolver,
        service.credentials,
        service.audit,
        service.credential_refresh,
        graphql=service.graphql,
    )
    calls = []

    def transport(request):
        calls.append(request.url.path)
        assert request.url.host == "ones-mcp" and request.url.port == 9104
        response = client.post(
            request.url.path,
            content=request.read(),
            headers={"authorization": request.headers["authorization"]},
        )
        return httpx.Response(response.status_code, content=response.content)

    verifier = OnesSourceVerifier(
        db,
        fixture["issuer"],
        instance_code="default",
        provider_origin="http://ones-mock:8001",
        transport=httpx.MockTransport(transport),
    )
    source_service = SourceBindingService(
        GovernanceStore(db), runtime.permission_service, runtime.audit_service, verifier
    )
    binding = source_service.create(
        actor_id="user_local_admin",
        source_id=source_id,
        instance_code="default",
        team_id=mock.team_uuid,
        expected_revision=0,
        batch_attested=True,
        attestation_hash="b" * 64,
    )
    endpoint = OnesSourceVerification(
        db,
        runtime.permission_service,
        projection,
        instance_code="default",
        target_hash=verifier.target_hash,
    )
    app = create_app(
        fixture["registry"],
        database=db,
        max_request_bytes=32768,
        audit_retention_days=0,
        source_verification=endpoint,
    )
    with TestClient(app, base_url="http://ones-mcp:9104") as client:
        yield {
            **fixture,
            "binding": binding,
            "source_service": source_service,
            "endpoint": endpoint,
            "client": client,
            "calls": calls,
            "projection": projection,
        }
    db.close()


def verify(fixture):
    return fixture["source_service"].verify(
        actor_id="user_local_admin", binding_id=fixture["binding"]["id"], job_id=fixture["job"].id
    )


def test_real_principal_mock_provider_projection_and_no_body_or_token_persistence(source_fixture):
    f = source_fixture
    binding = verify(f)
    assert binding["state"] == "VERIFIED" and binding["verified_job_id"] == f["job"].id
    assert binding["checked_count"] == 1 and f["calls"] == [SOURCE_VERIFICATION_PATH]
    db = f["runtime"].database
    audit = db.execute(
        "select * from mcp_operation_audit where tool_identifier='ones_get_work_item_detail'"
    )
    assert audit
    stored = json.dumps({"audit": audit, "binding": binding}, default=str)
    assert f["token"] not in stored and f["mock"].token not in stored
    assert "description" not in stored and "related_items" not in stored
    assert "project_id" in stored and "task_id" in stored
    assert not any(tool.tool_identifier.startswith("knowledge") for tool in f["registry"].tools)


@pytest.mark.parametrize(
    "change", ["terminal", "direct", "tool", "identity", "team", "source", "target"]
)
def test_current_job_grant_identity_and_source_fail_closed(source_fixture, change):
    f, db = source_fixture, source_fixture["runtime"].database
    if change == "terminal":
        db.execute("update agent_job set status='SUCCEEDED' where id=?", (f["job"].id,))
    elif change == "direct":
        db.execute("update agent_job set business_application_id=null where id=?", (f["job"].id,))
    elif change == "tool":
        db.execute(
            "delete from rbac_role_application_mcp_tool where tool_identifier='ones_get_work_item_detail'"
        )
    elif change == "identity":
        db.execute(
            "update user_external_identity set tenant_code='other_instance' where id=?",
            (f["identity"]["id"],),
        )
    elif change == "team":
        db.execute('update "knowledge.source_binding" set team_id=?', ("wrong_team",))
    elif change == "source":
        db.execute(
            'update "knowledge.document_revision" set source_project_id=?', ("wrong_project",)
        )
    else:
        f["endpoint"].target_hash = "c" * 64
    with pytest.raises(KnowledgeGovernanceError):
        verify(f)
    assert f["source_service"].store.get("source_binding", f["binding"]["id"])["state"] == "PENDING"


@pytest.mark.parametrize("status", [403, 404, 429, 500])
def test_provider_errors_are_failure_not_verified_or_empty_success(source_fixture, status):
    f = source_fixture

    def fail(request, timeout):
        raise f["provider_http"].status_error(status)

    f["provider_http"]._open_response = fail
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_verification_failed"):
        verify(f)
    assert f["source_service"].store.get("source_binding", f["binding"]["id"])["state"] == "PENDING"


def test_projection_uses_existing_one_time_401_refresh(source_fixture):
    f = source_fixture
    original = f["provider_http"]._open_response
    calls = 0

    def first_unauthorized(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise f["provider_http"].status_error(401)
        return original(request, timeout)

    f["provider_http"]._open_response = first_unauthorized
    assert verify(f)["state"] == "VERIFIED"
    assert calls == 2 and f["login"].calls == 1


def test_second_401_does_not_start_another_refresh(source_fixture):
    f = source_fixture
    calls = 0

    def unauthorized(request, timeout):
        nonlocal calls
        calls += 1
        raise f["provider_http"].status_error(401)

    f["provider_http"]._open_response = unauthorized
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_verification_failed"):
        verify(f)
    assert calls == 2 and f["login"].calls == 1


@pytest.mark.parametrize(
    "case", ["business_error", "missing_task", "wrong_uuid", "wrong_project", "timeout"]
)
def test_provider_200_failure_and_changed_ownership_are_not_source_proof(source_fixture, case):
    f = source_fixture
    original = f["provider_http"]._open_response

    def malformed(request, timeout):
        if case == "timeout":
            raise TimeoutError("synthetic hidden transport error")
        payload = json.loads(original(request, timeout).content)
        if case == "business_error":
            payload = {"errors": [{"message": "synthetic hidden provider error"}]}
        elif case == "missing_task":
            payload = {"data": {"task": None}}
        elif case == "wrong_uuid":
            payload["data"]["task"]["uuid"] = "synthetic_wrong_task"
        else:
            payload["data"]["task"]["project"]["uuid"] = "synthetic_wrong_project"
        return _ProviderResponse(200, json.dumps(payload).encode())

    f["provider_http"]._open_response = malformed
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_verification_failed"):
        verify(f)
    assert f["source_service"].store.get("source_binding", f["binding"]["id"])["state"] == "PENDING"
    stored = json.dumps(
        f["runtime"].database.execute("select * from mcp_operation_audit"), default=str
    )
    assert "synthetic hidden" not in stored


@pytest.mark.parametrize("change", ["grant", "job", "binding"])
def test_final_recheck_rejects_revocation_during_provider_request(source_fixture, change):
    f, db = source_fixture, source_fixture["runtime"].database
    original = f["provider_http"]._open_response

    def revoke(request, timeout):
        result = original(request, timeout)
        if change == "grant":
            db.execute(
                "delete from rbac_role_application_mcp_tool where tool_identifier='ones_get_work_item_detail'"
            )
        elif change == "job":
            db.execute("update agent_job set status='SUCCEEDED' where id=?", (f["job"].id,))
        else:
            f["source_service"].revoke(actor_id="user_local_admin", binding_id=f["binding"]["id"])
        return result

    f["provider_http"]._open_response = revoke
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_verification_failed"):
        verify(f)
    assert (
        f["source_service"].store.get("source_binding", f["binding"]["id"])["verification_hash"]
        is None
    )


@pytest.mark.parametrize("change", ["audience", "scope", "authorization_hash", "actor"])
def test_even_validly_signed_foreign_or_changed_principal_is_rejected(source_fixture, change):
    f = source_fixture
    claims = jwt.decode(f["token"], options={"verify_signature": False})
    if change == "audience":
        claims["aud"] = "knowledge-mcp"
    elif change == "scope":
        claims["scope"] = ["ones_get_work_item_detail"]
    elif change == "authorization_hash":
        claims["authorization_hash"] = "f" * 64
    else:
        claims["sub"] = "synthetic_other_user"
    token = f["issuer"].signing_key.sign(claims)
    response = f["client"].post(
        SOURCE_VERIFICATION_PATH,
        json={"binding_id": f["binding"]["id"]},
        headers={"authorization": "Bearer " + token},
    )
    assert response.status_code == 401
    assert token not in response.text


def test_internal_endpoint_rejects_invalid_and_expired_jwt(source_fixture):
    f = source_fixture
    for token in ("invalid", ""):
        result = f["client"].post(
            SOURCE_VERIFICATION_PATH,
            json={"binding_id": f["binding"]["id"]},
            headers={"authorization": "Bearer " + token},
        )
        assert result.status_code == 401
    f["issuer"]._now = lambda: int(time.time()) - 600
    expired = f["issuer"].issue_business_mcp_for_job(job_id=f["job"].id, server_code="ones-mcp")
    result = f["client"].post(
        SOURCE_VERIFICATION_PATH,
        json={"binding_id": f["binding"]["id"]},
        headers={"authorization": "Bearer " + expired},
    )
    assert result.status_code == 401 and expired not in result.text


@pytest.mark.parametrize("case", ["host", "origin", "large", "duplicate_auth", "extra", "method"])
def test_internal_endpoint_has_its_own_http_security(source_fixture, case):
    f = source_fixture
    headers = {"authorization": "Bearer " + f["token"]}
    value = {"binding_id": f["binding"]["id"]}
    expected = 400
    if case == "host":
        headers["host"] = "other.invalid"
        expected = 403
    elif case == "origin":
        headers["origin"] = "http://other.invalid"
        expected = 403
    elif case == "large":
        value = {"binding_id": "a" * 4100}
        expected = 413
    elif case == "duplicate_auth":
        headers = [("authorization", headers["authorization"]), ("authorization", "Bearer invalid")]
        expected = 401
    elif case == "extra":
        value["team_id"] = "not-client-controlled"
    if case == "method":
        result = f["client"].get(SOURCE_VERIFICATION_PATH, headers=headers)
        expected = 405
    else:
        result = f["client"].post(SOURCE_VERIFICATION_PATH, json=value, headers=headers)
    assert result.status_code == expected


def test_verification_limiter_is_bounded_and_does_not_evict_active_jobs():
    limiter = SourceVerificationLimiter()
    for i in range(4):
        limiter.acquire(str(i))
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_verification_busy"):
        limiter.acquire("fifth")
    limiter.release("0")
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_verification_busy"):
        limiter.acquire("0")
    limiter.acquire("fifth")
