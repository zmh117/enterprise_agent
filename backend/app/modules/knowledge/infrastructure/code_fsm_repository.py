"""Transactional relational projection of immutable, explicitly defined state machines."""

from __future__ import annotations

import json
from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_fsm import verify_state_definitions
from app.modules.knowledge.domain.code_identity_catalog import (
    CATALOG_HASH,
    EVENTS,
    MACHINES,
    OBJECTS,
)
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.storage import insert, table
from app.shared.database import Database


def decoded(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class CodeStateMachineRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def bind_object(self, snapshot_id: str, object_key: str, document_id: str) -> None:
        insert(
            self.db,
            "code_object",
            dict(
                snapshot_id=snapshot_id,
                object_key=object_key,
                document_id=document_id,
                display_name=OBJECTS[object_key],
                catalog_hash=CATALOG_HASH,
            ),
            conflict="on conflict(snapshot_id,object_key) do nothing",
        )
        for key, machine in MACHINES.items():
            if machine["object_key"] == object_key:
                insert(
                    self.db,
                    "code_machine",
                    dict(snapshot_id=snapshot_id, machine_key=key, **machine),
                    conflict="on conflict(snapshot_id,machine_key) do nothing",
                )
        for key, event in EVENTS.items():
            if event["object_key"] == object_key:
                insert(
                    self.db,
                    "code_event",
                    dict(
                        snapshot_id=snapshot_id,
                        event_key=key,
                        object_key=object_key,
                        display_name=event["name"],
                    ),
                    conflict="on conflict(snapshot_id,event_key) do nothing",
                )

    def known_states(self, snapshot_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            f"select machine_key,state_key,raw_value,display_name from {table(self.db, 'code_state')} "
            "where snapshot_id=? order by machine_key,state_key limit 1001",
            (snapshot_id,),
        )
        if len(rows) > 1000:
            raise CodeKnowledgeError("code_state_catalog_limit")
        return [
            dict(
                machine_key=r["machine_key"],
                key=r["state_key"],
                raw_value=r["raw_value"],
                name=r["display_name"],
            )
            for r in rows
        ]

    def store(
        self,
        snapshot_id: str,
        document_id: str,
        revision_id: str,
        record: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> None:
        transition = record["transition"]
        machine, key = transition["machine_key"], record["business_key"]
        definitions = [{**state, "machine_key": machine} for state in record["states"]]
        verify_state_definitions(definitions, self.known_states(snapshot_id))
        for state in definitions:
            self._state(snapshot_id, state, evidence)
        insert(
            self.db,
            "code_transition",
            dict(
                snapshot_id=snapshot_id,
                business_key=key,
                document_id=document_id,
                revision_id=revision_id,
                object_key=record["object_key"],
                machine_key=machine,
                event_key=transition["event_key"],
                source_mode=transition["from_state"]["mode"],
                source_json=transition["from_state"],
                target_mode=transition["to_state"]["mode"],
                target_state_key=transition["to_state"]["state_key"],
                target_json=transition["to_state"],
                guard_json=record["guard"],
                actions_json=transition["actions"],
                success_boundary_json=record["success_boundary"],
            ),
            conflict="on conflict(snapshot_id,business_key) do nothing",
        )
        for state in transition["from_state"]["state_keys"]:
            insert(
                self.db,
                "code_transition_source",
                dict(
                    snapshot_id=snapshot_id, business_key=key, machine_key=machine, state_key=state
                ),
                conflict="on conflict(snapshot_id,business_key,state_key) do nothing",
            )
        for ordinal, failure in enumerate(transition["failures"]):
            insert(
                self.db,
                "code_transition_failure",
                dict(
                    snapshot_id=snapshot_id,
                    business_key=key,
                    failure_key=failure["key"],
                    ordinal=ordinal,
                    machine_key=machine,
                    outcome=failure["outcome"],
                    phase=failure["phase"],
                    state_mode=failure["state_after"]["mode"],
                    state_key=failure["state_after"]["state_key"],
                    failure_json=failure,
                ),
                conflict="on conflict(snapshot_id,business_key,failure_key) do nothing",
            )
        self.read(snapshot_id, document_id, revision_id, record)

    def _state(
        self, snapshot_id: str, state: dict[str, Any], evidence: list[dict[str, Any]]
    ) -> None:
        current = self.db.execute_one(
            f"select evidence_json from {table(self.db, 'code_state')} "
            "where snapshot_id=? and machine_key=? and state_key=?",
            (snapshot_id, state["machine_key"], state["key"]),
        )
        proof = decoded(current["evidence_json"]) if current else []
        proof.extend(
            {k: v for k, v in item.items() if k != "id"}
            for item in evidence
            if item["id"] in state["evidence_ids"]
        )
        unique = {digest(item): item for item in proof}
        proof = [unique[key] for key in sorted(unique)]
        insert(
            self.db,
            "code_state",
            dict(
                snapshot_id=snapshot_id,
                machine_key=state["machine_key"],
                state_key=state["key"],
                raw_value=state["raw_value"],
                display_name=state["name"],
                evidence_json=proof,
            ),
            conflict="on conflict(snapshot_id,machine_key,state_key) do nothing",
        )
        if current:
            self.db.execute(
                f"update {table(self.db, 'code_state')} set evidence_json=? "
                "where snapshot_id=? and machine_key=? and state_key=?",
                (canonical_json(proof), snapshot_id, state["machine_key"], state["key"]),
            )

    def read(
        self, snapshot_id: str, document_id: str, revision_id: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        row = self.db.execute_one(
            f"select business_key,object_key,machine_key,event_key,source_mode,source_json,target_mode,target_state_key,target_json,guard_json,actions_json,success_boundary_json "
            f"from {table(self.db, 'code_transition')} where snapshot_id=? and document_id=? and revision_id=?",
            (snapshot_id, document_id, revision_id),
        )
        if not row:
            raise CodeKnowledgeError("code_transition_projection_missing")
        failures = self.db.execute(
            f"select failure_key,phase,outcome,state_mode,state_key,failure_json from {table(self.db, 'code_transition_failure')} "
            "where snapshot_id=? and business_key=? order by ordinal",
            (snapshot_id, row["business_key"]),
        )
        origins = self.db.execute(
            f"select state_key from {table(self.db, 'code_transition_source')} "
            "where snapshot_id=? and business_key=?",
            (snapshot_id, row["business_key"]),
        )
        states = self.db.execute(
            f"select state_key,raw_value from {table(self.db, 'code_state')} where snapshot_id=? and machine_key=?",
            (snapshot_id, row["machine_key"]),
        )
        values = {state["state_key"]: state["raw_value"] for state in states}
        transition = dict(
            machine_key=row["machine_key"],
            event_key=row["event_key"],
            from_state={**decoded(row["source_json"]), "mode": row["source_mode"]},
            to_state={
                **decoded(row["target_json"]),
                "mode": row["target_mode"],
                "state_key": row["target_state_key"],
            },
            actions=decoded(row["actions_json"]),
            failures=[
                {
                    **decoded(f["failure_json"]),
                    "key": f["failure_key"],
                    "phase": f["phase"],
                    "outcome": f["outcome"],
                    "state_after": {
                        **decoded(f["failure_json"])["state_after"],
                        "mode": f["state_mode"],
                        "state_key": f["state_key"],
                    },
                }
                for f in failures
            ],
        )
        if (
            transition != record["transition"]
            or row["object_key"] != record["object_key"]
            or row["business_key"] != record["business_key"]
            or any(values.get(s["key"]) != s["raw_value"] for s in record["states"])
            or decoded(row["guard_json"]) != record["guard"]
            or decoded(row["success_boundary_json"]) != record["success_boundary"]
            or {r["state_key"] for r in origins} != set(transition["from_state"]["state_keys"])
        ):
            raise CodeKnowledgeError("code_transition_projection_mismatch")
        return {
            **record,
            "transition": transition,
            "guard": decoded(row["guard_json"]),
            "success_boundary": decoded(row["success_boundary_json"]),
        }
