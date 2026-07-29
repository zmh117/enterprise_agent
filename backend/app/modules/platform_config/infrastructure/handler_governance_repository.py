from __future__ import annotations

import json
from typing import Any

from app.modules.internal_tools.domain import HandlerDefinition
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound

from .repository import json_text, new_id, now_iso


class HandlerGovernanceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def reconcile_installation(
        self,
        definition: HandlerDefinition,
    ) -> dict[str, Any]:
        existing = self.find_installation(
            definition.handler_id,
            definition.handler_version,
        )
        timestamp = now_iso()
        if existing is None:
            self.database.execute(
                """
                insert into handler_installation
                  (handler_id, handler_version, implementation_digest,
                   display_name, description, input_schema_json,
                   output_schema_json, risk_level,
                   required_permissions_json, resource_slots_json,
                   visibility, installation_status, first_seen_at,
                   last_seen_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'INSTALLED', ?, ?)
                """,
                (
                    definition.handler_id,
                    definition.handler_version,
                    definition.implementation_digest,
                    definition.display_name,
                    definition.description,
                    json_text(definition.input_schema),
                    json_text(definition.output_schema),
                    definition.risk_level,
                    json_text(list(definition.required_permissions)),
                    json_text(
                        [
                            slot.public()
                            for slot in definition.resource_slots
                        ]
                    ),
                    definition.visibility,
                    timestamp,
                    timestamp,
                ),
            )
        elif (
            existing["implementation_digest"]
            != definition.implementation_digest
        ):
            self.database.execute(
                """
                update handler_installation
                   set installation_status = 'DRIFTED',
                       last_seen_at = ?
                 where handler_id = ? and handler_version = ?
                """,
                (
                    timestamp,
                    definition.handler_id,
                    definition.handler_version,
                ),
            )
        else:
            self.database.execute(
                """
                update handler_installation
                   set installation_status = 'INSTALLED',
                       last_seen_at = ?
                 where handler_id = ? and handler_version = ?
                """,
                (
                    timestamp,
                    definition.handler_id,
                    definition.handler_version,
                ),
            )
        return self.get_installation(
            definition.handler_id,
            definition.handler_version,
        )

    def mark_unseen_missing(
        self,
        installed_keys: set[tuple[str, str]],
    ) -> int:
        changed = 0
        for row in self.list_installations():
            key = (row["handler_id"], row["handler_version"])
            if key in installed_keys:
                continue
            if row["installation_status"] != "MISSING":
                self.database.execute(
                    """
                    update handler_installation
                       set installation_status = 'MISSING'
                     where handler_id = ? and handler_version = ?
                    """,
                    key,
                )
                changed += 1
        return changed

    def find_installation(
        self,
        handler_id: str,
        handler_version: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from handler_installation
             where handler_id = ? and handler_version = ?
            """,
            (handler_id, handler_version),
        )
        return self._installation(row) if row else None

    def get_installation(
        self,
        handler_id: str,
        handler_version: str,
    ) -> dict[str, Any]:
        result = self.find_installation(handler_id, handler_version)
        if result is None:
            raise NotFound(
                f"Handler installation not found: "
                f"{handler_id}@{handler_version}"
            )
        return result

    def list_installations(self) -> list[dict[str, Any]]:
        return [
            self._installation(row)
            for row in self.database.execute(
                """
                select * from handler_installation
                 order by handler_id, handler_version
                """
            )
        ]

    def publish(
        self,
        *,
        handler_id: str,
        handler_version: str,
        actor_id: str,
    ) -> dict[str, Any]:
        installation = self.get_installation(
            handler_id,
            handler_version,
        )
        if installation["installation_status"] != "INSTALLED":
            raise NonRetryableExecutionError(
                "Handler installation is not healthy",
                safe_message="Handler 未安装或代码版本已漂移",
                error_code="handler_installation_unavailable",
            )
        existing = self.find_publication(
            handler_id,
            handler_version,
        )
        if existing is not None:
            raise NonRetryableExecutionError(
                "Handler version was already governed",
                safe_message="该 Handler 版本已发布或已停用，不能重复发布",
                error_code="handler_publication_immutable",
            )
        publication_id = new_id("handler_publication")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into handler_publication
              (id, handler_id, handler_version, status, revision,
               published_by, published_at)
            values (?, ?, ?, 'PUBLISHED', 1, ?, ?)
            """,
            (
                publication_id,
                handler_id,
                handler_version,
                actor_id,
                timestamp,
            ),
        )
        return self.get_publication(publication_id)

    def find_publication(
        self,
        handler_id: str,
        handler_version: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from handler_publication
             where handler_id = ? and handler_version = ?
            """,
            (handler_id, handler_version),
        )
        return dict(row) if row else None

    def get_publication(self, publication_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from handler_publication where id = ?",
            (publication_id,),
        )
        if not row:
            raise NotFound(
                f"Handler publication not found: {publication_id}"
            )
        return dict(row)

    def list_publications(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.database.execute(
                """
                select * from handler_publication
                 order by handler_id, handler_version
                """
            )
        ]

    def set_publication_status(
        self,
        *,
        publication_id: str,
        status: str,
        actor_id: str,
    ) -> dict[str, Any]:
        before = self.get_publication(publication_id)
        normalized = status.upper()
        if normalized not in {"DISABLED", "ARCHIVED"}:
            raise NonRetryableExecutionError(
                "Handler publication cannot be re-enabled or modified",
                safe_message="Handler 发布后只能禁用或归档",
                error_code="handler_publication_immutable",
            )
        if before["status"] == "ARCHIVED" or (
            before["status"] == "DISABLED"
            and normalized == "DISABLED"
        ):
            raise NonRetryableExecutionError(
                "Handler publication status cannot move backwards",
                safe_message="Handler 发布状态不能回退或重复变更",
                error_code="handler_publication_immutable",
            )
        timestamp = now_iso()
        field_actor = (
            "disabled_by"
            if normalized == "DISABLED"
            else "archived_by"
        )
        field_at = (
            "disabled_at"
            if normalized == "DISABLED"
            else "archived_at"
        )
        self.database.execute(
            f"""
            update handler_publication
               set status = ?,
                   revision = revision + 1,
                   {field_actor} = ?,
                   {field_at} = ?
             where id = ?
            """,
            (normalized, actor_id, timestamp, publication_id),
        )
        return self.get_publication(publication_id)

    @staticmethod
    def _installation(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for source, target in (
            ("input_schema_json", "input_schema"),
            ("output_schema_json", "output_schema"),
            ("required_permissions_json", "required_permissions"),
            ("resource_slots_json", "resource_slots"),
        ):
            result[target] = json.loads(result.pop(source))
        return result
