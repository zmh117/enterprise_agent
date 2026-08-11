from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.shared.database import Database


LEGACY_MANIFEST_FILENAME = "legacy-v1-manifest.json"
LEGACY_GENERATION = "legacy-v1"
LEGACY_HEAD = "042"
TARGET_BASELINE = "100"
INTERNAL_TABLES = frozenset({"schema_migration", "schema_baseline_adoption"})


def digest_payload(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def catalog_digest(entries: Iterable[Mapping[str, Any]]) -> str:
    return digest_payload(
        [
            {
                "version": str(entry["version"]),
                "name": str(entry["name"]),
                "checksum": str(entry["checksum"]),
            }
            for entry in entries
        ]
    )


def load_legacy_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Legacy migration manifest could not be read") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Legacy migration manifest must be an object")
    required = {
        "format_version": 1,
        "legacy_generation": LEGACY_GENERATION,
        "legacy_head": LEGACY_HEAD,
        "target_baseline": TARGET_BASELINE,
    }
    for key, expected in required.items():
        if manifest.get(key) != expected:
            raise ValueError(f"Legacy migration manifest has invalid {key}")
    catalog = manifest.get("catalog")
    if not isinstance(catalog, list) or not catalog:
        raise ValueError("Legacy migration manifest catalog is missing")
    if manifest.get("catalog_digest") != catalog_digest(catalog):
        raise ValueError("Legacy migration manifest catalog digest does not match")
    if str(catalog[-1].get("version")) != LEGACY_HEAD:
        raise ValueError("Legacy migration manifest head does not match")
    return manifest


def _normalize_sql(value: Any) -> str:
    return " ".join(str(value or "").replace('"public".', "").replace("public.", "").split())


def _sqlite_schema_payload(database: Database) -> dict[str, Any]:
    table_rows = database.execute(
        """
        select rowid, name
          from sqlite_master
         where type = 'table'
           and name not in ('schema_migration', 'schema_baseline_adoption')
           and name not like 'sqlite_%'
         order by rowid
        """
    )
    tables: list[dict[str, Any]] = []
    for table_row in table_rows:
        table = str(table_row["name"])
        columns = [
            {
                "name": str(row["name"]),
                "type": str(row["type"]).upper(),
                "not_null": bool(row["notnull"]),
                "default": row["dflt_value"],
                "primary_key_order": int(row["pk"]),
            }
            for row in database.execute(f'pragma table_info("{table}")')
        ]
        foreign_keys = [
            {
                "id": int(row["id"]),
                "sequence": int(row["seq"]),
                "target_table": str(row["table"]),
                "from_column": str(row["from"]),
                "target_column": str(row["to"]),
                "on_update": str(row["on_update"]).upper(),
                "on_delete": str(row["on_delete"]).upper(),
            }
            for row in database.execute(f'pragma foreign_key_list("{table}")')
        ]
        unique_constraints: list[dict[str, Any]] = []
        for index_row in database.execute(f'pragma index_list("{table}")'):
            if not bool(index_row["unique"]):
                continue
            index_name = str(index_row["name"])
            unique_constraints.append(
                {
                    "origin": str(index_row["origin"]),
                    "partial": bool(index_row["partial"]),
                    "columns": [
                        str(row["name"])
                        for row in database.execute(f'pragma index_info("{index_name}")')
                    ],
                }
            )
        tables.append(
            {
                "name": table,
                "columns": columns,
                "foreign_keys": sorted(
                    foreign_keys,
                    key=lambda item: (item["id"], item["sequence"]),
                ),
                "unique_constraints": sorted(
                    unique_constraints,
                    key=lambda item: (
                        item["origin"],
                        item["partial"],
                        item["columns"],
                    ),
                ),
            }
        )
    indexes = [
        {
            "name": str(row["name"]),
            "table": str(row["tbl_name"]),
            "sql": _normalize_sql(row["sql"]),
        }
        for row in database.execute(
            """
            select rowid, name, tbl_name, sql
              from sqlite_master
             where type = 'index' and sql is not null
             order by rowid
            """
        )
    ]
    return {
        "table_count": len(tables),
        "column_count": sum(len(table["columns"]) for table in tables),
        "explicit_index_count": len(indexes),
        "tables": tables,
        "indexes": indexes,
    }


def _postgres_schema_payload(database: Database) -> dict[str, Any]:
    table_rows = database.execute(
        """
        select table_name
          from information_schema.tables
         where table_schema = 'public'
           and table_type = 'BASE TABLE'
           and table_name not in ('schema_migration', 'schema_baseline_adoption')
         order by table_name
        """
    )
    table_names = [str(row["table_name"]) for row in table_rows]
    columns = database.execute(
        """
        select table_name, column_name, ordinal_position, data_type,
               is_nullable, column_default
          from information_schema.columns
         where table_schema = 'public'
           and table_name not in ('schema_migration', 'schema_baseline_adoption')
         order by table_name, ordinal_position
        """
    )
    constraints = database.execute(
        """
        select relation.relname as table_name,
               constraint_row.contype as constraint_type,
               pg_get_constraintdef(constraint_row.oid, true) as definition
          from pg_constraint constraint_row
          join pg_class relation on relation.oid = constraint_row.conrelid
          join pg_namespace namespace on namespace.oid = relation.relnamespace
         where namespace.nspname = 'public'
           and relation.relkind in ('r', 'p')
           and relation.relname not in ('schema_migration', 'schema_baseline_adoption')
         order by relation.relname, constraint_row.contype,
                  pg_get_constraintdef(constraint_row.oid, true)
        """
    )
    indexes = database.execute(
        """
        select table_relation.relname as tablename,
               index_relation.relname as indexname,
               pg_get_indexdef(index_relation.oid) as indexdef
          from pg_index index_row
          join pg_class index_relation on index_relation.oid = index_row.indexrelid
          join pg_class table_relation on table_relation.oid = index_row.indrelid
          join pg_namespace namespace on namespace.oid = table_relation.relnamespace
          left join pg_constraint constraint_row
            on constraint_row.conindid = index_relation.oid
         where namespace.nspname = 'public'
           and constraint_row.oid is null
           and table_relation.relname not in
               ('schema_migration', 'schema_baseline_adoption')
         order by table_relation.relname, index_relation.relname
        """
    )
    payload = {
        "table_count": len(table_names),
        "column_count": len(columns),
        "index_count": len(indexes),
        "tables": table_names,
        "columns": [
            {
                "table": str(row["table_name"]),
                "name": str(row["column_name"]),
                "type": str(row["data_type"]),
                "nullable": str(row["is_nullable"]),
                "default": _normalize_sql(row["column_default"]),
            }
            for row in columns
        ],
        "constraints": [
            {
                "table": str(row["table_name"]),
                "type": str(row["constraint_type"]),
                "definition": _normalize_sql(row["definition"]),
            }
            for row in constraints
        ],
        "indexes": [
            {
                "table": str(row["tablename"]),
                "name": str(row["indexname"]),
                "definition": _normalize_sql(row["indexdef"]),
            }
            for row in indexes
        ],
    }
    return payload


def schema_snapshot(database: Database) -> dict[str, Any]:
    payload = (
        _sqlite_schema_payload(database)
        if database.engine == "sqlite"
        else _postgres_schema_payload(database)
    )
    return {"fingerprint": digest_payload(payload), **payload}


def postgres_comment_snapshot(database: Database) -> dict[str, Any]:
    if database.engine != "postgres":
        raise ValueError("PostgreSQL comments can only be read from PostgreSQL")
    rows = database.execute(
        """
        select relation.relname as table_name,
               attribute.attname as column_name,
               description.description as comment
          from pg_description description
          join pg_class relation on relation.oid = description.objoid
          join pg_namespace namespace on namespace.oid = relation.relnamespace
         left join pg_attribute attribute
            on attribute.attrelid = relation.oid
           and attribute.attnum = description.objsubid
         where namespace.nspname = 'public'
           and relation.relkind in ('r', 'p')
           and relation.relname not in ('schema_migration', 'schema_baseline_adoption')
           and description.description is not null
         order by relation.relname, description.objsubid
        """
    )
    tables: dict[str, str] = {}
    columns: dict[str, str] = {}
    for row in rows:
        table = str(row["table_name"])
        column = row["column_name"]
        if column is None:
            tables[table] = str(row["comment"])
        else:
            columns[f"{table}.{column}"] = str(row["comment"])
    payload = {
        "tables": dict(sorted(tables.items())),
        "columns": dict(sorted(columns.items())),
    }
    return {
        "table_count": len(tables),
        "column_count": len(columns),
        "digest": digest_payload(payload),
        **payload,
    }
