from __future__ import annotations

from typing import Any

from app.modules.identity_discovery.domain import (
    CandidateIdentityState,
    ConversationScope,
    DingTalkIdentityObservation,
)
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound


class DingTalkIdentityDiscoveryRepository:
    max_messages_per_candidate = 20

    def __init__(self, database: Database) -> None:
        self.database = database

    def observe(self, observation: DingTalkIdentityObservation) -> dict[str, object]:
        timestamp = now_iso()
        candidate_id = new_id("dingtalk_candidate")
        with self.database.unit_of_work():
            self.database.execute(
                """
                insert into dingtalk_identity_candidate
                  (id, tenant_code, external_subject_id, display_name,
                   first_seen_at, last_seen_at, observation_count, revision,
                   created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, 0, 1, ?, ?)
                on conflict(tenant_code, external_subject_id) do nothing
                """,
                (
                    candidate_id,
                    observation.tenant_code,
                    observation.external_subject_id,
                    observation.display_name,
                    observation.received_at,
                    observation.received_at,
                    timestamp,
                    timestamp,
                ),
            )
            candidate = self.database.execute_one(
                """
                select *
                from dingtalk_identity_candidate
                where tenant_code = ? and external_subject_id = ?
                """,
                (observation.tenant_code, observation.external_subject_id),
            )
            if candidate is None:
                raise RuntimeError("DingTalk identity candidate could not be resolved")
            candidate_id = str(candidate["id"])
            inserted = self.database.execute(
                """
                insert into dingtalk_identity_candidate_message
                  (id, candidate_id, source_ingress_event_id, connector_id,
                   robot_code, conversation_type, conversation_id, message_kind,
                   safe_text, text_truncated, attachment_type, attachment_name,
                   attachment_size, occurred_at, received_at, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(source_ingress_event_id) do nothing
                returning id
                """,
                (
                    new_id("dingtalk_candidate_message"),
                    candidate_id,
                    observation.source_ingress_event_id,
                    observation.connector_id,
                    observation.robot_code,
                    observation.conversation_type,
                    observation.conversation_id,
                    observation.message_kind,
                    observation.safe_text,
                    1 if observation.text_truncated else 0,
                    observation.attachment_type,
                    observation.attachment_name,
                    observation.attachment_size,
                    observation.occurred_at,
                    observation.received_at,
                    timestamp,
                ),
            )
            if inserted:
                self.database.execute(
                    """
                    update dingtalk_identity_candidate
                    set display_name = case
                          when ? <> '' then ? else display_name end,
                        first_seen_at = case
                          when first_seen_at > ? then ? else first_seen_at end,
                        last_seen_at = case
                          when last_seen_at < ? then ? else last_seen_at end,
                        observation_count = observation_count + 1,
                        revision = revision + 1,
                        updated_at = ?
                    where id = ?
                    """,
                    (
                        observation.display_name,
                        observation.display_name,
                        observation.received_at,
                        observation.received_at,
                        observation.received_at,
                        observation.received_at,
                        timestamp,
                        candidate_id,
                    ),
                )
                self.database.execute(
                    """
                    delete from dingtalk_identity_candidate_message
                    where candidate_id = ?
                      and id not in (
                        select id
                        from dingtalk_identity_candidate_message
                        where candidate_id = ?
                        order by received_at desc, id desc
                        limit ?
                      )
                    """,
                    (
                        candidate_id,
                        candidate_id,
                        self.max_messages_per_candidate,
                    ),
                )
        return self._candidate_public(self._get_candidate_row(candidate_id))

    def list_candidates(
        self,
        *,
        cutoff: str,
        search: str,
        conversation_scope: str,
        limit: int,
        after_last_seen_at: str,
        after_id: str,
    ) -> tuple[list[dict[str, object]], bool]:
        where, params = self._visible_where(
            cutoff=cutoff,
            search=search,
            conversation_scope=conversation_scope,
        )
        if after_last_seen_at and after_id:
            where += (
                " and (c.last_seen_at < ? "
                "or (c.last_seen_at = ? and c.id < ?))"
            )
            params.extend((after_last_seen_at, after_last_seen_at, after_id))
        rows = self.database.execute(
            f"""
            select c.*,
                   i.id as historical_identity_id,
                   i.status as historical_identity_status,
                   i.revision as historical_identity_revision,
                   i.user_id as historical_user_id,
                   u.username as historical_username,
                   u.display_name as historical_user_display_name,
                   u.status as historical_user_status
            from dingtalk_identity_candidate c
            left join user_external_identity i
              on i.provider = 'dingtalk'
             and i.tenant_code = c.tenant_code
             and i.external_subject_id = c.external_subject_id
            left join app_user u on u.id = i.user_id
            where {where}
            order by c.last_seen_at desc, c.id desc
            limit ?
            """,
            (*params, limit + 1),
        )
        has_more = len(rows) > limit
        return (
            [self._candidate_public(row, include_messages=True) for row in rows[:limit]],
            has_more,
        )

    def get_visible_candidate(
        self, candidate_id: str, *, cutoff: str
    ) -> dict[str, object]:
        row = self.database.execute_one(
            """
            select c.*,
                   i.id as historical_identity_id,
                   i.status as historical_identity_status,
                   i.revision as historical_identity_revision,
                   i.user_id as historical_user_id,
                   u.username as historical_username,
                   u.display_name as historical_user_display_name,
                   u.status as historical_user_status
            from dingtalk_identity_candidate c
            left join user_external_identity i
              on i.provider = 'dingtalk'
             and i.tenant_code = c.tenant_code
             and i.external_subject_id = c.external_subject_id
            left join app_user u on u.id = i.user_id
            where c.id = ? and c.last_seen_at >= ?
              and (
                i.id is null
                or i.status <> 'enabled'
                or u.status <> 'enabled'
              )
            """,
            (candidate_id, cutoff),
        )
        if row is None:
            raise NotFound(
                "DingTalk identity candidate not found",
                safe_message="未找到待处理的钉钉用户",
            )
        return self._candidate_public(row, include_messages=True)

    def count_visible(self, *, cutoff: str) -> int:
        row = self.database.execute_one(
            """
            select count(*) as count
            from dingtalk_identity_candidate c
            left join user_external_identity i
              on i.provider = 'dingtalk'
             and i.tenant_code = c.tenant_code
             and i.external_subject_id = c.external_subject_id
            left join app_user u on u.id = i.user_id
            where c.last_seen_at >= ?
              and (
                i.id is null
                or i.status <> 'enabled'
                or u.status <> 'enabled'
              )
            """,
            (cutoff,),
        )
        return int(row["count"]) if row else 0

    def cleanup_expired(self, *, cutoff: str, limit: int = 500) -> int:
        rows = self.database.execute(
            """
            select id
            from dingtalk_identity_candidate
            where last_seen_at < ?
            order by last_seen_at, id
            limit ?
            """,
            (cutoff, min(max(limit, 1), 5_000)),
        )
        candidate_ids = [str(row["id"]) for row in rows]
        if not candidate_ids:
            return 0
        placeholders = ",".join("?" for _ in candidate_ids)
        with self.database.unit_of_work():
            self.database.execute(
                f"delete from dingtalk_identity_candidate where id in ({placeholders})",
                tuple(candidate_ids),
            )
        return len(candidate_ids)

    def _get_candidate_row(self, candidate_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            "select * from dingtalk_identity_candidate where id = ?",
            (candidate_id,),
        )
        if row is None:
            raise NotFound(
                "DingTalk identity candidate not found",
                safe_message="未找到待处理的钉钉用户",
            )
        return row

    def _candidate_public(
        self,
        row: dict[str, Any],
        *,
        include_messages: bool = False,
    ) -> dict[str, object]:
        messages = self._messages(str(row["id"])) if include_messages else []
        direct = any(item["conversation_type"] == "direct" for item in messages)
        group = any(item["conversation_type"] == "group" for item in messages)
        scope = (
            ConversationScope.BOTH.value
            if direct and group
            else (
                ConversationScope.GROUP.value
                if group
                else ConversationScope.DIRECT.value
            )
        )
        historical_identity_id = str(row.get("historical_identity_id") or "")
        identity_state = (
            CandidateIdentityState.RESTORE_REQUIRED.value
            if historical_identity_id
            else CandidateIdentityState.WAITING_BIND.value
        )
        return {
            "id": str(row["id"]),
            "tenant_code": str(row["tenant_code"]),
            "external_subject_id": str(row["external_subject_id"]),
            "display_name": str(row.get("display_name") or ""),
            "first_seen_at": str(row["first_seen_at"]),
            "last_seen_at": str(row["last_seen_at"]),
            "observation_count": int(row.get("observation_count") or 0),
            "revision": int(row.get("revision") or 1),
            "identity_state": identity_state,
            "conversation_scope": scope,
            "group_ids": list(
                dict.fromkeys(
                    str(item["conversation_id"])
                    for item in messages
                    if item["conversation_type"] == "group"
                    and item["conversation_id"]
                )
            ),
            "robot_codes": list(
                dict.fromkeys(
                    str(item["robot_code"])
                    for item in messages
                    if item["robot_code"]
                )
            ),
            "connector_names": list(
                dict.fromkeys(
                    str(item["connector_name"])
                    for item in messages
                    if item["connector_name"]
                )
            ),
            "latest_message": messages[0] if messages else None,
            "messages": messages,
            "historical_identity": (
                {
                    "id": historical_identity_id,
                    "status": str(row.get("historical_identity_status") or ""),
                    "revision": int(row.get("historical_identity_revision") or 1),
                    "user_id": str(row.get("historical_user_id") or ""),
                    "username": str(row.get("historical_username") or ""),
                    "user_display_name": str(
                        row.get("historical_user_display_name") or ""
                    ),
                    "user_status": str(row.get("historical_user_status") or ""),
                }
                if historical_identity_id
                else None
            ),
        }

    def _messages(self, candidate_id: str) -> list[dict[str, object]]:
        rows = self.database.execute(
            """
            select m.id, m.connector_id, c.name as connector_name,
                   m.robot_code, m.conversation_type, m.conversation_id,
                   m.message_kind, m.safe_text, m.text_truncated,
                   m.attachment_type, m.attachment_name, m.attachment_size,
                   m.occurred_at, m.received_at
            from dingtalk_identity_candidate_message m
            left join integration_connector c on c.id = m.connector_id
            where m.candidate_id = ?
            order by m.received_at desc, m.id desc
            limit ?
            """,
            (candidate_id, self.max_messages_per_candidate),
        )
        return [
            {
                "id": str(row["id"]),
                "connector_id": str(row["connector_id"]),
                "connector_name": str(row.get("connector_name") or ""),
                "robot_code": str(row.get("robot_code") or ""),
                "conversation_type": str(row["conversation_type"]),
                "conversation_id": str(row.get("conversation_id") or ""),
                "message_kind": str(row.get("message_kind") or "unsupported"),
                "safe_text": str(row.get("safe_text") or ""),
                "text_truncated": bool(row.get("text_truncated")),
                "attachment_type": str(row.get("attachment_type") or ""),
                "attachment_name": str(row.get("attachment_name") or ""),
                "attachment_size": (
                    int(row["attachment_size"])
                    if row.get("attachment_size") is not None
                    else None
                ),
                "occurred_at": str(row["occurred_at"]),
                "received_at": str(row["received_at"]),
            }
            for row in rows
        ]

    @staticmethod
    def _visible_where(
        *,
        cutoff: str,
        search: str,
        conversation_scope: str,
    ) -> tuple[str, list[object]]:
        clauses = [
            "c.last_seen_at >= ?",
            "(i.id is null or i.status <> 'enabled' or u.status <> 'enabled')",
        ]
        params: list[object] = [cutoff]
        term = search.strip().lower()
        if term:
            escaped = (
                term.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            clauses.append(
                """
                (
                  lower(c.display_name) like ? escape '\\'
                  or lower(c.external_subject_id) like ? escape '\\'
                  or exists (
                    select 1
                    from dingtalk_identity_candidate_message sm
                    left join integration_connector sc on sc.id = sm.connector_id
                    where sm.candidate_id = c.id
                      and (
                        lower(sm.conversation_id) like ? escape '\\'
                        or lower(sm.robot_code) like ? escape '\\'
                        or lower(coalesce(sc.name, '')) like ? escape '\\'
                      )
                  )
                )
                """
            )
            params.extend((pattern, pattern, pattern, pattern, pattern))
        has_direct = (
            "exists (select 1 from dingtalk_identity_candidate_message dm "
            "where dm.candidate_id = c.id and dm.conversation_type = 'direct')"
        )
        has_group = (
            "exists (select 1 from dingtalk_identity_candidate_message gm "
            "where gm.candidate_id = c.id and gm.conversation_type = 'group')"
        )
        if conversation_scope == ConversationScope.DIRECT.value:
            clauses.extend((has_direct, f"not {has_group}"))
        elif conversation_scope == ConversationScope.GROUP.value:
            clauses.extend((has_group, f"not {has_direct}"))
        elif conversation_scope == ConversationScope.BOTH.value:
            clauses.extend((has_direct, has_group))
        return " and ".join(clauses), params
