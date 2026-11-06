"""Complete root behavior plus bounded same-snapshot dependency pages.

Authorization is checked before and after each operation through the injected current
resource gate. This service never evaluates code or infers transitive restrictions.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken

from app.modules.knowledge.domain.code_contracts import MAX_RESPONSE_BYTES, CodeKnowledgeError
from app.modules.knowledge.domain.code_history import compare_records
from app.modules.knowledge.domain.normalization import canonical_json


class BehaviorStore(Protocol):
    def read_member(self, base_id: str, snapshot_id: str, document_id: str) -> dict[str, Any]: ...
    def relation_page(
        self, base_id: str, snapshot_id: str, document_id: str, *, after: str = "", limit: int = 51
    ) -> list[dict[str, Any]]: ...


class CodeBehaviorReader:
    def __init__(self, store: BehaviorStore, authorize: Callable[[str, str], str]) -> None:
        self.store, self.authorize = store, authorize
        self.cursors = Fernet(Fernet.generate_key())

    def _state(self, cursor: str | None, binding: list[str], root_id: str) -> dict[str, Any]:
        if cursor is None:
            return {
                "binding": binding,
                "queue": [[root_id, 0, ""]],
                "seen": [root_id],
                "incomplete": False,
            }
        if len(cursor) > 32_000:
            raise CodeKnowledgeError("code_cursor_invalid")
        try:
            state: dict[str, Any] = json.loads(self.cursors.decrypt(cursor.encode(), ttl=300))
            if state["binding"] != binding:
                raise ValueError
            return state
        except (InvalidToken, ValueError, KeyError, UnicodeError):
            raise CodeKnowledgeError("code_cursor_invalid") from None

    def get(
        self, base_id: str, snapshot_id: str, knowledge_id: str, *, cursor: str | None = None
    ) -> dict[str, Any]:
        authorization = self.authorize(base_id, snapshot_id)
        binding = [base_id, snapshot_id, knowledge_id, authorization]
        state = self._state(cursor, binding, knowledge_id)
        root = self.store.read_member(base_id, snapshot_id, knowledge_id)
        result: dict[str, Any] = {
            "knowledge_base_id": base_id,
            "snapshot_id": snapshot_id,
            "root": root,
            "nodes": [],
            "relations": [],
            "unexpanded": [],
            "prior_pages_incomplete": bool(state.get("incomplete")),
        }
        self._expand(base_id, snapshot_id, state, result)
        more = bool(state["queue"])
        state["incomplete"] = bool(state.get("incomplete")) or bool(result["unexpanded"])
        result.update(
            partial=more or state["incomplete"],
            has_more=more,
            next_cursor=self.cursors.encrypt(canonical_json(state).encode()).decode()
            if more
            else None,
            content_scope="complete_root_bounded_dependencies",
        )
        _bounded(result)
        if self.authorize(base_id, snapshot_id) != authorization:
            raise CodeKnowledgeError("code_authorization_changed")
        return result

    def _expand(
        self, base_id: str, snapshot_id: str, state: dict[str, Any], result: dict[str, Any]
    ) -> None:
        seen = set(state["seen"])
        while state["queue"] and len(result["relations"]) < 50:
            node, depth, after = state["queue"].pop(0)
            if depth >= 3:
                remaining = self.store.relation_page(base_id, snapshot_id, node, limit=1)
                if remaining:
                    result["unexpanded"].append({"knowledge_id": node, "reason": "depth_limit"})
                continue
            limit = 50 - len(result["relations"])
            edges = self.store.relation_page(
                base_id, snapshot_id, node, after=after, limit=limit + 1
            )
            for edge in edges[:limit]:
                result["relations"].append(edge)
                target = edge["target_id"]
                if target in seen:
                    continue
                if len(seen) >= 100:
                    result["unexpanded"].append({"knowledge_id": target, "reason": "node_limit"})
                    continue
                seen.add(target)
                result["nodes"].append(self.store.read_member(base_id, snapshot_id, target))
                state["queue"].append([target, depth + 1, ""])
            if len(edges) > limit:
                state["queue"].insert(0, [node, depth, edges[limit - 1]["relation_id"]])
        state["seen"] = sorted(seen)

    def compare(
        self, base_id: str, knowledge_id: str, from_snapshot: str, to_snapshot: str
    ) -> dict[str, Any]:
        before_auth = self.authorize(base_id, from_snapshot)
        after_auth = self.authorize(base_id, to_snapshot)
        before = self.store.read_member(base_id, from_snapshot, knowledge_id)
        after = self.store.read_member(base_id, to_snapshot, knowledge_id)
        old_relations = self._all_relations(base_id, from_snapshot, knowledge_id)
        new_relations = self._all_relations(base_id, to_snapshot, knowledge_id)
        comparison = compare_records(
            before["knowledge"],
            after["knowledge"],
            old_relations=old_relations,
            new_relations=new_relations,
        )
        if comparison["classification"] == "unchanged" and before["evidence"] != after["evidence"]:
            comparison["classification"] = "evidence_only"
        result = {
            "knowledge_id": knowledge_id,
            "from_snapshot_id": from_snapshot,
            "to_snapshot_id": to_snapshot,
            **comparison,
            "before": before,
            "after": after,
            "old_relations": old_relations,
            "new_relations": new_relations,
            "changed_at_revision": None,
            "exact_revision_proven": False,
        }
        _bounded(result)
        if (
            self.authorize(base_id, from_snapshot) != before_auth
            or self.authorize(base_id, to_snapshot) != after_auth
        ):
            raise CodeKnowledgeError("code_authorization_changed")
        return result

    def _all_relations(
        self, base_id: str, snapshot_id: str, knowledge_id: str
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        after = ""
        while len(result) <= 1000:
            rows = self.store.relation_page(
                base_id, snapshot_id, knowledge_id, after=after, limit=101
            )
            result.extend(row["relation"] for row in rows)
            if len(rows) < 101:
                return result
            after = rows[-1]["relation_id"]
        raise CodeKnowledgeError("code_compare_relations_limit")


def _bounded(value: dict[str, Any]) -> None:
    if len(canonical_json(value).encode()) > MAX_RESPONSE_BYTES:
        raise CodeKnowledgeError("code_behavior_response_too_large")
