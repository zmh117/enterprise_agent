from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
import uuid


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.shared.database import Database  # noqa: E402
from app.shared.migrations import Migrator, load_migration_catalog  # noqa: E402
from app.shared.schema_baseline import (  # noqa: E402
    postgres_comment_snapshot,
    schema_snapshot,
)


LEGACY_HEAD = "042"
TARGET_BASELINE = "100"
TABLE_COMMENT = re.compile(
    r"COMMENT\s+ON\s+TABLE\s+(?:public\.)?\"?([a-z0-9_]+)\"?\s+IS\s+"
    r"'((?:''|[^'])*)'\s*;",
    re.IGNORECASE | re.DOTALL,
)
COLUMN_COMMENT = re.compile(
    r"COMMENT\s+ON\s+COLUMN\s+(?:public\.)?\"?([a-z0-9_]+)\"?\."
    r"\"?([a-z0-9_]+)\"?\s+IS\s+'((?:''|[^'])*)'\s*;",
    re.IGNORECASE | re.DOTALL,
)


def _digest_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _comments(sql: str) -> dict[str, Any]:
    table_comments = {
        match.group(1): match.group(2).replace("''", "'") for match in TABLE_COMMENT.finditer(sql)
    }
    column_comments = {
        f"{match.group(1)}.{match.group(2)}": match.group(3).replace("''", "'")
        for match in COLUMN_COMMENT.finditer(sql)
    }
    payload = {
        "tables": dict(sorted(table_comments.items())),
        "columns": dict(sorted(column_comments.items())),
    }
    return {
        "table_count": len(table_comments),
        "column_count": len(column_comments),
        "digest": _digest_json(payload),
        **payload,
    }


def _sqlite_schema(database: Database) -> dict[str, Any]:
    table_rows = database.execute(
        """
        select rowid, name, sql
          from sqlite_master
         where type = 'table'
           and name <> 'schema_migration'
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
            "sql": " ".join(str(row["sql"]).split()),
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
    payload = {
        "table_count": len(tables),
        "column_count": sum(len(table["columns"]) for table in tables),
        "explicit_index_count": len(indexes),
        "tables": tables,
        "indexes": indexes,
    }
    return {"fingerprint": _digest_json(payload), **payload}


TABLE_FOREIGN_KEY = re.compile(
    r",\s*FOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+"
    r"\"?[a-z_][a-z0-9_]*\"?\s*\([^)]*\)"
    r"(?:\s+ON\s+(?:DELETE|UPDATE)\s+(?:NO\s+ACTION|RESTRICT|CASCADE|SET\s+NULL|SET\s+DEFAULT))*",
    re.IGNORECASE | re.DOTALL,
)
INLINE_REFERENCE = re.compile(
    r"\s+REFERENCES\s+\"?[a-z_][a-z0-9_]*\"?\s*\([^)]*\)"
    r"(?:\s+ON\s+(?:DELETE|UPDATE)\s+(?:NO\s+ACTION|RESTRICT|CASCADE|SET\s+NULL|SET\s+DEFAULT))*",
    re.IGNORECASE | re.DOTALL,
)


def _postgres_table_sql(sql: str) -> str:
    without_table_foreign_keys = TABLE_FOREIGN_KEY.sub("", sql)
    return INLINE_REFERENCE.sub("", without_table_foreign_keys)


def _postgres_foreign_key_sql(database: Database, table: str) -> list[str]:
    rows = database.execute(f'pragma foreign_key_list("{table}")')
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["id"]), []).append(row)
    statements: list[str] = []
    for foreign_key_id, entries in sorted(grouped.items()):
        entries.sort(key=lambda row: int(row["seq"]))
        target_table = str(entries[0]["table"])
        from_columns = ", ".join(f'"{row["from"]}"' for row in entries)
        target_columns = ", ".join(f'"{row["to"]}"' for row in entries)
        on_update = str(entries[0]["on_update"]).upper()
        on_delete = str(entries[0]["on_delete"]).upper()
        statements.append(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "fk_{table}_{foreign_key_id}" '
            f'FOREIGN KEY ({from_columns}) REFERENCES "{target_table}" ({target_columns}) '
            f"ON UPDATE {on_update} ON DELETE {on_delete};"
        )
    return statements


def _render_baseline(database: Database, comments_sql: str) -> str:
    tables = database.execute(
        """
        select rowid, name, sql
          from sqlite_master
         where type = 'table'
           and name <> 'schema_migration'
           and name not like 'sqlite_%'
         order by rowid
        """
    )
    indexes = database.execute(
        """
        select rowid, name, sql
          from sqlite_master
         where type = 'index' and sql is not null
         order by rowid
        """
    )
    sqlite_tables = [f"-- sqlite-only\n{str(row['sql']).rstrip(';')};\n" for row in tables]
    postgres_tables = [
        f"-- postgres-only\n{_postgres_table_sql(str(row['sql'])).rstrip(';')};\n" for row in tables
    ]
    postgres_foreign_keys = [
        f"-- postgres-only\n{statement}\n"
        for row in tables
        for statement in _postgres_foreign_key_sql(database, str(row["name"]))
    ]
    statements = [
        "-- Baseline v1: final schema equivalent to the immutable legacy 001-042 chain.",
        "-- Schema only: identity bootstrap and local fixtures are deliberately separate.",
        "",
        *sqlite_tables,
        *postgres_tables,
        *postgres_foreign_keys,
        *(f"{str(row['sql']).rstrip(';')};\n" for row in indexes),
        "-- postgres-only",
        comments_sql.strip(),
        "",
    ]
    return "\n".join(statements)


def _fingerprint_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot[key]
        for key in (
            "fingerprint",
            "table_count",
            "column_count",
            "explicit_index_count",
            "index_count",
            "digest",
        )
        if key in snapshot
    }


def _postgres_equivalence(
    *,
    admin_dsn: str,
    legacy_dir: Path,
    baseline_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    parameters = conninfo_to_dict(admin_dsn)
    names = {
        "legacy": f"baseline_legacy_{uuid.uuid4().hex[:12]}",
        "baseline": f"baseline_fresh_{uuid.uuid4().hex[:12]}",
    }
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        for name in names.values():
            admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    snapshots: dict[str, dict[str, Any]] = {}
    comments: dict[str, dict[str, Any]] = {}
    try:
        for generation, database_name in names.items():
            database_parameters = dict(parameters)
            database_parameters["dbname"] = database_name
            database = Database(make_conninfo(**database_parameters))
            try:
                migrations_dir = legacy_dir if generation == "legacy" else baseline_dir
                Migrator(
                    database,
                    migrations_dir,
                    migrator_build=f"schema-baseline-{generation}-probe",
                ).run()
                snapshots[generation] = schema_snapshot(database)
                comments[generation] = postgres_comment_snapshot(database)
            finally:
                database.close()
        if snapshots["legacy"] != snapshots["baseline"]:
            legacy_lines = json.dumps(
                snapshots["legacy"], ensure_ascii=False, indent=2, sort_keys=True
            ).splitlines()
            baseline_lines = json.dumps(
                snapshots["baseline"], ensure_ascii=False, indent=2, sort_keys=True
            ).splitlines()
            difference = "\n".join(
                list(
                    difflib.unified_diff(
                        legacy_lines,
                        baseline_lines,
                        fromfile="legacy-042",
                        tofile="baseline-100",
                    )
                )[:160]
            )
            raise SystemExit(
                "PostgreSQL legacy and baseline schema fingerprints differ: "
                f"{snapshots['legacy']['fingerprint']} != "
                f"{snapshots['baseline']['fingerprint']}\n{difference}"
            )
        if comments["legacy"] != comments["baseline"]:
            legacy_lines = json.dumps(
                comments["legacy"], ensure_ascii=False, indent=2, sort_keys=True
            ).splitlines()
            baseline_lines = json.dumps(
                comments["baseline"], ensure_ascii=False, indent=2, sort_keys=True
            ).splitlines()
            difference = "\n".join(
                list(
                    difflib.unified_diff(
                        legacy_lines,
                        baseline_lines,
                        fromfile="legacy-042-comments",
                        tofile="baseline-100-comments",
                    )
                )[:160]
            )
            raise SystemExit(f"PostgreSQL legacy and baseline comments differ\n{difference}")
        return snapshots["legacy"], comments["legacy"]
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            for name in names.values():
                admin.execute(
                    """
                    select pg_terminate_backend(pid)
                      from pg_stat_activity
                     where datname = %s and pid <> pg_backend_pid()
                    """,
                    (name,),
                )
                admin.execute(sql.SQL("drop database if exists {}").format(sql.Identifier(name)))


def build(legacy_dir: Path, output_dir: Path, *, postgres_admin_dsn: str = "") -> None:
    catalog = load_migration_catalog(legacy_dir)
    if catalog[-1].version != LEGACY_HEAD:
        raise SystemExit(f"legacy catalog must end at {LEGACY_HEAD}")
    if any(artifact.version == TARGET_BASELINE for artifact in catalog):
        raise SystemExit("legacy catalog must not contain target baseline 100")

    database = Database("sqlite:///:memory:")
    try:
        result = Migrator(
            database,
            legacy_dir,
            migrator_build="schema-baseline-generator",
        ).run()
        if result.head != LEGACY_HEAD:
            raise SystemExit(f"legacy migration ended at unexpected head {result.head}")
        schema = _sqlite_schema(database)
        comments = _comments(catalog[-1].sql)
        if comments["table_count"] != schema["table_count"]:
            raise SystemExit("table comment manifest does not cover the final schema")
        if comments["column_count"] != schema["column_count"]:
            raise SystemExit("column comment manifest does not cover the final schema")

        catalog_entries = [
            {
                "version": artifact.version,
                "name": artifact.name,
                "checksum": artifact.checksum,
            }
            for artifact in catalog
        ]
        catalog_digest = _digest_json(catalog_entries)
        manifest: dict[str, Any] = {
            "format_version": 1,
            "legacy_generation": "legacy-v1",
            "legacy_head": LEGACY_HEAD,
            "target_baseline": TARGET_BASELINE,
            "catalog_digest": catalog_digest,
            "catalog": catalog_entries,
            "sqlite_schema": _fingerprint_summary(schema),
            "postgres_comments": _fingerprint_summary(comments),
        }

        output_dir.mkdir(parents=True, exist_ok=True)
        baseline_path = output_dir / "100_baseline_v1.sql"
        manifest_path = output_dir / "legacy-v1-manifest.json"
        baseline_path.write_text(
            _render_baseline(database, catalog[-1].sql),
            encoding="utf-8",
        )
        if postgres_admin_dsn:
            postgres_schema, postgres_comments = _postgres_equivalence(
                admin_dsn=postgres_admin_dsn,
                legacy_dir=legacy_dir,
                baseline_dir=output_dir,
            )
            if postgres_comments != comments:
                raise SystemExit("PostgreSQL comments differ from the static comment manifest")
            manifest["postgres_schema"] = _fingerprint_summary(postgres_schema)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "baseline": str(baseline_path),
                    "manifest": str(manifest_path),
                    "catalog_digest": catalog_digest,
                    "schema_fingerprint": schema["fingerprint"],
                    "comment_digest": comments["digest"],
                    "tables": schema["table_count"],
                    "columns": schema["column_count"],
                    "indexes": schema["explicit_index_count"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    finally:
        database.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build baseline 100 and immutable evidence from legacy 001-042 migrations"
    )
    parser.add_argument("--legacy-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--postgres-admin-dsn",
        default="",
        help="optional admin DSN used to prove old-chain and baseline equivalence",
    )
    args = parser.parse_args()
    build(
        args.legacy_dir.resolve(),
        args.output_dir.resolve(),
        postgres_admin_dsn=args.postgres_admin_dsn,
    )


if __name__ == "__main__":
    main()
