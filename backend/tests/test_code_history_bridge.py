"""Real signed internal HTTP boundaries with synthetic rules and no network/model work."""

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pathlib import Path

from app.modules.identity.application.principal_jwt import PrincipalJwks, PrincipalTokenVerifier
from app.modules.identity.application.service_principal import (
    ServicePrincipalTokenIssuer,
    KnowledgeServicePrincipalVerifier,
)
from app.modules.knowledge.api.readability_controller import build_knowledge_readability_router
from app.modules.knowledge.infrastructure.code_history_bridge import CodeHistoryBridge
from app.modules.knowledge.infrastructure.code_collection_controller import CodeCollectionController
from app.modules.knowledge.infrastructure.readability_bridge import PlatformOnesReadabilityGateway
from app.modules.knowledge.infrastructure.storage import table
from app.shared.code_knowledge_tool_contracts import CODE_HISTORY_PATH
from backend.tests.test_code_queries import code_mcp as code_mcp_fixture

code_mcp = code_mcp_fixture


@pytest.fixture
def bridge(code_mcp):
    f = code_mcp
    issuer = f["query_issuer"]
    keys = PrincipalJwks.from_dict(issuer.signing_key.public_jwks())
    credentials = {
        "knowledge-mcp": "synthetic-knowledge-bootstrap-" + "k" * 48,
        "file-worker": "synthetic-file-bootstrap-" + "f" * 48,
        "file-processing-worker": "synthetic-process-bootstrap-" + "p" * 48,
        "delivery-worker": "synthetic-delivery-bootstrap-" + "d" * 48,
    }
    services = ServicePrincipalTokenIssuer(
        signing_key=issuer.signing_key,
        bootstrap_credentials=credentials,
        audit_service=f["runtime"].audit_service,
    )
    gateway = PlatformOnesReadabilityGateway(
        KnowledgeServicePrincipalVerifier(keys),
        PrincipalTokenVerifier(keys, expected_audience="knowledge-mcp"),
        issuer,
        f["query_access"].gate,
        instance_code="synthetic",
    )
    handler = CodeHistoryBridge(
        f["runtime"].database,
        gateway,
        f["query_access"],
        f["query_resources"],
        f["runtime"].audit_service,
    )
    app = FastAPI()
    app.state.container = SimpleNamespace(code_history_bridge=handler)
    app.include_router(build_knowledge_readability_router())
    with TestClient(app, base_url="http://api-server:8000") as client:
        yield {
            **f,
            "client": client,
            "auth": {
                "authorization": "Bearer "
                + services.issue(credentials["knowledge-mcp"]).access_token,
                "x-knowledge-principal": "Bearer " + f["knowledge_token"],
            },
            "resource_revision_id": f["query_resources"]
            .resolve(f["knowledge_base_id"])
            .revision_id,
        }


def version(f, revision=99):
    return {
        "action": "version",
        "knowledge_base_id": f["knowledge_base_id"],
        "resource_revision_id": f["resource_revision_id"],
        "revision": revision,
    }


def test_version_demand_requires_policy_is_idempotent_and_does_not_activate(bridge):
    f = bridge
    db = f["runtime"].database
    assert (
        f["client"].post(CODE_HISTORY_PATH, json=version(f), headers=f["auth"]).json()["status"]
        == "BUILD_REQUIRED"
    )
    db.execute(
        f"update {table(db, 'code_binding')} set enabled=1,demand_enabled=1 where source_id=?",
        (f["source_id"],),
    )
    first = f["client"].post(CODE_HISTORY_PATH, json=version(f), headers=f["auth"])
    assert first.status_code == 200 and first.json()["status"] == "BUILD_PENDING"
    assert (
        first.json()
        == f["client"].post(CODE_HISTORY_PATH, json=version(f), headers=f["auth"]).json()
    )
    assert db.execute_one(f"select count(*) as n from {table(db, 'code_demand')}")["n"] == 1
    assert f["repo"].binding(f["source_id"])["active_snapshot_id"] is None


def test_history_persists_nonmonotonic_proof_and_missing_middle_progress(bridge):
    f = bridge
    db = f["runtime"].database
    request = {
        "action": "history",
        "resource_revision_id": f["resource_revision_id"],
        "arguments": {
            "knowledge_base_id": f["knowledge_base_id"],
            "knowledge_id": f["knowledge_id"],
            "mode": "history",
            "from_version": {"kind": "svn", "revision": 100},
            "to_version": {"kind": "svn", "revision": 102},
        },
    }
    result = f["client"].post(CODE_HISTORY_PATH, json=request, headers=f["auth"])
    assert result.status_code == 200
    assert result.json()["complete"] and len(result.json()["changes"]) == 2
    row = db.execute_one(f"select comparison_json from {table(db, 'code_history_check')}")
    assert json.loads(row["comparison_json"])["checked_revisions"] == [101, 102]
    db.execute(
        f"update {table(db, 'code_snapshot')} set state='UNAVAILABLE' where id=?",
        (f["snapshots"][101],),
    )
    result = f["client"].post(CODE_HISTORY_PATH, json=request, headers=f["auth"])
    assert result.status_code == 200 and not result.json()["complete"]
    assert not json.loads(
        db.execute_one(f"select comparison_json from {table(db, 'code_history_check')}")[
            "comparison_json"
        ]
    )["complete"]


def test_compare_requests_missing_exact_endpoint_without_creating_history_proof(bridge):
    f = bridge
    db = f["runtime"].database
    db.execute(
        f"update {table(db, 'code_binding')} set enabled=1,demand_enabled=1 where source_id=?",
        (f["source_id"],),
    )
    request = {
        "action": "compare",
        "resource_revision_id": f["resource_revision_id"],
        "arguments": {
            "knowledge_base_id": f["knowledge_base_id"],
            "knowledge_id": f["knowledge_id"],
            "from_version": {"kind": "svn", "revision": 99},
            "to_version": {"kind": "svn", "revision": 102},
        },
    }
    response = f["client"].post(CODE_HISTORY_PATH, json=request, headers=f["auth"])
    assert response.status_code == 200
    assert response.json()["from_version"]["status"] == "BUILD_PENDING"
    assert response.json()["to_version"]["status"] == "READY"
    assert db.execute_one(f"select count(*) as n from {table(db, 'code_demand')}")["n"] == 1
    assert db.execute_one(f"select count(*) as n from {table(db, 'code_history_check')}")["n"] == 0


def test_prebaseline_ledger_is_collected_without_moving_development_cursor(bridge):
    f = bridge
    db = f["runtime"].database
    db.execute(
        f"update {table(db, 'code_binding')} set collected_from_revision=102 where source_id=?",
        (f["source_id"],),
    )
    request = {
        "action": "history",
        "resource_revision_id": f["resource_revision_id"],
        "arguments": {
            "knowledge_base_id": f["knowledge_base_id"],
            "knowledge_id": f["knowledge_id"],
            "mode": "history",
            "from_version": {"kind": "svn", "revision": 100},
            "to_version": {"kind": "svn", "revision": 102},
        },
    }
    assert (
        not f["client"]
        .post(CODE_HISTORY_PATH, json=request, headers=f["auth"])
        .json()["ledger_complete"]
    )

    def commits(*, after, target, through):
        assert (after, target, through) == (100, 102, 102)
        return [{"revision": 101, "paths": []}, {"revision": 102, "paths": []}]

    collector = CodeCollectionController(db, SimpleNamespace(), Path("/unused-synthetic-source"))
    source = SimpleNamespace(commits=commits, expected_uuid="synthetic")
    assert collector._history_ledger(f["repo"].binding(f["source_id"]), source)
    assert not collector._history_ledger(f["repo"].binding(f["source_id"]), source)
    result = f["client"].post(CODE_HISTORY_PATH, json=request, headers=f["auth"])
    assert result.status_code == 200 and result.json()["complete"]
    assert len(result.json()["changes"]) == 2
    assert f["repo"].binding(f["source_id"])["collected_from_revision"] == 102


@pytest.mark.parametrize(
    "mutate", ["missing_service", "cookie", "origin", "wrong_base", "wrong_resource", "raw_command"]
)
def test_bridge_rejects_untrusted_routes_and_inputs_without_queuing(bridge, mutate):
    f = bridge
    body, headers = version(f), dict(f["auth"])
    if mutate == "missing_service":
        del headers["authorization"]
    elif mutate in {"cookie", "origin"}:
        headers[mutate] = "synthetic"
    elif mutate == "wrong_base":
        body["knowledge_base_id"] = "another-base"
    elif mutate == "wrong_resource":
        body["resource_revision_id"] = "stale-resource"
    else:
        body["command"] = "svn update"
    result = f["client"].post(CODE_HISTORY_PATH, json=body, headers=headers)
    assert result.status_code >= 400
    db = f["runtime"].database
    assert db.execute_one(f"select count(*) as n from {table(db, 'code_demand')}")["n"] == 0
    audit = json.dumps(db.execute("select * from audit_event"), default=str)
    assert (
        f["knowledge_token"] not in audit
        and headers.get("authorization", "not-a-token") not in audit
    )
