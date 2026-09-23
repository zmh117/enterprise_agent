from __future__ import annotations
from app.modules.knowledge.infrastructure.import_repository import ImportRepository

from copy import deepcopy
import json
import os
from pathlib import Path
import uuid

import pytest

from app.cli.import_ones_knowledge import main
from app.modules.knowledge.application.import_service import KnowledgeImportService
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.infrastructure.storage import table
from app.modules.knowledge.domain.normalization import ExportValidationError, Sanitizer
from app.modules.knowledge.infrastructure.ones_export import prepare_export
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator, load_migration_catalog, schema_expectations
from app.shared.schema_fact_sources import baseline_engine_catalogs
from app.shared.schema_baseline import postgres_comment_snapshot, schema_snapshot


STAMP = 1_750_000_000_000_000


def export_row(index: int = 1, *, target: str | None = None) -> tuple[dict, dict]:
    key = f"synthetic_item_{index}"
    listing = {
        "uuid": key,
        "name": f"合成缺陷 {index}",
        "number": index,
        "createTime": STAMP,
        "project": {"uuid": "project_id"},
        "status": {"uuid": "status_id", "name": "处理中"},
        "sprint": {"uuid": "sprint_id", "name": "合成迭代"},
    }
    detail = {
        "uuid": key,
        "summary": listing["name"],
        "number": index,
        "create_time": STAMP,
        "server_update_stamp": STAMP + 100,
        "project_uuid": "合成项目",
        "status_uuid": "处理中",
        "sprint_uuid": "合成迭代",
        "issue_type_uuid": "缺陷",
        "desc": "操作步骤：输入 a < b\n实际结果：合成错误\n预期结果：合成成功",
        "desc_rich": '<p>合成正文</p><img data-uuid="synthetic_image" src="https://example.invalid/image?signed=synthetic">',
        "field_values": [
            {"field_uuid": "解决方案", "value": "检查合成参数"},
            {"field_uuid": "所属功能模块", "value": ["合成模块"]},
            {"field_uuid": "标签", "value": "合成标签"},
            {"field_uuid": "未知字段", "value": "保留合成字段"},
        ],
        "discussion_count": 2,
        "attachment_count": 1,
        "related_tasks": [],
        "links": [],
    }
    if target:
        detail["links"] = [
            {
                "task_uuid": target,
                "task_link_type_uuid": "synthetic_link_type",
                "link_desc_type": "link_out_desc",
            }
        ]
        detail["related_tasks"] = [
            {"uuid": target, "summary": "不得导入的关联摘要", "readable": True}
        ]
    return detail, listing


def prepare(tmp_path: Path, rows: list[tuple[dict, dict]]):
    detail = tmp_path / "detail.jsonl"
    listing = tmp_path / "list.jsonl"
    detail.write_text("\n".join(json.dumps(r[0], ensure_ascii=False) for r in rows) + "\n")
    listing.write_text("\n".join(json.dumps(r[1], ensure_ascii=False) for r in rows) + "\n")
    return prepare_export(detail, listing, expected_count=len(rows))


@pytest.fixture
def database():
    value = Database("sqlite:///:memory:")
    Migrator(value, default_migrations_dir(), migrator_build="knowledge-test").run()
    yield value
    value.close()


def run(database, prepared, **kwargs):
    return KnowledgeImportService(ImportRepository(database)).import_export(
        prepared,
        source_code="synthetic_source",
        knowledge_base_code="synthetic_base",
        **kwargs,
    )


def test_mapping_plain_text_and_no_attachment_processing(tmp_path):
    prepared = prepare(tmp_path, [export_row(target="unimported_ticket")])
    record = prepared.records[0]
    assert record.values["source_project_id"] == "project_id"
    assert record.values["source_project_name"] == "合成项目"
    assert record.values["source_status_id"] == "status_id"
    assert "a < b" in record.values["body_text"]
    assert record.values["attributes"]["sprint_id"] == "sprint_id"
    assert record.values["attributes"]["labels"] == "合成标签"
    assert record.values["attributes"]["unmapped_fields"]["未知字段"] == "保留合成字段"
    assert record.values["completeness"]["ocr"] == "not_requested"
    assert record.values["completeness"]["discussion"] == "not_collected"
    serialized = json.dumps(record.values, ensure_ascii=False)
    assert "https://" not in serialized
    assert "signed=" not in serialized
    assert "不得导入的关联摘要" not in serialized
    assert (
        record.values["attributes"]["image_references"][0]["source_attachment_id"]
        == "synthetic_image"
    )


def test_secret_cleaning():
    sanitizer = Sanitizer()
    value = sanitizer.value(
        {
            "access_token": "synthetic-do-not-persist",
            "note": "正常正文\nPASSWORD=synthetic-secret\n后续文字",
            "url": "postgresql://synthetic:synthetic@localhost/test",
            "data": "data:image/gif;base64,synthetic",
            "authorization_note": "synthetic-authorization",
            "text": "Bearer synthetic-credential\n<password>synthetic-xml-secret</password>",
        }
    )
    serialized = json.dumps(value, ensure_ascii=False)
    assert "synthetic" not in serialized
    assert "正常正文" in serialized and "后续文字" in serialized


def test_input_mismatch_rejected_before_any_import(tmp_path):
    detail, listing = export_row()
    listing["name"] = "不同的合成标题"
    with pytest.raises(ExportValidationError, match="knowledge_list_detail_mismatch"):
        prepare(tmp_path, [(detail, listing)])


def test_duplicate_document_rejected(tmp_path):
    row = export_row()
    with pytest.raises(ExportValidationError, match="knowledge_duplicate_document"):
        prepare(tmp_path, [row, row])


def test_duplicate_custom_field_rejected(tmp_path):
    detail, listing = export_row()
    detail["field_values"].append(detail["field_values"][0])
    with pytest.raises(ExportValidationError, match="knowledge_field_duplicate"):
        prepare(tmp_path, [(detail, listing)])


def test_bad_timestamp_unit_rejected(tmp_path):
    detail, listing = export_row()
    detail["server_update_stamp"] = STAMP // 1000
    with pytest.raises(ExportValidationError, match="knowledge_timestamp_invalid"):
        prepare(tmp_path, [(detail, listing)])


@pytest.mark.parametrize("stamp", [True, False, "1750000000000000", -1])
def test_invalid_stamp_types_fail_preflight(tmp_path, stamp):
    detail, listing = export_row()
    detail["server_update_stamp"] = stamp
    with pytest.raises(ExportValidationError, match="knowledge_timestamp_invalid"):
        prepare(tmp_path, [(detail, listing)])


def test_duplicate_json_keys_and_oversize_rows_rejected(tmp_path, monkeypatch):
    prepare(tmp_path, [export_row()])
    detail = tmp_path / "detail.jsonl"
    detail.write_text('{"uuid":"synthetic","uuid":"synthetic"}\n')
    with pytest.raises(ExportValidationError, match="knowledge_json_duplicate_key"):
        prepare_export(detail, tmp_path / "list.jsonl", expected_count=1)
    monkeypatch.setattr("app.modules.knowledge.infrastructure.ones_export.MAX_ROW_BYTES", 16)
    detail.write_text("x" * 17)
    with pytest.raises(ExportValidationError, match="knowledge_input_limit_exceeded"):
        prepare_export(detail, tmp_path / "list.jsonl", expected_count=1)


def test_input_count_and_identity_set_mismatch(tmp_path):
    prepare(tmp_path, [export_row()])
    with pytest.raises(ExportValidationError, match="knowledge_record_count_mismatch"):
        prepare_export(tmp_path / "detail.jsonl", tmp_path / "list.jsonl", expected_count=2)
    detail, listing = export_row()
    listing["uuid"] = "synthetic_other_identity"
    with pytest.raises(ExportValidationError, match="knowledge_record_set_mismatch"):
        prepare(tmp_path, [(detail, listing)])


def test_import_idempotence_and_dangling_targets(database, tmp_path):
    prepared = prepare(
        tmp_path,
        [export_row(target="synthetic_item_2"), export_row(2, target="missing_requirement")],
    )
    first = run(database, prepared)
    second = run(database, prepared)
    assert first["created_count"] == 2
    assert second["replayed"] is True
    assert (
        first["verification"]
        == second["verification"]
        == {
            "source_documents": 2,
            "defect_documents": 2,
            "matching_input_documents": 2,
            "source_revisions": 2,
            "memberships": 2,
            "relation_observations": 2,
            "resolved_relation_targets": 1,
            "unresolved_relation_targets": 1,
        }
    )
    assert not database.execute("pragma foreign_key_check")


def test_document_can_be_in_two_bases_without_copying(database, tmp_path):
    prepared = prepare(tmp_path, [export_row()])
    run(database, prepared)
    result = KnowledgeImportService(ImportRepository(database)).import_export(
        prepared,
        source_code="synthetic_source",
        knowledge_base_code="another_base",
    )
    assert result["unchanged_count"] == 1
    assert result["verification"]["source_revisions"] == 1
    assert len(database.execute('select * from "knowledge.knowledge_base_document"')) == 2


def test_new_revision_and_stale_input_do_not_overwrite(database, tmp_path):
    original = export_row(target="missing_requirement")
    run(database, prepare(tmp_path, [original]))
    changed = deepcopy(original)
    changed[0]["desc"] += "\n合成更新"
    changed[0]["server_update_stamp"] += 100
    result = run(database, prepare(tmp_path, [changed]))
    assert result["revised_count"] == 1
    assert result["verification"]["source_revisions"] == 2
    stale = deepcopy(original)
    stale[0]["server_update_stamp"] -= 1
    result = run(database, prepare(tmp_path, [stale]))
    assert result["stale_count"] == 1
    assert result["verification"]["matching_input_documents"] == 0
    assert result["verification"]["source_revisions"] == 2


def test_same_source_stamp_conflict_is_rejected(database, tmp_path):
    first = export_row()
    run(database, prepare(tmp_path, [first]))
    conflict = deepcopy(first)
    conflict[0]["desc"] += "冲突的合成内容"
    with pytest.raises(ExportValidationError, match="knowledge_source_version_conflict"):
        run(database, prepare(tmp_path, [conflict]))
    rows = database.execute(
        "select state,processed_count,error_code from \"knowledge.import_run\" where state='failed'"
    )
    assert rows == [
        {"state": "failed", "processed_count": 0, "error_code": "knowledge_source_version_conflict"}
    ]


def test_interrupted_run_resumes_committed_checkpoint(database, tmp_path, monkeypatch):
    prepared = prepare(tmp_path, [export_row(), export_row(2)])
    original = ImportRepository.record
    calls = 0

    def interrupted(self, record, *args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic internal error must not be exposed")
        return original(self, record, *args)

    monkeypatch.setattr(ImportRepository, "record", interrupted)
    with pytest.raises(ExportValidationError, match="^knowledge_import_failed$"):
        run(database, prepared)
    assert (
        database.execute_one('select processed_count from "knowledge.import_run"')[
            "processed_count"
        ]
        == 1
    )
    monkeypatch.setattr(ImportRepository, "record", original)
    result = run(database, prepared)
    assert result["created_count"] == 2 and result["processed_count"] == 2
    assert result["verification"]["source_revisions"] == 2


def test_unavailable_document_is_not_restored(database, tmp_path):
    prepared = prepare(tmp_path, [export_row()])
    run(database, prepared)
    database.execute("update \"knowledge.document\" set lifecycle_state='deleted'")
    row = export_row()
    row[0]["server_update_stamp"] += 100
    with pytest.raises(ExportValidationError, match="knowledge_document_unavailable"):
        run(database, prepare(tmp_path, [row]))


def test_current_pointer_cannot_reference_another_document(database, tmp_path):
    run(database, prepare(tmp_path, [export_row(), export_row(2)]))
    docs = database.execute('select id,current_revision_id from "knowledge.document" order by id')
    with pytest.raises(Exception):
        with database.unit_of_work():
            database.execute(
                'update "knowledge.document" set current_revision_id=? where id=?',
                (docs[1]["current_revision_id"], docs[0]["id"]),
            )


def test_schema_tools_recognize_qualified_names(database):
    expected = schema_expectations(load_migration_catalog(default_migrations_dir()))
    assert "knowledge.document" in expected.tables
    assert "knowledge" not in expected.tables
    catalogs = baseline_engine_catalogs(default_migrations_dir() / "100_baseline_v1.sql")
    for catalog in catalogs.values():
        assert ("knowledge.document_relation", "to_external_id") in catalog.columns
    assert table(database, "document") == '"knowledge.document"'
    assert stable_id("document", "a") != stable_id("document", "b")


def test_cli_preflight_does_not_load_database_settings(tmp_path, monkeypatch, capsys):
    prepare(tmp_path, [export_row()])

    def forbidden():
        raise AssertionError("Database configuration must not be loaded for preflight")

    monkeypatch.setattr("app.cli.import_ones_knowledge.load_settings", forbidden)
    assert (
        main(
            [
                "--input-dir",
                str(tmp_path),
                "--detail-file",
                "detail.jsonl",
                "--list-file",
                "list.jsonl",
                "--expected-count",
                "1",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "合成缺陷" not in output
    assert "preflight_passed" in output


@pytest.mark.skipif(
    not os.getenv("KNOWLEDGE_TEST_POSTGRES_DSN"), reason="requires isolated PostgreSQL"
)
def test_real_postgres_migration_import_constraints_and_lock(tmp_path):
    # 仅使用独立测试实例；不清空 schema，不删除已有行；每次使用新的合成来源。
    database = Database(os.environ["KNOWLEDGE_TEST_POSTGRES_DSN"])
    contender = Database(os.environ["KNOWLEDGE_TEST_POSTGRES_DSN"])
    try:
        result = Migrator(
            database, default_migrations_dir(), migrator_build="knowledge-postgres-test"
        ).run()
        assert result.head == "144"
        assert (
            not Migrator(
                database, default_migrations_dir(), migrator_build="knowledge-postgres-test"
            )
            .run()
            .applied
        )
        snapshot = schema_snapshot(database)
        assert "knowledge.document" in snapshot["tables"]
        comments = postgres_comment_snapshot(database)
        assert sum(key.startswith("knowledge.") for key in comments["tables"]) == 18
        column_count = database.execute_one(
            "select count(*) as n from information_schema.columns where table_schema='knowledge'"
        )["n"]
        assert sum(key.startswith("knowledge.") for key in comments["columns"]) == column_count
        source_code = f"synthetic_{uuid.uuid4().hex}"
        source_id = stable_id("source", source_code)
        base_code = f"synthetic_{uuid.uuid4().hex}"
        service = KnowledgeImportService(ImportRepository(database))
        with service.repository.source_lock(source_id):
            with pytest.raises(ExportValidationError, match="knowledge_source_import_busy"):
                with ImportRepository(contender).source_lock(source_id):
                    pytest.fail("second connection must not acquire the source lock")
        first = prepare(tmp_path, [export_row(target="synthetic_item_2")])
        imported = service.import_export(
            first, source_code=source_code, knowledge_base_code=base_code
        )
        assert imported["verification"]["unresolved_relation_targets"] == 1
        assert service.import_export(first, source_code=source_code, knowledge_base_code=base_code)[
            "replayed"
        ]
        later = prepare(tmp_path, [export_row(2)])
        imported = service.import_export(
            later, source_code=source_code, knowledge_base_code=base_code
        )
        assert imported["verification"]["source_revisions"] == 2
        assert imported["verification"]["resolved_relation_targets"] == 1
        docs = database.execute(
            "select id,current_revision_id from knowledge.document where source_id=? order by id",
            (source_id,),
        )
        row = database.execute_one(
            "select source_snapshot,source_created_at from knowledge.document_revision where id=?",
            (docs[0]["current_revision_id"],),
        )
        assert isinstance(row["source_snapshot"], dict)
        assert row["source_created_at"].utcoffset() is not None
        with pytest.raises(Exception):
            with database.unit_of_work():
                database.execute(
                    "update knowledge.document set current_revision_id=? where id=?",
                    (docs[1]["current_revision_id"], docs[0]["id"]),
                )
        with pytest.raises(Exception):
            with database.unit_of_work():
                database.execute(
                    "update knowledge.document_relation set to_external_id='wrong_synthetic_target' where from_source_id=?",
                    (source_id,),
                )
        with pytest.raises(Exception):
            with database.unit_of_work():
                database.execute(
                    "update knowledge.document_revision set attributes='invalid-json' where id=?",
                    (docs[0]["current_revision_id"],),
                )
        assert (
            service.import_export(later, source_code=source_code, knowledge_base_code=base_code)[
                "verification"
            ]["source_revisions"]
            == 2
        )
    finally:
        contender.close()
        database.close()
