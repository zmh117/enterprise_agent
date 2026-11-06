"""Semantic references of data-only state machines; never evaluate guard expressions."""

from typing import Any
from collections.abc import Sequence

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_identity_catalog import ENTRIES, EVENTS, MACHINES, OBJECTS


def verify_state_definitions(
    definitions: list[dict[str, Any]], known: Sequence[dict[str, Any]] = ()
) -> None:
    by_key: dict[tuple[str, str], str] = {}
    by_value: dict[tuple[str, str], str] = {}
    for state in [*known, *definitions]:
        machine, key, raw = state["machine_key"], state["key"], state["raw_value"]
        if (machine, key) in by_key and by_key[machine, key] != raw:
            raise CodeKnowledgeError("code_state_definition_conflict", key)
        if (machine, raw) in by_value and by_value[machine, raw] != key:
            raise CodeKnowledgeError("code_state_identity_conflict", key)
        by_key[machine, key], by_value[machine, raw] = raw, key


def validate_state_machines(
    records: list[dict[str, Any]],
    expected_entries: set[str],
    *,
    known_states: Sequence[dict[str, Any]] = (),
) -> bool:
    """Return whether unresolved FSM semantics block activation after validation."""
    if not expected_entries <= ENTRIES.keys():
        raise CodeKnowledgeError("code_entry_identity_unknown")
    definitions: list[dict[str, Any]] = []
    blocked = False
    for record in records:
        key = record["business_key"]
        entry = next(
            (entry for entry in expected_entries if key == entry or key.startswith(entry + ".")),
            None,
        )
        if entry is None:
            raise CodeKnowledgeError("code_unit_identity_outside_scope", key)
        if record["object_key"] not in OBJECTS or record["kind"] == "object":
            raise CodeKnowledgeError("code_object_identity_unknown", record["object_key"])
        if record["fact_class"] == "identity":
            raise CodeKnowledgeError("code_identity_is_controller_owned", key)
        transition = record["transition"]
        if transition is None:
            continue
        if record["role"] != "backend" or record["fact_class"] != "backend_behavior":
            raise CodeKnowledgeError("code_transition_requires_backend_evidence", key)
        machine, event = (
            MACHINES.get(transition["machine_key"]),
            EVENTS.get(transition["event_key"]),
        )
        if not machine or machine["object_key"] != record["object_key"]:
            raise CodeKnowledgeError("code_machine_object_mismatch", key)
        if not event or event["object_key"] != record["object_key"] or event["entry_id"] != entry:
            raise CodeKnowledgeError("code_event_object_mismatch", key)
        if event["machine_key"] != transition["machine_key"]:
            raise CodeKnowledgeError("code_event_machine_mismatch", key)
        definitions.extend(
            {**state, "machine_key": transition["machine_key"]} for state in record["states"]
        )
        blocked |= _validate_transition(record)
    verify_state_definitions(definitions, known_states)
    return bool(blocked)


def _validate_transition(record: dict[str, Any]) -> bool:
    transition, key = record["transition"], record["business_key"]
    blocked = False
    states = {state["key"]: state for state in record["states"]}
    if len(states) != len(record["states"]):
        raise CodeKnowledgeError("code_duplicate_state_identity", key)
    origins = transition["from_state"]
    if not set(origins["state_keys"]) <= states.keys():
        raise CodeKnowledgeError("code_transition_source_missing", key)
    blocked |= origins["mode"] == "unresolved"
    actions = {action["key"] for action in transition["actions"]}
    if len(actions) != len(transition["actions"]):
        raise CodeKnowledgeError("code_duplicate_action_identity", key)
    failures = {failure["key"] for failure in transition["failures"]}
    if len(failures) != len(transition["failures"]):
        raise CodeKnowledgeError("code_duplicate_failure_identity", key)
    targets = [transition["to_state"]]
    for failure in transition["failures"]:
        if (
            failure["state_after"]["mode"] == "indeterminate"
            and not record["required_runtime_facts"]
        ):
            raise CodeKnowledgeError("code_indeterminate_state_requires_runtime_facts", key)
        if not set(failure["retained_action_keys"]) <= actions:
            raise CodeKnowledgeError("code_failure_action_missing", key)
        targets.append(failure["state_after"])
        blocked |= failure["outcome"] == "unknown"
    for target in targets:
        if target["mode"] == "state" and target["state_key"] not in states:
            raise CodeKnowledgeError("code_transition_target_missing", key)
        blocked |= target["mode"] == "unknown"
    if (
        record["success_boundary"]["phase"] == "accepted"
        and transition["to_state"]["mode"] != "unchanged"
    ):
        raise CodeKnowledgeError("code_acceptance_is_not_state_completion", key)
    return bool(blocked)
