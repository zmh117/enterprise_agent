"""内部投影的合成 Provider 验收；不代表真实 ONES、部署或模型边界已验收。"""

from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.domain.chunking import DEFAULT_PROFILE
from app.modules.knowledge.application.source_service import SourceBindingService
from app.modules.knowledge.infrastructure.job_access import KnowledgeJobGate, KNOWLEDGE_TOOLS
from app.modules.knowledge.infrastructure.ones_verifier import ones_target_hash
from app.modules.knowledge.application.resource_service import (
    KnowledgeResourceReader,
    KnowledgeResourceService,
)
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.infrastructure.storage import insert
from app.shared import ones_io_budget as budget
from app.shared.exceptions import AppError
from backend.tests.test_knowledge_chunks import import_rows
from backend.tests.test_knowledge_governance import SyntheticVerifier
from backend.tests.test_knowledge_import import export_row
from backend.tests.test_knowledge_authorization import add_base
from backend.tests.test_knowledge_job_access import knowledge_contract as knowledge_contract_fixture
from backend.tests.test_knowledge_vectors import SyntheticEmbedding, SyntheticQdrant
from backend.tests.test_ones_mcp_runtime import _fixture, _ProviderResponse
from backend.tests.support.ones_provider import MockOnesSettings
from services.ones_mcp_server.app import create_app
from services.ones_mcp_server.knowledge_readability import (
    OnesKnowledgeReadability,
    READABILITY_PATH,
)
from services.ones_mcp_server.knowledge_verification import OnesWorkItemReferenceService

knowledge_contract = knowledge_contract_fixture


@pytest.fixture
def readable_fixture(knowledge_contract, tmp_path, request):
    mock = MockOnesSettings()
    options = getattr(request, "param", 1)
    base_count = options.get("bases", 1) if isinstance(options, dict) else options
    document_count = options.get("documents", 1) if isinstance(options, dict) else 1

    def configure(c, selection):
        detail, listing = export_row()
        number = mock.config.tasks[0]["number"]
        detail["uuid"] = listing["uuid"] = f"MOCK-ONES-TASK-{number}"
        detail["number"] = listing["number"] = number
        listing["project"]["uuid"] = mock.config.project_uuid
        rows = [(detail, listing)]
        for ordinal in range(2, document_count + 1):
            extra_detail, extra_listing = export_row(ordinal)
            extra_detail["uuid"] = extra_listing["uuid"] = f"synthetic-task-{ordinal}"
            extra_listing["project"]["uuid"] = mock.config.project_uuid
            rows.append((extra_detail, extra_listing))
        import_rows(c.database, tmp_path, rows)
        memberships = c.database.execute('select * from "knowledge.knowledge_base_document"')
        for number in range(1, base_count):
            key = f"kb-page-{number:04d}"
            add_base(c, key)
            for membership in memberships:
                insert(
                    c.database, "knowledge_base_document", {**membership, "knowledge_base_id": key}
                )
        c.database.execute(
            "insert into rbac_role_application_knowledge_base(application_access_id,knowledge_base_id,created_at) "
            'select a.id,k.id,a.created_at from rbac_role_application_access a cross join "knowledge.knowledge_base" k where a.application_id=?',
            (selection["application_id"],),
        )

    f = _fixture(
        capabilities=("ones_work_item_search", "ones_get_work_item_detail", *KNOWLEDGE_TOOLS),
        before_job=configure,
        current_agent_envelope=True,
    )
    c, service = f["runtime"], f["service"]
    db = c.database
    chunks = ChunkService(ChunkRepository(db)).run(
        knowledge_base_code="synthetic_base", expected_count=document_count, commit=True
    )["counts"]["chunks"]
    vector = VectorService(VectorRepository(db), SyntheticEmbedding(), SyntheticQdrant())
    snapshot = vector.repository.snapshot(
        vector.repository.scope("synthetic_base"),
        DEFAULT_PROFILE.fingerprint,
        document_count,
        chunks,
    )
    vector.build("synthetic-v1", snapshot)
    verifier = SyntheticVerifier()
    verifier.instance_code = "default"
    verifier.target_hash = ones_target_hash("default", "http://ones-mock:8001")
    sources = SourceBindingService(
        GovernanceStore(db), c.permission_service, c.audit_service, verifier
    )
    sources.verifier = None
    assert sources.catalog()["bindings"] == []
    resources = KnowledgeResourceService(
        sources,
        VectorRepository(sources.store.database),
        embedding=vector.embedding,
        qdrant=vector.qdrant,
    )
    resource = resources.create(
        actor_id="user_local_admin",
        knowledge_base_id=snapshot["knowledge_base_id"],
        code="synthetic",
        name="合成知识库",
    )
    index = vector.repository.get("synthetic-v1")
    draft = resources.save_draft(
        actor_id="user_local_admin",
        resource_id=resource["id"],
        expected_revision=resource["revision"],
        index_id=index["id"],
    )
    checked = resources.verify_draft(
        actor_id="user_local_admin", resource_id=resource["id"], expected_revision=draft["revision"]
    )
    published = resources.publish(
        actor_id="user_local_admin",
        resource_id=resource["id"],
        expected_revision=checked["revision"],
    )
    for number in range(1, base_count):
        key = f"kb-page-{number:04d}"
        extra_vector = VectorService(VectorRepository(db), SyntheticEmbedding(), SyntheticQdrant())
        extra_vector.build(
            key,
            extra_vector.repository.snapshot(
                key, DEFAULT_PROFILE.fingerprint, document_count, chunks
            ),
        )
        extra_resource = KnowledgeResourceService(
            sources,
            VectorRepository(sources.store.database),
            embedding=extra_vector.embedding,
            qdrant=extra_vector.qdrant,
        )
        created = extra_resource.create(
            actor_id="user_local_admin", knowledge_base_id=key, code=key, name=key
        )
        draft = extra_resource.save_draft(
            actor_id="user_local_admin",
            resource_id=created["id"],
            expected_revision=created["revision"],
            index_id=extra_vector.repository.get(key)["id"],
        )
        checked = extra_resource.verify_draft(
            actor_id="user_local_admin",
            resource_id=created["id"],
            expected_revision=draft["revision"],
        )
        extra_resource.publish(
            actor_id="user_local_admin",
            resource_id=created["id"],
            expected_revision=checked["revision"],
        )
    if base_count == 0:
        db.execute("update \"knowledge.retrieval_resource\" set status='disabled'")
    projection = OnesWorkItemReferenceService(
        service.resolver,
        service.credentials,
        service.audit,
        service.credential_refresh,
        graphql=service.graphql,
    )
    endpoint = OnesKnowledgeReadability(
        KnowledgeJobGate(db, c.mcp_tool_snapshot_service, c.business_authorization_service),
        KnowledgeResourceReader(
            GovernanceStore(db),
            VectorRepository(db),
        ),
        projection,
        instance_code="default",
    )
    body = {
        "knowledge_base_id": snapshot["knowledge_base_id"],
        "resource_revision_id": published["published"]["id"],
        "index_id": index["id"],
        "chunk_ids": [
            row["id"] for row in db.execute('select id from "knowledge.document_chunk" order by id')
        ],
    }
    calls = []
    original = f["provider_http"]._open_response

    def transport(request, timeout):
        calls.append(request.get_method())
        return original(request, timeout)

    f["provider_http"]._open_response = transport
    app = create_app(
        f["registry"],
        database=db,
        max_request_bytes=32768,
        audit_retention_days=0,
        knowledge_readability=endpoint,
    )
    with TestClient(app, base_url="http://ones-mcp:9104") as client:
        yield {
            **f,
            "client": client,
            "endpoint": endpoint,
            "body": body,
            "calls": calls,
            "vector": vector,
            "resources": resources,
        }
    db.close()


def post(f, body=None, **kwargs):
    return f["client"].post(
        READABILITY_PATH,
        json=body if body is not None else f["body"],
        headers={"authorization": "Bearer " + f["token"]},
        **kwargs,
    )


def test_reference_only_deduplicated_personal_read_with_no_admin_bypass(readable_fixture):
    f = readable_fixture
    f["runtime"].database.execute(
        "delete from rbac_user_role where user_id='user_local_admin' and role_id in (select id from rbac_role where code='platform-admin')"
    )
    response = post(f)
    assert response.status_code == 200
    assert f["calls"] == ["POST"]  # 多个块只检查一次工作项。
    assert all(item["readable"] for item in response.json()["items"])
    content = response.text + json.dumps(
        f["runtime"].database.execute("select * from mcp_operation_audit"), default=str
    )
    for forbidden in (f["token"], f["mock"].token, "合成正文", "description", "related_items"):
        assert forbidden not in content
    assert not any(tool.tool_identifier.startswith("knowledge") for tool in f["registry"].tools)


@pytest.mark.parametrize("status", [403, 404])
def test_denied_and_missing_are_false_and_no_positive_cross_call_cache(readable_fixture, status):
    f = readable_fixture
    assert post(f).status_code == 200

    def denied(*args):
        raise f["provider_http"].status_error(status)

    f["provider_http"]._open_response = denied
    response = post(f)
    assert response.status_code == 200
    assert all(
        set(item) == {"chunk_id", "readable"} and item["readable"] is False
        for item in response.json()["items"]
    )


@pytest.mark.parametrize(
    "failure", [401, 429, 500, "timeout", "business", "uuid", "project", "schema"]
)
def test_provider_unknown_is_error_never_success_or_partial(readable_fixture, failure):
    f = readable_fixture
    original = f["provider_http"]._open_response

    def fail(request, timeout):
        if isinstance(failure, int):
            raise f["provider_http"].status_error(failure)
        if failure == "timeout":
            raise TimeoutError()
        response = original(request, timeout)
        data = json.loads(response.content)
        if failure == "business":
            data = {"code": 403, "message": "synthetic private failure"}
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
    assert "synthetic private" not in response.text
    if failure == 401:
        assert f["login"].calls == 1


def test_one_401_refresh_reuses_existing_personal_path(readable_fixture):
    f = readable_fixture
    original = f["provider_http"]._open_response
    count = 0

    def first_401(request, timeout):
        nonlocal count
        count += 1
        if count == 1:
            raise f["provider_http"].status_error(401)
        return original(request, timeout)

    f["provider_http"]._open_response = first_401
    assert post(f).status_code == 200
    assert count == 2 and f["login"].calls == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "kb",
        "member",
        "source",
        "membership",
        "revision",
        "index",
        "identity",
        "binding",
        "project",
        "default_team",
        "detail",
    ],
)
@pytest.mark.parametrize("during", [False, True])
def test_revocation_before_or_during_provider_discards_result(readable_fixture, mutation, during):
    f, db = readable_fixture, readable_fixture["runtime"].database
    statements = {
        "kb": "delete from rbac_role_application_knowledge_base",
        "member": "update rbac_user_role set status='disabled'",
        "source": "update \"knowledge.retrieval_resource\" set status='disabled'",
        "membership": "update \"knowledge.knowledge_base_document\" set state='removed'",
        "revision": "update \"knowledge.document\" set lifecycle_state='deleted'",
        "index": "update \"knowledge.vector_index\" set state='FAILED'",
        "identity": "update user_external_identity set tenant_code='other-instance' where provider='ones'",
        "binding": 'update "knowledge.source" set source_system=\'other\'',
        "project": "update \"knowledge.document_revision\" set source_project_id='other-project'",
        "default_team": 'update user_external_identity set metadata_json=\'{"team_uuids":["other-team"],"default_team_id":"other-team"}\' where provider=\'ones\'',
        "detail": "delete from rbac_role_application_mcp_tool where tool_identifier='ones_get_work_item_detail'",
    }
    original = f["provider_http"]._open_response

    def revoke(request, timeout):
        value = original(request, timeout)
        db.execute(statements[mutation])
        return value

    if during:
        f["provider_http"]._open_response = revoke
    else:
        db.execute(statements[mutation])
    # 调用前已切换到另一个有效默认 Team 时，按本人新 Team 请求并依赖 Provider 可读结果；
    # 不再要求匹配知识库预填 Team。调用中切换仍必须丢弃结果。
    new_default = mutation == "default_team" and not during
    assert post(f).status_code == (200 if new_default else 503)
    assert bool(f["calls"]) == (during or new_default)


@pytest.mark.parametrize(
    "extra",
    [
        {"actor": "someone"},
        {"team_id": "other"},
        {"url": "http://example.invalid"},
        {"scope": []},
        {"work_item_uuid": "other"},
        {"operation": "mutation"},
    ],
)
def test_overrides_rejected_before_io(readable_fixture, extra):
    f = readable_fixture
    assert post(f, {**f["body"], **extra}).status_code == 400
    assert not f["calls"]


def test_internal_security_and_size_and_concurrency(readable_fixture):
    f, client = readable_fixture, readable_fixture["client"]
    for headers, expected in [
        ({}, 401),
        ({"authorization": "Bearer invalid"}, 401),
        ({"authorization": "Bearer " + f["token"], "origin": "http://example.invalid"}, 403),
        ({"authorization": "Bearer " + f["token"], "host": "example.invalid"}, 403),
    ]:
        assert (
            client.post(READABILITY_PATH, json=f["body"], headers=headers).status_code == expected
        )
    assert (
        client.post(
            READABILITY_PATH, content=" " * 8193, headers={"authorization": "Bearer " + f["token"]}
        ).status_code
        == 413
    )
    for _ in range(4):
        assert f["endpoint"]._slots.acquire(blocking=False)
    try:
        assert post(f).status_code == 429
    finally:
        for _ in range(4):
            f["endpoint"]._slots.release()
    assert not f["calls"]
    assert post(f).status_code == 200


@pytest.mark.parametrize(
    "field,value",
    [
        ("chunk_ids", []),
        ("chunk_ids", ["unknown"]),
        ("chunk_ids", ["x", "x"]),
        ("chunk_ids", [f"x{i}" for i in range(51)]),
        ("chunk_ids", [1]),
        ("knowledge_base_id", "unknown"),
        ("index_id", "unknown"),
        ("resource_revision_id", "unknown"),
    ],
)
def test_candidate_membership_and_input_bounds(readable_fixture, field, value):
    f = readable_fixture
    response = post(f, {**f["body"], field: value})
    assert response.status_code in (400, 503) and not f["calls"]


def test_duplicate_json_and_authorization_rejected(readable_fixture):
    f = readable_fixture
    token = "Bearer " + f["token"]
    response = f["client"].post(
        READABILITY_PATH,
        content='{"chunk_ids":[],"chunk_ids":[]}',
        headers={"authorization": token},
    )
    assert response.status_code == 400
    response = f["client"].post(
        READABILITY_PATH,
        json=f["body"],
        headers=[("authorization", token), ("authorization", token)],
    )
    assert response.status_code == 401
    assert not f["calls"]


def test_budget_caps_io_and_drops_late_result_without_leaking_context(
    readable_fixture, monkeypatch
):
    f = readable_fixture
    clock = [100.0]
    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    original = f["provider_http"]._open_response

    def late(request, timeout):
        assert 0 < timeout <= 5
        result = original(request, timeout)
        clock[0] += 61
        return result

    f["provider_http"]._open_response = late
    assert post(f).status_code == 503
    assert budget.ones_io_timeout(12) == 12  # 不改变后续普通工具调用。
    f["provider_http"]._open_response = original
    assert post(f).status_code == 200


def test_nested_budget_never_extends_parent_and_expires_before_io(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    with pytest.raises(AppError) as error:
        with budget.ones_io_budget(3):
            assert budget.ones_io_timeout(30) == 3
            with budget.ones_io_budget(60):
                clock[0] += 2
                assert budget.ones_io_timeout(30) == 1
                clock[0] += 2
                budget.ones_io_timeout(30)
    assert error.value.error_code == "ones_read_budget_exhausted"
    assert budget.ones_io_timeout(-1) == -1
