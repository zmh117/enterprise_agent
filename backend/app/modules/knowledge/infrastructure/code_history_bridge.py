"""Control-plane authorization for original-Job SVN operations and derived answer writes."""

from datetime import UTC, datetime
from typing import Any

from cryptography.fernet import Fernet

from app.modules.agent.infrastructure.runtime_pool_store import database_now
from app.modules.knowledge.application.ports import PrincipalAccess, ReadabilityBridgeGateway
from app.modules.knowledge.application.resource_service import KnowledgeResourceReader
from app.modules.knowledge.application.retrieval_budget import knowledge_entry
from app.modules.knowledge.domain.code_answers import (
    CodeAnalysisContext,
    code_authorization_hash,
    utc_time,
)
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError, ID, obj, validate
from app.modules.knowledge.domain.code_svn_requests import history_request
from app.modules.knowledge.domain.code_user_revision import user_svn_revisions
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_answer_store import CodeAnswerStore
from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.modules.knowledge.infrastructure.code_operation_store import CodeOperationStore
from app.modules.knowledge.infrastructure.code_result_client import CodeResultClient
from app.modules.knowledge.infrastructure.code_search_receipts import CodeSearchReceipts
from app.shared.code_answer_tool_contracts import CODE_TOOL_SCHEMAS, REVISION
from app.shared.database import Database

SEARCH_CONTEXT = obj(
    {
        "action": {"const": "search_context"},
        "knowledge_base_id": ID,
        "resource_revision_id": ID,
        "requested_revision": REVISION,
    }
)
TOOL_REQUEST = obj(
    {
        "action": {"const": "tool"},
        "tool": {"enum": list(CODE_TOOL_SCHEMAS)},
        "resource_revision_id": ID,
        "arguments": {"type": "object"},
    }
)


class CodeHistoryBridge:
    def __init__(
        self,
        database: Database,
        gateway: ReadabilityBridgeGateway,
        access: PrincipalAccess,
        resources: KnowledgeResourceReader,
        audit: Any,
        *,
        results: CodeResultClient | None = None,
    ) -> None:
        self.db, self.gateway, self.access, self.resources, self.audit = (
            database,
            gateway,
            access,
            resources,
            audit,
        )
        self.operations, self.answers = CodeOperationStore(database), CodeAnswerStore(database)
        self.receipts, self.results = CodeSearchReceipts(database), results
        self.cursors = Fernet(Fernet.generate_key())

    def authenticate(self, service_token: str, knowledge_token: str) -> Any:
        return self.gateway.authenticate(service_token, knowledge_token)

    def _user_version(self, access: Any, revision: int) -> None:
        # Only this control-plane path can inspect the private input; it never returns,
        # logs or copies message text to code knowledge/audit records.
        row = self.db.execute_one(
            "SELECT m.content FROM agent_job j JOIN agent_message m ON m.id=j.input_message_id "
            "AND m.job_id=j.id AND m.role='user' AND m.content_status='READY' "
            "WHERE j.id=? AND j.internal_user_id=? AND j.status='RUNNING'",
            (access.job_id, access.actor_id),
        )
        if not row or revision not in user_svn_revisions(row["content"]):
            raise CodeKnowledgeError("SVN_REVISION_REQUIRED")

    @knowledge_entry
    def check(
        self,
        *,
        service_token: str,
        knowledge_token: str,
        request: dict[str, Any],
        deadline_ms: int | None = None,
    ) -> dict[str, Any]:
        validate(request, {"oneOf": [SEARCH_CONTEXT, TOOL_REQUEST]})
        search = request["action"] == "search_context"
        tool = "knowledge_search" if search else request["tool"]
        if not search:
            validate(request["arguments"], CODE_TOOL_SCHEMAS[tool][0])
        access = self.authenticate(service_token, knowledge_token)
        if self.access.authenticate(knowledge_token, tool) != access:
            raise KnowledgeGovernanceError("knowledge_authorization_changed")
        base = request["knowledge_base_id"] if search else request["arguments"]["knowledge_base_id"]
        if base not in access.knowledge_base_ids:
            raise KnowledgeGovernanceError("knowledge_job_denied")
        budget = self.gateway.budget(access.job_id, deadline_ms=deadline_ms)
        with budget.activate():
            pin = self.resources.resolve(base)
            if pin.revision_id != request["resource_revision_id"]:
                raise KnowledgeGovernanceError("knowledge_resource_changed")
            config = self.resources.store.code_configuration(pin.revision_id)
            if not config or config["source_id"] != pin.source_id:
                raise CodeKnowledgeError("CODE_CONFIGURATION_CHANGED")
            if search:
                self._user_version(access, request["requested_revision"])
                result = {
                    "requested_revision": request["requested_revision"],
                    "source_id": pin.source_id,
                    "checkout_id": config["checkout_id"],
                }
            elif tool == "knowledge_svn_update":
                result = self._begin(access, pin, config, request["arguments"])
            elif tool == "knowledge_get_code_answer":
                raise CodeKnowledgeError("CODE_QUERY_TOOL_INVALID")
            elif tool == "knowledge_get_source_operation":
                operation = self.operations.row(
                    "code_svn_operation", request["arguments"]["operation_id"]
                )
                if not operation["analysis_id"] or operation["job_id"] != access.job_id:
                    raise CodeKnowledgeError("CODE_OPERATION_MISMATCH")
                analysis = self.operations.row("code_analysis", operation["analysis_id"])
                context = self._context(access, pin, config, analysis)
                result = self._view(context, analysis, config, operation)
            else:
                args = request["arguments"]
                analysis = self.operations.row("code_analysis", args["analysis_id"])
                context = self._context(access, pin, config, analysis)
                if tool == "knowledge_save_code_answer":
                    # Runtime must have stopped new native reads and drained in-flight
                    # calls via its authenticated host endpoint before this mutation.
                    result = self.answers.save(
                        context,
                        analysis["id"],
                        question=args["question"],
                        visibility_scope={"paths": config["allowed_paths_json"]},
                        result=args["result"],
                        request_key=args["request_key"],
                    )
                else:
                    operation = self._history(context, analysis, config, tool, args)
                    result = self._view(context, analysis, config, operation)
            budget.check()
            if (
                self.authenticate(service_token, knowledge_token) != access
                or self.access.authenticate(knowledge_token, tool) != access
            ):
                raise KnowledgeGovernanceError("knowledge_authorization_changed")
            self.resources.recheck(pin)
            return result

    def _context(
        self, access: Any, pin: Any, config: dict[str, Any], analysis: dict[str, Any]
    ) -> CodeAnalysisContext:
        if (
            analysis["job_id"] != access.job_id
            or analysis["knowledge_base_id"] != pin.knowledge_base_id
            or analysis["config_revision_id"] != pin.revision_id
            or analysis["source_id"] != pin.source_id
            or analysis["checkout_id"] != config["checkout_id"]
            or analysis["authorization_hash"] != code_authorization_hash(access)
        ):
            raise CodeKnowledgeError("CODE_ANALYSIS_MISMATCH")
        context = CodeAnalysisContext(
            job_id=access.job_id,
            actor_id=access.actor_id,
            invocation_id=analysis["invocation_id"],
            owner_instance_id=analysis["owner_instance_id"],
            knowledge_base_id=pin.knowledge_base_id,
            config_revision_id=pin.revision_id,
            source_id=pin.source_id,
            checkout_id=config["checkout_id"],
            revision=analysis["requested_revision"],
            exact_search_id=analysis["exact_search_id"],
            question_hash=analysis["question_hash"],
            authorization_hash=analysis["authorization_hash"],
            deadline_at=utc_time(analysis["deadline_at"]).isoformat(),
        )
        self.operations._owner(context)
        self.operations._configuration(context)
        return context

    def _begin(
        self, access: Any, pin: Any, config: dict[str, Any], args: dict[str, Any]
    ) -> dict[str, Any]:
        receipt = self.receipts.read(args["search_id"], access=access, pin=pin)
        if (
            args["source_id"] != pin.source_id
            or args["checkout_id"] != config["checkout_id"]
            or args["revision"] != receipt["requested_revision"]
        ):
            raise CodeKnowledgeError("CODE_SEARCH_CONTEXT_CHANGED")
        exact = receipt
        if receipt["version_mode"] != "exact":
            exact = self.receipts.read(receipt["exact_search_id"], access=access, pin=pin)
        if (
            exact["version_mode"] != "exact"
            or exact["requested_revision"] != args["revision"]
            or exact["question_hash"] != receipt["question_hash"]
        ):
            raise CodeKnowledgeError("CODE_SUCCESSFUL_SEARCH_REQUIRED")
        invocation = self.db.execute_one(
            "SELECT instance_id,execution_deadline_at FROM agent_runtime_invocation "
            "WHERE job_id=? AND invocation_id=? AND app_user_id=? AND state='RUNNING'",
            (access.job_id, receipt["invocation_id"], access.actor_id),
        )
        if not invocation or invocation["instance_id"] is None:
            raise CodeKnowledgeError("CODE_EXECUTION_MISMATCH")
        self._user_version(access, args["revision"])
        deadline = min(
            utc_time(invocation["execution_deadline_at"]),
            datetime.fromtimestamp(min(receipt["deadline_ms"], exact["deadline_ms"]) / 1000, UTC),
        )
        context = CodeAnalysisContext(
            job_id=access.job_id,
            actor_id=access.actor_id,
            invocation_id=receipt["invocation_id"],
            owner_instance_id=invocation["instance_id"],
            knowledge_base_id=pin.knowledge_base_id,
            config_revision_id=pin.revision_id,
            source_id=pin.source_id,
            checkout_id=config["checkout_id"],
            revision=args["revision"],
            exact_search_id=exact["search_id"],
            question_hash=exact["question_hash"],
            authorization_hash=code_authorization_hash(access),
            deadline_at=deadline.isoformat(),
        )
        previous = self.db.execute_one(
            f"SELECT o.error_code FROM {self.operations.t('code_svn_operation')} o "
            f"JOIN {self.operations.t('code_checkout')} c ON c.id=o.checkout_id "
            "WHERE o.job_id=? AND o.invocation_id=? AND o.config_revision_id=? "
            "AND o.checkout_id=? AND o.target_revision=? AND o.checkout_generation=c.generation "
            "AND o.state='failed' AND o.error_code IN "
            "('CODE_CHECKOUT_IDENTITY_CHANGED','CODE_CHECKOUT_SOURCE_MISMATCH',"
            "'CODE_CHECKOUT_SCOPE_CHANGED','CODE_SVN_AUTH_FAILED','CODE_SVN_CERTIFICATE_INVALID') LIMIT 1",
            (
                context.job_id,
                context.invocation_id,
                context.config_revision_id,
                context.checkout_id,
                context.revision,
            ),
        )
        if previous:
            raise CodeKnowledgeError(previous["error_code"])
        analysis = self.operations.begin(context, args["request_key"])
        operation = self.db.execute_one(
            f"SELECT * FROM {self.operations.t('code_svn_operation')} WHERE analysis_id=? AND request_key=?",
            (analysis["id"], analysis["request_key"]),
        )
        assert operation is not None
        return self._view(context, analysis, config, operation)

    def _history(
        self,
        context: CodeAnalysisContext,
        analysis: dict[str, Any],
        config: dict[str, Any],
        tool: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        kind = tool.removeprefix("knowledge_svn_")
        raw = {
            k: v
            for k, v in args.items()
            if k
            not in {
                "knowledge_base_id",
                "analysis_id",
                "request_key",
                "cursor",
            }
        }
        if kind == "info":
            raw.setdefault("path", "")
        normalized = history_request(
            kind, raw, upper=context.revision, paths=config["allowed_paths_json"]
        )
        deadline = None
        if args.get("cursor"):
            try:
                cursor = json_value(self.cursors.decrypt(args["cursor"].encode()).decode())
                if (
                    cursor["context"] != context.fingerprint()
                    or cursor["kind"] != kind
                    or cursor["request"] != self._request_hash(normalized)
                    or utc_time(cursor["deadline_at"]) <= database_now(self.db)
                ):
                    raise ValueError
                raw.update(cursor["page"])
                deadline = cursor["deadline_at"]
            except Exception:
                raise CodeKnowledgeError("CODE_HISTORY_CURSOR_INVALID") from None
        return self.operations.submit_history(
            context,
            analysis["id"],
            kind=kind,
            request=raw,
            request_key=args["request_key"],
            deadline_at=deadline,
        )

    @staticmethod
    def _request_hash(request: dict[str, Any]) -> str:
        return digest({k: v for k, v in request.items() if k not in {"offset", "before"}})

    def _view(
        self,
        context: CodeAnalysisContext,
        analysis: dict[str, Any],
        config: dict[str, Any],
        operation: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            operation["analysis_id"] != analysis["id"]
            or operation["job_id"] != context.job_id
            or operation["invocation_id"] != context.invocation_id
        ):
            raise CodeKnowledgeError("CODE_OPERATION_MISMATCH")
        self.operations._owner(context)
        value = {
            "operation_id": operation["id"],
            "operation_kind": operation["operation_kind"],
            "state": operation["state"],
            "analysis_id": analysis["id"],
            "svn_revision": context.revision,
            "error_code": operation["error_code"],
        }
        if operation["state"] != "succeeded":
            return value
        reader = self.operations.require_reader(context, analysis["id"])
        request = json_value(operation["request_json"])
        admission = operation["operation_kind"] in {"info", "update"} and not request.get("target")
        if admission:
            result = json_value(operation["result_json"])
        else:
            if self.results is None:
                raise CodeKnowledgeError("CODE_RESULT_UNAVAILABLE")
            remaining = (utc_time(operation["deadline_at"]) - database_now(self.db)).total_seconds()
            try:
                result = self.results.read(
                    operation["id"],
                    operation["claim_version"],
                    result_hash=operation["result_hash"],
                    remaining=remaining,
                )
            except CodeKnowledgeError as exc:
                if exc.code != "CODE_RESULT_EXPIRED":
                    raise
                replay = self.operations.replay_history(context, operation["id"])
                return {**value, "state": replay["state"]}
            self.operations.require_reader(context, analysis["id"])
        value["result"] = result
        if admission:
            checkout = self.operations.row("code_checkout", context.checkout_id)
            value["source_access"] = {
                "analysis_id": analysis["id"],
                "source_id": context.source_id,
                "checkout_id": context.checkout_id,
                "revision": context.revision,
                "generation": reader["generation"],
                "directory": checkout["relative_dir"],
                "allowed_paths": config["allowed_paths_json"],
            }
        page = {}
        if result.get("has_more") and result.get("next_revision") is not None:
            page["before_revision"] = result["next_revision"]
        if result.get("has_more") and result.get("next_offset") is not None:
            page["offset"] = result["next_offset"]
        value["next_cursor"] = (
            self.cursors.encrypt(
                canonical_json(
                    {
                        "context": context.fingerprint(),
                        "kind": operation["operation_kind"],
                        "request": self._request_hash(request),
                        "deadline_at": utc_time(operation["deadline_at"]).isoformat(),
                        "page": page,
                    }
                ).encode()
            ).decode()
            if page
            else None
        )
        return value
