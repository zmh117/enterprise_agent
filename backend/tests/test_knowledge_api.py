from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
import json

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.domain.chunking import DEFAULT_PROFILE
from app.modules.knowledge.application.source_service import SourceBindingService
from app.modules.knowledge.application.resource_service import KnowledgeResourceService
from app.modules.knowledge.application.vector_service import VectorService
from backend.tests.test_knowledge_chunks import import_rows
from backend.tests.test_knowledge_governance import SyntheticVerifier
from backend.tests.test_knowledge_import import export_row
from backend.tests.test_knowledge_vectors import SyntheticEmbedding, SyntheticQdrant
from backend.tests.test_unified_identity_rbac import (
    unified_container,
    login,
    csrf_headers,
    ADMIN_ID,
)


ROOT = "/api/platform/knowledge"


@pytest.fixture
def managed(tmp_path, monkeypatch):
    runtime = unified_container()
    db = runtime.database
    import_rows(db, tmp_path, [export_row()])
    chunks = ChunkService(ChunkRepository(db)).run(
        knowledge_base_code="synthetic_base", expected_count=1, commit=True
    )["counts"]["chunks"]
    vectors = VectorService(VectorRepository(db), SyntheticEmbedding(), SyntheticQdrant())
    snapshot = vectors.repository.snapshot(
        vectors.repository.scope("synthetic_base"), DEFAULT_PROFILE.fingerprint, 1, chunks
    )
    vectors.build("synthetic-v1", snapshot)
    sources = SourceBindingService(
        GovernanceStore(db), runtime.permission_service, runtime.audit_service, SyntheticVerifier()
    )
    resources = KnowledgeResourceService(
        sources,
        VectorRepository(sources.store.database),
        embedding=vectors.embedding,
        qdrant=vectors.qdrant,
    )
    monkeypatch.setattr(runtime.knowledge_services, "sources", lambda: sources)
    monkeypatch.setattr(
        runtime.knowledge_services,
        "verify_resource",
        lambda **kwargs: resources.verify_draft(**kwargs),
    )
    with TestClient(create_app(runtime.settings, container_factory=lambda _: runtime)) as client:
        yield runtime, client, vectors, sources, resources


def create_binding(f, headers):
    runtime, client, *_ = f
    source = runtime.database.execute_one('select id from "knowledge.source"')
    return client.post(
        ROOT + "/source-bindings",
        headers=headers,
        json={
            "source_id": source["id"],
            "instance_code": "synthetic_instance",
            "team_id": "synthetic_team",
            "expected_revision": 0,
            "batch_attested": True,
            "attestation_hash": "a" * 64,
        },
    )


def test_admin_resource_lifecycle_and_safe_management_projection(managed):
    _, client, vector, _, _ = managed
    headers = csrf_headers(login(client))
    binding = create_binding(managed, headers)
    assert binding.status_code == 200, binding.text
    response = client.post(
        ROOT + "/source-bindings/" + binding.json()["id"] + "/verify",
        headers=headers,
        json={"job_id": "synthetic_job"},
    )
    assert response.status_code == 200 and response.json()["state"] == "VERIFIED"
    catalog = client.get(ROOT + "/catalog").json()
    resource = client.post(
        ROOT + "/resources",
        headers=headers,
        json={
            "knowledge_base_id": catalog["bases"][0]["id"],
            "code": "synthetic",
            "name": "合成知识库",
        },
    )
    assert resource.status_code == 200, resource.text
    path = ROOT + "/resources/" + resource.json()["id"]
    saved = client.put(
        path + "/draft",
        headers=headers,
        json={
            "expected_revision": resource.json()["revision"],
            "binding_id": binding.json()["id"],
            "index_id": catalog["indexes"][0]["id"],
        },
    )
    assert saved.status_code == 200, saved.text
    verified = client.post(
        path + "/verify", headers=headers, json={"expected_revision": saved.json()["revision"]}
    )
    assert verified.status_code == 200, verified.text
    published = client.post(
        path + "/publish", headers=headers, json={"expected_revision": verified.json()["revision"]}
    )
    assert published.status_code == 200 and published.json()["published"]["published_at"]
    disabled = client.post(
        path + "/status",
        headers=headers,
        json={"expected_revision": published.json()["revision"], "status": "disabled"},
    )
    assert disabled.status_code == 200 and disabled.json()["status"] == "disabled"
    revoked = client.post(
        ROOT + "/source-bindings/" + binding.json()["id"] + "/revoke", headers=headers, json={}
    )
    assert revoked.status_code == 200 and revoked.json() == {"revoked": True}
    for suffix in ("sources", "resources", "catalog"):
        response = client.get(ROOT + "/" + suffix)
        assert response.status_code == 200
        encoded = json.dumps(response.json())
        for forbidden in (
            "embedding_text",
            "provider_token",
            "collection_name",
            "description",
            "base_url",
        ):
            assert forbidden not in encoded
    assert vector.repository.get("synthetic-v1")["state"] == "READY"


def test_authentication_csrf_and_permission_are_checked_before_parsing(managed):
    runtime, client, *_ = managed
    for suffix in ("sources", "resources", "catalog"):
        assert (
            client.get(ROOT + "/" + suffix, headers={"x-admin-user-id": ADMIN_ID}).status_code
            == 401
        )
    assert client.post(ROOT + "/resources", content="invalid").status_code == 401
    csrf = login(client)
    assert client.post(ROOT + "/resources", content="invalid").status_code == 403
    assert (
        client.post(
            ROOT + "/resources",
            headers={**csrf_headers(csrf), "origin": "http://evil.invalid"},
            content="invalid",
        ).status_code
        == 403
    )
    runtime.database.execute("delete from rbac_user_role where user_id=?", (ADMIN_ID,))
    for suffix in ("sources", "resources", "catalog"):
        assert client.get(ROOT + "/" + suffix).status_code == 403
    assert (
        client.post(ROOT + "/resources", headers=csrf_headers(csrf), content="invalid").status_code
        == 403
    )
    assert not runtime.database.execute('select * from "knowledge.retrieval_resource"')


@pytest.mark.parametrize(
    "content",
    [
        '{"knowledge_base_id":"synthetic","code":"a","name":"a","environment":"jnw"}',
        '{"knowledge_base_id":"synthetic","code":"a","name":"a","url":"http://evil.invalid"}',
        '{"knowledge_base_id":"synthetic","code":"a","name":"a","code":"b"}',
        "[]",
        "null",
        "{",
        "[" * 2000 + "]" * 2000,
    ],
)
def test_management_rejects_unknown_fields_and_duplicate_json_keys(managed, content):
    _, client, *_ = managed
    response = client.post(
        ROOT + "/resources", headers=csrf_headers(login(client)), content=content
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "knowledge_input_invalid"
    assert "evil.invalid" not in response.text


def test_body_limit_source_job_contract_and_unconfigured_ones_fail_closed(managed, monkeypatch):
    runtime, client, *_ = managed
    headers = csrf_headers(login(client))
    response = client.post(ROOT + "/resources", headers=headers, content="a" * 8193)
    assert response.status_code == 413
    for value in (
        {},
        {"job_id": "synthetic_job", "jwt": "synthetic-forbidden"},
        {"actor_id": ADMIN_ID},
    ):
        response = client.post(
            ROOT + "/source-bindings/synthetic/verify", headers=headers, json=value
        )
        assert response.status_code == 400
        assert "synthetic-forbidden" not in response.text
    unavailable = SourceBindingService(
        GovernanceStore(runtime.database), runtime.permission_service, runtime.audit_service, None
    )
    monkeypatch.setattr(runtime.knowledge_services, "sources", lambda: unavailable)
    response = create_binding(managed, headers)
    assert (
        response.status_code == 400
        and response.json()["detail"]["error_code"] == "knowledge_verifier_unavailable"
    )
    assert not runtime.database.execute('select * from "knowledge.source_binding"')
