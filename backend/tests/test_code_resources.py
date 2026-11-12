"""Empty code libraries and resource-scoped checkout admission; synthetic providers."""

from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest

from app.modules.knowledge.application.content_access import KnowledgeContent
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.domain.models import KnowledgeJobAccess
from app.modules.knowledge.infrastructure.code_checkout_jobs import CodeCheckoutJobs
from app.modules.knowledge.infrastructure.code_resource_service import CodeResourceService
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.modules.knowledge.infrastructure.storage import insert
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.infrastructure.code_svn_access import (
    CodeSvnAccess,
    connection_fingerprint,
)
from backend.tests.support.code_answers import code_configuration, analysis_context, confirm
from backend.tests.support.runtime import container


class Models:
    def __init__(self):
        self.checked = 0

    def check(self):
        self.checked += 1


class Vectors:
    def __init__(self):
        self.collections = {}

    def ensure(self, index):
        self.collections.setdefault(index["collection_name"], digest(index["profile"]))

    def check(self, index):
        assert self.collections[index["collection_name"]] == index["profile_hash"]


class Content:
    def __init__(self, store, vectors, qdrant):
        self.store, self.vectors, self.qdrant = store, vectors, qdrant

    @contextmanager
    def open(self, config, *, knowledge_base_id, revision_id=""):
        yield KnowledgeContent(self.store, self.vectors, self.qdrant)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    runtime = container()
    try:
        _, source, checkout, root = code_configuration(runtime, tmp_path)
        entry = {
            "public_url": "https://svn.invalid/repository/trunk",
            "branch_url": "https://svn.invalid/repository/trunk",
            "repository_uuid": "00000000-0000-0000-0000-000000000001",
            "branch_path": "/trunk",
            "auth_ref": "synthetic",
        }
        registry = (tmp_path / "registry.json").resolve()
        registry.write_text(json.dumps({"synthetic": entry}))
        insert(
            runtime.database,
            "code_svn_operation",
            dict(
                id="synthetic-original-checkout",
                source_id=source,
                checkout_id=checkout["id"],
                actor_id="user_local_admin",
                config_revision_id="code-config",
                operation_kind="checkout",
                request_key="synthetic-original-checkout",
                request_hash="0" * 64,
                state="succeeded",
                target_revision=100,
                request_json={
                    "registration": "synthetic",
                    "registration_hash": connection_fingerprint(entry),
                },
                deadline_at=now(),
                created_at=now(),
                updated_at=now(),
            ),
        )
        monkeypatch.setenv("CODE_CHECKOUT_REGISTRY_FILE", str(registry))
        monkeypatch.setenv("CODE_CHECKOUT_ENABLED", "true")
        admin = runtime.knowledge_services.sources()
        vectors = VectorRepository(runtime.database)
        qdrant, embedding = Vectors(), Models()
        service = CodeResourceService(
            admin,
            vectors,
            embedding=embedding,
            qdrant=qdrant,
            content_access=Content(GovernanceStore(runtime.database), vectors, qdrant),
        )
        yield runtime, source, checkout, root, service, registry
    finally:
        runtime.database.close()


def create(service):
    return service.create_code(
        actor_id="user_local_admin", code="new-code-kb", name="Synthetic code library"
    )


def bind(service, resource, checkout):
    return service.save_code_draft(
        actor_id="user_local_admin",
        resource_id=resource["id"],
        expected_revision=resource["revision"],
        checkout_id=checkout["id"],
        allowed_paths=["set_server"],
    )


def test_binding_uses_original_connection_not_same_url_or_newer_account(setup):
    runtime, _, checkout, _, service, registry = setup
    resource = create(service)
    access = CodeSvnAccess(runtime.database, registry)
    args = dict(
        resource_id=resource["id"],
        url="https://svn.invalid/repository/trunk",
        username="synthetic-user",
        password="synthetic-password",
        actor_id="user_local_admin",
        platform_config=runtime.platform_config_service,
    )
    original = access.create(**args)
    newer = access.create(**args)
    access.pin(
        original["id"],
        resource["id"],
        repository_uuid="00000000-0000-0000-0000-000000000001",
        branch_path="/trunk",
    )
    runtime.database.execute(
        f"UPDATE {service.store.t('code_svn_operation')} SET config_revision_id=?,request_json=? WHERE id=?",
        (
            resource["draft"]["id"],
            json.dumps(
                {
                    "registration": original["id"],
                    "registration_hash": connection_fingerprint(
                        access.entry(original["id"], resource["id"])
                    ),
                }
            ),
            "synthetic-original-checkout",
        ),
    )
    saved = bind(service, resource, checkout)
    assert saved["draft"]["code_configuration"]["svn_access_ref"] == original["id"]
    assert original["id"] != newer["id"]
    summary = CodeCheckoutJobs(
        runtime.database, runtime.knowledge_services.sources(), registry
    ).snapshot(resource["id"])["checkouts"][0]["connection"]
    assert summary == {"id": original["id"], "url": args["url"], "kind": "account"}
    other = service.create_code(actor_id="user_local_admin", code="other-code", name="Other")
    with pytest.raises(CodeKnowledgeError, match="CODE_REGISTRATION_CHANGED"):
        bind(service, other, checkout)
    denied = CodeCheckoutJobs(
        runtime.database, runtime.knowledge_services.sources(), registry
    ).snapshot(other["id"])["checkouts"][0]
    assert denied["connection"] is None
    assert denied["connection_error"] == "CODE_REGISTRATION_CHANGED"
    # Pinning is excluded from the connection fingerprint; source identity is still checked.
    runtime.database.execute(
        f"UPDATE {service.store.t('code_svn_connection')} SET repository_uuid=? WHERE id=?",
        ("00000000-0000-0000-0000-000000000002", original["id"]),
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_REGISTRATION_CHANGED"):
        bind(service, saved, checkout)


@pytest.mark.parametrize("state", ["failed", "missing", "ambiguous"])
def test_binding_refuses_missing_or_ambiguous_checkout_provenance(setup, state):
    runtime, _, checkout, _, service, _ = setup
    resource = create(service)
    table = service.store.t("code_svn_operation")
    if state == "missing":
        runtime.database.execute(f"DELETE FROM {table} WHERE id='synthetic-original-checkout'")
    elif state == "failed":
        runtime.database.execute(
            f"UPDATE {table} SET state='failed' WHERE id='synthetic-original-checkout'"
        )
    else:
        original = runtime.database.execute_one(
            f"SELECT * FROM {table} WHERE id='synthetic-original-checkout'"
        )
        original.update(id="second-checkout", request_key="second-checkout")
        insert(runtime.database, "code_svn_operation", original)
    with pytest.raises(CodeKnowledgeError, match="CODE_CHECKOUT_CONNECTION_UNAVAILABLE"):
        bind(service, resource, checkout)
    assert service.view(resource["id"])["draft"]["code_configuration"]["checkout_id"] is None


def test_binding_refuses_changed_deployment_connection(setup):
    _, _, checkout, _, service, registry = setup
    resource = create(service)
    data = json.loads(registry.read_text())
    data["synthetic"]["auth_ref"] = "changed-configuration"
    registry.write_text(json.dumps(data))
    with pytest.raises(CodeKnowledgeError, match="CODE_REGISTRATION_CHANGED"):
        bind(service, resource, checkout)


def test_code_library_can_bind_multiple_existing_environments(setup):
    runtime, _, checkout, _, service, _ = setup
    environments = [
        runtime.platform_config_service.upsert_environment(
            {"code": code, "display_name": code}, actor_id="user_local_admin"
        )
        for code in ("code-env-one", "code-env-two")
    ]
    resource = create(service)
    ids = sorted(item["id"] for item in environments)
    saved = service.save_code_draft(
        actor_id="user_local_admin",
        resource_id=resource["id"],
        expected_revision=resource["revision"],
        checkout_id=checkout["id"],
        allowed_paths=["set_server"],
        environment_ids=ids,
    )
    assert saved["draft"]["code_configuration"]["environment_ids"] == ids
    assert service.store.code_environments(saved["draft"]["id"]) == [
        {"id": row["id"], "code": row["code"], "name": row["code"]} for row in environments
    ]
    with pytest.raises(CodeKnowledgeError, match="CODE_ENVIRONMENT_INVALID"):
        service.save_code_draft(
            actor_id="user_local_admin",
            resource_id=resource["id"],
            expected_revision=saved["revision"],
            checkout_id=checkout["id"],
            allowed_paths=["set_server"],
            environment_ids=["missing-environment"],
        )


def test_index_controls_do_not_change_published_configuration(setup):
    _, _, _, _, service, _ = setup
    created = create(service)
    assert service.indexing_status(actor_id="user_local_admin", resource_id=created["id"]) == {
        "paused": False,
        "indexes": [],
    }
    assert (
        service.set_indexing(actor_id="user_local_admin", resource_id=created["id"], paused=True)[
            "paused"
        ]
        is True
    )
    assert service.view(created["id"])["revision"] == created["revision"]
    assert (
        service.set_indexing(actor_id="user_local_admin", resource_id=created["id"], paused=False)[
            "paused"
        ]
        is False
    )
    with pytest.raises(CodeKnowledgeError):
        service.set_indexing(actor_id="user_local_admin", resource_id=created["id"], paused=1)


@pytest.mark.parametrize(
    "field,value", [("collection_name", "ones_collection"), ("state", "RETIRED")]
)
def test_initialize_never_retargets_an_existing_index(setup, field, value):
    runtime, _, checkout, _, service, _ = setup
    bound = bind(service, create(service), checkout)
    initialized = service.initialize_index(
        actor_id="user_local_admin", resource_id=bound["id"], expected_revision=bound["revision"]
    )
    runtime.database.execute(
        f"UPDATE {service.store.t('vector_index')} SET {field}=? WHERE id=?",
        (value, initialized["draft"]["index_id"]),
    )
    before = dict(service.qdrant.collections)
    with pytest.raises(CodeKnowledgeError, match="CODE_INDEX_CONFIGURATION_INVALID"):
        service.initialize_index(
            actor_id="user_local_admin",
            resource_id=bound["id"],
            expected_revision=initialized["revision"],
        )
    assert service.qdrant.collections == before


@pytest.mark.parametrize("historical_state", [None, "disabled", "archived", "unpublished"])
def test_empty_library_has_its_own_initialization_and_publication(setup, historical_state):
    runtime, source, checkout, _, service, _ = setup
    created = create(service)
    assert created["kind"] == "code" and created["published"] is None
    assert created["draft"]["index_id"] is None
    assert created["draft"]["code_configuration"]["source_id"] is None
    bound = bind(service, created, checkout)
    initialized = service.initialize_index(
        actor_id="user_local_admin", resource_id=bound["id"], expected_revision=bound["revision"]
    )
    index_id = initialized["draft"]["index_id"]
    repeated = service.initialize_index(
        actor_id="user_local_admin",
        resource_id=bound["id"],
        expected_revision=initialized["revision"],
    )
    assert repeated["draft"]["index_id"] == index_id and len(service.qdrant.collections) == 1
    verified = service.verify_draft(
        actor_id="user_local_admin", resource_id=bound["id"], expected_revision=repeated["revision"]
    )
    published = service.publish(
        actor_id="user_local_admin", resource_id=bound["id"], expected_revision=verified["revision"]
    )
    pin = service.resolve(created["knowledge_base_id"])
    assert pin.source_id == source and pin.index_id == index_id
    assert published["published"]["configuration_version"] == 5
    assert runtime.database.execute_one('SELECT count(*) AS n FROM "knowledge.document"')["n"] == 0
    assert (
        runtime.database.execute_one('SELECT count(*) AS n FROM "knowledge.code_index_task"')["n"]
        == 0
    )
    assert next(iter(service.qdrant.collections)).startswith("code_answers_")
    # The Runtime's production composition must resolve this managed storage
    # configuration, not only test fixtures whose storage_config_json is null.
    ctx = analysis_context(runtime, source, checkout)
    grant = runtime.code_source_grant
    assert grant is not None
    base_ids = (created["knowledge_base_id"],)
    if historical_state:
        if historical_state == "unpublished":
            runtime.database.execute(
                'UPDATE "knowledge.retrieval_resource" SET published_revision_id=null '
                "WHERE id='code-resource'"
            )
        else:
            runtime.database.execute(
                'UPDATE "knowledge.retrieval_resource" SET status=? WHERE id=?',
                (historical_state, "code-resource"),
            )
        base_ids += ("code-kb",)
    grant.gate = SimpleNamespace(
        resolve=lambda **kw: KnowledgeJobAccess(
            ctx.job_id,
            ctx.actor_id,
            "app",
            "pub",
            "a" * 64,
            "b" * 64,
            base_ids,
            "c" * 64,
        ),
        snapshots=SimpleNamespace(
            verify=lambda job: {
                "snapshot": {"tools": [{"tool_identifier": "knowledge_svn_update"}]}
            }
        ),
    )
    capability = grant.for_job(ctx.job_id)
    assert [item["knowledge_base_id"] for item in capability["sources"]] == [
        created["knowledge_base_id"]
    ]
    assert capability["sources"][0]["resource_fingerprint"] == pin.fingerprint
    assert capability["sources"][0]["checkout_id"] == checkout["id"]


def test_source_binding_rejects_wrong_repository_scope_and_active_analysis(setup):
    runtime, source, checkout, _, service, registry = setup
    created = create(service)
    entries = json.loads(registry.read_text())
    entries["synthetic"]["repository_uuid"] = "00000000-0000-0000-0000-000000000002"
    registry.write_text(json.dumps(entries))
    with pytest.raises(CodeKnowledgeError, match="CODE_REGISTRATION_CHANGED"):
        bind(service, created, checkout)
    with pytest.raises(CodeKnowledgeError, match="CODE_MANAGED_STORAGE_REQUIRED"):
        service.create_code(
            actor_id="user_local_admin",
            code="wrong-target",
            name="Wrong",
            storage={
                "postgres": {"mode": "platform"},
                "qdrant": {"url": "http://other.invalid:6333", "api_key_ref": ""},
            },
        )
    # The original synthetic publication is in use; expiry alone never permits rebinding.
    store = CodeCheckoutJobs(runtime.database, runtime.knowledge_services.sources())
    store.authorize_context = lambda context: None
    ctx = analysis_context(runtime, source, checkout)
    analysis = confirm(store, ctx, store.begin(ctx, "active"))
    from app.modules.knowledge.domain.governance import KnowledgeGovernanceError

    with pytest.raises(KnowledgeGovernanceError, match="knowledge_resource_busy"):
        service.store.assert_code_idle(ctx.knowledge_base_id)
    assert store.row("code_analysis", analysis["id"])["read_released_at"] is None


def test_management_initial_browse_has_no_invented_source_and_checkout_reserves_directory(setup):
    runtime, source, _, root, service, registry = setup
    resource = create(service)
    jobs = CodeCheckoutJobs(runtime.database, runtime.knowledge_services.sources(), registry)
    browse = jobs.submit_browse(
        actor_id="user_local_admin",
        resource_id=resource["id"],
        url="https://svn.invalid/repository/trunk",
        revision=100,
        request_key="browse",
    )
    assert browse["source_id"] is None and browse["analysis_id"] is None
    assert (
        jobs.submit_browse(
            actor_id="user_local_admin",
            resource_id=resource["id"],
            url="https://svn.invalid/repository/trunk",
            revision=100,
            request_key="browse",
        )["id"]
        == browse["id"]
    )
    claim = jobs.claim_management(browse["id"], owner="synthetic-worker")
    with jobs.db.unit_of_work():
        jobs.finish_management(
            browse["id"],
            owner="synthetic-worker",
            claim=claim["claim_version"],
            source_id=source,
            metadata={"revision": 100},
            result_hash="f" * 64,
        )
    pending = jobs.submit_checkout(
        actor_id="user_local_admin",
        resource_id=resource["id"],
        browse_job_id=browse["id"],
        paths=["set_server/a.cpp", "set_web/JTH"],
        folder="chosen",
        request_key="checkout",
    )
    reserved = jobs.row("code_checkout", pending["checkout_id"])
    assert reserved["physical_key"] is None and reserved["state"] == "preparing"
    assert reserved["writer_operation_id"] == pending["id"] and not (root / "chosen").exists()
    with pytest.raises(CodeKnowledgeError, match="CODE_CHECKOUT_OVERLAP"):
        jobs.submit_checkout(
            actor_id="user_local_admin",
            resource_id=resource["id"],
            browse_job_id=browse["id"],
            paths=["set_server"],
            folder="chosen",
            request_key="other",
        )
    with pytest.raises(CodeKnowledgeError, match="CODE_SCOPE_INVALID"):
        jobs.submit_checkout(
            actor_id="user_local_admin",
            resource_id=resource["id"],
            browse_job_id=browse["id"],
            paths=["set_server", "set_server/a.cpp"],
            folder="overlap",
            request_key="overlap",
        )
