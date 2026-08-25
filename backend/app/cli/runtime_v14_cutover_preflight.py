from __future__ import annotations

import json

from app.modules.agent.application.runtime_v14_cutover import (
    RuntimeV14CutoverPreflight,
)
from app.modules.message_bus.infrastructure.rabbitmq_topology import (
    inspect_agent_job_topology_read_only,
)
from app.shared.config import load_settings
from app.shared.database import Database


def main() -> int:
    settings = load_settings()
    database = Database(settings.database_dsn)
    try:
        queue_facts = inspect_agent_job_topology_read_only(
            settings.rabbitmq_url,
            settings.queue,
        )
        report = RuntimeV14CutoverPreflight(database).run(queue_facts)
    except Exception:
        print(
            "RUNTIME_V14_CUTOVER_PREFLIGHT_FAILED: "
            "database, schema ledger, or exact queue facts are unavailable"
        )
        return 1
    finally:
        database.close()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
