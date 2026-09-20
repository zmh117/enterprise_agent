"""合成双库存储与凭据边界；不连接真实 ONES、数据库或读取真实 Secret。"""

from contextlib import contextmanager
from copy import deepcopy
import json

import httpx
import pytest

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.infrastructure.repositories import AuditRepository
from app.modules.knowledge.application.content_access import KnowledgeContent
from app.modules.knowledge.application.resource_service import KnowledgeResourceService
from app.modules.knowledge.application.source_service import KnowledgeAdministration
from app.modules.knowledge.application.storage_broker import KnowledgeStorageBroker, STORAGE_PATH
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.storage_connection import storage_config
from app.modules.knowledge.infrastructure.content_access import (
    ManagedContentAccess,
    PlatformStorageCredentials,
)
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.modules.knowledge.infrastructure.vector_clients import QdrantClient
from app.shared.database import Database, default_migrations_dir, assert_external_io_allowed
from app.shared.migrations import Migrator
from backend.tests.test_knowledge_governance import (
    governance as governance_fixture,
    prepared as prepared_fixture,
)
from backend.tests.test_knowledge_job_access import knowledge_contract as knowledge_contract_fixture
from backend.tests.test_knowledge_readability import readable_fixture as readable_fixture_impl
from backend.tests.test_knowledge_readability_bridge import (
    bridge_fixture as bridge_fixture_impl,
    auth,
)
from backend.tests.test_knowledge_search import search_fixture as search_fixture_impl, search
from services.knowledge_mcp_server.storage_credentials import (
    BrokerStorageCredentials,
    storage_principal,
)

prepared = prepared_fixture
governance = governance_fixture
knowledge_contract = knowledge_contract_fixture
readable_fixture = readable_fixture_impl
bridge_fixture = bridge_fixture_impl
search_fixture = search_fixture_impl


def connection():
    return {
        "postgres": {
            "mode": "external",
            "host": "synthetic-content",
            "port": 5432,
            "database": "synthetic_knowledge",
            "username": "synthetic_reader",
            "password_ref": "secret://platform/synthetic_pg",
            "sslmode": "require",
        },
        "qdrant": {
            "url": "https://synthetic-qdrant:6333",
            "api_key_ref": "secret://platform/synthetic_qdrant",
        },
    }


class SyntheticContentAccess:
    def __init__(self, db, vector):
        self.db, self.vector = db, vector
        self.calls = []
        self.available = True

    @contextmanager
    def open(self, config, *, knowledge_base_id, revision_id):
        assert_external_io_allowed("synthetic_remote_content")
        self.calls.append((deepcopy(config), knowledge_base_id, revision_id))
        if not self.available:
            raise KnowledgeGovernanceError("knowledge_storage_unavailable")
        yield KnowledgeContent(GovernanceStore(self.db), self.vector.repository, self.vector.qdrant)


@pytest.mark.parametrize(
    "field,value",
    [
        ("postgres", {"mode": "external", "dsn": "postgresql://synthetic"}),
        ("qdrant", {"url": "http://user:password@synthetic", "api_key_ref": ""}),
        ("qdrant", {"url": "http://169.254.169.254", "api_key_ref": ""}),
        ("qdrant", {"url": "https://synthetic/path", "api_key_ref": ""}),
        ("qdrant", {"url": "https://synthetic?token=synthetic", "api_key_ref": ""}),
        ("qdrant", {"url": "https://synthetic", "api_key_ref": "env:SYNTHETIC"}),
    ],
)
def test_storage_contract_rejects_secret_payload_and_control_fields(field, value):
    config = connection()
    config[field] = value
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_storage_config_invalid"):
        storage_config(config)


@pytest.mark.parametrize(
    "field,value",
    [
        ("port", True),
        ("port", 0),
        ("host", "host/options"),
        ("host", "::"),
        ("password_ref", "synthetic-plaintext"),
        ("sslmode", "prefer"),
    ],
)
def test_postgres_connection_contract_is_strict(field, value):
    config = connection()
    config["postgres"][field] = value
    with pytest.raises(KnowledgeGovernanceError):
        storage_config(config)


def test_two_databases_publish_and_read_without_platform_content_or_rewrites(governance):
    content_db, vector, snapshot, source, permission, *_ = governance
    vector.build("synthetic-v1", snapshot)
    points = deepcopy(vector.qdrant.points)
    platform = Database("sqlite:///:memory:")
    Migrator(platform, default_migrations_dir(), migrator_build="synthetic-split").run()
    access = SyntheticContentAccess(content_db, vector)
    resources = KnowledgeResourceService(
        KnowledgeAdministration(
            GovernanceStore(platform), permission, AuditService(AuditRepository(platform))
        ),
        VectorRepository(platform),
        embedding=vector.embedding,
        content_access=access,
    )
    try:
        resource = resources.create(
            actor_id="synthetic_admin",
            knowledge_base_id=snapshot["knowledge_base_id"],
            code="synthetic-remote",
            name="合成外部知识库",
            storage=connection(),
            index_id=vector.repository.get("synthetic-v1")["id"],
        )
        assert resource["draft"]["storage"] == connection()
        verified = resources.verify_draft(
            actor_id="synthetic_admin",
            resource_id=resource["id"],
            expected_revision=resource["revision"],
        )
        published = resources.publish(
            actor_id="synthetic_admin",
            resource_id=resource["id"],
            expected_revision=verified["revision"],
        )
        pin = resources.resolve(resource["knowledge_base_id"])
        with resources.content_for(pin) as content:
            assert content.vectors.get(pin.index_code)["id"] == pin.index_id
        for table in ("document", "source", "vector_index", "document_chunk"):
            assert platform.execute(f'select * from "knowledge.{table}"') == []
        assert platform.execute("pragma foreign_key_check") == []
        assert len(platform.execute('select * from "knowledge.knowledge_base"')) == 1
        assert vector.qdrant.points == points
        from app.modules.platform_config.application.secret_usage import PlatformSecretUsageService
        from app.modules.platform_config.infrastructure.repository import PlatformConfigRepository

        usage = PlatformSecretUsageService(PlatformConfigRepository(platform))
        dependencies = usage.dependencies(
            secret_id="synthetic", secret_ref="secret://platform/synthetic_pg"
        )
        assert len(dependencies) == 1
        assert (
            dependencies[0]["active"]
            and dependencies[0]["dependency_type"] == "knowledge_resource_revision"
        )
        assert dependencies[0]["field_paths"] == ["postgres.password_ref"]
        assert "synthetic-content" not in json.dumps(dependencies)
        access.available = False
        assert resources.list_resources()["resources"][0]["published"] == published["published"]
        with pytest.raises(KnowledgeGovernanceError, match="knowledge_storage_unavailable"):
            resources.resolve(resource["knowledge_base_id"])
        resources.set_status(
            actor_id="synthetic_admin",
            resource_id=resource["id"],
            expected_revision=published["revision"],
            status="disabled",
        )
        assert not usage.dependencies(
            secret_id="synthetic", secret_ref="secret://platform/synthetic_pg"
        )[0]["active"]
        assert access.calls
    finally:
        platform.close()


@pytest.fixture
def broker(bridge_fixture):
    f = bridge_fixture
    resources = f["resources"]
    resources.content_access = SyntheticContentAccess(f["runtime"].database, f["vector"])
    current = resources.list_resources()["resources"][0]
    draft = resources.save_draft(
        actor_id="user_local_admin",
        resource_id=current["id"],
        expected_revision=current["revision"],
        index_id=f["body"]["index_id"],
        storage=connection(),
    )
    verified = resources.verify_draft(
        actor_id="user_local_admin", resource_id=current["id"], expected_revision=draft["revision"]
    )
    published = resources.publish(
        actor_id="user_local_admin",
        resource_id=current["id"],
        expected_revision=verified["revision"],
    )
    calls = []

    def credentials(config, base, revision):
        calls.append((config, base, revision))
        return {
            "postgres_password": "synthetic-private-password",
            "qdrant_api_key": "synthetic-private-key",
        }

    service = KnowledgeStorageBroker(
        f["bridge"].gateway, resources.store, credentials, f["runtime"].audit_service
    )
    f["bridge_client"].app.state.container.knowledge_storage_broker = service
    return (
        f,
        service,
        calls,
        {
            "knowledge_base_id": current["knowledge_base_id"],
            "resource_revision_id": published["published"]["id"],
        },
    )


def test_broker_requires_both_identities_current_grant_and_exact_published_revision(broker):
    f, service, calls, body = broker
    client = f["bridge_client"]
    for headers, value in [
        ({}, body),
        ({**auth(f), "authorization": "Bearer " + f["file_token"]}, body),
        ({**auth(f), "cookie": "synthetic=1"}, body),
        ({**auth(f), "origin": "http://synthetic"}, body),
        (auth(f), {**body, "secret_ref": "secret://platform/another"}),
        (auth(f), {**body, "resource_revision_id": "unpublished"}),
        (auth(f), {**body, "knowledge_base_id": "other"}),
    ]:
        response = client.post(STORAGE_PATH, headers=headers, json=value)
        assert response.status_code != 200 and "synthetic-private" not in response.text
    assert calls == []
    response = client.post(STORAGE_PATH, headers=auth(f), json=body)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["config"] == connection() and len(calls) == 1
    audit = json.dumps(f["runtime"].database.execute("select * from audit_event"), default=str)
    assert "synthetic-private" not in audit and "synthetic_pg" not in audit
    assert f["calls"] == []


@pytest.mark.parametrize("change", ["revoke", "disable", "secret"])
def test_broker_rechecks_after_secret_resolution_and_never_falls_back(broker, change):
    f, broker_service, calls, body = broker

    def mutate(config, base, revision):
        db = f["runtime"].database
        if change == "secret":
            raise KnowledgeGovernanceError("knowledge_storage_credentials_unavailable")
        if change == "revoke":
            db.execute(
                "delete from rbac_role_application_knowledge_base where knowledge_base_id=?",
                (base,),
            )
        else:
            db.execute("update \"knowledge.retrieval_resource\" set status='disabled'")
        return {
            "postgres_password": "synthetic-private-password",
            "qdrant_api_key": "synthetic-private-key",
        }

    broker_service.credentials = mutate
    response = f["bridge_client"].post(STORAGE_PATH, headers=auth(f), json=body)
    assert response.status_code != 200 and "synthetic-private" not in response.text


def test_broker_credentials_are_call_scoped_and_bound_to_configuration():
    class Client:
        def connection(self, **kwargs):
            assert kwargs["token"] == "synthetic-token"
            return {
                "knowledge_base_id": "kb",
                "resource_revision_id": "rev",
                "config": connection(),
                "credentials": {
                    "postgres_password": "synthetic-pass",
                    "qdrant_api_key": "synthetic-key",
                },
            }

    resolve = BrokerStorageCredentials(Client())
    with pytest.raises(KnowledgeGovernanceError):
        resolve(connection(), "kb", "rev")
    with storage_principal("synthetic-token"):
        assert resolve(connection(), "kb", "rev")["postgres_password"] == "synthetic-pass"
        with pytest.raises(KnowledgeGovernanceError):
            resolve(connection(), "kb", "other-rev")
    with pytest.raises(KnowledgeGovernanceError):
        resolve(connection(), "kb", "rev")


def test_qdrant_managed_credentials_never_follow_redirects_or_reach_embedding():
    calls = []

    def respond(request):
        calls.append(request)
        assert request.headers["api-key"] == "synthetic-qdrant-key"
        return httpx.Response(302, headers={"location": "https://elsewhere.invalid"})

    client = QdrantClient(
        endpoint="https://synthetic-qdrant",
        api_key="synthetic-qdrant-key",
        transport=httpx.MockTransport(respond),
    )
    try:
        with pytest.raises(ValueError):
            client.http.request("GET", "/collections")
        assert len(calls) == 1
    finally:
        client.http.close()


def test_content_adapter_sanitizes_connection_errors_and_does_not_use_platform():
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic-private-password synthetic-private-host")

    credentials = PlatformStorageCredentials(lambda _: "synthetic-private-password")
    access = ManagedContentAccess(None, credentials, database_factory=fail)
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_storage_unavailable") as captured:
        with access.open(connection(), knowledge_base_id="kb", revision_id="rev"):
            pytest.fail("must not yield platform fallback")
    assert "synthetic-private" not in str(captured.value)


@pytest.mark.parametrize("read_only", ["on", "off", None])
def test_content_adapter_checks_session_not_account_privileges_and_closes(read_only):
    from urllib.parse import parse_qs, urlsplit

    closed, calls = [], []

    class ContentDatabase:
        def execute_one(self, statement):
            calls.append(statement)
            assert statement == "select current_setting('transaction_read_only') as read_only"
            return {"read_only": read_only} if read_only else None

        def close(self):
            closed.append("database")

    database = ContentDatabase()

    def factory(dsn, **options):
        params = parse_qs(urlsplit(dsn).query)
        assert params["options"] == [
            "-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=3000"
        ]
        assert params["sslmode"] == ["require"]
        assert params["connect_timeout"] == ["5"]
        assert options == {"pool_min_size": 0, "pool_max_size": 1, "pool_timeout_seconds": 3}
        return database

    access = ManagedContentAccess(
        None,
        PlatformStorageCredentials(lambda _: "synthetic-private-password"),
        database_factory=factory,
    )
    if read_only == "on":
        with access.open(connection(), knowledge_base_id="kb", revision_id="rev") as content:
            assert content.records.database is database
    else:
        with pytest.raises(
            KnowledgeGovernanceError, match="knowledge_storage_readonly_unavailable"
        ):
            with access.open(connection(), knowledge_base_id="kb", revision_id="rev"):
                pytest.fail("non-read-only session must not yield a content handle")
    assert len(calls) == 1 and closed == ["database"]


def test_content_credentials_follow_rotation_and_disable_without_caching(governance):
    import base64
    from app.modules.platform_config.application.secrets import EncryptedDbSecretProvider
    from app.modules.platform_config.infrastructure.repository import PlatformConfigRepository

    db = governance[0]
    provider = EncryptedDbSecretProvider(
        PlatformConfigRepository(db), master_key=base64.urlsafe_b64encode(b"s" * 32).decode()
    )
    provider.create_secret(code="synthetic_pg", value="synthetic-password-first")
    provider.create_secret(code="synthetic_qdrant", value="synthetic-key")
    resolve = PlatformStorageCredentials(provider.resolve)
    assert resolve(connection(), "kb", "rev")["postgres_password"] == "synthetic-password-first"
    provider.rotate_secret(code="synthetic_pg", value="synthetic-password-rotated")
    assert resolve(connection(), "kb", "rev")["postgres_password"] == "synthetic-password-rotated"
    provider.disable_secret(code="synthetic_pg")
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_storage_credentials_unavailable"):
        resolve(connection(), "kb", "rev")


def test_search_platform_bridge_and_ones_all_read_the_selected_content_database(
    search_fixture, monkeypatch
):
    from app.modules.knowledge.infrastructure.storage import insert
    from types import SimpleNamespace

    f = search_fixture
    platform = f["runtime"].database
    remote = Database("sqlite:///:memory:")
    Migrator(remote, default_migrations_dir(), migrator_build="synthetic-content-only").run()
    try:
        with remote.unit_of_work():
            for name in (
                "source",
                "knowledge_base",
                "import_run",
                "document",
                "document_revision",
                "knowledge_base_document",
                "document_chunk_set",
                "document_chunk",
                "vector_index",
                "vector_index_item",
            ):
                for row in platform.execute(f'select * from "knowledge.{name}"'):
                    insert(remote, name, row)
        remote_vector = SimpleNamespace(
            repository=VectorRepository(remote), qdrant=f["vector"].qdrant
        )
        access = SyntheticContentAccess(remote, remote_vector)
        resources = f["resources"]
        resources.content_access = access
        f["endpoint"].resources.content_access = access
        f["bridge"].resources.content_access = access
        current = resources.list_resources()["resources"][0]
        draft = resources.save_draft(
            actor_id="user_local_admin",
            resource_id=current["id"],
            expected_revision=current["revision"],
            index_id=f["body"]["index_id"],
            storage=connection(),
        )
        verified = resources.verify_draft(
            actor_id="user_local_admin",
            resource_id=current["id"],
            expected_revision=draft["revision"],
        )
        published = resources.publish(
            actor_id="user_local_admin",
            resource_id=current["id"],
            expected_revision=verified["revision"],
        )
        protected = (
            "knowledge.source",
            "knowledge.document",
            "knowledge.vector_index",
            "knowledge.knowledge_base_document",
        )
        original_execute, original_one = platform.execute, platform.execute_one

        def execute(sql, *args, **kwargs):
            assert not any(name in sql for name in protected), (
                "content must not use the platform connection"
            )
            return original_execute(sql, *args, **kwargs)

        def execute_one(sql, *args, **kwargs):
            assert not any(name in sql for name in protected), (
                "content must not use the platform connection"
            )
            return original_one(sql, *args, **kwargs)

        monkeypatch.setattr(platform, "execute", execute)
        monkeypatch.setattr(platform, "execute_one", execute_one)
        result = search(f)
        assert result["resource_revision_id"] == published["published"]["id"]
        assert len(result["documents"]) == 1 and f["calls"] == ["POST"]
        # 同一索引在内容库中撤销，必须失效，不能读平台原来的 READY 索引兜底。
        remote.execute("update \"knowledge.vector_index\" set state='FAILED'")
        with pytest.raises(KnowledgeGovernanceError):
            search(f)
    finally:
        remote.close()
