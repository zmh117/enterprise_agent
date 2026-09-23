from __future__ import annotations

from app.shared.database import default_migrations_dir
from app.shared.migrations import (
    deployable_migration_catalog,
    load_migration_catalog,
    migration_version_key,
)


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
