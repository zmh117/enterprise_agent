"""Resolve current environment identity and published code resource association."""

from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_environment import user_environment
from app.shared.database import Database


def declared_environment(database: Database, text: str) -> dict[str, Any]:
    return user_environment(
        text,
        database.execute(
            "SELECT id,code,display_name AS name FROM platform_environment WHERE status='enabled'"
        ),
    )


def require_environment(database: Database, revision_id: str, environment_id: str) -> None:
    table = (
        "knowledge.code_resource_environment"
        if database.engine == "postgres"
        else '"knowledge.code_resource_environment"'
    )
    row = database.execute_one(
        f"SELECT e.id FROM {table} c JOIN platform_environment e ON e.id=c.environment_id "
        "WHERE c.revision_id=? AND e.id=? AND e.status='enabled'",
        (revision_id, environment_id),
    )
    if not row:
        raise CodeKnowledgeError("CODE_ENVIRONMENT_UNAVAILABLE")
