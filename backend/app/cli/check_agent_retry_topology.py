from __future__ import annotations

import json

from app.modules.message_bus.infrastructure.rabbitmq_topology import (
    inspect_agent_job_topology,
)
from app.shared.config import load_settings


def main() -> None:
    settings = load_settings()
    report = inspect_agent_job_topology(settings.rabbitmq_url, settings.queue)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
