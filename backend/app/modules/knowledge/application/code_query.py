"""Authorized version queries through the existing published knowledge resource boundary."""

from dataclasses import asdict
from typing import Any

from cryptography.fernet import Fernet

from app.modules.knowledge.application.code_behavior import CodeBehaviorReader, _bounded
from app.modules.knowledge.application.content_access import CodeContentRepository
from app.modules.knowledge.application.ports import PrincipalAccess, CodeHistoryPort
from app.modules.knowledge.application.principal import PrincipalToken
from app.modules.knowledge.application.resource_service import KnowledgeResourceReader
from app.modules.knowledge.application.retrieval_budget import knowledge_entry
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError, validate
from app.modules.knowledge.domain.code_history import history_intervals
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.normalization import digest
from app.shared.code_knowledge_tool_contracts import GET_INPUT, COMPARE_INPUT


class CodeKnowledgeQuery:
    def __init__(
        self,
        access: PrincipalAccess,
        resources: KnowledgeResourceReader,
        *,
        history: CodeHistoryPort | None = None,
    ) -> None:
        self.access, self.resources = access, resources
        self.history = history
        self.cursors = Fernet(Fernet.generate_key())

    @knowledge_entry
    def invoke(self, *, tool: str, token: PrincipalToken, arguments: Any) -> dict[str, Any]:
        if tool not in {"knowledge_get_behavior", "knowledge_compare_behavior"}:
            raise CodeKnowledgeError("code_query_tool_invalid")
        validate(arguments, GET_INPUT if tool == "knowledge_get_behavior" else COMPARE_INPUT)
        access = self.access.authenticate(token, tool)
        base = arguments["knowledge_base_id"]
        if base not in access.knowledge_base_ids:
            raise KnowledgeGovernanceError("knowledge_job_denied")
        budget = self.access.budget(access.job_id)
        with budget.activate():
            pin = self.resources.resolve(base)
            with self.resources.content_for(pin) as content:
                store = content.code
                if (
                    store is None
                    or content.records.get("source", pin.source_id)["source_system"] != "code"
                ):
                    raise CodeKnowledgeError("code_source_unavailable")

                def authorize(base_id: str, snapshot_id: str) -> str:
                    budget.check()
                    if base_id != base or self.access.authenticate(token, tool) != access:
                        raise KnowledgeGovernanceError("knowledge_authorization_changed")
                    self.resources.recheck(pin)
                    snapshot = store.snapshot(base, snapshot_id)
                    if snapshot["source_id"] != pin.source_id:
                        raise CodeKnowledgeError("code_snapshot_unavailable")
                    return digest([asdict(access), asdict(pin)])

                reader = CodeBehaviorReader(store, authorize)
                reader.cursors = self.cursors
                if tool == "knowledge_get_behavior":
                    result = reader.get(
                        base,
                        arguments["snapshot_id"],
                        arguments["knowledge_id"],
                        cursor=arguments.get("cursor"),
                    )
                elif self.history is not None:
                    result = self.history.code_history(
                        token=token,
                        request={
                            "action": arguments.get("mode", "compare"),
                            "resource_revision_id": pin.revision_id,
                            "arguments": arguments,
                        },
                    )
                else:
                    result = self._compare(reader, store, arguments)
                budget.check()
                if self.access.authenticate(token, tool) != access:
                    raise KnowledgeGovernanceError("knowledge_authorization_changed")
                self.resources.recheck(pin)
                _bounded(result)
                return result

    def _compare(
        self, reader: CodeBehaviorReader, store: CodeContentRepository, args: dict[str, Any]
    ) -> dict[str, Any]:
        base, key = args["knowledge_base_id"], args["knowledge_id"]
        before, after = (
            store.resolve(base, args["from_version"]),
            store.resolve(base, args["to_version"]),
        )
        mode = args.get("mode", "compare")
        if before["status"] != "READY" or after["status"] != "READY":
            return {
                "mode": mode,
                "status": "VERSION_UNAVAILABLE",
                "from_version": before,
                "to_version": after,
            }
        if mode == "compare":
            return {
                "mode": mode,
                **reader.compare(base, key, before["snapshot_id"], after["snapshot_id"]),
            }
        if args["from_version"]["kind"] != "svn" or args["to_version"]["kind"] != "svn":
            raise CodeKnowledgeError("code_history_requires_svn")
        lower, upper = args["from_version"]["revision"], args["to_version"]["revision"]
        facts = store.history_facts(base, lower, upper)
        # Always validate both endpoint identities, including an empty ledger or range.
        reader.compare(base, key, before["snapshot_id"], after["snapshot_id"])
        checked = {}
        previous = lower
        for revision in facts["revisions"]:
            left = store.resolve(base, {"kind": "svn", "revision": previous})
            right = store.resolve(base, {"kind": "svn", "revision": revision})
            if left["status"] == right["status"] == "READY":
                value = reader.compare(base, key, left["snapshot_id"], right["snapshot_id"])
                checked[revision] = {
                    "from_revision": previous,
                    **{
                        name: value[name]
                        for name in (
                            "classification",
                            "changed_fields",
                            "from_snapshot_id",
                            "to_snapshot_id",
                        )
                    },
                    "before_evidence": value["before"]["evidence"],
                    "after_evidence": value["after"]["evidence"],
                }
            previous = revision
        ledger_complete = facts["ledger_complete"]
        tail_gap = None
        if previous < upper:
            tail = store.resolve(base, {"kind": "svn", "revision": previous})
            if tail["status"] != "READY":
                tail_gap = {"after_revision": previous, "through_revision": upper}
            else:
                comparison = reader.compare(base, key, tail["snapshot_id"], after["snapshot_id"])
                if comparison["classification"] in {"semantic", "identity_unresolved"}:
                    # A change after the last recorded relevant commit disproves completeness.
                    # Never attribute it to the requested upper bound or report unchanged.
                    ledger_complete = False
        result = {
            "mode": "history",
            "knowledge_id": key,
            "from_revision": lower,
            "to_revision": upper,
            "ledger_complete": ledger_complete,
            **history_intervals(
                lower=lower,
                upper=upper,
                relevant_revisions=facts["revisions"],
                checked=checked,
                ledger_complete=ledger_complete,
            ),
        }
        if tail_gap is not None and ledger_complete:
            result["unresolved_intervals"].append(tail_gap)
            result["complete"] = False
        if store.history_facts(base, lower, upper) != facts:
            raise CodeKnowledgeError("code_history_ledger_changed")
        return result
