from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable

from jsonschema import Draft202012Validator


FACT_SOURCE_MANIFEST_FILENAME = "schema_fact_sources.json"
FACT_SOURCE_SCHEMA_FILENAME = "schema_fact_sources.schema.json"

_CREATE_TABLE_BLOCK = re.compile(
    r"CREATE\s+TABLE\s+(?P<table>[a-z_][a-z0-9_]*)\s*\((?P<body>.*?)\);",
    re.IGNORECASE | re.DOTALL,
)
_COLUMN_DEFINITION = re.compile(
    r"(?:^|,)\s*(?P<column>[a-z_][a-z0-9_]*)\s+"
    r"(?:TEXT|INTEGER|BIGINT|BOOLEAN|JSONB|TIMESTAMPTZ|TIMESTAMP|VARCHAR|UUID|BYTEA|REAL|NUMERIC)\b",
    re.IGNORECASE | re.MULTILINE,
)
_ADD_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+(?P<table>[a-z_][a-z0-9_]*)\s+"
    r"ADD\s+COLUMN\s+(?P<column>[a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)
_VERSION = re.compile(r"[0-9]{3}")


class FactSourceManifestError(ValueError):
    """Safe validation failure for the version-controlled fact-source manifest."""


@dataclass(frozen=True)
class SchemaCatalog:
    tables: frozenset[str]
    columns: frozenset[tuple[str, str]]


def default_fact_source_manifest_path() -> Path:
    return Path(__file__).with_name(FACT_SOURCE_MANIFEST_FILENAME)


def default_fact_source_schema_path() -> Path:
    return Path(__file__).with_name(FACT_SOURCE_SCHEMA_FILENAME)


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FactSourceManifestError(f"{label} could not be read") from exc
    if not isinstance(value, dict):
        raise FactSourceManifestError(f"{label} must be a JSON object")
    return value


def load_fact_source_manifest(
    path: Path | None = None,
    *,
    schema_path: Path | None = None,
) -> dict[str, Any]:
    manifest_path = path or default_fact_source_manifest_path()
    definition_path = schema_path or default_fact_source_schema_path()
    manifest = _load_json_object(manifest_path, label="Fact-source manifest")
    schema = _load_json_object(definition_path, label="Fact-source manifest schema")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "root"
        raise FactSourceManifestError(
            f"Fact-source manifest schema validation failed at {location}"
        )
    _validate_semantics(manifest)
    return manifest


def _validate_semantics(manifest: dict[str, Any]) -> None:
    entries = manifest["entries"]
    identifiers: set[str] = set()
    objects: set[tuple[str, str, str | None]] = set()
    for entry in entries:
        identifier = str(entry["id"])
        if identifier in identifiers:
            raise FactSourceManifestError(
                f"Fact-source manifest contains duplicate id {identifier}"
            )
        identifiers.add(identifier)
        object_key = (
            str(entry["object_type"]),
            str(entry["table"]),
            str(entry.get("column")) if entry.get("column") is not None else None,
        )
        if object_key in objects:
            raise FactSourceManifestError(
                f"Fact-source manifest contains duplicate object {identifier}"
            )
        objects.add(object_key)

        classification = str(entry["classification"])
        retirement = entry["retirement"]
        if classification == "compatibility_shadow":
            if not entry.get("canonical_source"):
                raise FactSourceManifestError(
                    f"Compatibility shadow {identifier} requires canonical_source"
                )
            if retirement["status"] not in {"planned", "blocked"}:
                raise FactSourceManifestError(
                    f"Compatibility shadow {identifier} requires an exit status"
                )
            if retirement["earliest_phase"] != "contract/drop" or not retirement["gates"]:
                raise FactSourceManifestError(
                    f"Compatibility shadow {identifier} requires contract/drop gates"
                )
        if classification == "immutable_snapshot" and not entry.get("source_contract"):
            raise FactSourceManifestError(
                f"Immutable snapshot {identifier} requires source_contract"
            )
        if classification == "operational_coordination_fact":
            if retirement["status"] != "retained":
                raise FactSourceManifestError(
                    f"Operational fact {identifier} must remain retained"
                )
        if classification == "one_time_migration_artifact":
            if retirement["status"] != "blocked" or not retirement["gates"]:
                raise FactSourceManifestError(
                    f"One-time artifact {identifier} must remain blocked until gated"
                )

    migration_plan = manifest["migration_plan"]
    versions = [
        migration_plan["expand_candidate"],
        migration_plan["backfill_checkpoint_candidate"],
        migration_plan["contract_candidate"],
    ]
    if any(_VERSION.fullmatch(str(version)) is None for version in versions):
        raise FactSourceManifestError("Migration plan versions must be three digits")
    if [int(version) for version in versions] != sorted({int(version) for version in versions}):
        raise FactSourceManifestError(
            "Migration plan versions must be unique and monotonically increasing"
        )
    if int(versions[0]) <= int(manifest["baseline_predecessor"]):
        raise FactSourceManifestError(
            "Migration plan must start after the baseline predecessor"
        )


def schema_catalog_from_sql(sql: str) -> SchemaCatalog:
    tables: set[str] = set()
    columns: set[tuple[str, str]] = set()
    for match in _CREATE_TABLE_BLOCK.finditer(sql):
        table = match.group("table").lower()
        tables.add(table)
        for column_match in _COLUMN_DEFINITION.finditer(match.group("body")):
            columns.add((table, column_match.group("column").lower()))
    return SchemaCatalog(tables=frozenset(tables), columns=frozenset(columns))


def baseline_engine_catalogs(path: Path) -> dict[str, SchemaCatalog]:
    try:
        sql = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FactSourceManifestError("Schema baseline could not be read") from exc
    marker = "-- postgres-only\nCREATE TABLE agent_session"
    if marker not in sql:
        raise FactSourceManifestError("Schema baseline engine boundary is missing")
    sqlite_sql, postgres_sql = sql.split(marker, maxsplit=1)
    catalogs = {
        "sqlite": schema_catalog_from_sql(sqlite_sql),
        "postgres": schema_catalog_from_sql("CREATE TABLE agent_session" + postgres_sql),
    }
    later_sql = "\n".join(
        candidate.read_text(encoding="utf-8")
        for candidate in sorted(path.parent.glob("*.sql"))
        if candidate != path
    )
    added_columns = {
        (match.group("table").lower(), match.group("column").lower())
        for match in _ADD_COLUMN.finditer(later_sql)
    }
    later_catalog = schema_catalog_from_sql(later_sql)
    return {
        engine: SchemaCatalog(
            tables=frozenset((*catalog.tables, *later_catalog.tables)),
            columns=frozenset(
                (*catalog.columns, *later_catalog.columns, *added_columns)
            ),
        )
        for engine, catalog in catalogs.items()
    }


def reconcile_manifest_with_catalogs(
    manifest: dict[str, Any],
    catalogs: dict[str, SchemaCatalog],
) -> None:
    missing: list[str] = []
    for engine, catalog in sorted(catalogs.items()):
        for entry in manifest["entries"]:
            table = str(entry["table"]).lower()
            identifier = str(entry["id"])
            if table not in catalog.tables:
                missing.append(f"{engine}:table:{identifier}")
                continue
            column = entry.get("column")
            if column is not None and (table, str(column).lower()) not in catalog.columns:
                missing.append(f"{engine}:column:{identifier}")
    if missing:
        raise FactSourceManifestError(
            "Fact-source manifest references unknown schema objects: " + ", ".join(missing[:20])
        )


def referenced_code_paths(manifest: dict[str, Any]) -> Iterable[str]:
    for entry in manifest["entries"]:
        for value in (*entry["writers"], *entry["readers"]):
            if str(value).startswith("code:"):
                yield str(value).removeprefix("code:")


def validate_declared_code_paths(manifest: dict[str, Any], repository_root: Path) -> None:
    missing = sorted(
        path for path in set(referenced_code_paths(manifest)) if not (repository_root / path).exists()
    )
    if missing:
        raise FactSourceManifestError(
            "Fact-source manifest references missing code paths: " + ", ".join(missing[:20])
        )
