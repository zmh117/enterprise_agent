"""Versioned, data-only business knowledge contracts. No expressions are executed."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator

from app.modules.knowledge.domain.normalization import canonical_json

CONTRACT_VERSION = "code-business/v2"
CODE_SOURCE_GRANT_PATH = "/api/internal/code-knowledge/source-grant"
CODE_INTERNAL_CONNECTOR_ID = "internal-code-knowledge"
ROLES = ("backend", "factory_frontend", "group_frontend")
COMPONENTS = dict(zip(ROLES, ("set_server", "set_web/EBR", "set_web/JTH"), strict=True))
KINDS = ("object", "transition", "rule")
MAX_PACKAGE_BYTES = 15 * 1024 * 1024
MAX_RESPONSE_BYTES = 512 * 1024


class CodeKnowledgeError(ValueError):
    """Only a stable code and JSON location; never include source content."""

    def __init__(self, code: str, location: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.location = location


def obj(properties: dict[str, Any], optional: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": [key for key in properties if key not in optional],
    }


def array(item: dict[str, Any], maximum: int = 1000, minimum: int = 0) -> dict[str, Any]:
    return {"type": "array", "items": item, "maxItems": maximum, "minItems": minimum}


TEXT = {"type": "string", "minLength": 1, "maxLength": 8000}
ID = {"type": "string", "pattern": r"^[A-Za-z0-9_.:/-]{1,200}$"}
HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
ROLE = {"enum": list(ROLES)}
REVISION = {"type": "integer", "minimum": 0}
EVIDENCE_IDS = array(ID, 100, 1)
SOURCE_REF = {
    "oneOf": [
        obj(
            {
                "kind": {"const": "local_bundle"},
                "bundle_id": ID,
                "manifest_hash": HASH,
                "svn_revision": {"type": "null"},
            }
        ),
        obj(
            {
                "kind": {"const": "svn"},
                "repository_uuid": ID,
                "branch_path": TEXT,
                "revision": REVISION,
                "manifest_hash": HASH,
                "component_paths": obj({role: TEXT for role in ROLES}),
                "external_revisions": array(
                    obj(
                        {
                            "path": TEXT,
                            "repository_uuid": ID,
                            "branch_path": TEXT,
                            "revision": REVISION,
                        }
                    ),
                    100,
                ),
            },
            ("component_paths", "external_revisions"),
        ),
    ]
}
VERSION_SELECTOR = {
    "oneOf": [
        obj({"kind": {"const": "local_baseline"}, "snapshot_id": ID}),
        obj({"kind": {"const": "svn"}, "revision": REVISION}),
        obj({"kind": {"const": "latest_verified"}}),
    ]
}
UNKNOWN = obj({"code": ID, "description": TEXT, "critical": {"type": "boolean"}})
FACT = obj(
    {
        "description": TEXT,
        "phase": {
            "enum": [
                "frontend",
                "request",
                "accepted",
                "execution",
                "state_write",
                "transaction_commit",
                "message",
                "acknowledgement",
                "failure",
                "unknown",
            ]
        },
        "evidence_ids": EVIDENCE_IDS,
    }
)
GUARD = {
    "$defs": {
        "guard": {
            "oneOf": [
                obj(
                    {
                        "op": {"enum": ["AND", "OR"]},
                        "args": array({"$ref": "#/$defs/guard"}, 100, 1),
                        "evaluation": {"enum": ["short_circuit", "all", "unknown"]},
                        "evidence_ids": EVIDENCE_IDS,
                    }
                ),
                obj(
                    {
                        "op": {"const": "NOT"},
                        "arg": {"$ref": "#/$defs/guard"},
                        "evidence_ids": EVIDENCE_IDS,
                    }
                ),
                obj(
                    {
                        "op": {"const": "predicate"},
                        "expression": TEXT,
                        "null_semantics": {
                            "enum": [
                                "distinct_from_empty",
                                "same_as_empty",
                                "not_applicable",
                                "unknown",
                            ]
                        },
                        "checked_at": TEXT,
                        "evidence_ids": EVIDENCE_IDS,
                    }
                ),
                obj({"op": {"const": "unknown"}, "reason": TEXT}),
            ]
        }
    },
    "$ref": "#/$defs/guard",
}
STATE_RESULT = obj(
    {
        "mode": {"enum": ["state", "unchanged", "unknown"]},
        "state_key": {"type": ["string", "null"], "maxLength": 200},
        "description": TEXT,
        "evidence_ids": EVIDENCE_IDS,
    }
)
STATE_RESULT["allOf"] = [
    {
        "if": {"properties": {"mode": {"const": "state"}}},
        "then": {"properties": {"state_key": ID}},
        "else": {"properties": {"state_key": {"type": "null"}}},
    }
]
STATE_SELECTION = obj(
    {
        "mode": {"enum": ["states", "any", "unresolved"]},
        "state_keys": {**array(ID, 100), "uniqueItems": True},
        "description": TEXT,
        "evidence_ids": EVIDENCE_IDS,
    }
)
STATE_SELECTION["allOf"] = [
    {
        "if": {"properties": {"mode": {"const": "states"}}},
        "then": {"properties": {"state_keys": {"minItems": 1}}},
        "else": {"properties": {"state_keys": {"maxItems": 0}}},
    }
]
ACTION = obj({"key": ID, **FACT["properties"]})
FAILURE_STATE_RESULT = deepcopy(STATE_RESULT)
FAILURE_STATE_RESULT["properties"]["mode"]["enum"].append("indeterminate")
FAILURE = obj(
    {
        "key": ID,
        "condition": {"$ref": "#/$defs/guard"},
        "phase": FACT["properties"]["phase"],
        "outcome": {"enum": ["rejected", "failed", "partial", "unknown"]},
        "state_after": FAILURE_STATE_RESULT,
        "retained_action_keys": {**array(ID, 100), "uniqueItems": True},
        "description": TEXT,
        "evidence_ids": EVIDENCE_IDS,
    }
)
TRANSITION = obj(
    {
        "machine_key": ID,
        "event_key": ID,
        "from_state": STATE_SELECTION,
        "to_state": STATE_RESULT,
        "actions": array(ACTION, 100, 1),
        "failures": array(FAILURE, 100, 1),
    }
)
# Shared guard definitions belong to the complete record/envelope root.
KNOWLEDGE = obj(
    {
        "business_key": ID,
        "object_key": ID,
        "identity_state": {"enum": ["confirmed", "unresolved"]},
        "kind": {"enum": list(KINDS)},
        "role": ROLE,
        "title": TEXT,
        "fact_class": {
            "enum": [
                "backend_behavior",
                "frontend_constraint",
                "requirement",
                "observation",
                "identity",
            ]
        },
        "summary": TEXT,
        "object_version": {"type": ["string", "null"], "maxLength": 200},
        "states": array(
            obj({"key": ID, "name": TEXT, "raw_value": TEXT, "evidence_ids": EVIDENCE_IDS})
        ),
        "trigger": {"type": ["string", "null"], "maxLength": 8000},
        "guard": {"oneOf": [{"$ref": "#/$defs/guard"}, {"type": "null"}]},
        "transition": {"oneOf": [TRANSITION, {"type": "null"}]},
        "check_order": array(FACT),
        "effects": array(FACT),
        "outcomes": array(FACT),
        "success_boundary": obj({**FACT["properties"], "evidence_ids": array(ID, 100)}),
        "configuration": array(FACT),
        "evidence_ids": array(ID, 100),
        "required_runtime_facts": array(obj({"field": TEXT, "relation_path": TEXT, "time": TEXT})),
        "coverage": {"enum": ["analyzed", "partial", "not_analyzed"]},
        "unknowns": array(UNKNOWN),
    }
)
KNOWLEDGE["$defs"] = GUARD["$defs"]
KNOWLEDGE["allOf"] = [
    {
        "if": {"properties": {"kind": {"enum": ["transition", "rule"]}}},
        "then": {
            "properties": {
                "guard": {"$ref": "#/$defs/guard"},
                "evidence_ids": EVIDENCE_IDS,
                "success_boundary": FACT,
            }
        },
    },
    {
        "if": {"properties": {"kind": {"const": "transition"}}},
        "then": {
            "properties": {
                "transition": TRANSITION,
                "guard": {"$ref": "#/$defs/guard"},
                "effects": {"maxItems": 0},
                "outcomes": {"maxItems": 0},
            }
        },
        "else": {"properties": {"transition": {"type": "null"}, "states": {"maxItems": 0}}},
    },
]
RELATION = obj(
    {
        "id": ID,
        "from_key": ID,
        "to_key": ID,
        "kind": {
            "enum": ["references", "contains", "operation_rule", "rule_dependency", "effect_object"]
        },
        "reading_mode": {
            "enum": ["fixed_version", "current_record", "copied_at_operation", "unknown"]
        },
        "read_at": TEXT,
        "required": {"type": "boolean"},
        "evidence_ids": EVIDENCE_IDS,
    }
)
EVIDENCE = obj(
    {
        "id": ID,
        "source_snapshot_id": ID,
        "file_id": ID,
        "path": TEXT,
        "symbol": TEXT,
        "start_line": {"type": "integer", "minimum": 1},
        "end_line": {"type": "integer", "minimum": 1},
        "raw_hash": HASH,
        "representation_hash": HASH,
        "excerpt_hash": HASH,
    }
)
COVERAGE = obj(
    {
        "entries": array(
            obj(
                {
                    "entry_id": ID,
                    "role": ROLE,
                    "status": {"enum": ["analyzed", "partial", "not_analyzed"]},
                    "knowledge_keys": array(ID),
                    "unknowns": array(UNKNOWN),
                }
            )
        ),
        "unknowns": array(UNKNOWN),
        "dependency_requests": array(obj({"entry_id": ID, "path": TEXT, "reason": TEXT}), 8),
    }
)
COVERAGE["required"] = ["entries", "unknowns"]
MANIFEST = obj(
    {
        "contract_version": {"const": CONTRACT_VERSION},
        "source_snapshot_id": ID,
        "source_ref": SOURCE_REF,
        "build_id": ID,
        "work_unit_id": ID,
        "scope_hash": HASH,
        "config_hash": HASH,
    }
)
CHANGES = obj(
    {
        "removed_keys": array(obj({"business_key": ID, "evidence_ids": EVIDENCE_IDS})),
        "identity_unresolved": array(ID),
    }
)
LOGICAL_SCHEMAS = {
    "manifest.json": MANIFEST,
    "knowledge.jsonl": KNOWLEDGE,
    "evidence.jsonl": EVIDENCE,
    "relations.jsonl": RELATION,
    "coverage.json": COVERAGE,
    "changes.json": CHANGES,
}
ENVELOPE = obj(
    {
        "contract_version": {"const": CONTRACT_VERSION},
        "entries": array(
            obj(
                {
                    "logical_name": {"enum": list(LOGICAL_SCHEMAS)},
                    "content": {"type": "string"},
                    "sha256": HASH,
                }
            ),
            6,
            6,
        ),
    }
)
COMPARISON = obj(
    {
        "knowledge_id": ID,
        "from_snapshot_id": ID,
        "to_snapshot_id": ID,
        "classification": {
            "enum": ["semantic", "evidence_only", "unchanged", "identity_unresolved"]
        },
        "changed_fields": array(TEXT),
        "changed_at_revision": {"type": ["integer", "null"], "minimum": 0},
        "exact_revision_proven": {"type": "boolean"},
    }
)

# Authoring omits only a derived checksum; Runtime computes it from admitted bytes.
AUTHORING_ENTRIES = {
    name: array(deepcopy(schema), 10000) if name.endswith(".jsonl") else deepcopy(schema)
    for name, schema in LOGICAL_SCHEMAS.items()
}
AUTHORING_ENTRIES["evidence.jsonl"]["items"]["properties"]["excerpt_hash"] = {"type": "null"}
AUTHORING = obj(
    {"contract_version": {"const": CONTRACT_VERSION}, "entries": obj(AUTHORING_ENTRIES)}
)
AUTHORING["$defs"] = deepcopy(KNOWLEDGE["$defs"])


def validate(value: Any, schema: dict[str, Any]) -> None:
    # Bound recursive JSON before recursive schema traversal; reject NaN and opaque objects.
    try:
        encoded = canonical_json(value).encode("utf-8")
        if len(encoded) > MAX_PACKAGE_BYTES:
            raise CodeKnowledgeError("code_contract_too_large")
        _depth(value)
        error = next(Draft202012Validator(schema).iter_errors(value), None)
    except (RecursionError, TypeError, ValueError) as exc:
        if isinstance(exc, CodeKnowledgeError):
            raise
        raise CodeKnowledgeError("code_contract_invalid") from None
    if error is not None:
        raise CodeKnowledgeError("code_contract_invalid", "/".join(map(str, error.absolute_path)))


def _depth(value: Any, level: int = 0) -> None:
    if level > 32:
        raise CodeKnowledgeError("code_contract_too_deep")
    if isinstance(value, dict):
        for item in value.values():
            _depth(item, level + 1)
    elif isinstance(value, list):
        for item in value:
            _depth(item, level + 1)
