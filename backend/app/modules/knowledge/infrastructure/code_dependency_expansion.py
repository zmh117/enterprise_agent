"""Turn untrusted dependency requests into bounded, controller-approved follow-up units."""

from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError, COMPONENTS
from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository
from app.modules.knowledge.infrastructure.code_repository import decoded
from app.modules.knowledge.infrastructure.code_source import relative_path
from app.modules.knowledge.infrastructure.storage import insert, table
from app.shared.database import Database


def expand_dependencies(database: Database, unit: dict[str, Any], lease: int) -> str:
    result = decoded(unit["result_json"])
    if result.get("replacement_unit_id"):
        return str(result["replacement_unit_id"])
    scope = decoded(unit["scope_json"])
    requests = result.get("dependency_requests", [])
    if not 1 <= len(requests) <= 8 or scope.get("expansion_depth", 0) >= 2:
        raise CodeKnowledgeError("code_dependency_expansion_budget_exhausted")
    with database.unit_of_work():
        build = CodeBuildRepository(database)._leased(unit["build_id"], lease)
        binding = database.execute_one(
            f"select config_json from {table(database, 'code_binding')} where source_id=?",
            (build["source_id"],),
        )
        approved = (
            decoded(binding["config_json"]).get("approved_dependency_roots", []) if binding else []
        )
        source = database.execute_one(
            f"select manifest_json,retired_at from {table(database, 'code_source_snapshot')} where id=?",
            (build["source_snapshot_id"],),
        )
        if not source or source["retired_at"] is not None:
            raise CodeKnowledgeError("code_source_unavailable")
        admitted = {row["path"] for row in decoded(source["manifest_json"])["files"]}
        paths = set()
        for request in requests:
            path = relative_path(request["path"])
            if (
                request["entry_id"] not in scope["entry_ids"]
                or path not in admitted
                or not any(path.startswith(root + "/") for root in COMPONENTS.values())
                or not any(path == root or path.startswith(root + "/") for root in approved)
            ):
                raise CodeKnowledgeError("code_dependency_expansion_denied")
            if not any(
                path == root or path.startswith(root + "/") for root in scope["allowed_prefixes"]
            ):
                paths.add(path)
        if not paths:
            raise CodeKnowledgeError("code_dependency_expansion_no_new_scope")
        expanded = {
            **scope,
            "allowed_prefixes": sorted(set(scope["allowed_prefixes"]) | paths),
            "start_files": sorted(set(scope.get("start_files", [])) | paths),
            "expansion_depth": scope.get("expansion_depth", 0) + 1,
            "parent_unit_id": unit["id"],
        }
        if len(expanded["allowed_prefixes"]) > 100:
            raise CodeKnowledgeError("code_dependency_expansion_budget_exhausted")
        identifier = stable_id("code_unit", unit["build_id"], unit["id"], digest(expanded))
        count = database.execute_one(
            f"select count(*) as n from {table(database, 'code_unit')} where build_id=?",
            (unit["build_id"],),
        )
        if count and count["n"] >= 24:
            raise CodeKnowledgeError("code_dependency_expansion_budget_exhausted")
        insert(
            database,
            "code_unit",
            {
                "id": identifier,
                "build_id": unit["build_id"],
                "unit_key": unit["unit_key"] + ".deps",
                "scope_json": expanded,
                "state": "QUEUED",
                "created_at": now(),
                "updated_at": now(),
            },
            conflict="on conflict(id) do nothing",
        )
        database.execute(
            f"update {table(database, 'code_unit')} set result_json=?,updated_at=? where id=? and state='VALIDATED'",
            (canonical_json({**result, "replacement_unit_id": identifier}), now(), unit["id"]),
        )
        return identifier
