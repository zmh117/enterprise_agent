from __future__ import annotations

from app.modules.agent_config.application.bootstrap import AgentConfigBootstrapper
from app.modules.agent_config.infrastructure import AgentConfigRepository
from app.modules.audit.application.audit_service import AuditService
from app.modules.job.infrastructure.repositories import AuditRepository
from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def main() -> int:
    settings = load_settings()
    database = Database(settings.database_dsn)
    try:
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        result = AgentConfigBootstrapper(
            AgentConfigRepository(database),
            AuditService(
                AuditRepository(database),
                max_chars=settings.execution.max_tool_response_chars,
            ),
        ).ensure_builtin_agents(model=settings.claude_model)
    except Exception:
        print("AGENT_BOOTSTRAP_FAILED: schema, database, or Agent contract rejected")
        return 1
    finally:
        database.close()
    print(
        "AGENT_BOOTSTRAP_SUCCEEDED: "
        f"created={len(result['created'])} "
        f"drafts_created={len(result['drafts_created'])} "
        f"preserved={len(result['preserved'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
