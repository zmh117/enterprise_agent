from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.admin.application import AdminCapabilityService
from app.modules.authorization_center.infrastructure import AuthorizationCenterRepository
from app.modules.channel.domain.channel_event import ChannelEvent
from app.modules.identity.application import IdentityService
from app.modules.identity.application import AuthorizationEvaluator
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.identity_discovery.application.ports import DingTalkIdentityDiscoveryStore
from app.modules.identity_discovery.domain import PendingDingTalkIdentityObservation
from app.shared.database import Database
from app.shared.exceptions import AppError, NonRetryableExecutionError


_DISCOVERY_REJECTION_CODES = frozenset(
    {"identity_not_bound", "identity_inactive", "identity_user_inactive"}
)
_ALLOWED_MESSAGE_KINDS = frozenset(
    {"text", "markdown", "image", "picture", "file", "audio", "video", "unsupported"}
)
_ALLOWED_ATTACHMENT_TYPES = frozenset(
    {"image", "file", "document", "audio", "video"}
)


class DingTalkIdentityDiscoveryService:
    retention_days = 30
    max_message_chars = 1_000
    max_attachment_name_chars = 255
    max_attachment_size = 1024 * 1024 * 1024 * 1024

    def __init__(
        self,
        *,
        store: DingTalkIdentityDiscoveryStore,
        database: Database,
        identity_repository: IdentityRepository,
        identity_service: IdentityService,
        audit_service: AuditService,
        authorization: AuthorizationEvaluator,
        authorization_repository: AuthorizationCenterRepository,
    ) -> None:
        self.store = store
        self.database = database
        self.identity_repository = identity_repository
        self.identity_service = identity_service
        self.audit_service = audit_service
        self.authorization = authorization
        self.authorization_repository = authorization_repository

    @staticmethod
    def is_discoverable_rejection(error_code: str) -> bool:
        return error_code in _DISCOVERY_REJECTION_CODES

    def build_pending_observation(
        self,
        *,
        event: ChannelEvent,
        message_kind: object,
        occurred_at: object,
    ) -> PendingDingTalkIdentityObservation | None:
        descriptor = event.source.external_identity
        if (
            event.source.type != "dingding_stream"
            or descriptor is None
            or descriptor.provider != "dingtalk"
            or not descriptor.tenant_code
            or not descriptor.external_subject_id
        ):
            return None
        safe_text = str(event.message or "")
        truncated = len(safe_text) > self.max_message_chars
        safe_text = safe_text[: self.max_message_chars]
        attachment_type = ""
        attachment_name = ""
        attachment_size: int | None = None
        if event.attachments:
            attachment = event.attachments[0]
            raw_type = str(attachment.media_type or "").strip().lower()
            attachment_type = (
                raw_type if raw_type in _ALLOWED_ATTACHMENT_TYPES else "file"
            )
            attachment_name = str(attachment.file_name or "")[
                : self.max_attachment_name_chars
            ]
            if attachment.declared_size is not None:
                declared_size = int(attachment.declared_size)
                if 0 <= declared_size <= self.max_attachment_size:
                    attachment_size = declared_size
        raw_kind = str(message_kind or "").strip().lower()
        normalized_kind = (
            raw_kind
            if raw_kind in _ALLOWED_MESSAGE_KINDS
            else (attachment_type or ("text" if safe_text else "unsupported"))
        )
        return PendingDingTalkIdentityObservation(
            tenant_code=descriptor.tenant_code[:120],
            external_subject_id=descriptor.external_subject_id[:200],
            display_name=descriptor.display_name[:200],
            connector_id=event.source.connector_id[:200],
            robot_code=str(
                event.source.metadata.get("robot_code")
                or event.source.metadata.get("bot_identity")
                or ""
            )[:200],
            conversation_type=(
                "group"
                if str(event.source.metadata.get("conversation_type") or "") == "group"
                else "direct"
            ),
            conversation_id=event.source.conversation_id[:300],
            message_kind=normalized_kind,
            safe_text=safe_text,
            text_truncated=truncated,
            attachment_type=attachment_type,
            attachment_name=attachment_name,
            attachment_size=attachment_size,
            occurred_at=_parse_dingtalk_occurred_at(occurred_at),
        )

    def observe_rejection(
        self,
        pending: PendingDingTalkIdentityObservation,
        *,
        source_ingress_event_id: str,
        received_at: str,
        rejection_code: str,
    ) -> dict[str, object]:
        if not self.is_discoverable_rejection(rejection_code):
            raise NonRetryableExecutionError(
                "Rejection is not eligible for identity discovery",
                safe_message="该渠道事件不符合身份发现条件",
                error_code="identity_discovery_ineligible",
            )
        return self.store.observe(
            pending.with_source(
                source_ingress_event_id=source_ingress_event_id,
                received_at=received_at,
            )
        )

    def list_candidates(
        self,
        *,
        search: str = "",
        conversation_scope: str = "all",
        limit: int = 25,
        cursor: str = "",
    ) -> dict[str, object]:
        after_last_seen_at, after_id = _decode_cursor(cursor)
        items, has_more = self.store.list_candidates(
            cutoff=self.cutoff(),
            search=search,
            conversation_scope=conversation_scope,
            limit=min(max(limit, 1), 100),
            after_last_seen_at=after_last_seen_at,
            after_id=after_id,
        )
        next_cursor = ""
        if has_more and items:
            last = items[-1]
            next_cursor = _encode_cursor(
                str(last["last_seen_at"]),
                str(last["id"]),
            )
        return {
            "candidates": items,
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    def get_candidate(self, candidate_id: str) -> dict[str, object]:
        return self.store.get_visible_candidate(candidate_id, cutoff=self.cutoff())

    def count_candidates(self) -> int:
        return self.store.count_visible(cutoff=self.cutoff())

    def cleanup_expired(self, *, limit: int = 500) -> int:
        return self.store.cleanup_expired(cutoff=self.cutoff(), limit=limit)

    def bind_candidate(
        self,
        *,
        actor_id: str,
        candidate_id: str,
        target_user_id: str,
        expected_candidate_revision: int,
        expected_user_revision: int,
        initial_role_ids: list[str] | None = None,
        bind_without_access_confirmed: bool = False,
    ) -> dict[str, object]:
        role_ids = list(dict.fromkeys(initial_role_ids or []))
        if not role_ids and not bind_without_access_confirmed:
            raise NonRetryableExecutionError(
                "Binding without access must be confirmed",
                safe_message="请选择初始角色，或明确确认“仅绑定身份，暂不授权”",
                error_code="bind_without_access_confirmation_required",
                field_errors=[
                    {
                        "field": "bind_without_access_confirmed",
                        "message": "仅绑定身份时必须明确确认",
                    }
                ],
            )
        if role_ids and bind_without_access_confirmed:
            raise NonRetryableExecutionError(
                "Initial roles conflict with bind-only confirmation",
                safe_message="已选择初始角色时不能同时选择“仅绑定身份”",
                error_code="validation_failed",
            )
        try:
            with self.database.unit_of_work():
                candidate = self.store.get_visible_candidate(
                    candidate_id,
                    cutoff=self.cutoff(),
                )
                if int(candidate["revision"]) != expected_candidate_revision:
                    raise NonRetryableExecutionError(
                        "Candidate revision conflict",
                        safe_message="候选信息已发生变化，请刷新后重试",
                        error_code="revision_conflict",
                    )
                historical = self.identity_repository.find_external_identity(
                    provider="dingtalk",
                    tenant_code=str(candidate["tenant_code"]),
                    external_subject_id=str(candidate["external_subject_id"]),
                    include_disabled=True,
                )
                if historical is not None:
                    raise NonRetryableExecutionError(
                        "Historical identity must be restored by its original owner",
                        safe_message="该钉钉身份已有历史归属，请前往原人员恢复",
                        error_code="identity_restore_required",
                    )
                messages = candidate.get("messages")
                latest = messages[0] if isinstance(messages, list) and messages else None
                if not isinstance(latest, dict) or not latest.get("connector_id"):
                    raise NonRetryableExecutionError(
                        "Candidate has no trusted active connector source",
                        safe_message="候选来源渠道不可用，请刷新或检查渠道配置",
                        error_code="identity_discovery_connector_unavailable",
                    )
                roles = []
                actor_roles = self.identity_repository.role_codes_for_user(actor_id)
                for role_id in role_ids:
                    role = self.authorization_repository.get_role(role_id)
                    if role["status"] != "enabled":
                        raise NonRetryableExecutionError(
                            "Initial role is disabled",
                            safe_message=f"角色“{role['name']}”已停用，不能分配",
                            error_code="role_disabled",
                            field_errors=[
                                {
                                    "field": "initial_role_ids",
                                    "message": f"角色“{role['name']}”已停用",
                                }
                            ],
                        )
                    if "platform-admin" not in actor_roles:
                        self.authorization.require(
                            user_id=actor_id,
                            resource_type="role",
                            resource_code=role_id,
                            action="assign",
                        )
                    roles.append(role)
                identity = self.identity_service.bind_dingtalk(
                    actor_id=actor_id,
                    user_id=target_user_id,
                    tenant_code=str(candidate["tenant_code"]),
                    external_subject_id=str(candidate["external_subject_id"]),
                    connector_id=str(latest["connector_id"]),
                    display_name=str(candidate.get("display_name") or ""),
                    expected_user_revision=expected_user_revision,
                )
                memberships = []
                for role in roles:
                    current = self.database.execute_one(
                        """
                        select * from rbac_user_role
                         where user_id = ? and role_id = ?
                        """,
                        (target_user_id, role["id"]),
                    )
                    self.authorization_repository.bump_membership_revision(
                        str(role["id"]), int(role["membership_revision"])
                    )
                    memberships.append(
                        self.identity_repository.assign_role(
                            user_id=target_user_id,
                            role_id=str(role["id"]),
                            expected_revision=int(current["revision"]) if current else 0,
                            assigned_by=actor_id,
                            assignment_source="dingtalk_binding",
                        )
                    )
                self.audit_service.record(
                    "identity.discovery.bound",
                    status="SUCCEEDED",
                    summary="DingTalk discovery candidate bound",
                    actor_id=actor_id,
                    payload={
                        "candidate_id": candidate_id,
                        "target_user_id": target_user_id,
                        "identity_id": identity["id"],
                        "initial_role_ids": role_ids,
                        "bind_without_access": not role_ids,
                    },
                )
                admin_summary = AdminCapabilityService(
                    self.identity_repository,
                    self.authorization,
                ).summary(target_user_id)
                business_access = [
                    access
                    for role in self.authorization_repository.active_role_rows_for_user(
                        target_user_id
                    )
                    for access in self.authorization_repository.list_business_access(
                        str(role["id"])
                    )
                    if access["status"] == "enabled"
                ]
            return {
                "candidate_id": candidate_id,
                "identity": identity,
                "memberships": memberships,
                "authorization_summary": {
                    "access_status": (
                        "已获得角色授权"
                        if business_access
                        else "未获得应用权限"
                    ),
                    "role_ids": role_ids,
                    "management_capabilities": admin_summary["capabilities"],
                    "business_applications": [
                        {
                            "id": item["application_id"],
                            "code": item["application_code"],
                            "name": item["application_name"],
                            "capability_codes": item["capability_codes"],
                            "scopes": item["scopes"],
                        }
                        for item in business_access
                    ],
                },
            }
        except Exception as exc:
            error_code = (
                exc.error_code
                if isinstance(exc, AppError) and exc.error_code
                else "identity_discovery_bind_failed"
            )
            self.audit_service.record(
                "identity.discovery.binding_failed",
                status="DENIED",
                summary="DingTalk discovery candidate binding failed",
                actor_id=actor_id,
                payload={
                    "candidate_id": candidate_id,
                    "target_user_id": target_user_id,
                    "error_code": error_code,
                },
            )
            raise

    def cutoff(self) -> str:
        return (
            datetime.now(UTC) - timedelta(days=self.retention_days)
        ).isoformat()


def _parse_dingtalk_occurred_at(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    parsed: datetime | None = None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1_000
        try:
            parsed = datetime.fromtimestamp(raw, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.replace(".", "", 1).isdigit():
            try:
                return _parse_dingtalk_occurred_at(float(text))
            except ValueError:
                return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        parsed = parsed.astimezone(UTC)
    if parsed is None or not 2000 <= parsed.year <= 2100:
        return None
    return parsed.isoformat()


def _encode_cursor(last_seen_at: str, candidate_id: str) -> str:
    payload = json.dumps(
        {"last_seen_at": last_seen_at, "id": candidate_id},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    if not cursor:
        return "", ""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value: Any = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(value, dict):
            raise ValueError
        last_seen_at = str(value.get("last_seen_at") or "")
        candidate_id = str(value.get("id") or "")
        if not last_seen_at or not candidate_id:
            raise ValueError
        return last_seen_at, candidate_id
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NonRetryableExecutionError(
            "Invalid identity discovery cursor",
            safe_message="分页游标无效，请刷新后重试",
            error_code="validation_failed",
            field_errors=[{"field": "cursor", "message": "分页游标无效"}],
        ) from exc
