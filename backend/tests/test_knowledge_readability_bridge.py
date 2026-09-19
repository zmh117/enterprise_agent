"""平台双身份桥合成验收；没有真实用户、凭据或 ONES 数据。"""

import json
import time
from dataclasses import replace
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import jwt
import pytest

from app.modules.identity.application.principal_jwt import (
    PrincipalJwks,
    PrincipalTokenIssuer,
    PrincipalTokenVerifier,
)
from app.modules.identity.application.service_principal import (
    KnowledgeServicePrincipalVerifier,
    ServicePrincipalTokenIssuer,
    ServicePrincipalTokenError,
)
from app.modules.knowledge.api.readability_controller import build_knowledge_readability_router
from app.modules.knowledge.application.retrieval_budget import DEADLINE_HEADER
from app.modules.knowledge.application.readability_bridge import KnowledgeReadabilityBridge
from app.modules.knowledge.infrastructure.readability_bridge import PlatformOnesReadabilityGateway
from app.modules.knowledge.application.readability import BRIDGE_PATH, READABILITY_PATH
from app.shared import mcp_server_policy
from app.shared.config import ServicePrincipalSettings
from backend.tests.test_knowledge_job_access import knowledge_contract as knowledge_contract_fixture
from backend.tests.test_knowledge_readability import readable_fixture as readable_fixture_impl
from backend.tests.test_ones_mcp_runtime import _ProviderResponse
from backend.tests.test_service_principal_identity import _issuer

knowledge_contract = knowledge_contract_fixture
readable_fixture = readable_fixture_impl


@pytest.fixture
def bridge_fixture(readable_fixture):
    f = readable_fixture
    runtime, endpoint = f["runtime"], f["endpoint"]
    key = f["issuer"].signing_key
    public_keys = PrincipalJwks.from_dict(key.public_jwks())
    credentials = {
        "file-worker": "f" * 48,
        "file-processing-worker": "p" * 48,
        "delivery-worker": "d" * 48,
        "knowledge-mcp": "k" * 48,
    }
    service_issuer = ServicePrincipalTokenIssuer(
        signing_key=key,
        bootstrap_credentials=credentials,
        audit_service=runtime.audit_service,
    )
    issuer = PrincipalTokenIssuer(
        runtime.database,
        runtime.mcp_tool_snapshot_service,
        runtime.business_authorization_service,
        key,
        runtime.audit_service,
        knowledge_job_gate=endpoint.gate,
        server_policies=mcp_server_policy.MCP_SERVER_POLICIES,
    )
    knowledge_token = issuer.issue_business_mcp_for_job(
        job_id=f["job"].id, server_code="knowledge-mcp"
    )
    exchanges = []

    def transport(request):
        assert str(request.url) == "http://ones-mcp:9104" + READABILITY_PATH
        assert request.method == "POST"
        token = request.headers["authorization"][7:]
        claims = f["service"].authenticate(token)
        assert set(claims["scope"]) == {
            "mcp:ones-mcp:ones_work_item_search:invoke",
            "mcp:ones-mcp:ones_get_work_item_detail:invoke",
        }
        assert claims["job_id"] == f["job"].id and token != knowledge_token
        exchanges.append({"job_id": claims["job_id"], "scope": claims["scope"]})
        response = f["client"].post(
            READABILITY_PATH,
            content=request.content,
            headers={
                "authorization": request.headers["authorization"],
                "content-type": "application/json",
                DEADLINE_HEADER: request.headers[DEADLINE_HEADER],
            },
        )
        return httpx.Response(response.status_code, content=response.content)

    gateway = PlatformOnesReadabilityGateway(
        KnowledgeServicePrincipalVerifier(public_keys),
        PrincipalTokenVerifier(
            public_keys,
            expected_audience="knowledge-mcp",
            server_policies=mcp_server_policy.MCP_SERVER_POLICIES,
        ),
        issuer,
        endpoint.gate,
        instance_code=endpoint.resources.instance_code,
        transport=httpx.MockTransport(transport),
    )
    bridge = KnowledgeReadabilityBridge(gateway, endpoint.resources, runtime.audit_service)
    app = FastAPI()
    app.state.container = SimpleNamespace(knowledge_readability_bridge=bridge)
    app.include_router(build_knowledge_readability_router())
    with TestClient(app, base_url="http://api-server:8000") as client:
        yield {
            **f,
            "bridge_client": client,
            "bridge": bridge,
            "key": key,
            "knowledge_token": knowledge_token,
            "service_token": service_issuer.issue(credentials["knowledge-mcp"]).access_token,
            "file_token": service_issuer.issue(credentials["file-worker"]).access_token,
            "exchanges": exchanges,
            "transport": transport,
        }


def post(f, body=None, headers=None, **kwargs):
    return f["bridge_client"].post(
        BRIDGE_PATH,
        json=f["body"] if body is None else body,
        headers=headers if headers is not None else auth(f),
        **kwargs,
    )


def auth(f):
    return {
        "authorization": "Bearer " + f["service_token"],
        "x-knowledge-principal": "Bearer " + f["knowledge_token"],
    }


def test_fixed_full_scope_bridge_has_no_body_or_token_in_output_audit(bridge_fixture):
    f = bridge_fixture
    response = post(f)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert f["calls"] == ["POST"] and len(f["exchanges"]) == 1
    assert all(item["readable"] for item in response.json()["items"])
    safe = response.text + json.dumps(
        f["runtime"].database.execute("select * from audit_event"), default=str
    )
    for forbidden in (
        f["knowledge_token"],
        f["service_token"],
        f["mock"].token,
        "合成正文",
        "description",
        "access_token",
    ):
        assert forbidden not in safe


@pytest.mark.parametrize(
    "kind",
    [
        "missing_service",
        "missing_user",
        "file",
        "ones",
        "swapped",
        "duplicate",
        "origin",
        "cookie",
        "host",
        "blank",
    ],
)
def test_both_independent_identities_required_before_ones(bridge_fixture, kind):
    f = bridge_fixture
    headers = auth(f)
    if kind == "missing_service":
        del headers["authorization"]
    elif kind == "missing_user":
        del headers["x-knowledge-principal"]
    elif kind == "file":
        headers["authorization"] = "Bearer " + f["file_token"]
    elif kind == "ones":
        headers["x-knowledge-principal"] = "Bearer " + f["token"]
    elif kind == "swapped":
        headers["authorization"], headers["x-knowledge-principal"] = (
            headers["x-knowledge-principal"],
            headers["authorization"],
        )
    elif kind == "duplicate":
        headers = [*headers.items(), ("authorization", headers["authorization"])]
    elif kind == "blank":
        headers["authorization"] = "Bearer "
    else:
        headers[kind] = "untrusted"
    assert post(f, headers=headers).status_code == 401
    assert not f["calls"] and not f["exchanges"]


@pytest.mark.parametrize(
    "field",
    [
        "actor",
        "server",
        "scope",
        "team_id",
        "operation",
        "url",
        "work_item_uuid",
        "provider_credentials",
    ],
)
def test_no_caller_override_or_general_proxy(bridge_fixture, field):
    f = bridge_fixture
    assert post(f, {**f["body"], field: "untrusted"}).status_code == 400
    assert not f["exchanges"]


@pytest.mark.parametrize(
    "mutation", ["knowledge_base_id", "resource_revision_id", "index_id", "chunk_ids"]
)
def test_candidate_membership_checked_before_principal_issuance(bridge_fixture, mutation):
    f = bridge_fixture
    sql = "select id from audit_event where event_type='principal.jwt.issued' order by id"
    before = f["runtime"].database.execute(sql)
    body = {**f["body"], mutation: ["other-chunk"] if mutation == "chunk_ids" else "other-id"}
    assert post(f, body).status_code == 503
    assert not f["exchanges"]
    assert f["runtime"].database.execute(sql) == before


@pytest.mark.parametrize(
    "failure", [401, 429, 500, "timeout", "business", "uuid", "project", "schema"]
)
def test_full_bridge_provider_failures_never_become_empty_results(bridge_fixture, failure):
    f = bridge_fixture
    original = f["provider_http"]._open_response

    def fail(request, timeout):
        if isinstance(failure, int):
            raise f["provider_http"].status_error(failure)
        if failure == "timeout":
            raise TimeoutError("private-sentinel")
        data = json.loads(original(request, timeout).content)
        if failure == "business":
            data = {"code": 403, "message": "private-sentinel"}
        else:
            task = data["data"]["tasks"][0]
            if failure == "uuid":
                task["uuid"] = "other-task"
            elif failure == "project":
                task["project"]["uuid"] = "other-project"
            else:
                task.pop("uuid")
        return _ProviderResponse(200, json.dumps(data).encode())

    f["provider_http"]._open_response = fail
    response = post(f)
    assert response.status_code == 503 and "items" not in response.json()
    assert "private-sentinel" not in response.text
    if failure == 401:
        assert f["login"].calls == 1


@pytest.mark.parametrize("status", [403, 404])
def test_no_allowed_result_cache_across_calls(bridge_fixture, status):
    f = bridge_fixture
    assert post(f).status_code == 200

    def deny(*args):
        raise f["provider_http"].status_error(status)

    f["provider_http"]._open_response = deny
    response = post(f)
    assert response.status_code == 200 and len(f["exchanges"]) == 2
    assert all(
        item == {"chunk_id": item["chunk_id"], "readable": False}
        for item in response.json()["items"]
    )


def test_bridge_preserves_one_personal_401_refresh(bridge_fixture):
    f = bridge_fixture
    original = f["provider_http"]._open_response
    attempts = 0

    def first_401(request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise f["provider_http"].status_error(401)
        return original(request, timeout)

    f["provider_http"]._open_response = first_401
    assert post(f).status_code == 200
    assert attempts == 2 and f["login"].calls == 1


@pytest.mark.parametrize(
    "mutation", ["scope_subset", "scope_extra", "actor", "job", "publication", "hash"]
)
def test_knowledge_principal_exact_job_and_scope(bridge_fixture, mutation):
    f = bridge_fixture
    claims = jwt.decode(f["knowledge_token"], options={"verify_signature": False})
    if mutation == "scope_subset":
        claims["scope"] = ["mcp:knowledge-mcp:knowledge_search:invoke"]
    elif mutation == "scope_extra":
        claims["scope"].append("mcp:knowledge-mcp:undeclared:invoke")
    else:
        field = {
            "actor": "sub",
            "job": "job_id",
            "publication": "application_publication_id",
            "hash": "authorization_hash",
        }[mutation]
        claims[field] = "a" * 64 if mutation == "hash" else "another"
    headers = {**auth(f), "x-knowledge-principal": "Bearer " + f["key"].sign(claims)}
    assert post(f, headers=headers).status_code == 401
    assert not f["exchanges"]


def test_incomplete_http_lengths_and_streamed_bound(bridge_fixture):
    f = bridge_fixture
    headers = {**auth(f), "content-type": "application/json"}
    client = f["bridge_client"]
    assert (
        client.post(BRIDGE_PATH, content=iter([b" " * 8192, b" "]), headers=headers).status_code
        == 413
    )
    assert (
        client.post(
            BRIDGE_PATH, content=b"{}", headers={**headers, "content-length": "-1"}
        ).status_code
        == 400
    )
    duplicated = [*headers.items(), ("content-length", "2"), ("content-length", "3")]
    assert client.post(BRIDGE_PATH, content=b"{}", headers=duplicated).status_code == 400
    assert not f["exchanges"]


@pytest.mark.parametrize(
    "mutation",
    [
        "kb",
        "detail",
        "member",
        "job",
        "source",
        "membership",
        "project",
        "identity",
        "instance",
        "default_team",
        "credential",
    ],
)
@pytest.mark.parametrize("during", [False, True])
def test_platform_rechecks_persistent_facts_even_after_successful_ones(
    bridge_fixture, mutation, during
):
    f = bridge_fixture
    statements = {
        "kb": "delete from rbac_role_application_knowledge_base",
        "detail": "delete from rbac_role_application_mcp_tool where tool_identifier='ones_get_work_item_detail'",
        "member": "update rbac_user_role set status='disabled'",
        "job": "update agent_job set status='SUCCEEDED'",
        "source": "update \"knowledge.retrieval_resource\" set status='disabled'",
        "membership": "update \"knowledge.knowledge_base_document\" set state='removed'",
        "project": "update \"knowledge.document_revision\" set source_project_id='other-project'",
        "identity": "update user_external_identity set status='disabled' where provider='ones'",
        "instance": "update user_external_identity set tenant_code='other-instance' where provider='ones'",
        "default_team": 'update user_external_identity set metadata_json=\'{"team_uuids":["other-team"],"default_team_id":"other-team"}\' where provider=\'ones\'',
        "credential": "update external_identity_credential set status='DISABLED' where provider='ones'",
    }

    def transport(request):
        response = f["transport"](request)
        f["runtime"].database.execute(statements[mutation])
        return response

    if during:
        f["bridge"].gateway._transport = httpx.MockTransport(transport)
    else:
        f["runtime"].database.execute(statements[mutation])
    response = post(f)
    assert response.status_code in {401, 503} and "items" not in response.json()
    if not during:
        assert not f["exchanges"]


@pytest.mark.parametrize(
    "corruption",
    [
        "job",
        "actor",
        "extra",
        "missing",
        "uuid",
        "number",
        "denied_body",
        "duplicate",
        "huge",
        "redirect",
        "timeout",
    ],
)
def test_bridge_strict_bounded_projection_never_relays_untrusted_response(
    bridge_fixture, corruption
):
    f = bridge_fixture

    def transport(request):
        if corruption == "huge":
            return httpx.Response(200, content=b" " * (64 * 1024 + 1))
        if corruption == "redirect":
            return httpx.Response(302, headers={"location": "https://untrusted.invalid"})
        if corruption == "timeout":
            raise httpx.ReadTimeout("private-sentinel")
        result = f["transport"](request).json()
        if corruption in {"job", "actor"}:
            result[corruption + "_id"] = "other"
        elif corruption == "extra":
            result["body"] = "private-sentinel"
        elif corruption == "missing":
            result["items"].pop()
        elif corruption == "uuid":
            result["items"][0]["task_id"] = "other"
        elif corruption == "number":
            result["items"][0]["number"] = True
        elif corruption == "denied_body":
            result["items"][0]["readable"] = False
        elif corruption == "duplicate":
            return httpx.Response(200, content=b'{"items":[],"items":[]}')
        return httpx.Response(200, json=result)

    f["bridge"].gateway._transport = httpx.MockTransport(transport)
    response = post(f)
    assert response.status_code == 503 and "items" not in response.json()
    assert "private-sentinel" not in response.text


def test_bounded_http_request_and_concurrency(bridge_fixture):
    f = bridge_fixture
    headers = {**auth(f), "content-type": "application/json"}
    assert (
        f["bridge_client"].post(BRIDGE_PATH, content=" " * 8193, headers=headers).status_code == 413
    )
    assert (
        f["bridge_client"].post(BRIDGE_PATH, content='{"a":1,"a":2}', headers=headers).status_code
        == 400
    )
    assert post(f, params={"url": "other"}).status_code == 401
    for _ in range(4):
        assert f["bridge"]._slots.acquire(blocking=False)
    try:
        assert post(f).status_code == 429
    finally:
        for _ in range(4):
            f["bridge"]._slots.release()
    assert not f["exchanges"]


@pytest.mark.parametrize("identity", ["service", "knowledge"])
def test_principal_expiry_during_http_discards_success(bridge_fixture, identity):
    f = bridge_fixture
    principal = (
        f["bridge"].gateway.service_identity
        if identity == "service"
        else f["bridge"].gateway.principal
    )

    def transport(request):
        response = f["transport"](request)
        principal._now = lambda: int(time.time()) + 600
        return response

    f["bridge"].gateway._transport = httpx.MockTransport(transport)
    assert post(f).status_code == 503


@pytest.mark.parametrize(
    "field,value",
    [
        ("aud", "ones-mcp"),
        ("aud", ["knowledge-readability-bridge"]),
        ("sub", "file-worker"),
        ("azp", "agent-runtime"),
        ("iss", "enterprise-agent-identity"),
        ("scope", []),
        ("scope", ["internal:file-service:delivery:read"]),
        ("authorization_hash", "a" * 64),
        ("exp", 1),
        ("iat", True),
        ("extra", "unsafe"),
    ],
)
def test_service_identity_exact_claims(field, value):
    base, audit = _issuer(now=int(time.time()))
    issuer = ServicePrincipalTokenIssuer(
        signing_key=base.signing_key,
        audit_service=audit,
        bootstrap_credentials={**base._bootstrap_credentials, "knowledge-mcp": "k" * 48},
    )
    token = issuer.issue("k" * 48).access_token
    verifier = KnowledgeServicePrincipalVerifier(
        PrincipalJwks.from_dict(base.signing_key.public_jwks())
    )
    verifier.verify(token)
    claims = jwt.decode(token, options={"verify_signature": False})
    claims[field] = value
    with pytest.raises(ServicePrincipalTokenError):
        verifier.verify(base.signing_key.sign(claims))


def test_knowledge_identity_is_optional_and_isolated():
    issuer, _ = _issuer()
    with pytest.raises(ServicePrincipalTokenError):
        issuer.issue("k" * 48)
    assert not ServicePrincipalSettings().knowledge_bootstrap_token_file
    with pytest.raises(ValueError):
        ServicePrincipalSettings(knowledge_bootstrap_token_file="synthetic-file")
    with pytest.raises(ValueError):
        ServicePrincipalTokenIssuer(
            signing_key=issuer.signing_key,
            audit_service=issuer.audit_service,
            bootstrap_credentials={**issuer._bootstrap_credentials, "knowledge-mcp": "f" * 48},
        )
    app = FastAPI()
    app.state.container = SimpleNamespace()
    app.include_router(build_knowledge_readability_router())
    with TestClient(app, base_url="http://api-server:8000") as client:
        assert client.post(BRIDGE_PATH).status_code == 503


def test_bootstrap_file_is_loaded_only_when_explicitly_configured(monkeypatch):
    from app.modules.identity.application import service_principal as module

    base, audit = _issuer(now=int(time.time()))
    seen = []

    def read(path, *, label):
        seen.append(path)
        return path * 48

    monkeypatch.setattr(module, "_read_bootstrap_credential", read)
    monkeypatch.setattr(
        module.PrincipalSigningKey, "from_file", lambda *args, **kwargs: base.signing_key
    )
    kwargs = dict(
        signing_private_key_file="synthetic-key",
        file_worker_bootstrap_file="f",
        file_processing_worker_bootstrap_file="p",
        delivery_worker_bootstrap_file="d",
        audit_service=audit,
        environment="test",
    )
    ServicePrincipalTokenIssuer.from_files(**kwargs)
    assert seen == ["f", "p", "d"]
    seen.clear()
    issuer = ServicePrincipalTokenIssuer.from_files(**kwargs, knowledge_bootstrap_file="k")
    assert seen == ["f", "p", "d", "k"]
    verifier = KnowledgeServicePrincipalVerifier(
        PrincipalJwks.from_dict(base.signing_key.public_jwks())
    )
    verifier.verify(issuer.issue("k" * 48).access_token)


def test_api_bootstrap_wires_bridge_only_with_optional_identity(bridge_fixture, monkeypatch):
    from app.bootstrap import build_test_container
    from app.modules.identity.application import principal_jwt, service_principal

    f = bridge_fixture
    assert f["runtime"].knowledge_readability_bridge is None
    monkeypatch.setattr(principal_jwt, "MCP_SERVER_POLICIES", mcp_server_policy.MCP_SERVER_POLICIES)
    monkeypatch.setattr(
        principal_jwt.PrincipalSigningKey, "from_file", lambda *args, **kwargs: f["key"]
    )
    monkeypatch.setattr(
        service_principal, "_read_bootstrap_credential", lambda path, **kwargs: path * 48
    )
    settings = replace(
        f["runtime"].settings,
        principal_jwt=replace(
            f["runtime"].settings.principal_jwt, signing_private_key_file="synthetic-key"
        ),
        service_principal=ServicePrincipalSettings(
            enabled=True,
            file_worker_bootstrap_token_file="f",
            file_processing_worker_bootstrap_token_file="p",
            delivery_worker_bootstrap_token_file="d",
            knowledge_bootstrap_token_file="k",
        ),
        ones_mcp=replace(f["runtime"].settings.ones_mcp, provider_base_url="http://ones-mock:8001"),
    )
    runtime = build_test_container(settings, service_name="api-server")
    try:
        assert runtime.knowledge_readability_bridge is not None
        assert runtime.knowledge_readability_bridge.gateway.issuer is runtime.principal_token_issuer
        token = runtime.service_principal_token_issuer.issue("k" * 48).access_token
        runtime.knowledge_readability_bridge.gateway.service_identity.verify(token)
        assert (
            runtime.knowledge_readability_bridge.gateway.principal.expected_audience
            == "knowledge-mcp"
        )
    finally:
        runtime.database.close()
