"""Read-only gate before the coordinated Runtime pool release cutover."""

from __future__ import annotations

import json
from typing import Any

from app.shared.config import load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def inspect(database: Database, queues: dict[str, dict[str, int]]) -> dict[str, Any]:
    head = SchemaHeadValidator(database, default_migrations_dir()).require_current_or_previous(
        allowed_previous_heads=frozenset({"146"}),
    )
    row = database.execute_one(
        "select count(*) as n from agent_job where status not in ('SUCCEEDED','FAILED','TIMEOUT')"
    )
    active = int(row["n"]) if row else 0
    return {
        "mode": "read-only",
        "schema_head": head,
        "nonterminal_jobs": active,
        "queues": queues,
        "status": "blocked"
        if active or any(any(fact.values()) for fact in queues.values())
        else "ready",
        "scope": "Database and broker only; operators must also verify old containers have stopped",
    }


def main() -> int:
    import pika

    settings = load_settings()
    database = Database(settings.database_dsn)
    connection = None
    try:
        parameters = pika.URLParameters(settings.rabbitmq_url)
        parameters.socket_timeout = 5
        parameters.blocked_connection_timeout = 5
        connection = pika.BlockingConnection(parameters)
        queues = {}
        for label, name in (
            ("job", settings.queue.job_queue),
            ("retry", settings.queue.retry_queue),
            ("legacy_retry", settings.queue.legacy_retry_queue),
        ):
            channel = connection.channel()
            try:
                method = channel.queue_declare(queue=name, passive=True).method
                queues[label] = {
                    "messages": int(method.message_count),
                    "consumers": int(method.consumer_count),
                }
            except pika.exceptions.ChannelClosedByBroker as exc:
                if exc.reply_code != 404:
                    raise
                queues[label] = {"messages": 0, "consumers": 0}
            finally:
                if channel.is_open:
                    channel.close()
        report = inspect(database, queues)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["status"] == "ready" else 2
    except Exception:
        # Connection errors can contain DSNs. Print no exception text.
        print(json.dumps({"status": "blocked", "reason": "database_schema_or_broker_unavailable"}))
        return 1
    finally:
        database.close()
        if connection is not None and connection.is_open:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
