from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


_ALLOWED_QUEUE_FACTS = (
    "job_queue",
    "retry_queue",
    "legacy_retry_queue",
    "dead_queue",
)


class RuntimeV14CutoverPreflight:
    """Read-only safety gate for the one-time Runtime protocol 1.4 cutover."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def run(self, queue_facts: Mapping[str, object]) -> dict[str, Any]:
        schema_head = SchemaHeadValidator(
            self.database,
            default_migrations_dir(),
        ).require_current_or_previous(allowed_previous_heads=frozenset({"119"}))
        database_counts = {
            "protocol_v13_nonterminal_jobs": self._count(
                """
                select count(*) as count
                  from agent_job
                 where agent_runtime_protocol_version = '1.3'
                   and status not in ('SUCCEEDED', 'FAILED', 'TIMEOUT')
                """
            ),
            "protocol_v13_dispatch_outbox_nonterminal": self._count(
                """
                select count(*) as count
                  from job_dispatch_outbox outbox
                  join agent_job job on job.id = outbox.job_id
                 where job.agent_runtime_protocol_version = '1.3'
                   and outbox.status not in ('PUBLISHED', 'DEAD')
                """
            ),
            "protocol_v13_delivery_outbox_nonterminal": self._count(
                """
                select count(*) as count
                  from delivery_outbox outbox
                  join agent_job job on job.id = outbox.job_id
                 where job.agent_runtime_protocol_version = '1.3'
                   and outbox.status not in ('SUCCEEDED', 'FAILED', 'DEAD', 'SKIPPED')
                """
            ),
        }
        queues = {
            label: self._safe_queue_fact(queue_facts.get(label)) for label in _ALLOWED_QUEUE_FACTS
        }
        blocking = any(database_counts.values()) or any(
            fact["messages"] != 0 or fact["consumers"] != 0 for fact in queues.values()
        )
        return {
            "mode": "read-only",
            "target_protocol_version": "1.4",
            "schema_head": schema_head,
            "database": database_counts,
            "queues": queues,
            "status": "blocked" if blocking else "ready",
        }

    def _count(self, query: str) -> int:
        row = self.database.execute_one(query)
        return int(row["count"]) if row is not None else 0

    @staticmethod
    def _safe_queue_fact(value: object | None) -> dict[str, object]:
        if value is None:
            raise ValueError("Runtime 1.4 cutover queue fact is missing")
        if not isinstance(value, Mapping):
            raise ValueError("Runtime 1.4 cutover queue fact is invalid")
        exists = value.get("exists")
        messages = value.get("messages")
        consumers = value.get("consumers")
        if not isinstance(exists, bool):
            raise ValueError("Runtime 1.4 cutover queue existence fact is invalid")
        if not isinstance(messages, int) or isinstance(messages, bool) or messages < 0:
            raise ValueError("Runtime 1.4 cutover queue message count is invalid")
        if not isinstance(consumers, int) or isinstance(consumers, bool) or consumers < 0:
            raise ValueError("Runtime 1.4 cutover queue consumer count is invalid")
        return {
            "exists": exists,
            "messages": messages,
            "consumers": consumers,
        }
