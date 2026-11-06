"""Authorized derived-cache requests, handled in the control plane, never MCP SQL writes."""

from typing import Any

from app.modules.knowledge.application.code_query import CodeKnowledgeQuery
from app.modules.knowledge.application.ports import PrincipalAccess, ReadabilityBridgeGateway
from app.modules.knowledge.application.resource_service import KnowledgeResourceReader
from app.modules.knowledge.application.retrieval_budget import knowledge_entry
from app.modules.knowledge.domain.code_contracts import (
    CodeKnowledgeError,
    ID,
    REVISION,
    obj,
    validate,
)
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.infrastructure.code_repository import CodeRepository, decoded
from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository
from app.modules.knowledge.infrastructure.storage import insert, source_lock, table
from app.shared.code_knowledge_tool_contracts import COMPARE_INPUT
from app.shared.database import Database

VERSION_REQUEST = obj(
    {
        "action": {"const": "version"},
        "knowledge_base_id": ID,
        "resource_revision_id": ID,
        "revision": REVISION,
    }
)
HISTORY_REQUEST = obj(
    {
        "action": {"enum": ["history", "compare"]},
        "resource_revision_id": ID,
        "arguments": COMPARE_INPUT,
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
    ) -> None:
        self.db, self.gateway, self.access, self.resources, self.audit = (
            database,
            gateway,
            access,
            resources,
            audit,
        )
        self.repo, self.builds = CodeRepository(database), CodeBuildRepository(database)

    def authenticate(self, service_token: str, knowledge_token: str) -> Any:
        return self.gateway.authenticate(service_token, knowledge_token)

    @knowledge_entry
    def check(
        self,
        *,
        service_token: str,
        knowledge_token: str,
        request: dict[str, Any],
        deadline_ms: int | None = None,
    ) -> dict[str, Any]:
        validate(request, {"oneOf": [VERSION_REQUEST, HISTORY_REQUEST]})
        tool = (
            "knowledge_search" if request["action"] == "version" else "knowledge_compare_behavior"
        )
        context = self.authenticate(service_token, knowledge_token)
        if self.access.authenticate(knowledge_token, tool) != context:
            raise KnowledgeGovernanceError("knowledge_authorization_changed")
        base = (
            request["knowledge_base_id"]
            if tool == "knowledge_search"
            else request["arguments"]["knowledge_base_id"]
        )
        if base not in context.knowledge_base_ids:
            raise KnowledgeGovernanceError("knowledge_job_denied")
        budget = self.gateway.budget(context.job_id, deadline_ms=deadline_ms)
        with budget.activate():
            pin = self.resources.resolve(base)
            if pin.revision_id != request["resource_revision_id"]:
                raise KnowledgeGovernanceError("knowledge_resource_changed")
            binding = self.repo.binding(pin.source_id)
            if binding["knowledge_base_id"] != base:
                raise CodeKnowledgeError("code_source_unavailable")
            if tool == "knowledge_compare_behavior":
                args = request["arguments"]
                if args.get("mode", "compare") != request["action"]:
                    raise CodeKnowledgeError("code_contract_invalid")
                if request["action"] == "history" and any(
                    args[name]["kind"] != "svn" for name in ("from_version", "to_version")
                ):
                    raise CodeKnowledgeError("code_history_requires_svn")
                result = CodeKnowledgeQuery(self.access, self.resources).invoke(
                    tool=tool, token=knowledge_token, arguments=args
                )
            else:
                result = self.repo.resolve(base, {"kind": "svn", "revision": request["revision"]})
            budget.check()
            with source_lock(self.db, pin.source_id), self.db.unit_of_work():
                if (
                    self.authenticate(service_token, knowledge_token) != context
                    or self.access.authenticate(knowledge_token, tool) != context
                ):
                    raise KnowledgeGovernanceError("knowledge_authorization_changed")
                self.resources.recheck(pin)
                if self.repo.binding(pin.source_id)["config_hash"] != binding["config_hash"]:
                    raise CodeKnowledgeError("code_source_configuration_changed")
                if tool == "knowledge_search" and result["status"] == "BUILD_REQUIRED":
                    result = {
                        **result,
                        **self.builds.demand(pin.source_id, request["revision"], context.actor_id),
                    }
                elif tool == "knowledge_compare_behavior":
                    if request["action"] == "history":
                        self._history(binding, args, result, context.actor_id)
                    self._missing_endpoints(binding, args, result, context.actor_id)
                budget.check()
                self.audit.record(
                    "knowledge.code.cache_requested",
                    status="success",
                    summary="已核验版本缓存需求",
                    actor_id=context.actor_id,
                    job_id=context.job_id,
                    payload={"knowledge_base_id": base, "action": request["action"]},
                )
            return result

    def _missing_endpoints(
        self, binding: dict[str, Any], args: dict[str, Any], result: dict[str, Any], actor_id: str
    ) -> None:
        if result.get("status") != "VERSION_UNAVAILABLE":
            return
        for name in ("from_version", "to_version"):
            if args[name]["kind"] == "svn" and result[name]["status"] == "BUILD_REQUIRED":
                result[name] = {
                    **result[name],
                    **self.builds.demand(binding["source_id"], args[name]["revision"], actor_id),
                }

    def _history(
        self, binding: dict[str, Any], args: dict[str, Any], result: dict[str, Any], actor_id: str
    ) -> None:
        base, key = args["knowledge_base_id"], args["knowledge_id"]
        lower, upper = args["from_version"]["revision"], args["to_version"]["revision"]
        facts = self.repo.history_facts(base, lower, upper)
        before, after = (
            self.repo.resolve(base, args["from_version"]),
            self.repo.resolve(base, args["to_version"]),
        )
        # Proof and progress are computed here from immutable members, never supplied by a caller/model.
        if (
            before["status"] == after["status"] == "READY"
            and result.get("mode") == "history"
            and "ledger_complete" in result
        ):
            prior = self.db.execute_one(
                f"select ledger_complete,comparison_json from {table(self.db, 'code_history_check')} where source_id=? and document_id=? and config_hash=? and from_revision=? and to_revision=?",
                (binding["source_id"], key, binding["config_hash"], lower, upper),
            )
            progress = decoded(prior["comparison_json"]).get("ledger_progress") if prior else None
            insert(
                self.db,
                "code_history_check",
                dict(
                    source_id=binding["source_id"],
                    document_id=key,
                    config_hash=binding["config_hash"],
                    from_revision=lower,
                    to_revision=upper,
                    from_snapshot_id=before["snapshot_id"],
                    to_snapshot_id=after["snapshot_id"],
                    ledger_complete=int(
                        bool(prior and prior["ledger_complete"]) or result["ledger_complete"]
                    ),
                    comparison_json={
                        **result,
                        **({"ledger_progress": progress} if progress else {}),
                    },
                ),
                conflict="on conflict(source_id,document_id,config_hash,from_revision,to_revision) do update set from_snapshot_id=excluded.from_snapshot_id,to_snapshot_id=excluded.to_snapshot_id,ledger_complete=excluded.ledger_complete,comparison_json=excluded.comparison_json",
            )
        requested = 0
        for revision in sorted({lower, upper, *facts["revisions"]}):
            if (
                self.repo.resolve(base, {"kind": "svn", "revision": revision})["status"]
                == "BUILD_REQUIRED"
            ):
                self.builds.demand(binding["source_id"], revision, actor_id)
                requested += 1
                if requested >= 20:
                    break
