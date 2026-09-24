from __future__ import annotations

import json
from typing import Any

from app.modules.job.domain.agent_job import MessageAttachment
from app.modules.job.infrastructure.persistence_values import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound


class AttachmentRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add_attachment(
        self,
        *,
        message_id: str,
        job_id: str | None,
        task_workspace_id: str = "",
        ordinal: int,
        media_type: str,
        file_name: str,
        declared_mime: str = "",
        declared_size: int | None = None,
        credential_ciphertext: str = "",
        credential_type: str = "",
        credential_expires_at: str | None = None,
    ) -> MessageAttachment:
        attachment, _created = self.add_or_get_attachment(
            message_id=message_id,
            job_id=job_id,
            task_workspace_id=task_workspace_id,
            ordinal=ordinal,
            media_type=media_type,
            file_name=file_name,
            declared_mime=declared_mime,
            declared_size=declared_size,
            credential_ciphertext=credential_ciphertext,
            credential_type=credential_type,
            credential_expires_at=credential_expires_at,
        )
        return attachment

    def add_or_get_attachment(
        self,
        *,
        message_id: str,
        job_id: str | None,
        task_workspace_id: str = "",
        ordinal: int,
        media_type: str,
        file_name: str,
        declared_mime: str = "",
        declared_size: int | None = None,
        credential_ciphertext: str = "",
        credential_type: str = "",
        credential_expires_at: str | None = None,
    ) -> tuple[MessageAttachment, bool]:
        existing = self.database.execute_one(
            "select * from message_attachment where message_id = ? and ordinal = ?",
            (message_id, ordinal),
        )
        if existing:
            return self._attachment_from_row(existing), False
        attachment_id = new_id("attachment")
        timestamp = now_iso()
        inserted = self.database.execute(
            """
            insert into message_attachment
              (id, message_id, job_id, ordinal, media_type, file_name, declared_mime,
               declared_size, status, source_credential_ciphertext, source_credential_type,
               source_credential_expires_at, task_workspace_id, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?)
            on conflict(message_id, ordinal) do nothing
            returning *
            """,
            (
                attachment_id,
                message_id,
                job_id,
                ordinal,
                media_type,
                file_name,
                declared_mime,
                declared_size,
                credential_ciphertext,
                credential_type,
                credential_expires_at,
                task_workspace_id or None,
                timestamp,
                timestamp,
            ),
        )
        if inserted:
            return self._attachment_from_row(inserted[0]), True
        existing = self.database.execute_one(
            "select * from message_attachment where message_id = ? and ordinal = ?",
            (message_id, ordinal),
        )
        if existing is None:
            raise RuntimeError("Attachment idempotency lookup failed")
        return self._attachment_from_row(existing), False

    def increment_attachment_retry(self, attachment_id: str) -> int:
        row = self.database.execute_one(
            """
            update message_attachment set retry_count = retry_count + 1, updated_at = ?
            where id = ? returning retry_count
            """,
            (now_iso(), attachment_id),
        )
        return int(row["retry_count"]) if row else 0

    def get_attachment(self, attachment_id: str) -> MessageAttachment:
        row = self.database.execute_one(
            "select * from message_attachment where id = ?", (attachment_id,)
        )
        if not row:
            raise NotFound(f"Message attachment not found: {attachment_id}")
        return self._attachment_from_row(row)

    def get_attachment_secret(self, attachment_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select source_credential_ciphertext, source_credential_type,
                   source_credential_expires_at
            from message_attachment where id = ?
            """,
            (attachment_id,),
        )
        if not row:
            raise NotFound(f"Message attachment not found: {attachment_id}")
        return row

    def list_attachments(self, job_id: str) -> list[MessageAttachment]:
        rows = self.database.execute(
            """
            select a.*
              from message_attachment a
              join agent_message m on m.id = a.message_id
             where a.job_id = ?
             order by m.sequence_no, a.ordinal, a.id
            """,
            (job_id,),
        )
        return [self._attachment_from_row(row) for row in rows]

    def list_waiting_job_ids_for_attachment(self, attachment_id: str) -> list[str]:
        """Waiting jobs whose frozen file dependencies name this attachment."""

        if not attachment_id:
            return []
        rows = self.database.execute(
            """
            select id, business_application_route_decision_json
              from agent_job
             where status = 'WAITING_INPUT'
             order by id
            """
        )
        matched: list[str] = []
        for row in rows:
            raw = row.get("business_application_route_decision_json") or "{}"
            try:
                decision = json.loads(str(raw))
            except json.JSONDecodeError:
                continue
            dependencies = decision.get("file_turn_dependencies") if isinstance(decision, dict) else None
            if not isinstance(dependencies, list):
                continue
            if any(
                isinstance(item, dict) and str(item.get("attachment_id") or "") == attachment_id
                for item in dependencies
            ):
                matched.append(str(row["id"]))
        return matched

    def attachment_session_context(self, attachment_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            """
            select m.session_id, s.source_connector_id, s.bot_identity,
                   s.source_channel, m.sender_id,
                   coalesce(a.task_workspace_id, j.task_workspace_id) as task_workspace_id,
                   coalesce(j.internal_user_id, m.sender_id, s.requester_id) as internal_user_id
              from message_attachment a
              join agent_message m on m.id = a.message_id
              join agent_session s on s.id = m.session_id
              left join agent_job j on j.id = a.job_id
             where a.id = ?
            """,
            (attachment_id,),
        )
        if row is None:
            raise NotFound(f"Message attachment not found: {attachment_id}")
        return row

    def claim_staged_attachments(
        self,
        *,
        session_id: str,
        task_workspace_id: str,
        job_id: str,
        attachment_ids: tuple[str, ...] | list[str] = (),
    ) -> list[MessageAttachment]:
        ids = [item for item in attachment_ids if item and not str(item).startswith("current:")]
        if not ids:
            return []
        timestamp = now_iso()
        placeholders = ", ".join("?" for _ in ids)
        self.database.execute(
            f"""
            update message_attachment
               set job_id = ?, claimed_at = ?, updated_at = ?
             where job_id is null and task_workspace_id = ?
               and id in ({placeholders})
               and message_id in (
                 select id from agent_message where session_id = ?
               )
            """,
            (job_id, timestamp, timestamp, task_workspace_id, *ids, session_id),
        )
        return self.list_attachments(job_id)

    def list_file_turn_candidate_rows(
        self,
        *,
        session_id: str,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        if not session_id or not workspace_id:
            return []
        attachments = self.database.execute(
            """
            select coalesce(b.file_id, '') as file_id,
                   coalesce(b.version_id, '') as version_id,
                   coalesce(wf.logical_name, a.file_name) as display_name,
                   a.id as attachment_id,
                   coalesce(m.external_message_id, '') as message_external_id,
                   a.status as source_status,
                   a.readability_status as readability_status,
                   coalesce(nullif(a.readability_error_code, ''), a.failure_code, '')
                     as error_code,
                   a.finished_at as source_ready_at,
                   f.source_received_at as source_received_at,
                   f.status as file_status,
                   v.status as version_status
              from message_attachment a
              join agent_message m on m.id = a.message_id
              left join message_attachment_file_binding b on b.attachment_id = a.id
              left join managed_file f on f.id = b.file_id
              left join managed_file_version v on v.id = b.version_id
              left join task_workspace_file wf
                on wf.workspace_id = a.task_workspace_id
               and wf.file_id = b.file_id
               and wf.status = 'ACTIVE'
             where m.session_id = ? and a.task_workspace_id = ?
             order by a.finished_at, a.id
            """,
            (session_id, workspace_id),
        )
        workspace_files = self.database.execute(
            """
            select wf.file_id as file_id,
                   wf.selected_version_id as version_id,
                   wf.logical_name as display_name,
                   '' as attachment_id,
                   '' as message_external_id,
                   case when v.status = 'AVAILABLE' then 'READY' else coalesce(v.status, '') end
                     as source_status,
                   coalesce((
                     select a.readability_status
                       from message_attachment_file_binding b
                       join message_attachment a on a.id = b.attachment_id
                      where b.version_id = wf.selected_version_id
                      order by a.readability_updated_at desc, a.id desc
                      limit 1
                   ), 'NOT_REQUIRED') as readability_status,
                   coalesce((
                     select coalesce(nullif(a.readability_error_code, ''), a.failure_code, '')
                       from message_attachment_file_binding b
                       join message_attachment a on a.id = b.attachment_id
                      where b.version_id = wf.selected_version_id
                      order by a.readability_updated_at desc, a.id desc
                      limit 1
                   ), '') as error_code,
                   v.created_at as source_ready_at,
                   f.source_received_at as source_received_at,
                   f.status as file_status,
                   v.status as version_status
              from task_workspace_file wf
              join managed_file f on f.id = wf.file_id
              join managed_file_version v on v.id = wf.selected_version_id
             where wf.workspace_id = ? and wf.status = 'ACTIVE'
             order by v.created_at, wf.file_id
            """,
            (workspace_id,),
        )
        return self._merge_file_turn_rows([*attachments, *workspace_files])

    def list_session_retained_attachment_rows(
        self,
        *,
        session_id: str,
        now: str,
    ) -> list[dict[str, Any]]:
        if not session_id:
            return []
        rows = self.database.execute(
            """
            select coalesce(b.file_id, '') as file_id,
                   coalesce(b.version_id, '') as version_id,
                   coalesce(a.file_name, f.display_name, '') as display_name,
                   a.id as attachment_id,
                   coalesce(m.external_message_id, '') as message_external_id,
                   a.status as source_status,
                   a.readability_status as readability_status,
                   coalesce(nullif(a.readability_error_code, ''), a.failure_code, '')
                     as error_code,
                   a.finished_at as source_ready_at,
                   f.source_received_at as source_received_at,
                   f.status as file_status,
                   v.status as version_status
              from message_attachment a
              join agent_message m on m.id = a.message_id
              join message_attachment_file_binding b on b.attachment_id = a.id
              join managed_file f on f.id = b.file_id
             join managed_file_version v on v.id = b.version_id
             where m.session_id = ?
               and a.status in ('READY', 'stored_not_interpreted')
               and a.expires_at is not null
               and a.expires_at > ?
               and b.retention_expires_at > ?
               and f.status = 'ACTIVE'
               and v.status in ('AVAILABLE', 'CONFLICT')
               and exists (
                 select 1 from file_retention_fact r
                  where r.version_id = v.id and r.expires_at > ?
               )
             order by a.created_at, a.id
            """,
            (session_id, now, now, now),
        )
        return [row for row in rows if row.get("file_id") and row.get("version_id")]

    @staticmethod
    def _merge_file_turn_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in rows:
            payload = dict(row)
            file_id = str(payload.get("file_id") or "")
            version_id = str(payload.get("version_id") or "")
            attachment_id = str(payload.get("attachment_id") or "")
            key = (file_id, version_id, attachment_id or file_id)
            existing = merged.get(key)
            if existing is None:
                merged[key] = payload
                continue
            if not existing.get("message_external_id") and payload.get("message_external_id"):
                merged[key] = payload
        return list(merged.values())

    def record_file_readiness_blocked_turn(
        self,
        *,
        session_id: str,
        workspace_id: str,
        user_message_id: str,
        reason_code: str,
        version_ids: tuple[str, ...],
        expires_at: str,
    ) -> str:
        turn_id = new_id("file_turn")
        timestamp = now_iso()
        self.database.execute(
            """
            insert into file_readiness_blocked_turn
              (id, session_id, workspace_id, user_message_id, reason_code,
               status, created_at, expires_at, notified_at)
            values (?, ?, ?, ?, ?, 'OPEN', ?, ?, null)
            """,
            (
                turn_id,
                session_id,
                workspace_id,
                user_message_id,
                reason_code,
                timestamp,
                expires_at,
            ),
        )
        for version_id in dict.fromkeys(version_ids):
            if not version_id:
                continue
            self.database.execute(
                """
                insert into file_readiness_blocked_turn_version
                  (turn_id, file_version_id)
                values (?, ?)
                """,
                (turn_id, version_id),
            )
        return turn_id

    def expire_file_readiness_blocked_turns(self, *, now: str | None = None) -> int:
        timestamp = now or now_iso()
        rows = self.database.execute(
            """
            update file_readiness_blocked_turn
               set status = 'EXPIRED'
             where status = 'OPEN'
               and (
                 expires_at <= ?
                 or workspace_id in (
                   select id from task_workspace where status <> 'ACTIVE'
                 )
               )
            returning id
            """,
            (timestamp,),
        )
        return len(rows)

    def list_ready_file_readiness_blocked_turns(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select t.id, t.session_id, t.workspace_id, t.user_message_id, t.reason_code
              from file_readiness_blocked_turn t
             where t.status = 'OPEN'
               and exists (
                 select 1 from file_readiness_blocked_turn_version v
                  where v.turn_id = t.id
               )
               and not exists (
                 select 1
                   from file_readiness_blocked_turn_version v
                  where v.turn_id = t.id
                    and coalesce((
                      select a.readability_status
                        from message_attachment_file_binding b
                        join message_attachment a on a.id = b.attachment_id
                       where b.version_id = v.file_version_id
                       order by a.readability_updated_at desc, a.id desc
                       limit 1
                    ), (
                      select case r.status
                               when 'AVAILABLE' then 'AVAILABLE'
                               when 'PARTIAL' then 'PARTIAL'
                               else r.status
                             end
                        from file_representation r
                       where r.source_version_id = v.file_version_id
                         and r.kind = 'MARKDOWN'
                       order by r.created_at desc
                       limit 1
                    ), 'PENDING') not in ('AVAILABLE', 'PARTIAL')
               )
             order by t.created_at, t.id
            """
        )
        return [dict(row) for row in rows]

    def list_blocked_turn_version_ids(self, turn_id: str) -> list[str]:
        rows = self.database.execute(
            """
            select file_version_id
              from file_readiness_blocked_turn_version
             where turn_id = ?
             order by file_version_id
            """,
            (turn_id,),
        )
        return [str(row["file_version_id"]) for row in rows]

    def mark_file_readiness_blocked_turn_notified(self, turn_id: str) -> None:
        timestamp = now_iso()
        self.database.execute(
            """
            update file_readiness_blocked_turn
               set status = 'NOTIFIED', notified_at = ?
             where id = ? and status = 'OPEN'
            """,
            (timestamp, turn_id),
        )

    def display_names_for_versions(self, version_ids: tuple[str, ...]) -> tuple[str, ...]:
        names: list[str] = []
        for version_id in version_ids:
            row = self.database.execute_one(
                """
                select coalesce(wf.logical_name, f.display_name, a.file_name, '') as display_name
                  from managed_file_version v
                  join managed_file f on f.id = v.file_id
                  left join task_workspace_file wf
                    on wf.file_id = v.file_id and wf.status = 'ACTIVE'
                  left join message_attachment_file_binding b on b.version_id = v.id
                  left join message_attachment a on a.id = b.attachment_id
                 where v.id = ?
                 limit 1
                """,
                (version_id,),
            )
            names.append(str((row or {}).get("display_name") or "文件"))
        return tuple(names)

    def refresh_file_turn_dependency_row(self, payload: dict[str, Any]) -> dict[str, Any]:
        refreshed = dict(payload)
        attachment_id = str(payload.get("attachment_id") or "")
        version_id = str(payload.get("version_id") or "")
        if attachment_id and not attachment_id.startswith("current:"):
            row = self.database.execute_one(
                """
                select a.status, a.readability_status, a.file_name,
                       coalesce(nullif(a.readability_error_code, ''), a.failure_code, '')
                         as error_code,
                       coalesce(b.file_id, '') as file_id,
                       coalesce(b.version_id, '') as version_id
                  from message_attachment a
                  left join message_attachment_file_binding b on b.attachment_id = a.id
                 where a.id = ?
                """,
                (attachment_id,),
            )
            if row is not None:
                refreshed["source_status"] = str(row["status"] or "")
                refreshed["readability_status"] = str(
                    row.get("readability_status") or "NOT_REQUIRED"
                )
                refreshed["file_id"] = str(row.get("file_id") or refreshed.get("file_id") or "")
                refreshed["version_id"] = str(
                    row.get("version_id") or refreshed.get("version_id") or ""
                )
                refreshed["display_name"] = str(
                    row.get("file_name") or refreshed.get("display_name") or ""
                )
                refreshed["error_code"] = str(
                    row.get("error_code") or refreshed.get("error_code") or ""
                )
                return refreshed
        if version_id:
            row = self.database.execute_one(
                """
                select v.status as version_status,
                       coalesce((
                         select a.readability_status
                           from message_attachment_file_binding b
                           join message_attachment a on a.id = b.attachment_id
                          where b.version_id = v.id
                          order by a.readability_updated_at desc, a.id desc
                          limit 1
                       ), 'NOT_REQUIRED') as readability_status,
                       coalesce((
                         select coalesce(nullif(a.readability_error_code, ''), a.failure_code, '')
                           from message_attachment_file_binding b
                           join message_attachment a on a.id = b.attachment_id
                          where b.version_id = v.id
                          order by a.readability_updated_at desc, a.id desc
                          limit 1
                       ), '') as error_code
                  from managed_file_version v
                 where v.id = ?
                """,
                (version_id,),
            )
            if row is not None:
                status = str(row.get("version_status") or "")
                refreshed["source_status"] = "READY" if status == "AVAILABLE" else status
                refreshed["readability_status"] = str(
                    row.get("readability_status") or "NOT_REQUIRED"
                )
                refreshed["error_code"] = str(
                    row.get("error_code") or refreshed.get("error_code") or ""
                )
        return refreshed

    def update_attachment(
        self,
        attachment_id: str,
        *,
        status: str,
        detected_mime: str | None = None,
        size_bytes: int | None = None,
        sha256: str | None = None,
        object_bucket: str | None = None,
        object_key: str | None = None,
        failure_code: str | None = None,
        clear_credential: bool = False,
    ) -> MessageAttachment:
        terminal = status in {"READY", "REJECTED", "FAILED", "stored_not_interpreted"}
        self.database.execute(
            """
            update message_attachment
            set status = ?, detected_mime = coalesce(?, detected_mime),
                size_bytes = coalesce(?, size_bytes), sha256 = coalesce(?, sha256),
                object_bucket = coalesce(?, object_bucket), object_key = coalesce(?, object_key),
                failure_code = coalesce(?, failure_code), updated_at = ?,
                finished_at = case when ? then ? else finished_at end,
                source_credential_ciphertext = case when ? then '' else source_credential_ciphertext end,
                source_credential_type = case when ? then '' else source_credential_type end,
                source_credential_expires_at = case when ? then null else source_credential_expires_at end
            where id = ?
            """,
            (
                status,
                detected_mime,
                size_bytes,
                sha256,
                object_bucket,
                object_key,
                failure_code,
                now_iso(),
                terminal,
                now_iso(),
                clear_credential or terminal,
                clear_credential or terminal,
                clear_credential or terminal,
                attachment_id,
            ),
        )
        return self.get_attachment(attachment_id)

    def _attachment_from_row(self, row: dict[str, Any]) -> MessageAttachment:
        return MessageAttachment(
            id=str(row["id"]),
            message_id=str(row["message_id"]),
            job_id=str(row.get("job_id") or ""),
            ordinal=int(row["ordinal"]),
            media_type=str(row["media_type"]),
            file_name=str(row["file_name"]),
            declared_mime=str(row.get("declared_mime") or ""),
            detected_mime=str(row.get("detected_mime") or ""),
            declared_size=int(row["declared_size"])
            if row.get("declared_size") is not None
            else None,
            size_bytes=int(row["size_bytes"]) if row.get("size_bytes") is not None else None,
            sha256=str(row.get("sha256") or ""),
            object_bucket=str(row.get("object_bucket") or ""),
            object_key=str(row.get("object_key") or ""),
            status=str(row["status"]),
            task_workspace_id=str(row.get("task_workspace_id") or ""),
            claimed_at=(str(row["claimed_at"]) if row.get("claimed_at") else None),
            failure_code=str(row.get("failure_code") or ""),
            readability_status=str(row.get("readability_status") or "NOT_REQUIRED"),
            file_processing_run_id=str(row.get("file_processing_run_id") or ""),
            readability_error_code=str(row.get("readability_error_code") or ""),
            readability_updated_at=(
                str(row["readability_updated_at"]) if row.get("readability_updated_at") else None
            ),
        )
