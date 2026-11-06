"""Published MCP code queries with synthetic rules; no production model/source claims."""

from copy import deepcopy
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app.modules.identity.application.principal_jwt import (
    PrincipalJwks,
    PrincipalTokenIssuer,
    PrincipalTokenVerifier,
)
from app.modules.knowledge.infrastructure.code_indexing import CodeIndexStore, CodeSnapshotIndexer
from app.modules.knowledge.application.code_query import CodeKnowledgeQuery
from app.modules.knowledge.application.directory import KnowledgeDirectory
from app.modules.knowledge.application.resource_service import KnowledgeResourceService
from app.modules.knowledge.application.search import KnowledgeSearch
from app.modules.knowledge.application.source_service import SourceBindingService
from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository
from app.modules.knowledge.infrastructure.code_repository import CodeRepository, knowledge_id
from app.modules.knowledge.infrastructure.content_access import ManagedContentAccess
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.job_access import KnowledgeJobGate, KNOWLEDGE_TOOLS
from app.modules.knowledge.infrastructure.reader_access import KnowledgePrincipalAccess
from app.modules.knowledge.infrastructure.storage import table
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.modules.mcp_audit import McpAuditCoordinator
from app.shared import mcp_server_policy
from services.knowledge_mcp_server.app import create_app
from services.knowledge_mcp_server.auth import KnowledgeMcpAuth
from services.knowledge_mcp_server.tools import KnowledgeMcpTools
from backend.tests.support.knowledge_reranker import SyntheticReranker
from backend.tests.test_code_indexing import candidate, SnapshotQdrant
from backend.tests.test_knowledge_mcp_server import rpc
from backend.tests.test_knowledge_vectors import SyntheticEmbedding
from backend.tests.test_ones_mcp_runtime import _fixture


class QueryQdrant(SnapshotQdrant):
    def code_search(self, index, snapshot_id, vector, limit):
        self.search_limits.append((snapshot_id, limit))
        return [
            dict(deepcopy(p), score=0.8)
            for p in self.points.values()
            if p["payload"].get("snapshot_id") == snapshot_id
        ][:limit]


@pytest.fixture
def code_mcp():
    embedding, qdrant = SyntheticEmbedding(), QueryQdrant()
    snapshots = {}
    ids = {}

    def configure(runtime, selection):
        db = runtime.database
        for revision in (100, 101, 102):
            current, build, lease = candidate(db, revision, source_config={"svn_verified": True})
            ids.update(current)
            indexer = CodeSnapshotIndexer(db, embedding, qdrant)
            assert not indexer.index(build["build_id"], lease)
            assert indexer.index(build["build_id"], lease)
            CodeBuildRepository(db).finish_history(build["build_id"], lease)
            snapshots[revision] = build["snapshot_id"]
        db.execute(
            "insert into rbac_role_application_knowledge_base(application_access_id,knowledge_base_id,created_at) "
            "select id,?,created_at from rbac_role_application_access where application_id=?",
            (ids["knowledge_base_id"], selection["application_id"]),
        )

    f = _fixture(
        capabilities=("ones_work_item_search", *KNOWLEDGE_TOOLS),
        current_agent_envelope=True,
        before_job=configure,
    )
    runtime, db = f["runtime"], f["runtime"].database
    try:
        repo = CodeRepository(db)
        builds = CodeBuildRepository(db)
        builds.record_commits(
            ids["source_id"],
            config_hash=repo.binding(ids["source_id"])["config_hash"],
            after=100,
            target=102,
            repository_uuid="synthetic",
            commits=[{"revision": rev, "paths": []} for rev in (101, 102)],
        )
        sources = SourceBindingService(
            GovernanceStore(db), runtime.permission_service, runtime.audit_service
        )
        resources = KnowledgeResourceService(
            sources,
            VectorRepository(db),
            embedding=embedding,
            qdrant=qdrant,
            content_access=ManagedContentAccess(db, lambda *a: {}),
        )
        resource = resources.create(
            actor_id="user_local_admin",
            knowledge_base_id=ids["knowledge_base_id"],
            code="code-query-test",
            name="合成代码知识",
        )
        index = CodeIndexStore(db).ensure(ids["source_id"])
        draft = resources.save_draft(
            actor_id="user_local_admin",
            resource_id=resource["id"],
            expected_revision=resource["revision"],
            index_id=index["id"],
        )
        checked = resources.verify_draft(
            actor_id="user_local_admin",
            resource_id=resource["id"],
            expected_revision=draft["revision"],
        )
        resources.publish(
            actor_id="user_local_admin",
            resource_id=resource["id"],
            expected_revision=checked["revision"],
        )
        gate = KnowledgeJobGate(
            db, runtime.mcp_tool_snapshot_service, runtime.business_authorization_service
        )
        issuer = PrincipalTokenIssuer(
            db,
            runtime.mcp_tool_snapshot_service,
            runtime.business_authorization_service,
            f["issuer"].signing_key,
            runtime.audit_service,
            knowledge_job_gate=gate,
            server_policies=mcp_server_policy.MCP_SERVER_POLICIES,
        )
        token = issuer.issue_business_mcp_for_job(job_id=f["job"].id, server_code="knowledge-mcp")
        access = KnowledgePrincipalAccess(
            PrincipalTokenVerifier(
                PrincipalJwks.from_dict(issuer.signing_key.public_jwks()),
                expected_audience="knowledge-mcp",
                server_policies=mcp_server_policy.MCP_SERVER_POLICIES,
            ),
            gate,
        )
        # No ONES identity may be needed, even with online mode enabled.
        db.execute("update user_external_identity set status='disabled' where provider='ones'")
        principal_client = SimpleNamespace(
            renew_principal=lambda _: pytest.fail("unexpected renewal")
        )
        search = KnowledgeSearch(
            access,
            resources,
            embedding,
            qdrant,
            runtime.audit_service,
            reranker=SyntheticReranker(),
            readability=principal_client,
        )
        audit = McpAuditCoordinator(db, max_payload_bytes=16384)
        tools = KnowledgeMcpTools(
            KnowledgeMcpAuth(db, access),
            KnowledgeDirectory(access, resources, runtime.audit_service),
            search,
            audit,
            principal_client,
            CodeKnowledgeQuery(access, resources),
        )
        with TestClient(
            create_app(tools, ready=audit.assert_ready), base_url="http://knowledge-mcp:9108"
        ) as client:
            yield {
                **f,
                **ids,
                "mcp": client,
                "knowledge_token": token,
                "qdrant": qdrant,
                "embedding": embedding,
                "snapshots": snapshots,
                "query_access": access,
                "query_search": search,
                "query_resources": resources,
                "query_issuer": issuer,
                "repo": repo,
                "knowledge_id": knowledge_id(ids["source_id"], "factory.work_order.publish"),
                "body": {"knowledge_base_id": ids["knowledge_base_id"]},
            }
    finally:
        db.close()


def invoke(f, name, **arguments):
    response = rpc(
        f,
        params={
            "name": name,
            "arguments": {"knowledge_base_id": f["knowledge_base_id"], **arguments},
        },
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert not result["isError"], result
    return result["structuredContent"]


def test_real_mcp_search_get_compare_and_nonmonotonic_history(code_mcp):
    f = code_mcp
    directory = rpc(f, params={"name": "knowledge_list_bases", "arguments": {}}).json()["result"]
    assert directory["structuredContent"]["items"][0]["source_kind"] == "code"
    initial = f["embedding"].encoded
    unspecified = invoke(f, "knowledge_search", query="a 字段为空可以发布吗")
    assert unspecified["version"]["status"] == "VERSION_REQUIRED"
    assert f["embedding"].encoded == initial
    for revision, expected in (
        (100, "a is not empty"),
        (101, "no a restriction"),
        (102, "a is not empty"),
    ):
        found = invoke(
            f,
            "knowledge_search",
            query="a 字段为空可以发布吗",
            version={"kind": "svn", "revision": revision},
        )
        assert found["version"]["snapshot_id"] == f["snapshots"][revision]
        detail = invoke(
            f,
            "knowledge_get_behavior",
            knowledge_id=found["documents"][0]["knowledge_id"],
            snapshot_id=found["version"]["snapshot_id"],
        )
        assert detail["root"]["knowledge"]["guard"]["expression"] == expected
        assert not detail["partial"]
    args = dict(
        knowledge_id=f["knowledge_id"],
        from_version={"kind": "svn", "revision": 100},
        to_version={"kind": "svn", "revision": 102},
    )
    endpoints = invoke(f, "knowledge_compare_behavior", **args)
    assert endpoints["classification"] == "evidence_only"
    assert not endpoints["exact_revision_proven"]
    history = invoke(f, "knowledge_compare_behavior", mode="history", **args)
    assert history["complete"] and history["checked_revisions"] == [101, 102]
    assert [row["changed_at_revision"] for row in history["changes"]] == [101, 102]
    assert all(row["classification"] == "semantic" for row in history["changes"])
    assert all(row["before_evidence"] and row["after_evidence"] for row in history["changes"])
    audit = json.dumps(
        f["runtime"].database.execute("select * from mcp_operation_audit"), default=str
    )
    assert "a is not empty" not in audit and "a 字段为空" not in audit


def test_search_reads_snapshot_that_becomes_ready_during_cache_request(code_mcp, monkeypatch):
    f = code_mcp
    db = f["runtime"].database
    snapshot_id = f["snapshots"][101]
    db.execute(
        f"update {table(db, 'code_snapshot')} set state='CANDIDATE' where id=?", (snapshot_id,)
    )

    def completed(*, token, request):
        assert request["action"] == "version" and request["revision"] == 101
        db.execute(
            f"update {table(db, 'code_snapshot')} set state='READY' where id=?", (snapshot_id,)
        )
        return f["repo"].resolve(f["knowledge_base_id"], {"kind": "svn", "revision": 101})

    monkeypatch.setattr(f["query_search"], "code_history", SimpleNamespace(code_history=completed))
    result = invoke(
        f, "knowledge_search", query="发布条件", version={"kind": "svn", "revision": 101}
    )
    assert result["version"]["status"] == "READY" and result["documents"]
    assert result.get("partial_reason") != "version_not_ready"


@pytest.mark.parametrize(
    "fault", ["middle_missing", "ledger_missing", "contradictory_empty_ledger"]
)
def test_history_never_infers_changes_across_gaps(code_mcp, fault):
    f, upper = code_mcp, 102
    db = f["runtime"].database
    if fault == "middle_missing":
        db.execute(
            f"update {table(db, 'code_snapshot')} set state='CANDIDATE' where id=?",
            (f["snapshots"][101],),
        )
    elif fault == "ledger_missing":
        db.execute(f"update {table(db, 'code_binding')} set collected_from_revision=null")
    else:
        db.execute(f"delete from {table(db, 'code_commit')}")
        upper = 101
    value = invoke(
        f,
        "knowledge_compare_behavior",
        mode="history",
        knowledge_id=f["knowledge_id"],
        from_version={"kind": "svn", "revision": 100},
        to_version={"kind": "svn", "revision": upper},
    )
    assert not value["complete"] and value["unresolved_intervals"]
    assert not any(change["exact_revision_proven"] for change in value["changes"])


def test_version_not_ready_and_cross_snapshot_point_are_not_answers(code_mcp, monkeypatch):
    f = code_mcp
    before = f["embedding"].encoded
    result = invoke(f, "knowledge_search", query="发布", version={"kind": "svn", "revision": 99})
    assert result["version"] == {"status": "BUILD_REQUIRED", "requested_revision": 99}
    assert not result["documents"] and f["embedding"].encoded == before
    real = f["qdrant"].code_search
    monkeypatch.setattr(
        f["qdrant"],
        "code_search",
        lambda index, sid, vector, limit: real(index, f["snapshots"][101], vector, limit),
    )
    result = rpc(
        f,
        params={
            "name": "knowledge_search",
            "arguments": {
                "knowledge_base_id": f["knowledge_base_id"],
                "query": "发布",
                "version": {"kind": "svn", "revision": 100},
            },
        },
    ).json()["result"]
    assert (
        result["isError"]
        and result["structuredContent"]["error_code"] == "code_search_candidate_invalid"
    )


def test_get_rechecks_role_and_rejects_cross_library_id(code_mcp):
    f = code_mcp
    args = {
        "knowledge_base_id": "other",
        "knowledge_id": f["knowledge_id"],
        "snapshot_id": f["snapshots"][100],
    }
    assert rpc(f, params={"name": "knowledge_get_behavior", "arguments": args}).json()["result"][
        "isError"
    ]
    f["runtime"].database.execute("delete from rbac_role_application_knowledge_base")
    args["knowledge_base_id"] = f["knowledge_base_id"]
    assert rpc(f, params={"name": "knowledge_get_behavior", "arguments": args}).json()["result"][
        "isError"
    ]
