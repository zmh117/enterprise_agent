"""Container-side synthetic acceptance, not an administrative deployment entrypoint."""

from dataclasses import replace
from contextlib import contextmanager
import base64
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

import httpx
import psycopg

from app.bootstrap import build_test_container
from app.modules.identity.application.principal_jwt import PrincipalSigningKey, PrincipalTokenIssuer
from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.domain.chunking import DEFAULT_PROFILE
from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository
from app.modules.knowledge.infrastructure.job_access import KnowledgeJobGate, KNOWLEDGE_TOOLS
from app.modules.knowledge.infrastructure.vector_clients import EmbeddingClient, QdrantClient
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from backend.tests.support.ones_provider import MockOnesSettings
from backend.tests.support.runtime import test_settings
from backend.tests.test_knowledge_chunks import import_rows
from backend.tests.test_knowledge_import import export_row
from backend.tests.test_ones_mcp_runtime import _fixture
from services.knowledge_mcp_server.database_policy import grant_reader

STATE = Path("/fixture")
DSN = "postgresql://postgres@postgres:5432/knowledge_acceptance"
BASE_URL = "http://api-server:8000"
ROOT = "/api/platform/knowledge"
QUERY = "仅合成容器验收查询，不应进入审计"


def settings():
    return replace(
        test_settings(),
        database_dsn=DSN,
        environment="test",
        app_config_master_key=base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("="),
    )


def wait_http(url):
    until = time.monotonic() + 60
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < until:
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
    raise AssertionError("synthetic service did not become healthy: " + url)


def seed():  # noqa: PLR0915
    until = time.monotonic() + 45
    while True:
        try:
            with psycopg.connect(DSN, autocommit=True) as connection:
                connection.execute("CREATE DATABASE without_knowledge")
                connection.execute("CREATE DATABASE knowledge_deadline_test")
            break
        except psycopg.OperationalError:
            if time.monotonic() > until:
                raise
            time.sleep(0.3)
    other = Database("postgresql://postgres@postgres:5432/without_knowledge")
    try:
        Migrator(other, default_migrations_dir(), migrator_build="synthetic-container").run()
    finally:
        other.close()
    ordinary = build_test_container(
        replace(settings(), database_dsn="postgresql://postgres@postgres:5432/without_knowledge"),
        migrate=False,
        seed=True,
    )
    ordinary.database.close()
    mock = MockOnesSettings()

    def configure(runtime, selection):
        detail, listing = export_row()
        number = mock.config.tasks[0]["number"]
        detail["uuid"] = listing["uuid"] = f"MOCK-ONES-TASK-{number}"
        detail["number"] = listing["number"] = number
        listing["project"]["uuid"] = mock.config.project_uuid
        with tempfile.TemporaryDirectory() as path:
            import_rows(runtime.database, Path(path), [(detail, listing)])
        runtime.database.execute(
            "insert into rbac_role_application_knowledge_base(application_access_id,knowledge_base_id,created_at) "
            "select a.id,k.id,CURRENT_TIMESTAMP from rbac_role_application_access a cross join knowledge.knowledge_base k where a.application_id=?",
            (selection["application_id"],),
        )

    key = PrincipalSigningKey.from_file(str(STATE / "private.pem"), environment="test")
    with (
        patch("backend.tests.support.runtime.test_settings", settings),
        patch("backend.tests.test_ones_mcp_runtime._signing_key", lambda: key),
    ):
        fixture = _fixture(
            capabilities=("ones_work_item_search", "ones_get_work_item_detail", *KNOWLEDGE_TOOLS),
            before_job=configure,
            current_agent_envelope=True,
        )
    runtime = fixture["runtime"]
    try:
        chunks = ChunkService(ChunkRepository(runtime.database)).run(
            knowledge_base_code="synthetic_base", expected_count=1, commit=True
        )["counts"]["chunks"]
        wait_http("http://knowledge-embedding:8096/ready")
        wait_http("http://knowledge-qdrant:6333/healthz")
        embedding, qdrant = EmbeddingClient(), QdrantClient()
        try:
            vector = VectorService(VectorRepository(runtime.database), embedding, qdrant)
            snapshot = vector.repository.snapshot(
                vector.repository.scope("synthetic_base"), DEFAULT_PROFILE.fingerprint, 1, chunks
            )
            vector.build("synthetic-container-v1", snapshot)
            index = vector.repository.get("synthetic-container-v1")
        finally:
            embedding.http.close()
            qdrant.http.close()
        runtime.platform_config_service.secret_provider.create_secret(
            code="synthetic_content", value="synthetic-only-content", actor_id="user_local_admin"
        )
        grant_reader(runtime.database, "synthetic-only-reader-password")
        (STATE / "facts.json").write_text(
            json.dumps(
                {
                    "job_id": fixture["job"].id,
                    "knowledge_base_id": snapshot["knowledge_base_id"],
                    "index_id": index["id"],
                    "chunks": chunks,
                }
            )
        )
    finally:
        runtime.database.close()


@contextmanager
def management():
    client = httpx.Client(base_url=BASE_URL, trust_env=False, timeout=30)
    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": "111111111111"}
    )
    assert response.status_code == 200, "synthetic admin login failed"
    csrf = client.cookies.get("enterprise_agent_csrf")
    assert csrf
    client.headers.update({"origin": BASE_URL, "x-csrf-token": csrf})
    try:
        yield client
    finally:
        client.close()


def data(response):
    assert response.status_code == 200, f"HTTP {response.status_code}: {response.text[:800]}"
    return response.json()


def runtime_and_headers(facts):
    runtime = build_test_container(settings(), migrate=False, seed=False)
    gate = KnowledgeJobGate(
        runtime.database, runtime.mcp_tool_snapshot_service, runtime.business_authorization_service
    )
    issuer = PrincipalTokenIssuer(
        runtime.database,
        runtime.mcp_tool_snapshot_service,
        runtime.business_authorization_service,
        PrincipalSigningKey.from_file(str(STATE / "private.pem"), environment="test"),
        runtime.audit_service,
        knowledge_job_gate=gate,
    )
    job = runtime.database.execute_one("select * from agent_job where id=?", (facts["job_id"],))
    headers = {
        "authorization": "Bearer "
        + issuer.issue_business_mcp_for_job(job_id=job["id"], server_code="knowledge-mcp"),
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": "2025-06-18",
        "x-job-id": job["id"],
        "x-app-user-id": job["internal_user_id"],
        "x-project-code": job["project_code"],
        "x-agent-publication-id": job["agent_publication_id"],
        "x-application-publication-id": job["business_application_publication_id"],
        "x-invocation-id": f"{job['id']}.attempt-{job['retry_count']}",
        "x-correlation-id": "job:" + job["id"],
    }
    return runtime, headers, issuer


def rpc(headers, name="knowledge_search", arguments=None, method="tools/call"):
    with httpx.Client(trust_env=False, timeout=125) as client:
        response = client.post(
            "http://knowledge-mcp:9108/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": {"name": name, "arguments": arguments or {}}
                if method == "tools/call"
                else arguments or {},
            },
        )
    result = data(response)["result"]
    assert QUERY not in response.text
    assert "embedding_text" not in response.text and "evidence_text" not in response.text
    return result


def positive(headers, facts):
    result = rpc(
        headers, arguments={"knowledge_base_id": facts["knowledge_base_id"], "query": QUERY}
    )
    assert not result.get("isError"), result.get("structuredContent")
    assert len(result["structuredContent"]["documents"]) == 1
    return result["structuredContent"]["documents"][0]


def verify(*, after_restart=False):  # noqa: PLR0915
    for url in (
        BASE_URL + "/api/health",
        "http://ones-mcp:9104/health",
        "http://knowledge-mcp:9108/health",
    ):
        wait_http(url)
    facts = json.loads((STATE / "facts.json").read_text())
    if not after_restart:
        with management() as client:
            resource = data(
                client.post(
                    ROOT + "/resources",
                    json={
                        "knowledge_base_id": facts["knowledge_base_id"],
                        "code": "synthetic-container",
                        "name": "合成容器知识库",
                    },
                )
            )
            path = ROOT + "/resources/" + resource["id"]
            # Exercise the published-connection broker as well as the readability bridge.
            storage = {
                "postgres": {
                    "mode": "external",
                    "host": "postgres",
                    "port": 5432,
                    "database": "knowledge_acceptance",
                    "username": "postgres",
                    "sslmode": "disable",
                    "password_ref": "secret://platform/synthetic_content",
                },
                "qdrant": {"url": "http://knowledge-qdrant:6333", "api_key_ref": ""},
            }
            draft = data(
                client.put(
                    path + "/draft",
                    json={
                        "expected_revision": resource["revision"],
                        "index_id": facts["index_id"],
                        "storage": storage,
                    },
                )
            )
            assert draft["draft"]["binding_id"] is None
            checked = data(
                client.post(path + "/verify", json={"expected_revision": draft["revision"]})
            )
            published = data(
                client.post(path + "/publish", json={"expected_revision": checked["revision"]})
            )
            assert published["published"]
            facts["resource_id"] = resource["id"]
            (STATE / "facts.json").write_text(json.dumps(facts))
    runtime, headers, issuer = runtime_and_headers(facts)
    try:
        init = rpc(
            headers,
            method="initialize",
            arguments={
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "synthetic", "version": "1"},
            },
        )
        assert init["serverInfo"]["name"] == "Enterprise Knowledge MCP"
        catalog = rpc(headers, method="tools/list")
        assert {tool["name"] for tool in catalog["tools"]} == set(KNOWLEDGE_TOOLS)
        listing = rpc(headers, name="knowledge_list_bases")
        assert not listing.get("isError"), listing.get("structuredContent")
        hit = positive(headers, facts)
        # Actual ONES MCP details, with a separately issued audience; no direct provider bypass.
        ones_headers = {
            **headers,
            "authorization": "Bearer "
            + issuer.issue_business_mcp_for_job(job_id=facts["job_id"], server_code="ones-mcp"),
        }
        with httpx.Client(trust_env=False, timeout=30) as client:
            response = client.post(
                "http://ones-mcp:9104/mcp",
                headers=ones_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "ones_get_work_item_detail",
                        "arguments": {"work_item_uuid": hit["work_item_uuid"]},
                    },
                },
            )
        assert not data(response)["result"].get("isError"), "synthetic ONES detail failed"
        if after_restart:
            return
        args = {"knowledge_base_id": facts["knowledge_base_id"], "query": QUERY}
        # Valid ONES token must not authenticate to Knowledge MCP.
        assert rpc(ones_headers, arguments=args)["isError"]
        for mode in ("403", "500"):
            (STATE / "provider-mode").write_text(mode)
            result = rpc(headers, arguments=args)
            if mode == "403":
                assert not result.get("isError") and result["structuredContent"]["documents"] == []
            else:
                assert result["isError"] and "documents" not in result["structuredContent"]
        (STATE / "provider-mode").write_text("allow")
        positive(headers, facts)
        grants = runtime.database.execute("select * from rbac_role_application_knowledge_base")
        runtime.database.execute("delete from rbac_role_application_knowledge_base")
        assert rpc(headers, arguments=args)["isError"]
        for row in grants:
            runtime.database.execute(
                "insert into rbac_role_application_knowledge_base(application_access_id,knowledge_base_id,created_at) values(?,?,?)",
                (row["application_access_id"], row["knowledge_base_id"], row["created_at"]),
            )
        positive(headers, facts)
        with management() as client:
            path = ROOT + "/resources/" + facts["resource_id"]
            resource = next(
                row
                for row in data(client.get(ROOT + "/resources"))["resources"]
                if row["id"] == facts["resource_id"]
            )
            disabled = data(
                client.post(
                    path + "/status",
                    json={"expected_revision": resource["revision"], "status": "disabled"},
                )
            )
            assert rpc(headers, arguments=args)["isError"]
            data(
                client.post(
                    path + "/status",
                    json={"expected_revision": disabled["revision"], "status": "enabled"},
                )
            )
        positive(headers, facts)
        audit = json.dumps(runtime.database.execute("select * from audit_event"), default=str)
        assert QUERY not in audit and headers["authorization"][7:] not in audit
        assert (
            runtime.database.execute_one(
                "select count(*) as n from mcp_operation_audit where status='SUCCEEDED'"
            )["n"]
            > 0
        )
    finally:
        runtime.database.close()


def without():
    wait_http("http://api-without-knowledge:8000/api/health")
    with httpx.Client(trust_env=False, timeout=10) as client:
        health = data(client.get("http://api-without-knowledge:8000/api/health"))
        assert health["status"] == "ok"
        response = client.post(
            "http://api-without-knowledge:8000/api/auth/login",
            json={"username": "admin", "password": "111111111111"},
        )
        assert response.status_code == 200, "ordinary login requires no knowledge services"
        assert client.get("http://api-without-knowledge:8000/api/auth/me").status_code == 200
        response = client.post(
            "http://api-without-knowledge:8000/api/internal/knowledge/storage-connection", json={}
        )
        assert response.status_code in {401, 403, 404, 503}


if __name__ == "__main__":
    stage = sys.argv[1]
    {
        "seed": seed,
        "verify": verify,
        "restart": lambda: verify(after_restart=True),
        "without": without,
    }[stage]()
    print("SYNTHETIC_KNOWLEDGE_CONTAINER_PASS " + stage)
