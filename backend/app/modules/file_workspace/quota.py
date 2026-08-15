from __future__ import annotations

from dataclasses import dataclass

from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError


MAX_WORKSPACE_FILES = 20
MAX_TEMPORARY_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class WorkspaceQuotaUsage:
    file_count: int
    temporary_bytes: int


class WorkspaceQuotaService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def usage(self, workspace_id: str, *, now: str) -> WorkspaceQuotaUsage:
        count = self.database.execute_one(
            """
            select count(*) as value from task_workspace_file
             where workspace_id = ? and status = 'ACTIVE'
            """,
            (workspace_id,),
        )
        temporary = self.database.execute_one(
            """
            select coalesce(sum(size_bytes), 0) as value
              from (
                select distinct v.id, v.size_bytes
                  from managed_file_version v
                  join task_workspace_file wf on wf.file_id = v.file_id
                 where wf.workspace_id = ? and wf.status = 'ACTIVE'
                   and v.status in ('AVAILABLE', 'CONFLICT')
                   and not exists (
                     select 1 from file_retention_fact r
                      where r.version_id = v.id and r.expires_at > ?
                   )
                union
                select distinct v.id, v.size_bytes
                  from managed_file_version v
                  join file_conflict_candidate c on c.candidate_version_id = v.id
                  join file_commit_intent i on i.id = c.commit_intent_id
                 where i.workspace_id = ? and c.status = 'OPEN'
                   and v.status = 'CONFLICT'
              ) temporary_versions
            """,
            (workspace_id, now, workspace_id),
        )
        return WorkspaceQuotaUsage(
            int((count or {}).get("value") or 0),
            int((temporary or {}).get("value") or 0),
        )

    def require_commit_capacity(
        self,
        *,
        workspace_id: str,
        incoming_bytes: int,
        creates_logical_file: bool,
        now: str,
    ) -> WorkspaceQuotaUsage:
        if incoming_bytes < 0:
            self._deny("file_size_invalid", "文件大小无效")
        usage = self.usage(workspace_id, now=now)
        next_count = usage.file_count + int(creates_logical_file)
        if next_count > MAX_WORKSPACE_FILES:
            self._deny("workspace_file_limit_exceeded", "每个工作区最多包含 20 个文件")
        if usage.temporary_bytes + incoming_bytes > MAX_TEMPORARY_BYTES:
            self._deny("workspace_quota_exceeded", "工作区临时文件已达到 100 MiB 上限")
        return usage

    @staticmethod
    def _deny(code: str, message: str) -> None:
        raise NonRetryableExecutionError(
            "Workspace quota rejected the commit",
            safe_message=message,
            error_code=code,
        )
