from __future__ import annotations

import json
import secrets
from typing import Any

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


class WebhookTriggerRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_definitions(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "where d.status = 'enabled'"
        rows = self.database.execute(
            f"""
            select d.*, u.username as service_account_username,
                   u.display_name as service_account_display_name,
                   u.status as service_account_status,
                   p.revision as publication_revision,
                   p.agent_publication_id,
                   (select e.status from webhook_event e
                    where e.trigger_id = d.id
                    order by e.received_at desc, e.id desc limit 1) as recent_event_status,
                   (select e.received_at from webhook_event e
                    where e.trigger_id = d.id
                    order by e.received_at desc, e.id desc limit 1) as recent_event_at,
                   (select count(*) from webhook_event e
                    where e.trigger_id = d.id) as event_count,
                   (select count(*) from webhook_event e
                    where e.trigger_id = d.id
                      and e.status in ('REJECTED_AUTH', 'REJECTED')) as rejected_event_count,
                   (select count(*) from webhook_event e
                    where e.trigger_id = d.id
                      and e.status = 'DISPATCH_FAILED') as failed_event_count
            from webhook_trigger_definition d
            join app_user u on u.id = d.service_account_id
            left join webhook_trigger_publication p on p.id = d.current_publication_id
            {where}
            order by d.code
            """
        )
        return [self._definition(row) for row in rows]

    def get_definition(self, code: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select d.*, u.username as service_account_username,
                   u.display_name as service_account_display_name,
                   u.status as service_account_status,
                   u.account_type as service_account_type
            from webhook_trigger_definition d
            join app_user u on u.id = d.service_account_id
            where d.code = ?
            """,
            (code,),
        )
        if not row:
            raise NotFound("Webhook Trigger not found", safe_message="Webhook Trigger not found")
        return self._definition(row)

    def get_definition_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select d.*, u.username as service_account_username,
                   u.display_name as service_account_display_name,
                   u.status as service_account_status,
                   u.account_type as service_account_type
            from webhook_trigger_definition d
            join app_user u on u.id = d.service_account_id
            where d.public_id = ?
            """,
            (public_id,),
        )
        return self._definition(row) if row else None

    def get_enabled_grafana_by_connector(
        self, connector_id: str
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select d.*, u.username as service_account_username,
                   u.display_name as service_account_display_name,
                   u.status as service_account_status,
                   u.account_type as service_account_type
            from webhook_trigger_definition d
            join app_user u on u.id = d.service_account_id
            where d.connector_id = ? and d.trigger_type = 'grafana'
              and d.status = 'enabled'
            order by d.created_at, d.id limit 1
            """,
            (connector_id,),
        )
        return self._definition(row) if row else None

    def create_definition(
        self,
        *,
        code: str,
        name: str,
        trigger_type: str,
        connector_id: str,
        service_account_id: str,
        actor_id: str,
        public_id: str | None = None,
    ) -> dict[str, Any]:
        trigger_id = new_id("webhook_trigger")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into webhook_trigger_definition
              (id, code, name, trigger_type, public_id, connector_id,
               service_account_id, status, revision, created_by, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, 'disabled', 1, ?, ?, ?)
            """,
            (
                trigger_id,
                code,
                name,
                trigger_type,
                public_id or generate_public_id(),
                connector_id,
                service_account_id,
                actor_id,
                timestamp,
                timestamp,
            ),
        )
        return self.get_definition(code)

    def update_definition(
        self,
        *,
        code: str,
        expected_revision: int,
        name: str,
        connector_id: str,
        status: str,
    ) -> dict[str, Any]:
        rows = self.database.execute(
            """
            update webhook_trigger_definition
            set name = ?, connector_id = ?, status = ?, revision = revision + 1,
                updated_at = ?
            where code = ? and revision = ?
            returning id
            """,
            (name, connector_id, status, now_iso(), code, expected_revision),
        )
        self._require_changed(rows, code)
        return self.get_definition(code)

    def set_service_account_status(
        self,
        *,
        code: str,
        expected_revision: int,
        enabled: bool,
    ) -> dict[str, Any]:
        definition = self.get_definition(code)
        self.database.execute(
            """
            update app_user
            set status = ?, revision = revision + 1, updated_at = ?
            where id = ? and account_type = 'service'
            """,
            ("enabled" if enabled else "disabled", now_iso(), definition["service_account_id"]),
        )
        rows = self.database.execute(
            """
            update webhook_trigger_definition
            set revision = revision + 1, updated_at = ?
            where code = ? and revision = ? returning id
            """,
            (now_iso(), code, expected_revision),
        )
        self._require_changed(rows, code)
        return self.get_definition(code)

    def latest_revision(self, trigger_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select * from webhook_trigger_revision
            where trigger_id = ? order by revision desc limit 1
            """,
            (trigger_id,),
        )
        return self._revision(row) if row else None

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from webhook_trigger_revision where id = ?", (revision_id,)
        )
        if not row:
            raise NotFound("Webhook Trigger revision not found", safe_message="Revision not found")
        return self._revision(row)

    def save_draft(
        self,
        *,
        trigger_id: str,
        expected_revision: int,
        config: dict[str, Any],
        config_hash: str,
        actor_id: str,
    ) -> dict[str, Any]:
        latest = self.latest_revision(trigger_id)
        if latest and int(latest["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Webhook Trigger revision conflict",
                safe_message="Webhook Trigger draft changed; refresh and try again",
                error_code="revision_conflict",
            )
        revision_id = new_id("webhook_trigger_revision")
        revision = expected_revision + 1
        timestamp = now_iso()
        self.database.execute(
            """
            insert into webhook_trigger_revision
              (id, trigger_id, revision, status, schema_version, config_json,
               config_hash, validation_json, created_by, created_at, updated_at)
            values (?, ?, ?, 'draft', 1, ?, ?, '{}', ?, ?, ?)
            """,
            (
                revision_id,
                trigger_id,
                revision,
                json.dumps(config, ensure_ascii=False, sort_keys=True),
                config_hash,
                actor_id,
                timestamp,
                timestamp,
            ),
        )
        return self.get_revision(revision_id)

    def set_validation(
        self,
        revision_id: str,
        *,
        errors: list[dict[str, str]],
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        validation = {"valid": not errors, "errors": errors, **summary}
        self.database.execute(
            """
            update webhook_trigger_revision
            set status = ?, validation_json = ?, updated_at = ?
            where id = ? and status != 'published'
            """,
            (
                "validated" if not errors else "draft",
                json.dumps(validation, ensure_ascii=False, sort_keys=True),
                now_iso(),
                revision_id,
            ),
        )
        return self.get_revision(revision_id)

    def create_publication(
        self,
        *,
        trigger_id: str,
        revision_id: str,
        revision: int,
        snapshot: dict[str, Any],
        config_hash: str,
        agent_publication: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        publication_id = new_id("webhook_trigger_publication")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into webhook_trigger_publication
              (id, trigger_id, revision_id, revision, schema_version, snapshot_json,
               config_hash, agent_publication_id, agent_revision, agent_config_hash,
               status, published_by, published_at)
            values (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                publication_id,
                trigger_id,
                revision_id,
                revision,
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                config_hash,
                agent_publication["id"],
                agent_publication["revision"],
                agent_publication["config_hash"],
                actor_id,
                timestamp,
            ),
        )
        self.database.execute(
            """
            update webhook_trigger_revision
            set status = 'published', updated_at = ? where id = ?
            """,
            (timestamp, revision_id),
        )
        self.database.execute(
            """
            update webhook_trigger_definition
            set current_publication_id = ?, revision = revision + 1, updated_at = ?
            where id = ?
            """,
            (publication_id, timestamp, trigger_id),
        )
        return self.get_publication(publication_id)

    def get_publication(self, publication_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from webhook_trigger_publication where id = ?", (publication_id,)
        )
        if not row:
            raise NotFound("Webhook Trigger publication not found", safe_message="Publication not found")
        return self._publication(row)

    def current_publication(self, trigger_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select p.* from webhook_trigger_definition d
            join webhook_trigger_publication p on p.id = d.current_publication_id
            where d.id = ? and p.status = 'active'
            """,
            (trigger_id,),
        )
        if not row:
            raise NotFound(
                "Webhook Trigger has no publication",
                safe_message="Webhook Trigger is not published",
            )
        return self._publication(row)

    def list_publications(self, trigger_id: str) -> list[dict[str, Any]]:
        return [
            self._publication(row)
            for row in self.database.execute(
                """
                select * from webhook_trigger_publication
                where trigger_id = ? order by revision desc
                """,
                (trigger_id,),
            )
        ]

    def set_current_publication(
        self, *, code: str, publication_id: str, expected_revision: int
    ) -> dict[str, Any]:
        definition = self.get_definition(code)
        publication = self.get_publication(publication_id)
        if str(publication["trigger_id"]) != str(definition["id"]):
            raise NonRetryableExecutionError(
                "Publication belongs to another Trigger",
                safe_message="Publication does not belong to this Trigger",
            )
        rows = self.database.execute(
            """
            update webhook_trigger_definition
            set current_publication_id = ?, revision = revision + 1, updated_at = ?
            where code = ? and revision = ? returning id
            """,
            (publication_id, now_iso(), code, expected_revision),
        )
        self._require_changed(rows, code)
        return publication

    def rotate_public_id(self, *, code: str, expected_revision: int) -> dict[str, Any]:
        new_public_id = generate_public_id()
        rows = self.database.execute(
            """
            update webhook_trigger_definition
            set public_id = ?, revision = revision + 1, updated_at = ?
            where code = ? and revision = ? returning id
            """,
            (new_public_id, now_iso(), code, expected_revision),
        )
        self._require_changed(rows, code)
        return self.get_definition(code)

    def _require_changed(self, rows: list[dict[str, Any]], code: str) -> None:
        if rows:
            return
        if self.database.execute_one(
            "select id from webhook_trigger_definition where code = ?", (code,)
        ):
            raise NonRetryableExecutionError(
                "Webhook Trigger revision conflict",
                safe_message="Webhook Trigger changed; refresh and try again",
                error_code="revision_conflict",
            )
        raise NotFound("Webhook Trigger not found", safe_message="Webhook Trigger not found")

    def _definition(self, row: dict[str, Any]) -> dict[str, Any]:
        result = {**row, "revision": int(row["revision"])}
        for field in ("event_count", "rejected_event_count", "failed_event_count"):
            if field in result:
                result[field] = int(result[field] or 0)
        return result

    def _revision(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "revision": int(row["revision"]),
            "schema_version": int(row["schema_version"]),
            "config": _json(str(row.get("config_json") or "{}")),
            "validation": _json(str(row.get("validation_json") or "{}")),
        }

    def _publication(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "revision": int(row["revision"]),
            "schema_version": int(row["schema_version"]),
            "agent_revision": int(row["agent_revision"]),
            "snapshot": _json(str(row.get("snapshot_json") or "{}")),
        }


def generate_public_id() -> str:
    return f"wh_{secrets.token_urlsafe(32)}"


def _json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}
