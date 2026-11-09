"""Persist authenticated Runtime observations, never model-asserted source text."""

from typing import Any

from app.modules.agent.infrastructure.runtime_pool_store import database_now, timestamp
from app.modules.knowledge.domain.code_answers import CodeAnalysisContext, path_in_scope, code_path
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError, ID, HASH, obj, validate
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_answer_store import CodeAnswerStore
from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.modules.knowledge.infrastructure.storage import insert

REPRESENTATION = obj(
    {
        "source_encoding": {"enum": ["utf-8", "utf-8-sig", "utf-16", "gb18030"]},
        "newline": {"const": "LF"},
        "keyword_policy": {"const": "repository_unexpanded"},
        "working_content_hash": HASH,
        "line_mapping": {"const": "identity"},
    }
)
FILE_EVIDENCE = obj(
    {
        "kind": {"const": "file_read"},
        "relative_path": {"type": "string", "maxLength": 2048},
        "line_start": {"type": "integer", "minimum": 1},
        "line_end": {"type": "integer", "minimum": 1},
        "repository_content_hash": HASH,
        "read_content_hash": HASH,
        "representation": REPRESENTATION,
        "tool_call_id": ID,
    }
)
HISTORY_EVIDENCE = obj(
    {
        "kind": {"const": "svn_history"},
        "operation_id": ID,
        "result_hash": HASH,
        "tool_call_id": ID,
    }
)


def record_runtime_evidence(
    store: CodeAnswerStore, context: CodeAnalysisContext, analysis: dict[str, Any], value: Any
) -> dict[str, Any]:
    validate(value, {"oneOf": [FILE_EVIDENCE, HISTORY_EVIDENCE]})
    identity = {**value, "analysis_id": analysis["id"], "svn_revision": context.revision}
    hashed = digest(identity)
    identifier = stable_id("code-runtime-evidence", analysis["id"], hashed)
    record = dict(
        id=identifier,
        analysis_id=analysis["id"],
        kind=value["kind"],
        svn_revision=context.revision,
        tool_call_id=value["tool_call_id"],
        evidence_hash=hashed,
        observed_at=timestamp(database_now(store.db)),
        validated_at=timestamp(database_now(store.db)),
    )
    if value["kind"] == "file_read":
        path = code_path(value["relative_path"])
        config = store.db.execute_one(
            f"SELECT allowed_paths_json FROM {store.t('code_resource_config')} WHERE revision_id=?",
            (context.config_revision_id,),
        )
        if (
            not config
            or not path_in_scope(path, json_value(config["allowed_paths_json"]))
            or not 1 <= value["line_end"] - value["line_start"] + 1 <= 400
        ):
            raise CodeKnowledgeError("CODE_EVIDENCE_SCOPE_MISMATCH")
        record.update(
            {
                k: value[k]
                for k in (
                    "relative_path",
                    "line_start",
                    "line_end",
                    "repository_content_hash",
                    "read_content_hash",
                )
            }
        )
        record["representation_json"] = value["representation"]
    else:
        operation = store.row("code_svn_operation", value["operation_id"])
        audit = store.db.execute_one(
            "SELECT m.tool_identifier,m.business_response_json FROM mcp_operation_audit m "
            "JOIN agent_tool_call a ON a.id=m.agent_tool_call_id "
            "WHERE m.agent_tool_call_id=? AND m.job_id=? AND m.invocation_id=? "
            "AND m.parent_audit_id IS NULL AND m.server_code='knowledge-mcp' "
            "AND m.status='SUCCEEDED' AND a.status='SUCCEEDED' AND m.response_truncated=0",
            (value["tool_call_id"], context.job_id, context.invocation_id),
        )
        if (
            operation["analysis_id"] != analysis["id"]
            or operation["state"] != "succeeded"
            or operation["operation_kind"] not in {"log", "diff", "blame"}
            or operation["result_hash"] != value["result_hash"]
            or not audit
            or audit["tool_identifier"]
            not in {
                "knowledge_svn_log",
                "knowledge_svn_diff",
                "knowledge_svn_blame",
                "knowledge_get_source_operation",
            }
            or json_value(audit["business_response_json"]).get("operation_id") != operation["id"]
        ):
            raise CodeKnowledgeError("CODE_EVIDENCE_UNVERIFIED")
        request = json_value(operation["request_json"])
        record.update(
            operation_id=operation["id"],
            result_hash=value["result_hash"],
            from_revision=operation["from_revision"],
            to_revision=operation["to_revision"],
            peg_revision=operation["peg_revision"],
            relative_path=request.get("path"),
        )
    insert(
        store.db,
        "code_evidence",
        record,
        conflict="ON CONFLICT(analysis_id,evidence_hash) DO NOTHING",
    )
    return {"evidence_id": identifier, "svn_revision": context.revision}
