from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError, NotFound


class ManagedChannelRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_dingtalk_connectors(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        enabled = "" if include_disabled else "and c.enabled = 1"
        rows = self.database.execute(
            f"""
            select c.*, e.name as dingtalk_enterprise_name,
                   e.corp_id as dingtalk_enterprise_corp_id,
                   e.status as dingtalk_enterprise_status,
                   e.verified_at as dingtalk_enterprise_verified_at,
                   e.revision as dingtalk_enterprise_revision,
                   r.runtime_id, r.runtime_status, r.loaded_revision,
                   r.connected, r.registered, r.connected_at, r.disconnected_at,
                   r.last_message_at, r.last_heartbeat_at, r.last_error_code,
                   r.last_error_summary
              from integration_connector c
              left join dingtalk_enterprise e on e.id = c.dingtalk_enterprise_id
              left join channel_connector_runtime r on r.connector_id = c.id
             where c.connector_type = 'dingtalk_enterprise_stream'
               and c.deleted = 0 {enabled}
             order by c.name, c.id
            """
        )
        return [self._connector(row) for row in rows]

    def list_webhook_connector_options(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select id, connector_type, name, revision
              from integration_connector
             where enabled = 1
               and allow_ingress = 1
               and deleted = 0
               and connector_type != 'dingtalk_enterprise_stream'
             order by name, id
            """
        )
        return [
            {
                "id": str(row["id"]),
                "name": str(row["name"]),
                "connector_type": str(row["connector_type"]),
                "revision": int(row.get("revision") or 1),
            }
            for row in rows
        ]

    def get_connector(self, connector_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select c.*, e.name as dingtalk_enterprise_name,
                   e.corp_id as dingtalk_enterprise_corp_id,
                   e.status as dingtalk_enterprise_status,
                   e.verified_at as dingtalk_enterprise_verified_at,
                   e.revision as dingtalk_enterprise_revision,
                   r.runtime_id, r.runtime_status, r.loaded_revision,
                   r.connected, r.registered, r.connected_at, r.disconnected_at,
                   r.last_message_at, r.last_heartbeat_at, r.last_error_code,
                   r.last_error_summary
              from integration_connector c
              left join dingtalk_enterprise e on e.id = c.dingtalk_enterprise_id
              left join channel_connector_runtime r on r.connector_id = c.id
             where c.id = ? and c.connector_type = 'dingtalk_enterprise_stream'
               and c.deleted = 0
            """,
            (connector_id,),
        )
        if row is None:
            raise NotFound("Managed channel not found", safe_message="未找到渠道")
        return self._connector(row)

    def find_by_client_id(self, client_id: str) -> dict[str, Any] | None:
        rows = self.list_dingtalk_connectors()
        return next(
            (
                item
                for item in rows
                if str(item.get("metadata", {}).get("client_id") or "") == client_id
            ),
            None,
        )

    def create_dingtalk_connector(
        self,
        *,
        name: str,
        secret_ref: str,
        metadata: dict[str, Any],
        dingtalk_enterprise_id: str,
        enabled: bool,
    ) -> dict[str, Any]:
        connector_id = new_id("connector")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into integration_connector
              (id, connector_type, name, base_url, enabled, metadata,
               allow_ingress, allow_delivery, secret_ref, endpoint_ref,
               host_allowlist, revision, created_at, updated_at, deleted,
               dingtalk_enterprise_id)
            values (?, 'dingtalk_enterprise_stream', ?, '', ?, ?, 1, 0, ?, '', '',
                    1, ?, ?, 0, ?)
            """,
            (
                connector_id,
                name,
                1 if enabled else 0,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                secret_ref,
                timestamp,
                timestamp,
                dingtalk_enterprise_id,
            ),
        )
        return self.get_connector(connector_id)

    def update_dingtalk_connector(
        self,
        *,
        connector_id: str,
        expected_revision: int,
        name: str,
        metadata: dict[str, Any],
        dingtalk_enterprise_id: str,
        secret_ref: str,
        enabled: bool,
        force_revision: bool = False,
    ) -> dict[str, Any]:
        current = self.get_connector(connector_id)
        if int(current["revision"]) != expected_revision:
            raise _revision_conflict()
        rows = self.database.execute(
            """
            update integration_connector
               set name = ?, metadata = ?, dingtalk_enterprise_id = ?,
                   secret_ref = ?, enabled = ?,
                   revision = revision + 1, updated_at = ?
             where id = ? and revision = ? and deleted = 0
             returning id
            """,
            (
                name,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                dingtalk_enterprise_id,
                secret_ref,
                1 if enabled else 0,
                now_iso(),
                connector_id,
                expected_revision,
            ),
        )
        if not rows:
            raise _revision_conflict()
        if force_revision:
            self.database.execute(
                """
                update channel_connector_runtime
                   set runtime_status = 'RECONNECTING', updated_at = ?
                 where connector_id = ?
                """,
                (now_iso(), connector_id),
            )
        return self.get_connector(connector_id)

    def list_dingtalk_enterprises(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select e.*,
                   count(c.id) as connector_count,
                   coalesce(sum(case when c.enabled = 1 and c.deleted = 0
                                     then 1 else 0 end), 0) as enabled_connector_count
              from dingtalk_enterprise e
              left join integration_connector c
                on c.dingtalk_enterprise_id = e.id
               and c.connector_type = 'dingtalk_enterprise_stream'
             group by e.id, e.name, e.corp_id, e.status,
                      e.verification_event_id, e.verified_at, e.revision,
                      e.created_by, e.created_at, e.updated_at
             order by e.name, e.id
            """
        )
        return [self._enterprise(row) for row in rows]

    def get_dingtalk_enterprise(self, enterprise_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select e.*,
                   count(c.id) as connector_count,
                   coalesce(sum(case when c.enabled = 1 and c.deleted = 0
                                     then 1 else 0 end), 0) as enabled_connector_count
              from dingtalk_enterprise e
              left join integration_connector c
                on c.dingtalk_enterprise_id = e.id
               and c.connector_type = 'dingtalk_enterprise_stream'
             where e.id = ?
             group by e.id, e.name, e.corp_id, e.status,
                      e.verification_event_id, e.verified_at, e.revision,
                      e.created_by, e.created_at, e.updated_at
            """,
            (enterprise_id,),
        )
        if row is None:
            raise NotFound(
                "DingTalk enterprise not found",
                safe_message="未找到钉钉企业",
            )
        return self._enterprise(row)

    def find_dingtalk_enterprise_by_corp_id(self, corp_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            "select * from dingtalk_enterprise where corp_id = ?",
            (corp_id,),
        )
        return self._enterprise(row) if row else None

    def create_dingtalk_enterprise(
        self,
        *,
        name: str,
        actor_id: str,
    ) -> dict[str, Any]:
        enterprise_id = new_id("dingtalk_enterprise")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into dingtalk_enterprise
              (id, name, corp_id, status, verification_event_id, verified_at,
               revision, created_by, created_at, updated_at)
            values (?, ?, null, 'PENDING_VERIFICATION', '', null,
                    1, ?, ?, ?)
            """,
            (enterprise_id, name, actor_id, timestamp, timestamp),
        )
        return self.get_dingtalk_enterprise(enterprise_id)

    def rename_dingtalk_enterprise(
        self,
        enterprise_id: str,
        *,
        name: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        rows = self.database.execute(
            """
            update dingtalk_enterprise
               set name = ?, revision = revision + 1, updated_at = ?
             where id = ? and revision = ?
             returning id
            """,
            (name, now_iso(), enterprise_id, expected_revision),
        )
        if not rows:
            self.get_dingtalk_enterprise(enterprise_id)
            raise _enterprise_revision_conflict()
        return self.get_dingtalk_enterprise(enterprise_id)

    def set_dingtalk_enterprise_status(
        self,
        enterprise_id: str,
        *,
        status: str,
        expected_revision: int,
        clear_verification: bool = False,
    ) -> dict[str, Any]:
        rows = self.database.execute(
            """
            update dingtalk_enterprise
               set status = ?,
                   verified_at = case when ? = 1 then null else verified_at end,
                   verification_event_id = case when ? = 1 then ''
                                                else verification_event_id end,
                   revision = revision + 1,
                   updated_at = ?
             where id = ? and revision = ?
             returning id
            """,
            (
                status,
                1 if clear_verification else 0,
                1 if clear_verification else 0,
                now_iso(),
                enterprise_id,
                expected_revision,
            ),
        )
        if not rows:
            self.get_dingtalk_enterprise(enterprise_id)
            raise _enterprise_revision_conflict()
        return self.get_dingtalk_enterprise(enterprise_id)

    def verify_dingtalk_enterprise(
        self,
        enterprise_id: str,
        *,
        corp_id: str,
        source_event_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        rows = self.database.execute(
            """
            update dingtalk_enterprise
               set corp_id = coalesce(corp_id, ?),
                   status = 'ACTIVE',
                   verification_event_id = ?,
                   verified_at = ?,
                   revision = revision + 1,
                   updated_at = ?
             where id = ? and revision = ?
               and status = 'PENDING_VERIFICATION'
               and (corp_id is null or corp_id = ?)
             returning id
            """,
            (
                corp_id,
                source_event_id,
                timestamp,
                timestamp,
                enterprise_id,
                expected_revision,
                corp_id,
            ),
        )
        if not rows:
            current = self.get_dingtalk_enterprise(enterprise_id)
            if (
                current["status"] == "ACTIVE"
                and current["verification_event_id"] == source_event_id
                and current["corp_id"] == corp_id
            ):
                return current
            raise _enterprise_revision_conflict()
        return self.get_dingtalk_enterprise(enterprise_id)

    def dingtalk_enterprise_impacts(self, enterprise_id: str) -> list[dict[str, Any]]:
        self.get_dingtalk_enterprise(enterprise_id)
        rows = self.database.execute(
            """
            select c.id as connector_id, c.name as connector_name,
                   c.enabled, c.deleted,
                   a.id as application_id, a.name as application_name,
                   r.revision as application_revision
              from integration_connector c
              left join business_application_revision_trigger t
                on t.connector_id = c.id and t.enabled = 1
              left join business_application_revision r on r.id = t.revision_id
              left join business_application a on a.id = r.application_id
             where c.dingtalk_enterprise_id = ?
               and c.connector_type = 'dingtalk_enterprise_stream'
             order by c.name, a.name, r.revision
            """,
            (enterprise_id,),
        )
        return [
            {
                "connector_id": str(row["connector_id"]),
                "connector_name": str(row["connector_name"]),
                "connector_enabled": bool(row["enabled"]) and not bool(row["deleted"]),
                "application_id": str(row.get("application_id") or ""),
                "application_name": str(row.get("application_name") or ""),
                "application_revision": row.get("application_revision"),
            }
            for row in rows
        ]

    def soft_delete(self, connector_id: str, *, expected_revision: int) -> None:
        current = self.get_connector(connector_id)
        if int(current["revision"]) != expected_revision:
            raise _revision_conflict()
        rows = self.database.execute(
            """
            update integration_connector
               set enabled = 0, deleted = 1, revision = revision + 1, updated_at = ?
             where id = ? and revision = ? and deleted = 0 returning id
            """,
            (now_iso(), connector_id, expected_revision),
        )
        if not rows:
            raise _revision_conflict()

    def connector_references(self, connector_id: str) -> list[dict[str, Any]]:
        return self.database.execute(
            """
            select a.code as application_code, a.name as application_name,
                   r.revision as application_revision, t.trigger_type
             from business_application_revision_trigger t
              join business_application_revision r on r.id = t.revision_id
              join business_application a on a.id = r.application_id
             where t.connector_id = ? and t.enabled = 1
               and r.status in ('draft', 'validated', 'published')
             order by a.code, r.revision
            """,
            (connector_id,),
        )

    def acquire_lease(
        self, *, lease_name: str, runtime_id: str, ttl_seconds: int
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        expires_at = (now + timedelta(seconds=max(ttl_seconds, 5))).isoformat()
        token = secrets.token_urlsafe(24)
        with self.database.unit_of_work():
            current = self.database.execute_one(
                "select * from channel_runtime_lease where lease_name = ?", (lease_name,)
            )
            if current and str(current["expires_at"]) > now.isoformat():
                return None
            if current:
                self.database.execute(
                    """
                    update channel_runtime_lease
                       set runtime_id = ?, lease_token = ?, expires_at = ?, updated_at = ?
                     where lease_name = ?
                    """,
                    (runtime_id, token, expires_at, now.isoformat(), lease_name),
                )
            else:
                self.database.execute(
                    """
                    insert into channel_runtime_lease
                      (lease_name, runtime_id, lease_token, expires_at, updated_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (lease_name, runtime_id, token, expires_at, now.isoformat()),
                )
        return {
            "lease_name": lease_name,
            "runtime_id": runtime_id,
            "lease_token": token,
            "expires_at": expires_at,
        }

    def renew_lease(
        self,
        *,
        lease_name: str,
        runtime_id: str,
        lease_token: str,
        ttl_seconds: int,
    ) -> dict[str, Any] | None:
        expires_at = (datetime.now(UTC) + timedelta(seconds=max(ttl_seconds, 5))).isoformat()
        rows = self.database.execute(
            """
            update channel_runtime_lease
               set expires_at = ?, updated_at = ?
             where lease_name = ? and runtime_id = ? and lease_token = ?
             returning *
            """,
            (expires_at, now_iso(), lease_name, runtime_id, lease_token),
        )
        return rows[0] if rows else None

    def release_lease(self, *, lease_name: str, runtime_id: str, lease_token: str) -> bool:
        rows = self.database.execute(
            """
            delete from channel_runtime_lease
             where lease_name = ? and runtime_id = ? and lease_token = ?
             returning lease_name
            """,
            (lease_name, runtime_id, lease_token),
        )
        return bool(rows)

    def require_lease(self, *, runtime_id: str, lease_token: str) -> None:
        row = self.database.execute_one(
            """
            select lease_name from channel_runtime_lease
             where runtime_id = ? and lease_token = ? and expires_at > ?
            """,
            (runtime_id, lease_token, now_iso()),
        )
        if row is None:
            raise NonRetryableExecutionError(
                "Runtime lease is missing or expired",
                safe_message="Runtime 租约无效或已过期",
                error_code="runtime_lease_invalid",
            )

    def upsert_runtime_state(
        self,
        *,
        connector_id: str,
        runtime_id: str,
        runtime_status: str,
        loaded_revision: int,
        connected: bool,
        registered: bool,
        error_code: str,
        error_summary: str,
        message_received: bool = False,
    ) -> None:
        timestamp = now_iso()
        self.database.execute(
            """
            insert into channel_connector_runtime
              (connector_id, runtime_id, runtime_status, loaded_revision,
               connected, registered, connected_at, disconnected_at,
               last_message_at, last_heartbeat_at, last_error_code,
               last_error_summary, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(connector_id) do update set
              runtime_id = excluded.runtime_id,
              runtime_status = excluded.runtime_status,
              loaded_revision = excluded.loaded_revision,
              connected = excluded.connected,
              registered = excluded.registered,
              connected_at = case
                when excluded.connected = 1 then
                  coalesce(channel_connector_runtime.connected_at, excluded.connected_at)
                else channel_connector_runtime.connected_at end,
              disconnected_at = case
                when excluded.connected = 0 then excluded.disconnected_at
                else channel_connector_runtime.disconnected_at end,
              last_message_at = coalesce(excluded.last_message_at,
                                         channel_connector_runtime.last_message_at),
              last_heartbeat_at = excluded.last_heartbeat_at,
              last_error_code = excluded.last_error_code,
              last_error_summary = excluded.last_error_summary,
              updated_at = excluded.updated_at
            """,
            (
                connector_id,
                runtime_id,
                runtime_status,
                loaded_revision,
                1 if connected else 0,
                1 if registered else 0,
                timestamp if connected else None,
                None if connected else timestamp,
                timestamp if message_received else None,
                timestamp,
                error_code[:120],
                error_summary[:500],
                timestamp,
            ),
        )

    def receive_event(
        self,
        *,
        source_type: str,
        connector_id: str,
        external_event_id: str,
        correlation_id: str,
        payload_hash: str,
        request_bytes: int,
        safe_summary: dict[str, Any],
        normalized_event: dict[str, Any],
        reply_credential_ciphertext: str,
    ) -> tuple[dict[str, Any], bool]:
        event_id = new_id("channel_event")
        timestamp = now_iso()
        with self.database.unit_of_work():
            rows = self.database.execute(
                """
                insert into channel_ingress_event
                  (id, source_type, connector_id, external_event_id, correlation_id,
                   payload_hash, safe_summary_json, normalized_event_json,
                   reply_credential_ciphertext, status, request_bytes, received_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACCEPTED', ?, ?)
                on conflict(connector_id, external_event_id) do nothing
                returning id
                """,
                (
                    event_id,
                    source_type,
                    connector_id,
                    external_event_id,
                    correlation_id,
                    payload_hash,
                    json.dumps(safe_summary, ensure_ascii=False, sort_keys=True),
                    json.dumps(normalized_event, ensure_ascii=False, sort_keys=True),
                    reply_credential_ciphertext,
                    request_bytes,
                    timestamp,
                ),
            )
            created = bool(rows)
            if not created:
                row = self.database.execute_one(
                    """
                    select id from channel_ingress_event
                     where connector_id = ? and external_event_id = ?
                    """,
                    (connector_id, external_event_id),
                )
                if row is None:
                    raise RuntimeError("Channel event dedup record could not be resolved")
                event_id = str(row["id"])
            else:
                self.database.execute(
                    """
                    insert into channel_ingress_outbox
                      (id, channel_event_id, correlation_id, status, attempt_count,
                       next_attempt_at, created_at, updated_at)
                    values (?, ?, ?, 'pending', 0, ?, ?, ?)
                    """,
                    (
                        new_id("channel_outbox"),
                        event_id,
                        correlation_id,
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
        return self.get_event(event_id), created

    def get_event(self, event_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from channel_ingress_event where id = ?", (event_id,)
        )
        if row is None:
            raise NotFound("Channel event not found", safe_message="未找到渠道事件")
        value = dict(row)
        value["safe_summary"] = _json(value.pop("safe_summary_json", "{}"))
        value["normalized_event"] = _json(value.pop("normalized_event_json", "{}"))
        return value

    def find_event_by_external_id(
        self,
        *,
        source_type: str,
        connector_id: str,
        external_event_id: str,
    ) -> dict[str, Any] | None:
        row = self.database.execute_one(
            """
            select id
              from channel_ingress_event
             where source_type = ? and connector_id = ? and external_event_id = ?
            """,
            (source_type, connector_id, external_event_id),
        )
        return self.get_event(str(row["id"])) if row is not None else None

    def claim_outbox(self, *, worker_id: str) -> dict[str, Any] | None:
        now = now_iso()
        rows = self.database.execute(
            """
            update channel_ingress_outbox
               set status = 'publishing', claimed_by = ?, claimed_at = ?,
                   attempt_count = attempt_count + 1, updated_at = ?
             where id = (
               select id from channel_ingress_outbox
                where status = 'pending' and next_attempt_at <= ?
                order by next_attempt_at, created_at limit 1
             ) and status = 'pending'
             returning *
            """,
            (worker_id, now, now, now),
        )
        return rows[0] if rows else None

    def recover_stale_claims(self, *, stale_seconds: int = 300) -> int:
        before = (datetime.now(UTC) - timedelta(seconds=stale_seconds)).isoformat()
        rows = self.database.execute(
            """
            update channel_ingress_outbox
               set status = 'pending', claimed_by = '', claimed_at = null, updated_at = ?
             where status = 'publishing' and claimed_at < ?
             returning id
            """,
            (now_iso(), before),
        )
        return len(rows)

    def mark_outbox_published(self, outbox_id: str) -> None:
        timestamp = now_iso()
        self.database.execute(
            """
            update channel_ingress_outbox
               set status = 'published', published_at = ?, claimed_by = '',
                   claimed_at = null, last_error_summary = '', updated_at = ?
             where id = ?
            """,
            (timestamp, timestamp, outbox_id),
        )
        self.database.execute(
            """
            update channel_ingress_event set status = 'DISPATCH_PENDING'
             where id = (
               select channel_event_id from channel_ingress_outbox where id = ?
             ) and status = 'ACCEPTED'
            """,
            (outbox_id,),
        )

    def mark_outbox_failed(
        self, outbox_id: str, *, error_summary: str, max_attempts: int, base_delay: int
    ) -> dict[str, Any]:
        current = self.database.execute_one(
            "select * from channel_ingress_outbox where id = ?", (outbox_id,)
        )
        attempts = int(current["attempt_count"] if current else max_attempts)
        dead = attempts >= max_attempts
        next_attempt = datetime.now(UTC) + timedelta(
            seconds=max(base_delay, 1) * (2 ** max(attempts - 1, 0))
        )
        self.database.execute(
            """
            update channel_ingress_outbox
               set status = ?, next_attempt_at = ?, claimed_by = '', claimed_at = null,
                   last_error_summary = ?, updated_at = ?
             where id = ?
            """,
            (
                "dead" if dead else "pending",
                next_attempt.isoformat(),
                error_summary[:500],
                now_iso(),
                outbox_id,
            ),
        )
        return (
            self.database.execute_one(
                "select * from channel_ingress_outbox where id = ?", (outbox_id,)
            )
            or {}
        )

    def attach_job(self, event_id: str, job_id: str) -> None:
        self.database.execute(
            """
            update channel_ingress_event
               set job_id = ?, status = 'JOB_CREATED', dispatched_at = ?, completed_at = ?
             where id = ? and job_id is null
            """,
            (job_id, now_iso(), now_iso(), event_id),
        )

    def mark_event_attachments_staged(self, event_id: str) -> None:
        self.database.execute(
            """
            update channel_ingress_event
               set status = 'ATTACHMENTS_STAGED', dispatched_at = ?, completed_at = ?
             where id = ? and job_id is null
               and status in ('ACCEPTED', 'DISPATCH_PENDING', 'DISPATCHING')
            """,
            (now_iso(), now_iso(), event_id),
        )

    def mark_event_rejected(self, event_id: str, *, error_code: str, error_summary: str) -> None:
        self.database.execute(
            """
            update channel_ingress_event
               set status = 'REJECTED', error_code = ?, error_summary = ?,
                   completed_at = ?
             where id = ? and job_id is null
            """,
            (error_code[:120], error_summary[:500], now_iso(), event_id),
        )

    @staticmethod
    def _connector(row: dict[str, Any]) -> dict[str, Any]:
        value = dict(row)
        value["metadata"] = _json(value.get("metadata") or "{}")
        value["enabled"] = bool(value.get("enabled"))
        value["allow_ingress"] = bool(value.get("allow_ingress"))
        value["allow_delivery"] = bool(value.get("allow_delivery"))
        value["connected"] = bool(value.get("connected"))
        value["registered"] = bool(value.get("registered"))
        return value

    @staticmethod
    def _enterprise(row: dict[str, Any]) -> dict[str, Any]:
        value = dict(row)
        value["corp_id"] = str(value.get("corp_id") or "")
        value["verification_event_id"] = str(value.get("verification_event_id") or "")
        value["connector_count"] = int(value.get("connector_count") or 0)
        value["enabled_connector_count"] = int(value.get("enabled_connector_count") or 0)
        return value


def _json(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _revision_conflict() -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "Managed channel revision conflict",
        safe_message="渠道配置已发生变化，请刷新后重试",
        error_code="revision_conflict",
    )


def _enterprise_revision_conflict() -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "DingTalk enterprise revision conflict",
        safe_message="钉钉企业信息已发生变化，请刷新后重试",
        error_code="revision_conflict",
    )
