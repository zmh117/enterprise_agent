"""Source review imports are atomic, bound, administrator-only and API-free."""

from copy import deepcopy
import json

import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.infrastructure.code_build_controller import review_digest
from app.modules.knowledge.infrastructure.code_curated_import import CodeCuratedImport
from app.modules.knowledge.infrastructure.code_repository import CodeRepository, decoded
from app.modules.knowledge.infrastructure.storage import insert, table
from backend.tests.test_code_knowledge import (
    database as database_fixture,
    fixture,
    _freeze_test_source,
)

database = database_fixture


class Admin:
    def __init__(self):
        self.events = []

    def require_admin(self, actor_id):
        if actor_id != "reviewer":
            raise PermissionError("denied")

    def record(self, event, **kwargs):
        self.events.append((event, kwargs))


def setup_review(db, tmp_path):
    repo = CodeRepository(db)
    ids = repo.register(code="curated", base_code="curated", config={})
    source_id, root = _freeze_test_source(tmp_path, repo, ids["source_id"])
    source = db.execute_one(
        f"select * from {table(db, 'code_source_snapshot')} where id=?", (source_id,)
    )
    build = repo.new_build(ids["source_id"], source_id, purpose="baseline", configuration={})
    scope = dict(entry_ids=["factory.work_order.publish"], allowed_prefixes=["set_server"])
    insert(
        db,
        "code_unit",
        dict(
            id="original-unit",
            build_id=build["build_id"],
            unit_key="publish",
            scope_json=scope,
            state="FAILED",
            result_json={},
            artifact_json={},
            created_at=now(),
            updated_at=now(),
        ),
    )
    db.execute(
        f"update {table(db, 'code_build')} set stage='FAILED',active=0 where id=?",
        (build["build_id"],),
    )
    package, _ = fixture(source_snapshot_id=source_id)
    package["manifest.json"]["source_ref"] = decoded(source["source_ref"])
    manifest = json.loads((root / source_id / "manifest.json").read_text())
    package["evidence.jsonl"][0]["file_id"] = manifest["files"][0]["file_id"]
    package["evidence.jsonl"][0]["excerpt_hash"] = None
    units = db.execute(
        f"select * from {table(db, 'code_unit')} where build_id=?", (build["build_id"],)
    )
    args = dict(
        actor_id="reviewer",
        original_build_id=build["build_id"],
        expected_digest=review_digest(units),
        review_reference="review-20261106",
    )
    importer = CodeCuratedImport(db, Admin(), root)
    return importer, args, dict(contract_version="code-business/v2", entries=package), ids


def test_review_import_roundtrip_idempotent_no_jobs_or_publication(database, tmp_path):
    importer, args, authoring, ids = setup_review(database, tmp_path)
    raw = json.dumps(authoring).encode()
    result = importer.import_package(**args, raw=raw)
    assert result["created"] and result["machine_valid"]
    assert result["business_verified"] is False
    repeat = importer.import_package(**args, raw=raw)
    assert repeat["snapshot_id"] == result["snapshot_id"] and not repeat["created"]
    build = database.execute_one(
        f"select * from {table(database, 'code_build')} where id=?", (result["build_id"],)
    )
    assert build["stage"] == "VALIDATING"
    config = decoded(build["configuration_json"])
    assert config["origin_kind"] == "source_review" and config["reviewer_id"] == "reviewer"
    assert config["original_build_id"] == args["original_build_id"]
    unit = database.execute_one(
        f"select * from {table(database, 'code_unit')} where id=?", (result["unit_id"],)
    )
    assert unit["job_id"] is None
    assert len(importer.admin.events) == 1
    assert (
        database.execute_one(
            f"select count(*) n from {table(database, 'code_transition')} where snapshot_id=?",
            (result["snapshot_id"],),
        )["n"]
        == 1
    )
    assert importer.repo.binding(ids["source_id"])["active_snapshot_id"] is None
    assert not database.execute("pragma foreign_key_check")


@pytest.mark.parametrize(
    "mutation,error",
    [
        (
            lambda a: a["entries"]["manifest.json"].update(source_snapshot_id="elsewhere"),
            "binding_mismatch",
        ),
        (lambda a: a["entries"]["evidence.jsonl"][0].update(raw_hash="f" * 64), "digest_mismatch"),
        (
            lambda a: a["entries"]["knowledge.jsonl"][0]["transition"]["to_state"].update(
                mode="state", state_key="absent"
            ),
            "target_missing",
        ),
    ],
)
def test_invalid_import_rolls_back_every_row(database, tmp_path, mutation, error):
    importer, args, authoring, _ = setup_review(database, tmp_path)
    before = {
        t: database.execute(f"select * from {table(database, t)}")
        for t in ("code_build", "code_snapshot", "document", "code_transition")
    }
    mutation(authoring)
    with pytest.raises(CodeKnowledgeError, match=error):
        importer.import_package(**args, raw=json.dumps(authoring).encode())
    assert before == {t: database.execute(f"select * from {table(database, t)}") for t in before}


def test_review_rejects_stale_original_and_unprivileged_actor(database, tmp_path):
    importer, args, authoring, _ = setup_review(database, tmp_path)
    raw = json.dumps(authoring).encode()
    with pytest.raises(PermissionError):
        importer.import_package(**(args | dict(actor_id="reader")), raw=raw)
    with pytest.raises(CodeKnowledgeError, match="candidate_changed"):
        importer.import_package(**(args | dict(expected_digest="f" * 64)), raw=raw)
    database.execute(
        f"update {table(database, 'code_build')} set stage='EXTRACTING',active=1 where id=?",
        (args["original_build_id"],),
    )
    with pytest.raises(CodeKnowledgeError, match="not_stopped"):
        importer.import_package(**args, raw=raw)


def test_state_dimensions_share_object_but_not_raw_state_namespace(database):
    from backend.tests.test_code_state_machines import new_build

    repo, _, source, build = new_build(database)
    package, _ = fixture(source_snapshot_id=source)
    second = deepcopy(package["knowledge.jsonl"][0])
    second["business_key"] = "factory.work_order.start.request"
    second["transition"].update(
        event_key=second["business_key"], machine_key="factory.work_order.execution"
    )
    second["states"][0]["key"] = "runtime_created"
    second["transition"]["from_state"]["state_keys"] = ["runtime_created"]
    package["knowledge.jsonl"].append(second)
    package["coverage.json"]["entries"].append(
        dict(
            entry_id="factory.work_order.start",
            role="backend",
            status="analyzed",
            knowledge_keys=[second["business_key"]],
            unknowns=[],
        )
    )
    repo.store_candidate(build["snapshot_id"], package)
    assert (
        database.execute_one(f"select count(*) n from {table(database, 'code_object')}")["n"] == 1
    )
    assert database.execute_one(f"select count(*) n from {table(database, 'code_state')}")["n"] == 2
    second["transition"]["machine_key"] = "factory.work_order.configuration"
    with pytest.raises(CodeKnowledgeError, match="event_machine_mismatch"):
        repo.store_candidate(build["snapshot_id"], package)
