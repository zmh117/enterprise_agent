"""Administrative review, durable recovery and HTTP boundaries; synthetic source only."""

import json
from types import SimpleNamespace

import pytest

from app.modules.knowledge.infrastructure.code_build_controller import CodeBuildController
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.storage import table
from backend.tests.test_code_knowledge import code_job_runtime as code_job_fixture, fixture
from backend.tests.test_knowledge_api import managed as managed_fixture
from backend.tests.test_unified_identity_rbac import login, csrf_headers

code_job_runtime = code_job_fixture
managed = managed_fixture


def validation_candidate(f):
    runtime, *_, source, lease, source_root = f
    db = runtime.database
    build = db.execute_one(f"select * from {table(db, 'code_build')}")
    result = dict(
        machine_valid=True,
        activation_blocked=False,
        business_verified=False,
        knowledge_count=1,
        evidence_count=1,
        relation_count=0,
        dependency_requests=[],
    )
    db.execute(
        f"update {table(db, 'code_unit')} set state='VALIDATED',result_json=?",
        (json.dumps(result),),
    )
    ops = runtime.knowledge_services.code_operations()
    package, _ = fixture(source_snapshot_id=source)
    ops.repo.store_candidate(build["snapshot_id"], package)
    controller = CodeBuildController(
        db, SimpleNamespace(), SimpleNamespace(), source_root=source_root
    )
    controller.leases[build["id"]] = lease
    assert controller.step(build["id"])["state"] == "VALIDATING"
    assert controller.step(build["id"])["state"] == "BUSINESS_REVIEW_REQUIRED"
    return ops, controller, build


def test_review_reads_whole_candidate_and_requires_exact_units_and_processing(code_job_runtime):
    ops, controller, build = validation_candidate(code_job_runtime)
    page = ops.details(build["id"])
    assert page["records"][0]["knowledge"]["guard"]["expression"] == "a is not empty"
    assert page["records"][0]["evidence"] and not page["has_more"]
    processing = digest(json.loads(build["configuration_json"]))
    inputs = dict(
        actor_id="user_local_admin",
        build_id=build["id"],
        review_reference="independent-review-1",
        processing_hash=processing,
        candidate_digest=page["review_digest"],
        checked_unit_ids=["code-unit-test"],
    )
    for changes in ({"checked_unit_ids": ["wrong-unit"]}, {"processing_hash": "0" * 64}):
        with pytest.raises(CodeKnowledgeError):
            ops.review(**(inputs | changes))
    review = ops.review(**inputs)
    assert review["validation"]["business_verified"]
    assert controller.step(build["id"])["state"] == "INDEXING"
    assert (
        ops.snapshot()["builds"][0]["validation"]["business_review"]["reference"]
        == "independent-review-1"
    )


def test_review_invalidated_if_unit_result_changes(code_job_runtime):
    ops, controller, build = validation_candidate(code_job_runtime)
    ops.review(
        actor_id="user_local_admin",
        build_id=build["id"],
        review_reference="review-1",
        processing_hash=digest(json.loads(build["configuration_json"])),
        candidate_digest=ops.details(build["id"])["review_digest"],
        checked_unit_ids=["code-unit-test"],
    )
    db = ops.db
    row = db.execute_one(f"select result_json from {table(db, 'code_unit')}")
    value = json.loads(row["result_json"])
    value["knowledge_count"] = 2
    db.execute(f"update {table(db, 'code_unit')} set result_json=?", (json.dumps(value),))
    assert controller.step(build["id"])["state"] == "BUSINESS_REVIEW_REQUIRED"


def test_retry_keeps_successful_artifacts_and_build_identity(code_job_runtime):
    ops, controller, build = validation_candidate(code_job_runtime)
    db = ops.db
    before = db.execute(f"select * from {table(db, 'code_unit')}")
    db.execute(
        f"update {table(db, 'code_build')} set stage='FAILED',active=0,error_code='code_build_dependency_unavailable'"
    )
    result = ops.retry(actor_id="user_local_admin", build_id=build["id"])
    assert result == {"build_id": build["id"], "stage": "VALIDATING"}
    assert db.execute(f"select * from {table(db, 'code_unit')}") == before
    with pytest.raises(CodeKnowledgeError, match="not_retryable"):
        ops.retry(actor_id="user_local_admin", build_id=build["id"])


def test_start_uses_registered_ids_and_frozen_application(code_job_runtime):
    runtime, svc, _, _, app_pub, _, source, _, _ = code_job_runtime
    ops = runtime.knowledge_services.code_operations()
    row = runtime.database.execute_one(
        f"select source_id from {table(runtime.database, 'code_binding')}"
    )
    kwargs = dict(
        actor_id="user_local_admin",
        source_id=row["source_id"],
        source_snapshot_id=source,
        application_publication_id=app_pub["id"],
        service_account_id=svc["id"],
    )
    first = ops.start(**kwargs)
    assert first == ops.start(**kwargs)
    with pytest.raises(CodeKnowledgeError, match="configuration_unavailable"):
        ops.start(**(kwargs | {"service_account_id": "user_local_admin"}))
    config = json.loads(ops.builds.get(first["build_id"])["configuration_json"])
    assert (
        config["application_publication_id"] == app_pub["id"]
        and config["contract_version"] == "code-business/v1"
    )


def test_independent_plan_requires_verified_source_and_cas_without_activating(code_job_runtime):
    runtime, svc, _, _, app_pub, _, _, _, _ = code_job_runtime
    ops = runtime.knowledge_services.code_operations()
    db = runtime.database
    binding = db.execute_one(f"select * from {table(db, 'code_binding')}")
    inputs = dict(
        actor_id="user_local_admin",
        source_id=binding["source_id"],
        expected_plan_revision=0,
        application_publication_id=app_pub["id"],
        service_account_id=svc["id"],
        schedule_enabled=True,
        demand_enabled=False,
    )
    with pytest.raises(CodeKnowledgeError, match="svn_unverified"):
        ops.configure_plan(**inputs)
    config = {**json.loads(binding["config_json"]), "svn_verified": True}
    db.execute(f"update {table(db, 'code_binding')} set config_json=?", (json.dumps(config),))
    result = ops.configure_plan(**inputs)
    assert result["plan_revision"] == 1 and result["next_run_at"]
    with pytest.raises(CodeKnowledgeError, match="schedule_changed"):
        ops.configure_plan(**inputs)
    assert ops.repo.binding(binding["source_id"])["active_snapshot_id"] is None
    assert (
        ops.request_version(
            actor_id="user_local_admin", source_id=binding["source_id"], revision=101
        )["status"]
        == "BUILD_PENDING"
    )
    assert (
        ops.configure_plan(**(inputs | {"expected_plan_revision": 1, "schedule_enabled": False}))[
            "next_run_at"
        ]
        is None
    )


def test_missing_parent_knowledge_cannot_be_silently_dropped_or_reviewed(code_job_runtime):
    ops, controller, build = validation_candidate(code_job_runtime)
    db = ops.db
    parent = ops.repo.new_build(
        build["source_id"],
        build["source_snapshot_id"],
        purpose="history",
        configuration={"synthetic": "parent"},
    )
    package, _ = fixture(source_snapshot_id=build["source_snapshot_id"])
    package["knowledge.jsonl"][0]["business_key"] = "factory.work_order.old_rule"
    ops.repo.store_candidate(parent["snapshot_id"], package)
    db.execute(
        f"update {table(db, 'code_build')} set parent_snapshot_id=? where id=?",
        (parent["snapshot_id"], build["id"]),
    )
    assert controller.step(build["id"])["state"] == "BUSINESS_REVIEW_REQUIRED"
    current = ops.snapshot()["builds"]
    target = next(row for row in current if row["id"] == build["id"])
    assert target["validation"]["activation_blocked"]
    assert target["validation"]["continuity"]["missing_keys"] == ["factory.work_order.old_rule"]
    with pytest.raises(CodeKnowledgeError, match="validation_incomplete"):
        ops.review(
            actor_id="user_local_admin",
            build_id=build["id"],
            review_reference="independent-review",
            processing_hash=target["processing_hash"],
            candidate_digest=ops.details(build["id"])["review_digest"],
            checked_unit_ids=["code-unit-test"],
        )


def test_management_api_requires_admin_csrf_and_rejects_paths(managed):
    _, client, *_ = managed
    root = "/api/platform/knowledge/code"
    assert client.get(root).status_code in (401, 403)
    auth = csrf_headers(login(client))
    assert client.get(root).status_code == 200
    assert client.post(root + "/builds", json={}).status_code == 403
    response = client.post(
        root + "/builds",
        headers=auth,
        json={
            "source_id": "registered",
            "source_snapshot_id": "admitted",
            "application_publication_id": "published",
            "service_account_id": "service",
            "source_root": "/arbitrary/host/path",
        },
    )
    assert response.status_code == 400
