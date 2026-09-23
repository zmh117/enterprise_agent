"""新版合同全部使用合成文件，不读取真实业务输入。"""

from copy import deepcopy
import json

import pytest

from app.modules.knowledge.domain.chunking import KEEP_IDS_PROFILE, prepare_chunks
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.infrastructure.keep_ids_export import prepare_keep_ids
from backend.tests.test_knowledge_import import (
    database as database_fixture,
    export_row,
    prepare as old_prepare,
    run as old_import,
)
from backend.tests.test_knowledge_sync_candidates import configured

database = database_fixture


def dataset(root):
    root.mkdir(exist_ok=True)
    dictionary = {
        "source_host": "https://synthetic.invalid",
        "team_id": "synthetic_team",
        "fields": [
            {
                "uuid": "field_module",
                "name": "所属功能模块",
                "type": 1,
                "options": [{"uuid": "module_report", "value": "报工管理"}],
            }
        ],
    }
    (root / "字段字典.json").write_text(json.dumps(dictionary))
    rows = {}
    for number, (label, subtype) in enumerate(
        (("缺陷", "缺陷"), ("工单", "MES工单"), ("Story", "Story"), ("子任务", "Sub-task")), 1
    ):
        row = {
            "uuid": f"item_{number}",
            "number": number,
            "summary": "合成报工重复提交",
            "desc": "合成问题：报工数量重复累计" if number < 3 else "",
            "desc_rich": "",
            "_export_format": "keep_ids_v1",
            "create_time": 1700000000000000,
            "server_update_stamp": 1700000000000001,
            "issue_type_uuid": f"type_{number}",
            "issue_type_name": subtype,
            "project_uuid": "project_id",
            "project_name": "合成 MES 项目",
            "status_uuid": "status_id",
            "status_name": "处理中",
            "parent_uuid": "item_3" if label == "子任务" else "",
            "subtasks": [{"uuid": "item_4"}] if label == "Story" else [],
            "field_values": [
                {
                    "field_uuid": "field_module",
                    "field_name": "所属功能模块",
                    "type": 1,
                    "value_type": 0,
                    "value": "module_report",
                    "value_display": "报工管理",
                }
            ],
        }
        rows[label] = row
        (root / (label + ".jsonl")).write_text(json.dumps(row) + "\n")
        meta = {
            "source_host": dictionary["source_host"],
            "team_id": dictionary["team_id"],
            "export_format": "keep_ids_v1",
            "success": 1,
            "failed": 0,
            "list_pagination_complete": True,
        }
        (root / (label + "_采集说明.json")).write_text(json.dumps(meta))
        if label != "子任务":
            listing = {
                "uuid": row["uuid"],
                "name": row["summary"],
                "number": number,
                "createTime": row["create_time"],
                "project": {"uuid": row["project_uuid"], "name": row["project_name"]},
                "status": {"uuid": row["status_uuid"], "name": row["status_name"]},
                "issueType": {"uuid": row["issue_type_uuid"], "name": row["issue_type_name"]},
            }
            (root / (label + "_list.jsonl")).write_text(json.dumps(listing) + "\n")
    return rows


def prepare(root):
    return prepare_keep_ids(root, expected={"缺陷": 1, "工单": 1, "Story": 1, "子任务": 1})


def test_keep_ids_names_embedding_parent_and_three_batches(tmp_path):
    dataset(tmp_path)
    batches = prepare(tmp_path)
    assert [b.manifest["record_count"] for b in batches] == [1, 1, 2]
    record = batches[0].records[0]
    assert record.values["source_project_id"] == "project_id"
    assert record.values["attributes"]["source_fields"]["field_module"]["value"] == "module_report"
    chunks = prepare_chunks(record.values, KEEP_IDS_PROFILE).chunks
    assert "项目：合成 MES 项目" in chunks[0]["embedding_text"]
    assert "模块：报工管理" in chunks[0]["embedding_text"]
    assert "module_report" not in chunks[0]["embedding_text"]
    assert "project_id" not in chunks[0]["embedding_text"]
    child = batches[2].records[1]
    assert child.relations == (
        {
            "target_external_id": "item_3",
            "source_relation_type": "parent_uuid",
            "source_direction": "child_to_parent",
        },
    )
    chunk = prepare_chunks(child.values).chunks[0]
    assert "类型：Sub-task" in chunk["embedding_text"]
    assert "title_only" in chunk["quality_flags"]
    assert child.values["completeness"]["discussion"] == "not_indexed"


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda r: r.update(_export_format="old"), "knowledge_export_format_invalid"),
        (lambda r: r.update(project_uuid="wrong_project"), "knowledge_list_scope_invalid"),
        (lambda r: r.update(project_name="另一项目"), "knowledge_display_name_conflict"),
        (
            lambda r: r["field_values"][0].update(value_display="错误模块"),
            "knowledge_field_option_invalid",
        ),
        (
            lambda r: r["field_values"][0].update(field_name="未知字段"),
            "knowledge_field_dictionary_invalid",
        ),
        (lambda r: r.update(server_update_stamp=1), "knowledge_timestamp_invalid"),
    ],
)
def test_keep_ids_rejects_drift(tmp_path, mutation, code):
    rows = dataset(tmp_path)
    mutation(rows["缺陷"])
    (tmp_path / "缺陷.jsonl").write_text(json.dumps(rows["缺陷"]))
    with pytest.raises(ExportValidationError, match=code):
        prepare(tmp_path)


def test_keep_ids_nested_children_and_cycle(tmp_path):
    rows = dataset(tmp_path)
    extra = deepcopy(rows["子任务"])
    extra.update(uuid="item_5", number=5, parent_uuid="item_4")
    rows["Story"]["subtasks"].append({"uuid": "item_5"})
    (tmp_path / "Story.jsonl").write_text(json.dumps(rows["Story"]))
    child_path = tmp_path / "子任务.jsonl"
    child_path.write_text(json.dumps(rows["子任务"]) + "\n" + json.dumps(extra))
    meta_path = tmp_path / "子任务_采集说明.json"
    meta = json.loads(meta_path.read_text())
    meta["success"] = 2
    meta_path.write_text(json.dumps(meta))
    counts = {"缺陷": 1, "工单": 1, "Story": 1, "子任务": 2}
    assert len(prepare_keep_ids(tmp_path, expected=counts)[2].records) == 3
    rows["子任务"]["parent_uuid"] = "item_5"
    child_path.write_text(json.dumps(rows["子任务"]) + "\n" + json.dumps(extra))
    with pytest.raises(ExportValidationError, match="knowledge_parent_cycle"):
        prepare_keep_ids(tmp_path, expected=counts)


def test_keep_ids_replay_deterministic_and_ignores_acceptance_subfolder(tmp_path):
    dataset(tmp_path)
    first = prepare(tmp_path)
    sample = tmp_path / "验收"
    sample.mkdir()
    (sample / "缺陷.jsonl").write_text("invalid")
    assert prepare(tmp_path) == first


def test_keep_ids_source_mismatch_fails_without_echo(tmp_path):
    dataset(tmp_path)
    p = tmp_path / "Story_采集说明.json"
    meta = json.loads(p.read_text())
    meta["team_id"] = "other_team"
    p.write_text(json.dumps(meta))
    with pytest.raises(ExportValidationError, match="knowledge_source_identity_invalid"):
        prepare(tmp_path)


def test_replacement_is_explicit_and_preserves_current_until_activation(database, tmp_path):
    old_import(database, old_prepare(tmp_path, [export_row(index=90)]))
    before = database.execute('select id,current_revision_id from "knowledge.document"')
    repo, binding, service = configured(database)
    dataset(tmp_path)
    result = service.stage_test_replacement(binding["id"], prepare(tmp_path))
    assert result["phase"] == "STAGED"
    candidate = repo.candidate(result["run_id"], before[0]["id"])
    assert list(candidate["candidate_members_json"].values()) == ["removed"]
    assert (
        database.execute(
            "select id,current_revision_id from \"knowledge.document\" where lifecycle_state='active'"
        )
        == before
    )
    assert service.stage_test_replacement(binding["id"], prepare(tmp_path)) == result
    assert len(list(repo.candidates(result["run_id"]))) == 5


def test_replacement_requires_all_three_kinds(database, tmp_path):
    _, binding, service = configured(database)
    dataset(tmp_path)
    with pytest.raises(ExportValidationError, match="knowledge_replacement_scope_invalid"):
        service.stage_test_replacement(binding["id"], prepare(tmp_path)[:1])
