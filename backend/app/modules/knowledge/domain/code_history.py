"""Conservative structural comparison, including non-monotonic checked history."""

from __future__ import annotations

from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError


def semantic_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: semantic_value(item)
            for key, item in value.items()
            if key not in {"evidence_ids", "summary", "title"}
        }
    if isinstance(value, list):
        return [semantic_value(item) for item in value]
    return value


def compare_records(
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    old_relations: list[dict[str, Any]],
    new_relations: list[dict[str, Any]],
) -> dict[str, Any]:
    if (
        old["business_key"] != new["business_key"]
        or old["identity_state"] != "confirmed"
        or new["identity_state"] != "confirmed"
    ):
        return {"classification": "identity_unresolved", "changed_fields": []}
    before, after = semantic_value(old), semantic_value(new)

    # Relation order and surrogate identity are not business semantics.
    def edges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        values = [
            {
                key: semantic_value(value)
                for key, value in row.items()
                if key not in {"id", "evidence_ids"}
            }
            for row in rows
        ]
        return sorted(values, key=lambda row: (row["from_key"], row["kind"], row["to_key"]))

    before["relations"], after["relations"] = edges(old_relations), edges(new_relations)
    fields = sorted(
        key for key in before.keys() | after.keys() if before.get(key) != after.get(key)
    )
    classification = "semantic" if fields else "unchanged"
    if not fields and (old != new or old_relations != new_relations):
        classification = "evidence_only"
    return {"classification": classification, "changed_fields": fields}


def history_intervals(
    *,
    lower: int,
    upper: int,
    relevant_revisions: list[int],
    checked: dict[int, dict[str, Any]],
    ledger_complete: bool,
) -> dict[str, Any]:
    """Caller supplies a durable complete SVN ledger; endpoints alone never prove history.

    A checked item contains a comparison against the immediately preceding relevant
    revision (or lower bound), established from the two fixed source snapshots.
    """
    if lower < 0 or upper < lower or any(not lower < rev <= upper for rev in relevant_revisions):
        raise CodeKnowledgeError("code_history_range_invalid")
    revisions = sorted(set(relevant_revisions))
    changes, gaps = [], []
    previous = lower
    for revision in revisions:
        result = checked.get(revision)
        verified = bool(
            result
            and result.get("from_revision") == previous
            and result.get("classification") != "identity_unresolved"
        )
        if not verified:
            gaps.append({"after_revision": previous, "through_revision": revision})
        elif result and result["classification"] != "unchanged":
            changes.append(
                {
                    **result,
                    "to_revision": revision,
                    "changed_at_revision": revision if ledger_complete else None,
                    "exact_revision_proven": ledger_complete,
                }
            )
        previous = revision
    if not ledger_complete:
        gaps = [{"after_revision": lower, "through_revision": upper}]
    return {
        "changes": changes,
        "unresolved_intervals": gaps,
        "complete": ledger_complete and not gaps,
        "checked_revisions": [rev for rev in revisions if rev in checked],
    }
