"""Independent semantic, relational and deletion-boundary checks, not MES acceptance."""

from copy import deepcopy
import json

import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_history import compare_records
from app.modules.knowledge.domain.code_package import verify_candidate
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_candidate_retirement import CodeCandidateRetirement
from app.modules.knowledge.infrastructure.code_repository import CodeRepository, knowledge_id
from app.modules.knowledge.infrastructure.storage import table
from backend.tests.test_code_knowledge import database as database_fixture, fixture

database = database_fixture


def verify(package, sources, **kwargs):
    return verify_candidate(
        package,
        expected_manifest=package["manifest.json"],
        sources=sources,
        expected_entries={"factory.work_order.publish"},
        **kwargs,
    )


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda r: r.update(object_key="wo.work_order"), "object_identity_unknown"),
        (lambda r: r.update(business_key="factory.work_order.start"), "identity_outside_scope"),
        (
            lambda r: r["transition"].update(machine_key="group.application.lifecycle"),
            "machine_object_mismatch",
        ),
        (
            lambda r: r["transition"].update(event_key="factory.work_order.start.execute"),
            "event_object_mismatch",
        ),
        (lambda r: r["transition"]["from_state"].update(state_keys=["absent"]), "source_missing"),
        (
            lambda r: r["transition"]["to_state"].update(mode="state", state_key="absent"),
            "target_missing",
        ),
        (
            lambda r: r["transition"]["failures"][0].update(retained_action_keys=["absent"]),
            "failure_action_missing",
        ),
        (
            lambda r: r["transition"]["to_state"].update(mode="state", state_key="created"),
            "acceptance_is_not_state_completion",
        ),
        (lambda r: r["transition"].update(failures=[]), "contract_invalid"),
    ],
)
def test_invalid_transition_cannot_be_sealed(mutation, code):
    package, sources = fixture()
    mutation(package["knowledge.jsonl"][0])
    package["coverage.json"]["entries"][0]["knowledge_keys"] = [
        package["knowledge.jsonl"][0]["business_key"]
    ]
    with pytest.raises(CodeKnowledgeError, match=code):
        verify(package, sources)


@pytest.mark.parametrize(
    "part", ["source", "target", "failure_state", "failure_condition", "failure_outcome"]
)
def test_unknown_transition_semantics_block_activation(part):
    package, sources = fixture()
    t = package["knowledge.jsonl"][0]["transition"]
    if part == "source":
        t["from_state"].update(mode="unresolved", state_keys=[])
    elif part == "target":
        t["to_state"]["mode"] = "unknown"
        package["knowledge.jsonl"][0]["success_boundary"]["phase"] = "unknown"
    elif part == "failure_state":
        t["failures"][0]["state_after"]["mode"] = "unknown"
    elif part == "failure_condition":
        t["failures"][0]["condition"] = dict(op="unknown", reason="callee unavailable")
    else:
        t["failures"][0]["outcome"] = "unknown"
    assert verify(package, sources)["activation_blocked"]


def new_build(db):
    repo = CodeRepository(db)
    ids = repo.register(code="fsm", base_code="fsm", config={})
    manifest = dict(files=[])
    source = repo.freeze_source(
        ids["source_id"],
        dict(
            kind="local_bundle",
            bundle_id="synthetic",
            manifest_hash=digest(manifest),
            svn_revision=None,
        ),
        manifest,
    )
    build = repo.new_build(
        ids["source_id"],
        source,
        purpose="baseline",
        configuration={"contract_version": "code-business/v2"},
    )
    return repo, ids, source, build


def test_shared_object_states_atomic_conflict_and_query_projection(database):
    repo, ids, source, build = new_build(database)
    package, _ = fixture(source_snapshot_id=source)
    first = package["knowledge.jsonl"][0]
    first["business_key"] = "factory.work_order.start.request"
    first["transition"].update(
        event_key=first["business_key"], machine_key="factory.work_order.execution"
    )
    package["coverage.json"]["entries"][0].update(
        entry_id="factory.work_order.start", knowledge_keys=[first["business_key"]]
    )
    repo.store_candidate(build["snapshot_id"], package)
    second = deepcopy(package)
    record = second["knowledge.jsonl"][0]
    record["business_key"] = "factory.work_order.report.prepare"
    record["transition"]["event_key"] = record["business_key"]
    second["coverage.json"]["entries"][0].update(
        entry_id="factory.work_order.report", knowledge_keys=[record["business_key"]]
    )
    conflict = deepcopy(second)
    conflict["knowledge.jsonl"][0]["states"][0]["raw_value"] = "20"
    with pytest.raises(CodeKnowledgeError, match="state_definition_conflict"):
        repo.store_candidate(build["snapshot_id"], conflict)
    assert (
        database.execute_one(f"select count(*) as n from {table(database, 'code_member')}")["n"]
        == 2
    )
    repo.store_candidate(build["snapshot_id"], second)
    for entity, count in [
        ("code_object", 1),
        ("code_machine", 2),
        ("code_state", 1),
        ("code_transition", 2),
        ("code_transition_source", 2),
        ("code_transition_failure", 2),
    ]:
        assert (
            database.execute_one(f"select count(*) as n from {table(database, entity)}")["n"]
            == count
        )
    database.execute(
        f"update {table(database, 'code_snapshot')} set state='READY' where id=?",
        (build["snapshot_id"],),
    )
    doc = knowledge_id(ids["source_id"], record["business_key"])
    loaded = repo.read_member(ids["knowledge_base_id"], build["snapshot_id"], doc)
    assert loaded["knowledge"]["transition"] == record["transition"]
    database.execute(
        f"delete from {table(database, 'code_transition_source')} where business_key=?",
        (record["business_key"],),
    )
    with pytest.raises(CodeKnowledgeError, match="projection_mismatch"):
        repo.read_member(ids["knowledge_base_id"], build["snapshot_id"], doc)
    assert not database.execute("pragma foreign_key_check")


def test_state_alias_and_failure_or_target_changes_are_not_evidence_only():
    package, sources = fixture()
    with pytest.raises(CodeKnowledgeError, match="state_identity_conflict"):
        verify(
            package,
            sources,
            known_states=[
                dict(machine_key="factory.work_order.configuration", key="draft", raw_value="10")
            ],
        )
    old = package["knowledge.jsonl"][0]
    for part in ("to_state", "failures"):
        new = deepcopy(old)
        if part == "to_state":
            new["transition"][part].update(mode="state", state_key="created")
        else:
            new["transition"][part][0]["state_after"].update(mode="state", state_key="created")
        assert compare_records(old, new, old_relations=[], new_relations=[]) == dict(
            classification="semantic", changed_fields=["transition"]
        )


def test_v1_retirement_preserves_ones_source_and_audit(database, tmp_path):
    from backend.tests.test_knowledge_import import prepare, export_row, run

    run(database, prepare(tmp_path, [export_row()]))
    before = database.execute(f"select * from {table(database, 'document_revision')}")
    repo, ids, source, build = new_build(database)
    package, _ = fixture(source_snapshot_id=source)
    package["manifest.json"]["contract_version"] = "code-business/v1"
    snapshot = repo.snapshot(ids["knowledge_base_id"], build["snapshot_id"], ready=False)
    run_id = repo._import_run(snapshot, package)
    record = package["knowledge.jsonl"][0] | dict(kind="operation", transition=None)
    repo._store_record(snapshot, run_id, record, package["evidence.jsonl"])
    row = database.execute_one(
        f"select r.id,r.attributes from {table(database, 'document_revision')} r join {table(database, 'document')} d on d.id=r.document_id where d.source_id=?",
        (ids["source_id"],),
    )
    attributes = json.loads(row["attributes"])
    attributes["contract_version"] = "code-business/v1"
    database.execute(
        f"update {table(database, 'document_revision')} set attributes=? where id=?",
        (json.dumps(attributes), row["id"]),
    )
    database.execute(
        f"update {table(database, 'code_build')} set configuration_json=?,stage='FAILED',active=0 where id=?",
        (json.dumps(dict(contract_version="code-business/v1")), build["build_id"]),
    )
    retirement = CodeCandidateRetirement(database)
    manifest = retirement.retire(ids["source_id"])
    with pytest.raises(CodeKnowledgeError, match="retirement_changed"):
        retirement.retire(ids["source_id"], expected_digest="wrong")
    assert (
        retirement.retire(ids["source_id"], expected_digest=manifest["digest"])["state"]
        == "RETIRED"
    )
    assert database.execute(f"select * from {table(database, 'document_revision')}") == before
    assert database.execute_one(
        f"select id from {table(database, 'code_source_snapshot')} where id=?", (source,)
    )
    assert database.execute_one(
        f"select id from {table(database, 'code_build')} where id=?", (build["build_id"],)
    )
    assert not database.execute("pragma foreign_key_check")


@pytest.mark.parametrize(
    "entity,column,value",
    [
        ("code_transition", "target_mode", "unknown"),
        ("code_transition_failure", "outcome", "partial"),
        ("code_state", "raw_value", "20"),
    ],
)
def test_query_rejects_changed_relational_facts(database, entity, column, value):
    repo, ids, source, build = new_build(database)
    package, _ = fixture(source_snapshot_id=source)
    repo.store_candidate(build["snapshot_id"], package)
    database.execute(
        f"update {table(database, 'code_snapshot')} set state='READY' where id=?",
        (build["snapshot_id"],),
    )
    database.execute(
        f"update {table(database, entity)} set {column}=? where snapshot_id=?",
        (value, build["snapshot_id"]),
    )
    with pytest.raises(CodeKnowledgeError, match="projection_mismatch"):
        repo.read_member(
            ids["knowledge_base_id"],
            build["snapshot_id"],
            knowledge_id(ids["source_id"], "factory.work_order.publish"),
        )


def test_proven_indeterminate_failure_is_distinct_from_missing_analysis(database):
    repo, ids, source, build = new_build(database)
    package, sources = fixture(source_snapshot_id=source)
    record = package["knowledge.jsonl"][0]
    record["transition"]["failures"][0]["state_after"].update(
        mode="indeterminate", description="补偿写入失败，须查询状态字段确认"
    )
    with pytest.raises(CodeKnowledgeError, match="indeterminate_state_requires_runtime_facts"):
        verify(package, sources)
    record["required_runtime_facts"] = [
        dict(field="work_order.status", relation_path="work_order.id", time="补偿失败后")
    ]
    assert not verify(package, sources)["activation_blocked"]
    repo.store_candidate(build["snapshot_id"], package)
    database.execute(
        f"update {table(database, 'code_snapshot')} set state='READY' where id=?",
        (build["snapshot_id"],),
    )
    row = repo.read_member(
        ids["knowledge_base_id"],
        build["snapshot_id"],
        knowledge_id(ids["source_id"], record["business_key"]),
    )
    assert row["knowledge"]["transition"]["failures"][0]["state_after"]["mode"] == "indeterminate"
    record["transition"]["to_state"]["mode"] = "indeterminate"
    with pytest.raises(CodeKnowledgeError, match="contract_invalid"):
        verify(package, sources)
