from __future__ import annotations

from app.shared.database import default_migrations_dir
from app.shared.migrations import (
    deployable_migration_catalog,
    load_migration_catalog,
    migration_version_key,
)


def seed_before_execution_user_migration() -> str:
    """Historical Webhook seed shape for tests upgrading databases through 157."""
    from app.cli.apply_local_seed import local_seed_sql

    seed = local_seed_sql()
    start = seed.index("INSERT INTO webhook_trigger_definition")
    end = seed.index("ON CONFLICT(id) DO NOTHING;", start) + len("ON CONFLICT(id) DO NOTHING;")
    old_definition = (
        seed[start:end]
        .replace("execution_user_id", "service_account_id")
        .replace(
            "'connector-grafana-default', NULL",
            "'connector-grafana-default', 'user_webhook_grafana_default'",
        )
    )
    old_user = """
INSERT INTO app_user (id, username, display_name, status, account_type, revision, created_at, updated_at)
VALUES ('user_webhook_grafana_default', 'svc-grafana-default', 'Historical test service',
        'enabled', 'service', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
"""
    return seed[:start] + old_user + old_definition + seed[end:]


def deployable_schema_versions() -> tuple[str, ...]:
    catalog = deployable_migration_catalog(load_migration_catalog(default_migrations_dir()))
    return tuple(artifact.version for artifact in catalog)


def current_schema_head() -> str:
    return deployable_schema_versions()[-1]


def schema_versions_after(version: str) -> tuple[str, ...]:
    """Deployable versions a database at ``version`` still has to apply, in order."""

    floor = migration_version_key(version)
    return tuple(
        candidate
        for candidate in deployable_schema_versions()
        if migration_version_key(candidate) > floor
    )
