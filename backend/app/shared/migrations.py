from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any

from app.shared.database import Database
from app.shared.schema_baseline import (
    LEGACY_HEAD,
    LEGACY_MANIFEST_FILENAME,
    TARGET_BASELINE,
    digest_payload,
    load_legacy_manifest,
    postgres_comment_snapshot,
    schema_snapshot,
)


MIGRATION_FILENAME = re.compile(r"^(?P<version>[0-9]{3}[a-z]?)_(?P<name>[a-z0-9][a-z0-9_]*)\.sql$")
LEGACY_BASELINE_HEAD = "018"
BASELINE_ADOPTION_SOURCE_HEAD = LEGACY_HEAD
BASELINE_VERSION = TARGET_BASELINE


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

SCHEMA_BASELINE_ADOPTION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_baseline_adoption (
    target_baseline TEXT PRIMARY KEY,
    source_generation TEXT NOT NULL,
    source_head TEXT NOT NULL,
    legacy_catalog_digest TEXT NOT NULL CHECK(length(legacy_catalog_digest) = 64),
    schema_fingerprint TEXT NOT NULL CHECK(length(schema_fingerprint) = 64),
    comment_manifest_digest TEXT NOT NULL CHECK(length(comment_manifest_digest) = 64),
    retained_data_counts_json TEXT NOT NULL,
    retained_data_digest TEXT NOT NULL CHECK(length(retained_data_digest) = 64),
    baseline_name TEXT NOT NULL,
    baseline_checksum TEXT NOT NULL CHECK(length(baseline_checksum) = 64),
    migrator_build TEXT NOT NULL,
    adopted_at TEXT NOT NULL
)
"""

RETAINED_DATA_TABLES = (
    "app_user",
    "user_external_identity",
    "rbac_role",
    "rbac_user_role",
    "agent_definition",
    "agent_publication",
    "business_application",
    "business_application_publication",
    "integration_connector",
    "platform_resource",
)

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
            raise MigrationDefinitionError(f"Invalid migration filename: {path.name}")
        version = match.group("version")
        if version in versions:
            raise MigrationDefinitionError(
                f"Duplicate migration version {version}: {versions[version]}, {path.name}"
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
        raise MigrationDefinitionError(f"No migration files found in {migrations_dir}")
    artifacts.sort(key=lambda item: migration_version_key(item.version))
    return tuple(artifacts)


def legacy_baseline_artifacts(
    catalog: tuple[MigrationArtifact, ...],
    *,
    head: str = LEGACY_BASELINE_HEAD,
) -> tuple[MigrationArtifact, ...]:
    expected_key = migration_version_key(head)
    baseline = tuple(
        artifact for artifact in catalog if migration_version_key(artifact.version) <= expected_key
    )
    if not baseline or baseline[-1].version != head:
        raise MigrationDefinitionError(f"Legacy baseline head is missing: {head}")
    return baseline


def schema_expectations(
    artifacts: tuple[MigrationArtifact, ...],
) -> MigrationSchemaExpectations:
    sql = "\n".join(artifact.sql for artifact in artifacts)
    return MigrationSchemaExpectations(
        tables=frozenset(match.group("table").lower() for match in CREATE_TABLE.finditer(sql)),
        columns=frozenset(
            (
                match.group("table").lower(),
                match.group("column").lower(),
            )
            for match in ADD_COLUMN.finditer(sql)
        ),
        indexes=frozenset(match.group("index").lower() for match in CREATE_INDEX.finditer(sql)),
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

    def ensure_adoption_table(self) -> None:
        self.database.execute(SCHEMA_BASELINE_ADOPTION_TABLE_SQL)

    def read_adoptions(self) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select target_baseline, source_generation, source_head,
                   legacy_catalog_digest, schema_fingerprint,
                   comment_manifest_digest, retained_data_counts_json,
                   retained_data_digest, baseline_name, baseline_checksum,
                   migrator_build, adopted_at
              from schema_baseline_adoption
             order by target_baseline
            """
        )

    def adopt_legacy_baseline(
        self,
        *,
        manifest: dict[str, Any],
        baseline: MigrationArtifact,
        migrator_build: str,
    ) -> None:
        self.ensure_table()
        self.ensure_adoption_table()
        with self.database.unit_of_work():
            records = self.read_records()
            _validate_legacy_manifest_records(records, manifest)
            if self.read_adoptions():
                raise MigrationDefinitionError(
                    "Legacy baseline adoption metadata already exists without its marker"
                )
            expected_schema = _manifest_schema_for_engine(manifest, self.database.engine)
            actual_schema = schema_snapshot(self.database)
            if str(actual_schema["fingerprint"]) != str(expected_schema["fingerprint"]):
                raise MigrationDefinitionError(
                    "Legacy 042 schema fingerprint does not match the immutable manifest"
                )
            expected_comments = manifest.get("postgres_comments")
            if not isinstance(expected_comments, dict):
                raise MigrationDefinitionError(
                    "Legacy manifest is missing the PostgreSQL comment fingerprint"
                )
            if self.database.engine == "postgres":
                actual_comments = postgres_comment_snapshot(self.database)
                if str(actual_comments["digest"]) != str(expected_comments["digest"]):
                    raise MigrationDefinitionError(
                        "Legacy 042 PostgreSQL comments do not match the immutable manifest"
                    )
            if self.database.engine == "sqlite":
                foreign_key_errors = self.database.execute("pragma foreign_key_check")
                if foreign_key_errors:
                    raise MigrationDefinitionError(
                        "Legacy 042 schema has foreign key integrity errors"
                    )
            counts = _retained_data_counts(self.database)
            counts_json = json.dumps(
                counts,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            adopted_at = datetime.now(UTC).isoformat()
            self.database.execute(
                """
                insert into schema_migration
                  (version, name, checksum, applied_at, duration_ms, migrator_build)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    baseline.version,
                    baseline.name,
                    baseline.checksum,
                    adopted_at,
                    0,
                    migrator_build,
                ),
            )
            self.database.execute(
                """
                insert into schema_baseline_adoption
                  (target_baseline, source_generation, source_head,
                   legacy_catalog_digest, schema_fingerprint,
                   comment_manifest_digest, retained_data_counts_json,
                   retained_data_digest, baseline_name, baseline_checksum,
                   migrator_build, adopted_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    baseline.version,
                    str(manifest["legacy_generation"]),
                    str(manifest["legacy_head"]),
                    str(manifest["catalog_digest"]),
                    str(expected_schema["fingerprint"]),
                    str(expected_comments["digest"]),
                    counts_json,
                    digest_payload(counts),
                    baseline.name,
                    baseline.checksum,
                    migrator_build,
                    adopted_at,
                ),
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
            if self.database.execute_one("select version from schema_migration limit 1"):
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
        expected = {artifact.version: (artifact.name, artifact.checksum) for artifact in baseline}
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
                "Existing migration compatibility baseline does not match the repository catalog"
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
                "Legacy schema cannot be baselined; missing " + ", ".join(details[:20])
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
                str(row["name"]).lower() for row in objects if row["type"] == "table"
            )
            indexes = frozenset(
                str(row["name"]).lower() for row in objects if row["type"] == "index"
            )
            columns = frozenset(
                (table, str(row["name"]).lower())
                for table in tables
                for row in self.database.execute(f'pragma table_info("{table}")')
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
        indexes = frozenset(str(row["indexname"]).lower() for row in index_rows)
        return tables, columns, indexes


def _manifest_schema_for_engine(
    manifest: dict[str, Any],
    engine: str,
) -> dict[str, Any]:
    key = "sqlite_schema" if engine == "sqlite" else "postgres_schema"
    snapshot = manifest.get(key)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("fingerprint"), str):
        raise MigrationDefinitionError(
            f"Legacy manifest is missing the {engine} schema fingerprint"
        )
    return snapshot


def _validate_legacy_manifest_records(
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    expected = manifest.get("catalog")
    if not isinstance(expected, list):
        raise MigrationDefinitionError("Legacy migration manifest catalog is missing")
    if len(records) != len(expected):
        current_head = str(records[-1]["version"]) if records else "none"
        raise MigrationDefinitionError(
            "Legacy database must have the exact immutable 042 ledger before baseline "
            f"adoption; current head is {current_head}"
        )
    for row, entry in zip(records, expected, strict=True):
        if (
            str(row["version"]) != str(entry["version"])
            or str(row["name"]) != str(entry["name"])
            or str(row["checksum"]) != str(entry["checksum"])
        ):
            raise MigrationDefinitionError(
                "Legacy migration ledger checksum or identity does not match the "
                f"immutable manifest at version {entry['version']}"
            )


def _retained_data_counts(database: Database) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in RETAINED_DATA_TABLES:
        row = database.execute_one(f'select count(*) as count from "{table}"')
        if row is None:
            raise MigrationDefinitionError(
                f"Legacy 042 retained-data table could not be counted: {table}"
            )
        counts[table] = int(row["count"])
    return counts


def _validate_adoption_metadata(
    *,
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    baseline: MigrationArtifact,
    engine: str,
) -> None:
    if len(rows) != 1:
        raise MigrationDefinitionError(
            "Adopted legacy ledger requires exactly one baseline adoption metadata row"
        )
    row = rows[0]
    expected_schema = _manifest_schema_for_engine(manifest, engine)
    expected_comments = manifest.get("postgres_comments")
    if not isinstance(expected_comments, dict):
        raise MigrationDefinitionError(
            "Legacy manifest is missing the PostgreSQL comment fingerprint"
        )
    expected = {
        "target_baseline": baseline.version,
        "source_generation": str(manifest["legacy_generation"]),
        "source_head": str(manifest["legacy_head"]),
        "legacy_catalog_digest": str(manifest["catalog_digest"]),
        "schema_fingerprint": str(expected_schema["fingerprint"]),
        "comment_manifest_digest": str(expected_comments["digest"]),
        "baseline_name": baseline.name,
        "baseline_checksum": baseline.checksum,
    }
    for key, value in expected.items():
        if str(row[key]) != value:
            raise MigrationDefinitionError(
                f"Baseline adoption metadata does not match immutable field {key}"
            )
    try:
        retained_counts = json.loads(str(row["retained_data_counts_json"]))
    except json.JSONDecodeError as exc:
        raise MigrationDefinitionError(
            "Baseline adoption retained-data evidence is invalid"
        ) from exc
    if not isinstance(retained_counts, dict) or digest_payload(retained_counts) != str(
        row["retained_data_digest"]
    ):
        raise MigrationDefinitionError(
            "Baseline adoption retained-data evidence digest does not match"
        )


def _safe_migrator_build(value: str) -> str:
    build = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", build):
        raise MigrationDefinitionError(
            "Migrator build must be a non-secret release or commit identifier"
        )
    return build


def _runtime_config_summary(database: Database) -> dict[str, Any]:
    row = database.execute_one(
        """
        select
          (select count(*) from platform_runtime_config_definition) as definition_count,
          (select count(*) from platform_runtime_config_value) as value_count,
          (select count(*) from platform_secret) as secret_count,
          (select coalesce(sum(revision), 0) from (
             select revision from platform_runtime_config_definition
             union all select revision from platform_runtime_config_value
             union all select revision from platform_secret
           ) runtime_config_revisions) as revision
        """
    )
    if row is None:
        raise MigrationDefinitionError("Runtime config summary could not be read")
    summary = {
        "definition_count": int(row["definition_count"]),
        "value_count": int(row["value_count"]),
        "secret_count": int(row["secret_count"]),
        "revision": int(row["revision"]),
    }
    return {**summary, "digest": digest_payload(summary)}


class BaselineAdoptionInspector:
    """Read-only evidence collection for legacy baseline adoption operations."""

    def __init__(self, database: Database, migrations_dir: Path) -> None:
        self.database = database
        self.migrations_dir = migrations_dir

    def preflight(self, *, migrator_build: str) -> dict[str, Any]:
        build = _safe_migrator_build(migrator_build)
        catalog, manifest, migrator = self._load_context(build)
        validator = SchemaHeadValidator(self.database, self.migrations_dir)
        if not validator._ledger_exists():
            raise MigrationDefinitionError(
                "Baseline adoption preflight requires the exact immutable 042 ledger"
            )
        ledger = SchemaMigrationLedger(self.database)
        records = ledger.read_records()
        _validate_legacy_manifest_records(records, manifest)
        adoptions = ledger.read_adoptions() if validator._adoption_table_exists() else []
        if adoptions:
            raise MigrationDefinitionError(
                "Baseline adoption preflight requires an unadopted legacy ledger"
            )
        evidence = self._physical_evidence(manifest)
        counts = _retained_data_counts(self.database)
        baseline = catalog[0]
        return {
            "mode": "preflight",
            "status": "ready-for-adoption",
            "source_generation": str(manifest["legacy_generation"]),
            "source_head": str(manifest["legacy_head"]),
            "target_baseline": baseline.version,
            "target_baseline_name": baseline.name,
            "target_baseline_checksum": baseline.checksum,
            "legacy_catalog_digest": str(manifest["catalog_digest"]),
            **evidence,
            "retained_data_counts": counts,
            "retained_data_digest": digest_payload(counts),
            "runtime_config_summary": _runtime_config_summary(self.database),
            "migrator_build": build,
        }

    def verify(self, *, expected_migrator_build: str) -> dict[str, Any]:
        build = _safe_migrator_build(expected_migrator_build)
        catalog, manifest, migrator = self._load_context(build)
        schema_head = SchemaHeadValidator(
            self.database,
            self.migrations_dir,
        ).require_current()
        ledger = SchemaMigrationLedger(self.database)
        records = ledger.read_records()
        validator = SchemaHeadValidator(self.database, self.migrations_dir)
        if not validator._adoption_table_exists():
            raise MigrationDefinitionError(
                "Baseline adoption verification requires adoption metadata"
            )
        adoptions = ledger.read_adoptions()
        generation, _ = migrator._validate_baseline_records(
            records=records,
            catalog=catalog,
            manifest=manifest,
            adoptions=adoptions,
            require_full=True,
        )
        if generation != "adopted-legacy":
            raise MigrationDefinitionError(
                "Baseline adoption verification does not accept a fresh baseline database"
            )
        adoption = adoptions[0]
        if str(adoption["migrator_build"]) != build:
            raise MigrationDefinitionError(
                "Baseline adoption migrator build does not match the expected build"
            )
        evidence = self._physical_evidence(manifest)
        counts = _retained_data_counts(self.database)
        try:
            adopted_counts = json.loads(str(adoption["retained_data_counts_json"]))
        except json.JSONDecodeError as exc:
            raise MigrationDefinitionError(
                "Baseline adoption retained-data evidence is invalid"
            ) from exc
        if counts != adopted_counts:
            raise MigrationDefinitionError(
                "Baseline adoption retained-data counts changed before verification"
            )
        return {
            "mode": "verify",
            "status": "adoption-verified",
            "source_generation": str(manifest["legacy_generation"]),
            "source_head": str(manifest["legacy_head"]),
            "target_baseline": catalog[0].version,
            "schema_head": schema_head,
            "marker_count": sum(
                1 for record in records if str(record["version"]) == BASELINE_VERSION
            ),
            "adoption_metadata_count": len(adoptions),
            "legacy_catalog_digest": str(manifest["catalog_digest"]),
            **evidence,
            "retained_data_counts": counts,
            "retained_data_digest": digest_payload(counts),
            "runtime_config_summary": _runtime_config_summary(self.database),
            "migrator_build": build,
            "readiness": {
                "schema_head_current": True,
                "adoption_verified": True,
                "business_start_gate": "schema-verified",
            },
        }

    def _load_context(
        self,
        migrator_build: str,
    ) -> tuple[tuple[MigrationArtifact, ...], dict[str, Any], Migrator]:
        catalog = load_migration_catalog(self.migrations_dir)
        migrator = Migrator(
            self.database,
            self.migrations_dir,
            migrator_build=migrator_build,
        )
        manifest = migrator._load_baseline_manifest()
        migrator._validate_baseline_catalog(catalog)
        if catalog[0].version != str(manifest["target_baseline"]):
            raise MigrationDefinitionError(
                "Baseline adoption target does not match the immutable manifest"
            )
        return catalog, manifest, migrator

    def _physical_evidence(self, manifest: dict[str, Any]) -> dict[str, str]:
        expected_schema = _manifest_schema_for_engine(manifest, self.database.engine)
        actual_schema = schema_snapshot(self.database)
        if str(actual_schema["fingerprint"]) != str(expected_schema["fingerprint"]):
            raise MigrationDefinitionError(
                "Legacy 042 schema fingerprint does not match the immutable manifest"
            )
        expected_comments = manifest.get("postgres_comments")
        if not isinstance(expected_comments, dict):
            raise MigrationDefinitionError(
                "Legacy manifest is missing the PostgreSQL comment fingerprint"
            )
        if self.database.engine == "postgres":
            actual_comments = postgres_comment_snapshot(self.database)
            if str(actual_comments["digest"]) != str(expected_comments["digest"]):
                raise MigrationDefinitionError(
                    "Legacy 042 PostgreSQL comments do not match the immutable manifest"
                )
        elif self.database.execute("pragma foreign_key_check"):
            raise MigrationDefinitionError(
                "Legacy 042 schema has foreign key integrity errors"
            )
        return {
            "schema_fingerprint": str(actual_schema["fingerprint"]),
            "comment_manifest_digest": str(expected_comments["digest"]),
        }


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
        baseline_manifest_exists = (self.migrations_dir / LEGACY_MANIFEST_FILENAME).is_file()
        if baseline_manifest_exists or catalog[0].version == BASELINE_VERSION:
            if catalog[0].version != BASELINE_VERSION:
                raise MigrationDefinitionError(
                    f"Baseline migration catalog must start at {BASELINE_VERSION}"
                )
            return self._run_baseline_generation(catalog)
        return self._run_legacy_catalog(catalog)

    def _run_legacy_catalog(
        self,
        catalog: tuple[MigrationArtifact, ...],
    ) -> MigrationRunResult:
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
                for artifact in catalog[len(records) :]:
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

    def _run_baseline_generation(
        self,
        catalog: tuple[MigrationArtifact, ...],
    ) -> MigrationRunResult:
        manifest = self._load_baseline_manifest()
        self._validate_baseline_catalog(catalog)
        with self.database.session():
            lock_acquired = False
            try:
                self._acquire_lock()
                lock_acquired = True
                ledger = SchemaMigrationLedger(self.database)
                ledger.ensure_table()
                ledger.ensure_adoption_table()
                records = ledger.read_records()
                baselined = 0
                if not records:
                    if self._application_schema_exists():
                        raise MigrationDefinitionError(
                            "Non-empty application schema has no migration ledger; "
                            "baseline adoption requires the exact immutable 042 ledger"
                        )
                elif self._is_exact_legacy_ledger(records, manifest):
                    ledger.adopt_legacy_baseline(
                        manifest=manifest,
                        baseline=catalog[0],
                        migrator_build=self.migrator_build,
                    )
                    baselined = 1
                    records = ledger.read_records()

                _, active_records = self._validate_baseline_records(
                    records=records,
                    catalog=catalog,
                    manifest=manifest,
                    adoptions=ledger.read_adoptions(),
                    require_full=False,
                )
                applied: list[str] = []
                for artifact in catalog[len(active_records) :]:
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

    def _load_baseline_manifest(self) -> dict[str, Any]:
        path = self.migrations_dir / LEGACY_MANIFEST_FILENAME
        try:
            return load_legacy_manifest(path)
        except ValueError as exc:
            raise MigrationDefinitionError(str(exc)) from exc

    def _validate_baseline_catalog(
        self,
        catalog: tuple[MigrationArtifact, ...],
    ) -> None:
        if catalog[0].version != BASELINE_VERSION:
            raise MigrationDefinitionError(
                f"Baseline migration catalog must start at {BASELINE_VERSION}"
            )
        previous = int(BASELINE_VERSION)
        for artifact in catalog[1:]:
            if not re.fullmatch(r"[0-9]{3}", artifact.version):
                raise MigrationDefinitionError(
                    "Post-baseline migration versions must be three-digit integers"
                )
            current = int(artifact.version)
            if current < 101 or current <= previous:
                raise MigrationDefinitionError(
                    "Post-baseline migration versions must increase monotonically from 101"
                )
            previous = current

    def _is_exact_legacy_ledger(
        self,
        records: list[dict[str, Any]],
        manifest: dict[str, Any],
    ) -> bool:
        catalog = manifest.get("catalog")
        if not isinstance(catalog, list) or len(records) != len(catalog):
            return False
        return all(
            str(row["version"]) == str(entry["version"])
            and str(row["name"]) == str(entry["name"])
            and str(row["checksum"]) == str(entry["checksum"])
            for row, entry in zip(records, catalog, strict=True)
        )

    def _validate_baseline_records(
        self,
        *,
        records: list[dict[str, Any]],
        catalog: tuple[MigrationArtifact, ...],
        manifest: dict[str, Any],
        adoptions: list[dict[str, Any]],
        require_full: bool,
    ) -> tuple[str, list[dict[str, Any]]]:
        legacy_catalog = manifest.get("catalog")
        if not isinstance(legacy_catalog, list):
            raise MigrationDefinitionError("Legacy migration manifest catalog is missing")
        if not records:
            if adoptions:
                raise MigrationDefinitionError(
                    "Baseline adoption metadata exists without a migration marker"
                )
            active_records: list[dict[str, Any]] = []
            generation = "fresh"
        elif str(records[0]["version"]) == BASELINE_VERSION:
            if adoptions:
                raise MigrationDefinitionError(
                    "Fresh baseline ledger must not contain legacy adoption metadata"
                )
            active_records = records
            generation = "fresh"
        elif str(records[0]["version"]) == str(legacy_catalog[0]["version"]):
            if len(records) < len(legacy_catalog):
                current_head = str(records[-1]["version"])
                raise MigrationDefinitionError(
                    "Legacy database must first be upgraded with the old migrator to exact "
                    f"head {BASELINE_ADOPTION_SOURCE_HEAD}; current head is {current_head}"
                )
            legacy_records = records[: len(legacy_catalog)]
            _validate_legacy_manifest_records(legacy_records, manifest)
            active_records = records[len(legacy_catalog) :]
            if not active_records or str(active_records[0]["version"]) != BASELINE_VERSION:
                raise MigrationDefinitionError(
                    "Legacy 042 ledger is missing the baseline 100 adoption marker"
                )
            _validate_adoption_metadata(
                rows=adoptions,
                manifest=manifest,
                baseline=catalog[0],
                engine=self.database.engine,
            )
            generation = "adopted-legacy"
        else:
            raise MigrationDefinitionError(
                "Migration ledger generation is unknown to this baseline build"
            )

        self._validate_applied_prefix(active_records, catalog)
        if require_full and len(active_records) != len(catalog):
            current_head = str(active_records[-1]["version"]) if active_records else "none"
            raise MigrationDefinitionError(
                f"Database schema head is {current_head}; expected {catalog[-1].version}"
            )
        return generation, active_records

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
        sqlite_foreign_keys_off = (
            self.database.engine == "sqlite"
            and "-- migration: sqlite-foreign-keys-off" in artifact.sql
        )
        try:
            if sqlite_foreign_keys_off:
                self.database.execute("PRAGMA foreign_keys = OFF")
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
        finally:
            if sqlite_foreign_keys_off:
                self.database.execute("PRAGMA foreign_keys = ON")

    def _application_schema_exists(self) -> bool:
        if self.database.engine == "sqlite":
            return (
                self.database.execute_one(
                    """
                    select name
                      from sqlite_master
                     where type = 'table'
                       and name not in ('schema_migration', 'schema_baseline_adoption')
                       and name not like 'sqlite_%'
                     limit 1
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
                   and table_type = 'BASE TABLE'
                   and table_name not in
                       ('schema_migration', 'schema_baseline_adoption')
                 limit 1
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


class BaselineAdoptionRollback:
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

    def run(self) -> str:
        catalog = load_migration_catalog(self.migrations_dir)
        migrator = Migrator(
            self.database,
            self.migrations_dir,
            migrator_build=self.migrator_build,
        )
        if catalog[0].version != BASELINE_VERSION:
            raise MigrationDefinitionError(
                "Baseline adoption rollback requires the baseline generation catalog"
            )
        manifest = migrator._load_baseline_manifest()
        migrator._validate_baseline_catalog(catalog)
        with self.database.session():
            lock_acquired = False
            try:
                migrator._acquire_lock()
                lock_acquired = True
                ledger = SchemaMigrationLedger(self.database)
                if (
                    not SchemaHeadValidator(self.database, self.migrations_dir)._ledger_exists()
                    or not SchemaHeadValidator(
                        self.database, self.migrations_dir
                    )._adoption_table_exists()
                ):
                    raise MigrationDefinitionError(
                        "Baseline adoption rollback requires an adopted legacy ledger"
                    )
                records = ledger.read_records()
                generation, active_records = migrator._validate_baseline_records(
                    records=records,
                    catalog=catalog,
                    manifest=manifest,
                    adoptions=ledger.read_adoptions(),
                    require_full=False,
                )
                if generation != "adopted-legacy":
                    raise MigrationDefinitionError(
                        "Fresh baseline databases cannot use adoption rollback"
                    )
                if any(int(str(row["version"])[:3]) >= 101 for row in active_records):
                    raise MigrationDefinitionError(
                        "Baseline adoption rollback is forbidden after migration 101 or later"
                    )
                with self.database.unit_of_work():
                    self.database.execute(
                        "delete from schema_baseline_adoption where target_baseline = ?",
                        (BASELINE_VERSION,),
                    )
                    self.database.execute(
                        "delete from schema_migration where version = ?",
                        (BASELINE_VERSION,),
                    )
                return BASELINE_ADOPTION_SOURCE_HEAD
            finally:
                if lock_acquired:
                    migrator._release_lock()


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
                    f"Database schema ledger is missing; expected head {expected_head}"
                )
            ledger = SchemaMigrationLedger(self.database)
            records = ledger.read_records()
            migrator = Migrator(
                self.database,
                self.migrations_dir,
                migrator_build="schema-head-validator",
            )
            if catalog[0].version == BASELINE_VERSION:
                manifest = migrator._load_baseline_manifest()
                migrator._validate_baseline_catalog(catalog)
                adoptions = ledger.read_adoptions() if self._adoption_table_exists() else []
                migrator._validate_baseline_records(
                    records=records,
                    catalog=catalog,
                    manifest=manifest,
                    adoptions=adoptions,
                    require_full=True,
                )
            else:
                migrator._validate_applied_prefix(records, catalog)
                current_head = str(records[-1]["version"]) if records else "none"
                if len(records) != len(catalog):
                    raise SchemaHeadError(
                        f"Database schema head is {current_head}; expected {expected_head}"
                    )
            return expected_head
        except SchemaHeadError:
            raise
        except MigrationDefinitionError as exc:
            raise SchemaHeadError(str(exc)) from exc
        except Exception as exc:
            raise SchemaHeadError(
                f"Database schema head could not be read; expected {expected_head}"
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

    def _adoption_table_exists(self) -> bool:
        if self.database.engine == "sqlite":
            return (
                self.database.execute_one(
                    """
                    select name
                      from sqlite_master
                     where type = 'table' and name = 'schema_baseline_adoption'
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
                   and table_name = 'schema_baseline_adoption'
                """
            )
            is not None
        )
