"""Persist safe save outcomes beside analysis, independently of answer delivery/indexing."""

from typing import Any

from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.modules.knowledge.infrastructure.storage import table
from app.modules.knowledge.domain.normalization import canonical_json
from app.shared.database import Database
from app.shared.knowledge_tool_errors import knowledge_failure
from app.shared.tool_response_summary import tool_response_summary


def record_save_outcomes(db: Database, job_id: str, invocation_id: str) -> None:
    analyses = db.execute(
        f"SELECT id,state,saved_revision_id,save_request_hash,report_json "
        f"FROM {table(db, 'code_analysis')} WHERE job_id=? AND invocation_id=? ORDER BY created_at,id",
        (job_id, invocation_id),
    )
    if not analyses:
        return
    dispatched = db.execute(
        "SELECT t.status,t.response_summary,m.business_request_json FROM mcp_operation_audit m "
        "JOIN agent_tool_call t ON t.id=m.agent_tool_call_id "
        "WHERE m.job_id=? AND m.invocation_id=? AND m.server_code='knowledge-mcp' "
        "AND m.tool_identifier='knowledge_save_code_answer' AND m.parent_audit_id IS NULL "
        "ORDER BY m.created_at,m.id LIMIT 1001",
        (job_id, invocation_id),
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    unlinked = 0
    for call in dispatched:
        request = json_value(call["business_request_json"])
        identifier = request.get("analysis_id") if isinstance(request, dict) else None
        if isinstance(identifier, str):
            grouped.setdefault(identifier, []).append(call)
        else:
            unlinked += 1
    for analysis in analyses:
        admitted = bool(
            db.execute_one(
                f"SELECT id FROM {table(db, 'code_svn_operation')} "
                "WHERE analysis_id=? AND operation_kind IN ('info','update') "
                "AND state='succeeded' LIMIT 1",
                (analysis["id"],),
            )
        )
        outcome = _outcome(analysis, grouped.get(analysis["id"], []), admitted=admitted)
        outcome["unlinked_invocation_attempts"] = unlinked
        outcome["attempts_truncated"] = len(dispatched) > 1000
        if (unlinked or len(dispatched) > 1000) and outcome["state"] in {
            "not_attempted",
            "not_ready",
        }:
            outcome["state"] = "unconfirmed"
        report = json_value(analysis["report_json"])
        report["knowledge_save"] = outcome
        db.execute(
            f"UPDATE {table(db, 'code_analysis')} SET report_json=? WHERE id=?",
            (canonical_json(report), analysis["id"]),
        )


def _outcome(
    analysis: dict[str, Any], calls: list[dict[str, Any]], *, admitted: bool
) -> dict[str, Any]:
    failed = [call for call in calls if call["status"] in {"FAILED", "DENIED"}]
    code: str | None = None
    if analysis["saved_revision_id"]:
        state = "saved"
    elif analysis["save_request_hash"] and analysis["state"] in {"partial", "conflicted"}:
        state = "saved_" + analysis["state"]
    elif failed:
        state = "failed"
        summary = tool_response_summary(failed[-1]["response_summary"])
        code = knowledge_failure(summary.get("error_code"))["code"]
    elif calls:
        state = "unconfirmed"
    elif admitted:
        state = "not_attempted"
    else:
        state = "not_ready"
    return {
        "state": state,
        "attempt_scope": "save_service",
        "attempts": min(len(calls), 1000),
        "attempts_truncated": len(calls) > 1000,
        "error_code": code,
    }
