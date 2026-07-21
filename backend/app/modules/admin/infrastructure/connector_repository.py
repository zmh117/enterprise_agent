from __future__ import annotations

import json
from typing import Any

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound


class AdminConnectorRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select * from integration_connector
            where connector_type in (
              'dingtalk_enterprise_stream', 'dingtalk_callback',
              'dingtalk_enterprise_robot', 'dingtalk_webhook_robot'
            )
            order by name, id
            """
        )
        return [self._public(row) for row in rows]

    def get(self, connector_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from integration_connector where id = ?", (connector_id,)
        )
        if not row or str(row["connector_type"]) not in {
            "dingtalk_enterprise_stream",
            "dingtalk_callback",
            "dingtalk_enterprise_robot",
            "dingtalk_webhook_robot",
        }:
            raise NotFound(
                "Channel connector not found", safe_message="Channel connector not found"
            )
        return self._public(row)

    def save(self, payload: dict[str, Any], *, expected_revision: int) -> dict[str, Any]:
        connector_id = str(payload.get("id") or "")
        existing = self.get(connector_id) if connector_id else None
        timestamp = now_iso()
        values = (
            payload["connector_type"],
            payload["name"],
            payload.get("base_url") or "",
            1 if payload.get("enabled") else 0,
            json.dumps(payload.get("metadata") or {}, ensure_ascii=False, sort_keys=True),
            1 if payload.get("allow_ingress") else 0,
            1 if payload.get("allow_delivery") else 0,
            payload.get("secret_ref") or "",
            payload.get("endpoint_ref") or "",
            ",".join(payload.get("host_allowlist") or []),
        )
        if existing:
            if int(existing["revision"]) != expected_revision:
                raise _conflict()
            rows = self.database.execute(
                """
                update integration_connector
                set connector_type=?, name=?, base_url=?, enabled=?, metadata=?,
                    allow_ingress=?, allow_delivery=?, secret_ref=?, endpoint_ref=?,
                    host_allowlist=?, revision=revision+1, updated_at=?
                where id=? and revision=? returning id
                """,
                (*values, timestamp, connector_id, expected_revision),
            )
            if not rows:
                raise _conflict()
        else:
            if expected_revision != 0:
                raise _conflict()
            connector_id = new_id("connector")
            self.database.execute(
                """
                insert into integration_connector
                  (id, connector_type, name, base_url, enabled, metadata,
                   allow_ingress, allow_delivery, secret_ref, endpoint_ref,
                   host_allowlist, revision, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (connector_id, *values, timestamp, timestamp),
            )
        return self.get(connector_id)

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        try:
            metadata = json.loads(str(row.get("metadata") or "{}"))
        except ValueError:
            metadata = {}
        return {
            "id": row["id"],
            "connector_type": row["connector_type"],
            "name": row["name"],
            "base_url": row.get("base_url") or "",
            "enabled": bool(row.get("enabled")),
            "metadata": metadata if isinstance(metadata, dict) else {},
            "allow_ingress": bool(row.get("allow_ingress")),
            "allow_delivery": bool(row.get("allow_delivery")),
            "secret_ref": row.get("secret_ref") or "",
            "endpoint_ref": row.get("endpoint_ref") or "",
            "host_allowlist": [
                value.strip()
                for value in str(row.get("host_allowlist") or "").split(",")
                if value.strip()
            ],
            "revision": int(row.get("revision") or 1),
            "updated_at": row.get("updated_at"),
        }


def _conflict() -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "Channel connector revision conflict",
        safe_message="Channel connector changed; refresh and try again",
        error_code="revision_conflict",
    )
