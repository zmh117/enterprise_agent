from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import re
import time
from typing import Any

from app.shared.database import Database


MIGRATION_FILENAME = re.compile(
    r"^(?P<version>[0-9]{3}[a-z]?)_(?P<name>[a-z0-9][a-z0-9_]*)\.sql$"
)
LEGACY_BASELINE_HEAD = "018"


class MigrationDefinitionError(RuntimeError):
    """Raised before database access when migration files are ambiguous."""


class MigrationExecutionError(RuntimeError):
    """Safe migration failure without SQL, DSN, or database exception text."""


class SchemaHeadError(RuntimeError):
    """Safe read-only startup rejection for an incompatible database schema."""


@dataclass(frozen=True)
class MigrationArtifact:
    version: str
    name: str
    checksum: str
    path: Path
    sql: str


@dataclass(frozen=True)
class MigrationSchemaExpectations:
    tables: frozenset[str]
    columns: frozenset[tuple[str, str]]
    indexes: frozenset[str]


SCHEMA_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL CHECK(length(checksum) = 64),
    applied_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL CHECK(duration_ms >= 0),
    migrator_build TEXT NOT NULL
)
"""

CREATE_TABLE = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<table>[a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)
ADD_COLUMN = re.compile(
    r"\bALTER\s+TABLE\s+(?P<table>[a-z_][a-z0-9_]*)\s+"
    r"ADD\s+COLUMN\s+(?P<column>[a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)
CREATE_INDEX = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<index>[a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)
MIGRATOR_ADVISORY_LOCK_KEY = 764589320241


def normalized_migration_sql(raw: bytes) -> str:
    try:
        sql = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MigrationDefinitionError("Migration must be UTF-8") from exc
    sql = sql.replace("\r\n", "\n").replace("\r", "\n")
    if not sql.strip():
        raise MigrationDefinitionError("Migration must not be empty")
    return sql


def migration_checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def migration_version_key(version: str) -> tuple[int, str]:
    match = re.fullmatch(r"(?P<number>[0-9]{3})(?P<suffix>[a-z]?)", version)
    if match is None:
        raise MigrationDefinitionError(f"Invalid migration version: {version}")
    return int(match.group("number")), match.group("suffix")


def load_migration_catalog(migrations_dir: Path) -> tuple[MigrationArtifact, ...]:
    artifacts: list[MigrationArtifact] = []
    versions: dict[str, str] = {}
    names: set[str] = set()
    for path in migrations_dir.glob("*.sql"):
        match = MIGRATION_FILENAME.fullmatch(path.name)
        if match is None:
            raise MigrationDefinitionError(
                f"Invalid migration filename: {path.name}"
            )
        version = match.group("version")
        if version in versions:
            raise MigrationDefinitionError(
                "Duplicate migration version "
                f"{version}: {versions[version]}, {path.name}"
            )
        if path.name in names:
            raise MigrationDefinitionError(f"Duplicate migration name: {path.name}")
        sql = normalized_migration_sql(path.read_bytes())
        artifact = MigrationArtifact(
            version=version,
            name=path.name,
            checksum=migration_checksum(sql),
            path=path,
            sql=sql,
        )
        artifacts.append(artifact)
        versions[version] = path.name
        names.add(path.name)
    if not artifacts:
        raise MigrationDefinitionError(
            f"No migration files found in {migrations_dir}"
        )
    artifacts.sort(key=lambda item: migration_version_key(item.version))
    return tuple(artifacts)


def legacy_baseline_artifacts(
    catalog: tuple[MigrationArtifact, ...],
    *,
    head: str = LEGACY_BASELINE_HEAD,
) -> tuple[MigrationArtifact, ...]:
    expected_key = migration_version_key(head)
    baseline = tuple(
        artifact
        for artifact in catalog
        if migration_version_key(artifact.version) <= expected_key
    )
    if not baseline or baseline[-1].version != head:
        raise MigrationDefinitionError(
            f"Legacy baseline head is missing: {head}"
        )
    return baseline


def schema_expectations(
    artifacts: tuple[MigrationArtifact, ...],
) -> MigrationSchemaExpectations:
    sql = "\n".join(artifact.sql for artifact in artifacts)
    return MigrationSchemaExpectations(
        tables=frozenset(
            match.group("table").lower()
            for match in CREATE_TABLE.finditer(sql)
        ),
        columns=frozenset(
            (
                match.group("table").lower(),
                match.group("column").lower(),
            )
            for match in ADD_COLUMN.finditer(sql)
        ),
        indexes=frozenset(
            match.group("index").lower()
            for match in CREATE_INDEX.finditer(sql)
        ),
    )


class SchemaMigrationLedger:
    def __init__(self, database: Database) -> None:
        self.database = database

    def ensure_table(self) -> None:
        self.database.execute(SCHEMA_MIGRATION_TABLE_SQL)

    def list_records(self) -> list[dict[str, Any]]:
        self.ensure_table()
        return self.read_records()

    def read_records(self) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select version, name, checksum, applied_at, duration_ms, migrator_build
              from schema_migration
             order by version
            """
        )

    def baseline_legacy(
        self,
        catalog: tuple[MigrationArtifact, ...],
        *,
        migrator_build: str,
    ) -> int:
        baseline = legacy_baseline_artifacts(catalog)
        self.ensure_table()
        existing = self.list_records()
        if existing:
            self._validate_existing_baseline(existing, baseline)
            return 0

        self._validate_legacy_schema(schema_expectations(baseline))
        applied_at = datetime.now(UTC).isoformat()
        with self.database.unit_of_work():
            if self.database.execute_one(
                "select version from schema_migration limit 1"
            ):
                raise MigrationDefinitionError(
                    "Migration ledger changed during compatibility baseline"
                )
            for artifact in baseline:
                self.database.execute(
                    """
                    insert into schema_migration
                      (version, name, checksum, applied_at, duration_ms, migrator_build)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact.version,
                        artifact.name,
                        artifact.checksum,
                        applied_at,
                        0,
                        migrator_build,
                    ),
                )
        return len(baseline)

    def _validate_existing_baseline(
        self,
        records: list[dict[str, Any]],
        baseline: tuple[MigrationArtifact, ...],
    ) -> None:
        expected = {
            artifact.version: (artifact.name, artifact.checksum)
            for artifact in baseline
        }
        actual = {
            str(row["version"]): (
                str(row["name"]),
                str(row["checksum"]),
            )
            for row in records
            if migration_version_key(str(row["version"]))
            <= migration_version_key(LEGACY_BASELINE_HEAD)
        }
        if actual != expected:
            raise MigrationDefinitionError(
                "Existing migration compatibility baseline does not match "
                "the repository catalog"
            )

    def _validate_legacy_schema(
        self,
        expected: MigrationSchemaExpectations,
    ) -> None:
        tables, columns, indexes = self._read_schema_objects()
        missing_tables = sorted(expected.tables - tables)
        missing_columns = sorted(expected.columns - columns)
        missing_indexes = sorted(expected.indexes - indexes)
        if missing_tables or missing_columns or missing_indexes:
            details = [
                *(f"table:{name}" for name in missing_tables),
                *(f"column:{table}.{column}" for table, column in missing_columns),
                *(f"index:{name}" for name in missing_indexes),
            ]
            raise MigrationDefinitionError(
                "Legacy schema cannot be baselined; missing "
                + ", ".join(details[:20])
            )
        nonlocal_deployments = self.database.execute_one(
            """
            select
              (select count(*) from business_application_deployment
                where environment <> 'local')
              +
              (select count(*) from business_application_active_route
                where environment <> 'local') as count
            """
        )
        if nonlocal_deployments and int(nonlocal_deployments["count"]) != 0:
            raise MigrationDefinitionError(
                "Legacy schema cannot be baselined; migration 012 invariant failed"
            )

    def _read_schema_objects(
        self,
    ) -> tuple[
        frozenset[str],
        frozenset[tuple[str, str]],
        frozenset[str],
    ]:
        if self.database.engine == "sqlite":
            objects = self.database.execute(
                """
                select type, name
                  from sqlite_master
                 where type in ('table', 'index')
                """
            )
            tables = frozenset(
                str(row["name"]).lower()
                for row in objects
                if row["type"] == "table"
            )
            indexes = frozenset(
                str(row["name"]).lower()
                for row in objects
                if row["type"] == "index"
            )
            columns = frozenset(
                (table, str(row["name"]).lower())
                for table in tables
                for row in self.database.execute(
                    f'pragma table_info("{table}")'
                )
            )
            return tables, columns, indexes

        column_rows = self.database.execute(
            """
            select table_name, column_name
              from information_schema.columns
             where table_schema = 'public'
            """
        )
        index_rows = self.database.execute(
            """
            select indexname
              from pg_indexes
             where schemaname = 'public'
            """
        )
        columns = frozenset(
            (
                str(row["table_name"]).lower(),
                str(row["column_name"]).lower(),
            )
            for row in column_rows
        )
        tables = frozenset(table for table, _ in columns)
        indexes = frozenset(
            str(row["indexname"]).lower() for row in index_rows
        )
        return tables, columns, indexes


@dataclass(frozen=True)
class MigrationRunResult:
    head: str
    baselined: int
    applied: tuple[str, ...]


class Migrator:
    def __init__(
        self,
        database: Database,
        migrations_dir: Path,
        *,
        migrator_build: str,
    ) -> None:
        self.database = database
        self.migrations_dir = migrations_dir
        self.migrator_build = migrator_build.strip() or "unknown"

    def run(self) -> MigrationRunResult:
        catalog = load_migration_catalog(self.migrations_dir)
        with self.database.session():
            lock_acquired = False
            try:
                self._acquire_lock()
                lock_acquired = True
                ledger = SchemaMigrationLedger(self.database)
                ledger.ensure_table()
                records = ledger.list_records()
                baselined = 0
                if not records and self._application_schema_exists():
                    baselined = ledger.baseline_legacy(
                        catalog,
                        migrator_build=self.migrator_build,
                    )
                    records = ledger.list_records()
                self._validate_applied_prefix(records, catalog)
                applied: list[str] = []
                for artifact in catalog[len(records):]:
                    self._apply_one(artifact)
                    applied.append(artifact.version)
                return MigrationRunResult(
                    head=catalog[-1].version,
                    baselined=baselined,
                    applied=tuple(applied),
                )
            finally:
                if lock_acquired:
                    self._release_lock()

    def _validate_applied_prefix(
        self,
        records: list[dict[str, Any]],
        catalog: tuple[MigrationArtifact, ...],
    ) -> None:
        if len(records) > len(catalog):
            raise MigrationDefinitionError(
                "Migration ledger contains versions unknown to this build"
            )
        for artifact, row in zip(catalog, records, strict=False):
            if (
                str(row["version"]) != artifact.version
                or str(row["name"]) != artifact.name
                or str(row["checksum"]) != artifact.checksum
            ):
                raise MigrationDefinitionError(
                    "Applied migration checksum or identity does not match "
                    f"repository version {artifact.version}"
                )

    def _apply_one(self, artifact: MigrationArtifact) -> None:
        started = time.monotonic()
        try:
            with self.database.unit_of_work():
                self.database.execute_script(
                    artifact.sql,
                    ignore_existing_errors=False,
                )
                duration_ms = max(
                    0,
                    int((time.monotonic() - started) * 1000),
                )
                self.database.execute(
                    """
                    insert into schema_migration
                      (version, name, checksum, applied_at, duration_ms, migrator_build)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact.version,
                        artifact.name,
                        artifact.checksum,
                        datetime.now(UTC).isoformat(),
                        duration_ms,
                        self.migrator_build,
                    ),
                )
        except Exception as exc:
            if isinstance(exc, MigrationDefinitionError):
                raise
            raise MigrationExecutionError(
                f"Migration {artifact.version} failed and was rolled back"
            ) from exc

    def _application_schema_exists(self) -> bool:
        if self.database.engine == "sqlite":
            return (
                self.database.execute_one(
                    """
                    select name
                      from sqlite_master
                     where type = 'table' and name = 'agent_job'
                    """
                )
                is not None
            )
        return (
            self.database.execute_one(
                """
                select table_name
                  from information_schema.tables
                 where table_schema = 'public' and table_name = 'agent_job'
                """
            )
            is not None
        )

    def _acquire_lock(self) -> None:
        if self.database.engine == "postgres":
            self.database.execute(
                "select pg_advisory_lock(?)",
                (MIGRATOR_ADVISORY_LOCK_KEY,),
            )

    def _release_lock(self) -> None:
        if self.database.engine != "postgres":
            return
        try:
            self.database.execute(
                "select pg_advisory_unlock(?)",
                (MIGRATOR_ADVISORY_LOCK_KEY,),
            )
        except Exception:
            self.database.close()


class SchemaHeadValidator:
    def __init__(self, database: Database, migrations_dir: Path) -> None:
        self.database = database
        self.migrations_dir = migrations_dir

    def require_current(self) -> str:
        catalog = load_migration_catalog(self.migrations_dir)
        expected_head = catalog[-1].version
        try:
            if not self._ledger_exists():
                raise SchemaHeadError(
                    "Database schema ledger is missing; "
                    f"expected head {expected_head}"
                )
            records = SchemaMigrationLedger(self.database).read_records()
            Migrator(
                self.database,
                self.migrations_dir,
                migrator_build="schema-head-validator",
            )._validate_applied_prefix(records, catalog)
            current_head = (
                str(records[-1]["version"]) if records else "none"
            )
            if len(records) != len(catalog):
                raise SchemaHeadError(
                    f"Database schema head is {current_head}; "
                    f"expected {expected_head}"
                )
            return expected_head
        except SchemaHeadError:
            raise
        except MigrationDefinitionError as exc:
            raise SchemaHeadError(str(exc)) from exc
        except Exception as exc:
            raise SchemaHeadError(
                "Database schema head could not be read; "
                f"expected {expected_head}"
            ) from exc

    def _ledger_exists(self) -> bool:
        if self.database.engine == "sqlite":
            return (
                self.database.execute_one(
                    """
                    select name
                      from sqlite_master
                     where type = 'table' and name = 'schema_migration'
                    """
                )
                is not None
            )
        return (
            self.database.execute_one(
                """
                select table_name
                  from information_schema.tables
                 where table_schema = 'public'
                   and table_name = 'schema_migration'
                """
            )
            is not None
        )
