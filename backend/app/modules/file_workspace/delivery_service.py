from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.file_workspace.domain import RetentionReason
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.job.infrastructure.repositories import AgentRepository
from app.shared.config import DeliverySettings
from app.shared.exceptions import NonRetryableExecutionError


class FileVersionDeliveryService:
    """Freeze exact committed versions into the existing Delivery Outbox."""

    def __init__(
        self,
        repository: FileWorkspaceRepository,
        agent_repository: AgentRepository,
        settings: DeliverySettings,
    ) -> None:
        self.repository = repository
        self.agent_repository = agent_repository
        self.settings = settings

    def enqueue(
        self,
        *,
        job_id: str,
        file_id: str,
        version_id: str,
        display_name: str,
    ) -> dict[str, str]:
        version = self.repository.require_content_available(version_id)
        if str(version["file_id"]) != file_id or str(version["status"]) != "AVAILABLE":
            raise NonRetryableExecutionError(
                "Only an available exact file version can be delivered",
                safe_message="只能交付已成功提交的精确文件版本",
                error_code="file_delivery_version_invalid",
            )
        job = self.agent_repository.get_job(job_id)
        route = ReplyRoute.from_dict(job.reply_route)
        canonical_route = json.dumps(
            job.reply_route or {"type": "none"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact_name = f"file-delivery-{version_id}.json"
        artifact = self.agent_repository.get_artifact_for_job(
            job_id=job_id,
            artifact_type="file_version_delivery",
            name=artifact_name,
        )
        with self.repository.database.unit_of_work():
            if artifact is None:
                artifact_id = self.agent_repository.add_artifact(
                    job_id=job_id,
                    artifact_type="file_version_delivery",
                    name=artifact_name,
                    content=json.dumps(
                        {
                            "file_id": file_id,
                            "version_id": version_id,
                            "display_name": display_name,
                            "size_bytes": int(version["size_bytes"]),
                            "content_sha256": str(version["content_sha256"]),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
            else:
                artifact_id = str(artifact["id"])
            event = self.agent_repository.create_delivery_event(
                job_id=job_id,
                result_artifact_id=artifact_id,
                application_publication_id=(
                    job.business_application_publication_id
                    or job.agent_publication_id
                ),
                delivery_binding={
                    "delivery_kind": "file_version",
                    "title": display_name,
                    "route_type": route.type,
                    "connector_id": route.connector_id,
                    "route_hash": hashlib.sha256(
                        canonical_route.encode("utf-8")
                    ).hexdigest(),
                    "route_source": "agent_job.reply_route_json",
                },
                target_summary={
                    "route_type": route.type,
                    "connector_id": route.connector_id,
                    "file_count": 1,
                },
                correlation_id=str(
                    (job.business_application_route_decision or {}).get(
                        "correlation_id", ""
                    )
                ),
                max_attempts=self.settings.outbox_max_attempts,
                max_replay_count=self.settings.outbox_max_replays,
            )
            changed = self.repository.database.execute(
                """
                update delivery_outbox
                   set delivery_kind = 'FILE_VERSION', file_id = ?,
                       file_version_id = ?, file_content_sha256 = ?,
                       principal_user_id = ?, session_id = ?,
                       agent_publication_id = ?
                 where id = ? and file_version_id in ('', ?)
                 returning id
                """,
                (
                    file_id,
                    version_id,
                    version["content_sha256"],
                    job.internal_user_id,
                    job.session_id,
                    job.agent_publication_id,
                    event.id,
                    version_id,
                ),
            )
            if not changed:
                raise NonRetryableExecutionError(
                    "Delivery event is bound to another file version",
                    safe_message="文件交付幂等绑定冲突",
                    error_code="file_delivery_idempotency_conflict",
                )
            binding = self.exact_binding(event.id)
            if binding is None:
                raise NonRetryableExecutionError(
                    "File Delivery binding disappeared after enqueue",
                    safe_message="文件交付绑定无效",
                    error_code="file_delivery_binding_invalid",
                )
            return {
                "delivery_id": event.id,
                "status": str(binding["status"]),
            }

    def exact_binding(self, delivery_id: str) -> dict[str, Any] | None:
        return self.repository.database.execute_one(
            """
            select delivery_kind, file_id, file_version_id, file_content_sha256,
                   principal_user_id, session_id, application_publication_id,
                   agent_publication_id, job_id, status
              from delivery_outbox where id = ? and delivery_kind = 'FILE_VERSION'
            """,
            (delivery_id,),
        )

    def retain_delivered_version(self, *, delivery_id: str) -> None:
        binding = self.exact_binding(delivery_id)
        if binding is None:
            return
        existing = self.repository.database.execute_one(
            """
            select id from file_retention_fact
             where version_id = ? and reason = 'DELIVERED' and source_id = ?
            """,
            (binding["file_version_id"], delivery_id),
        )
        if existing is not None:
            return
        starts_at = datetime.now(UTC)
        self.repository.add_retention(
            version_id=str(binding["file_version_id"]),
            reason=RetentionReason.DELIVERED,
            source_id=delivery_id,
            starts_at=starts_at.isoformat(),
            expires_at=(starts_at + timedelta(days=360)).isoformat(),
            retention_days=360,
        )
