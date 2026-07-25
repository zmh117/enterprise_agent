from __future__ import annotations

import json
from typing import Any

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


class ModelConnectionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_connections(self) -> list[dict[str, Any]]:
        rows = self.database.execute("select * from model_connection order by code")
        return [self._connection(row) for row in rows]

    def get_connection(self, code: str) -> dict[str, Any]:
        row = self.database.execute_one("select * from model_connection where code = ?", (code,))
        if not row:
            raise NotFound(
                f"Model connection not found: {code}",
                safe_message="Model connection not found",
            )
        return self._connection(row)

    def get_connection_by_id(self, connection_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from model_connection where id = ?", (connection_id,)
        )
        if not row:
            raise NotFound(
                f"Model connection not found: {connection_id}",
                safe_message="Model connection not found",
            )
        return self._connection(row)

    def create_connection(
        self,
        *,
        code: str,
        name: str,
        protocol: str,
        actor_id: str,
    ) -> dict[str, Any]:
        connection_id = new_id("model_connection")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into model_connection
              (id, code, name, protocol, current_revision_id, status, revision,
               created_by, created_at, updated_at)
            values (?, ?, ?, ?, null, 'rotation_required', 0, ?, ?, ?)
            on conflict(code) do nothing
            """,
            (connection_id, code, name, protocol, actor_id, timestamp, timestamp),
        )
        return self.get_connection(code)

    def initialize_revision_if_missing(
        self,
        *,
        connection_id: str,
        config: dict[str, Any],
        config_hash: str,
        api_key_secret_id: str | None,
        actor_id: str,
    ) -> dict[str, Any]:
        revision_id = new_id("model_connection_revision")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into model_connection_revision
              (id, connection_id, revision, status, config_json, config_hash,
               api_key_secret_id, created_by, created_at)
            values (?, ?, 1, 'rotation_required', ?, ?, ?, ?, ?)
            on conflict(connection_id, revision) do nothing
            """,
            (
                revision_id,
                connection_id,
                json.dumps(config, ensure_ascii=False, sort_keys=True),
                config_hash,
                api_key_secret_id,
                actor_id,
                timestamp,
            ),
        )
        initialized = self.database.execute_one(
            """
            select id
              from model_connection_revision
             where connection_id = ? and revision = 1
            """,
            (connection_id,),
        )
        if not initialized:
            raise NonRetryableExecutionError(
                "Default model connection revision was not initialized",
                safe_message="Default model connection initialization failed",
                error_code="model_connection_initialization_failed",
            )
        self.database.execute(
            """
            update model_connection
               set current_revision_id = ?, status = 'rotation_required',
                   revision = 1, updated_at = ?
             where id = ? and revision = 0
            """,
            (initialized["id"], timestamp, connection_id),
        )
        connection = self.get_connection_by_id(connection_id)
        current_revision_id = str(connection.get("current_revision_id") or "")
        if not current_revision_id:
            raise NonRetryableExecutionError(
                "Default model connection has no current revision",
                safe_message="Default model connection initialization failed",
                error_code="model_connection_initialization_failed",
            )
        return self.get_revision(current_revision_id)

    def append_revision(
        self,
        *,
        connection_id: str,
        expected_revision: int,
        config: dict[str, Any],
        config_hash: str,
        api_key_secret_id: str | None,
        status: str,
        actor_id: str,
    ) -> dict[str, Any]:
        connection = self.get_connection_by_id(connection_id)
        if int(connection["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Model connection revision conflict",
                safe_message="Model connection changed; refresh and try again",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(connection["revision"])},
            )
        revision = expected_revision + 1
        revision_id = new_id("model_connection_revision")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into model_connection_revision
              (id, connection_id, revision, status, config_json, config_hash,
               api_key_secret_id, created_by, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                connection_id,
                revision,
                status,
                json.dumps(config, ensure_ascii=False, sort_keys=True),
                config_hash,
                api_key_secret_id,
                actor_id,
                timestamp,
            ),
        )
        self.database.execute(
            """
            update model_connection
               set current_revision_id = ?, status = ?, revision = ?, updated_at = ?
             where id = ? and revision = ?
            """,
            (
                revision_id,
                status,
                revision,
                timestamp,
                connection_id,
                expected_revision,
            ),
        )
        refreshed = self.get_connection_by_id(connection_id)
        if int(refreshed["revision"]) != revision:
            raise NonRetryableExecutionError(
                "Model connection revision conflict",
                safe_message="Model connection changed; refresh and try again",
                error_code="revision_conflict",
            )
        return self.get_revision(revision_id)

    def set_connection_status(
        self,
        *,
        code: str,
        expected_revision: int,
        status: str,
    ) -> dict[str, Any]:
        connection = self.get_connection(code)
        if int(connection["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Model connection revision conflict",
                safe_message="Model connection changed; refresh and try again",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(connection["revision"])},
            )
        next_revision = expected_revision + 1
        self.database.execute(
            """
            update model_connection
               set status = ?, revision = ?, updated_at = ?
             where id = ? and revision = ?
            """,
            (
                status,
                next_revision,
                now_iso(),
                connection["id"],
                expected_revision,
            ),
        )
        refreshed = self.get_connection(code)
        if int(refreshed["revision"]) != next_revision:
            raise NonRetryableExecutionError(
                "Model connection revision conflict",
                safe_message="Model connection changed; refresh and try again",
                error_code="revision_conflict",
            )
        return refreshed

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select r.*, c.code connection_code, c.name connection_name,
                   c.protocol connection_protocol, c.status connection_status
              from model_connection_revision r
              join model_connection c on c.id = r.connection_id
             where r.id = ?
            """,
            (revision_id,),
        )
        if not row:
            raise NotFound(
                f"Model connection revision not found: {revision_id}",
                safe_message="Model connection revision not found",
            )
        return self._revision(row)

    def list_revisions(self, connection_id: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select r.*, c.code connection_code, c.name connection_name,
                   c.protocol connection_protocol, c.status connection_status
              from model_connection_revision r
              join model_connection c on c.id = r.connection_id
             where r.connection_id = ?
             order by r.revision desc
            """,
            (connection_id,),
        )
        return [self._revision(row) for row in rows]

    def active_application_usage(self, agent_publication_id: str) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select a.code, a.name, d.environment, p.id application_publication_id,
                   p.snapshot_json
              from business_application_deployment d
              join business_application a on a.id = d.application_id
              join business_application_publication p on p.id = d.publication_id
             where d.active = 1
             order by a.code
            """
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            snapshot = _json(row.get("snapshot_json"))
            if str(snapshot.get("agent_publication_id") or "") != agent_publication_id:
                continue
            result.append(
                {
                    "code": str(row["code"]),
                    "name": str(row["name"]),
                    "environment": str(row["environment"]),
                    "application_publication_id": str(row["application_publication_id"]),
                    "href": f"/applications/{row['code']}",
                }
            )
        return result

    @staticmethod
    def _connection(row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "revision": int(row.get("revision") or 0)}

    @staticmethod
    def _revision(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "revision": int(row.get("revision") or 0),
            "config": _json(row.get("config_json")),
        }


def _json(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
