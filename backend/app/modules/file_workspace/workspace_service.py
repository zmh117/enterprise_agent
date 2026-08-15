from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.modules.file_workspace.domain import (
    FileOwner,
    RetentionPeriod,
    WorkspaceStatus,
)
from app.modules.file_workspace.lifecycle import task_workspace_expiry_iso
from app.modules.file_workspace.repository import FileWorkspaceRepository


class TaskWorkspaceService:
    def __init__(self, repository: FileWorkspaceRepository) -> None:
        self.repository = repository

    def resolve_for_request(
        self,
        *,
        tenant_id: str,
        session_id: str,
        owner: FileOwner,
        publication_id: str,
        retention_period: RetentionPeriod,
        actor_id: str,
        has_file_input: bool,
        requests_file_output: bool,
        start_new_task: bool = False,
        end_current_task: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        created_at = now or datetime.now(UTC)
        active = self.repository.get_active_workspace(session_id)
        if active is not None and datetime.fromisoformat(
            str(active["expires_at"])
        ) <= created_at.astimezone(datetime.fromisoformat(str(active["expires_at"])).tzinfo):
            self.repository.transition_workspace(
                str(active["id"]), WorkspaceStatus.EXPIRED, at=created_at.isoformat()
            )
            active = None
        if active is not None and (start_new_task or end_current_task):
            self.repository.transition_workspace(
                str(active["id"]), WorkspaceStatus.CLOSED, at=created_at.isoformat()
            )
            active = None
        needs_files = has_file_input or requests_file_output
        if not needs_files:
            return None if active is None or end_current_task else active
        if active is not None:
            return active
        workspace_id = f"task_workspace_{uuid.uuid4().hex}"
        return self.repository.create_workspace(
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            session_id=session_id,
            owner=owner,
            publication_id=publication_id,
            retention_period=retention_period,
            expires_at=task_workspace_expiry_iso(created_at, retention_period),
            actor_id=actor_id,
        )
