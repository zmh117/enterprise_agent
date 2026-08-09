from __future__ import annotations

import json
from typing import Any

from app.shared.database import Database
from app.shared.exceptions import NotFound


class BusinessApplicationRepository:
    """Read-only repository for immutable channel routing publications."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def get_by_code(self, code: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from business_application where code = ?", (code,)
        )
        if row is None:
            raise NotFound(
                f"Business Application not found: {code}",
                safe_message="未找到业务应用",
            )
        return self._application(row)

    def get_by_id(self, application_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from business_application where id = ?", (application_id,)
        )
        if row is None:
            raise NotFound(
                f"Business Application not found: {application_id}",
                safe_message="未找到业务应用",
            )
        return self._application(row)

    def get_publication(self, publication_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from business_application_publication where id = ?",
            (publication_id,),
        )
        if row is None:
            raise NotFound(
                f"Business Application publication not found: {publication_id}",
                safe_message="未找到业务应用发布版本",
            )
        return {
            **row,
            "revision": int(row["revision"]),
            "schema_version": int(row["schema_version"]),
            "snapshot": self._json(row.get("snapshot_json")),
        }

    def get_deployment(
        self,
        application_id: str,
        environment: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from business_application_deployment
             where application_id = ? and environment = ?
            """,
            (application_id, environment),
        )
        if row is None:
            return None
        return {
            **row,
            "active": bool(row.get("active")),
            "revision": int(row.get("revision") or 0),
        }

    def find_route(
        self,
        *,
        environment: str,
        trigger_type: str,
        connector_id: str,
        normalized_routing_key: str,
    ) -> dict[str, Any] | None:
        return self.database.execute_one(
            """
            select * from business_application_active_route
             where environment = ? and trigger_type = ? and connector_id = ?
               and normalized_routing_key = ?
            """,
            (environment, trigger_type, connector_id, normalized_routing_key),
        )

    @staticmethod
    def _application(row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "revision": int(row.get("revision") or 0)}

    @staticmethod
    def _json(raw: object) -> dict[str, Any]:
        try:
            value = json.loads(str(raw or "{}"))
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}
