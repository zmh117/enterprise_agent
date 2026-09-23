"""多类型合同，仅使用合成数据，不读取真实导出或启动外部服务。"""

import pytest
from copy import deepcopy
import json

from backend.tests.test_knowledge_import import (
    export_row,
    database as database_fixture,
    prepare as prepare_defect,
    run,
)
from app.modules.knowledge.application.import_service import KnowledgeImportService
from app.modules.knowledge.infrastructure.import_repository import ImportRepository
from app.modules.knowledge.infrastructure.ones_export import prepare_export
from app.modules.knowledge.domain.chunking import prepare_chunks, DEFAULT_PROFILE
from app.modules.knowledge.domain.chunking import WORK_ITEM_PROFILE, validate_chunks
from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository

from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.work_items import check_offline_type, compare_version

database = database_fixture


@pytest.mark.parametrize("source_type", ["Story", "Sub-task", "演示子任务"])
def test_approved_requirement_subtypes(source_type):
    check_offline_type("requirement", source_type)


@pytest.mark.parametrize(
    "kind,source_type",
    [
        ("ticket", "Story"),
        ("requirement", "未知类型"),
        ("story", "Story"),
        ("defect", "MES工单"),
        ("ticket", None),
        ("ticket", {"uuid": "synthetic"}),
    ],
)
def test_unknown_or_mismatched_types_rejected(kind, source_type):
    with pytest.raises(ExportValidationError):
        check_offline_type(kind, source_type)


def version(**changes):
    return compare_version(
        **{
            "old_stamp": 100,
            "new_stamp": 101,
            "old_hash": "a",
            "new_hash": "a",
            "old_kind": "ticket",
            "new_kind": "ticket",
            **changes,
        }
    )


def test_version_comparison_includes_type_and_rejects_stale_reclassification():
    assert version() == "unchanged"
    assert version(new_kind="requirement") == "revised"
    assert version(new_stamp=99) == "stale"
    assert version(new_stamp=None, new_kind="requirement") == "stale"
    with pytest.raises(ExportValidationError, match="knowledge_source_version_conflict"):
        version(new_stamp=100, new_kind="requirement")
    with pytest.raises(ExportValidationError, match="knowledge_source_version_conflict"):
        version(new_stamp=100, new_hash="b")


@pytest.mark.parametrize("stamp", [True, -1, "100", 0])
def test_version_rejects_invalid_stamps(stamp):
    with pytest.raises(ExportValidationError, match="knowledge_timestamp_invalid"):
        version(new_stamp=stamp)


def prepare(tmp_path, rows, kind):
    details, listings = tmp_path / "details.jsonl", tmp_path / "listings.jsonl"
    details.write_text("\n".join(json.dumps(row[0]) for row in rows) + "\n")
    listings.write_text("\n".join(json.dumps(row[1]) for row in rows) + "\n")
    return prepare_export(details, listings, expected_count=len(rows), document_kind=kind)


def typed_row(kind="requirement", *, index=1, source_type=None, body=""):
    detail, listing = export_row(index)
    detail["issue_type_uuid"] = source_type or ("Story" if kind == "requirement" else "MES工单")
    detail["desc"], detail["desc_rich"] = body, "<p><br></p>"
    listing["sprint"] = {"uuid": "", "name": ""}
    return detail, listing


def test_defect_byte_contract_is_unchanged(tmp_path):
    record = prepare_defect(tmp_path, [export_row()]).records[0]
    assert record.content_hash == "7ced4d3a0127e5b92762dcd356debb355bd15a62e8b3732c370f18ef453b0700"
    assert (
        prepare_chunks(record.values).output_hash
        == "8c3466160a1c6b5dc61e5abc6bdd5728c3e213b4dad572793ede258c4b18c714"
    )
    assert (
        DEFAULT_PROFILE.fingerprint
        == "edd49b9698781b2e473dfae2fcd3410de631a4ddbcc27468cd55bb35ba55fd35"
    )


def test_all_approved_subtypes_retained(tmp_path, database):
    names = ["Story", "Sub-task", "演示子任务"]
    prepared = prepare(
        tmp_path,
        [typed_row(index=i, source_type=name) for i, name in enumerate(names)],
        "requirement",
    )
    assert [r.values["attributes"]["source_issue_type_display"] for r in prepared.records] == names
    assert all(r.document_kind == "requirement" for r in prepared.records)
    assert all(r.values["attributes"]["source_issue_type_id"] is None for r in prepared.records)
    assert all(r.values["attributes"]["sprint_id"] is None for r in prepared.records)
    assert prepared.statistics["description_missing"] == 3
    imported = run(database, prepared)
    assert imported["verification"]["requirement_documents"] == 3
    assert run(database, prepared)["replayed"]


@pytest.mark.parametrize(
    "body,rich",
    [
        ("", ""),
        (None, ""),
        ("<p><br></p>", ""),
        ("", '<img src="https://example.invalid/synthetic">'),
    ],
)
def test_sparse_description_does_not_fabricate_body(tmp_path, body, rich):
    detail, listing = typed_row()
    detail.update(desc=body, desc_rich=rich)
    record = prepare(tmp_path, [(detail, listing)], "requirement").records[0]
    assert record.values["body_text"] == ""
    assert record.values["completeness"]["description"] == "missing"
    assert "https://" not in json.dumps(record.values)


@pytest.mark.parametrize(
    "sprint", [{"uuid": "", "name": "合成已命名迭代"}, {"uuid": "invalid id", "name": ""}]
)
def test_only_unassigned_sprint_shape_is_accepted(tmp_path, sprint):
    detail, listing = typed_row()
    listing["sprint"] = sprint
    with pytest.raises(ExportValidationError, match="knowledge_source_identifier_invalid"):
        prepare(tmp_path, [(detail, listing)], "requirement")


def test_type_mismatch_and_missing_title_fail_preflight(tmp_path):
    with pytest.raises(ExportValidationError, match="knowledge_source_type_mismatch"):
        prepare(tmp_path, [typed_row(source_type="未批准类型")], "requirement")
    detail, listing = typed_row()
    detail["summary"] = listing["name"] = ""
    with pytest.raises(ExportValidationError, match="knowledge_body_invalid"):
        prepare(tmp_path, [(detail, listing)], "requirement")


def test_typed_import_cross_type_relations_and_identity(tmp_path, database):
    first = export_row(index=99, target="synthetic_item_1")
    run(database, prepare_defect(tmp_path, [first]))
    prepared = prepare(tmp_path, [typed_row("ticket")], "ticket")
    service = KnowledgeImportService(ImportRepository(database))
    result = service.import_export(
        prepared, source_code="synthetic_source", knowledge_base_code="synthetic_tickets"
    )
    assert result["verification"]["ticket_documents"] == 1
    assert result["verification"]["resolved_relation_targets"] == 1
    service.import_export(
        prepared, source_code="synthetic_source", knowledge_base_code="another_ticket_base"
    )
    assert database.execute_one('select count(*) as n from "knowledge.document"')["n"] == 2
    before = database.execute_one(
        'select id,current_revision_id from "knowledge.document" where external_id=?',
        ("synthetic_item_1",),
    )
    newer = typed_row("ticket", body="合成修改")
    newer[0]["server_update_stamp"] += 100
    changed = prepare(tmp_path, [newer], "ticket")
    service.import_export(
        changed, source_code="synthetic_source", knowledge_base_code="synthetic_tickets"
    )
    after = database.execute_one(
        'select id,current_revision_id from "knowledge.document" where external_id=?',
        ("synthetic_item_1",),
    )
    assert (
        before["id"] == after["id"]
        and before["current_revision_id"] != after["current_revision_id"]
    )
    stale = deepcopy(newer)
    stale[0]["server_update_stamp"] -= 200
    older = prepare(tmp_path, [stale], "ticket")
    result = service.import_export(
        older, source_code="synthetic_source", knowledge_base_code="stale_base"
    )
    assert result["stale_count"] == 1 and result["verification"]["memberships"] == 0


@pytest.mark.parametrize("source_type", ["Story", "Sub-task", "演示子任务"])
def test_sparse_chunks_keep_real_type_and_title_evidence(tmp_path, source_type):
    detail, listing = typed_row(source_type=source_type)
    detail["field_values"] = []
    record = prepare(tmp_path, [(detail, listing)], "requirement").records[0]
    chunks = prepare_chunks(record.values)
    assert len(chunks.chunks) == 1
    chunk = chunks.chunks[0]
    assert chunk["source_field"] == "title"
    assert chunk["evidence_text"] == record.values["title"]
    assert f"类型：{source_type}" in chunk["embedding_text"]
    assert "解决方案证据" not in chunk["embedding_text"]
    assert "title_only" in chunk["quality_flags"]
    assert "description_missing" in chunk["quality_flags"]
    validate_chunks(chunks, WORK_ITEM_PROFILE)
    with pytest.raises(ExportValidationError, match="knowledge_chunk_source_profile_unsupported"):
        prepare_chunks(record.values, DEFAULT_PROFILE)


def test_long_typed_body_and_fields_are_bounded(tmp_path):
    detail, listing = typed_row("ticket", body="合成描述\n" * 1000)
    detail["field_values"] = [{"field_uuid": "解决方案", "value": "合成处理步骤。" * 1000}]
    record = prepare(tmp_path, [(detail, listing)], "ticket").records[0]
    chunks = prepare_chunks(record.values)
    assert len(chunks.chunks) > 2
    assert all(c["char_count"] <= 1200 and c["embedding_char_count"] <= 1800 for c in chunks.chunks)
    validate_chunks(chunks, WORK_ITEM_PROFILE)


def test_title_evidence_persists_and_vectors_use_typed_base(tmp_path, database):
    detail, listing = typed_row(source_type="Sub-task")
    detail["field_values"] = []
    prepared = prepare(tmp_path, [(detail, listing)], "requirement")
    run(database, prepared)
    service = ChunkService(ChunkRepository(database, profile=WORK_ITEM_PROFILE))
    first = service.run(knowledge_base_code="synthetic_base", expected_count=1, commit=True)
    assert first["counts"]["created"] == 1 and first["counts"]["chunks"] == 1
    second = service.run(knowledge_base_code="synthetic_base", expected_count=1, commit=True)
    assert second["counts"]["reused"] == 1
    chunk = database.execute_one(
        'select source_field,evidence_text from "knowledge.document_chunk"'
    )
    assert chunk == {"source_field": "title", "evidence_text": detail["summary"]}
    vectors = VectorRepository(database)
    snapshot = vectors.snapshot(
        vectors.scope("synthetic_base"), WORK_ITEM_PROFILE.fingerprint, 1, 1
    )
    assert snapshot["expected_document_count"] == 1
    assert not database.execute("pragma foreign_key_check")
